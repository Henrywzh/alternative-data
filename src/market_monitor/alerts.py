"""Daily Gmail report for the Index & ETF Allocation Monitor.

Decision-first, modular card digest categorized by market (Domestic vs Overseas/QDII).
"""

from __future__ import annotations

import html
import io
import os
import re
import smtplib
import ssl
from collections.abc import Collection
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib import font_manager
import pandas as pd

from .config import REPO_ROOT


LABEL_ZH_MAP = {
    "csi300": "沪深300 (大盘蓝筹)",
    "csi500": "中证500 (中盘成长)",
    "sp500": "标普500 (美股核心)",
}


def load_gmail_config(recipient_override: str | None = None) -> dict[str, str]:
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
    if recipient_override:
        recipients = [recipient_override.strip()]
    else:
        recipients = [item.strip() for item in re.split(r"[,;]", values.get("GMAIL_RECIPIENTS") or values.get("GMAIL_RECIPIENT", "")) if item.strip()]
    values["GMAIL_RECIPIENTS"] = ", ".join(recipients)
    missing = [key for key in ("GMAIL_SENDER", "GMAIL_APP_PASSWORD") if not values.get(key)]
    if not recipients:
        missing.append("GMAIL_RECIPIENTS")
    if missing:
        raise RuntimeError("Missing Gmail config for market_monitor: " + ", ".join(missing))
    return values


def _esc(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return html.escape(str(value))


def _fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{value:+.{digits}f}%"


def _configure_font() -> None:
    candidates = (
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.otf",
    )
    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            try:
                font_manager.fontManager.addfont(str(path))
                font_name = font_manager.FontProperties(fname=str(path)).get_name()
                plt.rcParams["font.sans-serif"] = [font_name, "DejaVu Sans", "sans-serif"]
                plt.rcParams["font.family"] = font_name
                break
            except Exception:
                pass
    plt.rcParams["axes.unicode_minus"] = False


def generate_sparkline_chart(
    df_prices: pd.DataFrame,
    exposure_id: str,
    title: str,
    color: str = "#2563eb",
    days: int = 60,
) -> bytes | None:
    _configure_font()
    if df_prices is None or df_prices.empty or "exposure_id" not in df_prices.columns:
        return None
    series = df_prices[df_prices["exposure_id"] == exposure_id].sort_values("date").copy()
    if series.empty:
        return None
    # Compute the moving average on the full series, then cut the window. Doing
    # it the other way round leaves the first 19 of the plotted days without an
    # MA -- a third of a 60-day chart with no line on it.
    series["ma20"] = series["close"].rolling(20).mean()
    sub = series.tail(days)
    if len(sub) < 5:
        return None
    sub = sub.copy()
    sub["date"] = pd.to_datetime(sub["date"])

    fig, ax = plt.subplots(figsize=(6.0, 2.1), dpi=160)
    fig.patch.set_facecolor("#ffffff")
    ax.set_facecolor("#ffffff")

    ax.plot(sub["date"], sub["close"], color=color, linewidth=1.8, label="收盘价")
    ax.plot(sub["date"], sub["ma20"], color="#f59e0b", linewidth=1.2, linestyle="--", label="20日均线")

    min_val = sub["close"].min() * 0.99
    ax.fill_between(sub["date"], min_val, sub["close"], color=color, alpha=0.05)

    ax.set_title(title, fontsize=10, fontweight="bold", color="#0f172a", pad=6, loc="left")
    ax.grid(True, color="#f1f5f9", linestyle="-", linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#e2e8f0")
    ax.spines["bottom"].set_color("#e2e8f0")
    ax.tick_params(axis="both", labelsize=7.5, colors="#64748b")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.legend(loc="upper left", fontsize=7.5, frameon=False, ncol=2)

    last_row = sub.iloc[-1]
    ret_pct = ((last_row["close"] / sub.iloc[0]["close"]) - 1) * 100
    ret_sign = "+" if ret_pct > 0 else ""
    ret_color = "#16a34a" if ret_pct > 0 else "#dc2626"
    ax.annotate(
        f"{last_row['close']:.1f} ({ret_sign}{ret_pct:.1f}%)",
        xy=(last_row["date"], last_row["close"]),
        xytext=(6, 0),
        textcoords="offset points",
        fontsize=8,
        fontweight="bold",
        color=ret_color,
        va="center",
        bbox=dict(boxstyle="round,pad=0.2", facecolor="#f8fafc", edgecolor="#cbd5e1", alpha=0.9),
    )

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=160, facecolor="#ffffff")
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()


# Kept as a private alias so existing callers do not break.
_generate_sparkline_chart = generate_sparkline_chart


def _get_tech_summary(tech_df: pd.DataFrame, exposure_id: str) -> dict[str, str]:
    # Same degraded-run guard as _render_etf_card: a technicals frame that is
    # missing the key column must read as "no data yet", not raise.
    if tech_df is None or tech_df.empty or "exposure_id" not in tech_df.columns:
        return {"ma_status": "数据更新中", "rsi_status": "中性"}
    row = tech_df[tech_df["exposure_id"] == exposure_id]
    if row.empty:
        return {"ma_status": "数据更新中", "rsi_status": "中性"}
    r = row.iloc[0]
    ma20 = r.get("ma20_pct")
    rsi = r.get("rsi")
    
    if pd.isna(ma20):
        ma_str = "震荡整理"
    elif float(ma20) > 1.0:
        ma_str = f"强势站上20日线 ({ma20:+.1f}%)"
    elif float(ma20) < -1.0:
        ma_str = f"处于20日线下方承压 ({ma20:+.1f}%)"
    else:
        ma_str = f"贴近20日线窄幅震荡 ({ma20:+.1f}%)"
        
    if pd.isna(rsi):
        rsi_str = "中性"
    elif float(rsi) >= 70:
        rsi_str = f"情绪过热预警 (RSI: {rsi:.0f})"
    elif float(rsi) <= 35:
        rsi_str = f"超卖低估区间 (RSI: {rsi:.0f})"
    else:
        rsi_str = f"动量中性温和 (RSI: {rsi:.0f})"
        
    return {"ma_status": ma_str, "rsi_status": rsi_str}


_NO_WRAPPER_DATA = '<div style="color:#94a3b8;font-size:12px;">暂无该指数的跟踪标的数据</div>'


def _render_etf_card(w_df: pd.DataFrame, exposure_id: str, is_overseas: bool = False) -> str:
    # A run with no wrapper metrics at all -- the pre-open window where the
    # spot feed publishes no IOPV, or a failed spot fetch -- hands this an
    # empty frame with no columns. That is exactly when the digest is most
    # worth sending, so it degrades to a placeholder instead of raising and
    # taking the whole email down through the caller's best-effort except.
    if w_df is None or w_df.empty or "exposure_id" not in w_df.columns:
        return _NO_WRAPPER_DATA
    cohort = w_df[w_df["exposure_id"] == exposure_id].copy()
    if cohort.empty:
        return _NO_WRAPPER_DATA

    # Sort: Domestic by peer_rank, Overseas by premium_pct ascending. Either
    # column can be absent on a partial run; an unsorted card still informs.
    sort_column = "premium_pct" if is_overseas else "peer_rank"
    if sort_column in cohort.columns:
        cohort = cohort.sort_values(sort_column, ascending=True)


    rows = []
    min_prem = cohort["premium_pct"].min() if "premium_pct" in cohort.columns else 0.0

    for idx, (_, w) in enumerate(cohort.iterrows()):
        ticker = _esc(w.get("ticker"))
        fund_name = _esc(w.get("fund_name"))
        prem = w.get("premium_pct")
        fee = w.get("management_fee")
        custody_fee = w.get("custody_fee")
        
        # Fee display
        fee_val = (float(fee) if pd.notna(fee) else 0.0) + (float(custody_fee) if pd.notna(custody_fee) else 0.0)
        fee_str = f"{fee_val*100:.2f}%/年" if fee_val > 0 else (f"{float(fee)*100:.2f}%/年" if pd.notna(fee) else "—")

        prem_color = "#16a34a" if pd.notna(prem) and float(prem) < 0 else ("#dc2626" if pd.notna(prem) and float(prem) > 0.5 else "#334155")
        
        if not is_overseas:
            # Domestic A-share ETF Logic
            if idx == 0:
                badge = '<span style="background:#dcfce7;color:#15803d;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700;">🏆 综合首选</span>'
            else:
                badge = '<span style="background:#f1f5f9;color:#64748b;padding:2px 6px;border-radius:4px;font-size:11px;">备选标的</span>'
            detail_str = f'折溢价: <b style="color:{prem_color};font-family:monospace;">{_fmt_pct(prem)}</b> · 费率: <span style="color:#64748b;">{fee_str}</span>'
        else:
            # Overseas QDII ETF Logic (Within-Cohort comparison)
            diff_from_min = float(prem) - min_prem if pd.notna(prem) else 0.0
            if idx == 0:
                badge = '<span style="background:#e0f2fe;color:#0369a1;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700;">同类溢价最低</span>'
                rel_note = " (同类最优)"
            else:
                badge = '<span style="background:#fee2e2;color:#b91c1c;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700;">同类溢价偏高</span>'
                rel_note = f" (比最低高 +{diff_from_min:.2f}%)" if diff_from_min > 0.01 else ""

            detail_str = f'溢价率: <b style="color:{prem_color};font-family:monospace;">{_fmt_pct(prem)}</b><span style="font-size:11px;color:#64748b;">{rel_note}</span> · 费率: <span style="color:#64748b;">{fee_str}</span>'
            
        rows.append(
            f'<div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid #f1f5f9;font-size:12px;">'
            f'  <div>'
            f'    {badge} <b style="color:#0f172a;margin-left:4px;">{ticker}</b> <span style="color:#475569;">{fund_name}</span>'
            f'  </div>'
            f'  <div style="text-align:right;">{detail_str}</div>'
            f'</div>'
        )
    return "".join(rows)


def build_email_html(
    *,
    report_date: str,
    technicals: pd.DataFrame,
    regime: pd.DataFrame,
    wrappers: pd.DataFrame,
    charts: Collection[str] | None = None,
) -> str:
    """Render a clean, modular, decision-first email digest."""
    csi500_tech = _get_tech_summary(technicals, "csi500")
    csi300_tech = _get_tech_summary(technicals, "csi300")
    sp500_tech = _get_tech_summary(technicals, "sp500")

    # Chart embeds if available
    # Emit a cid: reference only for a chart that was actually attached. A
    # single boolean would render every slot as soon as one chart existed, and
    # the missing ones would arrive as broken images.
    available = set(charts or ())

    def _chart_html(chart_id: str, alt: str) -> str:
        if chart_id not in available:
            return ""
        return (
            '<div style="margin:8px 0 12px;text-align:center;">'
            f'<img src="cid:{chart_id}" alt="{alt}" '
            'style="width:100%;max-width:540px;height:auto;'
            'border-radius:6px;border:1px solid #e2e8f0;" /></div>'
        )

    chart_csi300_html = _chart_html("chart_csi300", "沪深300走势")
    chart_csi500_html = _chart_html("chart_csi500", "中证500走势")
    chart_sp500_html = _chart_html("chart_sp500", "标普500走势")

    csi500_etfs = _render_etf_card(wrappers, "csi500", is_overseas=False)
    csi300_etfs = _render_etf_card(wrappers, "csi300", is_overseas=False)
    sp500_etfs = _render_etf_card(wrappers, "sp500", is_overseas=True)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>指数与 ETF 战术配置快报</title>
</head>
<body style="margin:0;padding:12px;background-color:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;">
  <table width="100%" border="0" cellspacing="0" cellpadding="0">
    <tr>
      <td align="center">
        <div style="max-width:580px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 6px rgba(0,0,0,0.06);border:1px solid #e2e8f0;text-align:left;">

          <!-- Header -->
          <div style="background:#0f172a;padding:18px 20px;color:#ffffff;">
            <div style="font-size:11px;font-weight:700;color:#94a3b8;letter-spacing:1px;">Asia Markets Monitor · 战术决策</div>
            <div style="font-size:18px;font-weight:700;margin-top:3px;color:#ffffff;">指数与 ETF 核心配置快报</div>
            <div style="font-size:12px;color:#94a3b8;margin-top:2px;">{report_date} · 聚焦 沪深300 / 中证500 / 标普500</div>
          </div>

          <div style="padding:16px 18px;">

            <!-- Summary Takeaways -->
            <div style="background:#f0fdf4;border-left:4px solid #16a34a;padding:12px 14px;border-radius:6px;margin-bottom:20px;">
              <div style="font-size:12px;font-weight:700;color:#166534;margin-bottom:4px;">💡 今日核心配置摘要</div>
              <div style="font-size:12px;color:#1e293b;line-height:1.6;">
                • <b>国内 A 股</b>：中盘风格更具弹性，<b>510500 (南方中证500)</b> 处于小幅折价区间，性价比最佳。<br>
                • <b>海外跨境</b>：标普500 维持高位整理；国内挂钩 ETF 整体处于高溢价状态，同类中优先选择溢价相对较低的标的，避免追高。
              </div>
            </div>

            <!-- Card 1: CSI 500 -->
            <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:14px 16px;margin-bottom:18px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                <div style="font-size:14px;font-weight:700;color:#0f172a;">🇨🇳 中证500 (CSI 500)</div>
                <div style="font-size:11px;color:#64748b;">中盘成长 · 弹性主线</div>
              </div>
              <div style="font-size:12px;color:#475569;margin-bottom:6px;">
                趋势状态：<b>{csi500_tech['ma_status']}</b> · {csi500_tech['rsi_status']}
              </div>
              {chart_csi500_html}
              <div style="background:#f8fafc;padding:8px 12px;border-radius:6px;margin-top:6px;">
                <div style="font-size:11px;font-weight:700;color:#64748b;margin-bottom:4px;">🎯 优选跟踪 ETF</div>
                {csi500_etfs}
              </div>
            </div>

            <!-- Card 2: CSI 300 -->
            <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:14px 16px;margin-bottom:18px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                <div style="font-size:14px;font-weight:700;color:#0f172a;">🇨🇳 沪深300 (CSI 300)</div>
                <div style="font-size:11px;color:#64748b;">大盘蓝筹 · 核心底仓</div>
              </div>
              <div style="font-size:12px;color:#475569;margin-bottom:6px;">
                趋势状态：<b>{csi300_tech['ma_status']}</b> · {csi300_tech['rsi_status']}
              </div>
              {chart_csi300_html}
              <div style="background:#f8fafc;padding:8px 12px;border-radius:6px;margin-top:6px;">
                <div style="font-size:11px;font-weight:700;color:#64748b;margin-bottom:4px;">🎯 优选跟踪 ETF</div>
                {csi300_etfs}
              </div>
            </div>

            <!-- Card 3: S&P 500 -->
            <div style="background:#ffffff;border:1px solid #e2e8f0;border-radius:8px;padding:14px 16px;margin-bottom:14px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                <div style="font-size:14px;font-weight:700;color:#0f172a;">🇺🇸 标普500 (S&P 500)</div>
                <div style="font-size:11px;color:#64748b;">美股核心 · 跨境 QDII</div>
              </div>
              <div style="font-size:12px;color:#475569;margin-bottom:6px;">
                趋势状态：<b>{sp500_tech['ma_status']}</b> · {sp500_tech['rsi_status']}
              </div>
              {chart_sp500_html}
              <div style="background:#fef2f2;border:1px solid #fee2e2;padding:8px 10px;border-radius:6px;margin-bottom:8px;font-size:11px;color:#991b1b;line-height:1.4;">
                ⚠️ <b>跨境溢价提示</b>：QDII 额度受限导致二级市场普遍存在 +8%~+11% 结构性高溢价。请勿与国内 A 股 ETF 混比，在同类中优选溢价相对较低者。
              </div>
              <div style="background:#f8fafc;padding:8px 12px;border-radius:6px;">
                <div style="font-size:11px;font-weight:700;color:#64748b;margin-bottom:4px;">🎯 挂钩 ETF 溢价横向对比</div>
                {sp500_etfs}
              </div>
            </div>

          </div>

          <!-- Footer -->
          <div style="background:#f8fafc;padding:12px 18px;border-top:1px solid #f1f5f9;font-size:11px;color:#94a3b8;line-height:1.4;">
            注：本快报由 Asia Markets 量化系统自动生成，数据仅供研究参考，不构成投资建议。
          </div>

        </div>
      </td>
    </tr>
  </table>
</body>
</html>"""


def send_report(
    *,
    subject: str,
    body_html: str,
    recipient_override: str | None = None,
    images: dict[str, bytes] | None = None,
) -> None:
    config = load_gmail_config(recipient_override=recipient_override)
    msg = EmailMessage()
    msg["From"] = config["GMAIL_SENDER"]
    msg["To"] = config["GMAIL_RECIPIENTS"]
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg.set_content("指数与 ETF 核心配置快报 (请启用 HTML 视图查看完整报告与走势图)")
    msg.add_alternative(body_html, subtype="html")

    if images:
        html_part = msg.get_payload()[-1]
        for cid, img_data in images.items():
            html_part.add_related(img_data, maintype="image", subtype="png", cid=f"<{cid}>", filename=f"{cid}.png")

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as smtp:
        smtp.login(config["GMAIL_SENDER"], config["GMAIL_APP_PASSWORD"])
        smtp.send_message(msg)
