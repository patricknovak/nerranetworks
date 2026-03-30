#!/usr/bin/env python3
"""
Omni View – FULL AUTO X + PODCAST MACHINE
Daily Balanced News Digest (Patrick in Vancouver)
Auto-published to X — January 2026+

.. deprecated::
    This legacy script is no longer used in production.
    All shows now run via ``python run_show.py omni_view``.
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
from openai import OpenAI
from openai import RateLimitError, PermissionDeniedError, APIStatusError
from difflib import SequenceMatcher
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont
import feedparser
from typing import List, Dict, Any
from threading import Lock

# ========================== ENGINE IMPORTS ==========================
from engine.utils import (
    number_to_words as _engine_number_to_words,
    remove_similar_items as _engine_remove_similar_items,
    env_bool,
)
from engine.audio import get_audio_duration, format_duration
from engine.publisher import (
    get_next_episode_number as _engine_get_next_episode_number,
    save_summary_to_github_pages as _engine_save_summary,
    update_rss_feed as _engine_update_rss_feed,
    post_to_x as _engine_post_to_x,
)
from engine.tracking import create_tracker, save_usage as _engine_save_usage
from engine.tts import synthesize as _engine_synthesize
from engine.content_tracker import ContentTracker, OV_SECTION_PATTERNS
from engine.utils import deduplicate_by_entity

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

# Omni View-specific HTTP defaults (override engine defaults for this show)
DEFAULT_HEADERS = {
    "User-Agent": "OmniViewBot/1.0 (+https://x.com/omniviewnews)"
}
HTTP_TIMEOUT_SECONDS = 10

# ========================== NUMBER TO WORDS CONVERTER ==========================
# MIGRATED: engine/utils.py
number_to_words = _engine_number_to_words

# ========================== UTILITY FUNCTIONS ==========================
def fix_omni_pronunciation(text: str) -> str:
    """Prepare Omni View script text for ElevenLabs TTS.

    Delegates to the shared pronunciation module (assets/pronunciation.py)
    which handles text cleanup, number/date/time expansion, acronyms,
    unit abbreviations, and more.
    """
    from assets.pronunciation import prepare_text_for_tts
    return prepare_text_for_tts(text)

# MIGRATED: engine/utils.py
remove_similar_items = _engine_remove_similar_items

# MIGRATED: engine/tracking.py
def save_credit_usage(usage_data: dict, output_dir: Path):
    """Save credit usage to a JSON file."""
    _engine_save_usage(usage_data, output_dir)

# MIGRATED: engine/publisher.py
def save_summary_to_github_pages(
    summary_text: str,
    output_dir: Path,
    podcast_name: str = "omni",
    *,
    episode_num=None,
    episode_title=None,
    audio_url=None,
    rss_url=None,
):
    """Thin wrapper around engine.publisher.save_summary_to_github_pages."""
    # Summaries live in per-show subdirectories under digests/
    _proj_root = Path(__file__).resolve().parent.parent
    json_path = _proj_root / "digests" / "omni_view" / f"summaries_{podcast_name}.json"
    return _engine_save_summary(
        summary_text,
        json_path,
        podcast_name,
        episode_num=episode_num,
        episode_title=episode_title,
        audio_url=audio_url,
        rss_url=rss_url,
    )

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

    # Keywords for news that helps everyone (children to seniors) understand the world
    # Prioritize: major policy, safety, economy, world events, health, science, local impact
    important_keywords = [
        "election", "president", "government", "policy", "law", "court", "supreme",
        "economy", "recession", "inflation", "unemployment", "federal reserve", "jobs",
        "war", "conflict", "peace", "treaty", "sanctions", "diplomacy",
        "climate", "environment", "disaster", "weather", "storm", "flood", "fire", "energy",
        "health", "pandemic", "vaccine", "medical", "fda", "cdc", "hospital",
        "technology", "ai", "internet", "privacy", "cyber",
        "crime", "justice", "police", "protest", "civil rights", "safety",
        "international", "trade", "immigration", "borders",
        "business", "corporate", "merger", "bankruptcy", "stocks", "market",
        "education", "school", "student", "college", "university",
        "housing", "rent", "cost of living", "food", "prices",
        "science", "space", "research", "discovery",
        "sports", "championship", "olympics", "world cup",
        "breaking", "announces", "reports", "says", "deal", "agreement",
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
    Select news that is most important and widely discussed, while keeping source
    diversity. Prioritizes stories that help everyone (children to seniors) understand
    what's happening in the world. Articles are scored by importance, recency, then
    diversity is applied so we don't over-represent one outlet.
    """
    if not articles:
        return []

    importance_terms = [
        "election", "president", "government", "court", "supreme", "war", "ceasefire",
        "inflation", "jobs", "unemployment", "fed", "interest rate", "sanctions",
        "climate", "storm", "earthquake", "wildfire", "outbreak", "health", "disaster",
        "ai", "cyber", "security", "breaking", "announces", "deal", "agreement",
    ]

    def _article_importance(a):
        text = ((a.get("title") or "") + " " + (a.get("description") or "")).lower()
        return 1 if any(t in text for t in importance_terms) else 0

    def _article_recency_score(a):
        try:
            published = datetime.datetime.fromisoformat(
                (a.get("publishedAt") or "").replace("Z", "+00:00")
            )
            hours_old = (datetime.datetime.now(datetime.timezone.utc) - published).total_seconds() / 3600
            if hours_old < 6:
                return 5
            if hours_old < 12:
                return 3
            if hours_old < 24:
                return 1
        except Exception:
            pass
        return 0

    # Score all articles by importance first, then recency
    scored = [
        (_article_importance(a) * 10 + _article_recency_score(a), a)
        for a in articles
    ]
    scored.sort(key=lambda x: (x[0], x[1].get("publishedAt", "")), reverse=True)

    # Build selection: take top by score but cap per source for diversity
    source_counts: dict = {}
    max_per_source = 3
    selected = []
    for _score, article in scored:
        if len(selected) >= max_articles:
            break
        src = article.get("source") or "Unknown"
        if source_counts.get(src, 0) >= max_per_source:
            continue
        selected.append(article)
        source_counts[src] = source_counts.get(src, 0) + 1

    # Sort selected by same importance+recency (most important/discussed first)
    selected_scored = [
        (_article_importance(a) * 10 + _article_recency_score(a), a)
        for a in selected
    ]
    selected_scored.sort(key=lambda x: (x[0], x[1].get("publishedAt", "")), reverse=True)
    selected = [a for _, a in selected_scored]

    # Log the selection
    log_counts: dict = {}
    for article in selected:
        source = article.get("source", "Unknown")
        log_counts[source] = log_counts.get(source, 0) + 1
    logging.info(f"Selected {len(selected)} news articles (importance + discussion first):")
    for source, count in sorted(log_counts.items()):
        logging.info(f"  {source}: {count} article(s)")

    return selected[:max_articles]

# ========================== MAIN EXECUTION ==========================
# All execution code is in the if __name__ == "__main__" block below

# ========================== IMPLEMENTATION FUNCTIONS ==========================

# REMOVED: dead code — superseded by generate_balanced_news_digest() below (line ~855)

# MIGRATED: engine/publisher.py
def get_next_episode_number(rss_path: Path, digests_dir: Path) -> int:
    return _engine_get_next_episode_number(rss_path, digests_dir, mp3_glob_pattern="Omni_View_Ep*.mp3")


def _source_buckets():
    # Reuse the same sets as selection logic (keep centralized)
    left_sources = {"CNN", "New York Times", "Washington Post", "NPR", "BBC", "The Guardian", "Al Jazeera"}
    center_sources = {"Reuters", "Wall Street Journal", "Bloomberg", "CNBC", "Real Clear Politics"}
    right_sources = {"Fox News", "Newsmax", "Breitbart", "Daily Mail"}
    international_sources = {"France 24", "Deutsche Welle"}
    alternative_sources = {"The Intercept", "Mother Jones", "Reason"}
    tech_sources = {"Wired", "Ars Technica"}
    return {
        "Center/Left": left_sources,
        "Center": center_sources,
        "Center/Right": right_sources,
        "International": international_sources,
        "Independent": alternative_sources,
        "Tech/Science": tech_sources,
    }


def _bucket_for_source(source: str) -> str:
    s = (source or "").strip()
    for bucket, sources in _source_buckets().items():
        if s in sources:
            return bucket
    return "Other"


def _norm_story_key(text: str) -> str:
    t = (text or "").lower()
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # light stopword removal for clustering
    stop = {"the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "as", "at", "by", "from"}
    parts = [p for p in t.split() if p not in stop]
    return " ".join(parts)[:220]


def _cluster_articles(articles: list[dict], similarity_threshold: float = 0.78) -> list[dict]:
    """
    Cluster articles that appear to describe the same story, based primarily on title similarity.
    Output clusters contain a representative title and the list of article dicts.
    """
    clusters: list[dict] = []
    for a in (articles or []):
        title = (a.get("title") or "").strip()
        if not title:
            continue
        key = _norm_story_key(title)
        placed = False
        for c in clusters:
            sim = SequenceMatcher(None, key, c["key"]).ratio()
            if sim >= similarity_threshold:
                c["articles"].append(a)
                # prefer a "cleaner" representative title if this one is longer but not clickbaity
                if len(title) > len(c["title"]) and len(title) < 140:
                    c["title"] = title
                placed = True
                break
        if not placed:
            clusters.append({"key": key, "title": title, "articles": [a]})
    return clusters


def _parse_iso(dt_str: str) -> datetime.datetime:
    try:
        return datetime.datetime.fromisoformat((dt_str or "").replace("Z", "+00:00"))
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc)


def _score_cluster(cluster: dict) -> float:
    arts = cluster.get("articles") or []
    sources = {a.get("source") for a in arts if a.get("source")}
    buckets = {_bucket_for_source(a.get("source")) for a in arts if a.get("source")}
    latest = max((_parse_iso(a.get("publishedAt", "")) for a in arts), default=datetime.datetime.now(datetime.timezone.utc))
    hours_old = (datetime.datetime.now(datetime.timezone.utc) - latest).total_seconds() / 3600.0

    # Basic importance heuristic
    title = (cluster.get("title") or "").lower()
    importance_terms = [
        "election", "president", "government", "court", "supreme", "war", "ceasefire", "strike",
        "inflation", "jobs", "unemployment", "fed", "interest rate", "sanctions", "trade",
        "climate", "storm", "earthquake", "wildfire", "outbreak", "health", "ai", "cyber", "security",
    ]
    importance = 2.0 if any(t in title for t in importance_terms) else 0.0

    recency = max(0.0, 6.0 - min(hours_old, 48.0) / 8.0)  # ~6 down to 0
    coverage = min(len(sources), 6) * 1.3
    bucket_cov = min(len(buckets), 5) * 2.0
    return importance + recency + coverage + bucket_cov


def _category_for_title(title: str) -> str:
    """
    Assign one primary category for the story based on headline keywords.
    Categories are tailored to the Omni View sectioning requirement.
    """
    t = (title or "").lower()

    # Gossip (celebrity/tabloid/drama)
    gossip_terms = [
        "divorce", "dating", "breakup", "split", "engaged", "engagement", "pregnant", "affair",
        "scandal", "rumor", "rumour", "feud", "caught", "spotted", "exclusive", "sources say",
        "kardash", "royal", "prince", "princess",
    ]
    if any(w in t for w in gossip_terms):
        return "gossip"

    # Popular media (culture/entertainment/sports that isn't gossip-centric)
    media_terms = [
        "movie", "film", "box office", "tv", "series", "netflix", "hbo", "disney", "marvel",
        "music", "album", "tour", "grammy", "oscar", "emmy",
        "sports", "nba", "nfl", "nhl", "mlb", "soccer", "football", "olympic", "world cup",
        "celebrity", "hollywood", "entertainment",
    ]
    if any(w in t for w in media_terms):
        return "popular_media"

    # Technology
    tech_terms = [
        "ai", "artificial intelligence", "chatgpt", "openai", "grok", "xai",
        "cyber", "hack", "breach", "ransomware", "security", "privacy",
        "chip", "semiconductor", "nvidia", "amd", "intel",
        "smartphone", "iphone", "android", "google", "microsoft", "apple",
        "software", "internet", "social media", "platform", "algorithm",
        "space", "rocket", "spacex", "satellite",
    ]
    if any(w in t for w in tech_terms):
        return "technology"

    # Business
    business_terms = [
        "stocks", "market", "shares", "earnings", "revenue", "profit", "loss",
        "ipo", "merger", "acquisition", "bankruptcy", "layoff", "union",
        "inflation", "recession", "jobs report", "unemployment", "interest rate", "fed",
        "oil", "gas", "price", "tariff", "trade", "supply chain",
        "bitcoin", "crypto", "cryptocurrency",
        "ceo", "company", "corporate",
    ]
    if any(w in t for w in business_terms):
        return "business"

    # World (international / conflict / diplomacy / non-domestic)
    world_terms = [
        "ukraine", "russia", "gaza", "israel", "palest", "iran", "iraq", "syria", "yemen",
        "china", "taiwan", "north korea", "south korea", "japan", "india", "pakistan",
        "europe", "eu", "nato", "un", "united nations",
        "africa", "sahel", "sudan", "ethiopia",
        "mexico", "brazil", "argentina",
        "diplomacy", "sanctions", "ceasefire", "war", "conflict", "missile", "attack", "invasion",
        "refugee", "immigration", "border",
    ]
    if any(w in t for w in world_terms):
        return "world"

    # Default "top stories" (domestic/general)
    return "top"


def _category_for_cluster(cluster: dict) -> str:
    return _category_for_title(cluster.get("title") or "")


def _select_story_sections(
    clusters: list[dict],
    *,
    top_n: int = 5,
    world_n: int = 5,
    business_n: int = 3,
    tech_n: int = 3,
    popular_media_n: int = 3,
    gossip_n: int = 3,
) -> dict[str, list[dict]]:
    """
    Select non-overlapping story clusters for each required section.
    """
    scored = sorted(((_score_cluster(c), c) for c in clusters), key=lambda x: x[0], reverse=True)
    used: set[str] = set()

    def pick(category: str, n: int) -> list[dict]:
        picked: list[dict] = []
        for _, c in scored:
            if len(picked) >= n:
                break
            key = c.get("key") or ""
            if not key or key in used:
                continue
            if _category_for_cluster(c) != category:
                continue
            picked.append(c)
            used.add(key)
        return picked

    sections = {
        "Top stories": pick("top", top_n),
        "Top world stories": pick("world", world_n),
        "Top business stories": pick("business", business_n),
        "Top technology stories": pick("technology", tech_n),
        "Top popular media stories": pick("popular_media", popular_media_n),
        "Top gossip stories": pick("gossip", gossip_n),
    }

    # If any section is short, fill from remaining highest-scoring unused clusters
    for section_name, target in [
        ("Top stories", top_n),
        ("Top world stories", world_n),
        ("Top business stories", business_n),
        ("Top technology stories", tech_n),
        ("Top popular media stories", popular_media_n),
        ("Top gossip stories", gossip_n),
    ]:
        need = target - len(sections[section_name])
        if need <= 0:
            continue
        desired_cat = {
            "Top stories": "top",
            "Top world stories": "world",
            "Top business stories": "business",
            "Top technology stories": "technology",
            "Top popular media stories": "popular_media",
            "Top gossip stories": "gossip",
        }[section_name]

        # First pass: same category
        for _, c in scored:
            if need <= 0:
                break
            key = c.get("key") or ""
            if not key or key in used:
                continue
            if _category_for_cluster(c) != desired_cat:
                continue
            sections[section_name].append(c)
            used.add(key)
            need -= 1

        # Second pass: any remaining
        for _, c in scored:
            if need <= 0:
                break
            key = c.get("key") or ""
            if not key or key in used:
                continue
            sections[section_name].append(c)
            used.add(key)
            need -= 1

    return sections


def _pick_diverse_articles(cluster: dict, max_articles: int = 6) -> list[dict]:
    """
    Pick a diverse set of articles within a cluster, prioritizing different buckets/sources.
    """
    arts = list(cluster.get("articles") or [])
    if not arts:
        return []
    # newest first
    arts.sort(key=lambda x: x.get("publishedAt", ""), reverse=True)

    picked: list[dict] = []
    used_sources: set[str] = set()
    used_buckets: set[str] = set()
    bucket_priority = ["Center", "Center/Left", "Center/Right", "International", "Independent", "Tech/Science", "Other"]

    # First: try to get one per bucket
    for b in bucket_priority:
        for a in arts:
            s = (a.get("source") or "").strip()
            if not s or s in used_sources:
                continue
            if _bucket_for_source(s) != b:
                continue
            picked.append(a)
            used_sources.add(s)
            used_buckets.add(b)
            break
        if len(picked) >= max_articles:
            return picked

    # Fill: remaining newest unique sources
    for a in arts:
        if len(picked) >= max_articles:
            break
        s = (a.get("source") or "").strip()
        if not s or s in used_sources:
            continue
        picked.append(a)
        used_sources.add(s)
    return picked


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    retry=retry_if_exception_type((Exception,)),
)
def _grok_balanced_briefing(story_payload: dict) -> str:
    """
    Use Grok to write the Omni View briefing.
    Must only cite the URLs we provide in the payload.
    """
    prompt = f"""
You are Omni View — a neutral, media-literacy-first daily briefing for everyone from children to seniors.
Your job: help people understand what is happening in the world and around them WITHOUT promoting any single outlet.

Use ONLY the information in the provided story list (titles + short descriptions) and ONLY cite the provided URLs.
Do NOT invent sources, links, quotes, or specific facts not supported by what’s provided.
If details are unclear, say what is uncertain and what to verify.

Ordering: Present the most important and widely discussed news first. Within each section, put the biggest and most talked-about stories first. The "Top stories" section must contain the five most important items of the day.

Write a single website-friendly markdown briefing with this exact structure and section sizes:

# Omni View — Omni‑View Briefing
**Date:** {story_payload.get("date_human")}

## Top stories (5)
## Top world stories (5)
## Top business stories (3)
## Top technology stories (3)
## Top popular media stories (3)
## Top gossip stories (3)

Critical rules:
- Do NOT repeat the same story across sections.
- Use ONLY the stories and URLs provided in the JSON. Do NOT invent any sources, links, or facts.
- If the provided sources conflict, describe the disagreement neutrally.

Under each section, for each story:
### <N>) <short neutral headline>
**What happened (neutral):** 2–4 sentences in plain language so any reader can follow.

**Perspectives:** Write 3–6 sentences in flowing prose (do not number or label individual perspectives). Weave together how different outlets or groups frame this story so readers see multiple viewpoints naturally. Be slightly more detailed than a single sentence per view.

**Questions to consider:** 2–4 bullets (use '-' bullets).
**Read more (sources):** 3–6 bullets, each as a markdown link like `- [Source](URL) — short note`

Then end with:
## Media-literacy note
2–4 sentences encouraging cross-checking and primary documents.

Here are the sections, stories, and allowed sources (JSON). Again: ONLY use these URLs in the Read more section:

{json.dumps(story_payload.get("sections", {}), ensure_ascii=False, indent=2)}
""".strip()

    # Grok call (mirrors Tesla script patterns)
    resp = client.chat.completions.create(
        model=os.getenv("GROK_MODEL", "grok-4.20-non-reasoning"),
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_tokens=3200,
    )
    text = resp.choices[0].message.content.strip()

    # Track token usage/cost (best-effort)
    try:
        if hasattr(resp, "usage") and resp.usage:
            usage = resp.usage
            est_cost = (usage.total_tokens / 1_000_000) * 0.01
            credit_usage["services"]["grok_api"]["x_thread_generation"]["prompt_tokens"] = usage.prompt_tokens
            credit_usage["services"]["grok_api"]["x_thread_generation"]["completion_tokens"] = usage.completion_tokens
            credit_usage["services"]["grok_api"]["x_thread_generation"]["total_tokens"] = usage.total_tokens
            credit_usage["services"]["grok_api"]["x_thread_generation"]["estimated_cost_usd"] = est_cost
    except Exception:
        pass

    return text


def generate_balanced_news_digest(news_articles: list[dict]) -> str:
    """
    Generate Omni View’s core product:
    - A list of TOP STORIES (clustered across outlets)
    - For each: neutral recap, multiple perspectives, questions, and source links
    """
    today_human = datetime.datetime.now().strftime("%B %d, %Y")
    if not news_articles:
        return "\n".join([
            "# Omni View — Balanced Briefing",
            f"**Date:** {today_human}",
            "",
            "No stories were found from the configured RSS sources in the last 24 hours.",
        ])

    # Cluster headlines into "stories", then select unique stories per required section
    clusters = _cluster_articles(news_articles, similarity_threshold=0.78)
    scored = sorted(((_score_cluster(c), c) for c in clusters), key=lambda x: x[0], reverse=True)

    targets: dict[str, int] = {
        "Top stories": 5,
        "Top world stories": 5,
        "Top business stories": 3,
        "Top technology stories": 3,
        "Top popular media stories": 3,
        "Top gossip stories": 3,
    }
    desired_cat: dict[str, str] = {
        "Top stories": "top",
        "Top world stories": "world",
        "Top business stories": "business",
        "Top technology stories": "technology",
        "Top popular media stories": "popular_media",
        "Top gossip stories": "gossip",
    }

    used: set[str] = set()
    sections_payload: dict[str, list[dict]] = {k: [] for k in targets.keys()}

    def _build_story(cluster: dict, rank: int) -> dict | None:
        picked = _pick_diverse_articles(cluster, max_articles=6)
        src_rows = []
        for a in picked:
            url = (a.get("url") or "").strip()
            if not url:
                continue
            src_rows.append(
                {
                    "source": (a.get("source") or "").strip(),
                    "bucket": _bucket_for_source(a.get("source") or ""),
                    "title": (a.get("title") or "").strip(),
                    "description": (a.get("description") or "").strip()[:320],
                    "url": url,
                }
            )
        if not src_rows:
            return None

        distinct_sources = {r.get("source") for r in src_rows if r.get("source")}
        story = {
            "rank": rank,
            "topic_title": (cluster.get("title") or "").strip(),
            "category": _category_for_cluster(cluster),
            "source_count": len(distinct_sources),
            "sources": src_rows,
        }
        if story["source_count"] < 2:
            story["coverage_note"] = "Only one distinct source available in our feeds for this story today."
        return story

    def _try_add(section: str, cluster: dict) -> bool:
        key = cluster.get("key") or ""
        if not key or key in used:
            return False
        story = _build_story(cluster, rank=len(sections_payload[section]) + 1)
        if not story:
            return False
        sections_payload[section].append(story)
        used.add(key)
        return True

    # Pass 1: fill "Top stories" with the 5 highest-scoring clusters (any category)
    # so the most important and widely discussed news leads the briefing
    for _, c in scored:
        if len(sections_payload["Top stories"]) >= targets["Top stories"]:
            break
        _try_add("Top stories", c)

    # Pass 2: fill other sections by category (world, business, tech, etc.)
    for section, n in targets.items():
        if section == "Top stories":
            continue
        cat = desired_cat[section]
        for _, c in scored:
            if len(sections_payload[section]) >= n:
                break
            if _category_for_cluster(c) != cat:
                continue
            _try_add(section, c)

    # Pass 3: top up any short section from remaining best stories (any category), still unique
    for section, n in targets.items():
        for _, c in scored:
            if len(sections_payload[section]) >= n:
                break
            _try_add(section, c)

    total_selected = sum(len(v) for v in sections_payload.values())
    if total_selected < 8:
        digest_lines = [
            "# Omni View — Balanced Briefing",
            f"**Date:** {today_human}",
            "",
            "## Top stories (single-source fallback)",
            "Not enough overlap across sources today to build multi-source clusters. Here are the top headlines we found:",
            "",
        ]
        for i, a in enumerate(news_articles[:10], 1):
            title = (a.get("title") or "Untitled").strip()
            source = (a.get("source") or "Unknown").strip()
            url = (a.get("url") or "").strip()
            if url:
                digest_lines.append(f"- **{i}.** {title} — *{source}* ([link]({url}))")
            else:
                digest_lines.append(f"- **{i}.** {title} — *{source}*")
        digest_lines += [
            "",
            "## Media-literacy note",
            "Compare multiple outlets when possible, watch for loaded language, and look for primary documents or official statements.",
        ]
        return "\n".join(digest_lines)

    payload = {"date_human": today_human, "sections": sections_payload}

    try:
        return _grok_balanced_briefing(payload)
    except PermissionDeniedError as e:
        logging.error(f"Grok permission denied: {e}")
    except RateLimitError as e:
        logging.error(f"Grok rate limited: {e}")
    except APIStatusError as e:
        logging.error(f"Grok API status error: {e}")
    except Exception as e:
        logging.error(f"Grok briefing generation failed: {e}")

    # Last-resort fallback (no Grok)
    digest_lines = [
        "# Omni View — Balanced Briefing",
        f"**Date:** {today_human}",
        "",
        "## Top stories (raw)",
        "Grok briefing generation failed, so this is a raw list of candidate stories and links:",
        "",
    ]
    for section_name, stories in sections_payload.items():
        digest_lines.append(f"## {section_name}")
        for i, s in enumerate((stories or [])[:8], 1):
            digest_lines.append(f"### {i}) {s.get('topic_title','Story').strip()}")
            digest_lines.append("**Read more (sources):**")
            for src in (s.get("sources") or [])[:6]:
                digest_lines.append(f"- [{src.get('source','Source')}]({src.get('url','')})")
            digest_lines.append("")
    return "\n".join(digest_lines)


def generate_omni_view_script(briefing_markdown: str) -> str:
    """
    Create a spoken-friendly script from the website briefing.
    Keeps the podcast punchy (no long link lists) while still sounding like a daily news read.
    """
    today = datetime.datetime.now().strftime("%B %d, %Y")

    def _strip_md(s: str) -> str:
        # Drop markdown links down to label + remove emphasis markers
        s = re.sub(r"\[([^\]]+)\]\(https?://[^\)]+\)", r"\1", s)
        s = re.sub(r"https?://\S+", "", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
        s = re.sub(r"\*([^*]+)\*", r"\1", s)
        return s.strip()

    def _after_colon(ln: str) -> str:
        parts = ln.split(":", 1)
        if len(parts) == 2:
            return _strip_md(parts[1])
        return ""

    text = _strip_md(briefing_markdown or "")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Parse the structured Grok website briefing.
    stories: list[dict] = []
    current_section = ""
    cur: dict | None = None
    in_questions = False
    in_perspectives = False
    perspective_lines: list[str] = []

    for ln in lines:
        if ln.startswith("## "):
            if cur and in_perspectives and perspective_lines:
                cur["perspectives"] = [" ".join(perspective_lines).strip()]
            in_perspectives = False
            perspective_lines = []
            current_section = ln[3:].strip()
            current_section = re.sub(r"\s*\(\d+\)\s*$", "", current_section).strip()
            continue

        if ln.startswith("### "):
            if cur and in_perspectives and perspective_lines:
                cur["perspectives"] = [" ".join(perspective_lines).strip()]
            in_perspectives = False
            perspective_lines = []
            if cur:
                stories.append(cur)
            raw_title = ln[4:].strip()
            raw_title = re.sub(r"^\d+\)\s*", "", raw_title).strip()
            cur = {
                "section": current_section,
                "title": raw_title,
                "what": "",
                "perspectives": [],
                "questions": [],
            }
            in_questions = False
            continue

        if not cur:
            continue

        low = ln.lower()
        if low.startswith("what happened"):
            in_perspectives = False
            perspective_lines = []
            cur["what"] = _after_colon(ln)
            in_questions = False
            continue
        if low.startswith("why it matters"):
            # No longer used; skip this line
            in_questions = False
            continue
        if low.startswith("questions to consider"):
            if in_perspectives and perspective_lines:
                cur["perspectives"] = [" ".join(perspective_lines).strip()]
            in_perspectives = False
            perspective_lines = []
            in_questions = True
            continue

        if in_questions and ln.startswith("- "):
            q = ln[2:].strip()
            if q:
                cur["questions"].append(q)
            continue

        # Perspectives: either a block of prose (new format) or numbered bullets (legacy)
        if low.startswith("**perspectives") or (low.startswith("perspectives") and ":" in ln[:20]):
            in_perspectives = True
            perspective_lines = []
            after_colon = _after_colon(ln)
            if after_colon:
                perspective_lines.append(after_colon)
            in_questions = False
            continue
        if in_perspectives:
            # End perspectives block on a new bold header
            if ln.strip().startswith("**") and not ln.strip().lower().startswith("**perspectives"):
                if perspective_lines:
                    cur["perspectives"] = [" ".join(perspective_lines).strip()]
                in_perspectives = False
                perspective_lines = []
                # Re-process this line (could be Questions to consider)
                if "questions to consider" in ln.lower():
                    in_questions = True
                continue
            perspective_lines.append(ln.strip())
            continue

        if ln.startswith("- ") and "perspective" in low[:25]:
            # Legacy: "- Perspective 1: ..." (explicit numbering)
            p = re.sub(r"^-+\s*", "", ln).strip()
            p = re.sub(r"^Perspective\s*\d*\s*:\s*", "", p, flags=re.IGNORECASE).strip()
            if p:
                cur["perspectives"].append(p)
            continue

    if cur:
        if in_perspectives and perspective_lines:
            cur["perspectives"] = [" ".join(perspective_lines).strip()]
        stories.append(cur)

    # Fallback: if structure is missing, use bullet headlines
    if not stories:
        titles = []
        for ln in lines:
            if ln.startswith("- ") and len(titles) < 8:
                titles.append(ln[2:].strip())
        stories = [{"section": "Top stories", "title": t, "what": "", "perspectives": [], "questions": []} for t in titles]

    # Keep this listenable: pick a tight set across sections
    max_stories = 7
    picked: list[dict] = []
    for s in stories:
        if len(picked) >= max_stories:
            break
        picked.append(s)

    section_intro = {
        "Top stories": "First, here are the top stories of the day.",
        "Top world stories": "Now, a quick scan of the world headlines.",
        "Top business stories": "In business and the economy.",
        "Top technology stories": "In tech.",
        "Top popular media stories": "And in culture and popular media.",
        "Top gossip stories": "Finally, a quick round of lighter headlines.",
    }
    transitions = [
        "Next.",
        "Meanwhile.",
        "Also in the mix today.",
        "Here’s another one to watch.",
        "And one more story worth your attention.",
    ]

    script: list[str] = []
    script.append("Good morning. This is Omni View — balanced news perspectives.")
    script.append(f"Today is {today}.")
    script.append("")
    script.append("We’ll cover what happened, how different viewpoints frame it — so you can decide for yourself.")
    script.append("")

    last_section = None
    t_i = 0
    for idx, s in enumerate(picked, 1):
        sec = (s.get("section") or "").strip() or "Top stories"
        if sec != last_section:
            script.append(section_intro.get(sec, f"Now, {sec.lower()}."))
            script.append("")
            last_section = sec

        if idx > 1:
            script.append(transitions[t_i % len(transitions)])
            t_i += 1

        title = (s.get("title") or "A developing story").strip()
        what = (s.get("what") or "").strip()
        perspectives = s.get("perspectives") or []
        questions = s.get("questions") or []

        script.append(title + ".")
        if what:
            script.append(what)

        # Perspectives: one prose block (new format) or list of short views (legacy)
        if perspectives:
            p1 = (perspectives[0] or "").strip()
            if p1:
                if len(perspectives) > 1:
                    p2 = (perspectives[1] or "").strip()
                    script.append("Across perspectives: " + p1 + " " + p2)
                else:
                    script.append("Across perspectives: " + p1)

        if questions:
            q = questions[0].strip()
            script.append("Question to consider: " + q)

        script.append("")

    script.append("That’s Omni View.")
    script.append("For full source links and more context, open today’s written briefing on the Omni View summaries page.")
    script.append("As always: compare outlets, look for primary documents, and separate what’s known from what’s assumed.")

    return fix_omni_pronunciation("\n".join(script))


# MIGRATED: engine/tts.py (_chunk_text_for_elevenlabs, _elevenlabs_tts_mp3)
# MIGRATED: engine/audio.py (_ffprobe_duration_seconds → get_audio_duration)

def create_omni_view_podcast(script_text: str) -> tuple[Path, float]:
    """Create an MP3 using ElevenLabs via engine.tts.synthesize."""
    episode_num = get_next_episode_number(project_root / "omni_view_podcast.rss", digests_dir)
    out_mp3 = digests_dir / f"Omni_View_Ep{episode_num:03d}_{datetime.datetime.now():%Y%m%d}.mp3"

    voice_id = (os.getenv("OMNI_VIEW_ELEVENLABS_VOICE_ID") or "ns7MjJ6c8tJKnvw7U6sN").strip()
    api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")

    _engine_synthesize(
        script_text,
        voice_id,
        out_mp3,
        api_key=api_key,
        max_chars=int(os.getenv("ELEVENLABS_MAX_CHARS", "4500")),
        model_id=os.getenv("ELEVENLABS_MODEL_ID", "eleven_v3"),
        stability=float(os.getenv("ELEVENLABS_STABILITY", "0.65")),
        similarity_boost=float(os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.9")),
        style=float(os.getenv("ELEVENLABS_STYLE", "0.85")),
        append_exclamation=False,
    )

    duration = get_audio_duration(out_mp3)
    # Save transcript alongside
    transcript_path = digests_dir / f"omni_view_transcript_{datetime.datetime.now():%Y%m%d}.txt"
    transcript_path.write_text(script_text, encoding="utf-8")
    return out_mp3, duration

# MIGRATED: engine/publisher.py (update_omni_view_rss_feed → update_rss_feed)
def update_omni_view_rss_feed(audio_file, duration):
    """Update the Omni View RSS feed via engine.publisher.update_rss_feed."""
    rss_path = project_root / "omni_view_podcast.rss"
    base_url = "https://nerranetwork.com"
    episode_num = get_next_episode_number(rss_path, digests_dir)
    today = datetime.datetime.now().strftime("%B %d, %Y")

    _engine_update_rss_feed(
        rss_path,
        episode_num=episode_num,
        episode_title=f"Omni View - Balanced News Digest - {today}",
        episode_description=(
            f"Daily balanced news summary for {today}. Multiple perspectives on the "
            "stories shaping our world from diverse sources across the political spectrum."
        ),
        episode_date=datetime.date.today(),
        mp3_filename=audio_file.name,
        mp3_duration=duration,
        mp3_path=audio_file,
        base_url=base_url,
        audio_subdir="digests/omni_view",
        channel_title="Omni View - Balanced News Perspectives",
        channel_link="https://nerranetwork.com/omni-view.html",
        channel_description=(
            "Daily balanced news summaries presenting multiple perspectives on the "
            "stories that matter. Countering media bias through diverse sources and "
            "critical analysis."
        ),
        channel_author="Omni View",
        channel_email="patrick@planetterrian.com",
        channel_image=f"{base_url}/omni-view-podcast-image.jpg",
        channel_category="News",
        guid_prefix="omni-view",
    )

# MIGRATED: engine/audio.py (format_duration)
# format_duration is now imported from engine.audio at the top

# ========================== MAIN EXECUTION ==========================
if __name__ == "__main__":
    # Load environment variables
    load_dotenv()

    # Optional env overrides (useful for local testing)
    # MIGRATED: engine/utils.py (_env_bool → env_bool)
    TEST_MODE = env_bool("TEST_MODE", TEST_MODE)
    ENABLE_X_POSTING = env_bool("ENABLE_X_POSTING", ENABLE_X_POSTING)
    ENABLE_PODCAST = env_bool("ENABLE_PODCAST", ENABLE_PODCAST)
    ENABLE_GITHUB_SUMMARIES = env_bool("ENABLE_GITHUB_SUMMARIES", ENABLE_GITHUB_SUMMARIES)

    if TEST_MODE:
        # In test mode, default to no posting/no audio unless explicitly overridden above
        ENABLE_X_POSTING = env_bool("ENABLE_X_POSTING", False)
        ENABLE_PODCAST = env_bool("ENABLE_PODCAST", False)

    # Set up paths
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    # New episodes go to dedicated subdirectory; old flat files stay in digests/ for RSS compat
    digests_dir = project_root / "digests" / "omni_view"
    digests_dir.mkdir(parents=True, exist_ok=True)

    # Initialize credit usage tracking — MIGRATED: engine/tracking.py
    episode_num = get_next_episode_number(project_root / "omni_view_podcast.rss", digests_dir)
    credit_usage = create_tracker("Omni View", episode_num)

    # Initialize clients
    client = OpenAI(
        api_key=os.getenv("GROK_API_KEY"),
        base_url="https://api.x.ai/v1",
        timeout=300.0
    )

    # X posting delegated to engine/publisher.post_to_x()
    logging.info("X posting will use engine/publisher.post_to_x()")

    # Initialize variables
    audio_files = []
    voice_mix = None

    logging.info("="*80)
    logging.info("OMNI VIEW — BALANCED NEWS DIGEST")
    logging.info("="*80)

    # ========================== STEP 1: FETCH BALANCED NEWS ==========================
    balanced_news, raw_news_articles = fetch_balanced_news()

    # --- Cross-episode content tracking ---
    _ov_tracker = ContentTracker("omni_view", digests_dir)
    _ov_tracker.load()

    # Entity-level dedup: cap articles to max 2 per primary entity
    balanced_news = deduplicate_by_entity(balanced_news, max_per_entity=2)

    # Cross-episode dedup: drop articles too similar to recently covered stories
    balanced_news = _ov_tracker.filter_recent_articles(balanced_news, similarity_threshold=0.65, days=3)

    logging.info(f"After cross-episode + entity dedup: {len(balanced_news)} articles remain")

    # ========================== STEP 2: GENERATE X THREAD FROM NEWS ==========================
    logging.info("Step 2: Generating balanced news summary thread...")

    # Generate the X thread
    x_thread = generate_balanced_news_digest(balanced_news)

    # Record episode content in the tracker
    _ov_tracker.record_episode(x_thread, OV_SECTION_PATTERNS)
    _ov_tracker.save()

    # ========================== STEP 3: GENERATE PODCAST SCRIPT ==========================
    logging.info("Step 3: Generating podcast script...")

    podcast_script = generate_omni_view_script(x_thread)

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
            _base_url = "https://nerranetwork.com"
            _audio_url = None
            try:
                if ENABLE_PODCAST and final_mp3:
                    _audio_url = f"{_base_url}/digests/omni_view/{final_mp3.name}"
            except Exception:
                _audio_url = None

            summary_json_file = save_summary_to_github_pages(
                x_thread.strip(),
                digests_dir,
                "omni",
                episode_num=episode_num,
                episode_title=f"Omni View — Omni‑View Briefing — {datetime.datetime.now().strftime('%B %d, %Y')}",
                audio_url=_audio_url,
                rss_url=f"{_base_url}/omni_view_podcast.rss",
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
            # Create link to the Omni View summaries page
            summaries_url = "https://nerranetwork.com/omni-view-summaries.html"

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

            # Post the teaser with link via engine
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

    # Save credit usage tracking
    save_credit_usage(credit_usage, digests_dir)

    logging.info("Omni View processing complete!")