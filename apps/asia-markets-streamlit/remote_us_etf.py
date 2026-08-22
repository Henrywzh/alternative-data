"""Remote artifact loader for US Sector & Sub-industry ETFs.

Supports fetching from Cloudflare R2 / Public CDN with automatic fallback to
git-ignored local cache or on-demand fetch.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import requests
import streamlit as st

# Streamlit puts the *script's* directory on sys.path, not the working
# directory, so neither ``src.market_monitor`` nor ``market_monitor`` resolves
# in the live app on its own -- the package is not installed either. Put the
# repo root on the path here so the import works the same under streamlit run,
# pytest and a plain interpreter.
_REPO_ROOT = str(Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from src.market_monitor.us_etf.fetch import (
    build_us_sector_artifact,
    fetch_us_etf_history,
)
from src.market_monitor.us_etf.storage_r2 import (
    get_r2_config,
    load_local_cache_json,
    local_cache_age_hours,
)

logger = logging.getLogger(__name__)


@st.cache_data(ttl=1800, show_spinner=False)
def load_us_sector_artifact() -> dict[str, Any]:
    """Fetch US Sector & Sub-industry artifact from R2, local cache, or live fallback."""
    cfg = get_r2_config()
    public_url = cfg.get("R2_PUBLIC_URL")
    cache_key = "us_sector_latest.json"

    # Each tier stamps where the data came from. Without it a month-old local
    # cache and a fresh publish render identically, and a board built on a
    # stale read looks exactly like one built on today's.
    # 1. Cloudflare R2 / public CDN
    if public_url:
        target_url = f"{public_url.rstrip('/')}/market-monitor/latest/{cache_key}"
        try:
            resp = requests.get(target_url, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("sectors"):
                    data["source"] = "r2"
                    return data
        except Exception as exc:
            logger.warning("R2 remote fetch failed: %s, falling back to local cache", exc)

    # 2. Git-ignored local cache, carrying its own age
    local_data = load_local_cache_json(cache_key)
    if local_data and local_data.get("sectors"):
        local_data["source"] = "local_cache"
        local_data["cache_age_hours"] = local_cache_age_hours(cache_key)
        return local_data

    # 3. Live generation. Deliberately the same 2y window the pipeline uses:
    # a shorter one would silently change what RSI and the 60D metrics mean.
    try:
        df = fetch_us_etf_history(period="2y")
        if not df.empty:
            artifact = build_us_sector_artifact(df)
            artifact["source"] = "live"
            return artifact
    except Exception as exc:
        logger.error("Live fallback generation failed: %s", exc)

    return {"as_of": "—", "sectors": [], "sub_industries": {}, "source": "unavailable"}
