"""HKO Severe Weather Warnings & Demand Drivers (FRED Exchange Rate).

Fetches open-data HKO warning signal history (rstorm.dat & tc.dat) and FRED FX
data to build demand-suppression & macro purchasing power indicators:
- Monthly hours under Typhoon Signal 8+ (Signal 8, 9, 10)
- Monthly hours under Red/Black Rainstorm Warnings
- Monthly average RMB per 100 HKD exchange rate
"""

from __future__ import annotations

import logging
from io import StringIO

import pandas as pd
import requests

from ..config import (
    DEFAULT_HEADERS,
    FRED_DEXCHUS_URL,
    FRED_DEXHKUS_URL,
    HKO_RAINSTORM_URL,
    HKO_TYPHOON_URL,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "month",
    "date",
    "signal_8_plus_hours",
    "red_black_rain_hours",
    "amber_rain_hours",
    "total_disruption_hours",
    "rmb_per_100_hkd",
]


def _fetch_rstorm_events() -> pd.DataFrame:
    """Fetch and parse HKO Rainstorm Warning Signal database."""
    resp = requests.get(HKO_RAINSTORM_URL, headers=DEFAULT_HEADERS, timeout=15)
    resp.raise_for_status()
    text = resp.content.decode("latin1").strip()

    events = []
    for line in text.split("\n"):
        parts = line.strip().split("\t")
        if len(parts) >= 11 and parts[0] in ("A", "R", "B"):
            code, sy, sm, sd, sh, smi, ey, em, ed, eh, emi = parts[:11]
            try:
                start_dt = pd.Timestamp(int(sy), int(sm), int(sd), int(sh), int(smi))
                end_dt = pd.Timestamp(int(ey), int(em), int(ed), int(eh), int(emi))
                dur_hrs = max(0.0, (end_dt - start_dt).total_seconds() / 3600.0)
                events.append({
                    "signal_code": code,
                    "signal_name": "Black Rainstorm" if code == "B" else ("Red Rainstorm" if code == "R" else "Amber Rainstorm"),
                    "start": start_dt,
                    "end": end_dt,
                    "duration_hours": round(dur_hrs, 2),
                    "month": start_dt.strftime("%Y-%m"),
                })
            except Exception:
                continue
    return pd.DataFrame(events)


def _fetch_tc_events() -> pd.DataFrame:
    """Fetch and parse HKO Tropical Cyclone Warning Signal database."""
    resp = requests.get(HKO_TYPHOON_URL, headers=DEFAULT_HEADERS, timeout=15)
    resp.raise_for_status()
    text = resp.content.decode("latin1").strip()

    events = []
    for line in text.split("\n"):
        parts = line.strip().split("\t")
        if len(parts) >= 15:
            sig = parts[3].strip()
            # Only care about Signal 8, 8NE, 8SE, 8NW, 8SW, 9, 10
            if not any(k in sig for k in ("8", "9", "10")):
                continue
            tc_name = parts[2].strip()
            sy, sm, sd = parts[8], parts[7], parts[6]
            shmm = parts[5].zfill(4)
            ey, em, ed = parts[13], parts[12], parts[11]
            ehmm = parts[10].zfill(4)
            try:
                sh, smi = int(shmm[:2]), int(shmm[2:])
                eh, emi = int(ehmm[:2]), int(ehmm[2:])
                start_dt = pd.Timestamp(int(sy), int(sm), int(sd), sh, smi)
                end_dt = pd.Timestamp(int(ey), int(em), int(ed), eh, emi)
                dur_hrs = max(0.0, (end_dt - start_dt).total_seconds() / 3600.0)
                events.append({
                    "signal_code": f"T{sig}",
                    "signal_name": f"Typhoon Signal {sig} ({tc_name})",
                    "start": start_dt,
                    "end": end_dt,
                    "duration_hours": round(dur_hrs, 2),
                    "month": start_dt.strftime("%Y-%m"),
                })
            except Exception:
                continue
    return pd.DataFrame(events)


def _fetch_fx_monthly() -> pd.DataFrame:
    """Fetch FRED DEXHKUS and DEXCHUS to derive monthly HKD/RMB exchange rate."""
    hkus = pd.read_csv(FRED_DEXHKUS_URL)
    chus = pd.read_csv(FRED_DEXCHUS_URL)

    # Normalize date column name across FRED CSV format variations
    for frame in (hkus, chus):
        if "observation_date" in frame.columns:
            frame.rename(columns={"observation_date": "DATE"}, inplace=True)

    hkus["DEXHKUS"] = pd.to_numeric(hkus["DEXHKUS"], errors="coerce")
    chus["DEXCHUS"] = pd.to_numeric(chus["DEXCHUS"], errors="coerce")

    merged = hkus.merge(chus, on="DATE").dropna()
    merged["DATE"] = pd.to_datetime(merged["DATE"])
    merged["rmb_per_100_hkd"] = (merged["DEXCHUS"] / merged["DEXHKUS"]) * 100.0
    merged["month"] = merged["DATE"].dt.strftime("%Y-%m")

    monthly_fx = merged.groupby("month")["rmb_per_100_hkd"].mean().round(2).reset_index()
    return monthly_fx


def fetch_weather_demand_drivers() -> pd.DataFrame:
    """Fetch and aggregate severe weather disruption hours and HKD/RMB FX rate."""
    try:
        r_df = _fetch_rstorm_events()
        t_df = _fetch_tc_events()
        fx_df = _fetch_fx_monthly()
    except Exception as exc:
        logger.warning(f"Failed to fetch weather or demand drivers ({exc}).")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    # Monthly severe weather aggregations
    r_agg = pd.DataFrame()
    if not r_df.empty:
        r_df["red_black"] = r_df["signal_code"].isin(["R", "B"])
        r_df["amber"] = r_df["signal_code"] == "A"
        r_agg = r_df.groupby("month").agg(
            red_black_rain_hours=("duration_hours", lambda x: r_df.loc[x.index[r_df.loc[x.index, "red_black"]], "duration_hours"].sum()),
            amber_rain_hours=("duration_hours", lambda x: r_df.loc[x.index[r_df.loc[x.index, "amber"]], "duration_hours"].sum()),
        ).reset_index()

    t_agg = pd.DataFrame()
    if not t_df.empty:
        t_agg = t_df.groupby("month")["duration_hours"].sum().rename("signal_8_plus_hours").reset_index()

    # Combine all months from 2021 to current
    all_months = pd.date_range("2021-01-01", pd.Timestamp.now(), freq="MS").strftime("%Y-%m")
    base_df = pd.DataFrame({"month": all_months})
    base_df["date"] = base_df["month"] + "-01"

    if not r_agg.empty:
        base_df = base_df.merge(r_agg, on="month", how="left")
    else:
        base_df["red_black_rain_hours"] = 0.0
        base_df["amber_rain_hours"] = 0.0

    if not t_agg.empty:
        base_df = base_df.merge(t_agg, on="month", how="left")
    else:
        base_df["signal_8_plus_hours"] = 0.0

    base_df = base_df.merge(fx_df, on="month", how="left")

    base_df["red_black_rain_hours"] = base_df["red_black_rain_hours"].fillna(0.0).round(1)
    base_df["amber_rain_hours"] = base_df["amber_rain_hours"].fillna(0.0).round(1)
    base_df["signal_8_plus_hours"] = base_df["signal_8_plus_hours"].fillna(0.0).round(1)
    base_df["total_disruption_hours"] = (base_df["red_black_rain_hours"] + base_df["signal_8_plus_hours"]).round(1)

    result = base_df[SCHEMA_COLUMNS].sort_values("date").reset_index(drop=True)

    # Save raw snapshot
    raw_path = save_raw_snapshot(
        "weather_demand_drivers",
        result.to_dict(orient="records"),
        file_ext="json",
        source_url=HKO_RAINSTORM_URL,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = HKO_RAINSTORM_URL

    # Save recent severe weather events list
    events = []
    if not r_df.empty:
        r_recent = r_df[r_df["signal_code"].isin(["R", "B"])].copy()
        for _, row in r_recent.iterrows():
            events.append({
                "signal_name": row["signal_name"],
                "start": row["start"].strftime("%Y-%m-%d %H:%M"),
                "end": row["end"].strftime("%Y-%m-%d %H:%M"),
                "duration_hours": row["duration_hours"],
            })
    if not t_df.empty:
        for _, row in t_df.iterrows():
            events.append({
                "signal_name": row["signal_name"],
                "start": row["start"].strftime("%Y-%m-%d %H:%M"),
                "end": row["end"].strftime("%Y-%m-%d %H:%M"),
                "duration_hours": row["duration_hours"],
            })

    events_df = pd.DataFrame(events)
    if not events_df.empty:
        events_df = events_df.sort_values("start", ascending=False).head(30)
        result.attrs["recent_events"] = events_df.to_dict(orient="records")
    else:
        result.attrs["recent_events"] = []

    return result
