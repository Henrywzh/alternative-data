from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from openrouter_revenue import CONSERVATIVE_ECONOMICS_COLUMNS, build_conservative_provider_economics
from supplement_pricing import supplement_pricing_df
from .clean import clean_model_id, mean_of_available, percentile_rank, to_datetime
from .joins import latest_huggingface_snapshot, latest_pricing_snapshot
from .loaders import load_dataset


MART_REGISTRY: dict[str, dict[str, str | None]] = {
    "weekly_openrouter_usage": {
        "label": "Weekly OpenRouter Usage",
        "domain": "research",
        "primary_date_column": "week_start_date",
        "metric_column": "metric_value",
    },
    "daily_provider_economics": {
        "label": "Daily Provider Economics",
        "domain": "research",
        "primary_date_column": "usage_date",
        "metric_column": "estimated_revenue",
    },
    "frontier_model_registry": {
        "label": "Frontier Model Registry",
        "domain": "research",
        "primary_date_column": "release_date",
        "metric_column": "frontier_score",
    },
}


def marts_root(base_dir: str | Path | None = None) -> Path:
    base = Path(base_dir).resolve() if base_dir is not None else Path(__file__).resolve().parents[2]
    return base / "data" / "normalized" / "marts"


def mart_paths(mart_name: str, base_dir: str | Path | None = None) -> tuple[Path, Path]:
    root = marts_root(base_dir=base_dir)
    return root / f"{mart_name}.csv", root / f"{mart_name}.parquet"


def read_mart(mart_name: str, base_dir: str | Path | None = None) -> pd.DataFrame:
    csv_path, parquet_path = mart_paths(mart_name, base_dir=base_dir)
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return pd.DataFrame()


def write_mart(mart_name: str, frame: pd.DataFrame, base_dir: str | Path | None = None) -> pd.DataFrame:
    csv_path, parquet_path = mart_paths(mart_name, base_dir=base_dir)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(csv_path, index=False)
    frame.to_parquet(parquet_path, index=False)
    return frame


def compute_weekly_openrouter_usage(base_dir: str | Path | None = None) -> pd.DataFrame:
    standardized_frames: list[pd.DataFrame] = []
    dataset_configs = [
        ("top_models", "model"),
        ("market_share", "author"),
        ("categories_programming", "model"),
    ]

    columns = [
        "week_start_date",
        "time_grain",
        "dataset_source",
        "entity_type",
        "entity_id",
        "entity_name",
        "parent_entity_id",
        "parent_entity_name",
        "metric_name",
        "metric_unit",
        "metric_value",
        "rank",
        "category_slug",
        "source_url",
        "source_run_id",
        "scraped_at",
    ]

    for dataset_id, entity_type in dataset_configs:
        frame = load_dataset(dataset_id, base_dir=base_dir)
        if frame.empty:
            continue
        standardized = frame.copy()
        standardized["week_start_date"] = pd.to_datetime(standardized["week_start_date"], errors="coerce").dt.strftime(
            "%Y-%m-%d"
        )
        standardized["time_grain"] = "week"
        standardized["dataset_source"] = dataset_id
        standardized["entity_type"] = entity_type
        standardized_frames.append(standardized[columns].copy())

    if not standardized_frames:
        return pd.DataFrame(columns=columns)

    merged = pd.concat(standardized_frames, ignore_index=True)
    merged = merged.sort_values(["week_start_date", "dataset_source", "rank", "entity_id"], na_position="last")
    return merged.reset_index(drop=True)


def compute_daily_provider_economics(
    base_dir: str | Path | None = None,
) -> pd.DataFrame:
    activity = load_dataset("provider_daily_activity", base_dir=base_dir)
    model_activity = load_dataset("openrouter_model_activity", base_dir=base_dir)
    pricing = load_dataset("raw_openrouter_models", base_dir=base_dir)
    if activity.empty:
        return pd.DataFrame(columns=CONSERVATIVE_ECONOMICS_COLUMNS)

    pricing = pd.concat([pricing, supplement_pricing_df()], ignore_index=True)
    output = build_conservative_provider_economics(
        activity,
        pricing,
        model_activity=model_activity,
    )
    return output


def compute_frontier_model_registry(base_dir: str | Path | None = None) -> pd.DataFrame:
    benchmarks = load_dataset("llm_benchmarks", base_dir=base_dir)
    pricing_history = load_dataset("raw_openrouter_models", base_dir=base_dir)
    huggingface = load_dataset("huggingface_models_daily", base_dir=base_dir)

    if benchmarks.empty:
        return pd.DataFrame(
            columns=[
                "model_id",
                "name",
                "organization",
                "release_date",
                "context_window",
                "gpqa",
                "swe_bench",
                "pricing_prompt",
                "pricing_completion",
                "latest_openrouter_snapshot_ts",
                "is_on_openrouter",
                "hf_downloads_daily_est_latest",
                "hf_downloads_all_time_latest",
                "is_large_model",
                "frontier_score",
            ]
        )

    base = benchmarks[
        [
            "model_id",
            "name",
            "organization",
            "release_date",
            "context_window",
            "gpqa",
            "swe_bench",
        ]
    ].copy()
    base["model_id"] = clean_model_id(base["model_id"])
    base["release_date"] = pd.to_datetime(base["release_date"], errors="coerce")

    latest_pricing = latest_pricing_snapshot(pricing_history).rename(
        columns={"pricing_snapshot_ts": "latest_openrouter_snapshot_ts"}
    )
    latest_hf = latest_huggingface_snapshot(huggingface)

    merged = base.merge(latest_pricing, on="model_id", how="left").merge(latest_hf, on="model_id", how="left")
    merged["context_window"] = pd.to_numeric(merged["context_window"], errors="coerce").fillna(
        pd.to_numeric(merged["openrouter_context_length"], errors="coerce")
    )
    merged["is_on_openrouter"] = merged["latest_openrouter_snapshot_ts"].notna()

    gpqa_cutoff = merged["gpqa"].dropna().quantile(0.9) if merged["gpqa"].notna().any() else np.nan
    swe_cutoff = merged["swe_bench"].dropna().quantile(0.9) if merged["swe_bench"].notna().any() else np.nan
    merged["is_large_model"] = (
        (merged["context_window"] >= 131072)
        | (merged["gpqa"] >= gpqa_cutoff)
        | (merged["swe_bench"] >= swe_cutoff)
    ).fillna(False)

    merged["gpqa_pct"] = percentile_rank(merged["gpqa"])
    merged["swe_bench_pct"] = percentile_rank(merged["swe_bench"])
    merged["context_window_pct"] = percentile_rank(np.log1p(pd.to_numeric(merged["context_window"], errors="coerce")))
    merged["frontier_score"] = mean_of_available(
        merged, ["gpqa_pct", "swe_bench_pct", "context_window_pct"]
    ).astype("float64")

    output = merged[
        [
            "model_id",
            "name",
            "organization",
            "release_date",
            "context_window",
            "gpqa",
            "swe_bench",
            "pricing_prompt",
            "pricing_completion",
            "latest_openrouter_snapshot_ts",
            "is_on_openrouter",
            "hf_downloads_daily_est_latest",
            "hf_downloads_all_time_latest",
            "is_large_model",
            "frontier_score",
        ]
    ].copy()
    output["release_date"] = output["release_date"].dt.strftime("%Y-%m-%d")
    output["latest_openrouter_snapshot_ts"] = pd.to_datetime(
        output["latest_openrouter_snapshot_ts"], errors="coerce", utc=True
    ).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    output = output.sort_values(["release_date", "organization", "model_id"], na_position="last").reset_index(drop=True)
    return output


def build_weekly_openrouter_usage(base_dir: str | Path | None = None, refresh: bool = False) -> pd.DataFrame:
    if not refresh:
        existing = read_mart("weekly_openrouter_usage", base_dir=base_dir)
        if not existing.empty:
            return existing
    return write_mart("weekly_openrouter_usage", compute_weekly_openrouter_usage(base_dir=base_dir), base_dir=base_dir)


def build_daily_provider_economics(
    base_dir: str | Path | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    if not refresh:
        existing = read_mart("daily_provider_economics", base_dir=base_dir)
        if not existing.empty:
            return existing
    computed = compute_daily_provider_economics(base_dir=base_dir)
    return write_mart("daily_provider_economics", computed, base_dir=base_dir)


def build_frontier_model_registry(base_dir: str | Path | None = None, refresh: bool = False) -> pd.DataFrame:
    if not refresh:
        existing = read_mart("frontier_model_registry", base_dir=base_dir)
        if not existing.empty:
            return existing
    return write_mart("frontier_model_registry", compute_frontier_model_registry(base_dir=base_dir), base_dir=base_dir)


def build_all_marts(base_dir: str | Path | None = None, refresh: bool = False) -> dict[str, pd.DataFrame]:
    return {
        "weekly_openrouter_usage": build_weekly_openrouter_usage(base_dir=base_dir, refresh=refresh),
        "daily_provider_economics": build_daily_provider_economics(base_dir=base_dir, refresh=refresh),
        "frontier_model_registry": build_frontier_model_registry(base_dir=base_dir, refresh=refresh),
    }
