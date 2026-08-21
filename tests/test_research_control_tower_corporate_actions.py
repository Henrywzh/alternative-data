"""T1 corporate-actions collector tests: HKEX Next Day Disclosure parsing.

Offline only: title-search adapters run against a fake HKEXnews session, body
fetches run against a fake fetcher keyed to official-document fixtures under
tests/fixtures/hkex_corporate_actions/ (text snapshots extracted from official
Tencent Next Day Disclosure Return PDFs: FF305 2025-06-13 and FF304
2024-01-18).  No live network is required; missing fields are asserted null
with provenance, never inferred.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.research_control_tower.build import SOURCE_STATE_COLUMNS
import src.research_control_tower.corporate_actions as corporate_actions
from src.research_control_tower.corporate_actions import (
    CORP_ACTIONS_COLUMNS,
    _action_id,
    classify_action_type,
    collect_corporate_actions,
    parse_next_day_disclosure,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "hkex_corporate_actions"
FF305_FIXTURE = FIXTURE_DIR / "ndd_tencent_ff305_20250613.txt"
FF304_FIXTURE = FIXTURE_DIR / "ndd_tencent_ff304_20240118.txt"


@pytest.fixture(autouse=True)
def _no_network_throttle(monkeypatch):
    """Zero the per-window pause so offline collector tests stay fast."""

    monkeypatch.setattr(corporate_actions, "HKEX_QUERY_INTERVAL_SECONDS", 0)


def _fixture_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class _FakeResponse:
    def __init__(self, payload, *, jsonp=False, text=None):
        self._payload = payload
        self._jsonp = jsonp
        self._text = text

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    @property
    def text(self):
        if self._text is not None:
            return self._text
        if self._jsonp:
            return f"callback({json.dumps(self._payload)});"
        return json.dumps(self._payload)


def _hkex_row(
    *,
    news_id,
    title,
    date_time,
    file_link,
    file_type="PDF",
    stock_code="00700<br/>80700",
    long_text="",
    short_text="",
):
    return {
        "NEWS_ID": news_id,
        "STOCK_CODE": stock_code,
        "STOCK_NAME": "TENCENT",
        "TITLE": title,
        "LONG_TEXT": long_text,
        "SHORT_TEXT": short_text,
        "DATE_TIME": date_time,
        "FILE_LINK": file_link,
        "FILE_TYPE": file_type,
    }


class _FakeHkexSession:
    """Stub for prefix.do and the two title-search queries (NDD, Dividend)."""

    def __init__(self, *, ndd_rows=None, dividend_rows=None, stock_id="7609"):
        self.ndd_rows = ndd_rows or []
        self.dividend_rows = dividend_rows or []
        self.stock_id = stock_id
        self.calls = []

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if url.endswith("prefix.do"):
            return _FakeResponse(
                {"more": "1", "stockInfo": [{"stockId": self.stock_id, "code": "00700", "name": "TENCENT"}]},
                jsonp=True,
            )
        title = (params or {}).get("title")
        if title == "Next Day Disclosure Return":
            payload = self.ndd_rows
        elif title == "Dividend":
            payload = self.dividend_rows
        else:
            payload = []
        return _FakeResponse({"result": json.dumps(payload)})


class _WindowedHkexSession(_FakeHkexSession):
    """Return only rows inside the requested title-search date window."""

    def __init__(self, rows):
        super().__init__(ndd_rows=rows)

    def get(self, url, *, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if url.endswith("prefix.do"):
            return _FakeResponse(
                {"more": "1", "stockInfo": [{"stockId": self.stock_id, "code": "00700", "name": "TENCENT"}]},
                jsonp=True,
            )
        title = (params or {}).get("title")
        if title != "Next Day Disclosure Return":
            payload = []
        else:
            start = pd.Timestamp((params or {}).get("fromDate"))
            end = pd.Timestamp((params or {}).get("toDate"))
            payload = [
                row
                for row in self.ndd_rows
                if start
                <= pd.to_datetime(row["DATE_TIME"].split(" ", 1)[0], dayfirst=True)
                <= end
            ]
        return _FakeResponse({"result": json.dumps(payload)})


def _fake_body_fetcher(payload_by_suffix: dict[str, bytes]):
    def fetch(url: str) -> bytes | None:
        for suffix, payload in payload_by_suffix.items():
            if url.endswith(suffix):
                return payload
        return None

    return fetch


def _identity_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entity_id": "TENCENT",
                "listing_id": "0700_HK",
                "canonical_ticker": "0700.HK",
                "source_kind": "hkex_code",
                "source_native_id": "700",
                "source_url": "https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en",
                "note": "",
            }
        ]
    )


def test_ff305_fixture_parses_all_source_extractable_fields():
    parsed = parse_next_day_disclosure(_fixture_text(FF305_FIXTURE))
    assert parsed.form == "FF305"
    assert parsed.issuer_name == "Tencent Holdings Limited"
    assert parsed.date_submitted == "2025-06-13"
    assert len(parsed.rows) == 1
    row = parsed.rows[0]
    assert row["row_no"] == 1
    assert row["trading_date"] == "2025-06-13"
    assert row["shares"] == 982_000
    assert row["method"] == "On the Exchange"
    # Official header order: highest price first, then lowest; min/max by value.
    assert row["price_first"] == 515.0
    assert row["price_second"] == 506.5
    assert row["total_paid"] == 500_382_813.6
    assert parsed.aggregate_price_paid == 500_382_813.6
    assert parsed.shares_for_cancellation == 982_000
    assert parsed.shares_for_treasury == 0
    assert parsed.mandate_resolution_date == "2025-05-14"
    assert parsed.mandate_authorised_shares == 918_901_866
    assert parsed.mandate_cumulative_shares == 19_588_000
    assert "cancellation_status null by design" in parsed.coverage_reason


def test_ff304_fixture_parses_legacy_purchase_report():
    parsed = parse_next_day_disclosure(_fixture_text(FF304_FIXTURE))
    assert parsed.form == "FF304"
    assert parsed.date_submitted == "2024-01-18"
    assert len(parsed.rows) == 1
    row = parsed.rows[0]
    assert row["trading_date"] == "2024-01-18"
    assert row["shares"] == 3_640_000
    assert row["price_first"] == 278.8
    assert row["price_second"] == 271.2
    assert row["total_paid"] == 1_002_506_232
    assert parsed.aggregate_price_paid == 1_002_506_232
    # FF304 discloses no cancellation designation or mandate resolution date.
    assert parsed.shares_for_cancellation is None
    assert parsed.shares_for_treasury is None
    assert parsed.mandate_resolution_date is None
    assert parsed.mandate_cumulative_shares == 169_202_600
    assert "FF304 discloses no repurchase-mandate resolution date" in parsed.coverage_reason


def test_unsupported_layout_reports_parse_error_not_fabrication():
    text = (
        "FF999\nNext Day Disclosure Return\nName of Issuer: Some Issuer Limited\n"
        "Section I\nNo repurchase report section present in this variant.\n"
    )
    parsed = parse_next_day_disclosure(text)
    assert parsed.rows == []
    assert "no A. Repurchase/Purchase report section found" in parsed.parse_errors
    assert "metadata only" in parsed.coverage_reason


def test_classify_action_type_covers_buyback_dividend_and_skips():
    action, note = classify_action_type(
        title="Next Day Disclosure Return - Changes in issued shares and share buybacks",
        long_text="Next Day Disclosure Returns - [Others & / Share Buyback]",
    )
    assert action == "buyback_execution"
    action, _ = classify_action_type(
        title="Next Day Disclosure Return (Share Buyback)",
        long_text="Next Day Disclosure Returns - [Share Buyback]",
    )
    assert action == "buyback_execution"
    action, _ = classify_action_type(title="Next Day Disclosure Return (Directors'/Chief Executive's Interests)")
    assert action is None
    action, _ = classify_action_type(title="FINAL DIVIDEND FOR THE YEAR ENDED 31 DECEMBER 2024")
    assert action == "cash_dividend"
    action, _ = classify_action_type(title="INTERIM DIVIDEND FOR THE SIX MONTHS ENDED 30 JUNE 2025")
    assert action == "cash_dividend"
    action, _ = classify_action_type(title="DISTRIBUTION IN SPECIE OF HELD SHARES")
    assert action == "distribution_in_specie"
    action, _ = classify_action_type(title="MONTHLY RETURN OF EQUITY ISSUER")
    assert action is None


def test_action_id_is_deterministic_key_of_listing_dates_and_type():
    first = _action_id("0700_HK", "2025-06-13", "2025-06-13", "buyback_execution")
    same = _action_id("0700_HK", "2025-06-13", "2025-06-13", "buyback_execution")
    different_day = _action_id("0700_HK", "2025-06-13", "2025-06-12", "buyback_execution")
    different_type = _action_id("0700_HK", "2025-06-13", "", "cash_dividend")
    assert first == same
    assert first != different_day
    assert first != different_type
    assert first.startswith("ca:")
    assert len(first) == 3 + 24


def _default_ndd_rows():
    return [
        _hkex_row(
            news_id="11713183",
            title="Next Day Disclosure Return - Changes in issued shares and share buybacks",
            date_time="13/06/2025 17:56",
            file_link="/listedco/listconews/sehk/2025/0613/2025061300897.pdf",
            long_text="Next Day Disclosure Returns - [Share Buyback]",
            short_text="Next Day Disclosure Returns - [Share Buyback]",
        ),
        _hkex_row(
            news_id="11700000",
            title="Next Day Disclosure Return (Directors'/Chief Executive's Interests)",
            date_time="12/06/2025 16:30",
            file_link="/listedco/listconews/sehk/2025/0612/2025061200000.pdf",
            long_text="Next Day Disclosure Returns - [Directors'/Chief Executive's Interests]",
        ),
        # Wrong-company row must be dropped by the STOCK_CODE guard.
        _hkex_row(
            news_id="11999999",
            title="Next Day Disclosure Return (Share Buyback)",
            date_time="11/06/2025 17:00",
            file_link="/listedco/listconews/sehk/2025/0611/2025061100000.pdf",
            stock_code="00362",
            long_text="Next Day Disclosure Returns - [Share Buyback]",
        ),
    ]


def _default_dividend_rows():
    return [
        _hkex_row(
            news_id="11576458",
            title="FINAL DIVIDEND FOR THE YEAR ENDED 31 DECEMBER 2024",
            date_time="19/03/2025 16:35",
            file_link="/listedco/listconews/sehk/2025/0319/2025031900412.pdf",
            long_text="Announcements and Notices - [Dividend or Distribution (Announcement Form)]",
            short_text="Announcements and Notices - [Dividend or Distribution (Announcement Form)]",
        )
    ]


def test_collector_end_to_end_buyback_dividend_skip_and_guard(tmp_path):
    session = _FakeHkexSession(
        ndd_rows=_default_ndd_rows(),
        dividend_rows=_default_dividend_rows(),
    )
    fetcher = _fake_body_fetcher(
        {"2025061300897.pdf": _fixture_text(FF305_FIXTURE).encode("utf-8")}
    )
    frame, state = collect_corporate_actions(
        _identity_frame(),
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        retrieved_at_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        lookback_days=400,
        output_dir=tmp_path / "out",
        hkex_session=session,
        body_fetcher=fetcher,
        text_extractor=lambda payload, fmt: payload.decode("utf-8"),
        timeout=5,
    )
    assert list(frame.columns) == CORP_ACTIONS_COLUMNS
    assert list(state.columns) == SOURCE_STATE_COLUMNS
    assert frame["action_type"].tolist() == ["buyback_execution", "cash_dividend"]

    buyback = frame.iloc[0]
    assert buyback["entity_id"] == "TENCENT"
    assert buyback["listing_id"] == "0700_HK"
    assert buyback["canonical_ticker"] == "0700.HK"
    assert buyback["filing_date"] == "2025-06-13"
    assert buyback["execution_date"] == "2025-06-13"
    # 17:56 Asia/Hong_Kong = 09:56 UTC.
    assert buyback["published_at"] == pd.Timestamp("2025-06-13T09:56:00Z")
    assert buyback["shares_affected"] == 982_000
    assert buyback["price_min"] == 506.5
    assert buyback["price_max"] == 515.0
    assert buyback["price_avg"] is None or pd.isna(buyback["price_avg"])
    assert buyback["total_amount_paid"] == 500_382_813.6
    assert buyback["currency"] == "HKD"
    assert buyback["shares_for_cancellation"] == 982_000
    assert buyback["shares_for_treasury"] == 0
    assert buyback["mandate_resolution_date"] == "2025-05-14"
    assert buyback["mandate_authorised_shares"] == 918_901_866
    assert buyback["mandate_cumulative_repurchased_shares"] == 19_588_000
    assert buyback["source_url"].endswith("/2025061300897.pdf")
    assert buyback["source_document_id"] == "11713183"
    assert buyback["document_format"] == "pdf"
    assert buyback["source_timezone"] == "Asia/Hong_Kong"
    assert buyback["date_precision"] == "minute"
    assert buyback["source_quality"] == "official_body"
    assert buyback["pit_class"] == "snapshot_from_live_source"
    assert buyback["source_license_class"] == "official_public_metadata"
    assert buyback["registry_version"] == "v1"
    assert buyback["action_id"] == _action_id("0700_HK", "2025-06-13", "2025-06-13", "buyback_execution", "11713183", 1)

    dividend = frame.iloc[1]
    assert dividend["action_type"] == "cash_dividend"
    assert dividend["filing_date"] == "2025-03-19"
    assert dividend["execution_date"] == ""
    assert dividend["published_at"] == pd.Timestamp("2025-03-19T08:35:00Z")
    assert pd.isna(dividend["shares_affected"])
    assert pd.isna(dividend["price_min"])
    assert pd.isna(dividend["price_max"])
    assert pd.isna(dividend["total_amount_paid"])
    assert "deferred to a specialised dividend parser" in dividend["coverage_reason"]
    assert dividend["source_quality"] == "official_metadata"
    assert dividend["action_id"] == _action_id("0700_HK", "2025-03-19", "", "cash_dividend", "11576458", 1)

    # Directors' interests row skipped; wrong-company row dropped by guard.
    state_row = state.iloc[0]
    assert state_row["status"] == "available"
    assert state_row["source_id"] == "corporate_actions:hkexnews"
    assert "collected=3" in state_row["detail"]
    assert "parsed=1" in state_row["detail"]
    assert "skipped=1" in state_row["detail"]
    assert state_row["row_count"] == 2
    assert state_row["first_observation_at"] == pd.Timestamp("2025-03-19T08:35:00Z")
    assert state_row["latest_observation_at"] == pd.Timestamp("2025-06-13T09:56:00Z")
    assert state_row["source_latest_at"] == pd.Timestamp("2025-06-13T09:56:00Z")
    assert state_row["retrieved_at_utc"] == pd.Timestamp("2026-08-16T12:00:00Z")
    assert (tmp_path / "out" / "corporate_actions_v1.parquet").is_file()
    assert (tmp_path / "out" / "corporate_actions_state.parquet").is_file()


def test_365_day_tencent_collection_completes_beyond_legacy_120_row_cap(tmp_path):
    rows = []
    start = pd.Timestamp("2025-08-20")
    for index in range(121):
        day = start + pd.Timedelta(days=index)
        rows.append(
            _hkex_row(
                news_id=f"audit-{index:03d}",
                title="Next Day Disclosure Return - Changes in issued shares and share buybacks",
                date_time=day.strftime("%d/%m/%Y") + " 17:00",
                file_link=f"/listedco/listconews/sehk/{day:%Y}/{day:%m%d}/audit-{index:03d}.pdf",
                long_text="Next Day Disclosure Returns - [Share Buyback]",
            )
        )
    session = _WindowedHkexSession(rows)

    frame, state = collect_corporate_actions(
        _identity_frame(),
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        retrieved_at_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        lookback_days=365,
        output_dir=tmp_path / "complete",
        hkex_session=session,
        body_fetcher=lambda _url: None,
        timeout=5,
    )

    assert len(frame) == 121
    detail = state.iloc[0]["detail"]
    assert "raw_rows=121" in detail
    assert "truncated=false" in detail
    assert state.iloc[0]["status"] == "partial"

    capped_frame, capped_state = collect_corporate_actions(
        _identity_frame(),
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        retrieved_at_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        lookback_days=365,
        max_rows_per_query=120,
        hkex_session=_WindowedHkexSession(rows),
        body_fetcher=lambda _url: None,
        timeout=5,
    )
    assert len(capped_frame) == 120
    assert "truncated=true" in capped_state.iloc[0]["detail"]
    assert capped_state.iloc[0]["status"] == "partial"


def test_parquet_roundtrip_preserves_nullable_schema(tmp_path):
    session = _FakeHkexSession(
        ndd_rows=_default_ndd_rows()[:1],
        dividend_rows=_default_dividend_rows(),
    )
    fetcher = _fake_body_fetcher(
        {"2025061300897.pdf": _fixture_text(FF305_FIXTURE).encode("utf-8")}
    )
    frame, _state = collect_corporate_actions(
        _identity_frame(),
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        lookback_days=400,
        output_dir=tmp_path / "out",
        hkex_session=session,
        body_fetcher=fetcher,
        text_extractor=lambda payload, fmt: payload.decode("utf-8"),
        timeout=5,
    )
    reloaded = pd.read_parquet(tmp_path / "out" / "corporate_actions_v1.parquet")
    assert list(reloaded.columns) == CORP_ACTIONS_COLUMNS
    dtype_text = str(reloaded["published_at"].dtype)
    assert dtype_text.startswith("datetime64[") and "UTC" in dtype_text
    assert "Int64" in str(reloaded["shares_affected"].dtype)
    # Dividend row keeps null shares through the parquet round trip.
    assert pd.isna(reloaded["shares_affected"].iloc[1])
    assert pd.isna(reloaded["total_amount_paid"].iloc[1])
    assert reloaded["action_id"].is_unique


def test_body_fetch_failure_preserves_metadata_row(tmp_path):
    session = _FakeHkexSession(ndd_rows=_default_ndd_rows()[:1])
    fetcher = _fake_body_fetcher({})  # every body fetch returns None
    frame, state = collect_corporate_actions(
        _identity_frame(),
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        lookback_days=400,
        output_dir=tmp_path / "out",
        hkex_session=session,
        body_fetcher=fetcher,
        text_extractor=lambda payload, fmt: payload.decode("utf-8"),
        timeout=5,
    )
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["action_type"] == "buyback_execution"
    assert row["filing_date"] == "2025-06-13"
    assert row["execution_date"] == ""
    assert pd.isna(row["shares_affected"])
    assert pd.isna(row["total_amount_paid"])
    assert "body fetch failed" in row["coverage_reason"]
    assert row["source_quality"] == "official_metadata"
    assert "collected=1" in state.iloc[0]["detail"]
    assert "unparsed=1" in state.iloc[0]["detail"]


def test_parse_failure_preserves_metadata_row(tmp_path):
    session = _FakeHkexSession(ndd_rows=_default_ndd_rows()[:1])
    fetcher = _fake_body_fetcher(
        {"2025061300897.pdf": b"FF305 not-a-real-ndd-body without report sections"}
    )
    frame, state = collect_corporate_actions(
        _identity_frame(),
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        lookback_days=400,
        output_dir=tmp_path / "out",
        hkex_session=session,
        body_fetcher=fetcher,
        text_extractor=lambda payload, fmt: payload.decode("utf-8"),
        timeout=5,
    )
    assert len(frame) == 1
    row = frame.iloc[0]
    assert row["action_type"] == "buyback_execution"
    assert pd.isna(row["shares_affected"])
    assert "no A. Repurchase/Purchase report section found" in row["coverage_reason"]
    assert "unparsed=1" in state.iloc[0]["detail"]


def test_multi_row_filing_keeps_filing_level_fields_null(tmp_path):
    # Compact FF305-style body with TWO repurchase rows in Part A (very rare
    # but legitimate: round-lot + off-exchange rows in one return).
    multi_row_body = (
        "FF305\nNext Day Disclosure Return\n"
        "Name of Issuer: Tencent Holdings Limited\n"
        "Date Submitted: 13 June 2025\n"
        "Section II\n"
        "1. Class of shares Ordinary shares Type of shares Not applicable Listed on the Exchange Yes\n"
        "A. Repurchase report\n"
        "Trading date Number of shares Method of repurchase highest price Lowest price Aggregate price paid\n"
        "1). 05 June 2025 100,000On the Exchange HKD 100.5HKD 99.2HKD 9,985,000\n"
        "2). 06 June 2025 50,000On the Exchange HKD 101HKD 100HKD 5,025,000\n"
        "Total number of shares repurchased 150,000 Aggregate price paid $HKD 15,010,000\n"
        "Number of shares repurchased for cancellation 150,000\n"
        "Number of shares repurchased for holding as treasury shares 0\n"
        "B. Additional information for issuer who has a primary listing on the Exchange\n"
        "1). Date of the resolution granting the repurchase mandate 14 May 2025\n"
    )
    session = _FakeHkexSession(ndd_rows=_default_ndd_rows()[:1])
    fetcher = _fake_body_fetcher({"2025061300897.pdf": multi_row_body.encode("utf-8")})
    frame, _state = collect_corporate_actions(
        _identity_frame(),
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        lookback_days=400,
        output_dir=tmp_path / "out",
        hkex_session=session,
        body_fetcher=fetcher,
        text_extractor=lambda payload, fmt: payload.decode("utf-8"),
        timeout=5,
    )
    # Two execution rows, each with its own numbers; filing-level summary,
    # designation and mandate fields stay null on multi-row filings.
    assert len(frame) == 2
    assert frame["shares_affected"].tolist() == [100_000, 50_000]
    assert frame["total_amount_paid"].tolist() == [9_985_000, 5_025_000]
    assert frame["execution_date"].tolist() == ["2025-06-05", "2025-06-06"]
    assert pd.isna(frame["shares_for_cancellation"].iloc[0])
    assert pd.isna(frame["mandate_authorised_shares"].iloc[0])
    assert "multi-row filings" in frame["coverage_reason"].iloc[0]
    assert frame["action_id"].is_unique


def test_no_hkex_identity_emits_no_records_state(tmp_path):
    identity = pd.DataFrame(
        [
            {
                "entity_id": "ALIBABA",
                "listing_id": "BABA_US",
                "canonical_ticker": "BABA.US",
                "source_kind": "sec_cik",
                "source_native_id": "1577552",
                "source_url": "https://www.sec.gov/",
                "note": "",
            }
        ]
    )
    frame, state = collect_corporate_actions(
        identity,
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        output_dir=tmp_path / "out",
        timeout=5,
    )
    assert frame.empty
    assert list(frame.columns) == CORP_ACTIONS_COLUMNS
    assert state.iloc[0]["status"] == "no_records"
    assert "no hkex_code identity rows" in state.iloc[0]["detail"]


def test_ff305_round_trip_matches_official_filing_values():
    """Cross-check the fixture text against the officially filed numbers."""

    parsed = parse_next_day_disclosure(_fixture_text(FF305_FIXTURE))
    row = parsed.rows[0]
    # Real 2025-06-13 Tencent NDD disclosures (public official record).
    assert (row["shares"], row["price_first"], row["price_second"]) == (982_000, 515.0, 506.5)
    assert row["total_paid"] == 500_382_813.6
    assert parsed.shares_for_cancellation == row["shares"]
    assert parsed.shares_for_treasury == 0


def test_collection_clock_and_as_of_utc_separation(tmp_path):
    """A historical query cutoff must never fabricate a historical retrieval timestamp."""
    session = _FakeHkexSession(ndd_rows=_default_ndd_rows()[:1])
    fetcher = _fake_body_fetcher(
        {"2025061300897.pdf": _fixture_text(FF305_FIXTURE).encode("utf-8")}
    )
    historical_cutoff = pd.Timestamp("2025-06-30T00:00:00Z")
    true_retrieval_clock = pd.Timestamp("2026-08-21T14:30:00Z")

    frame, state = collect_corporate_actions(
        _identity_frame(),
        as_of_utc=historical_cutoff,
        retrieved_at_utc=true_retrieval_clock,
        output_dir=tmp_path / "out",
        hkex_session=session,
        body_fetcher=fetcher,
        text_extractor=lambda payload, fmt: payload.decode("utf-8"),
        timeout=5,
    )
    assert len(frame) == 1
    # Row retrieved_at_utc is the actual collection time, not the query cutoff.
    assert frame["retrieved_at_utc"].iloc[0] == true_retrieval_clock
    assert state["retrieved_at_utc"].iloc[0] == true_retrieval_clock
    # Observation timestamps honestly reflect the data.
    assert state["first_observation_at"].iloc[0] == pd.Timestamp("2025-06-13T09:56:00Z")
    assert state["latest_observation_at"].iloc[0] == pd.Timestamp("2025-06-13T09:56:00Z")


def test_intraday_and_future_published_at_discarded():
    """Rows published after as_of_utc (including same calendar day future times) must be discarded."""
    # Three rows:
    # 1. 13/06/2025 16:30 HKT = 08:30 UTC (before cutoff -> KEPT)
    # 2. 13/06/2025 17:56 HKT = 09:56 UTC (after cutoff on same day -> DISCARDED)
    # 3. 14/06/2025 09:00 HKT = 01:00 UTC next day (after cutoff -> DISCARDED)
    ndd_rows = [
        _hkex_row(
            news_id="11700001",
            title="Next Day Disclosure Return - Changes in issued shares and share buybacks",
            date_time="13/06/2025 16:30",
            file_link="/listedco/listconews/sehk/2025/0613/2025061300001.pdf",
            long_text="Next Day Disclosure Returns - [Share Buyback]",
        ),
        _hkex_row(
            news_id="11700002",
            title="Next Day Disclosure Return - Changes in issued shares and share buybacks",
            date_time="13/06/2025 17:56",
            file_link="/listedco/listconews/sehk/2025/0613/2025061300002.pdf",
            long_text="Next Day Disclosure Returns - [Share Buyback]",
        ),
        _hkex_row(
            news_id="11700003",
            title="Next Day Disclosure Return - Changes in issued shares and share buybacks",
            date_time="14/06/2025 09:00",
            file_link="/listedco/listconews/sehk/2025/0614/2025061400003.pdf",
            long_text="Next Day Disclosure Returns - [Share Buyback]",
        ),
    ]
    session = _FakeHkexSession(ndd_rows=ndd_rows)
    fetcher = _fake_body_fetcher(
        {"2025061300001.pdf": _fixture_text(FF305_FIXTURE).encode("utf-8")}
    )
    # Cutoff at 09:00 UTC on 2025-06-13
    frame, state = collect_corporate_actions(
        _identity_frame(),
        as_of_utc=pd.Timestamp("2025-06-13T09:00:00Z"),
        hkex_session=session,
        body_fetcher=fetcher,
        text_extractor=lambda payload, fmt: payload.decode("utf-8"),
        timeout=5,
    )
    # Only the 08:30 UTC row is kept.
    assert len(frame) == 1
    assert frame["source_document_id"].iloc[0] == "11700001"
    assert frame["published_at"].iloc[0] == pd.Timestamp("2025-06-13T08:30:00Z")
    assert state["row_count"].iloc[0] == 1
    assert state["latest_observation_at"].iloc[0] == pd.Timestamp("2025-06-13T08:30:00Z")


def test_action_id_collision_freedom_on_same_execution_date():
    """Multi-row filings with same execution date produce distinct, deterministic action_ids."""
    body = (
        "FF305\nNext Day Disclosure Return\n"
        "Name of Issuer: Tencent Holdings Limited\n"
        "Date Submitted: 13 June 2025\n"
        "Section II\nA. Repurchase report\n"
        "1). 13 June 2025 500,000On the Exchange HKD 510HKD 505HKD 253,750,000\n"
        "2). 13 June 2025 482,000another stock exchange HKD 512HKD 508HKD 246,632,813.6\n"
    )
    session = _FakeHkexSession(ndd_rows=_default_ndd_rows()[:1])
    fetcher = _fake_body_fetcher({"2025061300897.pdf": body.encode("utf-8")})
    frame, _state = collect_corporate_actions(
        _identity_frame(),
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        hkex_session=session,
        body_fetcher=fetcher,
        text_extractor=lambda payload, fmt: payload.decode("utf-8"),
        timeout=5,
    )
    assert len(frame) == 2
    # Both rows share the same execution date (2025-06-13).
    assert frame["execution_date"].iloc[0] == "2025-06-13"
    assert frame["execution_date"].iloc[1] == "2025-06-13"
    # But their action_ids must NOT collide!
    assert frame["action_id"].iloc[0] != frame["action_id"].iloc[1]
    assert frame["action_id"].is_unique


def test_duplicate_action_id_fails_closed(monkeypatch):
    """If action_id generation ever collides, collect_corporate_actions must fail closed."""
    session = _FakeHkexSession(ndd_rows=_default_ndd_rows()[:1], dividend_rows=_default_dividend_rows())
    fetcher = _fake_body_fetcher(
        {"2025061300897.pdf": _fixture_text(FF305_FIXTURE).encode("utf-8")}
    )
    # Force collision by monkeypatching _action_id to return a constant
    monkeypatch.setattr(corporate_actions, "_action_id", lambda *args, **kwargs: "ca:constant_hash")
    with pytest.raises(ValueError, match="duplicate action_id detected"):
        collect_corporate_actions(
            _identity_frame(),
            as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
            hkex_session=session,
            body_fetcher=fetcher,
            text_extractor=lambda payload, fmt: payload.decode("utf-8"),
            timeout=5,
        )


def test_atomic_write_leaves_no_temp_files(tmp_path):
    """Atomic parquet write writes the expected files without leftover .tmp files."""
    session = _FakeHkexSession(ndd_rows=_default_ndd_rows()[:1])
    fetcher = _fake_body_fetcher(
        {"2025061300897.pdf": _fixture_text(FF305_FIXTURE).encode("utf-8")}
    )
    out_dir = tmp_path / "atomic_out"
    frame, state = collect_corporate_actions(
        _identity_frame(),
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        output_dir=out_dir,
        hkex_session=session,
        body_fetcher=fetcher,
        text_extractor=lambda payload, fmt: payload.decode("utf-8"),
        timeout=5,
    )
    assert (out_dir / "corporate_actions_v1.parquet").is_file()
    assert (out_dir / "corporate_actions_state.parquet").is_file()
    # Ensure no leftover temporary files in out_dir
    tmp_files = list(out_dir.glob("*.tmp"))
    assert tmp_files == []


def test_causal_clock_violation_raises_value_error():
    """retrieved_at_utc < as_of_utc claims impossible pre-cognition and must fail closed."""
    future_as_of = pd.Timestamp("2026-08-30T00:00:00Z")
    past_retrieved = pd.Timestamp("2026-08-21T12:00:00Z")
    with pytest.raises(ValueError, match="causal clock violation"):
        collect_corporate_actions(
            _identity_frame(),
            as_of_utc=future_as_of,
            retrieved_at_utc=past_retrieved,
        )


def test_source_status_partial_when_parsed_coexists_with_unparsed_or_exceptions():
    """Status is partial when parsed rows coexist with unparsed or exceptions; skips do not degrade."""
    # 1. Parsed + unparsed -> partial
    ndd_rows = [
        _hkex_row(
            news_id="11713183",
            title="Next Day Disclosure Return - Changes in issued shares and share buybacks",
            date_time="13/06/2025 17:56",
            file_link="/listedco/listconews/sehk/2025/0613/2025061300897.pdf",
            long_text="Next Day Disclosure Returns - [Share Buyback]",
        ),
        _hkex_row(
            news_id="11713184",
            title="Next Day Disclosure Return - Changes in issued shares and share buybacks",
            date_time="14/06/2025 17:56",
            file_link="/listedco/listconews/sehk/2025/0614/2025061400898.pdf",
            long_text="Next Day Disclosure Returns - [Share Buyback]",
        ),
        # Deliberate non-corporate skip
        _hkex_row(
            news_id="11700000",
            title="Next Day Disclosure Return (Directors'/Chief Executive's Interests)",
            date_time="12/06/2025 16:30",
            file_link="/listedco/listconews/sehk/2025/0612/2025061200000.pdf",
            long_text="Next Day Disclosure Returns - [Directors'/Chief Executive's Interests]",
        ),
    ]
    session = _FakeHkexSession(ndd_rows=ndd_rows)
    # Only 00897 succeeds; 00898 returns None (unparsed fetch failure)
    fetcher = _fake_body_fetcher({"2025061300897.pdf": _fixture_text(FF305_FIXTURE).encode("utf-8")})
    _frame, state = collect_corporate_actions(
        _identity_frame(),
        as_of_utc=pd.Timestamp("2026-08-16T12:00:00Z"),
        hkex_session=session,
        body_fetcher=fetcher,
        text_extractor=lambda payload, fmt: payload.decode("utf-8"),
        timeout=5,
    )
    assert state["status"].iloc[0] == "partial"
    assert "parsed=1" in state["detail"].iloc[0]
    assert "unparsed=1" in state["detail"].iloc[0]
    assert "skipped=1" in state["detail"].iloc[0]
