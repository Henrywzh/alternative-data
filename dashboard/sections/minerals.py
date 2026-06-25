from __future__ import annotations

import inspect
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import matplotlib
import yfinance as yf

from dashboard import remote
from dashboard.checks import CheckResult, run_checks
from dashboard.data import (DOMAIN_ORDER, DATASET_REGISTRY, DatasetLoadResult, FreshnessInfo, dataset_source_for_domain, domain_dataset_ids, load_domain_datasets, load_latest_manifest, repo_root)
from openrouter_revenue import (build_price_context, build_conservative_provider_economics, estimate_usage_revenue, summarize_economics_coverage)
from semiconductor_memory_data.sources.config import AI_DEMAND_PPI_WEIGHTS
from dashboard.theme import (ACCENT, BG, SIDEBAR, CARD, BORDER, TEXT, MUTED, GREEN, RED, YELLOW, GRID, TICK, MODEL_COLORS)
from dashboard.components import (format_metric, _empty_dataset_frame, _styler_applymap_compat, WEEKLY_MONTHLY_OTHER_PROVIDERS, DAILY_OTHER_PROVIDERS, US_PROVIDER_ORDER, CHINA_PROVIDER_ORDER, order_provider_columns, regroup_provider_pivot_for_display, render_dataset_guard, format_scraped_at_display, dataframe_for_display, make_stacked_bar, make_stacked_area_chart, make_line_chart, kpi_card_html, kpi_grid_html, _top_n_with_others)

BASE_DIR = repo_root()


_MINERALS_SIGNAL_ROOT = BASE_DIR / "data" / "processed" / "minerals_signal_data"


def _minerals_partition_dir(dataset: str) -> Path | None:
    """Resolve a minerals dataset partition: prefer `latest`, else the newest dated run."""
    root = _MINERALS_SIGNAL_ROOT / dataset
    if not root.exists():
        return None
    latest = root / "latest"
    if latest.exists():
        return latest
    candidates = sorted(p for p in root.iterdir() if p.is_dir())
    return candidates[-1] if candidates else None


@st.cache_data(ttl=3600)
def _load_minerals_csv(dataset: str) -> pd.DataFrame:
    part = _minerals_partition_dir(dataset)
    if part is None:
        return pd.DataFrame()
    path = part / f"{dataset}.csv"
    if not path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(path)
    for column in ("date", "signal_date", "as_of_date", "source_timestamp"):
        if column in frame.columns:
            frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def render_minerals_section() -> None:
    st.markdown("## ⛏️ Critical Minerals")
    st.caption(
        "Price trends for USGS critical minerals and their related listed stocks. "
        "Mineral prices come from public commodity feeds (yfinance futures/ETFs, FRED, Investing.com); "
        "weekly bullish markers flag weeks where both the 4-week and 12-week returns are positive."
    )

    universe = _load_minerals_csv("mineral_price_universe_live")
    prices = _load_minerals_csv("mineral_price_series_daily")
    signals = _load_minerals_csv("mineral_signal_weekly")
    mapping = _load_minerals_csv("stock_mapping_expanded_live")
    stock_prices = _load_minerals_csv("stock_price_series_daily")

    if prices.empty:
        st.warning("No minerals price data is available in this deployment.")
        st.caption(
            "Expected the `latest` partition under `data/processed/minerals_signal_data/`. "
            "Run the weekly pipeline: `minerals-signal-data run-v2 --run-label latest "
            "--workbook data/reference/minerals_signal_data/critical_minerals.csv "
            "--stock-mapping data/reference/minerals_signal_data/stock_mapping.csv`."
        )
        return

    name_by_id = dict(zip(prices["normalized_mineral_id"], prices["mineral_name"]))
    tracked_ids = sorted(prices["normalized_mineral_id"].unique(), key=lambda i: name_by_id.get(i, i))
    labels = [str(name_by_id.get(i, i)) for i in tracked_ids]

    sel_col, _ = st.columns([2, 3])
    with sel_col:
        selected_label = st.selectbox("Mineral", labels, index=0)
    selected_id = tracked_ids[labels.index(selected_label)]
    selected_name = name_by_id.get(selected_id, selected_id)

    meta_rows = universe.loc[universe["normalized_mineral_id"] == selected_id] if not universe.empty else pd.DataFrame()
    meta = meta_rows.iloc[0] if not meta_rows.empty else None

    m_prices = prices.loc[prices["normalized_mineral_id"] == selected_id].sort_values("date")
    m_signals = (
        signals.loc[signals["normalized_mineral_id"] == selected_id].sort_values("signal_date")
        if not signals.empty
        else pd.DataFrame()
    )

    # ── Header metrics ────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    if meta is not None:
        col1.metric("Trackability", str(meta.get("trackability_grade", "—")))
        col2.metric("Price source", str(meta.get("price_source_type", "—")))
        col3.metric("Currency", str(meta.get("price_currency", "—")) or "—")
    latest_price = float(m_prices["price"].iloc[-1])
    latest_date = m_prices["date"].iloc[-1]
    col4.metric(
        "Latest price",
        f"{latest_price:,.2f}",
        help=f"As of {pd.Timestamp(latest_date).date()}",
    )

    # ── Price trend with weekly signal overlay ────────────────────────────────
    st.markdown("### Price trend")
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=m_prices["date"],
        y=m_prices["price"],
        name=str(selected_name),
        line=dict(color=ACCENT, width=2),
        hovertemplate="%{x|%Y-%m-%d}<br>Price: %{y:.2f}<extra></extra>",
    ))
    if not m_signals.empty and "signal_state" in m_signals.columns:
        bullish = m_signals.loc[m_signals["signal_state"] == "bullish"]
        if not bullish.empty:
            fig.add_trace(go.Scatter(
                x=bullish["signal_date"],
                y=bullish["price"],
                name="Bullish week",
                mode="markers",
                marker=dict(color=GREEN, size=8, symbol="triangle-up"),
                hovertemplate="%{x|%Y-%m-%d}<br>Bullish<br>Price: %{y:.2f}<extra></extra>",
            ))
    fig.update_layout(
        template="plotly_white",
        height=420,
        margin=dict(l=0, r=0, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis=dict(title=dict(text=f"Price ({meta.get('price_currency', '') if meta is not None else ''})"), gridcolor=GRID),
        xaxis=dict(gridcolor=GRID),
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch", theme=None)

    # ── Related stocks (rebased to 100) ───────────────────────────────────────
    st.markdown("### Related stocks")
    links = mapping.loc[mapping["normalized_mineral_id"] == selected_id] if not mapping.empty else pd.DataFrame()
    if links.empty:
        st.info(f"No related stocks are mapped for {selected_name}.")
        return

    ticker_rows = links.drop_duplicates("ticker_normalized")
    market_by_ticker = dict(zip(ticker_rows["ticker_normalized"], ticker_rows["market"]))
    is_primary = ticker_rows["is_primary_exposure"].astype(str).str.lower().isin(["true", "1"])
    primary_tickers = ticker_rows.loc[is_primary, "ticker_normalized"].tolist()
    all_tickers = ticker_rows["ticker_normalized"].tolist()
    default_tickers = (primary_tickers or all_tickers)[:5]

    chosen = st.multiselect(
        "Tickers",
        all_tickers,
        default=default_tickers,
        format_func=lambda t: f"{t} ({market_by_ticker.get(t, '?')})",
    )
    if not chosen:
        st.caption("Select one or more tickers to compare price trends.")
        return

    sp = (
        stock_prices.loc[stock_prices["ticker_normalized"].isin(chosen)]
        if not stock_prices.empty
        else pd.DataFrame()
    )
    if sp.empty:
        st.info("No price history is available for the selected tickers.")
        return

    fig2 = go.Figure()
    for index, (ticker, group) in enumerate(sp.groupby("ticker_normalized")):
        group = group.sort_values("date")
        base = group["adj_close"].iloc[0]
        if not base or pd.isna(base):
            continue
        rebased = group["adj_close"] / base * 100.0
        fig2.add_trace(go.Scatter(
            x=group["date"],
            y=rebased,
            name=f"{ticker} ({market_by_ticker.get(ticker, '?')})",
            line=dict(color=MODEL_COLORS[index % len(MODEL_COLORS)], width=1.8),
            hovertemplate="%{x|%Y-%m-%d}<br>" + str(ticker) + ": %{y:.1f}<extra></extra>",
        ))
    fig2.update_layout(
        template="plotly_white",
        height=420,
        margin=dict(l=0, r=0, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis=dict(title=dict(text="Rebased price (=100 at start)"), gridcolor=GRID),
        xaxis=dict(gridcolor=GRID),
        hovermode="x unified",
    )
    st.caption("Each line is rebased to 100 at the start of its available history for comparability.")
    st.plotly_chart(fig2, width="stretch", theme=None)


_TUNGSTEN_SERIES = [
    "apt",
    "european_apt",
    "wolframite_concentrate",
    "scheelite_concentrate",
    "ferrotungsten",
    "tungsten_powder",
    "tungsten_carbide_powder",
    "cobalt_powder",
    "scrap_carbide_rod",
]


def _render_tungsten_panel() -> None:
    st.markdown("### Tungsten prices (Chinatungsten daily)")
    frame = _load_minerals_csv("tungsten_price_daily")
    if frame.empty:
        st.info(
            "No tungsten price data yet. Run "
            "`minerals-signal-data scrape-tungsten --base-dir .` to populate it."
        )
        return

    series_cols = [c for c in _TUNGSTEN_SERIES if c in frame.columns]
    labels = {col: col.replace("_", " ").title() for col in series_cols}
    st.caption(
        "Daily Chinatungsten product prices. Series use different units "
        "(RMB/tonne, USD/mtu, RMB/kg), so each line is rebased to 100 at its first "
        "available value for comparability."
    )
    default = [c for c in ("apt", "wolframite_concentrate", "ferrotungsten") if c in series_cols]
    chosen = st.multiselect(
        "Tungsten series",
        series_cols,
        default=default or series_cols[:3],
        format_func=lambda c: labels[c],
    )
    if not chosen:
        st.caption("Select one or more series to compare.")
        return

    fig = go.Figure()
    for index, col in enumerate(chosen):
        series = frame[["date", col]].dropna()
        series = series[series[col] > 0].sort_values("date")
        if series.empty:
            continue
        base = series[col].iloc[0]
        fig.add_trace(go.Scatter(
            x=series["date"],
            y=series[col] / base * 100.0,
            name=labels[col],
            line=dict(color=MODEL_COLORS[index % len(MODEL_COLORS)], width=1.8),
            hovertemplate="%{x|%Y-%m-%d}<br>" + labels[col] + ": %{y:.1f}<extra></extra>",
        ))
    fig.update_layout(
        template="plotly_white",
        height=420,
        margin=dict(l=0, r=0, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis=dict(title=dict(text="Rebased price (=100 at first value)"), gridcolor=GRID),
        xaxis=dict(gridcolor=GRID),
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch", theme=None)


def render(domain_states, datasets) -> None:
    render_minerals_section()
    _render_tungsten_panel()
