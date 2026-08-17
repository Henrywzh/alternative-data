from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_pair_event_trade_triggers import (
    build_airline_pair_event_trade_triggers,
)


def test_event_trigger_requires_surprise_revision_and_valuation_confirmation() -> None:
    working = pd.DataFrame([{"pair_id": "A__B", "selection_bucket": "core", "asset_a": "A", "asset_b": "B", "variant_perception_a_gap_pct": -10.0, "variant_perception_b_gap_pct": -2.0, "base_revenue_gap_a_pct": -8.0, "base_revenue_gap_b_pct": -2.0, "report_date_a": "2026-08-29", "report_date_b": "2026-08-31"}])
    trade = pd.DataFrame([{"pair_id": "A__B", "scenario": "base", "long_asset": "B", "short_asset": "A", "long_leg": "B Co", "short_leg": "A Co"}])
    direction = pd.DataFrame([{"pair_id": "A__B", "selected_direction_status": "no_direction_due_revision_unconfirmed"}])
    revision = pd.DataFrame([{"pair_id": "A__B", "revision_confirmation_status": "not_confirmed_no_signal"}])
    target = pd.DataFrame([{"pair_id": "A__B", "scenario": "base", "beta_hedged_pair_payoff_low_pct": -10.0, "beta_hedged_pair_payoff_high_pct": 20.0}])
    risk = pd.DataFrame([{"pair_id": "A__B", "portfolio_loss_budget_pct": 0.5, "direction_aware_hedged_spread_max_drawdown_pct": -20.0, "diagnostic_gross_notional_pct_nav": 3.0, "risk_status": "borrow_unavailable"}])
    frame = build_airline_pair_event_trade_triggers(working=working, trade=trade, direction=direction, revision=revision, target_range=target, risk=risk)
    row = frame.iloc[0]
    assert row.conditional_direction == "long B Co / short A Co"
    assert row.minimum_profit_surprise_gap_for_entry_pp == 4.0
    assert row.minimum_revenue_surprise_gap_for_entry_pp == 3.0
    assert row.trade_status == "wait_for_event_trigger_no_pre_event_trade"
    assert "fresh revision signal" in row.entry_trigger


def test_priority_matrix_has_one_trigger_row_per_pair() -> None:
    frame = build_airline_pair_event_trade_triggers()
    assert len(frame) == 5
    assert frame.pair_id.is_unique
    assert frame.trade_status.eq("wait_for_event_trigger_no_pre_event_trade").all()


def test_spring_juneyao_entry_threshold_uses_the_independent_pre_event_view() -> None:
    frame = build_airline_pair_event_trade_triggers()
    row = frame.loc[frame.pair_id.eq("601021.SH__603885.SH")].iloc[0]
    assert row.surprise_threshold_basis == "independent_pre_event_forecast"
    assert row.pre_event_profit_gap_spread_pp > 30.0
    assert row.minimum_profit_surprise_gap_for_entry_pp > 15.0
