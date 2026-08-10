from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_trade_construction import (
    build_airline_trade_construction,
)


def test_trade_card_integrates_all_layers() -> None:
    df = build_airline_trade_construction()
    assert len(df) == 1
    row = df.iloc[0]
    assert row["direction"] == "long_Spring_short_Juneyao"
    assert row["cask_advantage_pct"] > 10.0
    assert row["ask_growth_spread_pp"] > 10.0
    assert row["short_implied_rask_gap_pct"] > 5.0
    assert row["beta_hedge_ratio"] > 0.5


def test_sensitivity_robustness_is_explicit() -> None:
    df = build_airline_trade_construction()
    row = df.iloc[0]
    assert row["sensitivity_robust_combinations"] == 27
    assert row["sensitivity_total_combinations"] == 27
    assert row["sensitivity_min_pair_spread"] > 1.0


def test_trade_status_is_explicitly_not_approved() -> None:
    df = build_airline_trade_construction()
    row = df.iloc[0]
    assert "not_approved" in row["trade_status"]
    assert "borrow" in row["remaining_gates"]
    assert row["catalyst_window"] == "2026-08-29; 2026-08-31"
