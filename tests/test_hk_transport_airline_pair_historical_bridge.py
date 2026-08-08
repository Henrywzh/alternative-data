from __future__ import annotations

import pandas as pd
import pytest


def test_pair_historical_bridge_covers_universe_and_priority_buckets() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_historical_bridge.csv")

    assert len(frame) == 21
    assert frame["pair_id"].is_unique
    assert frame["source_quality"].eq("derived_pair_historical_bridge").all()
    assert set(frame["pair_selection_bucket"]) == {
        "core_candidate", "backup_candidate", "cross_market_backup", "monitor"
    }
    core = frame.loc[frame["pair_selection_bucket"].eq("core_candidate")].iloc[0]
    assert {core["company_a"], core["company_b"]} == {"Spring Airlines", "Juneyao Airlines"}
    assert core["historical_bridge_status"] == "complete"
    assert core["historical_divergence_status"] == "material_historical_divergence"
    assert core["fy2025_net_margin_gap_a_minus_b_pp"] == pytest.approx(6.178421, abs=1e-5)
    assert core["current_ashare_detailed_consensus_net_profit_gap_a_minus_b_usd_mn"] == pytest.approx(175.320618, abs=1e-5)

    backup = frame.loc[frame["pair_selection_bucket"].eq("backup_candidate")].iloc[0]
    assert {backup["company_a"], backup["company_b"]} == {"China Southern Airlines", "China Eastern Airlines"}
    assert backup["historical_bridge_status"] == "complete"
    assert backup["q1_2026_demand_capacity_gap_a_minus_b_pp"] == pytest.approx(-3.815491, abs=1e-5)

    cathay = frame.loc[frame["pair_selection_bucket"].eq("cross_market_backup")]
    assert len(cathay) == 6
    assert cathay["historical_bridge_status"].eq("partial").all()
    assert cathay["historical_divergence_status"].eq("historical_bridge_incomplete").all()


def test_pair_historical_bridge_retains_anomaly_and_expectation_caveats() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_historical_bridge.csv")
    core = frame.loc[frame["pair_selection_bucket"].eq("core_candidate")].iloc[0]
    assert "passenger_load_factor_gt_100_source_anomaly" in str(core["operating_anomaly_flag_b"])
    assert core["source_note"].find("not historical vintages") >= 0
