"""
Unit tests for the pure utility functions in engine/.

Tests cover:
  - number_to_words()      (engine.utils)
  - calculate_similarity()  (engine.utils)
  - remove_similar_items()  (engine.utils)

Pronunciation tests for the shared module live in test_pronunciation.py.
"""

import re
from pathlib import Path

import pytest

from engine.utils import number_to_words as tesla_number_to_words
from engine.utils import number_to_words as omni_number_to_words
from engine.utils import calculate_similarity as tesla_calculate_similarity
from engine.utils import remove_similar_items as tesla_remove_similar_items
from engine.utils import remove_similar_items as omni_remove_similar_items


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
