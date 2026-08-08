from __future__ import annotations

import pandas as pd
import pytest


def test_core_pair_model_inputs_cover_both_legs_and_required_model_fields() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_core_pair_model_inputs.csv")

    assert len(frame) == 2
    assert set(frame["company"]) == {"Spring Airlines", "Juneyao Airlines"}
    required = [
        "fy2025_revenue_usd_mn", "fy2025_attributable_profit_usd_mn",
        "h1_2025_revenue_usd_mn", "q1_2026_demand_capacity_gap_pp",
        "fy2026_consensus_revenue_usd_mn", "fy2026_consensus_net_profit_usd_mn",
        "scenario_bear_profit_usd_mn", "scenario_base_profit_usd_mn", "scenario_bull_profit_usd_mn",
    ]
    assert frame[required].notna().all().all()
    assert frame["primary_fy2025_operating_cost_status"].eq("official_provider_mismatch").all()
    assert frame["source_quality"].eq("derived_core_pair_model_inputs").all()


def test_core_pair_model_preserves_the_relative_profit_and_valuation_gap() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_core_pair_model_inputs.csv").set_index("company")
    spring = frame.loc["Spring Airlines"]
    juneyao = frame.loc["Juneyao Airlines"]
    assert spring["fy2025_attributable_profit_usd_mn"] - juneyao["fy2025_attributable_profit_usd_mn"] == pytest.approx(182.510985, abs=1e-5)
    assert spring["fy2026_market_cap_to_consensus_revenue"] - juneyao["fy2026_market_cap_to_consensus_revenue"] == pytest.approx(0.8321, abs=1e-3)
