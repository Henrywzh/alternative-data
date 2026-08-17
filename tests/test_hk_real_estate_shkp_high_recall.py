import pandas as pd

from src.hk_real_estate.shkp_high_recall import (
    build_shkp_high_recall_phase_candidates,
    enrich_indicative_ownership_with_high_recall,
)
from src.hk_real_estate.sources import shkp
from src.hk_real_estate.sources.shkp import build_shkp_annual_srpe_crosswalk


def _index():
    return pd.DataFrame(
        [
            {
                "development_id": "1",
                "display_name": "NOVO LAND",
                "development_name_en": "NOVO LAND",
                "phase_name_en": "PHASE 2A",
                "address_en": "1 NOVO ROAD",
                "planning_area_en": "TUEN MUN",
                "active": "Y",
                "official_website": "novo.example",
            },
            {
                "development_id": "2",
                "display_name": "UNRELATED ESTATE",
                "development_name_en": "UNRELATED ESTATE",
                "phase_name_en": "PHASE 1",
                "address_en": "2 OTHER ROAD",
                "planning_area_en": "SHA TIN",
                "active": "N",
                "official_website": "other.example",
            },
            {
                "development_id": "3",
                "display_name": "CULLINAN SKY",
                "development_name_en": "CULLINAN SKY",
                "phase_name_en": "PHASE 1",
                "address_en": "3 SKY ROAD",
                "planning_area_en": "KOWLOON",
                "active": "N",
                "official_website": "sky.example",
            },
        ]
    )


def test_high_recall_keeps_explicit_current_match_and_does_not_call_unknown_negative():
    result = build_shkp_high_recall_phase_candidates(
        _index(),
        current_crosswalk=pd.DataFrame(
            [
                {
                    "srpe_development_id": "1",
                    "marketing_name": "NOVO LAND Phase 2A",
                    "match_status": "matched",
                    "shkp_source_url": "https://www.shkp.com/project/novo",
                }
            ]
        ),
    )
    rows = result.set_index("srpe_development_id")
    assert rows.loc["1", "candidate_status"] == "likely_shkp"
    assert rows.loc["1", "match_confidence"] == "high"
    assert rows.loc["2", "candidate_status"] == "identity_unknown_owner_evidence_missing"
    assert rows.loc["2", "strict_ownership_promotion_status"] == "blocked_high_recall_identity_only"


def test_high_recall_name_match_is_review_only_and_routes_register_when_present():
    result = build_shkp_high_recall_phase_candidates(
        _index(),
        historical_annual_crosswalk=pd.DataFrame(
            [
                {
                    "project_label": "Cullinan Sky",
                    "match_status": "unmatched",
                    "document_url": "https://www.shkp.com/report.pdf",
                }
            ]
        ),
        manifest=pd.DataFrame(
            [
                {"srpe_development_id": "3", "document_category": "register_of_transactions"}
            ]
        ),
    )
    row = result.loc[result["srpe_development_id"].eq("3")].iloc[0]
    assert row["candidate_status"] == "possible_shkp_high_recall"
    assert row["transaction_route_status"] == "transaction_register_available"
    assert row["strict_ownership_promotion_status"] == "blocked_high_recall_identity_only"


def test_enrichment_does_not_overwrite_numeric_snapshot():
    ownership = pd.DataFrame(
        [
            {
                "registry_key": "srpe:1",
                "srpe_development_id": "1",
                "indicative_owner_status": "likely_shkp_numeric_snapshot",
                "indicative_confidence": "medium",
                "indicative_evidence_basis": "annual_report_group_interest_snapshot",
                "indicative_sales_use_status": "indicative_numeric_only",
            },
            {
                "registry_key": "srpe:2",
                "srpe_development_id": "2",
                "indicative_owner_status": "not_observed",
                "indicative_confidence": "none",
                "indicative_evidence_basis": "srpe_parent_only",
                "indicative_sales_use_status": "not_covered",
            },
        ]
    )
    candidates = pd.DataFrame(
        [
            {
                "srpe_development_id": "1",
                "candidate_status": "possible_shkp_high_recall",
                "identity_evidence_status": "official_evidence_or_name_match_review",
                "match_confidence": "low",
                "match_score": 0.8,
                "match_method": "official_label_distinctive_token",
                "evidence_source_types": "annual_report",
                "evidence_urls_json": "[]",
                "explicit_evidence_rows": 0,
                "recommended_next_step": "quick check",
            },
            {
                "srpe_development_id": "2",
                "candidate_status": "possible_shkp_high_recall",
                "identity_evidence_status": "official_evidence_or_name_match_review",
                "match_confidence": "low",
                "match_score": 0.8,
                "match_method": "official_label_distinctive_token",
                "evidence_source_types": "annual_report",
                "evidence_urls_json": "[]",
                "explicit_evidence_rows": 0,
                "recommended_next_step": "quick check",
            },
        ]
    )
    result = enrich_indicative_ownership_with_high_recall(ownership, candidates)
    assert result.loc[result["srpe_development_id"].eq("1"), "indicative_owner_status"].iloc[0] == "likely_shkp_numeric_snapshot"
    assert result.loc[result["srpe_development_id"].eq("2"), "indicative_owner_status"].iloc[0] == "possible_shkp_high_recall"
    assert result["strict_ownership_promotion_status"].eq("blocked_high_recall_identity_only").all()



def test_curated_non_shkp_exclusion_suppresses_lohas_and_one_innovale():
    """Curated non-SHKP phases must not re-enter the queue via explicit or fuzzy evidence."""
    index = pd.DataFrame(
        [
            {
                "development_id": "10486",
                "display_name": "LOHAS PARK",
                "development_name_en": "LOHAS PARK",
                "phase_name_en": "GRAND SEASONS",
                "address_en": "1 LOHAS PARK ROAD",
                "planning_area_en": "TSEUNG KWAN O",
                "active": "Y",
                "official_website": "grandseasons.example",
            },
            {
                "development_id": "8667",
                "display_name": "ONE INNOVALE",
                "development_name_en": "ONE INNOVALE",
                "phase_name_en": "PHASE 1 OF ONE INNOVALE",
                "address_en": "8 MA SIK ROAD",
                "planning_area_en": "FANLING NORTH",
                "active": "Y",
                "official_website": "oneinnovale.example",
            },
        ]
    )
    # A crosswalk row that used to fan the "Wings at Sea" label out to every
    # Lohas phase; the exclusion must drop it even if the label is present.
    annual_crosswalk = pd.DataFrame(
        [
            {
                "srpe_development_id": "10486",
                "project_label": "Wings at Sea & Wings at Sea II",
                "match_status": "ambiguous",
            }
        ]
    )
    candidates = build_shkp_high_recall_phase_candidates(
        index,
        annual_crosswalk=annual_crosswalk,
        historical_annual_crosswalk=annual_crosswalk,
    )
    for _, row in candidates.iterrows():
        assert row["candidate_status"] == "identity_unknown_owner_evidence_missing", row["srpe_development_id"]
        assert row["identity_evidence_status"] == "curated_non_shkp_exclusion", row["srpe_development_id"]
        assert row["explicit_evidence_rows"] == 0
        assert row["fuzzy_evidence_rows"] == 0


def test_address_substring_guard_rejects_house_number_prefix_swallow():
    """'8 Ma Sik Road' must not match '38 Ma Sik Road' via substring collapse."""
    annual = pd.DataFrame(
        [
            {
                "report_id": "r1",
                "project_label": "Noble Hill",
                "project_state": "handover_completed",
                "geography": "Hong Kong",
                "location": "38 Ma Sik Road, Sheung Shui",
                "group_interest_raw": "100",
                "group_interest_pct": 100.0,
                "page_number": 11,
                "document_url": "https://example.com/ar",
                "evidence_type": "handover_table",
            }
        ]
    )
    index = pd.DataFrame(
        [
            {
                "development_id": "8667",
                "display_name": "ONE INNOVALE",
                "development_name_en": "ONE INNOVALE",
                "phase_name_en": "PHASE 1 OF ONE INNOVALE",
                "address_en": "8 Ma Sik Road",
                "planning_area_en": "FANLING NORTH",
                "active": "Y",
                "official_website": "oneinnovale.example",
            }
        ]
    )
    crosswalk = build_shkp_annual_srpe_crosswalk(annual, index)
    # The annual disclosure is retained as an explicit unmatched audit row,
    # but no SRPE candidate may be created: the address substring is unsafe
    # and the names do not match.
    assert len(crosswalk) == 1
    assert crosswalk["match_status"].iloc[0] == "unmatched"
    assert crosswalk["srpe_development_id"].isna().all()


def test_safe_address_substring_helper():
    assert shkp._safe_address_substring("8masikroad", "38masikroad") is False
    assert shkp._safe_address_substring("38masikroad", "38masikroad") is True
    assert shkp._safe_address_substring("lohasparkroad", "1lohasparkroad") is True
    assert shkp._safe_address_substring("1lohasparkroad", "1lohasparkroad") is True
