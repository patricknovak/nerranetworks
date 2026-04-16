"""Content Synthesizer — Produces derivative content products from the Content Lake.

Weekly newsletters, monthly reports, cross-show briefings, and topic guides.
All synthesis uses the existing ``_call_grok()`` LLM interface from
``engine.generator``.
"""

from __future__ import annotations

import calendar
import logging
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from engine.content_lake import query_all_shows_range, query_show_range
from engine.generator import _call_grok

logger = logging.getLogger(__name__)


def _load_config_safe(show_slug: str, config_path: Optional[Path] = None):
    """Load a show config, returning None on failure."""
    from engine.config import load_config

    try:
        path = str(config_path) if config_path else f"shows/{show_slug}.yaml"
        return load_config(path)
    except Exception as e:
        logger.warning("Failed to load config for %s: %s", show_slug, e)
        return None


# ---------------------------------------------------------------------------
# Weekly newsletter
# ---------------------------------------------------------------------------

_DEFAULT_WEEKLY_PROMPT = """\
You are the weekly newsletter editor for {show_name}, part of the Nerra Network.

Synthesize this week's {episode_count} episodes (from {start_date} to \
{end_date}) into a compelling weekly newsletter.

## This Week's Episodes:

{episodes_text}

## Key Entities This Week:
{entities}

## Instructions:

Write a weekly newsletter in markdown format with these sections:

1. **This Week's Big Picture** — 2-3 paragraphs summarizing the most \
important themes and developments from the week. Connect the dots between \
stories. What's the narrative arc?

2. **Top Stories** — The 5 most important stories from the week, each with \
a 2-3 sentence summary and why it matters.

3. **Trend Watch** — 2-3 emerging trends you noticed across this week's \
coverage. What patterns are forming?

4. **Quick Hits** — 5-8 smaller stories worth knowing about, each in one \
sentence.

5. **What to Watch Next Week** — 2-3 things to keep an eye on based on \
this week's developments.

Write in an engaging, informed tone. This is for subscribers who want the \
week's highlights without listening to every episode. Keep the total length \
under 1500 words.

End with a brief sign-off that encourages the reader to share the newsletter \
with someone who would enjoy it, and remind them they can listen to full \
episodes at nerranetwork.com. Keep it natural and brief — one sentence, \
not a hard sell."""


def synthesize_weekly_newsletter(
    show_slug: str,
    week_ending: date,
    *,
    config_path: Optional[Path] = None,
    prompt_file: Optional[Path] = None,
) -> Optional[str]:
    """Generate a weekly newsletter for a show from the past 7 days.

    Returns markdown-formatted newsletter text, or ``None`` if insufficient
    data.
    """
    start_date = (week_ending - timedelta(days=6)).isoformat()
    end_date = week_ending.isoformat()

    episodes = query_show_range(show_slug, start_date, end_date)
    if len(episodes) < 2:
        logger.warning(
            "[Synthesizer] Only %d episodes for %s week of %s, skipping",
            len(episodes), show_slug, end_date,
        )
        return None

    cfg = _load_config_safe(show_slug, config_path)
    if not cfg:
        return None

    # Build context from episodes
    episode_summaries = []
    all_entities: set[str] = set()

    for ep in episodes:
        episode_summaries.append(
            f"### Episode {ep['episode_num']} — {ep['date']}\n"
            f"**Hook:** {ep.get('hook', 'N/A')}\n\n"
            f"{ep.get('digest_md', '')[:2000]}"
        )
        all_entities.update(ep.get("entities", []))

    episodes_text = "\n\n---\n\n".join(episode_summaries)

    # Cross-show highlights: top stories from OTHER shows this week that
    # subscribers of THIS show might find interesting. This is a key
    # cross-promotion mechanism for the network.
    cross_show_section = ""
    try:
        all_shows_eps = query_all_shows_range(start_date, end_date)
        other_shows = [
            ep for ep in all_shows_eps
            if ep.get("show_slug") != show_slug and ep.get("hook")
        ]
        if other_shows:
            highlights = other_shows[:5]
            cross_lines = []
            for ep in highlights:
                show_label = ep.get("show_name") or ep.get("show_slug", "")
                hook = (ep.get("hook") or "")[:120]
                cross_lines.append(f"- **{show_label}**: {hook}")
            cross_show_section = (
                "\n\n## From the Nerra Network This Week\n"
                "Other shows in the network covered these notable stories:\n"
                + "\n".join(cross_lines)
            )
    except Exception as exc:
        logger.debug("Cross-show highlights failed: %s", exc)

    # Load show-specific or default prompt
    if prompt_file and prompt_file.exists():
        prompt_template = prompt_file.read_text(encoding="utf-8")
    else:
        prompt_template = _DEFAULT_WEEKLY_PROMPT

    show_name = getattr(cfg.publishing, "rss_title", show_slug)
    prompt = prompt_template.format(
        show_name=show_name,
        episode_count=len(episodes),
        start_date=start_date,
        end_date=end_date,
        episodes_text=episodes_text + cross_show_section,
        entities=", ".join(sorted(all_entities)[:30]),
    )

    system_prompt = (
        f"You are the weekly newsletter editor for {show_name}, "
        f"part of the Nerra Network podcast network."
    )

    try:
        text, meta = _call_grok(
            prompt=prompt,
            model=cfg.llm.model,
            temperature=0.5,
            max_tokens=cfg.llm.max_tokens,
            system_prompt=system_prompt,
        )
        logger.info(
            "[Synthesizer] Weekly newsletter for %s: %d chars",
            show_slug, len(text),
        )
        return text
    except Exception as e:
        logger.error(
            "[Synthesizer] Weekly newsletter failed for %s: %s",
            show_slug, e,
        )
        return None


# ---------------------------------------------------------------------------
# Monthly report
# ---------------------------------------------------------------------------

def synthesize_monthly_report(
    show_slug: str,
    month: int,
    year: int,
    *,
    config_path: Optional[Path] = None,
) -> Optional[str]:
    """Generate a monthly "State of..." report for a show.

    Returns markdown text, or ``None`` if insufficient data.
    """
    last_day = calendar.monthrange(year, month)[1]
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month:02d}-{last_day:02d}"

    episodes = query_show_range(show_slug, start_date, end_date)
    if len(episodes) < 5:
        logger.warning(
            "[Synthesizer] Only %d episodes for %s in %d-%02d, skipping",
            len(episodes), show_slug, year, month,
        )
        return None

    cfg = _load_config_safe(show_slug, config_path)
    if not cfg:
        return None

    # Aggregate content
    all_entities: list[str] = []
    all_topics: list[str] = []
    all_hooks: list[str] = []
    episode_digests: list[str] = []

    for ep in episodes:
        all_entities.extend(ep.get("entities", []))
        all_topics.extend(ep.get("topics", []))
        all_hooks.append(
            f"Ep{ep['episode_num']} ({ep['date']}): {ep.get('hook', 'N/A')}"
        )
        episode_digests.append(
            f"**Ep{ep['episode_num']} ({ep['date']}):** "
            f"{ep.get('digest_md', '')[:800]}"
        )

    entity_counts = Counter(all_entities).most_common(20)
    topic_counts = Counter(all_topics).most_common(10)
    month_name = calendar.month_name[month]
    show_name = getattr(cfg.publishing, "rss_title", show_slug)

    next_month = month % 12 + 1
    next_year = year if month < 12 else year + 1
    next_month_name = calendar.month_name[next_month]

    prompt = f"""\
You are writing the monthly report for {show_name}, part of the Nerra Network.

Generate a comprehensive "State of {show_name} — {month_name} {year}" \
report based on {len(episodes)} daily episodes.

## Episode Hooks (chronological):
{chr(10).join(all_hooks)}

## Most Mentioned Entities:
{chr(10).join(f"- {entity}: {count} mentions" for entity, count in entity_counts)}

## Top Topics:
{chr(10).join(f"- {topic}: {count} episodes" for topic, count in topic_counts)}

## Episode Digests (truncated):
{chr(10).join(episode_digests[:15])}

## Instructions:

Write a comprehensive monthly report in markdown with these sections:

# State of {show_name} — {month_name} {year}

## Executive Summary
2-3 paragraphs capturing the month's most important developments and themes.

## Key Events Timeline
A chronological list of the month's most significant events with dates and \
brief descriptions (10-15 events).

## Trend Analysis
3-4 major trends with supporting evidence from the month's coverage. Each \
trend should be 2-3 paragraphs with specific examples and data points.

## Most Active Players
Brief profiles of the entities that dominated the month's news and what \
they did.

## By the Numbers
Key statistics, metrics, and data points from the month's coverage.

## What to Watch in {next_month_name} {next_year}
3-5 things to watch based on the month's developments.

Keep the tone authoritative and analytical. Target 2500-3500 words."""

    system_prompt = (
        f"You are the monthly report editor for {show_name}. "
        f"Write comprehensive, data-driven analysis."
    )

    try:
        text, meta = _call_grok(
            prompt=prompt,
            model=cfg.llm.model,
            temperature=0.4,
            max_tokens=8000,
            system_prompt=system_prompt,
        )
        logger.info(
            "[Synthesizer] Monthly report for %s %d-%02d: %d chars",
            show_slug, year, month, len(text),
        )
        return text
    except Exception as e:
        logger.error(
            "[Synthesizer] Monthly report failed for %s: %s", show_slug, e,
        )
        return None


# ---------------------------------------------------------------------------
# Cross-show intelligence briefing
# ---------------------------------------------------------------------------

def synthesize_cross_show_briefing(
    week_ending: date,
) -> Optional[str]:
    """Generate a cross-network weekly intelligence briefing.

    Finds connections and themes across all shows.
    """
    start_date = (week_ending - timedelta(days=6)).isoformat()
    end_date = week_ending.isoformat()

    episodes = query_all_shows_range(start_date, end_date)
    if len(episodes) < 10:
        logger.warning(
            "[Synthesizer] Only %d total episodes for cross-show briefing, "
            "skipping", len(episodes),
        )
        return None

    # Group by show and find cross-show entities
    by_show: Dict[str, list] = {}
    entity_show_map: Dict[str, set[str]] = {}

    for ep in episodes:
        show = ep.get("show_name", ep["show_slug"])
        by_show.setdefault(show, []).append(ep)
        for entity in ep.get("entities", []):
            entity_show_map.setdefault(entity, set()).add(show)

    cross_entities = {
        e: shows for e, shows in entity_show_map.items() if len(shows) >= 2
    }

    # Build per-show summaries
    show_sections = []
    for show_name, eps in sorted(by_show.items()):
        hooks = [f"- {ep.get('hook', 'N/A')}" for ep in eps[:5]]
        show_sections.append(
            f"### {show_name} ({len(eps)} episodes)\n{chr(10).join(hooks)}"
        )

    cross_lines = [
        f"- **{entity}** appeared in: {', '.join(sorted(shows))}"
        for entity, shows in sorted(
            cross_entities.items(), key=lambda x: -len(x[1])
        )[:15]
    ]

    prompt = f"""\
You are the editor-in-chief of the Nerra Network, a podcast network with 9 \
daily shows covering AI, Tesla/energy, space, biotech, environmental policy, \
world news, Russian finance, and Russian language learning.

Write the weekly cross-network intelligence briefing for the week of \
{start_date} to {end_date}.

## This Week's Coverage by Show:
{chr(10).join(show_sections)}

## Cross-Show Entity Connections:
{chr(10).join(cross_lines) if cross_lines else "No cross-show entities this week."}

## Instructions:

Write a "Nerra Network Weekly Intelligence" briefing in markdown:

# Nerra Network Weekly Intelligence — Week of {end_date}

## The Big Connections
2-3 paragraphs identifying the most interesting cross-domain threads this \
week. Where do AI developments intersect with energy? How do space \
discoveries relate to biotech? What regulatory moves affect multiple domains?

## Domain Roundup
A brief (3-4 sentence) summary of each show's week, focusing on the single \
most important development per domain.

## Cross-Domain Watch
3-5 emerging stories that span multiple shows' coverage areas.

## The Week Ahead
What to watch across all domains next week.

Keep it under 1200 words. The tone should be sharp, insightful, and focused \
on connections that no single-domain publication would catch."""

    try:
        text, meta = _call_grok(
            prompt=prompt,
            model="grok-4.20-non-reasoning",
            temperature=0.5,
            max_tokens=4000,
            system_prompt=(
                "You are the editor-in-chief of the Nerra Network, an "
                "independent podcast network. You specialize in finding "
                "cross-domain connections."
            ),
        )
        logger.info(
            "[Synthesizer] Cross-show briefing: %d chars", len(text),
        )
        return text
    except Exception as e:
        logger.error("[Synthesizer] Cross-show briefing failed: %s", e)
        return None
