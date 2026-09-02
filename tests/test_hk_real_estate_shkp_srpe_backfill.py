import pandas as pd

from src.hk_real_estate.shkp_srpe_backfill import (
    SHKP_PHASE_CANDIDATE_COLUMNS,
    SHKP_PHASE_RENDERED_SITE_EVIDENCE_COLUMNS,
    SHKP_PHASE_SITE_EVIDENCE_COLUMNS,
    _extract_field,
    _extract_role_fields,
    _extract_role_fields_from_html,
    build_shkp_phase_candidates,
    build_shkp_transaction_scratch_registry,
    classify_srpe_lifecycle,
    fetch_shkp_phase_site_evidence_rendered,
    select_recent_shkp_phase_candidates,
)


def test_site_role_extractor_requires_statutory_field_boundary():
    text = (
        "Details of the sales agent are available below. "
        "Vendor: Ease Gold Development Limited | "
        "Sales Agent: Sun Hung Kai Real Estate Agency Limited | "
        "Holding Companies: Sun Hung Kai Properties Limited"
    )
    assert _extract_field(text, ("Vendor",)) == "Ease Gold Development Limited"
    assert _extract_field(text, ("Sales Agent", "Sales Agents")) == "Sun Hung Kai Real Estate Agency Limited"
    assert _extract_field(text, ("Holding Companies", "Holding Company")) == "Sun Hung Kai Properties Limited"


def test_site_role_extractor_handles_vendor_holding_label_and_full_width_pipe():
    text = (
        "Vendor: Channel First Limited ｜ "
        "Holding companies of the Vendor: Elisford Limited, Sun Hung Kai Properties Limited ｜ "
        "Sales Agent: Sun Hung Kai Real Estate Agency Limited"
    )
    assert _extract_role_fields(text) == (
        "Channel First Limited",
        "Sun Hung Kai Real Estate Agency Limited",
        "Elisford Limited, Sun Hung Kai Properties Limited",
    )


def test_site_role_extractor_does_not_turn_empty_sales_agent_into_disclaimer():
    text = (
        "Sales Agent : To the extent this website constitutes an advertisement, "
        "this notice shall apply. District: Kennedy Town"
    )
    assert _extract_role_fields(text)[1] is None


def test_html_role_extractor_drops_markup_from_statutory_values():
    html = """
    <div>Holding companies of the Vendor: Sharberg Holdings Limited,<br>
    Sun Hung Kai Properties Limited</div>
    """
    assert _extract_role_fields_from_html(html)[2] == (
        "Sharberg Holdings Limited, Sun Hung Kai Properties Limited"
    )


def test_candidate_builder_keeps_direct_annual_and_identity_evidence():
    srpe = pd.DataFrame([
        {
            "development_id": "1",
            "development_name_en": "CULLINAN",
            "phase_name_en": "PHASE 1",
            "phase_no": "1",
            "address_en": "1 TEST ROAD",
            "active": "Y",
            "official_website": "www.example.com",
        },
        {
            "development_id": "2",
            "development_name_en": "FUTURE",
            "phase_name_en": "PHASE 1",
            "phase_no": "1",
            "address_en": "2 TEST ROAD",
            "active": "N",
            "official_website": "www.future.example",
        },
    ])
    direct = pd.DataFrame([
        {"srpe_development_id": "1", "marketing_name": "Cullinan", "match_status": "matched"},
    ])
    annual = pd.DataFrame([
        {"srpe_development_id": "2", "project_label": "Future", "match_status": "matched_needs_review"},
    ])
    identity = pd.DataFrame(columns=["srpe_development_id", "canonical_identity_status"])
    result = build_shkp_phase_candidates(srpe, direct, annual, identity)
    assert list(result.columns) == SHKP_PHASE_CANDIDATE_COLUMNS
    assert result["srpe_development_id"].tolist() == ["1", "2"]
    assert result["candidate_tier"].tolist() == ["tier_1", "tier_3"]


def test_site_evidence_schema_is_explicit():
    assert "sales_agent" in SHKP_PHASE_SITE_EVIDENCE_COLUMNS
    assert "holding_companies" in SHKP_PHASE_SITE_EVIDENCE_COLUMNS
    assert "raw_snapshot_path" in SHKP_PHASE_SITE_EVIDENCE_COLUMNS
    assert SHKP_PHASE_RENDERED_SITE_EVIDENCE_COLUMNS == SHKP_PHASE_SITE_EVIDENCE_COLUMNS


def test_rendered_probe_is_bounded_and_preserves_no_website_rows():
    candidates = pd.DataFrame(
        [
            {
                "srpe_development_id": "10",
                "development_name_en": "TEST",
                "phase_name_en": "PHASE 1",
                "official_website": None,
            }
        ]
    )
    result = fetch_shkp_phase_site_evidence_rendered(candidates, max_phases=1)
    assert list(result.columns) == SHKP_PHASE_RENDERED_SITE_EVIDENCE_COLUMNS
    assert len(result) == 1
    assert result.loc[0, "fetch_status"] == "rendered_no_official_website"
    assert result.loc[0, "caveat"].startswith("Browser-rendered")


def test_transaction_scratch_registry_is_routing_only():
    candidates = pd.DataFrame(
        [
            {
                "srpe_development_id": "10",
                "development_name_en": "TEST",
                "phase_name_en": "PHASE 1",
                "phase_no": "1",
                "address_en": "1 TEST ROAD",
                "candidate_status": "matched",
                "official_website": "www.test.example",
            },
            {
                "srpe_development_id": "11",
                "development_name_en": "REVIEW",
                "phase_name_en": "PHASE 1",
                "phase_no": "1",
                "address_en": "2 TEST ROAD",
                "candidate_status": "matched_needs_review",
                "official_website": "www.review.example",
            },
        ]
    )
    result = build_shkp_transaction_scratch_registry(candidates)
    assert result["project_id"].tolist() == ["shkp-srpe-10"]
    assert result["stock_code"].tolist() == ["0016"]
    assert result["ownership_pct"].tolist() == [0.0]
    assert result["ownership_attribution_ready"].tolist() == [False]


def test_srpe_lifecycle_classification_separates_active_suspended_and_completed():
    assert classify_srpe_lifecycle({"active": "Y"}) == "active"
    assert classify_srpe_lifecycle({"active": "N", "srpe_date_suspend_sales": "2025-02-01"}) == "suspended"
    assert classify_srpe_lifecycle({"active": "N", "srpe_date_complete_sales": "2025-03-01"}) == "completed"
    assert classify_srpe_lifecycle({"active": "N"}) == "inactive"


def test_recent_phase_selector_excludes_old_and_terminal_phases():
    candidates = pd.DataFrame(
        [
            {
                "srpe_development_id": "active-doc",
                "active": "Y",
                "srpe_earliest_publication": "2020-01-01",
                "candidate_status": "matched",
            },
            {
                "srpe_development_id": "active-new",
                "active": "Y",
                "srpe_earliest_publication": "2026-07-01",
                "candidate_status": "matched",
            },
            {
                "srpe_development_id": "active-old",
                "active": "Y",
                "srpe_earliest_publication": "2020-01-01",
                "candidate_status": "matched",
            },
            {
                "srpe_development_id": "suspended",
                "active": "N",
                "srpe_date_suspend_sales": "2026-08-01",
                "candidate_status": "matched",
            },
            {
                "srpe_development_id": "completed",
                "active": "N",
                "srpe_date_complete_sales": "2026-08-01",
                "candidate_status": "matched",
            },
        ]
    )
    documents = pd.DataFrame(
        [
            {
                "srpe_development_id": "active-doc",
                "document_category": "register_of_transactions",
                "submission_time": "2026-08-20T10:00:00+08:00",
                "date_of_printing": None,
            },
            {
                "srpe_development_id": "suspended",
                "document_category": "register_of_transactions",
                "submission_time": "2026-08-20T10:00:00+08:00",
                "date_of_printing": None,
            },
        ]
    )
    result = select_recent_shkp_phase_candidates(
        candidates,
        documents,
        now=pd.Timestamp("2026-08-24", tz="UTC"),
        recent_days=90,
        recent_years=2,
    )
    assert result["srpe_development_id"].tolist() == ["active-doc", "active-new"]
    assert result["lifecycle_status"].tolist() == ["active", "active"]
    assert result["recent_phase_reason"].tolist() == ["recent_document", "recent_publication"]


def test_recent_phase_selector_can_explicitly_include_older_active_for_audit():
    candidates = pd.DataFrame(
        [
            {"srpe_development_id": "old-active", "active": "Y", "candidate_status": "matched"},
            {"srpe_development_id": "suspended", "active": "N", "srpe_date_suspend_sales": "2025-01-01", "candidate_status": "matched"},
        ]
    )
    result = select_recent_shkp_phase_candidates(
        candidates,
        now=pd.Timestamp("2026-08-24", tz="UTC"),
        include_older_active=True,
    )
    assert result["srpe_development_id"].tolist() == ["old-active"]
