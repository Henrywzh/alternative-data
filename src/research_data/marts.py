from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from openrouter_revenue import (
    CONSERVATIVE_ECONOMICS_COLUMNS,
    SERVING_PROVIDER_ECONOMICS_COLUMNS,
    build_conservative_provider_economics,
    build_provider_revenue_estimates,
    build_serving_provider_economics,
)
from common.partitioned_parquet import PartitionSpec, PartitionedParquetStore
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
    "daily_provider_revenue_estimates": {
        "label": "Daily Provider Revenue Estimates",
        "domain": "research",
        "primary_date_column": "usage_date",
        "metric_column": "estimated_revenue",
    },
    "daily_cloud_infra_economics": {
        "label": "Daily Serving-Provider Economics",
        "domain": "openrouter_derived",
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
    """Where the marts live; ``RESEARCH_DATA_MARTS_DIR`` overrides the default.

    write_mart() writes here, and notebooks/03_frontier_intelligence_dynamics
    rebuilds a mart on execution -- which tests/test_research_notebooks.py does
    by exec'ing the notebook, so the suite rewrote the tracked parquet. An
    explicit ``base_dir`` still wins; the override only replaces the default,
    the same way HK_TRANSPORT_NORMALIZED_DIR does for src/hk_transport.
    """
    if base_dir is not None:
        return Path(base_dir).resolve() / "data" / "normalized" / "marts"
    override = os.environ.get("RESEARCH_DATA_MARTS_DIR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "data" / "normalized" / "marts"


def mart_paths(mart_name: str, base_dir: str | Path | None = None) -> tuple[Path, Path]:
    root = marts_root(base_dir=base_dir)
    return root / f"{mart_name}.csv", root / f"{mart_name}.parquet"


# daily_provider_economics is rebuilt from source every run, and the rebuild is
# almost entirely stable: measured across two consecutive commits (2026-09-08 ->
# 2026-09-09) only 5 of its 366 usage_date groups differed. The single-file
# layout still rewrote the whole parquet, and parquet is compressed binary that
# git cannot delta -- 24.2 MB of history over the last 90 days for a 1% change.
# Writing one file per usage_date, and skipping partitions whose bytes did not
# move, reduces that to the days that actually changed.
#
# The partition column is the mart's own primary_date_column from MART_REGISTRY.
# Readers must go through read_mart()/mart_frame_paths() rather than opening
# "<mart>.parquet": a reader that does not know a mart is partitioned does not
# fail, it misses the file and returns zero rows.
PARTITIONED_MARTS: frozenset[str] = frozenset({"daily_provider_economics"})


def mart_partition_dir(mart_name: str, base_dir: str | Path | None = None) -> Path:
    return marts_root(base_dir=base_dir) / mart_name


def mart_frame_paths(mart_name: str, base_dir: str | Path | None = None) -> list[Path]:
    """Every file that makes up this mart, newest layout first.

    One entry for a single-file mart, one per partition for a partitioned one,
    and an empty list when it has not been built. Consumers that fingerprint
    the mart for caching should hash this list rather than a single path.
    """
    csv_path, parquet_path = mart_paths(mart_name, base_dir=base_dir)
    if mart_name in PARTITIONED_MARTS:
        directory = mart_partition_dir(mart_name, base_dir=base_dir)
        if directory.is_dir():
            partitions = sorted(directory.glob("*.parquet"))
            if partitions:
                return partitions
    if parquet_path.exists():
        return [parquet_path]
    if csv_path.exists():
        return [csv_path]
    return []


def _mart_partition_store(
    mart_name: str, frame: pd.DataFrame, base_dir: str | Path | None = None
) -> PartitionedParquetStore | None:
    """The partitioned store for this mart, or None if it is single-file."""
    if mart_name not in PARTITIONED_MARTS or frame.empty:
        return None
    column = MART_REGISTRY.get(mart_name, {}).get("primary_date_column")
    if not column or column not in frame.columns:
        return None
    # Dtype kinds are normalised rather than copied, so int64-vs-float64 drift
    # between rebuilds cannot change the written bytes for unchanged days.
    bools = {str(c) for c in frame.columns if frame[c].dtype.kind == "b"}
    numerics = {str(c) for c in frame.columns if frame[c].dtype.kind in "iuf"}
    return PartitionedParquetStore(
        mart_partition_dir(mart_name, base_dir=base_dir),
        PartitionSpec(
            column=str(column),
            columns=[str(c) for c in frame.columns],
            bool_columns=frozenset(bools),
            numeric_columns=frozenset(numerics),
            # Month, not day. This mart holds ~110 rows per usage_date across
            # 366 days, so per-file parquet overhead dominates at day
            # granularity: 366 files and 5.73 MB on disk, for a 136 KB daily
            # delta. By month it is 13 files and 1.14 MB for a 125 KB delta --
            # better on both axes. Datasets with far more rows per day (e.g.
            # openrouter_task_spend) measure the other way round.
            granularity="month",
        ),
    )


def read_mart(mart_name: str, base_dir: str | Path | None = None) -> pd.DataFrame:
    csv_path, parquet_path = mart_paths(mart_name, base_dir=base_dir)
    if mart_name in PARTITIONED_MARTS:
        directory = mart_partition_dir(mart_name, base_dir=base_dir)
        if directory.is_dir():
            partitions = sorted(directory.glob("*.parquet"))
            if partitions:
                # A leftover single file would double every row, so the
                # partition directory is authoritative once it exists. A
                # pre-migration checkout has none and falls through.
                return pd.concat(
                    [pd.read_parquet(path) for path in partitions], ignore_index=True
                )
    if parquet_path.exists():
        return pd.read_parquet(parquet_path)
    if csv_path.exists():
        return pd.read_csv(csv_path)
    return pd.DataFrame()


def write_mart(mart_name: str, frame: pd.DataFrame, base_dir: str | Path | None = None) -> pd.DataFrame:
    csv_path, parquet_path = mart_paths(mart_name, base_dir=base_dir)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    # Skip a rewrite that would not change the bytes. build_*(refresh=False)
    # reuses an existing mart only when it is non-empty, so a mart that is
    # committed empty -- frontier_model_registry is -- gets recomputed and
    # rewritten on every call, including every execution of
    # notebooks/00_data_catalog.ipynb. That touched a tracked file with
    # identical content, which is invisible to `git diff` but not to anything
    # watching mtimes, and it happens to a human opening the notebook too.
    if frame.equals(read_mart(mart_name, base_dir=base_dir)):
        return frame
    store = _mart_partition_store(mart_name, frame, base_dir=base_dir)
    if store is not None:
        store.write(frame)
        # The pre-partition files are now stale duplicates of the whole mart;
        # either one left behind would double-count on a reader that still
        # prefers it.
        parquet_path.unlink(missing_ok=True)
        csv_path.unlink(missing_ok=True)
        return frame
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


DAILY_PROVIDER_REVENUE_ESTIMATES_COLUMNS = [
    "usage_date",
    "entity_id",
    "provider_slug",
    "model_permaslug",
    "total_tokens",
    "estimated_revenue",
    "pricing_join_status",
]


def compute_daily_provider_revenue_estimates(
    base_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Provider-fallback revenue estimate mart, mirroring the dashboard's primary revenue chart.

    Unlike ``daily_provider_economics`` (which leaves rows with no exact price
    match unpriced), this uses provider/global median fallbacks so it prices
    the full activity volume. It is the precomputed twin of
    ``build_provider_revenue_estimates(provider_activity, pricing)``.
    """
    activity = load_dataset("provider_daily_activity", base_dir=base_dir)
    pricing = load_dataset("raw_openrouter_models", base_dir=base_dir)
    if activity.empty:
        return pd.DataFrame(columns=DAILY_PROVIDER_REVENUE_ESTIMATES_COLUMNS)

    output = build_provider_revenue_estimates(activity, pricing)
    if output.empty:
        return pd.DataFrame(columns=DAILY_PROVIDER_REVENUE_ESTIMATES_COLUMNS)
    return output[DAILY_PROVIDER_REVENUE_ESTIMATES_COLUMNS].reset_index(drop=True)


def compute_daily_cloud_infra_economics(
    base_dir: str | Path | None = None,
) -> pd.DataFrame:
    """Compute route-level serving-provider economics from canonical datasets."""

    activity = load_dataset("cloud_infra_daily_activity", base_dir=base_dir)
    pricing = load_dataset("raw_openrouter_models", base_dir=base_dir)
    model_activity = load_dataset("openrouter_model_activity", base_dir=base_dir)
    if activity.empty:
        return pd.DataFrame(columns=SERVING_PROVIDER_ECONOMICS_COLUMNS)
    return build_serving_provider_economics(
        activity,
        pricing,
        model_activity=model_activity,
    )


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


def build_daily_provider_revenue_estimates(
    base_dir: str | Path | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    if not refresh:
        existing = read_mart("daily_provider_revenue_estimates", base_dir=base_dir)
        if not existing.empty:
            return existing
    computed = compute_daily_provider_revenue_estimates(base_dir=base_dir)
    return write_mart("daily_provider_revenue_estimates", computed, base_dir=base_dir)


def build_daily_cloud_infra_economics(
    base_dir: str | Path | None = None,
    refresh: bool = False,
) -> pd.DataFrame:
    if not refresh:
        existing = read_mart("daily_cloud_infra_economics", base_dir=base_dir)
        if not existing.empty:
            return existing
    computed = compute_daily_cloud_infra_economics(base_dir=base_dir)
    # This mart is fully derived from the canonical activity store, whose own
    # ingestion layer already performs history-preserving natural-key upserts.
    # Rewriting the mart prevents legacy or fabricated rows from surviving a
    # corrected pricing/identity implementation.
    return write_mart("daily_cloud_infra_economics", computed, base_dir=base_dir)


def build_all_marts(base_dir: str | Path | None = None, refresh: bool = False) -> dict[str, pd.DataFrame]:
    return {
        "weekly_openrouter_usage": build_weekly_openrouter_usage(base_dir=base_dir, refresh=refresh),
        "daily_provider_economics": build_daily_provider_economics(base_dir=base_dir, refresh=refresh),
        "daily_provider_revenue_estimates": build_daily_provider_revenue_estimates(base_dir=base_dir, refresh=refresh),
        "daily_cloud_infra_economics": build_daily_cloud_infra_economics(base_dir=base_dir, refresh=refresh),
        "frontier_model_registry": build_frontier_model_registry(base_dir=base_dir, refresh=refresh),
    }
