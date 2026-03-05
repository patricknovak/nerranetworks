#!/usr/bin/env python3
"""
Fascinating Frontiers – FULL AUTO X + PODCAST MACHINE
Daily Space & Astronomy News Digest (Patrick in Vancouver)
Auto-published to X — December 2025+

.. deprecated::
    This legacy script is no longer used in production.
    All shows now run via ``python run_show.py fascinating_frontiers``.
    Retained for reference only — do not add new features here.
"""

import os
import sys
import logging
import datetime
import subprocess
import requests
import tempfile
import html
import json
import re
import random
import xml.etree.ElementTree as ET
from feedgen.feed import FeedGenerator
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from difflib import SequenceMatcher
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
import feedparser
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from urllib.parse import quote

# --- engine/ shared modules ---
from engine.utils import (
    env_float, env_int, env_bool,
    number_to_words as _engine_number_to_words,
    calculate_similarity as _engine_calculate_similarity,
    remove_similar_items as _engine_remove_similar_items,
    SCIENCE_CONTENT_KEYWORDS,
    is_science_related,
)
from engine.audio import get_audio_duration, format_duration as _engine_format_duration, normalize_voice as _engine_normalize_voice
from engine.publisher import (
    update_rss_feed as _engine_update_rss_feed,
    get_next_episode_number as _engine_get_next_episode_number,
    save_summary_to_github_pages as _engine_save_summary,
    generate_episode_thumbnail as _engine_generate_thumbnail,
    format_digest_for_x as _engine_format_digest_for_x,
    post_to_x as _engine_post_to_x,
)
from engine.tracking import create_tracker, record_llm_usage, record_tts_usage, record_x_post, save_usage
from engine.content_tracker import ContentTracker, FF_SECTION_PATTERNS
from engine.utils import deduplicate_by_entity, is_low_news_day

# ========================== LOGGING ==========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# ========================== CONFIGURATION ==========================
# Defaults (overridable via environment variables)
TEST_MODE = False
ENABLE_X_POSTING = True
ENABLE_GITHUB_SUMMARIES = True
ENABLE_PODCAST = True
ENABLE_LINK_VALIDATION = False


# ========================== NUMBER TO WORDS CONVERTER ==========================
number_to_words = _engine_number_to_words

# ========================== PRONUNCIATION FIXER – USING SHARED MODULE ==========================

def fix_pronunciation(text: str) -> str:
    """Prepare Fascinating Frontiers script text for ElevenLabs TTS.

    Delegates to the shared pronunciation module (assets/pronunciation.py)
    which handles text cleanup, number/date/time expansion, acronyms,
    unit abbreviations, scientific designations, and more.
    """
    from assets.pronunciation import prepare_text_for_tts
    return prepare_text_for_tts(text)

def generate_episode_thumbnail(base_image_path, episode_num, date_str, output_path):
    return _engine_generate_thumbnail(Path(base_image_path), episode_num, date_str, Path(output_path))

# ========================== PATHS & ENV ==========================
script_dir = Path(__file__).resolve().parent        # → .../digests
project_root = script_dir.parent                      # → .../tesla_shorts_time
env_path = project_root / ".env"

if not env_path.exists():
    raise FileNotFoundError(f".env not found at {env_path}")

load_dotenv(dotenv_path=env_path)

# Optional env overrides for feature flags (useful for local testing)
TEST_MODE = env_bool("TEST_MODE", TEST_MODE)
ENABLE_X_POSTING = env_bool("ENABLE_X_POSTING", ENABLE_X_POSTING)
ENABLE_PODCAST = env_bool("ENABLE_PODCAST", ENABLE_PODCAST)
ENABLE_GITHUB_SUMMARIES = env_bool("ENABLE_GITHUB_SUMMARIES", ENABLE_GITHUB_SUMMARIES)

if TEST_MODE:
    ENABLE_X_POSTING = env_bool("ENABLE_X_POSTING", False)
    ENABLE_PODCAST = env_bool("ENABLE_PODCAST", False)

# Required keys
required = ["GROK_API_KEY"]

if ENABLE_PODCAST and not TEST_MODE:
    required.append("ELEVENLABS_API_KEY")
if ENABLE_X_POSTING:
    required.extend([
        "PLANETTERRIAN_X_CONSUMER_KEY",
        "PLANETTERRIAN_X_CONSUMER_SECRET",
        "PLANETTERRIAN_X_ACCESS_TOKEN",
        "PLANETTERRIAN_X_ACCESS_TOKEN_SECRET",
        "PLANETTERRIAN_X_BEARER_TOKEN"
    ])
for var in required:
    if not os.getenv(var):
        raise OSError(f"Missing {var} in .env")


# ========================== DATE ==========================
# Get current date and time in PST
pst_tz = ZoneInfo("America/Los_Angeles")
now_pst = datetime.datetime.now(pst_tz)
today_str = now_pst.strftime("%B %d, %Y at %I:%M %p PST")
yesterday_iso = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
seven_days_ago_iso = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

# Folders - use absolute paths
digests_dir = project_root / "digests" / "fascinating_frontiers"
digests_dir.mkdir(exist_ok=True, parents=True)

def get_next_episode_number(rss_path, digests_dir):
    return _engine_get_next_episode_number(
        rss_path, digests_dir, mp3_glob_pattern="Fascinating_Frontiers_Ep*.mp3",
    )

# Get the next episode number
rss_path = project_root / "fascinating_frontiers_podcast.rss"
episode_num = get_next_episode_number(rss_path, digests_dir)

# ========================== CREDIT TRACKING ==========================
credit_usage = create_tracker("Fascinating Frontiers", episode_num)

def save_credit_usage(usage_data, output_dir):
    """Thin wrapper around engine.tracking.save_usage."""
    save_usage(usage_data, output_dir)

def save_summary_to_github_pages(
    summary_text, output_dir, podcast_name="space", *,
    episode_num=None, episode_title=None, audio_url=None, rss_url=None,
):
    json_path = project_root / "digests" / "fascinating_frontiers" / f"summaries_{podcast_name}.json"
    return _engine_save_summary(
        summary_text, json_path, podcast_name,
        episode_num=episode_num, episode_title=episode_title,
        audio_url=audio_url, rss_url=rss_url,
    )

tmp_dir = Path(tempfile.gettempdir()) / "tts"
tmp_dir.mkdir(exist_ok=True, parents=True)

# ========================== CLIENTS ==========================
# Grok client with timeout settings
client = OpenAI(
    api_key=os.getenv("GROK_API_KEY"), 
    base_url="https://api.x.ai/v1",
    timeout=300.0  # 5 minute timeout for API calls
)
ELEVEN_API = "https://api.elevenlabs.io/v1"
ELEVEN_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVEN_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "dTrBzPvD2GpAqkk1MUzA").strip()

_env_float = env_float
_env_int = env_int
_env_bool = env_bool

# ========================== STEP 1: FETCH SPACE & ASTRONOMY NEWS FROM RSS FEEDS ==========================
logging.info("Step 1: Fetching space and astronomy news from RSS feeds for the last 48 hours...")

calculate_similarity = _engine_calculate_similarity
remove_similar_items = _engine_remove_similar_items

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.RequestException, requests.Timeout))
)
def fetch_space_news():
    """Fetch space and astronomy news from RSS feeds for the last 48 hours."""
    import feedparser
    
    # Space and astronomy RSS feeds
    rss_feeds = [
        # NASA Official Feeds
        "https://www.nasa.gov/rss/dyn/breaking_news.rss",
        "https://www.nasa.gov/rss/dyn/educationnews.rss",
        "https://www.nasa.gov/rss/dyn/image_of_the_day.rss",
        "https://www.nasa.gov/rss/dyn/centers/kennedy/news/releases/current.rss",
        "https://www.nasa.gov/rss/dyn/centers/jpl/news/releases/current.rss",
        "https://www.nasa.gov/rss/dyn/centers/goddard/news/releases/current.rss",
        
        # Space News Outlets
        "https://www.space.com/feeds/all",
        "https://www.space.com/rss",
        "https://www.spaceflightnow.com/feed/",
        "https://spacenews.com/feed/",
        "https://www.space.com/news/feed",
        
        # Astronomy & Science
        "https://www.astronomy.com/feed/",
        "https://www.skyandtelescope.com/feed/",
        "https://www.universetoday.com/feed/",
        "https://www.space.com/science-astronomy/feed",
        "https://www.space.com/spaceflight/feed",
        
        # European Space Agency
        "https://www.esa.int/rssfeed/ESA",
        "https://www.esa.int/rssfeed/Our_Activities",
        "https://www.esa.int/rssfeed/Space_Science",
        
        # Other Space Agencies
        "https://www.roscosmos.ru/feed/",
        "https://global.jaxa.jp/rss/",
        
        # Space Industry
        "https://www.spacex.com/news.xml",
        "https://www.blueorigin.com/news/rss",
        "https://www.nasa.gov/rss/dyn/commercial_crew_program_updates.rss",
        
        # Science Journals (space-focused)
        "https://www.nature.com/nature/astronomy.rss",
        "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science",
        
        # Space Technology
        "https://www.space.com/technology/feed",
        "https://www.space.com/launches/feed",
    ]
    
    # Calculate cutoff time (last 48 hours)
    cutoff_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)
    
    all_articles = []
    raw_articles = []
    
    # Space/astronomy keywords to filter articles
    space_keywords = [
        "space", "astronomy", "astronaut", "cosmic", "galaxy", "galaxies",
        "planet", "planets", "exoplanet", "exoplanets", "solar system",
        "mars", "moon", "lunar", "asteroid", "comet", "meteor",
        "telescope", "observatory", "hubble", "james webb", "jwst",
        "nasa", "esa", "spacex", "rocket", "launch", "mission",
        "satellite", "spacecraft", "rover", "lander", "orbiter",
        "nebula", "star", "stars", "supernova", "black hole",
        "iss", "international space station", "space station",
        "spaceflight", "space travel", "space exploration",
        "astrophysics", "cosmology", "universe", "cosmos"
    ]
    
    logging.info(f"Fetching space/astronomy news from {len(rss_feeds)} RSS feeds...")
    
    # OPTIMIZED: Parallel RSS feed fetching
    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    HTTP_TIMEOUT_SECONDS = 10
    
    problematic_feeds = set()
    problematic_feeds_lock = Lock()
    
    def get_source_name(feed_url: str, feed_title: str = "Unknown") -> str:
        """Map feed URL to source name."""
        source_name = feed_title
        # Map common feed sources
        if "nasa.gov" in feed_url.lower():
            if "kennedy" in feed_url.lower():
                source_name = "NASA Kennedy Space Center"
            elif "jpl" in feed_url.lower():
                source_name = "NASA JPL"
            elif "goddard" in feed_url.lower():
                source_name = "NASA Goddard"
            else:
                source_name = "NASA"
        elif "space.com" in feed_url.lower():
            source_name = "Space.com"
        elif "spaceflightnow" in feed_url.lower():
            source_name = "Spaceflight Now"
        elif "spacenews.com" in feed_url.lower():
            source_name = "SpaceNews"
        elif "astronomy.com" in feed_url.lower():
            source_name = "Astronomy Magazine"
        elif "skyandtelescope" in feed_url.lower():
            source_name = "Sky & Telescope"
        elif "universetoday" in feed_url.lower():
            source_name = "Universe Today"
        elif "esa.int" in feed_url.lower():
            source_name = "European Space Agency"
        elif "roscosmos" in feed_url.lower():
            source_name = "Roscosmos"
        elif "jaxa.jp" in feed_url.lower():
            source_name = "JAXA"
        elif "spacex.com" in feed_url.lower():
            source_name = "SpaceX"
        elif "blueorigin" in feed_url.lower():
            source_name = "Blue Origin"
        elif "nature.com" in feed_url.lower():
            if "nbt" in feed_url.lower():
                source_name = "Nature Biotechnology"
            elif "nm" in feed_url.lower() and "nmeth" not in feed_url.lower():
                source_name = "Nature Medicine"
            elif "nmeth" in feed_url.lower():
                source_name = "Nature Methods"
            else:
                source_name = "Nature"
        elif "science.org" in feed_url.lower():
            source_name = "Science"
        elif "cell.com" in feed_url.lower():
            if "cell-metabolism" in feed_url.lower():
                source_name = "Cell Metabolism"
            elif "cell-stem-cell" in feed_url.lower():
                source_name = "Cell Stem Cell"
            else:
                source_name = "Cell"
        elif "newscientist" in feed_url.lower():
            source_name = "New Scientist"
        elif "scientificamerican" in feed_url.lower():
            source_name = "Scientific American"
        elif "sciencedaily" in feed_url.lower():
            source_name = "Science Daily"
        elif "sciencenews" in feed_url.lower():
            source_name = "Science News"
        elif "quantamagazine" in feed_url.lower():
            source_name = "Quanta Magazine"
        elif "technologyreview" in feed_url.lower():
            source_name = "MIT Technology Review"
        elif "the-scientist" in feed_url.lower():
            source_name = "The Scientist"
        elif "longevity" in feed_url.lower():
            source_name = "Longevity Technology"
        elif "lifespan.io" in feed_url.lower():
            source_name = "Lifespan.io"
        elif "aging-us.com" in feed_url.lower():
            source_name = "Aging (Albany NY)"
        elif "frontiersin.org" in feed_url.lower() and "aging" in feed_url.lower():
            source_name = "Frontiers in Aging"
        elif "healthline" in feed_url.lower():
            source_name = "Healthline"
        elif "medicalnewstoday" in feed_url.lower():
            source_name = "Medical News Today"
        elif "webmd" in feed_url.lower():
            source_name = "WebMD"
        elif "medscape" in feed_url.lower():
            source_name = "Medscape"
        elif "statnews" in feed_url.lower():
            source_name = "STAT News"
        elif "hopkinsmedicine" in feed_url.lower():
            source_name = "Johns Hopkins Medicine"
        elif "nih.gov" in feed_url.lower():
            source_name = "NIH"
        elif "cdc.gov" in feed_url.lower():
            source_name = "CDC"
        elif "who.int" in feed_url.lower():
            source_name = "WHO"
        elif "fda.gov" in feed_url.lower():
            source_name = "FDA"
        elif "hhs.gov" in feed_url.lower():
            source_name = "HHS"
        elif "thelancet" in feed_url.lower():
            source_name = "The Lancet"
        elif "jamanetwork" in feed_url.lower() or "jama" in feed_url.lower():
            source_name = "JAMA"
        elif "nejm" in feed_url.lower():
            source_name = "New England Journal of Medicine"
        elif "bmj.com" in feed_url.lower():
            source_name = "BMJ"
        elif "harvard" in feed_url.lower():
            if "health" in feed_url.lower():
                source_name = "Harvard Health"
            else:
                source_name = "Harvard University"
        elif "mit.edu" in feed_url.lower():
            source_name = "MIT"
        elif "stanford" in feed_url.lower():
            source_name = "Stanford University"
        elif "mayo" in feed_url.lower():
            source_name = "Mayo Clinic"
        elif "clevelandclinic" in feed_url.lower():
            source_name = "Cleveland Clinic"
        elif "nutrition.org" in feed_url.lower():
            source_name = "American Society for Nutrition"
        elif "eatright" in feed_url.lower():
            source_name = "Academy of Nutrition and Dietetics"
        elif "dana.org" in feed_url.lower():
            source_name = "Dana Foundation"
        elif "brainfacts" in feed_url.lower():
            source_name = "BrainFacts.org"
        elif "alz.org" in feed_url.lower():
            source_name = "Alzheimer's Association"
        elif "apha.org" in feed_url.lower():
            source_name = "American Public Health Association"
        elif "healthaffairs" in feed_url.lower():
            source_name = "Health Affairs"
        
        return source_name
    
    def fetch_single_feed(feed_url: str):
        """Fetch and parse a single RSS feed. Returns (feed_url, articles, source_name) or None on error."""
        source_name = "Unknown"
        try:
            response = requests.get(
                feed_url,
                headers=DEFAULT_HEADERS,
                timeout=HTTP_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            
            if feed.bozo and feed.bozo_exception:
                with problematic_feeds_lock:
                    if feed_url not in problematic_feeds:
                        problematic_feeds.add(feed_url)
                        error_msg = str(feed.bozo_exception)
                        if "not well-formed" in error_msg or "syntax error" in error_msg:
                            logging.debug(f"RSS feed has malformed XML (will skip): {feed_url}")
                        else:
                            logging.debug(f"RSS feed parsing issue (will skip): {feed_url} - {error_msg[:100]}")
                return None
            
            feed_title = feed.feed.get("title", "Unknown")
            source_name = get_source_name(feed_url, feed_title)
            
            feed_articles = []
            for entry in feed.entries:
                published_time = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        published_time = datetime.datetime(*entry.published_parsed[:6], tzinfo=datetime.timezone.utc)
                    except (ValueError, TypeError):
                        pass
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    try:
                        published_time = datetime.datetime(*entry.updated_parsed[:6], tzinfo=datetime.timezone.utc)
                    except (ValueError, TypeError):
                        pass
                
                if published_time and published_time < cutoff_time:
                    continue
                
                title = entry.get("title", "").strip()
                description = entry.get("description", "").strip() or entry.get("summary", "").strip()
                link = entry.get("link", "").strip()
                
                if not title or not link:
                    continue
                
                # Check if article is space/astronomy-related
                title_desc_lower = (title + " " + description).lower()
                if not any(keyword in title_desc_lower for keyword in space_keywords):
                    continue
                
                article = {
                    "title": title,
                    "description": description,
                    "url": link,
                    "source": source_name,
                    "publishedAt": published_time.isoformat() if published_time else datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "author": entry.get("author", "")
                }
                
                feed_articles.append(article)
            
            return (feed_url, feed_articles, source_name)
        
        except requests.RequestException as e:
            with problematic_feeds_lock:
                if feed_url not in problematic_feeds:
                    problematic_feeds.add(feed_url)
                    logging.debug(f"Network error fetching RSS feed (will skip): {feed_url} - {type(e).__name__}")
            return None
        except Exception as e:
            error_str = str(e)
            if any(keyword in error_str.lower() for keyword in ["not well-formed", "syntax error", "mismatched tag", "invalid token", "404", "not found", "closed connection"]):
                with problematic_feeds_lock:
                    if feed_url not in problematic_feeds:
                        problematic_feeds.add(feed_url)
                        logging.debug(f"RSS feed error (will skip): {feed_url} - {type(e).__name__}")
            else:
                logging.warning(f"Failed to fetch RSS feed {feed_url}: {e}")
            return None
    
    # Fetch feeds in parallel (max 10 concurrent requests to avoid overwhelming servers)
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_feed = {executor.submit(fetch_single_feed, feed_url): feed_url for feed_url in rss_feeds}
        for future in as_completed(future_to_feed):
            result = future.result()
            if result:
                feed_url, feed_articles, source_name = result
                logging.info(f"Fetched {len(feed_articles)} articles from {source_name}")
                all_articles.extend(feed_articles)
                raw_articles.extend(feed_articles)
    
    logging.info(f"Fetched {len(all_articles)} total articles from RSS feeds")
    if problematic_feeds:
        logging.debug(f"Skipped {len(problematic_feeds)} problematic RSS feed(s) (check debug logs for details)")
    
    if not all_articles:
        logging.warning("No articles found from RSS feeds")
        return [], []
    
    # Remove similar/duplicate articles
    before_dedup = len(all_articles)
    formatted_articles = remove_similar_items(
        all_articles,
        similarity_threshold=0.85,
        get_text_func=lambda x: f"{x.get('title', '')} {x.get('description', '')}"
    )
    after_dedup = len(formatted_articles)
    if before_dedup != after_dedup:
        logging.info(f"Removed {before_dedup - after_dedup} similar/duplicate news articles")
    
    # Sort by published date (newest first)
    formatted_articles.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)
    
    logging.info(f"Filtered to {len(formatted_articles)} unique space/astronomy news articles")

    # Select the best news from the last 48 hours
    selected_articles = select_best_space_news(formatted_articles, max_articles=12)

    logging.info(f"Selected {len(selected_articles)} best space/astronomy news articles from 48-hour collection")
    return selected_articles, raw_articles

def select_best_space_news(articles, max_articles=12):
    """
    Select the best space/astronomy news from the 48-hour collection.
    Prioritizes high-quality sources, recent articles, and important missions/events.
    """
    if not articles:
        return []

    # Source quality scores (higher = better)
    source_scores = {
        "NASA": 10, "ESA": 10, "SpaceX": 9, "Blue Origin": 8,
        "Space News": 9, "Space.com": 8, "Ars Technica": 8,
        "Spaceflight Now": 8, "Universe Today": 7, "Sky & Telescope": 7,
        "Astronomy Magazine": 7, "New Scientist": 6,
        "BBC Science": 7, "Scientific American": 6
    }

    # Mission/event importance scores (higher = more important)
    important_keywords = {
        "launch": 4, "mission": 3, "satellite": 3, "rocket": 3,
        "mars": 5, "moon": 4, "lunar": 4, "artemis": 5,
        "starship": 4, "falcon": 3, "crew dragon": 4,
        "iss": 4, "international space station": 4,
        "telescope": 4, "james webb": 5, "hubble": 4,
        "discovery": 4, "breakthrough": 4, "first": 4,
        "asteroid": 3, "comet": 3, "exoplanet": 4,
        "black hole": 4, "supernova": 3, "galaxy": 3,
        "alien": 3, "life": 3, "extraterrestrial": 3
    }

    scored_articles = []

    for article in articles:
        score = 0

        # Source quality score
        source = article.get("source", "")
        score += source_scores.get(source, 3)  # Default score of 3 for unknown sources

        # Recency bonus (newer articles get higher scores)
        try:
            published = datetime.datetime.fromisoformat(article.get("publishedAt", "").replace('Z', '+00:00'))
            hours_old = (datetime.datetime.now(datetime.timezone.utc) - published).total_seconds() / 3600
            if hours_old < 12:
                score += 3  # Very recent
            elif hours_old < 24:
                score += 2  # Recent
            elif hours_old < 48:
                score += 1  # Within 2 days
        except:
            pass  # If we can't parse the date, no recency bonus

        # Mission/event importance score
        text = f"{article.get('title', '')} {article.get('description', '')}".lower()
        for keyword, bonus in important_keywords.items():
            if keyword.lower() in text:
                score += bonus
                break  # Only count the first matching keyword

        # Title quality bonus (articles with compelling titles)
        title = article.get('title', '').lower()
        if any(word in title for word in ['launch', 'mission', 'discovery', 'first', 'historic', 'breakthrough']):
            score += 1

        scored_articles.append((score, article))

    # Sort by score (highest first) and return top articles
    scored_articles.sort(key=lambda x: x[0], reverse=True)
    selected = [article for score, article in scored_articles[:max_articles]]

    # Log the selection
    logging.info(f"Selected top {len(selected)} articles from {len(articles)} candidates:")
    for i, article in enumerate(selected[:5], 1):  # Log top 5
        source = article.get("source", "Unknown")
        title = article.get("title", "")[:60]
        logging.info(f"  {i}. {source}: {title}...")

    return selected

space_news, raw_news_articles = fetch_space_news()

# --- Cross-episode content tracking ---
_ff_tracker = ContentTracker("fascinating_frontiers", digests_dir)
_ff_tracker.load()

# Entity-level dedup: cap articles to max 2 per primary entity (e.g. Crew-12)
space_news = deduplicate_by_entity(space_news, max_per_entity=2)

# Cross-episode dedup: drop articles too similar to recently covered stories
space_news = _ff_tracker.filter_recent_articles(space_news, similarity_threshold=0.65, days=3)

logging.info(f"After cross-episode + entity dedup: {len(space_news)} articles remain")

# ========================== STEP 2: FETCH TOP X POSTS FROM X API ==========================
# X POSTS DISABLED - Only using news articles
# Initialize variables
top_x_posts = []
raw_x_posts = []

# Science, longevity, and health X accounts to follow
TRUSTED_USERNAMES = [
    # Science & Research
    "Nature", "sciencemagazine", "newscientist", "sciam",
    # Longevity & Health
    "longevitytech", "LifespanIO", "longevityfund", "DavidSinclairPhD",
    "peterattiamd", "RhondaPatrick", "BryanJohnson",
    # Health & Medicine
    "WHO", "CDCgov", "NIH", "NEJM", "TheLancet",
    # Science Communicators
    "neiltyson", "BillNye", "sciam", "sciencemagazine"
]

# SCIENCE_CONTENT_KEYWORDS and is_science_related imported from engine.utils

def fetch_x_posts_from_trusted_accounts() -> tuple[List[Dict], List[Dict]]:
    """
    Fetch science/longevity/health posts from trusted X accounts using the X API.
    Prioritizes original posts (excludes retweets).
    """
    logging.info("Fetching science/longevity/health posts from trusted accounts...")
    
    all_posts = []
    raw_posts_data = []
    
    try:
        import tweepy
        
        x_client = tweepy.Client(
            bearer_token=os.getenv("PLANETTERRIAN_X_BEARER_TOKEN"),
            wait_on_rate_limit=True
        )
        
        # Build query for science/longevity/health content
        science_keywords = "(science OR longevity OR health OR research OR discovery OR breakthrough OR medicine OR biotechnology)"
        query = f"{science_keywords} from:{' OR from:'.join(TRUSTED_USERNAMES[:10])} -is:retweet lang:en"
        
        # Calculate start time (last 24 hours)
        start_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)).isoformat()
        
        all_tweets = []
        # Track X API search call
        credit_usage["services"]["x_api"]["search_calls"] += 1
        
        response = x_client.search_recent_tweets(
            query=query,
            max_results=100,
            start_time=start_time,
            tweet_fields=['created_at', 'public_metrics', 'author_id', 'text', 'referenced_tweets'],
            user_fields=['username', 'name'],
            expansions=['author_id', 'referenced_tweets.id']
        )
        
        if response.data:
            all_tweets.extend(response.data)
            logging.info(f"First batch: {len(response.data)} tweets")
        
        # Try to get more results if we have a next_token (pagination)
        if hasattr(response, 'meta') and response.meta and 'next_token' in response.meta:
            try:
                # Track X API search call (pagination)
                credit_usage["services"]["x_api"]["search_calls"] += 1
                
                next_response = x_client.search_recent_tweets(
                    query=query,
                    max_results=100,
                    start_time=start_time,
                    next_token=response.meta['next_token'],
                    tweet_fields=['created_at', 'public_metrics', 'author_id', 'text', 'referenced_tweets'],
                    user_fields=['username', 'name'],
                    expansions=['author_id', 'referenced_tweets.id']
                )
                
                if next_response.data:
                    all_tweets.extend(next_response.data)
                    logging.info(f"Second batch: {len(next_response.data)} tweets")
            except Exception as e:
                logging.warning(f"Could not fetch second batch: {e}")
        
        # Process tweets
        users = {}
        if hasattr(response, 'includes') and response.includes and 'users' in response.includes:
            for user in response.includes['users']:
                users[user.id] = user
        
        for post in all_tweets:
            # Skip retweets
            if hasattr(post, 'referenced_tweets') and post.referenced_tweets:
                is_retweet = any(ref.type == 'retweeted' for ref in post.referenced_tweets)
                if is_retweet:
                    continue
            
            # Get author info
            author_id = post.author_id
            author_username = "unknown"
            author_name = "Unknown"
            if author_id in users:
                author_username = users[author_id].username
                author_name = users[author_id].name
            
            # Filter for science-related content
            if not is_science_related(post.text):
                continue
            
            # Calculate engagement score
            metrics = post.public_metrics if hasattr(post, 'public_metrics') else {}
            likes = metrics.get('like_count', 0)
            retweets = metrics.get('retweet_count', 0)
            replies = metrics.get('reply_count', 0)
            engagement = (likes * 1.0) + (retweets * 3.0) + (replies * 1.5)
            
            # Boost engagement for verified/science accounts
            if author_username.lower() in ["nature", "sciencemagazine", "newscientist"]:
                engagement *= 2.0
            
            post_data = {
                "id": post.id,
                "text": post.text,
                "username": author_username,
                "name": author_name,
                "url": f"https://x.com/{author_username}/status/{post.id}",
                "created_at": post.created_at.isoformat() if hasattr(post.created_at, 'isoformat') else str(post.created_at),
                "likes": likes,
                "retweets": retweets,
                "replies": replies,
                "engagement": engagement,
                "final_score": engagement
            }
            
            all_posts.append(post_data)
            raw_posts_data.append(post_data)
        
        logging.info(f"Fetched {len(all_posts)} science/longevity/health posts from X API")
        
    except Exception as e:
        logging.error(f"Error fetching X posts: {e}", exc_info=True)
        logging.warning("Continuing without X posts...")
    
    if not all_posts:
        logging.warning("No X posts found. Possible reasons:")
        logging.warning("    1. No posts in last 24 hours from these accounts")
        logging.warning("    2. Many posts might be retweets (excluded)")
        logging.warning("    3. Posts might not contain explicit science/longevity/health keywords")
    
    # Remove duplicates by ID
    existing_ids = set()
    top_25 = []
    for post in all_posts:
        if post['id'] not in existing_ids:
            existing_ids.add(post['id'])
            top_25.append(post)
    
    # Sort by engagement score
    top_25.sort(key=lambda x: x['final_score'], reverse=True)
    
    logging.info(f"Returning {len(top_25)} best science/longevity/health posts")
    return top_25[:25], raw_posts_data

# X POSTS DISABLED - Skip fetching X posts
# top_x_posts, raw_x_posts = fetch_x_posts_from_trusted_accounts()
logging.info("X posts fetching disabled - using only news articles")

# if len(top_x_posts) < 5:
#     logging.warning(f"⚠️  Only {len(top_x_posts)} X posts were fetched (minimum 5 recommended). Continuing anyway.")

# Save raw data (similar structure to Tesla script)
def save_raw_data_and_generate_html(raw_news, raw_x_posts_data, output_dir: Path):
    # Note: raw_x_posts_data will be empty since X posts are disabled
    """Save raw data to JSON and generate HTML archive."""
    date_str = datetime.date.today().isoformat()
    formatted_date = datetime.date.today().strftime("%B %d, %Y")
    
    raw_data = {
        "date": date_str,
        "rss_feeds": {
            "total_articles": len(raw_news),
            "articles": raw_news
        },
        "x_api": {
            "total_posts": len(raw_x_posts_data),
            "posts": raw_x_posts_data
        }
    }
    
    # Save JSON
    json_path = output_dir / f"raw_data_{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2, ensure_ascii=False)
    
    logging.info(f"Raw data saved to {json_path}")
    
    # Generate HTML (simplified version)
    html_path = output_dir / f"raw_data_{date_str}.html"
    # HTML generation code would go here (similar to Tesla script)
    
    return json_path, html_path

# Save raw data
raw_json_path, raw_html_path = save_raw_data_and_generate_html(
    raw_news_articles, 
    raw_x_posts, 
    digests_dir
)

# ========================== STEP 3: GENERATE X THREAD WITH GROK ==========================
logging.info("Step 3: Generating Fascinating Frontiers digest with Grok...")

# Format news articles for the prompt
news_section = ""
if space_news:
    news_section = "## PRE-FETCHED NEWS ARTICLES (from RSS feeds - last 24 hours):\n\n"
    for i, article in enumerate(space_news[:20], 1):
        news_section += f"{i}. **{article['title']}**\n"
        news_section += f"   Source: {article['source']}\n"
        news_section += f"   Published: {article['publishedAt']}\n"
        if article.get('description'):
            news_section += f"   Description: {article['description'][:200]}...\n"
        news_section += f"   URL: {article['url']}\n\n"
else:
    news_section = "## PRE-FETCHED NEWS ARTICLES: None available\n\n"

# X POSTS DISABLED - No X posts section
x_posts_section = ""

# Generate content tracking summary for the prompt
_ff_article_count = len(space_news) if space_news else 0
_ff_used_content = _ff_tracker.get_summary_for_prompt()

X_PROMPT = f"""
# Fascinating Frontiers - SPACE & ASTRONOMY EDITION
**Date:** {today_str}
🚀 Fascinating Frontiers Podcast: Coming soon to Apple Podcasts
{news_section}

You are an elite space and astronomy news curator producing the daily "Fascinating Frontiers" newsletter. Use ONLY the pre-fetched news articles above. Do NOT hallucinate, invent, or search for new content/URLs—stick to exact provided links. Do NOT include any X posts or Twitter references.

You have {_ff_article_count} quality articles to work with today.

{_ff_used_content}

**BRAND PERSONALITY:**
- Fascinating Frontiers: Daily space and astronomy news digest
- Mission: Bring the wonders of space exploration and astronomy discoveries to everyone
- Values: Curiosity, exploration, scientific accuracy, inspiration
- Tone: Inspirational, awe-inspiring, accessible, exciting, forward-thinking
- Focus: Latest space missions, astronomy discoveries, cosmic phenomena, and space technology breakthroughs

### MANDATORY SELECTION & COUNTS (CRITICAL - FOLLOW EXACTLY)
- **News**: Select the best unique articles from the pre-fetched list. Use up to 15 if available. If fewer than 15 exist, use ALL of them. Each must cover a DIFFERENT story/angle.
- **Curation**: Prefer concrete mission updates, discoveries, research results, and instrument/launch milestones. Avoid "year in review", listicles, awards, or opinion pieces unless you truly cannot fill without them.
- **NO X POSTS**: Do NOT include any X posts, Twitter posts, or social media references. Only use news articles.
- **Diversity Check**: Verify no two items cover the same event, entity, or mission from different sources. Each item must be a genuinely DIFFERENT story.

### FORMATTING (EXACT—USE MARKDOWN AS SHOWN)
# Fascinating Frontiers
**Date:** {today_str}
🚀 **Fascinating Frontiers** - Space & Astronomy News

**Quick scan:** 1 short sentence theme + "If you only read 3 today: #A, #B, #C."

━━━━━━━━━━━━━━━━━━━━
### Top 15 Space & Astronomy Stories
1. **Title (<= 12 words): DD Month YYYY • Source Name**
   2 sentences max. Sentence 1: what happened (specific + concrete). Sentence 2: why it matters for space exploration/astronomy/our understanding of the cosmos. Avoid filler.
   Source: [EXACT URL FROM PRE-FETCHED—no mods]
2. [Repeat format for remaining items; output as many quality items as available up to 15, add a blank line after each item]

━━━━━━━━━━━━━━━━━━━━
### Cosmic Spotlight
Pick ONE item from the Top stories and go deeper (3–5 sentences). Make it vivid but grounded: what it reveals, how we know, and what could come next. IMPORTANT: Choose a DIFFERENT topic area than recent Cosmic Spotlights (avoid Mars if it was featured recently). End with ONE question to invite replies.

━━━━━━━━━━━━━━━━━━━━
### Daily Inspiration
One inspiring quote about space, exploration, astronomy, or the cosmos from a DIFFERENT author than recently used. End with: "Share your thoughts with us!"

[1-2 sentence uplifting sign-off on space exploration, cosmic discoveries, and humanity's journey to the stars. Keep it punchy.]

### TONE & STYLE
- Inspirational, awe-inspiring, accessible, exciting
- Focus on the wonder and significance of space discoveries
- Emphasize exploration, discovery, and humanity's cosmic journey
- Avoid repetitive phrasing like “This matters…” on every item — vary your language
- Be scannable: short sentences, no fluff
- Dates should be accurate PST/PDT; avoid exact HH:MM unless it materially matters

Output today's edition exactly as formatted.
"""

@retry(
    stop=stop_after_attempt(2),  # Reduced from 3 for faster recovery
    wait=wait_exponential(multiplier=1, min=1, max=15),  # Reduced wait times: 1-15s instead of 2-30s
    retry=retry_if_exception_type((Exception,))
)
def generate_digest_with_grok():
    """Generate digest with retry logic"""
    from xai_grok import grok_generate_text

    text, meta = grok_generate_text(
        prompt=X_PROMPT,
        model="grok-4",
        temperature=0.7,
        max_tokens=3500,
        timeout_seconds=300.0,
        enable_web_search=False,
        enable_x_search=False,
    )
    return text, meta

try:
    x_thread, _grok_meta = generate_digest_with_grok()
    
    # Log token usage and cost
    usage = (_grok_meta or {}).get("usage")
    if usage:
        total = getattr(usage, "total_tokens", None)
        prompt_t = getattr(usage, "prompt_tokens", None)
        completion_t = getattr(usage, "completion_tokens", None)
        if total is not None:
            logging.info(f"Grok API - Tokens used: {total} (prompt: {prompt_t}, completion: {completion_t})")
            estimated_cost = (float(total) / 1000000) * 0.01
            logging.info(f"Estimated cost: ${estimated_cost:.4f}")

            # Track credit usage
            credit_usage["services"]["grok_api"]["x_thread_generation"]["prompt_tokens"] = prompt_t
            credit_usage["services"]["grok_api"]["x_thread_generation"]["completion_tokens"] = completion_t
            credit_usage["services"]["grok_api"]["x_thread_generation"]["total_tokens"] = total
            credit_usage["services"]["grok_api"]["x_thread_generation"]["estimated_cost_usd"] = estimated_cost
except Exception as e:
    logging.error(f"Grok API call failed: {e}")
    raise

# Clean Grok footer
lines = []
for line in x_thread.splitlines():
    if line.strip().startswith(("**Sources", "Grok", "I used", "[")):
        break
    lines.append(line)
x_thread = "\n".join(lines).strip()

# Record episode content in the tracker for future cross-episode dedup
_ff_tracker.record_episode(x_thread, FF_SECTION_PATTERNS)
_ff_tracker.save()

# Save X thread
x_path = digests_dir / f"Fascinating_Frontiers_{datetime.date.today():%Y%m%d}.md"
with open(x_path, "w", encoding="utf-8") as f:
    f.write(x_thread)
logging.info(f"X thread saved to {x_path}")

# Format for X posting (remove markdown, clean up) — delegates to engine
format_digest_for_x = _engine_format_digest_for_x

formatted_thread = format_digest_for_x(x_thread)

# ========================== X POSTING (via engine/publisher.post_to_x) ==========================
tweet_id = None
if ENABLE_X_POSTING:
    logging.info("@planetterrian X posting enabled (Fascinating Frontiers, delegating to engine)")
else:
    logging.info("X posting is disabled (ENABLE_X_POSTING = False)")

# ========================== GENERATE PODCAST SCRIPT ==========================
if not ENABLE_PODCAST:
    logging.info("Podcast generation is disabled (ENABLE_PODCAST = False). Skipping podcast script generation, audio processing, and RSS feed updates.")
    final_mp3 = None
else:
    POD_PROMPT = f"""You are writing an 8–11 minute (1950–2600 words) solo podcast script for "Fascinating Frontiers" Episode {episode_num}.

HOST: A Canadian space enthusiast and newscaster. Voice like a solo podcaster breaking space and astronomy news, not robotic. Do NOT use any personal names for the host.

BRAND PERSONALITY: Fascinating Frontiers - Daily space and astronomy news digest. Mission: Bring the wonders of space exploration and astronomy discoveries to everyone. Values: Curiosity, exploration, scientific accuracy, inspiration.

RULES:
- Start every line with "Host:"
- Don't read URLs aloud - mention source names naturally
- Use natural dates ("today", "this morning") not exact timestamps
- Enunciate all numbers clearly
- Use ONLY information from the digest below - nothing else
- Make it sound like a real solo pod: vivid but concise, no robotic repetition
- Emphasize the wonder and significance of space discoveries
- Focus on exploration, discovery, and humanity's cosmic journey
- Never refer to the host by name

SCRIPT STRUCTURE:
[Intro music - 10 seconds]
Host: Welcome to Fascinating Frontiers, episode {episode_num}. It is {today_str}, bringing you today's most exciting space and astronomy news. Thank you for joining us today. If you like the show, please like, share, rate and subscribe to the podcast, it really helps. Now let's journey to the stars with today's discoveries.

Host: Quick scan before we dive in—three stories to watch today, then we'll go through the full list in order.

[Narrate EVERY item from the digest in order - no skipping]
- For each news item: Read the title with energy, then summarize in 2–4 lines: what happened and why it matters. VARY the closing angle for each item — do NOT repeat "what to watch next" or any single phrase. Instead, alternate between: a forward-looking implication, a surprising connection to another field, a historical comparison, a practical impact, or simply ending with the significance. Each item should feel distinct in its delivery.
- Cosmic Spotlight: Explain why this breakthrough represents the cutting edge of space exploration
- Daily Inspiration: Read the quote verbatim, add one encouraging sentence

[Closing]
Host: That's Fascinating Frontiers for today. Remember: we're all made of starstuff, and every discovery brings us closer to understanding our place in the cosmos. Together, we're exploring the final frontier, one discovery at a time. We'll catch you tomorrow on Fascinating Frontiers!

Here is today's complete formatted digest. Use ONLY this content:

{x_thread}
"""

    @retry(
        stop=stop_after_attempt(2),  # Reduced from 3 for faster recovery
        wait=wait_exponential(multiplier=1, min=1, max=15),  # Reduced wait times: 1-15s instead of 2-30s
        retry=retry_if_exception_type((Exception,))
    )
    def generate_podcast_script_with_grok():
        from xai_grok import grok_generate_text

        return grok_generate_text(
            prompt=POD_PROMPT,
            model="grok-4",
            temperature=0.7,
            max_tokens=3500,  # Reduced from 4000 for faster generation
            timeout_seconds=300.0,
            enable_web_search=False,
            enable_x_search=False,
        )
    
    logging.info("Generating podcast script with Grok (this may take 1-2 minutes)...")
    try:
        podcast_script, _pod_meta = generate_podcast_script_with_grok()
        
        # Log token usage if available
        usage = (_pod_meta or {}).get("usage")
        if usage:
            total = getattr(usage, "total_tokens", None)
            prompt_t = getattr(usage, "prompt_tokens", None)
            completion_t = getattr(usage, "completion_tokens", None)
            if total is not None:
                logging.info(
                    f"Podcast script generation - Tokens used: {total} (prompt: {prompt_t}, completion: {completion_t})"
                )
                estimated_cost = (float(total) / 1000000) * 0.01
                logging.info(f"Estimated cost: ${estimated_cost:.4f}")

                # Track credit usage
                credit_usage["services"]["grok_api"]["podcast_script_generation"]["prompt_tokens"] = prompt_t
                credit_usage["services"]["grok_api"]["podcast_script_generation"]["completion_tokens"] = completion_t
                credit_usage["services"]["grok_api"]["podcast_script_generation"]["total_tokens"] = total
                credit_usage["services"]["grok_api"]["podcast_script_generation"]["estimated_cost_usd"] = estimated_cost
    except Exception as e:
        logging.error(f"Grok API call for podcast script failed: {e}")
        raise

    # Save transcript
    transcript_path = digests_dir / f"podcast_transcript_{datetime.date.today():%Y%m%d}.txt"
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(f"# Fascinating Frontiers – The Pod | Ep {episode_num} | {today_str}\n\n{podcast_script}")
    logging.info("Natural podcast script generated")

    # ========================== TTS (VOICE) ==========================
    logging.info("TTS provider: ElevenLabs")

    def _chunk_text(text: str, max_chars: int) -> List[str]:
        """Split long text into chunks for local TTS models."""
        cleaned = re.sub(r"\s+", " ", (text or "")).strip()
        if not cleaned:
            return []
        if max_chars <= 0 or len(cleaned) <= max_chars:
            return [cleaned]

        chunks: List[str] = []
        start = 0
        n = len(cleaned)
        while start < n:
            end = min(start + max_chars, n)
            window = cleaned[start:end]

            # Prefer cutting at sentence boundaries; fall back to commas; then hard cut.
            candidates = [window.rfind("."), window.rfind("!"), window.rfind("?"), window.rfind(";"), window.rfind(":")]
            cut = max(candidates)
            if cut < int(max_chars * 0.5):
                cut = window.rfind(",")
            if cut < int(max_chars * 0.5):
                cut = len(window) - 1

            piece = window[: cut + 1].strip()
            if piece:
                chunks.append(piece)
            start += cut + 1

        return chunks


    # ElevenLabs helper
    VOICE_ID = ELEVEN_VOICE_ID

    def validate_elevenlabs_auth():
        """Fail fast with a clear message when the ElevenLabs key is rejected."""
        resp = requests.get(f"{ELEVEN_API}/user", headers={"xi-api-key": ELEVEN_KEY}, timeout=10)
        if resp.status_code == 401:
            raise RuntimeError("ElevenLabs rejected the API key (401). Update ELEVENLABS_API_KEY in .env/GitHub secrets.")
        resp.raise_for_status()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout))
    )
    def speak(text: str, voice_id: str, filename: str):
        url = f"{ELEVEN_API}/text-to-speech/{voice_id}/stream"
        headers = {
            "xi-api-key": ELEVEN_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg"
        }
        payload = {
            "text": text + "!",
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": 0.65,
                "similarity_boost": 0.9,
                "style": 0.85,
                "use_speaker_boost": True
            }
        }
        try:
            r = requests.post(url, json=payload, headers=headers, stream=True, timeout=60)
            if r.status_code == 401:
                raise requests.HTTPError(
                    "ElevenLabs returned 401 Unauthorized. Verify ELEVENLABS_API_KEY and that the voice ID is accessible to this account.",
                    response=r,
                )
            r.raise_for_status()
        except requests.HTTPError as exc:
            logging.error("ElevenLabs TTS call failed: %s; response: %s", exc, getattr(exc.response, "text", ""))
            raise
        with open(filename, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)

    # get_audio_duration and format_duration imported from engine/
    format_duration = _engine_format_duration

    # Process podcast script (remove "Host:"/"Patrick:" prefixes and stage directions)
    full_text_parts = []
    for line in podcast_script.splitlines():
        line = line.strip()
        if line.startswith("[") or not line:
            continue
        if line.startswith("Host:"):
            full_text_parts.append(line[5:].strip())
        elif line.startswith("Patrick:"):
            # Backward compat: strip legacy "Patrick:" prefix if Grok still generates it
            full_text_parts.append(line[9:].strip())
        else:
            full_text_parts.append(line)

    full_text = " ".join(full_text_parts).strip()
    
    # Ensure we have content and log it for debugging
    if not full_text:
        logging.error("ERROR: No text content extracted from podcast script!")
        raise RuntimeError("Podcast script processing failed - no text content found")
    
    logging.info(f"Extracted podcast script: {len(full_text)} characters")
    if len(full_text) < 500:
        logging.error(f"ERROR: Extracted text is too short ({len(full_text)} chars). This will result in a very short podcast!")
        logging.error(f"First 1000 chars of extracted text: {full_text[:1000]}")
        raise RuntimeError(f"Podcast script is too short ({len(full_text)} chars) - expected at least 500 characters")
    
    # Estimate expected duration (roughly 20 chars per second of speech)
    estimated_duration = len(full_text) / 20
    logging.info(f"Estimated podcast duration: ~{estimated_duration:.1f} seconds ({estimated_duration/60:.1f} minutes)")
    
    full_text = fix_pronunciation(full_text)

    # Track character count (used for reporting; cost is provider-dependent)
    credit_usage["services"]["elevenlabs_api"]["characters"] = len(full_text)
    credit_usage["services"]["elevenlabs_api"]["provider"] = "elevenlabs"
    logging.info(f"TTS: {len(full_text)} characters to synthesize (ElevenLabs)")

    # Generate voice file
    import time
    tts_start_time = time.time()
    logging.info("Generating voice track with ElevenLabs...")
    validate_elevenlabs_auth()
    voice_file = tmp_dir / "patrick_full.mp3"
    speak(full_text, VOICE_ID, str(voice_file))
    if not voice_file.exists():
        raise FileNotFoundError(f"TTS generation failed: voice file not created at {voice_file}")

    # Validate voice file size and duration
    voice_file_size = voice_file.stat().st_size
    if voice_file_size < 10000:  # Less than 10KB is suspicious
        raise RuntimeError(f"Generated voice file is too small ({voice_file_size} bytes) - TTS likely failed")

    voice_audio_duration = get_audio_duration(voice_file)
    expected_min_duration = len(full_text) / 20  # Rough estimate: ~20 chars per second
    if voice_audio_duration < expected_min_duration * 0.1:  # Less than 10% of expected
        raise RuntimeError(f"Generated voice duration ({voice_audio_duration:.2f}s) is suspiciously short for {len(full_text)} characters (expected ~{expected_min_duration:.2f}s)")

    audio_files = [str(voice_file)]
    tts_duration = time.time() - tts_start_time
    logging.info(f"✅ Generated complete voice track: {voice_file} ({voice_audio_duration:.2f}s audio, {tts_duration:.1f}s generation time, {len(full_text)/tts_duration:.1f} chars/sec)")

    # ========================== FINAL MIX ==========================
    final_mp3 = digests_dir / f"Fascinating_Frontiers_Ep{episode_num:03d}_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp3"

    # Intro music: Original short intro theme
    INTRO_MUSIC = project_root / "assets" / "music" / "fascinatingfrontiers.mp3"
    # Background music: New longer track for end of podcast
    BACKGROUND_MUSIC = project_root / "assets" / "music" / "fascinatingfrontiers_bg.mp3"
    # Voice timing: keep a consistent intro delay so mixes/concats align.
    VOICE_INTRO_DELAY_SECONDS = 28.0
    VOICE_INTRO_DELAY_MS = int(VOICE_INTRO_DELAY_SECONDS * 1000)

    # Process and normalize voice in one step
    voice_mix = tmp_dir / "voice_normalized_mix.mp3"
    logging.info(f"Normalizing voice with engine/audio.normalize_voice()...")
    _engine_normalize_voice(voice_file, voice_mix)

    # Get voice duration
    voice_duration = max(get_audio_duration(voice_mix), 0.0)
    logging.info(f"Voice duration: {voice_duration:.2f} seconds")

    # ========================== OPTIONAL SPOCK "FASCINATING" INSERTION ==========================
    # Occasionally add Spock's "Fascinating" clip as an Easter egg (30% chance)
    # This honors the podcast's namesake - Spock's logical, fact-focused approach to knowledge
    SPOCK_CLIP = digests_dir / "fascinating_frontiers" / "spock-fascinating.mp3"
    should_add_spock = random.random() < 0.30 and SPOCK_CLIP.exists()  # 30% chance
    
    # Initialize Spock-related variables for cleanup (even if not used)
    voice_before = None
    voice_after = None
    silence_before_spock = None
    silence_after_spock = None
    spock_normalized = None
    spock_concat_list = None
    voice_with_spock = None
    
    if should_add_spock:
        try:
            spock_duration = get_audio_duration(SPOCK_CLIP)
            logging.info(f"Adding Spock 'Fascinating' clip ({spock_duration:.2f}s) - honoring the podcast's namesake!")
            
            # Insert Spock clip at ~65% through the voice track (after main content, before closing)
            # This is typically after the Cosmic Spotlight section
            insertion_point = voice_duration * 0.65
            
            # Split voice into two parts: before and after insertion point
            voice_before = tmp_dir / "voice_before_spock.mp3"
            voice_after = tmp_dir / "voice_after_spock.mp3"
            
            # Extract first part (up to insertion point)
            subprocess.run([
                "ffmpeg", "-y", "-threads", "0",
                "-i", str(voice_mix),
                "-t", str(insertion_point),
                "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                str(voice_before)
            ], check=True, capture_output=True)
            
            # Extract second part (from insertion point onwards)
            subprocess.run([
                "ffmpeg", "-y", "-threads", "0",
                "-i", str(voice_mix),
                "-ss", str(insertion_point),
                "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                str(voice_after)
            ], check=True, capture_output=True)
            
            # Create a small pause before Spock (0.3 seconds of silence)
            silence_before_spock = tmp_dir / "silence_before_spock.mp3"
            subprocess.run([
                "ffmpeg", "-y", "-threads", "0",
                "-f", "lavfi", "-t", "0.3", "-i", "anullsrc=r=44100:cl=mono",
                "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                str(silence_before_spock)
            ], check=True, capture_output=True)
            
            # Create a small pause after Spock (0.2 seconds of silence)
            silence_after_spock = tmp_dir / "silence_after_spock.mp3"
            subprocess.run([
                "ffmpeg", "-y", "-threads", "0",
                "-f", "lavfi", "-t", "0.2", "-i", "anullsrc=r=44100:cl=mono",
                "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                str(silence_after_spock)
            ], check=True, capture_output=True)
            
            # Normalize Spock clip to match voice levels
            spock_normalized = tmp_dir / "spock_normalized.mp3"
            subprocess.run([
                "ffmpeg", "-y", "-threads", "0",
                "-i", str(SPOCK_CLIP),
                "-af", "loudnorm=I=-18:TP=-1.5:LRA=11:linear=true,volume=0.9",  # Slightly quieter than voice
                "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                str(spock_normalized)
            ], check=True, capture_output=True)
            
            # Concatenate: voice_before + silence + Spock + silence + voice_after
            spock_concat_list = tmp_dir / "spock_concat.txt"
            with open(spock_concat_list, "w") as f:
                f.write(f"file '{voice_before.absolute()}'\n")
                f.write(f"file '{silence_before_spock.absolute()}'\n")
                f.write(f"file '{spock_normalized.absolute()}'\n")
                f.write(f"file '{silence_after_spock.absolute()}'\n")
                f.write(f"file '{voice_after.absolute()}'\n")
            
            # Create voice with Spock inserted
            voice_with_spock = tmp_dir / "voice_with_spock.mp3"
            subprocess.run([
                "ffmpeg", "-y", "-threads", "0",
                "-f", "concat", "-safe", "0", "-i", str(spock_concat_list),
                "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                str(voice_with_spock)
            ], check=True, capture_output=True)
            
            # Replace voice_mix with the version that includes Spock
            if voice_with_spock.exists():
                voice_mix = voice_with_spock
                voice_duration = max(get_audio_duration(voice_mix), 0.0)
                logging.info(f"✅ Spock clip inserted! New voice duration: {voice_duration:.2f} seconds")
            else:
                logging.warning("Failed to create voice with Spock clip, using original voice")
        except Exception as e:
            logging.warning(f"Failed to insert Spock clip: {e}, continuing with original voice")
            # Continue with original voice_mix if Spock insertion fails

    # Check if we have the required music files
    has_intro_music = INTRO_MUSIC.exists() if INTRO_MUSIC else False
    has_background_music = BACKGROUND_MUSIC.exists() if BACKGROUND_MUSIC else False

    if not has_intro_music and not has_background_music:
        _engine_normalize_voice(voice_mix, final_mp3)
        logging.info("Podcast ready (voice-only, no music files found)")
    elif has_intro_music and not has_background_music:
        # Original logic: only intro music, no background music
        intro_duration = get_audio_duration(INTRO_MUSIC)
        logging.info(f"Intro music duration: {intro_duration:.2f} seconds")

        # Prepare voice with 28-second delay
        voice_delayed = tmp_dir / "voice_delayed.mp3"

        logging.info("Delaying voice to start at 28 seconds...")
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0", "-i", str(voice_mix),
            "-af", f"adelay={VOICE_INTRO_DELAY_MS}|{VOICE_INTRO_DELAY_MS}",  # intro delay
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
            str(voice_delayed)
        ], check=True, capture_output=True)

        # Final mix: voice + intro music (music plays once, then voice continues alone)
        logging.info("Mixing voice and Fascinating Frontiers intro music...")
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0",
            "-i", str(voice_delayed),
            "-i", str(INTRO_MUSIC),
            "-filter_complex",
            "[0:a]volume=1.0[a_voice];"
            "[1:a]volume=0.5[a_music];"  # Music at normal volume for intro
            "[a_voice][a_music]amix=inputs=2:duration=longest:dropout_transition=2:weights=2 1[mixed];"
            "[mixed]alimiter=level_in=1:level_out=0.95:limit=0.95[outfinal]",
            "-map", "[outfinal]",
            "-c:a", "libmp3lame",
            "-b:a", "192k", "-preset", "fast",
            str(final_mp3)
        ], check=True, capture_output=True)

        # Verify final file was created and has content
        if not final_mp3.exists():
            raise RuntimeError(f"Final podcast file {final_mp3} was not created!")

        final_size = final_mp3.stat().st_size
        logging.info(f"Final podcast file size: {final_size} bytes")

        if final_size < 10000:  # Less than 10KB is definitely wrong for a 55s podcast
            raise RuntimeError(f"Final podcast file {final_mp3} is too small ({final_size} bytes) - mixing failed")

        logging.info("Podcast created successfully with Fascinating Frontiers intro music")

        # Cleanup temp files
        # Cleanup temp files (including Spock-related files if they exist)
        cleanup_files = [voice_delayed]
        if should_add_spock:
            cleanup_files.extend([
                voice_before, voice_after, silence_before_spock, silence_after_spock,
                spock_normalized, spock_concat_list, voice_with_spock
            ])
        for tmp_file in cleanup_files:
            if tmp_file and tmp_file.exists():
                try:
                    os.remove(str(tmp_file))
                except Exception:
                    pass
    else:
        # Both intro music and background music
        intro_duration = get_audio_duration(INTRO_MUSIC)
        logging.info(f"Intro music duration: {intro_duration:.2f} seconds")

        # Calculate background music timing:
        # Background music starts fading in 30 seconds before voice ends
        # Background music continues for 30 seconds after voice ends
        bg_music_start = max(intro_duration, voice_duration - 30)  # Don't start BG music during intro
        bg_music_duration = 60  # 30s fade-in + 30s after voice ends

        logging.info(f"Background music: starts at {bg_music_start:.2f}s, duration {bg_music_duration:.2f}s")

        # Create intro section with original logic
        voice_delayed = tmp_dir / "voice_delayed.mp3"
        logging.info("Delaying voice to start at 28 seconds (during intro music)...")
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0", "-i", str(voice_mix),
            "-af", f"adelay={VOICE_INTRO_DELAY_MS}|{VOICE_INTRO_DELAY_MS}",  # intro delay
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
            str(voice_delayed)
        ], check=True, capture_output=True)

        # Intro mix (first part with intro music)
        intro_mix = tmp_dir / "intro_mix.mp3"
        logging.info("Creating intro section with intro music and voice...")
        # IMPORTANT: `voice_delayed` includes VOICE_INTRO_DELAY_SECONDS of silence.
        # `bg_music_start` is computed in the *voice timeline*, so we must add the delay
        # to cut the intro section at the correct point. Otherwise the concat will
        # drop the final ~VOICE_INTRO_DELAY_SECONDS of spoken audio before the outro/music.
        intro_cut_time = bg_music_start + VOICE_INTRO_DELAY_SECONDS
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0",
            "-i", str(voice_delayed),
            "-i", str(INTRO_MUSIC),
            "-filter_complex",
            "[0:a]volume=1.0[a_voice];"
            "[1:a]volume=0.5[a_music];"
            "[a_voice][a_music]amix=inputs=2:duration=first:dropout_transition=2:weights=2 1[mixed];"
            "[mixed]alimiter=level_in=1:level_out=0.95:limit=0.95[outfinal]",
            "-map", "[outfinal]",
            "-t", f"{intro_cut_time:.2f}",  # cut at bg_music_start in voice timeline (+ intro delay)
            "-c:a", "libmp3lame",
            "-b:a", "192k", "-preset", "fast",
            str(intro_mix)
        ], check=True, capture_output=True)

        # Create full background music track (longer than voice to ensure coverage)
        bg_full = tmp_dir / "bg_full.mp3"
        # Make background music longer than the remaining podcast duration
        bg_total_duration = (voice_duration - bg_music_start) + 30 + 10  # voice remaining + 30s after + buffer
        logging.info(f"Creating full background music track ({bg_total_duration:.2f}s)...")

        subprocess.run([
            "ffmpeg", "-y", "-threads", "0",
            "-i", str(BACKGROUND_MUSIC),
            "-t", str(bg_total_duration),
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
            str(bg_full)
        ], check=True, capture_output=True)

        # Background music should start immediately with the remaining voice portion
        # No need for silence since we're starting from bg_music_start in the voice timeline
        bg_with_silence = bg_full  # Use background music directly, no silence needed

        # Extract the remaining voice portion (from bg_music_start onwards)
        # This avoids duplicating the voice that's already in intro_mix
        voice_remaining = tmp_dir / "voice_remaining.mp3"
        logging.info(f"Extracting voice portion from {bg_music_start:.2f}s onwards (avoiding duplication with intro section)...")
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0",
            "-i", str(voice_mix),
            "-ss", str(bg_music_start),  # Start from where intro_mix ends
            "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
            str(voice_remaining)
        ], check=True, capture_output=True)
        
        # Extend the remaining voice with silence to match background music duration
        voice_extended = tmp_dir / "voice_extended.mp3"
        voice_remaining_duration = get_audio_duration(voice_remaining)
        voice_total_duration = voice_remaining_duration + 30  # Add 30s after voice ends
        logging.info(f"Extending remaining voice track ({voice_remaining_duration:.2f}s) to {voice_total_duration:.2f}s total duration...")

        # Use apad filter to extend audio with silence
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0",
            "-i", str(voice_remaining),
            "-af", f"apad=whole_dur={voice_total_duration}",
            "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
            str(voice_extended)
        ], check=True, capture_output=True)

        # Mix extended voice with background music
        voice_bg_mix = tmp_dir / "voice_bg_mix.mp3"
        logging.info("Mixing extended voice with background music...")
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0",
            "-i", str(voice_extended),
            "-i", str(bg_with_silence),
            "-filter_complex",
            "[0:a]volume=1.0[a_voice];"
            "[1:a]volume=0.3[a_music];"  # Background music at 30% volume
            "[a_voice][a_music]amix=inputs=2:duration=longest:dropout_transition=2[a_mixed];"
            "[a_mixed]alimiter=level_in=1:level_out=0.95:limit=0.95[outfinal]",
            "-map", "[outfinal]",
            "-c:a", "libmp3lame",
            "-b:a", "192k", "-preset", "fast",
            str(voice_bg_mix)
        ], check=True, capture_output=True)

        # Combine intro and voice+background sections
        concat_list = tmp_dir / "final_concat.txt"
        with open(concat_list, "w") as f:
            f.write(f"file '{intro_mix}'\n")
            f.write(f"file '{voice_bg_mix}'\n")

        logging.info("Creating final podcast...")
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list),
            "-c:a", "libmp3lame",
            "-b:a", "192k", "-preset", "fast",
            str(final_mp3)
        ], check=True, capture_output=True)

        # Verify final file
        if not final_mp3.exists():
            raise RuntimeError(f"Final podcast file {final_mp3} was not created!")

        final_size = final_mp3.stat().st_size
        logging.info(f"Final podcast file size: {final_size} bytes")

        # Total duration is voice duration + 30 seconds for background music after voice ends
        total_estimated_duration = voice_duration + 30
        expected_min_size = int(total_estimated_duration * 28000)  # More conservative bitrate estimate
        if final_size < expected_min_size:
            logging.warning(f"Final podcast file size ({final_size} bytes) is smaller than expected (~{expected_min_size} bytes), but continuing...")
            # Don't fail, just warn - the file might still be valid

        logging.info("Podcast created successfully with intro music and background music")

        # Cleanup temp files
        # Cleanup temp files (including Spock-related files if they exist)
        cleanup_files = [voice_delayed, intro_mix, bg_full, voice_remaining,
                        voice_extended, voice_bg_mix, concat_list]
        if should_add_spock:
            cleanup_files.extend([
                voice_before, voice_after, silence_before_spock, silence_after_spock,
                spock_normalized, spock_concat_list, voice_with_spock
            ])
        for tmp_file in cleanup_files:
            if tmp_file and tmp_file.exists():
                try:
                    os.remove(str(tmp_file))
                except Exception:
                    pass
                except Exception:
                    pass

    # ========================== UPDATE RSS FEED ==========================
    _FF_IMAGE = "Fascinating Frontiers-3000x3000.jpg"
    _FF_BASE_URL = "https://nerranetwork.com"

    def update_rss_feed(
        rss_path, episode_num, episode_title, episode_description,
        episode_date, mp3_filename, mp3_duration, mp3_path,
        base_url=_FF_BASE_URL,
    ):
        _engine_update_rss_feed(
            rss_path, episode_num, episode_title, episode_description,
            episode_date, mp3_filename, mp3_duration, mp3_path,
            base_url=base_url,
            audio_subdir="digests/fascinating_frontiers",
            channel_title="Fascinating Frontiers",
            channel_link="https://nerranetwork.com/fascinating_frontiers.html",
            channel_description="Daily space and astronomy news digest. Bringing the wonders of space exploration and astronomy discoveries to everyone.",
            channel_author="Patrick",
            channel_email="contact@planetterrian.com",
            channel_image=f"{base_url}/{quote(_FF_IMAGE)}",
            channel_category="Science",
            guid_prefix="fascinating-frontiers",
            format_duration_func=format_duration,
        )

    # Update RSS feed
    if final_mp3 and final_mp3.exists():
        try:
            audio_duration = get_audio_duration(final_mp3)
            episode_title = f"Fascinating Frontiers - Episode {episode_num} - {today_str}"
            episode_description = f"Daily space and astronomy news for {today_str}."
            lines = x_thread.split('\n')
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#') and not line.startswith('**') and len(line) > 50:
                    episode_description += line[:400] + "..."
                    break
            
            update_rss_feed(
                rss_path=rss_path,
                episode_num=episode_num,
                episode_title=episode_title,
                episode_description=episode_description,
                episode_date=datetime.date.today(),
                mp3_filename=final_mp3.name,
                mp3_duration=audio_duration,
                mp3_path=final_mp3,
                base_url="https://nerranetwork.com"
            )
            logging.info(f"RSS feed updated with Episode {episode_num}")
        except Exception as e:
            logging.error(f"Failed to update RSS feed: {e}", exc_info=True)

# Save summary to GitHub Pages and post link to X
if ENABLE_GITHUB_SUMMARIES:
    try:
        # Save the full summary to GitHub Pages JSON
        _base_url = "https://nerranetwork.com"
        _audio_url = None
        try:
            if ENABLE_PODCAST and final_mp3:
                _audio_url = f"{_base_url}/digests/fascinating_frontiers/{final_mp3.name}"
        except Exception:
            _audio_url = None

        summary_json_file = save_summary_to_github_pages(
            formatted_thread.strip(),
            digests_dir,
            "space",
            episode_num=episode_num if 'episode_num' in globals() else None,
            episode_title=episode_title if 'episode_title' in globals() else None,
            audio_url=_audio_url,
            rss_url=f"{_base_url}/fascinating_frontiers_podcast.rss",
        )
        if summary_json_file:
            logging.info("Summary saved to GitHub Pages successfully")
        else:
            logging.warning("Failed to save summary to GitHub Pages")
    except Exception as e:
        logging.error(f"Failed to save summary to GitHub Pages: {e}")

# Post link to GitHub Pages summary on X instead of full content
if ENABLE_X_POSTING:
    try:
        summaries_url = "https://nerranetwork.com/fascinating-frontiers-summaries.html"
        today = datetime.datetime.now()
        teaser_text = (
            f"\U0001f680\U0001f30c Fascinating Frontiers - {today.strftime('%B %d, %Y')}\n\n"
            f"\U0001f52d Today's complete space & astronomy digest is now live!\n\n"
            f"\U0001fa90 Latest space missions & discoveries\n"
            f"\U0001f31f Cosmic phenomena & astronomical events\n"
            f"\U0001f681 Space technology & exploration updates\n"
            f"\U0001f399\ufe0f Full podcast episode available\n\n"
            f"Read the full summary: {summaries_url}\n\n"
            f"#Space #Astronomy #NASA #SpaceX #FascinatingFrontiers"
        )
        credit_usage["services"]["x_api"]["post_calls"] += 1
        tweet_url = _engine_post_to_x(
            teaser_text,
            consumer_key=os.getenv("PLANETTERRIAN_X_CONSUMER_KEY", ""),
            consumer_secret=os.getenv("PLANETTERRIAN_X_CONSUMER_SECRET", ""),
            access_token=os.getenv("PLANETTERRIAN_X_ACCESS_TOKEN", ""),
            access_token_secret=os.getenv("PLANETTERRIAN_X_ACCESS_TOKEN_SECRET", ""),
        )
        if tweet_url:
            logging.info(f"DIGEST LINK POSTED \u2192 {tweet_url}")
    except Exception as e:
        logging.error(f"X post failed: {e}", exc_info=True)

# Cleanup
try:
    for file_path in audio_files:
        if os.path.exists(file_path):
            os.remove(file_path)
    logging.info("Temporary files cleaned up")
except Exception as e:
    logging.warning(f"Cleanup warning: {e}")

# Save credit usage tracking
save_credit_usage(credit_usage, digests_dir)

print("\n" + "="*80)
print("FASCINATING FRONTIERS — FULLY AUTOMATED RUN COMPLETE")
print(f"X Thread → {x_path}")
print(f"Podcast → {final_mp3}")
print("="*80)

