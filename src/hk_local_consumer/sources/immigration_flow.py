"""HK Immigration Department daily passenger traffic source.

Fetches open-data daily passenger clearance statistics across 17 control
points for HK Residents, Mainland Visitors, and Other Visitors.

Calculates key cross-border signal metrics:
- 北上 (Northbound Flow): HK Resident Departures (total & land checkpoints)
- 南下 (Southbound Flow): Mainland Visitor Arrivals
- 7-day moving averages (7d MA) to smooth out day-of-week seasonality (weekend spikes).
"""

from __future__ import annotations

import logging

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, IMMIGRATION_PASSENGER_TRAFFIC_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

LAND_CONTROL_POINTS = [
    "Lo Wu",
    "Lok Ma Chau Spur Line",
    "Shenzhen Bay",
    "Heung Yuen Wai",
    "Hong Kong-Zhuhai-Macao Bridge",
    "Express Rail Link West Kowloon",
    "Lok Ma Chau",
    "Man Kam To",
    "Sha Tau Kok",
]

SCHEMA_COLUMNS = [
    "date",
    "hk_resident_departures",
    "mainland_visitor_arrivals",
    "other_visitor_arrivals",
    "hk_resident_arrivals",
    "mainland_visitor_departures",
    "hk_resident_departures_7d_ma",
    "mainland_visitor_arrivals_7d_ma",
    "land_hk_resident_departures_7d_ma",
]


def fetch_immigration_flow() -> pd.DataFrame:
    """Fetch and aggregate HK Immigration Department daily passenger clearance statistics."""
    try:
        resp = requests.get(IMMIGRATION_PASSENGER_TRAFFIC_URL, headers=DEFAULT_HEADERS, timeout=15)
        resp.raise_for_status()
        csv_text = resp.content.decode("utf-8-sig")
        df = pd.read_csv(pd.io.common.StringIO(csv_text))
    except Exception as exc:
        logger.warning(f"Failed to fetch Immigration Department daily traffic data ({exc}).")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    if df.empty or "Date" not in df.columns:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    # Clean column names
    df.columns = [c.strip() for c in df.columns]

    # Convert numeric fields
    numeric_cols = ["Hong Kong Residents", "Mainland Visitors", "Other Visitors", "Total"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.replace(",", "").str.strip()
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    # Convert dates
    df["Date"] = pd.to_datetime(df["Date"], format="%d-%m-%Y", errors="coerce")
    df = df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)

    # Aggregate daily totals
    arrivals = df[df["Arrival / Departure"].str.strip() == "Arrival"].groupby("Date").agg({
        "Hong Kong Residents": "sum",
        "Mainland Visitors": "sum",
        "Other Visitors": "sum",
    }).rename(columns={
        "Hong Kong Residents": "hk_resident_arrivals",
        "Mainland Visitors": "mainland_visitor_arrivals",
        "Other Visitors": "other_visitor_arrivals",
    })

    departures = df[df["Arrival / Departure"].str.strip() == "Departure"].groupby("Date").agg({
        "Hong Kong Residents": "sum",
        "Mainland Visitors": "sum",
        "Other Visitors": "sum",
    }).rename(columns={
        "Hong Kong Residents": "hk_resident_departures",
        "Mainland Visitors": "mainland_visitor_departures",
        "Other Visitors": "other_visitor_departures",
    })

    # Land-border HK resident departures (pure 北上 flow)
    land_df = df[
        (df["Arrival / Departure"].str.strip() == "Departure") &
        (df["Control Point"].str.strip().isin(LAND_CONTROL_POINTS))
    ]
    land_departures = land_df.groupby("Date")["Hong Kong Residents"].sum().rename("land_hk_resident_departures")

    # Combine daily aggregations
    daily = pd.concat([arrivals, departures, land_departures], axis=1).fillna(0).reset_index()
    daily["date"] = daily["Date"].dt.strftime("%Y-%m-%d")

    # Calculate 7-day moving averages
    daily["hk_resident_departures_7d_ma"] = daily["hk_resident_departures"].rolling(7, min_periods=1).mean().round(1)
    daily["mainland_visitor_arrivals_7d_ma"] = daily["mainland_visitor_arrivals"].rolling(7, min_periods=1).mean().round(1)
    daily["land_hk_resident_departures_7d_ma"] = daily["land_hk_resident_departures"].rolling(7, min_periods=1).mean().round(1)

    result = daily[SCHEMA_COLUMNS].sort_values("date").reset_index(drop=True)

    # Save raw snapshot
    source_url = IMMIGRATION_PASSENGER_TRAFFIC_URL
    raw_path = save_raw_snapshot(
        "immigration_passenger_traffic",
        df.to_dict(orient="records"),
        file_ext="json",
        source_url=source_url,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = source_url

    # Compute control point breakdown snapshot for recent 30 days
    recent_date = df["Date"].max()
    recent_df = df[df["Date"] == recent_date]
    checkpoint_snapshot = recent_df.to_dict(orient="records")
    result.attrs["latest_checkpoint_snapshot"] = checkpoint_snapshot
    result.attrs["latest_date"] = recent_date.strftime("%Y-%m-%d")
    result.attrs["checkpoint_history"] = df[[
        "Date", "Control Point", "Arrival / Departure", "Hong Kong Residents", "Mainland Visitors", "Other Visitors", "Total"
    ]].copy()

    return result
