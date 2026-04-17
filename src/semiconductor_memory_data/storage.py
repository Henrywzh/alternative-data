from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pandas as pd

from semiconductor_memory_data.models import DatasetRecord, Snapshot


NATURAL_KEYS: dict[str, list[str]] = {
    "adata_marketwatch_raw":               ["month"],
    "adata_marketwatch_images":            ["month", "image_url"],
    "adata_marketwatch_monthly":           ["month"],
    "fred_semiconductor_ppi":              ["date", "series_id"],
    "semiconductor_memory_regime_monthly": ["month"],
}

SORT_KEYS: dict[str, list[str]] = {
    "adata_marketwatch_raw":               ["month"],
    "adata_marketwatch_images":            ["month", "image_url"],
    "adata_marketwatch_monthly":           ["month"],
    "fred_semiconductor_ppi":             ["series_id", "date"],
    "semiconductor_memory_regime_monthly": ["month"],
}

DATASET_COLUMNS = [
    "dataset_id",
    "source_url",
    "source_run_id",
    "scraped_at",
    # adata_marketwatch_raw
    "month",
    "fetch_time",
    "title",
    "raw_text",
    "raw_html_path",
    # adata_marketwatch_images
    "page_url",
    "image_url",
    "local_path",
    "image_type",
    "vision_extracted",
    "vision_result_json",
    "extracted_at",
    # adata_marketwatch_monthly
    "narrative_nand_supply",
    "narrative_nand_price",
    "narrative_dram_supply",
    "narrative_dram_price",
    "mentions_hbm",
    "mentions_csp",
    "mentions_server",
    "mentions_ddr4",
    "mentions_reallocate_capacity",
    "mentions_shortage",
    "mentions_oversupply",
    "nand_regime_label",
    "dram_regime_label",
    # fred_semiconductor_ppi
    "date",
    "series_id",
    "series_name",
    "value",
    # semiconductor_memory_regime_monthly
    "fred_ppi_value",
    "fred_ppi_mom_pct",
    "fred_ppi_3m_trend",
    "ppi_component_pcu33443344_rebased",
    "ppi_component_pcu33423342_rebased",
    "ppi_component_pcu335313335313_rebased",
    "ppi_component_pcu334111334111_rebased",
    "ppi_component_pcu3341123341121_rebased",
    "adata_freshness_days",
    "fred_release_lag_days",
    "data_completeness",
]

NUMERIC_COLUMNS = [
    "value",
    "fred_ppi_value",
    "fred_ppi_mom_pct",
    "fred_ppi_3m_trend",
    "ppi_component_pcu33443344_rebased",
    "ppi_component_pcu33423342_rebased",
    "ppi_component_pcu335313335313_rebased",
    "ppi_component_pcu334111334111_rebased",
    "ppi_component_pcu3341123341121_rebased",
    "adata_freshness_days",
    "fred_release_lag_days",
]

BOOL_COLUMNS = [
    "vision_extracted",
    "mentions_hbm",
    "mentions_csp",
    "mentions_server",
    "mentions_ddr4",
    "mentions_reallocate_capacity",
    "mentions_shortage",
    "mentions_oversupply",
]

TEXT_COLUMNS = [
    column for column in DATASET_COLUMNS
    if column not in NUMERIC_COLUMNS and column not in BOOL_COLUMNS
]


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "semiconductor_memory"
        self.normalized_root = base_dir / "data" / "normalized" / "semiconductor_memory"
        self.images_root = self.raw_root / "images"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)
        self.images_root.mkdir(parents=True, exist_ok=True)

    def write_raw_run(
        self,
        run_id: str,
        snapshots: list[Snapshot],
        manifest: dict[str, Any],
    ) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in snapshots:
            stripped = snapshot.body.lstrip()
            if stripped.startswith(("{", "[")):
                suffix = ".json"
            elif stripped.lower().startswith("<"):
                suffix = ".html"
            else:
                suffix = ".txt"
            (run_dir / f"{snapshot.name}{suffix}").write_text(snapshot.body, encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return run_dir

    def load_dataset(self, dataset_id: str) -> pd.DataFrame:
        csv_path = self.normalized_root / f"{dataset_id}.csv"
        if not csv_path.exists():
            return pd.DataFrame(columns=DATASET_COLUMNS)
        dataframe = pd.read_csv(csv_path, low_memory=False)
        for column in DATASET_COLUMNS:
            if column not in dataframe.columns:
                dataframe[column] = pd.NA
        return dataframe[DATASET_COLUMNS]

    def upsert_dataset(self, dataset_id: str, records: list[DatasetRecord]) -> pd.DataFrame:
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

    def save_image(self, month: str, image_url: str, image_bytes: bytes) -> Path:
        """Download and store an image file; skips if already exists (idempotent)."""
        filename = Path(urlparse(image_url).path).name
        month_dir = self.images_root / month
        month_dir.mkdir(parents=True, exist_ok=True)
        dest = month_dir / filename
        if not dest.exists():
            dest.write_bytes(image_bytes)
        return dest

    @staticmethod
    def _coerce_types(dataframe: pd.DataFrame) -> pd.DataFrame:
        for column in NUMERIC_COLUMNS:
            if column in dataframe.columns:
                dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")
        for column in BOOL_COLUMNS:
            if column in dataframe.columns:
                dataframe[column] = dataframe[column].map(
                    lambda value: value
                    if pd.isna(value) or isinstance(value, bool)
                    else str(value).strip().lower() == "true"
                )
        for column in TEXT_COLUMNS:
            if column in dataframe.columns:
                dataframe[column] = dataframe[column].astype("string")
        return dataframe
