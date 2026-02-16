"""Shared utility functions for the podcast generation pipeline.

Extracted from the 4 show runner scripts to eliminate duplication.
Canonical versions chosen for robustness:
  - env_float/int/bool: from planetterrian.py (handles None, strips whitespace)
  - number_to_words: identical across all 4 scripts
  - calculate_similarity / remove_similar_items: identical across TST/FF/PT
  - norm_headline_for_similarity / filter_articles_by_recent_stories: from TST
"""

import logging
import os
import re
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Environment variable helpers
# ---------------------------------------------------------------------------

def env_float(name: str, default: float) -> float:
    """Read an env var as a float, returning *default* on missing/invalid."""
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(str(raw).strip())
    except ValueError:
        logger.warning("Invalid %s='%s' (expected float). Using default %s.", name, raw, default)
        return default


def env_int(name: str, default: int) -> int:
    """Read an env var as an int, returning *default* on missing/invalid."""
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        logger.warning("Invalid %s='%s' (expected int). Using default %s.", name, raw, default)
        return default


def env_bool(name: str, default: bool) -> bool:
    """Read an env var as a bool, returning *default* on missing/invalid."""
    raw = os.getenv(name)
    if raw is None:
        return default
    v = str(raw).strip().lower()
    if v in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if v in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default


# ---------------------------------------------------------------------------
# Number-to-words converter (for TTS pronunciation)
# ---------------------------------------------------------------------------

def number_to_words(num: float) -> str:
    """Convert numbers to words for better TTS pronunciation.

    Handles integers up to 999,999 and decimals.  Numbers >= 1,000,000
    are returned as their string representation (TTS usually handles those).
    """
    digit_names = [
        "zero", "one", "two", "three", "four",
        "five", "six", "seven", "eight", "nine",
    ]

    def _convert_under_1000(n: int) -> str:
        ones = [
            "", "one", "two", "three", "four", "five", "six", "seven",
            "eight", "nine", "ten", "eleven", "twelve", "thirteen",
            "fourteen", "fifteen", "sixteen", "seventeen", "eighteen",
            "nineteen",
        ]
        tens = [
            "", "", "twenty", "thirty", "forty", "fifty",
            "sixty", "seventy", "eighty", "ninety",
        ]
        if n == 0:
            return "zero"
        if n < 20:
            return ones[n]
        if n < 100:
            return tens[n // 10] + ("-" + ones[n % 10] if n % 10 else "")
        if n < 1000:
            result = ones[n // 100] + " hundred"
            remainder = n % 100
            if remainder:
                result += " " + _convert_under_1000(remainder)
            return result
        return str(n)

    is_negative = num < 0
    num = abs(num)

    integer_part = int(num)
    decimal_part = num - integer_part

    # Integer portion
    if integer_part == 0:
        result = "zero"
    elif integer_part < 1000:
        result = _convert_under_1000(integer_part)
    elif integer_part < 1_000_000:
        thousands = integer_part // 1000
        remainder = integer_part % 1000
        result = _convert_under_1000(thousands) + " thousand"
        if remainder:
            result += " " + _convert_under_1000(remainder)
    else:
        result = str(integer_part)

    # Decimal portion
    if decimal_part > 0:
        decimal_str = f"{decimal_part:.10f}".rstrip("0").rstrip(".")
        if "." in decimal_str:
            decimal_digits = decimal_str.split(".")[1]
            decimal_words = " ".join(
                digit_names[int(d)] if d.isdigit() and int(d) < 10 else d
                for d in decimal_digits
            )
            result += " point " + decimal_words

    return ("negative " if is_negative else "") + result


# ---------------------------------------------------------------------------
# Text similarity helpers
# ---------------------------------------------------------------------------

def calculate_similarity(text1: str, text2: str) -> float:
    """Calculate similarity ratio between two texts (0.0 to 1.0)."""
    if not text1 or not text2:
        return 0.0
    text1_norm = " ".join(text1.lower().split())
    text2_norm = " ".join(text2.lower().split())
    return SequenceMatcher(None, text1_norm, text2_norm).ratio()


def remove_similar_items(items, similarity_threshold=0.7, get_text_func=None):
    """Remove similar items from a list based on text similarity.

    Args:
        items: List of items to filter.
        similarity_threshold: Ratio above which items are considered duplicates.
        get_text_func: Callable to extract comparison text from an item.
            Defaults to looking for 'title', 'text', or 'description' keys.

    Returns:
        Filtered list with duplicates removed (first occurrence kept).
    """
    if not items:
        return items

    if get_text_func is None:
        def get_text_func(item):
            if isinstance(item, dict):
                return (
                    item.get("title", "")
                    or item.get("text", "")
                    or item.get("content", "")
                    or item.get("description", "")
                )
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
                logger.debug(
                    "Filtered similar item (similarity: %.2f): %s...",
                    similarity,
                    item_text[:50],
                )
                break

        if not is_similar:
            filtered.append(item)

    return filtered


def norm_headline_for_similarity(text: str) -> str:
    """Normalize headline for similarity comparison.

    Strips trailing date patterns, source labels, and extra whitespace so
    that cross-day deduplication compares only the meaningful portion.
    """
    if not text:
        return ""
    # Remove "DD Month, YYYY, HH:MM AM/PM TZ, Source" suffixes
    t = re.sub(
        r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)[a-z]*\s*,?\s*\d{4}[^*]*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Remove "DD/MM/YYYY …" suffixes
    t = re.sub(r"\d{1,2}/\d{1,2}/\d{2,4}[^*]*$", "", t)
    t = " ".join(t.lower().split())
    return t.strip()


def filter_articles_by_recent_stories(
    articles: list,
    recent_headlines: list,
    similarity_threshold: float = 0.72,
) -> list:
    """Drop articles whose title is too similar to a recently covered story.

    Used for cross-day deduplication so the same headline doesn't appear in
    consecutive episodes.
    """
    if not recent_headlines or not articles:
        return articles
    filtered = []
    recent_norm = [norm_headline_for_similarity(h) for h in recent_headlines if h]
    for article in articles:
        title = (article.get("title") or "").strip()
        if not title:
            filtered.append(article)
            continue
        norm_title = norm_headline_for_similarity(title)
        is_covered = False
        for r in recent_norm:
            if not r:
                continue
            if calculate_similarity(norm_title, r) >= similarity_threshold:
                is_covered = True
                logger.debug(
                    "Skipping already-covered story (similar to recent): %s...",
                    title[:60],
                )
                break
        if not is_covered:
            filtered.append(article)
    dropped = len(articles) - len(filtered)
    if dropped:
        logger.info(
            "Filtered %d articles that were too similar to recently covered stories",
            dropped,
        )
    return filtered


# ---------------------------------------------------------------------------
# HTTP constants
# ---------------------------------------------------------------------------

DEFAULT_HEADERS = {
    "User-Agent": "PodcastBot/1.0 (+https://github.com/patricknovak/Tesla-shorts-time)"
}
HTTP_TIMEOUT_SECONDS = 10
