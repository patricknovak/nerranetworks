"""Episode cost and usage tracking for the podcast generation pipeline.

Provides:
  - create_tracker(): initialize a per-episode usage tracking dict
  - record_llm_usage(): record LLM token usage for a generation step
  - record_tts_usage(): record TTS character count
  - record_x_post(): increment X API post counter
  - save_usage(): finalize costs and write JSON file
"""

import datetime
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ElevenLabs pricing: $0.30 per 1000 characters
ELEVENLABS_COST_PER_1K_CHARS = 0.30


def create_tracker(show_name: str, episode_num: int) -> dict:
    """Create a fresh per-episode usage tracker."""
    return {
        "date": datetime.date.today().isoformat(),
        "show": show_name,
        "episode_number": episode_num,
        "services": {
            "grok_api": {
                "x_thread_generation": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                },
                "podcast_script_generation": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                },
                "total_tokens": 0,
                "total_cost_usd": 0.0,
            },
            "elevenlabs_api": {
                "provider": "elevenlabs",
                "characters": 0,
                "estimated_cost_usd": 0.0,
            },
            "x_api": {
                "search_calls": 0,
                "post_calls": 0,
                "total_calls": 0,
            },
        },
        "total_estimated_cost_usd": 0.0,
    }


def record_llm_usage(
    tracker: dict,
    step: str,
    prompt_tokens: int,
    completion_tokens: int,
    estimated_cost_usd: float = 0.0,
) -> None:
    """Record LLM token usage for a generation step.

    *step* should be ``"x_thread_generation"`` or
    ``"podcast_script_generation"``.
    """
    grok = tracker["services"]["grok_api"]
    if step not in grok:
        grok[step] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
        }
    grok[step]["prompt_tokens"] += prompt_tokens
    grok[step]["completion_tokens"] += completion_tokens
    grok[step]["total_tokens"] += prompt_tokens + completion_tokens
    grok[step]["estimated_cost_usd"] += estimated_cost_usd


def record_tts_usage(tracker: dict, characters: int) -> None:
    """Record TTS character usage."""
    tracker["services"]["elevenlabs_api"]["characters"] += characters


def record_x_post(tracker: dict) -> None:
    """Increment the X API post counter."""
    tracker["services"]["x_api"]["post_calls"] += 1


def save_usage(tracker: dict, output_dir: Path) -> Path | None:
    """Finalize cost calculations and write the tracker to a JSON file.

    Returns the path to the saved file, or ``None`` on error.
    """
    try:
        grok = tracker["services"]["grok_api"]
        # Sum up LLM totals
        grok["total_tokens"] = (
            grok["x_thread_generation"]["total_tokens"]
            + grok["podcast_script_generation"]["total_tokens"]
        )
        grok["total_cost_usd"] = (
            grok["x_thread_generation"]["estimated_cost_usd"]
            + grok["podcast_script_generation"]["estimated_cost_usd"]
        )

        x_api = tracker["services"]["x_api"]
        x_api["total_calls"] = x_api["search_calls"] + x_api["post_calls"]

        # ElevenLabs cost
        el = tracker["services"]["elevenlabs_api"]
        el["estimated_cost_usd"] = (el["characters"] / 1000) * ELEVENLABS_COST_PER_1K_CHARS

        tracker["total_estimated_cost_usd"] = (
            grok["total_cost_usd"] + el["estimated_cost_usd"]
        )

        # Write file
        filename = f"credit_usage_{tracker['date']}_ep{tracker['episode_number']:03d}.json"
        filepath = output_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(tracker, f, indent=2)

        # Log summary
        logger.info("=" * 60)
        logger.info("CREDIT USAGE SUMMARY")
        logger.info("=" * 60)
        logger.info(
            "Grok API (X Thread): %d tokens ($%.4f)",
            grok["x_thread_generation"]["total_tokens"],
            grok["x_thread_generation"]["estimated_cost_usd"],
        )
        logger.info(
            "Grok API (Podcast): %d tokens ($%.4f)",
            grok["podcast_script_generation"]["total_tokens"],
            grok["podcast_script_generation"]["estimated_cost_usd"],
        )
        logger.info(
            "TTS (ElevenLabs): %d chars ($%.4f)",
            el["characters"],
            el["estimated_cost_usd"],
        )
        logger.info(
            "X API: %d calls (search: %d, post: %d)",
            x_api["total_calls"],
            x_api["search_calls"],
            x_api["post_calls"],
        )
        logger.info("TOTAL ESTIMATED COST: $%.4f", tracker["total_estimated_cost_usd"])
        logger.info("=" * 60)
        logger.info("Credit usage saved to %s", filepath)

        return filepath

    except Exception as exc:
        logger.error("Failed to save credit usage: %s", exc, exc_info=True)
        return None
