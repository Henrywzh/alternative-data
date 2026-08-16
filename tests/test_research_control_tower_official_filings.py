"""Batch 2 collector tests: SEC submissions, HKEXnews and issuer-IR states."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.research_control_tower.build import OFFICIAL_FILINGS_COLUMNS, SOURCE_STATE_COLUMNS
from src.research_control_tower.official_filings import (
    SecSubmissionsClient,
    _classify_hkex_title,
    _hkex_announcement_rows,
    _sec_metadata_rows,
    collect_official_filings,
    load_source_identity,
)


SEC_PAYLOAD = {
    "cik": 1577552,
    "name": "Alibaba Group Holding Ltd",
    "filings": {
        "recent": {
            "form": ["6-K", "20-F", "6-K"],
            "accessionNumber": ["0001104659-26-096226", "0001104659-26-000001", "0001104659-26-000002"],
            "filingDate": ["2026-08-14", "2026-06-25", "2026-05-14"],
            "acceptanceDateTime": [
                "2026-08-14T10:02:25-04:00",
                "2026-06-25T09:00:00-04:00",
                "2026-05-14T20:06:18-04:00",
            ],
            "reportDate": ["2026-08-14", "2026-03-31", "2026-05-14"],
            "primaryDocument": ["tm2623260d1_6k.htm", "alibaba-20f.htm", "tm2618550d1_6k.htm"],
            "primaryDocDescription": ["FORM 6-K", "20-F", "FORM 6-K"],
        }
    },
}


def _sec_rows(**overrides):
    defaults = {
        "cik": 1577552,
        "entity_id": "ALIBABA",
        "listing_id": "BABA_US",
        "canonical_ticker": "BABA.US",
        "as_of_utc": pd.Timestamp("2026-08-16T12:00:00Z"),
        "lookback_days": 365,
        "fetched_at": pd.Timestamp("2026-08-16T12:00:00Z"),
        "max_rows": 100,
    }
    defaults.update(overrides)
    return _sec_metadata_rows(SEC_PAYLOAD, **defaults)


class _FakeResponse:
    def __init__(self, payload, *, jsonp=False):
        self._payload = payload
        self._jsonp = jsonp

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    @property
    def text(self):
        if self._jsonp:
            return f"callback({json.dumps(self._payload)});"
        return json.dumps(self._payload)


class _FakeHkexSession:
    """Stub HKEXnews prefix/title endpoints; returns rows only for the first
    title-search window so the month-window loop terminates."""

    def __init__(self, *, rows, stock_id="7609"):
        self.rows = rows
        self.stock_id = stock_id
        self.calls = []
        self._title_searches = 0

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if url.endswith("prefix.do"):
            return _FakeResponse(
                {"more": "1", "stockInfo": [{"stockId": self.stock_id, "code": "00700", "name": "TENCENT"}]},
                jsonp=True,
            )
        self._title_searches += 1
        if self._title_searches > 1:
            return _FakeResponse({"result": "[]"})
        return _FakeResponse({"result": json.dumps(self.rows)})


def _hkex_row(**overrides):
    row = {
        "NEWS_ID": "2026081201234",
        "STOCK_CODE": "00700<br/>80700",
        "STOCK_NAME": "TENCENT",
        "TITLE": "ANNOUNCEMENT OF THE RESULTS FOR THE THREE AND SIX MONTHS ENDED 30 JUNE 2026",
        "DATE_TIME": "12/08/2026 16:31",
        "FILE_LINK": "/listedco/listconews/sehk/2026/0812/2026081201234.htm",
        "FILE_TYPE": "HTM",
    }
    row.update(overrides)
    return row


def test_sec_submissions_mapping_preserves_accepted_report_and_period_fields():
    rows = _sec_rows()
    assert len(rows) == 3
    assert {row["document_type"] for row in rows} == {"filing"}
    assert {row["source_id"] for row in rows} == {"sec_edgar_submissions"}
    assert rows[0]["document_id"] == "sec:0001104659-26-096226"
    assert rows[0]["accepted_at"] == pd.Timestamp("2026-08-14T14:02:25Z")
    assert rows[0]["published_at"] == rows[0]["accepted_at"]
    assert rows[0]["date_precision"] == "minute"
    assert rows[0]["source_timezone"] == "UTC"
    # 6-K rows carry no reporting period (the SEC reportDate is the event
    # date, not a period end); only annual 20-F rows get a period.
    assert pd.isna(rows[0]["reporting_period_end"])
    assert rows[1]["event_class"] == "earnings_results"
    assert rows[1]["reporting_period_label"] == "FY2026"
    assert rows[1]["reporting_period_end"] == pd.Timestamp("2026-03-31T00:00:00Z")
    assert rows[1]["source_url"].startswith("https://www.sec.gov/Archives/edgar/data/1577552/")
    assert not any("content_hash_if_permitted" in row and row["content_hash_if_permitted"] for row in rows)
    assert all(row["content_hash_if_permitted"] == "" for row in rows)


def test_sec_mapping_drops_out_of_window_and_future_rows():
    rows = _sec_rows(as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"), lookback_days=30)
    assert [row["document_id"] for row in rows] == ["sec:0001104659-26-096226"]


def test_hkex_title_classification_covers_annual_interim_quarterly_and_general():
    assert _classify_hkex_title("ANNOUNCEMENT OF THE RESULTS FOR THE THREE AND SIX MONTHS ENDED 30 JUNE 2026") == {
        "event_class": "earnings_results",
        "reporting_period_label": "1H2026",
        "reporting_period_start": date(2025, 12, 30),
        "reporting_period_end": date(2026, 6, 30),
    }
    annual = _classify_hkex_title("ANNOUNCEMENT OF ANNUAL RESULTS FOR THE YEAR ENDED DECEMBER 31, 2025")
    assert annual["event_class"] == "earnings_results"
    assert annual["reporting_period_label"] == "FY2025"
    quarterly = _classify_hkex_title("ANNOUNCEMENT OF THE RESULTS FOR THE FIRST QUARTER ENDED 31 MARCH 2026")
    assert quarterly["event_class"] == "earnings_results"
    assert quarterly["reporting_period_label"] == "Q12026"
    assert _classify_hkex_title("MONTHLY RETURN OF EQUITY ISSUER")["event_class"] == "general"


def test_hkex_adapter_guards_stock_code_and_maps_publication_time():
    rows = [
        _hkex_row(),
        _hkex_row(
            NEWS_ID="2026081209999",
            TITLE="MONTHLY RETURN OF EQUITY ISSUER",
            DATE_TIME="06/08/2026 16:57",
            FILE_LINK="/listedco/listconews/sehk/2026/0806/2026081209999.htm",
        ),
        # Wrong-company row must be dropped by the STOCK_CODE guard.
        _hkex_row(
            NEWS_ID="2026081200001",
            STOCK_CODE="00362",
            TITLE="WRONG COMPANY ANNOUNCEMENT",
        ),
    ]
    session = _FakeHkexSession(rows=rows)
    mapped, state = _hkex_announcement_rows(
        session,
        ticker="700",
        entity_id="TENCENT",
        listing_id="0700_HK",
        canonical_ticker="0700.HK",
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        lookback_days=90,
        fetched_at=pd.Timestamp("2026-08-16T12:00:00Z"),
        timeout=5,
        max_rows=100,
    )
    assert state == "available"
    assert [row["document_id"] for row in mapped] == ["hkexnews:2026081201234", "hkexnews:2026081209999"]
    earnings = mapped[0]
    assert earnings["event_class"] == "earnings_results"
    # 16:31 Asia/Hong_Kong on 2026-08-12 == 08:31 UTC.
    assert earnings["published_at"] == pd.Timestamp("2026-08-12T08:31:00Z")
    assert earnings["date_precision"] == "minute"
    assert earnings["source_timezone"] == "Asia/Hong_Kong"
    assert earnings["source_url"] == "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0812/2026081201234.htm"
    assert earnings["reporting_period_label"] == "1H2026"
    assert mapped[1]["event_class"] == "general"


def test_identity_crosswalk_requires_native_id_columns(tmp_path):
    path = tmp_path / "identity.csv"
    path.write_text("entity_id,listing_id\nALIBABA,BABA_US\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        load_source_identity(path)


def test_collector_writes_honest_issuer_ir_and_bytedance_states(tmp_path):
    identity = pd.DataFrame(
        [
            {
                "entity_id": "TENCENT",
                "listing_id": "0700_HK",
                "canonical_ticker": "0700.HK",
                "source_kind": "hkex_code",
                "source_native_id": "700",
                "source_url": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en",
                "note": "",
            },
            {
                "entity_id": "ALIBABA",
                "listing_id": "BABA_US",
                "canonical_ticker": "BABA.US",
                "source_kind": "sec_cik",
                "source_native_id": "1577552",
                "source_url": "https://www.sec.gov/",
                "note": "",
            },
        ]
    )
    output = tmp_path / "out"

    class _StubSecClient:
        def fetch_submissions(self, cik):
            assert cik == 1577552
            return SEC_PAYLOAD

    frame, state = collect_official_filings(
        identity,
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        lookback_days=365,
        output_dir=output,
        raw_root=tmp_path,
        user_agent="test/0.1 research@example.com",
        sec_client=_StubSecClient(),
        hkex_session=_FakeHkexSession(rows=[_hkex_row()]),
        timeout=5,
    )
    assert list(frame.columns) == OFFICIAL_FILINGS_COLUMNS
    assert list(state.columns) == SOURCE_STATE_COLUMNS
    assert {"sec_edgar_submissions", "hkexnews"} <= set(frame["source_id"])
    by_source = state.set_index("source_id")["status"].to_dict()
    assert by_source["filings:sec_edgar_submissions"] == "available"
    assert by_source["filings:hkexnews"] == "available"
    assert by_source["filings:issuer_ir"] == "no_records"
    assert by_source["filings:bytedance"] == "not_applicable"
    assert (output / "official_filings_v1.parquet").is_file()
    assert (output / "official_filings_state.parquet").is_file()
    assert not any("body" in column for column in frame.columns)
