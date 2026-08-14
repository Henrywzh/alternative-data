"""Focused tests for the pure functional market_data module."""

from __future__ import annotations

from pathlib import Path
import sys

_APP_ROOT = Path(__file__).resolve().parent.parent / "apps" / "research-control-tower"
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

import pandas as pd
import pytest

from control_tower.market_data import (
    MARKET_BARS_COLUMNS,
    QUOTE_SNAPSHOT_COLUMNS,
    build_listing_crosswalk,
    classify_quote_freshness,
    normalize_market_bars,
    normalize_quote_snapshots,
    resolve_listing_identity,
)


@pytest.fixture
def sample_listings() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "listing_id": "L_NVDA",
            "canonical_ticker": "NVDA",
            "financial_data_security_id": "SEC_NVDA_123",
            "native_ticker": "NVDA",
        },
        {
            "listing_id": "L_TSMC_TW",
            "canonical_ticker": "2330.TW",
            "financial_data_security_id": "SEC_2330_TW",
            "native_ticker": "2330",
        },
    ])


def test_build_listing_crosswalk_and_resolution(sample_listings: pd.DataFrame) -> None:
    crosswalk = build_listing_crosswalk(sample_listings)
    assert "L_NVDA" in crosswalk
    assert "SEC_NVDA_123" in crosswalk
    assert "NVDA" in crosswalk
    assert "2330" in crosswalk

    # Test direct listing_id resolution
    lid, ctick = resolve_listing_identity({"listing_id": "L_NVDA"}, crosswalk)
    assert lid == "L_NVDA" and ctick == "NVDA"

    # Test security_id resolution
    lid, ctick = resolve_listing_identity({"security_id": "SEC_NVDA_123"}, crosswalk)
    assert lid == "L_NVDA" and ctick == "NVDA"

    # Test ticker resolution
    lid, ctick = resolve_listing_identity({"ticker": "2330.TW"}, crosswalk)
    assert lid == "L_TSMC_TW" and ctick == "2330.TW"

    # Test unmapped resolution
    lid, ctick = resolve_listing_identity({"ticker": "UNKNOWN"}, crosswalk)
    assert lid is None and ctick == ""


def test_classify_quote_freshness() -> None:
    as_of = pd.Timestamp("2026-08-14T12:00:00Z")

    # 30 seconds old with realtime latency class -> live
    q_live = pd.Timestamp("2026-08-14T11:59:30Z")
    assert classify_quote_freshness(q_live, as_of, latency_class="realtime") == "live"

    # The two-minute live boundary is inclusive; older realtime data is delayed.
    q_live_boundary = pd.Timestamp("2026-08-14T11:58:00Z")
    assert classify_quote_freshness(q_live_boundary, as_of, latency_class="realtime") == "live"
    q_delayed_boundary = pd.Timestamp("2026-08-14T11:57:59Z")
    assert classify_quote_freshness(q_delayed_boundary, as_of, latency_class="realtime") == "delayed"

    # 1 hour old with realtime latency class -> delayed
    q_delayed1 = pd.Timestamp("2026-08-14T11:00:00Z")
    assert classify_quote_freshness(q_delayed1, as_of, latency_class="realtime") == "delayed"

    # 1 hour old with delayed latency class -> delayed
    assert classify_quote_freshness(q_delayed1, as_of, latency_class="delayed") == "delayed"

    # 48 hours old -> stale
    q_stale = pd.Timestamp("2026-08-12T12:00:00Z")
    assert classify_quote_freshness(q_stale, as_of, latency_class="realtime") == "stale"

    # Future quote timestamp relative to as_of -> unavailable
    q_future = pd.Timestamp("2026-08-14T13:00:00Z")
    assert classify_quote_freshness(q_future, as_of) == "unavailable"

    # Missing / NaT timestamp -> unavailable
    assert classify_quote_freshness(None, as_of) == "unavailable"
    assert classify_quote_freshness(pd.NaT, as_of) == "unavailable"
    assert classify_quote_freshness(q_live, as_of, latency_class="unknown") == "unavailable"


def test_normalize_market_bars_mapped_and_unmapped(sample_listings: pd.DataFrame) -> None:
    as_of = pd.Timestamp("2026-08-14T18:00:00Z")
    raw_input = [
        {
            "listing_id": "L_NVDA",
            "timestamp": "2026-08-14T00:00:00Z",
            "open": 120.0,
            "high": 125.0,
            "low": 119.5,
            "close": 124.0,
            "volume": 1000000,
        },
        {
            "ticker": "UNKNOWN_CO",
            "timestamp": "2026-08-14T00:00:00Z",
            "close": 50.0,
        },
    ]

    res = normalize_market_bars(raw_input, sample_listings, as_of_utc=as_of)
    assert res.valid_count == 1
    assert res.unmapped_count == 1
    assert res.future_count == 0
    assert len(res.frame) == 1
    assert res.frame.iloc[0]["listing_id"] == "L_NVDA"
    assert res.frame.iloc[0]["canonical_ticker"] == "NVDA"
    assert res.frame.iloc[0]["close"] == 124.0
    assert any("failed listing crosswalk" in issue for issue in res.issues)


def test_normalize_market_bars_future_and_nan_rejection(sample_listings: pd.DataFrame) -> None:
    as_of = pd.Timestamp("2026-08-14T18:00:00Z")
    raw_input = [
        {
            "security_id": "SEC_NVDA_123",
            "timestamp": "2026-08-15T00:00:00Z",  # Future timestamp relative to as_of
            "close": 130.0,
        },
        {
            "listing_id": "L_NVDA",
            "timestamp": "2026-08-14T00:00:00Z",
            "close": float("nan"),  # Invalid close price
        },
    ]

    res = normalize_market_bars(raw_input, sample_listings, as_of_utc=as_of)
    assert res.valid_count == 0
    assert res.future_count == 1
    assert res.invalid_count == 1
    assert res.frame.empty
    assert list(res.frame.columns) == list(MARKET_BARS_COLUMNS)


def test_normalize_quote_snapshots_mapped_freshness_and_unmapped(sample_listings: pd.DataFrame) -> None:
    as_of = pd.Timestamp("2026-08-14T18:00:00Z")
    raw_input = [
        {
            "security_id": "SEC_NVDA_123",
            "quote_timestamp": "2026-08-14T17:50:00Z",
            "last_price": 124.5,
            "bid": 124.4,
            "ask": 124.6,
            "day_change_pct": 1.25,
            "currency": "USD",
            "latency_class": "realtime",
        },
        {
            "native_ticker": "2330",
            "quote_timestamp": "2026-08-14T06:00:00Z",
            "last_price": 950.0,
            "currency": "TWD",
            "latency_class": "delayed",
        },
        {
            "ticker": "UNMAPPED_SP",
            "quote_timestamp": "2026-08-14T17:00:00Z",
            "last_price": 10.0,
        },
    ]

    res = normalize_quote_snapshots(raw_input, sample_listings, as_of_utc=as_of)
    assert res.valid_count == 2
    assert res.unmapped_count == 1
    assert len(res.frame) == 2
    assert set(res.frame["listing_id"]) == {"L_NVDA", "L_TSMC_TW"}

    # Verify latest NVDA quote freshness classification
    nvda_row = res.frame.loc[res.frame["listing_id"].eq("L_NVDA")].iloc[0]
    freshness = classify_quote_freshness(nvda_row["quote_timestamp"], as_of, nvda_row["latency_class"])
    assert freshness == "delayed"


def test_conflicting_identifiers_are_removed_and_explicit_identity_fails_closed(
    sample_listings: pd.DataFrame,
) -> None:
    conflicting = pd.concat([
        sample_listings,
        pd.DataFrame([{
            "listing_id": "L_DUPLICATE",
            "canonical_ticker": "NVDA",
            "financial_data_security_id": "SEC_DUPLICATE",
            "native_ticker": "NVDA.US",
        }]),
    ], ignore_index=True)

    crosswalk = build_listing_crosswalk(conflicting)
    assert "NVDA" not in crosswalk
    assert "L_NVDA" in crosswalk
    assert "L_DUPLICATE" in crosswalk
    assert "SEC_NVDA_123" in crosswalk
    assert "SEC_DUPLICATE" in crosswalk

    # An explicit unknown listing_id must not be remapped by its ticker.
    assert resolve_listing_identity(
        {"listing_id": "L_REMOVED", "ticker": "2330.TW"},
        build_listing_crosswalk(sample_listings),
    ) == (None, "")


def test_market_bars_dedupe_prefers_real_retrieval_and_keeps_zero_adj_close(
    sample_listings: pd.DataFrame,
) -> None:
    as_of = pd.Timestamp("2026-08-14T18:00:00Z")
    res = normalize_market_bars([
        {
            "listing_id": "L_NVDA",
            "timestamp": "2026-08-14T17:00:00Z",
            "close": 100.0,
            "adj_close": 0.0,
            "source_id": "missing-retrieval",
        },
        {
            "listing_id": "L_NVDA",
            "timestamp": "2026-08-14T17:00:00Z",
            "close": 101.0,
            "retrieved_at_utc": "2026-08-14T17:59:00Z",
            "source_id": "real-retrieval",
        },
    ], sample_listings, as_of_utc=as_of)

    assert res.valid_count == 1
    assert res.dropped_duplicate_count == 1
    row = res.frame.iloc[0]
    assert row["close"] == 101.0
    assert row["retrieved_at_utc"] == pd.Timestamp("2026-08-14T17:59:00Z")
    assert any("duplicate bar" in issue for issue in res.issues)
    assert any("no retrieved timestamp" in issue for issue in res.issues)


def test_quote_dedupe_prefers_latest_retrieval_and_preserves_falsey_values(
    sample_listings: pd.DataFrame,
) -> None:
    as_of = pd.Timestamp("2026-08-14T18:00:00Z")
    res = normalize_quote_snapshots([
        {
            "listing_id": "L_NVDA",
            "quote_timestamp": "2026-08-14T17:59:00Z",
            "retrieved_at_utc": "2026-08-14T17:59:05Z",
            "last_price": 100.0,
            "day_change_pct": 2.0,
            "latency_class": "realtime",
        },
        {
            "listing_id": "L_NVDA",
            "quote_timestamp": "2026-08-14T17:59:00Z",
            "retrieved_at_utc": "2026-08-14T17:59:30Z",
            "last_price": 0.0,
            "close": 999.0,
            "day_change_pct": 0.0,
            "change_pct": 7.0,
            "latency_class": "realtime",
        },
    ], sample_listings, as_of_utc=as_of)

    assert res.valid_count == 1
    assert res.dropped_duplicate_count == 1
    row = res.frame.iloc[0]
    assert row["last_price"] == 0.0
    assert row["day_change_pct"] == 0.0
    assert row["retrieved_at_utc"] == pd.Timestamp("2026-08-14T17:59:30Z")


def test_future_retrieval_is_rejected_and_empty_frames_are_typed(
    sample_listings: pd.DataFrame,
) -> None:
    as_of = pd.Timestamp("2026-08-14T18:00:00Z")
    bars = normalize_market_bars([
        {
            "listing_id": "L_NVDA",
            "timestamp": "2026-08-14T17:00:00Z",
            "retrieved_at_utc": "2026-08-14T18:00:01Z",
            "close": 100.0,
        },
        {
            "listing_id": "L_NVDA",
            "timestamp": "2026-08-14T17:01:00Z",
            "close": float("inf"),
        },
    ], sample_listings, as_of_utc=as_of)
    quotes = normalize_quote_snapshots([], sample_listings, as_of_utc=as_of)

    assert bars.valid_count == 0
    assert bars.future_count == 1
    assert bars.invalid_count == 1
    assert bars.frame["timestamp_utc"].dtype == "datetime64[ns, UTC]"
    assert bars.frame["close"].dtype == "Float64"
    assert bars.frame["listing_id"].dtype == "string"
    assert quotes.frame["quote_timestamp"].dtype == "datetime64[ns, UTC]"
    assert quotes.frame["last_price"].dtype == "Float64"
    assert quotes.frame["listing_id"].dtype == "string"


def test_intraday_fallback_bar_ids_are_unique(sample_listings: pd.DataFrame) -> None:
    as_of = pd.Timestamp("2026-08-14T18:00:00Z")
    res = normalize_market_bars([
        {
            "listing_id": "L_NVDA",
            "interval": "5m",
            "timestamp": "2026-08-14T17:00:00Z",
            "close": 100.0,
        },
        {
            "listing_id": "L_NVDA",
            "interval": "5m",
            "timestamp": "2026-08-14T17:05:00Z",
            "close": 101.0,
        },
    ], sample_listings, as_of_utc=as_of)

    assert res.valid_count == 2
    assert res.frame["bar_id"].nunique() == 2
