from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_consensus_dispersion_all import build_airline_consensus_dispersion_all


def test_all_name_consensus_dispersion_covers_dual_and_single_market_names() -> None:
    result = build_airline_consensus_dispersion_all(retrieved_at="2026-08-07T00:00:00+00:00")

    assert len(result) == 7
    assert result["company"].nunique() == 7
    assert result.loc[result["company"].eq("Air China"), "vintage_status"].item() == "dual_market_consensus"
    assert result.loc[result["company"].eq("Cathay Pacific"), "vintage_status"].item() == "hk_only_consensus"
    assert result.loc[result["company"].eq("Spring Airlines"), "vintage_status"].item() == "a_share_only_consensus"
    assert result.loc[result["company"].eq("Air China"), "profit_sign_disagreement_hk_vs_a"].item() is True
    air_china = result.loc[result["company"].eq("Air China")].iloc[0]
    assert air_china["public_eps_count"] > 0
    assert air_china["public_eps_low_native"] <= air_china["public_eps_median_native"] <= air_china["public_eps_high_native"]
    assert air_china["public_net_profit_latest_report_date"] == "2026-07-21"
    assert air_china["public_revenue_count"] > 0
    assert result["source_quality"].eq("derived_consensus_reconciliation").all()


def test_dispersion_layer_keeps_range_crossing_zero_as_a_flag() -> None:
    result = build_airline_consensus_dispersion_all()

    dual = result.loc[result["vintage_status"].eq("dual_market_consensus")]
    assert dual["dispersion_status"].str.contains("range_crosses_zero").all()
    assert result["em_buy_add_pct_2026"].dropna().between(0, 100).all()
