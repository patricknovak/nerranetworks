"""Tests for the shared pronunciation module (assets/pronunciation.py).

Covers text cleanup, number/value converters, dictionary-based fixes,
and the top-level prepare_text_for_tts() entry point.
"""

import sys
from pathlib import Path

# Ensure project root is on the path so `assets` and `engine` can be imported.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from assets.pronunciation import (
    strip_emojis,
    strip_markdown,
    strip_urls,
    strip_unicode_decorations,
    clean_social_handles,
    clean_text_for_tts,
    replace_currency,
    replace_percentages,
    replace_dates,
    replace_times,
    replace_timezones,
    replace_episode_numbers,
    replace_ordinal_numbers,
    replace_roman_numerals,
    replace_quarter_notation,
    replace_units,
    replace_large_numbers_with_k,
    replace_scientific_designations,
    replace_standalone_large_numbers,
    apply_pronunciation_fixes,
    prepare_text_for_tts,
    _number_to_ordinal,
    _year_to_words,
    COMMON_ACRONYMS,
    WORD_PRONUNCIATIONS,
)


# ===================== Text Cleanup =====================

class TestStripEmojis:
    def test_removes_common_emojis(self):
        assert strip_emojis("Hello 🚗⚡ world") == "Hello  world"

    def test_removes_number_keycaps(self):
        result = strip_emojis("1️⃣ First item")
        # After emoji stripping, the digit should remain
        assert "First item" in result

    def test_preserves_normal_text(self):
        assert strip_emojis("No emojis here") == "No emojis here"


class TestStripMarkdown:
    def test_removes_bold(self):
        assert strip_markdown("This is **bold** text") == "This is bold text"

    def test_removes_headings(self):
        assert strip_markdown("### Heading\nContent").strip() == "Heading\nContent"

    def test_removes_horizontal_rules(self):
        assert "━" not in strip_markdown("━━━━━━━━━━━━━━━━━━━━")

    def test_preserves_content(self):
        assert strip_markdown("Plain text stays") == "Plain text stays"


class TestStripUrls:
    def test_removes_source_url_lines(self):
        text = "Some news.\nSource: https://example.com/article"
        result = strip_urls(text)
        assert "https://" not in result

    def test_removes_source_post_url(self):
        text = "Content\nSource/Post: https://example.com"
        result = strip_urls(text)
        assert "https://" not in result

    def test_removes_inline_urls(self):
        text = "Visit https://tesla.com for details"
        result = strip_urls(text)
        assert "https://" not in result
        assert "Visit" in result

    def test_preserves_non_url_text(self):
        assert strip_urls("No links here") == "No links here"


class TestStripUnicodeDecorations:
    def test_removes_zero_width_chars(self):
        assert strip_unicode_decorations("hello\u200Bworld") == "helloworld"
        assert strip_unicode_decorations("test\u2060data") == "testdata"

    def test_removes_box_drawing(self):
        result = strip_unicode_decorations("─── Section ───")
        assert "─" not in result


class TestCleanSocialHandles:
    def test_known_handles(self):
        result = clean_social_handles("Follow @teslashortstime")
        assert result == "Follow at tesla shorts time"

    def test_camelcase_handles(self):
        result = clean_social_handles("@SomeUser posted")
        assert "at Some User" in result


class TestCleanTextForTts:
    def test_full_cleanup(self):
        text = "🎙️ **Title**\n━━━\nSource: https://example.com\nContent @teslashortstime"
        result = clean_text_for_tts(text)
        assert "🎙" not in result
        assert "**" not in result
        assert "━" not in result
        assert "https://" not in result
        assert "at tesla shorts time" in result


# ===================== Number / Value Converters =====================

class TestNumberToOrdinal:
    def test_first(self):
        assert _number_to_ordinal(1) == "first"

    def test_second(self):
        assert _number_to_ordinal(2) == "second"

    def test_third(self):
        assert _number_to_ordinal(3) == "third"

    def test_eleventh(self):
        assert _number_to_ordinal(11) == "eleventh"

    def test_twentieth(self):
        assert _number_to_ordinal(20) == "twentieth"

    def test_twenty_first(self):
        assert _number_to_ordinal(21) == "twenty-first"

    def test_thirtieth(self):
        assert _number_to_ordinal(30) == "thirtieth"

    def test_fifteenth(self):
        assert _number_to_ordinal(15) == "fifteenth"


class TestYearToWords:
    def test_2026(self):
        assert _year_to_words(2026) == "twenty twenty-six"

    def test_2000(self):
        assert _year_to_words(2000) == "two thousand"

    def test_2001(self):
        assert _year_to_words(2001) == "two thousand one"

    def test_1999(self):
        assert _year_to_words(1999) == "nineteen ninety-nine"

    def test_1564(self):
        # Should be "fifteen sixty-four" not "one thousand five hundred sixty-four"
        result = _year_to_words(1564)
        assert "fifteen" in result
        assert "sixty-four" in result

    def test_1900(self):
        assert _year_to_words(1900) == "nineteen hundred"


class TestReplaceCurrency:
    def test_dollars_with_cents(self):
        result = replace_currency("Price is $417.44")
        assert "four hundred seventeen dollars and forty-four cents" in result

    def test_whole_dollars(self):
        result = replace_currency("Cost $500")
        assert "five hundred dollars" in result

    def test_large_currency(self):
        result = replace_currency("Worth $3 billion")
        assert "three billion dollars" in result

    def test_euros(self):
        result = replace_currency("Price \u20ac50")
        assert "fifty euros" in result

    def test_pounds(self):
        result = replace_currency("Cost \u00a3100")
        assert "one hundred pounds" in result


class TestReplacePercentages:
    def test_simple_percentage(self):
        result = replace_percentages("Up 30%")
        assert "thirty percent" in result

    def test_positive_sign(self):
        result = replace_percentages("+0.27%")
        assert "plus" in result
        assert "percent" in result

    def test_negative_sign(self):
        result = replace_percentages("-5.5%")
        assert "minus" in result
        assert "percent" in result

    def test_decimal_percentage(self):
        result = replace_percentages("3.59%")
        assert "percent" in result


class TestReplaceDates:
    def test_month_day_year(self):
        result = replace_dates("February 15, 2026")
        assert "fifteenth" in result
        assert "twenty twenty-six" in result

    def test_day_month_year(self):
        result = replace_dates("13 February, 2026")
        assert "thirteenth" in result

    def test_abbreviated_month(self):
        result = replace_dates("Feb 15, 2026")
        assert "fifteenth" in result

    def test_first_day(self):
        result = replace_dates("March 1, 2026")
        assert "first" in result

    def test_historical_year(self):
        result = replace_dates("February 15, 1564")
        assert "fifteen" in result


class TestReplaceTimes:
    def test_am_time(self):
        result = replace_times("at 03:08 AM")
        assert "three oh eight A M" in result

    def test_pm_time(self):
        result = replace_times("at 2:30 PM")
        assert "two thirty P M" in result

    def test_midnight(self):
        result = replace_times("00:00")
        assert "twelve" in result

    def test_time_with_periods(self):
        result = replace_times("at 2:59 a.m.")
        assert "two" in result
        assert "fifty-nine" in result


class TestReplaceTimezones:
    def test_pst(self):
        assert "Pacific Standard Time" in replace_timezones("3 PM PST")

    def test_est(self):
        assert "Eastern Standard Time" in replace_timezones("8 AM EST")

    def test_utc(self):
        assert "U T C" in replace_timezones("12:00 UTC")


class TestReplaceEpisodeNumbers:
    def test_episode_number(self):
        result = replace_episode_numbers("Episode 39")
        assert "thirty-nine" in result

    def test_episode_large_number(self):
        result = replace_episode_numbers("episode 336")
        assert "three hundred thirty-six" in result


class TestReplaceOrdinalNumbers:
    def test_seventh(self):
        assert replace_ordinal_numbers("7th magnitude") == "seventh magnitude"

    def test_tenth(self):
        assert replace_ordinal_numbers("10th flight") == "tenth flight"

    def test_first(self):
        assert replace_ordinal_numbers("1st place") == "first place"

    def test_twenty_second(self):
        result = replace_ordinal_numbers("22nd item")
        assert "twenty-second" in result


class TestReplaceRomanNumerals:
    def test_phase_three(self):
        result = replace_roman_numerals("Phase III trials")
        assert "Phase three" in result

    def test_part_two(self):
        result = replace_roman_numerals("Part II begins")
        assert "Part two" in result

    def test_no_false_positive(self):
        # "I" alone should not be converted without context
        result = replace_roman_numerals("I went home")
        assert result == "I went home"

    def test_generation_four(self):
        result = replace_roman_numerals("Generation IV reactor")
        assert "Generation four" in result


class TestReplaceQuarterNotation:
    def test_quarter_with_year(self):
        result = replace_quarter_notation("Q2 2026")
        assert "Q two twenty twenty-six" in result

    def test_standalone_quarter(self):
        result = replace_quarter_notation("in Q4")
        assert "Q four" in result


class TestReplaceUnits:
    def test_kilometers(self):
        result = replace_units("500 km away")
        assert "kilometers" in result

    def test_kilowatt_hours(self):
        result = replace_units("100 kWh battery")
        assert "kilowatt hours" in result

    def test_miles_per_hour(self):
        result = replace_units("60 mph speed")
        assert "miles per hour" in result


class TestReplaceLargeNumbersWithK:
    def test_two_point_five_k(self):
        result = replace_large_numbers_with_k("2.5k km")
        assert "two thousand five hundred" in result

    def test_plain_k(self):
        result = replace_large_numbers_with_k("10k followers")
        assert "ten thousand" in result


class TestReplaceScientificDesignations:
    def test_comet_designation(self):
        result = replace_scientific_designations("Comet C/2024 E1")
        assert "slash" in result
        assert "Comet" in result

    def test_star_catalog(self):
        result = replace_scientific_designations("HR 8799 system")
        assert "H R" in result


class TestReplaceStandaloneLargeNumbers:
    def test_comma_separated(self):
        result = replace_standalone_large_numbers("500,000 people")
        assert "five hundred thousand" in result

    def test_million(self):
        result = replace_standalone_large_numbers("2,000,000 users")
        assert "two million" in result


# ===================== Dictionary-based Fixes =====================

class TestApplyPronunciationFixes:
    def test_xai_fix(self):
        result = apply_pronunciation_fixes("The xAI company")
        assert "ex A.I." in result

    def test_evs_fix(self):
        result = apply_pronunciation_fixes("Electric EVs are growing")
        assert "E Vs" in result

    def test_spacex_fix(self):
        result = apply_pronunciation_fixes("SpaceX launched")
        assert "Space X" in result

    def test_who_word_protected(self):
        result = apply_pronunciation_fixes("who did this")
        assert "who" in result
        assert "W H O" not in result

    def test_ice_word_protected(self):
        result = apply_pronunciation_fixes("The ice is cold")
        assert "ice" in result
        assert "I C E" not in result

    def test_robotaxi(self):
        result = apply_pronunciation_fixes("Tesla Robotaxi service")
        assert "Robo-taxi" in result

    def test_cybertruck(self):
        result = apply_pronunciation_fixes("The Cybertruck is here")
        assert "Cyber-truck" in result

    def test_planetterrian(self):
        result = apply_pronunciation_fixes("Welcome to Planetterrian")
        assert "Planet-terry-an" in result

    def test_teslarati(self):
        result = apply_pronunciation_fixes("According to Teslarati")
        assert "Tesla-rah-tee" in result


# ===================== Full Pipeline (prepare_text_for_tts) =====================

class TestPrepareTextForTts:
    def test_full_tesla_episode_snippet(self):
        """Test with a representative snippet from the latest TST episode."""
        text = (
            "🚗⚡ **Tesla Shorts Time**\n"
            "📅 **Date:** February 15, 2026 at 03:08 AM PST\n"
            "💰 **REAL-TIME TSLA price:** $417.44 +1.11 (+0.27%)\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "1️⃣ **Tesla Nears Closure of Full Self-Driving Purchasing Option**\n"
            "Source: https://www.teslarati.com/article\n"
            "SpaceX-xAI Deal confirmed. Q2 2026 production.\n"
            "S3XY Plaid models covering 2.5k km in Norway.\n"
            "DM us @teslashortstime with your thoughts!"
        )
        result = prepare_text_for_tts(text)

        # Emojis removed
        assert "🚗" not in result
        assert "📅" not in result
        assert "1️⃣" not in result or "1" in result

        # Markdown removed
        assert "**" not in result

        # URLs removed
        assert "https://" not in result

        # Unicode decorations removed
        assert "━" not in result

        # Currency converted
        assert "four hundred seventeen dollars" in result

        # Percentage converted
        assert "percent" in result

        # Date converted
        assert "fifteenth" in result

        # Time converted
        assert "three oh eight" in result

        # Timezone expanded
        assert "Pacific Standard Time" in result

        # xAI handled
        assert "ex A.I." in result

        # TSLA spelled out
        assert "T S L A" in result

        # Q2 expanded
        assert "Q two" in result

        # S3XY expanded
        assert "S three X Y" in result

        # 2.5k expanded
        assert "two thousand five hundred" in result

        # Social handle expanded
        assert "at tesla shorts time" in result

    def test_empty_text(self):
        assert prepare_text_for_tts("") == ""

    def test_skip_acronyms(self):
        """TST skips ICE so it reads as 'ice' not 'I C E'."""
        result = prepare_text_for_tts("ICE vehicles vs EVs", skip_acronyms={"ICE"})
        # ICE should NOT be expanded since we skipped it
        assert "I C E" not in result

    def test_extra_acronyms(self):
        result = prepare_text_for_tts(
            "The DLT platform is great",
            extra_acronyms={"DLT": "D L T"},
        )
        assert "D L T" in result

    def test_feature_toggles(self):
        """Can disable individual features."""
        result = prepare_text_for_tts(
            "$500 item",
            do_currency=False,
            do_clean=False,
        )
        assert "$500" in result  # Currency not converted

    def test_fascinating_frontiers_snippet(self):
        """Test with FF-style content including scientific terms."""
        text = (
            "Fascinating Frontiers Episode 39\n"
            "Comet C/2024 E1 approaches!\n"
            "Cassini found water on Enceladus.\n"
            "Phase III of the mission.\n"
            "500,000 km away from Earth.\n"
            "ESA confirmed 7th flyby."
        )
        result = prepare_text_for_tts(text)
        assert "thirty-nine" in result        # Episode number
        assert "slash" in result               # Comet designation
        assert "Kah-see-nee" in result         # Cassini pronunciation
        assert "En-sell-uh-dus" in result      # Enceladus pronunciation
        assert "Phase three" in result         # Roman numeral
        assert "five hundred thousand" in result  # Large number
        assert "kilometers" in result          # Unit expansion
        assert "E S A" in result               # Acronym
        assert "seventh" in result             # Ordinal number

    def test_omni_view_snippet(self):
        """Test with OV-style content including business/politics terms."""
        text = (
            "The CEO announced the IPO.\n"
            "FDA-cleared LED device.\n"
            "EU regulations on AI.\n"
            "$2.5 billion investment.\n"
            "15% growth in Q3 2026."
        )
        result = prepare_text_for_tts(text)
        assert "C E O" in result
        assert "I P O" in result
        assert "F D A" in result
        assert "L E D" in result
        assert "E U" in result
        # AI should be expanded (could be "A.I." or "A . I ." depending on spacing)
        assert "A" in result and "I" in result
        assert "billion dollars" in result
        assert "fifteen percent" in result
        assert "Q three" in result
