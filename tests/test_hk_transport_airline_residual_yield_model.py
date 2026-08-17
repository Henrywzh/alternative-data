from __future__ import annotations

import pandas as pd
import pytest

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


def test_historical_pressure_score_is_period_specific_and_not_annual_leaky() -> None:
    """H1/H2 must not consume the other half of the same calendar year."""
    from src.hk_transport.config import NORMALIZED_DIR

    result = build_airline_residual_yield_model()
    pressure = pd.read_csv(NORMALIZED_DIR / "airline_yield_pressure_index.csv")
    pressure["month"] = pressure["month"].astype(str)
    pressure["year"] = pressure["month"].str[:4].astype(int)
    pressure["month_num"] = pressure["month"].str[5:7].astype(int)

    spring_2023 = result[
        result["company"].eq("Spring Airlines")
        & result["target_year"].eq(2023)
        & result["row_status"].eq("historical_evaluated")
    ].set_index("period")
    spring_pressure = pressure[pressure["company"].eq("Spring Airlines") & pressure["year"].eq(2023)]

    expected_h1 = spring_pressure.loc[spring_pressure["month_num"].between(1, 6), "yield_pressure_score"].mean()
    expected_h2 = spring_pressure.loc[spring_pressure["month_num"].between(7, 12), "yield_pressure_score"].mean()
    expected_fy = spring_pressure["yield_pressure_score"].mean()

    assert spring_2023.loc["H1", "yield_pressure_score"] == pytest.approx(expected_h1)
    assert spring_2023.loc["H2", "yield_pressure_score"] == pytest.approx(expected_h2)
    assert spring_2023.loc["FY", "yield_pressure_score"] == pytest.approx(expected_fy)
    assert spring_2023.loc["H1", "yield_pressure_score"] != pytest.approx(expected_fy)
    assert spring_2023.loc["H2", "yield_pressure_score"] != pytest.approx(expected_fy)
