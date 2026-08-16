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


def _obs(
    series_id: str,
    date: str,
    value: float,
    fetched_at: str,
    realtime_start: str | None = None,
    realtime_end: str | None = None,
) -> FredObservation:
    return FredObservation(
        date=date,
        series_id=series_id,
        value=value,
        fetched_at=fetched_at,
        realtime_start=realtime_start,
        realtime_end=realtime_end,
    )


def test_upsert_series_meta_keeps_latest_and_dedupes(tmp_path: Path) -> None:
    storage = FredMacroStorage(tmp_path)

    storage.upsert_series_meta([_meta("SOFR", "SOFR v1", "t1")])
    merged = storage.upsert_series_meta([_meta("SOFR", "SOFR v2", "t2")])

    assert len(merged) == 1
    assert merged.iloc[0]["title"] == "SOFR v2"


def test_upsert_observations_dedupes_by_series_date_realtime_and_value(tmp_path: Path) -> None:
    # The upsert key is (series_id, date, realtime_start, value): the legacy
    # (series_id, date) key collapsed same-day values; the new key preserves
    # distinct values and vintage bounds for the same observation date.
    storage = FredMacroStorage(tmp_path)

    storage.upsert_observations([_obs("SOFR", "2026-07-01", 3.5, "t1")])
    merged = storage.upsert_observations(
        [
            _obs("SOFR", "2026-07-01", 3.6, "t2"),
            _obs("SOFR", "2026-07-02", 3.7, "t2"),
        ]
    )

    # 3.5 and 3.6 are distinct (series, date, realtime_start, value) keys and
    # both survive; 2026-07-02 adds a third row.
    assert len(merged) == 3
    july_first = merged[merged["date"] == "2026-07-01"]
    assert set(july_first["value"]) == {3.5, 3.6}
    assert pd.api.types.is_numeric_dtype(merged["value"])


def test_upsert_observations_preserves_same_vintage_value_change(tmp_path: Path) -> None:
    # A value change within the same vintage (same series/date/realtime_start)
    # must not silently overwrite the previously stored value: it is a new
    # (…, value) key, while re-inserting the identical record dedupes.
    storage = FredMacroStorage(tmp_path)

    storage.upsert_observations(
        [_obs("SOFR", "2026-07-01", 3.5, "t1", realtime_start="2026-07-02", realtime_end="9999-12-31")]
    )
    merged = storage.upsert_observations(
        [_obs("SOFR", "2026-07-01", 3.6, "t2", realtime_start="2026-07-02", realtime_end="9999-12-31")]
    )

    assert len(merged) == 2
    assert set(merged["value"]) == {3.5, 3.6}
    assert merged["realtime_start"].dropna().eq("2026-07-02").all()

    # Identical record re-inserted -> deduped, still two rows.
    merged_again = storage.upsert_observations(
        [_obs("SOFR", "2026-07-01", 3.6, "t3", realtime_start="2026-07-02", realtime_end="9999-12-31")]
    )
    assert len(merged_again) == 2


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


def test_get_observations_does_not_fabricate_vintages_from_request_window() -> None:
    # P2-12: per-observation realtime bounds are authoritative; when the API
    # omits them the vintage is unknown (NULL) rather than the request window.
    client = FredMacroClient(api_key="key")
    client.session = FakeSession(
        {
            "observations": [
                {"date": "2026-07-01", "value": "3.5"},
                {
                    "date": "2026-07-02",
                    "value": "3.6",
                    "realtime_start": "2026-07-03",
                    "realtime_end": "9999-12-31",
                },
            ]
        }
    )

    points = client.get_observations("SOFR", realtime_start="2015-01-01")

    assert points[0].realtime_start is None
    assert points[0].realtime_end is None
    assert points[1].realtime_start == "2026-07-03"
    assert points[1].realtime_end == "9999-12-31"


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
