from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_pair_target_range import build_airline_pair_target_range


def test_target_range_uses_min_max_of_two_independent_methods() -> None:
    trade = pd.DataFrame([{"pair_id": "A__B", "selection_bucket": "core", "scenario": "base", "asset_a": "A", "asset_b": "B", "long_asset": "A", "short_asset": "B", "long_leg": "A Co", "short_leg": "B Co", "model_revenue_gap_a_pct": 5.0, "model_revenue_gap_b_pct": -2.0, "beta_hedge_ratio_long_to_short": 1.0, "beta_hedged_pair_payoff_pct": 7.0, "catalyst_a": "a", "catalyst_b": "b"}])
    pb = pd.DataFrame([{"pair_id": "A__B", "scenario": "base", "pb_target_return_a_pct": -10.0, "pb_target_return_b_pct": 10.0, "beta_hedged_pair_payoff_pct": -20.0}])
    direction = pd.DataFrame([{"pair_id": "A__B", "earnings_model_direction": "long A Co / short B Co", "selected_direction_status": "provisional_candidate_not_trade_ready", "selected_direction": "long A Co / short B Co", "direction_concordance": "earnings_and_pb_direction_conflict", "risk_status_at_0_5pct_budget": "borrow_unavailable"}])
    frame = build_airline_pair_target_range(trade=trade, pb_trade=pb, direction=direction, retrieved_at="2026-08-08T00:00:00+00:00")
    row = frame.iloc[0]
    assert row.long_leg_return_low_pct == -10.0
    assert row.long_leg_return_high_pct == 5.0
    assert row.equal_notional_pair_payoff_low_pct == -20.0
    assert row.equal_notional_pair_payoff_high_pct == 7.0
    assert "not_confidence_interval" in row.target_range_method


def test_priority_set_has_three_scenarios_per_pair() -> None:
    frame = build_airline_pair_target_range()
    assert len(frame) == 15
    assert frame.pair_id.nunique() == 5
    assert set(frame.scenario) == {"bear", "base", "bull"}
    assert frame.target_range_method.notna().all()
