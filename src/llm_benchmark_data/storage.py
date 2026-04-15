from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from llm_benchmark_data.models import BenchmarkPoint, Snapshot


BENCHMARK_COLUMNS = [
    "model_id",
    "name",
    "organization",
    "release_date",
    "context_window",
    "gpqa",
    "swe_bench",
    "scraped_at",
    "source_url",
    "dataset_id",
    "source_run_id",
]

NUMERIC_COLUMNS = ["context_window", "gpqa", "swe_bench"]
TEXT_COLUMNS = ["model_id", "name", "organization", "release_date", "scraped_at", "source_url", "dataset_id", "source_run_id"]


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "llm_benchmarks"
        self.normalized_root = base_dir / "data" / "normalized" / "llm_benchmarks"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_run(
        self,
        run_id: str,
        snapshots: Iterable[Snapshot],
        manifest: dict[str, Any],
    ) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in snapshots:
            (run_dir / f"{snapshot.name}.json").write_text(snapshot.body, encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return run_dir

    def load_dataset(self) -> pd.DataFrame:
        csv_path = self.normalized_root / "llm_benchmarks.csv"
        if not csv_path.exists():
            return pd.DataFrame(columns=BENCHMARK_COLUMNS)
        dataframe = pd.read_csv(csv_path)
        for column in BENCHMARK_COLUMNS:
            if column not in dataframe.columns:
                dataframe[column] = pd.NA
        return dataframe[BENCHMARK_COLUMNS]

    def upsert_dataset(self, records: Iterable[BenchmarkPoint]) -> pd.DataFrame:
        incoming = pd.DataFrame([record.to_dict() for record in records], columns=BENCHMARK_COLUMNS)
        if incoming.empty:
            return self.load_dataset()
            
        existing = self.load_dataset()
        if existing.empty:
            merged = incoming.copy()
        else:
            merged = pd.concat([existing, incoming], ignore_index=True)
        
        merged = self._coerce_types(merged)
        # Use model_id and release_date as natural keys for de-duplication
        merged = merged.drop_duplicates(subset=["model_id"], keep="last")
        merged = merged.sort_values(by=["release_date", "model_id"], na_position="last").reset_index(drop=True)

        csv_path = self.normalized_root / "llm_benchmarks.csv"
        parquet_path = self.normalized_root / "llm_benchmarks.parquet"
        merged.to_csv(csv_path, index=False)
        merged.to_parquet(parquet_path, index=False)
        return merged

    @staticmethod
    def _coerce_types(dataframe: pd.DataFrame) -> pd.DataFrame:
        for column in NUMERIC_COLUMNS:
            dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")
        for column in TEXT_COLUMNS:
            dataframe[column] = dataframe[column].astype("string")
        return dataframe
