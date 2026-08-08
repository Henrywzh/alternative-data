from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_sector_external_outlook import build_airline_sector_external_outlook


def test_sector_external_outlook_preserves_dated_vintages_and_statuses() -> None:
    result = build_airline_sector_external_outlook(retrieved_at="2026-08-07T00:00:00+00:00")
    assert len(result) == 62
    assert result.duplicated(["source_url", "source_document_date", "period", "scope", "metric"]).sum() == 0
    assert result["source_url"].notna().all()
    assert result["source_document_date"].notna().all()
    assert set(result["status"]) == {"forecast", "actual", "planned_schedule"}
    assert result["source_organization"].isin({"IATA", "CAAC"}).all()
    caac_june = result.loc[
        (result["source_organization"].eq("CAAC"))
        & result["period"].eq("2026-06")
        & result["scope"].eq("China")
    ]
    assert caac_june.loc[caac_june["metric"].eq("passenger_rpk"), "value"].iloc[0] == 1074.3
    assert caac_june.loc[caac_june["metric"].eq("cargo_ctk"), "value"].iloc[0] == 38.3
    assert caac_june.loc[caac_june["metric"].eq("scheduled_passenger_load_factor"), "value"].iloc[0] == 84.7
    assert caac_june.loc[caac_june["metric"].eq("passenger_rpk_yoy"), "value"].iloc[0] == -3.3
    h1 = result.loc[
        (result["source_organization"].eq("CAAC"))
        & result["period"].eq("2026H1")
        & result["scope"].eq("China")
    ]
    assert h1.loc[h1["metric"].eq("cargo_ctk_yoy"), "value"].iloc[0] == 12.8


def test_sector_external_outlook_keeps_forecast_metric_definitions_separate() -> None:
    result = build_airline_sector_external_outlook()
    global_forecasts = result.loc[(result["scope"] == "Global") & (result["status"] == "forecast")]
    assert set(global_forecasts["metric"]) == {
        "passenger_traffic_growth", "cargo_traffic_growth", "passenger_demand_rpk_growth"
    }
    ap = result.loc[(result["scope"] == "Asia Pacific") & (result["period"] == "2026")]
    assert ap.loc[ap["metric"].eq("passenger_demand_rpk_growth"), "value"].eq(7.3).any()
    assert ap.loc[ap["metric"].eq("capacity_ask_growth"), "value"].eq(7.1).any()


def test_sector_external_outlook_keeps_caac_schedule_separate_from_realized_traffic() -> None:
    result = build_airline_sector_external_outlook()
    schedule = result.loc[result["status"].eq("planned_schedule")]
    actual = result.loc[(result["source_organization"].eq("CAAC")) & result["status"].eq("actual")]
    assert not schedule.empty
    assert not actual.empty
    assert schedule["source_quality"].eq("caac_primary").all()
    assert actual["source_quality"].eq("caac_primary").all()
