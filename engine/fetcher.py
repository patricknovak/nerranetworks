"""RSS feed fetching for the podcast generation pipeline.

Provides:
  - fetch_rss_articles(): fetch, filter, and deduplicate articles from RSS feeds
"""

import datetime
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional

import requests

from engine.utils import (
    DEFAULT_HEADERS,
    HTTP_TIMEOUT_SECONDS,
    remove_similar_items,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Source name mapping
# ---------------------------------------------------------------------------

_SOURCE_MAP: List[tuple] = [
    # Space / Astronomy
    ("nasa.gov", "NASA"),
    ("space.com", "Space.com"),
    ("spaceflightnow", "Spaceflight Now"),
    ("spacenews.com", "SpaceNews"),
    ("astronomy.com", "Astronomy Magazine"),
    ("skyandtelescope", "Sky & Telescope"),
    ("universetoday", "Universe Today"),
    ("esa.int", "European Space Agency"),
    ("roscosmos", "Roscosmos"),
    ("jaxa.jp", "JAXA"),
    ("spacex.com", "SpaceX"),
    ("blueorigin", "Blue Origin"),
    # Science / Medicine
    ("nature.com", "Nature"),
    ("science.org", "Science"),
    ("cell.com", "Cell"),
    ("newscientist", "New Scientist"),
    ("scientificamerican", "Scientific American"),
    ("sciencedaily", "Science Daily"),
    ("sciencenews", "Science News"),
    ("quantamagazine", "Quanta Magazine"),
    ("technologyreview", "MIT Technology Review"),
    ("the-scientist", "The Scientist"),
    # Health / Longevity
    ("longevity", "Longevity Technology"),
    ("lifespan.io", "Lifespan.io"),
    ("healthline", "Healthline"),
    ("medicalnewstoday", "Medical News Today"),
    ("statnews", "STAT News"),
    ("nih.gov", "NIH"),
    ("cdc.gov", "CDC"),
    ("who.int", "WHO"),
    ("fda.gov", "FDA"),
    ("thelancet", "The Lancet"),
    ("jamanetwork", "JAMA"),
    ("nejm", "New England Journal of Medicine"),
    ("bmj.com", "BMJ"),
    ("harvard", "Harvard"),
    ("mayo", "Mayo Clinic"),
    # News / General
    ("reuters.com", "Reuters"),
    ("apnews.com", "AP News"),
    ("bbc.com", "BBC"),
    ("npr.org", "NPR"),
    ("cnbc.com", "CNBC"),
    ("bloomberg.com", "Bloomberg"),
    ("nytimes.com", "New York Times"),
    ("washingtonpost.com", "Washington Post"),
    ("theguardian.com", "The Guardian"),
    ("aljazeera.com", "Al Jazeera"),
    ("foxnews.com", "Fox News"),
    # Tesla-specific
    ("electrek.co", "Electrek"),
    ("teslarati.com", "Teslarati"),
    ("insideevs.com", "InsideEVs"),
    ("tesmanian.com", "Tesmanian"),
    ("notateslaapp.com", "Not a Tesla App"),
    ("torquenews.com", "Torque News"),
    ("cleantechnica.com", "CleanTechnica"),
]


def _get_source_name(feed_url: str, feed_title: str = "Unknown") -> str:
    """Map a feed URL to a human-readable source name."""
    url_lower = feed_url.lower()
    for pattern, name in _SOURCE_MAP:
        if pattern in url_lower:
            return name
    return feed_title if feed_title != "Unknown" else "Unknown"


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def _parse_entry_date(entry) -> Optional[datetime.datetime]:
    """Extract a UTC datetime from a feedparser entry."""
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime.datetime(
                    *parsed[:6], tzinfo=datetime.timezone.utc
                )
            except (ValueError, TypeError):
                pass
    return None


# ---------------------------------------------------------------------------
# Single-feed fetcher
# ---------------------------------------------------------------------------

def _fetch_single_feed(
    feed_url: str,
    cutoff_time: datetime.datetime,
    keywords: Optional[List[str]],
    problematic_feeds: set,
    problematic_feeds_lock: Lock,
    max_articles: int = 0,
) -> Optional[tuple]:
    """Fetch and parse a single RSS feed.

    Returns ``(feed_url, articles, source_name)`` on success, ``None`` on
    error or if the feed produced no usable articles.
    """
    import feedparser

    try:
        response = requests.get(
            feed_url,
            headers=DEFAULT_HEADERS,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        feed = feedparser.parse(response.content)

        if feed.bozo and feed.bozo_exception:
            # Only skip if the feed produced zero entries — many valid feeds
            # trigger bozo on minor XML issues but still have usable entries.
            if not feed.entries:
                with problematic_feeds_lock:
                    if feed_url not in problematic_feeds:
                        problematic_feeds.add(feed_url)
                        logger.warning(
                            "RSS feed parsing failed (no entries): %s — %s",
                            feed_url,
                            str(feed.bozo_exception)[:100],
                        )
                return None
            else:
                logger.debug(
                    "RSS feed has minor XML issues but %d entries parsed OK: %s",
                    len(feed.entries), feed_url,
                )

        feed_title = feed.feed.get("title", "Unknown")
        source_name = _get_source_name(feed_url, feed_title)

        articles: List[Dict] = []
        for entry in feed.entries:
            published_time = _parse_entry_date(entry)

            # Skip articles older than the cutoff
            if published_time and published_time < cutoff_time:
                continue

            title = entry.get("title", "").strip()
            description = (
                entry.get("description", "").strip()
                or entry.get("summary", "").strip()
            )
            link = entry.get("link", "").strip()

            if not title or not link:
                continue

            # Keyword filtering (if keywords provided)
            if keywords:
                text_lower = (title + " " + description).lower()
                if not any(kw in text_lower for kw in keywords):
                    continue

            articles.append(
                {
                    "title": title,
                    "description": description,
                    "url": link,
                    "source_name": source_name,
                    "published_date": (
                        published_time.isoformat()
                        if published_time
                        else datetime.datetime.now(
                            datetime.timezone.utc
                        ).isoformat()
                    ),
                    "relevance_score": 0.0,
                    "author": entry.get("author", ""),
                }
            )

        # Cap per-feed articles to prevent high-volume feeds (e.g. arXiv)
        # from flooding the pipeline with hundreds of entries.
        if max_articles and len(articles) > max_articles:
            logger.info(
                "Capping %s from %d to %d articles",
                source_name, len(articles), max_articles,
            )
            articles = articles[:max_articles]

        return (feed_url, articles, source_name)

    except requests.RequestException:
        with problematic_feeds_lock:
            if feed_url not in problematic_feeds:
                problematic_feeds.add(feed_url)
                logger.debug(
                    "Network error fetching RSS feed (skipping): %s", feed_url
                )
        return None
    except Exception as exc:
        with problematic_feeds_lock:
            if feed_url not in problematic_feeds:
                problematic_feeds.add(feed_url)
                logger.debug(
                    "RSS feed error (skipping): %s — %s", feed_url, exc
                )
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_rss_articles(
    feed_urls: List[Dict[str, str]],
    cutoff_hours: int = 24,
    keywords: Optional[List[str]] = None,
    *,
    max_workers: int = 10,
    similarity_threshold: float = 0.85,
    max_articles_per_feed: int = 50,
) -> List[Dict]:
    """Fetch, filter, and deduplicate articles from RSS feeds.

    Parameters
    ----------
    feed_urls:
        List of ``{"url": "...", "label": "..."}`` dicts.
    cutoff_hours:
        Only include articles published within the last *cutoff_hours*.
    keywords:
        If provided, only include articles whose title+description
        contain at least one keyword (case-insensitive).
    max_workers:
        Maximum number of concurrent feed fetches.
    similarity_threshold:
        Threshold for deduplication (0.0–1.0).  Articles above this
        similarity are considered duplicates.
    max_articles_per_feed:
        Maximum number of articles to keep from any single feed.
        Prevents high-volume feeds (e.g. arXiv) from flooding the
        pipeline.  Set to 0 to disable the cap.

    Returns
    -------
    list[dict]
        Deduplicated articles sorted newest-first.  Each dict has keys:
        ``title``, ``description``, ``url``, ``source_name``,
        ``published_date``, ``relevance_score``, ``author``.
    """
    cutoff_time = datetime.datetime.now(
        datetime.timezone.utc
    ) - datetime.timedelta(hours=cutoff_hours)

    urls = [fd["url"] for fd in feed_urls]
    logger.info("Fetching news from %d RSS feeds...", len(urls))

    all_articles: List[Dict] = []
    problematic_feeds: set = set()
    problematic_feeds_lock = Lock()

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_to_url = {
            pool.submit(
                _fetch_single_feed,
                url,
                cutoff_time,
                keywords,
                problematic_feeds,
                problematic_feeds_lock,
                max_articles_per_feed,
            ): url
            for url in urls
        }
        for future in as_completed(future_to_url):
            result = future.result()
            if result:
                _feed_url, feed_articles, source_name = result
                logger.info(
                    "Fetched %d articles from %s",
                    len(feed_articles),
                    source_name,
                )
                all_articles.extend(feed_articles)

    logger.info("Fetched %d total articles from RSS feeds", len(all_articles))
    if problematic_feeds:
        logger.warning(
            "Skipped %d problematic feed(s): %s",
            len(problematic_feeds),
            ", ".join(sorted(problematic_feeds)),
        )

    if not all_articles:
        logger.warning("No articles found from RSS feeds")
        return []

    # Deduplicate
    before = len(all_articles)
    articles = remove_similar_items(
        all_articles,
        similarity_threshold=similarity_threshold,
        get_text_func=lambda x: f"{x.get('title', '')} {x.get('description', '')}",
    )
    after = len(articles)
    if before != after:
        logger.info(
            "Removed %d similar/duplicate articles", before - after
        )

    # Sort newest first
    articles.sort(key=lambda x: x.get("published_date", ""), reverse=True)

    logger.info("Returning %d unique articles", len(articles))
    return articles
