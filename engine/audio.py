"""Audio utility functions for the podcast generation pipeline.

Provides:
  - get_audio_duration(): cached ffprobe duration lookup
  - format_duration(): seconds → HH:MM:SS or MM:SS string
"""

import logging
import subprocess
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

_audio_duration_cache: Dict[Path, float] = {}


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
