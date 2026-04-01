"""
Unit tests for notifier.py — SNS notification module.

Tests SMS formatting, email formatting, graceful failure when boto3
is unavailable, and graceful failure when SNS publish fails.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import notifier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_options_picks(n: int = 5) -> list[dict]:
    tickers = ["MRVL", "NFLX", "MSFT", "AAPL", "TSLA"]
    return [
        {
            "ticker": tickers[i % len(tickers)],
            "composite_score": 6.5 - i * 0.1,
            "direction": "BUY",
            "confidence": "HIGH",
        }
        for i in range(n)
    ]


def _sample_stock_picks(n: int = 10) -> list[dict]:
    tickers = ["GOOG", "AMZN", "META", "NVDA", "AMD", "INTC", "PYPL", "SQ", "SHOP", "COIN"]
    return [
        {
            "ticker": tickers[i % len(tickers)],
            "composite_score": 6.0 - i * 0.05,
            "action": "BUY",
            "confidence": "MEDIUM",
        }
        for i in range(n)
    ]


def _sample_recap_data() -> dict:
    return {
        "broker_pnl": {"daily_pnl": 150.0, "equity": 10150.0},
        "trade_results": [],
        "options_accuracy": 80.0,
        "stock_accuracy": 70.0,
        "overall_accuracy": 75.0,
        "weight_update": {"weights_updated": False, "days_evaluated": 3},
        "horizon_status": {"current_mode": "day_trade", "transition": None},
    }


# ---------------------------------------------------------------------------
# SMS formatting tests
# ---------------------------------------------------------------------------

class TestSmsFormatting:
    """SMS messages must be ≤160 chars and contain top 3 picks."""

    def test_sms_top3_picks_included(self):
        """send_morning_alert SMS should reference the top 3 tickers."""
        mock_client = MagicMock()
        picks = _sample_options_picks(5)

        with patch.dict(os.environ, {"SNS_PHONE_NUMBER": "+15551234567", "SNS_TOPIC_ARN": ""}):
            with patch.object(notifier, "_get_sns_client", return_value=mock_client):
                notifier.send_morning_alert(picks, [])

        # SMS was sent (first call to publish with PhoneNumber)
        sms_calls = [
            c for c in mock_client.publish.call_args_list
            if "PhoneNumber" in c.kwargs or (c.args and "PhoneNumber" not in str(c))
        ]
        # Check via keyword args
        assert mock_client.publish.called
        first_call = mock_client.publish.call_args_list[0]
        msg = first_call.kwargs.get("Message", first_call[1].get("Message", ""))
        assert len(msg) <= 160
        assert "MRVL" in msg
        assert "NFLX" in msg
        assert "MSFT" in msg

    def test_sms_respects_160_char_limit(self):
        """Even with long ticker names, SMS must be truncated to 160 chars."""
        mock_client = MagicMock()

        with patch.dict(os.environ, {"SNS_PHONE_NUMBER": "+15551234567"}):
            with patch.object(notifier, "_get_sns_client", return_value=mock_client):
                notifier.send_sms("A" * 200)

        call_msg = mock_client.publish.call_args.kwargs.get(
            "Message", mock_client.publish.call_args[1].get("Message", "")
        )
        assert len(call_msg) <= 160

    def test_sms_falls_back_to_stock_picks_when_no_options(self):
        """If no options picks, SMS should use stock picks."""
        mock_client = MagicMock()
        stocks = _sample_stock_picks(5)

        with patch.dict(os.environ, {"SNS_PHONE_NUMBER": "+15551234567", "SNS_TOPIC_ARN": ""}):
            with patch.object(notifier, "_get_sns_client", return_value=mock_client):
                notifier.send_morning_alert([], stocks)

        first_call = mock_client.publish.call_args_list[0]
        msg = first_call.kwargs.get("Message", first_call[1].get("Message", ""))
        assert "GOOG" in msg

    def test_eod_sms_contains_accuracy_and_pnl(self):
        """EOD SMS should contain accuracy % and P&L."""
        mock_client = MagicMock()
        recap = _sample_recap_data()

        with patch.dict(os.environ, {"SNS_PHONE_NUMBER": "+15551234567", "SNS_TOPIC_ARN": ""}):
            with patch.object(notifier, "_get_sns_client", return_value=mock_client):
                notifier.send_eod_alert(recap)

        first_call = mock_client.publish.call_args_list[0]
        msg = first_call.kwargs.get("Message", first_call[1].get("Message", ""))
        assert "75" in msg  # accuracy
        assert "150" in msg  # P&L


# ---------------------------------------------------------------------------
# Email formatting tests
# ---------------------------------------------------------------------------

class TestEmailFormatting:
    """Email subject and body should be properly formatted plain text."""

    def test_email_subject_for_morning(self):
        mock_client = MagicMock()
        picks = _sample_options_picks(3)

        with patch.dict(os.environ, {"SNS_TOPIC_ARN": "arn:aws:sns:us-west-1:123:test", "SNS_PHONE_NUMBER": ""}):
            with patch.object(notifier, "_get_sns_client", return_value=mock_client):
                notifier.send_morning_alert(picks, [])

        # Find the email call (TopicArn)
        email_calls = [
            c for c in mock_client.publish.call_args_list
            if "TopicArn" in (c.kwargs or {}) or (len(c.args) > 0 and "TopicArn" in str(c))
        ]
        assert len(email_calls) >= 1
        subject = email_calls[0].kwargs.get("Subject", "")
        assert "Morning" in subject

    def test_email_body_is_plain_text_no_markdown(self):
        """Email body should have markdown stripped."""
        mock_client = MagicMock()
        picks = _sample_options_picks(3)

        with patch.dict(os.environ, {"SNS_TOPIC_ARN": "arn:aws:sns:us-west-1:123:test", "SNS_PHONE_NUMBER": ""}):
            with patch.object(notifier, "_get_sns_client", return_value=mock_client):
                notifier.send_morning_alert(picks, [])

        email_calls = [
            c for c in mock_client.publish.call_args_list
            if "TopicArn" in (c.kwargs or {})
        ]
        if email_calls:
            body = email_calls[0].kwargs.get("Message", "")
            # No markdown bold markers should remain
            assert "**" not in body
            assert "*#" not in body

    def test_eod_email_subject(self):
        mock_client = MagicMock()
        recap = _sample_recap_data()

        with patch.dict(os.environ, {"SNS_TOPIC_ARN": "arn:aws:sns:us-west-1:123:test", "SNS_PHONE_NUMBER": ""}):
            with patch.object(notifier, "_get_sns_client", return_value=mock_client):
                notifier.send_eod_alert(recap)

        email_calls = [
            c for c in mock_client.publish.call_args_list
            if "TopicArn" in (c.kwargs or {})
        ]
        assert len(email_calls) >= 1
        subject = email_calls[0].kwargs.get("Subject", "")
        assert "EOD" in subject


# ---------------------------------------------------------------------------
# Graceful failure — boto3 not available
# ---------------------------------------------------------------------------

class TestBoto3Unavailable:
    """When boto3 is not importable, all functions should return False / do nothing."""

    def setup_method(self):
        # Reset module-level state
        notifier._sns_client = None
        notifier._boto3_available = True

    def test_send_sms_returns_false_when_boto3_missing(self):
        notifier._boto3_available = True
        notifier._sns_client = None

        with patch.dict(os.environ, {"SNS_PHONE_NUMBER": "+15551234567"}):
            with patch.object(notifier, "_get_sns_client", return_value=None):
                result = notifier.send_sms("test message")
        assert result is False

    def test_send_email_returns_false_when_boto3_missing(self):
        notifier._sns_client = None

        with patch.dict(os.environ, {"SNS_TOPIC_ARN": "arn:aws:sns:us-west-1:123:test"}):
            with patch.object(notifier, "_get_sns_client", return_value=None):
                result = notifier.send_email("Subject", "Body")
        assert result is False

    def test_morning_alert_does_not_crash_when_boto3_missing(self):
        """send_morning_alert should silently succeed even without boto3."""
        notifier._sns_client = None

        with patch.dict(os.environ, {"SNS_PHONE_NUMBER": "+15551234567"}):
            with patch.object(notifier, "_get_sns_client", return_value=None):
                # Should not raise
                notifier.send_morning_alert(_sample_options_picks(), _sample_stock_picks())

    def test_eod_alert_does_not_crash_when_boto3_missing(self):
        notifier._sns_client = None

        with patch.dict(os.environ, {"SNS_PHONE_NUMBER": "+15551234567"}):
            with patch.object(notifier, "_get_sns_client", return_value=None):
                notifier.send_eod_alert(_sample_recap_data())


# ---------------------------------------------------------------------------
# Graceful failure — SNS publish fails
# ---------------------------------------------------------------------------

class TestSnsPublishFailure:
    """When SNS publish raises, functions should return False, not crash."""

    def test_send_sms_returns_false_on_publish_error(self):
        mock_client = MagicMock()
        mock_client.publish.side_effect = Exception("SNS throttled")

        with patch.dict(os.environ, {"SNS_PHONE_NUMBER": "+15551234567"}):
            with patch.object(notifier, "_get_sns_client", return_value=mock_client):
                result = notifier.send_sms("test")
        assert result is False

    def test_send_email_returns_false_on_publish_error(self):
        mock_client = MagicMock()
        mock_client.publish.side_effect = Exception("Access denied")

        with patch.dict(os.environ, {"SNS_TOPIC_ARN": "arn:aws:sns:us-west-1:123:test"}):
            with patch.object(notifier, "_get_sns_client", return_value=mock_client):
                result = notifier.send_email("Subj", "Body")
        assert result is False

    def test_morning_alert_survives_publish_error(self):
        mock_client = MagicMock()
        mock_client.publish.side_effect = Exception("Network error")

        with patch.dict(os.environ, {"SNS_PHONE_NUMBER": "+15551234567", "SNS_TOPIC_ARN": "arn:aws:sns:us-west-1:123:test"}):
            with patch.object(notifier, "_get_sns_client", return_value=mock_client):
                # Should not raise
                notifier.send_morning_alert(_sample_options_picks(), _sample_stock_picks())

    def test_eod_alert_survives_publish_error(self):
        mock_client = MagicMock()
        mock_client.publish.side_effect = Exception("Network error")

        with patch.dict(os.environ, {"SNS_PHONE_NUMBER": "+15551234567", "SNS_TOPIC_ARN": "arn:aws:sns:us-west-1:123:test"}):
            with patch.object(notifier, "_get_sns_client", return_value=mock_client):
                notifier.send_eod_alert(_sample_recap_data())

    def test_send_sms_returns_false_when_phone_not_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SNS_PHONE_NUMBER", None)
            result = notifier.send_sms("test")
        assert result is False

    def test_send_email_returns_false_when_topic_not_set(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SNS_TOPIC_ARN", None)
            result = notifier.send_email("Subj", "Body")
        assert result is False
