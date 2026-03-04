#!/usr/bin/env python3
"""Generate static HTML pages for the Nerra Network podcast shows.

Uses Jinja2 templates to produce show pages, summaries pages, and the
network landing page — all sharing a common base template and CSS.

Usage:
    python generate_html.py --all           # Generate everything (default)
    python generate_html.py --summaries     # Generate summaries pages only
    python generate_html.py --shows         # Generate show pages only
    python generate_html.py --network       # Generate network page only
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
        "brand_color": "#E31937",
        "brand_color_dark": "#C4122E",
        "tagline": "Shorting Tesla? Time's Up.",
        "hero_tagline": "Shorting Tesla? Time's Up.",
        "about_text": "Tesla Shorts Time is a daily podcast delivering the most important Tesla news and developments. We focus on how Tesla is advancing its mission to accelerate the world's transition to sustainable energy, saving lives through safer vehicles, and making the world a better place.",
        "about_host": "Hosted by Patrick, each episode covers breaking news, product updates, technology breakthroughs, and the latest developments from Tesla and the broader electric vehicle world.",
        "apple_podcasts_url": "https://podcasts.apple.com/us/podcast/tesla-shorts-time/id1855142939",
        "theme_color": "#E31937",
        "meta_description": "Daily Tesla Shorts Time podcast — Tesla news, TSLA stock, FSD updates, and sustainable energy progress.",
        "meta_keywords": "Tesla podcast, TSLA news, Tesla stock, EV analysis, Tesla Shorts Time, daily digests",
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
        "brand_color": "#0B6FD6",
        "brand_color_dark": "#0B1B3B",
        "tagline": "See every side. Decide for yourself.",
        "hero_tagline": "See every side. Decide for yourself.",
        "about_text": "Omni View is a neutral, media-literacy-first daily briefing designed for everyone from children to seniors. Covers top world, business, technology, and media stories with perspectives from across the political spectrum.",
        "about_host": "Helping you form your own informed opinions through balanced, multi-perspective coverage.",
        "apple_podcasts_url": None,
        "theme_color": "#0B6FD6",
        "meta_description": "Omni View — Daily balanced news summaries from diverse sources. Multiple perspectives on the stories that matter.",
        "meta_keywords": "balanced news, diverse perspectives, media literacy, news analysis, unbiased reporting",
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
        "podcast_image": "Fascinating Frontiers-3000x3000.jpg",
        "x_account": "planetterrian",
        "brand_color": "#7C5CFF",
        "brand_color_dark": "#6366f1",
        "tagline": "Journey to the stars with today's discoveries.",
        "hero_tagline": "Journey to the stars with today's discoveries.",
        "about_text": "Daily space and astronomy news covering mission updates, cosmic discoveries, exoplanet breakthroughs, and rocket launches. From NASA and ESA to SpaceX and beyond.",
        "about_host": "Hosted by Patrick in Vancouver, bringing the cosmos to your ears.",
        "apple_podcasts_url": None,
        "theme_color": "#7C5CFF",
        "meta_description": "Fascinating Frontiers — Daily space and astronomy news podcast. Mission updates, cosmic discoveries, and rocket launches.",
        "meta_keywords": "space podcast, astronomy news, NASA discoveries, space exploration, Fascinating Frontiers",
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
        "brand_color": "#018DB1",
        "brand_color_dark": "#35B5C4",
        "tagline": "Science, longevity, and the frontier of human health.",
        "hero_tagline": "Science, longevity, and the frontier of human health.",
        "about_text": "Daily discoveries in longevity science, genetics, biotech, CRISPR, neuroscience, and health research. If it could extend your healthspan or change medicine, we cover it.",
        "about_host": "Hosted by Patrick in Vancouver. A tribe of forward-thinking innovators.",
        "apple_podcasts_url": None,
        "theme_color": "#018DB1",
        "meta_description": "Planetterrian Daily — Science, longevity, and health discoveries. Genetics, biotech, CRISPR, and more.",
        "meta_keywords": "science podcast, longevity research, health discoveries, Planetterrian Daily, biotech news",
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
        "brand_color": "#1B5E20",
        "brand_color_dark": "#0D3B0F",
        "tagline": "Daily environmental regulatory and compliance briefing.",
        "hero_tagline": "Daily environmental regulatory and compliance briefing.",
        "about_text": "Environmental regulatory, science, and compliance briefing for BC professionals. Covers contaminated sites, CEPA, emissions, carbon policy, PFAS, and remediation developments.",
        "about_host": "Hosted by Patrick in Vancouver.",
        "apple_podcasts_url": None,
        "theme_color": "#1B5E20",
        "meta_description": "Environmental Intelligence — Daily environmental regulatory and compliance briefing for BC professionals.",
        "meta_keywords": "environmental intelligence, regulatory compliance, environmental briefings, Canadian environment",
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
        "brand_color": "#8B5CF6",
        "brand_color_dark": "#6D28D9",
        "tagline": "Not the ones you're thinking about!",
        "hero_tagline": "Not the ones you're thinking about!",
        "about_text": "Daily AI briefing covering new model releases, agent frameworks, and practical developments. From GPT and Claude to OpenClaw and Agent Zero — stay on top of the most exciting developments of our generation.",
        "about_host": "Hosted by Patrick in Vancouver.",
        "apple_podcasts_url": None,
        "theme_color": "#8B5CF6",
        "meta_description": "Models & Agents — Daily AI briefing on models, agent frameworks, and practical AI developments.",
        "meta_keywords": "AI models, agent frameworks, LLM news, AI briefings, Models and Agents",
    },
}


def _build_all_shows_list():
    """Build a list of all shows with metadata needed by templates."""
    return [
        {
            "name": cfg["name"],
            "slug": cfg["slug"],
            "show_page": cfg["show_page"],
            "summaries_page": cfg["summaries_page"],
            "podcast_image": cfg["podcast_image"],
            "rss_file": cfg["rss_file"],
            "brand_color": cfg["brand_color"],
            "tagline": cfg["tagline"],
        }
        for cfg in NETWORK_SHOWS.values()
    ]


def _get_jinja_env():
    """Create a shared Jinja2 environment."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=False,
        keep_trailing_newline=True,
    )


# ---------------------------------------------------------------------------
# Summaries pages
# ---------------------------------------------------------------------------

def generate_summaries_page(slug, *, dry_run=False):
    """Render and write a summaries page for a single show."""
    cfg = NETWORK_SHOWS[slug]
    env = _get_jinja_env()
    template = env.get_template("summaries_page.html.j2")

    podcast_logo_url = None
    if cfg.get("podcast_image"):
        podcast_logo_url = f"{GITHUB_RAW}/{cfg['podcast_image']}"

    context = {
        **cfg,
        "show_name": cfg["name"],
        "show_slug": cfg["slug"],
        "page_title": f"{cfg['name']} | Summaries",
        "podcast_logo_url": podcast_logo_url,
        "og_image": podcast_logo_url,
        "show_color": cfg["brand_color"],
        "show_color_dark": cfg.get("brand_color_dark", cfg["brand_color"]),
        "hero_title": cfg["name"],
        "hero_subtitle": f"Complete archive of {cfg['name']} episode summaries.",
        "all_shows": _build_all_shows_list(),
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


# ---------------------------------------------------------------------------
# Show pages
# ---------------------------------------------------------------------------

def generate_show_page(slug, *, dry_run=False):
    """Render and write a show page for a single show."""
    cfg = NETWORK_SHOWS[slug]
    env = _get_jinja_env()
    template = env.get_template("show_page.html.j2")

    podcast_image_url = cfg["podcast_image"]

    context = {
        **cfg,
        "show_name": cfg["name"],
        "show_slug": cfg["slug"],
        "show_description": cfg.get("about_text", cfg["description"]),
        "page_title": f"{cfg['name']} | Nerra Network",
        "podcast_image_url": podcast_image_url,
        "og_image": f"{GITHUB_RAW}/{cfg['podcast_image']}",
        "show_color": cfg["brand_color"],
        "show_color_dark": cfg.get("brand_color_dark", cfg["brand_color"]),
        "all_shows": _build_all_shows_list(),
    }

    html = template.render(**context)

    out_path = ROOT / cfg["show_page"]
    if dry_run:
        print(f"[dry-run] Would write {out_path} ({len(html):,} bytes)")
        return None

    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({len(html):,} bytes)")
    return out_path


def generate_all_show_pages(*, dry_run=False):
    """Generate show pages for every show."""
    paths = []
    for slug in NETWORK_SHOWS:
        result = generate_show_page(slug, dry_run=dry_run)
        if result:
            paths.append(result)
    return paths


# ---------------------------------------------------------------------------
# Network landing page
# ---------------------------------------------------------------------------

def generate_network_page(*, dry_run=False):
    """Render and write the network landing page."""
    env = _get_jinja_env()
    template = env.get_template("network_page.html.j2")

    context = {
        "page_title": "Nerra Network | 6 Daily Shows",
        "meta_description": "Nerra Network — Six daily podcasts keeping you informed. Tesla, world news, space, science, environment, and AI. Independent, daily, free.",
        "meta_keywords": "podcast network, daily podcasts, Nerra Network, Tesla, space, science, AI, environment",
        "theme_color": "#7C5CFF",
        "og_image": f"{GITHUB_RAW}/podcast-image.jpg",
        "all_shows": _build_all_shows_list(),
    }

    html = template.render(**context)

    out_path = ROOT / "network.html"
    if dry_run:
        print(f"[dry-run] Would write {out_path} ({len(html):,} bytes)")
        return None

    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({len(html):,} bytes)")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

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
        "--shows",
        action="store_true",
        help="Generate show pages",
    )
    parser.add_argument(
        "--network",
        action="store_true",
        help="Generate network landing page",
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
    if not args.summaries and not args.shows and not args.network and not args.all and not args.show:
        args.all = True

    if args.show:
        if args.show not in NETWORK_SHOWS:
            print(f"Error: unknown show '{args.show}'. Valid: {', '.join(NETWORK_SHOWS)}", file=sys.stderr)
            sys.exit(1)
        generate_show_page(args.show, dry_run=args.dry_run)
        generate_summaries_page(args.show, dry_run=args.dry_run)
        return

    if args.all:
        generate_all_show_pages(dry_run=args.dry_run)
        generate_all_summaries(dry_run=args.dry_run)
        generate_network_page(dry_run=args.dry_run)
        return

    if args.shows:
        generate_all_show_pages(dry_run=args.dry_run)
    if args.summaries:
        generate_all_summaries(dry_run=args.dry_run)
    if args.network:
        generate_network_page(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
