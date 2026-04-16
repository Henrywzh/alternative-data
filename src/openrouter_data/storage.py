from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from openrouter_data.exceptions import ValidationError
from openrouter_data.models import DatasetRecord, Snapshot


NATURAL_KEYS: dict[str, list[str]] = {
    "top_models": ["week_start_date", "entity_id"],
    "market_share": ["week_start_date", "entity_id"],
    "categories_programming": ["week_start_date", "category_slug", "entity_id"],
    "app_metadata_snapshots": ["app_id", "scrape_date"],
    "app_usage_daily": ["app_id", "usage_date", "model_permaslug"],
    "app_top_models_daily_snapshot": ["app_id", "snapshot_date", "model_permaslug"],
    "apps_global_ranking_snapshots": ["snapshot_date", "period", "rank"],
    "apps_trending_snapshots": ["snapshot_date", "rank"],
    "openrouter_model_activity": ["usage_date", "model_permaslug", "category_slug"],
    "provider_daily_activity": ["usage_date", "model_permaslug"],
}

DATASET_COLUMNS = [
    "dataset_id",
    "source_url",
    "source_run_id",
    "scraped_at",
    "week_label",
    "week_start_date",
    "entity_id",
    "entity_name",
    "parent_entity_id",
    "parent_entity_name",
    "metric_name",
    "metric_unit",
    "metric_value",
    "rank",
    "category_slug",
    "app_id",
    "app_name",
    "origin_url",
    "main_url",
    "description",
    "categories",
    "group_by_origin",
    "is_private",
    "is_hidden",
    "created_at",
    "scrape_date",
    "usage_date",
    "model_permaslug",
    "total_tokens",
    "snapshot_date",
    "observed_at",
    "period",
    "tokens",
    "growth_percent",
    "prompt_tokens",
    "completion_tokens",
    "request_count",
]

NUMERIC_COLUMNS = ["metric_value", "rank", "total_tokens", "tokens", "growth_percent", "prompt_tokens", "completion_tokens", "request_count"]
BOOL_COLUMNS = ["group_by_origin", "is_private", "is_hidden"]
TEXT_COLUMNS = [
    column
    for column in DATASET_COLUMNS
    if column not in NUMERIC_COLUMNS and column not in BOOL_COLUMNS
]
SORT_KEYS: dict[str, list[str]] = {
    "top_models": ["week_start_date", "rank", "entity_id"],
    "market_share": ["week_start_date", "rank", "entity_id"],
    "categories_programming": ["week_start_date", "rank", "entity_id"],
    "app_metadata_snapshots": ["scrape_date", "app_id"],
    "app_usage_daily": ["usage_date", "app_id", "rank", "model_permaslug"],
    "app_top_models_daily_snapshot": ["snapshot_date", "app_id", "rank", "model_permaslug"],
    "apps_global_ranking_snapshots": ["snapshot_date", "period", "rank", "origin_url"],
    "apps_trending_snapshots": ["snapshot_date", "rank", "origin_url"],
    "openrouter_model_activity": ["usage_date", "model_permaslug", "category_slug"],
    "provider_daily_activity": ["usage_date", "model_permaslug"],
}


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "openrouter"
        self.normalized_root = base_dir / "data" / "normalized" / "openrouter"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_run(
        self,
        run_id: str,
        snapshots: Iterable[Snapshot],
        manifest: dict[str, Any],
    ) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in snapshots:
            (run_dir / f"{snapshot.name}.html").write_text(snapshot.body, encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return run_dir

    def load_dataset(self, dataset_id: str) -> pd.DataFrame:
        csv_path = self.normalized_root / f"{dataset_id}.csv"
        if not csv_path.exists():
            return pd.DataFrame(columns=DATASET_COLUMNS)
        dataframe = pd.read_csv(csv_path)
        for column in DATASET_COLUMNS:
            if column not in dataframe.columns:
                dataframe[column] = pd.NA
        return dataframe[DATASET_COLUMNS]

    def upsert_dataset(self, dataset_id: str, records: Iterable[DatasetRecord]) -> pd.DataFrame:
        incoming = pd.DataFrame([record.to_dict() for record in records], columns=DATASET_COLUMNS)
        if incoming.empty:
            raise ValidationError(f"Dataset {dataset_id} has no incoming records")
        existing = self.load_dataset(dataset_id)
        if existing.empty:
            merged = incoming.copy()
        else:
            merged = pd.concat([existing, incoming], ignore_index=True)
        merged = self._coerce_types(merged)
        keys = NATURAL_KEYS[dataset_id]
        merged = merged.drop_duplicates(subset=keys, keep="last")
        merged = merged.sort_values(by=SORT_KEYS[dataset_id], na_position="last").reset_index(drop=True)

        csv_path = self.normalized_root / f"{dataset_id}.csv"
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"
        merged.to_csv(csv_path, index=False)
        merged.to_parquet(parquet_path, index=False)
        return merged

    @staticmethod
    def _coerce_types(dataframe: pd.DataFrame) -> pd.DataFrame:
        for column in NUMERIC_COLUMNS:
            dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")
        for column in BOOL_COLUMNS:
            dataframe[column] = dataframe[column].map(
                lambda value: value
                if pd.isna(value) or isinstance(value, bool)
                else str(value).strip().lower() == "true"
            )
        for column in TEXT_COLUMNS:
            dataframe[column] = dataframe[column].astype("string")
        if dataframe["rank"].notna().any():
            dataframe["rank"] = dataframe["rank"].astype("Int64")
        return dataframe
