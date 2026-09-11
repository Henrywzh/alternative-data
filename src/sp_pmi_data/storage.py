from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .models import SpPmiObservation


class SpPmiStorage:
    COLS = [
        "period", "region", "sector", "is_flash", "headline_pmi", "new_orders_index",
        "output_index", "finished_goods_inventory_index", "input_prices_index",
        "output_prices_index", "employment_index", "orders_to_inventory_ratio",
        "price_pass_through_spread", "release_date", "fetched_at",
        "source_url",
    ]

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "sp_pmi"
        self.normalized_root = base_dir / "data" / "normalized" / "sp_pmi"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_payload(self, run_id: str, name: str, data: Any) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def load_observations(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "sp_pmi_subindices.parquet"
        csv_path = self.normalized_root / "sp_pmi_subindices.csv"
        if parquet_path.exists():
            return pd.read_parquet(parquet_path)[self.COLS]
        if csv_path.exists():
            return pd.read_csv(csv_path)[self.COLS]
        return pd.DataFrame(columns=self.COLS)

    def upsert_observations(self, records: Iterable[SpPmiObservation]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.COLS)
        if incoming.empty:
            return self.load_observations()
        existing = self.load_observations()
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        for col in ["headline_pmi", "new_orders_index", "output_index", "finished_goods_inventory_index", "input_prices_index", "output_prices_index", "orders_to_inventory_ratio", "price_pass_through_spread"]:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")
        merged = merged.drop_duplicates(subset=["period", "region", "sector", "is_flash"], keep="last")
        merged = merged.sort_values(by=["region", "sector", "period", "is_flash"]).reset_index(drop=True)
        # No CSV twin: `*.csv` is gitignored repo-wide, so the twin was never
        # published -- it only cost local disk (151 MB against a 12 MB parquet
        # for the largest lane) and doubled the write on every refresh.
        merged.to_parquet(self.normalized_root / "sp_pmi_subindices.parquet", index=False)
        return merged
