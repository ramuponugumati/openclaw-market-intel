"""
Prediction Tracker — saves daily predictions and compares against actual results.

Stores predictions on EFS so the next day's analysis can reference
what we got right/wrong and adjust accordingly.
"""

from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_predictions_dir() -> Path:
    base = os.environ.get("SHARED_MEMORY_PATH", "shared_memory")
    d = Path(base) / "predictions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_predictions(stock_picks: list[dict], options_picks: list[dict], movers: list[dict] | None = None) -> str:
    """Save today's predictions to EFS for next-day comparison."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    data = {
        "date": today,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stock_picks": [
            {
                "ticker": p.get("ticker"),
                "action": p.get("action", p.get("direction")),
                "score": p.get("composite_score"),
                "confidence": p.get("confidence"),
            }
            for p in (stock_picks or [])
        ],
        "options_picks": [
            {
                "ticker": p.get("ticker"),
                "direction": p.get("direction"),
                "score": p.get("composite_score"),
            }
            for p in (options_picks or [])
        ],
        "movers_at_time": [
            {"ticker": m.get("ticker"), "change_pct": m.get("change_pct")}
            for m in (movers or [])[:20]
        ],
    }
    filepath = _get_predictions_dir() / f"{today}.json"
    filepath.write_text(json.dumps(data, indent=2))
    logger.info("Saved predictions for %s (%d stocks, %d options)", today, len(data["stock_picks"]), len(data["options_picks"]))
    return str(filepath)


def load_yesterday_predictions() -> dict | None:
    """Load yesterday's predictions from EFS."""
    from datetime import timedelta
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    filepath = _get_predictions_dir() / f"{yesterday}.json"
    if not filepath.exists():
        # Try 2 days ago (weekend)
        two_days = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")
        filepath = _get_predictions_dir() / f"{two_days}.json"
    if not filepath.exists():
        three_days = (datetime.now(timezone.utc) - timedelta(days=3)).strftime("%Y-%m-%d")
        filepath = _get_predictions_dir() / f"{three_days}.json"
    if not filepath.exists():
        return None
    try:
        return json.loads(filepath.read_text())
    except Exception as exc:
        logger.warning("Failed to load yesterday's predictions: %s", exc)
        return None


def evaluate_predictions(predictions: dict, actual_movers: list[dict]) -> dict:
    """Compare yesterday's predictions against actual market movers.

    Returns a summary dict with hits, misses, and accuracy.
    """
    predicted_buys = {p["ticker"] for p in predictions.get("stock_picks", []) if p.get("action") in ("BUY",)}
    predicted_sells = {p["ticker"] for p in predictions.get("stock_picks", []) if p.get("action") in ("SELL/SHORT",)}
    actual_up = {m["ticker"] for m in actual_movers if m.get("change_pct", 0) > 2}
    actual_down = {m["ticker"] for m in actual_movers if m.get("change_pct", 0) < -2}

    correct_buys = predicted_buys & actual_up
    correct_sells = predicted_sells & actual_down
    wrong_buys = predicted_buys & actual_down
    wrong_sells = predicted_sells & actual_up
    missed_movers = (actual_up | actual_down) - predicted_buys - predicted_sells

    total_predictions = len(predicted_buys) + len(predicted_sells)
    correct = len(correct_buys) + len(correct_sells)
    accuracy = (correct / total_predictions * 100) if total_predictions > 0 else 0

    result = {
        "prediction_date": predictions.get("date", "unknown"),
        "correct_buys": sorted(correct_buys),
        "correct_sells": sorted(correct_sells),
        "wrong_buys": sorted(wrong_buys),
        "wrong_sells": sorted(wrong_sells),
        "missed_movers": sorted(list(missed_movers)[:10]),
        "accuracy_pct": round(accuracy, 1),
        "total_predictions": total_predictions,
        "total_correct": correct,
    }

    # Save evaluation
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    eval_path = _get_predictions_dir() / f"eval_{today}.json"
    eval_path.write_text(json.dumps(result, indent=2))
    logger.info("Prediction evaluation: %d/%d correct (%.1f%%)", correct, total_predictions, accuracy)

    return result
