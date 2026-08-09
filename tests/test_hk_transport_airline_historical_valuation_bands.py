from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_historical_valuation_bands import (
    build_airline_free_constructed_ps_history,
    build_airline_historical_valuation_bands,
    build_airline_valuation_reconciliation_audit,
)


def test_constructed_ps_uses_market_cap_and_latest_annual_revenue() -> None:
    free_history = pd.DataFrame(
        [
            {"asset": "601021.SH", "company": "Spring Airlines", "market": "CN_A", "observation_date": "2025-01-02", "metric": "market_cap", "value": 100.0},
            {"asset": "601021.SH", "company": "Spring Airlines", "market": "CN_A", "observation_date": "2026-01-02", "metric": "market_cap", "value": 120.0},
        ]
    )
    financial = pd.DataFrame(
        [
            {"company": "Spring Airlines", "period_type": "FY", "period_end": "2024-12-31", "metric": "total_revenue", "value_native": 10000.0, "native_currency": "RMB"},
        ]
    )
    constructed = build_airline_free_constructed_ps_history(
        free_history=free_history,
        financial_history=financial,
        fx_rates=pd.DataFrame(),
        retrieved_at="2026-08-08T00:00:00+00:00",
    )
    assert len(constructed) == 2
    assert constructed.value.tolist() == [1.0, 1.2]
    assert set(constructed.point_in_time_status) == {"period_end_only_no_announcement_date"}


def test_cathay_constructed_ps_keeps_hkd_market_cap_against_hkd_revenue() -> None:
    free_history = pd.DataFrame(
        [
            {"asset": "0293.HK", "company": "Cathay Pacific", "market": "HK", "observation_date": "2026-08-08", "metric": "market_cap", "value": 100.0},
        ]
    )
    comparability = pd.DataFrame(
        [
            {
                "company": "Cathay Pacific", "canonical_metric": "total_revenue", "statement_period": "FY2025",
                "period_end": "2025-12-31", "value_native": 10000.0, "native_currency": "HKD",
                "information_date": "2026-03-11",
            }
        ]
    )
    constructed = build_airline_free_constructed_ps_history(
        free_history=free_history,
        financial_history=pd.DataFrame(),
        comparability_drivers=comparability,
        fx_rates=pd.DataFrame(),
        retrieved_at="2026-08-08T00:00:00+00:00",
    )
    cathay = constructed.loc[constructed.asset.eq("0293.HK")].iloc[0]
    assert cathay.value == pytest.approx(1.0)
    assert cathay.revenue_currency == "HKD"
    assert cathay.fx_pair == ""
    assert cathay.point_in_time_status == "announcement_aligned_for_available_report_date"


def test_mainland_h_share_constructed_ps_still_converts_hkd_market_cap_to_rmb() -> None:
    free_history = pd.DataFrame(
        [
            {"asset": "01055.HK", "company": "China Southern Airlines", "market": "HK", "observation_date": "2026-08-08", "metric": "market_cap", "value": 100.0},
        ]
    )
    financial = pd.DataFrame(
        [
            {"company": "China Southern Airlines", "period_type": "FY", "period_end": "2025-12-31", "metric": "total_revenue", "value_native": 10000.0, "native_currency": "RMB"},
        ]
    )
    fx = pd.DataFrame(
        [
            {"pair": "USD_CNY", "observation_date": "2026-08-08", "value": 7.0},
            {"pair": "USD_HKD", "observation_date": "2026-08-08", "value": 8.0},
        ]
    )
    constructed = build_airline_free_constructed_ps_history(
        free_history=free_history,
        financial_history=financial,
        fx_rates=fx,
        retrieved_at="2026-08-08T00:00:00+00:00",
    )
    southern = constructed.loc[constructed.asset.eq("01055.HK")].iloc[0]
    assert southern.value == pytest.approx(0.875)
    assert southern.revenue_currency == "RMB"
    assert southern.fx_pair == "HKD_RMB_derived_from_USD_CNY_USD_HKD"


def test_bands_keep_non_positive_pe_out_of_percentiles() -> None:
    history = pd.DataFrame(
        [
            {"asset": "601021.SH", "company": "Spring Airlines", "market": "CN_A", "observation_date": "2025-01-02", "metric": "pe_ttm", "value": -5.0},
            {"asset": "601021.SH", "company": "Spring Airlines", "market": "CN_A", "observation_date": "2026-01-02", "metric": "pe_ttm", "value": 10.0},
            {"asset": "601021.SH", "company": "Spring Airlines", "market": "CN_A", "observation_date": "2025-01-02", "metric": "pb", "value": 2.0},
        ]
    )
    current = pd.DataFrame(
        [{"asset": "601021.SH", "metric": "pe_ttm", "value": 10.0, "basis": "市盈率-TTM"}]
    )
    constructed = pd.DataFrame(
        [{"asset": "601021.SH", "company": "Spring Airlines", "market": "CN_A", "observation_date": "2026-01-02", "metric": "ps_annual_period_end", "value": 1.5, "point_in_time_status": "period_end_only_no_announcement_date", "source_quality": "test", "source_paths": "test"}]
    )
    bands = build_airline_historical_valuation_bands(
        free_history=history,
        free_current=current,
        constructed_ps=constructed,
        retrieved_at="2026-08-08T00:00:00+00:00",
    )
    pe = bands.loc[(bands.asset.eq("601021.SH")) & (bands.metric.eq("pe_ttm")) & (bands.window.eq("all"))].iloc[0]
    assert pe.observation_count == 2
    assert pe.positive_observation_count == 1
    assert pe.non_positive_observation_count == 1
    assert pe.median_value == 10.0
    assert pe.current_percentile_positive == 100.0


def test_reconciliation_labels_ps_basis_mismatch_instead_of_calling_it_validated() -> None:
    current = pd.DataFrame(
        [{"asset": "601021.SH", "metric": "ps_ttm", "value": 2.0, "basis": "市销率-TTM", "observation_date": "2026-08-08"}]
    )
    constructed = pd.DataFrame(
        [{"asset": "601021.SH", "metric": "ps_annual_period_end", "value": 3.0, "basis": "annual", "observation_date": "2026-08-08", "point_in_time_status": "period_end_only_no_announcement_date"}]
    )
    audit = build_airline_valuation_reconciliation_audit(
        free_history=pd.DataFrame(),
        free_current=current,
        constructed_ps=constructed,
        retrieved_at="2026-08-08T00:00:00+00:00",
    )
    row = audit.loc[audit.asset.eq("601021.SH") & audit.metric.eq("ps_ttm")].iloc[0]
    assert row.comparison_status == "basis_mismatch_current_ttm_vs_latest_annual_revenue"
    assert row.relative_difference_pct == pytest.approx(-33.33333333333333)
