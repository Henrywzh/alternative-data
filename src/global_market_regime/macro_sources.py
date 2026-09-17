"""Macro tab sources: commodity futures proxies and monthly inflation prints."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .config import HISTORY_START, INFLATION_SERIES, MACRO_COMMODITY_ASSETS, REPO_ROOT
from .sources import safe_error_message
from .storage import utc_now


def fetch_macro_commodity_prices(
    *,
    start: str | None = None,
    end: str | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Fetch Yahoo Finance front-month futures / ETF proxies for the Macro tab.

    These are not LBMA/EIA spot prints. Partial success is allowed.
    """
    from market_monitor.sources.yfinance import fetch_daily

    start = start or HISTORY_START
    retrieved_at = utc_now()
    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for spec in MACRO_COMMODITY_ASSETS:
        symbol = str(spec["symbol"])
        try:
            frame = fetch_daily(symbol, start_date=start, end_date=end)
        except Exception as exc:
            errors[str(spec["asset_id"])] = safe_error_message(exc)
            continue
        if frame is None or frame.empty or "close" not in frame.columns:
            errors[str(spec["asset_id"])] = f"{symbol} returned no rows."
            continue
        subset = frame.copy()
        subset["date"] = pd.to_datetime(subset["date"], errors="coerce")
        subset["close"] = pd.to_numeric(subset["close"], errors="coerce")
        subset = subset.dropna(subset=["date", "close"])
        if subset.empty:
            errors[str(spec["asset_id"])] = f"{symbol} returned no usable closes."
            continue
        for row in subset.to_dict("records"):
            rows.append(
                {
                    "date": row["date"],
                    "asset_id": spec["asset_id"],
                    "symbol": symbol,
                    "label_en": spec["label_en"],
                    "label_zh": spec["label_zh"],
                    "group": spec["group"],
                    "unit": spec["unit"],
                    "close": float(row["close"]),
                    "source": "yahoo_finance",
                    "retrieved_at": retrieved_at,
                }
            )
    out = pd.DataFrame(rows)
    if not out.empty:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")
        out = (
            out.dropna(subset=["date", "asset_id", "close"])
            .sort_values(["asset_id", "date"], kind="mergesort")
            .drop_duplicates(["asset_id", "date"], keep="last")
            .reset_index(drop=True)
        )
    return out, errors


def fetch_inflation_observations(
    *,
    start: str | None = None,
    client=None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Fetch the monthly PCE / income / spending panel used by the Macro tab."""
    from fred_macro_data.client import FredMacroClient
    from fred_macro_data.config import resolve_api_key

    fred = client or FredMacroClient(api_key=resolve_api_key(REPO_ROOT))
    credential = str(getattr(fred, "api_key", "") or "")
    retrieved_at = utc_now()
    rows: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    observation_start = start or "2015-01-01"
    for spec in INFLATION_SERIES:
        series_id = spec["series_id"]
        try:
            observations = fred.get_observations(series_id, observation_start=observation_start)
        except Exception as exc:
            errors[series_id] = safe_error_message(exc, secrets=(credential,))
            continue
        values = [point for point in observations if getattr(point, "value", None) is not None]
        if not values:
            errors[series_id] = "No observations returned."
            continue
        for point in values:
            rows.append(
                {
                    "date": point.date,
                    "series_id": series_id,
                    "indicator_id": spec["indicator_id"],
                    "label_en": spec["label_en"],
                    "label_zh": spec["label_zh"],
                    "unit": spec["unit"],
                    "display": spec["display"],
                    "value": point.value,
                    "source": spec["source"],
                    "retrieved_at": retrieved_at,
                }
            )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
        frame = (
            frame.dropna(subset=["date", "indicator_id", "value"])
            .sort_values(["indicator_id", "date"], kind="mergesort")
            .drop_duplicates(["indicator_id", "date"], keep="last")
            .reset_index(drop=True)
        )
    return frame, errors
