#!/usr/bin/env python3
"""
Tesla Shorts Time – FULL AUTO X + PODCAST MACHINE
X Thread + Daily Podcast (Patrick in Vancouver)
Auto-published to X — November 19, 2025+

.. deprecated::
    This legacy script is no longer used in production.
    All shows now run via ``python run_show.py tesla``.
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
from engine.audio import get_audio_duration, format_duration as _engine_format_duration, mix_with_music as _engine_mix_with_music, normalize_voice as _engine_normalize_voice
from engine.publisher import (
    update_rss_feed as _engine_update_rss_feed,
    get_next_episode_number as _engine_get_next_episode_number,
    save_summary_to_github_pages as _engine_save_summary,
    generate_episode_thumbnail as _engine_generate_thumbnail,
    format_tst_digest_for_x as _engine_format_tst_digest_for_x,
    post_to_x as _engine_post_to_x,
    scan_existing_episodes_from_files as _engine_scan_episodes,
)
from engine.tracking import create_tracker, record_llm_usage, record_tts_usage, record_x_post, save_usage
from engine.content_tracker import ContentTracker, TST_SECTION_PATTERNS
from engine.utils import deduplicate_by_entity

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
# Defaults (overridable via environment variables)
TEST_MODE = False
ENABLE_X_POSTING = True
ENABLE_PODCAST = True
ENABLE_GITHUB_SUMMARIES = True
ENABLE_LINK_VALIDATION = False

# Shared HTTP defaults
DEFAULT_HEADERS = {
    "User-Agent": "TeslaShortsTimeBot/1.0 (+https://x.com/teslashortstime)"
}
HTTP_TIMEOUT_SECONDS = 10


# ========================== NUMBER TO WORDS CONVERTER ==========================
number_to_words = _engine_number_to_words

# ========================== PRONUNCIATION FIXER – USING SHARED MODULE ==========================

def fix_tesla_pronunciation(text: str) -> str:
    """Prepare Tesla Shorts Time script text for ElevenLabs TTS.

    Delegates to the shared pronunciation module (assets/pronunciation.py)
    with Tesla-specific overrides:
      - ICE is spoken as "ice" (not spelled out as "I C E")
      - All Tesla product names, acronyms, and terminology are handled
    """
    from assets.pronunciation import prepare_text_for_tts
    return prepare_text_for_tts(
        text,
        skip_acronyms={"ICE"},  # TST wants "ice" not "I C E"
    )

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
    # In test mode, default to no posting/no audio unless explicitly overridden
    ENABLE_X_POSTING = env_bool("ENABLE_X_POSTING", False)
    ENABLE_PODCAST = env_bool("ENABLE_PODCAST", False)

# ========================== SET UP SHARED PRONUNCIATION MODULE ==========================
import sys
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


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
if change != 0:
    sign = "+" if change > 0 else "-"
    change_str = f"{sign}${abs(change):.2f} ({change_pct:+.2f}%) {market_status}"
else:
    change_str = "unchanged"

# Folders - use absolute paths
# New episodes go to dedicated subdirectory; old flat files stay in digests/ for RSS compat
digests_dir = project_root / "digests" / "tesla_shorts_time"
digests_dir.mkdir(parents=True, exist_ok=True)

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
    """Extract Short Spot, First Principles, Daily Challenge, and Inspiration Quote from a digest file."""
    sections = {
        "short_spot": None,
        "short_squeeze": None,
        "first_principles": None,
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
            r'(?:## Short Spot|📉 \*\*Short Spot\*\*)(.*?)(?=━━|### Short Squeeze|📈|### Tesla First Principles|🧠|### Daily Challenge|💪|✨|$)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        if short_spot_match:
            sections["short_spot"] = short_spot_match.group(1).strip()

        # Extract Tesla First Principles
        first_principles_match = re.search(
            r'(?:### Tesla First Principles|🧠 Tesla First Principles)(.*?)(?=━━|### Daily Challenge|💪|## Tesla Market Movers|$)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        if first_principles_match:
            sections["first_principles"] = first_principles_match.group(1).strip()

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
        
        for pattern in [f"Tesla_Shorts_Time_{date_str}.md"]:
            # Check new subdirectory first, then old flat directory
            digest_path = digests_dir / pattern
            if not digest_path.exists():
                digest_path = digests_dir.parent / pattern
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
    json_path = project_root / "digests" / "tesla_shorts_time" / f"summaries_{podcast_name}.json"
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

# Entity-level dedup: cap articles to max 2 per primary entity
tesla_news = deduplicate_by_entity(tesla_news, max_per_entity=2)

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
    "tslaming",  # Deep dive Tesla content creator

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
article_count = len(tesla_news) if tesla_news else 0
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

# Determine whether to include Tesla X Takeover based on article count
include_takeover = article_count >= 15

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
**TSLA:** ${price:.2f} {change_str}

{news_section}

{x_posts_section}

You are an elite Tesla news curator producing the daily "Tesla Shorts Time" newsletter. Use ONLY the pre-fetched news above. Do NOT hallucinate, invent, or search for new content/URLs—stick to exact provided links. Do NOT include a "Top X Posts" section in your output. Prioritize diversity: No duplicates/similar stories (≥70% overlap in angle/content); max 3 from one source/account.

You have {article_count} quality articles to work with today.

CRITICAL: Only select articles that are SPECIFIC, FRESH (within last 48 hours), and SUBSTANTIVE. Prioritize stories about Tesla's products, technology, safety, sustainability, and mission to accelerate the transition to sustainable energy. REJECT any articles that are:
- Generic homepage content ("latest news", "ongoing coverage", "provides updates")
- Purely stock price/market data focused (no product or mission angle)
- Very short descriptions (<100 characters)
- From obviously wrong dates (future dates or very old)
- Elon Musk posts that aren't Tesla-specific
- Company overview pages

If fewer than 8 quality articles are available, use ALL available quality articles and create a shorter digest rather than padding with low-quality content.
{"" if not include_takeover else '''
**TESLA X TAKEOVER SECTION**: This section should focus on the most interesting, fresh, and engaging recent Tesla news developments, trends, or breaking stories. Use the pre-fetched news articles above to identify 5 compelling Tesla stories or trends that are generating buzz. Focus on what is NEW, INTERESTING, and DIFFERENT from the main news section. This could include:
- Breaking developments that just emerged
- Interesting trends or patterns in Tesla's business
- Surprising announcements or updates
- Community reactions to major Tesla news
- Unique angles on Tesla stories that stand out
- Deep dive analysis and insights (check @tslaming on X for excellent deep dive Tesla content)

CRITICAL: The 5 Tesla X Takeover items must each be a DIFFERENT story from the Top News items—do NOT use the same article, same headline, or same story angle in both sections. Make each Takeover item engaging and fresh; each should feel like you are sharing exciting, breaking Tesla news with enthusiasm.
'''}
**FINAL FALLBACK**: Only if RSS feeds provide fewer than 5 quality articles, you may search for additional recent, legitimate Tesla news articles from reputable sources (Teslarati, The Verge, WebProNews, CleanTechnica) published within the last 48 hours. Also check @tslaming on X for deep dive Tesla content worth sharing. Prioritize breaking news and specific product updates over analysis pieces. Ensure no more than 2 articles from any single source.

**CRITICAL**:
- Do NOT include any instruction language, meta-commentary, or formatting notes in your output - only output the actual content.
- Focus on FRESH, INTERESTING Tesla news
- Make it engaging and exciting

{used_content_summary}

### CRITICAL INSTRUCTIONS (DO NOT INCLUDE THESE IN YOUR OUTPUT):
- Short Spot: Must be COMPLETELY DIFFERENT from any recent Short Spots. Use a DIFFERENT bearish story, DIFFERENT angle, and DIFFERENT framing.
- Tesla First Principles: Must be COMPLETELY DIFFERENT from any recent First Principles analyses. Use a DIFFERENT current situation, DIFFERENT fundamental question, DIFFERENT data analysis, and DIFFERENT Tesla approach.
- Tesla Market Movers (Mondays only): Must provide FRESH market analysis from the past week. Focus on REAL market movements, not speculation.
- Daily Challenge: Must be COMPLETELY NEW and DIFFERENT from any recent Daily Challenges. Use a DIFFERENT theme, DIFFERENT approach, and DIFFERENT wording.
- Inspiration Quote: Must be from a DIFFERENT author than recent quotes. Use a DIFFERENT quote with a DIFFERENT message. Vary authors widely.

**IMPORTANT**: The format template below shows what your OUTPUT should look like. Do NOT include any instruction text, warnings (🚨 CRITICAL), or meta-commentary in your output. Only output the actual content sections.

### MANDATORY SELECTION & COUNTS (CRITICAL - FOLLOW EXACTLY)
- **News**: You have {article_count} pre-fetched articles. Select ONLY high-quality, fresh articles (within 48 hours, specific content, substantial descriptions). Use up to the best 10 if available. If fewer than 8 quality articles exist, use ALL of them. Each article must have a unique angle and substantial, specific information about Tesla.
- **CRITICAL URL RULE**: NEVER invent URLs. If you don't have enough pre-fetched articles, output fewer items rather than making up URLs. All URLs must be exact matches from the pre-fetched list above.
- **Diversity Check**: Before finalizing, verify no similar content; replace if needed from pre-fetched pool.{"" if not include_takeover else " Top News and Tesla X Takeover must have ZERO overlapping stories."}
- **Short Spot**: Must use an article whose URL does NOT appear in the Top News section. If no separate bearish article exists, skip Short Spot this episode.

### FORMATTING (EXACT—USE MARKDOWN AS SHOWN)
# Tesla Shorts Time
**Date:** {today_str}
**TSLA:** ${price:.2f} {change_str}

━━━━━━━━━━━━━━━━━━━━
### Top News
1. **Title (One Line): DD Month, YYYY, HH:MM AM/PM PST, Source Name**
   2–4 sentences: Start with what happened, then why it matters for Tesla's mission and how it advances sustainable energy, saves lives, or makes the world better. End with: Source: [EXACT URL FROM PRE-FETCHED—no mods]
2. [Repeat format for remaining items; output as many quality items as available up to 10, add a blank line after each item]
{"" if not include_takeover else '''
━━━━━━━━━━━━━━━━━━━━
## Tesla X Takeover: What is Hot Right Now
🎙️ Tesla X Takeover - What is breaking in the Tesla world today! Here are the most interesting, fresh Tesla developments that have everyone talking.

1. 🚨 **[INCREDIBLE TITLE THAT HOOKS]** - [Breaking Tesla news or development]
   [Make it sound exciting and fresh - like sharing breaking Tesla news with friends. Include what happened, why it matters for Tesla mission, and how it advances sustainable energy or saves lives. 2-3 sentences with personality and enthusiasm.]
   Source: [EXACT URL FROM PRE-FETCHED NEWS - if available]

2. 🔥 **[EXCITING TITLE]** - [Another fresh Tesla development or trend]
   [Make it conversational and engaging. Focus on what makes this story interesting, surprising, or important for Tesla mission to make the world better.]

3. 💡 **[INSIGHTFUL TITLE]** - [Interesting Tesla trend or pattern]
   [Highlight what is unique or noteworthy about this development. Connect it to Tesla bigger picture — accelerating sustainable energy, advancing autonomy and safety, or improving lives.]

4. ⚡ **[ENERGETIC TITLE]** - [Surprising Tesla announcement or update]
   [Focus on what makes this development exciting or unexpected. Explain why this could be significant for Tesla mission or for making the world a safer, cleaner place.]

5. 🎯 **[PRECISION TITLE]** - [Fresh Tesla story that stands out]
   [Show why this particular development is noteworthy and different from the usual news. Make it clear why Tesla fans and anyone who cares about the future should pay attention.]

**The Vibe Check:** "Overall, the Tesla world is [ENERGIZED/CHALLENGED/EVOLVING] this week, with key themes around [Autopilot safety, energy storage, Cybertruck deliveries, manufacturing efficiency, etc.]. The most exciting developments are [specific trends or patterns], showing Tesla progress toward [its mission of sustainable energy / saving lives through autonomy / etc.]."
'''}

━━━━━━━━━━━━━━━━━━━━
## Short Spot
One bearish or critical item from pre-fetched news about Tesla.
**Catchy Title: DD Month, YYYY, HH:MM AM/PM PST, @username/Source**
2–4 sentences explaining the concern, then why it's temporary or overblown — frame it in terms of Tesla's long-term mission and track record of overcoming obstacles. End with: Source/Post: [EXACT URL]

━━━━━━━━━━━━━━━━━━━━
### Tesla First Principles
🧠 Tesla First Principles - Cutting Through the Noise

Taking a step back from today's headlines, let's apply first principles thinking to [COMPLETELY DIFFERENT topic than recent days - choose something unrelated to recent analyses like battery tech, autonomous driving, manufacturing, energy storage, international expansion, regulatory challenges, supply chain, competition, or any other fundamental Tesla issue]...

**The Fundamental Question:** [Core question that actually matters for Tesla's long-term success]

**The Data Says:** [Factual analysis based on Tesla's actual numbers, physics, market realities - no hype]

**The Tesla Approach:** [How Tesla would actually solve this problem using their proven methodologies]

**The Real-World Impact:** [What this means for people's lives — safety, environment, energy independence, transportation access]

**The Long-Term Play:** [Why this matters for Tesla's mission to accelerate the world's transition to sustainable energy and how it makes the world a better place]
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
- Inspirational, pro-Tesla, optimistic, energetic, mission-focused.
- Emphasize how Tesla's work saves lives, advances sustainability, and makes the world better.
- De-emphasize stock price movements and financial metrics — focus on products, technology, and real-world impact.
- Timestamps: Accurate PST/PDT (convert from pre-fetched).
- No stock-quote pages/pure price commentary as "news."

### FINAL VALIDATION CHECKLIST (DO THIS BEFORE OUTPUT)
- ✅ Top News items: Up to 10 (or all if <10), numbered, unique stories.{"" if not include_takeover else chr(10) + "- ✅ Tesla X Takeover section included with 5 fresh, interesting Tesla developments (ZERO overlap with Top News)."}
- ✅ Short Spot: Uses a DIFFERENT article URL from the Top News section.
- ✅ Podcast link: Full URL as shown.
- ✅ Lists: "1. " format (number, period, space)—no bullets.
- ✅ Separators: "━━━━━━━━━━━━━━━━━━━━" before each major section.
- ✅ No duplicates: All items unique (review pairwise).
- ✅ All sections included: Short Spot, Tesla First Principles, Tesla Market Movers (Mondays only), Daily Challenge, Quote, sign-off.
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
    """Delegate to engine.publisher.format_tst_digest_for_x."""
    return _engine_format_tst_digest_for_x(digest)

# Format the digest
x_thread_formatted = format_digest_for_x(x_thread)
logging.info(f"Digest formatted for X ({len(x_thread_formatted)} characters)")

# Use the formatted version for posting and save once
x_thread = x_thread_formatted

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

# Save the updated tracker (legacy format)
save_used_content_tracker(content_tracker)
logging.info("Content tracker updated with today's sections")

# Also save with the new engine-based content tracker for future cross-episode dedup
try:
    _tst_tracker = ContentTracker("tesla_shorts_time", digests_dir)
    _tst_tracker.load()
    _tst_tracker.record_episode(x_thread, TST_SECTION_PATTERNS)
    _tst_tracker.save()
    logging.info("Engine content tracker updated")
except Exception as _e:
    logging.warning("Failed to update engine content tracker: %s", _e)

# Exit early if in test mode (only generate digest)
if TEST_MODE:
    print("\n" + "="*80)
    print("TEST MODE - Digest generated only (skipping podcast and X posting)")
    print(f"Digest saved to: {x_path}")
    print("="*80)
    sys.exit(0)

# ========================== X POSTING (via engine/publisher.post_to_x) ==========================
tweet_id = None
if ENABLE_X_POSTING:
    logging.info("@teslashortstime X posting enabled (delegating to engine)")
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
        f'Host: Welcome back to Tesla Shorts Time Daily, episode {{episode_num}}. It\'s {{today_str}}. Let\'s talk about what really moved Tesla today.',
        f'Host: Hey, welcome to Tesla Shorts Time Daily, episode {{episode_num}}. Today is {{today_str}}, and we\'ve got a fresh batch of Tesla stories to unpack together.',
        f'Host: This is Tesla Shorts Time Daily, episode {{episode_num}}. It\'s {{today_str}}. Grab a coffee, and let\'s walk through what actually mattered for Tesla today.',
        f'Host: Good to have you here for Tesla Shorts Time Daily, episode {{episode_num}}. It\'s {{today_str}}, and we\'re diving into the Tesla news that matters.',
        f'Host: Tesla Shorts Time Daily, episode {{episode_num}}. {{today_str}}. Thanks for tuning in; here\'s what\'s going on with Tesla.',
        f'Host: Welcome to Tesla Shorts Time Daily, episode {{episode_num}}. It is {{today_str}}, bringing you the latest Tesla news and updates. If you like the show, like, share, rate and subscribe — it really helps. Now straight to the news.',
    ]
    CLOSING_TEMPLATES = [
        f'Host: Every day Tesla is out there making roads safer, making energy cleaner, and pushing humanity forward. That\'s what this show is really about.\nHost: That\'s Tesla Shorts Time Daily for today. I\'d love to hear your thoughts — reach out @teslashortstime on X or DM us. Stay safe, keep accelerating, and we\'ll catch you tomorrow.',
        f'Host: When you step back and look at the big picture, Tesla is saving lives through safer cars, powering homes with clean energy, and building a more sustainable future. That\'s what keeps me excited.\nHost: Thanks for listening to Tesla Shorts Time Daily. Hit us up @teslashortstime with feedback or ideas. Future is electric — talk to you next time.',
        f'Host: Remember, the real story with Tesla isn\'t the day-to-day noise. It\'s the lives being saved by autopilot, the grid being stabilized by Megapacks, and the air getting cleaner every time someone drives a Tesla instead of burning gas.\nHost: That\'s it for today\'s Tesla Shorts Time Daily. I look forward to hearing from you — @teslashortstime on X or DM. Stay safe, keep accelerating, and we\'ll catch you tomorrow.',
        f'Host: The mission is what matters — accelerating the world\'s transition to sustainable energy. Everything Tesla does feeds into that, and every day we\'re getting closer.\nHost: Thanks for spending a few minutes with me. DM @teslashortstime with thoughts or ideas. Your efforts help accelerate the transition to sustainable energy. We\'ll catch you tomorrow on Tesla Shorts Time Daily.',
        f'Host: The real value of Tesla can\'t be measured in a stock ticker. It\'s measured in lives saved, emissions avoided, and a future being built right now.\nHost: That\'s Tesla Shorts Time Daily for today. Reach out @teslashortstime — I\'d love to hear what you\'re seeing. Take care, and we\'ll talk again tomorrow.',
    ]
    _intro_line = _podcast_rng.choice(INTRO_TEMPLATES).format(episode_num=episode_num, today_str=today_str)
    _closing_block = _podcast_rng.choice(CLOSING_TEMPLATES)

    # Tone hint so script matches the day (not always max enthusiasm)
    # Driven by news sentiment, not stock price
    tone_hint = "natural and conversational — match your energy to the news stories, not stock movement. Some days are exciting, some are reflective; let the content guide your delivery."

    # Podcast prompt: guidelines + rotated intro/outro for variety
    POD_PROMPT = f"""You are writing an 8–11 minute (1950–2600 words) solo podcast script for "Tesla Shorts Time Daily" Episode {episode_num}.

HOST: A Canadian newscaster and science enthusiast. Sound like a real person catching a friend up on Tesla, not a robotic announcer. Do NOT use any personal names for the host — no "I'm [name]" or self-introductions by name.

RULES:
- Start every line with "Host:"
- Don't read URLs aloud — mention source names naturally
- Use natural dates ("today", "this morning") not exact timestamps
- Enunciate all numbers, dollar amounts, percentages clearly
- Use ONLY information from the digest below — nothing else
- Do NOT mention TSLA stock price, share price, dollar amounts for the stock, or percentage changes in the stock. Focus entirely on Tesla's mission, products, and news.
- Never refer to the host by name

TONE (vary by the day):
- {tone_hint}
- Focus on how Tesla's daily developments advance the mission — saving lives, sustainable energy, making the world better.
- Do NOT discuss stock price or stock movement. Skip any stock data in the digest — it is only there for internal reference. The podcast is about Tesla's mission, not its share price.
- Vary sentence length and pacing; some moments can be calm or thoughtful, not always high-energy.
- Sound warm and human — occasionally excited, occasionally reflective — never mechanical.

SCRIPT STRUCTURE:
[Intro music - 5–10 seconds]
Use this exact intro (do not rewrite it):
{_intro_line}

[Narrate EVERY item from the digest in order - no skipping]
- For each news item: Read the title naturally, then paraphrase the summary in your own words. Vary delivery — not every item needs the same level of enthusiasm.
- Tesla X Takeover: Introduce the section in your own words. Cover each item clearly; explain why it matters for Tesla's mission and for making the world better. End with the vibe check in a natural way.
- Short Spot: Explain the concern and why it's temporary or overblown in terms of Tesla's long-term mission — tone can be more measured here.
- Tesla First Principles: Explain the fundamental question, data, Tesla approach, and real-world impact. Educational but engaging; no need to oversell.
- Tesla Market Movers (Mondays only): Brief recap of the week's Tesla context in terms of mission progress and product execution. Do NOT read specific stock prices or percentage changes.
- Daily Challenge + Quote: Read the quote verbatim, then the challenge verbatim, add one short encouraging sentence.

[Closing]
Use this exact closing (do not rewrite it):
{_closing_block}

Here is today's complete formatted digest. Use ONLY this content:
"""

    # Strip stock price line from digest before passing to podcast prompt
    # The stock price is for the X thread/markdown only, not the podcast
    _pod_digest = re.sub(r'\*\*TSLA:\*\*[^\n]+\n?', '', x_thread)
    # Also strip any "I'm Patrick" self-identification the model might have produced
    _pod_digest = re.sub(r"\bI'm Patrick\b", "I'm your host", _pod_digest)
    _pod_digest = re.sub(r"\bPatrick here\b", "Your host here", _pod_digest)

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
                        "text": "You are the world's best Tesla podcast writer. Make it feel like a real Canadian friend catching you up on Tesla: warm, honest, occasionally excited, occasionally thoughtful — never robotic or like an AI reading a script. Focus on how Tesla's daily news advances the mission of sustainable energy, saves lives, and makes the world a better place. Do NOT mention stock prices, share prices, or financial metrics — the mission is what matters. Never use a personal name for the host.",
                    }
                ],
            },
            {"role": "user", "content": [{"type": "input_text", "text": f"{POD_PROMPT}\n\n{_pod_digest}"}]},
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

    # Extract text from podcast script (remove "Host:"/"Patrick:" prefixes and stage directions)
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
        if line.startswith("Host:"):
            full_text_parts.append(line[5:].strip())
        elif line.startswith("Patrick:"):
            # Backward compat: strip legacy "Patrick:" prefix if Grok still generates it
            full_text_parts.append(line[9:].strip())
        else:
            # Include all other content that isn't stage directions
            full_text_parts.append(line)

    full_text = " ".join(full_text_parts).strip()

    # Strip any personal name references that slipped through
    full_text = re.sub(r"\bI'm Patrick\b", "I'm your host", full_text)
    full_text = re.sub(r"\bPatrick here\b", "Your host here", full_text)
    full_text = re.sub(r"\bI'm Patrick[\w, ]+\.", "I'm your host.", full_text)

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

    # ========================== FINAL MIX (delegated to engine/audio) ==========================
    final_mp3 = digests_dir / f"Tesla_Shorts_Time_Pod_Ep{episode_num:03d}_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp3"
    MAIN_MUSIC = project_root / "assets" / "music" / "tesla_shorts_time.mp3"

    # Validate voice file before mixing
    if not voice_file.exists():
        raise RuntimeError(f"Voice file {voice_file} does not exist!")
    voice_file_size = voice_file.stat().st_size
    if voice_file_size < 1000:
        raise RuntimeError(f"Voice file {voice_file} is too small ({voice_file_size} bytes) - TTS may have failed")

    _engine_mix_with_music(voice_file, MAIN_MUSIC, final_mp3)

    # Verify final output
    if not final_mp3.exists():
        raise RuntimeError(f"Final podcast file {final_mp3} was not created!")
    final_size = final_mp3.stat().st_size
    if final_size < 10000:
        raise RuntimeError(f"Final podcast file {final_mp3} is too small ({final_size} bytes) - mixing failed")
    logging.info(f"Final podcast created: {final_mp3.name}")


def scan_existing_episodes_from_files(digests_dir: Path, base_url: str) -> list:
    """Scan digests directory for all existing MP3 files and return episode data.
    Handles both old format (without timestamp) and new format (with timestamp).
    Also checks digests/digests subdirectory for older episodes.

    Delegates the common directory-scan logic to engine.publisher.scan_existing_episodes_from_files
    and adds TST-specific legacy directory handling + rich RSS-ready metadata.
    """
    # --- Collect basic episode info from primary directory via engine ----------
    basic_episodes = _engine_scan_episodes(
        digests_dir,
        base_url,
        mp3_glob="Tesla_Shorts_Time_Pod_Ep*.mp3",
        filename_pattern=r"Tesla_Shorts_Time_Pod_Ep(\d+)_(\d{8})",
        audio_subdir="digests",
    )

    # --- TST legacy: also scan old flat digests/ and digests/digests/ dirs -----
    old_flat_dir = digests_dir.parent  # project_root / "digests"
    legacy_dirs = []
    if old_flat_dir != digests_dir:
        legacy_dirs.append(("digests", old_flat_dir))
    digests_subdir = old_flat_dir / "digests"
    if digests_subdir.exists():
        legacy_dirs.append(("digests/digests", digests_subdir))

    for audio_sub, legacy_dir in legacy_dirs:
        legacy_eps = _engine_scan_episodes(
            legacy_dir,
            base_url,
            mp3_glob="Tesla_Shorts_Time_Pod_Ep*.mp3",
            filename_pattern=r"Tesla_Shorts_Time_Pod_Ep(\d+)_(\d{8})",
            audio_subdir=audio_sub,
        )
        basic_episodes.extend(legacy_eps)

    # --- Deduplicate by episode number (keep first seen) ----------------------
    seen_eps = set()
    deduped = []
    for ep in basic_episodes:
        if ep["episode_num"] not in seen_eps:
            seen_eps.add(ep["episode_num"])
            deduped.append(ep)

    # --- Build rich RSS-ready dicts from basic episode info --------------------
    pattern_new = re.compile(r"Tesla_Shorts_Time_Pod_Ep(\d+)_(\d{8})_(\d{6})\.mp3")
    episodes = []
    for ep in deduped:
        mp3_file = ep["path"]
        # Verify file has content
        if not mp3_file.exists() or mp3_file.stat().st_size < 1000:
            logging.warning(f"Skipping {mp3_file.name}: file doesn't exist or is too small")
            continue

        episode_num = ep["episode_num"]
        episode_date = ep["date"]
        date_str = episode_date.strftime("%Y%m%d")

        # Extract timestamp from new-format filenames for GUID
        ts_match = pattern_new.match(mp3_file.name)
        if ts_match:
            time_str = ts_match.group(3)
        else:
            mtime = datetime.datetime.fromtimestamp(mp3_file.stat().st_mtime)
            time_str = mtime.strftime("%H%M%S")

        episode_guid = f"tesla-shorts-time-ep{episode_num:03d}-{date_str}-{time_str}"
        episode_title = f"Tesla Shorts Time Daily - Episode {episode_num} - {episode_date.strftime('%B %d, %Y')}"
        url_path = ep["url"]

        try:
            mp3_duration = ep["duration"]
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


_TST_BASE_URL = "https://nerranetwork.com"


def update_rss_feed(
    rss_path: Path,
    episode_num: int,
    episode_title: str,
    episode_description: str,
    episode_date: datetime.date,
    mp3_filename: str,
    mp3_duration: float,
    mp3_path: Path,
    base_url: str = _TST_BASE_URL,
):
    """Update Tesla Shorts Time RSS feed — delegates to engine.publisher.update_rss_feed."""
    _engine_update_rss_feed(
        rss_path, episode_num, episode_title, episode_description,
        episode_date, mp3_filename, mp3_duration, mp3_path,
        base_url=base_url,
        audio_subdir="digests/tesla_shorts_time",
        channel_title="Tesla Shorts Time Daily",
        channel_link="https://nerranetwork.com/",
        channel_description="A daily podcast covering the latest Tesla news, stock prices, and industry insights.",
        channel_author="Patrick",
        channel_email="contact@teslashortstime.com",
        channel_image=f"{base_url}/podcast-image-v3.jpg",
        channel_category="Technology",
        guid_prefix="tesla-shorts-time",
        format_duration_func=format_duration,
    )

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
        base_url = "https://nerranetwork.com"
        
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
        _base_url = "https://nerranetwork.com"
        _audio_url = None
        try:
            if ENABLE_PODCAST and final_mp3:
                _audio_url = f"{_base_url}/digests/tesla_shorts_time/{final_mp3.name}"
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
        summaries_url = "https://nerranetwork.com/tesla-summaries.html"
        today = datetime.datetime.now()
        teaser_text = (
            f"\U0001f697\u26a1 Tesla Shorts Time Daily - {today.strftime('%B %d, %Y')}\n\n"
            f"\U0001f525 Today's complete digest is now live on our website!\n\n"
            f"\U0001f4c8 TSLA news, stock analysis, and market insights\n"
            f"\U0001f399\ufe0f Full podcast episode available\n"
            f"\U0001f4ca Raw data and sources included\n\n"
            f"Read the full summary: {summaries_url}\n\n"
            f"#Tesla #TSLA #TeslaShortsTime #EV"
        )
        credit_usage["services"]["x_api"]["post_calls"] += 1
        tweet_url = _engine_post_to_x(
            teaser_text,
            consumer_key=os.getenv("X_CONSUMER_KEY", ""),
            consumer_secret=os.getenv("X_CONSUMER_SECRET", ""),
            access_token=os.getenv("X_ACCESS_TOKEN", ""),
            access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET", ""),
        )
        if tweet_url:
            logging.info(f"DIGEST LINK POSTED \u2192 {tweet_url}")
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