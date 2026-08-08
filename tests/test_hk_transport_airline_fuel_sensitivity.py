from __future__ import annotations

import pandas as pd
import pytest


def test_fuel_sensitivity_scenario_layer_distinguishes_reported_and_mechanical_cases() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_fuel_sensitivity_scenarios.csv")

    assert len(frame) == 42
    assert set(frame["company"]) == {
        "Air China", "China Southern Airlines", "China Eastern Airlines",
        "Spring Airlines", "Juneyao Airlines", "Hainan Airlines Holdings",
        "Cathay Pacific",
    }
    assert frame["jet_fuel_observation_date"].notna().all()
    assert frame[[
        "fx_pair", "fx_observation_date", "fx_value_quote_per_usd",
        "jet_fuel_spot_native_per_gallon", "fuel_cost_usd_mn",
        "post_shock_fuel_cost_usd_mn", "pre_tax_profit_impact_usd_mn",
    ]].notna().all().all()

    air_china = frame.loc[
        frame["company"].eq("Air China") & frame["scenario_fuel_price_change_pct"].eq(5)
    ].iloc[0]
    assert air_china["scenario_method"] == "issuer_reported_5pct_sensitivity"
    assert air_china["pre_tax_profit_impact_native_mn"] == pytest.approx(-2502.0)

    southern = frame.loc[
        frame["company"].eq("China Southern Airlines") & frame["scenario_fuel_price_change_pct"].eq(5)
    ].iloc[0]
    assert southern["scenario_method"] == "mechanical_fuel_cost_proxy"
    assert southern["pre_tax_profit_impact_native_mn"] == pytest.approx(-2626.3)
    assert "100 CNY" in southern["surcharge_reference"]
    assert southern["fx_pair"] == "USD_CNY"
    assert southern["pre_tax_profit_impact_usd_mn"] == pytest.approx(
        southern["pre_tax_profit_impact_native_mn"] / southern["fx_value_quote_per_usd"]
    )

    cathay = frame.loc[
        frame["company"].eq("Cathay Pacific") & frame["scenario_fuel_price_change_pct"].eq(5)
    ].iloc[0]
    assert cathay["fx_pair"] == "USD_HKD"
    assert cathay["jet_fuel_spot_native_per_gallon"] == pytest.approx(
        cathay["jet_fuel_spot_usd_per_gallon"] * cathay["fx_value_quote_per_usd"]
    )
