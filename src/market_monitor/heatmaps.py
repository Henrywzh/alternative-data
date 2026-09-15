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

FLOW_CALENDAR_DAYS: dict[str, int] = {
    "1d": 1,
    "1w": 7,
    "1m": 30,
    "3m": 90,
}

HEATMAP_CATEGORY_LABELS: dict[str, dict[str, str]] = {
    "broad_equity": {"en": "Broad Equity", "zh": "宽基股票"},
    "sector": {"en": "Sectors", "zh": "行业板块"},
    "international": {"en": "International", "zh": "国际市场"},
    "commodity": {"en": "Commodities", "zh": "大宗商品"},
    "fixed_income": {"en": "Fixed Income", "zh": "固定收益"},
}


def build_heatmap_health(
    expected: int,
    observed: int,
    latest_date: str | None = None,
) -> dict[str, Any]:
    """Build a source health dictionary for the ETF heat map data."""
    coverage_str = f"{observed}/{expected}"
    if expected <= 0:
        status = "Healthy" if observed > 0 else "Unavailable"
    elif observed == 0:
        status = "Unavailable"
    elif observed < expected:
        status = "Degraded"
    else:
        status = "Healthy"

    obs_str = str(latest_date) if latest_date and str(latest_date) != "—" else "—"

    if status == "Healthy":
        notes = f"Daily OHLCV for all {observed} heatmap ETFs."
    elif status == "Degraded":
        notes = f"Daily OHLCV for {observed} of {expected} heatmap ETFs."
    else:
        notes = "Heatmap ETF price fetch returned no rows."

    return {
        "source": "US & Cross-Asset ETF heat map prices",
        "status": status,
        "latest_observation": obs_str,
        "coverage": coverage_str,
        "expected": expected,
        "observed": observed,
        "records": observed,
        "notes": notes,
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
        category = str(item.get("category", "")).strip()
        if category in HEATMAP_CATEGORY_LABELS:
            row.setdefault("category_en", HEATMAP_CATEGORY_LABELS[category]["en"])
            row.setdefault("category_zh", HEATMAP_CATEGORY_LABELS[category]["zh"])
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


def _normalize_fund_id(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    s = str(value).strip().upper()
    if s.endswith(".0"):
        s = s[:-2]
    if s.isdigit() and len(s) < 6:
        s = s.zfill(6)
    return s


def _clean_activity(activity: pd.DataFrame) -> pd.DataFrame:
    """Clean, filter, deduplicate and sort ETF fund activity history."""
    if activity is None or activity.empty:
        return pd.DataFrame()
    frame = activity.copy()

    date_col = (
        "observation_date"
        if "observation_date" in frame.columns
        else ("date" if "date" in frame.columns else None)
    )
    if date_col is None:
        return pd.DataFrame()
    frame["observation_date"] = pd.to_datetime(frame[date_col], errors="coerce")

    if "fund_id" in frame.columns and "ticker" in frame.columns:
        fund_series = frame["fund_id"].replace("", pd.NA).fillna(frame["ticker"])
        frame["fund_id"] = fund_series.map(_normalize_fund_id)
    elif "fund_id" in frame.columns:
        frame["fund_id"] = frame["fund_id"].map(_normalize_fund_id)
    elif "ticker" in frame.columns:
        frame["fund_id"] = frame["ticker"].map(_normalize_fund_id)
    else:
        return pd.DataFrame()

    frame = frame[frame["fund_id"] != ""].dropna(subset=["observation_date"])
    if frame.empty:
        return pd.DataFrame()

    if "flow_status" not in frame.columns:
        if "coverage_status" in frame.columns:
            frame["flow_status"] = frame["coverage_status"]
        else:
            frame["flow_status"] = "unavailable"
    frame["flow_status"] = frame["flow_status"].astype(str).str.strip()

    flow_col = (
        "estimated_flow_cny"
        if "estimated_flow_cny" in frame.columns
        else ("estimated_flow" if "estimated_flow" in frame.columns else None)
    )
    if flow_col is not None:
        frame["estimated_flow_cny"] = pd.to_numeric(frame[flow_col], errors="coerce")
    else:
        frame["estimated_flow_cny"] = pd.NA

    size_col = (
        "aum_nav_estimate_cny"
        if "aum_nav_estimate_cny" in frame.columns
        else (
            "size_value"
            if "size_value" in frame.columns
            else ("aum" if "aum" in frame.columns else None)
        )
    )
    if size_col is not None:
        frame["size_value"] = pd.to_numeric(frame[size_col], errors="coerce")
    else:
        frame["size_value"] = pd.NA

    frame = (
        frame.sort_values(["fund_id", "observation_date"], kind="mergesort")
        .drop_duplicates(["fund_id", "observation_date"], keep="last")
        .reset_index(drop=True)
    )
    return frame


def build_flow_snapshot(
    activity: pd.DataFrame,
    metadata: pd.DataFrame | Sequence[Mapping[str, Any]],
    *,
    as_of: str | None = None,
) -> pd.DataFrame:
    """Build a flow snapshot DataFrame across standard calendar windows for each metadata fund.

    Sums estimated flow only for rows where flow_status == 'validated'.
    Preserves missing flows as null rather than converting to zero.
    """
    if isinstance(metadata, pd.DataFrame):
        meta_records = metadata.to_dict(orient="records")
    elif metadata is not None:
        meta_records = [dict(item) for item in metadata]
    else:
        meta_records = []

    if not meta_records:
        return pd.DataFrame()

    cleaned = _clean_activity(activity)
    as_of_ts = pd.to_datetime(as_of) if as_of is not None else None

    if as_of_ts is not None and not cleaned.empty:
        cleaned = cleaned[cleaned["observation_date"] <= as_of_ts]

    if as_of is not None:
        effective_as_of_str = str(as_of)
        effective_as_of_ts = as_of_ts
    elif not cleaned.empty:
        valid_rows_all = cleaned[cleaned["flow_status"] == "validated"]
        if not valid_rows_all.empty:
            effective_as_of_ts = valid_rows_all["observation_date"].max()
        else:
            effective_as_of_ts = cleaned["observation_date"].max()
        effective_as_of_str = effective_as_of_ts.strftime("%Y-%m-%d")
    else:
        effective_as_of_ts = None
        effective_as_of_str = None

    rows: list[dict[str, Any]] = []
    grouped = dict(tuple(cleaned.groupby("fund_id", sort=False))) if not cleaned.empty else {}

    for item in meta_records:
        row = dict(item)
        category = str(item.get("category", "")).strip()
        if category in HEATMAP_CATEGORY_LABELS:
            row.setdefault("category_en", HEATMAP_CATEGORY_LABELS[category]["en"])
            row.setdefault("category_zh", HEATMAP_CATEGORY_LABELS[category]["zh"])
        fund_id = _normalize_fund_id(item.get("fund_id"))
        if not fund_id and "ticker" in item:
            fund_id = _normalize_fund_id(item.get("ticker"))
        fund_data = grouped.get(fund_id)
        if fund_data is None and "ticker" in item:
            fund_data = grouped.get(_normalize_fund_id(item.get("ticker")))

        row["as_of"] = effective_as_of_str

        if fund_data is not None and not fund_data.empty:
            latest_row = fund_data.iloc[-1]
            raw_status = latest_row.get("flow_status")
            coverage_status = (
                str(raw_status)
                if raw_status is not None and not pd.isna(raw_status)
                else "unavailable"
            )
            row["coverage_status"] = coverage_status

            size_val = latest_row.get("size_value")
            if size_val is not None and not pd.isna(size_val) and float(size_val) > 0:
                row["size_value"] = float(size_val)
                basis = latest_row.get("size_basis")
                if basis is not None and not pd.isna(basis) and str(basis).strip():
                    row["size_basis"] = str(basis).strip()
                else:
                    row["size_basis"] = "nav_estimate"
            else:
                row["size_value"] = None
                row["size_basis"] = None

            valid_rows = fund_data[fund_data["flow_status"] == "validated"]
            valid_obs_count = len(valid_rows)
            row["valid_observations"] = valid_obs_count

            if valid_obs_count > 0:
                first_date_ts = valid_rows["observation_date"].iloc[0]
                latest_date_ts = valid_rows["observation_date"].iloc[-1]
                row["first_valid_flow_date"] = first_date_ts.strftime("%Y-%m-%d")
                row["latest_valid_flow_date"] = latest_date_ts.strftime("%Y-%m-%d")
            else:
                row["first_valid_flow_date"] = None
                row["latest_valid_flow_date"] = None

            anchor_ts = latest_row["observation_date"]

            for window_name, days in FLOW_CALENDAR_DAYS.items():
                field_name = f"flow_{window_name}"
                if valid_obs_count == 0 or anchor_ts is None:
                    row[field_name] = None
                else:
                    window_start_ts = anchor_ts - pd.Timedelta(days=days - 1)
                    in_window = valid_rows[
                        (valid_rows["observation_date"] >= window_start_ts)
                        & (valid_rows["observation_date"] <= anchor_ts)
                    ]
                    if in_window.empty:
                        row[field_name] = None
                    else:
                        flows = in_window["estimated_flow_cny"].dropna()
                        if flows.empty:
                            row[field_name] = None
                        else:
                            row[field_name] = float(flows.sum())

            if valid_obs_count == 0 or anchor_ts is None:
                row["flow_ytd"] = None
            else:
                ytd_start_ts = pd.Timestamp(year=anchor_ts.year, month=1, day=1)
                ytd_rows = valid_rows[
                    (valid_rows["observation_date"] >= ytd_start_ts)
                    & (valid_rows["observation_date"] <= anchor_ts)
                ]
                if ytd_rows.empty:
                    row["flow_ytd"] = None
                else:
                    ytd_flows = ytd_rows["estimated_flow_cny"].dropna()
                    if ytd_flows.empty:
                        row["flow_ytd"] = None
                    else:
                        row["flow_ytd"] = float(ytd_flows.sum())
        else:
            row["coverage_status"] = "unavailable"
            row["size_value"] = None
            row["size_basis"] = None
            row["valid_observations"] = 0
            row["first_valid_flow_date"] = None
            row["latest_valid_flow_date"] = None
            for window_name in FLOW_CALENDAR_DAYS:
                row[f"flow_{window_name}"] = None
            row["flow_ytd"] = None

        rows.append(row)

    return pd.DataFrame(rows)
