from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .models import CmeObservation


class CmeVoiStorage:
    OBS_COLS = [
        "trade_date",
        "product_code",
        "contract_month",
        "settle_price",
        "price_change",
        "volume",
        "open_interest",
        "open_interest_change",
        "flow_regime",
        "fetched_at",
    ]

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "cme_voi"
        self.normalized_root = base_dir / "data" / "normalized" / "cme_voi"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_payload(self, run_id: str, name: str, data: Any) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def load_observations(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "cme_futures_voi.parquet"
        csv_path = self.normalized_root / "cme_futures_voi.csv"
        if parquet_path.exists():
            return pd.read_parquet(parquet_path)[self.OBS_COLS]
        if csv_path.exists():
            return pd.read_csv(csv_path)[self.OBS_COLS]
        return pd.DataFrame(columns=self.OBS_COLS)

    def upsert_observations(self, records: Iterable[CmeObservation]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.OBS_COLS)
        if incoming.empty:
            return self.load_observations()
        existing = self.load_observations()
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        for col in ["settle_price", "volume", "open_interest", "open_interest_change"]:
            merged[col] = pd.to_numeric(merged[col], errors="coerce")
        merged = merged.drop_duplicates(subset=["trade_date", "product_code", "contract_month"], keep="last")
        merged = merged.sort_values(by=["product_code", "trade_date", "contract_month"]).reset_index(drop=True)
        # No CSV twin: `*.csv` is gitignored repo-wide, so the twin was never
        # published -- it only cost local disk (151 MB against a 12 MB parquet
        # for the largest lane) and doubled the write on every refresh.
        merged.to_parquet(self.normalized_root / "cme_futures_voi.parquet", index=False)
        return merged
