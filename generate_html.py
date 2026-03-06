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
from urllib.parse import quote

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
        "show_page": "tesla.html",
        "summaries_page": "tesla-summaries.html",
        "json_path": "digests/tesla_shorts_time/summaries_tesla.json",
        "json_format": "wrapped",
        "rss_file": "podcast.rss",
        "podcast_image": "podcast-image-v3.jpg",
        "x_account": "teslashortstime",
        "brand_color": "#E31937",
        "brand_color_dark": "#C4122E",
        "tagline": "Shorting Tesla? Time's Up.",
        "hero_tagline": "Shorting Tesla? Time's Up.",
        "schedule": "Daily",
        "episode_length": "~15 min",
        "about_text": "Tesla Shorts Time is a daily podcast delivering the most important Tesla news and developments. We focus on how Tesla is advancing its mission to accelerate the world's transition to sustainable energy, saving lives through safer vehicles, and making the world a better place.",
        "about_host": "Hosted by Patrick, each episode covers breaking news, product updates, technology breakthroughs, and the latest developments from Tesla and the broader electric vehicle world.",
        "description_long": "Daily podcast covering how Tesla is advancing its mission to accelerate the transition to sustainable energy. Covers FSD safety milestones, Cybertruck production, energy storage breakthroughs, TSLA stock movements, and why the shorts keep getting it wrong.",
        "related_show": "omni_view",
        "related_reason": "If you enjoy Tesla Shorts Time, you might also like Omni View — balanced daily news from every perspective.",
        "apple_podcasts_url": "https://podcasts.apple.com/us/podcast/tesla-shorts-time/id1855142939",
        "theme_color": "#E31937",
        "meta_description": "Daily Tesla Shorts Time podcast — Tesla news, TSLA stock, FSD updates, and sustainable energy progress.",
        "meta_keywords": "Tesla podcast, TSLA news, Tesla stock, EV analysis, Tesla Shorts Time, daily digests",
        "audience": "For Tesla owners, TSLA investors, EV enthusiasts, and anyone following the transition to sustainable energy.",
        "source_highlights": ["Teslarati", "CleanTechnica", "InsideEVs", "The Verge"],
        "resources": [
            {"name": "Tesla Investor Relations", "url": "https://ir.tesla.com", "desc": "Official SEC filings, earnings calls, and shareholder letters"},
            {"name": "Tesla Blog", "url": "https://www.tesla.com/blog", "desc": "Official Tesla announcements and product updates"},
            {"name": "TSLA on Yahoo Finance", "url": "https://finance.yahoo.com/quote/TSLA", "desc": "Real-time stock price, charts, and financial data"},
            {"name": "Teslarati", "url": "https://www.teslarati.com", "desc": "Independent Tesla and SpaceX news coverage"},
            {"name": "Not A Tesla App", "url": "https://www.notateslaapp.com", "desc": "Tesla software updates and feature tracking"},
            {"name": "CleanTechnica", "url": "https://cleantechnica.com", "desc": "Clean energy and electric vehicle industry news"},
        ],
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
        "schedule": "Daily",
        "episode_length": "~20 min",
        "about_text": "Omni View is a neutral, media-literacy-first daily briefing designed for everyone from children to seniors. Covers top world, business, technology, and media stories with perspectives from across the political spectrum.",
        "about_host": "Hosted by Patrick in Vancouver. Helping you form your own informed opinions through balanced, multi-perspective coverage.",
        "description_long": "A neutral, media-literacy-first daily briefing designed for everyone from children to seniors. Covers top world, business, technology, and media stories with perspectives from across the political spectrum — so you can decide for yourself.",
        "related_show": "tesla",
        "related_reason": "If you enjoy Omni View, you might also like Tesla Shorts Time — daily news focused on Tesla and sustainable energy.",
        "apple_podcasts_url": None,
        "theme_color": "#0B6FD6",
        "meta_description": "Omni View — Daily balanced news summaries from diverse sources. Multiple perspectives on the stories that matter.",
        "meta_keywords": "balanced news, diverse perspectives, media literacy, news analysis, unbiased reporting",
        "audience": "For thoughtful news consumers who want every side of the story — not just the one their algorithm picks.",
        "source_highlights": ["NPR", "BBC", "Reuters", "WSJ", "Al Jazeera", "The Guardian"],
        "resources": [
            {"name": "AllSides Media Bias Chart", "url": "https://www.allsides.com/media-bias/ratings", "desc": "See where news sources fall on the political spectrum"},
            {"name": "Ground News", "url": "https://ground.news", "desc": "Compare how different outlets cover the same story"},
            {"name": "Ad Fontes Media Bias Chart", "url": "https://adfontesmedia.com", "desc": "Independent media reliability and bias ratings"},
            {"name": "Reuters", "url": "https://www.reuters.com", "desc": "Wire service known for factual, neutral reporting"},
            {"name": "AP News", "url": "https://apnews.com", "desc": "Non-profit global news wire with minimal editorial bias"},
            {"name": "FactCheck.org", "url": "https://www.factcheck.org", "desc": "Non-partisan fact-checking from the Annenberg Public Policy Center"},
        ],
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
        "schedule": "Daily",
        "episode_length": "~15 min",
        "about_text": "Daily space and astronomy news covering mission updates, cosmic discoveries, exoplanet breakthroughs, and rocket launches. From NASA and ESA to SpaceX and beyond.",
        "about_host": "Hosted by Patrick in Vancouver, bringing the cosmos to your ears.",
        "description_long": "Daily space and astronomy news covering mission updates, cosmic discoveries, exoplanet breakthroughs, and rocket launches. From NASA and ESA to SpaceX and beyond — the universe is more exciting than you think.",
        "related_show": "planetterrian",
        "related_reason": "If you enjoy Fascinating Frontiers, you might also like Planetterrian Daily — daily science, longevity, and health discoveries.",
        "apple_podcasts_url": None,
        "theme_color": "#7C5CFF",
        "meta_description": "Fascinating Frontiers — Daily space and astronomy news podcast. Mission updates, cosmic discoveries, and rocket launches.",
        "meta_keywords": "space podcast, astronomy news, NASA discoveries, space exploration, Fascinating Frontiers",
        "audience": "For space enthusiasts, amateur astronomers, students, and anyone who looks up and wonders what's out there.",
        "source_highlights": ["NASA", "ESA", "Space.com", "SpaceNews"],
        "resources": [
            {"name": "NASA", "url": "https://www.nasa.gov", "desc": "Official NASA mission updates, images, and research"},
            {"name": "NASA APOD", "url": "https://apod.nasa.gov", "desc": "Astronomy Picture of the Day — daily cosmic imagery with explanations"},
            {"name": "Space.com", "url": "https://www.space.com", "desc": "Space news, astronomy guides, and stargazing tips"},
            {"name": "Webb Telescope", "url": "https://webbtelescope.org", "desc": "James Webb Space Telescope images and science results"},
            {"name": "Heavens-Above", "url": "https://www.heavens-above.com", "desc": "Track satellites, ISS passes, and night sky objects for your location"},
            {"name": "The Planetary Society", "url": "https://www.planetary.org", "desc": "Space exploration advocacy and citizen science projects"},
        ],
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
        "schedule": "Daily",
        "episode_length": "~15 min",
        "about_text": "Daily discoveries in longevity science, genetics, biotech, CRISPR, neuroscience, and health research. If it could extend your healthspan or change medicine, we cover it.",
        "about_host": "Hosted by Patrick in Vancouver. A tribe of forward-thinking innovators.",
        "description_long": "Daily discoveries in longevity science, genetics, biotech, CRISPR, neuroscience, and health research. If it could extend your healthspan or change medicine, we cover it.",
        "related_show": "fascinating_frontiers",
        "related_reason": "If you enjoy Planetterrian Daily, you might also like Fascinating Frontiers — daily space and astronomy news.",
        "apple_podcasts_url": None,
        "theme_color": "#018DB1",
        "meta_description": "Planetterrian Daily — Science, longevity, and health discoveries. Genetics, biotech, CRISPR, and more.",
        "meta_keywords": "science podcast, longevity research, health discoveries, Planetterrian Daily, biotech news",
        "audience": "For the health-curious, longevity enthusiasts, biohackers, and anyone who wants tomorrow's medicine explained today.",
        "source_highlights": ["Nature", "Science", "Cell", "New Scientist"],
        "resources": [
            {"name": "PubMed", "url": "https://pubmed.ncbi.nlm.nih.gov", "desc": "Free access to biomedical and life science research papers"},
            {"name": "ClinicalTrials.gov", "url": "https://clinicaltrials.gov", "desc": "Database of clinical studies and trials worldwide"},
            {"name": "Nature", "url": "https://www.nature.com", "desc": "Premier multidisciplinary science journal"},
            {"name": "Quanta Magazine", "url": "https://www.quantamagazine.org", "desc": "Accessible coverage of math, physics, and biology research"},
            {"name": "Lifespan.io", "url": "https://www.lifespan.io", "desc": "Longevity research news and rejuvenation science tracker"},
            {"name": "Examine.com", "url": "https://examine.com", "desc": "Evidence-based supplement and nutrition research"},
        ],
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
        "tagline": "Environmental regulatory and compliance briefing.",
        "hero_tagline": "Environmental regulatory and compliance briefing.",
        "schedule": "Weekdays",
        "episode_length": "~10 min",
        "about_text": "Environmental regulatory, science, and compliance briefing for BC professionals. Covers contaminated sites, CEPA, emissions, carbon policy, PFAS, and remediation developments.",
        "about_host": "Hosted by Patrick in Vancouver.",
        "description_long": "Environmental regulatory, science, and compliance briefing for BC professionals. Covers contaminated sites, CEPA, emissions, carbon policy, PFAS, and remediation developments across Canada.",
        "related_show": "planetterrian",
        "related_reason": "If you enjoy Environmental Intelligence, you might also like Planetterrian Daily — science, longevity, and health research.",
        "apple_podcasts_url": None,
        "theme_color": "#1B5E20",
        "meta_description": "Environmental Intelligence — Daily environmental regulatory and compliance briefing for BC professionals.",
        "meta_keywords": "environmental intelligence, regulatory compliance, environmental briefings, Canadian environment",
        "audience": "For Canadian environmental professionals — contaminated sites consultants, regulators, lawyers, and lab scientists.",
        "source_highlights": ["Canada Gazette", "ECCC", "BC Ministry of Environment", "The Narwhal"],
        "resources": [
            {"name": "Canada Gazette", "url": "https://www.gazette.gc.ca", "desc": "Official source for federal regulations and proposed amendments"},
            {"name": "ECCC", "url": "https://www.canada.ca/en/environment-climate-change.html", "desc": "Environment and Climate Change Canada — federal policy and enforcement"},
            {"name": "CCME", "url": "https://ccme.ca", "desc": "Canadian Council of Ministers of the Environment — guidelines and standards"},
            {"name": "BC Site Remediation", "url": "https://www2.gov.bc.ca/gov/content/environment/air-land-water/site-remediation", "desc": "BC contaminated sites registry, guidance, and CSR protocols"},
            {"name": "The Narwhal", "url": "https://thenarwhal.ca", "desc": "Independent Canadian environmental investigative journalism"},
            {"name": "Ecojustice", "url": "https://ecojustice.ca", "desc": "Canada's leading environmental law charity"},
        ],
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
        "tagline": "Daily AI models, agents, and practical developments.",
        "hero_tagline": "Daily AI models, agents, and practical developments.",
        "schedule": "Daily",
        "episode_length": "~15 min",
        "about_text": "Daily AI briefing covering new model releases, agent frameworks, and practical developments. From GPT and Claude to OpenClaw and Agent Zero — stay on top of the most exciting developments of our generation.",
        "about_host": "Hosted by Patrick in Vancouver.",
        "description_long": "Daily AI briefing covering new model releases, agent frameworks, and practical developments. From GPT and Claude to open-source projects — stay on top of the most exciting tech developments of our generation.",
        "related_show": "models_agents_beginners",
        "related_reason": "If you enjoy Models & Agents, you might also like Models & Agents for Beginners — the same AI news explained simply for newcomers.",
        "apple_podcasts_url": None,
        "theme_color": "#8B5CF6",
        "meta_description": "Models & Agents — Daily AI briefing on models, agent frameworks, and practical AI developments.",
        "meta_keywords": "AI models, agent frameworks, LLM news, AI briefings, Models and Agents",
        "audience": "For developers building with AI, professionals adopting AI tools, and anyone who wants to stay ahead of the most transformative technology of our generation.",
        "source_highlights": ["OpenAI", "Anthropic", "Hugging Face", "arXiv"],
        "resources": [
            {"name": "Hugging Face", "url": "https://huggingface.co", "desc": "Open-source models, datasets, demos, and the model Hub"},
            {"name": "Papers With Code", "url": "https://paperswithcode.com", "desc": "ML papers with code, benchmarks, and leaderboards"},
            {"name": "arXiv AI", "url": "https://arxiv.org/list/cs.AI/recent", "desc": "Latest AI research preprints from the research community"},
            {"name": "LM Arena", "url": "https://lmarena.ai", "desc": "Chatbot Arena — crowdsourced LLM rankings and leaderboard"},
            {"name": "Latent Space", "url": "https://www.latent.space", "desc": "AI engineering podcast, newsletter, and community"},
            {"name": "The Decoder", "url": "https://the-decoder.com", "desc": "AI news focused on practical developments and new releases"},
        ],
    },
    "models_agents_beginners": {
        "name": "Models & Agents for Beginners",
        "slug": "models_agents_beginners",
        "description": "Daily AI podcast for beginners and teens — AI explained simply.",
        "show_page": "models-agents-beginners.html",
        "summaries_page": "models-agents-beginners-summaries.html",
        "json_path": "digests/models_agents_beginners/summaries_models_agents_beginners.json",
        "json_format": "wrapped",
        "rss_file": "models_agents_beginners_podcast.rss",
        "podcast_image": "models-agents-beginners-podcast-image.jpg",
        "x_account": None,
        "brand_color": "#F59E0B",
        "brand_color_dark": "#D97706",
        "tagline": "AI explained simply — for beginners and teens.",
        "hero_tagline": "AI explained simply — for beginners and teens.",
        "schedule": "Daily",
        "episode_length": "~10 min",
        "about_text": "A daily AI podcast for beginners and teens. Learn about AI models, agents, and the tools shaping our future — explained simply, with hands-on experiments you can try today. Every expert started as a beginner.",
        "about_host": "Hosted by Patrick in Vancouver.",
        "description_long": "A daily AI podcast for beginners and teens — learn about models, agents, and the AI revolution in plain language. We explain the jargon, encourage experimentation, and help you understand the most exciting technology of our generation.",
        "related_show": "models_agents",
        "related_reason": "If you enjoy Models & Agents for Beginners and want to go deeper, check out Models & Agents — the full daily AI briefing for developers and professionals.",
        "apple_podcasts_url": None,
        "theme_color": "#F59E0B",
        "meta_description": "Models & Agents for Beginners — Daily AI podcast for beginners and teens. AI models, agents, and tools explained simply.",
        "meta_keywords": "AI for beginners, AI podcast teens, learn AI, beginner AI, Models and Agents for Beginners",
        "audience": "For students, teens, curious parents, career changers, and anyone new to AI who wants to understand what's happening without the jargon.",
        "source_highlights": ["OpenAI", "Google AI", "Hugging Face", "TechCrunch AI"],
        "resources": [
            {"name": "Google AI Essentials", "url": "https://grow.google/ai-essentials/", "desc": "Free introductory AI course from Google — no experience needed"},
            {"name": "Hugging Face", "url": "https://huggingface.co", "desc": "Try AI models in your browser — text, images, and more"},
            {"name": "Scratch + AI", "url": "https://machinelearningforkids.co.uk", "desc": "Machine Learning for Kids — hands-on AI projects for beginners"},
            {"name": "Elements of AI", "url": "https://www.elementsofai.com", "desc": "Free online course — understand AI concepts without coding"},
            {"name": "ChatGPT", "url": "https://chat.openai.com", "desc": "Try conversing with an AI chatbot — the best way to learn is by doing"},
            {"name": "Khan Academy AI", "url": "https://www.khanacademy.org/computing/ai-for-everyone", "desc": "AI for Everyone — free lessons from Khan Academy"},
        ],
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
            "schedule": cfg.get("schedule", "Daily"),
            "episode_length": cfg.get("episode_length", ""),
            "description_long": cfg.get("description_long", cfg["description"]),
            "source_highlights": cfg.get("source_highlights", []),
        }
        for cfg in NETWORK_SHOWS.values()
    ]


def _url_encode_image(image_path):
    """URL-encode an image filename for use in OG/meta tags."""
    return quote(image_path, safe="/")


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
    og_image_url = None
    if cfg.get("podcast_image"):
        podcast_logo_url = f"{GITHUB_RAW}/{_url_encode_image(cfg['podcast_image'])}"
        og_image_url = podcast_logo_url

    context = {
        **cfg,
        "show_name": cfg["name"],
        "show_slug": cfg["slug"],
        "page_title": f"{cfg['name']} | Summaries",
        "podcast_logo_url": podcast_logo_url,
        "og_image": og_image_url,
        "show_color": cfg["brand_color"],
        "show_color_dark": cfg.get("brand_color_dark", cfg["brand_color"]),
        "canonical_url": f"{GITHUB_RAW}/{cfg['summaries_page']}",
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

    # Build related show info for cross-promotion
    related_show_data = None
    related_slug = cfg.get("related_show")
    if related_slug and related_slug in NETWORK_SHOWS:
        rel = NETWORK_SHOWS[related_slug]
        related_show_data = {
            "name": rel["name"],
            "slug": rel["slug"],
            "show_page": rel["show_page"],
            "podcast_image": rel["podcast_image"],
            "tagline": rel["tagline"],
            "reason": cfg.get("related_reason", ""),
        }

    context = {
        **cfg,
        "show_name": cfg["name"],
        "show_slug": cfg["slug"],
        "show_description": cfg.get("about_text", cfg["description"]),
        "page_title": f"{cfg['name']} | Nerra Network",
        "podcast_image_url": podcast_image_url,
        "og_image": f"{GITHUB_RAW}/{_url_encode_image(cfg['podcast_image'])}",
        "show_color": cfg["brand_color"],
        "show_color_dark": cfg.get("brand_color_dark", cfg["brand_color"]),
        "canonical_url": f"{GITHUB_RAW}/{cfg['show_page']}",
        "related_show": related_show_data,
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
        "page_title": "Nerra Network | 7 Daily Shows",
        "meta_description": "Nerra Network — Seven daily podcasts keeping you informed. Tesla, world news, space, science, environment, and AI. Independent, daily, free.",
        "meta_keywords": "podcast network, daily podcasts, Nerra Network, Tesla, space, science, AI, environment",
        "theme_color": "#7C5CFF",
        "og_image": None,  # No single show image represents the network
        "canonical_url": f"{GITHUB_RAW}/index.html",
        "all_shows": _build_all_shows_list(),
    }

    html = template.render(**context)

    out_path = ROOT / "index.html"
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
