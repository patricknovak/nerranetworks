#!/usr/bin/env python3
"""Unified entry point for all podcast shows.

Usage:
    python run_show.py <show_name> [options]

    show_name: tesla | omni_view | fascinating_frontiers | planetterrian | env_intel

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
import sys
from pathlib import Path

from dotenv import load_dotenv

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
# Pipeline
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> None:
    from engine.config import load_config

    # 1. Load config
    config_path = PROJECT_ROOT / "shows" / f"{args.show}.yaml"
    config = load_config(config_path)
    logger.info("=== %s ===", config.name)

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

    # 2. Episode number
    from engine.publisher import get_next_episode_number
    rss_path = PROJECT_ROOT / config.publishing.rss_file
    episode_num = get_next_episode_number(
        rss_path, digests_dir, mp3_glob_pattern=config.episode.mp3_glob,
    )
    logger.info("Episode number: %d", episode_num)

    # 3. Tracker
    from engine.tracking import create_tracker, save_usage
    tracker = create_tracker(config.name, episode_num)

    # 4. Pre-fetch hook (Tesla: stock price + X posts; others: no-op)
    hook_module = _load_hook(args.show)
    extra_context: dict = {}
    if hook_module and hasattr(hook_module, "pre_fetch"):
        logger.info("Running pre-fetch hook for %s ...", args.show)
        extra_context = hook_module.pre_fetch(config) or {}

    # 5. Fetch news
    from engine.fetcher import fetch_rss_articles
    feed_dicts = [{"url": s.url, "label": s.label} for s in config.sources]
    articles = fetch_rss_articles(
        feed_dicts,
        cutoff_hours=24,
        keywords=config.keywords,
    )
    logger.info("Fetched %d articles from %d feeds", len(articles), len(config.sources))

    # 5b. Cross-episode content tracking & dedup
    from engine.content_tracker import ContentTracker, SHOW_SECTION_PATTERNS
    from engine.utils import deduplicate_by_entity

    section_patterns = SHOW_SECTION_PATTERNS.get(config.slug, {})
    content_tracker = ContentTracker(config.slug, digests_dir)
    content_tracker.load()

    articles = deduplicate_by_entity(articles, max_per_entity=2)
    articles = content_tracker.filter_recent_articles(articles, similarity_threshold=0.65, days=3)
    logger.info("After cross-episode + entity dedup: %d articles remain", len(articles))

    if not articles:
        logger.warning("No articles found. Exiting.")
        return

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

    template_vars = {
        "today_str": today_str,
        "date_human": today_str,  # alias used by Omni View prompts
        "news_section": news_section,
        "sections_json": news_section,  # alias used by Omni View digest prompt
        "episode_num": episode_num,
    }
    # Merge extra context from hooks (e.g. price, change_str, x_posts_section)
    template_vars.update(extra_context)

    # 7. Generate digest
    from engine.generator import generate_digest
    logger.info("Generating digest ...")
    x_thread = generate_digest(template_vars, config, tracker=tracker)

    # Record episode content in the cross-episode tracker
    if section_patterns:
        content_tracker.record_episode(x_thread, section_patterns)
        content_tracker.save()

    # Extract the daily hook (headline) from the digest
    hook = _extract_hook(x_thread)
    if hook:
        logger.info("Hook: %s", hook)
    else:
        logger.warning("No HOOK found in digest — using generic episode title")

    # Save digest to file
    digest_md = digests_dir / f"{config.episode.prefix}_Ep{episode_num:03d}_{today:%Y%m%d}.md"
    digest_md.write_text(x_thread, encoding="utf-8")
    logger.info("Digest saved: %s", digest_md)

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

        pod_vars = {
            "episode_num": episode_num,
            "today_str": today_str,
            "date_human": today_str,  # alias used by Omni View prompts
            "digest": clean_digest,
            "hook": hook or f"Here's what's making news in the {config.name} world today.",
        }
        # Merge extra context for podcast prompt (e.g. tone_hint, intro_line)
        pod_vars.update(extra_context)

        # OV uses procedural script generation, not LLM
        if args.show == "omni_view":
            podcast_script = _generate_omni_view_script(x_thread, hook=hook)
        else:
            logger.info("Generating podcast script ...")
            podcast_script = generate_podcast_script(pod_vars, config, tracker=tracker)

        # Clean podcast script: strip speaker prefixes and stage directions
        podcast_script = _clean_podcast_script(podcast_script)

        # Apply pronunciation fixes
        podcast_script = _apply_pronunciation(podcast_script, args.show)

        # Save TTS-ready script for debugging pronunciation/intro issues
        tts_script_path = digests_dir / f"{config.episode.prefix}_Ep{episode_num:03d}_{today:%Y%m%d}_tts.txt"
        tts_script_path.write_text(podcast_script, encoding="utf-8")
        logger.info("TTS script saved: %s", tts_script_path)

        # 9. TTS
        api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
        if not api_key:
            logger.error("ELEVENLABS_API_KEY not set. Skipping TTS.")
        else:
            from engine.tts import synthesize, validate_elevenlabs_auth
            validate_elevenlabs_auth(api_key)

            raw_mp3 = digests_dir / f"{config.episode.prefix}_Ep{episode_num:03d}_{today:%Y%m%d}_raw.mp3"
            logger.info("Synthesizing audio ...")
            synthesize(
                podcast_script,
                config.tts.voice_id,
                raw_mp3,
                api_key=api_key,
                max_chars=config.tts.max_chars,
                model_id=config.tts.model,
                stability=config.tts.stability,
                similarity_boost=config.tts.similarity_boost,
                style=config.tts.style,
            )
            from engine.tracking import record_tts_usage
            record_tts_usage(tracker, len(podcast_script))

            # 10. Audio mixing
            from engine.audio import get_audio_duration, mix_with_music, normalize_voice

            final_mp3 = digests_dir / f"{config.episode.prefix}_Ep{episode_num:03d}_{today:%Y%m%d}.mp3"

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
                    )
                else:
                    logger.warning("Music file not found: %s — using voice only", music_path)
                    normalize_voice(raw_mp3, final_mp3)
            else:
                normalize_voice(raw_mp3, final_mp3)

            audio_duration = get_audio_duration(final_mp3)
            logger.info("Final audio: %s (%.0fs)", final_mp3.name, audio_duration)

            # Cleanup raw audio
            if raw_mp3.exists() and final_mp3.exists() and raw_mp3 != final_mp3:
                raw_mp3.unlink(missing_ok=True)

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
    if final_mp3 and final_mp3.exists():
        from engine.publisher import update_rss_feed
        from engine.audio import format_duration

        if hook:
            episode_title = f"Ep {episode_num}: {hook}"
        else:
            episode_title = f"{config.name} - Episode {episode_num} - {today_str}"
        episode_desc = x_thread[:500] + "..." if len(x_thread) > 500 else x_thread

        # If no R2 URL but analytics is enabled, build URL and prefix it
        feed_audio_url = rss_audio_url
        if not feed_audio_url and config.analytics.enabled:
            from engine.publisher import apply_op3_prefix
            raw_url = f"{config.publishing.base_url}/{config.publishing.audio_subdir}/{final_mp3.name}"
            feed_audio_url = apply_op3_prefix(raw_url, config.analytics.prefix_url)
            logger.info("OP3 prefixed URL: %s", feed_audio_url)

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
            channel_description=config.publishing.rss_description,
            channel_language=config.publishing.rss_language,
            channel_author=config.publishing.rss_author,
            channel_email=config.publishing.rss_email,
            channel_image=config.publishing.rss_image,
            channel_category=config.publishing.rss_category,
            guid_prefix=config.publishing.guid_prefix,
            format_duration_func=format_duration,
            audio_url=feed_audio_url,  # Use R2/OP3-prefixed URL if available
        )

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

    # 12b. Send newsletter
    if config.newsletter.enabled and not args.skip_newsletter:
        from engine.newsletter import send_show_newsletter

        email_id = send_show_newsletter(x_thread, config, episode_num, today_str)
        if email_id:
            logger.info("Newsletter sent: %s", email_id)
        else:
            logger.info("Newsletter skipped or failed.")

    # 13. Post to X
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

    # 14. Save tracking
    save_usage(tracker, digests_dir)
    logger.info("=== %s complete ===", config.name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _clean_podcast_script(script: str) -> str:
    """Strip speaker prefixes (Host:, Patrick:) and stage directions from podcast script.

    This produces clean text suitable for TTS synthesis.
    """
    import re

    parts: list[str] = []
    for line in script.splitlines():
        line = line.strip()
        # Skip stage directions, blank lines, and bracketed notes
        if not line or line.startswith("["):
            continue
        # Stop at footer/debug metadata Grok sometimes appends
        if re.match(r"(?i)^(word\s*count|total\s*words|character\s*count)\b", line):
            break
        if re.match(r"(?i)^content\s*:\s*$", line):
            break
        # Drop markdown artifacts
        if line in {"**", "*", "__", "—", "–"}:
            continue
        # Drop leaked prompt instruction lines the LLM may echo
        if re.match(r"(?i)^(RULES|NEVER INCLUDE|CONTENT FOCUS|TONE|SCRIPT STRUCTURE|HOST:)\b", line):
            continue
        if re.match(r"(?i)^(Use this exact|Deliver this hook|Narrate EVERY|Here is today)", line):
            continue
        # Drop source attribution lines that survived earlier cleaning
        if re.match(r"(?i)^\s*source\s*:", line):
            continue
        # Strip speaker prefixes
        if line.startswith("Host:"):
            parts.append(line[5:].strip())
        elif line.startswith("Patrick:"):
            parts.append(line[9:].strip())
        else:
            parts.append(line)

    return " ".join(parts).strip()


def _build_teaser(config, episode_num: int, today_str: str, extra_context: dict) -> str:
    """Build a short X teaser post for the episode."""
    slug = config.slug
    if slug == "tesla":
        price_str = ""
        if "price" in extra_context:
            price_str = f" | TSLA ${extra_context['price']}"
        return (
            f"🚀⚡ Tesla Shorts Time Daily — {today_str}{price_str}\n\n"
            f"Episode {episode_num} is live!\n"
            f"🎧 Listen & read: https://patricknovak.github.io/Tesla-shorts-time/tesla-summaries.html"
        )
    elif slug == "omni_view":
        return (
            f"📰⚖️ Omni View — {today_str}\n\n"
            f"Episode {episode_num}: Balanced news perspectives.\n"
            f"🎧 Read & listen: https://patricknovak.github.io/Tesla-shorts-time/omni-view-summaries.html"
        )
    elif slug == "fascinating_frontiers":
        return (
            f"🚀🌌 Fascinating Frontiers — {today_str}\n\n"
            f"Episode {episode_num}: Space & astronomy news.\n"
            f"🎧 Read & listen: https://patricknovak.github.io/Tesla-shorts-time/fascinating-frontiers-summaries.html"
        )
    elif slug == "planetterrian":
        return (
            f"🌍🧬 Planetterrian Daily — {today_str}\n\n"
            f"Episode {episode_num}: Science, longevity & health.\n"
            f"🎧 Read & listen: https://patricknovak.github.io/Tesla-shorts-time/planetterrian-summaries.html"
        )
    return f"{config.name} Episode {episode_num} — {today_str}"


def _generate_omni_view_script(briefing_markdown: str, hook: str | None = None) -> str:
    """Procedural podcast script generation for Omni View.

    Omni View doesn't use an LLM for podcast scripts — it parses the
    markdown briefing and builds a spoken script programmatically.
    This is a simplified version of omni_view.py's generate_omni_view_script().
    """
    import re

    today = datetime.datetime.now().strftime("%B %d, %Y")

    def _strip_md(s: str) -> str:
        s = re.sub(r"\[([^\]]+)\]\(https?://[^\)]+\)", r"\1", s)
        s = re.sub(r"https?://\S+", "", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
        s = re.sub(r"\*([^*]+)\*", r"\1", s)
        return s.strip()

    def _after_colon(ln: str) -> str:
        parts = ln.split(":", 1)
        return _strip_md(parts[1]) if len(parts) == 2 else ""

    text = _strip_md(briefing_markdown or "")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

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

        if low.startswith("**perspectives") or (low.startswith("perspectives") and ":" in ln[:20]):
            in_perspectives = True
            perspective_lines = []
            after_colon = _after_colon(ln)
            if after_colon:
                perspective_lines.append(after_colon)
            in_questions = False
            continue
        if in_perspectives:
            if ln.strip().startswith("**") and not ln.strip().lower().startswith("**perspectives"):
                if perspective_lines:
                    cur["perspectives"] = [" ".join(perspective_lines).strip()]
                in_perspectives = False
                perspective_lines = []
                if "questions to consider" in ln.lower():
                    in_questions = True
                continue
            perspective_lines.append(ln.strip())
            continue

        if ln.startswith("- ") and "perspective" in low[:25]:
            p = re.sub(r"^-+\s*", "", ln).strip()
            p = re.sub(r"^Perspective\s*\d*\s*:\s*", "", p, flags=re.IGNORECASE).strip()
            if p:
                cur["perspectives"].append(p)
            continue

    if cur:
        if in_perspectives and perspective_lines:
            cur["perspectives"] = [" ".join(perspective_lines).strip()]
        stories.append(cur)

    if not stories:
        titles = []
        for ln in lines:
            if ln.startswith("- ") and len(titles) < 8:
                titles.append(ln[2:].strip())
        stories = [{"section": "Top stories", "title": t, "what": "", "perspectives": [], "questions": []} for t in titles]

    max_stories = 7
    picked = stories[:max_stories]

    section_intro = {
        "Top stories": "First, here are the top stories of the day.",
        "Top world stories": "Now, a quick scan of the world headlines.",
        "Top business stories": "In business and the economy.",
        "Top technology stories": "In tech.",
        "Top popular media stories": "And in culture and popular media.",
        "Top gossip stories": "Finally, a quick round of lighter headlines.",
    }
    transitions = [
        "Next.", "Meanwhile.", "Also in the mix today.",
        "Here's another one to watch.", "And one more story worth your attention.",
    ]

    script: list[str] = []
    script.append("Good morning. This is Omni View — balanced news perspectives.")
    script.append(f"Today is {today}.")
    if hook:
        script.append(hook)
    script.append("")
    script.append("We'll cover what happened, how different viewpoints frame it — so you can decide for yourself.")
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
        if perspectives:
            p1 = (perspectives[0] or "").strip()
            if p1:
                if len(perspectives) > 1:
                    script.append("Across perspectives: " + p1 + " " + (perspectives[1] or "").strip())
                else:
                    script.append("Across perspectives: " + p1)
        if questions:
            script.append("Question to consider: " + questions[0].strip())
        script.append("")

    script.append("That's Omni View.")
    script.append("For full source links and more context, open today's written briefing on the Omni View summaries page.")
    script.append("As always: compare outlets, look for primary documents, and separate what's known from what's assumed.")

    return "\n".join(script)


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
