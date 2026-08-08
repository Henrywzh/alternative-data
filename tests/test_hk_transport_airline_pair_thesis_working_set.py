from __future__ import annotations

from src.hk_transport.sources.airline_pair_thesis_working_set import build_airline_pair_thesis_working_set


def test_thesis_working_set_contains_selected_pairs_and_spring_juneyao_monitor() -> None:
    frame = build_airline_pair_thesis_working_set()
    assert len(frame) == 5
    assert frame.pair_id.is_unique
    assert "601021.SH__603885.SH" in set(frame.pair_id)
    assert frame.thesis_status.eq("direction_pending_review").all()
    assert frame.next_evidence_gate.notna().all()


def test_thesis_working_set_exposes_valuation_catalyst_and_trade_risk_fields() -> None:
    frame = build_airline_pair_thesis_working_set()
    required = [
        "ps_consensus_revenue_a", "ps_consensus_revenue_b",
        "report_date_a", "report_date_b", "warning_date_a", "warning_date_b",
        "correlation_a_b", "hedged_spread_max_drawdown_pct",
        "factor_beta_gap_a_minus_b", "invalidation_rule_count_a", "invalidation_rule_count_b",
    ]
    assert frame[required].notna().all().all()
