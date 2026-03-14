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
        "podcast_image": "assets/covers/tesla-shorts-time.jpg",
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
        "resource_categories": [
            {
                "title": "Investor Resources",
                "resources": [
                    {"name": "Tesla Investor Relations", "url": "https://ir.tesla.com", "desc": "Official SEC filings, earnings calls, and shareholder letters"},
                    {"name": "TSLA on Yahoo Finance", "url": "https://finance.yahoo.com/quote/TSLA", "desc": "Real-time stock price, charts, and financial data"},
                    {"name": "Tesla Daily (Rob Maurer)", "url": "https://www.youtube.com/@TeslaDaily", "desc": "Daily TSLA analysis from the most-followed Tesla stock commentator"},
                    {"name": "Hypercharts Tesla", "url": "https://hypercharts.co/tsla", "desc": "Tesla financial data visualizations — revenue, margins, deliveries"},
                    {"name": "Macrotrends TSLA", "url": "https://www.macrotrends.net/stocks/charts/TSLA/tesla/revenue", "desc": "Historical Tesla financials, ratios, and growth metrics"},
                ],
            },
            {
                "title": "News Sources",
                "resources": [
                    {"name": "Teslarati", "url": "https://www.teslarati.com", "desc": "Independent Tesla and SpaceX news — the largest dedicated Tesla news outlet"},
                    {"name": "Not A Tesla App", "url": "https://www.notateslaapp.com", "desc": "Tesla software updates, feature tracking, and release notes"},
                    {"name": "CleanTechnica", "url": "https://cleantechnica.com", "desc": "Clean energy and EV industry analysis and commentary"},
                    {"name": "InsideEVs", "url": "https://insideevs.com", "desc": "Electric vehicle news, reviews, and sales data across all brands"},
                    {"name": "Drive Tesla Canada", "url": "https://driveteslacanada.ca", "desc": "Canadian Tesla ownership news, tips, and community coverage"},
                    {"name": "Electrek", "url": "https://electrek.co", "desc": "Electric transport and clean energy news — Tesla, EVs, solar, and storage"},
                ],
            },
            {
                "title": "Community & Forums",
                "resources": [
                    {"name": "Tesla Motors Club", "url": "https://teslamotorsclub.com", "desc": "The largest Tesla owner forum — 500K+ members discussing ownership, mods, and tips"},
                    {"name": "r/TeslaMotors", "url": "https://www.reddit.com/r/TeslaMotors/", "desc": "Reddit's main Tesla community — news, reviews, and owner discussions"},
                    {"name": "r/TSLALounge", "url": "https://www.reddit.com/r/TSLALounge/", "desc": "Tesla investor community focused on TSLA stock and market analysis"},
                    {"name": "Tesla Owners Online", "url": "https://teslaownersonline.com", "desc": "Owner forum with detailed guides for Model 3, Y, S, X, and Cybertruck"},
                ],
            },
            {
                "title": "Tesla Data & Tools",
                "resources": [
                    {"name": "Tesla Blog", "url": "https://www.tesla.com/blog", "desc": "Official Tesla announcements and product updates"},
                    {"name": "PlugShare", "url": "https://www.plugshare.com", "desc": "Find EV charging stations — Supercharger network and third-party chargers"},
                    {"name": "A Better Route Planner", "url": "https://abetterrouteplanner.com", "desc": "EV trip planner with real-time range estimation for Tesla and other EVs"},
                    {"name": "TeslaFi", "url": "https://teslafi.com", "desc": "Tesla data logger — track efficiency, battery health, trips, and charging"},
                ],
            },
            {
                "title": "Learning & Deep Dives",
                "resources": [
                    {"name": "Tesla AI Day Presentations", "url": "https://www.youtube.com/results?search_query=tesla+ai+day", "desc": "Technical presentations on FSD, Optimus robot, and Dojo supercomputer"},
                    {"name": "Sandy Munro", "url": "https://www.youtube.com/@MunroLive", "desc": "Engineering teardowns and manufacturing analysis of Tesla vehicles"},
                    {"name": "Tesla Master Plan", "url": "https://www.tesla.com/blog/master-plan-part-3", "desc": "Tesla's vision for sustainable energy — Master Plan Part 3"},
                    {"name": "Third Row Tesla", "url": "https://www.youtube.com/@thirdrowtesla", "desc": "In-depth Tesla interviews and analysis from the community"},
                ],
            },
        ],
        "tools": [
            {"name": "TradingView", "url": "https://www.tradingview.com/symbols/NASDAQ-TSLA/", "desc": "Advanced TSLA charting, technical analysis, and community ideas", "badge": "Free tier"},
            {"name": "Yahoo Finance", "url": "https://finance.yahoo.com/quote/TSLA", "desc": "Real-time TSLA quotes, financials, analyst ratings, and news", "badge": "Free"},
            {"name": "PlugShare", "url": "https://www.plugshare.com", "desc": "Find Superchargers and charging stations anywhere — essential for road trips", "badge": "Free"},
            {"name": "A Better Route Planner", "url": "https://abetterrouteplanner.com", "desc": "Plan EV road trips with accurate range estimates and charging stops", "badge": "Free"},
            {"name": "TeslaFi", "url": "https://teslafi.com", "desc": "Track your Tesla's efficiency, charging, battery degradation, and trip data", "badge": "Paid"},
            {"name": "Optiwatt", "url": "https://getoptiwatt.com", "desc": "Smart Tesla charging — schedule charging for the cheapest electricity rates", "badge": "Free"},
        ],
        "faq": [
            {"q": "What is FSD (Full Self-Driving)?", "a": "FSD is Tesla's advanced driver-assistance system that aims to enable fully autonomous driving. It uses cameras and neural networks to navigate roads, handle intersections, and park. As of 2026, FSD (Supervised) requires driver attention at all times — it's not yet fully autonomous, but Tesla is working toward unsupervised capability with its robotaxi program."},
            {"q": "What does 'shorts' mean in Tesla Shorts Time?", "a": "In stock market terminology, 'shorting' means betting that a stock's price will go down. Tesla has historically been one of the most-shorted stocks on the market. 'Tesla Shorts Time' plays on this — suggesting that time is running out for those betting against Tesla, as the company continues to grow and prove skeptics wrong."},
            {"q": "What is a Gigafactory?", "a": "A Gigafactory is Tesla's term for its massive manufacturing facilities. The name comes from 'giga' (billion) — these factories produce batteries and vehicles at a scale measured in gigawatt-hours. Tesla operates Gigafactories in Nevada, Shanghai, Berlin, and Texas, each producing hundreds of thousands of vehicles per year."},
            {"q": "What is the Tesla Megapack?", "a": "The Megapack is Tesla's utility-scale battery storage product. Each unit stores up to 4 MWh of energy — enough to power about 3,600 homes for one hour. Utilities and grid operators use Megapacks to store renewable energy from solar and wind farms, stabilize the grid, and replace fossil fuel peaker plants."},
            {"q": "What does TSLA's P/E ratio mean?", "a": "The Price-to-Earnings (P/E) ratio shows how much investors pay per dollar of Tesla's earnings. A high P/E (Tesla's is often 50-100+) means investors expect strong future growth. For comparison, traditional automakers trade at P/E ratios of 5-15. Tesla's premium reflects the market pricing in its AI, energy, and robotaxi potential beyond just car sales."},
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
        "podcast_image": "assets/covers/omni-view.jpg",
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
        "resource_categories": [
            {
                "title": "Media Bias & Literacy Tools",
                "resources": [
                    {"name": "AllSides Media Bias Ratings", "url": "https://www.allsides.com/media-bias/ratings", "desc": "See where 800+ news sources fall on the political spectrum — crowd-sourced and editorial ratings"},
                    {"name": "Ad Fontes Media Bias Chart", "url": "https://adfontesmedia.com", "desc": "Interactive chart rating news sources on reliability and political bias"},
                    {"name": "Media Bias/Fact Check", "url": "https://mediabiasfactcheck.com", "desc": "Independent media bias and factual reporting database — 7,000+ sources rated"},
                    {"name": "The News Literacy Project", "url": "https://newslit.org", "desc": "Free tools and lessons for evaluating news credibility — great for students and adults"},
                    {"name": "First Draft News", "url": "https://firstdraftnews.org", "desc": "Research and training on misinformation, disinformation, and media manipulation"},
                ],
            },
            {
                "title": "Wire Services & Neutral Sources",
                "resources": [
                    {"name": "Reuters", "url": "https://www.reuters.com", "desc": "Global wire service known for factual, neutral reporting across politics and business"},
                    {"name": "AP News", "url": "https://apnews.com", "desc": "Non-profit global news wire — one of the most trusted sources for straight news"},
                    {"name": "BBC News", "url": "https://www.bbc.com/news", "desc": "British public broadcaster — comprehensive international coverage with editorial standards"},
                    {"name": "NPR", "url": "https://www.npr.org", "desc": "US public radio — in-depth reporting on politics, culture, science, and economics"},
                    {"name": "PBS NewsHour", "url": "https://www.pbs.org/newshour/", "desc": "US public television news — long-form reporting without commercial pressure"},
                ],
            },
            {
                "title": "Left-Leaning Sources",
                "resources": [
                    {"name": "The Guardian", "url": "https://www.theguardian.com", "desc": "UK-based global coverage with progressive editorial perspective — free, no paywall"},
                    {"name": "The Intercept", "url": "https://theintercept.com", "desc": "Investigative journalism focused on civil liberties, government accountability, and justice"},
                    {"name": "Mother Jones", "url": "https://www.motherjones.com", "desc": "Investigative reporting on politics, environment, and social justice"},
                    {"name": "Vox", "url": "https://www.vox.com", "desc": "Explanatory journalism — complex stories broken down with context and data"},
                ],
            },
            {
                "title": "Right-Leaning Sources",
                "resources": [
                    {"name": "Wall Street Journal", "url": "https://www.wsj.com", "desc": "Business and financial news with center-right editorial perspective"},
                    {"name": "National Review", "url": "https://www.nationalreview.com", "desc": "Conservative commentary and analysis on politics, culture, and policy"},
                    {"name": "The Dispatch", "url": "https://thedispatch.com", "desc": "Fact-based conservative journalism — emphasis on accuracy over outrage"},
                    {"name": "Reason", "url": "https://reason.com", "desc": "Libertarian perspective on politics, culture, and ideas — free markets and individual liberty"},
                ],
            },
            {
                "title": "International Perspectives",
                "resources": [
                    {"name": "Al Jazeera English", "url": "https://www.aljazeera.com", "desc": "Middle East-based global coverage — perspectives often underrepresented in Western media"},
                    {"name": "Deutsche Welle (DW)", "url": "https://www.dw.com/en/", "desc": "Germany's international broadcaster — European perspective on global events"},
                    {"name": "France 24", "url": "https://www.france24.com/en/", "desc": "French international news — European and African coverage with global lens"},
                    {"name": "South China Morning Post", "url": "https://www.scmp.com", "desc": "Hong Kong-based English coverage of China and Asia-Pacific affairs"},
                ],
            },
            {
                "title": "Fact-Checking",
                "resources": [
                    {"name": "FactCheck.org", "url": "https://www.factcheck.org", "desc": "Non-partisan fact-checking from the Annenberg Public Policy Center at UPenn"},
                    {"name": "PolitiFact", "url": "https://www.politifact.com", "desc": "Pulitzer Prize-winning fact-checking — rates claims on a Truth-O-Meter scale"},
                    {"name": "Snopes", "url": "https://www.snopes.com", "desc": "The internet's oldest fact-checking site — urban legends, viral claims, and political checks"},
                    {"name": "Full Fact", "url": "https://fullfact.org", "desc": "UK's independent fact-checking charity — clear verdicts on public claims"},
                ],
            },
        ],
        "tools": [
            {"name": "Ground News", "url": "https://ground.news", "desc": "See how left, center, and right outlets cover the same story side by side", "badge": "Freemium"},
            {"name": "AllSides", "url": "https://www.allsides.com", "desc": "Balanced news feed showing headlines from left, center, and right perspectives", "badge": "Free"},
            {"name": "Feedly", "url": "https://feedly.com", "desc": "Build your own balanced news feed from multiple sources — organize by topic and bias", "badge": "Free tier"},
            {"name": "Perplexity", "url": "https://www.perplexity.ai", "desc": "AI-powered research tool — ask questions and get sourced answers from across the web", "badge": "Free tier"},
            {"name": "Google News", "url": "https://news.google.com", "desc": "Aggregated headlines from thousands of sources — see full coverage of any story", "badge": "Free"},
        ],
        "faq": [
            {"q": "What is media bias?", "a": "Media bias is the tendency of a news outlet to present information in a way that favors a particular political viewpoint, ideology, or narrative. It can appear in story selection (what gets covered), framing (how it's described), word choice, and source selection. Every outlet has some degree of bias — the key is recognizing it and reading multiple perspectives."},
            {"q": "What's the difference between news and opinion?", "a": "News reporting aims to present facts — who, what, when, where, why — with minimal editorial interpretation. Opinion pieces (editorials, columns, op-eds) express the author's views and arguments about those facts. Many outlets mix both, which is why media literacy matters. Look for labels like 'Opinion,' 'Analysis,' or 'Editorial' to distinguish them."},
            {"q": "What is a wire service?", "a": "A wire service (like AP, Reuters, or AFP) is a news organization that gathers and distributes news to other media outlets. They focus on straight factual reporting without editorial slant, because their stories are used by newspapers, TV stations, and websites across the political spectrum. Wire service reports are generally considered among the most reliable news sources."},
            {"q": "How do I identify misinformation?", "a": "Check multiple sources — if only one outlet reports something, be skeptical. Look at the source's track record on fact-checking databases. Check if the story cites primary sources (documents, studies, official statements). Be wary of emotional headlines, anonymous sources without corroboration, and stories that perfectly confirm your existing beliefs. When in doubt, check FactCheck.org or Snopes."},
            {"q": "Why does Omni View cover sources from 'both sides'?", "a": "Because no single perspective has a monopoly on truth. Stories look different depending on which facts are emphasized, which sources are quoted, and what context is provided. By presenting perspectives from across the political spectrum, Omni View helps you see the full picture and form your own informed opinions — rather than having your views shaped by a single outlet's editorial choices."},
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
        "podcast_image": "assets/covers/fascinating-frontiers.jpg",
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
        "resource_categories": [
            {
                "title": "Space Agencies",
                "resources": [
                    {"name": "NASA", "url": "https://www.nasa.gov", "desc": "Official NASA mission updates, images, and research — the world's largest space agency"},
                    {"name": "ESA", "url": "https://www.esa.int", "desc": "European Space Agency — Rosalind Franklin rover, Ariane rockets, and Earth observation"},
                    {"name": "JAXA", "url": "https://global.jaxa.jp", "desc": "Japan Aerospace Exploration Agency — Hayabusa asteroid missions and lunar exploration"},
                    {"name": "ISRO", "url": "https://www.isro.gov.in", "desc": "Indian Space Research Organisation — Chandrayaan lunar missions and Mars Orbiter"},
                    {"name": "CSA", "url": "https://www.asc-csa.gc.ca/eng/", "desc": "Canadian Space Agency — Canadarm, Chris Hadfield's agency, and Arctic Earth observation"},
                ],
            },
            {
                "title": "News & Journalism",
                "resources": [
                    {"name": "Space.com", "url": "https://www.space.com", "desc": "Space news, stargazing guides, and astronomy explainers — the go-to popular source"},
                    {"name": "SpaceNews", "url": "https://spacenews.com", "desc": "Industry-focused space journalism — policy, launches, satellites, and business"},
                    {"name": "Spaceflight Now", "url": "https://spaceflightnow.com", "desc": "Launch tracking, mission updates, and real-time coverage of rocket launches"},
                    {"name": "Universe Today", "url": "https://www.universetoday.com", "desc": "Astronomy and space exploration news written for enthusiasts by enthusiasts"},
                    {"name": "The Planetary Society", "url": "https://www.planetary.org", "desc": "Space exploration advocacy, citizen science, and Carl Sagan's legacy organization"},
                ],
            },
            {
                "title": "Citizen Science & Stargazing",
                "resources": [
                    {"name": "NASA APOD", "url": "https://apod.nasa.gov", "desc": "Astronomy Picture of the Day — a stunning new cosmic image with expert explanation every day"},
                    {"name": "Heavens-Above", "url": "https://www.heavens-above.com", "desc": "Track satellites, ISS passes, and planets for your location — essential for observers"},
                    {"name": "Zooniverse", "url": "https://www.zooniverse.org", "desc": "Citizen science projects — help classify galaxies, discover exoplanets, and hunt asteroids"},
                    {"name": "Globe at Night", "url": "https://www.globeatnight.org", "desc": "Citizen science program measuring light pollution — contribute from your backyard"},
                    {"name": "Sky & Telescope", "url": "https://skyandtelescope.org", "desc": "Observing guides, equipment reviews, and astronomical event calendars for amateur astronomers"},
                ],
            },
            {
                "title": "Telescopes & Missions",
                "resources": [
                    {"name": "Webb Telescope", "url": "https://webbtelescope.org", "desc": "James Webb Space Telescope — the most powerful space telescope ever built, images and science"},
                    {"name": "Hubble Site", "url": "https://hubblesite.org", "desc": "Hubble Space Telescope gallery, news, and 35+ years of iconic cosmic images"},
                    {"name": "NASA Mars Exploration", "url": "https://mars.nasa.gov", "desc": "Perseverance rover, Ingenuity helicopter, and the journey to send humans to Mars"},
                    {"name": "NASA Exoplanet Archive", "url": "https://exoplanetarchive.ipac.caltech.edu", "desc": "Database of 5,700+ confirmed exoplanets — search, filter, and explore alien worlds"},
                    {"name": "SpaceX", "url": "https://www.spacex.com", "desc": "Starship development, Falcon 9 launches, and the mission to make humanity multiplanetary"},
                ],
            },
            {
                "title": "Learning & Courses",
                "resources": [
                    {"name": "Crash Course Astronomy", "url": "https://www.youtube.com/playlist?list=PL8dPuuaLjXtPAJr1ysd5yGIyiSFuh0mIL", "desc": "46 free episodes covering the solar system to cosmology — fun, fast, and accurate"},
                    {"name": "Khan Academy Cosmology", "url": "https://www.khanacademy.org/science/cosmology-and-astronomy", "desc": "Free lessons on stars, galaxies, and the Big Bang — great for students"},
                    {"name": "AstroBites", "url": "https://astrobites.org", "desc": "Graduate students summarize the latest astrophysics papers in plain language — daily"},
                    {"name": "ESA Kids", "url": "https://www.esa.int/kids/en/home", "desc": "Space explained for young learners — games, activities, and mission guides from ESA"},
                ],
            },
        ],
        "tools": [
            {"name": "Stellarium", "url": "https://stellarium-web.org", "desc": "Free planetarium in your browser — see tonight's sky from any location on Earth", "badge": "Free"},
            {"name": "NASA Eyes", "url": "https://eyes.nasa.gov", "desc": "3D visualization of the solar system, Earth, and active NASA missions in real time", "badge": "Free"},
            {"name": "Heavens-Above", "url": "https://www.heavens-above.com", "desc": "Track the ISS, Starlink trains, and bright satellites passing over your city", "badge": "Free"},
            {"name": "SkySafari", "url": "https://skysafariastronomy.com", "desc": "Point your phone at the sky to identify stars, planets, and constellations instantly", "badge": "Freemium"},
            {"name": "SpaceX Launch Tracker", "url": "https://www.spacex.com/launches/", "desc": "Upcoming and past SpaceX launches — schedules, webcasts, and mission details", "badge": "Free"},
            {"name": "Spot The Station", "url": "https://spotthestation.nasa.gov", "desc": "NASA's official ISS sighting tool — get alerts when the station flies over your area", "badge": "Free"},
        ],
        "faq": [
            {"q": "What is an exoplanet?", "a": "An exoplanet is a planet that orbits a star outside our solar system. Over 5,700 exoplanets have been confirmed as of 2026, with thousands more candidates awaiting verification. They range from scorching hot Jupiters to potentially habitable rocky worlds. NASA's TESS and the James Webb Space Telescope are the primary tools for finding and studying them."},
            {"q": "How does the James Webb Space Telescope work?", "a": "JWST is an infrared space telescope with a 6.5-meter gold-coated mirror (compared to Hubble's 2.4m). It orbits the Sun at the L2 Lagrange point, 1.5 million km from Earth, where its sunshield keeps instruments at -233C. By observing in infrared, Webb can see through cosmic dust, study the atmospheres of exoplanets, and detect light from the earliest galaxies formed after the Big Bang."},
            {"q": "What is a light-year?", "a": "A light-year is the distance light travels in one year — about 9.46 trillion kilometers (5.88 trillion miles). It's used because space distances are so vast that kilometers become meaningless. For scale: the nearest star (Proxima Centauri) is 4.24 light-years away. The Milky Way galaxy is about 100,000 light-years across. The observable universe extends 46 billion light-years in every direction."},
            {"q": "What's the difference between NASA, ESA, and SpaceX?", "a": "NASA (US) and ESA (Europe) are government space agencies funded by taxpayers — they do science, exploration, and Earth observation. SpaceX is a private company founded by Elon Musk that builds rockets and spacecraft. SpaceX focuses on making space access cheaper (reusable Falcon 9, Starship), while NASA and ESA define scientific missions. They often work together — SpaceX launches NASA astronauts to the ISS."},
            {"q": "How can I see the ISS?", "a": "The International Space Station is the third brightest object in the night sky (after the Sun and Moon). It looks like a fast-moving bright star crossing the sky in 3-5 minutes. Use NASA's Spot The Station website or the Heavens-Above app to get exact times for your location. Best sightings happen just after sunset or before sunrise when the station catches sunlight against a dark sky."},
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
        "podcast_image": "assets/covers/planetterrian-daily.jpg",
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
        "resource_categories": [
            {
                "title": "Journals & Research",
                "resources": [
                    {"name": "Nature", "url": "https://www.nature.com", "desc": "The world's premier multidisciplinary science journal — breakthrough research across all fields"},
                    {"name": "Science (AAAS)", "url": "https://www.science.org", "desc": "Peer-reviewed research and news from the American Association for the Advancement of Science"},
                    {"name": "Cell", "url": "https://www.cell.com", "desc": "Leading journal for molecular biology, genetics, and cell biology research"},
                    {"name": "PubMed", "url": "https://pubmed.ncbi.nlm.nih.gov", "desc": "Free database of 36M+ biomedical research papers — search any health or science topic"},
                    {"name": "Quanta Magazine", "url": "https://www.quantamagazine.org", "desc": "Accessible, beautifully written coverage of math, physics, and biology research"},
                ],
            },
            {
                "title": "Longevity Science",
                "resources": [
                    {"name": "Lifespan.io", "url": "https://www.lifespan.io", "desc": "Longevity research news, rejuvenation science tracker, and clinical trial database"},
                    {"name": "Longevity Technology", "url": "https://longevity.technology", "desc": "Industry news on longevity biotech, startups, and anti-aging interventions"},
                    {"name": "David Sinclair Lab", "url": "https://sinclair.hms.harvard.edu", "desc": "Harvard geneticist's lab — NAD+, sirtuins, and aging reversal research"},
                    {"name": "SENS Research Foundation", "url": "https://www.sens.org", "desc": "Aubrey de Grey's foundation funding damage-repair approaches to aging"},
                    {"name": "ClinicalTrials.gov", "url": "https://clinicaltrials.gov", "desc": "Database of 450,000+ clinical studies — search for longevity, anti-aging, and health trials"},
                ],
            },
            {
                "title": "Health & Nutrition",
                "resources": [
                    {"name": "Examine.com", "url": "https://examine.com", "desc": "Evidence-based supplement and nutrition research — no ads, no hype, just science"},
                    {"name": "Healthline", "url": "https://www.healthline.com", "desc": "Medical information reviewed by doctors — conditions, treatments, and wellness"},
                    {"name": "Nutritionfacts.org", "url": "https://nutritionfacts.org", "desc": "Dr. Michael Greger's free database of nutrition research — video summaries of studies"},
                    {"name": "Harvard Health", "url": "https://www.health.harvard.edu", "desc": "Health information from Harvard Medical School — trusted, peer-reviewed content"},
                    {"name": "Mayo Clinic", "url": "https://www.mayoclinic.org", "desc": "Patient-friendly health information from one of the world's top medical centers"},
                ],
            },
            {
                "title": "Biotech & CRISPR",
                "resources": [
                    {"name": "STAT News", "url": "https://www.statnews.com", "desc": "Health and medicine journalism — biotech, pharma, and life science industry coverage"},
                    {"name": "Genetic Engineering News", "url": "https://www.genengnews.com", "desc": "Biotech industry news — CRISPR, gene therapy, cell therapy, and drug development"},
                    {"name": "The CRISPR Journal", "url": "https://www.liebertpub.com/loi/crispr", "desc": "Peer-reviewed journal dedicated to CRISPR gene editing research and applications"},
                    {"name": "Broad Institute", "url": "https://www.broadinstitute.org", "desc": "MIT-Harvard genomics research institute — home of key CRISPR innovations"},
                ],
            },
            {
                "title": "Mental Health & Neuroscience",
                "resources": [
                    {"name": "Huberman Lab", "url": "https://www.hubermanlab.com", "desc": "Stanford neuroscientist Andrew Huberman's podcast and protocols for brain and body optimization"},
                    {"name": "BrainFacts.org", "url": "https://www.brainfacts.org", "desc": "Neuroscience education from the Society for Neuroscience — brain basics to cutting-edge research"},
                    {"name": "NIMH", "url": "https://www.nimh.nih.gov", "desc": "National Institute of Mental Health — research, statistics, and clinical trial information"},
                    {"name": "Neuroscience News", "url": "https://neurosciencenews.com", "desc": "Daily neuroscience research summaries — psychology, AI, and brain science"},
                ],
            },
        ],
        "tools": [
            {"name": "PubMed", "url": "https://pubmed.ncbi.nlm.nih.gov", "desc": "Search 36M+ biomedical papers — the essential tool for finding health and science research", "badge": "Free"},
            {"name": "Examine.com", "url": "https://examine.com", "desc": "Look up any supplement or nutrient — see what the research actually says, not marketing claims", "badge": "Free tier"},
            {"name": "Cronometer", "url": "https://cronometer.com", "desc": "Track nutrition, micronutrients, and macros with the most detailed food database available", "badge": "Free tier"},
            {"name": "Oura Ring", "url": "https://ouraring.com", "desc": "Sleep, recovery, and readiness tracking — used by longevity researchers for personal data", "badge": "Hardware"},
            {"name": "InsideTracker", "url": "https://www.insidetracker.com", "desc": "Blood biomarker analysis with personalized health recommendations based on your biology", "badge": "Paid"},
        ],
        "faq": [
            {"q": "What is healthspan vs lifespan?", "a": "Lifespan is how long you live. Healthspan is how long you live in good health — free from chronic disease and disability. Longevity researchers increasingly focus on healthspan because living to 100 matters less if the last 20 years are spent in poor health. The goal is to compress morbidity — keeping you healthy and active until very late in life."},
            {"q": "What is CRISPR?", "a": "CRISPR (Clustered Regularly Interspaced Short Palindromic Repeats) is a revolutionary gene-editing tool that allows scientists to precisely cut, delete, or modify DNA sequences. Think of it as molecular scissors with a GPS — you can target a specific gene and change it. It's being used to develop treatments for sickle cell disease, certain cancers, and inherited genetic conditions. The 2020 Nobel Prize in Chemistry was awarded for this technology."},
            {"q": "What are senolytics?", "a": "Senolytics are drugs that selectively destroy senescent cells — 'zombie cells' that have stopped dividing but refuse to die. These cells accumulate with age and secrete inflammatory signals that damage surrounding tissue, contributing to aging and age-related diseases. Senolytic drugs like dasatinib + quercetin and fisetin are being studied in clinical trials. Early results suggest they may improve physical function and reduce inflammation in older adults."},
            {"q": "What is NAD+ and why does it matter?", "a": "NAD+ (Nicotinamide Adenine Dinucleotide) is a coenzyme found in every cell that's essential for energy metabolism, DNA repair, and cellular signaling. NAD+ levels decline with age — by age 50, you may have half the NAD+ you had at 20. Researchers like David Sinclair believe boosting NAD+ (via precursors like NMN or NR) could slow aging. Clinical trials are underway, but results are still preliminary."},
            {"q": "What is a clinical trial?", "a": "A clinical trial is a research study that tests a medical treatment, drug, or intervention in human volunteers. Trials progress through phases: Phase 1 tests safety (small group), Phase 2 tests effectiveness (larger group), Phase 3 compares to existing treatments (thousands of participants), and Phase 4 monitors long-term effects after approval. You can search for trials at ClinicalTrials.gov — some actively recruit participants."},
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
        "podcast_image": "assets/covers/environmental-intelligence.jpg",
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
        "resource_categories": [
            {
                "title": "Federal Regulation",
                "resources": [
                    {"name": "Canada Gazette", "url": "https://www.gazette.gc.ca", "desc": "Official source for proposed and enacted federal regulations — Part I (proposals) and Part II (final)"},
                    {"name": "ECCC", "url": "https://www.canada.ca/en/environment-climate-change.html", "desc": "Environment and Climate Change Canada — federal environmental policy, enforcement, and data"},
                    {"name": "CEPA Registry", "url": "https://www.canada.ca/en/environment-climate-change/services/canadian-environmental-protection-act-registry.html", "desc": "Canadian Environmental Protection Act registry — substance assessments and regulations"},
                    {"name": "Impact Assessment Agency", "url": "https://www.canada.ca/en/impact-assessment-agency.html", "desc": "Federal impact assessments for major projects — pipelines, mines, and infrastructure"},
                    {"name": "CCME", "url": "https://ccme.ca", "desc": "Canadian Council of Ministers of the Environment — national guidelines, standards, and water quality objectives"},
                ],
            },
            {
                "title": "BC & Provincial",
                "resources": [
                    {"name": "BC Site Remediation", "url": "https://www2.gov.bc.ca/gov/content/environment/air-land-water/site-remediation", "desc": "BC contaminated sites registry, CSR protocols, technical guidance, and site profiles"},
                    {"name": "BC ENV", "url": "https://www2.gov.bc.ca/gov/content/environment", "desc": "BC Ministry of Environment — permits, compliance, air/water quality, and wildlife"},
                    {"name": "BC Environmental Assessment Office", "url": "https://www.projects.eao.gov.bc.ca", "desc": "Track BC environmental assessments for major projects — mines, LNG, pipelines"},
                    {"name": "Alberta Energy Regulator", "url": "https://www.aer.ca", "desc": "Alberta's energy and environmental regulator — oil sands, pipelines, and reclamation"},
                    {"name": "Ontario MOE", "url": "https://www.ontario.ca/page/ministry-environment-conservation-parks", "desc": "Ontario environmental regulation — brownfields, air quality, and water resources"},
                ],
            },
            {
                "title": "Professional Associations",
                "resources": [
                    {"name": "CSAP (BC)", "url": "https://csapsociety.bc.ca", "desc": "Contaminated Sites Approved Professionals Society — BC's roster of qualified environmental professionals"},
                    {"name": "ECO Canada", "url": "https://eco.ca", "desc": "Environmental careers, training, and professional development across Canada"},
                    {"name": "APEGA", "url": "https://www.apega.ca", "desc": "Association of Professional Engineers and Geoscientists of Alberta — licensing and practice"},
                    {"name": "EGBC", "url": "https://www.egbc.ca", "desc": "Engineers and Geoscientists BC — professional regulation for BC environmental practitioners"},
                ],
            },
            {
                "title": "Contaminated Sites & Remediation",
                "resources": [
                    {"name": "Federal Contaminated Sites Inventory", "url": "https://www.tbs-sct.canada.ca/fcsi-rscf/home-accueil-eng.aspx", "desc": "Database of 24,000+ federal contaminated sites across Canada — searchable by province"},
                    {"name": "ITRC", "url": "https://www.itrcweb.org", "desc": "Interstate Technology and Regulatory Council — technical guidance on PFAS, vapour intrusion, and remediation"},
                    {"name": "CLU-IN", "url": "https://clu-in.org", "desc": "US EPA's contaminated site cleanup information — technologies, training, and case studies"},
                    {"name": "ASTM Environmental Standards", "url": "https://www.astm.org/products-services/standards-and-publications/standards/environmental-standards.html", "desc": "Phase I/II ESA standards (E1527, E1903) and environmental assessment protocols"},
                    {"name": "RemTech Symposium", "url": "https://www.esaa.org/remtech/", "desc": "Canada's premier remediation technology conference — ESAA annual event in Banff"},
                ],
            },
            {
                "title": "Environmental Science & Journalism",
                "resources": [
                    {"name": "The Narwhal", "url": "https://thenarwhal.ca", "desc": "Independent Canadian environmental investigative journalism — in-depth, evidence-based"},
                    {"name": "Ecojustice", "url": "https://ecojustice.ca", "desc": "Canada's leading environmental law charity — legal actions and policy advocacy"},
                    {"name": "Nature Climate Change", "url": "https://www.nature.com/nclimate/", "desc": "Peer-reviewed journal on climate change science, impacts, and policy"},
                    {"name": "Inside Climate News", "url": "https://insideclimatenews.org", "desc": "Pulitzer Prize-winning climate and energy journalism — US and global coverage"},
                ],
            },
        ],
        "tools": [
            {"name": "BC CSR Database", "url": "https://www2.gov.bc.ca/gov/content/environment/air-land-water/site-remediation/contaminated-sites", "desc": "Search BC's contaminated sites registry — site profiles, risk classifications, and remediation status", "badge": "Free"},
            {"name": "CCME Guidelines", "url": "https://ccme.ca/en/current-activities/canadian-environmental-quality-guidelines", "desc": "Canadian soil, water, and sediment quality guidelines — the foundation for site assessments", "badge": "Free"},
            {"name": "ERIS", "url": "https://www.eris.com", "desc": "Environmental risk information services — Phase I ESA database searches for Canadian and US sites", "badge": "Paid"},
            {"name": "Canada Gazette Alerts", "url": "https://www.gazette.gc.ca/cg-gc/subscribe-abonner-eng.html", "desc": "Subscribe to alerts for new federal environmental regulations and amendments", "badge": "Free"},
            {"name": "ArcGIS Environmental", "url": "https://www.esri.com/en-us/industries/environment/overview", "desc": "GIS mapping for environmental data — contaminated sites, watersheds, and monitoring wells", "badge": "Paid"},
        ],
        "faq": [
            {"q": "What is CEPA?", "a": "The Canadian Environmental Protection Act (CEPA 1999) is Canada's primary federal environmental law. It governs the assessment and management of toxic substances, pollution prevention, and environmental emergencies. CEPA gives the federal government authority to regulate chemicals, fuels, and wastes that pose risks to human health or the environment. It was significantly updated in 2023 (Bill S-5) to recognize the right to a healthy environment."},
            {"q": "What is a contaminated site?", "a": "A contaminated site is land or water where hazardous substances exceed regulatory standards and may pose risks to human health or the environment. Common contaminants include petroleum hydrocarbons (from gas stations), heavy metals (from industrial operations), chlorinated solvents (from dry cleaners), and PFAS (from firefighting foam). In BC, the Contaminated Sites Regulation (CSR) defines standards and the process for investigation, risk assessment, and remediation."},
            {"q": "What are PFAS?", "a": "PFAS (Per- and Polyfluoroalkyl Substances) are a group of 12,000+ synthetic chemicals known as 'forever chemicals' because they don't break down in the environment. Used since the 1950s in non-stick coatings, food packaging, firefighting foam, and waterproof clothing, PFAS contaminate groundwater, soil, and drinking water worldwide. Health concerns include cancer, thyroid disease, and immune system effects. Canada is developing federal PFAS regulations, and remediation is extremely challenging and costly."},
            {"q": "What is the CSR (Contaminated Sites Regulation)?", "a": "BC's Contaminated Sites Regulation sets numerical standards for soil, groundwater, vapour, and sediment quality. It defines when a site is 'contaminated' (exceeds standards) and the process for investigation, risk assessment, and remediation. Key concepts include: site profiles (disclosure triggers), preliminary and detailed site investigations, risk-based standards vs. generic standards, and certificates of compliance issued upon successful remediation."},
            {"q": "What does 'remediation' mean?", "a": "Remediation is the process of cleaning up contaminated land or groundwater to make it safe for its intended use. Methods include: excavation and disposal (dig-and-dump), in-situ treatment (treating contamination in place using bioremediation, chemical oxidation, or thermal treatment), pump-and-treat (extracting and treating groundwater), and risk management (containing contamination with barriers or institutional controls). The approach depends on contaminant type, site geology, and intended land use."},
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
        "podcast_image": "assets/covers/models-agents.jpg",
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
        "resource_categories": [
            {
                "title": "AI Labs & Research",
                "resources": [
                    {"name": "OpenAI", "url": "https://openai.com/research", "desc": "GPT, DALL-E, and Sora — research and blog posts from the makers of ChatGPT"},
                    {"name": "Anthropic", "url": "https://www.anthropic.com/research", "desc": "Claude model family — constitutional AI, safety research, and responsible scaling"},
                    {"name": "Google DeepMind", "url": "https://deepmind.google/research/", "desc": "Gemini, AlphaFold, and fundamental AI research — one of the world's top AI labs"},
                    {"name": "Meta AI (FAIR)", "url": "https://ai.meta.com/research/", "desc": "Llama open-source models, computer vision, and fundamental research"},
                    {"name": "Mistral AI", "url": "https://mistral.ai", "desc": "European AI lab building efficient open-weight models — Mixtral and Mistral Large"},
                    {"name": "arXiv AI", "url": "https://arxiv.org/list/cs.AI/recent", "desc": "Latest AI research preprints — papers drop here before journal publication"},
                ],
            },
            {
                "title": "Developer Tools & Frameworks",
                "resources": [
                    {"name": "Hugging Face", "url": "https://huggingface.co", "desc": "The GitHub of ML — 500K+ models, datasets, and Spaces demos. Essential for any AI developer"},
                    {"name": "LangChain", "url": "https://www.langchain.com", "desc": "Framework for building LLM-powered applications — chains, agents, and retrieval pipelines"},
                    {"name": "LlamaIndex", "url": "https://www.llamaindex.ai", "desc": "Data framework for LLM apps — connect your data to language models with RAG pipelines"},
                    {"name": "Ollama", "url": "https://ollama.com", "desc": "Run open-source LLMs locally — Llama, Mistral, Phi, and more on your own hardware"},
                    {"name": "Vercel AI SDK", "url": "https://sdk.vercel.ai", "desc": "TypeScript toolkit for building AI-powered web applications with streaming UI"},
                    {"name": "Weights & Biases", "url": "https://wandb.ai", "desc": "ML experiment tracking, model versioning, and dataset management for AI teams"},
                ],
            },
            {
                "title": "Benchmarks & Leaderboards",
                "resources": [
                    {"name": "LM Arena (Chatbot Arena)", "url": "https://lmarena.ai", "desc": "Crowdsourced LLM rankings — users vote on which model gives better responses"},
                    {"name": "Open LLM Leaderboard", "url": "https://huggingface.co/spaces/HuggingFaceH4/open_llm_leaderboard", "desc": "Hugging Face's benchmark for open-source models — MMLU, ARC, HellaSwag scores"},
                    {"name": "Papers With Code", "url": "https://paperswithcode.com", "desc": "ML papers with code implementations and state-of-the-art benchmarks across tasks"},
                    {"name": "Artificial Analysis", "url": "https://artificialanalysis.ai", "desc": "Compare LLM providers on speed, cost, and quality — essential for API selection"},
                ],
            },
            {
                "title": "Newsletters & Analysis",
                "resources": [
                    {"name": "Latent Space", "url": "https://www.latent.space", "desc": "AI engineering podcast and newsletter — deep dives with builders and researchers"},
                    {"name": "The Decoder", "url": "https://the-decoder.com", "desc": "Daily AI news focused on practical developments, model releases, and tools"},
                    {"name": "Import AI", "url": "https://importai.substack.com", "desc": "Jack Clark's weekly AI newsletter — policy, research, and industry analysis"},
                    {"name": "The Batch (deeplearning.ai)", "url": "https://www.deeplearning.ai/the-batch/", "desc": "Andrew Ng's weekly AI newsletter — news, insights, and research highlights"},
                    {"name": "Simon Willison's Weblog", "url": "https://simonwillison.net", "desc": "Prolific AI practitioner's blog — LLM tools, prompt engineering, and practical AI"},
                ],
            },
            {
                "title": "Open-Source Ecosystem",
                "resources": [
                    {"name": "Ollama", "url": "https://ollama.com", "desc": "Run Llama 3, Mistral, Phi, and other open models locally with one command"},
                    {"name": "LM Studio", "url": "https://lmstudio.ai", "desc": "Desktop app for running local LLMs — GUI for model discovery, download, and chat"},
                    {"name": "vLLM", "url": "https://github.com/vllm-project/vllm", "desc": "High-throughput LLM serving engine — the standard for production model deployment"},
                    {"name": "llama.cpp", "url": "https://github.com/ggerganov/llama.cpp", "desc": "Run LLMs on CPU/GPU with minimal resources — the engine behind most local AI apps"},
                    {"name": "Open WebUI", "url": "https://github.com/open-webui/open-webui", "desc": "Self-hosted ChatGPT-like interface for local models — works with Ollama out of the box"},
                ],
            },
        ],
        "tools": [
            {"name": "Claude", "url": "https://claude.ai", "desc": "Anthropic's AI assistant — strong at reasoning, coding, and long-context analysis", "badge": "Free tier"},
            {"name": "ChatGPT", "url": "https://chat.openai.com", "desc": "OpenAI's conversational AI — GPT-4o with vision, code, and browsing capabilities", "badge": "Free tier"},
            {"name": "Cursor", "url": "https://cursor.com", "desc": "AI-first code editor — autocomplete, chat, and codebase-aware assistance built on LLMs", "badge": "Free tier"},
            {"name": "Hugging Face", "url": "https://huggingface.co", "desc": "Try 500K+ models in your browser — text, image, audio, and multimodal demos", "badge": "Free"},
            {"name": "Ollama", "url": "https://ollama.com", "desc": "Run open-source LLMs locally — one command to download and chat with Llama, Mistral, Phi", "badge": "Free"},
            {"name": "Perplexity", "url": "https://www.perplexity.ai", "desc": "AI-powered search engine — asks follow-up questions and cites sources for every answer", "badge": "Free tier"},
        ],
        "faq": [
            {"q": "What is an LLM?", "a": "A Large Language Model (LLM) is an AI system trained on vast amounts of text data to understand and generate human language. Models like GPT-4, Claude, Gemini, and Llama are LLMs. They work by predicting the most likely next token (word piece) in a sequence, but this simple mechanism produces remarkably capable systems that can write code, analyze documents, reason through problems, and hold conversations."},
            {"q": "What is an AI agent?", "a": "An AI agent is a system that uses an LLM as its 'brain' to autonomously plan and execute multi-step tasks. Unlike a simple chatbot that responds to one message at a time, an agent can break down complex goals, use tools (web search, code execution, APIs), observe results, and iterate. Examples include coding agents (Cursor, Claude Code), research agents (Perplexity), and browser agents that navigate websites on your behalf."},
            {"q": "What is RAG?", "a": "Retrieval-Augmented Generation (RAG) is a technique that gives LLMs access to external knowledge by retrieving relevant documents before generating a response. Instead of relying solely on training data, a RAG system searches a database (using vector embeddings), finds relevant passages, and includes them in the LLM's context. This reduces hallucinations and lets you build AI that can answer questions about your own documents, codebase, or data."},
            {"q": "What is fine-tuning?", "a": "Fine-tuning is the process of further training a pre-trained LLM on a specific dataset to specialize it for a particular task or domain. For example, you might fine-tune Llama on medical literature to create a healthcare-specific model. It's more expensive than RAG but can teach the model new behaviors, styles, or domain expertise that prompt engineering alone can't achieve. Most developers start with RAG and only fine-tune when necessary."},
            {"q": "What is MCP (Model Context Protocol)?", "a": "MCP is an open protocol (created by Anthropic) that standardizes how AI models connect to external data sources and tools. Think of it as a USB-C port for AI — instead of building custom integrations for every tool, MCP provides a universal interface. An MCP server can expose databases, APIs, file systems, or any tool, and any MCP-compatible AI client can use them. It's rapidly becoming the standard for agent tool connectivity."},
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
        "podcast_image": "assets/covers/models-agents-beginners.jpg",
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
        "resource_categories": [
            {
                "title": "Start Here — Free Courses",
                "resources": [
                    {"name": "Google AI Essentials", "url": "https://grow.google/ai-essentials/", "desc": "Free introductory AI course from Google — no experience needed, earn a certificate"},
                    {"name": "Elements of AI", "url": "https://www.elementsofai.com", "desc": "Free online course from University of Helsinki — understand AI concepts without coding"},
                    {"name": "Khan Academy AI", "url": "https://www.khanacademy.org/computing/ai-for-everyone", "desc": "AI for Everyone — free, self-paced lessons from Khan Academy"},
                    {"name": "Crash Course AI", "url": "https://www.youtube.com/playlist?list=PL8dPuuaLjXtO65LeD2p4_Sb5XQ51par_b", "desc": "20 fun video episodes explaining AI concepts — great for visual learners"},
                    {"name": "AI for Everyone (Coursera)", "url": "https://www.coursera.org/learn/ai-for-everyone", "desc": "Andrew Ng's non-technical AI course — understand what AI can and can't do"},
                ],
            },
            {
                "title": "Try AI Right Now",
                "resources": [
                    {"name": "ChatGPT", "url": "https://chat.openai.com", "desc": "The most popular AI chatbot — ask questions, write stories, get homework help, or learn to code"},
                    {"name": "Claude", "url": "https://claude.ai", "desc": "Anthropic's AI assistant — excellent at explaining concepts, writing, and careful reasoning"},
                    {"name": "Google Gemini", "url": "https://gemini.google.com", "desc": "Google's AI — integrated with Search, can analyze images, and create content"},
                    {"name": "Microsoft Copilot", "url": "https://copilot.microsoft.com", "desc": "Free AI assistant from Microsoft — chat, create images, and get help with tasks"},
                    {"name": "Hugging Face Spaces", "url": "https://huggingface.co/spaces", "desc": "Try thousands of AI demos in your browser — image generation, translation, and more"},
                ],
            },
            {
                "title": "Hands-On Projects",
                "resources": [
                    {"name": "Machine Learning for Kids", "url": "https://machinelearningforkids.co.uk", "desc": "Build AI projects with Scratch — teach a computer to recognize images, text, and sounds"},
                    {"name": "Teachable Machine", "url": "https://teachablemachine.withgoogle.com", "desc": "Google's tool to train your own AI model in the browser — no code needed, instant results"},
                    {"name": "AI Experiments with Google", "url": "https://experiments.withgoogle.com/collection/ai", "desc": "Interactive AI demos — draw with AI, make music, play games, and explore neural networks"},
                    {"name": "Runway ML", "url": "https://runwayml.com", "desc": "Create AI-generated videos, images, and effects — the creative playground for AI art"},
                ],
            },
            {
                "title": "YouTube Channels & Creators",
                "resources": [
                    {"name": "3Blue1Brown", "url": "https://www.youtube.com/@3blue1brown", "desc": "Beautiful math visualizations that explain neural networks and machine learning intuitively"},
                    {"name": "Two Minute Papers", "url": "https://www.youtube.com/@TwoMinutePapers", "desc": "Quick, exciting summaries of the latest AI research — 'What a time to be alive!'"},
                    {"name": "Fireship", "url": "https://www.youtube.com/@Fireship", "desc": "Fast-paced tech explainers — AI news in 100 seconds, coding tutorials, and developer culture"},
                    {"name": "Matt Wolfe", "url": "https://www.youtube.com/@maboroshi", "desc": "Weekly AI tool roundups, tutorials, and news — perfect for staying current as a beginner"},
                ],
            },
            {
                "title": "Books & Reading",
                "resources": [
                    {"name": "Life 3.0 (Max Tegmark)", "url": "https://www.goodreads.com/book/show/34272565-life-3-0", "desc": "Accessible exploration of how AI will transform society — great for teens and adults"},
                    {"name": "Hello World (Hannah Fry)", "url": "https://www.goodreads.com/book/show/38212157-hello-world", "desc": "How algorithms are changing our lives — fun, readable, and thought-provoking"},
                    {"name": "AI 2041 (Kai-Fu Lee)", "url": "https://www.goodreads.com/book/show/56377201-ai-2041", "desc": "Ten short stories imagining AI's impact 15 years from now — science fiction meets real science"},
                    {"name": "You Look Like a Thing and I Love You", "url": "https://www.goodreads.com/book/show/44286534", "desc": "Hilarious, illustrated guide to how AI works (and fails) — by AI researcher Janelle Shane"},
                ],
            },
        ],
        "tools": [
            {"name": "ChatGPT", "url": "https://chat.openai.com", "desc": "Start here — ask anything, get homework help, write stories, or learn to code with AI", "badge": "Free"},
            {"name": "Claude", "url": "https://claude.ai", "desc": "Great for learning — ask it to explain any topic like you're a beginner. Patient and thorough", "badge": "Free"},
            {"name": "Google Gemini", "url": "https://gemini.google.com", "desc": "Google's AI — analyze images, get study help, and explore topics with web search built in", "badge": "Free"},
            {"name": "Teachable Machine", "url": "https://teachablemachine.withgoogle.com", "desc": "Train your own AI in minutes — teach it to recognize your face, gestures, or sounds. No code!", "badge": "Free"},
            {"name": "Canva Magic Studio", "url": "https://www.canva.com/ai-image-generator/", "desc": "Generate images, presentations, and designs with AI — great for school projects", "badge": "Free tier"},
        ],
        "faq": [
            {"q": "What is AI?", "a": "Artificial Intelligence (AI) is technology that enables computers to perform tasks that normally require human intelligence — like understanding language, recognizing images, making decisions, and learning from experience. Modern AI systems learn from huge amounts of data rather than following explicit rules. When you use ChatGPT, Google Translate, or Instagram filters, you're using AI."},
            {"q": "What is a 'model'?", "a": "An AI model is the trained 'brain' of an AI system. It's created by feeding a computer program enormous amounts of data and letting it find patterns. For example, a language model like GPT or Claude was trained on billions of pages of text, so it learned how language works. The word 'model' just means 'a simplified representation of something' — an AI model is a simplified representation of human knowledge and reasoning."},
            {"q": "Is AI dangerous?", "a": "Like any powerful technology, AI has risks and benefits. Current AI can spread misinformation, create deepfakes, and be biased against certain groups. Long-term, researchers debate whether very advanced AI could be hard to control. But AI also helps doctors diagnose diseases, scientists discover new medicines, and students learn faster. The key is developing AI responsibly — with safety research, regulation, and public awareness. Understanding AI helps you use it wisely."},
            {"q": "Can AI replace my job?", "a": "AI is more likely to change jobs than eliminate them entirely. It's very good at repetitive, pattern-based tasks (data entry, basic writing, image sorting) but struggles with creativity, empathy, physical dexterity, and complex judgment. Most experts predict AI will become a powerful tool that makes workers more productive — like how calculators didn't replace mathematicians but changed what they focus on. The best strategy is learning to work WITH AI, not compete against it."},
            {"q": "What's the difference between ChatGPT and Google Gemini?", "a": "Both are AI chatbots powered by large language models, but they're made by different companies with different strengths. ChatGPT (by OpenAI) was the first widely popular AI chatbot and is known for creative writing and coding. Gemini (by Google) is integrated with Google Search and services, so it's good at finding current information. Claude (by Anthropic) is known for careful reasoning and safety. Try all three — they're all free to use — and see which you prefer!"},
        ],
    },
    "finansy_prosto": {
        "name": "Финансы Просто",
        "slug": "finansy_prosto",
        "description": "Ежедневный подкаст о финансах на русском языке для женщин в Канаде.",
        "show_page": "ru/finansy-prosto.html",
        "summaries_page": "ru/finansy-prosto-summaries.html",
        "json_path": "digests/finansy_prosto/summaries_finansy_prosto.json",
        "json_format": "wrapped",
        "rss_file": "finansy_prosto_podcast.rss",
        "podcast_image": "assets/covers/finansy-prosto.jpg",
        "x_account": None,
        "brand_color": "#EC4899",
        "brand_color_dark": "#DB2777",
        "tagline": "Finances Made Simple.",
        "hero_tagline": "Финансы — просто и понятно.",
        "schedule": "Daily",
        "episode_length": "~12 min",
        "about_text": "Ежедневный подкаст о финансах на русском языке для женщин в Канаде. Ведущая Оля объясняет инвестиции, сбережения, бюджет и финансовую грамотность — просто и понятно.",
        "about_host": "Ведущая — Оля из Ванкувера. Каждый выпуск — практические советы, новости и ресурсы для финансовой независимости.",
        "description_long": "Ежедневный подкаст о финансах на русском языке для женщин в Канаде — инвестиции, сбережения, бюджет и финансовая грамотность просто и понятно.",
        "related_show": "privet_russian",
        "related_reason": "If you enjoy Финансы Просто, you might also like Привет, Русский! — learn Russian through fun, themed episodes.",
        "apple_podcasts_url": None,
        "theme_color": "#EC4899",
        "meta_description": "Финансы Просто — ежедневный подкаст о финансах на русском языке для женщин в Канаде. Инвестиции, сбережения, бюджет.",
        "meta_keywords": "финансы, подкаст, русский, Канада, инвестиции, сбережения, бюджет, финансовая грамотность",
        "audience": "Для русскоговорящих женщин в Канаде, которые хотят разобраться в финансах — от TFSA до ипотеки.",
        "source_highlights": ["MoneySense", "Financial Post", "FinTolk", "Tinkoff Journal"],
        "resource_categories": [
            {
                "title": "Канадские финансы",
                "resources": [
                    {"name": "MoneySense", "url": "https://www.moneysense.ca", "desc": "Канадский портал о финансах — инвестиции, пенсия, ипотека и налоги"},
                    {"name": "Financial Post", "url": "https://financialpost.com", "desc": "Финансовые новости Канады — рынки, экономика и личные финансы"},
                    {"name": "Globe and Mail Investing", "url": "https://www.theglobeandmail.com/investing/", "desc": "Инвестиционные новости и аналитика от ведущей канадской газеты"},
                    {"name": "Canadian Couch Potato", "url": "https://canadiancouchpotato.com", "desc": "Пассивное инвестирование для канадцев — модельные портфели из ETF"},
                    {"name": "Young and Thrifty", "url": "https://youngandthrifty.ca", "desc": "Финансовые советы для молодых канадцев — бюджет, сбережения, инвестиции"},
                ],
            },
            {
                "title": "Инвестиционные платформы",
                "resources": [
                    {"name": "Wealthsimple", "url": "https://www.wealthsimple.com", "desc": "Инвестиционная платформа для канадцев — TFSA, RRSP, торговля без комиссии"},
                    {"name": "Questrade", "url": "https://www.questrade.com", "desc": "Канадский онлайн-брокер — ETF без комиссии, TFSA, RRSP, RESP"},
                    {"name": "Interactive Brokers", "url": "https://www.interactivebrokers.ca", "desc": "Профессиональная торговая платформа — низкие комиссии, доступ к мировым рынкам"},
                    {"name": "EQ Bank", "url": "https://www.eqbank.ca", "desc": "Высокие ставки по сберегательным счетам и GIC — без ежемесячных комиссий"},
                ],
            },
            {
                "title": "Калькуляторы и инструменты",
                "resources": [
                    {"name": "RateHub", "url": "https://www.ratehub.ca", "desc": "Сравнение ипотечных ставок, кредитных карт и сберегательных счетов в Канаде"},
                    {"name": "Borrowell", "url": "https://www.borrowell.com", "desc": "Бесплатная проверка кредитного рейтинга и персональные финансовые рекомендации"},
                    {"name": "Wealthsimple Tax", "url": "https://www.wealthsimple.com/en-ca/tax", "desc": "Бесплатная подача налоговой декларации онлайн — простой и понятный интерфейс"},
                    {"name": "CRA My Account", "url": "https://www.canada.ca/en/revenue-agency/services/e-services/digital-services-individuals/account-individuals.html", "desc": "Личный кабинет в налоговой — проверка возвратов, лимитов TFSA/RRSP"},
                ],
            },
            {
                "title": "Государственные ресурсы",
                "resources": [
                    {"name": "Canada.ca Benefits", "url": "https://www.canada.ca/en/services/benefits.html", "desc": "Государственные пособия — CCB, EI, CPP, OAS, кредиты на детей и налоговые льготы"},
                    {"name": "Financial Consumer Agency", "url": "https://www.canada.ca/en/financial-consumer-agency.html", "desc": "Защита прав потребителей финансовых услуг — жалобы, права и образование"},
                    {"name": "BC Housing", "url": "https://www.bchousing.org", "desc": "Программы доступного жилья в BC — субсидии, аренда, первый дом"},
                    {"name": "Settlement.org", "url": "https://settlement.org/ontario/employment/financial-information/", "desc": "Финансовая информация для иммигрантов — банки, налоги и кредит в Канаде"},
                ],
            },
            {
                "title": "Финансовое образование",
                "resources": [
                    {"name": "Tinkoff Journal", "url": "https://journal.tinkoff.ru", "desc": "Российский портал о финансовой грамотности — инвестиции, налоги, экономика (на русском)"},
                    {"name": "FinTolk", "url": "https://fintolk.pro", "desc": "Финансы простым языком на русском — статьи, калькуляторы и советы"},
                    {"name": "Investopedia", "url": "https://www.investopedia.com", "desc": "Энциклопедия инвестиций и финансов — термины, стратегии и обучение (на английском)"},
                    {"name": "Khan Academy Finance", "url": "https://www.khanacademy.org/economics-finance-domain", "desc": "Бесплатные уроки по экономике и финансам — от базовых до продвинутых тем"},
                ],
            },
        ],
        "tools": [
            {"name": "Wealthsimple", "url": "https://www.wealthsimple.com", "desc": "Инвестируйте без комиссии — TFSA, RRSP, торговля акциями и ETF для начинающих", "badge": "Бесплатно"},
            {"name": "Questrade", "url": "https://www.questrade.com", "desc": "Канадский брокер — покупайте ETF без комиссии, управляйте RRSP и RESP", "badge": "Бесплатно"},
            {"name": "YNAB", "url": "https://www.ynab.com", "desc": "You Need A Budget — лучшее приложение для бюджетирования, помогает контролировать расходы", "badge": "Пробный период"},
            {"name": "Borrowell", "url": "https://www.borrowell.com", "desc": "Бесплатная проверка кредитного рейтинга — следите за вашим Equifax score", "badge": "Бесплатно"},
            {"name": "Wealthsimple Tax", "url": "https://www.wealthsimple.com/en-ca/tax", "desc": "Подайте налоговую декларацию бесплатно — простой интерфейс на английском", "badge": "Бесплатно"},
        ],
        "faq": [
            {"q": "Что такое TFSA?", "a": "Tax-Free Savings Account (TFSA) — это канадский сберегательный счёт, на котором вся прибыль от инвестиций не облагается налогом. Каждый год правительство увеличивает лимит взносов (в 2026 году — $7,000). Вы можете инвестировать в акции, ETF, облигации и GIC внутри TFSA, и все доходы — дивиденды, проценты, прирост капитала — остаются полностью вашими. Это один из лучших инструментов для долгосрочных сбережений в Канаде."},
            {"q": "Что такое RRSP?", "a": "Registered Retirement Savings Plan (RRSP) — это пенсионный сберегательный план. Главное отличие от TFSA: взносы в RRSP уменьшают ваш налогооблагаемый доход в текущем году (вы получаете налоговый возврат), но при снятии денег на пенсии вы платите налог. RRSP выгоден, если сейчас ваш доход (и налоговая ставка) выше, чем будет на пенсии. Лимит взносов — 18% от заработка прошлого года."},
            {"q": "Как начать инвестировать в Канаде?", "a": "Шаг 1: Откройте TFSA (максимально используйте налоговые льготы). Шаг 2: Выберите платформу — Wealthsimple (самая простая для начинающих) или Questrade (больше опций). Шаг 3: Начните с ETF широкого рынка, например XEQT или VGRO — они автоматически диверсифицированы по всему миру. Шаг 4: Инвестируйте регулярно (даже $50-100 в месяц), не пытайтесь угадать рынок. Время на рынке важнее, чем тайминг рынка."},
            {"q": "Что такое GIC?", "a": "Guaranteed Investment Certificate (GIC) — это гарантированный инвестиционный сертификат. Вы вкладываете деньги в банк на фиксированный срок (от 30 дней до 5 лет), и банк гарантирует возврат + проценты. GIC застрахованы CDIC до $100,000. Ставки зависят от срока и банка — сравнивайте на RateHub.ca. GIC подходят для краткосрочных сбережений (на первый взнос, фонд безопасности), но для долгосрочных целей ETF обычно приносят больше."},
            {"q": "Что такое кредитный рейтинг?", "a": "Кредитный рейтинг (credit score) — это число от 300 до 900, показывающее вашу кредитоспособность. В Канаде два бюро — Equifax и TransUnion. Рейтинг выше 700 считается хорошим, выше 750 — отличным. Он влияет на одобрение ипотеки, кредитных карт и процентные ставки. Чтобы улучшить рейтинг: платите вовремя, используйте менее 30% кредитного лимита, не закрывайте старые карты. Проверяйте бесплатно через Borrowell."},
        ],
    },
    "privet_russian": {
        "name": "Привет, Русский!",
        "slug": "privet_russian",
        "description": "Bilingual Russian language learning podcast for English speakers.",
        "show_page": "ru/privet-russian.html",
        "summaries_page": "ru/privet-russian-summaries.html",
        "json_path": "digests/privet_russian/summaries_privet_russian.json",
        "json_format": "wrapped",
        "rss_file": "privet_russian_podcast.rss",
        "podcast_image": "assets/covers/privet-russian.jpg",
        "x_account": None,
        "brand_color": "#6366F1",
        "brand_color_dark": "#4F46E5",
        "tagline": "Learn Russian — Привет means hello!",
        "hero_tagline": "Learn Russian — Привет means hello!",
        "schedule": "Daily",
        "episode_length": "~10 min",
        "about_text": "A bilingual Russian language learning podcast for English speakers — kids and adult beginners. Host Olya teaches vocabulary, phrases, grammar, and culture through fun, themed episodes.",
        "about_host": "Hosted by Olya from Vancouver. Each episode is a mini lesson you can practice anywhere.",
        "description_long": "A bilingual Russian language learning podcast for English speakers — kids and adult beginners. Vocabulary, phrases, grammar, and culture in fun themed episodes.",
        "related_show": "finansy_prosto",
        "related_reason": "If you enjoy Привет, Русский!, you might also like Финансы Просто — a Russian-language finance podcast for women in Canada.",
        "apple_podcasts_url": None,
        "theme_color": "#6366F1",
        "meta_description": "Привет, Русский! — Learn Russian with fun bilingual podcast episodes. Vocabulary, phrases, grammar, and culture for beginners.",
        "meta_keywords": "learn Russian, Russian podcast, Russian for beginners, Russian language, bilingual podcast",
        "audience": "For students, teens, curious parents, career changers, and anyone who wants to learn Russian — no experience needed.",
        "source_highlights": ["BBC News", "NPR", "National Geographic", "Moscow Times"],
        "resource_categories": [
            {
                "title": "Language Learning Apps",
                "resources": [
                    {"name": "Duolingo Russian", "url": "https://www.duolingo.com/course/ru/en/Learn-Russian", "desc": "Free gamified Russian course — 5 minutes a day builds vocabulary and grammar habits"},
                    {"name": "Babbel Russian", "url": "https://www.babbel.com/learn-russian", "desc": "Structured Russian lessons with speech recognition — more grammar-focused than Duolingo"},
                    {"name": "Busuu Russian", "url": "https://www.busuu.com/en/course/learn-russian-online", "desc": "Russian course with native speaker feedback on your writing and speaking exercises"},
                    {"name": "Pimsleur Russian", "url": "https://www.pimsleur.com/learn-russian", "desc": "Audio-first method — learn Russian through listening and speaking, great for car commutes"},
                ],
            },
            {
                "title": "Dictionaries & Grammar",
                "resources": [
                    {"name": "OpenRussian", "url": "https://en.openrussian.org", "desc": "Free Russian dictionary with declensions, conjugations, stress marks, and usage examples"},
                    {"name": "Wiktionary Russian", "url": "https://en.wiktionary.org/wiki/Category:Russian_language", "desc": "Community dictionary with etymologies, pronunciations, and detailed grammar tables"},
                    {"name": "Russian Grammar Tables", "url": "https://www.russianlessons.net/grammar/", "desc": "Clear grammar reference — cases, verb conjugations, and adjective agreements"},
                    {"name": "Reverso Context", "url": "https://context.reverso.net/translation/russian-english/", "desc": "See Russian words used in real sentences — context-based translation with examples"},
                ],
            },
            {
                "title": "Russian Media",
                "resources": [
                    {"name": "Russian With Max", "url": "https://russianwithmax.com", "desc": "Comprehensible input podcast — slow, clear Russian with transcripts for A2-B2 learners"},
                    {"name": "Meduza (English)", "url": "https://meduza.io/en", "desc": "Independent Russian news in English — understand current events and cultural context"},
                    {"name": "Arzamas Academy", "url": "https://arzamas.academy", "desc": "Russian culture and history courses — literature, art, and philosophy (in Russian with subtitles)"},
                    {"name": "Kinopoisk", "url": "https://www.kinopoisk.ru", "desc": "Russia's IMDB — find Russian films and TV shows to practice listening comprehension"},
                ],
            },
            {
                "title": "Practice & Immersion",
                "resources": [
                    {"name": "Forvo Russian", "url": "https://forvo.com/languages/ru/", "desc": "Hear native speakers pronounce any Russian word — essential for mastering pronunciation"},
                    {"name": "Tandem", "url": "https://www.tandem.net", "desc": "Find Russian-speaking language partners for text and voice chat — free language exchange"},
                    {"name": "italki", "url": "https://www.italki.com/en/teachers/russian", "desc": "Book affordable 1-on-1 lessons with native Russian tutors — from $5/hour"},
                    {"name": "Clozemaster", "url": "https://www.clozemaster.com/languages/eng-rus", "desc": "Learn Russian through mass sentence exposure — fill in the blanks in context"},
                ],
            },
            {
                "title": "Culture & History",
                "resources": [
                    {"name": "Russia Beyond", "url": "https://www.rbth.com", "desc": "Russian culture, history, food, and travel — English-language articles about Russia"},
                    {"name": "Moscow Times", "url": "https://www.themoscowtimes.com", "desc": "Independent English-language news about Russia — politics, culture, and society"},
                    {"name": "Russian Life Magazine", "url": "https://russianlife.com", "desc": "Russian culture, travel, and history — beautifully written long-form articles"},
                    {"name": "RussianPod101", "url": "https://www.russianpod101.com", "desc": "Comprehensive Russian learning platform — lessons, vocabulary lists, and cultural notes"},
                ],
            },
        ],
        "tools": [
            {"name": "Duolingo", "url": "https://www.duolingo.com/course/ru/en/Learn-Russian", "desc": "Start learning Russian with 5-minute daily lessons — gamified, fun, and builds habits", "badge": "Free"},
            {"name": "Anki", "url": "https://apps.ankiweb.net", "desc": "Spaced repetition flashcards — the most effective way to memorize Russian vocabulary", "badge": "Free"},
            {"name": "Forvo", "url": "https://forvo.com/languages/ru/", "desc": "Hear any Russian word pronounced by native speakers — type it in, hear it spoken", "badge": "Free"},
            {"name": "Tandem", "url": "https://www.tandem.net", "desc": "Free language exchange app — find native Russian speakers who want to learn English", "badge": "Free"},
            {"name": "Google Translate", "url": "https://translate.google.com/?sl=en&tl=ru", "desc": "Instant English-to-Russian translation — use camera mode to translate signs and menus", "badge": "Free"},
        ],
        "faq": [
            {"q": "How hard is Russian to learn?", "a": "The US Foreign Service Institute rates Russian as a Category III language — harder than Spanish or French, but easier than Chinese, Japanese, or Arabic. For English speakers, the main challenges are the Cyrillic alphabet (learnable in a week), six grammatical cases (takes months to internalize), and verb aspect (perfective vs imperfective). The good news: Russian pronunciation is very regular — if you can read a word, you can pronounce it. With daily practice, expect basic conversational ability in 6-12 months."},
            {"q": "What is the Cyrillic alphabet?", "a": "Cyrillic is the alphabet used to write Russian (and Ukrainian, Bulgarian, Serbian, and others). It has 33 letters — some look and sound like English letters (A, K, M, O, T), some look familiar but sound different (B sounds like V, H sounds like N, P sounds like R, C sounds like S), and some are unique (Ж, Щ, Ы, Э). You can learn all 33 letters in about a week of focused practice. Once you know Cyrillic, you can sound out any Russian word."},
            {"q": "How many cases does Russian have?", "a": "Russian has six grammatical cases: Nominative (subject), Genitive (possession/of), Dative (to/for), Accusative (direct object), Instrumental (by/with), and Prepositional (about/in). Cases change the endings of nouns, adjectives, and pronouns depending on their role in the sentence. English handles this with word order and prepositions; Russian uses endings. It sounds intimidating, but you learn them gradually — start with Nominative and Accusative, then add others as you progress."},
            {"q": "What's the difference between ты and вы?", "a": "Both mean 'you,' but ты (tee) is informal/singular and вы (vee) is formal/plural. Use ты with friends, family, children, and pets. Use вы with strangers, older people, professionals, and in formal situations. Вы (capitalized Вы) is also used as a polite singular 'you' — like saying 'sir' or 'ma'am' in English. Using the wrong form isn't a disaster, but switching from вы to ты with someone signals that you've become friends — it's a meaningful social moment in Russian culture."},
            {"q": "How long does it take to learn Russian?", "a": "It depends on your goals and daily practice. With 30 minutes/day: basic greetings and survival phrases in 1-2 months, simple conversations in 4-6 months, comfortable intermediate level in 12-18 months. The FSI estimates 1,100 classroom hours for professional proficiency. Key accelerators: daily consistency (even 15 minutes beats occasional long sessions), native speaker practice (italki or Tandem), and immersion through media (Russian music, YouTube, Netflix shows with subtitles). This podcast is designed to be one of those daily touchpoints!"},
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
        "page_title": "Nerra Network | 9 Daily Shows",
        "meta_description": "Nerra Network — Nine daily podcasts keeping you informed. Tesla, world news, space, science, environment, AI, Russian finance, and language learning. Independent, daily, free.",
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
