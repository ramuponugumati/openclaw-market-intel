"""
HTML Email Formatter — paragraph style, reads like a normal email.
White background, minimal formatting, mobile-friendly.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

try:
    from company_lookup import get_company_name, get_fortune_badge
except ImportError:
    def get_company_name(t): return t
    def get_fortune_badge(t): return ""

GREEN = "#16a34a"
RED = "#dc2626"
GRAY = "#6b7280"


def _sf(v, d=0.0):
    try: return float(v)
    except: return d


def _today():
    return datetime.now(timezone.utc).strftime("%A, %B %d, %Y")


def _dir_word(d):
    d = d.upper()
    if d in ("CALL", "BUY"): return "buy"
    if d in ("PUT", "SELL", "SELL/SHORT"): return "sell"
    return "watch"


def _dir_color(d):
    d = d.upper()
    if d in ("CALL", "BUY"): return GREEN
    if d in ("PUT", "SELL", "SELL/SHORT"): return RED
    return GRAY


def _wrap(body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1f2937;line-height:1.6;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:16px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;text-align:left;">
{body}
<tr><td style="padding:24px 0 8px;font-size:11px;color:{GRAY};font-style:italic;border-top:1px solid #e5e7eb;">Not financial advice. Do your own research.</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def _pick_line(p: dict, kind: str = "stock") -> str:
    """One paragraph per pick."""
    tk = p.get("ticker", "?")
    co = get_company_name(tk)
    fort = get_fortune_badge(tk)
    sc = _sf(p.get("composite_score", 5))
    thesis = p.get("thesis", "")
    conf = p.get("confidence", "LOW")

    if kind == "option":
        d = p.get("direction", "HOLD")
        action = d.upper()
    else:
        action = p.get("action", p.get("direction", "WATCH")).upper()
        d = action

    color = _dir_color(d)
    fort_str = f" ({fort})" if fort else ""

    line = f'<span style="font-weight:700;">{tk}</span> — {co}{fort_str} — '
    line += f'<span style="color:{color};font-weight:700;">{action}</span> '
    line += f'(score {sc:.1f}, {conf.lower()} confidence)'

    if thesis:
        line += f'<br><span style="color:{GRAY};font-size:13px;">{thesis}</span>'

    return f'<p style="margin:0 0 14px;font-size:14px;">{line}</p>'


def _movers_paragraph(movers: list[dict] | None) -> str:
    if not movers:
        return ""
    top = movers[:20]
    parts = []
    for m in top:
        tk = m.get("ticker", "?")
        co = get_company_name(tk)
        ch = _sf(m.get("change_pct", m.get("gap_pct", 0)))
        color = GREEN if ch > 0 else RED
        arrow = "↑" if ch > 0 else "↓"
        parts.append(f'<span style="font-weight:600;">{tk}</span> ({co}) <span style="color:{color};">{arrow}{ch:+.1f}%</span>')
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Public: Morning Email
# ---------------------------------------------------------------------------

def format_morning_email_html(
    options_picks: list[dict],
    stock_picks: list[dict],
    movers: list[dict] | None = None,
    prediction_eval: dict | None = None,
) -> str:
    try:
        parts = []

        # Greeting
        parts.append(f"""<tr><td style="padding:24px 0 0;">
<p style="margin:0 0 4px;font-size:20px;font-weight:700;">🦀 OpenClaw Morning Picks</p>
<p style="margin:0 0 16px;font-size:13px;color:{GRAY};">{_today()}</p>
</td></tr>""")

        # Yesterday's report card (if available)
        if prediction_eval and prediction_eval.get("total_predictions", 0) > 0:
            acc = prediction_eval.get("accuracy_pct", 0)
            correct = prediction_eval.get("total_correct", 0)
            total = prediction_eval.get("total_predictions", 0)
            correct_buys = prediction_eval.get("correct_buys", [])
            wrong_buys = prediction_eval.get("wrong_buys", [])
            missed = prediction_eval.get("missed_movers", [])

            acc_color = GREEN if acc >= 60 else RED if acc < 40 else GRAY
            report = f'<span style="color:{acc_color};font-weight:700;">{acc:.0f}%</span> ({correct}/{total} correct)'
            if correct_buys:
                report += f'. Got it right: {", ".join(correct_buys[:5])}'
            if wrong_buys:
                report += f'. Missed: {", ".join(wrong_buys[:5])}'
            if missed:
                report += f'. Movers we didn\'t pick: {", ".join(missed[:5])}'

            parts.append(f"""<tr><td style="padding:0 0 16px;">
<p style="margin:0 0 6px;font-size:15px;font-weight:700;">📊 Yesterday's Report Card</p>
<p style="margin:0;font-size:13px;line-height:1.6;">{report}</p>
</td></tr>""")

        # Top movers section
        if movers:
            movers_text = _movers_paragraph(movers)
            parts.append(f"""<tr><td style="padding:0 0 16px;">
<p style="margin:0 0 6px;font-size:15px;font-weight:700;">🔥 Yesterday's Top 20 Movers</p>
<p style="margin:0;font-size:13px;line-height:1.7;">{movers_text}</p>
</td></tr>""")

        # Options picks
        if options_picks:
            options_html = "".join(_pick_line(p, "option") for p in options_picks)
            parts.append(f"""<tr><td style="padding:8px 0 0;">
<p style="margin:0 0 10px;font-size:15px;font-weight:700;">🎯 Options Plays</p>
{options_html}
</td></tr>""")

        # Stock picks
        if stock_picks:
            stocks_html = "".join(_pick_line(p, "stock") for p in stock_picks)
            parts.append(f"""<tr><td style="padding:8px 0 0;">
<p style="margin:0 0 10px;font-size:15px;font-weight:700;">📈 Stock Trades</p>
{stocks_html}
</td></tr>""")

        body = "\n".join(parts)
        return _wrap(body)
    except Exception as exc:
        logger.error("format_morning_email_html failed: %s", exc)
        return f"<html><body><p>Error: {exc}</p></body></html>"


# ---------------------------------------------------------------------------
# Public: EOD Recap Email
# ---------------------------------------------------------------------------

def format_eod_email_html(recap_data: dict) -> str:
    try:
        parts = []

        parts.append(f"""<tr><td style="padding:24px 0 0;">
<p style="margin:0 0 4px;font-size:20px;font-weight:700;">🌙 OpenClaw EOD Recap</p>
<p style="margin:0 0 16px;font-size:13px;color:{GRAY};">{_today()}</p>
</td></tr>""")

        # P&L
        broker = recap_data.get("broker_pnl", {})
        pnl = _sf(broker.get("daily_pnl", 0))
        equity = broker.get("equity", "N/A")
        pnl_color = GREEN if pnl >= 0 else RED
        pnl_sign = "+" if pnl >= 0 else ""

        parts.append(f"""<tr><td style="padding:0 0 16px;">
<p style="margin:0 0 6px;font-size:15px;font-weight:700;">💰 P&L</p>
<p style="margin:0;font-size:14px;">Daily: <span style="color:{pnl_color};font-weight:700;">{pnl_sign}${abs(pnl):,.2f}</span> · Equity: ${equity}</p>
</td></tr>""")

        # Accuracy
        oa = recap_data.get("overall_accuracy", "N/A")
        sa = recap_data.get("stock_accuracy", "N/A")
        opta = recap_data.get("options_accuracy", "N/A")

        def _fmt(v):
            try: return f"{float(v):.1f}%"
            except: return str(v)

        parts.append(f"""<tr><td style="padding:0 0 16px;">
<p style="margin:0 0 6px;font-size:15px;font-weight:700;">🎯 Accuracy</p>
<p style="margin:0;font-size:14px;">Overall: {_fmt(oa)} · Stocks: {_fmt(sa)} · Options: {_fmt(opta)}</p>
</td></tr>""")

        # Learning status
        wu = recap_data.get("weight_update", {})
        days = wu.get("days_evaluated", 0)
        updated = wu.get("weights_updated", False)
        mode = recap_data.get("horizon_status", {}).get("current_mode", "day_trade")

        parts.append(f"""<tr><td style="padding:0 0 16px;">
<p style="margin:0 0 6px;font-size:15px;font-weight:700;">🧠 Learning</p>
<p style="margin:0;font-size:14px;">Days evaluated: {days} · Weights {"updated" if updated else "pending"} · Mode: {mode}</p>
</td></tr>""")

        body = "\n".join(parts)
        return _wrap(body)
    except Exception as exc:
        logger.error("format_eod_email_html failed: %s", exc)
        return f"<html><body><p>Error: {exc}</p></body></html>"
