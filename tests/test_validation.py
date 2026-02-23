"""Tests for engine/validation.py — post-generation digest validation."""

import pytest

from engine.validation import (
    ValidationConfig,
    SectionRule,
    validate_digest,
    check_section_overlap,
    check_item_counts,
    check_forbidden_content,
    check_within_episode_duplicates,
    check_cross_episode_repeats,
    tst_validation_config,
    ff_validation_config,
    pt_validation_config,
    ov_validation_config,
)
from engine.content_tracker import TST_SECTION_PATTERNS, FF_SECTION_PATTERNS


SAMPLE_DIGEST = """
━━━━━━━━━━━━━━━━━━━━
### Top News
1. **Tesla Cybertruck Production Ramps Up Significantly**
   Big milestone. More trucks coming.
   Source: https://example.com/1

2. **FSD v13 Achieves Cross-Country Zero Interventions**
   Autonomous driving breakthrough.
   Source: https://example.com/2

3. **Tesla Energy Storage Revenue Doubles Year Over Year**
   Megapacks are growing fast.
   Source: https://example.com/3

4. **Model Y Refresh Spotted at Gigafactory Berlin**
   New design details emerging.
   Source: https://example.com/4

5. **Tesla Supercharger Network Reaches 60,000 Globally**
   Charging infrastructure expands.
   Source: https://example.com/5

6. **Tesla Semi Deliveries Begin to PepsiCo Fleet**
   Commercial trucking starts.
   Source: https://example.com/6

━━━━━━━━━━━━━━━━━━━━
## Tesla X Takeover: What's Hot Right Now
🎙️ Tesla X Takeover

1. 🚨 **Optimus Robot Walks Unassisted in Demo**
   Robot division making progress.

2. 🔥 **Tesla Insurance Expands to All 50 States**
   Insurance business growing.

3. 💡 **Giga Mexico Construction Accelerates**
   New factory on schedule.

━━━━━━━━━━━━━━━━━━━━
## Short Spot
📉 **Short Spot**: Margin pressure from price cuts.

━━━━━━━━━━━━━━━━━━━━
### Tesla First Principles
🧠 Battery degradation analysis.

━━━━━━━━━━━━━━━━━━━━
### Daily Challenge
💪 Calculate your EV savings today.

━━━━━━━━━━━━━━━━━━━━
✨ **Inspiration Quote:** "Innovation distinguishes between a leader and a follower." – Steve Jobs
"""


OVERLAP_DIGEST = """
━━━━━━━━━━━━━━━━━━━━
### Top News
1. **Tesla Cybertruck Production Ramps Up Significantly**
   Source: https://example.com/1

2. **FSD v13 Achieves Zero Interventions Milestone**
   Source: https://example.com/2

━━━━━━━━━━━━━━━━━━━━
## Tesla X Takeover: What's Hot Right Now
🎙️ Tesla X Takeover

1. 🚨 **Tesla Cybertruck Production Ramps Up Significantly** - Same story repeated.
   Very similar to Top News #1.

2. 🔥 **FSD v13 Achieves Zero Interventions Milestone** - Same story repeated.
   Very similar to Top News #2.
"""


class TestSectionOverlap:
    def test_no_overlap(self):
        issues = check_section_overlap(
            SAMPLE_DIGEST,
            [("headlines", "takeover_headlines")],
            TST_SECTION_PATTERNS,
            threshold=0.50,
        )
        assert len(issues) == 0

    def test_detects_overlap(self):
        issues = check_section_overlap(
            OVERLAP_DIGEST,
            [("headlines", "takeover_headlines")],
            TST_SECTION_PATTERNS,
            threshold=0.50,
        )
        assert len(issues) >= 1
        assert "similarity" in issues[0].lower() or "similar" in issues[0].lower()


class TestItemCounts:
    def test_sufficient_items(self):
        sections = [
            SectionRule(
                name="Top News",
                pattern=(
                    r"(?:### Top News|### Top 10 News)"
                    r"(.*?)"
                    r"(?=━━|## Tesla X Takeover|## Short Spot|$)"
                ),
                min_items=5,
            ),
        ]
        issues = check_item_counts(SAMPLE_DIGEST, sections)
        assert len(issues) == 0

    def test_insufficient_items(self):
        sections = [
            SectionRule(
                name="Top News",
                pattern=(
                    r"(?:### Top News|### Top 10 News)"
                    r"(.*?)"
                    r"(?=━━|## Tesla X Takeover|## Short Spot|$)"
                ),
                min_items=10,
            ),
        ]
        issues = check_item_counts(SAMPLE_DIGEST, sections)
        assert len(issues) == 1
        assert "6 items" in issues[0]

    def test_missing_section(self):
        sections = [
            SectionRule(
                name="Nonexistent",
                pattern=r"### Nonexistent Section(.*?)(?=━━|$)",
                min_items=1,
            ),
        ]
        issues = check_item_counts(SAMPLE_DIGEST, sections)
        assert len(issues) == 1
        assert "missing" in issues[0].lower()

    def test_optional_section_not_flagged(self):
        sections = [
            SectionRule(
                name="Nonexistent",
                pattern=r"### Nonexistent Section(.*?)(?=━━|$)",
                min_items=1,
                optional=True,
            ),
        ]
        issues = check_item_counts(SAMPLE_DIGEST, sections)
        assert len(issues) == 0


class TestForbiddenContent:
    def test_no_forbidden(self):
        issues = check_forbidden_content(SAMPLE_DIGEST, [r"FORBIDDEN_WORD"])
        assert len(issues) == 0

    def test_detects_forbidden(self):
        issues = check_forbidden_content(
            SAMPLE_DIGEST, [r"Cybertruck"]
        )
        assert len(issues) == 1


class TestWithinEpisodeDuplicates:
    def test_no_duplicates(self):
        issues = check_within_episode_duplicates(
            SAMPLE_DIGEST, TST_SECTION_PATTERNS
        )
        assert len(issues) == 0


class TestCrossEpisodeRepeats:
    def test_detects_repeat(self):
        recent = ["Tesla Cybertruck Production Ramps Up Significantly"]
        issues = check_cross_episode_repeats(
            SAMPLE_DIGEST,
            recent,
            TST_SECTION_PATTERNS,
            threshold=0.65,
        )
        assert len(issues) >= 1

    def test_no_repeats_with_different_headlines(self):
        recent = ["SpaceX Launches New Satellite"]
        issues = check_cross_episode_repeats(
            SAMPLE_DIGEST,
            recent,
            TST_SECTION_PATTERNS,
            threshold=0.65,
        )
        assert len(issues) == 0


class TestValidateDigest:
    def test_clean_digest_passes(self):
        config = ValidationConfig()
        passed, issues = validate_digest(SAMPLE_DIGEST, config)
        assert passed is True
        assert len(issues) == 0

    def test_empty_digest_fails(self):
        config = ValidationConfig()
        passed, issues = validate_digest("", config)
        assert passed is False

    def test_with_section_pairs(self):
        config = ValidationConfig(
            section_pairs=[("headlines", "takeover_headlines")],
        )
        passed, issues = validate_digest(
            SAMPLE_DIGEST, config, section_patterns=TST_SECTION_PATTERNS
        )
        assert passed is True


class TestPrebuiltConfigs:
    def test_tst_config(self):
        config = tst_validation_config()
        assert len(config.section_pairs) > 0
        assert len(config.sections) > 0

    def test_ff_config(self):
        config = ff_validation_config()
        assert len(config.sections) > 0

    def test_pt_config(self):
        config = pt_validation_config()
        assert len(config.sections) > 0

    def test_ov_config(self):
        config = ov_validation_config()
        assert len(config.sections) > 0
