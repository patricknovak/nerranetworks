# Tesla Shorts Time — Podcast Network

Automated daily podcast generation system running 5 shows. Each show fetches
news via RSS, generates a digest and podcast script via xAI/Grok, synthesizes
audio via ElevenLabs TTS, and publishes to RSS feeds, GitHub Pages, and X/Twitter.

## Shows

| Show | Schedule | Player | RSS |
|------|----------|--------|-----|
| **Tesla Shorts Time** | Daily | [Player](https://patricknovak.github.io/Tesla-shorts-time/) | [RSS](https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main/tesla_shorts_time_podcast.rss) |
| **Omni View** | Daily | [Player](https://patricknovak.github.io/Tesla-shorts-time/omni-view.html) | [RSS](https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main/omni_view_podcast.rss) |
| **Fascinating Frontiers** | Even days | [Player](https://patricknovak.github.io/Tesla-shorts-time/fascinating-frontiers.html) | [RSS](https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main/fascinating_frontiers_podcast.rss) |
| **Planetterrian Daily** | Odd days | [Player](https://patricknovak.github.io/Tesla-shorts-time/planetterrian.html) | [RSS](https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main/planetterrian_podcast.rss) |
| **Environmental Intelligence** | Weekdays | [Player](https://patricknovak.github.io/Tesla-shorts-time/env-intel.html) | [RSS](https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main/env_intel_podcast.rss) |

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
├── .github/workflows/
│   └── run-show.yml            # Unified GitHub Actions workflow
└── scripts/                    # Migration + verification utilities
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
```

### Available shows

`tesla`, `omni_view`, `fascinating_frontiers`, `planetterrian`, `env_intel`

## Adding a New Show

1. Create `shows/<slug>.yaml` with sources, LLM, TTS, audio, and publishing config
2. Create `shows/prompts/<slug>_digest.txt` and `<slug>_podcast.txt`
3. Optionally create `shows/hooks/<slug>.py` for pre-fetch logic
4. Add the slug to `run_show.py` choices
5. Add cron schedule to `.github/workflows/run-show.yml`
6. Create GitHub Pages player HTML

## Testing

```bash
pytest                           # Run all 158 tests
pytest tests/test_utils.py       # Pure function tests
pytest tests/test_rss.py         # RSS feed validation
pytest tests/test_audio_commands.py  # ffmpeg command structure
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
