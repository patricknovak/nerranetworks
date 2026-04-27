"""Video assembly helpers for the YouTube publishing pipeline.

Two builders share one visual recipe so every show looks like part of
the same network without per-show artwork. The recipe:

  - **Background**: the show cover image, scaled-and-cropped to fill
    the frame; long-form gets a slow Ken Burns zoom (1.00 → 1.08 over
    the audio), Shorts stay static (55s of zoom looks frenetic on
    mobile).
  - **Tint band**: 25% black overlay sits underneath the visualization
    so it reads against any cover.
  - **Visualization**: ``showcqt`` (constant-Q transform) burned in —
    the colorful music-bar look you see on Lofi Girl / Spotify Canvas.
    Inherently dynamic frame-by-frame, audio-reactive, and works for
    speech and music alike.
  - **Brand pill**: a small ``Nerra Network · AI-narrated`` pill PNG
    (rendered once with Pillow per work-dir, then reused) overlaid
    top-left on long-form / top-right on Shorts.
  - **First-seconds burn-in**: long-form fades in/out a centered
    "AI-narrated content · Editorial by Nerra Network" line for the
    first 4s. Shorts (when given a hook headline) burn the headline
    for the first 3s so the scrolling viewer sees the topic before
    deciding to stay.

The encoder profile uses ``-g 60 -keyint_min 60 -sc_threshold 0
-force_key_frames`` to force a keyframe every 2s. Without this, x264
sees redundant input frames and produces a single keyframe at t=0,
which made YouTube's transcoder reject the long-form rendition.

The command builders are pure functions (no subprocess) so unit tests
in ``tests/test_video_commands.py`` can inspect them without a real
ffmpeg install.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Encoding profile
# ---------------------------------------------------------------------------

# libx264 + yuv420p + faststart is what YouTube wants for instant
# playback (moov atom before mdat). The keyframe args below are what
# fixes the original "video can't play" bug — without them, x264 sees
# the looped cover input as one big static scene and emits a single
# IDR at t=0, producing an MP4 the YouTube transcoder either rejects
# or serves as un-seekable. Forcing a keyframe every 2s is cheap (the
# zoompan + showcqt motion gives x264 actual change to compress) and
# matches what handbrake/Handbrake-Web defaults use for streaming.
_VIDEO_ENCODE: List[str] = [
    "-c:v", "libx264",
    "-pix_fmt", "yuv420p",
    "-preset", "medium",
    "-crf", "22",
    "-profile:v", "high",
    "-level", "4.1",
    "-g", "60",
    "-keyint_min", "60",
    "-sc_threshold", "0",
    "-force_key_frames", "expr:gte(t,n_forced*2)",
]

_AUDIO_ENCODE: List[str] = [
    "-c:a", "aac",
    "-b:a", "192k",
    "-ar", "44100",
    "-ac", "2",
]


# ---------------------------------------------------------------------------
# Font + drawtext helpers
# ---------------------------------------------------------------------------

# DejaVu ships on Ubuntu / GitHub Actions runners and includes glyphs
# for the en-dot, em-dash, and Cyrillic so it works for English and
# Russian shows alike.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


def _find_font() -> str:
    """Return the path of an installed bold sans-serif font.

    Falls through a list of common platform paths. If none exist we
    return the first candidate anyway — ffmpeg will fail loudly with
    ``Cannot find a valid font for the specified font`` and the caller
    sees the error in logs (better than silently rendering with no
    glyphs).
    """
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return _FONT_CANDIDATES[0]


def _drawtext_escape(value: str) -> str:
    """Escape a string for ffmpeg's ``drawtext text=...`` value.

    drawtext uses ``:`` to separate options and ``\\`` / ``'`` /
    ``%`` as metacharacters inside the text value. This minimal escape
    is what ffmpeg's documented examples use — robust enough for
    arbitrary news-headline content.
    """
    return (
        value.replace("\\", "\\\\")
             .replace(":", r"\:")
             .replace("'", r"\'")
             .replace("%", r"\%")
    )


def _wrap_caption(text: str, max_chars_per_line: int = 22,
                  max_lines: int = 3) -> str:
    """Greedy word-wrap for a Shorts caption, capped at *max_lines*.

    drawtext supports ``\\n`` literal in the text value to break lines,
    so we just join with that. Truncates with an ellipsis if the
    message exceeds the line cap.
    """
    if not text:
        return ""
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars_per_line or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) >= max_lines and len(" ".join(lines).split()) < len(words):
        # Truncated mid-sentence — add ellipsis to the last line.
        last = lines[-1]
        if not last.endswith("..."):
            lines[-1] = (last[: max_chars_per_line - 3].rstrip() + "...") \
                if len(last) > max_chars_per_line - 3 else last + "..."
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Brand pill PNG
# ---------------------------------------------------------------------------

_BRAND_PILL_TEXT = "Nerra Network · AI-narrated"


def _make_brand_pill(output_path: Path,
                     *, width: int = 320, height: int = 60) -> Path:
    """Render the network brand pill as an RGBA PNG.

    Idempotent: if *output_path* already exists, returns it without
    re-rendering. Output is a transparent-background PNG with a
    rounded-rect 50% black backdrop and the brand text centered.
    """
    if output_path.exists():
        return output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded rectangle backdrop, 50% black.
    radius = height // 2
    draw.rounded_rectangle(
        [(0, 0), (width - 1, height - 1)],
        radius=radius,
        fill=(0, 0, 0, 140),
    )

    # Text — pick the largest font size that fits horizontally.
    font_path = _find_font()
    font = None
    for size in range(22, 12, -1):
        try:
            candidate = ImageFont.truetype(font_path, size)
        except (IOError, OSError):
            continue
        bbox = candidate.getbbox(_BRAND_PILL_TEXT)
        if bbox[2] - bbox[0] <= width - 32:
            font = candidate
            break
    if font is None:
        font = ImageFont.load_default()

    bbox = font.getbbox(_BRAND_PILL_TEXT)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (width - text_w) // 2 - bbox[0]
    y = (height - text_h) // 2 - bbox[1]
    draw.text((x, y), _BRAND_PILL_TEXT, font=font, fill=(255, 255, 255, 235))

    img.save(output_path, "PNG")
    return output_path


# ---------------------------------------------------------------------------
# Filter graphs
# ---------------------------------------------------------------------------

def _long_form_filter_graph(width: int = 1920, height: int = 1080,
                            fps: int = 30) -> str:
    """filter_complex graph for the 1920x1080 long-form build.

    Inputs (assumed by ``_long_form_cmd``):

      ``[0:v]``  show cover, looped at ``fps``
      ``[1:a]``  episode audio
      ``[2:v]``  brand pill PNG, looped

    Outputs ``[v]`` for video mapping.
    """
    # Visualization band sits along the bottom 25% of the frame.
    viz_h = height // 4
    viz_y = height - viz_h
    # Slow Ken Burns: 0.000004/frame → 1.08 cap reaches at ~6000 frames
    # (200s @30fps), then clamps. Subtle on shorter episodes, satisfying
    # on hour-long ones.
    zoom_expr = "min(zoom+0.000004,1.08)"
    # Pre-scale before zoompan so we don't zoom into pixelated source —
    # 1.15× the target dims is enough headroom for the 1.08 zoom cap.
    pre_w = int(width * 1.15)
    pre_h = int(height * 1.15)

    disclosure = _drawtext_escape("AI-narrated content · Editorial by Nerra Network")
    font_path = _drawtext_escape(_find_font())

    return (
        f"[0:v]"
        f"scale={pre_w}:{pre_h}:force_original_aspect_ratio=increase,"
        f"crop={pre_w}:{pre_h},setsar=1,"
        f"zoompan=z='{zoom_expr}':d=1:s={width}x{height}:fps={fps}"
        f"[bg];"
        f"[bg]drawbox=x=0:y={viz_y}:w={width}:h={viz_h}:color=black@0.25:t=fill[bg2];"
        f"[1:a]showcqt=s={width}x{viz_h}:fps={fps}:basefreq=30:endfreq=18000:axis=0[viz];"
        f"[bg2][viz]overlay=x=0:y={viz_y}:format=auto[bgviz];"
        f"[2:v]format=rgba[brand];"
        f"[bgviz][brand]overlay=x=24:y=24[branded];"
        f"[branded]drawtext=fontfile='{font_path}':"
        f"text='{disclosure}':"
        f"fontsize=44:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:"
        f"box=1:boxcolor=black@0.55:boxborderw=18:"
        f"enable='between(t,0,4)':"
        f"alpha='if(lt(t,3),1,if(lt(t,4),1-(t-3),0))'"
        f"[v]"
    )


def _short_form_filter_graph(width: int = 1080, height: int = 1920,
                             fps: int = 30,
                             hook: Optional[str] = None) -> str:
    """filter_complex graph for the 1080x1920 Shorts build.

    Inputs (assumed by ``_short_form_cmd``):

      ``[0:v]``  show cover, looped at ``fps``
      ``[1:a]``  audio (already clipped via input-side ``-ss``/``-t``)
      ``[2:v]``  brand pill PNG, looped

    Outputs ``[v]`` for video mapping.

    When *hook* is provided, the headline is wrapped, escaped, and
    burned in as a centered caption for the first 3s.
    """
    viz_h = height // 4 + 40  # 520 — slightly taller band reads better in vertical
    viz_y = (height // 2) - (viz_h // 2)
    font_path = _drawtext_escape(_find_font())

    base = (
        f"[0:v]"
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,format=yuv420p[bg];"
        f"[bg]drawbox=x=0:y={viz_y}:w={width}:h={viz_h}:color=black@0.25:t=fill[bg2];"
        f"[1:a]showcqt=s={width}x{viz_h}:fps={fps}:basefreq=30:endfreq=18000:axis=0[viz];"
        f"[bg2][viz]overlay=x=0:y={viz_y}:format=auto[bgviz];"
        f"[2:v]format=rgba[brand];"
        f"[bgviz][brand]overlay=x=W-w-24:y=24[branded]"
    )

    if hook:
        wrapped = _wrap_caption(hook)
        escaped = _drawtext_escape(wrapped)
        caption = (
            f";[branded]drawtext=fontfile='{font_path}':"
            f"text='{escaped}':"
            f"fontsize=64:fontcolor=white:"
            f"x=(w-text_w)/2:y=240:"
            f"box=1:boxcolor=black@0.6:boxborderw=24:"
            f"line_spacing=14:"
            f"enable='between(t,0,3)'"
            f"[v]"
        )
        return base + caption
    return base + ";[branded]null[v]"


# ---------------------------------------------------------------------------
# Command builders
# ---------------------------------------------------------------------------

def _long_form_cmd(audio_in: str, cover_in: str, brand_in: str,
                   output: str, *, fps: int = 30) -> List[str]:
    """Full ffmpeg command for the 1920x1080 long-form build."""
    return [
        "ffmpeg", "-y", "-threads", "0",
        "-loop", "1", "-framerate", str(fps), "-i", cover_in,
        "-i", audio_in,
        "-loop", "1", "-framerate", str(fps), "-i", brand_in,
        "-filter_complex", _long_form_filter_graph(1920, 1080, fps),
        "-map", "[v]", "-map", "1:a",
        *_VIDEO_ENCODE,
        "-r", str(fps),
        *_AUDIO_ENCODE,
        "-shortest",
        "-movflags", "+faststart",
        output,
    ]


def _short_form_cmd(audio_in: str, cover_in: str, brand_in: str,
                    output: str, *,
                    start_offset: float = 0.0,
                    duration: float = 55.0,
                    fps: int = 30,
                    hook: Optional[str] = None) -> List[str]:
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
        "-loop", "1", "-framerate", str(fps), "-i", brand_in,
        "-filter_complex", _short_form_filter_graph(1080, 1920, fps, hook),
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

    The brand pill PNG is generated once per work directory
    (``output_path.parent / _brand_pill.png``) and reused on
    subsequent calls.

    Parameters
    ----------
    audio_path:
        Path to the final mixed episode MP3.
    cover_path:
        Path to the show's static cover image (under ``assets/covers/``).
    output_path:
        Where to write the MP4. Parent dir must exist.
    fps:
        Frame rate for both the still video stream and the
        visualization animation. 30 is the standard YouTube target.

    Returns
    -------
    Path
        ``output_path`` on success.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"audio not found: {audio_path}")
    if not cover_path.exists():
        raise FileNotFoundError(f"cover not found: {cover_path}")

    brand_path = output_path.parent / "_brand_pill.png"
    _make_brand_pill(brand_path)

    cmd = _long_form_cmd(str(audio_path), str(cover_path),
                         str(brand_path), str(output_path), fps=fps)
    logger.info("Building long-form video → %s", output_path.name)
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path


def build_short_video(audio_path: Path, cover_path: Path,
                      output_path: Path, *,
                      start_offset: float = 0.0,
                      duration: float = 55.0,
                      fps: int = 30,
                      hook: Optional[str] = None) -> Path:
    """Render a 1080x1920 vertical YouTube Shorts video.

    Parameters
    ----------
    audio_path:
        Source audio (usually the same final mixed episode MP3 used
        for long-form). Only the slice from *start_offset* to
        *start_offset + duration* is included.
    cover_path:
        Path to the show's cover image (filled, then cropped to vertical).
    output_path:
        Where to write the MP4.
    start_offset:
        Seconds into the audio where the Short should start. Pass
        ``audio.intro_duration + audio.voice_intro_delay`` so the clip
        skips music intro and starts on voice.
    duration:
        Length of the short clip in seconds. **Must stay below 60** so
        YouTube classifies the upload as a Short.
    fps:
        Frame rate; same caveats as the long-form builder.
    hook:
        Optional one-line headline. When provided, it's wrapped and
        burned in as a centered caption for the first 3s — gives the
        scrolling Shorts viewer a topic preview before they decide to
        stay.

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

    brand_path = output_path.parent / "_brand_pill.png"
    _make_brand_pill(brand_path)

    cmd = _short_form_cmd(
        str(audio_path), str(cover_path), str(brand_path),
        str(output_path),
        start_offset=start_offset,
        duration=duration, fps=fps, hook=hook,
    )
    logger.info(
        "Building Shorts video (%.1fs from %.1fs) → %s",
        duration, start_offset, output_path.name,
    )
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path
