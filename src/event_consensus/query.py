"""Read-only event research queries over local PIT artifacts and ledgers."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import (
    COMPONENT_LEDGER_PATH,
    EVENT_LEDGER_PATH,
    LATEST_ARTIFACT_PATH,
    QUOTE_LEDGER_PATH,
)
from .storage import (
    load_artifact,
    load_component_ledger,
    load_event_ledger,
    load_quote_ledger,
)


QUERY_CONTRACT_VERSION = "1.0"
QUERY_NAMES = (
    "capabilities",
    "brief",
    "list",
    "research",
    "history",
    "postmortem",
    "health",
)


class QueryError(ValueError):
    """Raised when a local artifact cannot safely answer a query."""


def _now_utc(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    parsed = pd.to_datetime(value, errors="coerce", utc=True)
    return None if pd.isna(parsed) else parsed


def _iso(value: Any) -> str | None:
    parsed = _timestamp(value)
    return None if parsed is None else parsed.isoformat()


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, pd.Timestamp)):
        return _iso(value)
    if value is pd.NA or value is pd.NaT:
        return None
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except (TypeError, ValueError):
            pass
    return value


def _records(frame: pd.DataFrame | None) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    return [
        _json_safe(row)
        for row in frame.astype(object).where(pd.notna(frame), None).to_dict("records")
    ]


def _numeric(value: Any) -> float | None:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return None if pd.isna(parsed) else float(parsed)


def _priority(row: Mapping[str, Any]) -> tuple[str, str, int]:
    importance = _numeric(row.get("importance"))
    if importance is not None and importance == 1.0:
        return "high", "provider_importance_1", 0
    score = _numeric(row.get("risk_score"))
    if score is None:
        return "unknown", "score_unavailable", 3
    if score >= 70:
        return "high", "risk_score", 0
    if score >= 50:
        return "medium", "risk_score", 1
    return "low", "risk_score", 2


def _availability(row: Mapping[str, Any], *, now: datetime) -> dict[str, str]:
    scheduled = _timestamp(row.get("scheduled_at_utc"))
    actual = row.get("actual")
    forecast = row.get("forecast")
    if forecast is None or pd.isna(forecast):
        forecast_status = "not_provided"
    else:
        forecast_status = "available"
    if actual is not None and not pd.isna(actual):
        actual_status = "available"
    elif scheduled is not None and scheduled > pd.Timestamp(now):
        actual_status = "not_released"
    else:
        actual_status = "not_provided"
    return {
        "forecast": forecast_status,
        "actual": actual_status,
        "market_reaction": "insufficient_history",
    }


def _source_health_summary(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    statuses: dict[str, int] = {}
    records = 0
    total = 0
    for row in rows:
        total += 1
        status = str(row.get("status") or "unknown")
        statuses[status] = statuses.get(status, 0) + 1
        records += int(_numeric(row.get("records")) or 0)
    return {"total_sources": total, "records": records, "by_status": statuses}


class EventQueryService:
    """Serve deterministic, local-only event research read models."""

    def __init__(
        self,
        *,
        artifact_path: Path = LATEST_ARTIFACT_PATH,
        event_ledger_path: Path = EVENT_LEDGER_PATH,
        quote_ledger_path: Path = QUOTE_LEDGER_PATH,
        component_ledger_path: Path = COMPONENT_LEDGER_PATH,
        now_utc: datetime | None = None,
    ) -> None:
        artifact = load_artifact(Path(artifact_path))
        if artifact is None:
            raise QueryError(f"latest artifact is missing or invalid: {artifact_path}")
        if not isinstance(artifact.get("events", []), list):
            raise QueryError(f"artifact events collection is invalid: {artifact_path}")
        self.artifact_path = Path(artifact_path)
        self.event_ledger_path = Path(event_ledger_path)
        self.quote_ledger_path = Path(quote_ledger_path)
        self.component_ledger_path = Path(component_ledger_path)
        self.artifact = artifact
        self.now = _now_utc(now_utc)
        self.events = [dict(row) for row in artifact.get("events", []) if isinstance(row, Mapping)]

    def _data_as_of(self) -> str | None:
        candidates: list[pd.Timestamp] = []
        for collection_name in ("events", "quotes", "official_components"):
            for row in self.artifact.get(collection_name, []):
                if not isinstance(row, Mapping):
                    continue
                for field in ("retrieved_at_utc", "market_timestamp_utc"):
                    parsed = _timestamp(row.get(field))
                    if parsed is not None:
                        candidates.append(parsed)
        return max(candidates).isoformat() if candidates else _iso(self.artifact.get("generated_at_utc"))

    def _envelope(
        self,
        query: str,
        data: Mapping[str, Any],
        *,
        filters: Mapping[str, Any] | None = None,
        warnings: Iterable[str] = (),
    ) -> dict[str, Any]:
        return _json_safe(
            {
                "query_contract_version": QUERY_CONTRACT_VERSION,
                "query": query,
                "generated_at_utc": self.now,
                "data_as_of_utc": self._data_as_of(),
                "artifact_schema_version": self.artifact.get("schema_version"),
                "content_hash": self.artifact.get("content_hash"),
                "status": "ready",
                "source_health_summary": _source_health_summary(
                    self.artifact.get("source_health", [])
                ),
                "filters": dict(filters or {}),
                "data": dict(data),
                "warnings": list(warnings),
            }
        )

    def _decorate_event(self, row: Mapping[str, Any]) -> dict[str, Any]:
        priority, reason, rank = _priority(row)
        output = dict(row)
        output.update(
            {
                "priority": priority,
                "priority_reason": reason,
                "priority_rank": rank,
                "released": (
                    _timestamp(row.get("scheduled_at_utc")) is not None
                    and _timestamp(row.get("scheduled_at_utc")) <= pd.Timestamp(self.now)
                ),
                "availability": _availability(row, now=self.now),
            }
        )
        return _json_safe(output)

    def _event_rows(self) -> list[dict[str, Any]]:
        return [self._decorate_event(row) for row in self.events]

    def capabilities(self) -> dict[str, Any]:
        events = self._event_rows()
        scheduled = [_timestamp(row.get("scheduled_at_utc")) for row in events]
        scheduled = [value for value in scheduled if value is not None]
        return self._envelope(
            "capabilities",
            {
                "commands": list(QUERY_NAMES),
                "countries": sorted({str(row.get("country")) for row in events if row.get("country")}),
                "event_families": sorted({str(row.get("event_family")) for row in events if row.get("event_family")}),
                "scheduled_range": {
                    "start_utc": min(scheduled).isoformat() if scheduled else None,
                    "end_utc": max(scheduled).isoformat() if scheduled else None,
                },
                "artifact_sections": sorted(
                    key for key, value in self.artifact.items() if isinstance(value, (list, dict))
                ),
            },
        )

    def brief(
        self,
        *,
        horizon_hours: int = 48,
        countries: Iterable[str] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        if horizon_hours <= 0:
            raise QueryError("horizon_hours must be positive")
        country_set = {str(country) for country in countries} if countries else None
        end = pd.Timestamp(self.now) + pd.Timedelta(hours=horizon_hours)
        rows = [
            row
            for row in self._event_rows()
            if not row["released"]
            and (_timestamp(row.get("scheduled_at_utc")) or end) <= end
            and (_timestamp(row.get("scheduled_at_utc")) or pd.Timestamp(self.now)) >= pd.Timestamp(self.now)
            and (country_set is None or str(row.get("country")) in country_set)
            and row["priority"] in {"high", "medium"}
        ]
        rows.sort(
            key=lambda row: (
                row["priority_rank"],
                0 if row["priority_reason"] == "provider_importance_1" else 1,
                -(_numeric(row.get("risk_score")) or 0.0),
                _timestamp(row.get("scheduled_at_utc")) or pd.Timestamp.max.tz_localize("UTC"),
            )
        )
        all_window_rows = [
            row
            for row in self._event_rows()
            if not row["released"]
            and (_timestamp(row.get("scheduled_at_utc")) or end) <= end
            and (_timestamp(row.get("scheduled_at_utc")) or pd.Timestamp(self.now)) >= pd.Timestamp(self.now)
            and (country_set is None or str(row.get("country")) in country_set)
        ]
        focus_rows = [
            row for row in all_window_rows if row["priority"] in {"high", "medium"}
        ]
        low_count = len(all_window_rows) - len(focus_rows)
        consensus_count = sum(
            1
            for row in focus_rows
            if row["availability"].get("forecast") == "available"
        )
        return self._envelope(
            "brief",
            {
                "horizon_hours": horizon_hours,
                "events": rows[: max(1, limit)],
                "high_priority_count": sum(
                    1 for row in focus_rows if row["priority"] == "high"
                ),
                "consensus_available_count": consensus_count,
                "awaiting_consensus_count": len(focus_rows) - consensus_count,
                "hidden_low_priority_count": low_count,
            },
            filters={"horizon_hours": horizon_hours, "countries": sorted(country_set) if country_set else None},
        )

    def list_events(
        self,
        *,
        start_utc: str | None = None,
        end_utc: str | None = None,
        countries: Iterable[str] | None = None,
        priority: str | None = None,
        event_family: str | None = None,
        checkpoint: str | None = None,
        released: bool | None = None,
    ) -> dict[str, Any]:
        allowed_priorities = {"high", "medium", "low", "unknown"}
        if priority is not None and priority not in allowed_priorities:
            raise QueryError(f"unsupported priority: {priority}")
        start = _timestamp(start_utc)
        end = _timestamp(end_utc)
        country_set = {str(country) for country in countries} if countries else None
        rows: list[dict[str, Any]] = []
        for row in self._event_rows():
            scheduled = _timestamp(row.get("scheduled_at_utc"))
            if start is not None and (scheduled is None or scheduled < start):
                continue
            if end is not None and (scheduled is None or scheduled > end):
                continue
            if country_set is not None and str(row.get("country")) not in country_set:
                continue
            if priority is not None and row["priority"] != priority:
                continue
            if event_family is not None and str(row.get("event_family")) != event_family:
                continue
            if checkpoint is not None and str(row.get("snapshot_stage")) != checkpoint:
                continue
            if released is not None and row["released"] is not released:
                continue
            rows.append(row)
        rows.sort(
            key=lambda row: (
                _timestamp(row.get("scheduled_at_utc")) or pd.Timestamp.max.tz_localize("UTC"),
                row["priority_rank"],
                str(row.get("event_id") or ""),
            )
        )
        return self._envelope(
            "list",
            {"events": rows, "count": len(rows)},
            filters={
                "start_utc": start_utc,
                "end_utc": end_utc,
                "countries": sorted(country_set) if country_set else None,
                "priority": priority,
                "event_family": event_family,
                "checkpoint": checkpoint,
                "released": released,
            },
        )

    def _find_event(self, event_id: str) -> dict[str, Any]:
        for row in self._event_rows():
            if str(row.get("event_id")) == str(event_id):
                return row
        raise QueryError(f"event_id not found: {event_id}")

    def research(self, event_id: str) -> dict[str, Any]:
        event = self._find_event(event_id)
        family = str(event.get("event_family") or "other")
        history = [
            row
            for row in self.artifact.get("consensus_history", [])
            if isinstance(row, Mapping) and str(row.get("event_id")) == str(event_id)
        ]
        components = [
            row
            for row in self.artifact.get("component_contracts", [])
            if isinstance(row, Mapping) and str(row.get("event_family")) == family
        ]
        official = [
            row
            for row in self.artifact.get("official_components", [])
            if isinstance(row, Mapping) and str(row.get("event_family")) == family
        ]
        scenarios = self.artifact.get("scenario_templates", {}).get(family, [])
        return self._envelope(
            "research",
            {
                "event": event,
                "consensus_history": _json_safe(history),
                "component_contracts": _json_safe(components),
                "official_components": _json_safe(official),
                "quotes": _json_safe(self.artifact.get("quotes", [])),
                "scenario_templates": _json_safe(scenarios),
                "evidence": {
                    "source_name": event.get("source_name"),
                    "source_url": event.get("source_url"),
                    "verification_status": event.get("verification_status"),
                    "first_observed_at_utc": event.get("first_observed_at_utc"),
                    "retrieved_at_utc": event.get("retrieved_at_utc"),
                },
            },
            filters={"event_id": event_id},
        )

    def history(self, event_id: str) -> dict[str, Any]:
        self._find_event(event_id)
        ledger = load_event_ledger(self.event_ledger_path)
        warnings: list[str] = []
        if ledger.empty:
            warnings.append("event ledger is unavailable; no PIT observations were loaded")
            observations: list[dict[str, Any]] = []
        else:
            observations = _records(
                ledger[ledger["event_id"].astype(str).eq(str(event_id))]
                .sort_values("retrieved_at_utc")
            )
        return self._envelope(
            "history",
            {"event_id": event_id, "observations": observations},
            filters={"event_id": event_id},
            warnings=warnings,
        )

    def postmortem(self, event_id: str) -> dict[str, Any]:
        event = self._find_event(event_id)
        actual = event.get("actual")
        actual_available = actual is not None and not pd.isna(actual)
        return self._envelope(
            "postmortem",
            {
                "event": event,
                "pre_release": {
                    "forecast": event.get("forecast"),
                    "previous": event.get("previous"),
                    "revised_previous": event.get("revised_previous"),
                },
                "release": {
                    "actual": actual,
                    "surprise": event.get("surprise"),
                    "verification_status": event.get("verification_status"),
                    "available": actual_available,
                },
                "market_reaction": {
                    "status": "insufficient_history",
                    "observations": [],
                    "reason": "no PIT-safe event-study observations are published",
                },
            },
            filters={"event_id": event_id},
        )

    def health(self) -> dict[str, Any]:
        return self._envelope(
            "health",
            {
                "artifact_path": str(self.artifact_path),
                "artifact_status": self.artifact.get("status"),
                "generated_at_utc": self.artifact.get("generated_at_utc"),
                "content_hash": self.artifact.get("content_hash"),
                "source_health": _json_safe(self.artifact.get("source_health", [])),
                "caveats": _json_safe(self.artifact.get("caveats", [])),
            },
        )
