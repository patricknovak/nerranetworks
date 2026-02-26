"""
RSS feed regression tests.

Parses each existing RSS file and captures:
  - Episode counts (must match known values)
  - Channel metadata structure
  - Item field completeness
  - Enclosure URL patterns

This becomes our baseline: after refactoring RSS generation into a shared
engine, these tests verify the output is structurally equivalent.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Constants (must match conftest.py — duplicated here because conftest is
# auto-loaded by pytest but not directly importable as a module).
# ---------------------------------------------------------------------------

RSS_FEEDS = {
    "tesla": PROJECT_ROOT / "podcast.rss",
    "omni": PROJECT_ROOT / "omni_view_podcast.rss",
    "planetterrian": PROJECT_ROOT / "planetterrian_podcast.rss",
    "frontiers": PROJECT_ROOT / "fascinating_frontiers_podcast.rss",
}

EXPECTED_EPISODE_COUNTS = {
    "tesla": 46,
    "omni": 0,
    "frontiers": 20,
    "planetterrian": 11,
}

# ---------------------------------------------------------------------------
# Namespace helpers (RSS feeds use different namespace prefixes)
# ---------------------------------------------------------------------------

ITUNES_NAMESPACES = [
    "http://www.itunes.com/dtds/podcast-1.0.dtd",
]


def _find_itunes(element, tag):
    """Find an iTunes-namespaced child element, trying all known prefixes."""
    for ns in ITUNES_NAMESPACES:
        found = element.find(f"{{{ns}}}{tag}")
        if found is not None:
            return found
    return None


def _findall_itunes(element, tag):
    """Find all iTunes-namespaced child elements."""
    results = []
    for ns in ITUNES_NAMESPACES:
        results.extend(element.findall(f"{{{ns}}}{tag}"))
    return results


def _parse_rss(rss_path: Path):
    """Parse an RSS file and return (channel_element, list_of_item_elements)."""
    tree = ET.parse(str(rss_path))
    root = tree.getroot()
    channel = root.find("channel")
    items = channel.findall("item")
    return channel, items


# ===================================================================
# TEST: Episode counts match expected values
# ===================================================================

class TestEpisodeCounts:

    @pytest.mark.parametrize("show,expected_count", list(EXPECTED_EPISODE_COUNTS.items()))
    def test_episode_count(self, show, expected_count):
        rss_path = RSS_FEEDS[show]
        assert rss_path.exists(), f"RSS file not found: {rss_path}"
        _, items = _parse_rss(rss_path)
        actual = len(items)
        assert actual == expected_count, (
            f"{show}: expected {expected_count} episodes, found {actual}"
        )


# ===================================================================
# TEST: Channel metadata structure
# ===================================================================

EXPECTED_CHANNEL_METADATA = {
    "tesla": {
        "title": "Tesla Shorts Time Daily",
        "language": "en-us",
        "generator": "python-feedgen",
        "itunes_category": "Technology",
        "itunes_explicit": "no",
    },
    "omni": {
        "title": "Omni View - Balanced News Perspectives",
        "language": "en-us",
        "generator": "python-feedgen",
        "itunes_category": "News",
        "itunes_explicit": "no",
    },
    "planetterrian": {
        "title": "Planetterrian Daily",
        "language": "en-us",
        "generator": "python-feedgen",
        "itunes_category": "Science",
        "itunes_explicit": "no",
    },
    "frontiers": {
        "title": "Fascinating Frontiers",
        "language": "en-us",
        "generator": "python-feedgen",
        "itunes_category": "Science",
        "itunes_explicit": "no",
    },
}


class TestChannelMetadata:

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_channel_title(self, show):
        channel, _ = _parse_rss(RSS_FEEDS[show])
        title = channel.find("title").text
        assert title == EXPECTED_CHANNEL_METADATA[show]["title"]

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_channel_language(self, show):
        channel, _ = _parse_rss(RSS_FEEDS[show])
        lang = channel.find("language").text
        assert lang == EXPECTED_CHANNEL_METADATA[show]["language"]

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_channel_generator(self, show):
        channel, _ = _parse_rss(RSS_FEEDS[show])
        gen = channel.find("generator").text
        assert gen == EXPECTED_CHANNEL_METADATA[show]["generator"]

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_itunes_category(self, show):
        channel, _ = _parse_rss(RSS_FEEDS[show])
        cat = _find_itunes(channel, "category")
        assert cat is not None, f"{show}: missing itunes:category"
        assert cat.get("text") == EXPECTED_CHANNEL_METADATA[show]["itunes_category"]

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_itunes_explicit(self, show):
        channel, _ = _parse_rss(RSS_FEEDS[show])
        explicit = _find_itunes(channel, "explicit")
        assert explicit is not None, f"{show}: missing itunes:explicit"
        assert explicit.text == EXPECTED_CHANNEL_METADATA[show]["itunes_explicit"]

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_has_itunes_image(self, show):
        channel, _ = _parse_rss(RSS_FEEDS[show])
        img = _find_itunes(channel, "image")
        assert img is not None, f"{show}: missing itunes:image"
        href = img.get("href")
        assert href and href.startswith("https://"), f"{show}: bad image href: {href}"

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_has_itunes_owner(self, show):
        channel, _ = _parse_rss(RSS_FEEDS[show])
        owner = _find_itunes(channel, "owner")
        assert owner is not None, f"{show}: missing itunes:owner"
        name = _find_itunes(owner, "name")
        email = _find_itunes(owner, "email")
        assert name is not None and name.text, f"{show}: missing owner name"
        assert email is not None and email.text, f"{show}: missing owner email"

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_has_channel_link(self, show):
        channel, _ = _parse_rss(RSS_FEEDS[show])
        link = channel.find("link")
        assert link is not None and link.text, f"{show}: missing channel <link>"

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_has_description(self, show):
        channel, _ = _parse_rss(RSS_FEEDS[show])
        desc = channel.find("description")
        assert desc is not None and desc.text, f"{show}: missing channel <description>"


# ===================================================================
# TEST: Item / Episode structure
# ===================================================================

BASE_URL = "https://raw.githubusercontent.com/patricknovak/Tesla-shorts-time/main"

ENCLOSURE_URL_PATTERNS = {
    "tesla": f"{BASE_URL}/digests/",
    "omni": f"{BASE_URL}/digests/",
    "planetterrian": f"{BASE_URL}/digests/planetterrian/",
    "frontiers": f"{BASE_URL}/digests/fascinating_frontiers/",
}


class TestItemStructure:
    """Every episode item must have the required RSS and iTunes fields."""

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_all_items_have_title(self, show):
        _, items = _parse_rss(RSS_FEEDS[show])
        for i, item in enumerate(items):
            title = item.find("title")
            assert title is not None and title.text, (
                f"{show} item {i}: missing <title>"
            )

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_all_items_have_guid(self, show):
        _, items = _parse_rss(RSS_FEEDS[show])
        guids = set()
        for i, item in enumerate(items):
            guid = item.find("guid")
            assert guid is not None and guid.text, (
                f"{show} item {i}: missing <guid>"
            )
            # GUIDs must be unique
            assert guid.text not in guids, (
                f"{show} item {i}: duplicate GUID '{guid.text}'"
            )
            guids.add(guid.text)

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_all_items_have_enclosure(self, show):
        _, items = _parse_rss(RSS_FEEDS[show])
        expected_prefix = ENCLOSURE_URL_PATTERNS[show]
        for i, item in enumerate(items):
            enc = item.find("enclosure")
            assert enc is not None, f"{show} item {i}: missing <enclosure>"
            url = enc.get("url")
            assert url, f"{show} item {i}: empty enclosure url"
            assert url.startswith(expected_prefix), (
                f"{show} item {i}: enclosure URL doesn't match expected pattern.\n"
                f"  expected prefix: {expected_prefix}\n"
                f"  actual URL: {url}"
            )
            assert enc.get("type") == "audio/mpeg", (
                f"{show} item {i}: enclosure type should be audio/mpeg"
            )
            assert url.endswith(".mp3"), (
                f"{show} item {i}: enclosure URL should end with .mp3"
            )

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_all_items_have_pubdate(self, show):
        _, items = _parse_rss(RSS_FEEDS[show])
        for i, item in enumerate(items):
            pubdate = item.find("pubDate")
            assert pubdate is not None and pubdate.text, (
                f"{show} item {i}: missing <pubDate>"
            )

    # Current state: Tesla and Omni have duration on all episodes.
    # Planetterrian and Frontiers only have it on the most recent episode
    # (the scripts only set duration on newly generated episodes).
    EXPECTED_DURATION_COUNTS = {
        "tesla": 46,
        "omni": 0,
        "planetterrian": 0,
        "frontiers": 0,
    }

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_itunes_duration_counts(self, show):
        """Capture the current state of itunes:duration coverage per feed."""
        _, items = _parse_rss(RSS_FEEDS[show])
        with_duration = sum(
            1 for item in items
            if _find_itunes(item, "duration") is not None
            and _find_itunes(item, "duration").text
        )
        expected = self.EXPECTED_DURATION_COUNTS[show]
        assert with_duration == expected, (
            f"{show}: expected {expected} items with itunes:duration, found {with_duration}"
        )

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_all_items_have_itunes_episode(self, show):
        _, items = _parse_rss(RSS_FEEDS[show])
        for i, item in enumerate(items):
            ep = _find_itunes(item, "episode")
            assert ep is not None and ep.text, (
                f"{show} item {i}: missing itunes:episode"
            )

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_all_items_have_itunes_explicit(self, show):
        _, items = _parse_rss(RSS_FEEDS[show])
        for i, item in enumerate(items):
            expl = _find_itunes(item, "explicit")
            assert expl is not None and expl.text == "no", (
                f"{show} item {i}: missing or wrong itunes:explicit"
            )

    @pytest.mark.parametrize("show", list(RSS_FEEDS.keys()))
    def test_all_items_have_description(self, show):
        _, items = _parse_rss(RSS_FEEDS[show])
        for i, item in enumerate(items):
            desc = item.find("description")
            assert desc is not None and desc.text, (
                f"{show} item {i}: missing <description>"
            )


# ===================================================================
# TEST: Sample RSS fixture parsing
# ===================================================================

class TestSampleRSSFixture:
    """Tests against the minimal sample_rss_xml fixture from conftest."""

    def test_parse_fixture(self, sample_rss_xml):
        root = ET.fromstring(sample_rss_xml)
        channel = root.find("channel")
        assert channel is not None
        assert channel.find("title").text == "Test Podcast"

    def test_fixture_has_two_items(self, sample_rss_xml):
        root = ET.fromstring(sample_rss_xml)
        items = root.find("channel").findall("item")
        assert len(items) == 2

    def test_fixture_enclosure_urls(self, sample_rss_xml):
        root = ET.fromstring(sample_rss_xml)
        items = root.find("channel").findall("item")
        urls = [item.find("enclosure").get("url") for item in items]
        assert urls == [
            "https://example.com/ep001.mp3",
            "https://example.com/ep002.mp3",
        ]
