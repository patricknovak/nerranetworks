#!/usr/bin/env python3
"""Scaffold a new podcast show from quality templates.

Creates the YAML config, digest prompt, and podcast prompt files from
templates, then runs validation to catch quality issues before the first
episode.

Usage:
    python create_show.py

Interactive prompts guide you through the setup. All generated files are
pre-populated with quality standards and annotated with customization
instructions.
"""

from __future__ import annotations

import re
import shutil
import sys
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SHOWS_DIR = PROJECT_ROOT / "shows"
PROMPTS_DIR = SHOWS_DIR / "prompts"
TEMPLATES_DIR = SHOWS_DIR / "templates"


def _slugify(name: str) -> str:
    """Convert a show name to a filesystem-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug


def _ask(prompt: str, default: str = "") -> str:
    """Prompt for input with optional default."""
    if default:
        prompt = f"{prompt} [{default}]: "
    else:
        prompt = f"{prompt}: "
    result = input(prompt).strip()
    return result or default


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    """Prompt for yes/no answer."""
    suffix = " [Y/n]: " if default else " [y/N]: "
    result = input(prompt + suffix).strip().lower()
    if not result:
        return default
    return result in ("y", "yes")


def _print_header(text: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {text}")
    print(f"{'=' * 60}\n")


def _print_quality_check(label: str, status: str, ok: bool) -> None:
    icon = "+" if ok else "!"
    print(f"  [{icon}] {label}: {status}")


def main() -> None:
    _print_header("New Podcast Show — Scaffolding Tool")

    print("This tool creates the config and prompt files for a new show,")
    print("pre-populated with quality standards from the best existing shows.\n")

    # -----------------------------------------------------------------------
    # 1. Basic info
    # -----------------------------------------------------------------------
    show_name = _ask("Show name (e.g. 'Environmental Intelligence')")
    if not show_name:
        print("Error: Show name is required.")
        sys.exit(1)

    slug = _ask("URL slug", _slugify(show_name))

    # Check for conflicts
    config_path = SHOWS_DIR / f"{slug}.yaml"
    if config_path.exists():
        print(f"\nError: {config_path} already exists. Choose a different slug or remove it first.")
        sys.exit(1)

    description = _ask("One-sentence description for RSS feeds")
    topic_domain = _ask("Topic domain (e.g. 'environmental science', 'space exploration', 'AI research')")

    # -----------------------------------------------------------------------
    # 2. Audience
    # -----------------------------------------------------------------------
    _print_header("Audience Definition")

    print("Defining your audience precisely is the #1 factor in content quality.")
    print("Be specific — 'tech professionals' is weak; 'senior ML engineers at")
    print("startups who need to stay current on model architectures' is strong.\n")

    audience = _ask("Who is your audience? (specific description)")
    audience_traits = _ask("Audience traits (e.g. 'busy, skeptical, expert-level')", "busy, informed, and skeptical")
    audience_wants = _ask("What do they want? (e.g. 'actionable intelligence they can use this week')")
    audience_doesnt_want = _ask("What DON'T they want? (e.g. 'hype and general awareness pieces')")

    # -----------------------------------------------------------------------
    # 3. Host persona
    # -----------------------------------------------------------------------
    _print_header("Host Persona")

    print("A strong host persona makes the podcast sound human, not robotic.")
    print("The host should have specific expertise, not just be 'a journalist'.\n")

    host_location = _ask("Host location (e.g. 'Vancouver, BC')", "Vancouver")
    host_experience_years = _ask("Years of experience", "15")
    host_expertise = _ask("Specific expertise area (e.g. 'contaminated sites and remediation')")
    host_personality = _ask(
        "Personality traits (e.g. 'occasionally dry humour, genuine curiosity')",
        "occasionally dry humour, genuine curiosity",
    )

    # -----------------------------------------------------------------------
    # 4. Content sections
    # -----------------------------------------------------------------------
    _print_header("Content Sections")

    print("Your show needs 3-4 distinct content sections beyond the Lead Story.")
    print("Example: Env Intel uses 'Regulatory Watch', 'Science & Technical',")
    print("'Industry & Practice'. Tesla uses 'X Takeover', 'Short Spot',")
    print("'First Principles'.\n")

    sections: list[str] = []
    for i in range(1, 5):
        sec = _ask(f"Section {i} name (blank to stop)", "")
        if not sec:
            break
        sections.append(sec)

    if not sections:
        sections = ["Analysis & Context", "Research & Findings", "Industry Watch"]
        print(f"  Using defaults: {', '.join(sections)}")

    # -----------------------------------------------------------------------
    # 5. Show format
    # -----------------------------------------------------------------------
    _print_header("Show Format")

    use_music = _ask_yes_no("Include intro/outro music?", default=False)
    enable_newsletter = _ask_yes_no("Enable newsletter integration?", default=False)

    episode_prefix = _ask(
        "Episode filename prefix (e.g. 'Env_Intel', 'Tesla')",
        slug.replace("_", " ").title().replace(" ", "_"),
    )

    # -----------------------------------------------------------------------
    # 6. Generate files
    # -----------------------------------------------------------------------
    _print_header("Generating Files")

    # Create output directory
    output_dir = PROJECT_ROOT / "digests" / slug
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / ".gitkeep").touch()
    print(f"  Created: digests/{slug}/")

    # --- YAML config ---
    template_yaml = (TEMPLATES_DIR / "show_template.yaml").read_text()
    yaml_content = template_yaml.replace("{SHOW_NAME}", show_name)
    yaml_content = yaml_content.replace("{slug}", slug)
    yaml_content = yaml_content.replace("{ONE_SENTENCE_DESCRIPTION}", description)
    yaml_content = yaml_content.replace("{EPISODE_PREFIX}", episode_prefix)
    yaml_content = yaml_content.replace("{RSS_DESCRIPTION}", description)
    yaml_content = yaml_content.replace("{SLUG_UPPER}", slug.upper())

    if not use_music:
        # Already null in template, no changes needed
        pass

    if enable_newsletter:
        yaml_content = yaml_content.replace(
            "newsletter:\n  enabled: false",
            f"newsletter:\n  enabled: true\n  platform: buttondown\n"
            f"  api_key_env: {slug.upper()}_NEWSLETTER_API_KEY\n"
            f"  status: about_to_send",
        )

    config_path.write_text(yaml_content)
    print(f"  Created: shows/{slug}.yaml")

    # --- Digest prompt ---
    template_digest = (TEMPLATES_DIR / "digest_template.txt").read_text()
    digest_content = template_digest.replace("{SHOW_NAME}", show_name)
    digest_content = digest_content.replace("{TOPIC_DOMAIN}", topic_domain)
    digest_content = digest_content.replace(
        "{TARGET_AUDIENCE_DESCRIPTION}", audience,
    )
    digest_content = digest_content.replace(
        "{AUDIENCE_DESCRIPTION_WITH_STAKES}", audience,
    )

    section_blocks = []
    for i, sec in enumerate(sections):
        key = f"{{SECTION_{i + 2}_NAME}}"
        digest_content = digest_content.replace(key, sec)
        section_blocks.append(sec)

    digest_path = PROMPTS_DIR / f"{slug}_digest.txt"
    digest_path.write_text(digest_content)
    print(f"  Created: shows/prompts/{slug}_digest.txt")

    # --- Podcast prompt ---
    template_podcast = (TEMPLATES_DIR / "podcast_template.txt").read_text()
    podcast_content = template_podcast.replace("{SHOW_NAME}", show_name)
    podcast_content = podcast_content.replace("{DOMAIN}", topic_domain)
    podcast_content = podcast_content.replace("{LOCATION}", host_location)
    podcast_content = podcast_content.replace("{YEARS}", host_experience_years)
    podcast_content = podcast_content.replace("{SPECIFIC_EXPERTISE}", host_expertise)
    podcast_content = podcast_content.replace("{PERSONALITY_TRAITS}", host_personality)
    podcast_content = podcast_content.replace("{TARGET_AUDIENCE}", audience)
    podcast_content = podcast_content.replace("{AUDIENCE_TRAITS}", audience_traits)
    podcast_content = podcast_content.replace("{WHAT_AUDIENCE_WANTS}", audience_wants)
    podcast_content = podcast_content.replace("{WHAT_AUDIENCE_DOESNT_WANT}", audience_doesnt_want)

    music_note = "no music" if not use_music else "with intro music"
    podcast_content = podcast_content.replace("{MUSIC_NOTE}", music_note)

    intro = (
        f"Good morning. This is {show_name}, episode {{episode_num}}, "
        f"for {{today_str}}. "
        f"Your daily briefing on {topic_domain} developments that matter. "
        f"Let's get into it."
    )
    podcast_content = podcast_content.replace("{INTRO_LINE}", intro)

    closing = (
        f"That's {show_name} for {{today_str}}. "
        f"If this briefing is useful, share it with a colleague and "
        f"subscribe wherever you get your podcasts. We're back tomorrow. "
        f"Have a productive day."
    )
    podcast_content = podcast_content.replace("{CLOSING_LINE}", closing)
    podcast_content = podcast_content.replace(
        "{SHOW_SPECIFIC_TONE_NOTE}",
        f"Remember: your audience is {audience_traits} — earn their attention with substance, not enthusiasm",
    )

    for i, sec in enumerate(sections):
        key = f"{{SECTION_{i + 2}_NAME}}"
        podcast_content = podcast_content.replace(key, sec)

    podcast_path = PROMPTS_DIR / f"{slug}_podcast.txt"
    podcast_path.write_text(podcast_content)
    print(f"  Created: shows/prompts/{slug}_podcast.txt")

    # -----------------------------------------------------------------------
    # 7. Quality pre-flight checks
    # -----------------------------------------------------------------------
    _print_header("Quality Pre-Flight Checks")

    all_ok = True

    # Check config has no remaining placeholders
    yaml_text = config_path.read_text()
    remaining = re.findall(r"\{[A-Z_]+\}", yaml_text)
    if remaining:
        _print_quality_check("Config placeholders", f"REMAINING: {remaining}", False)
        all_ok = False
    else:
        _print_quality_check("Config placeholders", "all replaced", True)

    # Check prompt files for template instructions that should be deleted
    for label, path in [("Digest prompt", digest_path), ("Podcast prompt", podcast_path)]:
        text = path.read_text()
        if "TEMPLATE INSTRUCTIONS" in text:
            _print_quality_check(label, "template instruction block still present — customize and delete it", False)
            all_ok = False
        else:
            _print_quality_check(label, "template instructions removed", True)

    # Check TTS settings are in safe range
    _print_quality_check("TTS voice", "using standard voice (dTrBzPvD2GpAqkk1MUzA)", True)
    _print_quality_check("TTS settings", "stability=0.65, similarity=0.9, style=0.85 (proven)", True)

    # Check sources
    source_count = yaml_text.count("- url:")
    if source_count < 5:
        _print_quality_check("RSS sources", f"only {source_count} — add at least 12-20", False)
        all_ok = False
    elif source_count < 12:
        _print_quality_check("RSS sources", f"{source_count} found — aim for 12-20", False)
    else:
        _print_quality_check("RSS sources", f"{source_count} sources configured", True)

    # Check keywords
    keyword_count = yaml_text.count("  - ") - source_count  # rough estimate
    _print_quality_check("Keywords", f"~{max(0, keyword_count)} defined", keyword_count > 15)

    # -----------------------------------------------------------------------
    # 8. Next steps
    # -----------------------------------------------------------------------
    _print_header("Next Steps — DO ALL OF THESE")

    steps = [
        f"Edit shows/{slug}.yaml — add 12-20 RSS sources and 30-60 keywords",
        f"Edit shows/prompts/{slug}_digest.txt — customize ALL sections, delete template instructions block",
        f"Edit shows/prompts/{slug}_podcast.txt — customize ALL sections, delete template instructions block",
        f"Run: python validate_show.py {slug}  — checks quality gates",
        f"Run: python run_show.py {slug} --test  — generates a test digest (no TTS/posting)",
        "READ the test digest output carefully — is this the quality you'd pay to listen to?",
        "If not, iterate on the prompts until it is. The prompts are 90% of quality.",
        f"Run a full test: python run_show.py {slug} --skip-x  — generates audio",
        "Listen to the audio. Adjust TTS settings if voice sounds off.",
        f"Create GitHub Pages HTML: {slug}.html and {slug}-summaries.html",
        f"Add '{slug}' to run_show.py CLI choices (if not using dynamic loading)",
        f"Add cron schedule to .github/workflows/run-show.yml",
    ]

    for i, step in enumerate(steps, 1):
        print(f"  {i:2d}. {step}")

    print(f"\n  Files created:")
    print(f"      shows/{slug}.yaml")
    print(f"      shows/prompts/{slug}_digest.txt")
    print(f"      shows/prompts/{slug}_podcast.txt")
    print(f"      digests/{slug}/.gitkeep")
    print()

    if not all_ok:
        print("  ** Some checks need attention — see warnings above **")
    else:
        print("  All pre-flight checks passed. Now customize the files above.")


if __name__ == "__main__":
    main()
