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
    # Juneyao's fleet delivery must carry the low-pace confidence label given
    # its observed ~0 trailing net add.
    juneyao_fleet = df[
        df["company"].eq("Juneyao Airlines")
        & df["event_category"].eq("fleet_delivery")
    ]
    assert (juneyao_fleet["confidence"] == "low_no_recent_delivery_pace").all()
