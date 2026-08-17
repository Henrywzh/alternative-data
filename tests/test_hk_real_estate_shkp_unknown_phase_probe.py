import pandas as pd

from src.hk_real_estate.shkp_unknown_phase_probe import (
    build_unknown_phase_identity_review,
    fetch_unknown_phase_site_evidence,
)


def test_review_keeps_no_keyword_as_non_negative_and_routes_role_hit():
    evidence = pd.DataFrame(
        [
            {
                "srpe_development_id": "1",
                "development_name_en": "ONE",
                "official_website": "one.example",
                "fetch_status": "ok",
                "robots_status": "checked",
                "http_status": 200,
                "shkp_match_status": "site_no_shkp_keyword",
                "vendor_name": "Other Vendor",
                "sales_agent": None,
                "holding_companies": None,
                "source_url": "https://one.example",
                "fetched_at": "2026-08-09T00:00:00+00:00",
            },
            {
                "srpe_development_id": "2",
                "development_name_en": "TWO",
                "official_website": "two.example",
                "fetch_status": "ok",
                "robots_status": "checked",
                "http_status": 200,
                "shkp_match_status": "site_named_shkp",
                "vendor_name": "Vendor",
                "sales_agent": None,
                "holding_companies": "Sun Hung Kai Properties Limited",
                "source_url": "https://two.example",
                "fetched_at": "2026-08-09T00:00:00+00:00",
            },
        ]
    )
    review = build_unknown_phase_identity_review(evidence).set_index("srpe_development_id")
    assert review.loc["1", "quick_check_result"] == "checked_no_shkp_keyword"
    assert "do not reject" in review.loc["1", "recommended_next_step"]
    assert review.loc["2", "quick_check_result"] == "quick_verified_role_shkp"
    assert "stake/JV" in review.loc["2", "recommended_next_step"]


def test_fetch_empty_or_non_unknown_queue_is_schema_stable():
    empty = fetch_unknown_phase_site_evidence(pd.DataFrame())
    assert empty.empty
    assert "fetch_status" in empty.columns
    non_unknown = pd.DataFrame(
        [{"srpe_development_id": "1", "candidate_status": "possible_shkp_high_recall", "official_website": "one.example"}]
    )
    result = fetch_unknown_phase_site_evidence(non_unknown)
    assert result.empty
    assert list(result.columns) == list(empty.columns)

