"""Stablecoin and crypto sector page.

Split out of the former monolithic app.py; behaviour is unchanged.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from .config import CRYPTO_ATTENTION_AGENT_LABELS, CRYPTO_ATTENTION_AGENT_LABELS_ZH, CRYPTO_PAGE_LABELS, CRYPTO_PAGE_LABELS_ZH, PALETTE

from .core import chart_theme, format_metric, frame_for_dataset, latest_row, observation_date_label, render_fear_greed_daily_chart, render_header, render_line_chart, render_table, section_heading, tr

from .signals import latest_daily_signal, latest_period_signal

from .explorer import render_source_coverage


def crypto_metric_delta(signal: dict[str, Any]) -> str | None:
    change = signal.get("change")
    if change is None:
        return None
    if abs(change) < 0.05:
        change = 0.0
    return f"{change:+,.1f}% YoY"


def render_crypto_policy_pulse(
    artifact: dict[str, Any],
    labels: dict[str, Any],
    language: str,
) -> None:
    """Render official Hong Kong crypto policy facts separately from forecasts."""
    section_heading(
        language,
        "Hong Kong regulatory & policy pulse",
        "香港监管与政策脉搏",
        "Official HKMA and SFC registers provide the status layer; the news pulse shows regulatory activity, not market sentiment.",
        "金管局和证监会官方登记册提供状态层；新闻脉搏反映监管活动度，不代表市场情绪。",
    )

    kpi = latest_row(frame_for_dataset(artifact, "market_kpi_summary"))
    status_metrics = (
        ("hkma_count", "hkma_issuers", "number", tr(language, "HKMA stablecoin issuers", "金管局稳定币发行人")),
        ("sfc_licensed_count", "sfc_vatps", "number", tr(language, "SFC licensed VATPs", "证监会持牌 VATP")),
        ("sfc_pending_count", "sfc_vatps", "number", tr(language, "SFC pending VATPs", "证监会申请中 VATP")),
    )
    register_available = any(
        not frame_for_dataset(artifact, dataset_id).empty
        for _, dataset_id, _, _ in status_metrics
    )
    with st.container(border=True):
        columns = st.columns(len(status_metrics))
        for column, (field, dataset_id, fmt, label) in zip(columns, status_metrics):
            with column:
                register_rows = frame_for_dataset(artifact, dataset_id)
                value = format_metric(kpi.get(field), fmt) if not register_rows.empty else "—"
                st.metric(label, value)
                st.caption(
                    tr(language, "Current register snapshot", "当前登记册快照")
                    if value != "—"
                    else tr(
                        language,
                        "Register unavailable in this artifact build",
                        "本次 artifact 构建没有可用登记册记录",
                    )
                )
    if not register_available:
        st.caption(
            tr(
                language,
                "A blank status is different from zero: the latest local build did not contain register rows, so no licensing count is inferred.",
                "空白状态不等于零：最新本地构建没有登记册记录，因此不推断持牌数量。",
            )
        )

    news = frame_for_dataset(artifact, "regulatory_news").copy()
    required_news_columns = {"issue_date", "source"}
    if news.empty or not required_news_columns.issubset(news.columns):
        st.info(tr(language, "No official regulatory news is available.", "没有可用的官方监管新闻。"))
    else:
        news["_date"] = pd.to_datetime(news["issue_date"], errors="coerce")
        news = news.dropna(subset=["_date"]).sort_values("_date", ascending=False).copy()
        latest_news_date = news["_date"].max()
        recent = news[news["_date"] >= latest_news_date - pd.Timedelta(days=90)]
        source_counts = recent["source"].astype(str).str.upper().value_counts()
        source_cards = (
            ("HKMA", tr(language, "HKMA releases", "金管局新闻")),
            ("SFC", tr(language, "SFC releases", "证监会新闻")),
            ("__total__", tr(language, "Official releases", "官方新闻合计")),
        )
        with st.container(border=True):
            columns = st.columns(len(source_cards))
            for column, (source, label) in zip(columns, source_cards):
                with column:
                    count = len(recent) if source == "__total__" else int(source_counts.get(source, 0))
                    st.metric(label, f"{count:,}")
                    st.caption(
                        tr(
                            language,
                            f"Trailing 90 days through {latest_news_date:%d %b %Y}",
                            f"截至 {latest_news_date.year}年{latest_news_date.month}月{latest_news_date.day}日的最近90日",
                        )
                    )

        monthly = news.assign(month=news["_date"].dt.to_period("M").dt.to_timestamp())
        monthly["source_display"] = monthly["source"].astype(str).str.upper().map(
            {
                "HKMA": tr(language, "HKMA", "金管局"),
                "SFC": tr(language, "SFC", "证监会"),
            }
        ).fillna(monthly["source"].astype(str).str.upper())
        monthly = (
            monthly.groupby(["month", "source_display"], as_index=False)
            .size()
            .rename(columns={"size": "count"})
            .sort_values("month")
        )
        st.markdown(
            f'<div class="am-chart-title">{tr(language, "Official regulatory news activity", "官方监管新闻活动度")}</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            tr(
                language,
                "Monthly count of crypto-relevant HKMA and SFC releases retained by the artifact; this is an activity count, not a policy score.",
                "artifact 保留的金管局及证监会加密相关新闻月度数量；这是活动度统计，不是政策评分。",
            )
        )
        fig = px.bar(
            monthly,
            x="month",
            y="count",
            color="source_display",
            barmode="stack",
            color_discrete_sequence=PALETTE,
        )
        fig.update_xaxes(title=None, tickformat="%b %Y")
        fig.update_yaxes(title=tr(language, "Official releases", "官方新闻数"), dtick=1)
        for trace in fig.data:
            trace.hovertemplate = f"<b>%{{x|%b %Y}}</b><br>{trace.name}: %{{y:,.0f}}<extra></extra>"
        fig = chart_theme(fig, date_axis=True, height=370)
        st.plotly_chart(fig, width="stretch", config={"displaylogo": False, "responsive": True})

    section_heading(
        language,
        "Policy timeline",
        "政策时间线",
        "The table is an official-source timeline, not a media sentiment feed.",
        "以下是官方来源时间线，不是媒体情绪新闻流。",
    )
    with st.container(border=True):
        render_table(artifact, labels, "regulatory_news_table", language)

    with st.expander(
        tr(language, "Market expectations — separate from official policy facts", "市场预期——与官方政策事实分开"),
        expanded=False,
    ):
        st.caption(
            tr(
                language,
                "Polymarket probabilities are prediction-market observations, not HKMA or SFC positions.",
                "Polymarket 概率是预测市场观察值，不代表金管局或证监会立场。",
            )
        )
        render_table(artifact, labels, "polymarket_table", language)

    with st.expander(tr(language, "Company disclosures on HKEXnews", "港交所披露易公司公告"), expanded=False):
        st.caption(
            tr(
                language,
                "Recent announcements from the tracked Hong Kong crypto/stablecoin company watchlist; these are company disclosures, not regulatory decisions.",
                "香港加密／稳定币观察名单公司的近期公告；这是公司披露，不是监管决定。",
            )
        )
        render_table(artifact, labels, "hkexnews_announcements_table", language)


def render_crypto(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None:
    """Render V1 as global crypto context plus an official HK policy pulse.

    Local adoption and on-chain Hong Kong activity remain outside this first
    page until a recurring data series is validated.
    """
    render_header(
        artifact,
        labels,
        language,
        "crypto",
        title_override=tr(language, "Global Crypto Market Context", "全球加密市场背景"),
        description_override=tr(
            language,
            "V1 combines global stablecoin liquidity, decentralized-exchange activity and crypto sentiment with an official Hong Kong regulatory and policy pulse. Local adoption signals remain a later data track.",
            "V1 结合全球稳定币流动性、去中心化交易所活动、加密市场情绪，以及香港官方监管与政策脉搏。本地采用度信号待后续数据验证后接入。",
        ),
    )

    stablecoin = frame_for_dataset(artifact, "stablecoin_history")
    dex_volume = frame_for_dataset(artifact, "dex_volume_history")
    fear_greed = frame_for_dataset(artifact, "fear_greed_history")
    fear_greed_daily = frame_for_dataset(artifact, "fear_greed_daily")

    section_heading(
        language,
        "Global market pulse",
        "全球市场脉搏",
        "Stablecoin supply and DEX volume remain monthly long-history series; Fear & Greed also has a daily research view below.",
        "稳定币供应量及 DEX 交易量保留月度长期序列；下方另提供恐惧与贪婪的日度研究视图。",
    )
    stablecoin_signal = latest_period_signal(stablecoin, "date", "circulating_usd_bn", aggregation="mean")
    dex_signal = latest_period_signal(dex_volume, "date", "dex_volume_usd_bn", aggregation="mean")
    fear_greed_signal = latest_period_signal(fear_greed, "date", "score", aggregation="mean")
    daily_fear_greed_signal = latest_daily_signal(fear_greed_daily, "score")
    rolling_fear_greed_signal = latest_daily_signal(fear_greed_daily, "score_7d_avg")
    if daily_fear_greed_signal["value"] is None:
        daily_fear_greed_signal = fear_greed_signal
    cards = [
        (
            tr(language, "Stablecoin supply ($B)", "稳定币供应量（十亿美元）"),
            stablecoin_signal,
            "number",
            tr(language, "Monthly average of daily circulating supply", "每日流通供应量月均值"),
            True,
        ),
        (
            tr(language, "DEX volume ($B/day)", "DEX 交易量（十亿美元／日）"),
            dex_signal,
            "number",
            tr(language, "Monthly average daily volume, not monthly total", "月均每日交易量，不是当月总额"),
            True,
        ),
        (
            tr(language, "Fear & Greed daily", "恐惧与贪婪（日度）"),
            daily_fear_greed_signal,
            "number",
            tr(language, "Daily score from 0 (fear) to 100 (greed)", "日度分数，0 代表恐惧，100 代表贪婪"),
            False,
        ),
        (
            tr(language, "Fear & Greed 7-day avg", "恐惧与贪婪（7日均值）"),
            rolling_fear_greed_signal,
            "number",
            tr(language, "Trailing seven-calendar-day average", "最近七个日历日的滚动平均"),
            False,
        ),
    ]
    columns = st.columns(len(cards))
    for column, (label, signal, fmt, note, show_delta) in zip(columns, cards):
        with column:
            st.metric(
                label,
                format_metric(signal.get("value"), fmt),
                delta=crypto_metric_delta(signal) if show_delta else None,
            )
            st.caption(f"{note} · {observation_date_label(signal.get('date'), language)}")

    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "stablecoin_history_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=430,
        )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "dex_volume_history_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=430,
        )
    with st.container(border=True):
        render_fear_greed_daily_chart(artifact, language, window)
    with st.container(border=True):
        st.caption(
            tr(
                language,
                "Long-run monthly average for context.",
                "长期月度平均，用于长期背景比较。",
            )
        )
        st.caption(
            tr(
                language,
                "Reference bands: 0–24 Extreme Fear · 25–49 Fear · 50–74 Greed · 75–100 Extreme Greed.",
                "参考区间：0–24 极度恐惧 · 25–49 恐惧 · 50–74 贪婪 · 75–100 极度贪婪。",
            )
        )
        render_line_chart(
            artifact,
            labels,
            "fear_greed_history_chart",
            language,
            window,
            views=("Level",),
            periods_per_year=12,
            height=430,
            reference_bands=(
                (0, 25, "#ef4444"),
                (25, 50, "#f59e0b"),
                (50, 75, "#84cc16"),
                (75, 100, "#16a34a"),
            ),
        )

    section_heading(
        language,
        "Crypto attention",
        "加密资产关注度",
        "Wikipedia pageviews are an attention proxy, not trading activity. The weekly view separates traffic agents; the monthly view keeps user pageviews by topic page.",
        "Wikipedia 页面访问量是关注度代理，不是交易活动。周度图按流量代理拆分，月度图按主题页面保留用户访问量。",
    )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "wikipedia_crypto_attention_agent_weekly_chart",
            language,
            window,
            views=("Level", "WoW %", "YoY %"),
            periods_per_year=52,
            height=430,
            series_label_map=(
                CRYPTO_ATTENTION_AGENT_LABELS_ZH
                if language == "zh"
                else CRYPTO_ATTENTION_AGENT_LABELS
            ),
        )
    with st.container(border=True):
        render_line_chart(
            artifact,
            labels,
            "wikipedia_crypto_user_attention_monthly_chart",
            language,
            window,
            views=("Level", "MoM %", "YoY %"),
            periods_per_year=12,
            height=430,
            series_label_map=CRYPTO_PAGE_LABELS_ZH if language == "zh" else CRYPTO_PAGE_LABELS,
        )
    st.caption(
        tr(
            language,
            "Coverage: curated English Wikipedia pages for Bitcoin, Ethereum, stablecoins and DeFi. Automated/spider traffic is retained for transparency; use the user series for the cleaner attention signal.",
            "覆盖范围：精选英文 Wikipedia 比特币、以太坊、稳定币及 DeFi 页面。自动化程序和爬虫流量为透明度而保留；如需较干净的关注度信号，应优先查看用户序列。",
        )
    )

    with st.container(border=True):
        st.markdown(
            f'<div class="am-chart-title">{tr(language, "V1 scope note", "V1 范围说明")}</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            tr(
                language,
                "These global indicators are not Hong Kong trading-volume or stablecoin-adoption measures. The official HKMA/SFC policy layer below is a separate fact stream; HKEX ETF activity and local on-chain metrics remain separate data tracks.",
                "这些全球指标不代表香港交易量或本地稳定币采用度。下方的金管局／证监会政策层是独立的事实流；港交所 ETF 活动及本地链上指标仍是独立数据路径。",
            )
        )

    render_crypto_policy_pulse(artifact, labels, language)
    render_source_coverage({"crypto": artifact}, {"crypto": labels}, language)
