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
import yfinance as yf

from dashboard import remote
from dashboard.checks import CheckResult, run_checks
from dashboard.data import (
    LazyDatasetMap,DOMAIN_ORDER, DATASET_REGISTRY, DatasetLoadResult, FreshnessInfo, dataset_source_for_domain, domain_dataset_ids, load_domain_datasets, load_latest_manifest, repo_root)
from openrouter_revenue import (build_price_context, build_conservative_provider_economics, estimate_usage_revenue, summarize_economics_coverage)
from semiconductor_memory_data.sources.config import AI_DEMAND_PPI_WEIGHTS
from dashboard.theme import (ACCENT, BG, SIDEBAR, CARD, BORDER, TEXT, MUTED, GREEN, RED, YELLOW, GRID, TICK, MODEL_COLORS)
from dashboard.components import (format_metric, _empty_dataset_frame, _styler_applymap_compat, WEEKLY_MONTHLY_OTHER_PROVIDERS, DAILY_OTHER_PROVIDERS, US_PROVIDER_ORDER, CHINA_PROVIDER_ORDER, order_provider_columns, regroup_provider_pivot_for_display, render_dataset_guard, format_scraped_at_display, dataframe_for_display, make_stacked_bar, make_stacked_area_chart, make_line_chart, kpi_card_html, kpi_grid_html, _top_n_with_others)


NPM_CATEGORY_LABELS = {
    "core_sdk": "Core SDK",
    "agent_sdk": "Agent SDK",
    "cli": "CLI",
    "legacy_sdk": "Legacy SDK",
}


def prepare_hf_models_table(
    latest_hf_models: pd.DataFrame,
    *,
    provider_display_name: str | None,
    metric_label: str = "Trailing 30d",
    limit: int = 20,
) -> pd.DataFrame:
    if latest_hf_models.empty or not provider_display_name or provider_display_name == "All":
        return pd.DataFrame(columns=["Provider", "Model", "30d Downloads", "All-Time Downloads", "Daily (Est)", "Likes", "Last Modified"])

    table = latest_hf_models[latest_hf_models["provider_display_name"] == provider_display_name].copy()
    if table.empty:
        return pd.DataFrame(columns=["Provider", "Model", "30d Downloads", "All-Time Downloads", "Daily (Est)", "Likes", "Last Modified"])

    if metric_label == "Daily (Est)":
        sort_columns = ["hf_downloads_daily_est", "hf_downloads_all_time"]
    elif metric_label == "All-time":
        sort_columns = ["hf_downloads_all_time", "hf_downloads_30d"]
    else:
        sort_columns = ["hf_downloads_30d", "hf_downloads_all_time"]

    table = table.sort_values(sort_columns, ascending=[False, False], na_position="last").head(limit)

    return table.rename(
        columns={
            "provider_display_name": "Provider",
            "model_id": "Model",
            "hf_downloads_30d": "30d Downloads",
            "hf_downloads_all_time": "All-Time Downloads",
            "hf_downloads_daily_est": "Daily (Est)",
            "hf_likes": "Likes",
            "hf_last_modified": "Last Modified",
        }
    )[
        ["Provider", "Model", "30d Downloads", "All-Time Downloads", "Daily (Est)", "Likes", "Last Modified"]
    ]


def resolve_hf_metric_config(metric_label: str) -> dict[str, str]:
    if metric_label == "All-time":
        return {
            "value_column": "downloads_all_time",
            "downloads_title": "Hugging Face All-Time Downloads",
            "downloads_axis": "Downloads (All-Time)",
            "downloads_hover": "all-time downloads",
            "share_title": "Hugging Face Download Share (All-Time)",
            "models_caption_metric": "all-time downloads",
        }
    if metric_label == "Daily (Est)":
        return {
            "value_column": "downloads_daily_est",
            "downloads_title": "Hugging Face Daily Downloads (Est)",
            "downloads_axis": "Downloads (Daily Est)",
            "downloads_hover": "estimated daily downloads",
            "share_title": "Hugging Face Download Share (Daily Est)",
            "models_caption_metric": "estimated daily downloads",
        }
    return {
        "value_column": "downloads_30d",
        "downloads_title": "Hugging Face Trailing 30d Downloads",
        "downloads_axis": "Downloads (30d)",
        "downloads_hover": "30d downloads",
        "share_title": "Hugging Face Download Share (30d)",
        "models_caption_metric": "trailing 30d downloads",
    }


@st.cache_data(ttl=3600, max_entries=8, hash_funcs={LazyDatasetMap: lambda mapping: mapping.cache_key})
def compute_provider_adoption_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    views: dict[str, object] = {}
    # Mistral and Qwen don't publish meaningful PyPI/npm packages; exclude from those charts.
    _PYPI_NPM_EXCLUDE = {"Mistral", "Qwen"}

    pypi_result = datasets.get("pypi_downloads_daily")
    npm_result = datasets.get("npm_downloads_daily")
    hf_result = datasets.get("huggingface_models_daily")

    pypi = pypi_result.frame.copy() if pypi_result and pypi_result.frame is not None else pd.DataFrame()
    pypi = pypi[pypi["with_mirrors"] == False].copy() if not pypi.empty else pypi
    pypi = pypi[~pypi["provider_display_name"].isin(_PYPI_NPM_EXCLUDE)].copy() if not pypi.empty else pypi
    if not pypi.empty:
        pypi_grouped = pypi.groupby(["download_date", "provider_display_name"], dropna=False)["downloads"].sum().reset_index()
        pypi_grouped["download_date"] = pypi_grouped["download_date"].astype(str)
        latest_pypi_date = pypi_grouped["download_date"].max()
        latest_pypi = pypi_grouped[pypi_grouped["download_date"] == latest_pypi_date].copy()
    else:
        pypi_grouped = pd.DataFrame(columns=["download_date", "provider_display_name", "downloads"])
        latest_pypi_date = None
        latest_pypi = pd.DataFrame(columns=["download_date", "provider_display_name", "downloads"])

    npm = npm_result.frame.copy() if npm_result and npm_result.frame is not None else pd.DataFrame()
    if not npm.empty:
        npm = npm[~npm["provider_display_name"].isin(_PYPI_NPM_EXCLUDE)].copy()
        npm["download_date"] = npm["download_date"].astype(str)
        npm["package_category"] = npm["package_category"].astype(str)
        npm_categories = sorted(category for category in npm["package_category"].dropna().unique().tolist() if category and category != "<NA>")
        npm_grouped_all = (
            npm.groupby(["package_category", "download_date", "provider_display_name"], dropna=False)["downloads"].sum().reset_index()
        )
        latest_npm_date = npm_grouped_all["download_date"].max()
        latest_npm_all = npm_grouped_all[npm_grouped_all["download_date"] == latest_npm_date].copy()
    else:
        npm_grouped_all = pd.DataFrame(columns=["package_category", "download_date", "provider_display_name", "downloads"])
        latest_npm_date = None
        latest_npm_all = pd.DataFrame(columns=["package_category", "download_date", "provider_display_name", "downloads"])
        npm_categories = []

    hf = hf_result.frame.copy() if hf_result and hf_result.frame is not None else pd.DataFrame()
    if not hf.empty:
        hf["download_date"] = hf["download_date"].astype(str)
        hf_grouped = (
            hf.groupby(["download_date", "provider_display_name"], dropna=False)
            .agg(
                downloads_30d=("hf_downloads_30d", "sum"),
                downloads_all_time=("hf_downloads_all_time", "sum"),
                downloads_daily_est=("hf_downloads_daily_est", lambda values: values.sum(min_count=1)),
                likes=("hf_likes", "sum"),
            )
            .reset_index()
        )
        latest_hf_date = hf_grouped["download_date"].max()
        latest_hf = hf_grouped[hf_grouped["download_date"] == latest_hf_date].copy()
        latest_hf_models = hf[hf["download_date"] == latest_hf_date].copy()
    else:
        hf_grouped = pd.DataFrame(columns=["download_date", "provider_display_name", "downloads_30d", "downloads_all_time", "downloads_daily_est", "likes"])
        latest_hf_date = None
        latest_hf = pd.DataFrame(columns=["download_date", "provider_display_name", "downloads_30d", "downloads_all_time", "downloads_daily_est", "likes"])
        latest_hf_models = pd.DataFrame(
            columns=["provider_display_name", "model_id", "hf_downloads_30d", "hf_downloads_all_time", "hf_downloads_daily_est", "hf_likes", "hf_last_modified"]
        )

    all_providers = set()
    if not latest_pypi.empty:
        all_providers.update(latest_pypi["provider_display_name"].dropna().unique())
    if not latest_npm_all.empty:
        all_providers.update(latest_npm_all["provider_display_name"].dropna().unique())
    if not latest_hf.empty:
        all_providers.update(latest_hf["provider_display_name"].dropna().unique())

    provider_order = sorted(list(all_providers))

    views["pypi_grouped"] = pypi_grouped
    views["latest_pypi_date"] = latest_pypi_date
    views["latest_pypi"] = latest_pypi
    views["npm_grouped"] = npm_grouped_all
    views["latest_npm_date"] = latest_npm_date
    views["latest_npm"] = latest_npm_all
    views["npm_categories"] = npm_categories
    views["hf_grouped"] = hf_grouped
    views["latest_hf_date"] = latest_hf_date
    views["latest_hf"] = latest_hf
    views["latest_hf_models"] = latest_hf_models
    views["provider_order"] = provider_order

    github_adoption_result = datasets.get("github_provider_adoption_daily")
    github_adoption = (
        github_adoption_result.frame.copy()
        if github_adoption_result and github_adoption_result.frame is not None
        else pd.DataFrame()
    )

    if not github_adoption.empty and provider_order:
        github_adoption = github_adoption[github_adoption["provider_display_name"].isin(provider_order)].copy()
        github_adoption["signal_date"] = github_adoption["signal_date"].astype(str)

    latest_github_date = github_adoption["signal_date"].max() if not github_adoption.empty else None

    views["github_adoption"] = github_adoption
    views["latest_github_date"] = latest_github_date

    if not github_adoption.empty:
        candidates_daily = (
            github_adoption.groupby(["signal_date"], dropna=False)["github_new_repo_count"]
            .max()
            .reset_index(name="repo_candidates")
            .rename(columns={"signal_date": "repo_created_date"})
        )
    else:
        candidates_daily = pd.DataFrame(columns=["repo_created_date", "repo_candidates"])
    latest_github_candidate_count = (
        int(candidates_daily[candidates_daily["repo_created_date"] == latest_github_date]["repo_candidates"].max())
        if latest_github_date and not candidates_daily.empty
        else 0
    )

    if not github_adoption.empty:
        rollup_daily = github_adoption[
            [
                "signal_date",
                "provider_display_name",
                "github_signal_repo_count",
                "github_manifest_repo_count",
                "github_import_repo_count",
                "github_env_repo_count",
                "github_model_repo_count",
            ]
        ].rename(
            columns={
                "github_signal_repo_count": "signal_repos",
                "github_manifest_repo_count": "manifest_repos",
                "github_import_repo_count": "import_repos",
                "github_env_repo_count": "env_repos",
                "github_model_repo_count": "model_repos",
            }
        )
    else:
        rollup_daily = pd.DataFrame(
            columns=["signal_date", "provider_display_name", "signal_repos", "manifest_repos", "import_repos", "env_repos", "model_repos"]
        )

    views["candidates_daily"] = candidates_daily
    views["rollup_daily"] = rollup_daily
    views["latest_github_candidate_count"] = latest_github_candidate_count
    return views


def render_provider_adoption_section(datasets: dict[str, DatasetLoadResult], provider_views: dict[str, object]) -> None:
    st.markdown('<div class="section-title">Provider Adoption</div>', unsafe_allow_html=True)
    st.caption("Scraped GitHub, PyPI, npm, and Hugging Face activity by provider")

    pypi_result = datasets.get("pypi_downloads_daily")
    npm_result = datasets.get("npm_downloads_daily")
    hf_result = datasets.get("huggingface_models_daily")

    if not pypi_result or not render_dataset_guard(pypi_result):
        st.info("Run the provider-adoption pipeline to populate GitHub, PyPI, npm, and Hugging Face scraped data.")
        return

    pypi = pypi_result.frame.copy()
    pypi = pypi[pypi["with_mirrors"] == False].copy()
    if pypi.empty:
        st.info("No PyPI provider data available yet.")
        return

    pypi_grouped = provider_views["pypi_grouped"]
    latest_pypi_date = provider_views["latest_pypi_date"]
    latest_pypi = provider_views["latest_pypi"]
    npm_grouped_all = provider_views["npm_grouped"]
    latest_npm_date = provider_views["latest_npm_date"]
    latest_npm_all = provider_views["latest_npm"]
    npm_categories = provider_views["npm_categories"]
    provider_order = provider_views["provider_order"]
    if not provider_order:
        st.info("No provider rows available yet.")
        return

    github_adoption = provider_views["github_adoption"]
    latest_github_date = provider_views["latest_github_date"]
    latest_hf_date = provider_views["latest_hf_date"]
    latest_hf = provider_views["latest_hf"]
    hf_grouped = provider_views["hf_grouped"]
    latest_hf_models = provider_views["latest_hf_models"]

    top_download_row = latest_pypi.sort_values("downloads", ascending=False).iloc[0] if not latest_pypi.empty else None
    total_latest_downloads = latest_pypi["downloads"].sum() if not latest_pypi.empty else 0
    latest_candidate_count = provider_views["latest_github_candidate_count"]
    top_hf_row = latest_hf.sort_values("downloads_30d", ascending=False).iloc[0] if not latest_hf.empty else None

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Top PyPI Provider</div>'
            f'<div class="kpi-value" style="font-size: 1.1rem;">{top_download_row["provider_display_name"] if top_download_row is not None else "—"}</div>'
            f'<div class="kpi-delta-flat">latest daily downloads</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Latest PyPI Downloads</div>'
            f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(total_latest_downloads)}</div>'
            f'<div class="kpi-delta-flat">{latest_pypi_date or "n/a"}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Top Hugging Face</div>'
            f'<div class="kpi-value" style="font-size: 1.1rem;">{top_hf_row["provider_display_name"] if top_hf_row is not None else "—"}</div>'
            f'<div class="kpi-delta-flat">by 30d downloads</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            f'<div class="kpi-card">'
            f'<div class="kpi-label">Latest GH Candidate Pool</div>'
            f'<div class="kpi-value" style="font-size: 1.5rem;">{format_metric(latest_candidate_count)}</div>'
            f'<div class="kpi-delta-flat">{latest_github_date or "n/a"}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    selected_npm_category = "core_sdk"
    if npm_categories:
        selected_npm_category = st.selectbox(
            "npm package category",
            options=npm_categories,
            index=npm_categories.index("core_sdk") if "core_sdk" in npm_categories else 0,
            format_func=lambda value: NPM_CATEGORY_LABELS.get(value, value.replace("_", " ").title()),
            key="provider_adoption_npm_category",
        )

    npm_grouped = (
        npm_grouped_all[npm_grouped_all["package_category"] == selected_npm_category].copy()
        if not npm_grouped_all.empty
        else pd.DataFrame(columns=["package_category", "download_date", "provider_display_name", "downloads"])
    )
    latest_npm = (
        latest_npm_all[latest_npm_all["package_category"] == selected_npm_category].copy()
        if not latest_npm_all.empty
        else pd.DataFrame(columns=["package_category", "download_date", "provider_display_name", "downloads"])
    )

    # HF/PyPI/npm each combine downloads + share into a single tab
    hf_tab, hf_models_tab, pypi_tab, npm_tab, github_tab, summary_tab = st.tabs(
        ["HF", "HF Models", "PyPI", "npm", "GitHub Signals", "Latest Summary"]
    )

    hf_metric = st.segmented_control(
        "Hugging Face metric",
        options=["Trailing 30d", "Daily (Est)", "All-time"],
        default="Trailing 30d",
        key="provider_adoption_hf_metric",
    )
    hf_metric_config = resolve_hf_metric_config(hf_metric)

    with hf_tab:
        if hf_result is None or hf_result.frame.empty or hf_grouped.empty:
            st.info("No Hugging Face model data available yet.")
        else:
            # Downloads trend
            pivot_hf = (
                hf_grouped.pivot_table(
                    index="download_date",
                    columns="provider_display_name",
                    values=hf_metric_config["value_column"],
                    aggfunc="last",
                )
                .fillna(0)
                .sort_index()
            )
            st.plotly_chart(
                make_line_chart(
                    pivot_hf, MODEL_COLORS,
                    title=hf_metric_config["downloads_title"],
                    y_title=hf_metric_config["downloads_axis"],
                    hover_suffix=hf_metric_config["downloads_hover"],
                ),
                width="stretch", theme=None,
            )
            # Market share (stacked bar)
            value_column = hf_metric_config["value_column"]
            totals = hf_grouped.groupby("download_date")[value_column].sum().rename("total").reset_index()
            share = hf_grouped.merge(totals, on="download_date", how="left")
            share["share"] = share[value_column] / share["total"].where(share["total"] != 0)
            pivot_share = (
                share.pivot_table(index="download_date", columns="provider_display_name", values="share", aggfunc="last")
                .fillna(0)
                .sort_index()
            )
            st.plotly_chart(
                make_stacked_bar(pivot_share * 100, MODEL_COLORS,
                                 title=hf_metric_config["share_title"], y_title="Share", pct=True, height=340),
                width="stretch", theme=None,
            )

    with hf_models_tab:
        if hf_result is None or hf_result.frame.empty or latest_hf_models.empty:
            st.info("No Hugging Face model snapshot available yet.")
        else:
            available_providers = sorted(
                provider for provider in latest_hf_models["provider_display_name"].dropna().astype(str).unique().tolist() if provider
            )
            selected_hf_provider = st.selectbox(
                "Hugging Face provider",
                options=["All"] + available_providers,
                index=0,
                key="provider_adoption_hf_provider",
            )
            st.caption(f"Latest HF snapshot: {latest_hf_date or 'n/a'}")
            if selected_hf_provider == "All":
                st.info("Choose a provider to view its top 20 Hugging Face models.")
            else:
                table = prepare_hf_models_table(
                    latest_hf_models,
                    provider_display_name=selected_hf_provider,
                    metric_label=hf_metric,
                    limit=20,
                )
                st.caption(
                    f"Showing top 20 models for {selected_hf_provider} by {hf_metric_config['models_caption_metric']}."
                )
                st.dataframe(dataframe_for_display(table, "-"), width="stretch", hide_index=True)

    with pypi_tab:
        # Downloads trend
        pivot_downloads = (
            pypi_grouped.pivot_table(index="download_date", columns="provider_display_name", values="downloads", aggfunc="last")
            .fillna(0)
            .sort_index()
        )
        st.plotly_chart(
            make_line_chart(pivot_downloads, MODEL_COLORS,
                            title="PyPI Daily Download History (Without Mirrors)",
                            y_title="Downloads", hover_suffix="downloads"),
            width="stretch", theme=None,
        )
        # Market share
        totals = pypi_grouped.groupby("download_date")["downloads"].sum().rename("total").reset_index()
        share = pypi_grouped.merge(totals, on="download_date", how="left")
        share["share"] = share["downloads"] / share["total"].where(share["total"] != 0)
        pivot_share = (
            share.pivot_table(index="download_date", columns="provider_display_name", values="share", aggfunc="last")
            .fillna(0)
            .sort_index()
        )
        st.plotly_chart(
            make_stacked_bar(pivot_share * 100, MODEL_COLORS,
                             title="PyPI Daily Download Share (Without Mirrors)",
                             y_title="Share", pct=True, height=340),
            width="stretch", theme=None,
        )

    with npm_tab:
        if npm_result is None or npm_result.frame.empty or npm_grouped.empty:
            st.info("No npm provider data available yet.")
        else:
            _npm_label = NPM_CATEGORY_LABELS.get(selected_npm_category, selected_npm_category)
            # Downloads trend
            pivot_downloads = (
                npm_grouped.pivot_table(index="download_date", columns="provider_display_name", values="downloads", aggfunc="last")
                .fillna(0)
                .sort_index()
            )
            st.plotly_chart(
                make_line_chart(pivot_downloads, MODEL_COLORS,
                                title=f"{_npm_label} npm Daily Download History",
                                y_title="Downloads", hover_suffix="downloads"),
                width="stretch", theme=None,
            )
            # Market share
            totals = npm_grouped.groupby("download_date")["downloads"].sum().rename("total").reset_index()
            share = npm_grouped.merge(totals, on="download_date", how="left")
            share["share"] = share["downloads"] / share["total"].where(share["total"] != 0)
            pivot_share = (
                share.pivot_table(index="download_date", columns="provider_display_name", values="share", aggfunc="last")
                .fillna(0)
                .sort_index()
            )
            st.plotly_chart(
                make_stacked_bar(pivot_share * 100, MODEL_COLORS,
                                 title=f"{_npm_label} npm Daily Download Share",
                                 y_title="Share", pct=True, height=340),
                width="stretch", theme=None,
            )

    with github_tab:
        if github_adoption.empty:
            st.info("No GitHub provider signal data available yet.")
        else:
            candidates_daily = provider_views["candidates_daily"]
            rollup_daily = provider_views["rollup_daily"]

            col_left, col_right = st.columns(2)
            with col_left:
                pivot_candidates = (
                    candidates_daily.set_index("repo_created_date")[["repo_candidates"]]
                    .rename(columns={"repo_candidates": "Scanned Repo Pool"})
                    .fillna(0)
                    .sort_index()
                )
                st.plotly_chart(
                    make_line_chart(pivot_candidates, MODEL_COLORS,
                                    title="GitHub Scanned New Repo Pool by Day",
                                    y_title="Repos", hover_suffix="repos", height=340),
                    width="stretch", theme=None,
                )

            with col_right:
                pivot_signals = (
                    rollup_daily.pivot_table(
                        index="signal_date",
                        columns="provider_display_name",
                        values="signal_repos",
                        aggfunc="last",
                    )
                    .fillna(0)
                    .sort_index()
                )
                st.plotly_chart(
                    make_line_chart(pivot_signals, MODEL_COLORS,
                                    title="GitHub Signal-Bearing Repos by Day",
                                    y_title="Repos", hover_suffix="repos", height=340),
                    width="stretch", theme=None,
                )

    with summary_tab:
        pypi_window = pypi_grouped.copy()
        pypi_window["download_date"] = pd.to_datetime(pypi_window["download_date"], errors="coerce")
        latest_pypi_ts = pd.to_datetime(latest_pypi_date, errors="coerce")
        trailing_start = latest_pypi_ts - pd.Timedelta(days=6) if pd.notna(latest_pypi_ts) else None

        if trailing_start is not None:
            window = pypi_window[pypi_window["download_date"] >= trailing_start].copy()
        else:
            window = pypi_window.copy()

        pypi_7d = (
            window.groupby("provider_display_name", dropna=False)["downloads"].mean().rename("PyPI 7d Avg").reset_index()
            if not window.empty
            else pd.DataFrame(columns=["provider_display_name", "PyPI 7d Avg"])
        )
        latest_pypi_summary = latest_pypi.rename(
            columns={
                "provider_display_name": "Provider",
                "downloads": "Latest PyPI Downloads",
            }
        )[["Provider", "Latest PyPI Downloads"]]

        summary = latest_pypi_summary.merge(
            pypi_7d.rename(columns={"provider_display_name": "Provider"}),
            on="Provider",
            how="left",
        )

        npm_window = npm_grouped.copy()
        npm_window["download_date"] = pd.to_datetime(npm_window["download_date"], errors="coerce")
        latest_npm_ts = pd.to_datetime(latest_npm_date, errors="coerce")
        npm_trailing_start = latest_npm_ts - pd.Timedelta(days=6) if pd.notna(latest_npm_ts) else None
        if npm_trailing_start is not None:
            npm_window = npm_window[npm_window["download_date"] >= npm_trailing_start].copy()

        if not latest_npm.empty:
            cat_summary = latest_npm[latest_npm["package_category"] == selected_npm_category].copy()
            if not cat_summary.empty:
                cat_summary = cat_summary.rename(columns={"provider_display_name": "Provider", "downloads": "npm Daily (Selected)"})[["Provider", "npm Daily (Selected)"]]
                summary = summary.merge(cat_summary, on="Provider", how="left")

        if not latest_hf.empty:
            hf_sum = latest_hf.rename(columns={
                "provider_display_name": "Provider",
                "downloads_30d": "HF 30d Downloads",
                "downloads_all_time": "HF All-Time Downloads",
                "downloads_daily_est": "HF Daily (Est)",
                "likes": "HF Likes"
            })[["Provider", "HF 30d Downloads", "HF All-Time Downloads", "HF Daily (Est)", "HF Likes"]]
            summary = summary.merge(hf_sum, on="Provider", how="left")

        if latest_github_date and not provider_views["rollup_daily"].empty:
            latest_rollup = provider_views["rollup_daily"]
            latest_rollup = latest_rollup[latest_rollup["signal_date"] == latest_github_date].copy()
            rollup_summary = latest_rollup.rename(
                columns={
                    "provider_display_name": "Provider",
                    "signal_repos": "GH Signals",
                    "import_repos": "Import Repos",
                }
            )[["Provider", "GH Signals", "Import Repos"]]
            summary = summary.merge(rollup_summary, on="Provider", how="left")

        # Sort: priority to HF 30d, otherwise PyPI
        sort_col = "HF 30d Downloads" if "HF 30d Downloads" in summary.columns else "Latest PyPI Downloads"
        summary = summary.sort_values(sort_col, ascending=False) if sort_col in summary.columns else summary

        display_date = latest_github_date or latest_npm_date or latest_pypi_date
        st.caption(f"Latest provider snapshot: {display_date or 'n/a'}")
        st.dataframe(dataframe_for_display(summary, "-"), width="stretch", hide_index=True)


def render(domain_states, datasets) -> None:
    provider_views = compute_provider_adoption_views(domain_states["provider_adoption"][0])
    render_provider_adoption_section(datasets, provider_views)
