from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_consensus_freshness import build_airline_consensus_freshness


def test_consensus_freshness_contract_exposes_staleness_and_revision_coverage() -> None:
    result = build_airline_consensus_freshness(retrieved_at="2026-08-07T00:00:00+00:00")

    assert len(result) == 47
    assert result.duplicated(["ticker", "source_layer"]).sum() == 0
    assert result[["as_of_date", "latest_observation_date", "freshness_band"]].notna().all().all()

    cathay = result.loc[
        result["company"].eq("Cathay Pacific")
        & result["source_layer"].eq("hk_broker_profit_consensus")
    ].iloc[0]
    assert cathay["freshness_band"] == "fresh"
    assert cathay["prior_comparison_count"] == 0

    hainan = result.loc[
        result["company"].eq("Hainan Airlines Holdings")
        & result["source_layer"].eq("ashare_profit_consensus")
    ].iloc[0]
    assert hainan["freshness_band"] == "stale"
    assert hainan["age_days"] > 90

    em = result.loc[result["source_layer"].eq("ashare_em_profit_consensus")]
    assert len(em) == 6
    assert em["freshness_band"].eq("fresh").all()
    assert em["prior_comparison_count"].eq(0).all()

    mainland_pdf = result.loc[result["source_layer"].eq("mainland_revenue_sell_side_pdf")]
    assert mainland_pdf["prior_comparison_count"].sum() == 48
    assert mainland_pdf["freshness_band"].isin({"aging", "stale"}).all()

    public = result.loc[result["source_layer"].eq("public_report_evidence")]
    assert len(public) == 6
    assert public["metric_scope"].eq("public EPS/net profit/revenue evidence").all()
    assert public["latest_observation_date"].notna().all()
    assert public["latest_snapshot_date"].eq("2026-08-07").all()
    assert public["revision_history_available"].eq(False).all()
    assert public["source_quality"].eq("10jqka_structured_page").all()

    eps_proxy = result.loc[result["source_layer"].eq("mainland_eps_sell_side_revision_proxy")]
    assert len(eps_proxy) == 5
    assert eps_proxy["metric_scope"].eq("EPS revision proxy").all()
    assert eps_proxy["prior_comparison_count"].sum() == 114
    assert eps_proxy["revision_history_available"].all()
