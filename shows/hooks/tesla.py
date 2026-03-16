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


def pre_fetch(config, *, episode_num: int | None = None, today_str: str | None = None) -> dict:
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
    # Intro/closing are now handled by engine.intros (day-varying, dynamic).
    # Tesla hook only provides stock-specific closing with price data.
    context["closing_block"] = _pick_closing(context)

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
    """Get current TSLA price and change string via yfinance.

    Uses multiple fallback strategies with retries to ensure accurate
    stock data:
      1. fast_info (lightweight, real-time)
      2. history fallback (2-day OHLC data)
      3. Retries up to 3 times with exponential backoff
    """
    import time as _time

    price = None
    prev_close = None
    market_status = ""

    for attempt in range(3):
        try:
            import yfinance as yf
            ticker = yf.Ticker("TSLA")

            # Strategy 1: fast_info (lightweight real-time data)
            try:
                info = ticker.fast_info
                price = (
                    getattr(info, "last_price", None)
                    or getattr(info, "regularMarketPrice", None)
                    or getattr(info, "postMarketPrice", None)
                )
                prev_close = getattr(info, "previous_close", None)
                market_state = str(
                    getattr(info, "market_state", "")
                    or getattr(info, "marketState", "")
                )
                if market_state.upper() == "POST":
                    market_status = " (After-hours)"
                elif market_state.upper() == "PRE":
                    market_status = " (Pre-market)"
            except Exception as e:
                logger.warning("fast_info failed (attempt %d): %s", attempt + 1, e)

            # Strategy 2: history fallback if fast_info didn't return data
            if price is None or prev_close is None:
                try:
                    hist = ticker.history(period="5d", interval="1d")
                    if not hist.empty:
                        price = price or float(hist["Close"].iloc[-1])
                        if len(hist) > 1 and prev_close is None:
                            prev_close = float(hist["Close"].iloc[-2])
                except Exception as e:
                    logger.warning("History fallback failed (attempt %d): %s", attempt + 1, e)

            if price is not None:
                if prev_close is None:
                    prev_close = price  # No change data available
                change = price - prev_close
                pct = (change / prev_close) * 100 if prev_close else 0
                direction = "▲" if change >= 0 else "▼"
                change_str = f"{direction} ${abs(change):.2f} ({abs(pct):.1f}%){market_status}"
                logger.info("TSLA: $%.2f %s (attempt %d)", price, change_str, attempt + 1)
                return price, change_str

        except Exception as exc:
            logger.warning("yfinance attempt %d failed: %s", attempt + 1, exc)

        if attempt < 2:
            backoff = 2 ** (attempt + 1)  # 2s, 4s
            logger.info("Retrying TSLA price in %ds...", backoff)
            _time.sleep(backoff)

    logger.error("All TSLA price fetch attempts failed — using placeholder")
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
    """Pick a tone hint based on overall energy of the day."""
    if "▲" in change_str:
        return "positive day — upbeat and energetic"
    elif "▼" in change_str:
        return "quieter day — thoughtful but still optimistic"
    return "steady day — natural and conversational"


def _pick_intro(
    context: dict,
    *,
    episode_num: int | None = None,
    today_str: str | None = None,
) -> str:
    """Return a standard intro line for the podcast script.

    Includes episode number and date so listeners know exactly which
    episode they're hearing.  Stock price is reserved for the closing.
    """
    ep_part = f", episode {episode_num}" if episode_num else ""
    date_part = f" Today is {today_str}." if today_str else ""
    return (
        f"Patrick: Hey, welcome to Tesla Shorts Time Daily{ep_part}. "
        f"I'm Patrick in Vancouver.{date_part} "
        f"Here's what's happening with Tesla today."
    )


def _pick_closing(context: dict) -> str:
    """Return a standard closing block with stock price and long-term perspective.

    Stock price is mentioned only at the end of the episode, paired with
    a reminder to focus on the long term over short-term fluctuations.
    """
    price = context.get("price", "0.00")
    change = context.get("change_str", "")

    price_spoken = _format_price_for_speech(price)
    change_spoken = _format_change_for_speech(change)

    return (
        "Patrick: That's your Tesla news for today. "
        "T S L A closed at {price}, {change}. "
        "If you found this useful, a rating or review on Apple Podcasts or Spotify "
        "really helps new listeners find the show. "
        "You can also find us on X at tesla shorts time. "
        "I'm Patrick in Vancouver. Thanks for listening, and I'll see you tomorrow."
    ).format(price=price_spoken, change=change_spoken)
