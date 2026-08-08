"""Free HKEX Stock Connect short-selling evidence for A-share airlines.

HKEX publishes one dated JavaScript data file for each Northbound trading day.
The file contains the displayed remaining balance available for short selling,
short-selling turnover and short-selling percentages for eligible SSE/SZSE
securities.  This is useful implementation context, but it is not locatable
borrow, a borrow fee, recall risk or a broker-specific execution guarantee.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, NORMALIZED_DIR


OUTPUT_PATH = NORMALIZED_DIR / "airline_stock_connect_short_selling.csv"
HKEX_PAGE_URL = (
    "https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Statistics/"
    "Short-Selling?sc_lang=en"
)
HKEX_DATA_URL_TEMPLATE = (
    "https://www.hkex.com.hk/eng/csm/shortsell/"
    "data_tab_short_selling_{date}e.js"
)

A_UNIVERSE: dict[str, dict[str, str]] = {
    "601111": {"ticker": "601111.SH", "company": "Air China", "board": "SSE"},
    "600029": {"ticker": "600029.SH", "company": "China Southern Airlines", "board": "SSE"},
    "600115": {"ticker": "600115.SH", "company": "China Eastern Airlines", "board": "SSE"},
    "601021": {"ticker": "601021.SH", "company": "Spring Airlines", "board": "SSE"},
    "600221": {"ticker": "600221.SH", "company": "Hainan Airlines Holdings", "board": "SSE"},
    "603885": {"ticker": "603885.SH", "company": "Juneyao Airlines", "board": "SSE"},
}

OUTPUT_COLUMNS = [
    "dataset_id", "company", "ticker", "market", "security_code", "exchange_board",
    "observation_date", "suspension_status", "remaining_available_display",
    "remaining_available_shares", "short_selling_turnover_shares",
    "short_selling_turnover_value_rmb", "short_selling_pct_today",
    "short_selling_pct_10d", "borrow_data_available", "source_quality", "source_url",
    "source_note", "retrieved_at",
]

_ROW_RE = re.compile(
    r'\[\s*"(?P<suspension>[^"]*)"\s*,\s*"(?P<code>\d+)"\s*,\s*'
    r'"(?P<name>[^"]*)"\s*,\s*"(?P<remaining>[^"]*)"\s*,\s*'
    r'"(?P<shares>[^"]*)"\s*,\s*"(?P<value>[^"]*)"\s*,\s*'
    r'"(?P<pct_today>[^"]*)"\s*,\s*"(?P<pct_10d>[^"]*)"\s*\]'
)


def _retrieved_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _number(value: Any) -> float | None:
    parsed = pd.to_numeric(str(value).replace(",", ""), errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _percentage(value: Any) -> float | None:
    text = str(value).strip().replace("%", "")
    return _number(text)


def _date_text(value: Any) -> str | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else parsed.strftime("%Y-%m-%d")


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=OUTPUT_COLUMNS)


def parse_hkex_stock_connect_short_selling(
    javascript: str,
    *,
    observation_date: str,
    source_url: str,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Parse target SSE airline rows from one HKEX dated data file."""
    date_text = _date_text(observation_date)
    if date_text is None:
        raise ValueError("observation_date must be parseable")
    retrieved = retrieved_at or _retrieved_at()
    rows: list[dict[str, Any]] = []
    for match in _ROW_RE.finditer(javascript):
        item = match.groupdict()
        code = item["code"].zfill(6)
        metadata = A_UNIVERSE.get(code)
        if metadata is None:
            continue
        remaining = item["remaining"].strip()
        rows.append({
            "dataset_id": "airline_stock_connect_short_selling",
            "company": metadata["company"],
            "ticker": metadata["ticker"],
            "market": "CN_A",
            "security_code": code,
            "exchange_board": metadata["board"],
            "observation_date": date_text,
            "suspension_status": item["suspension"].strip() or None,
            "remaining_available_display": remaining or None,
            "remaining_available_shares": _number(remaining),
            "short_selling_turnover_shares": _number(item["shares"]),
            "short_selling_turnover_value_rmb": _number(item["value"]),
            "short_selling_pct_today": _percentage(item["pct_today"]),
            "short_selling_pct_10d": _percentage(item["pct_10d"]),
            "borrow_data_available": False,
            "source_quality": "hkex_official_stock_connect_short_selling",
            "source_url": source_url,
            "source_note": (
                "HKEX Northbound Stock Connect short-selling display. The remaining field may be the literal "
                "'Available' rather than a numeric quantity; it is exchange dissemination evidence only and "
                "does not establish locatable borrow, borrow fee, recall risk or broker execution availability."
            ),
            "retrieved_at": retrieved,
        })
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def _candidate_dates(start_date: str, cutoff_date: str) -> list[str]:
    start = pd.Timestamp(start_date)
    cutoff = pd.Timestamp(cutoff_date)
    if pd.isna(start) or pd.isna(cutoff) or start > cutoff:
        raise ValueError("start_date must be parseable and no later than cutoff_date")
    return [item.strftime("%Y-%m-%d") for item in pd.date_range(start, cutoff, freq="D")]


def fetch_airline_stock_connect_short_selling(
    *,
    snapshot_date: str | None = None,
    start_date: str = "2026-01-01",
    session: requests.Session | None = None,
) -> pd.DataFrame:
    """Fetch dated HKEX Stock Connect short-selling history to a PIT cutoff."""
    cutoff = _date_text(snapshot_date or datetime.now(timezone.utc).date().isoformat())
    if cutoff is None:
        raise ValueError("snapshot_date must be parseable")
    retrieved = _retrieved_at()
    http = session or requests.Session()
    if session is None:
        http.headers.update(DEFAULT_HEADERS)
    frames: list[pd.DataFrame] = []
    for date_text in _candidate_dates(start_date, cutoff):
        url = HKEX_DATA_URL_TEMPLATE.format(date=pd.Timestamp(date_text).strftime("%Y%m%d"))
        try:
            response = http.get(url, headers=DEFAULT_HEADERS, timeout=max(DEFAULT_TIMEOUT, 30))
        except requests.RequestException:
            continue
        if response.status_code != 200 or "tabData" not in response.text:
            continue
        parsed = parse_hkex_stock_connect_short_selling(
            response.text,
            observation_date=date_text,
            source_url=url,
            retrieved_at=retrieved,
        )
        if not parsed.empty:
            frames.append(parsed)
    result = (
        pd.DataFrame(
            [record for frame in frames for record in frame.to_dict("records")],
            columns=OUTPUT_COLUMNS,
        )
        if frames else _empty()
    )
    if not result.empty:
        result = (
            result.drop_duplicates(subset=["ticker", "observation_date"], keep="last")
            .sort_values(["ticker", "observation_date"])
            .reset_index(drop=True)
        )
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH
