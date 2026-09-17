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
            ticker_obj = yf.Ticker(ticker)
            fast_info = ticker_obj.fast_info
            price = pd.to_numeric(
                _value(fast_info, "last_price", "lastPrice", "regularMarketPrice"),
                errors="coerce",
            )
            market_cap = pd.to_numeric(
                _value(fast_info, "market_cap", "marketCap"),
                errors="coerce",
            )
            observation_value = _value(
                fast_info,
                "last_trade_time",
                "lastTradeTime",
                "regularMarketTime",
                "last_trade_date",
            )

            # yfinance's current FastInfo object does not expose an ETF
            # market cap or trade timestamp consistently.  Fill those fields
            # from the ordinary quote dictionary only when needed; this keeps
            # the fast path cheap while supporting the provider's real
            # camelCase ETF fields.
            quote_info: Any | None = None
            if pd.isna(price) or pd.isna(market_cap) or observation_value is None:
                try:
                    quote_info = ticker_obj.info
                except Exception:  # noqa: BLE001 - fail closed below
                    quote_info = None
            if quote_info is not None:
                if pd.isna(price):
                    price = pd.to_numeric(
                        _value(quote_info, "regularMarketPrice", "lastPrice"),
                        errors="coerce",
                    )
                if pd.isna(market_cap):
                    market_cap = pd.to_numeric(
                        _value(quote_info, "marketCap", "market_cap"),
                        errors="coerce",
                    )
                if observation_value is None:
                    observation_value = _value(
                        quote_info,
                        "regularMarketTime",
                        "lastTradeTime",
                        "last_trade_time",
                    )

                # ETFs often publish shares outstanding but no marketCap in
                # the quote endpoint.  Price × shares is an explicit size
                # proxy and is preferable to dropping an otherwise valid
                # post-close observation.
                if pd.isna(market_cap):
                    shares_outstanding = pd.to_numeric(
                        _value(
                            quote_info,
                            "sharesOutstanding",
                            "shares_outstanding",
                            "shares",
                        ),
                        errors="coerce",
                    )
                    if pd.notna(price) and pd.notna(shares_outstanding):
                        market_cap = price * shares_outstanding

            # Last-trade timestamps are absent from some yfinance quote
            # responses.  A recent daily history index is an allowed provider
            # session-date fallback; if it is unavailable, omit the ticker
            # rather than using the local retrieval date as an observation.
            if observation_value is None:
                try:
                    history = ticker_obj.history(period="5d", interval="1d", auto_adjust=False)
                    if history is not None and not history.empty:
                        observation_value = history.index[-1]
                except Exception:  # noqa: BLE001 - fail closed below
                    observation_value = None
            observation_date = _observation_date(observation_value)
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
