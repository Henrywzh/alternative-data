"""Polymarket Regulatory & Macro Catalysts Source.

Fetches active events using tag_slug parameter (tag_slug=crypto, tag_slug=fed-rates, tag_slug=etf, tag_slug=finance)
to guarantee 100% financial and regulatory relevance without sports/esports noise.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

POLYMARKET_TAG_SLUGS = ["crypto", "fed-rates", "etf", "finance"]
POLYMARKET_EVENTS_URL = "https://gamma-api.polymarket.com/events"
SCHEMA_COLUMNS = ["title", "probability", "end_date", "market_id", "fetched_at"]


def fetch_markets_by_tag(tag_slug: str) -> pd.DataFrame:
    """Fetch active markets using Polymarket tag_slug parameter."""
    now_str = datetime.now(timezone.utc).isoformat()
    params = {
        "active": "true",
        "closed": "false",
        "limit": "20",
        "tag_slug": tag_slug,
    }
    
    try:
        resp = requests.get(POLYMARKET_EVENTS_URL, params=params, timeout=15)
        resp.raise_for_status()
        events = resp.json()
        
        rows = []
        for ev in events if isinstance(events, list) else []:
            mkts = ev.get("markets", []) if isinstance(ev, dict) else []
            if not mkts:
                continue
            m = mkts[0]
            title = ev.get("title") or m.get("question") or m.get("title", "")
            
            raw_p = m.get("outcomePrices", [])
            if isinstance(raw_p, str):
                try:
                    raw_p = json.loads(raw_p)
                except (ValueError, TypeError):
                    raw_p = []
            
            prob = float(raw_p[0]) if (raw_p and isinstance(raw_p, list) and len(raw_p) > 0) else None
            
            rows.append({
                "title": title,
                "probability": prob,
                "end_date": str(m.get("endDate") or m.get("resolutionDate") or "")[:10],
                "market_id": str(m.get("id") or m.get("conditionId") or ""),
                "fetched_at": now_str,
            })
            
        if not rows:
            return pd.DataFrame(columns=SCHEMA_COLUMNS)
            
        return pd.DataFrame(rows)[SCHEMA_COLUMNS]
        
    except Exception as exc:
        logger.exception(f"Failed to fetch Polymarket events for tag_slug: {tag_slug}")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)


def fetch_all_polymarket_catalysts() -> pd.DataFrame:
    """Fetch and combine all relevant Polymarket regulatory & macro catalysts."""
    dfs = []
    
    for tag in POLYMARKET_TAG_SLUGS:
        df = fetch_markets_by_tag(tag)
        if not df.empty:
            dfs.append(df)
            
    if not dfs:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
        
    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.drop_duplicates(subset=["market_id"])
    
    save_raw_snapshot(
        "polymarket_catalysts",
        combined.to_dict(orient="records"),
        file_ext="json",
        source_url=POLYMARKET_EVENTS_URL,
    )
    
    return combined.reset_index(drop=True)
