#!/usr/bin/env python3
"""
Lube Change - Oilers Daily News – FULL AUTO X + PODCAST MACHINE
Daily Edmonton Oilers News Digest (Jason Potter in Hinton, Alberta)
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
from difflib import SequenceMatcher
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
import feedparser
from typing import List, Dict, Any
import tweepy
import shutil
import asyncio
import websockets
import base64

# ========================== LOGGING ==========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

# ========================== CONFIGURATION ==========================
# Set to True to test digest generation only (skips podcast and X posting)
TEST_MODE = False  # Set to False for full run

# Set to False to disable X posting (thread will still be generated and saved)
ENABLE_X_POSTING = True

# Set to False to disable podcast generation and RSS feed updates
ENABLE_PODCAST = True

# Link validation is currently disabled - validation functions have been removed
# Set to True and re-implement validation functions if needed in the future
ENABLE_LINK_VALIDATION = False


# ========================== NUMBER TO WORDS CONVERTER ==========================
def number_to_words(num: float) -> str:
    """
    Convert numbers to words for better TTS pronunciation.
    Handles integers and decimals.
    """
    # Define digit names for decimal conversion
    digit_names = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine']
    
    def convert_under_1000(n):
        """Convert numbers under 1000 to words."""
        ones = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine',
                'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen',
                'seventeen', 'eighteen', 'nineteen']
        tens = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']
        
        if n == 0:
            return 'zero'
        if n < 20:
            return ones[n]
        if n < 100:
            return tens[n // 10] + ('-' + ones[n % 10] if n % 10 else '')
        if n < 1000:
            result = ones[n // 100] + ' hundred'
            remainder = n % 100
            if remainder:
                result += ' ' + convert_under_1000(remainder)
            return result
        return str(n)
    
    # Handle negative numbers
    is_negative = num < 0
    num = abs(num)
    
    # Split into integer and decimal parts
    integer_part = int(num)
    decimal_part = num - integer_part
    
    # Convert integer part
    if integer_part == 0:
        result = 'zero'
    elif integer_part < 1000:
        result = convert_under_1000(integer_part)
    elif integer_part < 1000000:
        thousands = integer_part // 1000
        remainder = integer_part % 1000
        result = convert_under_1000(thousands) + ' thousand'
        if remainder:
            result += ' ' + convert_under_1000(remainder)
    else:
        # For very large numbers, just return the number (TTS usually handles these)
        result = str(integer_part)
    
    # Convert decimal part
    if decimal_part > 0:
        # Convert decimal to words (e.g., 0.17 -> "point one seven")
        decimal_str = f"{decimal_part:.10f}".rstrip('0').rstrip('.')
        if '.' in decimal_str:
            decimal_digits = decimal_str.split('.')[1]
            decimal_words = ' '.join([digit_names[int(d)] if d.isdigit() and int(d) < 10 else d for d in decimal_digits])
            result += ' point ' + decimal_words
    
    return ('negative ' if is_negative else '') + result

# ========================== PRONUNCIATION FIXER v3 – ACRONYMS + NUMBERS ==========================
def fix_pronunciation(text: str) -> str:
    """
    Forces correct spelling of hockey/Oilers acronyms and converts numbers to words
    for better TTS pronunciation on Cartesia.
    """
    import re

    # List of acronyms that must be spelled out letter-by-letter
    acronyms = {
        "NHL": "N H L",
        "NHLPA": "N H L P A",
        "AHL": "A H L",
        "WHL": "W H L",
        "OHL": "O H L",
        "QMJHL": "Q M J H L",
        "PP": "power play",
        "PK": "penalty kill",
        "SHG": "short-handed goal",
        "PPG": "power play goal",
        "OT": "overtime",
        "SO": "shootout",
        "GAA": "G A A",
        "SV%": "save percentage",
        "PIM": "P I M",
        "TOI": "time on ice",
        "CF%": "Corsi for percentage",
        "xGF": "expected goals for",
        "HDCF": "high danger chances for",
    }

    # Invisible zero-width non-breaking space / word joiner
    ZWJ = "\u2060"   # U+2060 WORD JOINER — this one is safe

    for acronym, spelled in acronyms.items():
        # Build a regex that only matches the acronym when it's a whole word
        pattern = rf'(?<!\w){re.escape(acronym)}(?!\w)'
        replacement = ZWJ.join(list(spelled))
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Convert episode numbers (e.g., "episode 336" → "episode three hundred thirty-six")
    def replace_episode_number(match):
        episode_text = match.group(1)
        num_str = match.group(2)
        try:
            num = int(num_str)
            words = number_to_words(num)
            return f"{episode_text} {words}"
        except ValueError:
            return match.group(0)
    
    text = re.sub(r'(episode\s+)(\d+)', replace_episode_number, text, flags=re.IGNORECASE)
    
    # Convert percentages (e.g., "+3.59%" → "plus three point five nine percent")
    def replace_percentage(match):
        sign = match.group(1) if match.group(1) else ''
        num_str = match.group(2)
        try:
            num = float(num_str)
            words = number_to_words(abs(num))
            if sign == '+':
                sign_word = 'plus'
            elif sign == '-':
                sign_word = 'minus'
            else:
                sign_word = ''
            result = f"{sign_word} {words} percent" if sign_word else f"{words} percent"
            return result.strip()
        except ValueError:
            return match.group(0)
    
    text = re.sub(r'([\+\-]?)(\d+\.?\d*)\s*%', replace_percentage, text)
    
    return text

def generate_episode_thumbnail(base_image_path, episode_num, date_str, output_path):
    img = Image.open(base_image_path)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except IOError:
        font = ImageFont.load_default()
    draw.text((50, 50), f"Episode {episode_num}", font=font, fill=(255, 255, 255))
    draw.text((50, 100), date_str, font=font, fill=(255, 255, 255))
    img.save(output_path, "PNG")

# ========================== PATHS & ENV ==========================
script_dir = Path(__file__).resolve().parent        # → .../digests
project_root = script_dir.parent                      # → .../tesla_shorts_time
env_path = project_root / ".env"

if not env_path.exists():
    raise FileNotFoundError(f".env not found at {env_path}")

load_dotenv(dotenv_path=env_path)

# Required keys (X credentials for @lubechange_oilers account - using same as planetterrian for now)
required = [
    "GROK_API_KEY"
]
if ENABLE_X_POSTING:
    required.extend([
        "PLANETTERRIAN_X_CONSUMER_KEY",  # Reusing for now, can be updated later
        "PLANETTERRIAN_X_CONSUMER_SECRET",
        "PLANETTERRIAN_X_ACCESS_TOKEN",
        "PLANETTERRIAN_X_ACCESS_TOKEN_SECRET",
        "PLANETTERRIAN_X_BEARER_TOKEN"
    ])
for var in required:
    if not os.getenv(var):
        raise OSError(f"Missing {var} in .env")

# Cartesia API key - use env var if available, otherwise use provided key
if not os.getenv("CARTESIA_API_KEY"):
    logging.warning("CARTESIA_API_KEY not found in .env, using provided fallback key")
    os.environ["CARTESIA_API_KEY"] = "sk_car_qGDH5TeA4D1q43UmvF7S1m"

# ========================== DATE ==========================
# Get current date and time in MST (Mountain Standard Time - Alberta)
mst_tz = ZoneInfo("America/Edmonton")
now_mst = datetime.datetime.now(mst_tz)
today_str = now_mst.strftime("%B %d, %Y at %I:%M %p MST")
yesterday_iso = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
seven_days_ago_iso = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

# Folders - use absolute paths
digests_dir = project_root / "digests" / "lubechange"
digests_dir.mkdir(exist_ok=True, parents=True)

# Determine episode number by finding the highest existing episode number and incrementing
def get_next_episode_number(rss_path: Path, digests_dir: Path) -> int:
    """Get the next episode number by finding the highest existing episode number."""
    max_episode = 0
    
    # Check RSS feed first
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
                            ep_num = int(itunes_episode.text)
                            max_episode = max(max_episode, ep_num)
                        except ValueError:
                            pass
        except Exception as e:
            logging.warning(f"Could not parse RSS feed to find episode number: {e}")
    
    # Also check existing MP3 files
    pattern = r"Lube_Change_Ep(\d+)_\d{8}\.mp3"
    for mp3_file in digests_dir.glob("Lube_Change_Ep*.mp3"):
        match = re.match(pattern, mp3_file.name)
        if match:
            try:
                ep_num = int(match.group(1))
                max_episode = max(max_episode, ep_num)
            except ValueError:
                pass
    
    # Return next episode number (increment by 1)
    next_episode = max_episode + 1
    logging.info(f"Next episode number: {next_episode} (highest existing: {max_episode})")
    return next_episode

# Get the next episode number
rss_path = project_root / "lubechange_podcast.rss"
episode_num = get_next_episode_number(rss_path, digests_dir)

# ========================== CREDIT TRACKING ==========================
# Initialize credit usage tracking
credit_usage = {
    "date": datetime.date.today().isoformat(),
    "episode_number": episode_num,
    "services": {
        "grok_api": {
            "x_thread_generation": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0
            },
            "podcast_script_generation": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0
            },
            "total_tokens": 0,
            "total_cost_usd": 0.0
        },
        "cartesia_api": {
            "characters": 0,
            "estimated_cost_usd": 0.0
        },
        "x_api": {
            "search_calls": 0,
            "post_calls": 0,
            "total_calls": 0
        }
    },
    "total_estimated_cost_usd": 0.0
}

def save_credit_usage(usage_data: dict, output_dir: Path):
    """Save credit usage to a JSON file."""
    try:
        # Calculate totals
        grok_total = (
            usage_data["services"]["grok_api"]["x_thread_generation"]["total_tokens"] +
            usage_data["services"]["grok_api"]["podcast_script_generation"]["total_tokens"]
        )
        usage_data["services"]["grok_api"]["total_tokens"] = grok_total
        usage_data["services"]["grok_api"]["total_cost_usd"] = (
            usage_data["services"]["grok_api"]["x_thread_generation"]["estimated_cost_usd"] +
            usage_data["services"]["grok_api"]["podcast_script_generation"]["estimated_cost_usd"]
        )
        
        usage_data["services"]["x_api"]["total_calls"] = (
            usage_data["services"]["x_api"]["search_calls"] +
            usage_data["services"]["x_api"]["post_calls"]
        )
        
        # Calculate total cost (Cartesia pricing: check their pricing, using estimate for now)
        # Cartesia pricing varies, using conservative estimate
        cartesia_cost = (usage_data["services"]["cartesia_api"]["characters"] / 1000) * 0.02  # Estimate
        usage_data["services"]["cartesia_api"]["estimated_cost_usd"] = cartesia_cost
        
        usage_data["total_estimated_cost_usd"] = (
            usage_data["services"]["grok_api"]["total_cost_usd"] +
            usage_data["services"]["cartesia_api"]["estimated_cost_usd"]
        )
        
        # Save to JSON file
        filename = f"credit_usage_{usage_data['date']}_ep{usage_data['episode_number']:03d}.json"
        filepath = output_dir / filename
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(usage_data, f, indent=2)
        
        logging.info(f"Credit usage saved to {filepath}")
        
        # Also log summary
        logging.info("="*80)
        logging.info("CREDIT USAGE SUMMARY")
        logging.info("="*80)
        logging.info(f"Grok API (X Thread): {usage_data['services']['grok_api']['x_thread_generation']['total_tokens']} tokens (${usage_data['services']['grok_api']['x_thread_generation']['estimated_cost_usd']:.4f})")
        logging.info(f"Grok API (Podcast Script): {usage_data['services']['grok_api']['podcast_script_generation']['total_tokens']} tokens (${usage_data['services']['grok_api']['podcast_script_generation']['estimated_cost_usd']:.4f})")
        logging.info(f"Grok API Total: {usage_data['services']['grok_api']['total_tokens']} tokens (${usage_data['services']['grok_api']['total_cost_usd']:.4f})")
        logging.info(f"Cartesia API: {usage_data['services']['cartesia_api']['characters']} characters (${usage_data['services']['cartesia_api']['estimated_cost_usd']:.4f})")
        logging.info(f"X API: {usage_data['services']['x_api']['total_calls']} API calls (search: {usage_data['services']['x_api']['search_calls']}, post: {usage_data['services']['x_api']['post_calls']})")
        logging.info(f"TOTAL ESTIMATED COST: ${usage_data['total_estimated_cost_usd']:.4f}")
        logging.info("="*80)
        
    except Exception as e:
        logging.error(f"Failed to save credit usage: {e}", exc_info=True)

tmp_dir = Path(tempfile.gettempdir()) / "tts"
tmp_dir.mkdir(exist_ok=True, parents=True)

# ========================== CLIENTS ==========================
# Grok client with timeout settings
client = OpenAI(
    api_key=os.getenv("GROK_API_KEY"), 
    base_url="https://api.x.ai/v1",
    timeout=300.0  # 5 minute timeout for API calls
)
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY")
CARTESIA_API = "https://api.cartesia.ai"

# ========================== STEP 1: FETCH OILERS NEWS FROM RSS FEEDS ==========================
logging.info("Step 1: Fetching Edmonton Oilers news from RSS feeds for the last 24 hours...")

def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity ratio between two texts (0.0 to 1.0)."""
    if not text1 or not text2:
        return 0.0
    # Normalize: lowercase, remove extra whitespace
    text1_norm = ' '.join(text1.lower().split())
    text2_norm = ' '.join(text2.lower().split())
    return SequenceMatcher(None, text1_norm, text2_norm).ratio()

def remove_similar_items(items, similarity_threshold=0.7, get_text_func=None):
    """
    Remove similar items from a list based on text similarity.
    """
    if not items:
        return items
    
    if get_text_func is None:
        def get_text_func(item):
            if isinstance(item, dict):
                return item.get('title', '') or item.get('text', '') or item.get('description', '')
            return str(item)
    
    filtered = []
    for item in items:
        item_text = get_text_func(item)
        if not item_text:
            continue
        
        is_similar = False
        for accepted_item in filtered:
            accepted_text = get_text_func(accepted_item)
            similarity = calculate_similarity(item_text, accepted_text)
            if similarity >= similarity_threshold:
                is_similar = True
                logging.debug(f"Filtered similar item (similarity: {similarity:.2f}): {item_text[:50]}...")
                break
        
        if not is_similar:
            filtered.append(item)
    
    return filtered

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.RequestException, requests.Timeout))
)
def fetch_oilers_news():
    """Fetch Edmonton Oilers news from RSS feeds for the last 24 hours."""
    import feedparser
    
    # Edmonton Oilers and NHL RSS feeds
    rss_feeds = [
        # Official NHL and Oilers sources
        "https://www.nhl.com/oilers/rss.xml",
        "https://www.nhl.com/rss/news",
        "https://www.nhl.com/rss/scores",
        
        # Sports news outlets with Oilers coverage
        "https://www.tsn.ca/rss/nhl",
        "https://www.sportsnet.ca/rss/nhl",
        "https://www.espn.com/espn/rss/nhl/news",
        "https://www.espn.com/espn/rss/nhl/news",
        "https://www.cbssports.com/rss/headlines/nhl",
        "https://www.thescore.com/nhl/rss",
        
        # Canadian sports media
        "https://www.cbc.ca/sports/hockey/rss",
        "https://www.theglobeandmail.com/sports/hockey/rss",
        "https://www.edmontonjournal.com/sports/hockey/edmonton-oilers/rss",
        "https://www.edmontonsun.com/sports/hockey/edmonton-oilers/rss",
        
        # Hockey-specific sites
        "https://www.nhl.com/news/rss",
        "https://www.hockeynews.com/rss",
        "https://www.thehockeynews.com/rss",
        "https://www.dailyfaceoff.com/rss",
        "https://www.puckprose.com/rss",
        
        # Analytics and advanced stats
        "https://www.naturalstattrick.com/rss",
        "https://www.hockey-reference.com/rss",
    ]
    
    # Calculate cutoff time (last 24 hours)
    cutoff_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    
    all_articles = []
    raw_articles = []
    
    # Oilers/NHL keywords to filter articles
    oilers_keywords = [
        "oilers", "edmonton", "connor mcdavid", "leon draisaitl", "evander kane",
        "zach hyman", "stuart skinner", "jack campbell", "darnell nurse", "evan bouchard",
        "nhl", "hockey", "nhl playoffs", "stanley cup", "western conference",
        "pacific division", "roger place", "rogers place", "ice district",
        "alberta", "edmonton oilers", "oilers news", "oilers trade", "oilers game",
        "oilers score", "oilers roster", "oilers injury", "oilers draft"
    ]
    
    logging.info(f"Fetching Oilers news from {len(rss_feeds)} RSS feeds...")
    
    for feed_url in rss_feeds:
        source_name = "Unknown"
        try:
            feed = feedparser.parse(feed_url)
            
            if feed.bozo and feed.bozo_exception:
                logging.warning(f"Failed to parse RSS feed {feed_url}: {feed.bozo_exception}")
                continue
            
            source_name = feed.feed.get("title", "Unknown")
            # Map common feed sources
            if "nhl.com" in feed_url.lower():
                if "oilers" in feed_url.lower():
                    source_name = "NHL.com - Edmonton Oilers"
                else:
                    source_name = "NHL.com"
            elif "tsn.ca" in feed_url.lower():
                source_name = "TSN"
            elif "sportsnet.ca" in feed_url.lower():
                source_name = "Sportsnet"
            elif "espn.com" in feed_url.lower():
                source_name = "ESPN"
            elif "cbssports.com" in feed_url.lower():
                source_name = "CBS Sports"
            elif "thescore.com" in feed_url.lower():
                source_name = "The Score"
            elif "cbc.ca" in feed_url.lower():
                source_name = "CBC Sports"
            elif "edmontonjournal.com" in feed_url.lower():
                source_name = "Edmonton Journal"
            elif "edmontonsun.com" in feed_url.lower():
                source_name = "Edmonton Sun"
            elif "thehockeynews.com" in feed_url.lower():
                source_name = "The Hockey News"
            elif "dailyfaceoff.com" in feed_url.lower():
                source_name = "Daily Faceoff"
            elif "naturalstattrick.com" in feed_url.lower():
                source_name = "Natural Stat Trick"
            
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
                
                # Check if article is Oilers/NHL-related
                title_desc_lower = (title + " " + description).lower()
                if not any(keyword in title_desc_lower for keyword in oilers_keywords):
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
    
    logging.info(f"Filtered to {len(formatted_articles)} unique Oilers news articles")
    filtered_result = formatted_articles[:15]  # Return top 15 for selection
    return filtered_result, raw_articles

oilers_news, raw_news_articles = fetch_oilers_news()

# ========================== SAVE RAW DATA ==========================
def save_raw_data_and_generate_html(raw_news, output_dir: Path):
    """Save raw data to JSON and generate HTML archive."""
    date_str = datetime.date.today().isoformat()
    formatted_date = datetime.date.today().strftime("%B %d, %Y")
    
    raw_data = {
        "date": date_str,
        "rss_feeds": {
            "total_articles": len(raw_news),
            "articles": raw_news
        }
    }
    
    # Save JSON
    json_path = output_dir / f"raw_data_{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2, ensure_ascii=False)
    
    logging.info(f"Raw data saved to {json_path}")
    
    # Generate simple HTML
    html_path = output_dir / f"raw_data_{date_str}.html"
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lube Change Raw Data - {formatted_date}</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #0a0f1a; color: #fff; }}
        h1 {{ color: #FF4C00; }}
        .article {{ margin: 20px 0; padding: 15px; background: #1a2332; border-radius: 8px; }}
        .article h3 {{ color: #FF4C00; margin-top: 0; }}
        .article a {{ color: #1C4A8C; }}
    </style>
</head>
<body>
    <h1>Lube Change Raw Data - {formatted_date}</h1>
    <p>Total Articles: {len(raw_news)}</p>
"""
    for article in raw_news:
        html_content += f"""
    <div class="article">
        <h3>{html.escape(article.get('title', 'No title'))}</h3>
        <p><strong>Source:</strong> {html.escape(article.get('source', 'Unknown'))}</p>
        <p><strong>Published:</strong> {html.escape(article.get('publishedAt', 'Unknown'))}</p>
        <p>{html.escape(article.get('description', '')[:200])}...</p>
        <p><a href="{html.escape(article.get('url', ''))}" target="_blank">Read more</a></p>
    </div>
"""
    html_content += """
</body>
</html>
"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    logging.info(f"Raw data HTML saved to {html_path}")
    
    return json_path, html_path

# Save raw data
raw_json_path, raw_html_path = save_raw_data_and_generate_html(
    raw_news_articles, 
    digests_dir
)

# ========================== STEP 2: GENERATE X THREAD WITH GROK ==========================
logging.info("Step 2: Generating Lube Change - Oilers Daily News digest with Grok...")

# Format news articles for the prompt
news_section = ""
if oilers_news:
    news_section = "## PRE-FETCHED OILERS NEWS ARTICLES (from RSS feeds - last 24 hours):\n\n"
    for i, article in enumerate(oilers_news[:20], 1):
        news_section += f"{i}. **{article['title']}**\n"
        news_section += f"   Source: {article['source']}\n"
        news_section += f"   Published: {article['publishedAt']}\n"
        if article.get('description'):
            news_section += f"   Description: {article['description'][:200]}...\n"
        news_section += f"   URL: {article['url']}\n\n"
else:
    news_section = "## PRE-FETCHED OILERS NEWS ARTICLES: None available\n\n"

X_PROMPT = f"""
# Lube Change - Oilers Daily News
**Date:** {today_str}
🏒 Lube Change Podcast: Daily Edmonton Oilers News from the Heart of Oil Country

{news_section}

You are an elite Edmonton Oilers news curator producing the daily "Lube Change - Oilers Daily News" newsletter. Use ONLY the pre-fetched news articles above. Do NOT hallucinate, invent, or search for new content/URLs—stick to exact provided links.

**BRAND PERSONALITY:**
- Host: Jason Potter from Hinton, Alberta - in the heart of Oil Country
- Passionate, knowledgeable Oilers fan with deep love for the team
- Authentic Alberta voice, proud of Oil Country
- Focus: Breaking Oilers news, game recaps, trades, roster moves, player updates
- Tone: Enthusiastic, knowledgeable, passionate about the Oilers, authentic Albertan
- Audience: Die-hard Oilers fans who want the latest news and analysis

### MANDATORY SELECTION & COUNTS (CRITICAL - FOLLOW EXACTLY)
- **News**: You MUST select EXACTLY 15 unique articles. If you have fewer than 15 available, use ALL of them and number them 1 through N. If you have more than 15, select the BEST 15. Prioritize high-quality sources; each must cover a DIFFERENT story/angle.
- **Diversity Check**: Verify no similar content; each item must cover a DIFFERENT angle.

### FORMATTING (EXACT—USE MARKDOWN AS SHOWN)
# Lube Change - Oilers Daily News
**Date:** {today_str}
🏒 **Lube Change** - Your Daily Dose of Oilers News from Oil Country

━━━━━━━━━━━━━━━━━━━━
### Top 15 Oilers Stories
1. **Title (One Line): DD Month, YYYY, HH:MM AM/PM MST, Source Name**  
   2–4 sentences: Start with what happened, explain why it matters for Oilers fans. End with: Source: [EXACT URL FROM PRE-FETCHED—no mods]
2. [Repeat format for 3-15; if <15 items, stop at available count, add a blank line after each item]

━━━━━━━━━━━━━━━━━━━━
### Oilers Spotlight
One major story or development that Oilers fans need to know about. Explain why this matters for the team and fans.

━━━━━━━━━━━━━━━━━━━━
### Oilers Historical Fact
Share one interesting, lesser-known historical fact about the Edmonton Oilers. This could be about a player, a game, a season, a record, or team history. Make it engaging and something that even die-hard fans might not know. Keep it to 2-3 sentences.

━━━━━━━━━━━━━━━━━━━━
### The Drip
What are Oilers fans and analysts talking about right now? What do they think the team needs to do or change? This is the current conversation, buzz, or hot topic in Oil Country. It could be about roster moves, coaching, strategy, player performance, or team needs. Keep it to 3-4 sentences and make it feel like you're capturing the pulse of Oil Country.

━━━━━━━━━━━━━━━━━━━━
### Oil Country Moment
One inspiring or memorable moment from Oilers history, current team, or fan culture. End with: "Let's go Oilers!"

[2-3 sentence uplifting sign-off about the Oilers and Oil Country pride.]

### TONE & STYLE
- Enthusiastic, passionate, knowledgeable about the Oilers
- Authentic Alberta voice
- Focus on what matters to Oilers fans
- Timestamps: Accurate MST/MDT

Output today's edition exactly as formatted.
"""

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((Exception,))
)
def generate_digest_with_grok():
    """Generate digest with retry logic"""
    response = client.chat.completions.create(
        model="grok-4",
        messages=[{"role": "user", "content": X_PROMPT}],
        temperature=0.7,
        max_tokens=4000,
        extra_body={"search_parameters": {"mode": "off"}}
    )
    return response

try:
    response = generate_digest_with_grok()
    x_thread = response.choices[0].message.content.strip()
    
    # Log token usage and cost
    if hasattr(response, 'usage') and response.usage:
        usage = response.usage
        logging.info(f"Grok API - Tokens used: {usage.total_tokens} (prompt: {usage.prompt_tokens}, completion: {usage.completion_tokens})")
        estimated_cost = (usage.total_tokens / 1000000) * 0.01
        logging.info(f"Estimated cost: ${estimated_cost:.4f}")
        
        # Track credit usage
        credit_usage["services"]["grok_api"]["x_thread_generation"]["prompt_tokens"] = usage.prompt_tokens
        credit_usage["services"]["grok_api"]["x_thread_generation"]["completion_tokens"] = usage.completion_tokens
        credit_usage["services"]["grok_api"]["x_thread_generation"]["total_tokens"] = usage.total_tokens
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
x_path = digests_dir / f"Lube_Change_{datetime.date.today():%Y%m%d}.md"
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
    logging.info("@lubechange_oilers X posting client ready")
else:
    logging.info("X posting is disabled (ENABLE_X_POSTING = False)")

# ========================== GENERATE PODCAST SCRIPT ==========================
# Initialize audio_files list to prevent NameError in cleanup
audio_files = []
final_mp3 = None

if not ENABLE_PODCAST:
    logging.info("Podcast generation is disabled (ENABLE_PODCAST = False). Skipping podcast script generation, audio processing, and RSS feed updates.")
else:
    POD_PROMPT = f"""You are writing an 8–11 minute (1950–2600 words) solo podcast script for "Lube Change - Oilers Daily News" Episode {episode_num}.

HOST: Jason Potter from Hinton, Alberta - in the heart of Oil Country. Authentic Albertan voice, passionate Oilers fan, knowledgeable about hockey and the Oilers. Voice like a sports radio host breaking Oilers news, not robotic.

BRAND PERSONALITY: Lube Change - Oilers Daily News. Daily Edmonton Oilers news from Oil Country. Passionate, knowledgeable, authentic Alberta voice.

RULES:
- Start every line with "Jason:"
- Don't read URLs aloud - mention source names naturally
- Use natural dates ("today", "this morning") not exact timestamps
- Enunciate all numbers clearly
- Use ONLY information from the digest below - nothing else
- Emphasize Oilers pride and Oil Country spirit
- Use authentic Alberta/hockey terminology

SCRIPT STRUCTURE:
[Intro music - 10 seconds]
Jason: Welcome to Lube Change - Oilers Daily News, episode {episode_num}. It is {today_str}. I'm Jason Potter coming to you from Hinton, Alberta, in the heart of Oil Country. Thank you for joining us today. If you like the show, please like, share, rate and subscribe to the podcast, it really helps. Now let's dive into today's Oilers news.

[Narrate EVERY item from the digest in order - no skipping]
- For each news item: Read the title with enthusiasm, then explain the story and why it matters for Oilers fans
- Oilers Spotlight: Explain why this story is important for the team and fans
- Oilers Historical Fact: Share the historical fact with enthusiasm and context
- The Drip: Present what fans are talking about with energy, like you're breaking the latest buzz
- Oil Country Moment: Share the moment with passion and Oilers pride

[FIRST AD - Planetterrian]
Jason: [Write an enthusiastic, natural ad for Planetterrian Daily. Must include: This podcast is made possible by Planetterrian Daily. It's a daily science, longevity, and health podcast hosted by Patrick in Vancouver. It covers groundbreaking scientific discoveries, health breakthroughs, and cutting-edge research. Mention that listeners can find it wherever they get podcasts or visit planetterrian.com. Include the tagline about technology meeting compassion. Make it sound natural and enthusiastic, like Jason is genuinely excited about the podcast. Keep it to 4-5 sentences.]

[SECOND AD - Tesla Shorts Time]
Jason: [Write an enthusiastic, natural ad for Tesla Shorts Time Daily. Must include: Lube Change is also made possible by Tesla Shorts Time Daily. It's a daily podcast about Tesla news, stock updates, and electric vehicles hosted by Patrick. It covers new vehicle releases, stock movements, and all the latest Tesla developments. Perfect for Tesla fans and investors. Mention listeners can subscribe wherever they get podcasts. Thank Tesla Shorts Time for making Lube Change possible. Make it sound natural and enthusiastic, like Jason is genuinely excited about the podcast. Keep it to 4-5 sentences.]

[Closing]
Jason: That's Lube Change - Oilers Daily News for today. Thanks for tuning in from Oil Country. Let's go Oilers! We'll catch you tomorrow on Lube Change!

Here is today's complete formatted digest. Use ONLY this content:

{x_thread}
"""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((Exception,))
    )
    def generate_podcast_script_with_grok():
        response = client.chat.completions.create(
            model="grok-4",
            messages=[{"role": "user", "content": POD_PROMPT}],
            temperature=0.7,
            max_tokens=4000
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
        f.write(f"# Lube Change - Oilers Daily News | Ep {episode_num} | {today_str}\n\n{podcast_script}")
    logging.info("Natural podcast script generated")

    # ========================== CARTESIA TTS ==========================
    # Cartesia voice ID - using a default voice, can be customized
    # You may need to get a voice ID from Cartesia's API
    # For now using the provided API key directly
    CARTESIA_VOICE_ID = "a0e99841-438c-4a64-b679-ae501e7d6091"  # Default voice, update as needed

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout, Exception))
    )
    async def speak_cartesia(text: str, voice_id: str, filename: str):
        """Generate speech using Cartesia TTS via WebSocket."""
        uri = "wss://api.cartesia.ai/tts/websocket"
        # Use the API key from environment or the provided one
        api_key = CARTESIA_API_KEY or "sk_car_qGDH5TeA4D1q43UmvF7S1m"
        headers = {
            "Cartesia-Version": "2025-04-16",
            "Authorization": f"Bearer {api_key}"
        }
        
        try:
            async with websockets.connect(uri, extra_headers=headers) as websocket:
                message = {
                    "model_id": "sonic-2",
                    "transcript": text,
                    "voice": {"mode": "id", "id": voice_id},
                    "language": "en",
                    "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 16000},
                    "add_timestamps": True,
                    "continue": False
                }
                await websocket.send(json.dumps(message))
                
                audio_data = b""
                while True:
                    try:
                        response = await websocket.recv()
                        response_data = json.loads(response)
                        
                        if response_data.get("type") == "chunk":
                            # Decode base64 audio data
                            chunk_data = base64.b64decode(response_data.get("data", ""))
                            audio_data += chunk_data
                        elif response_data.get("type") == "done":
                            break
                        elif response_data.get("type") == "error":
                            raise Exception(f"Cartesia API error: {response_data.get('message', 'Unknown error')}")
                    except websockets.exceptions.ConnectionClosed:
                        break
                
                # Save raw PCM data
                with open(filename.replace('.mp3', '.pcm'), "wb") as f:
                    f.write(audio_data)
                
                # Convert PCM to MP3 using ffmpeg
                subprocess.run([
                    "ffmpeg", "-y",
                    "-f", "s16le",
                    "-ar", "16000",
                    "-ac", "1",
                    "-i", filename.replace('.mp3', '.pcm'),
                    "-ar", "44100",
                    "-ac", "1",
                    "-c:a", "libmp3lame",
                    "-b:a", "192k",
                    filename
                ], check=True, capture_output=True)
                
                # Clean up PCM file
                pcm_file = filename.replace('.mp3', '.pcm')
                if os.path.exists(pcm_file):
                    os.remove(pcm_file)
                    
        except Exception as e:
            logging.error(f"Cartesia TTS error: {e}")
            raise

    def speak(text: str, voice_id: str, filename: str):
        """Synchronous wrapper for Cartesia TTS."""
        asyncio.run(speak_cartesia(text, voice_id, filename))

    def get_audio_duration(path: Path) -> float:
        """Return duration in seconds for an audio file."""
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return float(result.stdout.strip())
        except Exception as exc:
            logging.warning(f"Unable to determine duration for {path}: {exc}")
            return 0.0

    def format_duration(seconds: float) -> str:
        """Format duration in seconds to HH:MM:SS or MM:SS format."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    # Process podcast script
    full_text_parts = []
    for line in podcast_script.splitlines():
        line = line.strip()
        if line.startswith("[") or not line:
            continue
        if line.startswith("Jason:"):
            full_text_parts.append(line[7:].strip())
        else:
            full_text_parts.append(line)

    full_text = " ".join(full_text_parts)
    full_text = fix_pronunciation(full_text)

    # Track character count for Cartesia
    credit_usage["services"]["cartesia_api"]["characters"] = len(full_text)
    logging.info(f"Cartesia TTS: {len(full_text)} characters to convert")

    # Generate voice file
    logging.info("Generating single voice segment for entire podcast...")
    voice_file = tmp_dir / "jason_full.mp3"
    speak(full_text, CARTESIA_VOICE_ID, str(voice_file))
    audio_files = [str(voice_file)]
    logging.info("Generated complete voice track")

    # ========================== FINAL MIX ==========================
    final_mp3 = digests_dir / f"Lube_Change_Ep{episode_num:03d}_{datetime.date.today():%Y%m%d}.mp3"
    
    MAIN_MUSIC = project_root / "oilers-pride.mp3"
    
    # Process and normalize voice in one step
    voice_mix = tmp_dir / "voice_normalized_mix.mp3"
    file_duration = get_audio_duration(voice_file)
    timeout_seconds = max(int(file_duration * 3) + 120, 600)
    
    logging.info(f"Processing and normalizing voice ({file_duration:.1f}s) - this may take a few minutes...")
    subprocess.run([
        "ffmpeg", "-y", "-i", str(voice_file),
        "-af", "highpass=f=80,lowpass=f=15000,loudnorm=I=-18:TP=-1.5:LRA=11:linear=true,acompressor=threshold=-20dB:ratio=4:attack=1:release=100:makeup=2,alimiter=level_in=1:level_out=0.95:limit=0.95",
        "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k",
        str(voice_mix)
    ], check=True, capture_output=True, timeout=timeout_seconds)
    
    if not MAIN_MUSIC.exists():
        subprocess.run(["ffmpeg", "-y", "-i", str(voice_mix), str(final_mp3)], check=True, capture_output=True)
        logging.info("Podcast ready (voice-only, no music file found)")
    else:
        # Get voice duration to calculate music timing
        voice_duration = max(get_audio_duration(voice_mix), 0.0)
        logging.info(f"Voice duration: {voice_duration:.2f} seconds")
        
        # Music timing - Professional intro with perfect overlap (same as planetterrian)
        music_fade_in_start = max(voice_duration - 25.0, 0.0)
        music_fade_in_duration = min(35.0, voice_duration - music_fade_in_start)
        
        # Create music segments
        music_intro = tmp_dir / "music_intro.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-t", "5",
            "-af", "volume=0.6",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(music_intro)
        ], check=True, capture_output=True)
        
        music_overlap = tmp_dir / "music_overlap.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "5", "-t", "3",
            "-af", "volume=0.5",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(music_overlap)
        ], check=True, capture_output=True)
        
        music_fadeout = tmp_dir / "music_fadeout.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "8", "-t", "18",
            "-af", "volume=0.4,afade=t=out:curve=log:st=0:d=18",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(music_fadeout)
        ], check=True, capture_output=True)
        
        middle_silence_duration = max(music_fade_in_start - 26.0, 0.0)
        music_silence = tmp_dir / "music_silence.mp3"
        if middle_silence_duration > 0.1:
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                "-t", f"{middle_silence_duration:.2f}", "-c:a", "libmp3lame", "-b:a", "192k",
                str(music_silence)
            ], check=True, capture_output=True)
        
        music_fadein = tmp_dir / "music_fadein.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "25", "-t", f"{music_fade_in_duration:.2f}",
            "-af", f"volume=0.4,afade=t=in:st=0:d={music_fade_in_duration:.2f}",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(music_fadein)
        ], check=True, capture_output=True)
        
        music_tail_full = tmp_dir / "music_tail_full.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "55", "-t", "30",
            "-af", "volume=0.4",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(music_tail_full)
        ], check=True, capture_output=True)
        
        music_tail_fadeout = tmp_dir / "music_tail_fadeout.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "85", "-t", "20",
            "-af", "volume=0.4,afade=t=out:st=0:d=20",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(music_tail_fadeout)
        ], check=True, capture_output=True)
        
        # Concatenate music
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
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(music_concat_list),
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(background_track)
        ], check=True, capture_output=True)
        
        # Delay voice to start at 5 seconds
        voice_delayed = tmp_dir / "voice_delayed.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(voice_mix),
            "-af", "adelay=5000|5000",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
            str(voice_delayed)
        ], check=True, capture_output=True)
        
        # Final mix: voice + music
        logging.info("Mixing voice and music...")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", str(voice_delayed),
            "-i", str(background_track),
            "-filter_complex",
            "[0:a]volume=1.0[a_voice];"
            "[1:a]volume=0.5[a_music];"
            "[a_voice][a_music]amix=inputs=2:duration=longest:dropout_transition=2:weights=2 1[mixed];"
            "[mixed]alimiter=level_in=1:level_out=0.95:limit=0.95[outfinal]",
            "-map", "[outfinal]",
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            str(final_mp3)
        ], check=True, capture_output=True)
        
        logging.info("Podcast created successfully with background music")
        
        # Cleanup music temp files
        for tmp_file in [music_intro, music_overlap, music_fadeout, music_fadein, music_tail_full, music_tail_fadeout, music_silence, background_track, voice_delayed, music_concat_list]:
            if tmp_file.exists():
                try:
                    os.remove(str(tmp_file))
                except Exception:
                    pass

    # ========================== UPDATE RSS FEED ==========================
    def update_rss_feed(
        rss_path: Path,
        episode_num: int,
        episode_title: str,
        episode_description: str,
        episode_date: datetime.date,
        mp3_filename: str,
        mp3_duration: float,
        mp3_path: Path,
        base_url: str = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
    ):
        """Update or create RSS feed with new episode."""
        fg = FeedGenerator()
        fg.load_extension('podcast')
        
        # Parse existing RSS feed
        existing_episodes = []
        if rss_path.exists():
            try:
                tree = ET.parse(str(rss_path))
                root = tree.getroot()
                channel = root.find('channel')
                if channel is not None:
                    items = channel.findall('item')
                    for item in items:
                        episode_data = {}
                        for elem in item:
                            if elem.tag == 'title':
                                episode_data['title'] = elem.text or ''
                            elif elem.tag == 'description':
                                episode_data['description'] = elem.text or ''
                            elif elem.tag == 'guid':
                                if elem.text:
                                    episode_data['guid'] = elem.text.strip()
                            elif elem.tag == 'pubDate':
                                episode_data['pubDate'] = elem.text or ''
                            elif elem.tag == 'enclosure':
                                episode_data['enclosure'] = {
                                    'url': elem.get('url', ''),
                                    'type': elem.get('type', 'audio/mpeg'),
                                    'length': elem.get('length', '0')
                                }
                            elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}episode':
                                episode_data['itunes_episode'] = elem.text or ''
                        if episode_data.get('guid'):
                            existing_episodes.append(episode_data)
            except Exception as e:
                logging.warning(f"Could not parse existing RSS feed: {e}")
        
        # Deduplicate existing episodes by episode number
        episodes_by_number = {}
        for ep_data in existing_episodes:
            ep_num_str = ep_data.get('itunes_episode', '')
            if not ep_num_str:
                guid = ep_data.get('guid', '')
                match = re.search(r'ep(\d+)', guid)
                if match:
                    ep_num_str = match.group(1)
            
            if ep_num_str:
                try:
                    ep_num = int(ep_num_str)
                    if ep_num not in episodes_by_number:
                        episodes_by_number[ep_num] = ep_data
                    else:
                        existing_guid = episodes_by_number[ep_num].get('guid', '')
                        current_guid = ep_data.get('guid', '')
                        existing_ts = existing_guid.split('-')[-1] if '-' in existing_guid else '000000'
                        current_ts = current_guid.split('-')[-1] if '-' in current_guid else '000000'
                        if current_ts > existing_ts:
                            episodes_by_number[ep_num] = ep_data
                except ValueError:
                    pass
        
        # Set channel metadata
        fg.title("Lube Change - Oilers Daily News")
        fg.link(href="https://github.com/patricknovak/Tesla-shorts-time")
        fg.description("Daily Edmonton Oilers news from Oil Country. Hosted by Jason Potter from Hinton, Alberta.")
        fg.language('en-us')
        fg.copyright(f"Copyright {datetime.date.today().year}")
        fg.podcast.itunes_author("Jason Potter")
        fg.podcast.itunes_summary("Daily Edmonton Oilers news from Oil Country. Your daily dose of Oilers news, game recaps, trades, and analysis.")
        fg.podcast.itunes_owner(name='Lube Change', email='contact@lubechange.com')
        fg.podcast.itunes_image(f"{base_url}/lubechange-podcast-image.jpg")
        fg.podcast.itunes_category("Sports")
        fg.podcast.itunes_explicit("no")
        
        # Add existing episodes (skip if same episode number)
        current_time_str = datetime.datetime.now().strftime("%H%M%S")
        new_episode_guid = f"lubechange-ep{episode_num:03d}-{episode_date:%Y%m%d}-{current_time_str}"
        
        for ep_data in episodes_by_number.values():
            ep_num_str = ep_data.get('itunes_episode', '')
            if not ep_num_str:
                guid = ep_data.get('guid', '')
                match = re.search(r'ep(\d+)', guid)
                if match:
                    ep_num_str = match.group(1)
            
            if ep_num_str and int(ep_num_str) == episode_num:
                logging.info(f"Skipping existing episode {ep_num_str} - will be replaced with new version")
                continue
            
            if ep_data.get('guid') == new_episode_guid:
                continue
            
            entry = fg.add_entry()
            entry.id(ep_data.get('guid', ''))
            entry.title(ep_data.get('title', ''))
            entry.description(ep_data.get('description', ''))
            if ep_data.get('link'):
                entry.link(href=ep_data['link'])
            
            if ep_data.get('pubDate'):
                try:
                    if isinstance(ep_data['pubDate'], datetime.datetime):
                        entry.pubDate(ep_data['pubDate'])
                    else:
                        from email.utils import parsedate_to_datetime
                        pub_date = parsedate_to_datetime(ep_data['pubDate'])
                        entry.pubDate(pub_date)
                except Exception:
                    pass
            
            if ep_data.get('enclosure'):
                enc = ep_data['enclosure']
                entry.enclosure(url=enc.get('url', ''), type=enc.get('type', 'audio/mpeg'), length=enc.get('length', '0'))
            
            if ep_data.get('itunes_title'):
                entry.podcast.itunes_title(ep_data['itunes_title'])
            if ep_data.get('itunes_summary'):
                entry.podcast.itunes_summary(ep_data['itunes_summary'])
            if ep_data.get('itunes_duration'):
                entry.podcast.itunes_duration(ep_data['itunes_duration'])
            if ep_data.get('itunes_episode'):
                entry.podcast.itunes_episode(ep_data['itunes_episode'])
            if ep_data.get('itunes_season'):
                entry.podcast.itunes_season(ep_data['itunes_season'])
            if ep_data.get('itunes_episode_type'):
                entry.podcast.itunes_episode_type(ep_data['itunes_episode_type'])
            entry.podcast.itunes_explicit("no")
            entry.podcast.itunes_image(f"{base_url}/lubechange-podcast-image.jpg")
        
        # Add new episode
        entry = fg.add_entry()
        entry.id(new_episode_guid)
        entry.title(episode_title)
        entry.description(episode_description)
        entry.link(href=f"{base_url}/digests/lubechange/{mp3_filename}")
        pub_date = datetime.datetime.combine(episode_date, datetime.time(8, 0, 0), tzinfo=datetime.timezone.utc)
        entry.pubDate(pub_date)
        
        mp3_url = f"{base_url}/digests/lubechange/{mp3_filename}"
        mp3_size = mp3_path.stat().st_size if mp3_path.exists() else 0
        entry.enclosure(url=mp3_url, type="audio/mpeg", length=str(mp3_size))
        
        entry.podcast.itunes_title(episode_title)
        entry.podcast.itunes_summary(episode_description)
        entry.podcast.itunes_duration(format_duration(mp3_duration))
        entry.podcast.itunes_episode(str(episode_num))
        entry.podcast.itunes_season("1")
        entry.podcast.itunes_episode_type("full")
        entry.podcast.itunes_explicit("no")
        entry.podcast.itunes_image(f"{base_url}/lubechange-podcast-image.jpg")
        
        fg.lastBuildDate(datetime.datetime.now(datetime.timezone.utc))
        fg.rss_file(str(rss_path), pretty=True)
        logging.info(f"RSS feed updated → {rss_path}")

    # Update RSS feed
    if final_mp3 and final_mp3.exists():
        try:
            audio_duration = get_audio_duration(final_mp3)
            episode_title = f"Lube Change - Oilers Daily News - Episode {episode_num} - {today_str}"
            episode_description = f"Daily Edmonton Oilers news for {today_str}."
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

# Post to X
if ENABLE_X_POSTING:
    try:
        thread_text = formatted_thread.strip()
        
        # Track X API post call
        credit_usage["services"]["x_api"]["post_calls"] += 1
        
        tweet = x_client.create_tweet(text=thread_text)
        tweet_id = tweet.data['id']
        thread_url = f"https://x.com/lubechange_oilers/status/{tweet_id}"
        logging.info(f"DIGEST POSTED → {thread_url}")
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
print("LUBE CHANGE - OILERS DAILY NEWS — FULLY AUTOMATED RUN COMPLETE")
print(f"X Thread → {x_path}")
print(f"Podcast → {final_mp3}")
print("="*80)
