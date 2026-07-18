from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pandas as pd

from provider_incident_data.extract import DATASET_IDS, extract_snapshot
from provider_incident_data.models import FetchFailure
from provider_incident_data.quality import validate_incidents, validate_source_health
from provider_incident_data.source import ProviderIncidentSource
from provider_incident_data.storage import IncidentStorage


class ProviderIncidentPipeline:
    def __init__(self, base_dir: Path, *, source: ProviderIncidentSource | None = None) -> None:
        self.source = source or ProviderIncidentSource()
        self.storage = IncidentStorage(base_dir)

    @staticmethod
    def _context() -> tuple[str, str]:
        now = datetime.now(timezone.utc)
        return (
            now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
            now.isoformat().replace("+00:00", "Z"),
        )

    def run_update(self) -> dict[str, int]:
        run_id, scraped_at = self._context()
        snapshots, fetch_failures = self.source.fetch_all()
        rows: dict[str, list[dict[str, object]]] = {dataset_id: [] for dataset_id in DATASET_IDS}
        parse_failures: list[FetchFailure] = []
        source_health: list[dict[str, object]] = []
        previous_health = self.storage.load("provider_incident_source_health")
        previous_counts: dict[str, object] = {}
        if not previous_health.empty:
            for _, health_row in previous_health.iterrows():
                baseline = health_row.get("last_good_incident_rows")
                if pd.isna(baseline):
                    baseline = health_row.get("incident_rows")
                previous_counts[str(health_row["provider_id"])] = baseline

        for snapshot in snapshots:
            try:
                extracted = extract_snapshot(snapshot, run_id=run_id, scraped_at=scraped_at)
            except (ValueError, TypeError, KeyError) as exc:
                parse_failures.append(
                    FetchFailure(
                        provider_id=snapshot.provider_id,
                        provider_name=snapshot.provider_name,
                        source_kind=snapshot.source_kind,
                        source_url=snapshot.source_url,
                        error=f"{type(exc).__name__}: {exc}",
                        status_code=snapshot.status_code,
                    )
                )
                continue
            incident_count = len(extracted.get("provider_incidents", []))
            previous_count = pd.to_numeric(previous_counts.get(snapshot.provider_id), errors="coerce")
            count_collapsed = (
                not pd.isna(previous_count)
                and (
                    (previous_count >= 5 and incident_count == 0)
                    or (previous_count >= 10 and incident_count < previous_count * 0.2)
                )
            )
            if count_collapsed:
                parse_failures.append(
                    FetchFailure(
                        provider_id=snapshot.provider_id,
                        provider_name=snapshot.provider_name,
                        source_kind=snapshot.source_kind,
                        source_url=snapshot.source_url,
                        error=f"CountCollapse: extracted {incident_count} incidents after {int(previous_count)} previously",
                        status_code=snapshot.status_code,
                    )
                )
                continue
            for dataset_id in DATASET_IDS:
                rows[dataset_id].extend(extracted.get(dataset_id, []))
            canonical_rows = []
            for dataset_id in DATASET_IDS:
                for row in extracted.get(dataset_id, []):
                    canonical_rows.append(
                        {
                            key: value
                            for key, value in row.items()
                            if key not in {"dataset_id", "source_url", "source_run_id", "scraped_at"}
                        }
                    )
            canonical_rows.sort(key=lambda row: json.dumps(row, sort_keys=True, default=str))
            canonical_payload = json.dumps(canonical_rows, sort_keys=True, default=str, ensure_ascii=True)
            source_health.append(
                {
                    "dataset_id": "provider_incident_source_health",
                    "source_url": snapshot.source_url,
                    "source_run_id": run_id,
                    "scraped_at": scraped_at,
                    "provider_id": snapshot.provider_id,
                    "provider_name": snapshot.provider_name,
                    "source_system": snapshot.source_kind,
                    "status": "ok",
                    "status_code": snapshot.status_code,
                    "response_ms": snapshot.response_ms,
                    "content_bytes": len(snapshot.body.encode("utf-8")),
                    "content_hash": hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest(),
                    "etag": snapshot.etag,
                    "last_modified": snapshot.last_modified,
                    "incident_rows": incident_count,
                    "last_good_incident_rows": incident_count,
                    "detail": "Provider-reported public status source",
                }
            )

        all_failures = [*fetch_failures, *parse_failures]
        for failure in all_failures:
            source_health.append(
                {
                    "dataset_id": "provider_incident_source_health",
                    "source_url": failure.source_url,
                    "source_run_id": run_id,
                    "scraped_at": scraped_at,
                    "provider_id": failure.provider_id,
                    "provider_name": failure.provider_name,
                    "source_system": failure.source_kind,
                    "status": "warning",
                    "status_code": failure.status_code,
                    "response_ms": None,
                    "content_bytes": None,
                    "content_hash": None,
                    "etag": None,
                    "last_modified": None,
                    "incident_rows": 0,
                    "last_good_incident_rows": previous_counts.get(failure.provider_id),
                    "detail": failure.error[:1000],
                }
            )

        expected = {spec.provider_id for spec in self.source.specs}
        successful_sources = len(snapshots) - len(parse_failures)
        minimum_successful = max(1, (len(expected) + 1) // 2)
        if successful_sources < minimum_successful:
            manifest = {
                "run_id": run_id,
                "scraped_at": scraped_at,
                "status": "failed",
                "source_count": len(expected),
                "successful_sources": successful_sources,
                "failed_sources": len(all_failures),
                "datasets": {},
                "failures": [failure.__dict__ for failure in all_failures],
                "error": f"Only {successful_sources}/{len(expected)} provider sources succeeded",
            }
            self.storage.write_raw_run(run_id=run_id, snapshots=snapshots, manifest=manifest)
            raise RuntimeError(manifest["error"])
        health_frame = pd.DataFrame(source_health)
        validate_source_health(health_frame, expected_providers=expected)
        incidents_frame = pd.DataFrame(rows["provider_incidents"])
        validate_incidents(incidents_frame)

        written: dict[str, int] = {}
        for dataset_id in DATASET_IDS:
            if rows[dataset_id]:
                written[dataset_id] = len(self.storage.upsert(dataset_id, rows[dataset_id]))
            else:
                written[dataset_id] = len(self.storage.load(dataset_id))
        written["provider_incident_source_health"] = len(
            self.storage.upsert("provider_incident_source_health", health_frame)
        )

        manifest = {
            "run_id": run_id,
            "scraped_at": scraped_at,
            "status": "success" if not all_failures else "warning",
            "source_count": len(expected),
            "successful_sources": successful_sources,
            "failed_sources": len(all_failures),
            "datasets": written,
            "failures": [failure.__dict__ for failure in all_failures],
        }
        self.storage.write_raw_run(run_id=run_id, snapshots=snapshots, manifest=manifest)
        return written
