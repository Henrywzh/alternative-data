"""Point-in-time verification of mainland airline interim filings on CNINFO.

The 10jqka filing calendar is a useful scheduled-date discovery source, but it
does not by itself prove that an issuer has published the report.  This module
queries CNINFO's public announcement archive for the six Shanghai-listed
airline groups and keeps the official announcement evidence separate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests

from ..config import AIRLINE_TICKER_ALIASES, DEFAULT_HEADERS, DEFAULT_TIMEOUT, NORMALIZED_DIR
from .airline_filing_calendar import FILING_UNIVERSE


OUTPUT_PATH = NORMALIZED_DIR / "airline_official_filing_watch.csv"
CNINFO_STOCK_LIST_URL = "https://www.cninfo.com.cn/new/data/szse_stock.json"
CNINFO_ANNOUNCEMENT_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_HOME_URL = "https://www.cninfo.com.cn/"
CNINFO_REPORT_CATEGORY = "category_bndbg_szsh;"

OUTPUT_COLUMNS = [
    "dataset_id",
    "ticker",
    "company",
    "symbol",
    "statement_period",
    "snapshot_date",
    "scheduled_date",
    "official_report_found",
    "official_disclosure_date",
    "official_disclosure_datetime",
    "announcement_id",
    "announcement_title",
    "report_pdf_url",
    "announcement_type",
    "source_quality",
    "source_url",
    "source_note",
    "retrieved_at",
]


def _retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _date_text(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.strftime("%Y-%m-%d")


def _announcement_datetime(value: Any) -> tuple[str | None, str | None]:
    """Return Shanghai-local date and ISO datetime from CNINFO milliseconds."""
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
    else:
        parsed = pd.to_datetime(numeric, unit="ms", errors="coerce", utc=True)
    if pd.isna(parsed):
        return None, None
    local = parsed.tz_convert("Asia/Shanghai")
    return local.strftime("%Y-%m-%d"), local.isoformat()


def _is_2026_half_year_report(title: Any) -> bool:
    text = str(title or "").strip()
    return "2026年半年度报告" in text


def _is_full_report(title: Any) -> bool:
    return "摘要" not in str(title or "") and "英文版" not in str(title or "")


def _pdf_url(adjunct_url: Any) -> str | None:
    text = str(adjunct_url or "").strip()
    if not text or text in {"nan", "None"}:
        return None
    if text.startswith("http://") or text.startswith("https://"):
        return text.replace("http://static.cninfo.com.cn", "https://static.cninfo.com.cn")
    return f"https://static.cninfo.com.cn/{text.lstrip('/')}"


def _scheduled_dates() -> dict[str, str | None]:
    path = NORMALIZED_DIR / "airline_filing_calendar.csv"
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    if "symbol" not in frame or "first_scheduled_date" not in frame:
        return {}
    return {
        str(row["symbol"]): _date_text(row["first_scheduled_date"])
        for _, row in frame.iterrows()
    }


def _empty_row(
    *,
    symbol: str,
    company: str,
    snapshot_date: str,
    scheduled_date: str | None,
    retrieved_at: str,
) -> dict[str, Any]:
    metadata = FILING_UNIVERSE.get(symbol, {})
    return {
        "dataset_id": "airline_official_filing_watch",
        "ticker": metadata.get("ticker", symbol).replace("00670.HK", "0670.HK"),
        "company": company,
        "symbol": symbol,
        "statement_period": "1H2026",
        "snapshot_date": snapshot_date,
        "scheduled_date": scheduled_date,
        "official_report_found": False,
        "official_disclosure_date": None,
        "official_disclosure_datetime": None,
        "announcement_id": None,
        "announcement_title": None,
        "report_pdf_url": None,
        "announcement_type": None,
        "source_quality": "cninfo_official_query",
        "source_url": CNINFO_ANNOUNCEMENT_QUERY_URL,
        "source_note": (
            "CNINFO half-year-report-category query at the stated snapshot cutoff. "
            "No matching 2026 full interim report was found in the queried public archive; "
            "this is query-scoped absence, not proof of permanent non-disclosure."
        ),
        "retrieved_at": retrieved_at,
    }


def normalize_official_filing_watch(
    announcements_by_symbol: Iterable[tuple[str, str, Iterable[dict[str, Any]]]],
    *,
    snapshot_date: str,
    scheduled_dates: dict[str, str | None] | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Normalize raw CNINFO announcement lists into one row per company."""
    retrieved = retrieved_at or _retrieved_at()
    schedules = scheduled_dates or {}
    rows: list[dict[str, Any]] = []
    for symbol, company, announcements in announcements_by_symbol:
        row = _empty_row(
            symbol=symbol,
            company=company,
            snapshot_date=snapshot_date,
            scheduled_date=schedules.get(symbol),
            retrieved_at=retrieved,
        )
        candidates = [
            item for item in announcements
            if _is_2026_half_year_report(item.get("announcementTitle"))
        ]
        candidates.sort(
            key=lambda item: (
                not _is_full_report(item.get("announcementTitle")),
                str(item.get("announcementTime", "")),
                str(item.get("announcementId", "")),
            )
        )
        if candidates:
            selected = candidates[0]
            disclosure_date, disclosure_datetime = _announcement_datetime(
                selected.get("announcementTime")
            )
            row.update(
                {
                    "official_report_found": True,
                    "official_disclosure_date": disclosure_date,
                    "official_disclosure_datetime": disclosure_datetime,
                    "announcement_id": selected.get("announcementId"),
                    "announcement_title": selected.get("announcementTitle"),
                    "report_pdf_url": _pdf_url(selected.get("adjunctUrl")),
                    "announcement_type": selected.get("announcementType"),
                    "source_note": (
                        "CNINFO half-year-report-category query matched the official 2026 "
                        "interim-report announcement. Full report is preferred over an abstract."
                    ),
                }
            )
        rows.append(row)
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def merge_official_filing_watch_history(
    prior: pd.DataFrame,
    current: pd.DataFrame,
) -> pd.DataFrame:
    """Append PIT snapshots while replacing only an identical company/day key."""
    result = pd.concat([prior, current], ignore_index=True)
    if result.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    result["ticker"] = result["ticker"].replace(AIRLINE_TICKER_ALIASES)
    for column in OUTPUT_COLUMNS:
        if column not in result.columns:
            result[column] = None
    key = ["ticker", "snapshot_date"]
    result = result.drop_duplicates(key, keep="last")
    return result.sort_values(["snapshot_date", "ticker"]).reset_index(drop=True)[OUTPUT_COLUMNS]


def _cninfo_headers() -> dict[str, str]:
    return {
        **DEFAULT_HEADERS,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": CNINFO_HOME_URL,
    }


def _stock_org_ids(session: requests.Session) -> dict[str, str]:
    response = session.get(
        CNINFO_STOCK_LIST_URL,
        headers=_cninfo_headers(),
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    response.raise_for_status()
    payload = response.json()
    return {
        str(row.get("code")): str(row.get("orgId"))
        for row in payload.get("stockList", [])
        if row.get("code") and row.get("orgId")
    }


def _query_announcements(
    session: requests.Session,
    *,
    symbol: str,
    org_id: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    payload = {
        "stock": f"{symbol},{org_id}",
        "searchkey": "",
        "plate": "",
        "category": CNINFO_REPORT_CATEGORY,
        "trade": "",
        "column": "sse",
        "pageNum": 1,
        "pageSize": 30,
        "tabName": "fulltext",
        "sortName": "",
        "sortType": "",
        "limit": "",
        "showTitle": "true",
        "seDate": f"{start_date}~{end_date}",
        "isHLtitle": "true",
    }
    response = session.post(
        CNINFO_ANNOUNCEMENT_QUERY_URL,
        data=payload,
        headers=_cninfo_headers(),
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    response.raise_for_status()
    result = response.json()
    return result.get("announcements") or []


def fetch_airline_official_filing_watch(
    *,
    snapshot_date: str | None = None,
    statement_year: int = 2026,
) -> pd.DataFrame:
    """Fetch and persist the six-name 1H2026 CNINFO official-filing watch."""
    snap = snapshot_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    retrieved = _retrieved_at()
    session = requests.Session()
    org_ids = _stock_org_ids(session)
    frames: list[tuple[str, str, Iterable[dict[str, Any]]]] = []
    for symbol, metadata in FILING_UNIVERSE.items():
        org_id = org_ids.get(symbol)
        announcements: list[dict[str, Any]] = []
        if org_id:
            announcements = _query_announcements(
                session,
                symbol=symbol,
                org_id=org_id,
                start_date=f"{statement_year}-01-01",
                end_date=f"{statement_year}-12-31",
            )
        frames.append((symbol, metadata["company"], announcements))

    current = normalize_official_filing_watch(
        frames,
        snapshot_date=snap,
        scheduled_dates=_scheduled_dates(),
        retrieved_at=retrieved,
    )
    if OUTPUT_PATH.exists():
        current = merge_official_filing_watch_history(
            pd.read_csv(OUTPUT_PATH),
            current,
        )
    current.to_csv(OUTPUT_PATH, index=False)
    return current


def source_path() -> Path:
    return OUTPUT_PATH
