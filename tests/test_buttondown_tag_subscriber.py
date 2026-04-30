"""Tests for the Buttondown subscriber tagging script.

The script lives under ``scripts/`` rather than ``engine/`` so we
import it via the path. We exercise the pure helpers — the HTTP
calls themselves are not tested here (they're guarded by a
``BUTTONDOWN_API_KEY`` env var the test suite never has).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import buttondown_tag_subscriber as bts  # noqa: E402  (path manipulation needed)


# ---------------------------------------------------------------------------
# Tag validity
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tag", [
    "Tesla Shorts Time",
    "Privet Russian",
    "Finansy Prosto",
    "ABC123",
    "a",                     # one char, valid
    "1",                     # one digit, valid
    "Tesla — 2026",          # mixed but has ASCII letters
])
def test_valid_buttondown_tag_accepts_with_ascii_alphanum(tag):
    assert bts._is_valid_buttondown_tag(tag) is True


@pytest.mark.parametrize("tag", [
    "Привет, Русский!",      # all Cyrillic + punctuation
    "Финансы Просто",        # all Cyrillic
    "!!!",                   # punctuation only
    "—",                     # em-dash only
    "",                      # empty
])
def test_valid_buttondown_tag_rejects_no_ascii_alphanum(tag):
    assert bts._is_valid_buttondown_tag(tag) is False


# ---------------------------------------------------------------------------
# YAML tag loader
# ---------------------------------------------------------------------------

def test_load_show_tags_returns_only_ascii_friendly():
    """All shipped show tags should pass Buttondown's validator."""
    tags = bts._load_show_tags()
    assert tags, "expected at least one show tag"
    invalid = {
        slug: tag for slug, tag in tags.items()
        if not bts._is_valid_buttondown_tag(tag)
    }
    assert not invalid, f"these tags would be rejected by Buttondown: {invalid}"


def test_load_show_tags_includes_russian_shows_with_ascii():
    tags = bts._load_show_tags()
    # Russian shows have ASCII transliterations — verify they're set.
    assert tags.get("privet_russian") == "Privet Russian"
    assert tags.get("finansy_prosto") == "Finansy Prosto"
