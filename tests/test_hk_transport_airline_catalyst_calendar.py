from __future__ import annotations

import pandas as pd

from src.hk_transport.sources.airline_catalyst_calendar import (
    build_airline_catalyst_calendar,
)


def test_calendar_covers_all_event_categories() -> None:
    df = build_airline_catalyst_calendar()
    assert not df.empty
    assert set(df["event_category"]) >= {
        "earnings_report",
        "holiday_demand",
        "fleet_delivery",
        "route_launch",
        "monthly_kpi",
        "fuel",
        "seasonal_schedule",
    }


def test_earnings_catalyst_is_august_2026() -> None:
    df = build_airline_catalyst_calendar()
    earnings = df[df["event_category"].eq("earnings_report")]
    assert len(earnings) >= 5
    assert earnings["event_window_start"].str.startswith("2026-08").all()
    # Spring and Juneyao are both in the calendar.
    names = earnings["event_name"].str.cat(sep=" ")
    assert "Spring Airlines" in names
    assert "Juneyao Airlines" in names


def test_every_row_has_kpi_and_earnings_link() -> None:
    df = build_airline_catalyst_calendar()
    assert df["kpi_link"].notna().all()
    assert df["earnings_link"].notna().all()
    assert df["direction_hypothesis"].notna().all()
