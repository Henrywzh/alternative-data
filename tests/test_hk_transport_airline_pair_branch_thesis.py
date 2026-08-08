from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_pair_branch_thesis import build_airline_pair_branch_thesis


def test_branch_matrix_has_fundamental_and_valuation_branches() -> None:
    working = pd.DataFrame([{"pair_id": "A__B", "selection_bucket": "core", "asset_a": "A", "asset_b": "B", "company_a": "A Co", "company_b": "B Co"}])
    trade = pd.DataFrame([{"pair_id": "A__B", "scenario": "base", "long_asset": "B", "short_asset": "A", "long_leg": "B Co", "short_leg": "A Co", "model_revenue_gap_a_pct": -10.0, "model_revenue_gap_b_pct": -2.0}])
    pb = pd.DataFrame([{"pair_id": "A__B", "scenario": "base", "pb_target_return_a_pct": 20.0, "pb_target_return_b_pct": 5.0}])
    risk = pd.DataFrame([{"asset_a": "A", "asset_b": "B", "beta_a_to_b": 0.5, "beta_b_to_a": 2.0, "hedged_spread_max_drawdown_a_minus_beta_b_pct": -10.0, "hedged_spread_max_drawdown_b_minus_beta_a_pct": -20.0, "hedged_spread_vol_a_minus_beta_b_pct": 10.0, "hedged_spread_vol_b_minus_beta_a_pct": 20.0}])
    triggers = pd.DataFrame([{"pair_id": "A__B", "current_direction_status": "no_direction_due_valuation_conflict", "current_revision_status": "not_confirmed_no_signal", "event_window": "2026-08-31", "entry_trigger": "entry", "invalidation_rule": "invalidate"}])
    frame = build_airline_pair_branch_thesis(working=working, trade=trade, pb_trade=pb, risk=risk, triggers=triggers)
    assert set(frame.branch) == {"fundamental_resilience", "valuation_mean_reversion"}
    value_branch = frame[frame.branch.eq("valuation_mean_reversion")].iloc[0]
    assert value_branch.long_asset == "A"
    assert value_branch.short_asset == "B"
    assert value_branch.direction_aware_drawdown_pct == -10.0


def test_priority_matrix_has_two_branches_per_pair() -> None:
    frame = build_airline_pair_branch_thesis()
    assert len(frame) == 10
    assert frame.pair_id.nunique() == 5
    assert set(frame.branch) == {"fundamental_resilience", "valuation_mean_reversion"}
    assert frame.branch_status.eq("conditional_pre_event_no_entry").all()
