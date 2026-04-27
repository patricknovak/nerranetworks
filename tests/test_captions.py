"""Tests for the transcript-JSON → SRT converter used by the YouTube
caption burn-in pipeline."""

import json
from pathlib import Path

import pytest

from engine.captions import (
    _format_srt_timestamp,
    _wrap_caption_line,
    find_transcript_for_episode,
    transcript_to_srt,
)


def test_srt_timestamp_format():
    assert _format_srt_timestamp(0.0) == "00:00:00,000"
    assert _format_srt_timestamp(1.5) == "00:00:01,500"
    assert _format_srt_timestamp(75.123) == "00:01:15,123"
    assert _format_srt_timestamp(3725.999) == "01:02:05,999"
    # Negatives clamp to zero rather than emitting "-00:..." which
    # libass refuses to parse.
    assert _format_srt_timestamp(-1.0) == "00:00:00,000"


def test_wrap_caption_line_short_text_unchanged():
    assert _wrap_caption_line("Short caption.") == "Short caption."


def test_wrap_caption_line_breaks_at_word_boundary():
    out = _wrap_caption_line(
        "This is a fairly long caption that needs wrapping",
        max_chars=20,
    )
    lines = out.split("\n")
    assert len(lines) >= 2
    # No line should split a word in the middle.
    for line in lines:
        assert " " in line or len(line) <= 20


def test_transcript_to_srt_basic(tmp_path: Path):
    transcript = {
        "language": "en",
        "duration": 30.0,
        "segments": [
            {"start": 0.0, "end": 2.5, "text": "Hello world"},
            {"start": 3.0, "end": 6.5, "text": "This is a test caption"},
            # Sub-min-duration cue should be filtered out.
            {"start": 7.0, "end": 7.05, "text": "blip"},
            {"start": 8.0, "end": 11.0, "text": "Final cue"},
        ],
    }
    transcript_path = tmp_path / "ep_transcript.json"
    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")

    srt_path = tmp_path / "ep.srt"
    result = transcript_to_srt(transcript_path, srt_path)

    assert result == srt_path
    content = srt_path.read_text(encoding="utf-8")

    # Three usable cues (the sub-min-duration one was dropped).
    assert content.count(" --> ") == 3
    assert "Hello world" in content
    assert "Final cue" in content
    assert "blip" not in content
    # Cues are 1-indexed.
    assert content.startswith("1\n")


def test_transcript_to_srt_skips_blank_text(tmp_path: Path):
    transcript = {
        "segments": [
            {"start": 0.0, "end": 2.0, "text": ""},
            {"start": 2.5, "end": 4.0, "text": "   "},
            {"start": 5.0, "end": 8.0, "text": "Real caption"},
        ],
    }
    transcript_path = tmp_path / "t.json"
    transcript_path.write_text(json.dumps(transcript), encoding="utf-8")
    srt_path = tmp_path / "t.srt"
    transcript_to_srt(transcript_path, srt_path)
    content = srt_path.read_text(encoding="utf-8")
    assert content.count(" --> ") == 1
    assert "Real caption" in content


def test_transcript_to_srt_handles_unicode(tmp_path: Path):
    """Russian transcripts must round-trip through UTF-8 unchanged."""
    transcript = {
        "language": "ru",
        "segments": [
            {"start": 0.0, "end": 2.0, "text": "Привет, Русский!"},
        ],
    }
    transcript_path = tmp_path / "ru.json"
    transcript_path.write_text(json.dumps(transcript, ensure_ascii=False),
                               encoding="utf-8")
    srt_path = tmp_path / "ru.srt"
    transcript_to_srt(transcript_path, srt_path)
    assert "Привет, Русский!" in srt_path.read_text(encoding="utf-8")


def test_transcript_to_srt_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        transcript_to_srt(tmp_path / "missing.json", tmp_path / "out.srt")


def test_find_transcript_for_episode(tmp_path: Path):
    digests = tmp_path / "digests"
    digests.mkdir()
    target = digests / "TST_Ep042_20260427_transcript.json"
    target.write_text("{}", encoding="utf-8")

    found = find_transcript_for_episode(digests, "TST", 42, "20260427")
    assert found == target

    missing = find_transcript_for_episode(digests, "TST", 99, "20260427")
    assert missing is None
