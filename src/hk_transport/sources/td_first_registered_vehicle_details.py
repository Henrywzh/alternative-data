"""Latest Transport Department per-vehicle first-registration details.

This feed complements Table 4.1(e): the monthly CSV has a long history and is
used for charts, while this feed preserves the latest vehicle make/model
detail for a bounded dashboard lookup table. It is intentionally not treated
as a historical model series because the individual-month files are published
as separate snapshots.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    TD_FIRST_REGISTERED_VEHICLE_URL_TEMPLATE,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

RAW_COLUMNS = [
    "Vehicle Class",
    "Vehicle Make",
    "Vehicle Model",
    "Fuel Type",
    "Cylinder Capacity Of Engine (c.c.)",
    "Rated Power (kW)",
    "Body Type",
    "First Registration Vehicle Status",
    "Permitted Gross Vehicle Weight",
    "Number Of Passenger Seats",
    "Taxable Value (HK$)",
    "Year Of Manufacture",
]

SCHEMA_COLUMNS = [
    "observation_date",
    "vehicle_class",
    "vehicle_make",
    "vehicle_model",
    "fuel_type",
    "first_registration_status",
    "rated_power_kw",
    "year_of_manufacture",
]

MONTH_ABBREVIATIONS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def parse_td_first_registered_vehicle_csv(payload: bytes, *, observation_date: pd.Timestamp) -> pd.DataFrame:
    """Parse one official monthly detail CSV and keep private-car rows."""
    frame = pd.read_csv(
        io.BytesIO(payload),
        encoding="utf-8-sig",
        dtype=str,
        low_memory=False,
    )
    frame.columns = [str(column).strip() for column in frame.columns]
    missing = sorted(set(RAW_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"TD first-registration detail CSV is missing columns: {missing}")

    normalized = frame[RAW_COLUMNS].rename(
        columns={
            "Vehicle Class": "vehicle_class",
            "Vehicle Make": "vehicle_make",
            "Vehicle Model": "vehicle_model",
            "Fuel Type": "fuel_type",
            "Rated Power (kW)": "rated_power_kw",
            "First Registration Vehicle Status": "first_registration_status",
            "Year Of Manufacture": "year_of_manufacture",
        }
    ).copy()
    normalized = normalized[
        normalized["vehicle_class"].astype("string").str.strip().str.casefold().eq("private car")
    ].copy()
    for column in ("vehicle_class", "vehicle_make", "vehicle_model", "fuel_type", "first_registration_status"):
        normalized[column] = normalized[column].astype("string").fillna("").str.strip()
    normalized["rated_power_kw"] = pd.to_numeric(normalized["rated_power_kw"], errors="coerce")
    normalized["year_of_manufacture"] = pd.to_numeric(normalized["year_of_manufacture"], errors="coerce")
    normalized["observation_date"] = pd.Timestamp(observation_date).normalize()
    normalized = normalized[normalized["vehicle_make"].ne("")].copy()
    return normalized[SCHEMA_COLUMNS].reset_index(drop=True)


def _candidate_months() -> list[tuple[int, int, str]]:
    now_hkt = datetime.now(timezone.utc) + timedelta(hours=8)
    current = pd.Timestamp(year=now_hkt.year, month=now_hkt.month, day=1)
    candidates = []
    for offset in range(0, 8):
        month = current - pd.DateOffset(months=offset)
        candidates.append((int(month.year), int(month.month), MONTH_ABBREVIATIONS[int(month.month) - 1]))
    return candidates


def fetch_td_first_registered_vehicle_details() -> pd.DataFrame:
    """Fetch the newest available monthly private-car detail CSV."""
    last_error: Exception | None = None
    for year, month_number, month_abbreviation in _candidate_months():
        url = TD_FIRST_REGISTERED_VEHICLE_URL_TEMPLATE.format(
            month=month_abbreviation,
            year=year,
        )
        try:
            response = requests.get(url, headers=DEFAULT_HEADERS, timeout=max(DEFAULT_TIMEOUT, 30))
            response.raise_for_status()
            result = parse_td_first_registered_vehicle_csv(
                response.content,
                observation_date=pd.Timestamp(year=year, month=month_number, day=1),
            )
            if result.empty:
                raise ValueError(f"TD detail feed returned no private-car rows for {year}-{month_number:02d}")
            raw_path = save_raw_snapshot(
                "td_first_registered_vehicle_details",
                response.content,
                file_ext="csv",
                source_url=url,
            )
            result.attrs["raw_snapshot"] = str(raw_path)
            result.attrs["source_url"] = url
            result.attrs["source_last_modified"] = response.headers.get("Last-Modified")
            result.attrs["source_observation_date"] = f"{year:04d}-{month_number:02d}-01"
            return result
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            logger.info("TD detail feed candidate unavailable (%s): %s", url, exc)

    raise RuntimeError("No recent TD first-registered vehicle detail CSV was available") from last_error
