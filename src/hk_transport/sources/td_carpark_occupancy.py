"""Transport Department metered parking-space occupancy signal.

The territory-wide TD car-park vacancy feed is a useful snapshot but has no
capacity denominator.  TD's CSDI metered-parking dataset is a different,
sensor-backed source: it lists individual parking spaces and publishes a
matching occupancy-status CSV.  This module uses that pair to calculate a
real observed occupancy rate by district and for all Hong Kong.  The two
signals remain separate in the artifact; one must not be described as the
other.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    TD_METERED_PARKING_OCCUPANCY_URL,
    TD_METERED_PARKING_SPACES_URL,
)
from ..storage import save_raw_snapshot

SCHEMA_COLUMNS = [
    "snapshot_at",
    "district",
    "occupancy_rate",
    "sample_size",
    "capacity_spaces",
    "occupied_spaces",
    "vacant_spaces",
    "listed_spaces",
]


def _decode_json(payload: bytes | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8-sig")
    return json.loads(payload)


def _space_inventory(payload: bytes | str | dict[str, Any]) -> pd.DataFrame:
    data = _decode_json(payload)
    features = data.get("features", [])
    rows = []
    for feature in features:
        properties = feature.get("properties", {}) if isinstance(feature, dict) else {}
        space_id = str(properties.get("ParkingSpaceId") or "").strip()
        district = str(properties.get("District") or "Unknown").strip().upper() or "UNKNOWN"
        if space_id:
            rows.append({"parking_space_id": space_id, "district": district})
    result = pd.DataFrame(rows, columns=["parking_space_id", "district"])
    if result.empty:
        raise ValueError("TD metered-parking inventory contained no parking spaces")
    return result.drop_duplicates("parking_space_id").reset_index(drop=True)


def _status_table(payload: bytes | str) -> pd.DataFrame:
    raw = payload.encode() if isinstance(payload, str) else payload
    frame = pd.read_csv(io.BytesIO(raw), dtype=str)
    frame.columns = [str(column).strip() for column in frame.columns]
    required = {"ParkingSpaceId", "OccupancyStatus", "OccupancyDateChanged"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"TD metered-parking status is missing columns: {missing}")
    result = frame[["ParkingSpaceId", "OccupancyStatus", "OccupancyDateChanged"]].rename(
        columns={
            "ParkingSpaceId": "parking_space_id",
            "OccupancyStatus": "occupancy_status",
            "OccupancyDateChanged": "occupancy_date_changed",
        }
    )
    result["parking_space_id"] = result["parking_space_id"].astype(str).str.strip()
    result["occupancy_status"] = result["occupancy_status"].astype(str).str.strip().str.upper()
    result["occupancy_date_changed"] = pd.to_datetime(
        result["occupancy_date_changed"], format="%m/%d/%Y %I:%M:%S %p", errors="coerce"
    )
    return result.drop_duplicates("parking_space_id", keep="last")


def parse_td_carpark_occupancy(
    spaces_payload: bytes | str | dict[str, Any],
    status_payload: bytes | str,
    *,
    snapshot_at: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Aggregate sensor-backed metered parking occupancy by district."""
    inventory = _space_inventory(spaces_payload)
    status = _status_table(status_payload)
    merged = inventory.merge(status, on="parking_space_id", how="left")
    merged["known_status"] = merged["occupancy_status"].isin({"O", "V"})
    merged = merged[merged["known_status"]].copy()
    if merged.empty:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
    merged["occupied_spaces"] = merged["occupancy_status"].eq("O").astype(int)
    merged["vacant_spaces"] = merged["occupancy_status"].eq("V").astype(int)
    merged["snapshot_at"] = snapshot_at or pd.Timestamp(datetime.now(timezone.utc).replace(tzinfo=None))

    groups = [
        merged.groupby(["snapshot_at", "district"], as_index=False),
        merged.assign(district="All Hong Kong").groupby(["snapshot_at", "district"], as_index=False),
    ]
    rows: list[pd.DataFrame] = []
    for group in groups:
        summary = group.agg(
            sample_size=("parking_space_id", "nunique"),
            capacity_spaces=("parking_space_id", "nunique"),
            occupied_spaces=("occupied_spaces", "sum"),
            vacant_spaces=("vacant_spaces", "sum"),
            listed_spaces=("parking_space_id", "nunique"),
        )
        summary["occupancy_rate"] = summary["occupied_spaces"] / summary["capacity_spaces"]
        rows.append(summary)
    result = pd.concat(rows, ignore_index=True)[SCHEMA_COLUMNS]
    return result.sort_values(["snapshot_at", "district"]).reset_index(drop=True)


def fetch_td_carpark_occupancy() -> pd.DataFrame:
    spaces_response = requests.get(
        TD_METERED_PARKING_SPACES_URL,
        headers=DEFAULT_HEADERS,
        timeout=max(DEFAULT_TIMEOUT, 90),
    )
    spaces_response.raise_for_status()
    status_response = requests.get(
        TD_METERED_PARKING_OCCUPANCY_URL,
        headers=DEFAULT_HEADERS,
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    status_response.raise_for_status()
    snapshot_at = pd.Timestamp(datetime.now(timezone.utc).replace(tzinfo=None))
    result = parse_td_carpark_occupancy(
        spaces_response.content,
        status_response.content,
        snapshot_at=snapshot_at,
    )
    spaces_raw = save_raw_snapshot(
        "td_metered_parking_spaces",
        spaces_response.content,
        file_ext="geojson",
        source_url=TD_METERED_PARKING_SPACES_URL,
    )
    status_raw = save_raw_snapshot(
        "td_metered_parking_occupancy_status",
        status_response.content,
        file_ext="csv",
        source_url=TD_METERED_PARKING_OCCUPANCY_URL,
    )
    result.attrs["raw_snapshot"] = str(spaces_raw)
    result.attrs["status_raw_snapshot"] = str(status_raw)
    result.attrs["source_url"] = TD_METERED_PARKING_SPACES_URL
    result.attrs["status_source_url"] = TD_METERED_PARKING_OCCUPANCY_URL
    return result
