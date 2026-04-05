from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dashboard.data import DatasetLoadResult, FreshnessInfo, dataset_ids, normalized_root


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
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    root = normalized_root(base_dir)

    missing_files = []
    for dataset_id in dataset_ids():
        if not ((root / f"{dataset_id}.parquet").exists() or (root / f"{dataset_id}.csv").exists()):
            missing_files.append(dataset_id)
    if missing_files:
        checks.append(CheckResult("error", "Missing datasets", ", ".join(missing_files), "global"))

    for dataset_id, result in datasets.items():
        if result.row_count == 0:
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

    if freshness.latest_scraped_at is None:
        checks.append(CheckResult("warning", "Freshness unavailable", "No dataset-level scraped timestamps found.", "global"))
    if freshness.latest_manifest_path is None:
        checks.append(CheckResult("warning", "Manifest unavailable", "No raw run manifest found in data/raw/openrouter.", "global"))

    if not checks:
        checks.append(CheckResult("ok", "All checks passed", "Expected datasets are present and look internally consistent.", "global"))
    return checks
