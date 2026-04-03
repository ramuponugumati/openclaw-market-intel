"""
HTML Email Formatter for OpenClaw Market Intel

Clean, white-background, mobile-friendly emails.
Minimal colors — green for buy, red for sell, gray for neutral.
Inline CSS only for email client compatibility.
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

# Minimal palette
GREEN = "#16a34a"
RED = "#dc2626"
AMBER = "#d97706"
GRAY = "#6b7280"
LIGHT_GRAY = "#f3f4f6"
BORDER = "#e5e7eb"


def _score_color(score: float) -> str:
    if score >= 7: return GREEN
    if score >= 5: return AMBER
    return RED


def _dir_color(d: str) -> str:
    d = d.upper()
    if d in ("CALL", "BUY"): return GREEN
    if d in ("PUT", "SELL", "SELL/SHORT"): return RED
    return GRAY


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%A, %B %d, %Y")


def _sf(val, default=0.0) -> float:
    try: return float(val)
    except: return default


def _wrap(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#ffffff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#1f2937;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:16px 8px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">

<tr><td style="padding:20px 16px 12px;border-bottom:2px solid #1f2937;">
<h1 style="margin:0;font-size:20px;font-weight:700;color:#1f2937;">🦀 {title}</h1>
<p style="margin:4px 0 0;font-size:13px;color:{GRAY};">{_today()}</p>
</td></tr>

{body}

<tr><td style="padding:16px;text-align:center;">
<p style="margin:0;font-size:11px;color:{GRAY};font-style:italic;">Not financial advice. Do your own research.</p>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Options section
# ---------------------------------------------------------------------------

def _build_options_section(picks: list[dict]) -> str:
    if not picks:
        return ""
    rows = ""
    for i, p in enumerate(picks, 1):
        tk = p.get("ticker", "?")
        co = get_company_name(tk)
        fort = get_fortune_badge(tk)
        d = p.get("direction", "HOLD")
        sc = _sf(p.get("composite_score", 5))
        conf = p.get("confidence", "LOW")
        thesis = p.get("thesis", "")
        dc = _dir_color(d)
        sc_c = _score_color(sc)
        fort_html = f' <span style="font-size:10px;color:{AMBER};font-weight:600;">{fort}</span>' if fort else ""

        rows += f"""<tr style="border-bottom:1px solid {BORDER};">
<td style="padding:10px 8px;font-size:13px;color:{GRAY};text-align:center;width:30px;">{i}</td>
<td style="padding:10px 8px;">
<span style="font-size:14px;font-weight:700;color:#1f2937;">{tk}</span>{fort_html}<br>
<span style="font-size:12px;color:{GRAY};">{co}</span>
</td>
<td style="padding:10px 8px;text-align:center;"><span style="font-size:13px;font-weight:700;color:{dc};">{d}</span></td>
<td style="padding:10px 8px;text-align:center;font-size:14px;font-weight:700;color:{sc_c};">{sc:.1f}</td>
<td style="padding:10px 8px;text-align:center;font-size:12px;color:{GRAY};">{conf}</td>
</tr>"""
        if thesis:
            rows += f"""<tr style="border-bottom:1px solid {BORDER};"><td></td>
<td colspan="4" style="padding:2px 8px 10px;font-size:12px;color:{GRAY};line-height:1.4;">📝 {thesis}</td></tr>"""

    return f"""<tr><td style="padding:20px 16px 0;">
<h2 style="margin:0 0 8px;font-size:15px;font-weight:700;color:#1f2937;">🎯 Top Options Plays</h2>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {BORDER};border-radius:6px;">
<tr style="background:{LIGHT_GRAY};">
<th style="padding:8px;font-size:11px;color:{GRAY};text-transform:uppercase;text-align:center;width:30px;">#</th>
<th style="padding:8px;font-size:11px;color:{GRAY};text-transform:uppercase;text-align:left;">Ticker</th>
<th style="padding:8px;font-size:11px;color:{GRAY};text-transform:uppercase;text-align:center;">Dir</th>
<th style="padding:8px;font-size:11px;color:{GRAY};text-transform:uppercase;text-align:center;">Score</th>
<th style="padding:8px;font-size:11px;color:{GRAY};text-transform:uppercase;text-align:center;">Conf</th>
</tr>
{rows}
</table>
</td></tr>"""


# ---------------------------------------------------------------------------
# Stocks section
# ---------------------------------------------------------------------------

def _find_strongest(agent_scores: dict) -> str:
    if not agent_scores: return ""
    best, best_d = "", 0.0
    for aid, info in agent_scores.items():
        s = info.get("score", 5.0) if isinstance(info, dict) else 5.0
        d = abs(s - 5.0)
        if d > best_d:
            best_d = d
            best = aid
    return best


def _build_stocks_section(picks: list[dict]) -> str:
    if not picks:
        return ""
    rows = ""
    for i, p in enumerate(picks, 1):
        tk = p.get("ticker", "?")
        co = get_company_name(tk)
        fort = get_fortune_badge(tk)
        act = p.get("action", p.get("direction", "WATCH"))
        sc = _sf(p.get("composite_score", 5))
        conf = p.get("confidence", "LOW")
        strongest = _find_strongest(p.get("agent_scores", {}))
        thesis = p.get("thesis", "")
        ac = _dir_color(act)
        sc_c = _score_color(sc)
        fort_html = f' <span style="font-size:10px;color:{AMBER};font-weight:600;">{fort}</span>' if fort else ""

        rows += f"""<tr style="border-bottom:1px solid {BORDER};">
<td style="padding:10px 8px;font-size:13px;color:{GRAY};text-align:center;width:30px;">{i}</td>
<td style="padding:10px 8px;">
<span style="font-size:14px;font-weight:700;color:#1f2937;">{tk}</span>{fort_html}<br>
<span style="font-size:12px;color:{GRAY};">{co}</span>
</td>
<td style="padding:10px 8px;text-align:center;"><span style="font-size:13px;font-weight:700;color:{ac};">{act}</span></td>
<td style="padding:10px 8px;text-align:center;font-size:14px;font-weight:700;color:{sc_c};">{sc:.1f}</td>
<td style="padding:10px 8px;text-align:center;font-size:12px;color:{GRAY};">{conf}</td>
<td style="padding:10px 8px;text-align:center;font-size:11px;color:{GRAY};">{strongest}</td>
</tr>"""
        if thesis:
            rows += f"""<tr style="border-bottom:1px solid {BORDER};"><td></td>
<td colspan="5" style="padding:2px 8px 10px;font-size:12px;color:{GRAY};line-height:1.4;">📝 {thesis}</td></tr>"""

    return f"""<tr><td style="padding:20px 16px 0;">
<h2 style="margin:0 0 8px;font-size:15px;font-weight:700;color:#1f2937;">📈 Top Stock Trades</h2>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {BORDER};border-radius:6px;">
<tr style="background:{LIGHT_GRAY};">
<th style="padding:8px;font-size:11px;color:{GRAY};text-transform:uppercase;text-align:center;width:30px;">#</th>
<th style="padding:8px;font-size:11px;color:{GRAY};text-transform:uppercase;text-align:left;">Ticker</th>
<th style="padding:8px;font-size:11px;color:{GRAY};text-transform:uppercase;text-align:center;">Action</th>
<th style="padding:8px;font-size:11px;color:{GRAY};text-transform:uppercase;text-align:center;">Score</th>
<th style="padding:8px;font-size:11px;color:{GRAY};text-transform:uppercase;text-align:center;">Conf</th>
<th style="padding:8px;font-size:11px;color:{GRAY};text-transform:uppercase;text-align:center;">Lead</th>
</tr>
{rows}
</table>
</td></tr>"""


# ---------------------------------------------------------------------------
# Movers section
# ---------------------------------------------------------------------------

def _build_movers_section(movers: list[dict] | None) -> str:
    if not movers:
        return ""
    rows = ""
    for m in movers[:15]:
        tk = m.get("ticker", "?")
        co = get_company_name(tk)
        ch = _sf(m.get("change_pct", m.get("gap_pct", 0)))
        c = GREEN if ch > 0 else RED
        arrow = "▲" if ch > 0 else "▼"
        rows += f"""<tr style="border-bottom:1px solid {BORDER};">
<td style="padding:6px 8px;font-size:13px;font-weight:600;color:#1f2937;">{tk} <span style="font-size:11px;color:{GRAY};font-weight:400;">{co}</span></td>
<td style="padding:6px 8px;text-align:right;font-size:13px;font-weight:700;color:{c};">{arrow} {ch:+.1f}%</td>
</tr>"""

    return f"""<tr><td style="padding:20px 16px 0;">
<h2 style="margin:0 0 8px;font-size:15px;font-weight:700;color:#1f2937;">🔥 Top Movers</h2>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {BORDER};border-radius:6px;">
{rows}
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
    try:
        parts = [
            _build_options_section(options_picks or []),
            _build_stocks_section(stock_picks or []),
            _build_movers_section(movers),
        ]
        body = "\n".join(p for p in parts if p)
        return _wrap("OpenClaw Morning Picks", body)
    except Exception as exc:
        logger.error("format_morning_email_html failed: %s", exc)
        return f"<html><body><p>Error: {exc}</p></body></html>"


# ---------------------------------------------------------------------------
# EOD Recap Email
# ---------------------------------------------------------------------------

def _build_pnl_section(broker_pnl: dict) -> str:
    pnl = _sf(broker_pnl.get("daily_pnl", 0))
    equity = broker_pnl.get("equity", "N/A")
    c = GREEN if pnl >= 0 else RED
    sign = "+" if pnl >= 0 else ""
    return f"""<tr><td style="padding:20px 16px 0;">
<h2 style="margin:0 0 8px;font-size:15px;font-weight:700;">💰 P&L</h2>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {BORDER};border-radius:6px;">
<tr style="border-bottom:1px solid {BORDER};">
<td style="padding:10px 12px;font-size:13px;color:{GRAY};">Daily P&L</td>
<td style="padding:10px 12px;text-align:right;font-size:16px;font-weight:700;color:{c};">{sign}${abs(pnl):,.2f}</td>
</tr>
<tr>
<td style="padding:10px 12px;font-size:13px;color:{GRAY};">Equity</td>
<td style="padding:10px 12px;text-align:right;font-size:14px;color:#1f2937;">${equity}</td>
</tr>
</table>
</td></tr>"""


def _build_accuracy_section(data: dict) -> str:
    def _f(v):
        try: return f"{float(v):.1f}%"
        except: return str(v)
    def _c(v):
        try:
            v = float(v)
            return GREEN if v >= 70 else AMBER if v >= 50 else RED
        except: return GRAY

    oa = data.get("overall_accuracy", "N/A")
    sa = data.get("stock_accuracy", "N/A")
    opta = data.get("options_accuracy", "N/A")

    return f"""<tr><td style="padding:20px 16px 0;">
<h2 style="margin:0 0 8px;font-size:15px;font-weight:700;">🎯 Accuracy</h2>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border:1px solid {BORDER};border-radius:6px;">
<tr style="border-bottom:1px solid {BORDER};">
<td style="padding:10px 12px;font-size:13px;color:{GRAY};">Overall</td>
<td style="padding:10px 12px;text-align:right;font-size:16px;font-weight:700;color:{_c(oa)};">{_f(oa)}</td>
</tr>
<tr style="border-bottom:1px solid {BORDER};">
<td style="padding:10px 12px;font-size:13px;color:{GRAY};">Stocks</td>
<td style="padding:10px 12px;text-align:right;font-size:14px;font-weight:600;color:{_c(sa)};">{_f(sa)}</td>
</tr>
<tr>
<td style="padding:10px 12px;font-size:13px;color:{GRAY};">Options</td>
<td style="padding:10px 12px;text-align:right;font-size:14px;font-weight:600;color:{_c(opta)};">{_f(opta)}</td>
</tr>
</table>
</td></tr>"""


def format_eod_email_html(recap_data: dict) -> str:
    try:
        parts = [
            _build_pnl_section(recap_data.get("broker_pnl", {})),
            _build_accuracy_section(recap_data),
        ]
        body = "\n".join(p for p in parts if p)
        return _wrap("OpenClaw EOD Recap", body)
    except Exception as exc:
        logger.error("format_eod_email_html failed: %s", exc)
        return f"<html><body><p>Error: {exc}</p></body></html>"
