"""Transport Department real-time parking-vacancy feed.

The vacancy endpoint is a current snapshot of participating car parks. The
parser keeps one row per car park, vehicle type and service category, joins
the official basic-information feed for names/districts/coordinates, and
leaves vacancy types A/B/C explicit so an unknown count is never treated as
zero.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    TD_PARKING_BASIC_INFO_URL,
    TD_PARKING_VACANCY_URL,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "snapshot_at",
    "park_id",
    "name_en",
    "name_tc",
    "district_en",
    "district_tc",
    "latitude",
    "longitude",
    "vehicle_type",
    "service_category",
    "vacancy_type",
    "vacancy",
    "lastupdate",
]


def _decode_json(payload: bytes | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8-sig")
    return json.loads(payload.lstrip("\ufeff"))


def _value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    return None


def parse_td_parking_vacancy(
    vacancy_payload: bytes | str | dict[str, Any],
    basic_payload: bytes | str | dict[str, Any],
    *,
    snapshot_at: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Normalize vacancy plus basic-information JSON into long-form rows."""
    vacancy_data = _decode_json(vacancy_payload)
    basic_data = _decode_json(basic_payload)
    basic_by_id = {
        str(row.get("park_id")): row
        for row in basic_data.get("car_park", [])
        if row.get("park_id") is not None
    }
    snapshot = snapshot_at or pd.Timestamp(datetime.now(timezone.utc).replace(tzinfo=None))
    rows: list[dict[str, Any]] = []
    for carpark in vacancy_data.get("car_park", []):
        park_id = str(carpark.get("park_id") or "").strip()
        if not park_id:
            continue
        basic = basic_by_id.get(park_id, {})
        for vehicle in carpark.get("vehicle_type", []) or []:
            vehicle_type = str(vehicle.get("type") or "").strip()
            for service in vehicle.get("service_category", []) or []:
                category = str(service.get("category") or "").strip()
                vacancy_type = str(service.get("vacancy_type") or "").strip().upper()
                if not vehicle_type or not category or not vacancy_type:
                    continue
                rows.append(
                    {
                        "snapshot_at": snapshot,
                        "park_id": park_id,
                        "name_en": _value(basic, "name_en") or "",
                        "name_tc": _value(basic, "name_tc") or "",
                        "district_en": _value(basic, "district_en") or "",
                        "district_tc": _value(basic, "district_tc") or "",
                        "latitude": _value(basic, "latitude"),
                        "longitude": _value(basic, "longitude"),
                        "vehicle_type": vehicle_type,
                        "service_category": category,
                        "vacancy_type": vacancy_type,
                        "vacancy": service.get("vacancy"),
                        "lastupdate": service.get("lastupdate"),
                    }
                )

    result = pd.DataFrame(rows, columns=SCHEMA_COLUMNS)
    if result.empty:
        return result
    result["snapshot_at"] = pd.to_datetime(result["snapshot_at"], errors="coerce")
    result["lastupdate"] = pd.to_datetime(result["lastupdate"], errors="coerce")
    for column in ("latitude", "longitude", "vacancy"):
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["vacancy_type"] = result["vacancy_type"].astype("string")
    result = result.dropna(subset=["snapshot_at", "park_id"]).reset_index(drop=True)
    return result


def fetch_td_parking_vacancy() -> pd.DataFrame:
    """Fetch current vacancy and basic-information feeds from TD."""
    vacancy_response = requests.get(
        TD_PARKING_VACANCY_URL,
        headers=DEFAULT_HEADERS,
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    vacancy_response.raise_for_status()
    basic_response = requests.get(
        TD_PARKING_BASIC_INFO_URL,
        headers=DEFAULT_HEADERS,
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    basic_response.raise_for_status()
    fetched_at = pd.Timestamp(datetime.now(timezone.utc).replace(tzinfo=None))
    result = parse_td_parking_vacancy(
        vacancy_response.content,
        basic_response.content,
        snapshot_at=fetched_at,
    )
    vacancy_raw_path = save_raw_snapshot(
        "td_parking_vacancy",
        vacancy_response.content,
        file_ext="json",
        source_url=TD_PARKING_VACANCY_URL,
    )
    basic_raw_path = save_raw_snapshot(
        "td_parking_basic_info",
        basic_response.content,
        file_ext="json",
        source_url=TD_PARKING_BASIC_INFO_URL,
    )
    result.attrs["raw_snapshot"] = str(vacancy_raw_path)
    result.attrs["basic_raw_snapshot"] = str(basic_raw_path)
    result.attrs["source_url"] = TD_PARKING_VACANCY_URL
    result.attrs["source_last_modified"] = vacancy_response.headers.get("Last-Modified")
    return result
