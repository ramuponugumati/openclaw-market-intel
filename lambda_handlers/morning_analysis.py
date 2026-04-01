"""
Morning Analysis Lambda Handler

Entry point for the 5:30 AM PST EventBridge-triggered Lambda.
Launches all 7 sub-agents via the orchestrator fleet command, polls
shared memory for results, combines weighted scores, selects top
options and stock picks, enriches with options contracts, logs picks
via tracker, and sends the formatted morning message via Telegram.

Lambda timeout: 300 seconds (5 minutes).
Retry: once after 60 seconds on failure (Requirement 13.5).
Telegram queue: retry unsent messages every 60s for up to 10 attempts (Requirement 21.5).

Requirements: 13.1, 13.2, 13.4, 13.5, 21.5
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Ensure project root is on sys.path for imports
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import requests

from agents.orchestrator.skills.fleet_launcher import launch_fleet, poll_completion
from agents.orchestrator.skills.score_combiner import combine
from agents.orchestrator.skills.pick_selector import (
    select_options,
    select_stocks,
    enrich_options_picks,
)
from agents.orchestrator.skills.message_formatter import (
    format_morning_analysis,
    split_message,
)
from tracker import log_morning_picks
from horizon_manager import get_current_mode
from notifier import send_morning_alert

logger = logging.getLogger(__name__)

# Retry configuration (Requirement 13.5)
LAMBDA_RETRY_DELAY_S = 60
LAMBDA_MAX_RETRIES = 1

# Telegram message queue retry configuration (Requirement 21.5)
TELEGRAM_RETRY_INTERVAL_S = 60
TELEGRAM_MAX_RETRIES = 10


# ---------------------------------------------------------------------------
# Telegram helpers with queue + retry (Requirement 21.5)
# ---------------------------------------------------------------------------

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
                    logger.info(
                        "Queued Telegram message sent (attempt %d/%d)",
                        attempt, TELEGRAM_MAX_RETRIES,
                    )
                else:
                    still_failed.append(text)
            except Exception:
                still_failed.append(text)

        remaining = still_failed
        if remaining and attempt < TELEGRAM_MAX_RETRIES:
            logger.info(
                "Telegram queue: %d messages remaining, retrying in %ds "
                "(attempt %d/%d)",
                len(remaining), TELEGRAM_RETRY_INTERVAL_S,
                attempt, TELEGRAM_MAX_RETRIES,
            )
            time.sleep(TELEGRAM_RETRY_INTERVAL_S)

    # Re-queue anything that still failed
    _telegram_message_queue.extend(remaining)
    if remaining:
        logger.error(
            "Telegram queue: %d messages could not be delivered after %d attempts",
            len(remaining), TELEGRAM_MAX_RETRIES,
        )

    return sent_count


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

def run_morning_analysis() -> dict:
    """
    Execute the full morning analysis pipeline:

    1. Generate run_id from current UTC timestamp
    2. Launch all 7 sub-agents concurrently via fleet_launcher
    3. Poll shared memory for agent results (120s timeout)
    4. Combine weighted scores via score_combiner
    5. Select Top 5 options + Top 10 stocks via pick_selector
    6. Enrich options picks with specific contracts
    7. Log picks via tracker
    8. Format and send morning message via Telegram

    Returns:
        Dict summarizing the analysis results.
    """
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    logger.info("Starting morning analysis — run_id: %s", run_id)

    # Step 1: Launch all 7 sub-agents
    launch_statuses = launch_fleet(run_id, run_type="morning_analysis")
    logger.info("Fleet launch statuses: %s", launch_statuses)

    # Step 2: Poll for completion (120s timeout, 5s interval)
    poll_result = poll_completion(run_id, timeout_s=120, interval_s=5)
    agent_results = poll_result.get("results", {})
    timed_out = poll_result.get("timed_out", [])

    if timed_out:
        logger.warning("Agents timed out: %s", timed_out)

    # Step 3: Combine weighted scores
    combined = combine(agent_results)
    logger.info("Combined scores for %d tickers", len(combined))

    # Step 4: Select picks
    options_picks = select_options(combined)
    stock_picks = select_stocks(combined)

    # Step 5: Enrich options picks with specific contracts
    options_picks = enrich_options_picks(options_picks)

    # Step 6: Log picks via tracker
    horizon = get_current_mode()
    log_morning_picks(options_picks, stock_picks, run_id=run_id, horizon=horizon)

    # Step 7: Extract premarket data for message formatting
    premarket_data = _extract_premarket_data(agent_results)

    # Step 8: Format and send via Telegram
    message_data = {
        "options_picks": options_picks,
        "stock_picks": stock_picks,
        "premarket_data": premarket_data,
        "run_id": run_id,
        "combined": combined,
        "timed_out": timed_out,
    }

    message = format_morning_analysis(message_data)
    messages = split_message(message)

    for msg in messages:
        _send_telegram_message(msg)

    # SNS notifications (optional — skipped if not configured)
    send_morning_alert(options_picks, stock_picks)

    logger.info(
        "Morning analysis complete — %d options picks, %d stock picks, "
        "%d agents timed out",
        len(options_picks),
        len(stock_picks),
        len(timed_out),
    )

    return {
        "run_id": run_id,
        "options_picks": options_picks,
        "stock_picks": stock_picks,
        "combined": combined,
        "timed_out": timed_out,
        "horizon": horizon,
    }


def _extract_premarket_data(agent_results: dict) -> list[dict]:
    """Extract premarket data from the premarket agent's results."""
    premarket = agent_results.get("premarket", {})
    results = premarket.get("results", [])
    return results if isinstance(results, list) else []


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def handler(event: dict, context: object) -> dict:
    """
    AWS Lambda entry point for morning analysis.

    Implements retry-once-after-60s on failure (Requirement 13.5).
    Sends failure notification to Telegram on final failure.
    Flushes any queued Telegram messages before returning.
    """
    attempt = event.get("_retry_attempt", 0)

    try:
        result = run_morning_analysis()
        # Flush any queued messages that failed during the run
        _flush_telegram_queue()
        return {
            "statusCode": 200,
            "body": {
                "message": "Morning analysis completed successfully",
                "run_id": result.get("run_id", ""),
                "options_picks": len(result.get("options_picks", [])),
                "stock_picks": len(result.get("stock_picks", [])),
                "timed_out": result.get("timed_out", []),
                "horizon": result.get("horizon", "day_trade"),
            },
        }
    except Exception as exc:
        logger.exception(
            "Morning analysis Lambda failed (attempt %d): %s", attempt, exc
        )

        if attempt < LAMBDA_MAX_RETRIES:
            logger.info(
                "Retrying morning analysis in %ds (attempt %d/%d)",
                LAMBDA_RETRY_DELAY_S, attempt + 1, LAMBDA_MAX_RETRIES,
            )
            time.sleep(LAMBDA_RETRY_DELAY_S)
            event["_retry_attempt"] = attempt + 1
            return handler(event, context)

        # Final failure — notify via Telegram
        _send_telegram_message(
            f"❌ *Morning Analysis Failed*\n\n"
            f"Error: {exc}\n"
            f"Attempts: {attempt + 1}"
        )
        _flush_telegram_queue()

        return {
            "statusCode": 500,
            "body": {"error": str(exc), "attempts": attempt + 1},
        }
