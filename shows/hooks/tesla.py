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


def fix_pronunciation(text: str) -> str:
    """Apply Tesla-specific pronunciation fixes on top of shared ones."""
    try:
        from assets.pronunciation import PRONUNCIATION_FIXES
        for pattern, replacement in PRONUNCIATION_FIXES:
            text = re.sub(pattern, replacement, text)
    except ImportError:
        pass

    # Tesla-specific: strip "Patrick:" prefixes and stage directions
    text = re.sub(r"^Patrick:\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[.*?\]", "", text)
    return text.strip()


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


def _tone_from_change(change_str: str) -> str:
    """Pick a tone hint based on price movement."""
    if "▲" in change_str:
        return "bullish/up — upbeat and energetic"
    elif "▼" in change_str:
        return "bearish/down — thoughtful but still optimistic"
    return "mixed/unchanged — natural and conversational"


def _pick_intro(context: dict) -> str:
    """Return a standard intro line for the podcast script."""
    price = context.get("price", "0.00")
    change = context.get("change_str", "")
    return (
        f"Patrick: Welcome to Tesla Shorts Time Daily! I'm Patrick in "
        f"Vancouver, Canada. TSLA is trading at ${price} {change}. "
        f"Let's dive into today's Tesla news."
    )


def _pick_closing() -> str:
    """Return a standard closing block for the podcast script."""
    return (
        "Patrick: That's all for today's Tesla Shorts Time Daily. "
        "If you enjoyed this episode, please like, share, rate, and subscribe. "
        "It really helps the show grow. You can find us on X at @teslashortstime. "
        "We'll catch you tomorrow. Stay charged!"
    )
