# Environment Variable Inventory

> Generated 2026-02-15 as part of the `refactor/engine-extraction` effort.
> This document audits every environment variable and GitHub Secret used across the project.

---

## 1. Complete Variable Table

### 1a. xAI / Grok API

| Variable | Used By | Purpose | Required? | Default | Set in Workflow |
|----------|---------|---------|-----------|---------|-----------------|
| `GROK_API_KEY` | Tesla, Planetterrian, Fascinating Frontiers, Omni View, `xai_grok.py` | Primary xAI/Grok API key for content generation | **Yes** (all shows) | — | All 4 workflows |
| `XAI_API_KEY` | Tesla (`_get_xai_api_key`), `xai_grok.py` | Fallback alias for `GROK_API_KEY` | No (fallback only) | — | **Not set in any workflow** |
| `XAI_API_BASE_URL` | Tesla only | Override xAI API base URL | No | `https://api.x.ai/v1` | Not set |
| `GROK_MODEL` | Omni View only | Override Grok model name | No | `grok-4.20-beta-0309-non-reasoning` | Not set |
| `GROK_WEB_SEARCH` | Tesla only | Enable/disable web search for Tesla X Takeover section | No | `1` (enabled) | Not set |

### 1b. ElevenLabs TTS

| Variable | Used By | Purpose | Required? | Default | Set in Workflow |
|----------|---------|---------|-----------|---------|-----------------|
| `ELEVENLABS_API_KEY` | Tesla, Planetterrian, Fascinating Frontiers, Omni View, `backfill_omni_ep001_audio.py` | ElevenLabs TTS API key | **Yes** (all shows with podcast) | — | All 4 workflows |
| `ELEVENLABS_VOICE_ID` | Tesla, Planetterrian, Fascinating Frontiers | ElevenLabs voice to use | No | `dTrBzPvD2GpAqkk1MUzA` | Not set |
| `OMNI_VIEW_ELEVENLABS_VOICE_ID` | Omni View, `backfill_omni_ep001_audio.py` | Omni View's own ElevenLabs voice | No | `ns7MjJ6c8tJKnvw7U6sN` | Not set |
| `ELEVENLABS_MODEL_ID` | Omni View, `backfill_omni_ep001_audio.py` | ElevenLabs model override | No | `eleven_turbo_v2_5` | Not set |
| `ELEVENLABS_STABILITY` | Omni View, `backfill_omni_ep001_audio.py` | Voice stability parameter | No | `0.35` | Not set |
| `ELEVENLABS_SIMILARITY_BOOST` | Omni View, `backfill_omni_ep001_audio.py` | Voice similarity boost | No | `0.75` | Not set |
| `ELEVENLABS_STYLE` | Omni View, `backfill_omni_ep001_audio.py` | Voice style parameter | No | `0.2` | Not set |
| `ELEVENLABS_MAX_CHARS` | Omni View, `backfill_omni_ep001_audio.py` | Max chars per TTS chunk | No | `4500` | Not set |

### 1c. X/Twitter Credentials (Tesla + Omni View account: `@teslashortstime` / `@omniviewnews`)

| Variable | Used By | Purpose | Required? | Default | Set in Workflow |
|----------|---------|---------|-----------|---------|-----------------|
| `X_CONSUMER_KEY` | Tesla, Omni View, `science_that_changes.py`, `verify_account.py`, `test_x_api_auth.py` | OAuth 1.0a consumer key | Yes (if X posting enabled) | — | `daily-podcast.yml`, `omni-view-daily.yml` |
| `X_CONSUMER_SECRET` | Tesla, Omni View, `science_that_changes.py`, `verify_account.py`, `test_x_api_auth.py` | OAuth 1.0a consumer secret | Yes (if X posting enabled) | — | `daily-podcast.yml`, `omni-view-daily.yml` |
| `X_ACCESS_TOKEN` | Tesla, Omni View, `science_that_changes.py`, `verify_account.py`, `test_x_api_auth.py` | OAuth 1.0a access token | Yes (if X posting enabled) | — | `daily-podcast.yml`, `omni-view-daily.yml` |
| `X_ACCESS_TOKEN_SECRET` | Tesla, Omni View, `science_that_changes.py`, `verify_account.py`, `test_x_api_auth.py` | OAuth 1.0a access token secret | Yes (if X posting enabled) | — | `daily-podcast.yml`, `omni-view-daily.yml` |
| `X_BEARER_TOKEN` | Tesla, Omni View, `test_x_posts_retrieval.py`, `test_x_api_auth.py` | OAuth 2.0 bearer token | Optional (recommended) | — | `daily-podcast.yml`, `omni-view-daily.yml` |

### 1d. X/Twitter Credentials (Planetterrian + Fascinating Frontiers account: `@planetterrian`)

| Variable | Used By | Purpose | Required? | Default | Set in Workflow |
|----------|---------|---------|-----------|---------|-----------------|
| `PLANETTERRIAN_X_CONSUMER_KEY` | Planetterrian, Fascinating Frontiers | OAuth 1.0a consumer key | Yes (if X posting enabled) | — | `planetterrian-daily.yml`, `fascinating-frontiers-daily.yml` |
| `PLANETTERRIAN_X_CONSUMER_SECRET` | Planetterrian, Fascinating Frontiers | OAuth 1.0a consumer secret | Yes (if X posting enabled) | — | `planetterrian-daily.yml`, `fascinating-frontiers-daily.yml` |
| `PLANETTERRIAN_X_ACCESS_TOKEN` | Planetterrian, Fascinating Frontiers | OAuth 1.0a access token | Yes (if X posting enabled) | — | `planetterrian-daily.yml`, `fascinating-frontiers-daily.yml` |
| `PLANETTERRIAN_X_ACCESS_TOKEN_SECRET` | Planetterrian, Fascinating Frontiers | OAuth 1.0a access token secret | Yes (if X posting enabled) | — | `planetterrian-daily.yml`, `fascinating-frontiers-daily.yml` |
| `PLANETTERRIAN_X_BEARER_TOKEN` | Planetterrian, Fascinating Frontiers | OAuth 2.0 bearer token | Optional (recommended) | — | `planetterrian-daily.yml`, `fascinating-frontiers-daily.yml` |

### 1e. Feature Flags (In-Script, Not from .env)

| Variable | Used By | Purpose | Required? | Default |
|----------|---------|---------|-----------|---------|
| `TEST_MODE` | All shows | Env-overridable in Omni View; hardcoded `False` in others | No | `False` |
| `ENABLE_X_POSTING` | All shows | Env-overridable in Omni View; hardcoded `True` in others | No | `True` |
| `ENABLE_PODCAST` | All shows | Env-overridable in Omni View; hardcoded `True` in others | No | `True` |
| `ENABLE_GITHUB_SUMMARIES` | All shows | Env-overridable in Omni View; hardcoded `True` in others | No | `True` |

### 1f. Other / Miscellaneous

| Variable | Used By | Purpose | Required? | Default | Set in Workflow |
|----------|---------|---------|-----------|---------|-----------------|
| `NEWSAPI_KEY` | Tesla (historically; no longer used in code) | NewsAPI key (legacy) | No | — | `daily-podcast.yml` (still set) |
| `TICKER_SYMBOL` | `test_tesla_shorts_time.py` | Override stock ticker for testing | No | `TSLA` | Not set |
### 1g. GitHub Actions Internal Variables

| Variable | Used By | Purpose |
|----------|---------|---------|
| `GITHUB_EVENT_NAME` | `omni-view-daily.yml` (gate job) | Detect manual vs. scheduled trigger |
| `GITHUB_OUTPUT` | `omni-view-daily.yml` (gate job) | Write outputs for job communication |
| `TZ` | All workflows (step `env:`) | Set timezone to UTC |

---

## 2. GitHub Secrets Inventory

These are the distinct `secrets.*` references across all workflows:

| Secret Name | Used In Workflow(s) | Maps To .env Variable |
|-------------|---------------------|-----------------------|
| `GROK_API_KEY` | All 4 | `GROK_API_KEY` |
| `ELEVENLABS_API_KEY` | All 4 | `ELEVENLABS_API_KEY` |
| `NEWSAPI_KEY` | `daily-podcast.yml` only | `NEWSAPI_KEY` |
| `X_CONSUMER_KEY` | `daily-podcast.yml`, `omni-view-daily.yml` | `X_CONSUMER_KEY` |
| `X_CONSUMER_SECRET` | `daily-podcast.yml`, `omni-view-daily.yml` | `X_CONSUMER_SECRET` |
| `X_ACCESS_TOKEN` | `daily-podcast.yml`, `omni-view-daily.yml` | `X_ACCESS_TOKEN` |
| `X_ACCESS_TOKEN_SECRET` | `daily-podcast.yml`, `omni-view-daily.yml` | `X_ACCESS_TOKEN_SECRET` |
| `X_BEARER_TOKEN` | `daily-podcast.yml`, `omni-view-daily.yml` | `X_BEARER_TOKEN` |
| `PLANETTERRIAN_X_CONSUMER_KEY` | `planetterrian-daily.yml`, `fascinating-frontiers-daily.yml` | `PLANETTERRIAN_X_CONSUMER_KEY` |
| `PLANETTERRIAN_X_CONSUMER_SECRET` | `planetterrian-daily.yml`, `fascinating-frontiers-daily.yml` | `PLANETTERRIAN_X_CONSUMER_SECRET` |
| `PLANETTERRIAN_X_ACCESS_TOKEN` | `planetterrian-daily.yml`, `fascinating-frontiers-daily.yml` | `PLANETTERRIAN_X_ACCESS_TOKEN` |
| `PLANETTERRIAN_X_ACCESS_TOKEN_SECRET` | `planetterrian-daily.yml`, `fascinating-frontiers-daily.yml` | `PLANETTERRIAN_X_ACCESS_TOKEN_SECRET` |
| `PLANETTERRIAN_X_BEARER_TOKEN` | `planetterrian-daily.yml`, `fascinating-frontiers-daily.yml` | `PLANETTERRIAN_X_BEARER_TOKEN` |

**Total distinct secrets: 14**

---

## 3. Inconsistencies & Issues

### 3a. Naming Convention Inconsistencies

| Issue | Details | Severity |
|-------|---------|----------|
| **X creds prefix split** | Tesla + Omni View use unprefixed `X_CONSUMER_KEY` etc. Planetterrian + Fascinating Frontiers use `PLANETTERRIAN_X_*`. This correctly maps to two different X accounts, but the naming implies Planetterrian ownership of Fascinating Frontiers' creds. | Medium |
| **TTS provider var naming** | TTS provider selection variables were removed — all shows now use ElevenLabs exclusively. | Resolved |
| **ElevenLabs voice ID split** | Tesla/Planetterrian/FF share `ELEVENLABS_VOICE_ID` (same default). Omni View uses `OMNI_VIEW_ELEVENLABS_VOICE_ID` with a different default. The Omni View var has a unique prefix but the other three do not. | Low |
| **ElevenLabs settings scope** | `ELEVENLABS_MODEL_ID`, `ELEVENLABS_STABILITY`, `ELEVENLABS_SIMILARITY_BOOST`, `ELEVENLABS_STYLE`, `ELEVENLABS_MAX_CHARS` are only used by Omni View (and the backfill script), not by Tesla/Planetterrian/FF, despite being named generically. Tesla/Planet/FF hardcode their ElevenLabs settings. | Medium |
| **`GROK_API_KEY` vs `XAI_API_KEY`** | Two names for the same key. `XAI_API_KEY` is supported as a fallback in Tesla and `xai_grok.py` but never set in any workflow. | Low |

### 3b. Variables Set But Never Used in Code

| Variable | Set In | Used? | Notes |
|----------|--------|-------|-------|
| `NEWSAPI_KEY` | `daily-podcast.yml` secret + .env | **No** | Code comment says "no longer needed - using RSS feeds instead." Dead secret. |

### 3c. Variables Used in Code But Not Set in All Required Workflows

| Variable | Used By | Missing From Workflow |
|----------|---------|----------------------|
| `XAI_API_KEY` | Tesla fallback, `xai_grok.py` fallback | All workflows (never set) |
| `ELEVENLABS_VOICE_ID` | Tesla, Planetterrian, Fascinating Frontiers | All workflows (relies on code default) |
| `OMNI_VIEW_ELEVENLABS_VOICE_ID` | Omni View | `omni-view-daily.yml` (relies on code default) |
| `ELEVENLABS_MODEL_ID` | Omni View | `omni-view-daily.yml` (relies on code default) |
| `ELEVENLABS_STABILITY` | Omni View | `omni-view-daily.yml` (relies on code default) |
| `ELEVENLABS_SIMILARITY_BOOST` | Omni View | `omni-view-daily.yml` (relies on code default) |
| `ELEVENLABS_STYLE` | Omni View | `omni-view-daily.yml` (relies on code default) |
| `GROK_MODEL` | Omni View | `omni-view-daily.yml` (relies on code default `grok-4.20-beta-0309-non-reasoning`) |
| `GROK_WEB_SEARCH` | Tesla | `daily-podcast.yml` (relies on code default `1`) |

### 3d. Omni View Feature Flags Are Env-Overridable; Others Are Not

Omni View's `__main__` block reads `TEST_MODE`, `ENABLE_X_POSTING`, `ENABLE_PODCAST`, and `ENABLE_GITHUB_SUMMARIES` from env vars. The other three shows hardcode these as Python constants (e.g., `TEST_MODE = False`). This means you can't easily do a dry-run of Tesla/Planetterrian/FF from the workflow without editing code.

---

## 4. Proposed Unified Naming Convention

For the refactored engine, adopt a consistent `<SCOPE>_<SERVICE>_<DETAIL>` pattern:

### 4a. Shared (Engine-Level) Variables

These are service credentials that don't change per-show:

| Current Name(s) | Proposed Name | Notes |
|-----------------|---------------|-------|
| `GROK_API_KEY` / `XAI_API_KEY` | `XAI_API_KEY` | Align with vendor name. Drop `GROK_API_KEY` alias. |
| `ELEVENLABS_API_KEY` | `ELEVENLABS_API_KEY` | Keep as-is (shared across shows). |

### 4b. Per-Show X/Twitter Credentials

Each X account gets its own set. Use a `<SHOW_SLUG>` prefix:

| Show | X Account | Prefix | Example |
|------|-----------|--------|---------|
| Tesla Shorts Time | `@teslashortstime` | `TESLA_` | `TESLA_X_CONSUMER_KEY` |
| Omni View | `@omniviewnews` | `OMNI_` | `OMNI_X_CONSUMER_KEY` |
| Planetterrian | `@planetterrian` | `PLANET_` | `PLANET_X_CONSUMER_KEY` |
| Fascinating Frontiers | `@planetterrian` (shared) | `PLANET_` | `PLANET_X_CONSUMER_KEY` (same) |

> Currently Tesla and Omni View share the same `X_*` secret values, but it's
> not obvious from the naming. Making it explicit per-show clarifies which
> account each show posts to, even when the underlying credential is the same
> GitHub Secret.

### 4c. Per-Show TTS Configuration

| Current Name(s) | Proposed Pattern | Example |
|-----------------|------------------|---------|
| `ELEVENLABS_VOICE_ID` (shared) + `OMNI_VIEW_ELEVENLABS_VOICE_ID` | `<SLUG>_ELEVENLABS_VOICE_ID` | `TESLA_ELEVENLABS_VOICE_ID`, `OMNI_ELEVENLABS_VOICE_ID` |

### 4d. Shared TTS Tuning (Engine-Level)

Keep these unprefixed since they apply globally:

| Variable | Keep/Change |
|----------|-------------|
| `ELEVENLABS_MODEL_ID` | Keep |
| `ELEVENLABS_STABILITY` | Keep |
| `ELEVENLABS_SIMILARITY_BOOST` | Keep |
| `ELEVENLABS_STYLE` | Keep |
| `ELEVENLABS_MAX_CHARS` | Keep |

### 4e. Feature Flags (Standardize Across All Shows)

Make all shows respect env overrides consistently:

| Variable | Proposed Scope |
|----------|---------------|
| `TEST_MODE` | Global (engine-level) |
| `ENABLE_X_POSTING` | Global or per-show (`<SLUG>_ENABLE_X_POSTING`) |
| `ENABLE_PODCAST` | Global or per-show |
| `ENABLE_GITHUB_SUMMARIES` | Global or per-show |

### 4f. Remove / Deprecate

| Variable | Action |
|----------|--------|
| `NEWSAPI_KEY` | Remove from `daily-podcast.yml`. Dead code. |
| `XAI_API_BASE_URL` | Remove (hardcoded `https://api.x.ai/v1` everywhere). |
| `GROK_API_KEY` | Replace with `XAI_API_KEY` (or keep as primary and drop the alias -- pick one). |
| `TICKER_SYMBOL` | Keep for testing only. |

### 4g. Proposed GitHub Secrets (Post-Refactor)

Reduced from 16 to 13 distinct secrets:

| Secret | Maps To |
|--------|---------|
| `XAI_API_KEY` | Shared Grok/xAI key |
| `ELEVENLABS_API_KEY` | Shared ElevenLabs key |
| `TESLA_X_CONSUMER_KEY` | Tesla + Omni View X account |
| `TESLA_X_CONSUMER_SECRET` | Tesla + Omni View X account |
| `TESLA_X_ACCESS_TOKEN` | Tesla + Omni View X account |
| `TESLA_X_ACCESS_TOKEN_SECRET` | Tesla + Omni View X account |
| `TESLA_X_BEARER_TOKEN` | Tesla + Omni View X account |
| `PLANET_X_CONSUMER_KEY` | Planetterrian + FF X account |
| `PLANET_X_CONSUMER_SECRET` | Planetterrian + FF X account |
| `PLANET_X_ACCESS_TOKEN` | Planetterrian + FF X account |
| `PLANET_X_ACCESS_TOKEN_SECRET` | Planetterrian + FF X account |
| `PLANET_X_BEARER_TOKEN` | Planetterrian + FF X account |

> `NEWSAPI_KEY` removed. Chatterbox-related secrets (`HF_TOKEN`,
> `PLANETTERRIAN_VOICE_PROMPT_BASE64`) removed — all shows use ElevenLabs.
