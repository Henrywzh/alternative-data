"""US Treasury curve snapshots for the Regime Fixed Income tab."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .config import TREASURY_CURVE_POINTS, TREASURY_CURVE_SNAPSHOT_LABELS, US10Y_ENTER


CURVE_INDICATOR_IDS = tuple(point["indicator_id"] for point in TREASURY_CURVE_POINTS)


def _iso(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return None
    return stamp.strftime("%Y-%m-%d")


def _clean_yield_history(fred: pd.DataFrame) -> pd.DataFrame:
    if fred is None or fred.empty:
        return pd.DataFrame(columns=["date", "indicator_id", "value"])
    required = {"date", "indicator_id", "value"}
    if not required.issubset(fred.columns):
        return pd.DataFrame(columns=["date", "indicator_id", "value"])
    frame = fred.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame["indicator_id"] = frame["indicator_id"].astype(str)
    return (
        frame.loc[frame["indicator_id"].isin(CURVE_INDICATOR_IDS)]
        .dropna(subset=["date", "indicator_id", "value"])
        .sort_values(["indicator_id", "date"], kind="mergesort")
        .drop_duplicates(["indicator_id", "date"], keep="last")
        .reset_index(drop=True)
    )


def _value_on_or_before(history: pd.DataFrame, asof: pd.Timestamp) -> pd.Series | None:
    eligible = history[history["date"] <= asof]
    if eligible.empty:
        return None
    return eligible.iloc[-1]


def _prior_session(latest: pd.Timestamp, history: pd.DataFrame) -> pd.Timestamp | None:
    earlier = history[history["date"] < latest]["date"]
    if earlier.empty:
        return None
    return pd.Timestamp(earlier.max())


def _week_ago_session(latest: pd.Timestamp, history: pd.DataFrame) -> pd.Timestamp | None:
    cutoff = latest - pd.Timedelta(days=7)
    eligible = history[history["date"] <= cutoff]
    if eligible.empty:
        return None
    return pd.Timestamp(eligible["date"].max())


def _month_ago_session(latest: pd.Timestamp, history: pd.DataFrame) -> pd.Timestamp | None:
    cutoff = latest - pd.DateOffset(months=1)
    eligible = history[history["date"] <= cutoff]
    if eligible.empty:
        return None
    return pd.Timestamp(eligible["date"].max())


def _year_start_session(latest: pd.Timestamp, history: pd.DataFrame) -> pd.Timestamp | None:
    year_start = pd.Timestamp(year=int(latest.year), month=1, day=1)
    eligible = history[(history["date"] >= year_start) & (history["date"] <= latest)]
    if eligible.empty:
        return None
    return pd.Timestamp(eligible["date"].min())


def build_treasury_curve_snapshots(fred: pd.DataFrame) -> pd.DataFrame:
    """Four curve copies: latest, 1W, 1M, and first session of the current year."""
    history = _clean_yield_history(fred)
    if history.empty:
        return pd.DataFrame()
    latest = pd.Timestamp(history["date"].max())
    anchors = {
        "latest": latest,
        "week_ago": _week_ago_session(latest, history),
        "month_ago": _month_ago_session(latest, history),
        "year_start": _year_start_session(latest, history),
    }
    label_map = {item["snapshot_id"]: item for item in TREASURY_CURVE_SNAPSHOT_LABELS}
    rows: list[dict[str, Any]] = []
    for snapshot_id, asof in anchors.items():
        if asof is None:
            continue
        labels = label_map[snapshot_id]
        for point in TREASURY_CURVE_POINTS:
            subset = history[history["indicator_id"].eq(point["indicator_id"])]
            match = _value_on_or_before(subset, asof)
            rows.append(
                {
                    "snapshot_id": snapshot_id,
                    "label_en": labels["label_en"],
                    "label_zh": labels["label_zh"],
                    "as_of": _iso(asof),
                    "indicator_id": point["indicator_id"],
                    "maturity": point["maturity"],
                    "tenor_months": int(point["tenor_months"]),
                    "maturity_en": point["label_en"],
                    "maturity_zh": point["label_zh"],
                    "yield_pct": None if match is None else round(float(match["value"]), 4),
                    "observation_date": None if match is None else _iso(match["date"]),
                }
            )
    return pd.DataFrame(rows)


def build_treasury_yield_changes(fred: pd.DataFrame) -> pd.DataFrame:
    """Latest yield plus 1D / 1W / 1M / YTD bp changes, including curve spreads."""
    history = _clean_yield_history(fred)
    if history.empty:
        return pd.DataFrame()
    latest = pd.Timestamp(history["date"].max())
    prior = _prior_session(latest, history)
    week_ago = _week_ago_session(latest, history)
    month_ago = _month_ago_session(latest, history)
    year_start = _year_start_session(latest, history)

    def _yield_at(indicator_id: str, asof: pd.Timestamp | None) -> float | None:
        if asof is None:
            return None
        subset = history[history["indicator_id"].eq(indicator_id)]
        match = _value_on_or_before(subset, asof)
        if match is None:
            return None
        return float(match["value"])

    def _bp(current: float | None, previous: float | None) -> float | None:
        if current is None or previous is None:
            return None
        return round((current - previous) * 100.0, 1)

    rows: list[dict[str, Any]] = []
    for point in TREASURY_CURVE_POINTS:
        current = _yield_at(point["indicator_id"], latest)
        rows.append(
            {
                "row_kind": "tenor",
                "indicator_id": point["indicator_id"],
                "maturity": point["maturity"],
                "tenor_months": int(point["tenor_months"]),
                "maturity_en": point["label_en"],
                "maturity_zh": point["label_zh"],
                "as_of": _iso(latest),
                "yield_pct": None if current is None else round(current, 4),
                "change_1d_bp": _bp(current, _yield_at(point["indicator_id"], prior)),
                "change_1w_bp": _bp(current, _yield_at(point["indicator_id"], week_ago)),
                "change_1m_bp": _bp(current, _yield_at(point["indicator_id"], month_ago)),
                "change_ytd_bp": _bp(current, _yield_at(point["indicator_id"], year_start)),
                "us10y_vs_threshold_bp": (
                    None
                    if point["indicator_id"] != "us10y" or current is None
                    else round((current - US10Y_ENTER) * 100.0, 1)
                ),
            }
        )

    def _spread(left_id: str, right_id: str, asof: pd.Timestamp | None) -> float | None:
        left = _yield_at(left_id, asof)
        right = _yield_at(right_id, asof)
        if left is None or right is None:
            return None
        return left - right

    spreads = (
        {
            "indicator_id": "us10y_us2y",
            "maturity": "10Y-2Y",
            "tenor_months": 120,
            "maturity_en": "10Y - 2Y",
            "maturity_zh": "10年-2年",
            "left": "us10y",
            "right": "us2y",
        },
        {
            "indicator_id": "us10y_us3m",
            "maturity": "10Y-3M",
            "tenor_months": 120,
            "maturity_en": "10Y - 3M",
            "maturity_zh": "10年-3个月",
            "left": "us10y",
            "right": "us3m",
        },
    )
    for spec in spreads:
        current = _spread(spec["left"], spec["right"], latest)
        rows.append(
            {
                "row_kind": "spread",
                "indicator_id": spec["indicator_id"],
                "maturity": spec["maturity"],
                "tenor_months": int(spec["tenor_months"]),
                "maturity_en": spec["maturity_en"],
                "maturity_zh": spec["maturity_zh"],
                "as_of": _iso(latest),
                "yield_pct": None if current is None else round(current * 100.0, 1),
                "change_1d_bp": _bp(current, _spread(spec["left"], spec["right"], prior)),
                "change_1w_bp": _bp(current, _spread(spec["left"], spec["right"], week_ago)),
                "change_1m_bp": _bp(current, _spread(spec["left"], spec["right"], month_ago)),
                "change_ytd_bp": _bp(current, _spread(spec["left"], spec["right"], year_start)),
                "us10y_vs_threshold_bp": None,
            }
        )
    return pd.DataFrame(rows)
