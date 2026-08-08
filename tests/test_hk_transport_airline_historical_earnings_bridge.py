from __future__ import annotations

import json

import pandas as pd
import pytest

from hk_transport.sources.airline_historical_earnings_bridge import _detailed_consensus_usd_mn


def test_current_historical_earnings_bridge_aligns_six_companies_and_periods() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_historical_earnings_bridge.csv")

    assert len(frame) == 250
    assert frame["company"].nunique() == 7
    mainland = frame[frame["company"].ne("Cathay Pacific")]
    assert mainland.groupby("company").size().eq(41).all()
    cathay = frame[frame["company"].eq("Cathay Pacific")]
    assert len(cathay) == 4
    assert set(cathay["period_end"]) == {"2024-06-30", "2025-06-30", "2025-12-31", "2026-06-30"}
    assert cathay["bridge_scope"].eq("cathay_cross_region_partial_official_driver_history").all()
    assert cathay.loc[cathay["period_end"].eq("2026-06-30"), "revenue_usd_mn"].notna().all()
    provenance = json.loads(cathay.loc[cathay["period_end"].eq("2026-06-30"), "financial_driver_provenance_json"].item())
    assert provenance["total_revenue"]["source_page"] == 9
    assert provenance["total_revenue"]["native_unit"] == "HKD million"
    assert provenance["total_revenue"]["native_currency"] == "HKD"
    assert frame["period_end"].min() == "2016-03-31"
    assert mainland["period_end"].max() == "2026-03-31"
    assert frame["period_end"].max() == "2026-06-30"
    assert frame["operating_month_count"].between(0, 12).all()
    assert mainland.loc[mainland["company"].ne("Hainan Airlines Holdings"), "operating_month_count"].ge(3).all()
    core = mainland[mainland["company"].ne("Hainan Airlines Holdings") | mainland["period_end"].ne("2016-03-31")]
    assert core[["revenue_usd_mn", "operating_cost_usd_mn", "ask_mn_seat_km", "rpk_mn_passenger_km", "jet_fuel_avg_usd_per_gallon", "usd_cny_avg"]].notna().all().all()
    assert mainland["current_ashare_detailed_fy2026_net_profit_usd_mn"].notna().all()
    assert mainland["current_ashare_detailed_snapshot_date"].eq("2026-08-07").all()
    assert mainland["current_hk_broker_snapshot_date"].notna().sum() == 123
    anomaly = frame.loc[frame["company"].eq("Juneyao Airlines") & frame["period_end"].eq("2019-12-31"), "operating_anomaly_flag"].item()
    assert "passenger_load_factor_gt_100_source_anomaly" in anomaly
    assert mainland["source_quality"].eq("derived_multi_source_bridge").all()
    assert mainland["financial_point_in_time_status"].eq("period_end_only_no_announcement_date").all()
    assert cathay["source_quality"].eq("derived_cross_region_driver_bridge").all()


def test_detailed_consensus_unit_is_normalized_to_usd_millions() -> None:
    assert _detailed_consensus_usd_mn(
        {"value_avg_usd_at_snapshot": 2.7 / 6.75, "native_unit": "RMB 100 million"}
    ) == pytest.approx(40.0)
    assert _detailed_consensus_usd_mn(
        {"value_avg_usd_at_snapshot": 40.0, "native_unit": "RMB million"}
    ) == pytest.approx(40.0)
