"""Hong Kong population and migration sector page.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from .config import get_pair_heights

from .core import frequency_control, metric_from_card, render_bar_chart, render_header, render_line_chart, section_heading, tr

from .explorer import render_source_coverage


def render_population(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    render_header(artifact, labels, language, "population")
    section_heading(language, "Summary", "摘要", "Population, movement, departure claims and student pipeline.", "人口、迁移、离港申索和学生流量。")
    population_card = metric_from_card(artifact, labels, "kpi_total_pop", "latest_pop", "number")
    movement_card = metric_from_card(artifact, labels, "kpi_net_mov", "latest_net_mov", "number")
    mpf_card = metric_from_card(artifact, labels, "kpi_mpfa_claims", "latest_mpfa", "number")
    student_card = metric_from_card(artifact, labels, "kpi_ugc_students", "latest_ugc", "number")
    cards = [
        (tr(language, "Population ('000)", "人口（千人）"), population_card[1], population_card[2]),
        (tr(language, "Net movement ('000)", "净人口移动（千人）"), movement_card[1], movement_card[2]),
        (tr(language, "MPF claims (HK$m)", "强积金申索（百万港元）"), mpf_card[1], mpf_card[2]),
        (tr(language, "Mainland students", "在港内地生"), student_card[1], student_card[2]),
    ]
    columns = st.columns(len(cards))
    for column, (label, value, help_text) in zip(columns, cards):
        with column:
            st.metric(label, value, help=help_text)

    section_heading(
        language,
        "High-frequency movement",
        "高频人口流动",
        "Daily ImmD data is shown at source grain; a one-year source history is not silently presented as a long-run trend.",
        "入境处日度数据保留来源粒度；只有约一年历史时不会伪装成长周期趋势。",
    )
    with st.container(border=True):
        frequency = frequency_control(language)
        render_line_chart(
            artifact,
            labels,
            "immd_net_flow_chart",
            language,
            window,
            views=("Level", "Day %", "YoY %"),
            periods_per_year=30,
            height=400,
            resample_frequency=frequency,
        )

    section_heading(language, "Population and migration signals", "人口与迁移信号", "Long-run official population series plus permanent-departure claims.", "长期官方人口序列及永久离港强积金申索。")
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "csd_population_chart",
            language,
            window,
            views=("Level", "Half-year Δ", "YoY Δ"),
            periods_per_year=2,
            change_mode="delta",
            height=400,
        )
    card_h, chart_h = get_pair_heights(None, None, 'bar', 'bar')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_bar_chart(artifact, labels, "mpfa_claims_chart", language, height=chart_h)
    with right:
        with st.container(height=card_h, border=True):
            render_bar_chart(artifact, labels, "mpfa_claims_count_chart", language, height=chart_h)

    section_heading(language, "Student and cross-border flows", "学生与跨境流量", "Education and transport indicators provide complementary migration signals.", "教育及交通指标提供互补的迁移信号。")
    card_h, chart_h = get_pair_heights(None, 400, 'bar', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_bar_chart(artifact, labels, "ugc_students_chart", language, height=chart_h)
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "td_cross_border_chart",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=400,
            )

    render_source_coverage({"population": artifact}, {"population": labels}, language)
