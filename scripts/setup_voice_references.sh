#!/usr/bin/env bash
# Download and extract voice reference samples for Fish Audio TTS shows.
# Run this script locally before the first episode of any Fish Audio show.
#
# Usage: ./scripts/setup_voice_references.sh
#
# Source: LibriVox public domain audiobooks (CC0)

set -euo pipefail

VOICE_DIR="assets/voice_references"
mkdir -p "$VOICE_DIR"

# ---------------------------------------------------------------------------
# Hanna Ponomarenko — Russian female voice for Финансы Просто
# Source: "Избранные" by Sholem Aleichem, read by Hanna Ponomarenko (LibriVox)
# https://archive.org/details/izbrannye_2212_librivox
# ---------------------------------------------------------------------------
HANNA_REF="$VOICE_DIR/hanna_ponomarenko_reference.wav"
if [ -f "$HANNA_REF" ]; then
    echo "✓ $HANNA_REF already exists, skipping."
else
    echo "Downloading Hanna Ponomarenko voice sample from LibriVox..."
    TMP_MP3="/tmp/hanna_ch01.mp3"

    # Download Chapter 1 (128kbps version preferred, fallback to 64kbps)
    curl -L --fail --retry 3 -o "$TMP_MP3" \
        "https://www.archive.org/download/izbrannye_2212_librivox/izbrannye_01_alejhem_128kb.mp3" 2>/dev/null \
    || curl -L --fail --retry 3 -o "$TMP_MP3" \
        "https://www.archive.org/download/izbrannye_2212_librivox/izbrannye_01_alejhem_64kb.mp3"

    # Extract 30s of clean speech (skip 15s LibriVox intro)
    ffmpeg -y -i "$TMP_MP3" -ss 15 -t 30 -ar 24000 -ac 1 "$HANNA_REF"

    rm -f "$TMP_MP3"

    # Verify
    DURATION=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$HANNA_REF" 2>/dev/null | cut -d. -f1)
    if [ "$DURATION" -ge 25 ] 2>/dev/null; then
        echo "✓ Created $HANNA_REF (${DURATION}s, $(du -h "$HANNA_REF" | cut -f1))"
    else
        echo "✗ WARNING: $HANNA_REF may be too short (${DURATION}s). Check manually."
    fi
fi

echo ""
echo "Voice references setup complete."
echo "Files in $VOICE_DIR:"
ls -lh "$VOICE_DIR"/*.wav 2>/dev/null || echo "  (no WAV files found)"
