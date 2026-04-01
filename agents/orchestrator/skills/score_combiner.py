"""
Score Combiner Skill

Computes a composite score per ticker by combining all sub-agent scores
using self-adjusting weights.  Determines consensus direction and confidence
level for each ticker.

Requirements: 11.1, 11.2, 11.3, 11.4
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is importable so we can reach shared_memory_io
# ---------------------------------------------------------------------------
_PROJECT_ROOT = str(Path(__file__).resolve().parents[3])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import shared_memory_io  # noqa: E402

logger = logging.getLogger(__name__)

# Default weights used when fewer than 5 days have been evaluated.
DEFAULT_WEIGHTS: dict[str, float] = {
    "premarket": 0.25,
    "macro": 0.20,
    "technical": 0.20,
    "news": 0.12,
    "sentiment": 0.08,
    "fundamentals": 0.08,
    "congress": 0.07,
}

MIN_DAYS_FOR_LEARNED_WEIGHTS = 5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_weights() -> dict[str, float]:
    """
    Load agent weights from shared memory.

    Falls back to DEFAULT_WEIGHTS if the learned weights file has fewer
    than 5 days evaluated (Requirement 11.2).
    """
    data = shared_memory_io.load_weights()
    days_evaluated = data.get("days_evaluated", 0)

    if days_evaluated >= MIN_DAYS_FOR_LEARNED_WEIGHTS:
        learned = data.get("weights", {})
        if learned:
            logger.info(
                "Using learned weights (%d days evaluated): %s",
                days_evaluated,
                learned,
            )
            return learned

    logger.info(
        "Using default weights (days_evaluated=%d < %d)",
        days_evaluated,
        MIN_DAYS_FOR_LEARNED_WEIGHTS,
    )
    return dict(DEFAULT_WEIGHTS)


def _determine_direction(directions: list[str]) -> str:
    """
    Determine consensus direction from a list of agent directions.

    CALL if ≥3 agents signal CALL, PUT if ≥3 signal PUT, else HOLD.
    (Requirement 11.3)
    """
    call_count = sum(1 for d in directions if d == "CALL")
    put_count = sum(1 for d in directions if d == "PUT")

    if call_count >= 3:
        return "CALL"
    if put_count >= 3:
        return "PUT"
    return "HOLD"


def _determine_confidence(directions: list[str], consensus: str) -> str:
    """
    Assign confidence level based on agent agreement.

    HIGH if ≥4 agree on the consensus direction, MEDIUM if exactly 3, LOW for HOLD.
    (Requirement 11.4)
    """
    if consensus == "HOLD":
        return "LOW"

    agree_count = sum(1 for d in directions if d == consensus)
    if agree_count >= 4:
        return "HIGH"
    return "MEDIUM"


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def combine(
    agent_results: dict,
    weights: dict[str, float] | None = None,
) -> list[dict]:
    """
    Combine sub-agent scores into a single composite score per ticker.

    Args:
        agent_results: Dict mapping agent_id → parsed result dict.
            Each result dict must have a ``results`` key containing a list
            of ``{ticker, score, direction, ...}`` dicts.
        weights: Optional explicit weight dict.  If *None*, weights are
            loaded from shared memory (with default fallback).

    Returns:
        A list of dicts sorted by composite score distance from 5.0
        (strongest signals first), each containing::

            {
                "ticker": str,
                "composite_score": float,
                "direction": str,       # CALL / PUT / HOLD
                "confidence": str,      # HIGH / MEDIUM / LOW
                "agent_scores": {agent_id: {"score": float, "direction": str}},
            }
    """
    if weights is None:
        weights = _load_weights()

    # Build per-ticker aggregation: {ticker: {agent_id: {score, direction}}}
    ticker_data: dict[str, dict[str, dict]] = {}

    for agent_id, result in agent_results.items():
        agent_weight = weights.get(agent_id, 0.0)
        if agent_weight == 0.0:
            continue

        entries = result.get("results", [])
        for entry in entries:
            ticker = entry.get("ticker", "")
            if not ticker:
                continue
            score = float(entry.get("score", 5.0))
            direction = entry.get("direction", "HOLD")

            if ticker not in ticker_data:
                ticker_data[ticker] = {}
            ticker_data[ticker][agent_id] = {
                "score": score,
                "direction": direction,
            }

    # Compute composite score per ticker
    combined: list[dict] = []
    for ticker, agents in ticker_data.items():
        weighted_sum = 0.0
        total_weight = 0.0
        directions: list[str] = []

        for agent_id, info in agents.items():
            w = weights.get(agent_id, 0.0)
            weighted_sum += info["score"] * w
            total_weight += w
            directions.append(info["direction"])

        # Normalise by total contributing weight so partial results still
        # produce a meaningful 0-10 score.
        composite = weighted_sum / total_weight if total_weight > 0 else 5.0

        consensus = _determine_direction(directions)
        confidence = _determine_confidence(directions, consensus)

        combined.append({
            "ticker": ticker,
            "composite_score": round(composite, 4),
            "direction": consensus,
            "confidence": confidence,
            "agent_scores": agents,
        })

    # Sort by distance from neutral 5.0 (strongest signals first)
    combined.sort(key=lambda x: abs(x["composite_score"] - 5.0), reverse=True)

    logger.info("Combined scores for %d tickers", len(combined))
    return combined
