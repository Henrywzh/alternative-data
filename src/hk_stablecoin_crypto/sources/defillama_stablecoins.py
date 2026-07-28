"""DefiLlama Stablecoins & DEX Analytics Source.

As of 2026-07-26, 413 tracked stablecoins, USDT ~$184.3B, USDC ~$73.5B. 
AxCNH and HKDAP are NOT listed yet (their appearance would be a signal). 
CNHT (Tether CNH, ~$3M) is a different, pre-existing coin — not the same as AnchorX's AxCNH.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFILLAMA_URL, HK_CHINA_STABLECOINS_TO_WATCH
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = ["name", "symbol", "circulating_usd", "fetched_at"]


def fetch_stablecoin_supply() -> pd.DataFrame:
    """Fetch stablecoin circulating supply from DefiLlama."""
    now_str = datetime.now(timezone.utc).isoformat()
    
    try:
        resp = requests.get(DEFILLAMA_URL, headers=DEFAULT_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        pegged_assets = data.get("peggedAssets", [])
        rows = []
        
        for asset in pegged_assets:
            symbol = asset.get("symbol")
            
            if symbol in HK_CHINA_STABLECOINS_TO_WATCH:
                logger.info(f"SIGNIFICANT EVENT: HK/China stablecoin {symbol} now tracked on DefiLlama — this is itself a launch signal")
                
            rows.append({
                "name": asset.get("name"),
                "symbol": symbol,
                "circulating_usd": asset.get("circulating", {}).get("peggedUSD"),
                "fetched_at": now_str,
            })
            
        if not rows:
            logger.warning("No pegged assets found in DefiLlama response")
            return pd.DataFrame(columns=SCHEMA_COLUMNS)
            
        result = pd.DataFrame(rows)[SCHEMA_COLUMNS]
        
        raw_path = save_raw_snapshot(
            "defillama_stablecoins",
            data,
            file_ext="json",
            source_url=DEFILLAMA_URL,
        )
        result.attrs["raw_snapshot"] = str(raw_path)
        result.attrs["source_url"] = DEFILLAMA_URL
        
        return result
        
    except Exception as exc:
        logger.exception("Failed to fetch DefiLlama stablecoins")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)


HISTORY_URL = "https://stablecoins.llama.fi/stablecoincharts/all"
HISTORY_SCHEMA_COLUMNS = ["date", "circulating_usd_bn", "fetched_at"]


def fetch_stablecoin_history(days: int = 365) -> pd.DataFrame:
    """Fetch global stablecoin total circulating supply time series from DefiLlama (default 365 days)."""
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        resp = requests.get(HISTORY_URL, headers=DEFAULT_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        rows = []
        for item in data:
            ts = int(item.get("date", 0))
            if ts <= 0:
                continue
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            total_circ = item.get("totalCirculating", {}).get("peggedUSD", 0)
            if total_circ > 0:
                rows.append({
                    "date": dt,
                    "circulating_usd_bn": round(total_circ / 1e9, 2),
                    "fetched_at": now_str,
                })
                
        if not rows:
            return pd.DataFrame(columns=HISTORY_SCHEMA_COLUMNS)
            
        df = pd.DataFrame(rows)
        save_raw_snapshot("defillama_stablecoin_history", data, file_ext="json", source_url=HISTORY_URL)
        
        # Filter for the recent N days for dashboard chart display
        if days > 0 and len(df) > days:
            df = df.tail(days)
            
        return df[HISTORY_SCHEMA_COLUMNS].reset_index(drop=True)
    except Exception as exc:
        logger.exception("Failed to fetch DefiLlama stablecoin history")
        return pd.DataFrame(columns=HISTORY_SCHEMA_COLUMNS)


def fetch_stablecoin_chain_distribution() -> pd.DataFrame:
    """Fetch top 10 blockchain chains by total stablecoin circulating supply ($B USD)."""
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        resp = requests.get(DEFILLAMA_URL, headers=DEFAULT_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        pegged = data.get("peggedAssets", [])
        chain_totals: dict[str, float] = {}
        
        for asset in pegged:
            cc = asset.get("chainCirculating", {})
            for chain, info in cc.items():
                circ = info.get("current", {}).get("peggedUSD", 0) or 0
                if circ > 0:
                    chain_totals[chain] = chain_totals.get(chain, 0.0) + float(circ)
                    
        sorted_chains = sorted(chain_totals.items(), key=lambda x: x[1], reverse=True)
        rows = [
            {
                "chain": chain,
                "circulating_usd_bn": round(val / 1e9, 2),
                "fetched_at": now_str,
            }
            for chain, val in sorted_chains[:10]
        ]
        
        if not rows:
            return pd.DataFrame(columns=["chain", "circulating_usd_bn", "fetched_at"])
            
        return pd.DataFrame(rows)
    except Exception as exc:
        logger.exception("Failed to fetch DefiLlama stablecoin chain distribution")
        return pd.DataFrame(columns=["chain", "circulating_usd_bn", "fetched_at"])


DEX_VOLUME_URL = "https://api.llama.fi/overview/dexs"


def fetch_dex_volume_history(days: int = 365) -> pd.DataFrame:
    """Fetch global daily DEX trading volume history ($B USD/day) from DefiLlama."""
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        resp = requests.get(DEX_VOLUME_URL, headers=DEFAULT_HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        chart = data.get("totalDataChart", [])
        rows = []
        for pt in chart:
            if not isinstance(pt, list) or len(pt) < 2:
                continue
            ts = int(pt[0])
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            vol_usd = float(pt[1] or 0.0)
            rows.append({
                "date": dt,
                "dex_volume_usd_bn": round(vol_usd / 1e9, 2),
                "fetched_at": now_str,
            })
            
        if not rows:
            return pd.DataFrame(columns=["date", "dex_volume_usd_bn", "fetched_at"])
            
        df = pd.DataFrame(rows)
        save_raw_snapshot("defillama_dex_volume_history", data, file_ext="json", source_url=DEX_VOLUME_URL)
        
        if days > 0 and len(df) > days:
            df = df.tail(days)
            
        return df.reset_index(drop=True)
    except Exception as exc:
        logger.exception("Failed to fetch DefiLlama DEX volume history")
        return pd.DataFrame(columns=["date", "dex_volume_usd_bn", "fetched_at"])
