from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_pair_pb_trade_diagnostic import (
    build_airline_pair_pb_trade_diagnostic,
)


def test_pair_pb_diagnostic_has_three_valuation_cases() -> None:
    pb = pd.DataFrame(
        [
            {"asset": "A.HK", "pb_target_return_p25_pct": -10.0, "pb_target_return_median_pct": 5.0, "pb_target_return_p75_pct": 20.0},
            {"asset": "B.SH", "pb_target_return_p25_pct": -20.0, "pb_target_return_median_pct": 10.0, "pb_target_return_p75_pct": 30.0},
        ]
    )
    trade = pd.DataFrame(
        [
            {"pair_id": "A__B", "selection_bucket": "test", "scenario": "base", "company_a": "A", "asset_a": "A.HK", "company_b": "B", "asset_b": "B.SH", "long_leg": "A", "long_asset": "A.HK", "short_leg": "B", "short_asset": "B.SH", "beta_hedge_ratio_long_to_short": 1.0, "observed_hedged_spread_max_drawdown_pct": -20.0, "catalyst_a": "a", "catalyst_b": "b"}
        ]
    )
    frame = build_airline_pair_pb_trade_diagnostic(pb=pb, trade=trade, retrieved_at="2026-08-08T00:00:00+00:00")
    assert len(frame) == 3
    assert set(frame.scenario) == {"bear", "base", "bull"}
    base = frame[frame.scenario.eq("base")].iloc[0]
    assert base.equal_notional_gross_pair_payoff_pct == -5.0
    assert base.valuation_conflict_flag.startswith("pb_cross_check_disagrees")
    assert base.direction_status == "provisional_mechanical_direction_requires_review"
