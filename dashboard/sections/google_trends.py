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


SIGNAL_QUALITY_COLOR = {"High": GREEN, "Medium": YELLOW, "Low": RED}


SIGNAL_QUALITY_EMOJI = {"High": "🟢", "Medium": "🟡", "Low": "🔴"}


def _load_watchlist() -> list[dict]:
    import json
    candidate_paths = [
        BASE_DIR / "src" / "google_trends_data" / "watchlist.json",
        Path(__file__).resolve().parent.parent / "src" / "google_trends_data" / "watchlist.json",
    ]

    try:
        import google_trends_data

        candidate_paths.append(Path(google_trends_data.__file__).resolve().with_name("watchlist.json"))
    except Exception:
        pass

    for wl_path in candidate_paths:
        if wl_path.exists():
            with open(wl_path, encoding="utf-8") as f:
                return json.load(f)
    return []


def _load_combined(ticker: str, keyword: str, geo: str) -> pd.DataFrame:
    slug_kw = keyword.lower().replace(" ", "_").replace(".", "_").replace("/", "_")
    slug_tk = ticker.lower().replace(" ", "_").replace(".", "_").replace("/", "_")
    geo_tag = geo if geo else "worldwide"
    path = BASE_DIR / "data" / "processed" / "google_trends" / f"{slug_kw}_{geo_tag}_{slug_tk}_combined.parquet"
    if path.exists():
        df = pd.read_parquet(path)
        df["week_start"] = pd.to_datetime(df["week_start"])
        return df
    return pd.DataFrame()


def _correlation_table(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(subset=["trend_value", "stock_adj_close"]).copy()
    df["ret_0w"] = df["stock_weekly_return"]
    df["ret_+1w"] = df["ret_0w"].shift(-1)
    df["ret_+2w"] = df["ret_0w"].shift(-2)
    df["ret_-1w"] = df["ret_0w"].shift(1)
    rows = []
    for lag, col in [("Prior week", "ret_-1w"), ("Same week", "ret_0w"),
                     ("Next week", "ret_+1w"), ("2w ahead", "ret_+2w")]:
        sub = df[["trend_value", col]].dropna()
        if len(sub) > 5:
            r = sub["trend_value"].corr(sub[col])
            rows.append({"Lag": lag, "Pearson r": round(r, 4), "N": len(sub)})
    return pd.DataFrame(rows)


def render_google_trends_section() -> None:
    st.markdown("## 📈 Google Trends Signal")
    st.caption(
        "Weekly Google Search interest matched to stock weekly returns. "
        "Automated watchlist refreshes use Google Trends CSV export/import on a self-hosted runner; "
        "single-keyword local experiments can still use trendspyg plus yfinance."
    )

    watchlist = _load_watchlist()
    if not watchlist:
        st.warning("Google Trends watchlist is not available in this deployment.")
        st.caption("Expected `src/google_trends_data/watchlist.json` or packaged `google_trends_data/watchlist.json`.")
        return

    tab_explorer, tab_watchlist, tab_leaderboard = st.tabs(["📊 Signal Explorer", "📋 Watchlist", "🏆 Signal Leaderboard"])

    # ── Tab 1: Signal Explorer ────────────────────────────────────────────────
    with tab_explorer:
        # Sidebar-style controls in a horizontal row
        ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns([2, 2, 1, 1])

        enabled = [w for w in watchlist if w["enabled"]]
        show_all = st.toggle("Show stocks without data", value=False)
        pool = watchlist if show_all else (enabled if enabled else watchlist)

        ticker_options = [
            f"{SIGNAL_QUALITY_EMOJI.get(w['signal_quality'], '')} {w['ticker']} — {w['name']}"
            + ("" if w["enabled"] else " ⏳")
            for w in pool
        ]
        with ctrl_col1:
            selected_label = st.selectbox("Stock", ticker_options, index=0)
        selected_stock = pool[ticker_options.index(selected_label)]

        kw_options = [
            f"{k['term']} ({k['geo'] if k['geo'] else 'Worldwide'})"
            for k in selected_stock["keywords"]
        ]
        with ctrl_col2:
            selected_kw_label = st.selectbox("Keyword / Region", kw_options, index=0)
        kw_idx = kw_options.index(selected_kw_label)
        selected_kw = selected_stock["keywords"][kw_idx]

        df = _load_combined(
            ticker=selected_stock["ticker"],
            keyword=selected_kw["term"],
            geo=selected_kw["geo"],
        )

        if df.empty:
            st.warning(
                f"No data found for **{selected_kw['term']}** / **{selected_stock['ticker']}** "
                f"(geo: {selected_kw['geo'] or 'Worldwide'}). "
                "Run the pipeline first: `python -m google_trends_data.cli --keyword '...' --ticker '...'`"
            )
            return

        df_valid = df.dropna(subset=["stock_close"])
        with ctrl_col3:
            st.metric("Weeks of data", len(df_valid))
        with ctrl_col4:
            latest = df_valid["week_start"].max()
            st.metric("Latest week", pd.Timestamp(latest).strftime("%Y-%m-%d"))

        st.divider()

        # ── Trend vs Price chart ──────────────────────────────────────────────
        st.markdown("### Trends vs Price")
        fig = go.Figure()

        # Google Trends (primary y)
        fig.add_trace(go.Scatter(
            x=df_valid["week_start"],
            y=df_valid["trend_value"],
            name=f"Google Trends: {selected_kw['term']}",
            line=dict(color="#4285F4", width=2),
            fill="tozeroy",
            fillcolor="rgba(66,133,244,0.10)",
            yaxis="y1",
            hovertemplate="%{x|%Y-%m-%d}<br>Interest: %{y}<extra></extra>",
        ))

        # Stock price (secondary y)
        fig.add_trace(go.Scatter(
            x=df_valid["week_start"],
            y=df_valid["stock_adj_close"],
            name=f"{selected_stock['ticker']} Adj Close",
            line=dict(color="#FF6B6B", width=2),
            yaxis="y2",
            hovertemplate="%{x|%Y-%m-%d}<br>Price: %{y:.2f}<extra></extra>",
        ))

        fig.update_layout(
            template="plotly_white",
            height=420,
            margin=dict(l=0, r=0, t=40, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            yaxis=dict(
                title=dict(text="Google Trends (0–100)", font=dict(color="#4285F4")),
                tickfont=dict(color="#4285F4"),
                range=[0, 105],
                gridcolor=GRID,
            ),
            yaxis2=dict(
                title=dict(text=f"{selected_stock['ticker']} Price", font=dict(color="#FF6B6B")),
                tickfont=dict(color="#FF6B6B"),
                overlaying="y",
                side="right",
                gridcolor="rgba(0,0,0,0)",
            ),
            xaxis=dict(gridcolor=GRID),
            hovermode="x unified",
        )
        st.plotly_chart(fig, use_container_width=True, theme=None)

        # ── Trend delta (momentum) chart ──────────────────────────────────────
        st.markdown("### Trends Momentum (Week-over-Week Δ)")
        df_valid = df_valid.copy()
        df_valid["trend_delta"] = df_valid["trend_value"].diff()
        df_valid["delta_color"] = df_valid["trend_delta"].apply(
            lambda x: "rgba(22,163,74,0.7)" if (pd.notna(x) and x >= 0) else "rgba(220,38,38,0.7)"
        )

        fig_delta = go.Figure()
        fig_delta.add_trace(go.Bar(
            x=df_valid["week_start"],
            y=df_valid["trend_delta"],
            marker_color=df_valid["delta_color"],
            name="Trend Δ",
            hovertemplate="%{x|%Y-%m-%d}<br>Δ: %{y:+.0f}<extra></extra>",
        ))

        # Overlay stock weekly return on secondary axis
        fig_delta.add_trace(go.Scatter(
            x=df_valid["week_start"],
            y=(df_valid["stock_weekly_return"] * 100),
            name=f"{selected_stock['ticker']} Weekly Return %",
            line=dict(color="#FF6B6B", width=1.5, dash="dot"),
            yaxis="y2",
            hovertemplate="%{x|%Y-%m-%d}<br>Ret: %{y:+.2f}%<extra></extra>",
        ))

        fig_delta.update_layout(
            template="plotly_white",
            height=300,
            margin=dict(l=0, r=0, t=30, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            yaxis=dict(title="Trend WoW Δ", gridcolor=GRID),
            yaxis2=dict(
                title=dict(text="Stock Return %", font=dict(color="#FF6B6B")),
                overlaying="y",
                side="right",
                tickformat="+.1f",
                gridcolor="rgba(0,0,0,0)",
                tickfont=dict(color="#FF6B6B"),
            ),
            xaxis=dict(gridcolor=GRID),
            hovermode="x unified",
            barmode="relative",
        )
        st.plotly_chart(fig_delta, use_container_width=True, theme=None)

        # ── Trend YoY (Deseasonalized) chart ──────────────────────────────────
        st.markdown("### Trends Seasonality (Year-over-Year 52-Week Δ)")
        df_valid = df_valid.copy()
        df_valid["trend_yoy"] = df_valid["trend_value"].diff(52)
        df_valid["yoy_color"] = df_valid["trend_yoy"].apply(
            lambda x: "rgba(22,163,74,0.7)" if (pd.notna(x) and x >= 0) else "rgba(220,38,38,0.7)"
        )

        fig_yoy = go.Figure()
        fig_yoy.add_trace(go.Bar(
            x=df_valid["week_start"],
            y=df_valid["trend_yoy"],
            marker_color=df_valid["yoy_color"],
            name="Trend YoY Δ",
            hovertemplate="%{x|%Y-%m-%d}<br>YoY Δ: %{y:+.0f}<extra></extra>",
        ))

        # Overlay stock weekly return on secondary axis
        fig_yoy.add_trace(go.Scatter(
            x=df_valid["week_start"],
            y=(df_valid["stock_weekly_return"] * 100),
            name=f"{selected_stock['ticker']} Weekly Return %",
            line=dict(color="#FF6B6B", width=1.5, dash="dot"),
            yaxis="y2",
            hovertemplate="%{x|%Y-%m-%d}<br>Ret: %{y:+.2f}%<extra></extra>",
        ))

        fig_yoy.update_layout(
            template="plotly_white",
            height=300,
            margin=dict(l=0, r=0, t=30, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            yaxis=dict(title="Trend YoY Δ (52w)", gridcolor=GRID),
            yaxis2=dict(
                title=dict(text="Stock Return %", font=dict(color="#FF6B6B")),
                overlaying="y",
                side="right",
                tickformat="+.1f",
                gridcolor="rgba(0,0,0,0)",
                tickfont=dict(color="#FF6B6B"),
            ),
            xaxis=dict(gridcolor=GRID),
            hovermode="x unified",
            barmode="relative",
        )
        st.plotly_chart(fig_yoy, use_container_width=True, theme=None)

        # ── Correlation panel ─────────────────────────────────────────────────
        st.markdown("### Correlation Analysis")
        corr_col1, corr_col2, corr_col3 = st.columns(3)

        with corr_col1:
            st.markdown("**Level: Trend value vs returns**")
            corr_df = _correlation_table(df_valid)
            if not corr_df.empty:
                max_abs = corr_df["Pearson r"].abs().max()
                styled = corr_df.style.background_gradient(
                    subset=["Pearson r"], cmap="RdYlGn", vmin=-max_abs, vmax=max_abs
                ).format({"Pearson r": "{:+.4f}"})
                st.dataframe(styled, use_container_width=True, hide_index=True)

        with corr_col2:
            st.markdown("**Momentum: Trend WoW Δ vs returns**")
            df_delta_corr = df_valid.dropna(subset=["trend_delta", "stock_adj_close"]).copy()
            df_delta_corr["trend_value"] = df_delta_corr["trend_delta"]  # reuse helper
            corr_delta_df = _correlation_table(df_delta_corr)
            if not corr_delta_df.empty:
                max_abs2 = corr_delta_df["Pearson r"].abs().max()
                styled2 = corr_delta_df.style.background_gradient(
                    subset=["Pearson r"], cmap="RdYlGn", vmin=-max_abs2, vmax=max_abs2
                ).format({"Pearson r": "{:+.4f}"})
                st.dataframe(styled2, use_container_width=True, hide_index=True)

        with corr_col3:
            st.markdown("**Seasonality: Trend YoY Δ (52w) vs returns**")
            df_yoy_corr = df_valid.dropna(subset=["trend_yoy", "stock_adj_close"]).copy()
            df_yoy_corr["trend_value"] = df_yoy_corr["trend_yoy"]  # reuse helper
            corr_yoy_df = _correlation_table(df_yoy_corr)
            if not corr_yoy_df.empty:
                max_abs3 = corr_yoy_df["Pearson r"].abs().max()
                styled3 = corr_yoy_df.style.background_gradient(
                    subset=["Pearson r"], cmap="RdYlGn", vmin=-max_abs3, vmax=max_abs3
                ).format({"Pearson r": "{:+.4f}"})
                st.dataframe(styled3, use_container_width=True, hide_index=True)

        st.caption(
            f"Pearson r between Google Trends ('{selected_kw['term']}') and "
            f"{selected_stock['ticker']} weekly returns at different lags. "
            "Positive r = higher search interest associated with higher returns."
        )

    # ── Tab 2: Watchlist ──────────────────────────────────────────────────────
    with tab_watchlist:
        st.markdown("### 📋 Google Trends Signal Watchlist")
        st.caption(
            "Stocks where Google search interest has documented or hypothesised signal quality. "
            "'Enabled' = data has been fetched and is available in the Signal Explorer."
        )

        # Build display dataframe
        rows = []
        for w in watchlist:
            keywords_str = ", ".join(
                f"{k['term']} ({k['geo'] if k['geo'] else 'WW'})" for k in w["keywords"]
            )
            rows.append({
                "Signal": SIGNAL_QUALITY_EMOJI.get(w["signal_quality"], "⚪"),
                "Ticker": w["ticker"],
                "Company": w["name"],
                "Sector": w["sector"],
                "Subsector": w["subsector"],
                "Quality": w["signal_quality"],
                "Keywords": keywords_str,
                "Notes": w["signal_notes"],
                "Data Ready": "✅" if w["enabled"] else "⏳",
            })

        wl_df = pd.DataFrame(rows)

        # Color Quality column
        def color_quality(val: str) -> str:
            c = SIGNAL_QUALITY_COLOR.get(val, MUTED)
            return f"color: {c}; font-weight: 600"

        styled_wl = _styler_applymap_compat(wl_df.style, color_quality, subset=["Quality"])
        st.dataframe(styled_wl, use_container_width=True, hide_index=True,
                     column_config={
                         "Notes": st.column_config.TextColumn(width="large"),
                         "Keywords": st.column_config.TextColumn(width="medium"),
                     })

        st.divider()
        st.markdown("#### ⚠️ Coverage Notes")
        st.info(
            "**Mainland China (CN):** Google Trends has no meaningful data — Google is blocked. "
            "Recommend integrating **Baidu Index** (`index.baidu.com`) for A-share names (BYD, Moutai, Xiaomi). "
            "This is a planned next step for this project."
        )
        st.info(
            "**Chinese-language keywords:** For HK/TW-listed names with significant Chinese-speaking audiences, "
            "the Chinese name (e.g. `泡泡玛特`) is tracked separately. Worldwide correlation is weaker (~0.03–0.07) "
            "compared to English name in same geos (~0.10–0.18), confirming that international investors drive most of the signal."
        )

    # ── Tab 3: Leaderboard ────────────────────────────────────────────────────
    with tab_leaderboard:
        st.markdown("### 🏆 Google Trends Signal Leaderboard")
        st.caption(
            "Comparison of correlation strength across all enabled assets and keywords. "
            "Seasonality-adjusted (YoY) correlation is included to filter out holiday and calendar spikes."
        )

        leaderboard_rows = []
        for w in watchlist:
            if not w["enabled"]:
                continue
            for k in w["keywords"]:
                term = k["term"]
                geo = k["geo"]
                df = _load_combined(ticker=w["ticker"], keyword=term, geo=geo)
                if df.empty:
                    continue
                
                # Raw correlation
                corr_df = _correlation_table(df)
                if corr_df.empty:
                    continue
                
                r_map = {}
                for _, r_row in corr_df.iterrows():
                    r_map[r_row["Lag"]] = r_row["Pearson r"]

                # YoY correlation
                df_yoy = df.copy()
                df_yoy["trend_yoy"] = df_yoy["trend_value"].diff(52)
                df_yoy_corr = df_yoy.dropna(subset=["trend_yoy", "stock_weekly_return"]).copy()
                df_yoy_corr["trend_value"] = df_yoy_corr["trend_yoy"]
                corr_yoy_df = _correlation_table(df_yoy_corr)
                
                r_yoy_map = {}
                if not corr_yoy_df.empty:
                    for _, r_yoy_row in corr_yoy_df.iterrows():
                        r_yoy_map[r_yoy_row["Lag"]] = r_yoy_row["Pearson r"]
                
                # Determine max absolute r
                all_rs = list(r_map.values()) + list(r_yoy_map.values())
                max_abs_r = max([abs(val) for val in all_rs if pd.notna(val)], default=0.0)

                leaderboard_rows.append({
                    "Ticker": w["ticker"],
                    "Company": w["name"],
                    "Sector": w["sector"],
                    "Keyword": term,
                    "Region": geo if geo else "WW",
                    "Same Week r": r_map.get("Same week", 0.0),
                    "Next Week r": r_map.get("Next week", 0.0),
                    "YoY Same Week r": r_yoy_map.get("Same week", 0.0),
                    "YoY Next Week r": r_yoy_map.get("Next week", 0.0),
                    "Max |r|": max_abs_r,
                    "Quality": w["signal_quality"],
                })

        if not leaderboard_rows:
            st.info("No data available yet. Please enable and fetch data for watchlist items.")
        else:
            lead_df = pd.DataFrame(leaderboard_rows)
            lead_df = lead_df.sort_values(by="Max |r|", ascending=False).reset_index(drop=True)
            
            # Sector filter
            sectors = ["All"] + sorted(list(lead_df["Sector"].unique()))
            lead_col1, lead_col2 = st.columns([1, 3])
            with lead_col1:
                selected_sector = st.selectbox("Filter by Sector", sectors, index=0)
            if selected_sector != "All":
                lead_df = lead_df[lead_df["Sector"] == selected_sector]
            
            r_cols = ["Same Week r", "Next Week r", "YoY Same Week r", "YoY Next Week r"]
            
            def color_r(val):
                if pd.isna(val):
                    return ""
                norm = max(-1.0, min(1.0, val / 0.25))
                if norm >= 0:
                    return f"background-color: rgba(22, 163, 74, {0.05 + 0.3*norm:.2f})"
                else:
                    norm = abs(norm)
                    return f"background-color: rgba(220, 38, 38, {0.05 + 0.3*norm:.2f})"

            styled_lead = _styler_applymap_compat(lead_df.style, color_r, subset=r_cols).format({
                "Same Week r": "{:+.4f}",
                "Next Week r": "{:+.4f}",
                "YoY Same Week r": "{:+.4f}",
                "YoY Next Week r": "{:+.4f}",
                "Max |r|": "{:.4f}",
            })
            
            st.dataframe(styled_lead, use_container_width=True, hide_index=True,
                         column_config={
                             "Max |r|": st.column_config.NumberColumn(help="Strongest absolute correlation across raw and YoY metrics"),
                         })


def render(domain_states, datasets) -> None:
    render_google_trends_section()
