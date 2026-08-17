from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from taiwan_semiconductor_revenue_data.models import Snapshot


DATASET_SPECS: dict[str, dict[str, list[str]]] = {
    "tw_monthly_revenue": {
        "columns": [
            "dataset_id",
            "company_code",
            "company_name",
            "market",
            "industry",
            "filing_date",
            "revenue_month",
            "monthly_revenue_ntd",
            "mom_pct",
            "mom_pct_is_derived",
            "yoy_pct",
            "ytd_revenue_ntd",
            "ytd_yoy_pct",
            "source_url",
            "source_run_id",
            "scraped_at",
            "parser_version",
            "raw_company_name_text",
            "raw_monthly_revenue_text",
            "raw_mom_pct_text",
            "raw_yoy_pct_text",
            "raw_ytd_revenue_text",
            "raw_ytd_yoy_pct_text",
        ],
        "natural_key": ["company_code", "revenue_month"],
        "sort_keys": ["revenue_month", "market", "company_code"],
        "numeric": [
            "monthly_revenue_ntd",
            "mom_pct",
            "yoy_pct",
            "ytd_revenue_ntd",
            "ytd_yoy_pct",
        ],
        "bool": ["mom_pct_is_derived"],
    }
}


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "taiwan_semiconductor_revenue"
        self.normalized_root = base_dir / "data" / "normalized" / "taiwan_semiconductor_revenue"
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
        if incoming.empty:
            return self.load_dataset(dataset_id)

        existing = self.load_dataset(dataset_id)
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        merged = self._coerce_types(merged, dataset_id)
        merged = merged.drop_duplicates(subset=spec["natural_key"], keep="last")
        merged = merged.sort_values(by=spec["sort_keys"], na_position="last").reset_index(drop=True)
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"
        csv_path = self.normalized_root / f"{dataset_id}.csv"
        merged.to_parquet(parquet_path, index=False)
        csv_path.unlink(missing_ok=True)
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
