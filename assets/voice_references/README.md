# Voice Reference Samples

Stable voice reference audio clips extracted from existing podcast episodes.
These are used by zero-shot voice cloning TTS models (e.g., Fish Audio,
Chatterbox, Qwen3-TTS, Orpheus) to reproduce the show's voice without training.

## Files

| File | Source | Duration | Format | Notes |
|------|--------|----------|--------|-------|
| `tst_voice_reference.wav` | TST Ep397 (2026-03-03) | 30 s | 24 kHz, mono, PCM 16-bit | Extracted at 35 s offset (after intro music) |

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
