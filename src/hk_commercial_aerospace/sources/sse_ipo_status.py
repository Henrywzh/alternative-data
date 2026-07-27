"""SSE STAR Market IPO filing status fetcher.

Fetches the IPO filing status for aerospace companies on the Shanghai Stock Exchange.
"""

from __future__ import annotations

import logging
import json
import re
from datetime import datetime, timezone
import requests
import pandas as pd

from ..config import (
    DEFAULT_HEADERS,
    DEFAULT_TIMEOUT,
    SSE_SOAQUERY_URL,
    SSE_REFERER,
    IPO_RACE_COMPANIES,
)
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "name_en",
    "name_zh",
    "found",
    "audit_num",
    "status",
    "update_date",
    "fetched_at",
]


def fetch_ipo_status(company_name_zh: str) -> dict:
    """Fetch IPO filing status from SSE STAR Market."""
    headers = DEFAULT_HEADERS.copy()
    headers["Referer"] = SSE_REFERER

    params = {
        "sqlId": "SH_XM_LB",
        "keyword": company_name_zh,
        "isPagination": "true",
        "pageNum": "1",
        "pageSize": "10",
    }

    try:
        resp = requests.get(
            SSE_SOAQUERY_URL,
            params=params,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        resp.raise_for_status()
        raw_text = resp.text

        # Strip JSONP callback wrapper e.g., jsonpCallback({...})
        jsonp_match = re.search(r"^[^\(]*\((.*)\);?\s*$", raw_text, re.DOTALL)
        if jsonp_match:
            json_str = jsonp_match.group(1)
        else:
            json_str = raw_text

        data = json.loads(json_str)
        save_raw_snapshot(f"sse_ipo_status_{company_name_zh}", data, source_url=resp.url)

        results = data.get("pageHelp", {}).get("data", [])
        if not results:
            return {
                "company_zh": company_name_zh,
                "found": False,
                "audit_num": None,
                "status": "no_shanghai_filing",
                "update_date": None,
                "financing_amount": None,
            }

        # Take the first match
        first = results[0]
        # SSE JSONP response uses stockAuditNum for the numeric review ID
        # (e.g. 2174 for LandSpace, 2180 for CAS Space — confirmed 2026-07-26)
        raw_audit = first.get("stockAuditNum") or first.get("auditNum") or first.get("auditId")
        return {
            "company_zh": company_name_zh,
            "found": True,
            "audit_num": int(raw_audit) if raw_audit is not None else None,
            "status": first.get("auditStatus", "Unknown"),
            "update_date": first.get("updateDate"),
            "financing_amount": str(first.get("planIssueCapital", "")),
        }
    except Exception as e:
        logger.warning(f"Failed to fetch IPO status for {company_name_zh}: {e}")
        return {
            "company_zh": company_name_zh,
            "found": False,
            "audit_num": None,
            "status": "error",
            "update_date": None,
            "financing_amount": None,
        }


def fetch_all_ipo_statuses() -> pd.DataFrame:
    """Fetch IPO statuses for all tracked companies."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = []

    for comp in IPO_RACE_COMPANIES:
        name_en = comp["name_en"]
        name_zh = comp["name_zh"]
        status_data = fetch_ipo_status(name_zh)
        
        # We need audit_num specifically, so we'll try to extract it from the payload if it's there.
        # But if we rely on auditId we should make sure we grab it right. 
        # The prompt says `audit_num: int|None`. I'll cast it if found.
        audit_num = status_data.get("audit_num")
        if audit_num is not None:
            try:
                audit_num = int(audit_num)
            except (ValueError, TypeError):
                audit_num = None
                
        # Some fields in the sample response might be named differently, but we map to SCHEMA_COLUMNS.
        # Ensure we don't accidentally override the expected status if the fetch fails completely
        status = status_data["status"]

        rows.append({
            "name_en": name_en,
            "name_zh": name_zh,
            "found": status_data["found"],
            "audit_num": audit_num,
            "status": status,
            "update_date": status_data["update_date"],
            "fetched_at": fetched_at,
        })

    if not rows:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    return pd.DataFrame(rows)[SCHEMA_COLUMNS]
