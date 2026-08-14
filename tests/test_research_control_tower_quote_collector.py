from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.research_control_tower.quote_collector import (
    collect_yfinance_quotes,
    write_quote_snapshot,
)


def _listings() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "listing_id": "NVDA_US",
            "canonical_ticker": "NVDA.US",
            "native_ticker": "NVDA",
            "vendor_tickers": "yfinance:NVDA;nasdaq:NVDA",
            "collection_eligible": True,
            "mapping_status": "verified",
            "listing_status": "active",
            "currency": "USD",
            "registry_version": "v1",
        },
        {
            "listing_id": "2330_TW",
            "canonical_ticker": "2330.TW",
            "native_ticker": "2330",
            "vendor_tickers": "yfinance:2330.TW;twse:2330",
            "collection_eligible": True,
            "mapping_status": "verified",
            "listing_status": "active",
            "currency": "TWD",
            "registry_version": "v1",
        },
        {
            "listing_id": "UNMAPPED",
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


def _fake_download(symbols, **kwargs):
    assert symbols == ["2330.TW", "NVDA"]
    assert kwargs["interval"] == "1m"
    index = pd.DatetimeIndex(
        ["2026-08-13T11:58:00Z", "2026-08-13T11:59:00Z"],
        tz="UTC",
    )
    columns = pd.MultiIndex.from_tuples([
        ("2330.TW", "Close"),
        ("2330.TW", "Volume"),
        ("NVDA", "Close"),
        ("NVDA", "Volume"),
    ])
    return pd.DataFrame(
        [
            [900.0, 100.0, 123.0, 200.0],
            [901.0, 110.0, 124.0, 210.0],
        ],
        index=index,
        columns=columns,
    )


def test_collect_yfinance_quotes_maps_registry_symbols_and_labels_delayed() -> None:
    frame = collect_yfinance_quotes(
        _listings(),
        as_of_utc="2026-08-13T12:00:00Z",
        download_fn=_fake_download,
    )

    assert set(frame["listing_id"]) == {"NVDA_US", "2330_TW"}
    assert set(frame["provider_symbol"]) == {"NVDA", "2330.TW"}
    assert set(frame["last_price"]) == {124.0, 901.0}
    assert frame["latency_class"].eq("delayed").all()
    assert frame["quote_timestamp"].max() == pd.Timestamp("2026-08-13T11:59:00Z")
    assert frame["retrieved_at_utc"].eq(pd.Timestamp("2026-08-13T12:00:00Z")).all()
    assert frame["source_id"].eq("market:yfinance").all()


def test_write_quote_snapshot_preserves_contract(tmp_path: Path) -> None:
    frame = collect_yfinance_quotes(
        _listings(),
        as_of_utc="2026-08-13T12:00:00Z",
        download_fn=_fake_download,
    )
    path = write_quote_snapshot(frame, tmp_path / "quotes.parquet")
    loaded = pd.read_parquet(path)

    assert path.exists()
    assert list(loaded.columns) == list(frame.columns)
    assert len(loaded) == 2
