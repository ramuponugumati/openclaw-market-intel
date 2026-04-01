"""
HTML Email Formatter for OpenClaw Market Intel

Generates professional dark-themed HTML emails for morning picks and EOD recaps.
Uses inline CSS only for maximum email client compatibility.

Functions:
    format_morning_email_html — Morning picks email (options + stocks + movers)
    format_eod_email_html     — EOD recap email (P&L + accuracy + learning)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Color palette
# ---------------------------------------------------------------------------
BG_DARK = "#1a1a2e"
CARD_BG = "#16213e"
TEXT_COLOR = "#e0e0e0"
TEXT_MUTED = "#8892a0"
GREEN = "#00c853"
RED = "#ff1744"
YELLOW = "#ffd600"
BORDER_COLOR = "#2a2a4a"
HEADER_BG = "#0f3460"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _score_badge(score: float) -> str:
    """Return an inline-styled score badge colored by value."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        s = 5.0
    if s >= 7:
        color = GREEN
    elif s >= 5:
        color = YELLOW
    else:
        color = RED
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:10px;'
        f'background:{color};color:#000;font-weight:bold;font-size:13px;">'
        f'{s:.1f}</span>'
    )


def _direction_color(direction: str) -> str:
    d = direction.upper()
    if d in ("CALL", "BUY"):
        return GREEN
    if d in ("PUT", "SELL", "SELL/SHORT"):
        return RED
    return YELLOW


def _direction_label(direction: str) -> str:
    d = direction.upper()
    color = _direction_color(d)
    return f'<span style="color:{color};font-weight:bold;">{d}</span>'


def _pct_color(value: float) -> str:
    if value > 0:
        return GREEN
    if value < 0:
        return RED
    return TEXT_MUTED


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%B %d, %Y")


def _base_wrapper(title: str, body: str) -> str:
    """Wrap body content in the base HTML email shell."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:{BG_DARK};font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{BG_DARK};">
<tr><td align="center" style="padding:20px 10px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:{BG_DARK};">

<!-- Header -->
<tr><td style="background:{HEADER_BG};padding:24px 20px;border-radius:8px 8px 0 0;text-align:center;">
<h1 style="margin:0;color:#ffffff;font-size:22px;font-weight:bold;">{title}</h1>
<p style="margin:6px 0 0;color:{TEXT_MUTED};font-size:13px;">{_today_str()}</p>
</td></tr>

<!-- Body -->
<tr><td style="padding:0;">
{body}
</td></tr>

<!-- Disclaimer -->
<tr><td style="padding:16px 20px;text-align:center;">
<p style="margin:0;color:{TEXT_MUTED};font-size:11px;font-style:italic;">Not financial advice. Do your own research.</p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Section builders — Morning Email
# ---------------------------------------------------------------------------

def _build_options_section(options_picks: list[dict]) -> str:
    if not options_picks:
        return ""

    rows = ""
    for i, pick in enumerate(options_picks, 1):
        ticker = pick.get("ticker", "???")
        direction = pick.get("direction", "HOLD")
        score = _safe_float(pick.get("composite_score", 5.0))
        confidence = pick.get("confidence", "LOW")
        thesis = pick.get("thesis", "")
        border_color = _direction_color(direction)

        rows += f"""<tr>
<td style="padding:10px 12px;border-left:4px solid {border_color};color:{TEXT_COLOR};font-size:14px;border-bottom:1px solid {BORDER_COLOR};">{i}</td>
<td style="padding:10px 8px;color:#fff;font-weight:bold;font-size:14px;border-bottom:1px solid {BORDER_COLOR};">{ticker}</td>
<td style="padding:10px 8px;border-bottom:1px solid {BORDER_COLOR};">{_direction_label(direction)}</td>
<td style="padding:10px 8px;border-bottom:1px solid {BORDER_COLOR};">{_score_badge(score)}</td>
<td style="padding:10px 8px;color:{TEXT_COLOR};font-size:13px;border-bottom:1px solid {BORDER_COLOR};">{confidence}</td>
</tr>"""
        if thesis:
            rows += f"""<tr><td colspan="5" style="padding:4px 12px 12px 24px;color:{TEXT_MUTED};font-size:12px;font-style:italic;border-bottom:1px solid {BORDER_COLOR};">📝 {thesis}</td></tr>"""

    return f"""<tr><td style="padding:20px 20px 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CARD_BG};border-radius:8px;overflow:hidden;">
<tr><td style="padding:14px 16px;border-bottom:1px solid {BORDER_COLOR};">
<h2 style="margin:0;color:#fff;font-size:16px;">🎯 Top Options Plays</h2>
</td></tr>
<tr><td style="padding:0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr style="background:{HEADER_BG};">
<th style="padding:8px 12px;text-align:left;color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;">Rank</th>
<th style="padding:8px;text-align:left;color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;">Ticker</th>
<th style="padding:8px;text-align:left;color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;">Direction</th>
<th style="padding:8px;text-align:left;color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;">Score</th>
<th style="padding:8px;text-align:left;color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;">Confidence</th>
</tr>
{rows}
</table>
</td></tr>
</table>
</td></tr>"""


def _find_strongest_agent(agent_scores: dict) -> str:
    if not agent_scores:
        return ""
    best_agent = ""
    best_distance = 0.0
    for agent_id, info in agent_scores.items():
        score = info.get("score", 5.0) if isinstance(info, dict) else 5.0
        distance = abs(score - 5.0)
        if distance > best_distance:
            best_distance = distance
            best_agent = agent_id
    return best_agent


def _build_stocks_section(stock_picks: list[dict]) -> str:
    if not stock_picks:
        return ""

    rows = ""
    for i, pick in enumerate(stock_picks, 1):
        ticker = pick.get("ticker", "???")
        action = pick.get("action", pick.get("direction", "WATCH"))
        score = _safe_float(pick.get("composite_score", 5.0))
        confidence = pick.get("confidence", "LOW")
        strongest = _find_strongest_agent(pick.get("agent_scores", {}))
        thesis = pick.get("thesis", "")
        border_color = _direction_color(action)

        rows += f"""<tr>
<td style="padding:10px 12px;border-left:4px solid {border_color};color:{TEXT_COLOR};font-size:14px;border-bottom:1px solid {BORDER_COLOR};">{i}</td>
<td style="padding:10px 8px;color:#fff;font-weight:bold;font-size:14px;border-bottom:1px solid {BORDER_COLOR};">{ticker}</td>
<td style="padding:10px 8px;border-bottom:1px solid {BORDER_COLOR};">{_direction_label(action)}</td>
<td style="padding:10px 8px;border-bottom:1px solid {BORDER_COLOR};">{_score_badge(score)}</td>
<td style="padding:10px 8px;color:{TEXT_COLOR};font-size:13px;border-bottom:1px solid {BORDER_COLOR};">{confidence}</td>
<td style="padding:10px 8px;color:{TEXT_MUTED};font-size:12px;border-bottom:1px solid {BORDER_COLOR};">{strongest}</td>
</tr>"""
        if thesis:
            rows += f"""<tr><td colspan="6" style="padding:4px 12px 12px 24px;color:{TEXT_MUTED};font-size:12px;font-style:italic;border-bottom:1px solid {BORDER_COLOR};">📝 {thesis}</td></tr>"""

    return f"""<tr><td style="padding:20px 20px 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CARD_BG};border-radius:8px;overflow:hidden;">
<tr><td style="padding:14px 16px;border-bottom:1px solid {BORDER_COLOR};">
<h2 style="margin:0;color:#fff;font-size:16px;">📈 Top Stock Trades</h2>
</td></tr>
<tr><td style="padding:0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr style="background:{HEADER_BG};">
<th style="padding:8px 12px;text-align:left;color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;">Rank</th>
<th style="padding:8px;text-align:left;color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;">Ticker</th>
<th style="padding:8px;text-align:left;color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;">Action</th>
<th style="padding:8px;text-align:left;color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;">Score</th>
<th style="padding:8px;text-align:left;color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;">Confidence</th>
<th style="padding:8px;text-align:left;color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;">Strongest</th>
</tr>
{rows}
</table>
</td></tr>
</table>
</td></tr>"""


def _build_movers_section(movers: list[dict] | None) -> str:
    if not movers:
        return ""

    rows = ""
    for m in movers:
        ticker = m.get("ticker", "???")
        change = _safe_float(m.get("change_pct", m.get("gap_pct", 0)))
        color = _pct_color(change)
        arrow = "▲" if change > 0 else "▼" if change < 0 else "—"
        rows += f"""<tr>
<td style="padding:6px 12px;color:#fff;font-weight:bold;font-size:13px;border-bottom:1px solid {BORDER_COLOR};">{ticker}</td>
<td style="padding:6px 8px;color:{color};font-weight:bold;font-size:13px;border-bottom:1px solid {BORDER_COLOR};">{arrow} {change:+.2f}%</td>
</tr>"""

    return f"""<tr><td style="padding:20px 20px 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CARD_BG};border-radius:8px;overflow:hidden;">
<tr><td style="padding:14px 16px;border-bottom:1px solid {BORDER_COLOR};">
<h2 style="margin:0;color:#fff;font-size:16px;">🔥 Daily Movers Spotlight</h2>
</td></tr>
<tr><td style="padding:0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr style="background:{HEADER_BG};">
<th style="padding:8px 12px;text-align:left;color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;">Ticker</th>
<th style="padding:8px;text-align:left;color:{TEXT_MUTED};font-size:11px;text-transform:uppercase;">Change</th>
</tr>
{rows}
</table>
</td></tr>
</table>
</td></tr>"""


# ---------------------------------------------------------------------------
# Public: Morning Email
# ---------------------------------------------------------------------------

def format_morning_email_html(
    options_picks: list[dict],
    stock_picks: list[dict],
    movers: list[dict] | None = None,
) -> str:
    """
    Generate a professional HTML email for the morning picks.

    Args:
        options_picks: List of options pick dicts (ticker, direction, composite_score, confidence, thesis).
        stock_picks:   List of stock pick dicts (ticker, action, composite_score, confidence, agent_scores, thesis).
        movers:        Optional list of daily mover dicts (ticker, change_pct).

    Returns:
        Complete HTML string ready for SES send_email().
    """
    try:
        body_parts = []
        body_parts.append(_build_options_section(options_picks or []))
        body_parts.append(_build_stocks_section(stock_picks or []))
        body_parts.append(_build_movers_section(movers))
        body = "\n".join(p for p in body_parts if p)
        return _base_wrapper("🦀 OpenClaw Morning Picks", body)
    except Exception as exc:
        logger.error("format_morning_email_html failed: %s", exc)
        return f"<html><body><p>Morning picks formatting error: {exc}</p></body></html>"


# ---------------------------------------------------------------------------
# Section builders — EOD Recap Email
# ---------------------------------------------------------------------------

def _build_pnl_section(broker_pnl: dict) -> str:
    daily_pnl = _safe_float(broker_pnl.get("daily_pnl", 0))
    equity = broker_pnl.get("equity", "N/A")
    pnl_color = GREEN if daily_pnl >= 0 else RED
    pnl_sign = "+" if daily_pnl >= 0 else "-"
    pnl_abs = abs(daily_pnl)

    return f"""<tr><td style="padding:20px 20px 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CARD_BG};border-radius:8px;overflow:hidden;">
<tr><td style="padding:14px 16px;border-bottom:1px solid {BORDER_COLOR};">
<h2 style="margin:0;color:#fff;font-size:16px;">💰 Broker P&amp;L</h2>
</td></tr>
<tr><td style="padding:16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr>
<td style="padding:8px 0;color:{TEXT_MUTED};font-size:13px;">Daily P&amp;L</td>
<td style="padding:8px 0;text-align:right;color:{pnl_color};font-size:18px;font-weight:bold;">{pnl_sign}${pnl_abs:,.2f}</td>
</tr>
<tr>
<td style="padding:8px 0;color:{TEXT_MUTED};font-size:13px;border-top:1px solid {BORDER_COLOR};">Equity</td>
<td style="padding:8px 0;text-align:right;color:{TEXT_COLOR};font-size:16px;border-top:1px solid {BORDER_COLOR};">${equity}</td>
</tr>
</table>
</td></tr>
</table>
</td></tr>"""


def _build_accuracy_section(recap_data: dict) -> str:
    options_acc = recap_data.get("options_accuracy", "N/A")
    stock_acc = recap_data.get("stock_accuracy", "N/A")
    overall_acc = recap_data.get("overall_accuracy", "N/A")

    def _fmt(val) -> str:
        if isinstance(val, (int, float)):
            return f"{val:.1f}%"
        return str(val)

    def _acc_color(val) -> str:
        try:
            v = float(val)
            if v >= 70:
                return GREEN
            if v >= 50:
                return YELLOW
            return RED
        except (TypeError, ValueError):
            return TEXT_MUTED

    return f"""<tr><td style="padding:20px 20px 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CARD_BG};border-radius:8px;overflow:hidden;">
<tr><td style="padding:14px 16px;border-bottom:1px solid {BORDER_COLOR};">
<h2 style="margin:0;color:#fff;font-size:16px;">🎯 Pick Accuracy</h2>
</td></tr>
<tr><td style="padding:16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr>
<td style="padding:8px 0;color:{TEXT_MUTED};font-size:13px;">Options</td>
<td style="padding:8px 0;text-align:right;color:{_acc_color(options_acc)};font-size:15px;font-weight:bold;">{_fmt(options_acc)}</td>
</tr>
<tr>
<td style="padding:8px 0;color:{TEXT_MUTED};font-size:13px;border-top:1px solid {BORDER_COLOR};">Stocks</td>
<td style="padding:8px 0;text-align:right;color:{_acc_color(stock_acc)};font-size:15px;font-weight:bold;border-top:1px solid {BORDER_COLOR};">{_fmt(stock_acc)}</td>
</tr>
<tr>
<td style="padding:8px 0;color:{TEXT_MUTED};font-size:13px;border-top:1px solid {BORDER_COLOR};">Overall</td>
<td style="padding:8px 0;text-align:right;color:{_acc_color(overall_acc)};font-size:18px;font-weight:bold;border-top:1px solid {BORDER_COLOR};">{_fmt(overall_acc)}</td>
</tr>
</table>
</td></tr>
</table>
</td></tr>"""


def _build_learning_section(recap_data: dict) -> str:
    weight_update = recap_data.get("weight_update", {})
    horizon = recap_data.get("horizon_status", {})
    days_eval = weight_update.get("days_evaluated", 0)
    weights_updated = weight_update.get("weights_updated", False)
    current_mode = horizon.get("current_mode", "day_trade")
    transition = horizon.get("transition")

    mode_labels = {
        "day_trade": "📅 Day Trade",
        "swing_trade": "📆 Swing Trade",
        "long_term": "📈 Long Term",
    }
    mode_label = mode_labels.get(current_mode, current_mode)
    status_icon = "✅" if weights_updated else "⏳"
    status_text = "Weights updated" if weights_updated else f"Need ≥5 days (have {days_eval})"

    transition_row = ""
    if transition:
        transition_row = f"""<tr>
<td style="padding:8px 0;color:{TEXT_MUTED};font-size:13px;border-top:1px solid {BORDER_COLOR};">Transition</td>
<td style="padding:8px 0;text-align:right;color:{YELLOW};font-size:13px;border-top:1px solid {BORDER_COLOR};">🔄 {transition}</td>
</tr>"""

    return f"""<tr><td style="padding:20px 20px 0;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{CARD_BG};border-radius:8px;overflow:hidden;">
<tr><td style="padding:14px 16px;border-bottom:1px solid {BORDER_COLOR};">
<h2 style="margin:0;color:#fff;font-size:16px;">🧠 Learning Status</h2>
</td></tr>
<tr><td style="padding:16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr>
<td style="padding:8px 0;color:{TEXT_MUTED};font-size:13px;">Days Evaluated</td>
<td style="padding:8px 0;text-align:right;color:{TEXT_COLOR};font-size:15px;">{days_eval}</td>
</tr>
<tr>
<td style="padding:8px 0;color:{TEXT_MUTED};font-size:13px;border-top:1px solid {BORDER_COLOR};">Weight Status</td>
<td style="padding:8px 0;text-align:right;color:{TEXT_COLOR};font-size:13px;border-top:1px solid {BORDER_COLOR};">{status_icon} {status_text}</td>
</tr>
<tr>
<td style="padding:8px 0;color:{TEXT_MUTED};font-size:13px;border-top:1px solid {BORDER_COLOR};">Trading Mode</td>
<td style="padding:8px 0;text-align:right;color:{TEXT_COLOR};font-size:13px;border-top:1px solid {BORDER_COLOR};">{mode_label}</td>
</tr>
{transition_row}
</table>
</td></tr>
</table>
</td></tr>"""


# ---------------------------------------------------------------------------
# Public: EOD Recap Email
# ---------------------------------------------------------------------------

def format_eod_email_html(recap_data: dict) -> str:
    """
    Generate a professional HTML email for the EOD recap.

    Args:
        recap_data: Dict with keys: broker_pnl, trade_results,
                    options_accuracy, stock_accuracy, overall_accuracy,
                    weight_update, horizon_status.

    Returns:
        Complete HTML string ready for SES send_email().
    """
    try:
        body_parts = []
        body_parts.append(_build_pnl_section(recap_data.get("broker_pnl", {})))
        body_parts.append(_build_accuracy_section(recap_data))
        body_parts.append(_build_learning_section(recap_data))
        body = "\n".join(p for p in body_parts if p)
        return _base_wrapper("🌙 OpenClaw EOD Recap", body)
    except Exception as exc:
        logger.error("format_eod_email_html failed: %s", exc)
        return f"<html><body><p>EOD recap formatting error: {exc}</p></body></html>"
