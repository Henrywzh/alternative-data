"""Polymarket Regulatory Catalysts Source.

No HK-specific Polymarket markets found as of 2026-07-26 ("Hong Kong crypto" query returns unrelated results). 
Use for global/US regulatory catalyst angle only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from ..config import POLYMARKET_SEARCH_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

POLYMARKET_QUERIES = ["stablecoin", "bitcoin ETF", "crypto regulation", "USDC", "Circle"]
SCHEMA_COLUMNS = ["title", "probability", "end_date", "market_id", "fetched_at"]


def fetch_relevant_markets(query: str) -> pd.DataFrame:
    """Fetch relevant markets using public-search endpoint."""
    now_str = datetime.now(timezone.utc).isoformat()
    
    try:
        resp = requests.get(POLYMARKET_SEARCH_URL, params={"q": query}, timeout=15)
        resp.raise_for_status()
        
        data = resp.json()
        markets = data if isinstance(data, list) else data.get("markets", [])
        
        rows = []
        for m in markets:
            probs = m.get("outcomePrices", [])
            prob = float(probs[0]) if probs else None
            
            rows.append({
                "title": m.get("question", m.get("title", "")),
                "probability": prob,
                "end_date": m.get("endDate", m.get("resolutionDate", "")),
                "market_id": m.get("id", m.get("conditionId", "")),
                "fetched_at": now_str,
            })
            
        if not rows:
            return pd.DataFrame(columns=SCHEMA_COLUMNS)
            
        return pd.DataFrame(rows)[SCHEMA_COLUMNS]
        
    except Exception as exc:
        logger.exception(f"Failed to fetch Polymarket for query: {query}")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)


def fetch_all_polymarket_catalysts() -> pd.DataFrame:
    """Fetch and combine all relevant Polymarket regulatory catalysts."""
    dfs = []
    
    for query in POLYMARKET_QUERIES:
        df = fetch_relevant_markets(query)
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
        source_url=POLYMARKET_SEARCH_URL,
    )
    
    return combined.reset_index(drop=True)
