"""ETF Heat Maps: Market performance, fund flow, and single-ETF drilldown."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

from .config import HISTORY_WINDOWS, PALETTE
from .core import history_window as filter_history_window, tr

HEATMAP_CATEGORY_KEYS = (
    "all",
    "broad_equity",
    "sector",
    "international",
    "commodity",
    "fixed_income",
)

HEATMAP_CATEGORY_LABELS = {
    "all": {"en": "All Categories", "zh": "全部大类"},
    "broad_equity": {"en": "Broad Equity", "zh": "宽基股票"},
    "sector": {"en": "Sectors", "zh": "行业板块"},
    "international": {"en": "International", "zh": "国际市场"},
    "commodity": {"en": "Commodities", "zh": "大宗商品"},
    "fixed_income": {"en": "Fixed Income", "zh": "固定收益"},
}

RETURN_WINDOW_KEYS = ("1d", "1w", "1m", "3m", "ytd", "1y")

RETURN_WINDOW_LABELS = {
    "1d": {"en": "1D", "zh": "1日"},
    "1w": {"en": "1W", "zh": "1周"},
    "1m": {"en": "1M", "zh": "1月"},
    "3m": {"en": "3M", "zh": "3月"},
    "ytd": {"en": "YTD", "zh": "年初至今"},
    "1y": {"en": "1Y", "zh": "1年"},
}

FLOW_WINDOW_KEYS = ("1d", "1w", "1m", "3m", "ytd")

FLOW_WINDOW_LABELS = {
    "1d": {"en": "1D", "zh": "1日"},
    "1w": {"en": "1W", "zh": "1周"},
    "1m": {"en": "1M", "zh": "1月"},
    "3m": {"en": "3M", "zh": "3月"},
    "ytd": {"en": "YTD", "zh": "年初至今"},
}

RETURN_COLORSCALE = [
    [0.0, "#EF4444"],
    [0.5, "#F3F4F6"],
    [1.0, "#10B981"],
]

FLOW_COLORSCALE = [
    [0.0, "#EF4444"],
    [0.5, "#F3F4F6"],
    [1.0, "#10B981"],
]


def _format_flow_amount(val: float | None, language: str) -> str:
    if val is None or pd.isna(val):
        return "—"
    v = float(val)
    if language == "zh":
        if abs(v) >= 100_000_000:
            return f"{v / 100_000_000:+.2f} 亿"
        if abs(v) >= 10_000:
            return f"{v / 10_000:+.2f} 万"
        return f"{v:+.2f}"
    else:
        if abs(v) >= 1_000_000_000:
            return f"{v / 1_000_000_000:+.2f}B"
        if abs(v) >= 1_000_000:
            return f"{v / 1_000_000:+.2f}M"
        if abs(v) >= 1_000:
            return f"{v / 1_000:+.2f}K"
        return f"{v:+.2f}"


def _format_size_amount(val: float | None, language: str) -> str:
    if val is None or pd.isna(val) or float(val) <= 0:
        return "—"
    v = float(val)
    if language == "zh":
        if v >= 100_000_000:
            return f"{v / 100_000_000:.2f} 亿"
        if v >= 10_000:
            return f"{v / 10_000:.2f} 万"
        return f"{v:.2f}"
    else:
        if v >= 1_000_000_000:
            return f"{v / 1_000_000_000:.2f}B"
        if v >= 1_000_000:
            return f"{v / 1_000_000:.2f}M"
        if v >= 1_000:
            return f"{v / 1_000:.2f}K"
        return f"{v:.2f}"


def _format_ret(val: float | None) -> str:
    if val is None or pd.isna(val):
        return "—"
    return f"{float(val):+.2f}%"


def _category_display(cat: str, language: str) -> str:
    labels = HEATMAP_CATEGORY_LABELS.get(cat, {})
    return labels.get(language, labels.get("en", cat))


def render_performance_tab(
    returns_df: pd.DataFrame,
    language: str,
) -> None:
    """Render Market Performance Treemap and summary table."""
    if returns_df.empty:
        st.info(
            tr(
                language,
                "This chart is not available in the current artifact snapshot.",
                "当前数据快照未包含此图表。",
            )
        )
        return

    ctrl_col1, ctrl_col2 = st.columns([1, 1])
    with ctrl_col1:
        if hasattr(st, "segmented_control"):
            selected_window = (
                st.segmented_control(
                    tr(language, "Return Window", "收益周期"),
                    RETURN_WINDOW_KEYS,
                    default="1d",
                    format_func=lambda k: RETURN_WINDOW_LABELS[k][language],
                    key="hm_perf_window",
                )
                or "1d"
            )
        else:
            selected_window = (
                st.radio(
                    tr(language, "Return Window", "收益周期"),
                    RETURN_WINDOW_KEYS,
                    index=0,
                    horizontal=True,
                    format_func=lambda k: RETURN_WINDOW_LABELS[k][language],
                    key="hm_perf_window",
                )
                or "1d"
            )

    with ctrl_col2:
        selected_cat = st.selectbox(
            tr(language, "Category Filter", "资产大类筛选"),
            HEATMAP_CATEGORY_KEYS,
            index=0,
            format_func=lambda k: HEATMAP_CATEGORY_LABELS[k][language],
            key="hm_perf_category",
        )

    filtered_df = returns_df.copy()
    if selected_cat != "all" and "category" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["category"] == selected_cat]

    if filtered_df.empty:
        st.info(
            tr(
                language,
                "No ETF data available for the selected filter.",
                "所选筛选条件下暂无 ETF 数据。",
            )
        )
        return

    window_col = f"return_{selected_window}_pct"
    window_label = RETURN_WINDOW_LABELS[selected_window][language]

    # Build Treemap hierarchy
    ids: list[str] = []
    labels_list: list[str] = []
    parents: list[str] = []
    values: list[float] = []
    colors: list[float] = []
    customdata_list: list[list[Any]] = []

    categories_present = filtered_df["category"].dropna().unique().tolist()
    for cat in categories_present:
        cat_id = f"CAT_{cat}"
        cat_name = _category_display(str(cat), language)
        ids.append(cat_id)
        labels_list.append(cat_name)
        parents.append("")
        values.append(0.0)
        colors.append(0.0)
        customdata_list.append(["", cat_name, cat_name, "", "", "", "", "", "", "", ""])

    for _, row in filtered_df.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        cat = str(row.get("category", "")).strip()
        name_zh = str(row.get("name_zh") or row.get("fund_name") or ticker)
        name_en = str(row.get("name_en") or row.get("fund_name") or ticker)
        name = name_zh if language == "zh" else name_en
        cat_name = _category_display(cat, language)

        price = row.get("latest_price")
        price_str = f"{float(price):.2f}" if price is not None and not pd.isna(price) else "—"

        raw_ret = row.get(window_col)
        ret_val = float(raw_ret) if raw_ret is not None and not pd.isna(raw_ret) else None
        ret_str = _format_ret(ret_val)

        size_val = row.get("size_value")
        has_size = size_val is not None and not pd.isna(size_val) and float(size_val) > 0
        area_val = float(size_val) if has_size else 1.0
        size_basis = str(row.get("size_basis") or "equal_area")
        size_str = _format_size_amount(size_val, language) if has_size else tr(language, "Equal area", "等面积")

        ret_1d = _format_ret(row.get("return_1d_pct"))
        ret_1w = _format_ret(row.get("return_1w_pct"))
        ret_1m = _format_ret(row.get("return_1m_pct"))
        ret_3m = _format_ret(row.get("return_3m_pct"))
        ret_ytd = _format_ret(row.get("return_ytd_pct"))
        ret_1y = _format_ret(row.get("return_1y_pct"))

        leaf_id = f"{cat}_{ticker}"
        display_label = f"<b>{ticker}</b><br>{name}<br>{ret_str}"

        ids.append(leaf_id)
        labels_list.append(display_label)
        parents.append(f"CAT_{cat}")
        values.append(area_val)
        colors.append(ret_val if ret_val is not None else 0.0)
        customdata_list.append([
            ticker,
            name,
            cat_name,
            price_str,
            ret_1d,
            ret_1w,
            ret_1m,
            ret_3m,
            ret_ytd,
            ret_1y,
            f"{size_str} ({size_basis})",
        ])

    # Dynamic color scale bounds centered at 0
    valid_rets = [c for c in colors if c != 0.0]
    max_bound = max(abs(min(valid_rets, default=-3.0)), abs(max(valid_rets, default=3.0)), 2.0)

    fig = go.Figure(
        go.Treemap(
            ids=ids,
            labels=labels_list,
            parents=parents,
            values=values,
            branchvalues="remainder",
            marker=dict(
                colors=colors,
                colorscale=RETURN_COLORSCALE,
                cmid=0.0,
                cmin=-max_bound,
                cmax=max_bound,
                colorbar=dict(
                    title=f"{window_label} (%)",
                    ticksuffix="%",
                ),
                line=dict(width=1, color="#FFFFFF"),
            ),
            customdata=customdata_list,
            hovertemplate=(
                "<b>%{customdata[0]} · %{customdata[1]}</b><br>"
                + tr(language, "Category: ", "大类：")
                + "%{customdata[2]}<br>"
                + tr(language, "Price: ", "最新价：")
                + "%{customdata[3]}<br>"
                + f"{window_label} "
                + tr(language, "Return: ", "收益率：")
                + "%{color:+.2f}%<br>"
                + "1D: %{customdata[4]} | 1W: %{customdata[5]} | 1M: %{customdata[6]}<br>"
                + "3M: %{customdata[7]} | YTD: %{customdata[8]} | 1Y: %{customdata[9]}<br>"
                + tr(language, "Size Basis: ", "规模依据：")
                + "%{customdata[10]}<extra></extra>"
            ),
            textinfo="label",
            textposition="middle center",
        )
    )

    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        height=480,
    )

    st.markdown(
        f'<div class="am-chart-title">{tr(language, "ETF Cross-Asset Performance Treemap", "ETF 跨资产多周期表现热力图")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        tr(
            language,
            f"Rectangle size: Disclosed fund size / equal area · Color: {window_label} return (%).",
            f"色块面积：已披露基金规模／等面积 · 颜色：{window_label} 收益率 (%)。",
        )
    )
    st.plotly_chart(
        fig,
        width="stretch",
        config={"displaylogo": False, "responsive": True},
        key="hm_perf_treemap",
    )

    # Summary Dataframe
    st.markdown(
        f'<div class="am-chart-title" style="margin-top:16px;">{tr(language, "Performance Detail Table", "收益率明细表")}</div>',
        unsafe_allow_html=True,
    )

    table_rows = []
    for _, row in filtered_df.iterrows():
        ticker = str(row.get("ticker", "")).strip().upper()
        cat = str(row.get("category", "")).strip()
        name_zh = str(row.get("name_zh") or row.get("fund_name") or ticker)
        name_en = str(row.get("name_en") or row.get("fund_name") or ticker)
        name = name_zh if language == "zh" else name_en
        cat_name = _category_display(cat, language)

        price = row.get("latest_price")
        price_str = f"{float(price):.2f}" if price is not None and not pd.isna(price) else "—"

        table_rows.append({
            "_ticker": ticker,
            "_name": name,
            "_category": cat_name,
            "_price": price_str,
            "_ret_1d": _format_ret(row.get("return_1d_pct")),
            "_ret_1w": _format_ret(row.get("return_1w_pct")),
            "_ret_1m": _format_ret(row.get("return_1m_pct")),
            "_ret_3m": _format_ret(row.get("return_3m_pct")),
            "_ret_ytd": _format_ret(row.get("return_ytd_pct")),
            "_ret_1y": _format_ret(row.get("return_1y_pct")),
        })

    col_map = {
        "_ticker": tr(language, "Ticker", "代码"),
        "_name": tr(language, "Name", "基金名称"),
        "_category": tr(language, "Category", "资产大类"),
        "_price": tr(language, "Latest Price", "最新价"),
        "_ret_1d": tr(language, "1D Return", "1日收益"),
        "_ret_1w": tr(language, "1W Return", "1周收益"),
        "_ret_1m": tr(language, "1M Return", "1月收益"),
        "_ret_3m": tr(language, "3M Return", "3月收益"),
        "_ret_ytd": tr(language, "YTD Return", "年初至今"),
        "_ret_1y": tr(language, "1Y Return", "1年收益"),
    }
    df_table = pd.DataFrame(table_rows).rename(columns=col_map)
    st.dataframe(df_table, hide_index=True, width="stretch")


def render_flow_tab(
    flows_df: pd.DataFrame,
    language: str,
) -> None:
    """Render ETF Fund Flow Treemap and summary table."""
    if flows_df.empty:
        st.info(
            tr(
                language,
                "This chart is not available in the current artifact snapshot.",
                "当前数据快照未包含此图表。",
            )
        )
        return

    ctrl_col1, ctrl_col2 = st.columns([1, 1])
    with ctrl_col1:
        if hasattr(st, "segmented_control"):
            selected_window = (
                st.segmented_control(
                    tr(language, "Flow Window", "资金流周期"),
                    FLOW_WINDOW_KEYS,
                    default="1w",
                    format_func=lambda k: FLOW_WINDOW_LABELS[k][language],
                    key="hm_flow_window",
                )
                or "1w"
            )
        else:
            selected_window = (
                st.radio(
                    tr(language, "Flow Window", "资金流周期"),
                    FLOW_WINDOW_KEYS,
                    index=1,
                    horizontal=True,
                    format_func=lambda k: FLOW_WINDOW_LABELS[k][language],
                    key="hm_flow_window",
                )
                or "1w"
            )

    with ctrl_col2:
        selected_cat = st.selectbox(
            tr(language, "Category Filter", "资产大类筛选"),
            HEATMAP_CATEGORY_KEYS,
            index=0,
            format_func=lambda k: HEATMAP_CATEGORY_LABELS[k][language],
            key="hm_flow_category",
        )

    filtered_df = flows_df.copy()
    if selected_cat != "all" and "category" in filtered_df.columns:
        filtered_df = filtered_df[filtered_df["category"] == selected_cat]

    if filtered_df.empty:
        st.info(
            tr(
                language,
                "No ETF flow data available for the selected filter.",
                "所选筛选条件下暂无资金流数据。",
            )
        )
        return

    window_col = f"flow_{selected_window}"
    window_label = FLOW_WINDOW_LABELS[selected_window][language]

    # Build Treemap hierarchy
    ids: list[str] = []
    labels_list: list[str] = []
    parents: list[str] = []
    values: list[float] = []
    colors: list[float] = []
    customdata_list: list[list[Any]] = []

    categories_present = filtered_df["category"].dropna().unique().tolist()
    for cat in categories_present:
        cat_id = f"CAT_{cat}"
        cat_name = _category_display(str(cat), language)
        ids.append(cat_id)
        labels_list.append(cat_name)
        parents.append("")
        values.append(0.0)
        colors.append(0.0)
        customdata_list.append(["", cat_name, cat_name, "", "", "", "", ""])

    for _, row in filtered_df.iterrows():
        fund_id = str(row.get("fund_id") or row.get("ticker", "")).strip().upper()
        ticker = str(row.get("ticker") or fund_id).strip().upper()
        cat = str(row.get("category", "")).strip()
        name_zh = str(row.get("name_zh") or row.get("fund_name") or ticker)
        name_en = str(row.get("name_en") or row.get("fund_name") or ticker)
        name = name_zh if language == "zh" else name_en
        cat_name = _category_display(cat, language)

        coverage_status = str(row.get("coverage_status") or "unavailable").strip()
        valid_obs = int(row.get("valid_observations") or 0)

        raw_flow = row.get(window_col)
        has_valid_flow = (
            coverage_status == "validated"
            and raw_flow is not None
            and not pd.isna(raw_flow)
        )
        flow_val = float(raw_flow) if has_valid_flow else None
        flow_str = _format_flow_amount(flow_val, language) if has_valid_flow else tr(language, "Unavailable / Accumulating", "暂不可用／积累中")

        size_val = row.get("size_value")
        has_size = size_val is not None and not pd.isna(size_val) and float(size_val) > 0
        area_val = float(size_val) if has_size else 1.0
        size_basis = str(row.get("size_basis") or "equal_area")
        size_str = _format_size_amount(size_val, language) if has_size else tr(language, "Equal area", "等面积")

        first_d = str(row.get("first_valid_flow_date") or "—")
        latest_d = str(row.get("latest_valid_flow_date") or "—")
        date_range_str = f"{first_d} ~ {latest_d}" if valid_obs > 0 else "—"

        status_label = {
            "validated": tr(language, "Validated", "已核验"),
            "shares_only": tr(language, "Shares only", "仅份额"),
            "unavailable": tr(language, "Unavailable", "暂不可用"),
        }.get(coverage_status, coverage_status)

        leaf_id = f"{cat}_{ticker}"
        display_label = f"<b>{ticker}</b><br>{name}<br>{flow_str}"

        ids.append(leaf_id)
        labels_list.append(display_label)
        parents.append(f"CAT_{cat}")
        values.append(area_val)
        colors.append(flow_val if flow_val is not None else 0.0)
        customdata_list.append([
            ticker,
            name,
            cat_name,
            status_label,
            f"{size_str} ({size_basis})",
            str(valid_obs),
            date_range_str,
            flow_str,
        ])

    valid_flows = [c for c in colors if c != 0.0]
    max_bound = max(abs(min(valid_flows, default=-1e8)), abs(max(valid_flows, default=1e8)), 1e6)

    fig = go.Figure(
        go.Treemap(
            ids=ids,
            labels=labels_list,
            parents=parents,
            values=values,
            branchvalues="remainder",
            marker=dict(
                colors=colors,
                colorscale=FLOW_COLORSCALE,
                cmid=0.0,
                cmin=-max_bound,
                cmax=max_bound,
                colorbar=dict(
                    title=f"{window_label} Flow",
                ),
                line=dict(width=1, color="#FFFFFF"),
            ),
            customdata=customdata_list,
            hovertemplate=(
                "<b>%{customdata[0]} · %{customdata[1]}</b><br>"
                + tr(language, "Category: ", "大类：")
                + "%{customdata[2]}<br>"
                + tr(language, "Status: ", "状态：")
                + "%{customdata[3]}<br>"
                + tr(language, "Fund Size: ", "规模：")
                + "%{customdata[4]}<br>"
                + tr(language, "Valid Obs: ", "有效样本：")
                + "%{customdata[5]}<br>"
                + tr(language, "Observation Window: ", "观测区间：")
                + "%{customdata[6]}<br>"
                + f"{window_label} "
                + tr(language, "Estimated Flow: ", "预估资金流：")
                + "%{customdata[7]}<extra></extra>"
            ),
            textinfo="label",
            textposition="middle center",
        )
    )

    fig.update_layout(
        margin=dict(l=10, r=10, t=30, b=10),
        height=480,
    )

    st.markdown(
        f'<div class="am-chart-title">{tr(language, "ETF Validated Fund Flow Treemap", "ETF 资金流热力图（仅核验样本）")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        tr(
            language,
            f"Rectangle size: NAV-backed estimated assets / equal area · Color: {window_label} net flow (CNY/USD).",
            f"色块面积：NAV预估资产／等面积 · 颜色：{window_label} 净申赎资金流。",
        )
    )
    st.plotly_chart(
        fig,
        width="stretch",
        config={"displaylogo": False, "responsive": True},
        key="hm_flow_treemap",
    )

    # Summary Dataframe
    st.markdown(
        f'<div class="am-chart-title" style="margin-top:16px;">{tr(language, "Flow Detail Table", "资金流明细表")}</div>',
        unsafe_allow_html=True,
    )

    table_rows = []
    for _, row in filtered_df.iterrows():
        ticker = str(row.get("ticker") or row.get("fund_id", "")).strip().upper()
        cat = str(row.get("category", "")).strip()
        name_zh = str(row.get("name_zh") or row.get("fund_name") or ticker)
        name_en = str(row.get("name_en") or row.get("fund_name") or ticker)
        name = name_zh if language == "zh" else name_en
        cat_name = _category_display(cat, language)

        coverage_status = str(row.get("coverage_status") or "unavailable").strip()
        status_label = {
            "validated": tr(language, "Validated", "已核验"),
            "shares_only": tr(language, "Shares only", "仅份额"),
            "unavailable": tr(language, "Unavailable", "暂不可用"),
        }.get(coverage_status, coverage_status)

        size_val = row.get("size_value")
        size_str = _format_size_amount(size_val, language)

        table_rows.append({
            "_ticker": ticker,
            "_name": name,
            "_category": cat_name,
            "_status": status_label,
            "_valid_obs": int(row.get("valid_observations") or 0),
            "_size": size_str,
            "_flow_1d": _format_flow_amount(row.get("flow_1d"), language),
            "_flow_1w": _format_flow_amount(row.get("flow_1w"), language),
            "_flow_1m": _format_flow_amount(row.get("flow_1m"), language),
            "_flow_3m": _format_flow_amount(row.get("flow_3m"), language),
            "_flow_ytd": _format_flow_amount(row.get("flow_ytd"), language),
        })

    col_map = {
        "_ticker": tr(language, "Ticker", "代码"),
        "_name": tr(language, "Name", "基金名称"),
        "_category": tr(language, "Category", "资产大类"),
        "_status": tr(language, "Status", "核验状态"),
        "_valid_obs": tr(language, "Valid Obs", "有效样本数"),
        "_size": tr(language, "Estimated Size", "预估规模"),
        "_flow_1d": tr(language, "1D Flow", "1日流向"),
        "_flow_1w": tr(language, "1W Flow", "1周流向"),
        "_flow_1m": tr(language, "1M Flow", "1月流向"),
        "_flow_3m": tr(language, "3M Flow", "3月流向"),
        "_flow_ytd": tr(language, "YTD Flow", "年初至今"),
    }
    df_table = pd.DataFrame(table_rows).rename(columns=col_map)
    st.dataframe(df_table, hide_index=True, width="stretch")


def render_detail_tab(
    returns_df: pd.DataFrame,
    flows_df: pd.DataFrame,
    prices_df: pd.DataFrame,
    activity_df: pd.DataFrame,
    language: str,
    history_window_choice: str,
) -> None:
    """Render single ETF price/SMA and estimated flow drilldown."""
    # Collect all tickers that have price history
    available_price_tickers: set[str] = set()
    if not prices_df.empty and {"date", "ticker", "close"}.issubset(prices_df.columns):
        available_price_tickers = set(
            prices_df["ticker"].dropna().astype(str).str.strip().str.upper().unique()
        )

    # Collect metadata for known tickers with price history
    tickers_meta: dict[str, dict[str, Any]] = {}
    if not returns_df.empty:
        for _, r in returns_df.iterrows():
            t = str(r.get("ticker", "")).strip().upper()
            if t and t in available_price_tickers:
                tickers_meta[t] = {
                    "name_en": str(r.get("name_en") or r.get("fund_name") or t),
                    "name_zh": str(r.get("name_zh") or r.get("fund_name") or t),
                    "category": str(r.get("category", "")).strip() or "broad_equity",
                    "size_basis": r.get("size_basis"),
                    "size_value": r.get("size_value"),
                }
    if not flows_df.empty:
        for _, r in flows_df.iterrows():
            t = str(r.get("ticker") or r.get("fund_id", "")).strip().upper()
            if t and t in available_price_tickers:
                if t not in tickers_meta:
                    tickers_meta[t] = {
                        "name_en": str(r.get("name_en") or r.get("fund_name") or t),
                        "name_zh": str(r.get("name_zh") or r.get("fund_name") or t),
                        "category": str(r.get("category", "")).strip() or "broad_equity",
                        "size_basis": r.get("size_basis"),
                        "size_value": r.get("size_value"),
                    }
                else:
                    if r.get("size_basis"):
                        tickers_meta[t]["size_basis"] = r.get("size_basis")
                    if r.get("size_value"):
                        tickers_meta[t]["size_value"] = r.get("size_value")

    for t in available_price_tickers:
        if t and t not in tickers_meta:
            tickers_meta[t] = {
                "name_en": t,
                "name_zh": t,
                "category": "broad_equity",
                "size_basis": None,
                "size_value": None,
            }

    if not tickers_meta:
        st.info(
            tr(
                language,
                "No ETF price history available in this artifact.",
                "当前数据快照未包含 ETF 历史价格数据。",
            )
        )
        return

    all_tickers = sorted(tickers_meta.keys())

    ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1, 1, 1])
    with ctrl_col1:
        selected_cat = st.selectbox(
            tr(language, "Category Filter", "大类筛选"),
            HEATMAP_CATEGORY_KEYS,
            index=0,
            format_func=lambda k: HEATMAP_CATEGORY_LABELS[k][language],
            key="hm_detail_cat",
        )

    selectable_tickers = [
        t for t in all_tickers
        if selected_cat == "all" or tickers_meta[t].get("category") == selected_cat
    ] or all_tickers

    with ctrl_col2:
        selected_ticker = st.selectbox(
            tr(language, "Select ETF", "选择 ETF 标的"),
            selectable_tickers,
            index=0,
            format_func=lambda t: f"{t} - {tickers_meta[t]['name_zh'] if language == 'zh' else tickers_meta[t]['name_en']}",
            key="hm_detail_ticker",
        )

    with ctrl_col3:
        selected_window = st.selectbox(
            tr(language, "History Window", "历史窗口"),
            list(HISTORY_WINDOWS.keys()),
            index=list(HISTORY_WINDOWS.keys()).index(history_window_choice)
            if history_window_choice in HISTORY_WINDOWS
            else 0,
            key="hm_detail_window",
        )

    # Extract price history for selected ticker
    ticker_prices = prices_df[
        prices_df["ticker"].astype(str).str.strip().str.upper() == selected_ticker
    ].copy()
    ticker_prices["date"] = pd.to_datetime(ticker_prices["date"], errors="coerce")
    ticker_prices["close"] = pd.to_numeric(ticker_prices["close"], errors="coerce")
    ticker_prices = (
        ticker_prices.dropna(subset=["date", "close"])
        .loc[lambda df: df["close"].gt(0)]
        .sort_values("date")
        .drop_duplicates("date", keep="last")
        .reset_index(drop=True)
    )

    if ticker_prices.empty:
        st.info(
            tr(
                language,
                f"No price history found for {selected_ticker}.",
                f"暂未找到 {selected_ticker} 的历史价格数据。",
            )
        )
        return

    # Calculate SMAs
    ticker_prices["sma20"] = ticker_prices["close"].rolling(20).mean()
    ticker_prices["sma50"] = ticker_prices["close"].rolling(50).mean()
    ticker_prices["sma200"] = ticker_prices["close"].rolling(200).mean()

    # Filter price by window
    filtered_prices, _ = filter_history_window(ticker_prices, "date", selected_window)

    # Extract flow history for selected ticker
    ticker_flows = pd.DataFrame()
    if not activity_df.empty:
        date_col = "observation_date" if "observation_date" in activity_df.columns else "date"
        flow_col = "estimated_flow_cny" if "estimated_flow_cny" in activity_df.columns else "estimated_flow"
        id_col = "fund_id" if "fund_id" in activity_df.columns else "ticker"
        if date_col in activity_df.columns and flow_col in activity_df.columns and id_col in activity_df.columns:
            sub_act = activity_df[
                activity_df[id_col].astype(str).str.strip().str.upper() == selected_ticker
            ].copy()
            if not sub_act.empty:
                sub_act["date"] = pd.to_datetime(sub_act[date_col], errors="coerce")
                sub_act["flow"] = pd.to_numeric(sub_act[flow_col], errors="coerce")
                if "flow_status" in sub_act.columns:
                    sub_act = sub_act[sub_act["flow_status"] == "validated"]
                ticker_flows = (
                    sub_act.dropna(subset=["date", "flow"])
                    .sort_values("date")
                    .drop_duplicates("date", keep="last")
                    .reset_index(drop=True)
                )

    if not ticker_flows.empty:
        filtered_flows, _ = filter_history_window(ticker_flows, "date", selected_window)
    else:
        filtered_flows = pd.DataFrame()

    has_flow = not filtered_flows.empty and len(filtered_flows) > 0

    t_meta = tickers_meta[selected_ticker]
    ticker_name = t_meta["name_zh"] if language == "zh" else t_meta["name_en"]
    category_name = _category_display(t_meta.get("category", "broad_equity"), language)

    # Flow basis note
    flow_meta_row = (
        flows_df[flows_df["ticker"].astype(str).str.upper() == selected_ticker]
        if not flows_df.empty and "ticker" in flows_df.columns
        else pd.DataFrame()
    )
    if flow_meta_row.empty and not flows_df.empty and "fund_id" in flows_df.columns:
        flow_meta_row = flows_df[flows_df["fund_id"].astype(str).str.upper() == selected_ticker]

    if not flow_meta_row.empty:
        cov_status = str(flow_meta_row.iloc[0].get("coverage_status") or "unavailable")
        basis_str = str(flow_meta_row.iloc[0].get("size_basis") or "nav_estimate")
        valid_cnt = int(flow_meta_row.iloc[0].get("valid_observations") or 0)
    else:
        cov_status = "unavailable"
        basis_str = "—"
        valid_cnt = 0

    if cov_status == "validated":
        basis_desc = tr(
            language,
            f"Data basis: Exchange shares × published NAV (Validated · {valid_cnt} obs)",
            f"数据依据：交易所官方份额变动 × 估值NAV（已核验 · {valid_cnt} 个观测点）",
        )
    elif basis_str == "market_cap_proxy":
        basis_desc = tr(
            language,
            f"Data basis: Sampled market cap proxy (Accumulating · {valid_cnt} obs)",
            f"数据依据：采样市值代理（积累中 · {valid_cnt} 个观测点）",
        )
    else:
        basis_desc = tr(
            language,
            "Data basis: Daily adjusted close prices (Price only)",
            "数据依据：每日除权除息收盘价（仅价格）",
        )

    st.markdown(
        f'<div class="am-chart-title">{selected_ticker} · {ticker_name} ({category_name})</div>',
        unsafe_allow_html=True,
    )
    st.caption(basis_desc)

    if has_flow:
        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.08,
            row_heights=[0.7, 0.3],
        )

        fig.add_trace(
            go.Scatter(
                x=filtered_prices["date"],
                y=filtered_prices["close"],
                name=tr(language, "Close", "收盘价"),
                line=dict(color="#2563EB", width=1.5),
            ),
            row=1,
            col=1,
        )
        if filtered_prices["sma20"].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=filtered_prices["date"],
                    y=filtered_prices["sma20"],
                    name="SMA20",
                    line=dict(color="#F59E0B", width=1.2),
                ),
                row=1,
                col=1,
            )
        if filtered_prices["sma50"].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=filtered_prices["date"],
                    y=filtered_prices["sma50"],
                    name="SMA50",
                    line=dict(color="#8B5CF6", width=1.2),
                ),
                row=1,
                col=1,
            )
        if filtered_prices["sma200"].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=filtered_prices["date"],
                    y=filtered_prices["sma200"],
                    name="SMA200",
                    line=dict(color="#10B981", width=1.2),
                ),
                row=1,
                col=1,
            )

        bar_colors = [
            "#10B981" if f >= 0 else "#EF4444"
            for f in filtered_flows["flow"]
        ]
        fig.add_trace(
            go.Bar(
                x=filtered_flows["date"],
                y=filtered_flows["flow"],
                name=tr(language, "Estimated Flow", "预估资金流"),
                marker_color=bar_colors,
            ),
            row=2,
            col=1,
        )

        fig.update_yaxes(title_text=tr(language, "Price", "价格"), row=1, col=1)
        fig.update_yaxes(title_text=tr(language, "Flow", "资金流"), row=2, col=1)
        fig.update_layout(
            margin=dict(l=10, r=10, t=30, b=10),
            height=500,
            hovermode="x unified",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0,
            ),
        )
        st.plotly_chart(
            fig,
            width="stretch",
            config={"displaylogo": False, "responsive": True},
            key=f"hm_detail_chart_{selected_ticker}",
        )
    else:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=filtered_prices["date"],
                y=filtered_prices["close"],
                name=tr(language, "Close", "收盘价"),
                line=dict(color="#2563EB", width=1.5),
            )
        )
        if filtered_prices["sma20"].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=filtered_prices["date"],
                    y=filtered_prices["sma20"],
                    name="SMA20",
                    line=dict(color="#F59E0B", width=1.2),
                )
            )
        if filtered_prices["sma50"].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=filtered_prices["date"],
                    y=filtered_prices["sma50"],
                    name="SMA50",
                    line=dict(color="#8B5CF6", width=1.2),
                )
            )
        if filtered_prices["sma200"].notna().any():
            fig.add_trace(
                go.Scatter(
                    x=filtered_prices["date"],
                    y=filtered_prices["sma200"],
                    name="SMA200",
                    line=dict(color="#10B981", width=1.2),
                )
            )
        fig.update_yaxes(title_text=tr(language, "Price", "价格"))
        fig.update_layout(
            margin=dict(l=10, r=10, t=30, b=10),
            height=400,
            hovermode="x unified",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0,
            ),
        )
        st.plotly_chart(
            fig,
            width="stretch",
            config={"displaylogo": False, "responsive": True},
            key=f"hm_detail_chart_{selected_ticker}",
        )
        st.info(
            tr(
                language,
                "Fund flow data is not yet available or is accumulating for this ETF.",
                "该 ETF 暂无已核验的资金流数据或正在积累观察样本。",
            )
        )


def render_heatmaps(
    artifact: dict[str, Any],
    labels: dict[str, Any],
    language: str,
    window: str,
) -> None:
    """Render the Heat Maps page with three subtabs."""
    st.markdown(
        f'<div class="am-page-title">{tr(language, "Heat Maps", "热力图")}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        tr(
            language,
            "Cross-market ETF multi-horizon performance, validated fund flows, and single-ETF trend/activity drilldown.",
            "跨市场 ETF 多周期表现、资金流热力（仅核验样本）与单标的量价及流向详情。",
        )
    )

    datasets = artifact.get("snapshot", {}).get("datasets", {})
    returns_df = pd.DataFrame(datasets.get("etf_heatmap_returns", []))
    flows_df = pd.DataFrame(datasets.get("etf_heatmap_flows", []))
    heatmap_prices = pd.DataFrame(datasets.get("heatmap_etf_price_daily", []))
    china_etf_prices = pd.DataFrame(datasets.get("etf_price_daily_tail", []))
    activity_df = pd.DataFrame(datasets.get("etf_fund_activity_daily", []))

    # Combine price datasets to ensure all funds with price history are supported
    price_frames = []
    if not heatmap_prices.empty and {"date", "ticker", "close"}.issubset(heatmap_prices.columns):
        price_frames.append(heatmap_prices[["date", "ticker", "close"]])
    if not china_etf_prices.empty and {"date", "ticker", "close"}.issubset(china_etf_prices.columns):
        price_frames.append(china_etf_prices[["date", "ticker", "close"]])
    prices_df = pd.concat(price_frames, ignore_index=True) if price_frames else pd.DataFrame()

    tab1, tab2, tab3 = st.tabs(
        [
            tr(language, "Market Performance", "市场表现"),
            tr(language, "ETF Fund Flow", "ETF资金流"),
            tr(language, "ETF Detail", "ETF明细"),
        ]
    )

    with tab1:
        render_performance_tab(returns_df, language)

    with tab2:
        render_flow_tab(flows_df, language)

    with tab3:
        render_detail_tab(returns_df, flows_df, prices_df, activity_df, language, window)
