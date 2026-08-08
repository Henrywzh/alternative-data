"""Historical financial trend layer from the free A-share discovery feed.

This is intentionally separate from the primary Cninfo report-driver layer.
The provider feed contains long historical financial abstracts, but does not
expose issuer announcement dates.  It is therefore useful for trend and cycle
context, not for a strict announcement-date point-in-time backtest.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR


INPUT_PATH = NORMALIZED_DIR / "airline_financial_actuals_akshare_snapshot.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_financial_history_trend.csv"
DEFAULT_START_DATE = "2016-01-01"

OUTPUT_COLUMNS = [
    "dataset_id", "ticker", "company", "market", "statement_period",
    "period_type", "period_end", "metric", "provider_metric",
    "value_native", "native_unit", "native_currency", "value_usd", "usd_unit",
    "fx_pair", "fx_observation_date", "fx_value", "source_quality",
    "announcement_date_available", "point_in_time_status", "as_of_date",
    "source_url", "source_note", "retrieved_at",
]


def _period_type(statement_period: str) -> str:
    suffix = str(statement_period)[-2:]
    return {
        "03": "Q1_or_1Q",
        "06": "H1_or_2Q",
        "09": "Q3_or_9M",
        "12": "FY",
    }.get(suffix, "other")


def build_airline_financial_history(
    actuals: pd.DataFrame | None = None,
    *,
    start_date: str = DEFAULT_START_DATE,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    source = actuals if actuals is not None else pd.read_csv(INPUT_PATH)
    required = {
        "ticker", "company", "statement_period", "period_end", "metric",
        "provider_metric", "value_native", "native_unit", "native_currency",
        "value_usd", "usd_unit", "fx_pair", "fx_observation_date", "fx_value",
        "source_quality", "announcement_date_available", "source_url",
        "source_note", "retrieved_at",
    }
    missing = required.difference(source.columns)
    if missing:
        raise ValueError(f"financial actuals are missing columns: {sorted(missing)}")
    frame = source.copy()
    frame["period_end"] = pd.to_datetime(frame["period_end"], errors="coerce")
    start = pd.Timestamp(start_date)
    frame = frame.loc[frame["period_end"].ge(start)].copy()
    frame = frame.dropna(subset=["period_end", "value_native"])
    frame["period_end"] = frame["period_end"].dt.strftime("%Y-%m-%d")
    frame["period_type"] = frame["statement_period"].map(_period_type)
    frame["market"] = "CN_A"
    frame["dataset_id"] = "airline_financial_history_trend"
    frame["point_in_time_status"] = "period_end_only_no_announcement_date"
    frame["as_of_date"] = frame["period_end"]
    frame["source_quality"] = "akshare_discovery_historical"
    frame["source_note"] = frame["source_note"].astype(str) + (
        " Historical trend view filtered from the provider actuals archive; "
        "issuer announcement date is unavailable and must be reconciled to primary filings."
    )
    frame["retrieved_at"] = retrieved_at or datetime.now(timezone.utc).isoformat()
    return frame[OUTPUT_COLUMNS].sort_values(
        ["company", "period_end", "metric"]
    ).reset_index(drop=True)


def fetch_airline_financial_history(*, start_date: str = DEFAULT_START_DATE) -> pd.DataFrame:
    result = build_airline_financial_history(start_date=start_date)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
