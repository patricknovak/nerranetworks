#!/usr/bin/env python3
"""Daily episode quality review.

Scans all episodes produced today, runs automated quality checks, and
optionally creates GitHub issues for problems found.

Usage:
    python review_episodes.py [--date YYYY-MM-DD] [--create-issues] [--show SLUG]

Checks performed:
    - Digest length (too short / too long)
    - Podcast script length vs target duration
    - Audio duration vs expectations
    - Repeated content across today's episodes
    - LLM artifacts leaked into scripts (URLs, metadata, template vars)
    - Missing required sections (per-show validation)
    - Pipeline errors (stages that failed in metrics)
    - Cross-episode duplicate stories (same-day)
    - AI review via Grok for content quality (optional, needs GROK_API_KEY)

Exit codes:
    0 — all episodes OK (or no episodes today)
    1 — critical issues found (episodes that should be considered for removal)
    2 — warnings only (fixable for future episodes)
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("review")

PROJECT_ROOT = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    show: str
    episode: int
    severity: str  # "critical", "warning", "info"
    title: str
    detail: str
    file_path: str = ""

    @property
    def label(self) -> str:
        return {
            "critical": "severity: critical",
            "warning": "severity: warning",
            "info": "severity: info",
        }.get(self.severity, "severity: info")


@dataclass
class EpisodeReview:
    show_slug: str
    show_name: str
    episode_num: int
    date: str
    digest_path: Optional[Path] = None
    tts_path: Optional[Path] = None
    metrics_path: Optional[Path] = None
    chapters_path: Optional[Path] = None
    digest_text: str = ""
    tts_text: str = ""
    metrics: dict = field(default_factory=dict)
    issues: List[Issue] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Show registry (maps slug -> config needed for review)
# ---------------------------------------------------------------------------

SHOW_REGISTRY = {
    "tesla": {
        "name": "Tesla Shorts Time",
        "output_dir": "digests/tesla_shorts_time",
        "prefix": "Tesla_Shorts_Time_Pod",
        "min_digest_chars": 3000,
        "max_digest_chars": 20000,
        "min_tts_words": 2200,
        "min_audio_s": 300,
        "max_audio_s": 1800,
        "required_sections": ["Top", "X Takeover", "First Principles"],
        # "Counterpoint" is sometimes called "Short Spot" or "challenge worth discussing"
    },
    "omni_view": {
        "name": "Omni View",
        "output_dir": "digests/omni_view",
        "prefix": "Omni_View_Ep",
        "min_digest_chars": 2000,
        "max_digest_chars": 18000,
        "min_tts_words": 1500,
        "min_audio_s": 240,
        "max_audio_s": 1500,
        "required_sections": [],
    },
    "fascinating_frontiers": {
        "name": "Fascinating Frontiers",
        "output_dir": "digests/fascinating_frontiers",
        "prefix": "Fascinating_Frontiers_Ep",
        "min_digest_chars": 2000,
        "max_digest_chars": 18000,
        "min_tts_words": 1500,
        "min_audio_s": 240,
        "max_audio_s": 1500,
        "required_sections": [],
    },
    "planetterrian": {
        "name": "Planetterrian Daily",
        "output_dir": "digests/planetterrian",
        "prefix": "Planetterrian_Ep",
        "min_digest_chars": 2000,
        "max_digest_chars": 18000,
        "min_tts_words": 1500,
        "min_audio_s": 240,
        "max_audio_s": 1500,
        "required_sections": [],
    },
    "env_intel": {
        "name": "Environmental Intelligence",
        "output_dir": "digests/env_intel",
        "prefix": "Env_Intel_Ep",
        "min_digest_chars": 2000,
        "max_digest_chars": 18000,
        "min_tts_words": 1500,
        "min_audio_s": 240,
        "max_audio_s": 1500,
        "required_sections": [],
    },
    "models_agents": {
        "name": "Models & Agents",
        "output_dir": "digests/models_agents",
        "prefix": "Models_Agents_Ep",
        "min_digest_chars": 2000,
        "max_digest_chars": 18000,
        "min_tts_words": 1500,
        "min_audio_s": 240,
        "max_audio_s": 1500,
        "required_sections": [],
    },
    "models_agents_beginners": {
        "name": "Models & Agents for Beginners",
        "output_dir": "digests/models_agents_beginners",
        "prefix": "MAB_Ep",
        "min_digest_chars": 2000,
        "max_digest_chars": 18000,
        "min_tts_words": 1100,
        "min_audio_s": 180,
        "max_audio_s": 1500,
        "required_sections": [],
    },
    "finansy_prosto": {
        "name": "Finansy Prosto",
        "output_dir": "digests/finansy_prosto",
        "prefix": "Finansy_Prosto_Ep",
        "min_digest_chars": 1500,
        "max_digest_chars": 18000,
        "min_tts_words": 800,
        "min_audio_s": 180,
        "max_audio_s": 1200,
        "required_sections": [],
    },
    "modern_investing": {
        "name": "Modern Investing Techniques",
        "output_dir": "digests/modern_investing",
        "prefix": "Modern_Investing",
        "min_digest_chars": 2500,
        "max_digest_chars": 20000,
        "min_tts_words": 2000,
        "min_audio_s": 300,
        "max_audio_s": 1800,
        "required_sections": ["Strategy Spotlight", "Practice Investment"],
    },
    "privet_russian": {
        "name": "Privet Russian",
        "output_dir": "digests/privet_russian",
        "prefix": "Privet_Russian_Ep",
        "min_digest_chars": 1500,
        "max_digest_chars": 18000,
        "min_tts_words": 800,
        "min_audio_s": 180,
        "max_audio_s": 1200,
        "required_sections": [],
    },
}


# ---------------------------------------------------------------------------
# Discovery: find today's episodes
# ---------------------------------------------------------------------------

def discover_episodes(target_date: datetime.date, show_filter: str = "") -> List[EpisodeReview]:
    """Find all episodes generated on *target_date*."""
    date_str = target_date.strftime("%Y%m%d")
    episodes: List[EpisodeReview] = []

    for slug, info in SHOW_REGISTRY.items():
        if show_filter and slug != show_filter:
            continue

        output_dir = PROJECT_ROOT / info["output_dir"]
        if not output_dir.exists():
            continue

        # Find digest .md files matching today's date
        for md_file in sorted(output_dir.glob(f"*{date_str}.md")):
            # Extract episode number from filename
            m = re.search(r"Ep(\d+)", md_file.name)
            if not m:
                continue
            ep_num = int(m.group(1))

            # Find companion files
            stem = md_file.stem  # e.g. Tesla_Shorts_Time_Pod_Ep414_20260322
            tts_file = output_dir / f"{stem}_tts.txt"
            metrics_file = output_dir / f"metrics_ep{ep_num:03d}.json"
            chapters_file = output_dir / f"chapters_ep{ep_num:03d}.json"

            review = EpisodeReview(
                show_slug=slug,
                show_name=info["name"],
                episode_num=ep_num,
                date=target_date.isoformat(),
                digest_path=md_file if md_file.exists() else None,
                tts_path=tts_file if tts_file.exists() else None,
                metrics_path=metrics_file if metrics_file.exists() else None,
                chapters_path=chapters_file if chapters_file.exists() else None,
            )

            if review.digest_path:
                review.digest_text = review.digest_path.read_text(encoding="utf-8")
            if review.tts_path:
                review.tts_text = review.tts_path.read_text(encoding="utf-8")
            if review.metrics_path:
                try:
                    review.metrics = json.loads(review.metrics_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass

            episodes.append(review)

    return episodes


# ---------------------------------------------------------------------------
# Automated checks
# ---------------------------------------------------------------------------

def check_digest_length(ep: EpisodeReview, info: dict) -> None:
    """Check digest is within expected length bounds."""
    if not ep.digest_text:
        ep.issues.append(Issue(
            ep.show_slug, ep.episode_num, "critical",
            "Missing digest file",
            f"No digest .md found for {ep.show_name} Ep{ep.episode_num}",
        ))
        return

    chars = len(ep.digest_text)
    if chars < info["min_digest_chars"]:
        ep.issues.append(Issue(
            ep.show_slug, ep.episode_num, "critical",
            f"Digest too short ({chars} chars)",
            f"Digest is only {chars} characters (minimum: {info['min_digest_chars']}). "
            f"The LLM likely returned a truncated or low-quality response.",
            file_path=str(ep.digest_path),
        ))
    elif chars > info["max_digest_chars"]:
        ep.issues.append(Issue(
            ep.show_slug, ep.episode_num, "warning",
            f"Digest unusually long ({chars} chars)",
            f"Digest is {chars} characters (max expected: {info['max_digest_chars']}). "
            f"May contain duplicate content or LLM rambling.",
            file_path=str(ep.digest_path),
        ))


def check_tts_script(ep: EpisodeReview, info: dict) -> None:
    """Check podcast script quality."""
    if not ep.tts_text:
        # Not all shows generate a separate _tts.txt
        return

    words = len(ep.tts_text.split())
    min_words = info["min_tts_words"]

    if words < min_words * 0.5:
        ep.issues.append(Issue(
            ep.show_slug, ep.episode_num, "critical",
            f"Podcast script dangerously short ({words} words)",
            f"Script has only {words} words (target: {min_words}+). "
            f"Episode will sound thin and rushed. Consider deletion.",
            file_path=str(ep.tts_path),
        ))
    elif words < min_words:
        ep.issues.append(Issue(
            ep.show_slug, ep.episode_num, "warning",
            f"Podcast script below target ({words} words)",
            f"Script has {words} words (target: {min_words}+). "
            f"Episode may feel shorter than usual.",
            file_path=str(ep.tts_path),
        ))


def check_audio_duration(ep: EpisodeReview, info: dict) -> None:
    """Check audio duration from metrics."""
    duration = ep.metrics.get("counters", {}).get("audio_duration_s")
    if duration is None:
        return

    min_s = info["min_audio_s"]
    max_s = info["max_audio_s"]

    if duration < min_s * 0.5:
        ep.issues.append(Issue(
            ep.show_slug, ep.episode_num, "critical",
            f"Audio extremely short ({duration:.0f}s)",
            f"Audio is only {duration:.0f}s ({duration/60:.1f} min). "
            f"Minimum is {min_s}s. Episode is likely broken or truncated.",
        ))
    elif duration < min_s:
        ep.issues.append(Issue(
            ep.show_slug, ep.episode_num, "warning",
            f"Audio below minimum ({duration:.0f}s)",
            f"Audio is {duration:.0f}s ({duration/60:.1f} min), "
            f"below the {min_s}s minimum.",
        ))
    elif duration > max_s:
        ep.issues.append(Issue(
            ep.show_slug, ep.episode_num, "warning",
            f"Audio unusually long ({duration:.0f}s)",
            f"Audio is {duration:.0f}s ({duration/60:.1f} min), "
            f"above the {max_s}s expected maximum.",
        ))


def check_pipeline_errors(ep: EpisodeReview) -> None:
    """Check for pipeline stage failures in metrics."""
    stages = ep.metrics.get("stages", [])
    for stage in stages:
        if not stage.get("success", True):
            error = stage.get("error", "unknown error")
            ep.issues.append(Issue(
                ep.show_slug, ep.episode_num, "critical",
                f"Pipeline stage failed: {stage['name']}",
                f"Stage '{stage['name']}' failed with: {error}",
            ))


def check_leaked_artifacts(ep: EpisodeReview) -> None:
    """Check for LLM artifacts that shouldn't appear in the podcast script."""
    text = ep.tts_text or ep.digest_text
    if not text:
        return

    # Patterns that indicate LLM/prompt leakage or metadata in TTS output
    artifact_patterns = [
        (r"https?://\S+", "URL leaked into script"),
        (r"\{[a-z_]+\}", "Unfilled template placeholder"),
        (r"(?i)word\s*count\s*[:：]", "Word count metadata in script"),
        (r"(?i)character\s*count\s*[:：]", "Character count metadata in script"),
        (r"(?i)^(RULES|NEVER INCLUDE|CONTENT FOCUS)\s*:", "Leaked prompt instructions"),
        (r"(?i)as an AI language model", "AI self-reference leaked"),
        (r"(?i)I('m| am) (an AI|a language model|ChatGPT|Claude)", "AI identity leaked"),
        (r"Source:\s*https?://", "Source URL in podcast script"),
    ]

    # Only check TTS text for spoken artifacts
    check_text = ep.tts_text if ep.tts_text else text
    for pattern, desc in artifact_patterns:
        matches = re.findall(pattern, check_text, re.MULTILINE)
        if matches:
            # URLs in digest are normal; only flag in TTS script
            if "URL" in desc and not ep.tts_text:
                continue
            sample = matches[0] if isinstance(matches[0], str) else matches[0]
            ep.issues.append(Issue(
                ep.show_slug, ep.episode_num, "warning",
                f"Artifact in script: {desc}",
                f"Found {len(matches)} occurrence(s) of: {desc}. "
                f"Sample: '{str(sample)[:100]}'",
            ))


def check_required_sections(ep: EpisodeReview, info: dict) -> None:
    """Check that required sections are present in the digest."""
    required = info.get("required_sections", [])
    if not required or not ep.digest_text:
        return

    text_lower = ep.digest_text.lower()
    for section in required:
        if section.lower() not in text_lower:
            ep.issues.append(Issue(
                ep.show_slug, ep.episode_num, "warning",
                f"Missing section: {section}",
                f"Required section '{section}' not found in digest. "
                f"Episode may be missing expected content.",
            ))


def check_repetition(ep: EpisodeReview) -> None:
    """Check for excessive repetition within the episode."""
    text = ep.tts_text or ep.digest_text
    if not text:
        return

    words = text.split()
    if len(words) < 100:
        return

    from collections import Counter
    # Check 3-word phrases for repetition
    trigrams = [" ".join(words[i:i+3]).lower() for i in range(len(words) - 2)]
    counts = Counter(trigrams)

    # Skip common phrases, pronunciation expansions (single-letter words from
    # TTS abbreviation splitting like TFSA -> "t f s a"), and intentional
    # repetition in language-learning shows ("repeat after me").
    skip_phrases = {
        "of the the", "in the the", "and the the", "the the the",
        "repeat after me", "repeat after me.", "repeat after me:",
    }
    # Single-letter trigrams are TTS pronunciation splits (e.g. "f s d", "e s a").
    # Also match "the a i", "an a i", "your t f" — article/pronoun + split abbreviation.
    _SINGLE_LETTER_TRIGRAM = re.compile(r"^[a-z] [a-z] [a-z]$")
    _ABBREV_CONTEXT = re.compile(r"^(?:the|an|a|of|your|my|our|its|and) [a-z] [a-z]$")

    for phrase, count in counts.most_common(10):
        if phrase in skip_phrases:
            continue
        if _SINGLE_LETTER_TRIGRAM.match(phrase):
            continue
        if _ABBREV_CONTEXT.match(phrase):
            continue
        if count >= 5:
            ep.issues.append(Issue(
                ep.show_slug, ep.episode_num, "warning",
                f"Excessive repetition: '{phrase}' ({count}x)",
                f"The phrase '{phrase}' appears {count} times, "
                f"suggesting possible LLM hallucination or loop.",
            ))
            break  # One is enough


def check_cross_episode_duplicates(episodes: List[EpisodeReview]) -> None:
    """Check for duplicate stories across different shows on the same day."""
    if len(episodes) < 2:
        return

    # Extract headlines from each episode
    ep_headlines: dict[str, list[str]] = {}
    for ep in episodes:
        if not ep.digest_text:
            continue
        headlines = []
        for line in ep.digest_text.splitlines():
            line = line.strip()
            # Match numbered items or ### headers
            m = re.match(r"(?:\d+\.\s+\*{0,2})(.+?)(?:\*{0,2}\s*[—–-]|\s*$)", line)
            if m and len(m.group(1)) > 20:
                headlines.append(m.group(1).strip().lower())
            elif line.startswith("### ") and len(line) > 10:
                headlines.append(line[4:].strip().lower())
        ep_headlines[f"{ep.show_slug}:{ep.episode_num}"] = headlines

    # Simple overlap detection (word-based)
    keys = list(ep_headlines.keys())
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            h1 = ep_headlines.get(keys[i], [])
            h2 = ep_headlines.get(keys[j], [])
            duplicates = []
            for a in h1:
                a_words = set(a.split())
                for b in h2:
                    b_words = set(b.split())
                    if len(a_words) < 4 or len(b_words) < 4:
                        continue
                    overlap = len(a_words & b_words) / max(len(a_words | b_words), 1)
                    if overlap > 0.6:
                        duplicates.append((a[:60], b[:60]))

            if len(duplicates) >= 3:
                slug_i = keys[i].split(":")[0]
                ep_i = int(keys[i].split(":")[1])
                slug_j = keys[j].split(":")[0]
                for ep in episodes:
                    if ep.show_slug == slug_i and ep.episode_num == ep_i:
                        ep.issues.append(Issue(
                            ep.show_slug, ep.episode_num, "info",
                            f"Significant story overlap with {slug_j}",
                            f"Found {len(duplicates)} overlapping stories with {slug_j}. "
                            f"Example: '{duplicates[0][0]}...'",
                        ))
                        break


# ---------------------------------------------------------------------------
# AI-powered review (optional, uses Grok)
# ---------------------------------------------------------------------------

def ai_review_episode(ep: EpisodeReview) -> None:
    """Use Grok to review episode quality. Requires GROK_API_KEY."""
    api_key = (os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY") or "").strip()
    if not api_key:
        return

    text = ep.tts_text or ep.digest_text
    if not text:
        return

    # Truncate to avoid massive prompts
    if len(text) > 8000:
        text = text[:8000] + "\n...[truncated]"

    prompt = (
        f"You are a podcast quality reviewer. Review this episode of '{ep.show_name}' "
        f"(Episode {ep.episode_num}, {ep.date}).\n\n"
        f"TEXT:\n{text}\n\n"
        f"Check for these specific problems and rate each YES or NO:\n"
        f"1. FACTUAL_ERRORS: Are there obvious factual errors or contradictions?\n"
        f"2. INCOHERENT: Are there sections that don't make sense or seem garbled?\n"
        f"3. REPETITIVE: Are stories or paragraphs repeated verbatim or near-verbatim?\n"
        f"4. OFF_TOPIC: Is significant content unrelated to the show's topic?\n"
        f"5. TONE_BREAK: Are there abrupt tone shifts or inappropriate language?\n"
        f"6. INCOMPLETE: Does the episode feel like it ends abruptly or is missing sections?\n"
        f"7. QUALITY_SCORE: Rate overall quality 1-10 (1=terrible, 10=perfect)\n\n"
        f"Format your response EXACTLY like this (one per line):\n"
        f"FACTUAL_ERRORS: YES/NO — [brief explanation if YES]\n"
        f"INCOHERENT: YES/NO — [brief explanation if YES]\n"
        f"REPETITIVE: YES/NO — [brief explanation if YES]\n"
        f"OFF_TOPIC: YES/NO — [brief explanation if YES]\n"
        f"TONE_BREAK: YES/NO — [brief explanation if YES]\n"
        f"INCOMPLETE: YES/NO — [brief explanation if YES]\n"
        f"QUALITY_SCORE: [1-10]\n"
        f"SUMMARY: [1-2 sentence overall assessment]\n"
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1", timeout=120)
        resp = client.chat.completions.create(
            model="grok-3-mini-fast",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
        )
        review_text = resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.warning("AI review failed for %s Ep%d: %s", ep.show_slug, ep.episode_num, exc)
        return

    # Parse AI review
    quality_score = 0
    m = re.search(r"QUALITY_SCORE:\s*(\d+)", review_text)
    if m:
        quality_score = int(m.group(1))

    summary_m = re.search(r"SUMMARY:\s*(.+)", review_text)
    summary = summary_m.group(1).strip() if summary_m else ""

    # Flag critical AI findings
    critical_checks = ["FACTUAL_ERRORS", "INCOHERENT", "REPETITIVE"]
    for check in critical_checks:
        m = re.search(rf"{check}:\s*YES\s*[—–-]\s*(.+)", review_text)
        if m:
            severity = "critical" if check in ("INCOHERENT", "REPETITIVE") else "warning"
            ep.issues.append(Issue(
                ep.show_slug, ep.episode_num, severity,
                f"AI review: {check.replace('_', ' ').title()}",
                m.group(1).strip(),
            ))

    warning_checks = ["OFF_TOPIC", "TONE_BREAK", "INCOMPLETE"]
    for check in warning_checks:
        m = re.search(rf"{check}:\s*YES\s*[—–-]\s*(.+)", review_text)
        if m:
            ep.issues.append(Issue(
                ep.show_slug, ep.episode_num, "warning",
                f"AI review: {check.replace('_', ' ').title()}",
                m.group(1).strip(),
            ))

    if quality_score > 0 and quality_score <= 3:
        ep.issues.append(Issue(
            ep.show_slug, ep.episode_num, "critical",
            f"AI quality score: {quality_score}/10",
            f"Grok rated this episode {quality_score}/10. {summary}",
        ))
    elif quality_score > 0 and quality_score <= 5:
        ep.issues.append(Issue(
            ep.show_slug, ep.episode_num, "warning",
            f"AI quality score: {quality_score}/10",
            f"Grok rated this episode {quality_score}/10. {summary}",
        ))
    elif quality_score > 0:
        ep.issues.append(Issue(
            ep.show_slug, ep.episode_num, "info",
            f"AI quality score: {quality_score}/10",
            summary,
        ))


# ---------------------------------------------------------------------------
# GitHub issue creation
# ---------------------------------------------------------------------------

def create_github_issue(
    target_date: str,
    episodes: List[EpisodeReview],
    critical_only: bool = False,
) -> Optional[str]:
    """Create a GitHub issue summarizing today's review.

    Returns the issue URL on success, None if no issues to report or gh fails.
    """
    all_issues: List[Issue] = []
    for ep in episodes:
        all_issues.extend(ep.issues)

    if critical_only:
        all_issues = [i for i in all_issues if i.severity == "critical"]

    if not all_issues:
        return None

    critical = [i for i in all_issues if i.severity == "critical"]
    warnings = [i for i in all_issues if i.severity == "warning"]
    infos = [i for i in all_issues if i.severity == "info"]

    # Build issue title
    n_shows = len(set(i.show for i in all_issues))
    if critical:
        title = f"Daily Review {target_date}: {len(critical)} critical issue(s) across {n_shows} show(s)"
    else:
        title = f"Daily Review {target_date}: {len(warnings)} warning(s) across {n_shows} show(s)"

    # Build issue body
    body_lines = [
        f"## Daily Episode Review — {target_date}\n",
        f"**Episodes reviewed:** {len(episodes)}",
        f"**Issues found:** {len(critical)} critical, {len(warnings)} warning(s), {len(infos)} info\n",
    ]

    # Episodes summary table
    body_lines.append("### Episodes Reviewed\n")
    body_lines.append("| Show | Episode | Issues |")
    body_lines.append("|------|---------|--------|")
    for ep in episodes:
        n_crit = sum(1 for i in ep.issues if i.severity == "critical")
        n_warn = sum(1 for i in ep.issues if i.severity == "warning")
        status = ""
        if n_crit:
            status = f"{n_crit} critical"
        if n_warn:
            status += f"{', ' if status else ''}{n_warn} warning(s)"
        if not status:
            status = "OK"
        body_lines.append(f"| {ep.show_name} | Ep{ep.episode_num:03d} | {status} |")

    # Critical issues
    if critical:
        body_lines.append("\n### Critical Issues\n")
        body_lines.append("These episodes may need to be removed from the RSS feed:\n")
        for issue in critical:
            body_lines.append(f"- **[{issue.show} Ep{issue.episode:03d}]** {issue.title}")
            body_lines.append(f"  {issue.detail}")

    # Warnings
    if warnings:
        body_lines.append("\n### Warnings\n")
        body_lines.append("Issues to address in future episodes:\n")
        for issue in warnings:
            body_lines.append(f"- **[{issue.show} Ep{issue.episode:03d}]** {issue.title}")
            body_lines.append(f"  {issue.detail}")

    # Info
    if infos:
        body_lines.append("\n### Info\n")
        for issue in infos:
            body_lines.append(f"- **[{issue.show} Ep{issue.episode:03d}]** {issue.title}")
            body_lines.append(f"  {issue.detail}")

    body_lines.append(f"\n---\n*Auto-generated by `review_episodes.py`*")

    body = "\n".join(body_lines)

    # Assign labels
    labels = ["automated-review"]
    if critical:
        labels.append("severity: critical")
    if warnings:
        labels.append("severity: warning")

    # Create via gh CLI
    label_args = " ".join(f'--label "{l}"' for l in labels)
    try:
        result = subprocess.run(
            [
                "gh", "issue", "create",
                "--title", title,
                "--body", body,
                *[arg for l in labels for arg in ("--label", l)],
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            logger.info("Created GitHub issue: %s", url)
            return url
        else:
            logger.warning("gh issue create failed: %s", result.stderr.strip())
            return None
    except FileNotFoundError:
        logger.warning("gh CLI not found — skipping issue creation")
        return None
    except Exception as exc:
        logger.warning("Failed to create GitHub issue: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Claude Code output format
# ---------------------------------------------------------------------------

def format_for_claude(target_date: str, episodes: List[EpisodeReview]) -> str:
    """Format review results as a prompt you can paste directly into Claude Code.

    Groups issues by type with file paths and actionable instructions.
    """
    all_issues: List[tuple[EpisodeReview, Issue]] = []
    for ep in episodes:
        for issue in ep.issues:
            all_issues.append((ep, issue))

    if not all_issues:
        return (
            f"# Episode Review — {target_date}\n\n"
            f"All {len(episodes)} episodes passed review. No issues found."
        )

    critical = [(ep, i) for ep, i in all_issues if i.severity == "critical"]
    warnings = [(ep, i) for ep, i in all_issues if i.severity == "warning"]

    lines = [
        f"Fix the following issues found by the daily episode review for {target_date}.",
        f"There are {len(critical)} critical and {len(warnings)} warning-level issues.",
        "",
    ]

    # Group by issue type for efficient fixing
    issue_groups: dict[str, list[tuple[EpisodeReview, Issue]]] = {}
    for ep, issue in all_issues:
        if issue.severity == "info":
            continue
        key = issue.title.split(":")[0].strip() if ":" in issue.title else issue.title
        # Normalize similar titles
        if "word count" in key.lower() or "artifact" in key.lower():
            key = "LLM artifacts leaked into scripts"
        elif "missing section" in key.lower():
            key = "Missing required sections"
        elif "repetition" in key.lower():
            key = "Excessive repetition"
        elif "too short" in key.lower() or "below target" in key.lower() or "dangerously short" in key.lower():
            key = "Script/digest too short"
        elif "too long" in key.lower() or "unusually long" in key.lower():
            key = "Digest too long"
        elif "pipeline" in key.lower():
            key = "Pipeline failures"
        elif "audio" in key.lower():
            key = "Audio duration issues"
        elif "AI quality" in key.lower() or "AI review" in key.lower():
            key = "AI review findings"
        issue_groups.setdefault(key, []).append((ep, issue))

    for group_name, items in issue_groups.items():
        lines.append(f"## {group_name}")
        lines.append("")

        for ep, issue in items:
            severity_tag = "CRITICAL" if issue.severity == "critical" else "WARNING"
            lines.append(f"- **[{severity_tag}] {ep.show_name} Ep{ep.episode_num:03d}**")
            lines.append(f"  {issue.detail}")

            # Add file path for direct editing
            if issue.file_path:
                lines.append(f"  File: `{issue.file_path}`")
            elif ep.tts_path and ("script" in issue.title.lower() or "artifact" in issue.title.lower()):
                lines.append(f"  File: `{ep.tts_path}`")
            elif ep.digest_path:
                lines.append(f"  File: `{ep.digest_path}`")
            lines.append("")

    # Add context about what these episodes are
    lines.append("## Episodes reviewed")
    lines.append("")
    for ep in episodes:
        n_issues = len([i for i in ep.issues if i.severity != "info"])
        status = f"{n_issues} issue(s)" if n_issues else "OK"
        duration = ep.metrics.get("counters", {}).get("audio_duration_s")
        dur_str = f", {duration:.0f}s audio" if duration else ""
        lines.append(f"- {ep.show_name} Ep{ep.episode_num:03d} ({ep.date}{dur_str}): {status}")

    lines.append("")
    lines.append("For each issue above, investigate the file, determine if the episode "
                 "content is salvageable or needs regeneration, and fix what you can. "
                 "For critical issues, consider whether the episode should be removed "
                 "from the RSS feed entirely.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_review(
    target_date: datetime.date,
    create_issues: bool = False,
    show_filter: str = "",
    output_format: str = "log",
) -> int:
    """Run the full review pipeline. Returns exit code."""
    logger.info("=== Episode Review for %s ===", target_date.isoformat())

    episodes = discover_episodes(target_date, show_filter)
    if not episodes:
        logger.info("No episodes found for %s", target_date.isoformat())
        return 0

    logger.info("Found %d episode(s) to review", len(episodes))

    # Run all automated checks
    for ep in episodes:
        info = SHOW_REGISTRY.get(ep.show_slug, {})
        logger.info("Reviewing %s Ep%03d ...", ep.show_name, ep.episode_num)

        check_digest_length(ep, info)
        check_tts_script(ep, info)
        check_audio_duration(ep, info)
        check_pipeline_errors(ep)
        check_leaked_artifacts(ep)
        check_required_sections(ep, info)
        check_repetition(ep)

    # Cross-episode checks
    check_cross_episode_duplicates(episodes)

    # Optional AI review
    if os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY"):
        for ep in episodes:
            ai_review_episode(ep)
    else:
        logger.info("Skipping AI review (no GROK_API_KEY)")

    # Report
    total_critical = 0
    total_warnings = 0
    for ep in episodes:
        n_crit = sum(1 for i in ep.issues if i.severity == "critical")
        n_warn = sum(1 for i in ep.issues if i.severity == "warning")
        n_info = sum(1 for i in ep.issues if i.severity == "info")
        total_critical += n_crit
        total_warnings += n_warn

        if ep.issues:
            logger.info(
                "%s Ep%03d: %d critical, %d warning(s), %d info",
                ep.show_name, ep.episode_num, n_crit, n_warn, n_info,
            )
            for issue in ep.issues:
                level = {"critical": logging.ERROR, "warning": logging.WARNING, "info": logging.INFO}
                logger.log(level.get(issue.severity, logging.INFO),
                           "  [%s] %s: %s", issue.severity.upper(), issue.title, issue.detail)
        else:
            logger.info("%s Ep%03d: OK", ep.show_name, ep.episode_num)

    # Claude Code output
    if output_format == "claude":
        print("\n" + "=" * 72)
        print("COPY BELOW THIS LINE INTO CLAUDE CODE")
        print("=" * 72 + "\n")
        print(format_for_claude(target_date.isoformat(), episodes))
        print("\n" + "=" * 72)
        print("COPY ABOVE THIS LINE INTO CLAUDE CODE")
        print("=" * 72)

    # Create GitHub issue if requested
    if create_issues:
        has_actionable = any(
            i.severity in ("critical", "warning")
            for ep in episodes for i in ep.issues
        )
        if has_actionable:
            create_github_issue(target_date.isoformat(), episodes)
        else:
            logger.info("No actionable issues — skipping GitHub issue creation")

    # Summary
    logger.info(
        "=== Review complete: %d episode(s), %d critical, %d warning(s) ===",
        len(episodes), total_critical, total_warnings,
    )

    if total_critical > 0:
        return 1
    elif total_warnings > 0:
        return 2
    return 0


def main():
    parser = argparse.ArgumentParser(description="Daily episode quality review")
    parser.add_argument(
        "--date",
        type=lambda s: datetime.date.fromisoformat(s),
        default=datetime.date.today(),
        help="Date to review (YYYY-MM-DD, default: today)",
    )
    parser.add_argument(
        "--create-issues",
        action="store_true",
        help="Create GitHub issues for problems found",
    )
    parser.add_argument(
        "--show",
        default="",
        help="Review only a specific show (slug)",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["log", "claude"],
        default="log",
        help="Output format: 'log' (default) or 'claude' (paste-ready prompt for Claude Code)",
    )
    args = parser.parse_args()

    sys.exit(run_review(args.date, args.create_issues, args.show, args.output_format))


if __name__ == "__main__":
    main()
