"""
Tests for engine/publisher.py — RSS feed management, episode numbering,
GitHub Pages JSON, X posting, and analytics prefix.

Covers:
  - apply_op3_prefix(): URL rewriting for analytics
  - update_rss_feed(): XML generation, episode dedup, channel metadata
  - get_next_episode_number(): RSS + filesystem scanning
  - save_summary_to_github_pages(): JSON structure, max entries, ordering
  - post_to_x(): tweepy integration (mocked)
"""

import datetime
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from engine.publisher import (
    apply_op3_prefix,
    get_next_episode_number,
    post_to_x,
    save_summary_to_github_pages,
    update_rss_feed,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_dur(seconds):
    """Simple duration formatter for tests (avoids engine.audio import)."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _make_mp3(tmp_path, name="test.mp3", size=1024):
    """Helper to create a fake MP3 file."""
    mp3 = tmp_path / name
    mp3.write_bytes(b"\x00" * size)
    return mp3


def _make_rss(tmp_path, episode_num=1, title="Ep 1", desc="Desc",
              date=None, mp3_name="ep001.mp3", duration=300.0, **kwargs):
    """Create an RSS feed via update_rss_feed and return the path."""
    rss_path = tmp_path / "podcast.rss"
    mp3 = _make_mp3(tmp_path)
    date = date or datetime.date(2026, 1, 1)
    return update_rss_feed(
        rss_path, episode_num, title, desc, date,
        mp3_name, duration, mp3,
        format_duration_func=_fmt_dur,
        **kwargs,
    )


# ===================================================================
# TEST: apply_op3_prefix
# ===================================================================

class TestApplyOp3Prefix:

    def test_https_url_strips_scheme(self):
        result = apply_op3_prefix("https://cdn.example.com/ep1.mp3")
        assert result == "https://op3.dev/e/cdn.example.com/ep1.mp3"

    def test_http_url_keeps_full_url(self):
        result = apply_op3_prefix("http://cdn.example.com/ep1.mp3")
        assert result == "https://op3.dev/e/http://cdn.example.com/ep1.mp3"

    def test_no_scheme_appended_directly(self):
        result = apply_op3_prefix("cdn.example.com/ep1.mp3")
        assert result == "https://op3.dev/e/cdn.example.com/ep1.mp3"

    def test_custom_prefix_url(self):
        result = apply_op3_prefix(
            "https://cdn.example.com/ep1.mp3",
            prefix_url="https://custom.analytics.com/e/"
        )
        assert result == "https://custom.analytics.com/e/cdn.example.com/ep1.mp3"

    def test_github_raw_url(self):
        url = "https://raw.githubusercontent.com/user/repo/main/digests/ep001.mp3"
        result = apply_op3_prefix(url)
        assert result.startswith("https://op3.dev/e/")
        assert "raw.githubusercontent.com" in result
        assert "ep001.mp3" in result

    def test_empty_url(self):
        result = apply_op3_prefix("")
        assert result == "https://op3.dev/e/"


# ===================================================================
# TEST: get_next_episode_number
# ===================================================================

class TestGetNextEpisodeNumber:

    def test_no_rss_no_files_returns_1(self, tmp_path):
        rss_path = tmp_path / "podcast.rss"
        result = get_next_episode_number(rss_path, tmp_path)
        assert result == 1

    def test_rss_with_episodes(self, tmp_path):
        rss_path = tmp_path / "podcast.rss"
        rss_path.write_text("""<?xml version='1.0' encoding='UTF-8'?>
        <rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" version="2.0">
          <channel>
            <item><itunes:episode>5</itunes:episode></item>
            <item><itunes:episode>10</itunes:episode></item>
          </channel>
        </rss>""")
        result = get_next_episode_number(rss_path, tmp_path)
        assert result == 11

    def test_mp3_files_in_directory(self, tmp_path):
        rss_path = tmp_path / "podcast.rss"
        (tmp_path / "Tesla_Ep005_20260101.mp3").touch()
        (tmp_path / "Tesla_Ep012_20260102.mp3").touch()
        result = get_next_episode_number(rss_path, tmp_path)
        assert result == 13

    def test_rss_and_files_uses_max(self, tmp_path):
        rss_path = tmp_path / "podcast.rss"
        rss_path.write_text("""<?xml version='1.0' encoding='UTF-8'?>
        <rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" version="2.0">
          <channel>
            <item><itunes:episode>20</itunes:episode></item>
          </channel>
        </rss>""")
        (tmp_path / "Tesla_Ep015_20260101.mp3").touch()
        result = get_next_episode_number(rss_path, tmp_path)
        assert result == 21

    def test_custom_glob_pattern(self, tmp_path):
        rss_path = tmp_path / "podcast.rss"
        (tmp_path / "Omni_View_Ep007_20260101.mp3").touch()
        result = get_next_episode_number(
            rss_path, tmp_path, mp3_glob_pattern="Omni_View_Ep*.mp3"
        )
        assert result == 8

    def test_no_matching_files(self, tmp_path):
        rss_path = tmp_path / "podcast.rss"
        (tmp_path / "unrelated_file.mp3").touch()
        result = get_next_episode_number(rss_path, tmp_path)
        assert result == 1

    def test_malformed_rss_returns_1(self, tmp_path):
        rss_path = tmp_path / "podcast.rss"
        rss_path.write_text("this is not XML")
        result = get_next_episode_number(rss_path, tmp_path)
        assert result == 1

    def test_episode_numbers_from_filename_regex(self, tmp_path):
        rss_path = tmp_path / "podcast.rss"
        (tmp_path / "Show_Ep100_20260101.mp3").touch()
        (tmp_path / "Show_Ep099_20260101.mp3").touch()
        result = get_next_episode_number(rss_path, tmp_path)
        assert result == 101


# ===================================================================
# TEST: save_summary_to_github_pages
# ===================================================================

class TestSaveSummaryToGithubPages:

    def test_creates_new_file(self, tmp_path):
        json_path = tmp_path / "summaries.json"
        result = save_summary_to_github_pages(
            "Today's summary content", json_path, "Test Podcast",
            episode_num=1, episode_title="Episode 1",
        )
        assert result == json_path
        assert json_path.exists()

    def test_json_structure(self, tmp_path):
        json_path = tmp_path / "summaries.json"
        save_summary_to_github_pages(
            "Summary text", json_path, "My Podcast",
            episode_num=5, episode_title="Episode 5",
            audio_url="https://example.com/ep5.mp3",
            rss_url="https://example.com/feed.rss",
        )
        data = json.loads(json_path.read_text())
        assert data["podcast"] == "My Podcast"
        assert len(data["summaries"]) == 1
        entry = data["summaries"][0]
        assert entry["content"] == "Summary text"
        assert entry["episode_num"] == 5
        assert entry["episode_title"] == "Episode 5"
        assert entry["audio_url"] == "https://example.com/ep5.mp3"
        assert entry["rss_url"] == "https://example.com/feed.rss"
        assert "date" in entry
        assert "datetime" in entry

    def test_appends_to_existing(self, tmp_path):
        json_path = tmp_path / "summaries.json"
        save_summary_to_github_pages("First", json_path, "Test", episode_num=1)
        save_summary_to_github_pages("Second", json_path, "Test", episode_num=2)
        data = json.loads(json_path.read_text())
        assert len(data["summaries"]) == 2

    def test_newest_first(self, tmp_path):
        json_path = tmp_path / "summaries.json"
        save_summary_to_github_pages("Old", json_path, "Test", episode_num=1)
        save_summary_to_github_pages("New", json_path, "Test", episode_num=2)
        data = json.loads(json_path.read_text())
        assert data["summaries"][0]["content"] == "New"
        assert data["summaries"][1]["content"] == "Old"

    def test_max_summaries_limit(self, tmp_path):
        json_path = tmp_path / "summaries.json"
        for i in range(35):
            save_summary_to_github_pages(
                f"Summary {i}", json_path, "Test",
                episode_num=i, max_summaries=30,
            )
        data = json.loads(json_path.read_text())
        assert len(data["summaries"]) == 30

    def test_max_summaries_keeps_newest(self, tmp_path):
        json_path = tmp_path / "summaries.json"
        for i in range(35):
            save_summary_to_github_pages(
                f"Summary {i}", json_path, "Test",
                episode_num=i, max_summaries=30,
            )
        data = json.loads(json_path.read_text())
        assert data["summaries"][0]["content"] == "Summary 34"

    def test_returns_none_on_error(self, tmp_path):
        json_path = tmp_path / "nonexistent" / "dir" / "summaries.json"
        result = save_summary_to_github_pages(
            "Content", json_path, "Test", episode_num=1
        )
        assert result is None

    def test_optional_fields_default_to_none(self, tmp_path):
        json_path = tmp_path / "summaries.json"
        save_summary_to_github_pages("Text", json_path, "Test")
        data = json.loads(json_path.read_text())
        entry = data["summaries"][0]
        assert entry["episode_num"] is None
        assert entry["episode_title"] is None
        assert entry["audio_url"] is None
        assert entry["rss_url"] is None

    def test_preserves_podcast_name_on_append(self, tmp_path):
        json_path = tmp_path / "summaries.json"
        json_path.write_text(json.dumps({
            "podcast": "Original Name",
            "summaries": [{"content": "old"}]
        }))
        save_summary_to_github_pages("New", json_path, "Ignored", episode_num=2)
        data = json.loads(json_path.read_text())
        assert data["podcast"] == "Original Name"


# ===================================================================
# TEST: update_rss_feed
# ===================================================================

try:
    import feedgen  # noqa: F401
    _has_feedgen = True
except ImportError:
    _has_feedgen = False


@pytest.mark.skipif(not _has_feedgen, reason="feedgen not installed")
class TestUpdateRssFeed:

    def test_creates_new_rss_file(self, tmp_path):
        result = _make_rss(tmp_path, channel_title="Test Podcast")
        assert result == tmp_path / "podcast.rss"
        assert result.exists()

    def test_rss_is_valid_xml(self, tmp_path):
        _make_rss(tmp_path)
        tree = ET.parse(str(tmp_path / "podcast.rss"))
        root = tree.getroot()
        assert root.tag == "rss"
        assert root.find("channel") is not None

    def test_channel_metadata(self, tmp_path):
        _make_rss(tmp_path, channel_title="My Podcast",
                  channel_description="Great pod", channel_language="en-us")
        tree = ET.parse(str(tmp_path / "podcast.rss"))
        channel = tree.getroot().find("channel")
        assert channel.find("title").text == "My Podcast"
        assert channel.find("description").text == "Great pod"
        assert channel.find("language").text == "en-us"

    def test_episode_enclosure_url_default(self, tmp_path):
        _make_rss(tmp_path, mp3_name="ep001.mp3")
        tree = ET.parse(str(tmp_path / "podcast.rss"))
        items = tree.getroot().find("channel").findall("item")
        enc = items[0].find("enclosure")
        assert enc is not None
        assert "digests/ep001.mp3" in enc.get("url")
        assert enc.get("type") == "audio/mpeg"

    def test_custom_audio_url(self, tmp_path):
        _make_rss(tmp_path, audio_url="https://r2.example.com/ep001.mp3")
        tree = ET.parse(str(tmp_path / "podcast.rss"))
        items = tree.getroot().find("channel").findall("item")
        enc = items[0].find("enclosure")
        assert enc.get("url") == "https://r2.example.com/ep001.mp3"

    def test_episode_has_itunes_tags(self, tmp_path):
        _make_rss(tmp_path)
        tree = ET.parse(str(tmp_path / "podcast.rss"))
        item = tree.getroot().find("channel").findall("item")[0]
        ns = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
        assert item.find(f"{ns}episode").text == "1"
        assert item.find(f"{ns}season").text == "1"
        assert item.find(f"{ns}episodeType").text == "full"
        assert item.find(f"{ns}explicit").text == "no"

    def test_preserves_existing_episodes(self, tmp_path):
        rss_path = tmp_path / "podcast.rss"
        mp3 = _make_mp3(tmp_path)
        update_rss_feed(
            rss_path, 1, "Episode 1", "First",
            datetime.date(2026, 1, 1), "ep001.mp3", 300.0, mp3,
            channel_title="Test", format_duration_func=_fmt_dur,
        )
        update_rss_feed(
            rss_path, 2, "Episode 2", "Second",
            datetime.date(2026, 1, 2), "ep002.mp3", 350.0, mp3,
            channel_title="Test", format_duration_func=_fmt_dur,
        )
        tree = ET.parse(str(rss_path))
        items = tree.getroot().find("channel").findall("item")
        assert len(items) == 2

    def test_deduplicates_by_episode_number(self, tmp_path):
        rss_path = tmp_path / "podcast.rss"
        mp3 = _make_mp3(tmp_path)
        update_rss_feed(
            rss_path, 1, "Episode 1 v1", "First version",
            datetime.date(2026, 1, 1), "ep001.mp3", 300.0, mp3,
            channel_title="Test", format_duration_func=_fmt_dur,
        )
        update_rss_feed(
            rss_path, 1, "Episode 1 v2", "Second version",
            datetime.date(2026, 1, 1), "ep001_v2.mp3", 310.0, mp3,
            channel_title="Test", format_duration_func=_fmt_dur,
        )
        tree = ET.parse(str(rss_path))
        items = tree.getroot().find("channel").findall("item")
        assert len(items) == 1

    def test_mp3_file_size_in_enclosure(self, tmp_path):
        rss_path = tmp_path / "podcast.rss"
        mp3 = _make_mp3(tmp_path, size=5000)
        update_rss_feed(
            rss_path, 1, "Ep", "Desc",
            datetime.date(2026, 1, 1), "ep.mp3", 300.0, mp3,
            format_duration_func=_fmt_dur,
        )
        tree = ET.parse(str(rss_path))
        enc = tree.getroot().find("channel").findall("item")[0].find("enclosure")
        assert enc.get("length") == "5000"

    def test_nonexistent_mp3_zero_size(self, tmp_path):
        rss_path = tmp_path / "podcast.rss"
        fake_mp3 = tmp_path / "nonexistent.mp3"
        update_rss_feed(
            rss_path, 1, "Ep", "Desc",
            datetime.date(2026, 1, 1), "ep.mp3", 300.0, fake_mp3,
            format_duration_func=_fmt_dur,
        )
        tree = ET.parse(str(rss_path))
        enc = tree.getroot().find("channel").findall("item")[0].find("enclosure")
        assert enc.get("length") == "0"

    def test_duration_formatted(self, tmp_path):
        _make_rss(tmp_path, duration=3661.0)
        tree = ET.parse(str(tmp_path / "podcast.rss"))
        item = tree.getroot().find("channel").findall("item")[0]
        ns = "{http://www.itunes.com/dtds/podcast-1.0.dtd}"
        assert item.find(f"{ns}duration").text == "01:01:01"


# ===================================================================
# TEST: post_to_x
# ===================================================================

class TestPostToX:

    def test_successful_post(self):
        mock_tweepy = MagicMock()
        mock_client = MagicMock()
        mock_tweepy.Client.return_value = mock_client
        mock_client.create_tweet.return_value = MagicMock(data={"id": "12345"})

        with patch.dict(sys.modules, {"tweepy": mock_tweepy}):
            result = post_to_x(
                "Hello world",
                consumer_key="ck", consumer_secret="cs",
                access_token="at", access_token_secret="ats",
            )
        assert result == "https://x.com/i/status/12345"

    def test_returns_none_on_failure(self):
        mock_tweepy = MagicMock()
        mock_client = MagicMock()
        mock_tweepy.Client.return_value = mock_client
        mock_client.create_tweet.side_effect = Exception("API error")

        with patch.dict(sys.modules, {"tweepy": mock_tweepy}):
            result = post_to_x(
                "Hello",
                consumer_key="ck", consumer_secret="cs",
                access_token="at", access_token_secret="ats",
            )
        assert result is None

    def test_passes_credentials(self):
        mock_tweepy = MagicMock()
        mock_client = MagicMock()
        mock_tweepy.Client.return_value = mock_client
        mock_client.create_tweet.return_value = MagicMock(data={"id": "1"})

        with patch.dict(sys.modules, {"tweepy": mock_tweepy}):
            post_to_x(
                "Text",
                consumer_key="my_ck", consumer_secret="my_cs",
                access_token="my_at", access_token_secret="my_ats",
            )
        mock_tweepy.Client.assert_called_once_with(
            consumer_key="my_ck", consumer_secret="my_cs",
            access_token="my_at", access_token_secret="my_ats",
        )
