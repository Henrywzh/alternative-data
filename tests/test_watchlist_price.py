"""Tests for the HK Stablecoin & Crypto watchlist live price/volume source.

Mirrors the mocking style used elsewhere in this repo for akshare-backed
sources (e.g. tests/test_minerals_market_data.py): akshare is imported
locally inside each fetch function (see reit_price.py / watchlist_price.py),
so tests monkeypatch `sys.modules["akshare"]` with a fake module before
calling the fetch function, rather than patching an attribute on an
already-imported module.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timezone

import pandas as pd
import pytest

from src.hk_stablecoin_crypto.config import WATCHLIST
from src.hk_stablecoin_crypto.sources.watchlist_price import (
    all_watchlist_tickers,
    fetch_watchlist_price_history,
    fetch_watchlist_spot_quotes,
)


def _install_fake_akshare(monkeypatch, *, spot_df=None, hist_by_symbol=None, spot_raises=None):
    """Install a fake `akshare` module in sys.modules so `import akshare as ak`
    inside the fetch functions picks it up."""
    fake_ak = types.SimpleNamespace()

    def _stock_hk_spot_em():
        if spot_raises is not None:
            raise spot_raises
        return spot_df if spot_df is not None else pd.DataFrame()

    def _stock_hk_hist(symbol, period, start_date, end_date, adjust):
        hist_by_symbol_ = hist_by_symbol or {}
        return hist_by_symbol_.get(symbol, pd.DataFrame())

    fake_ak.stock_hk_spot_em = _stock_hk_spot_em
    fake_ak.stock_hk_hist = _stock_hk_hist
    monkeypatch.setitem(sys.modules, "akshare", fake_ak)
    return fake_ak


def _spot_row(code, price, change_pct, volume, turnover):
    return {
        "代码": code,
        "名称": "irrelevant",
        "最新价": price,
        "涨跌幅": change_pct,
        "成交量": volume,
        "成交额": turnover,
    }


# --- all_watchlist_tickers() -------------------------------------------------


def test_all_watchlist_tickers_covers_full_watchlist_with_bare_codes_and_names():
    entries = all_watchlist_tickers()
    expected_count = sum(len(v) for v in WATCHLIST.values())
    assert len(entries) == expected_count

    by_code = {e["code"]: e for e in entries}
    assert "00863" in by_code
    assert by_code["00863"]["ticker"] == "00863.HK"
    assert by_code["00863"]["company_name"] == "OSL Group"
    assert by_code["00863"]["tier"] == 1

    assert "00005" in by_code
    assert by_code["00005"]["company_name"] == "HSBC Holdings"
    assert by_code["00005"]["tier"] == 2


# --- fetch_watchlist_spot_quotes() ------------------------------------------


def test_fetch_watchlist_spot_quotes_empty_akshare_response_returns_empty_df(monkeypatch):
    _install_fake_akshare(monkeypatch, spot_df=pd.DataFrame())
    df = fetch_watchlist_spot_quotes()
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_fetch_watchlist_spot_quotes_akshare_raises_returns_empty_df(monkeypatch):
    _install_fake_akshare(monkeypatch, spot_raises=RuntimeError("upstream unavailable"))
    df = fetch_watchlist_spot_quotes()
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_fetch_watchlist_spot_quotes_missing_watchlist_tickers_returns_empty_df(monkeypatch):
    # Spot snapshot has real rows, but none of them are watchlist tickers.
    spot_df = pd.DataFrame(
        [
            _spot_row("00001", 50.0, 1.2, 1_000_000, 50_000_000),
            _spot_row("00002", 60.0, -0.5, 500_000, 30_000_000),
        ]
    )
    monkeypatch.setattr(pd.DataFrame, "to_json", pd.DataFrame.to_json, raising=False)
    _install_fake_akshare(monkeypatch, spot_df=spot_df)
    monkeypatch.setattr(
        "src.hk_stablecoin_crypto.sources.watchlist_price.save_raw_snapshot",
        lambda *args, **kwargs: "/raw/snapshot.json",
    )

    df = fetch_watchlist_spot_quotes()
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_fetch_watchlist_spot_quotes_correct_tier_and_company_name_attachment(monkeypatch):
    spot_df = pd.DataFrame(
        [
            _spot_row("00001", 999.0, 9.9, 999, 999),  # not in watchlist -- must be filtered out
            _spot_row("00863", 12.5, 3.2, 2_000_000, 25_000_000),  # OSL Group, TIER_1
            _spot_row("00005", 65.4, -0.8, 10_000_000, 654_000_000),  # HSBC, TIER_2
        ]
    )
    _install_fake_akshare(monkeypatch, spot_df=spot_df)
    monkeypatch.setattr(
        "src.hk_stablecoin_crypto.sources.watchlist_price.save_raw_snapshot",
        lambda *args, **kwargs: "/raw/snapshot.json",
    )

    df = fetch_watchlist_spot_quotes()

    assert list(df.columns) == [
        "date",
        "ticker",
        "company_name",
        "tier",
        "latest_price_hkd",
        "change_pct",
        "volume",
        "turnover_hkd",
        "fetched_at",
    ]
    # Only the two watchlist rows should survive the filter.
    assert len(df) == 2
    assert set(df["ticker"]) == {"00863", "00005"}

    by_ticker = df.set_index("ticker")
    assert by_ticker.loc["00863", "company_name"] == "OSL Group"
    assert int(by_ticker.loc["00863", "tier"]) == 1
    assert by_ticker.loc["00863", "latest_price_hkd"] == 12.5

    assert by_ticker.loc["00005", "company_name"] == "HSBC Holdings"
    assert int(by_ticker.loc["00005", "tier"]) == 2
    assert by_ticker.loc["00005", "latest_price_hkd"] == 65.4


def test_fetch_watchlist_spot_quotes_fetched_at_present_on_every_row(monkeypatch):
    spot_df = pd.DataFrame(
        [
            _spot_row("00863", 12.5, 3.2, 2_000_000, 25_000_000),
            _spot_row("03887", 8.1, -1.1, 1_500_000, 12_000_000),
        ]
    )
    _install_fake_akshare(monkeypatch, spot_df=spot_df)
    monkeypatch.setattr(
        "src.hk_stablecoin_crypto.sources.watchlist_price.save_raw_snapshot",
        lambda *args, **kwargs: "/raw/snapshot.json",
    )

    before = datetime.now(timezone.utc)
    df = fetch_watchlist_spot_quotes()
    after = datetime.now(timezone.utc)

    assert not df.empty
    assert df["fetched_at"].notna().all()
    for value in df["fetched_at"]:
        parsed = datetime.fromisoformat(value)
        assert before <= parsed <= after


# --- fetch_watchlist_price_history() ----------------------------------------


def test_fetch_watchlist_price_history_empty_akshare_response_returns_empty_df(monkeypatch):
    _install_fake_akshare(monkeypatch, hist_by_symbol={})
    df = fetch_watchlist_price_history(lookback_days=30)
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_fetch_watchlist_price_history_skips_failing_tickers_without_raising(monkeypatch):
    fake_ak = _install_fake_akshare(monkeypatch, hist_by_symbol={})

    def _stock_hk_hist(symbol, period, start_date, end_date, adjust):
        if symbol == "00863":
            raise RuntimeError("upstream error for this ticker only")
        return pd.DataFrame()

    fake_ak.stock_hk_hist = _stock_hk_hist

    df = fetch_watchlist_price_history(lookback_days=30)
    assert isinstance(df, pd.DataFrame)
    assert df.empty


def test_fetch_watchlist_price_history_correct_columns_and_company_name(monkeypatch):
    hist_df = pd.DataFrame(
        {
            "日期": ["2026-07-30", "2026-07-31"],
            "开盘": [12.0, 12.3],
            "最高": [12.5, 12.6],
            "最低": [11.8, 12.1],
            "收盘": [12.3, 12.5],
            "成交量": [1_000_000, 1_200_000],
        }
    )
    _install_fake_akshare(monkeypatch, hist_by_symbol={"00863": hist_df})
    monkeypatch.setattr(
        "src.hk_stablecoin_crypto.sources.watchlist_price.save_raw_snapshot",
        lambda *args, **kwargs: "/raw/snapshot.json",
    )

    df = fetch_watchlist_price_history(lookback_days=30)

    assert list(df.columns) == [
        "date",
        "ticker",
        "company_name",
        "open_hkd",
        "high_hkd",
        "low_hkd",
        "close_hkd",
        "volume",
    ]
    assert (df["ticker"] == "00863").all()
    assert (df["company_name"] == "OSL Group").all()
    assert len(df) == 2
