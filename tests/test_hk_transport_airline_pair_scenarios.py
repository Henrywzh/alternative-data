from __future__ import annotations

import pandas as pd
import pytest


def test_pair_scenario_inputs_have_three_explicit_cases_per_pair() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_scenario_inputs.csv")

    assert len(frame) == 63
    assert frame.groupby("pair_id").size().eq(3).all()
    assert set(frame["scenario"]) == {"bear", "base", "bull"}
    assert frame["source_quality"].eq("derived_scenario_stress_test").all()
    assert frame.loc[frame["scenario"].eq("bear"), "scenario_revenue_delta_vs_consensus_pct"].eq(-5).all()
    assert frame.loc[frame["scenario"].eq("base"), "scenario_margin_delta_vs_consensus_pp"].eq(0).all()
    assert frame.loc[frame["scenario"].eq("bull"), "scenario_margin_delta_vs_consensus_pp"].eq(2).all()


def test_core_pair_scenario_base_reconciles_to_detailed_consensus() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_scenario_inputs.csv")
    row = frame.loc[
        frame["pair_id"].eq("601021.SH__603885.SH") & frame["scenario"].eq("base")
    ].iloc[0]
    assert row["company_a"] == "Spring Airlines"
    assert row["company_b"] == "Juneyao Airlines"
    assert row["scenario_net_profit_usd_mn_a"] == pytest.approx(312.702033, abs=1e-5)
    assert row["scenario_net_profit_usd_mn_b"] == pytest.approx(137.381414, abs=1e-5)
    assert row["scenario_profit_gap_a_minus_b_usd_mn"] == pytest.approx(175.320618, abs=1e-5)
    assert row["source_note"].find("not an independent forecast") >= 0
