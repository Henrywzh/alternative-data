"""Hong Kong real estate sector page.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from .config import PALETTE, get_pair_heights

from .core import apply_line_hover, chart_theme, frame_for_dataset, history_window, line_view_frame, localize_coverage, metric_from_card, monthly_quarterly_control, render_header, render_line_chart, render_table, section_heading, series_options, tr, view_label

from .explorer import render_source_coverage


def render_ccl_mhpi_combined_chart(
    artifact: dict[str, Any],
    language: str,
    history_window_name: str,
    *,
    height: int = 380,
) -> None:
    """Overlay CCL and MHPI on one plot — both are weekly residential price indices on a comparable scale."""
    ccl = frame_for_dataset(artifact, "ccl_history").assign(series=tr(language, "Centaline CCL", "中原城市领先指数（CCL）"))
    mhpi = frame_for_dataset(artifact, "mhpi_history").assign(series=tr(language, "Midland MHPI", "美联物业价格指数（MHPI）"))
    combined = pd.concat([ccl, mhpi], ignore_index=True)
    combined, coverage = history_window(combined, "date", history_window_name)

    title = tr(language, "Centaline CCL & Midland MHPI", "中原城市领先指数（CCL）与美联物业价格指数（MHPI）")
    st.markdown(f'<div class="am-chart-title">{title}</div>', unsafe_allow_html=True)
    subtitle = tr(
        language,
        "Two independently published weekly residential price indices, plotted together for comparison.",
        "两个独立发布的住宅价格周度指数，一并显示以便比较。",
    )
    st.caption(" · ".join([subtitle, localize_coverage(coverage, language)]))
    if combined.empty:
        st.info(tr(language, "No rows are available for this selection.", "这个选择没有可用数据。"))
        return

    view = st.radio(
        tr(language, "View", "视图"),
        ("Level", "WoW %", "YoY %"),
        horizontal=True,
        key="view_ccl_mhpi_combined",
        format_func=lambda item: view_label(language, item),
    )
    transformed, value_label, transformed_format = line_view_frame(combined, "value", "series", view, 52, "pct", "number")
    if transformed.empty:
        st.info(tr(language, "Not enough observations for this comparison window.", "这个比较视图没有足够的观察值。"))
        return
    fig = px.line(transformed, x="_date", y="_value", color="series", markers=False, color_discrete_sequence=PALETTE)
    fig.update_yaxes(title=value_label)
    fig.update_xaxes(title=None, tickformat="%b %Y")
    if transformed["_date"].max() - transformed["_date"].min() > pd.Timedelta(days=365 * 7):
        fig.update_xaxes(dtick="M12")
    elif transformed["_date"].max() - transformed["_date"].min() > pd.Timedelta(days=365 * 3):
        fig.update_xaxes(dtick="M6")
    apply_line_hover(fig, transformed, transformed_format)
    fig = chart_theme(fig, transformed_format, date_axis=True, height=height)
    st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})


def render_real_estate_residential(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    cards = [
        metric_from_card(artifact, labels, "ccl_card", "latest", "number"),
        metric_from_card(artifact, labels, "mhpi_card", "latest", "number"),
        metric_from_card(artifact, labels, "rvd_price_card", "latest", "number"),
        metric_from_card(artifact, labels, "rvd_rent_card", "latest", "number"),
    ]
    columns = st.columns(len(cards))
    for column, (label, value, help_text) in zip(columns, cards):
        with column:
            st.metric(label, value, help=help_text)

    section_heading(
        language,
        "Price & rental core",
        "价格与租金核心走势",
        "CCL and MHPI are publisher-level weekly indices; RVD is the official monthly benchmark.",
        "CCL 与 MHPI 为发布者周度指数；RVD 为官方月度基准指数。",
    )
    with st.container(border=True):
        render_ccl_mhpi_combined_chart(artifact, language, window, height=420)

    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "rvd_trend",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "rvd_rent_trend",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=chart_h,
            )

    section_heading(
        language,
        "Mortgage & credit",
        "按揭与信贷",
        "HKMA residential mortgage survey: rate mix, LTV, credit quality, applications and loan amounts.",
        "金管局住宅按揭调查：利率组合、按揭成数、信贷质素、申请宗数及贷款金额。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "hkma_mortgage_rate_mix_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "hkma_ltv_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )

    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "hkma_credit_quality_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "hkma_applications_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )

    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "hkma_loan_amount_chart",
            language,
            window,
            views=("Level",),
            periods_per_year=12,
            height=390,
        )

    with st.container(border=True):
        render_table(artifact, labels, "hkma_mortgage_activity_table", language, max_rows=24)

    section_heading(
        language,
        "Transactions & new supply",
        "成交与新盘供应",
        "Land Registry ASP counts, agency transaction pulse, new project launches and 28Hse EPI/ERI.",
        "土地注册处买卖合约宗数、代理行成交脉搏、新盘推售及 28Hse 楼价/租金指数。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "landreg_asp_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "epi_eri_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )

    card_h, chart_h = get_pair_heights(400, 400, 'bar', 'bar')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_table(artifact, labels, "agency_transactions_pulse_table", language, max_rows=25)
    with right:
        with st.container(height=card_h, border=True):
            render_table(artifact, labels, "hse28_new_projects_table", language, max_rows=25)

    section_heading(
        language,
        "Government supply pipeline (Buildings Department)",
        "政府房屋供应管道（屋宇署）",
        "Demolition-to-occupation project lifecycle, from the official monthly digest archive.",
        "由拆卸至入伙的项目生命周期，来自屋宇署月报档案。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            selected_units = series_options(artifact, "bd_supply_history_units_chart", language, default_count=4)
            units_frequency = monthly_quarterly_control(language, "bd_supply_units_freq")
            render_line_chart(
                artifact,
                labels,
                "bd_supply_history_units_chart",
                language,
                window,
                series_selection=selected_units,
                views=("Level", "YoY %"),
                periods_per_year=12 if units_frequency == "Monthly" else 4,
                resample_frequency=units_frequency,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            selected_counts = series_options(artifact, "bd_supply_history_counts_chart", language, default_count=4)
            counts_frequency = monthly_quarterly_control(language, "bd_supply_counts_freq")
            render_line_chart(
                artifact,
                labels,
                "bd_supply_history_counts_chart",
                language,
                window,
                series_selection=selected_counts,
                views=("Level", "YoY %"),
                periods_per_year=12 if counts_frequency == "Monthly" else 4,
                resample_frequency=counts_frequency,
                height=chart_h,
            )

    with st.container(border=True):
        render_table(artifact, labels, "bd_supply_detail_table", language, max_rows=30)


def render_real_estate_cross_source(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    section_heading(
        language,
        "Rebased comparisons",
        "重新基准化比较",
        "Each series rebased to 100 at its first available month in the window; price and rent are kept on separate scales.",
        "各序列在窗口内首个可用月份重新基准化为 100；价格与租金分开显示，避免混合比较。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "residential_price_rebased_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "residential_rent_rebased_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=12,
                height=chart_h,
            )

    section_heading(
        language,
        "Centaline price & rental indices",
        "中原价格与租金指数",
        "CCI and CRI are separate Centaline index products from the CCL headline series; rental yield is a companion series, not a rent level.",
        "CCI 与 CRI 为中原独立指数产品，有别于 CCL headline 序列；租金回报率为配套序列，并非租金水平。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "cci_trend",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "cri_trend",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=chart_h,
            )

    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "cri_yield_trend",
            language,
            window,
            views=("Level",),
            periods_per_year=12,
            height=360,
        )

    section_heading(
        language,
        "Market sentiment",
        "市场情绪",
        "Two independent sentiment reads: Centaline CSI (weekly) and Midland's own confidence index.",
        "两个独立的情绪指标：中原 CSI（周度）及美联物业信心指数。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "csi_trend",
                language,
                window,
                views=("Level",),
                periods_per_year=52,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "confidence_trend",
                language,
                window,
                views=("Level",),
                periods_per_year=52,
                height=chart_h,
            )


def render_real_estate_commercial(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    section_heading(
        language,
        "Office & retail rents",
        "写字楼与零售租金",
        "Official RVD rental/price indices for commercial property, separate from the residential series.",
        "官方 RVD 商业地产租金／价格指数，与住宅序列分开显示。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "rvd_office_trend",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "rvd_retail_trend",
                language,
                window,
                views=("Level", "MoM %", "YoY %"),
                periods_per_year=12,
                height=chart_h,
            )

    section_heading(
        language,
        "Supply-side macro signals",
        "供应端宏观信号",
        "Economy-wide construction activity and government land disposed by method — leading indicators for future commercial and residential supply.",
        "全经济建筑活动及政府卖地（按方式划分）——未来商业及住宅供应的领先指标。",
    )
    card_h, chart_h = get_pair_heights(None, None, 'line', 'line')
    left, right = st.columns(2)
    with left:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "cnsd_construction_value_chart",
                language,
                window,
                views=("Level", "QoQ %", "YoY %"),
                periods_per_year=4,
                height=chart_h,
            )
    with right:
        with st.container(height=card_h, border=True):
            render_line_chart(
                artifact,
                labels,
                "censtatd_land_disposals_chart",
                language,
                window,
                views=("Level",),
                periods_per_year=4,
                height=chart_h,
            )


def render_real_estate_tabs(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    """Render Hong Kong real estate as residential, cross-source/sentiment and commercial/land-supply tabs.

    Company-level bottom-up analysis (e.g. individual developer deep dives) is
    tracked separately and intentionally has no tab here yet.
    """
    render_header(
        artifact,
        labels,
        language,
        "real_estate",
        title_override=tr(language, "Hong Kong Real Estate", "香港地产"),
        description_override=tr(
            language,
            "Sector-level residential, cross-source/sentiment and commercial/land-supply signals. Company-level bottom-up analysis is tracked separately and is not part of this page.",
            "板块级住宅、跨来源／情绪指标及商业地产／土地供应信号。个股自下而上分析另行追踪，不在此页面内。",
        ),
    )
    residential_tab, cross_source_tab, commercial_tab = st.tabs([
        tr(language, "Residential Market", "住宅市场"),
        tr(language, "Cross-Source & Sentiment", "跨来源与市场情绪"),
        tr(language, "Commercial & Land Supply", "商业地产与土地供应"),
    ])
    with residential_tab:
        render_real_estate_residential(artifact, labels, language, window)
    with cross_source_tab:
        render_real_estate_cross_source(artifact, labels, language, window)
    with commercial_tab:
        render_real_estate_commercial(artifact, labels, language, window)
    render_source_coverage({"real_estate": artifact}, {"real_estate": labels}, language)
