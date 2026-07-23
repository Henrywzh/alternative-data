import logging
import pandas as pd
import requests
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from ..config import CNSD_API_BASE_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

def parse_cnsd_retail_payload(payload: Union[Dict[str, Any], list]) -> pd.DataFrame:
    """Parse C&SD Retail Sales & Visitor Arrivals payload into normalized structure."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m") + "-01"
    records = []
    
    items = []
    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("records") or [payload]
    elif isinstance(payload, list):
        items = payload

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        date_val = str(item.get("period") or item.get("month") or item.get("date") or today_str)[:7] + "-01"
        cat = str(item.get("category") or item.get("trade") or item.get("industry") or "Total Retail Sales")
        
        val_idx = pd.to_numeric(item.get("sales_value_index") or item.get("value_index"), errors="coerce")
        vol_idx = pd.to_numeric(item.get("sales_volume_index") or item.get("volume_index"), errors="coerce")
        arr_val = pd.to_numeric(item.get("visitor_arrivals_thousands") or item.get("visitors"), errors="coerce")

        records.append({
            "date": date_val,
            "category": cat,
            "sales_value_index": float(val_idx) if pd.notna(val_idx) else 100.0,
            "sales_volume_index": float(vol_idx) if pd.notna(vol_idx) else 100.0,
            "visitor_arrivals_thousands": float(arr_val) if pd.notna(arr_val) else 0.0,
        })

    df_norm = pd.DataFrame(records)
    if df_norm.empty:
        df_norm = pd.DataFrame(columns=["date", "category", "sales_value_index", "sales_volume_index", "visitor_arrivals_thousands"])
    return df_norm


def fetch_cnsd_retail_sales(custom_url: Optional[str] = None) -> pd.DataFrame:
    """Fetch C&SD Retail Sales Index & Visitor Arrivals monthly series."""
    url = custom_url or f"{CNSD_API_BASE_URL}?cv=620-67002&lang=en"
    raw_path = None
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        if resp.status_code == 200:
            payload = resp.json()
            raw_path = save_raw_snapshot("cnsd_retail_sales", payload, file_ext="json", source_url=url)
            df = parse_cnsd_retail_payload(payload)
            df.attrs["raw_snapshot"] = str(raw_path)
            df.attrs["source_url"] = url
            return df
    except Exception as exc:
        logger.warning(f"Network fetch failed for C&SD retail sales ({exc}).")

    logger.error("C&SD retail sales unavailable; returning empty dataset (no fabricated data).")
    df_empty = pd.DataFrame(columns=["date", "category", "sales_value_index", "sales_volume_index", "visitor_arrivals_thousands"])
    df_empty.attrs["raw_snapshot"] = str(raw_path) if raw_path else None
    df_empty.attrs["source_url"] = url
    return df_empty
