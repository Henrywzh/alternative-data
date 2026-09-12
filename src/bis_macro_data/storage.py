from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .models import BisObservation, BisSeriesMeta


class BisMacroStorage:
    SERIES_COLS = ["series_id", "country", "indicator", "title", "frequency", "units", "fetched_at"]
    OBSERVATIONS_COLS = ["period", "series_id", "country", "value", "release_date", "fetched_at", "is_projected"]

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "bis_macro"
        self.normalized_root = base_dir / "data" / "normalized" / "bis_macro"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_payload(self, run_id: str, name: str, data: Any) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def write_raw_bytes(self, run_id: str, name: str, data: bytes) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / name
        path.write_bytes(data)
        return path

    def load_series_meta(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "bis_series_meta.parquet"
        csv_path = self.normalized_root / "bis_series_meta.csv"
        if parquet_path.exists():
            return pd.read_parquet(parquet_path)[self.SERIES_COLS]
        if csv_path.exists():
            return pd.read_csv(csv_path)[self.SERIES_COLS]
        return pd.DataFrame(columns=self.SERIES_COLS)

    def load_observations(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "bis_observations.parquet"
        csv_path = self.normalized_root / "bis_observations.csv"
        if parquet_path.exists():
            return pd.read_parquet(parquet_path)[self.OBSERVATIONS_COLS]
        if csv_path.exists():
            return pd.read_csv(csv_path)[self.OBSERVATIONS_COLS]
        return pd.DataFrame(columns=self.OBSERVATIONS_COLS)

    def upsert_series_meta(self, records: Iterable[BisSeriesMeta]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.SERIES_COLS)
        if incoming.empty:
            return self.load_series_meta()
        existing = self.load_series_meta()
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        merged = merged.drop_duplicates(subset=["series_id"], keep="last")
        merged = merged.sort_values(by=["series_id"]).reset_index(drop=True)
        # No CSV twin: `*.csv` is gitignored repo-wide, so the twin was never
        # published -- it only cost local disk (151 MB against a 12 MB parquet
        # for the largest lane) and doubled the write on every refresh.
        merged.to_parquet(self.normalized_root / "bis_series_meta.parquet", index=False)
        return merged

    def upsert_observations(self, records: Iterable[BisObservation]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.OBSERVATIONS_COLS)
        if incoming.empty:
            return self.load_observations()
        existing = self.load_observations()
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        merged["value"] = pd.to_numeric(merged["value"], errors="coerce")
        merged = merged.drop_duplicates(subset=["series_id", "period"], keep="last")
        merged = merged.sort_values(by=["series_id", "period"]).reset_index(drop=True)
        merged.to_parquet(self.normalized_root / "bis_observations.parquet", index=False)
        return merged
