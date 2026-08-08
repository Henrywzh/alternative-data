from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_revenue_consensus_coverage import build_airline_revenue_consensus_coverage


def test_revenue_consensus_coverage_is_one_row_per_traded_share_class() -> None:
    result = build_airline_revenue_consensus_coverage(retrieved_at="2026-08-07T00:00:00+00:00")
    assert len(result) == 10
    assert result.duplicated(["ticker", "fiscal_year"]).sum() == 0
    assert result["coverage_scope"].isin({
        "direct_ticker_vendor_estimate", "same_company_cross_market_fallback", "missing"
    }).all()
    assert result["native_unit"].isin({"HKD million", "RMB million"}).all()


def test_revenue_consensus_coverage_makes_hainan_unit_conversion_explicit() -> None:
    result = build_airline_revenue_consensus_coverage()
    hainan = result.loc[result["company"].eq("Hainan Airlines Holdings")].iloc[0]
    assert hainan["coverage_scope"] == "same_company_cross_market_fallback"
    assert hainan["normalization_factor_to_native_mn"] == 100.0
    assert hainan["native_unit"] == "RMB million"
    assert hainan["revenue_avg_native_mn"] == 79771.0


def test_revenue_consensus_coverage_keeps_direct_and_fallback_quality_separate() -> None:
    result = build_airline_revenue_consensus_coverage()
    direct = result.loc[result["coverage_scope"].eq("direct_ticker_vendor_estimate")]
    fallback = result.loc[result["coverage_scope"].eq("same_company_cross_market_fallback")]
    assert direct["source_quality"].eq("yfinance_discovery").all()
    assert fallback["source_quality"].eq("akshare_discovery").all()
    assert direct["revision_history_available"].eq(False).all()
