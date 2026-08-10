from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_consensus_reverse import (
    _effective_tax_rate,
    build_airline_consensus_reverse,
)


def test_effective_tax_rate_prefers_interim_and_guards_loss_years() -> None:
    drivers = pd.DataFrame(
        [
            {"company": "Test", "report_type": "annual",
             "metric": "profit_total", "value_native": 100.0},
            {"company": "Test", "report_type": "annual",
             "metric": "income_tax_expense", "value_native": 30.0},
            # loss-year artifact: tax / negative PBT = -120% (must be rejected)
            {"company": "Loss", "report_type": "interim",
             "metric": "profit_total", "value_native": -100.0},
            {"company": "Loss", "report_type": "interim",
             "metric": "income_tax_expense", "value_native": 120.0},
        ]
    )
    assert _effective_tax_rate(drivers, "Test") == 0.30
    assert _effective_tax_rate(drivers, "Loss") is None


def test_build_reverse_covers_all_carriers_with_rask_gap() -> None:
    df = build_airline_consensus_reverse()
    assert len(df) == 6
    assert df["consensus_revenue_native_mn"].notna().all()
    assert df["implied_rask_native"].notna().all()
    assert df["rask_gap_pct"].notna().all()
    # Juneyao should show the largest positive RASK gap: Street assumes
    # higher pricing power than our model.
    juneyao = df[df["company"].eq("Juneyao Airlines")].iloc[0]
    assert juneyao["rask_gap_pct"] > 5.0
    spring = df[df["company"].eq("Spring Airlines")].iloc[0]
    assert spring["rask_gap_pct"] < juneyao["rask_gap_pct"]


def test_reverse_method_documents_anchors() -> None:
    df = build_airline_consensus_reverse()
    assert df["reverse_method"].str.contains("consensus_net->pbt").all()
    assert df["anchor_source"].str.contains("consensus_ashare").all()
