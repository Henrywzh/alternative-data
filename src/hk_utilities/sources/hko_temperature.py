"""HKO Daily Mean Temperature History.

Ingests HKO Open Data daily mean temperature (°C) history from 1884 to present.
Calculates daily & monthly average mean temperatures as a physical driver for
air-conditioning power load (CLP & HK Electric).
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, HKO_MEAN_TEMP_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "date",
    "month",
    "mean_temp_c",
    "month_avg_temp_c",
]


def fetch_hko_temperature() -> pd.DataFrame:
    """Fetch HKO daily mean temperature history and compute monthly averages."""
    resp = requests.get(HKO_MEAN_TEMP_URL, headers=DEFAULT_HEADERS, timeout=15)
    resp.raise_for_status()

    # Skip 2 header lines
    df = pd.read_csv(io.BytesIO(resp.content), skiprows=2)
    # Columns: 年/Year, 月/Month, 日/Day, 數值/Value, 數據完整性/data Completeness
    col_map = {df.columns[0]: "year", df.columns[1]: "month_num", df.columns[2]: "day", df.columns[3]: "temp_c"}
    df = df.rename(columns=col_map)

    df["temp_c"] = pd.to_numeric(df["temp_c"], errors="coerce")
    df = df.dropna(subset=["year", "month_num", "day", "temp_c"]).copy()

    df["year"] = df["year"].astype(int)
    df["month_num"] = df["month_num"].astype(int)
    df["day"] = df["day"].astype(int)

    df["month"] = df.apply(lambda r: f"{int(r['year']):04d}-{int(r['month_num']):02d}", axis=1)
    df["date"] = df.apply(lambda r: f"{int(r['year']):04d}-{int(r['month_num']):02d}-{int(r['day']):02d}", axis=1)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()

    # Filter to 2021+
    df = df[df["date"] >= "2021-01-01"].copy()

    # Compute monthly average mean temp
    monthly_avg = df.groupby("month")["temp_c"].mean().round(1).rename("month_avg_temp_c").reset_index()
    df = df.merge(monthly_avg, on="month", how="left")
    df["mean_temp_c"] = df["temp_c"].round(1)

    result = df[SCHEMA_COLUMNS].sort_values("date").reset_index(drop=True)

    raw_path = save_raw_snapshot(
        "hko_mean_temperature",
        result.to_dict(orient="records"),
        file_ext="json",
        source_url=HKO_MEAN_TEMP_URL,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = HKO_MEAN_TEMP_URL
    return result
