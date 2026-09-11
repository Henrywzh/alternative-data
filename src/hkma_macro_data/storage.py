from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from .models import AGGREGATOR, SOURCE_TIER_RANK, HkmaObservation, HkmaSeriesMeta


class HkmaMacroStorage:
    SERIES_COLS = ["series_id", "title", "category", "frequency", "units", "fetched_at", "source_tier"]
    OBSERVATIONS_COLS = ["date", "series_id", "value", "fetched_at", "source_url", "source_tier"]

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "hkma_macro"
        self.normalized_root = base_dir / "data" / "normalized" / "hkma_macro"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_payload(self, run_id: str, name: str, data: Any) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def load_series_meta(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "hkma_series_meta.parquet"
        csv_path = self.normalized_root / "hkma_series_meta.csv"
        if parquet_path.exists():
            return pd.read_parquet(parquet_path).reindex(columns=self.SERIES_COLS)
        if csv_path.exists():
            return pd.read_csv(csv_path).reindex(columns=self.SERIES_COLS)
        return pd.DataFrame(columns=self.SERIES_COLS)

    def load_observations(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / "hkma_observations.parquet"
        csv_path = self.normalized_root / "hkma_observations.csv"
        if parquet_path.exists():
            return pd.read_parquet(parquet_path).reindex(columns=self.OBSERVATIONS_COLS)
        if csv_path.exists():
            return pd.read_csv(csv_path).reindex(columns=self.OBSERVATIONS_COLS)
        return pd.DataFrame(columns=self.OBSERVATIONS_COLS)

    def upsert_series_meta(self, records: Iterable[HkmaSeriesMeta]) -> pd.DataFrame:
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
        merged.to_parquet(self.normalized_root / "hkma_series_meta.parquet", index=False)
        return merged

    def upsert_observations(self, records: Iterable[HkmaObservation]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.OBSERVATIONS_COLS)
        if incoming.empty:
            return self.load_observations()
        existing = self.load_observations()
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        merged["value"] = pd.to_numeric(merged["value"], errors="coerce")
        # Rank by publisher before deduping so an official reading always beats
        # an aggregator mirror for the same (series_id, date), regardless of
        # which source happened to run last.
        merged["source_tier"] = merged["source_tier"].fillna(AGGREGATOR)
        merged["_rank"] = merged["source_tier"].map(SOURCE_TIER_RANK).fillna(len(SOURCE_TIER_RANK))
        # Worst tier first, then keep="last" so the best tier wins -- and a
        # stable sort leaves arrival order intact within a tier, so a later
        # revision from the same publisher still supersedes the earlier one.
        merged = merged.sort_values(by=["series_id", "date", "_rank"], ascending=[True, True, False], kind="stable")
        merged = merged.drop_duplicates(subset=["series_id", "date"], keep="last").drop(columns=["_rank"])
        merged = merged.sort_values(by=["series_id", "date"]).reset_index(drop=True)
        merged.to_parquet(self.normalized_root / "hkma_observations.parquet", index=False)
        return merged
