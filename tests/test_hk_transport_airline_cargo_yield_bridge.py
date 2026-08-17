from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_cargo_yield_bridge import (
    build_airline_cargo_yield_bridge,
)


def _monthly() -> pd.DataFrame:
    rows = []
    for code in ("600029", "601021"):
        for year in (2025, 2026):
            for month in (1, 2):
                rows.append(
                    {
                        "month": f"{year}-{month:02d}",
                        "airline_code": code,
                        "region": "Total",
                        "metric": "cargo_tonnes",
                        "value": 1000.0 + (month * 10.0),
                    }
                )
    return pd.DataFrame(rows)


def _official() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "company": "China Southern Airlines",
                "statement_period": "1H2025",
                "metric": "cargo_revenue",
                "value_native": 9080.0,
            },
            {
                "company": "Spring Airlines",
                "statement_period": "FY2025",
                "metric": "cargo_revenue",
                "value_native": 158.3,
            },
        ]
    )


def test_bridge_uses_h1_revenue_anchor_and_tonnage_growth(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "src.hk_transport.sources.airline_cargo_yield_bridge.OUTPUT_PATH",
        tmp_path / "airline_cargo_yield_bridge.csv",
    )
    result = build_airline_cargo_yield_bridge(
        official=_official(),
        monthly=_monthly(),
        retrieved_at="2026-08-09T00:00:00+00:00",
    )

    southern = result[result["company"].eq("China Southern Airlines")].iloc[0]
    # H1-2025 tonnes = 1,010 + 1,020 = 2,030; revenue 9,080m -> 4.473m RMB/tonne.
    assert southern["revenue_anchor_period"] == "1H2025"
    assert southern["h1_2025_cargo_tonnes"] == pytest.approx(2_030.0)
    assert southern["revenue_per_tonne_native"] == pytest.approx(4_472_906.4)
    assert southern["h1_2026_cargo_tonnes"] == pytest.approx(2_030.0)
    assert southern["h1_2026_cargo_revenue_bridge_native_mn"] == pytest.approx(9_080.0)
    assert southern["bridge_status"] == "available_bridge"

    spring = result[result["company"].eq("Spring Airlines")].iloc[0]
    assert spring["revenue_anchor_period"] == "FY2025"
    assert spring["revenue_anchor_type"] == "official_fy2025_cargo_revenue_annualized_anchor"
    assert spring["revenue_per_tonne_native"] == pytest.approx(77_980.2956)
    assert spring["h1_2026_cargo_tonnes_yoy_pct"] == pytest.approx(0.0)
