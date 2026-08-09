from __future__ import annotations

from src.hk_transport.sources.airline_pre_event_trade_candidate import (
    build_airline_pre_event_trade_candidate,
)


def test_spring_juneyao_is_a_controlled_risk_pre_event_candidate() -> None:
    frame = build_airline_pre_event_trade_candidate()
    assert len(frame) == 5
    row = frame.loc[frame.pair_id.eq("601021.SH__603885.SH")].iloc[0]
    assert row.candidate_status == "conditional_pre_event_candidate_with_valuation_conflict"
    assert row.direction == "long Spring Airlines / short Juneyao Airlines"
    assert row.independent_profit_gap_spread_pct > 30.0
    assert row.independent_beta_hedged_payoff_pct > 0
    assert row.pb_equal_notional_payoff_pct < 0
    assert row.valuation_payoff_low_pct < 0 < row.valuation_payoff_high_pct
    assert row.portfolio_loss_budget_pct == 0.25
    assert row.diagnostic_gross_notional_pct_nav > 0
    assert row.event_window == "2026-08-29; 2026-08-31"

