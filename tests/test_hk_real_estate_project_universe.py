import json

import pandas as pd
import pytest

from src.hk_real_estate.sources import shkp as shkp_source
from src.hk_real_estate.sources import srpe as srpe_source


def test_shkp_external_urls_preserve_http_https_and_multiple_links():
    fragment = (
        '<a href="https://novo.example/1">1</a>, '
        '<a href="http://novo.example/2">2</a>'
    )
    assert shkp_source._external_urls(fragment) == [
        "https://novo.example/1",
        "http://novo.example/2",
    ]


def test_shkp_normalization_keeps_project_site_lineage():
    rows = shkp_source._normalize_rows(
        [
            {
                "name": "NOVO LAND",
                "districtLabel": "New Territories",
                "src": "/sites/assets/novo.jpg",
                "langcode": '<a href="https://novoland.example">NOVO</a>',
            }
        ],
        config={"asset_type": "residential_for_sale", "subtype": "for_sale"},
        source_page_url="https://www.shkp.com/page",
        source_url="https://www.shkp.com/page/getList?page=0",
        page_number=0,
        fetched_at="2026-08-01T00:00:00+00:00",
    )
    assert rows[0]["marketing_name"] == "NOVO LAND"
    assert rows[0]["external_project_url"] == "https://novoland.example"
    assert json.loads(rows[0]["external_project_urls"]) == ["https://novoland.example"]
    assert rows[0]["source_record_id"] == "residential_for_sale:for_sale:0:1"


def test_shkp_principal_subsidiary_parser_keeps_wrapped_rows_together():
    def word(text, x0, top):
        return {"text": text, "x0": x0, "top": top, "x1": x0 + 8, "bottom": top + 8}

    words = [
        word("Principal", 56, 5),
        word("Subsidiaries", 135, 5),
        word("Name", 65, 20),
        word("Note", 232, 20),
        word("Company", 258, 20),
        word("(%)", 294, 20),
        word("Activities", 315, 20),
        word("Best", 65, 32),
        word("Vision", 87, 32),
        word("Development", 110, 32),
        word("Limited", 164, 32),
        word("100", 294, 32),
        word("Property", 315, 32),
        word("development", 344, 32),
        word("and", 315, 44),
        word("investment", 332, 44),
        word("Success", 65, 56),
        word("Keep", 98, 56),
        word("Limited", 119, 56),
        word("100", 294, 56),
        word("Property", 315, 56),
        word("development", 344, 56),
    ]

    rows = shkp_source._parse_shkp_principal_subsidiary_page_words(
        words,
        pdf_page=222,
        report_period_end="2024-06-30",
    )

    assert [row["spv_name"] for row in rows] == [
        "Best Vision Development Limited",
        "Success Keep Limited",
    ]
    assert rows[0]["attributable_equity_pct"] == 100.0
    assert rows[0]["business_description"] == "Property development and investment"


def test_shkp_principal_subsidiary_parser_accepts_continuation_page_without_title():
    def word(text, x0, top):
        return {"text": text, "x0": x0, "top": top, "x1": x0 + 8, "bottom": top + 8}

    rows = shkp_source._parse_shkp_principal_subsidiary_page_words(
        [
            word("Ease", 65, 10),
            word("Gold", 88, 10),
            word("Development", 110, 10),
            word("Limited", 165, 10),
            word("100", 294, 10),
            word("Property", 315, 10),
            word("development", 344, 10),
        ],
        pdf_page=219,
        report_period_end="2025-06-30",
        allow_continuation=True,
    )

    assert len(rows) == 1
    assert rows[0]["spv_name"] == "Ease Gold Development Limited"


def test_shkp_principal_subsidiary_parser_stops_at_table_footnotes():
    def word(text, x0, top):
        return {"text": text, "x0": x0, "top": top, "x1": x0 + 8, "bottom": top + 8}

    words = [
        word("Name", 65, 5),
        word("Company", 258, 5),
        word("(%)", 294, 5),
        word("Activities", 315, 5),
        word("Zarabanda", 65, 17),
        word("Company", 115, 17),
        word("Limited", 165, 17),
        word("100", 294, 17),
        word("Property", 315, 17),
        word("investment", 360, 17),
        # Footnotes can contain the same percentage column coordinates as a
        # row; they must not be parsed or appended to the last entity.
        word("Notes:", 65, 29),
        word("1.", 105, 29),
        word("Incorporated", 120, 29),
        word("Interest", 65, 41),
        word("rate", 100, 41),
        word("is", 125, 41),
        word("2.85%", 145, 41),
    ]

    rows = shkp_source._parse_shkp_principal_subsidiary_page_words(
        words,
        pdf_page=225,
        report_period_end="2024-06-30",
        allow_continuation=True,
    )

    assert [row["spv_name"] for row in rows] == ["Zarabanda Company Limited"]
    assert all("Notes" not in row["spv_name"] for row in rows)


def test_shkp_principal_subsidiary_crosswalk_only_uses_independent_phase_bridges():
    annual = pd.DataFrame([
        {
            "report_id": "ar-2024-25",
            "report_period_end": "2025-06-30",
            "as_of_date": "2025-06-30",
            "spv_name": "Super Great Limited",
            "attributable_equity_pct": 100.0,
            "business_description": "Property development and investment",
            "pdf_page": 222,
            "printed_page": "220",
            "annual_document_url": "https://example/ar.pdf",
            "source_url": "https://example/ar.pdf",
        },
        {
            "report_id": "ar-2024-25",
            "report_period_end": "2025-06-30",
            "as_of_date": "2025-06-30",
            "spv_name": "Unmapped Future SPV Limited",
            "attributable_equity_pct": 100.0,
            "business_description": "Property development",
            "pdf_page": 222,
            "printed_page": "220",
            "annual_document_url": "https://example/ar.pdf",
            "source_url": "https://example/ar.pdf",
        },
    ])
    legal = pd.DataFrame([
        {
            "srpe_development_id": "9366",
            "srpe_development_name": "CULLINAN SKY DEVELOPMENT",
            "srpe_phase_name": "CULLINAN SKY",
            "subsidiary_spv_name": "Super Great Limited",
            "ownership_pct": 100.0,
            "ownership_observed_as_of": "2025-06-30",
            "ownership_source_url": "https://example/legal.pdf",
            "ownership_source_page": "220",
            "promotion_status": "blocked_effective_interval",
            "caveat": "Snapshot only",
        }
    ])

    frame = shkp_source.build_shkp_annual_principal_subsidiary_crosswalk(
        annual,
        legal_ownership_observations=legal,
    )

    mapped = frame[frame["spv_name"].eq("Super Great Limited")].iloc[0]
    unmatched = frame[frame["spv_name"].eq("Unmapped Future SPV Limited")].iloc[0]
    assert mapped["srpe_development_id"] == "9366"
    assert mapped["match_status"] == "matched_legal_spv_phase_review_only"
    assert mapped["ownership_status"] == "snapshot_only_non_promoting"
    assert mapped["bridge_record_id"] == "exact_spv_name_to_legal_observation:supergreatlimited:9366"
    assert mapped["bridge_source_url"] == "https://example/legal.pdf"
    assert mapped["annual_observation_consistency_status"] == "date_and_pct_consistent"
    assert "https://example/ar.pdf" in mapped["source_urls_json"]
    assert pd.isna(unmatched["srpe_development_id"])
    assert unmatched["match_status"] == "unmatched_entity_only"
    assert unmatched["candidate_count"] == 0


def test_shkp_principal_subsidiary_crosswalk_marks_multi_phase_ambiguity():
    annual = pd.DataFrame([{
        "report_id": "ar-2024-25",
        "report_period_end": "2025-06-30",
        "as_of_date": "2025-06-30",
        "spv_name": "Well Capital (H.K.) Limited",
        "attributable_equity_pct": 100.0,
        "annual_document_url": "https://example/ar.pdf",
        "source_url": "https://example/ar.pdf",
    }])
    legal = pd.DataFrame([
        {
            "srpe_development_id": phase_id,
            "subsidiary_spv_name": "Well Capital (H.K.) Limited",
            "ownership_source_url": "https://example/legal.pdf",
        }
        for phase_id in ("9785", "10405", "11516")
    ])

    frame = shkp_source.build_shkp_annual_principal_subsidiary_crosswalk(
        annual,
        legal_ownership_observations=legal,
    )

    assert set(frame["srpe_development_id"]) == {"9785", "10405", "11516"}
    assert set(frame["candidate_count"]) == {3}
    assert set(frame["match_status"]) == {"matched_legal_spv_phase_group_ambiguous"}


def test_shkp_future_project_resolution_plan_keeps_unmatched_disclosures_operable():
    pipeline_registry = pd.DataFrame([
        {
            "pipeline_registry_key": "pipeline:artist-square",
            "disclosure_id": "interim",
            "project_label": "Artist Square Towers",
            "project_state": "under_development",
            "geography": "Kowloon",
            "source_url": "https://example/interim",
            "srpe_match_status": "unmatched",
            "srpe_candidate_ids": None,
            "srpe_candidate_count": 0,
            "ownership_status": "not_verified",
            "sales_ingestion_status": "not_ready",
            "last_verified_at": "2026-08-02T00:00:00+00:00",
        },
        {
            "pipeline_registry_key": "pipeline:cullinan-harbour-2",
            "disclosure_id": "interim",
            "project_label": "Cullinan Harbour Phase 2",
            "project_state": "planned_sale_10m",
            "geography": "Kai Tak",
            "source_url": "https://example/interim",
            "srpe_match_status": "ambiguous",
            "srpe_candidate_ids": "10405 | 11516",
            "srpe_candidate_count": 2,
            "ownership_status": "not_verified",
            "sales_ingestion_status": "not_ready",
            "last_verified_at": "2026-08-02T00:00:00+00:00",
        },
        {
            "pipeline_registry_key": "pipeline:known-phase",
            "disclosure_id": "interim",
            "project_label": "Known Phase",
            "project_state": "planned_sale_10m",
            "geography": "Hong Kong",
            "source_url": "https://example/interim",
            "srpe_match_status": "matched_needs_review",
            "srpe_candidate_ids": "10405",
            "srpe_candidate_count": 1,
            "ownership_status": "not_verified",
            "sales_ingestion_status": "not_ready",
            "last_verified_at": "2026-08-02T00:00:00+00:00",
        },
    ])
    sales_plan = pd.DataFrame([{"srpe_development_id": "10405"}])

    frame = shkp_source.build_shkp_future_project_resolution_plan(
        pipeline_registry,
        sales_plan=sales_plan,
    )

    unmatched = frame.loc[frame["pipeline_registry_key"].eq("pipeline:artist-square")].iloc[0]
    ambiguous = frame.loc[frame["pipeline_registry_key"].eq("pipeline:cullinan-harbour-2")].iloc[0]
    linked = frame.loc[frame["pipeline_registry_key"].eq("pipeline:known-phase")].iloc[0]
    assert unmatched["asset_scope"] == "commercial_investment_bot"
    assert unmatched["identity_resolution_action"] == "route_to_commercial_registry"
    assert unmatched["sales_plan_coverage_status"] == "not_applicable_non_residential"
    assert unmatched["resolution_status"] == "resolved_non_srpe_commercial_bot"
    assert unmatched["resolution_priority"] == "P2"
    assert ambiguous["identity_resolution_action"] == "resolve_phase_before_ownership"
    assert ambiguous["sales_plan_coverage_status"] == "candidate_unlinked"
    assert pd.isna(ambiguous["linked_srpe_development_id"])
    assert linked["linked_srpe_development_id"] == "10405"
    assert linked["sales_plan_coverage_status"] == "covered_by_phase_sales_plan"


def test_future_identity_evidence_is_joined_into_resolution_plan_without_sales_promotion():
    pipeline_registry = pd.DataFrame([{
        "pipeline_registry_key": "pipeline:silicon-hill",
        "disclosure_id": "interim",
        "project_label": "Silicon Hill/University Hill",
        "project_state": "planned_sale_10m",
        "geography": "Tai Po",
        "source_url": "https://example/interim",
        "srpe_match_status": "unmatched",
        "srpe_candidate_ids": None,
        "srpe_candidate_count": 0,
    }])
    identity = shkp_source.build_shkp_future_project_identity_evidence(
        last_verified_at="2026-08-03T00:00:00+00:00",
    )
    frame = shkp_source.build_shkp_future_project_resolution_plan(
        pipeline_registry,
        sales_plan=pd.DataFrame(columns=["srpe_development_id"]),
        identity_evidence=identity,
    )
    row = frame.iloc[0]
    assert set(row["srpe_candidate_ids"].split(" | ")) == {"8405", "8445", "9245"}
    assert row["identity_bridge_status"] == "multiple_phase_candidates"
    assert row["resolution_status"] == "unresolved_multiple_srpe_candidates"
    assert row["identity_bridge_ownership_promotion_status"] == "blocked_effective_interval"


def test_future_identity_aliases_join_descriptive_and_lot_labels_conservatively():
    pipeline_registry = pd.DataFrame([
        {
            "pipeline_registry_key": "pipeline:tsuen-wan-descriptive",
            "project_label": "Tsuen Wan West project (descriptive label)",
            "project_state": "planned_sale_10m",
            "srpe_match_status": "unmatched",
            "srpe_candidate_ids": None,
            "srpe_candidate_count": 0,
            "source_url": "https://example/interim",
        },
        {
            "pipeline_registry_key": "pipeline:kwu-tung-descriptive",
            "project_label": "Kwu Tung adjacent project Phase 1 (descriptive label)",
            "project_state": "planned_sale_10m",
            "srpe_match_status": "unmatched",
            "srpe_candidate_ids": None,
            "srpe_candidate_count": 0,
            "source_url": "https://example/interim",
        },
        {
            "pipeline_registry_key": "pipeline:tung-shing-lei-lot",
            "project_label": "Lot No. 1696 in DD 115, Tung Shing Lei, Yuen Long",
            "project_state": "planned_sale_10m",
            "srpe_match_status": "unmatched",
            "srpe_candidate_ids": None,
            "srpe_candidate_count": 0,
            "source_url": "https://example/interim",
        },
        {
            "pipeline_registry_key": "pipeline:commercial-lot",
            "project_label": "Lot No. 4354 in DD 124, Kiu Tau Wai, Yuen Long",
            "project_state": "under_development",
            "srpe_match_status": "unmatched",
            "srpe_candidate_ids": None,
            "srpe_candidate_count": 0,
            "source_url": "https://example/interim",
        },
    ])
    identity = shkp_source.build_shkp_future_project_identity_evidence(
        last_verified_at="2026-08-06T00:00:00+00:00",
    )
    frame = shkp_source.build_shkp_future_project_resolution_plan(
        pipeline_registry,
        sales_plan=pd.DataFrame(columns=["srpe_development_id"]),
        identity_evidence=identity,
    ).set_index("pipeline_registry_key")

    tsuen_wan = frame.loc["pipeline:tsuen-wan-descriptive"]
    assert tsuen_wan["identity_bridge_match_method"] == "curated_label_alias"
    assert tsuen_wan["identity_bridge_status"] == "phase_candidate_needs_review"
    assert tsuen_wan["srpe_candidate_ids"] == "11505"
    assert tsuen_wan["resolution_status"] == "identity_phase_linked_review_required"

    kwu_tung = frame.loc["pipeline:kwu-tung-descriptive"]
    assert kwu_tung["identity_bridge_match_method"] == "curated_label_alias"
    assert kwu_tung["identity_bridge_status"] == "lot_resolved_srpe_pending"
    assert kwu_tung["resolution_status"] == "identity_lot_resolved_srpe_pending"
    assert pd.isna(kwu_tung["linked_srpe_development_id"])

    tung_shing_lei = frame.loc["pipeline:tung-shing-lei-lot"]
    assert tung_shing_lei["identity_bridge_status"] == "lot_resolved_srpe_pending"
    assert tung_shing_lei["identity_bridge_lot_nos"] == "Lot 1696 in DD115"

    commercial = frame.loc["pipeline:commercial-lot"]
    assert commercial["identity_bridge_status"] == "non_srpe_asset"
    assert commercial["asset_scope"] == "commercial_investment"
    assert commercial["resolution_status"] == "not_applicable_to_srpe_residential"


def test_shkp_pipeline_aliases_resolve_lot_bridged_labels_without_ownership_promotion():
    disclosures = pd.DataFrame([
        {
            "disclosure_id": "interim",
            "disclosure_type": "interim_results",
            "project_label": "Sha Po South project",
            "status": "planned_launch_10m",
            "geography": "Yuen Long",
            "publication_date": "2026-02-26",
            "evidence_status": "found",
            "source_url": "https://example/interim",
            "fetched_at": "2026-08-02T00:00:00+00:00",
        },
        {
            "disclosure_id": "interim",
            "disclosure_type": "interim_results",
            "project_label": "Tsuen Wan West project",
            "status": "planned_launch_10m",
            "geography": "Tsuen Wan",
            "publication_date": "2026-02-26",
            "evidence_status": "found",
            "source_url": "https://example/interim",
            "fetched_at": "2026-08-02T00:00:00+00:00",
        },
    ])
    srpe = pd.DataFrame([
        {"development_id": "11554", "display_name": "GARDEN REGENCY", "development_name_en": "GARDEN REGENCY", "phase_name_en": "", "address_en": "1A YING HO ROAD", "planning_area_en": "Yuen Long"},
        {"development_id": "11505", "display_name": "LIME SPARK", "development_name_en": "LIME SPARK", "phase_name_en": "", "address_en": "21 WANG WO TSAI STREET", "planning_area_en": "Tsuen Wan"},
    ])
    frame = shkp_source.build_shkp_pipeline_srpe_crosswalk(disclosures, srpe)
    assert set(frame["srpe_development_id"]) == {"11554", "11505"}
    assert set(frame["match_status"]) == {"matched_needs_review"}
    assert set(frame["ownership_status"]) == {"not_verified"}


def test_shkp_pipeline_registry_preserves_non_srpe_commercial_status():
    crosswalk = pd.DataFrame([{
        "pipeline_evidence_key": "e1",
        "disclosure_id": "interim",
        "disclosure_type": "interim_results",
        "project_label": "Artist Square Towers",
        "pipeline_status": "under_development",
        "geography": "West Kowloon",
        "publication_date": "2026-02-26",
        "evidence_status": "found",
        "evidence_context": "commercial BOT",
        "source_url": "https://example/artist-square",
        "srpe_development_id": None,
        "srpe_development_name": None,
        "srpe_phase_name": None,
        "srpe_phase_no": None,
        "srpe_address_en": None,
        "match_method": "explicit_commercial_label",
        "match_confidence": "not_applicable",
        "match_status": "not_applicable_non_srpe",
        "candidate_count": 0,
        "ownership_status": "not_verified",
        "matched_at": "2026-08-03T00:00:00+00:00",
    }])
    registry = shkp_source.build_shkp_pipeline_project_registry(crosswalk)
    assert registry.loc[0, "srpe_match_status"] == "not_applicable_non_srpe"


def test_shkp_future_project_identity_evidence_keeps_lot_bridges_separate_from_ownership():
    frame = shkp_source.build_shkp_future_project_identity_evidence(
        last_verified_at="2026-08-03T00:00:00+00:00",
    )
    assert set(frame["project_label"]) >= {
        "Artist Square Towers",
        "Sha Po South project",
        "Tsuen Wan West project",
        "City One Sha Tin project",
        "Kwu Tung adjacent project Phase 1",
        "Kwu Tung South residential development",
        "Tung Shing Lei Phase 1",
        "Silicon Hill / University Hill",
    }
    sha_po = frame.loc[frame["project_label"].eq("Sha Po South project")].iloc[0]
    assert sha_po["srpe_development_id"] == "11554"
    assert sha_po["ownership_promotion_status"] == "blocked_effective_interval"
    artist = frame.loc[frame["project_label"].eq("Artist Square Towers")].iloc[0]
    assert pd.isna(artist["srpe_development_id"])
    assert artist["asset_scope"] == "commercial_investment_bot"
    tai_po = frame.loc[frame["srpe_development_id"].astype("string").isin({"8405", "8445", "9245"})]
    assert set(tai_po["srpe_development_id"]) == {"8405", "8445", "9245"}
    assert tai_po["canonical_identity_status"].eq("phase_resolved_srpe").all()
    assert tai_po["ownership_promotion_status"].eq("blocked_effective_interval").all()
    priority_identity_ids = set(
        frame["srpe_development_id"].dropna().astype(str)
    )
    assert {
        "9366", "11005", "9785", "10405", "11516", "11554", "11505",
        "11305", "11345", "9565", "10585", "7845", "8525",
    }.issubset(priority_identity_ids)


def test_shkp_phase_role_evidence_covers_priority_phases_without_opening_gate():
    frame = shkp_source.build_shkp_phase_role_evidence(
        last_verified_at="2026-08-03T00:00:00+00:00",
    )
    priority_ids = {
        "9366", "11005", "9785", "10405", "11516", "11554", "11505",
        "11305", "11345", "9565", "10585", "7845", "8525",
    }
    # The curated role layer intentionally includes bounded additions beyond
    # the original 13-phase audit; priority coverage is therefore a subset
    # contract rather than an exhaustive-universe assertion.
    assert priority_ids.issubset(set(frame["srpe_development_id"]))
    assert frame["ownership_pct"].isna().all()
    assert frame["effective_from"].isna().all()
    assert frame["effective_to"].isna().all()
    assert frame["promotion_status"].str.startswith("blocked").all()


def test_sierra_sea_quarterly_notice_adds_exact_phase_role_context_without_promotion():
    frame = shkp_source.build_shkp_phase_role_evidence(
        last_verified_at="2026-08-09T00:00:00+00:00",
    )
    quarterly = frame[frame["evidence_id"].str.contains("sierra-sea-q2-statutory")]
    assert set(quarterly["srpe_development_id"]) == {"10685", "10725"}
    assert quarterly["source_url"].eq(
        "https://www.shkp.com/Content/Uploads/SHKPQuarterly/2025q2/sc/PDF/qty2025q2sc.pdf"
    ).all()
    assert quarterly["ownership_pct"].isna().all()
    assert quarterly["effective_from"].isna().all()
    assert quarterly["effective_to"].isna().all()
    assert quarterly["promotion_status"].eq("blocked_role_only").all()


def test_cullinan_west_iii_notice_resolves_phase_five_role_context_without_promotion():
    frame = shkp_source.build_shkp_phase_role_evidence(
        last_verified_at="2026-08-09T00:00:00+00:00",
    )
    row = frame.loc[frame["evidence_id"].eq("official-role:5886:cullinan-west-p5")].iloc[0]
    assert row["role_scope"] == "owner_and_person_so_engaged"
    assert "Phase 5" in row["caveat"]
    assert "Sun Hung Kai Properties Limited" in row["holding_companies"]
    assert row["promotion_status"] == "blocked_role_only"
    assert pd.isna(row["ownership_pct"])
    assert pd.isna(row["effective_from"])
    assert pd.isna(row["effective_to"])


def test_historical_shared_address_role_additions_are_blocked_context_only():
    frame = shkp_source.build_shkp_phase_role_evidence(
        last_verified_at="2026-08-09T00:00:00+00:00",
    )
    additions = frame[frame["evidence_id"].str.startswith("primary-role:")]
    expected_ids = {
        "5505", "8845", "4447", "5325", "2906", "2905",
        "6585", "6765", "6967", "5265", "5266", "8445", "9245", "8405",
        "7965", "7525", "7325", "8245", "6445", "3625", "4267", "4285", "3826",
    }
    assert set(additions["srpe_development_id"]) == expected_ids
    assert additions["holding_companies"].str.contains("Sun Hung Kai Properties").all()
    assert additions["ownership_pct"].isna().all()
    assert additions["effective_from"].isna().all()
    assert additions["effective_to"].isna().all()
    assert additions["promotion_status"].str.startswith("blocked").all()


def test_ownership_coverage_audit_exposes_role_only_and_numeric_snapshot_gaps():
    priority_ids = {
        "9366", "11005", "9785", "10405", "11516", "11554", "11505",
        "11305", "11345", "9565", "10585", "7845", "8525",
    }
    srpe = pd.DataFrame([
        {
            "development_id": development_id,
            "display_name": f"SRPE {development_id}",
            "development_name_en": f"SRPE {development_id}",
            "phase_name_en": f"PHASE {development_id}",
            "phase_no": "1",
        }
        for development_id in sorted(priority_ids)
    ])
    legal = shkp_source.build_shkp_legal_ownership_observations(srpe)
    roles = shkp_source.build_shkp_phase_role_evidence(last_verified_at="2026-08-06T00:00:00+00:00")
    decisions = shkp_source.build_shkp_phase_attribution_decisions([
        {
            "decision_id": f"review:{development_id}:pending",
            "srpe_development_id": development_id,
            "decision_status": "blocked_review",
            "source_urls_json": "[]",
        }
        for development_id in sorted(priority_ids)
    ])
    frame = shkp_source.build_shkp_ownership_coverage_audit(
        srpe,
        phase_role_evidence=roles,
        legal_ownership_observations=legal,
        phase_attribution_decisions=decisions,
        identity_evidence=shkp_source.build_shkp_future_project_identity_evidence(),
        priority_phase_ids=priority_ids,
    )
    assert len(frame) == 13
    assert frame["attribution_decision_rows"].eq(1).all()
    assert frame["approved_interval_rows"].eq(0).all()
    assert frame["ownership_attribution_ready"].eq(False).all()
    assert set(frame["coverage_status"]) == {
        "numeric_snapshot_blocked",
        "identity_role_blocked",
    }
    assert frame.loc[frame["srpe_development_id"].eq("7845"), "coverage_status"].iloc[0] == "identity_role_blocked"
    yoho = frame.loc[frame["srpe_development_id"].eq("10585")].iloc[0]
    assert "MTR Corporation" in yoho["vendor_or_owner"]
    assert "Sun Hung Kai Properties" in yoho["holding_companies"]


def test_srpe_index_normalization_uses_legal_id_and_address_fields():
    frame = srpe_source._normalize_srpe_development_rows(
        [
            {
                "id": "8605",
                "engName": "NOVO LAND",
                "engPhaseName": "NOVO LAND",
                "engPhaseNo": "PHASE 1A",
                "addresses": [{"engAddress": "8 YAN PO ROAD", "chnAddress": "欣寶路 8號"}],
                "planningArea1": {
                    "id": 121,
                    "planningAreaNameEng": "TUEN MUN",
                    "broadDistrictId": 70,
                    "broadDistrictNameEng": "TUEN MUN AND YUEN LONG WEST",
                },
                "active": "Y",
                "website": "www.novoland.com.hk",
                "earlistPublicationTime": "2022-06-01T12:00:00+08:00",
                "dateSuspendSales": "2025-01-15T00:00:00+08:00",
                "dateCompleteSales": "2025-02-20T00:00:00+08:00",
                "engRemark": "Sales suspended",
                "chnRemark": "暫停銷售",
                "engAddrIdxRemark": "Suspended",
                "chnAddrIdxRemark": "暫停",
                "brochure": {"id": "29022", "dateOfPrint": "2022-07-08T00:00:00+08:00"},
            }
        ],
        source_url="https://www.srpe.gov.hk/api/SrpeWebService/DistrictAreaSearch/getDistrictAreaSearchResult",
        fetched_at="2026-08-01T00:00:00+00:00",
    )
    assert list(frame["development_id"]) == ["8605"]
    assert frame.loc[0, "display_name"] == "NOVO LAND"
    assert frame.loc[0, "phase_no"] == "PHASE 1A"
    assert frame.loc[0, "address_en"] == "8 YAN PO ROAD"
    assert frame.loc[0, "planning_area_en"] == "TUEN MUN"
    assert frame.loc[0, "brochure_first_print_date"] == "2022-07-08"
    assert frame.loc[0, "srpe_earliest_publication"] == "2022-06-01"
    assert frame.loc[0, "srpe_date_suspend_sales"] == "2025-01-15"
    assert frame.loc[0, "srpe_date_complete_sales"] == "2025-02-20"
    assert frame.loc[0, "srpe_eng_remark"] == "Sales suspended"
    assert frame.loc[0, "srpe_chn_addr_idx_remark"] == "暫停"


def test_historical_annual_report_index_keeps_vintages_and_variants():
    documents = pd.DataFrame(
        [
            {
                "document_type": "annual_report",
                "title": "Annual Report 2012/13",
                "document_url": "https://issuer.example/AR2012_13.pdf",
                "source_page_url": "https://issuer.example/reports",
                "issuer_release_date": "2013-10-01",
                "hkex_release_at": "2013-10-01T16:30:00+08:00",
                "release_source_url": "https://hkex.example/2013.pdf",
                "fetched_at": "2026-08-08T00:00:00+00:00",
            },
            {
                "document_type": "annual_report",
                "title": "Annual Report 2012/13 (Text Only)",
                "document_url": "https://issuer.example/AR2012_13_TextOnly.pdf",
                "source_page_url": "https://issuer.example/reports",
                "fetched_at": "2026-08-08T00:00:00+00:00",
            },
            {
                "document_type": "interim_report",
                "title": "Interim Report 2012/13",
                "document_url": "https://issuer.example/IR2012.pdf",
            },
        ]
    )
    frame = shkp_source.build_shkp_historical_annual_report_index(documents)
    assert len(frame) == 2
    assert frame["report_id"].nunique() == 1
    assert frame["report_document_id"].nunique() == 2
    assert set(frame["document_variant"]) == {"full_pdf", "text_only"}
    assert frame["report_period_end"].eq("2013-06-30").all()
    assert frame["project_table_parse_status"].eq("pending_template_audit").all()


class _FakeResponse:
    def __init__(self, payload):
        self.content = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def raise_for_status(self):
        return None

    def json(self):
        return json.loads(self.content.decode("utf-8"))


class _FakeSrpeSession:
    def __init__(self, payload):
        self.headers = {}
        self.payload = payload
        self.called = None

    def post(self, url, json, timeout):
        self.called = (url, json, timeout)
        return _FakeResponse(self.payload)


def test_fetch_srpe_index_uses_all_development_contract(monkeypatch, tmp_path):
    raw_path = tmp_path / "srpe-index.json"
    payload = {
        "code": 0,
        "resultData": {
            "total": 1,
            "list": [
                {
                    "id": "1",
                    "engName": "TEST DEVELOPMENT",
                    "active": "Y",
                    "addresses": [],
                }
            ],
        },
    }
    session = _FakeSrpeSession(payload)
    monkeypatch.setattr(srpe_source, "save_raw_snapshot", lambda *args, **kwargs: raw_path)

    frame = srpe_source.fetch_srpe_development_index(session=session)

    assert len(frame) == 1
    assert frame.loc[0, "development_id"] == "1"
    assert frame.attrs["lineage_metadata"]["api_total"] == 1
    # SRPE currently routes the all-development view through this exact
    # action label; the older longer label returns a valid-looking 0-row body.
    assert session.called[1]["actionType"] == "Index For All Residential"
    assert session.called[1]["planningAreaIds"] == ["A"]


def test_shkp_srpe_crosswalk_retains_ambiguous_domain_candidates():
    shkp_catalog = pd.DataFrame(
        [
            {
                "asset_type": "residential_for_sale",
                "marketing_name": "TEST HEIGHTS",
                "external_project_url": "https://test.example/project",
                "external_project_urls": '["https://test.example/project"]',
                "source_record_id": "residential_for_sale:for_sale:0:1",
                "source_url": "https://www.shkp.com/feed",
                "fetched_at": "2026-08-01T00:00:00+00:00",
            }
        ]
    )
    srpe_index = pd.DataFrame(
        [
            {
                "development_id": "1",
                "development_name_en": "TEST HEIGHTS",
                "development_name_zh": "測試山",
                "phase_name_en": "PHASE 1",
                "phase_name_zh": "第一期",
                "phase_no": "1",
                "official_website": "test.example",
                "source_url": "https://www.srpe.gov.hk/api/index",
            },
            {
                "development_id": "2",
                "development_name_en": "TEST HEIGHTS",
                "development_name_zh": "測試山",
                "phase_name_en": "PHASE 2",
                "phase_name_zh": "第二期",
                "phase_no": "2",
                "official_website": "test.example",
                "source_url": "https://www.srpe.gov.hk/api/index",
            },
        ]
    )

    frame = shkp_source.build_shkp_srpe_crosswalk(shkp_catalog, srpe_index)

    assert len(frame) == 2
    assert set(frame["match_status"]) == {"ambiguous"}
    assert set(frame["candidate_count"]) == {2}
    assert set(frame["ownership_status"]) == {"not_verified"}
    assert frame["ticker"].isna().all()


def test_shkp_srpe_crosswalk_does_not_assign_phase_two_to_phase_one_domain_row():
    shkp_catalog = pd.DataFrame(
        [{
            "asset_type": "residential_for_sale",
            "marketing_name": "Cullinan Harbour Phase 2A",
            "external_project_url": "https://cullinan.example/project",
            "external_project_urls": '["https://cullinan.example/project"]',
            "source_record_id": "shkp:1",
            "source_url": "https://www.shkp.com/feed",
            "fetched_at": "2026-08-01T00:00:00+00:00",
        }]
    )
    srpe_index = pd.DataFrame(
        [
            {
                "development_id": "9785",
                "development_name_en": "CULLINAN HARBOUR DEVELOPMENT",
                "phase_name_en": "CULLINAN HARBOUR",
                "phase_no": "PHASE 1",
                "official_website": "cullinan.example",
                "source_url": "https://www.srpe.gov.hk/api/index",
            },
            {
                "development_id": "10405",
                "development_name_en": "CULLINAN HARBOUR DEVELOPMENT",
                "phase_name_en": "CULLINAN HARBOUR PHASE 2A",
                "phase_no": "PHASE 2A",
                "official_website": "cullinan.example",
                "source_url": "https://www.srpe.gov.hk/api/index",
            },
        ]
    )

    frame = shkp_source.build_shkp_srpe_crosswalk(shkp_catalog, srpe_index)

    assert frame["srpe_development_id"].tolist() == ["10405"]
    assert frame.loc[0, "match_status"] == "matched"
    assert "9785" not in set(frame["srpe_development_id"])


def test_shkp_srpe_crosswalk_allows_phase_specific_domain_for_marketing_alias():
    shkp_catalog = pd.DataFrame([
        {
            "asset_type": "residential_for_sale",
            "marketing_name": "Sierra Sea Phase 2A",
            "external_project_url": "https://sierrasea2a.example",
            "external_project_urls": '["https://sierrasea2a.example"]',
            "source_record_id": "shkp:sierra-2a",
            "source_url": "https://www.shkp.com/feed",
            "fetched_at": "2026-08-02T00:00:00+00:00",
        }
    ])
    srpe_index = pd.DataFrame([
        {
            "development_id": "11305",
            "development_name_en": "SAI SHA RESIDENCES",
            "phase_name_en": "SIERRA SEA",
            "phase_no": "PHASE 2A",
            "official_website": "sierrasea2a.example",
            "source_url": "https://www.srpe.gov.hk/api/index",
        },
        {
            "development_id": "11345",
            "development_name_en": "SAI SHA RESIDENCES",
            "phase_name_en": "SIERRA SEA",
            "phase_no": "PHASE 2B",
            "official_website": "sierrasea2b.example",
            "source_url": "https://www.srpe.gov.hk/api/index",
        },
    ])

    frame = shkp_source.build_shkp_srpe_crosswalk(shkp_catalog, srpe_index)

    assert frame["srpe_development_id"].tolist() == ["11305"]
    assert frame.loc[0, "match_status"] == "matched_needs_review"
    assert frame.loc[0, "match_method"] == "website_domain_exact+website_domain_phase_exact"


def test_shkp_phase_evidence_audit_keeps_jv_and_phase_conflict_explicit():
    annual = pd.DataFrame(
        [{
            "report_id": "ar",
            "project_label": "YOHO WEST Phase 1",
            "project_state": "handover_completed",
            "location": "1 Tin Yan Road, Tin Shui Wai",
            "geography": "Hong Kong",
            "group_interest_raw": "JV",
            "group_interest_pct": None,
            "document_url": "https://www.shkp.com/ar.pdf",
        }]
    )
    srpe = pd.DataFrame(
        [
            {
                "development_id": "1",
                "display_name": "TIN SHUI WAI TOWN LOT NO. 23 DEVELOPMENT",
                "development_name_en": "TIN SHUI WAI TOWN LOT NO. 23 DEVELOPMENT",
                "phase_name_en": "YOHO WEST",
                "phase_no": "1",
                "address_en": "1 TIN YAN ROAD",
            },
            {
                "development_id": "2",
                "display_name": "TIN SHUI WAI TOWN LOT NO. 23 DEVELOPMENT",
                "development_name_en": "TIN SHUI WAI TOWN LOT NO. 23 DEVELOPMENT",
                "phase_name_en": "YOHO WEST PARKSIDE",
                "phase_no": "2",
                "address_en": "1 TIN YAN ROAD",
            },
        ]
    )
    planning = pd.DataFrame(
        [{
            "development_name_raw": "YOHO WEST Phase 1",
            "lot_no_raw": "TSWTL 23",
            "parent_or_holding_company_or_developer_raw": "Sun Hung Kai Properties Limited / MTR Corporation",
            "document_url": "https://www.landsd.gov.hk/yuen-long.pdf",
            "page_number": 29,
            "consent_or_approval_date": "2023-09-27",
        }]
    )

    frame = shkp_source.build_shkp_phase_evidence_quality_audit(annual, srpe, planning)

    assert set(frame["srpe_development_id"]) == {"1", "2"}
    assert set(frame["ownership_status"]) == {"annual_jv_unresolved"}
    assert set(frame["candidate_status"]) == {"candidate_supported_ambiguous"}
    assert set(frame["phase_status"]) == {"phase_not_exposed"}
    assert "MTR Corporation" in frame.loc[0, "planning_entity_raw"]


def test_unified_shkp_project_registry_keeps_evidence_layers_separate():
    srpe = pd.DataFrame(
        [{
            "development_id": "10405",
            "display_name": "CULLINAN HARBOUR DEVELOPMENT",
            "development_name_en": "CULLINAN HARBOUR DEVELOPMENT",
            "phase_name_en": "CULLINAN HARBOUR",
            "phase_no": "PHASE 2A",
            "address_en": "26 SHING FUNG ROAD",
            "planning_area_en": "KAI TAK",
            "active": "Y",
            "official_website": "www.cullinanharbour.com.hk",
            "srpe_earliest_publication": "2025-10-01",
            "srpe_date_suspend_sales": None,
            "srpe_date_complete_sales": None,
            "fetched_at": "2026-08-08T00:00:00+00:00",
            "source_url": "https://www.srpe.gov.hk/index",
        }]
    )
    shkp = pd.DataFrame(
        [{
            "marketing_name": "Cullinan Harbour Phase 2A",
            "srpe_development_id": "10405",
            "match_status": "matched_needs_review",
            "match_confidence": "medium",
            "shkp_source_url": "https://www.shkp.com/property",
            "srpe_source_url": "https://www.srpe.gov.hk/index",
        }]
    )
    annual = pd.DataFrame(
        [{
            "project_label": "Cullinan Harbour Phase 2",
            "project_state": "planned_sale_10m",
            "annual_group_interest_raw": "JV",
            "annual_group_interest_pct": None,
            "srpe_development_id": "10405",
            "match_status": "ambiguous",
            "annual_document_url": "https://www.shkp.com/ar.pdf",
        }]
    )
    planning = pd.DataFrame(
        [{
            "srpe_development_id": "10405",
            "match_status": "matched_needs_review",
            "lot_no_raw": "NKIL 6551",
            "planning_consent_date": "2026-02-10",
            "parent_or_developer_raw": "Sun Hung Kai Properties Limited / Time Effort Limited",
            "document_url": "https://www.landsd.gov.hk/ke.pdf",
        }]
    )
    pilot = pd.DataFrame(
        [{
            "project_id": "cullinan-pilot",
            "stock_code": "0016",
            "srpe_dev_id": "10405",
            "ownership_pct": "100",
            "pilot_group": "review_only",
        }]
    )

    frame = shkp_source.build_shkp_project_registry(
        srpe,
        shkp,
        annual,
        planning,
        pilot_registry=pilot,
    )

    row = frame.iloc[0]
    assert row["registry_key"] == "srpe:10405"
    assert row["pipeline_status"] == "current_website_listing|planned_sale_10m"
    assert row["universe_status"] == "review_required"
    assert "current_shkp_directory" in row["universe_evidence_types"]
    assert "shkp_annual_report" in row["universe_evidence_types"]
    assert row["official_website"] == "www.cullinanharbour.com.hk"
    assert row["srpe_earliest_publication"] == "2025-10-01"
    assert row["srpe_index_snapshot_at"] == "2026-08-08T00:00:00+00:00"
    assert row["ownership_status"] == "annual_jv_unresolved"
    assert not bool(row["ownership_attribution_ready"])
    assert row["ownership_evidence_level"] == "numeric_snapshot_or_grouped_interest"
    assert row["ownership_evidence_promotion_status"] == "blocked_jv_economics_interval"
    assert row["ownership_evidence_source_count"] >= 1
    assert "dated effective interval" in row["ownership_next_evidence"]
    assert row["planning_lot_nos"] == "NKIL 6551"
    assert row["planning_consent_dates"] == "2026-02-10"
    assert row["pilot_status"] == "review_only"


def test_project_registry_keeps_current_candidate_when_only_historical_match_is_ambiguous():
    srpe = pd.DataFrame([{
        "development_id": "10405",
        "display_name": "Cullinan Harbour",
        "development_name_en": "CULLINAN HARBOUR DEVELOPMENT",
        "phase_name_en": "CULLINAN HARBOUR PHASE 2A",
        "phase_no": "2A",
        "address_en": "NKIL 6551",
        "active": "Y",
        "fetched_at": "2026-08-08T00:00:00+00:00",
    }])
    current = pd.DataFrame([{
        "srpe_development_id": "10405",
        "marketing_name": "Cullinan Harbour Phase 2A",
        "match_status": "matched",
    }])
    historical = pd.DataFrame([{
        "srpe_development_id": "10405",
        "project_label": "Cullinan Harbour Phase 2",
        "match_status": "ambiguous",
    }])

    frame = shkp_source.build_shkp_project_registry(srpe, current, historical)

    assert frame.iloc[0]["universe_status"] == "current_candidate"
    assert frame.iloc[0]["annual_match_status"] == "ambiguous"


def test_historical_phase_review_queue_keeps_unmatched_labels_and_manifest_status():
    annual = pd.DataFrame([
        {
            "report_id": "shkp_ar_2014_15",
            "report_period_end": "2015-06-30",
            "evidence_type": "handover_table",
            "project_label": "Legacy Estate Phase 1",
            "annual_location": "Old Road, Kowloon",
            "srpe_development_id": "1966",
            "srpe_development_name": "LEGACY ESTATE",
            "srpe_phase_name": "PHASE 1",
            "match_status": "matched_needs_review",
            "match_confidence": "high",
            "match_method": "name_exact",
            "candidate_count": 1,
            "annual_document_url": "https://example.test/ar.pdf",
        },
        {
            "report_id": "shkp_ar_2004_05",
            "report_period_end": "2005-06-30",
            "evidence_type": "handover_table",
            "project_label": "Unmatched Old Label",
            "annual_location": "Unknown",
            "srpe_development_id": None,
            "match_status": "unmatched",
            "candidate_count": 0,
        },
    ])
    roster = pd.DataFrame([
        {
            "srpe_development_id": "1966",
            "development_name_en": "LEGACY ESTATE",
            "phase_name_en": "PHASE 1",
            "active": "N",
            "srpe_date_suspend_sales": "2014-01-01",
            "srpe_date_complete_sales": None,
        }
    ])
    manifest = pd.DataFrame([{
        "srpe_development_id": "1966",
        "document_category": "register_of_transactions",
    }])

    queue = shkp_source.build_shkp_historical_phase_review_queue(annual, roster, manifest)

    assert len(queue) == 2
    linked = queue.loc[queue["srpe_development_id"] == "1966"].iloc[0]
    assert linked["review_priority"] == "P0"
    assert linked["transaction_manifest_rows"] == 1
    assert linked["transaction_manifest_status"] == "register_manifest_available"
    unmatched = queue.loc[queue["match_status"] == "unmatched"].iloc[0]
    assert pd.isna(unmatched["srpe_development_id"])
    assert unmatched["review_action"] == "manual_alias_address_lot_reconciliation"


def test_legal_spv_observations_are_dated_snapshots_and_do_not_promote_sales():
    srpe = pd.DataFrame(
        [
            {
                "development_id": "9366",
                "display_name": "CULLINAN SKY DEVELOPMENT",
                "development_name_en": "CULLINAN SKY DEVELOPMENT",
                "phase_name_en": "CULLINAN SKY",
                "phase_no": "PHASE 1",
                "address_en": "10 CONCORDE ROAD",
                "source_url": "https://www.srpe.gov.hk/index",
            }
        ]
    )

    observations = shkp_source.build_shkp_legal_ownership_observations(srpe)
    assert len(observations) == 4
    assert observations["subsidiary_spv_name"].eq("Super Great Limited").all()
    assert observations["ownership_pct"].eq(100.0).all()
    assert observations["effective_from"].isna().all()
    assert observations["legally_continuous"].eq(False).all()
    assert observations["interval_blocker"].notna().all()
    assert observations["promotion_status"].eq("blocked_effective_interval").all()
    assert set(observations["ownership_observed_as_of"]) == {
        "2018-05-15",
        "2024-06-30",
        "2025-06-30",
        "2025-12-31",
    }
    interim = observations.loc[
        observations["observation_type"].eq("interim_property_table_group_interest")
    ].iloc[0]
    assert interim["evidence_status"] == "numeric_grouped_project_snapshot"
    assert "does not split" in interim["caveat"]

    registry = shkp_source.build_shkp_project_registry(
        srpe,
        legal_ownership_observations=observations,
    )
    row = registry.iloc[0]
    assert row["legal_spv_names"] == "Super Great Limited"
    assert row["ownership_observed_pct"] == 100.0
    assert row["legal_ownership_observation_status"] == "numeric_spv_snapshot_needs_effective_interval"
    assert row["legal_ownership_evidence_rows"] == 4
    assert not bool(row["ownership_attribution_ready"])


def test_latest_interim_stake_snapshots_are_phase_or_lot_bridged_but_still_blocked():
    srpe = pd.DataFrame([
        {
            "development_id": development_id,
            "display_name": f"SRPE {development_id}",
            "development_name_en": f"SRPE {development_id}",
            "phase_name_en": "PHASE",
            "phase_no": "1",
            "address_en": "HONG KONG",
            "source_url": "https://www.srpe.gov.hk/index",
        }
        for development_id in ("11005", "11516", "11554", "11505", "11305", "11345")
    ])
    observations = shkp_source.build_shkp_legal_ownership_observations(srpe)
    latest = observations.loc[observations["ownership_observed_as_of"].eq("2026-02-26")]
    assert set(latest["srpe_development_id"]) == {"11005", "11516", "11554", "11505"}
    assert latest["ownership_pct"].eq(100.0).all()
    assert latest["interval_blocker"].isin({"presentation_snapshot_no_effective_dates", "grouped_phase_or_project_snapshot"}).all()
    assert latest["effective_from"].isna().all()
    assert latest["effective_to"].isna().all()
    grouped = observations.loc[observations["srpe_development_id"].isin({"11305", "11345"})]
    assert len(grouped) == 2
    assert grouped["evidence_status"].eq("numeric_grouped_project_snapshot").all()
    assert grouped["legally_continuous"].eq(False).all()


def test_shkp_registry_blocks_interval_when_pct_does_not_reconcile_to_numeric_snapshot():
    srpe = pd.DataFrame([{
        "development_id": "9146",
        "development_name_en": "NOVO LAND",
        "phase_name_en": "PHASE 3A",
        "phase_no": "PHASE 3A",
        "address_en": "1 EXAMPLE ROAD",
    }])
    annual = pd.DataFrame([{
        "srpe_development_id": "9146",
        "annual_group_interest_pct": 100.0,
        "annual_group_interest_raw": "100%",
        "match_status": "matched",
    }])
    pilot = pd.DataFrame([{
        "project_id": "novo-3a",
        "srpe_dev_id": "9146",
        "ownership_pct": 100.0,
        "pilot_group": "review_only",
    }])
    decision = shkp_source.build_shkp_phase_attribution_decisions([{
        "decision_id": "decision:novo-3a",
        "srpe_development_id": "9146",
        "ownership_pct": 50.0,
        "effective_from": "2024-01-01",
        "effective_to": "2025-12-31",
        "phase_identity_status": "matched",
        "phase_identity_evidence_ids": "srpe:9146",
        "economic_evidence_ids": "economic:example",
        "title_chain_evidence_ids": "title:example",
        "continuity_basis": "reviewed example",
        "reviewer": "researcher",
        "reviewed_at": "2026-08-03",
        "decision_status": "approved",
        "source_urls_json": "[\"https://example.test/mismatch\"]",
    }])

    frame = shkp_source.build_shkp_project_registry(
        srpe,
        annual_srpe_crosswalk=annual,
        pilot_registry=pilot,
        phase_attribution_decisions=decision,
    )

    row = frame.iloc[0]
    assert row["ownership_status"] == "consistent_numeric"
    assert row["ownership_interval_status"] == "blocked_interval_pct_mismatch"
    assert not bool(row["ownership_attribution_ready"])


def test_shkp_land_registry_importer_is_evidence_only_and_does_not_infer_interval():
    frame = shkp_source.build_shkp_land_registry_evidence([
        {
            "srpe_development_id": "9366",
            "lot_no": "NKIL 6568",
            "memorial_no": "M123456",
            "instrument_type": "New Grant",
            "instrument_date": "2018-05-15",
            "registered_owner": "Super Great Limited",
            "owner_capacity": "registered owner",
            "registered_share": "1/1",
            "source_order_reference": "IRIS-TEST-001",
            "effective_from": "2018-05-15",
            "effective_to": "2025-06-30",
            "ownership_pct": 100,
            "phase_match_status": "matched_needs_review",
        }
    ], last_verified_at="2026-08-03T00:00:00+00:00")

    row = frame.iloc[0]
    assert row["evidence_id"].startswith("landreg:")
    assert row["instrument_date"] == "2018-05-15"
    # Explicit dates are preserved for review, but title evidence cannot open
    # the SHKP economic-interest gate by itself.
    assert row["effective_from"] == "2018-05-15"
    assert row["effective_to"] == "2025-06-30"
    assert not bool(row["legally_continuous"])
    assert row["promotion_status"] == "blocked_land_registry_owner_only"
    assert "Registered-title evidence" in row["caveat"]


def test_shkp_land_registry_importer_rejects_missing_provenance_and_bad_dates():
    with pytest.raises(ValueError, match="source URL, document, or order"):
        shkp_source.build_shkp_land_registry_evidence([
            {"lot_no": "NKIL 6568", "memorial_no": "M1"}
        ])
    with pytest.raises(ValueError, match="invalid date"):
        shkp_source.build_shkp_land_registry_evidence([
            {
                "lot_no": "NKIL 6568",
                "memorial_no": "M1",
                "instrument_date": "not-a-date",
                "source_order_reference": "IRIS-TEST-002",
            }
        ])


def test_shkp_land_registry_evidence_cannot_open_registry_when_misrouted():
    srpe = pd.DataFrame([{
        "development_id": "9366",
        "development_name_en": "CULLINAN SKY DEVELOPMENT",
        "phase_name_en": "PHASE 1",
        "phase_no": "PHASE 1",
    }])
    land = shkp_source.build_shkp_land_registry_evidence([{
        "srpe_development_id": "9366",
        "lot_no": "NKIL 6568",
        "memorial_no": "M1",
        "instrument_type": "Assignment",
        "instrument_date": "2018-05-15",
        "registered_owner": "Super Great Limited",
        "source_order_reference": "IRIS-TEST-003",
        "ownership_pct": 100,
        "effective_from": "2018-05-15",
        "effective_to": "2025-06-30",
    }])

    # Even if an operator accidentally passes the title layer through the
    # legal-observation argument, the approved-decision guard must keep it out.
    registry = shkp_source.build_shkp_project_registry(
        srpe,
        legal_ownership_observations=land,
    )
    assert not bool(registry.iloc[0]["ownership_attribution_ready"])


def test_shkp_phase_attribution_decision_is_the_only_promotable_interval_layer():
    decision = shkp_source.build_shkp_phase_attribution_decisions([{
        "decision_id": "decision:novo-3a",
        "srpe_development_id": "9146",
        "phase_label": "NOVO LAND Phase 3A",
        "listed_parent": "Sun Hung Kai Properties Limited",
        "stock_code": "0016",
        "ownership_pct": 100,
        "effective_from": "2024-01-01",
        "effective_to": "2025-12-31",
        "phase_identity_status": "matched",
        "phase_identity_evidence_ids": "srpe:9146|site:novo-3a",
        "economic_evidence_ids": "hkex:ar-2025:p220",
        "title_chain_evidence_ids": "landreg:M1",
        "continuity_basis": "dated SPV/JV instrument chain reviewed across the sales window",
        "reviewer": "researcher",
        "reviewed_at": "2026-08-03",
        "decision_status": "approved",
        "source_urls_json": "[\"https://example.test/decision\"]",
    }], last_verified_at="2026-08-03T00:00:00+00:00")
    assert decision.iloc[0]["evidence_type"] == "approved_phase_attribution_decision"
    assert decision.iloc[0]["promotion_status"] == "approved_phase_attribution"
    assert bool(decision.iloc[0]["ownership_attribution_ready"])

    srpe = pd.DataFrame([{
        "development_id": "9146",
        "development_name_en": "NOVO LAND",
        "phase_name_en": "PHASE 3A",
        "phase_no": "PHASE 3A",
    }])
    annual = pd.DataFrame([{
        "srpe_development_id": "9146",
        "annual_group_interest_pct": 100.0,
        "annual_group_interest_raw": "100%",
        "match_status": "matched",
    }])
    pilot = pd.DataFrame([{
        "project_id": "novo-3a",
        "stock_code": "0016",
        "srpe_dev_id": "9146",
        "ownership_pct": 100.0,
        "pilot_group": "review_only",
    }])
    registry = shkp_source.build_shkp_project_registry(
        srpe,
        annual_srpe_crosswalk=annual,
        pilot_registry=pilot,
        phase_attribution_decisions=decision,
    )
    row = registry.iloc[0]
    assert bool(row["ownership_attribution_ready"])
    assert row["ownership_interval_evidence_type"] == "approved_phase_attribution_decision"
    assert row["ownership_attribution_decision_id"] == "decision:novo-3a"


def test_shkp_phase_attribution_decision_rejects_approved_row_without_independent_evidence():
    with pytest.raises(ValueError, match="economic_evidence_ids"):
        shkp_source.build_shkp_phase_attribution_decisions([{
            "decision_id": "decision:forged",
            "srpe_development_id": "9146",
            "ownership_pct": 100,
            "effective_from": "2024-01-01",
            "effective_to": "2025-12-31",
            "phase_identity_status": "matched",
            "phase_identity_evidence_ids": "srpe:9146",
            "title_chain_evidence_ids": "landreg:M1",
            "continuity_basis": "asserted",
            "reviewer": "researcher",
            "reviewed_at": "2026-08-03",
            "decision_status": "approved",
            "source_urls_json": "[]",
        }])


def test_shkp_phase_attribution_decision_rejects_approved_row_without_source_url():
    with pytest.raises(ValueError, match="source URL"):
        shkp_source.build_shkp_phase_attribution_decisions([{
            "decision_id": "decision:no-source-url",
            "srpe_development_id": "9146",
            "ownership_pct": 100,
            "effective_from": "2024-01-01",
            "effective_to": "2025-12-31",
            "phase_identity_status": "matched",
            "phase_identity_evidence_ids": "srpe:9146",
            "economic_evidence_ids": "hkex:ar-2025:p220",
            "title_chain_evidence_ids": "landreg:M1",
            "continuity_basis": "dated SPV/JV instrument chain reviewed",
            "reviewer": "researcher",
            "reviewed_at": "2026-08-03",
            "decision_status": "approved",
            "source_urls_json": "[]",
        }])


def test_shkp_blocked_decision_cannot_open_interval_with_forged_promotion_fields():
    srpe = pd.DataFrame([{
        "development_id": "9366",
        "development_name_en": "CULLINAN SKY DEVELOPMENT",
        "phase_name_en": "CULLINAN SKY PHASE 1",
        "phase_no": "PHASE 1",
    }])
    annual = pd.DataFrame([{
        "srpe_development_id": "9366",
        "annual_group_interest_pct": 100.0,
        "annual_group_interest_raw": "100%",
        "match_status": "matched",
    }])
    forged = pd.DataFrame([{
        "decision_id": "decision:forged-blocked",
        "srpe_development_id": "9366",
        "ownership_pct": 100.0,
        "effective_from": "2024-01-01",
        "effective_to": "2025-12-31",
        "decision_status": "blocked_review",
        "evidence_type": "approved_phase_attribution_decision",
        "promotion_status": "approved_phase_attribution",
        "source_urls_json": "[\"https://example.test/forged\"]",
    }])
    registry = shkp_source.build_shkp_project_registry(
        srpe,
        annual_srpe_crosswalk=annual,
        phase_attribution_decisions=forged,
    )
    assert not bool(registry.iloc[0]["ownership_attribution_ready"])


def test_well_capital_tender_observation_is_parent_company_evidence_not_numeric_pct():
    srpe = pd.DataFrame([
        {
            "development_id": "10405",
            "development_name_en": "CULLINAN HARBOUR DEVELOPMENT",
            "phase_name_en": "CULLINAN HARBOUR PHASE 2A",
            "phase_no": "PHASE 2A",
            "address_en": "26 SHING FUNG ROAD",
            "source_url": "https://www.srpe.gov.hk/index",
        }
    ])

    observations = shkp_source.build_shkp_legal_ownership_observations(srpe)
    tender = observations.loc[
        observations["observation_type"].eq("landsd_tender_award_parent_company")
    ].iloc[0]
    assert tender["ownership_pct"] is None or pd.isna(tender["ownership_pct"])
    assert tender["ownership_observed_as_of"] == "2019-01-23"
    assert tender["evidence_status"] == "parent_company_observation"
    assert tender["promotion_status"] == "blocked_effective_interval"
    assert "P2019012300718.htm" in tender["source_urls_json"]


def test_entity_ownership_crosswalk_keeps_spv_parent_vendor_and_planning_labels_distinct():
    legal = pd.DataFrame([
        {
            "observation_id": "10405:2024-06-30:annual_principal_subsidiary",
            "srpe_development_id": "10405",
            "srpe_phase_name": "CULLINAN HARBOUR PHASE 2A",
            "listed_parent": "Sun Hung Kai Properties Limited",
            "stock_code": "0016",
            "subsidiary_spv_name": "Well Capital (H.K.) Limited",
            "ownership_pct": 100.0,
            "ownership_observed_as_of": "2024-06-30",
            "evidence_status": "numeric_spv_snapshot",
            "ownership_source_url": "https://example.test/ar.pdf",
            "ownership_source_page": "225",
            "caveat": "snapshot only",
            "source_urls_json": "[\"https://example.test/ar.pdf\"]",
        }
    ])
    site = pd.DataFrame([
        {
            "marketing_name": "Cullinan Harbour Phase 2A",
            "vendor_name": "Well Capital (H.K.) Limited",
            "holding_companies": "Sun Hung Kai Properties Limited, Time Effort Limited",
            "site_evidence_status": "found",
            "site_source_url": "https://example.test/project",
            "srpe_development_id": "10405",
            "srpe_phase_name": "CULLINAN HARBOUR PHASE 2A",
        }
    ])
    planning = pd.DataFrame([
        {
            "parent_or_developer_raw": "Sun Hung Kai Properties Limited / MTR Corporation",
            "evidence_status": "found",
            "source_url": "https://example.test/landsd.pdf",
            "page_or_detail": "page=4",
            "srpe_development_id": "10405",
            "srpe_phase_name": "CULLINAN HARBOUR PHASE 2A",
        }
    ])

    frame = shkp_source.build_shkp_entity_ownership_crosswalk(
        legal_ownership_observations=legal,
        planning_evidence_crosswalk=planning,
        site_vendor_crosswalk=site,
    )

    assert frame["entity_observation_id"].is_unique
    assert frame["effective_from"].isna().all()
    assert frame["effective_to"].isna().all()
    assert set(frame["entity_type"]) >= {
        "subsidiary_spv",
        "listed_parent",
        "vendor_or_developer",
        "holding_company_observation",
        "planning_entity_observation",
    }
    spv = frame.loc[frame["entity_type"].eq("subsidiary_spv")].iloc[0]
    assert spv["entity_key"] == "subsidiary_spv:wellcapitalhklimited"
    assert spv["ownership_pct_observed"] == 100.0
    assert spv["dedup_status"] == "snapshot_not_effective_interval"
    holding = frame.loc[
        frame["entity_name"].eq("Sun Hung Kai Properties Limited")
        & frame["entity_type"].eq("holding_company_observation")
    ].iloc[0]
    assert holding["stock_code"] == "0016"
    assert pd.isna(holding["ownership_pct_observed"])
    assert set(frame["relation_status"]) >= {
        "numeric_snapshot",
        "parent_observed",
        "vendor_observed",
        "holding_company_observed",
        "planning_entity_observed",
    }

    unrelated_planning = planning.copy()
    unrelated_planning.loc[0, "srpe_development_id"] = "9999"
    scoped = shkp_source.build_shkp_entity_ownership_crosswalk(
        legal_ownership_observations=legal,
        planning_evidence_crosswalk=unrelated_planning,
        site_vendor_crosswalk=site,
        allowed_srpe_development_ids={"10405"},
    )
    assert set(scoped["srpe_development_id"]) == {"10405"}


def test_shkp_sales_ingestion_gate_separates_ownership_and_manifest_availability():
    registry = pd.DataFrame([
        {
            "registry_key": "srpe:9146",
            "srpe_development_id": "9146",
            "development_name_en": "NOVO LAND",
            "phase_name_en": "PHASE 3A",
            "ownership_status": "consistent_numeric",
            "curated_registry_ownership_pct": 100.0,
            "ownership_effective_from": "2024-01-01",
            "ownership_effective_to": "2025-12-31",
            "ownership_interval_status": "phase_specific_bounded_interval",
            "ownership_interval_evidence_type": "approved_phase_attribution_decision",
            "ownership_attribution_decision_id": "decision:novo-3a",
            "ownership_interval_promotion_status": "approved_phase_attribution",
            "ownership_attribution_ready": True,
            "pilot_status": "core_pilot",
            "manifest_status": "not_loaded",
            "source_urls_json": "[]",
        },
        {
            "registry_key": "srpe:9785",
            "srpe_development_id": "9785",
            "development_name_en": "CULLINAN HARBOUR DEVELOPMENT",
            "phase_name_en": "PHASE 1",
            "ownership_status": "not_verified",
            "ownership_attribution_ready": False,
            "pilot_status": "not_in_pilot",
            "manifest_status": "filings_available",
            "source_urls_json": "[]",
        },
    ])
    manifest = pd.DataFrame([
        {
            "srpe_development_id": "9785",
            "document_category": "register_of_transactions",
            "document_id": "100",
            "serial_no": None,
            "file_name": "register.pdf",
        },
        {
            "srpe_development_id": "9785",
            "document_category": "sales_brochure",
            "document_id": "200",
            "serial_no": "1",
            "file_name": "brochure-1.pdf",
        },
        {
            "srpe_development_id": "9785",
            "document_category": "sales_brochure",
            "document_id": "200",
            "serial_no": "2",
            "file_name": "brochure-2.pdf",
        },
    ])

    result = shkp_source.build_shkp_sales_ingestion_eligibility(registry, manifest)

    novo = result.loc[result["srpe_development_id"].eq("9146")].iloc[0]
    cullinan = result.loc[result["srpe_development_id"].eq("9785")].iloc[0]
    assert novo["eligibility_status"] == "manifest_required"
    assert cullinan["eligibility_status"] == "ownership_review_required"
    assert cullinan["register_document_count"] == 1
    assert cullinan["sales_brochure_document_count"] == 2
    # Same document_id with distinct filing serial/file names is a valid
    # multi-file variant, not a duplicate at the ingestion grain.
    assert cullinan["manifest_composite_duplicate_count"] == 0


def test_shkp_sales_gate_rejects_legacy_ready_flag_without_effective_interval():
    registry = pd.DataFrame([{
        "registry_key": "srpe:9146",
        "srpe_development_id": "9146",
        "development_name_en": "NOVO LAND",
        "phase_name_en": "PHASE 3A",
        "ownership_status": "consistent_numeric",
        # A stale/manual row may still contain the legacy flag, but it must
        # not open sales attribution without bounded phase dates.
        "ownership_attribution_ready": True,
        "pilot_status": "core_pilot",
        "manifest_status": "filings_available",
        "source_urls_json": "[]",
    }])
    manifest = pd.DataFrame([{
        "srpe_development_id": "9146",
        "document_category": "register_of_transactions",
        "document_id": "100",
        "serial_no": None,
        "file_name": "register.pdf",
    }])

    result = shkp_source.build_shkp_sales_ingestion_eligibility(registry, manifest)

    row = result.iloc[0]
    assert not bool(row["ownership_attribution_ready"])
    assert row["eligibility_status"] == "ownership_review_required"
    assert "effective interval" in row["eligibility_reason"]


def test_shkp_sales_gate_rejects_ready_flag_for_unresolved_jv():
    registry = pd.DataFrame([{
        "registry_key": "srpe:9565",
        "srpe_development_id": "9565",
        "development_name_en": "YOHO WEST",
        "phase_name_en": "PHASE 1",
        "ownership_status": "annual_jv_unresolved",
        "ownership_observed_pct": 100.0,
        "ownership_effective_from": "2024-01-01",
        "ownership_effective_to": "2025-12-31",
        "ownership_attribution_ready": True,
        "manifest_status": "filings_available",
        "source_urls_json": "[]",
    }])

    result = shkp_source.build_shkp_sales_ingestion_eligibility(registry, pd.DataFrame([{
        "srpe_development_id": "9565",
        "document_category": "register_of_transactions",
        "document_id": "100",
        "file_name": "register.pdf",
    }]))

    row = result.iloc[0]
    assert not bool(row["ownership_attribution_ready"])
    assert row["eligibility_status"] == "ownership_review_required"


def test_shkp_sales_ingestion_plan_only_allows_register_review_for_eligible_phase():
    registry = pd.DataFrame([
        {
            "registry_key": "srpe:9146",
            "srpe_development_id": "9146",
            "development_name_en": "NOVO LAND",
            "phase_name_en": "PHASE 2A",
            "ownership_status": "consistent_numeric",
            "curated_registry_ownership_pct": 100.0,
            "ownership_effective_from": "2024-01-01",
            "ownership_effective_to": "2025-12-31",
            "ownership_interval_status": "phase_specific_bounded_interval",
            "ownership_interval_evidence_type": "approved_phase_attribution_decision",
            "ownership_attribution_decision_id": "decision:novo-2a",
            "ownership_interval_promotion_status": "approved_phase_attribution",
            "ownership_attribution_ready": True,
            "curated_project_ids": "novo-land-2a",
            "curated_stock_codes": "0016",
            "pilot_status": "core_pilot",
            "manifest_status": "filings_available",
            "source_urls_json": "[]",
        },
        {
            "registry_key": "srpe:9785",
            "srpe_development_id": "9785",
            "development_name_en": "CULLINAN HARBOUR DEVELOPMENT",
            "phase_name_en": "PHASE 1",
            "ownership_status": "not_verified",
            "ownership_attribution_ready": False,
            "curated_project_ids": None,
            "curated_stock_codes": None,
            "pilot_status": "not_in_pilot",
            "manifest_status": "filings_available",
            "source_urls_json": "[]",
        },
    ])
    eligibility = pd.DataFrame([
        {
            "srpe_development_id": "9146",
            "eligibility_status": "eligible_register_price_review",
            "eligibility_reason": "numeric ownership reconciled and transaction register is available",
            "ownership_status": "consistent_numeric",
            "curated_registry_ownership_pct": 100.0,
            "ownership_effective_from": "2024-01-01",
            "ownership_effective_to": "2025-12-31",
            "ownership_interval_status": "phase_specific_bounded_interval",
            "ownership_interval_evidence_type": "approved_phase_attribution_decision",
            "ownership_attribution_decision_id": "decision:novo-2a",
            "ownership_interval_promotion_status": "approved_phase_attribution",
            "ownership_attribution_ready": True,
            "manifest_status": "filings_available",
            "manifest_document_count": 3,
            "register_document_count": 1,
            "price_list_document_count": 2,
            "sales_arrangement_document_count": 1,
            "sales_brochure_document_count": 1,
            "source_urls_json": "[]",
        },
        {
            "srpe_development_id": "9785",
            "eligibility_status": "ownership_review_required",
            "eligibility_reason": "SRPE filings are available but SHKP ownership/JV attribution is not reconciled",
            "ownership_status": "not_verified",
            "ownership_attribution_ready": False,
            "manifest_status": "filings_available",
            "manifest_document_count": 4,
            "register_document_count": 1,
            "price_list_document_count": 1,
            "sales_arrangement_document_count": 1,
            "sales_brochure_document_count": 1,
            "source_urls_json": "[]",
        },
    ])

    plan = shkp_source.build_shkp_sales_ingestion_plan(registry, eligibility)

    novo = plan.loc[plan["srpe_development_id"].eq("9146")].iloc[0]
    assert novo["ingestion_action"] == "download_register_and_price_lists"
    assert novo["allowed_document_categories"] == "register_of_transactions|price_list|sales_arrangement"
    assert novo["parser_gate_status"] == "pending_document_completeness"
    assert novo["coverage_status"] == "pilot_boundary_available"
    assert pd.isna(novo["blocked_reason"])

    cullinan = plan.loc[plan["srpe_development_id"].eq("9785")].iloc[0]
    assert cullinan["ingestion_action"] == "review_ownership_before_sales"
    assert pd.isna(cullinan["allowed_document_categories"])
    assert cullinan["parser_gate_status"] == "blocked_ownership"
    assert "ownership/JV" in cullinan["blocked_reason"]


class _FakeHtmlResponse:
    def __init__(self, html):
        self.content = html.encode("utf-8")
        self.text = html

    def raise_for_status(self):
        return None


class _FakeCorporateSession:
    def __init__(self):
        self.headers = {}

    def get(self, url, timeout):
        return _FakeHtmlResponse(
            '<a href="/docs/annual-report-2025.pdf">Annual Report 2025</a>'
            '<a href="/docs/q1.pdf">Quarterly update</a>'
            '<a href="/docs/announcement.pdf">Project announcement</a>'
        )


def test_shkp_corporate_document_catalog_classifies_pdf_links(monkeypatch, tmp_path):
    monkeypatch.setattr(
        shkp_source,
        "save_raw_snapshot",
        lambda *args, **kwargs: tmp_path / f"snapshot-{len(list(tmp_path.iterdir()))}.html",
    )

    frame = shkp_source.fetch_shkp_corporate_documents(session=_FakeCorporateSession())

    assert len(frame) == len(shkp_source.SHKP_CORPORATE_PAGES) * 3
    assert "annual_report" in set(frame["document_type"])
    assert frame["document_url"].str.startswith("https://www.shkp.com/").all()


def test_shkp_pipeline_disclosure_keeps_found_and_not_found_states(monkeypatch, tmp_path):
    monkeypatch.setattr(
        shkp_source,
        "save_raw_snapshot",
        lambda *args, **kwargs: tmp_path / "pipeline.html",
    )
    monkeypatch.setitem(
        shkp_source.SHKP_PIPELINE_DISCLOSURES[0],
        "items",
        (
            ("Found project", "planned_launch_10m", "Hong Kong", "project near MTR"),
            ("Missing project", "under_development", "Hong Kong", "phrase absent"),
        ),
    )

    class _PipelineSession:
        headers = {}

        def get(self, url, timeout):
            return _FakeHtmlResponse("The Group plans a project near MTR Station.")

    frame = shkp_source.fetch_shkp_pipeline_disclosures(session=_PipelineSession())

    assert set(frame["evidence_status"]) == {"found", "not_found"}
    assert frame.loc[frame["project_label"] == "Found project", "evidence_context"].iloc[0]


def test_shkp_annual_handover_word_parser_preserves_jv_and_columns():
    def word(text, x0, top):
        return {"text": text, "x0": x0, "top": top}

    words = [
        word("Project", 72, 10), word("Location", 202, 10), word("Usage", 305, 10),
        word("Interest", 394, 20), word("Area", 470, 20),
        word("YOHO", 72, 40), word("WEST", 106, 40), word("Phase", 139, 40), word("1", 167, 40),
        word("1", 202, 40), word("Tin", 210, 40), word("Yan", 228, 40), word("Road,", 248, 40),
        word("Residential", 305, 40), word("/", 357, 40), word("JV", 418, 40), word("748,000", 486, 40),
        word("Tin", 202, 53), word("Shui", 220, 53), word("Wai", 243, 53), word("Shops", 305, 53),
        word("NOVO", 72, 66), word("LAND", 106, 66), word("8", 202, 66), word("Yan", 210, 66),
        word("Po", 230, 66), word("Road,", 245, 66), word("Residential", 305, 66), word("100", 414, 66), word("694,000", 486, 66),
        word("Phases", 72, 79), word("3A", 105, 79), word("&", 120, 79), word("3B", 132, 79), word("Tuen", 202, 79), word("Mun", 228, 79),
        word("Total", 72, 95), word("1,442,000", 478, 95),
    ]

    rows = shkp_source._parse_shkp_handover_table_words(words, page_number=4, geography="Hong Kong")

    assert len(rows) == 2
    assert rows[0]["project_label"] == "YOHO WEST Phase 1"
    assert rows[0]["group_interest_raw"] == "JV"
    assert rows[0]["group_interest_pct"] is None
    assert rows[1]["project_label"] == "NOVO LAND Phases 3A & 3B"
    assert rows[1]["location"] == "8 Yan Po Road, Tuen Mun"
    assert rows[1]["attributable_gfa_sqft"] == 694000


def test_shkp_bd_crosswalk_is_conservative_and_keeps_unmatched_rows():
    shkp_crosswalk = pd.DataFrame(
        [
            {
                "marketing_name": "NOVO LAND",
                "srpe_development_id": "1",
                "srpe_phase_name": "NOVO LAND",
                "match_status": "matched",
                "shkp_source_url": "https://www.shkp.com/feed",
                "srpe_source_url": "https://www.srpe.gov.hk/api",
                "matched_at": "2026-08-01T00:00:00+00:00",
            },
            {
                "marketing_name": "UNKNOWN",
                "srpe_development_id": "2",
                "srpe_phase_name": "UNKNOWN",
                "match_status": "ambiguous",
                "shkp_source_url": "https://www.shkp.com/feed",
                "srpe_source_url": "https://www.srpe.gov.hk/api",
                "matched_at": "2026-08-01T00:00:00+00:00",
            },
        ]
    )
    srpe_index = pd.DataFrame(
        [
            {"development_id": "1", "address_en": "8 Yan Po Road"},
            {"development_id": "2", "address_en": "No Such Road"},
        ]
    )
    bd_events = pd.DataFrame(
        [
            {
                "permit_stage": "Plans Approved",
                "permit_number": None,
                "site_address": "8 Yan Po Road, Tuen Mun",
                "domestic_units_count": 100,
                "usable_floor_area_sqm": 5000,
                "parser_confidence": "HIGH",
            }
        ]
    )
    bd_events.attrs["source_url"] = '["https://www.bd.gov.hk/md53.xls"]'

    frame = shkp_source.build_shkp_bd_crosswalk(shkp_crosswalk, srpe_index, bd_events)

    assert set(frame["bd_match_status"]) == {"matched_needs_review", "unmatched"}
    assert frame.loc[frame["marketing_name"] == "NOVO LAND", "bd_domestic_units_count"].iloc[0] == 100
    assert frame.loc[frame["marketing_name"] == "UNKNOWN", "bd_candidate_count"].iloc[0] == 0


def test_shkp_bd_crosswalk_marks_shared_phase_address_as_ambiguous():
    shkp_crosswalk = pd.DataFrame([
        {
            "marketing_name": "Sierra Sea Phase 2A",
            "srpe_development_id": "11305",
            "srpe_phase_name": "SIERRA SEA",
            "match_status": "matched_needs_review",
        },
        {
            "marketing_name": "Sierra Sea Phase 2B",
            "srpe_development_id": "11345",
            "srpe_phase_name": "SIERRA SEA",
            "match_status": "matched_needs_review",
        },
    ])
    srpe_index = pd.DataFrame([
        {"development_id": "11305", "address_en": "8 Hoi Ying Road"},
        {"development_id": "11345", "address_en": "8 Hoi Ying Road"},
    ])
    bd_events = pd.DataFrame([
        {
            "permit_stage": "Occupation Permits (OP) Issued",
            "permit_number": "NT32/2026/OP",
            "site_address": "8 Hoi Ying Road, Tai Po",
            "domestic_units_count": 86,
            "usable_floor_area_sqm": 17.2,
            "parser_confidence": "HIGH",
        }
    ])

    frame = shkp_source.build_shkp_bd_crosswalk(shkp_crosswalk, srpe_index, bd_events)

    assert set(frame["bd_match_status"]) == {"ambiguous"}
    assert set(frame["bd_phase_candidate_count"]) == {2}
    assert set(frame["bd_candidate_count"]) == {1}
    assert frame["bd_match_method"].str.endswith("+phase_group_ambiguous").all()


def test_shkp_supporting_source_catalog_declares_landsd_tpb_bd_and_srpe(monkeypatch, tmp_path):
    monkeypatch.setattr(
        shkp_source,
        "save_raw_snapshot",
        lambda *args, **kwargs: tmp_path / "sources.json",
    )
    frame = shkp_source.fetch_shkp_supporting_source_catalog()
    assert {"Lands Department", "Town Planning Board", "Hong Kong Buildings Department"}.issubset(
        set(frame["agency"])
    )
    assert "SRPE / SRPA" in set(frame["agency"])
    assert frame["join_keys"].notna().all()
    iris = frame[frame["source_id"] == "land_registry_iris_search"].iloc[0]
    assert iris["status"] == "paid_manual"
    crt = frame[frame["source_id"] == "land_registry_street_index_crt"].iloc[0]
    assert crt["status"] == "reference_only_manual_browse"
    assert "must not be scraped" in crt["caveat"]


def test_shkp_land_planning_catalog_preserves_page_only_portal(monkeypatch, tmp_path):
    monkeypatch.setattr(
        shkp_source,
        "save_raw_snapshot",
        lambda *args, **kwargs: tmp_path / "landing.html",
    )

    class _SourceSession:
        headers = {}

        def get(self, url, timeout):
            return _FakeHtmlResponse(
                '<a href="/docs/lot.pdf">Land lot document</a>'
                '<a href="/applications/Y_TEST_1.html">Y/TEST/1</a>'
            )

    frame = shkp_source.fetch_shkp_land_planning_documents(session=_SourceSession())

    assert "landsd_land_sale_records" in set(frame["source_id"])
    assert "tpb_applications_under_processing" in set(frame["source_id"])
    ozp = frame[frame["source_id"] == "tpb_statutory_planning_portal"]
    assert set(ozp["status"]) == {"page_only"}
    assert frame["document_url"].notna().all()


def test_shkp_ownership_audit_flags_annual_jv_conflict():
    registry = pd.DataFrame(
        [
            {
                "stock_code": "0016",
                "listed_company_en": "Sun Hung Kai Properties",
                "project_name_en": "YOHO WEST",
                "project_aliases": "YOHO WEST Phase 1",
                "ownership_pct": "100.0",
                "last_verified_date": "2026-08-01",
            },
            {
                "stock_code": "0016",
                "listed_company_en": "Sun Hung Kai Properties",
                "project_name_en": "NOVO LAND",
                "project_aliases": "NOVO LAND Phase 3B",
                "ownership_pct": "100.0",
                "last_verified_date": "2026-08-01",
            },
        ]
    )
    annual = pd.DataFrame(
        [
            {
                "evidence_type": "handover_table",
                "geography": "Hong Kong",
                "project_label": "YOHO WEST Phase 1",
                "group_interest_raw": "JV",
                "group_interest_pct": None,
                "page_number": 4,
                "document_url": "https://www.shkp.com/report.pdf",
            },
            {
                "evidence_type": "handover_table",
                "geography": "Hong Kong",
                "project_label": "NOVO LAND Phases 3A & 3B",
                "group_interest_raw": "100",
                "group_interest_pct": 100.0,
                "page_number": 4,
                "document_url": "https://www.shkp.com/report.pdf",
            },
        ]
    )

    frame = shkp_source.build_shkp_ownership_evidence_audit(registry, annual)

    statuses = dict(zip(frame["registry_project_name"], frame["audit_status"]))
    assert statuses["YOHO WEST"] == "unresolved_jv"
    assert statuses["NOVO LAND"] == "consistent_numeric"


def test_shkp_ownership_audit_adapts_current_phase_registry_schema():
    registry = pd.DataFrame([{
        "srpe_development_id": "8605",
        "development_name_en": "NOVO LAND",
        "phase_name_en": "Phase 3B",
        "shkp_marketing_names": "NOVO LAND",
        "curated_stock_codes": "0016",
        "curated_registry_ownership_pct": 100.0,
        "last_verified_at": "2026-08-06T00:00:00+00:00",
    }])
    annual = pd.DataFrame([{
        "evidence_type": "handover_table",
        "geography": "Hong Kong",
        "project_label": "NOVO LAND Phases 3A & 3B",
        "group_interest_raw": "100",
        "group_interest_pct": 100.0,
        "page_number": 4,
        "document_url": "https://www.shkp.com/report.pdf",
    }])

    frame = shkp_source.build_shkp_ownership_evidence_audit(registry, annual)

    assert len(frame) == 1
    assert frame.iloc[0]["registry_project_name"] == "NOVO LAND Phase 3B"
    assert frame.iloc[0]["audit_status"] == "consistent_numeric"


def test_shkp_annual_srpe_crosswalk_keeps_ambiguous_phases_and_unmatched_labels():
    annual = pd.DataFrame(
        [
            {
                "report_id": "ar",
                "report_period_end": "2025-06-30",
                "evidence_type": "handover_table",
                "project_label": "NOVO LAND Phases 3A & 3B",
                "project_state": "handover_completed",
                "geography": "Hong Kong",
                "location": "8 Yan Po Road, Tuen Mun",
                "group_interest_raw": "100",
                "group_interest_pct": 100.0,
                "page_number": 4,
                "document_url": "https://www.shkp.com/report.pdf",
                "fetched_at": "2026-08-01T00:00:00+00:00",
            },
            {
                "report_id": "ar",
                "report_period_end": "2025-06-30",
                "evidence_type": "future_pipeline_text",
                "project_label": "Descriptive future project",
                "project_state": "planned_sale_10m",
                "geography": "Hong Kong",
                "location": None,
                "document_url": "https://www.shkp.com/report.pdf",
                "fetched_at": "2026-08-01T00:00:00+00:00",
            },
        ]
    )
    srpe = pd.DataFrame(
        [
            {
                "development_id": "1",
                "display_name": "NOVO LAND",
                "development_name_en": "NOVO LAND",
                "phase_name_en": "NOVO LAND PHASE 3A",
                "phase_no": "PHASE 3A",
                "address_en": "8 YAN PO ROAD",
            },
            {
                "development_id": "2",
                "display_name": "NOVO LAND",
                "development_name_en": "NOVO LAND",
                "phase_name_en": "NOVO LAND PHASE 3B",
                "phase_no": "PHASE 3B",
                "address_en": "8 YAN PO ROAD",
            },
        ]
    )

    frame = shkp_source.build_shkp_annual_srpe_crosswalk(annual, srpe)

    novo = frame[frame["project_label"].str.startswith("NOVO LAND")]
    assert len(novo) == 2
    assert set(novo["match_status"]) == {"ambiguous"}
    assert set(novo["candidate_count"]) == {2}
    assert frame.loc[frame["project_label"] == "Descriptive future project", "match_status"].iloc[0] == "unmatched"
    assert frame["ownership_status"].eq("not_verified").all()


def test_shkp_annual_srpe_crosswalk_uses_bounded_novo_phase_hint():
    annual = pd.DataFrame([{
        "report_id": "ar",
        "report_period_end": "2024-06-30",
        "evidence_type": "handover_table",
        "project_label": "NOVO LAND Phases 2A & 2B",
        "project_state": "handover_completed",
        "geography": "Hong Kong",
        "location": "8 Yan Po Road, Tuen Mun",
        "group_interest_raw": "100",
        "group_interest_pct": 100.0,
        "page_number": 12,
        "document_url": "https://www.shkp.com/report.pdf",
        "fetched_at": "2026-08-01T00:00:00+00:00",
    }])
    srpe = pd.DataFrame([
        {"development_id": "9146", "display_name": "NOVO LAND", "development_name_en": "NOVO LAND", "phase_name_en": "NOVO LAND PHASE 2A", "phase_no": "PHASE 2A", "address_en": "8 YAN PO ROAD"},
        {"development_id": "9085", "display_name": "NOVO LAND", "development_name_en": "NOVO LAND", "phase_name_en": "NOVO LAND PHASE 2B", "phase_no": "PHASE 2B", "address_en": "8 YAN PO ROAD"},
        {"development_id": "8605", "display_name": "NOVO LAND", "development_name_en": "NOVO LAND", "phase_name_en": "NOVO LAND PHASE 1A", "phase_no": "PHASE 1A", "address_en": "8 YAN PO ROAD"},
    ])

    frame = shkp_source.build_shkp_annual_srpe_crosswalk(annual, srpe)

    assert set(frame["srpe_development_id"]) == {"9146", "9085"}
    assert frame["match_status"].eq("ambiguous").all()
    assert frame["match_method"].str.contains("phase_hint_exact").all()


def test_shkp_annual_srpe_crosswalk_uses_sai_sha_phase_hint_across_aliases():
    annual = pd.DataFrame([{
        "report_id": "ar",
        "report_period_end": "2025-06-30",
        "evidence_type": "future_pipeline_text",
        "project_label": "Sai Sha Residences Phase 2A and 2B",
        "project_state": "planned_sale_10m",
        "geography": "Sai Sha",
        "location": "Sai Sha, New Territories",
        "group_interest_raw": "JV",
        "group_interest_pct": None,
        "page_number": 21,
        "document_url": "https://www.shkp.com/report.pdf",
        "fetched_at": "2026-08-01T00:00:00+00:00",
    }])
    srpe = pd.DataFrame([
        {"development_id": "11305", "display_name": "SIERRA SEA", "development_name_en": "SIERRA SEA", "phase_name_en": "SIERRA SEA PHASE 2A", "phase_no": "PHASE 2A", "address_en": "SAI SHA ROAD"},
        {"development_id": "11345", "display_name": "SIERRA SEA", "development_name_en": "SIERRA SEA", "phase_name_en": "SIERRA SEA PHASE 2B", "phase_no": "PHASE 2B", "address_en": "SAI SHA ROAD"},
        {"development_id": "10685", "display_name": "SIERRA SEA", "development_name_en": "SIERRA SEA", "phase_name_en": "SIERRA SEA PHASE 1A", "phase_no": "PHASE 1A", "address_en": "SAI SHA ROAD"},
    ])

    frame = shkp_source.build_shkp_annual_srpe_crosswalk(annual, srpe)

    assert set(frame["srpe_development_id"]) == {"11305", "11345"}
    assert frame["match_status"].eq("ambiguous").all()
    assert frame["match_method"].str.contains("phase_hint_exact").all()


def test_shkp_annual_major_project_crosswalk_uses_bounded_lot_hint_without_promotion():
    annual = pd.DataFrame([{
        "report_id": "ar",
        "report_period_end": "2023-06-30",
        "evidence_type": "major_project_under_development",
        "project_label": "Cullinan Sky",
        "project_state": "under_development_major_project",
        "geography": "Hong Kong",
        "location": "New Kowloon Inland Lot No. 6568",
        "group_interest_raw": "100% owned",
        "group_interest_pct": 100.0,
        "page_number": 33,
        "document_url": "https://www.shkp.com/ar.pdf",
        "fetched_at": "2026-08-02T00:00:00+00:00",
    }])
    srpe = pd.DataFrame([
        {"development_id": "9366", "display_name": "CULLINAN SKY", "development_name_en": "CULLINAN SKY DEVELOPMENT", "phase_name_en": "CULLINAN SKY", "phase_no": "PHASE 1"},
        {"development_id": "11005", "display_name": "CULLINAN SKY", "development_name_en": "CULLINAN SKY DEVELOPMENT", "phase_name_en": "CULLINAN SKY", "phase_no": "PHASE 2"},
    ])

    frame = shkp_source.build_shkp_annual_srpe_crosswalk(annual, srpe)

    assert set(frame["srpe_development_id"]) == {"9366", "11005"}
    assert frame["match_status"].eq("ambiguous").all()
    assert frame["match_method"].str.contains("lot_hint_exact").all()
    assert frame["ownership_status"].eq("not_verified").all()


def test_shkp_srpe_manifest_catalog_preserves_document_ids_without_downloading_pdfs(monkeypatch, tmp_path):
    payload = {
        "resultData": {
            "devInfoResp": {
                "dev": {
                    "engName": "TEST DEVELOPMENT",
                    "engPhaseName": "TEST PHASE 1",
                    "engPhaseNo": "PHASE 1",
                    "addresses": [{"engAddress": "1 TEST ROAD"}],
                },
                "transactions": [
                    {
                        "id": "trx-1",
                        "serialNo": "1",
                        "dateOfPrinting": "2026-01-02",
                        "file": {"fileName": "transaction.pdf", "fileSize": 1234, "submissionTime": "2026-01-03"},
                    }
                ],
                "prices": [],
                "salesArrangements": [],
                "brochureList": [],
            }
        }
    }

    class _ManifestSession:
        headers = {}

        def post(self, url, json, timeout):
            return _FakeResponse(payload)

    monkeypatch.setattr(
        shkp_source,
        "save_raw_snapshot",
        lambda *args, **kwargs: tmp_path / "manifest.json",
    )

    frame = shkp_source.fetch_shkp_srpe_document_manifest(
        ["123", "123"],
        session=_ManifestSession(),
        max_developments=10,
    )

    assert len(frame) == 1
    assert frame.loc[0, "srpe_development_id"] == "123"
    assert frame.loc[0, "document_id"] == "trx-1"
    assert frame.loc[0, "document_category"] == "register_of_transactions"
    assert frame.loc[0, "download_endpoint"].endswith("downloadTrx")
    assert frame.attrs["lineage_metadata"]["pdf_downloaded"] is False


def test_shkp_planning_crosswalk_preserves_unmatched_and_ambiguous_evidence():
    tpb = pd.DataFrame(
        [
            {
                "application_no": "Y/TEST/1",
                "application_received_date": "2026-01-02",
                "location_raw": "8 Yan Po Road, Tuen Mun",
                "proposal_raw": "Residential development",
                "detail_url": "https://www.tpb.gov.hk/en/plan_application/Y_TEST_1.html",
                "evidence_status": "application_detail",
            },
            {
                "application_no": "Y/UNKNOWN/1",
                "application_received_date": "2026-01-03",
                "location_raw": "Lot with no SRPE address",
                "proposal_raw": "Other use",
                "detail_url": "https://www.tpb.gov.hk/en/plan_application/Y_UNKNOWN_1.html",
                "evidence_status": "application_detail",
            },
        ]
    )
    landsd = pd.DataFrame(
        [
            {
                "development_name_raw": "NOVO LAND",
                "lot_no_raw": "Tuen Mun Town Lot 500",
                "parent_or_holding_company_or_developer_raw": "Raw Developer Label",
                "consent_or_approval_date": "2026-01-04",
                "document_url": "https://www.landsd.gov.hk/consent.pdf",
                "page_number": 2,
            }
        ]
    )
    srpe = pd.DataFrame(
        [
            {"development_id": "1", "display_name": "NOVO LAND", "development_name_en": "NOVO LAND", "phase_name_en": "NOVO LAND PHASE 3A", "address_en": "8 YAN PO ROAD"},
            {"development_id": "2", "display_name": "NOVO LAND", "development_name_en": "NOVO LAND", "phase_name_en": "NOVO LAND PHASE 3B", "address_en": "8 YAN PO ROAD"},
        ]
    )

    frame = shkp_source.build_shkp_planning_evidence_crosswalk(tpb, landsd, srpe)

    # The TPB location also matches both phases by address; each candidate is
    # retained, so two TPB + one unmatched TPB + two LandsD rows are emitted.
    assert len(frame) == 5
    assert set(frame["evidence_source"]) == {"tpb", "landsd"}
    novo = frame[frame["evidence_record_id"] == "https://www.landsd.gov.hk/consent.pdf#page=2"]
    assert set(novo["match_status"]) == {"ambiguous"}
    assert set(novo["candidate_count"]) == {2}
    assert set(novo["planning_consent_date"]) == {"2026-01-04"}
    assert frame.loc[frame["evidence_record_id"] == "Y/TEST/1", "planning_consent_date"].iloc[0] == "2026-01-02"
    assert frame.loc[frame["evidence_record_id"] == "Y/UNKNOWN/1", "match_status"].iloc[0] == "unmatched"
    assert frame["ownership_status"].eq("not_verified").all()
    assert frame["page_or_detail"].map(type).eq(str).all()


def test_shkp_planning_crosswalk_uses_audited_lot_bridge_when_name_is_unknown():
    landsd = pd.DataFrame(
        [
            {
                "development_name_raw": "Unknown",
                "lot_no_raw": "Lot 1071 in DD 103",
                "parent_or_holding_company_or_developer_raw": "Peak Harbour Development / Sun Hung Kai Properties",
                "consent_or_approval_date": "2026-06-03",
                "document_url": "https://www.landsd.gov.hk/yuen-long-consent.pdf",
                "page_number": 35,
            }
        ]
    )
    srpe = pd.DataFrame(
        [
            {
                "development_id": "11554",
                "display_name": "GARDEN REGENCY",
                "development_name_en": "GARDEN REGENCY",
                "phase_name_en": None,
                "address_en": "19 MA WO ROAD",
            },
            {
                "development_id": "99999",
                "display_name": "UNRELATED DEVELOPMENT",
                "development_name_en": "UNRELATED DEVELOPMENT",
                "phase_name_en": None,
                "address_en": "1 OTHER ROAD",
            },
        ]
    )

    frame = shkp_source.build_shkp_planning_evidence_crosswalk(
        pd.DataFrame(), landsd, srpe
    )

    assert len(frame) == 1
    assert frame.loc[0, "srpe_development_id"] == "11554"
    assert frame.loc[0, "match_status"] == "matched_needs_review"
    assert frame.loc[0, "match_method"] == "lot_hint_exact"
    assert frame.loc[0, "planning_consent_date"] == "2026-06-03"


def test_shkp_planning_crosswalk_narrows_explicit_phase_names_without_ownership_promotion():
    landsd = pd.DataFrame([
        {
            "development_name_raw": "Cullinan Sky Development (Phase 1)",
            "lot_no_raw": "NKIL 6568",
            "parent_or_holding_company_or_developer_raw": "Super Great Limited",
            "consent_or_approval_date": "2023-06-14",
            "document_url": "https://www.landsd.gov.hk/ke.pdf",
            "page_number": 10,
        },
        {
            "development_name_raw": "Tin Shui Wai Town Lot No. 23 Development (Phase 2) - YOHO WEST PARKSIDE",
            "lot_no_raw": "TSWTL 23",
            "parent_or_holding_company_or_developer_raw": "MTR Corporation Limited",
            "consent_or_approval_date": "2025-02-24",
            "document_url": "https://www.landsd.gov.hk/yl.pdf",
            "page_number": 20,
        },
    ])
    srpe = pd.DataFrame([
        {"development_id": "9366", "development_name_en": "CULLINAN SKY DEVELOPMENT", "phase_name_en": "CULLINAN SKY", "address_en": "10 CONCORDE ROAD"},
        {"development_id": "11005", "development_name_en": "CULLINAN SKY DEVELOPMENT", "phase_name_en": "CULLINAN SKY", "address_en": "10 CONCORDE ROAD"},
        {"development_id": "9565", "development_name_en": "TIN SHUI WAI TOWN LOT NO. 23 DEVELOPMENT", "phase_name_en": "YOHO WEST", "address_en": "1 TIN YAN ROAD"},
        {"development_id": "10585", "development_name_en": "TIN SHUI WAI TOWN LOT NO. 23 DEVELOPMENT", "phase_name_en": "YOHO WEST PARKSIDE", "address_en": "1 TIN YAN ROAD"},
    ])

    frame = shkp_source.build_shkp_planning_evidence_crosswalk(pd.DataFrame(), landsd, srpe)

    sky = frame.loc[frame["evidence_record_id"].str.contains("ke.pdf")]
    park = frame.loc[frame["evidence_record_id"].str.contains("yl.pdf")]
    assert sky["srpe_development_id"].tolist() == ["9366"]
    assert park["srpe_development_id"].tolist() == ["10585"]
    assert set(frame["match_status"]) == {"matched_needs_review"}
    assert frame["ownership_status"].eq("not_verified").all()


def test_shkp_pipeline_crosswalk_requires_name_anchor_and_preserves_phase_ambiguity():
    pipeline = pd.DataFrame([
        {
            "disclosure_id": "interim",
            "disclosure_type": "interim_results",
            "project_label": "Cullinan Harbour Phase 2",
            "status": "planned_launch_10m",
            "geography": "Kai Tak",
            "publication_date": "2026-02-26",
            "evidence_status": "found",
            "evidence_context": "second phase of Cullinan Harbour",
            "source_url": "https://www.shkp.com/interim",
            "fetched_at": "2026-08-01T00:00:00+00:00",
        },
        {
            "disclosure_id": "interim",
            "disclosure_type": "interim_results",
            "project_label": "City One Sha Tin project",
            "status": "planned_launch_10m",
            "geography": "Sha Tin",
            "publication_date": "2026-02-26",
            "evidence_status": "found",
            "evidence_context": "project near City One Station",
            "source_url": "https://www.shkp.com/interim",
            "fetched_at": "2026-08-01T00:00:00+00:00",
        },
        {
            "disclosure_id": "variant",
            "disclosure_type": "interim_results",
            "project_label": "Cullinan Harbour Phase 2",
            "status": "planned_launch_10m",
            "geography": "Kai Tak",
            "publication_date": "2026-02-26",
            "evidence_status": "not_found",
            "evidence_context": "",
            "source_url": "https://www.shkp.com/interim",
            "fetched_at": "2026-08-01T00:00:00+00:00",
        },
    ])
    srpe = pd.DataFrame([
        {
            "development_id": "10405",
            "development_name_en": "CULLINAN HARBOUR DEVELOPMENT",
            "phase_name_en": "CULLINAN HARBOUR PHASE 2A",
            "phase_no": "PHASE 2A",
            "address_en": "26 SHING FUNG ROAD",
            "planning_area_en": "KAI TAK",
        },
        {
            "development_id": "11516",
            "development_name_en": "CULLINAN HARBOUR DEVELOPMENT",
            "phase_name_en": "CULLINAN HARBOUR PHASE 2B",
            "phase_no": "PHASE 2B",
            "address_en": "26 SHING FUNG ROAD",
            "planning_area_en": "KAI TAK",
        },
        {
            "development_id": "999",
            "development_name_en": "UNRELATED SHA TIN HEIGHTS",
            "phase_name_en": "PHASE 1",
            "phase_no": "PHASE 1",
            "address_en": "1 SHA TIN ROAD",
            "planning_area_en": "SHA TIN",
        },
    ])

    frame = shkp_source.build_shkp_pipeline_srpe_crosswalk(pipeline, srpe)

    found = frame[frame["project_label"].eq("Cullinan Harbour Phase 2") & frame["evidence_status"].eq("found")]
    assert set(found["srpe_development_id"]) == {"10405", "11516"}
    assert set(found["match_status"]) == {"ambiguous"}
    assert set(found["ownership_status"]) == {"not_verified"}
    geography_candidates = frame[frame["match_method"].fillna("").str.contains("geography_candidate")]
    assert not geography_candidates.empty
    assert geography_candidates["match_method"].map(
        lambda value: bool({"name_exact", "base_name_candidate", "phase_name_candidate"} & set(value.split("+")))
    ).all()
    geography_only = frame[frame["project_label"].eq("City One Sha Tin project")]
    assert len(geography_only) == 1
    assert pd.isna(geography_only.iloc[0]["srpe_development_id"])
    assert geography_only.iloc[0]["match_status"] == "unmatched"
    not_found = frame[frame["disclosure_id"].eq("variant")]
    assert len(not_found) == 1
    assert not_found.iloc[0]["match_status"] == "not_evaluated"
    assert pd.isna(not_found.iloc[0]["srpe_development_id"])


def test_shkp_project_registry_rolls_up_found_pipeline_evidence_without_ownership_inference():
    srpe = pd.DataFrame([
        {
            "development_id": "10405",
            "display_name": "CULLINAN HARBOUR DEVELOPMENT",
            "development_name_en": "CULLINAN HARBOUR DEVELOPMENT",
            "phase_name_en": "CULLINAN HARBOUR PHASE 2A",
            "phase_no": "PHASE 2A",
            "address_en": "26 SHING FUNG ROAD",
            "planning_area_en": "KAI TAK",
            "active": "Y",
            "source_url": "https://www.srpe.gov.hk/index",
        }
    ])
    pipeline = pd.DataFrame([
        {
            "pipeline_evidence_key": "evidence-key",
            "disclosure_id": "interim",
            "project_label": "Cullinan Harbour Phase 2",
            "pipeline_status": "planned_launch_10m",
            "geography": "Kai Tak",
            "publication_date": "2026-02-26",
            "evidence_status": "found",
            "source_url": "https://www.shkp.com/interim",
            "srpe_development_id": "10405",
            "match_status": "matched_needs_review",
            "ownership_status": "not_verified",
        }
    ])

    frame = shkp_source.build_shkp_project_registry(srpe, pipeline_crosswalk=pipeline)

    row = frame.iloc[0]
    assert row["pipeline_status"] == "planned_launch_10m"
    assert row["pipeline_disclosure_labels"] == "Cullinan Harbour Phase 2"
    assert row["pipeline_disclosure_states"] == "planned_launch_10m"
    assert row["pipeline_disclosure_match_status"] == "matched_needs_review"
    assert row["pipeline_disclosure_rows"] == 1
    assert row["pipeline_disclosure_last_publication_date"] == "2026-02-26"
    assert row["ownership_status"] == "not_verified"
    assert not bool(row["ownership_attribution_ready"])
    assert "https://www.shkp.com/interim" in json.loads(row["source_urls_json"])


def test_shkp_project_registry_rolls_up_bd_lifecycle_candidates_without_ownership_inference():
    srpe = pd.DataFrame([{
        "development_id": "10405",
        "display_name": "CULLINAN HARBOUR DEVELOPMENT",
        "development_name_en": "CULLINAN HARBOUR DEVELOPMENT",
        "phase_name_en": "CULLINAN HARBOUR PHASE 2A",
        "phase_no": "PHASE 2A",
        "address_en": "26 SHING FUNG ROAD",
        "planning_area_en": "KAI TAK",
        "active": "Y",
        "source_url": "https://www.srpe.gov.hk/index",
    }])
    bd = pd.DataFrame([{
        "srpe_development_id": "10405",
        "bd_permit_stage": "Occupation Permits (OP) Issued",
        "bd_permit_number": "OP 123/2026",
        "bd_site_address": "26 SHING FUNG ROAD",
        "bd_domestic_units_count": 600,
        "bd_usable_floor_area_sqm": 45000,
        "bd_parser_confidence": "high",
        "bd_match_status": "matched_needs_review",
        "bd_phase_candidate_count": 1,
    }])

    frame = shkp_source.build_shkp_project_registry(srpe, bd_crosswalk=bd)

    row = frame.iloc[0]
    assert row["bd_match_status"] == "matched_needs_review"
    assert row["bd_permit_stages"] == "Occupation Permits (OP) Issued"
    assert row["bd_permit_numbers"] == "OP 123/2026"
    assert row["bd_domestic_units_count"] == "600"
    assert row["bd_usable_floor_area_sqm"] == "45000"
    assert row["bd_phase_candidate_counts"] == "1"
    assert row["bd_evidence_rows"] == 1
    assert row["ownership_status"] == "not_verified"


def test_shkp_pipeline_project_registry_keeps_unmatched_future_labels_out_of_sales():
    pipeline = pd.DataFrame([
        {
            "pipeline_evidence_key": "future-1",
            "disclosure_id": "interim",
            "disclosure_type": "interim_results",
            "project_label": "Cullinan Harbour Phase 2",
            "pipeline_status": "planned_launch_10m",
            "geography": "Kai Tak",
            "publication_date": "2026-02-26",
            "evidence_status": "found",
            "evidence_context": "second phase",
            "source_url": "https://www.shkp.com/interim",
            "srpe_development_id": "10405",
            "srpe_development_name": "CULLINAN HARBOUR DEVELOPMENT",
            "srpe_phase_name": "PHASE 2A",
            "match_status": "ambiguous",
            "candidate_count": 2,
            "matched_at": "2026-08-01T00:00:00+00:00",
        },
        {
            "pipeline_evidence_key": "future-1",
            "disclosure_id": "interim",
            "disclosure_type": "interim_results",
            "project_label": "Cullinan Harbour Phase 2",
            "pipeline_status": "planned_launch_10m",
            "geography": "Kai Tak",
            "publication_date": "2026-02-26",
            "evidence_status": "found",
            "evidence_context": "second phase",
            "source_url": "https://www.shkp.com/interim",
            "srpe_development_id": "11516",
            "srpe_development_name": "CULLINAN HARBOUR DEVELOPMENT",
            "srpe_phase_name": "PHASE 2B",
            "match_status": "ambiguous",
            "candidate_count": 2,
            "matched_at": "2026-08-01T00:00:00+00:00",
        },
    ])
    annual = pd.DataFrame([
        {
            "report_id": "ar-2025",
            "report_period_end": "2025-06-30",
            "evidence_type": "pipeline",
            "project_label": "Kwu Tung adjacent project Phase 1",
            "project_state": "planned_sale_10m",
            "geography": "Kwu Tung",
            "annual_document_url": "https://www.shkp.com/ar.pdf",
            "match_status": "unmatched",
            "candidate_count": 0,
            "matched_at": "2026-08-01T00:00:00+00:00",
        }
    ])

    frame = shkp_source.build_shkp_pipeline_project_registry(pipeline, annual)

    assert len(frame) == 2
    cullinan = frame.loc[frame["project_label"].eq("Cullinan Harbour Phase 2")].iloc[0]
    assert cullinan["pipeline_registry_key"] == "pipeline:future-1"
    assert cullinan["srpe_candidate_ids"] == "10405 | 11516"
    assert cullinan["srpe_match_status"] == "ambiguous"
    assert cullinan["ownership_status"] == "not_verified"
    assert cullinan["sales_ingestion_status"] == "not_ready"

    kwu = frame.loc[frame["project_label"].eq("Kwu Tung adjacent project Phase 1")].iloc[0]
    assert kwu["pipeline_registry_key"].startswith("annual:")
    assert pd.isna(kwu["srpe_candidate_ids"])
    assert kwu["srpe_match_status"] == "unmatched"
    assert kwu["ownership_status"] == "not_verified"


def test_shkp_ownership_review_queue_prioritizes_sales_blockers_without_promoting_them():
    registry = pd.DataFrame([
        {
            "registry_key": "srpe:9785",
            "srpe_development_id": "9785",
            "development_name_en": "CULLINAN HARBOUR DEVELOPMENT",
            "phase_name_en": "CULLINAN HARBOUR",
            "address_en": "26 SHING FUNG ROAD",
            "ownership_status": "not_verified",
            "ownership_attribution_ready": False,
            "manifest_status": "filings_available",
            "planning_match_status": "ambiguous",
            "pipeline_disclosure_match_status": "not_observed",
            "shkp_match_status": "matched_needs_review",
            "annual_match_status": "not_observed",
            "evidence_count": 6,
            "planning_lot_nos": "NKIL 6551",
            "planning_entity_labels": "Sun Hung Kai Properties Limited / Time Effort Limited",
            "source_urls_json": "[\"https://www.landsd.gov.hk/consent.pdf\"]",
        },
        {
            "registry_key": "srpe:2947",
            "srpe_development_id": "2947",
            "development_name_en": "UNRELATED",
            "phase_name_en": "PHASE 1",
            "address_en": "1 ROAD",
            "ownership_status": "not_verified",
            "ownership_attribution_ready": False,
            "manifest_status": "not_loaded",
            "planning_match_status": "not_observed",
            "pipeline_disclosure_match_status": "not_observed",
            "shkp_match_status": "not_observed",
            "annual_match_status": "not_observed",
            "evidence_count": 0,
        },
    ])
    eligibility = pd.DataFrame([
        {
            "srpe_development_id": "9785",
            "eligibility_status": "ownership_review_required",
        }
    ])

    queue = shkp_source.build_shkp_ownership_review_queue(registry, eligibility)

    assert queue["srpe_development_id"].tolist() == ["9785"]
    row = queue.iloc[0]
    assert row["review_scope"] == "sales_promotion_blocker"
    assert row["review_priority"] == "P0"
    assert "planning" in row["evidence_layers_present"]
    assert "manifest" in row["evidence_layers_present"]
    assert "ownership" in row["review_reason"]
    assert "LandsD" in row["suggested_next_source"]
    assert not bool(row["ownership_attribution_ready"])


def test_shkp_project_site_vendor_facts_extracts_static_and_next_data_notices(monkeypatch, tmp_path):
    html_static = """
    <html><body><p>Information on the Vendor</p>
    <p>Name of Development: Garden Regency</p>
    <p>Vendor: Ease Gold Development Limited | Holding Companies of the vendor: Sun Hung Kai Properties Limited, Vast Earn Limited | The estimated material date for the Development: 17 May 2027 |</p>
    </body></html>
    """
    html_next = r'''<script>\"label\":\"Vendor\",\"value\":\"\u003cp\u003eTippon Investment Enterprises Limited\u003c/p\u003e\",\"label\":\"Holding companies of the Vendor\",\"value\":\"\u003cp\u003eSun Hung Kai Properties Limited\u003c/p\u003e\", The estimated material date for the Development: 30 April 2027.</script>'''

    class _SiteSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout):
            return _FakeHtmlResponse(html_static if "garden" in url else html_next)

    monkeypatch.setattr(
        shkp_source,
        "save_raw_snapshot",
        lambda *args, **kwargs: tmp_path / f"{len(list(tmp_path.iterdir()))}.html",
    )
    catalog = pd.DataFrame([
        {
            "asset_type": "residential_for_sale",
            "marketing_name": "Garden Regency",
            "external_project_url": "https://garden.example/en",
            "source_record_id": "garden",
        },
        {
            "asset_type": "residential_for_sale",
            "marketing_name": "Lime Spark",
            "external_project_url": "https://lime.example/en-US",
            "source_record_id": "lime",
        },
    ])

    frame = shkp_source.fetch_shkp_project_site_vendor_facts(catalog, session=_SiteSession(), run_id="test")

    assert set(frame["site_evidence_status"]) == {"found"}
    garden = frame.loc[frame["marketing_name"].eq("Garden Regency")].iloc[0]
    lime = frame.loc[frame["marketing_name"].eq("Lime Spark")].iloc[0]
    assert garden["vendor_name"] == "Ease Gold Development Limited"
    assert "Sun Hung Kai Properties Limited" in garden["holding_companies"]
    assert garden["estimated_material_date"] == "17 May 2027"
    assert lime["vendor_name"] == "Tippon Investment Enterprises Limited"
    assert "Sun Hung Kai Properties Limited" in lime["holding_companies"]
    assert lime["estimated_material_date"] == "30 April 2027"


def test_shkp_project_site_vendor_facts_accepts_fullwidth_notice_separator(monkeypatch, tmp_path):
    html = """
    <html><body><p>
    Vendor: Well Capital (H.K.) Limited｜Holding companies of the Vendor:
    Sun Hung Kai Properties Limited, Time Effort Limited, Trade Up Ventures Limited｜
    Authorized Person: Example
    </p></body></html>
    """

    class _FullwidthSeparatorSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout):
            return _FakeHtmlResponse(html)

    monkeypatch.setattr(
        shkp_source,
        "save_raw_snapshot",
        lambda *args, **kwargs: tmp_path / "phase-2b.html",
    )
    catalog = pd.DataFrame([
        {
            "asset_type": "residential_for_sale",
            "marketing_name": "Cullinan Harbour Phase 2B",
            "external_project_url": "https://phase2b.example/en",
            "source_record_id": "phase-2b",
        }
    ])

    frame = shkp_source.fetch_shkp_project_site_vendor_facts(
        catalog,
        session=_FullwidthSeparatorSession(),
        run_id="test-fullwidth-separator",
    )

    assert frame.loc[0, "site_evidence_status"] == "found"
    assert frame.loc[0, "vendor_name"] == "Well Capital (H.K.) Limited"
    assert "Sun Hung Kai Properties Limited" in frame.loc[0, "holding_companies"]


def test_shkp_project_site_vendor_facts_uses_phase_specific_url_override(monkeypatch, tmp_path):
    html = """
    <html><body>
    Vendor: Well Capital (H.K.) Limited | Holding Companies of the vendor:
    Sun Hung Kai Properties Limited, Time Effort Limited, Trade Up Ventures Limited |
    Authorized Person: Example
    </body></html>
    """
    seen_urls = []

    class _OverrideSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout):
            seen_urls.append(url)
            return _FakeHtmlResponse(html)

    monkeypatch.setattr(
        shkp_source,
        "save_raw_snapshot",
        lambda *args, **kwargs: tmp_path / "phase-2a.html",
    )
    catalog = pd.DataFrame([
        {
            "asset_type": "residential_for_sale",
            "marketing_name": "Cullinan Harbour Phase 2A",
            "external_project_url": "https://www.cullinanharbour.com.hk",
            "source_record_id": "phase-2a",
        }
    ])

    frame = shkp_source.fetch_shkp_project_site_vendor_facts(
        catalog,
        session=_OverrideSession(),
        run_id="test-phase-override",
    )

    assert seen_urls == ["https://www.cullinanharbour.com.hk/phaseii/en/"]
    assert frame.loc[0, "site_evidence_status"] == "found"
    assert frame.loc[0, "vendor_name"] == "Well Capital (H.K.) Limited"


def test_shkp_project_site_vendor_facts_accepts_space_before_notice_colon(monkeypatch, tmp_path):
    html = """
    <html><body>
    Vendor : Well Capital (H.K.) Limited | Holding companies of the Vendor :
    Sun Hung Kai Properties Limited, Time Effort Limited, Trade Up Ventures Limited |
    Authorized Person of the Phase : Example
    </body></html>
    """

    class _SpaceBeforeColonSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout):
            return _FakeHtmlResponse(html)

    monkeypatch.setattr(
        shkp_source,
        "save_raw_snapshot",
        lambda *args, **kwargs: tmp_path / "phase-1.html",
    )
    catalog = pd.DataFrame([
        {
            "asset_type": "residential_for_sale",
            "marketing_name": "Cullinan Harbour Phase 1",
            "external_project_url": "https://phase1.example/en",
            "source_record_id": "phase-1",
        }
    ])

    frame = shkp_source.fetch_shkp_project_site_vendor_facts(
        catalog,
        session=_SpaceBeforeColonSession(),
        run_id="test-space-before-colon",
    )

    assert frame.loc[0, "site_evidence_status"] == "found"
    assert frame.loc[0, "vendor_name"] == "Well Capital (H.K.) Limited"
    assert "Sun Hung Kai Properties Limited" in frame.loc[0, "holding_companies"]


def test_shkp_project_site_vendor_facts_parses_owner_and_person_so_engaged_fields(monkeypatch, tmp_path):
    html = """
    <html><body>
    Vendor: MTR Corporation Limited (as “Owner”), Best Vision Development Limited (as “Person so engaged”) |
    Holding company of the Vendor (Owner): Not applicable |
    Holding companies of the Vendor (Person so engaged): Better Sun Limited, Time Effort Limited, Sun Hung Kai Properties Limited |
    Authorized Person for the Phase: Example |
    The estimated material date for the Phase: 30 September 2026 |
    </body></html>
    """

    class _YohoSession:
        def __init__(self):
            self.headers = {}

        def get(self, url, timeout):
            return _FakeHtmlResponse(html)

    monkeypatch.setattr(
        shkp_source,
        "save_raw_snapshot",
        lambda *args, **kwargs: tmp_path / "yoho-west.html",
    )
    catalog = pd.DataFrame([
        {
            "asset_type": "residential_for_sale",
            "marketing_name": "YOHO WEST",
            "external_project_url": "https://www.yohowest.com.hk",
            "source_record_id": "yoho-west",
        }
    ])

    frame = shkp_source.fetch_shkp_project_site_vendor_facts(
        catalog,
        session=_YohoSession(),
        run_id="test-owner-person-so-engaged",
    )

    row = frame.iloc[0]
    assert row["site_evidence_status"] == "found"
    assert "MTR Corporation Limited" in row["vendor_name"]
    assert "Best Vision Development Limited" in row["vendor_name"]
    assert "Sun Hung Kai Properties Limited" in row["holding_companies"]
    assert row["estimated_material_date"] == "30 September 2026"


def test_shkp_project_site_vendor_crosswalk_keeps_site_facts_separate_from_ownership():
    facts = pd.DataFrame([
        {
            "marketing_name": "Cullinan Sky",
            "source_record_id": "site-1",
            "vendor_name": "Super Great Limited",
            "holding_companies": "Sun Hung Kai Properties Limited",
            "estimated_material_date": None,
            "site_evidence_status": "found",
            "source_url": "https://www.cullinansky.com.hk",
            "fetched_at": "2026-08-01T00:00:00+00:00",
        }
    ])
    candidates = pd.DataFrame([
        {
            "marketing_name": "Cullinan Sky",
            "srpe_development_id": "9366",
            "srpe_phase_name": "CULLINAN SKY",
            "srpe_address_en": "10 CONCORDE ROAD",
            "match_method": "website_domain_exact",
            "match_status": "ambiguous",
            "candidate_count": 2,
        },
        {
            "marketing_name": "Cullinan Sky",
            "srpe_development_id": "11005",
            "srpe_phase_name": "CULLINAN SKY PHASE 2",
            "srpe_address_en": "10 CONCORDE ROAD",
            "match_method": "website_domain_exact",
            "match_status": "ambiguous",
            "candidate_count": 2,
        },
    ])

    frame = shkp_source.build_shkp_project_site_vendor_crosswalk(facts, candidates)

    assert set(frame["srpe_development_id"]) == {"9366", "11005"}
    assert set(frame["match_status"]) == {"ambiguous"}
    assert frame["ownership_status"].eq("not_verified").all()
    assert frame["holding_companies"].str.contains("Sun Hung Kai Properties Limited").all()


def test_shkp_ownership_evidence_timeline_preserves_date_semantics_and_blocks_promotion():
    legal = pd.DataFrame([
        {
            "observation_id": "9366:2025",
            "srpe_development_id": "9366",
            "srpe_development_name": "CULLINAN SKY",
            "srpe_phase_name": "CULLINAN SKY",
            "ownership_observed_as_of": "2025-06-30",
            "ownership_pct": 100.0,
            "subsidiary_spv_name": "Super Great Limited",
            "observation_type": "annual_principal_subsidiary",
            "promotion_status": "blocked_effective_interval",
            "ownership_source_url": "https://example.test/ar.pdf",
            "ownership_source_page": "220",
            "caveat": "snapshot only",
        }
    ])
    annual = pd.DataFrame([
        {
            "srpe_development_id": "9366",
            "srpe_development_name": "CULLINAN SKY",
            "srpe_phase_name": "CULLINAN SKY",
            "report_period_end": "2024-06-30",
            "evidence_type": "major_project_under_development",
            "annual_group_interest_raw": "100% owned",
            "annual_group_interest_pct": 100.0,
            "match_status": "matched_needs_review",
            "annual_document_url": "https://example.test/ar-2024.pdf",
            "annual_page_number": 35,
            "report_id": "ar-2024",
        }
    ])
    planning = pd.DataFrame([
        {
            "evidence_source": "landsd",
            "evidence_record_id": "landsd:1",
            "evidence_date": "2023-06-14",
            "planning_consent_date": "2023-06-14",
            "development_name_raw": "Cullinan Sky Development (Phase 1)",
            "lot_no_raw": "NKIL 6568",
            "parent_or_developer_raw": "Super Great Limited / SHKP",
            "source_url": "https://example.test/landsd.pdf",
            "page_or_detail": "page=8",
            "srpe_development_id": "9366",
            "srpe_development_name": "CULLINAN SKY",
            "srpe_phase_name": "CULLINAN SKY",
        }
    ])
    site = pd.DataFrame([
        {
            "marketing_name": "Cullinan Sky",
            "srpe_development_id": "9366",
            "srpe_phase_name": "CULLINAN SKY",
            "estimated_material_date": "2027-01-01",
            "vendor_name": "Super Great Limited",
            "holding_companies": "Sun Hung Kai Properties Limited",
            "site_source_url": "https://example.test/project",
            "matched_at": "2026-08-02T00:00:00Z",
        }
    ])
    principal = pd.DataFrame([
        {
            "crosswalk_id": "cw-9366-2025",
            "srpe_development_id": "9366",
            "srpe_development_name": "CULLINAN SKY",
            "srpe_phase_name": "CULLINAN SKY",
            "as_of_date": "2025-06-30",
            "spv_name": "Super Great Limited",
            "attributable_equity_pct": 100.0,
            "match_status": "matched_legal_spv_phase_review_only",
            "annual_document_url": "https://example.test/ar-2025.pdf",
            "printed_page": "220",
            "annual_observation_consistency_status": "date_and_pct_consistent",
        }
    ])

    timeline = shkp_source.build_shkp_ownership_evidence_timeline(
        legal_ownership_observations=legal,
        annual_principal_subsidiary_crosswalk=principal,
        annual_srpe_crosswalk=annual,
        planning_evidence_crosswalk=planning,
        site_vendor_crosswalk=site,
    )

    assert set(timeline["date_semantics"]) == {
        "ownership_observed_as_of",
        "annual_principal_subsidiary_as_of",
        "annual_report_period_end",
        "regulatory_consent_or_approval_date",
        "estimated_material_date",
    }
    assert timeline["timeline_id"].is_unique
    assert timeline["effective_from"].isna().all()
    assert timeline["effective_to"].isna().all()
    assert timeline["promotion_status"].str.startswith("blocked").all()


def test_completion_schedule_parser_keeps_jv_and_completion_window():
    words = [
        {"text": "Scheduled", "x0": 12, "top": 10},
        {"text": "for", "x0": 50, "top": 10},
        {"text": "Completion", "x0": 70, "top": 10},
        {"text": "in", "x0": 120, "top": 10},
        {"text": "FY2027/28", "x0": 140, "top": 10},
        {"text": "1)", "x0": 12, "top": 30},
        {"text": "New", "x0": 27, "top": 30},
        {"text": "Kowloon", "x0": 45, "top": 30},
        {"text": "Inland", "x0": 80, "top": 30},
        {"text": "Lot", "x0": 125, "top": 30},
        {"text": "No.", "x0": 145, "top": 30},
        {"text": "6568", "x0": 165, "top": 30},
        {"text": "Cullinan", "x0": 249, "top": 30},
        {"text": "Sky", "x0": 300, "top": 30},
        {"text": "100", "x0": 425, "top": 30},
        {"text": "1", "x0": 466, "top": 30},
        {"text": ",066,000", "x0": 470, "top": 30},
        {"text": "1", "x0": 751, "top": 30},
        {"text": ",066,000", "x0": 755, "top": 30},
        {"text": "2)", "x0": 12, "top": 45},
        {"text": "Tin", "x0": 27, "top": 45},
        {"text": "Wing", "x0": 45, "top": 45},
        {"text": "Stop", "x0": 70, "top": 45},
        {"text": "Development", "x0": 95, "top": 45},
        {"text": "Phase", "x0": 160, "top": 45},
        {"text": "2", "x0": 190, "top": 45},
        {"text": "YOHO", "x0": 249, "top": 45},
        {"text": "WEST", "x0": 280, "top": 45},
        {"text": "PARKSIDE", "x0": 315, "top": 45},
        {"text": "JV", "x0": 425, "top": 45},
        {"text": "236,000", "x0": 466, "top": 45},
        {"text": "236,000", "x0": 751, "top": 45},
    ]

    frame = shkp_source._parse_shkp_completion_schedule_words(
        words,
        page_number=1,
        schedule_date="2026-02-28",
    )

    assert len(frame) == 2
    assert frame[0]["completion_window"] == "FY2027/28"
    assert frame[0]["residential_gfa_sqft"] == 1_066_000
    assert frame[1]["group_interest_raw"] == "JV"
    assert frame[1]["group_interest_pct"] is None


def test_completion_schedule_parser_handles_historical_left_margin_and_completed_heading():
    words = [
        {"text": "Completed", "x0": 20, "top": 10},
        {"text": "in", "x0": 70, "top": 10},
        {"text": "FY2022/23", "x0": 90, "top": 10},
        {"text": "1)", "x0": 25.3, "top": 30},
        {"text": "Tuen", "x0": 40, "top": 30},
        {"text": "Mun", "x0": 58, "top": 30},
        {"text": "Town", "x0": 73, "top": 30},
        {"text": "Lot", "x0": 92, "top": 30},
        {"text": "No.", "x0": 104, "top": 30},
        {"text": "483", "x0": 116, "top": 30},
        {"text": "NOVO", "x0": 253, "top": 30},
        {"text": "LAND", "x0": 275, "top": 30},
        {"text": "100", "x0": 413, "top": 30},
        {"text": "8", "x0": 457, "top": 30},
        {"text": ",07,000", "x0": 461, "top": 30},
        {"text": "8", "x0": 739, "top": 30},
        {"text": ",07,000", "x0": 743, "top": 30},
    ]

    frame = shkp_source._parse_shkp_completion_schedule_words(
        words,
        page_number=1,
        schedule_date="2023-09-30",
    )

    assert len(frame) == 1
    assert frame[0]["lot_description"] == "Tuen Mun Town Lot No. 483"
    assert frame[0]["group_interest_raw"] == "100"
    assert frame[0]["completion_window"] == "FY2022/23"
    assert frame[0]["residential_gfa_sqft"] == 807000


def test_completion_schedule_parser_does_not_leak_others_row_into_last_project():
    """A final project row is followed by an unnumbered ``Others`` subtotal.

    In the live 2023/2026 PDFs the last project's total column is visually
    aligned, but the old parser kept reading the following ``Others`` line and
    concatenated both totals (for example ``110000606000``).  ``Others`` is a
    subtotal, not part of the project row, and must terminate the row window.
    """
    words = [
        {"text": "1)", "x0": 12, "top": 10},
        {"text": "First", "x0": 27, "top": 10},
        {"text": "Project", "x0": 70, "top": 10},
        {"text": "100", "x0": 425, "top": 10},
        {"text": "1", "x0": 751, "top": 10},
        {"text": "10,000", "x0": 755, "top": 10},
        {"text": "Others", "x0": 27, "top": 25},
        {"text": "1", "x0": 751, "top": 25},
        {"text": "25,000", "x0": 755, "top": 25},
        {"text": "Total for Major Projects", "x0": 27, "top": 40},
        {"text": "35,000", "x0": 751, "top": 40},
    ]

    frame = shkp_source._parse_shkp_completion_schedule_words(
        words,
        page_number=1,
        schedule_date="2026-02-28",
    )

    assert len(frame) == 1
    assert frame[0]["total_gfa_sqft"] == 110000


def test_annual_report_row_geography_uses_location_for_older_mainland_template():
    assert shkp_source._classify_shkp_annual_row_geography(
        "Chancheng, Foshan",
        "Hong Kong",
    ) == "Mainland"
    assert shkp_source._classify_shkp_annual_row_geography(
        "8 Yan Po Road, Tuen Mun",
        "Hong Kong",
    ) == "Hong Kong"


def test_annual_handover_parser_handles_compact_2023_columns():
    words = [
        {"text": "Project", "x0": 56, "top": 10},
        {"text": "Location", "x0": 184, "top": 10},
        {"text": "Usage", "x0": 329, "top": 10},
        {"text": "Interest", "x0": 419, "top": 20},
        {"text": "square", "x0": 488, "top": 20},
        {"text": "1)", "x0": 56, "top": 40},
        {"text": "NOVO", "x0": 57, "top": 40},
        {"text": "LAND", "x0": 81, "top": 40},
        {"text": "Phases", "x0": 104, "top": 40},
        {"text": "2A", "x0": 130, "top": 40},
        {"text": "&", "x0": 142, "top": 40},
        {"text": "2B", "x0": 149, "top": 40},
        {"text": "8", "x0": 184, "top": 40},
        {"text": "Yan", "x0": 191, "top": 40},
        {"text": "Po", "x0": 206, "top": 40},
        {"text": "Road,", "x0": 217, "top": 40},
        {"text": "Tuen", "x0": 239, "top": 40},
        {"text": "Mun", "x0": 259, "top": 40},
        {"text": "Residential/Shops", "x0": 329, "top": 40},
        {"text": "100", "x0": 438, "top": 40},
        {"text": "931,000", "x0": 511, "top": 40},
    ]

    rows = shkp_source._parse_shkp_handover_table_words(
        words,
        page_number=12,
        geography="Hong Kong",
    )

    assert rows[0]["project_label"] == "NOVO LAND Phases 2A & 2B"
    assert rows[0]["location"] == "8 Yan Po Road, Tuen Mun"
    assert rows[0]["group_interest_pct"] == 100.0
    assert rows[0]["attributable_gfa_sqft"] == 931000


def test_annual_handover_parser_handles_legacy_project_location_interest_columns():
    words = [
        {"text": "Project", "x0": 68, "top": 10},
        {"text": "Location", "x0": 184, "top": 10},
        {"text": "Interest", "x0": 389, "top": 10},
        {"text": "(%)", "x0": 429, "top": 10},
        {"text": "(square", "x0": 488, "top": 10},
        {"text": "feet)", "x0": 523, "top": 10},
        {"text": "Park", "x0": 68, "top": 40},
        {"text": "Island", "x0": 91, "top": 40},
        {"text": "Phase", "x0": 119, "top": 40},
        {"text": "3", "x0": 149, "top": 40},
        {"text": "8", "x0": 184, "top": 40},
        {"text": "Pak", "x0": 193, "top": 40},
        {"text": "Lai", "x0": 212, "top": 40},
        {"text": "Road,", "x0": 228, "top": 40},
        {"text": "Ma", "x0": 256, "top": 40},
        {"text": "Wan", "x0": 272, "top": 40},
        {"text": "Joint", "x0": 387, "top": 40},
        {"text": "venture", "x0": 411, "top": 40},
        {"text": "1,017,000", "x0": 498, "top": 40},
    ]

    rows = shkp_source._parse_shkp_handover_table_words(
        words,
        page_number=11,
        geography="Hong Kong",
    )

    assert len(rows) == 1
    assert rows[0]["project_label"] == "Park Island Phase 3"
    assert rows[0]["location"] == "8 Pak Lai Road, Ma Wan"
    assert rows[0]["group_interest_raw"] == "Joint venture"
    assert rows[0]["attributable_gfa_sqft"] == 1_017_000


def test_annual_major_project_parser_keeps_lot_ownership_and_future_facts_separate():
    text = """
    Cullinan Sky
    New Kowloon Inland Lot No. 6568
    (100% owned)
    Site area : 178,000 square feet
    Gross floor area : 1.1 million square feet (residential)
    220,000 square feet (retail)
    Approximate : 1,500 number of units
    Expected date of : from first half of 2025, in phases
    Certificate of Compliance/Consent to Assign
    """

    rows = shkp_source._parse_shkp_major_project_column_text(
        text,
        page_number=33,
        geography="Hong Kong",
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["evidence_type"] == "major_project_under_development"
    assert row["project_label"] == "Cullinan Sky"
    assert row["location"] == "New Kowloon Inland Lot No. 6568"
    assert row["group_interest_pct"] == 100.0
    assert row["site_area_sqft"] == 178000
    assert row["residential_gfa_sqft"] == 1100000
    assert row["retail_gfa_sqft"] == 220000
    assert row["approximate_units"] == 1500
    assert row["completion_window"] == "from first half of 2025, in phases"
    assert row["project_state"] == "under_development_major_project"


def test_completion_schedule_crosswalk_keeps_grouped_lot_ambiguity_and_jv():
    schedules = pd.DataFrame([
        {
            "schedule_id": "feb",
            "schedule_date": "2026-02-28",
            "project_row_no": 1,
            "lot_description": "New Kowloon Inland Lot No. 6568 Phases 1 & 2",
            "project_label": "Cullinan Sky / Cullinan Sky Mall",
            "group_interest_raw": "100",
            "group_interest_pct": 100.0,
            "completion_window": "1H of FY2025/26",
            "document_url": "https://example/schedule.pdf",
            "source_url": "https://example/schedule.pdf",
        },
        {
            "schedule_id": "feb",
            "schedule_date": "2026-02-28",
            "project_row_no": 11,
            "lot_description": "Tin Wing Stop Development Phase 2",
            "project_label": "YOHO WEST PARKSIDE",
            "group_interest_raw": "JV",
            "group_interest_pct": None,
            "completion_window": "FY2026/27",
            "document_url": "https://example/schedule.pdf",
            "source_url": "https://example/schedule.pdf",
        },
    ])
    srpe = pd.DataFrame([
        {"development_id": "9366", "development_name_en": "CULLINAN SKY DEVELOPMENT", "phase_name_en": "CULLINAN SKY", "phase_no": "PHASE 1", "address_en": "10 CONCORDE ROAD"},
        {"development_id": "11005", "development_name_en": "CULLINAN SKY DEVELOPMENT", "phase_name_en": "CULLINAN SKY", "phase_no": "PHASE 2", "address_en": "10 CONCORDE ROAD"},
        {"development_id": "10585", "development_name_en": "TIN SHUI WAI TOWN LOT NO. 23 DEVELOPMENT", "phase_name_en": "YOHO WEST PARKSIDE", "phase_no": "2", "address_en": "1 TIN YAN ROAD"},
    ])

    frame = shkp_source.build_shkp_completion_schedule_crosswalk(schedules, srpe)

    sky = frame[frame["project_row_no"].eq(1)]
    assert set(sky["srpe_development_id"]) == {"9366", "11005"}
    assert sky["match_status"].eq("ambiguous").all()
    yoho = frame[frame["project_row_no"].eq(11)].iloc[0]
    assert yoho["srpe_development_id"] == "10585"
    assert yoho["ownership_status"] == "schedule_jv_unresolved"


def test_completion_schedule_ownership_evidence_is_non_promoting():
    crosswalk = pd.DataFrame([
        {
            "schedule_id": "feb",
            "schedule_date": "2026-02-28",
            "project_row_no": 1,
            "lot_description": "New Kowloon Inland Lot No. 6568 Phases 1 & 2",
            "project_label": "Cullinan Sky / Cullinan Sky Mall",
            "group_interest_raw": "100",
            "group_interest_pct": 100.0,
            "srpe_development_id": "9366",
            "srpe_development_name": "CULLINAN SKY DEVELOPMENT",
            "srpe_phase_name": "CULLINAN SKY",
            "srpe_phase_no": "PHASE 1",
            "match_status": "ambiguous",
            "document_url": "https://example/schedule.pdf",
            "source_url": "https://example/schedule.pdf",
        },
        {
            "schedule_id": "feb",
            "schedule_date": "2026-02-28",
            "project_row_no": 10,
            "lot_description": "Lot No. 1071 in DD 103, Kam Tin North, Yuen Long",
            "project_label": None,
            "group_interest_raw": "100",
            "group_interest_pct": 100.0,
            "srpe_development_id": "11554",
            "srpe_development_name": "GARDEN REGENCY",
            "srpe_phase_name": None,
            "srpe_phase_no": None,
            "match_status": "matched_needs_review",
            "document_url": "https://example/schedule.pdf",
            "source_url": "https://example/schedule.pdf",
        },
        {
            "schedule_id": "feb",
            "schedule_date": "2026-02-28",
            "project_row_no": 11,
            "lot_description": "Tin Wing Stop Development Phase 2",
            "project_label": "YOHO WEST PARKSIDE",
            "group_interest_raw": "JV",
            "group_interest_pct": None,
            "srpe_development_id": "10585",
            "srpe_development_name": "TIN SHUI WAI TOWN LOT NO. 23 DEVELOPMENT",
            "srpe_phase_name": "YOHO WEST PARKSIDE",
            "srpe_phase_no": "2",
            "match_status": "matched_needs_review",
            "document_url": "https://example/schedule.pdf",
            "source_url": "https://example/schedule.pdf",
        },
    ])

    frame = shkp_source.build_shkp_completion_schedule_ownership_evidence(crosswalk)

    assert len(frame) == 3
    sky = frame.loc[frame["srpe_development_id"].eq("9366")].iloc[0]
    assert sky["evidence_status"] == "reported_numeric_grouped_lot"
    assert sky["ownership_promotion_status"] == "blocked_phase_group_ambiguous"
    garden = frame.loc[frame["srpe_development_id"].eq("11554")].iloc[0]
    assert garden["legal_lot_bridge_status"] == "exact_legal_lot_bridge_with_supplemental_brochure"
    assert garden["ownership_promotion_status"] == "blocked_spv_reconciliation"
    yoho = frame.loc[frame["srpe_development_id"].eq("10585")].iloc[0]
    assert yoho["evidence_status"] == "reported_jv"
    assert pd.isna(yoho["group_interest_pct"])


def test_completion_schedule_reconciliation_joins_annual_and_vendor_evidence_without_promotion():
    crosswalk = pd.DataFrame([
        {
            "schedule_id": "feb",
            "schedule_date": "2026-02-28",
            "project_row_no": 1,
            "lot_description": "New Kowloon Inland Lot No. 6568 Phases 1 & 2",
            "project_label": "Cullinan Sky / Cullinan Sky Mall",
            "group_interest_raw": "100",
            "group_interest_pct": 100.0,
            "completion_window": "1H of FY2025/26",
            "srpe_development_id": "9366",
            "srpe_development_name": "CULLINAN SKY DEVELOPMENT",
            "srpe_phase_name": "CULLINAN SKY",
            "srpe_phase_no": "PHASE 1",
            "match_status": "ambiguous",
            "candidate_count": 2,
            "document_url": "https://example/schedule.pdf",
        },
        {
            "schedule_id": "feb",
            "schedule_date": "2026-02-28",
            "project_row_no": 10,
            "lot_description": "Lot No. 1071 in DD 103, Kam Tin North, Yuen Long",
            "project_label": None,
            "group_interest_raw": "100",
            "group_interest_pct": 100.0,
            "completion_window": "FY2026/27",
            "srpe_development_id": "11554",
            "srpe_development_name": "GARDEN REGENCY",
            "srpe_phase_name": None,
            "srpe_phase_no": None,
            "match_status": "matched_needs_review",
            "candidate_count": 1,
            "document_url": "https://example/schedule.pdf",
        },
        {
            "schedule_id": "feb",
            "schedule_date": "2026-02-28",
            "project_row_no": 11,
            "lot_description": "Tin Wing Stop Development Phase 2",
            "project_label": "YOHO WEST PARKSIDE",
            "group_interest_raw": "JV",
            "group_interest_pct": None,
            "completion_window": "FY2026/27",
            "srpe_development_id": "10585",
            "srpe_development_name": "TIN SHUI WAI TOWN LOT NO. 23 DEVELOPMENT",
            "srpe_phase_name": "YOHO WEST PARKSIDE",
            "srpe_phase_no": "2",
            "match_status": "matched_needs_review",
            "candidate_count": 1,
            "document_url": "https://example/schedule.pdf",
        },
    ])
    annual = pd.DataFrame([
        {
            "report_period_end": "2025-06-30",
            "report_id": "ar2526",
            "project_label": "Garden Regency",
            "annual_group_interest_raw": "100",
            "annual_group_interest_pct": 100.0,
            "annual_document_url": "https://example/annual.pdf",
            "match_status": "matched_needs_review",
            "srpe_development_id": "11554",
        },
        {
            "report_period_end": "2025-06-30",
            "report_id": "ar2526",
            "project_label": "YOHO WEST",
            "annual_group_interest_raw": "JV",
            "annual_group_interest_pct": None,
            "annual_document_url": "https://example/annual.pdf",
            "match_status": "ambiguous",
            "srpe_development_id": "10585",
        },
    ])
    sites = pd.DataFrame([
        {
            "marketing_name": "Garden Regency",
            "site_evidence_status": "found",
            "vendor_name": "Ease Gold Development Limited",
            "holding_companies": "Sun Hung Kai Properties Limited, Vast Earn Limited",
            "site_source_url": "https://www.gardenregency.com/en/",
            "match_status": "matched",
            "candidate_count": 1,
            "srpe_development_id": "11554",
        },
    ])

    frame = shkp_source.build_shkp_completion_schedule_reconciliation(crosswalk, annual, sites)

    assert len(frame) == 3
    sky = frame.loc[frame["srpe_development_id"].eq("9366")].iloc[0]
    assert sky["reconciliation_status"] == "grouped_phase_ambiguous"
    assert sky["ownership_promotion_status"] == "blocked_phase_group_ambiguous"
    garden = frame.loc[frame["srpe_development_id"].eq("11554")].iloc[0]
    assert garden["reconciliation_status"] == "numeric_interest_corroborated_vendor_found"
    assert garden["ownership_promotion_status"] == "blocked_spv_reconciliation"
    assert "annual.pdf" in garden["evidence_urls_json"]
    yoho = frame.loc[frame["srpe_development_id"].eq("10585")].iloc[0]
    assert yoho["reconciliation_status"] == "jv_unresolved"
    assert yoho["ownership_promotion_status"] == "blocked_jv_unresolved"
