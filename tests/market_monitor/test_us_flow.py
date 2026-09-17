from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from market_monitor.sources.us_etf_snapshot import fetch_us_etf_size_snapshot
from market_monitor.us_flow import build_us_proxy_flow


def _snapshot(date: str, price: float, market_cap: float, ticker: str = "SPY") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observation_date": date,
                "ticker": ticker,
                "last_price": price,
                "market_cap": market_cap,
            }
        ]
    )


def test_us_proxy_flow_requires_two_observations() -> None:
    row = build_us_proxy_flow(_snapshot("2026-09-15", 100.0, 1_000.0), None).iloc[0]
    assert row["shares_basis"] == "market_cap_proxy"
    assert row["size_basis"] == "market_cap_proxy"
    assert row["flow_status"] == "insufficient_history"
    assert pd.isna(row["estimated_flow"])


def test_us_proxy_flow_uses_same_moment_market_cap_and_price() -> None:
    previous = _snapshot("2026-09-14", 100.0, 1_000.0)
    current = _snapshot("2026-09-15", 110.0, 1_210.0)
    row = build_us_proxy_flow(current, previous).iloc[0]
    assert row["shares_outstanding"] == pytest.approx(11.0)
    assert row["shares_change"] == pytest.approx(1.0)
    assert row["estimated_flow"] == pytest.approx(110.0)
    assert row["flow_status"] == "validated_proxy"
    assert row["observation_gap_days"] == 1


def test_us_proxy_flow_rejects_repeated_or_stale_observations() -> None:
    previous = _snapshot("2026-09-15", 100.0, 1_000.0)
    repeated = build_us_proxy_flow(_snapshot("2026-09-15", 110.0, 1_210.0), previous).iloc[0]
    stale = build_us_proxy_flow(_snapshot("2026-09-14", 110.0, 1_210.0), previous).iloc[0]
    assert repeated["flow_status"] == "unavailable"
    assert pd.isna(repeated["estimated_flow"])
    assert stale["flow_status"] == "unavailable"
    assert pd.isna(stale["estimated_flow"])


def test_us_proxy_flow_handles_multiple_tickers_and_normalizes_ids() -> None:
    previous = pd.concat(
        [
            _snapshot("2026-09-14", 100.0, 1_000.0, "spy"),
            _snapshot("2026-09-14", 50.0, 500.0, "QQQ"),
        ],
        ignore_index=True,
    )
    current = pd.concat(
        [
            _snapshot("2026-09-15", 110.0, 1_210.0, "SPY"),
            _snapshot("2026-09-15", 55.0, 550.0, "qqq"),
        ],
        ignore_index=True,
    )
    result = build_us_proxy_flow(current, previous).set_index("ticker")
    assert set(result.index) == {"SPY", "QQQ"}
    assert result.loc["SPY", "estimated_flow"] == pytest.approx(110.0)
    assert result.loc["QQQ", "estimated_flow"] == pytest.approx(0.0)


def test_us_proxy_flow_empty_input_preserves_contract_columns() -> None:
    result = build_us_proxy_flow(pd.DataFrame(), None)
    assert result.empty
    assert {"ticker", "estimated_flow", "flow_status", "shares_basis"} <= set(result.columns)


def test_us_snapshot_sampler_fails_closed_and_reports_missing_tickers(monkeypatch) -> None:
    class _Ticker:
        def __init__(self, ticker: str) -> None:
            self.fast_info = (
                {
                    "last_price": 500.0,
                    "market_cap": 450_000.0,
                    "last_trade_time": 1_758_844_800,
                }
                if ticker == "SPY"
                else {"last_price": 0.0, "market_cap": 100.0, "last_trade_time": 1_758_844_800}
            )

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=_Ticker))
    frame = fetch_us_etf_size_snapshot(["spy", "QQQ"])
    assert list(frame["ticker"]) == ["SPY"]
    assert frame.iloc[0]["market_cap"] == pytest.approx(450_000.0)
    assert frame.attrs["requested_tickers"] == ["SPY", "QQQ"]
    assert frame.attrs["missing_tickers"] == ["QQQ"]


def test_us_snapshot_supports_current_yfinance_etf_quote_shape(monkeypatch) -> None:
    class _Ticker:
        def __init__(self, ticker: str) -> None:
            self.fast_info = {
                "lastPrice": 100.0,
                "marketCap": None,
            }
            self.info = {
                "sharesOutstanding": 12_000.0,
                "regularMarketTime": 1_789_416_000,
            }

    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=_Ticker))
    frame = fetch_us_etf_size_snapshot(["SPY"])
    assert list(frame["ticker"]) == ["SPY"]
    assert frame.iloc[0]["last_price"] == pytest.approx(100.0)
    assert frame.iloc[0]["market_cap"] == pytest.approx(1_200_000.0)
    assert frame.iloc[0]["observation_date"] == "2026-09-14"
