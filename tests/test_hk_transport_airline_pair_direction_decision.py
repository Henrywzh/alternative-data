from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_pair_direction_decision import (
    build_airline_pair_direction_decision,
)


def test_direction_gate_distinguishes_alignment_from_conflict() -> None:
    working = pd.DataFrame([{"pair_id": "A__B", "selection_bucket": "core", "asset_a": "A", "asset_b": "B", "variant_perception_gap_difference_pct": 10.0}])
    trade = pd.DataFrame([{"pair_id": "A__B", "scenario": "base", "long_asset": "A", "short_asset": "B", "long_leg": "A Co", "short_leg": "B Co", "beta_hedged_pair_payoff_pct": 3.0, "catalyst_a": "a", "catalyst_b": "b"}])
    pb_trade = pd.DataFrame([{"pair_id": "A__B", "scenario": "base", "pb_target_return_a_pct": 10.0, "pb_target_return_b_pct": 0.0, "equal_notional_gross_pair_payoff_pct": 10.0, "beta_hedged_pair_payoff_pct": 10.0}])
    factors = pd.DataFrame([{"pair_id": "A__B", "trade_readiness_status": "not_trade_ready_valuation_factor_or_scope_gap", "factor_risk_status": "material_factor_gap"}])
    budget = pd.DataFrame([{"pair_id": "A__B", "portfolio_loss_budget_pct": 0.5, "direction_aware_hedged_spread_max_drawdown_pct": -20.0, "diagnostic_gross_notional_pct_nav": 3.0, "risk_status": "borrow_unavailable"}])
    revision = pd.DataFrame([{"pair_id": "A__B", "revision_confirmation_status": "supports_model_direction", "long_latest_signal_direction": "up", "short_latest_signal_direction": "down", "long_latest_signal_date": "2026-08-07", "short_latest_signal_date": "2026-08-07"}])
    frame = build_airline_pair_direction_decision(working=working, trade=trade, pb_trade=pb_trade, factor_review=factors, risk_budget=budget, revision_confirmation=revision)
    row = frame.iloc[0]
    assert row.direction_concordance == "earnings_and_pb_direction_aligned"
    assert row.selected_direction == "long A Co / short B Co"
    assert row.selected_direction_status == "provisional_candidate_not_trade_ready"


def test_priority_set_has_only_two_direction_concordant_candidates() -> None:
    frame = build_airline_pair_direction_decision()
    assert len(frame) == 5
    assert frame.direction_concordance.value_counts().to_dict() == {
        "earnings_and_pb_direction_conflict": 3,
        "earnings_and_pb_direction_aligned": 2,
    }
    assert frame.selected_direction_status.eq("no_direction_due_revision_unconfirmed").sum() == 2
    assert frame.revision_confirmation_status.eq("not_confirmed_no_signal").sum() == 4
    assert frame.revision_confirmation_status.eq("not_confirmed_missing_leg_signal").sum() == 1
