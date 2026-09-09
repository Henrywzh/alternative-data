"""Transport sector page: airlines, MTR and rail backtests.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from .config import CHINA_AIRLINE_REGION_SERIES_LABELS, CHINA_AIRLINE_REGION_SERIES_LABELS_ZH, CHINA_AIRLINE_SERIES_LABELS, CHINA_AIRLINE_SERIES_LABELS_ZH, CHINA_AIRLINE_TABLE_LABELS_ZH, MTR_SERIES_LABELS, MTR_SERIES_LABELS_ZH

from .core import format_metric, frame_for_dataset, observation_date_label, render_bar_chart, render_header, render_line_chart, render_table, section_heading, series_options, tr

from .explorer import render_source_coverage
from .signals import latest_daily_signal, latest_period_signal


def transport_metric_delta(signal: dict[str, Any], change_mode: str = "pct") -> str | None:
    change = signal.get("change")
    if change is None:
        return None
    if abs(change) < 0.05:
        change = 0.0
    suffix = "pp YoY" if change_mode == "delta" else "% YoY"
    return f"{change:+,.1f}{suffix}"


def render_transport_metric(
    column: Any,
    label: str,
    signal: dict[str, Any],
    fmt: str,
    *,
    language: str = "en",
    change_mode: str = "pct",
    volume_unit: str | None = None,
) -> None:
    value = signal.get("value")
    if fmt == "number" and value is not None and volume_unit == "million":
        display_value = f"{float(value) / 1_000_000:,.2f}m"
    elif fmt == "number" and value is not None and volume_unit == "million_from_thousands":
        display_value = f"{float(value) / 1_000:,.1f}m"
    else:
        display_value = format_metric(value, fmt)
    with column:
        st.metric(
            label,
            display_value,
            delta=transport_metric_delta(signal, change_mode),
        )
        st.caption(observation_date_label(signal.get("date"), language))


def render_airline_h1_backtest(
    artifact: dict[str, Any], labels: dict[str, Any], language: str
) -> None:
    """Render source-recovery coverage and the H1 KPI calibration evidence."""
    if not frame_for_dataset(artifact, "airline_h1_backtest_summary").empty:
        section_heading(
            language,
            "H1 2026 earnings calibration",
            "2026 年上半年财报校准",
            "Historical KPI calibration and source-recovery sensitivity for the pre-report earnings view. This is calibration evidence, not a strict point-in-time trading backtest.",
            "用于财报前盈利判断的历史 KPI 校准及数据恢复敏感性；这是校准证据，不是严格的点时交易回测。",
        )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_bar_chart(artifact, labels, "airline_h1_revenue_mae_chart", language, height=390)
        with right:
            with st.container(border=True):
                render_bar_chart(artifact, labels, "airline_h1_cost_mae_chart", language, height=390)
        with st.container(border=True):
            render_table(artifact, labels, "airline_h1_backtest_summary_table", language)

    if not frame_for_dataset(artifact, "airline_period_backtest_summary").empty:
        section_heading(
            language,
            "H1 / H2 / FY calibration and Spring error diagnosis",
            "H1 / H2 / FY 校准与春秋误差诊断",
            "The period view separates first half, derived second half and full-year calibration. The table keeps logical-assumption coverage visible instead of treating it as observed data.",
            "期间视图分开上半年、由 FY 减 H1 推导的下半年及全年校准；表格保留逻辑假设覆盖，不把它当作观测数据。",
        )
        with st.container(border=True):
            render_bar_chart(artifact, labels, "airline_period_revenue_mae_chart", language, height=430)
        with st.container(border=True):
            render_table(artifact, labels, "airline_period_backtest_summary_table", language)

    if not frame_for_dataset(artifact, "airline_source_recovery_summary").empty:
        section_heading(
            language,
            "Recovered-source audit",
            "恢复数据源审计",
            "Monthly airline charts prefer verified official-PDF recoveries. Rows confirmed as absent from the source PDF remain missing; research interpolation is not silently displayed as observed data.",
            "月度航司图表优先使用已核验的官方 PDF 恢复值；确认源 PDF 未披露的行仍保持缺失，研究插值不会被静默当作观测值显示。",
        )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_bar_chart(artifact, labels, "airline_source_recovery_chart", language, height=360)
        with right:
            with st.container(border=True):
                render_table(artifact, labels, "airline_source_recovery_audit_table", language, max_rows=100)

    if not frame_for_dataset(artifact, "airline_h1_revenue_nowcast_comparison").empty:
        section_heading(
            language,
            "Current H1 2026 nowcast",
            "当前 2026 年上半年预测",
            "Spring and Juneyao flat-ASK baselines versus the analyst overlay, shown in USD million. Formal interim actuals remain the eventual event test.",
            "春秋与吉祥的 flat-ASK 基准与分析师调整项，单位为百万美元；正式中报实际值将是最终检验。",
        )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_bar_chart(artifact, labels, "airline_h1_revenue_nowcast_chart", language, height=370)
        with right:
            with st.container(border=True):
                render_bar_chart(artifact, labels, "airline_h1_profit_nowcast_chart", language, height=370)


def render_transport_tabs(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    """Render transport as separate Hong Kong aviation, China aviation and MTR tabs."""
    render_header(
        artifact,
        labels,
        language,
        "transport",
        title_override=tr(language, "Hong Kong Transport & Aviation", "香港交通与航空"),
        description_override=tr(
            language,
            "Company-level airline passenger, cargo, fleet and network-event signals plus MTR passenger demand. Other transport datasets remain outside this V1 page.",
            "航空公司客运、货运、机队与航线事件信号，以及港铁客运需求。其他交通数据暂不纳入此 V1 页面。",
        ),
    )

    cathay = frame_for_dataset(artifact, "cathay_history")
    cathay_fleet = frame_for_dataset(artifact, "cathay_fleet_total_history")
    mtr = frame_for_dataset(artifact, "mtr_history")
    airline_passengers = frame_for_dataset(artifact, "china_airline_passengers_history")
    airline_load_factor = frame_for_dataset(artifact, "china_airline_load_factor_history")

    hk_airline_tab, china_airline_tab, mtr_tab = st.tabs(
        [
            tr(language, "Hong Kong airline · Cathay", "香港航空 · 国泰"),
            tr(language, "China listed airlines", "中国上市航司"),
            tr(language, "MTR", "港铁"),
        ]
    )

    with hk_airline_tab:
        section_heading(
            language,
            "Hong Kong airline",
            "香港航空",
            "Cathay Group operating signals and Hong Kong International Airport demand context.",
            "国泰集团运营信号，以及香港国际机场需求背景。",
        )
        cathay_cards = [
            (
                tr(language, "Cathay passengers (m)", "国泰航空客运量（百万）"),
                latest_period_signal(cathay, "date", "cathay_passengers"),
                "number",
                "pct",
                "million",
            ),
            (
                tr(language, "Cathay load factor", "国泰航空客座率"),
                latest_period_signal(cathay, "date", "cathay_passenger_load_factor_pct", aggregation="mean", change_mode="delta"),
                "percent",
                "delta",
                None,
            ),
            (
                tr(language, "HKIA passengers (m)", "香港机场客运量（百万）"),
                latest_period_signal(cathay, "date", "hkia_passengers"),
                "number",
                "pct",
                "million",
            ),
            (
                tr(language, "HKIA movements", "香港机场飞机升降量"),
                latest_period_signal(cathay, "date", "hkia_aircraft_movements"),
                "number",
                "pct",
                None,
            ),
        ]
        columns = st.columns(len(cathay_cards))
        for column, (label, signal, fmt, change_mode, volume_unit) in zip(columns, cathay_cards):
            render_transport_metric(
                column,
                label,
                signal,
                fmt,
                language=language,
                change_mode=change_mode,
                volume_unit=volume_unit,
            )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "cathay_passengers_chart", language, window,
                views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
            )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "cathay_load_factor_chart", language, window,
                    views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
                )
        with right:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "cathay_capacity_demand_chart", language, window,
                    views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
                )
        section_heading(
            language,
            "Cathay cargo, flight operations and fleet",
            "国泰货运、航班运营与机队",
            "Cargo tonnage, freight load factor, reported flight sectors and official report-period fleet totals. Fleet is semiannual/annual and is not interpolated to monthly frequency.",
            "货运量、货运载运率、公告航班架次／航段，以及官方报告期末机队总数。机队为半年／年度频率，不插值成月度数据。",
        )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "cathay_cargo_tonnage_chart", language, window,
                    views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
                )
        with right:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "cathay_freight_load_factor_chart", language, window,
                    views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
                )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "cathay_cargo_capacity_demand_chart", language, window,
                    views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
                )
        with right:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "cathay_flight_sectors_chart", language, window,
                    views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
                )
        if not cathay_fleet.empty:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "cathay_fleet_total_chart", language, window,
                    views=("Level",), periods_per_year=2, height=390,
                    series_label_map=(
                        {
                            "Company": "国泰航空公司",
                            "HK Express": "香港快运",
                            "Air Hong Kong": "国泰航空货运（Air Hong Kong）",
                            "Grand total": "集团合计",
                        }
                        if language == "zh"
                        else None
                    ),
                )
        st.caption(
            tr(
                language,
                "Cathay cargo metrics are Cathay Group disclosures. HKIA freight tonnage shown in the airport context series is airport-wide and should not be read as Cathay cargo.",
                "国泰货运指标来自国泰集团公告；机场背景图中的香港国际机场货运量是全机场合计，不应解读为国泰货运量。",
            )
        )

    with china_airline_tab:
        section_heading(
            language,
            "China listed airlines",
            "中国上市航空公司",
            "All six available listed groups are selected by default; deselect only when comparing a smaller peer set.",
            "默认显示六家上市航司集团；只有需要缩小同业组时才取消选择。",
        )
        china_series_labels = CHINA_AIRLINE_SERIES_LABELS_ZH if language == "zh" else CHINA_AIRLINE_SERIES_LABELS
        selected_airlines = series_options(
            artifact,
            "china_airline_passengers_chart",
            language,
            series_label_map=china_series_labels,
        )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "china_airline_passengers_chart", language, window,
                series_selection=selected_airlines, views=("Level", "MoM %", "YoY %"),
                periods_per_year=12, height=400, series_label_map=china_series_labels,
            )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "china_airline_ask_chart", language, window,
                    series_selection=selected_airlines, views=("Level", "MoM %", "YoY %"),
                    periods_per_year=12, height=390, series_label_map=china_series_labels,
                )
        with right:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "china_airline_rpk_chart", language, window,
                    series_selection=selected_airlines, views=("Level", "MoM %", "YoY %"),
                    periods_per_year=12, height=390, series_label_map=china_series_labels,
                )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "china_airline_load_factor_chart", language, window,
                series_selection=selected_airlines, views=("Level", "MoM %", "YoY %"),
                periods_per_year=12, height=390, series_label_map=china_series_labels,
            )

        regional_options = selected_airlines or list(CHINA_AIRLINE_SERIES_LABELS)
        regional_display_options = [china_series_labels.get(value, value) for value in regional_options]
        regional_display = st.selectbox(
            tr(language, "Carrier for regional drill-down", "地区客运量查看航司"),
            regional_display_options,
            key="china_airline_regional_carrier",
        )
        regional_airline = dict(zip(regional_display_options, regional_options))[regional_display]
        regional_series = [f"{regional_airline} · {region}" for region in ("Domestic", "International", "Regional")]
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "china_airline_region_by_carrier_chart", language, window,
                series_selection=regional_series, views=("Level", "MoM %", "YoY %"),
                periods_per_year=12, height=410,
                series_label_map=(
                    CHINA_AIRLINE_REGION_SERIES_LABELS_ZH
                    if language == "zh" else CHINA_AIRLINE_REGION_SERIES_LABELS
                ),
            )
            st.caption(
                tr(
                    language,
                    "Regional blanks in the issuer PDF remain missing; an explicit dash is shown as zero. This preserves the difference between undisclosed data and no reported regional traffic.",
                    "公司公告 PDF 中留空的地区数据会保持缺失；明确标示的横线会显示为 0，从而区分未披露数据与没有报告地区客运量。",
                )
            )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "china_airline_region_split_chart", language, window,
                views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=390,
            )
        with st.container(border=True):
            render_table(artifact, labels, "china_airline_latest_snapshot_table", language)

        section_heading(
            language,
            "Cargo operating signals",
            "货运运营信号",
            "Monthly cargo/mail demand and utilization, with issuer units normalized in the shared artifact.",
            "月度货邮需求与运力使用率；来源单位已在共享 artifact 中统一换算。",
        )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "china_airline_cargo_chart", language, window,
                series_selection=selected_airlines, views=("Level", "MoM %", "YoY %"),
                periods_per_year=12, height=400, series_label_map=china_series_labels,
            )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "china_airline_freight_load_factor_chart", language, window,
                series_selection=selected_airlines, views=("Level", "MoM %", "YoY %"),
                periods_per_year=12, height=400, series_label_map=china_series_labels,
            )
            st.caption(
                tr(
                    language,
                    "Spring Airlines has a small number of official freight-load-factor observations above 100%; those source anomalies are retained and not clipped.",
                    "春秋航空少数官方货邮载运率观测超过 100%；这些源数据异常会保留，不会人为截断。",
                )
            )
        with st.container(border=True):
            render_table(
                artifact, labels, "china_airline_cargo_latest_snapshot_table", language,
                value_maps=CHINA_AIRLINE_TABLE_LABELS_ZH if language == "zh" else None,
            )

        section_heading(
            language,
            "Fleet and network events",
            "机队与网络事件",
            "Fleet totals are monthly capacity context; net changes and route counts are disclosed event signals, not interpolated series.",
            "机队总数提供月度运力背景；净变化和航线数量是公告披露的事件信号，不做插值。",
        )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "china_airline_fleet_total_chart", language, window,
                series_selection=selected_airlines, views=("Level", "MoM %", "YoY %"),
                periods_per_year=12, height=420, series_label_map=china_series_labels,
            )
        left, right = st.columns(2)
        with left:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "china_airline_fleet_net_change_chart", language, window,
                    series_selection=selected_airlines, views=("Level", "MoM %"),
                    periods_per_year=12, height=390, series_label_map=china_series_labels,
                )
        with right:
            with st.container(border=True):
                render_line_chart(
                    artifact, labels, "china_airline_new_route_chart", language, window,
                    series_selection=selected_airlines, views=("Level", "MoM %"),
                    periods_per_year=12, height=390, series_label_map=china_series_labels,
                )
        with st.container(border=True):
            render_table(
                artifact, labels, "china_airline_operating_events_latest_table", language,
                value_maps=CHINA_AIRLINE_TABLE_LABELS_ZH if language == "zh" else None,
            )

        render_airline_h1_backtest(artifact, labels, language)

    with mtr_tab:
        section_heading(
            language,
            "MTR",
            "港铁",
            "Long-run patronage plus service-level demand context.",
            "长期客运量历史及服务类型需求背景。",
        )
        mtr_cards = [
            (
                tr(language, "Total patronage (m)", "总客运量（百万）"),
                latest_period_signal(mtr, "date", "total_mtr_patronage_thousands"),
                "number", "pct", "million_from_thousands",
            ),
            (
                tr(language, "Domestic service (m)", "本地服务（百万）"),
                latest_period_signal(mtr, "date", "domestic_service_thousands"),
                "number", "pct", "million_from_thousands",
            ),
            (
                tr(language, "Cross-boundary (m)", "跨境服务（百万）"),
                latest_period_signal(mtr, "date", "cross_boundary_thousands"),
                "number", "pct", "million_from_thousands",
            ),
            (
                tr(language, "HSR (m)", "高铁（百万）"),
                latest_period_signal(mtr, "date", "hsr_thousands"),
                "number", "pct", "million_from_thousands",
            ),
        ]
        columns = st.columns(len(mtr_cards))
        for column, (label, signal, fmt, change_mode, volume_unit) in zip(columns, mtr_cards):
            render_transport_metric(
                column, label, signal, fmt, language=language,
                change_mode=change_mode, volume_unit=volume_unit,
            )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "mtr_total_patronage_chart", language, window,
                views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=420,
            )
        with st.container(border=True):
            render_line_chart(
                artifact, labels, "mtr_service_breakdown_chart", language, window,
                views=("Level", "MoM %", "YoY %"), periods_per_year=12, height=420,
                series_label_map=MTR_SERIES_LABELS_ZH if language == "zh" else MTR_SERIES_LABELS,
            )

    render_source_coverage({"transport": artifact}, {"transport": labels}, language)
