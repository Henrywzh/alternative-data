"""Fail-closed post-close size snapshots for the US ETF heat-map universe."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Sequence

import pandas as pd


def _value(info: Any, *names: str) -> Any:
    """Read a fast_info value without assuming whether it is dict-like."""
    for name in names:
        try:
            value = info.get(name) if hasattr(info, "get") else info[name]
        except (KeyError, TypeError, AttributeError):
            continue
        if value is not None:
            return value
    return None


def _observation_date(value: Any) -> str | None:
    """Normalize yfinance's last-trade timestamp to a provider session date."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            timestamp = pd.to_datetime(value, unit="s", utc=True, errors="coerce")
        else:
            timestamp = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(timestamp):
            return None
        return timestamp.strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError):
        return None


def fetch_us_etf_size_snapshot(tickers: Sequence[str]) -> pd.DataFrame:
    """Fetch one co-timed price/market-cap row per requested US ETF.

    The function deliberately fails closed.  A ticker is omitted unless the
    provider supplies a positive price, positive market cap, and an explicit
    last-trade timestamp.  Missing tickers are exposed through DataFrame
    attributes so the caller can report partial coverage without inventing
    zero-sized funds.
    """
    import yfinance as yf

    requested = []
    for ticker in tickers:
        normalized = str(ticker).strip().upper()
        if normalized and normalized not in requested:
            requested.append(normalized)

    retrieved_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for ticker in requested:
        try:
            info = yf.Ticker(ticker).fast_info
            price = pd.to_numeric(_value(info, "last_price", "regularMarketPrice"), errors="coerce")
            market_cap = pd.to_numeric(_value(info, "market_cap", "marketCap"), errors="coerce")
            observation_date = _observation_date(
                _value(info, "last_trade_time", "regularMarketTime", "last_trade_date")
            )
            if (
                pd.isna(price)
                or pd.isna(market_cap)
                or float(price) <= 0
                or float(market_cap) <= 0
                or observation_date is None
            ):
                missing.append(ticker)
                continue
            rows.append(
                {
                    "observation_date": observation_date,
                    "ticker": ticker,
                    "last_price": float(price),
                    "market_cap": float(market_cap),
                    "source": "Yahoo Finance fast_info",
                    "source_observed_date": observation_date,
                    "retrieved_at_utc": retrieved_at,
                    "observation_type": "provider_post_close_snapshot",
                }
            )
        except Exception:  # noqa: BLE001 - one provider failure must not erase peers
            missing.append(ticker)

    frame = pd.DataFrame(rows)
    frame.attrs["requested_tickers"] = requested
    frame.attrs["missing_tickers"] = missing
    return frame
