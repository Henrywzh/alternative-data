"""Treasury curve snapshot and basis-point change tests."""

from __future__ import annotations

import pandas as pd

from global_market_regime.treasury import (
    build_treasury_curve_snapshots,
    build_treasury_yield_changes,
)


def _curve_frame() -> pd.DataFrame:
    # Latest session 2026-09-09, prior session 2026-09-08, week-ago 2026-09-02,
    # month-ago 2026-08-07, year-start 2026-01-02. Values follow the Shepherd
    # screenshot closely enough to lock the derived arithmetic.
    rows = [
        ("2026-01-02", "us3m", 3.65),
        ("2026-01-02", "us2y", 3.47),
        ("2026-01-02", "us10y", 4.19),
        ("2026-08-07", "us3m", 3.87),
        ("2026-08-07", "us2y", 4.19),
        ("2026-08-07", "us10y", 4.65),
        ("2026-09-02", "us3m", 3.92),
        ("2026-09-02", "us2y", 4.39),
        ("2026-09-02", "us10y", 4.79),
        ("2026-09-08", "us3m", 3.94),
        ("2026-09-08", "us2y", 4.39),
        ("2026-09-08", "us10y", 4.80),
        ("2026-09-09", "us3m", 3.95),
        ("2026-09-09", "us2y", 4.43),
        ("2026-09-09", "us10y", 4.83),
        ("2026-09-09", "us1m", 3.80),
        ("2026-09-09", "us30y", 5.28),
    ]
    return pd.DataFrame(
        [
            {"date": date, "indicator_id": indicator_id, "value": value, "unit": "percent"}
            for date, indicator_id, value in rows
        ]
    )


def test_curve_snapshots_use_published_sessions_not_interpolated_tenors() -> None:
    snapshots = build_treasury_curve_snapshots(_curve_frame())
    latest = snapshots[snapshots["snapshot_id"].eq("latest")]
    assert latest["as_of"].iloc[0] == "2026-09-09"
    tenors = latest.set_index("indicator_id")["yield_pct"]
    assert float(tenors["us10y"]) == 4.83
    assert pd.isna(tenors["us5y"])

    week = snapshots[snapshots["snapshot_id"].eq("week_ago")]
    assert week["as_of"].iloc[0] == "2026-09-02"
    month = snapshots[snapshots["snapshot_id"].eq("month_ago")]
    assert month["as_of"].iloc[0] == "2026-08-07"
    year_start = snapshots[snapshots["snapshot_id"].eq("year_start")]
    assert year_start["as_of"].iloc[0] == "2026-01-02"


def test_yield_table_uses_basis_points_and_keeps_threshold_distance() -> None:
    table = build_treasury_yield_changes(_curve_frame()).set_index("indicator_id")
    ten_year = table.loc["us10y"]
    assert ten_year["yield_pct"] == 4.83
    assert ten_year["change_1d_bp"] == 3.0
    assert ten_year["change_1w_bp"] == 4.0
    assert ten_year["change_1m_bp"] == 18.0
    assert ten_year["change_ytd_bp"] == 64.0
    assert ten_year["us10y_vs_threshold_bp"] == 1.0

    spread = table.loc["us10y_us2y"]
    assert spread["row_kind"] == "spread"
    assert spread["yield_pct"] == 40.0
    assert spread["change_1d_bp"] == -1.0
    assert spread["change_ytd_bp"] == -32.0


def test_empty_fred_panel_does_not_invent_a_curve() -> None:
    assert build_treasury_curve_snapshots(pd.DataFrame()).empty
    assert build_treasury_yield_changes(pd.DataFrame()).empty
