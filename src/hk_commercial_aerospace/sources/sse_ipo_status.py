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

# SSE currStatus numeric code mapping
SSE_STATUS_MAP = {
    1: "已受理",
    2: "已问询",
    3: "上市委会议通过",
    4: "提交注册",
    5: "注册生效",
    6: "中止",
    7: "终止",
}


def _configured_fallback(company_name_zh: str) -> dict | None:
    """Return the last reviewed IPO status when SSE is unavailable."""
    for company in IPO_RACE_COMPANIES:
        if company["name_zh"] == company_name_zh:
            return {
                "company_zh": company_name_zh,
                "found": company["audit_num"] is not None,
                "audit_num": company["audit_num"],
                "status": company["known_status"],
                "update_date": company["update_date"],
                "financing_amount": None,
            }
    return None


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

        # Map numeric currStatus code (e.g. 2 -> "已问询")
        curr_code = first.get("currStatus")
        if curr_code is not None:
            try:
                code_int = int(curr_code)
                status_str = SSE_STATUS_MAP.get(code_int, first.get("auditStatus", "Unknown"))
            except (ValueError, TypeError):
                status_str = str(curr_code)
        else:
            status_str = first.get("auditStatus", "Unknown")

        # Format updateDate from YYYYMMDDHHMMSS to YYYY-MM-DD
        raw_date = str(first.get("updateDate", ""))
        if len(raw_date) >= 8 and raw_date.isdigit():
            update_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
        else:
            update_date = raw_date or None

        return {
            "company_zh": company_name_zh,
            "found": True,
            "audit_num": int(raw_audit) if raw_audit is not None else None,
            "status": status_str,
            "update_date": update_date,
            "financing_amount": str(first.get("planIssueCapital", "")),
        }
    except Exception as e:
        fallback = _configured_fallback(company_name_zh)
        if fallback is not None:
            logger.warning(
                "Failed to fetch IPO status for %s: %s; using configured fallback last reviewed %s",
                company_name_zh,
                e,
                fallback["update_date"] or "status",
            )
            return fallback
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
        
        audit_num = status_data.get("audit_num")
        if audit_num is not None:
            try:
                audit_num = int(audit_num)
            except (ValueError, TypeError):
                audit_num = None
                
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
