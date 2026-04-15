from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from compute_availability_data.models import DatasetRecord, Snapshot


NATURAL_KEYS: dict[str, list[str]] = {
    "raw_openrouter_models": ["model_id", "snapshot_ts"],
    "raw_lambda_instance_types": ["instance_type_name", "region", "snapshot_ts"],
    "raw_aws_spot_price_history": ["instance_type", "availability_zone", "product_description", "price_timestamp"],
}

DATASET_COLUMNS = [
    "dataset_id",
    "source_url",
    "source_run_id",
    "scraped_at",
    "snapshot_ts",
    "model_id",
    "model_name",
    "created_at",
    "context_length",
    "architecture",
    "pricing_prompt",
    "pricing_completion",
    "top_provider_id",
    "instance_type_name",
    "gpu_type",
    "gpu_count",
    "region",
    "availability_zone",
    "instance_type",
    "product_description",
    "spot_price",
    "price_timestamp",
]

NUMERIC_COLUMNS = [
    "created_at",
    "context_length",
    "pricing_prompt",
    "pricing_completion",
    "gpu_count",
    "spot_price",
]

BOOL_COLUMNS = []

TEXT_COLUMNS = [
    column for column in DATASET_COLUMNS if column not in NUMERIC_COLUMNS and column not in BOOL_COLUMNS
]

SORT_KEYS: dict[str, list[str]] = {
    "raw_openrouter_models": ["snapshot_ts", "model_id"],
    "raw_lambda_instance_types": ["snapshot_ts", "region", "instance_type_name"],
    "raw_aws_spot_price_history": ["price_timestamp", "availability_zone", "instance_type"],
}


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "compute_availability"
        self.normalized_root = base_dir / "data" / "normalized" / "compute_availability"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_run(self, run_id: str, snapshots: Iterable[Snapshot], manifest: dict[str, Any]) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in snapshots:
            suffix = ".json" if snapshot.body.strip().startswith(("{", "[")) else ".txt"
            (run_dir / f"{snapshot.name}{suffix}").write_text(snapshot.body, encoding="utf-8")
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
            return self.load_dataset(dataset_id)

        existing = self.load_dataset(dataset_id)
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        merged = self._coerce_types(merged)
        merged = merged.drop_duplicates(subset=NATURAL_KEYS[dataset_id], keep="last")
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
        for column in TEXT_COLUMNS:
            dataframe[column] = dataframe[column].astype("string")
        return dataframe
