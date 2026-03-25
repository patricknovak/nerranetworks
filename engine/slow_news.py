"""Slow News Day handling: segment library loading, selection, and prompt assembly.

When a show's article count falls below the skip threshold but is not zero,
the pipeline can activate "slow news mode" instead of skipping the episode.
This module provides the logic for:

1. Determining if slow news mode should activate
2. Loading per-show evergreen segment libraries (JSON)
3. Selecting segments with cooldown-aware round-robin rotation
4. Building the prompt context block injected into the digest prompt
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from engine.config import ShowConfig

logger = logging.getLogger(__name__)

# Variation hints cycled round-robin to encourage diverse LLM output
# when a segment is reused after its cooldown period.
_VARIATION_HINTS = [
    "Focus on the most recent 2026 developments and breaking trends.",
    "Compare international approaches and perspectives.",
    "Use a beginner-friendly lens — explain concepts as if to a new investor or listener.",
    "Highlight contrarian or underappreciated viewpoints.",
    "Use concrete case studies and real-world examples.",
    "Frame this through the lens of long-term historical patterns.",
]

_REQUIRED_SEGMENT_KEYS = {"id", "type", "title", "prompt_template", "estimated_words"}


def is_slow_news_day(article_count: int, config: ShowConfig) -> bool:
    """Determine if this is a slow news day that should use evergreen segments.

    Returns ``True`` when:
    - ``config.slow_news.enabled`` is ``True``
    - ``article_count`` is below ``config.min_articles_skip``
    - ``article_count`` > 0 (zero articles still skips entirely)
    """
    if not config.slow_news.enabled:
        return False
    if article_count <= 0:
        return False
    skip_threshold = getattr(config, "min_articles_skip", 3) or 3
    return article_count < skip_threshold


def load_segment_library(library_file: str) -> List[Dict]:
    """Load and validate a per-show segment library JSON file.

    Parameters
    ----------
    library_file:
        Path to the JSON file, relative to the project root or absolute.

    Returns
    -------
    list[dict]
        List of validated segment dicts.

    Raises
    ------
    FileNotFoundError
        If the library file does not exist.
    ValueError
        If the file is malformed or segments are missing required keys.
    """
    path = Path(library_file)
    if not path.is_absolute():
        # Try relative to cwd (project root)
        path = Path.cwd() / path
    if not path.exists():
        raise FileNotFoundError(f"Segment library not found: {library_file}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict) or "segments" not in data:
        raise ValueError(f"Segment library must be a JSON object with a 'segments' key: {library_file}")

    segments = data["segments"]
    if not isinstance(segments, list) or len(segments) == 0:
        raise ValueError(f"Segment library 'segments' must be a non-empty list: {library_file}")

    for i, seg in enumerate(segments):
        missing = _REQUIRED_SEGMENT_KEYS - set(seg.keys())
        if missing:
            raise ValueError(
                f"Segment {i} in {library_file} missing required keys: {missing}"
            )

    logger.info("Loaded %d segments from %s", len(segments), library_file)
    return segments


def select_segments(
    library: List[Dict],
    recently_used_ids: List[str],
    *,
    max_segments: int = 2,
    mode: str = "round_robin",
) -> List[Dict]:
    """Pick segments from the library, avoiding recently used ones.

    Parameters
    ----------
    library:
        Full list of segment dicts from ``load_segment_library()``.
    recently_used_ids:
        Segment IDs used within the cooldown window (from ContentTracker).
    max_segments:
        Maximum number of segments to return.
    mode:
        Selection strategy — ``"round_robin"`` (default) or ``"random"``.

    Returns
    -------
    list[dict]
        Selected segments (up to ``max_segments``).
    """
    if not library:
        return []

    used_set = set(recently_used_ids)

    # Filter to segments not on cooldown
    available = [s for s in library if s["id"] not in used_set]

    if not available:
        # All on cooldown — fall back to least-recently-used.
        # recently_used_ids is ordered oldest-first from ContentTracker,
        # so segments whose IDs appear earliest are the least-recently-used.
        id_order = {sid: idx for idx, sid in enumerate(recently_used_ids)}
        available = sorted(
            library,
            key=lambda s: id_order.get(s["id"], -1),
        )
        logger.info(
            "All %d segments on cooldown — falling back to least-recently-used",
            len(library),
        )

    if mode == "random":
        import random
        random.shuffle(available)

    selected = available[:max_segments]
    logger.info(
        "Selected %d segment(s): %s",
        len(selected),
        [s["id"] for s in selected],
    )
    return selected


def build_slow_news_prompt_context(
    articles: List[Dict],
    selected_segments: List[Dict],
    config: ShowConfig,
    template_vars: Dict,
    previous_angles: Optional[Dict[str, List[str]]] = None,
) -> str:
    """Build the ``{slow_news_context}`` prompt block for slow news days.

    Parameters
    ----------
    articles:
        The (few) articles available on this slow news day.
    selected_segments:
        Segments chosen by ``select_segments()``.
    config:
        Show configuration.
    template_vars:
        Existing template variables (date, show name, etc.).
    previous_angles:
        Map of segment_id -> list of past angle summaries from ContentTracker.
        Used for freshness enforcement.

    Returns
    -------
    str
        A structured prompt block ready for injection into the digest prompt.
    """
    if not selected_segments:
        return ""

    previous_angles = previous_angles or {}
    parts: list[str] = []

    parts.append("=" * 60)
    parts.append("SLOW NEWS DAY MODE — SPECIAL EPISODE FORMAT")
    parts.append("=" * 60)
    parts.append("")
    parts.append(
        "Today has fewer news stories than usual. You MUST produce a full-length, "
        "high-quality episode using the format below. Do NOT shorten the episode "
        "or apologize for the lighter news day."
    )
    parts.append("")

    # --- News Pulse section ---
    parts.append("--- SECTION 1: NEWS PULSE ---")
    parts.append(
        "Summarize the available news stories in a concise 'News Pulse' segment. "
        "Cover each story briefly but substantively. Frame it as: "
        "'Today's news flow is lighter than usual, so we're using this as an "
        "opportunity to go deeper on some evergreen topics after the headlines.'"
    )
    parts.append("")
    if articles:
        parts.append(f"Available articles ({len(articles)}):")
        for i, art in enumerate(articles, 1):
            title = art.get("title", "Untitled")
            source = art.get("source", "")
            summary = art.get("summary", art.get("description", ""))[:200]
            parts.append(f"  {i}. [{source}] {title}")
            if summary:
                parts.append(f"     {summary}")
        parts.append("")

    # --- Evergreen segments ---
    for seg_idx, seg in enumerate(selected_segments, 1):
        parts.append(f"--- SECTION {seg_idx + 1}: EVERGREEN SEGMENT — {seg['title'].upper()} ---")
        parts.append(f"Segment type: {seg.get('type', 'deep_dive')}")
        parts.append(f"Target length: approximately {seg.get('estimated_words', 600)} words")
        parts.append("")

        # Fill prompt template with available vars
        prompt_template = seg["prompt_template"]
        try:
            prompt_text = prompt_template.format(**template_vars)
        except (KeyError, IndexError):
            prompt_text = prompt_template
        parts.append(f"Instructions: {prompt_text}")
        parts.append("")

        # Freshness enforcement — previous angles
        seg_id = seg["id"]
        past_angles = previous_angles.get(seg_id, [])
        if past_angles:
            parts.append("PREVIOUS ANGLES (you MUST take a DIFFERENT angle, use different examples,")
            parts.append("and cover different sub-topics than these previous episodes):")
            for angle in past_angles:
                parts.append(f"  - {angle}")
            parts.append("")

        # Variation hint — cycle through hints based on segment index + date
        date_str = template_vars.get("date", "")
        # Use date hash + segment index to pick a hint deterministically
        hint_seed = (hash(date_str) + seg_idx) % len(_VARIATION_HINTS)
        hint = _VARIATION_HINTS[hint_seed]
        parts.append(f"VARIATION DIRECTION: {hint}")
        parts.append("")

    parts.append("=" * 60)
    parts.append(
        "IMPORTANT: The episode MUST include ALL sections above. "
        "Maintain the show's normal tone, style, and quality standards throughout."
    )
    parts.append("=" * 60)

    return "\n".join(parts)
