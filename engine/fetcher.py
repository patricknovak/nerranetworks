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
    # Finance / Investing
    ("financialpost.com", "Financial Post"),
    ("bnnbloomberg.ca", "BNN Bloomberg"),
    ("theglobeandmail.com", "Globe and Mail"),
    ("moneysense.ca", "MoneySense"),
    ("wealthsimple.com", "Wealthsimple"),
    ("youngandthrifty.ca", "Young and Thrifty"),
    ("finance.yahoo.com", "Yahoo Finance"),
    ("investopedia.com", "Investopedia"),
    ("fool.com", "Motley Fool"),
    ("marketwatch.com", "MarketWatch"),
    ("bankofcanada.ca", "Bank of Canada"),
    ("benzinga.com", "Benzinga"),
    ("finextra.com", "Finextra"),
    ("etfdb.com", "ETF Database"),
    ("etf.com", "ETF.com"),
    ("cointelegraph.com", "CoinTelegraph"),
    ("seekingalpha.com", "Seeking Alpha"),
    ("morningstar.com", "Morningstar"),
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

    except requests.RequestException as exc:
        with problematic_feeds_lock:
            if feed_url not in problematic_feeds:
                problematic_feeds.add(feed_url)
                logger.warning(
                    "Network error fetching RSS feed: %s — %s", feed_url, exc
                )
        return None
    except Exception as exc:
        with problematic_feeds_lock:
            if feed_url not in problematic_feeds:
                problematic_feeds.add(feed_url)
                logger.warning(
                    "RSS feed error: %s — %s", feed_url, exc
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


# ---------------------------------------------------------------------------
# X / Twitter account fetcher (via xAI Grok x_search)
# ---------------------------------------------------------------------------

def fetch_x_posts(
    x_accounts: list,
    keywords: Optional[List[str]] = None,
) -> List[Dict]:
    """Fetch recent posts from X accounts using xAI's Grok API.

    Uses xAI's x_search tool to find recent posts from specified accounts.
    Returns articles in the same format as ``fetch_rss_articles()`` so they
    can be merged seamlessly into the pipeline.

    Parameters
    ----------
    x_accounts:
        List of ``XAccountConfig`` objects (handle, label, max_posts).
    keywords:
        Optional keyword filter — if provided, only posts whose text
        contains at least one keyword are kept.

    Returns
    -------
    list[dict]
        Articles with keys: ``title``, ``description``, ``url``,
        ``source_name``, ``published_date``, ``relevance_score``, ``author``.
    """
    import datetime as _dt
    import os
    import re

    if not x_accounts:
        return []

    api_key = (os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY") or "").strip()
    if not api_key:
        logger.warning("No GROK_API_KEY — skipping X account fetch")
        return []

    all_posts: List[Dict] = []

    for account in x_accounts:
        handle = account.handle.lstrip("@")
        label = account.label or f"@{handle}"
        max_posts = getattr(account, "max_posts", 5) or 5

        # Build a search query for the account's recent posts
        query = f"from:@{handle} recent posts last 24 hours"
        if keywords:
            # Add top keywords to help focus the search
            top_kw = keywords[:5]
            query += f" about {', '.join(top_kw)}"

        logger.info("Fetching X posts from @%s via Grok x_search ...", handle)

        try:
            from digests.xai_grok import grok_generate_text

            extraction_prompt = (
                f"Search X/Twitter for the most recent posts from @{handle} "
                f"in the last 24 hours.\n\n"
                f"Return ONLY a structured list of their posts, formatted exactly like this "
                f"(one block per post, separated by blank lines):\n\n"
                f"POST_TITLE: [A short headline summarizing the post content, max 100 chars]\n"
                f"POST_TEXT: [The full text of the post]\n"
                f"POST_URL: [The URL to the post, e.g. https://x.com/{handle}/status/...]\n\n"
                f"Rules:\n"
                f"- Include up to {max_posts} posts maximum\n"
                f"- Only include posts from the last 24 hours\n"
                f"- Skip retweets of other people's content — only include original posts and quote tweets\n"
                f"- If @{handle} has no recent posts, return exactly: NO_RECENT_POSTS\n"
                f"- Do NOT add any commentary, analysis, or extra text — just the structured list\n"
            )

            text, meta = grok_generate_text(
                prompt=extraction_prompt,
                enable_x_search=True,
                max_turns=3,
            )

            if not text or "NO_RECENT_POSTS" in text:
                logger.info("No recent posts found from @%s", handle)
                continue

            # Parse the structured response into article dicts
            now_iso = _dt.datetime.now(_dt.timezone.utc).isoformat()
            posts = _parse_x_posts(text, handle, label, now_iso)

            if keywords:
                before_filter = len(posts)
                kw_lower = [k.lower() for k in keywords]
                posts = [
                    p for p in posts
                    if any(
                        kw in (p.get("title", "") + " " + p.get("description", "")).lower()
                        for kw in kw_lower
                    )
                ]
                if before_filter != len(posts):
                    logger.info(
                        "Keyword filter: %d → %d posts from @%s",
                        before_filter, len(posts), handle,
                    )

            # Cap to max_posts
            posts = posts[:max_posts]
            logger.info("Fetched %d posts from @%s", len(posts), handle)
            all_posts.extend(posts)

        except Exception as exc:
            logger.warning("Failed to fetch X posts from @%s: %s", handle, exc)
            continue

    logger.info("Total X posts fetched: %d from %d account(s)", len(all_posts), len(x_accounts))
    return all_posts


def _parse_x_posts(
    text: str,
    handle: str,
    label: str,
    now_iso: str,
) -> List[Dict]:
    """Parse structured POST_TITLE/POST_TEXT/POST_URL blocks from Grok output."""
    import re

    posts: List[Dict] = []
    # Split on POST_TITLE to find individual post blocks
    blocks = re.split(r"(?=POST_TITLE\s*:)", text.strip())

    for block in blocks:
        block = block.strip()
        if not block.startswith("POST_TITLE"):
            continue

        title_m = re.search(r"POST_TITLE\s*:\s*(.+?)(?:\n|$)", block)
        text_m = re.search(r"POST_TEXT\s*:\s*(.+?)(?=POST_URL|\Z)", block, re.DOTALL)
        url_m = re.search(r"POST_URL\s*:\s*(https?://\S+)", block)

        title = title_m.group(1).strip() if title_m else ""
        desc = text_m.group(1).strip() if text_m else ""
        url = url_m.group(1).strip() if url_m else f"https://x.com/{handle}"

        if not title and not desc:
            continue

        posts.append({
            "title": title or desc[:100],
            "description": desc,
            "url": url,
            "source_name": f"{label} (X)",
            "published_date": now_iso,
            "relevance_score": 0.0,
            "author": f"@{handle}",
        })

    return posts
