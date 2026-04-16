"""Unit tests for shows/hooks/modern_investing.py.

Covers the new NASDAQ-benchmark / sector / lesson-tag helpers added in
the Chunk 1+2 implementation. yfinance is fully stubbed — no network.
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from shows.hooks import modern_investing as m


# ---------------------------------------------------------------------------
# _classify_sector
# ---------------------------------------------------------------------------

class TestClassifySector:
    def test_known_precious_metals(self):
        assert m._classify_sector("FSM", "", "TSX") == "precious_metals"
        assert m._classify_sector("WRLG", "", "TSX") == "precious_metals"

    def test_known_financials(self):
        assert m._classify_sector("SOFI", "", "NASDAQ") == "financials"

    def test_known_tech(self):
        assert m._classify_sector("WDC", "", "NASDAQ") == "tech"

    def test_known_consumer(self):
        assert m._classify_sector("TSLA", "", "NASDAQ") == "consumer"
        assert m._classify_sector("LUCID", "", "NASDAQ") == "consumer"

    def test_keyword_fallback_energy(self):
        assert m._classify_sector("XYZ", "Oil & gas refiner margin recovery", "TSX") == "energy"

    def test_keyword_fallback_healthcare(self):
        assert m._classify_sector("XYZ", "Novel biotech therapy in Phase 3", "NASDAQ") == "healthcare"

    def test_unknown_returns_other(self):
        assert m._classify_sector("ZZZZZ", "some vague catalyst", "") == "other"

    def test_empty_symbol(self):
        assert m._classify_sector("", "Gold miner earnings beat", "") == "precious_metals"


# ---------------------------------------------------------------------------
# _extract_lesson_tags
# ---------------------------------------------------------------------------

class TestExtractLessonTags:
    def test_hyphen_normalisation(self):
        tags = m._extract_lesson_tags("The bid-ask spread widened on news.")
        assert "bid_ask_spread" in tags

    def test_underscore_normalisation(self):
        tags = m._extract_lesson_tags("Today's lesson was bid_ask_spread risk.")
        assert "bid_ask_spread" in tags

    def test_multiple_tags(self):
        tags = m._extract_lesson_tags(
            "Momentum entry after catalyst confirmation beat sector rotation plays."
        )
        assert set(tags) >= {"momentum_entry", "catalyst_confirmation", "sector_rotation"}

    def test_empty_returns_empty(self):
        assert m._extract_lesson_tags("") == []

    def test_dedups(self):
        # Same tag mentioned twice — should appear once
        tags = m._extract_lesson_tags("bid-ask spread again, bid ask spread twice")
        assert tags.count("bid_ask_spread") == 1

    def test_no_false_positives(self):
        tags = m._extract_lesson_tags("Purely unrelated commentary about the weather.")
        assert tags == []


# ---------------------------------------------------------------------------
# _load_tracker / _ensure_schema
# ---------------------------------------------------------------------------

class TestTrackerSchema:
    def test_fresh_tracker_has_all_new_keys(self):
        t = m._fresh_tracker()
        assert "benchmark" in t
        assert "alpha" in t
        assert "sectors" in t
        assert "monthly_snapshots" in t
        assert t["metadata"]["benchmark_symbol"] == "^IXIC"
        assert t["metadata"]["nasdaq_inception_close"] is None

    def test_ensure_schema_upgrades_old_tracker(self):
        old = {
            "metadata": {"created": "2026-01-02"},
            "summary": {},
            "trades": [{"symbol": "LGD", "pnl_pct": 1.2}],
        }
        m._ensure_schema(old)
        assert old["metadata"]["benchmark_symbol"] == "^IXIC"
        assert old["metadata"]["inception_date"] == "2026-01-02"
        assert "benchmark" in old
        assert "alpha" in old
        assert old["trades"][0]["symbol"] == "LGD"  # preserved

    def test_load_tracker_upgrades_in_place(self, tmp_path: Path):
        p = tmp_path / "investment_tracker.json"
        p.write_text(json.dumps({
            "metadata": {"created": "2026-03-20"},
            "summary": {"total_trades": 3},
            "trades": [],
        }))
        tracker = m._load_tracker(p)
        assert tracker["metadata"]["benchmark_symbol"] == "^IXIC"
        assert tracker["alpha"]["monthly"] == {}

    def test_load_tracker_missing_file_returns_fresh(self, tmp_path: Path):
        tracker = m._load_tracker(tmp_path / "nope.json")
        assert "benchmark" in tracker
        assert tracker["trades"] == []


# ---------------------------------------------------------------------------
# Portfolio-return helpers
# ---------------------------------------------------------------------------

class TestPortfolioReturn:
    def test_no_trades_returns_zero(self):
        assert m._portfolio_return_pct(m._fresh_tracker()) == 0.0

    def test_single_trade_equals_pct(self):
        tracker = m._fresh_tracker()
        tracker["trades"].append({
            "status": "closed",
            "date": "2026-04-01",
            "pnl_pct": 5.0,
            "pnl_dollars": 50.0,
        })
        # 50 / 1000 = 5%
        assert m._portfolio_return_pct(tracker) == 5.0

    def test_multiple_trades_averaged_over_capital(self):
        tracker = m._fresh_tracker()
        tracker["trades"].extend([
            {"status": "closed", "date": "2026-01-10", "pnl_pct": 10.0, "pnl_dollars": 100.0},
            {"status": "closed", "date": "2026-02-10", "pnl_pct": -4.0, "pnl_dollars": -40.0},
        ])
        # (100 - 40) / (2 * 1000) = 3%
        assert m._portfolio_return_pct(tracker) == 3.0

    def test_ytd_filters_by_year(self):
        tracker = m._fresh_tracker()
        tracker["trades"].extend([
            {"status": "closed", "date": "2025-12-01", "pnl_pct": 10.0, "pnl_dollars": 100.0},
            {"status": "closed", "date": f"{datetime.date.today().year}-02-10",
             "pnl_pct": 2.0, "pnl_dollars": 20.0},
        ])
        # Only the current-year trade counts: 20 / 1000 = 2%
        assert m._portfolio_return_ytd_pct(tracker) == 2.0


# ---------------------------------------------------------------------------
# _compute_benchmark_state
# ---------------------------------------------------------------------------

class TestComputeBenchmarkState:
    def _stub_closes(self, inception=15000.0, ytd=16000.0, current=18000.0):
        """Return a function that maps date -> close based on the seed dates."""
        def _stub(for_date=None):
            today = datetime.date.today()
            if for_date is None:
                return current
            # Jan 2 of current year -> ytd; anything in 2025 -> inception
            if for_date.year < today.year:
                return inception
            if for_date.month == 1 and for_date.day <= 5:
                return ytd
            return current
        return _stub

    def test_alpha_math_trailing_nasdaq(self):
        tracker = m._fresh_tracker()
        tracker["metadata"]["inception_date"] = "2025-06-01"
        # Portfolio: 1 trade, +2% YTD and ITD
        tracker["trades"].append({
            "status": "closed",
            "date": f"{datetime.date.today().year}-03-15",
            "pnl_pct": 2.0,
            "pnl_dollars": 20.0,
        })
        stub = self._stub_closes(inception=15000.0, ytd=16000.0, current=18000.0)
        with patch.object(m, "_fetch_nasdaq_close", side_effect=stub):
            m._compute_benchmark_state(tracker)
        # NASDAQ ITD: (18000-15000)/15000 = 20.0% ; YTD: (18000-16000)/16000 = 12.5%
        assert tracker["benchmark"]["inception_to_date_pct"] == 20.0
        assert tracker["benchmark"]["ytd_pct"] == 12.5
        # Portfolio 2% ITD and 2% YTD — alpha is negative
        assert tracker["alpha"]["inception_to_date_pct"] == pytest.approx(2.0 - 20.0, abs=0.01)
        assert tracker["alpha"]["ytd_pct"] == pytest.approx(2.0 - 12.5, abs=0.01)

    def test_alpha_math_beating_nasdaq(self):
        tracker = m._fresh_tracker()
        tracker["metadata"]["inception_date"] = "2025-06-01"
        tracker["trades"].append({
            "status": "closed",
            "date": f"{datetime.date.today().year}-03-15",
            "pnl_pct": 25.0,
            "pnl_dollars": 250.0,
        })
        stub = self._stub_closes(inception=15000.0, ytd=16000.0, current=18000.0)
        with patch.object(m, "_fetch_nasdaq_close", side_effect=stub):
            m._compute_benchmark_state(tracker)
        # Portfolio 25% vs NASDAQ ITD 20% -> +5 alpha
        assert tracker["alpha"]["inception_to_date_pct"] == pytest.approx(5.0, abs=0.01)

    def test_ytd_rollover_refreshes_baseline(self):
        tracker = m._fresh_tracker()
        # Pretend we were last anchored in an earlier year
        tracker["metadata"]["nasdaq_ytd_year"] = datetime.date.today().year - 1
        tracker["metadata"]["nasdaq_ytd_start_close"] = 9999.0

        stub = self._stub_closes(inception=15000.0, ytd=16000.0, current=18000.0)
        with patch.object(m, "_fetch_nasdaq_close", side_effect=stub):
            m._compute_benchmark_state(tracker)
        # Rollover should have refreshed the YTD baseline to this year's Jan 2 close.
        assert tracker["metadata"]["nasdaq_ytd_year"] == datetime.date.today().year
        assert tracker["metadata"]["nasdaq_ytd_start_close"] == 16000.0

    def test_handles_missing_yfinance_gracefully(self):
        tracker = m._fresh_tracker()
        with patch.object(m, "_fetch_nasdaq_close", return_value=None):
            m._compute_benchmark_state(tracker)
        # No crash; no phantom numbers.
        assert tracker["benchmark"]["current_close"] is None


# ---------------------------------------------------------------------------
# _annotate_trade_with_nasdaq
# ---------------------------------------------------------------------------

class TestAnnotateTradeWithNasdaq:
    def test_weekly_alpha_math(self):
        trade = {
            "symbol": "WDC",
            "date": "2026-03-23",
            "trade_type": "weekly",
            "pnl_pct": 4.44,
        }
        # Stub so entry = 15000, exit = 15300 -> NASDAQ +2.0
        def _stub(for_date=None):
            if for_date and for_date.weekday() == 4:  # Friday exit
                return 15300.0
            return 15000.0
        with patch.object(m, "_fetch_nasdaq_close", side_effect=_stub):
            m._annotate_trade_with_nasdaq(trade)
        assert trade["nasdaq_entry"] == 15000.0
        assert trade["nasdaq_exit"] == 15300.0
        assert trade["nasdaq_return_pct"] == 2.0
        # 4.44 - 2.0 = 2.44 alpha
        assert trade["alpha_pct"] == pytest.approx(2.44, abs=0.01)

    def test_null_pnl_yields_null_alpha(self):
        trade = {"symbol": "X", "date": "2026-03-23", "trade_type": "weekly", "pnl_pct": None}
        with patch.object(m, "_fetch_nasdaq_close", return_value=15000.0):
            m._annotate_trade_with_nasdaq(trade)
        assert trade["alpha_pct"] is None

    def test_missing_data_leaves_fields_none(self):
        trade = {"symbol": "X", "date": "2026-03-23", "trade_type": "weekly", "pnl_pct": 3.0}
        with patch.object(m, "_fetch_nasdaq_close", return_value=None):
            m._annotate_trade_with_nasdaq(trade)
        assert trade["nasdaq_entry"] is None
        assert trade["alpha_pct"] is None


# ---------------------------------------------------------------------------
# _build_benchmark_block
# ---------------------------------------------------------------------------

class TestBuildBenchmarkBlock:
    def test_includes_all_four_numbers(self):
        tracker = m._fresh_tracker()
        tracker["benchmark"] = {
            "current_close": 17500.0,
            "ytd_pct": 10.0,
            "inception_to_date_pct": 22.0,
            "last_updated": "2026-04-16",
        }
        tracker["alpha"] = {"ytd_pct": -3.5, "inception_to_date_pct": -1.0, "monthly": {}}
        block = m._build_benchmark_block(tracker)
        assert "NASDAQ" in block
        assert "17,500" in block
        assert "+10.00%" in block
        assert "-3.50%" in block

    def test_missing_close_yields_fallback_message(self):
        tracker = m._fresh_tracker()
        tracker["benchmark"]["current_close"] = None
        block = m._build_benchmark_block(tracker)
        assert "unavailable" in block.lower()
