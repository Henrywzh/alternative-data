from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from ofr_macro_data.client import OfrClient
from ofr_macro_data.models import OfrDataPoint, OfrMnemonic
from ofr_macro_data.pipeline import OfrPipeline
from ofr_macro_data.storage import OfrStorage


def _mnemonic(mnemonic: str, name: str, fetched_at: str) -> OfrMnemonic:
    return OfrMnemonic(
        mnemonic=mnemonic,
        name=name,
        notes="",
        frequency="D",
        start_date="2020-01-01",
        last_update="2026-07-18",
        fetched_at=fetched_at,
    )


def _point(mnemonic: str, date: str, value: float, fetched_at: str) -> OfrDataPoint:
    return OfrDataPoint(date=date, mnemonic=mnemonic, value=value, fetched_at=fetched_at)


def test_upsert_mnemonics_keeps_latest_and_dedupes(tmp_path: Path) -> None:
    storage = OfrStorage(tmp_path)

    storage.upsert_mnemonics([_mnemonic("FOO", "Foo v1", "2026-07-17T00:00:00+00:00")])
    merged = storage.upsert_mnemonics([_mnemonic("FOO", "Foo v2", "2026-07-18T00:00:00+00:00")])

    assert len(merged) == 1
    assert merged.iloc[0]["name"] == "Foo v2"


def test_upsert_timeseries_dedupes_by_mnemonic_and_date_and_coerces_numeric(tmp_path: Path) -> None:
    storage = OfrStorage(tmp_path)

    storage.upsert_timeseries([_point("FOO", "2026-07-01", 1.0, "t1")])
    merged = storage.upsert_timeseries(
        [
            _point("FOO", "2026-07-01", 2.0, "t2"),  # same date -> overwrites
            _point("FOO", "2026-07-02", 3.0, "t2"),
        ]
    )

    assert len(merged) == 2
    row = merged[merged["date"] == "2026-07-01"].iloc[0]
    assert row["value"] == 2.0
    assert pd.api.types.is_numeric_dtype(merged["value"])


def test_upsert_timeseries_survives_csv_round_trip_reload(tmp_path: Path) -> None:
    storage = OfrStorage(tmp_path)
    storage.upsert_timeseries([_point("FOO", "2026-07-01", 1.0, "t1")])

    # Simulate a fresh process picking up only the CSV twin (no parquet on disk).
    (storage.normalized_root / "ofr_timeseries.parquet").unlink()
    reloaded = OfrStorage(tmp_path).load_timeseries()

    assert len(reloaded) == 1
    assert list(reloaded.columns) == OfrStorage.TIMESERIES_COLS


class FakeSession:
    def __init__(self, payload) -> None:
        self.payload = payload

    def get(self, url: str, params=None, timeout=None):
        class FakeResponse:
            def __init__(self, payload):
                self.payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self.payload

        return FakeResponse(self.payload)


def test_get_timeseries_skips_malformed_and_null_points() -> None:
    client = OfrClient()
    client.session = FakeSession(
        [
            ["2026-07-01", 1.5],
            ["2026-07-02", None],
            ["2026-07-03"],  # wrong shape
            ["2026-07-04", 2.5],
        ]
    )

    points = client.get_timeseries("FOO")

    assert [p.date for p in points] == ["2026-07-01", "2026-07-04"]


def test_get_timeseries_handles_non_list_payload_without_raising() -> None:
    client = OfrClient()
    client.session = FakeSession({"error": "mnemonic not found"})

    assert client.get_timeseries("BOGUS") == []


class FakeOfrClient:
    def __init__(self, failing_mnemonics: set[str]) -> None:
        self.failing_mnemonics = failing_mnemonics

    def get_mnemonics(self) -> list[str]:
        return ["FOO", "BAR"]

    def get_metadata(self, mnemonic: str) -> OfrMnemonic:
        if mnemonic in self.failing_mnemonics:
            raise RuntimeError(f"boom: {mnemonic}")
        return _mnemonic(mnemonic, f"{mnemonic} name", "2026-07-18T00:00:00+00:00")

    def get_timeseries(self, mnemonic: str) -> list[OfrDataPoint]:
        return [_point(mnemonic, "2026-07-01", 1.0, "2026-07-18T00:00:00+00:00")]


def test_pipeline_run_records_per_mnemonic_errors_and_continues(tmp_path: Path) -> None:
    pipeline = OfrPipeline(tmp_path, client=FakeOfrClient(failing_mnemonics={"BAR"}))

    result = pipeline.run(mnemonics=["FOO", "BAR"])

    assert result["mnemonics_written"] == 1
    assert result["timeseries_written"] == 1
    assert result["errors"] == {"BAR": "boom: BAR"}


def test_pipeline_run_reports_all_errors_when_every_mnemonic_fails(tmp_path: Path) -> None:
    pipeline = OfrPipeline(tmp_path, client=FakeOfrClient(failing_mnemonics={"FOO", "BAR"}))

    result = pipeline.run(mnemonics=["FOO", "BAR"])

    assert result["mnemonics_written"] == 0
    assert result["timeseries_written"] == 0
    assert set(result["errors"]) == {"FOO", "BAR"}
