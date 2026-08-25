"""Southbound individual holdings are listing-generic, not company-hardcoded."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.research_control_tower.southbound_holdings import (
    collect_listing_southbound,
    collect_stage1_southbound,
    hkex_security_code,
    southbound_mart_path,
)


def test_hkex_security_code_is_derived_from_native_ticker():
    assert hkex_security_code("700", "0700.HK") == "00700"
    assert hkex_security_code("0100", "0100.HK") == "00100"
    assert hkex_security_code("2513", "2513.HK") == "02513"
    assert hkex_security_code("", "9988.HK") == "09988"
    assert hkex_security_code("", "") == ""


def test_collect_listing_southbound_labels_rows_without_profile(tmp_path: Path):
    raw = pd.DataFrame(
        [
            {
                "hold_date": "2026-08-21",
                "close": 123.0,
                "day_change_pct": 1.0,
                "holding_shares": 1000,
                "holding_market_value": 123000,
                "holding_share_pct": 0.5,
                "holding_mv_change_1d": 1.0,
                "holding_mv_change_5d": 2.0,
                "holding_mv_change_10d": 3.0,
                "security_code": "00100",
                "source_id": "eastmoney:hsgt_individual",
                "source_url": "https://data.eastmoney.com/hsgt/hsgtV2.html",
                "retrieved_at_utc": "2026-08-24T00:00:00Z",
            }
        ]
    )
    listing = pd.Series(
        {
            "entity_id": "MINIMAX",
            "listing_id": "0100_HK",
            "native_ticker": "0100",
            "canonical_ticker": "0100.HK",
            "exchange": "HKEX",
        }
    )
    result = collect_listing_southbound(listing, fetch_fn=lambda code: raw)
    assert result.status == "available"
    assert result.security_code == "00100"
    assert result.frame.iloc[0]["entity_id"] == "MINIMAX"
    assert result.frame.iloc[0]["listing_id"] == "0100_HK"


def test_stage1_writer_uses_listing_id_filename(tmp_path: Path):
    listings = pd.DataFrame(
        [
            {
                "entity_id": "MINIMAX",
                "listing_id": "0100_HK",
                "native_ticker": "0100",
                "canonical_ticker": "0100.HK",
                "exchange": "HKEX",
            }
        ]
    )
    raw = pd.DataFrame(
        [
            {
                "hold_date": "2026-08-21",
                "close": 347.2,
                "day_change_pct": 11.8,
                "holding_shares": 10,
                "holding_market_value": 3472,
                "holding_share_pct": 0.1,
                "holding_mv_change_1d": 1.0,
                "holding_mv_change_5d": 2.0,
                "holding_mv_change_10d": 3.0,
                "security_code": "00100",
                "source_id": "eastmoney:hsgt_individual",
                "source_url": "https://example.test",
                "retrieved_at_utc": "2026-08-24T00:00:00Z",
            }
        ]
    )
    results = collect_stage1_southbound(listings, repo_root=tmp_path, fetch_fn=lambda code: raw)
    assert results[0].status == "available"
    path = southbound_mart_path(tmp_path, "0100_HK")
    assert path.exists()
    written = pd.read_parquet(path)
    assert written.iloc[0]["canonical_ticker"] == "0100.HK"


def test_company_page_derives_southbound_from_listing_not_profile():
    source = Path('apps/research-control-tower/control_tower/pages/company.py').read_text()
    assert 'def _southbound_spec_from_view' in source
    assert 'hkex_security_code' in source
    assert "f'{listing_id.lower()}_southbound_holdings.parquet'" in source or '{listing_id.lower()}_southbound_holdings.parquet' in source
    overlay = source[source.index('def _southbound_spec_from_view'):source.index('def _load_southbound_holdings')]
    assert 'native_ticker' in overlay

