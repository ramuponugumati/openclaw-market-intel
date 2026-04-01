"""
EOD Recap Lambda Handler

Entry point for the 1:15 PM PST EventBridge-triggered Lambda.
Evaluates morning picks, computes broker P&L via Alpaca, triggers
weight adjustment, checks horizon transitions, and sends the
EOD recap message via Telegram.

Retry: once after 60 seconds on failure (Requirement 13.5).
Telegram queue: retry unsent messages every 60s for up to 10 attempts (Requirement 21.5).

Requirements: 13.3, 13.5, 19.4, 21.5
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path for imports
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import requests

from tracker import evaluate_end_of_day
from weight_adjuster import update_weights, get_overall_accuracy
from horizon_manager import check_transition
from broker.alpaca_client import AlpacaClient
from shared_memory_io import cleanup_shared_memory
from agents.orchestrator.skills.message_formatter import (
    format_eod_recap,
    split_message,
)
from notifier import send_eod_alert

logger = logging.getLogger(__name__)

# Retry configuration (Requirement 13.5)
LAMBDA_RETRY_DELAY_S = 60
LAMBDA_MAX_RETRIES = 1

# Telegram message queue retry configuration (Requirement 21.5)
TELEGRAM_RETRY_INTERVAL_S = 60
TELEGRAM_MAX_RETRIES = 10

_telegram_message_queue: list[str] = []


def _send_telegram_message(text: str) -> bool:
    """Send a message via Telegram Bot API. Queues on failure for retry."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        logger.warning("Telegram credentials not configured; skipping send.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        if resp.ok:
            return True
        logger.error("Telegram send failed: %s %s", resp.status_code, resp.text)
        _telegram_message_queue.append(text)
        return False
    except Exception as exc:
        logger.error("Telegram send error: %s", exc)
        _telegram_message_queue.append(text)
        return False


def _flush_telegram_queue() -> int:
    """
    Retry sending queued Telegram messages.

    Retries every 60 seconds for up to 10 attempts per message.
    Returns the number of messages that were successfully sent.
    """
    if not _telegram_message_queue:
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return 0

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    sent_count = 0
    remaining: list[str] = list(_telegram_message_queue)
    _telegram_message_queue.clear()

    for attempt in range(1, TELEGRAM_MAX_RETRIES + 1):
        if not remaining:
            break

        still_failed: list[str] = []
        for text in remaining:
            try:
                resp = requests.post(
                    url,
                    json={
                        "chat_id": chat_id,
                        "text": text,
                        "parse_mode": "Markdown",
                    },
                    timeout=10,
                )
                if resp.ok:
                    sent_count += 1
                else:
                    still_failed.append(text)
            except Exception:
                still_failed.append(text)

        remaining = still_failed
        if remaining and attempt < TELEGRAM_MAX_RETRIES:
            time.sleep(TELEGRAM_RETRY_INTERVAL_S)

    _telegram_message_queue.extend(remaining)
    if remaining:
        logger.error(
            "Telegram queue: %d messages could not be delivered after %d attempts",
            len(remaining), TELEGRAM_MAX_RETRIES,
        )

    return sent_count


def _compute_accuracy_from_results(eod_results: dict) -> dict:
    """Compute options, stock, and overall accuracy from EOD results."""
    options = eod_results.get("options", [])
    stocks = eod_results.get("stocks", [])

    options_correct = sum(1 for r in options if r.get("correct"))
    options_total = len(options)
    stocks_correct = sum(1 for r in stocks if r.get("correct"))
    stocks_total = len(stocks)

    total_correct = options_correct + stocks_correct
    total_picks = options_total + stocks_total

    return {
        "options_accuracy": (
            round(options_correct / options_total * 100, 1)
            if options_total > 0 else 0.0
        ),
        "stock_accuracy": (
            round(stocks_correct / stocks_total * 100, 1)
            if stocks_total > 0 else 0.0
        ),
        "overall_accuracy": (
            round(total_correct / total_picks * 100, 1)
            if total_picks > 0 else 0.0
        ),
        "overall_accuracy_ratio": (
            total_correct / total_picks if total_picks > 0 else 0.0
        ),
    }


def run_eod_recap() -> dict:
    """
    Execute the full EOD recap pipeline:

    1. Evaluate morning picks against actual EOD prices
    2. Compute broker P&L via Alpaca
    3. Trigger weight adjustment
    4. Check horizon transitions
    5. Format and send EOD recap via Telegram

    Returns:
        Dict summarizing the recap results.
    """
    logger.info("Starting EOD recap...")

    # Step 1: Evaluate morning picks
    eod_results = evaluate_end_of_day()
    if eod_results.get("error"):
        logger.warning("EOD evaluation issue: %s", eod_results["error"])

    # Step 2: Compute broker P&L via Alpaca
    broker_pnl = {}
    try:
        client = AlpacaClient()
        account = client.get_account()
        if isinstance(account, dict) and not account.get("error"):
            broker_pnl = {
                "daily_pnl": account.get("daily_pnl", 0),
                "equity": account.get("equity", 0),
                "cash": account.get("cash", 0),
                "buying_power": account.get("buying_power", 0),
            }
        else:
            broker_pnl = {"daily_pnl": "N/A", "equity": "N/A"}
    except Exception as exc:
        logger.error("Broker P&L error: %s", exc)
        broker_pnl = {"daily_pnl": "N/A", "equity": "N/A"}

    # Step 3: Trigger weight adjustment
    weight_result = update_weights()

    # Step 4: Compute accuracy and check horizon transitions
    accuracy = _compute_accuracy_from_results(eod_results)
    overall_ratio = accuracy.get("overall_accuracy_ratio", 0.0)
    horizon_result = check_transition(overall_ratio)

    # Step 5: Format and send EOD recap via Telegram
    recap_data = {
        "broker_pnl": broker_pnl,
        "trade_results": [],  # populated from broker positions if available
        "options_accuracy": accuracy["options_accuracy"],
        "stock_accuracy": accuracy["stock_accuracy"],
        "overall_accuracy": accuracy["overall_accuracy"],
        "weight_update": weight_result,
        "horizon_status": {
            "current_mode": horizon_result.get("current_mode", "day_trade"),
            "transition": horizon_result.get("transition"),
        },
    }

    message = format_eod_recap(recap_data)
    messages = split_message(message)

    for msg in messages:
        _send_telegram_message(msg)

    # SNS notifications (optional — skipped if not configured)
    send_eod_alert(recap_data)

    # Send horizon transition notification if applicable
    notification = horizon_result.get("notification")
    if notification:
        _send_telegram_message(notification)

    # Step 6: Cleanup stale shared memory files (Req 2.6, 16.5)
    cleanup_result = cleanup_shared_memory()

    logger.info(
        "EOD recap complete — accuracy: %.1f%%, weights_updated: %s, mode: %s, "
        "cleanup: %d runs deleted, %d picks pruned",
        accuracy["overall_accuracy"],
        weight_result.get("weights_updated", False),
        horizon_result.get("current_mode", "day_trade"),
        cleanup_result.get("runs_deleted", 0),
        cleanup_result.get("picks_pruned", 0),
    )

    return {
        "eod_results": eod_results,
        "broker_pnl": broker_pnl,
        "accuracy": accuracy,
        "weight_update": weight_result,
        "horizon": horizon_result,
        "cleanup": cleanup_result,
    }


def handler(event: dict, context: object) -> dict:
    """
    AWS Lambda entry point for EOD recap.

    Implements retry-once-after-60s on failure (Requirement 13.5).
    Sends failure notification to Telegram on final failure.
    Flushes any queued Telegram messages before returning.
    """
    attempt = event.get("_retry_attempt", 0)

    try:
        result = run_eod_recap()
        _flush_telegram_queue()
        return {
            "statusCode": 200,
            "body": {
                "message": "EOD recap completed successfully",
                "accuracy": result.get("accuracy", {}),
                "mode": result.get("horizon", {}).get("current_mode", "day_trade"),
            },
        }
    except Exception as exc:
        logger.exception(
            "EOD recap Lambda failed (attempt %d): %s", attempt, exc
        )

        if attempt < LAMBDA_MAX_RETRIES:
            logger.info(
                "Retrying EOD recap in %ds (attempt %d/%d)",
                LAMBDA_RETRY_DELAY_S, attempt + 1, LAMBDA_MAX_RETRIES,
            )
            time.sleep(LAMBDA_RETRY_DELAY_S)
            event["_retry_attempt"] = attempt + 1
            return handler(event, context)

        # Final failure — notify via Telegram
        _send_telegram_message(
            f"❌ *EOD Recap Failed*\n\n"
            f"Error: {exc}\n"
            f"Attempts: {attempt + 1}"
        )
        _flush_telegram_queue()

        return {
            "statusCode": 500,
            "body": {"error": str(exc), "attempts": attempt + 1},
        }
