"""Publishing helpers for the podcast generation pipeline.

Provides:
  - update_rss_feed(): feedgen-based RSS feed creation/update with episode dedup
  - get_next_episode_number(): find the highest existing episode and return +1
  - save_summary_to_github_pages(): append episode summary to JSON for GitHub Pages
  - post_to_x(): post a tweet via tweepy (accepts credentials as params)
  - generate_episode_thumbnail(): simple PIL-based thumbnail overlay
"""

import datetime
import json
import logging
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Analytics prefix
# ---------------------------------------------------------------------------

def apply_op3_prefix(url: str, prefix_url: str = "https://op3.dev/e/") -> str:
    """Prepend the OP3 analytics prefix to an audio URL.

    For HTTPS URLs, the ``https://`` scheme is stripped before prepending.
    For HTTP URLs, the full original URL (with scheme) is appended.

    Example::

        >>> apply_op3_prefix("https://cdn.example.com/ep1.mp3")
        'https://op3.dev/e/cdn.example.com/ep1.mp3'
    """
    if url.startswith("https://"):
        return prefix_url + url[len("https://"):]
    if url.startswith("http://"):
        return prefix_url + url
    return prefix_url + url


# ---------------------------------------------------------------------------
# RSS feed update
# ---------------------------------------------------------------------------

def update_rss_feed(
    rss_path: Path,
    episode_num: int,
    episode_title: str,
    episode_description: str,
    episode_date: datetime.date,
    mp3_filename: str,
    mp3_duration: float,
    mp3_path: Path,
    *,
    base_url: str = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main",
    audio_url: Optional[str] = None,
    audio_subdir: str = "digests",
    channel_title: str = "Podcast",
    channel_link: str = "https://example.com",
    channel_description: str = "A podcast.",
    channel_language: str = "en-us",
    channel_author: str = "Patrick",
    channel_email: str = "contact@example.com",
    channel_image: str = "",
    channel_category: str = "Technology",
    guid_prefix: str = "podcast",
    format_duration_func=None,
) -> Path:
    """Create or update an RSS feed with a new episode.

    Parses any existing RSS file to preserve previous episodes, deduplicates
    by episode number, adds the new episode, and writes back via feedgen.

    Parameters
    ----------
    rss_path:
        Path to the ``.rss`` file.
    episode_num, episode_title, episode_description, episode_date:
        Metadata for the new episode.
    mp3_filename:
        Filename of the audio file (used to build the enclosure URL).
    mp3_duration:
        Duration of the audio in seconds.
    mp3_path:
        Local path to the MP3 (used to read file size).
    base_url:
        GitHub raw content base URL.
    audio_url:
        If provided, used as the enclosure URL directly (e.g. from R2).
    audio_subdir:
        Subdirectory under *base_url* where audio lives (default ``"digests"``).
    channel_*:
        RSS channel-level metadata.
    guid_prefix:
        Prefix for episode GUID strings.
    format_duration_func:
        Optional callable ``(float) -> str`` for formatting duration.
        If ``None``, a simple ``HH:MM:SS`` formatter is used.

    Returns
    -------
    Path
        The *rss_path* that was written.
    """
    from feedgen.feed import FeedGenerator

    if format_duration_func is None:
        from engine.audio import format_duration
        format_duration_func = format_duration

    fg = FeedGenerator()
    fg.load_extension("podcast")

    # --- Parse existing episodes -------------------------------------------
    existing_episodes = []
    if rss_path.exists():
        try:
            tree = ET.parse(str(rss_path))
            root = tree.getroot()
            channel = root.find("channel")
            if channel is not None:
                for item in channel.findall("item"):
                    ep_data: dict = {}
                    for elem in item:
                        tag = elem.tag
                        if tag == "title":
                            ep_data["title"] = elem.text or ""
                        elif tag == "description":
                            ep_data["description"] = elem.text or ""
                        elif tag == "guid" and elem.text:
                            ep_data["guid"] = elem.text.strip()
                        elif tag == "pubDate":
                            ep_data["pubDate"] = elem.text or ""
                        elif tag == "enclosure":
                            ep_data["enclosure"] = {
                                "url": elem.get("url", ""),
                                "type": elem.get("type", "audio/mpeg"),
                                "length": elem.get("length", "0"),
                            }
                        elif tag == "{http://www.itunes.com/dtds/podcast-1.0.dtd}episode":
                            ep_data["itunes_episode"] = elem.text or ""
                        elif tag == "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration":
                            ep_data["itunes_duration"] = elem.text or ""
                        elif tag == "{http://www.itunes.com/dtds/podcast-1.0.dtd}title":
                            ep_data["itunes_title"] = elem.text or ""
                        elif tag == "{http://www.itunes.com/dtds/podcast-1.0.dtd}summary":
                            ep_data["itunes_summary"] = elem.text or ""
                        elif tag == "{http://www.itunes.com/dtds/podcast-1.0.dtd}season":
                            ep_data["itunes_season"] = elem.text or ""
                        elif tag == "{http://www.itunes.com/dtds/podcast-1.0.dtd}episodeType":
                            ep_data["itunes_episode_type"] = elem.text or ""
                    if ep_data.get("guid"):
                        existing_episodes.append(ep_data)
        except Exception as exc:
            logger.warning("Could not parse existing RSS feed: %s", exc)

    # --- Deduplicate by episode number ------------------------------------
    episodes_by_number: dict = {}
    for ep_data in existing_episodes:
        ep_num_str = ep_data.get("itunes_episode", "")
        if not ep_num_str:
            guid = ep_data.get("guid", "")
            match = re.search(r"ep(\d+)", guid)
            if match:
                ep_num_str = match.group(1)
        if ep_num_str:
            try:
                num = int(ep_num_str)
                if num not in episodes_by_number:
                    episodes_by_number[num] = ep_data
                else:
                    # Keep the one with the more recent GUID timestamp
                    old_guid = episodes_by_number[num].get("guid", "")
                    new_guid = ep_data.get("guid", "")
                    old_ts = old_guid.split("-")[-1] if "-" in old_guid else "000000"
                    new_ts = new_guid.split("-")[-1] if "-" in new_guid else "000000"
                    if new_ts > old_ts:
                        episodes_by_number[num] = ep_data
            except ValueError:
                pass

    # --- Set channel metadata ---------------------------------------------
    fg.title(channel_title)
    fg.link(href=channel_link)
    fg.description(channel_description)
    fg.language(channel_language)
    fg.copyright(f"Copyright {datetime.date.today().year}")
    fg.podcast.itunes_author(channel_author)
    fg.podcast.itunes_summary(channel_description)
    fg.podcast.itunes_owner(name=channel_author, email=channel_email)
    if channel_image:
        fg.podcast.itunes_image(channel_image)
    fg.podcast.itunes_category(channel_category)
    fg.podcast.itunes_explicit("no")

    # --- Re-add existing episodes (skip the one being replaced) -----------
    current_time_str = datetime.datetime.now().strftime("%H%M%S")
    new_guid = f"{guid_prefix}-ep{episode_num:03d}-{episode_date:%Y%m%d}-{current_time_str}"

    for ep_data in episodes_by_number.values():
        ep_num_str = ep_data.get("itunes_episode", "")
        if not ep_num_str:
            guid = ep_data.get("guid", "")
            m = re.search(r"ep(\d+)", guid)
            if m:
                ep_num_str = m.group(1)
        if ep_num_str and int(ep_num_str) == episode_num:
            logger.info(
                "Replacing existing episode %s with new version", ep_num_str
            )
            continue
        if ep_data.get("guid") == new_guid:
            continue

        entry = fg.add_entry()
        entry.id(ep_data.get("guid", ""))
        entry.title(ep_data.get("title", ""))
        entry.description(ep_data.get("description", ""))

        if ep_data.get("pubDate"):
            try:
                if isinstance(ep_data["pubDate"], datetime.datetime):
                    entry.pubDate(ep_data["pubDate"])
                else:
                    entry.pubDate(parsedate_to_datetime(ep_data["pubDate"]))
            except Exception:
                pass

        if ep_data.get("enclosure"):
            enc = ep_data["enclosure"]
            entry.enclosure(
                url=enc.get("url", ""),
                type=enc.get("type", "audio/mpeg"),
                length=enc.get("length", "0"),
            )

        if ep_data.get("itunes_title"):
            entry.podcast.itunes_title(ep_data["itunes_title"])
        if ep_data.get("itunes_summary"):
            entry.podcast.itunes_summary(ep_data["itunes_summary"])
        if ep_data.get("itunes_duration"):
            entry.podcast.itunes_duration(ep_data["itunes_duration"])
        if ep_data.get("itunes_episode"):
            entry.podcast.itunes_episode(ep_data["itunes_episode"])
        if ep_data.get("itunes_season"):
            entry.podcast.itunes_season(ep_data["itunes_season"])
        if ep_data.get("itunes_episode_type"):
            entry.podcast.itunes_episode_type(ep_data["itunes_episode_type"])
        entry.podcast.itunes_explicit("no")
        if channel_image:
            entry.podcast.itunes_image(channel_image)

    # --- Add the new episode ----------------------------------------------
    entry = fg.add_entry()
    entry.id(new_guid)
    entry.title(episode_title)
    entry.description(episode_description)

    if audio_url:
        mp3_url = audio_url
    else:
        mp3_url = f"{base_url}/{audio_subdir}/{mp3_filename}"
    entry.link(href=mp3_url)

    pub_date = datetime.datetime.combine(
        episode_date,
        datetime.time(8, 0, 0),
        tzinfo=datetime.timezone.utc,
    )
    entry.pubDate(pub_date)

    mp3_size = mp3_path.stat().st_size if mp3_path.exists() else 0
    entry.enclosure(url=mp3_url, type="audio/mpeg", length=str(mp3_size))

    entry.podcast.itunes_title(episode_title)
    entry.podcast.itunes_summary(episode_description)
    entry.podcast.itunes_duration(format_duration_func(mp3_duration))
    entry.podcast.itunes_episode(str(episode_num))
    entry.podcast.itunes_season("1")
    entry.podcast.itunes_episode_type("full")
    entry.podcast.itunes_explicit("no")
    if channel_image:
        entry.podcast.itunes_image(channel_image)

    fg.lastBuildDate(datetime.datetime.now(datetime.timezone.utc))
    fg.rss_file(str(rss_path), pretty=True)
    logger.info("RSS feed updated: %s", rss_path)
    return rss_path


# ---------------------------------------------------------------------------
# Episode numbering
# ---------------------------------------------------------------------------

def get_next_episode_number(
    rss_path: Path,
    digests_dir: Path,
    mp3_glob_pattern: str = "*_Ep*.mp3",
) -> int:
    """Find the highest existing episode number and return ``max + 1``.

    Checks both the RSS feed (``<itunes:episode>`` tags) and the file
    system (MP3 filenames matching *mp3_glob_pattern*).
    """
    max_episode = 0

    # Check RSS feed
    if rss_path.exists():
        try:
            tree = ET.parse(str(rss_path))
            root = tree.getroot()
            channel = root.find("channel")
            if channel is not None:
                ns = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
                for item in channel.findall("item"):
                    ep_el = item.find(f"{ns}episode")
                    if ep_el is not None and ep_el.text:
                        try:
                            max_episode = max(max_episode, int(ep_el.text))
                        except ValueError:
                            pass
        except Exception as exc:
            logger.warning("Could not parse RSS feed for episode number: %s", exc)

    # Scan MP3 filenames
    for mp3_file in digests_dir.glob(mp3_glob_pattern):
        match = re.search(r"Ep(\d+)", mp3_file.name)
        if match:
            try:
                max_episode = max(max_episode, int(match.group(1)))
            except ValueError:
                pass

    next_ep = max_episode + 1
    logger.info("Next episode number: %d (highest existing: %d)", next_ep, max_episode)
    return next_ep


# ---------------------------------------------------------------------------
# GitHub Pages summary saving
# ---------------------------------------------------------------------------

def save_summary_to_github_pages(
    summary_text: str,
    summaries_json_path: Path,
    podcast_name: str,
    *,
    episode_num: Optional[int] = None,
    episode_title: Optional[str] = None,
    audio_url: Optional[str] = None,
    rss_url: Optional[str] = None,
    max_summaries: int = 30,
) -> Optional[Path]:
    """Append an episode summary to the GitHub Pages JSON file.

    The file stores the most recent *max_summaries* entries (newest first).
    Returns the path to the JSON file on success, ``None`` on error.
    """
    try:
        if summaries_json_path.exists():
            with open(summaries_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {"podcast": podcast_name, "summaries": []}

        now = datetime.datetime.now()
        entry = {
            "date": now.strftime("%Y-%m-%d"),
            "datetime": now.isoformat(),
            "content": summary_text,
            "episode_num": episode_num,
            "episode_title": episode_title,
            "audio_url": audio_url,
            "rss_url": rss_url,
        }

        data["summaries"].insert(0, entry)
        data["summaries"] = data["summaries"][:max_summaries]

        with open(summaries_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("Summary saved to GitHub Pages JSON: %s", summaries_json_path)
        return summaries_json_path

    except Exception as exc:
        logger.error("Failed to save summary to GitHub Pages: %s", exc)
        return None


# ---------------------------------------------------------------------------
# X / Twitter posting
# ---------------------------------------------------------------------------

def post_to_x(
    text: str,
    *,
    consumer_key: str,
    consumer_secret: str,
    access_token: str,
    access_token_secret: str,
) -> Optional[str]:
    """Post a tweet and return the tweet URL, or ``None`` on failure.

    Credentials are accepted as explicit parameters so the caller (or
    config system) decides which env vars to read.
    """
    try:
        import tweepy

        client = tweepy.Client(
            consumer_key=consumer_key,
            consumer_secret=consumer_secret,
            access_token=access_token,
            access_token_secret=access_token_secret,
        )
        response = client.create_tweet(text=text)
        tweet_id = response.data["id"]
        tweet_url = f"https://x.com/i/status/{tweet_id}"
        logger.info("Tweet posted: %s", tweet_url)
        return tweet_url

    except Exception as exc:
        logger.error("X post failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Episode thumbnail
# ---------------------------------------------------------------------------

def generate_episode_thumbnail(
    base_image_path: Path,
    episode_num: int,
    date_str: str,
    output_path: Path,
) -> Path:
    """Generate a simple episode thumbnail by overlaying text on a base image."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(base_image_path)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except IOError:
        font = ImageFont.load_default()
    draw.text((50, 50), f"Episode {episode_num}", font=font, fill=(255, 255, 255))
    draw.text((50, 100), date_str, font=font, fill=(255, 255, 255))
    img.save(output_path, "PNG")
    return output_path


# ---------------------------------------------------------------------------
# Digest formatting for X posting
# ---------------------------------------------------------------------------

def format_digest_for_x(digest: str) -> str:
    """Format a digest for X posting by stripping markdown formatting.

    Removes headers, bold markers, and markdown link syntax while preserving
    the actual content text and URLs. Suitable for shows with simple formatting
    needs (FF, PT).  TST has its own extended version with emoji formatting.
    """
    formatted = digest

    # Remove markdown headers but keep text
    formatted = re.sub(r'^#+\s+', '', formatted, flags=re.MULTILINE)

    # Convert markdown bold to plain text
    formatted = re.sub(r'\*\*(.*?)\*\*', r'\1', formatted)

    # Extract URLs from markdown links
    formatted = re.sub(r'\[([^\]]+)\]\((https?://[^\)]+)\)', r'\2', formatted)

    # Remove excessive blank lines
    formatted = re.sub(r'\n{3,}', '\n\n', formatted)

    return formatted.strip()
