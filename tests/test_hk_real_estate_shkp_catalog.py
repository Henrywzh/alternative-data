import json

from conftest import require_local_normalized

import pandas as pd

from src.hk_real_estate.cli import main as cli_main
from src.hk_real_estate.shkp_catalog import (
    SHKP_PRIORITY_PHASE_IDS,
    _build_historical_transaction_merge,
    _persist,
    run_shkp_catalog,
)
from src.hk_real_estate.sources import srpe
from src.hk_real_estate.sources.shkp import (
    build_shkp_historical_manifest_coverage_audit,
    build_shkp_historical_phase_evidence_coverage,
    build_shkp_indicative_ownership_roster,
    build_shkp_history_milestone_crosswalk,
    enrich_shkp_historical_phase_roster_manifest_coverage,
    fetch_shkp_history_milestones,
)


class _EmptySrpeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"code": 0, "resultData": {"total": 0, "list": []}}


def test_historical_transaction_merge_repairs_shifted_price_and_quarantines_missing_pasp():
    prior = pd.DataFrame(
        [
            {
                "srpe_development_id": "285",
                "development_id": "285",
                "development_name": "SHOUSON PEAK",
                "phase_name": "SHOUSON PEAK",
                "block_name": "17G Shouson Hill Road",
                "floor": "",
                "unit": "$228,420,000",
                "date_of_pasp": "2016-10-03",
                "date_of_asp": "2016-10-06",
                "date_of_asp_termination": None,
                "transaction_price_hkd": 1.0,
                "is_cancelled": False,
                "transaction_id": "compact-row",
                "project_id": "shkp-historical-srpe-285",
                "stock_code": "0016",
                "ownership_pct": 0.0,
                "ownership_attribution_ready": False,
                "sales_attribution_status": "blocked_phase_specific_interval",
            }
        ]
    )
    current = pd.DataFrame(
        [
            {
                "srpe_development_id": "gap",
                "development_id": "gap",
                "development_name": "DATE GAP",
                "phase_name": "DATE GAP",
                "block_name": "Tower 1",
                "floor": "10",
                "unit": "A",
                "date_of_pasp": None,
                "date_of_asp": "2026-01-10",
                "date_of_asp_termination": None,
                "transaction_price_hkd": 1_000_000.0,
                "is_cancelled": False,
                "transaction_id": "missing-pasp",
                "project_id": "shkp-historical-srpe-gap",
                "stock_code": "0016",
                "ownership_pct": 0.0,
                "ownership_attribution_ready": False,
                "sales_attribution_status": "blocked_phase_specific_interval",
            }
        ]
    )

    events, monthly, date_gaps = _build_historical_transaction_merge(
        prior,
        current,
        routed_phase_ids=["gap"],
    )

    repaired = events.loc[events["transaction_id"].eq("compact-row")].iloc[0]
    assert repaired["transaction_price_hkd"] == 228420000
    assert repaired["unit"] == ""
    assert repaired["parser_quality_status"] == "compact_row_price_shift_repaired"
    assert monthly["development_id"].tolist() == ["285"]
    assert monthly.iloc[0]["sales_value_gross_hkd"] == 228420000

    assert len(date_gaps) == 1
    gap = date_gaps.iloc[0]
    assert gap["date_gap_status"] == "pasp_missing_asp_observed"
    assert gap["date_gap_dataset_status"] == "quarantined_pasp_missing_asp_observed"
    assert not bool(gap["strict_signal_inclusion"])
    assert not bool(gap["asp_used_as_pasp"])
    assert "gap" not in set(monthly["development_id"])


def test_shkp_catalog_offline_audit_has_required_layers_and_keeps_gate_closed():
    # The offline audit walks the full SHKP catalog: 38 normalized datasets
    # that are pipeline outputs and are not tracked by git.
    require_local_normalized("shkp_property_catalog", "srpe_development_index")
    result = run_shkp_catalog(offline=True)

    assert result["mode"] == "offline"
    assert result["missing_datasets"] == []
    assert result["dataset_counts"]["srpe_development_index"] >= 500
    assert result["dataset_counts"]["shkp_future_project_identity_evidence"] >= 10
    if result["gate_status"] in {"usable", "usable_with_unscoped_source_inputs"}:
        # The legal-observation layer can grow as new dated evidence is
        # ingested; the invariant is that it is populated and the promotion
        # gate remains closed, not a hard-coded historical row count.
        assert result["ownership_observation_rows"] >= 18
        assert result["ownership_ready_observation_rows"] == 0
        assert result["priority_phase_count"] == len(SHKP_PRIORITY_PHASE_IDS)
        assert result["priority_phase_ready_count"] == 0
        assert set(result["priority_phase_gate"]) == set(SHKP_PRIORITY_PHASE_IDS)
        assert all(not row["ownership_attribution_ready"] for row in result["priority_phase_gate"].values())
    else:
        assert result["ownership_observation_rows"] is None
        assert result["diagnostic_gate"]["ownership_observation_rows"] >= 18


def test_history_milestones_parser_preserves_official_year_and_text(monkeypatch, tmp_path):
    class Response:
        content = b"fixture"
        text = '''
        <div class="year-projects" data-year="2025">
          <div class="project-block"><div class="project-image"><img alt="Hands over Alpha and Beta" src="/img/a.jpg"></div><div class="project-summary">Hands over Alpha and Beta</div></div>
        </div>
        <div class="year-projects" data-year="1972"><div class="project-block"><div class="project-summary">Founded</div></div></div>
        '''

        def raise_for_status(self):
            return None

    class Session:
        headers = {}

        def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(
        "src.hk_real_estate.sources.shkp.save_raw_snapshot",
        lambda *args, **kwargs: tmp_path / "history.html",
    )
    frame = fetch_shkp_history_milestones(session=Session())
    assert frame["milestone_year"].tolist() == [2025, 1972]
    assert frame.iloc[0]["milestone_summary"] == "Hands over Alpha and Beta"
    assert frame.iloc[0]["image_url"].endswith("/img/a.jpg")
    assert frame.attrs["lineage_metadata"]["phase_level_ownership_ready"] is False


def test_history_milestone_crosswalk_keeps_ambiguous_phase_candidates_review_only():
    milestones = __import__("pandas").DataFrame([
        {
            "milestone_id": "m1",
            "milestone_year": 2025,
            "project_label": "Cullinan Sky",
            "milestone_summary": "Hands over Cullinan Sky",
            "source_url": "https://www.shkp.com/en-US/about-us/history-and-milestones",
            "fetched_at": "2026-08-08T00:00:00Z",
        }
    ])
    srpe_index = __import__("pandas").DataFrame([
        {"development_id": "a", "development_name_en": "Cullinan Sky Development", "phase_name_en": "Cullinan Sky"},
        {"development_id": "b", "development_name_en": "Cullinan Sky Development", "phase_name_en": "Cullinan Sky"},
    ])
    frame = build_shkp_history_milestone_crosswalk(milestones, srpe_index)
    assert len(frame) == 2
    assert set(frame["match_status"]) == {"ambiguous"}
    assert set(frame["candidate_count"]) == {2}
    assert set(frame["ownership_promotion_status"]) == {"blocked_no_phase_specific_ownership_interval"}


def test_manifest_coverage_audit_distinguishes_no_register_from_unobserved():
    pandas = __import__("pandas")
    roster = pandas.DataFrame([
        {"srpe_development_id": "1", "development_name_en": "A", "phase_name_en": "P1", "active": "N", "universe_status": "review_required", "evidence_count": 1},
        {"srpe_development_id": "2", "development_name_en": "B", "phase_name_en": "P2", "active": "N", "universe_status": "not_observed", "evidence_count": 0},
    ])
    manifest = pandas.DataFrame([
        {"srpe_development_id": "1", "document_category": "price_list", "source_url": "srpe"},
    ])
    frame = build_shkp_historical_manifest_coverage_audit(roster, manifest)
    statuses = dict(zip(frame["srpe_development_id"], frame["manifest_status"]))
    assert statuses == {"1": "observed_no_register", "2": "not_observed"}


def test_historical_roster_exposes_manifest_layer_without_overwriting_live_status():
    pandas = __import__("pandas")
    roster = pandas.DataFrame([
        {
            "srpe_development_id": "1",
            "manifest_status": "live_loaded",
        },
        {
            "srpe_development_id": "2",
            "manifest_status": "not_loaded",
        },
    ])
    audit = pandas.DataFrame([
        {
            "srpe_development_id": "1",
            "manifest_status": "observed_register",
            "manifest_rows": 4,
            "register_rows": 1,
            "price_list_rows": 2,
            "sales_arrangement_rows": 1,
            "sales_brochure_rows": 0,
            "transaction_backfill_status": "transaction_register_available",
            "selection_scope": "inactive_historical_evidence",
            "source_urls_json": "[\"srpe\"]",
            "last_verified_at": "2026-08-08T00:00:00+00:00",
        }
    ])
    frame = enrich_shkp_historical_phase_roster_manifest_coverage(roster, audit)
    row_one = frame.set_index("srpe_development_id").loc["1"]
    row_two = frame.set_index("srpe_development_id").loc["2"]
    assert row_one["manifest_status"] == "live_loaded"
    assert row_one["historical_manifest_status"] == "observed_register"
    assert row_one["historical_register_rows"] == 1
    assert row_one["historical_transaction_backfill_status"] == "transaction_register_available"
    assert row_two["manifest_status"] == "not_loaded"
    assert row_two["historical_manifest_status"] == "not_audited"


def test_historical_phase_evidence_coverage_is_one_row_per_parent_phase():
    pandas = __import__("pandas")
    roster = pandas.DataFrame([
        {
            "registry_key": "srpe:1",
            "srpe_development_id": "1",
            "active": "N",
            "universe_status": "review_required",
            "universe_evidence_types": "shkp_annual_report",
            "evidence_count": 2,
            "ownership_status": "annual_numeric_unreconciled",
            "ownership_evidence_level": "numeric_snapshot_or_grouped_interest",
            "ownership_evidence_source_count": 1,
            "ownership_evidence_promotion_status": "blocked_numeric_snapshot_only",
            "ownership_next_evidence": "dated SPV interval",
            "ownership_interval_status": "blocked_effective_interval",
            "ownership_attribution_ready": False,
            "manifest_status": "not_loaded",
            "historical_manifest_status": "observed_register",
            "historical_manifest_rows": 4,
            "historical_register_rows": 1,
            "historical_price_list_rows": 2,
            "historical_sales_arrangement_rows": 1,
            "historical_sales_brochure_rows": 0,
            "historical_transaction_backfill_status": "transaction_register_available",
            "historical_manifest_selection_scope": "inactive_historical_evidence",
            "source_urls_json": "[\"https://example.test/evidence\"]",
            "last_verified_at": "2026-08-08T00:00:00Z",
        }
    ])
    frame = build_shkp_historical_phase_evidence_coverage(roster)
    assert len(frame) == 1
    assert frame.iloc[0]["srpe_development_id"] == "1"
    assert frame.iloc[0]["ownership_evidence_level"] == "numeric_snapshot_or_grouped_interest"
    assert frame.iloc[0]["historical_register_rows"] == 1


def test_indicative_ownership_layer_is_separate_from_strict_gate():
    pandas = __import__("pandas")
    roster = pandas.DataFrame([
        {
            "registry_key": "srpe:1",
            "srpe_development_id": "1",
            "development_name_en": "TEST DEVELOPMENT",
            "phase_name_en": "PHASE 1",
            "active": "Y",
            "universe_status": "current_candidate",
            "universe_evidence_types": "current_shkp_directory",
            "evidence_count": 3,
            "shkp_match_status": "matched",
            "annual_group_interest_raw": "100% owned",
            "annual_group_interest_pct": 100.0,
            "completion_schedule_group_interest_raw": None,
            "completion_schedule_group_interest_pct": None,
            "ownership_observed_pct": None,
            "curated_registry_ownership_pct": None,
            "ownership_status": "annual_numeric_unreconciled",
            "ownership_evidence_level": "numeric_snapshot_or_grouped_interest",
            "ownership_evidence_source_count": 2,
            "ownership_attribution_ready": False,
            "ownership_interval_status": "blocked_effective_interval",
            "source_urls_json": "[]",
            "last_verified_at": "2026-08-08T00:00:00Z",
        }
    ])
    frame = build_shkp_indicative_ownership_roster(roster)
    row = frame.iloc[0]
    assert row["indicative_owner_status"] == "likely_shkp_numeric_snapshot"
    assert row["indicative_ownership_pct"] == 100.0
    assert row["indicative_confidence"] == "high"
    assert row["indicative_sales_use_status"] == "indicative_numeric_only"
    assert not bool(row["strict_ownership_attribution_ready"])


def test_indicative_ownership_preserves_small_rounded_snapshot_variation():
    pandas = __import__("pandas")
    roster = pandas.DataFrame([
        {
            "registry_key": "srpe:7965",
            "srpe_development_id": "7965",
            "development_name_en": "KENNEDY 38",
            "phase_name_en": None,
            "active": "Y",
            "universe_status": "current_candidate",
            "universe_evidence_types": "current_shkp_directory",
            "evidence_count": 3,
            "shkp_match_status": "matched_needs_review",
            "annual_group_interest_raw": "53",
            "annual_group_interest_pct": 53.0,
            "completion_schedule_group_interest_raw": "53.3",
            "completion_schedule_group_interest_pct": 53.3,
            "ownership_observed_pct": None,
            "curated_registry_ownership_pct": None,
            "ownership_status": "annual_numeric_unreconciled",
            "ownership_evidence_level": "numeric_snapshot_or_grouped_interest",
            "ownership_evidence_source_count": 3,
            "ownership_attribution_ready": False,
            "ownership_interval_status": "blocked_effective_interval",
            "source_urls_json": "[]",
            "last_verified_at": "2026-08-08T00:00:00Z",
        }
    ])
    frame = build_shkp_indicative_ownership_roster(roster)
    row = frame.iloc[0]
    assert row["indicative_ownership_pct"] == 53.15
    assert row["indicative_ownership_pct_low"] == 53.0
    assert row["indicative_ownership_pct_high"] == 53.3
    assert row["indicative_numeric_consistency_status"] == "rounded_consistent_snapshots"
    assert row["indicative_sales_use_status"] == "indicative_numeric_only"
    assert not bool(row["strict_ownership_attribution_ready"])


def test_indicative_ownership_does_not_choose_large_snapshot_conflicts():
    pandas = __import__("pandas")
    roster = pandas.DataFrame([
        {
            "registry_key": "srpe:conflict",
            "srpe_development_id": "conflict",
            "development_name_en": "CONFLICT",
            "phase_name_en": "PHASE 1",
            "universe_status": "current_candidate",
            "universe_evidence_types": "annual_report|completion_schedule",
            "evidence_count": 2,
            "shkp_match_status": "matched_needs_review",
            "annual_group_interest_pct": 40.0,
            "completion_schedule_group_interest_pct": 60.0,
            "ownership_status": "annual_numeric_unreconciled",
            "ownership_evidence_level": "numeric_snapshot_or_grouped_interest",
            "ownership_evidence_source_count": 2,
            "ownership_attribution_ready": False,
            "source_urls_json": "[]",
        }
    ])
    row = build_shkp_indicative_ownership_roster(roster).iloc[0]
    assert pandas.isna(row["indicative_ownership_pct"])
    assert row["indicative_ownership_pct_low"] == 40.0
    assert row["indicative_ownership_pct_high"] == 60.0
    assert row["indicative_numeric_consistency_status"] == "conflicting_snapshots"
    assert row["indicative_sales_use_status"] == "indicative_numeric_conflict"
    assert not bool(row["strict_ownership_attribution_ready"])


def test_cli_exposes_shkp_catalog_offline(capsys):
    assert cli_main(["run-shkp-catalog", "--offline"]) is None
    output = capsys.readouterr().out
    payload = json.loads(output.split("completed:\n", 1)[1])
    assert payload["mode"] == "offline"
    assert payload["attribution_policy"].startswith("phase-specific effective interval")


def test_srpe_zero_row_response_is_not_accepted_as_a_refresh(monkeypatch, tmp_path):
    class Session:
        headers = {}

        def post(self, *args, **kwargs):
            return _EmptySrpeResponse()

    monkeypatch.setattr(srpe, "save_raw_snapshot", lambda *args, **kwargs: tmp_path / "empty.json")
    try:
        srpe.fetch_srpe_development_index(session=Session())
    except RuntimeError as exc:
        assert "zero rows" in str(exc)
    else:  # pragma: no cover - assertion keeps the no-empty-refresh contract explicit
        raise AssertionError("zero-row SRPE response was accepted")


def test_empty_catalog_layer_is_not_persisted_as_latest_snapshot():
    stored = {}
    _persist({"example": __import__("pandas").DataFrame()}, "example", "test-run", stored)
    assert stored["example"]["skipped"] is True
    assert "previous valid snapshot retained" in stored["example"]["reason"]


def test_historical_transaction_backfill_phase_ids_validation(monkeypatch):
    """Explicit phase routing reuses the same backfill and rejects unknown ids."""
    import src.hk_real_estate.shkp_catalog as catalog

    roster = pd.DataFrame(
        [
            {
                "srpe_development_id": "7305",
                "development_name_en": "ARBOUR",
                "phase_name_en": "ARBOUR",
                "phase_no": "",
                "address_en": "1 FULKERS ROAD",
                "official_website": "https://example.com/arbour",
                "active": "Y",
                "evidence_count": 2,
            },
            {
                "srpe_development_id": "7805",
                "development_name_en": "CENTRAL PEAK DEVELOPMENT",
                "phase_name_en": "CENTRAL PEAK II",
                "phase_no": "",
                "address_en": "",
                "official_website": None,
                "active": "Y",
                "evidence_count": 1,
            },
        ]
    )
    manifest = pd.DataFrame(
        [
            {
                "srpe_development_id": "1111",
                "development_name": "SOME OLD PHASE",
                "document_category": "register_of_transactions",
                "document_id": "doc-1",
                "serial_no": "1",
                "date_of_printing": "2020-01-01",
                "submission_time": "2020-01-02",
            }
        ]
    )

    def fake_load(dataset_name: str) -> pd.DataFrame:
        if dataset_name == "shkp_historical_srpe_document_manifest":
            return manifest
        if dataset_name == "shkp_historical_phase_roster":
            return roster
        raise AssertionError(f"unexpected dataset load: {dataset_name}")

    monkeypatch.setattr(catalog, "load_latest_normalized", fake_load)
    monkeypatch.setattr(
        catalog,
        "_load_all_non_empty_snapshots",
        lambda dataset_name: pd.DataFrame(),
    )
    monkeypatch.setattr(catalog, "save_raw_snapshot", lambda *args, **kwargs: "raw.csv")

    # Unknown phase id must be rejected up front (no network call).
    try:
        catalog.run_shkp_historical_transaction_backfill(
            phase_ids=["9999"],
            max_phases=2,
            timeout=5,
            request_delay=0,
        )
        raise AssertionError("expected ValueError for unknown phase id")
    except ValueError as exc:
        assert "9999" in str(exc)
