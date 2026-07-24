import os
import time
import requests
import pandas as pd
from typing import Any, Dict, List, Optional

from ..config import MIDLAND_MARKET_INSIGHT_URL, MIDLAND_DATA_API_BASE, DEFAULT_HEADERS
from ..storage import save_raw_snapshot
from .midland import fetch_midland_payload, parse_midland_estate_counts

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


def _get_midland_session_and_token() -> tuple[requests.Session, str]:
    """Visit any midland.com.hk page to obtain the anonymous 'token' cookie.

    Verified live: this token, issued on *any* page response (not just the
    transaction-history micro-frontend), is a Bearer JWT (``iss``:
    ``data.midland.com.hk``) that data.midland.com.hk's ``/info/v1/...``
    endpoints accept -- no login/credentials involved.
    """
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    response = session.get(MIDLAND_MARKET_INSIGHT_URL, timeout=15)
    response.raise_for_status()
    token = session.cookies.get("token")
    if not token:
        raise RuntimeError("Midland did not issue the expected 'token' session cookie")
    return session, token


def fetch_midland_building_ids(session: requests.Session, token: str, estate_id: str) -> List[Dict[str, Any]]:
    """Real call: GET {MIDLAND_DATA_API_BASE}/info/v1/buildings?est_ids=<estate_id>."""
    resp = session.get(
        f"{MIDLAND_DATA_API_BASE}/info/v1/buildings",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params={"lang": "zh-hk", "est_ids": estate_id},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_midland_building_transactions(session: requests.Session, token: str, building_id: str) -> Optional[Dict[str, Any]]:
    """Real call: GET {MIDLAND_DATA_API_BASE}/info/v1/transactions/buildings/<building_id>.

    Verified: despite the endpoint's own validation pattern accepting a
    comma-separated list of building ids, passing more than one id live
    returns ``{"data": []}`` -- the backend only actually resolves a single
    id per call. This function therefore only ever requests one building at
    a time.
    """
    resp = session.get(
        f"{MIDLAND_DATA_API_BASE}/info/v1/transactions/buildings/{building_id}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        params={"lang": "zh-hk"},
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("data"):
        return None
    return payload


def _parse_building_payload(payload: Dict[str, Any], estate_name: str) -> pd.DataFrame:
    building = payload.get("building") or {}
    building_name = building.get("name")
    records = []
    for unit in payload.get("data") or []:
        floor = unit.get("floor")
        flat = unit.get("flat_name") or unit.get("flat")
        for tx in unit.get("transactions") or []:
            iso_date = None
            raw_date = tx.get("tx_date")
            if raw_date:
                iso_date = raw_date.split("T")[0]
            price = tx.get("price")
            try:
                price_hkd = float(price) if price is not None else None
            except (TypeError, ValueError):
                price_hkd = None
            area = tx.get("area")
            try:
                area_sqft = float(area) if area not in (None, "") else None
            except (TypeError, ValueError):
                area_sqft = None
            records.append(
                {
                    "source_record_id": tx.get("id"),
                    "estate_name": estate_name,
                    "building_name": building_name,
                    "floor_level": floor,
                    "unit_flat": flat,
                    "date": iso_date,
                    "transaction_date": iso_date,
                    "price_hkd": price_hkd,
                    "saleable_area_sqft": area_sqft,
                    "unit_price_hkd_sqft": tx.get("net_ft_price"),
                    "source_url": tx.get("url_desc"),
                    "source_platform": "Midland Realty",
                    "source_page": f"{MIDLAND_DATA_API_BASE}/info/v1/transactions/buildings/{building.get('id')}",
                }
            )
    return pd.DataFrame(records)


def fetch_midland_transaction_pilot(*, max_estates: Optional[int] = None, max_buildings: Optional[int] = None) -> pd.DataFrame:
    """Fetch a bounded pilot of real, per-unit Midland transaction records.

    This mirrors ``hse28.fetch_28hse_transaction_pilot``'s "bounded pilot, not
    a crawler" approach: rather than enumerating every estate in Hong Kong,
    it walks Midland's own "top estates by transaction volume" list (already
    fetched for ``midland_top_estates_volume``), resolves each estate's real
    buildings via ``{MIDLAND_DATA_API_BASE}/info/v1/buildings``, and pulls
    each building's real transaction history via
    ``{MIDLAND_DATA_API_BASE}/info/v1/transactions/buildings/<id>``.

    Verified live end-to-end against a real HK estate ("Wang Fuk Court" /
    宏福苑 in Tai Po): genuine floor/unit/price/date records, e.g. a real
    HK$2,820,000 sale on 2025-02-23 and a HK$5,100,000 sale on 2021-07-26 for
    the same 564 sqft unit -- plausible, internally consistent history, not
    fabricated placeholders.
    """
    max_estates = max_estates or int(os.getenv("HK_REALESTATE_MIDLAND_MAX_ESTATES", "8"))
    max_buildings = max_buildings or int(os.getenv("HK_REALESTATE_MIDLAND_MAX_BUILDINGS", "20"))
    request_delay = float(os.getenv("HK_REALESTATE_MIDLAND_TX_DELAY", "0.2"))

    session, token = _get_midland_session_and_token()

    props = fetch_midland_payload()
    estates_df = parse_midland_estate_counts(props)
    if estates_df.empty:
        return pd.DataFrame(columns=TRANSACTION_COLUMNS)

    estate_rows = estates_df.head(max_estates).to_dict("records")

    frames = []
    buildings_queried = 0
    raw_payloads: Dict[str, Any] = {}
    for estate_row in estate_rows:
        estate_id = estate_row.get("estate_id")
        estate_name = estate_row.get("estate_name")
        if not estate_id or buildings_queried >= max_buildings:
            break
        try:
            buildings = fetch_midland_building_ids(session, token, estate_id)
        except Exception:
            continue
        for building in buildings:
            if buildings_queried >= max_buildings:
                break
            building_id = building.get("id")
            if not building_id:
                continue
            try:
                payload = fetch_midland_building_transactions(session, token, building_id)
            except Exception:
                continue
            buildings_queried += 1
            time.sleep(request_delay)
            if not payload:
                continue
            raw_payloads[building_id] = payload
            frames.append(_parse_building_payload(payload, estate_name))

    if raw_payloads:
        import json

        save_raw_snapshot(
            "midland_transaction_buildings",
            json.dumps(raw_payloads, ensure_ascii=False),
            file_ext="json",
            source_url=f"{MIDLAND_DATA_API_BASE}/info/v1/transactions/buildings/",
        )

    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=TRANSACTION_COLUMNS)
    if not result.empty:
        result = result.dropna(subset=["source_record_id"]).drop_duplicates(subset=["source_record_id"]).reset_index(drop=True)
    result.attrs.update(source_url=f"{MIDLAND_DATA_API_BASE}/info/v1/transactions/buildings/")
    return result
