from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_pair_readiness import build_airline_pair_readiness


def test_pair_readiness_is_non_directional_and_keeps_catalyst_gate() -> None:
    result = build_airline_pair_readiness(retrieved_at="2026-08-07T00:00:00+00:00")

    assert len(result) == 7
    assert result["source_quality"].eq("derived_readiness_gate").all()
    assert result[["has_official_latest_financial_actual", "has_h1_demand_trend", "has_fuel_cost_driver", "has_market_expectation"]].all().all()
    assert result.loc[result["company"].eq("Cathay Pacific"), "pair_readiness_status"].item() == "thesis_ready_with_revision_or_valuation_caveat"
    assert result.loc[result["company"].eq("Air China"), "pair_readiness_status"].item() == "monitor_until_formal_1H2026"
    assert result.loc[result["company"].eq("Air China"), "profit_base_stable"].item() is False
    assert result["has_market_risk_metrics"].all()
    assert result["borrow_data_available"].eq(False).all()
    assert result["risk_caveat"].eq("borrow_data_unavailable").all()
    assert result.loc[result["company"].eq("Air China"), "unified_consensus_event_count"].item() > 0
    assert result.loc[result["company"].eq("Air China"), "unified_estimate_revision_count"].item() > 0
    assert result.loc[result["company"].eq("Hainan Airlines Holdings"), "unified_rating_event_count"].item() > 0


def test_pair_readiness_does_not_turn_readiness_into_a_trade_signal() -> None:
    result = build_airline_pair_readiness()

    assert "long" not in " ".join(result["pair_readiness_status"].astype(str)).lower()
    assert "short" not in " ".join(result["pair_readiness_status"].astype(str)).lower()
    assert result["blocking_reason"].fillna("").str.contains("unstable_profit_base|estimate_revision_history", regex=True).any()
