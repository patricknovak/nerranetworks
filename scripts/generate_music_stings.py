"""Generate unique podcast intro/outro stings for 6 Nerra Network shows.

Uses numpy + wave stdlib to synthesize ambient pad stings.
Each show gets a distinct harmonic palette, tempo, and character.

Output: assets/music/preview/<show_slug>.wav (38 seconds each, 44100 Hz stereo)
"""

import math
import struct
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 44100
DURATION = 38.0  # seconds
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "assets" / "music" / "preview"


def sine(freq: float, t: np.ndarray, phase: float = 0.0) -> np.ndarray:
    return np.sin(2 * np.pi * freq * t + phase)


def envelope_fade(t: np.ndarray, fade_in: float = 3.0, fade_out_start: float = 33.0, fade_out_dur: float = 5.0) -> np.ndarray:
    """Smooth fade-in and fade-out envelope."""
    env = np.ones_like(t)
    # Fade in (raised cosine)
    mask_in = t < fade_in
    env[mask_in] = 0.5 * (1 - np.cos(np.pi * t[mask_in] / fade_in))
    # Fade out
    mask_out = t > fade_out_start
    progress = (t[mask_out] - fade_out_start) / fade_out_dur
    progress = np.clip(progress, 0, 1)
    env[mask_out] = 0.5 * (1 + np.cos(np.pi * progress))
    return env


def add_reverb(signal: np.ndarray, delays_ms: list, decays: list) -> np.ndarray:
    """Simple multi-tap delay reverb."""
    result = signal.copy()
    for delay_ms, decay in zip(delays_ms, decays):
        delay_samples = int(SAMPLE_RATE * delay_ms / 1000)
        if delay_samples < len(signal):
            delayed = np.zeros_like(signal)
            delayed[delay_samples:] = signal[:-delay_samples] * decay
            result += delayed
    # Normalize to avoid clipping
    peak = np.max(np.abs(result))
    if peak > 0.95:
        result = result * 0.95 / peak
    return result


def write_wav(path: Path, signal: np.ndarray):
    """Write a mono float signal as stereo 16-bit WAV."""
    # Create stereo by slightly delaying right channel (wider stereo image)
    delay = int(SAMPLE_RATE * 0.012)  # 12ms Haas effect
    left = signal
    right = np.zeros_like(signal)
    right[delay:] = signal[:-delay] * 0.95

    # Convert to 16-bit PCM
    left_16 = np.clip(left * 32767, -32768, 32767).astype(np.int16)
    right_16 = np.clip(right * 32767, -32768, 32767).astype(np.int16)

    # Interleave L/R samples
    stereo = np.empty(len(left_16) * 2, dtype=np.int16)
    stereo[0::2] = left_16
    stereo[1::2] = right_16

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(stereo.tobytes())
    print(f"  Written: {path} ({path.stat().st_size / 1024:.0f} KB)")


def gen_env_intel(t: np.ndarray) -> np.ndarray:
    """Env Intel — Professional, serious, clean. D minor, slow evolving pad.
    Conveys regulatory authority. Minimal, spacious, deliberate."""
    env = envelope_fade(t, fade_in=3.5, fade_out_start=33, fade_out_dur=5)

    # D minor chord: D3, F3, A3 + octave D4
    signal = (
        0.25 * sine(146.83, t) +           # D3 (root)
        0.18 * sine(174.61, t) +           # F3 (minor third)
        0.20 * sine(220.00, t) +           # A3 (fifth)
        0.14 * sine(293.66, t) +           # D4 (octave)
        0.10 * sine(73.42, t)              # D2 (sub-bass)
    )

    # Very slow tremolo — stately, breathing
    tremolo = 0.85 + 0.15 * sine(0.12, t)
    signal *= tremolo * env * 0.75

    return add_reverb(signal, [60, 120, 200], [0.3, 0.2, 0.12])


def gen_models_agents(t: np.ndarray) -> np.ndarray:
    """Models & Agents — Digital, forward-moving, AI/tech feel.
    A minor with detuned layers creating beating/phasing. Electronic character."""
    env = envelope_fade(t, fade_in=2.0, fade_out_start=33, fade_out_dur=5)

    # A minor with detuning for electronic beating
    signal = (
        0.20 * sine(220.00, t) +           # A3
        0.12 * sine(221.80, t) +           # A3 detuned (beat freq ~1.8 Hz)
        0.18 * sine(261.63, t) +           # C4 (minor third)
        0.14 * sine(329.63, t) +           # E4 (fifth)
        0.10 * sine(331.00, t) +           # E4 detuned
        0.08 * sine(440.00, t) +           # A4 (octave)
        0.08 * sine(110.00, t)             # A2 (sub)
    )

    # Slightly faster tremolo — forward momentum
    tremolo = 0.80 + 0.20 * sine(0.22, t)

    # Subtle frequency-modulated shimmer on top
    shimmer = 0.06 * sine(523.25 * (1 + 0.003 * sine(0.5, t)), t)
    signal = (signal + shimmer) * tremolo * env * 0.70

    return add_reverb(signal, [40, 85, 150], [0.25, 0.18, 0.10])


def gen_models_agents_beginners(t: np.ndarray) -> np.ndarray:
    """M&A Beginners — Warm, friendly, approachable. C major, bright and gentle.
    Higher register with gentle movement. Welcoming for teens/beginners."""
    env = envelope_fade(t, fade_in=2.0, fade_out_start=33, fade_out_dur=5)

    # C major — universally happy and open
    signal = (
        0.20 * sine(261.63, t) +           # C4 (root)
        0.18 * sine(329.63, t) +           # E4 (major third)
        0.16 * sine(392.00, t) +           # G4 (fifth)
        0.10 * sine(523.25, t) +           # C5 (octave)
        0.08 * sine(130.81, t)             # C3 (sub)
    )

    # Gentle shimmer that slowly breathes in and out
    shimmer = 0.07 * sine(659.25, t) * np.maximum(0, sine(0.08, t))
    sparkle = 0.05 * sine(783.99, t) * np.maximum(0, sine(0.12, t, phase=0.5))

    # Gentle, warm tremolo
    tremolo = 0.85 + 0.15 * sine(0.18, t)
    signal = (signal + shimmer + sparkle) * tremolo * env * 0.72

    return add_reverb(signal, [80, 150, 250], [0.32, 0.22, 0.14])


def gen_finansy_prosto(t: np.ndarray) -> np.ndarray:
    """Финансы Просто — Warm, elegant, confident. F major, smooth pad.
    Warm low-mid frequencies with gentle shimmer. Sophisticated feel."""
    env = envelope_fade(t, fade_in=3.0, fade_out_start=33, fade_out_dur=5)

    # F major — warm and grounded
    signal = (
        0.22 * sine(174.61, t) +           # F3 (root)
        0.18 * sine(220.00, t) +           # A3 (major third)
        0.16 * sine(261.63, t) +           # C4 (fifth)
        0.10 * sine(349.23, t) +           # F4 (octave)
        0.10 * sine(87.31, t)              # F2 (sub-bass)
    )

    # Smooth, slow evolution with shimmer appearing and disappearing
    shimmer = 0.06 * sine(523.25, t) * np.maximum(0, sine(0.06, t))
    warm_layer = 0.05 * sine(440.00, t) * (0.5 + 0.5 * sine(0.04, t))

    # Very gentle breathing
    tremolo = 0.88 + 0.12 * sine(0.10, t)
    signal = (signal + shimmer + warm_layer) * tremolo * env * 0.75

    return add_reverb(signal, [90, 180, 280], [0.30, 0.22, 0.15])


def gen_modern_investing(t: np.ndarray) -> np.ndarray:
    """Modern Investing — Confident, precise, Bloomberg-esque. E minor with pulse.
    Rhythmic amplitude modulation gives a driving, analytical character."""
    env = envelope_fade(t, fade_in=2.0, fade_out_start=33, fade_out_dur=5)

    # E minor — serious but energetic
    signal = (
        0.20 * sine(164.81, t) +           # E3 (root)
        0.16 * sine(196.00, t) +           # G3 (minor third)
        0.18 * sine(246.94, t) +           # B3 (fifth)
        0.12 * sine(329.63, t) +           # E4 (octave)
        0.08 * sine(82.41, t)              # E2 (sub)
    )

    # Rhythmic pulse on root and fifth (~ 108 BPM feel)
    pulse_root = 0.08 * sine(164.81, t) * (0.6 + 0.4 * sine(1.8, t))
    pulse_fifth = 0.06 * sine(246.94, t) * (0.6 + 0.4 * sine(1.8, t, phase=1.57))

    # Clean high shimmer
    high = 0.05 * sine(493.88, t) * (0.5 + 0.5 * sine(0.9, t))

    tremolo = 0.82 + 0.18 * sine(0.15, t)
    signal = (signal + pulse_root + pulse_fifth + high) * tremolo * env * 0.72

    return add_reverb(signal, [50, 100, 170], [0.22, 0.15, 0.08])


def gen_privet_russian(t: np.ndarray) -> np.ndarray:
    """Привет, Русский! — Cheerful, bright, educational, playful. G major.
    Higher register with bouncy character. Fun and inviting for language learners."""
    env = envelope_fade(t, fade_in=2.0, fade_out_start=33, fade_out_dur=5)

    # G major — bright and cheerful
    signal = (
        0.18 * sine(196.00, t) +           # G3 (root)
        0.16 * sine(246.94, t) +           # B3 (major third)
        0.18 * sine(293.66, t) +           # D4 (fifth)
        0.12 * sine(392.00, t) +           # G4 (octave)
        0.08 * sine(98.00, t)              # G2 (sub)
    )

    # Playful shimmering overtones that dance in and out
    sparkle1 = 0.08 * sine(587.33, t) * np.maximum(0, sine(0.15, t))
    sparkle2 = 0.06 * sine(493.88, t) * np.maximum(0, sine(0.12, t, phase=1.0))
    twinkle = 0.05 * sine(783.99, t) * np.maximum(0, sine(0.10, t, phase=2.0))

    # Slightly bouncy tremolo — playful energy
    tremolo = 0.82 + 0.18 * sine(0.28, t)
    signal = (signal + sparkle1 + sparkle2 + twinkle) * tremolo * env * 0.72

    return add_reverb(signal, [70, 140, 220], [0.28, 0.20, 0.12])


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    n_samples = int(SAMPLE_RATE * DURATION)
    t = np.linspace(0, DURATION, n_samples, endpoint=False)

    shows = {
        "env_intel": gen_env_intel,
        "models_agents": gen_models_agents,
        "models_agents_beginners": gen_models_agents_beginners,
        "finansy_prosto": gen_finansy_prosto,
        "modern_investing": gen_modern_investing,
        "privet_russian": gen_privet_russian,
    }

    for slug, gen_func in shows.items():
        print(f"Generating {slug}...")
        signal = gen_func(t)
        write_wav(OUTPUT_DIR / f"{slug}.wav", signal)

    print(f"\nAll 6 stings generated in {OUTPUT_DIR}/")
    print("Listen to each one and let me know which to keep, adjust, or redo.")


if __name__ == "__main__":
    main()
