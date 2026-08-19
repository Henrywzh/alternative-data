"""Daily Gmail report for the Index & ETF Allocation Monitor.

Mirrors the tungsten daily-report channel (Gmail SMTP/SSL, secrets or local
``.config``), but sends a decision-oriented HTML digest — leadership,
relative-regime moves, wrapper-premium opportunities, and timing — rather than
a chart attachment dump.
"""

from __future__ import annotations

import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

import pandas as pd

from .config import REPO_ROOT


def load_gmail_config() -> dict[str, str]:
    values = {
        key: os.environ[key]
        for key in ("GMAIL_SENDER", "GMAIL_APP_PASSWORD", "GMAIL_RECIPIENT", "GMAIL_RECIPIENTS")
        if os.environ.get(key)
    }
    config_path = REPO_ROOT / ".config"
    if config_path.exists():
        for raw in config_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    recipients = [item.strip() for item in re.split(r"[,;]", values.get("GMAIL_RECIPIENTS") or values.get("GMAIL_RECIPIENT", "")) if item.strip()]
    values["GMAIL_RECIPIENTS"] = ", ".join(recipients)
    missing = [key for key in ("GMAIL_SENDER", "GMAIL_APP_PASSWORD") if not values.get(key)]
    if not recipients:
        missing.append("GMAIL_RECIPIENTS")
    if missing:
        raise RuntimeError("Missing Gmail config for market_monitor: " + ", ".join(missing))
    return values


def _fmt_pct(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value:+.{digits}f}%"


def _arrow(trend: str | None) -> str:
    return {"UP": "▲", "DOWN": "▼"}.get(trend or "", "→")


def _fmt_z(z: float | None) -> str:
    return "—" if z is None else f"{z:+.1f}σ"


def build_email_html(
    *,
    report_date: str,
    technicals: pd.DataFrame,
    regime: pd.DataFrame,
    wrappers: pd.DataFrame,
) -> str:
    """Render a compact decision-oriented digest."""
    rows_html = []
    if not technicals.empty:
        for _, row in technicals.iterrows():
            trend = "▲" if (row.get("ma20_pct") or 0) > 0 else "▼"
            rsi_val = row.get("rsi")
            rsi_display = "—" if rsi_val is None or (isinstance(rsi_val, float) and rsi_val != rsi_val) else f"{float(rsi_val):.0f}"
            rows_html.append(
                f"<tr><td>{row.get('label','')}</td>"
                f"<td>{_fmt_pct(row.get('ma20_pct'))}</td>"
                f"<td>{_fmt_pct(row.get('ma60_pct'))}</td>"
                f"<td>{trend}</td>"
                f"<td>{rsi_display}</td></tr>"
            )
    regime_html = "".join(
        f"<tr><td>{r.get('label','')}</td><td>{_fmt_z(r.get('spread_20d_zscore'))}</td><td>{_arrow(r.get('trend'))}</td><td>{_fmt_pct(r.get('spread_20d_pct'))}</td></tr>"
        for _, r in regime.iterrows()
    )
    wrap_html = "".join(
        f"<tr><td>{w.get('ticker','')}</td><td>{w.get('fund_name','')}</td>"
        f"<td>{_fmt_pct(w.get('premium_pct'),2)}</td><td>{_fmt_pct(w.get('relative_premium_pct'),2)}</td>"
        f"<td>{int(round(w.get('buy_rank'))) if pd.notna(w.get('buy_rank')) else '-'}</td>"
        f"<td>{int(round(w.get('hold_rank'))) if pd.notna(w.get('hold_rank')) else '-'}</td></tr>"
        for _, w in wrappers.head(24).iterrows()
    )
    return f"""<html><body style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.5">
<h2>Index &amp; ETF Allocation Monitor — {report_date}</h2>
<h3>Market Leadership</h3>
<table border="0" cellspacing="0" cellpadding="6">
<tr><th align="left">Exposure</th><th align="left">MA20</th><th align="left">MA60</th><th>Trend</th><th>RSI</th></tr>
{''.join(rows_html)}
</table>
<h3>Relative Regime</h3>
<table border="0" cellspacing="0" cellpadding="6">
<tr><th align="left">Spread</th><th align="left">20D z-score</th><th>Trend</th><th align="left">20D ret</th></tr>
{regime_html}
</table>
<h3>Wrapper Opportunities (Buy-Now vs Hold)</h3>
<table border="0" cellspacing="0" cellpadding="6">
<tr><th align="left">Ticker</th><th align="left">Fund</th><th align="left">Premium</th><th align="left">Rel Premium</th><th>Buy</th><th>Hold</th></tr>
{wrap_html}
</table>
<p style="color:#666;font-size:12px">Cross-border (QDII) premium interpretation differs from domestic ETFs. This is a research digest, not investment advice.</p>
</body></html>"""


def send_report(*, subject: str, body_html: str) -> None:
    config = load_gmail_config()
    msg = EmailMessage()
    msg["From"] = config["GMAIL_SENDER"]
    msg["To"] = config["GMAIL_RECIPIENTS"]
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.set_content("Index & ETF Allocation Monitor digest (HTML only)")
    msg.add_alternative(body_html, subtype="html")
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as smtp:
        smtp.login(config["GMAIL_SENDER"], config["GMAIL_APP_PASSWORD"])
        smtp.send_message(msg)
