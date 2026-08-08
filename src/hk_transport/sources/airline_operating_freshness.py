"""Point-in-time freshness contract for mainland airline operating releases.

The monthly KPI archive is an observation history.  This companion layer asks a
different question: as of a stated snapshot date, was the expected prior-month
issuer operating bulletin visible in CNINFO?  A no-match is query-scoped and is
never converted into a zero or an invented missing observation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, NORMALIZED_DIR


OUTPUT_PATH = NORMALIZED_DIR / "airline_operating_freshness.csv"
KPI_PATH = Path(__file__).resolve().parents[3] / "data" / "processed" / "airline_traffic" / "china_airlines_monthly.parquet"
REGISTRY_PATH = NORMALIZED_DIR / "airline_operating_release_registry.csv"
CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_HOME_URL = "https://www.cninfo.com.cn/"

OPERATING_UNIVERSE: dict[str, dict[str, Any]] = {
    "601111": {"company": "Air China", "org_id": "9900000441", "searchkeys": ("主要运营数据",)},
    "600029": {"company": "China Southern Airlines", "org_id": "gssh0600029", "searchkeys": ("主要运营数据",)},
    "600115": {"company": "China Eastern Airlines", "org_id": "gssh0600115", "searchkeys": ("运营数据", "经营数据")},
    "601021": {"company": "Spring Airlines", "org_id": "9900023129", "searchkeys": ("主要运营数据",)},
    "600221": {"company": "Hainan Airlines Holdings", "org_id": "gssh0600221", "searchkeys": ("主要运营数据",)},
    "603885": {"company": "Juneyao Airlines", "org_id": "9900023633", "searchkeys": ("主要运营数据",)},
}

OUTPUT_COLUMNS = [
    "dataset_id", "company", "airline_code", "snapshot_date", "target_month",
    "target_window_start", "target_window_end", "target_release_status",
    "target_announcement_date", "target_announcement_datetime", "target_announcement_id",
    "target_announcement_title", "target_source_pdf_url", "latest_observation_month",
    "latest_observation_announcement_date", "latest_observation_announcement_id",
    "latest_kpi_row_count", "latest_kpi_metric_count", "release_lag_days",
    "source_quality", "source_url", "source_note", "retrieved_at",
]


def _retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_title(value: Any) -> str:
    return str(value or "").replace("<em>", "").replace("</em>", "").strip()


def _announcement_datetime(value: Any) -> tuple[str | None, str | None]:
    numeric = pd.to_numeric(value, errors="coerce")
    if pd.isna(numeric):
        parsed = pd.to_datetime(value, errors="coerce", utc=True)
    else:
        parsed = pd.to_datetime(numeric, unit="ms", errors="coerce", utc=True)
    if pd.isna(parsed):
        return None, None
    local = parsed.tz_convert("Asia/Shanghai")
    return local.strftime("%Y-%m-%d"), local.isoformat()


def _headers() -> dict[str, str]:
    return {
        **DEFAULT_HEADERS,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": CNINFO_HOME_URL,
    }


def query_operating_announcements(
    session: requests.Session,
    *,
    symbol: str,
    org_id: str,
    searchkey: str,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    """Query only announcement metadata for one carrier and date window."""
    payload = {
        "stock": f"{symbol},{org_id}",
        "searchkey": searchkey,
        "plate": "sse",
        "category": "",
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
        CNINFO_QUERY_URL,
        data=payload,
        headers=_headers(),
        timeout=max(DEFAULT_TIMEOUT, 30),
    )
    response.raise_for_status()
    return response.json().get("announcements") or []


def _target_month(snapshot_date: str) -> str:
    return str(pd.Period(snapshot_date, freq="M") - 1)


def _target_candidates(announcements: Iterable[dict[str, Any]], target_month: str) -> list[dict[str, Any]]:
    marker = f"{target_month[:4]}年{int(target_month[5:]):d}月"
    candidates = []
    for item in announcements:
        title = _clean_title(item.get("announcementTitle"))
        if marker not in title or not ("运营数据" in title or "经营数据" in title):
            continue
        item = dict(item)
        item["_clean_title"] = title
        candidates.append(item)
    return sorted(
        candidates,
        key=lambda item: (str(item.get("announcementTime", "")), str(item.get("announcementId", ""))),
    )


def _pdf_url(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text or text in {"nan", "None"}:
        return None
    if text.startswith("http://") or text.startswith("https://"):
        return text.replace("http://static.cninfo.com.cn", "https://static.cninfo.com.cn")
    return f"https://static.cninfo.com.cn/{text.lstrip('/')}"


def _latest_kpi(kpi: pd.DataFrame, code: str) -> tuple[str | None, int, int]:
    if kpi.empty or "airline_code" not in kpi or "month" not in kpi:
        return None, 0, 0
    rows = kpi.loc[kpi["airline_code"].astype(str).eq(code)].copy()
    if rows.empty:
        return None, 0, 0
    rows["month"] = rows["month"].astype(str)
    latest = rows["month"].max()
    latest_rows = rows.loc[rows["month"].eq(latest)]
    return latest, len(latest_rows), int(latest_rows["metric"].nunique()) if "metric" in latest_rows else 0


def _latest_registry(registry: pd.DataFrame, code: str) -> tuple[str | None, str | None, str | None]:
    if registry.empty or "airline_code" not in registry:
        return None, None, None
    rows = registry.loc[registry["airline_code"].astype(str).eq(code)].copy()
    if rows.empty:
        return None, None, None
    rows["_date"] = pd.to_datetime(rows.get("announcement_date"), errors="coerce")
    row = rows.sort_values(["_date", "month"]).iloc[-1]
    return str(row.get("month")) if pd.notna(row.get("month")) else None, _date_text(row.get("announcement_date")), str(row.get("announcement_id")) if pd.notna(row.get("announcement_id")) else None


def _date_text(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def build_airline_operating_freshness(
    *,
    kpi: pd.DataFrame | None = None,
    registry: pd.DataFrame | None = None,
    announcements_by_company: Iterable[tuple[str, Iterable[dict[str, Any]]]] | None = None,
    snapshot_date: str | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build one freshness row per mainland listed airline."""
    snap = _date_text(snapshot_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if snap is None:
        raise ValueError("snapshot_date must be parseable")
    target = _target_month(snap)
    target_start = f"{target}-01"
    target_end = snap
    kpi = kpi if kpi is not None else (pd.read_parquet(KPI_PATH) if KPI_PATH.exists() else pd.DataFrame())
    registry = registry if registry is not None else (pd.read_csv(REGISTRY_PATH) if REGISTRY_PATH.exists() else pd.DataFrame())
    retrieved = retrieved_at or _retrieved_at()
    supplied = {company: list(items) for company, items in (announcements_by_company or [])}
    rows: list[dict[str, Any]] = []
    for code, metadata in OPERATING_UNIVERSE.items():
        company = metadata["company"]
        latest_month, latest_rows, latest_metrics = _latest_kpi(kpi, code)
        latest_release_month, latest_release_date, latest_release_id = _latest_registry(registry, code)
        candidates = _target_candidates(supplied.get(company, []), target)
        selected = candidates[-1] if candidates else None
        announcement_date, announcement_datetime = _announcement_datetime(selected.get("announcementTime")) if selected else (None, None)
        target_status = "announcement_found" if selected else "not_found_in_cninfo_window"
        lag = None
        if latest_release_date:
            lag = (pd.Timestamp(snap) - pd.Timestamp(latest_release_date)).days
        if selected:
            note = "CNINFO metadata query found the target-month issuer operating bulletin at the stated snapshot cutoff."
        else:
            note = (
                "CNINFO metadata query found no target-month issuer operating bulletin at the stated snapshot cutoff; "
                "this is query-scoped absence, not proof of permanent non-disclosure."
            )
        rows.append({
            "dataset_id": "airline_operating_freshness",
            "company": company,
            "airline_code": code,
            "snapshot_date": snap,
            "target_month": target,
            "target_window_start": target_start,
            "target_window_end": target_end,
            "target_release_status": target_status,
            "target_announcement_date": announcement_date,
            "target_announcement_datetime": announcement_datetime,
            "target_announcement_id": selected.get("announcementId") if selected else None,
            "target_announcement_title": selected.get("_clean_title") if selected else None,
            "target_source_pdf_url": _pdf_url(selected.get("adjunctUrl")) if selected else None,
            "latest_observation_month": latest_month,
            "latest_observation_announcement_date": latest_release_date,
            "latest_observation_announcement_id": latest_release_id,
            "latest_kpi_row_count": latest_rows,
            "latest_kpi_metric_count": latest_metrics,
            "release_lag_days": lag,
            "source_quality": "cninfo_operating_release_query",
            "source_url": CNINFO_QUERY_URL,
            "source_note": note,
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_operating_freshness(
    *,
    snapshot_date: str | None = None,
) -> pd.DataFrame:
    """Query the target month and persist the operating-release freshness layer."""
    snap = _date_text(snapshot_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if snap is None:
        raise ValueError("snapshot_date must be parseable")
    target = _target_month(snap)
    session = requests.Session()
    announcements: list[tuple[str, Iterable[dict[str, Any]]]] = []
    for symbol, metadata in OPERATING_UNIVERSE.items():
        combined: list[dict[str, Any]] = []
        for searchkey in metadata["searchkeys"]:
            combined.extend(query_operating_announcements(
                session,
                symbol=symbol,
                org_id=metadata["org_id"],
                searchkey=searchkey,
                start_date=f"{target}-01",
                end_date=snap,
            ))
        announcements.append((metadata["company"], combined))
    result = build_airline_operating_freshness(
        announcements_by_company=announcements,
        snapshot_date=snap,
    )
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
