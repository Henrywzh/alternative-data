#!/usr/bin/env python3
"""Audit whether core Asia Markets artifacts meet their publication cadence.

Artifact ``generatedAt`` timestamps only prove that a builder ran.  This audit
checks the newest source observation against a small, explicit set of release
contracts whose schedules are known well enough to fail closed.
"""

from __future__ import annotations

import argparse
import json
from calendar import monthrange
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_ROOT = ROOT / "apps" / "asia-markets-dashboard" / ".generated"
DEFAULT_OUTPUT = DEFAULT_ARTIFACT_ROOT / "asia-markets-freshness.json"


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    sector: str
    dataset: str
    required: bool
    status: str
    expected_latest_period: str | None
    latest_observation: str | None
    notes: str


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _shift_month(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def expected_month(as_of: date, *, release_day: int) -> str:
    """Return the latest prior month expected to be published by ``as_of``."""
    lag = -1 if as_of.day >= release_day else -2
    return _shift_month(_month_start(as_of), lag).strftime("%Y-%m")


def expected_quarter(as_of: date, *, release_lag_days: int) -> str:
    """Return the newest completed quarter whose release lag has elapsed."""
    candidates: list[tuple[date, str]] = []
    for year in range(as_of.year - 2, as_of.year + 1):
        for quarter, month in enumerate((3, 6, 9, 12), start=1):
            end = date(year, month, monthrange(year, month)[1])
            if end + timedelta(days=release_lag_days) <= as_of:
                candidates.append((end, f"{year}-Q{quarter}"))
    if not candidates:
        raise ValueError(f"No completed quarter found for {as_of}")
    return max(candidates)[1]


def expected_month_by_lag(as_of: date, *, release_lag_days: int) -> str:
    """Return the newest month-end whose publication lag has elapsed."""
    candidates: list[date] = []
    for offset in range(-15, 1):
        start = _shift_month(_month_start(as_of), offset)
        end = date(start.year, start.month, monthrange(start.year, start.month)[1])
        if end + timedelta(days=release_lag_days) <= as_of:
            candidates.append(end)
    if not candidates:
        raise ValueError(f"No completed month found for {as_of}")
    return max(candidates).strftime("%Y-%m")


def _normalise_period(value: Any, *, grain: str = "month") -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "Q" in text.upper():
        compact = text.upper().replace(" ", "")
        if len(compact) >= 6 and compact[:4].isdigit():
            return f"{compact[:4]}-Q{compact.split('Q', 1)[1][0]}"
    try:
        parsed = date.fromisoformat(text[:10])
        if grain == "quarter":
            quarter = ((parsed.month - 1) // 3) + 1
            return f"{parsed.year}-Q{quarter}"
        return parsed.strftime("%Y-%m")
    except ValueError:
        if len(text) >= 7 and text[:4].isdigit() and text[4] in "-/":
            return text[:7].replace("/", "-")
    return text


def _max_period(
    rows: Iterable[dict[str, Any]],
    fields: tuple[str, ...],
    *,
    grain: str = "month",
) -> str | None:
    values: list[str] = []
    for row in rows:
        for field in fields:
            value = _normalise_period(row.get(field), grain=grain)
            if value:
                values.append(value)
                break
    return max(values) if values else None


def _load_artifact(root: Path, slug: str, language: str = "en") -> dict[str, Any]:
    suffix = "" if language == "en" else f"-{language}"
    path = root / f"{slug}-artifact{suffix}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _dataset(artifact: dict[str, Any], dataset_id: str) -> list[dict[str, Any]]:
    value = artifact.get("snapshot", {}).get("datasets", {}).get(dataset_id, [])
    return value if isinstance(value, list) else []


def _period_check(
    *,
    artifact: dict[str, Any],
    check_id: str,
    sector: str,
    dataset_id: str,
    expected: str,
    fields: tuple[str, ...] = ("date", "month", "period", "quarter"),
    grain: str = "month",
    required: bool = True,
    notes: str,
) -> CheckResult:
    latest = _max_period(_dataset(artifact, dataset_id), fields, grain=grain)
    status = "healthy" if latest is not None and latest >= expected else "stale"
    return CheckResult(
        check_id=check_id,
        sector=sector,
        dataset=dataset_id,
        required=required,
        status=status,
        expected_latest_period=expected,
        latest_observation=latest,
        notes=notes,
    )


def _date_check(
    *,
    artifact: dict[str, Any],
    check_id: str,
    sector: str,
    dataset_id: str,
    expected: date,
    fields: tuple[str, ...] = ("date", "observation_date"),
    required: bool = True,
    notes: str,
) -> CheckResult:
    values: list[date] = []
    for row in _dataset(artifact, dataset_id):
        for field in fields:
            value = row.get(field)
            if value in (None, ""):
                continue
            try:
                values.append(date.fromisoformat(str(value)[:10]))
            except ValueError:
                pass
            break
    latest = max(values) if values else None
    return CheckResult(
        check_id=check_id,
        sector=sector,
        dataset=dataset_id,
        required=required,
        status="healthy" if latest is not None and latest >= expected else "stale",
        expected_latest_period=expected.isoformat(),
        latest_observation=latest.isoformat() if latest else None,
        notes=notes,
    )


def _dataset_alignment_check(
    *,
    artifact: dict[str, Any],
    check_id: str,
    sector: str,
    source_dataset: str,
    dependent_datasets: tuple[str, ...],
    required: bool = True,
    notes: str,
) -> CheckResult:
    source_latest = _max_period(_dataset(artifact, source_dataset), ("date", "month"))
    dependent_latest = [
        _max_period(_dataset(artifact, dataset_id), ("date", "month"))
        for dataset_id in dependent_datasets
    ]
    comparable = source_latest is not None and all(dependent_latest)
    status = (
        "healthy"
        if comparable and min(value for value in dependent_latest if value) >= source_latest
        else "stale"
    )
    observed = min((value for value in dependent_latest if value), default=None)
    return CheckResult(
        check_id=check_id,
        sector=sector,
        dataset=",".join(dependent_datasets),
        required=required,
        status=status,
        expected_latest_period=source_latest,
        latest_observation=observed,
        notes=notes,
    )


def _localisation_check(root: Path, slug: str) -> CheckResult:
    en = _load_artifact(root, slug, "en")
    zh = _load_artifact(root, slug, "zh")
    en_snapshot = en.get("snapshot", {})
    zh_snapshot = zh.get("snapshot", {})
    en_generated = en_snapshot.get("generatedAt")
    zh_generated = zh_snapshot.get("generatedAt")
    en_datasets = en_snapshot.get("datasets", {})
    zh_datasets = zh_snapshot.get("datasets", {})
    en_counts = {
        dataset_id: len(rows) if isinstance(rows, list) else None
        for dataset_id, rows in en_datasets.items()
    }
    zh_counts = {
        dataset_id: len(rows) if isinstance(rows, list) else None
        for dataset_id, rows in zh_datasets.items()
    }
    healthy = (
        bool(en and zh)
        and en_generated == zh_generated
        and en_counts == zh_counts
    )
    return CheckResult(
        check_id=f"{slug}.localisation",
        sector=slug,
        dataset="artifact-en/zh",
        required=True,
        status="healthy" if healthy else "stale",
        expected_latest_period=str(en_generated) if en_generated else None,
        latest_observation=str(zh_generated) if zh_generated else None,
        notes=(
            "EN and ZH must describe the same generated snapshot, dataset IDs "
            "and per-dataset row counts."
        ),
    )


def audit_artifacts(
    artifact_root: Path,
    *,
    as_of: date,
    sectors: set[str] | None = None,
) -> dict[str, Any]:
    labour = _load_artifact(artifact_root, "hk-labour-market")
    local_consumer = _load_artifact(artifact_root, "hk-local-consumer")
    population = _load_artifact(artifact_root, "hk-population-migration")
    real_estate = _load_artifact(artifact_root, "hk-real-estate")
    transport = _load_artifact(artifact_root, "hk-transport")

    checks = [
        _period_check(
            artifact=labour,
            check_id="labour.unemployment",
            sector="hk-labour-market",
            dataset_id="labour_force_history",
            expected=expected_month(as_of, release_day=20),
            notes="C&SD rolling three-month labour-force release, normally published around day 20.",
        ),
        _period_check(
            artifact=labour,
            check_id="labour.earnings",
            sector="hk-labour-market",
            dataset_id="earnings_history",
            expected=expected_quarter(as_of, release_lag_days=61),
            grain="quarter",
            notes=(
                "C&SD industry/occupation median employment earnings come from the "
                "Quarterly General Household Survey report, normally released near "
                "the end of the second month after quarter-end."
            ),
        ),
        _period_check(
            artifact=labour,
            check_id="labour.vacancies",
            sector="hk-labour-market",
            dataset_id="vacancy_history",
            expected=expected_quarter(as_of, release_lag_days=79),
            grain="quarter",
            notes=(
                "C&SD persons-engaged and vacancy statistics are quarterly; the "
                "2026 calendar schedules Q2 for 18 September."
            ),
        ),
        _period_check(
            artifact=labour,
            check_id="labour.wages",
            sector="hk-labour-market",
            dataset_id="wage_yoy_history",
            expected=expected_quarter(as_of, release_lag_days=89),
            grain="quarter",
            notes=(
                "C&SD wage and payroll statistics are quarterly; the 2026 calendar "
                "schedules Q2 for 28 September."
            ),
        ),
        _period_check(
            artifact=local_consumer,
            check_id="local_consumer.retail",
            sector="hk-local-consumer",
            dataset_id="retail_history",
            expected=expected_month_by_lag(as_of, release_lag_days=35),
            notes="C&SD retail sales are monthly and normally release about 32-35 days after month-end.",
        ),
        _period_check(
            artifact=local_consumer,
            check_id="local_consumer.restaurant",
            sector="hk-local-consumer",
            dataset_id="restaurant_history",
            expected=expected_quarter(as_of, release_lag_days=35),
            grain="quarter",
            notes="C&SD restaurant receipts and purchases are quarterly.",
        ),
        _period_check(
            artifact=local_consumer,
            check_id="local_consumer.cpi",
            sector="hk-local-consumer",
            dataset_id="censtatd_cpi_headline_history",
            expected=expected_month_by_lag(as_of, release_lag_days=23),
            notes="C&SD CPI is monthly and normally releases about three weeks after month-end.",
        ),
        _date_check(
            artifact=local_consumer,
            check_id="local_consumer.immigration",
            sector="hk-local-consumer",
            dataset_id="kpi_northbound",
            expected=as_of - timedelta(days=2),
            fields=("observation_date", "date"),
            notes="Immigration passenger clearance is daily; allow a two-day publication/holiday lag.",
        ),
        _date_check(
            artifact=local_consumer,
            check_id="local_consumer.oilprice",
            sector="hk-local-consumer",
            dataset_id="consumer_council_oilprice",
            expected=as_of - timedelta(days=2),
            notes="Consumer Council pump-price snapshot is fetched daily; allow a two-day publication lag.",
        ),
        _period_check(
            artifact=population,
            check_id="population.mpfa",
            sector="hk-population-migration",
            dataset_id="mpfa_claims",
            expected=expected_quarter(as_of, release_lag_days=49),
            grain="quarter",
            notes="MPFA Statistical Digest is quarterly and normally arrives within roughly 49 days.",
        ),
        _dataset_alignment_check(
            artifact=real_estate,
            check_id="real_estate.bd_history",
            sector="hk-real-estate",
            source_dataset="bd_monthly_stats",
            dependent_datasets=(
                "bd_supply_pipeline_history_units",
                "bd_supply_pipeline_history_counts",
            ),
            notes="Md54/Md55/Md56 history must include the latest parsed Buildings Department digest.",
        ),
        _period_check(
            artifact=real_estate,
            check_id="real_estate.hkma_mortgage",
            sector="hk-real-estate",
            dataset_id="hkma_applications_history",
            expected=expected_month_by_lag(as_of, release_lag_days=60),
            notes="HKMA residential mortgage survey is monthly; a conservative two-month release gate is applied.",
        ),
        _period_check(
            artifact=transport,
            check_id="transport.china_airlines",
            sector="hk-transport",
            dataset_id="china_airline_passengers_history",
            expected=expected_month(as_of, release_day=20),
            notes="Listed airlines normally publish the prior month's operating bulletin before day 20.",
        ),
    ]
    for slug in (
        "market-monitor",
        "hk-labour-market",
        "hk-local-consumer",
        "hk-population-migration",
        "hk-real-estate",
        "hk-transport",
        "hk-commercial-aerospace",
        "hk-stablecoin-crypto",
    ):
        checks.append(_localisation_check(artifact_root, slug))
    if sectors:
        checks = [result for result in checks if result.sector in sectors]

    required_failures = [
        result.check_id
        for result in checks
        if result.required and result.status != "healthy"
    ]
    return {
        "version": "asia-markets-freshness.v1",
        "auditedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "asOf": as_of.isoformat(),
        "status": "healthy" if not required_failures else "degraded",
        "requiredFailures": required_failures,
        "checks": [asdict(result) for result in checks],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument(
        "--sector",
        action="append",
        dest="sectors",
        help="Restrict enforcement to one or more sector IDs (repeatable).",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Write the report without failing when required checks are stale.",
    )
    args = parser.parse_args()

    report = audit_artifacts(
        args.artifact_root,
        as_of=args.as_of,
        sectors=set(args.sectors or []) or None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if args.report_only or report["status"] == "healthy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
