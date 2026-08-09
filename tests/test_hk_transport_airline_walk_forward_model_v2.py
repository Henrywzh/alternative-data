"""Tests for the leakage-safe airline walk-forward model v2."""

from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_walk_forward_model_v2 import (
    MODEL_SPECS,
    build_airline_walk_forward_model_v2,
)


@pytest.fixture(scope="module")
def v2_result(tmp_path_factory: pytest.TempPathFactory):
    output_dir = tmp_path_factory.mktemp("airline_walk_forward_v2")
    return build_airline_walk_forward_model_v2(
        as_of_date="2026-08-09",
        output_path=output_dir / "detail.csv",
        summary_output_path=output_dir / "summary.csv",
        current_forecast_output_path=output_dir / "current.csv",
    )


def test_v2_contains_declared_models_and_h1_current_forecast(v2_result) -> None:
    detail, summary, current = v2_result
    assert set(detail["model_name"].dropna().unique()) == {item[0] for item in MODEL_SPECS}
    assert set(summary["model_name"].unique()) == {item[0] for item in MODEL_SPECS}
    assert set(current["period"].unique()) == {"H1"}
    assert set(current["target_year"].unique()) == {2026}
    assert current["target_revenue_native_mn"].isna().all()
    assert current["target_operating_cost_native_mn"].isna().all()


def test_walk_forward_training_never_uses_target_or_future_year(v2_result) -> None:
    detail, _, current = v2_result
    evaluated = detail.loc[detail["row_status"].eq("historical_evaluated")].copy()
    training_year = pd.to_numeric(evaluated["walk_forward_training_max_target_year"], errors="coerce")
    target_year = pd.to_numeric(evaluated["target_year"], errors="coerce")
    # The first historical target year has no earlier training sample and is
    # therefore explicitly a fallback row with a null training maximum.
    assert (training_year.dropna() < target_year.loc[training_year.notna()]).all()
    current_training_year = pd.to_numeric(current["walk_forward_training_max_target_year"], errors="coerce")
    assert (current_training_year < 2026).all()


def test_h2_financial_label_keeps_fy_minus_h1_identity(v2_result) -> None:
    detail, _, _ = v2_result
    base = detail.drop_duplicates(["company", "target_year", "period"])
    for (company, year), group in base.groupby(["company", "target_year"]):
        h1 = group.loc[group["period"].eq("H1")]
        h2 = group.loc[group["period"].eq("H2")]
        fy = group.loc[group["period"].eq("FY")]
        if h1.empty or h2.empty or fy.empty:
            continue
        values = [
            h1["target_revenue_native_mn"].iloc[0],
            h2["target_revenue_native_mn"].iloc[0],
            fy["target_revenue_native_mn"].iloc[0],
        ]
        if all(pd.notna(value) for value in values):
            assert abs(values[0] + values[1] - values[2]) < 1.0


def test_integrated_operating_profit_proxy_is_revenue_less_cost(v2_result) -> None:
    detail, _, current = v2_result
    for frame in (detail, current):
        check = frame.dropna(subset=["predicted_revenue_native_mn", "predicted_operating_cost_native_mn", "predicted_operating_profit_proxy_native_mn"])
        assert (check["predicted_revenue_native_mn"] - check["predicted_operating_cost_native_mn"] - check["predicted_operating_profit_proxy_native_mn"]).abs().max() < 1e-6


def test_fuel_bridge_retains_vintage_limitation(v2_result) -> None:
    detail, _, current = v2_result
    assert detail["fuel_pit_status"].dropna().astype(str).str.contains("release_vintage_unverified").any()
    assert current["fuel_growth_pct"].notna().all()
    assert current["fuel_source_release_date"].notna().all()
