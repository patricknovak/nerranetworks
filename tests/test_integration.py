"""Integration tests for the podcast generation pipeline.

Tests the wiring between engine modules and show scripts by exercising
the full path from content tracking through digest formatting, RSS
generation, and publishing — all without making real API calls.
"""

import datetime
import json
import os
import re
import sys
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "digests"))


# ---------------------------------------------------------------------------
# ContentTracker integration
# ---------------------------------------------------------------------------


class TestContentTrackerIntegration:
    """Test ContentTracker across all show patterns."""

    SAMPLE_TST_DIGEST = textwrap.dedent("""\
        # Tesla Shorts Time
        **Date:** February 23, 2026
        **TSLA:** $245.67 +3.21 (+1.31%)

        ━━━━━━━━━━━━━━━━━━━━
        ### Top News
        1. **Tesla Cybertruck Production Ramps: 23 February, 2026, 08:00 AM PST, Teslarati**
           Tesla is now producing 2,500 Cybertrucks per week at GigaTexas.
           Source: https://www.teslarati.com/cybertruck-ramp

        2. **FSD v13.5 Rolling Out: 23 February, 2026, 09:00 AM PST, The Verge**
           The latest FSD update shows significant improvement in unprotected lefts.
           Source: https://www.theverge.com/fsd-v13-5

        ━━━━━━━━━━━━━━━━━━━━
        ## Tesla X Takeover: What is Hot Right Now
        1. 🚨 **Robotaxi Fleet Growing in Austin** - Big news from Austin
           Source: https://example.com/robotaxi

        ━━━━━━━━━━━━━━━━━━━━
        ## Short Spot
        **Analyst Downgrades Tesla: 23 February, 2026, 07:00 AM PST, MarketWatch**
        Some analyst downgraded Tesla, but the long-term mission remains strong.
        Source: https://example.com/downgrade

        ━━━━━━━━━━━━━━━━━━━━
        ### Tesla First Principles
        🧠 Tesla First Principles - Cutting Through the Noise

        Taking a step back, let's apply first principles to battery chemistry...

        **The Fundamental Question:** Can Tesla maintain cost leadership?

        **The Data Says:** Tesla's 4680 cells are approaching $80/kWh.

        **The Tesla Approach:** Vertical integration from mining to manufacturing.

        **The Real-World Impact:** Cheaper EVs mean more people can afford clean transport.

        **The Long-Term Play:** Battery cost parity with ICE by 2027.

        ━━━━━━━━━━━━━━━━━━━━
        ### Daily Challenge
        💪 **Daily Challenge**
        Try tracking your energy usage for one week.

        ━━━━━━━━━━━━━━━━━━━━
        ✨ **Inspiration Quote:** "The future belongs to those who believe in the beauty of their dreams." – Eleanor Roosevelt
    """)

    SAMPLE_FF_DIGEST = textwrap.dedent("""\
        # Fascinating Frontiers
        **Date:** February 23, 2026

        ━━━━━━━━━━━━━━━━━━━━
        ### Top 15 Space & Astronomy News
        1. **James Webb Discovers New Exoplanet: 23 February, 2026, Space.com**
           The JWST found a potentially habitable world 40 light-years away.

        2. **SpaceX Starship Test Flight 7 Success: 23 February, 2026, Teslarati**
           Full stack flight with successful booster catch.

        ━━━━━━━━━━━━━━━━━━━━
        ### Cosmic Spotlight
        Today's deep dive: The search for biosignatures in exoplanet atmospheres.

        ━━━━━━━━━━━━━━━━━━━━
        ### Daily Inspiration
        "Look up at the stars and not down at your feet." – Stephen Hawking
    """)

    SAMPLE_PT_DIGEST = textwrap.dedent("""\
        # Planetterrian Daily
        **Date:** February 23, 2026

        ━━━━━━━━━━━━━━━━━━━━
        ### Top 15 Science & Longevity News
        1. **CRISPR Gene Therapy Breakthrough: 23 February, 2026, Nature**
           A new CRISPR variant shows promise for treating genetic disorders.

        ━━━━━━━━━━━━━━━━━━━━
        ### Planetterrian Spotlight
        Deep dive into telomere biology and aging research.

        ━━━━━━━━━━━━━━━━━━━━
        ### Daily Inspiration
        "Science is a way of thinking much more than a body of knowledge." – Carl Sagan
    """)

    SAMPLE_OV_DIGEST = textwrap.dedent("""\
        # Omni View - Balanced News
        **Date:** February 23, 2026

        ### Today's Top Stories

        1. **US-China Trade Tensions Rise Over New Tech Tariffs**
           New tariffs imposed on tech imports affect semiconductor supply chains.

        2. **Federal Reserve Signals Extended Rate Hold at 5.25%**
           Markets react to Fed decision to hold rates steady through Q2.
    """)

    SAMPLE_EI_DIGEST = textwrap.dedent("""\
        # Environmental Intelligence
        **Date:** February 23, 2026

        ## Executive Summary
        BC Ministry of Environment announces new contaminated sites regulation amendments.

        ## Lead Story
        **New CSR Amendments Take Effect March 1: 23 February, 2026, BC Government**
        The BC government has finalized amendments to the Contaminated Sites Regulation.

        ### Regulatory & Policy Watch
        1. **CEPA Review Progress: Canada Gazette Part II**
           Federal review of CEPA moves to public consultation phase.

        ### Science & Technical
        1. **PFAS Remediation Breakthrough: Nature Climate Change**
           New photocatalytic process shows 99.9% destruction of PFAS compounds.

        ### Industry & Practice
        1. **ISO 17025 Accreditation Update: Environmental Protection Online**
           New requirements for environmental testing laboratories take effect.
    """)

    @pytest.fixture
    def tmp_tracker_dir(self, tmp_path):
        return tmp_path / "tracker"

    def test_tst_section_extraction(self, tmp_tracker_dir):
        """TST ContentTracker extracts all sections including First Principles."""
        from engine.content_tracker import ContentTracker, TST_SECTION_PATTERNS

        tracker = ContentTracker("tesla", tmp_tracker_dir)
        tracker.load()
        tracker.record_episode(self.SAMPLE_TST_DIGEST, TST_SECTION_PATTERNS)

        ep = tracker.data["episodes"][-1]
        assert len(ep["headlines"]) >= 2, "Should extract at least 2 headlines"
        assert "first_principles" in ep["sections"], "Should extract First Principles"
        assert "short_spot" in ep["sections"], "Should extract Short Spot"
        assert "daily_challenge" in ep["sections"], "Should extract Daily Challenge"
        assert ep["quote_author"] == "Eleanor Roosevelt"

    def test_ff_section_extraction(self, tmp_tracker_dir):
        """FF ContentTracker extracts cosmic spotlight and inspiration."""
        from engine.content_tracker import ContentTracker, FF_SECTION_PATTERNS

        tracker = ContentTracker("fascinating_frontiers", tmp_tracker_dir)
        tracker.load()
        tracker.record_episode(self.SAMPLE_FF_DIGEST, FF_SECTION_PATTERNS)

        ep = tracker.data["episodes"][-1]
        assert len(ep["headlines"]) >= 1
        assert "cosmic_spotlight" in ep["sections"]
        assert "daily_inspiration" in ep["sections"]
        assert ep["quote_author"] == "Stephen Hawking"

    def test_pt_section_extraction(self, tmp_tracker_dir):
        """PT ContentTracker extracts planetterrian spotlight."""
        from engine.content_tracker import ContentTracker, PT_SECTION_PATTERNS

        tracker = ContentTracker("planetterrian", tmp_tracker_dir)
        tracker.load()
        tracker.record_episode(self.SAMPLE_PT_DIGEST, PT_SECTION_PATTERNS)

        ep = tracker.data["episodes"][-1]
        assert len(ep["headlines"]) >= 1
        assert "planetterrian_spotlight" in ep["sections"]
        assert ep["quote_author"] == "Carl Sagan"

    def test_ov_section_extraction(self, tmp_tracker_dir):
        """OV ContentTracker extracts headlines."""
        from engine.content_tracker import ContentTracker, OV_SECTION_PATTERNS

        tracker = ContentTracker("omni_view", tmp_tracker_dir)
        tracker.load()
        tracker.record_episode(self.SAMPLE_OV_DIGEST, OV_SECTION_PATTERNS)

        ep = tracker.data["episodes"][-1]
        assert len(ep["headlines"]) >= 1

    def test_ei_section_extraction(self, tmp_tracker_dir):
        """EI ContentTracker extracts regulatory, science, and industry sections."""
        from engine.content_tracker import ContentTracker, EI_SECTION_PATTERNS

        tracker = ContentTracker("env_intel", tmp_tracker_dir)
        tracker.load()
        tracker.record_episode(self.SAMPLE_EI_DIGEST, EI_SECTION_PATTERNS)

        ep = tracker.data["episodes"][-1]
        assert len(ep["headlines"]) >= 1, "Should extract lead story headline"
        assert "regulatory_watch" in ep["sections"], "Should extract Regulatory Watch"
        assert "science_technical" in ep["sections"], "Should extract Science & Technical"
        assert "industry_practice" in ep["sections"], "Should extract Industry & Practice"

    def test_show_section_patterns_registry(self):
        """SHOW_SECTION_PATTERNS maps all known show slugs."""
        from engine.content_tracker import SHOW_SECTION_PATTERNS

        expected = {"tesla", "tesla_shorts_time", "fascinating_frontiers",
                    "planetterrian", "omni_view", "env_intel"}
        assert set(SHOW_SECTION_PATTERNS.keys()) == expected

    def test_cross_episode_dedup(self, tmp_tracker_dir):
        """Articles similar to previously recorded headlines are filtered."""
        from engine.content_tracker import ContentTracker, TST_SECTION_PATTERNS

        tracker = ContentTracker("tesla", tmp_tracker_dir)
        tracker.load()
        tracker.record_episode(self.SAMPLE_TST_DIGEST, TST_SECTION_PATTERNS)

        articles = [
            {"title": "Tesla Cybertruck Production Ramps Up at Giga Texas"},
            {"title": "Completely Different Article About Solar Panels"},
        ]
        filtered = tracker.filter_recent_articles(articles, similarity_threshold=0.5)
        assert len(filtered) < len(articles), "Similar article should be filtered"
        assert any("Solar" in a["title"] for a in filtered)

    def test_prompt_summary_generation(self, tmp_tracker_dir):
        """get_summary_for_prompt returns meaningful text."""
        from engine.content_tracker import ContentTracker, TST_SECTION_PATTERNS

        tracker = ContentTracker("tesla", tmp_tracker_dir)
        tracker.load()
        tracker.record_episode(self.SAMPLE_TST_DIGEST, TST_SECTION_PATTERNS)

        summary = tracker.get_summary_for_prompt()
        assert "RECENTLY COVERED" in summary
        assert "Eleanor Roosevelt" in summary

    def test_tracker_persistence(self, tmp_tracker_dir):
        """Tracker data survives save/load round trip."""
        from engine.content_tracker import ContentTracker, FF_SECTION_PATTERNS

        tracker1 = ContentTracker("ff_test", tmp_tracker_dir)
        tracker1.load()
        tracker1.record_episode(self.SAMPLE_FF_DIGEST, FF_SECTION_PATTERNS)
        tracker1.save()

        tracker2 = ContentTracker("ff_test", tmp_tracker_dir)
        tracker2.load()
        assert len(tracker2.data["episodes"]) == 1
        assert tracker2.data["episodes"][0]["quote_author"] == "Stephen Hawking"


# ---------------------------------------------------------------------------
# Publisher integration
# ---------------------------------------------------------------------------


class TestPublisherIntegration:
    """Test publisher functions end to end."""

    def test_format_digest_for_x_strips_markdown(self):
        """Engine format_digest_for_x strips markdown correctly."""
        from engine.publisher import format_digest_for_x

        input_text = textwrap.dedent("""\
            ## Breaking News
            **Bold headline**: Important details here.
            [Click here](https://example.com/article) for more.


            Another paragraph.
        """)
        result = format_digest_for_x(input_text)
        assert "##" not in result
        assert "**" not in result
        assert "https://example.com/article" in result
        assert "[Click here]" not in result
        assert "\n\n\n" not in result

    def test_rss_feed_round_trip(self, tmp_path):
        """Create an RSS feed, add an episode, verify structure."""
        pytest.importorskip("feedgen")
        from engine.publisher import update_rss_feed

        rss_path = tmp_path / "test.rss"
        mp3_path = tmp_path / "test_ep001.mp3"
        mp3_path.write_bytes(b"\xff" * 5000)

        update_rss_feed(
            rss_path=rss_path,
            episode_num=1,
            episode_title="Test Episode 1",
            episode_description="A test description.",
            episode_date=datetime.date(2026, 2, 23),
            mp3_filename="test_ep001.mp3",
            mp3_duration=300.0,
            mp3_path=mp3_path,
            base_url="https://example.com",
            audio_subdir="audio",
            channel_title="Test Podcast",
            channel_link="https://example.com",
            channel_description="Test",
            channel_author="Tester",
            channel_email="test@example.com",
            channel_category="Technology",
            guid_prefix="test",
        )

        assert rss_path.exists()
        tree = ET.parse(str(rss_path))
        root = tree.getroot()
        items = root.findall(".//item")
        assert len(items) == 1

        # Add a second episode
        mp3_path2 = tmp_path / "test_ep002.mp3"
        mp3_path2.write_bytes(b"\xff" * 6000)

        update_rss_feed(
            rss_path=rss_path,
            episode_num=2,
            episode_title="Test Episode 2",
            episode_description="Second test.",
            episode_date=datetime.date(2026, 2, 24),
            mp3_filename="test_ep002.mp3",
            mp3_duration=360.0,
            mp3_path=mp3_path2,
            base_url="https://example.com",
            audio_subdir="audio",
            channel_title="Test Podcast",
            channel_link="https://example.com",
            channel_description="Test",
            channel_author="Tester",
            channel_email="test@example.com",
            channel_category="Technology",
            guid_prefix="test",
        )

        tree = ET.parse(str(rss_path))
        items = tree.findall(".//item")
        assert len(items) == 2

    def test_episode_numbering(self, tmp_path):
        """get_next_episode_number reads from RSS and file system."""
        pytest.importorskip("feedgen")
        from engine.publisher import get_next_episode_number, update_rss_feed

        rss_path = tmp_path / "test.rss"
        digests_dir = tmp_path / "digests"
        digests_dir.mkdir()

        # No RSS, no files → episode 1
        assert get_next_episode_number(rss_path, digests_dir) == 1

        # Create an RSS with episode 5
        mp3 = digests_dir / "Test_Ep005_20260223.mp3"
        mp3.write_bytes(b"\xff" * 5000)

        update_rss_feed(
            rss_path=rss_path,
            episode_num=5,
            episode_title="Ep 5",
            episode_description="Test",
            episode_date=datetime.date(2026, 2, 23),
            mp3_filename=mp3.name,
            mp3_duration=100.0,
            mp3_path=mp3,
            guid_prefix="test",
        )

        assert get_next_episode_number(rss_path, digests_dir) == 6

    def test_summary_json_round_trip(self, tmp_path):
        """save_summary_to_github_pages creates and updates JSON."""
        from engine.publisher import save_summary_to_github_pages

        json_path = tmp_path / "summaries.json"

        result = save_summary_to_github_pages(
            "Episode 1 content",
            json_path,
            "Test Podcast",
            episode_num=1,
        )
        assert result == json_path
        data = json.loads(json_path.read_text())
        assert data["podcast"] == "Test Podcast"
        assert len(data["summaries"]) == 1

        # Add second summary
        save_summary_to_github_pages("Episode 2 content", json_path, "Test Podcast", episode_num=2)
        data = json.loads(json_path.read_text())
        assert len(data["summaries"]) == 2
        assert data["summaries"][0]["episode_num"] == 2  # newest first


# ---------------------------------------------------------------------------
# Feature flags integration
# ---------------------------------------------------------------------------


class TestFeatureFlags:
    """Verify feature flags are env-overridable in all show scripts."""

    def _extract_flag_pattern(self, script_path: Path) -> bool:
        """Check if a script uses env_bool for feature flag overrides."""
        content = script_path.read_text(encoding="utf-8")
        has_env_bool_test_mode = bool(
            re.search(r'TEST_MODE\s*=\s*env_bool\s*\(\s*"TEST_MODE"', content)
        )
        has_env_bool_x_posting = bool(
            re.search(r'ENABLE_X_POSTING\s*=\s*env_bool\s*\(\s*"ENABLE_X_POSTING"', content)
        )
        return has_env_bool_test_mode and has_env_bool_x_posting

    def test_tst_has_env_overridable_flags(self):
        script = PROJECT_ROOT / "digests" / "tesla_shorts_time.py"
        assert self._extract_flag_pattern(script), "TST should have env-overridable flags"

    def test_ff_has_env_overridable_flags(self):
        script = PROJECT_ROOT / "digests" / "fascinating_frontiers.py"
        assert self._extract_flag_pattern(script), "FF should have env-overridable flags"

    def test_pt_has_env_overridable_flags(self):
        script = PROJECT_ROOT / "digests" / "planetterrian.py"
        assert self._extract_flag_pattern(script), "PT should have env-overridable flags"

    def test_ov_has_env_overridable_flags(self):
        script = PROJECT_ROOT / "digests" / "omni_view.py"
        assert self._extract_flag_pattern(script), "OV should have env-overridable flags"


# ---------------------------------------------------------------------------
# Show config integration
# ---------------------------------------------------------------------------


class TestShowConfigs:
    """Verify all show YAML configs can be loaded."""

    @pytest.fixture(params=["tesla", "omni_view", "fascinating_frontiers", "planetterrian", "env_intel"])
    def show_slug(self, request):
        return request.param

    def test_config_loads(self, show_slug):
        """Each show YAML config loads without error."""
        from engine.config import load_config

        config_path = PROJECT_ROOT / "shows" / f"{show_slug}.yaml"
        if not config_path.exists():
            pytest.skip(f"Config not found: {config_path}")

        config = load_config(config_path)
        assert config.name
        assert config.slug == show_slug
        assert len(config.sources) > 0

    def test_env_intel_config_details(self):
        """Environmental Intelligence config has expected properties."""
        from engine.config import load_config

        config_path = PROJECT_ROOT / "shows" / "env_intel.yaml"
        if not config_path.exists():
            pytest.skip("env_intel.yaml not found")

        config = load_config(config_path)
        assert config.slug == "env_intel"
        assert config.publishing.x_enabled is False
        assert config.newsletter.enabled is True
        assert config.audio.music_file == "assets/music/env_intel.mp3"


# ---------------------------------------------------------------------------
# Subdirectory structure
# ---------------------------------------------------------------------------


class TestOutputDirectories:
    """Verify expected output directory structure."""

    def test_ff_uses_subdirectory(self):
        subdir = PROJECT_ROOT / "digests" / "fascinating_frontiers"
        assert subdir.is_dir(), "FF should have digests/fascinating_frontiers/"

    def test_pt_uses_subdirectory(self):
        subdir = PROJECT_ROOT / "digests" / "planetterrian"
        assert subdir.is_dir(), "PT should have digests/planetterrian/"

    def test_ei_uses_subdirectory(self):
        subdir = PROJECT_ROOT / "digests" / "env_intel"
        assert subdir.is_dir(), "EI should have digests/env_intel/"

    def test_tst_subdirectory_exists(self):
        subdir = PROJECT_ROOT / "digests" / "tesla_shorts_time"
        assert subdir.is_dir(), "TST should have digests/tesla_shorts_time/"

    def test_ov_subdirectory_exists(self):
        subdir = PROJECT_ROOT / "digests" / "omni_view"
        assert subdir.is_dir(), "OV should have digests/omni_view/"


# ---------------------------------------------------------------------------
# No dead secrets
# ---------------------------------------------------------------------------


class TestCleanup:
    """Verify dead code and secrets are cleaned up."""

    def test_no_newsapi_in_active_workflow(self):
        """NEWSAPI_KEY should not appear in the active workflow."""
        workflow = PROJECT_ROOT / ".github" / "workflows" / "run-show.yml"
        if workflow.exists():
            content = workflow.read_text()
            assert "NEWSAPI_KEY" not in content

    def test_no_formatted_md_creation(self):
        """TST should no longer create _formatted.md files."""
        tst = PROJECT_ROOT / "digests" / "tesla_shorts_time.py"
        content = tst.read_text()
        assert "x_path_formatted" not in content, "TST should not create _formatted.md files"
