import json
import logging
import pandas as pd
import requests
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Union

from ..http import get_with_retry
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


# The Online Price Watch open data is published as CSV and has been for some
# time. This lane still asked for JSON -- CONSUMER_COUNCIL_PRICE_WATCH_URL ends
# in `pricewatch_en.csv` and answers `Content-Type: text/csv` -- so every run
# raised "Expecting value: line 1 column 1 (char 0)", returned an empty frame,
# and under `--strict` failed the whole stage-1 ingest. That is what kept the
# Asia Markets refresh in DEGRADED_RETAINED with a permanently open incident.
#
# consumer_council_pricewatch already fetches and parses exactly these bytes
# correctly, so this lane reshapes that frame to its own published column
# names rather than issuing a second request and running a second parser
# against the same URL.
_PRICEWATCH_TO_PRICE_WATCH = {
    "date": "date",
    "product_code": "product_id",
    "product_name": "product_name",
    "category_1": "category",
    "brand": "brand",
    "supermarket_code": "supermarket_name",
    "price": "price_hkd",
}


def fetch_consumer_council_prices(custom_url: Optional[str] = None) -> pd.DataFrame:
    """Fetch HK Consumer Council Online Price Watch prices.

    ``custom_url`` is still honoured for callers that point at a JSON payload
    of the historical shape; the default path reads the CSV the department
    actually publishes.
    """
    url = custom_url or CONSUMER_COUNCIL_PRICE_WATCH_URL
    raw_path = None
    try:
        if custom_url is not None:
            resp = get_with_retry(url)
            payload = resp.json()
            raw_path = save_raw_snapshot("consumer_council_prices", payload, file_ext="json", source_url=url)
            df = parse_consumer_council_payload(payload)
            df.attrs["raw_snapshot"] = str(raw_path)
            df.attrs["source_url"] = url
            return df

        from .consumer_council_pricewatch import fetch_consumer_council_pricewatch

        source = fetch_consumer_council_pricewatch()
        if not source.empty:
            df = source.rename(columns=_PRICEWATCH_TO_PRICE_WATCH)
            df = df[[column for column in _PRICEWATCH_TO_PRICE_WATCH.values() if column in df.columns]].copy()
            # The CSV carries an "offers" note but no pre-discount figure, so
            # original_price_hkd stays absent rather than being invented.
            df["original_price_hkd"] = pd.NA
            df["is_on_sale"] = (
                source["offers"].notna() & source["offers"].astype(str).str.strip().ne("")
                if "offers" in source.columns
                else False
            )
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
