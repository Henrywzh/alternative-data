"""Strict long-table grain and aligned descriptive transformations."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import SERIES

COLUMNS = ["metric", "date", "value", "unit", "frequency", "scope", "source", "source_url", "retrieved_at", "definition", "release_date", "period_start", "period_end"]


def no_standalone_january(metric: str, date: object) -> bool:
    date = pd.Timestamp(date)
    spec = SERIES[metric]
    return date.year >= 2012 and date.month == 1 and (
        metric in {"industrial_yoy", "retail", "retail_yoy", "production_consumption"}
        or (spec["frequency"] == "M" and spec["scope"] == "ytd")
    )


def missing_months(history: pd.DataFrame, metric: str) -> list[str]:
    """Internal coverage holes only; not pre-inception or unpublished January."""
    spec = SERIES[metric]
    if history.empty or spec["frequency"] != "M" or spec["scope"] == "day":
        return []
    dates = pd.to_datetime(history["date"]).dt.to_period("M")
    return [str(month) for month in pd.period_range(dates.min(), dates.max(), freq="M")
            if month not in set(dates) and not no_standalone_january(metric, month.to_timestamp())]


def observation(metric: str, date: object, value: object, source: str, url: str,
                retrieved_at: str, *, scale: float = 1, definition: str = "",
                release_date: str | None = None) -> dict | None:
    spec = SERIES[metric]
    # PBC archival XLS cells can be strings ending in a non-breaking space.
    # Trim boundary whitespace only; blanks and malformed numbers stay missing.
    number = pd.to_numeric(value.strip() if isinstance(value, str) else value, errors="coerce")
    timestamp = pd.to_datetime(date, errors="coerce")
    if pd.isna(number) or not np.isfinite(number) or pd.isna(timestamp):
        return None
    if timestamp.date() > pd.Timestamp(retrieved_at).date():
        return None
    return dict(metric=metric, date=timestamp.strftime("%Y-%m-%d"), value=float(number) * scale,
                unit=spec["unit"], frequency=spec["frequency"], scope=spec["scope"],
                source=source, source_url=url, retrieved_at=retrieved_at,
                definition=definition or spec["scope"], release_date=release_date)


def clean(rows: list[dict] | pd.DataFrame) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=COLUMNS)
    if frame.empty:
        return frame
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame[frame["metric"].isin(SERIES) & np.isfinite(frame["value"])]
    # Monthly reference dates are month starts; daily fixing dates stay exact.
    monthly = frame["frequency"].eq("M") & frame["scope"].ne("day")
    frame.loc[monthly, "date"] = pd.to_datetime(frame.loc[monthly, "date"]).dt.to_period("M").dt.to_timestamp().dt.strftime("%Y-%m-%d")
    dates = pd.to_datetime(frame["date"])
    # The 2026 published infrastructure series explicitly includes utilities.
    # Migrate prior wrongly labelled rows rather than splice incompatible vintages.
    changed = frame["metric"].eq("infrastructure_investment_yoy") & dates.dt.year.ge(2026)
    frame.loc[changed, "metric"] = "infrastructure_investment_incl_utilities_yoy"
    frame["period_start"] = dates.dt.strftime("%Y-%m-%d")
    frame["period_end"] = dates.dt.strftime("%Y-%m-%d")
    frame.loc[monthly, "period_end"] = dates[monthly].dt.to_period("M").dt.to_timestamp(how="end").dt.strftime("%Y-%m-%d")
    ytd = frame["scope"].eq("ytd")
    frame.loc[ytd, "period_start"] = dates[ytd].dt.strftime("%Y-01-01")
    quarterly = frame["frequency"].eq("Q")
    frame.loc[quarterly, "period_end"] = dates[quarterly].dt.to_period("Q").dt.to_timestamp(how="end").dt.strftime("%Y-%m-%d")
    combined = frame["metric"].isin(["industrial_yoy", "retail", "retail_yoy", "production_consumption"]) & dates.dt.month.eq(2) & dates.dt.year.ge(2012)
    frame.loc[combined, "scope"] = "jan_feb"
    frame.loc[combined, "period_start"] = dates[combined].dt.strftime("%Y-01-01")
    return frame.drop_duplicates(["metric", "date"], keep="last").sort_values(["metric", "date"]).reset_index(drop=True)


def derive(frame: pd.DataFrame, retrieved_at: str) -> pd.DataFrame:
    """Missing months never become adjacent; cumulative YoY is not differenced."""
    if frame.empty:
        return clean([])
    pivot = frame.pivot(index="date", columns="metric", values="value")
    rows: list[dict] = []
    pairs = [
        ("orders_inventory", "pmi_new_orders", "pmi_inventory", 1),
        ("production_consumption", "industrial_yoy", "retail_yoy", 1),
        ("m1_m2", "m1_yoy", "m2_yoy", 1),
        ("tsf_ex_government", "tsf_flow", "tsf_government", 1),
        ("trade_balance", "exports", "imports", 1),
        ("curve_10y_1y", "cgb_10y", "cgb_1y", 100),
    ]
    for out, left, right, multiplier in pairs:
        if left not in pivot or right not in pivot:
            continue
        values = (pivot[left] - pivot[right]) * multiplier
        for date, value in values.dropna().items():
            inputs = frame[(frame["date"] == date) & frame["metric"].isin([left, right])]
            # Preserve the oldest input's capture time; rebuilding is not freshness.
            captured = inputs["retrieved_at"].min()
            row = observation(out, date, value, "derived", "", captured,
                              definition=f"{left} - {right}; multiplier={multiplier}")
            if row:
                rows.append(row)
    for metric in ["exports_yoy", "imports_yoy"]:
        if metric not in pivot or pivot[metric].dropna().empty:
            continue
        values = pivot[metric].dropna()
        values.index = pd.to_datetime(values.index).to_period("M")
        values = values.reindex(pd.period_range(values.index.min(), values.index.max(), freq="M"))
        for period, value in values.rolling(3, min_periods=3).mean().dropna().items():
            date = period.to_timestamp().strftime("%Y-%m-%d")
            inputs = frame[frame["metric"].eq(metric) & frame["date"].between((period - 2).to_timestamp().strftime("%Y-%m-%d"), date)]
            row = observation(metric + "_3m", date, value, "derived", "", inputs["retrieved_at"].min(),
                              definition="Arithmetic average of three published monthly YoY rates; not a 3-month return")
            if row:
                rows.append(row)
    for metric in ["household_loan_balance", "corporate_loan_balance"]:
        if metric not in pivot or pivot[metric].dropna().empty:
            continue
        values = pivot[metric].dropna()
        values.index = pd.to_datetime(values.index).to_period("M")
        values = values.reindex(pd.period_range(values.index.min(), values.index.max(), freq="M"))
        for period, value in values.diff().dropna().items():
            date = period.to_timestamp().strftime("%Y-%m-%d")
            inputs = frame[frame["metric"].eq(metric) & frame["date"].between((period - 1).to_timestamp().strftime("%Y-%m-%d"), date)]
            row = observation(metric.replace("balance", "change"), date, value, "derived", "", inputs["retrieved_at"].min(),
                              definition="Difference of consecutive loan balances; not official new lending, can include revisions/write-offs")
            if row:
                rows.append(row)
    return clean(rows)
