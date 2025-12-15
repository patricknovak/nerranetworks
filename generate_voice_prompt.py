#!/usr/bin/env python3
"""
Generate a permanent Chatterbox voice prompt file from an episode MP3.

This script extracts a clean voice sample from an episode MP3 and saves it
as a permanent WAV file that can be reused across all podcast workflows.

Usage:
    python generate_voice_prompt.py <source_episode.mp3> [output_name.wav]
    
Example:
    python generate_voice_prompt.py digests/planetterrian/Planetterrian_Daily_Ep012_20251212.mp3 assets/voice_prompts/patrick_voice_prompt.wav
"""

import sys
import subprocess
from pathlib import Path

# Default settings (can be overridden via command line)
DEFAULT_OFFSET_SECONDS = 35.0  # Start after intro music
DEFAULT_DURATION_SECONDS = 10.0  # 10 seconds of voice
DEFAULT_SAMPLE_RATE = 16000  # 16kHz mono (Chatterbox requirement)
DEFAULT_CHANNELS = 1  # Mono


def generate_voice_prompt(
    source_mp3: Path,
    output_wav: Path,
    offset_seconds: float = DEFAULT_OFFSET_SECONDS,
    duration_seconds: float = DEFAULT_DURATION_SECONDS,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channels: int = DEFAULT_CHANNELS,
) -> None:
    """
    Extract a voice prompt from an episode MP3.
    
    Args:
        source_mp3: Path to source episode MP3 file
        output_wav: Path where output WAV file will be saved
        offset_seconds: Start time in seconds (skip intro music)
        duration_seconds: Duration of voice sample in seconds
        sample_rate: Output sample rate (default 16000 for Chatterbox)
        channels: Number of audio channels (default 1 for mono)
    """
    if not source_mp3.exists():
        raise FileNotFoundError(f"Source MP3 not found: {source_mp3}")
    
    # Ensure output directory exists
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Extracting voice prompt from: {source_mp3.name}")
    print(f"  Offset: {offset_seconds}s")
    print(f"  Duration: {duration_seconds}s")
    print(f"  Output: {output_wav}")
    
    # Use ffmpeg to extract the voice sample
    subprocess.run(
        [
            "ffmpeg",
            "-y",  # Overwrite output file
            "-ss", str(offset_seconds),
            "-t", str(duration_seconds),
            "-i", str(source_mp3),
            "-ac", str(channels),  # Mono
            "-ar", str(sample_rate),  # 16kHz
            "-c:a", "pcm_s16le",  # 16-bit PCM WAV
            str(output_wav),
        ],
        check=True,
        capture_output=True,
    )
    
    if output_wav.exists():
        file_size = output_wav.stat().st_size
        print(f"✅ Voice prompt created successfully!")
        print(f"   File size: {file_size / 1024:.1f} KB")
        print(f"   Location: {output_wav}")
        print(f"\nTo use this voice prompt, set in your .env file:")
        print(f"   CHATTERBOX_VOICE_PROMPT_PATH={output_wav.absolute()}")
    else:
        raise RuntimeError(f"Output file was not created: {output_wav}")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    source_mp3 = Path(sys.argv[1])
    
    if len(sys.argv) >= 3:
        output_wav = Path(sys.argv[2])
    else:
        # Default: save to assets/voice_prompts/ with same name as source
        output_wav = Path("assets") / "voice_prompts" / f"{source_mp3.stem}_prompt.wav"
    
    # Optional: override offset/duration via environment variables
    import os
    offset = float(os.getenv("VOICE_PROMPT_OFFSET", DEFAULT_OFFSET_SECONDS))
    duration = float(os.getenv("VOICE_PROMPT_DURATION", DEFAULT_DURATION_SECONDS))
    
    try:
        generate_voice_prompt(source_mp3, output_wav, offset, duration)
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

