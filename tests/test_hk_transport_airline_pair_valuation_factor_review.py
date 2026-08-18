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
    assert frame.residual_alpha_annualized_pct.notna().all()

    # The gate is what must hold: no pair reaches trade-ready while the
    # valuation target is not ready, however good the quant screen looks.
    assert not frame.trade_readiness_status.eq("provisional_trade_ready_for_review").any()

    # But the two rejection reasons stay distinct. Asserting a single status
    # across all five rows used to hide that a pair clearing the quant screen
    # was being reported as having a valuation/factor/scope gap it does not
    # have; the label must name the reason that actually applies.
    screened = frame.loc[frame.quant_screen_status.eq("passed")]
    assert set(screened.pair_id) == {"600221.SH__601021.SH", "601021.SH__603885.SH"}
    assert screened.trade_readiness_status.eq("not_trade_ready_pending_required_evidence").all()
    assert screened.consensus_market_scope_status.eq("same_market_leg").all()
    assert not screened.factor_risk_status.eq("material_factor_gap").any()

    rejected = frame.loc[frame.quant_screen_status.eq("failed")]
    assert len(rejected) == 3
    assert rejected.trade_readiness_status.eq("not_trade_ready_valuation_factor_or_scope_gap").all()
