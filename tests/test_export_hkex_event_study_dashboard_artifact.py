from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "export_hkex_event_study_dashboard_artifact.py"
SPEC = importlib.util.spec_from_file_location("export_hkex_event_study_dashboard_artifact", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _minimal_artifact() -> dict:
    required = {
        "coverage_summary", "direction_summary", "pit_summary", "pit_recovery_summary", "cluster_summary", "stock_summary",
        "stale_symbol_summary",
        "directional_horizon_summary", "event_returns", "event_robustness_summary",
        "event_stratified_summary", "event_gap_drift_summary", "event_native_1h_sensitivity",
        "event_direction_conflicts", "signal_registry", "source_health",
    }
    datasets = {name: [] for name in required}
    datasets["coverage_summary"] = [{"signal_gate_status": "blocked"}]
    return {
        "surface": "dashboard",
        "manifest": {
            "version": "hkex_event_study_artifact.v1",
            "charts": [
                {"id": "chart", "encodings": {"x": {"field": "x"}, "y": {"field": "y"}}}
            ],
            "tables": [],
        },
        "snapshot": {"status": "ready", "datasets": datasets},
        "package_info": {"researchOnly": True, "productionDatabaseModified": False},
    }


def test_validate_artifact_requires_research_only_blocked_contract():
    artifact = _minimal_artifact()
    MODULE.validate_artifact(artifact)
    artifact["snapshot"]["datasets"]["signal_registry"] = [
        {"registered_for_trading_signal": True}
    ]
    with pytest.raises(ValueError, match="registered trading signals"):
        MODULE.validate_artifact(artifact)


def test_direction_summary_keeps_review_rows_out_of_directional_efficacy():
    summary = MODULE._build_direction_summary(
        {"resolved_impact_direction_counts": {"positive": 2, "review_required": 1}},
        pd.DataFrame([{}, {}, {}]),
    )
    positive = summary.loc[summary["resolved_impact_direction"].eq("positive")].iloc[0]
    review = summary.loc[summary["resolved_impact_direction"].eq("review_required")].iloc[0]
    assert positive["dashboard_eligibility"] == "directional_efficacy_view"
    assert review["dashboard_eligibility"] == "context_or_review_only"


def test_pit_recovery_summary_isolated_from_event_study(tmp_path: Path):
    sidecar = tmp_path / "sidecar"
    sidecar.mkdir()
    (sidecar / "pit_recovery_manifest.json").write_text(
        json.dumps(
            {
                "version": "hkex_pit_recovery_sidecar.v1",
                "status": "ok",
                "recovered_legacy_rows": 1,
                "official_datetime_verified_rows": 1,
                "event_study_eligible_rows": 0,
                "production_database_modified": False,
            }
        )
    )
    pd.DataFrame(
        [{
            "url_continuity_ok": True,
            "official_timestamp_ok": True,
            "availability_delta_ok": True,
            "retrospective_collection_ok": True,
            "availability_delta_minutes": 10.0,
        }]
    ).to_parquet(sidecar / "pit_recovered_filings.parquet", index=False)
    summary = MODULE._build_pit_recovery_summary(sidecar)
    row = summary.iloc[0]
    assert row["sidecar_status"] == "ok"
    assert row["recovered_legacy_rows"] == 1
    assert row["event_study_eligible_rows"] == 0
    assert bool(row["event_study_eligible"]) is False
    assert row["isolation_status"] == "isolated_audit_sidecar"


def test_scope_mapping_keeps_candidate_pit_recovered_normalized():
    assert MODULE._scope_for(Path("outputs/hkex_event_study_candidates_pit_recovered")) == "candidate_pit_recovered"


def test_archive_provenance_distinguishes_single_and_merged_replays():
    coverage = {
        "archive_capture_id": "canonical-2",
        "archive_audit": {
            "intervals": {
                "5m": {"capture_records": [
                    {"capture_id": "canonical-1", "latest_bar_utc": "2026-08-07T08:05:00Z"},
                    {"capture_id": "canonical-2", "latest_bar_utc": "2026-08-10T08:05:00Z"},
                    {"capture_id": "candidate-1", "latest_bar_utc": "2026-08-10T08:05:00Z"},
                ]},
                "1h": {"capture_records": [
                    {"capture_id": "canonical-2", "latest_bar_utc": "2026-08-10T07:30:00Z"},
                ]},
            }
        },
    }
    single = MODULE._archive_provenance(coverage)
    assert single["archive_capture_ids"] == ["canonical-2"]
    assert single["archive_capture_scope"] == "single_capture"
    assert single["archive_market_cutoffs_by_interval"]["5m"] == ["2026-08-10T08:05:00Z"]
    assert single["distinct_market_cutoff_count_5m"] == 1
    assert single["distinct_market_cutoffs_1h"] == ["2026-08-10T07:30:00Z"]
    assert single["canonical_symbol_count"] == 0

    merged = MODULE._archive_provenance({"archive_audit": coverage["archive_audit"]})
    assert merged["archive_capture_scope"] == "merged_manifest_archive"
    assert merged["archive_capture_ids"] == ["candidate-1", "canonical-1", "canonical-2"]


def test_coverage_summary_exposes_5m_30m_and_1h_return_coverage():
    coverage = {
        "market_data_status_counts": {"covered": 2, "missing": 1},
        "event_row_return_coverage": {"5m": 2, "30m": 1, "1h": 1},
        "cluster_return_coverage": {"5m": 1, "30m": 1, "1h": 0},
        "bar_hole_event_rows": 1,
        "signal_registration_gate": {"status": "blocked", "reasons": []},
    }
    events = pd.DataFrame(
        {
            "is_type_cluster_representative": [True, False, True],
            "market_data_status": ["covered", "missing", "covered"],
            "signed_total_1h_abnormal_return": [0.01, None, None],
        }
    )
    row = MODULE._build_coverage_summary(coverage, events, "candidate_exploratory").iloc[0]
    assert row["event_return_coverage_5m"] == 2
    assert row["event_return_coverage_30m"] == 1
    assert row["event_return_coverage_1h"] == 1
    assert row["cluster_return_coverage_5m"] == 1
    assert row["cluster_return_coverage_30m"] == 1
    assert row["cluster_return_coverage_1h"] == 0
    assert row["bar_hole_event_rows"] == 1
