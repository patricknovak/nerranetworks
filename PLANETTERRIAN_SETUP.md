# Planetterrian Daily Setup Guide

## Overview

Planetterrian Daily is a new daily science, longevity, and health discovery digest and podcast, following the same structure as Tesla Shorts Time but focused on scientific breakthroughs, longevity research, and health discoveries.

## Files Created

1. **`digests/planetterrian.py`** - Main script for generating daily digest and podcast
2. **`planetterrian.html`** - GitHub Pages website for Planetterrian Daily
3. **`planetterrian_podcast.rss`** - RSS feed for the podcast (will be generated automatically)

## Environment Variables Required

### For Local Runs

Add these to your `.env` file:

```bash
# Grok API (same as Tesla show)
GROK_API_KEY=your_grok_api_key

# TTS (Chatterbox local voice cloning)
PLANETTERRIAN_TTS_PROVIDER=chatterbox
CHATTERBOX_VOICE_PROMPT_PATH=/absolute/path/to/your_voice_sample.(wav|mp3)
CHATTERBOX_DEVICE=cpu
CHATTERBOX_EXAGGERATION=0.5
CHATTERBOX_MAX_CHARS=600

# Optional fallback: ElevenLabs (only needed if you switch PLANETTERRIAN_TTS_PROVIDER=elevenlabs)
# ELEVENLABS_API_KEY=your_elevenlabs_api_key
# ELEVENLABS_VOICE_ID=your_elevenlabs_voice_id  # optional

# X API credentials for @planetterrian account
PLANETTERRIAN_X_CONSUMER_KEY=your_consumer_key
PLANETTERRIAN_X_CONSUMER_SECRET=your_consumer_secret
PLANETTERRIAN_X_ACCESS_TOKEN=your_access_token
PLANETTERRIAN_X_ACCESS_TOKEN_SECRET=your_access_token_secret
PLANETTERRIAN_X_BEARER_TOKEN=your_bearer_token
```

### For GitHub Actions (Automated Daily Runs)

If you want to run Planetterrian Daily automatically via GitHub Actions, add these as **GitHub Secrets**:

1. Go to your repository → **Settings** → **Secrets and variables** → **Actions**
2. Click **"New repository secret"** and add:

**Required Secrets:**
- `GROK_API_KEY` - Your Grok/X.AI API key (shared with Tesla show)
- `PLANETTERRIAN_VOICE_PROMPT_BASE64` - Base64 of a short voice sample (5–10s) used for Chatterbox voice cloning

**Optional Secrets (fallback only):**
- `ELEVENLABS_API_KEY` - Only needed if you switch `PLANETTERRIAN_TTS_PROVIDER=elevenlabs`

**Required for X Posting:**
- `PLANETTERRIAN_X_CONSUMER_KEY` - X API consumer key for @planetterrian
- `PLANETTERRIAN_X_CONSUMER_SECRET` - X API consumer secret for @planetterrian
- `PLANETTERRIAN_X_ACCESS_TOKEN` - X API access token for @planetterrian
- `PLANETTERRIAN_X_ACCESS_TOKEN_SECRET` - X API access token secret for @planetterrian
- `PLANETTERRIAN_X_BEARER_TOKEN` - X API bearer token for @planetterrian (optional but recommended)

**Note:** The GitHub Actions workflow (`.github/workflows/planetterrian-daily.yml`) will automatically use these secrets to create a `.env` file when running.

## Voice Cloning (Chatterbox) – Creating Your Voice Prompt

Chatterbox voice cloning in this project is **prompt-based**: each run conditions the voice on a short reference clip.

### Option A (Recommended): Derive the prompt from an existing Planetterrian episode

If you already have Planetterrian episode MP3s committed in `digests/planetterrian/`, you can **skip** providing a prompt file/secret.  
The script will automatically extract a short voice-only window from the most recent episode and use it as the Chatterbox prompt.

**Note:** This will clone the voice heard in those episodes (e.g., if older episodes were generated with ElevenLabs, you’ll be cloning that voice).

### Option B: Provide your own prompt clip (local or GitHub Secrets)

1. Record a clean voice sample (quiet room, no music), **5–10 seconds** is plenty.
2. Convert it to a small MP3 (recommended for GitHub Secrets size limits):

```bash
ffmpeg -y -i input.wav -t 8 -ac 1 -ar 16000 -b:a 64k voice_prompt.mp3
```

3. Base64 encode it and save as the GitHub secret `PLANETTERRIAN_VOICE_PROMPT_BASE64`:

- macOS (copies to clipboard):

```bash
base64 -i voice_prompt.mp3 | tr -d '\n' | pbcopy
```

- Linux:

```bash
base64 -w 0 voice_prompt.mp3
```

## Running the Script

```bash
pip install -r requirements_planetterrian.txt
cd digests
python3 planetterrian.py
```

## Features

### Content Focus
- **Science News**: Breakthroughs in biotechnology, genetics, medicine
- **Longevity Research**: Anti-aging, lifespan extension, healthspan
- **Health Discoveries**: Medical breakthroughs, treatments, wellness

### RSS Feeds Monitored
- Nature
- Science Magazine
- New Scientist
- Scientific American
- Longevity Technology
- Lifespan.io
- Healthline
- Medical News Today
- NIH News
- CDC
- WHO
- Science Daily

### X Accounts Followed
- Science publications: @Nature, @sciencemagazine, @newscientist
- Longevity researchers: @DavidSinclairPhD, @peterattiamd, @RhondaPatrick, @BryanJohnson
- Health organizations: @WHO, @CDCgov, @NIH
- Science communicators: @neiltyson, @BillNye

### Brand Personality
Based on [planetterrian.com/about](https://planetterrian.com/about):
- **Mission**: Intertwine technology and compassion
- **Values**: Technology as a force for good, sustainability, environmental consciousness
- **Tone**: Inspirational, optimistic, planet-conscious, compassionate, forward-thinking
- **Focus**: Groundbreaking solutions that are state-of-the-art AND sustainable

## Output Files

All files are saved in `digests/planetterrian/`:
- `Planetterrian_Daily_YYYYMMDD.md` - X thread/digest
- `Planetterrian_Daily_EpXXX_YYYYMMDD.mp3` - Podcast audio
- `podcast_transcript_YYYYMMDD.txt` - Podcast transcript
- `credit_usage_YYYY-MM-DD_epXXX.json` - API usage tracking
- `raw_data_YYYY-MM-DD.json` - Raw news and X posts data

## RSS Feed

The RSS feed is automatically generated at:
- File: `planetterrian_podcast.rss` (in project root)
- URL: `https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main/planetterrian_podcast.rss`

## GitHub Pages Setup

1. The `planetterrian.html` file is ready to use
2. You can either:
   - Set up a separate GitHub Pages site for Planetterrian
   - Or serve it from a subdirectory in the existing repo

## Differences from Tesla Shorts Time

1. **Content Focus**: Science/longevity/health instead of Tesla news
2. **RSS Feeds**: Science publications instead of Tesla news sites
3. **X Accounts**: Science/longevity researchers instead of Tesla accounts
4. **Brand Voice**: Planet-conscious, compassionate, sustainability-focused
5. **File Naming**: `Planetterrian_Daily_*` instead of `Tesla_Shorts_Time_*`
6. **RSS Feed**: `planetterrian_podcast.rss` instead of `podcast.rss`
7. **X Account**: Uses @planetterrian instead of @teslashortstime

## Next Steps

### Local Setup
1. ✅ Add X API credentials for @planetterrian to `.env` (you've done this!)
2. Test run the script: `python3 digests/planetterrian.py`

### GitHub Actions Setup (Optional - for automated daily runs)
1. Add Planetterrian X API credentials to **GitHub Secrets** (see above)
2. The workflow file (`.github/workflows/planetterrian-daily.yml`) is already created
3. Enable workflow permissions:
   - Go to **Settings** → **Actions** → **General**
   - Under **"Workflow permissions"**, select **"Read and write permissions"**
   - Click **Save**
4. Test the workflow:
   - Go to **Actions** tab → **Planetterrian Daily** workflow
   - Click **"Run workflow"** → **"Run workflow"** (manual trigger)

### Website Setup
1. Set up GitHub Pages for the Planetterrian site
2. Create podcast cover image: `planetterrian-podcast-image.jpg`
3. Submit podcast to Apple Podcasts (when ready)

## Notes

- The podcast voice comes from a short voice sample (voice cloning via Chatterbox)
- Credit usage is tracked separately for Planetterrian
- The RSS feed is separate from the Tesla show's feed
- All files are organized in `digests/planetterrian/` subdirectory

