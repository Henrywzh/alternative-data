from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_capacity_pipeline import (
    _fleet_delivery_events,
    _route_launch_events,
    _trailing_net_fleet_add,
)


def test_trailing_net_fleet_add_calculates_added_minus_retired() -> None:
    events = pd.DataFrame(
        [
            {"airline_code": "601021", "month": "2026-01-01",
             "event_type": "fleet_added_aircraft", "value": 3},
            {"airline_code": "601021", "month": "2026-03-01",
             "event_type": "fleet_added_aircraft", "value": 2},
            {"airline_code": "601021", "month": "2026-02-01",
             "event_type": "fleet_retired_aircraft", "value": 1},
            {"airline_code": "601021", "month": "2020-01-01",  # outside window
             "event_type": "fleet_added_aircraft", "value": 10},
        ]
    )
    assert _trailing_net_fleet_add(events, "601021") == 4.0


def test_fleet_delivery_events_use_pace_anchor_and_cap_at_book() -> None:
    snapshot = pd.DataFrame(
        [
            {"company": "Spring Airlines", "aircraft_type": "A320neo", "on_order": 42.0},
        ]
    )
    events = pd.DataFrame(
        [
            {"airline_code": "601021", "month": "2026-01-01",
             "event_type": "fleet_added_aircraft", "value": 2},
            {"airline_code": "601021", "month": "2026-02-01",
             "event_type": "fleet_added_aircraft", "value": 2},
        ]
    )
    rows = _fleet_delivery_events(snapshot, events)
    assert len(rows) == 3  # 6m/12m/24m
    for row in rows:
        assert row["company"] == "Spring Airlines"
        assert row["event_category"] == "fleet_delivery"
    # 12m horizon: pace 4 => ~4 aircraft
    twelve = next(r for r in rows if r["horizon"] == "12m")
    assert "~4" in twelve["event_detail"]
    assert twelve["confidence"] == "medium"


def test_route_launch_events_count_frequency() -> None:
    licences = pd.DataFrame(
        [
            {"airline_normalized_name": "Spring Airlines",
             "table_type": "new_domestic_route", "route_text": "a",
             "initial_frequency_per_week": 14.0, "planned_start_date": "2026-03-29"},
            {"airline_normalized_name": "Spring Airlines",
             "table_type": "new_domestic_route", "route_text": "b",
             "initial_frequency_per_week": 14.0, "planned_start_date": "2026-03-29"},
            {"airline_normalized_name": "Spring Airlines",
             "table_type": "cancelled_route_licence", "route_text": "c",
             "initial_frequency_per_week": 7.0, "planned_start_date": None},
        ]
    )
    rows = _route_launch_events(licences)
    assert len(rows) == 1
    assert "2 new domestic routes" in rows[0]["event_detail"]
    assert "~28 weekly" in rows[0]["event_detail"]
    assert rows[0]["confidence"] == "high_licence_issued"


def test_build_capacity_pipeline_covers_all_carriers() -> None:
    from src.hk_transport.sources.airline_capacity_pipeline import (
        build_airline_capacity_pipeline,
    )

    df = build_airline_capacity_pipeline()
    assert not df.empty
    assert df["company"].nunique() >= 6
    assert set(df["event_category"]) >= {
        "fleet_delivery",
        "route_launch",
        "ask_decomposition",
    }
    # Every fleet-delivery row carries one of the three declared labels.  Which
    # label a given carrier lands on is a property of this month's traffic
    # prints, not of the pipeline: pinning "Juneyao is low-pace" here made the
    # suite fail the day Juneyao took delivery of a single aircraft.  The
    # labelling rule itself is guarded on fixtures in
    # test_one_airframe_in_a_year_is_not_a_delivery_pace.
    fleet = df[df["event_category"].eq("fleet_delivery")]
    assert not fleet.empty
    assert set(fleet["confidence"]) <= {
        "high",
        "medium",
        "low_no_recent_delivery_pace",
    }


def test_ask_growth_reads_the_year_not_whichever_month_landed_last() -> None:
    """The field says trailing-12m, so a soft final month must not define it."""
    from src.hk_transport.sources.airline_capacity_pipeline import _ask_decomposition

    months = pd.date_range("2024-08-01", periods=24, freq="MS")
    # Flat prior year, a clearly stronger recent year, and one soft final print.
    # Comparing the last month against the same month a year earlier reads 0%;
    # comparing the two twelve-month windows reads +9.2%.
    values = [100.0] * 12 + [110.0] * 11 + [100.0]
    monthly = pd.DataFrame(
        {
            "month": months.strftime("%Y-%m-%d"),
            "region": "Total",
            "metric": "ask",
            "airline_code": "601021",
            "value": values,
        }
    )

    rows = _ask_decomposition(monthly, pd.DataFrame(), pd.DataFrame())

    assert len(rows) == 1
    assert "+9.2%" in rows[0]["event_detail"]


def test_a_carrier_without_two_clean_years_is_dropped_not_compared() -> None:
    """A short series has no prior window to compare against."""
    from src.hk_transport.sources.airline_capacity_pipeline import _ask_decomposition

    months = pd.date_range("2025-08-01", periods=23, freq="MS")
    monthly = pd.DataFrame(
        {
            "month": months.strftime("%Y-%m-%d"),
            "region": "Total",
            "metric": "ask",
            "airline_code": "601021",
            "value": [100.0] * 23,
        }
    )

    assert _ask_decomposition(monthly, pd.DataFrame(), pd.DataFrame()) == []


def test_one_airframe_in_a_year_is_not_a_delivery_pace() -> None:
    """A single net add is one observation, not evidence of a cadence."""
    snapshot = pd.DataFrame(
        [{"company": "Juneyao Airlines", "aircraft_type": "A320neo", "on_order": 25.0}]
    )
    # Anchored to today so the trailing window keeps covering these rows: the
    # bug this guards against was found by a fixture ageing out of its window.
    recent = pd.Timestamp.now().normalize() - pd.DateOffset(months=2)
    older = pd.Timestamp.now().normalize() - pd.DateOffset(months=8)
    events = pd.DataFrame(
        [
            {"airline_code": "603885", "month": recent.strftime("%Y-%m-01"),
             "event_type": "fleet_added_aircraft", "value": 2},
            {"airline_code": "603885", "month": older.strftime("%Y-%m-01"),
             "event_type": "fleet_retired_aircraft", "value": 1},
        ]
    )

    rows = _fleet_delivery_events(snapshot, events)

    assert rows
    assert {row["confidence"] for row in rows} == {"low_no_recent_delivery_pace"}
