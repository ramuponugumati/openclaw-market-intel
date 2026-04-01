"""
SNS Notification Module

Sends SMS and email alerts via AWS SNS for morning analysis and EOD recaps.
Gracefully degrades — if SNS is not configured or boto3 is unavailable,
the pipeline continues without notifications.

Environment variables:
    SNS_PHONE_NUMBER  — E.164 phone number for SMS (e.g. +1XXXXXXXXXX)
    SNS_TOPIC_ARN     — SNS topic ARN for email notifications

All SNS calls use boto3 default session with region us-west-1.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

SMS_MAX_LENGTH = 160

# ---------------------------------------------------------------------------
# boto3 / SNS client — lazy init, graceful if unavailable
# ---------------------------------------------------------------------------

_sns_client = None
_boto3_available = True


def _get_sns_client():
    """Return a cached SNS client, or None if boto3 is unavailable."""
    global _sns_client, _boto3_available
    if not _boto3_available:
        return None
    if _sns_client is not None:
        return _sns_client
    try:
        import boto3
        _sns_client = boto3.Session(region_name="us-west-1").client("sns")
        return _sns_client
    except Exception as exc:
        logger.warning("boto3/SNS unavailable: %s", exc)
        _boto3_available = False
        return None


def _strip_markdown(text: str) -> str:
    """Remove Markdown formatting for plain-text email."""
    text = re.sub(r"\*+", "", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text


# ---------------------------------------------------------------------------
# Core send functions
# ---------------------------------------------------------------------------

def send_sms(message: str) -> bool:
    """
    Send a short SMS via SNS publish() with PhoneNumber parameter.

    Truncates to 160 characters. Returns False if SNS is unavailable
    or the phone number is not configured.
    """
    phone = os.environ.get("SNS_PHONE_NUMBER", "").strip()
    if not phone:
        logger.debug("SNS_PHONE_NUMBER not set; skipping SMS.")
        return False

    client = _get_sns_client()
    if client is None:
        return False

    truncated = message[:SMS_MAX_LENGTH]
    try:
        client.publish(PhoneNumber=phone, Message=truncated)
        logger.info("SMS sent (%d chars).", len(truncated))
        return True
    except Exception as exc:
        logger.error("SNS SMS publish failed: %s", exc)
        return False


def send_email(subject: str, body: str) -> bool:
    """
    Send a full report via SNS publish() to a topic ARN.

    Returns False if SNS is unavailable or the topic ARN is not configured.
    """
    topic_arn = os.environ.get("SNS_TOPIC_ARN", "").strip()
    if not topic_arn:
        logger.debug("SNS_TOPIC_ARN not set; skipping email.")
        return False

    client = _get_sns_client()
    if client is None:
        return False

    try:
        client.publish(TopicArn=topic_arn, Subject=subject[:100], Message=body)
        logger.info("Email published to SNS topic.")
        return True
    except Exception as exc:
        logger.error("SNS email publish failed: %s", exc)
        return False



# ---------------------------------------------------------------------------
# Morning alert
# ---------------------------------------------------------------------------

def send_morning_alert(options_picks: list, stock_picks: list) -> None:
    """
    Format and send both SMS + email for the morning analysis.

    SMS: top 3 picks summary (≤160 chars).
    Email: full formatted morning analysis (plain text, markdown stripped).

    Never raises — logs errors and returns silently.
    """
    try:
        # --- SMS: top 3 summary ---
        top3 = (options_picks or [])[:3]
        if not top3:
            top3 = (stock_picks or [])[:3]

        picks_str = ", ".join(
            f"{p.get('ticker', '?')} {p.get('composite_score', 0):.1f} {p.get('direction', p.get('action', 'HOLD'))}"
            for p in top3
        )
        sms = f"\U0001f980 OpenClaw: Top 3 \u2192 {picks_str}. Full report in email."
        send_sms(sms)

        # --- Email: full morning analysis ---
        try:
            from agents.orchestrator.skills.message_formatter import format_morning_analysis

            message_data = {
                "options_picks": options_picks or [],
                "stock_picks": stock_picks or [],
                "premarket_data": [],
                "run_id": "",
                "combined": [],
                "timed_out": [],
            }
            full_msg = format_morning_analysis(message_data)
            plain = _strip_markdown(full_msg)
            send_email("OpenClaw Morning Analysis", plain)
        except Exception as exc:
            logger.error("Morning email formatting failed: %s", exc)

    except Exception as exc:
        logger.error("send_morning_alert failed: %s", exc)


# ---------------------------------------------------------------------------
# EOD alert
# ---------------------------------------------------------------------------

def send_eod_alert(recap_data: dict) -> None:
    """
    Format and send both SMS + email for the EOD recap.

    SMS: accuracy + P&L summary (≤160 chars).
    Email: full formatted EOD recap (plain text, markdown stripped).

    Never raises — logs errors and returns silently.
    """
    try:
        # --- SMS: accuracy + P&L summary ---
        accuracy = recap_data.get("overall_accuracy", recap_data.get("accuracy", "N/A"))
        if isinstance(accuracy, dict):
            accuracy = accuracy.get("overall_accuracy", "N/A")

        broker = recap_data.get("broker_pnl", {})
        pnl = broker.get("daily_pnl", "N/A")
        pnl_str = f"${pnl}" if pnl != "N/A" else "N/A"
        if isinstance(pnl, (int, float)):
            pnl_str = f"+${pnl}" if pnl >= 0 else f"-${abs(pnl)}"

        acc_str = f"{accuracy}%" if isinstance(accuracy, (int, float)) else str(accuracy)
        sms = f"\U0001f980 EOD: accuracy {acc_str}, P&L {pnl_str}. Details in email."
        send_sms(sms)

        # --- Email: full EOD recap ---
        try:
            from agents.orchestrator.skills.message_formatter import format_eod_recap

            full_msg = format_eod_recap(recap_data)
            plain = _strip_markdown(full_msg)
            send_email("OpenClaw EOD Recap", plain)
        except Exception as exc:
            logger.error("EOD email formatting failed: %s", exc)

    except Exception as exc:
        logger.error("send_eod_alert failed: %s", exc)
