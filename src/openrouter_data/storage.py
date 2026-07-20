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
    "provider_weekly_requests": ["week_start_date", "entity_id"],
    "categories_programming": ["week_start_date", "category_slug", "entity_id"],
    "context_length_requests": ["week_start_date", "context_length_bucket", "entity_id"],
    "modality_rankings": ["week_start_date", "modality", "entity_id"],
    "app_metadata_snapshots": ["app_id", "scrape_date"],
    "app_usage_daily": ["app_id", "usage_date", "model_permaslug"],
    "app_top_models_daily_snapshot": ["app_id", "snapshot_date", "model_permaslug"],
    "apps_global_ranking_snapshots": ["snapshot_date", "period", "rank"],
    "apps_trending_snapshots": ["snapshot_date", "rank"],
    "openrouter_model_activity": ["usage_date", "model_permaslug", "category_slug"],
    # Provider pages can emit the synthetic `Others` bucket for every
    # provider.  Keep provider identity in the grain so same-day buckets do
    # not overwrite one another during the upsert.
    "provider_daily_activity": ["usage_date", "entity_id", "model_permaslug"],
    "openrouter_task_spend": ["snapshot_date", "period", "window_days", "category_slug", "model_permaslug"],
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
    "context_length_bucket",
    "modality",
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
    "reasoning_tokens",
    "request_count",
    "window_days",
    "macro_category",
    "task_share_of_total",
    "model_share",
    "delta_pp",
]

NUMERIC_COLUMNS = [
    "metric_value",
    "rank",
    "total_tokens",
    "tokens",
    "growth_percent",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "request_count",
    "window_days",
    "task_share_of_total",
    "model_share",
    "delta_pp",
]
BOOL_COLUMNS = ["group_by_origin", "is_private", "is_hidden"]
TEXT_COLUMNS = [
    column
    for column in DATASET_COLUMNS
    if column not in NUMERIC_COLUMNS and column not in BOOL_COLUMNS
]
SORT_KEYS: dict[str, list[str]] = {
    "top_models": ["week_start_date", "rank", "entity_id"],
    "market_share": ["week_start_date", "rank", "entity_id"],
    "provider_weekly_requests": ["week_start_date", "rank", "entity_id"],
    "categories_programming": ["week_start_date", "rank", "entity_id"],
    "context_length_requests": ["week_start_date", "context_length_bucket", "rank", "entity_id"],
    "modality_rankings": ["week_start_date", "modality", "rank", "entity_id"],
    "app_metadata_snapshots": ["scrape_date", "app_id"],
    "app_usage_daily": ["usage_date", "app_id", "rank", "model_permaslug"],
    "app_top_models_daily_snapshot": ["snapshot_date", "app_id", "rank", "model_permaslug"],
    "apps_global_ranking_snapshots": ["snapshot_date", "period", "rank", "origin_url"],
    "apps_trending_snapshots": ["snapshot_date", "rank", "origin_url"],
    "openrouter_model_activity": ["usage_date", "model_permaslug", "category_slug"],
    "provider_daily_activity": ["usage_date", "entity_id", "model_permaslug"],
    "openrouter_task_spend": ["snapshot_date", "period", "category_slug", "rank", "model_permaslug"],
}
PARQUET_ONLY_DATASETS = {"provider_daily_activity", "openrouter_model_activity"}
RETENTION_DAYS = {
    # Daily model detail can add thousands of category rows per run. A rolling
    # six-month window keeps the Streamlit load useful without unbounded growth.
    "openrouter_model_activity": 180,
}


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "openrouter"
        self.normalized_root = base_dir / "data" / "normalized" / "openrouter"
        self.archive_root = base_dir / "data" / "normalized" / "openrouter_archive"
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
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"
        if parquet_path.exists():
            dataframe = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            dataframe = pd.read_csv(csv_path)
        else:
            return pd.DataFrame(columns=DATASET_COLUMNS)
        for column in DATASET_COLUMNS:
            if column not in dataframe.columns:
                dataframe[column] = pd.NA
        return dataframe[DATASET_COLUMNS]

    def upsert_dataset(
        self,
        dataset_id: str,
        records: Iterable[DatasetRecord],
        *,
        replace_partitions: list[str] | None = None,
    ) -> pd.DataFrame:
        incoming = pd.DataFrame([record.to_dict() for record in records], columns=DATASET_COLUMNS)
        if incoming.empty:
            raise ValidationError(f"Dataset {dataset_id} has no incoming records")
        existing = self.load_dataset(dataset_id)
        if not existing.empty and replace_partitions:
            missing = [column for column in replace_partitions if column not in incoming.columns]
            if missing:
                raise ValidationError(
                    f"Dataset {dataset_id} cannot replace partitions; missing columns: {missing}"
                )
            incoming_partitions = pd.MultiIndex.from_frame(
                incoming[replace_partitions].astype("string").drop_duplicates()
            )
            existing_partitions = pd.MultiIndex.from_frame(existing[replace_partitions].astype("string"))
            existing = existing[~existing_partitions.isin(incoming_partitions)].copy()
        if existing.empty:
            merged = incoming.copy()
        else:
            merged = pd.concat([existing, incoming], ignore_index=True)
        merged = self._coerce_types(merged)
        keys = NATURAL_KEYS[dataset_id]
        merged = merged.drop_duplicates(subset=keys, keep="last")
        retention_days = RETENTION_DAYS.get(dataset_id)
        if retention_days and merged["usage_date"].notna().any():
            usage_dates = pd.to_datetime(merged["usage_date"], errors="coerce")
            latest_usage_date = usage_dates.max()
            if pd.notna(latest_usage_date):
                cutoff = latest_usage_date - pd.Timedelta(days=retention_days - 1)
                archive_rows = merged[usage_dates < cutoff].copy()
                if not archive_rows.empty:
                    self._archive_rows(dataset_id, archive_rows)
                merged = merged[usage_dates >= cutoff].copy()
        merged = merged.sort_values(by=SORT_KEYS[dataset_id], na_position="last").reset_index(drop=True)

        csv_path = self.normalized_root / f"{dataset_id}.csv"
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"
        merged.to_parquet(parquet_path, index=False)
        if dataset_id in PARQUET_ONLY_DATASETS:
            csv_path.unlink(missing_ok=True)
        else:
            merged.to_csv(csv_path, index=False)
        return merged

    def _archive_rows(self, dataset_id: str, rows: pd.DataFrame) -> None:
        """Persist rows before rolling-window eviction.

        Archive files are deliberately outside dashboard registry domains, so
        they preserve research-grade detail without being loaded by Streamlit.
        """

        dated = rows.copy()
        years = pd.to_datetime(dated["usage_date"], errors="coerce").dt.year
        dated = dated[years.notna()].copy()
        if dated.empty:
            return
        dated["_archive_year"] = years[years.notna()].astype(int).to_numpy()
        self.archive_root.mkdir(parents=True, exist_ok=True)
        for year, group in dated.groupby("_archive_year"):
            path = self.archive_root / f"{dataset_id}_{int(year)}.parquet"
            archived = pd.read_parquet(path) if path.exists() else pd.DataFrame(columns=DATASET_COLUMNS)
            incoming = group.drop(columns="_archive_year").reindex(columns=DATASET_COLUMNS)
            combined = pd.concat([archived, incoming], ignore_index=True) if not archived.empty else incoming.copy()
            combined = self._coerce_types(combined)
            combined = combined.drop_duplicates(subset=NATURAL_KEYS[dataset_id], keep="last")
            combined = combined.sort_values(SORT_KEYS[dataset_id], na_position="last").reset_index(drop=True)
            temp_path = path.with_suffix(".tmp")
            combined.to_parquet(temp_path, index=False)
            temp_path.replace(path)

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
