from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import pytest

from event_consensus.sources.bls import (
    fetch_official_components,
    verify_calendar_actuals,
)
from event_consensus.sources.finnhub import fetch_quotes
from event_consensus.sources.tradingview import fetch_calendar


NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


class Response:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(self.status)

    def json(self) -> dict:
        return self.payload


class GetSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def get(self, *_args, **_kwargs) -> Response:
        return Response(self.payload)


class PostSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def post(self, *_args, **_kwargs) -> Response:
        return Response(self.payload)


class QuoteSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def get(self, *_args, **_kwargs) -> Response:
        return Response(self.payload)


def test_tradingview_calendar_normalizes_and_filters_countries() -> None:
    payload = {
        "result": [
            {
                "id": "abc",
                "country": "US",
                "title": "Core CPI MoM",
                "date": "2026-09-16T12:30:00.000Z",
                "importance": 1,
                "forecastRaw": 0.3,
                "previousRaw": 0.2,
                "actualRaw": None,
                "unit": "%",
                "source": "BLS",
                "source_url": "https://www.bls.gov/",
            },
            {
                "id": "skip",
                "country": "GB",
                "title": "CPI YoY",
                "date": "2026-09-16T06:00:00.000Z",
            },
        ]
    }
    frame, health = fetch_calendar(
        date(2026, 9, 15),
        date(2026, 9, 20),
        countries=("US",),
        trigger_type="manual",
        session=GetSession(payload),
        now_utc=NOW,
    )
    assert len(frame) == 1
    assert frame.iloc[0]["event_id"] == "tradingview:abc"
    assert frame.iloc[0]["event_family"] == "cpi"
    assert frame.iloc[0]["forecast"] == 0.3
    assert frame.iloc[0]["verification_status"] == "third_party_consensus"
    assert len(frame.iloc[0]["payload_checksum"]) == 64
    assert frame.iloc[0]["first_observed_at_utc"] == NOW.isoformat()
    assert health["status"] == "Healthy"


def test_finnhub_quote_has_pit_lineage_fields() -> None:
    frame, health = fetch_quotes(
        ({"symbol": "SPY", "label": "S&P 500", "asset_class": "US equity"},),
        api_key="test",
        trigger_type="manual",
        session=QuoteSession({"c": 500.0, "d": 1.0, "dp": 0.2, "t": 1790000000}),
        now_utc=NOW,
    )
    assert health["status"] == "Healthy"
    assert len(frame.iloc[0]["payload_checksum"]) == 64
    assert len(frame.iloc[0]["snapshot_id"]) == 24
    assert frame.iloc[0]["observation_signature"]


def test_bls_components_and_country_guard() -> None:
    payload = {
        "status": "REQUEST_SUCCEEDED",
        "Results": {
            "series": [
                {
                    "seriesID": "LNS14000000",
                    "data": [
                        {"year": "2026", "period": "M08", "value": "4.1"},
                        {"year": "2026", "period": "M07", "value": "4.0"},
                        {"year": "2025", "period": "M08", "value": "4.2"},
                    ],
                }
            ]
        },
    }
    specs = (
        {
            "series_id": "LNS14000000",
            "event_family": "payrolls",
            "component_id": "unemployment",
            "label_en": "Unemployment rate",
            "label_zh": "失业率",
            "value_kind": "rate",
        },
    )
    components, health = fetch_official_components(
        trigger_type="manual",
        session=PostSession(payload),
        now_utc=NOW,
        series_specs=specs,
    )
    assert health["status"] == "Healthy"
    assert components.iloc[0]["latest_value"] == 4.1
    assert components.iloc[0]["mom_change_pp"] == pytest.approx(0.1)
    assert pd.isna(components.iloc[0]["mom_pct"])

    events = pd.DataFrame(
        [
            {
                "country": "US",
                "title": "Unemployment Rate",
                "event_family": "labour",
                "reference_period": "Aug",
                "scheduled_at_utc": "2026-09-04T12:30:00Z",
                "actual": 4.1,
                "verification_status": "third_party_actual_unverified",
            },
            {
                "country": "CN",
                "title": "Unemployment Rate",
                "event_family": "labour",
                "actual": 5.3,
                "verification_status": "third_party_actual_unverified",
            },
        ]
    )
    verified = verify_calendar_actuals(events, components)
    assert verified.iloc[0]["verification_status"] == "official_verified"
    assert verified.iloc[1]["verification_status"] == "third_party_actual_unverified"
    assert pd.isna(verified.iloc[1]["official_value"])


def test_future_release_does_not_copy_latest_official_component_into_event() -> None:
    components = pd.DataFrame(
        [
            {
                "event_family": "cpi",
                "component_id": "core",
                "series_id": "CUSR0000SA0L1E",
                "reference_period": "2026-08",
                "mom_pct": 0.25,
            }
        ]
    )
    events = pd.DataFrame(
        [
            {
                "country": "US",
                "title": "Core CPI MoM",
                "event_family": "cpi",
                "actual": None,
                "verification_status": "third_party_consensus",
            }
        ]
    )
    verified = verify_calendar_actuals(events, components)
    assert verified.iloc[0]["verification_status"] == "third_party_consensus"
    assert pd.isna(verified.iloc[0]["official_value"])
    assert pd.isna(verified.iloc[0]["official_series_id"])


def test_official_cross_check_requires_matching_reference_month() -> None:
    components = pd.DataFrame(
        [
            {
                "event_family": "cpi",
                "component_id": "core",
                "series_id": "CUSR0000SA0L1E",
                "reference_period": "2026-08",
                "mom_pct": 0.25,
            }
        ]
    )
    events = pd.DataFrame(
        [
            {
                "country": "US",
                "title": "Core CPI MoM",
                "event_family": "cpi",
                "reference_period": "Jul",
                "scheduled_at_utc": "2026-09-11T12:30:00Z",
                "actual": 0.25,
                "verification_status": "third_party_actual_unverified",
            }
        ]
    )
    verified = verify_calendar_actuals(events, components)
    assert verified.iloc[0]["verification_status"] == "third_party_actual_unverified"
    assert pd.isna(verified.iloc[0]["official_value"])


def test_ppi_cross_check_uses_final_demand_component() -> None:
    components = pd.DataFrame(
        [
            {
                "event_family": "ppi",
                "component_id": "core",
                "series_id": "WPSFD4111",
                "reference_period": "2026-08",
                "mom_pct": 0.20,
            }
        ]
    )
    events = pd.DataFrame(
        [
            {
                "country": "US",
                "title": "Core PPI MoM",
                "event_family": "ppi",
                "reference_period": "Aug",
                "scheduled_at_utc": "2026-09-10T12:30:00Z",
                "actual": 0.20,
                "verification_status": "third_party_actual_unverified",
            }
        ]
    )
    verified = verify_calendar_actuals(events, components)
    assert verified.iloc[0]["verification_status"] == "official_verified"
    assert verified.iloc[0]["official_series_id"] == "WPSFD4111"
