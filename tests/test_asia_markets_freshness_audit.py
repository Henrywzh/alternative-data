from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_asia_markets_freshness.py"
SPEC = importlib.util.spec_from_file_location("asia_markets_freshness_audit", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _write_artifact(
    root: Path,
    slug: str,
    datasets: dict[str, list[dict]],
    *,
    language: str = "en",
    generated_at: str = "2026-08-30T00:00:00Z",
) -> None:
    suffix = "" if language == "en" else f"-{language}"
    payload = {
        "manifest": {"dataAsOf": "2026-08-30"},
        "snapshot": {
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": datasets,
        },
    }
    (root / f"{slug}-artifact{suffix}.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def _write_pair(root: Path, slug: str, datasets: dict[str, list[dict]]) -> None:
    _write_artifact(root, slug, datasets)
    _write_artifact(root, slug, datasets, language="zh")


def _healthy_artifact_root(tmp_path: Path) -> Path:
    root = tmp_path / ".generated"
    root.mkdir()
    _write_pair(
        root,
        "hk-labour-market",
        {
            "labour_force_history": [{"date": "2026-07-31"}],
            "earnings_history": [{"date": "2026-06-30"}],
            "vacancy_history": [{"date": "2026-03-31"}],
            "wage_yoy_history": [{"date": "2026-03-31"}],
        },
    )
    _write_pair(
        root,
        "hk-population-migration",
        {"mpfa_claims": [{"quarter": "2026-Q2"}]},
    )
    _write_pair(
        root,
        "hk-local-consumer",
        {
            "retail_history": [{"date": "2026-06-30"}],
            "restaurant_history": [{"date": "2026-06-30"}],
            "censtatd_cpi_headline_history": [{"date": "2026-07"}],
            "kpi_northbound": [{"observation_date": "2026-08-29"}],
            "consumer_council_oilprice": [{"date": "2026-08-30"}],
        },
    )
    _write_pair(
        root,
        "hk-real-estate",
        {
            "bd_monthly_stats": [{"date": "2026-06-01"}],
            "bd_supply_pipeline_history_units": [{"date": "2026-06"}],
            "bd_supply_pipeline_history_counts": [{"date": "2026-06"}],
            "hkma_applications_history": [{"date": "2026-06"}],
        },
    )
    _write_pair(
        root,
        "hk-transport",
        {
            "china_airline_passengers_history": [{"month": "2026-07"}],
            "mtr_history": [{"month": "2026-06"}],
        },
    )
    for slug in ("market-monitor", "hk-commercial-aerospace", "hk-stablecoin-crypto"):
        _write_pair(root, slug, {"history": [{"date": "2026-08-29"}]})
    return root


def test_expected_periods_respect_release_lags() -> None:
    assert MODULE.expected_month(date(2026, 8, 19), release_day=20) == "2026-06"
    assert MODULE.expected_month(date(2026, 8, 20), release_day=20) == "2026-07"
    assert MODULE.expected_quarter(date(2026, 8, 17), release_lag_days=49) == "2026-Q1"
    assert MODULE.expected_quarter(date(2026, 8, 18), release_lag_days=49) == "2026-Q2"
    assert MODULE.expected_quarter(date(2026, 8, 30), release_lag_days=61) == "2026-Q2"
    assert MODULE.expected_quarter(date(2026, 8, 30), release_lag_days=79) == "2026-Q1"
    assert MODULE.expected_quarter(date(2026, 8, 30), release_lag_days=89) == "2026-Q1"
    assert MODULE.expected_month_by_lag(date(2026, 8, 30), release_lag_days=35) == "2026-06"
    assert MODULE.expected_month_by_lag(date(2026, 8, 31), release_lag_days=31) == "2026-07"
    assert MODULE.expected_month_by_lag(date(2026, 8, 31), release_lag_days=35) == "2026-06"
    assert MODULE.expected_month_by_lag(date(2026, 9, 4), release_lag_days=35) == "2026-07"


def test_audit_is_healthy_when_core_sources_and_localisations_align(tmp_path: Path) -> None:
    report = MODULE.audit_artifacts(
        _healthy_artifact_root(tmp_path),
        as_of=date(2026, 8, 30),
    )
    assert report["status"] == "healthy"
    assert report["requiredFailures"] == []


def test_audit_flags_stale_source_periods_and_localisation_drift(tmp_path: Path) -> None:
    root = _healthy_artifact_root(tmp_path)
    _write_artifact(
        root,
        "hk-labour-market",
        {
            "labour_force_history": [{"date": "2026-06-30"}],
            "earnings_history": [{"date": "2025-12-31"}],
            "vacancy_history": [{"date": "2025-12-31"}],
            "wage_yoy_history": [{"date": "2025-12-31"}],
        },
    )
    _write_artifact(
        root,
        "hk-population-migration",
        {"mpfa_claims": [{"quarter": "2026-Q1"}]},
    )
    _write_artifact(
        root,
        "hk-real-estate",
        {
            "bd_monthly_stats": [{"date": "2026-06-01"}],
            "bd_supply_pipeline_history_units": [{"date": "2026-05"}],
            "bd_supply_pipeline_history_counts": [{"date": "2026-05"}],
            "hkma_applications_history": [{"date": "2026-05"}],
        },
    )
    _write_artifact(
        root,
        "hk-transport",
        {
            "china_airline_passengers_history": [{"month": "2026-06"}],
            "mtr_history": [{"month": "2026-05"}],
        },
    )
    _write_artifact(
        root,
        "hk-commercial-aerospace",
        {"history": [{"date": "2026-08-23"}]},
        language="zh",
        generated_at="2026-08-08T00:00:00Z",
    )

    report = MODULE.audit_artifacts(root, as_of=date(2026, 8, 30))

    assert report["status"] == "degraded"
    assert {
        "labour.unemployment",
        "labour.earnings",
        "labour.vacancies",
        "labour.wages",
        "population.mpfa",
            "real_estate.bd_history",
        "real_estate.hkma_mortgage",
        "transport.china_airlines",
        "transport.mtr_patronage",
        "hk-commercial-aerospace.localisation",
    }.issubset(report["requiredFailures"])


def test_audit_flags_localisation_row_count_drift(tmp_path: Path) -> None:
    root = _healthy_artifact_root(tmp_path)
    _write_artifact(
        root,
        "hk-transport",
        {"china_airline_passengers_history": []},
        language="zh",
    )

    report = MODULE.audit_artifacts(
        root,
        as_of=date(2026, 8, 30),
        sectors={"hk-transport"},
    )

    assert report["status"] == "degraded"
    assert "hk-transport.localisation" in report["requiredFailures"]


def test_audit_can_enforce_one_sector_without_unrelated_failures(tmp_path: Path) -> None:
    root = _healthy_artifact_root(tmp_path)
    _write_artifact(
        root,
        "hk-labour-market",
        {
            "labour_force_history": [{"date": "2026-06-30"}],
            "earnings_history": [{"date": "2026-05-31"}],
            "vacancy_history": [{"date": "2026-03-31"}],
            "wage_yoy_history": [{"date": "2026-03-31"}],
        },
    )

    report = MODULE.audit_artifacts(
        root,
        as_of=date(2026, 8, 30),
        sectors={"hk-transport"},
    )

    assert report["status"] == "healthy"
    assert report["requiredFailures"] == []
    assert {check["sector"] for check in report["checks"]} == {"hk-transport"}
