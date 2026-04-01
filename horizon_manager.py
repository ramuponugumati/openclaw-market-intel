"""
Trading Horizon Progression Manager

Manages the day_trade → swing_trade → long_term state machine.
Transitions are driven by sustained accuracy thresholds over
consecutive evaluated days.

Requirements: 18.1, 18.2, 18.3, 18.4, 18.5
"""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import shared_memory_io

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mode definitions
# ---------------------------------------------------------------------------

MODES = {
    "day_trade": {
        "label": "Day Trade",
        "expiry_range": (1, 7),       # 1-7 day expiry
        "hold_days": 0,               # close all EOD
        "description": "1-7 day expiry, close all EOD",
    },
    "swing_trade": {
        "label": "Swing Trade",
        "expiry_range": (7, 30),      # 7-30 day expiry
        "hold_days": (2, 7),          # 2-7 day holds
        "description": "7-30 day expiry, 2-7 day holds",
    },
    "long_term": {
        "label": "Long Term",
        "expiry_range": (30, 365),    # up to 1 year
        "hold_days": (7, 365),        # positions up to 1 year
        "description": "Positions up to 1 year",
    },
}

# Transition thresholds
SWING_TRADE_ACCURACY = 0.65       # >65% accuracy
SWING_TRADE_DAYS = 30             # for 30 consecutive evaluated days
LONG_TERM_ACCURACY = 0.75         # >75% accuracy
LONG_TERM_DAYS = 90              # for 90 consecutive evaluated days
REVERT_CONSECUTIVE_DAYS = 10     # 10 consecutive days below threshold → revert

# Mode ordering for progression / reversion
MODE_ORDER = ["day_trade", "swing_trade", "long_term"]


def get_current_mode() -> str:
    """Return the current trading horizon mode."""
    state = shared_memory_io.load_horizon_state()
    return state.get("current_mode", "day_trade")


def get_mode_config(mode: str | None = None) -> dict:
    """Return the configuration for the given (or current) mode."""
    if mode is None:
        mode = get_current_mode()
    return MODES.get(mode, MODES["day_trade"])


def check_transition(daily_accuracy: float) -> dict:
    """
    Check whether a horizon transition should occur based on today's accuracy.

    Updates the horizon state with the new accuracy data point and evaluates
    whether the system should upgrade or revert modes.

    Args:
        daily_accuracy: Today's overall pick accuracy (0.0 to 1.0).

    Returns:
        Dict with keys: current_mode, previous_mode, transition (str or None),
        consecutive_days, notification (str or None for Telegram).
    """
    state = shared_memory_io.load_horizon_state()
    current_mode = state.get("current_mode", "day_trade")
    accuracy_history = state.get("accuracy_history", [])
    transitions = state.get("mode_transitions", [])

    today_str = str(date.today())

    # Append today's accuracy
    accuracy_history.append({
        "date": today_str,
        "accuracy": round(daily_accuracy, 4),
    })

    # Keep only trailing 90 days of accuracy history (enough for long_term check)
    accuracy_history = accuracy_history[-90:]

    result: dict = {
        "current_mode": current_mode,
        "previous_mode": current_mode,
        "transition": None,
        "consecutive_days": 0,
        "notification": None,
    }

    new_mode = current_mode

    # --- Check for UPGRADE ---
    if current_mode == "day_trade":
        new_mode = _check_upgrade(
            accuracy_history, current_mode,
            SWING_TRADE_ACCURACY, SWING_TRADE_DAYS, "swing_trade",
        )
    elif current_mode == "swing_trade":
        new_mode = _check_upgrade(
            accuracy_history, current_mode,
            LONG_TERM_ACCURACY, LONG_TERM_DAYS, "long_term",
        )

    # --- Check for REVERT (only if no upgrade happened) ---
    if new_mode == current_mode and current_mode != "day_trade":
        new_mode = _check_revert(accuracy_history, current_mode)

    # Count consecutive days at/above threshold for current mode
    result["consecutive_days"] = _count_consecutive_above(
        accuracy_history, _threshold_for_mode(current_mode)
    )

    # Apply transition if mode changed
    if new_mode != current_mode:
        result["transition"] = f"{current_mode} → {new_mode}"
        result["current_mode"] = new_mode
        result["notification"] = _build_notification(current_mode, new_mode, daily_accuracy)

        transitions.append({
            "from": current_mode,
            "to": new_mode,
            "date": today_str,
            "reason": (
                f"accuracy {daily_accuracy:.1%} triggered transition"
            ),
        })

        logger.info(
            "Horizon transition: %s → %s (accuracy: %.1f%%)",
            current_mode, new_mode, daily_accuracy * 100,
        )

    # Persist updated state
    state["current_mode"] = result["current_mode"]
    state["accuracy_history"] = accuracy_history
    state["mode_transitions"] = transitions
    state["consecutive_days_at_threshold"] = result["consecutive_days"]
    shared_memory_io.save_horizon_state(state)

    return result


def _check_upgrade(
    history: list[dict],
    current_mode: str,
    threshold: float,
    required_days: int,
    target_mode: str,
) -> str:
    """Check if accuracy exceeds threshold for required consecutive days."""
    consecutive = _count_consecutive_above(history, threshold)
    if consecutive >= required_days:
        return target_mode
    return current_mode


def _check_revert(history: list[dict], current_mode: str) -> str:
    """Check if accuracy has been below threshold for 10 consecutive days."""
    threshold = _threshold_for_mode(current_mode)
    consecutive_below = _count_consecutive_below(history, threshold)

    if consecutive_below >= REVERT_CONSECUTIVE_DAYS:
        # Revert to previous lower-risk mode
        idx = MODE_ORDER.index(current_mode)
        if idx > 0:
            return MODE_ORDER[idx - 1]
    return current_mode


def _threshold_for_mode(mode: str) -> float:
    """Return the accuracy threshold required to maintain a mode."""
    if mode == "swing_trade":
        return SWING_TRADE_ACCURACY
    if mode == "long_term":
        return LONG_TERM_ACCURACY
    return 0.0  # day_trade has no threshold


def _count_consecutive_above(history: list[dict], threshold: float) -> int:
    """Count consecutive days from the end of history where accuracy > threshold."""
    count = 0
    for entry in reversed(history):
        if entry.get("accuracy", 0) > threshold:
            count += 1
        else:
            break
    return count


def _count_consecutive_below(history: list[dict], threshold: float) -> int:
    """Count consecutive days from the end of history where accuracy < threshold."""
    count = 0
    for entry in reversed(history):
        if entry.get("accuracy", 0) < threshold:
            count += 1
        else:
            break
    return count


def _build_notification(old_mode: str, new_mode: str, accuracy: float) -> str:
    """Build a Telegram notification message for a mode transition."""
    old_label = MODES.get(old_mode, {}).get("label", old_mode)
    new_label = MODES.get(new_mode, {}).get("label", new_mode)
    new_desc = MODES.get(new_mode, {}).get("description", "")

    # Determine if upgrade or revert
    old_idx = MODE_ORDER.index(old_mode) if old_mode in MODE_ORDER else 0
    new_idx = MODE_ORDER.index(new_mode) if new_mode in MODE_ORDER else 0

    if new_idx > old_idx:
        emoji = "🎉"
        action = "UPGRADED"
    else:
        emoji = "⚠️"
        action = "REVERTED"

    return (
        f"{emoji} *Trading Mode {action}*\n\n"
        f"From: {old_label}\n"
        f"To: {new_label}\n"
        f"Accuracy: {accuracy:.1%}\n"
        f"Mode: {new_desc}"
    )
