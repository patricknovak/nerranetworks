# Nerra Network — Daily Podcast Network

Automated daily podcast generation system running 7 shows via a unified
`run_show.py` runner + per-show YAML configs. Each show fetches news via RSS
and xAI/Grok web search, generates a digest and podcast script via xAI/Grok,
synthesizes audio via ElevenLabs TTS, mixes intro/outro music, and publishes
to RSS feeds, GitHub Pages, and X/Twitter.

All shows are produced independently in Vancouver, Canada.

**Website:** [nerranetwork.com](https://nerranetwork.com)

## Shows

| Show | Schedule | Player | RSS |
|------|----------|--------|-----|
| **Tesla Shorts Time** | Daily | [Player](https://nerranetwork.com/tesla.html) | [RSS](https://nerranetwork.com/podcast.rss) |
| **Omni View** | Daily | [Player](https://nerranetwork.com/omni-view.html) | [RSS](https://nerranetwork.com/omni_view_podcast.rss) |
| **Fascinating Frontiers** | Daily | [Player](https://nerranetwork.com/fascinating_frontiers.html) | [RSS](https://nerranetwork.com/fascinating_frontiers_podcast.rss) |
| **Planetterrian Daily** | Daily | [Player](https://nerranetwork.com/planetterrian.html) | [RSS](https://nerranetwork.com/planetterrian_podcast.rss) |
| **Environmental Intelligence** | Weekdays | [Player](https://nerranetwork.com/env-intel.html) | [RSS](https://nerranetwork.com/env_intel_podcast.rss) |
| **Models & Agents** | Daily | [Player](https://nerranetwork.com/models-agents.html) | [RSS](https://nerranetwork.com/models_agents_podcast.rss) |
| **Models & Agents for Beginners** | Daily | [Player](https://nerranetwork.com/models-agents-beginners.html) | [RSS](https://nerranetwork.com/models_agents_beginners_podcast.rss) |

## Apple Podcasts

- [Tesla Shorts Time](https://podcasts.apple.com/us/podcast/tesla-shorts-time/id1855142939)

## Architecture

```
run_show.py                     # Unified entry point for all shows
├── engine/                     # Shared modules
│   ├── config.py               # YAML-based show configuration
│   ├── fetcher.py              # RSS feed fetching + keyword scoring
│   ├── generator.py            # xAI/Grok LLM digest + podcast generation
│   ├── tts.py                  # ElevenLabs TTS synthesis
│   ├── audio.py                # ffmpeg audio processing + music mixing
│   ├── publisher.py            # RSS feed update, GitHub Pages, X posting
│   ├── newsletter.py           # Buttondown newsletter integration
│   ├── storage.py              # Cloudflare R2 audio storage
│   ├── tracking.py             # API usage + cost tracking
│   └── utils.py                # Text processing, similarity, helpers
├── shows/                      # Per-show configuration
│   ├── *.yaml                  # Show configs (sources, TTS, publishing)
│   ├── prompts/                # LLM prompt templates
│   └── hooks/                  # Show-specific pre-fetch hooks
├── digests/                    # Generated output (audio, markdown, JSON)
├── templates/                  # Jinja2 HTML templates
│   ├── base.html.j2            # Shared layout (nav, footer, design tokens)
│   ├── show_page.html.j2       # Per-show player + episodes page
│   ├── summaries_page.html.j2  # Per-show episode archive
│   └── network_page.html.j2    # Network landing page
├── styles/
│   └── main.css                # Shared stylesheet (dark theme, glassmorphism)
├── generate_html.py            # Static site generator (Jinja2 → HTML)
├── .github/workflows/
│   └── run-show.yml            # Unified GitHub Actions workflow
└── *.rss                       # Podcast RSS feeds
```

### Pipeline (per show, per run)

1. **Load config** from `shows/<show>.yaml`
2. **Pre-fetch hook** (optional — e.g., Tesla stock price via yfinance)
3. **Fetch** news from RSS sources, score by keyword relevance
4. **Generate** digest text via xAI/Grok API
5. **Generate** podcast script via xAI/Grok API
6. **Synthesize** audio via ElevenLabs TTS (with chunking)
7. **Mix** intro/outro music with voice (ffmpeg) — where configured
8. **Upload** to Cloudflare R2 (if configured)
9. **Update** RSS feed
10. **Save** summary to GitHub Pages JSON
11. **Send** newsletter (if configured)
12. **Post** X/Twitter teaser

## Usage

```bash
# Run a show (full pipeline)
python run_show.py tesla

# Test mode (fetch + digest only, no TTS/posting)
python run_show.py omni_view --test

# Dry run (print plan, no API calls)
python run_show.py env_intel --dry-run

# Skip specific steps
python run_show.py tesla --skip-x --skip-newsletter
python run_show.py fascinating_frontiers --skip-podcast

# Regenerate all HTML pages
python generate_html.py --all
```

### Available shows

`tesla`, `omni_view`, `fascinating_frontiers`, `planetterrian`, `env_intel`, `models_agents`, `models_agents_beginners`

## Adding a New Show

1. Create `shows/<slug>.yaml` with sources, LLM, TTS, audio, and publishing config
2. Create `shows/prompts/<slug>_digest.txt` and `<slug>_podcast.txt`
3. Optionally create `shows/hooks/<slug>.py` for pre-fetch logic
4. Add the slug to `run_show.py` choices
5. Add cron schedule to `.github/workflows/run-show.yml`
6. Add show config to `generate_html.py` and run `python generate_html.py --all`

## Testing

```bash
pytest                           # Run all tests
pytest tests/test_utils.py       # Pure function tests
pytest tests/test_rss.py         # RSS feed validation
pytest tests/test_audio_commands.py  # ffmpeg command structure
pytest tests/test_integration.py # Pipeline integration tests
```

## Environment Variables

See `docs/env_var_inventory.md` for the complete list. Key variables:

- `GROK_API_KEY` — xAI/Grok API (all shows)
- `ELEVENLABS_API_KEY` — ElevenLabs TTS (all shows)
- `X_*` / `PLANETTERRIAN_X_*` — X/Twitter credentials
- `R2_*` — Cloudflare R2 storage (optional)
- `*_NEWSLETTER_API_KEY` — Buttondown newsletter (optional)

## Documentation

- `docs/env_var_inventory.md` — Environment variable reference
- `docs/directory_audit.md` — File structure and path dependencies
- `docs/audio_storage_plan.md` — R2 migration strategy
- `docs/newsletter_comparison.md` — Newsletter platform evaluation
- `docs/podcast_directories.md` — Directory submission guide
- `docs/monetization_roadmap.md` — Revenue strategy and timeline
