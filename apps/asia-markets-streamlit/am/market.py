"""ETF monitor: shared frames, signals and index detail charts.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from .config import ETF_ACTIVITY_CNY_PER_YI, ETF_ACTIVITY_SHARES_PER_WAN, PALETTE

from .core import apply_line_hover, chart_theme, date_hover_format, date_tick_format, history_window, localize_coverage, section_heading, tr


def _market_price_frame(datasets: dict[str, Any]) -> pd.DataFrame:
    """Daily index closes from the artifact, typed and sorted."""
    rows = datasets.get("index_price_daily_tail", [])
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if not {"date", "close", "exposure_id"}.issubset(frame.columns):
        return pd.DataFrame()
    frame["_date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["_date", "close", "exposure_id"])
    frame["exposure_id"] = frame["exposure_id"].astype(str).str.strip()
    frame = frame[frame["exposure_id"].ne("") & frame["exposure_id"].ne("nan") & frame["close"].gt(0)]
    return (
        frame.drop_duplicates(["exposure_id", "_date"], keep="last")
        .sort_values(["exposure_id", "_date"])
        .reset_index(drop=True)
    )


def _market_label(technical_row: pd.Series, language: str) -> str:
    """Return the bilingual label for an exposure row."""
    if language == "zh":
        zh = technical_row.get("label_zh")
        if pd.notna(zh) and str(zh).strip():
            return str(zh)
    return str(technical_row.get("label", ""))


def _market_ticker_series(values: pd.Series) -> pd.Series:
    """Normalize exchange tickers without turning missing values into IDs."""
    normalized = values.astype("string").str.strip()
    missing = normalized.isna() | normalized.isin({"", "nan", "none", "<na>"})
    normalized = normalized.mask(missing)
    return normalized.str.replace(r"\.0$", "", regex=True).str.zfill(6)


def _market_etf_price_frame(datasets: dict[str, Any]) -> pd.DataFrame:
    """Daily ETF closes from the artifact, typed and sorted."""
    rows = datasets.get("etf_price_daily_tail", [])
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if not {"date", "close", "ticker"}.issubset(frame.columns):
        return pd.DataFrame()
    frame["_date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["_date", "close", "ticker"])
    frame["ticker"] = _market_ticker_series(frame["ticker"])
    frame = frame.dropna(subset=["ticker"])
    frame = frame[frame["close"].gt(0)]
    return (
        frame.drop_duplicates(["ticker", "_date"], keep="last")
        .sort_values(["ticker", "_date"])
        .reset_index(drop=True)
    )


def _market_pair_history_frame(datasets: dict[str, Any]) -> pd.DataFrame:
    """Relative-pair ratio history from the artifact, typed and sorted."""
    rows = datasets.get("relative_pair_history", [])
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if not {"date", "ratio", "pair_id"}.issubset(frame.columns):
        return pd.DataFrame()
    frame["_date"] = pd.to_datetime(frame["date"], errors="coerce")
    for column in ("ratio", "ratio_ma", "zscore"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["_date", "ratio", "pair_id"])
    frame["pair_id"] = frame["pair_id"].astype("string").str.strip()
    frame = frame.dropna(subset=["pair_id"])
    frame = frame[frame["pair_id"].ne("")]
    frame = frame[frame["ratio"].gt(0)]
    return (
        frame.drop_duplicates(["pair_id", "_date"], keep="last")
        .sort_values(["pair_id", "_date"])
        .reset_index(drop=True)
    )


def _pair_label(row: pd.Series, language: str) -> str:
    if language == "zh":
        zh = row.get("label_zh")
        if pd.notna(zh) and str(zh).strip():
            return str(zh)
    return str(row.get("label", row.get("pair_id", "")))


def _market_exposure_label_map(language: str) -> dict[str, str]:
    """Map stable exposure ids to reader-facing labels for the UI."""
    from market_monitor.config import EXPOSURES

    labels: dict[str, str] = {}
    for spec in EXPOSURES:
        exposure_id = str(spec.get("exposure_id") or "")
        if not exposure_id:
            continue
        field = "label_zh" if language == "zh" else "label"
        labels[exposure_id] = str(spec.get(field) or spec.get("label") or exposure_id)
    return labels


def _format_pair_legs(
    row: pd.Series,
    language: str,
    label_map: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Return display labels for a pair's numerator and denominator."""
    labels = label_map or _market_exposure_label_map(language)

    def _missing(value: Any) -> bool:
        try:
            return bool(pd.isna(value))
        except (TypeError, ValueError):
            return False

    def _value(primary: str, fallback: str) -> str:
        value = row.get(primary)
        if value is None or _missing(value):
            value = row.get(fallback)
        if value is None or _missing(value):
            return ""
        return str(value).strip()

    def _format(value: str) -> str:
        if not value or value.casefold() in {"nan", "none"}:
            return "—"
        members = [member.strip() for member in value.split("+") if member.strip()]
        return " + ".join(labels.get(member, member) for member in members) or "—"

    return (
        _format(_value("left", "numerator_id")),
        _format(_value("right", "denominator_id")),
    )


REGION_NAMES = {
    "China": ("China A-shares", "A股"),
    "HK": ("Hong Kong", "港股"),
    "US": ("United States", "美股"),
    "Cross": ("Cross-region", "跨区域"),
}


def render_relative_regime(
    summary: pd.DataFrame,
    history: pd.DataFrame,
    language: str,
    history_window_name: str,
    key_prefix: str = "market",
) -> None:
    """One pair at a time: the ratio, its 60D trend, and its z-score.

    Replaces a bar chart of one z-score per pair. That chart could not say
    whether -0.3 was the end of a year-long slide or the end of a bounce,
    which is most of what a relative-strength reading is for.
    """
    frame = summary.copy()
    if "pair_id" not in frame.columns or "region" not in frame.columns:
        st.info(
            tr(
                language,
                "Relative-pair summary is unavailable in the current snapshot.",
                "当前快照没有可用的相对配对摘要。",
            )
        )
        return
    frame["_label"] = frame.apply(lambda row: _pair_label(row, language), axis=1)
    frame["region"] = frame["region"].astype("string").str.strip()
    regions = [r for r in ("China", "HK", "US", "Cross") if r in set(frame["region"].dropna())]
    if not regions:
        regions = sorted(set(frame["region"].dropna()))

    if len(regions) > 1:
        if hasattr(st, "segmented_control"):
            region_choice = st.segmented_control(
                tr(language, "Market", "市场"),
                regions,
                default=regions[0] if regions else None,
                key=f"{key_prefix}_pair_region",
                format_func=lambda r: tr(language, *REGION_NAMES.get(r, (r, r))),
                label_visibility="collapsed",
            ) or (regions[0] if regions else None)
        elif hasattr(st, "pills"):
            region_choice = st.pills(
                tr(language, "Market", "市场"),
                regions,
                default=regions[0] if regions else None,
                key=f"{key_prefix}_pair_region",
                format_func=lambda r: tr(language, *REGION_NAMES.get(r, (r, r))),
                label_visibility="collapsed",
            ) or (regions[0] if regions else None)
        else:
            region_choice = st.radio(
                tr(language, "Market", "市场"),
                regions,
                horizontal=True,
                key=f"{key_prefix}_pair_region",
                format_func=lambda r: tr(language, *REGION_NAMES.get(r, (r, r))),
            )
    else:
        region_choice = regions[0] if regions else None

    cohort = frame[frame["region"].eq(region_choice)] if region_choice else frame
    if cohort.empty:
        return
    pair_label_map = _market_exposure_label_map(language)

    # Scoreboard first: every pair in the region at a glance, then one chart.
    columns = st.columns(min(4, len(cohort)))
    for column, (_, row) in zip(columns, cohort.iterrows()):
        zscore = row.get("zscore")
        display = "—" if zscore is None or pd.isna(zscore) else f"{float(zscore):+.2f}"
        trend = row.get("trend")
        delta = None if trend in (None, "") or pd.isna(trend) else (
            tr(language, "above 60D mean", "高于60日均值") if trend == "UP"
            else tr(language, "below 60D mean", "低于60日均值")
        )
        column.metric(
            row["_label"],
            display,
            delta,
            delta_color="normal" if trend == "UP" else ("inverse" if trend == "DOWN" else "off"),
            help=tr(language, "z-score of the ratio vs its trailing year", "比值相对过去一年的 z-score"),
        )

    selected_label = st.selectbox(
        tr(language, "Pair", "配对"),
        cohort["_label"].tolist(),
        key=f"{key_prefix}_pair_select",
    )
    row = cohort[cohort["_label"].eq(selected_label)].iloc[0]
    pair_id = str(row["pair_id"])
    series = (
        history[history["pair_id"].astype(str).eq(pair_id)]
        if history is not None
        and not history.empty
        and {"pair_id", "date", "ratio"}.issubset(history.columns)
        else pd.DataFrame()
    )
    if series.empty:
        st.info(tr(language, "No ratio history in the current snapshot.", "当前快照未包含该比值历史。"))
        return

    windowed, coverage = history_window(series, "date", history_window_name)
    coverage = localize_coverage(coverage, language)
    if windowed.empty:
        return

    has_z = "zscore" in windowed.columns and windowed["zscore"].notna().any()
    rows_count = 2 if has_z else 1
    fig = make_subplots(
        rows=rows_count, cols=1, shared_xaxes=True, vertical_spacing=0.06,
        row_heights=[0.68, 0.32] if has_z else [1.0],
    )
    fig.add_trace(
        go.Scatter(
            x=windowed["_date"], y=windowed["ratio"], mode="lines",
            name=tr(language, "Ratio", "比值"), line=dict(width=1.8),
            hovertemplate=tr(language, "Ratio", "比值") + ": %{y:.3f}<extra></extra>",
        ),
        row=1, col=1,
    )
    if "ratio_ma" in windowed.columns and windowed["ratio_ma"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=windowed["_date"], y=windowed["ratio_ma"], mode="lines",
                name=tr(language, "60D mean", "60日均值"), line=dict(width=1.0),
                hovertemplate=tr(language, "60D mean", "60日均值") + ": %{y:.3f}<extra></extra>",
            ),
            row=1, col=1,
        )
    fig.update_yaxes(title=tr(language, "Ratio (rebased)", "比值（归一）"), row=1, col=1)

    if has_z:
        fig.add_trace(
            go.Scatter(
                x=windowed["_date"], y=windowed["zscore"], mode="lines",
                name="z", line=dict(width=1.4),
                hovertemplate="z: %{y:+.2f}<extra></extra>",
            ),
            row=2, col=1,
        )
        fig.add_hrect(y0=1.0, y1=4.0, fillcolor="#10B981", opacity=0.06, line_width=0, row=2, col=1)
        fig.add_hrect(y0=-4.0, y1=-1.0, fillcolor="#EF4444", opacity=0.06, line_width=0, row=2, col=1)
        for level in (-1.0, 0.0, 1.0):
            fig.add_hline(y=level, line_dash="dot", line_color="#D1D5DB", line_width=0.5, row=2, col=1)
        fig.update_yaxes(title=tr(language, "z-score (1Y)", "z-score（1年）"), row=2, col=1)

    tick_format = date_tick_format(windowed["_date"])
    fig.update_xaxes(
        title=None, tickformat=tick_format,
        hoverformat=date_hover_format(windowed["_date"]),
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikethickness=1, spikedash="dot", spikecolor="#9CA3AF",
    )
    fig.update_layout(hovermode="x unified", hoverlabel=dict(namelength=-1),
                      spikedistance=-1, hoverdistance=100)

    left, right = _format_pair_legs(row, language, pair_label_map)
    st.markdown(
        f'<div class="am-chart-title">{escape(selected_label)} — '
        f'{escape(left)} / {escape(right)}</div>',
        unsafe_allow_html=True,
    )
    regime_text = str(row.get("regime_zh" if language == "zh" else "regime", ""))
    st.caption(
        " · ".join(
            part for part in (
                coverage,
                regime_text,
                tr(
                    language,
                    f"rising = {left} outperforming {right}",
                    f"上行 = {left} 跑赢 {right}",
                ),
            ) if part
        )
    )
    st.plotly_chart(
        chart_theme(fig, "number", date_axis=True, height=440 if has_z else 320),
        width="stretch",
        config={"displaylogo": False, "responsive": True},
        key=f"{key_prefix}_pair_history_chart",
    )

    display = cohort.copy()

    # 标签优化
    if language == "zh" and "label_zh" in display.columns:
        display["_label_show"] = display["label_zh"]
    else:
        display["_label_show"] = display.get("label", display.get("pair_id"))

    # 组合标的清晰展示: reader-facing labels, not persisted exposure ids.
    display["_pair_show"] = display.apply(
        lambda pair_row: " / ".join(_format_pair_legs(pair_row, language, pair_label_map)),
        axis=1,
    )

    # 当前比值与60日均线
    display["_ratio_show"] = display["ratio"].apply(lambda v: f"{float(v):.4f}" if pd.notna(v) else "—") if "ratio" in display.columns else "—"
    display["_ratio_ma_show"] = display["ratio_ma60"].apply(lambda v: f"{float(v):.4f}" if pd.notna(v) else "—") if "ratio_ma60" in display.columns else "—"

    # Z-Score 格式化
    display["_zscore_show"] = display["zscore"].apply(lambda v: f"{float(v):+.2f}σ" if pd.notna(v) else "—") if "zscore" in display.columns else "—"

    # 动量趋势
    trend_map = {"UP": "▲ 向上占优", "DOWN": "▼ 向下转弱"} if language == "zh" else {"UP": "▲ Bullish", "DOWN": "▼ Bearish"}
    display["_trend_show"] = display["trend"].map(trend_map).fillna(display.get("trend", "—")) if "trend" in display.columns else "—"

    # 当前强弱状态说明
    if language == "zh" and "regime_zh" in display.columns:
        display["_regime_show"] = display["regime_zh"]
    else:
        display["_regime_show"] = display.get("regime", "—")

    col_map_reg_zh = {
        "_label_show": "配置风格对",
        "_pair_show": "底层组合 (分子/分母)",
        "_ratio_show": "当前比值",
        "_ratio_ma_show": "60日均线",
        "_zscore_show": "1年Z-Score",
        "_trend_show": "动量趋势",
        "_regime_show": "相对强弱状态",
    }
    col_map_reg_en = {
        "_label_show": "Style Pair",
        "_pair_show": "Basket (A/B)",
        "_ratio_show": "Ratio",
        "_ratio_ma_show": "60D MA",
        "_zscore_show": "1Y Z-Score",
        "_trend_show": "Trend",
        "_regime_show": "Regime",
    }
    mapping_reg = col_map_reg_zh if language == "zh" else col_map_reg_en
    final_reg_cols = [c for c in mapping_reg.keys() if c in display.columns]
    table_to_show_reg = display[final_reg_cols].rename(columns=mapping_reg)
    st.dataframe(table_to_show_reg, hide_index=True, width="stretch")


def _market_premium_history_frame(datasets: dict[str, Any]) -> pd.DataFrame:
    """Daily premium history from the artifact."""
    rows = datasets.get("premium_history", [])
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if not {"date", "premium_pct", "ticker"}.issubset(frame.columns):
        return pd.DataFrame()
    frame["_date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["premium_pct"] = pd.to_numeric(frame["premium_pct"], errors="coerce")
    frame["ticker"] = _market_ticker_series(frame["ticker"])
    frame = frame.dropna(subset=["_date", "premium_pct", "ticker"])
    return (
        frame.drop_duplicates(["ticker", "_date"], keep="last")
        .sort_values(["ticker", "_date"])
        .reset_index(drop=True)
    )


def _market_etf_activity_frame(datasets: dict[str, Any]) -> pd.DataFrame:
    """Official ETF share observations and NAV-backed flow estimates."""
    rows = datasets.get("etf_fund_activity_daily", [])
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    required = {"observation_date", "fund_id", "shares_outstanding"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    frame["_date"] = pd.to_datetime(frame["observation_date"], errors="coerce")
    frame["fund_id"] = _market_ticker_series(frame["fund_id"])
    for column in (
        "shares_outstanding",
        "shares_change",
        "observation_gap_days",
        "nav",
        "aum_nav_estimate_cny",
        "estimated_flow_cny",
        "flow_pct_aum",
    ):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if "shares_outstanding" in frame.columns:
        frame["shares_outstanding"] = pd.to_numeric(
            frame["shares_outstanding"], errors="coerce"
        )
    frame = frame.dropna(subset=["_date", "fund_id", "shares_outstanding"])
    frame = frame[frame["shares_outstanding"].gt(0)]
    return (
        frame.drop_duplicates(["fund_id", "_date"], keep="last")
        .sort_values(["fund_id", "_date"])
        .reset_index(drop=True)
    )


def _compute_rsi_series(close: pd.Series, window: int = 14) -> pd.Series:
    """Wilder RSI for a close series."""
    window = max(2, int(window))
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, float("nan"))
    rsi = 100.0 - 100.0 / (1.0 + rs)
    # A one-directional series is not missing information. The previous
    # implementation returned NaN whenever average loss was zero, which made
    # a perfectly valid rally look like an absent RSI panel.
    rsi = rsi.mask(avg_loss.eq(0.0) & avg_gain.gt(0.0), 100.0)
    rsi = rsi.mask(avg_loss.eq(0.0) & avg_gain.eq(0.0), 50.0)
    return rsi


def _format_observed_premium(value: Any, days: Any, language: str) -> str:
    """Format a premium together with the observations that support it."""
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    count = pd.to_numeric(pd.Series([days]), errors="coerce").iloc[0]
    if pd.isna(numeric) or pd.isna(count) or float(count) <= 0:
        return "—"
    count_int = int(count)
    suffix = f"（{count_int}日）" if language == "zh" else f" ({count_int}D)"
    return f"{float(numeric):+.2f}%{suffix}"


# A wrapper's raw premium can survive a stale snapshot for auditability. It is
# not a current reading, though, so the table must use the same display gate as
# the ranking and email paths. ``Unverified`` means the provider gave us a
# recently retrieved quote but no exchange observation timestamp; it may be
# shown with a status label, but it must not be treated as a verified signal.
DISPLAYABLE_WRAPPER_QUOTE_STATUSES = frozenset({"Fresh", "Unverified"})


def _displayable_wrapper_quote_mask(frame: pd.DataFrame) -> pd.Series:
    """Return rows whose premium is safe to show as a current quote."""
    if frame is None or frame.empty:
        return pd.Series(dtype=bool)
    mask = (
        pd.to_numeric(frame["premium_pct"], errors="coerce").notna()
        if "premium_pct" in frame.columns
        else pd.Series(False, index=frame.index)
    )
    if "quote_basis" in frame.columns:
        mask &= ~frame["quote_basis"].astype("string").str.casefold().eq("last_close")
    # A missing freshness field is deliberately not assumed to be current.
    # Rebuilt artifacts stamp it; an old artifact must not quietly resurrect a
    # stale premium merely because its JSON file is readable.
    if "quote_status" not in frame.columns:
        return pd.Series(False, index=frame.index)
    status = frame["quote_status"].astype("string").str.strip()
    return mask & status.str.casefold().isin(
        {value.casefold() for value in DISPLAYABLE_WRAPPER_QUOTE_STATUSES}
    )


def _wrapper_quote_status_label(row: pd.Series, language: str) -> str:
    """Reader-facing status for the premium/quote fields in one ETF row."""
    basis = str(row.get("quote_basis") or "").strip().casefold()
    status = str(row.get("quote_status") or "").strip()
    if basis == "last_close":
        return tr(language, "Previous close (not live)", "上一收盘（非实时）")
    status = status.title()
    labels = {
        "Fresh": ("Latest quote", "最新报价"),
        "Unverified": ("Fetched; time unverified", "已抓取；时间未验证"),
        "Stale": ("Quote expired", "报价已过期"),
        "Unavailable": ("No latest quote", "暂无最新报价"),
    }
    en, zh = labels.get(status, ("Quote status unknown", "报价状态未知"))
    return tr(language, en, zh)


def render_market_leadership_chart(
    prices: pd.DataFrame,
    label_by_exposure: dict[str, str],
    language: str,
    history_window_name: str,
    key_prefix: str = "market",
) -> None:
    """Every exposure rebased to 100, which is the only way to read leadership.

    Rebasing is anchored to the latest first-observation across the series, not
    to each series' own first point. CSI and S&P 500 histories start days apart
    and run on different trading calendars, so rebasing each to its own start
    would silently hand the later-starting series a different measurement
    period and read as performance.
    """
    windowed, coverage = history_window(prices, "date", history_window_name)
    coverage = localize_coverage(coverage, language)
    if windowed.empty:
        st.info(tr(language, "No rows are available for this selection.", "这个选择没有可用数据。"))
        return
    common_start = windowed.groupby("exposure_id")["_date"].min().max()
    aligned = windowed[windowed["_date"] >= common_start].copy()
    if aligned.empty:
        st.info(tr(language, "No overlapping history across exposures.", "各指数没有重叠的历史区间。"))
        return
    base = aligned.sort_values("_date").groupby("exposure_id")["close"].transform("first")
    aligned["_value"] = aligned["close"] / base * 100.0
    aligned["series"] = aligned["exposure_id"].map(label_by_exposure).fillna(aligned["exposure_id"])

    st.markdown(
        f'<div class="am-chart-title">{tr(language, "Relative Performance (rebased to 100)", "相对表现（归一至 100）")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        " · ".join(
            [
                tr(
                    language,
                    f"All exposures rebased at {common_start:%d %b %Y}, the first date every series covers.",
                    f"全部指数以 {common_start:%Y-%m-%d} 归一，该日期是所有序列共同覆盖的最早一天。",
                ),
                tr(
                    language,
                    "CN, HK and US sessions run on different calendars; lines are plotted on their own trading days.",
                    "中国内地、香港与美国的交易日历不同，各线按各自的交易日绘制。",
                ),
                coverage,
            ]
        )
    )
    fig = px.line(
        aligned.sort_values(["series", "_date"]),
        x="_date",
        y="_value",
        color="series",
        color_discrete_sequence=PALETTE,
        render_mode="svg",
    )
    fig.add_hline(y=100.0, line_dash="dot", line_color="#9CA3AF", line_width=1)
    fig.update_yaxes(title=tr(language, "Rebased level", "归一水平"))
    fig.update_xaxes(title=None, tickformat="%b %Y")
    apply_line_hover(fig, aligned, "number")
    st.plotly_chart(
        chart_theme(fig, "number", date_axis=True, height=420),
        width="stretch",
        config={"displaylogo": False, "responsive": True},
        key=f"{key_prefix}_leadership_chart",
    )


def render_market_ratio_chart(
    prices: pd.DataFrame,
    technicals: pd.DataFrame,
    language: str,
    history_window_name: str,
    key_prefix: str = "market",
) -> None:
    """Ratio of two exposures, A / B, with 20D and 60D means.

    ``key_prefix`` namespaces the two selectboxes. It used to be absent, and
    the keys were the literals "market_ratio_num"/"market_ratio_den" -- but
    every region tab calls this, and st.tabs evaluates all five tab bodies on
    every run, so putting a second tab into Ratio mode crashed the whole page
    with StreamlitDuplicateElementKey.

    The ratio is plotted raw. The docstring used to claim it was "rebased to
    its own first value", which no line of this function did.
    """
    if (
        technicals is None
        or technicals.empty
        or "exposure_id" not in technicals.columns
        or prices is None
        or prices.empty
        or not {"exposure_id", "_date", "close"}.issubset(prices.columns)
    ):
        return

    labels = {}
    for _, row in technicals.iterrows():
        eid = str(row["exposure_id"])
        labels[eid] = _market_label(row, language) or eid

    eids = sorted(labels.keys() & set(prices["exposure_id"].astype(str)))
    if len(eids) < 2:
        st.info(
            tr(
                language,
                "At least two indices with overlapping price history are required for a ratio.",
                "比值视图至少需要两个有重叠价格历史的指数。",
            )
        )
        return
    col1, col2 = st.columns(2)
    with col1:
        numerator = st.selectbox(
            tr(language, "Numerator (A)", "分子 (A)"),
            eids,
            index=eids.index("csi1000") if "csi1000" in eids else 0,
            key=f"{key_prefix}_ratio_num",
            format_func=lambda e: labels.get(e, e),
        )
    with col2:
        denominator = st.selectbox(
            tr(language, "Denominator (B)", "分母 (B)"),
            eids,
            index=eids.index("csi300") if "csi300" in eids else min(1, len(eids) - 1),
            key=f"{key_prefix}_ratio_den",
            format_func=lambda e: labels.get(e, e),
        )
    if numerator == denominator:
        st.caption(tr(language, "Select two different indices to see their ratio.", "选择两个不同指数以查看比值。"))
        return

    left = prices[prices["exposure_id"].astype(str).eq(str(numerator))].sort_values("_date").set_index("_date")["close"]
    right = prices[prices["exposure_id"].astype(str).eq(str(denominator))].sort_values("_date").set_index("_date")["close"]
    joined = pd.concat([left.rename("a"), right.rename("b")], axis=1, join="inner").dropna()
    if joined.empty:
        st.info(tr(language, "No overlapping history for this pair.", "该配对没有重叠的历史区间。"))
        return

    ratio = (joined["a"] / joined["b"]).dropna()
    if ratio.empty:
        return

    # Use existing history_window via the prices frame approach
    ratio_frame = pd.DataFrame({"date": ratio.index, "ratio": ratio.values})
    ratio_frame["_date"] = pd.to_datetime(ratio_frame["date"])
    windowed, coverage = history_window(ratio_frame, "date", history_window_name)
    coverage = localize_coverage(coverage, language)
    if windowed.empty:
        st.info(tr(language, "No rows in this window.", "该时间窗口没有数据。"))
        return
    series = windowed.set_index("_date")["ratio"].dropna()
    if series.empty:
        return

    title = f"{labels.get(numerator, numerator)} / {labels.get(denominator, denominator)}"
    st.markdown(
        f'<div class="am-chart-title">{escape(title)} — {tr(language, "ratio", "比值")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        " · ".join(
            [
                tr(
                    language,
                    f"Rising = {labels.get(numerator, numerator)} outperforming {labels.get(denominator, denominator)}.",
                    f"上升 = {labels.get(numerator, numerator)} 跑赢 {labels.get(denominator, denominator)}。",
                ),
                coverage,
            ]
        )
    )

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=series.index, y=series.values, mode="lines", name=title, line=dict(color=PALETTE[0], width=2)))
    ma20 = series.rolling(20).mean()
    ma60 = series.rolling(60).mean()
    fig.add_trace(go.Scatter(x=ma20.index, y=ma20.values, mode="lines", name=tr(language, "20D MA", "20日均线"), line=dict(color=PALETTE[1], width=1, dash="dot")))
    fig.add_trace(go.Scatter(x=ma60.index, y=ma60.values, mode="lines", name=tr(language, "60D MA", "60日均线"), line=dict(color=PALETTE[2], width=1, dash="dash")))
    fig.update_yaxes(title=tr(language, "Ratio", "比值"))
    fig.update_xaxes(title=None, tickformat="%b %Y")
    st.plotly_chart(
        chart_theme(fig, "number", date_axis=True, height=380),
        width="stretch",
        config={"displaylogo": False, "responsive": True},
        key=f"{key_prefix}_ratio_chart",
    )


def render_market_fund_activity(
    activity: pd.DataFrame | None,
    exposure_id: str,
    wrappers: pd.DataFrame,
    language: str,
    history_window_name: str,
    key_prefix: str = "market",
) -> None:
    """Show official ETF share counts and conservative flow estimates.

    The panel is deliberately scoped by the selected index and its wrapper
    cohort.  A share change is a source-backed fact; a CNY flow is shown only
    when the same date has a NAV-backed observation.  This keeps the panel
    useful for a non-technical reader without presenting turnover or a
    provider's "main-force" field as ETF creation/redemption.
    """
    if activity is None or wrappers is None or wrappers.empty:
        return
    if "exposure_id" not in wrappers.columns:
        return

    cohort = wrappers[wrappers["exposure_id"].astype(str).eq(str(exposure_id))].copy()
    if cohort.empty:
        return

    activity = activity.copy()
    if "exposure_id" in activity.columns:
        activity = activity[activity["exposure_id"].astype(str).eq(str(exposure_id))].copy()
    if "fund_id" not in activity.columns:
        return

    wrapper_ids = pd.Series(dtype="string")
    for column in ("fund_id", "ticker"):
        if column in cohort.columns:
            wrapper_ids = pd.concat(
                [wrapper_ids, _market_ticker_series(cohort[column])], ignore_index=True
            )
    wrapper_ids = wrapper_ids.dropna().unique().tolist()
    if wrapper_ids:
        activity["fund_id"] = _market_ticker_series(activity["fund_id"])
        activity = activity[activity["fund_id"].isin(wrapper_ids)].copy()
    if activity.empty:
        section_heading(
            language,
            "ETF fund activity",
            "ETF资金与规模",
            "Official exchange share counts have not reached this snapshot yet.",
            "当前快照还没有该指数的交易所公布份额数据。",
        )
        return

    windowed, coverage = history_window(activity, "observation_date", history_window_name)
    coverage = localize_coverage(coverage, language)
    if windowed.empty:
        return

    section_heading(
        language,
        "ETF fund activity",
        "ETF资金与规模",
        "Exchange-published shares; estimated flow uses share change × same-day published NAV.",
        "交易所公布的基金份额；估算净申赎 = 份额变化 × 同日已公布 NAV。",
    )

    latest = (
        windowed.sort_values(["fund_id", "_date"])
        .groupby("fund_id", sort=False, as_index=False)
        .tail(1)
        .copy()
    )
    latest["_fund_display"] = latest["fund_id"].astype(str)
    if "fund_name" in latest.columns:
        names = latest["fund_name"].fillna("").astype(str).str.strip()
        latest["_fund_display"] = latest["_fund_display"] + names.where(names.eq(""), " " + names)

    def _scaled(value: Any, divisor: float, decimals: int, signed: bool = False) -> str:
        if value is None or pd.isna(value):
            return "—"
        sign = "+" if signed else ""
        return f"{float(value) / divisor:{sign},.{decimals}f}"

    latest["_shares_display"] = latest["shares_outstanding"].map(
        lambda value: _scaled(value, ETF_ACTIVITY_SHARES_PER_WAN, 1)
    )
    latest["_change_display"] = latest.get(
        "shares_change", pd.Series(pd.NA, index=latest.index)
    ).map(lambda value: _scaled(value, ETF_ACTIVITY_SHARES_PER_WAN, 1, signed=True))
    latest["_nav_display"] = latest.get(
        "nav", pd.Series(pd.NA, index=latest.index)
    ).map(lambda value: f"{float(value):,.4f}" if value is not None and pd.notna(value) else "—")
    latest["_flow_display"] = latest.get(
        "estimated_flow_cny", pd.Series(pd.NA, index=latest.index)
    ).map(lambda value: _scaled(value, ETF_ACTIVITY_CNY_PER_YI, 2, signed=True))
    latest["_flow_pct_display"] = latest.get(
        "flow_pct_aum", pd.Series(pd.NA, index=latest.index)
    ).map(lambda value: f"{float(value):+.2f}%" if value is not None and pd.notna(value) else "—")
    status_labels = {
        "validated": ("Validated (shares × NAV)", "已验证（份额 × NAV）"),
        "shares_only": ("Shares only", "仅份额变化"),
        "insufficient_history": ("Needs next observation", "尚需下一次观察"),
        "unavailable": ("Unavailable", "不可用"),
    }
    latest["_status_display"] = latest.get(
        "flow_status", pd.Series(pd.NA, index=latest.index)
    ).map(
        lambda value: (
            status_labels.get(str(value), (str(value), str(value)))[1]
            if language == "zh"
            else status_labels.get(str(value), (str(value), str(value)))[0]
        )
    )
    latest["_date_display"] = latest["_date"].dt.strftime("%Y-%m-%d")
    latest["_gap_display"] = latest.get(
        "observation_gap_days", pd.Series(pd.NA, index=latest.index)
    ).map(lambda value: f"{int(value)}" if value is not None and pd.notna(value) else "—")

    column_map = (
        {
            "_fund_display": "ETF",
            "_date_display": "观察日",
            "_shares_display": "份额（万份）",
            "_change_display": "较上次变化（万份）",
            "_gap_display": "间隔（日）",
            "_nav_display": "同日 NAV",
            "_flow_display": "估算净申赎（亿元）",
            "_flow_pct_display": "占估算规模",
            "_status_display": "数据状态",
        }
        if language == "zh"
        else {
            "_fund_display": "ETF",
            "_date_display": "Observation",
            "_shares_display": "Shares (10k)",
            "_change_display": "Change since prior obs. (10k)",
            "_gap_display": "Gap (days)",
            "_nav_display": "Same-day NAV",
            "_flow_display": "Est. flow (CNY 100m)",
            "_flow_pct_display": "Flow / est. AUM",
            "_status_display": "Data status",
        }
    )
    table_columns = [column for column in column_map if column in latest.columns]
    st.dataframe(
        latest[table_columns].rename(columns=column_map),
        hide_index=True,
        width="stretch",
    )

    validated = windowed.copy()
    if "flow_status" in validated.columns:
        validated = validated[validated["flow_status"].astype(str).eq("validated")]
    if "estimated_flow_cny" not in validated.columns:
        validated = validated.iloc[0:0]
    else:
        validated["estimated_flow_cny"] = pd.to_numeric(
            validated["estimated_flow_cny"], errors="coerce"
        )
        validated = validated.dropna(subset=["estimated_flow_cny"])

    if not validated.empty:
        flow_by_date = (
            validated.groupby("_date", as_index=False)["estimated_flow_cny"].sum()
        )
        flow_by_date["flow_yi"] = flow_by_date["estimated_flow_cny"] / ETF_ACTIVITY_CNY_PER_YI
        bar_colors = ["#1d4ed8" if value >= 0 else "#dc2626" for value in flow_by_date["flow_yi"]]
        fig = go.Figure(
            go.Bar(
                x=flow_by_date["_date"],
                y=flow_by_date["flow_yi"],
                marker=dict(color=bar_colors, line=dict(width=0)),
                name=tr(language, "Estimated net creation / redemption", "估算净申赎"),
                hovertemplate=(
                    "%{x|%Y-%m-%d}<br>"
                    + tr(language, "Estimated flow", "估算净申赎")
                    + ": %{y:+,.2f} 亿元<extra></extra>"
                ),
            )
        )
        fig.add_hline(y=0.0, line_color="#64748b", line_width=1)
        fig.update_xaxes(title=None, tickformat=date_tick_format(flow_by_date["_date"]))
        fig.update_yaxes(
            title=tr(language, "Estimated flow (CNY 100m)", "估算净申赎（亿元）"),
            zeroline=False,
        )
        st.markdown(
            f'<div class="am-chart-title">{escape(tr(language, "Estimated ETF fund activity", "估算 ETF 资金活动"))}</div>',
            unsafe_allow_html=True,
        )
        st.caption(coverage)
        st.plotly_chart(
            chart_theme(fig, "number", date_axis=True, height=300),
            width="stretch",
            config={"displaylogo": False, "responsive": True},
            key=f"{key_prefix}_{exposure_id}_fund_activity_chart",
        )
    else:
        st.info(
            tr(
                language,
                "Share counts are present, but no two-point same-day NAV-validated flow is available yet.",
                "已接入交易所份额，但当前还没有具备两期份额及同日 NAV 的可验证净申赎金额。",
            )
        )
    st.caption(
        tr(
            language,
            "Shares are official exchange-published observations. Estimated flow is not turnover or a provider's main-force flow; it excludes rows without a same-day published NAV.",
            "份额为交易所公布数据。估算净申赎不等于成交额或主力资金流；没有同日已公布 NAV 的记录不会计入金额。",
        )
    )


def render_market_index_detail(
    exposure_id: str,
    label: str,
    prices: pd.DataFrame,
    technicals: pd.DataFrame,
    wrappers: pd.DataFrame,
    language: str,
    history_window_name: str,
    etf_prices: pd.DataFrame | None = None,
    premium_history: pd.DataFrame | None = None,
    fund_activity: pd.DataFrame | None = None,
    rsi_window: int = 14,
    ma_window: int = 20,
    rsi_upper: float = 70.0,
    rsi_lower: float = 30.0,
    key_prefix: str = "market",
    show_premium: bool = True,
) -> None:
    """One index: technicals plus optional listed-wrapper context."""
    if (
        prices is None
        or prices.empty
        or not {"exposure_id", "_date", "date", "close"}.issubset(prices.columns)
    ):
        series = pd.DataFrame(columns=["exposure_id", "_date", "date", "close"])
    else:
        series = prices[prices["exposure_id"].astype(str).eq(str(exposure_id))].sort_values("_date").copy()
    windowed, coverage = history_window(series, "date", history_window_name)
    coverage = localize_coverage(coverage, language)

    # --- Metric cards: RSI, MA20, avg premium, drawdown (no MA60) ---
    tech_row = (
        technicals[technicals["exposure_id"].astype(str).eq(str(exposure_id))]
        if technicals is not None
        and not technicals.empty
        and "exposure_id" in technicals.columns
        else pd.DataFrame()
    )
    if not tech_row.empty:
        row = tech_row.iloc[0]
        readings = [
            ("RSI", "RSI", row.get("rsi"), "{:.0f}"),
            ("vs MA20", "相对20日均线", row.get("ma20_pct"), "{:+.2f}%"),
            ("60D drawdown", "60日回撤", row.get("drawdown_60d"), "{:+.2f}%"),
        ]
        # Name the window the mean was actually taken over. The premium series
        # accumulates one observation per run, so a fresh deployment has a
        # single day of it; labelling that "30D" states a month of averaging
        # that did not happen.
        if show_premium:
            premium_days = row.get("avg_premium_days")
            premium_days = 0 if premium_days is None or pd.isna(premium_days) else int(premium_days)
            if premium_days <= 1:
                premium_en, premium_zh = "Premium (today)", "溢价（当日）"
            elif premium_days >= 30:
                premium_en, premium_zh = "Avg premium 30D", "平均溢价 30日"
            else:
                premium_en, premium_zh = f"Avg premium {premium_days}D", f"平均溢价 {premium_days}日"
            readings.insert(
                2,
                (premium_en, premium_zh, row.get("avg_premium_30d"), "{:+.2f}%"),
            )
        columns = st.columns(len(readings))
        for column, (en, zh, value, fmt) in zip(columns, readings):
            display = "—" if value is None or pd.isna(value) else fmt.format(float(value))
            column.metric(tr(language, en, zh), display)

    # --- Index price + RSI, one figure, one shared date axis ---
    # Price and RSI used to be two figures. Reading "what was RSI on the day
    # of that drawdown" then meant matching two x-axes by eye; on a shared
    # axis with unified hover the crosshair answers it directly.
    if not windowed.empty:
        tick_format = date_tick_format(windowed["_date"])
        hover_format = date_hover_format(windowed["_date"])

        # RSI is computed on the full series and only then windowed, so the
        # first plotted day already carries its warm-up rather than starting
        # from an undefined average.
        rsi_full = _compute_rsi_series(series.set_index("_date")["close"], window=rsi_window)
        rsi = rsi_full.reindex(windowed["_date"]).dropna()
        has_rsi = not rsi.empty

        rows = 2 if has_rsi else 1
        fig = make_subplots(
            rows=rows,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.06,
            row_heights=[0.72, 0.28] if has_rsi else [1.0],
        )
        ma_label = tr(language, f"MA{ma_window}", f"{ma_window}日均线")
        ma = windowed.set_index("_date")["close"].rolling(ma_window).mean()
        for name, values, width in (
            (tr(language, "Close", "收盘"), windowed.set_index("_date")["close"], 1.8),
            (ma_label, ma, 1.0),
        ):
            fig.add_trace(
                go.Scatter(
                    x=values.index,
                    y=values.values,
                    mode="lines",
                    name=name,
                    line=dict(width=width),
                    hovertemplate=f"{name}: %{{y:,.2f}}<extra></extra>",
                ),
                row=1,
                col=1,
            )
        fig.update_yaxes(title=tr(language, "Index level", "指数点位"), row=1, col=1)

        if has_rsi:
            fig.add_trace(
                go.Scatter(
                    x=rsi.index,
                    y=rsi.values,
                    mode="lines",
                    name=f"RSI({rsi_window})",
                    line=dict(width=1.4),
                    hovertemplate=f"RSI({rsi_window}): %{{y:.1f}}<extra></extra>",
                ),
                row=2,
                col=1,
            )
            fig.add_hrect(y0=rsi_upper, y1=100, fillcolor="#EF4444", opacity=0.06, line_width=0, row=2, col=1)
            fig.add_hrect(y0=0, y1=rsi_lower, fillcolor="#10B981", opacity=0.06, line_width=0, row=2, col=1)
            fig.add_hline(y=rsi_upper, line_dash="dot", line_color="#D1D5DB", line_width=0.5, row=2, col=1)
            fig.add_hline(y=rsi_lower, line_dash="dot", line_color="#D1D5DB", line_width=0.5, row=2, col=1)
            fig.update_yaxes(title="RSI", range=[0, 100], row=2, col=1)

        fig.update_xaxes(title=None, tickformat=tick_format, row=rows, col=1)
        fig.update_layout(hovermode="x unified", hoverlabel=dict(namelength=-1))
        # One crosshair spanning both panels. "across" draws the spike over
        # the whole plotting area rather than only the subplot under the
        # cursor, so reading the RSI at a price move is one glance instead of
        # matching two axes by eye. spikedistance=-1 keeps the line alive
        # anywhere on the row, not only within snapping range of a point.
        fig.update_xaxes(
            hoverformat=hover_format,
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikethickness=1,
            spikedash="dot",
            spikecolor="#9CA3AF",
        )
        fig.update_layout(spikedistance=-1, hoverdistance=100)

        st.markdown(
            f'<div class="am-chart-title">{escape(label)} — '
            f'{tr(language, "price and RSI", "价格与 RSI")}</div>',
            unsafe_allow_html=True,
        )
        st.caption(coverage)
        st.plotly_chart(
            chart_theme(fig, "number", date_axis=True, height=460 if has_rsi else 340),
            width="stretch",
            config={"displaylogo": False, "responsive": True},
            key=f"{key_prefix}_{exposure_id}_price_rsi_chart",
        )

    # --- All ETF prices on this index (rebased to 100) ---
    cohort_tickers: list[str] = []
    if wrappers is not None and not wrappers.empty and "exposure_id" in wrappers.columns:
        cohort = wrappers[wrappers["exposure_id"].astype(str).eq(str(exposure_id))]
        if not cohort.empty and "ticker" in cohort.columns:
            cohort_tickers = _market_ticker_series(cohort["ticker"]).dropna().tolist()

    if (
        etf_prices is not None
        and not etf_prices.empty
        and {"ticker", "_date", "date", "close"}.issubset(etf_prices.columns)
        and cohort_tickers
    ):
        ep = etf_prices[
            _market_ticker_series(etf_prices["ticker"]).isin(cohort_tickers)
        ].copy()
        ep["ticker"] = _market_ticker_series(ep["ticker"])
        if not ep.empty:
            ep_windowed, ep_cov = history_window(ep, "date", history_window_name)
            ep_cov = localize_coverage(ep_cov, language)
            if not ep_windowed.empty:
                # Rebase each ETF to 100 at the common first date
                common = ep_windowed.groupby("ticker")["_date"].min().max()
                ep_al = ep_windowed[ep_windowed["_date"] >= common].copy()
                if not ep_al.empty:
                    base = ep_al.sort_values("_date").groupby("ticker")["close"].transform("first")
                    ep_al["_value"] = ep_al["close"] / base * 100.0
                    name_map = {}
                    if not wrappers.empty and "exposure_id" in wrappers.columns:
                        for _, w in wrappers[wrappers["exposure_id"].astype(str).eq(str(exposure_id))].iterrows():
                            ticker = _market_ticker_series(pd.Series([w["ticker"]])).iloc[0]
                            if pd.notna(ticker):
                                name_map[str(ticker)] = f"{w['ticker']} {str(w.get('fund_name', ''))[:12]}"
                    ep_al["series"] = ep_al["ticker"].map(name_map).fillna(ep_al["ticker"])
                    st.markdown(
                        f'<div class="am-chart-title">{escape(label)} — {tr(language, "ETF prices (rebased to 100)", "ETF价格（归一至 100）")}</div>',
                        unsafe_allow_html=True,
                    )
                    st.caption(ep_cov)
                    fig_etf = px.line(
                        ep_al.sort_values(["series", "_date"]),
                        x="_date",
                        y="_value",
                        color="series",
                        color_discrete_sequence=PALETTE,
                        render_mode="svg",
                    )
                    fig_etf.add_hline(y=100.0, line_dash="dot", line_color="#9CA3AF", line_width=1)
                    fig_etf.update_yaxes(title=tr(language, "Rebased level", "归一水平"))
                    fig_etf.update_xaxes(title=None, tickformat=date_tick_format(ep_al["_date"]))
                    fig_etf.update_xaxes(hoverformat=date_hover_format(ep_al["_date"]))
                    apply_line_hover(fig_etf, ep_al, "number")
                    st.plotly_chart(
                        chart_theme(fig_etf, "number", date_axis=True, height=300),
                        width="stretch",
                        config={"displaylogo": False, "responsive": True},
                        key=f"{key_prefix}_{exposure_id}_etf_rebased_chart",
                    )

    # --- Premium history ---
    if (
        premium_history is not None
        and not premium_history.empty
        and {"ticker", "_date", "date", "premium_pct"}.issubset(premium_history.columns)
        and cohort_tickers
    ):
        ph = premium_history[
            _market_ticker_series(premium_history["ticker"]).isin(cohort_tickers)
        ].copy()
        ph["ticker"] = _market_ticker_series(ph["ticker"])
        if not ph.empty:
            ph_windowed, ph_cov = history_window(ph, "date", history_window_name)
            ph_cov = localize_coverage(ph_cov, language)
            if not ph_windowed.empty:
                name_map_ph = {}
                if not wrappers.empty and "exposure_id" in wrappers.columns:
                    for _, w in wrappers[wrappers["exposure_id"].astype(str).eq(str(exposure_id))].iterrows():
                        ticker = _market_ticker_series(pd.Series([w["ticker"]])).iloc[0]
                        if pd.notna(ticker):
                            name_map_ph[str(ticker)] = str(w["ticker"])
                ph_windowed["series"] = ph_windowed["ticker"].map(name_map_ph).fillna(ph_windowed["ticker"])
                st.markdown(
                    f'<div class="am-chart-title">{escape(label)} — {tr(language, "premium history", "溢价历史")}</div>',
                    unsafe_allow_html=True,
                )
                # The series mixes two measurements of the same quantity:
                # published NAV for the history, IOPV for the days NAV has not
                # caught up to. Say which, rather than labelling the whole
                # line with one of them.
                bases = (
                    set(ph_windowed["basis"].dropna().astype(str))
                    if "basis" in ph_windowed.columns
                    else set()
                )
                if bases == {"nav"}:
                    basis_note = tr(language, "Close vs published NAV.", "收盘价对已公布净值。")
                elif bases == {"iopv"}:
                    basis_note = tr(language, "Close vs intraday IOPV.", "收盘价对盘中 IOPV。")
                elif bases:
                    basis_note = tr(
                        language,
                        "Close vs published NAV, with IOPV for the most recent days NAV has not reached.",
                        "收盘价对已公布净值；净值尚未公布的最近几日以 IOPV 补足。",
                    )
                else:
                    basis_note = ""
                st.caption(" · ".join(part for part in (ph_cov, basis_note) if part))
                fig_ph = px.line(
                    ph_windowed.sort_values(["series", "_date"]),
                    x="_date",
                    y="premium_pct",
                    color="series",
                    color_discrete_sequence=PALETTE,
                    render_mode="svg",
                )
                fig_ph.add_hline(y=0.0, line_dash="dot", line_color="#9CA3AF", line_width=1)
                # A premium only means something against its own history: 7%
                # is cheap for a wrapper that usually trades at 10% and dear
                # for one that usually trades at 3%.
                median_premium = pd.to_numeric(ph_windowed["premium_pct"], errors="coerce").median()
                if pd.notna(median_premium) and len(ph_windowed) >= 20:
                    fig_ph.add_hline(
                        y=float(median_premium),
                        line_dash="dash",
                        line_color="#9CA3AF",
                        line_width=1,
                        annotation_text=tr(language, "cohort median", "同组中位数")
                        + f" {median_premium:+.2f}%",
                        annotation_position="top left",
                        annotation_font_size=10,
                    )
                fig_ph.update_yaxes(title=tr(language, "Premium %", "溢价率 %"))
                fig_ph.update_xaxes(title=None, tickformat=date_tick_format(ph_windowed["_date"]))
                fig_ph.update_xaxes(hoverformat=date_hover_format(ph_windowed["_date"]))
                st.plotly_chart(
                    chart_theme(fig_ph, "number", date_axis=True, height=280),
                    width="stretch",
                    config={"displaylogo": False, "responsive": True},
                    key=f"{key_prefix}_{exposure_id}_prem_history_chart",
                )

    # --- Official ETF shares and conservative flow estimate ----------------
    if fund_activity is not None:
        render_market_fund_activity(
            fund_activity,
            exposure_id,
            wrappers,
            language,
            history_window_name,
            key_prefix=key_prefix,
        )

    # --- ETF wrapper table ---
    if wrappers is None or wrappers.empty or "exposure_id" not in wrappers.columns:
        return
    cohort = wrappers[wrappers["exposure_id"].astype(str).eq(str(exposure_id))].copy()
    if cohort.empty:
        return
    st.markdown(
        f'<div class="am-chart-title">{tr(language, "ETF wrappers on this index", "追踪该指数的 ETF")}</div>',
        unsafe_allow_html=True,
    )

    if "peer_rank" in cohort.columns:
        cohort["_peer_rank_sort"] = pd.to_numeric(
            cohort["peer_rank"], errors="coerce"
        )
        cohort = cohort.sort_values("_peer_rank_sort", na_position="last").drop(
            columns=["_peer_rank_sort"]
        )

    # Format human-readable columns
    display_df = cohort.copy()

    # 费率格式化 (如 0.0015 -> 0.15%/年)。管理费 + 托管费，与 hold_score
    # 的计分口径和邮件快报保持一致：单列管理费会把持有成本报低,
    # 日经 225 的 0.20% 实际是 0.25%。
    _management_fee = (
        pd.to_numeric(display_df["management_fee"], errors="coerce")
        if "management_fee" in display_df.columns
        else pd.Series(float("nan"), index=display_df.index)
    )
    _custody_fee = (
        pd.to_numeric(display_df["custody_fee"], errors="coerce")
        if "custody_fee" in display_df.columns
        else pd.Series(float("nan"), index=display_df.index)
    )
    _fee_available = _management_fee.notna() | _custody_fee.notna()
    _total_fee = _management_fee.fillna(0.0).add(_custody_fee.fillna(0.0))
    display_df["_fee_display"] = [
        f"{float(value) * 100:.2f}%/年" if available else "—"
        for value, available in zip(_total_fee, _fee_available)
    ]

    quote_displayable = _displayable_wrapper_quote_mask(display_df)
    display_df["_quote_status_display"] = display_df.apply(
        lambda row: _wrapper_quote_status_label(row, language), axis=1
    )

    # 溢价率格式化 (如 -0.01 -> -0.01%)
    display_df["_prem_display"] = [
        f"{float(value):+.2f}%" if allowed and pd.notna(value) else "—"
        for value, allowed in zip(
            display_df.get("premium_pct", pd.Series(float("nan"), index=display_df.index)),
            quote_displayable,
        )
    ]

    # 同类相对溢价
    display_df["_rel_prem_display"] = [
        f"{float(value):+.2f}%" if allowed and pd.notna(value) else "—"
        for value, allowed in zip(
            display_df.get("relative_premium_pct", pd.Series(float("nan"), index=display_df.index)),
            quote_displayable,
        )
    ]

    # 规模格式化 (如 30628289962 -> 306.3 亿)
    display_df["_aum_display"] = [
        f"{float(value) / 1e8:.1f} 亿元"
        if allowed and pd.notna(value) and float(value) > 0
        else "—"
        for value, allowed in zip(
            display_df.get("aum_proxy", pd.Series(float("nan"), index=display_df.index)),
            quote_displayable,
        )
    ]

    # 入场成本 (bp)
    display_df["_cost_display"] = [
        f"{float(value):.1f} bp" if allowed and pd.notna(value) else "—"
        for value, allowed in zip(
            display_df.get("entry_cost_bp", pd.Series(float("nan"), index=display_df.index)),
            quote_displayable,
        )
    ]

    # 状态翻译与徽章化
    status_map_zh = {
        "ATTRACTIVE": "折价机会 (优先)",
        "FAIR": "估值合理 (正常)",
        "AVOID": "高溢警惕 (慎入)",
        "EXPENSIVE": "偏贵",
        "UNAVAILABLE": "暂无最新报价",
    }
    if "entry_status" in display_df.columns:
        status_values = display_df["entry_status"].astype("string").where(
            quote_displayable, "UNAVAILABLE"
        )
        if language == "zh":
            display_df["_status_display"] = status_values.map(status_map_zh).fillna(status_values)
        else:
            display_df["_status_display"] = status_values
    else:
        display_df["_status_display"] = quote_displayable.map(
            {True: "—", False: "UNAVAILABLE"}
        )

    # 买入优选排名
    display_df["_rank_display"] = [
        f"#{int(round(value))}" if allowed and pd.notna(value) else "—"
        for value, allowed in zip(
            display_df.get("peer_rank", pd.Series(float("nan"), index=display_df.index)),
            quote_displayable,
        )
    ]

    # 列映射定义
    col_mapping_zh = {
        "ticker": "代码",
        "fund_name": "ETF简称",
        "_quote_status_display": "报价状态",
        "_status_display": "建仓建议",
        "_prem_display": "折溢价率",
        "_rel_prem_display": "同类相对溢价",
        "_fee_display": "总费率",
        "_aum_display": "基金规模",
        "_cost_display": "综合买入成本",
        "_rank_display": "买入优选",
    }
    col_mapping_en = {
        "ticker": "Ticker",
        "fund_name": "Fund Name",
        "_quote_status_display": "Quote Status",
        "_status_display": "Status",
        "_prem_display": "Premium",
        "_rel_prem_display": "Rel Premium",
        "_fee_display": "Total Fee",
        "_aum_display": "AUM",
        "_cost_display": "Entry Cost",
        "_rank_display": "Peer Rank",
    }

    mapping = col_mapping_zh if language == "zh" else col_mapping_en
    final_cols = [c for c in mapping.keys() if c in display_df.columns]
    table_to_show = display_df[final_cols].rename(columns=mapping)

    st.dataframe(table_to_show, hide_index=True, width="stretch")

    current_cohort = cohort.loc[_displayable_wrapper_quote_mask(cohort)]
    if (
        "entry_cost_bp" in current_cohort.columns
        and current_cohort["entry_cost_bp"].notna().any()
    ):
        render_market_entry_cost_chart(
            current_cohort,
            language,
            key_prefix=f"{key_prefix}_{exposure_id}",
        )

    if not bool(quote_displayable.all()):
        st.warning(
            tr(
                language,
                "Some ETF quotes are stale or unavailable; premium, peer comparison, entry cost, rank and quote-based AUM are shown as —. Fees remain the latest published total fee.",
                "部分 ETF 报价已过期或不可用；溢价、同类比较、综合买入成本、排名及基于报价的规模显示为 —。费率仍显示最近公布的总费率。",
            )
        )

    if "premium_caveat" in cohort.columns:
        caveats = [str(x) for x in cohort["premium_caveat"].dropna().unique().tolist() if x]
        if caveats:
            st.caption(
                tr(
                    language,
                    "Cross-border QDII premium interpretation differs from domestic ETFs.",
                    "跨境 QDII 溢价的解释方式不同于境内 ETF。",
                )
            )


def render_market_entry_cost_chart(cohort: pd.DataFrame, language: str, key_prefix: str = "market") -> None:
    """Entry cost & premium per wrapper with clear contextual axis limits."""
    frame = cohort.dropna(subset=["entry_cost_bp"]).copy()
    if frame.empty:
        return
    frame["_label"] = frame.get("ticker", pd.Series(dtype=str)).astype(str)
    if "fund_name" in frame.columns:
        frame["_label"] = frame["_label"] + " " + frame["fund_name"].astype(str).str.slice(0, 16)
    frame = frame.sort_values("entry_cost_bp")

    # Determine colors based on cost/premium
    colors = []
    for _, r in frame.iterrows():
        c = r.get("entry_cost_bp", 0)
        if c < 0:
            colors.append("#16a34a") # green for discount
        elif c > 100:
            colors.append("#dc2626") # red for high premium
        else:
            colors.append("#3b82f6") # blue

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=frame["entry_cost_bp"],
            y=frame["_label"],
            orientation="h",
            marker=dict(color=colors),
            text=[f"{v:.1f} bp ({v/100:+.2f}%)" for v in frame["entry_cost_bp"]],
            textposition="outside",
            hovertemplate=(
                "<b>%{y}</b><br>"
                + tr(language, "Entry cost", "综合入场成本")
                + ": %{x:.2f} bp<extra></extra>"
            ),
        )
    )

    # Smart X-axis range so bars are not squished against 100bp
    min_x = min(frame["entry_cost_bp"].min(), 0) - 5
    max_x = max(frame["entry_cost_bp"].max() * 1.35, 10)
    fig.update_xaxes(
        title=tr(language, "Entry Cost (bp = 0.01%) — Premium + Half-Spread", "综合买入成本 (bp，1bp=0.01%) = 折溢价 + 0.5×买卖价差"),
        range=[min_x, max_x],
        zeroline=True,
        zerolinewidth=1.5,
        zerolinecolor="#94a3b8",
    )
    fig.update_yaxes(title=None, automargin=True)

    st.plotly_chart(
        chart_theme(fig, "number", date_axis=False, height=max(180, 50 * len(frame))),
        width="stretch",
        config={"displaylogo": False, "responsive": True},
        key=f"{key_prefix}_entry_cost_chart",
    )
