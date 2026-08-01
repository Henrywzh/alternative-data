"""Transport Department MTTD Table 2.3 passenger journeys."""

from __future__ import annotations

import io

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, MTTD_PASSENGER_JOURNEYS_URL
from ..storage import save_raw_snapshot

RAW_COLUMNS = [
    "YR_MTH",
    "BUS_RAIL",
    "TTD_PTO_CODE",
    "FRANCHISE_TYPE",
    "RAIL_LINE",
    "PAX_HK",
    "PAX_KLN_NT",
    "PAX_CROSS_HARBOUR",
]
SCHEMA_COLUMNS = [
    "date",
    "month",
    "bus_rail",
    "pto_code",
    "franchise_type",
    "rail_line",
    "pax_hk_k",
    "pax_kln_nt_k",
    "pax_cross_harbour_k",
    "total_passenger_journeys_k",
]


def parse_mttd_passenger_journeys_csv(payload: bytes) -> pd.DataFrame:
    frame = pd.read_csv(io.BytesIO(payload), encoding="utf-8-sig", dtype=str)
    frame.columns = [str(column).strip() for column in frame.columns]
    missing = sorted(set(RAW_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"MTTD Table 2.3 is missing columns: {missing}")
    normalized = frame[RAW_COLUMNS].rename(
        columns={
            "YR_MTH": "month",
            "BUS_RAIL": "bus_rail",
            "TTD_PTO_CODE": "pto_code",
            "FRANCHISE_TYPE": "franchise_type",
            "RAIL_LINE": "rail_line",
            "PAX_HK": "pax_hk_k",
            "PAX_KLN_NT": "pax_kln_nt_k",
            "PAX_CROSS_HARBOUR": "pax_cross_harbour_k",
        }
    ).copy()
    normalized["month"] = normalized["month"].astype(str).str.strip()
    normalized["date"] = pd.to_datetime(normalized["month"], format="%Y%m", errors="coerce")
    if normalized["date"].isna().any():
        raise ValueError("MTTD Table 2.3 contains invalid YR_MTH values")
    for column in ("bus_rail", "pto_code", "franchise_type", "rail_line"):
        normalized[column] = normalized[column].fillna("").astype(str).str.strip()
    for column in ("pax_hk_k", "pax_kln_nt_k", "pax_cross_harbour_k"):
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    numeric = normalized[["pax_hk_k", "pax_kln_nt_k", "pax_cross_harbour_k"]]
    normalized["total_passenger_journeys_k"] = numeric.sum(axis=1, min_count=1)
    normalized = normalized.dropna(subset=["total_passenger_journeys_k"])
    result = normalized[SCHEMA_COLUMNS].drop_duplicates().sort_values(
        ["date", "bus_rail", "pto_code", "rail_line", "franchise_type"]
    )
    return result.reset_index(drop=True)


def fetch_mttd_passenger_journeys() -> pd.DataFrame:
    response = requests.get(
        MTTD_PASSENGER_JOURNEYS_URL,
        headers=DEFAULT_HEADERS,
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    response.raise_for_status()
    result = parse_mttd_passenger_journeys_csv(response.content)
    raw_path = save_raw_snapshot(
        "mttd_passenger_journeys",
        response.content,
        file_ext="csv",
        source_url=MTTD_PASSENGER_JOURNEYS_URL,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = MTTD_PASSENGER_JOURNEYS_URL
    return result
