from __future__ import annotations

from pathlib import Path

from bis_macro_data.client import BisMacroClient
from bis_macro_data.models import BisObservation, BisSeriesMeta
from bis_macro_data.storage import BisMacroStorage


def _meta(series_id: str, country: str, fetched_at: str) -> BisSeriesMeta:
    return BisSeriesMeta(
        series_id=series_id,
        country=country,
        indicator="Credit Gap",
        title=f"BIS Credit Gap {country}",
        frequency="Q",
        units="Percent",
        fetched_at=fetched_at,
    )


def _obs(period: str, series_id: str, country: str, value: float, fetched_at: str) -> BisObservation:
    return BisObservation(
        period=period,
        series_id=series_id,
        country=country,
        value=value,
        release_date="2026-06-30",
        fetched_at=fetched_at,
    )


def test_bis_upsert_series_meta(tmp_path: Path) -> None:
    storage = BisMacroStorage(tmp_path)
    storage.upsert_series_meta([_meta("BIS_CREDIT_GAP_US", "US", "t1")])
    merged = storage.upsert_series_meta([_meta("BIS_CREDIT_GAP_US", "US", "t2")])
    assert len(merged) == 1
    assert merged.iloc[0]["fetched_at"] == "t2"


def test_bis_upsert_observations_dedupes(tmp_path: Path) -> None:
    storage = BisMacroStorage(tmp_path)
    storage.upsert_observations([
        _obs("2026-Q1", "BIS_CREDIT_GAP_US", "US", -2.5, "t1"),
        _obs("2026-Q1", "BIS_CREDIT_GAP_CN", "CN", 5.2, "t1"),
    ])
    merged = storage.upsert_observations([
        _obs("2026-Q1", "BIS_CREDIT_GAP_US", "US", -2.1, "t2"),
        _obs("2026-Q2", "BIS_CREDIT_GAP_US", "US", -1.8, "t2"),
    ])
    assert len(merged) == 3
    us_q1 = merged[(merged["series_id"] == "BIS_CREDIT_GAP_US") & (merged["period"] == "2026-Q1")]
    assert len(us_q1) == 1
    assert us_q1.iloc[0]["value"] == -2.1


def test_bis_quarterly_lag_derivation() -> None:
    assert BisMacroClient._derive_quarterly_release_date("2026-Q1") == "2026-06-30"
    assert BisMacroClient._derive_quarterly_release_date("2026-Q4") == "2027-03-31"
