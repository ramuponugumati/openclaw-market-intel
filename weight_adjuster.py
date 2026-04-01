"""
Weight Adjustment Engine

Computes per-agent accuracy from historical pick evaluations and
recalculates agent weights so that more accurate agents have greater
influence. Persists learned weights to shared memory.

Adapted from update_agent_weights() in market-intel/tracker.py.

Requirements: 15.1, 15.2, 15.3, 15.4, 15.5
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import shared_memory_io
from tracker import get_evaluated_days

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS: dict[str, float] = {
    "fundamentals": 0.18,
    "sentiment": 0.15,
    "macro": 0.10,
    "news": 0.15,
    "technical": 0.15,
    "premarket": 0.12,
    "congress": 0.15,
}

# Minimum evaluated days before learning kicks in (Req 15.3)
MIN_DAYS_FOR_LEARNING = 5

# Trailing window for accuracy computation (Req 15.2)
TRAILING_DAYS = 30


def compute_agent_accuracy(evaluated_days: list[dict]) -> dict[str, dict]:
    """
    Compute per-agent accuracy over the provided evaluated days.

    For each evaluated day, builds a result_map {ticker → was_correct}
    from EOD results, then checks each pick's per-agent scores to
    determine if the agent's directional prediction was correct.

    Returns:
        Dict mapping agent_id → {correct: int, total: int, accuracy: float}
    """
    agent_correct: dict[str, int] = {}
    agent_total: dict[str, int] = {}

    for day in evaluated_days:
        eod = day.get("eod_results", {})
        if not eod or eod.get("error"):
            continue

        # Build result map: ticker → was_correct
        result_map: dict[str, bool] = {}
        for r in eod.get("options", []):
            if "correct" in r:
                result_map[r["ticker"]] = r["correct"]
        for r in eod.get("stocks", []):
            if "correct" in r:
                result_map[r["ticker"]] = r["correct"]

        # Check each pick's per-agent contributions
        all_picks = day.get("options_picks", []) + day.get("stock_picks", [])
        for pick in all_picks:
            ticker = pick.get("ticker", "")
            was_correct = result_map.get(ticker)
            if was_correct is None:
                continue

            agents = pick.get("agents", {})
            for agent_id, agent_data in agents.items():
                agent_total[agent_id] = agent_total.get(agent_id, 0) + 1
                direction = (
                    agent_data.get("direction", "HOLD")
                    if isinstance(agent_data, dict)
                    else "HOLD"
                )
                # Agent is correct if its direction matched the outcome,
                # or if it was HOLD (neutral — not penalized)
                if (direction in ("CALL", "PUT") and was_correct) or direction == "HOLD":
                    agent_correct[agent_id] = agent_correct.get(agent_id, 0) + 1

    # Compute accuracy ratios
    accuracy_data: dict[str, dict] = {}
    for agent_id in DEFAULT_WEIGHTS:
        total = agent_total.get(agent_id, 0)
        correct = agent_correct.get(agent_id, 0)
        acc = correct / total if total > 0 else 0.5
        accuracy_data[agent_id] = {
            "correct": correct,
            "total": total,
            "accuracy": round(acc, 4),
        }

    return accuracy_data


def update_weights() -> dict:
    """
    Recalculate and persist agent weights based on historical accuracy.

    Algorithm (preserved from market-intel/tracker.py):
    1. Collect evaluated days from pick history (trailing 30 days)
    2. Compute per-agent accuracy
    3. If ≥5 days evaluated: normalize accuracy ratios so weights sum to 1.0
    4. Persist to shared_memory/weights/learned_weights.json
    5. Log previous weights, new weights, and accuracy data

    Returns:
        Dict with keys: weights_updated (bool), weights, previous_weights,
        accuracy_data, days_evaluated.
    """
    evaluated = get_evaluated_days(max_days=TRAILING_DAYS)
    days_count = len(evaluated)

    # Load current weights for comparison
    current_data = shared_memory_io.load_weights()
    previous_weights = current_data.get("weights", dict(DEFAULT_WEIGHTS))

    result: dict = {
        "weights_updated": False,
        "weights": dict(previous_weights),
        "previous_weights": dict(previous_weights),
        "accuracy_data": {},
        "days_evaluated": days_count,
    }

    if days_count < MIN_DAYS_FOR_LEARNING:
        logger.info(
            "Need %d+ evaluated days to learn (have %d). Using current weights.",
            MIN_DAYS_FOR_LEARNING,
            days_count,
        )
        return result

    # Compute accuracy from trailing evaluated days
    accuracy_data = compute_agent_accuracy(evaluated)
    result["accuracy_data"] = accuracy_data

    # Normalize: new_weight = accuracy / sum(all accuracies)
    new_weights: dict[str, float] = {}
    total_accuracy = sum(
        accuracy_data[agent]["accuracy"] for agent in DEFAULT_WEIGHTS
    )

    if total_accuracy > 0:
        for agent in DEFAULT_WEIGHTS:
            new_weights[agent] = round(
                accuracy_data[agent]["accuracy"] / total_accuracy, 3
            )
    else:
        # Fallback to equal weights if all accuracies are zero
        equal = round(1.0 / len(DEFAULT_WEIGHTS), 3)
        new_weights = {agent: equal for agent in DEFAULT_WEIGHTS}

    result["weights"] = new_weights
    result["weights_updated"] = True

    # Persist to shared memory (Req 15.4)
    weight_data = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "weights": new_weights,
        "accuracy_data": accuracy_data,
        "days_evaluated": days_count,
    }
    shared_memory_io.save_weights(weight_data)

    # Log the update (Req 15.5)
    logger.info(
        "Weight update — days_evaluated: %d\n"
        "  Previous: %s\n"
        "  New:      %s\n"
        "  Accuracy: %s",
        days_count,
        previous_weights,
        new_weights,
        {a: d["accuracy"] for a, d in accuracy_data.items()},
    )

    return result


def get_overall_accuracy(days: int = 30) -> float:
    """
    Compute overall pick accuracy over the trailing N evaluated days.

    Returns accuracy as a float between 0.0 and 1.0.
    """
    evaluated = get_evaluated_days(max_days=days)
    if not evaluated:
        return 0.0

    total_correct = 0
    total_picks = 0

    for day in evaluated:
        eod = day.get("eod_results", {})
        if not eod or eod.get("error"):
            continue
        for r in eod.get("options", []) + eod.get("stocks", []):
            if "correct" in r:
                total_picks += 1
                if r["correct"]:
                    total_correct += 1

    return total_correct / total_picks if total_picks > 0 else 0.0
