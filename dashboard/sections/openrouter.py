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


REVENUE_CACHE_VERSION = "2026-04-23-historical-revenue-fallback-v1"


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


# --- OpenRouter Provider Mapping ---
OPENROUTER_PROVIDER_MAP = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "meta": "Meta (Llama)",
    "meta-llama": "Meta (Llama)",
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


@st.cache_data(ttl=3600)
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
        frame["week_start_date"] = frame["week_start_date"].astype(str)
        pivot = (
            frame.pivot_table(index="week_start_date", columns="entity_id", values="metric_value", aggfunc="sum")
            .fillna(0)
            .sort_index()
        )
        views["market_share"] = {
            "weeks": sorted(frame["week_start_date"].unique(), reverse=True),
            "pivot_pct_top": _top_n_with_others(pivot, top_n_count=15, exclude_others_named=True, pct=True),
        }
    else:
        views["market_share"] = {"weeks": [], "pivot_pct_top": pd.DataFrame()}

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
    if frame.empty:
        return pd.Series(dtype="float64", name="market_share")
    market = frame.copy()
    original_dates = pd.to_datetime(market["week_start_date"].astype(str), errors="coerce")
    market["original_week_start_date"] = original_dates.dt.normalize()
    market["week_start_date"] = _align_rankings_week_to_monday(market["week_start_date"].astype(str))
    market["metric_value"] = pd.to_numeric(market["metric_value"], errors="coerce")
    totals = (
        market.dropna(subset=["original_week_start_date", "week_start_date"])
        .groupby(["week_start_date", "original_week_start_date"], as_index=False)["metric_value"]
        .sum()
    )
    if totals.empty:
        return pd.Series(dtype="float64", name="market_share")
    totals["is_aligned_monday"] = totals["original_week_start_date"].dt.strftime("%Y-%m-%d") == totals["week_start_date"]
    totals = totals.sort_values(
        ["week_start_date", "is_aligned_monday", "metric_value", "original_week_start_date"],
        ascending=[True, False, False, False],
    )
    return (
        totals.drop_duplicates(subset=["week_start_date"], keep="first")
        .set_index("week_start_date")["metric_value"]
        .rename("market_share")
        .sort_index()
    )


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


def _is_xiaomi_mimo_backpricing_hazard(frame: pd.DataFrame) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=bool, index=frame.index)
    usage_date = pd.to_datetime(frame.get("usage_date"), errors="coerce").dt.strftime("%Y-%m-%d")
    provider = frame.get("entity_id", frame.get("provider_slug", pd.Series("", index=frame.index))).astype("string").str.lower()
    model = frame.get("model_permaslug", pd.Series("", index=frame.index)).astype("string").str.lower()
    return (
        provider.eq("xiaomi")
        & usage_date.between("2026-03-19", "2026-04-05")
        & model.str.startswith("xiaomi/mimo-v2-", na=False)
    )


def _compute_revenue_views(datasets: dict[str, DatasetLoadResult]) -> dict[str, object]:
    """Dashboard-oriented provider tokens and revenue with legacy fallback stitching."""
    provider_res = datasets.get("provider_daily_activity")
    model_activity_res = datasets.get("openrouter_model_activity")
    market_share_res = datasets.get("market_share")
    pricing_res = datasets.get("raw_openrouter_models")
    macro_res = datasets.get("top_models")

    provider_activity = provider_res.frame.copy() if provider_res and not provider_res.frame.empty else pd.DataFrame()
    model_activity = (
        model_activity_res.frame.copy() if model_activity_res and not model_activity_res.frame.empty else pd.DataFrame()
    )
    pricing = pricing_res.frame.copy() if pricing_res and not pricing_res.frame.empty else pd.DataFrame()

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
        modern_tok["provider_label"] = modern_tok["entity_name"].fillna(modern_tok["entity_id"])
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
        "OpenAI", "Anthropic", "Google", "Meta (Llama)", "DeepSeek",
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
    if not provider_activity.empty:
        modern_df = provider_activity.copy()
        modern_df = modern_df[~_is_xiaomi_mimo_backpricing_hazard(modern_df)].copy()
        modern_with_price = (
            estimate_usage_revenue(
                modern_df,
                pricing,
                slug_strategy="canonical",
                pricing_strategy="provider_fallback",
            )
            if not modern_df.empty
            else pd.DataFrame()
        )
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
            modern_with_price["provider_label"] = modern_with_price["entity_name"].fillna(modern_with_price["provider_slug"])

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

    coverage_summary = summarize_economics_coverage(economics)

    if macro_res and not macro_res.frame.empty and market_share_res and not market_share_res.frame.empty:
        macro_df = macro_res.frame.copy()
        share_df = market_share_res.frame.copy()
        macro_df["usage_week"] = _align_rankings_week_to_monday(macro_df["week_start_date"].astype(str))
        share_df["usage_week"] = _align_rankings_week_to_monday(share_df["week_start_date"].astype(str))

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
        pivot_rev_weekly_legacy = pivot_rev_weekly_legacy[pivot_rev_weekly_legacy.index <= "2026-01-05"]

        pivot_rev_monthly_legacy = (
            combined.pivot_table(index="usage_month", columns="provider_label", values="final_revenue", aggfunc="sum")
            .fillna(0).sort_index()
        )
        pivot_rev_monthly_legacy = pivot_rev_monthly_legacy[pivot_rev_monthly_legacy.index <= "2026-01"]

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
        },
        "token_volume": {
            "pivot_daily": pivot_tok_daily,
            "pivot_weekly": pivot_tok_weekly,
            "pivot_monthly": pivot_tok_monthly,
            "weekly_coverage": weekly_coverage,
            "monthly_coverage": monthly_coverage,
        },
    }


@st.cache_data(ttl=3600)
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
        max_snapshot_size = max(group["model_id"].nunique() for _, group in snapshot_groups)
        full_snapshot_threshold = max_snapshot_size * 0.8

        current_catalog: dict[str, pd.Series] = {}
        growth_rows: list[dict[str, object]] = []

        for snapshot_ts, group in snapshot_groups:
            snapshot_rows = (
                group.drop_duplicates(subset=["model_id"], keep="last")
                .sort_values("model_id")
                .reset_index(drop=True)
            )

            if snapshot_rows["model_id"].nunique() >= full_snapshot_threshold:
                current_catalog = {
                    str(row["model_id"]): row.copy()
                    for _, row in snapshot_rows.iterrows()
                }
            else:
                for _, row in snapshot_rows.iterrows():
                    current_catalog[str(row["model_id"])] = row.copy()

            growth_rows.append({"snapshot_ts": snapshot_ts, "model_count": len(current_catalog)})

        latest_ts = snapshot_groups[-1][0]
        latest_models = pd.DataFrame(current_catalog.values()).sort_values("model_id").reset_index(drop=True)

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


def render_top_models_chart(datasets: dict[str, DatasetLoadResult], openrouter_views: dict[str, object]) -> None:
    st.markdown('<div class="section-title">Total Weekly Tokens</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="section-subtitle">Completed weekly OpenRouter token-usage buckets. Uses Market Share totals when they remain directionally complete, and falls back to Top Models when the Market Share feed undercounts recent weeks.</div>',
        unsafe_allow_html=True,
    )
    top_view = openrouter_views.get("top_models", {})
    total_source = top_view.get("total_source", "top_models")
    pivot_total = top_view.get("pivot_total", pd.DataFrame())
    latest_week = pivot_total.index.max() if not pivot_total.empty else "n/a"
    latest_source = top_view.get("source_by_week", {}).get(latest_week, total_source)
    result = datasets.get("market_share") if latest_source == "market_share" else datasets.get("top_models")
    if latest_source == "hybrid":
        result = datasets.get("top_models")
    if not result or not render_dataset_guard(result):
        return
    st.markdown(
        f'<div class="status-caption">Total source: {total_source} · Latest plotted week: {latest_week} · Latest-week source: {latest_source} · Scraped: {format_scraped_at_display(result.latest_scraped_at)}</div>',
        unsafe_allow_html=True,
    )

    fig = make_line_chart(
        pivot_total,
        [ACCENT],
        y_title="Tokens",
        x_title="Usage Week (Starting)",
        hover_suffix="tokens",
    )
    st.plotly_chart(fig, width="stretch", theme=None)


def render_revenue_estimator(datasets: dict[str, DatasetLoadResult], openrouter_views: dict[str, object]) -> None:
    rev_data = openrouter_views.get("revenue_estimator", {})
    pivot_rev = rev_data.get("pivot_rev", pd.DataFrame())
    total_revenue = rev_data.get("total_revenue", 0)
    coverage = rev_data.get("coverage", {})

    st.markdown('<div class="section-title">Provider Revenue Estimator</div>', unsafe_allow_html=True)
    
    if pivot_rev.empty:
        st.info("No priced provider activity is available for conservative revenue estimation yet.")
        return

    st.markdown(
        kpi_grid_html(
            kpi_card_html("Observed Priced Revenue", f"${total_revenue:,.0f}", delta="matched model pricing only"),
            kpi_card_html("Provider Coverage", str(len(pivot_rev.columns)), delta="active priced providers"),
            kpi_card_html("Priced Token Coverage", f"{coverage.get('priced_token_coverage', 0):.1%}", delta="of observed provider tokens"),
            kpi_card_html("Split Token Coverage", f"{coverage.get('split_token_coverage', 0):.1%}", delta="prompt/completion known or inferred"),
        ),
        unsafe_allow_html=True,
    )

    st.markdown('<div class="section-subtitle">Estimated Revenue by Provider (USD)</div>', unsafe_allow_html=True)

    pivot_monthly = regroup_provider_pivot_for_display(rev_data.get("pivot_rev_monthly", pd.DataFrame()), "monthly")
    pivot_weekly  = regroup_provider_pivot_for_display(rev_data.get("pivot_rev_weekly", pd.DataFrame()), "weekly")
    pivot_daily   = regroup_provider_pivot_for_display(rev_data.get("pivot_rev_daily", pd.DataFrame()), "daily")

    tab_week, tab_month, tab_day = st.tabs(["Weekly", "Monthly", "Daily"])
    
    def _render_rev_chart(pivot_df, date_title):
        if pivot_df.empty:
            st.info(f"No {date_title.lower()} data available.")
            return
        # Label the current month as MTD in the X-axis for clarity
        today_month = datetime.now().strftime("%Y-%m")
        display_index = [
            f"{d} (MTD)" if date_title == "Usage Month" and str(d) == today_month else d
            for d in pivot_df.index
        ]
        st.plotly_chart(
            make_stacked_area_chart(
                pivot_df,
                display_index,
                MODEL_COLORS,
                x_title=date_title,
                y_title="Revenue (USD)",
                hover_prefix="$",
            ),
            width="stretch", theme=None,
        )

    with tab_week:
        if pivot_weekly.empty:
            st.info("No weekly data available.")
        else:
            today_month = datetime.now().strftime("%Y-%m")
            display_index = [str(d) for d in pivot_weekly.index]
            fig_week = make_stacked_area_chart(
                pivot_weekly,
                display_index,
                MODEL_COLORS,
                x_title="Usage Week (Starting)",
                y_title="Revenue (USD)",
                hover_prefix="$",
            )
            st.plotly_chart(fig_week, width="stretch", theme=None)
            st.caption(
                "Weekly revenue combines legacy Market Share plus Top Models fallback estimates before mid-January 2026, "
                "then switches to observed provider activity with pricing fallbacks."
            )
    with tab_month:
        _render_rev_chart(pivot_monthly, "Usage Month")
    with tab_day:
        _render_rev_chart(pivot_daily, "Usage Date")
        
    st.caption(
        "Methodology: dashboard revenue uses a hybrid estimate. Legacy weekly history starts from Market Share provider totals, "
        "prices the ranked model subset, and tops up uncovered provider volume with provider/global blended pricing benchmarks. "
        "Modern daily history uses observed provider/model activity with OpenRouter pricing plus provider/global fallbacks when exact as-of matches are unavailable. "
        "Models whose OpenRouter slug ends in :free are included in token volume and zero-rated for revenue."
    )
    st.markdown("---")


def render_token_volume_chart(openrouter_views: dict[str, object]) -> None:
    """Stacked area chart: raw token consumption by provider over time (daily/weekly/monthly)."""
    st.markdown('<div class="section-title">Token Volume by Provider</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="section-subtitle">Token volume by provider across OpenRouter. '
        'Legacy (pre-Jan 2026): provider-level history from weekly Market Share rankings. '
        'Modern (2026+): observed daily logs for tracked priority providers, with the first partial modern week bridged from the following week for continuity.</div>',
        unsafe_allow_html=True,
    )

    tok_data = openrouter_views.get("token_volume", {})
    pivot_daily = regroup_provider_pivot_for_display(tok_data.get("pivot_daily", pd.DataFrame()), "daily")
    pivot_weekly = regroup_provider_pivot_for_display(tok_data.get("pivot_weekly", pd.DataFrame()), "weekly")
    pivot_monthly = regroup_provider_pivot_for_display(tok_data.get("pivot_monthly", pd.DataFrame()), "monthly")

    if pivot_weekly.empty and pivot_daily.empty:
        st.info("No token volume data available.")
        return

    # --- KPI Row ---
    latest_tok_total, tok_wow_pct, dominant_provider = None, None, None
    if not pivot_weekly.empty:
        latest_row = pivot_weekly.iloc[-1]
        latest_tok_total = float(latest_row.sum())
        if len(pivot_weekly) >= 2:
            prev_total = float(pivot_weekly.iloc[-2].sum())
            if prev_total > 0:
                tok_wow_pct = (latest_tok_total - prev_total) / prev_total * 100
        if latest_tok_total > 0:
            dominant_provider = latest_row.idxmax()

    if tok_wow_pct is not None:
        tok_delta_cls  = "up" if tok_wow_pct >= 0 else "down"
        tok_delta_text = f"{'↑' if tok_wow_pct >= 0 else '↓'} {abs(tok_wow_pct):.1f}% WoW"
    else:
        tok_delta_cls, tok_delta_text = "flat", "—"

    coverage = "Legacy + observed modern" if not pivot_weekly.empty and pivot_weekly.index[0] < "2026" else "Observed modern"
    wow_str = f"{'+'  if tok_wow_pct and tok_wow_pct >= 0 else ''}{f'{tok_wow_pct:.1f}%' if tok_wow_pct is not None else '—'}"

    st.markdown(
        kpi_grid_html(
            kpi_card_html("Total Tokens (Latest Week)", format_metric(latest_tok_total) if latest_tok_total else "—", delta=tok_delta_text, delta_class=tok_delta_cls),
            kpi_card_html("WoW Change", wow_str, delta="vs prior week"),
            kpi_card_html("Dominant Provider", dominant_provider or "—", delta="by token share this week"),
            kpi_card_html("Data Coverage", coverage, delta="legacy + smoothed modern seam"),
        ),
        unsafe_allow_html=True,
    )

    tab_week, tab_month, tab_day = st.tabs(["Weekly", "Monthly", "Daily"])

    def _render_tok_chart(pivot_df: pd.DataFrame, date_title: str) -> None:
        if pivot_df.empty:
            st.info(f"No {date_title.lower()} token data available.")
            return
        today_month = datetime.now().strftime("%Y-%m")
        display_index = [
            f"{d} (MTD)" if date_title == "Usage Month" and str(d) == today_month else d
            for d in pivot_df.index
        ]
        st.plotly_chart(
            make_stacked_area_chart(
                pivot_df,
                display_index,
                MODEL_COLORS,
                x_title=date_title,
                y_title="Tokens",
                value_format=",.0f",
                hover_suffix="tokens",
            ),
            width="stretch", theme=None,
        )

    with tab_week:
        _render_tok_chart(pivot_weekly, "Usage Week (Starting)")
    with tab_month:
        _render_tok_chart(pivot_monthly, "Usage Month")
    with tab_day:
        _render_tok_chart(pivot_daily, "Usage Date")

    st.caption(
        "Legacy (pre-Jan 2026): weekly/monthly token views come from provider-level Market Share history, "
        "so they reflect providers visible in OpenRouter's author-share chart rather than only the surviving top-model cutoff. "
        "Modern (post-Jan 2026): daily token views come from exact per-provider logs, but only for the configured priority providers, "
        "not the full OpenRouter provider universe, so some providers may still be missing from the chart. Partial periods are observed totals."
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


def render(domain_states, datasets) -> None:
    openrouter_views = compute_openrouter_views(
        {
            **domain_states["rankings"][0],
            **domain_states["apps"][0],
            **domain_states["compute_availability"][0],
        },
        revenue_cache_version=REVENUE_CACHE_VERSION,
    )
    compute_views = compute_compute_availability_views(domain_states["compute_availability"][0])
    render_kpi_row(datasets, openrouter_views)
    render_top_models_chart(datasets, openrouter_views)
    render_revenue_estimator(datasets, openrouter_views)
    render_token_volume_chart(openrouter_views)
    render_token_revenue_comparison(openrouter_views)
    render_compute_evolution_section(compute_views)
    render_apps_tables(datasets)
