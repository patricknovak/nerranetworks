#!/usr/bin/env python3
"""Generate static HTML pages for the Nerra Network podcast shows.

Uses Jinja2 templates to produce show pages and summaries pages,
replacing ~3,900 lines of hand-maintained HTML with data-driven output.

Usage:
    python generate_html.py --all           # Generate everything (default)
    python generate_html.py --summaries     # Generate summaries pages only
    python generate_html.py --dry-run       # Preview without writing files
    python generate_html.py --show tesla    # Generate pages for one show
"""

import argparse
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).resolve().parent
TEMPLATES_DIR = ROOT / "templates"
GITHUB_RAW = "https://nerranetwork.com"

# ---------------------------------------------------------------------------
# Per-show configuration
# ---------------------------------------------------------------------------

NETWORK_SHOWS = {
    "tesla": {
        "name": "Tesla Shorts Time",
        "slug": "tesla",
        "description": "Daily Tesla news digest and podcast.",
        "show_page": "index.html",
        "summaries_page": "tesla-summaries.html",
        "json_path": "digests/tesla_shorts_time/summaries_tesla.json",
        "json_format": "wrapped",
        "rss_file": "podcast.rss",
        "podcast_image": "podcast-image.jpg",
        "x_account": "teslashortstime",
        "colors": {
            "primary": "#E31937",
            "primary_dark": "#C4122E",
            "accent": "#CCD6F6",
            "bg": "#000000",
            "bg_alt": "#1a1a2e",
            "card": "#1a1a1a",
            "text": "#ffffff",
            "text_light": "#cccccc",
            "border_subtle": "rgba(255,255,255,0.18)",
            "header_bg": "rgba(0, 0, 0, 0.95)",
        },
        "google_fonts_params": "family=Orbitron:wght@400;700;900&family=Rajdhani:wght@400;600;700&family=Inter:wght@400;500;600&family=Roboto:wght@400;500;700",
        "heading_font": "'Orbitron', sans-serif",
        "body_font": "'Inter', 'Roboto', -apple-system, BlinkMacSystemFont, sans-serif",
        "logo_weight": 900,
        "logo_emoji": "⚡",
        "logo_text": "TS",
        "favicon_svg": "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>⚡</text></svg>",
        "theme_color": "#E31937",
        "meta_description": "Daily Tesla Shorts Time summaries - complete archives of Tesla news, mission updates, and sustainable energy progress.",
        "meta_keywords": "Tesla podcast summaries, TSLA news, Tesla stock, EV analysis, Tesla Shorts Time, daily digests",
        "hero_title": "Tesla Shorts Time Daily",
        "hero_tagline": "Complete Archive of Daily Digests",
        "hero_subtitle": "Full daily summaries of Tesla news, mission updates, and sustainable energy progress",
        "hero_bg": "linear-gradient(135deg, var(--bg) 0%, #1a1a2e 100%)",
        "hero_h1_gradient": "linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%)",
        "section_title": "Tesla Shorts Time Daily Summaries",
        "nav_links": [
            {"href": "index.html#episodes", "label": "Episodes"},
            {"href": "index.html#highlights", "label": "Highlights"},
            {"href": "index.html#news", "label": "News"},
            {"href": "tesla-summaries.html", "label": "Summaries"},
            {"href": "podcasts/", "label": "All Podcasts"},
            {"href": "index.html#about", "label": "About"},
        ],
        "footer_links": [
            {"href": "index.html#episodes", "label": "🎧 Episodes"},
            {"href": f"{GITHUB_RAW}/podcast.rss", "label": "📡 RSS Feed", "target": "_blank"},
            {"href": "https://x.com/teslashortstime", "label": "🐦 X / Twitter", "target": "_blank"},
            {"href": "podcasts/", "label": "🌐 All Podcasts"},
            {"href": "https://github.com/patricknovak/Tesla-shorts-time", "label": "💻 GitHub", "target": "_blank"},
        ],
        "footer_copyright": "Tesla Shorts Time Daily © 2025 | Hosted by Dan and Patrick",
        "footer_tagline": "⚡ Keep accelerating! ⚡",
    },
    "omni_view": {
        "name": "Omni View",
        "slug": "omni_view",
        "description": "Daily balanced news summaries from diverse sources.",
        "show_page": "omni-view.html",
        "summaries_page": "omni-view-summaries.html",
        "json_path": "digests/omni_view/summaries_omni.json",
        "json_format": "wrapped",
        "rss_file": "omni_view_podcast.rss",
        "podcast_image": "omni-view-podcast-image.jpg",
        "x_account": "omniviewnews",
        "colors": {
            "primary": "#0B6FD6",
            "primary_dark": "#0B1B3B",
            "accent": "rgba(191, 232, 255, 0.85)",
            "bg": "#F4F8FF",
            "bg_alt": "#F4F8FF",
            "card": "#ffffff",
            "text": "#0B1B3B",
            "text_light": "rgba(11, 27, 59, 0.62)",
            "border_subtle": "rgba(11, 27, 59, 0.18)",
            "header_bg": "rgba(255, 255, 255, 0.95)",
        },
        "google_fonts_params": "family=Inter:wght@400;500;600;700&family=Crimson+Text:wght@400;600",
        "heading_font": "'Crimson Text', serif",
        "body_font": "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
        "logo_weight": 600,
        "favicon_svg": "assets/omni-view-logo.svg",
        "theme_color": "#0B6FD6",
        "meta_description": "Omni View - Daily balanced news summaries from diverse sources. Multiple perspectives on the stories that matter.",
        "meta_keywords": "balanced news, diverse perspectives, media literacy, news analysis, unbiased reporting, multiple viewpoints",
        "hero_title": "Omni View",
        "hero_tagline": "Balanced Perspectives on the News",
        "hero_subtitle": "Daily summaries presenting multiple viewpoints on the stories that matter, helping you form your own informed opinions.",
        "hero_bg": "linear-gradient(135deg, var(--bg) 0%, #E8F0FE 100%)",
        "hero_h1_gradient": "linear-gradient(135deg, var(--primary) 0%, #3498DB 100%)",
        "section_title": "Daily News Summaries",
        "extra_head_links": [
            'rel="stylesheet" href="assets/omni-view-theme.css"',
        ],
        "nav_links": [
            {"href": "omni-view-summaries.html", "label": "Summaries"},
            {"href": "omni-view.html#episodes", "label": "Episodes"},
            {"href": "podcasts/", "label": "All Podcasts"},
            {"href": "omni-view.html#about", "label": "About"},
            {"href": "omni-view.html#subscribe", "label": "Subscribe"},
        ],
        "footer_links": [
            {"href": "omni-view.html#episodes", "label": "🎧 Episodes"},
            {"href": f"{GITHUB_RAW}/omni_view_podcast.rss", "label": "📡 RSS Feed", "target": "_blank"},
            {"href": "https://x.com/omniviewnews", "label": "🐦 X / Twitter", "target": "_blank"},
            {"href": "podcasts/", "label": "🌐 All Podcasts"},
            {"href": "https://github.com/patricknovak/Tesla-shorts-time", "label": "💻 Source", "target": "_blank"},
        ],
        "footer_copyright": "Omni View © 2025 | Promoting media literacy through balanced perspectives",
        "footer_tagline": "Stay informed • Think critically • Form your own opinions",
        # TODO: Add Apple Podcasts / Spotify links once submitted
    },
    "fascinating_frontiers": {
        "name": "Fascinating Frontiers",
        "slug": "fascinating_frontiers",
        "description": "Daily space and astronomy news digest.",
        "show_page": "fascinating_frontiers.html",
        "summaries_page": "fascinating-frontiers-summaries.html",
        "json_path": "digests/fascinating_frontiers/summaries_space.json",
        "json_format": "wrapped",
        "rss_file": "fascinating_frontiers_podcast.rss",
        "podcast_image": "Fascinating%20Frontiers-3000x3000.jpg",
        "x_account": "planetterrian",
        "colors": {
            "primary": "#06b6d4",
            "primary_dark": "#6366f1",
            "accent": "#6366f1",
            "bg": "#0f172a",
            "bg_alt": "#1e293b",
            "card": "#1e293b",
            "text": "#ffffff",
            "text_light": "#cbd5e1",
            "border_subtle": "rgba(255,255,255,0.18)",
            "header_bg": "rgba(15, 23, 42, 0.95)",
        },
        "google_fonts_params": "family=Inter:wght@400;500;600;700&family=Montserrat:wght@400;600;700;800;900",
        "heading_font": "'Montserrat', sans-serif",
        "body_font": "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
        "logo_weight": 800,
        "logo_uppercase": True,
        "theme_color": "#06b6d4",
        "meta_description": "Daily Fascinating Frontiers summaries - complete archives of space and astronomy news.",
        "meta_keywords": "space podcast summaries, astronomy news, NASA discoveries, space exploration, Fascinating Frontiers",
        "hero_title": "Fascinating Frontiers",
        "hero_tagline": "Complete Archive of Space & Astronomy Digests",
        "hero_subtitle": "Full daily summaries of space missions, astronomical discoveries, and cosmic phenomena",
        "hero_bg": "radial-gradient(ellipse at center, #1e293b 0%, #0f172a 100%)",
        "hero_h1_gradient": "linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%)",
        "hero_before_css": (
            "content: '';"
            "position: absolute; top: 0; left: 0; right: 0; bottom: 0;"
            "background-image:"
            "  radial-gradient(2px 2px at 20px 30px, #ffffff, transparent),"
            "  radial-gradient(2px 2px at 40px 70px, rgba(255,255,255,0.8), transparent),"
            "  radial-gradient(1px 1px at 90px 40px, #ffffff, transparent),"
            "  radial-gradient(1px 1px at 130px 80px, rgba(255,255,255,0.6), transparent),"
            "  radial-gradient(2px 2px at 160px 30px, #ffffff, transparent);"
            "background-repeat: repeat;"
            "background-size: 200px 100px;"
            "animation: twinkle 4s ease-in-out infinite alternate;"
            "opacity: 0.6;"
        ),
        "extra_css": (
            "@keyframes twinkle { 0% { opacity: 0.3; } 100% { opacity: 0.8; } }"
        ),
        "section_title": "Fascinating Frontiers Space Summaries",
        "nav_links": [
            {"href": "fascinating_frontiers.html#episodes", "label": "Episodes"},
            {"href": "fascinating_frontiers.html#about", "label": "About"},
            {"href": "fascinating-frontiers-summaries.html", "label": "Summaries"},
            {"href": "podcasts/", "label": "All Podcasts"},
            {"href": "fascinating_frontiers.html#subscribe", "label": "Subscribe"},
        ],
        "footer_links": [
            {"href": "fascinating_frontiers.html#episodes", "label": "🎧 Episodes"},
            {"href": f"{GITHUB_RAW}/fascinating_frontiers_podcast.rss", "label": "📡 RSS Feed", "target": "_blank"},
            {"href": "https://x.com/planetterrian", "label": "🐦 X / Twitter", "target": "_blank"},
            {"href": "https://github.com/patricknovak/Tesla-shorts-time/tree/main/digests/fascinating_frontiers", "label": "📚 Archive", "target": "_blank"},
            {"href": "podcasts/", "label": "🌐 All Podcasts"},
            {"href": "https://github.com/patricknovak/Tesla-shorts-time", "label": "💻 Source", "target": "_blank"},
        ],
        "footer_copyright": "Fascinating Frontiers © 2025 | Exploring the wonders of space and astronomy",
        "footer_tagline": "🚀🌌 Bringing the cosmos to your ears 🚀🌌",
        # TODO: Add Apple Podcasts / Spotify links once submitted
    },
    "planetterrian": {
        "name": "Planetterrian Daily",
        "slug": "planetterrian",
        "description": "Daily science, longevity, and health discoveries.",
        "show_page": "planetterrian.html",
        "summaries_page": "planetterrian-summaries.html",
        "json_path": "digests/planetterrian/summaries_planet.json",
        "json_format": "wrapped",
        "rss_file": "planetterrian_podcast.rss",
        "podcast_image": "planetterrian-podcast-image.jpg",
        "x_account": "planetterrian",
        "hero_logo_url": f"{GITHUB_RAW}/PlanetTerrian%20logo%20only%20final.jpg",
        "colors": {
            "primary": "#35B5C4",
            "primary_dark": "#018DB1",
            "accent": "#F2D20D",
            "bg": "#0a1929",
            "bg_alt": "#1a2332",
            "card": "#1a2332",
            "text": "#ffffff",
            "text_light": "#b0bec5",
            "border_subtle": "rgba(255,255,255,0.18)",
            "header_bg": "rgba(10, 25, 41, 0.95)",
        },
        "google_fonts_params": "family=Inter:wght@400;500;600;700&family=Montserrat:wght@400;600;700;800;900",
        "heading_font": "'Montserrat', sans-serif",
        "body_font": "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
        "logo_weight": 800,
        "logo_uppercase": True,
        "logo_html": (
            '<img src="https://nerranetwork.com/PlanetTerrian%20logo%20only%20final.jpg" '
            'alt="Planetterrian Logo" style="height:50px;width:auto;border-radius:8px;" onerror="this.style.display=\'none\'">'
            '<span style="font-family:Montserrat,sans-serif;font-weight:800;text-transform:uppercase;letter-spacing:0.05em;">PLANETTERRIAN</span>'
        ),
        "theme_color": "#35B5C4",
        "meta_description": "Daily Planetterrian Daily summaries - complete archives of science, longevity, and health discoveries.",
        "meta_keywords": "science podcast summaries, longevity research, health discoveries, Planetterrian Daily, biotech news",
        "hero_title": "Planetterrian Daily",
        "hero_tagline": "Complete Archive of Science & Health Digests",
        "hero_subtitle": "Full daily summaries of science, longevity, and health discoveries",
        "hero_bg": "linear-gradient(135deg, var(--bg) 0%, #1a2332 100%)",
        "hero_h1_gradient": "linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%)",
        "hero_before_css": (
            "content: '';"
            "position: absolute; top: 0; left: 0; right: 0; bottom: 0;"
            "background: radial-gradient(circle at 30% 20%, rgba(1, 141, 177, 0.12) 0%, transparent 55%),"
            "            radial-gradient(circle at 70% 80%, rgba(242, 210, 13, 0.10) 0%, transparent 55%);"
            "pointer-events: none;"
        ),
        "section_title": "Planetterrian Daily Science Summaries",
        "nav_links": [
            {"href": "planetterrian.html#episodes", "label": "Episodes"},
            {"href": "planetterrian.html#about", "label": "About"},
            {"href": "planetterrian-summaries.html", "label": "Summaries"},
            {"href": "podcasts/", "label": "All Podcasts"},
            {"href": "planetterrian.html#subscribe", "label": "Subscribe"},
        ],
        "footer_links": [
            {"href": "planetterrian.html#episodes", "label": "🎧 Episodes"},
            {"href": f"{GITHUB_RAW}/planetterrian_podcast.rss", "label": "📡 RSS Feed", "target": "_blank"},
            {"href": "https://x.com/planetterrian", "label": "🐦 X / Twitter", "target": "_blank"},
            {"href": "https://github.com/patricknovak/Tesla-shorts-time/tree/main/digests/planetterrian", "label": "📚 Archive", "target": "_blank"},
            {"href": "podcasts/", "label": "🌐 All Podcasts"},
            {"href": "https://github.com/patricknovak/Tesla-shorts-time", "label": "💻 Source", "target": "_blank"},
        ],
        "footer_copyright": "Planetterrian Daily © 2025 | A tribe of forward-thinking innovators",
        "footer_tagline": "🌍 Intertwining technology and compassion for the planet 🌍",
        # TODO: Add Apple Podcasts / Spotify links once submitted
    },
    "env_intel": {
        "name": "Environmental Intelligence",
        "slug": "env_intel",
        "description": "Daily environmental regulatory and compliance briefing.",
        "show_page": "env-intel.html",
        "summaries_page": "env-intel-summaries.html",
        "json_path": "digests/env_intel/summaries_env_intel.json",
        "json_format": "array",
        "rss_file": "env_intel_podcast.rss",
        "podcast_image": "env-intel-podcast-image.jpg",
        "x_account": "teslashortstime",
        "colors": {
            "primary": "#1B5E20",
            "primary_dark": "#0D3B0F",
            "accent": "#4CAF50",
            "bg": "#0a1a0a",
            "bg_alt": "#142214",
            "card": "#1a2e1a",
            "text": "#ffffff",
            "text_light": "#a5c4a5",
            "border_subtle": "rgba(255,255,255,0.18)",
            "header_bg": "rgba(10, 26, 10, 0.95)",
        },
        "google_fonts_params": "family=Inter:wght@400;500;600;700&family=Montserrat:wght@400;600;700;800",
        "heading_font": "'Montserrat', sans-serif",
        "body_font": "'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
        "logo_weight": 800,
        "logo_emoji": "🔬",
        "theme_color": "#1B5E20",
        "meta_description": "Environmental Intelligence - Written briefing summaries for environmental professionals.",
        "meta_keywords": "environmental intelligence, regulatory compliance, environmental briefings, Canadian environment, BC environment",
        "hero_title": "Environmental Intelligence",
        "hero_tagline": "Briefing Summaries Archive",
        "hero_subtitle": "Written summaries of daily environmental regulatory and compliance briefings.",
        "hero_bg": "linear-gradient(135deg, var(--bg) 0%, #142214 100%)",
        "hero_h1_gradient": "linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%)",
        "section_title": "Environmental Intelligence Briefings",
        "nav_links": [
            {"href": "env-intel.html", "label": "Podcast Player"},
            {"href": "env-intel-summaries.html", "label": "Summaries"},
            {"href": "podcasts/", "label": "All Podcasts"},
        ],
        "footer_links": [
            {"href": "env-intel.html", "label": "🎧 Podcast Player"},
            {"href": "env_intel_podcast.rss", "label": "📡 RSS Feed"},
            {"href": "podcasts/", "label": "🌐 All Podcasts"},
            {"href": "https://github.com/patricknovak/Tesla-shorts-time", "label": "💻 Source", "target": "_blank"},
        ],
        "footer_copyright": "Environmental Intelligence © 2025 | Nerra Network",
        # TODO: Add Apple Podcasts / Spotify links once submitted
    },
    "models_agents": {
        "name": "Models & Agents",
        "slug": "models_agents",
        "description": "Daily AI briefing on models, agent frameworks, and practical AI.",
        "show_page": "models-agents.html",
        "summaries_page": "models-agents-summaries.html",
        "json_path": "digests/models_agents/summaries_models_agents.json",
        "json_format": "wrapped",
        "rss_file": "models_agents_podcast.rss",
        "podcast_image": "models-agents-podcast-image.jpg",
        "x_account": None,
        "colors": {
            "primary": "#8B5CF6",
            "primary_dark": "#6D28D9",
            "accent": "#06B6D4",
            "bg": "#0B0D1A",
            "bg_alt": "#12152A",
            "card": "#12152A",
            "text": "#ffffff",
            "text_light": "#8B8FAE",
            "border_subtle": "#1E2140",
            "header_bg": "rgba(11, 13, 26, 0.95)",
        },
        "google_fonts_params": "family=Inter:wght@400;500;600;700&family=Montserrat:wght@400;600;700;800",
        "heading_font": "'Montserrat', sans-serif",
        "body_font": "-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif",
        "logo_weight": 800,
        "theme_color": "#8B5CF6",
        "meta_description": "Models & Agents - Written briefing summaries on AI models, agent frameworks, and practical AI developments.",
        "meta_keywords": "AI models, agent frameworks, LLM news, AI briefings, Models and Agents",
        "hero_title": "Models & Agents",
        "hero_tagline": "Briefing Summaries Archive",
        "hero_subtitle": "Written summaries of daily AI model and agent development briefings.",
        "hero_bg": "linear-gradient(135deg, var(--bg) 0%, #12152A 100%)",
        "hero_h1_gradient": "linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%)",
        "section_title": "Models & Agents Briefings",
        "nav_links": [
            {"href": "models-agents.html", "label": "Podcast Player"},
            {"href": "models-agents-summaries.html", "label": "Summaries"},
            {"href": "network.html", "label": "Nerra Network"},
            {"href": "podcasts/", "label": "All Podcasts"},
        ],
        "footer_links": [
            {"href": "models-agents.html", "label": "🎧 Podcast Player"},
            {"href": "models_agents_podcast.rss", "label": "📡 RSS Feed"},
            {"href": "network.html", "label": "🌐 Nerra Network"},
            {"href": "https://github.com/patricknovak/Tesla-shorts-time", "label": "💻 Source", "target": "_blank"},
        ],
        "footer_copyright": "Models & Agents © 2025 | Nerra Network",
        # TODO: Add Apple Podcasts / Spotify links once submitted
    },
}


def _build_network_list():
    """Build a minimal list of all shows for the footer cross-links."""
    return [
        {"name": cfg["name"], "slug": cfg["slug"], "summaries_page": cfg["summaries_page"]}
        for cfg in NETWORK_SHOWS.values()
    ]


def generate_summaries_page(slug, *, dry_run=False):
    """Render and write a summaries page for a single show.

    Returns the output path (or None if dry_run).
    """
    cfg = NETWORK_SHOWS[slug]

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
        keep_trailing_newline=True,
    )
    template = env.get_template("summaries_page.html.j2")

    # Build podcast logo URL
    podcast_logo_url = None
    if cfg.get("podcast_image"):
        podcast_logo_url = f"{GITHUB_RAW}/{cfg['podcast_image']}"

    context = {
        **cfg,
        "show_name": cfg["name"],
        "page_title": f"{cfg['name']} | Summaries",
        "podcast_logo_url": podcast_logo_url,
        "og_image": podcast_logo_url,
        "network_shows": _build_network_list(),
        "extra_head_links": cfg.get("extra_head_links", []),
    }

    html = template.render(**context)

    out_path = ROOT / cfg["summaries_page"]
    if dry_run:
        print(f"[dry-run] Would write {out_path} ({len(html):,} bytes)")
        return None

    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({len(html):,} bytes)")
    return out_path


def generate_all_summaries(*, dry_run=False):
    """Generate summaries pages for every show."""
    paths = []
    for slug in NETWORK_SHOWS:
        result = generate_summaries_page(slug, dry_run=dry_run)
        if result:
            paths.append(result)
    return paths


def main():
    parser = argparse.ArgumentParser(
        description="Generate static HTML pages for the Nerra Network."
    )
    parser.add_argument(
        "--summaries",
        action="store_true",
        help="Generate summaries pages",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Generate all pages (default if no flags given)",
    )
    parser.add_argument(
        "--show",
        type=str,
        help="Generate pages for a specific show slug (e.g. tesla, omni_view)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview output without writing files",
    )

    args = parser.parse_args()

    # Default to --all if no specific flag
    if not args.summaries and not args.all and not args.show:
        args.all = True

    if args.show:
        if args.show not in NETWORK_SHOWS:
            print(f"Error: unknown show '{args.show}'. Valid: {', '.join(NETWORK_SHOWS)}", file=sys.stderr)
            sys.exit(1)
        generate_summaries_page(args.show, dry_run=args.dry_run)
        return

    if args.all or args.summaries:
        generate_all_summaries(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
