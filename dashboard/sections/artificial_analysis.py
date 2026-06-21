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
from dashboard.components import (format_metric, _empty_dataset_frame, _styler_applymap_compat, WEEKLY_MONTHLY_OTHER_PROVIDERS, DAILY_OTHER_PROVIDERS, US_PROVIDER_ORDER, CHINA_PROVIDER_ORDER, order_provider_columns, regroup_provider_pivot_for_display, render_dataset_guard, format_scraped_at_display, dataframe_for_display, make_stacked_bar, make_stacked_area_chart, make_line_chart, make_yoy_growth_chart, kpi_card_html, kpi_grid_html, _top_n_with_others)


def _quarter_sort_value(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d{4})-q([1-4])", str(value).lower())
    if not match:
        return (9999, 9)
    return (int(match.group(1)), int(match.group(2)))


def _frontier_pivot(
    frame: pd.DataFrame,
    *,
    group_column: str,
    max_groups: int | None = None,
) -> pd.DataFrame:
    required = {"release_date", "intelligence_index", group_column}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()
    work = frame.dropna(subset=["release_date", "intelligence_index", group_column]).copy()
    if work.empty:
        return pd.DataFrame()
    work["release_date"] = pd.to_datetime(work["release_date"], errors="coerce")
    work = work.dropna(subset=["release_date"])
    if work.empty:
        return pd.DataFrame()
    if max_groups is not None:
        top_groups = (
            work.groupby(group_column)["intelligence_index"]
            .max()
            .sort_values(ascending=False)
            .head(max_groups)
            .index
        )
        work = work[work[group_column].isin(top_groups)]
    pivot = (
        work.pivot_table(index="release_date", columns=group_column, values="intelligence_index", aggfunc="max")
        .sort_index()
        .cummax()
        .ffill()
    )
    return pivot


ARTIFICIAL_ANALYSIS_PROVIDER_COUNTRIES = {
    "ai2": "United States",
    "anthropic": "United States",
    "arcee": "United States",
    "aws": "United States",
    "azure": "United States",
    "databricks": "United States",
    "google": "United States",
    "ibm": "United States",
    "liquidai": "United States",
    "meta": "United States",
    "nvidia": "United States",
    "openai": "United States",
    "perplexity": "United States",
    "reka-ai": "United States",
    "servicenow": "United States",
    "snowflake": "United States",
    "xai": "United States",
    "alibaba": "China",
    "baidu": "China",
    "bytedance_seed": "China",
    "china-mobile": "China",
    "deepseek": "China",
    "inclusionai": "China",
    "kimi": "China",
    "kwaikat": "China",
    "longcat": "China",
    "minimax": "China",
    "nanbeige": "China",
    "stepfun": "China",
    "xiaomi": "China",
    "zai": "China",
}


def _artificial_analysis_country_label(row: pd.Series) -> str | None:
    raw_country = row.get("creator_country")
    if pd.notna(raw_country):
        normalized = str(raw_country).strip().lower()
        if normalized in {"us", "usa", "united states", "united states of america"}:
            return "United States"
        if normalized in {"cn", "china", "prc", "people's republic of china"}:
            return "China"

    raw_slug = row.get("creator_slug")
    if pd.isna(raw_slug):
        return None
    return ARTIFICIAL_ANALYSIS_PROVIDER_COUNTRIES.get(str(raw_slug).strip().lower())


def _china_catchup_lag(frontier_by_country: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "us_breakthrough_date",
        "us_intelligence_index",
        "china_catchup_date",
        "lag_months",
        "status",
    ]
    if frontier_by_country.empty or not {"United States", "China"}.issubset(frontier_by_country.columns):
        return pd.DataFrame(columns=columns)

    work = frontier_by_country[["United States", "China"]].copy().sort_index()
    work.index = pd.to_datetime(work.index, errors="coerce")
    work = work[work.index.notna()]
    if work.empty:
        return pd.DataFrame(columns=columns)

    latest_date = work.index.max()
    previous_us_frontier = float("-inf")
    rows: list[dict[str, object]] = []
    for breakthrough_date, values in work.iterrows():
        us_score = values.get("United States")
        if pd.isna(us_score) or float(us_score) <= previous_us_frontier:
            continue
        previous_us_frontier = float(us_score)
        future_china = work.loc[work.index > breakthrough_date]
        caught = future_china[future_china["China"] >= previous_us_frontier]
        if caught.empty:
            catchup_date = pd.NaT
            horizon_date = latest_date
            status = "not_yet_caught"
        else:
            catchup_date = caught.index[0]
            horizon_date = catchup_date
            status = "caught_up"
        lag_months = (horizon_date - breakthrough_date).days / 30.4375
        rows.append(
            {
                "us_breakthrough_date": breakthrough_date.date().isoformat(),
                "us_intelligence_index": previous_us_frontier,
                "china_catchup_date": None if pd.isna(catchup_date) else catchup_date.date().isoformat(),
                "lag_months": float(lag_months),
                "status": status,
            }
        )

    return pd.DataFrame(rows, columns=columns)


def _frontier_points_with_metadata(
    frame: pd.DataFrame,
    frontier_pivot: pd.DataFrame,
    *,
    group_column: str,
) -> pd.DataFrame:
    columns = ["release_date", "country_label", "intelligence_index", "model_name", "creator_name"]
    required = {"release_date", "intelligence_index", group_column, "model_name", "creator_name"}
    if frame.empty or frontier_pivot.empty or not required.issubset(frame.columns):
        return pd.DataFrame(columns=columns)

    source = frame.dropna(subset=["release_date", "intelligence_index", group_column]).copy()
    source["release_date"] = pd.to_datetime(source["release_date"], errors="coerce")
    source = source.dropna(subset=["release_date"])
    if source.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for group_name in frontier_pivot.columns:
        group_rows = source[source[group_column] == group_name].copy()
        if group_rows.empty:
            continue
        group_rows = group_rows.sort_values(["release_date", "intelligence_index"], ascending=[True, False])
        group_rows = group_rows.drop_duplicates(subset=["release_date"], keep="first")
        for release_date, intelligence_index in frontier_pivot[group_name].dropna().items():
            candidates = group_rows[
                (group_rows["release_date"] <= release_date)
                & (group_rows["intelligence_index"] == intelligence_index)
            ].sort_values("release_date")
            if candidates.empty:
                continue
            active = candidates.iloc[-1]
            rows.append(
                {
                    "release_date": pd.Timestamp(release_date),
                    "country_label": group_name,
                    "intelligence_index": float(intelligence_index),
                    "model_name": active.get("model_name"),
                    "creator_name": active.get("creator_name"),
                }
            )

    return pd.DataFrame(rows, columns=columns)


@st.cache_data(ttl=3600)
def compute_artificial_analysis_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    views: dict[str, object] = {}
    models_result = datasets.get("artificial_analysis_models_daily")
    capex_result = datasets.get("artificial_analysis_capex_quarterly")

    models = models_result.frame.copy() if models_result and not models_result.frame.empty else pd.DataFrame()
    capex = capex_result.frame.copy() if capex_result and not capex_result.frame.empty else pd.DataFrame()
    if not models.empty and "as_of_date" in models.columns:
        latest_as_of = models["as_of_date"].dropna().astype(str).max()
        models_latest = models[models["as_of_date"].astype(str) == latest_as_of].copy()
    else:
        latest_as_of = None
        models_latest = pd.DataFrame()

    if not capex.empty:
        capex = capex.sort_values("quarter_id", key=lambda series: series.map(_quarter_sort_value))
        company_cols = ["microsoft", "google", "meta", "amazon", "oracle", "apple"]
        capex_pivot = (
            capex[["quarter_label", *company_cols]]
            .set_index("quarter_label")
            .rename(
                columns={
                    "microsoft": "Microsoft",
                    "google": "Google",
                    "meta": "Meta",
                    "amazon": "Amazon",
                    "oracle": "Oracle",
                    "apple": "Apple",
                }
            )
        )
        latest_capex_total = float(capex_pivot.iloc[-1].sum()) if not capex_pivot.empty else np.nan
        
        # Calculate Year-over-Year (YoY) Growth
        capex_yoy_growth = (capex_pivot / capex_pivot.shift(4) - 1) * 100
        capex_yoy_growth = capex_yoy_growth.replace([np.inf, -np.inf], np.nan)
        agg_capex = capex_pivot.sum(axis=1)
        agg_yoy = (agg_capex / agg_capex.shift(4) - 1) * 100
        capex_yoy_growth["Aggregated"] = agg_yoy
        capex_yoy_growth = capex_yoy_growth.iloc[4:]
    else:
        capex_pivot = pd.DataFrame()
        capex_yoy_growth = pd.DataFrame()
        latest_capex_total = np.nan

    frontier_by_lab = _frontier_pivot(models_latest, group_column="creator_name", max_groups=10)

    price_models = pd.DataFrame()
    if not models_latest.empty:
        price_models = models_latest.dropna(subset=["release_date", "price_1m_blended_3_to_1", "intelligence_index"]).copy()
        price_models["release_date"] = pd.to_datetime(price_models["release_date"], errors="coerce")
        price_models = price_models.dropna(subset=["release_date"]).sort_values("release_date")
        price_models = price_models[
            [
                "release_date",
                "model_name",
                "creator_name",
                "intelligence_index",
                "price_1m_blended_3_to_1",
                "median_output_tokens_per_second",
            ]
        ]

    country_models = models_latest.copy()
    if not country_models.empty:
        country_models["country_label"] = country_models.apply(_artificial_analysis_country_label, axis=1)
        country_models = country_models[country_models["country_label"].isin(["United States", "China"])]
    else:
        country_models["country_label"] = pd.Series(dtype="string")
    frontier_by_country = _frontier_pivot(country_models, group_column="country_label")
    frontier_by_country_points = _frontier_points_with_metadata(
        country_models,
        frontier_by_country,
        group_column="country_label",
    )
    china_catchup_lag = _china_catchup_lag(frontier_by_country)

    openness_models = models_latest.copy()
    if not openness_models.empty:
        openness_models["openness_label"] = openness_models.apply(_artificial_analysis_openness_label, axis=1)
        openness_models = openness_models.dropna(subset=["openness_label"])
    else:
        openness_models["openness_label"] = pd.Series(dtype="string")
    open_vs_proprietary = _frontier_pivot(openness_models, group_column="openness_label")

    views["models_latest"] = models_latest
    views["latest_as_of"] = latest_as_of
    views["capex_pivot"] = capex_pivot
    views["capex_yoy_growth"] = capex_yoy_growth
    views["latest_capex_total"] = latest_capex_total
    views["frontier_by_lab_pivot"] = frontier_by_lab
    views["price_models"] = price_models
    views["frontier_by_country_pivot"] = frontier_by_country
    views["frontier_by_country_points"] = frontier_by_country_points
    views["china_catchup_lag"] = china_catchup_lag
    views["open_vs_proprietary_pivot"] = open_vs_proprietary
    return views


def _artificial_analysis_openness_label(row: pd.Series) -> str | None:
    raw_bool = row.get("is_open_weights")
    if isinstance(raw_bool, bool):
        return "Open Weights" if raw_bool else "Proprietary"
    if pd.notna(raw_bool):
        lowered = str(raw_bool).strip().lower()
        if lowered in {"true", "1", "yes"}:
            return "Open Weights"
        if lowered in {"false", "0", "no"}:
            return "Proprietary"
    category = row.get("open_source_categorization")
    if pd.isna(category):
        return None
    return "Open Weights" if "open" in str(category).lower() else "Proprietary"


def render_artificial_analysis_section(datasets: dict[str, DatasetLoadResult], aa_views: dict[str, object]) -> None:
    models_latest = aa_views.get("models_latest", pd.DataFrame())
    capex_pivot = aa_views.get("capex_pivot", pd.DataFrame())
    capex_yoy_growth = aa_views.get("capex_yoy_growth", pd.DataFrame())
    frontier_by_lab = aa_views.get("frontier_by_lab_pivot", pd.DataFrame())
    price_models = aa_views.get("price_models", pd.DataFrame())
    frontier_by_country = aa_views.get("frontier_by_country_pivot", pd.DataFrame())
    frontier_by_country_points = aa_views.get("frontier_by_country_points", pd.DataFrame())
    china_catchup_lag = aa_views.get("china_catchup_lag", pd.DataFrame())
    open_vs_proprietary = aa_views.get("open_vs_proprietary_pivot", pd.DataFrame())

    if models_latest.empty and capex_pivot.empty:
        st.warning("No Artificial Analysis data available.")
        return

    st.markdown('<div class="section-title">Artificial Analysis Trends</div>', unsafe_allow_html=True)
    latest_as_of = aa_views.get("latest_as_of") or "-"
    peak_intelligence = models_latest["intelligence_index"].max() if not models_latest.empty else np.nan
    median_price = price_models["price_1m_blended_3_to_1"].median() if not price_models.empty else np.nan
    latest_capex_total = aa_views.get("latest_capex_total", np.nan)

    st.markdown(
        kpi_grid_html(
            kpi_card_html("Snapshot Date", str(latest_as_of), delta=f"{len(models_latest)} models"),
            kpi_card_html("Peak Intelligence", f"{peak_intelligence:.1f}" if pd.notna(peak_intelligence) else "-", delta="latest API snapshot"),
            kpi_card_html("Median Blended Price", f"${median_price:.2f}" if pd.notna(median_price) else "-", delta="per 1M tokens"),
            kpi_card_html("Latest Capex Quarter", f"${latest_capex_total:,.1f}B" if pd.notna(latest_capex_total) else "-", delta="tracked companies"),
        ),
        unsafe_allow_html=True,
    )

    capex_tab, frontier_tab, price_tab, country_tab, openness_tab = st.tabs(
        ["Capex", "Frontier Intelligence", "Inference Price", "Country", "Open vs Proprietary"]
    )

    with capex_tab:
        st.markdown('<div class="section-subtitle">Capital Expenditure by Major Tech Companies, Over Time</div>', unsafe_allow_html=True)
        if capex_pivot.empty:
            st.info("Capital expenditure data is not available yet.")
        else:
            st.plotly_chart(
                make_stacked_bar(
                    capex_pivot,
                    ["#00A4EF", "#34A853", "#0089F4", "#FF9900", "#F80000", "#6B7280"],
                    y_title="Capital Expenditure (USD billions)",
                    height=430,
                ),
                width="stretch",
                theme=None,
            )

            st.markdown('<div class="section-subtitle" style="margin-top: 2rem;">Year-over-Year (YoY) Capital Expenditure Growth Rate</div>', unsafe_allow_html=True)
            if capex_yoy_growth.empty:
                st.info("YoY growth data is not available.")
            else:
                st.plotly_chart(
                    make_yoy_growth_chart(
                        capex_yoy_growth,
                        ["#00A4EF", "#34A853", "#0089F4", "#FF9900", "#F80000", "#6B7280"],
                        height=430,
                    ),
                    width="stretch",
                    theme=None,
                )

    with frontier_tab:
        st.markdown('<div class="section-subtitle">Frontier Language Model Intelligence, Over Time</div>', unsafe_allow_html=True)
        if frontier_by_lab.empty:
            st.info("Frontier intelligence data is not available yet.")
        else:
            st.plotly_chart(
                make_line_chart(
                    frontier_by_lab,
                    MODEL_COLORS,
                    y_title="Artificial Analysis Intelligence Index",
                    x_title="Release Date",
                    height=430,
                ),
                width="stretch",
                theme=None,
            )

    with price_tab:
        st.markdown('<div class="section-subtitle">Language Model Inference Price</div>', unsafe_allow_html=True)
        if price_models.empty:
            st.info("Inference price data is not available yet.")
        else:
            fig_price = go.Figure()
            for i, (creator, creator_df) in enumerate(price_models.groupby("creator_name", dropna=True)):
                fig_price.add_trace(
                    go.Scatter(
                        x=creator_df["release_date"],
                        y=creator_df["price_1m_blended_3_to_1"],
                        mode="markers",
                        name=str(creator),
                        marker=dict(
                            size=np.clip(creator_df["intelligence_index"].fillna(5) * 0.45, 6, 20),
                            color=MODEL_COLORS[i % len(MODEL_COLORS)],
                            opacity=0.75,
                            line=dict(width=1, color="white"),
                        ),
                        text=creator_df["model_name"],
                        customdata=creator_df[["intelligence_index", "median_output_tokens_per_second"]],
                        hovertemplate=(
                            "<b>%{text}</b><br>%{x|%Y-%m-%d}<br>"
                            "Blended price: $%{y:.3f} / 1M tokens<br>"
                            "Intelligence: %{customdata[0]:.1f}<br>"
                            "Output speed: %{customdata[1]:.1f} tok/s<extra></extra>"
                        ),
                    )
                )
            fig_price.update_layout(
                template="plotly_white",
                xaxis_title="Release Date",
                yaxis_title="Blended Price ($ / 1M tokens)",
                height=430,
                margin=dict(l=0, r=0, t=20, b=80),
                legend=dict(orientation="h", y=-0.22),
            )
            st.plotly_chart(fig_price, width="stretch", theme=None)

    with country_tab:
        st.markdown('<div class="section-subtitle">Frontier Language Model Intelligence: US vs China</div>', unsafe_allow_html=True)
        if frontier_by_country.empty:
            st.info("No US or China provider-country matches are available in the current Artificial Analysis snapshot.")
        else:
            country_colors = {"United States": "#2563EB", "China": "#DC2626"}
            fig_country = go.Figure()
            for country in frontier_by_country.columns:
                country_points = frontier_by_country_points[
                    frontier_by_country_points["country_label"] == country
                ].sort_values("release_date")
                if country_points.empty:
                    fig_country.add_trace(
                        go.Scatter(
                            x=frontier_by_country.index,
                            y=frontier_by_country[country],
                            mode="lines+markers",
                            name=str(country),
                            line=dict(width=3, color=country_colors.get(str(country), MODEL_COLORS[0])),
                        )
                    )
                    continue
                fig_country.add_trace(
                    go.Scatter(
                        x=country_points["release_date"],
                        y=country_points["intelligence_index"],
                        mode="lines+markers",
                        name=str(country),
                        line=dict(width=3, color=country_colors.get(str(country), MODEL_COLORS[0])),
                        customdata=country_points[["model_name", "creator_name"]],
                        hovertemplate=(
                            "<b>%{customdata[0]}</b><br>"
                            "%{customdata[1]} - %{fullData.name}<br>"
                            "%{x|%Y-%m-%d}<br>"
                            "Intelligence: %{y:.1f}<extra></extra>"
                        ),
                    )
                )
            fig_country.update_layout(
                template="plotly_white",
                xaxis_title="Release Date",
                yaxis_title="Artificial Analysis Intelligence Index",
                legend=dict(orientation="h", y=-0.2),
                height=430,
                margin=dict(l=0, r=0, t=40, b=80),
            )
            st.plotly_chart(fig_country, width="stretch", theme=None)
            st.markdown('<div class="section-subtitle">China Catch-Up Lag to US Frontier Breakthroughs</div>', unsafe_allow_html=True)
            if china_catchup_lag.empty:
                st.info("Catch-up lag requires both United States and China frontier series.")
            else:
                lag_plot = china_catchup_lag.copy()
                lag_plot["catchup_label"] = lag_plot["china_catchup_date"].fillna("Not yet caught")
                fig_lag = go.Figure(
                    go.Scatter(
                        x=pd.to_datetime(lag_plot["us_breakthrough_date"], errors="coerce"),
                        y=lag_plot["lag_months"],
                        mode="lines+markers",
                        line=dict(width=3, color="#DC2626", dash="solid"),
                        marker=dict(
                            size=10,
                            color=np.where(lag_plot["status"] == "caught_up", "#DC2626", "#9CA3AF"),
                            symbol=np.where(lag_plot["status"] == "caught_up", "circle", "x"),
                        ),
                        customdata=lag_plot[["us_intelligence_index", "catchup_label", "status"]],
                        hovertemplate=(
                            "<b>US breakthrough %{x}</b><br>"
                            "US intelligence: %{customdata[0]:.1f}<br>"
                            "China catch-up: %{customdata[1]}<br>"
                            "Lag: %{y:.1f} months<br>"
                            "Status: %{customdata[2]}<extra></extra>"
                        ),
                    )
                )
                fig_lag.update_layout(
                    template="plotly_white",
                    xaxis_title="US Breakthrough Date",
                    yaxis_title="Months Until China Catch-Up",
                    height=320,
                    margin=dict(l=0, r=0, t=20, b=80),
                    showlegend=False,
                )
                st.plotly_chart(fig_lag, width="stretch", theme=None)

    with openness_tab:
        st.markdown('<div class="section-subtitle">Progress in Open Weights vs. Proprietary Intelligence</div>', unsafe_allow_html=True)
        if open_vs_proprietary.empty:
            st.info("The current Artificial Analysis API snapshot does not expose open-weight categorization fields.")
        else:
            st.plotly_chart(
                make_line_chart(
                    open_vs_proprietary,
                    ["#071846", "#6467F4"],
                    y_title="Artificial Analysis Intelligence Index",
                    x_title="Release Date",
                    height=430,
                ),
                width="stretch",
                theme=None,
            )


def render(domain_states, datasets) -> None:
    aa_views = compute_artificial_analysis_views(domain_states["artificial_analysis"][0])
    render_artificial_analysis_section(datasets, aa_views)
