from __future__ import annotations

from src.hk_transport.sources.airline_pair_valuation_factor_review import build_airline_pair_valuation_factor_review


def test_valuation_factor_review_covers_five_priority_pairs() -> None:
    frame = build_airline_pair_valuation_factor_review()
    assert len(frame) == 5
    assert frame.pair_id.is_unique
    assert frame.long_multiple_compression_10pct_payoff_pct.notna().all()
    assert frame.consensus_market_scope_status.notna().all()
    assert frame.residual_test_status.eq("estimated").all()
    core = frame.loc[frame.pair_id.eq("601021.SH__603885.SH")].iloc[0]
    assert core.pre_event_independent_view_status == "pre_event_view_defined"
    assert core.pre_event_independent_beta_hedged_pair_payoff_pct > 0


def test_historical_ps_reversion_does_not_bypass_valuation_readiness_gate() -> None:
    frame = build_airline_pair_valuation_factor_review()
    assert frame.long_multiple_compression_10pct_payoff_pct.notna().all()
    assert frame.valuation_gate_status.str.startswith("not_ready_").all()
    assert frame.trade_readiness_status.eq("not_trade_ready_valuation_factor_or_scope_gap").all()
    assert frame.residual_alpha_annualized_pct.notna().all()
