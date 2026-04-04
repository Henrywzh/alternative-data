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
}

DATASET_COLUMNS = [
    "dataset_id",
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
    "source_url",
    "source_run_id",
    "scraped_at",
    "category_slug",
]


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
        return pd.read_csv(csv_path)

    def upsert_dataset(self, dataset_id: str, records: Iterable[DatasetRecord]) -> pd.DataFrame:
        incoming = pd.DataFrame([record.to_dict() for record in records], columns=DATASET_COLUMNS)
        if incoming.empty:
            raise ValidationError(f"Dataset {dataset_id} has no incoming records")
        existing = self.load_dataset(dataset_id)
        if existing.empty:
            merged = incoming.copy()
        else:
            merged = pd.concat([existing, incoming], ignore_index=True)
        keys = NATURAL_KEYS[dataset_id]
        merged = merged.drop_duplicates(subset=keys, keep="last")
        merged["metric_value"] = merged["metric_value"].astype(float)
        merged["rank"] = merged["rank"].astype(int)
        merged = merged.sort_values(by=["week_start_date", "rank", "entity_id"]).reset_index(drop=True)

        csv_path = self.normalized_root / f"{dataset_id}.csv"
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"
        merged.to_csv(csv_path, index=False)
        merged.to_parquet(parquet_path, index=False)
        return merged
