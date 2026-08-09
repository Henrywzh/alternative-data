from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_cargo_bridge_backtest import (
    build_airline_cargo_bridge_backtest,
)


def _official() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "company": "China Southern Airlines",
                "statement_period": period,
                "metric": "cargo_revenue",
                "value_native": value,
            }
            for period, value in (("FY2025", 19_670.0), ("1H2025", 9_080.0))
        ]
    )


def _monthly() -> pd.DataFrame:
    rows = []
    for code in ("600029", "601021"):
        for year, months in ((2024, (1, 6)), (2025, (1, 12)), (2026, (1, 6))):
            for month in range(1, months[1] + 1):
                rows.append(
                    {
                        "month": f"{year}-{month:02d}",
                        "airline_code": code,
                        "region": "Total",
                        "metric": "cargo_tonnes",
                        "value": 1_000.0 + month,
                    }
                )
    return pd.DataFrame(rows)


def _airports() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observation_month": "2026-01",
                "airport": "CAN",
                "metric": "cargo_throughput",
                "scope": "total",
                "value": 10.0,
                "yoy_pct": 3.0,
            },
            {
                "observation_month": "2026-02",
                "airport": "CAN",
                "metric": "cargo_throughput",
                "scope": "total",
                "value": 11.0,
                "yoy_pct": 4.0,
            },
        ]
    )


def test_backtest_holdout_error_and_airport_signal(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "src.hk_transport.sources.airline_cargo_bridge_backtest.OUTPUT_PATH",
        tmp_path / "airline_cargo_bridge_backtest.csv",
    )
    result = build_airline_cargo_bridge_backtest(
        official=_official(),
        monthly=_monthly(),
        airports=_airports(),
        retrieved_at="2026-08-09T00:00:00+00:00",
    )

    southern = result[result["company"].eq("China Southern Airlines")].iloc[0]
    # FY2025 tonnes = 12*(1001+..+1012) ; H1-2025 tonnes = 6-month sum.
    assert southern["fy2025_cargo_tonnes"] == pytest.approx(12_078.0)
    assert southern["fy2025_revenue_per_tonne_native"] == pytest.approx(1_628_580.0)
    assert southern["h1_2025_revenue_error_pct"] == pytest.approx(7.9921315)
    assert southern["airport_cargo_h1_2026_yoy_pct"] == pytest.approx(3.5)
    assert southern["airport_signal_gap_pp"] is not None
    assert southern["backtest_status"] == "available_holdout_and_airport_signal"

    spring = result[result["company"].eq("Spring Airlines")].iloc[0]
    # No 1H2025 official cargo revenue anchor -> holdout leg missing.
    assert pd.isna(spring["actual_h1_2025_cargo_revenue_native_mn"])
