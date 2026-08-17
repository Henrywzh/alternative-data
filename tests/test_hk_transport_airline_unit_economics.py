from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_unit_economics import (
    _juneyao_fy2025_components,
    _spring_fy2025_components,
    build_airline_unit_economics,
)


def test_spring_fy2025_components_sum_to_operating_cost() -> None:
    components = _spring_fy2025_components()
    operating_cost = 18_544.164818
    total = sum(components.values())
    # shares applied to operating cost, so total == operating cost
    assert total == pytest.approx(operating_cost, rel=1e-6)


def test_juneyao_fy2025_components_fuel_consistent_with_unit_disclosure() -> None:
    components = _juneyao_fy2025_components()
    ask = 57_178.0275
    fuel_cask = components["fuel"] / ask
    # 0.34 unit CASK - 0.23 ex-fuel = 0.11 fuel CASK
    assert fuel_cask == pytest.approx(0.11, abs=1e-4)
    assert components["fuel_share_pct_anchor"] == pytest.approx(33.11)


def test_unit_economics_builds_all_six_carriers() -> None:
    df = build_airline_unit_economics()
    assert len(df) == 6
    assert df["cask_native"].notna().all()
    assert df["rask_native"].notna().all()
    assert df["cask_ex_fuel_native"].notna().all()


def test_spring_has_full_decomposition_and_lower_cask_than_juneyao() -> None:
    df = build_airline_unit_economics()
    spring = df[df["company"].eq("Spring Airlines")].iloc[0]
    juneyao = df[df["company"].eq("Juneyao Airlines")].iloc[0]
    assert spring["component_status"] == "full_decomposition"
    assert spring["cask_native"] < juneyao["cask_native"]
    assert spring["cask_ex_fuel_native"] < juneyao["cask_ex_fuel_native"]
    # The LCC advantage is non-fuel: fuel shares are nearly identical.
    assert abs(spring["fuel_cost_share_pct"] - juneyao["fuel_cost_share_pct"]) < 1.0
    assert spring["unit_profit_proxy"] == pytest.approx(
        spring["rask_native"] - spring["cask_native"]
    )
