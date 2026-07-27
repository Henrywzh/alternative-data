"""Google Patents fetcher for commercial aerospace companies."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
import requests
import pandas as pd

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    GOOGLE_PATENTS_URL,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

PATENT_ASSIGNEES = [
    "LandSpace 蓝箭航天",
    "CAS Space 中科宇航",
    "Galactic Energy 星河动力",
    "Space Pioneer 天兵科技",
    "i-Space 星际荣耀",
]

SCHEMA_COLUMNS = [
    "assignee_query",
    "estimated_count",
    "fetched_at",
]


def fetch_patent_count(company_name: str) -> dict:
    """Fetch estimated patent count from Google Patents."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    params = {
        "q": company_name,
        "num": "10",
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
    }
    
    count = None
    try:
        resp = requests.get(
            GOOGLE_PATENTS_URL,
            params=params,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        
        save_raw_snapshot(f"google_patents_{company_name.replace(' ', '_')}", data, source_url=resp.url)
        
        results_obj = data.get("results", {})
        total_results = results_obj.get("total_num_results", 0)
        if total_results > 0:
            count = total_results
    except Exception as e:
        logger.warning(f"Failed to fetch patents for {company_name}: {e}")

    return {
        "assignee_query": company_name,
        "estimated_count": count,
        "fetched_at": fetched_at,
    }


def fetch_all_patent_counts() -> pd.DataFrame:
    """Fetch patent counts for all tracked assignees."""
    rows = []
    
    for assignee in PATENT_ASSIGNEES:
        rows.append(fetch_patent_count(assignee))
        
    if not rows:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
        
    return pd.DataFrame(rows)[SCHEMA_COLUMNS]
