from __future__ import annotations

import pandas as pd


def test_pair_risk_matrix_covers_all_unique_pairs() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_risk_metrics.csv")

    assert len(frame) == 21
    assert frame["asset_a"].nunique() >= 1
    assert frame["asset_b"].nunique() >= 1
    assert frame.duplicated(["asset_a", "asset_b", "snapshot_date", "window_label"]).sum() == 0
    assert frame["observations"].ge(30).all()
    assert frame["correlation_a_b"].between(-1, 1).all()
    assert frame["beta_a_to_b"].notna().all()
    assert frame["beta_b_to_a"].notna().all()
    assert frame["hedged_spread_max_drawdown_a_minus_beta_b_pct"].notna().all()
    assert frame["hedged_spread_max_drawdown_b_minus_beta_a_pct"].notna().all()
    assert frame["borrow_data_available_a"].eq(False).all()
    assert frame["borrow_data_available_b"].eq(False).all()


def test_pair_risk_matrix_distinguishes_same_market_and_cross_market_pairs() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_risk_metrics.csv")

    assert frame["same_market"].any()
    assert (~frame["same_market"]).any()
    assert frame["source_quality"].eq("yfinance_discovery").all()
