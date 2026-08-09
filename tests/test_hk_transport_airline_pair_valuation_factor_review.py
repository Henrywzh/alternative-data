from __future__ import annotations

from src.hk_transport.sources.airline_pair_valuation_factor_review import build_airline_pair_valuation_factor_review


def test_valuation_factor_review_covers_five_priority_pairs() -> None:
    frame = build_airline_pair_valuation_factor_review()
    assert len(frame) == 5
    assert frame.pair_id.is_unique
    assert frame.long_multiple_compression_10pct_payoff_pct.notna().all()
    assert frame.consensus_market_scope_status.notna().all()


def test_current_directions_are_never_auto_promoted_to_trade_ready() -> None:
    """Some pairs' current spreads are wide enough to survive a flat 10pp
    long-multiple compression stress (payoff stays positive) with no
    material factor gap and same-market legs -- clearing the quant screen.
    That is necessary but not sufficient: required_next_evidence lists
    corroborating work (route-level yield, 1H2026 actuals, HK/A consensus
    reconciliation, a real factor-residual test, a non-constant P/S target)
    that nothing here has gathered yet, and this chain is research-only in
    v1 with no trading signal. So readiness must never auto-promote on the
    quant screen alone, no matter how the compression stress lands.
    """
    frame = build_airline_pair_valuation_factor_review()
    assert frame.trade_readiness_status.isin([
        "not_trade_ready_valuation_factor_or_scope_gap",
        "not_trade_ready_pending_required_evidence",
    ]).all()
    assert frame.required_next_evidence.ne("").all()
