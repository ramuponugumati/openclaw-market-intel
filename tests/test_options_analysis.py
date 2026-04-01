"""
Unit tests for the Options Chain Analysis Skill.

Validates Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 21.1, 21.4
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agents.options_chain.skills.options_analysis import (
    get_best_option,
    run,
    write_to_shared_memory,
    _find_target_expiry,
    _rank_contracts,
    MAX_PREMIUM_PER_CONTRACT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_options_df(**overrides) -> pd.DataFrame:
    """Return a realistic options DataFrame with sensible defaults."""
    base = {
        "strike": [130.0, 135.0, 140.0, 145.0, 150.0],
        "bid": [3.00, 2.50, 2.00, 1.50, 1.00],
        "ask": [3.20, 2.70, 2.20, 1.70, 1.20],
        "volume": [500.0, 800.0, 1200.0, 600.0, 300.0],
        "openInterest": [2000.0, 3500.0, 5000.0, 2500.0, 1000.0],
        "impliedVolatility": [0.35, 0.33, 0.30, 0.32, 0.38],
    }
    base.update(overrides)
    return pd.DataFrame(base)


def _make_chain(calls_df=None, puts_df=None):
    """Return a mock option chain object."""
    chain = MagicMock()
    chain.calls = calls_df if calls_df is not None else _make_options_df()
    chain.puts = puts_df if puts_df is not None else _make_options_df()
    return chain


def _make_ticker_data(current_price=140.0, expirations=None):
    """Return a mock ticker data dict."""
    if expirations is None:
        from datetime import datetime, timedelta
        # 3 days out
        exp = (datetime.now().date() + timedelta(days=3)).strftime("%Y-%m-%d")
        expirations = [exp]
    return {"current_price": current_price, "expirations": expirations}


# ---------------------------------------------------------------------------
# Requirement 8.1 — Retrieve option chains with 1-7 day expiry
# ---------------------------------------------------------------------------

class TestExpirySelection:
    """Validates expiry date selection within 1-7 day window."""

    def test_selects_expiry_within_1_to_7_days(self):
        from datetime import datetime, timedelta
        today = datetime.now().date()
        exps = [
            (today + timedelta(days=0)).strftime("%Y-%m-%d"),  # today, skip
            (today + timedelta(days=3)).strftime("%Y-%m-%d"),  # 3 days, pick
            (today + timedelta(days=10)).strftime("%Y-%m-%d"),  # too far
        ]
        result = _find_target_expiry(exps)
        assert result == exps[1]

    def test_skips_today_expiry(self):
        from datetime import datetime, timedelta
        today = datetime.now().date()
        exps = [
            today.strftime("%Y-%m-%d"),  # today
            (today + timedelta(days=5)).strftime("%Y-%m-%d"),
        ]
        result = _find_target_expiry(exps)
        assert result == exps[1]

    def test_fallback_to_nearest_when_none_in_range(self):
        from datetime import datetime, timedelta
        today = datetime.now().date()
        exps = [
            (today + timedelta(days=14)).strftime("%Y-%m-%d"),
            (today + timedelta(days=21)).strftime("%Y-%m-%d"),
        ]
        result = _find_target_expiry(exps)
        assert result == exps[0]

    def test_returns_none_for_empty_list(self):
        assert _find_target_expiry([]) is None


# ---------------------------------------------------------------------------
# Requirement 8.2 — Filter contracts ≤$300 per contract
# ---------------------------------------------------------------------------

class TestAffordabilityFilter:
    """Validates the $300 per-contract affordability filter."""

    def test_filters_to_affordable_contracts(self):
        # All contracts: mid_price * 100 = contract_cost
        # bid=2, ask=2.20 → mid=2.10 → cost=210 (affordable)
        # bid=4, ask=4.20 → mid=4.10 → cost=410 (over budget)
        df = pd.DataFrame({
            "strike": [130.0, 140.0],
            "bid": [4.00, 2.00],
            "ask": [4.20, 2.20],
            "volume": [500.0, 800.0],
            "openInterest": [2000.0, 3000.0],
            "impliedVolatility": [0.30, 0.30],
        })
        ranked = _rank_contracts(df, current_price=140.0)
        # Only the affordable one should remain (cost=210)
        assert len(ranked) == 1
        assert ranked.iloc[0]["strike"] == 140.0
        assert ranked.iloc[0]["over_budget"] == False

    def test_fallback_5_cheapest_when_none_affordable(self):
        # All contracts over $300
        df = pd.DataFrame({
            "strike": [100.0 + i * 5 for i in range(8)],
            "bid": [4.00 + i * 0.5 for i in range(8)],
            "ask": [4.50 + i * 0.5 for i in range(8)],
            "volume": [100.0] * 8,
            "openInterest": [500.0] * 8,
            "impliedVolatility": [0.30] * 8,
        })
        ranked = _rank_contracts(df, current_price=120.0)
        assert len(ranked) == 5
        assert all(ranked["over_budget"])


# ---------------------------------------------------------------------------
# Requirement 8.3 — Composite ranking: moneyness 30%, OI 25%, vol 25%, spread 20%
# ---------------------------------------------------------------------------

class TestCompositeRanking:
    """Validates the composite ranking formula."""

    def test_near_the_money_ranks_higher(self):
        """Contract closer to current price should rank higher (moneyness 30%)."""
        df = pd.DataFrame({
            "strike": [139.0, 160.0],  # near vs far from 140
            "bid": [2.00, 2.00],
            "ask": [2.20, 2.20],
            "volume": [500.0, 500.0],
            "openInterest": [2000.0, 2000.0],
            "impliedVolatility": [0.30, 0.30],
        })
        ranked = _rank_contracts(df, current_price=140.0)
        best = ranked.nlargest(1, "rank_score").iloc[0]
        assert best["strike"] == 139.0

    def test_higher_oi_ranks_higher(self):
        """Higher open interest should rank higher (OI 25%)."""
        df = pd.DataFrame({
            "strike": [140.0, 140.0],
            "bid": [2.00, 2.00],
            "ask": [2.20, 2.20],
            "volume": [500.0, 500.0],
            "openInterest": [8000.0, 100.0],
            "impliedVolatility": [0.30, 0.30],
        })
        ranked = _rank_contracts(df, current_price=140.0)
        best = ranked.nlargest(1, "rank_score").iloc[0]
        assert best["openInterest"] == 8000.0

    def test_higher_volume_ranks_higher(self):
        """Higher volume should rank higher (volume 25%)."""
        df = pd.DataFrame({
            "strike": [140.0, 140.0],
            "bid": [2.00, 2.00],
            "ask": [2.20, 2.20],
            "volume": [4000.0, 50.0],
            "openInterest": [2000.0, 2000.0],
            "impliedVolatility": [0.30, 0.30],
        })
        ranked = _rank_contracts(df, current_price=140.0)
        best = ranked.nlargest(1, "rank_score").iloc[0]
        assert best["volume"] == 4000.0

    def test_tighter_spread_ranks_higher(self):
        """Tighter bid-ask spread should rank higher (spread 20%)."""
        df = pd.DataFrame({
            "strike": [140.0, 140.0],
            "bid": [2.00, 1.00],
            "ask": [2.05, 2.00],  # tight vs wide spread
            "volume": [500.0, 500.0],
            "openInterest": [2000.0, 2000.0],
            "impliedVolatility": [0.30, 0.30],
        })
        ranked = _rank_contracts(df, current_price=140.0)
        best = ranked.nlargest(1, "rank_score").iloc[0]
        assert best["bid"] == 2.00  # the tight-spread contract


# ---------------------------------------------------------------------------
# Requirement 8.4 — Return top contract with all required fields
# ---------------------------------------------------------------------------

class TestReturnSchema:
    """Validates the returned dict contains all required fields."""

    def test_successful_result_has_all_fields(self):
        from datetime import datetime, timedelta
        exp = (datetime.now().date() + timedelta(days=3)).strftime("%Y-%m-%d")
        ticker_data = _make_ticker_data(current_price=140.0, expirations=[exp])
        chain = _make_chain()

        with patch(
            "agents.options_chain.skills.options_analysis._fetch_ticker_data",
            return_value=ticker_data,
        ), patch(
            "agents.options_chain.skills.options_analysis._fetch_option_chain",
            return_value=chain,
        ):
            result = get_best_option("AAPL", "CALL")

        required_keys = {
            "ticker", "direction", "strike", "expiry", "bid", "ask",
            "mid_price", "contract_cost", "volume", "open_interest",
            "implied_vol", "current_price",
        }
        assert required_keys.issubset(result.keys())
        assert result["ticker"] == "AAPL"
        assert result["direction"] == "CALL"

    def test_returns_single_top_contract(self):
        from datetime import datetime, timedelta
        exp = (datetime.now().date() + timedelta(days=3)).strftime("%Y-%m-%d")
        ticker_data = _make_ticker_data(current_price=140.0, expirations=[exp])
        chain = _make_chain()

        with patch(
            "agents.options_chain.skills.options_analysis._fetch_ticker_data",
            return_value=ticker_data,
        ), patch(
            "agents.options_chain.skills.options_analysis._fetch_option_chain",
            return_value=chain,
        ):
            result = get_best_option("NVDA", "CALL")

        # Should be a single dict, not a list
        assert isinstance(result, dict)
        assert "strike" in result


# ---------------------------------------------------------------------------
# Requirement 8.5 — Fallback: 5 cheapest if none affordable
# ---------------------------------------------------------------------------

class TestFallbackBehavior:
    """Validates fallback to 5 cheapest when none meet affordability."""

    def test_over_budget_flag_set(self):
        from datetime import datetime, timedelta
        exp = (datetime.now().date() + timedelta(days=3)).strftime("%Y-%m-%d")
        ticker_data = _make_ticker_data(current_price=140.0, expirations=[exp])

        # All contracts expensive (mid > $3 → cost > $300)
        expensive_df = pd.DataFrame({
            "strike": [130.0, 135.0, 140.0, 145.0, 150.0, 155.0],
            "bid": [5.00, 4.50, 4.00, 3.50, 3.20, 3.10],
            "ask": [5.50, 5.00, 4.50, 4.00, 3.60, 3.50],
            "volume": [500.0] * 6,
            "openInterest": [2000.0] * 6,
            "impliedVolatility": [0.30] * 6,
        })
        chain = _make_chain(calls_df=expensive_df)

        with patch(
            "agents.options_chain.skills.options_analysis._fetch_ticker_data",
            return_value=ticker_data,
        ), patch(
            "agents.options_chain.skills.options_analysis._fetch_option_chain",
            return_value=chain,
        ):
            result = get_best_option("TSLA", "CALL")

        assert result.get("over_budget") is True


# ---------------------------------------------------------------------------
# Requirement 21.1, 21.4 — Error handling and timeouts
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Validates graceful degradation on failures."""

    def test_no_current_price_returns_empty(self):
        ticker_data = {"current_price": 0, "expirations": ["2026-01-20"]}
        with patch(
            "agents.options_chain.skills.options_analysis._fetch_ticker_data",
            return_value=ticker_data,
        ):
            result = get_best_option("BAD", "CALL")
        assert result == {}

    def test_no_expirations_returns_empty(self):
        ticker_data = {"current_price": 140.0, "expirations": []}
        with patch(
            "agents.options_chain.skills.options_analysis._fetch_ticker_data",
            return_value=ticker_data,
        ):
            result = get_best_option("BAD", "CALL")
        assert result == {}

    def test_exception_returns_empty(self):
        with patch(
            "agents.options_chain.skills.options_analysis._fetch_ticker_data",
            side_effect=RuntimeError("network error"),
        ):
            result = get_best_option("ERR", "CALL")
        assert result == {}

    def test_empty_chain_returns_empty(self):
        from datetime import datetime, timedelta
        exp = (datetime.now().date() + timedelta(days=3)).strftime("%Y-%m-%d")
        ticker_data = _make_ticker_data(current_price=140.0, expirations=[exp])
        empty_chain = _make_chain(calls_df=pd.DataFrame())

        with patch(
            "agents.options_chain.skills.options_analysis._fetch_ticker_data",
            return_value=ticker_data,
        ), patch(
            "agents.options_chain.skills.options_analysis._fetch_option_chain",
            return_value=empty_chain,
        ):
            result = get_best_option("EMPTY", "CALL")
        assert result == {}


# ---------------------------------------------------------------------------
# run() — accepts watchlist + config, processes picks
# ---------------------------------------------------------------------------

class TestRun:
    """Validates the run() public interface."""

    def test_processes_call_and_put_picks(self):
        from datetime import datetime, timedelta
        exp = (datetime.now().date() + timedelta(days=3)).strftime("%Y-%m-%d")
        ticker_data = _make_ticker_data(current_price=140.0, expirations=[exp])
        chain = _make_chain()

        with patch(
            "agents.options_chain.skills.options_analysis._fetch_ticker_data",
            return_value=ticker_data,
        ), patch(
            "agents.options_chain.skills.options_analysis._fetch_option_chain",
            return_value=chain,
        ):
            results = run([
                {"ticker": "AAPL", "direction": "CALL"},
                {"ticker": "INTC", "direction": "PUT"},
            ])

        assert len(results) == 2
        assert results[0]["ticker"] == "AAPL"
        assert results[1]["ticker"] == "INTC"

    def test_skips_hold_direction(self):
        results = run([
            {"ticker": "MSFT", "direction": "HOLD"},
        ])
        assert len(results) == 0

    def test_returns_error_for_failed_ticker(self):
        with patch(
            "agents.options_chain.skills.options_analysis._fetch_ticker_data",
            return_value={"current_price": 0, "expirations": []},
        ):
            results = run([{"ticker": "BAD", "direction": "CALL"}])
        assert len(results) == 1
        assert "error" in results[0]

    def test_accepts_config_parameter(self):
        with patch(
            "agents.options_chain.skills.options_analysis._fetch_ticker_data",
            return_value={"current_price": 0, "expirations": []},
        ):
            results = run(
                [{"ticker": "AAPL", "direction": "CALL"}],
                config={"max_premium": 300},
            )
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# write_to_shared_memory — delegates to shared_memory_io
# ---------------------------------------------------------------------------

class TestWriteToSharedMemory:
    """Validates shared memory integration."""

    def test_writes_and_reads_back(self, tmp_path):
        """Round-trip: write results, read them back via shared_memory_io."""
        with patch.dict("os.environ", {"SHARED_MEMORY_PATH": str(tmp_path)}):
            (tmp_path / "runs").mkdir(parents=True, exist_ok=True)

            sample = [
                {
                    "ticker": "NVDA",
                    "direction": "CALL",
                    "strike": 128.0,
                    "expiry": "2026-01-17",
                    "bid": 2.30,
                    "ask": 2.60,
                    "mid_price": 2.45,
                    "contract_cost": 245.0,
                    "volume": 1523,
                    "open_interest": 8900,
                    "implied_vol": 0.42,
                    "current_price": 128.50,
                },
            ]
            filepath = write_to_shared_memory("20260115_053000", sample)
            assert Path(filepath).exists()

            import shared_memory_io
            parsed = shared_memory_io.read_agent_result("options_chain", "20260115_053000")
            assert parsed is not None
            assert parsed["agent_id"] == "options_chain"
            assert parsed["run_id"] == "20260115_053000"
            assert len(parsed["results"]) == 1
            assert parsed["results"][0]["ticker"] == "NVDA"
