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
_MINERALS_REFERENCE_ROOT = BASE_DIR / "data" / "reference" / "minerals_signal_data"


_CHINATUNGSTEN_MINERAL_IDS = {"tungsten", "molybdenum", "rare_earth"}


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


_MOLYBDENUM_SERIES = [
    "molybdenum_concentrate",
    "ferromolybdenum",
    "ammonium_heptamolybdate",
    "ammonium_tetramolybdate",
]


_RARE_EARTH_SERIES = [
    "lanthanum_oxide",
    "cerium_oxide",
    "praseodymium_oxide",
    "neodymium_oxide",
    "samarium_oxide",
    "europium_oxide",
    "gadolinium_oxide",
    "terbium_oxide",
    "dysprosium_oxide",
    "holmium_oxide",
    "erbium_oxide",
    "yttrium_oxide",
]


_CHINATUNGSTEN_SERIES = {
    "tungsten": {
        "dataset": "tungsten_price_daily",
        "mineral_name": "Tungsten",
        "series": _TUNGSTEN_SERIES,
        "default": ["apt", "wolframite_concentrate", "ferrotungsten"],
    },
    "molybdenum": {
        "dataset": "molybdenum_price_daily",
        "mineral_name": "Molybdenum",
        "series": _MOLYBDENUM_SERIES,
        "default": ["molybdenum_concentrate", "ferromolybdenum", "ammonium_heptamolybdate"],
    },
    "rare_earth": {
        "dataset": "rare_earth_price_daily",
        "mineral_name": "Rare Earth",
        "series": _RARE_EARTH_SERIES,
        "default": ["praseodymium_oxide", "neodymium_oxide", "dysprosium_oxide"],
    },
}


_PRODUCT_LABELS = {
    "apt": "APT",
    "european_apt": "European APT",
    "wolframite_concentrate": "Wolframite Concentrate",
    "scheelite_concentrate": "Scheelite Concentrate",
    "ferrotungsten": "Ferrotungsten",
    "tungsten_powder": "Tungsten Powder",
    "tungsten_carbide_powder": "Tungsten Carbide Powder",
    "cobalt_powder": "Cobalt Powder",
    "scrap_carbide_rod": "Scrap Carbide Rod",
    "molybdenum_concentrate": "Molybdenum Concentrate",
    "ferromolybdenum": "Ferromolybdenum",
    "ammonium_heptamolybdate": "Ammonium Heptamolybdate",
    "ammonium_tetramolybdate": "Ammonium Tetramolybdate",
    "lanthanum_oxide": "Lanthanum Oxide",
    "cerium_oxide": "Cerium Oxide",
    "praseodymium_oxide": "Praseodymium Oxide",
    "neodymium_oxide": "Neodymium Oxide",
    "samarium_oxide": "Samarium Oxide",
    "europium_oxide": "Europium Oxide",
    "gadolinium_oxide": "Gadolinium Oxide",
    "terbium_oxide": "Terbium Oxide",
    "dysprosium_oxide": "Dysprosium Oxide",
    "holmium_oxide": "Holmium Oxide",
    "erbium_oxide": "Erbium Oxide",
    "yttrium_oxide": "Yttrium Oxide",
}


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


def _product_label(series_id: str) -> str:
    return _PRODUCT_LABELS.get(series_id, series_id.replace("_", " ").title())


def _format_source_label(source_type: str | object) -> str:
    labels = {
        "yfinance_futures": "Yahoo Finance",
        "fred_series": "FRED",
        "chinatungsten_daily": "Chinatungsten",
        "investing_html": "Investing.com",
    }
    source = str(source_type or "")
    return labels.get(source, source.replace("_", " ").title() if source else "—")


def _format_proxy_type(proxy_type: str | object) -> str:
    proxy = str(proxy_type or "")
    return proxy.replace("_", " ").title() if proxy else "—"


def _series_to_long(frame: pd.DataFrame, *, mineral_id: str, mineral_name: str, series_cols: list[str]) -> pd.DataFrame:
    if frame.empty or "date" not in frame.columns:
        return pd.DataFrame()
    rows: list[pd.DataFrame] = []
    for series_id in series_cols:
        if series_id not in frame.columns:
            continue
        series = frame[["date", series_id]].copy()
        series["date"] = pd.to_datetime(series["date"], errors="coerce")
        series["price"] = pd.to_numeric(series[series_id], errors="coerce")
        series = series.dropna(subset=["date", "price"])
        series = series.loc[series["price"] > 0, ["date", "price"]]
        if series.empty:
            continue
        series["normalized_mineral_id"] = mineral_id
        series["mineral_name"] = mineral_name
        series["source_type"] = "chinatungsten_daily"
        series["product_series"] = series_id
        series["product_label"] = _product_label(series_id)
        rows.append(series)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _build_chinatungsten_long_prices(
    tungsten: pd.DataFrame, molybdenum: pd.DataFrame, rare_earth: pd.DataFrame | None = None
) -> pd.DataFrame:
    rare_earth = rare_earth if rare_earth is not None else pd.DataFrame()
    frames = [
        _series_to_long(
            tungsten,
            mineral_id="tungsten",
            mineral_name="Tungsten",
            series_cols=_TUNGSTEN_SERIES,
        ),
        _series_to_long(
            molybdenum,
            mineral_id="molybdenum",
            mineral_name="Molybdenum",
            series_cols=_MOLYBDENUM_SERIES,
        ),
        _series_to_long(
            rare_earth,
            mineral_id="rare_earth",
            mineral_name="Rare Earth",
            series_cols=_RARE_EARTH_SERIES,
        ),
    ]
    frames = [frame for frame in frames if not frame.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _merge_mineral_selector_prices(base_prices: pd.DataFrame, chinatungsten_prices: pd.DataFrame) -> pd.DataFrame:
    if chinatungsten_prices.empty:
        return base_prices
    if base_prices.empty:
        return chinatungsten_prices
    filtered = base_prices.loc[
        ~base_prices["normalized_mineral_id"].isin(_CHINATUNGSTEN_MINERAL_IDS)
    ].copy()
    return pd.concat([filtered, chinatungsten_prices], ignore_index=True, sort=False)


def _merge_mineral_selector_universe(universe: pd.DataFrame, chinatungsten_prices: pd.DataFrame) -> pd.DataFrame:
    if chinatungsten_prices.empty:
        return universe
    base = universe.copy()
    if base.empty:
        base = pd.DataFrame(
            columns=[
                "normalized_mineral_id",
                "mineral_name",
                "trackability_grade",
                "price_source_type",
                "price_symbol_or_series_id",
                "price_currency",
                "price_unit",
                "publish_lag_assumption_days",
                "is_active_for_v1",
                "proxy_target",
                "proxy_type",
                "proxy_instrument",
                "proxy_display_name",
            ]
        )
    existing_ids = set(base.get("normalized_mineral_id", pd.Series(dtype=str)).dropna())
    additions = []
    for mineral_id, config in _CHINATUNGSTEN_SERIES.items():
        if mineral_id in existing_ids or mineral_id not in set(chinatungsten_prices["normalized_mineral_id"]):
            continue
        additions.append(
            {
                "normalized_mineral_id": mineral_id,
                "mineral_name": config["mineral_name"],
                "trackability_grade": "direct",
                "price_source_type": "chinatungsten_daily",
                "price_symbol_or_series_id": config["dataset"],
                "price_currency": "mixed",
                "price_unit": "mixed product units",
                "publish_lag_assumption_days": 1,
                "is_active_for_v1": True,
                "proxy_target": "",
                "proxy_type": "",
                "proxy_instrument": "",
                "proxy_display_name": "",
            }
        )
    if additions:
        base = pd.concat([base, pd.DataFrame(additions)], ignore_index=True, sort=False)
    return base


def _load_reference_stock_mapping(base_dir: Path) -> pd.DataFrame:
    path = base_dir / "data" / "reference" / "minerals_signal_data" / "stock_mapping.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _load_related_stock_links(mapping: pd.DataFrame, selected_id: str, base_dir: Path = BASE_DIR) -> pd.DataFrame:
    links = mapping.loc[mapping["normalized_mineral_id"] == selected_id] if not mapping.empty else pd.DataFrame()
    if not links.empty or selected_id != "tungsten":
        return links
    reference_mapping = _load_reference_stock_mapping(base_dir)
    if reference_mapping.empty:
        return pd.DataFrame()
    return reference_mapping.loc[reference_mapping["normalized_mineral_id"] == selected_id].copy()


def _shared_price_axis_range(mineral_prices: pd.DataFrame, stock_prices: pd.DataFrame) -> list[str] | None:
    """Return one calendar window for both charts, keeping source gaps visible."""
    dates: list[pd.Timestamp] = []
    for frame in (mineral_prices, stock_prices):
        if frame.empty or "date" not in frame.columns:
            continue
        parsed = pd.to_datetime(frame["date"], errors="coerce").dropna()
        if not parsed.empty:
            dates.extend([parsed.min(), parsed.max()])
    if len(dates) < 2:
        return None
    return [pd.Timestamp(min(dates)).strftime("%Y-%m-%d"), pd.Timestamp(max(dates)).strftime("%Y-%m-%d")]


def render_minerals_section() -> None:
    st.markdown("## ⛏️ Critical Minerals")
    st.caption(
        "Price trends for USGS critical minerals and their related listed stocks. "
        "The live dashboard uses stable public sources from Yahoo Finance, FRED, and Chinatungsten, "
        "with proxy minerals labeled by the actual tracked instrument."
    )

    universe = _load_minerals_csv("mineral_price_universe_live")
    base_prices = _load_minerals_csv("mineral_price_series_daily")
    tungsten_prices = _load_minerals_csv("tungsten_price_daily")
    molybdenum_prices = _load_minerals_csv("molybdenum_price_daily")
    rare_earth_prices = _load_minerals_csv("rare_earth_price_daily")
    chinatungsten_prices = _build_chinatungsten_long_prices(tungsten_prices, molybdenum_prices, rare_earth_prices)
    prices = _merge_mineral_selector_prices(base_prices, chinatungsten_prices)
    universe = _merge_mineral_selector_universe(universe, chinatungsten_prices)
    mapping = _load_minerals_csv("stock_mapping_expanded_live")
    stock_prices = _load_minerals_csv("stock_price_series_daily")

    if prices.empty:
        st.warning("No minerals price data is available in this deployment.")
        st.caption(
            "Expected the `latest` partition under `data/processed/minerals_signal_data/`. "
            "Run the live pipeline: `minerals-signal-data run-live --run-label latest "
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
    is_chinatungsten = selected_id in _CHINATUNGSTEN_MINERAL_IDS and "product_series" in m_prices.columns

    # ── Header metrics ────────────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    if meta is not None:
        col1.metric("Trackability", str(meta.get("trackability_grade", "—")))
        col2.metric("Price source", _format_source_label(meta.get("price_source_type", "—")))
        if str(meta.get("trackability_grade", "")) == "proxy":
            col3.metric("Proxy type", _format_proxy_type(meta.get("proxy_type", "")))
            instrument = str(meta.get("proxy_instrument", "") or meta.get("price_symbol_or_series_id", "") or "—")
            col4.metric("Tracked instrument", instrument)
            proxy_name = str(meta.get("proxy_display_name", "") or "").strip()
            if proxy_name:
                st.caption(f"Proxy instrument: {proxy_name}")
        else:
            col3.metric("Currency", str(meta.get("price_currency", "—")) or "—")
    latest_date = m_prices["date"].iloc[-1]
    if is_chinatungsten:
        if meta is None or str(meta.get("trackability_grade", "")) != "proxy":
            col4.metric("Latest date", str(pd.Timestamp(latest_date).date()))
    else:
        latest_price = float(m_prices["price"].iloc[-1])
        if meta is None or str(meta.get("trackability_grade", "")) != "proxy":
            col4.metric(
                "Latest price",
                f"{latest_price:,.2f}",
                help=f"As of {pd.Timestamp(latest_date).date()}",
            )
        else:
            st.caption(f"Latest price: {latest_price:,.2f} as of {pd.Timestamp(latest_date).date()}")

    # ── Price trend ───────────────────────────────────────────────────────────
    st.markdown("### Price trend")
    fig = go.Figure()
    selected_links = _load_related_stock_links(mapping, selected_id, BASE_DIR)
    linked_tickers = selected_links.get("ticker_normalized", pd.Series(dtype=str)).dropna().unique().tolist()
    linked_stock_prices = stock_prices.loc[
        stock_prices["ticker_normalized"].isin(linked_tickers)
    ] if not stock_prices.empty and linked_tickers else pd.DataFrame()
    shared_xrange = _shared_price_axis_range(m_prices, linked_stock_prices)
    if is_chinatungsten:
        product_rows = m_prices.dropna(subset=["product_series"]).copy()
        product_options = [
            series_id
            for series_id in _CHINATUNGSTEN_SERIES[selected_id]["series"]
            if series_id in set(product_rows["product_series"])
        ]
        default_products = [
            series_id for series_id in _CHINATUNGSTEN_SERIES[selected_id]["default"] if series_id in product_options
        ]
        chosen_products = st.multiselect(
            "Product series",
            product_options,
            default=default_products or product_options[:3],
            format_func=_product_label,
        )
        st.caption(
            "Chinatungsten product prices use different units, so selected product lines are rebased to "
            "100 at their first available value."
        )
        for index, series_id in enumerate(chosen_products):
            series = product_rows.loc[product_rows["product_series"] == series_id].sort_values("date")
            if series.empty:
                continue
            base = series["price"].iloc[0]
            if not base or pd.isna(base):
                continue
            fig.add_trace(go.Scatter(
                x=series["date"],
                y=series["price"] / base * 100.0,
                customdata=series["price"],
                name=_product_label(series_id),
                line=dict(color=MODEL_COLORS[index % len(MODEL_COLORS)], width=1.8),
                hovertemplate=(
                    "%{x|%Y-%m-%d}<br>"
                    + _product_label(series_id)
                    + " index: %{y:.1f}<br>Raw: %{customdata:,.2f}<extra></extra>"
                ),
            ))
    else:
        fig.add_trace(go.Scatter(
            x=m_prices["date"],
            y=m_prices["price"],
            name=str(selected_name),
            line=dict(color=ACCENT, width=2),
            hovertemplate="%{x|%Y-%m-%d}<br>Price: %{y:.2f}<extra></extra>",
        ))
    fig.update_layout(
        template="plotly_white",
        height=420,
        margin=dict(l=0, r=0, t=30, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis=dict(
            title=dict(
                text=(
                    "Rebased price (=100 at first value)"
                    if is_chinatungsten
                    else f"Price ({meta.get('price_currency', '') if meta is not None else ''})"
                )
            ),
            gridcolor=GRID,
        ),
        xaxis=dict(gridcolor=GRID, range=shared_xrange),
        hovermode="x unified",
    )
    st.plotly_chart(fig, width="stretch", theme=None)

    # ── Related stocks (rebased to 100) ───────────────────────────────────────
    st.markdown("### Related stocks")
    links = selected_links
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

    latest_stock_date = pd.to_datetime(sp["date"], errors="coerce").max()
    if pd.notna(latest_stock_date):
        st.caption(f"Stock prices shown through {latest_stock_date.date()}.")

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
        xaxis=dict(gridcolor=GRID, range=shared_xrange),
        hovermode="x unified",
    )
    st.caption("Each line is rebased to 100 at the start of its available history for comparability.")
    st.plotly_chart(fig2, width="stretch", theme=None)


def render(domain_states, datasets) -> None:
    render_minerals_section()
