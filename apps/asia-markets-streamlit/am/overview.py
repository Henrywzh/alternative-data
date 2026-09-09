"""Terminal overview page and sector pulse cards.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from .config import OVERVIEW_FEATURED_CHARTS, OVERVIEW_PULSE_CONFIG, PAIR_CARD_HEIGHT, PALETTE, SECTORS

from .core import latest_metric_reading, latest_series_reading, observation_date_label, parse_period, render_line_chart, section_heading, source_health_frame, sparkline_context, sparkline_svg, tr
from .regime_labels import (
    COT_LABELS_ZH,
    FOMC_DIST_LABELS_ZH,
    REGIME_DIST_LABELS_ZH,
    REGIME_DOMAIN_LABELS,
    REGIME_EXPOSURE_LABELS,
    REGIME_FRESHNESS_LABELS_ZH,
    REGIME_FRESHNESS_OK,
    REGIME_INDICATOR_LABELS,
    REGIME_RETURN_HORIZONS,
    REGIME_SERIES_LABELS,
    REGIME_SERIES_LABELS_ZH,
)


def set_app_page(page_key: str) -> None:
    st.session_state["page"] = page_key


def overview_source_summary(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
) -> dict[str, int]:
    total = healthy = attention = problem = 0
    for sector_key, artifact in artifacts.items():
        health = source_health_frame(artifact)
        if health.empty:
            status_values = ["Ready"] * len(labels.get(sector_key, artifact).get("sources", []))
        else:
            status_values = health.get("status", pd.Series(dtype="object")).astype(str).tolist()
        for value in status_values:
            normalized = value.casefold()
            total += 1
            if normalized in {"healthy", "ready", "live", "success"}:
                healthy += 1
            elif normalized in {"partial", "warning", "degraded", "stale"}:
                attention += 1
            else:
                problem += 1
    return {"total": total, "healthy": healthy, "attention": attention, "problem": problem}


def sector_source_status(artifact: dict[str, Any], label_artifact: dict[str, Any], language: str) -> str:
    health = source_health_frame(artifact)
    if health.empty:
        statuses = ["ready"] * len(label_artifact.get("sources", []))
    else:
        statuses = health.get("status", pd.Series(dtype="object")).astype(str).str.casefold().tolist()
    if not statuses:
        return tr(language, "Snapshot", "数据快照")
    if all(value in {"healthy", "ready", "live", "success"} for value in statuses):
        return tr(language, "Ready", "可用")
    if any(value in {"partial", "warning", "degraded", "stale"} for value in statuses):
        return tr(language, "Attention", "需留意")
    return tr(language, "Problem", "有问题")


def latest_artifact_date(artifacts: dict[str, dict[str, Any]], language: str) -> str:
    values = [
        artifact.get("package_info", {}).get("dataAsOf")
        for artifact in artifacts.values()
        if artifact.get("package_info", {}).get("dataAsOf")
    ]
    if not values:
        return "—"
    parsed = [parse_period(value) for value in values]
    parsed = [value for value in parsed if not pd.isna(value)]
    if not parsed:
        return str(max(values))
    return observation_date_label(max(parsed), language)


def render_overview_header(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
) -> None:
    summary = overview_source_summary(artifacts, labels)
    latest = latest_artifact_date(artifacts, language)
    status_items = [
        (
            tr(language, "Connected sectors", "已接入板块"),
            f"{len(artifacts)}",
            tr(language, "Detailed pages available", "已有详细板块页面"),
        ),
        (
            tr(language, "Source feeds", "来源数据流"),
            f"{summary['total']}",
            tr(language, "Across current sectors", "覆盖当前板块"),
        ),
        (
            tr(language, "Ready feeds", "可用数据流"),
            f"{summary['healthy']}/{summary['total']}" if summary["total"] else "—",
            tr(language, "Build-validated", "已通过构建验证"),
        ),
        (
            tr(language, "Latest artifact", "最新数据快照"),
            latest,
            tr(language, "Individual metrics have their own dates", "各指标仍保留自己的观察日期"),
        ),
    ]
    cards = "".join(
        f'<div class="am-overview-status-item"><div class="am-overview-status-label">{escape(label)}</div>'
        f'<div class="am-overview-status-value">{escape(value)}</div>'
        f'<div class="am-overview-status-note">{escape(note)}</div></div>'
        for label, value, note in status_items
    )
    st.markdown(f'<div class="am-overview-status">{cards}</div>', unsafe_allow_html=True)


def render_sector_pulse(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
) -> None:
    section_heading(
        language,
        "Sector pulse",
        "板块脉搏",
        "A compact reading for each connected sector; open the sector page for full detail.",
        "每个已接入板块只保留一组核心读数；完整细节请进入板块页面。",
    )
    columns = st.columns(2 if len(artifacts) > 1 else 1)
    for index, (sector_key, artifact) in enumerate(artifacts.items()):
        config = OVERVIEW_PULSE_CONFIG.get(sector_key, {})
        sector = SECTORS.get(sector_key, {})
        label_artifact = labels.get(sector_key, artifact)
        name = sector.get("name_zh" if language == "zh" else "name_en", sector_key)
        status = sector_source_status(artifact, label_artifact, language)
        as_of = artifact.get("package_info", {}).get("dataAsOf", "—")
        as_of = observation_date_label(as_of, language)
        metric_blocks: list[str] = []
        for metric in config.get("metrics", ())[:3]:
            if metric.get("series"):
                value, date = latest_series_reading(
                    artifact,
                    metric.get("chart_id", "immd_net_flow_chart"),
                    metric["field"],
                    metric.get("format", "number"),
                    language,
                )
                label = metric["label_zh"] if language == "zh" else metric["label_en"]
            else:
                label, value, date = latest_metric_reading(
                    artifact,
                    metric["dataset"],
                    metric["field"],
                    metric.get("format", "number"),
                    label_en=metric["label_en"],
                    label_zh=metric["label_zh"],
                    language=language,
                )
            if value == "—":
                continue
            metric_blocks.append(
                f'<div class="am-pulse-metric"><div class="am-pulse-label">{escape(label)}</div>'
                f'<div class="am-pulse-value">{escape(value)}</div>'
                f'<div class="am-pulse-asof">{escape(date)}</div></div>'
            )
        sparkline = config.get("sparkline")
        sparkline_markup = ""
        sparkline_context_markup = ""
        if sparkline:
            sparkline_frame, sparkline_title, sparkline_latest, sparkline_range, sparkline_note = sparkline_context(
                artifact,
                sparkline,
                language,
            )
            if not sparkline_frame.empty:
                sparkline_context_markup = (
                    f'<div class="am-pulse-sparkline-title">{escape(sparkline_title)}</div>'
                    f'<div class="am-pulse-sparkline-meta">'
                    f'{escape(tr(language, "Latest", "最新"))} {escape(sparkline_latest)} · '
                    f'{escape(str(len(sparkline_frame)))} '
                    f'{escape(tr(language, "plotted observations", "个观察值"))} · '
                    f'{escape(sparkline_range)}</div>'
                    f'<div class="am-pulse-sparkline-note">{escape(sparkline_note)}</div>'
                )
                sparkline_markup = sparkline_svg(
                    sparkline_frame,
                    color=PALETTE[index % len(PALETTE)],
                )
        with columns[index % len(columns)]:
            with st.container(border=True):
                region_en, region_zh = ("Global", "全球") if sector_key == "regime" else ("Hong Kong", "香港")
                st.markdown(
                    f'<div class="am-pulse-title">{escape(name)}</div>'
                    f'<div class="am-pulse-meta">{escape(tr(language, region_en, region_zh))} · '
                    f'{escape(status)} · {escape(tr(language, "artifact through", "数据截至"))} {escape(as_of)}</div>',
                    unsafe_allow_html=True,
                )
                if metric_blocks:
                    st.markdown(
                        f'<div class="am-pulse-metrics">{"".join(metric_blocks)}</div>',
                        unsafe_allow_html=True,
                    )
                if sparkline_markup:
                    st.markdown(f"{sparkline_context_markup}{sparkline_markup}", unsafe_allow_html=True)
                st.button(
                    tr(language, f"Open {sector.get('short_en', name)}", f"打开{sector.get('short_zh', name)}"),
                    key=f"overview_open_{sector_key}",
                    width="stretch",
                    on_click=set_app_page,
                    args=(sector_key,),
                )


def render_featured_trends(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
    window: str,
) -> None:
    _ = (artifacts, labels, window)
    section_heading(
        language,
        "Featured trends",
        "精选走势",
        "Reserved for higher-frequency derived signals after data ingestion and validation.",
        "待高频数据接入及派生信号验证后再展示。",
    )
    if not OVERVIEW_FEATURED_CHARTS:
        return
    columns = st.columns(2)
    for index, chart in enumerate(OVERVIEW_FEATURED_CHARTS[:2]):
        sector_key = chart["sector"]
        if sector_key not in artifacts:
            continue
        with columns[index]:
            with st.container(height=PAIR_CARD_HEIGHT, border=True):
                sector = SECTORS[sector_key]
                st.markdown(
                    f'<div class="am-kicker">{escape(sector["short_zh" if language == "zh" else "short_en"])}</div>',
                    unsafe_allow_html=True,
                )
                st.caption(tr(language, chart["note_en"], chart["note_zh"]))
                render_line_chart(
                    artifacts[sector_key],
                    labels[sector_key],
                    chart["chart_id"],
                    language,
                    window,
                    views=chart["views"],
                    periods_per_year=chart["periods_per_year"],
                    change_mode=chart["change_mode"],
                    height=chart["height"],
                )
                st.button(
                    tr(language, f"Open {sector['short_en']}", f"打开{sector['short_zh']}"),
                    key=f"overview_featured_open_{sector_key}",
                    width="stretch",
                    on_click=set_app_page,
                    args=(sector_key,),
                )


def render_overview_health_summary(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
) -> None:
    section_heading(
        language,
        "Source health",
        "来源健康度",
        "Overview shows only the compact status; the full source table stays on Source Health.",
        "总览只显示摘要；完整来源表保留在来源健康度页面。",
    )
    summary = overview_source_summary(artifacts, labels)
    with st.container(border=True):
        columns = st.columns(4)
        values = [
            (tr(language, "Total feeds", "数据流总数"), summary["total"]),
            (tr(language, "Ready", "可用"), summary["healthy"]),
            (tr(language, "Attention", "需留意"), summary["attention"]),
            (tr(language, "Problem", "有问题"), summary["problem"]),
        ]
        for column, (label, value) in zip(columns, values):
            with column:
                st.markdown(
                    f'<div class="am-health-value">{escape(str(value))}</div>'
                    f'<div class="am-health-label">{escape(label)}</div>',
                    unsafe_allow_html=True,
                )
        st.caption(
            tr(
                language,
                "Source observation dates remain mixed by cadence; inspect Source Health for dataset-level detail.",
                "不同来源的观察日期按各自频率更新；请到来源健康度查看数据集详情。",
            )
        )
        st.button(
            tr(language, "Open Source Health", "打开来源健康度"),
            key="overview_open_health",
            width="stretch",
            on_click=set_app_page,
            args=("health",),
        )



def render_overview(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
    window: str,
) -> None:
    st.markdown(f'<div class="am-page-title">{tr(language, "Asia Markets Overview", "亚洲市场总览")}</div>', unsafe_allow_html=True)
    st.caption(
        tr(
            language,
            "A bounded Hong Kong market pulse across the connected sectors; detailed analysis stays on sector pages.",
            "香港市场脉搏总览；详细分析保留在各板块页面。",
        )
    )
    st.markdown(
        f'<div class="am-meta">{escape(tr(language, "Hong Kong", "香港"))} · '
        f'{escape(tr(language, "artifact snapshots, not live browser connections", "artifact 数据快照，不是浏览器实时连接"))}</div>',
        unsafe_allow_html=True,
    )
    render_overview_header(artifacts, labels, language)
    render_sector_pulse(artifacts, labels, language)
    render_featured_trends(artifacts, labels, language, window)
    render_overview_health_summary(artifacts, labels, language)
