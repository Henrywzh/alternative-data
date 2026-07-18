from __future__ import annotations

import json

import pytest
import requests

from semiconductor_proxy_data.models import Snapshot
from semiconductor_proxy_data.sources.eurostat import EurostatSource, _chunk_months


def _make_body(partners: dict[str, int], time_periods: dict[str, int], values: dict[str, float]) -> str:
    indicators = {"VALUE_IN_EUROS": 0, "QUANTITY_IN_100KG": 1, "SUPPLEMENTARY_QUANTITY": 2}
    body = {
        "version": "2.0",
        "class": "dataset",
        "value": values,
        "id": ["freq", "reporter", "partner", "product", "flow", "indicators", "time"],
        "size": [1, 1, len(partners), 1, 1, len(indicators), len(time_periods)],
        "dimension": {
            "freq": {"category": {"index": {"M": 0}}},
            "reporter": {"category": {"index": {"NL": 0}}},
            "partner": {"category": {"index": partners}},
            "product": {"category": {"index": {"84862000": 0}}},
            "flow": {"category": {"index": {"2": 0}}},
            "indicators": {"category": {"index": indicators}},
            "time": {"category": {"index": time_periods}},
        },
    }
    return json.dumps(body)


def test_eurostat_source_extraction_all_five_partners() -> None:
    source = EurostatSource()
    partners = {"CN": 0, "KR": 1, "TW": 2, "US": 3, "WORLD": 4}
    time_periods = {"2025-01": 0, "2025-02": 1}
    n_ind, n_time = 3, 2
    values = {}
    for p_code, p_idx in partners.items():
        for t_idx in range(n_time):
            flat_idx = p_idx * n_ind * n_time + 0 * n_time + t_idx
            values[str(flat_idx)] = (p_idx + 1) * 1000.0 + t_idx

    snapshot = Snapshot(
        name="official_netherlands_lithography_2025-01_2025-02",
        source_url="http://mocked/eurostat",
        body=_make_body(partners, time_periods, values),
    )

    points = source.extract([snapshot], run_id="test-run", scraped_at="2026-07-14T00:00:00Z")

    assert len(points) == 10
    scopes = {p.partner_scope for p in points}
    assert scopes == {"cn", "kr", "tw", "us", "world"}

    world_jan = [p for p in points if p.partner_scope == "world" and p.period == "2025-01"][0]
    assert world_jan.value == 5000.0
    assert world_jan.source_region == "netherlands"
    assert world_jan.category_id == "lithography"
    assert world_jan.currency == "EUR"
    assert world_jan.unit == "eur"

    catalog = source.catalog_points(run_id="test-run", scraped_at="2026-07-14T00:00:00Z")
    assert len(catalog) == 1
    assert catalog[0].source_region == "netherlands"
    assert catalog[0].category_id == "lithography"


def test_extract_skips_snapshot_when_fixed_dimensions_are_not_singular() -> None:
    # If Eurostat ever returned more than one category for reporter/product/flow,
    # the simplified flat-index formula would silently misattribute values, so
    # such a response must be skipped rather than trusted.
    source = EurostatSource()
    body = {
        "id": ["freq", "reporter", "partner", "product", "flow", "indicators", "time"],
        "size": [1, 2, 1, 1, 1, 1, 1],
        "dimension": {
            "partner": {"category": {"index": {"CN": 0}}},
            "indicators": {"category": {"index": {"VALUE_IN_EUROS": 0}}},
            "time": {"category": {"index": {"2025-01": 0}}},
        },
        "value": {"0": 123.0},
    }
    snapshot = Snapshot(
        name="official_netherlands_lithography_2025-01",
        source_url="http://mocked/eurostat",
        body=json.dumps(body),
    )
    points = source.extract([snapshot], run_id="test-run", scraped_at="2026-07-14T00:00:00Z")
    assert points == []


def test_extract_ignores_snapshots_from_other_sources() -> None:
    source = EurostatSource()
    snapshot = Snapshot(name="official_korea_ic_only_2025-01_2025-01", source_url="x", body="{}")
    assert source.extract([snapshot], run_id="r", scraped_at="t") == []


def test_extract_ignores_malformed_json() -> None:
    source = EurostatSource()
    snapshot = Snapshot(
        name="official_netherlands_lithography_2025-01",
        source_url="http://mocked/eurostat",
        body="not json",
    )
    assert source.extract([snapshot], run_id="r", scraped_at="t") == []


def test_fetch_snapshots_filters_on_region_category_and_months() -> None:
    source = EurostatSource()
    assert source.fetch_snapshots(["2025-01"], ["korea"], ["lithography"]) == []
    assert source.fetch_snapshots(["2025-01"], ["netherlands"], ["ic_only"]) == []
    assert source.fetch_snapshots([], ["netherlands"], ["lithography"]) == []


def test_chunk_months_splits_and_dedupes() -> None:
    months = [f"2020-{m:02d}" for m in range(1, 13)] + [f"2021-{m:02d}" for m in range(1, 6)] + ["2020-01"]
    chunks = _chunk_months(months, max_months=10)
    assert [len(c) for c in chunks] == [10, 7]
    assert chunks[0][0] == "2020-01"
    assert sum(len(c) for c in chunks) == len(set(months))


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "{}", url: str = "http://mocked") -> None:
        self.status_code = status_code
        self.text = text
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


class _FakeSession:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def headers(self):
        return {}


def test_fetch_with_retry_succeeds_after_transient_server_error(monkeypatch) -> None:
    session = _FakeSession([_FakeResponse(503), _FakeResponse(200, text='{"ok": true}')])
    source = EurostatSource(session=session)
    monkeypatch.setattr("semiconductor_proxy_data.sources.eurostat.time.sleep", lambda _: None)

    response = source._fetch_with_retry(["2025-01"])

    assert session.calls == 2
    assert response.status_code == 200


def test_fetch_with_retry_raises_immediately_on_client_error(monkeypatch) -> None:
    session = _FakeSession([_FakeResponse(400)])
    source = EurostatSource(session=session)
    monkeypatch.setattr("semiconductor_proxy_data.sources.eurostat.time.sleep", lambda _: None)

    with pytest.raises(requests.HTTPError):
        source._fetch_with_retry(["2025-01"])

    # A non-retryable error should not burn through the retry budget.
    assert session.calls == 1
