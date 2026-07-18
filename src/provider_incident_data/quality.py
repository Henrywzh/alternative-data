from __future__ import annotations

import pandas as pd


VALID_STATUSES = {"resolved", "monitoring", "identified", "investigating", "scheduled", "in_progress", "verifying", "active", "unknown"}


def validate_incidents(frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    keys = ["provider_id", "source_incident_id"]
    if frame[keys].isna().any().any():
        raise ValueError("Provider incidents contain null natural keys")
    if frame.duplicated(keys).any():
        raise ValueError("Provider incidents contain duplicate natural keys")
    invalid_statuses = set(frame["normalized_status"].dropna().astype(str)) - VALID_STATUSES
    if invalid_statuses:
        raise ValueError(f"Provider incidents contain invalid statuses: {sorted(invalid_statuses)}")
    severity = pd.to_numeric(frame["severity_level"], errors="coerce")
    if severity.isna().any() or (~severity.between(0, 3)).any():
        raise ValueError("Provider incident severity levels must be between 0 and 3")
    starts = pd.to_datetime(frame["started_at"], format="mixed", errors="coerce", utc=True)
    resolutions = pd.to_datetime(frame["resolved_at"], format="mixed", errors="coerce", utc=True)
    invalid_duration = starts.notna() & resolutions.notna() & (resolutions < starts)
    if invalid_duration.any():
        raise ValueError("Provider incidents contain a resolution before the start time")


def validate_source_health(frame: pd.DataFrame, *, expected_providers: set[str]) -> None:
    if frame.empty:
        raise ValueError("Provider incident source health is empty")
    observed = set(frame["provider_id"].dropna().astype(str))
    if observed != expected_providers:
        missing = sorted(expected_providers - observed)
        extra = sorted(observed - expected_providers)
        raise ValueError(f"Provider incident source coverage mismatch: missing={missing}, extra={extra}")
    if frame["provider_id"].duplicated().any():
        raise ValueError("Provider incident source health contains duplicate providers")
