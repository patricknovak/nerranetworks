"""Tests for the branded newsletter HTML wrapper.

Pure-string output tests — they don't render to email, just confirm
the structure of the inline HTML so a future change can't quietly
remove the hero/footer or break the per-show branding.
"""

from __future__ import annotations

import datetime

from engine import newsletter_template as nt


# ---------------------------------------------------------------------------
# Per-show branding lookup
# ---------------------------------------------------------------------------

def test_load_show_branding_uses_network_shows_for_known_slug():
    show = nt._load_show_branding("tesla")
    # Pulled straight from generate_html.NETWORK_SHOWS["tesla"].
    assert show["name"] == "Tesla Shorts Time"
    assert show["brand_color"].startswith("#")
    assert show["cover_url"].endswith(".jpg") or show["cover_url"].endswith(".webp")
    assert show["show_page"].startswith("https://nerranetwork.com/")
    # YouTube playlist URL pulled from the show YAML.
    assert show["youtube_playlist_url"].startswith(
        "https://www.youtube.com/playlist?list="
    )


def test_load_show_branding_falls_back_for_unknown_slug():
    show = nt._load_show_branding("not-a-real-show")
    assert show["name"] == "not-a-real-show"
    assert show["brand_color"].startswith("#")
    # No crash, no exceptions, just safe defaults.


# ---------------------------------------------------------------------------
# Date pill formatting
# ---------------------------------------------------------------------------

def test_week_pill_same_month():
    out = nt._format_week_pill(datetime.date(2026, 4, 30))
    # Apr 24 → Apr 30 should collapse to one month label.
    assert "Apr" in out
    assert "Weekly digest" in out


def test_week_pill_cross_month():
    out = nt._format_week_pill(datetime.date(2026, 5, 4))
    # Apr 28 → May 4 spans months.
    assert "Apr" in out and "May" in out


def test_daily_pill_format():
    out = nt._format_date_pill("Ep 42", datetime.date(2026, 4, 30))
    assert "Ep 42" in out
    assert "Apr" in out
    assert "2026" in out


# ---------------------------------------------------------------------------
# Hero + footer rendering
# ---------------------------------------------------------------------------

def test_hero_html_includes_show_name_and_brand_color():
    show = nt._load_show_branding("tesla")
    pill = "Weekly digest · Apr 24–30, 2026"
    hero = nt._build_hero_html(show, pill)
    assert "Tesla Shorts Time" in hero
    assert show["brand_color"] in hero
    assert pill in hero
    # The cover image renders (real Tesla cover exists).
    assert "<img" in hero and show["cover_url"] in hero


def test_hero_html_omits_image_when_cover_missing():
    show = dict(nt._load_show_branding("not-a-real-show"))
    show["cover_url"] = ""
    hero = nt._build_hero_html(show, "Weekly digest · Test")
    assert "<img" not in hero


def test_footer_html_renders_buttons_when_links_exist():
    show = nt._load_show_branding("tesla")
    footer = nt._build_footer_html(show)
    assert "Listen to the podcast" in footer
    assert "Watch on YouTube" in footer
    assert "Read the blog" in footer
    assert "Nerra Network" in footer
    # Brand color appears as the button background + top border.
    assert show["brand_color"] in footer


def test_footer_html_omits_youtube_when_playlist_missing():
    show = dict(nt._load_show_branding("tesla"))
    show["youtube_playlist_url"] = ""
    footer = nt._build_footer_html(show)
    assert "Watch on YouTube" not in footer
    # But the other CTAs still render.
    assert "Listen to the podcast" in footer


# ---------------------------------------------------------------------------
# Top-level wrap_with_branding
# ---------------------------------------------------------------------------

def test_wrap_with_branding_weekly_keeps_markdown_in_middle():
    body_md = "## This week\n\nA paragraph with **bold** text."
    out = nt.wrap_with_branding(
        "tesla", body_md,
        week_ending=datetime.date(2026, 4, 30),
    )
    # Hero appears before the markdown.
    hero_idx = out.find("Tesla Shorts Time")
    body_idx = out.find("## This week")
    footer_idx = out.find("Listen to the podcast")
    assert 0 <= hero_idx < body_idx < footer_idx
    # The original markdown is preserved verbatim (no transformation).
    assert body_md in out


def test_wrap_with_branding_daily_uses_episode_pill():
    out = nt.wrap_with_branding(
        "tesla", "Body text here.",
        daily_label="Ep 100",
        daily_date=datetime.date(2026, 4, 30),
    )
    assert "Ep 100" in out


def test_wrap_with_branding_falls_back_when_no_dates():
    """No dates passed → use today's date for the hero pill (don't
    crash)."""
    out = nt.wrap_with_branding("tesla", "Body.")
    assert "Tesla Shorts Time" in out  # hero rendered
    assert "Body." in out               # body preserved


def test_wrap_with_branding_renders_for_russian_show():
    """Cyrillic show display names should render unchanged."""
    out = nt.wrap_with_branding(
        "privet_russian", "## Урок 1\n\nПривет!",
        week_ending=datetime.date(2026, 4, 30),
    )
    assert "Привет, Русский!" in out
    assert "Урок 1" in out