from __future__ import annotations

import pandas as pd


def test_primary_financial_reconciliation_has_full_period_metric_grid() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_primary_financial_reconciliation.csv")

    assert len(frame) == 60
    assert frame.groupby(["company", "statement_period"]).size().eq(5).all()
    assert frame["source_quality"].eq("primary_vs_provider_reconciliation").all()
    assert frame["official_source_url"].notna().sum() >= 54
    assert frame["reconciliation_status"].isin(
        {"matched", "official_provider_mismatch", "official_gap_provider_only", "provider_gap_official_only", "both_missing"}
    ).all()


def test_core_and_backup_reconciliation_matches_results_but_flags_operating_cost_scope() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_primary_financial_reconciliation.csv")
    names = {"Spring Airlines", "Juneyao Airlines", "China Southern Airlines", "China Eastern Airlines"}
    core = frame.loc[frame["company"].isin(names)]
    matched = core.loc[core["metric"].isin({"total_revenue", "attributable_net_income", "operating_cash_flow", "basic_eps"})]
    assert (matched["reconciliation_status"].eq("matched") | matched["reconciliation_status"].str.startswith("official_gap")).all()
    costs = core.loc[core["metric"].eq("operating_cost")]
    assert costs["reconciliation_status"].eq("official_provider_mismatch").all()
    assert costs["difference_pct_vs_provider"].abs().gt(5).all()
