from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_residual_yield_model import (
    LAMBDA,
    _yield_bucket,
    build_airline_residual_yield_model,
)


def test_yield_bucket_three_class() -> None:
    assert _yield_bucket(0.6) == "improving"
    assert _yield_bucket(-0.6) == "deteriorating"
    assert _yield_bucket(0.1) == "flat"
    assert _yield_bucket(None) == "unknown"


def test_shrinkage_is_bounded_by_lambda() -> None:
    assert 0.0 < LAMBDA < 1.0


def test_residual_model_covers_all_carriers_and_both_row_types() -> None:
    df = build_airline_residual_yield_model()
    assert len(df) > 150
    assert df["company"].nunique() == 6
    assert set(df["row_status"].unique()) >= {"historical_evaluated", "current_forecast"}
    assert df["flat_yield_revenue_native_mn"].notna().all()
    assert df["yield_adjustment_pct"].abs().le(10.0).all()  # bounded by shrink


def test_spring_adjusted_mae_improves_historically() -> None:
    df = build_airline_residual_yield_model()
    spring = df[df["company"].eq("Spring Airlines") & df["row_status"].eq("historical_evaluated")]
    flat_mae = spring["flat_yield_revenue_mae_pct"].mean()
    adj_mae = spring["adjusted_revenue_mae_pct"].mean()
    assert adj_mae < flat_mae


def test_current_forecast_uses_flat_yield_when_signal_weak() -> None:
    df = build_airline_residual_yield_model()
    current = df[df["row_status"].eq("current_forecast")]
    # With weak recent yield-pressure scores, the model keeps flat-yield
    # (adjustment 0) rather than forcing a move.
    assert (current["yield_adjustment_pct"] == 0.0).all()
