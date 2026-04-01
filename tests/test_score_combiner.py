"""
Unit tests for the Score Combiner Skill.

Validates Requirements: 11.1, 11.2, 11.3, 11.4
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from agents.orchestrator.skills.score_combiner import (
    combine,
    _determine_direction,
    _determine_confidence,
    _load_weights,
    DEFAULT_WEIGHTS,
    MIN_DAYS_FOR_LEARNED_WEIGHTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent_result(agent_id: str, entries: list[dict]) -> dict:
    """Build a parsed agent result dict matching poll_completion output."""
    return {
        "agent_id": agent_id,
        "run_id": "test_run",
        "status": "complete",
        "tickers_analyzed": len(entries),
        "results": entries,
    }


EQUAL_WEIGHTS = {
    "fundamentals": 1 / 7,
    "sentiment": 1 / 7,
    "macro": 1 / 7,
    "news": 1 / 7,
    "technical": 1 / 7,
    "premarket": 1 / 7,
    "congress": 1 / 7,
}


# ---------------------------------------------------------------------------
# Weight loading tests (Req 11.2)
# ---------------------------------------------------------------------------

class TestLoadWeights:

    @patch("agents.orchestrator.skills.score_combiner.shared_memory_io")
    def test_uses_defaults_when_few_days_evaluated(self, mock_sio):
        """Should use default weights when days_evaluated < 5."""
        mock_sio.load_weights.return_value = {
            "days_evaluated": 3,
            "weights": {"fundamentals": 0.50, "sentiment": 0.50},
        }
        w = _load_weights()
        assert w == DEFAULT_WEIGHTS

    @patch("agents.orchestrator.skills.score_combiner.shared_memory_io")
    def test_uses_learned_weights_when_enough_days(self, mock_sio):
        """Should use learned weights when days_evaluated >= 5."""
        learned = {"fundamentals": 0.25, "sentiment": 0.20, "macro": 0.10,
                    "news": 0.15, "technical": 0.10, "premarket": 0.10, "congress": 0.10}
        mock_sio.load_weights.return_value = {
            "days_evaluated": 10,
            "weights": learned,
        }
        w = _load_weights()
        assert w == learned

    @patch("agents.orchestrator.skills.score_combiner.shared_memory_io")
    def test_uses_defaults_when_file_empty(self, mock_sio):
        """Should use defaults when weights file returns empty dict."""
        mock_sio.load_weights.return_value = {}
        w = _load_weights()
        assert w == DEFAULT_WEIGHTS


# ---------------------------------------------------------------------------
# Direction consensus tests (Req 11.3)
# ---------------------------------------------------------------------------

class TestDetermineDirection:

    def test_call_when_3_or_more_call(self):
        assert _determine_direction(["CALL", "CALL", "CALL", "HOLD"]) == "CALL"

    def test_put_when_3_or_more_put(self):
        assert _determine_direction(["PUT", "PUT", "PUT", "CALL"]) == "PUT"

    def test_hold_when_no_majority(self):
        assert _determine_direction(["CALL", "CALL", "PUT", "PUT"]) == "HOLD"

    def test_hold_when_all_hold(self):
        assert _determine_direction(["HOLD", "HOLD", "HOLD"]) == "HOLD"

    def test_call_takes_precedence_when_both_at_3(self):
        """If both CALL and PUT have ≥3, CALL is checked first."""
        dirs = ["CALL", "CALL", "CALL", "PUT", "PUT", "PUT"]
        assert _determine_direction(dirs) == "CALL"


# ---------------------------------------------------------------------------
# Confidence tests (Req 11.4)
# ---------------------------------------------------------------------------

class TestDetermineConfidence:

    def test_high_when_4_agree(self):
        dirs = ["CALL", "CALL", "CALL", "CALL", "HOLD"]
        assert _determine_confidence(dirs, "CALL") == "HIGH"

    def test_medium_when_exactly_3_agree(self):
        dirs = ["CALL", "CALL", "CALL", "PUT", "HOLD"]
        assert _determine_confidence(dirs, "CALL") == "MEDIUM"

    def test_low_for_hold(self):
        dirs = ["CALL", "PUT", "HOLD"]
        assert _determine_confidence(dirs, "HOLD") == "LOW"


# ---------------------------------------------------------------------------
# Composite score combination tests (Req 11.1)
# ---------------------------------------------------------------------------

class TestCombine:

    def test_composite_score_with_equal_weights(self):
        """With equal weights, composite should be the average of agent scores."""
        agent_results = {
            "fundamentals": _make_agent_result("fundamentals", [
                {"ticker": "AAPL", "score": 8.0, "direction": "CALL"},
            ]),
            "sentiment": _make_agent_result("sentiment", [
                {"ticker": "AAPL", "score": 6.0, "direction": "CALL"},
            ]),
            "macro": _make_agent_result("macro", [
                {"ticker": "AAPL", "score": 7.0, "direction": "CALL"},
            ]),
        }
        weights = {"fundamentals": 1 / 3, "sentiment": 1 / 3, "macro": 1 / 3}
        result = combine(agent_results, weights=weights)

        assert len(result) == 1
        assert result[0]["ticker"] == "AAPL"
        assert result[0]["composite_score"] == pytest.approx(7.0, abs=0.01)

    def test_composite_score_with_unequal_weights(self):
        """Weighted sum should reflect different agent weights."""
        agent_results = {
            "fundamentals": _make_agent_result("fundamentals", [
                {"ticker": "NVDA", "score": 9.0, "direction": "CALL"},
            ]),
            "sentiment": _make_agent_result("sentiment", [
                {"ticker": "NVDA", "score": 3.0, "direction": "PUT"},
            ]),
        }
        weights = {"fundamentals": 0.75, "sentiment": 0.25}
        result = combine(agent_results, weights=weights)

        # 9.0 * 0.75 + 3.0 * 0.25 = 6.75 + 0.75 = 7.5
        assert result[0]["composite_score"] == pytest.approx(7.5, abs=0.01)

    def test_multiple_tickers_sorted_by_distance_from_5(self):
        """Tickers should be sorted by distance from neutral 5.0."""
        agent_results = {
            "fundamentals": _make_agent_result("fundamentals", [
                {"ticker": "AAPL", "score": 5.5, "direction": "HOLD"},
                {"ticker": "NVDA", "score": 9.0, "direction": "CALL"},
                {"ticker": "INTC", "score": 2.0, "direction": "PUT"},
            ]),
        }
        weights = {"fundamentals": 1.0}
        result = combine(agent_results, weights=weights)

        # NVDA (dist 4.0) > INTC (dist 3.0) > AAPL (dist 0.5)
        assert result[0]["ticker"] == "NVDA"
        assert result[1]["ticker"] == "INTC"
        assert result[2]["ticker"] == "AAPL"

    def test_consensus_direction_and_confidence_in_output(self):
        """Output should include direction and confidence fields."""
        agent_results = {
            "fundamentals": _make_agent_result("fundamentals", [
                {"ticker": "TSLA", "score": 8.0, "direction": "CALL"},
            ]),
            "sentiment": _make_agent_result("sentiment", [
                {"ticker": "TSLA", "score": 7.5, "direction": "CALL"},
            ]),
            "macro": _make_agent_result("macro", [
                {"ticker": "TSLA", "score": 7.0, "direction": "CALL"},
            ]),
            "news": _make_agent_result("news", [
                {"ticker": "TSLA", "score": 6.0, "direction": "CALL"},
            ]),
        }
        weights = {"fundamentals": 0.25, "sentiment": 0.25, "macro": 0.25, "news": 0.25}
        result = combine(agent_results, weights=weights)

        assert result[0]["direction"] == "CALL"
        assert result[0]["confidence"] == "HIGH"

    def test_agent_scores_preserved_in_output(self):
        """Each ticker should carry per-agent score breakdown."""
        agent_results = {
            "fundamentals": _make_agent_result("fundamentals", [
                {"ticker": "AAPL", "score": 7.0, "direction": "CALL"},
            ]),
            "sentiment": _make_agent_result("sentiment", [
                {"ticker": "AAPL", "score": 6.0, "direction": "CALL"},
            ]),
        }
        weights = {"fundamentals": 0.5, "sentiment": 0.5}
        result = combine(agent_results, weights=weights)

        assert "fundamentals" in result[0]["agent_scores"]
        assert result[0]["agent_scores"]["fundamentals"]["score"] == 7.0

    def test_partial_agent_coverage_normalises_correctly(self):
        """If only some agents cover a ticker, score should still be 0-10."""
        agent_results = {
            "fundamentals": _make_agent_result("fundamentals", [
                {"ticker": "RARE", "score": 8.0, "direction": "CALL"},
            ]),
            # sentiment has no data for RARE
            "sentiment": _make_agent_result("sentiment", []),
        }
        weights = {"fundamentals": 0.5, "sentiment": 0.5}
        result = combine(agent_results, weights=weights)

        # Only fundamentals contributes → normalised to 8.0
        assert result[0]["composite_score"] == pytest.approx(8.0, abs=0.01)

    def test_empty_agent_results_returns_empty(self):
        """No agent results should produce an empty list."""
        result = combine({}, weights=DEFAULT_WEIGHTS)
        assert result == []

    @patch("agents.orchestrator.skills.score_combiner.shared_memory_io")
    def test_loads_weights_from_shared_memory_when_none(self, mock_sio):
        """When weights=None, should load from shared memory."""
        mock_sio.load_weights.return_value = {"days_evaluated": 0, "weights": {}}
        agent_results = {
            "fundamentals": _make_agent_result("fundamentals", [
                {"ticker": "AAPL", "score": 7.0, "direction": "CALL"},
            ]),
        }
        result = combine(agent_results, weights=None)
        mock_sio.load_weights.assert_called_once()
        assert len(result) == 1
