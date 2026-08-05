from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.components import dataframe_for_display, format_metric, kpi_card_html, kpi_grid_html, make_stacked_area_chart
from dashboard.data import DatasetLoadResult
from dashboard.theme import CARD, GRID, MODEL_COLORS, MUTED, TEXT


MARKET_SHARE_ID = "opencode_market_share"
LEADERBOARD_ID = "opencode_leaderboard"
COUNTRY_ID = "opencode_country_usage"
DEEPDIVES_ID = "opencode_model_deepdives"

DEFAULT_TIER = "All Users"
DAILY_TIMEFRAME = "1D"
MONTHLY_TIMEFRAME = "1M"

# (timeframe code, display label) for the over-time chart's window selector.
# Only day-granularity timeframes are listed here — "ALL"/"YTD" bucket by
# month instead of day and aren't useful for a daily trend line.
OVER_TIME_WINDOWS = [("1M", "30 days"), ("3M", "90 days")]


def _frame(datasets: dict[str, DatasetLoadResult], dataset_id: str) -> pd.DataFrame:
    result = datasets.get(dataset_id)
    return result.frame.copy() if result is not None and not result.frame.empty else pd.DataFrame()


def _prepare(datasets: dict[str, DatasetLoadResult]) -> dict[str, pd.DataFrame]:
    market_share = _frame(datasets, MARKET_SHARE_ID)
    leaderboard = _frame(datasets, LEADERBOARD_ID)
    country = _frame(datasets, COUNTRY_ID)
    deepdives = _frame(datasets, DEEPDIVES_ID)

    if not leaderboard.empty:
        leaderboard["tokens"] = pd.to_numeric(leaderboard["tokens"], errors="coerce")
        leaderboard["rank"] = pd.to_numeric(leaderboard["rank"], errors="coerce")
    if not market_share.empty:
        market_share["tokens_trillion"] = pd.to_numeric(market_share["tokens_trillion"], errors="coerce")
        market_share["share_pct"] = pd.to_numeric(market_share["share_pct"], errors="coerce")
    if not country.empty:
        country["tokens_trillion"] = pd.to_numeric(country["tokens_trillion"], errors="coerce")
        country["share_pct"] = pd.to_numeric(country["share_pct"], errors="coerce")
    if not deepdives.empty:
        for column in (
            "sessions", "unique_users", "tokens_total", "cost_total_usd",
            "cost_per_session_usd", "cache_ratio_pct",
        ):
            deepdives[column] = pd.to_numeric(deepdives[column], errors="coerce")

    return {
        "market_share": market_share,
        "leaderboard": leaderboard,
        "country": country,
        "deepdives": deepdives,
    }


def _latest_leaderboard(leaderboard: pd.DataFrame) -> pd.DataFrame:
    if leaderboard.empty:
        return leaderboard
    latest_date = leaderboard["snapshot_date"].max()
    scoped = leaderboard[
        (leaderboard["snapshot_date"] == latest_date)
        & (leaderboard["user_tier"] == DEFAULT_TIER)
        & (leaderboard["timeframe"] == DAILY_TIMEFRAME)
    ]
    return scoped.sort_values("rank")


def _render_kpis(leaderboard: pd.DataFrame, country: pd.DataFrame) -> None:
    latest_lb = _latest_leaderboard(leaderboard)
    top_model = str(latest_lb.iloc[0]["model_slug"]) if not latest_lb.empty else "—"
    total_tokens = float(latest_lb["tokens"].sum()) if not latest_lb.empty else 0.0
    latest_date = str(leaderboard["snapshot_date"].max()) if not leaderboard.empty else "—"

    top_country = "—"
    if not country.empty:
        monthly = country[country["timeframe"] == MONTHLY_TIMEFRAME]
        scoped = monthly if not monthly.empty else country
        latest_country_date = scoped["snapshot_date"].max()
        scoped = scoped[scoped["snapshot_date"] == latest_country_date].sort_values("share_pct", ascending=False)
        if not scoped.empty:
            top_country = str(scoped.iloc[0]["country_code"])

    st.markdown(
        kpi_grid_html(
            kpi_card_html("Latest Snapshot", latest_date, delta="daily scrape of opencode.ai/data"),
            kpi_card_html("Top Coding Model", top_model, delta=f"{DEFAULT_TIER} · {DAILY_TIMEFRAME} leaderboard"),
            kpi_card_html("Daily Token Volume", format_metric(total_tokens), delta="top-ranked models, latest day"),
            kpi_card_html("Top Adoption Country", top_country, delta=f"{MONTHLY_TIMEFRAME} window, by token share"),
        ),
        unsafe_allow_html=True,
    )


def _render_market_share(market_share: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Model Author Market Share</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Share of OpenCode coding-agent token volume by model author, latest day.</div>',
        unsafe_allow_html=True,
    )
    scoped = market_share[market_share["timeframe"] == DAILY_TIMEFRAME]
    if scoped.empty:
        st.info("No daily market share snapshot is available yet.")
        return
    scoped = scoped.sort_values("share_pct", ascending=True)
    figure = go.Figure(go.Bar(
        x=scoped["share_pct"], y=scoped["author"], orientation="h",
        marker_color=MODEL_COLORS[0],
        text=scoped["share_pct"], texttemplate="%{text:.1f}%", textposition="outside", cliponaxis=False,
        hovertemplate="%{y}<br><b>%{x:.1f}%</b> token share<extra></extra>",
    ))
    figure.update_layout(
        template="plotly_white", height=max(280, 28 * len(scoped)), margin=dict(l=0, r=30, t=12, b=30),
        paper_bgcolor=CARD, plot_bgcolor=CARD, font=dict(color=TEXT, size=12),
        xaxis=dict(gridcolor=GRID, title="Token share", ticksuffix="%"), yaxis=dict(showgrid=False),
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


def _parse_usage_date(usage_date: object, reference_year: int, reference_month: int) -> pd.Timestamp | None:
    """Parse a source chart's "AUG 4"-style axis label into a real date.

    opencode.ai's day-granularity timeframes never repeat a month label
    within one window, so the label alone (plus the scrape's own year) is
    enough — except right at a year boundary, where a label like "DEC 31"
    scraped in early January actually belongs to the previous year.
    """
    if pd.isna(usage_date):
        return None
    try:
        candidate = pd.to_datetime(f"{str(usage_date).strip()} {reference_year}", format="%b %d %Y")
    except (ValueError, TypeError):
        return None
    if candidate.month - reference_month > 6:
        candidate = candidate.replace(year=reference_year - 1)
    return candidate


def _render_usage_over_time(market_share: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Token Volume Over Time</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Daily coding-agent token volume by model author. '
        'opencode.ai publishes this history directly, so it\'s available from day one rather '
        'than something we have to accumulate across our own daily scrapes.</div>',
        unsafe_allow_html=True,
    )
    window_codes = [code for code, _ in OVER_TIME_WINDOWS]
    window_labels = dict(OVER_TIME_WINDOWS)
    window = st.radio(
        "Window", window_codes, index=1, horizontal=True,
        format_func=lambda code: window_labels[code], key="opencode_usage_over_time_window",
    )

    scoped = market_share[market_share["timeframe"] == window].copy()
    if scoped.empty:
        st.info("No historical market share data is available yet.")
        return

    reference = pd.to_datetime(scoped["scraped_at"], errors="coerce", utc=True).max()
    if pd.isna(reference):
        st.info("No historical market share data is available yet.")
        return
    scoped["date"] = scoped["usage_date"].apply(lambda v: _parse_usage_date(v, reference.year, reference.month))
    scoped = scoped.dropna(subset=["date"])
    if scoped.empty:
        st.info("No historical market share data is available yet.")
        return

    pivot = scoped.pivot_table(index="date", columns="author", values="tokens_trillion", aggfunc="last").sort_index()
    # Largest-author-first column order keeps stacking/legend order matching
    # a natural reading of the latest day, and keeps colors stable day to day.
    latest_row = pivot.iloc[-1].sort_values(ascending=False)
    pivot = pivot[latest_row.index]
    display_index = [d.strftime("%b %d") for d in pivot.index]

    figure = make_stacked_area_chart(
        pivot, display_index=display_index, colors=MODEL_COLORS,
        x_title="Date", y_title="Trillion tokens", value_format=",.2f",
        height=420,
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


def _render_leaderboard(leaderboard: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Coding Agent Leaderboard</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Top models by token volume across coding-agent sessions, latest day.</div>',
        unsafe_allow_html=True,
    )
    latest_lb = _latest_leaderboard(leaderboard)
    if latest_lb.empty:
        st.info("No leaderboard snapshot is available yet.")
        return
    table = latest_lb.rename(
        columns={
            "rank": "Rank", "model_slug": "Model", "provider": "Provider", "author": "Author",
            "tokens": "Tokens", "rank_change": "Rank Δ",
        }
    )[["Rank", "Model", "Provider", "Author", "Tokens", "Rank Δ"]]
    st.dataframe(
        dataframe_for_display(table),
        width="stretch", hide_index=True, height=420,
        column_config={"Tokens": st.column_config.NumberColumn("Tokens", format="%d")},
    )


def _render_country_usage(country: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Geographic Developer Adoption</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="section-subtitle">Top countries by coding-agent token volume, {MONTHLY_TIMEFRAME} window.</div>',
        unsafe_allow_html=True,
    )
    monthly = country[country["timeframe"] == MONTHLY_TIMEFRAME]
    scoped = monthly if not monthly.empty else country
    if scoped.empty:
        st.info("No country adoption snapshot is available yet.")
        return
    latest_date = scoped["snapshot_date"].max()
    scoped = scoped[scoped["snapshot_date"] == latest_date].sort_values("tokens_trillion", ascending=False).head(15)
    scoped = scoped.sort_values("tokens_trillion", ascending=True)
    figure = go.Figure(go.Bar(
        x=scoped["tokens_trillion"], y=scoped["country_code"], orientation="h",
        marker_color=MODEL_COLORS[2],
        text=scoped["share_pct"], texttemplate="%{text:.1f}%", textposition="outside", cliponaxis=False,
        hovertemplate="%{y}<br><b>%{x:.2f}T</b> tokens<extra></extra>",
    ))
    figure.update_layout(
        template="plotly_white", height=440, margin=dict(l=0, r=30, t=12, b=30),
        paper_bgcolor=CARD, plot_bgcolor=CARD, font=dict(color=TEXT, size=12),
        xaxis=dict(gridcolor=GRID, title="Trillion tokens"), yaxis=dict(showgrid=False),
    )
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    st.caption("Bar labels show token share of the window total, not the bar's own axis.")


def _render_model_economics(deepdives: pd.DataFrame) -> None:
    st.markdown('<div class="section-title">Model Session Economics</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Sessions, spend, and cache efficiency for the top tracked models\' dedicated deepdive pages.</div>',
        unsafe_allow_html=True,
    )
    if deepdives.empty:
        st.info("No model deepdive data is available yet.")
        return
    latest_date = deepdives["snapshot_date"].max()
    scoped = deepdives[deepdives["snapshot_date"] == latest_date].sort_values("tokens_total", ascending=False)
    table = scoped.rename(
        columns={
            "model_slug": "Model", "author": "Author", "sessions": "Sessions", "unique_users": "Unique Users",
            "tokens_total": "Total Tokens", "cost_total_usd": "Total Cost (USD)",
            "cost_per_session_usd": "Cost / Session (USD)", "cache_ratio_pct": "Cache Ratio",
        }
    )[["Model", "Author", "Sessions", "Unique Users", "Total Tokens", "Total Cost (USD)", "Cost / Session (USD)", "Cache Ratio"]]
    st.dataframe(
        dataframe_for_display(table),
        width="stretch", hide_index=True, height=420,
        column_config={
            "Total Tokens": st.column_config.NumberColumn("Total Tokens", format="%d"),
            "Total Cost (USD)": st.column_config.NumberColumn("Total Cost (USD)", format="$%.2f"),
            "Cost / Session (USD)": st.column_config.NumberColumn("Cost / Session (USD)", format="$%.4f"),
            "Cache Ratio": st.column_config.NumberColumn("Cache Ratio", format="%.1f%%"),
        },
    )


def render(domain_states, datasets: dict[str, DatasetLoadResult]) -> None:
    _ = domain_states
    st.markdown('<div class="section-title" style="margin-top:0.25rem;">OpenCode Coding Agent Data</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Developer demand for AI coding agents — model market share, token volume, geographic adoption, and per-model session economics from opencode.ai/data.</div>',
        unsafe_allow_html=True,
    )
    frames = _prepare(datasets)
    market_share = frames["market_share"]
    leaderboard = frames["leaderboard"]
    country = frames["country"]
    deepdives = frames["deepdives"]

    if leaderboard.empty and market_share.empty:
        st.info("Run the OpenCode scrape pipeline to populate this page.")
        return

    _render_kpis(leaderboard, country)
    _render_leaderboard(leaderboard)
    _render_market_share(market_share)
    _render_usage_over_time(market_share)
    _render_country_usage(country)
    _render_model_economics(deepdives)
    st.caption("Source: opencode.ai/data (unofficial usage dashboard) · refreshed daily. History accumulates day over day; trend views will follow once enough daily snapshots exist.")
