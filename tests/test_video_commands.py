"""Tests that pin down the EXACT ffmpeg commands :mod:`engine.video` emits.

We don't actually run ffmpeg — we just verify the command lists. Same
pattern as :mod:`tests.test_audio_commands`. These act as a regression
fence: any future tweak to the long-form or Shorts video pipeline will
trip these tests, forcing the change to be intentional.
"""

import pytest

from engine.video import (
    _AUDIO_ENCODE,
    _VIDEO_ENCODE,
    _long_form_cmd,
    _long_form_filter_graph,
    _short_form_cmd,
    _short_form_filter_graph,
    build_long_form_video,
    build_short_video,
)


# ---------------------------------------------------------------------------
# Filter graph shape
# ---------------------------------------------------------------------------

def test_long_form_filter_graph_default_resolution():
    graph = _long_form_filter_graph()
    assert "scale=1920:1080" in graph
    assert "showwaves=s=1920x180" in graph
    assert "[bg]" in graph and "[wave]" in graph and "[v]" in graph
    # waveform overlay sits 60px above the bottom edge
    assert "y=H-h-60" in graph


def test_short_form_filter_graph_default_resolution():
    graph = _short_form_filter_graph()
    assert "scale=1080:1920" in graph
    assert "showwaves=s=1080x300" in graph
    # 1920/2 - 150 = 810 — waveform centered vertically
    assert "y=810" in graph


# ---------------------------------------------------------------------------
# Long-form command shape
# ---------------------------------------------------------------------------

def test_long_form_cmd_structure():
    cmd = _long_form_cmd("voice.mp3", "cover.jpg", "out.mp4")

    # Two inputs: looped cover image, then audio.
    assert cmd[:2] == ["ffmpeg", "-y"]
    assert "-loop" in cmd and cmd[cmd.index("-loop") + 1] == "1"
    # Two -i flags for the two inputs
    assert cmd.count("-i") == 2
    # Filter graph is supplied via -filter_complex
    fc_idx = cmd.index("-filter_complex")
    graph = cmd[fc_idx + 1]
    assert "[bg][wave]overlay" in graph
    # Map the composited video and the second input's audio
    assert "-map" in cmd
    map_indices = [i for i, x in enumerate(cmd) if x == "-map"]
    map_values = [cmd[i + 1] for i in map_indices]
    assert "[v]" in map_values
    assert "1:a" in map_values
    # Encoding profile + faststart + shortest are present
    for token in ("-shortest", "-movflags", "+faststart"):
        assert token in cmd
    for token in _VIDEO_ENCODE:
        assert token in cmd
    for token in _AUDIO_ENCODE:
        assert token in cmd
    assert cmd[-1] == "out.mp4"


def test_long_form_cmd_respects_fps():
    cmd = _long_form_cmd("voice.mp3", "cover.jpg", "out.mp4", fps=24)
    # -framerate is set on the looped image input *before* -i
    assert cmd[cmd.index("-framerate") + 1] == "24"
    # -r controls the output frame rate
    assert cmd[cmd.index("-r") + 1] == "24"
    # Filter graph picks up the same fps for the waveform animation
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "rate=24" in graph


# ---------------------------------------------------------------------------
# Shorts command shape
# ---------------------------------------------------------------------------

def test_short_form_cmd_clips_audio():
    cmd = _short_form_cmd(
        "voice.mp3", "cover.jpg", "short.mp4",
        start_offset=15.0, duration=55.0,
    )
    # -ss / -t are applied to the audio input (they appear AFTER the
    # cover input's -i but BEFORE the audio input's -i).
    ss_idx = cmd.index("-ss")
    t_idx = cmd.index("-t")
    assert cmd[ss_idx + 1] == "15.00"
    assert cmd[t_idx + 1] == "55.00"
    # Two -i flags: cover then audio.
    i_indices = [i for i, x in enumerate(cmd) if x == "-i"]
    assert len(i_indices) == 2
    # Audio input must come after -ss/-t.
    assert i_indices[1] > t_idx
    # Filter graph references the vertical Shorts geometry.
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "scale=1080:1920" in graph
    assert "showwaves=s=1080x300" in graph
    assert cmd[-1] == "short.mp4"


def test_short_form_rejects_60s_duration(tmp_path):
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"\x00")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\x00")
    out = tmp_path / "short.mp4"
    with pytest.raises(ValueError, match="below 60s"):
        build_short_video(audio, cover, out, duration=60.0)


def test_short_form_accepts_under_60s(tmp_path, monkeypatch):
    """Shorts under 60s should pass validation; we don't actually run ffmpeg."""
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"\x00")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\x00")
    out = tmp_path / "short.mp4"

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class _R:
            returncode = 0
        return _R()

    monkeypatch.setattr("engine.video.subprocess.run", fake_run)
    build_short_video(audio, cover, out, duration=55.0, start_offset=10.0)
    assert captured["cmd"][0] == "ffmpeg"
    assert "55.00" in captured["cmd"]


# ---------------------------------------------------------------------------
# Public API guards
# ---------------------------------------------------------------------------

def test_build_long_form_video_requires_audio(tmp_path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\x00")
    with pytest.raises(FileNotFoundError, match="audio not found"):
        build_long_form_video(tmp_path / "missing.mp3", cover, tmp_path / "out.mp4")


def test_build_long_form_video_requires_cover(tmp_path):
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"\x00")
    with pytest.raises(FileNotFoundError, match="cover not found"):
        build_long_form_video(audio, tmp_path / "missing.jpg", tmp_path / "out.mp4")
