from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_revision_coverage import build_airline_revision_coverage


def test_revision_coverage_summary_exposes_evidence_bands_and_direction_counts() -> None:
    result = build_airline_revision_coverage(retrieved_at="2026-08-07T00:00:00+00:00")

    assert len(result) == 7
    assert result["company"].nunique() == 7
    assert result["source_quality"].eq("derived_coverage_summary").all()
    assert result.loc[result["company"].eq("Air China"), "ashare_eps_revision_proxy_count"].item() > 0
    assert result.loc[result["company"].eq("Air China"), "mainland_revenue_revision_proxy_count"].item() > 0
    assert result.loc[result["company"].eq("Air China"), "cninfo_rating_event_count"].item() > 0
    assert result.loc[result["company"].eq("Cathay Pacific"), "revision_evidence_band"].item() == "current_snapshot_only"
    assert result.loc[result["company"].eq("Hainan Airlines Holdings"), "revision_evidence_band"].item() == "dated_public_report_markers"
    assert result["provider_revision_history_available"].eq(False).all()
    air_china = result.loc[result["company"].eq("Air China")].iloc[0]
    assert air_china["yahoo_coverage_status"] == "available_with_revision_signal"
    assert air_china["yahoo_eps_revision_signal_count"] > 0
    assert air_china["yahoo_source_quality"] == "yfinance_discovery"
    assert air_china["public_report_evidence_row_count"] > 0
    assert air_china["public_report_dated_row_count"] > 0


def test_revision_coverage_exposes_yahoo_missingness_without_fabrication() -> None:
    result = build_airline_revision_coverage()
    hainan = result.loc[result["company"].eq("Hainan Airlines Holdings")].iloc[0]
    assert hainan["yahoo_coverage_status"] == "available_no_eps_revision"
    assert hainan["yahoo_eps_revision_signal_count"] == 0


def test_revision_coverage_keeps_positive_and_negative_proxy_counts_separate() -> None:
    result = build_airline_revision_coverage()
    mainland = result.loc[result["ashare_eps_revision_proxy_count"].gt(0)]
    assert (mainland["ashare_eps_positive_revision_count"] + mainland["ashare_eps_negative_revision_count"] <= mainland["ashare_eps_revision_proxy_count"]).all()
    assert result["em_buy_add_pct_2026"].dropna().between(0, 100).all()
