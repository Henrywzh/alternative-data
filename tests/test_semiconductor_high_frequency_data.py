from __future__ import annotations

import json
from pathlib import Path

import pytest

from semiconductor_high_frequency_data.models import Snapshot
from semiconductor_high_frequency_data.pipeline import HighFrequencyPipeline
from semiconductor_high_frequency_data.sources.kcs import KoreaCustomsHighFrequencySource
from semiconductor_high_frequency_data.sources.kosis import KosisSemiconductorSource
from semiconductor_high_frequency_data.sources.krx import KrxPositioningSource


FIXTURES = Path(__file__).parent / "fixtures" / "semiconductor_high_frequency"


class FakeResponse:
    def __init__(self, payload: object, text: str = "") -> None:
        self.payload = payload
        self.text = text
        self.status_code = 200

    def json(self) -> object:
        return self.payload

    def raise_for_status(self) -> None:
        return None


class KcsSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: dict[str, str], timeout: int) -> FakeResponse:
        self.calls.append((url, params))
        if "prlstMmUtPrviExpAcrs" in url:
            payload = json.loads((FIXTURES / "kcs_10day.json").read_text(encoding="utf-8"))
        elif params.get("cntyCd") == "TW":
            payload = json.loads((FIXTURES / "kcs_memory_taiwan.json").read_text(encoding="utf-8"))
        else:
            payload = json.loads((FIXTURES / "kcs_memory_world.json").read_text(encoding="utf-8"))
        return FakeResponse(payload)


class KrxSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict[str, str]]] = []

    def post(self, url: str, data: dict[str, str], headers: dict[str, str], timeout: int) -> FakeResponse:
        self.calls.append((url, data))
        filename = "krx_investor_flow.json" if "02303" in data["bld"] else "krx_short_position.json"
        payload = json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
        return FakeResponse(payload)


class KosisSession:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, dict[str, str]]] = []

    def get(self, url: str, params: dict[str, str], timeout: int) -> FakeResponse:
        self.calls.append((url, params))
        payload = json.loads((FIXTURES / "kosis_cycle.json").read_text(encoding="utf-8"))
        return FakeResponse(payload)


def test_kcs_fetch_and_extract_preserves_10day_units_and_memory_weight() -> None:
    session = KcsSession()
    source = KoreaCustomsHighFrequencySource(service_key="test-key", session=session)

    ten_day_snapshots = source.fetch_ten_day_snapshots(["2026-07"])
    ten_day_points = source.extract_ten_day(ten_day_snapshots, run_id="run", scraped_at="2026-07-31T00:00:00Z")
    assert len(ten_day_points) == 2
    semiconductor = next(point for point in ten_day_points if point.metric == "semiconductor_exports")
    assert semiconductor.value == 45678.0
    assert semiconductor.unit == "usd_thousand"
    assert semiconductor.period_start == "2026-07-01"
    assert semiconductor.period_end == "2026-07-10"
    assert semiconductor.release_date == "2026-07-11"
    assert semiconductor.is_preliminary is True

    memory_snapshots = source.fetch_monthly_memory_snapshots(["2026-06"])
    memory_points = source.extract_monthly_memory(memory_snapshots, run_id="run", scraped_at="2026-07-31T00:00:00Z")
    world = next(point for point in memory_points if point.country_scope == "world")
    taiwan = next(point for point in memory_points if point.country_scope == "taiwan")
    assert world.export_value_usd == 500000000.0
    assert world.export_weight_kg == 1000000.0
    assert world.export_value_per_kg_usd == 500.0
    assert taiwan.export_value_per_kg_usd == 600.0
    assert session.calls[0][1]["strtYymm"] == "202607"
    assert session.calls[-1][1]["hsSgn"] == "854232"


def test_kcs_requires_service_key() -> None:
    source = KoreaCustomsHighFrequencySource()
    with pytest.raises(ValueError, match="service key"):
        source.fetch_ten_day_snapshots(["2026-07"])


def test_krx_parser_extracts_foreign_flow_and_tplus2_short_balance() -> None:
    source = KrxPositioningSource()
    investor_snapshot = Snapshot(
        name="krx_investor_flow_000660",
        source_url="https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
        body=(FIXTURES / "krx_investor_flow.json").read_text(encoding="utf-8"),
        metadata={"kind": "investor_flow", "instrument_code": "000660"},
    )
    short_snapshot = Snapshot(
        name="krx_short_position_000660",
        source_url="https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
        body=(FIXTURES / "krx_short_position.json").read_text(encoding="utf-8"),
        metadata={"kind": "short_position", "instrument_code": "000660"},
    )

    points = source.extract([investor_snapshot, short_snapshot], run_id="run", scraped_at="2026-07-31T00:00:00Z")
    net_buy = next(point for point in points if point.measure == "net_buy_shares")
    short_balance = next(point for point in points if point.measure == "net_short_balance_volume")
    short_value = next(point for point in points if point.measure == "short_value")
    assert net_buy.value == 334.0
    assert net_buy.investor_type == "foreigner"
    assert net_buy.unit == "shares"
    assert short_balance.value == 12000.0
    assert short_balance.availability_lag_days == 2
    assert short_value.currency == "KRW"


def test_krx_fetch_uses_issue_blds_and_date_range() -> None:
    session = KrxSession()
    source = KrxPositioningSource(session=session)
    snapshots = source.fetch_snapshots(
        start_date="20260701",
        end_date="20260730",
        instrument_codes=["000660"],
    )
    assert len(snapshots) == 2
    assert session.calls[0][1]["isuCd2"] == "000660"
    assert session.calls[0][1]["strtDd"] == "20260701"
    assert session.calls[1][1]["isuCd"] == "000660"
    assert session.calls[1][1]["bld"].endswith("MDCSTAT30001_OUT")


def test_kosis_parser_filters_semiconductor_production_shipment_inventory() -> None:
    source = KosisSemiconductorSource(api_key="test-key")
    snapshot = Snapshot(
        name="kosis_cycle",
        source_url="https://kosis.kr/openapi/Param/statisticsParameterData.do",
        body=(FIXTURES / "kosis_cycle.json").read_text(encoding="utf-8"),
        metadata={"kind": "kosis_industry_index", "org_id": "101", "table_id": "DT_1F01501"},
    )
    points = source.extract([snapshot], run_id="run", scraped_at="2026-07-31T00:00:00Z")
    assert {point.measure for point in points} == {"production", "shipment", "inventory"}
    assert len([point for point in points if point.seasonal_adjustment == "seasonally_adjusted"]) == 1
    assert next(point for point in points if point.measure == "inventory").value == 95.0


def test_kosis_fetch_builds_parameterized_monthly_request() -> None:
    session = KosisSession()
    source = KosisSemiconductorSource(api_key="test-key", session=session)
    snapshots = source.fetch_snapshots(start_month="2026-01", end_month="2026-06")
    assert len(snapshots) == 1
    params = session.calls[0][1]
    assert params["orgId"] == "101"
    assert params["tblId"] == "DT_1F01501"
    assert params["startPrdDe"] == "202601"
    assert params["endPrdDe"] == "202606"


def test_kcs_pipeline_writes_independent_datasets(tmp_path: Path) -> None:
    source = KoreaCustomsHighFrequencySource(service_key="test-key", session=KcsSession())
    pipeline = HighFrequencyPipeline(tmp_path, kcs_source=source)
    result = pipeline.run_kcs_update(start_month="2026-06", end_month="2026-06")

    assert result.datasets_written["kcs_10day_exports"] == 2
    assert result.datasets_written["kcs_memory_monthly_country"] == 2
    assert (tmp_path / "data" / "normalized" / "semiconductor_high_frequency" / "kcs_10day_exports.parquet").exists()
    assert (tmp_path / "data" / "normalized" / "semiconductor_high_frequency" / "kcs_memory_monthly_country.parquet").exists()
