from __future__ import annotations

from pathlib import Path
import json
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
    quote_status_path,
    write_quote_snapshot,
)
from control_tower.market_data import (
    classify_quote_freshness,
    format_quote_age,
)


def _sample_listings() -> pd.DataFrame:
    frame = pd.DataFrame([
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
    frame["exchange"] = frame["canonical_ticker"].map(
        lambda value: "HKEX" if str(value).endswith(".HK") else "NYSE"
    )
    frame["financial_data_security_id"] = [f"security-{index}" for index in range(len(frame))]
    frame["financial_data_issuer_group_id"] = ""
    frame["mapping_verified_at"] = "2026-01-01"
    frame["mapping_source_url"] = "https://example.test/registry/listing"
    frame["listing_role"] = "primary"
    frame["primary_listing"] = True
    frame["source_url"] = "https://example.test/registry/listing"
    frame["source_or_research_note"] = "fixture"
    return frame


def _sample_entities() -> pd.DataFrame:
    frame = pd.DataFrame([
        {"entity_id": "ALIBABA", "entity_type": "public", "active_status": "active", "display_name": "Alibaba", "active_from": "2026-01-01", "active_to": None},
        {"entity_id": "TENCENT", "entity_type": "public", "active_status": "active", "display_name": "Tencent", "active_from": "2026-01-01", "active_to": None},
        {"entity_id": "BYTEDANCE", "entity_type": "private", "active_status": "active", "display_name": "ByteDance", "active_from": "2026-01-01", "active_to": None},
        {"entity_id": "COMPANY_A", "entity_type": "public", "active_status": "active", "display_name": "Company A", "active_from": "2026-01-01", "active_to": None},
        {"entity_id": "COMPANY_B", "entity_type": "public", "active_status": "active", "display_name": "Company B", "active_from": "2026-01-01", "active_to": None},
        {"entity_id": "NO_SYM", "entity_type": "public", "active_status": "active", "display_name": "No symbol", "active_from": "2026-01-01", "active_to": None},
    ])
    frame["legal_name"] = frame["display_name"]
    frame["country"] = "CN"
    frame["sector"] = "Technology"
    frame["industry"] = "Internet"
    frame["registry_version"] = "v1"
    frame["source_or_research_note"] = "fixture"
    return frame


def _sample_baskets() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "basket_id": "RESEARCH_STAGE_1_CHINA_INTERNET",
            "display_name": "Stage 1",
            "purpose": "fixture",
            "active_from": "2026-01-01",
            "active_to": None,
            "registry_version": "v1",
            "source_or_research_note": "fixture",
        }
    ])


def _sample_memberships() -> pd.DataFrame:
    frame = pd.DataFrame([
        {"basket_id": "RESEARCH_STAGE_1_CHINA_INTERNET", "entity_id": "ALIBABA", "membership_tier": "core", "active_from": "2026-01-01", "active_to": None},
        {"basket_id": "RESEARCH_STAGE_1_CHINA_INTERNET", "entity_id": "TENCENT", "membership_tier": "core", "active_from": "2026-01-01", "active_to": None},
        {"basket_id": "RESEARCH_STAGE_1_CHINA_INTERNET", "entity_id": "BYTEDANCE", "membership_tier": "watch_only", "active_from": "2026-01-01", "active_to": None},
    ])
    frame["primary_layer"] = "platforms"
    frame["secondary_layers"] = ""
    frame["membership_reason"] = "fixture"
    frame["source_or_research_note"] = "fixture"
    frame["registry_version"] = "v1"
    return frame


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
        baskets=_sample_baskets(),
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
    assert frame["pit_class"].eq("snapshot_from_delayed_source").all()
    assert frame["latency_class"].eq("delayed").all()
    assert frame["market_status"].eq("unknown").all()

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
        "exchange": "PRIVATE",
        "financial_data_security_id": "security-bytedance",
        "financial_data_issuer_group_id": "",
        "mapping_verified_at": "2026-01-01",
        "mapping_source_url": "https://example.test/registry/bytedance",
        "listing_role": "primary",
        "primary_listing": True,
        "source_url": "https://example.test/registry/bytedance",
        "source_or_research_note": "fixture private listing used to test exclusion",
    }])
    combined_listings = pd.concat([listings, bytedance_listing], ignore_index=True)

    queried_symbols = []
    def spy_download(symbols, **kwargs):
        queried_symbols.extend(symbols)
        return pd.DataFrame()

    res = collect_yfinance_quotes(
        combined_listings,
        entities=entities,
        baskets=_sample_baskets(),
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


def test_stage1_missing_registry_fails_closed_before_provider_call() -> None:
    calls: list[tuple[object, dict]] = []

    def spy_download(symbols, **kwargs):
        calls.append((symbols, kwargs))
        return pd.DataFrame()

    result = collect_yfinance_quotes(
        _sample_listings(),
        entities=None,
        baskets=None,
        basket_memberships=None,
        as_of_utc="2026-08-13T12:00:00Z",
        download_fn=spy_download,
        stage1_only=True,
    )

    assert result.aggregate_status == "unavailable"
    assert result.frame.empty
    assert not calls
    assert any("entities registry is missing" in issue for issue in result.issues)


def test_stage1_malformed_entity_interval_fails_closed_before_provider_call() -> None:
    entities = _sample_entities()
    entities.loc[entities["entity_id"].eq("ALIBABA"), ["entity_type", "active_from"]] = ["unknown", None]
    calls: list[object] = []

    def spy_download(symbols, **kwargs):
        calls.append(symbols)
        return pd.DataFrame()

    result = collect_yfinance_quotes(
        _sample_listings(),
        entities=entities,
        baskets=_sample_baskets(),
        basket_memberships=_sample_memberships(),
        as_of_utc="2026-08-13T12:00:00Z",
        download_fn=spy_download,
        stage1_only=True,
    )

    assert result.aggregate_status == "unavailable"
    assert not calls
    assert any(d.status == "invalid_listing" for d in result.symbol_diagnostics)


def test_stage1_missing_listing_status_fails_closed_before_provider_call() -> None:
    calls: list[object] = []

    def spy_download(symbols, **kwargs):
        calls.append(symbols)
        return pd.DataFrame()

    listings = _sample_listings().drop(columns=["listing_status"])
    result = collect_yfinance_quotes(
        listings,
        entities=_sample_entities(),
        baskets=_sample_baskets(),
        basket_memberships=_sample_memberships(),
        as_of_utc="2026-08-13T12:00:00Z",
        download_fn=spy_download,
        stage1_only=True,
    )

    assert result.aggregate_status == "unavailable"
    assert not calls
    assert any("listings registry missing required columns" in issue for issue in result.issues)


def test_historical_as_of_is_rejected_without_provider_call() -> None:
    calls: list[object] = []

    def spy_download(symbols, **kwargs):
        calls.append(symbols)
        return pd.DataFrame()

    as_of = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=4)
    result = collect_yfinance_quotes(
        _sample_listings(),
        as_of_utc=as_of,
        download_fn=spy_download,
        stage1_only=False,
    )

    assert result.aggregate_status == "unavailable"
    assert not calls
    assert any("Historical as_of_utc" in issue for issue in result.issues)


def test_unsorted_hk_and_us_frames_use_prior_completed_local_session_close() -> None:
    as_of = pd.Timestamp.now(tz="UTC").floor("min")
    listings = _sample_listings().loc[
        lambda frame: frame["listing_id"].isin(["9988_HK", "BABA_US"])
    ].copy()
    hk_session_date = as_of.tz_convert("Asia/Hong_Kong").date()
    us_session_date = as_of.tz_convert("America/New_York").date()
    quote_index = pd.DatetimeIndex([as_of - pd.Timedelta(minutes=1), as_of - pd.Timedelta(minutes=3)])
    quote_columns = pd.MultiIndex.from_tuples([
        ("9988.HK", "Close"), ("9988.HK", "Volume"),
        ("BABA", "Close"), ("BABA", "Volume"),
    ])
    intraday = pd.DataFrame(
        [[120.0, 2.0, 125.0, 3.0], [119.0, 1.0, 124.0, 2.0]],
        index=quote_index,
        columns=quote_columns,
    )
    daily_columns = quote_columns
    daily = pd.DataFrame(
        [[95.0, 10.0, 110.0, 10.0], [99.0, 11.0, 120.0, 11.0], [90.0, 12.0, 120.0, 12.0]],
        index=pd.DatetimeIndex([
            pd.Timestamp(hk_session_date) - pd.Timedelta(days=1),
            pd.Timestamp(hk_session_date),
            pd.Timestamp(hk_session_date) - pd.Timedelta(days=2),
        ]),
        columns=daily_columns,
    )
    calls: list[str] = []

    def download(symbols, **kwargs):
        calls.append(kwargs["interval"])
        return intraday

    def daily_download(symbols, **kwargs):
        calls.append(kwargs["interval"])
        return daily

    result = collect_yfinance_quotes(
        listings,
        as_of_utc=as_of,
        download_fn=download,
        daily_download_fn=daily_download,
        stage1_only=False,
    )

    assert result.aggregate_status == "available"
    assert calls == ["1m", "1d"]
    hk = result.frame.loc[result.frame["listing_id"].eq("9988_HK")].iloc[0]
    us = result.frame.loc[result.frame["listing_id"].eq("BABA_US")].iloc[0]
    assert hk["day_change_pct"] == 26.3158
    assert us["day_change_pct"] == 4.1667
    assert result.frame["quote_timestamp"].is_monotonic_increasing


def test_success_plus_missing_and_ambiguous_listings_is_partial() -> None:
    listings = _sample_listings()
    as_of = pd.Timestamp.now(tz="UTC").floor("min")
    index = pd.DatetimeIndex([as_of - pd.Timedelta(minutes=1)])
    downloaded = pd.DataFrame(
        [[120.0, 100.0]],
        index=index,
        columns=pd.MultiIndex.from_tuples([("9988.HK", "Close"), ("9988.HK", "Volume")]),
    )

    result = collect_yfinance_quotes(
        listings,
        as_of_utc=as_of,
        download_fn=lambda symbols, **kwargs: downloaded,
        stage1_only=False,
    )

    assert result.aggregate_status == "partial"
    assert len(result.frame) == 1
    assert any(d.listing_id == "UNMAPPED" and d.status == "no_records" for d in result.symbol_diagnostics)
    assert any(d.status == "ambiguous_symbol" for d in result.symbol_diagnostics)


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
    sidecar = quote_status_path(written)
    assert sidecar.exists()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    assert payload["schema"] == "quote_collection_status_v1"
    assert payload["row_count"] == len(res.frame)
    loaded = pd.read_parquet(written)
    assert len(loaded) == len(res.frame)
