from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from vercel_ai_data.models import DatasetRecord, Snapshot

NATURAL_KEYS: dict[str, list[str]] = {
    "vercel_model_leaderboard": ["date", "name", "metric", "modality"],
    "vercel_lab_leaderboard": ["date", "name", "metric", "modality"],
    "vercel_models": ["model_id"],
}

SORT_KEYS: dict[str, list[str]] = {
    "vercel_model_leaderboard": ["date", "metric", "modality", "rank", "name"],
    "vercel_lab_leaderboard": ["date", "metric", "modality", "rank", "name"],
    "vercel_models": ["owned_by", "model_id"],
}

DATASET_COLUMNS: dict[str, list[str]] = {
    "vercel_model_leaderboard": [
        "dataset_id", "source_url", "source_run_id", "scraped_at",
        "date", "group", "name", "metric", "modality", "share_percent", "rank"
    ],
    "vercel_lab_leaderboard": [
        "dataset_id", "source_url", "source_run_id", "scraped_at",
        "date", "group", "name", "metric", "modality", "share_percent", "rank"
    ],
    "vercel_models": [
        "dataset_id", "source_url", "source_run_id", "scraped_at",
        "model_id", "name", "owned_by", "description", "context_window",
        "max_tokens", "type", "pricing_input", "pricing_output",
        "pricing_cache_read", "pricing_cache_write", "tags", "raw_pricing_json"
    ],
}

NUMERIC_COLUMNS = [
    "share_percent", "rank", "context_window", "max_tokens",
    "pricing_input", "pricing_output", "pricing_cache_read", "pricing_cache_write"
]

# Provenance columns that change every run. They are excluded from change
# detection so that a row whose *substantive* payload is unchanged keeps its
# original provenance (and therefore produces no parquet diff / no daily commit).
META_COLUMNS = ["dataset_id", "source_url", "source_run_id", "scraped_at"]

# Current-snapshot datasets: each fetch is the complete current set, so rows
# whose natural key is absent from the latest fetch are pruned (delisted models
# should not linger forever). History datasets (leaderboards) accumulate instead.
REPLACE_DATASETS = {"vercel_models"}

# The leaderboard export is historical, but each successful modality fetch is a
# complete snapshot for every date/metric in that slice.  Refresh those
# partitions on every fetch so models that disappear from an upstream
# historical row do not linger and inflate the displayed share above 100%.
# Partitions not present in an incoming fetch are retained, which keeps a
# temporary route failure from deleting previously stored history.
REPLACE_PARTITION_KEYS: dict[str, list[str]] = {
    "vercel_model_leaderboard": ["date", "metric", "modality"],
    "vercel_lab_leaderboard": ["date", "metric", "modality"],
}


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "vercel_ai"
        self.normalized_root = base_dir / "data" / "normalized" / "vercel_ai"
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
            safe_name = "".join(c for c in snapshot.name if c.isalnum() or c in "._-")
            (run_dir / f"{safe_name}.json").write_text(snapshot.body, encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return run_dir

    def load_dataset(self, dataset_id: str) -> pd.DataFrame:
        csv_path = self.normalized_root / f"{dataset_id}.csv"
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"
        cols = DATASET_COLUMNS[dataset_id]
        if parquet_path.exists():
            dataframe = pd.read_parquet(parquet_path)
        elif csv_path.exists():
            dataframe = pd.read_csv(csv_path)
        else:
            return pd.DataFrame(columns=cols)
        for column in cols:
            if column not in dataframe.columns:
                dataframe[column] = pd.NA
        return dataframe[cols]

    def upsert_dataset(self, dataset_id: str, records: Iterable[DatasetRecord]) -> pd.DataFrame:
        cols = DATASET_COLUMNS[dataset_id]
        keys = NATURAL_KEYS[dataset_id]
        incoming = pd.DataFrame([record.to_dict() for record in records], columns=cols)
        if incoming.empty:
            raise ValueError(f"Dataset {dataset_id} has no incoming records")

        incoming = self._coerce_types(incoming).drop_duplicates(subset=keys, keep="last")
        existing = self._coerce_types(self.load_dataset(dataset_id))

        merged = self._merge_preserving_meta(dataset_id, existing, incoming)

        merged = merged.sort_values(
            by=SORT_KEYS[dataset_id],
            ascending=True,
            na_position="last",
        ).reset_index(drop=True)

        csv_path = self.normalized_root / f"{dataset_id}.csv"
        parquet_path = self.normalized_root / f"{dataset_id}.parquet"
        merged.to_parquet(parquet_path, index=False)
        merged.to_csv(csv_path, index=False)
        return merged

    def _merge_preserving_meta(
        self,
        dataset_id: str,
        existing: pd.DataFrame,
        incoming: pd.DataFrame,
    ) -> pd.DataFrame:
        """Merge incoming rows into existing, keeping the existing provenance for
        rows whose substantive payload is unchanged.

        - History datasets: union of existing and incoming keys.
        - REPLACE_DATASETS: only keys present in the latest fetch survive
          (delisted rows are pruned).

        Preserving provenance for unchanged rows means an unchanged daily fetch
        produces an identical parquet (no churn, no empty commits).
        """
        cols = DATASET_COLUMNS[dataset_id]
        keys = NATURAL_KEYS[dataset_id]
        if existing.empty:
            return incoming.reset_index(drop=True)

        existing = existing.drop_duplicates(subset=keys, keep="last")
        substantive = [c for c in cols if c not in META_COLUMNS and c not in keys]

        ex = existing.set_index(keys)
        inc = incoming.set_index(keys)

        common = ex.index.intersection(inc.index)
        unchanged = common[
            self._signature(ex.loc[common], substantive).to_numpy()
            == self._signature(inc.loc[common], substantive).to_numpy()
        ]

        if dataset_id in REPLACE_DATASETS:
            keep_existing = unchanged
        else:
            existing_only = ex.index.difference(inc.index)
            if dataset_id in REPLACE_PARTITION_KEYS and len(existing_only):
                # Incoming leaderboard rows represent complete historical
                # partitions.  Keep rows outside those partitions, but prune
                # stale natural keys inside them.  Rows in ``unchanged`` still
                # retain their original provenance below.
                partition_cols = REPLACE_PARTITION_KEYS[dataset_id]
                incoming_partitions = set(
                    incoming[partition_cols]
                    .astype("string")
                    .fillna("")
                    .agg("\x1f".join, axis=1)
                )
                existing_only_frame = existing_only.to_frame(index=False)
                existing_only_partitions = existing_only_frame[partition_cols].astype("string").fillna("").agg(
                    "\x1f".join,
                    axis=1,
                )
                existing_only = existing_only[~existing_only_partitions.isin(incoming_partitions)]
            keep_existing = unchanged.union(existing_only)
        take_incoming = inc.index.difference(unchanged)

        parts = []
        if len(keep_existing):
            parts.append(ex.loc[keep_existing])
        if len(take_incoming):
            parts.append(inc.loc[take_incoming])
        merged = pd.concat(parts).reset_index()
        return merged[cols]

    @staticmethod
    def _signature(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
        """Order-preserving canonical string per row over the given columns,
        used to detect whether a row's substantive payload changed."""
        if frame.empty:
            return pd.Series([], dtype="string")
        canonical = frame[columns].astype("string").fillna("")
        return canonical.agg("\x1f".join, axis=1)

    @staticmethod
    def _coerce_types(dataframe: pd.DataFrame) -> pd.DataFrame:
        for column in dataframe.columns:
            if column in NUMERIC_COLUMNS:
                dataframe[column] = pd.to_numeric(dataframe[column], errors="coerce")
            else:
                dataframe[column] = dataframe[column].astype("string")
        return dataframe
