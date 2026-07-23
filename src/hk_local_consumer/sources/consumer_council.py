import json
import logging
import pandas as pd
import requests
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from ..config import CONSUMER_COUNCIL_PRICE_WATCH_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

def parse_consumer_council_payload(payload: Union[Dict[str, Any], list]) -> pd.DataFrame:
    """Parse HK Consumer Council Online Price Watch payload into normalized dataset."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    items = []
    
    if isinstance(payload, dict):
        items = payload.get("items") or payload.get("products") or payload.get("data") or [payload]
    elif isinstance(payload, list):
        items = payload

    records = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        prod_id = str(item.get("code") or item.get("id") or item.get("product_id") or f"PROD_{idx:04d}")
        prod_name = str(item.get("name") or item.get("title") or item.get("product_name") or "Retail Item")
        cat = str(item.get("category") or item.get("cat_name") or "Personal Care & Cosmetics")
        brand = str(item.get("brand") or item.get("brand_name") or "Generic")
        supermarket = str(item.get("supermarket") or item.get("store_name") or "Watsons / Mannings")
        
        price_val = pd.to_numeric(item.get("price") or item.get("current_price"), errors="coerce")
        orig_price_val = pd.to_numeric(item.get("original_price") or item.get("normal_price") or price_val, errors="coerce")
        
        obs_date = str(item.get("date") or item.get("updated_at") or today_str)[:10]

        p_num = float(price_val) if pd.notna(price_val) else 0.0
        op_num = float(orig_price_val) if pd.notna(orig_price_val) else p_num
        is_sale = bool(item.get("on_sale")) or (op_num > p_num)

        records.append({
            "date": obs_date,
            "product_id": prod_id,
            "product_name": prod_name,
            "category": cat,
            "brand": brand,
            "supermarket_name": supermarket,
            "price_hkd": p_num,
            "original_price_hkd": op_num,
            "is_on_sale": is_sale,
        })

    df_norm = pd.DataFrame(records)
    if df_norm.empty:
        df_norm = pd.DataFrame(columns=[
            "date", "product_id", "product_name", "category", "brand",
            "supermarket_name", "price_hkd", "original_price_hkd", "is_on_sale"
        ])
    return df_norm


def fetch_consumer_council_prices(custom_url: Optional[str] = None) -> pd.DataFrame:
    """Fetch and parse HK Consumer Council Online Price Watch prices."""
    url = custom_url or CONSUMER_COUNCIL_PRICE_WATCH_URL
    raw_path = None
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        if resp.status_code == 200:
            payload = resp.json()
            raw_path = save_raw_snapshot("consumer_council_prices", payload, file_ext="json", source_url=url)
            df = parse_consumer_council_payload(payload)
            df.attrs["raw_snapshot"] = str(raw_path)
            df.attrs["source_url"] = url
            return df
    except Exception as exc:
        logger.warning(f"Network fetch failed for Consumer Council prices ({exc}).")

    logger.error("Consumer Council price watch unavailable; returning empty dataset (no fabricated data).")
    df_empty = pd.DataFrame(columns=[
        "date", "product_id", "product_name", "category", "brand",
        "supermarket_name", "price_hkd", "original_price_hkd", "is_on_sale"
    ])
    df_empty.attrs["raw_snapshot"] = str(raw_path) if raw_path else None
    df_empty.attrs["source_url"] = url
    return df_empty
