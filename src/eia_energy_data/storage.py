from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from common.partitioned_parquet import PartitionSpec, PartitionedParquetStore

from .models import EiaGridHourlyObservation


class EiaEnergyStorage:
    GRID_COLS = ["timestamp_utc", "respondent", "fuel_type", "generation_mwh", "fetched_at"]
    DATASET_ID = "eia_grid_hourly"

    # 2.5M hourly rows across 5 balancing authorities. As a single table that
    # is an 11.5 MB parquet rewritten in full on every daily refresh, and
    # parquet is compressed binary git cannot delta -- roughly 4 GB of history
    # a year. One file per observation day costs 25 MB once and 5 KB per new
    # day. The partition column is hourly, so the store truncates it to the
    # day; partitioning on the raw value would write ~67,000 files.
    PARTITION_COLUMN = "timestamp_utc"

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "eia_energy"
        self.normalized_root = base_dir / "data" / "normalized" / "eia_energy"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def write_raw_payload(self, run_id: str, name: str, data: Any) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def partition_store(self) -> PartitionedParquetStore:
        return PartitionedParquetStore(
            self.normalized_root / self.DATASET_ID,
            PartitionSpec(
                column=self.PARTITION_COLUMN,
                columns=self.GRID_COLS,
                numeric_columns=frozenset({"generation_mwh"}),
                granularity="day",
            ),
        )

    def load_grid_hourly(self) -> pd.DataFrame:
        parquet_path = self.normalized_root / f"{self.DATASET_ID}.parquet"
        csv_path = self.normalized_root / f"{self.DATASET_ID}.csv"
        partitioned = self.partition_store().load()
        if partitioned is not None:
            # A leftover single file would silently double every row, so the
            # partition directory wins once it exists. A pre-migration
            # checkout has no directory and falls through.
            return partitioned.reindex(columns=self.GRID_COLS)
        if parquet_path.exists():
            return pd.read_parquet(parquet_path).reindex(columns=self.GRID_COLS)
        if csv_path.exists():
            return pd.read_csv(csv_path).reindex(columns=self.GRID_COLS)
        return pd.DataFrame(columns=self.GRID_COLS)

    def upsert_grid_hourly(self, records: Iterable[EiaGridHourlyObservation]) -> pd.DataFrame:
        incoming = pd.DataFrame([r.to_dict() for r in records], columns=self.GRID_COLS)
        if incoming.empty:
            return self.load_grid_hourly()
        existing = self.load_grid_hourly()
        merged = pd.concat([existing, incoming], ignore_index=True) if not existing.empty else incoming.copy()
        merged["generation_mwh"] = pd.to_numeric(merged["generation_mwh"], errors="coerce")
        merged = merged.drop_duplicates(subset=["timestamp_utc", "respondent", "fuel_type"], keep="last")
        merged = merged.sort_values(by=["respondent", "timestamp_utc", "fuel_type"]).reset_index(drop=True)
        self.partition_store().write(merged)
        # The pre-partition files are now stale duplicates of the whole table.
        # The CSV twin is dropped outright: it was 151 MB against a 12 MB
        # parquet and `*.csv` is gitignored, so it was never published.
        (self.normalized_root / f"{self.DATASET_ID}.parquet").unlink(missing_ok=True)
        (self.normalized_root / f"{self.DATASET_ID}.csv").unlink(missing_ok=True)
        return merged
