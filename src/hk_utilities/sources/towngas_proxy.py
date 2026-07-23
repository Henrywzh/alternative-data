"""Towngas Proxy: CenStatD HK Energy Statistics (Gas Consumption by Sector).

Ingests CenStatD Theme 91, Table 915-91201 monthly town gas consumption (TJ)
broken down by user type (Domestic, Commercial, Industrial, Total).
Serves as an operational proxy for Towngas (HK's sole town gas supplier).
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import requests

from ..config import CENSTATD_ENERGY_GAS_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "date",
    "month",
    "domestic_gas_tj",
    "commercial_gas_tj",
    "industrial_gas_tj",
    "total_gas_tj",
]

USER_TYPE_MAP = {
    "1": "domestic_gas_tj",
    "2": "commercial_gas_tj",
    "3": "industrial_gas_tj",
}


def fetch_towngas_proxy() -> pd.DataFrame:
    """Fetch CenStatD monthly gas consumption by user type."""
    resp = requests.get(CENSTATD_ENERGY_GAS_URL, headers=DEFAULT_HEADERS, timeout=15)
    resp.raise_for_status()

    df = pd.read_csv(io.BytesIO(resp.content))
    # Drop annual rows (where MM is NaN)
    df = df.dropna(subset=["MM"]).copy()
    df["year"] = df["CCYY"].astype(int)
    df["month_num"] = df["MM"].astype(int)
    df["month"] = df.apply(lambda r: f"{int(r['year']):04d}-{int(r['month_num']):02d}", axis=1)
    df["date"] = pd.to_datetime(df["month"] + "-01")
    df["obs_value"] = pd.to_numeric(df["obs_value"], errors="coerce")

    # Pivot by USER_TYPE
    # USER_TYPE NaN is total
    totals = df[df["USER_TYPE"].isna()][["month", "date", "obs_value"]].rename(
        columns={"obs_value": "total_gas_tj"}
    )

    sectors = df[df["USER_TYPE"].notna()].copy()
    sectors["user_code"] = sectors["USER_TYPE"].astype(int).astype(str)
    sectors["col_name"] = sectors["user_code"].map(USER_TYPE_MAP)
    pivoted = sectors.pivot(index="month", columns="col_name", values="obs_value").reset_index()

    merged = totals.merge(pivoted, on="month", how="left").sort_values("date").reset_index(drop=True)

    for col in ("domestic_gas_tj", "commercial_gas_tj", "industrial_gas_tj", "total_gas_tj"):
        if col not in merged.columns:
            merged[col] = 0.0
        else:
            merged[col] = merged[col].fillna(0.0).round(1)

    result = merged[SCHEMA_COLUMNS]

    raw_path = save_raw_snapshot(
        "towngas_proxy_gas_consumption",
        result.to_dict(orient="records"),
        file_ext="json",
        source_url=CENSTATD_ENERGY_GAS_URL,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = CENSTATD_ENERGY_GAS_URL
    return result
