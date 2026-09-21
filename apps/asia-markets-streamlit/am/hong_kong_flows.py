"""Hong Kong institutional-data context page.

This page is intentionally complementary to ETF Monitor.  It renders HKEX
short inventory, HKMA liquidity and MSCI index-review context, while linking
back to ETF Monitor for the canonical Eastmoney Southbound Stock Connect view.
"""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .artifacts import ARTIFACT_LOAD_ERRORS, artifact_mtime_ns, load_artifact
from .core import (
    frame_for_dataset,
    observation_date_label,
    render_header,
    section_heading,
    tr,
    unavailable_artifact,
)


ARTIFACT_SLUG = "hong-kong-flows"


def _number(value: Any, *, decimals: int = 1) -> str:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return "—"
    return f"{float(parsed):,.{decimals}f}"


def _shares(value: Any) -> str:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return "—"
    absolute = abs(float(parsed))
    if absolute >= 1_000_000_000:
        return f"{float(parsed) / 1_000_000_000:,.2f}bn"
    if absolute >= 1_000_000:
        return f"{float(parsed) / 1_000_000:,.1f}m"
    return f"{float(parsed):,.0f}"


def _latest(frame: pd.DataFrame, date_column: str) -> pd.Series:
    if frame.empty or date_column not in frame.columns:
        return pd.Series(dtype="object")
    ordered = frame.copy()
    ordered["_date"] = pd.to_datetime(ordered[date_column], errors="coerce")
    ordered = ordered.dropna(subset=["_date"]).sort_values("_date")
    return ordered.iloc[-1] if not ordered.empty else pd.Series(dtype="object")


def _load_page_artifact(language: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        current = load_artifact(ARTIFACT_SLUG, "en", artifact_mtime_ns(ARTIFACT_SLUG, "en"))
    except ARTIFACT_LOAD_ERRORS as error:
        reason = f"{type(error).__name__}: {error}"
        current = unavailable_artifact(ARTIFACT_SLUG, reason)
        return current, current
    if language != "zh":
        return current, current
    try:
        localized = load_artifact(
            ARTIFACT_SLUG,
            "zh",
            artifact_mtime_ns(ARTIFACT_SLUG, "zh"),
        )
    except ARTIFACT_LOAD_ERRORS:
        localized = current
    return current, localized


def _render_canonical_southbound_reference(language: str) -> None:
    st.info(
        tr(
            language,
            "Southbound Stock Connect is intentionally shown once: ETF Monitor remains the canonical flow chart and KPI view. This page adds institutional context around it, rather than copying the same history.",
            "南下资金只在一个地方展示：ETF监控仍是唯一的资金流图表和核心指标主视图。本页只补充机构数据背景，不复制同一段历史。",
        )
    )
    st.markdown(
        f"[{escape(tr(language, 'Open the canonical Southbound view in ETF Monitor', '打开ETF监控中的南下资金主视图'))}](./etf-monitor)"
    )


def _render_short_inventory(frame: pd.DataFrame, language: str) -> None:
    section_heading(
        language,
        "HKEX short inventory",
        "HKEX卖空库存",
        "Official daily counts and shares available. Short-selling value and ratio are deliberately omitted because their normalized fields are empty or unreliable.",
        "官方日度卖空证券数量和可卖空股数。卖空金额与比例的标准化字段为空或不可靠，因此不展示。",
    )
    if frame.empty:
        st.warning(tr(language, "HKEX short-inventory data is unavailable.", "HKEX卖空库存数据不可用。"))
        return
    latest = _latest(frame, "trade_date")
    metric_columns = st.columns(3)
    with metric_columns[0]:
        st.metric(
            tr(language, "Shortable securities", "可卖空证券数"),
            _number(latest.get("short_selling_security_count"), decimals=0),
            observation_date_label(latest.get("trade_date"), language),
        )
    with metric_columns[1]:
        st.metric(
            tr(language, "Shares available", "可卖空股数"),
            _shares(latest.get("short_selling_shares_available")),
            observation_date_label(latest.get("trade_date"), language),
        )
    with metric_columns[2]:
        st.metric(
            tr(language, "History", "历史记录"),
            f"{len(frame):,}",
            tr(language, "daily observations", "日度观察"),
        )

    chart = frame.copy()
    chart["trade_date"] = pd.to_datetime(chart["trade_date"], errors="coerce")
    chart["short_selling_security_count"] = pd.to_numeric(
        chart["short_selling_security_count"], errors="coerce"
    )
    chart["short_selling_shares_available"] = pd.to_numeric(
        chart["short_selling_shares_available"], errors="coerce"
    )
    chart = chart.dropna(subset=["trade_date"])
    figure = go.Figure()
    if chart["short_selling_security_count"].notna().any():
        figure.add_trace(
            go.Scatter(
                x=chart["trade_date"],
                y=chart["short_selling_security_count"],
                name=tr(language, "Shortable securities", "可卖空证券数"),
                mode="lines",
            )
        )
    if chart["short_selling_shares_available"].notna().any():
        figure.add_trace(
            go.Scatter(
                x=chart["trade_date"],
                y=chart["short_selling_shares_available"] / 1_000_000_000,
                name=tr(language, "Shares available (bn)", "可卖空股数（十亿）"),
                mode="lines",
                yaxis="y2",
            )
        )
    figure.update_layout(
        height=330,
        margin={"l": 12, "r": 12, "t": 24, "b": 12},
        yaxis={"title": tr(language, "Securities", "证券数")},
        yaxis2={
            "title": tr(language, "Shares (bn)", "股数（十亿）"),
            "overlaying": "y",
            "side": "right",
        },
        legend={"orientation": "h", "y": 1.1},
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})

    table = frame.copy().sort_values("trade_date", ascending=False).head(20)
    table[tr(language, "Trade date", "交易日")] = table["trade_date"].map(
        lambda value: observation_date_label(value, language)
    )
    table[tr(language, "Shortable securities", "可卖空证券数")] = table[
        "short_selling_security_count"
    ].map(lambda value: _number(value, decimals=0))
    table[tr(language, "Shares available", "可卖空股数")] = table[
        "short_selling_shares_available"
    ].map(_shares)
    columns = [
        tr(language, "Trade date", "交易日"),
        tr(language, "Shortable securities", "可卖空证券数"),
        tr(language, "Shares available", "可卖空股数"),
    ]
    st.dataframe(table[columns], hide_index=True, width="stretch")


def _render_hkma(frame: pd.DataFrame, language: str) -> None:
    section_heading(
        language,
        "HKMA liquidity and funding",
        "HKMA流动性与资金",
        "Selected daily HIBOR, Aggregate Balance and trade-weighted-index series. The artifact keeps the last five years; source tiers remain visible.",
        "选取日度HIBOR、总结余和贸易加权指数。数据快照保留最近五年，并保留来源层级。",
    )
    if frame.empty:
        st.warning(tr(language, "HKMA liquidity data is unavailable.", "HKMA流动性数据不可用。"))
        return
    labels = "series_label_zh" if language == "zh" else "series_label_en"
    latest_rows = (
        frame.assign(_date=pd.to_datetime(frame["date"], errors="coerce"))
        .dropna(subset=["_date"])
        .sort_values("_date")
        .groupby("series_id", as_index=False)
        .tail(1)
    )
    metric_columns = st.columns(4)
    for column, (_series_id, label_en, label_zh) in zip(
        metric_columns,
        (
            ("HKMA_HIBOR_ON", "Overnight HIBOR", "隔夜HIBOR"),
            ("HKMA_HIBOR_1M", "1-month HIBOR", "1个月HIBOR"),
            ("HKMA_AGGREGATE_BALANCE", "Aggregate Balance", "总结余"),
            ("HKMA_TWI", "Trade-weighted index", "贸易加权指数"),
        ),
    ):
        row = latest_rows[latest_rows["series_id"].eq(_series_id)]
        latest_row = row.iloc[-1] if not row.empty else pd.Series(dtype="object")
        with column:
            st.metric(
                tr(language, label_en, label_zh),
                _number(latest_row.get("value")),
                observation_date_label(latest_row.get("date"), language),
            )

    chart = frame.copy()
    chart["date"] = pd.to_datetime(chart["date"], errors="coerce")
    chart["value"] = pd.to_numeric(chart["value"], errors="coerce")
    chart = chart.dropna(subset=["date", "value"])
    hibor = chart[chart["series_id"].isin(["HKMA_HIBOR_ON", "HKMA_HIBOR_1M"])]
    balance = chart[chart["series_id"].eq("HKMA_AGGREGATE_BALANCE")]
    twi = chart[chart["series_id"].eq("HKMA_TWI")]
    left, right = st.columns(2)
    with left:
        figure = go.Figure()
        for series_id in ("HKMA_HIBOR_ON", "HKMA_HIBOR_1M"):
            rows = hibor[hibor["series_id"].eq(series_id)]
            if rows.empty:
                continue
            label = rows[labels].iloc[-1]
            figure.add_trace(go.Scatter(x=rows["date"], y=rows["value"], name=label, mode="lines"))
        figure.update_layout(
            height=300,
            margin={"l": 12, "r": 12, "t": 24, "b": 12},
            yaxis_title=tr(language, "Percent", "百分比"),
            legend={"orientation": "h", "y": 1.1},
        )
        st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    with right:
        figure = go.Figure()
        if not balance.empty:
            figure.add_trace(
                go.Scatter(
                    x=balance["date"],
                    y=balance["value"],
                    name=tr(language, "Aggregate Balance", "总结余"),
                    mode="lines",
                )
            )
        if not twi.empty:
            figure.add_trace(
                go.Scatter(
                    x=twi["date"],
                    y=twi["value"],
                    name=tr(language, "Trade-weighted index", "贸易加权指数"),
                    mode="lines",
                    yaxis="y2",
                )
            )
        figure.update_layout(
            height=300,
            margin={"l": 12, "r": 12, "t": 24, "b": 12},
            yaxis={"title": tr(language, "HK$ mn", "百万港元")},
            yaxis2={
                "title": tr(language, "Index", "指数"),
                "overlaying": "y",
                "side": "right",
            },
            legend={"orientation": "h", "y": 1.1},
        )
        st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})

    st.caption(
        tr(
            language,
            "No interpolation or cross-source replacement is performed. A missing source day remains missing.",
            "不做插值，也不以其他来源替换。来源缺失的日期仍保持缺失。",
        )
    )


def _render_msci(events: pd.DataFrame, cycles: pd.DataFrame, language: str) -> None:
    section_heading(
        language,
        "MSCI HK/CN index-review context",
        "MSCI港中指数审议背景",
        "The latest eight review cycles are shown as unlinked index events. Public identifiers are not populated, so this is not a security-level rebalance or position map.",
        "展示最近八个审议周期的未关联指数事件。公开标识符没有填充，因此这不是个股级调仓或持仓地图。",
    )
    if events.empty:
        st.warning(tr(language, "MSCI HK/CN review data is unavailable.", "MSCI港中指数审议数据不可用。"))
        return
    latest_cycle = cycles.iloc[-1] if not cycles.empty else pd.Series(dtype="object")
    metric_columns = st.columns(4)
    with metric_columns[0]:
        st.metric(
            tr(language, "Latest cycle", "最近周期"),
            str(latest_cycle.get("review_cycle") or "—").replace("_", " "),
        )
    with metric_columns[1]:
        st.metric(
            tr(language, "Effective date", "生效日"),
            observation_date_label(latest_cycle.get("effective_date"), language),
        )
    with metric_columns[2]:
        st.metric(tr(language, "Events in latest cycle", "最近周期事件数"), _number(latest_cycle.get("event_count"), decimals=0))
    with metric_columns[3]:
        st.metric(tr(language, "Cycles shown", "展示周期数"), f"{len(cycles):,}")

    cycle_table = cycles.copy().sort_values("effective_date", ascending=False)
    cycle_table[tr(language, "Review cycle", "审议周期")] = cycle_table["review_cycle"].str.replace("_", " ", regex=False)
    cycle_table[tr(language, "Announcement", "公告日")] = cycle_table["announcement_date"].map(
        lambda value: observation_date_label(value, language)
    )
    cycle_table[tr(language, "Effective", "生效日")] = cycle_table["effective_date"].map(
        lambda value: observation_date_label(value, language)
    )
    cycle_table[tr(language, "Events", "事件数")] = cycle_table["event_count"].map(lambda value: _number(value, decimals=0))
    cycle_table[tr(language, "Adds", "新增")] = cycle_table["additions"].map(lambda value: _number(value, decimals=0))
    cycle_table[tr(language, "Deletes", "删除")] = cycle_table["deletions"].map(lambda value: _number(value, decimals=0))
    cycle_columns = [
        tr(language, "Review cycle", "审议周期"),
        tr(language, "Announcement", "公告日"),
        tr(language, "Effective", "生效日"),
        tr(language, "Events", "事件数"),
        tr(language, "Adds", "新增"),
        tr(language, "Deletes", "删除"),
    ]
    st.dataframe(cycle_table[cycle_columns], hide_index=True, width="stretch")
    with st.expander(tr(language, "Recent unlinked index events", "最近未关联指数事件"), expanded=False):
        recent = events.copy().sort_values(["effective_date", "index_name", "security_name"], ascending=False).head(120)
        recent[tr(language, "Effective", "生效日")] = recent["effective_date"].map(
            lambda value: observation_date_label(value, language)
        )
        recent[tr(language, "Index", "指数")] = recent["index_name"]
        recent[tr(language, "Country", "国家/地区")] = recent["country"]
        recent[tr(language, "Action", "动作")] = recent["action"]
        recent[tr(language, "Security name", "证券名称")] = recent["security_name"]
        recent[tr(language, "Link status", "关联状态")] = recent["link_status"]
        columns = [
            tr(language, "Effective", "生效日"),
            tr(language, "Index", "指数"),
            tr(language, "Country", "国家/地区"),
            tr(language, "Action", "动作"),
            tr(language, "Security name", "证券名称"),
            tr(language, "Link status", "关联状态"),
        ]
        st.dataframe(recent[columns], hide_index=True, width="stretch")


def _render_source_health(frame: pd.DataFrame, language: str) -> None:
    section_heading(
        language,
        "Hong Kong context source health",
        "香港数据来源健康度",
        "These rows describe the local snapshot. The Southbound row is a reference to ETF Monitor, not a second data emission.",
        "这些行描述本地数据快照。南下资金行只是指向ETF监控的引用，不是第二次输出数据。",
    )
    if frame.empty:
        st.warning(tr(language, "Source-health metadata is unavailable.", "来源健康度元数据不可用。"))
        return
    show = frame.copy()
    renames = {
        "source": tr(language, "Source", "来源"),
        "status": tr(language, "Status", "状态"),
        "latest_observation": tr(language, "Latest observation", "最新观察"),
        "coverage_start": tr(language, "Coverage start", "覆盖起点"),
        "records": tr(language, "Records", "记录数"),
        "notes": tr(language, "Notes", "说明"),
    }
    show = show.rename(columns=renames)
    st.dataframe(show[list(renames.values())], hide_index=True, width="stretch")


def render_hong_kong_flows(language: str) -> None:
    artifact, labels = _load_page_artifact(language)
    if artifact.get("snapshot", {}).get("status") == "blocked":
        st.warning(
            tr(
                language,
                "The Hong Kong institutional context artifact is unavailable. Run the local artifact builder after the normalized free-data lanes are present.",
                "香港机构数据背景快照不可用。请在免费数据标准化数据存在后运行本地 artifact builder。",
            )
        )
    render_header(
        artifact,
        labels,
        language,
        "market",
        title_override=tr(language, "Hong Kong Flows & Liquidity", "香港资金流与流动性"),
        description_override=tr(
            language,
            "HKEX short inventory, HKMA liquidity and MSCI HK/CN index-review context. Southbound Stock Connect remains canonical in ETF Monitor.",
            "HKEX卖空库存、HKMA流动性与MSCI港中指数审议背景。南下资金仍以ETF监控为唯一主视图。",
        ),
    )
    _render_canonical_southbound_reference(language)
    st.divider()
    _render_short_inventory(frame_for_dataset(artifact, "hkex_short_inventory_daily"), language)
    _render_hkma(frame_for_dataset(artifact, "hkma_liquidity_daily"), language)
    _render_msci(
        frame_for_dataset(artifact, "msci_index_events"),
        frame_for_dataset(artifact, "msci_review_cycles"),
        language,
    )
    _render_source_health(frame_for_dataset(artifact, "source_health"), language)
