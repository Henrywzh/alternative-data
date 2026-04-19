from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from .catalog import catalog
from .clean import to_filter_list
from .loaders import load_dataset, load_domain
from .marts import (
    build_daily_provider_economics,
    build_frontier_model_registry,
    build_weekly_openrouter_usage,
)


def _match_any(frame: pd.DataFrame, columns: list[str], values: Iterable[str]) -> pd.Series:
    wanted = [value.casefold() for value in values]
    if not wanted:
        return pd.Series(True, index=frame.index)
    matches = pd.Series(False, index=frame.index)
    for column in columns:
        if column not in frame.columns:
            continue
        normalized = frame[column].astype("string").fillna("").str.casefold()
        matches = matches | normalized.isin(wanted)
    return matches


def weekly_tokens(
    models: str | Iterable[str] | None = None,
    authors: str | Iterable[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    *,
    base_dir: str | Path | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    frame = build_weekly_openrouter_usage(base_dir=base_dir, refresh=refresh).copy()
    if frame.empty:
        return frame

    if start:
        frame = frame[pd.to_datetime(frame["week_start_date"], errors="coerce") >= pd.Timestamp(start)]
    if end:
        frame = frame[pd.to_datetime(frame["week_start_date"], errors="coerce") <= pd.Timestamp(end)]

    model_filters = to_filter_list(models)
    author_filters = to_filter_list(authors)
    if model_filters:
        model_rows = frame["dataset_source"].isin(["top_models", "categories_programming"])
        frame = frame[~model_rows | _match_any(frame, ["entity_id", "entity_name"], model_filters)]
    if author_filters:
        author_rows = frame["dataset_source"].isin(["market_share"])
        frame = frame[~author_rows | _match_any(frame, ["entity_id", "entity_name"], author_filters)]
    return frame.reset_index(drop=True)


def provider_tokens_daily(
    providers: str | Iterable[str],
    start: str | None = None,
    end: str | None = None,
    *,
    include_others: bool = True,
    base_dir: str | Path | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    frame = build_daily_provider_economics(base_dir=base_dir, refresh=refresh).copy()
    if frame.empty:
        return frame

    provider_filters = to_filter_list(providers)
    if provider_filters:
        frame = frame[_match_any(frame, ["provider_slug", "provider_name"], provider_filters)]
    if start:
        frame = frame[pd.to_datetime(frame["usage_date"], errors="coerce") >= pd.Timestamp(start)]
    if end:
        frame = frame[pd.to_datetime(frame["usage_date"], errors="coerce") <= pd.Timestamp(end)]
    if not include_others:
        frame = frame[frame["model_permaslug"] != "Others"]
    return frame.reset_index(drop=True)


def provider_revenue_daily(
    providers: str | Iterable[str],
    start: str | None = None,
    end: str | None = None,
    *,
    include_others: bool = True,
    base_dir: str | Path | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    frame = build_daily_provider_economics(
        base_dir=base_dir,
        refresh=refresh,
    ).copy()

    provider_filters = to_filter_list(providers)
    if provider_filters:
        frame = frame[_match_any(frame, ["provider_slug", "provider_name"], provider_filters)]
    if start:
        frame = frame[pd.to_datetime(frame["usage_date"], errors="coerce") >= pd.Timestamp(start)]
    if end:
        frame = frame[pd.to_datetime(frame["usage_date"], errors="coerce") <= pd.Timestamp(end)]
    if not include_others:
        frame = frame[frame["model_permaslug"] != "Others"]
    return frame.reset_index(drop=True)


def monthly_model_releases(
    start: str | None = None,
    end: str | None = None,
    organizations: str | Iterable[str] | None = None,
    *,
    large_model_rule: str = "frontier_default",
    base_dir: str | Path | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    if large_model_rule != "frontier_default":
        raise ValueError("Only 'frontier_default' is currently supported")

    frame = build_frontier_model_registry(base_dir=base_dir, refresh=refresh).copy()
    if frame.empty:
        return frame

    frame["release_date"] = pd.to_datetime(frame["release_date"], errors="coerce")
    frame = frame.dropna(subset=["release_date"])
    if start:
        frame = frame[frame["release_date"] >= pd.Timestamp(start)]
    if end:
        frame = frame[frame["release_date"] <= pd.Timestamp(end)]
    org_filters = to_filter_list(organizations)
    if org_filters:
        frame = frame[_match_any(frame, ["organization"], org_filters)]

    frame["release_month"] = frame["release_date"].dt.to_period("M").dt.strftime("%Y-%m")
    grouped = (
        frame.groupby("release_month", as_index=False)
        .agg(
            model_count=("model_id", "count"),
            large_model_count=("is_large_model", "sum"),
            frontier_score_mean=("frontier_score", "mean"),
            gpqa_mean=("gpqa", "mean"),
            swe_bench_mean=("swe_bench", "mean"),
        )
        .sort_values("release_month")
        .reset_index(drop=True)
    )
    return grouped


def frontier_summary(
    start: str | None = None,
    end: str | None = None,
    organizations: str | Iterable[str] | None = None,
    *,
    base_dir: str | Path | None = None,
    refresh: bool = False,
) -> dict[str, object]:
    frame = build_frontier_model_registry(base_dir=base_dir, refresh=refresh).copy()
    if frame.empty:
        return {
            "model_count": 0,
            "large_model_count": 0,
            "organizations": [],
            "latest_release_date": None,
            "median_context_window": None,
            "mean_gpqa": None,
            "mean_swe_bench": None,
            "mean_frontier_score": None,
        }

    frame["release_date"] = pd.to_datetime(frame["release_date"], errors="coerce")
    if start:
        frame = frame[frame["release_date"] >= pd.Timestamp(start)]
    if end:
        frame = frame[frame["release_date"] <= pd.Timestamp(end)]
    org_filters = to_filter_list(organizations)
    if org_filters:
        frame = frame[_match_any(frame, ["organization"], org_filters)]

    return {
        "model_count": int(len(frame)),
        "large_model_count": int(frame["is_large_model"].fillna(False).sum()),
        "organizations": sorted(frame["organization"].dropna().astype(str).unique().tolist()),
        "latest_release_date": frame["release_date"].max().strftime("%Y-%m-%d") if frame["release_date"].notna().any() else None,
        "median_context_window": float(frame["context_window"].median()) if frame["context_window"].notna().any() else None,
        "mean_gpqa": float(frame["gpqa"].mean()) if frame["gpqa"].notna().any() else None,
        "mean_swe_bench": float(frame["swe_bench"].mean()) if frame["swe_bench"].notna().any() else None,
        "mean_frontier_score": float(frame["frontier_score"].mean()) if frame["frontier_score"].notna().any() else None,
    }
