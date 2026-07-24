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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config import (
    DATA_SOURCE_FALLBACK,
    DATA_SOURCE_LIVE,
    DEFAULT_HEADERS,
    FRED_DEXCHUS_URL,
    FRED_DEXHKUS_URL,
    HKO_RAINSTORM_URL,
    HKO_TYPHOON_URL,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

_RETRY_STATUS_CODES = (429, 500, 502, 503, 504)
FALLBACK_RMB_PER_100_HKD = 92.0


def _get_with_retry(url: str) -> requests.Response:
    """GET a public source with bounded retries for transient gateway errors."""
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        status=2,
        backoff_factor=0.5,
        status_forcelist=_RETRY_STATUS_CODES,
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    response = session.get(url, headers=DEFAULT_HEADERS, timeout=(8, 15))
    response.raise_for_status()
    return response

SCHEMA_COLUMNS = [
    "month",
    "date",
    "signal_8_plus_hours",
    "red_black_rain_hours",
    "amber_rain_hours",
    "total_disruption_hours",
    "rmb_per_100_hkd",
    "data_source",
]


def _fetch_rstorm_events() -> pd.DataFrame:
    """Fetch and parse HKO Rainstorm Warning Signal database."""
    resp = _get_with_retry(HKO_RAINSTORM_URL)
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
    resp = _get_with_retry(HKO_TYPHOON_URL)
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
    try:
        hkus = pd.read_csv(StringIO(_get_with_retry(FRED_DEXHKUS_URL).text))
        chus = pd.read_csv(StringIO(_get_with_retry(FRED_DEXCHUS_URL).text))
    except Exception as exc:
        # FRED occasionally returns a gateway timeout from CI runners. Keep
        # the weather series usable and make the fallback explicit; callers
        # can distinguish it through ``data_source`` instead of mistaking a
        # flat operational fallback for live FX observations.
        logger.warning("FRED FX unavailable after retries; using labeled fallback (%s).", exc)
        months = pd.date_range("2021-01-01", pd.Timestamp.now(), freq="MS").strftime("%Y-%m")
        return pd.DataFrame(
            {
                "month": months,
                "rmb_per_100_hkd": FALLBACK_RMB_PER_100_HKD,
                "data_source": DATA_SOURCE_FALLBACK,
            }
        )

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
    monthly_fx["data_source"] = DATA_SOURCE_LIVE
    return monthly_fx


def fetch_weather_demand_drivers() -> pd.DataFrame:
    """Fetch and aggregate severe weather disruption hours and HKD/RMB FX rate."""
    weather_source = DATA_SOURCE_LIVE
    try:
        r_df = _fetch_rstorm_events()
    except Exception as exc:
        logger.warning("Failed to fetch HKO rainstorm data; using zero-hour fallback (%s).", exc)
        r_df = pd.DataFrame()
        weather_source = DATA_SOURCE_FALLBACK
    try:
        t_df = _fetch_tc_events()
    except Exception as exc:
        logger.warning("Failed to fetch HKO typhoon data; using zero-hour fallback (%s).", exc)
        t_df = pd.DataFrame()
        weather_source = DATA_SOURCE_FALLBACK
    fx_df = _fetch_fx_monthly()

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
    base_df["data_source"] = base_df["data_source"].fillna(DATA_SOURCE_LIVE)
    if weather_source == DATA_SOURCE_FALLBACK:
        base_df["data_source"] = DATA_SOURCE_FALLBACK

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
