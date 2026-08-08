from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_data_completeness import build_airline_data_completeness


def test_airline_data_completeness_covers_all_required_company_domains() -> None:
    result = build_airline_data_completeness(retrieved_at="2026-08-07T00:00:00+00:00")
    company = result.loc[result["scope"].eq("company")]
    assert len(result) == 108
    assert company["company"].nunique() == 7
    assert company.groupby("company")["domain"].nunique().eq(15).all()
    assert result["limitation"].notna().all()
    assert result["point_in_time_status"].notna().all()


def test_airline_data_completeness_preserves_known_gaps_and_evidence_boundaries() -> None:
    result = build_airline_data_completeness()
    borrow = result.loc[result["domain"].eq("borrow_feasibility")]
    assert borrow["coverage_status"].eq("missing_free_source").all()
    eligibility = result.loc[result["domain"].eq("short_eligibility")]
    assert len(eligibility) == 7
    assert eligibility["coverage_status"].eq("available").all()
    assert eligibility["point_in_time_status"].eq("exchange_eligibility_evidence_not_borrow").all()
    cathay_risk = result.loc[
        result["company"].eq("Cathay Pacific") & result["domain"].eq("market_risk")
    ].iloc[0]
    assert "airline_hk_short_positions.csv" in cathay_risk["source_dataset"]
    assert "sfc_reportable_short_position_as_of_date" in cathay_risk["point_in_time_status"]

    hedging = result.loc[result["domain"].eq("fuel_hedging_disclosure")]
    assert len(hedging) == 7
    assert hedging["coverage_status"].isin(
        ["explicit_primary_disclosure", "primary_report_scan_completed_no_numeric_anchor"]
    ).all()

    cathay_kpi = result.loc[
        result["company"].eq("Cathay Pacific")
        & result["domain"].eq("monthly_supply_demand")
    ].iloc[0]
    assert cathay_kpi["coverage_status"] == "available_through_2026-06"
    assert cathay_kpi["point_in_time_status"] == "monthly_issuer_release_snapshot"

    mainland_filings = result.loc[
        result["scope"].eq("company")
        & result["domain"].eq("formal_1H2026_filing")
        & result["company"].ne("Cathay Pacific")
    ]
    assert mainland_filings["coverage_status"].eq("scheduled_no_official_match").all()
    assert mainland_filings["point_in_time_status"].eq("query_scoped_cninfo_no_match").all()

    hainan_revenue = result.loc[
        result["company"].eq("Hainan Airlines Holdings")
        & result["domain"].eq("revenue_consensus")
    ].iloc[0]
    assert hainan_revenue["coverage_status"] == "consolidated_group"
    assert "complete low/high" in hainan_revenue["limitation"]

    public_reports = result.loc[result["domain"].eq("public_report_evidence")]
    assert len(public_reports) == 7
    assert public_reports.loc[public_reports["company"].ne("Cathay Pacific"), "coverage_status"].eq("available").all()
    assert public_reports.loc[public_reports["company"].eq("Cathay Pacific"), "coverage_status"].eq("not_applicable").all()
    assert public_reports.loc[public_reports["company"].ne("Cathay Pacific"), "point_in_time_status"].eq(
        "dated_eps_profit_plus_page_snapshot_revenue"
    ).all()
