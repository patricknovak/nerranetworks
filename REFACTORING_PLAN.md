# REFACTORING_PLAN.md — Master Instructions for Claude Code

> This file is the complete refactoring plan. Claude Code should read this file
> and work through it sequentially, committing after each phase. If a session
> ends mid-plan, the next session should pick up where the previous left off
> by checking git log and the current state of the codebase.

## Status Tracking

Update this section as phases complete:

- [x] Phase 1A: engine/utils.py, engine/tts.py, engine/audio.py
- [x] Phase 1B: engine/publisher.py, engine/tracking.py, engine/fetcher.py
- [x] Phase 1C: Migrate omni_view.py to engine/
- [x] Phase 1D: Migrate fascinating_frontiers.py, planetterrian.py, tesla_shorts_time.py
- [x] Phase 2A: engine/config.py + show YAML configs + prompt extraction
- [x] Phase 2B: run_show.py + engine/generator.py
- [x] Phase 2C: Validate all 4 shows through run_show.py --test
- [x] Phase 3: Unified GitHub Actions workflow
- [x] Phase 4A: engine/storage.py for R2 + dual-write capability
- [x] Phase 4B: Migration scripts for existing episodes to R2
- [x] Phase 5: Environmental Intelligence show
- [ ] Phase 6: Newsletter integration
- [ ] Phase 7: Analytics + monetization prep
- [ ] Phase 8: Final cleanup + merge prep

---

## Context

- Branch: refactor/engine-extraction
- main runs 4 daily shows via GitHub Actions — don't touch main
- 158 regression tests in tests/ — run pytest after every phase
- Chatterbox TTS has been removed — ElevenLabs only
- Early episodes with quality issues have been deleted
- See CLAUDE.md for project context and known landmines
- See docs/env_var_inventory.md for all env vars and naming issues
- See docs/directory_audit.md for file structure and path dependencies
- See docs/audio_storage_plan.md for R2 migration details

---

## Phase 1A: Core Engine Modules

Create engine/ package with shared code extracted from the 4 show scripts
(digests/tesla_shorts_time.py, omni_view.py, fascinating_frontiers.py, planetterrian.py).

### engine/__init__.py
Empty or minimal, just makes it a package.

### engine/utils.py
Extract these duplicated pure functions from all 4 scripts:
- `number_to_words()` + its helper `convert_under_1000()`
- `calculate_similarity()` 
- `remove_similar_items()`
- `_norm_headline_for_similarity()`
- `filter_articles_by_recent_stories()`
- HTTP constants: `DEFAULT_HEADERS`, `HTTP_TIMEOUT_SECONDS`

### engine/tts.py
ElevenLabs-only TTS module (Chatterbox has been removed). Extract and consolidate:
- `_chunk_text_for_elevenlabs()` — text chunking logic
- `_elevenlabs_tts_mp3()` — API call wrapper with retry logic
- ffmpeg concatenation of chunks into final audio
- Top-level function: `synthesize(text, voice_id, output_path, max_chars=4500, model_id="eleven_turbo_v2_5", stability=0.35, similarity_boost=0.75, style=0.2) -> Path`
- Should handle chunking + concatenation internally so callers just pass text and get back a path
- All ElevenLabs settings as parameters with defaults

### engine/audio.py
Extract ffmpeg operations (tesla_shorts_time.py has the most complex version):
- `get_duration(path) -> float` — ffprobe wrapper
- `normalize_voice(input_path, output_path) -> Path` — the highpass/lowpass/loudnorm/compressor filter chain with fallback to simple loudnorm
- `concatenate_audio(file_list, output_path) -> Path` — ffmpeg concat demuxer
- `mix_with_music(voice_path, music_path, output_path, intro_duration=5, overlap_duration=3, fade_duration=18, outro_duration=30, intro_volume=0.6, overlap_volume=0.5, fade_volume=0.4, outro_volume=0.4) -> Path` — full music mixing pipeline from tesla_shorts_time.py
- Handle "no music" case gracefully (just normalize + return)

### Verification
```bash
python -c "from engine.utils import number_to_words; print(number_to_words(42))"
python -c "from engine.tts import synthesize; print('TTS module OK')"
python -c "from engine.audio import get_duration; print('Audio module OK')"
python -m pytest tests/ -v  # all 158 tests still pass
```

### Commit
`feat: create engine/ package with utils, tts, audio modules`

---

## Phase 1B: Publisher, Tracking, Fetcher Modules

### engine/publisher.py
Extract from all 4 scripts:
- `update_rss_feed(audio_file, duration, rss_path, title, description, link, image_url, base_url, language, copyright, categories, author, email, episode_prefix, episode_num)` — feedgen + XML preservation pattern
- `save_summary_to_github_pages(content, digests_dir, podcast_name, episode_num, episode_title, audio_url, rss_url)` — JSON summary saving
- `post_to_x(teaser_text, consumer_key, consumer_secret, access_token, access_token_secret, bearer_token)` — tweepy post
- `get_next_episode_number(rss_path, digests_dir) -> int`
- `generate_episode_thumbnail(base_image, episode_num, date_str, output_path)`

NOTE from env var audit: Tesla+Omni use unprefixed X_CONSUMER_KEY etc. Planetterrian+FF use PLANETTERRIAN_X_* prefix. The publisher functions should accept credentials as parameters, not read env vars directly. Let the caller (or config system) handle which env vars to read.

### engine/tracking.py
Extract from all 4 scripts:
- `create_tracker(show_name, tts_provider="elevenlabs") -> dict`
- `record_llm_usage(tracker, tokens_in, tokens_out)`
- `record_tts_usage(tracker, characters)`
- `record_x_post(tracker)`
- `save_usage(tracker, output_dir) -> Path`
- ElevenLabs cost: $0.30 per 1000 characters

### engine/fetcher.py
Extract the common RSS fetching pattern:
- `fetch_rss_articles(feed_urls, cutoff_hours=24, keywords=None) -> list[dict]`
  - feed_urls: list of {"url": "...", "label": "..."} dicts
  - Uses feedparser
  - Filters by publication date (cutoff_hours)
  - Scores by keyword relevance if keywords provided
  - Deduplicates by title similarity
  - Returns list of {"title", "description", "url", "source_name", "published_date", "relevance_score"} dicts
  - Handles feed parse errors gracefully (log warning, skip feed, continue)

### Verification
```bash
python -c "from engine.publisher import update_rss_feed; print('Publisher OK')"
python -c "from engine.tracking import create_tracker; print('Tracking OK')"
python -c "from engine.fetcher import fetch_rss_articles; print('Fetcher OK')"
python -m pytest tests/ -v
```

### Commit
`feat: add publisher, tracking, fetcher to engine/`

---

## Phase 1C: Migrate Omni View (Pilot)

Omni View is the simplest show — no music, no stock prices, no X post fetching. Migrate it first.

### Process
1. Comment out each replaced function with: `# MIGRATED: engine/<module>.py`
2. Add engine/ imports at top of digests/omni_view.py
3. Replace:
   - `number_to_words` → `engine.utils.number_to_words`
   - `calculate_similarity` / `remove_similar_items` → `engine.utils`
   - `_chunk_text_for_elevenlabs` → internal to `engine.tts`
   - `_elevenlabs_tts_mp3` → internal to `engine.tts`
   - `create_omni_view_podcast` → `engine.tts.synthesize` + `engine.audio`
   - `_ffprobe_duration_seconds` → `engine.audio.get_duration`
   - `update_omni_view_rss_feed` → `engine.publisher.update_rss_feed`
   - `save_summary_to_github_pages` → `engine.publisher`
   - `get_next_episode_number` → `engine.publisher`
   - Credit usage functions → `engine.tracking`
4. Keep ALL show-specific logic in the script (RSS feed list, LLM prompts, voice ID, X account)

### Verification
```bash
python -c "import ast; ast.parse(open('digests/omni_view.py').read())"
wc -l digests/omni_view.py  # show reduction
python -m pytest tests/ -v
```

### Commit
`refactor: migrate omni_view.py to engine/ modules`

---

## Phase 1D: Migrate Remaining Shows

Same pattern as omni_view.py. Do them in order:

### 1. fascinating_frontiers.py
Standard migration. Commit: `refactor: migrate fascinating_frontiers.py to engine/`

### 2. planetterrian.py
Standard migration. Commit: `refactor: migrate planetterrian.py to engine/`

### 3. tesla_shorts_time.py (most complex)
- Music mixing (~lines 3712-3900) → `engine.audio.mix_with_music()`
- Keep `fetch_tsla_price()` in script — Tesla-specific
- Keep X post fetching in script — Tesla-specific
- `fix_tesla_pronunciation()` has Tesla-specific entries beyond shared `assets/pronunciation.py` — keep Tesla-specific fixes in script, have it extend the shared dictionary
- Commit: `refactor: migrate tesla_shorts_time.py to engine/`

### After all 4
```bash
wc -l digests/tesla_shorts_time.py digests/omni_view.py digests/fascinating_frontiers.py digests/planetterrian.py
grep -c "MIGRATED" digests/*.py
python -m pytest tests/ -v
```

---

## Phase 2A: Config Schema + YAML Extraction

### engine/config.py
Create a ShowConfig dataclass (or similar) with:

```python
@dataclass
class SourceConfig:
    url: str
    label: str

@dataclass  
class LLMConfig:
    provider: str  # "xai"
    model: str  # "grok-3"
    system_prompt_file: str
    digest_prompt_file: str
    podcast_prompt_file: str

@dataclass
class TTSConfig:
    voice_id: str
    model: str  # "eleven_turbo_v2_5"
    stability: float  # 0.35
    similarity_boost: float  # 0.75
    style: float  # 0.2
    max_chars: int  # varies per show

@dataclass
class AudioConfig:
    music_file: Optional[str]  # None for shows without music
    intro_duration: float
    overlap_duration: float
    fade_duration: float
    outro_duration: float
    intro_volume: float
    overlap_volume: float
    fade_volume: float
    outro_volume: float

@dataclass
class PublishingConfig:
    rss_file: str
    rss_title: str
    rss_description: str
    rss_link: str
    podcast_image: str
    base_url: str  # raw.githubusercontent.com/...
    summaries_json: str
    player_html: str
    summaries_html: str
    x_enabled: bool
    x_env_prefix: str  # "" for Tesla/Omni, "PLANETTERRIAN_" for Planet/FF
    x_teaser_template: str
    x_hashtags: str

@dataclass
class EpisodeConfig:
    prefix: str  # "Omni_View", "Tesla_Shorts_Time_Pod", etc.
    filename_pattern: str
    output_dir: str

@dataclass
class ShowConfig:
    name: str
    slug: str
    description: str
    sources: list[SourceConfig]
    keyword_priorities: list[str]
    llm: LLMConfig
    tts: TTSConfig
    audio: AudioConfig
    publishing: PublishingConfig
    episode: EpisodeConfig
```

Provide `load_config(yaml_path) -> ShowConfig` with sensible defaults.
Add `pyyaml` to requirements-base.txt.

### Show YAML Configs
Extract ACTUAL values from each script into:
- `shows/tesla.yaml`
- `shows/omni_view.yaml`
- `shows/fascinating_frontiers.yaml`
- `shows/planetterrian.yaml`

Read each script to get the real RSS feed URLs, voice IDs, music file paths, X handles, episode prefixes, etc. Don't guess values.

### LLM Prompt Extraction
Extract the LLM prompts (the big multi-line strings passed to Grok) into:
- `shows/prompts/tesla_digest.txt` + `tesla_podcast.txt`
- `shows/prompts/omni_view_digest.txt` + `omni_view_podcast.txt`
- `shows/prompts/fascinating_frontiers_digest.txt` + `_podcast.txt`
- `shows/prompts/planetterrian_digest.txt` + `_podcast.txt`

### Verification
```bash
python -c "from engine.config import load_config; c = load_config('shows/omni_view.yaml'); print(c.name, c.tts.voice_id, len(c.sources))"
```

### Commit
`feat: add show config schema and YAML configs for all 4 shows`

---

## Phase 2B: Generic Show Runner

### run_show.py
Single entry point in project root.

```
Usage: python run_show.py <show_name> [--test] [--dry-run] [--skip-x] [--skip-podcast] [--skip-newsletter]
```

- `--test`: fetch RSS + generate digest only, no TTS or X posting
- `--dry-run`: print what would happen, no API calls at all
- `--skip-x`: everything except X posting
- `--skip-podcast`: everything except TTS/audio/RSS
- `--skip-newsletter`: everything except newsletter

These flags replace the inconsistent feature flag system (Omni View reads TEST_MODE from env, others hardcode it).

Pipeline:
1. Load config: `engine.config.load_config(f"shows/{show_name}.yaml")`
2. Create tracker: `engine.tracking.create_tracker(config)`
3. Fetch news: `engine.fetcher.fetch_rss_articles(config.sources, keywords=config.keyword_priorities)`
4. Run pre-hooks (for Tesla: fetch stock price, fetch X posts)
5. Generate digest: `engine.generator.generate_digest(articles, config)`
6. Generate podcast script: `engine.generator.generate_podcast_script(digest, config)`
7. Synthesize audio: `engine.tts.synthesize(script, config.tts)`
8. Process audio: `engine.audio.normalize_voice()` + optionally `mix_with_music()`
9. Update RSS: `engine.publisher.update_rss_feed(audio, config.publishing)`
10. Save summary: `engine.publisher.save_summary(digest, config.publishing)`
11. Post to X: `engine.publisher.post_to_x(teaser, config.publishing)`
12. Save tracking: `engine.tracking.save_usage(tracker)`

### engine/generator.py
LLM interaction module:
- `generate_digest(articles, config) -> str` — load prompt from file, send to xAI Grok
- `generate_podcast_script(digest, config) -> str` — load prompt from file, send to Grok
- Use tenacity for retries (pattern already in scripts)
- Track token usage via tracker

### shows/hooks/ (for show-specific logic)
- `shows/hooks/tesla.py` — `pre_fetch()` returns extra context (TSLA price, X posts)
- Hooks are optional. Most shows don't need them.
- run_show.py checks for `shows/hooks/{show_name}.py` and calls `pre_fetch()` if it exists

### Verification
```bash
python run_show.py omni_view --test
# Should: fetch RSS, generate digest, print it, exit
# Should NOT: call TTS, post to X, update RSS feed
```

### Commit
`feat: create run_show.py + engine/generator.py`

---

## Phase 2C: Validate All Shows

Make run_show.py work for all 4 shows.

```bash
python run_show.py omni_view --test
python run_show.py fascinating_frontiers --test
python run_show.py planetterrian --test
python run_show.py tesla --test
```

For Tesla, implement `shows/hooks/tesla.py`:
- `pre_fetch()` calls `yfinance` for TSLA price
- `pre_fetch()` optionally fetches X posts from Tesla-related accounts
- Returns dict of extra context injected into the article list

Fix any issues. All 4 should complete --test without errors.

```bash
python -m pytest tests/ -v
```

### Commit
`feat: all 4 shows working through run_show.py`

---

## Phase 3: Unified GitHub Actions Workflow

Create `.github/workflows/run-show.yml` replacing all 4 separate workflows.

### Schedule
All cron entries from existing workflows:
```yaml
schedule:
  - cron: '0 10 * * *'        # Omni View (EDT)
  - cron: '0 11 * * *'        # Tesla + Omni View EST fallback
  - cron: '0 12 1-31/2 * *'   # Planetterrian (odd days)
  - cron: '0 12 2-31/2 * *'   # Fascinating Frontiers (even days)
```

### Manual dispatch
```yaml
workflow_dispatch:
  inputs:
    show:
      description: 'Show to run'
      required: true
      type: choice
      options: [tesla, omni_view, fascinating_frontiers, planetterrian, all]
```

### Gate job
Python script that maps cron time → show name(s):
- 10:00 UTC + Eastern hour == 6 → omni_view
- 11:00 UTC + Eastern hour == 7 → tesla; Eastern hour == 6 → omni_view (EST)
- 12:00 UTC + odd day → planetterrian
- 12:00 UTC + even day → fascinating_frontiers
- DST-aware (reuse the zoneinfo pattern from omni-view-daily.yml)
- Output: JSON array of show names

### Matrix job
For each show in the array:
- Checkout, Python 3.11, ffmpeg, pip install requirements-base.txt
- If show is tesla: also pip install requirements-tesla.txt
- Create .env from secrets — include ALL secrets needed by any show
  - IMPORTANT: Drop NEWSAPI_KEY (dead)
  - IMPORTANT: Map X credential prefixes correctly per show
- Run: `python run_show.py ${{ matrix.show }}`
- Git add/commit/push with retry logic

### Concurrency
Group by show name: `group: show-${{ matrix.show }}`

### Cleanup
Rename old workflows to .yml.bak

### Verification
```bash
python -c "import yaml; yaml.safe_load(open('.github/workflows/run-show.yml'))"
```

### Commit
`feat: unified GitHub Actions workflow for all shows`

---

## Phase 4A: R2 Storage — Code Changes

See docs/audio_storage_plan.md for full context. This phase creates the code; actual R2 bucket setup is manual.

### engine/storage.py
```python
def upload_to_r2(local_path, remote_key, bucket, endpoint_url, access_key, secret_key) -> str:
    """Upload file to Cloudflare R2, return public URL."""
    # Uses boto3 with S3-compatible endpoint
```

### Modify engine/publisher.py
- `update_rss_feed()` accepts optional `audio_url` parameter
- If provided, use it as enclosure URL instead of constructing a GitHub raw URL
- Never modify URLs for existing episodes — only new ones

### Modify run_show.py
After audio creation:
- If storage config present, upload to R2 and get URL
- Pass URL to RSS update
- During transition, still git-add MP3 (dual-write)

### Config additions
```yaml
storage:
  provider: "r2"  # or "github" for backward compat
  bucket: "podcast-audio"
  endpoint_env: "R2_ENDPOINT_URL"
  access_key_env: "R2_ACCESS_KEY_ID"
  secret_key_env: "R2_SECRET_ACCESS_KEY"
  public_base_url: "https://audio.yourdomain.com"
```

Don't enable R2 in any config yet — just wire up the capability.
Add `boto3` to requirements-base.txt.

### Commit
`feat: add R2 storage support for podcast audio`

---

## Phase 4B: R2 Migration Scripts

### scripts/migrate_audio_to_r2.py
- Read all 4 RSS feeds
- For each episode, upload MP3 to R2
- Update enclosure URL in RSS to use R2
- Dry-run by default, --execute to actually run
- Progress logging

### scripts/verify_r2_migration.py
- Curl each enclosure URL in each RSS feed
- Verify HTTP 200 + audio/mpeg content type
- Report broken links

### Enable R2
- Set `storage.provider: "r2"` in all show configs
- Add `digests/**/*.mp3` to .gitignore
- Update run_show.py to not git-add MP3 when R2 is enabled

### Commit
`feat: R2 migration scripts + enable R2 in configs`

---

## Phase 5: Environmental Intelligence Show

New show targeting BC environmental professionals.

### shows/environmental_intel.yaml
- Name: Environmental Intelligence
- Slug: env_intel
- TTS: ElevenLabs, voice_id ns7MjJ6c8tJKnvw7U6sN
- Schedule: weekdays 6am Pacific

RSS feeds — search the web for REAL, working feeds. Verify each with curl. Sources:
- BC government environment / climate
- Environment and Climate Change Canada
- US EPA newsroom  
- Canadian environmental law / regulatory
- Environmental science journals
- BC-specific environmental news
- Contaminated sites / remediation industry

### shows/prompts/env_intel_digest.txt
Expert environmental science journalist prompt. Deep knowledge of BC CSR, EMA, CEPA, ISO 17025. Tone: professional briefing. Structure: Lead Story, Regulatory Watch, Science & Research, Industry & Compliance, Week Ahead.

### shows/prompts/env_intel_podcast.txt
Podcast script prompt — authoritative, accessible, ~5-7 min.

### GitHub Pages
- `env-intel.html` — player page (adapt from omni-view.html)
- `env-intel-summaries.html` — summaries page

### Workflow
Add cron `'0 14 * * 1-5'` (6am Pacific weekdays) to run-show.yml gate logic.

### Verification
```bash
python run_show.py env_intel --test
```

### Commit
`feat: add Environmental Intelligence show`

---

## Phase 6: Newsletter Integration

### Research
Check APIs for Beehiiv, Buttondown, ConvertKit, Substack.
Find: free tier limits, multi-publication support, API for automated sending, RSS-to-email.
Create `docs/newsletter_comparison.md` with recommendation.

### engine/newsletter.py
- `convert_digest_to_email_html(markdown_text) -> str` — clean HTML, inline CSS, mobile-friendly
- `send_newsletter(html_content, subject, config) -> bool`

### Config addition
```yaml
newsletter:
  enabled: true
  platform: "beehiiv"  # or whatever is recommended
  publication_id: "xxx"
  api_key_env: "SHOW_NEWSLETTER_API_KEY"
```

### Integration
Add to run_show.py between GitHub Pages save and X post. Respect --skip-newsletter.
Enable in env_intel and omni_view configs. Leave others disabled.

### Commit
`feat: add newsletter publishing to engine`

---

## Phase 7: Analytics + Monetization

### Podcast analytics
Research OP3 (op3.dev) — free, open-source. If viable, prefix MP3 URLs.
Add to engine/publisher.py and config:
```yaml
analytics:
  enabled: true
  prefix_url: "https://op3.dev/e/"
```

### Documentation
- `docs/podcast_directories.md` — submission steps per platform
- `docs/monetization_roadmap.md` — episode counts, ad network thresholds, CPM estimates, timeline

### Commit
`feat: add analytics prefix + monetization docs`

---

## Phase 8: Final Cleanup

1. Remove all `# MIGRATED` comments from show scripts
2. Move old standalone scripts to `legacy/`
3. Move old .yml.bak workflows to `legacy/workflows/`
4. Update README.md — project overview, architecture, how to add a show, how to run, links, costs
5. Final validation:
```bash
python -m pytest tests/ -v
python run_show.py omni_view --test
python run_show.py tesla --test
python run_show.py fascinating_frontiers --test
python run_show.py planetterrian --test
python run_show.py env_intel --test
```
6. Show line count comparison: old vs new
7. Mark all checkboxes at the top of this file as done

### Commit
`refactor: final cleanup, update README, ready for merge`

### After this commit — merge manually:
```bash
git checkout main
git merge refactor/engine-extraction
git push origin main
```
Then monitor the next day's GitHub Actions runs.
