from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_earnings_drivers import (
    METRIC_SPECS,
    build_airline_earnings_driver_comparability,
)


def test_driver_layer_has_unique_canonical_keys_and_explicit_missingness() -> None:
    result = build_airline_earnings_driver_comparability(retrieved_at="2026-08-07T00:00:00+00:00")

    assert len(result) == 560
    assert result.duplicated(["company", "statement_period", "canonical_metric"]).sum() == 0
    assert set(result["canonical_metric"]) == {spec.canonical_metric for spec in METRIC_SPECS}
    assert result["metric_definition"].notna().all()
    assert result["point_in_time_status"].notna().all()
    assert result.loc[result["value_native"].notna(), "source_url"].notna().all()


def test_common_cohorts_keep_scope_and_do_not_fake_cathay_1h2025_date() -> None:
    result = build_airline_earnings_driver_comparability()

    fy = result.loc[result["cohort"].eq("common_FY2025")]
    h1 = result.loc[result["cohort"].eq("common_1H2025")]
    assert fy["company"].nunique() == 7
    assert h1["company"].nunique() == 7
    assert result.loc[result["cohort"].eq("latest_available"), "company"].unique().tolist() == ["Cathay Pacific"]

    cathay_h1 = result.loc[
        result["company"].eq("Cathay Pacific") & result["statement_period"].eq("1H2025")
    ]
    assert cathay_h1["information_date_available"].eq(False).all()
    assert cathay_h1["point_in_time_status"].isin(
        {"period_evidence_without_announcement_date", "missing_disclosure"}
    ).all()


def test_driver_layer_preserves_usd_money_and_derived_proxy_labels() -> None:
    result = build_airline_earnings_driver_comparability()

    money = result.loc[result["value_type"].eq("monetary") & result["value_native"].notna()]
    assert money["value_usd"].notna().all()
    assert result.loc[result["canonical_metric"].eq("fuel_cost_per_ask"), "reported_or_derived"].dropna().eq("derived").all()
    assert result.loc[result["canonical_metric"].eq("cask"), "source_metric"].dropna().isin({"cask", "cask_derived"}).all()
    assert result.loc[result["canonical_metric"].eq("rask_proxy"), "metric_definition"].dropna().str.contains("scope").all()
    cash = result.loc[result["canonical_metric"].eq("cash_and_cash_equivalents")]
    assert cash["value_native"].notna().sum() == 11
    assert cash.loc[cash["value_native"].notna(), "reported_or_derived"].eq("issuer_reported").all()
    liabilities = result.loc[result["canonical_metric"].eq("total_liabilities")]
    assert liabilities["value_native"].notna().sum() == 11
    ratio = result.loc[result["canonical_metric"].eq("liabilities_to_assets_pct")]
    assert ratio["value_native"].notna().sum() == 11
    assert ratio.loc[ratio["value_native"].notna(), "reported_or_derived"].eq("derived").all()
    debt = result.loc[result["canonical_metric"].eq("interest_bearing_debt")]
    assert debt["value_native"].notna().sum() == 6
    capex = result.loc[result["canonical_metric"].eq("capex_cash_paid")]
    assert capex["value_native"].notna().sum() == 7
    net_borrowings = result.loc[result["canonical_metric"].eq("net_borrowings")]
    liquidity = result.loc[result["canonical_metric"].eq("available_unrestricted_liquidity")]
    assert net_borrowings["value_native"].notna().sum() == 2
    assert liquidity["value_native"].notna().sum() == 2
    fallback = result.loc[result["source_metric"].eq("rask_from_reported_yield_derived")]
    assert not fallback.empty
    assert fallback["reported_or_derived"].eq("derived").all()
