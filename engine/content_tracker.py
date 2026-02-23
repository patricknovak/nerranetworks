"""Cross-episode content tracking for all podcast shows.

Prevents story repetition, quote reuse, and topic clustering across episodes
by maintaining a per-show JSON tracker file.

Each show provides its own section_patterns dict so the tracker can extract
and record section content from generated digests.

Usage:
    from engine.content_tracker import ContentTracker

    tracker = ContentTracker("fascinating_frontiers", output_dir)
    tracker.load()

    # Before generation: get prompt context about recently used content
    summary = tracker.get_summary_for_prompt()

    # Before generation: filter articles already covered recently
    articles = tracker.filter_recent_articles(articles)

    # After generation: extract and record sections from the new digest
    tracker.record_episode(digest_text, section_patterns)
    tracker.save()
"""

import datetime
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from engine.utils import calculate_similarity, norm_headline_for_similarity

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default section patterns per show
# ---------------------------------------------------------------------------

TST_SECTION_PATTERNS: Dict[str, str] = {
    "headlines": (
        r"(?:📰 \*\*Top (?:10 )?News(?: Items)?\*\*|### Top (?:10 )?News(?: Items)?)"
        r"(.*?)"
        r"(?=━━|## Short Spot|📉|### Tesla First Principles|## Tesla X Takeover|🎙️ \*\*Tesla X Takeover)"
    ),
    "takeover_headlines": (
        r"(?:## Tesla X Takeover|🎙️ \*\*Tesla X Takeover[^\n]*)"
        r"(.*?)"
        r"(?=━━|## Short Spot|📉|### Tesla First Principles|$)"
    ),
    "short_spot": (
        r"(?:## Short Spot|📉 \*\*Short Spot\*\*)"
        r"(.*?)"
        r"(?=━━|### Short Squeeze|📈|### Daily Challenge|💪|✨|### Tesla First Principles|🧠|$)"
    ),
    "first_principles": (
        r"(?:### Tesla First Principles|🧠 Tesla First Principles)"
        r"(.*?)"
        r"(?=━━|### Daily Challenge|💪|## Tesla Market Movers|$)"
    ),
    "daily_challenge": (
        r"(?:### Daily Challenge|💪 \*\*Daily Challenge\*\*)"
        r"(.*?)"
        r"(?=━━|✨|\*\*Inspiration Quote\*\*|$)"
    ),
    "inspiration_quote": (
        r"(?:✨ \*\*Inspiration Quote:\*\*|\*\*Inspiration Quote:\*\*|Inspiration Quote:)"
        r"\s*\"([^\"]+)\"\s*[–-]\s*([^,\n]+)"
    ),
}

FF_SECTION_PATTERNS: Dict[str, str] = {
    "headlines": (
        r"(?:### Top 15 Space|### Top \d+ Space)"
        r"(.*?)"
        r"(?=━━|### Cosmic Spotlight|$)"
    ),
    "cosmic_spotlight": (
        r"(?:### Cosmic Spotlight)"
        r"(.*?)"
        r"(?=━━|### Daily Inspiration|$)"
    ),
    "daily_inspiration": (
        r"(?:### Daily Inspiration)"
        r"(.*?)"
        r"(?=━━|$)"
    ),
}

PT_SECTION_PATTERNS: Dict[str, str] = {
    "headlines": (
        r"(?:### Top 15 Science|### Top \d+ Science)"
        r"(.*?)"
        r"(?=━━|### Planetterrian Spotlight|$)"
    ),
    "planetterrian_spotlight": (
        r"(?:### Planetterrian Spotlight)"
        r"(.*?)"
        r"(?=━━|### Daily Inspiration|$)"
    ),
    "daily_inspiration": (
        r"(?:### Daily Inspiration)"
        r"(.*?)"
        r"(?=━━|$)"
    ),
}

OV_SECTION_PATTERNS: Dict[str, str] = {
    "headlines": (
        r"(?:### Top \d+|### Today's Top)"
        r"(.*?)"
        r"(?=━━|### (?:Deep Dive|Closing)|$)"
    ),
}

EI_SECTION_PATTERNS: Dict[str, str] = {
    "headlines": (
        r"(?:### Lead Story|## Lead Story)"
        r"(.*?)"
        r"(?=━━|### Regulatory|## Regulatory|$)"
    ),
    "regulatory_watch": (
        r"(?:### Regulatory & Policy Watch|## Regulatory & Policy Watch)"
        r"(.*?)"
        r"(?=━━|### Science|## Science|$)"
    ),
    "science_technical": (
        r"(?:### Science & Technical|## Science & Technical)"
        r"(.*?)"
        r"(?=━━|### Industry|## Industry|$)"
    ),
    "industry_practice": (
        r"(?:### Industry & Practice|## Industry & Practice)"
        r"(.*?)"
        r"(?=━━|### Action Items|## Action Items|$)"
    ),
}

# Registry mapping show slugs to their section patterns.
# New shows should be added here to enable cross-episode content tracking.
SHOW_SECTION_PATTERNS: Dict[str, Dict[str, str]] = {
    "tesla": TST_SECTION_PATTERNS,
    "tesla_shorts_time": TST_SECTION_PATTERNS,
    "fascinating_frontiers": FF_SECTION_PATTERNS,
    "planetterrian": PT_SECTION_PATTERNS,
    "omni_view": OV_SECTION_PATTERNS,
    "env_intel": EI_SECTION_PATTERNS,
}


def _extract_bold_headlines(text: str, max_items: int = 20) -> List[str]:
    """Extract bold-formatted headlines from a digest section."""
    headlines = []
    for m in re.finditer(r"\*{2}([^*]{10,})\*{2}", text):
        t = m.group(1).strip()
        # Skip short items that are likely formatting, not headlines
        if t and len(t) > 15 and t not in headlines:
            headlines.append(t)
        if len(headlines) >= max_items:
            break
    return headlines


def _extract_quote_author(text: str) -> Optional[str]:
    """Extract the author from a quote section."""
    # Match: "quote text" – Author Name  or  quote text – Author Name
    m = re.search(r'["""]?[^"""\n]+["""]?\s*[–—-]\s*([A-Z][^\n,]{2,40})', text)
    if m:
        return m.group(1).strip()
    return None


class ContentTracker:
    """Per-show cross-episode content tracker.

    Maintains a JSON file tracking:
    - headlines: news story headlines from recent episodes
    - section content: spotlight topics, short spots, quotes, challenges
    - quote authors: to enforce author diversity
    """

    def __init__(
        self,
        show_slug: str,
        output_dir: Path,
        max_days: int = 14,
    ):
        self.show_slug = show_slug
        self.output_dir = Path(output_dir)
        self.max_days = max_days
        self.tracker_file = self.output_dir / f"{show_slug}_content_tracker.json"
        self.data: Dict = {
            "show": show_slug,
            "last_updated": None,
            "episodes": [],
        }

    def load(self) -> None:
        """Load tracker from JSON file."""
        if self.tracker_file.exists():
            try:
                with open(self.tracker_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict) and "episodes" in loaded:
                    self.data = loaded
                    self._prune_old_episodes()
                    logger.info(
                        "Loaded content tracker for '%s': %d episodes tracked",
                        self.show_slug,
                        len(self.data["episodes"]),
                    )
                    return
            except Exception as e:
                logger.warning("Failed to load content tracker for %s: %s", self.show_slug, e)
        logger.info("Starting fresh content tracker for '%s'", self.show_slug)

    def save(self) -> None:
        """Persist tracker to JSON file."""
        self._prune_old_episodes()
        self.data["last_updated"] = datetime.date.today().isoformat()
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            with open(self.tracker_file, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
            logger.info("Saved content tracker to %s", self.tracker_file)
        except Exception as e:
            logger.error("Failed to save content tracker: %s", e)

    def _prune_old_episodes(self) -> None:
        """Remove episodes older than max_days."""
        cutoff = (datetime.date.today() - datetime.timedelta(days=self.max_days)).isoformat()
        self.data["episodes"] = [
            ep for ep in self.data["episodes"]
            if ep.get("date", "") >= cutoff
        ]

    # ----- Querying recent content -----

    def get_recent_headlines(self, days: Optional[int] = None) -> List[str]:
        """Return headlines from recent episodes for cross-day dedup."""
        cutoff = (
            datetime.date.today() - datetime.timedelta(days=days or self.max_days)
        ).isoformat()
        headlines = []
        for ep in self.data["episodes"]:
            if ep.get("date", "") >= cutoff:
                headlines.extend(ep.get("headlines", []))
        return headlines

    def get_recent_quote_authors(self, window_days: int = 30) -> List[str]:
        """Return quote authors used within the window."""
        cutoff = (datetime.date.today() - datetime.timedelta(days=window_days)).isoformat()
        authors = []
        for ep in self.data["episodes"]:
            if ep.get("date", "") >= cutoff:
                author = ep.get("quote_author")
                if author:
                    authors.append(author)
        return authors

    def get_recent_section_content(self, section_key: str, max_items: int = 7) -> List[str]:
        """Return recent content for a named section (e.g., 'cosmic_spotlight')."""
        items = []
        for ep in reversed(self.data["episodes"]):
            content = ep.get("sections", {}).get(section_key)
            if content:
                items.append(content[:500])
            if len(items) >= max_items:
                break
        return items

    def get_summary_for_prompt(self, limits: Optional[Dict[str, int]] = None) -> str:
        """Generate a 'RECENTLY USED...' block for inclusion in the Grok prompt.

        This tells Grok what was used recently so it can avoid repetition.
        """
        if not limits:
            limits = {}

        parts = []

        # Recent headlines
        recent_headlines = self.get_recent_headlines(days=3)
        if recent_headlines:
            hl_limit = limits.get("headlines", 40)
            hl_text = "\n".join(f"- {h[:120]}" for h in recent_headlines[-hl_limit:])
            parts.append(
                f"RECENTLY COVERED NEWS STORIES (DO NOT repeat these — pick DIFFERENT stories):\n{hl_text}"
            )

        # Recent quote authors
        recent_authors = self.get_recent_quote_authors(window_days=30)
        if recent_authors:
            auth_text = ", ".join(set(recent_authors))
            parts.append(
                f"RECENTLY USED QUOTE AUTHORS (use a DIFFERENT author): {auth_text}"
            )

        # Section-specific content
        section_labels = {
            "short_spot": "SHORT SPOTS",
            "first_principles": "FIRST PRINCIPLES TOPICS",
            "daily_challenge": "DAILY CHALLENGES",
            "cosmic_spotlight": "COSMIC SPOTLIGHT TOPICS",
            "planetterrian_spotlight": "PLANETTERRIAN SPOTLIGHT TOPICS",
            "regulatory_watch": "REGULATORY & POLICY WATCH TOPICS",
            "science_technical": "SCIENCE & TECHNICAL TOPICS",
            "industry_practice": "INDUSTRY & PRACTICE TOPICS",
        }
        for key, label in section_labels.items():
            items = self.get_recent_section_content(key, max_items=limits.get(key, 7))
            if items:
                items_text = "\n".join(f"- {item[:200]}..." for item in items)
                parts.append(
                    f"RECENTLY USED {label} (DO NOT REPEAT — create something COMPLETELY DIFFERENT):\n{items_text}"
                )

        if parts:
            return (
                "\n\n".join(parts)
                + "\n\nCRITICAL: Generate COMPLETELY NEW, FRESH content for ALL sections. "
                "Avoid ANY similarity to the above.\n"
            )
        return ""

    def filter_recent_articles(
        self,
        articles: List[Dict],
        similarity_threshold: float = 0.65,
        days: Optional[int] = None,
    ) -> List[Dict]:
        """Filter out articles that are too similar to recently covered stories.

        More aggressive than the in-episode dedup (0.85 threshold) because
        cross-episode repetition is more noticeable to listeners.
        """
        recent_headlines = self.get_recent_headlines(days=days or 3)
        if not recent_headlines or not articles:
            return articles

        recent_norm = [norm_headline_for_similarity(h) for h in recent_headlines if h]
        filtered = []
        for article in articles:
            title = (article.get("title") or "").strip()
            if not title:
                filtered.append(article)
                continue
            norm_title = norm_headline_for_similarity(title)
            is_repeat = False
            for r in recent_norm:
                if not r:
                    continue
                if calculate_similarity(norm_title, r) >= similarity_threshold:
                    is_repeat = True
                    logger.debug(
                        "Filtering recently-covered article: %s...", title[:60]
                    )
                    break
            if not is_repeat:
                filtered.append(article)

        dropped = len(articles) - len(filtered)
        if dropped:
            logger.info(
                "Filtered %d articles similar to recently covered stories", dropped
            )
        return filtered

    # ----- Recording new episodes -----

    def record_episode(
        self,
        digest_text: str,
        section_patterns: Dict[str, str],
        date: Optional[str] = None,
    ) -> None:
        """Extract and record content from a generated digest.

        Args:
            digest_text: The full digest markdown text.
            section_patterns: Dict mapping section names to regex patterns.
            date: Episode date (ISO format). Defaults to today.
        """
        ep_date = date or datetime.date.today().isoformat()

        # Don't record duplicate dates
        existing_dates = {ep.get("date") for ep in self.data["episodes"]}
        if ep_date in existing_dates:
            logger.debug("Episode for %s already recorded, updating", ep_date)
            self.data["episodes"] = [
                ep for ep in self.data["episodes"] if ep.get("date") != ep_date
            ]

        episode_record = {
            "date": ep_date,
            "headlines": [],
            "quote_author": None,
            "sections": {},
        }

        # Extract headlines
        headlines_pattern = section_patterns.get("headlines")
        if headlines_pattern:
            m = re.search(headlines_pattern, digest_text, re.DOTALL | re.IGNORECASE)
            if m:
                episode_record["headlines"] = _extract_bold_headlines(m.group(1))

        # Also extract takeover headlines (TST-specific)
        takeover_pattern = section_patterns.get("takeover_headlines")
        if takeover_pattern:
            m = re.search(takeover_pattern, digest_text, re.DOTALL | re.IGNORECASE)
            if m:
                episode_record["headlines"].extend(_extract_bold_headlines(m.group(1)))

        # Extract named sections
        for key, pattern in section_patterns.items():
            if key in ("headlines", "takeover_headlines"):
                continue

            m = re.search(pattern, digest_text, re.DOTALL | re.IGNORECASE)
            if m:
                content = m.group(0).strip()[:500]
                episode_record["sections"][key] = content

                # Special handling for quote/inspiration sections
                if "quote" in key or "inspiration" in key:
                    author = _extract_quote_author(m.group(0))
                    if author:
                        episode_record["quote_author"] = author

        self.data["episodes"].append(episode_record)
        logger.info(
            "Recorded episode %s: %d headlines, %d sections, quote by %s",
            ep_date,
            len(episode_record["headlines"]),
            len(episode_record["sections"]),
            episode_record["quote_author"] or "unknown",
        )

    def check_quote_reuse(self, quote_text: str, window_days: int = 30) -> bool:
        """Check if a quote's author has been used within the window.

        Returns True if the author has been used recently (i.e., it's a repeat).
        """
        author = _extract_quote_author(quote_text)
        if not author:
            return False

        recent_authors = self.get_recent_quote_authors(window_days)
        for recent_author in recent_authors:
            if calculate_similarity(author.lower(), recent_author.lower()) >= 0.8:
                logger.debug("Quote author '%s' reused (similar to '%s')", author, recent_author)
                return True
        return False
