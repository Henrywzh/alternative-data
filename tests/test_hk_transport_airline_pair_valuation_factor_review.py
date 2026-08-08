from __future__ import annotations

from src.hk_transport.sources.airline_pair_valuation_factor_review import build_airline_pair_valuation_factor_review


def test_valuation_factor_review_covers_five_priority_pairs() -> None:
    frame = build_airline_pair_valuation_factor_review()
    assert len(frame) == 5
    assert frame.pair_id.is_unique
    assert frame.long_multiple_compression_10pct_payoff_pct.notna().all()
    assert frame.consensus_market_scope_status.notna().all()


def test_current_directions_do_not_pass_ten_percent_long_multiple_compression() -> None:
    frame = build_airline_pair_valuation_factor_review()
    assert (frame.long_multiple_compression_10pct_payoff_pct < 0).all()
    assert frame.trade_readiness_status.eq("not_trade_ready_valuation_factor_or_scope_gap").all()
