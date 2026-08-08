from __future__ import annotations

from src.hk_transport.sources.airline_pair_trade_thesis import build_airline_pair_trade_thesis_scenarios


def test_trade_thesis_scenarios_cover_five_priority_pairs_and_three_cases() -> None:
    frame = build_airline_pair_trade_thesis_scenarios()
    assert len(frame) == 15
    assert frame.pair_id.nunique() == 5
    assert set(frame.scenario) == {"bear", "base", "bull"}
    assert frame.direction_status.eq("provisional_mechanical_direction_requires_review").all()
    assert frame.target_price_method.notna().all()


def test_trade_thesis_exposes_payoff_risk_catalyst_and_invalidation_fields() -> None:
    frame = build_airline_pair_trade_thesis_scenarios()
    required = [
        "long_leg", "short_leg", "variant_perception", "beta_hedge_ratio_long_to_short",
        "beta_hedged_pair_payoff_pct", "payoff_to_observed_max_drawdown",
        "catalyst_a", "catalyst_b", "risk_rule", "trade_construction_rule",
    ]
    assert frame[required].notna().all().all()
