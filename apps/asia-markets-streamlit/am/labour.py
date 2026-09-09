"""Hong Kong labour market sector page.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from .config import get_pair_heights

from .core import metric_from_card, render_bar_chart, render_header, render_line_chart, render_table, section_heading, series_options, tr

from .explorer import render_source_coverage


def render_labour(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    render_header(artifact, labels, language, "labour")
    section_heading(language, "Summary", "摘要", "Latest headline measures", "最新核心指标")
    income_card = metric_from_card(artifact, labels, "income_card", "median_monthly_earnings", "number")
    cards = [
        metric_from_card(artifact, labels, "labour_force_card", "labour_force_thousands", "number"),
        metric_from_card(artifact, labels, "labour_force_card", "unemployment_rate", "fraction"),
        (
            tr(language, "Median earnings (HK$)", "就业收入中位数（港元）"),
            income_card[1],
            income_card[2],
        ),
        metric_from_card(artifact, labels, "labour_demand_card", "vacancies", "number"),
    ]
    columns = st.columns(len(cards))
    for column, (label, value, help_text) in zip(columns, cards):
        with column:
            st.metric(label, value, help=help_text)

    section_heading(
        language,
        "Core labour pulse",
        "劳动力核心走势",
        "The main series stays visible together; use the local view controls for Level, period change or YoY.",
        "主要序列同时显示；可用每张图的视图控制切换水平、期间变化或同比。",
    )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "labour_force_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=390,
        )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "labour_rates_chart",
            language,
            window,
            views=("Level", "MoM Δpp", "YoY Δpp"),
            periods_per_year=12,
            change_mode="delta",
            height=360,
        )

    section_heading(language, "Labour demand", "劳动力需求", "Latest cross-section plus historical context.", "最新横截面对比及历史背景。")
    card_h, chart_h = get_pair_heights(520, 520, 'bar', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_bar_chart(artifact, labels, "vacancies_by_industry_chart", language, height=chart_h)
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "vacancy_rate_chart",
                language,
                window,
                views=("Level", "QoQ %", "YoY %"),
                periods_per_year=4,
                height=520,
            )
    with st.container(border=True):
        selected = series_options(artifact, "vacancy_industry_history_chart", language, default_count=4)
        render_line_chart(
            artifact,
            labels,
            "vacancy_industry_history_chart",
            language,
            window,
            series_selection=selected,
            views=("Level", "QoQ %", "YoY %"),
            periods_per_year=4,
            height=390,
        )

    section_heading(language, "Earnings & pay", "就业收入与工资", "Median earnings are separate from wage and payroll indices.", "就业收入中位数与工资／薪金指数分开显示。")
    card_h, chart_h = get_pair_heights(480, 480, 'bar', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_bar_chart(artifact, labels, "earnings_by_industry_chart", language, height=chart_h)
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "wage_yoy_chart",
                language,
                window,
                views=("Level",),
                height=480,
            )
    with st.container(border=True):
        selected = series_options(artifact, "earnings_industry_history_chart", language, default_count=4)
        render_line_chart(
            artifact,
            labels,
            "earnings_industry_history_chart",
            language,
            window,
            series_selection=selected,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=390,
        )
    with st.container(border=True):
        selected = series_options(artifact, "occupation_earnings_history_chart", language, default_count=4)
        render_line_chart(
            artifact,
            labels,
            "occupation_earnings_history_chart",
            language,
            window,
            series_selection=selected,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=390,
        )
    with st.container(border=True):
        render_table(artifact, labels, "earnings_by_occupation_table", language)

    section_heading(language, "Talent policy flows", "人才政策流量", "Applications and approvals are policy-flow indicators, not arrivals or employment.", "申请数和批准数是政策流量指标，不等于抵港人数或就业人数。")
    card_h, chart_h = get_pair_heights(350, 350, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(artifact, labels, "talent_policy_received_chart", language, window, views=("Level",), height=chart_h)
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(artifact, labels, "talent_policy_approved_chart", language, window, views=("Level",), height=chart_h)
    with st.container(border=True):
        render_table(artifact, labels, "talent_policy_latest_table", language)

    render_source_coverage({"labour": artifact}, {"labour": labels}, language)
