"""Pure derivation functions and constants for ETF heat maps and return snapshots."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

RETURN_WINDOWS: dict[str, int] = {
    "1d": 1,
    "1w": 5,
    "1m": 20,
    "3m": 63,
    "1y": 252,
}


def _session_return(closes: pd.Series, sessions: int) -> float | None:
    """Return compounded percentage return over the given session window."""
    if len(closes) <= sessions:
        return None
    prior = float(closes.iloc[-sessions - 1])
    latest = float(closes.iloc[-1])
    if prior <= 0 or latest <= 0:
        return None
    return (latest / prior - 1.0) * 100.0


def _clean_prices(prices: pd.DataFrame) -> pd.DataFrame:
    """Clean, filter positive closes, deduplicate and sort price history."""
    if prices is None or prices.empty:
        return pd.DataFrame(columns=["date", "ticker", "close"])
    required = {"date", "ticker", "close"}
    if not required.issubset(prices.columns):
        return pd.DataFrame(columns=["date", "ticker", "close"])

    frame = prices.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["ticker"] = frame["ticker"].astype(str).str.strip().str.upper()
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")

    frame = (
        frame.dropna(subset=["date", "ticker", "close"])
        .loc[lambda df: df["close"].gt(0)]
        .sort_values(["ticker", "date"], kind="mergesort")
        .drop_duplicates(["ticker", "date"], keep="last")
        .reset_index(drop=True)
    )
    return frame


def build_return_snapshot(
    prices: pd.DataFrame,
    universe: Sequence[Mapping[str, Any]],
    *,
    as_of: str | None = None,
) -> pd.DataFrame:
    """Build a return snapshot DataFrame across standard windows for each universe member.

    Consumes daily prices and a universe sequence. Preserves missing/short histories as null.
    """
    cleaned = _clean_prices(prices)
    as_of_ts = pd.to_datetime(as_of) if as_of is not None else None

    if as_of_ts is not None and not cleaned.empty:
        cleaned = cleaned[cleaned["date"] <= as_of_ts]

    if as_of is not None:
        effective_as_of_str = str(as_of)
    elif not cleaned.empty:
        effective_as_of_str = cleaned["date"].max().strftime("%Y-%m-%d")
    else:
        effective_as_of_str = None

    rows: list[dict[str, Any]] = []
    grouped = dict(tuple(cleaned.groupby("ticker", sort=False))) if not cleaned.empty else {}

    for item in universe:
        row: dict[str, Any] = dict(item)
        ticker = str(item.get("ticker", "")).strip().upper()
        ticker_data = grouped.get(ticker)

        row["as_of"] = effective_as_of_str

        if ticker_data is not None and not ticker_data.empty:
            closes = ticker_data["close"]
            latest_price = float(closes.iloc[-1])
            latest_date_ts = ticker_data["date"].iloc[-1]

            row["latest_price"] = latest_price

            for window_name, session_count in RETURN_WINDOWS.items():
                field_name = f"return_{window_name}_pct"
                row[field_name] = _session_return(closes, session_count)

            # Calendar YTD return: from the last close before Jan 1 of latest_date's year
            current_year = latest_date_ts.year
            year_start = pd.Timestamp(year=current_year, month=1, day=1)
            prior_year_rows = ticker_data[ticker_data["date"] < year_start]
            if not prior_year_rows.empty:
                ytd_base = float(prior_year_rows["close"].iloc[-1])
                if ytd_base > 0:
                    row["return_ytd_pct"] = (latest_price / ytd_base - 1.0) * 100.0
                else:
                    row["return_ytd_pct"] = None
            else:
                row["return_ytd_pct"] = None
        else:
            row["latest_price"] = None
            for window_name in RETURN_WINDOWS:
                row[f"return_{window_name}_pct"] = None
            row["return_ytd_pct"] = None

        rows.append(row)

    return pd.DataFrame(rows)
