"""Transport Department monthly private-car first registrations by make.

The official Table 4.1(e) CSV is a real monthly history with dimensions for
make, fuel type, first-registration status and body type. The parser keeps the
source dimensions intact; the dashboard builder aggregates them only for the
small set of visual series it displays.
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, TD_PRIVATE_CAR_FIRST_REG_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

RAW_COLUMNS = [
    "YR_MTH",
    "VEHICLE_CLASS_CODE",
    "MAKE",
    "FIRST_REG_STATUS",
    "FIRST_REG_STATUS_REV",
    "FUEL_TYPE_CODE",
    "BODY_TYPE_CODE",
    "FIRST_REG",
]

SCHEMA_COLUMNS = [
    "date",
    "month",
    "vehicle_class_code",
    "make",
    "first_reg_status",
    "first_reg_status_rev",
    "fuel_type",
    "body_type_code",
    "first_reg",
]


def parse_td_private_car_first_reg_csv(payload: bytes) -> pd.DataFrame:
    """Parse the official UTF-8 CSV and retain private-car source grain."""
    frame = pd.read_csv(
        io.BytesIO(payload),
        encoding="utf-8-sig",
        dtype=str,
        low_memory=False,
    )
    frame.columns = [str(column).strip() for column in frame.columns]
    missing = sorted(set(RAW_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"TD Table 4.1(e) is missing expected columns: {missing}")

    normalized = frame[RAW_COLUMNS].rename(
        columns={
            "YR_MTH": "month",
            "VEHICLE_CLASS_CODE": "vehicle_class_code",
            "MAKE": "make",
            "FIRST_REG_STATUS": "first_reg_status",
            "FIRST_REG_STATUS_REV": "first_reg_status_rev",
            "FUEL_TYPE_CODE": "fuel_type",
            "BODY_TYPE_CODE": "body_type_code",
            "FIRST_REG": "first_reg",
        }
    ).copy()
    normalized["month"] = normalized["month"].astype("string").str.strip()
    normalized["vehicle_class_code"] = (
        normalized["vehicle_class_code"].astype("string").str.strip().str.replace(r"\.0$", "", regex=True)
    )
    normalized = normalized[normalized["vehicle_class_code"].eq("1")].copy()
    normalized["date"] = pd.to_datetime(normalized["month"], format="%Y%m", errors="coerce")
    normalized["month"] = normalized["date"].dt.strftime("%Y-%m")
    normalized["make"] = normalized["make"].astype("string").str.strip().str.upper()
    for column in ("first_reg_status", "first_reg_status_rev", "fuel_type", "body_type_code"):
        normalized[column] = normalized[column].astype("string").fillna("").str.strip()
    normalized["first_reg"] = pd.to_numeric(normalized["first_reg"], errors="coerce")

    normalized = normalized.dropna(subset=["date", "make", "first_reg"]).copy()
    if (normalized["first_reg"] < 0).any():
        raise ValueError("TD Table 4.1(e) contains negative first-registration counts")

    result = (
        normalized[SCHEMA_COLUMNS]
        .sort_values(["date", "make", "fuel_type", "body_type_code"])
        .reset_index(drop=True)
    )
    duplicate_keys = result.duplicated(
        ["month", "make", "first_reg_status", "first_reg_status_rev", "fuel_type", "body_type_code"]
    ).sum()
    if duplicate_keys:
        # The official table contains repeated dimensional rows in some
        # historical months; the published counts are additive and the
        # materializer aggregates them by month/make/fuel. Keep the rows here
        # rather than silently dropping counts.
        logger.info("TD Table 4.1(e) contains %d repeated dimensional rows; retaining for additive aggregation", duplicate_keys)
    return result


def fetch_td_private_car_first_reg() -> pd.DataFrame:
    """Fetch and normalize TD's monthly private-car first-registration CSV."""
    response = requests.get(
        TD_PRIVATE_CAR_FIRST_REG_URL,
        headers=DEFAULT_HEADERS,
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    response.raise_for_status()
    result = parse_td_private_car_first_reg_csv(response.content)
    raw_path = save_raw_snapshot(
        "td_private_car_first_reg",
        response.content,
        file_ext="csv",
        source_url=TD_PRIVATE_CAR_FIRST_REG_URL,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = TD_PRIVATE_CAR_FIRST_REG_URL
    result.attrs["source_last_modified"] = response.headers.get("Last-Modified")
    return result
