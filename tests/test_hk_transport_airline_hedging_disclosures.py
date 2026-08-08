from __future__ import annotations

from pathlib import Path

import pandas as pd

from hk_transport.sources.airline_hedging_disclosures import build_airline_hedging_disclosures


ROOT = Path(__file__).resolve().parents[1]
TRANSPORT = ROOT / "data" / "normalized" / "hk_transport"


def test_primary_report_hedging_layer_keeps_notional_fair_value_and_policy_separate() -> None:
    frame = pd.read_csv(TRANSPORT / "airline_hedging_disclosures.csv")

    assert len(frame) == 13
    assert frame["report_id"].nunique() == 12
    assert frame["source_url"].notna().all()
    assert frame["scan_scope"].notna().all()
    assert frame["parse_status"].notna().all()

    eastern = frame.loc[frame["report_id"].eq("600115_2025_fy")]
    position = eastern.loc[eastern["disclosure_type"].eq("position")].iloc[0]
    fair_value = eastern.loc[eastern["disclosure_type"].eq("fair_value")].iloc[0]
    assert position["notional_native"] == 500_000
    assert position["notional_unit"] == "barrels"
    assert position["source_page"] == 41
    assert fair_value["fair_value_change_native"] == 3.75
    assert fair_value["fair_value_end_native"] == 3.75
    assert fair_value["native_currency"] == "RMB"
    assert fair_value["source_page"] == 36

    eastern_h1 = frame.loc[frame["report_id"].eq("600115_2025_h1")].iloc[0]
    assert eastern_h1["hedge_status"] == "policy_or_activity_not_quantified"
    assert pd.isna(eastern_h1["notional_native"])

    southern = frame.loc[frame["company"].eq("China Southern Airlines")]
    assert southern["hedge_status"].eq("no_fuel_futures_in_period").all()
    assert southern["source_page"].notna().all()
    assert southern["notional_native"].isna().all()


def test_hedging_scan_does_not_turn_missing_anchors_into_zero_hedges() -> None:
    frame = build_airline_hedging_disclosures(retrieved_at="2026-08-07T00:00:00+00:00")
    scan_rows = frame.loc[frame["disclosure_type"].eq("scan_result")]

    assert len(scan_rows) == 8
    assert scan_rows["hedge_status"].eq("no_explicit_fuel_hedge_anchor_found_in_scan").all()
    assert scan_rows["notional_native"].isna().all()
    assert scan_rows["fair_value_change_native"].isna().all()
    assert scan_rows["source_quality"].eq("primary_issuer_scan_audit").all()
