from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from semiconductor_proxy_data.models import Snapshot


DATASET_SPECS: dict[str, dict[str, list[str]]] = {
    "semiconductor_official_monthly": {
        "columns": [
            "dataset_id",
            "source_region",
            "country_name",
            "metric_type",
            "flow_code",
            "partner_scope",
            "period",
            "release_date",
            "expected_release_window_days",
            "lag_days",
            "category_id",
            "category_label",
            "classification_system",
            "classification_code",
            "unit",
            "currency",
            "value",
            "yoy_pct",
            "mom_pct",
            "is_preliminary",
            "is_revised",
            "is_official_primary",
            "comparison_gap_pct",
            "source_name",
            "source_url",
            "source_run_id",
            "scraped_at",
            "parser_version",
        ],
        "natural_key": ["source_region", "metric_type", "category_id", "flow_code", "period", "partner_scope"],
        "sort_keys": ["period", "source_region", "metric_type", "category_id", "flow_code", "partner_scope"],
        "numeric": ["expected_release_window_days", "lag_days", "value", "yoy_pct", "mom_pct", "comparison_gap_pct"],
        "bool": ["is_preliminary", "is_revised", "is_official_primary"],
    },
    "semiconductor_backup_check_monthly": {
        "columns": [
            "dataset_id",
            "source_region",
            "country_name",
            "metric_type",
            "flow_code",
            "partner_scope",
            "period",
            "release_date",
            "expected_release_window_days",
            "lag_days",
            "category_id",
            "category_label",
            "classification_system",
            "classification_code",
            "unit",
            "currency",
            "value",
            "yoy_pct",
            "mom_pct",
            "is_preliminary",
            "is_revised",
            "is_official_primary",
            "comparison_gap_pct",
            "source_name",
            "source_url",
            "source_run_id",
            "scraped_at",
            "parser_version",
        ],
        "natural_key": ["source_region", "metric_type", "category_id", "flow_code", "period", "partner_scope", "source_name"],
        "sort_keys": ["period", "source_region", "metric_type", "category_id", "flow_code", "partner_scope"],
        "numeric": ["expected_release_window_days", "lag_days", "value", "yoy_pct", "mom_pct", "comparison_gap_pct"],
        "bool": ["is_preliminary", "is_revised", "is_official_primary"],
    },
    "semiconductor_source_catalog": {
        "columns": [
            "dataset_id",
            "source_region",
            "country_name",
            "source_name",
            "source_tier",
            "metric_type",
            "category_id",
            "category_label",
            "coverage_start",
            "latest_period",
            "cadence",
            "expected_release_window_days",
            "default_unit",
            "default_currency",
            "is_official_primary",
            "notes",
            "source_url",
            "source_run_id",
            "scraped_at",
        ],
        "natural_key": ["source_region", "source_name", "metric_type", "category_id", "source_tier"],
        "sort_keys": ["source_region", "source_tier", "metric_type", "category_id", "source_name"],
        "numeric": ["expected_release_window_days"],
        "bool": ["is_official_primary"],
    },
}


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "semiconductor_proxies"
        self.normalized_root = base_dir / "data" / "normalized" / "semiconductor_proxies"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_run(self, run_id: str, snapshots: Iterable[Snapshot], manifest: dict[str, Any]) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in snapshots:
            stripped = snapshot.body.lstrip()
            if stripped.startswith("{") or stripped.startswith("["):
                suffix = ".json"
            elif stripped.startswith("<"):
                suffix = ".html"
            else:
                suffix = ".txt"
            (run_dir / f"{snapshot.name}{suffix}").write_text(snapshot.body, encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return run_dir

    def load_dataset(self, dataset_id: str) -> pd.DataFrame:
        spec = DATASET_SPECS[dataset_id]
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"
        if not parquet_path.exists():
            return pd.DataFrame(columns=spec["columns"])

        dataframe = pd.read_parquet(parquet_path)
        for column in spec["columns"]:
            if column not in dataframe.columns:
                dataframe[column] = pd.NA
        return dataframe[spec["columns"]]

    def upsert_dataset(self, dataset_id: str, records: Iterable[object]) -> pd.DataFrame:
        spec = DATASET_SPECS[dataset_id]
        incoming = pd.DataFrame([record.to_dict() for record in records], columns=spec["columns"])
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"

        if incoming.empty:
            existing = self.load_dataset(dataset_id)
            if not parquet_path.exists():
                existing = self._coerce_types(existing, dataset_id)
                existing.to_parquet(parquet_path, index=False)
            return existing

        existing = self.load_dataset(dataset_id)
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        merged = self._coerce_types(merged, dataset_id)
        merged = merged.drop_duplicates(subset=spec["natural_key"], keep="last")
        merged = merged.sort_values(by=spec["sort_keys"], na_position="last").reset_index(drop=True)
        merged.to_parquet(parquet_path, index=False)
        return merged

    @staticmethod
    def _coerce_types(dataframe: pd.DataFrame, dataset_id: str) -> pd.DataFrame:
        spec = DATASET_SPECS[dataset_id]
        for column in spec["numeric"]:
            dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")
        for column in spec["bool"]:
            dataframe[column] = dataframe[column].astype("boolean")
        text_columns = [column for column in spec["columns"] if column not in spec["numeric"] and column not in spec["bool"]]
        for column in text_columns:
            dataframe[column] = dataframe[column].astype("string")
        return dataframe
