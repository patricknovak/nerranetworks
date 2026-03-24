"""Podcast chapter generation from script section markers.

Parses an LLM-generated podcast script to identify section boundaries,
calculates approximate chapter timestamps using word-count proportions,
and writes Podcasting 2.0-compatible chapter JSON files.

Usage in the pipeline (run_show.py):
    1. After podcast script is generated + cleaned, call ``parse_chapters()``
    2. After final MP3 is produced, call ``calculate_timestamps()``
    3. Call ``write_chapters_json()`` to persist alongside the episode
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Chapter:
    """A single chapter in a podcast episode."""

    title: str
    startTime: float = 0.0
    endTime: float = 0.0
    # Word range within the script (used for proportion calculation)
    word_start: int = 0
    word_end: int = 0
    # Character range within the script (used for text splitting)
    char_start: int = 0
    char_end: int = 0


def parse_chapters(
    script: str,
    section_markers: list,
    *,
    show_name: str = "",
) -> List[Chapter]:
    """Parse a podcast script to identify section boundaries.

    Parameters
    ----------
    script:
        The cleaned podcast script text (after speaker prefix removal,
        pronunciation fixes, etc.).
    section_markers:
        List of ``SectionMarker`` objects (or dicts with ``pattern`` and
        ``title`` keys) from the show's YAML config.
    show_name:
        Show name for logging context.

    Returns
    -------
    list[Chapter]
        Ordered list of chapters with word boundaries set.  Timestamps
        are set to 0 — call ``calculate_timestamps()`` after the audio
        is produced to map word proportions to real timestamps.
    """
    if not section_markers:
        logger.info("No section markers configured — skipping chapter parsing")
        return []

    # Build compiled patterns
    compiled_markers = []
    for marker in section_markers:
        pattern = marker.pattern if hasattr(marker, "pattern") else marker.get("pattern", "")
        title = marker.title if hasattr(marker, "title") else marker.get("title", "")
        if not pattern or not title:
            continue
        try:
            compiled_markers.append((re.compile(pattern, re.IGNORECASE), title))
        except re.error as exc:
            logger.warning("Invalid chapter marker regex %r: %s", pattern, exc)

    if not compiled_markers:
        return []

    # Split script into words with their character positions
    words = script.split()
    total_words = len(words)
    total_chars = len(script)
    if total_words == 0:
        return []

    # Scan line by line, tracking both word index and character offset
    lines = script.splitlines(keepends=True)
    word_idx = 0
    char_offset = 0
    matches: list[tuple[int, int, str]] = []  # (word_index, char_offset, title)

    for line in lines:
        line_words = line.split()
        line_word_count = len(line_words)
        line_stripped = line.rstrip("\n\r")

        for regex, title in compiled_markers:
            if regex.search(line_stripped):
                # Avoid duplicate consecutive matches for the same title
                if not matches or matches[-1][2] != title:
                    matches.append((word_idx, char_offset, title))
                break  # Only match first marker per line

        word_idx += line_word_count
        char_offset += len(line)

    if not matches:
        logger.info("No chapter markers matched in podcast script for %s", show_name)
        return []

    # Build Chapter objects from matches
    chapters: list[Chapter] = []
    for i, (w_start, c_start, title) in enumerate(matches):
        w_end = matches[i + 1][0] if i + 1 < len(matches) else total_words
        c_end = matches[i + 1][1] if i + 1 < len(matches) else total_chars
        chapters.append(Chapter(
            title=title,
            word_start=w_start,
            word_end=w_end,
            char_start=c_start,
            char_end=c_end,
        ))

    logger.info(
        "Parsed %d chapters for %s: %s",
        len(chapters),
        show_name or "show",
        [c.title for c in chapters],
    )
    return chapters


def split_script_at_chapters(
    script: str,
    chapters: List[Chapter],
) -> List[str]:
    """Split a podcast script into text sections at chapter boundaries.

    Uses the ``char_start``/``char_end`` character offsets stored by
    ``parse_chapters()`` to slice the script into one text segment per
    chapter.  Each segment can then be synthesized separately via TTS.

    Parameters
    ----------
    script:
        The full podcast script text (same text passed to ``parse_chapters()``).
    chapters:
        Chapters with ``char_start``/``char_end`` set.

    Returns
    -------
    list[str]
        Ordered list of text sections, one per chapter.
        Empty sections are preserved to keep alignment with chapters.
    """
    if not chapters:
        return [script] if script.strip() else []

    sections: list[str] = []

    # Include any text before the first chapter as a leading section.
    # Without this, content before the first matched marker is lost.
    first_start = chapters[0].char_start
    if first_start > 0:
        preamble = script[:first_start].strip()
        if preamble:
            sections.append(preamble)

    for ch in chapters:
        section = script[ch.char_start:ch.char_end].strip()
        sections.append(section)

    return sections


def calculate_timestamps(
    chapters: List[Chapter],
    total_duration: float,
    *,
    music_intro_offset: float = 0.0,
) -> List[Chapter]:
    """Map word-count proportions to real timestamps.

    Parameters
    ----------
    chapters:
        Chapters with ``word_start``/``word_end`` set by ``parse_chapters()``.
    total_duration:
        Total duration of the final mixed MP3 in seconds.
    music_intro_offset:
        Seconds of music-only time before the voice content begins.
        Calculated as ``intro_duration + voice_intro_delay`` from audio config.
        The first chapter starts after this offset.

    Returns
    -------
    list[Chapter]
        Same chapters with ``startTime`` and ``endTime`` populated.
    """
    if not chapters or total_duration <= 0:
        return chapters

    # Voice content occupies the time after the music intro
    # We don't subtract outro since voice may overlap with it (crossfade)
    voice_duration = total_duration - music_intro_offset
    if voice_duration <= 0:
        voice_duration = total_duration
        music_intro_offset = 0.0

    # Total words across all chapters
    total_words = chapters[-1].word_end if chapters else 0
    if total_words <= 0:
        return chapters

    for ch in chapters:
        proportion_start = ch.word_start / total_words
        proportion_end = ch.word_end / total_words
        ch.startTime = round(music_intro_offset + proportion_start * voice_duration, 1)
        ch.endTime = round(music_intro_offset + proportion_end * voice_duration, 1)

    # Clamp final chapter end to total duration
    if chapters:
        chapters[-1].endTime = round(total_duration, 1)

    return chapters


def write_chapters_json(
    chapters: List[Chapter],
    output_path: Path,
    *,
    episode_title: str = "",
) -> Optional[Path]:
    """Write chapters in Podcasting 2.0 JSON Chapters format.

    Format spec: https://github.com/Podcastindex-org/podcast-namespace/blob/main/chapters/jsonChapters.md

    Parameters
    ----------
    chapters:
        Chapters with timestamps populated.
    output_path:
        Where to write the JSON file.
    episode_title:
        Optional episode title for the top-level ``title`` field.

    Returns
    -------
    Path or None
        The output path on success, ``None`` if no chapters or on error.
    """
    if not chapters:
        logger.info("No chapters to write")
        return None

    data = {
        "version": "1.2.0",
        "chapters": [],
    }
    if episode_title:
        data["title"] = episode_title

    for ch in chapters:
        entry = {
            "startTime": ch.startTime,
            "title": ch.title,
        }
        if ch.endTime > ch.startTime:
            entry["endTime"] = ch.endTime
        data["chapters"].append(entry)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info("Chapters JSON written: %s (%d chapters)", output_path, len(chapters))
        return output_path
    except Exception as exc:
        logger.error("Failed to write chapters JSON: %s", exc)
        return None
