#!/usr/bin/env python3
"""
Planetterrian Daily – FULL AUTO X + PODCAST MACHINE
Daily Science, Longevity & Health Digest (Patrick in Vancouver)
Auto-published to X — December 2025+
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
import xml.etree.ElementTree as ET
from feedgen.feed import FeedGenerator
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
from openai import APIStatusError
from difflib import SequenceMatcher
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
import feedparser
from typing import List, Dict, Any
import tweepy
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from urllib.parse import quote

# --- engine/ shared modules ---
from engine.utils import (
    env_float, env_int, env_bool,
    number_to_words as _engine_number_to_words,
    calculate_similarity as _engine_calculate_similarity,
    remove_similar_items as _engine_remove_similar_items,
)
from engine.audio import get_audio_duration, format_duration as _engine_format_duration
from engine.publisher import (
    update_rss_feed as _engine_update_rss_feed,
    get_next_episode_number as _engine_get_next_episode_number,
    save_summary_to_github_pages as _engine_save_summary,
    generate_episode_thumbnail as _engine_generate_thumbnail,
)
from engine.tracking import create_tracker, record_llm_usage, record_tts_usage, record_x_post, save_usage

# ========================== LOGGING ==========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

# ========================== CONFIGURATION ==========================
# Set to True to test digest generation only (skips podcast and X posting)
TEST_MODE = False  # Set to False for full run

# Set to False to disable X posting (thread will still be generated and saved)
ENABLE_X_POSTING = True

# Set to False to disable podcast generation and RSS feed updates
ENABLE_PODCAST = True

# Set to True to save summaries to GitHub Pages instead of posting full content to X
ENABLE_GITHUB_SUMMARIES = True

# Link validation is currently disabled - validation functions have been removed
# Set to True and re-implement validation functions if needed in the future
ENABLE_LINK_VALIDATION = False


# ========================== NUMBER TO WORDS CONVERTER ==========================
number_to_words = _engine_number_to_words

# ========================== PRONUNCIATION FIXER – USING SHARED MODULE ==========================

def fix_pronunciation(text: str) -> str:
    """Prepare Planetterrian Daily script text for ElevenLabs TTS.

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
digests_dir = project_root / "digests" / "planetterrian"
digests_dir.mkdir(exist_ok=True, parents=True)

def get_next_episode_number(rss_path, digests_dir):
    return _engine_get_next_episode_number(
        rss_path, digests_dir, mp3_glob_pattern="Planetterrian_Daily_Ep*.mp3",
    )

# Get the next episode number
rss_path = project_root / "planetterrian_podcast.rss"
episode_num = get_next_episode_number(rss_path, digests_dir)

# ========================== CREDIT TRACKING ==========================
credit_usage = create_tracker("Planetterrian Daily", episode_num)

def save_credit_usage(usage_data, output_dir):
    """Thin wrapper around engine.tracking.save_usage."""
    save_usage(usage_data, output_dir)

def save_summary_to_github_pages(
    summary_text, output_dir, podcast_name="planet", *,
    episode_num=None, episode_title=None, audio_url=None, rss_url=None,
):
    json_path = project_root / "digests" / f"summaries_{podcast_name}.json"
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


def _enforce_x_char_limit(text: str, max_chars: int = 280) -> str:
    """
    Ensure text fits within X's 280-char limit (non-subscribed accounts).
    If too long, we progressively compress, then truncate with an ellipsis.
    """
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t

    # Collapse excessive blank lines / whitespace first
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if len(t) <= max_chars:
        return t

    # If still too long, truncate safely
    suffix = "…"
    if max_chars <= len(suffix):
        return suffix[:max_chars]
    return (t[: max_chars - len(suffix)].rstrip() + suffix)


# ========================== STEP 1: FETCH SCIENCE/LONGEVITY/HEALTH NEWS FROM RSS FEEDS ==========================
logging.info("Step 1: Fetching science, longevity, and health news from RSS feeds for the last 48 hours...")

calculate_similarity = _engine_calculate_similarity
remove_similar_items = _engine_remove_similar_items

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.RequestException, requests.Timeout))
)
def fetch_science_news():
    """Fetch science, longevity, and health news from RSS feeds for the last 48 hours."""
    import feedparser
    
    # Science, longevity, and health RSS feeds
    rss_feeds = [
        # Major Science Journals
        "https://www.nature.com/nature.rss",
        "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science",
        "https://www.cell.com/cell/current.rss",
        "https://www.cell.com/cell-metabolism/current.rss",
        "https://www.cell.com/cell-stem-cell/current.rss",
        "https://www.nature.com/nbt.rss",
        "https://www.nature.com/nm.rss",
        "https://www.nature.com/nmeth.rss",
        
        # Science News Outlets
        "https://www.newscientist.com/feed/home/",
        "https://www.scientificamerican.com/rss/",
        "https://www.sciencedaily.com/rss/all.xml",
        "https://www.sciencenews.org/feed",
        "https://www.quantamagazine.org/feed/",
        "https://www.technologyreview.com/feed/",
        "https://www.the-scientist.com/rss",
        
        # Longevity & Anti-Aging
        "https://feeds.feedburner.com/longevity-technology",
        "https://www.lifespan.io/feed/",
        "https://www.longevity.technology/feed/",
        
        # Research Institutions
        "https://www.harvard.edu/feed/",
        "https://news.mit.edu/rss/topic/health",
        "https://www.stanford.edu/news/rss/",
        "https://www.mayo.edu/research/rss",
        "https://www.clevelandclinic.org/health/rss",
        
    ]
    
    # Calculate cutoff time (last 48 hours)
    cutoff_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)
    
    all_articles = []
    raw_articles = []
    
    # Science/longevity/health keywords to filter articles
    science_keywords = [
        "longevity", "anti-aging", "aging", "lifespan", "healthspan",
        "biotechnology", "genetics", "genomics", "CRISPR", "gene therapy",
        "medicine", "medical", "health", "wellness", "nutrition", "diet",
        "research", "study", "clinical trial", "discovery", "breakthrough",
        "science", "scientific", "biotech",
        "cancer", "disease", "treatment", "therapy", "vaccine",
        "brain", "neuroscience", "cognitive", "mental health",
        "exercise", "fitness", "metabolism", "mitochondria"
    ]
    
    logging.info(f"Fetching science/longevity/health news from {len(rss_feeds)} RSS feeds...")
    
    for feed_url in rss_feeds:
        source_name = "Unknown"
        try:
            feed = feedparser.parse(feed_url)
            
            if feed.bozo and feed.bozo_exception:
                logging.warning(f"Failed to parse RSS feed {feed_url}: {feed.bozo_exception}")
                continue
            
            source_name = feed.feed.get("title", "Unknown")
            # Map common feed sources
            if "nature.com" in feed_url.lower():
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
                
                # Check if article is science/longevity/health-related
                title_desc_lower = (title + " " + description).lower()
                if not any(keyword in title_desc_lower for keyword in science_keywords):
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
                raw_articles.append(article)
            
            logging.info(f"Fetched {len(feed_articles)} articles from {source_name}")
            all_articles.extend(feed_articles)
            
        except Exception as e:
            logging.warning(f"Failed to fetch RSS feed {feed_url}: {e}")
            continue
    
    logging.info(f"Fetched {len(all_articles)} total articles from RSS feeds")
    
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
    
    logging.info(f"Filtered to {len(formatted_articles)} unique science/longevity/health news articles")

    # Select the best news from the last 48 hours
    selected_articles = select_best_science_news(formatted_articles, max_articles=12)

    logging.info(f"Selected {len(selected_articles)} best science/longevity/health news articles from 48-hour collection")
    return selected_articles, raw_articles

def select_best_science_news(articles, max_articles=12):
    """
    Select the best science/longevity/health news from the 48-hour collection.
    Prioritizes high-quality sources, recent articles, and important topics.
    """
    if not articles:
        return []

    # Source quality scores (higher = better)
    source_scores = {
        "Nature": 10, "Nature Medicine": 10, "Nature Biotechnology": 10, "Nature Methods": 9,
        "Science": 10, "Cell": 9, "Cell Metabolism": 9, "Cell Stem Cell": 9,
        "New England Journal of Medicine": 9, "The Lancet": 9,
        "New Scientist": 7, "Scientific American": 7, "Science News": 7,
        "MIT Technology Review": 7, "Quanta Magazine": 7,
        "Harvard University": 8, "MIT News": 8, "Stanford University": 8,
        "Mayo Clinic": 8, "Cleveland Clinic": 8,
        "Lifespan.io": 6, "Longevity Technology": 6
    }

    # Topic importance scores (higher = more important)
    important_keywords = {
        "breakthrough": 5, "discovery": 4, "cure": 5, "treatment": 4, "vaccine": 5,
        "CRISPR": 4, "gene therapy": 4, "stem cell": 4, "longevity": 4,
        "aging": 3, "cancer": 4, "diabetes": 3, "Alzheimer": 4, "dementia": 3,
        "clinical trial": 4, "FDA approval": 5, "new drug": 4,
        "pandemic": 4, "vaccine": 5, "coronavirus": 3
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

        # Topic importance score
        text = f"{article.get('title', '')} {article.get('description', '')}".lower()
        for keyword, bonus in important_keywords.items():
            if keyword.lower() in text:
                score += bonus
                break  # Only count the first matching keyword

        # Title quality bonus (articles with compelling titles)
        title = article.get('title', '').lower()
        if any(word in title for word in ['new', 'breakthrough', 'discovery', 'first', 'major', 'significant']):
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

science_news, raw_news_articles = fetch_science_news()

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

# Science/longevity/health keywords for content filtering
SCIENCE_CONTENT_KEYWORDS = [
    "longevity", "anti-aging", "aging", "lifespan", "healthspan",
    "biotechnology", "genetics", "genomics", "CRISPR", "gene therapy",
    "medicine", "medical", "health", "wellness", "nutrition", "diet",
    "research", "study", "clinical trial", "discovery", "breakthrough",
    "science", "scientific", "biotech",
    "cancer", "disease", "treatment", "therapy", "vaccine",
    "brain", "neuroscience", "cognitive", "mental health"
]

def is_science_related(text: str) -> bool:
    """Check if post text contains science/longevity/health keywords."""
    if not text:
        return False
    
    text_lower = text.lower()
    for keyword in SCIENCE_CONTENT_KEYWORDS:
        if keyword.lower() in text_lower:
            return True
    
    return False

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
logging.info("Step 3: Generating Planetterrian Daily digest with Grok...")

# Format news articles for the prompt
news_section = ""
if science_news:
    news_section = "## PRE-FETCHED NEWS ARTICLES (from RSS feeds - last 24 hours):\n\n"
    for i, article in enumerate(science_news[:20], 1):
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

X_PROMPT = f"""
# Planetterrian Daily - SCIENCE, LONGEVITY & HEALTH EDITION
**Date:** {today_str}
🌍 Planetterrian Daily Podcast: Coming soon to Apple Podcasts
{news_section}

You are an elite science, longevity, and health news curator producing the daily "Planetterrian Daily" newsletter. Use ONLY the pre-fetched news articles above. Do NOT hallucinate, invent, or search for new content/URLs—stick to exact provided links. Do NOT include any X posts or Twitter references.

**BRAND PERSONALITY (from planetterrian.com/about):**
- Planetterrian Ventures: A tribe of forward-thinking innovators passionate about the planet
- Mission: Intertwine technology and compassion, ensuring innovations push boundaries while caring for Earth
- Values: Technology as a force for good, sustainability, environmental consciousness
- Tone: Inspirational, optimistic, planet-conscious, compassionate, forward-thinking
- Focus: Groundbreaking solutions that are state-of-the-art AND sustainable/environmentally-friendly

### MANDATORY SELECTION & COUNTS (CRITICAL - FOLLOW EXACTLY)
- **News**: You MUST select EXACTLY 15 unique articles. If you have fewer than 15 available, use ALL of them and number them 1 through N. If you have more than 15, select the BEST 15. Prioritize high-quality sources; each must cover a DIFFERENT story/angle.
- **Curation**: Prefer primary research, clinical results, and concrete discoveries. Avoid “year in review” roundups, awards, and career anecdote pieces unless you truly cannot fill 15 without them.
- **NO X POSTS**: Do NOT include any X posts, Twitter posts, or social media references. Only use news articles.
- **Diversity Check**: Verify no similar content; each item must cover a DIFFERENT angle.

### FORMATTING (EXACT—USE MARKDOWN AS SHOWN)
# Planetterrian Daily
**Date:** {today_str}
🌍 **Planetterrian Daily** - Science, Longevity & Health Discoveries

**Quick scan:** 1 short sentence theme + “If you only read 3 today: #A, #B, #C.”

━━━━━━━━━━━━━━━━━━━━
### Top 15 Science & Health Discoveries
1. **Title (<= 12 words): DD Month YYYY • Source Name**  
   2 sentences max. Sentence 1: what happened (specific + concrete). Sentence 2: why it matters for human health/longevity; add ONE planet/sustainability angle only if it is genuinely relevant (don’t force it).
   Source: [EXACT URL FROM PRE-FETCHED—no mods]
2. [Repeat format for 3-15; if <15 items, stop at available count, add a blank line after each item]

━━━━━━━━━━━━━━━━━━━━
### Planetterrian Spotlight
Pick ONE item from the Top 15 and go deeper (3–5 sentences). Make it feel practical: what it unlocks, who it could help, and one concrete planet-aligned takeaway (energy, materials, food systems, prevention, access, etc.). End with ONE question to invite replies.

━━━━━━━━━━━━━━━━━━━━
### Daily Inspiration
One inspiring quote about science, health, longevity, or planetary stewardship. End with: "Share your thoughts with us!"

[1-2 sentence uplifting sign-off on science, health, and planetary well-being. Keep it punchy.]

### TONE & STYLE
- Inspirational, planet-conscious, optimistic, compassionate
- Avoid repetitive phrasing like “This matters…” on every item — vary your language
- Be scannable: short sentences, no fluff
- Focus on how discoveries benefit humanity; include planet impact only when concrete
- Dates should be accurate PST/PDT; avoid exact HH:MM unless it materially matters

Output today's edition exactly as formatted.
"""

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=15),  # Reduced wait times: 1-15s instead of 2-30s
    retry=retry_if_exception_type((Exception,))
)
def generate_digest_with_grok():
    """Generate digest with retry logic"""
    def _create_via_openai_compat():
        return client.chat.completions.create(
            model="grok-4",
            messages=[{"role": "user", "content": X_PROMPT}],
            temperature=0.7,
            max_tokens=3500,  # Reduced from 4000 for faster generation
        )

    def _create_via_xai_sdk():
        # xAI is migrating away from OpenAI-compatible chat/completions.
        # Fall back to the official xAI Python SDK.
        try:
            from xai_sdk import Client as XAIClient
            from xai_sdk.chat import user as xai_user
        except Exception as exc:
            raise RuntimeError(
                "xai-sdk is required for Grok fallback. Please add 'xai-sdk' to requirements."
            ) from exc

        api_key = (os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("Missing GROK_API_KEY (or XAI_API_KEY) for xAI SDK client.")

        xai_client = XAIClient(api_key=api_key, timeout=3600)
        chat = xai_client.chat.create(model="grok-4", store_messages=False)
        chat.append(xai_user(X_PROMPT))
        return chat.sample()

    try:
        return _create_via_openai_compat()
    except APIStatusError as e:
        status = getattr(e, "status_code", None)
        msg = str(e) or ""
        if status == 410 or "live search is deprecated" in msg.lower():
            logging.warning("⚠️ xAI chat/completions deprecated (410). Retrying via xAI SDK.")
            return _create_via_xai_sdk()
        raise

try:
    response = generate_digest_with_grok()
    # Support both OpenAI-compatible responses and xai-sdk responses
    if hasattr(response, "choices"):
        x_thread = response.choices[0].message.content.strip()
    else:
        x_thread = (getattr(response, "content", "") or "").strip()
    
    # Log token usage and cost
    if hasattr(response, 'usage') and response.usage:
        usage = response.usage
        total_tokens = getattr(usage, "total_tokens", None)
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        completion_tokens = getattr(usage, "completion_tokens", None)
        if total_tokens is not None:
            logging.info(
                f"Grok API - Tokens used: {total_tokens} (prompt: {prompt_tokens}, completion: {completion_tokens})"
            )
            estimated_cost = (float(total_tokens) / 1000000) * 0.01
            logging.info(f"Estimated cost: ${estimated_cost:.4f}")
            
            # Track credit usage (best-effort across SDKs)
            credit_usage["services"]["grok_api"]["x_thread_generation"]["prompt_tokens"] = prompt_tokens
            credit_usage["services"]["grok_api"]["x_thread_generation"]["completion_tokens"] = completion_tokens
            credit_usage["services"]["grok_api"]["x_thread_generation"]["total_tokens"] = total_tokens
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

# Save X thread
x_path = digests_dir / f"Planetterrian_Daily_{datetime.date.today():%Y%m%d}.md"
with open(x_path, "w", encoding="utf-8") as f:
    f.write(x_thread)
logging.info(f"X thread saved to {x_path}")

# Format for X posting (remove markdown, clean up)
def format_digest_for_x(digest: str) -> str:
    """Format digest for X posting."""
    formatted = digest
    
    # Remove markdown headers but keep text
    formatted = re.sub(r'^#+\s+', '', formatted, flags=re.MULTILINE)
    
    # Convert markdown bold to plain text
    formatted = re.sub(r'\*\*(.*?)\*\*', r'\1', formatted)
    
    # Clean up URLs
    formatted = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'\2', formatted)
    
    # Remove excessive blank lines
    formatted = re.sub(r'\n{3,}', '\n\n', formatted)
    
    return formatted.strip()

formatted_thread = format_digest_for_x(x_thread)

# ========================== TWEEPY X CLIENT FOR AUTO-POSTING ==========================
tweet_id = None
if ENABLE_X_POSTING:
    import tweepy

    x_client = tweepy.Client(
        consumer_key=os.getenv("PLANETTERRIAN_X_CONSUMER_KEY"),
        consumer_secret=os.getenv("PLANETTERRIAN_X_CONSUMER_SECRET"),
        access_token=os.getenv("PLANETTERRIAN_X_ACCESS_TOKEN"),
        access_token_secret=os.getenv("PLANETTERRIAN_X_ACCESS_TOKEN_SECRET"),
        bearer_token=os.getenv("PLANETTERRIAN_X_BEARER_TOKEN"),
        wait_on_rate_limit=True
    )
    logging.info("@planetterrian X posting client ready")
else:
    logging.info("X posting is disabled (ENABLE_X_POSTING = False)")

# ========================== RSS FEED FUNCTIONS (DEFINED BEFORE PODCAST GENERATION) ==========================
# Cache for audio duration lookups to avoid redundant ffprobe calls
# get_audio_duration and format_duration imported from engine/
format_duration = _engine_format_duration

def scan_existing_episodes_from_files(digests_dir: Path, base_url: str) -> list:
    """Scan for existing episode MP3 files and return episode data."""
    episodes = []
    pattern = r"Planetterrian_Daily_Ep(\d+)_(\d{8})\.mp3"
    for mp3_file in digests_dir.glob("Planetterrian_Daily_Ep*.mp3"):
        match = re.match(pattern, mp3_file.name)
        if match:
            try:
                ep_num = int(match.group(1))
                date_str = match.group(2)
                # Parse date from filename
                episode_date = datetime.datetime.strptime(date_str, "%Y%m%d").date()
                
                # Get file size
                file_size = mp3_file.stat().st_size if mp3_file.exists() else 0
                
                # Get duration
                duration = get_audio_duration(mp3_file)
                
                episodes.append({
                    'episode_num': ep_num,
                    'date': episode_date,
                    'filename': mp3_file.name,
                    'path': mp3_file,
                    'size': file_size,
                    'duration': duration,
                    'url': f"{base_url}/digests/planetterrian/{mp3_file.name}"
                })
            except (ValueError, Exception) as e:
                logging.warning(f"Could not parse episode from file {mp3_file.name}: {e}")
    return sorted(episodes, key=lambda x: x['episode_num'])

_PT_BASE_URL = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"

def update_rss_feed(
    rss_path, episode_num, episode_title, episode_description,
    episode_date, mp3_filename, mp3_duration, mp3_path,
    base_url=_PT_BASE_URL,
):
    _engine_update_rss_feed(
        rss_path, episode_num, episode_title, episode_description,
        episode_date, mp3_filename, mp3_duration, mp3_path,
        base_url=base_url,
        audio_subdir="digests/planetterrian",
        channel_title="Planetterrian Daily",
        channel_link="https://planetterrian.com",
        channel_description="Daily science, longevity, and health discoveries. A tribe of forward-thinking innovators passionate about the planet, intertwining technology and compassion.",
        channel_author="Patrick",
        channel_email="contact@planetterrian.com",
        channel_image=f"{base_url}/planetterrian-podcast-image.jpg",
        channel_category="Science",
        guid_prefix="planetterrian-daily",
        format_duration_func=format_duration,
    )

# ========================== GENERATE PODCAST SCRIPT ==========================
if not ENABLE_PODCAST:
    logging.info("Podcast generation is disabled (ENABLE_PODCAST = False). Skipping podcast script generation, audio processing, and RSS feed updates.")
    final_mp3 = None
else:
    POD_PROMPT = f"""You are writing an 8–11 minute (1950–2600 words) solo podcast script for "Planetterrian Daily" Episode {episode_num}.

HOST: A Canadian scientist and newscaster. Voice like a solo podcaster breaking science, longevity, and health news, not robotic. Do NOT use any personal names for the host.

BRAND PERSONALITY: Planetterrian Ventures - A tribe of forward-thinking innovators passionate about the planet. Mission: Intertwine technology and compassion. Values: Technology as a force for good, sustainability, environmental consciousness.

RULES:
- Start every line with "Host:"
- Don't read URLs aloud - mention source names naturally
- Use natural dates ("today", "this morning") not exact timestamps
- Enunciate all numbers clearly
- Use ONLY information from the digest below - nothing else
- Make it sound like a real solo pod: vivid but concise, no robotic repetition
- Emphasize how discoveries benefit humanity; include planet impact only when concrete (don't force it)
- Never refer to the host by name

SCRIPT STRUCTURE:
[Intro music - 10 seconds]
Host: Welcome to Planetterrian Daily, episode {episode_num}. It is {today_str}, bringing you today's most exciting discoveries in science, longevity, and health. Thank you for joining us today. If you like the show, please like, share, rate and subscribe to the podcast, it really helps. Now let's dive into today's discoveries.

Host: Quick scan before we dive in—three stories to watch today, then we'll go through the full list in order.

[Narrate EVERY item from the digest in order - no skipping]
- For each news item: Read the title with energy, then summarize in 2–4 lines: what happened, why it matters for health/longevity, and (only if it naturally fits) one planet/sustainability implication
- Planetterrian Spotlight: Explain why this breakthrough aligns with our mission
- Daily Inspiration: Read the quote verbatim, add one encouraging sentence

[Closing]
Host: That's Planetterrian Daily for today. Remember: we're not just in the business of technology; we're in the business of making a difference. Together, we can drive change, one discovery at a time. We'll catch you tomorrow on Planetterrian Daily!

Here is today's complete formatted digest. Use ONLY this content:

{x_thread}
"""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=15),  # Reduced wait times: 1-15s instead of 2-30s
        retry=retry_if_exception_type((Exception,))
    )
    def generate_podcast_script_with_grok():
        response = client.chat.completions.create(
            model="grok-4",
            messages=[{"role": "user", "content": POD_PROMPT}],
            temperature=0.7,
            max_tokens=3500  # Reduced from 4000 for faster generation
        )
        return response
    
    logging.info("Generating podcast script with Grok (this may take 1-2 minutes)...")
    try:
        podcast_response = generate_podcast_script_with_grok()
        podcast_script = podcast_response.choices[0].message.content.strip()
        
        # Log token usage if available
        if hasattr(podcast_response, 'usage') and podcast_response.usage:
            usage = podcast_response.usage
            logging.info(f"Podcast script generation - Tokens used: {usage.total_tokens} (prompt: {usage.prompt_tokens}, completion: {usage.completion_tokens})")
            estimated_cost = (usage.total_tokens / 1000000) * 0.01
            logging.info(f"Estimated cost: ${estimated_cost:.4f}")
            
            # Track credit usage
            credit_usage["services"]["grok_api"]["podcast_script_generation"]["prompt_tokens"] = usage.prompt_tokens
            credit_usage["services"]["grok_api"]["podcast_script_generation"]["completion_tokens"] = usage.completion_tokens
            credit_usage["services"]["grok_api"]["podcast_script_generation"]["total_tokens"] = usage.total_tokens
            credit_usage["services"]["grok_api"]["podcast_script_generation"]["estimated_cost_usd"] = estimated_cost
    except Exception as e:
        logging.error(f"Grok API call for podcast script failed: {e}")
        raise

    # Save transcript
    transcript_path = digests_dir / f"podcast_transcript_{datetime.date.today():%Y%m%d}.txt"
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(f"# Planetterrian Daily – The Pod | Ep {episode_num} | {today_str}\n\n{podcast_script}")
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
    VOICE_ID = ELEVEN_VOICE_ID  # Override with ELEVENLABS_VOICE_ID to swap voices

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
    final_mp3 = digests_dir / f"Planetterrian_Daily_Ep{episode_num:03d}_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp3"
    
    MAIN_MUSIC = project_root / "science-daily.mp3"
    
    # Process and normalize voice in one step
    voice_mix = tmp_dir / "voice_normalized_mix.mp3"
    file_duration = get_audio_duration(voice_file)
    timeout_seconds = max(int(file_duration * 3) + 120, 600)
    
    logging.info(f"Processing and normalizing voice ({file_duration:.1f}s) - this may take a few minutes...")

    # First, check if voice_file exists and has content
    if not voice_file.exists():
        raise RuntimeError(f"Voice file {voice_file} does not exist!")

    voice_file_size = voice_file.stat().st_size
    logging.info(f"Voice file size: {voice_file_size} bytes")

    if voice_file_size < 1000:  # Less than 1KB is suspicious
        raise RuntimeError(f"Voice file {voice_file} is too small ({voice_file_size} bytes) - TTS may have failed")

    # Try simpler normalization first to avoid filter issues
    try:
        logging.info("Attempting voice normalization with full filter chain...")
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0", "-i", str(voice_file),
            "-af", "highpass=f=80,lowpass=f=15000,loudnorm=I=-18:TP=-1.5:LRA=11:linear=true,acompressor=threshold=-20dB:ratio=4:attack=1:release=100:makeup=2,alimiter=level_in=1:level_out=0.95:limit=0.95",
            "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
            str(voice_mix)
        ], check=True, capture_output=True, timeout=timeout_seconds)
    except subprocess.CalledProcessError as e:
        logging.warning(f"Full filter chain failed: {e}")
        logging.warning("Trying simpler normalization...")
        # Fallback to simpler processing
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0", "-i", str(voice_file),
            "-af", "loudnorm=I=-18:TP=-1.5:LRA=11:linear=true",
            "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
            str(voice_mix)
        ], check=True, capture_output=True, timeout=timeout_seconds)

    # Verify the output file was created
    if not voice_mix.exists():
        raise RuntimeError(f"Voice mix file {voice_mix} was not created!")

    voice_mix_size = voice_mix.stat().st_size
    logging.info(f"Voice mix file size: {voice_mix_size} bytes")

    if voice_mix_size < 1000:
        raise RuntimeError(f"Voice mix file {voice_mix} is too small ({voice_mix_size} bytes) - processing failed")
    
    # Check if we have background music
    has_background_music = MAIN_MUSIC.exists() if MAIN_MUSIC else False

    if not has_background_music:
        subprocess.run(["ffmpeg", "-y", "-threads", "0", "-i", str(voice_mix), "-preset", "fast", str(final_mp3)], check=True, capture_output=True)
        logging.info("Podcast ready (voice-only, no music file found)")
    else:
        # Get voice duration to calculate music timing
        voice_duration = max(get_audio_duration(voice_mix), 0.0)
        logging.info(f"Voice duration: {voice_duration:.2f} seconds")
        
        # Music timing - Professional intro with perfect overlap:
        # - 5 seconds of music alone (0-5s) - engaging intro
        # - Patrick starts talking at 5s while music is still at full volume (perfect overlap)
        # - Music continues at full volume for 3 seconds while Patrick talks (5-8s) - creates energy
        # - Music fades out smoothly over 18 seconds while Patrick continues (8-26s) - professional fade
        # - Voice continues alone after 26s
        # - 25 seconds before voice ends, music starts fading in (mixes well with voice)
        # - After voice ends, music continues for 50 seconds (30s full + 20s fade out)
        
        music_fade_in_start = max(voice_duration - 25.0, 0.0)  # 25s before voice ends
        music_fade_in_duration = min(35.0, voice_duration - music_fade_in_start)  # Fade in over 35s
        
        # OPTIMIZED: Generate independent music segments in parallel
        music_intro = tmp_dir / "music_intro.mp3"
        music_overlap = tmp_dir / "music_overlap.mp3"
        music_fadeout = tmp_dir / "music_fadeout.mp3"
        music_tail_full = tmp_dir / "music_tail_full.mp3"
        music_tail_fadeout = tmp_dir / "music_tail_fadeout.mp3"
        
        def generate_music_segment(segment_name, cmd_args):
            """Helper to generate a single music segment."""
            subprocess.run(cmd_args, check=True, capture_output=True)
        
        # Generate independent music segments in parallel (don't depend on voice_duration)
        logging.info("Generating music segments in parallel...")
        independent_segments = [
            ("intro", ["ffmpeg", "-y", "-threads", "0", "-i", str(MAIN_MUSIC), "-t", "5",
                      "-af", "volume=0.6", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                      str(music_intro)]),
            ("overlap", ["ffmpeg", "-y", "-threads", "0", "-i", str(MAIN_MUSIC), "-ss", "5", "-t", "3",
                        "-af", "volume=0.5", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                        str(music_overlap)]),
            ("fadeout", ["ffmpeg", "-y", "-threads", "0", "-i", str(MAIN_MUSIC), "-ss", "8", "-t", "18",
                        "-af", "volume=0.4,afade=t=out:curve=log:st=0:d=18", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                        str(music_fadeout)]),
            ("tail_full", ["ffmpeg", "-y", "-threads", "0", "-i", str(MAIN_MUSIC), "-ss", "55", "-t", "30",
                          "-af", "volume=0.4", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                          str(music_tail_full)]),
            ("tail_fadeout", ["ffmpeg", "-y", "-threads", "0", "-i", str(MAIN_MUSIC), "-ss", "85", "-t", "20",
                             "-af", "volume=0.4,afade=t=out:st=0:d=20", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                             str(music_tail_fadeout)]),
        ]
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(generate_music_segment, name, cmd): name for name, cmd in independent_segments}
            for future in as_completed(futures):
                segment_name = futures[future]
                try:
                    future.result()
                    logging.debug(f"Generated music segment: {segment_name}")
                except Exception as e:
                    logging.error(f"Failed to generate music segment {segment_name}: {e}")
                    raise
        
        # Generate voice-dependent segments (fadein and silence depend on voice_duration)
        middle_silence_duration = max(music_fade_in_start - 26.0, 0.0)
        music_silence = tmp_dir / "music_silence.mp3"
        music_fadein = tmp_dir / "music_fadein.mp3"
        
        voice_dependent_segments = []
        if middle_silence_duration > 0.1:
            voice_dependent_segments.append(("silence", ["ffmpeg", "-y", "-threads", "0", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                                                         "-t", f"{middle_silence_duration:.2f}", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                                                         str(music_silence)]))
        
        voice_dependent_segments.append(("fadein", ["ffmpeg", "-y", "-threads", "0", "-i", str(MAIN_MUSIC), "-ss", "25", "-t", f"{music_fade_in_duration:.2f}",
                                                    "-af", f"volume=0.4,afade=t=in:st=0:d={music_fade_in_duration:.2f}", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                                                    str(music_fadein)]))
        
        if voice_dependent_segments:
            with ThreadPoolExecutor(max_workers=len(voice_dependent_segments)) as executor:
                futures = {executor.submit(generate_music_segment, name, cmd): name for name, cmd in voice_dependent_segments}
                for future in as_completed(futures):
                    segment_name = futures[future]
                    try:
                        future.result()
                        logging.debug(f"Generated music segment: {segment_name}")
                    except Exception as e:
                        logging.error(f"Failed to generate music segment {segment_name}: {e}")
                        raise
        
        # Concatenate music and delay voice in parallel (they don't depend on each other)
        music_concat_list = tmp_dir / "music_timeline.txt"
        with open(music_concat_list, "w", encoding="utf-8") as f:
            f.write(f"file '{music_intro}'\n")
            f.write(f"file '{music_overlap}'\n")
            f.write(f"file '{music_fadeout}'\n")
            if middle_silence_duration > 0.1:
                f.write(f"file '{music_silence}'\n")
            f.write(f"file '{music_fadein}'\n")
            f.write(f"file '{music_tail_full}'\n")
            f.write(f"file '{music_tail_fadeout}'\n")
        
        background_track = tmp_dir / "background_track.mp3"
        voice_delayed = tmp_dir / "voice_delayed.mp3"
        
        logging.info("Concatenating music and delaying voice in parallel...")
        with ThreadPoolExecutor(max_workers=2) as executor:
            concat_future = executor.submit(subprocess.run,
                ["ffmpeg", "-y", "-threads", "0", "-f", "concat", "-safe", "0", "-i", str(music_concat_list),
                 "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                 str(background_track)],
                check=True, capture_output=True)
            delay_future = executor.submit(subprocess.run,
                ["ffmpeg", "-y", "-threads", "0", "-i", str(voice_mix),
                 "-af", "adelay=5000|5000",
                 "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                 str(voice_delayed)],
                check=True, capture_output=True)
            
            concat_future.result()
            delay_future.result()
        
        # Final mix: voice + music
        logging.info("Mixing voice and music...")
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0",
            "-i", str(voice_delayed),
            "-i", str(background_track),
            "-filter_complex",
            "[0:a]volume=1.0[a_voice];"
            "[1:a]volume=0.5[a_music];"  # Higher music volume for better presence
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

        logging.info("Podcast created successfully with background music")
        
        # Cleanup music temp files
        for tmp_file in [music_intro, music_overlap, music_fadeout, music_fadein, music_tail_full, music_tail_fadeout, music_silence, background_track, voice_delayed, music_concat_list]:
            if tmp_file.exists():
                try:
                    os.remove(str(tmp_file))
                except Exception:
                    pass

    # Update RSS feed
    # Fail loudly if podcast generation was enabled but failed
    if ENABLE_PODCAST and not TEST_MODE:
        if not final_mp3 or not final_mp3.exists():
            error_msg = f"❌ Podcast generation was enabled but failed - final_mp3={final_mp3}"
            if final_mp3:
                error_msg += f", exists={final_mp3.exists()}"
            error_msg += ". This means the episode will NOT appear in the RSS feed or GitHub page."
            logging.error(error_msg)
            raise RuntimeError(error_msg)  # Fail the workflow so it's visible
    
    if final_mp3 and final_mp3.exists():
        try:
            audio_duration = get_audio_duration(final_mp3)
            episode_title = f"Planetterrian Daily - Episode {episode_num} - {today_str}"
            episode_description = f"Daily science, longevity, and health discoveries for {today_str}."
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
                base_url="https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
            )
            logging.info(f"RSS feed updated with Episode {episode_num}")
        except Exception as e:
            logging.error(f"Failed to update RSS feed: {e}", exc_info=True)
    
    # Check if any episodes are missing from RSS feed
    try:
        existing_episodes = scan_existing_episodes_from_files(
            digests_dir, 
            "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
        )
        
        # Parse RSS feed to see what episodes are already there
        rss_episodes = set()
        if rss_path.exists():
            try:
                tree = ET.parse(str(rss_path))
                root = tree.getroot()
                channel = root.find('channel')
                if channel is not None:
                    for item in channel.findall('item'):
                        itunes_episode = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}episode')
                        if itunes_episode is not None and itunes_episode.text:
                            try:
                                rss_episodes.add(int(itunes_episode.text))
                            except ValueError:
                                pass
            except Exception as e:
                logging.warning(f"Could not parse RSS feed to check for missing episodes: {e}")
        
        # Find episodes that exist as files but not in RSS feed
        missing_episodes = [ep for ep in existing_episodes if ep['episode_num'] not in rss_episodes]
        
        if missing_episodes:
            logging.warning(f"Found {len(missing_episodes)} episode(s) missing from RSS feed: {[ep['episode_num'] for ep in missing_episodes]}")
            # Add missing episodes to RSS feed
            for ep_data in missing_episodes:
                try:
                    episode_title = f"Planetterrian Daily - Episode {ep_data['episode_num']} - {ep_data['date'].strftime('%B %d, %Y')}"
                    episode_description = f"Daily science, longevity, and health discoveries for {ep_data['date'].strftime('%B %d, %Y')}."
                    
                    update_rss_feed(
                        rss_path=rss_path,
                        episode_num=ep_data['episode_num'],
                        episode_title=episode_title,
                        episode_description=episode_description,
                        episode_date=ep_data['date'],
                        mp3_filename=ep_data['filename'],
                        mp3_duration=ep_data['duration'],
                        mp3_path=ep_data['path'],
                        base_url="https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
                    )
                    logging.info(f"Added missing Episode {ep_data['episode_num']} to RSS feed")
                except Exception as e:
                    logging.error(f"Failed to add missing episode {ep_data['episode_num']} to RSS feed: {e}", exc_info=True)
    except Exception as e:
        logging.warning(f"Could not scan for missing episodes: {e}", exc_info=True)

# Always check for missing episodes, even if podcast generation was disabled or failed
logging.info("Checking for any episodes missing from RSS feed...")
try:
    existing_episodes = scan_existing_episodes_from_files(
        digests_dir, 
        "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
    )
    
    # Parse RSS feed to see what episodes are already there
    rss_episodes = set()
    if rss_path.exists():
        try:
            tree = ET.parse(str(rss_path))
            root = tree.getroot()
            channel = root.find('channel')
            if channel is not None:
                for item in channel.findall('item'):
                    itunes_episode = item.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}episode')
                    if itunes_episode is not None and itunes_episode.text:
                        try:
                            rss_episodes.add(int(itunes_episode.text))
                        except ValueError:
                            pass
        except Exception as e:
            logging.warning(f"Could not parse RSS feed to check for missing episodes: {e}")
    
    # Find episodes that exist as files but not in RSS feed
    missing_episodes = [ep for ep in existing_episodes if ep['episode_num'] not in rss_episodes]
    
    if missing_episodes:
        logging.warning(f"Found {len(missing_episodes)} episode(s) missing from RSS feed: {[ep['episode_num'] for ep in missing_episodes]}")
        # Add missing episodes to RSS feed
        for ep_data in missing_episodes:
            try:
                episode_title = f"Planetterrian Daily - Episode {ep_data['episode_num']} - {ep_data['date'].strftime('%B %d, %Y')}"
                episode_description = f"Daily science, longevity, and health discoveries for {ep_data['date'].strftime('%B %d, %Y')}."
                
                update_rss_feed(
                    rss_path=rss_path,
                    episode_num=ep_data['episode_num'],
                    episode_title=episode_title,
                    episode_description=episode_description,
                    episode_date=ep_data['date'],
                    mp3_filename=ep_data['filename'],
                    mp3_duration=ep_data['duration'],
                    mp3_path=ep_data['path'],
                    base_url="https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
                )
                logging.info(f"Added missing Episode {ep_data['episode_num']} to RSS feed")
            except Exception as e:
                logging.error(f"Failed to add missing episode {ep_data['episode_num']} to RSS feed: {e}", exc_info=True)
    else:
        logging.info("All existing episodes are in the RSS feed")
except Exception as e:
    logging.warning(f"Could not scan for missing episodes: {e}", exc_info=True)

# Save summary to GitHub Pages and post link to X
if ENABLE_GITHUB_SUMMARIES:
    try:
        # Save the full summary to GitHub Pages JSON
        _base_url = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
        _audio_url = None
        try:
            if ENABLE_PODCAST and final_mp3:
                _audio_url = f"{_base_url}/digests/planetterrian/{final_mp3.name}"
        except Exception:
            _audio_url = None

        summary_json_file = save_summary_to_github_pages(
            formatted_thread.strip(),
            digests_dir,
            "planet",
            episode_num=episode_num if 'episode_num' in globals() else None,
            episode_title=episode_title if 'episode_title' in globals() else None,
            audio_url=_audio_url,
            rss_url=f"{_base_url}/planetterrian_podcast.rss",
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
        # Create link to the Planetterrian summaries page
        summaries_url = "https://patricknovak.github.io/Tesla-shorts-time/planetterrian-summaries.html"
        rss_url = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main/planetterrian_podcast.rss"

        # Create a teaser post with link to full summary
        today = datetime.datetime.now()
        teaser_text = (
            f"🌍🧬 Planetterrian Daily — {today.strftime('%b %d, %Y')}\n"
            f"Top science + health stories (last 48h) + new episode.\n"
            f"Read & listen: {summaries_url}\n"
            f"RSS: {rss_url}\n"
            f"#Science #Health #Longevity"
        )
        teaser_text = _enforce_x_char_limit(teaser_text, max_chars=_env_int("X_TWEET_MAX_CHARS", 280))

        # Track X API post call
        credit_usage["services"]["x_api"]["post_calls"] += 1

        # Post the teaser with link
        tweet = x_client.create_tweet(text=teaser_text)
        tweet_id = tweet.data['id']
        thread_url = f"https://x.com/planetterrian/status/{tweet_id}"
        logging.info(f"DIGEST LINK POSTED → {thread_url}")
    except Exception as e:
        logging.error(f"X post failed: {e}")

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
print("PLANETTERRIAN DAILY — FULLY AUTOMATED RUN COMPLETE")
print(f"X Thread → {x_path}")
print(f"Podcast → {final_mp3}")
print("="*80)

