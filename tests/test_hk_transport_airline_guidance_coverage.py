from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_guidance_coverage import build_airline_guidance_coverage


def test_guidance_coverage_keeps_company_outlook_status_explicit() -> None:
    result = build_airline_guidance_coverage(retrieved_at="2026-08-07T00:00:00+00:00")
    assert len(result) == 7
    assert result["company"].nunique() == 7
    assert result["guidance_coverage_status"].isin({
        "direct_issuer_guidance",
        "issuer_earnings_warning_only",
        "formal_result_without_structured_guidance",
        "no_company_guidance_before_formal_1H2026",
    }).all()
    cathay = result.loc[result["company"].eq("Cathay Pacific")].iloc[0]
    assert cathay["guidance_coverage_status"] == "direct_issuer_guidance"
    assert cathay["guidance_event_count"] > 0
    assert cathay["latest_guidance_metric"] == "group_passenger_capacity_growth_target"


def test_guidance_coverage_does_not_turn_missing_guidance_into_zero() -> None:
    result = build_airline_guidance_coverage()
    spring = result.loc[result["company"].eq("Spring Airlines")].iloc[0]
    hainan = result.loc[result["company"].eq("Hainan Airlines Holdings")].iloc[0]
    assert spring["guidance_coverage_status"] == "direct_issuer_guidance"
    assert spring["latest_guidance_metric"] == "planned_fleet_additions"
    assert hainan["guidance_coverage_status"] == "direct_issuer_guidance"
    assert hainan["latest_guidance_metric"] == "fleet_net_growth_target"
    assert hainan["latest_guidance_value_min"] == 3.0
    assert hainan["latest_guidance_value_max"] == 5.0


def test_guidance_coverage_retains_warning_dates_and_source_lineage() -> None:
    result = build_airline_guidance_coverage()
    warnings = result.loc[result["warning_event_count"].gt(0)]
    assert len(warnings) == 4
    assert warnings["latest_warning_date"].notna().all()
    assert warnings["latest_warning_source_url"].notna().all()
    assert result["retrieved_at"].nunique() == 1


def test_guidance_coverage_uses_cninfo_watch_without_overwriting_schedule() -> None:
    result = build_airline_guidance_coverage()
    air_china = result.loc[result["company"].eq("Air China")].iloc[0]
    assert air_china["formal_report_status"] == "scheduled"
    assert air_china["formal_report_scheduled_date"] == "2026-08-31"
    assert pd.isna(air_china["formal_report_actual_disclosure_date"])
    assert "direct CNINFO official-filing watch" in air_china["source_note"]
