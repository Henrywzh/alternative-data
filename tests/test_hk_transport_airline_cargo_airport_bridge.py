from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_cargo_airport_bridge import (
    build_airline_cargo_airport_bridge,
)


def _airports() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observation_month": "2026-01",
                "airport": "SHA-PVG",
                "metric": "cargo_throughput",
                "scope": "total",
                "value": 40.0,
                "yoy_pct": 5.0,
                "source_release_date": "2026-02-14",
                "source_quality": "issuer_primary_official_pdf",
            },
            {
                "observation_month": "2026-02",
                "airport": "SHA-PVG",
                "metric": "cargo_throughput",
                "scope": "total",
                "value": 42.0,
                "yoy_pct": 7.0,
                "source_release_date": "2026-03-14",
                "source_quality": "issuer_primary_official_pdf",
            },
            {
                "observation_month": "2026-01",
                "airport": "SZX",
                "metric": "cargo_throughput",
                "scope": "total",
                "value": 10.0,
                "yoy_pct": 2.0,
                "source_release_date": "2026-02-11",
                "source_quality": "issuer_primary_official_pdf",
            },
        ]
    )


def _monthly() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "month": month,
                "airline_code": "601021",
                "region": "Total",
                "metric": "cargo_tonnes",
                "value": value,
            }
            for month, value in (("2026-01", 10_000.0), ("2026-02", 12_000.0))
        ]
        + [
            {
                "month": month,
                "airline_code": "601021",
                "region": "Total",
                "metric": "cargo_tonnes",
                "value": value,
            }
            for month, value in (("2025-01", 9_000.0), ("2025-02", 10_000.0))
        ]
        + [
            {
                "month": month,
                "airline_code": "601021",
                "region": "Domestic",
                "metric": "cargo_tonnes",
                "value": 1_000.0,
            }
            for month in ("2026-01", "2026-02")
        ]
        + [
            {
                "month": month,
                "airline_code": "600029",
                "region": "Total",
                "metric": "cargo_tonnes",
                "value": value,
            }
            for month, value in (("2026-01", 100_000.0), ("2026-02", 110_000.0))
        ]
    )


def _official() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "company": "Spring Airlines",
                "statement_period": "FY2025",
                "metric": "cargo_revenue",
                "value_native": 158.3,
            },
            {
                "company": "China Southern Airlines",
                "statement_period": "FY2025",
                "metric": "cargo_revenue",
                "value_native": 19_670.0,
            },
        ]
    )


def test_bridge_uses_total_rows_only_and_builds_gap_diagnostics(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "src.hk_transport.sources.airline_cargo_airport_bridge.OUTPUT_PATH",
        tmp_path / "airline_cargo_airport_bridge.csv",
    )
    result = build_airline_cargo_airport_bridge(
        airports=_airports(),
        monthly=_monthly(),
        official=_official(),
        retrieved_at="2026-08-09T00:00:00+00:00",
    )

    spring = result[result["company"].eq("Spring Airlines")].iloc[0]
    # Airport cargo 40+42 10k tonnes -> 820k tonnes; company 22k tonnes.
    assert spring["airport_cargo_tonnes"] == pytest.approx(820_000.0)
    assert spring["company_cargo_tonnes"] == pytest.approx(22_000.0)
    assert spring["airport_cargo_yoy_pct"] == pytest.approx(6.0)
    assert spring["company_cargo_tonnes_yoy_pct"] == pytest.approx(15.7894736)
    assert spring["cargo_tonnage_bridge_gap_pp"] == pytest.approx(-9.7894736)
    assert spring["reported_cargo_revenue_per_tonne_native"] == pytest.approx(7.1954545)
    assert spring["bridge_status"] == "available_airport_and_company_tonnage"

    southern = result[result["company"].eq("China Southern Airlines")].iloc[0]
    # SZX only in this fixture; airport cargo 10 10k tonnes = 100k tonnes.
    assert southern["airport_cargo_tonnes"] == pytest.approx(100_000.0)
    assert southern["company_cargo_tonnes"] == pytest.approx(210_000.0)
