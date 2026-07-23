import logging
import pandas as pd
import requests
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from ..config import CNSD_API_BASE_URL, CENSTATD_RESTAURANT_TABLE_ID, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

def parse_censtatd_restaurant_payload(payload: Union[Dict[str, Any], list]) -> pd.DataFrame:
    """Parse CenStatD Quarterly Restaurant Receipts & Purchases payload."""
    today_q = "2026-Q1"
    today_date = "2026-03-31"
    records = []

    items = []
    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("records") or [payload]
    elif isinstance(payload, list):
        items = payload

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        q_str = str(item.get("quarter") or item.get("period") or today_q)
        obs_date = str(item.get("date") or today_date)
        sector = str(item.get("sub_sector") or item.get("type") or "Fast food shops")
        
        rec_m = pd.to_numeric(item.get("total_receipts_hkd_m") or item.get("receipts_m"), errors="coerce")
        pur_m = pd.to_numeric(item.get("total_purchases_hkd_m") or item.get("purchases_m"), errors="coerce")
        rec_idx = pd.to_numeric(item.get("receipts_value_index") or item.get("receipts_idx"), errors="coerce")
        pur_idx = pd.to_numeric(item.get("purchases_value_index") or item.get("purchases_idx"), errors="coerce")

        records.append({
            "quarter": q_str,
            "date": obs_date,
            "sub_sector": sector,
            "total_receipts_hkd_m": float(rec_m) if pd.notna(rec_m) else 0.0,
            "total_purchases_hkd_m": float(pur_m) if pd.notna(pur_m) else 0.0,
            "receipts_value_index": float(rec_idx) if pd.notna(rec_idx) else 100.0,
            "purchases_value_index": float(pur_idx) if pd.notna(pur_idx) else 100.0,
        })

    df_norm = pd.DataFrame(records)
    if df_norm.empty:
        df_norm = pd.DataFrame(columns=[
            "quarter", "date", "sub_sector", "total_receipts_hkd_m",
            "total_purchases_hkd_m", "receipts_value_index", "purchases_value_index"
        ])
    return df_norm


def fetch_censtatd_restaurant_survey(custom_url: Optional[str] = None) -> pd.DataFrame:
    """Fetch CenStatD Quarterly Restaurant Receipts & Purchases Survey."""
    url = custom_url or f"{CNSD_API_BASE_URL}?cv={CENSTATD_RESTAURANT_TABLE_ID}&lang=en"
    raw_path = None
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        if resp.status_code == 200:
            payload = resp.json()
            raw_path = save_raw_snapshot("censtatd_restaurant_survey", payload, file_ext="json", source_url=url)
            df = parse_censtatd_restaurant_payload(payload)
            df.attrs["raw_snapshot"] = str(raw_path)
            df.attrs["source_url"] = url
            return df
    except Exception as exc:
        logger.warning(f"Network fetch failed for CenStatD restaurant survey ({exc}).")

    logger.error("CenStatD restaurant survey unavailable; returning empty dataset (no fabricated data).")
    df_empty = pd.DataFrame(columns=[
        "quarter", "date", "sub_sector", "total_receipts_hkd_m",
        "total_purchases_hkd_m", "receipts_value_index", "purchases_value_index"
    ])
    df_empty.attrs["raw_snapshot"] = str(raw_path) if raw_path else None
    df_empty.attrs["source_url"] = url
    return df_empty
