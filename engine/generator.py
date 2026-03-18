"""LLM interaction module for podcast digest and script generation.

Loads prompt templates from files, fills in template variables, and calls the
xAI/Grok API.  All shows use the OpenAI-compatible endpoint unless tools
(web search / X search) are explicitly requested.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

# Only retry on transient API errors — permanent errors (KeyError, FileNotFoundError,
# RuntimeError) will fail immediately instead of wasting 3x API credits.
try:
    from openai import APITimeoutError, APIConnectionError, RateLimitError
    _TRANSIENT_ERRORS = (APITimeoutError, APIConnectionError, RateLimitError)
except ImportError:
    # Fallback if openai isn't installed (e.g. in tests)
    _TRANSIENT_ERRORS = (TimeoutError, ConnectionError)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompt template loading
# ---------------------------------------------------------------------------

def load_prompt(prompt_file: str, template_vars: Optional[Dict[str, Any]] = None) -> str:
    """Read a prompt template file and fill in ``{placeholder}`` variables.

    Parameters
    ----------
    prompt_file:
        Path to a ``.txt`` file containing the prompt template.  May be
        relative (resolved from cwd) or absolute.
    template_vars:
        Dict of values to substitute into ``{key}`` placeholders.  Uses
        ``str.format_map`` so missing keys raise ``KeyError``.  Pass
        ``None`` to skip substitution (useful for reference-only files).
    """
    path = Path(prompt_file)
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    if template_vars is not None:
        return raw.format_map(template_vars)
    return raw


# ---------------------------------------------------------------------------
# xAI / Grok API call
# ---------------------------------------------------------------------------

def _get_api_key() -> str:
    return (os.getenv("GROK_API_KEY") or os.getenv("XAI_API_KEY") or "").strip()


def _call_grok(
    prompt: str,
    *,
    model: str = "grok-4.20-beta-0309-non-reasoning",
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 3500,
    timeout: float = 300.0,
) -> tuple[str, Dict[str, Any]]:
    """Call xAI Grok via the OpenAI-compatible endpoint.

    Returns ``(text, meta)`` where *meta* contains usage info.
    """
    from openai import OpenAI

    api_key = _get_api_key()
    if not api_key:
        raise RuntimeError("Missing GROK_API_KEY (or XAI_API_KEY).")

    client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1", timeout=timeout)

    messages: list[dict] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    text = resp.choices[0].message.content.strip()
    meta: Dict[str, Any] = {"provider": "openai_compat", "model": model}
    if hasattr(resp, "usage") and resp.usage:
        meta["usage"] = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        }
    return text, meta


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

# Patterns that suggest leaked prompt instructions in the output
_INSTRUCTION_LEAK_PATTERNS = [
    r"(?i)^(RULES|NEVER INCLUDE|CONTENT FOCUS|TONE|SCRIPT STRUCTURE)\s*:",
    r"(?i)\{[a-z_]+\}",  # Unfilled template placeholders
    r"(?i)^(Use this exact|Deliver this hook|Narrate EVERY|Here is today)",
    r"(?i)^As an AI",
    r"(?i)^I('m| am) (an AI|a language model|ChatGPT|GPT|Claude)",
]

_MIN_CHARS = {"digest": 200, "podcast_script": 500}


def _validate_llm_output(
    text: str,
    stage: str = "digest",
    show_name: str = "unknown",
) -> None:
    """Warn if LLM output appears empty, too short, or contains leaked instructions.

    Does not raise — it logs warnings so the pipeline can still proceed
    (an imperfect episode is better than no episode), but operators are
    alerted to quality issues.
    """
    import re

    if not text or not text.strip():
        logger.error(
            "LLM returned EMPTY %s for '%s' — episode will likely be unusable",
            stage, show_name,
        )
        return

    char_count = len(text.strip())
    min_chars = _MIN_CHARS.get(stage, 200)
    if char_count < min_chars:
        logger.warning(
            "LLM %s for '%s' is suspiciously short (%d chars, minimum expected %d)",
            stage, show_name, char_count, min_chars,
        )

    # Check for leaked prompt instructions
    for pattern in _INSTRUCTION_LEAK_PATTERNS:
        if re.search(pattern, text, re.MULTILINE):
            logger.warning(
                "LLM %s for '%s' may contain leaked prompt instructions (matched: %s)",
                stage, show_name, pattern,
            )
            break

    # Check for potential hallucinations — words repeated 4+ times in close
    # proximity often indicate corruption (e.g. "Nano Banana 2" x4)
    words = text.split()
    if len(words) > 50:
        # Scan for any 2-3 word phrase that appears 4+ times
        from collections import Counter
        bigrams = [" ".join(words[i:i+2]).lower() for i in range(len(words) - 1)]
        bigram_counts = Counter(bigrams)
        for phrase, count in bigram_counts.most_common(5):
            # Skip common phrases
            if phrase in ("the the", "of the", "in the", "to the", "and the", "on the", "for the", "is the"):
                continue
            if count >= 4:
                logger.warning(
                    "LLM %s for '%s' has suspicious repetition: '%s' appears %d times (possible hallucination)",
                    stage, show_name, phrase, count,
                )

    # Warn if podcast script is too short to fill target duration
    if stage == "podcast_script":
        word_count = len(text.split())
        if word_count < 1500:
            logger.warning(
                "Podcast script for '%s' is too short (%d words, target >1500). "
                "Consider regenerating with more depth.",
                show_name, word_count,
            )


# ---------------------------------------------------------------------------
# Public generation functions
# ---------------------------------------------------------------------------

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    retry=retry_if_exception_type(_TRANSIENT_ERRORS),
)
def generate_digest(
    template_vars: Dict[str, Any],
    config,
    tracker: Optional[dict] = None,
) -> str:
    """Generate the news digest text using the show's digest prompt.

    Parameters
    ----------
    template_vars:
        Values to fill into the prompt template (e.g. ``today_str``,
        ``news_section``, ``price``, etc.).
    config:
        A ``ShowConfig`` instance.
    tracker:
        Optional cost-tracking dict (from ``engine.tracking``).

    Returns
    -------
    str
        The generated digest text.
    """
    prompt = load_prompt(config.llm.digest_prompt_file, template_vars)

    system_prompt = None
    if config.llm.system_prompt_file:
        sp_path = Path(config.llm.system_prompt_file)
        if sp_path.exists():
            system_prompt = sp_path.read_text(encoding="utf-8").strip()

    logger.info("Generating digest for '%s' (model=%s, temp=%.1f) ...",
                config.name, config.llm.model, config.llm.digest_temperature)

    text, meta = _call_grok(
        prompt,
        model=config.llm.model,
        system_prompt=system_prompt,
        temperature=config.llm.digest_temperature,
        max_tokens=config.llm.max_tokens,
    )

    if tracker and "usage" in meta:
        try:
            from engine.tracking import record_llm_usage
            record_llm_usage(
                tracker,
                "x_thread_generation",
                meta["usage"].get("prompt_tokens", 0),
                meta["usage"].get("completion_tokens", 0),
                model=config.llm.model,
            )
        except Exception as e:
            logger.warning("Failed to record LLM usage: %s", e)

    logger.info("Digest generated (%d chars, %s tokens)",
                len(text), meta.get("usage", {}).get("total_tokens", "?"))

    # Validate the digest is usable
    _validate_llm_output(text, stage="digest", show_name=config.name)

    return text


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    retry=retry_if_exception_type(_TRANSIENT_ERRORS),
)
def generate_podcast_script(
    template_vars: Dict[str, Any],
    config,
    tracker: Optional[dict] = None,
) -> str:
    """Generate a podcast script from the show's podcast prompt.

    Parameters
    ----------
    template_vars:
        Values to fill into the podcast prompt template (e.g.
        ``episode_num``, ``digest``, ``today_str``, etc.).
    config:
        A ``ShowConfig`` instance.
    tracker:
        Optional cost-tracking dict.

    Returns
    -------
    str
        The generated podcast script text.
    """
    prompt = load_prompt(config.llm.podcast_prompt_file, template_vars)

    system_prompt = None
    if config.llm.system_prompt_file:
        sp_path = Path(config.llm.system_prompt_file)
        if sp_path.exists():
            system_prompt = sp_path.read_text(encoding="utf-8").strip()

    logger.info("Generating podcast script for '%s' (model=%s, temp=%.1f) ...",
                config.name, config.llm.model, config.llm.podcast_temperature)

    # Use podcast-specific max_tokens if configured, otherwise fall back to shared max_tokens
    podcast_tokens = getattr(config.llm, "podcast_max_tokens", 0) or config.llm.max_tokens

    text, meta = _call_grok(
        prompt,
        model=config.llm.model,
        system_prompt=system_prompt,
        temperature=config.llm.podcast_temperature,
        max_tokens=podcast_tokens,
    )

    if tracker and "usage" in meta:
        try:
            from engine.tracking import record_llm_usage
            record_llm_usage(
                tracker,
                "podcast_script_generation",
                meta["usage"].get("prompt_tokens", 0),
                meta["usage"].get("completion_tokens", 0),
                model=config.llm.model,
            )
        except Exception as e:
            logger.warning("Failed to record LLM usage: %s", e)

    logger.info("Podcast script generated (%d chars, %s tokens)",
                len(text), meta.get("usage", {}).get("total_tokens", "?"))

    # Validate the podcast script is usable
    _validate_llm_output(text, stage="podcast_script", show_name=config.name)

    return text
