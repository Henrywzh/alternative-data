from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from semiconductor_high_frequency_data.models import Snapshot


DATASET_SPECS: dict[str, dict[str, list[str]]] = {
    "kcs_10day_exports": {
        "columns": [
            "dataset_id", "period", "period_start", "period_end", "period_month",
            "release_date", "release_date_inferred", "metric", "value", "unit",
            "currency", "is_preliminary", "is_revised", "source_url", "source_run_id",
            "scraped_at", "parser_version", "raw_period_date",
        ],
        "natural_key": ["period", "metric"],
        "sort_keys": ["period_end", "metric"],
        "numeric": ["value"],
        "bool": ["release_date_inferred", "is_preliminary", "is_revised"],
    },
    "kcs_memory_monthly_country": {
        "columns": [
            "dataset_id", "period", "country_scope", "country_code", "country_name",
            "hs_code", "item_name", "export_value_usd", "export_weight_kg",
            "import_value_usd", "import_weight_kg", "trade_balance_usd",
            "export_value_per_kg_usd", "release_date", "is_preliminary", "is_revised",
            "source_url", "source_run_id", "scraped_at", "parser_version",
        ],
        "natural_key": ["period", "country_scope", "country_code", "hs_code"],
        "sort_keys": ["period", "country_scope", "hs_code"],
        "numeric": [
            "export_value_usd", "export_weight_kg", "import_value_usd", "import_weight_kg",
            "trade_balance_usd", "export_value_per_kg_usd",
        ],
        "bool": ["is_preliminary", "is_revised"],
    },
    "krx_positioning_daily": {
        "columns": [
            "dataset_id", "trade_date", "instrument_code", "instrument_name", "market",
            "data_family", "investor_type", "measure", "value", "unit", "currency",
            "availability_lag_days", "source_url", "source_run_id", "scraped_at",
            "parser_version",
        ],
        "natural_key": [
            "trade_date", "instrument_code", "data_family", "investor_type", "measure",
        ],
        "sort_keys": ["trade_date", "instrument_code", "data_family", "investor_type", "measure"],
        "numeric": ["value", "availability_lag_days"],
        "bool": [],
    },
    "kosis_semiconductor_cycle_monthly": {
        "columns": [
            "dataset_id", "period", "industry_code", "industry_name", "measure", "value",
            "unit", "seasonal_adjustment", "item_code", "item_name", "object_code",
            "object_name", "release_date", "source_table_id", "source_org_id", "source_url",
            "source_run_id", "scraped_at", "parser_version",
        ],
        "natural_key": [
            "period", "industry_code", "measure", "seasonal_adjustment", "item_code", "object_code",
        ],
        "sort_keys": ["period", "measure", "seasonal_adjustment", "industry_code"],
        "numeric": ["value"],
        "bool": [],
    },
}


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "semiconductor_high_frequency"
        self.normalized_root = base_dir / "data" / "normalized" / "semiconductor_high_frequency"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_run(self, run_id: str, snapshots: Iterable[Snapshot], manifest: dict[str, Any]) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in snapshots:
            suffix = ".json" if snapshot.body.lstrip().startswith(("{", "[")) else ".txt"
            (run_dir / f"{snapshot.name}{suffix}").write_text(snapshot.body, encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return run_dir

    def load_dataset(self, dataset_id: str) -> pd.DataFrame:
        spec = DATASET_SPECS[dataset_id]
        path = self.normalized_root / f"{dataset_id}.parquet"
        if not path.exists():
            return pd.DataFrame(columns=spec["columns"])
        dataframe = pd.read_parquet(path)
        for column in spec["columns"]:
            if column not in dataframe.columns:
                dataframe[column] = pd.NA
        return dataframe[spec["columns"]]

    def upsert_dataset(self, dataset_id: str, records: Iterable[object]) -> pd.DataFrame:
        spec = DATASET_SPECS[dataset_id]
        incoming = pd.DataFrame(
            [record.to_dict() for record in records],
            columns=spec["columns"],
        )
        existing = self.load_dataset(dataset_id)
        if incoming.empty and existing.empty:
            dataframe = self._coerce_types(incoming, dataset_id)
        elif existing.empty:
            dataframe = self._coerce_types(incoming, dataset_id)
        elif incoming.empty:
            dataframe = self._coerce_types(existing, dataset_id)
        else:
            merged = pd.concat([existing, incoming], ignore_index=True)
            dataframe = self._coerce_types(merged, dataset_id)
            dataframe = dataframe.drop_duplicates(subset=spec["natural_key"], keep="last")
            dataframe = dataframe.sort_values(by=spec["sort_keys"], na_position="last").reset_index(drop=True)
        path = self.normalized_root / f"{dataset_id}.parquet"
        dataframe.to_parquet(path, index=False)
        return dataframe

    @staticmethod
    def _coerce_types(dataframe: pd.DataFrame, dataset_id: str) -> pd.DataFrame:
        spec = DATASET_SPECS[dataset_id]
        for column in spec["numeric"]:
            dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")
        for column in spec["bool"]:
            dataframe[column] = dataframe[column].astype("boolean")
        text_columns = [
            column for column in spec["columns"]
            if column not in spec["numeric"] and column not in spec["bool"]
        ]
        for column in text_columns:
            dataframe[column] = dataframe[column].astype("string")
        return dataframe[spec["columns"]]
