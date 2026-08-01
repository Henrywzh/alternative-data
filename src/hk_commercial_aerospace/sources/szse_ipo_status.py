"""Shenzhen Stock Exchange IPO project feed for aerospace-related issuers."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, SZSE_PROJECT_API_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "project_id",
    "company_name",
    "board",
    "status",
    "province",
    "industry",
    "sponsor",
    "law_firm",
    "accounting_firm",
    "update_date",
    "accept_date",
    "planned_financing_amount",
    "fetched_at",
]

TARGET_INDUSTRY = "铁路、船舶、航空航天和其他运输设备制造业"


def fetch_aerospace_ipo_projects(*, page_size: int = 100) -> pd.DataFrame:
    """Fetch current SZSE IPO projects classified in the aerospace industry.

    The official page exposes this JSON endpoint behind its JavaScript UI. We
    query the full industry classification rather than pretending every row is
    a pure commercial-space issuer; the returned industry field stays visible
    so aviation and rail names can be separated later.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    params = {
        "bizType": 1,
        "pageIndex": 0,
        "pageSize": min(page_size, 100),
        "industry": TARGET_INDUSTRY,
        "random": fetched_at,
    }
    headers = DEFAULT_HEADERS.copy()
    headers["Referer"] = "https://www.szse.cn/listing/projectdynamic/ipo/index.html"
    try:
        response = requests.get(
            SZSE_PROJECT_API_URL,
            params=params,
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        save_raw_snapshot("szse_aerospace_ipo", payload, source_url=response.url)
        rows = []
        for item in payload.get("data", []):
            rows.append({
                "project_id": item.get("prjid"),
                "company_name": item.get("cmpnm", ""),
                "board": item.get("boardName", ""),
                "status": item.get("prjst", ""),
                "province": item.get("regloc", ""),
                "industry": item.get("csrcind", ""),
                "sponsor": item.get("sprinst", ""),
                "law_firm": item.get("lawfm", ""),
                "accounting_firm": item.get("acctfm", ""),
                "update_date": item.get("updtdt", ""),
                "accept_date": item.get("acptdt", ""),
                "planned_financing_amount": item.get("maramt"),
                "fetched_at": fetched_at,
            })
        return pd.DataFrame(rows, columns=SCHEMA_COLUMNS)
    except Exception as exc:
        logger.warning("Failed to fetch SZSE aerospace IPO projects: %s", exc)
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
