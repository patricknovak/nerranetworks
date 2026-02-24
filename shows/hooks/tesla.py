"""Tesla-specific pre-fetch hook.

Provides extra context that the Tesla Shorts Time digest prompt needs:
- TSLA stock price and change string via yfinance
- X posts section placeholder (disabled by default)
- Market movers section (Monday only)
- Content tracking for freshness
"""

from __future__ import annotations

import datetime
import logging
import re

from engine.utils import number_to_words

logger = logging.getLogger(__name__)


def pre_fetch(config) -> dict:
    """Return extra template variables for the Tesla digest/podcast prompts.

    Called by ``run_show.py`` before digest generation.  Returns a dict
    that gets merged into the prompt template variables.
    """
    context: dict = {}

    # Stock price via yfinance
    price, change_str = _fetch_tsla_price()
    context["price"] = f"{price:.2f}"
    context["change_str"] = change_str

    # X posts section (disabled — placeholder)
    context["x_posts_section"] = ""

    # Used content summary (recent stories tracking — placeholder)
    context["used_content_summary"] = ""

    # Market movers (Monday only)
    if datetime.date.today().weekday() == 0:  # Monday
        context["market_movers_section"] = (
            "\n\n━━━━━━━━━━━━━━━━━━━━\n"
            "### Tesla Market Movers\n"
            "📊 Weekly Market Recap — Summarize this past week's key TSLA "
            "price movements, catalysts, and market sentiment shifts."
        )
    else:
        context["market_movers_section"] = ""

    # Podcast-specific vars
    context["tone_hint"] = _tone_from_change(change_str)
    context["intro_line"] = _pick_intro(context)
    context["closing_block"] = _pick_closing()

    return context


def pronunciation_overrides() -> dict:
    """Return Tesla-specific pronunciation overrides.

    Called by ``run_show.py:_apply_pronunciation()`` to customize the
    shared ``prepare_text_for_tts()`` pipeline.
    """
    return {
        # Don't expand "ICE" to "I C E" — Tesla context uses it as
        # "internal combustion engine" but TTS reads it fine as the word.
        "skip_acronyms": {"ICE"},
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_tsla_price() -> tuple[float, str]:
    """Get current TSLA price and change string via yfinance."""
    try:
        import yfinance as yf

        ticker = yf.Ticker("TSLA")
        info = ticker.fast_info
        price = info.last_price
        prev_close = info.previous_close
        change = price - prev_close
        pct = (change / prev_close) * 100 if prev_close else 0
        direction = "▲" if change >= 0 else "▼"
        change_str = f"{direction} ${abs(change):.2f} ({abs(pct):.1f}%)"
        logger.info("TSLA: $%.2f %s", price, change_str)
        return price, change_str
    except Exception as exc:
        logger.warning("yfinance lookup failed: %s — using placeholder", exc)
        return 0.0, "(price unavailable)"


def _format_price_for_speech(price_str: str) -> str:
    """Convert a price string like '411.82' to spoken words."""
    try:
        price = float(price_str)
        whole = int(price)
        cents = round((price - whole) * 100)
        whole_words = number_to_words(whole)
        if cents:
            cents_words = number_to_words(cents)
            return f"{whole_words} dollars and {cents_words} cents"
        return f"{whole_words} dollars"
    except (ValueError, TypeError):
        return f"{price_str} dollars"


def _format_change_for_speech(change_str: str) -> str:
    """Convert '▲ $0.57 (0.1%)' to natural speech like 'up fifty-seven cents, zero point one percent'."""
    if not change_str or change_str == "(price unavailable)":
        return "price unavailable"

    direction = "up" if "▲" in change_str else "down"

    # Extract dollar amount and percentage
    dollar_match = re.search(r"\$([\d.]+)", change_str)
    pct_match = re.search(r"([\d.]+)%", change_str)

    parts = [direction]

    if dollar_match:
        try:
            amount = float(dollar_match.group(1))
            whole = int(amount)
            cents = round((amount - whole) * 100)
            if whole > 0 and cents > 0:
                parts.append(f"{number_to_words(whole)} dollars and {number_to_words(cents)} cents")
            elif whole > 0:
                parts.append(f"{number_to_words(whole)} dollars")
            elif cents > 0:
                parts.append(f"{number_to_words(cents)} cents")
        except (ValueError, TypeError):
            pass

    if pct_match:
        try:
            pct_val = float(pct_match.group(1))
            pct_words = number_to_words(pct_val)
            parts.append(f"{pct_words} percent")
        except (ValueError, TypeError):
            pass

    return ", ".join(parts)


def _tone_from_change(change_str: str) -> str:
    """Pick a tone hint based on price movement."""
    if "▲" in change_str:
        return "bullish/up — upbeat and energetic"
    elif "▼" in change_str:
        return "bearish/down — thoughtful but still optimistic"
    return "mixed/unchanged — natural and conversational"


def _pick_intro(context: dict) -> str:
    """Return a standard intro line for the podcast script.

    Uses pre-formatted spoken-word price so TTS reads it naturally.
    """
    price = context.get("price", "0.00")
    change = context.get("change_str", "")

    price_spoken = _format_price_for_speech(price)
    change_spoken = _format_change_for_speech(change)

    return (
        f"Patrick: Welcome to Tesla Shorts Time Daily! I'm Patrick in "
        f"Vancouver, Canada. T S L A is trading at {price_spoken}, "
        f"{change_spoken}. Let's dive into today's Tesla news."
    )


def _pick_closing() -> str:
    """Return a standard closing block for the podcast script."""
    return (
        "Patrick: That's all for today's Tesla Shorts Time Daily. "
        "If you enjoyed this episode, please like, share, rate, and subscribe. "
        "It really helps the show grow. You can find us on X at tesla shorts time. "
        "We'll catch you tomorrow. Stay charged!"
    )
