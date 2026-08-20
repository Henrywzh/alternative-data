from __future__ import annotations

import inspect
import json
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
from dashboard.data import (DOMAIN_ORDER, DATASET_REGISTRY, DatasetLoadResult, FreshnessInfo, dataset_source_for_domain, domain_dataset_ids, load_domain_datasets, load_latest_manifest)
from openrouter_revenue import (
    build_price_context,
    build_conservative_provider_economics,
    build_provider_revenue_estimates,
    estimate_usage_revenue,
    summarize_economics_coverage,
)
from semiconductor_memory_data.sources.config import AI_DEMAND_PPI_WEIGHTS
from dashboard.theme import (ACCENT, BG, SIDEBAR, CARD, BORDER, TEXT, MUTED, GREEN, RED, YELLOW, GRID, TICK, MODEL_COLORS)
from dashboard.components import (format_metric, _empty_dataset_frame, _styler_applymap_compat, WEEKLY_MONTHLY_OTHER_PROVIDERS, DAILY_OTHER_PROVIDERS, US_PROVIDER_ORDER, CHINA_PROVIDER_ORDER, order_provider_columns, regroup_provider_pivot_for_display, render_dataset_guard, format_scraped_at_display, dataframe_for_display, make_stacked_bar, make_stacked_area_chart, make_line_chart, kpi_card_html, kpi_grid_html, _top_n_with_others)
from openrouter_derived_data.metrics import compute_legacy_original_price_series
from openrouter_derived_data.identity import load_capability_map


REVENUE_CACHE_VERSION = "2026-07-01-pricing-perf-v1"
OPENROUTER_COMPARISON_CACHE_VERSION = "2026-08-02-model-activity-test-run-filter-v1"
CHANGE_DISPLAY_MIN_PCT = -100.0
CHANGE_DISPLAY_MAX_PCT = 300.0


def canonical_provider_slug(value: object) -> str | None:
    """Normalize company identity without importing a standalone ``src`` module.

    Streamlit Cloud can load the dashboard module from a different import path
    than the local editable install.  Keeping this tiny display-level helper
    here avoids making dashboard startup depend on a separately packaged module;
    revenue estimation still uses the shared implementation in ``src``.
    """
    if value is None:
        return None
    slug = str(value).strip()
    if not slug or slug.casefold() in {"nan", "none", "null", "<na>"}:
        return None
    return "meta" if slug.casefold() == "meta-llama" else slug


def grouped_revenue_token_pivots(
    rev_data: dict[str, object],
    tok_data: dict[str, object],
    granularity: str,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return revenue/token pivots after applying the display grouping for one granularity."""
    rev_key = {
        "daily": "pivot_rev_daily",
        "weekly": "pivot_rev_weekly",
        "monthly": "pivot_rev_monthly",
    }[granularity]
    tok_key = {
        "daily": "pivot_daily",
        "weekly": "pivot_weekly",
        "monthly": "pivot_monthly",
    }[granularity]
    return (
        regroup_provider_pivot_for_display(rev_data.get(rev_key, pd.DataFrame()), granularity),
        regroup_provider_pivot_for_display(tok_data.get(tok_key, pd.DataFrame()), granularity),
    )


def rankings_week_context(datasets: dict[str, DatasetLoadResult]) -> dict[str, str | bool | None]:
    top_models = datasets.get("top_models")
    market_share = datasets.get("market_share")

    model_week = top_models.latest_date if top_models else None
    market_share_week = market_share.latest_date if market_share else None

    return {
        "model_week": model_week,
        "market_share_week": market_share_week,
        "model_scraped_at": top_models.latest_scraped_at if top_models else None,
        "market_share_scraped_at": market_share.latest_scraped_at if market_share else None,
        "has_divergent_weeks": bool(model_week and market_share_week and model_week != market_share_week),
    }


def rankings_bucket_warning(context: dict[str, str | bool | None]) -> str | None:
    if not context.get("has_divergent_weeks"):
        return None
    return (
        "Model rankings use week starting dates, while market share uses week ending dates. "
        "The latest completed buckets can differ by up to 6 days on the same scrape."
    )


def _pretty_task_label(task_slug: str) -> str:
    text = str(task_slug or "").replace(":", " · ").replace("_", " ").replace("-", " ")
    return " ".join(part.capitalize() for part in text.split()) or "Unknown"


MACRO_CATEGORY_COLORS = {
    "general": "#F97316",
    "agent": "#7C3AED",
    "code": "#16A34A",
    "data": "#2563EB",
}
DEFAULT_MACRO_COLOR = "#9CA3AF"


def _macro_color(macro_category: str) -> str:
    return MACRO_CATEGORY_COLORS.get(str(macro_category).lower(), DEFAULT_MACRO_COLOR)


_MODEL_DATE_SUFFIX_RE = re.compile(r"-(202[0-9]{5}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2})(?=:|$)")

# These two historical runs were local test scrapes of category-only model
# activity.  They carry request counts but are not production observations;
# when merged with the provider fallback they create false April
# tokens/request spikes.  Keep the guard here until the normalized remote
# parquet is regenerated, so local and Streamlit Cloud reads behave identically.
OPENROUTER_MODEL_ACTIVITY_TEST_RUN_IDS = frozenset({
    "20260416T134419Z-9c52eb4a",
    "20260424T163607Z-e27b0c04",
})


def _short_model_name(model_slug: str) -> str:
    """Provider-stripped, date-suffix-stripped display name (case preserved)."""
    text = str(model_slug)
    name = text.split("/", 1)[-1] if "/" in text else text
    return _MODEL_DATE_SUFFIX_RE.sub("", name)


def _task_top_models(model_rows: pd.DataFrame) -> pd.DataFrame:
    """Rank-1 (or highest-share) model per task category_slug, indexed by category_slug."""
    if model_rows.empty:
        return model_rows
    return (
        model_rows.sort_values(["category_slug", "rank", "model_share_pct"], ascending=[True, True, False])
        .drop_duplicates(subset=["category_slug"], keep="first")
        .set_index("category_slug")
    )


def _macro_top_models(model_rows: pd.DataFrame, task_summary: pd.DataFrame) -> pd.DataFrame:
    """Model with the highest share-of-total-spend contribution per macro category, indexed by macro_category."""
    if model_rows.empty or task_summary.empty:
        return pd.DataFrame()
    task_share_lookup = task_summary.set_index("category_slug")["task_share_pct"]
    contrib = model_rows.copy()
    contrib["task_share_pct"] = contrib["category_slug"].map(task_share_lookup)
    contrib["contribution_pct"] = contrib["model_share_pct"] / 100.0 * contrib["task_share_pct"]
    contrib = contrib.dropna(subset=["contribution_pct"])
    if contrib.empty:
        return pd.DataFrame()
    return (
        contrib.groupby(["macro_category", "model_permaslug"], as_index=False)["contribution_pct"]
        .sum()
        .sort_values(["macro_category", "contribution_pct"], ascending=[True, False])
        .drop_duplicates(subset=["macro_category"], keep="first")
        .set_index("macro_category")
    )


def _compute_task_spend_views(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {
            "latest_snapshot_date": None,
            "windows": [],
            "periods": [],
            "by_selection": {},
        }

    required = {"snapshot_date", "period", "window_days", "category_slug", "model_permaslug", "task_share_of_total", "model_share"}
    if not required.issubset(frame.columns):
        return {
            "latest_snapshot_date": None,
            "windows": [],
            "periods": [],
            "by_selection": {},
        }

    prepared = frame.copy()
    prepared["snapshot_date_dt"] = pd.to_datetime(prepared["snapshot_date"], errors="coerce")
    prepared["period"] = prepared["period"].astype("string")
    prepared["window_days"] = pd.to_numeric(prepared["window_days"], errors="coerce").astype("Int64")
    prepared["task_share_of_total"] = pd.to_numeric(prepared["task_share_of_total"], errors="coerce")
    prepared["model_share"] = pd.to_numeric(prepared["model_share"], errors="coerce")
    prepared["rank"] = pd.to_numeric(prepared.get("rank", pd.Series(pd.NA, index=prepared.index)), errors="coerce")
    prepared = prepared.dropna(subset=["snapshot_date_dt", "period", "window_days", "category_slug", "model_permaslug"])
    if prepared.empty:
        return {
            "latest_snapshot_date": None,
            "windows": [],
            "periods": [],
            "by_selection": {},
        }

    prepared["macro_category"] = prepared.get("macro_category", pd.Series(pd.NA, index=prepared.index)).fillna("unknown")
    prepared["task_share_pct"] = prepared["task_share_of_total"] * 100
    prepared["model_share_pct"] = prepared["model_share"] * 100
    prepared["window_days_int"] = prepared["window_days"].astype(int)
    prepared["snapshot_date_str"] = prepared["snapshot_date_dt"].dt.strftime("%Y-%m-%d")

    history_source = prepared.drop_duplicates(subset=["snapshot_date_str", "period", "window_days_int", "category_slug"])
    history_by_selection: dict[tuple[str, int], pd.DataFrame] = {}
    for (period, window_days), selection in history_source.groupby(["period", "window_days_int"], sort=True):
        pivot = (
            selection.groupby(["snapshot_date_str", "macro_category"], as_index=False)["task_share_pct"]
            .sum()
            .pivot(index="snapshot_date_str", columns="macro_category", values="task_share_pct")
            .sort_index()
        )
        history_by_selection[(str(period), int(window_days))] = pivot

    latest_date = prepared["snapshot_date_dt"].max()
    latest = prepared[prepared["snapshot_date_dt"] == latest_date].copy()
    latest["task_label"] = latest["category_slug"].map(_pretty_task_label)

    periods = [value for value in ("spend", "tokens") if value in set(latest["period"].dropna().astype(str))]
    periods.extend(sorted(set(latest["period"].dropna().astype(str)) - set(periods)))
    windows = sorted(latest["window_days_int"].dropna().unique().tolist())
    by_selection: dict[tuple[str, int], dict[str, object]] = {}

    for (period, window_days), selection in latest.groupby(["period", "window_days_int"], sort=True):
        selection = selection.copy()
        task_summary = (
            selection.drop_duplicates(subset=["category_slug"])
            [["category_slug", "task_label", "macro_category", "task_share_pct"]]
            .sort_values("task_share_pct", ascending=False)
            .reset_index(drop=True)
        )
        model_rows = (
            selection[["category_slug", "task_label", "macro_category", "model_permaslug", "model_share_pct", "rank"]]
            .sort_values(["category_slug", "rank", "model_share_pct"], ascending=[True, True, False])
            .reset_index(drop=True)
        )
        top_task = str(task_summary.iloc[0]["category_slug"]) if not task_summary.empty else None
        top_model = None
        if top_task:
            task_models = model_rows[model_rows["category_slug"] == top_task].sort_values(
                ["rank", "model_share_pct"],
                ascending=[True, False],
            )
            if not task_models.empty:
                top_model = str(task_models.iloc[0]["model_permaslug"])
        macro_summary = (
            task_summary.groupby("macro_category", as_index=False)["task_share_pct"]
            .sum()
            .sort_values("task_share_pct", ascending=False)
            .reset_index(drop=True)
        )
        by_selection[(str(period), int(window_days))] = {
            "task_summary": task_summary,
            "model_rows": model_rows,
            "macro_summary": macro_summary,
            "top_task": top_task,
            "top_model": top_model,
        }

    return {
        "latest_snapshot_date": latest_date.strftime("%Y-%m-%d"),
        "windows": windows,
        "periods": periods,
        "by_selection": by_selection,
        "history_by_selection": history_by_selection,
    }


# --- OpenRouter Provider Mapping ---
OPENROUTER_PROVIDER_MAP = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "meta": "Meta",
    "meta-llama": "Meta",
    "mistralai": "Mistral AI",
    "cohere": "Cohere",
    "qwen": "Alibaba (Qwen)",
    "z-ai": "智谱AI (Z.ai)",
    "deepseek": "DeepSeek",
    "google-palm": "Google (PaLM)",
    "perplexity": "Perplexity",
    "nvidia": "NVIDIA",
    "databricks": "Databricks",
    "pygmalionai": "Pygmalion AI",
    "bytedance-seed": "ByteDance (Seed)",
    "liquid": "Liquid AI",
    "arcee-ai": "Arcee AI",
    "stepfun": "StepFun",
    "kwaipilot": "Kwai (Kwailab)",
    "rekaai": "Reka AI",
    "xiaomi": "Xiaomi",
    "minimax": "MiniMax",
    "tencent": "Tencent",
    "x-ai": "xAI (Grok)",
    "01-ai": "01.AI (Yi)",
    "upstage": "Upstage",
    "together-ai": "Together AI",
    "microsoft": "Microsoft",
    "openrouter": "OpenRouter",
    "moonshotai": "Moonshot AI",
    "zhipu": "智谱AI (Z.ai)",
}


def _derive_provider_name(model_id: str, official_provider: str | None) -> str:
    """Derives a provider name from the model ID if the official provider is missing."""
    if pd.notna(official_provider) and str(official_provider).strip() != "" and str(official_provider) != "nan":
        # Check if official_provider is a number (like 262144 from historical bug)
        try:
            val = float(official_provider)
            if val > 1000: # Likely context length or other numeric metadata leak
                pass # fall through to derivation
            else:
                return str(official_provider)
        except (ValueError, TypeError):
            return str(official_provider)
    
    if pd.isna(model_id) or not isinstance(model_id, str):
        return "Unknown"
        
    if "/" in model_id:
        slug_prefix = model_id.split("/")[0].lower()
        slug_prefix = canonical_provider_slug(slug_prefix) or slug_prefix
        return OPENROUTER_PROVIDER_MAP.get(slug_prefix, slug_prefix.capitalize())
    
    return "Unknown"


def _fuzzy_normalize_model_id(model_id: str) -> str:
    """Normalize model IDs to match between rankings and pricing table."""
    val = str(model_id).lower()
    # Strip date suffixes like -20260217
    val = re.sub(r"-(202[0-9]{5}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2})$", "", val)
    # Strip modifiers
    val = val.replace(":thinking", "").replace(":beta", "").replace(":free", "").replace(":online", "")
    
    parts = val.split("/")
    if len(parts) < 2:
        return val
        
    provider, model = parts[0], parts[1]
    # Tokenize model part
    tokens = re.findall(r"[a-z0-9.]+", model)
    # Join sorted to handle order swaps (e.g. claude-4.6-sonnet vs claude-sonnet-4.6)
    normalized_model = "".join(sorted(tokens))
    return f"{provider}/{normalized_model}"


@st.cache_data(ttl=3600, max_entries=12)
def compute_openrouter_views(
    datasets: dict[str, DatasetLoadResult],
    revenue_cache_version: str = REVENUE_CACHE_VERSION,
) -> dict[str, object]:
    _ = revenue_cache_version
    views: dict[str, object] = {}

    top_models_result = datasets.get("top_models")
    market_share_result = datasets.get("market_share")
    if not top_models_result or top_models_result.frame.empty:
        views["top_models"] = {"weeks": [], "pivot_total": pd.DataFrame()}
    else:
        top_frame = top_models_result.frame.copy()
        top_frame["week_start_date"] = top_frame["week_start_date"].astype(str)
        top_totals = (
            top_frame.groupby("week_start_date", as_index=True)["metric_value"]
            .sum()
            .rename("top_models")
            .sort_index()
        )
        merged_totals = top_totals.to_frame()
        total_source = "top_models"
        if market_share_result and not market_share_result.frame.empty:
            market_frame = market_share_result.frame.copy()
            market_totals = _market_share_weekly_totals(market_frame)
            merged_totals = merged_totals.join(market_totals, how="outer")

            def _select_total(row: pd.Series) -> float:
                top_value = pd.to_numeric(pd.Series([row.get("top_models")]), errors="coerce").iloc[0]
                share_value = pd.to_numeric(pd.Series([row.get("market_share")]), errors="coerce").iloc[0]
                if pd.isna(share_value):
                    return float(top_value) if pd.notna(top_value) else np.nan
                if pd.isna(top_value):
                    return float(share_value)
                if share_value >= top_value * 0.80:
                    return float(share_value)
                return float(top_value)

            def _select_source(row: pd.Series) -> str:
                top_value = pd.to_numeric(pd.Series([row.get("top_models")]), errors="coerce").iloc[0]
                share_value = pd.to_numeric(pd.Series([row.get("market_share")]), errors="coerce").iloc[0]
                if pd.isna(share_value):
                    return "top_models"
                if pd.isna(top_value):
                    return "market_share"
                return "market_share" if share_value >= top_value * 0.80 else "top_models"

            merged_totals["selected_source"] = merged_totals.apply(_select_source, axis=1)
            merged_totals["Total Tokens"] = merged_totals.apply(_select_total, axis=1)
            previous_total = np.nan
            for index, row in merged_totals.sort_index().iterrows():
                if row["selected_source"] == "market_share" and pd.isna(row.get("top_models")) and pd.notna(previous_total):
                    share_value = pd.to_numeric(pd.Series([row.get("market_share")]), errors="coerce").iloc[0]
                    if pd.notna(share_value) and share_value < previous_total * 0.80:
                        merged_totals.at[index, "Total Tokens"] = np.nan
                        merged_totals.at[index, "selected_source"] = "suppressed_incomplete_market_share"
                        continue
                if pd.notna(row.get("Total Tokens")):
                    previous_total = float(row["Total Tokens"])
            total_source = "hybrid"
        else:
            merged_totals["selected_source"] = "top_models"
            merged_totals["Total Tokens"] = merged_totals["top_models"]

        pivot_total = merged_totals[["Total Tokens"]].dropna().sort_index()
        views["top_models"] = {
            "weeks": sorted(pivot_total.index.astype(str).tolist(), reverse=True),
            "pivot_total": pivot_total,
            "total_source": total_source,
            "source_by_week": merged_totals.get("selected_source", pd.Series(dtype="string")).to_dict(),
        }

    result = datasets.get("market_share")
    if result and not result.frame.empty:
        frame = result.frame.copy()
        # Company-level displays merge Meta's direct and Llama routes into one
        # origin company while preserving the raw ranking dataset unchanged.
        # Sunday and Monday snapshots can represent the same aligned week; use
        # the canonical snapshot selector so a malformed later copy cannot
        # create a false near-zero step in the provider chart.
        canonical_rows = _comparison_weekly_rankings(
            frame,
            date_column="week_start_date",
            entity_column="entity_id",
            value_column="metric_value",
            entity_mapper=canonical_provider_slug,
            sunday_alignment=True,
            exclude_other_entities=False,
        )
        canonical_rows["week_start_date"] = canonical_rows["period_start"].dt.strftime("%Y-%m-%d")
        pivot = (
            canonical_rows.pivot_table(index="week_start_date", columns="entity_id", values="value", aggfunc="sum")
            .fillna(0)
            .sort_index()
        )
        views["market_share"] = {
            "weeks": sorted(canonical_rows["week_start_date"].unique(), reverse=True),
            "pivot_pct_top": _top_n_with_others(pivot, top_n_count=15, exclude_others_named=True, pct=True),
        }
    else:
        views["market_share"] = {"weeks": [], "pivot_pct_top": pd.DataFrame()}

    requests_result = datasets.get("provider_weekly_requests")
    if requests_result and not requests_result.frame.empty:
        # ``provider_weekly_requests`` is a separately labelled historical
        # request series.  Do not de-duplicate it against ``market_share``:
        # the latter is token-volume data and can legitimately share provider
        # keys/values on newer rankings snapshots.
        request_frame = requests_result.frame.copy()
        request_frame["usage_week"] = _align_rankings_week_to_monday(request_frame["week_start_date"].astype(str))
        request_frame["metric_value"] = pd.to_numeric(request_frame["metric_value"], errors="coerce")
        request_frame["entity_id"] = request_frame["entity_id"].map(canonical_provider_slug)
        request_frame["provider_label"] = request_frame["entity_id"].astype("string").str.lower().map(OPENROUTER_PROVIDER_MAP)
        fallback_label = request_frame.get("entity_name", request_frame["entity_id"]).astype("string")
        request_frame["provider_label"] = request_frame["provider_label"].fillna(fallback_label)
        request_frame["provider_label"] = request_frame["provider_label"].replace({"others": "Others"})
        pivot_requests = (
            request_frame.dropna(subset=["usage_week", "provider_label"])
            .pivot_table(index="usage_week", columns="provider_label", values="metric_value", aggfunc="sum")
            .fillna(0)
            .sort_index()
        )
        pivot_requests = regroup_provider_pivot_for_display(pivot_requests, "weekly")
        views["provider_weekly_requests"] = {
            "weeks": sorted(pivot_requests.index.astype(str).tolist(), reverse=True),
            "pivot_weekly": pivot_requests,
        }
    else:
        views["provider_weekly_requests"] = {"weeks": [], "pivot_weekly": pd.DataFrame()}

    task_spend_result = datasets.get("openrouter_task_spend")
    task_spend_frame = task_spend_result.frame.copy() if task_spend_result and not task_spend_result.frame.empty else pd.DataFrame()
    views["task_spend"] = _compute_task_spend_views(task_spend_frame)

    views.update(_compute_revenue_views(datasets))
    return views


def _week_start(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series, errors="coerce")
    return (dates - pd.to_timedelta(dates.dt.weekday, unit="D")).dt.normalize().dt.strftime("%Y-%m-%d")


def _align_rankings_week_to_monday(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series, errors="coerce")
    dates = dates.apply(lambda value: value + pd.Timedelta(days=1) if pd.notna(value) and value.weekday() == 6 else value)
    return (dates - pd.to_timedelta(dates.dt.weekday, unit="D")).dt.normalize().dt.strftime("%Y-%m-%d")


def _market_share_weekly_totals(frame: pd.DataFrame) -> pd.Series:
    """Return one coherent rankings-volume snapshot per aligned week.

    ``market_share`` is an append-only history assembled from several
    rankings snapshots.  A week can therefore contain an older Sunday
    snapshot, a newer Monday snapshot, and (for a few runs) a partial or
    malformed provider batch.  Summing every row makes those snapshots look
    like one observation and can inflate downstream volume charts by thousands
    of times.  Prefer the newest *complete* snapshot for each week (with row
    count as the completeness guard), then retain the Monday snapshot when a
    Sunday/Monday pair exists.
    """
    if frame.empty:
        return pd.Series(dtype="float64", name="market_share")
    market = frame.copy()
    original_dates = pd.to_datetime(market["week_start_date"].astype(str), errors="coerce")
    market["original_week_start_date"] = original_dates.dt.normalize()
    market["week_start_date"] = _align_rankings_week_to_monday(market["week_start_date"].astype(str))
    market["metric_value"] = pd.to_numeric(market["metric_value"], errors="coerce")
    market["_is_sunday_snapshot"] = market["original_week_start_date"].dt.weekday.eq(6).astype(int)
    market = market.dropna(subset=["original_week_start_date", "week_start_date", "metric_value"])
    if market.empty:
        return pd.Series(dtype="float64", name="market_share")

    # Each scraper run is a snapshot.  Select the most complete/latest run
    # for an aligned week before resolving Sunday/Monday duplicate dates.
    # This removes partial legacy batches (including the known four-provider
    # trillion-scale rows) without applying an arbitrary value threshold.
    source_run = market.get("source_run_id")
    scraped_at = (
        pd.to_datetime(market.get("scraped_at"), errors="coerce", format="mixed")
        if "scraped_at" in market
        else None
    )
    if source_run is not None:
        market["_snapshot_id"] = source_run.astype("string").fillna("")
        market["_snapshot_at"] = scraped_at if scraped_at is not None else pd.NaT
        snapshot_dates = (
            market.groupby(
                ["week_start_date", "_snapshot_id", "original_week_start_date"],
                as_index=False,
            )
            .agg(
                metric_value=("metric_value", "sum"),
                snapshot_rows=("metric_value", "size"),
                snapshot_sunday_rows=("_is_sunday_snapshot", "sum"),
                snapshot_at=("_snapshot_at", "max"),
            )
        )
        snapshot_runs = (
            snapshot_dates.groupby(["week_start_date", "_snapshot_id"], as_index=False)
            .agg(
                snapshot_rows=("snapshot_rows", "sum"),
                snapshot_sunday_rows=("snapshot_sunday_rows", "sum"),
                snapshot_at=("snapshot_at", "max"),
            )
            .sort_values(
                ["week_start_date", "snapshot_rows", "snapshot_sunday_rows", "snapshot_at", "_snapshot_id"],
                ascending=[True, False, False, False, False],
            )
            .drop_duplicates("week_start_date", keep="first")
        )
        selected = snapshot_dates.merge(
            snapshot_runs[["week_start_date", "_snapshot_id"]],
            on=["week_start_date", "_snapshot_id"],
            how="inner",
        )
        selected["is_aligned_monday"] = (
            selected["original_week_start_date"].dt.strftime("%Y-%m-%d")
            == selected["week_start_date"]
        )
        totals = selected.sort_values(
            ["week_start_date", "is_aligned_monday", "original_week_start_date"],
            ascending=[True, False, False],
        )
    else:
        totals = (
            market.groupby(["week_start_date", "original_week_start_date"], as_index=False)["metric_value"]
            .sum()
        )
        totals["is_aligned_monday"] = (
            totals["original_week_start_date"].dt.strftime("%Y-%m-%d") == totals["week_start_date"]
        )
    if totals.empty:
        return pd.Series(dtype="float64", name="market_share")
    return (
        totals.drop_duplicates(subset=["week_start_date"], keep="first")
        .set_index("week_start_date")["metric_value"]
        .rename("market_share")
        .sort_index()
    )


def _clean_provider_request_frame(
    request_frame: pd.DataFrame,
    market_share_frame: pd.DataFrame,
) -> pd.DataFrame:
    """Explicitly remove known duplicated payloads for legacy callers.

    The dashboard no longer applies this heuristic to the recovered request
    history: a request-labelled dataset must not be discarded merely because
    its values happen to match a token snapshot.  The helper remains for
    compatibility with older analysis code and tests that opt into that
    conservative de-duplication explicitly.
    """
    if request_frame.empty or market_share_frame.empty:
        return request_frame.copy()
    request_keys = ["week_start_date", "entity_id", "metric_value"]
    if not set(request_keys).issubset(request_frame.columns) or not set(request_keys).issubset(market_share_frame.columns):
        return request_frame.copy()
    cleaned = request_frame.copy()
    right = market_share_frame[request_keys].copy()
    for current in (cleaned, right):
        current["week_start_date"] = current["week_start_date"].astype("string")
        current["entity_id"] = current["entity_id"].astype("string")
        current["metric_value"] = pd.to_numeric(current["metric_value"], errors="coerce").round(6)
    right["_market_share_duplicate"] = True
    duplicate_keys = right.drop_duplicates(request_keys)
    cleaned = cleaned.merge(duplicate_keys, on=request_keys, how="left")
    return cleaned[cleaned["_market_share_duplicate"].isna()].drop(columns="_market_share_duplicate")


def _period_coverage(frame: pd.DataFrame, period_column: str, date_column: str, expected_days: int) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[period_column, "observed_days", "expected_days", "is_partial_period"])
    coverage = (
        frame.groupby(period_column)[date_column]
        .nunique()
        .rename("observed_days")
        .reset_index()
        .sort_values(period_column)
    )
    coverage["expected_days"] = expected_days
    coverage["is_partial_period"] = coverage["observed_days"] < coverage["expected_days"]
    return coverage


def _scale_partial_week_values(
    modern_frame: pd.DataFrame,
    pivot_raw: pd.DataFrame,
    week_column: str,
    provider_column: str,
    value_column: str,
    date_column: str,
) -> pd.DataFrame:
    if pivot_raw.empty:
        return pivot_raw

    pivot = pivot_raw.copy()
    days_per_week = (
        modern_frame.groupby([week_column, provider_column])[date_column]
        .nunique()
        .rename("days_present")
    )
    first_week = pivot.index.min()
    first_week_dt = pd.Timestamp(first_week)
    next_week = (first_week_dt + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    first_week_rows = modern_frame[modern_frame[week_column] == first_week].copy()
    next_week_rows = modern_frame[modern_frame[week_column] == next_week].copy()

    if not next_week_rows.empty:
        for provider in pivot.columns:
            provider_first_rows = first_week_rows[first_week_rows[provider_column] == provider]
            if provider_first_rows.empty:
                continue
            observed_weekdays = set(provider_first_rows[date_column].dt.weekday.astype(int).tolist())
            if 0 < len(observed_weekdays) < 7:
                missing_weekdays = set(range(7)) - observed_weekdays
                provider_next_rows = next_week_rows[next_week_rows[provider_column] == provider]
                bridged_missing = provider_next_rows[
                    provider_next_rows[date_column].dt.weekday.isin(missing_weekdays)
                ][value_column].sum()
                if bridged_missing > 0:
                    observed_total = provider_first_rows[value_column].sum()
                    pivot.loc[first_week, provider] = observed_total + bridged_missing

    for week in pivot.index:
        for provider in pivot.columns:
            try:
                days_present = days_per_week.loc[(week, provider)]
            except KeyError:
                continue
            if 0 < days_present < 7:
                if week == first_week and pivot.loc[week, provider] > 0:
                    provider_first_rows = modern_frame[
                        (modern_frame[week_column] == week) & (modern_frame[provider_column] == provider)
                    ]
                    observed_total = provider_first_rows[value_column].sum()
                    if pivot.loc[week, provider] > observed_total:
                        continue
                pivot.loc[week, provider] *= 7 / days_present
    return pivot.sort_index()


def _revenue_pivots_from_economics(economics: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if economics.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    priced = economics[economics["estimated_revenue"].notna()].copy()
    if priced.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    priced["usage_date_dt"] = pd.to_datetime(priced["usage_date"], errors="coerce")
    priced = priced.dropna(subset=["usage_date_dt"])
    priced["usage_date_str"] = priced["usage_date_dt"].dt.strftime("%Y-%m-%d")
    priced["usage_week"] = _week_start(priced["usage_date_dt"])
    priced["usage_month"] = priced["usage_date_dt"].dt.strftime("%Y-%m")
    priced["provider_label"] = priced["provider_name"].fillna(priced["provider_slug"])
    daily = priced.pivot_table(index="usage_date_str", columns="provider_label", values="estimated_revenue", aggfunc="sum").fillna(0).sort_index()
    weekly = priced.pivot_table(index="usage_week", columns="provider_label", values="estimated_revenue", aggfunc="sum").fillna(0).sort_index()
    monthly = priced.pivot_table(index="usage_month", columns="provider_label", values="estimated_revenue", aggfunc="sum").fillna(0).sort_index()
    return daily, weekly, monthly


def _pivot_to_share_percent(pivot_df: pd.DataFrame) -> pd.DataFrame:
    if pivot_df.empty:
        return pivot_df.copy()
    denominator = pivot_df.sum(axis=1).replace(0, np.nan)
    return pivot_df.div(denominator, axis=0).fillna(0.0) * 100


def _pivot_to_change_percent(pivot_df: pd.DataFrame, granularity: str) -> pd.DataFrame:
    if pivot_df.empty:
        return pivot_df.copy()
    numeric = pivot_df.apply(pd.to_numeric, errors="coerce").sort_index()
    if granularity == "daily":
        baseline = numeric.rolling(window=7, min_periods=7).mean()
        prior = baseline.shift(7)
    elif granularity in {"weekly", "monthly"}:
        baseline = numeric
        prior = baseline.shift(1)
    else:
        raise ValueError(f"Unsupported granularity: {granularity}")
    changed = baseline.sub(prior).div(prior.replace(0, np.nan)) * 100
    return changed.replace([np.inf, -np.inf], np.nan)


def _pivot_to_aggregate_change_percent(pivot_df: pd.DataFrame, granularity: str, series_name: str) -> pd.DataFrame:
    if pivot_df.empty:
        return pd.DataFrame(columns=[series_name])
    numeric = pivot_df.apply(pd.to_numeric, errors="coerce").sort_index()
    total = numeric.sum(axis=1).to_frame(name=series_name)
    return _pivot_to_change_percent(total, granularity)


def _drop_first_valid_change_point(pivot_df: pd.DataFrame) -> pd.DataFrame:
    if pivot_df.empty:
        return pivot_df.copy()
    cleaned = pivot_df.copy()
    valid_rows = cleaned.notna().any(axis=1)
    if valid_rows.any():
        first_valid = valid_rows[valid_rows].index[0]
        cleaned.loc[first_valid] = np.nan
    return cleaned


def _nowcast_latest_partial_period(
    period_pivot: pd.DataFrame,
    daily_pivot: pd.DataFrame,
    granularity: str,
) -> tuple[pd.DataFrame, set[str]]:
    adjusted = period_pivot.copy()
    if adjusted.empty or daily_pivot.empty or granularity not in {"weekly", "monthly"}:
        return adjusted, set()

    daily = daily_pivot.apply(pd.to_numeric, errors="coerce").copy()
    daily_dates = pd.to_datetime(daily.index, errors="coerce")
    valid_mask = pd.Series(daily_dates.notna(), index=daily.index)
    if not valid_mask.any():
        return adjusted, set()

    daily = daily.loc[valid_mask].copy()
    daily_dates = pd.Series(daily_dates[valid_mask], index=daily.index)
    latest_date = daily_dates.max()
    if pd.isna(latest_date):
        return adjusted, set()

    if granularity == "weekly":
        period_start = latest_date - pd.Timedelta(days=int(latest_date.weekday()))
        period_label = period_start.strftime("%Y-%m-%d")
        period_mask = (daily_dates >= period_start) & (daily_dates < period_start + pd.Timedelta(days=7))
        expected_days = 7
    else:
        period_label = latest_date.strftime("%Y-%m")
        period_mask = daily_dates.dt.strftime("%Y-%m") == period_label
        expected_days = int(latest_date.days_in_month)

    if period_label not in adjusted.index:
        return adjusted, set()

    observed_days = int(daily_dates[period_mask].dt.strftime("%Y-%m-%d").nunique())
    if observed_days <= 0 or observed_days >= expected_days:
        return adjusted, set()

    observed_total = float(daily.loc[period_mask].sum().sum())
    existing_total = float(pd.to_numeric(adjusted.loc[period_label], errors="coerce").fillna(0).sum())
    if observed_total <= 0 or existing_total <= 0:
        return adjusted, set()

    nowcast_total = observed_total * expected_days / observed_days
    adjusted.loc[period_label] = adjusted.loc[period_label] * (nowcast_total / existing_total)
    return adjusted, {period_label}


def _cap_change_percent_for_display(pivot_df: pd.DataFrame) -> pd.DataFrame:
    if pivot_df.empty:
        return pivot_df.copy()
    return pivot_df.clip(lower=CHANGE_DISPLAY_MIN_PCT, upper=CHANGE_DISPLAY_MAX_PCT)


def _make_change_line_chart(
    pivot_df: pd.DataFrame,
    colors: list[str],
    x_title: str,
    y_title: str,
) -> go.Figure:
    fig = go.Figure()
    for i, col in enumerate(pivot_df.columns):
        fig.add_trace(
            go.Scatter(
                x=pivot_df.index,
                y=pivot_df[col],
                name=str(col),
                mode="lines+markers",
                line=dict(width=2.5, color=colors[i % len(colors)]),
                connectgaps=False,
                hovertemplate=f"<b>{col}</b><br>%{{x}}<br>%{{y:+.1f}}%<extra></extra>",
            )
        )
    fig.update_layout(
        template="plotly_white",
        xaxis_title=x_title,
        yaxis_title=y_title,
        legend=dict(orientation="h", y=-0.2),
        height=400,
        margin=dict(l=0, r=0, t=20, b=80),
    )
    fig.update_yaxes(ticksuffix="%", zeroline=True, zerolinecolor=GRID)
    return fig


def _estimator_coverage_summary(estimated: pd.DataFrame) -> dict[str, float | int | dict[str, int]]:
    if estimated.empty or "total_tokens" not in estimated.columns:
        return {
            "total_tokens": 0.0,
            "model_priced_tokens": 0.0,
            "fallback_priced_tokens": 0.0,
            "unpriced_tokens": 0.0,
            "model_priced_token_coverage": 0.0,
            "fallback_priced_token_coverage": 0.0,
            "unpriced_token_share": 0.0,
            "pricing_status_mix": {},
        }

    frame = estimated.copy()
    total_tokens = pd.to_numeric(frame["total_tokens"], errors="coerce").fillna(0.0)
    status = frame.get("pricing_join_status", pd.Series(pd.NA, index=frame.index)).astype("string")
    model_mask = status.isin(["matched_model_median", "matched_model_split_median", "free_model_zero_revenue"])
    fallback_mask = status.isin(["fallback_provider_median", "fallback_global_median"])
    unpriced_mask = status.isin(["unresolved_missing_pricing", "synthetic_unpriced"]) | status.isna()
    total = float(total_tokens.sum())
    model_tokens = float(total_tokens[model_mask].sum())
    fallback_tokens = float(total_tokens[fallback_mask].sum())
    unpriced_tokens = float(total_tokens[unpriced_mask].sum())
    return {
        "total_tokens": total,
        "model_priced_tokens": model_tokens,
        "fallback_priced_tokens": fallback_tokens,
        "unpriced_tokens": unpriced_tokens,
        "model_priced_token_coverage": model_tokens / total if total else 0.0,
        "fallback_priced_token_coverage": fallback_tokens / total if total else 0.0,
        "unpriced_token_share": unpriced_tokens / total if total else 0.0,
        "pricing_status_mix": status.value_counts(dropna=False).to_dict(),
    }


def _compute_revenue_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    """Dashboard-oriented provider tokens and revenue with legacy fallback stitching."""
    provider_res = datasets.get("provider_daily_activity")
    model_activity_res = datasets.get("openrouter_model_activity")
    market_share_res = datasets.get("market_share")
    pricing_res = datasets.get("raw_openrouter_models")
    macro_res = datasets.get("top_models")
    economics_mart_res = datasets.get("daily_provider_economics")
    revenue_estimates_mart_res = datasets.get("daily_provider_revenue_estimates")

    provider_activity = provider_res.frame.copy() if provider_res and not provider_res.frame.empty else pd.DataFrame()
    model_activity = (
        model_activity_res.frame.copy() if model_activity_res and not model_activity_res.frame.empty else pd.DataFrame()
    )
    pricing = pricing_res.frame.copy() if pricing_res and not pricing_res.frame.empty else pd.DataFrame()

    # Both revenue estimates below are precomputed daily by
    # openrouter-provider-activity-daily.yml (research_data.cli build-mart)
    # from the same provider_activity/pricing inputs used here. Reading the
    # marts avoids redoing the ~2s revenue estimation pass live on every
    # dashboard cache miss; only fall back to a live recompute if a mart is
    # unavailable (e.g. local dev without the committed parquet files).
    if economics_mart_res is not None and not economics_mart_res.frame.empty:
        economics = economics_mart_res.frame.copy()
    else:
        economics = build_conservative_provider_economics(
            provider_activity,
            pricing,
            model_activity=model_activity,
        )
    pivot_rev_daily = pd.DataFrame()
    pivot_rev_weekly = pd.DataFrame()
    pivot_rev_monthly = pd.DataFrame()

    pivot_tok_daily = pd.DataFrame()
    pivot_tok_weekly_modern = pd.DataFrame()
    pivot_tok_monthly_modern = pd.DataFrame()
    weekly_coverage = pd.DataFrame()
    monthly_coverage = pd.DataFrame()
    if not provider_activity.empty:
        modern_tok = provider_activity.copy()
        modern_tok["usage_date_dt"] = pd.to_datetime(modern_tok["usage_date"], errors="coerce")
        modern_tok = modern_tok.dropna(subset=["usage_date_dt"]).copy()
        modern_tok["usage_date_str"] = modern_tok["usage_date_dt"].dt.strftime("%Y-%m-%d")
        modern_tok["usage_week"] = _week_start(modern_tok["usage_date_dt"])
        modern_tok["usage_month"] = modern_tok["usage_date_dt"].dt.strftime("%Y-%m")
        modern_tok["provider_slug"] = modern_tok["entity_id"].map(canonical_provider_slug)
        modern_tok["provider_label"] = modern_tok["provider_slug"].map(
            lambda value: _derive_provider_name(f"{value}/model", None) if pd.notna(value) else "Unknown"
        )
        modern_tok["total_tokens"] = pd.to_numeric(modern_tok["total_tokens"], errors="coerce")
        pivot_tok_daily = modern_tok.pivot_table(index="usage_date_str", columns="provider_label", values="total_tokens", aggfunc="sum").fillna(0).sort_index()
        pivot_tok_weekly_modern_raw = modern_tok.pivot_table(index="usage_week", columns="provider_label", values="total_tokens", aggfunc="sum").fillna(0)
        pivot_tok_weekly_modern = _scale_partial_week_values(
            modern_tok,
            pivot_tok_weekly_modern_raw,
            "usage_week",
            "provider_label",
            "total_tokens",
            "usage_date_dt",
        )
        pivot_tok_monthly_modern = modern_tok.pivot_table(index="usage_month", columns="provider_label", values="total_tokens", aggfunc="sum").fillna(0).sort_index()
        weekly_coverage = _period_coverage(modern_tok, "usage_week", "usage_date_str", 7)
        monthly_expected = modern_tok.assign(
            expected_days=modern_tok["usage_date_dt"].dt.days_in_month
        ).groupby("usage_month", as_index=False)["expected_days"].max()
        monthly_coverage = (
            modern_tok.groupby("usage_month")["usage_date_str"].nunique().rename("observed_days").reset_index()
            .merge(monthly_expected, on="usage_month", how="left")
        )
        monthly_coverage["is_partial_period"] = monthly_coverage["observed_days"] < monthly_coverage["expected_days"]

    pivot_tok_weekly_legacy = pd.DataFrame()
    tok_legacy = pd.DataFrame()
    if market_share_res and not market_share_res.frame.empty:
        share = market_share_res.frame.copy()
        share["usage_week"] = _align_rankings_week_to_monday(share["week_start_date"])
        share = share.dropna(subset=["usage_week"]).copy()
        share = share.drop_duplicates(subset=["usage_week", "entity_id"])
        tok_legacy = share[["usage_week", "entity_id", "metric_value"]].copy()
        tok_legacy["provider_label"] = tok_legacy["entity_id"].apply(lambda x: _derive_provider_name(f"{x}/model", None))
        pivot_tok_weekly_legacy = (
            tok_legacy.pivot_table(index="usage_week", columns="provider_label", values="metric_value", aggfunc="sum")
            .fillna(0)
            .sort_index()
        )
        if not pivot_tok_weekly_modern.empty:
            first_modern_week = pivot_tok_weekly_modern.index.min()
            pivot_tok_weekly_legacy = pivot_tok_weekly_legacy[pivot_tok_weekly_legacy.index < first_modern_week]

    pivot_tok_weekly = pd.concat([pivot_tok_weekly_legacy, pivot_tok_weekly_modern]).fillna(0).sort_index()
    pivot_tok_weekly = pivot_tok_weekly.groupby(level=0).sum() if not pivot_tok_weekly.empty else pivot_tok_weekly

    tok_legacy_m = pd.DataFrame()
    if not pivot_tok_weekly_legacy.empty:
        legacy_month_index = pd.to_datetime(pivot_tok_weekly_legacy.index, errors="coerce").strftime("%Y-%m")
        tok_legacy_m = pivot_tok_weekly_legacy.copy()
        tok_legacy_m.index = legacy_month_index
        tok_legacy_m = tok_legacy_m.groupby(level=0).sum().sort_index()
    pivot_tok_monthly = pd.concat([tok_legacy_m, pivot_tok_monthly_modern]).fillna(0).sort_index()
    pivot_tok_monthly = pivot_tok_monthly.groupby(level=0).sum() if not pivot_tok_monthly.empty else pivot_tok_monthly

    big_tech_display = [
        "OpenAI", "Anthropic", "Google", "Meta", "DeepSeek",
        "Alibaba (Qwen)", "智谱AI (Z.ai)", "Moonshot AI", "xAI (Grok)",
        "Mistral AI", "Microsoft",
    ]
    if not pivot_tok_weekly.empty:
        for column in big_tech_display:
            if column in pivot_tok_weekly.columns:
                interpolated = pivot_tok_weekly[column].replace(0, float("nan")).interpolate(
                    method="linear", limit=4, limit_area="inside"
                )
                pivot_tok_weekly[column] = interpolated.fillna(0)

    modern_pivot_daily = pd.DataFrame()
    modern_pivot_weekly = pd.DataFrame()
    modern_pivot_monthly = pd.DataFrame()
    estimator_coverage = _estimator_coverage_summary(pd.DataFrame())
    if not provider_activity.empty:
        if revenue_estimates_mart_res is not None and not revenue_estimates_mart_res.frame.empty:
            modern_with_price = revenue_estimates_mart_res.frame.copy()
        else:
            modern_with_price = build_provider_revenue_estimates(provider_activity, pricing)
        estimator_coverage = _estimator_coverage_summary(modern_with_price)
        if "estimated_revenue" in modern_with_price.columns:
            modern_with_price = modern_with_price[modern_with_price["estimated_revenue"].notna()].copy()
        if not modern_with_price.empty:
            modern_with_price["revenue_usd"] = pd.to_numeric(modern_with_price["estimated_revenue"], errors="coerce")
            modern_with_price["usage_date_dt"] = pd.to_datetime(modern_with_price["usage_date"], errors="coerce")
            modern_with_price = modern_with_price.dropna(subset=["usage_date_dt"])
            modern_with_price = modern_with_price[modern_with_price["revenue_usd"] > 0].copy()
            modern_with_price["usage_date_str"] = modern_with_price["usage_date_dt"].dt.strftime("%Y-%m-%d")
            modern_with_price["usage_week"] = _week_start(modern_with_price["usage_date_dt"])
            modern_with_price["usage_month"] = modern_with_price["usage_date_dt"].dt.strftime("%Y-%m")
            modern_with_price["provider_slug"] = modern_with_price["provider_slug"].map(canonical_provider_slug)
            modern_with_price["provider_label"] = modern_with_price["provider_slug"].map(
                lambda value: _derive_provider_name(f"{value}/model", None) if pd.notna(value) else "Unknown"
            )

            modern_pivot_daily = (
                modern_with_price.pivot_table(index="usage_date_str", columns="provider_label", values="revenue_usd", aggfunc="sum")
                .fillna(0).sort_index()
            )
            modern_pivot_weekly_raw = (
                modern_with_price.pivot_table(index="usage_week", columns="provider_label", values="revenue_usd", aggfunc="sum")
                .fillna(0)
            )
            modern_pivot_weekly = _scale_partial_week_values(
                modern_with_price,
                modern_pivot_weekly_raw,
                "usage_week",
                "provider_label",
                "revenue_usd",
                "usage_date_dt",
            )
            modern_pivot_monthly = (
                modern_with_price.pivot_table(index="usage_month", columns="provider_label", values="revenue_usd", aggfunc="sum")
                .fillna(0).sort_index()
            )
            pivot_rev_daily = modern_pivot_daily

    strict_coverage_summary = summarize_economics_coverage(economics)
    coverage_summary = estimator_coverage if not provider_activity.empty else strict_coverage_summary

    if macro_res and not macro_res.frame.empty and market_share_res and not market_share_res.frame.empty:
        macro_df = macro_res.frame.copy()
        share_df = market_share_res.frame.copy()
        macro_df["usage_week"] = _align_rankings_week_to_monday(macro_df["week_start_date"].astype(str))
        share_df["usage_week"] = _align_rankings_week_to_monday(share_df["week_start_date"].astype(str))
        share_df["entity_id"] = share_df["entity_id"].map(canonical_provider_slug)

        macro_usage = macro_df.copy()
        macro_usage["usage_date"] = macro_usage["usage_week"]
        macro_usage["model_permaslug"] = macro_usage["entity_id"]
        macro_usage["provider_slug"] = macro_usage["parent_entity_id"]
        macro_usage["provider_name"] = macro_usage["parent_entity_name"].fillna(macro_usage["parent_entity_id"])
        macro_usage["total_tokens"] = pd.to_numeric(macro_usage["metric_value"], errors="coerce")
        macro_usage["prompt_tokens"] = 0.0
        macro_usage["completion_tokens"] = 0.0
        macro_usage["reasoning_tokens"] = np.nan

        macro_priced = estimate_usage_revenue(
            macro_usage[[
                "usage_date", "provider_slug", "provider_name", "model_permaslug",
                "total_tokens", "prompt_tokens", "completion_tokens", "reasoning_tokens",
            ]],
            pricing,
            slug_strategy="canonical",
            pricing_strategy="provider_fallback",
        )
        macro_priced = macro_priced[macro_priced["estimated_revenue"].notna()].copy()
        macro_priced["revenue_usd"] = pd.to_numeric(macro_priced["estimated_revenue"], errors="coerce")
        tier1_agg = (
            macro_priced.groupby(["usage_date", "provider_slug"], as_index=False)
            .agg(metric_value=("total_tokens", "sum"), revenue_usd=("revenue_usd", "sum"))
            .rename(columns={"usage_date": "usage_week"})
        )

        price_context = build_price_context(pricing)
        provider_benchmarks = {
            provider: values.get("pricing_blended", np.nan)
            for provider, values in price_context.provider_lookup.items()
            if pd.notna(values.get("pricing_blended", np.nan))
        }
        global_avg_price = (
            price_context.global_stats.get("pricing_blended", np.nan)
            if price_context.global_stats is not None
            else np.nan
        )

        share_dedup = share_df.drop_duplicates(subset=["usage_week", "entity_id"]).copy()
        combined = share_dedup.merge(
            tier1_agg,
            left_on=["usage_week", "entity_id"],
            right_on=["usage_week", "provider_slug"],
            how="left",
        ).fillna({"metric_value_y": 0.0, "revenue_usd": 0.0})

        def _legacy_hybrid_revenue(row: pd.Series) -> float:
            total_share_tokens = float(row.get("metric_value_x", 0.0))
            tier1_tokens = float(row.get("metric_value_y", 0.0))
            tier1_revenue = float(row.get("revenue_usd", 0.0))
            delta_tokens = max(0.0, total_share_tokens - tier1_tokens)
            provider_slug = str(row.get("entity_id", "")).lower()
            provider_median = provider_benchmarks.get(provider_slug, global_avg_price)
            if tier1_tokens > 0:
                vwap = tier1_revenue / tier1_tokens if tier1_tokens else 0.0
                delta_price = max(vwap, provider_median) if pd.notna(provider_median) else vwap
            else:
                delta_price = provider_median if pd.notna(provider_median) else 0.0
            return tier1_revenue + (delta_tokens * delta_price)

        combined["final_revenue"] = combined.apply(_legacy_hybrid_revenue, axis=1)
        combined["provider_label"] = combined["entity_id"].apply(lambda value: _derive_provider_name(f"{value}/model", None))
        combined["usage_date_dt"] = pd.to_datetime(combined["usage_week"], errors="coerce")
        combined["usage_month"] = combined["usage_date_dt"].dt.strftime("%Y-%m")

        pivot_rev_weekly_legacy = (
            combined.pivot_table(index="usage_week", columns="provider_label", values="final_revenue", aggfunc="sum")
            .fillna(0).sort_index()
        )
        # Keep legacy weeks strictly before modern (provider-activity-priced) coverage
        # begins, mirroring the token pivot's cutover a few lines up. This used to be
        # a hardcoded "2026-01-05" because that was where modern coverage started at
        # the time -- once modern coverage was backfilled deeper, the hardcoded date
        # left a long stretch where both legacy and modern covered the same weeks,
        # and concat+groupby(sum) below double-counted revenue for every one of them.
        if not modern_pivot_weekly.empty:
            first_modern_rev_week = modern_pivot_weekly.index.min()
            pivot_rev_weekly_legacy = pivot_rev_weekly_legacy[pivot_rev_weekly_legacy.index < first_modern_rev_week]

        pivot_rev_monthly_legacy = (
            combined.pivot_table(index="usage_month", columns="provider_label", values="final_revenue", aggfunc="sum")
            .fillna(0).sort_index()
        )
        if not modern_pivot_monthly.empty:
            first_modern_rev_month = modern_pivot_monthly.index.min()
            pivot_rev_monthly_legacy = pivot_rev_monthly_legacy[pivot_rev_monthly_legacy.index < first_modern_rev_month]

        pivot_rev_weekly = pd.concat([pivot_rev_weekly_legacy, modern_pivot_weekly]).fillna(0).sort_index()
        pivot_rev_weekly = pivot_rev_weekly.groupby(level=0).sum()

        if not modern_pivot_monthly.empty:
            modern_months = set(modern_pivot_monthly.index)
            legacy_only = pivot_rev_monthly_legacy[~pivot_rev_monthly_legacy.index.isin(modern_months)]
            overlap_months = pivot_rev_monthly_legacy[pivot_rev_monthly_legacy.index.isin(modern_months)]
            pivot_rev_monthly = pd.concat([
                legacy_only,
                overlap_months.add(modern_pivot_monthly, fill_value=0),
                modern_pivot_monthly.loc[~modern_pivot_monthly.index.isin(overlap_months.index)],
            ])
            pivot_rev_monthly = pivot_rev_monthly.sort_index().groupby(level=0).sum()
        else:
            pivot_rev_monthly = pivot_rev_monthly_legacy

        for column in big_tech_display:
            if column in pivot_rev_weekly.columns:
                interpolated = pivot_rev_weekly[column].replace(0, float("nan")).interpolate(
                    method="linear", limit=4, limit_area="inside"
                )
                pivot_rev_weekly[column] = interpolated.fillna(0)
            if column in pivot_rev_monthly.columns:
                interpolated = pivot_rev_monthly[column].replace(0, float("nan")).interpolate(
                    method="linear", limit=2, limit_area="inside"
                )
                pivot_rev_monthly[column] = interpolated.fillna(0)
    else:
        if pivot_rev_daily.empty and pivot_rev_weekly.empty and pivot_rev_monthly.empty:
            pivot_rev_daily, pivot_rev_weekly, pivot_rev_monthly = _revenue_pivots_from_economics(economics)

    return {
        "revenue_estimator": {
            "pivot_rev": pivot_rev_daily,
            "pivot_rev_daily": pivot_rev_daily,
            "pivot_rev_weekly": pivot_rev_weekly,
            "pivot_rev_monthly": pivot_rev_monthly,
            "total_revenue": float(pivot_rev_daily.sum().sum()) if not pivot_rev_daily.empty else 0,
            "has_activity": not provider_activity.empty,
            "merged_count": len(economics),
            "economics": economics,
            "coverage": coverage_summary,
            "strict_coverage": strict_coverage_summary,
            "legacy_cutover_week": modern_pivot_weekly.index.min() if not modern_pivot_weekly.empty else None,
        },
        "token_volume": {
            "pivot_daily": pivot_tok_daily,
            "pivot_weekly": pivot_tok_weekly,
            "pivot_monthly": pivot_tok_monthly,
            "weekly_coverage": weekly_coverage,
            "monthly_coverage": monthly_coverage,
        },
    }


def _default_task_spend_window(windows: list[int]) -> int:
    if not windows:
        return 7
    return 7 if 7 in windows else windows[0]


@st.cache_data(ttl=3600, max_entries=12)
def compute_compute_availability_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    # NOTE: Legacy function name. After removing AWS Spot + Lambda Cloud sources, this
    # now only surfaces OpenRouter catalog growth + latest-snapshot views used by the
    # Compute Evolution section on the OpenRouter tab.
    views: dict[str, object] = {}

    models_result = datasets.get("raw_openrouter_models")
    if models_result and not models_result.frame.empty:
        df = models_result.frame.copy()
        df["snapshot_ts"] = pd.to_datetime(df["snapshot_ts"], errors="coerce")
        df = df.dropna(subset=["snapshot_ts", "model_id"]).sort_values(["snapshot_ts", "model_id"]).reset_index(drop=True)

        if df.empty:
            views["models_latest"] = pd.DataFrame()
            views["models_growth"] = pd.DataFrame()
            views["models_history_start"] = None
            views["models_history_end"] = None
            return views

        snapshot_groups = list(df.groupby("snapshot_ts", sort=True))

        # Every recorded snapshot -- live-scraped or Wayback-backfilled -- is
        # one atomic pull of the entire openrouter.ai/api/v1/models response,
        # never a partial/incremental one: the live pipeline's
        # validate_current_catalog() rejects (and never writes) a collapsed
        # pull before it can reach this table, and the backfill script reads
        # a single-shot JSON dump per archived capture. So each snapshot's
        # own model_id set *is* the true catalog size as of that snapshot;
        # no "is this a full snapshot" guessing is needed or correct here.
        # (An earlier version of this used an 80%-of-max-snapshot-size
        # heuristic to decide full vs. partial and accumulated the "partial"
        # ones -- with backfilled history spanning catalog sizes from ~220 to
        # 600+, most of the smaller, perfectly legitimate early snapshots
        # fell under that threshold and got unioned instead of replaced,
        # producing an artificial climb-then-cliff sawtooth that didn't
        # exist in the underlying data.)
        growth_rows: list[dict[str, object]] = [
            {"snapshot_ts": snapshot_ts, "model_count": group["model_id"].nunique()}
            for snapshot_ts, group in snapshot_groups
        ]

        latest_ts = snapshot_groups[-1][0]
        latest_models = df[df["snapshot_ts"] == latest_ts].drop_duplicates(subset="model_id", keep="last").sort_values("model_id").reset_index(drop=True)
        # Prefer the authoritative current catalog emitted by the daily source.
        # The historical table is change-only and therefore cannot remove a
        # model that disappeared from the upstream API.
        source_path = models_result.source_path
        current_path = (
            source_path.parent / "raw_openrouter_models_current.parquet"
            if source_path is not None and source_path.is_absolute() else None
        )
        if current_path and current_path.exists():
            current_frame = pd.read_parquet(current_path)
            if not current_frame.empty and "model_id" in current_frame.columns:
                latest_models = current_frame.drop_duplicates("model_id", keep="last").sort_values("model_id").reset_index(drop=True)

        views["models_latest"] = latest_models
        views["models_growth"] = pd.DataFrame(growth_rows)
        views["models_history_start"] = snapshot_groups[0][0]
        views["models_history_end"] = latest_ts
    else:
        views["models_latest"] = pd.DataFrame()
        views["models_growth"] = pd.DataFrame()
        views["models_history_start"] = None
        views["models_history_end"] = None

    return views


def _prepare_explorer_catalog(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize the reconstructed OpenRouter catalog for explorer use."""
    if frame.empty:
        return pd.DataFrame()

    catalog = frame.copy()
    optional_columns = (
        "description", "hugging_face_id", "architecture_modality", "input_modalities_json",
        "output_modalities_json", "tokenizer", "instruct_type", "supported_parameters_json",
        "default_parameters_json", "per_request_limits_json", "pricing_input_cache_read",
        "pricing_input_cache_write", "top_provider_context_length",
        "top_provider_max_completion_tokens", "top_provider_is_moderated", "expiration_date",
        "knowledge_cutoff", "benchmarks_json", "links_json", "reasoning_json", "supported_voices_json",
    )
    for column in optional_columns:
        if column not in catalog.columns:
            catalog[column] = pd.NA
    for column in (
        "context_length", "pricing_prompt", "pricing_completion", "created_at",
        "pricing_input_cache_read", "pricing_input_cache_write", "top_provider_context_length",
        "top_provider_max_completion_tokens",
    ):
        catalog[column] = pd.to_numeric(catalog.get(column), errors="coerce")
    # OpenRouter uses -1 as an unavailable-price sentinel for routing-only
    # models.  Treat it as missing before deriving per-million display values.
    for column in (
        "pricing_prompt", "pricing_completion", "pricing_input_cache_read", "pricing_input_cache_write",
    ):
        catalog[column] = catalog[column].mask(catalog[column] < 0)
    catalog["provider_slug"] = catalog.get("provider_prefix", pd.Series(pd.NA, index=catalog.index)).astype("string")
    inferred_provider = catalog["model_id"].astype("string").str.split("/", n=1).str[0]
    catalog["provider_slug"] = catalog["provider_slug"].fillna(inferred_provider)
    catalog["is_openrouter_alias"] = (
        catalog["model_id"].astype("string").str.startswith("~", na=False)
        | catalog["provider_slug"].str.startswith("~", na=False)
    )
    # OpenRouter's ~...-latest entries are routing aliases, not separate companies.
    catalog["provider_slug"] = catalog["provider_slug"].str.lstrip("~").map(canonical_provider_slug)
    catalog["company"] = [
        _derive_provider_name(f"{provider}/{str(model_id).split('/', 1)[-1]}", None)
        for model_id, provider in zip(catalog["model_id"].astype("string"), catalog["provider_slug"])
    ]
    catalog["model_type"] = catalog["is_openrouter_alias"].map(
        {True: "OpenRouter latest alias", False: "Direct catalog model"}
    )
    catalog["model_name"] = catalog.get("model_name", catalog["model_id"]).fillna(catalog["model_id"])
    catalog["release_date"] = pd.to_datetime(catalog["created_at"], unit="s", errors="coerce", utc=True)
    catalog["input_price_per_m"] = catalog["pricing_prompt"] * 1_000_000
    catalog["output_price_per_m"] = catalog["pricing_completion"] * 1_000_000
    catalog["cache_read_price_per_m"] = catalog["pricing_input_cache_read"] * 1_000_000
    catalog["cache_write_price_per_m"] = catalog["pricing_input_cache_write"] * 1_000_000
    catalog["openrouter_url"] = "https://openrouter.ai/" + catalog["model_id"].astype(str)
    explorer_columns = [
        "model_id", "canonical_slug", "model_name", "provider_slug", "company",
        "is_openrouter_alias", "model_type",
        "release_date", "context_length", "architecture", "pricing_prompt",
        "pricing_completion", "input_price_per_m", "output_price_per_m",
        "cache_read_price_per_m", "cache_write_price_per_m", *optional_columns, "openrouter_url",
    ]
    return catalog[explorer_columns].sort_values(["company", "model_name", "model_id"]).reset_index(drop=True)


def _catalog_alias_map(catalog: pd.DataFrame) -> dict[str, str]:
    aliases: dict[str, str] = {}
    if catalog.empty:
        return aliases
    canonical_targets: dict[str, set[str]] = {}
    for _, row in catalog.iterrows():
        raw_model_id = row.get("model_id")
        raw_canonical_slug = row.get("canonical_slug")
        model_id = "" if pd.isna(raw_model_id) else str(raw_model_id)
        canonical_slug = "" if pd.isna(raw_canonical_slug) else str(raw_canonical_slug)
        if model_id:
            aliases[model_id] = model_id
        if canonical_slug:
            canonical_targets.setdefault(canonical_slug, set()).add(model_id)

    # A paid model and its :free variant can share the same canonical slug.
    # Resolve the bare slug to the paid/direct catalog model, while preserving
    # an explicit :free suffix for the free catalog entry.
    for canonical_slug, model_ids in canonical_targets.items():
        model_ids = {model_id for model_id in model_ids if model_id}
        if not model_ids:
            continue
        direct_ids = sorted(model_id for model_id in model_ids if not model_id.endswith(":free"))
        free_ids = sorted(model_id for model_id in model_ids if model_id.endswith(":free"))
        aliases[canonical_slug] = direct_ids[0] if direct_ids else free_ids[0]
        if not canonical_slug.endswith(":free"):
            # Provider activity may expose a dated free slug even when the
            # catalog only publishes the paid/direct preview model.
            aliases[f"{canonical_slug}:free"] = free_ids[0] if free_ids else aliases[canonical_slug]
    return aliases


def _normalize_explorer_activity(frame: pd.DataFrame, aliases: dict[str, str]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    activity = frame.copy()
    activity["usage_date_dt"] = pd.to_datetime(activity.get("usage_date"), errors="coerce")
    activity["model_permaslug"] = activity.get("model_permaslug", pd.Series(pd.NA, index=activity.index)).astype("string")
    activity["model_id"] = activity["model_permaslug"].map(aliases).fillna(activity["model_permaslug"])
    for column in ("total_tokens", "request_count", "prompt_tokens", "completion_tokens"):
        activity[column] = pd.to_numeric(activity.get(column, pd.Series(0, index=activity.index)), errors="coerce").fillna(0)
    keep_columns = [
        "usage_date_dt", "model_permaslug", "model_id", "entity_id", "entity_name",
        "category_slug", "total_tokens", "request_count", "prompt_tokens", "completion_tokens",
        "app_id", "app_name",
    ]
    for column in keep_columns:
        if column not in activity.columns:
            activity[column] = pd.NA
    activity = activity.dropna(subset=["usage_date_dt", "model_permaslug"])[keep_columns]
    activity["entity_id"] = activity["entity_id"].fillna(
        activity["model_id"].astype("string").str.split("/", n=1).str[0]
    )
    activity["entity_id"] = activity["entity_id"].astype("string").str.lstrip("~").map(canonical_provider_slug)
    activity.loc[activity["entity_id"].eq("meta"), "entity_name"] = "Meta"
    return activity


def _drop_known_model_activity_test_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Remove the two historical test runs without touching valid category history."""
    if frame.empty or "source_run_id" not in frame.columns:
        return frame
    run_ids = frame["source_run_id"].astype("string")
    return frame.loc[~run_ids.isin(OPENROUTER_MODEL_ACTIVITY_TEST_RUN_IDS)].copy()


def _combine_explorer_activity(provider_activity: pd.DataFrame, model_activity: pd.DataFrame) -> pd.DataFrame:
    """Prefer complete model totals and use provider rows for missing model-days.

    Older model-activity snapshots contain category-level rows, which are useful
    for workload detail but are not complete daily model totals. They must not
    suppress the fuller provider-page total for the same model/day.
    """
    model_activity = _drop_identical_route_alias_rows(model_activity)
    detail = model_activity[
        model_activity["category_slug"].astype("string").str.casefold().eq("all")
    ].copy() if not model_activity.empty else pd.DataFrame()
    fallback = provider_activity.copy()
    if detail.empty:
        if fallback.empty:
            return pd.DataFrame()
        fallback["activity_source"] = "Provider fallback"
        return fallback
    detail["activity_source"] = "Model activity"
    if fallback.empty:
        return detail

    # Compare the raw activity slug, not only the catalog-normalized model ID.
    # Paid and :free variants can intentionally share a catalog canonical slug;
    # each must be retained when the provider feed reports both variants.
    detail_keys = detail[["usage_date_dt", "model_permaslug"]].drop_duplicates()
    fallback = fallback.merge(
        detail_keys.assign(_has_model_activity=True),
        on=["usage_date_dt", "model_permaslug"],
        how="left",
    )
    fallback = fallback[fallback["_has_model_activity"].isna()].drop(columns="_has_model_activity")
    fallback["activity_source"] = "Provider fallback"
    return pd.concat([detail, fallback], ignore_index=True, sort=False)


def _drop_identical_route_alias_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Remove exact paid/`:free` duplicates from model-activity API rows.

    OpenRouter can return the canonical paid model payload for a `:free`
    request.  We keep a genuine `:free` row when its values differ, but drop
    only an exact per-day/category duplicate so provider-page free traffic can
    fill that route without being double-counted.
    """

    if frame.empty or "model_permaslug" not in frame.columns:
        return frame
    result = frame.copy()
    model = result["model_permaslug"].astype("string")
    result["_is_free_route"] = model.str.endswith(":free", na=False)
    result["_base_model"] = model.str.replace(r":free$", "", regex=True)
    compare_columns = [
        column for column in ("total_tokens", "request_count", "prompt_tokens", "completion_tokens")
        if column in result.columns
    ]
    if not compare_columns:
        return frame
    grouping = [column for column in ("usage_date_dt", "category_slug", "_base_model") if column in result.columns]
    # Almost every (date, category, base_model) group has just one row -
    # a group only needs the detailed row-by-row comparison below if it has
    # BOTH a free and a paid route, which is rare (a handful of groups out of
    # what's typically tens of thousands). Find those candidate groups with a
    # single cheap vectorized pass instead of running pandas' groupby/iterrows
    # machinery, with all its per-group DataFrame construction overhead, on
    # every group only to immediately skip almost all of them.
    route_counts = result.groupby(grouping, dropna=False)["_is_free_route"].agg(["sum", "count"])
    candidate_keys = route_counts.index[(route_counts["sum"] > 0) & (route_counts["sum"] < route_counts["count"])]
    if len(candidate_keys) == 0:
        return frame
    candidate_mask = (
        result.set_index(grouping).index.isin(candidate_keys)
        if len(grouping) > 1
        else result[grouping[0]].isin(candidate_keys)
    )
    drop_indices: set[object] = set()
    for _, group in result.loc[candidate_mask].groupby(grouping, dropna=False, sort=False):
        free_rows = group[group["_is_free_route"]]
        paid_rows = group[~group["_is_free_route"]]
        if free_rows.empty or paid_rows.empty:
            continue
        for free_index, free_row in free_rows.iterrows():
            duplicate = False
            for _, paid_row in paid_rows.iterrows():
                values_match = True
                for column in compare_columns:
                    left = pd.to_numeric(pd.Series([free_row.get(column)]), errors="coerce").iloc[0]
                    right = pd.to_numeric(pd.Series([paid_row.get(column)]), errors="coerce").iloc[0]
                    if pd.isna(left) and pd.isna(right):
                        continue
                    if pd.isna(left) or pd.isna(right) or not np.isclose(float(left), float(right), rtol=1e-9, atol=1e-6):
                        values_match = False
                        break
                if values_match:
                    duplicate = True
                    break
            if duplicate:
                drop_indices.add(free_index)
    if not drop_indices:
        return frame
    return result.drop(index=list(drop_indices)).drop(columns=["_is_free_route", "_base_model"])


@st.cache_data(ttl=3600, max_entries=12)
def build_openrouter_explorer_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    """Build compact, reusable frames for company, model, and catalog exploration."""
    catalog_views = compute_compute_availability_views(datasets)
    catalog = _prepare_explorer_catalog(catalog_views.get("models_latest", pd.DataFrame()))
    aliases = _catalog_alias_map(catalog)

    def dataset_frame(dataset_id: str) -> pd.DataFrame:
        result = datasets.get(dataset_id)
        return result.frame.copy() if result and not result.frame.empty else pd.DataFrame()

    provider_activity = _normalize_explorer_activity(dataset_frame("provider_daily_activity"), aliases)
    model_activity = _normalize_explorer_activity(
        _drop_known_model_activity_test_rows(dataset_frame("openrouter_model_activity")),
        aliases,
    )
    combined_activity = _combine_explorer_activity(provider_activity, model_activity)
    economics = dataset_frame("daily_provider_economics")
    if not economics.empty:
        economics["usage_date_dt"] = pd.to_datetime(economics.get("usage_date"), errors="coerce").dt.normalize()
        economics["provider_slug"] = economics.get("provider_slug", pd.Series(pd.NA, index=economics.index)).astype("string").str.lstrip("~").map(canonical_provider_slug)
        economics.loc[economics["provider_slug"].eq("meta"), "provider_name"] = "Meta"
        economics["total_tokens"] = pd.to_numeric(economics.get("total_tokens"), errors="coerce").fillna(0.0)
        economics["estimated_revenue"] = pd.to_numeric(economics.get("estimated_revenue"), errors="coerce")
        economics = economics.dropna(subset=["usage_date_dt", "provider_slug"]).copy()
    app_usage = _normalize_explorer_activity(dataset_frame("app_usage_daily"), aliases)
    app_metadata = dataset_frame("app_metadata_snapshots")
    metadata_columns = ["app_id", "scrape_date", "origin_url", "categories"]
    if not app_metadata.empty:
        app_metadata = app_metadata[[column for column in metadata_columns if column in app_metadata.columns]].copy()

    usage_30d = pd.DataFrame(columns=["model_id", "tokens_30d", "observed_days", "activity_source"])
    if not combined_activity.empty:
        latest_date = combined_activity["usage_date_dt"].max()
        recent = combined_activity[combined_activity["usage_date_dt"] >= latest_date - pd.Timedelta(days=29)]
        usage_30d = (
            recent.groupby("model_id", as_index=False)
            .agg(
                tokens_30d=("total_tokens", "sum"),
                observed_days=("usage_date_dt", "nunique"),
                activity_source=("activity_source", lambda values: " + ".join(sorted(set(values)))),
            )
        )
    catalog_with_usage = catalog.merge(usage_30d, on="model_id", how="left") if not catalog.empty else catalog
    if not catalog_with_usage.empty:
        catalog_with_usage["activity_source"] = catalog_with_usage["activity_source"].fillna("Not observed")
        catalog_with_usage["observed_days"] = catalog_with_usage["observed_days"].fillna(0).astype(int)

    return {
        "catalog": catalog_with_usage,
        "top_models": dataset_frame("top_models"),
        "provider_activity": provider_activity,
        "model_activity": model_activity,
        "combined_activity": combined_activity,
        "economics": economics,
        # The global top-model ranking is intentionally limited to ten rows;
        # use complete provider model activity for company weekly tokens and
        # the stacked model breakdown instead of implying that top-ranked
        # models are the company's full usage.
        "weekly_company_tokens": _weekly_company_tokens(provider_activity),
        "weekly_company_requests": _weekly_company_requests(dataset_frame("provider_weekly_requests")),
        "app_usage": app_usage,
        "app_metadata": app_metadata,
        "aliases": aliases,
        "catalog_history_start": catalog_views.get("models_history_start"),
        "catalog_history_end": catalog_views.get("models_history_end"),
    }


def _model_origin_slug(value: object) -> str | None:
    """Return the model creator/origin prefix, not a serving route."""
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().lstrip("~")
    prefix = text.split("/", 1)[0] if "/" in text else (text or None)
    return canonical_provider_slug(prefix)


def _weekly_company_tokens(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["usage_week", "company_slug", "tokens"])
    prepared = frame.copy()
    if {"usage_date_dt", "model_id", "total_tokens"}.issubset(prepared.columns):
        prepared["usage_week"] = pd.to_datetime(prepared["usage_date_dt"], errors="coerce")
        prepared["usage_week"] = prepared["usage_week"] - pd.to_timedelta(
            prepared["usage_week"].dt.weekday, unit="D"
        )
        prepared["company_slug"] = prepared["model_id"].map(_model_origin_slug)
        prepared["metric_value"] = pd.to_numeric(prepared["total_tokens"], errors="coerce")
    else:
        prepared["usage_week"] = pd.to_datetime(prepared.get("week_start_date"), errors="coerce")
        prepared["company_slug"] = prepared.get("parent_entity_id", pd.Series(pd.NA, index=prepared.index)).map(_model_origin_slug)
        fallback_company = prepared.get("entity_id", pd.Series(pd.NA, index=prepared.index)).map(_model_origin_slug)
        prepared["company_slug"] = prepared["company_slug"].fillna(fallback_company)
        prepared["metric_value"] = pd.to_numeric(prepared.get("metric_value"), errors="coerce")
    prepared = prepared.dropna(subset=["usage_week", "company_slug", "metric_value"])
    return (
        prepared.groupby(["usage_week", "company_slug"], as_index=False)["metric_value"]
        .sum()
        .rename(columns={"metric_value": "tokens"})
    )


def _weekly_company_requests(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["usage_week", "company_slug", "requests"])
    prepared = frame.copy()
    prepared["usage_week"] = pd.to_datetime(prepared.get("week_start_date"), errors="coerce")
    prepared["company_slug"] = prepared.get("entity_id", pd.Series(pd.NA, index=prepared.index)).map(_model_origin_slug)
    prepared["metric_value"] = pd.to_numeric(prepared.get("metric_value"), errors="coerce")
    prepared = prepared.dropna(subset=["usage_week", "company_slug", "metric_value"])
    return (
        prepared.groupby(["usage_week", "company_slug"], as_index=False)["metric_value"]
        .sum()
        .rename(columns={"metric_value": "requests"})
    )


def _weekly_company_model_pivot(frame: pd.DataFrame, company_slug: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    prepared = frame.copy()
    if {"usage_date_dt", "model_id", "total_tokens"}.issubset(prepared.columns):
        prepared["usage_week"] = pd.to_datetime(prepared["usage_date_dt"], errors="coerce")
        prepared["usage_week"] = prepared["usage_week"] - pd.to_timedelta(
            prepared["usage_week"].dt.weekday, unit="D"
        )
        prepared["company_slug"] = prepared["model_id"].map(_model_origin_slug)
        prepared["metric_value"] = pd.to_numeric(prepared["total_tokens"], errors="coerce")
        prepared["model_id"] = prepared["model_id"].astype("string")
    else:
        prepared["usage_week"] = pd.to_datetime(prepared.get("week_start_date"), errors="coerce")
        prepared["company_slug"] = prepared.get("parent_entity_id", pd.Series(pd.NA, index=prepared.index)).map(_model_origin_slug)
        fallback_company = prepared.get("entity_id", pd.Series(pd.NA, index=prepared.index)).map(_model_origin_slug)
        prepared["company_slug"] = prepared["company_slug"].fillna(fallback_company)
        prepared["metric_value"] = pd.to_numeric(prepared.get("metric_value"), errors="coerce")
        model_column = prepared.get("entity_id", pd.Series(pd.NA, index=prepared.index)).astype("string")
        prepared["model_id"] = model_column
    prepared = prepared.loc[prepared["company_slug"].eq(company_slug)].dropna(subset=["usage_week", "metric_value"])
    if prepared.empty:
        return pd.DataFrame()
    # Keep the historical chart, but choose the displayed model lines from
    # the latest trailing window. Ranking over the entire history can hide a
    # newly popular model behind a model that was dominant months ago.
    latest_date = prepared["usage_week"].max()
    recent = prepared[prepared["usage_week"] >= latest_date - pd.Timedelta(days=29)]
    ranking_frame = recent if not recent.empty else prepared
    leaders = ranking_frame.groupby("model_id")["metric_value"].sum().nlargest(8).index
    prepared["display_model"] = prepared["model_id"].where(prepared["model_id"].isin(leaders), "Other models")
    result = (
        prepared.pivot_table(index="usage_week", columns="display_model", values="metric_value", aggfunc="sum")
        .fillna(0)
        .sort_index()
    )
    return _regularize_company_pivot(result, "7D")


def _company_pivot(series: pd.Series, label: str) -> pd.DataFrame:
    if series.empty:
        return pd.DataFrame(columns=[label])
    prepared = pd.to_numeric(series, errors="coerce").rename(label).sort_index()
    prepared.index = pd.to_datetime(prepared.index, errors="coerce")
    prepared = prepared[prepared.index.notna()]
    valid = prepared.notna()
    if not valid.any():
        return pd.DataFrame(columns=[label])
    first_valid = valid[valid].index[0]
    last_valid = valid[valid].index[-1]
    return prepared.loc[first_valid:last_valid].to_frame()


def _regularize_company_pivot(frame: pd.DataFrame, frequency: str) -> pd.DataFrame:
    """Keep missing observation periods visible as gaps instead of connecting them."""
    if frame.empty:
        return frame
    index = pd.to_datetime(frame.index, errors="coerce")
    valid_index = index[index.notna()]
    if valid_index.empty:
        return frame
    result = frame.copy()
    result.index = index
    full_index = pd.date_range(valid_index.min(), valid_index.max(), freq=frequency)
    return result.reindex(full_index)


def _clip_company_pivot_start(frame: pd.DataFrame, start_date: pd.Timestamp) -> pd.DataFrame:
    """Show a company series from a consistent floor while preserving leading gaps."""
    if frame.empty:
        return frame
    index = pd.to_datetime(frame.index, errors="coerce")
    valid_index = index[index.notna()]
    if valid_index.empty:
        return frame
    start = pd.Timestamp(start_date)
    end = valid_index.max()
    if end < start:
        return frame.iloc[0:0]
    result = frame.copy()
    result.index = index
    full_index = pd.date_range(start, end, freq="D")
    return result.reindex(full_index)


def _daily_series_to_weekly(series: pd.Series, label: str) -> pd.Series:
    """Aggregate a daily company series to Monday-starting weekly totals."""
    if series.empty:
        return pd.Series(dtype="float64", name=label)
    prepared = pd.to_numeric(series, errors="coerce").copy()
    prepared.index = pd.to_datetime(prepared.index, errors="coerce")
    prepared = prepared[prepared.index.notna()]
    if prepared.empty:
        return pd.Series(dtype="float64", name=label)
    week_index = prepared.index - pd.to_timedelta(prepared.index.weekday, unit="D")
    return prepared.groupby(week_index).sum(min_count=1).rename(label).sort_index()


def _weekly_company_price(economics: pd.DataFrame, company_slug: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    if economics.empty or "provider_slug" not in economics.columns:
        return pd.DataFrame(columns=["Realized Price"]), pd.DataFrame(columns=["Priced Token Coverage"])
    rows = economics[economics["provider_slug"].astype("string").eq(company_slug)].copy()
    if rows.empty:
        return pd.DataFrame(columns=["Realized Price"]), pd.DataFrame(columns=["Priced Token Coverage"])
    rows["usage_week"] = rows["usage_date_dt"] - pd.to_timedelta(rows["usage_date_dt"].dt.weekday, unit="D")
    rows["priced_tokens"] = rows["total_tokens"].where(rows["estimated_revenue"].notna(), 0.0)
    grouped = rows.groupby("usage_week", as_index=True).agg(
        revenue=("estimated_revenue", "sum"),
        priced_tokens=("priced_tokens", "sum"),
        total_tokens=("total_tokens", "sum"),
    )
    price = grouped["revenue"].div(grouped["priced_tokens"].where(grouped["priced_tokens"].gt(0))).mul(1_000_000)
    coverage = grouped["priced_tokens"].div(grouped["total_tokens"].where(grouped["total_tokens"].gt(0))).mul(100)
    return _company_pivot(price, "Realized Price"), _company_pivot(coverage, "Priced Token Coverage")


def company_explorer_state(views: dict[str, object], provider_slug: str) -> dict[str, object]:
    catalog = views.get("catalog", pd.DataFrame())
    activity = views.get("combined_activity", pd.DataFrame())
    if activity is None or activity.empty:
        activity = _combine_explorer_activity(
            views.get("provider_activity", pd.DataFrame()),
            views.get("model_activity", pd.DataFrame()),
        )
    activity = activity.copy()
    if not activity.empty:
        activity["company_slug"] = activity["model_id"].map(_model_origin_slug)
    company_models = catalog[catalog["provider_slug"] == provider_slug].copy() if not catalog.empty else pd.DataFrame()
    company_activity = activity[activity["company_slug"].eq(provider_slug)].copy() if not activity.empty else pd.DataFrame()
    if not company_activity.empty and not company_models.empty:
        company_activity = company_activity[company_activity["model_id"].isin(company_models["model_id"])].copy()

    daily_total = pd.DataFrame()
    model_pivot = pd.DataFrame()
    if not company_activity.empty:
        daily_total = company_activity.groupby("usage_date_dt")["total_tokens"].sum().to_frame("Tokens").sort_index()
        # Select the model stack using trailing 30-day volume, while retaining
        # all available dates in the chart for historical context.
        latest_date = company_activity["usage_date_dt"].max()
        recent_activity = company_activity[
            company_activity["usage_date_dt"] >= latest_date - pd.Timedelta(days=29)
        ]
        ranking_frame = recent_activity if not recent_activity.empty else company_activity
        leaders = ranking_frame.groupby("model_id")["total_tokens"].sum().nlargest(8).index
        chart_rows = company_activity.copy()
        chart_rows["display_model"] = chart_rows["model_id"].where(chart_rows["model_id"].isin(leaders), "Other models")
        model_pivot = (
            chart_rows.pivot_table(index="usage_date_dt", columns="display_model", values="total_tokens", aggfunc="sum")
            .fillna(0)
            .sort_index()
        )

    model_activity = views.get("model_activity", pd.DataFrame())
    requests_daily = pd.DataFrame(columns=["Requests"])
    daily_request_proxy = False
    if not model_activity.empty:
        detail = model_activity.copy()
        detail["is_complete_total"] = detail["category_slug"].astype("string").str.casefold().eq("all")
        detail["company_slug"] = detail["model_id"].map(_model_origin_slug)
        detail = detail[detail["company_slug"].eq(provider_slug)]
        if not company_models.empty:
            detail = detail[detail["model_id"].isin(company_models["model_id"])]
        if not detail.empty:
            request_rows: list[dict[str, object]] = []
            for usage_date, day_rows in detail.groupby("usage_date_dt"):
                complete_rows = day_rows[day_rows["is_complete_total"]]
                selected_rows = complete_rows if not complete_rows.empty else day_rows
                if complete_rows.empty:
                    daily_request_proxy = True
                request_rows.append({
                    "usage_date_dt": usage_date,
                    "Requests": selected_rows["request_count"].sum(),
                })
            requests_daily = pd.DataFrame(request_rows).set_index("usage_date_dt").sort_index()
            requests_daily = requests_daily.loc[requests_daily.index >= COMPANY_DAILY_START_DATE]

    daily_ratio = pd.concat([
        daily_total.get("Tokens", pd.Series(dtype="float64", name="Tokens")),
        requests_daily.get("Requests", pd.Series(dtype="float64", name="Requests")),
    ], axis=1)
    if not daily_ratio.empty:
        daily_ratio["Tokens / Request"] = daily_ratio["Tokens"].div(daily_ratio["Requests"].where(daily_ratio["Requests"].gt(0)))
    economics = views.get("economics", pd.DataFrame())
    price_daily = pd.DataFrame(columns=["Realized Price"])
    coverage_daily = pd.DataFrame(columns=["Priced Token Coverage"])
    historical_pricing_coverage = None
    historical_price_fill_share = None
    if not economics.empty:
        rows = economics[economics["provider_slug"].astype("string").eq(provider_slug)].copy()
        rows["priced_tokens"] = rows["total_tokens"].where(rows["estimated_revenue"].notna(), 0.0)
        total_tokens = pd.to_numeric(rows["total_tokens"], errors="coerce").sum()
        priced_tokens = pd.to_numeric(rows["priced_tokens"], errors="coerce").sum()
        if total_tokens > 0:
            historical_pricing_coverage = float(priced_tokens / total_tokens * 100)
            historical_fill_tokens = pd.to_numeric(
                rows.loc[
                    rows.get(
                        "pricing_join_status",
                        pd.Series("", index=rows.index),
                    ).astype("string").eq("historical_route_price_fill"),
                    "total_tokens",
                ],
                errors="coerce",
            ).sum()
            historical_price_fill_share = float(historical_fill_tokens / total_tokens * 100)
        grouped = rows.groupby("usage_date_dt", as_index=True).agg(
            revenue=("estimated_revenue", "sum"),
            priced_tokens=("priced_tokens", "sum"),
            total_tokens=("total_tokens", "sum"),
        )
        price_daily = _company_pivot(
            grouped["revenue"].div(grouped["priced_tokens"].where(grouped["priced_tokens"].gt(0))).mul(1_000_000),
            "Realized Price",
        )
        coverage_daily = _company_pivot(
            grouped["priced_tokens"].div(grouped["total_tokens"].where(grouped["total_tokens"].gt(0))).mul(100),
            "Priced Token Coverage",
        )

    weekly_tokens = views.get("weekly_company_tokens", pd.DataFrame())
    weekly_requests = views.get("weekly_company_requests", pd.DataFrame())
    weekly_tokens_series = (
        weekly_tokens[weekly_tokens["company_slug"].eq(provider_slug)].set_index("usage_week")["tokens"]
        if not weekly_tokens.empty else pd.Series(dtype="float64")
    )
    weekly_requests_series = (
        weekly_requests[weekly_requests["company_slug"].eq(provider_slug)].set_index("usage_week")["requests"]
        if not weekly_requests.empty else pd.Series(dtype="float64")
    )
    weekly_token_source = "No weekly token history"
    weekly_request_source = "No weekly request history"
    if not weekly_tokens_series.empty:
        weekly_token_source = "Provider daily model activity aggregated to weekly totals"
    if not weekly_requests_series.empty:
        weekly_request_source = "Provider weekly request feed"
    if weekly_tokens_series.empty and not daily_total.empty:
        weekly_tokens_series = _daily_series_to_weekly(daily_total["Tokens"], "tokens")
        weekly_token_source = "Daily activity aggregated to weekly totals"
    if weekly_requests_series.empty and not requests_daily.empty:
        weekly_requests_series = _daily_series_to_weekly(requests_daily["Requests"], "requests")
        weekly_request_source = "Daily model activity aggregated to weekly totals"
    weekly_ratio = pd.concat([weekly_tokens_series.rename("Tokens"), weekly_requests_series.rename("Requests")], axis=1)
    if not weekly_ratio.empty:
        weekly_ratio["Tokens / Request"] = weekly_ratio["Tokens"].div(weekly_ratio["Requests"].where(weekly_ratio["Requests"].gt(0)))
    weekly_price, weekly_coverage = _weekly_company_price(economics, provider_slug)
    weekly_model_pivot = _weekly_company_model_pivot(
        views.get("provider_activity", pd.DataFrame()), provider_slug
    )

    company_models = company_models.sort_values(["tokens_30d", "model_name"], ascending=[False, True]) if not company_models.empty else company_models
    return {
        "catalog": company_models,
        "daily_total": daily_total,
        "model_pivot": model_pivot,
        "weekly_model_pivot": weekly_model_pivot,
        "daily_metrics": {
            "Tokens": _regularize_company_pivot(daily_total, "D"),
            "Requests": _clip_company_pivot_start(_regularize_company_pivot(requests_daily, "D"), COMPANY_DAILY_START_DATE),
            "Tokens / Request": _clip_company_pivot_start(_regularize_company_pivot(_company_pivot(daily_ratio.get("Tokens / Request", pd.Series(dtype="float64")), "Tokens / Request"), "D"), COMPANY_DAILY_START_DATE),
            "Realized Price": _clip_company_pivot_start(_regularize_company_pivot(price_daily, "D"), COMPANY_DAILY_START_DATE),
        },
        "weekly_metrics": {
            "Tokens": _regularize_company_pivot(_company_pivot(weekly_tokens_series, "Tokens"), "7D"),
            "Requests": _regularize_company_pivot(_company_pivot(weekly_requests_series, "Requests"), "7D"),
            "Tokens / Request": _regularize_company_pivot(_company_pivot(weekly_ratio.get("Tokens / Request", pd.Series(dtype="float64")), "Tokens / Request"), "7D"),
            "Realized Price": _regularize_company_pivot(weekly_price, "7D"),
        },
        "price_coverage_daily": _clip_company_pivot_start(_regularize_company_pivot(coverage_daily, "D"), COMPANY_DAILY_START_DATE),
        "price_coverage_weekly": weekly_coverage,
        "historical_pricing_coverage": historical_pricing_coverage,
        "historical_price_fill_share": historical_price_fill_share,
        "total_tokens": float(company_activity["total_tokens"].sum()) if not company_activity.empty else 0.0,
        "latest_date": company_activity["usage_date_dt"].max() if not company_activity.empty else None,
        "daily_request_start": requests_daily.index.min() if not requests_daily.empty else None,
        "daily_request_proxy": daily_request_proxy,
        "weekly_token_source": weekly_token_source,
        "weekly_request_source": weekly_request_source,
    }


def model_explorer_state(views: dict[str, object], model_id: str) -> dict[str, object]:
    catalog = views.get("catalog", pd.DataFrame())
    combined_activity = views.get("combined_activity", pd.DataFrame())
    model_activity = views.get("model_activity", pd.DataFrame())
    if combined_activity is None or combined_activity.empty:
        combined_activity = _combine_explorer_activity(
            views.get("provider_activity", pd.DataFrame()), model_activity,
        )
    app_usage = views.get("app_usage", pd.DataFrame())
    app_metadata = views.get("app_metadata", pd.DataFrame())

    info = catalog[catalog["model_id"] == model_id].head(1) if not catalog.empty else pd.DataFrame()
    token_rows = combined_activity[combined_activity["model_id"] == model_id].copy() if not combined_activity.empty else pd.DataFrame()
    detail_rows = model_activity[model_activity["model_id"] == model_id].copy() if not model_activity.empty else pd.DataFrame()

    activity = pd.DataFrame()
    request_granularity = "unavailable"
    if not token_rows.empty or not detail_rows.empty:
        tokens = token_rows.groupby("usage_date_dt")["total_tokens"].sum().rename("Tokens") if not token_rows.empty else pd.Series(dtype="float64")
        requests = pd.Series(dtype="float64")
        if not detail_rows.empty:
            request_dates = pd.to_datetime(detail_rows["usage_date_dt"], errors="coerce").dropna().dt.normalize()
            token_dates = pd.to_datetime(token_rows["usage_date_dt"], errors="coerce").dropna().dt.normalize()
            request_granularity = "daily"
            has_complete_all_category = (
                "category_slug" in detail_rows.columns
                and detail_rows["category_slug"].astype("string").str.casefold().eq("all").any()
            )
            if not request_dates.empty and has_complete_all_category:
                token_day_count = token_dates.nunique()
                request_day_count = request_dates.nunique()
                coverage = request_day_count / token_day_count if token_day_count else 1.0
                if token_day_count and coverage < 0.75:
                    request_weeks = request_dates - pd.to_timedelta(request_dates.dt.weekday, unit="D")
                    requests = detail_rows.assign(_request_week=request_weeks).groupby("_request_week")["request_count"].sum().rename("Requests")
                    request_granularity = "weekly"
                else:
                    requests = detail_rows.assign(_request_date=request_dates).groupby("_request_date")["request_count"].sum().rename("Requests")
            elif not request_dates.empty:
                # Category splits are the only request detail available for
                # some historical snapshots; keep them daily rather than
                # inventing a weekly fallback intended for complete totals.
                requests = detail_rows.assign(_request_date=request_dates).groupby("_request_date")["request_count"].sum().rename("Requests")
        activity = pd.concat([tokens, requests], axis=1).sort_index()

    categories = pd.DataFrame()
    if not detail_rows.empty:
        categories = (
            detail_rows.groupby("category_slug", as_index=False)
            .agg(Tokens=("total_tokens", "sum"), Requests=("request_count", "sum"))
            .sort_values("Tokens", ascending=False)
        )

    apps = pd.DataFrame()
    if not app_usage.empty:
        apps = (
            app_usage[app_usage["model_id"] == model_id]
            .groupby(["app_id", "app_name"], dropna=False, as_index=False)["total_tokens"]
            .sum()
            .rename(columns={"app_name": "App", "total_tokens": "Tokens"})
            .sort_values("Tokens", ascending=False)
        )
        if not apps.empty and not app_metadata.empty:
            latest_metadata = app_metadata.sort_values("scrape_date").drop_duplicates("app_id", keep="last")
            apps = apps.merge(latest_metadata[["app_id", "origin_url", "categories"]], on="app_id", how="left")

    return {
        "info": info,
        "activity": activity,
        "request_granularity": request_granularity,
        "categories": categories,
        "apps": apps,
        "total_tokens": float(token_rows["total_tokens"].sum()) if not token_rows.empty else 0.0,
        "total_requests": float(detail_rows["request_count"].sum()) if not detail_rows.empty else 0.0,
    }


# --- OpenRouter comparison view -------------------------------------------------
# The comparison tab deliberately builds compact long-form frames from the same
# reconciled inputs as the explorer.  It does not create another stored dataset.
COMPARISON_METRICS = (
    "Tokens",
    "Requests",
    "Estimated revenue",
    "Tokens / request",
    "Realized price",
)
COMPARISON_WINDOWS = ("Daily", "7-day avg", "Weekly", "Monthly")
COMPARISON_REQUEST_INTERPOLATION_CUTOFF = pd.Timestamp("2026-01-01")


def _comparison_period_start(values: pd.Series, window: str) -> pd.Series:
    dates = pd.to_datetime(values, errors="coerce").dt.normalize()
    if window == "Daily":
        return dates
    if window == "Monthly":
        return dates.dt.to_period("M").dt.to_timestamp()
    return dates - pd.to_timedelta(dates.dt.weekday, unit="D")


def _comparison_rolling_7d_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Build calendar-day trailing seven-day averages from the daily company frame.

    Volume and revenue metrics use a trailing daily mean. Tokens/request uses
    the ratio of trailing token and request sums, which keeps it request-weighted
    instead of averaging noisy daily ratios. Realized price is the trailing mean
    of the displayed daily realized-price observations.
    """
    columns = [
        "period_start", "entity_id", "Tokens", "Requests", "Estimated revenue",
        "Tokens / request", "Realized price",
    ]
    if frame.empty or not {"period_start", "entity_id"}.issubset(frame.columns):
        return pd.DataFrame(columns=columns)
    prepared = frame.copy()
    prepared["period_start"] = pd.to_datetime(prepared["period_start"], errors="coerce").dt.normalize()
    prepared["entity_id"] = prepared["entity_id"].astype("string")
    prepared = prepared.dropna(subset=["period_start", "entity_id"])
    if prepared.empty:
        return pd.DataFrame(columns=columns)

    rows: list[pd.DataFrame] = []
    metric_columns = ["Tokens", "Requests", "Estimated revenue", "Realized price"]
    for entity_id, group in prepared.groupby("entity_id", sort=False):
        indexed = (
            group.sort_values("period_start")
            .drop_duplicates("period_start", keep="last")
            .set_index("period_start")
        )
        full_index = pd.date_range(indexed.index.min(), indexed.index.max(), freq="D")
        indexed = indexed.reindex(full_index)
        rolling = pd.DataFrame(index=full_index)
        for column in metric_columns:
            if column in indexed.columns:
                rolling[column] = pd.to_numeric(indexed[column], errors="coerce").rolling(7, min_periods=1).mean()
            else:
                rolling[column] = np.nan
        token_values = pd.to_numeric(
            indexed.get("Tokens", pd.Series(np.nan, index=indexed.index)), errors="coerce"
        )
        request_values = pd.to_numeric(
            indexed.get("Requests", pd.Series(np.nan, index=indexed.index)), errors="coerce"
        )
        # Tokens and requests do not necessarily start on the same day.  Do
        # not let token-only days inflate the numerator while the denominator
        # is still sparse (for example, provider tokens begin before daily
        # request coverage).  The ratio is valid only on overlapping,
        # positive-request observations.
        valid_ratio_days = token_values.notna() & request_values.notna() & request_values.gt(0)
        token_sum = token_values.where(valid_ratio_days).rolling(7, min_periods=1).sum()
        request_sum = request_values.where(valid_ratio_days).rolling(7, min_periods=1).sum()
        rolling["Tokens / request"] = token_sum.div(request_sum.where(request_sum.gt(0)))
        rolling["period_start"] = full_index
        rolling["entity_id"] = entity_id
        rows.append(rolling.reset_index(drop=True))
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.concat(rows, ignore_index=True).reindex(columns=columns)


def _comparison_empty_rows(value_name: str = "value") -> pd.DataFrame:
    return pd.DataFrame(columns=["period_start", "entity_id", value_name])


def _comparison_first_week_coverage(
    frame: pd.DataFrame,
    *,
    date_column: str,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None, int]:
    """Return the first observed week, first complete week, and observed days."""
    if frame.empty or date_column not in frame.columns:
        return None, None, 0
    dates = pd.to_datetime(frame[date_column], errors="coerce").dt.normalize().dropna()
    if dates.empty:
        return None, None, 0
    first_date = dates.min()
    first_week = first_date - pd.Timedelta(days=int(first_date.weekday()))
    observed_days = int(dates[dates < first_week + pd.Timedelta(days=7)].nunique())
    first_complete_week = first_week if observed_days >= 7 else first_week + pd.Timedelta(days=7)
    return first_week, first_complete_week, observed_days


def _comparison_periodize(
    frame: pd.DataFrame,
    *,
    date_column: str,
    entity_column: str = "entity_id",
    value_column: str = "value",
    window: str,
    output_column: str = "value",
) -> pd.DataFrame:
    if frame.empty or not {date_column, entity_column, value_column}.issubset(frame.columns):
        return _comparison_empty_rows(output_column)
    prepared = frame[[date_column, entity_column, value_column]].copy()
    prepared["period_start"] = _comparison_period_start(prepared[date_column], window)
    prepared["entity_id"] = prepared[entity_column].astype("string")
    prepared[output_column] = pd.to_numeric(prepared[value_column], errors="coerce")
    prepared = prepared.dropna(subset=["period_start", "entity_id", output_column])
    if prepared.empty:
        return _comparison_empty_rows(output_column)
    return (
        prepared.groupby(["period_start", "entity_id"], as_index=False)[output_column]
        .sum(min_count=1)
        .sort_values(["period_start", "entity_id"])
    )


def _comparison_weekly_rankings(
    frame: pd.DataFrame,
    *,
    date_column: str,
    entity_column: str,
    value_column: str,
    entity_mapper,
    sunday_alignment: bool = False,
    exclude_other_entities: bool = True,
) -> pd.DataFrame:
    """Select one coherent weekly ranking snapshot per week before aggregating.

    Rankings histories can contain a Sunday and Monday copy of the same bucket,
    or several scraper runs for one week.  Selecting the most complete/latest
    snapshot first prevents the comparison from multiplying old token or request
    history when sources overlap.
    """
    if frame.empty or not {date_column, entity_column, value_column}.issubset(frame.columns):
        return _comparison_empty_rows()
    work = frame.copy()
    original = pd.to_datetime(work[date_column], errors="coerce").dt.normalize()
    work["_original_date"] = original
    if sunday_alignment:
        work["period_start"] = pd.to_datetime(
            _align_rankings_week_to_monday(work[date_column].astype("string")), errors="coerce"
        )
    else:
        work["period_start"] = original - pd.to_timedelta(original.dt.weekday, unit="D")
    work["entity_id"] = work[entity_column].map(entity_mapper).astype("string")
    work["value"] = pd.to_numeric(work[value_column], errors="coerce")
    work = work.dropna(subset=["period_start", "entity_id", "value"])
    if exclude_other_entities:
        work = work[~work["entity_id"].str.casefold().isin({"others", "other", "nan", "none"})]
    if work.empty:
        return _comparison_empty_rows()

    if "source_run_id" in work.columns:
        work["_snapshot_id"] = work["source_run_id"].astype("string").fillna("")
        work["_snapshot_at"] = pd.to_datetime(work.get("scraped_at"), errors="coerce")
        work["_is_sunday_snapshot"] = work["_original_date"].dt.weekday.eq(6).astype(int)
        choices = (
            work.groupby(["period_start", "_snapshot_id"], as_index=False)
            .agg(
                _snapshot_rows=("value", "size"),
                _snapshot_sunday_rows=("_is_sunday_snapshot", "sum"),
                _snapshot_at=("_snapshot_at", "max"),
            )
            .sort_values(
                ["period_start", "_snapshot_rows", "_snapshot_sunday_rows", "_snapshot_at", "_snapshot_id"],
                ascending=[True, False, False, False, False],
            )
            .drop_duplicates("period_start", keep="first")
        )
        work = work.merge(choices[["period_start", "_snapshot_id"]],
                          on=["period_start", "_snapshot_id"], how="inner")

    if sunday_alignment and not work.empty:
        work["_is_aligned_monday"] = (
            work["_original_date"].dt.strftime("%Y-%m-%d")
            == work["period_start"].dt.strftime("%Y-%m-%d")
        )
        preferred_dates = (
            work.sort_values(["period_start", "_is_aligned_monday", "_original_date"],
                             ascending=[True, False, False])
            .drop_duplicates("period_start", keep="first")
            [["period_start", "_original_date"]]
        )
        work = work.merge(preferred_dates, on=["period_start", "_original_date"], how="inner")

    return (
        work.groupby(["period_start", "entity_id"], as_index=False)["value"]
        .sum(min_count=1)
        .sort_values(["period_start", "entity_id"])
    )


def _comparison_merge_sources(
    legacy: pd.DataFrame,
    modern: pd.DataFrame,
    *,
    prefer_modern: bool,
) -> pd.DataFrame:
    """Union two already-aggregated series without adding overlapping rows."""
    parts: list[pd.DataFrame] = []
    if not legacy.empty:
        left = legacy[["period_start", "entity_id", "value"]].copy()
        left["_priority"] = 1 if not prefer_modern else 0
        parts.append(left)
    if not modern.empty:
        right = modern[["period_start", "entity_id", "value"]].copy()
        right["_priority"] = 0 if not prefer_modern else 1
        parts.append(right)
    if not parts:
        return _comparison_empty_rows()
    combined = pd.concat(parts, ignore_index=True)
    return (
        combined.sort_values(["period_start", "entity_id", "_priority"])
        .drop_duplicates(["period_start", "entity_id"], keep="last")
        .drop(columns="_priority")
        .sort_values(["period_start", "entity_id"])
        .reset_index(drop=True)
    )


def _comparison_interpolate_internal_weekly_request_gaps(
    frame: pd.DataFrame,
    *,
    cutoff: pd.Timestamp = COMPARISON_REQUEST_INTERPOLATION_CUTOFF,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Fill only isolated, pre-2026 gaps in the legacy request ranking feed.

    ``provider_weekly_requests`` is a top-10 ranking, so an absent provider is
    normally a real *coverage* limitation rather than a zero.  The one-week
    holes below are the narrow exception: when a provider is observed in the
    adjacent weeks, a midpoint is a useful display estimate.  We keep this
    transformation in the derived comparison view (the source parquet remains
    untouched), never extrapolate leading/trailing or multi-week gaps, and
    return metadata so the UI can label the estimates explicitly.
    """
    if frame.empty or not {"period_start", "entity_id", "value"}.issubset(frame.columns):
        return frame.copy(), []

    prepared = frame[["period_start", "entity_id", "value"]].copy()
    prepared["period_start"] = pd.to_datetime(prepared["period_start"], errors="coerce").dt.normalize()
    prepared["entity_id"] = prepared["entity_id"].astype("string")
    prepared["value"] = pd.to_numeric(prepared["value"], errors="coerce")
    prepared = prepared.dropna(subset=["period_start", "entity_id", "value"])
    if prepared.empty:
        return prepared, []

    additions: list[dict[str, object]] = []
    for entity_id, group in prepared.groupby("entity_id", sort=False):
        values = (
            group.groupby("period_start", as_index=True)["value"]
            .sum(min_count=1)
            .sort_index()
        )
        if len(values) < 2:
            continue
        full_weeks = pd.date_range(values.index.min(), values.index.max(), freq="7D")
        for period_start in full_weeks.difference(values.index):
            if period_start >= cutoff:
                continue
            previous = period_start - pd.Timedelta(days=7)
            following = period_start + pd.Timedelta(days=7)
            # Immediate neighbours are required.  This deliberately excludes
            # two-or-more-week runs of missing source observations.
            if previous not in values.index or following not in values.index:
                continue
            previous_value = float(values.loc[previous])
            following_value = float(values.loc[following])
            estimate = (previous_value + following_value) / 2.0
            additions.append({
                "period_start": period_start,
                "entity_id": entity_id,
                "value": estimate,
            })

    if not additions:
        return prepared.sort_values(["period_start", "entity_id"]).reset_index(drop=True), []

    interpolated = pd.concat([prepared, pd.DataFrame(additions)], ignore_index=True)
    interpolated = (
        interpolated.drop_duplicates(["period_start", "entity_id"], keep="first")
        .sort_values(["period_start", "entity_id"])
        .reset_index(drop=True)
    )
    notes = [
        {
            **row,
            "previous_period": row["period_start"] - pd.Timedelta(days=7),
            "following_period": row["period_start"] + pd.Timedelta(days=7),
        }
        for row in additions
    ]
    return interpolated, notes


def _comparison_model_activity_requests(model_activity: pd.DataFrame) -> pd.DataFrame:
    """Return daily request totals, preferring complete `all` rows per model/day."""
    if model_activity.empty:
        return _comparison_empty_rows()
    detail = _drop_identical_route_alias_rows(model_activity.copy())
    required = {"usage_date_dt", "model_id", "category_slug", "request_count"}
    if not required.issubset(detail.columns):
        return _comparison_empty_rows()
    detail["request_count"] = pd.to_numeric(detail["request_count"], errors="coerce")
    detail = detail.dropna(subset=["usage_date_dt", "model_id", "request_count"])
    if detail.empty:
        return _comparison_empty_rows()
    detail["_is_complete"] = detail["category_slug"].astype("string").str.casefold().eq("all")
    keys = detail.loc[detail["_is_complete"], ["usage_date_dt", "model_id"]].drop_duplicates()
    keys["_has_complete"] = True
    detail = detail.merge(keys, on=["usage_date_dt", "model_id"], how="left")
    has_complete = detail["_has_complete"].astype("boolean").fillna(False).astype(bool)
    selected = detail[(has_complete & detail["_is_complete"]) | ~has_complete].copy()
    return (
        selected.groupby(["usage_date_dt", "model_id"], as_index=False)["request_count"]
        .sum(min_count=1)
        .rename(columns={"usage_date_dt": "date", "model_id": "entity_id", "request_count": "value"})
    )


def _comparison_score_lookup(datasets: dict[str, DatasetLoadResult], catalog: pd.DataFrame) -> dict[str, dict[str, object]]:
    result = datasets.get("artificial_analysis_models_daily")
    if not result or result.frame.empty or catalog.empty:
        return {}
    scores = result.frame.copy()
    scores["as_of_date"] = pd.to_datetime(scores.get("as_of_date"), errors="coerce")
    scores["intelligence_index"] = pd.to_numeric(scores.get("intelligence_index"), errors="coerce")
    scores = scores.dropna(subset=["as_of_date", "model_id", "intelligence_index"])
    if scores.empty:
        return {}
    latest_date = scores["as_of_date"].max()
    latest = scores[scores["as_of_date"].eq(latest_date)].copy()
    by_aa_id = latest.set_index(latest["model_id"].astype("string"))
    route_to_aa: dict[str, str] = {}
    try:
        capability_map = load_capability_map(Path(__file__).resolve().parents[2])
        for entry in capability_map.entries:
            for route in entry.openrouter_routes:
                route_to_aa[route.model_id] = entry.aa_model_id
    except (OSError, ValueError):
        route_to_aa = {}

    lookup: dict[str, dict[str, object]] = {}
    for model_id in catalog["model_id"].dropna().astype(str).unique():
        candidates = [model_id, model_id.replace(":free", ""), model_id.replace(":thinking", "")]
        aa_id = next((route_to_aa.get(candidate) for candidate in candidates if route_to_aa.get(candidate)), None)
        row = by_aa_id.loc[aa_id] if aa_id is not None and aa_id in by_aa_id.index else None
        if row is None:
            continue
        if isinstance(row, pd.DataFrame):
            row = row.sort_values("intelligence_index", ascending=False).iloc[0]
        lookup[model_id] = {
            "score": float(row["intelligence_index"]),
            "as_of_date": pd.Timestamp(latest_date),
            "model_name": str(row.get("model_name", "")),
            "match_status": "exact curated route",
        }
    return lookup


def _comparison_metric_frame(
    tokens: pd.DataFrame,
    requests: pd.DataFrame,
    economics: pd.DataFrame,
) -> pd.DataFrame:
    columns = ["period_start", "entity_id", "Tokens", "Requests", "Estimated revenue", "Tokens / request", "Realized price"]
    parts: list[pd.DataFrame] = []
    for frame, column in ((tokens, "Tokens"), (requests, "Requests")):
        if not frame.empty:
            parts.append(frame.rename(columns={"value": column})[["period_start", "entity_id", column]])
    if not economics.empty:
        econ = economics.rename(columns={"revenue": "Estimated revenue", "priced_tokens": "_priced_tokens"})
        parts.append(econ[["period_start", "entity_id", "Estimated revenue", "_priced_tokens"]])
    if not parts:
        return pd.DataFrame(columns=columns)
    merged = parts[0]
    for part in parts[1:]:
        merged = merged.merge(part, on=["period_start", "entity_id"], how="outer")
    if "_priced_tokens" not in merged:
        merged["_priced_tokens"] = np.nan
    merged["Tokens / request"] = merged["Tokens"].div(merged["Requests"].where(merged["Requests"].gt(0)))
    merged["Realized price"] = merged["Estimated revenue"].div(
        merged["_priced_tokens"].where(merged["_priced_tokens"].gt(0))
    ).mul(1_000_000)
    return merged.reindex(columns=columns).sort_values(["period_start", "entity_id"]).reset_index(drop=True)


@st.cache_data(ttl=3600, max_entries=8)
def build_openrouter_comparison_views(
    datasets: dict[str, DatasetLoadResult],
    *,
    cache_version: str = OPENROUTER_COMPARISON_CACHE_VERSION,
) -> dict[str, object]:
    """Build compact company/model comparison frames with old/new source precedence."""
    _ = cache_version
    explorer = build_openrouter_explorer_views(datasets)
    aliases = explorer.get("aliases", {})

    def normalize_model(value: object) -> str | None:
        if value is None or pd.isna(value):
            return None
        raw = str(value).strip()
        mapped = aliases.get(raw)
        if mapped:
            return str(mapped)
        base = re.sub(r":(?:free|thinking|beta|online)$", "", raw)
        return str(aliases.get(base, raw))

    activity = explorer.get("combined_activity", pd.DataFrame()).copy()
    if not activity.empty:
        activity["usage_date_dt"] = pd.to_datetime(activity["usage_date_dt"], errors="coerce").dt.normalize()
        activity["model_id"] = activity["model_id"].map(normalize_model)
        activity["company_id"] = activity["model_id"].map(_model_origin_slug)
        activity["total_tokens"] = pd.to_numeric(activity["total_tokens"], errors="coerce")
        activity = activity.dropna(subset=["usage_date_dt", "model_id", "total_tokens"])

    provider_activity = explorer.get("provider_activity", pd.DataFrame())
    provider_first_week, provider_complete_week, provider_first_week_days = _comparison_first_week_coverage(
        provider_activity,
        date_column="usage_date_dt",
    )
    model_activity = explorer.get("model_activity", pd.DataFrame())
    complete_model_activity = (
        model_activity[
            model_activity.get("category_slug", pd.Series(pd.NA, index=model_activity.index))
            .astype("string").str.casefold().eq("all")
        ]
        if not model_activity.empty else pd.DataFrame()
    )
    complete_model_first_date = (
        pd.to_datetime(complete_model_activity["usage_date_dt"], errors="coerce").dt.normalize().min()
        if not complete_model_activity.empty else None
    )
    complete_model_week = (
        complete_model_first_date - pd.Timedelta(days=int(complete_model_first_date.weekday()))
        if complete_model_first_date is not None and pd.notna(complete_model_first_date) else None
    )

    modern_model_tokens = (
        activity.groupby(["usage_date_dt", "model_id"], as_index=False)["total_tokens"].sum()
        .rename(columns={"usage_date_dt": "date", "model_id": "entity_id", "total_tokens": "value"})
        if not activity.empty else _comparison_empty_rows()
    )
    modern_company_tokens = modern_model_tokens.copy()
    if not modern_company_tokens.empty:
        modern_company_tokens["entity_id"] = modern_company_tokens["entity_id"].map(_model_origin_slug)
        modern_company_tokens = modern_company_tokens.groupby(["date", "entity_id"], as_index=False)["value"].sum()

    model_requests_daily = _comparison_model_activity_requests(explorer.get("model_activity", pd.DataFrame()))
    if not model_requests_daily.empty:
        model_requests_daily["entity_id"] = model_requests_daily["entity_id"].map(normalize_model)
        model_requests_daily = model_requests_daily.dropna(subset=["entity_id"])
    company_requests_daily = model_requests_daily.copy()
    if not company_requests_daily.empty:
        company_requests_daily["entity_id"] = company_requests_daily["entity_id"].map(_model_origin_slug)
        company_requests_daily = company_requests_daily.groupby(["date", "entity_id"], as_index=False)["value"].sum()

    market = datasets.get("market_share")
    market_frame = market.frame.copy() if market and not market.frame.empty else pd.DataFrame()
    legacy_company_tokens = _comparison_weekly_rankings(
        market_frame, date_column="week_start_date", entity_column="entity_id", value_column="metric_value",
        entity_mapper=lambda value: canonical_provider_slug(value), sunday_alignment=True,
    )
    top_models = datasets.get("top_models")
    top_frame = top_models.frame.copy() if top_models and not top_models.frame.empty else pd.DataFrame()
    legacy_model_tokens = _comparison_weekly_rankings(
        top_frame, date_column="week_start_date", entity_column="entity_id", value_column="metric_value",
        entity_mapper=normalize_model, sunday_alignment=False,
    )
    requests = datasets.get("provider_weekly_requests")
    request_frame = requests.frame.copy() if requests and not requests.frame.empty else pd.DataFrame()
    legacy_company_requests = _comparison_weekly_rankings(
        request_frame, date_column="week_start_date", entity_column="entity_id", value_column="metric_value",
        entity_mapper=lambda value: canonical_provider_slug(value), sunday_alignment=False,
    )

    economics = explorer.get("economics", pd.DataFrame()).copy()
    if not economics.empty:
        economics["date"] = pd.to_datetime(economics.get("usage_date_dt"), errors="coerce").dt.normalize()
        economics["model_id"] = economics.get("model_permaslug", pd.Series(pd.NA, index=economics.index)).map(normalize_model)
        economics["company_id"] = economics.get("provider_slug", pd.Series(pd.NA, index=economics.index)).map(canonical_provider_slug)
        economics["company_id"] = economics["company_id"].fillna(economics["model_id"].map(_model_origin_slug))
        economics["total_tokens"] = pd.to_numeric(economics.get("total_tokens"), errors="coerce").fillna(0.0)
        economics["revenue"] = pd.to_numeric(economics.get("estimated_revenue"), errors="coerce")
        economics["priced_tokens"] = economics["total_tokens"].where(economics["revenue"].notna(), 0.0)
        economics = economics.dropna(subset=["date", "revenue"])
    model_econ_daily = (
        economics.groupby(["date", "model_id"], as_index=False).agg(
            revenue=("revenue", "sum"), priced_tokens=("priced_tokens", "sum")
        ).rename(columns={"date": "period_start", "model_id": "entity_id"})
        if not economics.empty else pd.DataFrame()
    )
    company_econ_daily = (
        economics.groupby(["date", "company_id"], as_index=False).agg(
            revenue=("revenue", "sum"), priced_tokens=("priced_tokens", "sum")
        ).rename(columns={"date": "period_start", "company_id": "entity_id"})
        if not economics.empty else pd.DataFrame()
    )

    series: dict[str, dict[str, pd.DataFrame]] = {"Companies": {}, "Models": {}}
    request_interpolations: list[dict[str, object]] = []
    for entity_type, modern_tokens, legacy_tokens, modern_requests, legacy_requests, econ_daily in (
        ("Companies", modern_company_tokens, legacy_company_tokens, company_requests_daily, legacy_company_requests, company_econ_daily),
        ("Models", modern_model_tokens, legacy_model_tokens, model_requests_daily, _comparison_empty_rows(), model_econ_daily),
    ):
        _, token_complete_week, _ = _comparison_first_week_coverage(modern_tokens, date_column="date")
        _, request_complete_week, _ = _comparison_first_week_coverage(modern_requests, date_column="date")
        _, economics_complete_week, _ = _comparison_first_week_coverage(econ_daily, date_column="period_start")
        weekly_modern_tokens = _comparison_periodize(modern_tokens, date_column="date", window="Weekly")
        weekly_modern_requests = _comparison_periodize(modern_requests, date_column="date", window="Weekly")
        if token_complete_week is not None:
            weekly_modern_tokens = weekly_modern_tokens[weekly_modern_tokens["period_start"] >= token_complete_week]
        if request_complete_week is not None:
            weekly_modern_requests = weekly_modern_requests[weekly_modern_requests["period_start"] >= request_complete_week]
        weekly_tokens = _comparison_merge_sources(legacy_tokens, weekly_modern_tokens, prefer_modern=True)
        # Model-detail rows come from provider_activity's per-model breakdown, so
        # older top-model ranking rows before that series starts aren't a
        # comparable model-detail series and shouldn't appear in this chart.
        # provider_first_week is derived from the live data (not hardcoded) so
        # this floor moves automatically if provider_activity's history changes.
        if entity_type == "Models" and not weekly_tokens.empty and provider_first_week is not None:
            weekly_tokens = weekly_tokens[weekly_tokens["period_start"] >= provider_first_week].copy()
        # The legacy company request feed is the longer, stable weekly series;
        # use newer model-detail requests only after it stops publishing.
        weekly_requests = _comparison_merge_sources(legacy_requests, weekly_modern_requests, prefer_modern=False)
        if entity_type == "Companies":
            weekly_requests, estimates = _comparison_interpolate_internal_weekly_request_gaps(weekly_requests)
            request_interpolations.extend(estimates)
        weekly_econ = _comparison_periodize(econ_daily, date_column="period_start", window="Weekly", value_column="revenue", output_column="revenue") if not econ_daily.empty else pd.DataFrame()
        if not econ_daily.empty:
            econ_weekly = _comparison_periodize(econ_daily, date_column="period_start", window="Weekly", value_column="revenue", output_column="revenue")
            priced_weekly = _comparison_periodize(econ_daily, date_column="period_start", window="Weekly", value_column="priced_tokens", output_column="priced_tokens")
            weekly_econ = econ_weekly.merge(priced_weekly, on=["period_start", "entity_id"], how="outer")
            if economics_complete_week is not None:
                weekly_econ = weekly_econ[weekly_econ["period_start"] >= economics_complete_week]
        else:
            weekly_econ = pd.DataFrame()
        daily_tokens = _comparison_periodize(modern_tokens, date_column="date", window="Daily")
        daily_requests = _comparison_periodize(modern_requests, date_column="date", window="Daily")
        daily_econ = econ_daily.rename(columns={"date": "period_start"}) if not econ_daily.empty else pd.DataFrame()
        monthly_tokens = _comparison_periodize(weekly_tokens, date_column="period_start", window="Monthly")
        monthly_requests = _comparison_periodize(weekly_requests, date_column="period_start", window="Monthly")
        monthly_econ = _comparison_periodize(weekly_econ, date_column="period_start", window="Monthly", value_column="revenue", output_column="revenue") if not weekly_econ.empty else pd.DataFrame()
        if not weekly_econ.empty:
            monthly_priced = _comparison_periodize(weekly_econ, date_column="period_start", window="Monthly", value_column="priced_tokens", output_column="priced_tokens")
            monthly_econ = monthly_econ.merge(monthly_priced, on=["period_start", "entity_id"], how="outer")
        series[entity_type]["Weekly"] = _comparison_metric_frame(weekly_tokens, weekly_requests, weekly_econ)
        series[entity_type]["Daily"] = _comparison_metric_frame(daily_tokens, daily_requests, daily_econ)
        series[entity_type]["Monthly"] = _comparison_metric_frame(monthly_tokens, monthly_requests, monthly_econ)

    catalog = explorer.get("catalog", pd.DataFrame()).copy()
    model_ids: set[str] = set(catalog.get("model_id", pd.Series(dtype="string")).dropna().astype(str))
    for frame in (modern_model_tokens, legacy_model_tokens, model_requests_daily, model_econ_daily):
        if not frame.empty:
            model_ids.update(frame["entity_id"].dropna().astype(str))
    model_ids = {value for value in model_ids if value.casefold() not in {"others", "other"}}
    catalog_labels = catalog.set_index("model_id")["model_name"].to_dict() if not catalog.empty else {}
    catalog_companies = catalog.set_index("model_id")["company"].to_dict() if not catalog.empty else {}
    model_options = pd.DataFrame({"entity_id": sorted(model_ids)})
    if not model_options.empty:
        model_options["label"] = model_options["entity_id"].map(catalog_labels).fillna(model_options["entity_id"].map(_short_model_name))
        model_options["company"] = model_options["entity_id"].map(catalog_companies).fillna(model_options["entity_id"].map(lambda value: _derive_provider_name(value, None)))
        model_options = model_options.sort_values(["label", "entity_id"]).reset_index(drop=True)

    company_ids: set[str] = set()
    for frame in (modern_company_tokens, legacy_company_tokens, company_requests_daily, legacy_company_requests, company_econ_daily):
        if not frame.empty:
            company_ids.update(frame["entity_id"].dropna().astype(str))
    company_ids = {value for value in company_ids if value.casefold() not in {"others", "other"}}
    company_options = pd.DataFrame({"entity_id": sorted(company_ids)})
    if not company_options.empty:
        company_options["label"] = company_options["entity_id"].map(lambda value: OPENROUTER_PROVIDER_MAP.get(value, value.replace("-", " ").title()))
        company_options = company_options.sort_values("label").reset_index(drop=True)

    return {
        "series": series,
        "company_options": company_options,
        "model_options": model_options,
        "model_scores": _comparison_score_lookup(datasets, catalog),
        "transition_markers": [
            marker for marker in [
                {
                    "date": provider_first_week,
                    "label": (
                        f"{provider_first_week.strftime('%b %d')}: provider daily activity starts; "
                        f"this week has {provider_first_week_days}/7 observed days and keeps the complete legacy weekly bucket"
                    ),
                    "short_label": "Provider daily starts",
                } if provider_first_week is not None else None,
                {
                    "date": complete_model_week,
                    "label": "Jun 17: complete model-activity totals begin; earlier model detail is category-level",
                    "short_label": "Complete model totals",
                } if complete_model_week is not None else None,
            ] if marker is not None
        ],
        "coverage": {
            "company_tokens_start": modern_company_tokens["date"].min() if not modern_company_tokens.empty else None,
            "company_requests_start": company_requests_daily["date"].min() if not company_requests_daily.empty else None,
            "model_tokens_start": modern_model_tokens["date"].min() if not modern_model_tokens.empty else None,
            "model_requests_start": model_requests_daily["date"].min() if not model_requests_daily.empty else None,
        },
        "request_interpolations": request_interpolations,
    }


def render_kpi_row(datasets: dict[str, DatasetLoadResult], openrouter_views: dict[str, object]) -> None:
    tm_result = datasets.get("top_models")
    ms_result = datasets.get("market_share")
    week_context = rankings_week_context(datasets)

    # --- top models KPIs ---
    total_latest = None
    wow_pct      = None
    top_model    = None

    if tm_result and not tm_result.frame.empty:
        tm = tm_result.frame.copy()
        tm["week_start_date"] = tm["week_start_date"].astype(str)
        sorted_weeks = sorted(tm["week_start_date"].unique())
        if sorted_weeks:
            latest_wk = sorted_weeks[-1]
            total_latest = tm[tm["week_start_date"] == latest_wk]["metric_value"].sum()
            tm_latest_named = (
                tm[
                    (tm["week_start_date"] == latest_wk) &
                    (tm["entity_id"].str.lower() != "others") &
                    (tm["entity_id"].str.contains("/", na=False))
                ]
                .groupby("entity_id", as_index=False)["metric_value"]
                .sum()
                .sort_values("metric_value", ascending=False)
            )
            top_model = tm_latest_named.iloc[0]["entity_id"] if not tm_latest_named.empty else None
            if len(sorted_weeks) >= 2:
                prev_wk    = sorted_weeks[-2]
                total_prev = tm[tm["week_start_date"] == prev_wk]["metric_value"].sum()
                if total_prev > 0:
                    wow_pct = (total_latest - total_prev) / total_prev * 100

    # --- market share leader ---
    leader_author = None
    leader_pct    = None

    if ms_result and not ms_result.frame.empty:
        ms = ms_result.frame.copy()
        ms["week_start_date"] = ms["week_start_date"].astype(str)
        latest_ms_wk = ms["week_start_date"].max()
        ms_latest    = ms[ms["week_start_date"] == latest_ms_wk].groupby("entity_id", as_index=False)["metric_value"].sum()
        ms_latest_named = ms_latest[ms_latest["entity_id"].str.lower() != "others"].copy()
        if not ms_latest_named.empty:
            ms_total = ms_latest["metric_value"].sum()
            ms_latest_named = ms_latest_named.sort_values("metric_value", ascending=False)
            leader_author = ms_latest_named.iloc[0]["entity_id"]
            if ms_total > 0:
                leader_pct = ms_latest_named.iloc[0]["metric_value"] / ms_total * 100

    # --- render ---
    if wow_pct is not None:
        tok_delta_cls  = "up" if wow_pct >= 0 else "down"
        tok_delta_text = f"{'↑' if wow_pct >= 0 else '↓'} {abs(wow_pct):.1f}% WoW"
    else:
        tok_delta_cls, tok_delta_text = "flat", "—"

    tokens_fmt   = format_metric(total_latest) if total_latest is not None else "—"
    leader_label = f"{leader_author} ({leader_pct:.1f}%)" if leader_author and leader_pct else leader_author or "—"
    model_label  = top_model or "—"
    if len(model_label) > 28:
        model_label = model_label[:26] + "…"
    wow_str = f"{'+'  if wow_pct and wow_pct >= 0 else ''}{f'{wow_pct:.1f}%' if wow_pct is not None else '—'}"

    st.markdown(
        kpi_grid_html(
            kpi_card_html("Total Tokens (Latest Model Week)", tokens_fmt, delta=tok_delta_text, delta_class=tok_delta_cls),
            kpi_card_html("WoW Change", wow_str, delta="vs prior week"),
            kpi_card_html("Top Model", model_label, delta="by tokens this week", value_style="font-size:1.1rem;"),
            kpi_card_html("Market Leader", leader_label, delta="latest market-share week", value_style="font-size:1.1rem;"),
        ),
        unsafe_allow_html=True,
    )

    warning = rankings_bucket_warning(week_context)
    if warning:
        st.markdown(f'<div class="rankings-warning">{warning}</div>', unsafe_allow_html=True)


PRICE_LABELS = {
    "original_spend_weighted_tei": "Spend-Weighted TEI",
    "original_cpi_workload_basket": "CPI Workload Basket Index (50/40/10)",
    "original_volume_weighted_tei": "Original Volume-Weighted TEI",
    "original_frontier_tei": "Premium-Priced Realized",
    "original_value_tei": "Value-Priced Realized",
    "sota_volume_weighted_atp": "SOTA Volume-Weighted Realized Price",
    "realized_market_average": "Realized Market Average",
    "sota_median_list_price": "SOTA Median List Price",
    "realized_sota_price": "Realized SOTA Price",
    "frontier_contenders_median_list_price": "Frontier Contenders Median List Price",
    "premium_priced_realized": "Premium-priced Realized Price",
    "mid_priced_realized": "Mid-priced Realized Price",
    "low_priced_realized": "Low-priced Realized Price",
    "fixed_workload_basket": "Fixed Workload Basket",
}
WORKLOAD_LABELS = {
    "total_tokens_per_request": "Total tokens/request",
    "prompt_tokens_per_request": "Prompt tokens/request",
    "completion_tokens_per_request": "Completion tokens/request",
}
DEFAULT_PRICE_METRIC_IDS = [
    "original_spend_weighted_tei",
    "original_cpi_workload_basket",
    "original_volume_weighted_tei",
    "original_frontier_tei",
    "original_value_tei",
    "sota_volume_weighted_atp",
]
DIAGNOSTIC_PRICE_METRIC_IDS = [
    "frontier_contenders_median_list_price",
    "premium_priced_realized",
    "mid_priced_realized",
    "low_priced_realized",
    "fixed_workload_basket",
]


def _legacy_original_price_series(economics: pd.DataFrame) -> pd.DataFrame:
    """Dashboard-accessible wrapper for the persisted legacy price logic."""
    return compute_legacy_original_price_series(economics)


PRICE_METRIC_ROLLING_WINDOWS = {
    "original_spend_weighted_tei": 7,
    "original_cpi_workload_basket": 7,
    "original_volume_weighted_tei": 7,
    "original_frontier_tei": 7,
    "original_value_tei": 7,
    "sota_volume_weighted_atp": 7,
    "realized_market_average": 7,
    "sota_median_list_price": 1,
    "realized_sota_price": 7,
    "frontier_contenders_median_list_price": 1,
    "premium_priced_realized": 7,
    "mid_priced_realized": 7,
    "low_priced_realized": 7,
    "fixed_workload_basket": 7,
}
WEEKLY_USAGE_START_DATE = pd.Timestamp("2025-08-04")
DAILY_USAGE_START_DATE = pd.Timestamp("2026-06-17")
# Per-company daily explorer views can expose the older, sparse request source
# from Apr 16; the global workload-intensity mart remains Jun 17 onward.
COMPANY_DAILY_START_DATE = pd.Timestamp("2026-04-16")
LOW_PRICING_COVERAGE_THRESHOLD = 60.0
WORKLOAD_COMPONENT_METRIC_IDS = {
    "Total": "total_tokens_per_request",
    "Prompt": "prompt_tokens_per_request",
    "Completion": "completion_tokens_per_request",
}


def _derived_metric_pivot(
    frame: pd.DataFrame,
    metric_ids: list[str],
    *,
    rolling_window_days: int,
) -> pd.DataFrame:
    """Pivot compact derived-mart rows without replacing guarded gaps."""
    labels = {**WORKLOAD_LABELS, **PRICE_LABELS}
    requested = list(dict.fromkeys(metric_ids))
    display_columns = [labels.get(metric_id, metric_id) for metric_id in requested]
    required = {"usage_date", "metric_id", "value", "rolling_window_days"}
    if frame.empty or not required.issubset(frame.columns) or not requested:
        return pd.DataFrame(columns=display_columns)

    prepared = frame.loc[
        frame["metric_id"].astype("string").isin(requested)
        & pd.to_numeric(frame["rolling_window_days"], errors="coerce").eq(rolling_window_days),
        ["usage_date", "metric_id", "value"],
    ].copy()
    prepared["usage_date"] = pd.to_datetime(prepared["usage_date"], errors="coerce")
    prepared["value"] = pd.to_numeric(prepared["value"], errors="coerce")
    prepared = prepared.dropna(subset=["usage_date", "metric_id"])
    if prepared.empty:
        return pd.DataFrame(columns=display_columns)

    prepared["usage_date"] = prepared["usage_date"].dt.strftime("%Y-%m-%d")
    prepared = prepared.drop_duplicates(subset=["usage_date", "metric_id"], keep="last")
    pivot = prepared.pivot(index="usage_date", columns="metric_id", values="value")
    pivot = pivot.reindex(columns=requested).rename(columns=labels).sort_index()
    # Do not let dates with no valid value for any selected series create a
    # misleading blank block at the front or between disjoint cadences.
    pivot = pivot.dropna(how="all")
    pivot.columns.name = None
    pivot.index.name = None
    return pivot


def _latest_pivot_values(pivot: pd.DataFrame) -> dict[str, float | None]:
    if pivot.empty:
        return {str(column): None for column in pivot.columns}
    latest = pivot.iloc[-1]
    return {
        str(column): (float(value) if pd.notna(value) else None)
        for column, value in latest.items()
    }


def _average_price_pivot(frame: pd.DataFrame, metric_ids: list[str]) -> pd.DataFrame:
    """Combine each price metric at its stored cadence without filling date gaps."""
    requested = list(dict.fromkeys(metric_ids))
    parts = [
        _derived_metric_pivot(
            frame,
            [metric_id],
            rolling_window_days=PRICE_METRIC_ROLLING_WINDOWS[metric_id],
        )
        for metric_id in requested
        if metric_id in PRICE_METRIC_ROLLING_WINDOWS
    ]
    if not parts:
        return pd.DataFrame()
    combined = pd.concat(parts, axis=1).sort_index()
    return combined.reindex(columns=[PRICE_LABELS[metric_id] for metric_id in requested])


def _workload_model_table(frame: pd.DataFrame) -> pd.DataFrame:
    display_columns = [
        "Model",
        "Company",
        "Token share",
        "Request share",
        "Tokens/request",
        "Intensity ratio",
    ]
    required = {
        "window_end_date",
        "model_id",
        "company_id",
        "token_share",
        "request_share",
        "tokens_per_request",
        "intensity_ratio",
    }
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame(columns=display_columns)

    prepared = frame.copy()
    prepared["window_end_date"] = pd.to_datetime(prepared["window_end_date"], errors="coerce")
    prepared = prepared.dropna(subset=["window_end_date"])
    if prepared.empty:
        return pd.DataFrame(columns=display_columns)
    latest_end = prepared["window_end_date"].max()
    latest = prepared.loc[prepared["window_end_date"].eq(latest_end)].copy()
    for column in ("token_share", "request_share", "tokens_per_request", "intensity_ratio"):
        latest[column] = pd.to_numeric(latest[column], errors="coerce")
    latest["token_share"] *= 100
    latest["request_share"] *= 100
    return (
        latest.sort_values(["intensity_ratio", "token_share"], ascending=[False, False])
        .rename(
            columns={
                "model_id": "Model",
                "company_id": "Company",
                "token_share": "Token share",
                "request_share": "Request share",
                "tokens_per_request": "Tokens/request",
                "intensity_ratio": "Intensity ratio",
            }
        )
        .loc[:, display_columns]
        .reset_index(drop=True)
    )


def _weekly_snapshot_pivot(daily_pivot: pd.DataFrame) -> pd.DataFrame:
    """Sample the latest available rolling observation in each calendar week."""
    if daily_pivot.empty:
        return daily_pivot.copy()
    prepared = daily_pivot.copy()
    prepared.index = pd.to_datetime(prepared.index, errors="coerce")
    prepared = prepared.loc[prepared.index.notna()].sort_index()
    if prepared.empty:
        return daily_pivot.iloc[0:0].copy()
    week_start = prepared.index - pd.to_timedelta(prepared.index.weekday, unit="D")
    prepared["_week_start"] = week_start
    weekly = prepared.groupby("_week_start", sort=True).tail(1).set_index("_week_start")
    weekly.index = weekly.index.strftime("%Y-%m-%d")
    weekly.index.name = None
    return weekly


def _workload_intensity_section_state(
    datasets: dict[str, DatasetLoadResult],
    component: str,
) -> dict[str, object]:
    daily_result = datasets.get("openrouter_usage_economics_daily")
    models_result = datasets.get("openrouter_workload_intensity_models")
    daily = daily_result.frame.copy() if daily_result and not daily_result.frame.empty else pd.DataFrame()
    models = models_result.frame.copy() if models_result and not models_result.frame.empty else pd.DataFrame()
    selected_component = component if component in WORKLOAD_COMPONENT_METRIC_IDS else "Total"
    metric_id = WORKLOAD_COMPONENT_METRIC_IDS[selected_component]
    raw_daily_pivot = _derived_metric_pivot(daily, [metric_id], rolling_window_days=1)
    seven_day_pivot = _derived_metric_pivot(daily, [metric_id], rolling_window_days=7)
    weekly_pivot = _weekly_snapshot_pivot(seven_day_pivot)
    all_components = _derived_metric_pivot(
        daily,
        list(WORKLOAD_COMPONENT_METRIC_IDS.values()),
        rolling_window_days=7,
    )
    latest_values: dict[str, object] = {
        metric_key: _latest_pivot_values(all_components).get(label)
        for metric_key, label in WORKLOAD_LABELS.items()
    }

    seven_day_change_pct = None
    if not seven_day_pivot.empty:
        series = seven_day_pivot.iloc[:, 0]
        dated = series.copy()
        dated.index = pd.to_datetime(dated.index, errors="coerce")
        dated = dated.loc[dated.index.notna()].sort_index()
        if not dated.empty:
            prior_date = dated.index[-1] - pd.Timedelta(days=7)
            latest_value = dated.iloc[-1]
            prior_value = dated.get(prior_date)
            if pd.notna(latest_value) and prior_value is not None and pd.notna(prior_value) and float(prior_value) != 0:
                seven_day_change_pct = (float(latest_value) - float(prior_value)) / float(prior_value) * 100

    observed_model_count = None
    if not daily.empty and {"usage_date", "metric_id", "rolling_window_days", "observed_model_count"}.issubset(daily.columns):
        coverage = daily.loc[
            daily["metric_id"].astype("string").eq(metric_id)
            & pd.to_numeric(daily["rolling_window_days"], errors="coerce").eq(7)
        ].copy()
        coverage["usage_date"] = pd.to_datetime(coverage["usage_date"], errors="coerce")
        coverage = coverage.sort_values("usage_date")
        counts = pd.to_numeric(coverage["observed_model_count"], errors="coerce").dropna()
        if not counts.empty:
            observed_model_count = int(counts.iloc[-1])
    latest_values["observed_model_count"] = observed_model_count
    latest_values["seven_day_change_pct"] = seven_day_change_pct
    workload_scraped_at = None
    if not daily.empty and {"metric_id", "scraped_at"}.issubset(daily.columns):
        workload_rows = daily.loc[
            daily["metric_id"].astype("string").isin(WORKLOAD_COMPONENT_METRIC_IDS.values())
        ]
        workload_timestamps = pd.to_datetime(
            workload_rows["scraped_at"], errors="coerce", utc=True
        ).dropna()
        if not workload_timestamps.empty:
            workload_scraped_at = workload_timestamps.max()

    return {
        "metric": "Workload Intensity",
        "component": selected_component,
        "metric_id": metric_id,
        "window": "Weekly",
        "pivot": weekly_pivot,
        "weekly_pivot": weekly_pivot,
        "raw_daily_pivot": raw_daily_pivot,
        "seven_day_pivot": seven_day_pivot,
        "latest_values": latest_values,
        "model_table": _workload_model_table(models),
        "y_title": "Tokens per Request",
        "hover_suffix": "/request",
        "empty_message": "No derived workload-intensity data is available yet.",
        "caption": "Tracked-model workload intensity is a request-demand proxy: it describes workload composition, not model efficiency.",
        "source_status": "Derived OpenRouter workload intensity · complete daily observations",
        "scraped_at": workload_scraped_at,
    }


def _weekly_model_request_totals_with_coverage(
    datasets: dict[str, DatasetLoadResult],
) -> tuple[pd.DataFrame, pd.DataFrame, str | None]:
    """Aggregate model-activity requests and observed dates by week."""
    result = datasets.get("openrouter_model_activity")
    frame = result.frame.copy() if result and not result.frame.empty else pd.DataFrame()
    required = {"usage_date", "request_count"}
    if frame.empty or not required.issubset(frame.columns):
        return (
            pd.DataFrame(columns=["Total Requests"]),
            pd.DataFrame(columns=["observed_days", "is_closed_week"]),
            None,
        )
    if "category_slug" in frame.columns:
        categories = frame["category_slug"].astype("string").str.casefold()
        if categories.eq("all").any():
            frame = frame.loc[categories.eq("all")].copy()
    prepared = pd.DataFrame(
        {
            "usage_date": pd.to_datetime(frame["usage_date"], errors="coerce").dt.normalize(),
            "requests": pd.to_numeric(frame["request_count"], errors="coerce"),
        }
    ).dropna(subset=["usage_date", "requests"])
    prepared = prepared.loc[prepared["requests"].ge(0)].copy()
    if prepared.empty:
        return (
            pd.DataFrame(columns=["Total Requests"]),
            pd.DataFrame(columns=["observed_days", "is_closed_week"]),
            result.latest_scraped_at,
        )
    prepared["usage_week"] = prepared["usage_date"] - pd.to_timedelta(
        prepared["usage_date"].dt.weekday, unit="D"
    )
    weekly = prepared.groupby("usage_week", as_index=True).agg(
        **{
            "Total Requests": ("requests", "sum"),
            "observed_days": ("usage_date", "nunique"),
        }
    )
    weekly["is_closed_week"] = (weekly.index + pd.Timedelta(days=6)) < prepared["usage_date"].max()
    weekly.index = weekly.index.strftime("%Y-%m-%d")
    return (
        weekly[["Total Requests"]].sort_index(),
        weekly[["observed_days", "is_closed_week"]].astype(
            {"observed_days": "Int64", "is_closed_week": "boolean"}
        ).sort_index(),
        result.latest_scraped_at,
    )


def _workload_total_ratio_state(
    datasets: dict[str, DatasetLoadResult],
    openrouter_views: dict[str, object],
    *,
    window: str = "Weekly",
) -> dict[str, object]:
    """Build workload intensity from the displayed token and request totals.

    This deliberately mirrors the two usage charts: total tokens from the
    Tokens series divided by total requests from the Requests series.  It is
    not a rolling model-level ratio, and therefore cannot silently change
    when the tracked-model universe changes.
    """
    requested_window = "Daily" if str(window).casefold() == "daily" else "Weekly"
    fallback = _workload_intensity_section_state(datasets, "Total")

    request_source_by_week: dict[str, str] = {}
    if requested_window == "Daily":
        token_pivot, _, token_scraped_at = _daily_total_usage_pivot(
            datasets, "Tokens", window="Daily"
        )
        request_pivot, _, request_scraped_at = _daily_total_usage_pivot(
            datasets, "Requests", window="Daily"
        )
    else:
        token_view = openrouter_views.get("top_models", {})
        # A view-only fixture can carry a hybrid total, but a bare top-model
        # view without the derived/raw marts is not enough to claim a workload
        # ratio.  Keep the section scoped to genuinely available usage data.
        if not datasets and token_view.get("total_source") != "hybrid":
            return fallback
        token_pivot = token_view.get("pivot_total", pd.DataFrame())
        if not isinstance(token_pivot, pd.DataFrame) or token_pivot.empty:
            token_pivot, _, token_scraped_at = _daily_total_usage_pivot(
                datasets, "Tokens", window="Weekly"
            )
        else:
            token_scraped_at = (
                datasets.get("top_models").latest_scraped_at
                if datasets.get("top_models")
                else None
            )

        request_view = openrouter_views.get("provider_weekly_requests", {})
        historical_pivot = request_view.get("pivot_weekly", pd.DataFrame())
        if isinstance(historical_pivot, pd.DataFrame) and not historical_pivot.empty:
            historical_requests = (
                historical_pivot.apply(pd.to_numeric, errors="coerce")
                .sum(axis=1, min_count=1)
                .rename("Total Requests")
                .sort_index()
            )
        else:
            historical_requests = pd.Series(dtype="float64", name="Total Requests")

        model_requests, request_coverage, request_scraped_at = _weekly_model_request_totals_with_coverage(datasets)
        complete_mask = (
            request_coverage["observed_days"].eq(7)
            & request_coverage["is_closed_week"].fillna(False)
        ).reindex(model_requests.index, fill_value=False)
        complete_model_requests = model_requests.loc[
            complete_mask
        ]["Total Requests"]

        # Historical provider totals extend the series and replace incomplete
        # model-activity overlaps. Complete seven-day model activity is the
        # canonical value whenever it is available.
        selected_requests = historical_requests.copy()
        request_sources = pd.Series(
            "Historical provider requests",
            index=selected_requests.index,
            dtype="string",
        )
        for usage_week, value in complete_model_requests.items():
            selected_requests.loc[usage_week] = value
            request_sources.loc[usage_week] = "Complete model activity"
        request_pivot = selected_requests.sort_index().to_frame("Total Requests")
        request_source_by_week = request_sources.reindex(request_pivot.index).dropna().astype(str).to_dict()
        if request_scraped_at is None and not historical_requests.empty:
            request_scraped_at = (
                datasets.get("provider_weekly_requests").latest_scraped_at
                if datasets.get("provider_weekly_requests")
                else None
            )

        # token_pivot is sourced from top_models/provider_daily_activity, both of
        # which now have real backfilled history well before WEEKLY_USAGE_START_DATE;
        # only request_pivot (openrouter_model_activity/provider_weekly_requests,
        # neither backfilled) still needs that floor.
        request_pivot = _clip_weekly_usage_pivot(request_pivot)

    def _total_series(frame: pd.DataFrame, label: str) -> pd.Series:
        if frame.empty:
            return pd.Series(dtype="float64", name=label)
        prepared = frame.copy()
        prepared.index = pd.to_datetime(prepared.index, errors="coerce")
        prepared = prepared.loc[prepared.index.notna()]
        if prepared.empty:
            return pd.Series(dtype="float64", name=label)
        numeric = prepared.apply(pd.to_numeric, errors="coerce")
        return numeric.sum(axis=1, min_count=1).rename(label).sort_index()

    tokens = _total_series(token_pivot, "Total Tokens")
    requests = _total_series(request_pivot, "Total Requests")
    aligned = pd.concat([tokens, requests], axis=1).sort_index()
    if requested_window == "Weekly":
        # Weekly points represent completed common periods only. This removes
        # unmatched current partial weeks instead of plotting a misleading gap
        # or extrapolated ratio.
        aligned = aligned.dropna(subset=["Total Tokens", "Total Requests"])
    if aligned.empty or aligned["Total Tokens"].notna().sum() == 0 or aligned["Total Requests"].notna().sum() == 0:
        # Keep fixture/backward compatibility when only the derived mart is
        # supplied; real dashboard data takes the graph-total path above.
        return fallback
    ratio = aligned["Total Tokens"].div(
        aligned["Total Requests"].where(aligned["Total Requests"].ne(0))
    ).to_frame("Total tokens/request")
    ratio.index = ratio.index.strftime("%Y-%m-%d")

    latest_value = ratio.iloc[-1, 0] if not ratio.empty else None
    change_pct = None
    if len(ratio) >= 2:
        previous = ratio.iloc[-2, 0]
        if pd.notna(latest_value) and pd.notna(previous) and float(previous) != 0:
            change_pct = (float(latest_value) - float(previous)) / float(previous) * 100

    latest_values = dict(fallback.get("latest_values", {}))
    latest_values.update(
        {
            "total_tokens_per_request": latest_value,
            "seven_day_change_pct": change_pct,
        }
    )
    scraped_candidates = [value for value in (token_scraped_at, request_scraped_at) if value]
    scraped_at = max(scraped_candidates) if scraped_candidates else fallback.get("scraped_at")
    return {
        **fallback,
        "window": requested_window,
        "pivot": ratio,
        "weekly_pivot": ratio if requested_window == "Weekly" else fallback.get("weekly_pivot", ratio),
        "raw_daily_pivot": ratio if requested_window == "Daily" else fallback.get("raw_daily_pivot", ratio),
        "seven_day_pivot": ratio if requested_window == "Daily" else fallback.get("seven_day_pivot", ratio),
        "latest_values": latest_values,
        "calculation_note": (
            "Daily total tokens ÷ daily total requests"
            if requested_window == "Daily"
            else "Weekly total tokens ÷ weekly total requests"
        ),
        "caption": (
            "Daily workload intensity uses total tokens ÷ daily model-activity requests; missing dates remain gaps. "
            "It describes workload composition, not model efficiency."
            if requested_window == "Daily"
            else "Weekly workload intensity uses the displayed weekly token total ÷ requests. Historical provider requests extend the series; complete seven-day model activity replaces overlapping weeks, and unmatched partial weeks are omitted. It describes workload composition, not model efficiency."
        ),
        "source_status": (
            "Derived OpenRouter workload intensity · graph totals"
            + (
                f" · {'daily' if requested_window == 'Daily' else 'weekly'} series starts "
                f"{ratio.index.min() if not ratio.empty else 'n/a'}"
                + ("" if requested_window == "Daily" else " · incomplete weeks omitted")
            )
        ),
        "request_source_by_week": {
            week: request_source_by_week[week]
            for week in ratio.index
            if week in request_source_by_week
        },
        "scraped_at": scraped_at,
    }


def _coverage_count(rows: pd.DataFrame, column: str) -> int | None:
    if column not in rows:
        return None
    values = pd.to_numeric(rows[column], errors="coerce").dropna()
    return int(values.max()) if not values.empty else None


def _average_price_section_state(
    datasets: dict[str, DatasetLoadResult],
    diagnostic_metric_ids: list[str] | None = None,
) -> dict[str, object]:
    daily_result = datasets.get("openrouter_usage_economics_daily")
    daily = daily_result.frame.copy() if daily_result and not daily_result.frame.empty else pd.DataFrame()
    # All approved lines are always shown together.  Keep the argument for
    # backwards compatibility with older callers, but deliberately ignore it:
    # diagnostics made the chart look like a configurable debugging panel.
    displayed_metric_ids = list(DEFAULT_PRICE_METRIC_IDS)
    pivot = _average_price_pivot(daily, displayed_metric_ids)
    price_scraped_at = None
    if not daily.empty and {"metric_id", "scraped_at"}.issubset(daily.columns):
        price_rows = daily.loc[
            daily["metric_id"].astype("string").isin(displayed_metric_ids)
        ]
        price_timestamps = pd.to_datetime(
            price_rows["scraped_at"], errors="coerce", utc=True
        ).dropna()
        if not price_timestamps.empty:
            price_scraped_at = price_timestamps.max()

    expected_count = 5
    observed_count = None
    priced_count = None
    if not daily.empty and {"usage_date", "metric_id", "rolling_window_days"}.issubset(daily.columns):
        sota_rows = daily.loc[
            daily["metric_id"].astype("string").isin(["sota_volume_weighted_atp", "realized_sota_price"])
        ].copy()
        sota_rows = sota_rows.loc[
            pd.to_numeric(sota_rows["rolling_window_days"], errors="coerce").eq(
                sota_rows["metric_id"].map(PRICE_METRIC_ROLLING_WINDOWS)
            )
        ]
        sota_rows["usage_date"] = pd.to_datetime(sota_rows["usage_date"], errors="coerce")
        sota_rows = sota_rows.dropna(subset=["usage_date"])
        if not sota_rows.empty:
            latest_sota_rows = sota_rows.loc[sota_rows["usage_date"].eq(sota_rows["usage_date"].max())]
            expected_count = _coverage_count(latest_sota_rows, "expected_family_count") or 5
            observed_count = _coverage_count(
                latest_sota_rows.loc[latest_sota_rows["metric_id"].eq("sota_volume_weighted_atp")],
                "observed_family_count",
            )
            priced_count = _coverage_count(latest_sota_rows, "priced_family_count")

    observed_label = str(observed_count) if observed_count is not None else "—"
    priced_label = str(priced_count) if priced_count is not None else "—"
    return {
        "metric": "Average Price",
        "metric_ids": displayed_metric_ids,
        "diagnostic_metric_ids": [],
        "pivot": pivot,
        "latest_values": _latest_pivot_values(pivot),
        "coverage_label": f"Observed {observed_label}/{expected_count} SOTA families · priced {priced_label}/{expected_count}",
        "y_title": "Price per Million Tokens ($)",
        "hover_suffix": "/M tokens",
        "empty_message": "No derived OpenRouter price data is available yet.",
        "caption": "Original price indices plus a capability-aware SOTA realized-price series. All lines are seven-day series.",
        "coverage_note": "Guarded SOTA values remain gaps when family coverage is insufficient; a gap is not a zero price.",
        "methodology_items": [
            f"**Coverage:** {observed_label}/{expected_count} SOTA families observed · {priced_label}/{expected_count} priced.",
            "**SOTA cohort:** Top-five capability families using the latest available Artificial Analysis score, backfilled historically with a release-date floor.",
            "**Pricing:** Exact OpenRouter route variants are retained, including fast, preview, free, pro, and dated routes.",
            "**Historical fills:** When a route lacks an early price, the first later non-free route price is backward-filled and labeled as a historical route-price proxy.",
        ],
        # Retained for callers that consumed the pre-expander state contract;
        # the dashboard now renders the structured methodology_items instead.
        "backcast_note": (
            "SOTA ATP uses the latest available Artificial Analysis intelligence score "
            "backfilled across historical usage dates as a transparent capability proxy; "
            "pricing routes remain exact."
        ),
        "source_status": "Derived OpenRouter price metrics · seven-day original indices + SOTA ATP",
        "scraped_at": price_scraped_at,
    }


def _daily_total_usage_pivot(
    datasets: dict[str, DatasetLoadResult],
    metric: str,
    *,
    window: str,
) -> tuple[pd.DataFrame, str, str | None]:
    """Return one total series for daily or weekly usage.

    Provider daily activity is the broadest token source.  Daily requests use
    the model-activity ``all`` category because provider activity does not
    publish request counts.  Weekly requests use the separately stored
    historical rankings request series when the complete model feed is not
    available.
    """
    requested_window = "Daily" if str(window).casefold() == "daily" else "Weekly"
    if metric == "Tokens":
        result = datasets.get("provider_daily_activity")
        frame = result.frame.copy() if result and not result.frame.empty else pd.DataFrame()
        date_column = "usage_date"
        value_column = "total_tokens"
    else:
        result = datasets.get("openrouter_model_activity")
        frame = result.frame.copy() if result and not result.frame.empty else pd.DataFrame()
        if not frame.empty and "category_slug" in frame.columns:
            categories = frame["category_slug"].astype("string").str.casefold()
            if categories.eq("all").any():
                frame = frame.loc[categories.eq("all")].copy()
        date_column = "usage_date"
        value_column = "request_count"

    if frame.empty or date_column not in frame.columns or value_column not in frame.columns:
        return pd.DataFrame(columns=[f"Total {metric}" ]), requested_window, None

    prepared = pd.DataFrame(
        {
            "usage_date_dt": pd.to_datetime(frame[date_column], errors="coerce").dt.normalize(),
            "value": pd.to_numeric(frame[value_column], errors="coerce"),
        }
    ).dropna(subset=["usage_date_dt", "value"])
    prepared = prepared[prepared["value"] >= 0]
    if prepared.empty:
        return pd.DataFrame(columns=[f"Total {metric}" ]), requested_window, None

    # WEEKLY_USAGE_START_DATE/DAILY_USAGE_START_DATE describe openrouter_model_activity's
    # real limits (it keeps only a rolling window). provider_daily_activity has no such
    # window, so the Tokens series shouldn't be clipped to a floor that belongs to a
    # different dataset -- only apply it to the Requests series sourced from model_activity.
    if requested_window == "Weekly":
        prepared["period"] = prepared["usage_date_dt"] - pd.to_timedelta(
            prepared["usage_date_dt"].dt.weekday, unit="D"
        )
        if metric != "Tokens":
            prepared = prepared.loc[prepared["period"].ge(WEEKLY_USAGE_START_DATE)].copy()
        if prepared.empty:
            return pd.DataFrame(columns=[f"Total {metric}"]), requested_window, result.latest_scraped_at if result else None
    else:
        prepared["period"] = prepared["usage_date_dt"]
        if metric != "Tokens":
            prepared = prepared.loc[prepared["period"].ge(DAILY_USAGE_START_DATE)].copy()
        if prepared.empty:
            return pd.DataFrame(columns=[f"Total {metric}"]), requested_window, result.latest_scraped_at if result else None
    pivot = (
        prepared.groupby("period", as_index=True)["value"]
        .sum()
        .to_frame(f"Total {metric}")
        .sort_index()
    )
    if requested_window == "Daily":
        full_days = pd.date_range(pivot.index.min(), pivot.index.max(), freq="D")
        pivot = pivot.reindex(full_days)
    pivot.index = pivot.index.strftime("%Y-%m-%d")
    latest_scraped_at = result.latest_scraped_at if result else None
    return pivot, requested_window, latest_scraped_at


def _clip_weekly_usage_pivot(frame: pd.DataFrame) -> pd.DataFrame:
    """Limit the Token/Request usage history to the requested chart start."""
    if frame.empty:
        return frame.copy()
    dates = pd.to_datetime(frame.index, errors="coerce")
    return frame.loc[dates.notna() & (dates >= WEEKLY_USAGE_START_DATE)].copy()


def _historical_weekly_request_pivot(
    datasets: dict[str, DatasetLoadResult],
) -> pd.DataFrame:
    """Build the recovered long-history rankings request context series.

    Older commits contain a request-labelled rankings snapshot in
    ``provider_weekly_requests``.  ``market_share`` is a different, mixed-
    provenance dataset and must never substitute for request counts.
    """
    result = datasets.get("provider_weekly_requests")
    frame = result.frame.copy() if result and not result.frame.empty else pd.DataFrame()
    column_name = "Historical rankings requests"
    if frame.empty or not {"week_start_date", "metric_value"}.issubset(frame.columns):
        return pd.DataFrame(columns=[column_name])

    prepared = frame.copy()
    prepared["original_week_start_date"] = pd.to_datetime(
        prepared["week_start_date"].astype(str), errors="coerce"
    ).dt.normalize()
    prepared["usage_week"] = _align_rankings_week_to_monday(prepared["week_start_date"].astype(str))
    prepared["metric_value"] = pd.to_numeric(prepared["metric_value"], errors="coerce")
    prepared = prepared.dropna(subset=["original_week_start_date", "usage_week", "metric_value"])
    if prepared.empty:
        return pd.DataFrame(columns=[column_name])

    # A scrape can contain several historical snapshots.  Pick the most
    # complete/latest snapshot for each aligned week before summing providers.
    if "source_run_id" in prepared.columns:
        prepared["_snapshot_id"] = prepared["source_run_id"].astype("string").fillna("")
        scraped_at = (
            prepared["scraped_at"]
            if "scraped_at" in prepared.columns
            else pd.Series(pd.NaT, index=prepared.index)
        )
        prepared["_snapshot_at"] = pd.to_datetime(scraped_at, errors="coerce", format="mixed")
        snapshots = (
            prepared.groupby(["usage_week", "_snapshot_id"], as_index=False)
            .agg(snapshot_rows=("metric_value", "size"), snapshot_at=("_snapshot_at", "max"))
            .sort_values(
                ["usage_week", "snapshot_rows", "snapshot_at", "_snapshot_id"],
                ascending=[True, False, False, False],
            )
            .drop_duplicates("usage_week", keep="first")
        )
        prepared = prepared.merge(
            snapshots[["usage_week", "_snapshot_id"]],
            on=["usage_week", "_snapshot_id"],
            how="inner",
        )

    totals = prepared.groupby("usage_week", as_index=True)["metric_value"].sum().sort_index()
    totals = totals.loc[pd.to_datetime(totals.index, errors="coerce") >= WEEKLY_USAGE_START_DATE]
    return totals.rename(column_name).to_frame()


def _weekly_usage_section_state(
    datasets: dict[str, DatasetLoadResult],
    openrouter_views: dict[str, object],
    metric: str,
    *,
    window: str = "Weekly",
) -> dict[str, object]:
    if metric == "Workload Intensity":
        return _workload_total_ratio_state(datasets, openrouter_views, window=window)
    if metric == "Average Price":
        return _average_price_section_state(datasets)

    if metric == "Requests":
        if str(window).casefold() == "daily":
            daily_pivot, actual_window, scraped_at = _daily_total_usage_pivot(
                datasets, "Requests", window="Daily"
            )
            if not daily_pivot.empty:
                latest_total = float(daily_pivot.iloc[-1, 0])
                wow_pct = None
                if len(daily_pivot) >= 2 and float(daily_pivot.iloc[-2, 0]) > 0:
                    wow_pct = (latest_total - float(daily_pivot.iloc[-2, 0])) / float(daily_pivot.iloc[-2, 0]) * 100
                return {
                    "metric": "Requests",
                    "window": actual_window,
                    "pivot": daily_pivot,
                    "latest_total": latest_total,
                    "wow_pct": wow_pct,
                    "dominant_label": None,
                    "provider_count": None,
                    "latest_week": str(daily_pivot.index[-1]),
                    "y_title": "Requests",
                    "hover_suffix": "requests",
                    "empty_message": "No daily model request data is available yet.",
                    "caption": "Daily total requests from the model-activity feed (all category). Provider-level request history is not published daily.",
                    "source_status": "Raw daily requests from OpenRouter model activity",
                    "scraped_at": scraped_at,
                }
        request_view = openrouter_views.get("provider_weekly_requests", {})
        legacy_pivot = request_view.get("pivot_weekly", pd.DataFrame())
        model_activity_result = datasets.get("openrouter_model_activity")
        model_activity_pivot, _, request_scraped_at = _daily_total_usage_pivot(
            datasets, "Requests", window="Weekly"
        )
        if not model_activity_pivot.empty:
            # Actual model totals are canonical whenever available.  The
            # rankings line below is context only and is never mixed into the
            # actual request KPI or workload-intensity denominator.
            pivot_requests = model_activity_pivot
            request_source = "Actual model activity"
            provider_count = None
        elif not legacy_pivot.empty:
            # Retain fixture/backward compatibility and support older snapshots
            # while no actual model-activity dataset is available.
            pivot_requests = legacy_pivot.apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1).to_frame("Total Requests")
            request_source = "Recovered rankings requests"
            provider_count = int(legacy_pivot.shape[1])
            if model_activity_result is None:
                request_scraped_at = (
                    datasets.get("provider_weekly_requests").latest_scraped_at
                    if datasets.get("provider_weekly_requests") else None
                )
        else:
            pivot_requests = model_activity_pivot
            request_source = "Actual model activity"
            provider_count = None
        pivot_requests = _clip_weekly_usage_pivot(pivot_requests)
        # When model activity is absent, the recovered history is already the
        # primary series; do not draw it a second time as a dashed context line.
        historical_request_pivot = (
            _historical_weekly_request_pivot(datasets)
            if request_source == "Actual model activity"
            else pd.DataFrame(columns=["Historical rankings requests"])
        )
        latest_total = None
        wow_pct = None
        dominant_provider = None
        latest_week = pivot_requests.index[-1] if not pivot_requests.empty else "n/a"
        if not pivot_requests.empty:
            latest_row = pivot_requests.iloc[-1]
            latest_total = float(latest_row.sum())
            # The chart intentionally presents one total series, so provider
            # identity is not implied by the plotted line.
            if len(pivot_requests) >= 2:
                previous_total = float(pivot_requests.iloc[-2].sum())
                if previous_total > 0:
                    wow_pct = (latest_total - previous_total) / previous_total * 100
        return {
            "metric": "Requests",
            "window": "Weekly",
            "pivot": pivot_requests,
            "latest_total": latest_total,
            "wow_pct": wow_pct,
            "dominant_label": dominant_provider,
            "provider_count": provider_count,
            "latest_week": str(latest_week),
            "y_title": "Requests",
            "hover_suffix": "requests",
            "empty_message": "No weekly model request data is available yet.",
            "caption": (
                "Solid: actual weekly requests from complete model-activity totals. "
                "Dashed: recovered historical rankings request snapshots. "
                "The mixed-provenance market_share series is excluded from this chart. "
                "Only actual requests are used for Tokens / Request."
            ),
            "source_status": (
                f"{request_source} · actual history starts 2026-06-15 when complete model totals are available"
                if request_source == "Actual model activity"
                else f"{request_source} · history starts 2025-08-04"
            ) + (" · historical provider requests start 2025-08-04" if not historical_request_pivot.empty else ""),
            "request_is_actual": request_source == "Actual model activity",
            "historical_request_pivot": historical_request_pivot,
            "scraped_at": request_scraped_at,
        }

    if str(window).casefold() == "daily":
        daily_pivot, actual_window, scraped_at = _daily_total_usage_pivot(
            datasets, "Tokens", window="Daily"
        )
        if not daily_pivot.empty:
            latest_total = float(daily_pivot.iloc[-1, 0])
            wow_pct = None
            if len(daily_pivot) >= 2 and float(daily_pivot.iloc[-2, 0]) > 0:
                wow_pct = (latest_total - float(daily_pivot.iloc[-2, 0])) / float(daily_pivot.iloc[-2, 0]) * 100
            return {
                "metric": "Tokens",
                "window": actual_window,
                "pivot": daily_pivot,
                "latest_total": latest_total,
                "wow_pct": wow_pct,
                "dominant_label": None,
                "provider_count": None,
                "top_model": None,
                "market_leader": None,
                "market_leader_pct": None,
                "latest_week": str(daily_pivot.index[-1]),
                "latest_source": "provider_daily_activity",
                "total_source": "provider_daily_activity",
                "y_title": "Tokens",
                "hover_suffix": "tokens",
                "empty_message": "No daily token data is available yet.",
                "caption": "Daily total token volume from Provider Daily Activity.",
                "source_status": "Raw daily tokens from Provider Daily Activity",
                "scraped_at": scraped_at,
            }

    top_view = openrouter_views.get("top_models", {})
    total_source = top_view.get("total_source", "top_models")
    # pivot_total blends market_share/top_models/provider_daily_activity, all
    # backfilled with real history before WEEKLY_USAGE_START_DATE -- that floor
    # belongs to openrouter_model_activity and shouldn't clip this series.
    pivot_total = top_view.get("pivot_total", pd.DataFrame())
    latest_week = pivot_total.index.max() if not pivot_total.empty else "n/a"
    latest_source = top_view.get("source_by_week", {}).get(latest_week, total_source)
    result = datasets.get("market_share") if latest_source == "market_share" else datasets.get("top_models")
    if latest_source == "hybrid":
        result = datasets.get("top_models")
    latest_total = None
    wow_pct = None
    top_model = None
    market_leader = None
    market_leader_pct = None
    if not pivot_total.empty:
        latest_total = float(pivot_total.iloc[-1].sum())
        if len(pivot_total) >= 2:
            previous_total = float(pivot_total.iloc[-2].sum())
            if previous_total > 0:
                wow_pct = (latest_total - previous_total) / previous_total * 100
    top_models_result = datasets.get("top_models")
    if top_models_result and not top_models_result.frame.empty:
        top_models = top_models_result.frame.copy()
        top_models["week_start_date"] = top_models["week_start_date"].astype(str)
        latest_top_week = top_models["week_start_date"].max()
        top_latest = (
            top_models[
                (top_models["week_start_date"] == latest_top_week)
                & (top_models["entity_id"].astype("string").str.lower() != "others")
                & (top_models["entity_id"].astype("string").str.contains("/", na=False))
            ]
            .groupby("entity_id", as_index=False)["metric_value"]
            .sum()
            .sort_values("metric_value", ascending=False)
        )
        if not top_latest.empty:
            top_model = str(top_latest.iloc[0]["entity_id"])
    market_share_result = datasets.get("market_share")
    if market_share_result and not market_share_result.frame.empty:
        market_share = market_share_result.frame.copy()
        market_share["week_start_date"] = market_share["week_start_date"].astype(str)
        latest_market_week = market_share["week_start_date"].max()
        market_latest = market_share[market_share["week_start_date"] == latest_market_week].copy()
        market_latest["metric_value"] = pd.to_numeric(market_latest["metric_value"], errors="coerce")
        market_totals = market_latest.groupby("entity_id", as_index=False)["metric_value"].sum()
        market_named = market_totals[market_totals["entity_id"].astype("string").str.lower() != "others"].copy()
        if not market_named.empty:
            market_named = market_named.sort_values("metric_value", ascending=False)
            market_leader = str(market_named.iloc[0]["entity_id"])
            total_market = float(market_totals["metric_value"].sum())
            if total_market > 0:
                market_leader_pct = float(market_named.iloc[0]["metric_value"]) / total_market * 100
    return {
        "metric": "Tokens",
        "window": "Weekly",
        "pivot": pivot_total,
        "latest_total": latest_total,
        "wow_pct": wow_pct,
        "dominant_label": None,
        "provider_count": None,
        "top_model": top_model,
        "market_leader": market_leader,
        "market_leader_pct": market_leader_pct,
        "latest_week": str(latest_week),
        "latest_source": latest_source,
        "total_source": total_source,
        "y_title": "Tokens",
        "hover_suffix": "tokens",
        "empty_message": "No weekly token data is available yet.",
        "caption": "Completed weekly OpenRouter token-usage buckets. Uses Market Share totals when they remain directionally complete, and falls back to Top Models when the Market Share feed undercounts recent weeks.",
        "source_status": (
            f"Total source: {total_source} · History starts {pivot_total.index.min() if not pivot_total.empty else 'n/a'} "
            f"· Latest plotted week: {latest_week} · Latest-week source: {latest_source}"
        ),
        "scraped_at": result.latest_scraped_at if result else None,
    }


PRICE_INDEX_COLORS = [
    "#4f46e5",
    "#0d9488",
    "#2563eb",
    "#64748b",
    "#ea580c",
    "#7c3aed",
    "#16a34a",
    "#9333ea",
]


def _format_optional_number(value: object, *, prefix: str = "", decimals: int = 0) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{prefix}{float(value):,.{decimals}f}"


def render_weekly_usage_section(datasets: dict[str, DatasetLoadResult], openrouter_views: dict[str, object]) -> None:
    st.markdown('<div class="section-title">OpenRouter Usage & Economics</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Monitor token and request demand, workload composition, and derived price signals in one workspace.</div>',
        unsafe_allow_html=True,
    )

    metric_options = ["Tokens", "Requests", "Workload Intensity", "Average Price"]
    if hasattr(st, "segmented_control"):
        metric = st.segmented_control("Metric", metric_options, default="Tokens", key="openrouter_weekly_usage_metric")
    else:
        metric = st.radio("Metric", metric_options, horizontal=True, key="openrouter_weekly_usage_metric")
    metric = str(metric or "Tokens")

    workload_window = "7-Day"
    usage_window = "Weekly"
    if metric == "Workload Intensity":
        window_options = ["Weekly", "Daily"]
        if hasattr(st, "segmented_control"):
            workload_window = st.segmented_control(
                "Window",
                window_options,
                default="Weekly",
                key="openrouter_workload_window_v2",
            )
        else:
            workload_window = st.radio(
                "Window",
                window_options,
                horizontal=True,
                key="openrouter_workload_window_v2",
            )
        workload_window = str(workload_window or "Weekly")
        state = _weekly_usage_section_state(
            datasets,
            openrouter_views,
            "Workload Intensity",
            window=workload_window,
        )
    elif metric == "Average Price":
        state = _average_price_section_state(datasets)
    else:
        window_options = ["Weekly", "Daily"]
        if hasattr(st, "segmented_control"):
            usage_window = st.segmented_control(
                "Window",
                window_options,
                default="Weekly",
                key="openrouter_usage_window",
            )
        else:
            usage_window = st.radio(
                "Window",
                window_options,
                horizontal=True,
                key="openrouter_usage_window",
            )
        state = _weekly_usage_section_state(datasets, openrouter_views, metric, window=str(usage_window or "Weekly"))

    pivot = state["pivot"]
    history_cutoff = render_history_range_control("openrouter_weekly_usage_history")
    pivot = _filter_pivot_by_history_range(pivot, history_cutoff)

    if state.get("scraped_at"):
        st.markdown(
            f'<div class="status-caption">{state["source_status"]} · Scraped: {format_scraped_at_display(state.get("scraped_at"))}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(f'<div class="status-caption">{state["source_status"]}</div>', unsafe_allow_html=True)

    if pivot.empty:
        st.info(str(state["empty_message"]))
        return

    if metric == "Requests":
        latest_total = state.get("latest_total")
        wow_pct = state.get("wow_pct")
        period_label = "Day" if state.get("window") == "Daily" else "Week"
        period_change_label = "DoD" if period_label == "Day" else "WoW"
        if wow_pct is not None:
            delta_cls = "up" if float(wow_pct) >= 0 else "down"
            delta_text = f"{'↑' if float(wow_pct) >= 0 else '↓'} {abs(float(wow_pct)):.1f}% {period_change_label}"
            wow_str = f"{'+' if float(wow_pct) >= 0 else ''}{float(wow_pct):.1f}%"
        else:
            delta_cls, delta_text, wow_str = "flat", "—", "—"
        st.markdown(
            kpi_grid_html(
                kpi_card_html(f"Total Requests (Latest {period_label})", format_metric(latest_total) if latest_total else "—", delta=delta_text, delta_class=delta_cls),
                kpi_card_html(f"{period_change_label} Change", wow_str, delta=f"vs prior {period_label.casefold()}"),
                kpi_card_html(
                    "Actual Series",
                    "Model activity" if state.get("request_is_actual") else "Unavailable",
                    delta="complete model totals" if state.get("request_is_actual") else "recovered history in use",
                ),
                kpi_card_html(
                    "Historical Series",
                    "Provider requests" if not state.get("historical_request_pivot", pd.DataFrame()).empty else "—",
                    delta="from Aug 2025" if not state.get("historical_request_pivot", pd.DataFrame()).empty else "not available",
                ),
            ),
            unsafe_allow_html=True,
        )
    elif metric == "Workload Intensity":
        values = state.get("latest_values", {})
        change_pct = values.get("seven_day_change_pct")
        if change_pct is not None:
            change_class = "up" if float(change_pct) >= 0 else "down"
            change_label = f"{'+' if float(change_pct) >= 0 else ''}{float(change_pct):.1f}%"
        else:
            change_class = "flat"
            change_label = "—"
        st.markdown(
            kpi_grid_html(
                kpi_card_html(
                    "Total Tokens / Request",
                    _format_optional_number(values.get("total_tokens_per_request")),
                    delta=("daily totals ratio" if workload_window == "Daily" else "weekly totals ratio"),
                ),
                kpi_card_html(
                    ("Day-over-Day Change" if workload_window == "Daily" else "Week-over-Week Change"),
                    change_label,
                    delta="vs prior period",
                    delta_class=change_class,
                ),
            ),
            unsafe_allow_html=True,
        )
        st.caption(str(state.get("calculation_note", "Total tokens ÷ total requests")))
    elif metric == "Average Price":
        vals = state.get("latest_values", {})
        st.markdown(
            kpi_grid_html(
                kpi_card_html(
                    "Original Volume-Weighted TEI",
                    _format_optional_number(vals.get("Original Volume-Weighted TEI"), prefix="$", decimals=3),
                    delta="per million tokens",
                ),
                kpi_card_html(
                    "Spend-Weighted TEI",
                    _format_optional_number(vals.get("Spend-Weighted TEI"), prefix="$", decimals=3),
                    delta="per million tokens",
                ),
                kpi_card_html(
                    "SOTA Volume-Weighted Price",
                    _format_optional_number(vals.get("SOTA Volume-Weighted Realized Price"), prefix="$", decimals=3),
                    delta="capability-aware · exact routes",
                ),
            ),
            unsafe_allow_html=True,
        )
        st.markdown(f'<div class="status-caption">{state["coverage_label"]}</div>', unsafe_allow_html=True)
    else:
        latest_total = state.get("latest_total")
        wow_pct = state.get("wow_pct")
        period_label = "Day" if state.get("window") == "Daily" else "Week"
        period_change_label = "DoD" if period_label == "Day" else "WoW"
        if wow_pct is not None:
            delta_cls = "up" if float(wow_pct) >= 0 else "down"
            delta_text = f"{'↑' if float(wow_pct) >= 0 else '↓'} {abs(float(wow_pct)):.1f}% {period_change_label}"
            wow_str = f"{'+' if float(wow_pct) >= 0 else ''}{float(wow_pct):.1f}%"
        else:
            delta_cls, delta_text, wow_str = "flat", "—", "—"
        top_model = str(state.get("top_model") or "—")
        if len(top_model) > 28:
            top_model = top_model[:26] + "…"
        market_leader = state.get("market_leader")
        market_leader_pct = state.get("market_leader_pct")
        if market_leader and market_leader_pct is not None:
            market_leader_label = f"{market_leader} ({float(market_leader_pct):.1f}%)"
        else:
            market_leader_label = str(market_leader or "—")
        st.markdown(
            kpi_grid_html(
                kpi_card_html(f"Total Tokens (Latest {period_label})", format_metric(latest_total) if latest_total else "—", delta=delta_text, delta_class=delta_cls),
                kpi_card_html(f"{period_change_label} Change", wow_str, delta=f"vs prior {period_label.casefold()}"),
                kpi_card_html("Top Model", top_model, delta="by tokens this week", value_style="font-size:1.1rem;"),
                kpi_card_html("Market Leader", market_leader_label, delta="latest market-share week", value_style="font-size:1.1rem;"),
            ),
            unsafe_allow_html=True,
        )

    if metric in {"Average Price", "Workload Intensity"}:
        st.plotly_chart(
            make_line_chart(
                pivot,
                PRICE_INDEX_COLORS if metric == "Average Price" else [ACCENT],
                y_title=str(state["y_title"]),
                x_title=("Usage Date (Daily)" if metric == "Average Price" or workload_window == "Daily" else "Usage Week (Starting)"),
                hover_suffix=str(state["hover_suffix"]),
                value_format=",.4f" if metric == "Average Price" else ",.1f",
                mode="lines",
            ),
            width="stretch",
            theme=None,
        )
    elif metric == "Requests":
        request_chart = pivot.copy()
        historical_request_pivot = _filter_pivot_by_history_range(
            state.get("historical_request_pivot", pd.DataFrame()), history_cutoff
        )
        if isinstance(historical_request_pivot, pd.DataFrame) and not historical_request_pivot.empty:
            request_chart = pd.concat([request_chart, historical_request_pivot], axis=1).sort_index()
        request_chart_fig = make_line_chart(
            request_chart,
            [ACCENT, YELLOW],
            y_title=str(state["y_title"]),
            x_title=("Usage Week (Starting)" if state.get("window") == "Weekly" else "Usage Date (Daily)"),
            hover_suffix=str(state["hover_suffix"]),
        )
        for trace in request_chart_fig.data:
            if trace.name == "Historical rankings requests":
                trace.line.dash = "dash"
                trace.line.width = 2
                trace.opacity = 0.75
        st.plotly_chart(request_chart_fig, width="stretch", theme=None)
    else:
        st.plotly_chart(
            make_line_chart(
                pivot,
                MODEL_COLORS,
                y_title=str(state["y_title"]),
                x_title=("Usage Week (Starting)" if state.get("window") == "Weekly" else "Usage Date (Daily)"),
                hover_suffix=str(state["hover_suffix"]),
            ),
            width="stretch",
            theme=None,
        )
    st.caption(str(state["caption"]))

    if metric == "Workload Intensity":
        model_table = state.get("model_table", pd.DataFrame())
        if not model_table.empty:
            st.markdown("**Tracked-model workload intensity · latest 30 days**")
            st.dataframe(
                model_table,
                hide_index=True,
                width="stretch",
                column_config={
                    "Token share": st.column_config.NumberColumn(format="%.2f%%"),
                    "Request share": st.column_config.NumberColumn(format="%.2f%%"),
                    "Tokens/request": st.column_config.NumberColumn(format="%.1f"),
                    "Intensity ratio": st.column_config.NumberColumn(format="%.2fx"),
                },
            )
            st.caption(
                "This tracked-model view compares token share with request share as a request-demand proxy. "
                "It does not measure model efficiency."
            )
        else:
            st.info("No latest 30-day tracked-model workload table is available yet.")

    if metric == "Average Price":
        st.markdown(
            f'<div class="status-caption">{state["coverage_note"]}</div>',
            unsafe_allow_html=True,
        )
        with st.expander("Price methodology & coverage"):
            for item in state.get("methodology_items", []):
                st.markdown(f"- {item}")


def render_top_models_chart(datasets: dict[str, DatasetLoadResult], openrouter_views: dict[str, object]) -> None:
    render_weekly_usage_section(datasets, openrouter_views)


CONTEXT_LENGTH_BUCKET_LABELS = ["<1K", "1K-10K", "10K-100K", "100K-1M", "1M-10M"]


def _context_length_frame(datasets: dict[str, DatasetLoadResult]) -> pd.DataFrame:
    result = datasets.get("context_length_requests")
    if result is None or result.frame.empty:
        return pd.DataFrame()
    frame = result.frame.copy()
    frame["week_start_date"] = frame["week_start_date"].astype(str)
    frame["context_length_bucket"] = frame["context_length_bucket"].astype(str)
    frame["entity_id"] = frame["entity_id"].astype(str)
    frame["metric_value"] = pd.to_numeric(frame["metric_value"], errors="coerce").fillna(0.0)
    return frame[frame["context_length_bucket"].isin(CONTEXT_LENGTH_BUCKET_LABELS)].copy()


def _context_length_bucket_pivot(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate request volume across models into context-length buckets."""
    required = {"week_start_date", "context_length_bucket", "metric_value"}
    if frame.empty or not required.issubset(frame.columns):
        return pd.DataFrame()
    work = frame[["week_start_date", "context_length_bucket", "metric_value"]].copy()
    work["week_start_date"] = pd.to_datetime(work["week_start_date"], errors="coerce").dt.normalize()
    work["context_length_bucket"] = work["context_length_bucket"].astype(str)
    work["metric_value"] = pd.to_numeric(work["metric_value"], errors="coerce")
    work = work.dropna(subset=["week_start_date", "context_length_bucket", "metric_value"])
    if work.empty:
        return pd.DataFrame()
    pivot = work.pivot_table(
        index="week_start_date",
        columns="context_length_bucket",
        values="metric_value",
        aggfunc="sum",
        fill_value=0.0,
    ).sort_index()
    ordered_columns = [
        bucket for bucket in CONTEXT_LENGTH_BUCKET_LABELS if bucket in pivot.columns
    ]
    return pivot.reindex(columns=ordered_columns)


def render_context_length_section(datasets: dict[str, DatasetLoadResult]) -> None:
    """Render the OpenRouter Rankings context-length request tracker.

    The upstream endpoint reports weekly request counts by model and prompt plus
    completion-length bucket. The percentage view is calculated per bucket/week
    from those raw counts, matching the website's chart toggle.
    """
    st.markdown('<div class="section-title">Context Length Usage</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Requests by prompt &amp; completion length on OpenRouter Rankings, with raw volume and share views.</div>',
        unsafe_allow_html=True,
    )
    frame = _context_length_frame(datasets)
    if frame.empty:
        st.info("No context-length request data is available yet. The weekly rankings scrape will populate it.")
        return

    st.markdown("#### Requests by context length")
    st.markdown(
        '<div class="section-subtitle">Total weekly requests grouped by prompt + completion length bucket across all models.</div>',
        unsafe_allow_html=True,
    )
    mix_view_options = ["Raw requests", "Share (%)"]
    if hasattr(st, "segmented_control"):
        mix_view = st.segmented_control(
            "Overall view",
            mix_view_options,
            default="Raw requests",
            key="openrouter_context_length_mix_view",
        )
    else:
        mix_view = st.radio(
            "Overall view",
            mix_view_options,
            horizontal=True,
            key="openrouter_context_length_mix_view",
        )
    mix_view = str(mix_view or "Raw requests")
    bucket_pivot = _context_length_bucket_pivot(frame)
    if bucket_pivot.empty:
        st.info("No context-length bucket totals are available yet.")
    else:
        mix_chart_pivot = bucket_pivot.copy()
        if mix_view == "Share (%)":
            totals = mix_chart_pivot.sum(axis=1).replace(0, np.nan)
            mix_chart_pivot = mix_chart_pivot.div(totals, axis=0).fillna(0.0) * 100.0
        st.plotly_chart(
            make_stacked_area_chart(
                mix_chart_pivot,
                list(mix_chart_pivot.index.astype(str)),
                MODEL_COLORS,
                x_title="Usage Week (Starting)",
                y_title="Request Share (%)" if mix_view == "Share (%)" else "Requests",
                value_format=",.1f" if mix_view == "Share (%)" else ",.0f",
                hover_suffix="%" if mix_view == "Share (%)" else "requests",
            ),
            width="stretch",
            theme=None,
        )
        st.caption(
            "Raw values are total requests in each bucket; percentage values are each bucket's share of all requests for that week."
        )

    st.markdown("#### Model breakdown within a context-length bucket")
    controls = st.columns([1, 1])
    with controls[0]:
        bucket = st.selectbox(
            "Prompt + completion length",
            CONTEXT_LENGTH_BUCKET_LABELS,
            index=1 if "1K-10K" in frame["context_length_bucket"].unique() else 0,
            key="openrouter_context_length_bucket",
        )
    with controls[1]:
        view_options = ["Raw requests", "Share (%)"]
        if hasattr(st, "segmented_control"):
            view_mode = st.segmented_control(
                "View",
                view_options,
                default="Raw requests",
                key="openrouter_context_length_view",
            )
        else:
            view_mode = st.radio(
                "View",
                view_options,
                horizontal=True,
                key="openrouter_context_length_view",
            )
    view_mode = str(view_mode or "Raw requests")

    selected = frame[frame["context_length_bucket"] == bucket].copy()
    pivot = selected.pivot_table(
        index="week_start_date",
        columns="entity_id",
        values="metric_value",
        aggfunc="sum",
        fill_value=0.0,
    ).sort_index()
    if pivot.empty:
        st.info(f"No request observations are available for the {bucket} bucket.")
        return
    pivot = pivot.loc[:, pivot.sum(axis=0).sort_values(ascending=False).index]
    chart_pivot = pivot.copy()
    if view_mode == "Share (%)":
        totals = chart_pivot.sum(axis=1).replace(0, np.nan)
        chart_pivot = chart_pivot.div(totals, axis=0).fillna(0.0) * 100.0

    latest_week = str(pivot.index.max())
    latest = pivot.loc[latest_week].sort_values(ascending=False).rename("requests").reset_index()
    latest.columns = ["model", "requests"]
    latest["share_pct"] = latest["requests"] / latest["requests"].sum() * 100.0
    latest["provider"] = latest["model"].map(lambda value: str(value).split("/", 1)[0] if "/" in str(value) else "Other")
    latest["model"] = latest["model"].map(lambda value: "Other models" if str(value).lower() == "others" else value)

    total_requests = float(latest["requests"].sum())
    named = latest[latest["model"] != "Other models"]
    top_model = str(named.iloc[0]["model"]) if not named.empty else "—"
    top_share = float(named.iloc[0]["share_pct"]) if not named.empty else 0.0
    st.markdown(
        kpi_grid_html(
            kpi_card_html("Requests (Latest Week)", format_metric(total_requests), delta=bucket),
            kpi_card_html("Top Model", top_model[:28] + ("…" if len(top_model) > 28 else ""), delta=f"{top_share:.1f}% share"),
            kpi_card_html("Models Shown", f"{len(latest)}", delta="includes Other models"),
            kpi_card_html("Latest Week", latest_week, delta="week starting"),
        ),
        unsafe_allow_html=True,
    )
    source_result = datasets.get("context_length_requests")
    scraped_at = source_result.latest_scraped_at if source_result else None
    source_caption = "OpenRouter Rankings context-length endpoint · weekly request counts"
    if scraped_at:
        source_caption += f" · Scraped: {format_scraped_at_display(scraped_at)}"
    st.markdown(f'<div class="status-caption">{source_caption}</div>', unsafe_allow_html=True)

    st.plotly_chart(
        make_stacked_area_chart(
            chart_pivot,
            list(chart_pivot.index.astype(str)),
            MODEL_COLORS,
            x_title="Usage Week (Starting)",
            y_title="Request Share (%)" if view_mode == "Share (%)" else "Requests",
            value_format=",.1f" if view_mode == "Share (%)" else ",.0f",
            hover_suffix="%" if view_mode == "Share (%)" else "requests",
        ),
        width="stretch",
        theme=None,
    )

    table = latest[["model", "provider", "requests", "share_pct"]].copy()
    table.insert(0, "rank", range(1, len(table) + 1))
    table = table.rename(columns={"share_pct": "share (%)"})
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            "requests": st.column_config.NumberColumn("Requests", format="%d"),
            "share (%)": st.column_config.NumberColumn("Share", format="%.2f%%"),
        },
    )
    st.caption(
        "The buckets describe the combined prompt and completion length of requests, not a model's maximum context window. "
        "Raw values are requests; percentage values are each model's share of the selected bucket for that week."
    )


MODALITY_RANKING_LABELS = {
    "image": "Image",
    "embeddings": "Embeddings",
    "rerank": "Rerank",
    "video": "Video",
    "speech": "Speech",
    "transcription": "Transcription",
}


def _modality_rankings_frame(datasets: dict[str, DatasetLoadResult]) -> pd.DataFrame:
    result = datasets.get("modality_rankings")
    if result is None or result.frame.empty:
        return pd.DataFrame()
    frame = result.frame.copy()
    frame["week_start_date"] = frame["week_start_date"].astype(str)
    frame["modality"] = frame["modality"].astype(str)
    frame["entity_id"] = frame["entity_id"].astype(str)
    frame["metric_value"] = pd.to_numeric(frame["metric_value"], errors="coerce").fillna(0.0)
    return frame[frame["modality"].isin(MODALITY_RANKING_LABELS)].copy()


def render_modality_rankings_section(datasets: dict[str, DatasetLoadResult]) -> None:
    """Render weekly OpenRouter rankings for non-text modalities.

    Covers image, embeddings, rerank, video, speech, and transcription models from
    the same modality-chart endpoint that powers the text top-models section.
    """
    st.markdown('<div class="section-title">Modality Rankings</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Weekly model rankings on OpenRouter Rankings for image, embeddings, rerank, video, speech, and transcription models.</div>',
        unsafe_allow_html=True,
    )
    frame = _modality_rankings_frame(datasets)
    if frame.empty:
        st.info("No modality ranking data is available yet. The weekly rankings scrape will populate it.")
        return

    available_modalities = [modality for modality in MODALITY_RANKING_LABELS if modality in frame["modality"].unique()]
    modality = st.selectbox(
        "Modality",
        available_modalities,
        format_func=lambda value: MODALITY_RANKING_LABELS.get(value, value),
        key="openrouter_modality_rankings_modality",
    )

    selected = frame[frame["modality"] == modality].copy()
    pivot = selected.pivot_table(
        index="week_start_date",
        columns="entity_id",
        values="metric_value",
        aggfunc="sum",
        fill_value=0.0,
    ).sort_index()
    if pivot.empty:
        st.info(f"No ranking observations are available for {MODALITY_RANKING_LABELS.get(modality, modality)}.")
        return
    pivot = pivot.loc[:, pivot.sum(axis=0).sort_values(ascending=False).index]

    latest_week = str(pivot.index.max())
    latest = pivot.loc[latest_week].sort_values(ascending=False).rename("volume").reset_index()
    latest.columns = ["model", "volume"]
    volume_total = float(latest["volume"].sum())
    latest["share_pct"] = latest["volume"] / volume_total * 100.0 if volume_total else 0.0
    latest["provider"] = latest["model"].map(lambda value: str(value).split("/", 1)[0] if "/" in str(value) else "Other")
    latest["model"] = latest["model"].map(lambda value: "Other models" if str(value).lower() == "others" else value)

    named = latest[latest["model"] != "Other models"]
    top_model = str(named.iloc[0]["model"]) if not named.empty else "—"
    top_share = float(named.iloc[0]["share_pct"]) if not named.empty else 0.0
    st.markdown(
        kpi_grid_html(
            kpi_card_html("Volume (Latest Week)", format_metric(volume_total), delta=MODALITY_RANKING_LABELS.get(modality, modality)),
            kpi_card_html("Top Model", top_model[:28] + ("…" if len(top_model) > 28 else ""), delta=f"{top_share:.1f}% share"),
            kpi_card_html("Models Shown", f"{len(latest)}", delta="includes Other models"),
            kpi_card_html("Latest Week", latest_week, delta="week starting"),
        ),
        unsafe_allow_html=True,
    )
    source_result = datasets.get("modality_rankings")
    scraped_at = source_result.latest_scraped_at if source_result else None
    source_caption = "OpenRouter Rankings modality endpoint · weekly volume by model"
    if scraped_at:
        source_caption += f" · Scraped: {format_scraped_at_display(scraped_at)}"
    st.markdown(f'<div class="status-caption">{source_caption}</div>', unsafe_allow_html=True)

    st.plotly_chart(
        make_stacked_area_chart(
            pivot,
            list(pivot.index.astype(str)),
            MODEL_COLORS,
            x_title="Usage Week (Starting)",
            y_title="Volume",
            value_format=",.0f",
            hover_suffix="volume",
        ),
        width="stretch",
        theme=None,
    )

    table = latest[["model", "provider", "volume", "share_pct"]].copy()
    table.insert(0, "rank", range(1, len(table) + 1))
    table = table.rename(columns={"share_pct": "share (%)"})
    st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        column_config={
            "volume": st.column_config.NumberColumn("Volume", format="%d"),
            "share (%)": st.column_config.NumberColumn("Share", format="%.2f%%"),
        },
    )
    st.caption(
        "Volume units vary by modality: tokens for image and embeddings, requests for rerank, "
        "seconds for video, speech, and transcription."
    )


def _latest_provider_market_coverage(
    datasets: dict[str, DatasetLoadResult],
    provider_daily_pivot: pd.DataFrame,
) -> tuple[float | None, str | None, int | None]:
    """Reconcile the plotted priority-provider total with the official full-market total."""
    official_result = datasets.get("official_model_rankings_daily")
    if official_result is None or official_result.frame.empty or provider_daily_pivot.empty:
        return None, None, None

    official = official_result.frame.copy()
    if not {"usage_date", "total_tokens"}.issubset(official.columns):
        return None, None, None
    official["usage_date"] = official["usage_date"].astype(str)
    official["total_tokens"] = pd.to_numeric(official["total_tokens"], errors="coerce").fillna(0.0)
    official_totals = official.groupby("usage_date")["total_tokens"].sum()

    provider_totals = provider_daily_pivot.sum(axis=1)
    provider_totals.index = provider_totals.index.astype(str)
    common_dates = sorted(set(official_totals.index) & set(provider_totals.index))
    if not common_dates:
        return None, None, None
    latest_date = common_dates[-1]
    official_total = float(official_totals.loc[latest_date])
    if official_total <= 0:
        return None, latest_date, None

    provider_count = None
    provider_result = datasets.get("provider_daily_activity")
    if provider_result is not None and not provider_result.frame.empty:
        provider_rows = provider_result.frame
        if {"usage_date", "entity_id"}.issubset(provider_rows.columns):
            on_date = provider_rows[provider_rows["usage_date"].astype(str).eq(latest_date)]
            provider_count = int(on_date["entity_id"].nunique())

    return float(provider_totals.loc[latest_date]) / official_total, latest_date, provider_count


HISTORY_RANGE_OPTIONS = ["YTD", "1Y", "2Y", "5Y", "All"]


def _history_range_cutoff(choice: str) -> pd.Timestamp | None:
    today = pd.Timestamp(datetime.now().date())
    if choice == "YTD":
        return pd.Timestamp(year=today.year, month=1, day=1)
    if choice == "1Y":
        return today - pd.DateOffset(years=1)
    if choice == "2Y":
        return today - pd.DateOffset(years=2)
    if choice == "5Y":
        return today - pd.DateOffset(years=5)
    return None


def _filter_pivot_by_history_range(pivot_df: pd.DataFrame, cutoff: pd.Timestamp | None) -> pd.DataFrame:
    if pivot_df.empty or cutoff is None:
        return pivot_df
    parsed = pd.to_datetime(pivot_df.index, errors="coerce")
    keep = parsed.isna() | (parsed >= cutoff)
    return pivot_df[keep]


def render_history_range_control(key: str, *, default: str = "1Y") -> pd.Timestamp | None:
    """Shared YTD/1Y/2Y/5Y/All control -- backfilled history now runs back to
    2024/2025 in several sections, so daily/weekly charts default to a
    readable window instead of plotting years of dense history at once."""
    if hasattr(st, "segmented_control"):
        choice = st.segmented_control("History", HISTORY_RANGE_OPTIONS, default=default, key=key)
    else:
        choice = st.radio("History", HISTORY_RANGE_OPTIONS, horizontal=True, index=HISTORY_RANGE_OPTIONS.index(default), key=key)
    return _history_range_cutoff(str(choice or default))


def render_revenue_token_section(datasets: dict[str, DatasetLoadResult], openrouter_views: dict[str, object]) -> None:
    """Unified provider revenue + token volume section with Metric/View toggles over shared Weekly/Monthly/Daily tabs."""
    rev_data = openrouter_views.get("revenue_estimator", {})
    tok_data = openrouter_views.get("token_volume", {})

    pivot_rev = rev_data.get("pivot_rev", pd.DataFrame())
    pivot_rev_monthly = regroup_provider_pivot_for_display(rev_data.get("pivot_rev_monthly", pd.DataFrame()), "monthly")
    pivot_rev_weekly  = regroup_provider_pivot_for_display(rev_data.get("pivot_rev_weekly", pd.DataFrame()), "weekly")
    pivot_rev_daily   = regroup_provider_pivot_for_display(rev_data.get("pivot_rev_daily", pd.DataFrame()), "daily")

    pivot_tok_daily   = regroup_provider_pivot_for_display(tok_data.get("pivot_daily", pd.DataFrame()), "daily")
    pivot_tok_weekly  = regroup_provider_pivot_for_display(tok_data.get("pivot_weekly", pd.DataFrame()), "weekly")
    pivot_tok_monthly = regroup_provider_pivot_for_display(tok_data.get("pivot_monthly", pd.DataFrame()), "monthly")

    st.markdown('<div class="section-title">Provider Revenue &amp; Token Volume</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Estimated revenue and observed token consumption for configured priority providers, '
        'switchable between absolute values, normalized share, and aggregate change. This is not full-market OpenRouter volume.</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Coverage note: OpenRouter’s official ‘Other’ bucket contains models below the daily top 50 across all providers. "
        "This priority-provider series already captures some of those long-tail models, so ‘Other’ is not the missing-provider gap."
    )

    if (
        pivot_rev_daily.empty and pivot_rev_weekly.empty and pivot_rev_monthly.empty
        and pivot_tok_daily.empty and pivot_tok_weekly.empty and pivot_tok_monthly.empty
    ):
        st.info("No provider revenue or token volume data is available yet.")
        return

    control_col1, control_col2 = st.columns([1, 1])
    with control_col1:
        metric_options = ["Revenue", "Tokens"]
        if hasattr(st, "segmented_control"):
            metric = st.segmented_control("Metric", metric_options, default="Revenue")
        else:
            metric = st.radio("Metric", metric_options, horizontal=True)
    with control_col2:
        view_options = ["Absolute", "Share (%)", "WoW (%)"]
        if hasattr(st, "segmented_control"):
            view_mode = st.segmented_control("View", view_options, default="Absolute")
        else:
            view_mode = st.radio("View", view_options, horizontal=True)
    metric = str(metric or "Revenue")
    view_mode = str(view_mode or "Absolute")
    is_share = view_mode == "Share (%)"
    is_change = view_mode == "WoW (%)"
    is_revenue = metric == "Revenue"

    if is_revenue:
        total_revenue = rev_data.get("total_revenue", 0)
        coverage = rev_data.get("coverage", {})
        st.markdown(
            kpi_grid_html(
                kpi_card_html("Estimated Revenue", f"${total_revenue:,.0f}", delta="modeled from OpenRouter pricing"),
                kpi_card_html("Provider Coverage", str(len(pivot_rev.columns)), delta="active priced providers"),
                kpi_card_html("Model-Priced Tokens", f"{coverage.get('model_priced_token_coverage', 0):.1%}", delta="matched or free model pricing"),
                kpi_card_html("Fallback-Priced Tokens", f"{coverage.get('fallback_priced_token_coverage', 0):.1%}", delta=f"{coverage.get('unpriced_token_share', 0):.1%} unpriced/synthetic"),
            ),
            unsafe_allow_html=True,
        )
    else:
        latest_tok_total, tok_wow_pct, dominant_provider = None, None, None
        market_coverage, coverage_date, provider_count = _latest_provider_market_coverage(datasets, pivot_tok_daily)
        if not pivot_tok_weekly.empty:
            latest_row = pivot_tok_weekly.iloc[-1]
            latest_tok_total = float(latest_row.sum())
            if len(pivot_tok_weekly) >= 2:
                prev_total = float(pivot_tok_weekly.iloc[-2].sum())
                if prev_total > 0:
                    tok_wow_pct = (latest_tok_total - prev_total) / prev_total * 100
            if latest_tok_total > 0:
                dominant_provider = latest_row.idxmax()

        if tok_wow_pct is not None:
            tok_delta_cls  = "up" if tok_wow_pct >= 0 else "down"
            tok_delta_text = f"{'↑' if tok_wow_pct >= 0 else '↓'} {abs(tok_wow_pct):.1f}% WoW"
        else:
            tok_delta_cls, tok_delta_text = "flat", "—"

        wow_str = f"{'+'  if tok_wow_pct and tok_wow_pct >= 0 else ''}{f'{tok_wow_pct:.1f}%' if tok_wow_pct is not None else '—'}"
        coverage_detail = "priority providers vs official total"
        if coverage_date:
            coverage_detail = f"{provider_count or 'priority'} providers · {pd.to_datetime(coverage_date).strftime('%b %d')}"

        st.markdown(
            kpi_grid_html(
                kpi_card_html("Total Tokens (Latest Week)", format_metric(latest_tok_total) if latest_tok_total else "—", delta=tok_delta_text, delta_class=tok_delta_cls),
                kpi_card_html("WoW Change", wow_str, delta="vs prior week"),
                kpi_card_html("Dominant Provider", dominant_provider or "—", delta="by token share this week"),
                kpi_card_html(
                    "Tracked-Provider Share",
                    f"{market_coverage:.1%}" if market_coverage is not None else "—",
                    delta=f"of official full market · {coverage_detail}",
                ),
            ),
            unsafe_allow_html=True,
        )

    pivot_active_daily   = pivot_rev_daily if is_revenue else pivot_tok_daily
    pivot_active_weekly  = pivot_rev_weekly if is_revenue else pivot_tok_weekly
    pivot_active_monthly = pivot_rev_monthly if is_revenue else pivot_tok_monthly

    # Backfilled history now runs back to mid-2024, so the Daily tab in
    # particular is unreadable without a range floor -- this trims all three
    # granularities to a shared window rather than only bounding one tab.
    history_cutoff = render_history_range_control("rev_tok_history")
    pivot_active_daily = _filter_pivot_by_history_range(pivot_active_daily, history_cutoff)
    pivot_active_weekly = _filter_pivot_by_history_range(pivot_active_weekly, history_cutoff)
    pivot_active_monthly = _filter_pivot_by_history_range(pivot_active_monthly, history_cutoff)

    def _render_chart(
        pivot_df: pd.DataFrame,
        date_title: str,
        granularity: str,
        extra_caption: str | None = None,
    ) -> None:
        if pivot_df.empty:
            st.info(f"No {date_title.lower()} data available.")
            return
        today_month = datetime.now().strftime("%Y-%m")
        display_index = [
            f"{d} (MTD)" if date_title == "Usage Month" and str(d) == today_month else d
            for d in pivot_df.index
        ]
        estimate_periods: set[str] = set()
        if is_change:
            aggregate_label = "Total Revenue" if is_revenue else "Total Tokens"
            change_source = pivot_df
            if granularity in {"weekly", "monthly"}:
                change_source, estimate_periods = _nowcast_latest_partial_period(
                    pivot_df,
                    pivot_active_daily,
                    granularity,
                )
            plot_df = _pivot_to_aggregate_change_percent(change_source, granularity, aggregate_label)
            if granularity in {"weekly", "monthly"}:
                plot_df = _drop_first_valid_change_point(plot_df)
            plot_df = _cap_change_percent_for_display(plot_df)
        elif is_share:
            plot_df = _pivot_to_share_percent(pivot_df)
        else:
            plot_df = pivot_df
        if is_change and not plot_df.empty:
            plot_df = plot_df.copy()
            plot_df.index = [
                f"{label} (est.)" if str(original) in estimate_periods else label
                for original, label in zip(pivot_df.index, display_index, strict=False)
            ]
        if is_revenue:
            if is_change:
                y_title = "Revenue Change (%)"
            else:
                y_title = "Revenue Share (%)" if is_share else "Revenue (USD)"
                value_format = ".1f" if is_share else ",.2f"
                hover_prefix = "" if is_share else "$"
                hover_suffix = "%" if is_share else ""
        else:
            if is_change:
                y_title = "Token Volume Change (%)"
            else:
                y_title = "Token Share (%)" if is_share else "Tokens"
                value_format = ".1f" if is_share else ",.0f"
                hover_prefix = ""
                hover_suffix = "%" if is_share else "tokens"
        if is_change:
            st.plotly_chart(
                _make_change_line_chart(
                    plot_df,
                    MODEL_COLORS,
                    x_title=date_title,
                    y_title=y_title,
                ),
                width="stretch",
                theme=None,
            )
        else:
            st.plotly_chart(
                make_stacked_area_chart(
                    plot_df,
                    display_index,
                    MODEL_COLORS,
                    x_title=date_title,
                    y_title=y_title,
                    value_format=value_format,
                    hover_prefix=hover_prefix,
                    hover_suffix=hover_suffix,
                ),
                width="stretch", theme=None,
            )
        if is_change and granularity == "daily":
            st.caption("Daily change uses total trailing 7-day average versus the prior total trailing 7-day average. Display is capped at -100% to +300% to keep tiny-base spikes readable.")
        elif is_change and granularity == "weekly":
            st.caption("Weekly change compares total volume with the previous weekly total. The first comparable point is hidden to avoid startup-base spikes; the latest incomplete week is nowcast from observed daily volume and marked (est.). Display is capped at -100% to +300%.")
        elif is_change and granularity == "monthly":
            st.caption("Monthly change compares total volume with the previous monthly total. The first comparable point is hidden to avoid startup-base spikes; the latest incomplete month is nowcast from observed daily volume and marked (est.). Display is capped at -100% to +300%.")
        if extra_caption:
            st.caption(extra_caption)

    tab_week, tab_month, tab_day = st.tabs(["Weekly", "Monthly", "Daily"])
    with tab_week:
        week_caption = None
        if is_revenue:
            cutover_week = rev_data.get("legacy_cutover_week")
            cutover_label = pd.Timestamp(cutover_week).strftime("%b %d, %Y") if cutover_week is not None else None
            week_caption = (
                f"Weekly revenue combines legacy Market Share plus Top Models fallback estimates before {cutover_label}, "
                "then switches to observed provider activity with pricing fallbacks."
                if cutover_label
                else "Weekly revenue uses observed provider activity with pricing fallbacks throughout the plotted history."
            )
        _render_chart(pivot_active_weekly, "Usage Week (Starting)", "weekly", extra_caption=week_caption)
    with tab_month:
        _render_chart(pivot_active_monthly, "Usage Month", "monthly")
    with tab_day:
        _render_chart(pivot_active_daily, "Usage Date", "daily")

    if is_revenue:
        st.caption(
            "Methodology: dashboard revenue uses a hybrid estimate. Legacy weekly history starts from Market Share provider totals, "
            "prices the ranked model subset, and tops up uncovered provider volume with provider/global blended pricing benchmarks. "
            "Modern daily history uses observed provider/model activity with OpenRouter pricing plus provider/global fallbacks when exact as-of matches are unavailable. "
            "Models whose OpenRouter slug ends in :free are included in token volume and zero-rated for revenue."
        )
    else:
        st.caption(
            "Legacy (pre-Jan 2026): weekly/monthly token views come from provider-level Market Share history, "
            "so they reflect providers visible in OpenRouter's author-share chart rather than only the surviving top-model cutoff. "
            "Modern (post-Jan 2026): daily token views come from exact per-provider logs, but only for the configured priority providers, "
            "not the full OpenRouter provider universe, so some providers may still be missing from the chart. Partial periods are observed totals."
        )
    st.markdown("---")


def render_task_spend_section(openrouter_views: dict[str, object]) -> None:
    task_view = openrouter_views.get("task_spend", {})
    by_selection = task_view.get("by_selection", {})

    st.markdown('<div class="section-title">Task-Level Model Leaders</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">OpenRouter task rankings from the new spend/token views. '
        'Rows are rolling-window shares, not absolute dollars or token counts.</div>',
        unsafe_allow_html=True,
    )

    if not by_selection:
        st.info("No task-level OpenRouter spend/token rankings are available yet.")
        return

    periods = task_view.get("periods", []) or ["spend"]
    windows = task_view.get("windows", []) or [30]
    default_period = "spend" if "spend" in periods else periods[0]
    default_window = _default_task_spend_window(windows)

    control_col1, control_col2 = st.columns([1, 1])
    with control_col1:
        period = st.selectbox(
            "Task ranking view",
            options=periods,
            index=periods.index(default_period),
            format_func=lambda value: "Spend share" if value == "spend" else "Token share",
            key="openrouter_task_spend_period",
        )
    with control_col2:
        window_days = st.selectbox(
            "Rolling window",
            options=windows,
            index=windows.index(default_window),
            format_func=lambda value: f"{int(value)} days",
            key="openrouter_task_spend_window",
        )

    selected = by_selection.get((str(period), int(window_days)))
    if not selected:
        st.info("No task ranking rows are available for that view/window selection.")
        return

    task_summary = selected.get("task_summary", pd.DataFrame()).copy()
    model_rows = selected.get("model_rows", pd.DataFrame()).copy()
    macro_summary = selected.get("macro_summary", pd.DataFrame()).copy()
    snapshot_label = task_view.get("latest_snapshot_date") or "n/a"
    top_task = selected.get("top_task") or "—"
    top_task_label = _pretty_task_label(str(top_task)) if top_task != "—" else "—"
    top_model = selected.get("top_model") or "—"

    top_task_share = 0.0
    if not task_summary.empty:
        top_task_share = float(task_summary.iloc[0]["task_share_pct"])

    st.markdown(
        kpi_grid_html(
            kpi_card_html("Snapshot", str(snapshot_label), delta=f"rolling {int(window_days)}d"),
            kpi_card_html("Tasks", f"{len(task_summary):,.0f}", delta=f"{str(period).title()} view"),
            kpi_card_html("Top Task", top_task_label, delta=f"{top_task_share:.1f}% of total {period}"),
            kpi_card_html("Top Model In Task", str(top_model), delta="ranked within top task", value_style="font-size:1.0rem;"),
        ),
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section-subtitle">Top Tasks</div>', unsafe_allow_html=True)
    if task_summary.empty:
        st.info("No task rows available.")
    else:
        treemap = task_summary.copy()
        treemap["macro_category"] = treemap["macro_category"].fillna("unknown").astype(str)
        macro_totals = treemap.groupby("macro_category")["task_share_pct"].sum()
        task_top_models = _task_top_models(model_rows)
        macro_top_models = _macro_top_models(model_rows, task_summary)

        ids: list[str] = []
        labels: list[str] = []
        parents: list[str] = []
        values: list[float] = []
        colors: list[str] = []
        customdata: list[str] = []
        for macro_category in sorted(macro_totals.index):
            ids.append(macro_category)
            labels.append(macro_category.capitalize())
            parents.append("")
            values.append(float(macro_totals[macro_category]))
            colors.append(_macro_color(macro_category))
            if macro_category in macro_top_models.index:
                top_row = macro_top_models.loc[macro_category]
                customdata.append(
                    f"#1 model: {_short_model_name(top_row['model_permaslug'])} "
                    f"({top_row['contribution_pct']:.1f}% of total {period})"
                )
            else:
                customdata.append("#1 model: —")
        for _, row in treemap.iterrows():
            ids.append(f"{row['macro_category']}::{row['category_slug']}")
            labels.append(row["task_label"])
            parents.append(row["macro_category"])
            values.append(float(row["task_share_pct"]))
            colors.append(_macro_color(row["macro_category"]))
            category_slug = row["category_slug"]
            if category_slug in task_top_models.index:
                top_row = task_top_models.loc[category_slug]
                customdata.append(
                    f"#1 model: {_short_model_name(top_row['model_permaslug'])} "
                    f"({top_row['model_share_pct']:.1f}% within task)"
                )
            else:
                customdata.append("#1 model: —")

        fig_tasks = go.Figure(
            go.Treemap(
                ids=ids,
                labels=labels,
                parents=parents,
                values=values,
                branchvalues="total",
                marker=dict(colors=colors, line=dict(width=1, color=BG)),
                textfont=dict(size=13, color="white"),
                customdata=customdata,
                hovertemplate=(
                    f"<b>%{{label}}</b><br>{str(period).title()} share: %{{value:.1f}}%<br>%{{customdata}}<extra></extra>"
                ),
            )
        )
        fig_tasks.update_layout(margin=dict(l=0, r=0, t=10, b=10), height=380)
        st.plotly_chart(fig_tasks, width="stretch", theme=None)

        if not macro_summary.empty:
            legend_items = "".join(
                f'<div class="macro-legend-item">'
                f'<span class="macro-legend-dot" style="background:{_macro_color(row["macro_category"])}"></span>'
                f'{str(row["macro_category"]).capitalize()} '
                f'<span class="macro-legend-pct">{row["task_share_pct"]:.1f}%</span>'
                f'</div>'
                for _, row in macro_summary.iterrows()
            )
            st.markdown(f'<div class="macro-legend-row">{legend_items}</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-subtitle">Macro Category Share Over Time</div>', unsafe_allow_html=True)
    history_pivot = task_view.get("history_by_selection", {}).get((str(period), int(window_days)), pd.DataFrame())
    if history_pivot.empty or len(history_pivot.index) < 2:
        snapshots_captured = len(history_pivot.index) if not history_pivot.empty else 0
        st.info(
            f"Only {snapshots_captured} daily snapshot(s) captured so far for this view. "
            "The OpenRouter task-spend scrape runs once a day, so this trend line fills in over the coming days/weeks."
        )
    else:
        fig_history = go.Figure()
        for macro_category in history_pivot.columns:
            fig_history.add_trace(
                go.Scatter(
                    x=history_pivot.index,
                    y=history_pivot[macro_category],
                    mode="lines+markers",
                    name=str(macro_category).capitalize(),
                    line=dict(color=_macro_color(macro_category), width=2),
                    hovertemplate="<b>%{fullData.name}</b><br>%{x}: %{y:.1f}%<extra></extra>",
                )
            )
        fig_history.update_layout(
            template="plotly_white",
            height=320,
            margin=dict(l=0, r=0, t=10, b=10),
            xaxis_title="Snapshot Date",
            yaxis_title=f"{str(period).title()} Share (%)",
            legend=dict(orientation="h", y=-0.2),
        )
        st.plotly_chart(fig_history, width="stretch", theme=None)
        st.caption(
            f"Rolling {int(window_days)}-day {period} share per macro category, one point per daily snapshot. "
            "Compare the 7d/30d/90d windows like fast/medium/slow moving averages to read trend speed."
        )

    if task_summary.empty or model_rows.empty:
        return

    task_options = task_summary["category_slug"].astype(str).tolist()
    default_task_index = task_options.index(top_task) if top_task in task_options else 0
    selected_task = st.selectbox(
        "Inspect task leaders",
        options=task_options,
        index=default_task_index,
        format_func=_pretty_task_label,
        key="openrouter_task_spend_task",
    )
    task_models = model_rows[model_rows["category_slug"].astype(str) == str(selected_task)].copy()
    if task_models.empty:
        st.info("No model rows are available for that task.")
        return

    task_models = task_models.sort_values(["rank", "model_share_pct"], ascending=[True, False]).head(10).reset_index(drop=True)

    def _leaderboard_row(rank: int, model_slug: str, share_pct: float) -> str:
        provider = _derive_provider_name(str(model_slug), None)
        model_name = _short_model_name(model_slug)
        return (
            '<div class="task-lb-row">'
            f'<div class="task-lb-rank">{rank}.</div>'
            f'<div class="task-lb-info"><div class="task-lb-name">{model_name}</div>'
            f'<div class="task-lb-provider">by {provider}</div></div>'
            f'<div class="task-lb-share">{share_pct:.1f}%</div>'
            '</div>'
        )

    rows_html = [
        _leaderboard_row(
            int(row["rank"]) if pd.notna(row["rank"]) else idx + 1,
            row["model_permaslug"],
            float(row["model_share_pct"]),
        )
        for idx, row in task_models.iterrows()
    ]
    half = (len(rows_html) + 1) // 2
    lb_col1, lb_col2 = st.columns(2)
    with lb_col1:
        st.markdown(f'<div class="task-lb-list">{"".join(rows_html[:half])}</div>', unsafe_allow_html=True)
    with lb_col2:
        st.markdown(f'<div class="task-lb-list">{"".join(rows_html[half:])}</div>', unsafe_allow_html=True)

    st.caption(
        "Source: OpenRouter frontend task rankings endpoint. Spend/token shares are normalized shares from rolling-window task classifications."
    )


def render_token_revenue_comparison(openrouter_views: dict[str, object]) -> None:
    """Sanity-check table: implied avg price = Revenue / Tokens, by provider and period."""
    with st.expander("📊 Revenue ÷ Token Accuracy Check (implied $/token)", expanded=False):
        st.markdown(
            "Divides estimated revenue by token volume for each provider to derive an **implied average price per token**. "
            "Compare against known model pricing to spot estimation errors, while remembering that revenue includes only conservatively priced observed rows.",
            unsafe_allow_html=True,
        )
        rev_data = openrouter_views.get("revenue_estimator", {})
        tok_data = openrouter_views.get("token_volume", {})

        rev_weekly, tok_weekly = grouped_revenue_token_pivots(rev_data, tok_data, "weekly")
        rev_monthly, tok_monthly = grouped_revenue_token_pivots(rev_data, tok_data, "monthly")

        tab_w, tab_m = st.tabs(["Weekly", "Monthly"])

        def _comparison_table(rev_piv: pd.DataFrame, tok_piv: pd.DataFrame, period_label: str) -> None:
            if rev_piv.empty or tok_piv.empty:
                st.info(f"Not enough data for {period_label} comparison.")
                return
            # Align columns and index
            common_cols = [col for col in rev_piv.columns if col in set(tok_piv.columns)]
            common_idx  = sorted(set(rev_piv.index)   & set(tok_piv.index))
            if not common_cols or not common_idx:
                st.info("No overlapping providers/periods between revenue and token data.")
                return
            rev_a = rev_piv.loc[common_idx, common_cols]
            tok_a = tok_piv.loc[common_idx, common_cols]
            # Implied price per token ($/token); multiply by 1e6 → $/M tokens for readability
            implied = (rev_a / tok_a.replace(0, float('nan'))).fillna(0) * 1e6
            # Show latest 12 periods
            display = implied.tail(12).round(4)
            # Colour: values outside [0.001, 10] $/M tokens are suspicious
            st.dataframe(
                display.style.background_gradient(axis=None, cmap="RdYlGn_r", vmin=0, vmax=5),
                width="stretch",
            )
            st.caption(
                f"Values in **$/M tokens** (implied avg price). "
                f"Typical range: $0.10–$5/M for mainstream models. "
                f"Very high values suggest token undercount; very low values suggest revenue undercount."
            )

        with tab_w:
            _comparison_table(rev_weekly, tok_weekly, "weekly")
        with tab_m:
            _comparison_table(rev_monthly, tok_monthly, "monthly")


def render_apps_tables(datasets: dict[str, DatasetLoadResult]) -> None:
    st.markdown('<div class="section-title">App Rankings & Trends</div>', unsafe_allow_html=True)

    tabs = st.tabs(["Global Rankings", "Trending Apps", "Monitored Apps"])

    with tabs[0]:
        result = datasets.get("apps_global_ranking_snapshots")
        if result and render_dataset_guard(result):
            frame = result.frame.copy()
            periods = sorted(frame["period"].dropna().astype(str).unique().tolist())
            _week_idx = next((i for i, p in enumerate(periods) if "week" in p.lower()), 0)
            period  = st.selectbox("Period", options=periods, index=_week_idx if periods else None, key="lb_period")
            if period:
                frame = frame[frame["period"] == period]
            latest_date = frame["snapshot_date"].max()
            latest = frame[frame["snapshot_date"] == latest_date].sort_values("rank").head(25)
            tbl = latest[["rank", "app_name", "categories", "tokens"]].copy()
            total_top25 = tbl["tokens"].sum()
            
            summary_col, _ = st.columns([1, 2])
            with summary_col:
                st.markdown(
                    kpi_card_html(f"Tokens in Top 25 ({latest_date})", format_metric(total_top25),
                                  card_style="margin-bottom:1rem", value_style="font-size:1.5rem"),
                    unsafe_allow_html=True,
                )
                
            tbl["tokens"] = tbl["tokens"].map(format_metric)
            st.dataframe(dataframe_for_display(tbl, ""), width="stretch", hide_index=True)

    with tabs[1]:
        result = datasets.get("apps_trending_snapshots")
        if result and render_dataset_guard(result):
            frame = result.frame.copy()
            latest_date = frame["snapshot_date"].max()
            latest = frame[frame["snapshot_date"] == latest_date].sort_values("rank").head(25)
            st.caption(f"Snapshot: {latest_date}")
            tbl = latest[["rank", "app_name", "categories", "tokens", "growth_percent"]].copy()
            tbl["tokens"] = tbl["tokens"].map(lambda v: "-" if pd.isna(v) else format_metric(v))
            tbl["growth_percent"] = tbl["growth_percent"].map(
                lambda v: "-" if pd.isna(v) else f"{v:,.0f}%"
            )
            st.dataframe(dataframe_for_display(tbl, ""), width="stretch", hide_index=True)

    with tabs[2]:
        meta_result  = datasets.get("app_metadata_snapshots")
        usage_result = datasets.get("app_usage_daily")
        if meta_result and render_dataset_guard(meta_result):
            latest_date   = meta_result.latest_date
            latest_meta   = meta_result.frame.copy()
            if latest_date:
                latest_meta = latest_meta[latest_meta["scrape_date"] == latest_date]
            st.caption(f"Metadata snapshot: {latest_date or 'n/a'}")
            st.dataframe(
                dataframe_for_display(
                    latest_meta[["app_name", "app_id", "origin_url", "categories", "description"]],
                    "",
                ),
                width="stretch",
                hide_index=True,
            )

        if usage_result and render_dataset_guard(usage_result, show_subheader=False):
            usage = usage_result.frame.copy()
            usage["usage_date"] = pd.to_datetime(usage["usage_date"], errors="coerce")
            scrape_dates = pd.to_datetime(usage.get("scraped_at"), errors="coerce", utc=True)
            latest_scrape_date = scrape_dates.max()
            if pd.notna(latest_scrape_date):
                partial_date = latest_scrape_date.tz_convert(None).normalize()
                usage = usage[usage["usage_date"] < partial_date].copy()
                st.caption(
                    f"Finalized daily usage only. The partial UTC day "
                    f"{partial_date.strftime('%Y-%m-%d')} is omitted and will be finalized by the next scrape."
                )
            app_names = sorted(usage["app_name"].dropna().astype(str).unique().tolist())
            selected  = st.multiselect("Apps", options=app_names, default=app_names[:3], key="mon_apps")
            if selected:
                usage = usage[usage["app_name"].isin(selected)]
            if not usage.empty:
                app_total = usage["total_tokens"].sum()
                st.markdown(
                    kpi_card_html("Cumulative Selection Usage", format_metric(app_total),
                                  card_style="margin-bottom:1rem; max-width:300px", value_style="font-size:1.5rem"),
                    unsafe_allow_html=True,
                )
                
                pivot_u = (
                    usage.pivot_table(index="usage_date", columns="model_permaslug", values="total_tokens", aggfunc="sum")
                    .fillna(0)
                    .sort_index()
                )
                top_m = pivot_u.sum().nlargest(15).index.tolist()
                pivot_u = pivot_u[top_m]
                fig_u = make_stacked_bar(pivot_u, MODEL_COLORS, y_title="Tokens", height=300)
                st.plotly_chart(fig_u, width="stretch", theme=None)


def _format_context_window(value: object) -> str:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(number):
        return "n/a"
    if number >= 1_000_000:
        return f"{number / 1_000_000:.2g}M tokens"
    if number >= 1_000:
        return f"{number / 1_000:.0f}K tokens"
    return f"{number:,.0f} tokens"


def _format_price_per_m(value: object) -> str:
    number = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "n/a" if pd.isna(number) or number < 0 else f"${number:,.4g} / 1M"


def _json_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if pd.isna(value):
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _safe_catalog_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _render_company_explorer(views: dict[str, object]) -> None:
    catalog = views.get("catalog", pd.DataFrame())
    if catalog.empty:
        st.warning("The OpenRouter catalog is unavailable, so company exploration cannot be shown.")
        return

    options = catalog[["provider_slug", "company"]].dropna().drop_duplicates().sort_values("company")
    labels = dict(zip(options["provider_slug"], options["company"]))
    slugs = options["provider_slug"].tolist()
    preferred = "openai" if "openai" in labels else slugs[0]
    provider_slug = st.selectbox(
        "Company (model origin)", slugs, index=slugs.index(preferred),
        format_func=lambda value: labels.get(value, value), key="openrouter_explorer_company",
    )
    state = company_explorer_state(views, str(provider_slug))
    models = state["catalog"]
    model_pivot = state["model_pivot"]

    latest_activity = (
        pd.Timestamp(state["latest_date"]).strftime("%b %d, %Y")
        if state["latest_date"] is not None else "n/a"
    )
    million_context = f"{int((models['context_length'] >= 1_000_000).sum()):,}" if not models.empty else "0"
    st.markdown(
        kpi_grid_html(
            kpi_card_html("Tokens in stored window", format_metric(state["total_tokens"]), delta="observed activity"),
            kpi_card_html("Catalog entries", f"{len(models):,}", delta="aliases included"),
            kpi_card_html("Latest activity", latest_activity, delta="daily coverage"),
            kpi_card_html("Models with 1M+ context", million_context, delta="current catalog"),
        ),
        unsafe_allow_html=True,
    )

    st.markdown("#### Company activity")
    control_left, control_right = st.columns([1, 1])
    with control_left:
        chart_metric = st.segmented_control(
            "Metric", ["Tokens", "Requests", "Tokens / Request", "Realized Price"],
            default="Tokens", key=f"openrouter_company_metric_{provider_slug}",
        ) if hasattr(st, "segmented_control") else st.radio(
            "Metric", ["Tokens", "Requests", "Tokens / Request", "Realized Price"],
            horizontal=True, key=f"openrouter_company_metric_{provider_slug}",
        )
    with control_right:
        chart_window = st.segmented_control(
            "Window", ["Weekly", "Daily"], default="Daily",
            key=f"openrouter_company_window_v2_{provider_slug}",
        ) if hasattr(st, "segmented_control") else st.radio(
            "Window", ["Weekly", "Daily"], horizontal=True,
            index=1, key=f"openrouter_company_window_v2_{provider_slug}",
        )
    chart_metric = str(chart_metric or "Tokens")
    chart_window = str(chart_window or "Weekly")
    history_cutoff = render_history_range_control(f"openrouter_company_history_{provider_slug}")
    metric_pivots = state["weekly_metrics"] if chart_window == "Weekly" else state["daily_metrics"]
    selected_pivot = _filter_pivot_by_history_range(metric_pivots.get(chart_metric, pd.DataFrame()), history_cutoff)
    if selected_pivot.empty:
        if chart_metric in {"Requests", "Tokens / Request"}:
            st.info(f"No daily {chart_metric.casefold()} observations are available for this company from Apr 16, 2026 yet.")
        elif chart_metric == "Realized Price":
            st.info("No priced-token economics are available for this company yet.")
        else:
            st.info(f"No {chart_window.casefold()} token activity is stored for this company yet.")
    elif chart_metric == "Tokens":
        token_model_pivot = state["weekly_model_pivot"] if chart_window == "Weekly" else model_pivot
        if token_model_pivot.empty:
            token_model_pivot = selected_pivot
        token_model_pivot = _filter_pivot_by_history_range(token_model_pivot, history_cutoff)
        chart = make_stacked_area_chart(
            token_model_pivot, list(token_model_pivot.index), MODEL_COLORS,
            x_title="Usage Week (Starting)" if chart_window == "Weekly" else "Usage Date (Daily)",
            y_title="Tokens", height=430, value_format=",.0f", hover_suffix="tokens",
        )
        chart.update_layout(hovermode="x unified")
        st.plotly_chart(chart, width="stretch", theme=None)
    else:
        y_title = "Requests" if chart_metric == "Requests" else "Tokens / Request" if chart_metric == "Tokens / Request" else "$ per 1M tokens"
        hover_suffix = "requests" if chart_metric == "Requests" else "tokens/request" if chart_metric == "Tokens / Request" else "$ / 1M tokens"
        chart = make_line_chart(
            selected_pivot, [ACCENT], y_title=y_title,
            x_title="Usage Week (Starting)" if chart_window == "Weekly" else "Usage Date (Daily)",
            hover_suffix=hover_suffix, value_format=",.1f" if chart_metric != "Realized Price" else "$,.3f",
        )
        st.plotly_chart(chart, width="stretch", theme=None)
    if chart_metric in {"Requests", "Tokens / Request"}:
        st.caption(
            "Daily request-derived measures are displayed from Apr 16, 2026. Complete model-total rows begin Jun 17, 2026; earlier observations are sparse category-level proxy data and missing dates remain gaps. "
            f"Weekly tokens use {state['weekly_token_source'].casefold()}; weekly requests use {state['weekly_request_source'].casefold()}."
        )
    elif chart_metric == "Tokens":
        st.caption(
            "Token totals prefer complete model-activity rows and use provider daily activity to fill missing route/model days. Exact paid/:free API duplicates are removed; distinct provider-page free traffic is retained."
        )
    elif chart_metric == "Realized Price":
        coverage = state["price_coverage_weekly"] if chart_window == "Weekly" else state["price_coverage_daily"]
        latest_coverage = coverage.iloc[-1, 0] if not coverage.empty else None
        coverage_text = f"Latest priced-token coverage: {float(latest_coverage):.1f}%" if latest_coverage is not None and pd.notna(latest_coverage) else "Priced-token coverage unavailable"
        historical_coverage = state.get("historical_pricing_coverage")
        if historical_coverage is not None and historical_coverage < LOW_PRICING_COVERAGE_THRESHOLD:
            st.warning(
                f"Low historical pricing coverage: {historical_coverage:.1f}% of stored company tokens have priced economics "
                f"(flagged below {LOW_PRICING_COVERAGE_THRESHOLD:.0f}%). Treat this realized-price series as a partial-coverage proxy."
            )
        historical_text = (
            f"Historical priced-token coverage: {historical_coverage:.1f}%"
            if historical_coverage is not None
            else "Historical priced-token coverage unavailable"
        )
        fill_share = state.get("historical_price_fill_share")
        fill_text = (
            f"Historical route-price fills: {float(fill_share):.1f}% of stored tokens"
            if fill_share is not None and float(fill_share) > 0
            else "No historical route-price fills"
        )
        st.caption(f"Blended company realized price from estimated revenue ÷ priced tokens. {coverage_text}; {historical_text}; {fill_text}. Unpriced tokens are excluded from the denominator.")

    st.markdown("#### Models by trailing 30-day token volume")
    st.caption("The stacked model chart selects its named model lines by trailing 30-day token volume, then preserves the full available history so recent leaders are visible without discarding context.")
    if models.empty:
        st.info("No current catalog models are available for this company.")
        return
    company_search = st.text_input(
        "Filter company models",
        placeholder="Search name or model ID, e.g. gpt-5.6",
        key=f"openrouter_company_model_search_{provider_slug}",
    )
    if company_search.strip():
        needle = company_search.strip().casefold()
        models = models[
            models["model_name"].astype(str).str.casefold().str.contains(needle, regex=False)
            | models["model_id"].astype(str).str.casefold().str.contains(needle, regex=False)
        ]
        st.caption(f"{len(models):,} matching models")
        if models.empty:
            st.info("No models match this filter.")
            return
    table = models[[
        "model_name", "model_type", "model_id", "release_date", "context_length",
        "input_price_per_m", "output_price_per_m", "tokens_30d", "observed_days", "activity_source", "openrouter_url",
    ]].copy()
    table["release_date"] = table["release_date"].dt.date
    table = table.rename(columns={
        "model_name": "Model", "model_type": "Type", "model_id": "Model ID", "release_date": "Released",
        "context_length": "Context", "input_price_per_m": "Input $/1M",
        "output_price_per_m": "Output $/1M", "tokens_30d": "Tokens (30d)",
        "observed_days": "Observed days", "activity_source": "Activity source", "openrouter_url": "OpenRouter",
    })
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "Context": st.column_config.NumberColumn(format="compact"),
        "Input $/1M": st.column_config.NumberColumn(format="$%.4g"),
        "Output $/1M": st.column_config.NumberColumn(format="$%.4g"),
        "Tokens (30d)": st.column_config.NumberColumn(format="compact"),
        "Observed days": st.column_config.NumberColumn(format="%d/30"),
        "OpenRouter": st.column_config.LinkColumn(display_text="Open model ↗"),
    })


def _render_model_explorer(views: dict[str, object]) -> None:
    catalog = views.get("catalog", pd.DataFrame())
    if catalog.empty:
        st.warning("The OpenRouter catalog is unavailable, so model exploration cannot be shown.")
        return

    catalog = catalog.sort_values(["tokens_30d", "model_name"], ascending=[False, True]).reset_index(drop=True)
    label_map = {row["model_id"]: f"{row['model_name']} · {row['company']}" for _, row in catalog.iterrows()}
    model_ids = catalog["model_id"].tolist()
    model_id = st.selectbox(
        "Model", model_ids, index=0,
        format_func=lambda value: label_map.get(value, value), key="openrouter_explorer_model",
    )

    state = model_explorer_state(views, str(model_id))
    info = state["info"]
    if info.empty:
        st.info("No catalog metadata is available for this model.")
        return
    info = info.iloc[0]
    released = info["release_date"].strftime("%b %d, %Y") if pd.notna(info["release_date"]) else "n/a"

    st.markdown(f"### {info['model_name']}")
    st.caption(f"{info['company']} · `{info['model_id']}` · [View on OpenRouter ↗]({info['openrouter_url']})")
    st.markdown(
        kpi_grid_html(
            kpi_card_html("Context", _format_context_window(info["context_length"]), delta="model metadata"),
            kpi_card_html("Input", _format_price_per_m(info["input_price_per_m"]), delta="per 1M tokens"),
            kpi_card_html("Output", _format_price_per_m(info["output_price_per_m"]), delta="per 1M tokens"),
            kpi_card_html("Released", released, delta="OpenRouter catalog"),
            kpi_card_html("30d tokens", format_metric(info["tokens_30d"]), delta="observed activity"),
        ),
        unsafe_allow_html=True,
    )
    request_granularity = state.get("request_granularity", "unavailable")
    request_note = (
        " Request traffic is aggregated weekly because daily request coverage is sparse."
        if request_granularity == "weekly"
        else ""
    )
    st.caption(
        f"Activity coverage: {int(info['observed_days'])}/30 days · {info['activity_source']}. "
        "A dash means no activity was observed, not confirmed zero traffic."
        + request_note
    )

    description = _safe_catalog_text(info.get("description"))
    input_modalities = _json_list(info.get("input_modalities_json"))
    output_modalities = _json_list(info.get("output_modalities_json"))
    supported_parameters = _json_list(info.get("supported_parameters_json"))
    if description:
        st.write(description)
    with st.expander("Capabilities and official Models API metadata"):
        meta_left, meta_right = st.columns(2)
        with meta_left:
            st.markdown("**Architecture**")
            st.write(_safe_catalog_text(info.get("architecture_modality")) or _safe_catalog_text(info.get("architecture")) or "n/a")
            st.markdown("**Input → output modalities**")
            st.write(f"{', '.join(input_modalities) or 'n/a'} → {', '.join(output_modalities) or 'n/a'}")
            st.markdown("**Tokenizer / instruction format**")
            tokenizer = _safe_catalog_text(info.get("tokenizer")) or "n/a"
            instruct = _safe_catalog_text(info.get("instruct_type"))
            st.write(f"{tokenizer}{f' · {instruct}' if instruct else ''}")
        with meta_right:
            st.markdown("**Cache pricing**")
            cache_read = _format_price_per_m(info.get("cache_read_price_per_m"))
            cache_write = _format_price_per_m(info.get("cache_write_price_per_m"))
            st.write(f"Read {cache_read} · Write {cache_write}")
            st.markdown("**Top-provider limits**")
            provider_context = _format_context_window(info.get("top_provider_context_length"))
            max_completion = _format_context_window(info.get("top_provider_max_completion_tokens"))
            st.write(f"Context {provider_context} · Max completion {max_completion}")
            st.markdown("**Moderation / knowledge cutoff**")
            moderated = info.get("top_provider_is_moderated")
            moderation_text = "n/a" if pd.isna(moderated) else "Yes" if bool(moderated) else "No"
            st.write(f"Moderated: {moderation_text} · Cutoff: {_safe_catalog_text(info.get('knowledge_cutoff')) or 'n/a'}")
        st.markdown("**Supported request parameters**")
        st.write(", ".join(supported_parameters) if supported_parameters else "Not published")

    st.markdown("#### Activity")
    st.caption("Token volume and, where the model-detail scraper has coverage, request traffic over time.")
    activity = state["activity"]
    if activity.empty:
        st.info("No activity history is stored for this model yet.")
    else:
        fig = go.Figure()
        if "Tokens" in activity and activity["Tokens"].notna().any():
            fig.add_trace(go.Scatter(
                x=activity.index, y=activity["Tokens"], name="Tokens", mode="lines",
                line=dict(color=ACCENT, width=3), fill="tozeroy",
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f} tokens<extra></extra>",
            ))
        if "Requests" in activity and activity["Requests"].notna().any():
            request_label = "Requests (weekly)" if request_granularity == "weekly" else "Requests"
            fig.add_trace(go.Scatter(
                x=activity.index, y=activity["Requests"], name=request_label, mode="lines",
                line=dict(color="#F97316", width=2), yaxis="y2",
                connectgaps=request_granularity == "weekly",
                hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f} requests<extra></extra>",
            ))
        fig.update_layout(
            template="plotly_white", height=420, hovermode="x unified", margin=dict(l=0, r=0, t=15, b=30),
            xaxis=dict(title="Date", showgrid=False), yaxis=dict(title="Tokens", gridcolor=GRID),
            yaxis2=dict(title="Requests", overlaying="y", side="right", showgrid=False),
            legend=dict(orientation="h", y=1.12),
        )
        st.plotly_chart(fig, width="stretch", theme=None)

    detail_left, detail_right = st.columns([1, 1])
    with detail_left:
        st.markdown("#### Workload mix")
        categories = state["categories"]
        if categories.empty:
            st.caption("Category-level request data is not available for this model yet.")
        else:
            display_categories = categories.head(12).rename(columns={"category_slug": "Category"})
            st.dataframe(display_categories, hide_index=True, width="stretch", column_config={
                "Tokens": st.column_config.NumberColumn(format="compact"),
                "Requests": st.column_config.NumberColumn(format="compact"),
            })
    with detail_right:
        st.markdown("#### Public apps")
        apps = state["apps"]
        if apps.empty:
            st.caption("No traffic from the currently monitored public apps is stored for this model.")
        else:
            app_table = apps[["App", "Tokens", "categories", "origin_url"]].rename(columns={
                "categories": "Use cases", "origin_url": "App URL",
            })
            st.dataframe(app_table, hide_index=True, width="stretch", column_config={
                "Tokens": st.column_config.NumberColumn(format="compact"),
                "App URL": st.column_config.LinkColumn(display_text="Visit ↗"),
            })
            st.caption("Coverage reflects the public apps monitored by the daily apps pipeline, not every OpenRouter app.")


def _render_models_catalog(views: dict[str, object]) -> None:
    catalog = views.get("catalog", pd.DataFrame())
    if catalog.empty:
        st.warning("The OpenRouter model catalog is unavailable.")
        return

    st.caption("Current OpenRouter catalog reconstructed from compact change-only snapshots. Click any header to sort.")
    modality_options = sorted({item for value in catalog["input_modalities_json"] for item in _json_list(value)})
    filter_cols = st.columns([2.0, 1.25, 1.05, 1.05, 1.0])
    search = filter_cols[0].text_input("Search models", placeholder="Name or model ID", key="openrouter_catalog_search")
    companies = filter_cols[1].multiselect(
        "Companies", sorted(catalog["company"].dropna().unique().tolist()), key="openrouter_catalog_companies",
    )
    min_context = filter_cols[2].selectbox(
        "Minimum context", [0, 32_000, 128_000, 1_000_000],
        format_func=lambda value: "Any" if value == 0 else _format_context_window(value),
        key="openrouter_catalog_context",
    )
    priced_only = filter_cols[3].toggle("Priced models only", value=False, key="openrouter_catalog_priced")
    input_modality = filter_cols[4].selectbox(
        "Input modality", ["Any", *modality_options], key="openrouter_catalog_input_modality",
    )

    filtered = catalog.copy()
    if search.strip():
        needle = search.strip().casefold()
        filtered = filtered[
            filtered["model_name"].astype(str).str.casefold().str.contains(needle, regex=False)
            | filtered["model_id"].astype(str).str.casefold().str.contains(needle, regex=False)
        ]
    if companies:
        filtered = filtered[filtered["company"].isin(companies)]
    if min_context:
        filtered = filtered[filtered["context_length"] >= min_context]
    if priced_only:
        filtered = filtered[(filtered["pricing_prompt"] > 0) | (filtered["pricing_completion"] > 0)]
    if input_modality != "Any":
        filtered = filtered[filtered["input_modalities_json"].map(lambda value: input_modality in _json_list(value))]
    filtered = filtered.sort_values(["tokens_30d", "model_name"], ascending=[False, True])

    st.caption(f"{len(filtered):,} of {len(catalog):,} current models")
    table = filtered[[
        "model_name", "model_type", "company", "model_id", "release_date", "architecture", "context_length",
        "input_price_per_m", "output_price_per_m", "cache_read_price_per_m", "tokens_30d", "observed_days", "activity_source", "openrouter_url",
    ]].copy()
    table["release_date"] = table["release_date"].dt.date
    table = table.rename(columns={
        "model_name": "Model", "model_type": "Type", "company": "Company", "model_id": "Model ID", "release_date": "Released",
        "architecture": "Modality", "context_length": "Context", "input_price_per_m": "Input $/1M",
        "output_price_per_m": "Output $/1M", "tokens_30d": "Tokens (30d)", "observed_days": "Observed days",
        "cache_read_price_per_m": "Cache read $/1M", "activity_source": "Activity source", "openrouter_url": "Details",
    })
    st.dataframe(table, hide_index=True, width="stretch", height=640, column_config={
        "Context": st.column_config.NumberColumn(format="compact"),
        "Input $/1M": st.column_config.NumberColumn(format="$%.4g"),
        "Output $/1M": st.column_config.NumberColumn(format="$%.4g"),
        "Cache read $/1M": st.column_config.NumberColumn(format="$%.4g"),
        "Tokens (30d)": st.column_config.NumberColumn(format="compact"),
        "Observed days": st.column_config.NumberColumn(format="%d/30"),
        "Details": st.column_config.LinkColumn(display_text="Open ↗"),
    })


def _render_explorer_source_note() -> None:
    st.info(
        "Data source: complete model-activity totals are preferred for model token/request detail; provider daily totals fill token gaps. "
        "Before complete model totals begin, category-only rows may appear as request proxies; they are not complete totals and do not replace provider token totals. "
        "Entries beginning with `~` are OpenRouter latest-routing aliases grouped under the underlying company. "
        "Company means model origin; serving routes such as Amazon, Google, or Anthropic are not treated as model companies.",
        icon="ℹ️",
    )


def _comparison_format_value(metric: str, value: object) -> str:
    if value is None or pd.isna(value):
        return "—"
    number = float(value)
    if metric == "Estimated revenue":
        return f"${number:,.0f}"
    if metric == "Realized price":
        return f"${number:,.3f}"
    if metric == "Tokens / request":
        return f"{number:,.0f}"
    return format_metric(number)


def _format_token_axis_label(value: object) -> str:
    """Format token chart ticks with dashboard units (B/T), not SI ``G``."""
    if value is None or pd.isna(value):
        return "—"
    number = float(value)
    absolute = abs(number)
    if absolute >= 1_000_000_000_000:
        return f"{number / 1_000_000_000_000:.1f}T"
    if absolute >= 1_000_000_000:
        return f"{number / 1_000_000_000:.0f}B"
    if absolute >= 1_000_000:
        return f"{number / 1_000_000:.0f}M"
    return f"{number:,.0f}"


def _comparison_latest_metric(frame: pd.DataFrame, entity_id: str, metric: str) -> tuple[float | None, float | None, pd.Timestamp | None]:
    if frame.empty or metric not in frame.columns:
        return None, None, None
    rows = frame[frame["entity_id"].astype("string").eq(str(entity_id))].sort_values("period_start")
    rows = rows.dropna(subset=[metric])
    if rows.empty:
        return None, None, None
    latest = float(rows.iloc[-1][metric])
    previous = float(rows.iloc[-2][metric]) if len(rows) > 1 else None
    return latest, previous, pd.Timestamp(rows.iloc[-1]["period_start"])


def _comparison_chart(
    frame: pd.DataFrame,
    *,
    entity_ids: tuple[str, ...],
    entity_labels: dict[str, str],
    metric: str,
    window: str,
    normalized: bool,
    transition_markers: list[dict[str, object]] | None = None,
) -> go.Figure:
    selected = frame[frame["entity_id"].astype("string").isin(entity_ids)][["period_start", "entity_id", metric]].copy()
    selected["period_start"] = pd.to_datetime(selected["period_start"], errors="coerce")
    selected[metric] = pd.to_numeric(selected[metric], errors="coerce")
    selected = selected.dropna(subset=["period_start"])
    pivot = selected.pivot_table(index="period_start", columns="entity_id", values=metric, aggfunc="last").sort_index()
    pivot = pivot.reindex(columns=list(entity_ids))
    if not pivot.empty:
        frequency = {"Daily": "D", "7-day avg": "D", "Weekly": "7D", "Monthly": "MS"}[window]
        full_index = pd.date_range(pivot.index.min(), pivot.index.max(), freq=frequency)
        pivot = pivot.reindex(full_index)
    y_title = metric
    if normalized and not pivot.empty:
        if metric in {"Tokens", "Requests", "Estimated revenue"}:
            total = pivot.sum(axis=1, min_count=1)
            pivot = pivot.div(total.where(total.gt(0)), axis=0).mul(100)
            y_title = f"{metric} share (%)"
        else:
            for column in pivot.columns:
                valid = pivot[column].dropna()
                if not valid.empty and float(valid.iloc[0]) != 0:
                    pivot[column] = pivot[column].div(float(valid.iloc[0])).mul(100)
            y_title = f"{metric} index (first observation = 100)"

    figure = go.Figure()
    # Keep comparison colors aligned with the OpenRouter Intelligence palette.
    # The shared palette has distinct colors for the first five series; the
    # previous local list reused the first blue for the fifth company.
    colors = MODEL_COLORS
    raw_token_axis = metric == "Tokens" and not normalized
    for index, entity_id in enumerate(entity_ids):
        if entity_id not in pivot.columns:
            continue
        customdata = None
        if raw_token_axis:
            customdata = [_format_token_axis_label(value) for value in pivot[entity_id]]
        figure.add_trace(go.Scatter(
            x=pivot.index,
            y=pivot[entity_id],
            name=entity_labels.get(entity_id, entity_id),
            mode="lines+markers",
            connectgaps=False,
            line=dict(color=colors[index % len(colors)], width=3),
            marker=dict(size=5),
            customdata=customdata,
            hovertemplate=(
                "<b>%{fullData.name}</b><br>%{customdata}<extra></extra>"
                if raw_token_axis
                else "<b>%{fullData.name}</b><br>%{y:,.2f}<extra></extra>"
                if metric in {"Realized price", "Tokens / request"}
                else "<b>%{fullData.name}</b><br>%{y:,.0f}<extra></extra>"
            ),
        ))
    figure.update_layout(
        template="plotly_white",
        height=460,
        hovermode="x unified",
        margin=dict(l=0, r=0, t=20, b=45),
        xaxis=dict(
            title=(
                "Usage date (7-day rolling average)"
                if window == "7-day avg"
                else "Usage date"
                if window == "Daily"
                else "Usage week/month"
            ),
            showgrid=False,
        ),
        legend=dict(orientation="h", y=1.08),
    )
    if raw_token_axis and not pivot.empty:
        maximum = float(np.nanmax(pivot.to_numpy(dtype=float)))
        if np.isfinite(maximum) and maximum > 0:
            tick_values = np.linspace(0.0, maximum, 6)
            figure.update_yaxes(
                title=y_title,
                gridcolor=GRID,
                tickmode="array",
                tickvals=tick_values.tolist(),
                ticktext=[_format_token_axis_label(value) for value in tick_values],
            )
        else:
            figure.update_yaxes(title=y_title, gridcolor=GRID)
    else:
        figure.update_yaxes(
            title=y_title,
            gridcolor=GRID,
            tickformat=",.2f" if metric in {"Realized price", "Tokens / request"} else (".1f" if normalized else "~s"),
        )
    for marker in transition_markers or []:
        marker_date = pd.to_datetime(marker.get("date"), errors="coerce")
        if pd.isna(marker_date) or pivot.empty or marker_date < pivot.index.min() or marker_date > pivot.index.max():
            continue
        figure.add_vline(
            x=marker_date,
            line=dict(color="#64748B", width=1.5, dash="dash"),
            opacity=0.75,
        )
        figure.add_annotation(
            x=marker_date,
            y=0.98,
            xref="x",
            yref="paper",
            text=str(marker.get("short_label", "Method change")),
            showarrow=False,
            textangle=-90,
            font=dict(size=10, color="#334155"),
            bgcolor="rgba(255,255,255,0.86)",
            bordercolor="rgba(100,116,139,0.45)",
            borderwidth=1,
            xanchor="left",
            yanchor="top",
        )
    return figure


def render_compare(domain_states, datasets) -> None:
    """Render a scalable company-only OpenRouter comparison."""
    _ = domain_states
    st.markdown('<div class="section-title">OpenRouter Compare</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Compare up to five model-origin companies across usage, economics, workload intensity, and realized price.</div>',
        unsafe_allow_html=True,
    )
    views = build_openrouter_comparison_views(
        datasets,
        cache_version=OPENROUTER_COMPARISON_CACHE_VERSION,
    )

    options = views.get("company_options", pd.DataFrame())
    if options.empty:
        st.info("No companies with stored activity are available for comparison yet.")
        return
    ids = options["entity_id"].astype(str).tolist()
    labels = dict(zip(options["entity_id"].astype(str), options["label"].astype(str)))
    preferred = [company for company in ("openai", "anthropic") if company in ids]
    if len(preferred) < 2:
        preferred = ids[: min(2, len(ids))]
    selected_companies = st.multiselect(
        "Companies (select up to 5)",
        ids,
        default=preferred,
        max_selections=5,
        format_func=lambda value: labels.get(value, value),
        key="openrouter_compare_companies",
        help="Choose one to five companies. The chart and latest-comparison table update together.",
    )
    if not selected_companies:
        st.info("Select at least one company to compare.")
        return
    company_ids = tuple(str(company) for company in selected_companies)
    with st.container():
        window = st.segmented_control(
            "Window", list(COMPARISON_WINDOWS), default="7-day avg", key="openrouter_compare_window",
        ) if hasattr(st, "segmented_control") else st.radio(
            "Window", list(COMPARISON_WINDOWS), horizontal=True, index=1, key="openrouter_compare_window",
        )

    source_window = "Daily" if str(window) == "7-day avg" else str(window)
    frame = views["series"]["Companies"].get(source_window, pd.DataFrame()).copy()
    if str(window) == "7-day avg":
        frame = _comparison_rolling_7d_frame(frame)
    metric_control, normalize_control = st.columns([1.5, 1.0])
    with metric_control:
        metric = st.selectbox("Metric", list(COMPARISON_METRICS), key="openrouter_compare_metric")
    with normalize_control:
        normalized = st.toggle("Share / index view", value=False, key="openrouter_compare_normalized")

    if frame.empty or metric not in frame.columns:
        st.info(f"No {str(window).casefold()} {metric.casefold()} history is available for this comparison yet.")
        return
    frame["period_start"] = pd.to_datetime(frame["period_start"], errors="coerce")
    frame = frame.dropna(subset=["period_start"])
    available = frame[frame["entity_id"].astype("string").isin(company_ids)]
    if available.empty or available[metric].notna().sum() == 0:
        st.info(f"No {str(window).casefold()} {metric.casefold()} history is available for the selected companies yet.")
        return

    min_date = available["period_start"].min().date()
    max_date = available["period_start"].max().date()
    date_filter = st.date_input(
        "Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date,
        key="openrouter_compare_date_range",
    )
    date_range = None
    if isinstance(date_filter, (tuple, list)) and len(date_filter) == 2:
        start_date, end_date = pd.Timestamp(date_filter[0]), pd.Timestamp(date_filter[1])
        date_range = (start_date, end_date)
        frame = frame[(frame["period_start"] >= start_date) & (frame["period_start"] <= end_date)]

    labels_for_chart = {company_id: labels.get(company_id, company_id) for company_id in company_ids}
    st.plotly_chart(
        _comparison_chart(frame, entity_ids=company_ids, entity_labels=labels_for_chart,
                          metric=metric, window=str(window), normalized=bool(normalized),
                          transition_markers=views.get("transition_markers", [])),
        width="stretch", theme=None,
    )

    st.markdown("#### Latest comparison")
    rows: list[dict[str, object]] = []
    for metric_name in COMPARISON_METRICS:
        row: dict[str, object] = {"Metric": metric_name}
        latest_dates: list[pd.Timestamp] = []
        for company_id in company_ids:
            value, _, date = _comparison_latest_metric(frame, company_id, metric_name)
            row[labels_for_chart[company_id]] = _comparison_format_value(metric_name, value)
            if date is not None:
                latest_dates.append(date)
        row["Latest period"] = max(latest_dates).strftime("%Y-%m-%d") if latest_dates else "—"
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

    coverage = views.get("coverage", {})
    if str(window) == "7-day avg":
        st.caption(
            "7-day avg is a trailing calendar-day mean of the daily company series. "
            "Tokens/request uses the ratio of trailing token and request sums on overlapping days only; "
            "the first six observations are partial windows."
        )
    st.caption(
        "Company totals retain the longer legacy rankings history and use reconciled model/provider activity for newer periods. "
        "Weekly requests retain the legacy provider request history and use model-detail requests after that feed ends. "
        f"Modern daily token coverage starts {coverage.get('company_tokens_start') or 'when available'}; daily request coverage starts {coverage.get('company_requests_start') or 'when available'}."
    )
    markers = views.get("transition_markers", [])
    if markers:
        st.caption("Method changes marked on the chart: " + " · ".join(str(marker.get("label")) for marker in markers))
    request_interpolations = views.get("request_interpolations", [])
    if request_interpolations:
        estimate_labels = []
        for estimate in request_interpolations:
            entity_id = str(estimate.get("entity_id", ""))
            entity_label = OPENROUTER_PROVIDER_MAP.get(entity_id, entity_id.replace("-", " ").title())
            period = pd.to_datetime(estimate.get("period_start"), errors="coerce")
            if pd.notna(period):
                estimate_labels.append(f"{entity_label} ({period.strftime('%b %-d, %Y')})")
        if estimate_labels:
            st.caption(
                "Request estimates (not source observations): " + ", ".join(estimate_labels) + ". "
                "Each is a linear midpoint between the adjacent observed weekly totals; the source is a top-10 provider ranking. "
                "Longer or unbounded gaps remain blank rather than being treated as zero."
            )
    st.caption(
        "Missing observations remain gaps. Estimated revenue and realized price use priced economics only; free/unpriced tokens are excluded from the realized-price denominator. "
        "The newest week or month may be partial."
    )


def render_data_explorer(datasets: dict[str, DatasetLoadResult]) -> None:
    st.markdown('<div class="section-title">OpenRouter Data Explorer</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Inspect company traffic, model activity and pricing, or search the full current catalog.</div>',
        unsafe_allow_html=True,
    )
    views = build_openrouter_explorer_views(datasets)
    page_view = st.segmented_control(
        "View",
        ["Companies", "Models"],
        default="Companies",
        key="openrouter_models_page_view",
    ) if hasattr(st, "segmented_control") else st.radio(
        "View",
        ["Companies", "Models"],
        horizontal=True,
        key="openrouter_models_page_view",
    )
    if page_view == "Companies":
        _render_company_explorer(views)
    else:
        _render_model_explorer(views)
        st.markdown("#### Full model catalog")
        _render_models_catalog(views)
    _render_explorer_source_note()


def render_models(domain_states, datasets) -> None:
    """Dedicated top-level tab for the OpenRouter catalog and explorer."""
    _ = domain_states
    render_data_explorer(datasets)


def render_workloads(domain_states, datasets) -> None:
    """Render OpenRouter workload composition without loading market economics."""
    _ = domain_states
    render_context_length_section(datasets)
    render_modality_rankings_section(datasets)
    render_apps_tables(datasets)


def render_compute_evolution_section(compute_views: dict[str, object]) -> None:
    """Render the OpenRouter catalog-growth + context-vs-pricing pair inside the OpenRouter tab.

    NOTE: Previously this was `render_compute_availability_section` with AWS Spot + Lambda
    Cloud KPIs and panels. Those sources were removed; only the two OpenRouter catalog
    charts survived and were moved out of the now-deleted HW & Compute tab.
    """
    models_latest = compute_views.get("models_latest", pd.DataFrame())
    models_growth = compute_views.get("models_growth", pd.DataFrame())
    models_history_start = compute_views.get("models_history_start")
    models_history_end = compute_views.get("models_history_end")

    st.markdown('<div class="section-title">Compute Evolution</div>', unsafe_allow_html=True)
    row2_col1, row2_col2 = st.columns(2)

    with row2_col1:
        st.markdown('<div class="section-subtitle">OpenRouter Model Catalog Growth</div>', unsafe_allow_html=True)
        if not models_growth.empty:
            fig_growth = go.Figure()
            fig_growth.add_trace(go.Scatter(
                x=models_growth["snapshot_ts"],
                y=models_growth["model_count"],
                fill='tozeroy',
                line=dict(color=ACCENT, width=3)
            ))
            fig_growth.update_layout(
                title="Model Catalog Growth",
                template="plotly_white",
                height=350,
                margin=dict(l=0, r=0, t=40, b=10)
            )
            st.plotly_chart(fig_growth, width="stretch", theme=None)
            if models_history_start is not None and models_history_end is not None:
                start_label = pd.Timestamp(models_history_start).strftime("%Y-%m-%d")
                end_label = pd.Timestamp(models_history_end).strftime("%Y-%m-%d")
                st.caption(
                    f"History reflects the normalized OpenRouter catalog snapshots currently on disk ({start_label} to {end_label})."
                )
            if len(models_growth) > 1:
                drops = models_growth[models_growth["model_count"].diff() < 0]
                if not drops.empty:
                    st.caption(
                        "Catalog history is change-only between full snapshots. A downward step indicates a full upstream "
                        "catalog refresh removed stale carry-forward models; it should not be read as a precise daily deletion count."
                    )

    with row2_col2:
        st.markdown('<div class="section-subtitle">Context Window vs. Pricing Prompt</div>', unsafe_allow_html=True)
        if not models_latest.empty:
            # Filter for positive pricing to avoid log-scale errors
            plot_df = models_latest[models_latest["pricing_prompt"] > 0].copy()
            
            fig_scatter = go.Figure()
            fig_scatter.add_trace(go.Scatter(
                x=plot_df["context_length"],
                y=plot_df["pricing_prompt"] * 1e6,
                mode="markers",
                marker=dict(
                    size=10,
                    color=ACCENT,
                    opacity=0.5,
                    line=dict(width=1, color="white")
                ),
                text=plot_df["model_id"],
                hovertemplate="<b>%{text}</b><br>Context: %{x:,.0f}<br>Price: $%{y:.2f}/1M<extra></extra>"
            ))
            fig_scatter.update_layout(
                title="Price vs. Context",
                template="plotly_white",
                height=400,
                xaxis_title="Context Length",
                yaxis_title="Price per 1M Tokens ($)",
                yaxis_type="log",
                margin=dict(l=0, r=0, t=40, b=10)
            )
            st.plotly_chart(fig_scatter, width="stretch", theme=None)


def render_official_market_section(datasets: dict[str, DatasetLoadResult]) -> None:
    result = datasets.get("official_model_rankings_daily")
    if result is None or result.frame.empty:
        return
    frame = result.frame.copy()
    frame["usage_date"] = pd.to_datetime(frame["usage_date"], errors="coerce")
    frame["total_tokens"] = pd.to_numeric(frame["total_tokens"], errors="coerce").fillna(0.0)
    frame["is_other"] = frame["is_other"].fillna(False).astype(bool)
    frame = frame.dropna(subset=["usage_date"])
    if frame.empty:
        return

    daily = frame.groupby("usage_date", as_index=False).agg(total_tokens=("total_tokens", "sum")).sort_values("usage_date")
    named = (
        frame[~frame["is_other"]]
        .groupby("usage_date", as_index=False)["total_tokens"]
        .sum()
        .rename(columns={"total_tokens": "named_tokens"})
    )
    daily = daily.merge(named, on="usage_date", how="left").fillna({"named_tokens": 0.0})
    latest_date = daily.iloc[-1]["usage_date"]
    latest_total = float(daily.iloc[-1]["total_tokens"])
    latest_named = float(daily.iloc[-1]["named_tokens"])
    dod = None
    if len(daily) > 1 and float(daily.iloc[-2]["total_tokens"]) > 0:
        dod = (latest_total / float(daily.iloc[-2]["total_tokens"]) - 1.0) * 100.0
    latest_models = frame[(frame["usage_date"] == latest_date) & (~frame["is_other"])].sort_values(
        "total_tokens", ascending=False
    )
    top_model = str(latest_models.iloc[0]["model_permaslug"]) if not latest_models.empty else "—"
    other_share = (latest_total - latest_named) / latest_total * 100.0 if latest_total else 0.0

    st.markdown('<div class="section-title">Official Daily Market Volume</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="rankings-warning"><b>Two complementary sources:</b> this panel uses the documented OpenRouter API '
        '(daily top 50 + Other) for broad market totals. The detailed provider/model pages below retain request, prompt, '
        'completion, category, and revenue granularity that the official aggregate API does not expose.</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        kpi_grid_html(
            kpi_card_html("Latest Daily Tokens", format_metric(latest_total), delta=latest_date.strftime("%b %d, %Y")),
            kpi_card_html(
                "Day-over-Day", f"{dod:+.1f}%" if dod is not None else "—", delta="official daily total",
                delta_class="up" if dod is not None and dod >= 0 else "down" if dod is not None else "flat",
            ),
            kpi_card_html(
                "Top Named Model", top_model[:28] + ("…" if len(top_model) > 28 else ""),
                delta="latest day", value_style="font-size:1.05rem;",
            ),
            kpi_card_html("Other Share", f"{other_share:.1f}%", delta="outside named top 50"),
        ),
        unsafe_allow_html=True,
    )
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily["usage_date"], y=daily["total_tokens"], name="All tokens", mode="lines",
        line=dict(color=ACCENT, width=2.5), fill="tozeroy", fillcolor="rgba(37,99,235,0.10)",
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f} tokens<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=daily["usage_date"], y=daily["named_tokens"], name="Named top models", mode="lines",
        line=dict(color=MODEL_COLORS[2], width=1.5, dash="dot"),
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:,.0f} tokens<extra></extra>",
    ))
    fig.update_layout(
        template="plotly_white", height=350, hovermode="x unified", margin=dict(l=0, r=0, t=10, b=55),
        xaxis=dict(showgrid=False), yaxis=dict(title="Tokens", tickformat="~s", gridcolor=GRID),
        legend=dict(orientation="h", y=-0.18),
    )
    st.plotly_chart(fig, width="stretch", theme=None)
    st.caption(
        f"Source: OpenRouter documented rankings-daily API · Scraped {format_scraped_at_display(result.latest_scraped_at)} · "
        "Official totals are additive and do not overwrite the detailed tracker."
    )


def render(domain_states, datasets) -> None:
    openrouter_views = compute_openrouter_views(
        {
            **domain_states["openrouter_intelligence"][0],
            **domain_states["compute_availability"][0],
        },
        revenue_cache_version=REVENUE_CACHE_VERSION,
    )
    compute_views = compute_compute_availability_views(domain_states["compute_availability"][0])
    render_top_models_chart(datasets, openrouter_views)
    render_revenue_token_section(datasets, openrouter_views)
    render_task_spend_section(openrouter_views)
    render_token_revenue_comparison(openrouter_views)
    render_compute_evolution_section(compute_views)


# ---------------------------------------------------------------------------
# Multi-Provider ARR Run-Rate & August Nowcast Analysis
# ---------------------------------------------------------------------------

TARGET_ARR_PROVIDERS: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
    "moonshotai": "Moonshot (Kimi)",
    "z-ai": "Z.ai (GLM)",
    "deepseek": "DeepSeek",
    "tencent": "Tencent (Hunyuan)",
    "x-ai": "xAI (Grok)",
    "xiaomi": "Xiaomi (MiMo)",
    "minimax": "MiniMax",
    "qwen": "Qwen",
    "meta": "Meta (Llama)",
}

ARR_PROVIDER_COLORS: dict[str, str] = {
    "anthropic": "#d97706",
    "openai": "#0f766e",
    "google": "#2563eb",
    "moonshotai": "#059669",
    "z-ai": "#db2777",
    "deepseek": "#7c3aed",
    "tencent": "#16a34a",
    "x-ai": "#475569",
    "xiaomi": "#ea580c",
    "minimax": "#0284c7",
    "qwen": "#0891b2",
    "meta": "#6366f1",
}


@st.cache_data(ttl=3600)
def compute_arr_nowcasts_summary(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    """Compute historical monthly ARR and 4 August nowcast models for priority providers."""
    rev_res = datasets.get("daily_provider_revenue_estimates")
    if rev_res is None or rev_res.frame.empty:
        return {}

    df = rev_res.frame.copy()
    if "usage_date" not in df.columns or "estimated_revenue" not in df.columns or "provider_slug" not in df.columns:
        return {}

    df["usage_date"] = pd.to_datetime(df["usage_date"], errors="coerce")
    df = df.dropna(subset=["usage_date"])
    max_date = df["usage_date"].max()

    # Exclude incomplete last date
    df_comp = df[df["usage_date"] < max_date].copy()
    df_comp["estimated_revenue"] = pd.to_numeric(df_comp["estimated_revenue"], errors="coerce").fillna(0.0)

    # Filter targets
    df_comp = df_comp[df_comp["provider_slug"].isin(TARGET_ARR_PROVIDERS)].copy()
    if df_comp.empty:
        return {}

    daily = df_comp.groupby(["usage_date", "provider_slug"], as_index=False)["estimated_revenue"].sum()
    daily["year_month"] = daily["usage_date"].dt.to_period("M").astype(str)
    daily["day_of_month"] = daily["usage_date"].dt.day
    daily["is_weekend"] = daily["usage_date"].dt.dayofweek >= 5

    latest_month = daily["year_month"].max()
    complete_months = sorted([m for m in daily["year_month"].unique() if m != latest_month])

    # 1. Historical Complete Months ARR
    monthly_rows = []
    for (m, p), grp in daily[daily["year_month"].isin(complete_months)].groupby(["year_month", "provider_slug"]):
        days_in_m = grp["usage_date"].dt.days_in_month.iloc[0]
        tot = grp["estimated_revenue"].sum()
        arr = (tot / days_in_m) * 365
        monthly_rows.append({"month": m, "date": pd.to_datetime(f"{m}-01"), "provider": p, "revenue": tot, "arr": arr})
    monthly_arr_df = pd.DataFrame(monthly_rows)

    # 2. August Nowcasts
    aug_data = daily[daily["year_month"] == latest_month].copy()
    observed_days = int(aug_data["day_of_month"].max()) if not aug_data.empty else 18
    days_in_latest = 31
    remaining_days = max(days_in_latest - observed_days, 0)

    hist_pacing_months = [f"{pd.Timestamp(latest_month).year}-{m:02d}" for m in range(2, 8)]
    pacing_df = daily[daily["year_month"].isin(hist_pacing_months)].copy()

    nowcast_results = []
    for p, display_name in TARGET_ARR_PROVIDERS.items():
        p_aug = aug_data[aug_data["provider_slug"] == p]
        mtd_rev = float(p_aug["estimated_revenue"].sum()) if not p_aug.empty else 0.0

        # M1: Simple MTD Daily Avg
        m1_arr = (mtd_rev / observed_days) * 365 if observed_days > 0 else 0.0

        # M2: Historical 18-day Pacing Model
        p_ratios = []
        for hm in hist_pacing_months:
            hm_data = pacing_df[(pacing_df["year_month"] == hm) & (pacing_df["provider_slug"] == p)]
            tot = hm_data["estimated_revenue"].sum()
            d18 = hm_data[hm_data["day_of_month"] <= observed_days]["estimated_revenue"].sum()
            if tot > 0:
                p_ratios.append(d18 / tot)

        if len(p_ratios) >= 2:
            p_mean = float(np.mean(p_ratios))
            p_se = float(np.std(p_ratios, ddof=1) / np.sqrt(len(p_ratios)))
            m2_arr = (mtd_rev / p_mean) * 12 if p_mean > 0 else m1_arr
            p_low = max(p_mean - 1.96 * p_se, 0.15)
            p_high = min(p_mean + 1.96 * p_se, 0.95)
            m2_low = (mtd_rev / p_high) * 12
            m2_high = (mtd_rev / p_low) * 12
        else:
            p_mean = 0.57
            m2_arr = (mtd_rev / p_mean) * 12
            m2_low, m2_high = m2_arr * 0.85, m2_arr * 1.15

        # M3 & M4: Latest 7 Days & Seasonality Adjustment
        latest_7_start = max(observed_days - 6, 1)
        p_l7 = p_aug[p_aug["day_of_month"] >= latest_7_start]
        if not p_l7.empty and len(p_l7) >= 4:
            wd_mean = p_l7[~p_l7["is_weekend"]]["estimated_revenue"].mean()
            we_mean = p_l7[p_l7["is_weekend"]]["estimated_revenue"].mean()
            if pd.isna(wd_mean): wd_mean = p_l7["estimated_revenue"].mean()
            if pd.isna(we_mean): we_mean = wd_mean * 0.75

            rem_dates = pd.date_range(f"{latest_month}-{observed_days+1:02d}", f"{latest_month}-{days_in_latest:02d}")
            rem_wd = int((rem_dates.dayofweek < 5).sum())
            rem_we = int((rem_dates.dayofweek >= 5).sum())

            rem_proj = (rem_wd * wd_mean) + (rem_we * we_mean)
            proj_m_tot = mtd_rev + rem_proj
            m3_arr = proj_m_tot * 12

            l7_std = p_l7["estimated_revenue"].std(ddof=1)
            rem_se = np.sqrt(remaining_days) * (l7_std if pd.notna(l7_std) and l7_std > 0 else (wd_mean * 0.1))
            m3_low = (mtd_rev + max(rem_proj - 1.96 * rem_se, 0)) * 12
            m3_high = (mtd_rev + rem_proj + 1.96 * rem_se) * 12

            m4_arr = p_l7["estimated_revenue"].mean() * 365
        else:
            m3_arr = m1_arr
            m3_low, m3_high = m1_arr * 0.9, m1_arr * 1.1
            m4_arr = m1_arr

        # July complete ARR for baseline
        july_data = monthly_arr_df[(monthly_arr_df["month"] == "2026-07") & (monthly_arr_df["provider"] == p)]
        july_arr = float(july_data["arr"].iloc[0]) if not july_data.empty else 0.0

        nowcast_results.append({
            "provider": p,
            "display_name": display_name,
            "mtd_revenue": mtd_rev,
            "july_arr": july_arr,
            "m1_arr": m1_arr,
            "m2_arr": m2_arr,
            "m2_low": m2_low,
            "m2_high": m2_high,
            "m3_arr": m3_arr,
            "m3_low": m3_low,
            "m3_high": m3_high,
            "m4_arr": m4_arr,
            "p_mean": p_mean,
        })

    nowcast_df = pd.DataFrame(nowcast_results).sort_values("m3_arr", ascending=False).reset_index(drop=True)
    total_m3 = nowcast_df["m3_arr"].sum()
    total_m4 = nowcast_df["m4_arr"].sum()
    nowcast_df["m3_share"] = (nowcast_df["m3_arr"] / total_m3 * 100) if total_m3 > 0 else 0
    nowcast_df["m4_share"] = (nowcast_df["m4_arr"] / total_m4 * 100) if total_m4 > 0 else 0

    return {
        "monthly_arr_df": monthly_arr_df,
        "nowcast_df": nowcast_df,
        "observed_days": observed_days,
        "latest_month": latest_month,
        "as_of_date": max_date - pd.Timedelta(days=1),
    }


def render_arr_nowcast_section(datasets: dict[str, DatasetLoadResult]) -> None:
    """Render dedicated ARR run-rates, nowcast models, and multi-provider market trajectory."""
    data = compute_arr_nowcasts_summary(datasets)
    if not data:
        st.info("Revenue estimates data is not available for ARR nowcast modeling.")
        return

    nowcast_df = data["nowcast_df"]
    monthly_arr_df = data["monthly_arr_df"]
    observed_days = data["observed_days"]
    latest_month = data["latest_month"]
    as_of = data["as_of_date"].strftime("%b %d, %Y")

    st.markdown('<div class="section-title">🚀 Multi-Provider ARR Run-Rate &amp; August Nowcast</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="section-subtitle">Annualized revenue run-rates across 12 major LLM labs on OpenRouter. '
        f'Complete historical months use calendar totals &times; 365/days; {latest_month} is nowcasted using 4 statistical methods '
        f'across {observed_days} complete MTD days through {as_of}.</div>',
        unsafe_allow_html=True,
    )

    tot_m3 = nowcast_df["m3_arr"].sum() / 1e6
    tot_m4 = nowcast_df["m4_arr"].sum() / 1e6
    top1 = nowcast_df.iloc[0]
    top2 = nowcast_df.iloc[1]

    st.markdown(
        kpi_grid_html(
            kpi_card_html("Top-12 Total ARR Nowcast", f"${tot_m3:,.0f}M", delta=f"${tot_m4:,.0f}M by M4 latest-7d"),
            kpi_card_html(f"Top 1: {top1['display_name']}", f"${top1['m3_arr']/1e6:,.0f}M", delta=f"{top1['m3_share']:.1f}% market share"),
            kpi_card_html(f"Top 2: {top2['display_name']}", f"${top2['m3_arr']/1e6:,.0f}M", delta=f"{top2['m3_share']:.1f}% market share"),
            kpi_card_html("MTD Complete Days", f"{observed_days} / 31 days", delta="incomplete max date excluded", delta_class="flat"),
        ),
        unsafe_allow_html=True,
    )

    col_c1, col_c2 = st.columns([1, 1])
    with col_c1:
        view_tab = st.segmented_control("ARR View", ["August Nowcast Ranking", "Monthly Trajectories (2025-2026)"], default="August Nowcast Ranking", key="arr_view_select") if hasattr(st, "segmented_control") else st.radio("ARR View", ["August Nowcast Ranking", "Monthly Trajectories (2025-2026)"], horizontal=True, key="arr_view_select")
    with col_c2:
        nowcast_metric = st.segmented_control("Nowcast Model Benchmark", ["M3: Seasonally-Adjusted (Recommended)", "M4: Latest 7-Day Run-Rate"], default="M3: Seasonally-Adjusted (Recommended)", key="arr_metric_select") if hasattr(st, "segmented_control") else st.radio("Nowcast Model Benchmark", ["M3: Seasonally-Adjusted (Recommended)", "M4: Latest 7-Day Run-Rate"], horizontal=True, key="arr_metric_select")

    is_m3 = "M3" in str(nowcast_metric)

    if "Ranking" in str(view_tab):
        chart_df = nowcast_df.sort_values("m3_arr" if is_m3 else "m4_arr", ascending=True).copy()

        fig = go.Figure()
        arr_vals = chart_df["m3_arr"] / 1e6 if is_m3 else chart_df["m4_arr"] / 1e6
        err_plus = (chart_df["m3_high"] - chart_df["m3_arr"]) / 1e6 if is_m3 else None
        err_minus = (chart_df["m3_arr"] - chart_df["m3_low"]) / 1e6 if is_m3 else None

        fig.add_trace(go.Bar(
            y=chart_df["display_name"],
            x=arr_vals,
            orientation="h",
            marker=dict(color=[MODEL_COLORS[i % len(MODEL_COLORS)] for i in range(len(chart_df))], opacity=0.9),
            error_x=dict(type="data", symmetric=False, array=err_plus, arrayminus=err_minus, color="#0f172a", thickness=1.5, width=4) if is_m3 else None,
            text=[f"${v:,.1f}M ({s:.1f}% share)" for v, s in zip(arr_vals, chart_df["m3_share" if is_m3 else "m4_share"])],
            textposition="auto",
            name="August Nowcast ARR ($M)",
        ))

        fig.update_layout(
            template="plotly_white",
            height=480,
            margin=dict(l=10, r=20, t=20, b=30),
            xaxis=dict(title="Annualized Run Rate ($M)", gridcolor=GRID),
            yaxis=dict(autorange="reversed"),
            showlegend=False,
        )
        st.plotly_chart(fig, width="stretch", theme=None)
        st.caption("Error bars denote the 95% confidence interval for M3 (seasonally-adjusted weekday/weekend residual standard error propagated to the remaining 13 days of August).")

    else:
        # Dynamic provider multiselect: allow selecting all or custom providers (default to top 6)
        all_p_options = nowcast_df["provider"].tolist()
        p_name_map = dict(zip(nowcast_df["provider"], nowcast_df["display_name"]))
        default_top = all_p_options[:6]

        selected_traj_p = st.multiselect(
            "Select Providers to Display in Trajectory",
            options=all_p_options,
            default=default_top,
            format_func=lambda x: p_name_map.get(x, x),
            key="arr_traj_provider_multiselect",
        )
        if not selected_traj_p:
            selected_traj_p = default_top

        traj_df = monthly_arr_df[monthly_arr_df["provider"].isin(selected_traj_p)].copy()
        pivot_traj = traj_df.pivot(index="date", columns="provider", values="arr") / 1e6

        fig_traj = go.Figure()
        for idx_p, p in enumerate(selected_traj_p):
            p_color = MODEL_COLORS[idx_p % len(MODEL_COLORS)]
            if p in pivot_traj.columns:
                fig_traj.add_trace(go.Scatter(
                    x=pivot_traj.index,
                    y=pivot_traj[p],
                    name=TARGET_ARR_PROVIDERS[p],
                    mode="lines+markers",
                    line=dict(color=p_color, width=2.5),
                    marker=dict(size=5),
                ))

        aug_dt = pd.to_datetime(f"{latest_month}-01")
        for idx_p, p in enumerate(selected_traj_p):
            p_rows = nowcast_df[nowcast_df["provider"] == p]
            if p_rows.empty:
                continue
            r = p_rows.iloc[0]
            p_color = MODEL_COLORS[idx_p % len(MODEL_COLORS)]
            val = r["m3_arr"] / 1e6 if is_m3 else r["m4_arr"] / 1e6
            fig_traj.add_trace(go.Scatter(
                x=[aug_dt],
                y=[val],
                mode="markers",
                marker=dict(color=p_color, size=10, symbol="diamond"),
                error_y=dict(type="data", symmetric=False, array=[(r["m3_high"]-r["m3_arr"])/1e6], arrayminus=[(r["m3_arr"]-r["m3_low"])/1e6], color="#0f172a", thickness=1.5, width=4) if is_m3 else None,
                showlegend=False,
                hovertext=f"{r['display_name']} Aug Nowcast: ${val:,.1f}M",
            ))

        fig_traj.update_layout(
            template="plotly_white",
            height=460,
            hovermode="x unified",
            margin=dict(l=10, r=20, t=20, b=40),
            xaxis=dict(showgrid=False),
            yaxis=dict(title="Annualized ARR ($M)", gridcolor=GRID, tickprefix="$", ticksuffix="M"),
            legend=dict(orientation="h", y=-0.15),
        )
        st.plotly_chart(fig_traj, width="stretch", theme=None)
        st.caption(f"Solid lines: complete months (through 2026-07). Diamonds: August 2026 MTD Nowcast estimates.")

    with st.expander("📊 Full 12-Provider ARR Model Comparison Table & Pacing Metrics", expanded=False):
        table_disp = nowcast_df.copy()
        table_disp["July Complete ARR"] = table_disp["july_arr"].map(lambda v: f"${v/1e6:,.1f}M" if v > 0 else "—")
        table_disp["M1: Simple MTD"] = table_disp["m1_arr"].map(lambda v: f"${v/1e6:,.1f}M")
        table_disp["M2: 18-Day Pacing (95% CI)"] = table_disp.apply(lambda r: f"${r['m2_arr']/1e6:,.1f}M (${r['m2_low']/1e6:,.0f}M–${r['m2_high']/1e6:,.0f}M)", axis=1)
        table_disp["M3: Seasonally-Adjusted (95% CI)"] = table_disp.apply(lambda r: f"${r['m3_arr']/1e6:,.1f}M (${r['m3_low']/1e6:,.0f}M–${r['m3_high']/1e6:,.0f}M)", axis=1)
        table_disp["M4: Latest 7-Day Run Rate"] = table_disp["m4_arr"].map(lambda v: f"${v/1e6:,.1f}M")
        table_disp["M3 vs July (%)"] = table_disp.apply(lambda r: f"{(r['m3_arr']/r['july_arr']-1)*100:+.1f}%" if r['july_arr'] > 0 else "N/A", axis=1)
        table_disp["Market Share"] = table_disp["m3_share"].map(lambda v: f"{v:.1f}%")

        cols_to_show = ["display_name", "Market Share", "July Complete ARR", "M3: Seasonally-Adjusted (95% CI)", "M4: Latest 7-Day Run Rate", "M1: Simple MTD", "M2: 18-Day Pacing (95% CI)", "M3 vs July (%)"]
        st.dataframe(table_disp[cols_to_show].rename(columns={"display_name": "Provider"}), width="stretch", hide_index=True)

    st.markdown("---")


# ---------------------------------------------------------------------------
# Cloud & Inference Infrastructure Providers Section
# ---------------------------------------------------------------------------

INFRA_PROVIDER_SLUGS = {
    "coreweave", "deepinfra", "together", "fireworks", "nebius", "novita",
    "groq", "cerebras", "azure", "amazon-bedrock", "chutes", "crusoe",
    "sambanova", "siliconflow", "modal", "baseten", "friendli", "digitalocean",
    "gmicloud", "streamlake", "atlas-cloud", "parasail", "decart", "open-inference",
    "venice", "morph", "inceptron", "akashml", "modelrun", "ambient", "claude-on-aws",
    "nextbit", "sail-research", "wafer", "phala", "ionstream", "io-net", "relace",
    "darkbloom", "seed", "aion-labs", "mancer", "mara", "inception", "crucible",
    "perceptron", "switchpoint", "cloudflare",
}

LLM_ORIGIN_MAPPING = {
    "deepseek": "DeepSeek",
    "meta-llama": "Meta",
    "meta": "Meta",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "z-ai": "智谱AI (Z.ai)",
    "qwen": "Alibaba (Qwen)",
    "alibaba": "Alibaba (Qwen)",
    "minimax": "MiniMax",
    "moonshotai": "Moonshot AI",
    "google": "Google",
    "mistralai": "Mistral AI",
    "x-ai": "xAI (Grok)",
    "xiaomi": "Xiaomi",
    "tencent": "Tencent",
    "stepfun": "StepFun",
    "nvidia": "Nvidia",
    "ibm-granite": "IBM",
    "cohere": "Cohere",
    "perplexity": "Perplexity",
}


def _derive_origin_lab(slug: str) -> str:
    if not slug or "/" not in str(slug):
        return "Other"
    prefix = str(slug).split("/")[0].lower()
    return LLM_ORIGIN_MAPPING.get(prefix, prefix.capitalize())


def _load_cloud_infra_economics() -> pd.DataFrame:
    candidates = [
        Path("data/normalized/marts/daily_cloud_infra_economics.parquet"),
        Path("/Users/henrywzh/Quant/alternative-data-arr/data/normalized/marts/daily_cloud_infra_economics.parquet"),
        Path("/Users/henrywzh/Desktop/Quant/alternative-data/data/normalized/marts/daily_cloud_infra_economics.parquet"),
    ]
    for p in candidates:
        if p.exists():
            try:
                df = pd.read_parquet(p)
                if not df.empty:
                    df["origin_lab"] = df["model_permaslug"].apply(_derive_origin_lab)
                    return df
            except Exception:
                pass
    return pd.DataFrame()


def render_cloud_infra_section(datasets: dict[str, DatasetLoadResult]) -> None:
    st.markdown('<div class="section-title">☁️ Cloud & Inference Infrastructure Providers</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Daily token volume, estimated revenue, and hosting distribution across 88+ underlying hosting and inference providers on OpenRouter (CoreWeave, DeepInfra, Amazon Bedrock, Azure, Novita, SiliconFlow, Cerebras, Groq, Nebius, Together, etc.).</div>',
        unsafe_allow_html=True,
    )

    df = _load_cloud_infra_economics()
    if df.empty:
        st.warning("Cloud infra economics dataset not found. Please run the extractor script.")
        return

    df = df.copy()
    df["is_infra"] = df["provider_slug"].isin(INFRA_PROVIDER_SLUGS)
    df["category"] = df["is_infra"].map(lambda x: "Cloud & Inference Infra" if x else "1st-Party Model Lab")
    df["usage_date_dt"] = pd.to_datetime(df["usage_date"], errors="coerce")

    # 1. Top KPI cards
    infra_only = df[df["is_infra"]]
    cw_df = df[df["provider_slug"] == "coreweave"]

    total_infra_tokens = infra_only["total_tokens"].sum()
    total_infra_rev = infra_only["estimated_revenue"].sum()
    cw_tokens = cw_df["total_tokens"].sum()
    cw_rev = cw_df["estimated_revenue"].sum()
    cw_top_model = cw_df.groupby("model_permaslug")["total_tokens"].sum().idxmax() if not cw_df.empty else "N/A"
    cw_top_model_clean = cw_top_model.split("/")[-1].split("-202")[0]

    top_tok_prov = infra_only.groupby("provider_name")["total_tokens"].sum().idxmax() if not infra_only.empty else "N/A"
    top_rev_prov = infra_only.groupby("provider_name")["estimated_revenue"].sum().idxmax() if not infra_only.empty else "N/A"

    kpi_cards = [
        kpi_card_html("Total Infra Tokens (90d)", f"{total_infra_tokens/1e12:.1f}T", delta="+24.8% vs Q2", delta_class="up"),
        kpi_card_html("Total Infra Revenue (90d)", f"${total_infra_rev/1e6:.1f}M", delta="48 infra providers", delta_class="flat"),
        kpi_card_html("Top Infra by Tokens", top_tok_prov, delta=f"Rev Leader: {top_rev_prov}", delta_class="flat"),
        kpi_card_html("CoreWeave (New)", f"{cw_tokens/1e12:.2f}T Tokens", delta=f"${cw_rev/1e6:.2f}M · Top: {cw_top_model_clean}", delta_class="up"),
    ]
    st.markdown(kpi_grid_html(*kpi_cards), unsafe_allow_html=True)

    # 2. Main Market Trajectory (Stacked Flow Area Chart)
    st.markdown('<div class="section-title">🌊 Inference & Cloud Infrastructure Volume Trajectory</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns([1.4, 1.1, 0.9, 1.0])
    with c1:
        scope = st.radio(
            "Provider Scope",
            ["Cloud & Inference Infra (48)", "All Providers (88)", "1st-Party Model Labs (39)"],
            horizontal=True,
            key="infra_scope_radio",
        )
    with c2:
        metric = st.selectbox(
            "Metric",
            ["Estimated Revenue ($)", "Tokens", "Revenue Share (%)", "Token Share (%)"],
            key="infra_metric_select",
        )
    with c3:
        window = st.radio(
            "Window",
            ["Daily (Raw)", "7-Day Moving Avg"],
            horizontal=True,
            key="infra_window_radio",
        )
    with c4:
        chart_style = st.radio(
            "Chart Style",
            ["Stacked Area (Flow)", "Multi-Line"],
            horizontal=True,
            key="infra_chart_style_radio",
        )

    if "Inference Infra" in scope:
        filtered_df = df[df["is_infra"]].copy()
    elif "1st-Party" in scope:
        filtered_df = df[~df["is_infra"]].copy()
    else:
        filtered_df = df.copy()

    val_col = "estimated_revenue" if "Revenue" in metric else "total_tokens"
    pivot_daily = filtered_df.pivot_table(index="usage_date", columns="provider_name", values=val_col, aggfunc="sum").fillna(0).sort_index()

    if window == "7-Day Moving Avg":
        pivot_chart = pivot_daily.rolling(7, min_periods=1).mean()
    else:
        pivot_chart = pivot_daily.copy()

    if "Share" in metric:
        row_sums = pivot_chart.sum(axis=1).replace(0, np.nan)
        pivot_chart = pivot_chart.div(row_sums, axis=0) * 100.0

    provider_totals = filtered_df.groupby("provider_name")[val_col].sum().sort_values(ascending=False)
    all_provs = provider_totals.index.tolist()
    default_top = all_provs[:8]
    if "CoreWeave" in all_provs and "CoreWeave" not in default_top:
        default_top.append("CoreWeave")

    selected_provs = st.multiselect(
        "Select Providers to Display (Default: Top Providers + CoreWeave)",
        options=all_provs,
        default=default_top,
        key="infra_prov_multiselect",
    )

    if selected_provs:
        chart_df = pivot_chart[[p for p in selected_provs if p in pivot_chart.columns]].copy()
        fig = go.Figure()
        is_stacked = ("Stacked" in chart_style) or ("Share" in metric)
        for idx, col in enumerate(chart_df.columns):
            color = MODEL_COLORS[idx % len(MODEL_COLORS)]
            y_vals = chart_df[col]
            hover_suffix = "$%{y:,.2f}" if metric == "Estimated Revenue ($)" else ("%{y:,.0f} tokens" if metric == "Tokens" else "%{y:.1f}% share")
            fig.add_trace(go.Scatter(
                x=chart_df.index,
                y=y_vals,
                name=col,
                mode="lines",
                stackgroup="one" if is_stacked else None,
                line=dict(width=0.8 if is_stacked else 2.5, color=color),
                hovertemplate=f"<b>{col}</b><br>%{{x}}<br>{hover_suffix}<extra></extra>",
            ))

        y_title = (
            "Estimated Daily Revenue ($)" if metric == "Estimated Revenue ($)" else
            "Daily Tokens" if metric == "Tokens" else
            "Share (%)"
        )
        fig.update_layout(
            height=480,
            plot_bgcolor="rgba(0,0,0,0)",
            paper_bgcolor="rgba(0,0,0,0)",
            hovermode="x unified",
            margin=dict(l=10, r=20, t=20, b=40),
            xaxis=dict(showgrid=False),
            yaxis=dict(title=y_title, gridcolor=GRID),
            legend=dict(orientation="h", y=-0.18),
        )
        st.plotly_chart(fig, width="stretch", theme=None)
    else:
        st.info("Please select at least one provider to view chart.")

    st.markdown("---")

    # 3. NEW: Routing & Infrastructure Breakdown per LLM Lab (Model Origin)
    st.markdown('<div class="section-title">🏢 Hosting & Infrastructure Breakdown per LLM Lab</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">For any LLM creator (DeepSeek, Meta Llama, OpenAI, Anthropic, MiniMax, Z.ai, Qwen, etc.), examine how their token volume is routed between 1st-party endpoints and 3rd-party Cloud & Inference Infra (CoreWeave, DeepInfra, Bedrock, Azure, Novita, etc.).</div>',
        unsafe_allow_html=True,
    )

    available_labs = [
        "DeepSeek", "Meta", "OpenAI", "Anthropic", "智谱AI (Z.ai)",
        "Alibaba (Qwen)", "MiniMax", "Moonshot AI", "Google", "Mistral AI",
        "xAI (Grok)", "Xiaomi", "Tencent", "StepFun", "Nvidia"
    ]
    lab_col1, lab_col2 = st.columns([1.5, 1.0])
    with lab_col1:
        selected_lab = st.selectbox(
            "Select LLM Model Lab / Creator",
            options=[l for l in available_labs if l in df["origin_lab"].unique()],
            index=0,
            key="infra_lab_select",
        )
    with lab_col2:
        lab_metric = st.radio(
            "Lab Breakdown Metric",
            ["Tokens", "Estimated Revenue ($)"],
            horizontal=True,
            key="infra_lab_metric_radio",
        )

    lab_df = df[df["origin_lab"] == selected_lab].copy()
    if not lab_df.empty:
        lab_total_tokens = lab_df["total_tokens"].sum()
        lab_total_rev = lab_df["estimated_revenue"].sum()
        lab_1st_party = lab_df[~lab_df["is_infra"]]
        lab_infra = lab_df[lab_df["is_infra"]]
        lab_1st_tokens = lab_1st_party["total_tokens"].sum()
        lab_infra_tokens = lab_infra["total_tokens"].sum()
        infra_share_pct = (lab_infra_tokens / lab_total_tokens * 100) if lab_total_tokens > 0 else 0.0
        direct_share_pct = 100.0 - infra_share_pct
        top_ext_host = lab_infra.groupby("provider_name")["total_tokens"].sum().idxmax() if not lab_infra.empty else "None"

        lab_kpi_cards = [
            kpi_card_html(f"{selected_lab} Total Volume", f"{lab_total_tokens/1e12:.2f}T" if lab_total_tokens>=1e12 else f"{lab_total_tokens/1e9:.1f}B", delta=f"${lab_total_rev/1e6:.2f}M est. revenue", delta_class="flat"),
            kpi_card_html("1st-Party Direct Share", f"{direct_share_pct:.1f}%", delta=f"{lab_1st_tokens/1e12:.2f}T tokens" if lab_1st_tokens>=1e12 else f"{lab_1st_tokens/1e9:.1f}B tokens", delta_class="flat"),
            kpi_card_html("3rd-Party Cloud Infra Share", f"{infra_share_pct:.1f}%", delta=f"{lab_infra_tokens/1e12:.2f}T tokens" if lab_infra_tokens>=1e12 else f"{lab_infra_tokens/1e9:.1f}B tokens", delta_class="up" if infra_share_pct>20 else "flat"),
            kpi_card_html("Top External Host", top_ext_host, delta="Leading 3rd-party inference provider", delta_class="flat"),
        ]
        st.markdown(kpi_grid_html(*lab_kpi_cards), unsafe_allow_html=True)

        val_col_lab = "estimated_revenue" if "Revenue" in lab_metric else "total_tokens"
        lab_pivot = lab_df.pivot_table(index="usage_date", columns="provider_name", values=val_col_lab, aggfunc="sum").fillna(0).sort_index()
        # Top 7 hosts + Other
        top_hosts = lab_pivot.sum().sort_values(ascending=False).head(7).index.tolist()
        lab_chart_df = lab_pivot[top_hosts].copy()
        other_hosts = [c for c in lab_pivot.columns if c not in top_hosts]
        if other_hosts:
            lab_chart_df["Other Providers"] = lab_pivot[other_hosts].sum(axis=1)

        col_lab_left, col_lab_right = st.columns([1.6, 1.0])
        with col_lab_left:
            st.markdown(f"**{selected_lab} Daily Token / Revenue Flow by Serving Provider**")
            fig_lab = go.Figure()
            for idx, c in enumerate(lab_chart_df.columns):
                color = MODEL_COLORS[idx % len(MODEL_COLORS)]
                hover_s = "$%{y:,.2f}" if "Revenue" in lab_metric else "%{y:,.0f} tokens"
                fig_lab.add_trace(go.Scatter(
                    x=lab_chart_df.index,
                    y=lab_chart_df[c],
                    name=c,
                    mode="lines",
                    stackgroup="one",
                    line=dict(width=0.5, color=color),
                    hovertemplate=f"<b>{c}</b><br>%{{x}}<br>{hover_s}<extra></extra>",
                ))
            fig_lab.update_layout(
                height=380,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                hovermode="x unified",
                margin=dict(l=10, r=20, t=10, b=30),
                xaxis=dict(showgrid=False),
                yaxis=dict(title="Daily Tokens" if "Tokens" in lab_metric else "Daily Revenue ($)", gridcolor=GRID),
                legend=dict(orientation="h", y=-0.2),
            )
            st.plotly_chart(fig_lab, width="stretch", theme=None)

        with col_lab_right:
            st.markdown(f"**Hosting Provider Share for {selected_lab}**")
            host_summary = lab_df.groupby(["provider_name", "category"]).agg(
                total_tokens=("total_tokens", "sum"),
                total_revenue=("estimated_revenue", "sum"),
            ).sort_values("total_tokens", ascending=False).reset_index()
            host_summary["Share"] = (host_summary["total_tokens"] / lab_total_tokens * 100).map(lambda v: f"{v:.1f}%")
            host_summary["Tokens"] = host_summary["total_tokens"].map(lambda v: f"{v/1e12:.2f}T" if v>=1e12 else f"{v/1e9:.2f}B" if v>=1e9 else f"{v/1e6:.1f}M")
            host_summary["Revenue"] = host_summary["total_revenue"].map(lambda v: f"${v/1e6:.2f}M" if v>=1e6 else f"${v/1e3:.1f}k" if v>=1e3 else f"${v:.1f}")
            st.dataframe(
                host_summary[["provider_name", "category", "Tokens", "Revenue", "Share"]].rename(columns={"provider_name": "Serving Host", "category": "Type"}),
                width="stretch",
                hide_index=True,
                height=360,
            )

    st.markdown("---")

    # 4. Provider Deep Dive Explorer
    st.markdown('<div class="section-title">🔍 Single Provider Deep Dive & Hosted Models</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-subtitle">Examine model portfolio, daily token trajectory, and realized economics for any specific hosting provider.</div>', unsafe_allow_html=True)

    all_provider_options = sorted(df["provider_name"].unique().tolist())
    cw_default_idx = all_provider_options.index("CoreWeave") if "CoreWeave" in all_provider_options else 0
    target_provider = st.selectbox(
        "Select Provider to Inspect",
        options=all_provider_options,
        index=cw_default_idx,
        key="infra_deepdive_select",
    )

    single_df = df[df["provider_name"] == target_provider].copy()
    if not single_df.empty:
        p_slug = single_df["provider_slug"].iloc[0]
        p_hq = single_df["headquarters"].iloc[0] or "N/A"
        p_dc = single_df["datacenters"].iloc[0] or "N/A"
        p_tokens = single_df["total_tokens"].sum()
        p_rev = single_df["estimated_revenue"].sum()
        p_realized_price = (p_rev / p_tokens * 1e6) if p_tokens > 0 else 0.0
        p_models_count = single_df["model_permaslug"].nunique()
        p_first_date = single_df["usage_date"].min()
        p_last_date = single_df["usage_date"].max()

        p_cards = [
            kpi_card_html("Cumulative Tokens", f"{p_tokens/1e12:.3f}T" if p_tokens >= 1e12 else f"{p_tokens/1e9:.2f}B", delta=f"{p_first_date} -> {p_last_date}", delta_class="flat"),
            kpi_card_html("Estimated Revenue", f"${p_rev/1e6:.2f}M" if p_rev >= 1e6 else f"${p_rev/1e3:.1f}k", delta="Blended GMV", delta_class="flat"),
            kpi_card_html("Realized Avg Price", f"${p_realized_price:.3f}", delta="per 1M tokens", delta_class="flat"),
            kpi_card_html("Hosted Models", f"{p_models_count} models", delta=f"HQ: {p_hq} · DC: {p_dc}", delta_class="flat"),
        ]
        st.markdown(kpi_grid_html(*p_cards), unsafe_allow_html=True)

        col_left, col_right = st.columns([1.6, 1.0])
        with col_left:
            st.markdown(f"**{target_provider} Daily Token Breakdown by Model**")
            model_pivot = single_df.pivot_table(index="usage_date", columns="model_permaslug", values="total_tokens", aggfunc="sum").fillna(0).sort_index()
            top_models_single = model_pivot.sum().sort_values(ascending=False).head(6).index.tolist()
            model_chart_df = model_pivot[top_models_single].copy()
            other_cols = [c for c in model_pivot.columns if c not in top_models_single]
            if other_cols:
                model_chart_df["Other Models"] = model_pivot[other_cols].sum(axis=1)

            fig_single = go.Figure()
            for idx, c in enumerate(model_chart_df.columns):
                clean_name = c.split("/")[-1].split("-202")[0]
                fig_single.add_trace(go.Scatter(
                    x=model_chart_df.index,
                    y=model_chart_df[c],
                    name=clean_name,
                    mode="lines",
                    stackgroup="one",
                    line=dict(width=0.5, color=MODEL_COLORS[idx % len(MODEL_COLORS)]),
                    hovertemplate=f"<b>{clean_name}</b><br>%{{x}}<br>%{{y:,.0f}} tokens<extra></extra>",
                ))
            fig_single.update_layout(
                height=360,
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                hovermode="x unified",
                margin=dict(l=10, r=20, t=10, b=30),
                xaxis=dict(showgrid=False),
                yaxis=dict(title="Daily Tokens", gridcolor=GRID),
                legend=dict(orientation="h", y=-0.2),
            )
            st.plotly_chart(fig_single, width="stretch", theme=None)

        with col_right:
            st.markdown(f"**Top Hosted Models on {target_provider}**")
            model_summary = single_df.groupby("model_permaslug").agg(
                total_tokens=("total_tokens", "sum"),
                total_revenue=("estimated_revenue", "sum"),
                unit_price=("blended_price", "mean"),
            ).sort_values("total_tokens", ascending=False).reset_index()
            model_summary["Share"] = (model_summary["total_tokens"] / p_tokens * 100).map(lambda v: f"{v:.1f}%")
            model_summary["Tokens"] = model_summary["total_tokens"].map(lambda v: f"{v/1e12:.2f}T" if v>=1e12 else f"{v/1e9:.2f}B" if v>=1e9 else f"{v/1e6:.1f}M")
            model_summary["Est Revenue"] = model_summary["total_revenue"].map(lambda v: f"${v/1e6:.2f}M" if v>=1e6 else f"${v/1e3:.1f}k" if v>=1e3 else f"${v:.1f}")
            model_summary["$/M"] = (model_summary["unit_price"] * 1e6).map(lambda v: f"${v:.3f}")
            model_summary["Model"] = model_summary["model_permaslug"].map(lambda v: v.split("/")[-1].split("-202")[0])
            st.dataframe(
                model_summary[["Model", "Tokens", "Est Revenue", "$/M", "Share"]],
                width="stretch",
                hide_index=True,
                height=340,
            )

    st.markdown("---")

    # 5. Full Provider Market Leaderboard Table
    with st.expander("📊 Full 88-Provider Cloud & Inference Infrastructure Matrix", expanded=False):
        leaderboard = df.groupby(["provider_slug", "provider_name", "category", "headquarters"]).agg(
            total_tokens=("total_tokens", "sum"),
            total_revenue=("estimated_revenue", "sum"),
            models_count=("model_permaslug", "nunique"),
            active_days=("usage_date", "nunique"),
            first_date=("usage_date", "min"),
            last_date=("usage_date", "max"),
        ).reset_index()

        leaderboard["Realized $/M"] = (leaderboard["total_revenue"] / leaderboard["total_tokens"] * 1e6).map(lambda v: f"${v:.3f}" if pd.notna(v) and v>0 else "—")
        leaderboard["Tokens"] = leaderboard["total_tokens"].map(lambda v: f"{v/1e12:.3f} T" if v >= 1e12 else f"{v/1e9:.2f} B")
        leaderboard["Est Revenue"] = leaderboard["total_revenue"].map(lambda v: f"${v/1e6:.2f} M" if v >= 1e6 else f"${v/1e3:.1f} k")
        leaderboard = leaderboard.sort_values("total_tokens", ascending=False).reset_index(drop=True)
        leaderboard["Rank"] = leaderboard.index + 1

        display_cols = ["Rank", "provider_name", "category", "Tokens", "Est Revenue", "Realized $/M", "models_count", "headquarters", "active_days"]
        rename_dict = {
            "provider_name": "Provider",
            "category": "Category",
            "models_count": "Active Models",
            "headquarters": "HQ",
            "active_days": "Observed Days",
        }
        st.dataframe(
            leaderboard[display_cols].rename(columns=rename_dict),
            width="stretch",
            hide_index=True,
        )


def render_unified(domain_states, datasets) -> None:
    """Unified OpenRouter hub with 4 top-level sub-tabs."""
    tab_econ, tab_cloud_infra, tab_models, tab_compare, tab_workloads = st.tabs([
        "📈 Overview, Economics & ARR",
        "☁️ Cloud & Infra Providers",
        "🔍 Model Explorer & Catalog",
        "⚖️ Provider Compare",
        "📊 Workloads & Modality",
    ])

    with tab_cloud_infra:
        render_cloud_infra_section(datasets)

    with tab_econ:
        openrouter_views = compute_openrouter_views(
            {
                **domain_states["openrouter_intelligence"][0],
                **domain_states["compute_availability"][0],
            },
            revenue_cache_version=REVENUE_CACHE_VERSION,
        )
        compute_views = compute_compute_availability_views(domain_states["compute_availability"][0])
        render_top_models_chart(datasets, openrouter_views)
        render_arr_nowcast_section(datasets)
        render_revenue_token_section(datasets, openrouter_views)
        render_task_spend_section(openrouter_views)
        render_token_revenue_comparison(openrouter_views)
        render_compute_evolution_section(compute_views)

    with tab_models:
        render_data_explorer(datasets)

    with tab_compare:
        render_compare(domain_states, datasets)

    with tab_workloads:
        render_workloads(domain_states, datasets)

