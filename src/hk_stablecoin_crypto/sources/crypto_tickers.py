"""Coinbase & Binance Crypto Tickers and Fear & Greed Index.

COIN/CRCL price+volume is a confirmed leading indicator for MACRO/REGULATORY-CATALYST-DRIVEN sector-wide moves (~1 week lead, n=2: GENIUS Act case confirmed, Jinyong/AnchorX case does NOT show this pattern). NOT predictive of idiosyncratic single-company deal announcements. Do not treat as a blanket predictor.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from ..config import BINANCE_TICKER_URL, COINBASE_TICKER_URL, FEAR_GREED_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)


def fetch_coinbase_btc_ticker() -> dict:
    """Fetch Coinbase BTC-USD ticker."""
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        resp = requests.get(COINBASE_TICKER_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return {
            "price_usd": float(data.get("price", 0.0)),
            "volume_24h": float(data.get("volume", 0.0)) if data.get("volume") else None,
            "fetched_at": now_str,
        }
    except Exception as exc:
        logger.exception("Failed to fetch Coinbase ticker")
        return {"price_usd": None, "volume_24h": None, "fetched_at": now_str, "error": str(exc)}


def fetch_binance_btc_ticker() -> dict:
    """Fetch Binance BTCUSDT ticker."""
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        resp = requests.get(BINANCE_TICKER_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return {
            "price_usd": float(data.get("price", 0.0)),
            "fetched_at": now_str,
        }
    except Exception as exc:
        logger.exception("Failed to fetch Binance ticker")
        return {"price_usd": None, "fetched_at": now_str, "error": str(exc)}


def compute_coinbase_premium() -> dict:
    """Compute Coinbase premium over Binance in basis points."""
    now_str = datetime.now(timezone.utc).isoformat()
    coinbase = fetch_coinbase_btc_ticker()
    binance = fetch_binance_btc_ticker()
    
    cb_price = coinbase.get("price_usd")
    bn_price = binance.get("price_usd")
    
    if cb_price and bn_price:
        premium_bps = (cb_price - bn_price) / bn_price * 10000
        return {
            "coinbase_price_usd": cb_price,
            "binance_price_usd": bn_price,
            "premium_bps": premium_bps,
            "fetched_at": now_str,
        }
    
    return {
        "premium_bps": None,
        "error": "Failed to fetch one or both prices",
        "fetched_at": now_str,
    }


def fetch_fear_greed_index() -> dict:
    """Fetch Crypto Fear & Greed Index."""
    now_str = datetime.now(timezone.utc).isoformat()
    try:
        resp = requests.get(FEAR_GREED_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        latest = data.get("data", [])[0]
        return {
            "value": int(latest.get("value", 0)),
            "classification": latest.get("value_classification", ""),
            "fetched_at": now_str,
        }
    except Exception as exc:
        logger.exception("Failed to fetch Fear & Greed index")
        return {"value": None, "classification": None, "fetched_at": now_str, "error": str(exc)}


def fetch_fear_greed_history(limit: int = 0) -> pd.DataFrame:
    """Fetch Crypto Fear & Greed Index historical time series (limit=0 for full 2018-present history)."""
    now_str = datetime.now(timezone.utc).isoformat()
    url = f"https://api.alternative.me/fng/?limit={limit}"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        fng_data = data.get("data", [])
        
        rows = []
        for item in reversed(fng_data):
            ts = int(item.get("timestamp", 0))
            if ts <= 0:
                continue
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            rows.append({
                "date": dt,
                "score": int(item.get("value", 0)),
                "classification": item.get("value_classification", ""),
                "fetched_at": now_str,
            })
            
        if not rows:
            return pd.DataFrame(columns=["date", "score", "classification", "fetched_at"])
            
        save_raw_snapshot("fear_greed_history", data, file_ext="json", source_url=url)
        return pd.DataFrame(rows)
    except Exception as exc:
        logger.exception("Failed to fetch Fear & Greed history")
        return pd.DataFrame(columns=["date", "score", "classification", "fetched_at"])


def fetch_btc_price_history(limit: int = 365) -> pd.DataFrame:
    """Fetch BTC daily spot history from Binance.

    Binance limits each klines response to 1,000 rows. ``limit=0`` requests
    the latest ten years through bounded backward pagination; a positive
    limit preserves the older single-request API for callers that need a
    smaller window.
    """
    now_str = datetime.now(timezone.utc).isoformat()
    url = "https://api.binance.com/api/v3/klines"
    try:
        target_days = limit if limit > 0 else 3653
        batches: list[list[list[object]]] = []
        remaining = target_days
        end_time: int | None = None
        while remaining > 0:
            batch_limit = min(1000, remaining)
            params: dict[str, object] = {
                "symbol": "BTCUSDT",
                "interval": "1d",
                "limit": batch_limit,
            }
            if end_time is not None:
                params["endTime"] = end_time
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            batch = resp.json()
            if not isinstance(batch, list) or not batch:
                break
            batches.append(batch)
            remaining -= len(batch)
            oldest_open_time = int(batch[0][0])
            if len(batch) < batch_limit:
                break
            end_time = oldest_open_time - 1

        data = [item for batch in batches for item in batch]

        rows = []
        for kline in data:
            ts = int(kline[0]) / 1000.0
            dt = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
            close_price = float(kline[4])
            rows.append({
                "date": dt,
                "btc_price_usd": round(close_price, 2),
                "fetched_at": now_str,
            })
            
        if not rows:
            return pd.DataFrame(columns=["date", "btc_price_usd", "fetched_at"])

        result = pd.DataFrame(rows).drop_duplicates(subset=["date"]).sort_values("date")
        result = result.tail(target_days).reset_index(drop=True)
        save_raw_snapshot("btc_price_history", data, file_ext="json", source_url=url)
        return result
    except Exception as exc:
        logger.exception("Failed to fetch BTC price history")
        return pd.DataFrame(columns=["date", "btc_price_usd", "fetched_at"])


def fetch_all_crypto_signals() -> dict:
    """Fetch all crypto market signals."""
    return {
        "coinbase_premium": compute_coinbase_premium(),
        "fear_greed": fetch_fear_greed_index(),
    }
