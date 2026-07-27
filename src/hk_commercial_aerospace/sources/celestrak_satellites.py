"""Celestrak satellite data fetcher.

Fetches satellite counts for commercial constellations using NORAD General Perturbation (GP) data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
import requests
import pandas as pd

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    CELESTRAK_URL,
    SATELLITE_CONSTELLATIONS,
    GUOWANG_GAP_REASON,
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


def fetch_constellation_count(constellation_key: str) -> dict:
    """Fetch satellite count for a single constellation from Celestrak."""
    config = SATELLITE_CONSTELLATIONS[constellation_key]
    param = config["param"]
    url = f"{CELESTRAK_URL}?{param}&FORMAT=json"
    fetched_at = datetime.now(timezone.utc).isoformat()
    
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        
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
        
    return pd.DataFrame(rows)[SCHEMA_COLUMNS]
