import pandas as pd

from src.hk_real_estate.shkp_bd_history import (
    _official_role_evidence_as_site_evidence,
    _indicative_ownership_context,
    _pdf_context_for_cluster,
    _pdf_phase_mentions,
    build_shkp_bd_history_crosswalk,
    build_shkp_bd_phase_group_evidence,
    build_shkp_bd_phase_permit_candidate_evidence,
    build_shkp_bd_phase_permit_reconciliation,
    build_shkp_bd_phase_ownership_review,
    build_shkp_bd_phase_resolution_candidates,
    build_shkp_bd_history_entity_resolution_review,
    build_shkp_bd_history_entity_resolution_review_queue,
    build_shkp_bd_history_entity_resolution_summary,
)


def test_indicative_ownership_context_keeps_multi_phase_stakes_separate():
    roster = pd.DataFrame([
        {
            "srpe_development_id": "100",
            "indicative_owner_status": "likely_shkp_numeric_snapshot",
            "indicative_ownership_pct": 100.0,
            "indicative_ownership_pct_low": 100.0,
            "indicative_ownership_pct_high": 100.0,
            "indicative_numeric_consistency_status": "single_snapshot_value",
            "indicative_evidence_basis": "annual_report_group_interest_snapshot",
            "indicative_evidence_level": "indicative",
            "indicative_evidence_source_count": 1,
            "indicative_sales_use_status": "indicative_only",
            "strict_ownership_attribution_ready": False,
        },
        {
            "srpe_development_id": "200",
            "indicative_owner_status": "likely_shkp_jv_unquantified",
            "indicative_numeric_consistency_status": "not_observed",
            "indicative_evidence_basis": "jv_wording",
            "indicative_evidence_level": "indicative",
            "indicative_evidence_source_count": 1,
            "indicative_sales_use_status": "gross_only",
            "strict_ownership_attribution_ready": False,
        },
    ])
    roles = {"100": [{"evidence_id": "role:100"}], "200": [{"evidence_id": "role:200"}]}
    result = _indicative_ownership_context(
        ["100", "200"],
        {"100": [roster.iloc[0].to_dict()], "200": [roster.iloc[1].to_dict()]},
        roles,
    )
    assert result["indicative_ownership_context_status"] == "mixed_or_incomplete_candidate_phase_context"
    assert result["indicative_ownership_role_alignment_status"] == "numeric_snapshot_with_role_context"
    assert result["indicative_ownership_pct"] is None
    assert '"srpe_development_id": "100"' in result["indicative_phase_ownership_context_json"]


def test_phase_ownership_review_rollup_does_not_assign_shared_permit_or_blend_stakes():
    queue = pd.DataFrame([
        {
            "srpe_development_id": "100",
            "marketing_name": "Example",
            "srpe_phase_name": "Phase 1A",
            "srpe_address_en": "1 Shared Road",
            "phase_group_id": "group:shared",
            "phase_group_member_ids": "100; 200",
            "entity_resolution_status": "ambiguous",
            "review_priority": "P0",
            "bd_history_row_count": 4,
            "bd_distinct_permit_number_count": 1,
            "bd_source_urls": "https://bd.example",
        },
        {
            "srpe_development_id": "200",
            "marketing_name": "Example",
            "srpe_phase_name": "Phase 1B",
            "srpe_address_en": "1 Shared Road",
            "phase_group_id": "group:shared",
            "phase_group_member_ids": "100; 200",
            "entity_resolution_status": "ambiguous",
            "review_priority": "P0",
            "bd_history_row_count": 4,
            "bd_distinct_permit_number_count": 1,
            "bd_source_urls": "https://bd.example",
        },
    ])
    candidates = pd.DataFrame([{
        "phase_group_id": "group:shared",
        "candidate_phase_ids": "100; 200",
        "phase_context_review_status": "primary_pdf_phase_context_supported_not_assigned",
        "phase_context_reviewed_candidate_ids": "100",
        "source_urls": "https://bd.example; https://srpe.example",
    }])
    reconciliation = pd.DataFrame([{
        "candidate_phase_ids": "100; 200",
        "phase_context_review_status": "phase_context_supported_not_assigned",
        "phase_context_reviewed_candidate_ids": "100",
        "source_urls": "https://bd.example",
    }])
    roster = pd.DataFrame([
        {
            "srpe_development_id": "100",
            "indicative_owner_status": "likely_shkp_numeric_snapshot",
            "indicative_ownership_pct": 100.0,
            "indicative_ownership_pct_low": 100.0,
            "indicative_ownership_pct_high": 100.0,
            "indicative_numeric_consistency_status": "single_snapshot_value",
            "indicative_evidence_basis": "annual_report_group_interest_snapshot",
            "indicative_evidence_level": "indicative",
            "indicative_evidence_source_count": 1,
            "indicative_sales_use_status": "indicative_only",
            "strict_ownership_attribution_ready": False,
        },
        {
            "srpe_development_id": "200",
            "indicative_owner_status": "likely_shkp_jv_unquantified",
            "indicative_numeric_consistency_status": "not_observed",
            "indicative_evidence_basis": "jv_wording",
            "indicative_evidence_level": "indicative",
            "indicative_evidence_source_count": 1,
            "indicative_sales_use_status": "gross_only",
            "strict_ownership_attribution_ready": False,
        },
    ])
    roles = pd.DataFrame([
        {"srpe_development_id": "100", "evidence_id": "role:100", "phase_label": "Phase 1A", "source_url": "https://role.example/100"},
        {"srpe_development_id": "200", "evidence_id": "role:200", "phase_label": "Phase 1B", "source_url": "https://role.example/200"},
    ])
    result = build_shkp_bd_phase_ownership_review(
        queue,
        candidates,
        reconciliation,
        ownership_roster=roster,
        phase_role_evidence=roles,
    )
    assert set(result["srpe_development_id"]) == {"100", "200"}
    phase_100 = result.loc[result["srpe_development_id"].eq("100")].iloc[0]
    phase_200 = result.loc[result["srpe_development_id"].eq("200")].iloc[0]
    assert phase_100["phase_context_review_status"] == "phase_context_supported_not_assigned"
    assert phase_200["phase_context_review_status"] == "unresolved_primary_document_context"
    assert phase_100["indicative_ownership_pct"] == 100.0
    assert pd.isna(phase_200["indicative_ownership_pct"])
    assert result["ownership_promotion_status"].eq("blocked_address_only").all()
    assert result["permit_attribution_status"].eq("blocked_address_only").all()
    assert result["research_only"].all()


def test_pdf_phase_mentions_preserves_alphanumeric_phase_tokens():
    tokens, snippets = _pdf_phase_mentions(
        "Apartment blocks (phase 1A and 1B); later phases 2A & 2B."
    )
    assert tokens == ["1A", "1B", "2A", "2B"]
    assert snippets == ["phase 1A and 1B", "phases 2A & 2B"]


def test_pdf_context_without_srpe_phase_numbers_is_not_called_a_conflict():
    cluster = pd.DataFrame(
        [{
            "bd_permit_number": "OP/1",
            "bd_source_url": "https://bd.example",
            "bd_source_pdf_page": 10,
            "bd_site_address": "1 Test Road",
            "bd_permit_stage": "Occupation Permits (OP) Issued",
        }]
    )
    context = pd.DataFrame(
        [{
            "bd_pdf_context_status": "permit_page_phase_tokens_observed",
            "bd_pdf_phase_tokens": "1A; 1B",
            "bd_pdf_phase_snippets": "phase 1A and 1B",
            "bd_pdf_permit_number": "OP/1",
            "bd_pdf_permit_stage": "Occupation Permits (OP) Issued",
            "bd_pdf_site_address": "1 Test Road",
            "bd_pdf_source_url": "https://bd.example",
            "bd_pdf_source_page": "10",
        }]
    )
    result = _pdf_context_for_cluster(
        cluster,
        context,
        phase_ids=["100", "200"],
        phase_nos={"100": None, "200": None},
    )
    assert result["phase_context_concordance_status"] == "pdf_phase_tokens_not_comparable_no_candidate_phase_nos"
    assert result["bd_pdf_phase_candidate_ids"] is None


def test_pdf_context_can_point_to_another_phase_in_the_same_address_group():
    cluster = pd.DataFrame(
        [{
            "bd_permit_number": "OP/1",
            "bd_source_url": "https://bd.example",
            "bd_source_pdf_page": 10,
            "bd_site_address": "1 Test Road",
            "bd_permit_stage": "Occupation Permits (OP) Issued",
        }]
    )
    context = pd.DataFrame(
        [{
            "bd_pdf_context_status": "permit_page_phase_tokens_observed",
            "bd_pdf_phase_tokens": "1",
            "bd_pdf_phase_snippets": "phase 1",
            "bd_pdf_permit_number": "OP/1",
            "bd_pdf_permit_stage": "Occupation Permits (OP) Issued",
            "bd_pdf_site_address": "1 Test Road",
            "bd_pdf_source_url": "https://bd.example",
            "bd_pdf_source_page": "10",
        }]
    )
    result = _pdf_context_for_cluster(
        cluster,
        context,
        phase_ids=["200"],
        phase_nos={"100": "Phase 1", "200": "Phase 2"},
        group_phase_ids=["100", "200"],
    )
    assert result["bd_pdf_phase_candidate_ids"] is None
    assert result["bd_pdf_group_phase_candidate_ids"] == "100"
    assert result["phase_context_concordance_status"] == "pdf_context_points_to_other_group_phase"


def test_pdf_context_distinguishes_same_family_phase_variant_from_true_conflict():
    cluster = pd.DataFrame([{
        "bd_permit_number": "OP/VARIANT",
        "bd_source_url": "https://bd.example/variant",
        "bd_source_pdf_page": 27,
        "bd_site_address": "8 Hoi Ying Road",
        "bd_permit_stage": "Occupation Permits (OP) Issued",
    }])
    context = pd.DataFrame([{
        "bd_pdf_context_status": "permit_page_phase_tokens_observed",
        "bd_pdf_phase_tokens": "1A(1)",
        "bd_pdf_phase_snippets": "phase 1A(1)",
        "bd_pdf_permit_number": "OP/VARIANT",
        "bd_pdf_permit_stage": "Occupation Permits (OP) Issued",
        "bd_pdf_site_address": "8 Hoi Ying Road",
        "bd_pdf_source_url": "https://bd.example/variant",
        "bd_pdf_source_page": "27",
    }])

    result = _pdf_context_for_cluster(
        cluster,
        context,
        phase_ids=["100", "200"],
        phase_nos={"100": "Phase 1A(2)", "200": "Phase 1B"},
    )

    assert result["phase_context_concordance_status"] == "pdf_context_same_family_different_phase_variant"


def test_pdf_context_surfaces_tokens_missing_from_srpe_candidate_set():
    cluster = pd.DataFrame([{
        "bd_permit_number": "OP/1",
        "bd_source_url": "https://bd.example/op1.pdf",
        "bd_source_pdf_page": 10,
        "bd_site_address": "1 Shared Road",
        "bd_permit_stage": "Occupation Permits (OP) Issued",
    }])
    pdf_context = pd.DataFrame([{
        "bd_pdf_context_status": "permit_page_phase_tokens_observed",
        "bd_pdf_phase_tokens": "1A; 1B",
        "bd_pdf_phase_snippets": "phase 1A and 1B",
        "bd_pdf_permit_number": "OP/1",
        "bd_pdf_source_url": "https://bd.example/op1.pdf",
        "bd_pdf_source_page": 10,
        "bd_pdf_site_address": "1 Shared Road",
        "bd_pdf_permit_stage": "Occupation Permits (OP) Issued",
    }])
    result = _pdf_context_for_cluster(
        cluster,
        pdf_context,
        phase_ids=["100"],
        phase_nos={"100": "1B"},
        group_phase_ids=["100"],
    )
    assert result["bd_pdf_phase_candidate_ids"] == "100"
    assert result["bd_pdf_unmatched_phase_tokens"] == "1A"
    assert result["bd_pdf_token_coverage_status"] == "some_pdf_phase_tokens_not_in_candidate_set"


def test_bd_history_crosswalk_retains_unmatched_candidates_and_blocks_ownership():
    candidates = pd.DataFrame(
        [
            {
                "srpe_development_id": "100",
                "marketing_name": "Example Phase",
                "srpe_phase_name": "Phase 1",
                "match_status": "matched_needs_review",
                "shkp_source_url": "https://shkp.example",
                "srpe_source_url": "https://srpe.example",
            },
            {
                "srpe_development_id": "200",
                "marketing_name": "Unmatched Phase",
                "srpe_phase_name": "Phase 1",
                "match_status": "matched_needs_review",
            },
        ]
    )
    srpe = pd.DataFrame(
        [
            {"development_id": "100", "phase_name_en": "Phase 1", "address_en": "123 Test Road"},
            {"development_id": "200", "phase_name_en": "Phase 1", "address_en": "9 Missing Road"},
        ]
    )
    history = pd.DataFrame(
        [
            {
                "digest_month": "2025-01-01",
                "observation_month": "2025-01-01",
                "revision_status": "as_published",
                "permit_stage": "Occupation Permits (OP) Issued",
                "permit_number": "HK1/2025/OP",
                "site_address": "123 Test Road, Hong Kong",
                "domestic_units_count": 100,
                "usable_floor_area_sqm": 5000,
                "applicant": "Example Ltd",
                "parser_confidence": "HIGH",
                "parser_quality_flag": "ok",
                "source_pdf_page": 10,
                "source_url": "https://bd.example",
            }
        ]
    )
    result = build_shkp_bd_history_crosswalk(candidates, srpe, history)

    assert len(result) == 2
    hit = result[result["srpe_development_id"].eq("100")].iloc[0]
    miss = result[result["srpe_development_id"].eq("200")].iloc[0]
    assert hit["bd_match_status"] == "matched_needs_review"
    assert hit["project_identity_status"] == "address_candidate_only"
    assert hit["ownership_promotion_status"] == "blocked_address_only"
    assert miss["bd_match_status"] == "unmatched"
    assert pd.isna(miss["digest_month"])


def test_bd_history_crosswalk_does_not_call_repeated_history_rows_ambiguous():
    candidates = pd.DataFrame(
        [
            {
                "srpe_development_id": "100",
                "marketing_name": "Example Phase",
                "srpe_phase_name": "Phase 1",
                "match_status": "matched_needs_review",
            }
        ]
    )
    srpe = pd.DataFrame(
        [{"development_id": "100", "phase_name_en": "Phase 1", "address_en": "123 Test Road"}]
    )
    history = pd.DataFrame(
        [
            {
                "digest_month": "2025-01-01",
                "observation_month": "2025-01-01",
                "permit_stage": "Plans Approved",
                "site_address": "123 Test Road, Hong Kong",
                "source_url": "https://bd.example/1",
            },
            {
                "digest_month": "2025-02-01",
                "observation_month": "2025-02-01",
                "permit_stage": "Consent to Commence",
                "site_address": "123 Test Road, Hong Kong",
                "source_url": "https://bd.example/2",
            },
        ]
    )
    result = build_shkp_bd_history_crosswalk(candidates, srpe, history)

    assert len(result) == 2
    assert result["bd_candidate_count"].eq(2).all()
    assert result["bd_phase_candidate_count"].eq(1).all()
    assert result["bd_match_status"].eq("matched_needs_review").all()


def test_bd_history_crosswalk_reserves_ambiguous_for_shared_srpe_address():
    candidates = pd.DataFrame(
        [
            {"srpe_development_id": "100", "srpe_phase_name": "Phase 1"},
            {"srpe_development_id": "200", "srpe_phase_name": "Phase 2"},
        ]
    )
    srpe = pd.DataFrame(
        [
            {"development_id": "100", "phase_name_en": "Phase 1", "address_en": "123 Test Road"},
            {"development_id": "200", "phase_name_en": "Phase 2", "address_en": "123 Test Road"},
        ]
    )
    history = pd.DataFrame(
        [
            {
                "digest_month": "2025-01-01",
                "observation_month": "2025-01-01",
                "permit_stage": "Plans Approved",
                "site_address": "123 Test Road, Hong Kong",
                "source_url": "https://bd.example",
            }
        ]
    )
    result = build_shkp_bd_history_crosswalk(candidates, srpe, history)

    assert result["bd_match_status"].eq("ambiguous").all()
    assert result["bd_phase_candidate_count"].eq(2).all()


def test_phase_group_evidence_keeps_shared_address_and_publication_order_context_only():
    crosswalk = pd.DataFrame(
        [
            {
                "srpe_development_id": "100",
                "srpe_phase_name": "Phase 1",
                "srpe_address_en": "123 Test Road",
                "bd_match_method": "address_exact",
                "bd_match_status": "ambiguous",
                "bd_permit_stage": "Occupation Permits (OP) Issued",
                "bd_permit_number": "HK1/2025/OP",
                "bd_site_address": "123 Test Road",
                "bd_applicant": "Example Ltd",
                "bd_source_url": "https://bd.example/2025",
            },
            {
                "srpe_development_id": "200",
                "srpe_phase_name": "Phase 2",
                "srpe_address_en": "123 Test Road",
                "bd_match_method": "address_exact",
                "bd_match_status": "ambiguous",
                "bd_permit_stage": "Occupation Permits (OP) Issued",
                "bd_permit_number": "HK1/2025/OP",
                "bd_site_address": "123 Test Road",
                "bd_applicant": "Example Ltd",
                "bd_source_url": "https://bd.example/2025",
            },
        ]
    )
    srpe = pd.DataFrame(
        [
            {"development_id": "100", "phase_name_en": "Phase 1", "srpe_earliest_publication": "2024-01-01"},
            {"development_id": "200", "phase_name_en": "Phase 2", "srpe_earliest_publication": "2025-06-01"},
        ]
    )

    result = build_shkp_bd_phase_group_evidence(crosswalk, srpe_index=srpe)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["group_resolution_status"] == "shared_address_group"
    assert row["group_evidence_status"] == "address_and_bd_cluster_observed"
    assert row["srpe_phase_ids"] == "100; 200"
    assert row["bd_permit_years"] == "2025"
    assert row["bd_distinct_permit_number_count"] == 1
    assert "published_by_observed_permit_year" in row["srpe_phase_order_context_json"]
    assert row["ownership_promotion_status"] == "blocked_address_only"
    assert row["permit_attribution_status"] == "blocked_address_only"


def test_phase_group_evidence_uses_official_schedule_labels_as_group_context_only():
    crosswalk = pd.DataFrame(
        [
            {
                "srpe_development_id": phase_id,
                "srpe_phase_name": phase_name,
                "srpe_address_en": "8 Test Road",
                "bd_match_method": "address_exact",
                "bd_match_status": "ambiguous",
                "bd_permit_number": "NT1/2024/OP",
                "bd_site_address": "8 Test Road",
                "bd_source_url": "https://bd.example/2024",
            }
            for phase_id, phase_name in (("100", "Phase 1A"), ("200", "Phase 1B"), ("300", "Phase 2A"))
        ]
    )
    srpe = pd.DataFrame(
        [
            {"development_id": "100", "phase_name_en": "Phase 1A", "phase_no": "1A"},
            {"development_id": "200", "phase_name_en": "Phase 1B", "phase_no": "1B"},
            {"development_id": "300", "phase_name_en": "Phase 2A", "phase_no": "2A"},
        ]
    )
    schedule = pd.DataFrame(
        [
            {
                "schedule_date": "2024-02-28",
                "project_row_no": 1,
                "lot_description": "Test Lot Phases 1A & 1B",
                "project_label": "Example Development",
                "srpe_development_id": phase_id,
                "srpe_phase_name": phase_name,
                "match_status": "ambiguous",
                "match_confidence": "medium",
                "group_interest_raw": "100",
                "group_interest_pct": 100.0,
                "ownership_status": "schedule_numeric_reported",
                "source_url": "https://shkp.example/schedule.pdf",
            }
            for phase_id, phase_name in (("100", "Phase 1A"), ("200", "Phase 1B"), ("300", "Phase 2A"))
        ]
    )

    result = build_shkp_bd_phase_group_evidence(crosswalk, srpe_index=srpe, schedule_crosswalk=schedule)

    row = result.iloc[0]
    assert row["official_schedule_evidence_status"] == "official_schedule_grouped"
    assert row["schedule_phase_group_sets"] == "100,200"
    assert "300" not in row["schedule_phase_group_sets"]
    assert row["schedule_ownership_status"] == "schedule_numeric_reported"
    assert row["ownership_promotion_status"] == "blocked_address_only"


def test_bd_history_entity_review_is_one_row_per_phase_and_preserves_block():
    crosswalk = pd.DataFrame(
        [
            {
                "srpe_development_id": "100",
                "marketing_name": "Single phase",
                "srpe_phase_name": "Phase 1",
                "srpe_address_en": "1 Test Road",
                "crosswalk_match_status": "matched",
                "digest_month": "2025-01-01",
                "bd_permit_stage": "Plans Approved",
                "bd_permit_number": "BD-100",
                "bd_site_address": "1 Test Road, Hong Kong",
                "bd_parser_confidence": "HIGH",
                "bd_parser_quality_flag": "ok",
                "bd_match_method": "address_exact",
                "bd_match_status": "matched_needs_review",
                "bd_candidate_count": 2,
                "bd_phase_candidate_count": 1,
                "ownership_promotion_status": "approved_by_bad_input",
                "bd_source_url": "https://bd.example/100/1",
            },
            {
                "srpe_development_id": "100",
                "marketing_name": "Single phase",
                "srpe_phase_name": "Phase 1",
                "srpe_address_en": "1 Test Road",
                "crosswalk_match_status": "matched",
                "digest_month": "2025-02-01",
                "bd_permit_stage": "Occupation Permits (OP) Issued",
                "bd_permit_number": "BD-100",
                "bd_site_address": "1 Test Road, Hong Kong",
                "bd_parser_confidence": "HIGH",
                "bd_parser_quality_flag": "ok",
                "bd_match_method": "address_exact",
                "bd_match_status": "matched_needs_review",
                "bd_candidate_count": 2,
                "bd_phase_candidate_count": 1,
                "ownership_promotion_status": "approved_by_bad_input",
                "bd_source_url": "https://bd.example/100/2",
            },
            {
                "srpe_development_id": "200",
                "marketing_name": "Shared address",
                "srpe_phase_name": "Phase 2",
                "srpe_address_en": "2 Shared Road",
                "crosswalk_match_status": "ambiguous",
                "digest_month": "2025-03-01",
                "bd_permit_stage": "Plans Approved",
                "bd_permit_number": None,
                "bd_site_address": "2 Shared Road, Hong Kong",
                "bd_match_method": "address_contains",
                "bd_match_status": "ambiguous",
                "bd_candidate_count": 1,
                "bd_phase_candidate_count": 2,
                "ownership_promotion_status": "approved_by_bad_input",
                "bd_source_url": "https://bd.example/200",
            },
            {
                "srpe_development_id": "300",
                "marketing_name": "Unmatched",
                "srpe_phase_name": "Phase 3",
                "srpe_address_en": "3 Missing Road",
                "crosswalk_match_status": "matched_needs_review",
                "bd_match_method": "none",
                "bd_match_status": "unmatched",
                "bd_candidate_count": 0,
                "bd_phase_candidate_count": 1,
                "ownership_promotion_status": "approved_by_bad_input",
            },
        ]
    )

    queue, summary = build_shkp_bd_history_entity_resolution_review(crosswalk)

    assert len(queue) == 3
    assert queue["srpe_development_id"].tolist() == ["200", "100", "300"]
    assert queue["entity_resolution_status"].tolist() == [
        "ambiguous",
        "matched_needs_review",
        "unmatched",
    ]
    assert queue["review_priority"].tolist() == ["P0", "P1", "P2"]
    assert queue["review_queue_rank"].tolist() == [1, 2, 3]
    assert queue["ownership_promotion_status"].eq("blocked_address_only").all()
    assert queue["permit_attribution_status"].eq("blocked_address_only").all()
    single_phase = queue.loc[queue["srpe_development_id"].eq("100")].iloc[0]
    assert single_phase["bd_history_row_count"] == 2
    assert single_phase["bd_digest_month_first_observed"] == "2025-01-01"
    assert single_phase["bd_digest_month_last_observed"] == "2025-02-01"
    assert single_phase["bd_distinct_permit_number_count"] == 1
    assert summary.iloc[0]["candidate_phase_count"] == 3
    assert summary.iloc[0]["phase_with_bd_address_hit_count"] == 2
    assert summary.iloc[0]["ambiguous_phase_count"] == 1
    assert summary.iloc[0]["matched_needs_review_phase_count"] == 1
    assert summary.iloc[0]["unmatched_phase_count"] == 1
    assert summary.iloc[0]["matched_bd_history_row_count"] == 3
    assert summary.iloc[0]["distinct_bd_permit_number_count"] == 1
    assert summary.iloc[0]["ownership_promotion_status"] == "blocked_address_only"


def test_bd_history_entity_review_empty_input_has_explicit_zero_denominators():
    queue = build_shkp_bd_history_entity_resolution_review_queue(pd.DataFrame())
    summary = build_shkp_bd_history_entity_resolution_summary(pd.DataFrame())

    assert queue.empty
    assert list(queue.columns)
    assert len(summary) == 1
    assert summary.iloc[0]["candidate_phase_count"] == 0
    assert summary.iloc[0]["blocked_address_only_phase_count"] == 0
    assert bool(summary.iloc[0]["research_only"])


def test_bd_history_entity_review_attaches_site_role_evidence_without_resolving_shared_address():
    crosswalk = pd.DataFrame(
        [
            {
                "srpe_development_id": "100",
                "marketing_name": "NOVO LAND",
                "srpe_phase_name": "Phase 2A",
                "srpe_address_en": "8 YAN PO ROAD",
                "bd_match_method": "address_exact",
                "bd_match_status": "ambiguous",
                "bd_phase_candidate_count": 4,
                "bd_candidate_count": 2,
                "bd_permit_stage": "Plans Approved",
                "bd_site_address": "8 YAN PO ROAD",
                "digest_month": "2024-01-01",
                "ownership_promotion_status": "approved_by_bad_input",
            }
        ]
    )
    site_evidence = pd.DataFrame(
        [
            {
                "srpe_development_id": "100",
                "shkp_match_status": "site_no_shkp_keyword",
                "fetch_status": "ok_short_or_js",
                "resolved_url": "https://www.novoland2a.com.hk",
            },
            {
                "srpe_development_id": "100",
                "shkp_match_status": "site_named_shkp",
                "fetch_status": "rendered_ok",
                "vendor_name": "Example Vendor Ltd",
                "holding_companies": "Sun Hung Kai Properties Limited, Example Holdings",
                "resolved_url": "https://www.novoland2a.com.hk/en/home/index.html",
            },
        ]
    )

    queue, summary = build_shkp_bd_history_entity_resolution_review(crosswalk, site_evidence)

    row = queue.iloc[0]
    assert row["entity_resolution_status"] == "ambiguous"
    assert row["developer_identity_status"] == "shkp_role_evidence"
    assert row["shkp_site_match_status"] == "site_named_shkp"
    assert row["shkp_site_vendor"] == "Example Vendor Ltd"
    assert "Sun Hung Kai Properties" in row["shkp_site_holding_companies"]
    assert row["ownership_promotion_status"] == "blocked_address_only"
    assert row["permit_attribution_status"] == "blocked_address_only"
    assert summary.iloc[0]["site_evidence_phase_count"] == 1
    assert summary.iloc[0]["site_named_shkp_phase_count"] == 1


def test_phase_resolution_candidates_keep_shared_address_as_p0_cluster_without_unit_aggregation():
    crosswalk = pd.DataFrame(
        [
            {
                "srpe_development_id": "100",
                "marketing_name": "Shared Phase",
                "srpe_phase_name": "Phase 1",
                "srpe_address_en": "1 Shared Road",
                "bd_match_method": "address_exact",
                "bd_match_status": "ambiguous",
                "bd_phase_candidate_count": 2,
                "bd_permit_stage": "Plans Approved",
                "bd_permit_number": "BD-1",
                "bd_site_address": "1 Shared Road",
                "bd_applicant": "Example Applicant Ltd",
                "digest_month": "2025-01-01",
                "bd_domestic_units_count": 10,
                "bd_source_url": "https://bd.example/1",
            },
            {
                "srpe_development_id": "100",
                "marketing_name": "Shared Phase",
                "srpe_phase_name": "Phase 1",
                "srpe_address_en": "1 Shared Road",
                "bd_match_method": "address_exact",
                "bd_match_status": "ambiguous",
                "bd_phase_candidate_count": 2,
                "bd_permit_stage": "Plans Approved",
                "bd_permit_number": "BD-1",
                "bd_site_address": "1 Shared Road",
                "bd_applicant": "Example Applicant Ltd",
                "digest_month": "2025-02-01",
                "bd_domestic_units_count": 20,
                "bd_source_url": "https://bd.example/2",
            },
        ]
    )

    result = build_shkp_bd_phase_resolution_candidates(crosswalk)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["phase_resolution_status"] == "shared_address_phase_candidate"
    assert row["phase_resolution_priority"] == "P0"
    assert row["permit_identity_status"] == "permit_number_observed"
    assert row["bd_history_row_count"] == 2
    assert "bd_domestic_units_count" not in result.columns
    assert row["ownership_promotion_status"] == "blocked_address_only"
    assert row["permit_attribution_status"] == "blocked_address_only"


def test_phase_resolution_candidates_carry_site_role_context_without_promotion():
    crosswalk = pd.DataFrame(
        [{
            "srpe_development_id": "400",
            "marketing_name": "Role Example",
            "srpe_phase_name": "Phase 1",
            "srpe_address_en": "4 Role Road",
            "bd_match_method": "address_exact",
            "bd_match_status": "matched_needs_review",
            "bd_phase_candidate_count": 1,
            "bd_permit_stage": "Plans Approved",
            "bd_permit_number": "BD-400",
            "bd_site_address": "4 Role Road",
            "digest_month": "2025-01-01",
        }]
    )
    site_evidence = pd.DataFrame(
        [{
            "srpe_development_id": "400",
            "shkp_match_status": "site_named_shkp",
            "fetch_status": "ok",
            "vendor_name": "Role Vendor Ltd",
            "holding_companies": "Sun Hung Kai Properties Limited",
            "sales_agent": "Role Sales Agent Ltd",
            "resolved_url": "https://role.example",
        }]
    )

    result = build_shkp_bd_phase_resolution_candidates(crosswalk, site_evidence=site_evidence)

    row = result.iloc[0]
    assert row["developer_identity_status"] == "shkp_role_evidence"
    assert row["shkp_site_vendor"] == "Role Vendor Ltd"
    assert row["shkp_site_holding_companies"] == "Sun Hung Kai Properties Limited"
    assert row["shkp_site_sales_agent"] == "Role Sales Agent Ltd"
    assert row["ownership_promotion_status"] == "blocked_address_only"


def test_official_role_evidence_is_identity_context_and_keeps_blocked_gate():
    crosswalk = pd.DataFrame(
        [{
            "srpe_development_id": "500",
            "marketing_name": "Corporate Role Phase",
            "srpe_phase_name": "Phase 1",
            "srpe_address_en": "5 Role Road",
            "bd_match_method": "address_exact",
            "bd_match_status": "ambiguous",
            "bd_phase_candidate_count": 2,
            "bd_permit_stage": "Plans Approved",
            "bd_site_address": "5 Role Road",
            "digest_month": "2025-01-01",
        }]
    )
    role = pd.DataFrame(
        [{
            "srpe_development_id": "500",
            "vendor_or_owner": "Example Vendor Limited",
            "holding_companies": "Sun Hung Kai Properties Limited",
            "source_url": "https://www.shkp.com/example-role",
            "last_verified_at": "2026-08-09T00:00:00Z",
            "caveat": "Role only",
        }]
    )
    adapted = _official_role_evidence_as_site_evidence(role)
    queue, summary = build_shkp_bd_history_entity_resolution_review(crosswalk, adapted)

    row = queue.iloc[0]
    assert row["developer_identity_status"] == "shkp_corporate_role_evidence"
    assert row["shkp_site_match_status"] == "corporate_role_evidence"
    assert row["shkp_site_vendor"] == "Example Vendor Limited"
    assert summary.iloc[0]["corporate_role_evidence_phase_count"] == 1
    assert row["ownership_promotion_status"] == "blocked_address_only"
    assert row["permit_attribution_status"] == "blocked_address_only"


def test_phase_resolution_candidates_mark_unique_permit_cluster_p1():
    crosswalk = pd.DataFrame(
        [
            {
                "srpe_development_id": "200",
                "marketing_name": "Unique Phase",
                "srpe_phase_name": "Phase 1",
                "srpe_address_en": "2 Unique Road",
                "bd_match_method": "address_contains",
                "bd_match_status": "matched_needs_review",
                "bd_phase_candidate_count": 1,
                "bd_permit_stage": "Occupation Permits",
                "bd_permit_number": "OP-200",
                "bd_site_address": "2 Unique Road",
                "bd_applicant": "Unique Applicant Ltd",
                "digest_month": "2024-05-01",
                "bd_parser_confidence": "HIGH",
                "bd_parser_quality_flag": "ok",
            }
        ]
    )

    result = build_shkp_bd_phase_resolution_candidates(crosswalk)

    row = result.iloc[0]
    assert row["phase_resolution_status"] == "single_phase_address_candidate"
    assert row["phase_resolution_priority"] == "P1"
    assert row["permit_identity_status"] == "permit_number_observed"
    assert row["bd_applicants"] == "Unique Applicant Ltd"
    assert row["bd_applicant_quality_status"] == "observed_text_requires_review"
    assert row["bd_digest_month_first_observed"] == "2024-05-01"
    assert row["bd_digest_month_last_observed"] == "2024-05-01"


def test_phase_resolution_candidates_keep_unmatched_p2_and_missing_permit_explicit():
    crosswalk = pd.DataFrame(
        [
            {
                "srpe_development_id": "300",
                "marketing_name": "Unmatched Phase",
                "srpe_phase_name": "Phase 1",
                "srpe_address_en": "3 Missing Road",
                "bd_match_method": "none",
                "bd_match_status": "unmatched",
                "bd_phase_candidate_count": 0,
                "bd_permit_stage": None,
                "bd_permit_number": None,
                "bd_site_address": None,
                "bd_applicant": None,
                "digest_month": None,
            }
        ]
    )

    result = build_shkp_bd_phase_resolution_candidates(crosswalk)

    row = result.iloc[0]
    assert row["phase_resolution_status"] == "unmatched_no_bd_address"
    assert row["phase_resolution_priority"] == "P2"
    assert row["permit_identity_status"] == "permit_number_not_published_or_missing"
    assert row["bd_match_method"] == "none"
    assert row["bd_applicant_quality_status"] == "missing_or_not_published"


def test_phase_permit_candidate_evidence_links_schedule_context_without_assignment():
    crosswalk = pd.DataFrame(
        [
            {
                "srpe_development_id": "100",
                "srpe_phase_name": "Phase 1",
                "srpe_address_en": "8 Shared Road",
                "srpe_source_url": "https://srpe.example/index",
                "shkp_source_url": "https://shkp.example/phase-1",
                "bd_match_method": "address_exact",
                "bd_match_status": "ambiguous",
                "bd_permit_stage": "Occupation Permits (OP) Issued",
                "bd_permit_number": "NT1/2024/OP",
                "bd_site_address": "8 Shared Road",
                "bd_applicant": "Example Applicant Ltd",
                "digest_month": "2024-06-01",
                "bd_parser_confidence": "HIGH",
                "bd_parser_quality_flag": "ok",
                "bd_source_pdf_page": 12,
                "bd_source_url": "https://bd.example/2024",
            },
            {
                "srpe_development_id": "200",
                "srpe_phase_name": "Phase 2",
                "srpe_address_en": "8 Shared Road",
                "srpe_source_url": "https://srpe.example/index",
                "shkp_source_url": "https://shkp.example/phase-2",
                "bd_match_method": "address_exact",
                "bd_match_status": "ambiguous",
                "bd_permit_stage": "Occupation Permits (OP) Issued",
                "bd_permit_number": "NT2/2024/OP",
                "bd_site_address": "8 Shared Road",
                "bd_applicant": "Example Applicant Ltd",
                "digest_month": "2024-07-01",
                "bd_parser_confidence": "HIGH",
                "bd_parser_quality_flag": "ok",
                "bd_source_pdf_page": 14,
                "bd_source_url": "https://bd.example/2024",
            },
        ]
    )
    group_evidence = pd.DataFrame(
        [
            {
                "phase_group_id": "srpe-address:8sharedroad",
                "group_resolution_status": "shared_address_group",
                "group_evidence_status": "address_and_bd_cluster_observed",
                "srpe_address_en": "8 Shared Road",
                "srpe_phase_ids": "100; 200",
                "srpe_phase_order_context_json": '[{"srpe_development_id":"100","phase_name":"Phase 1","phase_no":"1"},{"srpe_development_id":"200","phase_name":"Phase 2","phase_no":"2"}]',
                "schedule_group_context_json": '[{"schedule_date":"2024-02-28","project_row_no":"1","lot_description":"Test Lot Phases 1 & 2","project_label":"Example Development","group_interest_raw":"JV","group_interest_pct":null,"srpe_phase_ids":["100","200"]}]',
                "source_urls": "https://shkp.example/schedule.pdf; https://srpe.example/index",
                "ownership_promotion_status": "approved_by_bad_input",
                "permit_attribution_status": "approved_by_bad_input",
            }
        ]
    )
    schedule = pd.DataFrame(
        [
            {
                "srpe_development_id": "100",
                "document_url": "https://shkp.example/schedule.pdf",
                "source_url": "https://shkp.example/schedule.pdf",
            },
            {
                "srpe_development_id": "200",
                "document_url": "https://shkp.example/schedule.pdf",
                "source_url": "https://shkp.example/schedule.pdf",
            },
        ]
    )
    roles = pd.DataFrame(
        [
            {
                "srpe_development_id": "100",
                "evidence_id": "role:100",
                "phase_label": "Phase 1",
                "vendor_or_owner": "Example Vendor Ltd",
                "holding_companies": "Sun Hung Kai Properties Limited",
                "source_url": "https://shkp.example/phase-1",
            }
        ]
    )

    result = build_shkp_bd_phase_permit_candidate_evidence(
        crosswalk,
        group_evidence,
        schedule_crosswalk=schedule,
        phase_role_evidence=roles,
    )

    assert len(result) == 2
    assert result["candidate_phase_ids"].eq("100; 200").all()
    assert result["candidate_context_status"].eq("official_schedule_group_context_not_phase_unique").all()
    assert result["schedule_match_status"].eq("official_schedule_grouped").all()
    assert result["phase_role_evidence_status"].eq("observed_context_only").all()
    assert result["phase_context_review_status"].notna().all()
    assert result["resolution_priority"].eq("P0").all()
    assert result["ownership_promotion_status"].eq("blocked_address_only").all()
    assert result["permit_attribution_status"].eq("blocked_address_only").all()
    assert result["research_only"].all()


def test_phase_permit_candidate_evidence_keeps_unmatched_and_forces_blocked_gate():
    crosswalk = pd.DataFrame(
        [
            {
                "srpe_development_id": "300",
                "srpe_address_en": "3 Missing Road",
                "bd_match_method": "none",
                "bd_match_status": "unmatched",
                "bd_phase_candidate_count": 0,
            }
        ]
    )
    group_evidence = pd.DataFrame(
        [
            {
                "phase_group_id": "srpe-address:3missingroad",
                "group_resolution_status": "unmatched_phase_group",
                "group_evidence_status": "no_bd_address_match",
                "srpe_address_en": "3 Missing Road",
                "srpe_phase_ids": "300",
                "srpe_phase_order_context_json": "[]",
                "schedule_group_context_json": "[]",
                "ownership_promotion_status": "approved_by_bad_input",
                "permit_attribution_status": "approved_by_bad_input",
            }
        ]
    )

    result = build_shkp_bd_phase_permit_candidate_evidence(crosswalk, group_evidence)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["resolution_status"] == "no_bd_candidate_observed"
    assert row["resolution_priority"] == "P2"
    assert row["candidate_context_status"] == "no_schedule_context"
    assert row["bd_permit_number"] is None or pd.isna(row["bd_permit_number"])
    assert row["ownership_promotion_status"] == "blocked_address_only"
    assert row["permit_attribution_status"] == "blocked_address_only"
    assert row["ownership_promotion_status"] == "blocked_address_only"


def test_phase_permit_reconciliation_distinguishes_concordant_narrowed_and_conflict():
    candidates = pd.DataFrame([
        {
            "phase_group_id": "group:single",
            "candidate_context_key": "group:single::schedule:0",
            "srpe_address_en": "1 Single Road",
            "candidate_phase_ids": "100",
            "candidate_phase_names": "Phase 1",
            "candidate_phase_nos": "1",
            "candidate_context_status": "official_schedule_phase_group_context",
            "bd_permit_stage": "Occupation Permits (OP) Issued",
            "bd_permit_number": "OP1/2025",
            "bd_permit_year": 2025,
            "bd_applicants": "Single Applicant Ltd",
            "schedule_project_label": "Single Development",
            "schedule_lot_description": "Lot Phase 1",
            "phase_context_concordance_status": "pdf_context_agrees_with_candidate_set",
            "bd_pdf_phase_tokens": "1",
            "bd_pdf_phase_candidate_ids": "100",
            "source_urls": "https://bd.example/single",
        },
        {
            "phase_group_id": "group:multi",
            "candidate_context_key": "group:multi::schedule:0",
            "srpe_address_en": "2 Multi Road",
            "candidate_phase_ids": "200; 300",
            "candidate_phase_names": "Phase 1A; Phase 1B",
            "candidate_phase_nos": "1A; 1B",
            "candidate_context_status": "official_schedule_group_context_not_phase_unique",
            "bd_permit_stage": "Occupation Permits (OP) Issued",
            "bd_permit_number": "OP2/2025",
            "bd_permit_year": 2025,
            "bd_applicants": "Multi Applicant Ltd",
            "schedule_project_label": "Multi Development",
            "schedule_lot_description": "Lot Phases 1A & 1B",
            "phase_context_concordance_status": "pdf_context_narrows_candidate_set",
            "bd_pdf_phase_tokens": "1A",
            "bd_pdf_phase_candidate_ids": "200",
            "bd_pdf_group_phase_candidate_ids": "200",
            "source_urls": "https://bd.example/multi",
        },
        {
            "phase_group_id": "group:conflict",
            "candidate_context_key": "group:conflict::schedule:0",
            "srpe_address_en": "3 Conflict Road",
            "candidate_phase_ids": "400; 500",
            "candidate_phase_names": "Phase 1A; Phase 1B",
            "candidate_phase_nos": "1A; 1B",
            "candidate_context_status": "official_schedule_group_context_not_phase_unique",
            "bd_permit_stage": "Occupation Permits (OP) Issued",
            "bd_permit_number": "OP3/2025",
            "bd_permit_year": 2025,
            "bd_applicants": "Conflict Applicant Ltd",
            "phase_context_concordance_status": "pdf_phase_tokens_do_not_match_candidate_set",
            "bd_pdf_phase_tokens": "2A",
            "source_urls": "https://bd.example/conflict",
        },
    ])

    result = build_shkp_bd_phase_permit_reconciliation(candidates)

    assert set(result["reconciliation_status"]) == {
        "single_phase_primary_document_concordant_needs_review",
        "phase_set_narrowed_by_primary_document_needs_review",
        "primary_document_phase_conflict_review",
    }
    single = result.loc[result["phase_group_id"].eq("group:single")].iloc[0]
    assert single["resolved_phase_candidate_ids"] == "100"
    assert single["phase_context_review_status"] == "phase_context_supported_not_assigned"
    assert single["phase_context_reviewed_candidate_ids"] == "100"
    assert single["permit_assignment_status"] == "blocked_address_only"
    narrowed = result.loc[result["phase_group_id"].eq("group:multi")].iloc[0]
    assert narrowed["resolved_phase_candidate_ids"] == "200"
    conflict = result.loc[result["phase_group_id"].eq("group:conflict")].iloc[0]
    assert pd.isna(conflict["resolved_phase_candidate_ids"])
    assert result["ownership_promotion_status"].eq("blocked_address_only").all()
    assert result["permit_attribution_status"].eq("blocked_address_only").all()
    assert result["research_only"].all()


def test_phase_permit_reconciliation_empty_input_is_explicit():
    result = build_shkp_bd_phase_permit_reconciliation(pd.DataFrame())
    assert result.empty
    assert list(result.columns)


def test_phase_permit_reconciliation_separates_schedule_phase_set_without_pdf_token():
    result = build_shkp_bd_phase_permit_reconciliation(pd.DataFrame([{
        "phase_group_id": "group:schedule-only",
        "candidate_context_key": "group:schedule-only::schedule:0",
        "srpe_address_en": "4 Schedule Road",
        "candidate_phase_ids": "600; 700",
        "candidate_phase_names": "Phase 1A; Phase 1B",
        "candidate_phase_nos": "1A; 1B",
        "candidate_context_status": "official_schedule_phase_group_context",
        "bd_permit_stage": "Occupation Permits (OP) Issued",
        "bd_permit_number": "OP4/2025",
        "phase_context_concordance_status": "pdf_page_has_no_phase_tokens",
        "source_urls": "https://shkp.example/schedule-only",
    }]))

    row = result.iloc[0]
    assert row["reconciliation_status"] == "official_schedule_phase_set_needs_primary_pdf"
    assert row["evidence_strength"] == "official_schedule_phase_context_without_pdf_token"
    assert row["permit_assignment_status"] == "blocked_address_only"
