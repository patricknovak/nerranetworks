"""Tests that pin down the EXACT ffmpeg commands :mod:`engine.video` emits.

We don't actually run ffmpeg — we just verify the command lists. Same
pattern as :mod:`tests.test_audio_commands`. These act as a regression
fence: any future tweak to the long-form or Shorts video pipeline
will trip these tests, forcing the change to be intentional.

The tests also pin the keyframe-spacing args (``-g``, ``-keyint_min``,
``-sc_threshold``, ``-force_key_frames``) — without those, the
long-form MP4 has only one keyframe at t=0 and YouTube's transcoder
serves an unplayable rendition.
"""

from pathlib import Path

import pytest

from engine.video import (
    _AUDIO_ENCODE,
    _VIDEO_ENCODE,
    _drawtext_escape,
    _long_form_cmd,
    _long_form_filter_graph,
    _make_brand_pill,
    _short_form_cmd,
    _short_form_filter_graph,
    _wrap_caption,
    build_long_form_video,
    build_short_video,
)


# ---------------------------------------------------------------------------
# Encoder profile — keyframe args are the playback fix
# ---------------------------------------------------------------------------

def test_video_encode_profile_includes_keyframe_args():
    """``-g``, ``-keyint_min``, ``-sc_threshold`` and
    ``-force_key_frames`` must all be present.

    Without these, x264 sees the looped cover as one big static
    scene, emits a single IDR at t=0, and YouTube's transcoder
    rejects the rendition with "video can't play".
    """
    assert "-g" in _VIDEO_ENCODE
    assert _VIDEO_ENCODE[_VIDEO_ENCODE.index("-g") + 1] == "60"
    assert "-keyint_min" in _VIDEO_ENCODE
    assert _VIDEO_ENCODE[_VIDEO_ENCODE.index("-keyint_min") + 1] == "60"
    assert "-sc_threshold" in _VIDEO_ENCODE
    assert _VIDEO_ENCODE[_VIDEO_ENCODE.index("-sc_threshold") + 1] == "0"
    assert "-force_key_frames" in _VIDEO_ENCODE
    fkf_value = _VIDEO_ENCODE[_VIDEO_ENCODE.index("-force_key_frames") + 1]
    assert "expr:gte(t,n_forced*2)" in fkf_value


# ---------------------------------------------------------------------------
# Long-form filter graph — zoompan + showcqt + brand + disclosure
# ---------------------------------------------------------------------------

def test_long_form_filter_graph_uses_zoompan_and_showcqt():
    graph = _long_form_filter_graph()
    # Ken Burns zoom on the cover.
    assert "zoompan" in graph
    # Audio-reactive visualization (replaces the static-image
    # showwaves of the original implementation).
    assert "showcqt" in graph
    # Brand pill is overlaid (third input).
    assert "[2:v]" in graph and "format=rgba" in graph
    # 25%-black tint band sits underneath the visualization.
    assert "drawbox" in graph and "color=black@0.25" in graph
    # First-4s AI-disclosure burn-in.
    assert "drawtext" in graph
    assert r"enable='between(t,0,4)'" in graph
    assert "AI-narrated content" in graph
    # Final output label is [v].
    assert graph.endswith("[v]")


def test_long_form_filter_graph_respects_fps():
    graph = _long_form_filter_graph(fps=24)
    # Both the visualization and zoompan honour the requested fps.
    assert "fps=24" in graph


# ---------------------------------------------------------------------------
# Short-form filter graph
# ---------------------------------------------------------------------------

def test_short_form_filter_graph_uses_showcqt_and_vertical_dims():
    graph = _short_form_filter_graph()
    assert "showcqt" in graph
    assert "scale=1080:1920" in graph
    # Brand pill is anchored top-right (W-w-24).
    assert "x=W-w-24:y=24" in graph
    assert graph.endswith("[v]")


def test_short_form_filter_graph_with_hook_burns_caption():
    graph = _short_form_filter_graph(
        hook="Tesla just unveiled a Virtual Queue for Superchargers."
    )
    assert "drawtext" in graph
    # Hook caption shows for the first 3s only.
    assert r"enable='between(t,0,3)'" in graph
    # Some text from the hook appears (escaped) in the graph.
    assert "Tesla" in graph
    assert graph.endswith("[v]")


def test_short_form_filter_graph_without_hook_omits_caption():
    graph = _short_form_filter_graph(hook=None)
    # No first-3s caption when hook isn't provided.
    assert "between(t,0,3)" not in graph
    # But the brand pill + visualization still produce the [v] output.
    assert graph.endswith("[v]")


# ---------------------------------------------------------------------------
# Long-form command shape
# ---------------------------------------------------------------------------

def test_long_form_cmd_structure():
    cmd = _long_form_cmd("voice.mp3", "cover.jpg", "brand.png", "out.mp4")

    # Three inputs: cover (looped), audio, brand pill (looped).
    assert cmd[:2] == ["ffmpeg", "-y"]
    assert cmd.count("-loop") == 2  # cover + brand
    assert cmd.count("-i") == 3
    # filter_complex contains all the new filters.
    fc_idx = cmd.index("-filter_complex")
    graph = cmd[fc_idx + 1]
    assert "zoompan" in graph
    assert "showcqt" in graph
    assert "[bgviz][brand]overlay" in graph
    # Map composited video and audio.
    map_indices = [i for i, x in enumerate(cmd) if x == "-map"]
    map_values = [cmd[i + 1] for i in map_indices]
    assert "[v]" in map_values
    assert "1:a" in map_values
    # Encoding + container args present.
    for token in ("-shortest", "-movflags", "+faststart"):
        assert token in cmd
    for token in _VIDEO_ENCODE:
        assert token in cmd
    for token in _AUDIO_ENCODE:
        assert token in cmd
    assert cmd[-1] == "out.mp4"


def test_long_form_cmd_respects_fps():
    cmd = _long_form_cmd("voice.mp3", "cover.jpg", "brand.png",
                         "out.mp4", fps=24)
    # -framerate is set on each looped image input *before* its -i.
    framerate_indices = [i for i, x in enumerate(cmd) if x == "-framerate"]
    assert len(framerate_indices) == 2
    for idx in framerate_indices:
        assert cmd[idx + 1] == "24"
    # -r controls the output frame rate.
    assert cmd[cmd.index("-r") + 1] == "24"


# ---------------------------------------------------------------------------
# Shorts command shape
# ---------------------------------------------------------------------------

def test_short_form_cmd_clips_audio():
    cmd = _short_form_cmd(
        "voice.mp3", "cover.jpg", "brand.png", "short.mp4",
        start_offset=15.0, duration=55.0,
    )
    # -ss / -t are applied to the audio input (between cover -i and audio -i).
    ss_idx = cmd.index("-ss")
    t_idx = cmd.index("-t")
    assert cmd[ss_idx + 1] == "15.00"
    assert cmd[t_idx + 1] == "55.00"
    # Three -i flags: cover, audio, brand.
    i_indices = [i for i, x in enumerate(cmd) if x == "-i"]
    assert len(i_indices) == 3
    # Audio input must come after -ss/-t.
    assert i_indices[1] > t_idx
    # Two looped image inputs (cover + brand pill); audio is not looped.
    assert cmd.count("-loop") == 2
    # Filter graph references vertical Shorts geometry.
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "scale=1080:1920" in graph
    assert "showcqt" in graph
    assert cmd[-1] == "short.mp4"


def test_short_form_cmd_threads_hook_into_filter_graph():
    cmd = _short_form_cmd(
        "voice.mp3", "cover.jpg", "brand.png", "short.mp4",
        start_offset=10.0, duration=55.0,
        hook="A short headline",
    )
    graph = cmd[cmd.index("-filter_complex") + 1]
    assert "drawtext" in graph
    assert "A short headline" in graph
    assert r"enable='between(t,0,3)'" in graph


def test_short_form_rejects_60s_duration(tmp_path):
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"\x00")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\x00")
    out = tmp_path / "short.mp4"
    with pytest.raises(ValueError, match="below 60s"):
        build_short_video(audio, cover, out, duration=60.0)


def test_short_form_accepts_under_60s(tmp_path, monkeypatch):
    """Shorts under 60s pass validation. We don't run ffmpeg — we
    capture the command and assert its shape."""
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
    build_short_video(audio, cover, out, duration=55.0,
                      start_offset=10.0, hook="Test headline")
    assert captured["cmd"][0] == "ffmpeg"
    assert "55.00" in captured["cmd"]
    # Brand pill PNG should have been generated alongside the output.
    brand_pill = out.parent / "_brand_pill.png"
    assert brand_pill.exists()


# ---------------------------------------------------------------------------
# Public API guards
# ---------------------------------------------------------------------------

def test_build_long_form_video_requires_audio(tmp_path):
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\x00")
    with pytest.raises(FileNotFoundError, match="audio not found"):
        build_long_form_video(tmp_path / "missing.mp3", cover,
                              tmp_path / "out.mp4")


def test_build_long_form_video_requires_cover(tmp_path):
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"\x00")
    with pytest.raises(FileNotFoundError, match="cover not found"):
        build_long_form_video(audio, tmp_path / "missing.jpg",
                              tmp_path / "out.mp4")


# ---------------------------------------------------------------------------
# Brand pill PNG generation
# ---------------------------------------------------------------------------

def test_make_brand_pill_creates_png(tmp_path):
    target = tmp_path / "_brand_pill.png"
    assert not target.exists()
    result = _make_brand_pill(target)
    assert result == target
    assert target.exists()
    # Sanity: PNG signature is 8 bytes \x89PNG\r\n\x1a\n.
    with open(target, "rb") as f:
        assert f.read(8) == b"\x89PNG\r\n\x1a\n"


def test_make_brand_pill_is_idempotent(tmp_path):
    """Second call should reuse the cached file (not rewrite it)."""
    target = tmp_path / "_brand_pill.png"
    _make_brand_pill(target)
    first_mtime = target.stat().st_mtime_ns
    # Touch a marker so we'd notice if Pillow re-wrote.
    second = _make_brand_pill(target)
    assert second == target
    assert target.stat().st_mtime_ns == first_mtime


def test_build_long_form_video_generates_brand_pill(tmp_path, monkeypatch):
    """``build_long_form_video`` should generate the brand pill on
    first call so the ffmpeg command can reference it."""
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"\x00")
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\x00")
    out = tmp_path / "out.mp4"

    monkeypatch.setattr("engine.video.subprocess.run",
                        lambda cmd, **kwargs: type("R", (), {"returncode": 0})())
    build_long_form_video(audio, cover, out)
    assert (out.parent / "_brand_pill.png").exists()


# ---------------------------------------------------------------------------
# drawtext escaping
# ---------------------------------------------------------------------------

def test_drawtext_escape_handles_metacharacters():
    # Colons are option separators; backslashes, single quotes, and
    # percent signs are drawtext metachars.
    assert _drawtext_escape("It's 5:30 PM (50% off)") == \
        r"It\'s 5\:30 PM (50\% off)"
    assert _drawtext_escape("path\\to") == "path\\\\to"


# ---------------------------------------------------------------------------
# Caption wrapping for Shorts
# ---------------------------------------------------------------------------

def test_wrap_caption_breaks_long_text():
    out = _wrap_caption(
        "Tesla just unveiled a Virtual Queue for Superchargers.",
        max_chars_per_line=22,
    )
    lines = out.split("\n")
    assert all(len(line) <= 26 for line in lines)  # small slack for greedy wrap
    assert len(lines) <= 3


def test_wrap_caption_short_text_unchanged():
    assert _wrap_caption("Short headline.") == "Short headline."


def test_wrap_caption_empty_returns_empty():
    assert _wrap_caption("") == ""
