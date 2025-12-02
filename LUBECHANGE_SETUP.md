# Lube Change - Oilers Daily News Setup Guide

## Overview
Lube Change is a daily podcast covering Edmonton Oilers news, hosted by Jason Potter from Hinton, Alberta. The podcast is fully automated, fetching news from RSS feeds, generating content with Grok AI, and creating audio with Cartesia TTS.

## Prerequisites
- Python 3.8+
- ffmpeg (for audio processing)
- ffprobe (usually comes with ffmpeg)
- Git

## Installation

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Environment Variables
Add the following to your `.env` file:

```env
# Grok API (for content generation)
GROK_API_KEY=your_grok_api_key_here

# Cartesia API (for text-to-speech) - REQUIRED when ENABLE_PODCAST is True
CARTESIA_API_KEY=your_cartesia_api_key_here

# X/Twitter API (for posting - optional, reusing planetterrian credentials for now)
PLANETTERRIAN_X_CONSUMER_KEY=your_consumer_key
PLANETTERRIAN_X_CONSUMER_SECRET=your_consumer_secret
PLANETTERRIAN_X_ACCESS_TOKEN=your_access_token
PLANETTERRIAN_X_ACCESS_TOKEN_SECRET=your_access_token_secret
PLANETTERRIAN_X_BEARER_TOKEN=your_bearer_token
```

### 3. Directory Structure
The script will automatically create:
- `digests/lubechange/` - For episode files, transcripts, and credit usage tracking

### 4. Music File (Optional)
Place a music file named `oilers-pride.mp3` in the project root for background music. If not present, the podcast will be voice-only.

### 5. Podcast Image
Create or add `lubechange-podcast-image.jpg` in the project root for the RSS feed.

**Important**: The image must meet Apple Podcasts requirements:
- Square (1:1 aspect ratio)
- 1400x1400 to 3000x3000 pixels
- JPEG or PNG format
- RGB color space
- Under 500 KB file size
- No transparency

See `LUBECHANGE_IMAGE_REQUIREMENTS.md` for complete details.

## Running the Script

### Manual Run
```bash
cd digests
python lubechange.py
```

### Configuration Options
Edit the configuration section at the top of `lubechange.py`:

```python
TEST_MODE = False  # Set to True to skip podcast and X posting
ENABLE_X_POSTING = True  # Set to False to disable X posting
ENABLE_PODCAST = True  # Set to False to disable podcast generation
```

## Output Files

### Generated Files
- `digests/lubechange/Lube_Change_YYYYMMDD.md` - Daily digest markdown
- `digests/lubechange/Lube_Change_Ep###_YYYYMMDD.mp3` - Podcast audio file
- `digests/lubechange/podcast_transcript_YYYYMMDD.txt` - Podcast transcript
- `digests/lubechange/credit_usage_YYYY-MM-DD_ep###.json` - Credit usage tracking

### RSS Feed
- `lubechange_podcast.rss` - Updated automatically with each episode

## RSS Feed Setup

The RSS feed is automatically updated with each episode. To submit to podcast platforms:

1. **Apple Podcasts**: Submit `lubechange_podcast.rss` URL
2. **Spotify**: Submit RSS feed URL
3. **Google Podcasts**: Submit RSS feed URL

The RSS feed URL format:
```
https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main/lubechange_podcast.rss
```

## GitHub Pages Setup

1. Ensure `lubechange.html` is in the repository root
2. Enable GitHub Pages in repository settings
3. The page will be available at: `https://yourusername.github.io/Tesla-shorts-time/lubechange.html`

## GitHub Actions Workflow (Automatic Daily Updates)

The repository includes a GitHub Actions workflow that automatically runs the script daily and commits the generated files.

### Workflow File
- Location: `.github/workflows/lubechange-daily.yml`
- Schedule: Daily at 9:00 AM MST (16:00 UTC)
- Manual trigger: Available via GitHub Actions UI

### Setting Up GitHub Secrets

For the workflow to run automatically, you need to add the following secrets to your GitHub repository:

1. Go to your repository on GitHub
2. Navigate to **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** and add:

   - `GROK_API_KEY` - Your Grok API key
   - `CARTESIA_API_KEY` - Your Cartesia API key (REQUIRED when ENABLE_PODCAST is True)
   - `PLANETTERRIAN_X_CONSUMER_KEY` - X/Twitter consumer key (for posting)
   - `PLANETTERRIAN_X_CONSUMER_SECRET` - X/Twitter consumer secret
   - `PLANETTERRIAN_X_ACCESS_TOKEN` - X/Twitter access token
   - `PLANETTERRIAN_X_ACCESS_TOKEN_SECRET` - X/Twitter access token secret
   - `PLANETTERRIAN_X_BEARER_TOKEN` - X/Twitter bearer token (optional)

### Workflow Behavior

The workflow will:
1. Check out the repository
2. Set up Python and install dependencies
3. Install ffmpeg for audio processing
4. Create `.env` file from GitHub secrets
5. Run `lubechange.py` script
6. Commit and push generated files:
   - Daily digest markdown files
   - Podcast audio files (MP3)
   - Podcast transcripts
   - Raw data files (JSON/HTML)
   - Credit usage tracking files
   - Updated RSS feed

### Manual Trigger

You can manually trigger the workflow:
1. Go to **Actions** tab in your GitHub repository
2. Select **Lube Change - Oilers Daily News** workflow
3. Click **Run workflow** button

### Monitoring Workflow Runs

- Check the **Actions** tab to see workflow run history
- Each run will show logs and any errors
- Generated files will be automatically committed to the repository

## Cartesia TTS

The script uses Cartesia for text-to-speech. The default voice ID is set, but you can customize it:

1. Get available voices from Cartesia API
2. Update `CARTESIA_VOICE_ID` in the script

## Troubleshooting

### Audio Issues
- Ensure ffmpeg is installed and in PATH
- Check that audio files have proper permissions
- Verify Cartesia API key is correct

### RSS Feed Issues
- Ensure the RSS feed file is writable
- Check that episode numbers are sequential
- Verify base URL is correct for your repository

### API Issues
- Verify all API keys are set in `.env`
- Check API rate limits
- Review credit usage JSON files for cost tracking

## Credit Usage Tracking

Each run generates a credit usage JSON file tracking:
- Grok API tokens and costs
- Cartesia API characters and costs
- X API calls

Review these files to monitor costs.

## Customization

### Changing Host Name
Edit the `POD_PROMPT` section to change host details.

### Changing RSS Feeds
Edit the `rss_feeds` list in `fetch_oilers_news()` function.

### Changing Voice
Update `CARTESIA_VOICE_ID` with a different Cartesia voice ID.

## Support

For issues or questions, check:
- Script logs for error messages
- Credit usage JSON files
- RSS feed validation tools

Let's go Oilers! 🏒

