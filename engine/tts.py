"""TTS helpers for the podcast generation pipeline.

Supports two providers:
  - **ElevenLabs** (default): cloud API, paid, high quality
  - **Kokoro** (kokoro-onnx): local inference, free, Apache 2.0

ElevenLabs functions:
  - synthesize(): top-level entry point — text in, audio file out
  - validate_elevenlabs_auth(): fail-fast API key check
  - chunk_text(): sentence-aware text splitting for the 5000-char API limit
  - speak_chunk(): single-chunk TTS with retry
  - speak(): full TTS with automatic chunking + ffmpeg concatenation

Kokoro functions:
  - synthesize_kokoro(): top-level Kokoro entry point — text in, audio file out
  - synthesize_kokoro_sections(): section-aware Kokoro synthesis
"""

import logging
import subprocess
from pathlib import Path
from typing import List

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

ELEVENLABS_API_BASE = "https://api.elevenlabs.io/v1"


def validate_elevenlabs_auth(api_key: str) -> None:
    """Fail fast with a clear message when the ElevenLabs key is rejected."""
    resp = requests.get(
        f"{ELEVENLABS_API_BASE}/user",
        headers={"xi-api-key": api_key},
        timeout=10,
    )
    if resp.status_code == 401:
        raise RuntimeError(
            "ElevenLabs rejected the API key (401). "
            "Update ELEVENLABS_API_KEY in .env/GitHub secrets."
        )
    resp.raise_for_status()


def chunk_text(text: str, max_chars: int = 5000) -> List[str]:
    """Split text into chunks for ElevenLabs API.

    Split priority (best → worst for natural audio):
      1. Sentence boundaries (., !, ?) — cleanest break
      2. Clause boundaries (semicolons, colons, em dashes) — natural pause
      3. Conjunctions after commas (", and", ", but", ", so") — clause-level
      4. Any comma — last resort within-sentence split
      5. Last space in the trailing 30% of the chunk
    """
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    remaining = text.strip()

    while len(remaining) > max_chars:
        chunk_candidate = remaining[:max_chars]

        best_split = -1

        # 1. Prefer the rightmost sentence ending
        sentence_endings: List[int] = []
        for i, char in enumerate(chunk_candidate):
            if char in ".!?":
                # Avoid splitting on abbreviations (e.g., "U.S.") or decimals
                # by requiring whitespace or end-of-text after the punctuation
                if i + 1 >= len(chunk_candidate) or chunk_candidate[i + 1] in " \n\t":
                    sentence_endings.append(i + 1)

        if sentence_endings:
            best_split = sentence_endings[-1]

        # 2. Fallback: clause boundaries (semicolons, colons, em dashes)
        if best_split == -1:
            clause_splits: List[int] = []
            for i, char in enumerate(chunk_candidate):
                if char in ";:" or (char == '—'):
                    clause_splits.append(i + 1)
            if clause_splits:
                best_split = clause_splits[-1]

        # 3. Fallback: conjunction after comma (", and", ", but", ", so", ", or")
        if best_split == -1:
            import re
            conj_pattern = re.compile(r",\s+(?:and|but|so|or|yet|because|while|although)\s", re.IGNORECASE)
            conj_matches = list(conj_pattern.finditer(chunk_candidate))
            if conj_matches:
                # Split after the comma, before the conjunction
                best_split = conj_matches[-1].start() + 1

        # 4. Fallback: any comma (keep last one found)
        if best_split == -1:
            for i, char in enumerate(chunk_candidate):
                if char == ",":
                    best_split = i + 1

        # 5. Fallback: last space in the trailing 30%
        if best_split == -1:
            search_start = int(max_chars * 0.7)
            for i in range(len(chunk_candidate) - 1, search_start - 1, -1):
                if chunk_candidate[i] == " ":
                    best_split = i + 1
                    break

        # Absolute last resort
        if best_split == -1:
            for i in range(max_chars - 1, max(max_chars - 50, 0), -1):
                if i < len(chunk_candidate) and chunk_candidate[i] == " ":
                    best_split = i + 1
                    break

        if best_split == -1 or best_split == 0:
            best_split = max_chars

        chunk_text_str = remaining[:best_split].strip()
        if chunk_text_str:
            chunks.append(chunk_text_str)
        remaining = remaining[best_split:].strip()

    if remaining:
        chunks.append(remaining)

    if len(chunks) > 1:
        logger.info(
            "Split text into %d chunks: %s characters",
            len(chunks),
            [len(c) for c in chunks],
        )

    return chunks


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.RequestException, requests.Timeout)),
)
def speak_chunk(
    text: str,
    voice_id: str,
    out_path: Path,
    *,
    api_key: str,
    model_id: str = "eleven_turbo_v2_5",
    stability: float = 0.65,
    similarity_boost: float = 0.9,
    style: float = 0.85,
    use_speaker_boost: bool = True,
    stream: bool = True,
    timeout: int = 120,
) -> None:
    """Generate audio for a single text chunk via the ElevenLabs API."""
    endpoint = "stream" if stream else ""
    url_parts = [ELEVENLABS_API_BASE, "text-to-speech", voice_id]
    if endpoint:
        url_parts.append(endpoint)
    url = "/".join(url_parts)

    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "use_speaker_boost": use_speaker_boost,
        },
    }

    if stream:
        with requests.post(url, json=payload, headers=headers, stream=True, timeout=timeout) as r:
            if r.status_code == 401:
                raise requests.HTTPError(
                    "ElevenLabs returned 401 Unauthorized. "
                    "Verify ELEVENLABS_API_KEY and that the voice ID is accessible.",
                    response=r,
                )
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for data in r.iter_content(chunk_size=8192):
                    f.write(data)
    else:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code == 401:
            raise requests.HTTPError(
                "ElevenLabs returned 401 Unauthorized. "
                "Verify ELEVENLABS_API_KEY and that the voice ID is accessible.",
                response=resp,
            )
        resp.raise_for_status()
        out_path.write_bytes(resp.content)


def speak(
    text: str,
    voice_id: str,
    filename: str,
    *,
    api_key: str,
    max_chars: int = 5000,
    model_id: str = "eleven_turbo_v2_5",
    stability: float = 0.65,
    similarity_boost: float = 0.9,
    style: float = 0.85,
    use_speaker_boost: bool = True,
    stream: bool = True,
    timeout: int = 120,
    append_exclamation: bool = False,
) -> None:
    """Generate audio with automatic chunking and ffmpeg concatenation.

    For texts within *max_chars*, a single API call is made.  Longer texts
    are split at sentence boundaries, synthesised as separate chunks, and
    concatenated with ``ffmpeg -f concat``.
    """
    tts_kwargs = dict(
        api_key=api_key,
        model_id=model_id,
        stability=stability,
        similarity_boost=similarity_boost,
        style=style,
        use_speaker_boost=use_speaker_boost,
        stream=stream,
        timeout=timeout,
    )

    chunks = chunk_text(text, max_chars=max_chars)

    if len(chunks) == 1:
        out_text = text + "!" if append_exclamation else text
        speak_chunk(out_text, voice_id, Path(filename), **tts_kwargs)
        logger.info("ElevenLabs TTS: Generated single chunk (%d chars)", len(text))
        return

    logger.info(
        "ElevenLabs TTS: Splitting into %d chunks for seamless generation",
        len(chunks),
    )
    chunk_files: List[Path] = []
    tmp_dir = Path(filename).parent

    try:
        for i, chunk_text_str in enumerate(chunks):
            chunk_file = tmp_dir / f"tts_chunk_{i:03d}.mp3"
            if append_exclamation:
                if i < len(chunks) - 1:
                    chunk_text_str = chunk_text_str.rstrip(".!?") + "."
                else:
                    chunk_text_str = chunk_text_str + "!"

            speak_chunk(chunk_text_str, voice_id, chunk_file, **tts_kwargs)
            chunk_files.append(chunk_file)
            logger.info(
                "Generated chunk %d/%d (%d chars)",
                i + 1, len(chunks), len(chunk_text_str),
            )

        # Concatenate with ffmpeg
        concat_list = tmp_dir / "elevenlabs_concat.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for cf in chunk_files:
                f.write(f"file '{cf.absolute()}'\n")

        # Re-encode with libmp3lame instead of -c copy to avoid clicks/pops
        # at chunk boundaries caused by misaligned MP3 frames.
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list),
                "-c:a", "libmp3lame",
                "-q:a", "2",
                str(filename),
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )
        logger.info("ElevenLabs TTS: Concatenated %d chunks (re-encoded for seamless joins)", len(chunks))

    finally:
        for cf in chunk_files:
            try:
                if cf.exists():
                    cf.unlink()
            except Exception:
                pass
        try:
            concat_list = tmp_dir / "elevenlabs_concat.txt"
            if concat_list.exists():
                concat_list.unlink()
        except Exception:
            pass


def synthesize(
    text: str,
    voice_id: str,
    output_path: str | Path,
    *,
    api_key: str,
    max_chars: int = 4500,
    model_id: str = "eleven_turbo_v2_5",
    stability: float = 0.65,
    similarity_boost: float = 0.9,
    style: float = 0.85,
    stream: bool = True,
    timeout: int = 120,
    append_exclamation: bool = False,
) -> Path:
    """Top-level entry point: text in, audio file path out.

    Handles chunking and concatenation internally so callers just pass
    text and get back a path.  Default voice settings match Omni View's
    env-var-driven approach; callers can override per show.
    """
    output_path = Path(output_path)
    speak(
        text,
        voice_id,
        str(output_path),
        api_key=api_key,
        max_chars=max_chars,
        model_id=model_id,
        stability=stability,
        similarity_boost=similarity_boost,
        style=style,
        stream=stream,
        timeout=timeout,
        append_exclamation=append_exclamation,
    )
    return output_path


def synthesize_sections(
    sections: List[str],
    voice_id: str,
    output_dir: Path,
    *,
    api_key: str,
    section_prefix: str = "section",
    max_chars: int = 4500,
    model_id: str = "eleven_turbo_v2_5",
    stability: float = 0.65,
    similarity_boost: float = 0.9,
    style: float = 0.85,
    stream: bool = True,
    timeout: int = 120,
) -> List[Path]:
    """Synthesize multiple script sections into individual audio files.

    Each section is synthesized via ``speak()`` (which handles chunking
    internally for sections exceeding *max_chars*).  Returns an ordered
    list of MP3 paths — one per section.

    Parameters
    ----------
    sections:
        Ordered list of text sections to synthesize.
    voice_id:
        ElevenLabs voice ID.
    output_dir:
        Directory for intermediate per-section MP3 files.
    api_key:
        ElevenLabs API key.
    section_prefix:
        Filename prefix for section files.
    max_chars:
        Maximum characters per TTS API chunk.

    Returns
    -------
    list[Path]
        Ordered list of MP3 file paths, one per section.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    section_files: List[Path] = []

    for i, section_text in enumerate(sections):
        section_text = section_text.strip()
        if not section_text:
            logger.warning("Skipping empty section %d", i)
            continue

        section_path = output_dir / f"{section_prefix}_{i:03d}.mp3"
        speak(
            section_text,
            voice_id,
            str(section_path),
            api_key=api_key,
            max_chars=max_chars,
            model_id=model_id,
            stability=stability,
            similarity_boost=similarity_boost,
            style=style,
            stream=stream,
            timeout=timeout,
        )
        section_files.append(section_path)
        logger.info(
            "Synthesized section %d/%d (%d chars): %s",
            i + 1, len(sections), len(section_text), section_path.name,
        )

    return section_files


# ---------------------------------------------------------------------------
# Kokoro TTS (kokoro-onnx) — local, free, Apache 2.0
# ---------------------------------------------------------------------------

_kokoro_model = None
_kokoro_model_lock = None


def _get_kokoro_model():
    """Lazy-load the Kokoro ONNX model (singleton to avoid reloading ~330MB per chunk)."""
    global _kokoro_model, _kokoro_model_lock
    import threading

    if _kokoro_model_lock is None:
        _kokoro_model_lock = threading.Lock()

    with _kokoro_model_lock:
        if _kokoro_model is not None:
            return _kokoro_model

        try:
            from kokoro_onnx import Kokoro
        except ImportError:
            raise RuntimeError(
                "kokoro-onnx is not installed. Run: pip install kokoro-onnx soundfile"
            )

        # Look for model files in project root, then common locations
        search_dirs = [
            Path.cwd(),
            Path.cwd() / "models",
            Path.home() / ".cache" / "kokoro",
        ]

        model_path = None
        voices_path = None
        for d in search_dirs:
            candidate_model = d / "kokoro-v1.0.onnx"
            candidate_voices = d / "voices-v1.0.bin"
            if candidate_model.exists() and candidate_voices.exists():
                model_path = candidate_model
                voices_path = candidate_voices
                break

        if model_path is None or voices_path is None:
            raise FileNotFoundError(
                "Kokoro model files not found. Download kokoro-v1.0.onnx and "
                "voices-v1.0.bin from https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0 "
                "and place them in the project root or models/ directory."
            )

        logger.info("Loading Kokoro model from %s", model_path.parent)
        _kokoro_model = Kokoro(str(model_path), str(voices_path))
        logger.info("Kokoro model loaded successfully")
        return _kokoro_model


def _kokoro_synthesize_chunk(
    text: str,
    out_path: Path,
    *,
    voice: str = "am_adam",
    speed: float = 1.0,
    lang: str = "a",
) -> None:
    """Generate audio for a single text chunk via Kokoro ONNX."""
    import soundfile as sf
    import tempfile

    kokoro = _get_kokoro_model()
    samples, sample_rate = kokoro.create(text, voice=voice, speed=speed, lang=lang)

    # Kokoro outputs WAV at 24kHz — convert to MP3 for pipeline compatibility
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_wav = Path(tmp.name)

    try:
        sf.write(str(tmp_wav), samples, sample_rate)
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(tmp_wav),
                "-c:a", "libmp3lame",
                "-q:a", "2",
                "-ar", "44100",
                str(out_path),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
    finally:
        try:
            tmp_wav.unlink()
        except Exception:
            pass


def synthesize_kokoro(
    text: str,
    output_path: str | Path,
    *,
    voice: str = "am_adam",
    speed: float = 1.0,
    lang: str = "a",
    max_chars: int = 4500,
) -> Path:
    """Top-level Kokoro entry point: text in, audio file path out.

    Handles chunking and concatenation internally so callers just pass
    text and get back a path.
    """
    output_path = Path(output_path)
    chunks = chunk_text(text, max_chars=max_chars)

    if len(chunks) == 1:
        _kokoro_synthesize_chunk(text, output_path, voice=voice, speed=speed, lang=lang)
        logger.info("Kokoro TTS: Generated single chunk (%d chars)", len(text))
        return output_path

    logger.info("Kokoro TTS: Splitting into %d chunks", len(chunks))
    chunk_files: List[Path] = []
    tmp_dir = output_path.parent

    try:
        for i, chunk_text_str in enumerate(chunks):
            chunk_file = tmp_dir / f"kokoro_chunk_{i:03d}.mp3"
            _kokoro_synthesize_chunk(
                chunk_text_str, chunk_file, voice=voice, speed=speed, lang=lang,
            )
            chunk_files.append(chunk_file)
            logger.info(
                "Kokoro chunk %d/%d (%d chars)", i + 1, len(chunks), len(chunk_text_str),
            )

        # Concatenate with ffmpeg (same pattern as ElevenLabs)
        concat_list = tmp_dir / "kokoro_concat.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for cf in chunk_files:
                f.write(f"file '{cf.absolute()}'\n")

        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list),
                "-c:a", "libmp3lame",
                "-q:a", "2",
                str(output_path),
            ],
            check=True,
            capture_output=True,
            timeout=300,
        )
        logger.info("Kokoro TTS: Concatenated %d chunks", len(chunks))

    finally:
        for cf in chunk_files:
            try:
                if cf.exists():
                    cf.unlink()
            except Exception:
                pass
        try:
            concat_list = tmp_dir / "kokoro_concat.txt"
            if concat_list.exists():
                concat_list.unlink()
        except Exception:
            pass

    return output_path


def synthesize_kokoro_sections(
    sections: List[str],
    output_dir: Path,
    *,
    voice: str = "am_adam",
    speed: float = 1.0,
    lang: str = "a",
    section_prefix: str = "section",
    max_chars: int = 4500,
) -> List[Path]:
    """Synthesize multiple script sections via Kokoro into individual audio files.

    Mirrors ``synthesize_sections()`` for section-aware TTS.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    section_files: List[Path] = []

    for i, section_text in enumerate(sections):
        section_text = section_text.strip()
        if not section_text:
            logger.warning("Skipping empty section %d", i)
            continue

        section_path = output_dir / f"{section_prefix}_{i:03d}.mp3"
        synthesize_kokoro(
            section_text,
            section_path,
            voice=voice,
            speed=speed,
            lang=lang,
            max_chars=max_chars,
        )
        section_files.append(section_path)
        logger.info(
            "Kokoro section %d/%d (%d chars): %s",
            i + 1, len(sections), len(section_text), section_path.name,
        )

    return section_files
