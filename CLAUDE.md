# CLAUDE.md — Tesla Shorts Time Podcast Network

## Project Overview

Automated daily podcast generation system running 4 shows, each with its own
GitHub Actions workflow, X/Twitter posting, and RSS feed. All shows use
**ElevenLabs TTS** (Chatterbox support was fully removed Feb 2026).

| Show | Script | Schedule | X Account |
|------|--------|----------|-----------|
| Tesla Shorts Time | `digests/tesla_shorts_time.py` | Daily | `@teslashortstime` |
| Omni View | `digests/omni_view.py` | Daily | `@omniviewnews` |
| Fascinating Frontiers | `digests/fascinating_frontiers.py` | Daily | `@planetterrian` |
| Planetterrian Daily | `digests/planetterrian.py` | Daily | `@planetterrian` |

## Architecture

### Pipeline (per show, per run)

1. **Fetch** news sources (RSS, xAI/Grok web search, yfinance for Tesla)
2. **Generate** digest text via xAI/Grok API
3. **Synthesize** podcast audio via ElevenLabs TTS
4. **Mix** intro/outro music with voice (ffmpeg) — TST/PT/FF only, OV has no music
5. **Post** X thread + update RSS feed + commit output to git

### Key Directories

```
Tesla-shorts-time/
├── digests/                    # Show runner scripts + ALL generated output
│   ├── tesla_shorts_time.py    # ~4300 lines — the original, most complex
│   ├── omni_view.py            # ~1800 lines — structurally different from others
│   ├── fascinating_frontiers.py # ~2400 lines — near-identical twin of PT
│   ├── planetterrian.py        # ~2400 lines — near-identical twin of FF
│   ├── xai_grok.py             # Shared xAI/Grok API helper (112 lines)
│   ├── summaries_*.json        # Per-show episode summaries for GitHub Pages
│   ├── planetterrian/          # PT output subdirectory
│   ├── fascinating_frontiers/  # FF output subdirectory
│   └── *.mp3, *.md, *.txt     # TST + OV output (flat, mixed with source)
├── engine/                     # Shared modules (refactoring in progress)
│   ├── __init__.py
│   ├── utils.py                # Env helpers, text processing, similarity
│   ├── tts.py                  # ElevenLabs TTS (auth, chunking, synthesis)
│   └── audio.py                # Audio duration, format helpers
├── assets/
│   └── pronunciation.py        # Shared TTS pronunciation fixes
├── tests/                      # pytest suite
├── .github/workflows/          # 4 daily cron workflows
├── *.rss                       # Podcast RSS feeds (consumed by Apple/Spotify)
├── *.html                      # GitHub Pages web players
└── docs/                       # Audit docs, storage plan
```

### Script Relationships

- **FF and PT** are "nearly identical twins" — same structure, same functions,
  different news topics and X account
- **TST** shares most patterns with FF/PT but adds: complex pronunciation
  fixes, content tracking, chunked TTS, yfinance stock data
- **OV** is structurally different — different TTS approach (no streaming, uses
  env vars for voice settings), no music mixing, simpler functions

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
pytest                  # Run all tests (158 tests)
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

**Extract duplicated code from the 4 show scripts into `engine/` modules.**

Phase 1 (in progress):
- `engine/utils.py` — `number_to_words`, `_env_float/int/bool`,
  `calculate_similarity`, `remove_similar_items`
- `engine/tts.py` — `validate_elevenlabs_auth`, `speak`, `_speak_chunk`,
  `_chunk_text_for_elevenlabs`
- `engine/audio.py` — `get_audio_duration`, `format_duration`

Future phases: RSS management, X posting, content generation, music mixing.

## Known Landmines

### From Directory Audit (`docs/directory_audit.md`)

1. **TST + OV dump output into `digests/` flat** — mixed with source code.
   PT and FF already use subdirectories.
2. **Legacy `digests/digests/` path bug** — 20 early Tesla files written to
   wrong nested directory. RSS still references them.
3. **65 duplicate `_formatted.md` files** — Tesla-only, appear identical to
   plain `.md` versions.
4. **Summaries JSONs at wrong level** — all 4 live at `digests/` top-level
   instead of per-show subdirectories.

### From Env Var Audit (`docs/env_var_inventory.md`)

5. **`NEWSAPI_KEY`** set in workflow but never used in code (dead secret).
6. **OV feature flags are env-overridable** (`TEST_MODE`, `ENABLE_X_POSTING`,
   etc.) but the other 3 shows hardcode them.
7. **ElevenLabs tuning vars** (`ELEVENLABS_STABILITY`, etc.) only used by OV;
   TST/FF/PT hardcode their settings.

### From Audio Storage Plan (`docs/audio_storage_plan.md`)

8. **2.2 GB of MP3s in git** — repo will hit GitHub's 10 GB limit within ~6
   months at current growth. Cloudflare R2 migration recommended.
9. **Git LFS breaks RSS** — `raw.githubusercontent.com` returns pointer files
   for LFS-tracked content. Do NOT use LFS for MP3s.

### Recent Cleanup (Feb 2026)

10. **Early episodes deleted** — first 20 Tesla, 10 FF, 10 PT, 10 OV episodes
    removed (quality issues). RSS entries removed where applicable.
11. **Chatterbox TTS fully removed** — ElevenLabs is the only TTS provider.
    All Chatterbox code, requirements, docs, and voice prompt assets deleted.
