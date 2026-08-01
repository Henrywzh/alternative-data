"""Celestrak satellite data fetcher.

Fetches satellite counts for commercial constellations using NORAD General Perturbation (GP) data.
"""

from __future__ import annotations

import logging
import json
from datetime import datetime, timezone
import requests
import pandas as pd

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    CELESTRAK_URL,
    SATELLITE_CONSTELLATIONS,
    GUOWANG_GAP_REASON,
    NORMALIZED_DIR,
    RAW_DIR,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "constellation",
    "operator",
    "satellite_count",
    "fetched_at",
]

KNOWN_GAPS = {
    "guowang": {
        "reason": GUOWANG_GAP_REASON,
        "attempted_params": ["GROUP=guowang", "NAME=SATNET", "NAME=SATNET GROUP", "NAME=GW-"],
    }
}

HISTORY_PATH = NORMALIZED_DIR / "celestrak_constellation_history.jsonl"


def _read_history_file() -> pd.DataFrame:
    if not HISTORY_PATH.exists():
        return pd.DataFrame(columns=["constellation", "operator", "satellite_count", "as_of"])
    rows = []
    for line in HISTORY_PATH.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            if row.get("constellation") and row.get("as_of"):
                rows.append(row)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed Celestrak history row")
    return pd.DataFrame(rows, columns=["constellation", "operator", "satellite_count", "as_of"])


def _append_history(rows: list[dict]) -> None:
    """Append one daily observation per constellation without overwriting history."""
    if not rows:
        return
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_history_file()
    known = set(zip(existing.get("constellation", []), existing.get("as_of", [])))
    new_rows = [
        {
            "constellation": row["constellation"],
            "operator": row["operator"],
            "satellite_count": row["satellite_count"],
            "as_of": row["fetched_at"][:10],
        }
        for row in rows
        if row.get("_fetch_ok")
        and (row["constellation"], row["fetched_at"][:10]) not in known
    ]
    if not new_rows:
        return
    with HISTORY_PATH.open("a", encoding="utf-8") as handle:
        for row in new_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_constellation_history() -> pd.DataFrame:
    """Load persisted daily counts and current raw snapshots for backfill."""
    history = _read_history_file()
    raw_rows = []
    for path in RAW_DIR.glob("celestrak_*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            key = path.name.split("celestrak_", 1)[1].split("_20", 1)[0]
            if key not in SATELLITE_CONSTELLATIONS:
                continue
            fetched_at = payload.get("fetched_at") or path.stem.rsplit("_", 2)[-2]
            data = payload.get("data")
            if isinstance(data, list):
                raw_rows.append({
                    "constellation": key.capitalize(),
                    "operator": SATELLITE_CONSTELLATIONS[key]["operator"],
                    "satellite_count": len(data),
                    "as_of": str(fetched_at)[:10],
                })
        except (OSError, json.JSONDecodeError):
            continue
    combined = pd.concat([history, pd.DataFrame(raw_rows)], ignore_index=True)
    if combined.empty:
        return pd.DataFrame(columns=["constellation", "operator", "satellite_count", "as_of"])
    return (
        combined.drop_duplicates(["constellation", "as_of"], keep="last")
        .sort_values(["as_of", "constellation"])
        .reset_index(drop=True)
    )


def fetch_constellation_count(constellation_key: str) -> dict:
    """Fetch satellite count for a single constellation from Celestrak."""
    config = SATELLITE_CONSTELLATIONS[constellation_key]
    param = config["param"]
    url = f"{CELESTRAK_URL}?{param}&FORMAT=json"
    fetched_at = datetime.now(timezone.utc).isoformat()
    fetch_ok = False
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        fetch_ok = True
        
        # Save the raw payload
        save_raw_snapshot(f"celestrak_{constellation_key}", data, source_url=url)
        
        count = len(data) if isinstance(data, list) else 0
    except Exception as e:
        logger.warning(f"Failed to fetch Celestrak data for {constellation_key}: {e}")
        count = 0
        
    return {
        "constellation": constellation_key.capitalize(),  # We'll normalize this or use key
        "operator": config["operator"],
        "satellite_count": count,
        "fetched_at": fetched_at,
        "_fetch_ok": fetch_ok,
    }


def fetch_all_constellations() -> pd.DataFrame:
    """Fetch counts for all tracked satellite constellations."""
    rows = []
    
    for key in SATELLITE_CONSTELLATIONS:
        # We don't fetch guowang here, it's not in SATELLITE_CONSTELLATIONS
        # The prompt says: "Guowang is NOT fetched — it's documented as a known gap."
        result = fetch_constellation_count(key)
        rows.append(result)
        
    if not rows:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
        
    _append_history(rows)
    frame = pd.DataFrame(rows)[SCHEMA_COLUMNS]
    successful = sum(bool(row.get("_fetch_ok")) for row in rows)
    frame.attrs["source"] = "live" if successful else "unavailable"
    frame.attrs["partial"] = 0 < successful < len(rows)
    return frame
