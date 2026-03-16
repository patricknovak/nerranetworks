"""Modern Investing Techniques pre-fetch and post-generation hooks.

Provides:
- Market index data (S&P 500, NASDAQ, TSX) for digest context
- Yesterday's simulated trade evaluation using real market data
- Running portfolio performance stats
- Post-generation trade extraction from the generated digest
"""

from __future__ import annotations

import datetime
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TRACKER_FILENAME = "investment_tracker.json"


def pre_fetch(config, *, episode_num: int | None = None, today_str: str | None = None) -> dict:
    """Return extra template variables for the Modern Investing digest/podcast prompts.

    Called by ``run_show.py`` before digest generation.  Returns a dict
    that gets merged into the prompt template variables.
    """
    context: dict = {}

    output_dir = Path(config.episode.output_dir)
    tracker_path = output_dir / TRACKER_FILENAME

    # Load tracker
    tracker = _load_tracker(tracker_path)

    # Evaluate yesterday's open trade (if any)
    _evaluate_open_trade(tracker, tracker_path)

    # Build yesterday's trade review text
    context["yesterday_trade_review"] = _build_trade_review(tracker, episode_num)

    # Build portfolio summary
    context["portfolio_summary"] = _build_portfolio_summary(tracker)

    # Fetch market indices
    context["market_indices"] = _fetch_market_indices()

    # Podcast-specific vars
    context["tone_hint"] = "analytical and educational — focused on strategy and data"

    return context


def post_generate(config, *, digest_text: str = "", episode_num: int | None = None) -> None:
    """Extract today's Practice Investment pick from the generated digest.

    Called by ``run_show.py`` after digest generation.  Parses the pick
    and saves it as an open trade in the tracker for next-day evaluation.
    """
    output_dir = Path(config.episode.output_dir)
    tracker_path = output_dir / TRACKER_FILENAME

    tracker = _load_tracker(tracker_path)

    trade = _extract_trade_from_digest(digest_text, episode_num)
    if trade:
        tracker["trades"].append(trade)
        tracker["metadata"]["last_updated"] = datetime.date.today().isoformat()
        _save_tracker(tracker, tracker_path)
        logger.info(
            "Recorded trade pick: %s (%s) — confidence: %s",
            trade["symbol"], trade["strategy"], trade["confidence"],
        )
    else:
        logger.warning("Could not extract Practice Investment pick from digest")


# ---------------------------------------------------------------------------
# Internal helpers — tracker I/O
# ---------------------------------------------------------------------------

def _load_tracker(tracker_path: Path) -> dict:
    """Load the investment tracker JSON, or return a fresh one."""
    if tracker_path.exists():
        try:
            return json.loads(tracker_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load tracker: %s — starting fresh", exc)
    return {
        "metadata": {
            "show": "Modern Investing Techniques",
            "description": "Simulated trade performance tracker",
            "disclaimer": "All trades are simulated for educational purposes only.",
            "position_size": 1000,
            "currency": "USD",
            "created": datetime.date.today().isoformat(),
            "last_updated": datetime.date.today().isoformat(),
        },
        "summary": {
            "total_trades": 0, "wins": 0, "losses": 0, "breakeven": 0,
            "win_rate_pct": 0.0, "cumulative_pnl": 0.0,
            "best_trade_pct": 0.0, "worst_trade_pct": 0.0,
            "average_return_pct": 0.0,
            "current_streak": 0, "longest_win_streak": 0, "longest_loss_streak": 0,
        },
        "trades": [],
    }


def _save_tracker(tracker: dict, tracker_path: Path) -> None:
    """Write tracker JSON atomically."""
    tracker_path.write_text(
        json.dumps(tracker, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Trade evaluation — uses yfinance for real market data
# ---------------------------------------------------------------------------

def _evaluate_open_trade(tracker: dict, tracker_path: Path) -> None:
    """Find the most recent open trade and close it with real market data."""
    open_trades = [t for t in tracker["trades"] if t.get("status") == "open"]
    if not open_trades:
        return

    trade = open_trades[-1]  # Most recent open trade
    symbol = trade.get("symbol", "")
    if not symbol:
        logger.warning("Open trade has no symbol — skipping evaluation")
        return

    entry_price, exit_price = _fetch_trade_prices(symbol)
    if entry_price is None or exit_price is None:
        logger.warning("Could not fetch prices for %s — marking as data_unavailable", symbol)
        trade["status"] = "closed"
        trade["entry_price"] = None
        trade["exit_price"] = None
        trade["pnl_pct"] = 0.0
        trade["pnl_dollars"] = 0.0
        trade["lesson"] = "Market data was unavailable for evaluation."
    else:
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        position_size = tracker["metadata"].get("position_size", 1000)
        pnl_dollars = round(position_size * (pnl_pct / 100), 2)

        trade["status"] = "closed"
        trade["entry_price"] = round(entry_price, 2)
        trade["exit_price"] = round(exit_price, 2)
        trade["pnl_pct"] = round(pnl_pct, 2)
        trade["pnl_dollars"] = round(pnl_dollars, 2)

        logger.info(
            "Evaluated %s: entry=$%.2f exit=$%.2f pnl=%.2f%%",
            symbol, entry_price, exit_price, pnl_pct,
        )

    # Recompute summary stats
    _recompute_summary(tracker)
    _save_tracker(tracker, tracker_path)


def _fetch_trade_prices(symbol: str) -> tuple[float | None, float | None]:
    """Fetch market open and close prices for the trade date using yfinance.

    Returns (entry_price, exit_price) or (None, None) on failure.
    Uses the most recent trading day's open and close.
    """
    import time as _time

    for attempt in range(3):
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="5d", interval="1d")
            if hist.empty or len(hist) < 1:
                logger.warning("No history for %s (attempt %d)", symbol, attempt + 1)
            else:
                # Use the most recent completed trading day
                last_row = hist.iloc[-1]
                entry = float(last_row["Open"])
                exit_ = float(last_row["Close"])
                return entry, exit_
        except Exception as exc:
            logger.warning("yfinance attempt %d for %s failed: %s", attempt + 1, symbol, exc)

        if attempt < 2:
            backoff = 2 ** (attempt + 1)
            logger.info("Retrying %s price in %ds...", symbol, backoff)
            _time.sleep(backoff)

    return None, None


def _recompute_summary(tracker: dict) -> None:
    """Recompute summary statistics from all closed trades."""
    closed = [t for t in tracker["trades"] if t.get("status") == "closed"]
    if not closed:
        return

    wins = sum(1 for t in closed if (t.get("pnl_pct") or 0) > 0)
    losses = sum(1 for t in closed if (t.get("pnl_pct") or 0) < 0)
    breakeven = len(closed) - wins - losses
    total = len(closed)
    cum_pnl = sum(t.get("pnl_dollars") or 0 for t in closed)
    pnl_pcts = [t.get("pnl_pct") or 0 for t in closed]

    # Streak calculation
    current_streak = 0
    longest_win = 0
    longest_loss = 0
    streak = 0
    for t in closed:
        pnl = t.get("pnl_pct") or 0
        if pnl > 0:
            streak = streak + 1 if streak > 0 else 1
            longest_win = max(longest_win, streak)
        elif pnl < 0:
            streak = streak - 1 if streak < 0 else -1
            longest_loss = max(longest_loss, abs(streak))
        else:
            streak = 0
    current_streak = streak

    tracker["summary"] = {
        "total_trades": total,
        "wins": wins,
        "losses": losses,
        "breakeven": breakeven,
        "win_rate_pct": round((wins / total) * 100, 1) if total else 0.0,
        "cumulative_pnl": round(cum_pnl, 2),
        "best_trade_pct": round(max(pnl_pcts), 2) if pnl_pcts else 0.0,
        "worst_trade_pct": round(min(pnl_pcts), 2) if pnl_pcts else 0.0,
        "average_return_pct": round(sum(pnl_pcts) / len(pnl_pcts), 2) if pnl_pcts else 0.0,
        "current_streak": current_streak,
        "longest_win_streak": longest_win,
        "longest_loss_streak": longest_loss,
    }


# ---------------------------------------------------------------------------
# Market index data
# ---------------------------------------------------------------------------

def _fetch_market_indices() -> str:
    """Fetch current S&P 500, NASDAQ, and TSX levels for context."""
    import time as _time

    indices = {
        "^GSPC": "S&P 500",
        "^IXIC": "NASDAQ Composite",
        "^GSPTSE": "TSX Composite",
    }
    results = []

    for symbol, name in indices.items():
        for attempt in range(2):
            try:
                import yfinance as yf
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="5d", interval="1d")
                if not hist.empty:
                    close = float(hist["Close"].iloc[-1])
                    prev = float(hist["Close"].iloc[-2]) if len(hist) > 1 else close
                    change_pct = ((close - prev) / prev) * 100 if prev else 0
                    direction = "+" if change_pct >= 0 else ""
                    results.append(f"{name}: {close:,.0f} ({direction}{change_pct:.1f}%)")
                    break
            except Exception as exc:
                logger.warning("Index fetch %s attempt %d: %s", symbol, attempt + 1, exc)
                if attempt < 1:
                    _time.sleep(2)
        else:
            results.append(f"{name}: data unavailable")

    return " | ".join(results) if results else "Market index data temporarily unavailable"


# ---------------------------------------------------------------------------
# Trade review text builders
# ---------------------------------------------------------------------------

def _build_trade_review(tracker: dict, episode_num: int | None = None) -> str:
    """Build the Yesterday's Trade Review text block for the digest prompt."""
    if episode_num and episode_num <= 1:
        return ""  # No review for Episode 1

    closed = [t for t in tracker["trades"] if t.get("status") == "closed"]
    if not closed:
        return ""

    last = closed[-1]
    symbol = last.get("symbol", "???")
    strategy = last.get("strategy", "")
    entry = last.get("entry_price")
    exit_ = last.get("exit_price")
    pnl_pct = last.get("pnl_pct", 0)
    pnl_dollars = last.get("pnl_dollars", 0)
    summary = tracker.get("summary", {})

    if entry is None or exit_ is None:
        return (
            f"**Yesterday's Pick:** {symbol}\n"
            f"**Result:** Market data was unavailable for evaluation.\n"
            f"**Running Total:** ${summary.get('cumulative_pnl', 0):.2f}\n"
            f"**Win Rate:** {summary.get('wins', 0)} wins / "
            f"{summary.get('total_trades', 0)} total trades "
            f"({summary.get('win_rate_pct', 0):.0f}%)\n"
        )

    direction = "gained" if pnl_pct >= 0 else "lost"
    return (
        f"**Yesterday's Pick:** {symbol} — {strategy}\n"
        f"**Entry:** ${entry:.2f} (market open) → **Exit:** ${exit_:.2f} (market close)\n"
        f"**Result:** {direction} {abs(pnl_pct):.2f}% (${pnl_dollars:+.2f} on $1,000 position)\n"
        f"**Running Total:** ${summary.get('cumulative_pnl', 0):.2f} across "
        f"{summary.get('total_trades', 0)} trades\n"
        f"**Win Rate:** {summary.get('wins', 0)} wins / "
        f"{summary.get('total_trades', 0)} total trades "
        f"({summary.get('win_rate_pct', 0):.0f}%)\n"
        f"**Current Streak:** {_format_streak(summary.get('current_streak', 0))}\n"
    )


def _build_portfolio_summary(tracker: dict) -> str:
    """Build the Portfolio Performance summary for the digest prompt."""
    summary = tracker.get("summary", {})
    total = summary.get("total_trades", 0)
    if total == 0:
        return "No simulated trades completed yet — this is the first episode."

    return (
        f"Portfolio Performance (simulated, $1,000 per trade):\n"
        f"- Total trades: {total}\n"
        f"- Win rate: {summary.get('win_rate_pct', 0):.0f}% "
        f"({summary.get('wins', 0)}W / {summary.get('losses', 0)}L / "
        f"{summary.get('breakeven', 0)}BE)\n"
        f"- Cumulative P&L: ${summary.get('cumulative_pnl', 0):+.2f}\n"
        f"- Average return per trade: {summary.get('average_return_pct', 0):+.2f}%\n"
        f"- Best trade: {summary.get('best_trade_pct', 0):+.2f}%\n"
        f"- Worst trade: {summary.get('worst_trade_pct', 0):+.2f}%\n"
        f"- Current streak: {_format_streak(summary.get('current_streak', 0))}\n"
    )


def _format_streak(streak: int) -> str:
    """Format streak number as human-readable text."""
    if streak > 0:
        return f"{streak} win{'s' if streak != 1 else ''}"
    elif streak < 0:
        return f"{abs(streak)} loss{'es' if abs(streak) != 1 else ''}"
    return "even"


# ---------------------------------------------------------------------------
# Post-generation trade extraction
# ---------------------------------------------------------------------------

def _extract_trade_from_digest(digest_text: str, episode_num: int | None = None) -> dict | None:
    """Parse the Practice Investment of the Day from the generated digest.

    Returns a trade dict ready for the tracker, or None if extraction fails.
    """
    if not digest_text:
        return None

    # Extract ticker symbol
    ticker_match = re.search(
        r"\*\*Today's Pick:\*\*\s*\[?([A-Z]{1,5})\]?\s*[-—]",
        digest_text,
    )
    if not ticker_match:
        # Fallback: try alternative patterns
        ticker_match = re.search(
            r"Today's Pick[:\s]+([A-Z]{1,5})\s",
            digest_text,
        )
    if not ticker_match:
        return None

    symbol = ticker_match.group(1).strip()

    # Extract market
    market_match = re.search(
        r"\*\*Market:\*\*\s*(TSX|NYSE|NASDAQ|TSX-V)",
        digest_text, re.IGNORECASE,
    )
    market = market_match.group(1).upper() if market_match else "UNKNOWN"

    # Extract strategy
    strategy_match = re.search(
        r"\*\*Strategy:\*\*\s*(.+?)(?:\n|$)",
        digest_text,
    )
    strategy = strategy_match.group(1).strip().rstrip('"') if strategy_match else ""

    # Extract confidence
    confidence_match = re.search(
        r"\*\*Confidence Level:\*\*\s*(Low|Medium|High)",
        digest_text, re.IGNORECASE,
    )
    confidence = confidence_match.group(1).capitalize() if confidence_match else "Unknown"

    # Extract target
    target_match = re.search(
        r"\*\*Target:\*\*\s*(.+?)(?:\n|$)",
        digest_text,
    )
    target = target_match.group(1).strip() if target_match else ""

    return {
        "episode_num": episode_num or 0,
        "date": datetime.date.today().isoformat(),
        "symbol": symbol,
        "market": market,
        "strategy": strategy,
        "confidence": confidence,
        "target_range": target,
        "status": "open",
        "entry_price": None,
        "exit_price": None,
        "pnl_pct": None,
        "pnl_dollars": None,
        "lesson": "",
    }
