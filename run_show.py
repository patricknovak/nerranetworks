#!/usr/bin/env python3
"""Unified entry point for all podcast shows.

Usage:
    python run_show.py <show_name> [options]

    show_name: tesla | omni_view | fascinating_frontiers | planetterrian | env_intel | models_agents | models_agents_beginners

Options:
    --test              Fetch RSS + generate digest only (no TTS, X posting, or RSS update)
    --dry-run           Print what would happen; no API calls at all
    --skip-x            Everything except X posting
    --skip-podcast      Everything except TTS/audio/RSS update
    --skip-newsletter   Everything except newsletter sending
"""

from __future__ import annotations

import argparse
import datetime
import importlib
import importlib.util
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Pipeline timeout — guard against hung API calls or infinite loops.
# Default 15 minutes; override with PIPELINE_TIMEOUT_SECONDS env var.
# ---------------------------------------------------------------------------
_PIPELINE_TIMEOUT = int(os.environ.get("PIPELINE_TIMEOUT_SECONDS", 900))


def _timeout_handler(signum, frame):
    raise SystemExit(f"PIPELINE TIMEOUT: exceeded {_PIPELINE_TIMEOUT}s — aborting to prevent hung CI job")


# Only set alarm on platforms that support it (not Windows)
if hasattr(signal, "SIGALRM"):
    signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(_PIPELINE_TIMEOUT)


# ---------------------------------------------------------------------------
# AI disclosure — appended to every episode's spoken script and RSS metadata
# ---------------------------------------------------------------------------
_AI_DISCLOSURE = (
    "This podcast is curated by Patrick but generated using AI voice synthesis "
    "of my voice using ElevenLabs. The primary reason to do this is I "
    "unfortunately don't have the time to be consistent with generating all "
    "the content and wanted to focus on creating consistent and regular "
    "episodes for all the themes that I enjoy and I hope others do as well."
)

_AI_DISCLOSURE_RSS = (
    "AI Disclosure: This podcast is curated by Patrick but uses AI-generated "
    "voice synthesis (ElevenLabs) for audio production."
)

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("run_show")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _discover_shows() -> list[str]:
    """Find all show slugs by scanning shows/*.yaml."""
    shows_dir = PROJECT_ROOT / "shows"
    slugs = []
    for p in sorted(shows_dir.glob("*.yaml")):
        # Skip template files
        if p.stem.endswith("_template"):
            continue
        slugs.append(p.stem)
    return slugs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a podcast show pipeline.")
    available = _discover_shows()
    parser.add_argument(
        "show",
        choices=available,
        help="Show to run (discovered from shows/*.yaml)",
    )
    parser.add_argument("--test", action="store_true",
                        help="Fetch + generate digest only (no TTS/X/RSS)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print plan, make no API calls")
    parser.add_argument("--skip-x", action="store_true",
                        help="Skip X/Twitter posting")
    parser.add_argument("--skip-podcast", action="store_true",
                        help="Skip TTS, audio mixing, and RSS update")
    parser.add_argument("--skip-newsletter", action="store_true",
                        help="Skip newsletter sending")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Hook loader
# ---------------------------------------------------------------------------

def _load_hook(show_slug: str):
    """Try to import ``shows.hooks.<slug>`` and return the module, or None."""
    hook_path = PROJECT_ROOT / "shows" / "hooks" / f"{show_slug}.py"
    if not hook_path.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            f"shows.hooks.{show_slug}", hook_path,
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception as exc:
        logger.warning("Failed to load hook for %s: %s", show_slug, exc)
        return None


# ---------------------------------------------------------------------------
# Pronunciation loader
# ---------------------------------------------------------------------------

def _apply_pronunciation(text: str, show_slug: str) -> str:
    """Apply comprehensive pronunciation fixes for TTS readiness.

    Always calls ``prepare_text_for_tts()`` as the baseline — this handles
    URL stripping, emoji removal, number-to-words conversion, acronym
    expansion, and 200+ pronunciation rules.  Per-show hooks can supply
    extra overrides via ``pronunciation_overrides()`` returning a dict with
    optional keys: ``skip_acronyms``, ``extra_acronyms``, ``extra_words``.
    """
    from assets.pronunciation import prepare_text_for_tts

    # Collect per-show overrides from hook (if any)
    skip_acronyms: set = set()
    extra_acronyms: dict = {}
    extra_words: dict = {}

    hook = _load_hook(show_slug)
    if hook and hasattr(hook, "pronunciation_overrides"):
        overrides = hook.pronunciation_overrides()
        skip_acronyms = overrides.get("skip_acronyms", set())
        extra_acronyms = overrides.get("extra_acronyms", {})
        extra_words = overrides.get("extra_words", {})

    text = prepare_text_for_tts(
        text,
        skip_acronyms=skip_acronyms or None,
        extra_acronyms=extra_acronyms or None,
        extra_words=extra_words or None,
    )

    return text


# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------

def _preflight_checks(config, *, dry_run: bool = False) -> None:
    """Validate config before any API calls to fail fast on misconfigs.

    In dry-run mode, only checks config structure (not files or env vars).
    """
    if dry_run:
        logger.info("Pre-flight checks skipped (dry-run mode)")
        return

    issues = []

    # Check prompt files exist
    for attr in ("digest_prompt_file", "podcast_prompt_file", "system_prompt_file"):
        path_str = getattr(config.llm, attr, "")
        if path_str and not (PROJECT_ROOT / path_str).exists():
            issues.append(f"Prompt file not found: {path_str}")

    # Check music files exist (skip transition_sting — it's auto-generated at runtime)
    for attr in ("music_file", "background_music_file"):
        path_str = getattr(config.audio, attr, None)
        if path_str and not (PROJECT_ROOT / path_str).exists():
            issues.append(f"Audio file not found: {path_str}")

    # Check voice reference exists (Chatterbox/Fish Audio)
    if config.tts.provider in ("chatterbox", "fish"):
        ref = config.tts.voice_reference or config.tts.fish_voice_reference
        if ref and not (PROJECT_ROOT / ref).exists():
            issues.append(f"Voice reference not found: {ref}")

    # Validate TTS provider name
    valid_providers = {"elevenlabs", "kokoro", "chatterbox", "fish"}
    if config.tts.provider not in valid_providers:
        issues.append(f"Unknown TTS provider: {config.tts.provider!r} (expected one of {valid_providers})")

    # Check critical API key env vars are populated
    if config.tts.provider == "elevenlabs":
        if not os.environ.get("ELEVENLABS_API_KEY"):
            issues.append("ELEVENLABS_API_KEY env var is empty or missing")
    elif config.tts.provider == "fish":
        if not os.environ.get("FISH_AUDIO_API_KEY"):
            issues.append("FISH_AUDIO_API_KEY env var is empty or missing")

    if not os.environ.get("GROK_API_KEY"):
        issues.append("GROK_API_KEY env var is empty or missing")

    # Validate numeric config bounds
    for attr in ("stability", "similarity_boost", "style"):
        val = getattr(config.tts, attr, None)
        if val is not None and not (0.0 <= val <= 1.0):
            issues.append(f"tts.{attr}={val} is out of range [0.0, 1.0]")
    if config.tts.max_chars is not None and config.tts.max_chars <= 0:
        issues.append(f"tts.max_chars={config.tts.max_chars} must be > 0")
    for attr in ("voice_intro_delay", "intro_duration", "overlap_duration",
                 "fade_duration", "outro_duration", "outro_crossfade",
                 "intro_volume", "overlap_volume", "fade_volume", "outro_volume"):
        val = getattr(config.audio, attr, None)
        if val is not None and val < 0:
            issues.append(f"audio.{attr}={val} must be >= 0")

    # Check R2 storage credentials if R2 is configured
    if getattr(config, "storage", None) and config.storage.provider == "r2":
        for env_attr in ("endpoint_env", "access_key_env", "secret_key_env"):
            env_name = getattr(config.storage, env_attr, "")
            if env_name and not os.environ.get(env_name):
                logger.warning("R2 env var %s (%s) is empty — upload may fail", env_name, env_attr)

    if issues:
        for issue in issues:
            logger.error("Pre-flight check FAILED: %s", issue)
        raise SystemExit(f"Pre-flight validation failed with {len(issues)} issue(s)")

    logger.info("Pre-flight checks passed")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    from engine.config import load_config

    # 1. Load config
    config_path = PROJECT_ROOT / "shows" / f"{args.show}.yaml"
    config = load_config(config_path)
    logger.info("=== %s ===", config.name)

    # 1b. Pre-flight validation — catch misconfigs before expensive API calls
    _preflight_checks(config, dry_run=args.dry_run)

    if args.dry_run:
        logger.info("[DRY RUN] Would run full pipeline for '%s'", config.name)
        logger.info("  Sources: %d RSS feeds", len(config.sources))
        logger.info("  LLM: %s (model=%s)", config.llm.provider, config.llm.model)
        logger.info("  TTS: voice=%s, model=%s", config.tts.voice_id, config.tts.model)
        logger.info("  Music: %s", config.audio.music_file or "(none)")
        logger.info("  RSS: %s", config.publishing.rss_file)
        logger.info("  X posting: %s (prefix=%s)",
                     config.publishing.x_enabled, config.publishing.x_env_prefix)
        return

    today = datetime.date.today()
    today_str = today.strftime("%B %d, %Y")
    digests_dir = PROJECT_ROOT / config.episode.output_dir

    # Initialize pipeline metrics
    from engine.metrics import PipelineMetrics
    metrics = PipelineMetrics(show_slug=config.slug, episode_num=0)  # Updated after ep num known

    # 2. Episode number
    from engine.publisher import get_next_episode_number
    rss_path = PROJECT_ROOT / config.publishing.rss_file
    episode_num = get_next_episode_number(
        rss_path, digests_dir, mp3_glob_pattern=config.episode.mp3_glob,
    )
    logger.info("Episode number: %d", episode_num)
    metrics.episode_num = episode_num

    # 2b. Checkpoint: skip if today's MP3 already exists (avoids re-running
    # the full pipeline on retries after partial failures in later steps).
    expected_mp3 = digests_dir / config.episode.filename_pattern.format(
        prefix=config.episode.prefix, num=episode_num, date=today,
    )
    if expected_mp3.exists() and not args.test:
        logger.info(
            "Checkpoint: %s already exists (%d bytes). Skipping pipeline.",
            expected_mp3.name, expected_mp3.stat().st_size,
        )
        return

    # 3. Tracker
    from engine.tracking import create_tracker, save_usage
    tracker = create_tracker(config.name, episode_num)

    # 4 & 5. Pre-fetch hook + RSS fetch in parallel (concurrent.futures)
    hook_module = _load_hook(args.show)
    extra_context: dict = {}

    from engine.content_tracker import ContentTracker, SHOW_SECTION_PATTERNS
    from engine.utils import deduplicate_by_entity

    # Prefer YAML-provided section patterns; fall back to hardcoded registry
    section_patterns = (
        config.content_tracking.section_patterns
        if config.content_tracking.section_patterns
        else SHOW_SECTION_PATTERNS.get(config.slug, {})
    )
    content_tracker = ContentTracker(config.slug, digests_dir)
    content_tracker.load()

    feed_dicts = [{"url": s.url, "label": s.label} for s in config.sources]

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _run_hook():
        if hook_module and hasattr(hook_module, "pre_fetch"):
            logger.info("Running pre-fetch hook for %s ...", args.show)
            return hook_module.pre_fetch(
                config, episode_num=episode_num, today_str=today_str,
            ) or {}
        return {}

    def _run_fetch():
        min_articles = getattr(config, "min_articles", None) or 3
        return _fetch_with_expansion(
            feed_dicts, config.keywords, content_tracker, min_articles,
        )

    def _run_x_fetch():
        if not config.x_accounts:
            return []
        from engine.fetcher import fetch_x_posts
        return fetch_x_posts(config.x_accounts, keywords=config.keywords)

    articles = []
    x_posts = []
    with metrics.stage("fetch_and_dedup"):
        with ThreadPoolExecutor(max_workers=3) as executor:
            hook_future = executor.submit(_run_hook)
            fetch_future = executor.submit(_run_fetch)
            x_fetch_future = executor.submit(_run_x_fetch)

            try:
                extra_context = hook_future.result(timeout=60)
            except Exception as exc:
                logger.warning(
                    "Pre-fetch hook failed for %s: %s — continuing without hook data",
                    args.show, exc,
                )
                extra_context = {}

            try:
                articles = fetch_future.result(timeout=120)
            except Exception as exc:
                logger.error("RSS fetch failed: %s", exc)
                articles = []

            try:
                x_posts = x_fetch_future.result(timeout=120)
            except Exception as exc:
                logger.warning("X account fetch failed: %s — continuing with RSS only", exc)
                x_posts = []

    # Merge X posts into articles
    if x_posts:
        logger.info("Merging %d X posts from %d account(s) into %d RSS articles",
                     len(x_posts), len(config.x_accounts), len(articles))
        articles.extend(x_posts)
    logger.info("After fetch + dedup: %d articles (incl. %d X posts)", len(articles), len(x_posts))
    metrics.record("article_count", len(articles))

    if not articles:
        logger.warning("No articles found even after expanded search. Skipping episode.")
        sys.exit(2)

    # Skip episode if digest would be too thin — or activate slow news mode
    skip_threshold = getattr(config, "min_articles_skip", 3) or 3
    slow_news_mode = False
    selected_segs: list = []

    if len(articles) < skip_threshold:
        from engine.slow_news import is_slow_news_day, load_segment_library, select_segments

        if is_slow_news_day(len(articles), config):
            logger.info(
                "Slow news day: %d article(s) below threshold %d — activating evergreen segments",
                len(articles), skip_threshold,
            )
            library = load_segment_library(config.slow_news.library_file)
            recent_seg_ids = content_tracker.get_recent_segment_ids(
                days=config.slow_news.cooldown_days,
            )
            selected_segs = select_segments(
                library,
                recent_seg_ids,
                max_segments=config.slow_news.max_segments,
                mode=config.slow_news.selection_mode,
            )
            slow_news_mode = True
            metrics.record("slow_news_mode", True)
        else:
            logger.warning(
                "Only %d article(s) found — below minimum threshold (%d) for a quality episode. Skipping.",
                len(articles), skip_threshold,
            )
            sys.exit(2)

    # 5c. Cap article count to prevent prompt bloat and quality degradation
    MAX_ARTICLES_FOR_LLM = 25
    if len(articles) > MAX_ARTICLES_FOR_LLM:
        logger.info(
            "Capping articles from %d to %d to prevent prompt bloat",
            len(articles), MAX_ARTICLES_FOR_LLM,
        )
        articles = articles[:MAX_ARTICLES_FOR_LLM]

    # 6. Build template vars for digest prompt
    news_lines = []
    for i, art in enumerate(articles, 1):
        title = art.get("title", "Untitled")
        desc = art.get("description", "")
        url = art.get("url", "")
        source = art.get("source_name", "Unknown")
        pub = art.get("published_date", "")
        news_lines.append(
            f"{i}. **{title}** — {source}"
            + (f" ({pub})" if pub else "")
            + f"\n   {desc}\n   URL: {url}"
        )
    news_section = "\n\n".join(news_lines)

    # Get content tracker summary for the LLM to avoid cross-episode repetition
    content_tracker_summary = content_tracker.get_summary_for_prompt()
    if content_tracker_summary:
        logger.info("Injecting content tracker summary into LLM prompt (%d chars)", len(content_tracker_summary))

    # Get recent deep dive topics for freshness enforcement
    recent_deep_dives = content_tracker.get_recent_deep_dive_topics(max_items=14)
    if recent_deep_dives:
        deep_dive_topics_text = "\n".join(f"- {t}" for t in recent_deep_dives)
        logger.info("Injecting %d recent deep dive topics into prompt", len(recent_deep_dives))
    else:
        deep_dive_topics_text = "(No previous deep dives — you have full freedom to choose any topic.)"

    template_vars = {
        "today_str": today_str,
        "date_human": today_str,  # alias used by Omni View prompts
        "news_section": news_section,
        "sections_json": news_section,  # alias used by Omni View digest prompt
        "episode_num": episode_num,
        "recent_content_summary": content_tracker_summary,
        "recent_deep_dive_topics": deep_dive_topics_text,
    }
    # Slow news day context injection
    if slow_news_mode and selected_segs:
        from engine.slow_news import build_slow_news_prompt_context

        # Gather previous angle summaries for freshness enforcement
        previous_angles: dict = {}
        for seg in selected_segs:
            history = content_tracker.get_segment_history(seg["id"], limit=3)
            angles = [h["summary"] for h in history if h.get("summary")]
            if angles:
                previous_angles[seg["id"]] = angles

        template_vars["slow_news_context"] = build_slow_news_prompt_context(
            articles, selected_segs, config, template_vars, previous_angles,
        )
    else:
        template_vars["slow_news_context"] = ""

    # Merge extra context from hooks (e.g. price, change_str, x_posts_section)
    template_vars.update(extra_context)

    # 7. Generate digest
    from engine.generator import generate_digest, LLMRefusalError
    logger.info("Generating digest ...")
    try:
        with metrics.stage("generate_digest"):
            x_thread = generate_digest(template_vars, config, tracker=tracker)
    except LLMRefusalError as e:
        logger.error("PIPELINE ABORTED: %s", e)
        logger.error(
            "The LLM refused to generate content. This typically means the news "
            "sources had insufficient relevant content. Check source feeds and "
            "consider re-running later."
        )
        save_usage(tracker, digests_dir)
        sys.exit(1)

    # Record episode content in the cross-episode tracker
    if section_patterns:
        _article_urls = [a.get("url", "") for a in articles if a.get("url")]
        _article_titles = [a.get("title", "") for a in articles if a.get("title")]
        content_tracker.record_episode(
            x_thread, section_patterns,
            source_urls=_article_urls,
            source_titles=_article_titles,
        )
        content_tracker.save()

    # Record slow-news segment metadata for cooldown tracking & freshness
    if slow_news_mode and selected_segs:
        import datetime as _dt
        today_iso = _dt.date.today().isoformat()
        for ep in content_tracker.data.get("episodes", []):
            if ep.get("date") == today_iso:
                ep["slow_news"] = True
                ep["slow_news_segments"] = [s["id"] for s in selected_segs]
                ep["slow_news_segment_summaries"] = _extract_segment_summaries(
                    x_thread, selected_segs,
                )
                break
        content_tracker.save()
        logger.info(
            "Recorded slow-news segments: %s",
            [s["id"] for s in selected_segs],
        )

    # 7b. Post-generation digest validation — catch structure issues before TTS.
    #      If critical sections are missing, retry digest generation once with an
    #      explicit instruction to include them.
    from engine.validation import validate_digest as _validate_digest, SHOW_VALIDATION_CONFIGS
    _val_factory = SHOW_VALIDATION_CONFIGS.get(config.slug)
    if _val_factory:
        _val_config = _val_factory()
        _recent = content_tracker.get_recent_headlines(days=7)
        _val_passed, _val_issues = _validate_digest(
            x_thread, _val_config,
            section_patterns=section_patterns,
            recent_headlines=_recent,
        )
        if not _val_passed:
            # Check for critical missing sections (non-optional)
            _missing = [
                i for i in _val_issues
                if "missing from digest" in i.lower()
            ]
            if _missing:
                logger.warning(
                    "Digest missing %d critical section(s): %s — retrying once ...",
                    len(_missing), "; ".join(_missing),
                )
                _section_names = [
                    m.split("'")[1] for m in _missing if "'" in m
                ]
                _section_list = ", ".join(_section_names)
                _retry_suffix = (
                    f"\n\nCRITICAL: Your previous attempt was rejected because "
                    f"it was missing these required sections: {_section_list}. "
                    f"You MUST include ALL sections from the formatting template "
                    f"above. If source material is limited, use the available "
                    f"articles to write those sections with extra depth rather "
                    f"than omitting them. Do NOT skip any section."
                )
                try:
                    with metrics.stage("generate_digest_retry"):
                        x_thread_retry = generate_digest(
                            template_vars, config, tracker=tracker,
                            prompt_suffix=_retry_suffix,
                        )
                    # Re-validate
                    _val2_passed, _val2_issues = _validate_digest(
                        x_thread_retry, _val_config,
                        section_patterns=section_patterns,
                        recent_headlines=_recent,
                    )
                    _missing2 = [
                        i for i in _val2_issues
                        if "missing from digest" in i.lower()
                    ]
                    if len(_missing2) < len(_missing):
                        logger.info(
                            "Digest retry improved: %d → %d missing sections",
                            len(_missing), len(_missing2),
                        )
                        x_thread = x_thread_retry
                    elif len(x_thread_retry) > len(x_thread):
                        # Same missing sections but retry is longer — prefer
                        # the longer output (less likely to be garbage).
                        logger.info(
                            "Digest retry same sections but longer (%d → %d chars) — using retry",
                            len(x_thread), len(x_thread_retry),
                        )
                        x_thread = x_thread_retry
                    else:
                        logger.warning("Digest retry did not improve — keeping original")
                except LLMRefusalError:
                    # LLM refusal is a permanent failure — don't mask it
                    logger.error("Digest retry refused by LLM — aborting episode")
                    raise
                except Exception as exc:
                    logger.warning("Digest retry failed: %s — keeping original", exc)
            else:
                # Check for item-count shortfalls (e.g. "Top News has 3 items, minimum is 5").
                # These can be genuine content gaps OR formatting mismatches (the LLM
                # wrote the content but didn't use bold markers for items).  If the
                # digest is long enough to be real content, treat as a warning rather
                # than killing the episode.
                _item_count_issues = [
                    i for i in _val_issues
                    if "has only" in i.lower() or "below minimum" in i.lower()
                       or ("item" in i.lower() and "minimum" in i.lower())
                ]
                if _item_count_issues:
                    _digest_char_count = len(x_thread.strip())
                    if _digest_char_count < 1500:
                        # Genuinely thin digest — not enough content
                        logger.error(
                            "Digest has %d item-count shortfall(s) and is short "
                            "(%d chars) — episode too thin to publish: %s",
                            len(_item_count_issues), _digest_char_count,
                            "; ".join(_item_count_issues),
                        )
                        sys.exit(2)
                    else:
                        # Long enough to be real content — likely a formatting
                        # mismatch rather than missing content.
                        logger.warning(
                            "Digest has %d item-count shortfall(s) but is %d chars "
                            "(likely formatting mismatch, not missing content): %s",
                            len(_item_count_issues), _digest_char_count,
                            "; ".join(_item_count_issues),
                        )

                # Check for excessive cross-episode repeats — a few follow-ups
                # are normal, but 3+ identical headlines means the LLM ignored
                # the content tracker.
                _repeat_issues = [
                    i for i in _val_issues
                    if "cross-episode repeat" in i.lower()
                ]
                metrics.record("cross_episode_repeats", len(_repeat_issues))
                if len(_repeat_issues) >= 3:
                    # If slow news mode is available, fall back to it instead
                    # of skipping entirely — the repeat articles are stale but
                    # evergreen segments can fill the episode.
                    if not slow_news_mode and config.slow_news.enabled:
                        from engine.slow_news import (
                            load_segment_library, select_segments,
                            build_slow_news_prompt_context,
                        )
                        logger.warning(
                            "Digest has %d cross-episode repeat(s) — falling back "
                            "to slow news mode with evergreen segments",
                            len(_repeat_issues),
                        )
                        library = load_segment_library(config.slow_news.library_file)
                        recent_seg_ids = content_tracker.get_recent_segment_ids(
                            days=config.slow_news.cooldown_days,
                        )
                        selected_segs = select_segments(
                            library,
                            recent_seg_ids,
                            max_segments=config.slow_news.max_segments,
                            mode=config.slow_news.selection_mode,
                        )
                        slow_news_mode = True
                        metrics.record("slow_news_mode", True)
                        metrics.record("slow_news_trigger", "stale_repeats")

                        # Gather previous angle summaries for freshness
                        previous_angles: dict = {}
                        for seg in selected_segs:
                            history = content_tracker.get_segment_history(seg["id"], limit=3)
                            angles = [h["summary"] for h in history if h.get("summary")]
                            if angles:
                                previous_angles[seg["id"]] = angles

                        template_vars["slow_news_context"] = build_slow_news_prompt_context(
                            articles, selected_segs, config, template_vars, previous_angles,
                        )

                        # Re-generate digest with slow news context
                        logger.info("Re-generating digest with slow news context ...")
                        try:
                            with metrics.stage("generate_digest_slow_news"):
                                x_thread = generate_digest(
                                    template_vars, config, tracker=tracker,
                                )
                        except LLMRefusalError as e:
                            logger.error("Slow news fallback digest refused: %s", e)
                            sys.exit(2)
                        except Exception as e:
                            logger.error("Slow news fallback digest failed: %s", e)
                            sys.exit(1)

                        # Extract hook from the regenerated digest
                        hook = _extract_hook(x_thread)
                        if hook:
                            hook = f"[Slow News Edition] {hook}"
                        else:
                            hook = "[Slow News Edition]"
                        logger.info("Slow news fallback hook: %s", hook)

                        # Re-record episode content
                        if section_patterns:
                            _article_urls = [a.get("url", "") for a in articles if a.get("url")]
                            _article_titles = [a.get("title", "") for a in articles if a.get("title")]
                            content_tracker.record_episode(
                                x_thread, section_patterns,
                                source_urls=_article_urls,
                                source_titles=_article_titles,
                            )
                            content_tracker.save()
                    else:
                        logger.error(
                            "Digest has %d cross-episode repeat(s) — too many recycled "
                            "stories to publish.",
                            len(_repeat_issues),
                        )
                        sys.exit(2)

                logger.warning(
                    "Digest validation found %d issue(s) — continuing (non-blocking)",
                    len(_val_issues),
                )
    else:
        logger.debug("No validation config for show '%s' — skipping digest validation", config.slug)

    # 7c. Minimum digest length gate — catch LLM garbage (e.g. 319-char responses)
    #     before the pipeline spends TTS credits and publishes a bad episode.
    #     A normal digest is 3000-10000+ chars.  Below 800 chars the LLM clearly
    #     failed to produce a usable episode.
    _MIN_DIGEST_CHARS = 800
    _digest_len = len(x_thread.strip())
    if _digest_len < _MIN_DIGEST_CHARS:
        # Try slow news fallback — the LLM may do better with structured
        # evergreen prompts than with the regular digest template.
        if not slow_news_mode and config.slow_news.enabled:
            logger.warning(
                "Digest is too short (%d chars, minimum %d) — attempting slow "
                "news fallback with evergreen segments ...",
                _digest_len, _MIN_DIGEST_CHARS,
            )
            from engine.slow_news import (
                load_segment_library, select_segments,
                build_slow_news_prompt_context,
            )
            try:
                library = load_segment_library(config.slow_news.library_file)
                recent_seg_ids = content_tracker.get_recent_segment_ids(
                    days=config.slow_news.cooldown_days,
                )
                selected_segs = select_segments(
                    library, recent_seg_ids,
                    max_segments=config.slow_news.max_segments,
                    mode=config.slow_news.selection_mode,
                )
                previous_angles: dict = {}
                for seg in selected_segs:
                    previous_angles[seg["id"]] = content_tracker.get_segment_history(
                        seg["id"], limit=3,
                    )
                slow_ctx = build_slow_news_prompt_context(
                    articles, selected_segs, config, template_vars, previous_angles,
                )
                template_vars["slow_news_context"] = slow_ctx
                slow_news_mode = True

                with metrics.stage("generate_digest_llm_fallback"):
                    x_thread = generate_digest(template_vars, config, tracker=tracker)

                _digest_len = len(x_thread.strip())
                if _digest_len >= _MIN_DIGEST_CHARS:
                    logger.info(
                        "Slow news fallback produced usable digest (%d chars)",
                        _digest_len,
                    )
                else:
                    logger.error(
                        "Slow news fallback still too short (%d chars) — aborting",
                        _digest_len,
                    )
                    save_usage(tracker, digests_dir)
                    sys.exit(1)
            except Exception as exc:
                logger.error(
                    "Slow news fallback failed: %s — aborting", exc,
                )
                save_usage(tracker, digests_dir)
                sys.exit(1)
        else:
            logger.error(
                "Digest is too short (%d chars, minimum %d) — LLM returned "
                "garbage. Aborting episode.",
                _digest_len, _MIN_DIGEST_CHARS,
            )
            save_usage(tracker, digests_dir)
            sys.exit(1)

    # Extract the daily hook (headline) from the digest
    hook = _extract_hook(x_thread)
    if hook:
        logger.info("Hook: %s", hook)
    else:
        logger.warning("No HOOK found in digest — using generic episode title")

    # Tag slow news editions in the episode title
    if slow_news_mode:
        hook = f"[Slow News Edition] {hook}" if hook else "[Slow News Edition]"
        logger.info("Episode tagged as Slow News Edition")

    # Save digest to file
    digest_md = digests_dir / f"{config.episode.prefix}_Ep{episode_num:03d}_{today:%Y%m%d}.md"
    digest_md.write_text(x_thread, encoding="utf-8")
    logger.info("Digest saved: %s", digest_md)

    # Post-generation hook (e.g. extract trade picks for Modern Investing tracker)
    if hook_module and hasattr(hook_module, "post_generate"):
        try:
            hook_module.post_generate(config, digest_text=x_thread, episode_num=episode_num)
        except Exception as exc:
            logger.warning("Post-generate hook failed for %s: %s", args.show, exc)

    # Write episode to Content Lake (non-fatal — must never block pipeline)
    _lake_record = None
    try:
        from engine.content_lake import store_episode, EpisodeRecord, extract_entities_and_topics

        _et = extract_entities_and_topics(x_thread, args.show)
        _lang = "ru" if args.show in ("finansy_prosto", "privet_russian") else "en"
        _headlines = [a.get("title", "") for a in articles if a.get("title")]
        _source_urls = [a.get("url", "") for a in articles if a.get("url")]
        _lake_record = EpisodeRecord(
            show_slug=args.show,
            episode_num=episode_num,
            date=today.isoformat(),
            title=hook or f"Episode {episode_num}",
            hook=hook or "",
            digest_md=x_thread,
            podcast_script="",  # Updated after script generation
            summary=x_thread[:500] if x_thread else "",
            headlines=_headlines,
            source_urls=_source_urls,
            entities=_et["entities"],
            topics=_et["topics"],
            word_count=len(x_thread.split()) if x_thread else 0,
            show_name=config.name,
            language=_lang,
        )
        store_episode(_lake_record)
    except Exception as exc:
        logger.warning("Content lake write failed (non-fatal): %s", exc)

    if args.test:
        logger.info("[TEST MODE] Digest generated successfully. Stopping here.")
        print("\n" + "=" * 60)
        if hook:
            print(f"HOOK: {hook}")
            print("-" * 60)
        print(x_thread[:2000])
        if len(x_thread) > 2000:
            print(f"\n... ({len(x_thread)} chars total, truncated)")
        print("=" * 60)
        save_usage(tracker, digests_dir)
        return

    # 8. Generate podcast script (if not skipped)
    final_mp3 = None
    audio_duration = 0.0

    if not args.skip_podcast:
        from engine.generator import generate_podcast_script

        # Strip URLs, emojis, unicode decorations, and other metadata from
        # the digest before feeding it to the podcast script prompt.  The LLM
        # sometimes echoes these through to the script, and TTS reads them
        # aloud.  This is defense-in-depth alongside the prompt instructions.
        clean_digest = _clean_digest_for_podcast(x_thread)

        effective_hook = hook or f"Here's what's making news in the {config.name} world today."

        pod_vars = {
            "episode_num": episode_num,
            "today_str": today_str,
            "date_human": today_str,  # alias used by Omni View prompts
            "digest": clean_digest,
            "hook": effective_hook,
        }
        # Merge extra context for podcast prompt (e.g. tone_hint, intro_line)
        pod_vars.update(extra_context)

        # Provide default intro_line/closing_block if hook didn't supply them.
        # Uses engine.intros for day-varying, show-specific intros so
        # listeners don't hear the exact same opening every day.
        # Episode 1 gets a special intro — the podcast prompt templates handle
        # the detailed first-episode introduction based on {episode_num}.
        from engine.intros import build_intro_line, build_closing_block, get_show_host
        host = getattr(config.publishing, "host_name", None) or get_show_host(args.show)
        if episode_num == 1:
            pod_vars.setdefault(
                "intro_line",
                f"{host}: Welcome to the very first episode of {config.name}! "
                f"Today is {today_str}. {effective_hook}",
            )
            pod_vars.setdefault(
                "closing_block",
                f"{host}: That wraps up our very first episode of {config.name}! "
                f"If you enjoyed this, please subscribe on Apple Podcasts, Spotify, "
                f"or wherever you listen — and a rating or review really helps new "
                f"listeners find us. "
                f"I'm {host} in Vancouver. Thanks for joining me on this journey, "
                f"and I'll see you tomorrow for episode two.",
            )
        else:
            pod_vars.setdefault(
                "intro_line",
                build_intro_line(
                    args.show,
                    episode_num=episode_num,
                    today_str=today_str,
                    date=today,
                    extra_context=extra_context,
                ),
            )
            pod_vars.setdefault(
                "closing_block",
                build_closing_block(
                    args.show,
                    episode_num=episode_num,
                    today_str=today_str,
                    date=today,
                    extra_context=extra_context,
                ),
            )
        pod_vars.setdefault("tone_hint", "natural and conversational")

        t0 = time.monotonic()
        logger.info("Generating podcast script ...")
        try:
            podcast_script = generate_podcast_script(pod_vars, config, tracker=tracker)
        except LLMRefusalError as e:
            logger.error("PIPELINE ABORTED at podcast script stage: %s", e)
            save_usage(tracker, digests_dir)
            sys.exit(1)
        logger.info("Podcast script generation took %.1fs", time.monotonic() - t0)

        # 8b. Minimum podcast script length gate — catch LLM garbage before
        #     spending TTS credits on a worthless episode.
        _MIN_SCRIPT_WORDS = 100
        _script_word_count = len(podcast_script.split())
        if _script_word_count < _MIN_SCRIPT_WORDS:
            logger.error(
                "Podcast script is too short (%d words, minimum %d) — LLM "
                "likely returned garbage. Aborting episode.",
                _script_word_count, _MIN_SCRIPT_WORDS,
            )
            save_usage(tracker, digests_dir)
            sys.exit(1)

        # 8c. Pre-TTS duration estimate — skip obviously doomed episodes before
        #     burning TTS credits.  ~150 words/minute for podcast speech.
        #     Use a 70% margin to avoid false positives (the audio gate at
        #     step 10 remains the final authority).
        _min_audio = config.min_audio_duration
        if _min_audio:
            _estimated_duration = _script_word_count / 150.0 * 60.0
            if _estimated_duration < _min_audio * 0.7:
                logger.error(
                    "Script too short for minimum duration: ~%.0fs estimated "
                    "vs %ds minimum (%d words at ~150 wpm). Aborting before TTS.",
                    _estimated_duration, _min_audio, _script_word_count,
                )
                save_usage(tracker, digests_dir)
                sys.exit(1)

        # Update Content Lake with podcast script (non-fatal)
        if _lake_record is not None:
            try:
                from engine.content_lake import store_episode as _store_ep
                _lake_record.podcast_script = podcast_script
                _store_ep(_lake_record)
            except Exception as exc:
                logger.warning("Content lake script update failed (non-fatal): %s", exc)

        # Clean podcast script: strip speaker prefixes and stage directions
        podcast_script = _clean_podcast_script(podcast_script, host_name=host)

        # Apply pronunciation fixes
        podcast_script = _apply_pronunciation(podcast_script, args.show)

        # Post-pronunciation cleanup: strip metadata that survived in word form
        # (e.g. "(Word count: two thousand four hundred seventy-eight)" after
        # number-to-words conversion made it invisible to earlier regex passes)
        podcast_script = _strip_post_pronunciation_artifacts(podcast_script)

        # Append AI disclosure at the end of the episode
        podcast_script = podcast_script.rstrip() + "\n\n" + _AI_DISCLOSURE

        # Parse chapter markers from the cleaned script (before TTS)
        from engine.chapters import parse_chapters
        episode_chapters = parse_chapters(
            podcast_script,
            config.chapters.section_markers,
            show_name=config.name,
        ) if config.chapters.enabled and config.chapters.section_markers else []

        # Final defense-in-depth: strip any speaker prefixes that survived
        # all prior cleaning passes.  This catches edge cases where the LLM
        # output format, retry expansion, or paragraph breaking unexpectedly
        # places a prefix at a line/sentence start.
        import re as _re
        for _pfx in ("Host:", f"{host}:", "Patrick:", "Ведущая:", "Ведущий:", "Narrator:", "Speaker:"):
            _esc = _re.escape(_pfx)
            podcast_script = _re.sub(r"^" + _esc + r"\s*", "", podcast_script, flags=_re.MULTILINE)
            podcast_script = _re.sub(r"(?<=[.!?])\s+" + _esc + r"\s*", " ", podcast_script)
        podcast_script = _re.sub(r"\n{3,}", "\n\n", podcast_script).strip()

        # Save TTS-ready script for debugging pronunciation/intro issues
        tts_script_path = digests_dir / f"{config.episode.prefix}_Ep{episode_num:03d}_{today:%Y%m%d}_tts.txt"
        tts_script_path.write_text(podcast_script, encoding="utf-8")
        logger.info("TTS script saved: %s", tts_script_path)

        # 9. TTS — route based on provider (elevenlabs, kokoro, chatterbox, or fish)
        tts_provider = getattr(config.tts, "provider", "elevenlabs")

        tts_ready = False
        if tts_provider == "chatterbox":
            try:
                from engine.tts import synthesize_chatterbox, synthesize_chatterbox_sections
                # Resolve voice reference path relative to project root
                voice_ref = ""
                if config.tts.voice_reference:
                    voice_ref = str(PROJECT_ROOT / config.tts.voice_reference)
                tts_ready = True
                logger.info(
                    "TTS provider: Chatterbox (device=%s, voice_ref=%s, exag=%.2f, cfg=%.2f)",
                    config.tts.chatterbox_device,
                    config.tts.voice_reference or "(default voice)",
                    config.tts.chatterbox_exaggeration,
                    config.tts.chatterbox_cfg_weight,
                )
            except Exception as e:
                logger.error("Chatterbox TTS unavailable: %s. Skipping TTS.", e)
        elif tts_provider == "kokoro":
            try:
                from engine.tts import synthesize_kokoro, synthesize_kokoro_sections
                tts_ready = True
                logger.info("TTS provider: Kokoro (voice=%s, speed=%.2f)",
                            config.tts.kokoro_voice, config.tts.kokoro_speed)
            except Exception as e:
                logger.error("Kokoro TTS unavailable: %s. Skipping TTS.", e)
        elif tts_provider == "fish":
            try:
                from engine.tts import synthesize_fish, synthesize_fish_sections
                fish_api_key = (os.getenv("FISH_AUDIO_API_KEY") or "").strip()
                if not fish_api_key:
                    logger.error("FISH_AUDIO_API_KEY not set. Skipping TTS.")
                else:
                    fish_voice_ref = ""
                    if config.tts.fish_voice_reference:
                        fish_voice_ref = str(PROJECT_ROOT / config.tts.fish_voice_reference)
                    tts_ready = True
                    logger.info(
                        "TTS provider: Fish Audio (ref_id=%s, voice_ref=%s, temp=%.2f, speed=%.1f)",
                        config.tts.fish_reference_id or "(none)",
                        config.tts.fish_voice_reference or "(none)",
                        config.tts.fish_temperature,
                        config.tts.fish_speed,
                    )
            except Exception as e:
                logger.error("Fish Audio TTS unavailable: %s. Skipping TTS.", e)
        else:
            api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
            if not api_key:
                logger.error("ELEVENLABS_API_KEY not set. Skipping TTS.")
            else:
                from engine.tts import synthesize, validate_elevenlabs_auth
                validate_elevenlabs_auth(api_key)
                tts_ready = True

        if tts_ready:
            raw_mp3 = digests_dir / f"{config.episode.prefix}_Ep{episode_num:03d}_{today:%Y%m%d}_raw.mp3"
            logger.info("Synthesizing audio ...")
            t0 = time.monotonic()

            # Section-aware TTS: split at chapter boundaries and
            # concatenate with transition stings between sections.
            sting_path = None
            if config.audio.transition_sting:
                sting_path = PROJECT_ROOT / config.audio.transition_sting

            use_section_tts = (
                episode_chapters
                and len(episode_chapters) >= 2
                and sting_path
            )

            if use_section_tts:
                from engine.chapters import split_script_at_chapters
                from engine.audio import generate_transition_sting, concatenate_with_stings

                sections = split_script_at_chapters(podcast_script, episode_chapters)
                sections = [s for s in sections if s.strip()]

                # Safety: if sections capture < 80% of the script, something
                # went wrong with splitting — fall back to single synthesis.
                sections_total = sum(len(s) for s in sections)
                if sections_total < len(podcast_script) * 0.8:
                    logger.warning(
                        "Section TTS: sections only contain %d/%d chars (%.0f%%) — "
                        "falling back to single synthesis to avoid truncation",
                        sections_total, len(podcast_script),
                        100 * sections_total / len(podcast_script) if podcast_script else 0,
                    )
                    metrics.record("section_tts_fallback", True)
                    metrics.record("section_tts_coverage_pct", round(
                        100 * sections_total / len(podcast_script), 1,
                    ) if podcast_script else 0)
                    sections = []  # Force fallback to single synthesis below

                if len(sections) >= 2:
                    logger.info("Section TTS: synthesizing %d sections separately", len(sections))
                    metrics.record("section_tts_fallback", False)
                    metrics.record("section_tts_section_count", len(sections))
                    section_tmp_dir = digests_dir / f"_sections_ep{episode_num:03d}"

                    if tts_provider == "chatterbox":
                        section_files = synthesize_chatterbox_sections(
                            sections,
                            section_tmp_dir,
                            voice_reference=voice_ref,
                            exaggeration=config.tts.chatterbox_exaggeration,
                            cfg_weight=config.tts.chatterbox_cfg_weight,
                            device=config.tts.chatterbox_device,
                            section_prefix=f"sec_ep{episode_num:03d}",
                            max_chars=config.tts.max_chars,
                        )
                    elif tts_provider == "kokoro":
                        section_files = synthesize_kokoro_sections(
                            sections,
                            section_tmp_dir,
                            voice=config.tts.kokoro_voice,
                            speed=config.tts.kokoro_speed,
                            lang=config.tts.kokoro_lang,
                            section_prefix=f"sec_ep{episode_num:03d}",
                            max_chars=config.tts.max_chars,
                        )
                    elif tts_provider == "fish":
                        section_files = synthesize_fish_sections(
                            sections,
                            section_tmp_dir,
                            api_key=fish_api_key,
                            reference_id=config.tts.fish_reference_id,
                            voice_reference=fish_voice_ref,
                            section_prefix=f"sec_ep{episode_num:03d}",
                            max_chars=config.tts.max_chars,
                            temperature=config.tts.fish_temperature,
                            top_p=config.tts.fish_top_p,
                            speed=config.tts.fish_speed,
                            repetition_penalty=config.tts.fish_repetition_penalty,
                            format=config.tts.fish_format,
                            mp3_bitrate=config.tts.fish_mp3_bitrate,
                        )
                    else:
                        from engine.tts import synthesize_sections
                        section_files = synthesize_sections(
                            sections,
                            config.tts.voice_id,
                            section_tmp_dir,
                            api_key=api_key,
                            section_prefix=f"sec_ep{episode_num:03d}",
                            max_chars=config.tts.max_chars,
                            model_id=config.tts.model,
                            stability=config.tts.stability,
                            similarity_boost=config.tts.similarity_boost,
                            style=config.tts.style,
                        )

                    generate_transition_sting(sting_path)
                    concatenate_with_stings(
                        section_files, raw_mp3, sting_path=sting_path,
                    )

                    for sf in section_files:
                        try:
                            sf.unlink()
                        except Exception:
                            pass
                    try:
                        section_tmp_dir.rmdir()
                    except Exception:
                        pass
                else:
                    # Not enough sections — fall back to single synthesis
                    if tts_provider == "chatterbox":
                        synthesize_chatterbox(
                            podcast_script, raw_mp3,
                            voice_reference=voice_ref,
                            exaggeration=config.tts.chatterbox_exaggeration,
                            cfg_weight=config.tts.chatterbox_cfg_weight,
                            device=config.tts.chatterbox_device,
                            max_chars=config.tts.max_chars,
                        )
                    elif tts_provider == "kokoro":
                        synthesize_kokoro(
                            podcast_script, raw_mp3,
                            voice=config.tts.kokoro_voice,
                            speed=config.tts.kokoro_speed,
                            lang=config.tts.kokoro_lang,
                            max_chars=config.tts.max_chars,
                        )
                    elif tts_provider == "fish":
                        synthesize_fish(
                            podcast_script, raw_mp3,
                            api_key=fish_api_key,
                            reference_id=config.tts.fish_reference_id,
                            voice_reference=fish_voice_ref,
                            max_chars=config.tts.max_chars,
                            temperature=config.tts.fish_temperature,
                            top_p=config.tts.fish_top_p,
                            speed=config.tts.fish_speed,
                            repetition_penalty=config.tts.fish_repetition_penalty,
                            format=config.tts.fish_format,
                            mp3_bitrate=config.tts.fish_mp3_bitrate,
                        )
                    else:
                        synthesize(
                            podcast_script, config.tts.voice_id, raw_mp3,
                            api_key=api_key, max_chars=config.tts.max_chars,
                            model_id=config.tts.model, stability=config.tts.stability,
                            similarity_boost=config.tts.similarity_boost,
                            style=config.tts.style,
                        )
            else:
                if tts_provider == "chatterbox":
                    synthesize_chatterbox(
                        podcast_script, raw_mp3,
                        voice_reference=voice_ref,
                        exaggeration=config.tts.chatterbox_exaggeration,
                        cfg_weight=config.tts.chatterbox_cfg_weight,
                        device=config.tts.chatterbox_device,
                        max_chars=config.tts.max_chars,
                    )
                elif tts_provider == "kokoro":
                    synthesize_kokoro(
                        podcast_script, raw_mp3,
                        voice=config.tts.kokoro_voice,
                        speed=config.tts.kokoro_speed,
                        lang=config.tts.kokoro_lang,
                        max_chars=config.tts.max_chars,
                    )
                elif tts_provider == "fish":
                    synthesize_fish(
                        podcast_script, raw_mp3,
                        api_key=fish_api_key,
                        reference_id=config.tts.fish_reference_id,
                        voice_reference=fish_voice_ref,
                        max_chars=config.tts.max_chars,
                        temperature=config.tts.fish_temperature,
                        top_p=config.tts.fish_top_p,
                        speed=config.tts.fish_speed,
                        repetition_penalty=config.tts.fish_repetition_penalty,
                        format=config.tts.fish_format,
                        mp3_bitrate=config.tts.fish_mp3_bitrate,
                    )
                else:
                    synthesize(
                        podcast_script, config.tts.voice_id, raw_mp3,
                        api_key=api_key, max_chars=config.tts.max_chars,
                        model_id=config.tts.model, stability=config.tts.stability,
                        similarity_boost=config.tts.similarity_boost,
                        style=config.tts.style,
                    )

            _tts_duration = time.monotonic() - t0
            logger.info("TTS synthesis took %.1fs", _tts_duration)
            metrics.record("tts_duration_s", round(_tts_duration, 2))
            from engine.tracking import record_tts_usage
            record_tts_usage(tracker, len(podcast_script), provider=config.tts.provider)

            # 9a. Post-TTS transcription validation (opt-in)
            if config.tts.validate_transcription:
                import json as _json
                from engine.tts_validation import validate_tts_transcription
                logger.info("Running post-TTS transcription validation...")
                tts_val = validate_tts_transcription(
                    raw_mp3, podcast_script,
                    model_size=config.tts.whisper_model,
                    threshold=config.tts.whisper_threshold,
                )
                if tts_val["passed"]:
                    logger.info("TTS validation PASSED (%.1f%% match)", tts_val["match_score"] * 100)
                else:
                    logger.warning(
                        "TTS validation WARNING: %.1f%% match (threshold %.0f%%)",
                        tts_val["match_score"] * 100,
                        config.tts.whisper_threshold * 100,
                    )
                    for w in tts_val["mismatched_words"][:10]:
                        logger.warning("  Mismatch: expected '%s' → heard '%s'", w["expected"], w["heard"])
                val_path = digests_dir / f"{config.episode.prefix}_Ep{episode_num:03d}_{today:%Y%m%d}_tts_validation.json"
                val_path.write_text(_json.dumps(tts_val, indent=2))
                logger.info("TTS validation report saved: %s", val_path.name)

            # 9b. Generate transcript from raw TTS audio (non-fatal)
            try:
                from engine.transcripts import generate_transcript
                _lang = "ru" if args.show in ("finansy_prosto", "privet_russian") else "en"
                _ep_prefix = f"{config.episode.prefix}_Ep{episode_num:03d}_{today:%Y%m%d}"
                generate_transcript(
                    raw_mp3, digests_dir, _ep_prefix,
                    model_size="base", language=_lang,
                )
            except Exception as exc:
                logger.warning("Transcript generation failed (non-fatal): %s", exc)

            # 10. Audio mixing
            from engine.audio import get_audio_duration, mix_with_music, normalize_voice

            final_mp3 = digests_dir / f"{config.episode.prefix}_Ep{episode_num:03d}_{today:%Y%m%d}.mp3"

            t0 = time.monotonic()
            if config.audio.music_file:
                music_path = PROJECT_ROOT / config.audio.music_file
                if music_path.exists():
                    logger.info("Mixing with music: %s", music_path.name)

                    # Resolve optional background/outro music file
                    bg_music_path = None
                    if config.audio.background_music_file:
                        bg_music_path = PROJECT_ROOT / config.audio.background_music_file

                    mix_with_music(
                        raw_mp3, music_path, final_mp3,
                        intro_duration=int(config.audio.intro_duration),
                        overlap_duration=int(config.audio.overlap_duration),
                        fade_duration=int(config.audio.fade_duration),
                        outro_duration=int(config.audio.outro_duration),
                        intro_volume=config.audio.intro_volume,
                        overlap_volume=config.audio.overlap_volume,
                        fade_volume=config.audio.fade_volume,
                        outro_volume=config.audio.outro_volume,
                        voice_intro_delay=config.audio.voice_intro_delay,
                        background_music_path=bg_music_path,
                        outro_crossfade=config.audio.outro_crossfade,
                    )
                else:
                    logger.warning("Music file not found: %s — using voice only", music_path)
                    normalize_voice(raw_mp3, final_mp3)
            else:
                normalize_voice(raw_mp3, final_mp3)

            _mix_duration = time.monotonic() - t0
            logger.info("Audio mixing took %.1fs", _mix_duration)
            metrics.record("audio_mix_duration_s", round(_mix_duration, 2))
            audio_duration = get_audio_duration(final_mp3)
            logger.info("Final audio: %s (%.0fs)", final_mp3.name, audio_duration)

            # 10-gate. Skip episode if audio is too short to be a quality episode.
            _min_audio = config.min_audio_duration
            if _min_audio and audio_duration < _min_audio:
                logger.error(
                    "Audio too short (%.0fs < %ds minimum) — skipping episode.",
                    audio_duration, _min_audio,
                )
                final_mp3.unlink(missing_ok=True)
                sys.exit(2)

            # 10a. Generate chapter data (timestamps + JSON)
            if episode_chapters and audio_duration > 0:
                from engine.chapters import calculate_timestamps, write_chapters_json

                # Music intro offset = time before voice starts
                music_intro_offset = config.audio.voice_intro_delay + config.audio.intro_duration
                calculate_timestamps(
                    episode_chapters,
                    audio_duration,
                    music_intro_offset=music_intro_offset,
                )

                ep_title = f"Ep {episode_num}: {hook}" if hook else f"{config.name} - Episode {episode_num}"
                chapters_json_path = digests_dir / f"chapters_ep{episode_num:03d}.json"
                write_chapters_json(
                    episode_chapters,
                    chapters_json_path,
                    episode_title=ep_title,
                )

            # NOTE: raw MP3 cleanup is deferred until after post-validation
            # passes, so we have recovery if the mix is corrupt (see #20).

    # 10b. Upload to R2 (if configured)
    r2_audio_url = None
    if final_mp3 and final_mp3.exists():
        from engine.storage import upload_episode
        r2_audio_url = upload_episode(final_mp3, config)
        if r2_audio_url:
            logger.info("R2 audio URL: %s", r2_audio_url)

    # 10c. Apply OP3 analytics prefix (if enabled)
    rss_audio_url = r2_audio_url
    if config.analytics.enabled and rss_audio_url:
        from engine.publisher import apply_op3_prefix
        rss_audio_url = apply_op3_prefix(rss_audio_url, config.analytics.prefix_url)
        logger.info("OP3 prefixed URL: %s", rss_audio_url)

    # 11. Update RSS feed
    _t_rss = time.monotonic()
    if final_mp3 and final_mp3.exists():
        from engine.publisher import update_rss_feed
        from engine.audio import format_duration

        if hook:
            episode_title = f"Ep {episode_num}: {hook}"
        else:
            episode_title = f"{config.name} - Episode {episode_num} - {today_str}"
        # Use a short summary for the RSS description (first ~500 chars at sentence boundary)
        # to avoid overwhelming podcast app UIs with the full digest.
        _desc_limit = 500
        if len(x_thread) > _desc_limit:
            _cut = x_thread[:_desc_limit].rfind(". ")
            episode_desc = x_thread[:_cut + 1] + " ..." if _cut > 100 else x_thread[:_desc_limit] + "..."
        else:
            episode_desc = x_thread
        episode_desc = episode_desc.rstrip() + "\n\n" + _AI_DISCLOSURE_RSS

        # If no R2 URL but analytics is enabled, build URL and prefix it
        feed_audio_url = rss_audio_url
        if not feed_audio_url and config.analytics.enabled:
            from engine.publisher import apply_op3_prefix
            raw_url = f"{config.publishing.base_url}/{config.publishing.audio_subdir}/{final_mp3.name}"
            feed_audio_url = apply_op3_prefix(raw_url, config.analytics.prefix_url)
            logger.info("OP3 prefixed URL: %s", feed_audio_url)

        # Build chapters URL for RSS if chapter JSON was written
        chapters_url = None
        chapters_json_ep = digests_dir / f"chapters_ep{episode_num:03d}.json"
        if chapters_json_ep.exists():
            chapters_url = (
                f"{config.publishing.base_url}/{config.publishing.audio_subdir}"
                f"/chapters_ep{episode_num:03d}.json"
            )

        # Build transcript URL for RSS if transcript JSON was written
        transcript_url = None
        _ep_prefix = f"{config.episode.prefix}_Ep{episode_num:03d}_{today:%Y%m%d}"
        transcript_json = digests_dir / f"{_ep_prefix}_transcript.json"
        if transcript_json.exists():
            transcript_url = (
                f"{config.publishing.base_url}/{config.publishing.audio_subdir}"
                f"/{_ep_prefix}_transcript.json"
            )

        # Append AI disclosure to channel description for RSS metadata
        channel_desc_with_disclosure = (
            config.publishing.rss_description.rstrip() + " " + _AI_DISCLOSURE_RSS
        )

        logger.info("Updating RSS feed: %s", config.publishing.rss_file)
        update_rss_feed(
            rss_path=rss_path,
            episode_num=episode_num,
            episode_title=episode_title,
            episode_description=episode_desc,
            episode_date=today,
            mp3_filename=final_mp3.name,
            mp3_duration=audio_duration,
            mp3_path=final_mp3,
            base_url=config.publishing.base_url,
            audio_subdir=config.publishing.audio_subdir,
            channel_title=config.publishing.rss_title,
            channel_link=config.publishing.rss_link,
            channel_description=channel_desc_with_disclosure,
            channel_language=config.publishing.rss_language,
            channel_author=config.publishing.rss_author,
            channel_email=config.publishing.rss_email,
            channel_image=config.publishing.rss_image,
            channel_category=config.publishing.rss_category,
            channel_subcategory=getattr(config.publishing, "rss_subcategory", ""),
            guid_prefix=config.publishing.guid_prefix,
            format_duration_func=format_duration,
            audio_url=feed_audio_url,  # Use R2/OP3-prefixed URL if available
            chapters_url=chapters_url,
            transcript_url=transcript_url,
        )

        metrics.record("rss_update_duration_s", round(time.monotonic() - _t_rss, 2))

        # 11b. Notify podcast directories (best-effort, non-blocking)
        from engine.publisher import notify_directories
        rss_url = f"{config.publishing.base_url}/{config.publishing.rss_file}"
        notify_directories(rss_url, show_name=config.publishing.rss_title)

    # 12. Save GitHub Pages summary
    from engine.publisher import save_summary_to_github_pages

    summaries_json = PROJECT_ROOT / config.publishing.summaries_json
    audio_url = r2_audio_url  # Prefer R2 URL
    if not audio_url and final_mp3 and final_mp3.exists():
        audio_url = (
            f"{config.publishing.base_url}/{config.publishing.audio_subdir}/{final_mp3.name}"
        )

    save_summary_to_github_pages(
        summary_text=x_thread,
        summaries_json_path=summaries_json,
        podcast_name=config.publishing.summaries_podcast_name or config.slug,
        episode_num=episode_num,
        episode_title=f"Ep {episode_num}: {hook}" if hook else f"{config.name} - Episode {episode_num} - {today_str}",
        audio_url=audio_url,
        rss_url=f"{config.publishing.base_url}/{config.publishing.rss_file}",
    )

    # 12a. Generate blog post
    try:
        from engine.blog import extract_blog_metadata, generate_blog_post_html
        from generate_html import generate_blog_index, _get_jinja_env, NETWORK_SHOWS as _NS

        if config.slug in _NS:
            _blog_env = _get_jinja_env()
            _blog_meta = extract_blog_metadata(x_thread, config.slug, digest_path.name if digest_path else "")
            _blog_meta["episode_num"] = episode_num
            _blog_html = generate_blog_post_html(x_thread, _blog_meta, _NS[config.slug], _blog_env)
            _blog_dir = PROJECT_ROOT / "blog" / config.slug
            _blog_dir.mkdir(parents=True, exist_ok=True)
            _blog_path = _blog_dir / f"ep{episode_num:03d}.html"
            _blog_path.write_text(_blog_html, encoding="utf-8")
            logger.info("Blog post written: %s", _blog_path)

            # Regenerate blog index (per-show + network)
            generate_blog_index(config.slug)
            logger.info("Blog index regenerated for %s", config.slug)

            from generate_html import generate_network_blog_index as _gen_net_blog
            _gen_net_blog()
            logger.info("Network blog index regenerated")
        else:
            logger.debug("Show %s not in NETWORK_SHOWS, skipping blog generation", config.slug)
    except Exception as exc:
        logger.warning("Blog post generation failed (non-fatal): %s", exc)

    # 12b. Send newsletter
    if config.newsletter.enabled and not args.skip_newsletter:
        from engine.newsletter import send_show_newsletter

        email_id = send_show_newsletter(x_thread, config, episode_num, today_str)
        if email_id:
            logger.info("Newsletter sent: %s", email_id)
        else:
            logger.info("Newsletter skipped or failed.")

    # 13. Post to X
    _t_x = time.monotonic()
    if config.publishing.x_enabled and not args.skip_x:
        from engine.publisher import post_to_x
        from engine.tracking import record_x_post

        prefix = config.publishing.x_env_prefix
        consumer_key = os.getenv(f"{prefix}CONSUMER_KEY", "")
        consumer_secret = os.getenv(f"{prefix}CONSUMER_SECRET", "")
        access_token = os.getenv(f"{prefix}ACCESS_TOKEN", "")
        access_token_secret = os.getenv(f"{prefix}ACCESS_TOKEN_SECRET", "")

        if all([consumer_key, consumer_secret, access_token, access_token_secret]):
            teaser = _build_teaser(config, episode_num, today_str, extra_context)
            tweet_url = post_to_x(
                teaser,
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                access_token=access_token,
                access_token_secret=access_token_secret,
            )
            if tweet_url:
                record_x_post(tracker)
                logger.info("Posted to X: %s", tweet_url)
        else:
            logger.warning("X credentials missing (prefix=%s). Skipping X post.", prefix)

    if config.publishing.x_enabled:
        metrics.record("x_post_duration_s", round(time.monotonic() - _t_x, 2))

    # 14. Post-run validation
    from engine.post_run_validation import run_post_validation
    validation_passed = run_post_validation(
        mp3_path=final_mp3,
        rss_path=rss_path,
        digest_text=x_thread,
        show_name=config.name,
        episode_num=episode_num,
    )
    if not validation_passed:
        logger.error("Post-run validation FAILED — exiting with error code")
        save_usage(tracker, digests_dir)
        sys.exit(1)

    # 14b. Cleanup raw audio now that validation has passed
    if not args.skip_podcast and final_mp3 and final_mp3.exists():
        raw_mp3_cleanup = digests_dir / f"{config.episode.prefix}_Ep{episode_num:03d}_{today:%Y%m%d}_raw.mp3"
        if raw_mp3_cleanup.exists() and raw_mp3_cleanup != final_mp3:
            raw_mp3_cleanup.unlink(missing_ok=True)
            logger.info("Cleaned up raw audio: %s", raw_mp3_cleanup.name)

    # 15. Save tracking & metrics
    save_usage(tracker, digests_dir)
    try:
        metrics.record("digest_chars", len(x_thread) if x_thread else 0)
        metrics.record("audio_duration_s", audio_duration)
        metrics.save(digests_dir)
        logger.info("Pipeline summary: %s", metrics.summary())
    except Exception as exc:
        logger.warning("Metrics save failed (non-fatal): %s", exc)
    logger.info("=== %s complete ===", config.name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_with_expansion(
    feed_dicts: list[dict],
    keywords: list[str] | None,
    content_tracker,
    min_articles: int = 3,
) -> list[dict]:
    """Fetch articles with progressive search expansion on slow news days.

    Tries increasingly wider search windows (24h → 48h → 72h) and relaxed
    dedup thresholds until at least *min_articles* survive, or all expansion
    stages are exhausted.  This prevents shows like Env Intel from producing
    empty episodes on days when RSS feeds are sparse.
    """
    from engine.fetcher import fetch_rss_articles
    from engine.utils import deduplicate_by_entity

    expansion_stages = [
        # (cutoff_hours, similarity_threshold, keyword_filter)
        (24, 0.65, True),    # Normal: last 24h, strict dedup, keywords on
        (48, 0.65, True),    # Expand window to 48h
        (72, 0.55, True),    # Expand to 72h, relax dedup
        (72, 0.55, False),   # Drop keyword filter entirely (broader catch)
    ]

    for cutoff_hours, sim_threshold, use_keywords in expansion_stages:
        kw = keywords if use_keywords else None
        articles = fetch_rss_articles(
            feed_dicts, cutoff_hours=cutoff_hours, keywords=kw,
        )
        logger.info(
            "Fetch (cutoff=%dh, keywords=%s): %d articles",
            cutoff_hours, "on" if use_keywords else "off", len(articles),
        )

        articles = deduplicate_by_entity(articles, max_per_entity=2)
        # Reduce dedup lookback for young shows (< 10 episodes) to avoid
        # over-filtering when the content tracker has very few episodes.
        ep_count = len(content_tracker.data.get("episodes", []))
        lookback_days = 1 if ep_count < 10 else 3
        articles = content_tracker.filter_recent_articles(
            articles, similarity_threshold=sim_threshold, days=lookback_days,
        )
        logger.info(
            "After dedup (sim=%.2f): %d articles remain",
            sim_threshold, len(articles),
        )

        if len(articles) >= min_articles:
            return articles

        logger.info(
            "Only %d articles (need %d) — expanding search...",
            len(articles), min_articles,
        )

    # Return whatever we have, even if below min_articles
    return articles


def _extract_segment_summaries(
    digest_text: str, segments: list,
) -> dict:
    """Extract 1-2 sentence angle summaries for each evergreen segment.

    Searches the digest for each segment's title heading and captures the
    first couple of sentences as an angle summary.  This is stored in the
    content tracker so future slow-news prompts can enforce freshness.
    """
    import re

    summaries: dict = {}
    for seg in segments:
        title = seg.get("title", "")
        if not title:
            continue
        # Look for the segment title (possibly surrounded by markdown)
        pattern = re.escape(title)
        match = re.search(
            rf"(?:^|\n)(?:\*{{0,2}}|#+\s*).*{pattern}.*(?:\n|$)(.*?)(?:\n\n|\n#|\n\*\*|\Z)",
            digest_text,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            text = match.group(1).strip()
            # Take first 1-2 sentences (up to ~200 chars)
            sentences = re.split(r"(?<=[.!?])\s+", text)
            summary = " ".join(sentences[:2])[:200]
            if summary:
                summaries[seg["id"]] = summary
    return summaries


def _extract_hook(digest: str) -> str | None:
    """Extract the **HOOK:** line from a generated digest.

    The digest prompts instruct the LLM to include a line like:
        **HOOK:** Scientists just discovered a new way to...

    Returns the hook text (without the prefix) or *None* if not found.
    """
    import re

    for line in digest.splitlines():
        m = re.match(r"^\s*\*{0,2}HOOK:?\*{0,2}\s*(.+)", line, re.IGNORECASE)
        if m:
            hook = m.group(1).strip()
            # Strip leftover markdown/brackets the LLM sometimes wraps
            hook = re.sub(r"^\[|\]$", "", hook).strip()
            if hook:
                return hook
    return None

def _clean_digest_for_podcast(digest: str) -> str:
    """Strip metadata from a digest before it is fed to the podcast script prompt.

    Removes URLs, emoji, unicode box-drawing characters, ``Source:`` lines,
    markdown formatting, and raw timestamps so the LLM is less likely to echo
    them into the spoken script.  The *content* (titles, summaries, quotes)
    is preserved.
    """
    import re

    lines: list[str] = []
    for line in digest.splitlines():
        # Drop lines that are just separators (━━━, ----, ====, etc.)
        if re.match(r"^[\s━─═\-=]{4,}$", line):
            continue
        # Drop standalone source attribution lines
        if re.match(r"^\s*(Source|Post|Read more)\s*:", line, re.IGNORECASE):
            continue
        # Drop the HOOK line (already extracted; don't echo into podcast script)
        if re.match(r"^\s*\*{0,2}HOOK:?\*{0,2}\s+", line, re.IGNORECASE):
            continue
        # Strip inline URLs  (keeps surrounding text)
        line = re.sub(r"https?://\S+", "", line)
        # Strip markdown link syntax  [text](url) -> text
        line = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)
        # Strip markdown bold/italic markers
        line = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", line)
        # Strip markdown header markers
        line = re.sub(r"^#{1,6}\s+", "", line)
        # Strip emoji and common unicode symbols (broad range)
        line = re.sub(
            r"[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2B55"
            r"\u25B2\u25BC\u2580-\u259F\u2500-\u257F"
            r"\U0001F900-\U0001F9FF]+",
            "",
            line,
        )
        # Collapse leftover whitespace
        line = re.sub(r"  +", " ", line).strip()
        lines.append(line)

    return "\n".join(lines)


def _clean_podcast_script(script: str, host_name: str = "Patrick") -> str:
    """Strip speaker prefixes (Host:, <host_name>:) and stage directions from podcast script.

    This produces clean text suitable for TTS synthesis.
    """
    import re

    host_prefix = f"{host_name}:"
    # Common speaker/stage-direction prefixes that LLMs generate.
    # These must be stripped so TTS doesn't try to voice them.
    _SPEAKER_PREFIXES = [
        "Host:",
        host_prefix,
        # Russian (Финансы Просто)
        "Ведущая:",
        "Ведущий:",
        # Generic
        "Narrator:",
        "Speaker:",
    ]
    parts: list[str] = []
    for line in script.splitlines():
        line = line.strip()
        # Skip stage directions, blank lines, and bracketed notes
        if not line or line.startswith("["):
            continue
        # Skip footer/debug metadata Grok sometimes appends (numeric or word form)
        if re.match(r"(?i)^\(?\s*(word\s*count|total\s*words|character\s*count)\b", line):
            continue
        if re.match(r"(?i)^\(?\s*(approximately\s+)?\d[\d,]*\s+words?\s*\)?$", line):
            continue
        if re.match(r"(?i)^content\s*:\s*$", line):
            break
        # Skip title/episode header lines the LLM occasionally generates
        # before the actual script (e.g. "Tesla Shorts Time Daily – Episode 412 – March 19, 2026"
        # or with word-form numbers after pronunciation: "Episode four hundred twelve")
        if re.match(
            r"(?i)^.{3,50}\s*[-–—,]\s*episode\s+.{1,40}\s*[-–—,]\s*"
            r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\b",
            line,
        ):
            continue
        # Also catch simpler variants: "Show Name, Episode N" at end of line
        # (with optional trailing metadata like "Script (Expanded – X words)")
        if re.match(
            r"(?i)^.{3,50},?\s+episode\s+[\w\s]+[,.]?\s*"
            r"(?:script\b.*)?$",
            line,
        ):
            continue
        # Catch title lines with "(Expanded – X words)" or similar metadata suffix
        if re.search(r"(?i)\b(expanded|rewritten|revised)\s*[-–—]\s*.*\bwords?\b", line):
            continue
        # Drop markdown artifacts
        if line in {"**", "*", "__", "—", "–"}:
            continue
        # Drop leaked prompt instruction lines the LLM may echo
        if re.match(r"(?i)^(RULES|NEVER INCLUDE|CONTENT FOCUS|TONE|SCRIPT STRUCTURE|HOST:)\b", line):
            continue
        if re.match(r"(?i)^(Use this exact|Deliver this hook|Narrate EVERY|Here is today)", line):
            continue
        # Drop LLM preambles from retry/expansion responses
        if re.match(r"(?i)^(here(?:\s*'?s?|\s+is)\s+(your|the|my)\s+(expanded|rewritten|revised|updated)|I'?ve\s+(expanded|rewritten))", line):
            continue
        # Drop source attribution lines that survived earlier cleaning
        if re.match(r"(?i)^\s*source\s*:", line):
            continue
        # Strip speaker prefixes
        text = line
        for prefix in _SPEAKER_PREFIXES:
            if line.startswith(prefix):
                text = line[len(prefix):].strip()
                break
        if text:
            parts.append(text)

    joined = "\n\n".join(parts).strip()

    # Defense-in-depth: break wall-of-text paragraphs at sentence boundaries.
    # Grok-4 intermittently produces single mega-paragraphs (500+ chars) per
    # topic instead of natural 1-2 sentence paragraphs.  TTS reads these
    # without pauses, which sounds unnatural.  Split long paragraphs into
    # ~2 sentence chunks so TTS inserts natural breathing pauses.
    joined = _break_long_paragraphs(joined)

    # Second pass: strip any speaker prefixes — both at line/paragraph starts
    # (exposed by _break_long_paragraphs) and mid-sentence (when the LLM puts
    # multiple Host: segments on a single line).
    for prefix in _SPEAKER_PREFIXES:
        escaped = re.escape(prefix)
        # At line/paragraph starts
        joined = re.sub(r"^" + escaped + r"\s*", "", joined, flags=re.MULTILINE)
        # Mid-sentence: "sentence. Host: Next" → "sentence. Next"
        joined = re.sub(r"(?<=[.!?])\s+" + escaped + r"\s*", " ", joined)
    # Collapse blank lines that prefix removal may have created
    joined = re.sub(r"\n{3,}", "\n\n", joined).strip()

    return joined


def _strip_post_pronunciation_artifacts(text: str) -> str:
    """Strip metadata lines that survived pronunciation conversion.

    After ``_apply_pronunciation`` converts numbers to words, lines like
    ``(Word count: 2,478)`` become ``(Word count: two thousand four hundred
    seventy-eight)`` which earlier regex passes couldn't match.  This final
    pass catches them in word form.
    """
    import re
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Word count in any form (numeric or word)
        if re.match(r"(?i)^\(?\s*(word\s*count|total\s*words|character\s*count)\b", stripped):
            continue
        # "Target: X words" metadata (may have mangled numbers after pronunciation)
        if re.search(r"(?i)\btarget\s*:\s*.*\bwords?\b", stripped):
            continue
        # "approximately X min spoken" metadata
        if re.search(r"(?i)\bapproximately\s+.*\bmin(utes?)?\s+(spoken|audio|reading)\b", stripped):
            continue
        cleaned.append(line)
    return "\n".join(cleaned)


# Sentence-end pattern: period/!/?  followed by two+ spaces or a space before
# a capital letter (catches "sentence. Next sentence" even with single space).
_SENTENCE_SPLIT_RE = None


def _break_long_paragraphs(text: str, max_chars: int = 400) -> str:
    """Split paragraphs longer than *max_chars* at sentence boundaries.

    Keeps paragraphs at roughly 1-3 sentences so TTS produces natural pauses.
    """
    import re

    global _SENTENCE_SPLIT_RE
    if _SENTENCE_SPLIT_RE is None:
        # Split after sentence-ending punctuation followed by a space and
        # uppercase letter (the start of the next sentence).
        _SENTENCE_SPLIT_RE = re.compile(
            r'(?<=[.!?])\s+(?=[A-Z\u0400-\u04FF])'
        )

    out_paragraphs: list[str] = []
    for para in text.split("\n\n"):
        if len(para) <= max_chars:
            out_paragraphs.append(para)
            continue
        # Split into individual sentences
        sentences = _SENTENCE_SPLIT_RE.split(para)
        chunk: list[str] = []
        chunk_len = 0
        for sent in sentences:
            if chunk and chunk_len + len(sent) > max_chars:
                out_paragraphs.append(" ".join(chunk))
                chunk = []
                chunk_len = 0
            chunk.append(sent)
            chunk_len += len(sent) + 1  # +1 for joining space
        if chunk:
            out_paragraphs.append(" ".join(chunk))

    return "\n\n".join(out_paragraphs)


def _build_teaser(config, episode_num: int, today_str: str, extra_context: dict) -> str:
    """Build a short X teaser post for the episode.

    If the YAML config has ``x_teaser_template``, it's used as a format string
    with ``{episode_num}``, ``{today_str}``, and any extra_context keys.  Otherwise,
    falls back to the per-show hardcoded templates below.
    """
    # Use YAML template if configured
    template = getattr(config.publishing, "x_teaser_template", "")
    if template:
        fmt_vars = {"episode_num": episode_num, "today_str": today_str, "show_name": config.name}
        fmt_vars.update(extra_context)
        try:
            return template.format(**fmt_vars)
        except (KeyError, IndexError):
            logger.warning("x_teaser_template format failed, falling back to hardcoded")

    slug = config.slug
    if slug == "tesla":
        price_str = ""
        if "price" in extra_context:
            price_str = f" | TSLA ${extra_context['price']}"
        return (
            f"🚀⚡ Tesla Shorts Time Daily — {today_str}{price_str}\n\n"
            f"Episode {episode_num} is live!\n"
            f"🎧 Listen & read: https://nerranetwork.com/tesla-summaries.html"
        )
    elif slug == "omni_view":
        return (
            f"📰⚖️ Omni View — {today_str}\n\n"
            f"Episode {episode_num}: Balanced news perspectives.\n"
            f"🎧 Read & listen: https://nerranetwork.com/omni-view-summaries.html"
        )
    elif slug == "fascinating_frontiers":
        return (
            f"🚀🌌 Fascinating Frontiers — {today_str}\n\n"
            f"Episode {episode_num}: Space & astronomy news.\n"
            f"🎧 Read & listen: https://nerranetwork.com/fascinating-frontiers-summaries.html"
        )
    elif slug == "planetterrian":
        return (
            f"🌍🧬 Planetterrian Daily — {today_str}\n\n"
            f"Episode {episode_num}: Science, longevity & health.\n"
            f"🎧 Read & listen: https://nerranetwork.com/planetterrian-summaries.html"
        )
    return f"{config.name} Episode {episode_num} — {today_str}"



# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    args = parse_args()
    try:
        run(args)
    except KeyboardInterrupt:
        logger.info("Interrupted.")
        sys.exit(1)
    except Exception:
        logger.exception("Pipeline failed")
        sys.exit(1)
