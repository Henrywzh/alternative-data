"""Free SFC aggregate reportable short-position evidence for HK airlines.

The SFC publishes weekly aggregate reportable short positions for specified
shares.  This is closer to outstanding short-position crowding than daily
short turnover, but it is still not locatable borrow, borrow fee, recall risk
or broker execution availability.
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
import warnings

import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, NORMALIZED_DIR


OUTPUT_PATH = NORMALIZED_DIR / "airline_hk_short_positions.csv"
SFC_INDEX_URL = (
    "https://hksfc.org/en/Regulatory-functions/Market/Short-position-reporting/"
    "Aggregated-reportable-short-positions-of-specified-shares"
)

HK_UNIVERSE: dict[str, dict[str, str]] = {
    "293": {"ticker": "0293.HK", "company": "Cathay Pacific"},
    "753": {"ticker": "0753.HK", "company": "Air China"},
    "1055": {"ticker": "01055.HK", "company": "China Southern Airlines"},
    "670": {"ticker": "0670.HK", "company": "China Eastern Airlines"},
}

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "security_code", "reporting_date",
    "snapshot_date", "short_position_shares", "short_position_value_hkd",
    "source_quality", "source_url", "source_note", "borrow_data_available", "retrieved_at",
]

_CSV_RE = re.compile(r"Short_Position_Reporting_Aggregated_Data_(\d{8})\.csv", re.IGNORECASE)


def _date_text(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(session: requests.Session, url: str) -> requests.Response:
    try:
        return session.get(url, headers=DEFAULT_HEADERS, timeout=max(DEFAULT_TIMEOUT, 30))
    except requests.exceptions.SSLError:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", InsecureRequestWarning)
            return session.get(
                url,
                headers=DEFAULT_HEADERS,
                timeout=max(DEFAULT_TIMEOUT, 30),
                verify=False,
            )


def parse_sfc_csv_links(index_html: str, *, cutoff_date: str, start_date: str) -> list[tuple[str, str]]:
    """Extract dated SFC CSV links within the requested PIT window."""
    cutoff = pd.Timestamp(cutoff_date).date()
    start = pd.Timestamp(start_date).date()
    found: dict[str, str] = {}
    soup = BeautifulSoup(index_html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        href = str(anchor["href"])
        match = _CSV_RE.search(href)
        if not match:
            continue
        report_date = pd.to_datetime(match.group(1), format="%Y%m%d", errors="coerce")
        if pd.isna(report_date) or not (start <= report_date.date() <= cutoff):
            continue
        found[report_date.strftime("%Y-%m-%d")] = urljoin(SFC_INDEX_URL, href)
    return sorted(found.items())


def parse_sfc_csv(
    content: bytes,
    *,
    source_url: str,
    snapshot_date: str,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse one official SFC aggregate short-position CSV."""
    retrieved = retrieved_at or _retrieved_at()
    frame = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
    required = {
        "Date", "Stock Code", "Aggregated Reportable Short Positions (Shares)",
        "Aggregated Reportable Short Positions (HK$)",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"SFC short-position CSV missing columns: {sorted(missing)}")
    codes = frame["Stock Code"].astype(str).str.extract(r"(\d{1,4})", expand=False).str.zfill(4)
    frame = frame.loc[codes.isin({code.zfill(4) for code in HK_UNIVERSE})].copy()
    if frame.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)
    frame["security_code"] = codes.loc[frame.index].str.lstrip("0").replace("", "0")
    frame["reporting_date"] = pd.to_datetime(frame["Date"], dayfirst=True, errors="coerce").dt.strftime("%Y-%m-%d")
    rows: list[dict[str, Any]] = []
    for _, item in frame.iterrows():
        code = str(item["security_code"])
        if code not in HK_UNIVERSE:
            continue
        metadata = HK_UNIVERSE[code]
        rows.append({
            "dataset_id": "airline_hk_short_positions",
            "company": metadata["company"],
            "ticker": metadata["ticker"],
            "market": "HK",
            "security_code": code,
            "reporting_date": item["reporting_date"],
            "snapshot_date": snapshot_date,
            "short_position_shares": pd.to_numeric(
                item["Aggregated Reportable Short Positions (Shares)"], errors="coerce"
            ),
            "short_position_value_hkd": pd.to_numeric(
                item["Aggregated Reportable Short Positions (HK$)"], errors="coerce"
            ),
            "source_quality": "sfc_official_aggregate_reportable_short_position",
            "source_url": source_url,
            "source_note": (
                "SFC aggregate reportable short positions for specified shares. This is a public short-position "
                "crowding proxy, not locatable borrow, borrow fee, recall risk or broker execution availability; "
                "the SFC threshold/reporting scope does not equal total short interest."
            ),
            "borrow_data_available": False,
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def fetch_airline_hk_short_positions(
    *,
    snapshot_date: str | None = None,
    start_date: str = "2026-01-01",
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch SFC weekly short-position history up to a PIT cutoff."""
    as_of = _date_text(snapshot_date or datetime.now(timezone.utc).date().isoformat())
    if as_of is None:
        raise ValueError("snapshot_date must be parseable")
    retrieved = _retrieved_at()
    http = session or requests.Session()
    index = _get(http, SFC_INDEX_URL)
    index.raise_for_status()
    links = parse_sfc_csv_links(index.text, cutoff_date=as_of, start_date=start_date)
    frames: list[pd.DataFrame] = []
    for _, url in links:
        try:
            response = _get(http, url)
            response.raise_for_status()
            parsed = parse_sfc_csv(
                response.content,
                source_url=url,
                snapshot_date=as_of,
                retrieved_at=retrieved,
            )
            if not parsed.empty:
                frames.append(parsed)
        except (requests.RequestException, ValueError, UnicodeError):
            continue
    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=OUTPUT_COLUMNS)
    if not result.empty:
        result = result.drop_duplicates(
            subset=["ticker", "reporting_date"], keep="last"
        ).sort_values(["ticker", "reporting_date"]).reset_index(drop=True)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
