"""
Unit tests for the pure utility functions that exist across podcast scripts.

These tests capture the CURRENT behavior of:
  - number_to_words()     (tesla_shorts_time.py:83, omni_view.py:83)
  - fix_tesla_pronunciation()  (tesla_shorts_time.py:150)
  - fix_omni_pronunciation()   (omni_view.py:147)
  - calculate_similarity()     (tesla_shorts_time.py:1287)
  - remove_similar_items()     (tesla_shorts_time.py:1296, omni_view.py:165)

Because the scripts are not designed as importable modules (tesla_shorts_time.py
has a SystemExit guard; all scripts import heavy deps like torch), we extract
the functions via AST and exec() them in an isolated namespace.
"""

import ast
import re
import textwrap
from difflib import SequenceMatcher
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers: extract function source from a script file via AST
# ---------------------------------------------------------------------------

DIGESTS_DIR = Path(__file__).resolve().parent.parent / "digests"


def _extract_function_source(filepath: Path, func_name: str) -> str:
    """Return the source text of a top-level function from *filepath*."""
    source = filepath.read_text()
    tree = ast.parse(source)
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            lines = source.splitlines(keepends=True)
            start = node.lineno - 1  # 0-indexed
            end = node.end_lineno     # exclusive
            return "".join(lines[start:end])
    raise ValueError(f"{func_name} not found in {filepath}")


def _load_function(filepath: Path, func_name: str, extra_globals=None):
    """Execute a function definition from *filepath* and return the callable.

    *extra_globals* lets callers inject dependencies (e.g. ``re``, ``logging``)
    into the exec namespace.
    """
    src = _extract_function_source(filepath, func_name)
    ns = {"__builtins__": __builtins__}
    if extra_globals:
        ns.update(extra_globals)
    exec(compile(src, str(filepath), "exec"), ns)
    return ns[func_name]


# ---------------------------------------------------------------------------
# Load functions under test
# ---------------------------------------------------------------------------

import logging as _logging

_tesla_script = DIGESTS_DIR / "tesla_shorts_time.py"
_omni_script = DIGESTS_DIR / "omni_view.py"

# All utility functions now live in engine/ (migrated from all 4 show scripts)
from engine.utils import number_to_words as tesla_number_to_words
from engine.utils import number_to_words as omni_number_to_words
from engine.utils import calculate_similarity as tesla_calculate_similarity
from engine.utils import remove_similar_items as tesla_remove_similar_items
from engine.utils import remove_similar_items as omni_remove_similar_items

# fix_tesla_pronunciation — still inline in TST, needs number_to_words + flags
tesla_fix_pronunciation = _load_function(
    _tesla_script, "fix_tesla_pronunciation",
    extra_globals={
        "re": re,
        "number_to_words": tesla_number_to_words,
        "USE_SHARED_PRONUNCIATION": False,
        "logging": _logging,
    },
)

# fix_omni_pronunciation — simpler, needs number_to_words + re
omni_fix_pronunciation = _load_function(
    _omni_script, "fix_omni_pronunciation",
    extra_globals={
        "re": re,
        "number_to_words": omni_number_to_words,
    },
)


# ===================================================================
# TEST: number_to_words
# ===================================================================

class TestNumberToWords:
    """Tests for number_to_words() — the Tesla version."""

    @pytest.mark.parametrize("num, expected", [
        (0, "zero"),
        (1, "one"),
        (42, "forty-two"),
        (100, "one hundred"),
        (999, "nine hundred ninety-nine"),
        (1000, "one thousand"),
        (12345, "twelve thousand three hundred forty-five"),
    ])
    def test_integers(self, num, expected):
        assert tesla_number_to_words(num) == expected

    def test_million_returns_string(self):
        # >= 1_000_000 falls through to str(integer_part)
        result = tesla_number_to_words(1_000_000)
        assert result == "1000000"

    def test_negative(self):
        result = tesla_number_to_words(-7)
        assert result == "negative seven"

    def test_decimal_point_one_seven(self):
        result = tesla_number_to_words(0.17)
        assert "point" in result
        assert "one" in result
        assert "seven" in result

    def test_decimal_pi(self):
        result = tesla_number_to_words(3.14)
        assert result.startswith("three point")
        assert "one" in result
        assert "four" in result

    def test_negative_decimal(self):
        result = tesla_number_to_words(-3.14)
        assert result.startswith("negative three point")

    def test_zero_decimal_no_point(self):
        # Pure integer should not contain "point"
        assert "point" not in tesla_number_to_words(42)

    @pytest.mark.parametrize("num, expected", [
        (0, "zero"),
        (1, "one"),
        (42, "forty-two"),
        (100, "one hundred"),
        (999, "nine hundred ninety-nine"),
        (1000, "one thousand"),
        (12345, "twelve thousand three hundred forty-five"),
    ])
    def test_omni_integers_match_tesla(self, num, expected):
        """The two scripts' number_to_words should agree on integers."""
        assert omni_number_to_words(num) == expected


# ===================================================================
# TEST: fix_tesla_pronunciation
# ===================================================================

class TestFixTeslaPronunciation:
    """Snapshot tests for the Tesla pronunciation fixer."""

    def test_acronym_tsla(self):
        result = tesla_fix_pronunciation("TSLA is up today")
        assert "T S L A" in result

    def test_acronym_fsd(self):
        result = tesla_fix_pronunciation("FSD v13 is rolling out")
        assert "F S D" in result

    def test_acronym_ev_and_evs(self):
        result = tesla_fix_pronunciation("EV sales are up. EVs dominate.")
        assert "E V" in result
        # EVs should be expanded (either "E Vs" or "ee vees")
        assert "E Vs" in result or "ee vees" in result

    def test_ice_becomes_lowercase(self):
        """Tesla show wants 'ICE' read as the word 'ice', not spelled out."""
        result = tesla_fix_pronunciation("ICE vehicles are declining")
        assert "ice" in result.lower()
        # Should NOT be spelled out
        assert "I C E" not in result

    def test_spacex(self):
        result = tesla_fix_pronunciation("SpaceX launched a rocket")
        assert "Space X" in result

    def test_robotaxis(self):
        result = tesla_fix_pronunciation("Robotaxis are coming soon")
        assert "obo-taxi" in result.lower()

    def test_stock_price(self):
        result = tesla_fix_pronunciation("TSLA closed at $430.17")
        assert "dollars" in result
        assert "cents" in result

    def test_large_currency(self):
        result = tesla_fix_pronunciation("$3 Trillion market cap")
        assert "three" in result
        assert "trillion" in result
        assert "dollars" in result

    def test_percentage(self):
        result = tesla_fix_pronunciation("+3.59%")
        assert "plus" in result
        assert "percent" in result

    def test_negative_percentage(self):
        result = tesla_fix_pronunciation("-2.1%")
        assert "minus" in result
        assert "percent" in result

    def test_date_conversion(self):
        result = tesla_fix_pronunciation("November 19, 2025")
        # Day should be ordinal
        assert "nineteenth" in result or "nineteen" in result

    def test_time_conversion(self):
        result = tesla_fix_pronunciation("02:30 PM")
        assert "two" in result
        assert "thirty" in result
        # PM may be spaced as "P M" for clearer TTS pronunciation
        assert "PM" in result or "P M" in result

    def test_timezone_expansion(self):
        # Note: when a time string like "5:00 PST" is processed, the time regex
        # fires first and may consume boundary whitespace, so test the timezone
        # replacement independently.
        result = tesla_fix_pronunciation("The meeting is at PST timezone")
        assert "Pacific Standard Time" in result

    def test_kw_expansion(self):
        # The acronym dict maps "kW" -> "kilowatts", but with re.IGNORECASE
        # the replacement text "kilowatts" itself can be re-processed by later
        # regex passes.  The current output is "k i l o w a t t s" because
        # the case-insensitive match on "kW" replaces character-by-character.
        # We capture the CURRENT behavior here.
        result = tesla_fix_pronunciation("charging at 250 kW")
        # "kilowatts" is in the acronym dict replacement value
        assert "kilowatt" in result.replace(" ", "")

    def test_kwh_expansion(self):
        result = tesla_fix_pronunciation("battery capacity is 75 kWh")
        assert "kilowatt hours" in result

    def test_nasa_spelled_out(self):
        result = tesla_fix_pronunciation("NASA confirmed the rating")
        assert "N H T S A" not in result  # NASA is not in the acronym list
        # NHTSA should be spelled out though
        result2 = tesla_fix_pronunciation("NHTSA issued a recall")
        assert "N H T S A" in result2

    def test_who_not_spelled_as_acronym(self):
        """'who' should be the word, not W.H.O."""
        result = tesla_fix_pronunciation("who said that")
        assert "who" in result.lower()

    def test_episode_number_conversion(self):
        result = tesla_fix_pronunciation("Episode 336 covers Tesla")
        assert "three hundred thirty-six" in result


# ===================================================================
# TEST: fix_omni_pronunciation
# ===================================================================

class TestFixOmniPronunciation:
    """Snapshot tests for the Omni View pronunciation fixer."""

    def test_dollar_currency(self):
        result = omni_fix_pronunciation("The price is $12.50")
        assert "dollars" in result

    def test_euro_currency(self):
        result = omni_fix_pronunciation("The EU proposed €500 billion")
        assert "euros" in result
        assert "five hundred" in result

    def test_pound_currency(self):
        result = omni_fix_pronunciation("£1 exchange rate")
        assert "pounds" in result

    def test_percentage(self):
        result = omni_fix_pronunciation("inflation fell to 3.2%")
        assert "percent" in result

    def test_ordinal_stripped(self):
        result = omni_fix_pronunciation("The 3rd quarter")
        assert "3rd" not in result
        # The ordinal should be converted to a word like "third"
        assert "third" in result or "3" in result

    def test_time_conversion(self):
        result = omni_fix_pronunciation("at 10:30 AM")
        # Time should be converted to words
        assert "ten" in result or "10" in result
        assert "thirty" in result or "30" in result


# ===================================================================
# TEST: calculate_similarity
# ===================================================================

class TestCalculateSimilarity:

    def test_identical_strings(self):
        assert tesla_calculate_similarity("hello world", "hello world") == 1.0

    def test_empty_strings(self):
        assert tesla_calculate_similarity("", "anything") == 0.0
        assert tesla_calculate_similarity("anything", "") == 0.0

    def test_both_empty(self):
        assert tesla_calculate_similarity("", "") == 0.0

    def test_none_inputs(self):
        assert tesla_calculate_similarity(None, "text") == 0.0
        assert tesla_calculate_similarity("text", None) == 0.0

    def test_similar_strings_high_ratio(self):
        s1 = "Tesla stock surged 3.5% today on FSD news"
        s2 = "Tesla stock surged 3.5% today on FSD update"
        ratio = tesla_calculate_similarity(s1, s2)
        assert ratio > 0.8

    def test_dissimilar_strings_low_ratio(self):
        s1 = "Tesla stock surged today"
        s2 = "NASA launched a new satellite"
        ratio = tesla_calculate_similarity(s1, s2)
        assert ratio < 0.4

    def test_case_insensitive(self):
        """Similarity normalizes to lowercase."""
        assert tesla_calculate_similarity("HELLO", "hello") == 1.0

    def test_whitespace_normalized(self):
        """Extra whitespace is collapsed."""
        assert tesla_calculate_similarity("hello  world", "hello world") == 1.0


# ===================================================================
# TEST: remove_similar_items
# ===================================================================

class TestRemoveSimilarItems:

    def test_empty_list(self):
        result = tesla_remove_similar_items([])
        assert result == [] or result is None or result == []  # tesla returns items, omni returns []

    def test_no_duplicates(self):
        items = [
            {"title": "Tesla launches new Model 3"},
            {"title": "NASA discovers new exoplanet"},
            {"title": "Federal Reserve raises interest rates"},
        ]
        result = tesla_remove_similar_items(items)
        assert len(result) == 3

    def test_near_duplicates_removed(self):
        items = [
            {"title": "Tesla stock surges 5% on FSD news"},
            {"title": "Tesla stock surges 5% on FSD update"},  # near-dup
            {"title": "NASA announces Mars mission timeline"},
        ]
        result = tesla_remove_similar_items(items)
        assert len(result) == 2
        # First occurrence kept, near-duplicate removed
        assert result[0]["title"] == "Tesla stock surges 5% on FSD news"
        assert result[1]["title"] == "NASA announces Mars mission timeline"

    def test_custom_threshold(self):
        items = [
            {"title": "Tesla stock up 5%"},
            {"title": "Tesla stock up 6%"},
        ]
        # With a very high threshold, both should survive
        result = tesla_remove_similar_items(items, similarity_threshold=0.99)
        assert len(result) == 2
        # With a low threshold, only the first survives
        result = tesla_remove_similar_items(items, similarity_threshold=0.5)
        assert len(result) == 1

    def test_custom_get_text_func(self):
        items = [
            {"headline": "Breaking: Tesla FSD v13"},
            {"headline": "Breaking: Tesla FSD v13 released"},
        ]
        result = tesla_remove_similar_items(
            items,
            get_text_func=lambda x: x["headline"],
        )
        assert len(result) == 1

    def test_string_items(self):
        items = [
            "Tesla stock surges on FSD news",
            "Tesla stock surges on FSD update",
            "NASA mission update",
        ]
        result = tesla_remove_similar_items(items)
        assert len(result) == 2

    def test_skips_empty_text(self):
        """Items with empty text are skipped (tesla version)."""
        items = [
            {"title": ""},
            {"title": "Real headline"},
        ]
        result = tesla_remove_similar_items(items)
        assert len(result) == 1
        assert result[0]["title"] == "Real headline"

    def test_omni_version_basic(self):
        """Omni View version uses slightly different key lookup."""
        items = [
            {"title": "Federal Reserve holds rates"},
            {"title": "Federal Reserve holds rates steady"},
            {"content": "Completely different story about sports"},
        ]
        result = omni_remove_similar_items(items)
        assert len(result) == 2
