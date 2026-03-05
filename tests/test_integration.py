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
                    "planetterrian", "omni_view", "env_intel", "models_agents",
                    "models_agents_beginners"}
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

    @pytest.fixture(params=["tesla", "omni_view", "fascinating_frontiers", "planetterrian", "env_intel", "models_agents"])
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
        assert config.audio.music_file == "assets/music/tesla_shorts_time.mp3"

    def test_models_agents_config_details(self):
        """Models & Agents config has expected properties."""
        from engine.config import load_config

        config_path = PROJECT_ROOT / "shows" / "models_agents.yaml"
        if not config_path.exists():
            pytest.skip("models_agents.yaml not found")

        config = load_config(config_path)
        assert config.slug == "models_agents"
        assert config.name == "Models & Agents"
        assert config.publishing.x_enabled is False
        assert config.newsletter.enabled is True
        assert config.newsletter.api_key_env == "MODELS_AGENTS_NEWSLETTER_API_KEY"
        assert len(config.sources) > 10  # Has many RSS feeds
        assert config.tts.voice_id == "dTrBzPvD2GpAqkk1MUzA"


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

    def test_ma_subdirectory_exists(self):
        subdir = PROJECT_ROOT / "digests" / "models_agents"
        assert subdir.is_dir(), "M&A should have digests/models_agents/"


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


# ---------------------------------------------------------------------------
# Post-run validation tests
# ---------------------------------------------------------------------------


class TestPostRunValidation:
    """Test the post-run validation module."""

    def test_validate_mp3_missing(self, tmp_path):
        """Missing MP3 fails validation."""
        from engine.post_run_validation import validate_mp3

        assert validate_mp3(tmp_path / "nonexistent.mp3") is False

    def test_validate_mp3_too_small(self, tmp_path):
        """Tiny MP3 file fails validation."""
        from engine.post_run_validation import validate_mp3

        small_mp3 = tmp_path / "tiny.mp3"
        small_mp3.write_bytes(b"\x00" * 100)
        assert validate_mp3(small_mp3) is False

    def test_validate_mp3_good_size(self, tmp_path):
        """Reasonably sized MP3 passes validation (size check only)."""
        from engine.post_run_validation import validate_mp3

        good_mp3 = tmp_path / "good.mp3"
        good_mp3.write_bytes(b"\xff" * 200_000)
        assert validate_mp3(good_mp3) is True

    def test_validate_rss_missing(self, tmp_path):
        """Missing RSS file fails validation."""
        from engine.post_run_validation import validate_rss

        assert validate_rss(tmp_path / "missing.rss") is False

    def test_validate_rss_invalid_xml(self, tmp_path):
        """Invalid XML fails validation."""
        from engine.post_run_validation import validate_rss

        bad_rss = tmp_path / "bad.rss"
        bad_rss.write_text("not xml at all <unclosed", encoding="utf-8")
        assert validate_rss(bad_rss) is False

    def test_validate_rss_valid(self, tmp_path):
        """Valid RSS passes validation."""
        from engine.post_run_validation import validate_rss

        good_rss = tmp_path / "good.rss"
        good_rss.write_text(
            '<?xml version="1.0"?><rss><channel><title>Test</title>'
            "<item><guid>test-ep001</guid></item></channel></rss>",
            encoding="utf-8",
        )
        assert validate_rss(good_rss) is True

    def test_validate_digest_empty(self):
        """Empty digest fails validation."""
        from engine.post_run_validation import validate_digest

        assert validate_digest("", "test") is False
        assert validate_digest("   ", "test") is False

    def test_validate_digest_too_short(self):
        """Very short digest fails validation."""
        from engine.post_run_validation import validate_digest

        assert validate_digest("Hello world", "test") is False

    def test_validate_digest_good(self):
        """Sufficient digest passes validation."""
        from engine.post_run_validation import validate_digest

        assert validate_digest("x" * 300, "test") is True

    def test_run_post_validation_all_pass(self, tmp_path):
        """Full validation suite passes with good inputs."""
        from engine.post_run_validation import run_post_validation

        mp3 = tmp_path / "test.mp3"
        mp3.write_bytes(b"\xff" * 200_000)
        rss = tmp_path / "test.rss"
        rss.write_text(
            '<?xml version="1.0"?><rss><channel><title>T</title></channel></rss>',
            encoding="utf-8",
        )

        assert run_post_validation(
            mp3_path=mp3,
            rss_path=rss,
            digest_text="x" * 300,
            show_name="test",
            episode_num=1,
        ) is True


# ---------------------------------------------------------------------------
# LLM output validation tests
# ---------------------------------------------------------------------------


class TestLLMOutputValidation:
    """Test the LLM output validation in engine/generator.py."""

    def test_empty_output_logs_error(self, caplog):
        """Empty LLM output triggers error log."""
        from engine.generator import _validate_llm_output

        with caplog.at_level("ERROR"):
            _validate_llm_output("", stage="digest", show_name="test")
        assert "EMPTY" in caplog.text

    def test_short_output_logs_warning(self, caplog):
        """Short LLM output triggers warning log."""
        from engine.generator import _validate_llm_output

        with caplog.at_level("WARNING"):
            _validate_llm_output("tiny output", stage="digest", show_name="test")
        assert "suspiciously short" in caplog.text

    def test_good_output_no_warning(self, caplog):
        """Sufficient LLM output produces no warnings."""
        from engine.generator import _validate_llm_output

        with caplog.at_level("WARNING"):
            _validate_llm_output("x" * 500, stage="digest", show_name="test")
        assert "EMPTY" not in caplog.text
        assert "suspiciously short" not in caplog.text

    def test_instruction_leak_detected(self, caplog):
        """Leaked prompt instructions trigger warning."""
        from engine.generator import _validate_llm_output

        text = "x" * 300 + "\nAs an AI language model, I cannot"
        with caplog.at_level("WARNING"):
            _validate_llm_output(text, stage="digest", show_name="test")
        assert "leaked prompt" in caplog.text


# ---------------------------------------------------------------------------
# TTS chunking tests
# ---------------------------------------------------------------------------


class TestTTSChunking:
    """Test the improved TTS text chunking logic."""

    def test_short_text_no_split(self):
        """Text under max_chars returns single chunk."""
        from engine.tts import chunk_text

        result = chunk_text("Hello world.", max_chars=5000)
        assert len(result) == 1

    def test_splits_at_sentence_boundary(self):
        """Text is split at sentence ending, not mid-sentence."""
        from engine.tts import chunk_text

        # Build text that exceeds 100 chars
        text = "First sentence. " + "x" * 90 + ". Second sentence."
        result = chunk_text(text, max_chars=100)
        assert len(result) >= 2
        # First chunk should end with a period
        assert result[0].rstrip().endswith(".")

    def test_splits_at_clause_boundary(self):
        """When no sentence boundary exists, splits at clause boundary."""
        from engine.tts import chunk_text

        # A very long single sentence with semicolons
        text = "A" * 40 + "; " + "B" * 40 + "; " + "C" * 40
        result = chunk_text(text, max_chars=50)
        assert len(result) >= 2

    def test_no_exclamation_appended_by_default(self):
        """Speak function should not append exclamation by default."""
        from engine.tts import speak

        import inspect
        sig = inspect.signature(speak)
        assert sig.parameters["append_exclamation"].default is False


# ---------------------------------------------------------------------------
# Config validation tests (all shows have system prompts)
# ---------------------------------------------------------------------------


class TestSystemPrompts:
    """Verify all shows now have system prompt files."""

    @pytest.fixture(
        params=["tesla", "omni_view", "fascinating_frontiers", "planetterrian", "env_intel", "models_agents"]
    )
    def show_slug(self, request):
        return request.param

    def test_system_prompt_file_exists(self, show_slug):
        """Each show config references a system prompt file that exists."""
        from engine.config import load_config

        config_path = PROJECT_ROOT / "shows" / f"{show_slug}.yaml"
        if not config_path.exists():
            pytest.skip(f"Config not found: {config_path}")

        config = load_config(config_path)
        assert config.llm.system_prompt_file, f"{show_slug} should have system_prompt_file"
        sp_path = Path(config.llm.system_prompt_file)
        assert sp_path.exists(), f"System prompt file not found: {sp_path}"

    def test_all_shows_use_grok4(self, show_slug):
        """All shows should now use grok-4."""
        from engine.config import load_config

        config_path = PROJECT_ROOT / "shows" / f"{show_slug}.yaml"
        if not config_path.exists():
            pytest.skip(f"Config not found: {config_path}")

        config = load_config(config_path)
        assert config.llm.model == "grok-4", f"{show_slug} should use grok-4, got {config.llm.model}"

    def test_digest_temp_for_news_shows(self, show_slug):
        """News/factual shows should use temperature <= 0.5."""
        from engine.config import load_config

        config_path = PROJECT_ROOT / "shows" / f"{show_slug}.yaml"
        if not config_path.exists():
            pytest.skip(f"Config not found: {config_path}")

        config = load_config(config_path)
        assert config.llm.digest_temperature <= 0.5, (
            f"{show_slug} digest_temperature should be <= 0.5 for factual content, "
            f"got {config.llm.digest_temperature}"
        )


# ---------------------------------------------------------------------------
# Hook extraction
# ---------------------------------------------------------------------------


class TestHookExtraction:
    """Verify _extract_hook() extracts the daily headline from digests."""

    def test_extracts_bold_hook(self):
        from run_show import _extract_hook
        digest = textwrap.dedent("""\
            # Tesla Shorts Time
            **Date:** February 24, 2026
            **HOOK:** Tesla's Cybertruck just broke a sales record in its biggest quarter yet.

            ### Top 10 News Items
        """)
        assert _extract_hook(digest) == "Tesla's Cybertruck just broke a sales record in its biggest quarter yet."

    def test_extracts_plain_hook(self):
        from run_show import _extract_hook
        digest = "HOOK: A new Mars rover just sent back stunning images of ice deposits.\n\nMore content..."
        assert _extract_hook(digest) == "A new Mars rover just sent back stunning images of ice deposits."

    def test_extracts_hook_with_brackets(self):
        """LLM sometimes wraps the hook in square brackets."""
        from run_show import _extract_hook
        digest = "**HOOK:** [Scientists discover high-efficiency solar cells using lunar regolith]\n\nOther content"
        assert _extract_hook(digest) == "Scientists discover high-efficiency solar cells using lunar regolith"

    def test_returns_none_when_missing(self):
        from run_show import _extract_hook
        digest = "# Tesla Shorts Time\n**Date:** Feb 24\n\n### Top 10 News Items\n1. Headline"
        assert _extract_hook(digest) is None

    def test_returns_none_for_empty_hook(self):
        from run_show import _extract_hook
        digest = "**HOOK:** \n\n### News"
        assert _extract_hook(digest) is None

    def test_clean_digest_strips_hook_line(self):
        """_clean_digest_for_podcast removes the HOOK line so it doesn't leak into the script."""
        from run_show import _clean_digest_for_podcast
        digest = "**HOOK:** Tesla's Cybertruck just broke a sales record.\n\n### Top 10 News Items\n1. Headline"
        cleaned = _clean_digest_for_podcast(digest)
        assert "HOOK" not in cleaned
        assert "Cybertruck" not in cleaned
        assert "Top 10 News Items" in cleaned

    def test_clean_podcast_script_drops_leaked_prompt(self):
        """_clean_podcast_script strips leaked prompt instruction lines."""
        from run_show import _clean_podcast_script
        script = (
            "[Intro music - 5 seconds]\n"
            "RULES:\n"
            "Use this exact intro:\n"
            "Patrick: Welcome to the show!\n"
            "Patrick: Today we cover big news.\n"
            "Source: https://example.com\n"
            "[Outro music]\n"
        )
        cleaned = _clean_podcast_script(script)
        assert "RULES" not in cleaned
        assert "Use this exact" not in cleaned
        assert "Source:" not in cleaned
        assert "Welcome to the show!" in cleaned
        assert "Today we cover big news." in cleaned


# ---------------------------------------------------------------------------
# run_show.py pipeline integration
# ---------------------------------------------------------------------------


class TestRunShowPipeline:
    """Verify run_show.py works for all shows (dry-run only — no API calls)."""

    ALL_SHOWS = ["tesla", "omni_view", "fascinating_frontiers",
                 "planetterrian", "env_intel", "models_agents"]

    @pytest.mark.parametrize("show", ALL_SHOWS)
    def test_dry_run(self, show):
        """--dry-run should print the plan and exit cleanly."""
        import subprocess

        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "run_show.py"), show, "--dry-run"],
            capture_output=True, text=True, timeout=30,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, (
            f"Dry run failed for {show}:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "DRY RUN" in result.stdout

    def test_discover_shows_finds_all(self):
        """_discover_shows() finds all 6 show configs."""
        from run_show import _discover_shows
        shows = _discover_shows()
        for s in self.ALL_SHOWS:
            assert s in shows, f"{s} not found by _discover_shows()"

    def test_build_teaser_all_shows(self):
        """_build_teaser returns non-empty text for each show."""
        from engine.config import load_config
        from run_show import _build_teaser

        for show in self.ALL_SHOWS:
            config = load_config(PROJECT_ROOT / "shows" / f"{show}.yaml")
            teaser = _build_teaser(config, episode_num=1,
                                   today_str="February 27, 2026",
                                   extra_context={})
            assert teaser, f"_build_teaser returned empty for {show}"
            assert "Episode 1" in teaser or "episode 1" in teaser.lower()


# ---------------------------------------------------------------------------
# Legacy script deprecation
# ---------------------------------------------------------------------------


class TestLegacyDeprecation:
    """Verify legacy scripts carry deprecation notices."""

    LEGACY_SCRIPTS = [
        "tesla_shorts_time.py",
        "omni_view.py",
        "fascinating_frontiers.py",
        "planetterrian.py",
    ]

    @pytest.mark.parametrize("script", LEGACY_SCRIPTS)
    def test_has_deprecation_notice(self, script):
        """Each legacy script should have a deprecation notice in its docstring."""
        path = PROJECT_ROOT / "digests" / script
        content = path.read_text(encoding="utf-8")
        assert "deprecated" in content.lower(), (
            f"{script} is missing a deprecation notice"
        )
        assert "run_show.py" in content, (
            f"{script} deprecation notice should reference run_show.py"
        )

    def test_workflow_uses_run_show_not_legacy(self):
        """The CI workflow should call run_show.py, not legacy scripts."""
        workflow = PROJECT_ROOT / ".github" / "workflows" / "run-show.yml"
        content = workflow.read_text()
        assert "python run_show.py" in content
        for script in self.LEGACY_SCRIPTS:
            assert script not in content, (
                f"Workflow should not reference legacy script {script}"
            )

    def test_newsletter_env_vars_in_workflow(self):
        """CI workflow should inject newsletter API keys for shows that need them."""
        workflow = PROJECT_ROOT / ".github" / "workflows" / "run-show.yml"
        content = workflow.read_text()
        for var in ["OMNI_VIEW_NEWSLETTER_API_KEY",
                     "ENV_INTEL_NEWSLETTER_API_KEY",
                     "MODELS_AGENTS_NEWSLETTER_API_KEY"]:
            assert var in content, (
                f"Workflow .env should include {var} for newsletter delivery"
            )
