"""Audio utility functions for the podcast generation pipeline.

Provides:
  - get_audio_duration(): cached ffprobe duration lookup
  - format_duration(): seconds -> HH:MM:SS or MM:SS string
  - normalize_voice(): ffmpeg highpass/lowpass/loudnorm/compressor chain with fallback
  - concatenate_audio(): ffmpeg concat demuxer
  - mix_with_music(): full music mixing pipeline (intro/overlap/fadeout/silence/outro)

Music mixing supports three modes configured via YAML:
  1. Standard: single music file for intro + overlap + fadeout + outro (TST, PT)
  2. Delayed intro: voice_intro_delay > 0 shifts voice start so music plays alone
  3. Dual-music: separate background_music_path for the outro section (FF)
"""

import logging
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_audio_duration_cache: Dict[Path, float] = {}

# ---------------------------------------------------------------------------
# Common encoding constants
# ---------------------------------------------------------------------------

_ENCODE_ARGS = ["-ar", "44100", "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast"]


# ---------------------------------------------------------------------------
# Duration helpers
# ---------------------------------------------------------------------------

def get_audio_duration(path: Path) -> float:
    """Return duration in seconds for an audio file.

    Results are cached to avoid redundant ``ffprobe`` calls within the
    same process.
    """
    if path in _audio_duration_cache:
        return _audio_duration_cache[path]

    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        duration = float(result.stdout.strip())
        _audio_duration_cache[path] = duration
        return duration
    except Exception as exc:
        logger.warning("Unable to determine duration for %s: %s", path, exc)
        return 0.0


def format_duration(seconds: float) -> str:
    """Format duration in seconds to ``HH:MM:SS`` or ``MM:SS``."""
    if not seconds or seconds <= 0:
        return "00:00"

    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)

    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


# ---------------------------------------------------------------------------
# Voice normalization
# ---------------------------------------------------------------------------

def _voice_norm_full_cmd(voice_in: str, voice_out: str) -> list:
    """Build the full 5-stage voice normalization ffmpeg command."""
    return [
        "ffmpeg", "-y", "-threads", "0", "-i", voice_in,
        "-af",
        "highpass=f=80,lowpass=f=15000,"
        "loudnorm=I=-18:TP=-1.5:LRA=11:linear=true,"
        "acompressor=threshold=-20dB:ratio=4:attack=1:release=100:makeup=2,"
        "alimiter=level_in=1:level_out=0.95:limit=0.95",
        "-ar", "44100", "-ac", "1",
        "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
        voice_out,
    ]


def _voice_norm_fallback_cmd(voice_in: str, voice_out: str) -> list:
    """Build the simplified fallback voice normalization command."""
    return [
        "ffmpeg", "-y", "-threads", "0", "-i", voice_in,
        "-af", "loudnorm=I=-18:TP=-1.5:LRA=11:linear=true",
        "-ar", "44100", "-ac", "1",
        "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
        voice_out,
    ]


def normalize_voice(input_path: Path, output_path: Path) -> Path:
    """Normalize voice audio with a multi-stage filter chain.

    Tries the full chain (highpass -> lowpass -> loudnorm -> compressor ->
    limiter).  If it fails (e.g. ffmpeg version mismatch), falls back to
    loudnorm only.

    Returns *output_path* on success.
    """
    file_duration = get_audio_duration(input_path)
    timeout_seconds = max(int(file_duration * 3) + 120, 600)

    try:
        logger.info("Attempting voice normalization with full filter chain...")
        cmd = _voice_norm_full_cmd(str(input_path), str(output_path))
        subprocess.run(cmd, check=True, capture_output=True, timeout=timeout_seconds)
        logger.info("Voice normalization (full chain) succeeded.")
    except subprocess.CalledProcessError:
        logger.warning("Full filter chain failed, falling back to loudnorm only...")
        cmd = _voice_norm_fallback_cmd(str(input_path), str(output_path))
        subprocess.run(cmd, check=True, capture_output=True, timeout=timeout_seconds)
        logger.info("Voice normalization (fallback) succeeded.")

    return output_path


# ---------------------------------------------------------------------------
# Audio concatenation
# ---------------------------------------------------------------------------

def concatenate_audio(file_list: List[Path], output_path: Path) -> Path:
    """Concatenate audio files using the ffmpeg concat demuxer.

    Creates a temporary concat list file, runs ``ffmpeg -f concat``,
    and cleans up the list.  Returns *output_path*.
    """
    concat_list = output_path.parent / "concat_list.txt"
    try:
        with open(concat_list, "w", encoding="utf-8") as f:
            for fp in file_list:
                f.write(f"file '{fp.absolute()}'\n")

        cmd = [
            "ffmpeg", "-y", "-threads", "0",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c", "copy",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
    finally:
        try:
            if concat_list.exists():
                concat_list.unlink()
        except Exception:
            pass

    return output_path


# ---------------------------------------------------------------------------
# Music segment command builders (match test_audio_commands.py exactly)
# ---------------------------------------------------------------------------

def _music_intro_cmd(music_in: str, intro_out: str,
                     duration: int = 5, volume: float = 0.6) -> list:
    return [
        "ffmpeg", "-y", "-threads", "0", "-i", music_in, "-t", str(duration),
        "-af", f"volume={volume}",
        "-ar", "44100", "-ac", "2",
        "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
        intro_out,
    ]


def _music_overlap_cmd(music_in: str, overlap_out: str,
                       start: int = 5, duration: int = 3,
                       volume: float = 0.5) -> list:
    return [
        "ffmpeg", "-y", "-threads", "0", "-i", music_in,
        "-ss", str(start), "-t", str(duration),
        "-af", f"volume={volume}",
        "-ar", "44100", "-ac", "2",
        "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
        overlap_out,
    ]


def _music_fadeout_cmd(music_in: str, fadeout_out: str,
                       start: int = 8, duration: int = 18,
                       volume: float = 0.4) -> list:
    return [
        "ffmpeg", "-y", "-threads", "0", "-i", music_in,
        "-ss", str(start), "-t", str(duration),
        "-af", f"volume={volume},afade=t=out:curve=log:st=0:d={duration}",
        "-ar", "44100", "-ac", "2",
        "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
        fadeout_out,
    ]


def _music_outro_cmd(music_in: str, outro_out: str,
                     duration: int = 30, volume: float = 0.4,
                     fade_in_duration: int = 2,
                     fade_out_start: int = 27,
                     fade_out_duration: int = 3) -> list:
    return [
        "ffmpeg", "-y", "-threads", "0",
        "-stream_loop", "-1", "-i", music_in, "-t", str(duration),
        "-af",
        f"volume={volume},"
        f"afade=t=in:curve=log:st=0:d={fade_in_duration},"
        f"afade=t=out:curve=log:st={fade_out_start}:d={fade_out_duration}",
        "-ar", "44100", "-ac", "2",
        "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
        outro_out,
    ]


def _silence_cmd(duration_seconds: float, silence_out: str) -> list:
    return [
        "ffmpeg", "-y", "-threads", "0",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", str(duration_seconds),
        "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
        silence_out,
    ]


def _mono_silence_cmd(duration_seconds: float, silence_out: str) -> list:
    """Generate mono silence matching the normalized voice format."""
    return [
        "ffmpeg", "-y", "-threads", "0",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-t", str(duration_seconds),
        "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
        silence_out,
    ]


def _music_concat_cmd(concat_list: str, music_full_out: str) -> list:
    return [
        "ffmpeg", "-y", "-threads", "0",
        "-f", "concat", "-safe", "0", "-i", concat_list,
        "-c", "copy",
        music_full_out,
    ]


def _final_mix_cmd(voice_in: str, music_in: str, final_out: str) -> list:
    return [
        "ffmpeg", "-y", "-threads", "0",
        "-i", voice_in, "-i", music_in,
        "-filter_complex",
        "[0:a][1:a]amix=inputs=2:duration=longest:dropout_transition=2",
        "-ar", "44100", "-ac", "2",
        "-c:a", "libmp3lame", "-b:a", "192k", "-preset", "fast",
        final_out,
    ]


# ---------------------------------------------------------------------------
# Full music mixing pipeline
# ---------------------------------------------------------------------------

def mix_with_music(
    voice_path: Path,
    music_path: Path,
    output_path: Path,
    *,
    intro_duration: int = 5,
    overlap_duration: int = 3,
    fade_duration: int = 18,
    outro_duration: int = 30,
    intro_volume: float = 0.6,
    overlap_volume: float = 0.5,
    fade_volume: float = 0.4,
    outro_volume: float = 0.4,
    voice_intro_delay: float = 0.0,
    background_music_path: Optional[Path] = None,
) -> Path:
    """Full music mixing pipeline supporting three modes.

    **Standard mode** (voice_intro_delay=0, no background_music_path):
      0–5 s:  music intro alone (intro_volume)
      5–8 s:  music overlap while voice starts (overlap_volume)
      8–26 s: music fadeout (fade_volume -> 0, logarithmic)
      26 s–end: silence (no music under voice)
      after voice: 30 s outro with fade-in/out

    **Delayed-intro mode** (voice_intro_delay > 0):
      Voice is shifted right by *voice_intro_delay* seconds so music plays
      alone at the start.  Set intro_duration >= voice_intro_delay so the
      intro music covers the full delay period.

    **Dual-music mode** (background_music_path provided):
      Primary *music_path* is used for intro/overlap/fadeout segments.
      *background_music_path* is used for the outro segment, allowing a
      different musical feel for the show's closing.

    If *music_path* doesn't exist, normalizes voice only and returns.
    """
    if not music_path.exists():
        logger.warning("Music file %s not found — returning voice-only.", music_path)
        return normalize_voice(voice_path, output_path)

    voice_duration = get_audio_duration(voice_path)
    timeout_seconds = max(int(voice_duration * 3) + 120, 600)

    # Resolve the outro music source (primary or background)
    outro_music = music_path
    if background_music_path and background_music_path.exists():
        outro_music = background_music_path
        logger.info("Using background music for outro: %s", outro_music.name)
    elif background_music_path:
        logger.warning(
            "Background music %s not found — using primary music for outro.",
            background_music_path,
        )

    with tempfile.TemporaryDirectory(dir=voice_path.parent) as tmp_str:
        tmp_dir = Path(tmp_str)

        # Normalize voice first
        voice_mix = tmp_dir / "voice_normalized_mix.mp3"
        normalize_voice(voice_path, voice_mix)

        # --- Apply voice intro delay if configured ---
        effective_voice_duration = voice_duration
        if voice_intro_delay > 0:
            logger.info(
                "Applying %.1fs voice intro delay (music plays alone first).",
                voice_intro_delay,
            )
            if voice_intro_delay > intro_duration:
                logger.warning(
                    "voice_intro_delay (%.1fs) > intro_duration (%ds) — "
                    "consider increasing intro_duration to match.",
                    voice_intro_delay, intro_duration,
                )

            voice_silence = tmp_dir / "voice_delay_silence.mp3"
            subprocess.run(
                _mono_silence_cmd(voice_intro_delay, str(voice_silence)),
                check=True, capture_output=True,
            )

            voice_delayed = tmp_dir / "voice_delayed.mp3"
            delay_list = tmp_dir / "delay_concat.txt"
            with open(delay_list, "w") as f:
                f.write(f"file '{voice_silence.absolute()}'\n")
                f.write(f"file '{voice_mix.absolute()}'\n")
            subprocess.run(
                _music_concat_cmd(str(delay_list), str(voice_delayed)),
                check=True, capture_output=True,
            )
            voice_mix = voice_delayed
            effective_voice_duration = voice_duration + voice_intro_delay

        # --- Generate music segments in parallel ---
        music_intro_f = tmp_dir / "music_intro.mp3"
        music_overlap_f = tmp_dir / "music_overlap.mp3"
        music_fadeout_f = tmp_dir / "music_fadeout.mp3"
        music_outro_f = tmp_dir / "music_outro.mp3"
        music_silence_f = tmp_dir / "music_silence.mp3"

        fade_start = intro_duration + overlap_duration

        def _run_segment(name: str, cmd: list) -> str:
            subprocess.run(cmd, check=True, capture_output=True)
            return name

        segment_cmds = [
            ("intro", _music_intro_cmd(
                str(music_path), str(music_intro_f),
                duration=intro_duration, volume=intro_volume)),
            ("overlap", _music_overlap_cmd(
                str(music_path), str(music_overlap_f),
                start=intro_duration, duration=overlap_duration,
                volume=overlap_volume)),
            ("fadeout", _music_fadeout_cmd(
                str(music_path), str(music_fadeout_f),
                start=fade_start, duration=fade_duration,
                volume=fade_volume)),
            ("outro", _music_outro_cmd(
                str(outro_music), str(music_outro_f),
                duration=outro_duration, volume=outro_volume)),
        ]

        # Silence between fadeout and outro
        music_bed_duration = intro_duration + overlap_duration + fade_duration
        middle_silence_duration = max(
            effective_voice_duration - music_bed_duration, 0.0,
        )

        if middle_silence_duration > 0.1:
            segment_cmds.append(
                ("silence", _silence_cmd(middle_silence_duration, str(music_silence_f)))
            )

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {
                pool.submit(_run_segment, name, cmd): name
                for name, cmd in segment_cmds
            }
            for future in as_completed(futures):
                name = futures[future]
                future.result()  # propagate any exceptions
                logger.info("Generated music segment: %s", name)

        # --- Concatenate music segments ---
        concat_files = [music_intro_f, music_overlap_f, music_fadeout_f]
        if middle_silence_duration > 0.1:
            concat_files.append(music_silence_f)
        concat_files.append(music_outro_f)

        music_full = tmp_dir / "music_full.mp3"
        music_concat_list = tmp_dir / "music_concat.txt"
        with open(music_concat_list, "w") as f:
            for fp in concat_files:
                f.write(f"file '{fp.absolute()}'\n")

        cmd = _music_concat_cmd(str(music_concat_list), str(music_full))
        subprocess.run(cmd, check=True, capture_output=True)

        # --- Final mix: voice + music ---
        cmd = _final_mix_cmd(str(voice_mix), str(music_full), str(output_path))
        subprocess.run(cmd, check=True, capture_output=True, timeout=timeout_seconds)

    logger.info("Final mix complete: %s", output_path)
    return output_path
