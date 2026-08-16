import json
import logging
from pathlib import Path
from typing import Any, Iterable
import pandas as pd
from .models import FredSeriesMeta, FredObservation

logger = logging.getLogger(__name__)

class FredMacroStorage:
    SERIES_COLS = ["series_id", "title", "frequency", "units", "seasonal_adjustment", "observation_start", "last_updated", "fetched_at"]
    OBSERVATIONS_COLS = ["date", "series_id", "value", "fetched_at", "realtime_start", "realtime_end"]

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "fred_macro"
        self.normalized_root = base_dir / "data" / "normalized" / "fred_macro"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_payload(self, run_id: str, name: str, data: Any) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return path

    def load_series_meta(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "fred_series_meta.parquet"
        csv_path = self.normalized_root / "fred_series_meta.csv"
        if parquet_path.exists():
            df = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            return pd.DataFrame(columns=self.SERIES_COLS)
        return df[self.SERIES_COLS]

    def load_observations(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "fred_observations.parquet"
        csv_path = self.normalized_root / "fred_observations.csv"
        if parquet_path.exists():
            df = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            return pd.DataFrame(columns=self.OBSERVATIONS_COLS)
        for col in ("realtime_start", "realtime_end"):
            if col not in df.columns:
                df[col] = None
        return df[self.OBSERVATIONS_COLS]

    def upsert_series_meta(self, records: Iterable[FredSeriesMeta]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.SERIES_COLS)
        if incoming.empty:
            return self.load_series_meta()

        existing = self.load_series_meta()
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()

        merged = merged.drop_duplicates(subset=["series_id"], keep="last")
        merged = merged.sort_values(by=["series_id"]).reset_index(drop=True)

        parquet_path = self.normalized_root / "fred_series_meta.parquet"
        csv_path = self.normalized_root / "fred_series_meta.csv"
        merged.to_parquet(parquet_path, index=False)
        merged.to_csv(csv_path, index=False)
        return merged

    def upsert_observations(self, records: Iterable[FredObservation]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.OBSERVATIONS_COLS)
        if incoming.empty:
            return self.load_observations()

        existing = self.load_observations()
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()

        merged["value"] = pd.to_numeric(merged["value"], errors="coerce")
        for col in ("realtime_start", "realtime_end"):
            if col not in merged.columns:
                merged[col] = None

        merged = merged.drop_duplicates(subset=["series_id", "date", "realtime_start"], keep="last")
        merged = merged.sort_values(by=["series_id", "date", "realtime_start"]).reset_index(drop=True)

        parquet_path = self.normalized_root / "fred_observations.parquet"
        csv_path = self.normalized_root / "fred_observations.csv"
        merged.to_parquet(parquet_path, index=False)
        merged.to_csv(csv_path, index=False)
        return merged
