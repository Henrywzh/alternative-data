from __future__ import annotations

from pathlib import Path
import sys
_APP_ROOT = Path(__file__).resolve().parent.parent / "apps" / "research-control-tower"
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

import pandas as pd

from src.research_control_tower.quote_collector import (
    collect_yfinance_quotes,
    write_quote_snapshot,
)
from control_tower.market_data import (
    classify_quote_freshness,
    format_quote_age,
)


def _sample_listings() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "listing_id": "9988_HK",
            "entity_id": "ALIBABA",
            "canonical_ticker": "9988.HK",
            "native_ticker": "9988",
            "vendor_tickers": "yfinance:9988.HK;hkex:9988",
            "collection_eligible": True,
            "mapping_status": "verified",
            "listing_status": "active",
            "currency": "HKD",
            "registry_version": "v1",
        },
        {
            "listing_id": "BABA_US",
            "entity_id": "ALIBABA",
            "canonical_ticker": "BABA.US",
            "native_ticker": "BABA",
            "vendor_tickers": "yfinance:BABA;nyse:BABA",
            "collection_eligible": True,
            "mapping_status": "verified",
            "listing_status": "active",
            "currency": "USD",
            "registry_version": "v1",
        },
        {
            "listing_id": "0700_HK",
            "entity_id": "TENCENT",
            "canonical_ticker": "0700.HK",
            "native_ticker": "0700",
            "vendor_tickers": "yfinance:0700.HK;hkex:0700",
            "collection_eligible": True,
            "mapping_status": "verified",
            "listing_status": "active",
            "currency": "HKD",
            "registry_version": "v1",
        },
        {
            "listing_id": "DUPE_1",
            "entity_id": "COMPANY_A",
            "canonical_ticker": "DUPE.US",
            "native_ticker": "DUPE",
            "vendor_tickers": "yfinance:SHARED_SYM",
            "collection_eligible": True,
            "mapping_status": "verified",
            "listing_status": "active",
            "currency": "USD",
            "registry_version": "v1",
        },
        {
            "listing_id": "DUPE_2",
            "entity_id": "COMPANY_B",
            "canonical_ticker": "DUPE2.US",
            "native_ticker": "DUPE2",
            "vendor_tickers": "yfinance:SHARED_SYM",
            "collection_eligible": True,
            "mapping_status": "verified",
            "listing_status": "active",
            "currency": "USD",
            "registry_version": "v1",
        },
        {
            "listing_id": "UNMAPPED",
            "entity_id": "NO_SYM",
            "canonical_ticker": "NOPE.US",
            "native_ticker": "NOPE",
            "vendor_tickers": "",
            "collection_eligible": True,
            "mapping_status": "verified",
            "listing_status": "active",
            "currency": "USD",
            "registry_version": "v1",
        },
    ])


def _sample_entities() -> pd.DataFrame:
    return pd.DataFrame([
        {"entity_id": "ALIBABA", "entity_type": "public", "display_name": "Alibaba"},
        {"entity_id": "TENCENT", "entity_type": "public", "display_name": "Tencent"},
        {"entity_id": "BYTEDANCE", "entity_type": "private", "display_name": "ByteDance"},
    ])


def _fake_dual_download(symbols, **kwargs):
    assert "SHARED_SYM" not in symbols, "Duplicate vendor symbol should be excluded"
    index = pd.DatetimeIndex(["2026-08-13T11:59:00Z"], tz="UTC")
    columns = pd.MultiIndex.from_tuples([
        ("9988.HK", "Close"),
        ("9988.HK", "Volume"),
        ("9988.HK", "Previous Close"),
        ("BABA", "Close"),
        ("BABA", "Volume"),
        ("BABA", "Previous Close"),
        ("0700.HK", "Close"),
        ("0700.HK", "Volume"),
    ])
    return pd.DataFrame(
        [[120.0, 50000.0, 118.0, 125.0, 10000.0, 120.0, 440.0, 30000.0]],
        index=index,
        columns=columns,
    )


def test_collect_yfinance_quotes_hk_us_dual_listings_and_defensible_day_change() -> None:
    frame = collect_yfinance_quotes(
        _sample_listings(),
        entities=_sample_entities(),
        as_of_utc="2026-08-13T12:00:00Z",
        download_fn=_fake_dual_download,
        stage1_only=False,
    )

    listing_ids = set(frame["listing_id"])
    assert "9988_HK" in listing_ids
    assert "BABA_US" in listing_ids
    assert "0700_HK" in listing_ids
    assert "DUPE_1" not in listing_ids
    assert "DUPE_2" not in listing_ids
    assert "UNMAPPED" not in listing_ids

    baba_hk = frame.loc[frame["listing_id"] == "9988_HK"].iloc[0]
    assert baba_hk["currency"] == "HKD"
    assert baba_hk["last_price"] == 120.0
    # Day change = (120 - 118) / 118 * 100 = +1.6949%
    assert abs(baba_hk["day_change_pct"] - 1.6949) < 0.001

    baba_us = frame.loc[frame["listing_id"] == "BABA_US"].iloc[0]
    assert baba_us["currency"] == "USD"
    assert baba_us["last_price"] == 125.0
    # Day change = (125 - 120) / 120 * 100 = +4.1667%
    assert abs(baba_us["day_change_pct"] - 4.1667) < 0.001

    # 0700.HK had no Previous Close column in mock, so day_change_pct must be pd.NA (unavailable)
    tencent = frame.loc[frame["listing_id"] == "0700_HK"].iloc[0]
    assert pd.isna(tencent["day_change_pct"])


def test_private_entity_bytedance_is_never_queried() -> None:
    entities = _sample_entities()
    listings = _sample_listings()
    # Adding ByteDance fake listing if any
    bytedance_listing = pd.DataFrame([{
        "listing_id": "BYTEDANCE_PRIVATE",
        "entity_id": "BYTEDANCE",
        "canonical_ticker": "BYTEDANCE",
        "native_ticker": "BYTEDANCE",
        "vendor_tickers": "yfinance:BYTEDANCE",
        "collection_eligible": True,
        "mapping_status": "verified",
        "listing_status": "active",
        "currency": "USD",
        "registry_version": "v1",
    }])
    combined_listings = pd.concat([listings, bytedance_listing], ignore_index=True)

    queried_symbols = []
    def spy_download(symbols, **kwargs):
        queried_symbols.extend(symbols)
        return pd.DataFrame()

    frame = collect_yfinance_quotes(
        combined_listings,
        entities=entities,
        as_of_utc="2026-08-13T12:00:00Z",
        download_fn=spy_download,
        stage1_only=False,
    )

    assert "BYTEDANCE" not in queried_symbols
    assert "BYTEDANCE_PRIVATE" not in set(frame["listing_id"]) if not frame.empty else True


def test_quote_freshness_classification_stale_quotes_and_age_label() -> None:
    as_of = pd.Timestamp("2026-08-13T12:00:00Z")

    # Fresh delayed quote within 24h
    fresh_ts = pd.Timestamp("2026-08-13T10:00:00Z")
    assert classify_quote_freshness(fresh_ts, as_of, latency_class="delayed") == "delayed"
    assert format_quote_age(fresh_ts, as_of) == "2h ago"

    # Stale quote > 24h
    stale_ts = pd.Timestamp("2026-08-11T12:00:00Z")
    assert classify_quote_freshness(stale_ts, as_of, latency_class="delayed") == "stale"
    assert format_quote_age(stale_ts, as_of) == "2d ago"

    # Future quote
    future_ts = pd.Timestamp("2026-08-14T12:00:00Z")
    assert classify_quote_freshness(future_ts, as_of, latency_class="delayed") == "unavailable"
    assert format_quote_age(future_ts, as_of) == "future timestamp"


def test_no_data_failures_handled_gracefully() -> None:
    def empty_download(symbols, **kwargs):
        return pd.DataFrame()

    frame = collect_yfinance_quotes(
        _sample_listings(),
        as_of_utc="2026-08-13T12:00:00Z",
        download_fn=empty_download,
    )
    assert frame.empty
    assert list(frame.columns) == [
        "quote_id", "listing_id", "canonical_ticker", "provider_symbol",
        "quote_timestamp", "retrieved_at_utc", "last_price", "bid", "ask",
        "day_change_pct", "volume", "currency", "market_status", "latency_class",
        "source_id", "source_url", "pit_class", "source_license_class", "registry_version"
    ]


def test_write_quote_snapshot_atomic(tmp_path: Path) -> None:
    frame = collect_yfinance_quotes(
        _sample_listings(),
        as_of_utc="2026-08-13T12:00:00Z",
        download_fn=_fake_dual_download,
        stage1_only=False,
    )
    out_file = tmp_path / "quote_snapshots.parquet"
    written = write_quote_snapshot(frame, out_file)
    assert written.exists()
    loaded = pd.read_parquet(written)
    assert len(loaded) == len(frame)
