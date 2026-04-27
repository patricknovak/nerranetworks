"""Video assembly helpers for the YouTube publishing pipeline.

Two builders share one visual recipe so every show looks like part
of the same network without per-show artwork:

  - **Background**: either the show cover (single Ken Burns image) or
    a pre-rendered slideshow MP4 of Pexels photos cycling every ~12 s.
    Slideshow uses :mod:`engine.visual_assets`; without
    ``PEXELS_API_KEY`` we silently fall back to the static cover.
  - **Tint band**: 25% black overlay underneath the visualization so
    it reads against any cover.
  - **Visualization**: ``showcqt`` (constant-Q transform) — the
    colorful music-bar look. Audio-reactive, frame-by-frame motion.
  - **Brand pill**: ``Nerra Network · AI-narrated`` PNG (rendered
    once with Pillow). Top-left long-form, top-right Shorts.
  - **First-seconds burn-in**: long-form fades in/out a centered
    AI-disclosure line for the first 4 s. Shorts (with a hook) burn
    the headline for the first 3 s.
  - **Captions** (long-form only): when a transcript SRT is supplied,
    ffmpeg's ``subtitles`` filter burns synchronized captions in a
    semi-transparent band sitting just above the spectrum.

The encoder profile uses ``-g 60 -keyint_min 60 -sc_threshold 0
-force_key_frames`` to force a keyframe every 2 s; without this,
x264 produced a single IDR at t=0 and YouTube's transcoder rejected
the rendition with "video can't play".
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Encoding profile
# ---------------------------------------------------------------------------

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

_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)


def _find_font() -> str:
    """Return the path of an installed bold sans-serif font."""
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return _FONT_CANDIDATES[0]


def _drawtext_escape(value: str) -> str:
    """Escape a string for ffmpeg ``drawtext text=`` value."""
    return (
        value.replace("\\", "\\\\")
             .replace(":", r"\:")
             .replace("'", r"\'")
             .replace("%", r"\%")
    )


def _subtitles_path_escape(p: str) -> str:
    """Escape a path for use inside the ffmpeg ``subtitles`` filter.

    ``subtitles`` uses ``:`` as its option separator, so any colons
    in the path (notably the C: drive on Windows or any odd Linux
    paths) need backslash escaping. Single quotes are wrapped at the
    surrounding ``'…'`` so we escape those too.
    """
    return (
        p.replace("\\", "/")
         .replace(":", r"\:")
         .replace("'", r"\'")
    )


def _wrap_caption(text: str, max_chars_per_line: int = 22,
                  max_lines: int = 3) -> str:
    """Greedy word-wrap for a Shorts caption, capped at *max_lines*."""
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
    """Render the network brand pill as an RGBA PNG. Idempotent."""
    if output_path.exists():
        return output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)

    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    radius = height // 2
    draw.rounded_rectangle(
        [(0, 0), (width - 1, height - 1)],
        radius=radius,
        fill=(0, 0, 0, 140),
    )

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
# Slideshow renderer (stage 1)
# ---------------------------------------------------------------------------

# Each photo holds for ~12 s — long enough to read the spectrum + caption
# but short enough that the long-form keeps moving. Slideshow loops in
# stage 2 so we don't need to scale the photo count to audio length.
_SCENE_DURATION_SECONDS = 12.0


def _slideshow_filter_graph(scene_count: int, *,
                            scene_duration: float = _SCENE_DURATION_SECONDS,
                            width: int = 1920, height: int = 1080,
                            fps: int = 30) -> str:
    """Build the filter_complex for a Ken Burns slideshow with hard cuts.

    Each scene gets a 1.00 → 1.12 zoom over its window. Hard cuts
    between scenes (no crossfade) — the spectrum + brand pill + caption
    motion in stage 2 hides any visual jump.
    """
    pre_w = int(width * 1.15)
    pre_h = int(height * 1.15)
    zoom_expr = "min(zoom+0.0006,1.12)"
    frames_per_scene = int(scene_duration * fps)

    chains: List[str] = []
    for i in range(scene_count):
        chains.append(
            f"[{i}:v]"
            f"scale={pre_w}:{pre_h}:force_original_aspect_ratio=increase,"
            f"crop={pre_w}:{pre_h},setsar=1,"
            f"zoompan=z='{zoom_expr}':d={frames_per_scene}"
            f":s={width}x{height}:fps={fps},"
            f"trim=duration={scene_duration:.2f},setpts=PTS-STARTPTS"
            f"[s{i}]"
        )
    concat_in = "".join(f"[s{i}]" for i in range(scene_count))
    chains.append(f"{concat_in}concat=n={scene_count}:v=1:a=0[v]")
    return ";".join(chains)


def _slideshow_cmd(scene_paths: Sequence[Path], output: Path,
                   *, scene_duration: float = _SCENE_DURATION_SECONDS,
                   fps: int = 30) -> List[str]:
    """ffmpeg command for stage 1 (slideshow render)."""
    inputs: List[str] = []
    for path in scene_paths:
        inputs.extend([
            "-loop", "1",
            "-framerate", str(fps),
            "-t", f"{scene_duration + 0.5:.2f}",
            "-i", str(path),
        ])
    return [
        "ffmpeg", "-y", "-threads", "0",
        *inputs,
        "-filter_complex",
        _slideshow_filter_graph(len(scene_paths),
                                scene_duration=scene_duration, fps=fps),
        "-map", "[v]",
        "-r", str(fps),
        *_VIDEO_ENCODE,
        "-an",
        "-movflags", "+faststart",
        str(output),
    ]


def _render_slideshow(scene_paths: Sequence[Path], output: Path,
                      *, fps: int = 30) -> Path:
    """Render the stage-1 slideshow MP4. Idempotent (skips if output exists)."""
    if output.exists():
        return output
    cmd = _slideshow_cmd(scene_paths, output, fps=fps)
    logger.info("Rendering slideshow (%d scenes) → %s",
                len(scene_paths), output.name)
    subprocess.run(cmd, check=True, capture_output=True)
    return output


# ---------------------------------------------------------------------------
# Long-form filter graph (stage 2)
# ---------------------------------------------------------------------------

# Force-style for the burn-in subtitles. ASS color format is &HAABBGGRR
# (alpha is "100 minus opacity" — 0 is opaque, 255 is transparent).
# BorderStyle=3 = opaque box behind the text. MarginV=350 lifts the
# subtitle baseline above the spectrum band.
_SUBTITLES_FORCE_STYLE = (
    "FontName=DejaVu Sans,"
    "FontSize=22,"
    "PrimaryColour=&H00FFFFFF,"
    "OutlineColour=&H00000000,"
    "BackColour=&HA0000000,"
    "BorderStyle=3,"
    "Outline=4,"
    "Shadow=0,"
    "Alignment=2,"
    "MarginV=320"
)


def _long_form_filter_graph(*, width: int = 1920, height: int = 1080,
                            fps: int = 30,
                            bg_is_video: bool = False,
                            subtitles_path: Optional[str] = None) -> str:
    """filter_complex for stage 2.

    Inputs:
      ``[0:v]`` — background. Either looped cover image (Ken Burns
      applied here) or pre-rendered slideshow MP4 (zoom already
      baked in; we just scale to fill).
      ``[1:a]`` — episode audio.
      ``[2:v]`` — brand pill PNG, looped.
    """
    viz_h = height // 4
    viz_y = height - viz_h

    if bg_is_video:
        # Slideshow MP4 already has motion + zoom; just normalize to
        # the target frame and fps.
        bg_chain = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,format=yuv420p[bg]"
        )
    else:
        pre_w = int(width * 1.15)
        pre_h = int(height * 1.15)
        zoom_expr = "min(zoom+0.000004,1.08)"
        bg_chain = (
            f"[0:v]"
            f"scale={pre_w}:{pre_h}:force_original_aspect_ratio=increase,"
            f"crop={pre_w}:{pre_h},setsar=1,"
            f"zoompan=z='{zoom_expr}':d=1:s={width}x{height}:fps={fps}"
            f"[bg]"
        )

    disclosure = _drawtext_escape(
        "AI-narrated content · Editorial by Nerra Network"
    )
    font_path = _drawtext_escape(_find_font())

    graph = (
        f"{bg_chain};"
        f"[bg]drawbox=x=0:y={viz_y}:w={width}:h={viz_h}"
        f":color=black@0.25:t=fill[bg2];"
        f"[1:a]showcqt=s={width}x{viz_h}:fps={fps}"
        f":basefreq=30:endfreq=18000:axis=0[viz];"
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
        f"[disclosed]"
    )

    if subtitles_path:
        escaped = _subtitles_path_escape(subtitles_path)
        graph += (
            f";[disclosed]subtitles='{escaped}'"
            f":force_style='{_SUBTITLES_FORCE_STYLE}'[v]"
        )
    else:
        graph += ";[disclosed]null[v]"
    return graph


def _short_form_filter_graph(width: int = 1080, height: int = 1920,
                             fps: int = 30,
                             hook: Optional[str] = None) -> str:
    """filter_complex for the 1080x1920 Shorts build."""
    viz_h = height // 4 + 40
    viz_y = (height // 2) - (viz_h // 2)
    font_path = _drawtext_escape(_find_font())

    base = (
        f"[0:v]"
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,format=yuv420p[bg];"
        f"[bg]drawbox=x=0:y={viz_y}:w={width}:h={viz_h}"
        f":color=black@0.25:t=fill[bg2];"
        f"[1:a]showcqt=s={width}x{viz_h}:fps={fps}"
        f":basefreq=30:endfreq=18000:axis=0[viz];"
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
# Long-form command builder (stage 2)
# ---------------------------------------------------------------------------

def _long_form_cmd(audio_in: str, bg_in: str, brand_in: str,
                   output: str, *,
                   fps: int = 30,
                   bg_is_video: bool = False,
                   subtitles_path: Optional[str] = None) -> List[str]:
    """Full ffmpeg command for stage 2.

    When *bg_is_video* is True, *bg_in* is a pre-rendered slideshow
    MP4; we ``-stream_loop -1`` it so it loops to match the audio
    length, and we don't apply ``-loop 1 -framerate``.
    """
    if bg_is_video:
        bg_input = ["-stream_loop", "-1", "-i", bg_in]
    else:
        bg_input = ["-loop", "1", "-framerate", str(fps), "-i", bg_in]

    return [
        "ffmpeg", "-y", "-threads", "0",
        *bg_input,
        "-i", audio_in,
        "-loop", "1", "-framerate", str(fps), "-i", brand_in,
        "-filter_complex",
        _long_form_filter_graph(
            fps=fps,
            bg_is_video=bg_is_video,
            subtitles_path=subtitles_path,
        ),
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
    """ffmpeg command for the 1080x1920 Shorts build."""
    return [
        "ffmpeg", "-y", "-threads", "0",
        "-loop", "1", "-framerate", str(fps), "-i", cover_in,
        "-ss", f"{start_offset:.2f}",
        "-t", f"{duration:.2f}",
        "-i", audio_in,
        "-loop", "1", "-framerate", str(fps), "-i", brand_in,
        "-filter_complex",
        _short_form_filter_graph(1080, 1920, fps, hook),
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

def build_long_form_video(
    audio_path: Path,
    cover_path: Path,
    output_path: Path,
    *,
    fps: int = 30,
    scene_paths: Optional[Sequence[Path]] = None,
    subtitles_path: Optional[Path] = None,
) -> Path:
    """Render a 1920x1080 long-form podcast video.

    Parameters
    ----------
    audio_path:
        Final mixed episode MP3.
    cover_path:
        Show cover image. Used as the background when ``scene_paths``
        is empty / unset (single-image Ken Burns), or as the fallback
        if slideshow rendering fails.
    output_path:
        Where to write the final MP4.
    fps:
        Frame rate.
    scene_paths:
        Optional list of slideshow images. ``len ≥ 2`` triggers the
        two-stage pipeline (slideshow MP4 first, then composite). A
        single-element list (or ``None``) uses the single-cover path.
    subtitles_path:
        Optional path to an SRT file. When provided, ``ffmpeg``'s
        ``subtitles`` filter burns the cues onto the video using a
        styled box just above the spectrum band.

    Returns
    -------
    Path
        ``output_path`` on success.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"audio not found: {audio_path}")
    if not cover_path.exists():
        raise FileNotFoundError(f"cover not found: {cover_path}")

    work_dir = output_path.parent
    brand_path = work_dir / "_brand_pill.png"
    _make_brand_pill(brand_path)

    bg_path: Path = cover_path
    bg_is_video = False
    if scene_paths and len(scene_paths) >= 2:
        slideshow_path = work_dir / f"{output_path.stem}_slides.mp4"
        try:
            _render_slideshow(scene_paths, slideshow_path, fps=fps)
            bg_path = slideshow_path
            bg_is_video = True
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "Slideshow render failed (%s) — falling back to single cover",
                exc,
            )

    cmd = _long_form_cmd(
        str(audio_path), str(bg_path), str(brand_path),
        str(output_path),
        fps=fps,
        bg_is_video=bg_is_video,
        subtitles_path=str(subtitles_path) if subtitles_path else None,
    )
    logger.info("Building long-form video → %s (slideshow=%s, captions=%s)",
                output_path.name, bg_is_video, bool(subtitles_path))
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path


def build_short_video(audio_path: Path, cover_path: Path,
                      output_path: Path, *,
                      start_offset: float = 0.0,
                      duration: float = 55.0,
                      fps: int = 30,
                      hook: Optional[str] = None) -> Path:
    """Render a 1080x1920 vertical YouTube Shorts video."""
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
