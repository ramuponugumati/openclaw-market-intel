"""
Notification Module — SES (HTML email) + SNS (SMS + fallback email)

Sends HTML-formatted emails via AWS SES for morning analysis and EOD recaps.
Falls back to SNS topic publish (plain text) if SES is not configured.
SMS alerts continue via SNS as before.

Environment variables:
    SNS_PHONE_NUMBER  — E.164 phone number for SMS (e.g. +1XXXXXXXXXX)
    SNS_TOPIC_ARN     — SNS topic ARN for fallback email notifications
    SES_FROM_EMAIL    — Verified SES sender address (required for SES)
    SES_TO_EMAIL      — Recipient email address (required for SES)

All AWS calls use boto3 default session with region us-west-1.
"""

from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

SMS_MAX_LENGTH = 160
SES_REGION = "us-east-1"

# ---------------------------------------------------------------------------
# boto3 / client lazy init — graceful if unavailable
# ---------------------------------------------------------------------------

_sns_client = None
_ses_client = None
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


def _get_ses_client():
    """Return a cached SES client, or None if boto3 is unavailable."""
    global _ses_client, _boto3_available
    if not _boto3_available:
        return None
    if _ses_client is not None:
        return _ses_client
    try:
        import boto3
        _ses_client = boto3.Session(region_name=SES_REGION).client("ses")
        return _ses_client
    except Exception as exc:
        logger.warning("boto3/SES unavailable: %s", exc)
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
    Send a full report via SNS publish() to a topic ARN (plain-text fallback).

    Returns False if SNS is unavailable or the topic ARN is not configured.
    """
    topic_arn = os.environ.get("SNS_TOPIC_ARN", "").strip()
    if not topic_arn:
        logger.debug("SNS_TOPIC_ARN not set; skipping SNS email.")
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


def send_ses_email(subject: str, html_body: str, plain_body: str = "") -> bool:
    """
    Send an HTML email via AWS SES.

    Uses SES_FROM_EMAIL and SES_TO_EMAIL environment variables.
    Returns False if SES is not configured or the send fails.
    Falls back gracefully — never crashes the pipeline.
    """
    from_email = os.environ.get("SES_FROM_EMAIL", "").strip()
    to_email = os.environ.get("SES_TO_EMAIL", "").strip()

    if not from_email or not to_email:
        logger.debug("SES_FROM_EMAIL or SES_TO_EMAIL not set; skipping SES.")
        return False

    client = _get_ses_client()
    if client is None:
        return False

    if not plain_body:
        plain_body = _strip_markdown(subject)

    try:
        client.send_email(
            Source=from_email,
            Destination={"ToAddresses": [to_email]},
            Message={
                "Subject": {"Data": subject[:256], "Charset": "UTF-8"},
                "Body": {
                    "Html": {"Data": html_body, "Charset": "UTF-8"},
                    "Text": {"Data": plain_body, "Charset": "UTF-8"},
                },
            },
        )
        logger.info("HTML email sent via SES to %s.", to_email)
        return True
    except Exception as exc:
        logger.error("SES send_email failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Morning alert
# ---------------------------------------------------------------------------

def send_morning_alert(options_picks: list, stock_picks: list, movers: list | None = None, prediction_eval: dict | None = None) -> None:
    """
    Format and send SMS + HTML email for the morning analysis.

    SMS: top 3 picks summary (≤160 chars) via SNS.
    Email: HTML-formatted morning picks via SES, with SNS plain-text fallback.

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

        # --- Email: HTML via SES (with SNS fallback) ---
        try:
            from email_formatter import format_morning_email_html

            html = format_morning_email_html(
                options_picks or [],
                stock_picks or [],
                movers=movers,
                prediction_eval=prediction_eval,
            )
            ses_sent = send_ses_email("OpenClaw Morning Picks", html)

            if not ses_sent:
                # Fallback to SNS topic (plain text)
                logger.info("SES not available; falling back to SNS topic email.")
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
                except Exception as fallback_exc:
                    logger.error("SNS fallback email also failed: %s", fallback_exc)

        except Exception as exc:
            logger.error("Morning email formatting failed: %s", exc)

    except Exception as exc:
        logger.error("send_morning_alert failed: %s", exc)


# ---------------------------------------------------------------------------
# EOD alert
# ---------------------------------------------------------------------------

def send_eod_alert(recap_data: dict) -> None:
    """
    Format and send SMS + HTML email for the EOD recap.

    SMS: accuracy + P&L summary (≤160 chars) via SNS.
    Email: HTML-formatted EOD recap via SES, with SNS plain-text fallback.

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

        # --- Email: HTML via SES (with SNS fallback) ---
        try:
            from email_formatter import format_eod_email_html

            html = format_eod_email_html(recap_data)
            ses_sent = send_ses_email("OpenClaw EOD Recap", html)

            if not ses_sent:
                # Fallback to SNS topic (plain text)
                logger.info("SES not available; falling back to SNS topic email.")
                try:
                    from agents.orchestrator.skills.message_formatter import format_eod_recap

                    full_msg = format_eod_recap(recap_data)
                    plain = _strip_markdown(full_msg)
                    send_email("OpenClaw EOD Recap", plain)
                except Exception as fallback_exc:
                    logger.error("SNS fallback email also failed: %s", fallback_exc)

        except Exception as exc:
            logger.error("EOD email formatting failed: %s", exc)

    except Exception as exc:
        logger.error("send_eod_alert failed: %s", exc)
