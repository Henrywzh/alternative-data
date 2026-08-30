from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.hk_labour_market import pipeline
from src.hk_labour_market.quality import validate_frame, validate_policy_frame
from src.hk_labour_market.source_registry import CORE_CENSTATD_TABLES
from src.hk_labour_market.sources import censtatd
from src.hk_labour_market.sources.censtatd import fetch_censtatd_table, normalize_censtatd_table
from src.hk_labour_market.sources.labour_department import ESLS_SOURCE_ID


def test_labour_earnings_history_rows_are_globally_chronological_for_portable_charts():
    """Long-form chart input must keep the shared renderer's x-axis chronological.

    The portable renderer first pivots long-form rows by first-seen x value.  If
    rows are grouped by series before date, staggered series start dates append
    earlier months at the far right of the chart.
    """
    artifact_path = (
        Path(__file__).resolve().parents[1]
        / "apps"
        / "asia-markets-dashboard"
        / ".generated"
        / "hk-labour-market-artifact.json"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    datasets = artifact["snapshot"]["datasets"]

    for dataset_id in ("earnings_industry_history", "occupation_earnings_history"):
        rows = datasets[dataset_id]
        # Duplicate months are expected because the payload is long-form.  The
        # renderer's pivot uses the first-seen order of unique x values.
        months = list(dict.fromkeys(row["month"] for row in rows))
        assert months == sorted(months), f"{dataset_id} x-axis months are not chronological"


def _payload() -> dict:
    return {
        "header": {"status": {"name": "Success"}, "title": "Example C&SD table"},
        "dataSet": [
            {
                "IND": "", "INDDesc": "Total", "freq": "Q", "period": "202603",
                "sv": "VAC", "svDesc": "No.", "figure": 48610, "sd_value": "p",
            },
            {
                "IND": "ind_K", "INDDesc": "Financial and insurance activities", "freq": "Q",
                "period": "202603", "sv": "VAC", "svDesc": "No.", "figure": 4900, "sd_value": "",
            },
            {
                "IND": "", "INDDesc": "Total", "freq": "Q", "period": "202603",
                "sv": "VAC", "svDesc": "Year-on-year % change", "figure": -11.9, "sd_value": "",
            },
        ],
    }


def test_normalize_preserves_period_dimensions_and_status_flags():
    spec = next(item for item in CORE_CENSTATD_TABLES if item.table_id == "215-16001")
    frame = normalize_censtatd_table(_payload(), spec)
    assert frame["period_end"].tolist() == ["2026-03-31", "2026-03-31", "2026-03-31"]
    assert frame["frequency_label"].tolist() == ["quarterly", "quarterly", "quarterly"]
    assert frame.loc[1, "industry"] == "Financial and insurance activities"
    assert frame.loc[0, "status_flag"] == "p"
    assert frame.loc[0, "value"] == 48610.0


def test_censtatd_fetch_retries_transient_incomplete_response(monkeypatch):
    spec = next(item for item in CORE_CENSTATD_TABLES if item.table_id == "215-16001")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return _payload()

    class Session:
        def __init__(self):
            self.calls = 0

        def get(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise censtatd.requests.exceptions.ChunkedEncodingError("incomplete response")
            return Response()

    session = Session()
    monkeypatch.setattr(censtatd.time, "sleep", lambda _: None)

    payload, frame = fetch_censtatd_table(spec, session=session, attempts=2)

    assert session.calls == 2
    assert payload["header"]["status"]["name"] == "Success"
    assert len(frame) == 3


def test_validate_allows_provisional_values_but_rejects_duplicate_source_rows():
    spec = next(item for item in CORE_CENSTATD_TABLES if item.table_id == "215-16001")
    frame = normalize_censtatd_table(_payload(), spec)
    assert validate_frame(frame, spec) == []
    duplicated = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    assert validate_frame(duplicated, spec) == ["contains duplicate source observations for its natural key"]


def test_invalid_response_is_snapshotted_before_quality_rejection(monkeypatch, tmp_path):
    spec = next(item for item in CORE_CENSTATD_TABLES if item.table_id == "215-16001")
    frame = normalize_censtatd_table(_payload(), spec)
    invalid = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    raw_path = tmp_path / "provider-response.json"
    calls = []

    monkeypatch.setattr(pipeline, "fetch_censtatd_table", lambda _: (_payload(), invalid))
    monkeypatch.setattr(
        pipeline,
        "save_raw_snapshot",
        lambda *args, **kwargs: calls.append((args, kwargs)) or raw_path,
    )
    monkeypatch.setattr(
        pipeline,
        "save_normalized_dataset",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("invalid data must not be persisted")),
    )

    result = pipeline._ingest_table("test-run", spec)
    assert result["status"] == "invalid"
    assert result["raw_snapshot"] == str(raw_path)
    assert len(calls) == 1


def test_malformed_success_response_is_snapshotted_before_normalization_error(monkeypatch, tmp_path):
    from src.hk_labour_market.sources.censtatd import CenstatdFetchError

    spec = next(item for item in CORE_CENSTATD_TABLES if item.table_id == "215-16001")
    raw_path = tmp_path / "malformed-provider-response.json"
    calls = []
    monkeypatch.setattr(
        pipeline,
        "fetch_censtatd_table",
        lambda _: (_ for _ in ()).throw(CenstatdFetchError("provider returned an empty dataSet", payload={"header": {"status": {"name": "Success"}}})),
    )
    monkeypatch.setattr(
        pipeline,
        "save_raw_snapshot",
        lambda *args, **kwargs: calls.append((args, kwargs)) or raw_path,
    )
    result = pipeline._ingest_table("test-run", spec)
    assert result["status"] == "invalid"
    assert result["raw_snapshot"] == str(raw_path)
    assert len(calls) == 1


def test_unlisted_source_dimensions_are_preserved_in_the_observation_key():
    spec = next(item for item in CORE_CENSTATD_TABLES if item.table_id == "215-16001")
    payload = {
        "header": {"status": {"name": "Success"}, "title": "Establishment size example"},
        "dataSet": [
            {
                "IND": "ind_K", "INDDesc": "Financial and insurance activities",
                "MPS": "mps_1", "MPSDesc": "1-4", "freq": "M", "period": "202603",
                "sv": "PE", "svDesc": "No.", "figure": 100, "sd_value": "",
            },
            {
                "IND": "ind_K", "INDDesc": "Financial and insurance activities",
                "MPS": "mps_2", "MPSDesc": "5-9", "freq": "M", "period": "202603",
                "sv": "PE", "svDesc": "No.", "figure": 200, "sd_value": "",
            },
        ],
    }
    frame = normalize_censtatd_table(payload, spec)
    assert validate_frame(frame, spec) == []


def test_main_industry_and_occupation_aliases_are_exposed_for_specialized_tables():
    industry_spec = next(item for item in CORE_CENSTATD_TABLES if item.table_id == "210-06316")
    occupation_spec = next(item for item in CORE_CENSTATD_TABLES if item.table_id == "210-06317")
    industry_payload = {
        "header": {"status": {"name": "Success"}},
        "dataSet": [{"MIND": 1, "MINDDesc": "Manufacturing", "SEX": "", "SEXDesc": "Total", "freq": "Y", "period": "2025", "sv": "M", "svDesc": "HK$", "figure": 18000, "sd_value": ""}],
    }
    occupation_payload = {
        "header": {"status": {"name": "Success"}},
        "dataSet": [{"MOCC": 1, "MOCCDesc": "Managers", "SEX": "", "SEXDesc": "Total", "freq": "Y", "period": "2025", "sv": "M", "svDesc": "HK$", "figure": 40000, "sd_value": ""}],
    }
    industry_frame = normalize_censtatd_table(industry_payload, industry_spec)
    occupation_frame = normalize_censtatd_table(occupation_payload, occupation_spec)
    assert industry_frame.loc[0, "industry"] == "Manufacturing"
    assert occupation_frame.loc[0, "occupation"] == "Managers"


def test_esls_xml_parser_normalizes_annual_application_counts(monkeypatch):
    from src.hk_labour_market.sources import labour_department

    class Response:
        text = "<data><item><year>2025</year><no_of_app>12214</no_of_app></item></data>"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(labour_department.requests, "get", lambda *args, **kwargs: Response())
    _, frame = labour_department.fetch_esls_key_statistics()
    assert frame.loc[0, "source_table_id"] == ESLS_SOURCE_ID
    assert frame.loc[0, "period_end"] == "2025-12-31"
    assert frame.loc[0, "value"] == 12214.0


def test_esls_malformed_success_payload_keeps_raw_body_for_pipeline_snapshot(monkeypatch):
    from src.hk_labour_market.sources import labour_department

    class Response:
        text = "<data><item>broken"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(labour_department.requests, "get", lambda *args, **kwargs: Response())
    try:
        labour_department.fetch_esls_key_statistics()
    except labour_department.LabourDepartmentFetchError as exc:
        assert exc.raw_body == "<data><item>broken"
    else:
        raise AssertionError("malformed XML should raise LabourDepartmentFetchError")


def test_immd_csv_parser_keeps_qmas_breakdown_columns_as_dimensions(monkeypatch):
    from src.hk_labour_market.sources import immigration_employment

    class Response:
        content = "Year,Financial Services,Total,备注\n2025.0,\"2,524\",\"7,101\",official\n".encode()

        def raise_for_status(self):
            return None

    monkeypatch.setattr(immigration_employment.requests, "get", lambda *args, **kwargs: Response())
    _, frame = immigration_employment.fetch_employment_policy_source(
        {
            "dataset_id": "immd_qmas_industry_annual",
            "source_table_id": "immd_qmas_industry",
            "scheme": "Quality Migrant Admission Scheme",
            "breakdown_type": "industry_sector",
            "source_title": "Annual quota allotted under Quality Migrant Admission Scheme by industry/sector",
            "url": "https://example.test/qmas.csv",
        }
    )
    assert set(frame["metric_code"]) == {"quota_allotted"}
    assert set(frame["dimension_label"]) == {"Financial Services", "Total"}
    assert set(frame["metric_label"]) == {"Quota allotted under Quality Migrant Admission Scheme"}
    assert frame["source_title"].iloc[0] == "Annual quota allotted under Quality Migrant Admission Scheme by industry/sector"
    assert frame["value"].tolist() == [2524.0, 7101.0]


def test_immd_malformed_csv_keeps_raw_body_for_pipeline_snapshot(monkeypatch):
    from src.hk_labour_market.sources import immigration_employment

    class Response:
        content = b"only-one-column\n"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(immigration_employment.requests, "get", lambda *args, **kwargs: Response())
    try:
        immigration_employment.fetch_employment_policy_source(
            {
                "dataset_id": "immd_gep_applications_annual",
                "source_table_id": "immd_gep_applications",
                "scheme": "General Employment Policy",
                "source_title": "Applications received and approved under General Employment Policy",
                "url": "https://example.test/gep.csv",
            }
        )
    except immigration_employment.ImmigrationEmploymentFetchError as exc:
        assert exc.raw_body == "only-one-column\n"
    else:
        raise AssertionError("malformed CSV should raise ImmigrationEmploymentFetchError")


def test_policy_quality_gate_uses_full_source_natural_key_and_rejects_negative_counts(monkeypatch):
    from src.hk_labour_market.sources import immigration_employment

    class Response:
        content = "Year,Applications received,Applications approved\n2025,10,8\n".encode()

        def raise_for_status(self):
            return None

    monkeypatch.setattr(immigration_employment.requests, "get", lambda *args, **kwargs: Response())
    _, frame = immigration_employment.fetch_employment_policy_source(
        {
            "dataset_id": "immd_gep_applications_annual",
            "source_table_id": "immd_gep_applications",
            "scheme": "General Employment Policy",
            "source_title": "Applications received and approved under General Employment Policy",
            "url": "https://example.test/gep.csv",
        }
    )
    assert validate_policy_frame(frame) == []
    assert validate_policy_frame(frame, expected_source_table_id="unexpected_source") == [
        "policy source table identity does not match unexpected_source"
    ]
    duplicated = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    assert validate_policy_frame(duplicated) == ["contains duplicate policy observations for its natural key"]
    negative = frame.copy()
    negative.loc[0, "value"] = -1
    assert validate_policy_frame(negative) == ["policy frame contains negative counts"]


def test_run_update_rebuilds_marts_and_runs_audit_after_all_stages_succeed(monkeypatch):
    success = lambda **kwargs: {"results": {"dataset": {"status": "success"}}}
    monkeypatch.setattr(pipeline, "run_stage_1_pipeline", success)
    monkeypatch.setattr(pipeline, "run_stage_2_pipeline", success)
    monkeypatch.setattr(pipeline, "run_stage_3_pipeline", success)
    monkeypatch.setattr(pipeline, "run_stage_4_pipeline", success)

    from src.hk_labour_market import audit, marts

    monkeypatch.setattr(marts, "build_analysis_marts", lambda: {"marts": {}})
    monkeypatch.setattr(audit, "run_labour_market_audit", lambda: {"status": "pass", "errors": []})
    result = pipeline.run_update_pipeline()
    assert result["marts"] == {"marts": {}}
    assert result["audit"]["status"] == "pass"


def test_run_update_rebuilds_marts_when_only_optional_stage_two_fails(monkeypatch):
    success = lambda **kwargs: {"results": {"dataset": {"status": "success"}}}
    failure = lambda **kwargs: {"results": {"dataset": {"status": "error"}}}
    monkeypatch.setattr(pipeline, "run_stage_1_pipeline", success)
    monkeypatch.setattr(pipeline, "run_stage_2_pipeline", failure)
    monkeypatch.setattr(pipeline, "run_stage_3_pipeline", success)
    monkeypatch.setattr(pipeline, "run_stage_4_pipeline", success)

    from src.hk_labour_market import audit, marts

    monkeypatch.setattr(marts, "build_analysis_marts", lambda: {"marts": {}})
    monkeypatch.setattr(
        audit,
        "run_labour_market_audit",
        lambda: {"status": "fail", "errors": ["optional Stage 2 source failed"]},
    )

    result = pipeline.run_update_pipeline()

    assert result["marts"] == {"marts": {}}
    assert result["stage_success"]["stage_2"] is False
    assert result["audit"]["status"] == "fail"
