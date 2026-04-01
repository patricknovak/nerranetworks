# CLAUDE.md — Tesla Shorts Time Podcast Network

## Project Overview

Automated daily podcast generation system running 10 shows via a unified
`run_show.py` runner + per-show YAML configs, plus 4 legacy standalone scripts
(deprecated — see note below). Shows use **ElevenLabs TTS**, **Fish Audio TTS**
(with voice cloning), **Kokoro TTS**, or **Chatterbox TTS** (configurable per
show via `tts.provider` in YAML) and post to X/Twitter via
`engine/publisher.post_to_x()`.

| Show | Legacy Script | YAML Config | Schedule | X Account | TTS |
|------|--------------|-------------|----------|-----------|-----|
| Tesla Shorts Time | `digests/tesla_shorts_time.py` (deprecated) | `shows/tesla.yaml` | Daily | `@teslashortstime` | ElevenLabs |
| Omni View | `digests/omni_view.py` (deprecated) | `shows/omni_view.yaml` | Daily | `@omniviewnews` | ElevenLabs |
| Fascinating Frontiers | `digests/fascinating_frontiers.py` (deprecated) | `shows/fascinating_frontiers.yaml` | Daily | `@planetterrian` | ElevenLabs |
| Planetterrian Daily | `digests/planetterrian.py` (deprecated) | `shows/planetterrian.yaml` | Daily | `@planetterrian` | ElevenLabs |
| Env Intel | — | `shows/env_intel.yaml` | Weekdays | `@teslashortstime` | ElevenLabs |
| Models & Agents | — | `shows/models_agents.yaml` | Daily | — (X disabled) | ElevenLabs |
| Models & Agents for Beginners | — | `shows/models_agents_beginners.yaml` | Daily | — (X disabled) | ElevenLabs |
| Финансы Просто | — | `shows/finansy_prosto.yaml` | Daily | — (X disabled) | ElevenLabs |
| Modern Investing Techniques | — | `shows/modern_investing.yaml` | Weekdays | — (X disabled) | ElevenLabs |
| Привет, Русский! | — | `shows/privet_russian.yaml` | Even days | — (X disabled) | ElevenLabs |

**Science That Changes Everything** (`digests/science_that_changes.py`, ~83 lines)
is a standalone X-posting script, not a podcast show.

## Architecture

### Pipeline (per show, per run)

1. **Fetch** news sources (RSS, xAI/Grok web search, yfinance for Tesla)
2. **Dedup** via ContentTracker (cross-episode) + entity dedup
3. **Generate** digest text via xAI/Grok API
4. **Synthesize** podcast audio via ElevenLabs (`eleven_flash_v2_5`), Fish Audio, Kokoro, or Chatterbox TTS (per-show config)
5. **Mix** intro/outro music with voice (ffmpeg) — all shows (configurable per YAML)
6. **Post** X thread via `engine/publisher.post_to_x()` + update RSS feed + commit output to git

### Key Directories

```
nerranetworks/
├── run_show.py                    # Unified show runner (~716 lines)
├── shows/                         # Per-show YAML configs
│   ├── tesla.yaml
│   ├── omni_view.yaml
│   ├── fascinating_frontiers.yaml
│   ├── planetterrian.yaml
│   ├── env_intel.yaml
│   ├── models_agents.yaml
│   ├── models_agents_beginners.yaml
│   ├── finansy_prosto.yaml
│   ├── modern_investing.yaml
│   └── privet_russian.yaml
├── digests/                       # Legacy show scripts (deprecated) + ALL generated output
│   ├── tesla_shorts_time.py       # DEPRECATED — use run_show.py tesla
│   ├── omni_view.py               # DEPRECATED — use run_show.py omni_view
│   ├── fascinating_frontiers.py   # DEPRECATED — use run_show.py fascinating_frontiers
│   ├── planetterrian.py           # DEPRECATED — use run_show.py planetterrian
│   ├── science_that_changes.py    # ~83 lines — standalone X posting script
│   ├── xai_grok.py                # Shared xAI/Grok API helper (~111 lines)
│   ├── tesla_shorts_time/         # TST output + summaries_tesla.json
│   ├── omni_view/                 # OV output + summaries_omni.json
│   ├── fascinating_frontiers/     # FF output + summaries_space.json
│   ├── planetterrian/             # PT output + summaries_planet.json
│   ├── env_intel/                 # EI output + summaries_env_intel.json
│   ├── models_agents/             # M&A output + summaries_models_agents.json
│   ├── models_agents_beginners/   # MAB output
│   ├── finansy_prosto/            # FP output (Russian)
│   ├── modern_investing/          # MIT output
│   ├── privet_russian/            # PR output (bilingual Russian)
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
├── tests/                         # pytest suite
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
- **M&A** (Models & Agents) runs exclusively via `run_show.py` +
  `shows/models_agents.yaml`; no legacy script. X posting disabled.
- **MAB** (Models & Agents for Beginners) runs via `run_show.py` +
  `shows/models_agents_beginners.yaml`; beginner/teen-focused version of M&A.
  Uses **ElevenLabs TTS**. X posting disabled.
- **FP** (Финансы Просто) runs via `run_show.py` +
  `shows/finansy_prosto.yaml`; Russian-language financial literacy podcast
  for women in Canada. Uses **ElevenLabs TTS** (`eleven_flash_v2_5`
  with `language_code: ru`). All content generated in Russian. X posting disabled.
- **MIT** (Modern Investing Techniques) runs via `run_show.py` +
  `shows/modern_investing.yaml`; daily investing podcast focused on Canadian
  and US markets. Weekdays only. X posting disabled.
- **PR** (Привет, Русский!) runs via `run_show.py` +
  `shows/privet_russian.yaml`; bilingual Russian language learning podcast
  for English speakers. Even days only. Uses **ElevenLabs TTS**
  (`eleven_flash_v2_5` with `language_code: ru`). X posting disabled.
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
- Voice IDs: All English shows share `dTrBzPvD2GpAqkk1MUzA`, Russian shows (FP/PR) use `gedzfqL7OGdPbwm0ynTP`
- `FISH_AUDIO_API_KEY` — Fish Audio TTS (available but not currently used by active shows)
- See `docs/env_var_inventory.md` for the complete inventory

### RSS Feeds

All RSS `<enclosure>` URLs now use `audio.nerranetwork.com` (Cloudflare R2).
MP3 files are uploaded to R2 during the pipeline and excluded from git commits.
**Do NOT change R2 bucket paths — this breaks podcast subscribers.**

### Testing

```bash
pytest                             # Run all tests
pytest tests/test_utils.py         # Pure function tests (AST extraction)
pytest tests/test_rss.py           # RSS feed validation
pytest tests/test_audio_commands.py  # ffmpeg command structure tests
pytest tests/test_integration.py   # Pipeline integration tests
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
  (TST, FF, PT, OV, EI, M&A)
- `engine/fetcher.py` — `fetch_rss_articles`
- `engine/generator.py` — `generate_digest`, `generate_podcast_script`
- `engine/tracking.py` — `create_tracker`, `record_llm_usage`,
  `record_tts_usage`, `record_x_post`, `save_usage`

Phase 3 (current):
- All 10 shows now run via `run_show.py` + YAML configs in production (CI/CD).
- Legacy scripts (`digests/{tesla_shorts_time,omni_view,fascinating_frontiers,
  planetterrian}.py`) are **deprecated** — retained for reference only.
- `run_show.py` is the canonical entry point; legacy scripts are not called
  by any workflow or cron job.

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
11. **MAB TTS settled on ElevenLabs** — Chatterbox produced gibberish on CPU,
    Kokoro had robotic pronunciation, Fish Audio was trialled briefly. MAB and
    FP now use ElevenLabs (`eleven_flash_v2_5`
    respectively) for reliable quality.
12. **Summaries JSONs moved** — all summaries live in per-show subdirectories
    (`digests/<show>/summaries_*.json`), not at the `digests/` top level.
