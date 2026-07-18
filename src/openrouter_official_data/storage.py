from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from openrouter_official_data.source import Snapshot


DATASET_SPECS: dict[str, dict[str, list[str]]] = {
    "official_model_rankings_daily": {
        "keys": ["usage_date", "model_permaslug", "period", "modality", "context_bucket", "category", "language_type"],
        "partitions": ["usage_date", "period", "modality", "context_bucket", "category", "language_type"],
        "sort": ["usage_date", "rank", "model_permaslug"],
    },
    "official_app_rankings": {
        "keys": ["snapshot_date", "ranking_type", "app_id"],
        "partitions": ["snapshot_date", "ranking_type"],
        "sort": ["snapshot_date", "ranking_type", "rank", "app_id"],
    },
    "official_task_classifications": {
        "keys": ["snapshot_date", "window_days", "tag"],
        "partitions": ["snapshot_date", "window_days"],
        "sort": ["snapshot_date", "usage_share", "tag"],
    },
    "official_task_models": {
        "keys": ["snapshot_date", "window_days", "tag", "model_permaslug"],
        "partitions": ["snapshot_date", "window_days"],
        "sort": ["snapshot_date", "tag", "rank", "model_permaslug"],
    },
    "official_task_macro_categories": {
        "keys": ["snapshot_date", "window_days", "macro_category"],
        "partitions": ["snapshot_date", "window_days"],
        "sort": ["snapshot_date", "usage_share", "macro_category"],
    },
    "official_providers": {
        "keys": ["snapshot_date", "provider_slug"],
        "partitions": ["snapshot_date"],
        "sort": ["snapshot_date", "provider_slug"],
    },
    "official_benchmarks": {
        # Some sources publish multiple reasoning-effort variants under one
        # model permaslug (for example "GPT-5.2 (Low)" and "(XHigh)").
        # display_name is therefore part of the identity, not presentation-only.
        "keys": [
            "snapshot_date",
            "benchmark_source",
            "model_permaslug",
            "display_name",
            "arena",
            "category",
            "variant_index",
        ],
        "partitions": ["snapshot_date"],
        "sort": [
            "snapshot_date",
            "benchmark_source",
            "arena",
            "category",
            "model_permaslug",
            "display_name",
            "variant_index",
        ],
    },
    "official_legacy_reconciliation": {
        "keys": ["usage_date"],
        "partitions": [],
        "sort": ["usage_date"],
    },
    "official_source_health": {
        "keys": ["source_run_id", "dataset_id"],
        "partitions": [],
        "sort": ["scraped_at", "dataset_id"],
    },
}


class OfficialStorage:
    def __init__(self, base_dir: Path) -> None:
        self.raw_root = base_dir / "data" / "raw" / "openrouter_official"
        self.normalized_root = base_dir / "data" / "normalized" / "openrouter_official"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_run(
        self, *, run_id: str, snapshots: list[Snapshot], manifest: dict[str, Any]
    ) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in snapshots:
            (run_dir / f"{snapshot.name}.json").write_text(snapshot.body, encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return run_dir

    def load(self, dataset_id: str) -> pd.DataFrame:
        path = self.normalized_root / f"{dataset_id}.parquet"
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    def upsert(self, dataset_id: str, rows: list[dict[str, Any]] | pd.DataFrame) -> pd.DataFrame:
        if dataset_id not in DATASET_SPECS:
            raise KeyError(f"Unknown official dataset: {dataset_id}")
        incoming = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
        if incoming.empty:
            return self.load(dataset_id)
        if "dataset_id" not in incoming.columns:
            incoming["dataset_id"] = dataset_id
        existing = self.load(dataset_id)
        keys = DATASET_SPECS[dataset_id]["keys"]
        for key in keys:
            if key not in incoming.columns:
                incoming[key] = pd.NA
            if not existing.empty and key not in existing.columns:
                existing[key] = pd.NA

        # Official endpoints revise recent snapshots. Replace each affected
        # partition before inserting so a model/app that falls out of a ranking
        # does not survive as a stale row alongside the revised snapshot.
        partition_columns = DATASET_SPECS[dataset_id].get("partitions", [])
        if not existing.empty and partition_columns:
            for column in partition_columns:
                if column not in incoming.columns:
                    incoming[column] = pd.NA
                if column not in existing.columns:
                    existing[column] = pd.NA
            incoming_partitions = pd.MultiIndex.from_frame(
                incoming[partition_columns].astype("string").fillna("__NULL_PARTITION__")
            )
            existing_partitions = pd.MultiIndex.from_frame(
                existing[partition_columns].astype("string").fillna("__NULL_PARTITION__")
            )
            existing = existing[~existing_partitions.isin(incoming_partitions)].copy()

        merged = pd.concat([existing, incoming], ignore_index=True, sort=False) if not existing.empty else incoming.copy()
        merged = merged.drop_duplicates(subset=keys, keep="last")
        sort = [column for column in DATASET_SPECS[dataset_id]["sort"] if column in merged.columns]
        ascending = [False if column in {"usage_share", "token_share"} else True for column in sort]
        if sort:
            merged = merged.sort_values(sort, ascending=ascending, na_position="last")
        merged = merged.reset_index(drop=True)
        merged.to_parquet(self.normalized_root / f"{dataset_id}.parquet", index=False)
        return merged
