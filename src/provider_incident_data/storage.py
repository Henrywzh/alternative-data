from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from provider_incident_data.models import Snapshot


DATASET_COLUMNS: dict[str, list[str]] = {
    "provider_incidents": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", "provider_id", "provider_name",
        "source_system", "source_incident_id", "incident_url", "title", "incident_type", "raw_status",
        "normalized_status", "raw_severity", "severity_level", "started_at", "published_at", "resolved_at",
        "duration_minutes", "is_active", "affected_components_json", "affected_regions_json", "latest_message",
        "source_confidence", "rule_version",
    ],
    "provider_incident_updates": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", "provider_id", "provider_name",
        "source_system", "source_incident_id", "source_update_id", "update_at", "raw_status", "message",
    ],
    "provider_incident_components": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", "provider_id", "provider_name",
        "source_system", "source_incident_id", "component_id", "component_name",
    ],
    "provider_incident_source_health": [
        "dataset_id", "source_url", "source_run_id", "scraped_at", "provider_id", "provider_name",
        "source_system", "status", "status_code", "response_ms", "content_bytes", "content_hash", "etag",
        "last_modified", "incident_rows", "last_good_incident_rows", "detail",
    ],
}

NATURAL_KEYS = {
    "provider_incidents": ["provider_id", "source_incident_id"],
    "provider_incident_updates": ["provider_id", "source_incident_id", "source_update_id"],
    "provider_incident_components": ["provider_id", "source_incident_id", "component_id"],
    "provider_incident_source_health": ["provider_id"],
}

SORT_KEYS = {
    "provider_incidents": ["started_at", "provider_id", "source_incident_id"],
    "provider_incident_updates": ["update_at", "provider_id", "source_incident_id", "source_update_id"],
    "provider_incident_components": ["provider_id", "source_incident_id", "component_name"],
    "provider_incident_source_health": ["provider_id"],
}

META_COLUMNS = {
    "dataset_id",
    "source_url",
    "source_run_id",
    "scraped_at",
    # Transport metadata can change without any incident data changing. Keep it
    # for debugging, but do not let it create two-hourly Parquet churn.
    "response_ms",
    "content_bytes",
    "etag",
    "last_modified",
}


class IncidentStorage:
    def __init__(self, base_dir: Path) -> None:
        self.raw_root = base_dir / "data" / "raw" / "provider_incidents"
        self.normalized_root = base_dir / "data" / "normalized" / "provider_incidents"
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
        return frame[columns]

    @staticmethod
    def _signature(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
        if frame.empty:
            return pd.Series([], dtype="string")
        return frame[columns].astype("string").fillna("").agg("\x1f".join, axis=1)

    def upsert(self, dataset_id: str, rows: list[dict[str, Any]] | pd.DataFrame) -> pd.DataFrame:
        columns = DATASET_COLUMNS[dataset_id]
        incoming = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
        if incoming.empty:
            return self.load(dataset_id)
        incoming = incoming.reindex(columns=columns).drop_duplicates(NATURAL_KEYS[dataset_id], keep="last")
        existing = self.load(dataset_id).drop_duplicates(NATURAL_KEYS[dataset_id], keep="last")
        if existing.empty:
            merged = incoming
        else:
            keys = NATURAL_KEYS[dataset_id]
            substantive = [column for column in columns if column not in META_COLUMNS and column not in keys]
            old = existing.set_index(keys)
            new = incoming.set_index(keys)
            common = old.index.intersection(new.index)
            unchanged = common[
                self._signature(old.loc[common], substantive).to_numpy()
                == self._signature(new.loc[common], substantive).to_numpy()
            ]
            old_only = old.index.difference(new.index)
            changed = new.index.difference(unchanged)
            parts = []
            keep_old = unchanged.union(old_only)
            if len(keep_old):
                parts.append(old.loc[keep_old])
            if len(changed):
                parts.append(new.loc[changed])
            merged = pd.concat(parts).reset_index()[columns]
        merged = merged.sort_values(SORT_KEYS[dataset_id], na_position="last").reset_index(drop=True)
        path = self.normalized_root / f"{dataset_id}.parquet"
        temporary = path.with_suffix(".tmp.parquet")
        merged.to_parquet(temporary, index=False)
        os.replace(temporary, path)
        return merged

    def write_raw_run(self, *, run_id: str, snapshots: list[Snapshot], manifest: dict[str, Any]) -> Path:
        run_dir = self.raw_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in snapshots:
            suffix = "json" if "json" in snapshot.content_type.lower() or snapshot.parser in {"statuspage", "google"} else "xml"
            (run_dir / f"{snapshot.provider_id}.{suffix}").write_text(snapshot.body, encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return run_dir
