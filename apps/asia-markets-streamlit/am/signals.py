"""Shared latest-reading helpers used across sector pages."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .core import add_date_column


def latest_period_signal(
    frame: pd.DataFrame,
    date_field: str,
    value_field: str,
    *,
    aggregation: str = "sum",
    change_mode: str = "pct",
) -> dict[str, Any]:
    """Return the latest monthly reading and its same-month-prior-year change."""
    if frame.empty or date_field not in frame.columns or value_field not in frame.columns:
        return {"value": None, "change": None, "date": None}
    output = add_date_column(frame, date_field)
    if output.empty:
        return {"value": None, "change": None, "date": None}
    output["_signal_value"] = pd.to_numeric(output[value_field], errors="coerce")
    output = output.dropna(subset=["_signal_value"])
    if output.empty:
        return {"value": None, "change": None, "date": None}
    grouped = output.groupby("_date")["_signal_value"]
    values = grouped.mean() if aggregation == "mean" else grouped.sum(min_count=1)
    values = values.dropna().sort_index()
    if values.empty:
        return {"value": None, "change": None, "date": None}
    latest_date = values.index.max()
    latest_value = float(values.loc[latest_date])
    prior_period = latest_date.to_period("M") - 12
    prior_values = values[values.index.to_period("M") == prior_period]
    prior_value = float(prior_values.iloc[-1]) if not prior_values.empty else None
    if prior_value is None:
        change = None
    elif change_mode == "delta":
        change = latest_value - prior_value
    elif prior_value == 0:
        change = None
    else:
        change = (latest_value / prior_value - 1) * 100
    return {"value": latest_value, "change": change, "date": latest_date}


def latest_daily_signal(frame: pd.DataFrame, value_field: str) -> dict[str, Any]:
    """Return the latest daily value without applying a monthly comparison."""
    if frame.empty or value_field not in frame.columns or "date" not in frame.columns:
        return {"value": None, "date": None, "classification": None}
    output = add_date_column(frame, "date")
    output["_signal_value"] = pd.to_numeric(output[value_field], errors="coerce")
    output = output.dropna(subset=["_signal_value"]).sort_values("_date")
    if output.empty:
        return {"value": None, "date": None, "classification": None}
    row = output.iloc[-1]
    return {
        "value": float(row["_signal_value"]),
        "date": row["_date"],
        "classification": row.get("classification"),
    }
