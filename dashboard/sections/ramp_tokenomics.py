"""Ramp TSM token usage, spend and observed effective prices.

Model keys stay verbatim. Missing observations are gaps, and shares are
calculated against the full reported sample before any chart selection.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from dashboard.components import dataframe_for_display, make_line_chart
from dashboard.data import DatasetLoadResult

ACTIVITY_ID = "ramp_ai_token_activity"
PRICES_ID = "ramp_ai_token_prices"
SOURCE_URL = "https://ramp.com/data/ai-index?metric=token-spend&detail=maker&mode=volume"
COLORS = ["#2563EB", "#F97316", "#0D9488", "#8B5CF6", "#DB2777", "#65A30D", "#D97706", "#0891B2"]
MAKERS = {"openai": "OpenAI", "anthropic": "Anthropic", "xai": "xAI",
          "nvidia": "NVIDIA", "google": "Google", "meta": "Meta"}
TOKEN_TYPES = {"All tokens": "all_tokens", "Uncached input": "uncached_input", "Output": "output"}


def activity_pivot(frame: pd.DataFrame, metric: str, breakdown: str) -> pd.DataFrame:
    frame = frame.loc[frame["metric_key"].eq(metric)].copy()
    if frame.empty:
        return pd.DataFrame()
    frame["period_end"] = pd.to_datetime(frame["period_end"], utc=True).dt.tz_localize(None)
    frame["metric_value"] = pd.to_numeric(frame["metric_value"], errors="coerce")
    if breakdown == "By model maker":
        frame["series"] = frame["model_maker"].map(lambda value: MAKERS.get(value, value))
    else:
        # Labels can be shared by several aliases; never merge them by label.
        frame["series"] = frame["model_maker"].astype(str) + " · " + frame["series_key"].astype(str)
    grouped = frame.groupby(["period_end", "series"])["metric_value"].sum(min_count=1)
    return grouped.unstack("series").sort_index()


def price_pivot(frame: pd.DataFrame, token_type: str) -> pd.DataFrame:
    frame = frame.loc[frame["token_type"].eq(token_type)].copy()
    if frame.empty:
        return pd.DataFrame()
    frame["usage_date"] = pd.to_datetime(frame["usage_date"], utc=True).dt.tz_localize(None)
    columns = ["token_cost_usd_7d", "token_count_7d"]
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    # Sum numerator and denominator, rather than taking an average of ratios.
    grouped = frame.groupby(["usage_date", "model_maker"])[columns].sum(min_count=1)
    denominator = grouped["token_count_7d"].where(grouped["token_count_7d"].gt(0))
    prices = (grouped["token_cost_usd_7d"] / denominator * 1_000_000).unstack("model_maker")
    return prices.rename(columns=lambda value: MAKERS.get(value, value)).sort_index()


def _source_frame(datasets: dict[str, DatasetLoadResult], dataset_id: str) -> pd.DataFrame:
    result = datasets.get(dataset_id)
    return result.frame.copy() if result is not None else pd.DataFrame()


def render_tokenomics(datasets: dict[str, DatasetLoadResult]) -> None:
    st.caption(
        "Ramp Token Spend Management (TSM): connected-provider usage and billing from participating "
        "businesses. This sample differs from Ramp's monthly adoption index and does not represent "
        "total Ramp AI spend, provider revenue or ARR."
    )
    metric_label = st.radio("Tokenomics metric", ["Token volume", "Token spend", "Token prices"],
                            horizontal=True, key="ramp_tokenomics_metric")
    is_price = metric_label == "Token prices"
    dataset_id = PRICES_ID if is_price else ACTIVITY_ID
    frame = _source_frame(datasets, dataset_id)
    if frame.empty:
        st.info("Tokenomics data is not available yet.")
        return

    if is_price:
        token_label = st.selectbox("Token type", list(TOKEN_TYPES), key="ramp_tokenomics_type")
        pivot = price_pivot(frame, TOKEN_TYPES[token_label])
        source_rows = frame.loc[frame["token_type"].eq(TOKEN_TYPES[token_label])]
        unit, scale = "Effective USD / million tokens", 1
        coverage = ", ".join(MAKERS.get(value, value) for value in sorted(source_rows["model_maker"].dropna().unique()))
        st.caption(
            f"Daily anchors of rolling seven-day cost ÷ tokens × 1 million. Source coverage: {coverage}. "
            "No model-level prices. These are observed effective prices, not list prices. "
            "All-token averages also change with the mix of input, output and cached tokens."
        )
    else:
        breakdown = st.selectbox("Breakdown", ["By model maker", "By model"], key="ramp_tokenomics_breakdown")
        metric = "token_volume" if metric_label == "Token volume" else "token_spend"
        pivot = activity_pivot(frame, metric, breakdown)
        source_rows = frame.loc[frame["metric_key"].eq(metric)]
        display = st.radio("Display", ["Level", "Share of reported sample"], horizontal=True,
                           key="ramp_tokenomics_display")
        if display == "Share of reported sample":
            total = pivot.sum(axis=1, min_count=1)
            pivot = pivot.div(total.where(total.gt(0)), axis=0) * 100
            unit, scale = "Share of reported sample (%)", 1
        else:
            unit, scale = ("Tokens (billions)", 1e9) if metric == "token_volume" else ("Spend (USD millions)", 1e6)
        st.caption(
            "Monday–Sunday totals. Model series retain Ramp's raw identifiers, including aliases; "
            "they are not a count of distinct models. Spend and volume have different coverage, "
            "so weekly spend ÷ volume is not used to estimate prices."
        )
    if pivot.empty:
        st.info("No observations for this selection.")
        return

    latest = pivot.index.max()
    captured = pd.to_datetime(frame["scraped_at"], utc=True, errors="coerce").max()
    capture_label = captured.strftime("%Y-%m-%d %H:%M UTC") if pd.notna(captured) else "unknown"
    st.caption(f"Observation through {latest:%Y-%m-%d} · Latest changed-row capture {capture_label} · Checks Monday / Thursday")
    if (pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - latest).days > 21:
        st.warning("The newest observation is over 21 days old. A recent fetch does not make the underlying data current.")

    ranked = pivot.iloc[-1].dropna().sort_values(ascending=False)
    defaults = ranked.loc[ranked.gt(0)].head(8).index.tolist()
    options = list(ranked.index) + sorted(set(pivot.columns) - set(ranked.index))
    selected = st.multiselect("Chart series", options, default=defaults, key=f"ramp_tokenomics_series_{metric_label}_{'price' if is_price else breakdown}")
    history = st.selectbox("History", ["6 months", "3 months", "All available"], key="ramp_tokenomics_history")
    chart = pivot.loc[:, selected] / scale
    if history != "All available":
        chart = chart.loc[chart.index >= latest - pd.DateOffset(months=6 if history == "6 months" else 3)]
    if selected:
        fig = make_line_chart(chart, colors=COLORS, y_title=unit,
                              x_title="7-day window ending" if is_price else "Week ending (Sunday)",
                              value_format=",.3f", mode="lines", connect_gaps=False, height=430)
        st.plotly_chart(fig, width="stretch", theme=None)
    else:
        st.info("Select a series to plot.")
    st.caption("Missing observations remain gaps; reported zeros remain zero. Shares use every reported series, including those hidden from the chart.")

    st.markdown(f"**Latest observation · {latest:%Y-%m-%d}**")
    latest_table = (pivot.iloc[-1].rename(unit).div(scale).rename_axis("Series")
                    .sort_values(ascending=False, na_position="last").reset_index())
    st.dataframe(dataframe_for_display(latest_table), width="stretch", hide_index=True, height=300)
    with st.expander("Source data and revisions"):
        st.markdown(f"[Ramp source and methodology]({SOURCE_URL})")
        st.dataframe(dataframe_for_display(source_rows.drop(columns=["dataset_id"], errors="ignore")),
                     width="stretch", hide_index=True, height=280)
        st.download_button("Download source observations (CSV)", source_rows.to_csv(index=False),
                           file_name=f"{dataset_id}.csv", mime="text/csv", key="ramp_tokenomics_download")
        vintages = _source_frame(datasets, f"{dataset_id}_vintages")
        first_capture = pd.to_datetime(vintages.get("vintage_scraped_at", pd.Series(dtype="object")),
                                       utc=True, errors="coerce").min()
        first_label = first_capture.strftime("%Y-%m-%d") if pd.notna(first_capture) else "unknown"
        st.caption(
            f"{len(vintages):,} captured observation versions. First capture: {first_label}; "
            "historical source dates are not historical availability dates. "
            "Unchanged values retain their original capture time."
        )
