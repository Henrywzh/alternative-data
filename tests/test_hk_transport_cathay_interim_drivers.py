from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = ROOT / "data" / "normalized" / "hk_transport"


def test_cathay_1h2026_interim_driver_snapshot_is_primary_and_page_anchored() -> None:
    frame = pd.read_csv(TRANSPORT / "airline_cathay_interim_driver_snapshot.csv")

    assert len(frame) == 43
    assert frame["statement_period"].eq("1H2026").all()
    assert frame["period_end"].eq("2026-06-30").all()
    assert frame["source_quality"].eq("primary_issuer").all()
    assert frame["source_page"].notna().all()
    assert frame.loc[frame["metric"].eq("total_revenue"), "value_native"].item() == 68061.0
    assert frame.loc[frame["metric"].eq("fuel_cost"), "value_native"].item() == 23224.0
    assert frame.loc[frame["metric"].eq("fuel_hedging_loss_gain"), "value_native"].item() == -878.0
    assert frame.loc[frame["metric"].eq("recurring_underlying_profit"), "value_native"].item() == 5290.0
    assert frame.loc[frame["metric"].eq("operating_cash_flow"), "value_native"].item() == 13673.0
