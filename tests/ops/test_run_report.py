from __future__ import annotations

import json
from pathlib import Path

import pytest

from ops_control.models import (
    CheckResult,
    Evidence,
    OutputObservation,
    RunReport,
)
from ops_control.schema import RunReportSchemaError, validate_run_report


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "ops" / "run-report.schema.json"


def _report() -> RunReport:
    return RunReport(
        pipeline_id="openrouter-provider-activity",
        job_id="scrape-provider-activity",
        workflow="OpenRouter Provider Activity Daily",
        run_id="123456",
        run_attempt=1,
        commit_sha="a" * 40,
        started_at=None,
        finished_at="2026-09-08T02:00:00Z",
        execution="success",
        collection="complete",
        data_health="fresh",
        publication="published",
        evidence_quality="verified",
        derived_state="HEALTHY",
        checks=[
            CheckResult(
                check_id="provider-activity.contract",
                status="healthy",
                required=True,
                message="Dataset contract satisfied.",
            )
        ],
        outputs=[
            OutputObservation(
                output_id="provider-daily-activity",
                path="data/normalized/openrouter/provider_daily_activity.parquet",
                required=True,
                exists=True,
                size_bytes=42,
                row_count=2,
                latest_observation="2026-09-07",
            )
        ],
        evidence=[
            Evidence(
                kind="dataset",
                path="data/normalized/openrouter/provider_daily_activity.parquet",
                observed_at="2026-09-08T02:00:00Z",
                description="Observed required output.",
            )
        ],
        shadow=True,
    )


def test_run_report_round_trips_and_validates_against_json_schema() -> None:
    payload = _report().to_dict()

    validate_run_report(payload, SCHEMA_PATH)
    restored = RunReport.from_dict(json.loads(json.dumps(payload)))

    assert restored == _report()


def test_schema_rejects_an_unknown_health_value() -> None:
    payload = _report().to_dict()
    payload["data_health"] = "probably_fine"

    with pytest.raises(RunReportSchemaError, match="data_health"):
        validate_run_report(payload, SCHEMA_PATH)


def test_schema_rejects_an_invalid_timestamp() -> None:
    payload = _report().to_dict()
    payload["finished_at"] = "not-a-timestamp"

    with pytest.raises(RunReportSchemaError, match="finished_at"):
        validate_run_report(payload, SCHEMA_PATH)
