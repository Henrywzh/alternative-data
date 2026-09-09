"""Remote artifact loader for US Sector & Sub-industry ETFs.

Supports fetching from Cloudflare R2 / Public CDN with automatic fallback to
git-ignored local cache or on-demand fetch.
"""

from __future__ import annotations

from datetime import datetime
import logging
import sys
from pathlib import Path
from typing import Any

import requests
import streamlit as st

_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

logger = logging.getLogger(__name__)


def _validate_us_sector_artifact(
    data: Any,
    *,
    cache_age_hours: float | None = None,
    now_utc: datetime | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Accept only a sector snapshot inside the shared daily-close policy.

    A recently modified cache file is not necessarily a recently observed
    market. The artifact's ``as_of`` is authoritative; the file age is an
    additional guard for local caches. Returning a rejection record lets the
    page explain why it is blank instead of silently displaying old prices.
    """
    if not isinstance(data, dict) or not data.get("sectors"):
        return None, {
            "status": "Unavailable",
            "message": "US sector artifact has no usable sector rows.",
        }

    as_of = data.get("as_of")
    if as_of in (None, "", "—"):
        return None, {
            "status": "Unavailable",
            "message": "US sector artifact has no observation date.",
        }

    from market_monitor.config import FRESHNESS_POLICIES
    from market_monitor.freshness import classify_daily_observation

    observation = classify_daily_observation(
        as_of,
        now_utc=now_utc,
        observation_type="daily_close",
    )
    status = str(observation.get("status") or "Unavailable")
    max_cache_age_hours = (
        FRESHNESS_POLICIES["daily_close"]["stale_after_calendar_days"] * 24
    )
    if status in {"Stale", "Invalid", "Unavailable"}:
        return None, {
            **observation,
            "status": status,
            "message": f"US sector artifact is {status.lower()} (as of {as_of}).",
        }
    if cache_age_hours is not None and cache_age_hours > max_cache_age_hours:
        return None, {
            **observation,
            "status": "Stale",
            "message": (
                f"US sector local cache is {cache_age_hours:.1f} hours old; "
                f"the limit is {max_cache_age_hours:.0f} hours."
            ),
        }

    accepted = dict(data)
    accepted["freshness_status"] = status
    accepted["freshness"] = observation
    return accepted, observation


@st.cache_data(ttl=1800, show_spinner=False)
def load_us_sector_artifact() -> dict[str, Any]:
    """Fetch US Sector & Sub-industry artifact from R2, local cache, or live fallback."""
    cache_key = "us_sector_latest.json"
    rejected: list[str] = []

    def _accept(
        data: Any,
        source: str,
        *,
        cache_age_hours: float | None = None,
    ) -> dict[str, Any] | None:
        accepted, freshness = _validate_us_sector_artifact(
            data,
            cache_age_hours=cache_age_hours,
        )
        if accepted is None:
            rejected.append(f"{source}: {freshness.get('message', 'rejected')}")
            logger.warning("Rejected %s US sector artifact: %s", source, freshness)
            return None
        accepted["source"] = source
        if cache_age_hours is not None:
            accepted["cache_age_hours"] = cache_age_hours
        return accepted

    # 1. Cloudflare R2 / public CDN
    try:
        from market_monitor.us_etf.storage_r2 import get_r2_config
        cfg = get_r2_config()
        public_url = cfg.get("R2_PUBLIC_URL")
        if public_url:
            target_url = f"{public_url.rstrip('/')}/market-monitor/latest/{cache_key}"
            resp = requests.get(target_url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                accepted = _accept(data, "r2")
                if accepted is not None:
                    return accepted
    except Exception as exc:
        logger.warning("R2 remote fetch failed: %s, falling back to local cache", exc)

    # 2. Git-ignored local cache, carrying its own age
    try:
        from market_monitor.us_etf.storage_r2 import (
            load_local_cache_json,
            local_cache_age_hours,
        )
        local_data = load_local_cache_json(cache_key)
        if local_data:
            accepted = _accept(
                local_data,
                "local_cache",
                cache_age_hours=local_cache_age_hours(cache_key),
            )
            if accepted is not None:
                return accepted
    except Exception as exc:
        logger.warning("Local cache read failed: %s", exc)

    # 3. Live generation fallback if yfinance is installed
    try:
        from market_monitor.us_etf.fetch import (
            build_us_sector_artifact,
            fetch_us_etf_history,
        )
        df = fetch_us_etf_history(period="2y")
        if not df.empty:
            artifact = build_us_sector_artifact(df)
            accepted = _accept(artifact, "live")
            if accepted is not None:
                return accepted
    except Exception as exc:
        logger.error("Live fallback generation failed or dependency missing: %s", exc)

    message = (
        "No current US sector snapshot is available."
        if not rejected
        else "Current US sector snapshots were rejected: " + " | ".join(rejected[:3])
    )
    return {
        "as_of": "—",
        "sectors": [],
        "sub_industries": {},
        "source": "unavailable",
        "freshness_status": "Stale" if any("stale" in item.lower() for item in rejected) else "Unavailable",
        "freshness_message": message,
    }
