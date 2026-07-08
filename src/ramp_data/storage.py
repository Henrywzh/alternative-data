from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd

from ramp_data.models import DatasetRecord, GenericRecord, Snapshot
from ramp_data.schemas import AI_INDEX_DATASETS, CORE_COLUMNS, JOBS_IMPACT, JOBS_IMPACT_DATASET

NATURAL_KEYS: dict[str, list[str]] = {
    "ramp_vendor_adoption_monthly": ["vendor_slug", "spend_month"],
    "ramp_category_vendors": ["category_slug", "vendor_slug"],
}

SORT_KEYS: dict[str, list[str]] = {
    "ramp_vendor_adoption_monthly": ["vendor_slug", "spend_month"],
    "ramp_category_vendors": ["category_slug", "adoption_rate", "vendor_slug"],
}

# adoption_rate descends in the category snapshot so the leaders sort first.
SORT_DESCENDING: dict[str, set[str]] = {
    "ramp_category_vendors": {"adoption_rate"},
}

DATASET_COLUMNS: dict[str, list[str]] = {
    "ramp_vendor_adoption_monthly": [
        "dataset_id", "source_url", "source_run_id", "scraped_at",
        "vendor_slug", "vendor_name", "vendor_domain", "spend_month",
        "adoption_rate", "adoption_rate_yoy", "adoption_rank", "adoption_rank_mom",
        "adoption_rate_ent", "adoption_rate_mm", "adoption_rate_smb",
        "adoption_rate_growth_delta_mom", "adoption_rate_growth_rank_mom",
        "competitor_switch_rate", "new_adopter_share",
        "dominant_fte_segment", "dominant_fte_segment_pct",
    ],
    "ramp_category_vendors": [
        "dataset_id", "source_url", "source_run_id", "scraped_at",
        "category_slug", "category_name",
        "vendor_slug", "vendor_name", "vendor_domain",
        "adoption_rate", "adoption_rate_yoy",
    ],
}

NUMERIC_COLUMNS = [
    "adoption_rate", "adoption_rate_yoy", "adoption_rank", "adoption_rank_mom",
    "adoption_rate_ent", "adoption_rate_mm", "adoption_rate_smb",
    "adoption_rate_growth_delta_mom", "adoption_rate_growth_rank_mom",
    "competitor_switch_rate", "new_adopter_share", "dominant_fte_segment_pct",
]

# Provenance columns that change every run; excluded from change detection so an
# unchanged payload keeps its original provenance (no parquet churn, no empty commit).
META_COLUMNS = ["dataset_id", "source_url", "source_run_id", "scraped_at"]

# Current-snapshot datasets: each crawl is the complete current membership, so a
# (category, vendor) pair absent from the latest crawl is pruned (a vendor dropped
# from a category should not linger). The monthly series accumulates instead.
REPLACE_DATASETS = {"ramp_category_vendors"}


# Register the config-driven datasets (AI Index + Jobs Impact) from schemas.py so
# there is a single source of truth for their columns/keys. AI Index datasets are
# history/append (keyed on date_month); Jobs Impact is a static REPLACE snapshot.
for _dsid, _cfg in AI_INDEX_DATASETS.items():
    DATASET_COLUMNS[_dsid] = [*CORE_COLUMNS, *_cfg["fields"]]
    NATURAL_KEYS[_dsid] = _cfg["natural_keys"]
    SORT_KEYS[_dsid] = _cfg["sort_keys"]
    NUMERIC_COLUMNS.extend(c for c in _cfg["numeric"] if c not in NUMERIC_COLUMNS)

DATASET_COLUMNS[JOBS_IMPACT_DATASET] = [*CORE_COLUMNS, *JOBS_IMPACT["fields"]]
NATURAL_KEYS[JOBS_IMPACT_DATASET] = JOBS_IMPACT["natural_keys"]
SORT_KEYS[JOBS_IMPACT_DATASET] = JOBS_IMPACT["sort_keys"]
NUMERIC_COLUMNS.extend(c for c in JOBS_IMPACT["numeric"] if c not in NUMERIC_COLUMNS)
REPLACE_DATASETS.add(JOBS_IMPACT_DATASET)


class StorageManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.raw_root = base_dir / "data" / "raw" / "ramp"
        self.normalized_root = base_dir / "data" / "normalized" / "ramp"
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
        incoming = pd.DataFrame([record.to_dict() for record in records])
        incoming = incoming.reindex(columns=cols) if not incoming.empty else pd.DataFrame(columns=cols)
        if incoming.empty:
            raise ValueError(f"Dataset {dataset_id} has no incoming records")

        incoming = self._coerce_types(incoming).drop_duplicates(subset=keys, keep="last")
        existing = self._coerce_types(self.load_dataset(dataset_id))

        merged = self._merge_preserving_meta(dataset_id, existing, incoming)

        descending = SORT_DESCENDING.get(dataset_id, set())
        ascending_spec = [key not in descending for key in SORT_KEYS[dataset_id]]
        merged = merged.sort_values(
            by=SORT_KEYS[dataset_id],
            ascending=ascending_spec,
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
