from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_pair_risk_budget_sizing import (
    build_airline_pair_risk_budget_sizing,
)


def test_sizing_uses_direction_aware_drawdown_and_budget() -> None:
    working = pd.DataFrame([{"pair_id": "A__B", "selection_bucket": "core", "asset_a": "A", "asset_b": "B", "borrow_data_available_a": False, "borrow_data_available_b": False}])
    trade = pd.DataFrame([{"pair_id": "A__B", "scenario": "base", "long_leg": "B Co", "long_asset": "B", "short_leg": "A Co", "short_asset": "A"}])
    risk = pd.DataFrame([{"asset_a": "A", "asset_b": "B", "beta_a_to_b": 0.5, "beta_b_to_a": 2.0, "hedged_spread_vol_a_minus_beta_b_pct": 10.0, "hedged_spread_vol_b_minus_beta_a_pct": 20.0, "hedged_spread_max_drawdown_a_minus_beta_b_pct": -10.0, "hedged_spread_max_drawdown_b_minus_beta_a_pct": -25.0}])
    factors = pd.DataFrame([{"pair_id": "A__B", "beta_gap_a_minus_b": 0.5, "log_size_gap_a_minus_b": 0.1, "momentum_1y_gap_a_minus_b_pct": -15.0, "volatility_gap_a_minus_b_pct": 12.0}])
    frame = build_airline_pair_risk_budget_sizing(working=working, trade=trade, risk=risk, factors=factors, loss_budgets_pct=(0.5,), retrieved_at="2026-08-08T00:00:00+00:00")
    row = frame.iloc[0]
    assert row.direction_aware_hedged_spread_max_drawdown_pct == -25.0
    assert row.mechanical_beta_hedge_ratio_long_to_short == 2.0
    assert row.diagnostic_long_notional_pct_nav == 2.0
    assert row.diagnostic_short_notional_pct_nav == 4.0
    assert row.diagnostic_gross_notional_pct_nav == 6.0
    assert "borrow_unavailable" in row.risk_status
    assert "material_beta_gap" in row.risk_status


def test_default_artifact_has_three_budget_scenarios_per_priority_pair() -> None:
    frame = build_airline_pair_risk_budget_sizing()
    assert len(frame) == 15
    assert frame.pair_id.nunique() == 5
    assert set(frame.portfolio_loss_budget_pct) == {0.25, 0.5, 1.0}
    assert frame.direction_status.eq("provisional_mechanical_direction_requires_review").all()
