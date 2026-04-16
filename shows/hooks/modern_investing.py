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
TAUGHT_LESSONS_FILENAME = "taught_lessons.json"
LESSONS_LEARNED_FILENAME = "lessons_learned.json"
MONTHLY_EPISODES_FILENAME = "monthly_episodes.json"
NASDAQ_SYMBOL = "^IXIC"

# Sector vocabulary — canonical tags used across tracker, taught_lessons,
# lessons_learned, and the dashboard. Keep this list in sync with
# ``_SECTOR_BY_SYMBOL`` below and the digest prompt's required
# ``**Sector:**`` field.
SECTOR_TAGS = (
    "precious_metals",
    "energy",
    "tech",
    "financials",
    "healthcare",
    "consumer",
    "crypto",
    "industrials",
    "utilities",
    "other",
)

# Direct symbol -> sector lookup for tickers that have appeared (or are
# likely to appear) in the Practice Investment segment. Fallback is
# keyword-matched against the strategy text in ``_classify_sector``.
_SECTOR_BY_SYMBOL = {
    # Precious metals / mining
    "LGD": "precious_metals", "FSM": "precious_metals", "SSRM": "precious_metals",
    "WRLG": "precious_metals", "AEM": "precious_metals", "ABX": "precious_metals",
    "GOLD": "precious_metals", "NEM": "precious_metals", "FNV": "precious_metals",
    "WPM": "precious_metals", "K": "precious_metals",
    # Energy
    "XOM": "energy", "CVX": "energy", "CNQ": "energy", "SU": "energy",
    "ENB": "energy", "TRP": "energy", "IMO": "energy", "CVE": "energy",
    # Tech / semis / cloud
    "WDC": "tech", "SSNLF": "tech", "TMUS": "tech", "AAPL": "tech",
    "MSFT": "tech", "GOOGL": "tech", "META": "tech", "NVDA": "tech",
    "AMD": "tech", "TSM": "tech", "AVGO": "tech", "ORCL": "tech",
    "CRM": "tech", "INTC": "tech", "MU": "tech", "SHOP": "tech",
    # Financials
    "SOFI": "financials", "JPM": "financials", "BAC": "financials",
    "RY": "financials", "TD": "financials", "BMO": "financials",
    "BNS": "financials", "CM": "financials", "MFC": "financials",
    "SLF": "financials",
    # Consumer
    "TSLA": "consumer", "LCID": "consumer", "LUCID": "consumer",
    "SWGAY": "consumer", "AMZN": "consumer", "COST": "consumer",
    "WMT": "consumer", "L": "consumer",
    # Crypto
    "BTC-USD": "crypto", "ETH-USD": "crypto", "COIN": "crypto",
    "MARA": "crypto", "HUT": "crypto",
    # Healthcare
    "JNJ": "healthcare", "PFE": "healthcare", "LLY": "healthcare",
    "MRK": "healthcare", "ABBV": "healthcare",
    # Industrials / utilities
    "CAT": "industrials", "CNR": "industrials", "CP": "industrials",
    "FTS": "utilities", "EMA": "utilities", "H": "utilities",
}

# Lesson-tag vocabulary — paired with the digest prompt's required
# ``**Lesson Tags:**`` field. When the digest is parsed post-generation,
# ``_extract_lesson_tags`` pulls any of these strings and ``taught_lessons.json``
# is updated. Adding a new tag requires updating this list AND the prompt.
LESSON_VOCABULARY = (
    "bid_ask_spread",
    "order_flow_slippage",
    "sector_rotation",
    "sector_concentration",
    "risk_management",
    "position_sizing",
    "tax_loss_harvesting",
    "tfsa_rrsp_mechanics",
    "momentum_entry",
    "mean_reversion",
    "catalyst_confirmation",
    "catalyst_fade",
    "earnings_surprise",
    "technical_breakout",
    "technical_support",
    "valuation_discipline",
    "macro_rotation",
    "geopolitical_premium",
    "insider_buying",
    "analyst_upgrade",
    "activist_defense",
    "dividend_compounding",
    "dollar_cost_averaging",
    "covered_call",
    "fx_hedging",
    "portfolio_rebalancing",
)


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

    # Refresh NASDAQ benchmark state (inception/YTD/current close + alpha)
    # and expose a prompt-ready block. Save immediately so the dashboard
    # aggregator and the website always read a fresh ``benchmark`` block.
    try:
        _compute_benchmark_state(tracker)
        _save_tracker(tracker, tracker_path)
    except Exception as exc:
        logger.warning("Benchmark state refresh failed: %s", exc)
    context["benchmark_state"] = _build_benchmark_block(tracker)

    # Recent strategies for freshness enforcement
    closed_trades = [t for t in tracker["trades"] if t.get("status") == "closed"]
    recent = closed_trades[-5:] if closed_trades else []
    if recent:
        lines = [f"- Ep{t.get('episode_num', '?')}: {t.get('symbol', '?')} ({t.get('strategy', 'unknown')})" for t in recent]
        context["recent_strategies"] = "\n".join(lines)
    else:
        context["recent_strategies"] = "No previous trades yet — this may be the first episode."

    # Dynamic tone based on portfolio performance
    context["tone_hint"] = _tone_from_portfolio(tracker)

    return context


def _tone_from_portfolio(tracker: dict) -> str:
    """Return a tone hint based on recent portfolio performance."""
    summary = tracker.get("summary", {})
    streak = summary.get("current_streak", 0)
    cum_pnl = summary.get("cumulative_pnl", 0)
    total = summary.get("total_trades", 0)

    if total == 0:
        return "enthusiastic and welcoming — this is early days, set the foundation"
    if streak >= 3:
        return "momentum is building — confident and energetic, but stay disciplined"
    if streak <= -2:
        return "learning week — reflective and analytical, focus on what the losses teach"
    if cum_pnl > 50:
        return "portfolio doing well — upbeat but measured, credit the process not luck"
    if cum_pnl < -30:
        return "drawdown mode — humble and educational, remind listeners this is learning"
    return "steady progress — balanced and conversational"


def pronunciation_overrides() -> dict:
    """Return financial-term pronunciation fixes for ElevenLabs TTS."""
    return {
        "extra_acronyms": {
            "ETF": "E T F",
            "TFSA": "T F S A",
            "RRSP": "R R S P",
            "FHSA": "F H S A",
            "RESP": "R E S P",
            "RSI": "R S I",
            "MACD": "mac dee",
            "P/E": "P E",
            "EPS": "E P S",
            "IPO": "I P O",
            "NYSE": "N Y S E",
            "TSX": "T S X",
            "SPY": "S P Y",
            "QQQ": "Q Q Q",
            "VFV": "V F V",
            "VOO": "V O O",
            "CAD": "C A D",
            "USD": "U S D",
            "ACB": "A C B",
            "DRIP": "D R I P",
            "GIC": "G I C",
            "VGRO": "V G R O",
            "XEQT": "X E Q T",
            # Common tickers discussed frequently
            "NVDA": "N V D A",
            "ARKK": "A R K K",
            "SCHD": "S C H D",
            # Canadian tickers
            "BCE": "B C E",
            "ENB": "E N B",
            "CNR": "C N R",
            # Financial terms
            "YTD": "year to date",
            "MoM": "month over month",
            "QoQ": "quarter over quarter",
            "BoC": "Bank of Canada",
            "FOMC": "F O M C",
            "AUM": "A U M",
            "DCA": "D C A",
            "MER": "M E R",
            "CRA": "C R A",
            "HELOC": "H E L O C",
            "ROI": "R O I",
            "PE": "P E",
            "NAV": "N A V",
            "ATH": "all time high",
            # Canadian ETFs/tickers
            "BTCC": "B T C C",
            "XGRO": "X G R O",
            "VEQT": "V E Q T",
            "XIU": "X I U",
            "ZSP": "Z S P",
            "HXT": "H X T",
        },
        "extra_words": {
            "robo-advisor": "robo advisor",
            "fintech": "fin tech",
            "bps": "basis points",
        },
    }


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
    """Load the investment tracker JSON, or return a fresh one.

    Older trackers that predate the NASDAQ-benchmark / sector / alpha
    schema are upgraded in-place with safe defaults the first time they
    are read, so existing files keep working without a manual migration.
    """
    if tracker_path.exists():
        try:
            tracker = json.loads(tracker_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load tracker: %s — starting fresh", exc)
            tracker = _fresh_tracker()
        else:
            _ensure_schema(tracker)
            return tracker
    else:
        tracker = _fresh_tracker()
    return tracker


def _fresh_tracker() -> dict:
    today_iso = datetime.date.today().isoformat()
    return {
        "metadata": {
            "show": "Modern Investing Techniques",
            "description": "Simulated trade performance tracker",
            "disclaimer": "All trades are simulated for educational purposes only.",
            "position_size": 1000,
            "currency": "USD",
            "created": today_iso,
            "last_updated": today_iso,
            "inception_date": today_iso,
            "benchmark_symbol": NASDAQ_SYMBOL,
            "nasdaq_inception_close": None,
            "nasdaq_ytd_start_close": None,
            "nasdaq_ytd_year": datetime.date.today().year,
        },
        "summary": {
            "total_trades": 0, "wins": 0, "losses": 0, "breakeven": 0,
            "win_rate_pct": 0.0, "cumulative_pnl": 0.0,
            "best_trade_pct": 0.0, "worst_trade_pct": 0.0,
            "average_return_pct": 0.0,
            "current_streak": 0, "longest_win_streak": 0, "longest_loss_streak": 0,
        },
        "benchmark": {
            "current_close": None,
            "inception_to_date_pct": 0.0,
            "ytd_pct": 0.0,
            "last_updated": today_iso,
        },
        "alpha": {
            "inception_to_date_pct": 0.0,
            "ytd_pct": 0.0,
            "monthly": {},
        },
        "sectors": {},
        "monthly_snapshots": [],
        "trades": [],
    }


def _ensure_schema(tracker: dict) -> None:
    """Upgrade an older tracker dict in-place to the current schema."""
    today_iso = datetime.date.today().isoformat()
    meta = tracker.setdefault("metadata", {})
    meta.setdefault("inception_date", meta.get("created", today_iso))
    meta.setdefault("benchmark_symbol", NASDAQ_SYMBOL)
    meta.setdefault("nasdaq_inception_close", None)
    meta.setdefault("nasdaq_ytd_start_close", None)
    meta.setdefault("nasdaq_ytd_year", datetime.date.today().year)
    tracker.setdefault("benchmark", {
        "current_close": None,
        "inception_to_date_pct": 0.0,
        "ytd_pct": 0.0,
        "last_updated": today_iso,
    })
    tracker.setdefault("alpha", {
        "inception_to_date_pct": 0.0,
        "ytd_pct": 0.0,
        "monthly": {},
    })
    tracker.setdefault("sectors", {})
    tracker.setdefault("monthly_snapshots", [])
    tracker.setdefault("trades", [])


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
    """Evaluate open trades using the hybrid model.

    - **Weekly holds** are only closed on Fridays (weekday 4).
    - **Flash trades** (trade_type == "flash") are closed the next trading day.
    - On non-Friday weekdays, weekly holds get a mid-week price snapshot
      (stored as ``current_price``) but remain open.
    """
    open_trades = [t for t in tracker["trades"] if t.get("status") == "open"]
    if not open_trades:
        return

    today = datetime.date.today()
    is_friday = today.weekday() == 4  # Monday=0, Friday=4

    for trade in open_trades:
        symbol = trade.get("symbol", "")
        if not symbol:
            logger.warning("Open trade has no symbol — skipping evaluation")
            continue

        trade_type = trade.get("trade_type", "weekly")

        # Flash trades close the next day; weekly holds close on Friday only
        should_close = (trade_type == "flash") or is_friday

        if should_close:
            _close_trade(trade, tracker)
        else:
            # Mid-week snapshot for weekly holds
            _snapshot_trade(trade, symbol)

    # Recompute summary stats and save
    _recompute_summary(tracker)
    _save_tracker(tracker, tracker_path)


def _close_trade(trade: dict, tracker: dict) -> None:
    """Close a trade with real market data."""
    symbol = trade.get("symbol", "")
    trade_type = trade.get("trade_type", "weekly")

    if trade_type == "flash":
        # Flash trade: entry = trade date's open, exit = trade date's close
        entry_price, exit_price = _fetch_trade_prices(symbol)
    else:
        # Weekly hold: entry = Monday open, exit = Friday close
        entry_price, exit_price = _fetch_weekly_prices(symbol)

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

        # Annotate with NASDAQ benchmark alpha — best-effort, tolerant of yfinance failures.
        try:
            _annotate_trade_with_nasdaq(trade)
        except Exception as exc:
            logger.warning("NASDAQ annotation failed for %s: %s", symbol, exc)

        # Backfill sector if post_generate never set it (e.g. old trades).
        if not trade.get("sector"):
            trade["sector"] = _classify_sector(
                symbol, trade.get("strategy", ""), trade.get("market", ""),
            )

        logger.info(
            "Evaluated %s (%s): entry=$%.2f exit=$%.2f pnl=%.2f%% alpha=%s",
            symbol, trade_type, entry_price, exit_price, pnl_pct, trade.get("alpha_pct"),
        )


def _snapshot_trade(trade: dict, symbol: str) -> None:
    """Take a mid-week price snapshot for a weekly hold (does not close it)."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d", interval="1d")
        if not hist.empty:
            trade["current_price"] = round(float(hist["Close"].iloc[-1]), 2)
            logger.info("Mid-week snapshot %s: $%.2f", symbol, trade["current_price"])
    except Exception as exc:
        logger.warning("Mid-week snapshot failed for %s: %s", symbol, exc)


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


def _fetch_weekly_prices(symbol: str) -> tuple[float | None, float | None]:
    """Fetch the week's first trading day open and last trading day close.

    Returns (entry_price, exit_price) or (None, None) on failure.
    Uses 10 calendar days of history to handle shortened weeks (holidays),
    then filters to only this week's trading days.
    """
    import time as _time

    today = datetime.date.today()
    # Find this week's Monday (weekday 0)
    monday = today - datetime.timedelta(days=today.weekday())

    for attempt in range(3):
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            # Fetch 10 days to cover holidays and weekends
            hist = ticker.history(period="10d", interval="1d")
            if hist.empty or len(hist) < 1:
                logger.warning("No history for %s (attempt %d)", symbol, attempt + 1)
            else:
                # Filter to only this week's trading days (Monday through today)
                week_data = hist[hist.index.date >= monday]
                if week_data.empty:
                    logger.warning("No trading days this week for %s", symbol)
                else:
                    # First trading day's open, last trading day's close
                    entry = float(week_data.iloc[0]["Open"])
                    exit_ = float(week_data.iloc[-1]["Close"])
                    logger.info(
                        "Weekly prices for %s: %d trading days this week (entry=%s, exit=%s)",
                        symbol, len(week_data),
                        week_data.index[0].strftime("%a"),
                        week_data.index[-1].strftime("%a"),
                    )
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
# NASDAQ benchmark — fetch, alpha math, per-trade annotation
# ---------------------------------------------------------------------------

def _fetch_nasdaq_close(for_date: datetime.date | None = None) -> float | None:
    """Return the ^IXIC close for the given date (or most recent if None).

    Uses the same 3-retry pattern as ``_fetch_trade_prices``. Returns
    ``None`` on total failure — callers must tolerate missing data.
    """
    import time as _time
    for attempt in range(3):
        try:
            import yfinance as yf
            ticker = yf.Ticker(NASDAQ_SYMBOL)
            if for_date is None:
                hist = ticker.history(period="5d", interval="1d")
                if not hist.empty:
                    return float(hist["Close"].iloc[-1])
            else:
                start = for_date - datetime.timedelta(days=5)
                end = for_date + datetime.timedelta(days=1)
                hist = ticker.history(start=start.isoformat(), end=end.isoformat(), interval="1d")
                if not hist.empty:
                    # Pick the most recent close on or before ``for_date``.
                    mask = hist.index.date <= for_date
                    if mask.any():
                        return float(hist[mask]["Close"].iloc[-1])
                    return float(hist["Close"].iloc[-1])
        except Exception as exc:
            logger.warning("NASDAQ fetch attempt %d (%s): %s", attempt + 1, for_date, exc)
        if attempt < 2:
            _time.sleep(2 ** (attempt + 1))
    return None


def _portfolio_return_pct(tracker: dict) -> float:
    """Cumulative portfolio return as a percentage of total capital deployed.

    Treats every trade as ``position_size`` dollars of capital; divides
    summed P&L by (trades * position_size). Matches how listeners already
    hear the ``Running Total`` framed.
    """
    closed = [t for t in tracker.get("trades", []) if t.get("status") == "closed"]
    if not closed:
        return 0.0
    position = tracker.get("metadata", {}).get("position_size", 1000) or 1000
    total_pnl = sum((t.get("pnl_dollars") or 0) for t in closed)
    capital = len(closed) * position
    return round((total_pnl / capital) * 100, 2) if capital else 0.0


def _portfolio_return_ytd_pct(tracker: dict) -> float:
    """Same as ``_portfolio_return_pct`` but filtered to trades closed this year."""
    this_year = datetime.date.today().year
    closed = [
        t for t in tracker.get("trades", [])
        if t.get("status") == "closed"
        and isinstance(t.get("date"), str)
        and t["date"][:4] == str(this_year)
    ]
    if not closed:
        return 0.0
    position = tracker.get("metadata", {}).get("position_size", 1000) or 1000
    total_pnl = sum((t.get("pnl_dollars") or 0) for t in closed)
    capital = len(closed) * position
    return round((total_pnl / capital) * 100, 2) if capital else 0.0


def _compute_benchmark_state(tracker: dict) -> None:
    """Populate ``tracker['benchmark']`` and ``tracker['alpha']`` blocks.

    Mutates *tracker* in place. Refreshes the YTD baseline if the calendar
    year rolled over since the last run. Safe to call on every episode.
    """
    today = datetime.date.today()
    today_iso = today.isoformat()
    meta = tracker["metadata"]

    # Seed inception close if missing — this runs on day one or after an
    # operator-forced reset.
    if meta.get("nasdaq_inception_close") is None:
        inception = meta.get("inception_date") or meta.get("created") or today_iso
        try:
            inception_date = datetime.date.fromisoformat(inception)
        except ValueError:
            inception_date = today
        seeded = _fetch_nasdaq_close(inception_date)
        if seeded is not None:
            meta["nasdaq_inception_close"] = round(seeded, 2)

    # Refresh YTD baseline on Jan 2 rollover (or if missing).
    if meta.get("nasdaq_ytd_year") != today.year or meta.get("nasdaq_ytd_start_close") is None:
        ytd_anchor = datetime.date(today.year, 1, 2)
        ytd_close = _fetch_nasdaq_close(ytd_anchor)
        if ytd_close is not None:
            meta["nasdaq_ytd_start_close"] = round(ytd_close, 2)
            meta["nasdaq_ytd_year"] = today.year

    current_close = _fetch_nasdaq_close()

    benchmark = tracker.setdefault("benchmark", {})
    benchmark["current_close"] = round(current_close, 2) if current_close is not None else benchmark.get("current_close")
    benchmark["last_updated"] = today_iso

    inception_close = meta.get("nasdaq_inception_close")
    ytd_start = meta.get("nasdaq_ytd_start_close")
    ref_close = benchmark["current_close"]

    if ref_close is not None and inception_close:
        benchmark["inception_to_date_pct"] = round(((ref_close - inception_close) / inception_close) * 100, 2)
    if ref_close is not None and ytd_start:
        benchmark["ytd_pct"] = round(((ref_close - ytd_start) / ytd_start) * 100, 2)

    alpha = tracker.setdefault("alpha", {"monthly": {}})
    alpha["inception_to_date_pct"] = round(_portfolio_return_pct(tracker) - benchmark.get("inception_to_date_pct", 0.0), 2)
    alpha["ytd_pct"] = round(_portfolio_return_ytd_pct(tracker) - benchmark.get("ytd_pct", 0.0), 2)


def _annotate_trade_with_nasdaq(trade: dict, entry_date: datetime.date | None = None, exit_date: datetime.date | None = None) -> None:
    """Fill in NASDAQ entry/exit closes and alpha on a just-closed trade.

    Safe no-op if yfinance data is unavailable — ``nasdaq_*`` fields stay
    ``None`` and ``alpha_pct`` defaults to ``None``.
    """
    trade_date_str = trade.get("date")
    if entry_date is None and trade_date_str:
        try:
            entry_date = datetime.date.fromisoformat(trade_date_str)
        except ValueError:
            entry_date = None
    if entry_date is None:
        entry_date = datetime.date.today()
    if exit_date is None:
        # Weekly holds close on the Friday of the entry's week; flash
        # trades close the same day. Good enough for benchmark alpha.
        if trade.get("trade_type") == "flash":
            exit_date = entry_date
        else:
            exit_date = entry_date + datetime.timedelta(days=(4 - entry_date.weekday()) % 7)

    entry_close = _fetch_nasdaq_close(entry_date)
    exit_close = _fetch_nasdaq_close(exit_date)
    trade["nasdaq_entry"] = round(entry_close, 2) if entry_close else None
    trade["nasdaq_exit"] = round(exit_close, 2) if exit_close else None
    if entry_close and exit_close:
        nasdaq_return = ((exit_close - entry_close) / entry_close) * 100
        trade["nasdaq_return_pct"] = round(nasdaq_return, 2)
        pnl = trade.get("pnl_pct")
        if pnl is not None:
            trade["alpha_pct"] = round(pnl - nasdaq_return, 2)
        else:
            trade["alpha_pct"] = None
    else:
        trade["nasdaq_return_pct"] = None
        trade["alpha_pct"] = None


# ---------------------------------------------------------------------------
# Sector classification + lesson-tag extraction
# ---------------------------------------------------------------------------

_SECTOR_KEYWORDS = (
    ("precious_metals", ("gold", "silver", "mining", "miner", "platinum", "palladium", "bullion", "ore")),
    ("energy", ("oil", "gas", "petroleum", "lng", "energy", "pipeline", "refiner", "wti", "brent")),
    ("tech", ("semiconductor", "chip", "cloud", "software", "saas", "ai infrastructure", "data center", "fintech platform", "memory")),
    ("financials", ("bank", "insurer", "insurance", "mortgage", "broker", "credit union", "digital banking")),
    ("healthcare", ("pharma", "biotech", "therap", "vaccine", "hospital", "medical device", "clinical trial")),
    ("consumer", ("retail", "consumer", "ev ", "electric vehicle", "apparel", "beverage", "restaurant", "grocer")),
    ("crypto", ("crypto", "bitcoin", "ethereum", "stablecoin", "defi", "miner pool")),
    ("industrials", ("industrial", "rail", "transport", "logistics", "machinery", "construction")),
    ("utilities", ("utility", "utilities", "power generation", "grid")),
)


def _classify_sector(symbol: str, strategy: str = "", market: str = "") -> str:
    """Return a canonical sector tag for a Practice Investment pick.

    Direct symbol lookup wins; falls back to keyword matching on the
    strategy text. Always returns a tag from ``SECTOR_TAGS`` — defaults
    to ``"other"`` when uncertain so the dashboard aggregator never NPEs.
    """
    if symbol:
        sym = symbol.upper().strip()
        if sym in _SECTOR_BY_SYMBOL:
            return _SECTOR_BY_SYMBOL[sym]
    haystack = f"{strategy} {market}".lower()
    for sector, keywords in _SECTOR_KEYWORDS:
        for kw in keywords:
            if kw in haystack:
                return sector
    return "other"


def _extract_lesson_tags(text: str) -> list[str]:
    """Pull any tags from ``LESSON_VOCABULARY`` that appear in *text*.

    The digest prompt emits ``**Lesson Tags:** foo, bar`` after each
    Trade Review and Practice Investment; this function also matches
    loose mentions inside the Investor Education section so older
    episodes aren't silently missed.
    """
    if not text:
        return []
    # Normalise so "bid-ask spread", "bid ask spread", "bid_ask_spread"
    # all collapse to a single matching token stream.
    lowered = re.sub(r"[\-_\s]+", " ", text.lower())
    found: list[str] = []
    for tag in LESSON_VOCABULARY:
        needle = tag.replace("_", " ")
        if needle in lowered and tag not in found:
            found.append(tag)
    return found


# ---------------------------------------------------------------------------
# Trade review text builders
# ---------------------------------------------------------------------------

def _build_trade_review(tracker: dict, episode_num: int | None = None) -> str:
    """Build the Trade Review text block for the digest prompt.

    Handles both weekly holds and flash trades, with appropriate framing for each.
    """
    if episode_num and episode_num <= 1:
        return ""  # No review for Episode 1

    closed = [t for t in tracker["trades"] if t.get("status") == "closed"]
    if not closed:
        # Check for open weekly hold — provide mid-week update
        open_trades = [t for t in tracker["trades"] if t.get("status") == "open"]
        if open_trades:
            hold = open_trades[-1]
            current = hold.get("current_price")
            if current and hold.get("entry_price"):
                unrealized = ((current - hold["entry_price"]) / hold["entry_price"]) * 100
                direction = "up" if unrealized >= 0 else "down"
                return (
                    f"**Current Weekly Hold:** {hold.get('symbol', '???')} — {hold.get('strategy', '')}\n"
                    f"**Entry:** ${hold['entry_price']:.2f} (Monday open)\n"
                    f"**Current:** ${current:.2f} ({direction} {abs(unrealized):.2f}%)\n"
                    f"**Status:** Holding until Friday evaluation\n"
                )
        return ""

    last = closed[-1]
    symbol = last.get("symbol", "???")
    strategy = last.get("strategy", "")
    trade_type = last.get("trade_type", "weekly")
    entry = last.get("entry_price")
    exit_ = last.get("exit_price")
    pnl_pct = last.get("pnl_pct", 0)
    pnl_dollars = last.get("pnl_dollars", 0)
    summary = tracker.get("summary", {})

    type_label = "Flash Trade" if trade_type == "flash" else "Weekly Hold"
    entry_label = "market open" if trade_type == "flash" else "Monday open"
    exit_label = "market close" if trade_type == "flash" else "Friday close"

    if entry is None or exit_ is None:
        return (
            f"**Last {type_label}:** {symbol}\n"
            f"**Result:** Market data was unavailable for evaluation.\n"
            f"**Running Total:** ${summary.get('cumulative_pnl', 0):.2f}\n"
            f"**Win Rate:** {summary.get('wins', 0)} wins / "
            f"{summary.get('total_trades', 0)} total trades "
            f"({summary.get('win_rate_pct', 0):.0f}%)\n"
        )

    direction = "gained" if pnl_pct >= 0 else "lost"
    return (
        f"**Last {type_label}:** {symbol} — {strategy}\n"
        f"**Entry:** ${entry:.2f} ({entry_label}) → **Exit:** ${exit_:.2f} ({exit_label})\n"
        f"**Result:** {direction} {abs(pnl_pct):.2f}% (${pnl_dollars:+.2f} on $1,000 position)\n"
        f"**Running Total:** ${summary.get('cumulative_pnl', 0):.2f} across "
        f"{summary.get('total_trades', 0)} trades\n"
        f"**Win Rate:** {summary.get('wins', 0)} wins / "
        f"{summary.get('total_trades', 0)} total trades "
        f"({summary.get('win_rate_pct', 0):.0f}%)\n"
        f"**Current Streak:** {_format_streak(summary.get('current_streak', 0))}\n"
    )


def _build_benchmark_block(tracker: dict) -> str:
    """One-line benchmark block fed to the digest/podcast prompt.

    Names NASDAQ Composite level, YTD benchmark move, portfolio return,
    and alpha in both YTD and inception-to-date windows — the show is
    required by its system prompt to state all four in every episode.
    """
    benchmark = tracker.get("benchmark", {}) or {}
    alpha = tracker.get("alpha", {}) or {}
    portfolio_itd = _portfolio_return_pct(tracker)
    portfolio_ytd = _portfolio_return_ytd_pct(tracker)
    close = benchmark.get("current_close")
    bench_ytd = benchmark.get("ytd_pct")
    bench_itd = benchmark.get("inception_to_date_pct")
    alpha_ytd = alpha.get("ytd_pct")
    alpha_itd = alpha.get("inception_to_date_pct")

    if close is None:
        return (
            "NASDAQ Composite: data temporarily unavailable — acknowledge the gap "
            "on air rather than inventing numbers."
        )

    def _sign(v):
        if v is None:
            return "n/a"
        return f"{v:+.2f}%"

    return (
        f"NASDAQ Composite ^IXIC: {close:,.0f} "
        f"(YTD {_sign(bench_ytd)}, since inception {_sign(bench_itd)}). "
        f"Portfolio: YTD {_sign(portfolio_ytd)}, since inception {_sign(portfolio_itd)}. "
        f"Alpha vs NASDAQ: YTD {_sign(alpha_ytd)}, since inception {_sign(alpha_itd)}."
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

    # Extract trade type (hybrid model: weekly hold vs flash trade)
    trade_type_match = re.search(
        r"\*\*Trade Type:\*\*\s*(Weekly Hold|Flash Trade|Mid-Week Update)",
        digest_text, re.IGNORECASE,
    )
    if trade_type_match:
        raw_type = trade_type_match.group(1).strip().lower()
        trade_type = "flash" if "flash" in raw_type else "weekly"
    else:
        # Default: Monday = weekly, other days = flash (if it's a new pick)
        trade_type = "weekly" if datetime.date.today().weekday() == 0 else "flash"

    # Mid-week updates don't create new trades
    if trade_type_match and "update" in trade_type_match.group(1).lower():
        logger.info("Mid-week update detected — no new trade to record")
        return None

    return {
        "episode_num": episode_num or 0,
        "date": datetime.date.today().isoformat(),
        "symbol": symbol,
        "market": market,
        "strategy": strategy,
        "confidence": confidence,
        "target_range": target,
        "trade_type": trade_type,
        "status": "open",
        "entry_price": None,
        "exit_price": None,
        "pnl_pct": None,
        "pnl_dollars": None,
        "lesson": "",
    }
