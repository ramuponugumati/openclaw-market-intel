"""
Unit tests for email_formatter.py — HTML email generation.

Tests morning email and EOD recap email formatting, edge cases,
and graceful failure on bad input.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import email_formatter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sample_options(n: int = 3) -> list[dict]:
    tickers = ["MRVL", "NFLX", "MSFT", "AAPL", "TSLA"]
    dirs = ["CALL", "PUT", "CALL", "PUT", "CALL"]
    return [
        {
            "ticker": tickers[i % len(tickers)],
            "composite_score": 7.5 - i * 0.5,
            "direction": dirs[i % len(dirs)],
            "confidence": "HIGH" if i < 2 else "MEDIUM",
            "thesis": f"Thesis for {tickers[i % len(tickers)]}" if i < 2 else "",
        }
        for i in range(n)
    ]


def _sample_stocks(n: int = 5) -> list[dict]:
    tickers = ["GOOG", "AMZN", "META", "NVDA", "AMD"]
    actions = ["BUY", "SELL", "WATCH", "BUY", "SELL"]
    return [
        {
            "ticker": tickers[i % len(tickers)],
            "composite_score": 6.0 + i * 0.3,
            "action": actions[i % len(actions)],
            "confidence": "HIGH",
            "agent_scores": {"technical": {"score": 7.0}, "sentiment": {"score": 6.0}},
            "thesis": f"Stock thesis for {tickers[i % len(tickers)]}" if i == 0 else "",
        }
        for i in range(n)
    ]


def _sample_movers() -> list[dict]:
    return [
        {"ticker": "TSLA", "change_pct": 5.2},
        {"ticker": "AAPL", "change_pct": -2.1},
        {"ticker": "NVDA", "change_pct": 0.0},
    ]


def _sample_recap() -> dict:
    return {
        "broker_pnl": {"daily_pnl": 150.0, "equity": 10150.0},
        "trade_results": [],
        "options_accuracy": 80.0,
        "stock_accuracy": 70.0,
        "overall_accuracy": 75.0,
        "weight_update": {"weights_updated": True, "days_evaluated": 7},
        "horizon_status": {"current_mode": "day_trade", "transition": None},
    }


# ---------------------------------------------------------------------------
# Morning email tests
# ---------------------------------------------------------------------------

class TestMorningEmail:
    """format_morning_email_html produces valid HTML with all sections."""

    def test_returns_html_string(self):
        html = email_formatter.format_morning_email_html(
            _sample_options(), _sample_stocks()
        )
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")
        assert "</html>" in html

    def test_contains_header(self):
        html = email_formatter.format_morning_email_html(
            _sample_options(), _sample_stocks()
        )
        assert "OpenClaw Morning Picks" in html

    def test_contains_options_tickers(self):
        options = _sample_options(3)
        html = email_formatter.format_morning_email_html(options, [])
        for pick in options:
            assert pick["ticker"] in html

    def test_contains_stock_tickers(self):
        stocks = _sample_stocks(5)
        html = email_formatter.format_morning_email_html([], stocks)
        for pick in stocks:
            assert pick["ticker"] in html

    def test_call_direction_green(self):
        options = [{"ticker": "TEST", "direction": "CALL", "composite_score": 8.0, "confidence": "HIGH"}]
        html = email_formatter.format_morning_email_html(options, [])
        assert "#00c853" in html  # green color

    def test_put_direction_red(self):
        options = [{"ticker": "TEST", "direction": "PUT", "composite_score": 3.0, "confidence": "LOW"}]
        html = email_formatter.format_morning_email_html(options, [])
        assert "#ff1744" in html  # red color

    def test_score_badge_green_for_high(self):
        options = [{"ticker": "X", "direction": "CALL", "composite_score": 8.5, "confidence": "HIGH"}]
        html = email_formatter.format_morning_email_html(options, [])
        assert "8.5" in html
        assert "#00c853" in html

    def test_score_badge_yellow_for_mid(self):
        options = [{"ticker": "X", "direction": "HOLD", "composite_score": 6.0, "confidence": "MEDIUM"}]
        html = email_formatter.format_morning_email_html(options, [])
        assert "6.0" in html
        assert "#ffd600" in html

    def test_score_badge_red_for_low(self):
        options = [{"ticker": "X", "direction": "PUT", "composite_score": 3.0, "confidence": "LOW"}]
        html = email_formatter.format_morning_email_html(options, [])
        assert "3.0" in html

    def test_thesis_included_when_present(self):
        options = [{"ticker": "MRVL", "direction": "CALL", "composite_score": 8.0,
                     "confidence": "HIGH", "thesis": "Strong earnings momentum"}]
        html = email_formatter.format_morning_email_html(options, [])
        assert "Strong earnings momentum" in html

    def test_movers_section_included(self):
        movers = _sample_movers()
        html = email_formatter.format_morning_email_html([], [], movers=movers)
        assert "Daily Movers Spotlight" in html
        assert "TSLA" in html
        assert "+5.20%" in html
        assert "-2.10%" in html

    def test_movers_section_omitted_when_none(self):
        html = email_formatter.format_morning_email_html([], [], movers=None)
        assert "Daily Movers Spotlight" not in html

    def test_movers_section_omitted_when_empty(self):
        html = email_formatter.format_morning_email_html([], [], movers=[])
        assert "Daily Movers Spotlight" not in html

    def test_disclaimer_present(self):
        html = email_formatter.format_morning_email_html([], [])
        assert "Not financial advice" in html

    def test_no_unsubscribe_link(self):
        html = email_formatter.format_morning_email_html(
            _sample_options(), _sample_stocks(), movers=_sample_movers()
        )
        assert "unsubscribe" not in html.lower()
        assert "powered by" not in html.lower()

    def test_dark_theme_colors(self):
        html = email_formatter.format_morning_email_html(_sample_options(), [])
        assert "#1a1a2e" in html  # background
        assert "#16213e" in html  # card bg

    def test_inline_css_only(self):
        """No <style> blocks or <link> tags — all CSS must be inline."""
        html = email_formatter.format_morning_email_html(
            _sample_options(), _sample_stocks()
        )
        assert "<style" not in html
        assert "<link" not in html

    def test_empty_picks_no_crash(self):
        html = email_formatter.format_morning_email_html([], [])
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html

    def test_none_picks_no_crash(self):
        html = email_formatter.format_morning_email_html(None, None)
        assert isinstance(html, str)

    def test_strongest_agent_shown_for_stocks(self):
        stocks = [{"ticker": "GOOG", "action": "BUY", "composite_score": 7.0,
                    "confidence": "HIGH",
                    "agent_scores": {"technical": {"score": 9.0}, "sentiment": {"score": 5.0}}}]
        html = email_formatter.format_morning_email_html([], stocks)
        assert "technical" in html


# ---------------------------------------------------------------------------
# EOD recap email tests
# ---------------------------------------------------------------------------

class TestEodEmail:
    """format_eod_email_html produces valid HTML with P&L, accuracy, learning."""

    def test_returns_html_string(self):
        html = email_formatter.format_eod_email_html(_sample_recap())
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_header(self):
        html = email_formatter.format_eod_email_html(_sample_recap())
        assert "EOD Recap" in html

    def test_pnl_positive_green(self):
        recap = _sample_recap()
        recap["broker_pnl"]["daily_pnl"] = 250.0
        html = email_formatter.format_eod_email_html(recap)
        assert "+$250.00" in html
        assert "#00c853" in html

    def test_pnl_negative_red(self):
        recap = _sample_recap()
        recap["broker_pnl"]["daily_pnl"] = -100.0
        html = email_formatter.format_eod_email_html(recap)
        assert "-$100.00" in html
        assert "#ff1744" in html

    def test_accuracy_sections_present(self):
        html = email_formatter.format_eod_email_html(_sample_recap())
        assert "Pick Accuracy" in html
        assert "80.0%" in html
        assert "70.0%" in html
        assert "75.0%" in html

    def test_learning_status_present(self):
        html = email_formatter.format_eod_email_html(_sample_recap())
        assert "Learning Status" in html
        assert "Weights updated" in html

    def test_learning_status_pending(self):
        recap = _sample_recap()
        recap["weight_update"] = {"weights_updated": False, "days_evaluated": 2}
        html = email_formatter.format_eod_email_html(recap)
        assert "Need" in html
        assert "2" in html

    def test_transition_shown_when_present(self):
        recap = _sample_recap()
        recap["horizon_status"]["transition"] = "day_trade → swing_trade"
        html = email_formatter.format_eod_email_html(recap)
        assert "day_trade" in html

    def test_disclaimer_present(self):
        html = email_formatter.format_eod_email_html(_sample_recap())
        assert "Not financial advice" in html

    def test_no_unsubscribe_link(self):
        html = email_formatter.format_eod_email_html(_sample_recap())
        assert "unsubscribe" not in html.lower()

    def test_empty_recap_no_crash(self):
        html = email_formatter.format_eod_email_html({})
        assert isinstance(html, str)
        assert "<!DOCTYPE html>" in html
