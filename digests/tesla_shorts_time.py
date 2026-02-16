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
from openai import RateLimitError, PermissionDeniedError
from difflib import SequenceMatcher
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
import feedparser
from typing import List, Dict, Any
from collections import Counter
import random
import tweepy
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from urllib.parse import quote

# --- engine/ shared modules ---
from engine.utils import (
    env_float, env_int, env_bool,
    number_to_words as _engine_number_to_words,
    calculate_similarity as _engine_calculate_similarity,
    remove_similar_items as _engine_remove_similar_items,
    norm_headline_for_similarity as _engine_norm_headline,
    filter_articles_by_recent_stories as _engine_filter_recent,
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

# Set to True to save summaries to GitHub Pages instead of posting full content to X
ENABLE_GITHUB_SUMMARIES = True

# Link validation is currently disabled - validation functions have been removed
# Set to True and re-implement validation functions if needed in the future
ENABLE_LINK_VALIDATION = False

# Shared HTTP defaults
DEFAULT_HEADERS = {
    "User-Agent": "TeslaShortsTimeBot/1.0 (+https://x.com/teslashortstime)"
}
HTTP_TIMEOUT_SECONDS = 10


# ========================== NUMBER TO WORDS CONVERTER ==========================
number_to_words = _engine_number_to_words

# ========================== PRONUNCIATION FIXER – USING SHARED DICTIONARY ==========================
# Note: Import will be set up after project_root is defined
USE_SHARED_PRONUNCIATION = False

def fix_tesla_pronunciation(text: str) -> str:
    """
    Forces correct spelling of Tesla acronyms, converts numbers to words,
    and fixes dates/times for better TTS pronunciation on ElevenLabs.
    """
    import re

    # --------------------------
    # TTS pronunciation overrides (Tesla Shorts Time)
    # --------------------------
    # ElevenLabs tends to spell acronyms like "ICE" / "I.C.E" as "I C E".
    # For this show we want the spoken word "ice" instead (as requested).
    text = re.sub(r'(?i)(?<!\w)I\.?C\.?E\.?(?!\w)', 'ice', text)

    # ElevenLabs often misreads "robotaxis" as "robot axis". We bias toward the intended
    # "robo-taxis" pronunciation. Keep a light touch: whole-word only.
    def _fix_robotaxi_forms(m: re.Match) -> str:
        w = m.group(0)
        # Preserve leading capitalization for sentence starts / titles.
        if w[:1].isupper():
            return "Robo-taxis"
        return "robo-taxis"
    text = re.sub(r'(?i)(?<!\w)robotaxis(?!\w)', _fix_robotaxi_forms, text)
    text = re.sub(r'(?i)(?<!\w)robotaxi(?!\w)', lambda m: "Robo-taxi" if m.group(0)[:1].isupper() else "robo-taxi", text)

    # CRITICAL: Fix common words FIRST before any acronym processing
    # This prevents TTS from misreading words like "who" as "W.H.O."
    # ElevenLabs sometimes reads short words as acronyms, so we need explicit fixes
    
    # Fix "who" - prevent "W.H.O." mispronunciation
    # The issue is that TTS sees "who" and thinks it might be an acronym
    # Solution: Use a phonetic spelling that TTS will read correctly as a word
    # We'll temporarily replace with a unique marker that won't be confused with acronyms
    # Then restore it after all acronym processing is complete
    text = re.sub(r'\bwho\b', 'WHO_WORD_PLACEHOLDER', text, flags=re.IGNORECASE)
    
    # Additional common word fixes to prevent acronym misreading
    # These words are sometimes read as acronyms by TTS - we'll restore them after acronym processing
    common_word_protection = {
        'WHO_WORD_PLACEHOLDER': 'who',  # Restore "who" after acronym processing
    }
    
    # List of acronyms that must be spelled out letter-by-letter (use spaces, not ZWJ)
    # IMPORTANT: Order matters - longer/more specific acronyms must come FIRST
    # This prevents "EVs" from being matched by "EV" first
    acronyms = {
        # Plural forms first (longer matches)
        "BEVs": "B E V s",
        "PHEVs": "P H E V s",
        # Prefer a natural pronunciation over letter-by-letter spelling
        # (e.g., "EVs" -> "ee vees" instead of "E V s")
        "EVs":  "ee vees",
        # Company names with special handling
        "SpaceX": "Space X",  # Must be processed as phrase, not individual letters
        # Single forms (shorter matches)
        "TSLA": "T S L A",
        "FSD":  "F S D",
        "HW3":  "H W 3",
        "HW4":  "H W 4",
        "AI5":  "A I 5",
        "4680": "4 6 8 0",
        "EV":   "E V",
        "BEV":  "B E V",
        "PHEV": "P H E V",
        # NOTE: We intentionally do NOT spell out ICE for Tesla Shorts Time; we normalize it to "ice" above.
        "NHTSA":"N H T S A",
        "OTA":  "O T A",
        "LFP":  "L F P",
        "V2G": "V 2 G",
        "V2H": "V 2 H",
        "V2L": "V 2 L",
        "DC": "D C",
        "AC": "A C",
        "kW": "kilowatts",
        "kWh": "kilowatt hours",
        "MPGe": "M P G e",
        "EPA": "E P A",
        "WLTP": "W L T P",
        "NEDC": "N E D C",
    }

    for acronym, spelled in acronyms.items():
        # Build a regex that only matches the acronym when it's a whole word
        pattern = rf'(?<!\w){re.escape(acronym)}(?!\w)'
        # If the replacement already contains spaces (like "Space X"), use it as-is
        # Otherwise, join individual characters with spaces
        if ' ' in spelled:
            replacement = spelled
        else:
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
    
    # Handle large currency amounts with words like "trillion", "billion", "million"
    def replace_large_currency(match):
        dollar_sign = match.group(1)
        num_str = match.group(2)
        unit = match.group(3).lower() if match.group(3) else ""
        try:
            num = float(num_str)
            words = number_to_words(num)
            if unit:
                # Handle "trillion", "billion", "million"
                if unit == "trillion":
                    result = f"{words} trillion dollars"
                elif unit == "billion":
                    result = f"{words} billion dollars"
                elif unit == "million":
                    result = f"{words} million dollars"
                else:
                    result = f"{words} {unit} dollars"
            else:
                # Fall back to regular stock price handling
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
    
    # Match currency with large number words: "$3 Trillion", "$2.5 Billion", etc.
    text = re.sub(r'(\$)(\d+\.?\d*)\s*(trillion|billion|million)\b', replace_large_currency, text, flags=re.IGNORECASE)
    
    # Regular stock prices (after large currency to avoid conflicts)
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
    def replace_date_swapped(match):
        # Create a mock match object with the correct group order
        class MockMatch:
            def __init__(self, groups):
                self._groups = groups
            def group(self, n):
                return self._groups[n-1]
        # Swap day and month for "11 December, 2025" → "December 11, 2025"
        return replace_date(MockMatch([match.group(2), match.group(1), match.group(3)]))

    text = re.sub(r'(\d{1,2})\s+(\w+),\s+(\d{4})', replace_date_swapped, text, flags=re.IGNORECASE)

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
            # Override shared dictionaries for Tesla Shorts Time so we don't reintroduce
            # the ICE and Robotaxi issues via the shared defaults.
            local_acronyms = dict(COMMON_ACRONYMS)
            local_acronyms.pop("ICE", None)
            local_word_pronunciations = dict(WORD_PRONUNCIATIONS)
            local_word_pronunciations.update({
                "Robotaxis": "robo-taxis",
                "Robotaxi": "robo-taxi",
            })
            text = apply_pronunciation_fixes(
                text,
                acronyms=local_acronyms,
                hockey_terms={},  # Not needed for Tesla Shorts Time
                player_names={},  # Not needed for Tesla Shorts Time
                oilers_player_names={},  # Not needed for Tesla Shorts Time
                word_pronunciations=local_word_pronunciations,
                use_zwj=False  # Use spaces for Tesla Shorts Time (matches original behavior)
            )
        except Exception as e:
            logging.warning(f"Error applying shared pronunciation fixes: {e}, continuing with local fixes")

    # Fix common words that TTS might mispronounce as acronyms
    # IMPORTANT: Apply these BEFORE acronym processing to prevent misreading
    # Use phonetic spellings that TTS will read correctly as words, not acronyms
    common_word_fixes = {
        # Question words that TTS might read as acronyms
        "who": "who",  # Keep as "who" but ensure it's not processed as acronym
        "what": "what",  # Keep as "what"
        "where": "where",  # Keep as "where"
        "when": "when",  # Keep as "when"
        "why": "why",  # Keep as "why"
        "how": "how",  # Keep as "how"
        # Common words
        "now": "now",
        "new": "new",
        "one": "one",
        "two": "two",
        "too": "too",
        "for": "for",
        "four": "four",
    }
    
    # CRITICAL FIX: Prevent common words from being misread as acronyms
    # ElevenLabs TTS sometimes reads short words as acronyms (e.g., "who" → "W.H.O.")
    # The fix above (using WHO_WORD marker) should handle this, but we add extra protection here
    
    # Additional protection: ensure "who" is never processed as an acronym
    # Add explicit word boundaries and context
    text = re.sub(r'\bwho\s+', 'who ', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+who\b', ' who', text, flags=re.IGNORECASE)
    
    # Restore protected words after acronym processing
    for marker, word in common_word_protection.items():
        text = text.replace(marker, word)
    
    # Fix "EVs" - ensure it's read naturally (not letter-by-letter)
    # Apply this fix explicitly to ensure it overrides any earlier processing
    text = re.sub(r'\bEVs\b', 'ee vees', text, flags=re.IGNORECASE)
    
    # Fix "SpaceX" - ensure it's read as "Space X" not spelled out
    # Apply this fix explicitly to ensure it's handled correctly
    text = re.sub(r'\bSpaceX\b', 'Space X', text, flags=re.IGNORECASE)
    
    # "robotaxi(s)" handled above (avoid duplicate/contradictory rewrites)
    
    # Additional EV/Tesla terminology fixes
    ev_terminology_fixes = {
        # Vehicle models
        "Model 3": "Model Three",
        "Model Y": "Model Why",
        "Model S": "Model S",
        "Model X": "Model X",
        "Cybertruck": "Cyber truck",
        "Roadster": "Roadster",
        "Semi": "Semi",
        "Optimus": "Optimus",
        
        # Technology terms
        "Full Self-Driving": "Full Self Driving",
        "Autopilot": "Auto pilot",
        "Supercharger": "Super charger",
        "Megapack": "Mega pack",
        "Powerwall": "Power wall",
        "Solar Roof": "Solar Roof",
        "Gigafactory": "Giga factory",
        
        # Common phrases
        "robotaxi": "robo-taxi",
        "robotaxis": "robo-taxis",
        "V2G": "V 2 G",
        "V2H": "V 2 H",
        "V2L": "V 2 L",
    }
    
    # Apply EV/Tesla terminology fixes
    for term, replacement in ev_terminology_fixes.items():
        pattern = rf'\b{re.escape(term)}\b'
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    
    # Apply common word fixes (case insensitive, whole word only)
    # Note: These are kept for consistency but may not be needed if TTS handles them correctly
    for word, replacement in common_word_fixes.items():
        pattern = rf'\b{re.escape(word)}\b'
        # Only replace if it's not already been processed
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    return text

def generate_episode_thumbnail(base_image_path, episode_num, date_str, output_path):
    return _engine_generate_thumbnail(Path(base_image_path), episode_num, date_str, Path(output_path))

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


_env_float = env_float
_env_int = env_int
_env_bool = env_bool


# Required keys (X credentials only required if posting is enabled)
required = [
    "GROK_API_KEY"
]
if ENABLE_PODCAST and not TEST_MODE:
    required.append("ELEVENLABS_API_KEY")
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

# ========================== TESLA X TAKEOVER SECTION ==========================
# Tesla X Takeover now focuses on fresh, interesting Tesla news/trends instead of cycling through specific X accounts
# This ensures the section is always fresh and interesting, focusing on what's happening in the Tesla world right now

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
        "daily_challenges": [],
        "inspiration_quotes": [],
        "first_principles": [],
        "last_updated": None
    }

def save_used_content_tracker(tracker: dict):
    """Save used content tracker (only persisted keys; recent_stories is rebuilt from digest files)."""
    tracker_file = digests_dir / "tesla_content_tracker.json"
    try:
        # Keep only last 14 days of content (2 weeks)
        cutoff_date = (datetime.date.today() - datetime.timedelta(days=14)).isoformat()
        to_save = {}
        for key in ["short_spots", "daily_challenges", "inspiration_quotes", "first_principles"]:
            to_save[key] = [
                item for item in tracker.get(key, [])
                if item.get("date", "") >= cutoff_date
            ]
        to_save["last_updated"] = datetime.date.today().isoformat()
        with open(tracker_file, 'w', encoding='utf-8') as f:
            json.dump(to_save, f, indent=2)
    except Exception as e:
        logging.warning(f"Failed to save content tracker: {e}")

def extract_sections_from_digest(digest_path: Path) -> dict:
    """Extract Short Spot, Daily Challenge, and Inspiration Quote from a digest file."""
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


def extract_news_headlines_from_digest(digest_path: Path) -> list[str]:
    """Extract news story headlines from Top 10 News and Tesla X Takeover sections for dedup tracking."""
    headlines = []
    if not digest_path.exists():
        return headlines
    try:
        with open(digest_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Top 10 News: match numbered lines with bold title (e.g. "1. **Title...**" or "1️⃣ **Title...**")
        top10_section = re.search(
            r'(?:📰 \*\*Top 10 News Items\*\*|### Top 10 News Items)(.*?)(?=━━|## Short Spot|📉|### Tesla First Principles|## Tesla X Takeover|🎙️ \*\*Tesla X Takeover)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        if top10_section:
            block = top10_section.group(1)
            # First 10 bold runs in Top 10 section (handles "1. **Title**" and "1️⃣ **Title**")
            for m in re.finditer(r'\*{2}([^*]{15,})\*{2}', block):
                t = m.group(1).strip()
                if t and t not in headlines:
                    headlines.append(t)
                if len(headlines) >= 10:
                    break
        # Tesla X Takeover: match "1. 🚨 **Title** -" or "2. 🔥 **Title** -"
        takeover_section = re.search(
            r'(?:## Tesla X Takeover|🎙️ \*\*Tesla X Takeover[^\n]*)(.*?)(?=━━|## Short Spot|📉|### Tesla First Principles)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        if takeover_section:
            block = takeover_section.group(1)
            for m in re.finditer(r'^\d+\.\s*(?:🚨|🔥|💡|⚡|🎯)?\s*\*{2}(.+?)\*{2}\s*[-–]', block, re.MULTILINE):
                headlines.append(m.group(1).strip())
    except Exception as e:
        logging.debug(f"Could not extract headlines from {digest_path}: {e}")
    return headlines


_norm_headline_for_similarity = _engine_norm_headline


def load_recent_digests(max_days: int = 14) -> dict:
    """Load sections from recent digests to track what's been used."""
    tracker = {
        "short_spots": [],
        "short_squeezes": [],
        "daily_challenges": [],
        "inspiration_quotes": [],
        "recent_stories": []  # Headlines from Top 10 + Tesla X Takeover for cross-day dedup
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
                # Extract news headlines for cross-day story dedup
                for headline in extract_news_headlines_from_digest(digest_path):
                    tracker["recent_stories"].append({
                        "date": check_date.isoformat(),
                        "content": headline
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
    
    if tracker.get("first_principles"):
        recent = tracker["first_principles"][-7:]  # Last 7 First Principles analyses
        principles_text = "\n".join([f"- {item.get('content', '')[:200]}..." for item in recent])
        summary_parts.append(f"RECENTLY USED FIRST PRINCIPLES TOPICS (DO NOT REPEAT - use COMPLETELY DIFFERENT topics/analysis):\n{principles_text}")
    
    if tracker.get("daily_challenges"):
        recent = tracker["daily_challenges"][-7:]  # Last 7 Daily Challenges
        challenges_text = "\n".join([f"- {item.get('content', '')[:200]}..." for item in recent])
        summary_parts.append(f"RECENTLY USED DAILY CHALLENGES (DO NOT REPEAT - create a COMPLETELY NEW and DIFFERENT challenge):\n{challenges_text}")
    
    if tracker.get("inspiration_quotes"):
        recent = tracker["inspiration_quotes"][-10:]  # Last 10 quotes (more variety needed)
        quotes_text = "\n".join([f"- {item.get('content', '')[:150]}..." for item in recent])
        summary_parts.append(f"RECENTLY USED INSPIRATION QUOTES (DO NOT REPEAT - use a DIFFERENT quote from a DIFFERENT author):\n{quotes_text}")
    
    if tracker.get("recent_stories"):
        recent = tracker["recent_stories"][-35:]  # Last ~35 headlines (Top 10 + X Takeover across ~2 days)
        stories_text = "\n".join([f"- {item.get('content', '')[:120]}" for item in recent])
        summary_parts.append(f"RECENTLY COVERED NEWS STORIES (DO NOT repeat these in Top 10 News or Tesla X Takeover - pick DIFFERENT stories):\n{stories_text}")
    
    if summary_parts:
        return "\n\n".join(summary_parts) + "\n\n🚨 CRITICAL: Generate COMPLETELY NEW, FRESH, and DIFFERENT content for ALL sections. Avoid ANY similarity to the above. Each section must be unique and engaging.\n"
    return ""

# Initialize content tracker
content_tracker = load_used_content_tracker()
# Also load from recent digest files to get the most up-to-date tracking
recent_tracker = load_recent_digests(max_days=14)
# Merge both (recent digests take precedence)
for key in ["short_spots", "daily_challenges", "inspiration_quotes", "first_principles", "recent_stories"]:
    # Combine and deduplicate by content
    combined = content_tracker.get(key, []) + recent_tracker.get(key, [])
    seen_content = set()
    unique_items = []
    for item in combined:
        content_hash = item.get("content", "")[:100]  # Use first 100 chars as hash
        if content_hash not in seen_content:
            seen_content.add(content_hash)
            unique_items.append(item)
    # Sort by date, most recent first; keep last 14 for sections, last 45 for recent_stories
    unique_items.sort(key=lambda x: x.get("date", ""), reverse=True)
    content_tracker[key] = unique_items[:45] if key == "recent_stories" else unique_items[:14]

used_content_summary = get_used_content_summary(content_tracker)

def get_next_episode_number(rss_path, digests_dir):
    return _engine_get_next_episode_number(
        rss_path, digests_dir, mp3_glob_pattern="Tesla_Shorts_Time_Pod_Ep*.mp3",
    )

# Get the next episode number
rss_path = project_root / "podcast.rss"
episode_num = get_next_episode_number(rss_path, digests_dir)

# ========================== CREDIT TRACKING ==========================
credit_usage = create_tracker("Tesla Shorts Time", episode_num)

def save_credit_usage(usage_data, output_dir):
    """Thin wrapper around engine.tracking.save_usage."""
    save_usage(usage_data, output_dir)

def save_summary_to_github_pages(
    summary_text, output_dir, podcast_name="tesla", *,
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
ELEVEN_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVEN_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "dTrBzPvD2GpAqkk1MUzA")  # Default: High-energy Patrick
# NEWSAPI_KEY no longer needed - using RSS feeds instead


# ========================== XAI RESPONSES API (TOOLS) ==========================
# xAI deprecated "live search" on Chat Completions (410 Gone). Use Responses API + tools instead.
XAI_API_BASE_URL = os.getenv("XAI_API_BASE_URL", "https://api.x.ai/v1").rstrip("/")


def _get_xai_api_key() -> str:
    key = (os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("Missing xAI API key. Set GROK_API_KEY (preferred) or XAI_API_KEY.")
    return key


def _xai_responses_create(
    *,
    model: str,
    input_payload,
    tools: list[dict] | None = None,
    temperature: float | None = None,
    max_output_tokens: int | None = None,
    store: bool = False,
    timeout_seconds: float = 300.0,
) -> dict:
    """
    Call xAI Responses API directly (OpenAI-compatible).
    Supports server-side tools like {"type": "web_search"} without using deprecated Chat Completions params.
    """
    url = f"{XAI_API_BASE_URL}/responses"
    headers = {
        "Authorization": f"Bearer {_get_xai_api_key()}",
        "Content-Type": "application/json",
    }
    payload: dict = {
        "model": model,
        "input": input_payload,
        "store": store,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if max_output_tokens is not None:
        payload["max_output_tokens"] = max_output_tokens
    if tools:
        payload["tools"] = tools

    resp = requests.post(url, headers=headers, json=payload, timeout=timeout_seconds)
    if resp.status_code >= 400:
        try:
            err = resp.json()
        except Exception:
            err = {"error": resp.text}
        raise RuntimeError(f"xAI Responses API error {resp.status_code}: {err}")
    return resp.json()


def _extract_responses_text(response_json: dict) -> str:
    out_text = response_json.get("output_text")
    if isinstance(out_text, str) and out_text.strip():
        return out_text.strip()

    output = response_json.get("output", [])
    parts: list[str] = []
    if isinstance(output, list):
        for entry in output:
            if not isinstance(entry, dict):
                continue
            content = entry.get("content", [])
            if not isinstance(content, list):
                continue
            for chunk in content:
                if isinstance(chunk, dict) and isinstance(chunk.get("text"), str):
                    parts.append(chunk["text"])
    text = "".join(parts).strip()
    if not text:
        raise RuntimeError("xAI Responses API returned no text output.")
    return text


def _extract_responses_usage(response_json: dict) -> dict:
    usage = response_json.get("usage")
    return usage if isinstance(usage, dict) else {}


# ========================== STEP 1: FETCH TESLA NEWS FROM RSS FEEDS ==========================
logging.info("Step 1: Fetching Tesla news from RSS feeds for the last 24 hours...")

calculate_similarity = _engine_calculate_similarity
remove_similar_items = _engine_remove_similar_items
filter_articles_by_recent_stories = _engine_filter_recent


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.RequestException, requests.Timeout))
)
def fetch_tesla_news():
    """Fetch Tesla-related news from RSS feeds of Tesla news sites for the last 24 hours.
    Returns tuple: (filtered_articles, raw_articles) for saving raw data."""
    import feedparser
    
    # Tesla news site RSS feeds - prioritize high-quality, frequently updated sources
    rss_feeds = [
        # Primary sources (most reliable for fresh, specific content)
        "https://www.teslarati.com/feed/",  # High-quality Tesla news
        "https://www.theverge.com/rss/tesla/index.xml",  # Premium tech coverage
        "https://www.findmyelectric.com/feed/",  # EV news and reviews
        "https://insideevs.com/rss/",  # Good EV news
        "https://cleantechnica.com/tag/tesla/feed/",  # Clean energy focus

        # Secondary sources (good but sometimes generic)
        "https://www.thedrive.com/category/tesla-news/feed",  # Automotive focus
        "https://whatsuptesla.com/feed",  # Tesla-focused
        "https://www.notateslaapp.com/news/rss",  # Tesla news
        "https://www.tesmanian.com/blogs/tesmanian-blog.atom",  # Tesmanian

        # Regional sources
        "https://driveteslacanada.ca/feed/",  # Regional coverage
        "https://www.tesery.com/en-in/blogs/news.atom",  # Tesla news

        # Additional sources for broader coverage
        "https://www.webpronews.com/search/tesla/feed/rss2/",  # WebProNews Tesla
        "https://www.autoblog.com/rss.xml",  # Auto news (may contain Tesla)
        "https://www.greencarreports.com/rss.xml",  # Green car news

        # Limited use sources (often generic - heavily filtered)
        "http://feeds.feedburner.com/teslanorth",  # Tesla North
        "https://www.torquenews.com/rss/tesla",  # Torque News
        # Removed problematic sources: mashable, teslainvestor.blogspot, teslasiliconvalley, cnbc
    ]
    
    # Calculate cutoff time (last 48 hours - strict freshness requirement)
    cutoff_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=48)
    logging.info(f"Fetching articles published after {cutoff_time.strftime('%Y-%m-%d %H:%M:%S UTC')} (last 48 hours)")
    
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
            elif "findmyelectric" in feed_url.lower():
                source_name = "Find My Electric"
            elif "tesmanian" in feed_url.lower():
                source_name = "Tesmanian"
            elif "torquenews" in feed_url.lower():
                source_name = "Torque News"
            elif "cleantechnica" in feed_url.lower():
                source_name = "Clean Technica"
            elif "webpronews" in feed_url.lower():
                source_name = "WebProNews"
            elif "autoblog" in feed_url.lower():
                source_name = "Autoblog"
            elif "greencarreports" in feed_url.lower():
                source_name = "Green Car Reports"
            
            feed_articles = []
            logging.debug(f"Processing {len(feed.entries)} entries from {source_name}")
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
                
                # Skip if older than cutoff time (48 hours)
                if published_time and published_time < cutoff_time:
                    logging.debug(f"Skipping article older than 48 hours: {title[:50]}... (published: {published_time})")
                    continue

                # Skip articles with obviously wrong dates (future dates beyond reasonable window)
                now = datetime.datetime.now(datetime.timezone.utc)
                one_week_future = now + datetime.timedelta(days=7)
                if published_time and published_time > one_week_future:
                    logging.debug(f"Skipping article with future date: {published_time}")
                    continue

                # Skip articles that are too old (more than 10 days, even if within cutoff)
                ten_days_ago = now - datetime.timedelta(days=10)
                if published_time and published_time < ten_days_ago:
                    continue

                # Get title and description
                title = entry.get("title", "").strip()
                description = entry.get("description", "").strip() or entry.get("summary", "").strip()
                link = entry.get("link", "").strip()

                if not title or not link:
                    continue

                # Check if article is Tesla-related (must contain Tesla keywords)
                title_desc_lower = (title + " " + description).lower()
                if not any(keyword in title_desc_lower for keyword in tesla_keywords):
                    continue

                # Skip very short content (likely homepage or summary)
                if len(title_desc_lower) < 50:
                    continue
                
                # Skip stock quotes/price commentary and generic pages
                skip_terms = [
                    # Stock/finance content
                    "stock quote", "tradingview", "yahoo finance ticker", "price chart",
                    "stock price", "quote & history", "stock data", "trading data",
                    "stock hits", "stock climbs", "stock reaches", "stock update",

                    # Generic content
                    "company overview", "general news", "latest news", "news and tips",
                    "rumors and tips", "breaking news model 3", "news, latest software",
                    "news, tips, rumors", "news and reviews", "latest updates",
                    "ongoing coverage", "provides ongoing", "covers the latest",
                    "offers global views", "recent developments", "market positioning",

                    # Homepage/main page indicators
                    "home page", "main page", "front page", "featured articles",
                    "popular stories", "trending now", "most read",

                    # Elon Musk generic
                    "elon musk x posts", "elon musk recent", "musk's recent posts",
                    "musk active on x", "musk posting about",

                    # Generic Tesla content
                    "tesla news roundup", "tesla rumors roundup", "tesla updates roundup",
                    "tesla developments", "tesla innovations", "tesla advancements"
                ]
                if any(skip_term in title_desc_lower for skip_term in skip_terms):
                    continue

                # Skip if title is too generic (indicates homepage/main page)
                generic_titles = [
                    "tesla news", "tesla", "tesla inc", "elon musk", "tesla updates",
                    "latest tesla", "tesla latest", "tesla breaking", "tesla rumors",
                    "tesla news and rumors", "latest tesla news", "tesla breaking news",
                    "tesla vehicle updates", "breaking tesla", "tesla developments",
                    "elon musk x posts", "elon musk recent x", "musk's x posts",
                    "international tesla news", "tesla international", "global tesla",
                    "top tesla", "tesla top", "tesla analyst", "analyst on tesla"
                ]
                if any(title.lower().strip() == generic for generic in generic_titles):
                    continue

                # Source-specific filtering for known problematic feeds
                if "tesla-mag.com" in link.lower() and ("breaking news" in title_desc_lower or len(description) < 100):
                    continue  # Tesla Mag often has very short/generic content
                if "newsweek.com" in link.lower() and "elon musk x" in title_desc_lower:
                    continue  # Newsweek Elon Musk posts are usually not Tesla-specific
                if "reuters.com/company/tesla" in link.lower():
                    continue  # Reuters company overview pages are generic

                # Skip if description is too short or generic
                if len(description) < 60 or description.lower().startswith(("tesla", "elon musk", "the company")):
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
        logging.warning("No articles found from RSS feeds - this will result in limited news content")
        logging.warning(f"Checked {len(rss_feeds)} RSS feeds but found 0 articles")
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
    logging.info(f"Article counts by source: {dict(sorted(Counter(a['source'] for a in formatted_articles).items()))}")
    if len(formatted_articles) < 5:
        logging.warning(f"Only {len(formatted_articles)} quality articles found - web search fallback will be used")
        logging.warning("This may result in limited news content in the digest")
    filtered_result = formatted_articles[:30]  # Return top 30 for selection
    return filtered_result, raw_articles

tesla_news, raw_news_articles = fetch_tesla_news()

# Cross-day dedup: drop articles that are too similar to stories already covered in recent digests
recent_headlines = [item.get("content", "") for item in content_tracker.get("recent_stories", [])]
tesla_news = filter_articles_by_recent_stories(tesla_news, recent_headlines, similarity_threshold=0.72)

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
    news_section = "## PRE-FETCHED NEWS ARTICLES: Limited news available today. Focus on high-quality X posts for the digest.\n\n"

# X POSTS SECTION DISABLED - No longer including X posts in prompt
x_posts_section = ""

# Build conditional sections
weekday = datetime.date.today().weekday()  # 0=Monday, 6=Sunday
market_movers_section = ""
if weekday == 0:  # Monday (0 = Monday in Python weekday())
    market_movers_section = """
━━━━━━━━━━━━━━━━━━━━
### Tesla Market Movers
📈 Tesla Market Movers - What's Actually Moving TSLA

**The Big Picture:** [Analysis of broader market context affecting Tesla this week]

**Short Interest Update:** [Current short interest levels and week-over-week changes. Include notable movements and what they signal]

**Institutional Moves:** [Recent large buys/sells by institutions, hedge funds, or notable investors]

**Options Flow:** [Unusual options activity, call/put ratios, expiration dates with high volume]

**Whale Watching:** [Large shareholder moves, insider transactions, or notable retail investor activity]

**Market Sentiment:** [Overall market mood toward Tesla, compared to other EV/tech stocks]
"""

X_PROMPT = f"""
# Tesla Shorts Time - DAILY EDITION
**Date:** {today_str}
**REAL-TIME TSLA price:** ${price:.2f} {change_str}

{news_section}

{x_posts_section}

You are an elite Tesla news curator producing the daily "Tesla Shorts Time" newsletter. Use ONLY the pre-fetched news above. Do NOT hallucinate, invent, or search for new content/URLs—stick to exact provided links. Do NOT include a "Top X Posts" section in your output. Prioritize diversity: No duplicates/similar stories (≥70% overlap in angle/content); max 3 from one source/account.

CRITICAL: Only select articles that are SPECIFIC, FRESH (within last 48 hours), and SUBSTANTIVE. REJECT any articles that are:
- Generic homepage content ("latest news", "ongoing coverage", "provides updates")
- Stock price/market data focused
- Very short descriptions (<100 characters)
- From obviously wrong dates (future dates or very old)
- Elon Musk posts that aren't Tesla-specific
- Company overview pages

If fewer than 8 quality articles are available, use ALL available quality articles and create a shorter digest rather than padding with low-quality content.

**TESLA X TAKEOVER SECTION**: This section should focus on the most interesting, fresh, and engaging recent Tesla news developments, trends, or breaking stories. Use the pre-fetched news articles above to identify 5 compelling Tesla stories or trends that are generating buzz. Focus on what's NEW, INTERESTING, and DIFFERENT from the main news section. This could include:
- Breaking developments that just emerged
- Interesting trends or patterns in Tesla's business
- Surprising announcements or updates
- Community reactions to major Tesla news
- Unique angles on Tesla stories that stand out

CRITICAL: The 5 Tesla X Takeover items must each be a DIFFERENT story from the 10 Top 10 News items—do NOT use the same article, same headline, or same story angle in both sections. Make each Takeover item engaging and fresh; each should feel like you're sharing exciting, breaking Tesla news with enthusiasm.

**FINAL FALLBACK**: Only if RSS feeds provide fewer than 5 quality articles, you may search for additional recent, legitimate Tesla news articles from reputable sources (Teslarati, The Verge, WebProNews, CleanTechnica) published within the last 48 hours. Prioritize breaking news and specific product updates over analysis pieces. Ensure no more than 2 articles from any single source. 

**CRITICAL**: 
- Do NOT include any instruction language, meta-commentary, or formatting notes in your output - only output the actual content.
- Focus on FRESH, INTERESTING Tesla news that's different from the main news section
- Make it engaging and exciting - like sharing breaking Tesla news with friends

{used_content_summary}

### CRITICAL INSTRUCTIONS (DO NOT INCLUDE THESE IN YOUR OUTPUT):
- Short Spot: Must be COMPLETELY DIFFERENT from any recent Short Spots. Use a DIFFERENT bearish story, DIFFERENT angle, and DIFFERENT framing.
- Tesla First Principles: Must be COMPLETELY DIFFERENT from any recent First Principles analyses. Use a DIFFERENT current situation, DIFFERENT fundamental question, DIFFERENT data analysis, and DIFFERENT Tesla approach.
- Tesla Market Movers (Mondays only): Must provide FRESH market analysis from the past week. Focus on REAL market movements, not speculation.
- Daily Challenge: Must be COMPLETELY NEW and DIFFERENT from any recent Daily Challenges. Use a DIFFERENT theme, DIFFERENT approach, and DIFFERENT wording.
- Inspiration Quote: Must be from a DIFFERENT author than recent quotes. Use a DIFFERENT quote with a DIFFERENT message. Vary authors widely.

**IMPORTANT**: The format template below shows what your OUTPUT should look like. Do NOT include any instruction text, warnings (🚨 CRITICAL), or meta-commentary in your output. Only output the actual content sections.

### MANDATORY SELECTION & COUNTS (CRITICAL - FOLLOW EXACTLY)
- **News**: Select ONLY high-quality, fresh articles (within 48 hours, specific content, substantial descriptions). If you have 8+ quality articles, select the best 10. If you have 5-7 quality articles, use all of them. If you have fewer than 5 quality articles, create a digest using available articles plus brief market context - DO NOT pad with low-quality or generic content. Each article must have a unique angle and substantial, specific information about Tesla.
- **CRITICAL URL RULE**: NEVER invent URLs. If you don't have enough pre-fetched articles, output fewer items rather than making up URLs. All URLs must be exact matches from the pre-fetched list above.
- **Diversity Check**: Before finalizing, verify no similar content; replace if needed from pre-fetched pool. Top 10 and Tesla X Takeover must have ZERO overlapping stories—each of the 5 Takeover items must be a different story from the 10 news items.

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
## Tesla X Takeover: What's Hot Right Now
🎙️ Tesla X Takeover - What's breaking in the Tesla world today! Here are the most interesting, fresh Tesla developments that have everyone talking.

1. 🚨 **[INCREDIBLE TITLE THAT HOOKS]** - [Breaking Tesla news or development]
   [Make it sound exciting and fresh - like you're sharing breaking Tesla news with friends. Include what happened, why it matters, and why Tesla investors should care. 2-3 sentences with personality and enthusiasm.]
   Source: [EXACT URL FROM PRE-FETCHED NEWS - if available]

2. 🔥 **[EXCITING TITLE]** - [Another fresh Tesla development or trend]
   [Make it conversational and engaging. Focus on what makes this story interesting, surprising, or important for Tesla's future. Include why this matters for Tesla investors.]

3. 💡 **[INSIGHTFUL TITLE]** - [Interesting Tesla trend or pattern]
   [Highlight what's unique or noteworthy about this development. Connect it to Tesla's bigger picture or long-term strategy.]

4. ⚡ **[ENERGETIC TITLE]** - [Surprising Tesla announcement or update]
   [Focus on what makes this development exciting or unexpected. Explain why this could be significant for Tesla's business or stock.]

5. 🎯 **[PRECISION TITLE]** - [Fresh Tesla story that stands out]
   [Show why this particular development is noteworthy and different from the usual news. Make it clear why Tesla fans and investors should pay attention.]

**The Vibe Check:** "Overall, the Tesla world is [BULLISH/BEARISH/MIXED] this week, with key themes around [Autopilot, energy, Cybertruck, manufacturing, etc.]. The most exciting developments are [specific trends or patterns], showing Tesla's momentum in [relevant area]."

━━━━━━━━━━━━━━━━━━━━
## Short Spot
One bearish item from pre-fetched news that's negative for Tesla/stock.
**Catchy Title: DD Month, YYYY, HH:MM AM/PM PST, @username/Source**
2–4 sentences explaining it & why it's temporary/overblown (frame optimistically). End with: Source/Post: [EXACT URL]

━━━━━━━━━━━━━━━━━━━━
### Tesla First Principles
🧠 Tesla First Principles - Cutting Through the Noise

Taking a step back from today's headlines, let's apply first principles thinking to [COMPLETELY DIFFERENT topic than recent days - choose something unrelated to recent analyses like battery tech, autonomous driving, manufacturing, energy storage, international expansion, regulatory challenges, supply chain, competition, or any other fundamental Tesla issue]...

**The Fundamental Question:** [Core question that actually matters for Tesla's long-term success]

**The Data Says:** [Factual analysis based on Tesla's actual numbers, physics, market realities - no hype]

**The Tesla Approach:** [How Tesla would actually solve this problem using their proven methodologies]

**The Market Implication:** [What this means for TSLA valuation and investor expectations - be realistic]

**The Long-Term Play:** [Why this matters for Tesla's mission to accelerate the world's transition to sustainable energy]
{market_movers_section}

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
- ✅ Tesla X Takeover section included with 5 fresh, interesting Tesla news developments or trends.
- ✅ Podcast link: Full URL as shown.
- ✅ Lists: "1. " format (number, period, space)—no bullets.
- ✅ Separators: "━━━━━━━━━━━━━━━━━━━━" before each major section.
- ✅ No duplicates: All items unique (review pairwise). Top 10 and Tesla X Takeover: no story overlap.
- ✅ All sections included: Tesla X Takeover, Short Spot, Tesla First Principles, Tesla Market Movers (Mondays only), Daily Challenge, Quote, sign-off.
- ✅ URLs: Exact from pre-fetched; valid format; no inventions.
- ✅ FRESHNESS CHECK: Short Spot is DIFFERENT from recent ones (different story/angle).
- ✅ FRESHNESS CHECK: Tesla First Principles uses COMPLETELY DIFFERENT topics/analysis than recent ones.
- ✅ FRESHNESS CHECK: Daily Challenge is COMPLETELY NEW and DIFFERENT from recent ones.
- ✅ FRESHNESS CHECK: Inspiration Quote is from a DIFFERENT author than recent quotes.
- If any fail, adjust selections and re-check.

Output today's edition exactly as formatted.
"""

logging.info("Generating X thread with Grok using pre-fetched content (this may take 1-2 minutes)...")

# Web search is available for the Tesla X Takeover section to find fresh, interesting Tesla developments
# For news items, we still use only pre-fetched content
enable_web_search = os.getenv("GROK_WEB_SEARCH", "1").strip().lower() not in ("0", "false", "no", "off")
if enable_web_search:
    logging.info("✅ Web search enabled for Tesla X Takeover section (Responses API tool: web_search)")
else:
    logging.info("ℹ️ Web search disabled for Grok (set GROK_WEB_SEARCH=1 to enable)")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=15),  # Reduced wait times: 1-15s instead of 2-30s
    retry=retry_if_exception_type((Exception,))
)
def generate_digest_with_grok():
    """Generate digest with retry logic"""
    input_payload = [
        {"role": "user", "content": [{"type": "input_text", "text": X_PROMPT}]},
    ]
    tools = [{"type": "web_search"}] if enable_web_search else None
    return _xai_responses_create(
        model="grok-4",
        input_payload=input_payload,
        tools=tools,
        temperature=0.7,
        max_output_tokens=3500,
        store=False,
        timeout_seconds=300.0,
    )

try:
    response = generate_digest_with_grok()
    x_thread = _extract_responses_text(response)
    
    # Log token usage and cost
    usage = _extract_responses_usage(response)
    if usage:
        prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
        completion_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
        total_tokens = usage.get("total_tokens")
        if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int) and not isinstance(total_tokens, int):
            total_tokens = prompt_tokens + completion_tokens

        if isinstance(total_tokens, int):
            logging.info(
                f"Grok API - Tokens used: {total_tokens} (prompt: {prompt_tokens}, completion: {completion_tokens})"
            )
            # Estimate cost (Grok pricing may vary, using approximate $0.01 per 1M tokens)
            estimated_cost = (total_tokens / 1000000) * 0.01
        else:
            estimated_cost = 0.0
        logging.info(f"Estimated cost: ${estimated_cost:.4f}")
        
        # Track credit usage
        if isinstance(prompt_tokens, int):
            credit_usage["services"]["grok_api"]["x_thread_generation"]["prompt_tokens"] = prompt_tokens
        if isinstance(completion_tokens, int):
            credit_usage["services"]["grok_api"]["x_thread_generation"]["completion_tokens"] = completion_tokens
        if isinstance(total_tokens, int):
            credit_usage["services"]["grok_api"]["x_thread_generation"]["total_tokens"] = total_tokens
        credit_usage["services"]["grok_api"]["x_thread_generation"]["estimated_cost_usd"] = estimated_cost
except PermissionDeniedError as e:
    # Check if this is a no credits/licenses issue
    error_str = str(e).lower()
    if "credit" in error_str or "license" in error_str or "doesn't have any" in error_str or "purchase" in error_str:
        logging.error("=" * 80)
        logging.error("❌ GROK API: NO CREDITS OR LICENSES")
        logging.error("=" * 80)
        logging.error("The X.AI (Grok) API team associated with this API key:")
        logging.error("  - Does not have any credits, OR")
        logging.error("  - Does not have any licenses")
        logging.error("")
        logging.error("To continue generating episodes:")
        logging.error("  1. Go to https://console.x.ai/ and sign in")
        logging.error("  2. Navigate to your team settings")
        logging.error("  3. Purchase credits or licenses for your team")
        logging.error("")
        # Try to extract team ID from error message if available
        if "team/" in str(e):
            import re
            team_match = re.search(r'team/([a-f0-9-]+)', str(e))
            if team_match:
                team_id = team_match.group(1)
                logging.error(f"  Direct link: https://console.x.ai/team/{team_id}")
        logging.error("")
        logging.error("The script will exit now. No episode will be generated.")
        logging.error("=" * 80)
        sys.exit(3)  # Exit code 3 for no credits/licenses (different from other errors)
    else:
        # Other permission error, log and re-raise
        logging.error(f"Grok API permission denied: {e}")
        logging.error("Check your API key permissions and team access.")
        raise
except RateLimitError as e:
    # Check if this is a credit/spending limit issue
    error_str = str(e).lower()
    if "credit" in error_str or "spending limit" in error_str or "exhausted" in error_str:
        logging.error("=" * 80)
        logging.error("❌ GROK API CREDITS EXHAUSTED")
        logging.error("=" * 80)
        logging.error("The X.AI (Grok) API team has either:")
        logging.error("  - Used all available credits, OR")
        logging.error("  - Reached the monthly spending limit")
        logging.error("")
        logging.error("To continue generating episodes:")
        logging.error("  1. Purchase more credits in your X.AI account")
        logging.error("  2. Raise your monthly spending limit")
        logging.error("")
        logging.error("The script will exit now. No episode will be generated.")
        logging.error("=" * 80)
        sys.exit(2)  # Exit code 2 for credit exhaustion (different from general errors)
    else:
        # Regular rate limit (temporary), log and re-raise
        logging.error(f"Grok API rate limit error: {e}")
        logging.error("This is a temporary rate limit. The script will retry, but if this persists, check your API usage.")
        raise
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

# Clean up any remaining instruction-like text in Tesla X Takeover section
x_thread = re.sub(r'(## Tesla X Takeover[^\n]*\n)[^\n]*(?:TODAY\'S FOCUS|must curate|Using your|For each)', r'\1', x_thread, flags=re.IGNORECASE | re.DOTALL)

# ========================== TESLA X TAKEOVER SECTION CLEANUP ==========================
# The Tesla X Takeover section now focuses on fresh Tesla news/trends instead of specific accounts
# No account-specific formatting needed

# Find and limit news items to exactly 10
news_pattern = r'(### Top 10 News Items.*?)(## Short Spot|### Tesla First Principles|━━)'
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
    # Format Tesla X Takeover section (now focuses on fresh news/trends, not specific accounts)
    formatted = re.sub(r'^## Tesla X Takeover:', '🎙️ **Tesla X Takeover:**', formatted, flags=re.MULTILINE)
    formatted = re.sub(r'^### Tesla X Takeover:', '🎙️ **Tesla X Takeover:**', formatted, flags=re.MULTILINE)
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
    
    # Add separator before Tesla X Takeover
    formatted = re.sub(r'(\n\n?)(🎙️ \*\*Tesla X Takeover)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n?)(## Tesla X Takeover|### Tesla X Takeover)', separator + r'\2', formatted)
    # Also match after last news item (10.)
    formatted = re.sub(r'(10[️⃣\.]\s+.*?\n)(🎙️|\*\*Tesla X Takeover|## Tesla X Takeover|### Tesla X Takeover)', separator + r'\2', formatted, flags=re.DOTALL)
    
    # X POSTS SEPARATOR DISABLED - No longer adding separator before X posts
    
    # Add separator before Short Spot
    formatted = re.sub(r'(\n\n?)(📉 \*\*Short Spot\*\*)', separator + r'\2', formatted)
    formatted = re.sub(r'(\n\n?)(## Short Spot)', separator + r'\2', formatted)
    # Also match after Tesla X Takeover section (vibe check)
    formatted = re.sub(r'(The Vibe Check.*?\n)(📉|\*\*Short Spot|## Short Spot)', separator + r'\2', formatted, flags=re.DOTALL)
    
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

if new_sections.get("first_principles"):
    content_tracker["first_principles"].append({
        "date": today_date,
        "content": new_sections["first_principles"][:500]
    })
    logging.info("Saved new First Principles to content tracker")

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
    # Rotate intro/outro daily (seed by date so same day = same choice)
    _podcast_seed = int(datetime.date.today().strftime("%Y%m%d"))
    _podcast_rng = random.Random(_podcast_seed)
    INTRO_TEMPLATES = [
        f'Patrick: Welcome back to Tesla Shorts Time Daily, episode {{episode_num}}. It\'s {{today_str}}, and I\'m Patrick in Vancouver, Canada. Let\'s talk about what really moved Tesla today.',
        f'Patrick: Hey, it\'s Patrick in Vancouver with Tesla Shorts Time Daily, episode {{episode_num}}. Today is {{today_str}}, and we\'ve got a fresh batch of Tesla stories to unpack together.',
        f'Patrick: This is Tesla Shorts Time Daily, episode {{episode_num}}. I\'m Patrick up in Vancouver, and it\'s {{today_str}}. Grab a coffee, and let\'s walk through what actually mattered for Tesla today.',
        f'Patrick: Good to have you here for Tesla Shorts Time Daily, episode {{episode_num}}. I\'m Patrick in Vancouver — it\'s {{today_str}}, and we\'re diving into the Tesla news that matters.',
        f'Patrick: Tesla Shorts Time Daily, episode {{episode_num}}. Patrick in Vancouver, {{today_str}}. Thanks for tuning in; here\'s what\'s going on with Tesla.',
        f'Patrick: Welcome to Tesla Shorts Time Daily, episode {{episode_num}}. It is {{today_str}}. I\'m Patrick in Vancouver, Canada bringing you the latest Tesla news and updates. If you like the show, like, share, rate and subscribe — it really helps. Now straight to the news.',
    ]
    CLOSING_TEMPLATES = [
        f'Patrick: TSLA is at ${{price:.2f}} as we record. Short term is fun to watch, but with Tesla the long term is what really matters.\nPatrick: That\'s Tesla Shorts Time Daily for today. I\'d love to hear your thoughts — reach out @teslashortstime on X or DM us. Stay safe, keep accelerating, and we\'ll catch you tomorrow.',
        f'Patrick: Current TSLA price at recording: ${{price:.2f}}. Good to know, but remember it\'s the long game that counts.\nPatrick: Thanks for listening to Tesla Shorts Time Daily. Hit us up @teslashortstime with feedback or ideas. Future is electric — talk to you next time.',
        f'Patrick: TSLA right now is ${{price:.2f}}. Always good to know the short term; with Tesla, the long term is what really matters.\nPatrick: That\'s it for today\'s Tesla Shorts Time Daily. I look forward to hearing from you — @teslashortstime on X or DM. Stay safe, keep accelerating, and we\'ll catch you tomorrow.',
        f'Patrick: At the time of recording, TSLA is ${{price:.2f}}. Pace yourself — long term is what matters.\nPatrick: Thanks for spending a few minutes with me. DM @teslashortstime with thoughts or ideas. Your efforts help accelerate the transition to sustainable energy. We\'ll catch you tomorrow on Tesla Shorts Time Daily.',
        f'Patrick: TSLA at ${{price:.2f}} as we wrap. Short term is noisy; the long term is why we\'re here.\nPatrick: That\'s Tesla Shorts Time Daily for today. Reach out @teslashortstime — I\'d love to hear what you\'re seeing. Take care, and we\'ll talk again tomorrow.',
    ]
    _intro_line = _podcast_rng.choice(INTRO_TEMPLATES).format(episode_num=episode_num, today_str=today_str)
    _closing_block = _podcast_rng.choice(CLOSING_TEMPLATES).format(price=price)

    # Tone hint so script matches the day (not always max enthusiasm)
    if change > 3:
        tone_hint = "strongly bullish — okay to sound more excited"
    elif change > 0.5:
        tone_hint = "slightly bullish — warm and positive"
    elif change < -3:
        tone_hint = "rough/red day — be grounded, reflective, honest; don't fake hype"
    elif change < -0.5:
        tone_hint = "slightly bearish — thoughtful, no forced enthusiasm"
    else:
        tone_hint = "mixed/unchanged — natural and conversational"

    # Podcast prompt: guidelines + rotated intro/outro for variety
    POD_PROMPT = f"""You are writing an 8–11 minute (1950–2600 words) solo podcast script for "Tesla Shorts Time Daily" Episode {episode_num}.

HOST: Patrick in Vancouver — Canadian, scientist, newscaster. Sound like a real person catching a friend up on Tesla, not a robotic announcer.

RULES:
- Start every line with "Patrick:"
- Don't read URLs aloud — mention source names naturally
- Use natural dates ("today", "this morning") not exact timestamps
- Enunciate all numbers, dollar amounts, percentages clearly
- Use ONLY information from the digest below — nothing else

TONE (vary by the day):
- Match your energy to the news and TSLA move today: {tone_hint}.
- Vary sentence length and pacing; some moments can be calm or thoughtful, not always high-energy.
- Sound warm and human — occasionally excited, occasionally reflective — never mechanical.

SCRIPT STRUCTURE:
[Intro music - 5–10 seconds]
Use this exact intro (do not rewrite it):
{_intro_line}

[Narrate EVERY item from the digest in order - no skipping]
- For each news item: Read the title naturally, then paraphrase the summary in your own words. Vary delivery — not every item needs the same level of enthusiasm.
- Tesla X Takeover: Introduce the section in your own words. Cover each item clearly; explain why it matters for Tesla investors. End with the vibe check in a natural way.
- Short Spot: Explain the bearish concern and why it's temporary or overblown — tone can be more measured here.
- Tesla First Principles: Explain the fundamental question, data, Tesla approach, and market implications. Educational but engaging; no need to oversell.
- Tesla Market Movers (Mondays only): Recap the week's Tesla market activity and what moved TSLA.
- Daily Challenge + Quote: Read the quote verbatim, then the challenge verbatim, add one short encouraging sentence.

[Closing]
Use this exact closing (do not rewrite it):
{_closing_block}

Here is today's complete formatted digest. Use ONLY this content:
"""

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=15),  # Reduced wait times: 1-15s instead of 2-30s
        retry=retry_if_exception_type((Exception,))
    )
    def generate_podcast_script_with_grok():
        """Generate podcast script with retry logic"""
        input_payload = [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": "You are the world's best Tesla podcast writer. Make it feel like a real Canadian friend catching you up on Tesla: warm, honest, occasionally excited, occasionally thoughtful — never robotic or like an AI reading a script.",
                    }
                ],
            },
            {"role": "user", "content": [{"type": "input_text", "text": f"{POD_PROMPT}\n\n{x_thread}"}]},
        ]
        return _xai_responses_create(
            model="grok-4",
            input_payload=input_payload,
            tools=None,
            temperature=0.9,  # higher = more natural energy
            max_output_tokens=3500,
            store=False,
            timeout_seconds=300.0,
        )
    
    logging.info("Generating podcast script with Grok (this may take 1-2 minutes)...")
    try:
        # Use only the final formatted digest - much simpler and more reliable
        podcast_response = generate_podcast_script_with_grok()
        podcast_script = _extract_responses_text(podcast_response)
        
        # Log token usage if available
        usage = _extract_responses_usage(podcast_response)
        if usage:
            prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
            completion_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
            total_tokens = usage.get("total_tokens")
            if isinstance(prompt_tokens, int) and isinstance(completion_tokens, int) and not isinstance(total_tokens, int):
                total_tokens = prompt_tokens + completion_tokens

            if isinstance(total_tokens, int):
                logging.info(
                    f"Podcast script generation - Tokens used: {total_tokens} (prompt: {prompt_tokens}, completion: {completion_tokens})"
                )
                # Estimate cost (Grok pricing may vary, using approximate)
                estimated_cost = (total_tokens / 1000000) * 0.01  # Rough estimate
            else:
                estimated_cost = 0.0
            logging.info(f"Estimated cost: ${estimated_cost:.4f}")
            
            # Track credit usage
            if isinstance(prompt_tokens, int):
                credit_usage["services"]["grok_api"]["podcast_script_generation"]["prompt_tokens"] = prompt_tokens
            if isinstance(completion_tokens, int):
                credit_usage["services"]["grok_api"]["podcast_script_generation"]["completion_tokens"] = completion_tokens
            if isinstance(total_tokens, int):
                credit_usage["services"]["grok_api"]["podcast_script_generation"]["total_tokens"] = total_tokens
            credit_usage["services"]["grok_api"]["podcast_script_generation"]["estimated_cost_usd"] = estimated_cost
    except PermissionDeniedError as e:
        # Check if this is a no credits/licenses issue
        error_str = str(e).lower()
        if "credit" in error_str or "license" in error_str or "doesn't have any" in error_str or "purchase" in error_str:
            logging.error("=" * 80)
            logging.error("❌ GROK API: NO CREDITS OR LICENSES (during podcast script generation)")
            logging.error("=" * 80)
            logging.error("The X.AI (Grok) API team associated with this API key:")
            logging.error("  - Does not have any credits, OR")
            logging.error("  - Does not have any licenses")
            logging.error("")
            logging.error("To continue generating episodes:")
            logging.error("  1. Go to https://console.x.ai/ and sign in")
            logging.error("  2. Navigate to your team settings")
            logging.error("  3. Purchase credits or licenses for your team")
            logging.error("")
            # Try to extract team ID from error message if available
            if "team/" in str(e):
                import re
                team_match = re.search(r'team/([a-f0-9-]+)', str(e))
                if team_match:
                    team_id = team_match.group(1)
                    logging.error(f"  Direct link: https://console.x.ai/team/{team_id}")
            logging.error("")
            logging.error("The script will exit now. No episode will be generated.")
            logging.error("=" * 80)
            sys.exit(3)  # Exit code 3 for no credits/licenses (different from other errors)
        else:
            # Other permission error, log and re-raise
            logging.error(f"Grok API permission denied (podcast script): {e}")
            logging.error("Check your API key permissions and team access.")
            raise
    except RateLimitError as e:
        # Check if this is a credit/spending limit issue
        error_str = str(e).lower()
        if "credit" in error_str or "spending limit" in error_str or "exhausted" in error_str:
            logging.error("=" * 80)
            logging.error("❌ GROK API CREDITS EXHAUSTED (during podcast script generation)")
            logging.error("=" * 80)
            logging.error("The X.AI (Grok) API team has either:")
            logging.error("  - Used all available credits, OR")
            logging.error("  - Reached the monthly spending limit")
            logging.error("")
            logging.error("To continue generating episodes:")
            logging.error("  1. Purchase more credits in your X.AI account")
            logging.error("  2. Raise your monthly spending limit")
            logging.error("")
            logging.error("The script will exit now. No episode will be generated.")
            logging.error("=" * 80)
            sys.exit(2)  # Exit code 2 for credit exhaustion (different from general errors)
        else:
            # Regular rate limit (temporary), log and re-raise
            logging.error(f"Grok API rate limit error (podcast script): {e}")
            logging.error("This is a temporary rate limit. The script will retry, but if this persists, check your API usage.")
            raise
    except Exception as e:
        logging.error(f"Grok API call for podcast script failed: {e}")
        logging.error("This might be due to network issues or API timeout. Please try again.")
        raise

    # Save transcript
    transcript_path = digests_dir / f"podcast_transcript_{datetime.date.today():%Y%m%d}.txt"
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(f"# Tesla Shorts Time – The Pod | Ep {episode_num} | {today_str}\n\n{podcast_script}")
    logging.info("Podcast script generated with varied intro/outro and tone")

    # ========================== 3. TTS (VOICE) ==========================

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
    # get_audio_duration and format_duration imported from engine/
    format_duration = _engine_format_duration

    # Extract text from podcast script (remove "Patrick:" prefixes and stage directions)
    full_text_parts = []
    for line in podcast_script.splitlines():
        line = line.strip()
        if line.startswith("[") or not line:
            continue
        # Prevent accidental footer/debug metadata from being spoken by TTS
        # (e.g., Grok sometimes appends "Word count: ..." or "Content:" at the end)
        if re.match(r'(?i)^(word\s*count|total\s*words|character\s*count)\b', line):
            break
        if re.match(r'(?i)^content\s*:\s*$', line):
            break
        # Drop obvious markdown artifacts that can get read aloud ("asterisk", "underscore", etc.)
        if line in {"**", "*", "__", "—", "–"}:
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
        logging.error(f"ERROR: Extracted text is too short ({len(full_text)} chars). This will result in a very short podcast!")
        logging.error(f"First 1000 chars of extracted text: {full_text[:1000]}")
        raise RuntimeError(f"Podcast script is too short ({len(full_text)} chars) - expected at least 500 characters")
    
    # Estimate expected duration (roughly 20 chars per second of speech)
    estimated_duration = len(full_text) / 20
    logging.info(f"Estimated podcast duration: ~{estimated_duration:.1f} seconds ({estimated_duration/60:.1f} minutes)")
    
    full_text = fix_tesla_pronunciation(full_text)

    # Track character count (used for reporting; cost is provider-dependent)
    credit_usage["services"]["elevenlabs_api"]["characters"] = len(full_text)
    logging.info(f"TTS: {len(full_text)} characters to synthesize (ElevenLabs)")

    # Generate voice file
    import time
    tts_start_time = time.time()
    try:
        logging.info("Generating voice track with ElevenLabs (Patrick voice)...")
        validate_elevenlabs_auth()
        voice_file = tmp_dir / "patrick_full.mp3"
        speak(full_text, PATRICK_VOICE_ID, str(voice_file))
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

    except Exception as e:
        logging.error(f"ElevenLabs TTS generation failed: {e}", exc_info=True)
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
        # - End: Keep the final spoken lines clean (no music under them)
        # - After voice ends, fade in and play 30 seconds of outro music (no overlap with voice)
        
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
            # Outro is positioned after the voice ends by adding silence in the music bed.
            # Use stream_loop so even shorter music beds still produce a full 30s outro.
            ("outro", ["ffmpeg", "-y", "-threads", "0", "-stream_loop", "-1", "-i", str(MAIN_MUSIC), "-t", "30",
                      "-af", "volume=0.4,afade=t=in:curve=log:st=0:d=2,afade=t=out:curve=log:st=27:d=3", "-ar", "44100", "-ac", "2", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
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
        
        # Generate voice-dependent segments (silence depends on voice_duration)
        # Keep music silent after 26s until the voice fully ends, so the closing isn't masked/cut off.
        middle_silence_duration = max(voice_duration - 26.0, 0.0)
        music_silence = tmp_dir / "music_silence.mp3"
        
        voice_dependent_segments = []
        if middle_silence_duration > 0.1:
            voice_dependent_segments.append(("silence", ["ffmpeg", "-y", "-threads", "0", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                                                        "-t", str(middle_silence_duration), "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
                                                        str(music_silence)]))
        
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
            # Use duration=longest so the outro music remains after the voice ends.
            "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=2",
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
    """Scan digests directory for all existing MP3 files and return episode data.
    Handles both old format (without timestamp) and new format (with timestamp).
    Also checks digests/digests subdirectory for older episodes."""
    episodes = []
    # Pattern for new format: Ep{num}_{date}_{time}.mp3
    pattern_new = r"Tesla_Shorts_Time_Pod_Ep(\d+)_(\d{8})_(\d{6})\.mp3"
    # Pattern for old format: Ep{num}_{date}.mp3
    pattern_old = r"Tesla_Shorts_Time_Pod_Ep(\d+)_(\d{8})\.mp3"
    
    # Check main digests directory
    mp3_files = list(digests_dir.glob("Tesla_Shorts_Time_Pod_Ep*.mp3"))
    # Also check digests/digests subdirectory if it exists
    digests_subdir = digests_dir / "digests"
    if digests_subdir.exists():
        mp3_files.extend(digests_subdir.glob("Tesla_Shorts_Time_Pod_Ep*.mp3"))
    
    for mp3_file in mp3_files:
        # Verify file actually exists and has content
        if not mp3_file.exists() or mp3_file.stat().st_size < 1000:
            logging.warning(f"Skipping {mp3_file.name}: file doesn't exist or is too small")
            continue
            
        match = re.match(pattern_new, mp3_file.name)
        if match:
            # New format with timestamp
            episode_num = int(match.group(1))
            date_str = match.group(2)
            time_str = match.group(3)
            try:
                episode_date = datetime.datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S").date()
                episode_guid = f"tesla-shorts-time-ep{episode_num:03d}-{date_str}-{time_str}"
            except Exception as e:
                logging.warning(f"Could not parse date/time from {mp3_file.name}: {e}")
                continue
        else:
            # Try old format without timestamp
            match = re.match(pattern_old, mp3_file.name)
            if match:
                episode_num = int(match.group(1))
                date_str = match.group(2)
                try:
                    episode_date = datetime.datetime.strptime(date_str, "%Y%m%d").date()
                    # Use file modification time for old format
                    mtime = datetime.datetime.fromtimestamp(mp3_file.stat().st_mtime)
                    time_str = mtime.strftime("%H%M%S")
                    episode_guid = f"tesla-shorts-time-ep{episode_num:03d}-{date_str}-{time_str}"
                except Exception as e:
                    logging.warning(f"Could not parse date from {mp3_file.name}: {e}")
                    continue
            else:
                logging.warning(f"Could not match pattern for {mp3_file.name}")
                continue
        
        try:
            mp3_duration = get_audio_duration(mp3_file)
            episode_title = f"Tesla Shorts Time Daily - Episode {episode_num} - {episode_date.strftime('%B %d, %Y')}"
            
            # Generate correct URL path (handle subdirectories)
            if digests_subdir.exists() and mp3_file.is_relative_to(digests_subdir):
                # File is in digests/digests subdirectory
                url_path = f"{base_url}/digests/digests/{mp3_file.name}"
            else:
                # File is in main digests directory
                url_path = f"{base_url}/digests/{mp3_file.name}"
            
            episodes.append({
                'guid': episode_guid,
                'title': episode_title,
                'description': f"Daily Tesla news digest for {episode_date.strftime('%B %d, %Y')}.",
                'link': url_path,
                'pubDate': datetime.datetime.combine(episode_date, datetime.time(8, 0, 0), tzinfo=datetime.timezone.utc),
                'enclosure': {
                    'url': url_path,
                    'type': 'audio/mpeg',
                    'length': str(mp3_file.stat().st_size)
                },
                'itunes_title': episode_title,
                'itunes_summary': f"Daily Tesla news digest for {episode_date.strftime('%B %d, %Y')}.",
                'itunes_duration': format_duration(mp3_duration),
                'itunes_episode': str(episode_num),
                'itunes_season': '1',
                'itunes_episode_type': 'full',
                'itunes_image': f"{base_url}/podcast-image-v3.jpg",
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
                            link_url = elem.text or ''
                            # Fix double /digests/digests/ path errors
                            if '/digests/digests/' in link_url:
                                link_url = link_url.replace('/digests/digests/', '/digests/')
                            # Also ensure link doesn't point to MP3 (should point to episode page or GitHub)
                            if link_url.endswith('.mp3'):
                                # Extract filename and create proper link
                                filename = link_url.split('/')[-1]
                                link_url = f"{base_url}/digests/{filename}"
                            episode_data['link'] = link_url
                        elif elem.tag == 'guid':
                            # GUID is typically the text content
                            if elem.text:
                                episode_data['guid'] = elem.text.strip()
                            # Some feeds might use guid as an attribute, but we'll use text primarily
                        elif elem.tag == 'pubDate':
                            episode_data['pubDate'] = elem.text or ''
                        elif elem.tag == 'enclosure':
                            enclosure_url = elem.get('url', '')
                            # Fix double /digests/digests/ path errors
                            if '/digests/digests/' in enclosure_url:
                                enclosure_url = enclosure_url.replace('/digests/digests/', '/digests/')
                            episode_data['enclosure'] = {
                                'url': enclosure_url,
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
    
    # Set channel metadata - ALWAYS use general descriptions, never episode-specific data
    # This is critical for Apple Podcasts Connect validation
    channel_title = "Tesla Shorts Time Daily"
    channel_link = "https://github.com/patricknovak/Tesla-shorts-time"
    channel_description = "A daily podcast covering the latest Tesla news, stock prices, and industry insights."
    channel_summary = "Daily Tesla news digest and podcast covering the latest developments, stock updates, and market analysis."
    
    # Only use existing metadata if it's NOT episode-specific (check for episode numbers or dates)
    existing_title = channel_metadata.get('title', '')
    if existing_title and not re.search(r'Episode \d+|December|November|January|February|March|April|May|June|July|August|September|October', existing_title, re.IGNORECASE):
        channel_title = existing_title
    
    existing_link = channel_metadata.get('link', '')
    if existing_link and not existing_link.endswith('.mp3') and 'github.com' in existing_link:
        channel_link = existing_link
    
    existing_desc = channel_metadata.get('description', '')
    if existing_desc and not re.search(r'Episode \d+|December|November|January|February|March|April|May|June|July|August|September|October|TSLA price', existing_desc, re.IGNORECASE):
        channel_description = existing_desc
    
    existing_summary = channel_metadata.get('itunes_summary', '')
    if existing_summary and not re.search(r'Episode \d+|December|November|January|February|March|April|May|June|July|August|September|October|TSLA price', existing_summary, re.IGNORECASE):
        channel_summary = existing_summary
    
    fg.title(channel_title)
    fg.link(href=channel_link)
    fg.description(channel_description)
    fg.language(channel_metadata.get('language', 'en-us'))
    fg.copyright(channel_metadata.get('copyright', f"Copyright {datetime.date.today().year}"))
    
    # RSS feed URL for atom:link (will be added manually after feed generation)
    rss_feed_url = f"{base_url}/podcast.rss"
    
    fg.podcast.itunes_author(channel_metadata.get('itunes_author', "Patrick"))
    fg.podcast.itunes_summary(channel_summary)
    
    owner = channel_metadata.get('itunes_owner', {'name': 'Patrick', 'email': 'contact@teslashortstime.com'})
    fg.podcast.itunes_owner(name=owner.get('name', 'Patrick'), email=owner.get('email', 'contact@teslashortstime.com'))
    
    # Set image URL - use compressed v3 (under 512 KB) for Apple Podcasts compliance
    # Note: Image must be compressed to under 512 KB (current v2 is 752 KB, exceeds limit)
    # When podcast-image-v3.jpg (compressed) is uploaded, it will be used automatically
    image_url = channel_metadata.get('itunes_image', f"{base_url}/podcast-image-v3.jpg")
    fg.podcast.itunes_image(image_url)
    
    category = channel_metadata.get('itunes_category', 'Technology')
    # Add main category (subcategory will be added manually after feed generation)
    fg.podcast.itunes_category(category)
    fg.podcast.itunes_explicit("no")
    
    # Add itunes:type tag (required/recommended by Apple)
    fg.podcast.itunes_type("episodic")
    
    # Add itunes:subtitle for better Apple Podcasts display
    fg.podcast.itunes_subtitle("Your daily Tesla news and stock digest")
    
    # Generate GUID for the new episode based on current time to ensure uniqueness
    current_time_str = datetime.datetime.now().strftime("%H%M%S")
    new_episode_guid = f"tesla-shorts-time-ep{episode_num:03d}-{episode_date:%Y%m%d}-{current_time_str}"
    
    # Deduplicate existing episodes by episode number AND by date
    # Strategy: Keep only the highest episode number per date to remove duplicates
    episodes_by_number = {}  # For deduplication by episode number
    episodes_by_date = {}  # For deduplication by date (keep highest episode number per date)
    episodes_without_number = []  # Keep episodes that don't have extractable episode numbers
    
    def parse_pubdate(ep_data):
        """Parse pubDate from episode data and return as datetime or None."""
        pub_date_str = ep_data.get('pubDate', '')
        if not pub_date_str:
            return None
        try:
            if isinstance(pub_date_str, datetime.datetime):
                return pub_date_str
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(pub_date_str)
        except Exception:
            return None
    
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
                # Parse pubDate for date-based deduplication
                pub_date = parse_pubdate(ep_data)
                date_key = pub_date.date() if pub_date else None
                
                # Deduplicate by episode number (keep most recent GUID timestamp)
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
                
                # Deduplicate by date (keep highest episode number per date)
                if date_key:
                    if date_key not in episodes_by_date:
                        episodes_by_date[date_key] = ep_data
                    else:
                        # Extract episode number from existing episode
                        existing_ep_num_str = episodes_by_date[date_key].get('itunes_episode', '')
                        if not existing_ep_num_str:
                            existing_guid = episodes_by_date[date_key].get('guid', '')
                            match = re.search(r'ep(\d+)', existing_guid)
                            if match:
                                existing_ep_num_str = match.group(1)
                        existing_ep_num = int(existing_ep_num_str) if existing_ep_num_str else 0
                        # Keep the episode with the higher episode number
                        if ep_num > existing_ep_num:
                            episodes_by_date[date_key] = ep_data
            except ValueError:
                # If we can't parse episode number, keep the episode anyway (shouldn't happen normally)
                episodes_without_number.append(ep_data)
        else:
            # Episode without extractable episode number - keep it (shouldn't happen normally)
            episodes_without_number.append(ep_data)
    
    # Final deduplication: Use date-based deduplication as primary, but ensure we keep unique episode numbers
    # Build final list: prefer date-based deduplication, but include all unique episode numbers
    final_episodes = {}
    for date_key, ep_data in episodes_by_date.items():
        ep_num_str = ep_data.get('itunes_episode', '')
        if not ep_num_str:
            guid = ep_data.get('guid', '')
            match = re.search(r'ep(\d+)', guid)
            if match:
                ep_num_str = match.group(1)
        if ep_num_str:
            final_episodes[int(ep_num_str)] = ep_data
    
    # Also add episodes that might have been missed (episodes without date matches but with unique numbers)
    for ep_num, ep_data in episodes_by_number.items():
        if ep_num not in final_episodes:
            final_episodes[ep_num] = ep_data
    
    # Prepare all episodes for sorting (including new episode)
    all_episodes_to_add = []
    
    # Helper function to add an episode entry to the feed
    def add_episode_entry(ep_data, is_new_episode=False):
        """Add an episode entry to the feed generator."""
        entry = fg.add_entry()
        entry.id(ep_data.get('guid', ''))
        entry.title(ep_data.get('title', ''))
        entry.description(ep_data.get('description', ''))
        if ep_data.get('link'):
            entry.link(href=ep_data['link'])
        
        # Parse and set pubDate
        pub_date_dt = None
        if ep_data.get('pubDate'):
            try:
                # Handle both string dates (from RSS) and datetime objects (from file scan)
                if isinstance(ep_data['pubDate'], datetime.datetime):
                    pub_date_dt = ep_data['pubDate']
                    entry.pubDate(pub_date_dt)
                else:
                    from email.utils import parsedate_to_datetime
                    pub_date_dt = parsedate_to_datetime(ep_data['pubDate'])
                    entry.pubDate(pub_date_dt)
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
        episode_image = ep_data.get('itunes_image', image_url)
        entry.podcast.itunes_image(episode_image)
        
        return pub_date_dt
    
    # Collect all episodes to add (existing + new), then sort by pubDate descending
    episodes_to_add = []
    
    # Add all existing episodes (now deduplicated), but skip if same episode number as new episode
    for ep_data in final_episodes.values():
        # Extract episode number to check against new episode
        ep_num_str = ep_data.get('itunes_episode', '')
        if not ep_num_str:
            guid = ep_data.get('guid', '')
            match = re.search(r'ep(\d+)', guid)
            if match:
                ep_num_str = match.group(1)
        
        # Skip if this existing episode has the same episode number as the new one we're about to add
        if ep_num_str and int(ep_num_str) == episode_num:
            logging.info(f"Skipping existing episode {ep_num_str} - will be replaced with new version")
            continue
        
        # Skip if exact same GUID
        if ep_data.get('guid') == new_episode_guid:
            continue
        
        # Verify the MP3 file actually exists before including in RSS
        enclosure = ep_data.get('enclosure', {})
        enclosure_url = enclosure.get('url', '') if isinstance(enclosure, dict) else ''
        if enclosure_url:
            # Extract filename from URL
            filename = enclosure_url.split('/')[-1]
            # Check main directory first
            mp3_path_check = digests_dir / filename
            # Also check subdirectory if main doesn't exist
            if not mp3_path_check.exists():
                mp3_path_check = digests_dir / "digests" / filename
            if not mp3_path_check.exists() or mp3_path_check.stat().st_size < 1000:
                ep_num_str = ep_data.get('itunes_episode', 'unknown')
                logging.warning(f"Skipping episode {ep_num_str}: MP3 file {filename} doesn't exist or is too small")
                continue
        
        episodes_to_add.append(ep_data)
    
    # Also add episodes without extractable episode numbers to the list (will be sorted with others)
    for ep_data in episodes_without_number:
        # Skip if exact same GUID
        if ep_data.get('guid') == new_episode_guid:
            continue
        
        # Verify the MP3 file actually exists before including in RSS
        enclosure = ep_data.get('enclosure', {})
        enclosure_url = enclosure.get('url', '') if isinstance(enclosure, dict) else ''
        if enclosure_url:
            # Extract filename from URL
            filename = enclosure_url.split('/')[-1]
            # Check main directory first
            mp3_path_check = digests_dir / filename
            # Also check subdirectory if main doesn't exist
            if not mp3_path_check.exists():
                mp3_path_check = digests_dir / "digests" / filename
            if not mp3_path_check.exists() or mp3_path_check.stat().st_size < 1000:
                logging.warning(f"Skipping episode (no number): MP3 file {filename} doesn't exist or is too small")
                continue
        
        episodes_to_add.append(ep_data)
    
    # Prepare new episode data
    pub_date = datetime.datetime.combine(episode_date, datetime.time(8, 0, 0), tzinfo=datetime.timezone.utc)
    mp3_url = f"{base_url}/digests/{mp3_filename}"
    mp3_size = mp3_path.stat().st_size if mp3_path.exists() else 0
    
    new_episode_data = {
        'guid': new_episode_guid,
        'title': episode_title,
        'description': episode_description,
        'link': f"{base_url}/digests/{mp3_filename}",
        'pubDate': pub_date,
        'enclosure': {
            'url': mp3_url,
            'type': 'audio/mpeg',
            'length': str(mp3_size)
        },
        'itunes_title': episode_title,
        'itunes_summary': episode_description,
        'itunes_duration': format_duration(mp3_duration),
        'itunes_episode': str(episode_num),
        'itunes_season': '1',
        'itunes_episode_type': 'full',
        'itunes_image': image_url
    }
    
    # Add new episode to the list
    episodes_to_add.append(new_episode_data)
    
    # Sort all episodes by pubDate descending (newest first)
    def get_pubdate_for_sort(ep_data):
        """Extract pubDate as datetime for sorting."""
        pub_date = ep_data.get('pubDate')
        if isinstance(pub_date, datetime.datetime):
            return pub_date
        if isinstance(pub_date, str):
            try:
                from email.utils import parsedate_to_datetime
                return parsedate_to_datetime(pub_date)
            except Exception:
                pass
        # Fallback to very old date if can't parse
        return datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    
    episodes_to_add.sort(key=get_pubdate_for_sort, reverse=True)
    
    logging.info(f"Sorting {len(episodes_to_add)} episodes by pubDate descending (newest first)")
    
    # Now add all episodes in sorted order
    for ep_data in episodes_to_add:
        add_episode_entry(ep_data, is_new_episode=(ep_data.get('guid') == new_episode_guid))
    
    # Update lastBuildDate
    fg.lastBuildDate(datetime.datetime.now(datetime.timezone.utc))
    
    # Write RSS feed
    fg.rss_file(str(rss_path), pretty=True)
    
    # Manually add atom:link for self-reference (required by Apple Podcasts Connect)
    # FeedGenerator doesn't have a direct method for this, so we add it via XML manipulation
    try:
        tree = ET.parse(str(rss_path))
        root = tree.getroot()
        channel = root.find('channel')
        if channel is not None:
            # Check if atom:link already exists
            atom_ns = '{http://www.w3.org/2005/Atom}'
            existing_atom_link = channel.find(f'{atom_ns}link')
            if existing_atom_link is None:
                # Add atom:link element
                atom_link = ET.Element(f'{atom_ns}link')
                atom_link.set('href', rss_feed_url)
                atom_link.set('rel', 'self')
                atom_link.set('type', 'application/rss+xml')
                # Insert after <link> or at the beginning of channel
                first_link = channel.find('link')
                if first_link is not None:
                    channel.insert(list(channel).index(first_link) + 1, atom_link)
                else:
                    channel.insert(0, atom_link)
                tree.write(str(rss_path), encoding='UTF-8', xml_declaration=True)
                logging.info("Added atom:link for self-reference to RSS feed")
                
                # Also add itunes:subtitle and category subcategory if not present
                itunes_ns = '{http://www.itunes.com/dtds/podcast-1.0.dtd}'
                
                # Add itunes:subtitle if not present
                existing_subtitle = channel.find(f'{itunes_ns}subtitle')
                if existing_subtitle is None:
                    subtitle = ET.Element(f'{itunes_ns}subtitle')
                    subtitle.text = "Your daily Tesla news and stock digest"
                    # Insert after itunes:summary
                    summary = channel.find(f'{itunes_ns}summary')
                    if summary is not None:
                        channel.insert(list(channel).index(summary) + 1, subtitle)
                    else:
                        channel.append(subtitle)
                    logging.info("Added itunes:subtitle to RSS feed")
                
                # Add subcategory to existing category if not present
                category_elem = channel.find(f'{itunes_ns}category')
                if category_elem is not None and category_elem.get('text') == 'Technology':
                    # Check if subcategory already exists
                    subcategory = category_elem.find(f'{itunes_ns}category')
                    if subcategory is None:
                        subcategory = ET.Element(f'{itunes_ns}category')
                        subcategory.set('text', 'Tech News')
                        category_elem.append(subcategory)
                        logging.info("Added Tech News subcategory to RSS feed")
                
                # Update all image URLs to use compressed v3 (if v2 is still referenced)
                channel_image = channel.find(f'{itunes_ns}image')
                if channel_image is not None and 'podcast-image-v2.jpg' in channel_image.get('href', ''):
                    channel_image.set('href', channel_image.get('href', '').replace('podcast-image-v2.jpg', 'podcast-image-v3.jpg'))
                    logging.info("Updated channel image URL to podcast-image-v3.jpg")
                
                # Update episode image URLs
                items = channel.findall('item')
                updated_count = 0
                for item in items:
                    item_image = item.find(f'{itunes_ns}image')
                    if item_image is not None and 'podcast-image-v2.jpg' in item_image.get('href', ''):
                        item_image.set('href', item_image.get('href', '').replace('podcast-image-v2.jpg', 'podcast-image-v3.jpg'))
                        updated_count += 1
                if updated_count > 0:
                    logging.info(f"Updated {updated_count} episode image URLs to podcast-image-v3.jpg")
                
                tree.write(str(rss_path), encoding='UTF-8', xml_declaration=True)
    except Exception as e:
        logging.warning(f"Could not add enhancements to RSS feed: {e}")
    
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
        # Use v3 if available (compressed), fallback to v2
        base_image_path = project_root / "podcast-image-v3.jpg"
        if not base_image_path.exists():
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

# Save summary to GitHub Pages and post link to X
if ENABLE_GITHUB_SUMMARIES:
    try:
        # Save the full summary to GitHub Pages JSON
        _base_url = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"
        _audio_url = None
        try:
            if ENABLE_PODCAST and final_mp3:
                _audio_url = f"{_base_url}/digests/{final_mp3.name}"
        except Exception:
            _audio_url = None

        summary_json_file = save_summary_to_github_pages(
            x_thread.strip(),
            digests_dir,
            "tesla",
            episode_num=episode_num if 'episode_num' in globals() else None,
            episode_title=episode_title if 'episode_title' in globals() else None,
            audio_url=_audio_url,
            rss_url=f"{_base_url}/podcast.rss",
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
        # Create link to the Tesla summaries page
        summaries_url = "https://patricknovak.github.io/Tesla-shorts-time/tesla-summaries.html"

        # Create a teaser post with link to full summary
        today = datetime.datetime.now()
        teaser_text = f"""🚗⚡ Tesla Shorts Time Daily - {today.strftime('%B %d, %Y')}

🔥 Today's complete digest is now live on our website!

📈 TSLA news, stock analysis, and market insights
🎙️ Full podcast episode available
📊 Raw data and sources included

Read the full summary: {summaries_url}

#Tesla #TSLA #TeslaShortsTime #EV"""

        # Track X API post call
        credit_usage["services"]["x_api"]["post_calls"] += 1

        # Post the teaser with link
        tweet = x_client.create_tweet(text=teaser_text)
        tweet_id = tweet.data['id']
        thread_url = f"https://x.com/teslashortstime/status/{tweet_id}"
        logging.info(f"DIGEST LINK POSTED → {thread_url}")
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