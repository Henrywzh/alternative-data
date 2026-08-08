from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_valuation_peer_comparability import (
    build_airline_valuation_peer_comparability,
)


def test_priority_pairs_are_blocked_when_historical_market_series_is_missing() -> None:
    frame = build_airline_valuation_peer_comparability(retrieved_at="2026-08-08T00:00:00+00:00")
    assert len(frame) == 5
    assert frame.pair_id.is_unique
    assert frame.historical_market_multiple_status_a.eq("missing_historical_price_market_cap_series").all()
    assert frame.historical_market_multiple_status_b.eq("missing_historical_price_market_cap_series").all()
    assert frame.valuation_method_status.eq("current_relative_ps_only_no_historical_multiple").all()
    assert frame.valuation_target_readiness.eq("not_ready_missing_historical_multiple_evidence").all()
    assert frame.historical_pb_status_a.eq("dated_1y_pb_history_available").all()
    assert frame.historical_pb_status_b.eq("dated_1y_pb_history_available").all()


def test_business_model_classes_make_spring_pairs_explicitly_non_like_for_like() -> None:
    frame = build_airline_valuation_peer_comparability()
    southern = frame[frame.pair_id.eq("01055.HK__601021.SH")].iloc[0]
    spring_juneyao = frame[frame.pair_id.eq("601021.SH__603885.SH")].iloc[0]
    assert southern.business_model_match_status == "network_vs_low_cost_not_like_for_like"
    assert spring_juneyao.business_model_match_status == "different_business_model_or_group_scope"
    assert spring_juneyao.consolidated_scope_b == "listed_group_consolidated_including_9air"


def test_injected_same_model_market_series_can_clear_the_missing_history_gate() -> None:
    fundamentals = pd.DataFrame(
        [
            {"company": "Air China", "operating_scope_warning": ""},
            {"company": "China Southern Airlines", "operating_scope_warning": ""},
        ]
    )
    history = pd.DataFrame(
        [
            {"company": "Air China", "metric": "price", "period_end": "2025-12-31", "point_in_time_status": "pit"},
            {"company": "China Southern Airlines", "metric": "market_cap", "period_end": "2025-12-31", "point_in_time_status": "pit"},
        ]
    )
    working = pd.DataFrame(
        [
            {
                "pair_id": "A__B", "selection_bucket": "test", "company_a": "Air China", "asset_a": "A.HK", "market_a": "HKEX",
                "company_b": "China Southern Airlines", "asset_b": "B.HK", "market_b": "HKEX", "ps_consensus_revenue_a": 1.0,
                "ps_consensus_revenue_b": 1.1, "pe_consensus_profit_a": 10.0, "pe_consensus_profit_b": 11.0,
            }
        ]
    )
    frame = build_airline_valuation_peer_comparability(
        fundamentals=fundamentals, history=history, working=working, retrieved_at="2026-08-08T00:00:00+00:00"
    )
    row = frame.iloc[0]
    assert row.valuation_method_status == "current_relative_ps_with_historical_market_series_check_pending"
    assert row.valuation_target_readiness == "candidate_for_historical_peer_valuation_review"
