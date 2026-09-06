from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from dashboard.data import (
    DATASET_REGISTRY,
    DatasetLoadResult,
    FreshnessInfo,
    dataset_exists,
    dataset_ids,
    domain_dataset_ids,
)

# A dataset is called stale once it is this many of its own publication
# intervals behind, plus a week of grace. The cadence is measured from the
# dataset's own dates rather than declared per dataset, so a daily feed is
# judged on days and a monthly one on months without 96 registry entries to
# keep in step with reality.
STALENESS_INTERVALS = 2.0
STALENESS_GRACE_DAYS = 7.0
# Below this many distinct dates a median gap is not a cadence, just noise.
STALENESS_MIN_POINTS = 6


@dataclass(frozen=True)
class CheckResult:
    status: str
    title: str
    detail: str
    domain: str


def run_checks(
    datasets: dict[str, DatasetLoadResult],
    freshness: FreshnessInfo,
    base_dir: Path | None = None,
    expected_dataset_ids: list[str] | None = None,
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    missing_files = []
    expected_ids = expected_dataset_ids if expected_dataset_ids is not None else (list(datasets) if datasets else dataset_ids())
    for dataset_id in expected_ids:
        registry_entry = DATASET_REGISTRY.get(dataset_id, {})
        if not dataset_exists(dataset_id, base_dir):
            if registry_entry.get("optional", False):
                continue
            missing_files.append(dataset_id)
    
    if missing_files:
        checks.append(CheckResult("error", "Missing datasets", ", ".join(missing_files), "global"))

    for dataset_id, result in datasets.items():
        if dataset_id == "provider_momentum_daily":
            continue
        registry_entry = DATASET_REGISTRY.get(dataset_id, {})
        if result.row_count == 0 and not registry_entry.get("optional", False):
            checks.append(CheckResult("error", f"{dataset_id} is empty", "No rows available for this dataset.", result.domain))
        if result.missing_columns:
            checks.append(
                CheckResult(
                    "error",
                    f"{dataset_id} schema drift",
                    "Missing columns: " + ", ".join(result.missing_columns),
                    result.domain,
                )
            )
        if result.duplicate_rows:
            checks.append(
                CheckResult(
                    "warning",
                    f"{dataset_id} duplicate natural keys",
                    f"{result.duplicate_rows} duplicate rows detected on the natural key.",
                    result.domain,
                )
            )

    for dataset_id, result in datasets.items():
        # `optional` already means "absent or empty is not a fault here", which
        # is exactly the contract of a feed that has been retired upstream.
        if DATASET_REGISTRY.get(dataset_id, {}).get("optional", False):
            continue
        stale = _staleness(result)
        if stale is not None:
            days_behind, cadence_days = stale
            checks.append(
                CheckResult(
                    "warning",
                    f"{dataset_id} has stopped advancing",
                    f"Latest row is {result.latest_date} — {days_behind:.0f} days back, "
                    f"on a feed that normally publishes every {cadence_days:.0f} day(s).",
                    result.domain,
                )
            )

    if freshness.latest_scraped_at is None:
        checks.append(CheckResult("warning", "Freshness unavailable", "No dataset-level scraped timestamps found.", "global"))
    if expected_dataset_ids is None and freshness.latest_manifest_path is None:
        checks.append(CheckResult("warning", "Manifest unavailable", "No raw run manifest found across data/raw sources.", "global"))

    if not checks:
        checks.append(CheckResult("ok", "All checks passed", "Expected datasets are present and look internally consistent.", "global"))
    return checks


def _staleness(result: DatasetLoadResult) -> tuple[float, float] | None:
    """How far behind its own cadence a dataset is, or None if it is on time.

    Presence, schema and duplicate checks all pass for a feed that quietly
    stopped: the file is there, the columns are right, the rows are unique, and
    the newest row is from March. That is the failure mode this dashboard keeps
    hitting -- an upstream retirement or a red workflow nobody watched -- and
    the panel had nothing to say about it. Note this measures the *data*, not
    scraped_at: an upsert leaves the original scraped_at on rows it did not
    change, so a current dataset can carry a month-old timestamp.
    """
    if result.latest_date is None or result.frame.empty:
        return None
    column = result.primary_date_column
    if not column or column not in result.frame.columns:
        return None
    dates = pd.to_datetime(result.frame[column], errors="coerce", utc=True).dropna()
    distinct = pd.Index(dates.dt.normalize().unique()).sort_values()
    if len(distinct) < STALENESS_MIN_POINTS:
        return None
    cadence_days = float(pd.Series(distinct).diff().dropna().dt.total_seconds().median()) / 86400.0
    if cadence_days <= 0:
        return None
    latest = pd.Timestamp(distinct[-1])
    # Monthly observations are conventionally stamped on the first day of the
    # represented month. Measuring from that stamp overstates their age by
    # almost a full month and can flag a normally lagged publication as stale.
    # Use month-end only for genuine month-start series; daily/weekly feeds
    # retain their exact observation date.
    freshness_reference = latest
    if cadence_days >= 27.0 and latest.day == 1:
        freshness_reference = latest + pd.offsets.MonthEnd(0)
    days_behind = (
        pd.Timestamp.now(tz="UTC").normalize() - freshness_reference
    ).total_seconds() / 86400.0
    if days_behind > STALENESS_INTERVALS * cadence_days + STALENESS_GRACE_DAYS:
        return days_behind, cadence_days
    return None
