from __future__ import annotations

from pathlib import Path

from hkma_macro_data.models import HkmaObservation, HkmaSeriesMeta
from hkma_macro_data.storage import HkmaMacroStorage


def _meta(series_id: str, title: str, fetched_at: str) -> HkmaSeriesMeta:
    return HkmaSeriesMeta(
        series_id=series_id,
        title=title,
        category="Liquidity",
        frequency="D",
        units="HKD_Million",
        fetched_at=fetched_at,
    )


def _obs(series_id: str, date: str, value: float, fetched_at: str) -> HkmaObservation:
    return HkmaObservation(
        date=date,
        series_id=series_id,
        value=value,
        fetched_at=fetched_at,
        source_url="https://api.hkma.gov.hk/test",
    )


def test_hkma_upsert_series_meta(tmp_path: Path) -> None:
    storage = HkmaMacroStorage(tmp_path)
    storage.upsert_series_meta([_meta("HKMA_AGGREGATE_BALANCE", "Balance v1", "t1")])
    merged = storage.upsert_series_meta([_meta("HKMA_AGGREGATE_BALANCE", "Balance v2", "t2")])
    assert len(merged) == 1
    assert merged.iloc[0]["title"] == "Balance v2"


def test_hkma_upsert_observations_dedupes(tmp_path: Path) -> None:
    storage = HkmaMacroStorage(tmp_path)
    storage.upsert_observations([
        _obs("HKMA_AGGREGATE_BALANCE", "2026-08-31", 44850.0, "t1"),
        _obs("HKMA_HIBOR_3M", "2026-08-31", 4.15, "t1"),
    ])
    merged = storage.upsert_observations([
        _obs("HKMA_AGGREGATE_BALANCE", "2026-08-31", 45000.0, "t2"),
        _obs("HKMA_HIBOR_3M", "2026-09-01", 4.12, "t2"),
    ])
    assert len(merged) == 3
    bal = merged[merged["series_id"] == "HKMA_AGGREGATE_BALANCE"]
    assert len(bal) == 1
    assert bal.iloc[0]["value"] == 45000.0
