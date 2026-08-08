"""Exchange eligibility evidence for the airline short-side universe.

This layer is deliberately narrower than borrow feasibility.  HKEX's
designated-security list and SSE's public margin-detail feed can show that a
security is eligible or observed in the relevant exchange mechanism.  They do
not show locatable shares, broker borrow cost, recall risk or execution
availability, so ``borrow_data_available`` remains false for every row.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, NORMALIZED_DIR


OUTPUT_PATH = NORMALIZED_DIR / "airline_short_eligibility.csv"
HKEX_INDEX_URL = (
    "https://www.hkex.com.hk/Services/Trading/Securities/Securities-Lists/"
    "Designated-Securities-Eligible-for-Short-Selling?sc_lang=en"
)
HKEX_DETAIL_URL_TEMPLATE = "https://www.hkex.com.hk/eng/market/sec_tradinfo/ds{date}.htm"
SSE_SOURCE_URL = "https://www.sse.com.cn/market/othersdata/margin/detail/"

HK_UNIVERSE: dict[str, dict[str, str]] = {
    "293": {"ticker": "0293.HK", "company": "Cathay Pacific"},
    "753": {"ticker": "0753.HK", "company": "Air China"},
    "1055": {"ticker": "01055.HK", "company": "China Southern Airlines"},
    "670": {"ticker": "0670.HK", "company": "China Eastern Airlines"},
}

A_UNIVERSE: dict[str, dict[str, str]] = {
    "601111": {"ticker": "601111.SH", "company": "Air China"},
    "600029": {"ticker": "600029.SH", "company": "China Southern Airlines"},
    "600115": {"ticker": "600115.SH", "company": "China Eastern Airlines"},
    "601021": {"ticker": "601021.SH", "company": "Spring Airlines"},
    "600221": {"ticker": "600221.SH", "company": "Hainan Airlines Holdings"},
    "603885": {"ticker": "603885.SH", "company": "Juneyao Airlines"},
}

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "security_code", "snapshot_date",
    "eligibility_effective_date", "eligibility_status", "eligibility_scope",
    "evidence_type", "borrow_data_available", "source_quality", "source_url",
    "source_note", "retrieved_at",
]


def _date_text(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _candidate_dates(end_date: str, lookback: int = 10) -> list[str]:
    end = pd.Timestamp(end_date).date()
    return [(end - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(lookback)]


def candidate_hkex_detail_urls(index_html: str, *, cutoff_date: str) -> list[tuple[str, str]]:
    """Return dated HKEX list pages at or before the requested cutoff."""
    cutoff = pd.Timestamp(cutoff_date).date()
    matches: dict[str, str] = {}
    for href, date_text in re.findall(
        r"href=[\"']([^\"']*?/ds(\d{8})\.htm)[\"']", index_html, flags=re.IGNORECASE
    ):
        effective = pd.to_datetime(date_text, format="%Y%m%d", errors="coerce")
        if pd.isna(effective) or effective.date() > cutoff:
            continue
        matches[effective.strftime("%Y-%m-%d")] = urljoin(HKEX_INDEX_URL, href)
    return sorted(matches.items(), reverse=True)


def parse_hkex_eligibility(
    html: str,
    *,
    effective_date: str,
    snapshot_date: str,
    source_url: str,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse target HK airline codes from an HKEX designated-security page."""
    retrieved = retrieved_at or _retrieved_at()
    eligible: dict[str, str] = {}
    soup = BeautifulSoup(html, "html.parser")
    for row in soup.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"])]
        if len(cells) < 3:
            continue
        code = re.sub(r"\D", "", cells[1])
        if code in HK_UNIVERSE:
            eligible[code] = cells[2]
    rows: list[dict[str, Any]] = []
    for code, metadata in HK_UNIVERSE.items():
        is_eligible = code in eligible
        rows.append({
            "dataset_id": "airline_short_eligibility",
            "company": metadata["company"],
            "ticker": metadata["ticker"],
            "market": "HK",
            "security_code": code,
            "snapshot_date": snapshot_date,
            "eligibility_effective_date": effective_date,
            "eligibility_status": "designated_security_eligible" if is_eligible else "not_in_latest_designated_list",
            "eligibility_scope": "HKEX designated securities eligible for short selling",
            "evidence_type": "hkex_designated_short_selling_list",
            "borrow_data_available": False,
            "source_quality": "hkex_official_designated_short_list",
            "source_url": source_url,
            "source_note": (
                "HKEX designated-security evidence only. It does not establish locatable shares, borrow fee, "
                "recall risk, broker availability or execution guarantee."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def normalize_sse_eligibility(
    frame: pd.DataFrame,
    *,
    observation_date: str,
    snapshot_date: str,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Normalize target A-share presence in the SSE margin-detail feed."""
    retrieved = retrieved_at or _retrieved_at()
    code_column = "标的证券代码"
    rows: list[dict[str, Any]] = []
    for code, metadata in A_UNIVERSE.items():
        present = False
        if frame is not None and not frame.empty and code_column in frame.columns:
            present = frame[code_column].astype(str).str.extract(r"(\d{1,6})", expand=False).str.zfill(6).eq(code).any()
        rows.append({
            "dataset_id": "airline_short_eligibility",
            "company": metadata["company"],
            "ticker": metadata["ticker"],
            "market": "CN_A",
            "security_code": code,
            "snapshot_date": snapshot_date,
            "eligibility_effective_date": observation_date,
            "eligibility_status": "margin_security_observed" if present else "not_observed_in_margin_detail",
            "eligibility_scope": "SSE public margin-detail security presence",
            "evidence_type": "sse_margin_detail_security_presence",
            "borrow_data_available": False,
            "source_quality": "sse_public_margin_detail_via_akshare" if present else "sse_margin_detail_query",
            "source_url": SSE_SOURCE_URL,
            "source_note": (
                "SSE margin-detail presence is public eligibility/observation evidence only. It does not establish "
                "locatable shares, borrow fee, recall risk, broker availability or execution guarantee."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_short_eligibility(*, observation_date: str | None = None) -> pd.DataFrame:
    """Fetch latest official/public eligibility evidence at a PIT cutoff."""
    requested = _date_text(observation_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if requested is None:
        raise ValueError("observation_date must be parseable")
    retrieved = _retrieved_at()
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    hk = pd.DataFrame(columns=OUTPUT_COLUMNS)
    try:
        index_response = session.get(HKEX_INDEX_URL, timeout=max(DEFAULT_TIMEOUT, 30))
        candidates = candidate_hkex_detail_urls(index_response.text, cutoff_date=requested)
        for effective_date, url in candidates:
            response = session.get(url, timeout=max(DEFAULT_TIMEOUT, 30))
            if response.status_code != 200:
                continue
            parsed = parse_hkex_eligibility(
                response.text,
                effective_date=effective_date,
                snapshot_date=requested,
                source_url=url,
                retrieved_at=retrieved,
            )
            if not parsed.empty:
                hk = parsed
                break
    except Exception:
        hk = pd.DataFrame(columns=OUTPUT_COLUMNS)

    sse = pd.DataFrame(columns=OUTPUT_COLUMNS)
    try:
        import akshare as ak
    except ImportError:  # pragma: no cover
        ak = None
    if ak is not None:
        for date in _candidate_dates(requested):
            try:
                raw = ak.stock_margin_detail_sse(pd.Timestamp(date).strftime("%Y%m%d"))
            except Exception:
                continue
            sse = normalize_sse_eligibility(
                raw,
                observation_date=date,
                snapshot_date=requested,
                retrieved_at=retrieved,
            )
            if not sse.empty:
                break

    frames = [frame for frame in (hk, sse) if not frame.empty]
    result = (
        pd.concat(frames, ignore_index=True)
        if frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
    )
    for column in OUTPUT_COLUMNS:
        if column not in result:
            result[column] = None
    result = result[OUTPUT_COLUMNS].sort_values(["market", "company"]).reset_index(drop=True)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
