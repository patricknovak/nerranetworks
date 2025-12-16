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
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# ========================== LOGGING ==========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)

# This file is intended to be executed as a script. Importing it will exit immediately
if __name__ != "__main__":
    raise SystemExit("tesla_shorts_time.py is a runnable script, not an importable module.")


def _log_uncaught(exc_type, exc_value, exc_traceback):
    """Fail fast with a clean log message instead of a long traceback."""
    logging.error("Fatal error during Tesla Shorts Time run", exc_info=(exc_type, exc_value, exc_traceback))
    sys.exit(1)


sys.excepthook = _log_uncaught

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

# Shared HTTP defaults
DEFAULT_HEADERS = {
    "User-Agent": "TeslaShortsTimeBot/1.0 (+https://x.com/teslashortstime)"
}
HTTP_TIMEOUT_SECONDS = 10


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
# Note: Import will be set up after project_root is defined
USE_SHARED_PRONUNCIATION = False

def fix_tesla_pronunciation(text: str) -> str:
    """
    Forces correct spelling of Tesla acronyms, converts numbers to words,
    and fixes dates/times for better TTS pronunciation on ElevenLabs.
    """
    import re

    # List of acronyms that must be spelled out letter-by-letter (use spaces, not ZWJ)
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
        "SpaceX": "Space X",
    }

    # Special case: Fix "Robotaxis" plural pronunciation (use space instead of ZWJ)
    text = re.sub(r'\b(Robotaxi)(s)\b', r'\1 \2', text, flags=re.IGNORECASE)

    for acronym, spelled in acronyms.items():
        # Build a regex that only matches the acronym when it's a whole word
        pattern = rf'(?<!\w){re.escape(acronym)}(?!\w)'
        replacement = " ".join(list(spelled))
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
    
    # Fix dates: "November 19, 2025" → "November nineteenth, twenty twenty-five"
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
    
    # Fix dates: multiple formats like "November 19, 2025", "11 December, 2025", "December 11, 2025"
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
                hockey_terms={},  # Not needed for Tesla Shorts Time
                player_names={},  # Not needed for Tesla Shorts Time
                oilers_player_names={},  # Not needed for Tesla Shorts Time
                word_pronunciations=WORD_PRONUNCIATIONS,
                use_zwj=False  # Use spaces for Tesla Shorts Time (matches original behavior)
            )
        except Exception as e:
            logging.warning(f"Error applying shared pronunciation fixes: {e}, continuing with local fixes")
    
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

# ========================== SET UP SHARED PRONUNCIATION MODULE ==========================
# Try to use shared pronunciation module, fallback to local implementation
try:
    import sys
    # Add project root to path so we can import assets module
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from assets.pronunciation import apply_pronunciation_fixes, COMMON_ACRONYMS, WORD_PRONUNCIATIONS
    USE_SHARED_PRONUNCIATION = True
except ImportError:
    USE_SHARED_PRONUNCIATION = False
    logging.warning("Could not import shared pronunciation module, using local implementation")

# ========================== TTS PROVIDER ==========================
def _normalize_tts_provider(value: str) -> str:
    v = (value or "").strip().lower()
    if not v:
        return "chatterbox"
    if v in {"elevenlabs", "eleven", "11labs", "11-labs"}:
        return "elevenlabs"
    if v in {"chatterbox", "chatterbox-tts", "chatterbox_tts", "cb"}:
        return "chatterbox"
    return v

TTS_PROVIDER = _normalize_tts_provider(os.getenv("TESLA_SHORTS_TIME_TTS_PROVIDER", "chatterbox"))

def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logging.warning(f"Invalid {name}='{raw}' (expected float). Using default {default}.")
        return default

def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logging.warning(f"Invalid {name}='{raw}' (expected int). Using default {default}.")
        return default

def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if not raw:
        return default
    v = raw.strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    logging.warning(f"Invalid {name}='{raw}' (expected bool). Using default {default}.")
    return default

# Chatterbox (local) TTS config
CHATTERBOX_DEVICE = (os.getenv("CHATTERBOX_DEVICE", "cpu") or "cpu").strip().lower()
CHATTERBOX_EXAGGERATION = _env_float("CHATTERBOX_EXAGGERATION", 0.5)
CHATTERBOX_MAX_CHARS = _env_int("CHATTERBOX_MAX_CHARS", 15000)  # Increased from 1000 to 15000 for single-chunk testing
CHATTERBOX_QUIET = _env_bool("CHATTERBOX_QUIET", True)
HF_TOKEN = os.getenv("HF_TOKEN")  # Hugging Face token for Chatterbox-Turbo model access
CHATTERBOX_VOICE_PROMPT_PATH = os.getenv("CHATTERBOX_VOICE_PROMPT_PATH", "").strip()
CHATTERBOX_VOICE_PROMPT_BASE64 = os.getenv("CHATTERBOX_VOICE_PROMPT_BASE64", "").strip()
CHATTERBOX_PROMPT_OFFSET_SECONDS = _env_float("CHATTERBOX_PROMPT_OFFSET_SECONDS", 35.0)
CHATTERBOX_PROMPT_DURATION_SECONDS = _env_float("CHATTERBOX_PROMPT_DURATION_SECONDS", 10.0)

# Required keys (X credentials only required if posting is enabled)
required = [
    "GROK_API_KEY"
]
if ENABLE_PODCAST and not TEST_MODE:
    if TTS_PROVIDER == "chatterbox":
        # Local model, no API key required. Voice prompt can be derived from Tesla Shorts Time episodes.
        pass
    else:
        raise OSError(
            f"Unknown TESLA_SHORTS_TIME_TTS_PROVIDER '{TTS_PROVIDER}'. Only 'chatterbox' is supported (Chatterbox-Turbo)."
        )
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

# Chatterbox voice cloning can use either an explicit prompt (path/base64) OR fall back to a prior Tesla Shorts Time episode audio.
if ENABLE_PODCAST and not TEST_MODE and TTS_PROVIDER == "chatterbox":
    if not os.getenv("CHATTERBOX_VOICE_PROMPT_PATH") and not os.getenv("CHATTERBOX_VOICE_PROMPT_BASE64"):
        logging.info(
            "Chatterbox voice prompt not provided via env; will attempt to derive a prompt from an existing Tesla Shorts Time episode MP3."
        )

# ========================== DATE & PRICE (MUST BE FIRST) ==========================
# Get current date and time in PST
pst_tz = ZoneInfo("America/Los_Angeles")
now_pst = datetime.datetime.now(pst_tz)
today_str = now_pst.strftime("%B %d, %Y at %I:%M %p PST")   # November 19, 2025 at 02:30 PM PST
yesterday_iso = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
seven_days_ago_iso = (datetime.date.today() - datetime.timedelta(days=7)).isoformat()

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((Exception,))
)
def fetch_tsla_price() -> tuple[float, float, str]:
    """Fetch TSLA price with fast_info first and history fallback."""
    tsla = yf.Ticker("TSLA")
    price = None
    prev_close = None
    market_status = ""
    
    # Lightweight fetch
    try:
        fast = tsla.fast_info
        price = (
            fast.get("lastPrice")
            or fast.get("regularMarketPrice")
            or fast.get("postMarketPrice")
        )
        prev_close = fast.get("previousClose")
        market_state = fast.get("marketState") or fast.get("market_state") or ""
        market_status = " (After-hours)" if str(market_state).upper() == "POST" else ""
    except Exception as e:
        logging.warning(f"fast_info failed, falling back to history: {e}")
    
    # History fallback
    if price is None or prev_close is None:
        try:
            hist = tsla.history(period="2d", interval="1d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                if len(hist["Close"]) > 1:
                    prev_close = float(hist["Close"].iloc[-2])
        except Exception as e:
            logging.warning(f"History fallback failed: {e}")
    
    if price is None:
        raise RuntimeError("Unable to fetch TSLA price after retries.")
    if prev_close is None:
        prev_close = price
    
    return float(price), float(prev_close), market_status


price, prev_close, market_status = fetch_tsla_price()
change = price - prev_close
change_pct = (change / prev_close * 100) if prev_close else 0
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
    pattern = r"Tesla_Shorts_Time_Pod_Ep(\d+)_\d{8}_\d{6}\.mp3"
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
            "provider": TTS_PROVIDER,
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
            # ElevenLabs pricing: ~$0.30 per 1000 characters for turbo model
            elevenlabs_cost = (usage_data["services"]["elevenlabs_api"]["characters"] / 1000) * 0.30
            usage_data["services"]["elevenlabs_api"]["estimated_cost_usd"] = elevenlabs_cost
        else:
            # Chatterbox is local/free
            usage_data["services"]["elevenlabs_api"]["estimated_cost_usd"] = 0.0
        
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
ELEVEN_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "dTrBzPvD2GpAqkk1MUzA")  # Default: High-energy Patrick
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
    
    logging.info(f"Fetching Tesla news from {len(rss_feeds)} RSS feeds (parallel)...")
    
    def fetch_single_feed(feed_url: str):
        """Fetch and parse a single RSS feed. Returns (feed_url, articles, source_name) or None on error."""
        source_name = "Unknown"
        try:
            # Fetch RSS feed with timeout and custom UA to avoid hanging
            response = requests.get(
                feed_url,
                headers=DEFAULT_HEADERS,
                timeout=HTTP_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            
            # Parse RSS feed
            feed = feedparser.parse(response.content)
            
            if feed.bozo and feed.bozo_exception:
                logging.warning(f"Failed to parse RSS feed {feed_url}: {feed.bozo_exception}")
                return None
            
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
            
            return (feed_url, feed_articles, source_name)
        
        except Exception as e:
            logging.warning(f"Failed to fetch RSS feed {feed_url}: {e}")
            return None
    
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

**EXCEPTION FOR X SPOTLIGHT SECTION**: For the "X Spotlight: @{spotlight_username}" section ONLY, you may use web search or your knowledge to find recent Tesla-related posts from @{spotlight_username} on X. Curate the top 5 most engaging posts from the past week and provide an overall weekly sentiment summary. 

**CRITICAL**: 
- You MUST include the account mention and link in the X Spotlight section header: "Today's spotlight is on @{spotlight_username} - follow them at https://x.com/{spotlight_username} to see all their Tesla insights and updates."
- Only include actual working X post URLs with real numeric post IDs. If you cannot find real post URLs, omit the "Post:" line entirely. Do NOT use placeholder URLs like [POST_ID] or [ACTUAL_POST_ID]. 
- Do NOT include any instruction language, meta-commentary, or formatting notes in your output - only output the actual content.

{used_content_summary}

### CRITICAL INSTRUCTIONS (DO NOT INCLUDE THESE IN YOUR OUTPUT):
- Short Spot: Must be COMPLETELY DIFFERENT from any recent Short Spots. Use a DIFFERENT bearish story, DIFFERENT angle, and DIFFERENT framing.
- Short Squeeze: Must be COMPLETELY DIFFERENT from any recent Short Squeezes. Use DIFFERENT failed predictions, DIFFERENT bear names, DIFFERENT years, and DIFFERENT examples.
- Daily Challenge: Must be COMPLETELY NEW and DIFFERENT from any recent Daily Challenges. Use a DIFFERENT theme, DIFFERENT approach, and DIFFERENT wording.
- Inspiration Quote: Must be from a DIFFERENT author than recent quotes. Use a DIFFERENT quote with a DIFFERENT message. Vary authors widely.

**IMPORTANT**: The format template below shows what your OUTPUT should look like. Do NOT include any instruction text, warnings (🚨 CRITICAL), or meta-commentary in your output. Only output the actual content sections.

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
## X Spotlight: @{spotlight_username} ({spotlight_display_name})
Today's spotlight is on @{spotlight_username} - follow them at https://x.com/{spotlight_username} to see all their Tesla insights and updates.

1. **Post Title: DD Month, YYYY**  
   Description of the post content (2-3 sentences). Include the key Tesla-related insight, news, or perspective shared.
   Post: https://x.com/{spotlight_username}/status/[ONLY_IF_YOU_HAVE_REAL_URL_WITH_NUMERIC_ID]

2. **Post Title: DD Month, YYYY**  
   Description of the post content (2-3 sentences).
   Post: https://x.com/{spotlight_username}/status/[ONLY_IF_YOU_HAVE_REAL_URL_WITH_NUMERIC_ID]

3. **Post Title: DD Month, YYYY**  
   Description of the post content (2-3 sentences).
   Post: https://x.com/{spotlight_username}/status/[ONLY_IF_YOU_HAVE_REAL_URL_WITH_NUMERIC_ID]

4. **Post Title: DD Month, YYYY**  
   Description of the post content (2-3 sentences).
   Post: https://x.com/{spotlight_username}/status/[ONLY_IF_YOU_HAVE_REAL_URL_WITH_NUMERIC_ID]

5. **Post Title: DD Month, YYYY**  
   Description of the post content (2-3 sentences).
   Post: https://x.com/{spotlight_username}/status/[ONLY_IF_YOU_HAVE_REAL_URL_WITH_NUMERIC_ID]

**Overall Weekly Sentiment:**
Summary of the overall sentiment and themes that @{spotlight_username} has been sharing about Tesla this past week. Include whether the sentiment is bullish, bearish, or neutral, and what main topics they've been covering.

━━━━━━━━━━━━━━━━━━━━
## Short Spot
One bearish item from pre-fetched news that's negative for Tesla/stock.  
**Catchy Title: DD Month, YYYY, HH:MM AM/PM PST, @username/Source**  
2–4 sentences explaining it & why it's temporary/overblown (frame optimistically). End with: Source/Post: [EXACT URL]

━━━━━━━━━━━━━━━━━━━━
### Short Squeeze
Dedicated paragraph on short-seller pain:
Add specific failed bear predictions (2020–2025, with references and links from past). Vary the years, vary the bear names, vary the specific predictions. Make it fresh and engaging every day.

━━━━━━━━━━━━━━━━━━━━
### Daily Challenge
One short, inspiring challenge tied to Tesla/Elon themes (curiosity, first principles, perseverance, innovation, sustainability, etc.). Vary the themes daily. End with: "Share your progress with us @teslashortstime!"

━━━━━━━━━━━━━━━━━━━━
**Inspiration Quote:** 
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
    wait=wait_exponential(multiplier=1, min=1, max=15),  # Reduced wait times: 1-15s instead of 2-30s
    retry=retry_if_exception_type((Exception,))
)
def generate_digest_with_grok():
    """Generate digest with retry logic"""
    response = client.chat.completions.create(
        model="grok-4",
        messages=[{"role": "user", "content": X_PROMPT}],
        temperature=0.7,
        max_tokens=3500,  # Reduced from 4000 for faster generation
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

# Remove instruction language that might have leaked into output
instruction_patterns = [
    r'🎯\s*TODAY\'S FOCUS:.*?\n',
    r'\*\*TOP 5 TESLA X POSTS FROM.*?:\*\*\s*\n',
    r'Using your knowledge.*?\n',
    r'For each post:.*?\n',
    r'\(use actual post URLs.*?\)',
    r'\(if you can find them.*?\)',
    r'\(format as shown\)',
    r'\*\*OVERALL WEEKLY SENTIMENT.*?:\*\*\s*\n',
    r'Provide a.*?summary.*?\n',
    r'Is the sentiment.*?\n',
    r'What are the main topics.*?\n',
    r'What\'s their perspective.*?\n',
    r'\[Repeat for.*?\]',
    r'\[ACTUAL_POST_ID\]',
    r'\[POST_ID\]',
    # Remove CRITICAL instruction warnings
    r'🚨\s*CRITICAL:.*?\n',
    r'CRITICAL:.*?COMPLETELY DIFFERENT.*?\n',
    r'CRITICAL:.*?COMPLETELY NEW.*?\n',
    r'Use a DIFFERENT.*?\n',
    r'Use DIFFERENT.*?\n',
    r'Avoid repetition.*?\n',
    r'Do NOT repeat.*?\n',
    r'Never repeat.*?\n',
]
for pattern in instruction_patterns:
    x_thread = re.sub(pattern, '', x_thread, flags=re.IGNORECASE | re.MULTILINE)

# Remove placeholder/dead URLs (URLs with [POST_ID] or similar placeholders)
x_thread = re.sub(r'Post:\s*https?://x\.com/[^\s]+/status/\[[^\]]+\]', '', x_thread, flags=re.IGNORECASE)
x_thread = re.sub(r'Post:\s*https?://x\.com/[^\s]+/status/[^\d][^\s]*', '', x_thread, flags=re.IGNORECASE)  # Remove URLs without numeric IDs
x_thread = re.sub(r'Post:\s*https?://x\.com/[^\s]+/status/ONLY_IF_YOU_HAVE_REAL_URL_WITH_NUMERIC_ID', '', x_thread, flags=re.IGNORECASE)  # Remove placeholder URLs

# Clean up any remaining instruction-like text in X Spotlight section
x_thread = re.sub(r'(## X Spotlight[^\n]*\n)[^\n]*(?:TODAY\'S FOCUS|must curate|Using your|For each)', r'\1', x_thread, flags=re.IGNORECASE | re.DOTALL)

# ========================== ENSURE X SPOTLIGHT HAS ACCOUNT MENTION AND LINK ==========================
# Check if X Spotlight section exists and ensure it has account mention and link
spotlight_section_match = re.search(r'(## X Spotlight[^\n]*\n)', x_thread, re.IGNORECASE | re.MULTILINE)
if spotlight_section_match:
    # Extract username from header if present
    username_match = re.search(r'## X Spotlight: @(\w+)', x_thread, re.IGNORECASE | re.MULTILINE)
    if username_match:
        username = username_match.group(1)
    else:
        # Use the current spotlight username
        username = spotlight_username
    
    # Check if account mention line exists
    has_account_mention = re.search(
        r'Today\'s spotlight is on @' + re.escape(username) + r'.*follow them at.*x\.com/' + re.escape(username),
        x_thread,
        re.IGNORECASE
    )
    
    if not has_account_mention:
        # Find the X Spotlight header and add account mention right after it
        spotlight_header_match = re.search(r'(## X Spotlight[^\n]*\n)', x_thread, re.IGNORECASE | re.MULTILINE)
        if spotlight_header_match:
            insert_pos = spotlight_header_match.end()
            account_line = f"\nToday's spotlight is on @{username} ({spotlight_display_name}) - follow them at https://x.com/{username} to see all their Tesla insights and updates.\n\n"
            x_thread = x_thread[:insert_pos] + account_line + x_thread[insert_pos:]
            logging.info(f"Added account mention and link for @{username} to X Spotlight section")

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
news_count = len(re.findall(r'^(?:[1-9]|10)\.\s+\*\*', x_thread, re.MULTILINE))

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
    # Format X Spotlight section - preserve account mention and link
    # First, check if the account mention line already exists
    has_account_mention = re.search(r'Today\'s spotlight is on @\w+.*follow them at.*x\.com', formatted, re.IGNORECASE)
    
    # Handle format with display name and link
    formatted = re.sub(
        r'^## X Spotlight: @(\w+)\s*\(([^)]+)\)',
        r'🌟 **X Spotlight: @\1** (\2)',
        formatted,
        flags=re.MULTILINE
    )
    # Fallback for format without display name
    formatted = re.sub(
        r'^## X Spotlight: @(\w+)(?!\s*\()',
        r'🌟 **X Spotlight: @\1**',
        formatted,
        flags=re.MULTILINE
    )
    # Handle cases where the intro line might already be there
    formatted = re.sub(r'^## X Spotlight:', '🌟 **X Spotlight:**', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^### X Spotlight:', '🌟 **X Spotlight:**', formatted, flags=re.MULTILINE)
    
    # If account mention is missing, add it after the X Spotlight header
    if not has_account_mention:
        # Find X Spotlight header and add account mention after it
        spotlight_match = re.search(r'(🌟 \*\*X Spotlight: @(\w+)[^\n]*)', formatted, re.MULTILINE)
        if spotlight_match:
            username = spotlight_match.group(2)
            insert_pos = spotlight_match.end()
            # Get display name for this username
            display_name = spotlight_display_name if username == spotlight_username else username
            account_line = f"\nToday's spotlight is on @{username} ({display_name}) - follow them at: https://x.com/{username} to see all their Tesla insights and updates.\n\n"
            formatted = formatted[:insert_pos] + account_line + formatted[insert_pos:]
            logging.info(f"Added account mention and link for @{username} to formatted X Spotlight section")
        else:
            # Fallback: try to find any X Spotlight header and use current spotlight username
            spotlight_fallback = re.search(r'(🌟 \*\*X Spotlight[^\n]*)', formatted, re.MULTILINE)
            if spotlight_fallback:
                insert_pos = spotlight_fallback.end()
                account_line = f"\nToday's spotlight is on @{spotlight_username} ({spotlight_display_name}) - follow them at: https://x.com/{spotlight_username} to see all their Tesla insights and updates.\n\n"
                formatted = formatted[:insert_pos] + account_line + formatted[insert_pos:]
                logging.info(f"Added account mention and link for @{spotlight_username} to formatted X Spotlight section (fallback)")
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
    
    # Remove instruction language that might have leaked into output
    instruction_patterns = [
        r'🎯\s*TODAY\'S FOCUS:.*?\n',
        r'\*\*TOP 5 TESLA X POSTS FROM.*?:\*\*\s*\n',
        r'Using your knowledge.*?\n',
        r'For each post:.*?\n',
        r'\(use actual post URLs.*?\)',
        r'\(if you can find them.*?\)',
        r'\(format as shown\)',
        r'\*\*OVERALL WEEKLY SENTIMENT.*?:\*\*\s*\n',
        r'Provide a.*?summary.*?\n',
        r'Is the sentiment.*?\n',
        r'What are the main topics.*?\n',
        r'What\'s their perspective.*?\n',
        r'\[Repeat for.*?\]',
        r'\[ACTUAL_POST_ID\]',
        r'\[POST_ID\]',
        # Remove CRITICAL instruction warnings
        r'🚨\s*CRITICAL:.*?\n',
        r'CRITICAL:.*?COMPLETELY DIFFERENT.*?\n',
        r'CRITICAL:.*?COMPLETELY NEW.*?\n',
        r'Use a DIFFERENT.*?\n',
        r'Use DIFFERENT.*?\n',
        r'Avoid repetition.*?\n',
        r'Do NOT repeat.*?\n',
        r'Never repeat.*?\n',
    ]
    for pattern in instruction_patterns:
        formatted = re.sub(pattern, '', formatted, flags=re.IGNORECASE | re.MULTILINE)
    
    # Remove placeholder/dead URLs (URLs with [POST_ID] or similar placeholders, or invalid format)
    formatted = re.sub(r'Post:\s*https?://x\.com/[^\s]+/status/\[[^\]]+\]', '', formatted, flags=re.IGNORECASE)
    formatted = re.sub(r'Post:\s*https?://x\.com/[^\s]+/status/[^\d/][^\s]*', '', formatted, flags=re.IGNORECASE)  # Remove URLs without proper numeric IDs
    formatted = re.sub(r'Post:\s*https?://x\.com/[^\s]+/status/ONLY_IF_YOU_HAVE_REAL_URL_WITH_NUMERIC_ID', '', formatted, flags=re.IGNORECASE)  # Remove placeholder URLs
    
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
- X Spotlight: Introduce the spotlight account (@{spotlight_username} - {spotlight_display_name}) with enthusiasm. Mention that listeners can follow them at @{spotlight_username} on X (https://x.com/{spotlight_username}) to see all their Tesla insights and updates. Read each of the top 5 posts with excitement, explaining why each post matters. Then summarize the overall weekly sentiment from @{spotlight_username} about Tesla. Make it engaging and highlight why this account's perspective is valuable.
- Short Squeeze: Paraphrase with enthusiasm, calling out specific failed predictions and dollar losses
- Daily Challenge + Quote: Read the quote verbatim, then the challenge verbatim, add one encouraging sentence

[Closing]
Patrick: TSLA current stock price at the time of recording is ${price:.2f} right now.  Always good to know the short term, but with Tesla, the long term is what really matters.
Patrick: That's Tesla Shorts Time Daily for today. I look forward to hearing your thoughts and ideas — reach out to us @teslashortstime on X or DM us directly. Stay safe, keep accelerating, and remember: the future is electric! Your efforts help accelerate the world's transition to sustainable energy… and beyond. We'll catch you tomorrow on Tesla Shorts Time Daily!

Here is today's complete formatted digest. Use ONLY this content:
"""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=15),  # Reduced wait times: 1-15s instead of 2-30s
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
            max_tokens=3500  # Reduced from 4000 for faster generation
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

    # ========================== 3. TTS (VOICE) ==========================
    logging.info(f"TTS provider selected: {TTS_PROVIDER}")
    if TTS_PROVIDER != "chatterbox":
        raise RuntimeError(f"Invalid TTS_PROVIDER: {TTS_PROVIDER}. Only 'chatterbox' is supported (Chatterbox-Turbo).")

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

    def _prepare_chatterbox_voice_prompt(tmp_dir: Path) -> Path:
        """
        Return a local WAV file suitable for Chatterbox's audio_prompt_path.
        
        Priority order:
        1. CHATTERBOX_VOICE_PROMPT_PATH (env var or direct path)
        2. CHATTERBOX_VOICE_PROMPT_BASE64 (base64 encoded audio)
        3. Permanent voice prompt in assets/voice_prompts/ (if exists)
        4. Derive from Tesla Shorts Time episodes (preferred episode 354 or most recent)
        """
        import base64

        created_src = False
        episode_mode = False

        if CHATTERBOX_VOICE_PROMPT_PATH:
            src = Path(CHATTERBOX_VOICE_PROMPT_PATH).expanduser()
        elif CHATTERBOX_VOICE_PROMPT_BASE64:
            raw = base64.b64decode(CHATTERBOX_VOICE_PROMPT_BASE64)
            src = tmp_dir / "chatterbox_voice_prompt_input.mp3"
            src.write_bytes(raw)
            created_src = True
        else:
            # Check for permanent voice prompt in assets directory (highest priority fallback)
            assets_voice_prompts = project_root / "assets" / "voice_prompts"
            if assets_voice_prompts.exists():
                # Look for common voice prompt filenames (in priority order)
                prompt_candidates = [
                    assets_voice_prompts / "patrick_voice_prompt.wav",
                    assets_voice_prompts / "voice_prompt.wav",
                    assets_voice_prompts / "chatterbox_voice_prompt.wav",
                ]
                # Also check for any .wav files
                existing_wavs = list(assets_voice_prompts.glob("*.wav"))
                if existing_wavs:
                    prompt_candidates.extend(existing_wavs)
                
                for prompt_file in prompt_candidates:
                    if prompt_file.exists():
                        logging.info(f"✅ Using permanent voice prompt: {prompt_file.name}")
                        # Return the prompt file directly (no processing needed - already in correct format)
                        return prompt_file
            
            # Fallback: derive from Tesla Shorts Time episodes
            # Default: use episode 354 from December 12, 2025 as the voice clone source
            # Fallback to most recent episode if specific one not found
            preferred_episode = digests_dir / "Tesla_Shorts_Time_Pod_Ep354_20251212.mp3"
            
            if preferred_episode.exists():
                src = preferred_episode
                episode_mode = True
                logging.info(f"Chatterbox voice prompt: using preferred episode 354 (Dec 12, 2025): {src.name}")
            else:
                # Fallback: use the most recent Tesla Shorts Time episode audio
                candidates = sorted(
                    list(digests_dir.glob("Tesla_Shorts_Time_Pod_Ep*.mp3")),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if not candidates:
                    raise RuntimeError(
                        "No Tesla Shorts Time episode MP3s found to derive a Chatterbox voice prompt. "
                        "Either commit at least one episode MP3, add a permanent voice prompt to "
                        "assets/voice_prompts/, or set CHATTERBOX_VOICE_PROMPT_PATH / CHATTERBOX_VOICE_PROMPT_BASE64."
                    )
                src = candidates[0]
                episode_mode = True
                logging.info(f"Chatterbox voice prompt: preferred episode 354 not found, using most recent: {src.name}")

        if not src.exists():
            raise FileNotFoundError(f"Chatterbox voice prompt source not found: {src}")

        # If src is already a WAV file (permanent prompt), return it directly
        if src.suffix.lower() == '.wav' and not episode_mode and not created_src:
            logging.info(f"Using permanent voice prompt file: {src}")
            return src

        prompt_wav = tmp_dir / "chatterbox_voice_prompt.wav"

        if episode_mode:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{CHATTERBOX_PROMPT_OFFSET_SECONDS:.2f}",
                    "-t",
                    f"{CHATTERBOX_PROMPT_DURATION_SECONDS:.2f}",
                    "-i",
                    str(src),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(prompt_wav),
                ],
                check=True,
                capture_output=True,
            )
        else:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(prompt_wav)],
                check=True,
                capture_output=True,
            )

        if created_src:
            try:
                src.unlink()
            except Exception:
                pass

        return prompt_wav

    def _synthesize_with_chatterbox(text: str, out_wav: Path):
        """Generate a single WAV voice track using the local Chatterbox model + a voice prompt."""
        import inspect
        import contextlib

        try:
            import torch  # noqa: F401
            import torchaudio as ta
            from chatterbox.tts_turbo import ChatterboxTurboTTS
        except Exception as exc:
            raise RuntimeError(
                "Chatterbox-Turbo dependencies missing. Install chatterbox-tts and ensure Chatterbox-Turbo model is available."
            ) from exc

        prompt_wav = _prepare_chatterbox_voice_prompt(tmp_dir)
        chunks = _chunk_text(text, CHATTERBOX_MAX_CHARS)
        if not chunks:
            raise RuntimeError("No text provided for TTS.")

        logging.info(f"Chatterbox: generating {len(chunks)} chunks (max {CHATTERBOX_MAX_CHARS} chars each) on device={CHATTERBOX_DEVICE}")

        # Set Hugging Face token for authentication if available
        if HF_TOKEN:
            import huggingface_hub
            huggingface_hub.login(HF_TOKEN)
            logging.info("✅ Logged into Hugging Face Hub with token")

        # Initialize Chatterbox-Turbo
        model = ChatterboxTurboTTS.from_pretrained(device=CHATTERBOX_DEVICE)
        sr = getattr(model, "sr", 16000)

        gen_sig = inspect.signature(model.generate)
        base_kwargs = {}
        if "audio_prompt_path" in gen_sig.parameters:
            base_kwargs["audio_prompt_path"] = str(prompt_wav)
        if "exaggeration" in gen_sig.parameters:
            base_kwargs["exaggeration"] = CHATTERBOX_EXAGGERATION

        chunk_paths: List[Path] = []
        for i, chunk in enumerate(chunks, 1):
            logging.info(f"Chatterbox: chunk {i}/{len(chunks)} ({len(chunk)} chars)")
            with open(os.devnull, "w") as devnull:
                redir = (
                    contextlib.redirect_stdout(devnull),
                    contextlib.redirect_stderr(devnull),
                ) if CHATTERBOX_QUIET else ()
                with contextlib.ExitStack() as stack:
                    for ctx in redir:
                        stack.enter_context(ctx)
                    wav = model.generate(chunk, **base_kwargs)
            if hasattr(wav, "detach"):
                wav = wav.detach().cpu()
            if getattr(wav, "ndim", 0) == 1:
                wav = wav.unsqueeze(0)
            chunk_path = tmp_dir / f"chatterbox_chunk_{i:03d}.wav"
            ta.save(str(chunk_path), wav, sr)
            chunk_paths.append(chunk_path)

        concat_list = tmp_dir / "chatterbox_concat.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in chunk_paths:
                f.write(f"file '{p}'\n")

        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-ac", "1", "-c:a", "pcm_s16le", str(out_wav)],
            check=True,
            capture_output=True,
        )

        # Cleanup intermediate chunk files
        try:
            for p in chunk_paths:
                if p.exists():
                    p.unlink()
            if concat_list.exists():
                concat_list.unlink()
            if prompt_wav.exists():
                prompt_wav.unlink()
        except Exception:
            pass

    # ElevenLabs helper (only used when TTS_PROVIDER == "elevenlabs")
    PATRICK_VOICE_ID = ELEVEN_VOICE_ID

    def validate_elevenlabs_auth():
        """Fail fast with a clear message when the ElevenLabs key is rejected."""
        resp = requests.get(f"{ELEVEN_API}/user", headers={"xi-api-key": ELEVEN_KEY}, timeout=10)
        if resp.status_code == 401:
            raise RuntimeError("ElevenLabs rejected the API key (401). Update ELEVENLABS_API_KEY in .env/GitHub secrets.")
        resp.raise_for_status()

    def _chunk_text_for_elevenlabs(text: str, max_chars: int = 5000) -> List[str]:
        """
        Split text into chunks for ElevenLabs API (limit is 5000, use 4000 for more safety).
        Splits at sentence boundaries to avoid audio breaks and ensure complete thoughts.
        """
        if len(text) <= max_chars:
            return [text]

        chunks = []
        remaining = text.strip()

        while len(remaining) > max_chars:
            # Find the best split point: prefer sentence endings, then commas, then spaces
            chunk_candidate = remaining[:max_chars]

            # Look for sentence endings (., !, ?) anywhere in the chunk, prioritizing later ones
            best_split = -1
            sentence_endings = []

            for i, char in enumerate(chunk_candidate):
                if char in '.!?':
                    sentence_endings.append(i + 1)  # +1 to include the punctuation

            # Use the last (rightmost) sentence ending in the chunk
            if sentence_endings:
                best_split = sentence_endings[-1]
            else:
                # Fallback: look for commas or semicolons
                for i, char in enumerate(chunk_candidate):
                    if char in ',;':
                        best_split = i + 1  # +1 to include the punctuation

            # Last resort: look for spaces to avoid breaking words
            if best_split == -1:
                # Find the last space in the last 30% of the chunk
                search_start = int(max_chars * 0.7)
                for i in range(len(chunk_candidate) - 1, search_start - 1, -1):
                    if chunk_candidate[i] == ' ':
                        best_split = i + 1  # +1 to include the space
                        break

            # Absolute last resort: hard cut at max_chars (but try to avoid word breaks)
            if best_split == -1:
                # Try to find a space near the end
                for i in range(max_chars - 1, max(max_chars - 50, 0), -1):
                    if i < len(chunk_candidate) and chunk_candidate[i] == ' ':
                        best_split = i + 1
                        break

            # If still no good split, hard cut
            if best_split == -1 or best_split == 0:
                best_split = max_chars

            chunk_text = remaining[:best_split].strip()
            if chunk_text:  # Only add non-empty chunks
                chunks.append(chunk_text)
            remaining = remaining[best_split:].strip()

        if remaining:
            chunks.append(remaining)

        # Log chunking for debugging
        if len(chunks) > 1:
            logging.info(f"Split text into {len(chunks)} chunks: {[len(c) for c in chunks]} characters")

        return chunks

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout))
    )
    def _speak_chunk(text: str, voice_id: str, chunk_file: Path):
        """Generate audio for a single text chunk."""
        url = f"{ELEVEN_API}/text-to-speech/{voice_id}/stream"
        headers = {"xi-api-key": ELEVEN_KEY}
        payload = {
            "text": text,
            "model_id": "eleven_turbo_v2_5",
            "voice_settings": {
                "stability": 0.65,
                "similarity_boost": 0.9,
                "style": 0.85,
                "use_speaker_boost": True
            }
        }
        with requests.post(
            url,
            json=payload,
            headers=headers,
            stream=True,
            timeout=120,
        ) as r:
            if r.status_code >= 500 or r.status_code == 429:
                r.raise_for_status()
            r.raise_for_status()
            with open(chunk_file, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

    def speak(text: str, voice_id: str, filename: str):
        """
        Generate audio with intelligent chunking and seamless concatenation.
        Handles texts longer than ElevenLabs API limits by splitting at sentence boundaries.
        """
        # Split text into chunks if needed
        chunks = _chunk_text_for_elevenlabs(text)
        
        if len(chunks) == 1:
            # Single chunk: generate directly
            _speak_chunk(text + "!", voice_id, Path(filename))
            logging.info(f"ElevenLabs TTS: Generated single chunk ({len(text)} chars)")
        else:
            # Multiple chunks: generate each and concatenate seamlessly
            logging.info(f"ElevenLabs TTS: Splitting into {len(chunks)} chunks for seamless generation")
            chunk_files = []
            tmp_dir = Path(filename).parent
            
            try:
                for i, chunk_text in enumerate(chunks):
                    chunk_file = tmp_dir / f"tts_chunk_{i:03d}.mp3"
                    # Add punctuation to all but the last chunk to maintain flow
                    if i < len(chunks) - 1:
                        chunk_text = chunk_text.rstrip('.!?') + '.'
                    else:
                        chunk_text = chunk_text + "!"
                    
                    _speak_chunk(chunk_text, voice_id, chunk_file)
                    chunk_files.append(chunk_file)
                    logging.info(f"Generated chunk {i+1}/{len(chunks)} ({len(chunk_text)} chars)")
                
                # Concatenate chunks seamlessly using ffmpeg
                concat_list = tmp_dir / "elevenlabs_concat.txt"
                with open(concat_list, "w", encoding="utf-8") as f:
                    for chunk_file in chunk_files:
                        f.write(f"file '{chunk_file.absolute()}'\n")
                
                # Use ffmpeg concat with seamless joining (no gaps)
                subprocess.run([
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(concat_list),
                    "-c", "copy",  # Stream copy for speed and no re-encoding artifacts
                    str(filename)
                ], check=True, capture_output=True, timeout=300)
                
                logging.info(f"ElevenLabs TTS: Concatenated {len(chunks)} chunks seamlessly")
                
            finally:
                # Cleanup chunk files
                for chunk_file in chunk_files:
                    try:
                        if chunk_file.exists():
                            chunk_file.unlink()
                    except Exception:
                        pass
                try:
                    if concat_list.exists():
                        concat_list.unlink()
                except Exception:
                    pass

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

    # Extract text from podcast script (remove "Patrick:" prefixes and stage directions)
    full_text_parts = []
    for line in podcast_script.splitlines():
        line = line.strip()
        if line.startswith("[") or not line:
            continue
        if line.startswith("Patrick:"):
            full_text_parts.append(line[9:].strip())
        else:
            # Include all other content that isn't stage directions
            full_text_parts.append(line)

    full_text = " ".join(full_text_parts).strip()

    # Ensure we have content and log it for debugging
    if not full_text:
        logging.error("ERROR: No text content extracted from podcast script!")
        raise RuntimeError("Podcast script processing failed - no text content found")

    logging.info(f"Extracted podcast script: {len(full_text)} characters")
    if len(full_text) < 500:
        logging.warning(f"WARNING: Extracted text seems too short ({len(full_text)} chars). Full text: {full_text[:500]}...")
    full_text = fix_tesla_pronunciation(full_text)

    # Track character count (used for reporting; cost is provider-dependent)
    if TTS_PROVIDER == "elevenlabs":
        credit_usage["services"]["elevenlabs_api"]["characters"] = len(full_text)
    logging.info(f"TTS: {len(full_text)} characters to synthesize (provider={TTS_PROVIDER})")

    # Generate voice file
    import time
    tts_start_time = time.time()
    try:
        logging.info("Generating voice track with Chatterbox-Turbo (local model)...")
        voice_file = tmp_dir / "patrick_full.wav"
        _synthesize_with_chatterbox(full_text, voice_file)
        if not voice_file.exists():
            raise FileNotFoundError(f"TTS generation failed: voice file not created at {voice_file}")
        audio_files = [str(voice_file)]
        tts_duration = time.time() - tts_start_time
        logging.info(f"✅ Generated complete voice track: {voice_file} ({tts_duration:.1f}s, {len(full_text)/tts_duration:.1f} chars/sec)")
    except Exception as e:
        logging.error(f"❌ Chatterbox-Turbo TTS generation failed: {e}", exc_info=True)
        raise  # Re-raise to ensure workflow fails visibly

    # ========================== FINAL MIX ==========================
    final_mp3 = digests_dir / f"Tesla_Shorts_Time_Pod_Ep{episode_num:03d}_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp3"
    
    MAIN_MUSIC = project_root / "tesla_shorts_time.mp3"
    
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
    
    if not MAIN_MUSIC.exists():
        logging.warning(f"⚠️  Background music file '{MAIN_MUSIC}' not found - generating voice-only podcast")
        logging.warning("💡 To add background music: ensure 'tesla_shorts_time.mp3' exists in project root")
        subprocess.run(["ffmpeg", "-y", "-threads", "0", "-i", str(voice_mix), "-preset", "fast", str(final_mp3)], check=True, capture_output=True)
        logging.info("✅ Podcast ready (voice-only)")
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
        music_outro = tmp_dir / "music_outro.mp3"
        
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
            ("outro", ["ffmpeg", "-y", "-threads", "0", "-i", str(MAIN_MUSIC), "-ss", str(voice_duration), "-t", "50",
                      "-af", "volume=0.4,afade=t=out:curve=log:st=30:d=20", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                      str(music_outro)]),
        ]
        
        with ThreadPoolExecutor(max_workers=4) as executor:
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
                                                        "-t", str(middle_silence_duration), "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                                                        str(music_silence)]))
        
        voice_dependent_segments.append(("fadein", ["ffmpeg", "-y", "-threads", "0", "-i", str(MAIN_MUSIC), "-ss", str(music_fade_in_start), "-t", str(music_fade_in_duration),
                                                    "-af", f"volume=0.3,afade=t=in:curve=log:st=0:d={music_fade_in_duration}", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
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
        
        # Concatenate music segments
        music_concat_list = tmp_dir / "music_concat.txt"
        with open(music_concat_list, "w") as f:
            f.write(f"file '{music_intro.absolute()}'\n")
            f.write(f"file '{music_overlap.absolute()}'\n")
            f.write(f"file '{music_fadeout.absolute()}'\n")
            if middle_silence_duration > 0.1:
                f.write(f"file '{music_silence.absolute()}'\n")
            f.write(f"file '{music_fadein.absolute()}'\n")
            f.write(f"file '{music_outro.absolute()}'\n")
        
        music_full = tmp_dir / "music_full.mp3"
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0", "-f", "concat", "-safe", "0", "-i", str(music_concat_list),
            "-c", "copy", str(music_full)
        ], check=True, capture_output=True)
        
        # Verify music_full was created
        if not music_full.exists():
            raise RuntimeError(f"Music full file {music_full} was not created!")

        music_full_size = music_full.stat().st_size
        logging.info(f"Music full file size: {music_full_size} bytes")

        if music_full_size < 1000:
            raise RuntimeError(f"Music full file {music_full} is too small ({music_full_size} bytes) - music concatenation failed")

        # Mix voice and music
        logging.info("Mixing voice and music...")
        subprocess.run([
            "ffmpeg", "-y", "-threads", "0", "-i", str(voice_mix), "-i", str(music_full),
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:dropout_transition=2",
            "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
            str(final_mp3)
        ], check=True, capture_output=True, timeout=timeout_seconds)

        # Verify final file was created and has content
        if not final_mp3.exists():
            raise RuntimeError(f"Final podcast file {final_mp3} was not created!")

        final_size = final_mp3.stat().st_size
        logging.info(f"Final podcast file size: {final_size} bytes")

        if final_size < 10000:  # Less than 10KB is definitely wrong for a 55s podcast
            raise RuntimeError(f"Final podcast file {final_mp3} is too small ({final_size} bytes) - mixing failed")

        logging.info(f"✅ Final podcast created: {final_mp3.name}")


def scan_existing_episodes_from_files(digests_dir: Path, base_url: str) -> list:
    """Scan digests directory for all existing MP3 files and return episode data."""
    episodes = []
    pattern = r"Tesla_Shorts_Time_Pod_Ep(\d+)_(\d{8})_(\d{6})\.mp3"
    
    for mp3_file in digests_dir.glob("Tesla_Shorts_Time_Pod_Ep*.mp3"):
        match = re.match(pattern, mp3_file.name)
        if match:
            episode_num = int(match.group(1))
            date_str = match.group(2)
            time_str = match.group(3)
            try:
                episode_date = datetime.datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S").date()
                mp3_duration = get_audio_duration(mp3_file)
                
                # Create episode data
                # GUID based on date AND time to allow multiple episodes per day
                # Use the time from the filename (already extracted as time_str)
                
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

# ========================== 5. UPDATE RSS FEED ==========================
# Fail loudly if podcast generation was enabled but failed
if ENABLE_PODCAST and not TEST_MODE:
    if not final_mp3 or not final_mp3.exists():
        error_msg = f"❌ Podcast generation was enabled but failed - final_mp3={final_mp3}"
        if final_mp3:
            error_msg += f", exists={final_mp3.exists()}"
        error_msg += ". This means the episode will NOT appear in the RSS feed or GitHub page."
        logging.error(error_msg)
        raise RuntimeError(error_msg)  # Fail the workflow so it's visible

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
        thumbnail_filename = f"Tesla_Shorts_Time_Thumbnail_Ep{episode_num:03d}_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
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