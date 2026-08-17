from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from us_census_trade_data.config import MissingCredentialError, SourceResponseError
from us_census_trade_data.models import Snapshot
from us_census_trade_data.pipeline import CensusTradePipeline
from us_census_trade_data.sources.census import (
    CensusInternationalTradeSource,
    CensusPortInternationalTradeSource,
)
from us_census_trade_data.storage import DATASET_ID, PORT_DATASET_ID, StorageManager


FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_body() -> str:
    return (FIXTURES / "us_census_memory_imports.json").read_text(encoding="utf-8")


def _port_fixture_body() -> str:
    return (FIXTURES / "us_census_port_memory_imports.json").read_text(encoding="utf-8")


def test_source_extracts_monthly_value_and_quantity() -> None:
    source = CensusInternationalTradeSource(api_key="test-key")
    points = source.extract(
        [
            Snapshot(
                name="fixture",
                source_url="fixture://census",
                body=_fixture_body(),
                metadata={"partner_country_code": "5800", "hs_code": "854232"},
            )
        ],
        run_id="run-1",
        scraped_at="2026-07-31T00:00:00Z",
    )

    assert [point.period for point in points] == ["2026-05", "2026-06"]
    assert points[0].partner_country_name == "SOUTH KOREA"
    assert points[0].general_import_value_usd == 125000000.0
    assert points[0].general_import_quantity == 250000.0
    assert points[0].general_import_quantity_unit == "KG"
    assert points[0].air_import_value_usd == 120000000.0
    assert points[0].air_shipping_weight == 10000.0
    assert points[0].containerized_vessel_import_value_usd == 5000000.0
    assert points[0].containerized_vessel_shipping_weight == 500.0
    assert points[0].vessel_import_value_usd == 1000000.0
    assert points[0].vessel_shipping_weight == 100.0
    assert points[0].general_value_per_quantity_unit_usd == 500.0
    assert points[0].consumption_import_value_usd == 124500000.0


def test_source_marks_census_sentinel_quantity_as_unavailable() -> None:
    body = _fixture_body().replace('"250000",\n    "KG"', '"0",\n    "-"')
    source = CensusInternationalTradeSource(api_key="test-key")

    points = source.extract(
        [Snapshot("fixture", "fixture://census", body, {"partner_country_code": "5800", "hs_code": "854232"})],
        run_id="run-1",
        scraped_at="2026-07-31T00:00:00Z",
    )

    assert points[0].general_import_quantity is None
    assert points[0].general_import_quantity_unit is None
    assert points[0].general_value_per_quantity_unit_usd is None


def test_source_normalizes_census_last_update_sentinels() -> None:
    source = CensusInternationalTradeSource(api_key="test-key")
    body = _fixture_body().replace('"2026-07-07"', '"0"').replace('"2026-07-31"', '"127"')
    points = source.extract(
        [Snapshot("fixture", "fixture://census", body, {"partner_country_code": "5800", "hs_code": "854232"})],
        run_id="run-1",
        scraped_at="2026-07-31T00:00:00Z",
    )
    assert all(point.last_update is None for point in points)


class _FakeResponse:
    status_code = 200

    def __init__(self, body: str) -> None:
        self.text = body

    def raise_for_status(self) -> None:
        return None


class _RecordingSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[dict] = []

    def get(self, url: str, params: dict, timeout: int) -> _FakeResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return _FakeResponse(_fixture_body())


def test_fetch_uses_time_range_and_does_not_store_key_in_source_url() -> None:
    session = _RecordingSession()
    source = CensusInternationalTradeSource(api_key="secret-key", session=session)

    snapshots = source.fetch_snapshots(
        ["2026-05", "2026-06"],
        partner_country_code="5800",
        hs_code="854232",
    )

    assert len(snapshots) == 1
    assert session.calls[0]["url"].endswith("/imports/hs")
    assert session.calls[0]["params"]["time"] == "from 2026-05 to 2026-06"
    assert session.calls[0]["params"]["CTY_CODE"] == "5800"
    assert session.calls[0]["params"]["I_COMMODITY"] == "854232"
    assert session.calls[0]["params"]["key"] == "secret-key"
    assert "secret-key" not in snapshots[0].source_url


def test_fetch_supports_multiple_partner_country_codes() -> None:
    session = _RecordingSession()
    source = CensusInternationalTradeSource(api_key="secret-key", session=session)

    snapshots = source.fetch_snapshots(
        ["2026-06"],
        partner_country_codes=["5800", "5830", "5880", "5700"],
        hs_code="854232",
    )

    assert len(snapshots) == 4
    assert [call["params"]["CTY_CODE"] for call in session.calls] == ["5800", "5830", "5880", "5700"]
    assert all("secret-key" not in snapshot.source_url for snapshot in snapshots)


def test_source_requires_api_key_before_network_call() -> None:
    source = CensusInternationalTradeSource()
    with pytest.raises(MissingCredentialError):
        source.fetch_snapshots(["2026-06"])


class _FixtureSource(CensusInternationalTradeSource):
    def __init__(self) -> None:
        super().__init__(api_key="fixture-key")

    def fetch_snapshots(self, months: list[str], **kwargs) -> list[Snapshot]:
        return [
            Snapshot(
                name="fixture",
                source_url="fixture://census",
                body=_fixture_body(),
                metadata={"partner_country_code": "5800", "hs_code": "854232"},
            )
        ]


class _EmptySource(CensusInternationalTradeSource):
    def __init__(self) -> None:
        super().__init__(api_key="fixture-key")

    def fetch_snapshots(self, months: list[str], **kwargs) -> list[Snapshot]:
        return [
            Snapshot(
                name="empty",
                source_url="fixture://empty",
                body="[]",
                metadata={"partner_country_code": "5800", "hs_code": "854232"},
            )
        ]


def test_pipeline_writes_normalized_parquet(tmp_path: Path) -> None:
    pipeline = CensusTradePipeline(tmp_path, source=_FixtureSource())
    result = pipeline.run_update_latest(
        revenue_month="2026-06",
        partner_country_code="5800",
        hs_code="854232",
    )

    assert result.datasets_written[DATASET_ID] == 2
    output = tmp_path / "data" / "normalized" / "us_census_trade" / f"{DATASET_ID}.parquet"
    assert output.exists()
    dataframe = pd.read_parquet(output)
    assert set(dataframe["period"]) == {"2026-05", "2026-06"}
    assert dataframe.iloc[-1]["general_import_value_usd"] == 130000000.0


def test_storage_upsert_deduplicates_natural_key(tmp_path: Path) -> None:
    storage = StorageManager(tmp_path)
    source = CensusInternationalTradeSource(api_key="test-key")
    points = source.extract(
        [Snapshot("fixture", "fixture://census", _fixture_body(), {"partner_country_code": "5800", "hs_code": "854232"})],
        run_id="run-1",
        scraped_at="2026-07-31T00:00:00Z",
    )
    storage.upsert_dataset(points)
    written = storage.upsert_dataset(points)

    assert len(written) == 2
    assert len(pd.read_parquet(tmp_path / "data" / "normalized" / "us_census_trade" / f"{DATASET_ID}.parquet")) == 2


def test_port_source_extracts_port_and_shipping_metrics() -> None:
    source = CensusPortInternationalTradeSource(api_key="test-key")

    points = source.extract_port_snapshots(
        [
            Snapshot(
                name="port-fixture",
                source_url="fixture://census-port",
                body=_port_fixture_body(),
                metadata={"partner_country_code": "5800", "hs_code": "854232"},
            )
        ],
        run_id="run-1",
        scraped_at="2026-07-31T00:00:00Z",
    )

    assert len(points) == 2
    assert points[0].port_code == "2704"
    assert points[0].port_name == "LOS ANGELES, CA"
    assert points[0].general_import_value_usd == 200000000.0
    assert points[0].air_shipping_weight == 18000.0
    assert points[1].port_code == "2801"


class _RecordingPortSession(_RecordingSession):
    def get(self, url: str, params: dict, timeout: int) -> _FakeResponse:
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return _FakeResponse(_port_fixture_body())


def test_port_fetch_uses_port_endpoint_and_redacts_key() -> None:
    session = _RecordingPortSession()
    source = CensusPortInternationalTradeSource(api_key="secret-key", session=session)

    snapshots = source.fetch_port_snapshots(
        ["2026-06"],
        partner_country_codes=["5800", "5830"],
        hs_code="854232",
    )

    assert len(snapshots) == 2
    assert all(call["url"].endswith("/imports/porths") for call in session.calls)
    assert all("secret-key" not in snapshot.source_url for snapshot in snapshots)


class _FixturePortSource(CensusPortInternationalTradeSource):
    def __init__(self) -> None:
        super().__init__(api_key="fixture-key")

    def fetch_port_snapshots(self, months: list[str], **kwargs) -> list[Snapshot]:
        return [
            Snapshot(
                name="port-fixture",
                source_url="fixture://census-port",
                body=_port_fixture_body(),
                metadata={"partner_country_code": "5800", "hs_code": "854232"},
            )
        ]


def test_pipeline_writes_port_dataset(tmp_path: Path) -> None:
    pipeline = CensusTradePipeline(tmp_path, port_source=_FixturePortSource())

    result = pipeline.run_port_update_latest(
        revenue_month="2026-06",
        partner_country_code="5800",
        hs_code="854232",
    )

    assert result.datasets_written[PORT_DATASET_ID] == 2
    output = tmp_path / "data" / "normalized" / "us_census_trade" / f"{PORT_DATASET_ID}.parquet"
    assert output.exists()
    dataframe = pd.read_parquet(output)
    assert set(dataframe["port_code"]) == {"2704", "2801"}
    assert dataframe["period"].tolist() == ["2026-06", "2026-06"]


def test_pipeline_fails_when_requested_month_is_missing(tmp_path: Path) -> None:
    pipeline = CensusTradePipeline(tmp_path, source=_EmptySource())

    with pytest.raises(SourceResponseError, match="2026-06/5800"):
        pipeline.run_update_latest(revenue_month="2026-06", partner_country_code="5800")

    manifests = list((tmp_path / "data" / "raw" / "us_census_trade").glob("*/manifest.json"))
    assert len(manifests) == 1
    assert "2026-06/5800" in json.loads(manifests[0].read_text())["missing_month_partner_pairs"]
