"""Video assembly helpers for the YouTube publishing pipeline.

Provides ffmpeg-based builders for two video formats produced from each
podcast episode:

  - :func:`build_long_form_video`  — 1920x1080 (16:9) horizontal MP4
    with the show cover as a still background and an animated audio
    waveform overlay running for the full duration of the episode audio.
  - :func:`build_short_video`     — 1080x1920 (9:16) vertical MP4 with
    a clipped portion of the audio (default 55s, well under the 60s
    YouTube Shorts limit) and the cover scaled-and-cropped to fill.

Both functions share the same encoding profile (libx264 + AAC, faststart)
so uploads are immediately playable on YouTube without a re-mux pass.

The command builders are kept as module-level pure functions so they
can be inspected by ``tests/test_video_commands.py`` without invoking
ffmpeg.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Encoding profile
# ---------------------------------------------------------------------------

# Shared video/audio encoder args. libx264 + yuv420p + faststart is the
# combination YouTube requires for instant playback (the moov atom must
# sit before mdat or the upload triggers a re-process pass).
_VIDEO_ENCODE: List[str] = [
    "-c:v", "libx264",
    "-pix_fmt", "yuv420p",
    "-preset", "medium",
    "-crf", "22",
    "-profile:v", "high",
    "-level", "4.1",
]

_AUDIO_ENCODE: List[str] = [
    "-c:a", "aac",
    "-b:a", "192k",
    "-ar", "44100",
    "-ac", "2",
]


# ---------------------------------------------------------------------------
# Filter graph builders
# ---------------------------------------------------------------------------

def _long_form_filter_graph(width: int = 1920, height: int = 1080,
                            fps: int = 30) -> str:
    """Build the filter_complex graph for a horizontal long-form video.

    The graph composites three layers:

      1. The cover image, scaled to *cover* the 1920x1080 frame (no
         letterboxing) and given a fixed SAR so YouTube doesn't re-encode.
      2. A semi-transparent animated waveform spanning the full width,
         180 px tall, anchored 60 px above the bottom edge.
      3. The original audio passed through unchanged.

    Returns
    -------
    str
        The filter_complex string with three named outputs: ``[bg]``,
        ``[wave]``, ``[v]``.
    """
    return (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,format=yuv420p[bg];"
        f"[1:a]showwaves=s={width}x180:mode=cline:colors=0xFFFFFF:rate={fps},"
        f"format=yuva420p,colorchannelmixer=aa=0.7[wave];"
        f"[bg][wave]overlay=x=0:y=H-h-60:format=auto[v]"
    )


def _short_form_filter_graph(width: int = 1080, height: int = 1920,
                             fps: int = 30) -> str:
    """Build the filter_complex graph for a 9:16 vertical Shorts video.

    Scale-and-crop the cover to fill the vertical frame (square covers
    end up centred), drop a 1080x300 waveform overlay at the vertical
    midpoint, and pass audio through.
    """
    wave_y = (height // 2) - 150  # 300/2 = 150 → centred vertically
    return (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,format=yuv420p[bg];"
        f"[1:a]showwaves=s={width}x300:mode=cline:colors=0xFFFFFF:rate={fps},"
        f"format=yuva420p,colorchannelmixer=aa=0.7[wave];"
        f"[bg][wave]overlay=x=0:y={wave_y}:format=auto[v]"
    )


# ---------------------------------------------------------------------------
# Command builders
# ---------------------------------------------------------------------------

def _long_form_cmd(audio_in: str, cover_in: str, output: str,
                   *, fps: int = 30) -> List[str]:
    """Full ffmpeg command for the long-form 1920x1080 build."""
    return [
        "ffmpeg", "-y", "-threads", "0",
        "-loop", "1", "-framerate", str(fps), "-i", cover_in,
        "-i", audio_in,
        "-filter_complex", _long_form_filter_graph(1920, 1080, fps),
        "-map", "[v]", "-map", "1:a",
        *_VIDEO_ENCODE,
        "-r", str(fps),
        *_AUDIO_ENCODE,
        "-shortest",
        "-movflags", "+faststart",
        output,
    ]


def _short_form_cmd(audio_in: str, cover_in: str, output: str,
                    *, start_offset: float = 0.0,
                    duration: float = 55.0,
                    fps: int = 30) -> List[str]:
    """Full ffmpeg command for the 1080x1920 Shorts build.

    The audio input is clipped via ``-ss`` (input-side seek) before the
    decoder so we only decode the slice we keep. ``-t`` is applied to
    the audio input as well so ``-shortest`` truncates the looped cover
    to match.
    """
    return [
        "ffmpeg", "-y", "-threads", "0",
        "-loop", "1", "-framerate", str(fps), "-i", cover_in,
        "-ss", f"{start_offset:.2f}",
        "-t", f"{duration:.2f}",
        "-i", audio_in,
        "-filter_complex", _short_form_filter_graph(1080, 1920, fps),
        "-map", "[v]", "-map", "1:a",
        *_VIDEO_ENCODE,
        "-r", str(fps),
        *_AUDIO_ENCODE,
        "-shortest",
        "-movflags", "+faststart",
        output,
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_long_form_video(audio_path: Path, cover_path: Path,
                          output_path: Path, *, fps: int = 30) -> Path:
    """Render a 1920x1080 long-form podcast video.

    Parameters
    ----------
    audio_path:
        Path to the final mixed episode MP3 (output of
        :func:`engine.audio.mix_with_music`).
    cover_path:
        Path to the show's static cover image (typically the JPG under
        ``assets/covers/``). Anything ffmpeg can decode works.
    output_path:
        Where to write the MP4. Parent dir must exist.
    fps:
        Frame rate for both the still video stream and the waveform
        animation. 30 is the standard YouTube target; lower values
        produce smaller files but choppier waveforms.

    Returns
    -------
    Path
        ``output_path`` on success.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"audio not found: {audio_path}")
    if not cover_path.exists():
        raise FileNotFoundError(f"cover not found: {cover_path}")

    cmd = _long_form_cmd(str(audio_path), str(cover_path),
                         str(output_path), fps=fps)
    logger.info("Building long-form video → %s", output_path.name)
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path


def build_short_video(audio_path: Path, cover_path: Path,
                      output_path: Path, *,
                      start_offset: float = 0.0,
                      duration: float = 55.0,
                      fps: int = 30) -> Path:
    """Render a 1080x1920 vertical YouTube Shorts video.

    Parameters
    ----------
    audio_path:
        Path to the source audio (usually the same final mixed episode
        MP3 used for long-form). Only the slice from *start_offset* to
        *start_offset + duration* is included.
    cover_path:
        Path to the show's cover image (filled, then cropped to vertical).
    output_path:
        Where to write the MP4.
    start_offset:
        Seconds into the audio where the Short should start. Set to
        ``audio.intro_duration + audio.voice_intro_delay`` so we skip
        the music intro and start on voice.
    duration:
        Length of the short clip in seconds. **Must stay below 60** so
        YouTube classifies the upload as a Short.
    fps:
        Frame rate; same caveats as the long-form builder.

    Returns
    -------
    Path
        ``output_path`` on success.
    """
    if duration >= 60:
        raise ValueError(
            f"Shorts duration must stay below 60s; got {duration}"
        )
    if not audio_path.exists():
        raise FileNotFoundError(f"audio not found: {audio_path}")
    if not cover_path.exists():
        raise FileNotFoundError(f"cover not found: {cover_path}")

    cmd = _short_form_cmd(str(audio_path), str(cover_path),
                          str(output_path),
                          start_offset=start_offset,
                          duration=duration, fps=fps)
    logger.info(
        "Building Shorts video (%.1fs from %.1fs) → %s",
        duration, start_offset, output_path.name,
    )
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path
