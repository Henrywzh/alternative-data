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

from .config import (
    ALERT_CORE_EXPOSURES,
    ALERT_MA20_BAND_PCT,
    ALERT_RSI_OVERBOUGHT,
    ALERT_RSI_OVERSOLD,
    REPO_ROOT,
)
from .freshness import BLOCKING_FRESHNESS_STATUSES, freshness_note


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
    elif float(ma20) > ALERT_MA20_BAND_PCT:
        ma_str = f"强势站上20日线 ({ma20:+.1f}%)"
    elif float(ma20) < -ALERT_MA20_BAND_PCT:
        ma_str = f"处于20日线下方承压 ({ma20:+.1f}%)"
    else:
        ma_str = f"贴近20日线窄幅震荡 ({ma20:+.1f}%)"
        
    if pd.isna(rsi):
        rsi_str = "中性"
    elif float(rsi) >= ALERT_RSI_OVERBOUGHT:
        rsi_str = f"情绪过热预警 (RSI: {rsi:.0f})"
    elif float(rsi) <= ALERT_RSI_OVERSOLD:
        rsi_str = f"超卖低估区间 (RSI: {rsi:.0f})"
    else:
        rsi_str = f"动量中性温和 (RSI: {rsi:.0f})"
        
    return {"ma_status": ma_str, "rsi_status": rsi_str}


_NO_WRAPPER_DATA = '<div style="color:#94a3b8;font-size:12px;">暂无该指数的跟踪标的数据</div>'


def _current_quote_cohort(wrappers: pd.DataFrame, exposure_id: str) -> pd.DataFrame:
    """Return only rows eligible for a same-index current comparison."""
    if wrappers is None or wrappers.empty or "exposure_id" not in wrappers.columns:
        return pd.DataFrame()
    cohort = wrappers[wrappers["exposure_id"].eq(exposure_id)].copy()
    if cohort.empty:
        return cohort
    current = pd.Series(True, index=cohort.index)
    if "premium_pct" in cohort.columns:
        current &= pd.to_numeric(cohort["premium_pct"], errors="coerce").notna()
    if "quote_basis" in cohort.columns:
        current &= ~cohort["quote_basis"].astype(str).eq("last_close")
    if "quote_status" in cohort.columns:
        current &= cohort["quote_status"].fillna("").astype(str).eq("Fresh")
    return cohort.loc[current]


def _fee_display(row: pd.Series) -> str:
    management = pd.to_numeric(row.get("management_fee"), errors="coerce")
    custody = pd.to_numeric(row.get("custody_fee"), errors="coerce")
    total = sum(value for value in (management, custody) if pd.notna(value))
    return f"{float(total) * 100:.2f}%/年" if total else "费率暂无"


def _build_dynamic_summary(wrappers: pd.DataFrame) -> str:
    """Describe only same-index comparisons backed by current quote rows."""
    lines: list[str] = []
    for exposure_id in ALERT_CORE_EXPOSURES:
        cohort = _current_quote_cohort(wrappers, exposure_id)
        label = LABEL_ZH_MAP.get(exposure_id, exposure_id)
        if cohort.empty:
            lines.append(f"• <b>{_esc(label)}</b>：暂无经过当前报价验证的同类溢价比较。")
            continue
        ordered = cohort.assign(
            _premium=pd.to_numeric(cohort["premium_pct"], errors="coerce")
        ).sort_values("_premium")
        row = ordered.iloc[0]
        lines.append(
            f"• <b>{_esc(label)}</b>：同类最低溢价 "
            f"<b>{_esc(row.get('ticker'))} {_esc(row.get('fund_name'))}</b> "
            f"({_fmt_pct(row.get('premium_pct'))})，费率 {_esc(_fee_display(row))}。"
        )
    return "<br>".join(lines)


def _build_cross_border_note(wrappers: pd.DataFrame) -> str:
    cohort = _current_quote_cohort(wrappers, "sp500")
    if cohort.empty:
        return "⚠️ <b>跨境溢价提示</b>：当前没有经过源端时间验证的标普500挂钩 ETF 报价，暂不进行横向溢价判断。"
    premiums = pd.to_numeric(cohort["premium_pct"], errors="coerce").dropna()
    return (
        "ℹ️ <b>跨境溢价提示</b>：标普500挂钩 ETF 只在本组内比较；"
        f"当前 {len(premiums)} 个有效报价，溢价范围 {_fmt_pct(premiums.min())} 至 {_fmt_pct(premiums.max())}。"
        "不与 A 股或其他指数的 ETF 混比。"
    )


def _freshness_warning(freshness: dict[str, object], *, mode: str = "close") -> str:
    """Summarize blocking regional/source freshness issues for the email."""
    issues: list[str] = []
    if mode == "intraday":
        # The midday run borrows the last persisted close instead of computing
        # a half-session bar, and its own gate deliberately only blocks on the
        # live quote -- a stale close must never stop the quote mail. But the
        # per-region and per-source records below are produced by the close
        # pipeline only, so without this the intraday banner could never fire
        # and an arbitrarily old borrowed close read as if it were yesterday's.
        close = freshness.get("daily_close", {}) or {}
        if str(close.get("status")) in BLOCKING_FRESHNESS_STATUSES:
            issues.append(f"借用的收盘技术面: {freshness_note(close, language='zh')}")
    for scope, records in (
        ("区域", freshness.get("daily_close_by_region", {}) or {}),
        ("来源", freshness.get("daily_close_by_source", {}) or {}),
    ):
        for group, record in sorted(records.items()):
            if str(record.get("status")) in BLOCKING_FRESHNESS_STATUSES:
                issues.append(f"{scope} {group}: {freshness_note(record, language='zh')}")
    regressions = freshness.get("coverage_regressions") or []
    if regressions:
        issues.append("历史覆盖回退: " + "; ".join(str(item) for item in regressions[:4]))
    return "；".join(issues)


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


    # Only current quote rows may define a same-index premium comparison. A
    # last-close fallback is retained for auditability, but it must not become
    # the "lowest premium" anchor for the live QDII cohort.
    quote_is_current = pd.Series(True, index=cohort.index)
    if "premium_pct" in cohort.columns:
        quote_is_current &= pd.to_numeric(cohort["premium_pct"], errors="coerce").notna()
    if "quote_basis" in cohort.columns:
        quote_is_current &= ~cohort["quote_basis"].astype(str).eq("last_close")
    if "quote_status" in cohort.columns:
        quote_is_current &= cohort["quote_status"].fillna("").astype(str).isin({"", "Fresh"})
    current_cohort = cohort.loc[quote_is_current]

    rows = []
    min_prem = current_cohort["premium_pct"].min() if "premium_pct" in current_cohort.columns and not current_cohort.empty else 0.0
    live_seen = 0

    for idx, (_, w) in enumerate(cohort.iterrows()):
        ticker = _esc(w.get("ticker"))
        fund_name = _esc(w.get("fund_name"))
        prem = w.get("premium_pct")
        fee = w.get("management_fee")
        custody_fee = w.get("custody_fee")
        quote_basis = str(w.get("quote_basis") or "intraday_quote")
        quote_status = str(w.get("quote_status") or "Fresh")
        quote_ok = bool(quote_is_current.iloc[idx])
        displayable_quote = (
            pd.notna(prem)
            and quote_basis != "last_close"
            and quote_status in {"Fresh", "Unverified"}
        )
        
        # Fee display
        fee_val = (float(fee) if pd.notna(fee) else 0.0) + (float(custody_fee) if pd.notna(custody_fee) else 0.0)
        fee_str = f"{fee_val*100:.2f}%/年" if fee_val > 0 else (f"{float(fee)*100:.2f}%/年" if pd.notna(fee) else "—")

        prem_color = "#16a34a" if pd.notna(prem) and float(prem) < 0 else ("#dc2626" if pd.notna(prem) and float(prem) > 0.5 else "#334155")
        
        if not quote_ok:
            if quote_basis == "last_close":
                badge = '<span style="background:#fef3c7;color:#92400e;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700;">上一收盘 · 非实时</span>'
                detail_str = f'折溢价: <b style="color:#92400e;font-family:monospace;">{_fmt_pct(prem)}</b> · 费率: <span style="color:#64748b;">{fee_str}</span>'
            elif quote_status == "Stale":
                badge = '<span style="background:#fee2e2;color:#b91c1c;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700;">报价已过期</span>'
                detail_str = f'折溢价: <b style="color:#b91c1c;font-family:monospace;">{_fmt_pct(prem)}</b> · 费率: <span style="color:#64748b;">{fee_str}</span>'
            elif quote_status == "Unverified" and displayable_quote:
                badge = '<span style="background:#fef3c7;color:#92400e;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700;">已抓取 · 时间未验证</span>'
                detail_str = f'折溢价: <b style="color:#92400e;font-family:monospace;">{_fmt_pct(prem)}</b> · 费率: <span style="color:#64748b;">{fee_str}</span>'
            else:
                badge = '<span style="background:#f1f5f9;color:#64748b;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700;">暂无最新报价</span>'
                detail_str = f'折溢价: <b style="color:#64748b;font-family:monospace;">—</b> · 费率: <span style="color:#64748b;">{fee_str}</span>'
        elif not is_overseas:
            # Domestic A-share ETF Logic
            if live_seen == 0:
                badge = '<span style="background:#dcfce7;color:#15803d;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700;">🏆 综合首选</span>'
            else:
                badge = '<span style="background:#f1f5f9;color:#64748b;padding:2px 6px;border-radius:4px;font-size:11px;">备选标的</span>'
            detail_str = f'折溢价: <b style="color:{prem_color};font-family:monospace;">{_fmt_pct(prem)}</b> · 费率: <span style="color:#64748b;">{fee_str}</span>'
            live_seen += 1
        else:
            # Overseas QDII ETF Logic (Within-Cohort comparison)
            diff_from_min = float(prem) - min_prem if pd.notna(prem) else 0.0
            if live_seen == 0:
                badge = '<span style="background:#e0f2fe;color:#0369a1;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700;">同类溢价最低</span>'
                rel_note = " (同类最优)"
            else:
                badge = '<span style="background:#fee2e2;color:#b91c1c;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:700;">同类溢价偏高</span>'
                rel_note = f" (比最低高 +{diff_from_min:.2f}%)" if diff_from_min > 0.01 else ""

            detail_str = f'溢价率: <b style="color:{prem_color};font-family:monospace;">{_fmt_pct(prem)}</b><span style="font-size:11px;color:#64748b;">{rel_note}</span> · 费率: <span style="color:#64748b;">{fee_str}</span>'
            live_seen += 1
            
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
    mode: str = "close",
    freshness: dict[str, object] | None = None,
    alert_reason: Collection[str] | None = None,
) -> str:
    """Render a clean, modular, decision-first email digest."""
    freshness = freshness or {}
    is_intraday = mode == "intraday"
    report_title = "指数与 ETF 午盘实时快报" if is_intraday else "指数与 ETF 核心配置快报"
    # Do not assert "上一交易日" for the borrowed close: the midday run reads
    # whatever the close pipeline last persisted, which after a failed or
    # skipped daily run can be several sessions old. Name the observed date.
    borrowed_close_date = (freshness.get("daily_close", {}) or {}).get("observation_date")
    report_subtitle = (
        (
            f"盘中 ETF 行情；技术面沿用 {borrowed_close_date} 收盘，不重算半日 K 线"
            if borrowed_close_date
            else "盘中 ETF 行情；技术面沿用最近一次已持久化的收盘，不重算半日 K 线"
        )
        if is_intraday
        else "收盘数据；各区块按自身来源的最新观察日展示"
    )
    quote_note = freshness_note(freshness.get("quote", {}), language="zh") if freshness.get("quote") else "实时行情状态未提供"
    close_note = freshness_note(freshness.get("daily_close", {}), language="zh") if freshness.get("daily_close") else "收盘技术面状态未提供"
    freshness_warning = _freshness_warning(freshness, mode=mode)
    southbound_note = (
        freshness_note(freshness.get("southbound", {}), language="zh")
        if freshness.get("southbound")
        else None
    )
    fetch_errors = freshness.get("fetch_errors") or []
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
    summary_html = _build_dynamic_summary(wrappers)
    cross_border_note = _build_cross_border_note(wrappers)
    alert_reason_html = ""
    if alert_reason:
        reason_rows = "<br>".join(f"• {_esc(line)}" for line in alert_reason)
        alert_reason_html = f"""
            <div style="background:#fff7ed;border-left:4px solid #f97316;padding:10px 12px;border-radius:6px;margin-bottom:16px;font-size:12px;color:#9a3412;line-height:1.6;">
              <div style="font-weight:700;margin-bottom:3px;">🔔 本次提醒原因</div>
              <div>{reason_rows}</div>
            </div>
        """

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(report_title)}</title>
</head>
<body style="margin:0;padding:12px;background-color:#f8fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;">
  <table width="100%" border="0" cellspacing="0" cellpadding="0">
    <tr>
      <td align="center">
        <div style="max-width:580px;width:100%;background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 6px rgba(0,0,0,0.06);border:1px solid #e2e8f0;text-align:left;">

          <!-- Header -->
          <div style="background:#0f172a;padding:18px 20px;color:#ffffff;">
            <div style="font-size:11px;font-weight:700;color:#94a3b8;letter-spacing:1px;">Asia Markets Monitor · 战术决策</div>
            <div style="font-size:18px;font-weight:700;margin-top:3px;color:#ffffff;">{_esc(report_title)}</div>
            <div style="font-size:12px;color:#94a3b8;margin-top:2px;">{_esc(report_date)} · 聚焦 沪深300 / 中证500 / 标普500</div>
          </div>

          <div style="padding:16px 18px;">

            <div style="background:#eff6ff;border-left:4px solid #2563eb;padding:10px 12px;border-radius:6px;margin-bottom:16px;font-size:11px;color:#1e3a8a;line-height:1.55;">
              <b>数据口径</b>：{_esc(report_subtitle)}<br>
              ETF 行情：{_esc(quote_note)}<br>
              技术面：{_esc(close_note)}
              {('<br>南向资金：' + _esc(southbound_note)) if southbound_note else ''}
              {('<br><span style="color:#b91c1c;"><b>区域/来源数据警告</b>：' + _esc(freshness_warning) + '</span>') if freshness_warning else ''}
              {('<br><span style="color:#b91c1c;"><b>数据警告</b>：' + _esc(str(len(fetch_errors))) + ' 个数据源请求失败，缺失值未用旧数据补齐。</span>') if fetch_errors else ''}
            </div>

            {alert_reason_html}

            <!-- Summary Takeaways -->
            <div style="background:#f0fdf4;border-left:4px solid #16a34a;padding:12px 14px;border-radius:6px;margin-bottom:20px;">
              <div style="font-size:12px;font-weight:700;color:#166534;margin-bottom:4px;">💡 今日核心配置摘要</div>
              <div style="font-size:12px;color:#1e293b;line-height:1.6;">
                {summary_html}
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
                {cross_border_note}
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
