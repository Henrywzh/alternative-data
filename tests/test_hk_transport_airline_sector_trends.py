from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_sector_trends import build_airline_sector_trends


def test_build_airline_sector_trends_calculates_weighted_load_factor() -> None:
    frame = pd.DataFrame(
        {
            "month": ["2025-01", "2025-02", "2026-01", "2026-02"] * 2,
            "airline_code": ["600029"] * 4 + ["600115"] * 4,
            "region": ["Total"] * 8,
            "metric": ["ask", "rpk", "ask", "rpk"] * 2,
            "value": [100, 80, 120, 108, 50, 40, 60, 48],
        }
    )
    result = build_airline_sector_trends(frame, retrieved_at="2026-08-06")
    sector = result.loc[
        (result["scope_type"].eq("sector")) & result["metric"].eq("passenger_load_factor_pct")
    ].iloc[0]
    assert sector["current_value"] == 86.66666666666667
    assert sector["prior_value"] == 80.0
    assert sector["yoy_change_abs"] == 6.666666666666671
    assert sector["calculation_method"].startswith("rpk/ask")


def test_current_airline_sector_trend_snapshot_has_company_and_sector_rows() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_sector_trend_snapshot.csv")
    assert frame["current_period"].eq("2026H1").all()
    assert frame["prior_period"].eq("2025H1").all()
    assert set(frame["scope_type"]) == {"company", "sector"}
    assert frame["source_quality"].eq("issuer_monthly_operating_release").all()
    assert "quality_flag" in frame.columns
    assert frame["quality_flag"].isin({"ok", "large_yoy_move_review"}).all()
