import os
import time
import requests
import pandas as pd
from typing import Any, Dict, List, Optional

from ..config import CENTALINE_TRANSACTION_SEARCH_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

TRANSACTION_COLUMNS = [
    "source_record_id",
    "estate_name",
    "building_name",
    "floor_level",
    "unit_flat",
    "date",
    "transaction_date",
    "price_hkd",
    "saleable_area_sqft",
    "unit_price_hkd_sqft",
    "source_url",
    "source_platform",
    "source_page",
]


def _parse_transaction_record(record: Dict[str, Any]) -> Dict[str, Any]:
    estate_name = record.get("estateName") or record.get("bigEstateName") or record.get("buildingName")
    building_name = record.get("buildingName")
    raw_date = record.get("insDate")
    iso_date = raw_date.split("T")[0] if raw_date else None
    price = record.get("transactionPrice")
    try:
        price_hkd = float(price) if price is not None else None
    except (TypeError, ValueError):
        price_hkd = None
    area = record.get("nArea")
    try:
        area_sqft = float(area) if area not in (None, "") else None
    except (TypeError, ValueError):
        area_sqft = None
    return {
        "source_record_id": record.get("id"),
        "estate_name": estate_name,
        "building_name": building_name,
        "floor_level": record.get("yAxis"),
        "unit_flat": record.get("xAxis"),
        "date": iso_date,
        "transaction_date": iso_date,
        "price_hkd": price_hkd,
        "saleable_area_sqft": area_sqft,
        "unit_price_hkd_sqft": record.get("nUnitPrice"),
        "source_url": record.get("detailUrl"),
        "source_platform": "Centaline Property Agency",
        "source_page": CENTALINE_TRANSACTION_SEARCH_URL,
        "post_type": record.get("postType"),
    }


def fetch_centaline_transaction_pilot(
    *, lookback_days: Optional[int] = None, max_records: Optional[int] = None
) -> pd.DataFrame:
    """Fetch a bounded pilot of real, per-unit Centaline sale transaction records.

    Reverse-engineered from the ``findproperty`` Nuxt app's
    ``Transaction/Search`` Vuex action (the backend for
    https://hk.centanet.com/findproperty/list/transaction, "最新樓盤成交" /
    "Latest Property Transactions"). No authentication is required.

    Verified live: a real request for the last 7 days returned genuine sale
    records for known HK developments (e.g. "鑽嶺" in Wong Tai Sin,
    HK$4,100,000 for a 286 sqft unit -- internally consistent with its
    reported HK$14,336/sqft unit price), with a working ``detailUrl`` back
    to the same public page. Requesting with no ``postType`` filter returns
    only sale ("S") transactions; this pilot does not request rentals.
    """
    lookback_days = lookback_days or int(os.getenv("HK_REALESTATE_CENTALINE_LOOKBACK_DAYS", "7"))
    max_records = max_records or int(os.getenv("HK_REALESTATE_CENTALINE_MAX_RECORDS", "300"))
    page_size = min(100, max_records)
    request_delay = float(os.getenv("HK_REALESTATE_CENTALINE_DELAY", "0.2"))

    session = requests.Session()
    session.headers.update(
        {
            **DEFAULT_HEADERS,
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Referer": "https://hk.centanet.com/findproperty/list/transaction",
        }
    )

    records: List[Dict[str, Any]] = []
    offset = 0
    raw_pages = []
    while len(records) < max_records:
        body = {
            "day": lookback_days,
            "sort": "InsOrRegDate",
            "order": "Descending",
            "size": page_size,
            "offset": offset,
            "pageSource": "search",
        }
        resp = session.post(CENTALINE_TRANSACTION_SEARCH_URL, json=body, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
        raw_pages.append(payload)
        page_data = payload.get("data") or []
        if not page_data:
            break
        records.extend(page_data)
        offset += page_size
        if offset >= (payload.get("count") or 0):
            break
        time.sleep(request_delay)

    if raw_pages:
        import json

        save_raw_snapshot(
            "centaline_transaction_search",
            json.dumps(raw_pages, ensure_ascii=False),
            file_ext="json",
            source_url=CENTALINE_TRANSACTION_SEARCH_URL,
        )

    records = records[:max_records]
    parsed = [_parse_transaction_record(r) for r in records]
    df = pd.DataFrame(parsed, columns=TRANSACTION_COLUMNS + ["post_type"])
    if not df.empty:
        df = df[df["post_type"] == "S"].drop(columns=["post_type"])
        df = df.dropna(subset=["source_record_id"]).drop_duplicates(subset=["source_record_id"]).reset_index(drop=True)
    else:
        df = df.drop(columns=["post_type"])
    df.attrs.update(source_url=CENTALINE_TRANSACTION_SEARCH_URL)
    return df
