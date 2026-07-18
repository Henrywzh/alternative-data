from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from ai_hiring_data.config import BOARD_SPECS, COHORT_VERSION, INDEED_SOURCE, ROLE_FAMILIES
from ai_hiring_data.extract import extract_board, extract_indeed
from ai_hiring_data.models import FetchFailure, Snapshot, SourceSpec
from ai_hiring_data.quality import count_collapsed, validate_board, validate_indeed
from ai_hiring_data.source import AIHiringSource
from ai_hiring_data.storage import DATASET_COLUMNS, HiringStorage


class AIHiringPipeline:
    def __init__(
        self,
        base_dir: Path,
        *,
        source: AIHiringSource | None = None,
        production_quality: bool = True,
    ) -> None:
        self.source = source or AIHiringSource()
        self.storage = HiringStorage(base_dir)
        self.production_quality = production_quality

    @staticmethod
    def _context() -> tuple[str, str]:
        now = datetime.now(timezone.utc)
        return (
            now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8],
            now.isoformat().replace("+00:00", "Z"),
        )

    @staticmethod
    def _clean(value: object) -> object | None:
        return None if value is None or pd.isna(value) else value

    @classmethod
    def _text(cls, value: object, fallback: str = "") -> str:
        clean = cls._clean(value)
        return fallback if clean is None else str(clean)

    @staticmethod
    def _canonical_hash(rows: list[dict[str, Any]], fields: tuple[str, ...]) -> str:
        canonical = [{field: row.get(field) for field in fields} for row in rows]
        canonical.sort(key=lambda row: json.dumps(row, sort_keys=True, default=str))
        payload = json.dumps(canonical, sort_keys=True, default=str, ensure_ascii=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _validators(self, health: pd.DataFrame) -> dict[str, dict[str, str | None]]:
        validators: dict[str, dict[str, str | None]] = {}
        if health.empty:
            return validators
        for _, row in health.iterrows():
            validators[str(row["source_id"])] = {
                "etag": self._text(row.get("etag")) or None,
                "last_modified": self._text(row.get("last_modified")) or None,
            }
        return validators

    def _company_rows(
        self,
        *,
        run_id: str,
        scraped_at: str,
        snapshot_date: date,
        previous: pd.DataFrame,
        previous_health: pd.DataFrame,
        health_rows: list[dict[str, Any]],
        board_specs: tuple[SourceSpec, ...],
    ) -> list[dict[str, Any]]:
        previous_by_company = previous.set_index("company_id") if not previous.empty else pd.DataFrame()
        previous_health_by_source = (
            previous_health.set_index("source_id") if not previous_health.empty else pd.DataFrame()
        )
        current_health_by_source = {str(row["source_id"]): row for row in health_rows}
        rows = []
        for spec in board_specs:
            existing_start = None
            existing_continuous_start = None
            if not previous.empty and spec.company_id in previous_by_company.index:
                existing_start = self._clean(previous_by_company.loc[spec.company_id].get("coverage_start_date"))
                existing_continuous_start = self._clean(
                    previous_by_company.loc[spec.company_id].get("continuous_coverage_start_date")
                )
            current_status = str(current_health_by_source.get(spec.source_id, {}).get("status") or "warning")
            prior_status = None
            if not previous_health.empty and spec.source_id in previous_health_by_source.index:
                prior_status = self._text(previous_health_by_source.loc[spec.source_id].get("status"))
            if current_status == "ok":
                coverage_start = existing_start or snapshot_date.isoformat()
                continuous_start = (
                    existing_continuous_start or coverage_start
                    if prior_status == "ok"
                    else snapshot_date.isoformat()
                )
            else:
                coverage_start = existing_start
                continuous_start = None
            rows.append(
                {
                    "dataset_id": "hiring_companies",
                    "source_url": spec.source_url,
                    "source_run_id": run_id,
                    "scraped_at": scraped_at,
                    "company_id": spec.company_id,
                    "company_name": spec.company_name,
                    "company_segment": spec.company_segment,
                    "source_id": spec.source_id,
                    "source_platform": spec.source_platform,
                    "board_token": spec.board_token,
                    "careers_url": spec.careers_url,
                    "coverage_start_date": str(coverage_start) if coverage_start is not None else None,
                    "continuous_coverage_start_date": (
                        str(continuous_start) if continuous_start is not None else None
                    ),
                    "cohort_version": COHORT_VERSION,
                    "is_active": True,
                }
            )
        return rows

    def _event(
        self,
        *,
        run_id: str,
        scraped_at: str,
        source_url: str,
        row: dict[str, Any],
        event_date: date,
        event_type: str,
        previous_status: str | None,
        new_status: str,
        changed_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "dataset_id": "hiring_job_events",
            "source_url": source_url,
            "source_run_id": run_id,
            "scraped_at": scraped_at,
            "company_id": row["company_id"],
            "company_name": row["company_name"],
            "source_job_id": row["source_job_id"],
            "event_at": scraped_at,
            "event_date": event_date.isoformat(),
            "event_type": event_type,
            "previous_status": previous_status,
            "new_status": new_status,
            "changed_fields_json": json.dumps(changed_fields or []),
            "title": row["title"],
            "role_family": row["role_family"],
        }

    def _apply_company_snapshot(
        self,
        *,
        spec: SourceSpec,
        extracted: list[dict[str, Any]],
        existing: pd.DataFrame,
        run_id: str,
        scraped_at: str,
        snapshot_date: date,
    ) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
        existing_company = existing[existing["company_id"].astype(str) == str(spec.company_id)].copy()
        existing_map = {
            str(row["source_job_id"]): row.to_dict()
            for _, row in existing_company.iterrows()
        }
        incoming_map = {str(row["source_job_id"]): row for row in extracted}
        first_company_snapshot = existing_company.empty
        output: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        content_fields = (
            "title", "department", "team", "location_raw", "country_code", "workplace_type",
            "employment_type", "published_at", "source_updated_at", "job_url", "apply_url",
            "role_family", "seniority", "is_ai_role", "ai_role_confidence", "classifier_version", "content_hash",
        )

        for source_job_id, incoming in incoming_map.items():
            old = existing_map.get(source_job_id)
            base = {
                "dataset_id": "hiring_jobs",
                "source_url": spec.source_url,
                "source_run_id": run_id,
                "scraped_at": scraped_at,
                "source_id": spec.source_id,
                **incoming,
            }
            if old is None:
                base.update(
                    {
                        "first_seen_at": scraped_at,
                        "last_changed_at": scraped_at,
                        "missing_since_at": None,
                        "closed_at": None,
                        "status": "active",
                        "consecutive_missing_runs": 0,
                    }
                )
                output.append(base)
                events.append(
                    self._event(
                        run_id=run_id,
                        scraped_at=scraped_at,
                        source_url=spec.source_url,
                        row=base,
                        event_date=snapshot_date,
                        event_type="seeded" if first_company_snapshot else "opened",
                        previous_status=None,
                        new_status="active",
                    )
                )
                continue

            old_status = self._text(old.get("status"), "active")
            changed_fields = [
                field
                for field in content_fields
                if self._text(old.get(field)) != self._text(incoming.get(field))
            ]
            if old_status == "active" and not changed_fields:
                output.append(old)
                continue

            base.update(
                {
                    "first_seen_at": self._clean(old.get("first_seen_at")) or scraped_at,
                    "last_changed_at": scraped_at,
                    "missing_since_at": None,
                    "closed_at": None,
                    "status": "active",
                    "consecutive_missing_runs": 0,
                }
            )
            output.append(base)
            if old_status == "closed":
                event_type = "reopened"
            elif old_status == "missing":
                event_type = "reappeared"
            else:
                event_type = "updated"
            events.append(
                self._event(
                    run_id=run_id,
                    scraped_at=scraped_at,
                    source_url=spec.source_url,
                    row=base,
                    event_date=snapshot_date,
                    event_type=event_type,
                    previous_status=old_status,
                    new_status="active",
                    changed_fields=changed_fields,
                )
            )

        for source_job_id, old in existing_map.items():
            if source_job_id in incoming_map:
                continue
            old_status = self._text(old.get("status"), "active")
            if old_status == "closed":
                output.append(old)
                continue
            missing_since = pd.to_datetime(old.get("missing_since_at"), errors="coerce", utc=True)
            if (
                old_status == "missing"
                and not pd.isna(missing_since)
                and missing_since.date() == snapshot_date
            ):
                output.append(old)
                continue
            updated = dict(old)
            prior_missing = pd.to_numeric(old.get("consecutive_missing_runs"), errors="coerce")
            missing_runs = (0 if pd.isna(prior_missing) else int(prior_missing)) + 1
            updated.update(
                {
                    "dataset_id": "hiring_jobs",
                    "source_url": spec.source_url,
                    "source_run_id": run_id,
                    "scraped_at": scraped_at,
                    "last_changed_at": scraped_at,
                    "consecutive_missing_runs": missing_runs,
                }
            )
            if missing_runs >= 2:
                new_status = "closed"
                updated["status"] = "closed"
                updated["closed_at"] = scraped_at
                event_type = "closed"
            else:
                new_status = "missing"
                updated["status"] = "missing"
                updated["missing_since_at"] = (
                    self._clean(old.get("missing_since_at")) or snapshot_date.isoformat()
                )
                event_type = "missing"
            output.append(updated)
            events.append(
                self._event(
                    run_id=run_id,
                    scraped_at=scraped_at,
                    source_url=spec.source_url,
                    row=updated,
                    event_date=snapshot_date,
                    event_type=event_type,
                    previous_status=old_status,
                    new_status=new_status,
                )
            )

        return pd.DataFrame(output).reindex(columns=DATASET_COLUMNS["hiring_jobs"]), events

    def _demand_rows(
        self,
        *,
        run_id: str,
        scraped_at: str,
        snapshot_date: date,
        companies: pd.DataFrame,
        jobs: pd.DataFrame,
        events: pd.DataFrame,
        health_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        health_by_source = {str(row["source_id"]): row for row in health_rows}
        event_frame = events.copy()
        if not event_frame.empty:
            event_frame["event_date_parsed"] = pd.to_datetime(event_frame["event_date"], errors="coerce").dt.date
        window_start = snapshot_date - timedelta(days=27)
        rows: list[dict[str, Any]] = []
        for _, company in companies.iterrows():
            company_id = str(company["company_id"])
            company_jobs = jobs[jobs["company_id"].astype(str) == company_id]
            active = company_jobs[company_jobs["status"].astype(str) == "active"]
            company_events = event_frame[event_frame["company_id"].astype(str) == company_id] if not event_frame.empty else event_frame
            if not company_events.empty:
                company_events = company_events[
                    company_events["event_date_parsed"].between(window_start, snapshot_date)
                ]
            source_id = str(company["source_id"])
            source_health = health_by_source.get(source_id, {})
            source_status = str(source_health.get("status") or "warning")
            coverage_value = pd.to_datetime(company["coverage_start_date"], errors="coerce")
            continuous_value = pd.to_datetime(company["continuous_coverage_start_date"], errors="coerce")
            coverage_start = None if pd.isna(coverage_value) else coverage_value.date()
            continuous_start = None if pd.isna(continuous_value) else continuous_value.date()
            same_store = (
                source_status == "ok"
                and continuous_start is not None
                and continuous_start <= window_start
            )

            for role_family in ("All roles", *ROLE_FAMILIES):
                scoped_jobs = active if role_family == "All roles" else active[active["role_family"].astype(str) == role_family]
                scoped_events = company_events
                if role_family != "All roles" and not scoped_events.empty:
                    scoped_events = scoped_events[scoped_events["role_family"].astype(str) == role_family]
                opened = int(scoped_events["event_type"].isin(["opened", "reopened"]).sum()) if not scoped_events.empty else 0
                closed = int((scoped_events["event_type"] == "closed").sum()) if not scoped_events.empty else 0
                rows.append(
                    {
                        "dataset_id": "hiring_demand_daily",
                        "source_url": "derived://ai-hiring-demand",
                        "source_run_id": run_id,
                        "scraped_at": scraped_at,
                        "snapshot_date": snapshot_date.isoformat(),
                        "company_id": company_id,
                        "company_name": str(company["company_name"]),
                        "company_segment": str(company["company_segment"]),
                        "cohort_version": str(company["cohort_version"]),
                        "role_family": role_family,
                        "active_postings": len(scoped_jobs),
                        "active_requisitions": scoped_jobs["source_requisition_id"].dropna().astype(str).nunique(),
                        "ai_role_postings": int(scoped_jobs["is_ai_role"].fillna(False).astype(bool).sum()),
                        "new_postings_28d": opened,
                        "closed_postings_28d": closed,
                        "net_posting_flow_28d": opened - closed,
                        "source_status": source_status,
                        "coverage_start_date": coverage_start.isoformat() if coverage_start is not None else None,
                        "same_store_28d": same_store,
                        "continuous_coverage_start_date": (
                            continuous_start.isoformat() if continuous_start is not None else None
                        ),
                    }
                )
        return rows

    def run_daily_update(self, *, target_date: date | None = None) -> dict[str, int]:
        run_id, scraped_at = self._context()
        snapshot_date = target_date or datetime.now(timezone.utc).date()
        previous_health = self.storage.load("hiring_source_health")
        snapshots, fetch_failures = self.source.fetch_all(self._validators(previous_health))
        spec_by_id = {spec.source_id: spec for spec in self.source.specs}
        board_specs = tuple(spec for spec in self.source.specs if spec.source_kind == "job_board")
        previous_health_by_id = {
            str(row["source_id"]): row.to_dict() for _, row in previous_health.iterrows()
        }
        previous_jobs = self.storage.load("hiring_jobs")
        previous_indeed = self.storage.load("indeed_ai_posting_share_daily")

        accepted_board_rows: dict[str, list[dict[str, Any]] | None] = {}
        indeed_rows: list[dict[str, Any]] | None = None
        health_by_id: dict[str, dict[str, Any]] = {}
        failures: list[FetchFailure] = list(fetch_failures)

        for snapshot in snapshots:
            spec = spec_by_id[snapshot.source_id]
            prior = previous_health_by_id.get(snapshot.source_id, {})
            prior_good = self._clean(prior.get("last_good_row_count"))
            if prior_good is None:
                prior_good = self._clean(prior.get("row_count"))
            if snapshot.not_modified:
                has_existing = not previous_indeed.empty if spec.source_kind == "macro_csv" else not previous_jobs[previous_jobs["company_id"].astype(str) == str(spec.company_id)].empty
                if not has_existing:
                    failures.append(
                        FetchFailure(
                            source_id=spec.source_id,
                            source_kind=spec.source_kind,
                            source_url=spec.source_url,
                            company_id=spec.company_id,
                            company_name=spec.company_name,
                            error="NotModifiedWithoutBaseline: received 304 before any local dataset existed",
                            status_code=304,
                        )
                    )
                    continue
                row_count = int(pd.to_numeric(prior_good, errors="coerce") or 0)
                if spec.source_kind == "job_board":
                    accepted_board_rows[spec.source_id] = None
                health_by_id[spec.source_id] = {
                    "dataset_id": "hiring_source_health",
                    "source_url": spec.source_url,
                    "source_run_id": run_id,
                    "scraped_at": scraped_at,
                    "source_id": spec.source_id,
                    "source_kind": spec.source_kind,
                    "company_id": spec.company_id,
                    "company_name": spec.company_name,
                    "status": "ok",
                    "status_code": 304,
                    "response_ms": snapshot.response_ms,
                    "content_bytes": 0,
                    "content_hash": self._clean(prior.get("content_hash")),
                    "etag": snapshot.etag,
                    "last_modified": snapshot.last_modified,
                    "row_count": row_count,
                    "last_good_row_count": row_count,
                    "detail": "Official public source healthy",
                }
                continue

            try:
                if spec.source_kind == "macro_csv":
                    extracted_indeed = extract_indeed(snapshot, run_id=run_id, scraped_at=scraped_at)
                    validate_indeed(extracted_indeed, production=self.production_quality)
                    indeed_rows = extracted_indeed
                    extracted_count = len(extracted_indeed)
                    content_hash = self._canonical_hash(extracted_indeed, ("date", "jobcountry", "ai_share_pct"))
                else:
                    extracted_board = extract_board(snapshot, spec)
                    validate_board(extracted_board, company_id=str(spec.company_id), production=self.production_quality)
                    extracted_count = len(extracted_board)
                    if count_collapsed(extracted_count, prior_good):
                        raise ValueError(f"CountCollapse: extracted {extracted_count} jobs after {int(prior_good)} previously")
                    accepted_board_rows[spec.source_id] = extracted_board
                    content_hash = self._canonical_hash(extracted_board, ("source_job_id", "content_hash"))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
                failures.append(
                    FetchFailure(
                        source_id=spec.source_id,
                        source_kind=spec.source_kind,
                        source_url=spec.source_url,
                        company_id=spec.company_id,
                        company_name=spec.company_name,
                        error=f"{type(exc).__name__}: {exc}",
                        status_code=snapshot.status_code,
                    )
                )
                continue

            health_by_id[spec.source_id] = {
                "dataset_id": "hiring_source_health",
                "source_url": spec.source_url,
                "source_run_id": run_id,
                "scraped_at": scraped_at,
                "source_id": spec.source_id,
                "source_kind": spec.source_kind,
                "company_id": spec.company_id,
                "company_name": spec.company_name,
                "status": "ok",
                "status_code": snapshot.status_code,
                "response_ms": snapshot.response_ms,
                "content_bytes": len((snapshot.body or "").encode("utf-8")),
                "content_hash": content_hash,
                "etag": snapshot.etag,
                "last_modified": snapshot.last_modified,
                "row_count": extracted_count,
                "last_good_row_count": extracted_count,
                "detail": "Official public source healthy",
            }

        for failure in failures:
            prior = previous_health_by_id.get(failure.source_id, {})
            prior_good = self._clean(prior.get("last_good_row_count"))
            if prior_good is None:
                prior_good = self._clean(prior.get("row_count"))
            health_by_id[failure.source_id] = {
                "dataset_id": "hiring_source_health",
                "source_url": failure.source_url,
                "source_run_id": run_id,
                "scraped_at": scraped_at,
                "source_id": failure.source_id,
                "source_kind": failure.source_kind,
                "company_id": failure.company_id,
                "company_name": failure.company_name,
                "status": "warning",
                "status_code": failure.status_code,
                "response_ms": None,
                "content_bytes": None,
                "content_hash": self._clean(prior.get("content_hash")),
                "etag": self._clean(prior.get("etag")),
                "last_modified": self._clean(prior.get("last_modified")),
                "row_count": 0,
                "last_good_row_count": prior_good,
                "detail": failure.error[:1000],
            }

        for spec in self.source.specs:
            if spec.source_id not in health_by_id:
                failures.append(
                    FetchFailure(
                        source_id=spec.source_id,
                        source_kind=spec.source_kind,
                        source_url=spec.source_url,
                        company_id=spec.company_id,
                        company_name=spec.company_name,
                        error="MissingSourceResult: source produced neither a snapshot nor a fetch failure",
                    )
                )
                health_by_id[spec.source_id] = {
                    "dataset_id": "hiring_source_health", "source_url": spec.source_url,
                    "source_run_id": run_id, "scraped_at": scraped_at, "source_id": spec.source_id,
                    "source_kind": spec.source_kind, "company_id": spec.company_id, "company_name": spec.company_name,
                    "status": "warning", "status_code": None, "response_ms": None, "content_bytes": None,
                    "content_hash": None, "etag": None, "last_modified": None, "row_count": 0,
                    "last_good_row_count": None, "detail": "MissingSourceResult",
                }

        successful_boards = len(accepted_board_rows)
        minimum_boards = max(1, (len(board_specs) + 1) // 2)
        health_rows = [health_by_id[spec.source_id] for spec in self.source.specs]
        if successful_boards < minimum_boards:
            manifest = {
                "run_id": run_id, "scraped_at": scraped_at, "snapshot_date": snapshot_date.isoformat(),
                "status": "failed", "successful_boards": successful_boards, "expected_boards": len(board_specs),
                "error": f"Only {successful_boards}/{len(board_specs)} hiring boards succeeded",
                "failures": [failure.__dict__ for failure in failures],
            }
            self.storage.write_raw_run(run_id=run_id, snapshots=snapshots, manifest=manifest)
            raise RuntimeError(manifest["error"])

        previous_companies = self.storage.load("hiring_companies")
        company_rows = self._company_rows(
            run_id=run_id,
            scraped_at=scraped_at,
            snapshot_date=snapshot_date,
            previous=previous_companies,
            previous_health=previous_health,
            health_rows=health_rows,
            board_specs=board_specs,
        )
        companies = self.storage.upsert("hiring_companies", company_rows)

        job_parts = [previous_jobs[~previous_jobs["company_id"].astype(str).isin([str(spec.company_id) for spec in board_specs if spec.source_id in accepted_board_rows and accepted_board_rows[spec.source_id] is not None])]]
        new_events: list[dict[str, Any]] = []
        for spec in board_specs:
            extracted = accepted_board_rows.get(spec.source_id)
            if extracted is None:
                continue
            company_frame, company_events = self._apply_company_snapshot(
                spec=spec,
                extracted=extracted,
                existing=previous_jobs,
                run_id=run_id,
                scraped_at=scraped_at,
                snapshot_date=snapshot_date,
            )
            job_parts.append(company_frame)
            new_events.extend(company_events)
        combined_jobs = pd.concat(job_parts, ignore_index=True, sort=False).reindex(columns=DATASET_COLUMNS["hiring_jobs"])
        jobs = self.storage.upsert("hiring_jobs", combined_jobs)
        events = self.storage.upsert("hiring_job_events", new_events) if new_events else self.storage.load("hiring_job_events")
        if indeed_rows is not None:
            indeed = self.storage.upsert("indeed_ai_posting_share_daily", indeed_rows)
        else:
            indeed = previous_indeed
        health = self.storage.upsert("hiring_source_health", health_rows)
        demand_rows = self._demand_rows(
            run_id=run_id,
            scraped_at=scraped_at,
            snapshot_date=snapshot_date,
            companies=companies,
            jobs=jobs,
            events=events,
            health_rows=health_rows,
        )
        demand = self.storage.upsert("hiring_demand_daily", demand_rows)

        written = {
            "indeed_ai_posting_share_daily": len(indeed),
            "hiring_companies": len(companies),
            "hiring_jobs": len(jobs),
            "hiring_job_events": len(events),
            "hiring_demand_daily": len(demand),
            "hiring_source_health": len(health),
        }
        manifest = {
            "run_id": run_id,
            "scraped_at": scraped_at,
            "snapshot_date": snapshot_date.isoformat(),
            "status": "success" if not failures else "warning",
            "request_count": len(snapshots) + len(fetch_failures),
            "successful_boards": successful_boards,
            "expected_boards": len(board_specs),
            "datasets": written,
            "failures": [failure.__dict__ for failure in failures],
        }
        self.storage.write_raw_run(run_id=run_id, snapshots=snapshots, manifest=manifest)
        return written
