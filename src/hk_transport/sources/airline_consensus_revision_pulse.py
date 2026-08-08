"""Dated public-sample consensus revision pulses for airline research."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import NORMALIZED_DIR


EVENT_PATH = NORMALIZED_DIR / "airline_consensus_events.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_consensus_revision_pulse.csv"

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "event_date", "estimate_metric",
    "fiscal_year", "public_revision_sample_count", "institution_count",
    "current_value_median_native", "current_value_low_native", "current_value_high_native",
    "prior_value_median_native", "median_change_native", "median_change_pct",
    "up_revision_count", "down_revision_count", "flat_revision_count",
    "latest_source_quality", "source_scope", "source_note", "retrieved_at",
]


def build_airline_consensus_revision_pulse(
    *,
    events: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Aggregate only dated public revision observations, without filling dates."""
    if events is None:
        events = pd.read_csv(EVENT_PATH) if EVENT_PATH.exists() else pd.DataFrame()
    if events.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    source = events.loc[events["event_type"].eq("estimate_revision")].copy()
    if source.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    source["event_date"] = pd.to_datetime(source["event_date"], errors="coerce")
    source["current_value_native"] = pd.to_numeric(source["current_value_native"], errors="coerce")
    source["prior_value_native"] = pd.to_numeric(source["prior_value_native"], errors="coerce")
    source["change_pct"] = pd.to_numeric(source["change_pct"], errors="coerce")
    source = source.dropna(subset=["event_date", "current_value_native", "prior_value_native"])
    if source.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    group_columns = ["company", "ticker", "market", "event_date", "estimate_metric", "fiscal_year"]
    rows: list[dict[str, object]] = []
    for keys, group in source.groupby(group_columns, dropna=False):
        company, ticker, market, event_date, metric, fiscal_year = keys
        current = group["current_value_native"]
        prior = group["prior_value_native"]
        change = current - prior
        rows.append({
            "dataset_id": "airline_consensus_revision_pulse",
            "company": company,
            "ticker": ticker,
            "market": market,
            "event_date": pd.Timestamp(event_date).strftime("%Y-%m-%d"),
            "estimate_metric": metric,
            "fiscal_year": fiscal_year,
            "public_revision_sample_count": int(len(group)),
            "institution_count": int(group["institution"].nunique()),
            "current_value_median_native": float(current.median()),
            "current_value_low_native": float(current.min()),
            "current_value_high_native": float(current.max()),
            "prior_value_median_native": float(prior.median()),
            "median_change_native": float(change.median()),
            "median_change_pct": float(group["change_pct"].median()) if group["change_pct"].notna().any() else None,
            "up_revision_count": int(group["direction"].eq("up").sum()),
            "down_revision_count": int(group["direction"].eq("down").sum()),
            "flat_revision_count": int(group["direction"].eq("flat").sum()),
            "latest_source_quality": ";".join(sorted(set(group["source_quality"].dropna().astype(str)))),
            "source_scope": "dated_public_revision_subset",
            "source_note": (
                "Dated aggregation of public same-institution revision observations. "
                "No missing dates are forward-filled; this is a revision pulse, not a complete consensus vintage."
            ),
            "retrieved_at": retrieved,
        })
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    return result.sort_values(["event_date", "company", "estimate_metric", "fiscal_year"]).reset_index(drop=True)


def fetch_airline_consensus_revision_pulse() -> pd.DataFrame:
    result = build_airline_consensus_revision_pulse()
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
