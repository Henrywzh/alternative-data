"""DSD daily sewage flow and final-effluent laboratory observations.

The Drainage Services Department publishes one official UTF-16, tab-delimited
CSV covering daily observations from multiple sewage treatment works. The
dataset is listed in CSDI as ``dsd_rcd_1636622115573_60635`` and currently
contains both daily flow and sparse laboratory fields (BOD, TSS, nitrogen,
oil/grease, pH and E. coli).

The source's treatment-works coverage changes over time and several laboratory
columns are intentionally sparse. We preserve the source grain instead of
filling missing lab values or aggregating plants into a single total.
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, DSD_SEWAGE_FLOW_LAB_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "date",
    "month",
    "plant",
    "daily_flow_cum_d",
    "bod_symbol",
    "bod_mg_o2_l",
    "tss_symbol",
    "tss_mg_l",
    "nh3_n_symbol",
    "nh3_n_mg_l",
    "nox_n_symbol",
    "nox_n_mg_l",
    "og_symbol",
    "og_mg_l",
    "tn_symbol",
    "tn_mg_l",
    "ph",
    "e_coli_cfu_100ml",
]

RAW_COLUMN_MAP = {
    "Sampling Date": "date",
    "Sewage Treatment Works": "plant",
    "Daily Flow (CuM/d)": "daily_flow_cum_d",
    "BOD_SYMBOL": "bod_symbol",
    "BOD (mgO2/L)": "bod_mg_o2_l",
    "TSS_SYMBOL": "tss_symbol",
    "TSS (mg/L)": "tss_mg_l",
    "NH3-N_SYMBOL": "nh3_n_symbol",
    "NH3-N (mg/L)": "nh3_n_mg_l",
    "NOx-N_SYMBOL": "nox_n_symbol",
    "NOx-N (mg/L)": "nox_n_mg_l",
    "OG_SYMBOL": "og_symbol",
    "OG (mg/L)": "og_mg_l",
    "TN_SYMBOL": "tn_symbol",
    "TN (mg/L)": "tn_mg_l",
    "pH": "ph",
    "E.coli (cfu/100ml)": "e_coli_cfu_100ml",
}

NUMERIC_COLUMNS = [
    "daily_flow_cum_d",
    "bod_mg_o2_l",
    "tss_mg_l",
    "nh3_n_mg_l",
    "nox_n_mg_l",
    "og_mg_l",
    "tn_mg_l",
    "ph",
    "e_coli_cfu_100ml",
]


def parse_dsd_sewage_flow_lab_csv(payload: bytes) -> pd.DataFrame:
    """Parse the official DSD UTF-16 tab-delimited payload."""
    frame = pd.read_csv(
        io.BytesIO(payload),
        sep="\t",
        encoding="utf-16",
        low_memory=False,
    )
    frame.columns = [str(column).strip() for column in frame.columns]

    missing = [column for column in RAW_COLUMN_MAP if column not in frame.columns]
    if missing:
        raise ValueError(f"DSD sewage CSV is missing expected columns: {missing}")

    normalized = frame.rename(columns=RAW_COLUMN_MAP).copy()
    normalized["plant"] = normalized["plant"].astype("string").str.strip()
    normalized["date"] = pd.to_datetime(
        normalized["date"].astype("string").str.strip(),
        format="%Y/%m/%d",
        errors="coerce",
    )
    normalized = normalized.dropna(subset=["date", "plant"]).copy()
    normalized["month"] = normalized["date"].dt.strftime("%Y-%m")

    for column in NUMERIC_COLUMNS:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")

    for column in SCHEMA_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = pd.NA

    result = (
        normalized[SCHEMA_COLUMNS]
        .sort_values(["date", "plant"])
        .reset_index(drop=True)
    )

    duplicate_keys = result.duplicated(["date", "plant"]).sum()
    if duplicate_keys:
        logger.warning("DSD sewage feed contains %d duplicate date/plant rows", duplicate_keys)
    return result


def fetch_dsd_sewage_flow_lab() -> pd.DataFrame:
    """Fetch and normalize DSD daily flow and effluent laboratory data."""
    response = requests.get(
        DSD_SEWAGE_FLOW_LAB_URL,
        headers=DEFAULT_HEADERS,
        timeout=max(DEFAULT_TIMEOUT, 60),
    )
    response.raise_for_status()
    result = parse_dsd_sewage_flow_lab_csv(response.content)
    raw_path = save_raw_snapshot(
        "dsd_sewage_flow_lab",
        response.content,
        file_ext="csv",
        source_url=DSD_SEWAGE_FLOW_LAB_URL,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = DSD_SEWAGE_FLOW_LAB_URL
    result.attrs["source_last_modified"] = response.headers.get("Last-Modified")
    return result

