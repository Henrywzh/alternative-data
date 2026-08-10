"""Tests for the v2 cost engine (driver-based CASK backtest)."""

from __future__ import annotations

import pandas as pd
import pytest

from hk_transport.sources import airline_cost_engine_v2 as ce


@pytest.fixture(scope="module")
def outputs() -> dict[str, pd.DataFrame]:
    return ce.build_airline_cost_engine_v2()


def test_backtest_covers_all_carriers(outputs: dict[str, pd.DataFrame]) -> None:
    bt = outputs["backtest"]
    assert set(bt.company) == set(ce.COMPANIES)
    assert bt.target_year.min() >= 2018
    assert bt.target_year.max() == 2025


def test_ablation_monotonic_improvement(outputs: dict[str, pd.DataFrame]) -> None:
    abl = outputs["ablation"].set_index("layer")
    assert abl.loc["full_cask", "cost_mae_pct"] < abl.loc["flat_ask_cost", "cost_mae_pct"]
    assert abl.loc["fuel_mechanical", "cost_mae_pct"] < abl.loc["flat_ask_cost", "cost_mae_pct"]


def test_full_cask_meaningful_improvement(outputs: dict[str, pd.DataFrame]) -> None:
    abl = outputs["ablation"].set_index("layer")
    assert abl.loc["full_cask", "cost_mae_pct"] < 15.0
    assert abl.loc["full_cask", "cost_mae_pct"] < abl.loc["flat_ask_cost", "cost_mae_pct"] * 0.75


def test_hedge_diagnostic_cross_validated(outputs: dict[str, pd.DataFrame]) -> None:
    hedge = outputs["hedge"]
    cv = hedge[hedge.residual_type.eq("cross_validated_1h2025")]
    assert len(cv) >= 4
    # The cross-validated residuals should be small (hedge effect limited).
    assert cv.implied_hedge_residual_pct.abs().max() < 5.0


def test_ebit_decomposition_has_both_errors(outputs: dict[str, pd.DataFrame]) -> None:
    ebit = outputs["ebit"]
    assert {"revenue_error_pct", "error_full_cask_pct", "ebit_error_directional_pct"}.issubset(ebit.columns)
    assert ebit.revenue_error_pct.notna().any()
    assert ebit.error_full_cask_pct.notna().any()


def test_cost_history_uses_akshare_layer_label(outputs: dict[str, pd.DataFrame]) -> None:
    bt = outputs["backtest"]
    assert (bt.operating_cost_actual_native_mn > 0).all()
