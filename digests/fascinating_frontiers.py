#!/usr/bin/env python3
"""
Fascinating Frontiers – FULL AUTO X + PODCAST MACHINE
Daily Space & Astronomy News Digest (Patrick in Vancouver)
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
import tweepy
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from urllib.parse import quote

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

# Set to True to save summaries to GitHub Pages instead of posting full content to X
ENABLE_GITHUB_SUMMARIES = True

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

# ========================== PRONUNCIATION FIXER – USING SHARED DICTIONARY ==========================
# Try to use shared pronunciation module, fallback to local implementation
try:
    from assets.pronunciation import apply_pronunciation_fixes, COMMON_ACRONYMS, WORD_PRONUNCIATIONS
    USE_SHARED_PRONUNCIATION = True
except ImportError:
    USE_SHARED_PRONUNCIATION = False
    logging.warning("Could not import shared pronunciation module, using local implementation")

def fix_pronunciation(text: str) -> str:
    """
    Forces correct spelling of scientific/academic acronyms and converts numbers to words
    for better TTS pronunciation on ElevenLabs.
    """
    import re

    # CRITICAL: Protect common words from being misread as acronyms
    # TTS engines sometimes read "who" as "W.H.O." - protect it before acronym processing
    text = re.sub(r'\bwho\b', 'WHO_WORD_PLACEHOLDER', text, flags=re.IGNORECASE)

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

    # Fix dates: multiple formats like "November 19, 2025", "11 December, 2025", "December 11, 2025"
    def replace_date(match):
        month = match.group(1)
        day = match.group(2)
        year = match.group(3)
        try:
            day_num = int(day)
            day_words = number_to_words(day_num)
            # Convert ordinal numbers
            if day_num == 1:
                day_words = "first"
            elif day_num == 2:
                day_words = "second"
            elif day_num == 3:
                day_words = "third"
            elif day_num <= 20:
                if not day_words.endswith(("first", "second", "third")):
                    day_words += "th"
            else:
                if day_num % 10 == 1:
                    day_words = day_words.replace(" one", " first")
                elif day_num % 10 == 2:
                    day_words = day_words.replace(" two", " second")
                elif day_num % 10 == 3:
                    day_words = day_words.replace(" three", " third")
                else:
                    day_words += "th"

            # Convert year to words
            year_num = int(year)
            if year_num >= 2000:
                thousands = year_num // 1000
                remainder = year_num % 1000
                if remainder == 0:
                    year_words = number_to_words(thousands) + " thousand"
                else:
                    year_words = number_to_words(thousands) + " thousand " + number_to_words(remainder)
            else:
                year_words = number_to_words(year_num)

            return f"{month} {day_words}, {year_words}"
        except ValueError:
            return match.group(0)

    text = re.sub(r'(\w+)\s+(\d{1,2}),\s+(\d{4})', replace_date, text, flags=re.IGNORECASE)
    text = re.sub(r'(\d{1,2})\s+(\w+),\s+(\d{4})', lambda m: replace_date(m.group().replace(m.group(1) + ' ' + m.group(2), m.group(2) + ' ' + m.group(1))), text, flags=re.IGNORECASE)

    # Fix times: multiple formats "02:30 PM", "2:30PM", "14:30", "2:30 p.m."
    def replace_time(match):
        hour_str = match.group(1)
        minute_str = match.group(2)
        am_pm = match.group(3).upper() if match.group(3) else ""
        try:
            hour = int(hour_str)
            minute = int(minute_str)

            # Handle 24-hour format
            if not am_pm and hour >= 13:
                hour -= 12
                am_pm = "PM"
            elif not am_pm and hour == 12:
                am_pm = "PM"
            elif not am_pm and hour == 0:
                hour = 12
                am_pm = "AM"
            elif not am_pm:
                am_pm = "AM"

            # Ensure valid hour range
            if hour < 1 or hour > 12:
                return match.group(0)

            hour_word = number_to_words(hour)
            if minute == 0:
                time_str = f"{hour_word} o'clock {am_pm}".strip()
            else:
                minute_word = number_to_words(minute)
                # Handle teen numbers specially (e.g., "fifteen" instead of "fif teen")
                if 10 <= minute <= 19:
                    time_str = f"{hour_word} {minute_word} {am_pm}".strip()
                else:
                    time_str = f"{hour_word} {minute_word} {am_pm}".strip()

            return time_str
        except (ValueError, AttributeError):
            return match.group(0)

    # Match various time formats
    text = re.sub(r'(\d{1,2}):(\d{2})\s*(AM|PM|am|pm|A\.M\.|P\.M\.|a\.m\.|p\.m\.)?', replace_time, text)
    text = re.sub(r'(\d{1,2}):(\d{2})\s*(AM|PM|am|pm|A\.M\.|P\.M\.|a\.m\.|p\.m\.)', replace_time, text)  # Handle periods

    # Fix timezone abbreviations
    text = re.sub(r'\bPST\b', 'Pacific Standard Time', text)
    text = re.sub(r'\bPDT\b', 'Pacific Daylight Time', text)
    text = re.sub(r'\bEST\b', 'Eastern Standard Time', text)
    text = re.sub(r'\bEDT\b', 'Eastern Daylight Time', text)
    text = re.sub(r'\bUTC\b', 'U T C', text)
    text = re.sub(r'\bGMT\b', 'G M T', text)

    # Apply shared pronunciation fixes if available
    if USE_SHARED_PRONUNCIATION:
        try:
            text = apply_pronunciation_fixes(
                text,
                acronyms=COMMON_ACRONYMS,
                hockey_terms={},  # Not needed for Fascinating Frontiers
                player_names={},  # Not needed for Fascinating Frontiers
                oilers_player_names={},  # Not needed for Fascinating Frontiers
                word_pronunciations=WORD_PRONUNCIATIONS,
                use_zwj=True  # Use ZWJ for Fascinating Frontiers (matches original behavior)
            )
        except Exception as e:
            logging.warning(f"Error applying shared pronunciation fixes: {e}, continuing with local fixes")
    
    # Restore protected words after acronym processing
    text = text.replace('WHO_WORD_PLACEHOLDER', 'who')
    
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
    pattern = r"Fascinating_Frontiers_Ep(\d+)_\d{8}\.mp3"
    for mp3_file in digests_dir.glob("Fascinating_Frontiers_Ep*.mp3"):
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
rss_path = project_root / "fascinating_frontiers_podcast.rss"
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
        "elevenlabs_api": {
            "provider": "elevenlabs",
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
        
        # Calculate TTS cost (only applies if using a paid API provider like ElevenLabs)
        tts_provider = str(usage_data["services"]["elevenlabs_api"].get("provider", "elevenlabs")).strip().lower()
        if tts_provider == "elevenlabs":
            elevenlabs_cost = (usage_data["services"]["elevenlabs_api"]["characters"] / 1000) * 0.30
        else:
            elevenlabs_cost = 0.0
        usage_data["services"]["elevenlabs_api"]["estimated_cost_usd"] = elevenlabs_cost
        
        usage_data["total_estimated_cost_usd"] = (
            usage_data["services"]["grok_api"]["total_cost_usd"] +
            usage_data["services"]["elevenlabs_api"]["estimated_cost_usd"]
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
        logging.info(f"TTS ({usage_data['services']['elevenlabs_api'].get('provider', 'unknown')}): {usage_data['services']['elevenlabs_api']['characters']} characters (${usage_data['services']['elevenlabs_api']['estimated_cost_usd']:.4f})")
        logging.info(f"X API: {usage_data['services']['x_api']['total_calls']} API calls (search: {usage_data['services']['x_api']['search_calls']}, post: {usage_data['services']['x_api']['post_calls']})")
        logging.info(f"TOTAL ESTIMATED COST: ${usage_data['total_estimated_cost_usd']:.4f}")
        logging.info("="*80)

    except Exception as e:
        logging.error(f"Failed to save credit usage: {e}", exc_info=True)

def save_summary_to_github_pages(
    summary_text: str,
    output_dir: Path,
    podcast_name: str = "space",
    *,
    episode_num: int | None = None,
    episode_title: str | None = None,
    audio_url: str | None = None,
    rss_url: str | None = None,
):
    """
    Save summary to GitHub Pages JSON file for display on summaries page.
    """
    try:
        # Define the JSON file path
        json_file = project_root / "digests" / f"summaries_{podcast_name}.json"

        # Load existing summaries or create new structure
        if json_file.exists():
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {"podcast": podcast_name, "summaries": []}

        # Create new summary entry
        today = datetime.datetime.now()
        computed_episode_num = episode_num
        if computed_episode_num is None:
            computed_episode_num = get_next_episode_number(project_root / "fascinating_frontiers_podcast.rss", output_dir) - 1

        summary_entry = {
            "date": today.strftime("%Y-%m-%d"),
            "datetime": today.isoformat(),
            "content": summary_text,
            "episode_num": computed_episode_num,
            "episode_title": episode_title,
            "audio_url": audio_url,
            "rss_url": rss_url,
        }

        # Add to summaries (keep only last 30 days to prevent file from growing too large)
        data["summaries"].insert(0, summary_entry)  # Add to beginning (newest first)

        # Keep only last 30 summaries
        if len(data["summaries"]) > 30:
            data["summaries"] = data["summaries"][:30]

        # Save updated data
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logging.info(f"Summary saved to GitHub Pages JSON: {json_file}")
        return json_file

    except Exception as e:
        logging.error(f"Failed to save summary to GitHub Pages: {e}")
        return None

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

def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        logging.warning(f"Invalid {name}='{raw}' (expected float). Using default {default}.")
        return default

def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        logging.warning(f"Invalid {name}='{raw}' (expected int). Using default {default}.")
        return default

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    v = str(raw).strip().lower()
    if v in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


# ========================== STEP 1: FETCH SPACE & ASTRONOMY NEWS FROM RSS FEEDS ==========================
logging.info("Step 1: Fetching space and astronomy news from RSS feeds for the last 48 hours...")

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

X_PROMPT = f"""
# Fascinating Frontiers - SPACE & ASTRONOMY EDITION
**Date:** {today_str}
🚀 Fascinating Frontiers Podcast: Coming soon to Apple Podcasts
{news_section}

You are an elite space and astronomy news curator producing the daily "Fascinating Frontiers" newsletter. Use ONLY the pre-fetched news articles above. Do NOT hallucinate, invent, or search for new content/URLs—stick to exact provided links. Do NOT include any X posts or Twitter references.

**BRAND PERSONALITY:**
- Fascinating Frontiers: Daily space and astronomy news digest
- Mission: Bring the wonders of space exploration and astronomy discoveries to everyone
- Values: Curiosity, exploration, scientific accuracy, inspiration
- Tone: Inspirational, awe-inspiring, accessible, exciting, forward-thinking
- Focus: Latest space missions, astronomy discoveries, cosmic phenomena, and space technology breakthroughs

### MANDATORY SELECTION & COUNTS (CRITICAL - FOLLOW EXACTLY)
- **News**: You MUST select EXACTLY 15 unique articles. If you have fewer than 15 available, use ALL of them and number them 1 through N. If you have more than 15, select the BEST 15. Prioritize high-quality sources; each must cover a DIFFERENT story/angle.
- **Curation**: Prefer concrete mission updates, discoveries, research results, and instrument/launch milestones. Avoid “year in review”, listicles, awards, or opinion pieces unless you truly cannot fill 15 without them.
- **NO X POSTS**: Do NOT include any X posts, Twitter posts, or social media references. Only use news articles.
- **Diversity Check**: Verify no similar content; each item must cover a DIFFERENT angle.

### FORMATTING (EXACT—USE MARKDOWN AS SHOWN)
# Fascinating Frontiers
**Date:** {today_str}
🚀 **Fascinating Frontiers** - Space & Astronomy News

**Quick scan:** 1 short sentence theme + “If you only read 3 today: #A, #B, #C.”

━━━━━━━━━━━━━━━━━━━━
### Top 15 Space & Astronomy Stories
1. **Title (<= 12 words): DD Month YYYY • Source Name**  
   2 sentences max. Sentence 1: what happened (specific + concrete). Sentence 2: why it matters for space exploration/astronomy/our understanding of the cosmos. Avoid filler.
   Source: [EXACT URL FROM PRE-FETCHED—no mods]
2. [Repeat format for 3-15; if <15 items, stop at available count, add a blank line after each item]

━━━━━━━━━━━━━━━━━━━━
### Cosmic Spotlight
Pick ONE item from the Top 15 and go deeper (3–5 sentences). Make it vivid but grounded: what it reveals, how we know, and what could come next. End with ONE question to invite replies.

━━━━━━━━━━━━━━━━━━━━
### Daily Inspiration
One inspiring quote about space, exploration, astronomy, or the cosmos. End with: "Share your thoughts with us!"

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

# Save X thread
x_path = digests_dir / f"Fascinating_Frontiers_{datetime.date.today():%Y%m%d}.md"
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
    logging.info("@planetterrian X posting client ready (Fascinating Frontiers posts to @planetterrian)")
else:
    logging.info("X posting is disabled (ENABLE_X_POSTING = False)")

# ========================== GENERATE PODCAST SCRIPT ==========================
if not ENABLE_PODCAST:
    logging.info("Podcast generation is disabled (ENABLE_PODCAST = False). Skipping podcast script generation, audio processing, and RSS feed updates.")
    final_mp3 = None
else:
    POD_PROMPT = f"""You are writing an 8–11 minute (1950–2600 words) solo podcast script for "Fascinating Frontiers" Episode {episode_num}.

HOST: Patrick in Vancouver - Canadian, space enthusiast, newscaster. Voice like a solo podcaster breaking space and astronomy news, not robotic.

BRAND PERSONALITY: Fascinating Frontiers - Daily space and astronomy news digest. Mission: Bring the wonders of space exploration and astronomy discoveries to everyone. Values: Curiosity, exploration, scientific accuracy, inspiration.

RULES:
- Start every line with "Patrick:"
- Don't read URLs aloud - mention source names naturally
- Use natural dates ("today", "this morning") not exact timestamps
- Enunciate all numbers clearly
- Use ONLY information from the digest below - nothing else
- Make it sound like a real solo pod: vivid but concise, no robotic repetition
- Emphasize the wonder and significance of space discoveries
- Focus on exploration, discovery, and humanity's cosmic journey

SCRIPT STRUCTURE:
[Intro music - 10 seconds]
Patrick: Welcome to Fascinating Frontiers, episode {episode_num}. It is {today_str}. I'm Patrick in Vancouver, Canada, bringing you today's most exciting space and astronomy news. Thank you for joining us today. If you like the show, please like, share, rate and subscribe to the podcast, it really helps. Now let's journey to the stars with today's discoveries.

Patrick: Quick scan before we dive in—three stories to watch today, then we’ll go through the full list in order.

[Narrate EVERY item from the digest in order - no skipping]
- For each news item: Read the title with energy, then summarize in 2–4 lines: what happened, why it matters, and one “what to watch next” angle
- Cosmic Spotlight: Explain why this breakthrough represents the cutting edge of space exploration
- Daily Inspiration: Read the quote verbatim, add one encouraging sentence

[Closing]
Patrick: That's Fascinating Frontiers for today. Remember: we're all made of starstuff, and every discovery brings us closer to understanding our place in the cosmos. Together, we're exploring the final frontier, one discovery at a time. We'll catch you tomorrow on Fascinating Frontiers!

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

    # Cache for audio duration lookups to avoid redundant ffprobe calls
    _audio_duration_cache: Dict[Path, float] = {}
    
    def get_audio_duration(path: Path) -> float:
        """Return duration in seconds for an audio file. Uses cache to avoid redundant ffprobe calls."""
        # Check cache first
        if path in _audio_duration_cache:
            return _audio_duration_cache[path]
        
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
            duration = float(result.stdout.strip())
            _audio_duration_cache[path] = duration  # Cache the result
            return duration
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
        if line.startswith("Patrick:"):
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
    INTRO_MUSIC = project_root / "fascinatingfrontiers.mp3"
    # Background music: New longer track for end of podcast
    BACKGROUND_MUSIC = project_root / "Fascinating Frontierssmusic.mp3"
    # Voice timing: keep a consistent intro delay so mixes/concats align.
    VOICE_INTRO_DELAY_SECONDS = 28.0
    VOICE_INTRO_DELAY_MS = int(VOICE_INTRO_DELAY_SECONDS * 1000)

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
        subprocess.run(["ffmpeg", "-y", "-threads", "0", "-i", str(voice_mix), "-preset", "fast", str(final_mp3)], check=True, capture_output=True)
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
    # RSS feed update function (similar to Tesla script)
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
        fg.title("Fascinating Frontiers")
        fg.link(href="https://planetterrian.com")
        fg.description("Daily space and astronomy news digest. Bringing the wonders of space exploration and astronomy discoveries to everyone.")
        fg.language('en-us')
        fg.copyright(f"Copyright {datetime.date.today().year}")
        fg.podcast.itunes_author("Patrick")
        fg.podcast.itunes_summary("Daily space and astronomy news. Curiosity, exploration, scientific accuracy, and inspiration.")
        fg.podcast.itunes_owner(name='Planetterrian Ventures', email='contact@planetterrian.com')
        image_filename = "Fascinating Frontiers-3000x3000.jpg"
        fg.podcast.itunes_image(f"{base_url}/{quote(image_filename)}")
        fg.podcast.itunes_category("Science")
        fg.podcast.itunes_explicit("no")
        
        # Add update frequency for Apple Podcasts (required field)
        # Note: feedgen doesn't have direct support, so we'll add it manually after generation
        
        # Add existing episodes (skip if same episode number)
        current_time_str = datetime.datetime.now().strftime("%H%M%S")
        new_episode_guid = f"fascinating-frontiers-ep{episode_num:03d}-{episode_date:%Y%m%d}-{current_time_str}"
        
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
            image_filename = "Fascinating Frontiers-3000x3000.jpg"
            entry.podcast.itunes_image(f"{base_url}/{quote(image_filename)}")
        
        # Add new episode
        entry = fg.add_entry()
        entry.id(new_episode_guid)
        entry.title(episode_title)
        entry.description(episode_description)
        entry.link(href=f"{base_url}/digests/fascinating_frontiers/{mp3_filename}")
        pub_date = datetime.datetime.combine(episode_date, datetime.time(8, 0, 0), tzinfo=datetime.timezone.utc)
        entry.pubDate(pub_date)
        
        mp3_url = f"{base_url}/digests/fascinating_frontiers/{mp3_filename}"
        mp3_size = mp3_path.stat().st_size if mp3_path.exists() else 0
        entry.enclosure(url=mp3_url, type="audio/mpeg", length=str(mp3_size))
        
        entry.podcast.itunes_title(episode_title)
        entry.podcast.itunes_summary(episode_description)
        entry.podcast.itunes_duration(format_duration(mp3_duration))
        entry.podcast.itunes_episode(str(episode_num))
        entry.podcast.itunes_season("1")
        entry.podcast.itunes_episode_type("full")
        entry.podcast.itunes_explicit("no")
        image_filename = "Fascinating Frontiers-3000x3000.jpg"
        entry.podcast.itunes_image(f"{base_url}/{quote(image_filename)}")
        
        fg.lastBuildDate(datetime.datetime.now(datetime.timezone.utc))
        fg.rss_file(str(rss_path), pretty=True)
        
        # Add itunes:updateFrequency field (required by Apple Podcasts)
        # feedgen doesn't support this directly, so we add it manually
        try:
            tree = ET.parse(str(rss_path))
            root = tree.getroot()
            channel = root.find('channel')
            if channel is not None:
                # Check if updateFrequency already exists
                itunes_ns = '{http://www.itunes.com/dtds/podcast-1.0.dtd}'
                existing_freq = channel.find(f'{itunes_ns}updateFrequency')
                if existing_freq is None:
                    # Add updateFrequency after itunes:summary
                    summary_elem = channel.find(f'{itunes_ns}summary')
                    if summary_elem is not None:
                        # Create updateFrequency element
                        update_freq = ET.Element(f'{itunes_ns}updateFrequency')
                        update_freq.text = 'Daily'
                        # Insert after summary
                        channel.insert(list(channel).index(summary_elem) + 1, update_freq)
                    else:
                        # If no summary, add before first item
                        first_item = channel.find('item')
                        if first_item is not None:
                            update_freq = ET.Element(f'{itunes_ns}updateFrequency')
                            update_freq.text = 'Daily'
                            channel.insert(list(channel).index(first_item), update_freq)
                    tree.write(str(rss_path), encoding='UTF-8', xml_declaration=True)
                    logging.info("Added itunes:updateFrequency field to RSS feed")
        except Exception as e:
            logging.warning(f"Could not add updateFrequency to RSS feed: {e}")
        
        logging.info(f"RSS feed updated → {rss_path}")

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
                base_url="https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
            )
            logging.info(f"RSS feed updated with Episode {episode_num}")
        except Exception as e:
            logging.error(f"Failed to update RSS feed: {e}", exc_info=True)

# Save summary to GitHub Pages and post link to X
if ENABLE_GITHUB_SUMMARIES:
    try:
        # Save the full summary to GitHub Pages JSON
        _base_url = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
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
        # Create link to the Fascinating Frontiers summaries page
        summaries_url = "https://patricknovak.github.io/Tesla-shorts-time/fascinating-frontiers-summaries.html"

        # Create a teaser post with link to full summary
        today = datetime.datetime.now()
        teaser_text = f"""🚀🌌 Fascinating Frontiers - {today.strftime('%B %d, %Y')}

🔭 Today's complete space & astronomy digest is now live!

🪐 Latest space missions & discoveries
🌟 Cosmic phenomena & astronomical events
🚁 Space technology & exploration updates
🎙️ Full podcast episode available

Read the full summary: {summaries_url}

#Space #Astronomy #NASA #SpaceX #FascinatingFrontiers"""

        # Track X API post call
        credit_usage["services"]["x_api"]["post_calls"] += 1

        # Post the teaser with link
        tweet = x_client.create_tweet(text=teaser_text)
        tweet_id = tweet.data['id']
        thread_url = f"https://x.com/planetterrian/status/{tweet_id}"
        logging.info(f"DIGEST LINK POSTED → {thread_url}")
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

