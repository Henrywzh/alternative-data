from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from artificial_analysis_data.models import Snapshot


DATASET_SPECS: dict[str, dict[str, list[str]]] = {
    "artificial_analysis_models_daily": {
        "columns": [
            "dataset_id",
            "as_of_date",
            "model_id",
            "model_slug",
            "model_name",
            "creator_id",
            "creator_name",
            "creator_slug",
            "creator_country",
            "release_date",
            "release_quarter",
            "intelligence_index",
            "coding_index",
            "math_index",
            "gpqa",
            "scicode",
            "price_1m_blended_3_to_1",
            "price_1m_input_tokens",
            "price_1m_output_tokens",
            "median_output_tokens_per_second",
            "median_time_to_first_token_seconds",
            "context_window_tokens",
            "total_parameters_billions",
            "active_parameters_billions",
            "training_tokens_trillions",
            "open_source_categorization",
            "license_name",
            "is_open_weights",
            "source_url",
            "source_run_id",
            "scraped_at",
        ],
        "natural_key": ["as_of_date", "model_id"],
        "sort_keys": ["as_of_date", "creator_slug", "model_name"],
        "numeric": [
            "intelligence_index",
            "coding_index",
            "math_index",
            "gpqa",
            "scicode",
            "price_1m_blended_3_to_1",
            "price_1m_input_tokens",
            "price_1m_output_tokens",
            "median_output_tokens_per_second",
            "median_time_to_first_token_seconds",
            "context_window_tokens",
            "total_parameters_billions",
            "active_parameters_billions",
            "training_tokens_trillions",
        ],
        "bool": ["is_open_weights"],
    },
    "artificial_analysis_leading_models_by_lab_daily": {
        "columns": [
            "dataset_id",
            "as_of_date",
            "creator_id",
            "creator_name",
            "creator_slug",
            "creator_country",
            "model_id",
            "model_slug",
            "model_name",
            "release_date",
            "intelligence_index",
            "source_url",
            "source_run_id",
            "scraped_at",
        ],
        "natural_key": ["as_of_date", "creator_id"],
        "sort_keys": ["as_of_date", "creator_slug"],
        "numeric": ["intelligence_index"],
        "bool": [],
    },
    "artificial_analysis_context_window_quarter_daily": {
        "columns": [
            "dataset_id",
            "as_of_date",
            "release_quarter",
            "context_window_median_proprietary",
            "context_window_median_open_source_total",
            "proprietary_model_count",
            "open_source_model_count",
            "source_url",
            "source_run_id",
            "scraped_at",
        ],
        "natural_key": ["as_of_date", "release_quarter"],
        "sort_keys": ["as_of_date", "release_quarter"],
        "numeric": [
            "context_window_median_proprietary",
            "context_window_median_open_source_total",
            "proprietary_model_count",
            "open_source_model_count",
        ],
        "bool": [],
    },
    "artificial_analysis_capex_quarterly": {
        "columns": [
            "dataset_id",
            "quarter_id",
            "quarter_label",
            "microsoft",
            "google",
            "meta",
            "amazon",
            "oracle",
            "apple",
            "source_url",
            "page_url",
            "bundle_url",
            "source_run_id",
            "scraped_at",
        ],
        "natural_key": ["quarter_id"],
        "sort_keys": ["quarter_id"],
        "numeric": ["microsoft", "google", "meta", "amazon", "oracle", "apple"],
        "bool": [],
    },
}


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "artificial_analysis"
        self.normalized_root = base_dir / "data" / "normalized" / "artificial_analysis"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_run(self, run_id: str, snapshots: Iterable[Snapshot], manifest: dict[str, Any]) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in snapshots:
            suffix = _infer_suffix(snapshot)
            (run_dir / f"{snapshot.name}{suffix}").write_text(snapshot.body, encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return run_dir

    def load_dataset(self, dataset_id: str) -> pd.DataFrame:
        spec = DATASET_SPECS[dataset_id]
        csv_path = self.normalized_root / f"{dataset_id}.csv"
        if not csv_path.exists():
            return pd.DataFrame(columns=spec["columns"])
        dataframe = pd.read_csv(csv_path)
        for column in spec["columns"]:
            if column not in dataframe.columns:
                dataframe[column] = pd.NA
        return dataframe[spec["columns"]]

    def upsert_dataset(self, dataset_id: str, records: Iterable[object]) -> pd.DataFrame:
        spec = DATASET_SPECS[dataset_id]
        incoming = pd.DataFrame([record.to_dict() for record in records], columns=spec["columns"])
        if incoming.empty:
            return self.load_dataset(dataset_id)

        existing = self.load_dataset(dataset_id)
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        merged = self._coerce_types(merged, dataset_id)
        merged = merged.drop_duplicates(subset=spec["natural_key"], keep="last")
        merged = merged.sort_values(by=spec["sort_keys"], na_position="last").reset_index(drop=True)
        csv_path = self.normalized_root / f"{dataset_id}.csv"
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"
        merged.to_csv(csv_path, index=False)
        merged.to_parquet(parquet_path, index=False)
        return merged

    @staticmethod
    def _coerce_types(dataframe: pd.DataFrame, dataset_id: str) -> pd.DataFrame:
        spec = DATASET_SPECS[dataset_id]
        for column in spec["numeric"]:
            dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")
        for column in spec["bool"]:
            dataframe[column] = dataframe[column].map(
                lambda value: value
                if pd.isna(value) or isinstance(value, bool)
                else str(value).strip().lower() == "true"
            )
        text_columns = [column for column in spec["columns"] if column not in spec["numeric"] and column not in spec["bool"]]
        for column in text_columns:
            dataframe[column] = dataframe[column].astype("string")
        return dataframe


def _infer_suffix(snapshot: Snapshot) -> str:
    if snapshot.name.endswith((".json", ".html", ".js", ".txt")):
        return ""
    body = snapshot.body.lstrip()
    if snapshot.name.endswith("bundle") or snapshot.source_url.endswith(".js"):
        return ".js"
    if body.startswith("<!DOCTYPE html") or body.startswith("<html"):
        return ".html"
    if body.startswith("{") or body.startswith("["):
        return ".json"
    return ".txt"
