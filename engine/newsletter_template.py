"""Wrap newsletter markdown with a branded HTML hero and footer.

Buttondown renders the ``body`` field as markdown but allows inline
HTML to pass through. We exploit that to wrap each show's
synthesized markdown content with:

  - A hero block at the top (show cover, name, tagline, date pill)
    in the show's brand colour.
  - A footer with "catch up on" CTAs (Listen / Watch on YouTube /
    Read on the blog) plus a tiny Nerra Network credit line.

Email-safe constraints driving the design:

  - Inline styles only — Outlook strips ``<style>`` blocks.
  - Tables for the hero + footer layout (more reliable than
    flexbox/grid in Gmail / Outlook 2019).
  - System font stack for body copy.
  - Hero image served from ``nerranetwork.com`` (already public).
  - All colours hex; no CSS custom properties.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# Network-level fallbacks if a per-show entry is missing a field.
_NETWORK_SITE = "https://nerranetwork.com"
_NETWORK_NAME = "Nerra Network"
_NETWORK_TAGLINE = (
    "Daily AI-narrated podcasts. Editorial by Patrick."
)
_DEFAULT_BRAND = "#7C5CFF"
_DEFAULT_BRAND_DARK = "#4338ca"


def _shows_yaml_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "shows"


def _load_show_branding(slug: str) -> Dict[str, str]:
    """Return the visual + link metadata for a show.

    Pulls primarily from ``generate_html.NETWORK_SHOWS`` (the
    canonical website branding source) and supplements with the YAML
    config for the YouTube playlist URL and newsletter tag. Returns
    safe defaults if anything is missing so the wrapper degrades
    gracefully rather than crashing the send.
    """
    out: Dict[str, str] = {
        "name": slug,
        "tagline": "",
        "show_page": _NETWORK_SITE,
        "summaries_page": _NETWORK_SITE,
        "blog_page": _NETWORK_SITE,
        "cover_url": "",
        "brand_color": _DEFAULT_BRAND,
        "brand_color_dark": _DEFAULT_BRAND_DARK,
        "rss_url": "",
        "youtube_playlist_url": "",
    }

    # Lazy import to avoid pulling jinja into engine layer at import
    # time — generate_html is the website-script layer.
    try:
        from generate_html import NETWORK_SHOWS  # type: ignore
    except Exception as exc:
        logger.warning("Could not import NETWORK_SHOWS: %s", exc)
        NETWORK_SHOWS = {}  # type: ignore

    cfg = (NETWORK_SHOWS or {}).get(slug, {})
    if cfg:
        out["name"] = cfg.get("name", out["name"])
        out["tagline"] = cfg.get("tagline", "")
        out["brand_color"] = cfg.get("brand_color", out["brand_color"])
        out["brand_color_dark"] = cfg.get(
            "brand_color_dark", out["brand_color"]
        )
        if cfg.get("podcast_image"):
            out["cover_url"] = f"{_NETWORK_SITE}/{cfg['podcast_image']}"
        if cfg.get("show_page"):
            out["show_page"] = f"{_NETWORK_SITE}/{cfg['show_page']}"
        if cfg.get("summaries_page"):
            out["summaries_page"] = f"{_NETWORK_SITE}/{cfg['summaries_page']}"
        if cfg.get("rss_file"):
            out["rss_url"] = f"{_NETWORK_SITE}/{cfg['rss_file']}"
        out["blog_page"] = f"{_NETWORK_SITE}/blog/{slug}/index.html"

    # YouTube playlist URL — read straight from the show YAML so we
    # don't double-source it. Fail-soft if the YAML is missing.
    try:
        import yaml as _yaml

        yaml_path = _shows_yaml_dir() / f"{slug}.yaml"
        if yaml_path.exists():
            data = _yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            yt = data.get("youtube") or {}
            playlist_id = (yt.get("podcast_playlist_id") or "").strip()
            if playlist_id:
                out["youtube_playlist_url"] = (
                    f"https://www.youtube.com/playlist?list={playlist_id}"
                )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("Could not read YouTube playlist for %s: %s", slug, exc)

    return out


def _format_week_pill(week_ending: Optional[datetime.date]) -> str:
    """Pretty week-range string for the hero pill."""
    if week_ending is None:
        week_ending = datetime.date.today()
    week_start = week_ending - datetime.timedelta(days=6)
    if week_start.month == week_ending.month:
        return (
            f"Weekly digest · {week_start.strftime('%b %-d')}–"
            f"{week_ending.strftime('%-d, %Y')}"
        )
    return (
        f"Weekly digest · {week_start.strftime('%b %-d')} – "
        f"{week_ending.strftime('%b %-d, %Y')}"
    )


def _format_date_pill(label: str, date: datetime.date) -> str:
    """Pretty single-date string for the hero pill (daily newsletter)."""
    return f"{label} · {date.strftime('%b %-d, %Y')}"


def _build_hero_html(show: Dict[str, str], pill_text: str) -> str:
    """Render the email's hero block as inline-styled HTML."""
    name = show["name"]
    tagline = show["tagline"]
    cover_url = show["cover_url"]
    brand = show["brand_color"]
    brand_dark = show["brand_color_dark"]

    cover_img = (
        f'<img src="{cover_url}" alt="{name} cover" '
        f'width="120" height="120" '
        f'style="display:block;border-radius:18px;width:120px;'
        f'height:120px;object-fit:cover;margin:0 auto 16px;'
        f'box-shadow:0 8px 24px rgba(0,0,0,0.25);" />'
        if cover_url else ""
    )

    return (
        f'<table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0" border="0" '
        f'style="background:linear-gradient(135deg,{brand} 0%,'
        f'{brand_dark} 100%);">'
        f'<tr><td align="center" '
        f'style="padding:40px 24px 32px;'
        f'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\','
        f'Roboto,Helvetica,Arial,sans-serif;">'
        f'{cover_img}'
        f'<h1 style="color:#ffffff;font-size:28px;font-weight:700;'
        f'margin:0 0 8px;line-height:1.2;letter-spacing:-0.01em;">'
        f'{name}</h1>'
        + (
            f'<p style="color:rgba(255,255,255,0.92);font-size:15px;'
            f'margin:0 0 20px;line-height:1.4;max-width:480px;">'
            f'{tagline}</p>'
            if tagline else ""
        )
        + f'<div style="display:inline-block;background:rgba(0,0,0,0.25);'
        f'color:#ffffff;font-size:12px;font-weight:600;'
        f'padding:6px 14px;border-radius:100px;'
        f'letter-spacing:0.04em;text-transform:uppercase;">'
        f'{pill_text}</div>'
        f'</td></tr></table>'
    )


def _build_footer_html(show: Dict[str, str]) -> str:
    """Render the email's footer block as inline-styled HTML."""
    brand = show["brand_color"]
    name = show["name"]

    def _btn(href: str, label: str) -> str:
        if not href:
            return ""
        return (
            f'<a href="{href}" '
            f'style="display:inline-block;background:{brand};'
            f'color:#ffffff;text-decoration:none;font-weight:600;'
            f'font-size:14px;padding:10px 18px;border-radius:8px;'
            f'margin:4px;font-family:-apple-system,BlinkMacSystemFont,'
            f'\'Segoe UI\',Roboto,Helvetica,Arial,sans-serif;">'
            f'{label}</a>'
        )

    listen = _btn(show["show_page"], "▶ Listen to the podcast")
    watch = _btn(show["youtube_playlist_url"], "📺 Watch on YouTube")
    blog = _btn(show["blog_page"], "📝 Read the blog")

    return (
        f'<table role="presentation" width="100%" cellpadding="0" '
        f'cellspacing="0" border="0" '
        f'style="background:#fafafa;border-top:4px solid {brand};">'
        f'<tr><td align="center" '
        f'style="padding:32px 24px;'
        f'font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\','
        f'Roboto,Helvetica,Arial,sans-serif;color:#0f172a;">'
        f'<p style="font-size:14px;color:#475569;margin:0 0 16px;">'
        f'Catch up on more {name}:'
        f'</p>'
        f'<div style="line-height:1.8;">'
        f'{listen}{watch}{blog}'
        f'</div>'
        f'<p style="font-size:12px;color:#94a3b8;margin:24px 0 4px;'
        f'line-height:1.5;">'
        f'<a href="{_NETWORK_SITE}" '
        f'style="color:#475569;text-decoration:none;font-weight:600;">'
        f'Nerra Network</a> · '
        f'AI-narrated voice (ElevenLabs) · '
        f'Editorial by Patrick'
        f'</p>'
        f'<p style="font-size:11px;color:#cbd5e1;margin:0;line-height:1.5;">'
        f'You\'re receiving this because you subscribed to {name} on '
        f'<a href="{_NETWORK_SITE}" '
        f'style="color:#94a3b8;text-decoration:underline;">'
        f'nerranetwork.com</a>.'
        f'</p>'
        f'</td></tr></table>'
    )


def wrap_with_branding(
    slug: str,
    markdown_body: str,
    *,
    week_ending: Optional[datetime.date] = None,
    daily_label: Optional[str] = None,
    daily_date: Optional[datetime.date] = None,
) -> str:
    """Wrap *markdown_body* with a branded hero and footer.

    The result is a single string suitable for Buttondown's email
    body — markdown in the middle is left untouched, and the inline
    HTML at top/bottom passes through Buttondown's renderer.

    Pass *week_ending* for weekly newsletters; pass *daily_label* +
    *daily_date* for daily episode newsletters. If neither is set,
    the hero pill falls back to today's date.
    """
    show = _load_show_branding(slug)

    if week_ending is not None:
        pill = _format_week_pill(week_ending)
    elif daily_date is not None:
        pill = _format_date_pill(daily_label or "Today", daily_date)
    else:
        pill = _format_week_pill(None)

    hero = _build_hero_html(show, pill)
    footer = _build_footer_html(show)

    # Two blank lines between blocks so markdown processors treat
    # them as separate sections.
    return f"{hero}\n\n{markdown_body.strip()}\n\n{footer}\n"
