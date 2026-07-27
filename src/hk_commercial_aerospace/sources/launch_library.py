"""Launch Library 2 API integration.

Provides endpoints for fetching upcoming global launches and specific
agency historical launches.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
import requests
import pandas as pd

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    LAUNCH_LIBRARY_BASE,
    CHINESE_LAUNCH_AGENCIES,
    LL2_MAX_REQUESTS_PER_HOUR,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "launch_id",
    "name",
    "net_time",
    "status_abbrev",
    "status_name",
    "provider_name",
    "pad_name",
    "orbit_abbrev",
    "fetched_at",
]


def _parse_launch_results(results: list[dict], fetched_at: str) -> list[dict]:
    parsed = []
    for r in results:
        parsed.append({
            "launch_id": r.get("uuid", ""),
            "name": r.get("name", ""),
            "net_time": r.get("net", ""),
            "status_abbrev": r.get("status", {}).get("abbrev", ""),
            "status_name": r.get("status", {}).get("name", ""),
            "provider_name": r.get("launch_service_provider", {}).get("name", ""),
            "pad_name": r.get("pad", {}).get("name", ""),
            "orbit_abbrev": r.get("orbit", {}).get("abbrev", "") if r.get("orbit") else None,
            "fetched_at": fetched_at,
        })
    return parsed


def fetch_upcoming_launches(limit: int = 100) -> pd.DataFrame:
    """Fetch upcoming launches from Launch Library 2."""
    url = f"{LAUNCH_LIBRARY_BASE}/launch/upcoming/?format=json&limit={limit}"
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
    except Exception as e:
        logger.warning(f"Failed to fetch upcoming launches: {e}")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    save_raw_snapshot("ll2_upcoming_launches", data, source_url=url)
    parsed = _parse_launch_results(results, fetched_at)
    if not parsed:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
    return pd.DataFrame(parsed)[SCHEMA_COLUMNS]


def fetch_agency_launches(agency_name: str, limit: int = 50) -> pd.DataFrame:
    """Fetch previous launches for a specific agency name."""
    url = f"{LAUNCH_LIBRARY_BASE}/launch/previous/?search={agency_name}&format=json&limit={limit}"
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
    except Exception as e:
        logger.warning(f"Failed to fetch launches for agency {agency_name}: {e}")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    save_raw_snapshot(f"ll2_agency_launches_{agency_name.replace(' ', '_')}", data, source_url=url)
    parsed = _parse_launch_results(results, fetched_at)
    if not parsed:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
    return pd.DataFrame(parsed)[SCHEMA_COLUMNS]


def fetch_chinese_commercial_launches() -> dict[str, pd.DataFrame]:
    """Fetch all configured Chinese commercial launches from LL2.

    CRITICAL: This function is designed for a SINGLE scheduled run (daily/weekly),
    not for interactive ad hoc querying. Total HTTP requests across all agencies must
    stay under LL2_MAX_REQUESTS_PER_HOUR (15) — the free tier hard limit.

    If HTTP 429 is received, we stop immediately and return whatever has been
    collected so far. Partial results are honest; never retry immediately.
    """
    results: dict[str, pd.DataFrame] = {}
    requests_made = 0

    for agency in CHINESE_LAUNCH_AGENCIES:
        if requests_made >= LL2_MAX_REQUESTS_PER_HOUR - 2:  # Leave margin for upcoming_launches call
            logger.warning(
                "LL2 rate limit margin reached after %d requests — stopping agency fetch. "
                "Remaining agencies will be fetched on next scheduled run.",
                requests_made,
            )
            break

        url = f"{LAUNCH_LIBRARY_BASE}/launch/previous/?search={agency}&format=json&limit=50"
        fetched_at = datetime.now(timezone.utc).isoformat()
        requests_made += 1

        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=DEFAULT_TIMEOUT)
            if resp.status_code == 429:
                logger.warning(
                    "LL2 rate limit (HTTP 429) hit after %d requests — stopping. "
                    "Partial results returned. Will resume on next scheduled run.",
                    requests_made,
                )
                break
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.HTTPError:
            logger.warning("HTTP error fetching LL2 agency launches for %s.", agency)
            results[agency] = pd.DataFrame(columns=SCHEMA_COLUMNS)
            continue
        except Exception as exc:
            logger.warning("Failed to fetch LL2 agency launches for %s: %s", agency, exc)
            results[agency] = pd.DataFrame(columns=SCHEMA_COLUMNS)
            continue

        save_raw_snapshot(
            f"ll2_agency_launches_{agency.replace(' ', '_')}",
            data,
            source_url=url,
        )
        parsed = _parse_launch_results(data.get("results", []), fetched_at)
        results[agency] = pd.DataFrame(parsed, columns=SCHEMA_COLUMNS) if parsed else pd.DataFrame(columns=SCHEMA_COLUMNS)

    return results
