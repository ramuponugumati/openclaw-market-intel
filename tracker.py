"""
Pick Tracker & History Logging

Logs every morning pick, evaluates end-of-day outcomes, and maintains
persistent pick history for the weight adjustment engine and horizon manager.

Adapted from market-intel/tracker.py for the OpenClaw multi-agent system.

Requirements: 16.1, 16.2, 16.5
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import yfinance as yf

_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import shared_memory_io

logger = logging.getLogger(__name__)

# Retain pick history for at least 365 days (Req 16.5)
HISTORY_RETENTION_DAYS = 365


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_picks_history() -> list[dict]:
    """Load the picks history JSON list from shared memory."""
    base = shared_memory_io._get_base_path()
    filepath = base / "picks" / "picks_history.json"
    if not filepath.exists():
        return []
    try:
        data = json.loads(filepath.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_picks_history(history: list[dict]) -> None:
    """Save the picks history JSON list to shared memory."""
    base = shared_memory_io._get_base_path()
    picks_dir = base / "picks"
    picks_dir.mkdir(parents=True, exist_ok=True)
    filepath = picks_dir / "picks_history.json"
    filepath.write_text(
        json.dumps(history, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _prune_old_entries(history: list[dict]) -> list[dict]:
    """Remove entries older than HISTORY_RETENTION_DAYS."""
    cutoff = str(
        date.today().toordinal() - HISTORY_RETENTION_DAYS
    )
    # Use string date comparison (YYYY-MM-DD sorts lexicographically)
    from datetime import timedelta
    cutoff_date = str(date.today() - timedelta(days=HISTORY_RETENTION_DAYS))
    return [e for e in history if e.get("date", "") >= cutoff_date]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def log_morning_picks(
    options_picks: list[dict],
    stock_picks: list[dict],
    run_id: str | None = None,
    horizon: str = "day_trade",
) -> dict:
    """
    Log morning picks to shared_memory/picks/picks_history.json.

    Each pick entry includes ticker, direction, composite_score, confidence,
    option contract details, and per-agent scores.

    Args:
        options_picks: List of options pick dicts from pick_selector.
        stock_picks: List of stock pick dicts from pick_selector.
        run_id: Optional run identifier.
        horizon: Current trading horizon mode.

    Returns:
        The logged entry dict.
    """
    history = _load_picks_history()

    today_str = str(date.today())
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entry: dict = {
        "date": today_str,
        "timestamp": now_iso,
        "run_id": run_id or today_str.replace("-", "") + "_053000",
        "horizon": horizon,
        "options_picks": [],
        "stock_picks": [],
        "eod_results": None,
    }

    for p in options_picks:
        entry["options_picks"].append({
            "ticker": p.get("ticker", ""),
            "direction": p.get("direction", "HOLD"),
            "composite_score": p.get("composite_score", 5.0),
            "confidence": p.get("confidence", "LOW"),
            "option": p.get("option_contract", p.get("option", {})),
            "agents": p.get("agent_scores", p.get("agents", {})),
        })

    for s in stock_picks:
        entry["stock_picks"].append({
            "ticker": s.get("ticker", ""),
            "direction": s.get("direction", "HOLD"),
            "trade_action": s.get("action", s.get("trade_action", "WATCH")),
            "composite_score": s.get("composite_score", 5.0),
            "confidence": s.get("confidence", "LOW"),
            "agents": s.get("agent_scores", s.get("agents", {})),
        })

    history.append(entry)

    # Prune entries older than 365 days
    history = _prune_old_entries(history)

    _save_picks_history(history)
    logger.info(
        "Logged %d options + %d stock picks for %s",
        len(entry["options_picks"]),
        len(entry["stock_picks"]),
        today_str,
    )
    return entry


def evaluate_end_of_day(target_date: str | None = None) -> dict:
    """
    Evaluate morning picks against actual EOD prices.

    Compares close vs open for each pick, computes correctness and
    estimated P&L, and appends results to the pick entry.

    Args:
        target_date: Date string (YYYY-MM-DD) to evaluate. Defaults to today.

    Returns:
        Dict with date, options results, stock results, and total_pnl.
    """
    history = _load_picks_history()
    eval_date = target_date or str(date.today())

    # Find the entry for the target date (most recent if multiple)
    today_entry = None
    for entry in reversed(history):
        if entry.get("date") == eval_date:
            today_entry = entry
            break

    if not today_entry:
        return {"error": f"No picks found for {eval_date}"}

    results: dict = {
        "date": eval_date,
        "options": [],
        "stocks": [],
        "total_pnl": 0.0,
    }

    # Evaluate options picks
    for pick in today_entry.get("options_picks", []):
        ticker = pick.get("ticker", "")
        direction = pick.get("direction", "HOLD")
        eval_result = _evaluate_single_pick(ticker, direction, is_option=True)
        if eval_result:
            results["options"].append(eval_result)
            results["total_pnl"] += eval_result.get("est_pnl", 0)

    # Evaluate stock picks
    for pick in today_entry.get("stock_picks", []):
        ticker = pick.get("ticker", "")
        action = pick.get("trade_action", pick.get("direction", "HOLD"))
        # Map trade_action to direction for evaluation
        direction = "CALL" if action in ("BUY",) else "PUT" if action in ("SELL/SHORT", "SELL") else "HOLD"
        eval_result = _evaluate_single_pick(ticker, direction, is_option=False)
        if eval_result:
            eval_result["action"] = action
            results["stocks"].append(eval_result)

    # Append EOD results to the history entry
    today_entry["eod_results"] = results

    _save_picks_history(history)
    logger.info(
        "EOD evaluation for %s: %d options, %d stocks, total P&L: $%.2f",
        eval_date,
        len(results["options"]),
        len(results["stocks"]),
        results["total_pnl"],
    )
    return results


def _evaluate_single_pick(
    ticker: str, direction: str, is_option: bool = False
) -> Optional[dict]:
    """Fetch EOD prices for a ticker and compute correctness + P&L."""
    if not ticker or direction == "HOLD":
        return None
    try:
        hist = yf.Ticker(ticker).history(period="1d")
        if hist.empty:
            logger.warning("No EOD data for %s", ticker)
            return None

        open_price = float(hist["Open"].iloc[-1])
        close_price = float(hist["Close"].iloc[-1])
        change_pct = ((close_price - open_price) / open_price * 100) if open_price else 0

        correct = (
            (direction == "CALL" and close_price > open_price)
            or (direction == "PUT" and close_price < open_price)
        )

        result: dict = {
            "ticker": ticker,
            "direction": direction,
            "open": round(open_price, 2),
            "close": round(close_price, 2),
            "change_pct": round(change_pct, 2),
            "correct": correct,
        }

        if is_option:
            # Estimated P&L: delta approximation (0.5) × 100 shares per contract
            multiplier = 1 if direction == "CALL" else -1
            est_pnl = (close_price - open_price) * 0.5 * 100 * multiplier
            result["est_pnl"] = round(est_pnl, 2)

        return result

    except Exception as exc:
        logger.warning("EOD eval error for %s: %s", ticker, exc)
        return None


def get_picks_for_date(target_date: str | None = None) -> Optional[dict]:
    """Retrieve the pick entry for a given date."""
    history = _load_picks_history()
    eval_date = target_date or str(date.today())
    for entry in reversed(history):
        if entry.get("date") == eval_date:
            return entry
    return None


def get_evaluated_days(max_days: int = 30) -> list[dict]:
    """Return the most recent evaluated entries (those with eod_results)."""
    history = _load_picks_history()
    evaluated = [e for e in history if e.get("eod_results")]
    return evaluated[-max_days:]
