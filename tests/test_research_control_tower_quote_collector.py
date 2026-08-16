from __future__ import annotations

from pathlib import Path
import sys

_APP_ROOT = Path(__file__).resolve().parent.parent / "apps" / "research-control-tower"
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

import pandas as pd
import pytest

from src.research_control_tower.quote_collector import (
    QuoteCollectionResult,
    QuoteDiagnostic,
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
            "active_from": "2026-01-01",
            "active_to": None,
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
            "active_from": "2026-01-01",
            "active_to": None,
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
            "active_from": "2026-01-01",
            "active_to": None,
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
            "active_from": "2026-01-01",
            "active_to": None,
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
            "active_from": "2026-01-01",
            "active_to": None,
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
            "active_from": "2026-01-01",
            "active_to": None,
            "registry_version": "v1",
        },
    ])


def _sample_entities() -> pd.DataFrame:
    return pd.DataFrame([
        {"entity_id": "ALIBABA", "entity_type": "public", "active_status": "active", "display_name": "Alibaba", "active_from": "2026-01-01", "active_to": None},
        {"entity_id": "TENCENT", "entity_type": "public", "active_status": "active", "display_name": "Tencent", "active_from": "2026-01-01", "active_to": None},
        {"entity_id": "BYTEDANCE", "entity_type": "private", "active_status": "active", "display_name": "ByteDance", "active_from": "2026-01-01", "active_to": None},
    ])


def _sample_memberships() -> pd.DataFrame:
    return pd.DataFrame([
        {"basket_id": "RESEARCH_STAGE_1_CHINA_INTERNET", "entity_id": "ALIBABA", "membership_tier": "core", "active_from": "2026-01-01", "active_to": None},
        {"basket_id": "RESEARCH_STAGE_1_CHINA_INTERNET", "entity_id": "TENCENT", "membership_tier": "core", "active_from": "2026-01-01", "active_to": None},
        {"basket_id": "RESEARCH_STAGE_1_CHINA_INTERNET", "entity_id": "BYTEDANCE", "membership_tier": "watch_only", "active_from": "2026-01-01", "active_to": None},
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


def test_collect_yfinance_quotes_hk_us_dual_listings_and_diagnostics() -> None:
    res = collect_yfinance_quotes(
        _sample_listings(),
        entities=_sample_entities(),
        basket_memberships=_sample_memberships(),
        as_of_utc="2026-08-13T12:00:00Z",
        download_fn=_fake_dual_download,
        stage1_only=True,
    )

    assert isinstance(res, QuoteCollectionResult)
    assert res.aggregate_status == "available"
    frame = res.frame

    listing_ids = set(frame["listing_id"])
    assert "9988_HK" in listing_ids
    assert "BABA_US" in listing_ids
    assert "0700_HK" in listing_ids

    # Licensing assertion
    assert frame["source_license_class"].eq("personal_use_terms_unverified").all()

    # Defensible day change calculation
    baba_hk = frame.loc[frame["listing_id"] == "9988_HK"].iloc[0]
    assert baba_hk["currency"] == "HKD"
    assert baba_hk["last_price"] == 120.0
    assert abs(baba_hk["day_change_pct"] - 1.6949) < 0.001

    # Missing previous close in mock results in pd.NA
    tencent = frame.loc[frame["listing_id"] == "0700_HK"].iloc[0]
    assert pd.isna(tencent["day_change_pct"])

    # Verify per-symbol diagnostics
    diag_map = {d.listing_id: d for d in res.symbol_diagnostics if d.listing_id}
    assert diag_map["9988_HK"].status == "available"
    assert diag_map["BABA_US"].status == "available"
    assert diag_map["0700_HK"].status == "available"


def test_private_entity_bytedance_is_excluded_from_query() -> None:
    entities = _sample_entities()
    listings = _sample_listings()
    memberships = _sample_memberships()

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
        "active_from": "2026-01-01",
        "active_to": None,
        "registry_version": "v1",
    }])
    combined_listings = pd.concat([listings, bytedance_listing], ignore_index=True)

    queried_symbols = []
    def spy_download(symbols, **kwargs):
        queried_symbols.extend(symbols)
        return pd.DataFrame()

    res = collect_yfinance_quotes(
        combined_listings,
        entities=entities,
        basket_memberships=memberships,
        as_of_utc="2026-08-13T12:00:00Z",
        download_fn=spy_download,
        stage1_only=True,
    )

    assert "BYTEDANCE" not in queried_symbols
    private_diags = [d for d in res.symbol_diagnostics if d.entity_id == "BYTEDANCE"]
    assert len(private_diags) >= 1
    assert private_diags[0].status == "excluded_private"


def test_realtime_latency_claim_is_rejected() -> None:
    with pytest.raises(ValueError, match="latency_class cannot be 'realtime'"):
        collect_yfinance_quotes(_sample_listings(), latency_class="realtime")


def test_quote_freshness_classification_stale_quotes_and_age_label() -> None:
    as_of = pd.Timestamp("2026-08-13T12:00:00Z")

    fresh_ts = pd.Timestamp("2026-08-13T10:00:00Z")
    assert classify_quote_freshness(fresh_ts, as_of, latency_class="delayed") == "delayed"
    assert format_quote_age(fresh_ts, as_of) == "2h ago"

    stale_ts = pd.Timestamp("2026-08-11T12:00:00Z")
    assert classify_quote_freshness(stale_ts, as_of, latency_class="delayed") == "stale"
    assert format_quote_age(stale_ts, as_of) == "2d ago"

    future_ts = pd.Timestamp("2026-08-14T12:00:00Z")
    assert classify_quote_freshness(future_ts, as_of, latency_class="delayed") == "unavailable"
    assert format_quote_age(future_ts, as_of) == "future timestamp"


def test_no_data_failures_and_partial_diagnostics() -> None:
    def empty_download(symbols, **kwargs):
        return pd.DataFrame()

    res = collect_yfinance_quotes(
        _sample_listings(),
        as_of_utc="2026-08-13T12:00:00Z",
        download_fn=empty_download,
        stage1_only=False,
    )
    assert res.frame.empty
    assert res.aggregate_status in ("no_records", "partial")


def test_write_quote_snapshot_atomic_and_contract(tmp_path: Path) -> None:
    res = collect_yfinance_quotes(
        _sample_listings(),
        as_of_utc="2026-08-13T12:00:00Z",
        download_fn=_fake_dual_download,
        stage1_only=False,
    )
    out_file = tmp_path / "quote_snapshots.parquet"
    written = write_quote_snapshot(res.frame, out_file)
    assert written.exists()
    loaded = pd.read_parquet(written)
    assert len(loaded) == len(res.frame)
