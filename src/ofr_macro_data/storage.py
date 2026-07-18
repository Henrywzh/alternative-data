import json
import logging
from pathlib import Path
from typing import Any, Iterable
import pandas as pd
from .models import OfrMnemonic, OfrDataPoint

logger = logging.getLogger(__name__)

class OfrStorage:
    MNEMONICS_COLS = ["mnemonic", "name", "notes", "frequency", "start_date", "last_update", "fetched_at"]
    TIMESERIES_COLS = ["date", "mnemonic", "value", "fetched_at"]

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "ofr_macro"
        self.normalized_root = base_dir / "data" / "normalized" / "ofr_macro"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_payload(self, run_id: str, name: str, data: Any) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return path

    def load_mnemonics(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "ofr_mnemonics.parquet"
        csv_path = self.normalized_root / "ofr_mnemonics.csv"
        if parquet_path.exists():
            df = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            return pd.DataFrame(columns=self.MNEMONICS_COLS)
        return df[self.MNEMONICS_COLS]

    def load_timeseries(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "ofr_timeseries.parquet"
        csv_path = self.normalized_root / "ofr_timeseries.csv"
        if parquet_path.exists():
            df = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            return pd.DataFrame(columns=self.TIMESERIES_COLS)
        return df[self.TIMESERIES_COLS]

    def upsert_mnemonics(self, records: Iterable[OfrMnemonic]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.MNEMONICS_COLS)
        if incoming.empty:
            return self.load_mnemonics()

        existing = self.load_mnemonics()
        if not existing.empty:
            merged = pd.concat([existing, incoming], ignore_index=True)
        else:
            merged = incoming.copy()

        merged = merged.drop_duplicates(subset=["mnemonic"], keep="last")
        merged = merged.sort_values(by=["mnemonic"]).reset_index(drop=True)

        parquet_path = self.normalized_root / "ofr_mnemonics.parquet"
        csv_path = self.normalized_root / "ofr_mnemonics.csv"
        merged.to_parquet(parquet_path, index=False)
        merged.to_csv(csv_path, index=False)
        return merged

    def upsert_timeseries(self, records: Iterable[OfrDataPoint]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.TIMESERIES_COLS)
        if incoming.empty:
            return self.load_timeseries()

        existing = self.load_timeseries()
        if not existing.empty:
            merged = pd.concat([existing, incoming], ignore_index=True)
        else:
            merged = incoming.copy()

        merged["value"] = pd.to_numeric(merged["value"], errors="coerce")
        merged = merged.drop_duplicates(subset=["mnemonic", "date"], keep="last")
        merged = merged.sort_values(by=["mnemonic", "date"]).reset_index(drop=True)

        parquet_path = self.normalized_root / "ofr_timeseries.parquet"
        csv_path = self.normalized_root / "ofr_timeseries.csv"
        merged.to_parquet(parquet_path, index=False)
        merged.to_csv(csv_path, index=False)
        return merged
