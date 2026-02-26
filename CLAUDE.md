# CLAUDE.md — Tesla Shorts Time Podcast Network

## Project Overview

Automated daily podcast generation system running 5 shows via a unified
`run_show.py` runner + per-show YAML configs, plus 4 legacy standalone scripts.
All shows use **ElevenLabs TTS** and post to X/Twitter via
`engine/publisher.post_to_x()`.

| Show | Legacy Script | YAML Config | Schedule | X Account |
|------|--------------|-------------|----------|-----------|
| Tesla Shorts Time | `digests/tesla_shorts_time.py` (~2650 lines) | `shows/tesla.yaml` | Daily | `@teslashortstime` |
| Omni View | `digests/omni_view.py` (~1400 lines) | `shows/omni_view.yaml` | Daily | `@omniviewnews` |
| Fascinating Frontiers | `digests/fascinating_frontiers.py` (~1730 lines) | `shows/fascinating_frontiers.yaml` | Daily | `@planetterrian` |
| Planetterrian Daily | `digests/planetterrian.py` (~1660 lines) | `shows/planetterrian.yaml` | Daily | `@planetterrian` |
| Env Intel | — (run_show.py only) | `shows/env_intel.yaml` | Daily | `@teslashortstime` |

**Science That Changes Everything** (`digests/science_that_changes.py`, ~83 lines)
is a standalone X-posting script, not a podcast show.

## Architecture

### Pipeline (per show, per run)

1. **Fetch** news sources (RSS, xAI/Grok web search, yfinance for Tesla)
2. **Dedup** via ContentTracker (cross-episode) + entity dedup
3. **Generate** digest text via xAI/Grok API
4. **Synthesize** podcast audio via ElevenLabs TTS
5. **Mix** intro/outro music with voice (ffmpeg) — all shows (configurable per YAML)
6. **Post** X thread via `engine/publisher.post_to_x()` + update RSS feed + commit output to git

### Key Directories

```
Tesla-shorts-time/
├── run_show.py                    # Unified show runner (~716 lines)
├── shows/                         # Per-show YAML configs
│   ├── tesla.yaml
│   ├── omni_view.yaml
│   ├── fascinating_frontiers.yaml
│   ├── planetterrian.yaml
│   └── env_intel.yaml
├── digests/                       # Legacy show scripts + ALL generated output
│   ├── tesla_shorts_time.py       # ~2650 lines — the original, most complex
│   ├── omni_view.py               # ~1400 lines — structurally different from others
│   ├── fascinating_frontiers.py   # ~1730 lines — near-identical twin of PT
│   ├── planetterrian.py           # ~1660 lines — near-identical twin of FF
│   ├── science_that_changes.py    # ~83 lines — standalone X posting script
│   ├── xai_grok.py                # Shared xAI/Grok API helper (~111 lines)
│   ├── tesla_shorts_time/         # TST output + summaries_tesla.json
│   ├── omni_view/                 # OV output + summaries_omni.json
│   ├── fascinating_frontiers/     # FF output + summaries_space.json
│   ├── planetterrian/             # PT output + summaries_planet.json
│   ├── env_intel/                 # EI output + summaries_env_intel.json
│   └── *.mp3, *.md, *.txt        # Legacy TST flat output (historical)
├── engine/                        # Shared modules
│   ├── __init__.py
│   ├── utils.py                   # Env helpers, text processing, similarity, dedup
│   ├── tts.py                     # ElevenLabs TTS (auth, chunking, synthesis)
│   ├── audio.py                   # mix_with_music (3 modes), normalize_voice, duration helpers
│   ├── publisher.py               # RSS feeds, X posting, GitHub Pages summaries, digest formatting
│   ├── content_tracker.py         # Cross-episode dedup (per-show section patterns)
│   ├── fetcher.py                 # RSS article fetching
│   ├── generator.py               # LLM digest/podcast script generation
│   ├── tracking.py                # Credit/usage tracking
│   ├── config.py                  # YAML config loader
│   ├── storage.py                 # Cloudflare R2 storage helpers
│   ├── newsletter.py              # Email newsletter helpers
│   └── validation.py              # Config validation
├── assets/
│   ├── pronunciation.py           # Shared TTS pronunciation fixes
│   └── music/                     # Centralized podcast music (intro/outro)
│       ├── README.md              # Music generation guide + AI prompts
│       ├── tesla_shorts_time.mp3  # TST + EI + M&A theme
│       ├── fascinatingfrontiers.mp3     # FF intro jingle
│       ├── fascinatingfrontiers_bg.mp3  # FF background/outro
│       ├── LubechangeOilers.mp3         # OV theme
│       └── oilers-pride.mp3             # PT theme
├── tests/                         # pytest suite (627 tests)
├── .github/workflows/
│   └── run-show.yml               # Unified daily cron workflow (all shows)
├── *.rss                          # Podcast RSS feeds (consumed by Apple/Spotify)
├── *.html                         # GitHub Pages web players + summaries pages
└── docs/                          # Audit docs, storage plan
```

### Script Relationships

- **FF and PT** are "nearly identical twins" — same structure, same functions,
  different news topics and X account
- **TST** shares most patterns with FF/PT but adds: complex pronunciation
  fixes, content tracking, chunked TTS, yfinance stock data, TST-specific
  emoji formatting via `engine.publisher.format_tst_digest_for_x()`
- **OV** is structurally different — different TTS approach (no streaming, uses
  env vars for voice settings), simpler functions
- **EI** runs exclusively via `run_show.py` + `shows/env_intel.yaml`; no legacy script
- All shows delegate X posting to `engine.publisher.post_to_x()`
- TST/FF/PT delegate voice normalization to `engine.audio.normalize_voice()`
- All shows use `engine.audio.mix_with_music()` for music mixing (3 modes:
  standard, delayed-intro, dual-music). Music files in `assets/music/`.
  Shows without music files gracefully fall back to voice-only.

## Conventions

### Environment Variables

- All secrets come from `.env` (local) or GitHub Actions secrets
- `GROK_API_KEY` — primary xAI key (all shows)
- `ELEVENLABS_API_KEY` — ElevenLabs TTS (all shows)
- `X_*` / `PLANETTERRIAN_X_*` — two separate X accounts
- Voice IDs: TST/FF/PT share `dTrBzPvD2GpAqkk1MUzA`, OV uses `ns7MjJ6c8tJKnvw7U6sN`
- See `docs/env_var_inventory.md` for the complete inventory

### RSS Feeds

All RSS `<enclosure>` URLs use `raw.githubusercontent.com` pointing to files in
`digests/`. **Moving MP3 files breaks podcast subscribers.** See
`docs/audio_storage_plan.md` for migration strategy.

### Testing

```bash
pytest                  # Run all tests (627 tests)
pytest tests/test_utils.py   # Pure function tests (AST extraction)
pytest tests/test_rss.py     # RSS feed validation
pytest tests/test_audio_commands.py  # ffmpeg command structure tests
```

Tests use AST extraction + `exec()` to load functions from show scripts because
`tesla_shorts_time.py` has a `SystemExit` guard preventing import.

### Code Style

- No linter configured; scripts are large single-file programs
- Functions are defined inline (not imported), which is why we're extracting
- `logging` for all output; `sys.stdout` handler
- `pathlib.Path` for all file operations
- `tenacity` for retry logic on API calls

## Current Refactoring Goal

**Extract duplicated code from the show scripts into `engine/` modules.**

Phase 1 (complete):
- `engine/utils.py` — `number_to_words`, `_env_float/int/bool`,
  `calculate_similarity`, `remove_similar_items`, `deduplicate_by_entity`
- `engine/tts.py` — `validate_elevenlabs_auth`, `speak`, `_speak_chunk`,
  `_chunk_text_for_elevenlabs`
- `engine/audio.py` — `get_audio_duration`, `format_duration`,
  `mix_with_music` (standard / delayed-intro / dual-music modes),
  `normalize_voice`

Phase 2 (complete):
- `engine/publisher.py` — `update_rss_feed`, `get_next_episode_number`,
  `save_summary_to_github_pages`, `post_to_x`, `format_digest_for_x`,
  `format_tst_digest_for_x`, `apply_op3_prefix`
- `engine/content_tracker.py` — `ContentTracker` with per-show section patterns
  (TST, FF, PT, OV, EI)
- `engine/fetcher.py` — `fetch_rss_articles`
- `engine/generator.py` — `generate_digest`, `generate_podcast_script`
- `engine/tracking.py` — `create_tracker`, `record_llm_usage`,
  `record_tts_usage`, `record_x_post`, `save_usage`

Future work: Migrate remaining inline code from legacy scripts to engine
modules. Goal is for all shows to run via `run_show.py` + YAML configs.

## Known Landmines

### Active Issues

1. **2.2 GB of MP3s in git** — repo will hit GitHub's 10 GB limit within ~6
   months at current growth. Cloudflare R2 migration recommended.
2. **Git LFS breaks RSS** — `raw.githubusercontent.com` returns pointer files
   for LFS-tracked content. Do NOT use LFS for MP3s.
3. **Historical TST/OV flat files in `digests/`** — ~220 legacy output files
   (MP3s, markdown, JSON, HTML, TXT) remain at the `digests/` top level from
   before shows were migrated to subdirectories. These cannot be moved without
   breaking existing RSS feed URLs. New episodes now write to subdirectories.

### Resolved Issues (Feb 2026)

4. **TST/OV output dirs fixed** — `shows/tesla.yaml` and `shows/omni_view.yaml`
   now use `digests/tesla_shorts_time/` and `digests/omni_view/` for
   `output_dir` and `audio_subdir`, matching FF/PT/EI. Legacy scripts already
   pointed to subdirectories. Audio URL construction in both legacy scripts
   also fixed.
5. **Legacy `digests/digests/` path bug cleaned up** — nested directory deleted,
   RSS references removed, SETUP.md corrected. Defensive scanning code remains
   in `tesla_shorts_time.py` in case any legacy files resurface.
6. **58 duplicate `_formatted.md` files deleted** — removed in commit
   `0c10b7f`, code no longer generates them.
7. **`NEWSAPI_KEY` dead secret removed** — not present in active workflow
   (`run-show.yml`), not used in any code. Integration test
   `test_no_newsapi_in_active_workflow()` guards against re-introduction.
8. **Feature flags consistent across shows** — all four legacy scripts
   (TST, FF, PT, OV) support env-overridable `TEST_MODE`, `ENABLE_X_POSTING`,
   `ENABLE_PODCAST`, and `ENABLE_GITHUB_SUMMARIES`. `run_show.py` uses
   CLI flags (`--test`, `--skip-x`, `--skip-podcast`) instead.
9. **OV ElevenLabs tuning defaults aligned** — OV legacy script defaults
   updated from 0.35/0.75/0.2 to 0.65/0.9/0.85, matching all YAML configs
   and other legacy scripts. Env var overrides still supported.
10. **Early episodes deleted** — first 20 Tesla, 10 FF, 10 PT, 10 OV episodes
    removed (quality issues). RSS entries removed where applicable.
11. **Chatterbox TTS fully removed** — ElevenLabs is the only TTS provider.
    All Chatterbox code, requirements, docs, and voice prompt assets deleted.
12. **Summaries JSONs moved** — all summaries live in per-show subdirectories
    (`digests/<show>/summaries_*.json`), not at the `digests/` top level.
