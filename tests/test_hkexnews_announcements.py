"""Regression tests for the HKEXnews company announcements source.

titleSearchServlet.do's `stockId` query parameter does NOT filter by the
plain numeric stock code -- confirmed live: calling it with stockId="700"
(Tencent) returns HTTP 200 with a plausible-looking result set, but every
row's STOCK_CODE is "00362" ("C ZENITH CHEM"), a completely unrelated
company. This is the same bug class as the HK Transport Department scrapers
(see tests/test_hk_transport_scrapers.py): a 200 response with real-looking
data attributed to the wrong entity.

The fix resolves each ticker to HKEXnews' internal numeric stockId via the
prefix.do autocomplete endpoint first, and then -- as a non-negotiable final
guard -- drops any row whose own STOCK_CODE does not match the ticker that
was requested, rather than trusting the servlet's filtering.

These tests exercise that guard directly (via the internal row-filtering
logic) both positively (a real, live fetch for an active ticker must return
only matching rows) and negatively (a deliberately mismatched STOCK_CODE row
must be dropped, not kept).
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pandas as pd
import pytest

from src.hk_stablecoin_crypto.config import WATCHLIST
from src.hk_stablecoin_crypto.sources.hkexnews_announcements import (
    SCHEMA_COLUMNS,
    _normalize_code,
    all_watchlist_tickers,
    fetch_hkexnews_announcements,
    fetch_ticker_announcements,
)


def test_normalize_code_strips_suffix_and_leading_zeros():
    assert _normalize_code("00863.HK") == "863"
    assert _normalize_code("00700.hk") == "700"
    assert _normalize_code("700") == "700"
    assert _normalize_code("00005") == "5"


def test_all_watchlist_tickers_covers_full_watchlist():
    tickers = all_watchlist_tickers()
    expected_count = sum(len(v) for v in WATCHLIST.values())
    assert len(tickers) == expected_count
    assert "00863.HK" in tickers  # OSL Group, TIER_1
    assert "00434.HK" in tickers  # Boyaa Interactive, TIER_4


# --- Positive test: real, live fetch for an active watchlist ticker --------


def test_fetch_ticker_announcements_returns_only_matching_rows_for_osl():
    """OSL Group (00863.HK) is TIER_1 and actively trading/reporting. Every
    row returned must genuinely belong to stock code 863 -- this is the
    exact guard that would have caught the Tencent/C-Zenith-Chem
    misattribution bug."""
    df = fetch_ticker_announcements("00863.HK", lookback_days=180)
    assert list(df.columns) == SCHEMA_COLUMNS
    assert not df.empty, "expected at least one real announcement for OSL Group in the last 180 days"

    assert (df["ticker"] == "00863.HK").all()
    for stock_code in df["stock_code"]:
        assert _normalize_code(stock_code) == "863", (
            f"row claims to be for 00863.HK but its own STOCK_CODE is {stock_code!r} -- "
            "this is the misattribution bug this test guards against"
        )


def test_fetch_ticker_announcements_returns_only_matching_rows_for_tencent():
    """Cross-check against a second, unrelated ticker (Tencent, 00700.HK --
    not itself in the watchlist, but the exact ticker used to discover the
    original bug) to confirm the fix isn't coincidentally correct for one
    stock only."""
    df = fetch_ticker_announcements("00700.HK", lookback_days=180)
    assert not df.empty
    assert (df["ticker"] == "00700.HK").all()
    for stock_code in df["stock_code"]:
        assert _normalize_code(stock_code) == "700"
    # Guard against the specific historical failure mode.
    assert not any("362" == _normalize_code(c) for c in df["stock_code"])


# --- Negative test: mismatched STOCK_CODE rows must be dropped -------------


def _fake_prefix_response(stock_id: int, code: str, name: str) -> str:
    payload = {"more": "0", "stockInfo": [{"stockId": stock_id, "code": code, "name": name}]}
    return f"callback({json.dumps(payload)});"


class _FakeResponse:
    def __init__(self, *, text: str | None = None, json_body: dict | None = None, url: str = ""):
        self._text = text
        self._json_body = json_body
        self.url = url

    @property
    def text(self):
        return self._text

    def json(self):
        return self._json_body

    def raise_for_status(self):
        return None


def test_mismatched_stock_code_rows_are_dropped_not_kept():
    """Simulate the exact failure mode observed live: the servlet ignores the
    resolved stockId and returns rows for a different company entirely.
    The fetch must filter these out rather than silently keeping them."""

    ticker = "00700.HK"  # Tencent

    servlet_result_rows = [
        {
            "STOCK_CODE": "00362",  # wrong company -- must be dropped
            "STOCK_NAME": "C ZENITH CHEM",
            "NEWS_ID": "999999",
            "TITLE": "Monthly Returns",
            "SHORT_TEXT": "Monthly Returns",
            "DATE_TIME": "02/07/2026 10:02",
            "FILE_LINK": "/some/wrong/path.pdf",
            "FILE_TYPE": "PDF",
        },
        {
            "STOCK_CODE": "00700<br/>80700",  # correct, dual-listing style code -- must be kept
            "STOCK_NAME": "TENCENT",
            "NEWS_ID": "111111",
            "TITLE": "Next Day Disclosure Return",
            "SHORT_TEXT": "Next Day Disclosure Return",
            "DATE_TIME": "09/07/2026 17:58",
            "FILE_LINK": "/some/right/path.pdf",
            "FILE_TYPE": "PDF",
        },
    ]
    servlet_outer = {
        "result": json.dumps(servlet_result_rows),
        "hasNextRow": False,
        "recordCnt": 2,
    }

    def fake_get(url, params=None, headers=None, timeout=None):
        if "prefix.do" in url:
            return _FakeResponse(text=_fake_prefix_response(7609, "00700", "TENCENT"))
        if "titleSearchServlet.do" in url:
            return _FakeResponse(json_body=servlet_outer, url=url)
        raise AssertionError(f"unexpected URL requested: {url}")

    with patch("src.hk_stablecoin_crypto.sources.hkexnews_announcements.requests.get", side_effect=fake_get), \
         patch("src.hk_stablecoin_crypto.sources.hkexnews_announcements.save_raw_snapshot"):
        df = fetch_ticker_announcements(ticker)

    assert len(df) == 1, "exactly one of the two rows matches the requested ticker and should survive"
    assert df.iloc[0]["news_id"] == "111111"
    assert df.iloc[0]["stock_code"] == "00700"
    assert not (df["news_id"] == "999999").any(), "the C ZENITH CHEM row must be dropped, not kept"


def test_combined_fetch_tags_every_row_with_its_own_requested_ticker():
    """fetch_hkexnews_announcements combines multiple tickers -- confirm rows
    from one ticker's fetch never get tagged with another ticker's label."""

    def fake_fetch(ticker, lookback_days=90):
        bare = _normalize_code(ticker)
        return pd.DataFrame([{
            "ticker": ticker,
            "stock_code": bare,
            "stock_name": "TEST",
            "news_id": f"news-{bare}",
            "title": "Test announcement",
            "short_text": "Test announcement",
            "date_time": "01/08/2026 09:00",
            "file_link": "/test.pdf",
            "file_type": "PDF",
            "fetched_at": "2026-08-01T00:00:00+00:00",
        }])[SCHEMA_COLUMNS]

    with patch(
        "src.hk_stablecoin_crypto.sources.hkexnews_announcements.fetch_ticker_announcements",
        side_effect=fake_fetch,
    ), patch("src.hk_stablecoin_crypto.sources.hkexnews_announcements.save_raw_snapshot"):
        df = fetch_hkexnews_announcements(["00863.HK", "00700.HK"])

    assert set(df["ticker"]) == {"00863.HK", "00700.HK"}
    for _, row in df.iterrows():
        assert _normalize_code(row["ticker"]) == row["stock_code"]
