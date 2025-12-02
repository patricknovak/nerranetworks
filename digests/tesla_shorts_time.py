#!/usr/bin/env python3
"""
Tesla Shorts Time – FULL AUTO X + PODCAST MACHINE
X Thread + Daily Podcast (Patrick in Vancouver)
Auto-published to X — November 19, 2025+
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
import yfinance as yf
from openai import OpenAI
from difflib import SequenceMatcher
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
import feedparser
from typing import List, Dict, Any
import tweepy

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
def fix_tesla_pronunciation(text: str) -> str:
    """
    Forces correct spelling of Tesla acronyms and converts numbers to words
    for better TTS pronunciation on ElevenLabs.
    """
    import re

    # List of acronyms that must be spelled out letter-by-letter
    acronyms = {
        "TSLA": "T S L A",
        "FSD":  "F S D",
        "HW3":  "H W 3",
        "HW4":  "H W 4",
        "AI5":  "A I 5",
        "4680": "4 6 8 0",
        "EV":   "E V",
        "EVs":  "E Vs",
        "BEV":  "B E V",
        "PHEV": "P H E V",
        "ICE":  "I C E",
        "NHTSA":"N H T S A",
        "OTA":  "O T A",
        "LFP":  "L F P",
    }

    # Invisible zero-width non-breaking space / word joiner
    ZWJ = "\u2060"   # U+2060 WORD JOINER — this one is safe

    # Special case: Fix "Robotaxis" plural pronunciation
    # Use word joiner to help TTS recognize the plural form correctly
    # This keeps it as one word but helps TTS pronounce "Robotaxi" + "s" properly
    text = re.sub(r'\b(Robotaxi)(s)\b', rf'\1{ZWJ}\2', text, flags=re.IGNORECASE)

    for acronym, spelled in acronyms.items():
        # Build a regex that only matches the acronym when it's a whole word
        # (surrounded by space, punctuation, start/end of string, etc.)
        pattern = rf'(?<!\w){re.escape(acronym)}(?!\w)'
        replacement = ZWJ.join(list(spelled))
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Convert episode numbers (e.g., "episode 336" → "episode three hundred thirty-six")
    def replace_episode_number(match):
        episode_text = match.group(1)
        num_str = match.group(2)
        try:
            num = int(num_str)
            # Use full number-to-words conversion for episode numbers
            words = number_to_words(num)
            return f"{episode_text} {words}"
        except ValueError:
            return match.group(0)
    
    text = re.sub(r'(episode\s+)(\d+)', replace_episode_number, text, flags=re.IGNORECASE)
    
    # Convert stock prices (e.g., "$430.17" → "four hundred thirty dollars and seventeen cents")
    def replace_stock_price(match):
        dollar_sign = match.group(1)
        num_str = match.group(2)
        try:
            num = float(num_str)
            words = number_to_words(num)
            # Format as "X dollars and Y cents" for better pronunciation
            if '.' in num_str:
                parts = num_str.split('.')
                dollars = int(parts[0])
                cents = int(parts[1]) if len(parts) > 1 else 0
                if dollars == 0:
                    result = f"{number_to_words(cents)} cents"
                elif cents == 0:
                    result = f"{number_to_words(dollars)} dollars"
                else:
                    result = f"{number_to_words(dollars)} dollars and {number_to_words(cents)} cents"
            else:
                result = f"{words} dollars"
            return f"{dollar_sign}{result}"
        except ValueError:
            return match.group(0)
    
    text = re.sub(r'(\$)(\d+\.?\d*)', replace_stock_price, text)
    
    # Convert percentages (e.g., "+3.59%" → "plus three point five nine percent")
    def replace_percentage(match):
        sign = match.group(1) if match.group(1) else ''  # + or - or empty
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

# Required keys (X credentials only required if posting is enabled)
required = [
    "GROK_API_KEY", 
    "ELEVENLABS_API_KEY"
    # NEWSAPI_KEY no longer required - using RSS feeds instead
]
if ENABLE_X_POSTING:
    required.extend([
        "X_CONSUMER_KEY",
        "X_CONSUMER_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET"
    ])
for var in required:
    if not os.getenv(var):
        raise OSError(f"Missing {var} in .env")

# ========================== DATE & PRICE (MUST BE FIRST) ==========================
# Get current date and time in PST
pst_tz = ZoneInfo("America/Los_Angeles")
now_pst = datetime.datetime.now(pst_tz)
today_str = now_pst.strftime("%B %d, %Y at %I:%M %p PST")   # November 19, 2025 at 02:30 PM PST
yesterday_iso = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
seven_days_ago_iso = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

tsla = yf.Ticker("TSLA")
info = tsla.info
price = (info.get("currentPrice") or info.get("regularMarketPrice") or
         info.get("preMarketPrice") or info.get("previousClose") or 0.0)
prev_close = info.get("regularMarketPreviousClose") or price
change = price - prev_close
change_pct = (change / prev_close * 100) if prev_close else 0
market_status = " (After-hours)" if info.get("marketState") == "POST" else ""
change_str = f"{change:+.2f} ({change_pct:+.2f}%) {market_status}" if change != 0 else "unchanged"

# Folders - use absolute paths
digests_dir = project_root / "digests"
digests_dir.mkdir(exist_ok=True)

# ========================== X SPOTLIGHT USERNAME ROTATION ==========================
def get_spotlight_username() -> tuple[str, str]:
    """Get the spotlight username and display name based on the day of the week."""
    weekday = datetime.date.today().weekday()  # 0=Monday, 6=Sunday
    spotlight_map = {
        0: ("SawyerMerritt", "Sawyer Merritt"),
        1: ("WholeMarsBlog", "Whole Mars Blog"),
        2: ("DirtyTesLa", "Dirty Tesla"),
        3: ("TeslaPodcast", "Tesla Podcast"),
        4: ("elonmusk", "Elon Musk"),
        5: ("tesla_raj", "Tesla Raj"),
        6: ("TeslaBoomerMama", "Tesla Boomer Mama")
    }
    username, display_name = spotlight_map[weekday]
    logging.info(f"Today's X Spotlight: @{username} ({display_name})")
    return username, display_name

spotlight_username, spotlight_display_name = get_spotlight_username()

# ========================== CONTENT TRACKING (PREVENT REPETITION) ==========================
def load_used_content_tracker() -> dict:
    """Load previously used content to avoid repetition."""
    tracker_file = digests_dir / "tesla_content_tracker.json"
    if tracker_file.exists():
        try:
            with open(tracker_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.warning(f"Failed to load content tracker: {e}")
    return {
        "short_spots": [],
        "short_squeezes": [],
        "daily_challenges": [],
        "inspiration_quotes": [],
        "last_updated": None
    }

def save_used_content_tracker(tracker: dict):
    """Save used content tracker."""
    tracker_file = digests_dir / "tesla_content_tracker.json"
    try:
        # Keep only last 14 days of content (2 weeks)
        cutoff_date = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()
        for key in ["short_spots", "short_squeezes", "daily_challenges", "inspiration_quotes"]:
            tracker[key] = [
                item for item in tracker[key] 
                if item.get("date", "") >= cutoff_date
            ]
        tracker["last_updated"] = datetime.date.today().isoformat()
        with open(tracker_file, 'w', encoding='utf-8') as f:
            json.dump(tracker, f, indent=2)
    except Exception as e:
        logging.warning(f"Failed to save content tracker: {e}")

def extract_sections_from_digest(digest_path: Path) -> dict:
    """Extract Short Spot, Short Squeeze, Daily Challenge, and Inspiration Quote from a digest file."""
    sections = {
        "short_spot": None,
        "short_squeeze": None,
        "daily_challenge": None,
        "inspiration_quote": None
    }
    
    if not digest_path.exists():
        return sections
    
    try:
        with open(digest_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract Short Spot (between "## Short Spot" or "📉 **Short Spot**" and next separator)
        short_spot_match = re.search(
            r'(?:## Short Spot|📉 \*\*Short Spot\*\*)(.*?)(?=━━|### Short Squeeze|📈|### Daily Challenge|💪|✨|$)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        if short_spot_match:
            sections["short_spot"] = short_spot_match.group(1).strip()
        
        # Extract Short Squeeze (between "### Short Squeeze" or "📈 **Short Squeeze**" and next separator)
        short_squeeze_match = re.search(
            r'(?:### Short Squeeze|📈 \*\*Short Squeeze\*\*)(.*?)(?=━━|### Daily Challenge|💪|✨|$)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        if short_squeeze_match:
            sections["short_squeeze"] = short_squeeze_match.group(1).strip()
        
        # Extract Daily Challenge (between "### Daily Challenge" or "💪 **Daily Challenge**" and next separator)
        daily_challenge_match = re.search(
            r'(?:### Daily Challenge|💪 \*\*Daily Challenge\*\*)(.*?)(?=━━|✨|Inspiration Quote|$)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        if daily_challenge_match:
            sections["daily_challenge"] = daily_challenge_match.group(1).strip()
        
        # Extract Inspiration Quote (look for "Inspiration Quote:" or "✨ **Inspiration Quote:**")
        inspiration_quote_match = re.search(
            r'(?:✨ \*\*Inspiration Quote:\*\*|\*\*Inspiration Quote:\*\*|Inspiration Quote:)\s*"([^"]+)"\s*[–-]\s*([^,]+)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        if inspiration_quote_match:
            quote_text = inspiration_quote_match.group(1).strip()
            author = inspiration_quote_match.group(2).strip()
            sections["inspiration_quote"] = f'"{quote_text}" – {author}'
        
    except Exception as e:
        logging.warning(f"Failed to extract sections from {digest_path}: {e}")
    
    return sections

def load_recent_digests(max_days: int = 14) -> dict:
    """Load sections from recent digests to track what's been used."""
    tracker = {
        "short_spots": [],
        "short_squeezes": [],
        "daily_challenges": [],
        "inspiration_quotes": []
    }
    
    # Look for digest files from the last max_days days
    cutoff_date = datetime.date.today() - datetime.timedelta(days=max_days)
    
    for i in range(max_days):
        check_date = datetime.date.today() - datetime.timedelta(days=i)
        date_str = check_date.strftime("%Y%m%d")
        
        # Try both formatted and unformatted versions
        for pattern in [f"Tesla_Shorts_Time_{date_str}.md", f"Tesla_Shorts_Time_{date_str}_formatted.md"]:
            digest_path = digests_dir / pattern
            if digest_path.exists():
                sections = extract_sections_from_digest(digest_path)
                
                if sections["short_spot"]:
                    tracker["short_spots"].append({
                        "date": check_date.isoformat(),
                        "content": sections["short_spot"][:500]  # First 500 chars
                    })
                if sections["short_squeeze"]:
                    tracker["short_squeezes"].append({
                        "date": check_date.isoformat(),
                        "content": sections["short_squeeze"][:500]
                    })
                if sections["daily_challenge"]:
                    tracker["daily_challenges"].append({
                        "date": check_date.isoformat(),
                        "content": sections["daily_challenge"][:500]
                    })
                if sections["inspiration_quote"]:
                    tracker["inspiration_quotes"].append({
                        "date": check_date.isoformat(),
                        "content": sections["inspiration_quote"][:200]
                    })
                break  # Found one, don't check other pattern
    
    return tracker

def get_used_content_summary(tracker: dict) -> str:
    """Generate a summary of recently used content for prompts."""
    summary_parts = []
    
    if tracker.get("short_spots"):
        recent = tracker["short_spots"][-7:]  # Last 7 Short Spots
        spots_text = "\n".join([f"- {item.get('content', '')[:200]}..." for item in recent])
        summary_parts.append(f"RECENTLY USED SHORT SPOTS (DO NOT REPEAT - create something COMPLETELY DIFFERENT):\n{spots_text}")
    
    if tracker.get("short_squeezes"):
        recent = tracker["short_squeezes"][-7:]  # Last 7 Short Squeezes
        squeezes_text = "\n".join([f"- {item.get('content', '')[:200]}..." for item in recent])
        summary_parts.append(f"RECENTLY USED SHORT SQUEEZES (DO NOT REPEAT - use DIFFERENT failed predictions, DIFFERENT years, DIFFERENT bears):\n{squeezes_text}")
    
    if tracker.get("daily_challenges"):
        recent = tracker["daily_challenges"][-7:]  # Last 7 Daily Challenges
        challenges_text = "\n".join([f"- {item.get('content', '')[:200]}..." for item in recent])
        summary_parts.append(f"RECENTLY USED DAILY CHALLENGES (DO NOT REPEAT - create a COMPLETELY NEW and DIFFERENT challenge):\n{challenges_text}")
    
    if tracker.get("inspiration_quotes"):
        recent = tracker["inspiration_quotes"][-10:]  # Last 10 quotes (more variety needed)
        quotes_text = "\n".join([f"- {item.get('content', '')[:150]}..." for item in recent])
        summary_parts.append(f"RECENTLY USED INSPIRATION QUOTES (DO NOT REPEAT - use a DIFFERENT quote from a DIFFERENT author):\n{quotes_text}")
    
    if summary_parts:
        return "\n\n".join(summary_parts) + "\n\n🚨 CRITICAL: Generate COMPLETELY NEW, FRESH, and DIFFERENT content for ALL sections. Avoid ANY similarity to the above. Each section must be unique and engaging.\n"
    return ""

# Initialize content tracker
content_tracker = load_used_content_tracker()
# Also load from recent digest files to get the most up-to-date tracking
recent_tracker = load_recent_digests(max_days=14)
# Merge both (recent digests take precedence)
for key in ["short_spots", "short_squeezes", "daily_challenges", "inspiration_quotes"]:
    # Combine and deduplicate by content
    combined = content_tracker.get(key, []) + recent_tracker.get(key, [])
    seen_content = set()
    unique_items = []
    for item in combined:
        content_hash = item.get("content", "")[:100]  # Use first 100 chars as hash
        if content_hash not in seen_content:
            seen_content.add(content_hash)
            unique_items.append(item)
    # Sort by date, most recent first, keep last 14
    unique_items.sort(key=lambda x: x.get("date", ""), reverse=True)
    content_tracker[key] = unique_items[:14]

used_content_summary = get_used_content_summary(content_tracker)

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
    pattern = r"Tesla_Shorts_Time_Pod_Ep(\d+)_\d{8}\.mp3"
    for mp3_file in digests_dir.glob("Tesla_Shorts_Time_Pod_Ep*.mp3"):
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
rss_path = project_root / "podcast.rss"
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
        
        # Calculate total cost (ElevenLabs pricing: ~$0.30 per 1000 characters for turbo model)
        elevenlabs_cost = (usage_data["services"]["elevenlabs_api"]["characters"] / 1000) * 0.30
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
        logging.info(f"ElevenLabs API: {usage_data['services']['elevenlabs_api']['characters']} characters (${usage_data['services']['elevenlabs_api']['estimated_cost_usd']:.4f})")
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
ELEVEN_API = "https://api.elevenlabs.io/v1"
ELEVEN_KEY = os.getenv("ELEVENLABS_API_KEY")
# NEWSAPI_KEY no longer needed - using RSS feeds instead


# ========================== STEP 1: FETCH TESLA NEWS FROM RSS FEEDS ==========================
logging.info("Step 1: Fetching Tesla news from RSS feeds for the last 24 hours...")

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
    
    Args:
        items: List of items to filter
        similarity_threshold: Similarity ratio above which items are considered duplicates (0.0-1.0)
        get_text_func: Function to extract text from item for comparison (default: uses 'title' or 'text' key)
    
    Returns:
        Filtered list with similar items removed (keeps first occurrence)
    """
    if not items:
        return items
    
    if get_text_func is None:
        # Default: try 'title', then 'text', then 'description'
        def get_text_func(item):
            if isinstance(item, dict):
                return item.get('title', '') or item.get('text', '') or item.get('description', '')
            return str(item)
    
    filtered = []
    for item in items:
        item_text = get_text_func(item)
        if not item_text:
            continue
        
        # Check similarity against already accepted items
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
def fetch_tesla_news():
    """Fetch Tesla-related news from RSS feeds of Tesla news sites for the last 24 hours.
    Returns tuple: (filtered_articles, raw_articles) for saving raw data."""
    import feedparser
    
    # Tesla news site RSS feeds
    rss_feeds = [
        "https://whatsuptesla.com/feed",
        "https://www.thedrive.com/category/tesla-news/feed",
        "https://www.tesery.com/en-in/blogs/news.atom",
        "https://driveteslacanada.ca/feed/",
        "http://feeds.feedburner.com/teslanorth",
        "https://in.mashable.com/tesla.xml",
        "https://teslainvestor.blogspot.com/feeds/posts/default",
        "https://www.teslasiliconvalley.com/blog?format=rss",
        "https://www.teslarati.com/feed/",
        "https://www.notateslaapp.com/news/rss",
        "https://insideevs.com/rss/",
    ]
    
    # Calculate cutoff time (last 24 hours)
    cutoff_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)
    
    all_articles = []
    raw_articles = []
    
    # Tesla-related keywords to filter articles
    tesla_keywords = [
        "tesla", "tsla", "model 3", "model y", "model s", "model x", 
        "cybertruck", "roadster", "semi", "robotaxi", "optimus",
        "fsd", "full self-driving", "autopilot", "supercharger",
        "gigafactory", "powerwall", "solar roof", "4680", "ai5"
    ]
    
    logging.info(f"Fetching Tesla news from {len(rss_feeds)} RSS feeds...")
    
    for feed_url in rss_feeds:
        # Initialize source_name before the try block
        source_name = "Unknown"
        try:
            # Parse RSS feed
            feed = feedparser.parse(feed_url)
            
            if feed.bozo and feed.bozo_exception:
                logging.warning(f"Failed to parse RSS feed {feed_url}: {feed.bozo_exception}")
                continue
            
            # Extract source name from feed (before processing entries)
            source_name = feed.feed.get("title", "Unknown")
            if "whatsuptesla" in feed_url.lower():
                source_name = "What's Up Tesla"
            elif "thedrive" in feed_url.lower():
                source_name = "The Drive"
            elif "tesery" in feed_url.lower():
                source_name = "Tesery"
            elif "driveteslacanada" in feed_url.lower() or "drivetesla" in feed_url.lower():
                source_name = "Drive Tesla Canada"
            elif "teslanorth" in feed_url.lower() or "feedburner" in feed_url.lower():
                source_name = "Tesla North"
            elif "mashable" in feed_url.lower():
                source_name = "Mashable"
            elif "teslainvestor" in feed_url.lower() or "blogspot" in feed_url.lower():
                source_name = "Tesla Investor"
            elif "teslasiliconvalley" in feed_url.lower():
                source_name = "Tesla Silicon Valley"
            elif "teslarati" in feed_url.lower():
                source_name = "Teslarati"
            elif "notateslaapp" in feed_url.lower():
                source_name = "Not a Tesla App"
            elif "insideevs" in feed_url.lower():
                source_name = "InsideEVs"
            
            feed_articles = []
            for entry in feed.entries:
                # Parse published date
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
                
                # Skip if older than 24 hours
                if published_time and published_time < cutoff_time:
                    continue
                
                # Get title and description
                title = entry.get("title", "").strip()
                description = entry.get("description", "").strip() or entry.get("summary", "").strip()
                link = entry.get("link", "").strip()
                
                if not title or not link:
                    continue
                
                # Check if article is Tesla-related
                title_desc_lower = (title + " " + description).lower()
                if not any(keyword in title_desc_lower for keyword in tesla_keywords):
                    continue
                
                # Skip stock quotes/price commentary
                if any(skip_term in title_desc_lower for skip_term in ["stock quote", "tradingview", "yahoo finance ticker", "price chart"]):
                    continue
                
                # Format article
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
            # Don't reference source_name in exception handler to avoid scoping issues
            logging.warning(f"Failed to fetch RSS feed {feed_url}: {e}")
            continue
    
    logging.info(f"Fetched {len(all_articles)} total articles from RSS feeds")
    
    if not all_articles:
        logging.warning("No articles found from RSS feeds")
        return [], []
    
    # Remove similar/duplicate articles based on title similarity
    before_dedup = len(all_articles)
    formatted_articles = remove_similar_items(
        all_articles,
        similarity_threshold=0.85,  # 85% similarity = likely duplicate
        get_text_func=lambda x: f"{x.get('title', '')} {x.get('description', '')}"
    )
    after_dedup = len(formatted_articles)
    if before_dedup != after_dedup:
        logging.info(f"Removed {before_dedup - after_dedup} similar/duplicate news articles")
    
    # Sort by published date (newest first)
    formatted_articles.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)
    
    logging.info(f"Filtered to {len(formatted_articles)} unique Tesla news articles")
    filtered_result = formatted_articles[:30]  # Return top 30 for selection
    return filtered_result, raw_articles

tesla_news, raw_news_articles = fetch_tesla_news()

# ========================== STEP 2: FETCH TOP X POSTS FROM X API ==========================
# X POSTS DISABLED - No longer fetching X posts to avoid API costs
# Initialize variables at module level to ensure they're always defined
top_x_posts = []
raw_x_posts = []

# Focused on top high-engagement accounts optimized to fit within 512 character query limit
# Query uses 472 chars, leaving 40 chars buffer (18 accounts total)
TRUSTED_USERNAMES = [
    # Highest Engagement Accounts
    "elonmusk",  # Highest engagement, Tesla CEO
    
    # Official Tesla Accounts (High Engagement)
    "Tesla", "Tesla_AI", "TeslaCharging", "cybertruck", "teslaenergy",
    "GigaTexas", "GigaBerlin",  # Factory accounts with high engagement
    
    # Top Tesla Influencers (High Engagement)
    "SawyerMerritt", "WholeMarsBlog", "TeslaRaj",
    
    # Tesla Analysts & Investors (High Engagement)
    "GaryBlack00", "TroyTeslike", "RossGerber",
    
    # Top Tesla Media Outlets (High Engagement)
    "Teslarati", "ElectrekCo", "InsideEVs", "CleanTechnica",
]

# Tesla-related keywords for content filtering (case-insensitive)
TESLA_CONTENT_KEYWORDS = [
    "tesla", "tsla", "model 3", "model y", "model s", "model x", "cybertruck",
    "roadster", "semi", "robotaxi", "optimus", "fsd", "full self-driving",
    "autopilot", "supercharger", "giga", "gigafactory", "gigatexas", "gigaberlin",
    "gigashanghai", "4680", "lfp", "hw4", "hw5", "ai5", "tesla energy",
    "powerwall", "megapack", "solar roof", "tesla charging"
]


def is_tesla_related(text: str) -> bool:
    """
    Check if post text contains Tesla-related keywords.
    Returns True if the post is about Tesla, False otherwise.
    """
    if not text:
        return False
    
    text_lower = text.lower()
    
    # Check if any Tesla keyword appears in the text
    for keyword in TESLA_CONTENT_KEYWORDS:
        if keyword.lower() in text_lower:
            return True
    
    return False

def fetch_x_posts_nitter(usernames: List[str]) -> tuple[List[Dict], List[Dict]]:
    """Fetch X posts using Nitter scraping (Free fallback)."""
    try:
        from ntscraper import Nitter
        logging.info("Using Nitter scraper as fallback...")
    except ImportError:
        logging.warning("ntscraper not installed. Cannot use free Nitter scraping.")
        return [], []

    scraper = Nitter(log_level=1, skip_instance_check=False)
    all_posts = []
    
    # Limit to top accounts to save time and reduce failure chance
    priority_accounts = [u for u in usernames if u.lower() in ["elonmusk", "tesla", "sawyermerritt", "tesla_ai"]]
    if not priority_accounts:
        priority_accounts = usernames[:5]
    
    for username in priority_accounts:
        try:
            logging.info(f"Scraping tweets for @{username}...")
            tweets_data = scraper.get_tweets(username, mode='user', number=5)
            
            if not tweets_data or 'tweets' not in tweets_data:
                continue
                
            for tweet in tweets_data['tweets']:
                if tweet.get('is_pinned', False):
                    continue
                
                text = tweet.get('text', '')
                likes = tweet['stats'].get('likes', 0)
                retweets = tweet['stats'].get('retweets', 0)
                comments = tweet['stats'].get('comments', 0)
                
                score = (likes * 1.0) + (retweets * 3.0) + (comments * 1.5)
                if username.lower() == 'elonmusk':
                    score *= 3.0
                    
                all_posts.append({
                    "id": tweet['link'].split('/')[-1] if 'link' in tweet else '',
                    "text": text,
                    "username": username,
                    "name": tweet['user']['name'],
                    "url": tweet['link'],
                    "created_at": tweet['date'],
                    "likes": likes,
                    "retweets": retweets,
                    "replies": comments,
                    "final_score": score,
                    "is_elon_or_sawyer_repost": False,
                    "hours_old": 0
                })
        except Exception as e:
            logging.warning(f"Failed to scrape {username}: {e}")
            continue

    all_posts.sort(key=lambda x: x['final_score'], reverse=True)
    return all_posts[:25], all_posts

# X POSTS FUNCTION DISABLED - No longer fetching X posts to avoid API costs
# def fetch_top_x_posts_from_trusted_accounts() -> tuple[List[Dict], List[Dict]]:
#     """This function has been disabled to avoid X API costs."""
#     return [], []

# X POSTS DISABLED - No longer fetching X posts to avoid API costs
logging.info("Step 2: X posts fetching disabled (to avoid API costs)")

# ========================== SAVE RAW DATA AND GENERATE HTML PAGE ==========================
logging.info("Saving raw data and generating HTML page for raw news and X posts...")

def save_raw_data_and_generate_html(raw_news, raw_x_posts_data, output_dir):
    """Save raw data to JSON and generate HTML page for GitHub Pages."""
    today = datetime.date.today()
    date_str = today.strftime("%Y-%m-%d")
    
    # Prepare raw data structure
    raw_data = {
        "date": date_str,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "rss_feeds": {
            "total_articles": len(raw_news),
            "articles": raw_news
        },
        "x_api": {
            "total_posts": len(raw_x_posts_data),
            "posts": raw_x_posts_data
        }
    }
    
    # Save JSON file
    json_path = output_dir / f"raw_data_{date_str}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, indent=2, ensure_ascii=False)
    logging.info(f"Raw data saved to {json_path}")
    
    # Generate HTML page
    html_content = generate_raw_data_html(raw_data, output_dir)
    
    # Save date-specific HTML
    html_path = output_dir / f"raw_data_{date_str}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    logging.info(f"HTML page generated at {html_path}")
    
    # Also update index.html to point to latest
    index_path = output_dir / "raw_data_index.html"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    logging.info(f"Index HTML updated at {index_path}")
    
    return json_path, html_path

def generate_raw_data_html(raw_data, output_dir):
    """Generate HTML page displaying raw news and X posts."""
    date_str = raw_data["date"]
    formatted_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %d, %Y")
    
    # Find all existing JSON files to build archive
    json_files = sorted(output_dir.glob("raw_data_*.json"), reverse=True)
    archive_dates = []
    for json_file in json_files[:30]:  # Last 30 days
        date_part = json_file.stem.replace("raw_data_", "")
        try:
            archive_date = datetime.datetime.strptime(date_part, "%Y-%m-%d")
            archive_dates.append({
                "date": date_part,
                "formatted": archive_date.strftime("%B %d, %Y")
            })
        except:
            pass
    
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Raw Tesla News & X Posts - {formatted_date} | Tesla Shorts Time</title>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, sans-serif;
            line-height: 1.6;
            color: #333;
            background: #f5f5f5;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #e31937;
            margin-bottom: 10px;
            font-size: 2.5em;
        }}
        .subtitle {{
            color: #666;
            margin-bottom: 30px;
            font-size: 1.1em;
        }}
        .archive {{
            background: #f9f9f9;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 30px;
        }}
        .archive h2 {{
            font-size: 1.2em;
            margin-bottom: 10px;
            color: #333;
        }}
        .archive-links {{
            display: flex;
            flex-wrap: wrap;
            gap: 10px;
        }}
        .archive-link {{
            padding: 5px 12px;
            background: #e31937;
            color: white;
            text-decoration: none;
            border-radius: 4px;
            font-size: 0.9em;
        }}
        .archive-link:hover {{
            background: #c0152d;
        }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: linear-gradient(135deg, #e31937 0%, #c0152d 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }}
        .stat-number {{
            font-size: 2.5em;
            font-weight: bold;
            margin-bottom: 5px;
        }}
        .stat-label {{
            font-size: 0.9em;
            opacity: 0.9;
        }}
        .section {{
            margin-bottom: 40px;
        }}
        .section h2 {{
            color: #e31937;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #e31937;
        }}
        .article, .post {{
            background: #f9f9f9;
            padding: 20px;
            margin-bottom: 15px;
            border-radius: 5px;
            border-left: 4px solid #e31937;
        }}
        .article:hover, .post:hover {{
            background: #f0f0f0;
            transform: translateX(5px);
            transition: all 0.2s;
        }}
        .article-title, .post-text {{
            font-weight: bold;
            font-size: 1.1em;
            margin-bottom: 10px;
            color: #333;
        }}
        .article-meta, .post-meta {{
            color: #666;
            font-size: 0.9em;
            margin-bottom: 10px;
        }}
        .article-link, .post-link {{
            color: #e31937;
            text-decoration: none;
            font-weight: bold;
        }}
        .article-link:hover, .post-link:hover {{
            text-decoration: underline;
        }}
        .engagement {{
            display: inline-block;
            background: #e31937;
            color: white;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 0.85em;
            margin-left: 10px;
        }}
        .description {{
            color: #555;
            margin-top: 10px;
            line-height: 1.5;
        }}
        @media (max-width: 768px) {{
            .container {{
                padding: 15px;
            }}
            h1 {{
                font-size: 1.8em;
            }}
            .stats {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🚗⚡ Tesla Shorts Time - Raw Data</h1>
        <p class="subtitle">Daily Raw News & X Posts Archive - {formatted_date}</p>
        
        <div class="archive">
            <h2>📅 Archive</h2>
            <div class="archive-links">
                <a href="raw_data_index.html" class="archive-link">Today</a>
"""
    
    # Add archive links
    for archive_date in archive_dates:
        if archive_date["date"] != date_str:
            html_content += f'                <a href="raw_data_{archive_date["date"]}.html" class="archive-link">{archive_date["formatted"]}</a>\n'
    
    html_content += """            </div>
        </div>
        
        <div class="stats">
            <div class="stat-card">
                <div class="stat-number">""" + str(raw_data["rss_feeds"]["total_articles"]) + """</div>
                <div class="stat-label">News Articles</div>
            </div>
            <div class="stat-card">
                <div class="stat-number">""" + str(raw_data["x_api"]["total_posts"]) + """</div>
                <div class="stat-label">X Posts</div>
            </div>
        </div>
        
        <div class="section">
            <h2>📰 RSS Feed Articles (Raw)</h2>
"""
    
    # Add news articles
    for i, article in enumerate(raw_data["rss_feeds"]["articles"], 1):
        title = html.escape(str(article.get("title") or "No title"))
        description = html.escape(str(article.get("description") or "No description"))
        url = html.escape(str(article.get("url") or "#"))
        source = html.escape(article.get("source", {}).get("name", "Unknown") if isinstance(article.get("source"), dict) else str(article.get("source", "Unknown")))
        published = article.get("publishedAt", "Unknown")
        author = html.escape(str(article.get("author") or "Unknown"))
        
        html_content += f"""            <div class="article">
                <div class="article-title">{i}. {title}</div>
                <div class="article-meta">
                    Source: {source} | Author: {author} | Published: {published}
                </div>
                <div class="description">{description}</div>
                <a href="{url}" target="_blank" class="article-link">Read Article →</a>
            </div>
"""
    
    html_content += """        </div>
        
        <div class="section">
            <h2>🐦 X Posts (Raw)</h2>
"""
    
    # Add X posts
    for i, post in enumerate(raw_data["x_api"]["posts"], 1):
        text = html.escape(str(post.get("text") or "No text"))
        username = html.escape(str(post.get("username") or "unknown"))
        name = html.escape(str(post.get("name") or "Unknown"))
        url = html.escape(str(post.get("url") or "#"))
        created_at = post.get("created_at", "Unknown")
        engagement = post.get("engagement", 0)
        likes = post.get("likes", 0)
        retweets = post.get("retweets", 0)
        replies = post.get("reply_count", 0)
        
        html_content += f"""            <div class="post">
                <div class="post-text">{i}. {text}</div>
                <div class="post-meta">
                    @{username} ({name}) | {created_at} | 
                    ❤️ {likes} | 🔄 {retweets} | 💬 {replies}
                    <span class="engagement">Engagement: {engagement:.0f}</span>
                </div>
                <a href="{url}" target="_blank" class="post-link">View Post →</a>
            </div>
"""
    
    html_content += """        </div>
        
        <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; text-align: center; color: #666;">
            <p>Generated automatically by Tesla Shorts Time Daily</p>
            <p><a href="https://github.com/patricknovak/Tesla-shorts-time" style="color: #e31937;">View on GitHub</a></p>
        </div>
    </div>
</body>
</html>"""
    
    return html_content

# Save raw data and generate HTML
raw_json_path, raw_html_path = save_raw_data_and_generate_html(
    raw_news_articles, 
    raw_x_posts, 
    digests_dir
)

# ========================== STEP 3: GENERATE X THREAD WITH GROK ==========================
logging.info("Step 3: Generating Tesla Shorts Time digest with Grok using pre-fetched news and X posts...")

# Format news articles for the prompt
news_section = ""
if tesla_news:
    news_section = "## PRE-FETCHED NEWS ARTICLES (from RSS feeds - last 24 hours):\n\n"
    for i, article in enumerate(tesla_news[:20], 1):  # Top 20 articles
        news_section += f"{i}. **{article['title']}**\n"
        news_section += f"   Source: {article['source']}\n"
        news_section += f"   Published: {article['publishedAt']}\n"
        if article.get('description'):
            news_section += f"   Description: {article['description'][:200]}...\n"
        news_section += f"   URL: {article['url']}\n\n"
else:
    news_section = "## PRE-FETCHED NEWS ARTICLES: None available (you may need to search for news)\n\n"

# X POSTS SECTION DISABLED - No longer including X posts in prompt
x_posts_section = ""


X_PROMPT = f"""
# Tesla Shorts Time - DAILY EDITION
**Date:** {today_str}
**REAL-TIME TSLA price:** ${price:.2f} {change_str}

{news_section}

{x_posts_section}

You are an elite Tesla news curator producing the daily "Tesla Shorts Time" newsletter. Use ONLY the pre-fetched news above. Do NOT hallucinate, invent, or search for new content/URLs—stick to exact provided links. Do NOT include a "Top X Posts" section in your output. Prioritize diversity: No duplicates/similar stories (≥70% overlap in angle/content); max 3 from one source/account.

**EXCEPTION FOR X SPOTLIGHT SECTION**: For the "X Spotlight: @{spotlight_username}" section ONLY, you may use web search or your knowledge to find recent Tesla-related posts from @{spotlight_username} on X. Curate the top 5 most engaging posts from the past week and provide an overall weekly sentiment summary. Use actual post URLs when possible (format: https://x.com/{spotlight_username}/status/[POST_ID]).

{used_content_summary}

### MANDATORY SELECTION & COUNTS (CRITICAL - FOLLOW EXACTLY)
- **News**: You MUST select EXACTLY 10 unique articles. If you have fewer than 10 available, use ALL of them and number them 1 through N (where N is the count). If you have more than 10, select the BEST 10 and number them 1-10. DO NOT output 20 items - output EXACTLY 10. Prioritize high-quality sources; each must cover a DIFFERENT Tesla story/angle.
- **CRITICAL URL RULE**: NEVER invent URLs. If you don't have enough pre-fetched articles, output fewer items rather than making up URLs. All URLs must be exact matches from the pre-fetched list above.
- **Diversity Check**: Before finalizing, verify no similar content; replace if needed from pre-fetched pool.

### FORMATTING (EXACT—USE MARKDOWN AS SHOWN)
# Tesla Shorts Time
**Date:** {today_str}
**REAL-TIME TSLA price:** ${price:.2f} {change_str}

━━━━━━━━━━━━━━━━━━━━
### Top 10 News Items
1. **Title (One Line): DD Month, YYYY, HH:MM AM/PM PST, Source Name**  
   2–4 sentences: Start with what happened, then why it matters for Tesla's future/stock. End with: Source: [EXACT URL FROM PRE-FETCHED—no mods]
2. [Repeat format for 3-10; if <10 items, stop at available count, add a blank line after each item and the last item]

━━━━━━━━━━━━━━━━━━━━
## X Spotlight: @{spotlight_username}
🎯 TODAY'S FOCUS: You must curate content from @{spotlight_username} ({spotlight_display_name}) on X.

**TOP 5 TESLA X POSTS FROM @{spotlight_username}:**
Using your knowledge of X (formerly Twitter) and public information, curate the top 5 most engaging, insightful, or newsworthy Tesla-related posts from @{spotlight_username} from the past week. For each post:
1. **Post Title/Summary: DD Month, YYYY (if known)**  
   Brief description of the post content (2-3 sentences). Include the key Tesla-related insight, news, or perspective shared.
   Post: https://x.com/{spotlight_username}/status/[POST_ID] (use actual post URLs if you can find them, or format as shown)

**OVERALL WEEKLY SENTIMENT OF TESLA ON X FROM @{spotlight_username}:**
Provide a 2-3 sentence summary of the overall sentiment and themes that @{spotlight_username} has been sharing about Tesla this past week. Is the sentiment bullish, bearish, neutral? What are the main topics they've been covering? What's their perspective on Tesla's current trajectory?

━━━━━━━━━━━━━━━━━━━━
## Short Spot
🚨 CRITICAL: This must be COMPLETELY DIFFERENT from any recent Short Spots. Use a DIFFERENT bearish story, DIFFERENT angle, and DIFFERENT framing than what was used recently.
One bearish item from pre-fetched news that's negative for Tesla/stock.  
**Catchy Title: DD Month, YYYY, HH:MM AM/PM PST, @username/Source**  
2–4 sentences explaining it & why it's temporary/overblown (frame optimistically). End with: Source/Post: [EXACT URL]

━━━━━━━━━━━━━━━━━━━━
### Short Squeeze
🚨 CRITICAL: This must be COMPLETELY DIFFERENT from any recent Short Squeezes. Use DIFFERENT failed predictions, DIFFERENT bear names, DIFFERENT years, and DIFFERENT examples. Do NOT repeat the same predictions or bears from recent days.
Dedicated paragraph on short-seller pain:
Add specific failed bear predictions (2020–2025, with references and links from past). Vary the years, vary the bear names, vary the specific predictions. Make it fresh and engaging every day.

━━━━━━━━━━━━━━━━━━━━
### Daily Challenge
🚨 CRITICAL: This must be COMPLETELY NEW and DIFFERENT from any recent Daily Challenges. Use a DIFFERENT theme, DIFFERENT approach, and DIFFERENT wording. Avoid repetition at all costs.
One short, inspiring challenge tied to Tesla/Elon themes (curiosity, first principles, perseverance, innovation, sustainability, etc.). Vary the themes daily. End with: "Share your progress with us @teslashortstime!"

━━━━━━━━━━━━━━━━━━━━
**Inspiration Quote:** 
🚨 CRITICAL: This must be from a DIFFERENT author than recent quotes. Use a DIFFERENT quote with a DIFFERENT message. Vary authors widely - use quotes from scientists, entrepreneurs, philosophers, leaders, innovators, etc. Never repeat the same author or similar message.
"Exact quote" – Author, [Source Link] (fresh, no repeats and from a wide variety of sources)

[2-3 sentence uplifting sign-off on Tesla's mission + invite to DM @teslashortstime with feedback.]

(Add blank line after sign-off.)

### TONE & STYLE
- Inspirational, pro-Tesla, optimistic, energetic.
- Timestamps: Accurate PST/PDT (convert from pre-fetched).
- No stock-quote pages/pure price commentary as "news."

### FINAL VALIDATION CHECKLIST (DO THIS BEFORE OUTPUT)
- ✅ Exactly 10 news items (or all if <10): Numbered 1-10, unique stories.
- ✅ X Spotlight section included with Top 5 posts from @{spotlight_username} and weekly sentiment summary.
- ✅ Podcast link: Full URL as shown.
- ✅ Lists: "1. " format (number, period, space)—no bullets.
- ✅ Separators: "━━━━━━━━━━━━━━━━━━━━" before each major section.
- ✅ No duplicates: All items unique (review pairwise).
- ✅ All sections included: X Spotlight, Short Spot, Short Squeeze, Daily Challenge, Quote, sign-off.
- ✅ URLs: Exact from pre-fetched; valid format; no inventions.
- ✅ FRESHNESS CHECK: Short Spot is DIFFERENT from recent ones (different story/angle).
- ✅ FRESHNESS CHECK: Short Squeeze uses DIFFERENT predictions/bears/years than recent ones.
- ✅ FRESHNESS CHECK: Daily Challenge is COMPLETELY NEW and DIFFERENT from recent ones.
- ✅ FRESHNESS CHECK: Inspiration Quote is from a DIFFERENT author than recent quotes.
- If any fail, adjust selections and re-check.

Output today's edition exactly as formatted.
"""

logging.info("Generating X thread with Grok using pre-fetched content (this may take 1-2 minutes)...")

# Enable web search ONLY for X Spotlight section (Grok needs to find posts from spotlight account)
# For news items, we still use only pre-fetched content
enable_web_search = True
search_params = {"mode": "on"}  # Enable web search for X Spotlight curation
logging.info(f"✅ Web search enabled for X Spotlight section - Grok will curate posts from @{spotlight_username}")

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
        extra_body={"search_parameters": search_params}
    )
    return response

try:
    response = generate_digest_with_grok()
    x_thread = response.choices[0].message.content.strip()
    
    # Log token usage and cost
    if hasattr(response, 'usage') and response.usage:
        usage = response.usage
        logging.info(f"Grok API - Tokens used: {usage.total_tokens} (prompt: {usage.prompt_tokens}, completion: {usage.completion_tokens})")
        # Estimate cost (Grok pricing may vary, using approximate $0.01 per 1M tokens)
        estimated_cost = (usage.total_tokens / 1000000) * 0.01
        logging.info(f"Estimated cost: ${estimated_cost:.4f}")
        
        # Track credit usage
        credit_usage["services"]["grok_api"]["x_thread_generation"]["prompt_tokens"] = usage.prompt_tokens
        credit_usage["services"]["grok_api"]["x_thread_generation"]["completion_tokens"] = usage.completion_tokens
        credit_usage["services"]["grok_api"]["x_thread_generation"]["total_tokens"] = usage.total_tokens
        credit_usage["services"]["grok_api"]["x_thread_generation"]["estimated_cost_usd"] = estimated_cost
except Exception as e:
    logging.error(f"Grok API call failed: {e}")
    logging.error("This might be due to network issues or API timeout. Please try again.")
    raise

# Clean Grok footer
lines = []
for line in x_thread.splitlines():
    if line.strip().startswith(("**Sources", "Grok", "I used", "[")):
        break
    lines.append(line)
x_thread = "\n".join(lines).strip()

# Post-process to enforce exactly 10 items per section (fix Grok's tendency to output 20)
# Also fix podcast link and X post URLs
import re

# First, ensure podcast link is present with full URL
podcast_url = 'https://podcasts.apple.com/us/podcast/tesla-shorts-time/id1855142939'
podcast_link_md = f'🎙️ **Tesla Shorts Time Daily Podcast Link:** {podcast_url}'
if podcast_url not in x_thread:
    # Find price line and insert podcast link after it
    price_match = re.search(r'(\*\*REAL-TIME TSLA price:\*\*[^\n]+\n)', x_thread)
    if price_match:
        x_thread = x_thread[:price_match.end()] + '\n' + podcast_link_md + '\n\n' + x_thread[price_match.end():]
    else:
        # Insert after date line
        date_match = re.search(r'(\*\*Date:\*\*[^\n]+\n)', x_thread)
        if date_match:
            x_thread = x_thread[:date_match.end()] + '\n' + podcast_link_md + '\n\n' + x_thread[date_match.end():]
        else:
            # Insert at the beginning after header
            header_match = re.search(r'(# Tesla Shorts Time[^\n]+\n)', x_thread)
            if header_match:
                x_thread = x_thread[:header_match.end()] + '\n' + podcast_link_md + '\n\n' + x_thread[header_match.end():]

# Fix X post URLs - remove markdown brackets
x_thread = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'\2', x_thread)
x_thread = re.sub(r'\[(https?://[^\]]+)\]', r'\1', x_thread)
# Fix URLs with trailing brackets
x_thread = re.sub(r'(https?://x\.com/[^\s\)\]]+)[\)\]]+', r'\1', x_thread)

# Find and limit news items to exactly 10
news_pattern = r'(### Top 10 News Items.*?)(## Short Spot|### Short Squeeze|━━)'
news_match = re.search(news_pattern, x_thread, re.DOTALL | re.IGNORECASE)
if news_match:
    news_section = news_match.group(1)
    # Count numbered items (1. through 10.)
    news_items = re.findall(r'^(\d+)\.\s+\*\*', news_section, re.MULTILINE)
    if len(news_items) > 10:
        # Find all numbered items
        items = re.findall(r'^(\d+)\.\s+.*?(?=^\d+\.|###|##|━━|$)', news_section, re.MULTILINE | re.DOTALL)
        if len(items) > 10:
            # Keep only first 10, renumber them
            kept_items = items[:10]
            new_news_section = "### Top 10 News Items\n\n"
            for i, item in enumerate(kept_items, 1):
                # Remove old number and add new number
                item_cleaned = re.sub(r'^\d+\.\s+', '', item, flags=re.MULTILINE)
                new_news_section += f"{i}. {item_cleaned.strip()}\n\n"
            x_thread = x_thread.replace(news_match.group(1), new_news_section)

# X POSTS PARSING DISABLED - No longer parsing or adding X posts section

# Validate counts - check if we have exactly 10 news items
import re
news_count = len(re.findall(r'^[1-9]|10[️⃣\.]\s+\*\*', x_thread, re.MULTILINE))
# Also check for numbered lists without emojis
if news_count < 10:
    news_count = len(re.findall(r'^([1-9]|10)\.\s+\*\*', x_thread, re.MULTILINE))

if news_count != 10:
    logging.warning(f"⚠️  WARNING: Found {news_count} news items instead of 10. Grok may not have followed instructions.")

# ========================== VALIDATE AND FIX LINKS ==========================
# Link validation functions removed - disabled via ENABLE_LINK_VALIDATION = False
# If validation is needed in the future, set ENABLE_LINK_VALIDATION = True and re-implement

# ========================== STEP 4: FORMAT DIGEST FOR BEAUTIFUL X POST ==========================
logging.info("Step 4: Formatting digest for beautiful X post...")

def format_digest_for_x(digest: str) -> str:
    """
    Format the digest beautifully for a long X post with emojis, proper spacing, and visual appeal.
    X supports up to 25,000 characters for long posts.
    """
    import re
    
    formatted = digest
    
    # Add emoji to main header (only if it's the first line)
    formatted = re.sub(r'^# Tesla Shorts Time', '🚗⚡ **Tesla Shorts Time**', formatted, flags=re.MULTILINE)
    
    # Format date line with emoji
    formatted = re.sub(r'\*\*Date:\*\*', '📅 **Date:**', formatted)
    
    # Format price line with emoji
    formatted = re.sub(r'\*\*REAL-TIME TSLA price:\*\*', '💰 **REAL-TIME TSLA price:**', formatted)
    
    # Ensure podcast link is always present with full URL (add it if missing or incomplete)
    podcast_url = 'https://podcasts.apple.com/us/podcast/tesla-shorts-time/id1855142939'
    podcast_link_md = f'🎙️ **Tesla Shorts Time Daily Podcast Link:** {podcast_url}'
    
    # Check if the full URL is present (not just the text)
    # Also check for incomplete podcast links (has emoji but no URL)
    # More aggressive check - look for any line with podcast emoji that doesn't have the full URL
    has_incomplete_podcast_link = bool(re.search(r'🎙️[^\n]*[Pp]odcast[^\n]*(?!https://)', formatted))
    # Also check if podcast link line exists but URL is missing
    podcast_line_without_url = bool(re.search(r'🎙️[^\n]*[Pp]odcast[^\n]*\n(?!.*https://podcasts\.apple\.com)', formatted, re.DOTALL))
    
    if podcast_url not in formatted or has_incomplete_podcast_link or podcast_line_without_url:
        # Remove any incomplete podcast link text
        lines = formatted.split('\n')
        cleaned_lines = []
        for line in lines:
            # If line mentions podcast but doesn't have the full URL, skip it
            if ('podcast' in line.lower() or '🎙️' in line) and podcast_url not in line:
                continue
            cleaned_lines.append(line)
        formatted = '\n'.join(cleaned_lines)
        
        # Find the price line and insert podcast link right after it
        lines = formatted.split('\n')
        insert_pos = None
        for i, line in enumerate(lines):
            # Look for price line (with or without emoji)
            if 'REAL-TIME TSLA price' in line or '💰' in line:
                insert_pos = i + 1
                break
            # Fallback: look for date line
            elif 'Date:' in line and '📅' in line and insert_pos is None:
                insert_pos = i + 1
        
        # If we found a position, insert the podcast link
        if insert_pos is not None:
            lines.insert(insert_pos, '')
            lines.insert(insert_pos + 1, podcast_link_md)
            lines.insert(insert_pos + 2, '')
        else:
            # Last resort: add at the very beginning after header
            header_end = 0
            for i, line in enumerate(lines[:5]):
                if line.strip() and (line.startswith('#') or line.startswith('🚗')):
                    header_end = i
            lines.insert(header_end + 1, '')
            lines.insert(header_end + 2, podcast_link_md)
            lines.insert(header_end + 3, '')
        
        formatted = '\n'.join(lines)
    else:
        # URL is present, ensure it has the emoji prefix and proper formatting
        # Replace any variation of the podcast link with the properly formatted version
        formatted = re.sub(
            r'🎙️?\s*[Tt]esla\s+[Ss]horts\s+[Tt]ime\s+[Dd]aily\s+[Pp]odcast\s+[Ll]ink:?\s*' + re.escape(podcast_url),
            podcast_link_md,
            formatted,
            flags=re.IGNORECASE
        )
        # Also handle case where URL is there but formatting is wrong
        if podcast_url in formatted and '🎙️' not in formatted.split(podcast_url)[0][-50:]:
            # URL exists but no emoji nearby, add it
            formatted = re.sub(
                r'([^\n]*)' + re.escape(podcast_url),
                r'\1\n' + podcast_link_md,
                formatted,
                count=1
            )
    
    # Format section headers with emojis (preserve existing markdown)
    formatted = re.sub(r'^### Top 10 News Items', '📰 **Top 10 News Items**', formatted, flags=re.MULTILINE)
    # Format X Spotlight section
    formatted = re.sub(r'^## X Spotlight: @(\w+)', r'🌟 **X Spotlight: @\1**', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^## X Spotlight:', '🌟 **X Spotlight:**', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^### X Spotlight:', '🌟 **X Spotlight:**', formatted, flags=re.MULTILINE)
    # X POSTS SECTION DISABLED - No longer formatting X posts header
    formatted = re.sub(r'^## Short Spot', '📉 **Short Spot**', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^### Short Squeeze', '📈 **Short Squeeze**', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^### Daily Challenge', '💪 **Daily Challenge**', formatted, flags=re.MULTILINE)
    
    # Add emoji to Inspiration Quote
    formatted = re.sub(r'\*\*Inspiration Quote:\*\*', '✨ **Inspiration Quote:**', formatted)
    
    # Add separator lines before major sections
    separator = '\n\n━━━━━━━━━━━━━━━━━━━━\n\n'
    
    # First, remove any existing separators to avoid duplicates
    formatted = re.sub(r'\n\n━━━━━━━━━━━━━━━━━━━━\n\n+', '\n\n', formatted)
    
    # Add separator before Top 10 News Items (check multiple patterns)
    formatted = re.sub(r'(\n\n?)(📰 \*\*Top 10 News Items\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n?)(### Top 10 News Items)', separator + r'\2', formatted)
    # Also match after podcast link
    formatted = re.sub(r'(Podcast Link:.*?\n)(📰|\*\*Top 10 News|### Top 10 News)', separator + r'\2', formatted, flags=re.DOTALL)
    
    # Add separator before X Spotlight
    formatted = re.sub(r'(\n\n?)(🌟 \*\*X Spotlight)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n?)(## X Spotlight|### X Spotlight)', separator + r'\2', formatted)
    # Also match after last news item (10.)
    formatted = re.sub(r'(10[️⃣\.]\s+.*?\n)(🌟|\*\*X Spotlight|## X Spotlight|### X Spotlight)', separator + r'\2', formatted, flags=re.DOTALL)
    
    # X POSTS SEPARATOR DISABLED - No longer adding separator before X posts
    
    # Add separator before Short Spot
    formatted = re.sub(r'(\n\n?)(📉 \*\*Short Spot\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n?)(## Short Spot)', separator + r'\2', formatted)
    # Also match after X Spotlight section
    formatted = re.sub(r'(Overall Weekly Sentiment.*?\n)(📉|\*\*Short Spot|## Short Spot)', separator + r'\2', formatted, flags=re.DOTALL)
    
    # Add separator before Short Squeeze
    formatted = re.sub(r'(\n\n?)(📈 \*\*Short Squeeze\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n?)(### Short Squeeze)', separator + r'\2', formatted)
    
    # Add separator before Daily Challenge
    formatted = re.sub(r'(\n\n?)(💪 \*\*Daily Challenge\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n?)(### Daily Challenge)', separator + r'\2', formatted)
    
    # Add separator before Inspiration Quote
    formatted = re.sub(r'(\n\n?)(✨ \*\*Inspiration Quote:\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n?)(\*\*Inspiration Quote:\*\*)', separator + r'\2', formatted)
    
    # Add emoji to numbered list items for news (1️⃣, 2️⃣, etc.)
    emoji_numbers = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣', '🔟']
    
    # Find the news section and apply emojis
    if '📰' in formatted or 'Top 10 News' in formatted:
        news_section_match = re.search(r'(📰.*?Top 10 News Items.*?)(📉|Short Spot|━━)', formatted, re.DOTALL)
        if news_section_match:
            news_section = news_section_match.group(1)
            for i in range(1, 11):
                emoji_num = emoji_numbers[i-1]
                # Replace numbered items in news section
                news_section = re.sub(
                    rf'^(\s*){i}\.\s+',
                    lambda m: m.group(1) + emoji_num + ' ',
                    news_section,
                    flags=re.MULTILINE
                )
            formatted = formatted.replace(news_section_match.group(1), news_section)
    
    # X POSTS EMOJI FORMATTING DISABLED - No longer formatting X posts emojis
    
    # Clean up excessive newlines (more than 3 consecutive becomes 2)
    formatted = re.sub(r'\n{4,}', '\n\n', formatted)
    
    # Ensure proper spacing: add a blank line before numbered items if missing
    formatted = re.sub(r'\n(\d+\.)', r'\n\n\1', formatted)
    
    # Clean up: remove any triple newlines that might have been created
    formatted = re.sub(r'\n{3,}', '\n\n', formatted)
    
    # Clean up any markdown code blocks if any (they don't render well on X)
    formatted = re.sub(r'```[^`]*```', '', formatted, flags=re.DOTALL)
    
    # Ensure the post ends nicely if it doesn't already
    formatted = formatted.strip()
    if formatted and not formatted[-1] in '!?.':
        # Check if it ends with a quote or sign-off
        last_lines = formatted.split('\n')[-3:]
        last_text = ' '.join(last_lines).strip()
        if not any(word in last_text.lower() for word in ['feedback', 'dm', 'accelerating', 'electric', 'mission']):
            formatted += '\n\n⚡ Keep accelerating!'
    
    # Fix X post URLs - remove markdown brackets and ensure plain text URLs
    # Replace [text](url) or [url] with just the URL
    formatted = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'\2', formatted)
    formatted = re.sub(r'\[(https?://[^\]]+)\]', r'\1', formatted)
    # Fix URLs that might have trailing brackets or parentheses
    formatted = re.sub(r'(https?://x\.com/[^\s\)\]]+)[\)\]]+', r'\1', formatted)
    
    # Final cleanup: normalize whitespace
    # Replace multiple spaces with single space (but preserve intentional formatting)
    lines = formatted.split('\n')
    cleaned_lines = []
    for line in lines:
        # Preserve lines that are mostly spaces (intentional spacing)
        if line.strip() == '':
            cleaned_lines.append('')
        else:
            # Clean up excessive spaces but preserve markdown formatting
            cleaned_line = re.sub(r'[ \t]{2,}', ' ', line)
            cleaned_lines.append(cleaned_line)
    formatted = '\n'.join(cleaned_lines)
    
    # Final newline cleanup
    formatted = re.sub(r'\n{3,}', '\n\n', formatted)
    formatted = formatted.strip()
    
    # Check character limit (X allows 25,000 characters for long posts)
    max_chars = 25000
    if len(formatted) > max_chars:
        logging.warning(f"Formatted digest is {len(formatted)} characters, truncating to {max_chars}")
        # Try to truncate at a natural break point
        truncate_at = formatted[:max_chars-100].rfind('\n\n')
        if truncate_at > max_chars * 0.8:  # Only if we can keep at least 80% of content
            formatted = formatted[:truncate_at] + "\n\n... (content truncated for length)"
        else:
            formatted = formatted[:max_chars-50] + "\n\n... (truncated for length)"
    
    return formatted

# Format the digest
x_thread_formatted = format_digest_for_x(x_thread)
logging.info(f"Digest formatted for X ({len(x_thread_formatted)} characters)")

# Save both versions (original and formatted)
x_path = digests_dir / f"Tesla_Shorts_Time_{datetime.date.today():%Y%m%d}.md"
x_path_formatted = digests_dir / f"Tesla_Shorts_Time_{datetime.date.today():%Y%m%d}_formatted.md"

with open(x_path, "w", encoding="utf-8") as f:
    f.write(x_thread)
logging.info(f"Original X thread saved → {x_path}")

with open(x_path_formatted, "w", encoding="utf-8") as f:
    f.write(x_thread_formatted)
logging.info(f"Formatted X thread saved → {x_path_formatted}")

# Use the formatted version for posting
x_thread = x_thread_formatted

# Save X thread
x_path = digests_dir / f"Tesla_Shorts_Time_{datetime.date.today():%Y%m%d}.md"
with open(x_path, "w", encoding="utf-8") as f:
    f.write(x_thread)
logging.info(f"X thread generated and saved → {x_path}")

# ========================== SAVE NEW CONTENT TO TRACKER ==========================
# Extract sections from the newly generated digest and save to tracker
today_date = datetime.date.today().isoformat()
new_sections = extract_sections_from_digest(x_path)

if new_sections["short_spot"]:
    content_tracker["short_spots"].append({
        "date": today_date,
        "content": new_sections["short_spot"][:500]
    })
    logging.info("Saved new Short Spot to content tracker")

if new_sections["short_squeeze"]:
    content_tracker["short_squeezes"].append({
        "date": today_date,
        "content": new_sections["short_squeeze"][:500]
    })
    logging.info("Saved new Short Squeeze to content tracker")

if new_sections["daily_challenge"]:
    content_tracker["daily_challenges"].append({
        "date": today_date,
        "content": new_sections["daily_challenge"][:500]
    })
    logging.info("Saved new Daily Challenge to content tracker")

if new_sections["inspiration_quote"]:
    content_tracker["inspiration_quotes"].append({
        "date": today_date,
        "content": new_sections["inspiration_quote"][:200]
    })
    logging.info("Saved new Inspiration Quote to content tracker")

# Save the updated tracker
save_used_content_tracker(content_tracker)
logging.info("Content tracker updated with today's sections")

# Exit early if in test mode (only generate digest)
if TEST_MODE:
    print("\n" + "="*80)
    print("TEST MODE - Digest generated only (skipping podcast and X posting)")
    print(f"Digest saved to: {x_path}")
    print("="*80)
    sys.exit(0)

# ========================== TWEEPY X CLIENT FOR AUTO-POSTING ==========================
tweet_id = None
if ENABLE_X_POSTING:
    import tweepy

    x_client = tweepy.Client(
        consumer_key=os.getenv("X_CONSUMER_KEY"),
        consumer_secret=os.getenv("X_CONSUMER_SECRET"),
        access_token=os.getenv("X_ACCESS_TOKEN"),
        access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
        bearer_token=os.getenv("X_BEARER_TOKEN"),
        wait_on_rate_limit=True
    )
    logging.info("@teslashortstime X posting client ready")
else:
    logging.info("X posting is disabled (ENABLE_X_POSTING = False)")

# ========================== 2. GENERATE PODCAST SCRIPT (NATURAL & FACT-BASED) ==========================
if not ENABLE_PODCAST:
    logging.info("Podcast generation is disabled (ENABLE_PODCAST = False). Skipping podcast script generation, audio processing, and RSS feed updates.")
    final_mp3 = None
else:
    # Simplified podcast prompt - use only the final formatted digest
    POD_PROMPT = f"""You are writing an 8–11 minute (1950–2600 words) solo podcast script for "Tesla Shorts Time Daily" Episode {episode_num}.

HOST: Patrick in Vancouver - Canadian, scientist, newscaster. Voice like a solo Podcaster breaking Tesla news, not robotic.

RULES:
- Start every line with "Patrick:"
- Don't read URLs aloud - mention source names naturally
- Use natural dates ("today", "this morning") not exact timestamps
- Enunciate all numbers, dollar amounts, percentages clearly
- Use ONLY information from the digest below - nothing else

SCRIPT STRUCTURE:
[Intro music - 10 seconds]
Patrick: Welcome to Tesla Shorts Time Daily, episode {episode_num}. It is {today_str}. I'm Patrick in Vancouver, Canada bringing you the latest Tesla news and updates.  Thank you for joining us today. If you like the show, please like, share, rate and subscribe to the podcast, it really helps. Now straight to the daily news updates you are here for.

[Narrate EVERY item from the digest in order - no skipping]
- For each news item: Read the title with enthusiasm, then paraphrase the summary naturally
- X Spotlight: Introduce the spotlight account (@{spotlight_username} - {spotlight_display_name}) with enthusiasm. Read each of the top 5 posts with excitement, explaining why each post matters. Then summarize the overall weekly sentiment from @{spotlight_username} about Tesla. Make it engaging and highlight why this account's perspective is valuable.
- Short Squeeze: Paraphrase with enthusiasm, calling out specific failed predictions and dollar losses
- Daily Challenge + Quote: Read the quote verbatim, then the challenge verbatim, add one encouraging sentence

[Closing]
Patrick: TSLA current stock price at the time of recording is ${price:.2f} right now.  Always good to know the short term, but with Tesla, the long term is what really matters.
Patrick: That's Tesla Shorts Time Daily for today. I look forward to hearing your thoughts and ideas — reach out to us @teslashortstime on X or DM us directly. Stay safe, keep accelerating, and remember: the future is electric! Your efforts help accelerate the world's transition to sustainable energy… and beyond. We'll catch you tomorrow on Tesla Shorts Time Daily!

Here is today's complete formatted digest. Use ONLY this content:
"""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((Exception,))
    )
    def generate_podcast_script_with_grok():
        """Generate podcast script with retry logic"""
        return client.chat.completions.create(
            model="grok-4",
            messages=[
                {"role": "system", "content": "You are the world's best Tesla podcast writer. Make it feel like two real Canadian friends losing their minds (in a good way) over real Tesla news."},
                {"role": "user", "content": f"{POD_PROMPT}\n\n{x_thread}"}
            ],
            temperature=0.9,  # higher = more natural energy
            max_tokens=4000
        )
    
    logging.info("Generating podcast script with Grok (this may take 1-2 minutes)...")
    try:
        # Use only the final formatted digest - much simpler and more reliable
        podcast_response = generate_podcast_script_with_grok()
        podcast_script = podcast_response.choices[0].message.content.strip()
        
        # Log token usage if available
        if hasattr(podcast_response, 'usage') and podcast_response.usage:
            usage = podcast_response.usage
            logging.info(f"Podcast script generation - Tokens used: {usage.total_tokens} (prompt: {usage.prompt_tokens}, completion: {usage.completion_tokens})")
            # Estimate cost (Grok pricing may vary, using approximate)
            estimated_cost = (usage.total_tokens / 1000000) * 0.01  # Rough estimate
            logging.info(f"Estimated cost: ${estimated_cost:.4f}")
            
            # Track credit usage
            credit_usage["services"]["grok_api"]["podcast_script_generation"]["prompt_tokens"] = usage.prompt_tokens
            credit_usage["services"]["grok_api"]["podcast_script_generation"]["completion_tokens"] = usage.completion_tokens
            credit_usage["services"]["grok_api"]["podcast_script_generation"]["total_tokens"] = usage.total_tokens
            credit_usage["services"]["grok_api"]["podcast_script_generation"]["estimated_cost_usd"] = estimated_cost
    except Exception as e:
        logging.error(f"Grok API call for podcast script failed: {e}")
        logging.error("This might be due to network issues or API timeout. Please try again.")
        raise

    # Save transcript
    transcript_path = digests_dir / f"podcast_transcript_{datetime.date.today():%Y%m%d}.txt"
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(f"# Tesla Shorts Time – The Pod | Ep {episode_num} | {today_str}\n\n{podcast_script}")
    logging.info("Natural podcast script generated – Patrick starts, super enthusiastic")

    # ========================== 3. ELEVENLABS TTS + COLLECT AUDIO FILES ==========================
    PATRICK_VOICE_ID = "dTrBzPvD2GpAqkk1MUzA"    # High-energy Patrick

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout))
    )
    def speak(text: str, voice_id: str, filename: str):
        url = f"{ELEVEN_API}/text-to-speech/{voice_id}/stream"
        headers = {"xi-api-key": ELEVEN_KEY}
        payload = {
            "text": text + "!",  # extra excitement
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": 0.65,
                "similarity_boost": 0.9,
                "style": 0.85,
                "use_speaker_boost": True
            }
        }
        r = requests.post(url, json=payload, headers=headers, stream=True, timeout=60)
        r.raise_for_status()
        with open(filename, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)


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


def scan_existing_episodes_from_files(digests_dir: Path, base_url: str) -> list:
    """Scan digests directory for all existing MP3 files and return episode data."""
    episodes = []
    pattern = r"Tesla_Shorts_Time_Pod_Ep(\d+)_(\d{8})\.mp3"
    
    for mp3_file in digests_dir.glob("Tesla_Shorts_Time_Pod_Ep*.mp3"):
        match = re.match(pattern, mp3_file.name)
        if match:
            episode_num = int(match.group(1))
            date_str = match.group(2)
            try:
                episode_date = datetime.datetime.strptime(date_str, "%Y%m%d").date()
                mp3_duration = get_audio_duration(mp3_file)
                
                # Create episode data
                # GUID based on date AND time to allow multiple episodes per day
                # Get time from mp3 file modification time or default to 000000
                try:
                    mtime = datetime.datetime.fromtimestamp(mp3_file.stat().st_mtime)
                    time_str = mtime.strftime("%H%M%S")
                except:
                    time_str = "000000"
                
                episode_guid = f"tesla-shorts-time-ep{episode_num:03d}-{date_str}-{time_str}"
                episode_title = f"Tesla Shorts Time Daily - Episode {episode_num} - {episode_date.strftime('%B %d, %Y')}"
                
                episodes.append({
                    'guid': episode_guid,
                    'title': episode_title,
                    'description': f"Daily Tesla news digest for {episode_date.strftime('%B %d, %Y')}.",
                    'link': f"{base_url}/digests/{mp3_file.name}",
                    'pubDate': datetime.datetime.combine(episode_date, datetime.time(8, 0, 0), tzinfo=datetime.timezone.utc),
                    'enclosure': {
                        'url': f"{base_url}/digests/{mp3_file.name}",
                        'type': 'audio/mpeg',
                        'length': str(mp3_file.stat().st_size)
                    },
                    'itunes_title': episode_title,
                    'itunes_summary': f"Daily Tesla news digest for {episode_date.strftime('%B %d, %Y')}.",
                    'itunes_duration': format_duration(mp3_duration),
                    'itunes_episode': str(episode_num),
                    'itunes_season': '1',
                    'itunes_episode_type': 'full',
                    'itunes_image': f"{base_url}/podcast-image-v2.jpg",
                    'mp3_path': mp3_file,
                    'episode_num': episode_num,
                    'episode_date': episode_date
                })
            except Exception as e:
                logging.warning(f"Could not process {mp3_file.name}: {e}")
                continue
    
    # Sort by episode number (newest first for RSS)
    episodes.sort(key=lambda x: x['episode_num'], reverse=True)
    return episodes


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
    """Update or create RSS feed with new episode, preserving all existing episodes."""
    fg = FeedGenerator()
    fg.load_extension('podcast')
    
    # Parse existing RSS feed to preserve all episodes
    existing_episodes = []
    channel_metadata = {}
    existing_guids = set()
    
    if rss_path.exists():
        try:
            # Parse existing RSS XML
            tree = ET.parse(str(rss_path))
            root = tree.getroot()
            
            # Extract channel metadata
            channel = root.find('channel')
            if channel is not None:
                for elem in channel:
                    if elem.tag in ['title', 'link', 'description', 'language', 'copyright']:
                        channel_metadata[elem.tag] = elem.text
                    elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}author':
                        channel_metadata['itunes_author'] = elem.text
                    elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}summary':
                        channel_metadata['itunes_summary'] = elem.text
                    elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}owner':
                        name_elem = elem.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}name')
                        email_elem = elem.find('{http://www.itunes.com/dtds/podcast-1.0.dtd}email')
                        if name_elem is not None and email_elem is not None:
                            channel_metadata['itunes_owner'] = {'name': name_elem.text, 'email': email_elem.text}
                    elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}image':
                        channel_metadata['itunes_image'] = elem.get('href')
                    elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}category':
                        channel_metadata['itunes_category'] = elem.get('text')
                
                # Extract all existing episodes
                items = channel.findall('item')
                for item in items:
                    episode_data = {}
                    for elem in item:
                        if elem.tag == 'title':
                            episode_data['title'] = elem.text or ''
                        elif elem.tag == 'description':
                            episode_data['description'] = elem.text or ''
                        elif elem.tag == 'link':
                            episode_data['link'] = elem.text or ''
                        elif elem.tag == 'guid':
                            # GUID is typically the text content
                            if elem.text:
                                episode_data['guid'] = elem.text.strip()
                            # Some feeds might use guid as an attribute, but we'll use text primarily
                        elif elem.tag == 'pubDate':
                            episode_data['pubDate'] = elem.text or ''
                        elif elem.tag == 'enclosure':
                            episode_data['enclosure'] = {
                                'url': elem.get('url', ''),
                                'type': elem.get('type', 'audio/mpeg'),
                                'length': elem.get('length', '0')
                            }
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}title':
                            episode_data['itunes_title'] = elem.text or ''
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}summary':
                            episode_data['itunes_summary'] = elem.text or ''
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}duration':
                            episode_data['itunes_duration'] = elem.text or ''
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}episode':
                            episode_data['itunes_episode'] = elem.text or ''
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}season':
                            episode_data['itunes_season'] = elem.text or ''
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}episodeType':
                            episode_data['itunes_episode_type'] = elem.text or ''
                        elif elem.tag == '{http://www.itunes.com/dtds/podcast-1.0.dtd}image':
                            episode_data['itunes_image'] = elem.get('href', '')
                    
                    if episode_data.get('guid'):
                        existing_episodes.append(episode_data)
            
            logging.info(f"Loaded {len(existing_episodes)} existing episodes from RSS feed")
        except Exception as e:
            logging.warning(f"Could not parse existing RSS feed: {e}, creating new one")
            existing_episodes = []
    
    # Also scan file system for MP3 files to ensure we don't miss any episodes
    # This is important if the RSS feed was recreated or is missing episodes
    file_episodes = scan_existing_episodes_from_files(mp3_path.parent, base_url)
    
    # Merge episodes from RSS and file system, preferring RSS data but adding missing ones
    existing_guids = {ep.get('guid') for ep in existing_episodes if ep.get('guid')}
    file_guids = {fep.get('guid') for fep in file_episodes if fep.get('guid')}
    added_from_files = 0
    for file_ep in file_episodes:
        if file_ep.get('guid') not in existing_guids:
            logging.info(f"Found episode in file system but not in RSS: {file_ep.get('guid')} - adding it")
            existing_episodes.append(file_ep)
            existing_guids.add(file_ep.get('guid'))
            added_from_files += 1
    
    logging.info(f"Total episodes to include: {len(existing_episodes)} (from RSS: {len(existing_episodes) - added_from_files}, added from files: {added_from_files})")
    
    # Set channel metadata
    fg.title(channel_metadata.get('title', "Tesla Shorts Time Daily"))
    fg.link(href=channel_metadata.get('link', "https://github.com/patricknovak/Tesla-shorts-time"))
    fg.description(channel_metadata.get('description', "Daily Tesla news digest and podcast hosted by Patrick in Vancouver. Covering the latest Tesla developments, stock updates, and short squeeze celebrations."))
    fg.language(channel_metadata.get('language', 'en-us'))
    fg.copyright(channel_metadata.get('copyright', f"Copyright {datetime.date.today().year}"))
    fg.podcast.itunes_author(channel_metadata.get('itunes_author', "Patrick"))
    fg.podcast.itunes_summary(channel_metadata.get('itunes_summary', "Daily Tesla news digest and podcast covering the latest developments, stock updates, and short squeeze celebrations."))
    
    owner = channel_metadata.get('itunes_owner', {'name': 'Patrick', 'email': 'contact@teslashortstime.com'})
    fg.podcast.itunes_owner(name=owner.get('name', 'Patrick'), email=owner.get('email', 'contact@teslashortstime.com'))
    
    # Set image URL - ensure it's properly formatted for Apple Podcasts Connect
    image_url = channel_metadata.get('itunes_image', f"{base_url}/podcast-image-v2.jpg")
    fg.podcast.itunes_image(image_url)
    
    category = channel_metadata.get('itunes_category', 'Technology')
    fg.podcast.itunes_category(category)
    fg.podcast.itunes_explicit("no")
    
    # Generate GUID for the new episode based on current time to ensure uniqueness
    current_time_str = datetime.datetime.now().strftime("%H%M%S")
    new_episode_guid = f"tesla-shorts-time-ep{episode_num:03d}-{episode_date:%Y%m%d}-{current_time_str}"
    
    # Deduplicate existing episodes by episode number
    # Keep only the most recent entry for each episode number (based on GUID timestamp)
    episodes_by_number = {}
    episodes_without_number = []  # Keep episodes that don't have extractable episode numbers
    
    for ep_data in existing_episodes:
        # Extract episode number from itunes_episode field or from GUID
        ep_num_str = ep_data.get('itunes_episode', '')
        if not ep_num_str:
            # Try to extract from GUID pattern: tesla-shorts-time-epXXX-YYYYMMDD-HHMMSS
            guid = ep_data.get('guid', '')
            match = re.search(r'ep(\d+)', guid)
            if match:
                ep_num_str = match.group(1)
        
        if ep_num_str:
            try:
                ep_num = int(ep_num_str)
                # If we already have this episode number, keep the one with the more recent GUID (later timestamp)
                if ep_num not in episodes_by_number:
                    episodes_by_number[ep_num] = ep_data
                else:
                    # Compare GUIDs to determine which is more recent (later timestamp in GUID)
                    existing_guid = episodes_by_number[ep_num].get('guid', '')
                    current_guid = ep_data.get('guid', '')
                    # Extract timestamp from GUID (last 6 digits after final dash)
                    existing_ts = existing_guid.split('-')[-1] if '-' in existing_guid else '000000'
                    current_ts = current_guid.split('-')[-1] if '-' in current_guid else '000000'
                    if current_ts > existing_ts:
                        episodes_by_number[ep_num] = ep_data
            except ValueError:
                # If we can't parse episode number, keep the episode anyway (shouldn't happen normally)
                episodes_without_number.append(ep_data)
        else:
            # Episode without extractable episode number - keep it (shouldn't happen normally)
            episodes_without_number.append(ep_data)
    
    # Add all existing episodes (now deduplicated), but skip if same episode number as new episode
    # First add episodes with episode numbers
    for ep_data in episodes_by_number.values():
        # Extract episode number to check against new episode
        ep_num_str = ep_data.get('itunes_episode', '')
        if not ep_num_str:
            guid = ep_data.get('guid', '')
            match = re.search(r'ep(\d+)', guid)
            if match:
                ep_num_str = match.group(1)
        
        # Skip if this existing episode has the same episode number as the new one we're about to add
        # (we'll add the new one instead, which should be more up-to-date)
        if ep_num_str and int(ep_num_str) == episode_num:
            logging.info(f"Skipping existing episode {ep_num_str} - will be replaced with new version")
            continue
        
        # Skip if exact same GUID (should typically not happen with time-based GUIDs unless run very fast)
        if ep_data.get('guid') == new_episode_guid:
            continue
        
        # Re-add existing episode
        entry = fg.add_entry()
        entry.id(ep_data.get('guid', ''))
        entry.title(ep_data.get('title', ''))
        entry.description(ep_data.get('description', ''))
        if ep_data.get('link'):
            entry.link(href=ep_data['link'])
        
        # Parse and set pubDate
        if ep_data.get('pubDate'):
            try:
                # Handle both string dates (from RSS) and datetime objects (from file scan)
                if isinstance(ep_data['pubDate'], datetime.datetime):
                    entry.pubDate(ep_data['pubDate'])
                else:
                    from email.utils import parsedate_to_datetime
                    pub_date = parsedate_to_datetime(ep_data['pubDate'])
                    entry.pubDate(pub_date)
            except Exception:
                pass
        
        # Set enclosure
        if ep_data.get('enclosure'):
            enc = ep_data['enclosure']
            entry.enclosure(url=enc.get('url', ''), type=enc.get('type', 'audio/mpeg'), length=enc.get('length', '0'))
        
        # Set iTunes tags
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
        # Set image for each episode (Apple Podcasts Connect requirement)
        # Use episode-specific image if available, otherwise use channel image
        episode_image = ep_data.get('itunes_image', image_url)
        entry.podcast.itunes_image(episode_image)
    
    # Also add episodes without extractable episode numbers (shouldn't happen normally, but be safe)
    for ep_data in episodes_without_number:
        # Skip if exact same GUID
        if ep_data.get('guid') == new_episode_guid:
            continue
        
        # Re-add episode
        entry = fg.add_entry()
        entry.id(ep_data.get('guid', ''))
        entry.title(ep_data.get('title', ''))
        entry.description(ep_data.get('description', ''))
        if ep_data.get('link'):
            entry.link(href=ep_data['link'])
        
        # Parse and set pubDate
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
        
        # Set enclosure
        if ep_data.get('enclosure'):
            enc = ep_data['enclosure']
            entry.enclosure(url=enc.get('url', ''), type=enc.get('type', 'audio/mpeg'), length=enc.get('length', '0'))
        
        # Set iTunes tags
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
        episode_image = ep_data.get('itunes_image', image_url)
        entry.podcast.itunes_image(episode_image)
    
    # Add or update the new episode
    entry = fg.add_entry()
    entry.id(new_episode_guid)
    entry.title(episode_title)
    entry.description(episode_description)
    entry.link(href=f"{base_url}/digests/{mp3_filename}")
    pub_date = datetime.datetime.combine(episode_date, datetime.time(8, 0, 0), tzinfo=datetime.timezone.utc)
    entry.pubDate(pub_date)
    
    # Enclosure
    mp3_url = f"{base_url}/digests/{mp3_filename}"
    mp3_size = mp3_path.stat().st_size if mp3_path.exists() else 0
    entry.enclosure(url=mp3_url, type="audio/mpeg", length=str(mp3_size))
    
    # iTunes tags
    entry.podcast.itunes_title(episode_title)
    entry.podcast.itunes_summary(episode_description)
    entry.podcast.itunes_duration(format_duration(mp3_duration))
    entry.podcast.itunes_episode(str(episode_num))
    entry.podcast.itunes_season("1")
    entry.podcast.itunes_episode_type("full")
    entry.podcast.itunes_explicit("no")
    # Set image for the episode (Apple Podcasts Connect requirement)
    entry.podcast.itunes_image(image_url)
    
    # Update lastBuildDate
    fg.lastBuildDate(datetime.datetime.now(datetime.timezone.utc))
    
    # Write RSS feed
    fg.rss_file(str(rss_path), pretty=True)
    total_episodes = len(fg.entry())
    logging.info(f"RSS feed updated → {rss_path} ({total_episodes} episode(s) total)")

# Since there's only one voice (Patrick), combine entire script into one segment
# Remove speaker labels and sound cues, keep only the actual spoken text
full_text_parts = []
for line in podcast_script.splitlines():
    line = line.strip()
    # Skip sound cues and empty lines
    if line.startswith("[") or not line:
        continue
    # Remove speaker labels but keep the text
    if line.startswith("Patrick:"):
        full_text_parts.append(line[9:].strip())
    elif line.startswith("Dan:"):
        full_text_parts.append(line[4:].strip())
    else:
        full_text_parts.append(line)

# Combine into one continuous text
full_text = " ".join(full_text_parts)

# ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
# CRITICAL: Fix Tesla-world pronunciation for ElevenLabs
full_text = fix_tesla_pronunciation(full_text)
# ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←

# Generate ONE voice file for the entire script
logging.info("Generating single voice segment for entire podcast...")
voice_file = tmp_dir / "patrick_full.mp3"

# Track character count for ElevenLabs
credit_usage["services"]["elevenlabs_api"]["characters"] = len(full_text)
logging.info(f"ElevenLabs TTS: {len(full_text)} characters to convert")

speak(full_text, PATRICK_VOICE_ID, str(voice_file))
audio_files = [str(voice_file)]
logging.info("Generated complete voice track")

# ========================== 4. FINAL MIX – PERFECT LEVELS, NO VOLUME JUMPS ==========================
final_mp3 = digests_dir / f"Tesla_Shorts_Time_Pod_Ep{episode_num:03d}_{datetime.date.today():%Y%m%d}.mp3"

MAIN_MUSIC = project_root / "tesla_shorts_time.mp3"

# Process and normalize voice in one step for simplicity
voice_mix = tmp_dir / "voice_normalized_mix.mp3"
concat_file = None

if len(audio_files) == 1:
    # Single file: process and normalize in one pass
    file_duration = get_audio_duration(Path(audio_files[0]))
    timeout_seconds = max(int(file_duration * 3) + 120, 600)
    
    logging.info(f"Processing and normalizing voice ({file_duration:.1f}s) - this may take a few minutes...")
    subprocess.run([
        "ffmpeg", "-y", "-i", audio_files[0],
        "-af", "highpass=f=80,lowpass=f=15000,loudnorm=I=-18:TP=-1.5:LRA=11:linear=true,acompressor=threshold=-20dB:ratio=4:attack=1:release=100:makeup=2,alimiter=level_in=1:level_out=0.95:limit=0.95",
        "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k",
        str(voice_mix)
    ], check=True, capture_output=True, timeout=timeout_seconds)
else:
    # Multiple files: concatenate first, then process
    concat_file = tmp_dir / "concat_list.txt"
    with open(concat_file, "w") as f:
        for seg in audio_files:
            f.write(f"file '{seg}'\n")
    
    temp_concat = tmp_dir / "temp_concat.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k",
        str(temp_concat)
    ], check=True, capture_output=True)
    
    file_duration = get_audio_duration(temp_concat)
    timeout_seconds = max(int(file_duration * 3) + 120, 600)
    
    logging.info(f"Processing and normalizing voice ({file_duration:.1f}s) - this may take a few minutes...")
    subprocess.run([
        "ffmpeg", "-y", "-i", str(temp_concat),
        "-af", "highpass=f=80,lowpass=f=15000,loudnorm=I=-18:TP=-1.5:LRA=11:linear=true,acompressor=threshold=-20dB:ratio=4:attack=1:release=100:makeup=2,alimiter=level_in=1:level_out=0.95:limit=0.95",
        "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k",
        str(voice_mix)
    ], check=True, capture_output=True, timeout=timeout_seconds)
    
    if temp_concat.exists():
        os.remove(str(temp_concat))

if not MAIN_MUSIC.exists():
    subprocess.run(["ffmpeg", "-y", "-i", str(voice_mix), str(final_mp3)], check=True, capture_output=True)
    logging.info("Podcast ready (voice-only)")
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
    
    # Simplified music creation - create segments with louder intro
    music_intro = tmp_dir / "music_intro.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-t", "5",
        "-af", "volume=0.6",  # Much louder intro music
        "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k",
        str(music_intro)
    ], check=True, capture_output=True)
    
    music_overlap = tmp_dir / "music_overlap.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-i", str(MAIN_MUSIC), "-ss", "5", "-t", "3",
        "-af", "volume=0.5",  # Louder during overlap
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
    
    # Outro music: 30 seconds full volume + 20 seconds fade = 50 seconds total
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
        "[1:a]volume=0.5[a_music];"  # Higher music volume for better presence
        "[a_voice][a_music]amix=inputs=2:duration=longest:dropout_transition=2:weights=2 1[mixed];"
        "[mixed]alimiter=level_in=1:level_out=0.95:limit=0.95[outfinal]",
        "-map", "[outfinal]",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        str(final_mp3)
    ], check=True, capture_output=True)
    
    logging.info("Podcast created successfully")
    
    # Cleanup music temp files
    for tmp_file in [music_intro, music_overlap, music_fadeout, music_fadein, music_tail_full, music_tail_fadeout, music_concat_list, background_track, voice_delayed]:
        if tmp_file.exists():
            os.remove(str(tmp_file))
    if middle_silence_duration > 0.1 and music_silence.exists():
        os.remove(str(music_silence))
    
    logging.info("BROADCAST-QUALITY PODCAST CREATED – PROFESSIONAL MUSIC TRANSITIONS APPLIED")

# ========================== 5. UPDATE RSS FEED ==========================
if ENABLE_PODCAST and not TEST_MODE and final_mp3 and final_mp3.exists():
    try:
        # Get audio duration
        audio_duration = get_audio_duration(final_mp3)
        
        # Create episode title and description
        episode_title = f"Tesla Shorts Time Daily - Episode {episode_num} - {today_str}"
        
        # Extract a summary from the X thread (first 500 chars or first paragraph)
        episode_description = f"Daily Tesla news digest for {today_str}. TSLA price: ${price:.2f} {change_str}. "
        # Get first meaningful paragraph from x_thread
        lines = x_thread.split('\n')
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#') and not line.startswith('**') and len(line) > 50:
                episode_description += line[:400] + "..."
                break
        
        # RSS feed path (save in project root for easy access)
        rss_path = project_root / "podcast.rss"
        
        # MP3 filename relative to digests/ (where files are saved)
        mp3_filename = final_mp3.name
        
        # Generate thumbnail
        thumbnail_filename = f"Tesla_Shorts_Time_Thumbnail_Ep{episode_num:03d}_{datetime.date.today():%Y%m%d}.png"
        thumbnail_path = digests_dir / thumbnail_filename
        base_image_path = project_root / "podcast-image-v2.jpg"
        generate_episode_thumbnail(base_image_path, episode_num, today_str, thumbnail_path)
        
        # Define base_url for RSS feed
        base_url = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
        
        # Update RSS feed
        update_rss_feed(
            rss_path=rss_path,
            episode_num=episode_num,
            episode_title=episode_title,
            episode_description=episode_description,
            episode_date=datetime.date.today(),
            mp3_filename=mp3_filename,
            mp3_duration=audio_duration,
            mp3_path=final_mp3,
            base_url=base_url
        )
        logging.info(f"RSS feed updated with Episode {episode_num}")
    except Exception as e:
        logging.error(f"Failed to update RSS feed: {e}", exc_info=True)
        logging.warning("RSS feed update failed, but continuing...")

# Post everything to X in ONE SINGLE POST
if ENABLE_X_POSTING:
    try:
        # Use the formatted version that's already in memory (from Step 4)
        thread_text = x_thread.strip()
        
        # Track X API post call
        credit_usage["services"]["x_api"]["post_calls"] += 1
        
        # Post as one single tweet (X supports long posts up to 25,000 characters)
        tweet = x_client.create_tweet(text=thread_text)
        tweet_id = tweet.data['id']
        thread_url = f"https://x.com/planetterrian/status/{tweet_id}"
        logging.info(f"DIGEST POSTED → {thread_url}")
    except Exception as e:
        logging.error(f"X post failed: {e}")

# Cleanup temporary files
try:
    for file_path in audio_files:
        if os.path.exists(file_path):
            os.remove(file_path)
    cleanup_files = [voice_mix]
    if concat_file and concat_file.exists():
        cleanup_files.append(concat_file)
    for tmp_file in cleanup_files:
        if tmp_file and Path(tmp_file).exists():
            os.remove(str(tmp_file))
    logging.info("Temporary files cleaned up")
except Exception as e:
    logging.warning(f"Cleanup warning: {e}")

# ========================== CLEANUP TEMPORARY FILES ==========================
logging.info("Cleaning up temporary files...")
try:
    # Clean up all temp files in tmp_dir
    if tmp_dir.exists():
        for tmp_file in tmp_dir.glob("*"):
            try:
                if tmp_file.is_file():
                    tmp_file.unlink()
                    logging.debug(f"Removed temp file: {tmp_file}")
            except Exception as e:
                logging.warning(f"Could not remove temp file {tmp_file}: {e}")
    logging.info("Temporary files cleaned up")
except Exception as e:
    logging.warning(f"Error during temp file cleanup: {e}")

# Save credit usage tracking
save_credit_usage(credit_usage, digests_dir)

print("\n" + "="*80)
print("TESLA SHORTS TIME — FULLY AUTOMATED RUN COMPLETE")
print(f"X Thread → {x_path}")
print(f"Podcast → {final_mp3}")
print("="*80)

# Add at the end of the file, before the final print statements
