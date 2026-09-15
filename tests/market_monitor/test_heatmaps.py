from __future__ import annotations

import pandas as pd
import pytest

from market_monitor.heatmaps import build_return_snapshot
from market_monitor.us_etf.universe import HEATMAP_ETFS


def _spy() -> dict[str, str]:
    return {
        "ticker": "SPY",
        "name_en": "SPDR S&P 500 ETF",
        "name_zh": "标普500 ETF",
        "category": "broad_equity",
        "currency": "USD",
    }


def test_heatmap_universe_covers_five_asset_groups() -> None:
    assert {row["category"] for row in HEATMAP_ETFS} == {
        "broad_equity",
        "sector",
        "international",
        "commodity",
        "fixed_income",
    }


def test_heatmap_universe_has_unique_tickers_and_reference_members() -> None:
    tickers = [row["ticker"] for row in HEATMAP_ETFS]
    required = {
        "SPY",
        "QQQ",
        "XLK",
        "EFA",
        "GLD",
        "AGG",
        "IVV",
        "DIA",
        "RSP",
        "MDY",
        "IWM",
        "EEM",
        "SLV",
        "USO",
        "SHY",
        "HYG",
        "LQD",
        "IEF",
    }

    assert len(tickers) == len(set(tickers))
    assert required <= set(tickers)
    assert all(
        {"ticker", "name_en", "name_zh", "category", "currency"} <= row.keys()
        for row in HEATMAP_ETFS
    )


def test_return_snapshot_uses_trading_session_and_calendar_ytd() -> None:
    prices = pd.DataFrame(
        [
            {"date": "2025-12-31", "ticker": "SPY", "close": 100.0},
            {"date": "2026-01-02", "ticker": "SPY", "close": 110.0},
            {"date": "2026-01-05", "ticker": "SPY", "close": 121.0},
        ]
    )

    result = build_return_snapshot(prices, [_spy()], as_of="2026-01-05").iloc[0]

    assert result["as_of"] == "2026-01-05"
    assert result["latest_price"] == pytest.approx(121.0)
    assert result["return_1d_pct"] == pytest.approx(10.0)
    assert result["return_ytd_pct"] == pytest.approx(21.0)
    assert pd.isna(result["return_1m_pct"])


def test_return_snapshot_ytd_is_null_without_prior_year_baseline() -> None:
    prices = pd.DataFrame(
        [
            {"date": "2026-01-02", "ticker": "SPY", "close": 110.0},
            {"date": "2026-01-05", "ticker": "SPY", "close": 121.0},
        ]
    )

    result = build_return_snapshot(prices, [_spy()], as_of="2026-01-05").iloc[0]

    assert result["latest_price"] == pytest.approx(121.0)
    assert result["return_1d_pct"] == pytest.approx(10.0)
    assert pd.isna(result["return_ytd_pct"])


def test_return_snapshot_deduplicates_dates_and_rejects_non_positive_closes() -> None:
    prices = pd.DataFrame(
        [
            {"date": "2026-01-02", "ticker": "SPY", "close": 100.0},
            {"date": "2026-01-02", "ticker": "SPY", "close": 110.0},
            {"date": "2026-01-05", "ticker": "SPY", "close": 0.0},
            {"date": "2026-01-06", "ticker": "SPY", "close": 121.0},
        ]
    )

    result = build_return_snapshot(prices, [_spy()]).iloc[0]

    assert result["latest_price"] == pytest.approx(121.0)
    assert result["return_1d_pct"] == pytest.approx(10.0)


def test_return_snapshot_preserves_nulls_for_missing_or_short_histories() -> None:
    prices = pd.DataFrame(
        [
            {"date": "2026-01-02", "ticker": "SPY", "close": 100.0},
            {"date": "2026-01-05", "ticker": "SPY", "close": 110.0},
            {"date": "2026-01-05", "ticker": "QQQ", "close": 200.0},
        ]
    )
    universe = [_spy(), {**_spy(), "ticker": "QQQ", "name_en": "Invesco QQQ"}]

    result = build_return_snapshot(prices, universe).set_index("ticker")

    assert result.loc["SPY", "return_1d_pct"] == pytest.approx(10.0)
    assert pd.isna(result.loc["SPY", "return_1w_pct"])
    assert result.loc["QQQ", "latest_price"] == pytest.approx(200.0)
    assert pd.isna(result.loc["QQQ", "return_1d_pct"])


def test_return_snapshot_does_not_use_rows_after_as_of() -> None:
    prices = pd.DataFrame(
        [
            {"date": "2026-01-02", "ticker": "SPY", "close": 100.0},
            {"date": "2026-01-05", "ticker": "SPY", "close": 110.0},
            {"date": "2026-01-06", "ticker": "SPY", "close": 121.0},
        ]
    )

    result = build_return_snapshot(prices, [_spy()], as_of="2026-01-05").iloc[0]

    assert result["latest_price"] == pytest.approx(110.0)
    assert result["as_of"] == "2026-01-05"


def test_return_snapshot_handles_empty_prices_and_calculates_all_windows() -> None:
    empty_result = build_return_snapshot(pd.DataFrame(), [_spy()], as_of="2026-01-05")
    assert len(empty_result) == 1
    assert empty_result.iloc[0]["as_of"] == "2026-01-05"
    assert pd.isna(empty_result.iloc[0]["latest_price"])
    assert pd.isna(empty_result.iloc[0]["return_1d_pct"])

    dates = pd.date_range("2024-12-15", periods=280, freq="B").strftime("%Y-%m-%d")
    prices = pd.DataFrame([{"date": d, "ticker": "SPY", "close": 100.0 + i} for i, d in enumerate(dates)])
    full_result = build_return_snapshot(prices, [_spy()]).iloc[0]
    assert not pd.isna(full_result["return_1d_pct"])
    assert not pd.isna(full_result["return_1w_pct"])
    assert not pd.isna(full_result["return_1m_pct"])
    assert not pd.isna(full_result["return_3m_pct"])
    assert not pd.isna(full_result["return_1y_pct"])
    assert not pd.isna(full_result["return_ytd_pct"])
