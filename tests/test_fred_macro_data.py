from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from fred_macro_data.client import FredMacroClient
from fred_macro_data.config import resolve_api_key
from fred_macro_data.models import FredObservation, FredSeriesMeta
from fred_macro_data.pipeline import FredMacroPipeline
from fred_macro_data.storage import FredMacroStorage


def _meta(series_id: str, title: str, fetched_at: str) -> FredSeriesMeta:
    return FredSeriesMeta(
        series_id=series_id,
        title=title,
        frequency="D",
        units="Percent",
        seasonal_adjustment="NSA",
        observation_start="2020-01-01",
        last_updated="2026-07-18",
        fetched_at=fetched_at,
    )


def _obs(series_id: str, date: str, value: float, fetched_at: str) -> FredObservation:
    return FredObservation(date=date, series_id=series_id, value=value, fetched_at=fetched_at)


def test_upsert_series_meta_keeps_latest_and_dedupes(tmp_path: Path) -> None:
    storage = FredMacroStorage(tmp_path)

    storage.upsert_series_meta([_meta("SOFR", "SOFR v1", "t1")])
    merged = storage.upsert_series_meta([_meta("SOFR", "SOFR v2", "t2")])

    assert len(merged) == 1
    assert merged.iloc[0]["title"] == "SOFR v2"


def test_upsert_observations_dedupes_by_series_and_date(tmp_path: Path) -> None:
    storage = FredMacroStorage(tmp_path)

    storage.upsert_observations([_obs("SOFR", "2026-07-01", 3.5, "t1")])
    merged = storage.upsert_observations(
        [
            _obs("SOFR", "2026-07-01", 3.6, "t2"),
            _obs("SOFR", "2026-07-02", 3.7, "t2"),
        ]
    )

    assert len(merged) == 2
    row = merged[merged["date"] == "2026-07-01"].iloc[0]
    assert row["value"] == 3.6
    assert pd.api.types.is_numeric_dtype(merged["value"])


def test_resolve_api_key_prefers_env_over_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".config").write_text('FRED_API_KEY="from-config"\n', encoding="utf-8")
    monkeypatch.setenv("FRED_API_KEY", "from-env")

    assert resolve_api_key(tmp_path) == "from-env"


def test_resolve_api_key_reads_quoted_config_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    (tmp_path / ".config").write_text('FRED_API_KEY="from-config"\n', encoding="utf-8")

    assert resolve_api_key(tmp_path) == "from-config"


def test_resolve_api_key_raises_when_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)

    with pytest.raises(ValueError):
        resolve_api_key(tmp_path)


class FakeResponse:
    def __init__(self, payload) -> None:
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload) -> None:
        self.payload = payload

    def get(self, url: str, params=None, timeout=None):
        return FakeResponse(self.payload)


def test_get_observations_skips_missing_and_malformed_values() -> None:
    client = FredMacroClient(api_key="key")
    client.session = FakeSession(
        {
            "observations": [
                {"date": "2026-07-01", "value": "3.5"},
                {"date": "2026-07-02", "value": "."},
                {"date": "2026-07-03", "value": None},
                {"date": "2026-07-04", "value": "not-a-number"},
                {"date": "2026-07-05", "value": "3.6"},
            ]
        }
    )

    points = client.get_observations("SOFR")

    assert [p.date for p in points] == ["2026-07-01", "2026-07-05"]


def test_get_series_meta_raises_when_series_not_found() -> None:
    client = FredMacroClient(api_key="key")
    client.session = FakeSession({"seriess": []})

    with pytest.raises(ValueError):
        client.get_series_meta("BOGUS")


class FakeFredClient:
    def __init__(self, failing_series: set[str]) -> None:
        self.failing_series = failing_series

    def get_series_meta(self, series_id: str) -> FredSeriesMeta:
        if series_id in self.failing_series:
            raise RuntimeError(f"boom: {series_id}")
        return _meta(series_id, f"{series_id} title", "t1")

    def get_observations(self, series_id: str) -> list[FredObservation]:
        return [_obs(series_id, "2026-07-01", 1.0, "t1")]


def test_pipeline_run_records_per_series_errors_and_continues(tmp_path: Path) -> None:
    pipeline = FredMacroPipeline(tmp_path, client=FakeFredClient(failing_series={"BAMLC0A0CM"}))

    result = pipeline.run(series_ids=["SOFR", "BAMLC0A0CM"])

    assert result["series_written"] == 1
    assert result["observations_written"] == 1
    assert result["errors"] == {"BAMLC0A0CM": "boom: BAMLC0A0CM"}
