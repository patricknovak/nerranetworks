# Voice Reference Samples

Stable voice reference audio clips extracted from existing podcast episodes.
These are used by zero-shot voice cloning TTS models (e.g., Fish Audio,
Chatterbox, Qwen3-TTS, Orpheus) to reproduce the show's voice without training.

## Files

| File | Source | Duration | Format | Notes |
|------|--------|----------|--------|-------|
| `tst_voice_reference.wav` | TST Ep397 (2026-03-03) | 30 s | 24 kHz, mono, PCM 16-bit | Extracted at 35 s offset (after intro music) |
| `russian_female_reference.wav` | **NEEDED** | 10-30 s | 24 kHz, mono, PCM 16-bit | Russian female voice for Финансы Просто show. See instructions below. |

## Extraction Method

```bash
# 1. Pull a recent episode from git history
git show <commit>:digests/tesla_shorts_time/<episode>.mp3 > /tmp/episode.mp3

# 2. Skip intro music (first ~25-35s), grab 30s of clean speech
ffmpeg -y -i /tmp/episode.mp3 -ss 35 -t 30 -ar 24000 -ac 1 tst_voice_reference.wav
```

### Why 35 seconds offset?

The TST music mixing config (`shows/tesla.yaml`) uses:
- 5 s voice intro delay (music plays alone)
- 10 s music overlap with voice
- 10 s music fadeout

Music is fully gone by ~25 s. Starting at 35 s provides a comfortable margin
for clean, music-free speech.

## Best Practices

- **Format:** WAV or FLAC (lossless). Never use MP3 for reference samples.
- **Duration:** 10-30 seconds is the sweet spot for most zero-shot models.
- **Content:** Natural speech with varied intonation, not monotone reading.
- **Quality:** No background music, no room echo, no clipping.

## Adding New References

For other shows, follow the same extraction pattern. Check each show's YAML
config for its specific music timing to determine the correct offset:

| Show | Config | Approx. clean voice starts at |
|------|--------|-------------------------------|
| TST  | `shows/tesla.yaml` | ~25-30 s |
| FF   | `shows/fascinating_frontiers.yaml` | Check config |
| PT   | `shows/planetterrian.yaml` | Check config |
| OV   | `shows/omni_view.yaml` | Check config |
| EI   | `shows/env_intel.yaml` | Check config |
| M&A  | `shows/models_agents.yaml` | Check config |

## Финансы Просто (Russian Female Voice)

The `russian_female_reference.wav` file is **required before the first episode
can be generated**. This file should contain 10-30 seconds of natural Russian
female speech (warm, conversational tone — like explaining something to a friend).

### Options for sourcing:

1. **Record a sample** — Have a native Russian speaker read a short paragraph
   naturally. Record at 24 kHz mono WAV.
2. **Public domain audio** — Find a CC0/public domain Russian female speech
   sample (e.g., from LibriVox Russian audiobooks or Mozilla Common Voice).
3. **Fish Audio voice gallery** — Use a pre-existing Russian female voice from
   Fish Audio's public gallery instead of zero-shot cloning. Update
   `shows/finansy_prosto.yaml` to use a `voice_id` instead of `reference_audio`.

### Format requirements:
```bash
# Convert any source audio to the correct format:
ffmpeg -y -i source_audio.mp3 -ss <offset> -t 30 -ar 24000 -ac 1 russian_female_reference.wav
```
