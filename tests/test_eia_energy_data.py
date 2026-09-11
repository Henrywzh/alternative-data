from __future__ import annotations

from pathlib import Path

from eia_energy_data.models import EiaGridHourlyObservation
from eia_energy_data.config import DEFAULT_RESPONDENTS
from eia_energy_data.storage import EiaEnergyStorage


def _grid_obs(ts: str, resp: str, fuel: str, gen: float, fetched_at: str) -> EiaGridHourlyObservation:
    return EiaGridHourlyObservation(
        timestamp_utc=ts,
        respondent=resp,
        fuel_type=fuel,
        generation_mwh=gen,
        fetched_at=fetched_at,
    )


def test_eia_upsert_grid_hourly_dedupes(tmp_path: Path) -> None:
    storage = EiaEnergyStorage(tmp_path)
    storage.upsert_grid_hourly([
        _grid_obs("2026-09-01T12:00:00Z", "ERCOT", "NG", 28500.0, "t1"),
        _grid_obs("2026-09-01T12:00:00Z", "ERCOT", "WND", 12400.0, "t1"),
    ])
    merged = storage.upsert_grid_hourly([
        _grid_obs("2026-09-01T12:00:00Z", "ERCOT", "NG", 28600.0, "t2"),
        _grid_obs("2026-09-01T13:00:00Z", "ERCOT", "NG", 29100.0, "t2"),
    ])
    assert len(merged) == 3
    ercot_ng = merged[
        (merged["respondent"] == "ERCOT")
        & (merged["timestamp_utc"] == "2026-09-01T12:00:00Z")
        & (merged["fuel_type"] == "NG")
    ]
    assert len(ercot_ng) == 1
    assert ercot_ng.iloc[0]["generation_mwh"] == 28600.0


def test_eia_uses_official_ercot_respondent_code() -> None:
    assert "ERCO" in DEFAULT_RESPONDENTS
    assert "ERCOT" not in DEFAULT_RESPONDENTS
