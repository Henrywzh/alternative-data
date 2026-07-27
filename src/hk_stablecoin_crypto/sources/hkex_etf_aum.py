"""HKEX Integrated Fund Platform ETF AUM Source.

Verified live 2026-07-27. Monthly AUM data back to Sept 2024 inception. 
Harvest Ether (3179.HK, BUT245 guessed and 404'd) is the only unresolved fundId.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from ..config import HKEX_ETF_API_BASE, HKEX_ETF_FUNDS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = ["month", "aum_usd", "fund_id", "ticker", "name", "fetched_at"]


def fetch_etf_aum(fund_id: str, pages: int = 24) -> pd.DataFrame:
    """Fetch monthly AUM history for a single HKEX ETF."""
    now_str = datetime.now(timezone.utc).isoformat()
    
    params = {
        "fundId": fund_id,
        "page": "1",
        "size": str(pages),
        "startDate": "",
        "endDate": "",
        "lang": "en",
    }
    
    resp = requests.get(HKEX_ETF_API_BASE, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    
    rows = []
    records = data.get("data", []) if isinstance(data.get("data"), list) else (data.get("data", {}).get("list", []) if isinstance(data.get("data"), dict) else [])
    if not records and isinstance(data, list):
        records = data
        
    for rec in records:
        date_val = rec.get("fundSizeDate") or rec.get("fundSizeMonth") or rec.get("reportDate") or rec.get("date")
        aum_val = rec.get("fundSize") or rec.get("fundSizeUsd") or rec.get("aum")
        if isinstance(aum_val, str):
            try:
                aum_val = float(aum_val.replace(",", ""))
            except ValueError:
                pass
                
        rows.append({
            "month": str(date_val)[:7] if date_val else None,
            "aum_usd": aum_val,  # Value is directly in Millions USD ($M USD)
            "fund_id": fund_id,
            "fetched_at": now_str,
        })
        
    if not rows:
        return pd.DataFrame(columns=["month", "aum_usd", "fund_id", "fetched_at"])
        
    df = pd.DataFrame(rows)
    
    save_raw_snapshot(
        f"hkex_etf_{fund_id}",
        data,
        file_ext="json",
        source_url=resp.url,
    )
    
    return df


def fetch_all_etf_aum() -> pd.DataFrame:
    """Fetch AUM for all known HKEX crypto ETFs."""
    dfs = []
    
    for fund in HKEX_ETF_FUNDS:
        fund_id = fund.get("fund_id")
        if fund_id is None:
            logger.warning(f"{fund['name']} ({fund['ticker']}) fundId unknown — skipping. Look up via ifp.hkex.com.hk and add to config.")
            continue
            
        try:
            df = fetch_etf_aum(fund_id)
            if not df.empty:
                df["ticker"] = fund["ticker"]
                df["name"] = fund["name"]
                for col in SCHEMA_COLUMNS:
                    if col not in df.columns:
                        df[col] = None
                dfs.append(df[SCHEMA_COLUMNS])
        except Exception as exc:
            logger.exception(f"Failed to fetch AUM for {fund['ticker']}")
            
    if not dfs:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
        
    return pd.concat(dfs, ignore_index=True)
