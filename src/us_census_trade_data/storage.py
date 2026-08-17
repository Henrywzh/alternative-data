from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from us_census_trade_data.models import Snapshot


DATASET_ID = "us_census_memory_imports_monthly"
PORT_DATASET_ID = "us_census_memory_imports_port_monthly"
DATASET_SPECS: dict[str, dict[str, list[str]]] = {
    DATASET_ID: {
        "columns": [
            "dataset_id",
            "period",
            "reporter_country_code",
            "reporter_country_name",
            "partner_country_code",
            "partner_country_name",
            "hs_code",
            "item_name",
            "general_import_value_usd",
            "general_import_quantity",
            "general_import_quantity_unit",
            "general_import_quantity_2",
            "general_import_quantity_2_unit",
            "air_import_value_usd",
            "air_shipping_weight",
            "containerized_vessel_import_value_usd",
            "containerized_vessel_shipping_weight",
            "vessel_import_value_usd",
            "vessel_shipping_weight",
            "consumption_import_value_usd",
            "consumption_import_quantity",
            "consumption_import_quantity_unit",
            "consumption_import_quantity_2",
            "consumption_import_quantity_2_unit",
            "general_value_per_quantity_unit_usd",
            "last_update",
            "source_name",
            "source_url",
            "source_run_id",
            "scraped_at",
            "parser_version",
        ],
        "natural_key": ["period", "partner_country_code", "hs_code"],
        "sort_keys": ["period", "partner_country_code", "hs_code"],
        "numeric": [
            "general_import_value_usd",
            "general_import_quantity",
            "general_import_quantity_2",
            "air_import_value_usd",
            "air_shipping_weight",
            "containerized_vessel_import_value_usd",
            "containerized_vessel_shipping_weight",
            "vessel_import_value_usd",
            "vessel_shipping_weight",
            "consumption_import_value_usd",
            "consumption_import_quantity",
            "consumption_import_quantity_2",
            "general_value_per_quantity_unit_usd",
        ],
        "bool": [],
    },
    PORT_DATASET_ID: {
        "columns": [
            "dataset_id",
            "period",
            "reporter_country_code",
            "reporter_country_name",
            "partner_country_code",
            "partner_country_name",
            "hs_code",
            "item_name",
            "port_code",
            "port_name",
            "general_import_value_usd",
            "air_import_value_usd",
            "air_shipping_weight",
            "containerized_vessel_import_value_usd",
            "containerized_vessel_shipping_weight",
            "vessel_import_value_usd",
            "vessel_shipping_weight",
            "last_update",
            "source_name",
            "source_url",
            "source_run_id",
            "scraped_at",
            "parser_version",
        ],
        "natural_key": ["period", "port_code", "partner_country_code", "hs_code"],
        "sort_keys": ["period", "partner_country_code", "hs_code", "port_code"],
        "numeric": [
            "general_import_value_usd",
            "air_import_value_usd",
            "air_shipping_weight",
            "containerized_vessel_import_value_usd",
            "containerized_vessel_shipping_weight",
            "vessel_import_value_usd",
            "vessel_shipping_weight",
        ],
        "bool": [],
    },
}


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "us_census_trade"
        self.normalized_root = base_dir / "data" / "normalized" / "us_census_trade"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_run(self, run_id: str, snapshots: Iterable[Snapshot], manifest: dict[str, Any]) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in snapshots:
            (run_dir / f"{snapshot.name}.json").write_text(snapshot.body, encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return run_dir

    def load_dataset(self, dataset_id: str = DATASET_ID) -> pd.DataFrame:
        spec = DATASET_SPECS[dataset_id]
        path = self.normalized_root / f"{dataset_id}.parquet"
        if not path.exists():
            return pd.DataFrame(columns=spec["columns"])
        dataframe = pd.read_parquet(path)
        for column in spec["columns"]:
            if column not in dataframe.columns:
                dataframe[column] = pd.NA
        return dataframe[spec["columns"]]

    def upsert_dataset(self, records: Iterable[object], dataset_id: str = DATASET_ID) -> pd.DataFrame:
        spec = DATASET_SPECS[dataset_id]
        incoming = pd.DataFrame([record.to_dict() for record in records], columns=spec["columns"])
        incoming = self._coerce_types(incoming, dataset_id)
        existing = self._coerce_types(self.load_dataset(dataset_id), dataset_id)
        if incoming.empty and existing.empty:
            dataframe = incoming
        elif incoming.empty:
            dataframe = existing
        else:
            merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming
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
        text_columns = [
            column for column in spec["columns"]
            if column not in spec["numeric"] and column not in spec["bool"]
        ]
        for column in text_columns:
            dataframe[column] = dataframe[column].astype("string")
        return dataframe[spec["columns"]]
