"""Terminal overview page and sector pulse cards.

Market-first entrypoint with compact economic and thematic research access.
"""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from .config import OVERVIEW_FEATURED_CHARTS, OVERVIEW_PULSE_CONFIG, PAIR_CARD_HEIGHT, PALETTE, SECTORS, sector_region

from .core import find_manifest_item, latest_metric_reading, latest_series_reading, observation_date_label, parse_period, render_line_chart, section_heading, source_health_frame, sparkline_context, sparkline_svg, tr
from .overview_policy import economic_observation_rows


def set_app_page(page_key: str) -> None:
    # Use native navigation so the destination survives language/widget reruns
    # and can be bookmarked. The old one-shot session router reset on rerun.
    from .page_registry import build_streamlit_pages

    st.switch_page(build_streamlit_pages()[page_key])


def overview_page_button(label: str, key: str, page_key: str) -> None:
    # switch_page raises a rerun, which Streamlit suppresses inside callbacks.
    # Call it in the main render path, as the sidebar already does.
    if st.button(label, key=key, width="stretch"):
        set_app_page(page_key)


def overview_source_summary(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
) -> dict[str, int]:
    total = healthy = attention = problem = missing_metadata = 0
    for sector_key, artifact in artifacts.items():
        health = source_health_frame(artifact)
        if health.empty or "status" not in health.columns:
            missing_metadata += 1
            status_values = ["Unknown"] * len(artifact.get("sources", []))
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
    return {"total": total, "healthy": healthy, "attention": attention, "problem": problem, "missing_metadata": missing_metadata}


def sector_source_status(artifact: dict[str, Any], label_artifact: dict[str, Any], language: str) -> str:
    health = source_health_frame(artifact)
    if health.empty or "status" not in health.columns:
        return tr(language, "Health unknown", "健康状态未知")
    else:
        statuses = health.get("status", pd.Series(dtype="object")).astype(str).str.casefold().tolist()
    if not statuses:
        return tr(language, "Health unknown", "健康状态未知")
    if all(value in {"healthy", "ready", "live", "success"} for value in statuses):
        return tr(language, "Ready", "可用")
    if any(value not in {"healthy", "ready", "live", "success", "partial", "warning", "degraded", "stale"} for value in statuses):
        return tr(language, "Problem", "有问题")
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
    latest = latest_artifact_date(artifacts, language)
    st.caption(tr(
        language,
        f"Latest observation across sections: {latest}. Each metric retains its own date; this is not a common cutoff or publication date.",
        f"各板块最新观察日：{latest}。各指标日期独立；此日期不是所有数据的共同截止日或发布日期。",
    ))


def render_sector_pulse(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
) -> None:
    section_heading(
        language,
        "Markets & allocation",
        "市场与配置",
        "Core readings from the existing monitors; open a page for changes, signals and source detail.",
        "复用现有监控的核心读数；变化、信号及来源详情保留在各页面。",
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
                if not find_manifest_item(artifact, "charts", metric.get("chart_id", "immd_net_flow_chart")):
                    continue
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
        if sparkline and find_manifest_item(artifact, "charts", sparkline["chart_id"]):
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
                st.markdown(
                    f'<div class="am-pulse-title">{escape(name)}</div>'
                    f'<div class="am-pulse-meta">{escape(sector_region(sector_key, language))} · '
                    f'{escape(status)} · {escape(tr(language, "artifact through", "数据截至"))} {escape(as_of)}</div>',
                    unsafe_allow_html=True,
                )
                if sector_key == "regime":
                    from .regime import regime_data_warnings

                    warnings = regime_data_warnings(artifact, language)
                    if warnings:
                        st.warning(tr(
                            language,
                            "Incomplete or stale inputs: readings below are audit context, not a complete current assessment.",
                            "数据不完整或部分输入过期：下方读数仅供核查，并非完整的当前判断。",
                        ))
                        with st.expander(tr(language, "Data warning details", "数据警告详情")):
                            for warning in warnings:
                                st.caption(warning)
                if metric_blocks:
                    st.markdown(
                        f'<div class="am-pulse-metrics">{"".join(metric_blocks)}</div>',
                        unsafe_allow_html=True,
                    )
                if sparkline_markup:
                    st.markdown(f"{sparkline_context_markup}{sparkline_markup}", unsafe_allow_html=True)
                overview_page_button(
                    tr(language, f"Open {sector.get('short_en', name)}", f"打开{sector.get('short_zh', name)}"),
                    key=f"overview_open_{sector_key}",
                    page_key=sector_key,
                )


def render_economic_observations(artifacts: dict[str, dict[str, Any]], language: str) -> None:
    section_heading(
        language, "Economic data & releases", "经济数据与发布",
        "Recent known releases lead; observation periods are not publication dates. Full histories remain on their pages.",
        "已知近期发布优先；观察期不等于发布日期。完整历史保留在对应页面。",
    )
    for row in economic_observation_rows(artifacts, language):
        key = row["sector"]
        sector = SECTORS[key]
        release = (
            observation_date_label(row["release"], language)
            if not pd.isna(row["release"])
            else tr(language, "Publication date unavailable", "未提供发布日期")
        )
        badge = tr(language, "Released within 30 days", "近30天发布") if row["recent_release"] else ""
        name = sector["short_zh" if language == "zh" else "short_en"]
        st.markdown(
            '<div class="am-economic-row">'
            f'<div class="am-economic-name">{escape(name)}<div class="am-economic-meta">{escape(sector_region(key, language))}</div></div>'
            f'<div>{escape(row["label"])}<div class="am-economic-value">{escape(row["value"])}</div></div>'
            f'<div class="am-economic-meta">{escape(tr(language, "Observed", "观察期"))}<br>{escape(row["observation"])}</div>'
            f'<div class="am-economic-meta">{escape(release)}<div class="am-economic-release">{escape(badge)}</div></div>'
            '</div>', unsafe_allow_html=True,
        )
    columns = st.columns(4)
    for column, key in zip(columns, ("real_estate", "transport", "labour", "population")):
        with column:
            sector = SECTORS[key]
            overview_page_button(
                tr(language, sector["short_en"], sector["short_zh"]),
                key=f"overview_economy_{key}", page_key=key,
            )


def render_research_shortcuts(language: str) -> None:
    columns = st.columns(3)
    for column, (key, en, zh) in zip(columns, (
        ("hong_kong_flows", "Hong Kong flows", "香港资金流"),
        ("events", "Events & consensus", "事件与预期"),
        ("heatmaps", "Heat maps", "热力图"),
    )):
        with column:
            overview_page_button(tr(language, en, zh), key=f"overview_shortcut_{key}", page_key=key)


def render_thematic_shortcuts(language: str) -> None:
    with st.expander(tr(language, "Thematic research", "专题研究"), expanded=False):
        for key in ("aerospace", "crypto"):
            sector = SECTORS[key]
            st.caption(sector_region(key, language))
            overview_page_button(tr(language, sector["short_en"], sector["short_zh"]), key=f"overview_theme_{key}", page_key=key)


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
                overview_page_button(
                    tr(language, f"Open {sector['short_en']}", f"打开{sector['short_zh']}"),
                    key=f"overview_featured_open_{sector_key}",
                    page_key=sector_key,
                )


def render_overview_health_summary(
    artifacts: dict[str, dict[str, Any]],
    labels: dict[str, dict[str, Any]],
    language: str,
) -> None:
    summary = overview_source_summary(artifacts, labels)
    text_column, link_column = st.columns([3, 1])
    with text_column:
        st.caption(tr(
            language,
            f"Reported source checks: {summary['healthy']}/{summary['total']} ready · {summary['attention']} need attention · {summary['problem']} unavailable or unknown. Not a guarantee that all observations are current.",
            f"来源检查：{summary['healthy']}/{summary['total']} 可用 · {summary['attention']} 需留意 · {summary['problem']} 不可用或未知。不代表所有观察值均为最新。",
        ))
        if summary["missing_metadata"]:
            st.warning(tr(
                language,
                f"{summary['missing_metadata']} sections lack source-health metadata; their status is unknown.",
                f"{summary['missing_metadata']} 个板块缺少来源健康元数据，状态未知。",
            ))
    with link_column:
        overview_page_button(
            tr(language, "Open Source Health", "打开来源健康度"),
            key="overview_open_health",
            page_key="health",
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
            "Markets and allocation first, economic releases next; detailed research stays on its own pages.",
            "先看市场与配置，再看经济数据发布；详细研究保留在各页面。",
        )
    )
    st.markdown(
        f'<div class="am-meta">{escape(tr(language, "Cross-market", "跨市场"))} · '
        f'{escape(tr(language, "local data snapshots, not live quotes", "本地数据快照，非实时报价"))}</div>',
        unsafe_allow_html=True,
    )
    render_overview_header(artifacts, labels, language)
    render_overview_health_summary(artifacts, labels, language)
    market_artifacts = {key: artifacts[key] for key in ("regime", "market") if key in artifacts}
    if market_artifacts:
        render_sector_pulse(market_artifacts, labels, language)
    else:
        st.warning(tr(language, "Market snapshots are unavailable.", "市场数据快照不可用。"))
    render_research_shortcuts(language)
    render_economic_observations(artifacts, language)
    render_thematic_shortcuts(language)
    render_featured_trends(artifacts, labels, language, window)
