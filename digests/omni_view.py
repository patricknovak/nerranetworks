#!/usr/bin/env python3
"""
Omni View – FULL AUTO X + PODCAST MACHINE
Daily Balanced News Digest (Patrick in Vancouver)
Auto-published to X — January 2026+
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

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

# ========================== SHARED CONFIGURATION ==========================
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
    "User-Agent": "OmniViewBot/1.0 (+https://x.com/omniviewnews)"
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
        return str(integer_part)

    # Convert decimal part
    if decimal_part:
        decimal_str = str(decimal_part).lstrip('0.')
        if decimal_str:
            decimal_words = ' '.join(digit_names[int(d)] for d in decimal_str)
            result += ' point ' + decimal_words

    if is_negative:
        result = 'negative ' + result

    return result

# ========================== UTILITY FUNCTIONS ==========================
def fix_omni_pronunciation(text: str) -> str:
    """Fix pronunciation issues specific to Omni View content."""
    # Currency fixes
    text = re.sub(r'\$([0-9]+(?:\.[0-9]+)?)', lambda m: f"{number_to_words(float(m.group(1)))} dollars", text)
    text = re.sub(r'€([0-9]+(?:\.[0-9]+)?)', lambda m: f"{number_to_words(float(m.group(1)))} euros", text)
    text = re.sub(r'£([0-9]+(?:\.[0-9]+)?)', lambda m: f"{number_to_words(float(m.group(1)))} pounds", text)

    # Percentage fixes
    text = re.sub(r'([0-9]+(?:\.[0-9]+)?)%', lambda m: f"{number_to_words(float(m.group(1)))} percent", text)

    # Date fixes
    text = re.sub(r'([0-9]{1,2})(st|nd|rd|th)', r'\1', text)  # Remove ordinal suffixes

    # Time fixes
    text = re.sub(r'([0-9]{1,2}):([0-9]{2})', lambda m: f"{int(m.group(1))} {int(m.group(2))}", text)

    return text

def remove_similar_items(items, similarity_threshold=0.7, get_text_func=None):
    """
    Remove similar/duplicate items based on text similarity.

    Args:
        items: List of items to deduplicate
        similarity_threshold: Similarity threshold (0-1, higher = more similar required to remove)
        get_text_func: Function to extract text from item for comparison (default: uses 'title' or 'text' key)

    Returns:
        List of deduplicated items
    """
    if not items:
        return []

    if get_text_func is None:
        def get_text_func(item):
            # Try different keys for text content
            for key in ['title', 'text', 'content', 'description']:
                if key in item and item[key]:
                    return str(item[key])
            return str(item)

    deduplicated = []
    for item in items:
        item_text = get_text_func(item).lower().strip()

        # Check similarity with existing items
        is_duplicate = False
        for existing in deduplicated:
            existing_text = get_text_func(existing).lower().strip()
            similarity = SequenceMatcher(None, item_text, existing_text).ratio()
            if similarity >= similarity_threshold:
                is_duplicate = True
                break

        if not is_duplicate:
            deduplicated.append(item)

    return deduplicated

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

        # TTS cost (ElevenLabs pricing: ~$0.30 per 1000 characters)
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
        logging.info(f"TTS (ElevenLabs): {usage_data['services']['elevenlabs_api']['characters']} characters (${usage_data['services']['elevenlabs_api']['estimated_cost_usd']:.4f})")
        logging.info(f"X API: {usage_data['services']['x_api']['total_calls']} API calls (search: {usage_data['services']['x_api']['search_calls']}, post: {usage_data['services']['x_api']['post_calls']})")
        logging.info(f"TOTAL ESTIMATED COST: ${usage_data['total_estimated_cost_usd']:.4f}")
        logging.info("="*80)

    except Exception as e:
        logging.error(f"Failed to save credit usage: {e}", exc_info=True)

def save_summary_to_github_pages(summary_text: str, output_dir: Path, podcast_name: str = "omni"):
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
        summary_entry = {
            "date": today.strftime("%Y-%m-%d"),
            "datetime": today.isoformat(),
            "content": summary_text,
            "episode_num": get_next_episode_number(project_root / "omni_view_podcast.rss", output_dir) - 1  # Current episode
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

# ========================== STEP 1: FETCH BALANCED NEWS FROM DIVERSE SOURCES ==========================
logging.info("Step 1: Fetching balanced news from diverse sources for the last 24 hours...")

def fetch_balanced_news():
    """Fetch balanced news from diverse sources across the political spectrum."""
    import feedparser

    # Diverse news sources representing different perspectives
    rss_feeds = [
        # Major News Outlets - Center/Left
        "https://feeds.npr.org/1001/rss.xml",  # NPR
        "https://rss.cnn.com/rss/edition.rss",  # CNN
        "https://feeds.bbci.co.uk/news/rss.xml",  # BBC
        "https://www.nytimes.com/rss",  # New York Times
        "https://www.washingtonpost.com/rss/",  # Washington Post
        "https://feeds.reuters.com/Reuters/worldNews",  # Reuters
        "https://feeds.a.dj.com/rss/RSSWorldNews.xml",  # Wall Street Journal

        # Major News Outlets - Center/Right
        "https://feeds.foxnews.com/foxnews/politics",  # Fox News
        "https://www.newsmax.com/rss/Newsfront/16/",  # Newsmax
        "https://www.breitbart.com/rss.xml",  # Breitbart
        "https://www.dailymail.co.uk/articles.rss",  # Daily Mail

        # International Perspectives
        "https://www.aljazeera.com/xml/rss/all.xml",  # Al Jazeera
        "https://www.theguardian.com/world/rss",  # The Guardian (UK)
        "https://www.france24.com/en/rss",  # France 24
        "https://www.dw.com/en/rss.xml",  # Deutsche Welle

        # Alternative/Independent
        "https://theintercept.com/feed/?lang=en",  # The Intercept
        "https://www.motherjones.com/rss",  # Mother Jones
        "https://reason.com/feed/",  # Reason
        "https://www.realclearpolitics.com/index.xml",  # Real Clear Politics

        # Business/Financial
        "https://feeds.bloomberg.com/markets/news.rss",  # Bloomberg
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",  # CNBC

        # Science/Tech (for balance)
        "https://www.wired.com/feed/rss",  # Wired
        "https://arstechnica.com/rss.xml",  # Ars Technica
    ]

    # Calculate cutoff time (last 24 hours)
    cutoff_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)

    all_articles = []
    raw_articles = []

    # Keywords for important news (avoid overly niche topics)
    important_keywords = [
        "election", "president", "government", "policy", "law", "court", "supreme",
        "economy", "recession", "inflation", "unemployment", "federal reserve",
        "war", "conflict", "peace", "treaty", "sanctions", "diplomacy",
        "climate", "environment", "disaster", "weather", "energy",
        "health", "pandemic", "vaccine", "medical", "fda", "cdc",
        "technology", "ai", "internet", "social media", "privacy",
        "crime", "justice", "police", "protest", "civil rights",
        "international", "trade", "immigration", "borders",
        "business", "corporate", "merger", "bankruptcy", "stocks",
        "sports", "championship", "olympics", "world cup",  # Major events only
        "celebrity", "entertainment", "hollywood",  # Major stories only
    ]

    logging.info(f"Fetching balanced news from {len(rss_feeds)} diverse RSS feeds...")

    for feed_url in rss_feeds:
        source_name = "Unknown"
        try:
            feed = feedparser.parse(feed_url)

            if feed.bozo and feed.bozo_exception:
                logging.warning(f"Failed to parse RSS feed {feed_url}: {feed.bozo_exception}")
                continue

            source_name = feed.feed.get("title", "Unknown")

            # Map common feed sources
            if "npr.org" in feed_url.lower():
                source_name = "NPR"
            elif "cnn.com" in feed_url.lower():
                source_name = "CNN"
            elif "bbc" in feed_url.lower():
                source_name = "BBC"
            elif "nytimes.com" in feed_url.lower():
                source_name = "New York Times"
            elif "washingtonpost.com" in feed_url.lower():
                source_name = "Washington Post"
            elif "reuters.com" in feed_url.lower():
                source_name = "Reuters"
            elif "wsj.com" in feed_url.lower():
                source_name = "Wall Street Journal"
            elif "foxnews.com" in feed_url.lower():
                source_name = "Fox News"
            elif "newsmax.com" in feed_url.lower():
                source_name = "Newsmax"
            elif "breitbart.com" in feed_url.lower():
                source_name = "Breitbart"
            elif "dailymail.co.uk" in feed_url.lower():
                source_name = "Daily Mail"
            elif "aljazeera.com" in feed_url.lower():
                source_name = "Al Jazeera"
            elif "theguardian.com" in feed_url.lower():
                source_name = "The Guardian"
            elif "france24.com" in feed_url.lower():
                source_name = "France 24"
            elif "dw.com" in feed_url.lower():
                source_name = "Deutsche Welle"
            elif "theintercept.com" in feed_url.lower():
                source_name = "The Intercept"
            elif "motherjones.com" in feed_url.lower():
                source_name = "Mother Jones"
            elif "reason.com" in feed_url.lower():
                source_name = "Reason"
            elif "realclearpolitics.com" in feed_url.lower():
                source_name = "Real Clear Politics"
            elif "bloomberg.com" in feed_url.lower():
                source_name = "Bloomberg"
            elif "cnbc.com" in feed_url.lower():
                source_name = "CNBC"
            elif "wired.com" in feed_url.lower():
                source_name = "Wired"
            elif "arstechnica.com" in feed_url.lower():
                source_name = "Ars Technica"

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

                # Check if article covers important news topics
                title_desc_lower = (title + " " + description).lower()
                if not any(keyword in title_desc_lower for keyword in important_keywords):
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

    # Select the most important and diverse news
    selected_articles = select_balanced_news(formatted_articles, max_articles=15)

    logging.info(f"Selected {len(selected_articles)} balanced news articles from diverse sources")
    return selected_articles, raw_articles

def select_balanced_news(articles, max_articles=15):
    """
    Select balanced news that represents diverse perspectives and important topics.
    """
    if not articles:
        return []

    # Source diversity scoring - encourage variety
    processed_sources = set()
    diverse_articles = []

    # First pass: Get one article from each major source category
    left_sources = {"CNN", "New York Times", "Washington Post", "NPR", "BBC", "The Guardian", "Al Jazeera"}
    center_sources = {"Reuters", "Wall Street Journal", "Bloomberg", "CNBC", "Real Clear Politics"}
    right_sources = {"Fox News", "Newsmax", "Breitbart", "Daily Mail"}
    international_sources = {"France 24", "Deutsche Welle"}
    alternative_sources = {"The Intercept", "Mother Jones", "Reason"}
    tech_sources = {"Wired", "Ars Technica"}

    # Priority order for diversity
    source_categories = [
        ("Left/Center-Left", left_sources),
        ("Center", center_sources),
        ("Right/Center-Right", right_sources),
        ("International", international_sources),
        ("Alternative", alternative_sources),
        ("Tech/Business", tech_sources)
    ]

    # Select up to 2-3 articles from each major category
    target_per_category = 2

    for category_name, category_sources in source_categories:
        category_articles = [a for a in articles if a.get("source") in category_sources]
        selected_from_category = category_articles[:target_per_category]

        for article in selected_from_category:
            if len(diverse_articles) < max_articles:
                diverse_articles.append(article)
                processed_sources.add(article.get("source"))

    # Fill remaining slots with highest quality remaining articles
    remaining_articles = [a for a in articles if a.get("source") not in processed_sources]
    remaining_slots = max_articles - len(diverse_articles)

    if remaining_slots > 0 and remaining_articles:
        # Score remaining articles by recency and source reputation
        scored_remaining = []
        for article in remaining_articles[:remaining_slots * 2]:  # Get more than needed for scoring
            score = 0

            # Recency bonus
            try:
                published = datetime.datetime.fromisoformat(article.get("publishedAt", "").replace('Z', '+00:00'))
                hours_old = (datetime.datetime.now(datetime.timezone.utc) - published).total_seconds() / 3600
                if hours_old < 6:
                    score += 5
                elif hours_old < 12:
                    score += 3
                elif hours_old < 24:
                    score += 1
            except:
                pass

            # Source reputation (generic fallback)
            score += 1

            scored_remaining.append((score, article))

        scored_remaining.sort(key=lambda x: x[0], reverse=True)
        diverse_articles.extend([article for score, article in scored_remaining[:remaining_slots]])

    # Final sort by published date (newest first)
    diverse_articles.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)

    # Log the selection
    logging.info(f"Selected {len(diverse_articles)} balanced news articles:")
    source_counts = {}
    for article in diverse_articles:
        source = article.get("source", "Unknown")
        source_counts[source] = source_counts.get(source, 0) + 1

    for source, count in sorted(source_counts.items()):
        logging.info(f"  {source}: {count} article(s)")

    return diverse_articles[:max_articles]

# ========================== MAIN EXECUTION ==========================
# All execution code is in the if __name__ == "__main__" block below

# ========================== IMPLEMENTATION FUNCTIONS ==========================

def generate_balanced_news_digest(news_articles):
    """Generate a balanced news digest from the selected articles."""
    # Create a simple digest for now
    digest_lines = ["📰⚖️ **Omni View - Balanced News Digest**", ""]

    today = datetime.datetime.now().strftime("%B %d, %Y")
    digest_lines.extend([f"📅 **Date:** {today}", "", "🔍 **Balanced Perspectives on Today's News**", ""])

    for i, article in enumerate(news_articles[:12], 1):  # Limit to 12 for X thread
        title = article.get('title', 'Untitled')
        source = article.get('source', 'Unknown')
        digest_lines.extend([
            f"**{i}. {title}**",
            f"📺 *{source}*",
            ""
        ])

    digest_lines.extend([
        "",
        "🎙️ **Omni View Daily Podcast Link:** https://podcasts.apple.com/us/podcast/omni-view/idXXXXXXXXXX",
        "",
        "#OmniView #BalancedNews #MediaLiteracy"
    ])

    return "\n".join(digest_lines)

def generate_omni_view_script(news_articles):
    """Generate podcast script for Omni View."""
    script_lines = [
        "Welcome to Omni View, your daily source for balanced news perspectives.",
        "",
        f"Today is {datetime.datetime.now().strftime('%B %d, %Y')}.",
        "",
        "Here are the key stories from diverse sources, presented with multiple viewpoints:",
        ""
    ]

    for i, article in enumerate(news_articles[:10], 1):  # Limit for podcast length
        title = article.get('title', 'Untitled')
        source = article.get('source', 'Unknown')
        script_lines.extend([
            f"Story number {i}: {title}",
            f"This story is covered by {source}.",
            ""
        ])

    script_lines.extend([
        "",
        "Thank you for listening to Omni View. Remember, informed citizens make better decisions.",
        "Stay curious, stay balanced."
    ])

    return "\n".join(script_lines)

def create_omni_view_podcast(script_text):
    """Create the podcast audio file."""
    # For now, return a dummy file path and duration
    episode_num = get_next_episode_number(project_root / "omni_view_podcast.rss", digests_dir)
    audio_file = digests_dir / f"Omni_View_Ep{episode_num:03d}_{datetime.datetime.now():%Y%m%d}.mp3"
    duration = 600  # 10 minutes placeholder

    logging.info(f"Podcast audio would be saved to: {audio_file}")
    return audio_file, duration

def get_next_episode_number(rss_path: Path, digests_dir: Path) -> int:
    """Get the next episode number based on existing files."""
    try:
        if rss_path.exists():
            tree = ET.parse(rss_path)
            root = tree.getroot()
            items = root.findall('.//item')
            if items:
                return len(items) + 1
    except Exception:
        pass

    # Fallback: count existing MP3 files
    mp3_pattern = "Omni_View_Ep*.mp3"
    existing_episodes = list(digests_dir.glob(mp3_pattern))
    if existing_episodes:
        episode_nums = []
        for ep_file in existing_episodes:
            match = re.search(r'Ep(\d+)', ep_file.name)
            if match:
                episode_nums.append(int(match.group(1)))
        return max(episode_nums) + 1 if episode_nums else 1

    return 1

def generate_balanced_news_digest(news_articles):
    """Generate a balanced news digest from the selected articles."""
    # This is a placeholder - will be implemented with Grok AI
    logging.info("Generating balanced news digest...")

    # Create a simple digest for now
    digest_lines = ["📰⚖️ **Omni View - Balanced News Digest**", ""]

    today = datetime.datetime.now().strftime("%B %d, %Y")
    digest_lines.extend([f"📅 **Date:** {today}", "", "🔍 **Balanced Perspectives on Today's News**", ""])

    for i, article in enumerate(news_articles[:10], 1):  # Limit to 10 for X thread
        title = article.get('title', 'Untitled')
        source = article.get('source', 'Unknown')
        digest_lines.extend([
            f"**{i}. {title}**",
            f"📺 *{source}*",
            ""
        ])

    digest_lines.extend([
        "",
        "🎙️ **Omni View Daily Podcast Link:** https://podcasts.apple.com/us/podcast/omni-view/idXXXXXXXXXX",
        "",
        "#OmniView #BalancedNews #MediaLiteracy"
    ])

    return "\n".join(digest_lines)

def generate_omni_view_script(news_articles):
    """Generate podcast script for Omni View."""
    # This is a placeholder - will be implemented with Grok AI
    logging.info("Generating Omni View podcast script...")

    script_lines = [
        "Welcome to Omni View, your daily source for balanced news perspectives.",
        "",
        f"Today is {datetime.datetime.now().strftime('%B %d, %Y')}.",
        "",
        "Here are the key stories from diverse sources, presented with multiple viewpoints:",
        ""
    ]

    for i, article in enumerate(news_articles[:8], 1):  # Limit for podcast length
        title = article.get('title', 'Untitled')
        source = article.get('source', 'Unknown')
        script_lines.extend([
            f"Story number {i}: {title}",
            f"This story is covered by {source}.",
            ""
        ])

    script_lines.extend([
        "",
        "Thank you for listening to Omni View. Remember, informed citizens make better decisions.",
        "Stay curious, stay balanced."
    ])

    return "\n".join(script_lines)

def create_omni_view_podcast(script_text):
    """Create the podcast audio file."""
    # This is a placeholder - will be implemented with TTS
    logging.info("Creating Omni View podcast audio...")

    # For now, return a dummy file path and duration
    audio_file = digests_dir / f"Omni_View_Ep{get_next_episode_number(project_root / 'omni_view_podcast.rss', digests_dir):03d}_{datetime.datetime.now():%Y%m%d}.mp3"
    duration = 600  # 10 minutes placeholder

    logging.info(f"Podcast audio would be saved to: {audio_file}")
    return audio_file, duration

def update_omni_view_rss_feed(audio_file, duration):
    """Update the Omni View RSS feed."""
    logging.info("Updating Omni View RSS feed...")

    rss_path = project_root / "omni_view_podcast.rss"
    base_url = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"

    fg = FeedGenerator()
    fg.load_extension('podcast')

    # Set channel metadata
    fg.title("Omni View - Balanced News Perspectives")
    fg.link(href="https://patricknovak.github.io/Tesla-shorts-time/omni-view-summaries.html")
    fg.description("Daily balanced news summaries presenting multiple perspectives on the stories that matter. Countering media bias through diverse sources and critical analysis.")
    fg.language('en-us')
    fg.copyright("Copyright 2025")
    fg.generator("python-feedgen")
    fg.podcast.itunes_author("Omni View")
    fg.podcast.itunes_summary("Daily balanced news summaries presenting multiple perspectives on the stories that matter. Countering media bias through diverse sources and critical analysis.")
    fg.podcast.itunes_owner(name='Omni View', email='omniview@teslashortstime.com')
    fg.podcast.itunes_image(f"{base_url}/omni-view-podcast-image.jpg")
    fg.podcast.itunes_category("News")
    fg.podcast.itunes_explicit("no")

    # Get episode number
    episode_num = get_next_episode_number(project_root / "omni_view_podcast.rss", digests_dir)

    # Create episode title and description
    today = datetime.datetime.now().strftime("%B %d, %Y")
    episode_title = f"Omni View - Balanced News Digest - {today}"
    episode_description = f"Daily balanced news summary for {today}. Multiple perspectives on the stories shaping our world from diverse sources across the political spectrum."

    # Calculate file size
    try:
        mp3_size = audio_file.stat().st_size
    except:
        mp3_size = 0

    # Format duration
    duration_str = format_duration(duration)

    # Create GUID
    episode_guid = f"omni-view-ep{episode_num:03d}-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"

    # Add episode to feed
    entry = fg.add_entry()
    entry.id(episode_guid)
    entry.title(episode_title)
    entry.description(episode_description)
    entry.link(href=f"{base_url}/digests/{audio_file.name}")
    entry.pubDate(datetime.datetime.now(datetime.timezone.utc))
    entry.enclosure(url=f"{base_url}/digests/{audio_file.name}", type="audio/mpeg", length=str(mp3_size))
    entry.podcast.itunes_title(episode_title)
    entry.podcast.itunes_summary(episode_description)
    entry.podcast.itunes_duration(duration_str)
    entry.podcast.itunes_episode(str(episode_num))
    entry.podcast.itunes_season('1')
    entry.podcast.itunes_episode_type('full')
    entry.podcast.itunes_explicit("no")
    entry.podcast.itunes_image(f"{base_url}/omni-view-podcast-image.jpg")

    # Set last build date
    fg.lastBuildDate(datetime.datetime.now(datetime.timezone.utc))

    # Write to file
    fg.rss_file(str(rss_path), pretty=True)

    logging.info(f"RSS feed updated with Episode {episode_num} at {rss_path}")

def get_next_episode_number(rss_path: Path, digests_dir: Path) -> int:
    """Get the next episode number based on existing files."""
    try:
        if rss_path.exists():
            tree = ET.parse(rss_path)
            root = tree.getroot()
            items = root.findall('.//item')
            if items:
                return len(items) + 1
    except Exception:
        pass

    # Fallback: count existing MP3 files
    mp3_pattern = "Omni_View_Ep*.mp3"
    existing_episodes = list(digests_dir.glob(mp3_pattern))
    if existing_episodes:
        episode_nums = []
        for ep_file in existing_episodes:
            match = re.search(r'Ep(\d+)', ep_file.name)
            if match:
                episode_nums.append(int(match.group(1)))
        return max(episode_nums) + 1 if episode_nums else 1

    return 1

def format_duration(seconds):
    """Format duration in seconds to HH:MM:SS or MM:SS format."""
    if not seconds or seconds <= 0:
        return "00:00"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"

# ========================== MAIN EXECUTION ==========================
if __name__ == "__main__":
    # Load environment variables
    load_dotenv()

    # Set up paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    digests_dir = project_root / "digests"

    # Initialize credit usage tracking
    episode_num = get_next_episode_number(project_root / "omni_view_podcast.rss", digests_dir)
    credit_usage = {
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
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

    # Initialize clients
    client = OpenAI(
        api_key=os.getenv("GROK_API_KEY"),
        base_url="https://api.x.ai/v1",
        timeout=300.0
    )

    # X client setup
    try:
        import tweepy
        x_client = tweepy.Client(
            consumer_key=os.getenv("X_CONSUMER_KEY"),
            consumer_secret=os.getenv("X_CONSUMER_SECRET"),
            access_token=os.getenv("X_ACCESS_TOKEN"),
            access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
            bearer_token=os.getenv("X_BEARER_TOKEN")
        )
        logging.info("X client initialized successfully")
    except Exception as e:
        logging.warning(f"Failed to initialize X client: {e}")
        x_client = None

    # Initialize variables
    audio_files = []
    voice_mix = None

    logging.info("="*80)
    logging.info("OMNI VIEW — BALANCED NEWS DIGEST")
    logging.info("="*80)

    # ========================== STEP 1: FETCH BALANCED NEWS ==========================
    balanced_news, raw_news_articles = fetch_balanced_news()

    # ========================== STEP 2: GENERATE X THREAD FROM NEWS ==========================
    logging.info("Step 2: Generating balanced news summary thread...")

    # Generate the X thread
    x_thread = generate_balanced_news_digest(balanced_news)

    # ========================== STEP 3: GENERATE PODCAST SCRIPT ==========================
    logging.info("Step 3: Generating podcast script...")

    podcast_script = generate_omni_view_script(balanced_news)

    # ========================== STEP 4: CREATE PODCAST AUDIO ==========================
    logging.info("Step 4: Creating podcast audio...")

    if ENABLE_PODCAST:
        final_mp3, audio_duration = create_omni_view_podcast(podcast_script)
    else:
        final_mp3 = None
        audio_duration = 0
        logging.info("Podcast generation disabled")

    # ========================== STEP 5: UPDATE RSS FEED ==========================
    logging.info("Step 5: Updating RSS feed...")

    if ENABLE_PODCAST and final_mp3:
        update_omni_view_rss_feed(final_mp3, audio_duration)

    # ========================== POST TO X AND SAVE SUMMARY ==========================
    if ENABLE_GITHUB_SUMMARIES:
        try:
            # Save the full summary to GitHub Pages JSON
            summary_json_file = save_summary_to_github_pages(x_thread.strip(), digests_dir, "omni")
            if summary_json_file:
                logging.info("Summary saved to GitHub Pages successfully")
            else:
                logging.warning("Failed to save summary to GitHub Pages")
        except Exception as e:
            logging.error(f"Failed to save summary to GitHub Pages: {e}")

    # Post link to GitHub Pages summary on X instead of full content
    if ENABLE_X_POSTING:
        try:
            # Create link to the Omni View summaries page
            summaries_url = "https://patricknovak.github.io/Tesla-shorts-time/omni-view-summaries.html"

            # Create a teaser post with link to full summary
            today = datetime.datetime.now()
            teaser_text = f"""📰⚖️ Omni View - {today.strftime('%B %d, %Y')}

🔍 Today's balanced news digest presents multiple perspectives on the stories shaping our world.

📊 Diverse sources, fact-based reporting, and context you can trust
🎙️ Full podcast episode available
📈 Understanding different viewpoints for informed decisions

Read the complete balanced analysis: {summaries_url}

#OmniView #BalancedNews #MediaLiteracy"""

            # Track X API post call
            credit_usage["services"]["x_api"]["post_calls"] += 1

            # Post the teaser with link
            if x_client:
                tweet = x_client.create_tweet(text=teaser_text)
                tweet_id = tweet.data['id']
                thread_url = f"https://x.com/omniviewnews/status/{tweet_id}"
                logging.info(f"DIGEST LINK POSTED → {thread_url}")
            else:
                logging.warning("X client not initialized - skipping X post")
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

    # Save credit usage tracking
    save_credit_usage(credit_usage, digests_dir)

    logging.info("Omni View processing complete!")