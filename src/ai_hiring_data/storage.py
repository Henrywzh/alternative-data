from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from ai_hiring_data.models import Snapshot


DATASET_COLUMNS: dict[str, list[str]] = {
    "indeed_ai_posting_share_daily": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", "date", "jobcountry",
        "ai_share_pct", "source_frequency", "source_refresh_cadence", "license",
    ],
    "hiring_companies": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", "company_id", "company_name",
        "company_segment", "source_id", "source_platform", "board_token", "careers_url",
        "coverage_start_date", "continuous_coverage_start_date", "cohort_version", "is_active",
    ],
    "hiring_jobs": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", "source_id", "company_id",
        "company_name", "company_segment", "source_platform", "board_token", "source_job_id",
        "source_requisition_id", "title", "department", "team", "location_raw", "country_code",
        "workplace_type", "employment_type", "published_at", "source_updated_at", "job_url",
        "apply_url", "role_family", "seniority", "is_ai_role", "ai_role_confidence",
        "classifier_version", "content_hash", "first_seen_at", "last_changed_at", "missing_since_at",
        "closed_at", "status", "consecutive_missing_runs",
    ],
    "hiring_job_events": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", "company_id", "company_name",
        "source_job_id", "event_at", "event_date", "event_type", "previous_status", "new_status",
        "changed_fields_json", "title", "role_family",
    ],
    "hiring_demand_daily": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", "snapshot_date", "company_id",
        "company_name", "company_segment", "cohort_version", "role_family", "active_postings",
        "active_requisitions", "ai_role_postings", "new_postings_28d", "closed_postings_28d",
        "net_posting_flow_28d", "source_status", "coverage_start_date", "same_store_28d",
        "continuous_coverage_start_date",
    ],
    "hiring_source_health": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", "source_id", "source_kind",
        "company_id", "company_name", "status", "status_code", "response_ms", "content_bytes",
        "content_hash", "etag", "last_modified", "row_count", "last_good_row_count", "detail",
    ],
}

NATURAL_KEYS = {
    "indeed_ai_posting_share_daily": ["date", "jobcountry"],
    "hiring_companies": ["company_id"],
    "hiring_jobs": ["company_id", "source_job_id"],
    "hiring_job_events": ["company_id", "source_job_id", "event_at", "event_type"],
    "hiring_demand_daily": ["snapshot_date", "company_id", "role_family"],
    "hiring_source_health": ["source_id"],
}

SORT_KEYS = {
    "indeed_ai_posting_share_daily": ["date", "jobcountry"],
    "hiring_companies": ["company_name"],
    "hiring_jobs": ["status", "company_name", "role_family", "title", "source_job_id"],
    "hiring_job_events": ["event_at", "company_name", "source_job_id"],
    "hiring_demand_daily": ["snapshot_date", "company_name", "role_family"],
    "hiring_source_health": ["source_id"],
}

MODES = {
    "indeed_ai_posting_share_daily": "replace",
    "hiring_companies": "replace",
    "hiring_jobs": "replace",
    "hiring_job_events": "history",
    "hiring_demand_daily": "partition",
    "hiring_source_health": "replace",
}

PARTITIONS = {"hiring_demand_daily": ["snapshot_date"]}
META_COLUMNS = {
    "dataset_id", "source_url", "source_run_id", "scraped_at",
    "status_code", "response_ms", "content_bytes", "etag", "last_modified",
}
NUMERIC_COLUMNS = {
    "ai_share_pct", "consecutive_missing_runs", "active_postings", "active_requisitions",
    "ai_role_postings", "new_postings_28d", "closed_postings_28d", "net_posting_flow_28d",
    "status_code", "response_ms", "content_bytes", "row_count", "last_good_row_count",
}
BOOLEAN_COLUMNS = {"is_active", "is_ai_role", "same_store_28d"}


class HiringStorage:
    def __init__(self, base_dir: Path) -> None:
        self.raw_root = base_dir / "data" / "raw" / "ai_hiring"
        self.normalized_root = base_dir / "data" / "normalized" / "ai_hiring"
        self.raw_root.mkdir(parents=True, exist_ok=True)
        self.normalized_root.mkdir(parents=True, exist_ok=True)

    def load(self, dataset_id: str) -> pd.DataFrame:
        columns = DATASET_COLUMNS[dataset_id]
        path = self.normalized_root / f"{dataset_id}.parquet"
        if not path.exists():
            return pd.DataFrame(columns=columns)
        frame = pd.read_parquet(path)
        for column in columns:
            if column not in frame.columns:
                frame[column] = pd.NA
        return self._coerce(frame[columns])

    @staticmethod
    def _signature(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
        if frame.empty:
            return pd.Series([], dtype="string")
        return frame[columns].astype("string").fillna("").agg("\x1f".join, axis=1)

    @staticmethod
    def _partition_index(frame: pd.DataFrame, columns: list[str]) -> pd.MultiIndex:
        return pd.MultiIndex.from_frame(frame[columns].astype("string").fillna("__NULL_PARTITION__"))

    def _merge(self, dataset_id: str, existing: pd.DataFrame, incoming: pd.DataFrame) -> pd.DataFrame:
        keys = NATURAL_KEYS[dataset_id]
        columns = DATASET_COLUMNS[dataset_id]
        mode = MODES[dataset_id]
        if existing.empty:
            return incoming
        old = existing.drop_duplicates(keys, keep="last").set_index(keys)
        new = incoming.drop_duplicates(keys, keep="last").set_index(keys)
        substantive = [column for column in columns if column not in META_COLUMNS and column not in keys]
        common = old.index.intersection(new.index)
        unchanged = common[
            self._signature(old.loc[common], substantive).to_numpy()
            == self._signature(new.loc[common], substantive).to_numpy()
        ]
        changed = new.index.difference(unchanged)

        if mode == "replace":
            keep_old = unchanged
        elif mode == "history":
            keep_old = unchanged.union(old.index.difference(new.index))
        elif mode == "partition":
            partition_columns = PARTITIONS[dataset_id]
            old_frame = old.reset_index()
            new_frame = new.reset_index()
            affected = self._partition_index(new_frame, partition_columns)
            old_partitions = self._partition_index(old_frame, partition_columns)
            outside = old_frame.loc[~old_partitions.isin(affected)].set_index(keys).index
            keep_old = unchanged.union(outside)
        else:
            raise ValueError(f"Unknown storage mode: {mode}")

        parts = []
        if len(keep_old):
            parts.append(old.loc[keep_old])
        if len(changed):
            parts.append(new.loc[changed])
        if not parts:
            return pd.DataFrame(columns=columns)
        return pd.concat(parts).reset_index()[columns]

    def _coerce(self, frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        for column in frame.columns:
            if column in NUMERIC_COLUMNS:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
            elif column in BOOLEAN_COLUMNS:
                frame[column] = frame[column].astype("boolean")
            else:
                frame[column] = frame[column].astype("string")
        return frame

    def upsert(self, dataset_id: str, rows: list[dict[str, Any]] | pd.DataFrame) -> pd.DataFrame:
        columns = DATASET_COLUMNS[dataset_id]
        incoming = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
        if incoming.empty:
            return self.load(dataset_id)
        incoming = self._coerce(incoming.reindex(columns=columns))
        existing = self.load(dataset_id)
        merged = self._merge(dataset_id, existing, incoming)
        merged = self._coerce(merged).sort_values(SORT_KEYS[dataset_id], na_position="last").reset_index(drop=True)
        path = self.normalized_root / f"{dataset_id}.parquet"
        temporary = path.with_suffix(".tmp.parquet")
        merged.to_parquet(temporary, index=False)
        os.replace(temporary, path)
        return merged

    def write_raw_run(self, *, run_id: str, snapshots: list[Snapshot], manifest: dict[str, Any]) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in snapshots:
            if snapshot.body is None:
                continue
            suffix = "csv" if snapshot.source_kind == "macro_csv" else "json"
            (run_dir / f"{snapshot.source_id}.{suffix}").write_text(snapshot.body, encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return run_dir
