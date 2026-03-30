#!/usr/bin/env python3
"""
Backfill Omni View Episode 1 audio.

Why:
- Early Omni View runs created `omni_view_podcast.rss` entries pointing to an MP3 that was never committed,
  producing a 404 for the enclosure URL.

What this does:
- Reads `digests/summaries_omni.json` and extracts Episode 1 content (2026-01-23).
- Generates a short, spoken-friendly script from the stored summary content.
- Uses ElevenLabs TTS (chunked) to generate `digests/Omni_View_Ep001_20260123.mp3`.
- Updates `omni_view_podcast.rss` enclosure length + itunes:duration for that item.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
SUMMARY_JSON = ROOT / "digests" / "summaries_omni.json"
RSS_PATH = ROOT / "omni_view_podcast.rss"
OUT_MP3 = ROOT / "digests" / "Omni_View_Ep001_20260123.mp3"


def _chunk_text(text: str, max_chars: int = 4500) -> list[str]:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    buf: list[str] = []
    buf_len = 0

    for para in re.split(r"\n\s*\n", text):
        p = para.strip()
        if not p:
            continue
        if buf_len + len(p) + 2 > max_chars and buf:
            chunks.append("\n\n".join(buf))
            buf = [p]
            buf_len = len(p)
        else:
            buf.append(p)
            buf_len += len(p) + 2
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def _elevenlabs_tts_mp3(text: str, out_path: Path, voice_id: str) -> None:
    api_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is not set")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": os.getenv("ELEVENLABS_MODEL_ID", "eleven_v3"),
        "voice_settings": {
            "stability": float(os.getenv("ELEVENLABS_STABILITY", "0.35")),
            "similarity_boost": float(os.getenv("ELEVENLABS_SIMILARITY_BOOST", "0.75")),
            "style": float(os.getenv("ELEVENLABS_STYLE", "0.2")),
            "use_speaker_boost": True,
        },
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=180)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)


def _ffprobe_duration_seconds(path: Path) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return float((result.stdout or "").strip() or "0")
    except Exception:
        return 0.0


def _format_duration(seconds: float) -> str:
    if not seconds or seconds <= 0:
        return "00:00"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _extract_ep001_summary_content() -> str:
    if not SUMMARY_JSON.exists():
        raise FileNotFoundError(f"Missing {SUMMARY_JSON}")

    data = json.loads(SUMMARY_JSON.read_text(encoding="utf-8"))
    summaries = data.get("summaries") or []
    for s in summaries:
        if int(s.get("episode_num") or 0) == 1 and str(s.get("date") or "") == "2026-01-23":
            return str(s.get("content") or "")
    raise RuntimeError("Could not find episode 1 summary (date 2026-01-23) in summaries_omni.json")


def _build_spoken_script_from_summary(md: str) -> str:
    lines = [ln.rstrip() for ln in (md or "").splitlines()]

    # Pull out numbered headlines + sources when present.
    items: list[tuple[str, str]] = []
    i = 0
    item_re = re.compile(r"^\*\*(\d+)\.\s+(.*?)\*\*\s*$")
    src_re = re.compile(r"^\s*[📺📰🔍⚖️🎙️]*\s*\*(.*?)\*\s*$")

    while i < len(lines):
        m = item_re.match(lines[i].strip())
        if m:
            title = m.group(2).strip()
            source = ""
            if i + 1 < len(lines):
                m2 = src_re.match(lines[i + 1].strip())
                if m2:
                    source = m2.group(1).strip()
                    i += 1
            items.append((title, source))
        i += 1

    date_spoken = "January 23, 2026"
    intro = (
        "Omni View. Balanced news perspectives.\n\n"
        f"Here is your digest for {date_spoken}.\n\n"
        "These are headline summaries from a mix of sources across the spectrum.\n"
        "As always, treat this as a starting point, and read primary sources when you can.\n"
    )

    if not items:
        # Fallback: strip basic markdown and read the whole thing.
        cleaned = re.sub(r"\*\*(.*?)\*\*", r"\\1", md or "")
        cleaned = re.sub(r"\*(.*?)\*", r"\\1", cleaned)
        cleaned = re.sub(r"https?://\\S+", "", cleaned)
        return intro + "\n\n" + cleaned.strip()

    body_lines = []
    for idx, (title, source) in enumerate(items, 1):
        if source:
            body_lines.append(f"{idx}. {title}. Source: {source}.")
        else:
            body_lines.append(f"{idx}. {title}.")

    outro = (
        "\n\nThat's it for today.\n"
        "If you want the full written summary with links, open the Omni View summaries page.\n"
        "Thanks for listening."
    )
    return intro + "\n\n" + "\n".join(body_lines) + outro


def _generate_mp3(script_text: str) -> tuple[Path, float]:
    OUT_MP3.parent.mkdir(parents=True, exist_ok=True)

    # Keep in sync with Omni View default voice.
    voice_id = (os.getenv("OMNI_VIEW_ELEVENLABS_VOICE_ID") or "ns7MjJ6c8tJKnvw7U6sN").strip()
    chunks = _chunk_text(script_text, max_chars=int(os.getenv("ELEVENLABS_MAX_CHARS", "4500")))

    tmp_dir = Path(tempfile.gettempdir()) / "omni_view_backfill_tts"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    chunk_files: list[Path] = []
    for idx, chunk in enumerate(chunks, 1):
        chunk_path = tmp_dir / f"omni_view_backfill_ep001_{idx:02d}.mp3"
        _elevenlabs_tts_mp3(chunk, chunk_path, voice_id)
        chunk_files.append(chunk_path)

    if len(chunk_files) == 1:
        OUT_MP3.write_bytes(chunk_files[0].read_bytes())
    else:
        list_file = tmp_dir / "omni_view_backfill_ep001_concat.txt"
        list_file.write_text("\n".join([f"file '{p.as_posix()}'" for p in chunk_files]), encoding="utf-8")
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(OUT_MP3)],
            check=True,
            capture_output=True,
        )

    duration = _ffprobe_duration_seconds(OUT_MP3)
    return OUT_MP3, duration


def _update_rss_enclosure_for_ep1(mp3: Path, duration_seconds: float) -> None:
    if not RSS_PATH.exists():
        raise FileNotFoundError(f"Missing {RSS_PATH}")

    import xml.etree.ElementTree as ET

    itunes_ns = "http://www.itunes.com/dtds/podcast-1.0.dtd"
    ET.register_namespace("itunes", itunes_ns)

    tree = ET.parse(str(RSS_PATH))
    root = tree.getroot()
    channel = root.find("channel")
    if channel is None:
        raise RuntimeError("RSS channel not found")

    target_name = mp3.name
    mp3_size = str(mp3.stat().st_size)
    dur_str = _format_duration(duration_seconds)

    updated = False
    for item in channel.findall("item"):
        enc = item.find("enclosure")
        if enc is None:
            continue
        url = (enc.get("url") or "").strip()
        if url.endswith("/" + target_name) or url.endswith(target_name):
            enc.set("length", mp3_size)
            # Update <link> too (some clients look at it)
            link_el = item.find("link")
            if link_el is not None:
                link_el.text = url

            dur_el = item.find(f"{{{itunes_ns}}}duration")
            if dur_el is not None:
                dur_el.text = dur_str
            updated = True

    if not updated:
        raise RuntimeError(f"Could not find RSS item for enclosure {target_name}")

    # Touch lastBuildDate to "now"
    lbd = channel.find("lastBuildDate")
    if lbd is not None:
        lbd.text = _dt.datetime.now(_dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")

    tree.write(str(RSS_PATH), encoding="utf-8", xml_declaration=True)


def main() -> int:
    load_dotenv()

    md = _extract_ep001_summary_content()
    spoken = _build_spoken_script_from_summary(md)
    mp3, dur = _generate_mp3(spoken)
    _update_rss_enclosure_for_ep1(mp3, dur)
    print(f"Backfilled {mp3} ({dur:.1f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

