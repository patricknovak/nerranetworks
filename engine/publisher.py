"""Publishing helpers for the podcast generation pipeline.

Provides:
  - update_rss_feed(): feedgen-based RSS feed creation/update with episode dedup
  - get_next_episode_number(): find the highest existing episode and return +1
  - save_summary_to_github_pages(): append episode summary to JSON for GitHub Pages
  - post_to_x(): post a tweet via tweepy (accepts credentials as params)
  - notify_directories(): ping podcast directories after feed update
  - generate_episode_thumbnail(): simple PIL-based thumbnail overlay
"""

import datetime
import fcntl
import json
import os
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
    base_url: str = "https://nerranetwork.com",
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
    channel_subcategory: str = "",
    guid_prefix: str = "podcast",
    format_duration_func=None,
    chapters_url: Optional[str] = None,
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

    # WebSub / PubSubHubbub: declare hub and self links so directories can
    # subscribe to push notifications when the feed is updated.
    rss_self_url = f"{base_url}/{rss_path.name}"
    fg.link(href="https://pubsubhubbub.appspot.com/", rel="hub")
    fg.link(href=rss_self_url, rel="self")
    fg.copyright(f"Copyright {datetime.date.today().year}")
    fg.podcast.itunes_author(channel_author)
    fg.podcast.itunes_summary(channel_description)
    fg.podcast.itunes_owner(name=channel_author, email=channel_email)
    if channel_image:
        fg.podcast.itunes_image(channel_image)
    if channel_subcategory:
        fg.podcast.itunes_category({"cat": channel_category, "sub": channel_subcategory})
    else:
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

    # Atomic write: write to temp file, then rename to prevent corruption
    # from concurrent CI matrix jobs or pipeline crashes mid-write.
    import tempfile
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".rss", dir=str(rss_path.parent),
    )
    os.close(tmp_fd)
    try:
        fg.rss_file(tmp_path, pretty=True)

        # Post-process: add Podcasting 2.0 <podcast:chapters> to the new episode
        if chapters_url:
            _inject_chapters_tag(Path(tmp_path), new_guid, chapters_url)

        # Add <podcast:locked> to prevent unauthorized feed imports
        _inject_podcast_locked_tag(
            Path(tmp_path),
            channel_email or "patrick@planetterrian.com",
        )

        os.replace(tmp_path, str(rss_path))
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    logger.info("RSS feed updated: %s", rss_path)
    return rss_path


def _inject_podcast_locked_tag(rss_path: Path, owner_email: str) -> None:
    """Add ``<podcast:locked>`` to the RSS channel element.

    Prevents unauthorized feed imports on supporting platforms.
    Idempotent — skips if the tag already exists.
    """
    PODCAST_NS = "https://podcastindex.org/namespace/1.0"

    try:
        ET.register_namespace("podcast", PODCAST_NS)
        ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
        ET.register_namespace("atom", "http://www.w3.org/2005/Atom")

        tree = ET.parse(str(rss_path))
        root = tree.getroot()

        for attr in list(root.attrib):
            if attr == "xmlns:podcast" or (
                attr.startswith("xmlns:") and root.attrib[attr] == PODCAST_NS
            ):
                del root.attrib[attr]

        channel = root.find("channel")
        if channel is None:
            return

        # Skip if already present
        existing = channel.find(f"{{{PODCAST_NS}}}locked")
        if existing is not None:
            return

        locked_el = ET.SubElement(channel, f"{{{PODCAST_NS}}}locked")
        locked_el.set("owner", owner_email)
        locked_el.text = "yes"

        tree.write(str(rss_path), xml_declaration=True, encoding="UTF-8")
        logger.info("Injected <podcast:locked> tag")

    except Exception as exc:
        logger.warning("Failed to inject <podcast:locked> tag: %s", exc)


def _inject_chapters_tag(rss_path: Path, guid: str, chapters_url: str) -> None:
    """Add a Podcasting 2.0 ``<podcast:chapters>`` tag to an RSS episode.

    Feedgen doesn't support the ``podcast`` namespace natively, so we
    post-process the XML to insert the tag into the matching ``<item>``.
    """
    PODCAST_NS = "https://podcastindex.org/namespace/1.0"

    try:
        # Register namespace prefixes before parsing so serialization uses
        # clean prefixes and declares xmlns automatically.
        ET.register_namespace("podcast", PODCAST_NS)
        ET.register_namespace("itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
        ET.register_namespace("atom", "http://www.w3.org/2005/Atom")

        tree = ET.parse(str(rss_path))
        root = tree.getroot()

        # Remove any manually-set xmlns:podcast attribute to avoid
        # duplicating the declaration that ET.register_namespace handles.
        for attr in list(root.attrib):
            if attr == "xmlns:podcast" or (
                attr.startswith("xmlns:") and root.attrib[attr] == PODCAST_NS
            ):
                del root.attrib[attr]

        # Find the item with the matching GUID
        channel = root.find("channel")
        if channel is None:
            return

        for item in channel.findall("item"):
            guid_el = item.find("guid")
            if guid_el is not None and guid_el.text and guid_el.text.strip() == guid:
                chapters_el = ET.SubElement(item, f"{{{PODCAST_NS}}}chapters")
                chapters_el.set("url", chapters_url)
                chapters_el.set("type", "application/json+chapters")
                break

        tree.write(str(rss_path), xml_declaration=True, encoding="UTF-8")
        logger.info("Injected <podcast:chapters> for %s", guid)

    except Exception as exc:
        logger.warning("Failed to inject <podcast:chapters> tag: %s", exc)


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

        if summaries_json_path.exists():
            # Atomic read-modify-write under a single exclusive lock to
            # prevent data loss if another process writes concurrently.
            with open(summaries_json_path, "r+", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    data = json.load(f)
                    data["summaries"].insert(0, entry)
                    data["summaries"] = data["summaries"][:max_summaries]
                    f.seek(0)
                    f.truncate()
                    json.dump(data, f, indent=2, ensure_ascii=False)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        else:
            data = {"podcast": podcast_name, "summaries": [entry]}
            data["summaries"] = data["summaries"][:max_summaries]
            with open(summaries_json_path, "w", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

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
# Directory notifications (WebSub / PubSubHubbub, Podcast Index, Ping-O-Matic)
# ---------------------------------------------------------------------------

def notify_directories(rss_url: str, show_name: str = "Podcast") -> dict:
    """Notify podcast directories that a feed has been updated.

    Called after a new episode is published and the RSS feed is regenerated.
    All pings are best-effort — failures are logged but never raise.

    Returns a dict of ``{service_name: success_bool}`` results.
    """
    import requests

    results = {}

    # 1. PubSubHubbub / WebSub — used by Google Podcasts, Podcast Index, etc.
    try:
        resp = requests.post(
            "https://pubsubhubbub.appspot.com/",
            data={"hub.mode": "publish", "hub.url": rss_url},
            timeout=15,
        )
        results["pubsubhubbub"] = resp.status_code == 204
        if resp.status_code == 204:
            logger.info("[%s] PubSubHubbub notified successfully", show_name)
        else:
            logger.warning("[%s] PubSubHubbub returned %s", show_name, resp.status_code)
    except Exception as e:
        logger.warning("[%s] PubSubHubbub notification failed: %s", show_name, e)
        results["pubsubhubbub"] = False

    # 2. Podcast Index API ping — feeds Pocket Casts, Fountain, Podfriend, etc.
    try:
        resp = requests.get(
            "https://api.podcastindex.org/api/1.0/hub/pubnotify",
            params={"url": rss_url},
            timeout=15,
        )
        results["podcast_index"] = resp.status_code == 200
        if resp.status_code == 200:
            logger.info("[%s] Podcast Index notified successfully", show_name)
        else:
            logger.warning("[%s] Podcast Index returned %s", show_name, resp.status_code)
    except Exception as e:
        logger.warning("[%s] Podcast Index notification failed: %s", show_name, e)
        results["podcast_index"] = False

    # 3. Ping-O-Matic — notifies multiple blog/podcast search engines at once
    try:
        import xmlrpc.client
        server = xmlrpc.client.ServerProxy("http://rpc.pingomatic.com/")
        resp = server.weblogUpdates.ping(show_name, rss_url)
        results["pingomatic"] = resp.get("flerror", True) is False
        if results["pingomatic"]:
            logger.info("[%s] Ping-O-Matic notified successfully", show_name)
        else:
            logger.warning("[%s] Ping-O-Matic reported error: %s", show_name, resp)
    except Exception as e:
        logger.warning("[%s] Ping-O-Matic notification failed: %s", show_name, e)
        results["pingomatic"] = False

    successes = sum(1 for v in results.values() if v)
    logger.info("[%s] Directory notifications: %s/%s succeeded", show_name, successes, len(results))

    return results


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
    needs (FF, PT). For TST's emoji-rich version, use ``format_tst_digest_for_x``.
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


def format_tst_digest_for_x(digest: str, *, max_chars: int = 25000) -> str:
    """Format a Tesla Shorts Time digest for X with emojis and visual polish.

    Uses a structured pipeline approach instead of ad-hoc regex:
      1. Clean markdown & extract URLs
      2. Apply section header emojis via lookup table
      3. Ensure podcast link
      4. Number news items with emoji bullets
      5. Insert section separators
      6. Strip leaked instruction text
      7. Final cleanup & truncation
    """
    PODCAST_URL = "https://podcasts.apple.com/us/podcast/tesla-shorts-time/id1855142939"
    SEPARATOR = "\n\n\u2501" * 20 + "\n\n"  # ━━━━━━━━━━━━━━━━━━━━
    EMOJI_NUMBERS = [
        "1\ufe0f\u20e3", "2\ufe0f\u20e3", "3\ufe0f\u20e3", "4\ufe0f\u20e3",
        "5\ufe0f\u20e3", "6\ufe0f\u20e3", "7\ufe0f\u20e3", "8\ufe0f\u20e3",
        "9\ufe0f\u20e3", "\U0001f51f",
    ]

    # Section header mapping: (markdown pattern, emoji replacement)
    SECTION_HEADERS = [
        (r"^#{1,3}\s*Tesla Shorts Time\s*$",  "\U0001f697\u26a1 **Tesla Shorts Time**"),
        (r"^#{1,3}\s*Top 10 News Items",       "\U0001f4f0 **Top 10 News Items**"),
        (r"^#{1,3}\s*Tesla X Takeover:?",       "\U0001f399\ufe0f **Tesla X Takeover:**"),
        (r"^#{1,3}\s*Short Spot",               "\U0001f4c9 **Short Spot**"),
        (r"^#{1,3}\s*Short Squeeze",            "\U0001f4c8 **Short Squeeze**"),
        (r"^#{1,3}\s*Daily Challenge",          "\U0001f4aa **Daily Challenge**"),
        (r"^#{1,3}\s*First Principles",         "\U0001f9e0 **First Principles**"),
        (r"^#{1,3}\s*Market Movers",            "\U0001f4ca **Market Movers**"),
    ]

    # Metadata line emoji mapping
    METADATA_EMOJIS = [
        (r"\*\*Date:\*\*",                 "\U0001f4c5 **Date:**"),
        (r"\*\*REAL-TIME TSLA price:\*\*", "\U0001f4b0 **REAL-TIME TSLA price:**"),
        (r"\*\*Inspiration Quote:\*\*",    "\u2728 **Inspiration Quote:**"),
    ]

    # Leaked instruction patterns to strip
    INSTRUCTION_PATTERNS = [
        r"\U0001f3af\s*TODAY'S FOCUS:.*",
        r"\*\*TOP 5 TESLA X POSTS FROM.*?:\*\*",
        r"Using your knowledge.*",
        r"For each post:.*",
        r"\(use actual post URLs.*?\)",
        r"\(if you can find them.*?\)",
        r"\(format as shown\)",
        r"\*\*OVERALL WEEKLY SENTIMENT.*?:\*\*",
        r"Provide a.*?summary.*",
        r"Is the sentiment.*",
        r"What are the main topics.*",
        r"What's their perspective.*",
        r"\[Repeat for.*?\]",
        r"\[ACTUAL_POST_ID\]",
        r"\[POST_ID\]",
        r"\U0001f6a8\s*CRITICAL:.*",
        r"CRITICAL:.*?COMPLETELY (?:DIFFERENT|NEW).*",
        r"Use (?:a )?DIFFERENT.*",
        r"(?:Avoid|Do NOT|Never) repeat.*",
    ]

    # --- Step 1: Apply section header emojis ---
    text = digest
    for pattern, replacement in SECTION_HEADERS:
        text = re.sub(pattern, replacement, text, flags=re.MULTILINE)

    # --- Step 2: Apply metadata emojis ---
    for pattern, replacement in METADATA_EMOJIS:
        text = re.sub(pattern, replacement, text)

    # --- Step 3: Ensure podcast link ---
    podcast_link_line = f"\U0001f399\ufe0f **Tesla Shorts Time Daily Podcast Link:** {PODCAST_URL}"

    # Remove any malformed/incomplete podcast link lines
    lines = text.split("\n")
    lines = [
        line for line in lines
        if not (
            ("podcast" in line.lower() or "\U0001f399\ufe0f" in line)
            and PODCAST_URL not in line
            and "Tesla X Takeover" not in line  # Don't strip X Takeover section
        )
    ]
    text = "\n".join(lines)

    # Insert podcast link after price line (or date line, or header)
    if PODCAST_URL not in text:
        lines = text.split("\n")
        insert_pos = None
        for i, line in enumerate(lines):
            if "TSLA price" in line or "\U0001f4b0" in line:
                insert_pos = i + 1
                break
            if "Date:" in line and insert_pos is None:
                insert_pos = i + 1
        if insert_pos is None:
            insert_pos = min(2, len(lines))
        lines[insert_pos:insert_pos] = ["", podcast_link_line, ""]
        text = "\n".join(lines)

    # --- Step 4: Number news items with emoji bullets ---
    news_header_match = re.search(
        r"(\U0001f4f0 \*\*Top 10 News Items\*\*.*?)(?=\U0001f4c9|\U0001f399\ufe0f \*\*Tesla X|\u2501\u2501|\Z)",
        text, re.DOTALL,
    )
    if news_header_match:
        section = news_header_match.group(1)
        for i in range(1, 11):
            section = re.sub(
                rf"^(\s*){i}\.\s+",
                lambda m, idx=i: m.group(1) + EMOJI_NUMBERS[idx - 1] + " ",
                section, flags=re.MULTILINE,
            )
        text = text[:news_header_match.start()] + section + text[news_header_match.end():]

    # --- Step 5: Insert section separators ---
    # Add separator before each major section emoji
    section_markers = [
        "\U0001f4f0 **Top 10 News Items**",
        "\U0001f399\ufe0f **Tesla X Takeover:**",
        "\U0001f4c9 **Short Spot**",
        "\U0001f4c8 **Short Squeeze**",
        "\U0001f4aa **Daily Challenge**",
        "\u2728 **Inspiration Quote:**",
        "\U0001f9e0 **First Principles**",
        "\U0001f4ca **Market Movers**",
    ]
    for marker in section_markers:
        if marker in text:
            # Replace any whitespace before the marker with separator
            text = re.sub(
                r"\n\s*\n\s*" + re.escape(marker),
                "\n\n" + "\u2501" * 20 + "\n\n" + marker,
                text,
            )

    # --- Step 6: Strip leaked instruction text ---
    for pattern in INSTRUCTION_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE | re.MULTILINE)

    # Strip placeholder/dead X URLs
    text = re.sub(r"Post:\s*https?://x\.com/[^\s]+/status/\[[^\]]+\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Post:\s*https?://x\.com/[^\s]+/status/[^\d/][^\s]*", "", text, flags=re.IGNORECASE)

    # --- Step 7: Extract URLs from markdown links ---
    text = re.sub(r"\[([^\]]+)\]\((https?://[^\)]+)\)", r"\2", text)
    text = re.sub(r"\[(https?://[^\]]+)\]", r"\1", text)
    text = re.sub(r"(https?://x\.com/[^\s\)\]]+)[\)\]]+", r"\1", text)

    # Remove code blocks
    text = re.sub(r"```[^`]*```", "", text, flags=re.DOTALL)

    # --- Step 8: Final cleanup ---
    # Normalize whitespace per line
    lines = text.split("\n")
    lines = ["" if line.strip() == "" else re.sub(r"[ \t]{2,}", " ", line) for line in lines]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    # Ensure a nice ending — check the last content line (ignoring
    # the podcast link line which is always a URL)
    content_lines = [
        line for line in text.split("\n")
        if line.strip() and PODCAST_URL not in line
    ]
    last_content_char = content_lines[-1].strip()[-1] if content_lines else ""
    if last_content_char not in "!?.":
        last_text = " ".join(content_lines[-3:]).strip()
        if not any(w in last_text.lower() for w in ["feedback", "dm", "accelerating", "electric", "mission"]):
            text += "\n\n\u26a1 Keep accelerating!"

    # Enforce character limit
    if len(text) > max_chars:
        logger.warning("Formatted digest is %d characters, truncating to %d", len(text), max_chars)
        truncate_at = text[:max_chars - 100].rfind("\n\n")
        if truncate_at > max_chars * 0.8:
            text = text[:truncate_at] + "\n\n... (content truncated for length)"
        else:
            text = text[:max_chars - 50] + "\n\n... (truncated for length)"

    return text


# ---------------------------------------------------------------------------
# Scan existing episode MP3 files
# ---------------------------------------------------------------------------

def scan_existing_episodes_from_files(
    digests_dir: Path,
    base_url: str,
    *,
    mp3_glob: str = "*_Ep*_*.mp3",
    filename_pattern: str = r".*_Ep(\d+)_(\d{8})",
    audio_subdir: str = "digests",
    get_audio_duration_func=None,
) -> list:
    """Scan for existing episode MP3 files and return episode data.

    Parameters
    ----------
    digests_dir:
        Directory containing the MP3 files.
    base_url:
        GitHub raw content base URL for constructing download URLs.
    mp3_glob:
        Glob pattern to find MP3 files in *digests_dir*.
    filename_pattern:
        Regex to extract ``(episode_num, date_str)`` groups from filenames.
        The date group is expected in ``%Y%m%d`` format.
    audio_subdir:
        Path segment appended to *base_url* for the episode URL.
    get_audio_duration_func:
        Optional callable ``(Path) -> float`` for reading audio duration.
        Defaults to ``engine.audio.get_audio_duration``.

    Returns
    -------
    list[dict]
        Sorted by episode number (ascending).  Each dict has keys:
        ``episode_num``, ``date``, ``filename``, ``path``, ``size``,
        ``duration``, ``url``.
    """
    if get_audio_duration_func is None:
        from engine.audio import get_audio_duration as _gad
        get_audio_duration_func = _gad

    import datetime as _dt

    episodes: list = []
    compiled_pattern = re.compile(filename_pattern)

    for mp3_file in digests_dir.glob(mp3_glob):
        match = compiled_pattern.match(mp3_file.name)
        if match:
            try:
                ep_num = int(match.group(1))
                date_str = match.group(2)
                episode_date = _dt.datetime.strptime(date_str, "%Y%m%d").date()

                file_size = mp3_file.stat().st_size if mp3_file.exists() else 0
                duration = get_audio_duration_func(mp3_file)

                episodes.append({
                    "episode_num": ep_num,
                    "date": episode_date,
                    "filename": mp3_file.name,
                    "path": mp3_file,
                    "size": file_size,
                    "duration": duration,
                    "url": f"{base_url}/{audio_subdir}/{mp3_file.name}",
                })
            except (ValueError, Exception) as exc:
                logger.warning("Could not parse episode from file %s: %s", mp3_file.name, exc)

    return sorted(episodes, key=lambda x: x["episode_num"])
