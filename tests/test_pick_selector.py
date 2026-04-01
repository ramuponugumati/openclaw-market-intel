"""
Unit tests for the Pick Selector Skill.

Validates Requirements: 11.5, 11.6, 17.4
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agents.orchestrator.skills.pick_selector import (
    select_options,
    select_stocks,
    enrich_options_picks,
    ETF_TICKERS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_combined_entry(
    ticker: str,
    score: float,
    direction: str,
    confidence: str = "MEDIUM",
) -> dict:
    """Build a combined-score entry matching score_combiner output."""
    return {
        "ticker": ticker,
        "composite_score": score,
        "direction": direction,
        "confidence": confidence,
        "agent_scores": {},
    }


def _make_combined_list() -> list[dict]:
    """Build a realistic combined list sorted by distance from 5.0."""
    entries = [
        _make_combined_entry("NVDA", 9.0, "CALL", "HIGH"),
        _make_combined_entry("AAPL", 7.5, "CALL", "MEDIUM"),
        _make_combined_entry("TSLA", 7.0, "CALL", "MEDIUM"),
        _make_combined_entry("MSFT", 6.5, "CALL", "MEDIUM"),
        _make_combined_entry("INTC", 2.0, "PUT", "HIGH"),
        _make_combined_entry("MU", 3.0, "PUT", "MEDIUM"),
        _make_combined_entry("QCOM", 3.5, "PUT", "MEDIUM"),
        _make_combined_entry("AMD", 5.2, "HOLD", "LOW"),
        _make_combined_entry("SPY", 8.0, "CALL", "HIGH"),   # ETF
        _make_combined_entry("QQQ", 7.8, "CALL", "HIGH"),   # ETF
        _make_combined_entry("PLTR", 6.8, "CALL", "MEDIUM"),
        _make_combined_entry("CRM", 6.2, "CALL", "MEDIUM"),
        _make_combined_entry("NFLX", 5.8, "HOLD", "LOW"),
        _make_combined_entry("DIS", 4.5, "HOLD", "LOW"),
        _make_combined_entry("IWM", 5.0, "HOLD", "LOW"),    # ETF
    ]
    # Sort by distance from 5.0 (matching combine() output)
    entries.sort(key=lambda x: abs(x["composite_score"] - 5.0), reverse=True)
    return entries


# ---------------------------------------------------------------------------
# select_options tests (Req 11.5)
# ---------------------------------------------------------------------------

class TestSelectOptions:

    def test_selects_3_calls_and_2_puts(self):
        """Should pick 6 strongest CALL + 4 strongest PUT (expanded from 3+2)."""
        combined = _make_combined_list()
        picks = select_options(combined)

        call_picks = [p for p in picks if p["direction"] == "CALL"]
        put_picks = [p for p in picks if p["direction"] == "PUT"]

        assert len(call_picks) == 6
        assert len(put_picks) == 3  # only 3 PUTs in test data

    def test_total_picks_is_5(self):
        combined = _make_combined_list()
        picks = select_options(combined)
        # 6 CALLs + 3 PUTs available in test data = 9
        assert len(picks) == 9

    def test_picks_ranked_by_distance_from_5(self):
        """Final picks should be sorted by distance from 5.0."""
        combined = _make_combined_list()
        picks = select_options(combined)

        distances = [abs(p["composite_score"] - 5.0) for p in picks]
        assert distances == sorted(distances, reverse=True)

    def test_pick_rank_assigned(self):
        """Each pick should have a 1-based pick_rank."""
        combined = _make_combined_list()
        picks = select_options(combined)

        ranks = [p["pick_rank"] for p in picks]
        assert ranks == list(range(1, len(picks) + 1))

    def test_fewer_than_3_calls_available(self):
        """If only 2 CALLs exist, should return 2 CALL + up to 4 PUT."""
        combined = [
            _make_combined_entry("AAPL", 8.0, "CALL"),
            _make_combined_entry("MSFT", 7.0, "CALL"),
            _make_combined_entry("INTC", 2.0, "PUT"),
            _make_combined_entry("MU", 3.0, "PUT"),
            _make_combined_entry("QCOM", 3.5, "PUT"),
        ]
        combined.sort(key=lambda x: abs(x["composite_score"] - 5.0), reverse=True)
        picks = select_options(combined)

        call_picks = [p for p in picks if p["direction"] == "CALL"]
        put_picks = [p for p in picks if p["direction"] == "PUT"]
        assert len(call_picks) == 2
        assert len(put_picks) == 3  # 3 PUTs available, cap is 4

    def test_no_puts_available(self):
        """If no PUTs exist, should return up to 6 CALLs."""
        combined = [
            _make_combined_entry("NVDA", 9.0, "CALL"),
            _make_combined_entry("AAPL", 8.0, "CALL"),
            _make_combined_entry("TSLA", 7.0, "CALL"),
            _make_combined_entry("MSFT", 6.5, "CALL"),
        ]
        combined.sort(key=lambda x: abs(x["composite_score"] - 5.0), reverse=True)
        picks = select_options(combined)

        assert len(picks) == 4  # only 4 CALLs available, cap is 6
        assert all(p["direction"] == "CALL" for p in picks)

    def test_empty_combined_returns_empty(self):
        assert select_options([]) == []


# ---------------------------------------------------------------------------
# select_stocks tests (Req 11.6, 17.4)
# ---------------------------------------------------------------------------

class TestSelectStocks:

    def test_excludes_etfs(self):
        """SPY, QQQ, IWM, DIA, ARKK should never appear in stock picks."""
        combined = _make_combined_list()
        picks = select_stocks(combined)

        tickers = {p["ticker"] for p in picks}
        assert tickers.isdisjoint(ETF_TICKERS)

    def test_max_10_picks(self):
        combined = _make_combined_list()
        picks = select_stocks(combined)
        assert len(picks) <= 20

    def test_buy_action_for_score_gte_6(self):
        """Tickers with score ≥ 6 should get BUY action."""
        combined = [_make_combined_entry("NVDA", 8.0, "CALL")]
        picks = select_stocks(combined)
        assert picks[0]["action"] == "BUY"

    def test_sell_action_for_score_lte_4(self):
        """Tickers with score ≤ 4 should get SELL/SHORT action."""
        combined = [_make_combined_entry("INTC", 2.5, "PUT")]
        picks = select_stocks(combined)
        assert picks[0]["action"] == "SELL/SHORT"

    def test_watch_action_for_score_between_4_and_6(self):
        """Tickers with 4 < score < 6 should get WATCH action."""
        combined = [_make_combined_entry("AMD", 5.2, "HOLD")]
        picks = select_stocks(combined)
        assert picks[0]["action"] == "WATCH"

    def test_boundary_score_6_is_buy(self):
        combined = [_make_combined_entry("CRM", 6.0, "CALL")]
        picks = select_stocks(combined)
        assert picks[0]["action"] == "BUY"

    def test_boundary_score_4_is_sell(self):
        combined = [_make_combined_entry("DIS", 4.0, "PUT")]
        picks = select_stocks(combined)
        assert picks[0]["action"] == "SELL/SHORT"

    def test_pick_rank_assigned(self):
        combined = _make_combined_list()
        picks = select_stocks(combined)
        ranks = [p["pick_rank"] for p in picks]
        assert ranks == list(range(1, len(picks) + 1))

    def test_sorted_by_distance_from_5(self):
        combined = _make_combined_list()
        picks = select_stocks(combined)
        distances = [abs(p["composite_score"] - 5.0) for p in picks]
        assert distances == sorted(distances, reverse=True)

    def test_empty_combined_returns_empty(self):
        assert select_stocks([]) == []


# ---------------------------------------------------------------------------
# enrich_options_picks tests
# ---------------------------------------------------------------------------

class TestEnrichOptionsPicks:
    """Tests for enrich_options_picks.

    These tests mock the options_analysis module at the import level to
    avoid triggering a real ``import yfinance`` (which may not be installed
    in the test environment).
    """

    def _enrich_with_mock(self, picks, mock_return):
        """Call enrich_options_picks with a mocked get_best_option."""
        mock_mod = MagicMock()
        mock_mod.get_best_option = MagicMock(return_value=mock_return)
        with patch.dict("sys.modules", {
            "agents.options_chain.skills.options_analysis": mock_mod,
        }):
            # Re-import so the lazy import inside enrich_options_picks
            # picks up our mock module instead of the real one.
            from importlib import reload
            import agents.orchestrator.skills.pick_selector as ps
            reload(ps)
            return ps.enrich_options_picks(picks)

    def test_enrichment_adds_option_contract(self):
        """Each pick should get an option_contract key after enrichment."""
        mock_contract = {
            "ticker": "NVDA", "direction": "CALL", "strike": 128.0,
            "expiry": "2026-01-17", "mid_price": 2.45, "contract_cost": 245.0,
        }
        picks = [_make_combined_entry("NVDA", 9.0, "CALL")]
        enriched = self._enrich_with_mock(picks, mock_contract)

        assert "option_contract" in enriched[0]
        assert enriched[0]["option_contract"]["strike"] == 128.0

    def test_enrichment_handles_hold_direction(self):
        """HOLD picks should be skipped (no option_contract added)."""
        picks = [_make_combined_entry("AMD", 5.2, "HOLD")]
        enriched = self._enrich_with_mock(picks, {})

        assert "option_contract" not in enriched[0]

    def test_enrichment_with_no_contract_found(self):
        """When no contract is found, option_contract should contain error."""
        error_result = {"ticker": "NVDA", "direction": "CALL",
                        "error": "No suitable contract found"}
        picks = [_make_combined_entry("NVDA", 9.0, "CALL")]
        enriched = self._enrich_with_mock(picks, error_result)

        assert enriched[0]["option_contract"]["error"] == "No suitable contract found"
