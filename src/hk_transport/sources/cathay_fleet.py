"""Cathay Group fleet profile history from official annual/interim reports.

Cathay's monthly traffic announcements do not publish a fleet-total field.
The official annual and interim reports do, in a Fleet Profile table, by
reporting scope (the Company, HK Express, Air Hong Kong and Group grand total).
This module keeps that different cadence honest: each row is dated at the
reporting period end and is never expanded into monthly observations.
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd
import pdfplumber
import requests

from ..config import DEFAULT_HEADERS, RAW_DIR
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

CATHAY_REPORT_BASE_URL = (
    "https://www.cathaypacific.com/content/dam/cx/about-us/"
    "investor-relations/interim-annual-reports/en/"
)

# The Cathay archive exposes recent reports under a stable URL convention.
# Older annual reports are not consistently available at this path, so the
# available 2015-18 interim reports are included as the earliest verified
# public fleet observations. Missing/404 reports are skipped transparently.
FLEET_REPORTS = [
    (2015, "interim", "2015-06-30"),
    (2016, "interim", "2016-06-30"),
    (2017, "interim", "2017-06-30"),
    (2018, "interim", "2018-06-30"),
    (2020, "interim", "2020-06-30"),
    (2020, "annual", "2020-12-31"),
    (2021, "interim", "2021-06-30"),
    (2021, "annual", "2021-12-31"),
    (2022, "interim", "2022-06-30"),
    (2022, "annual", "2022-12-31"),
    (2023, "interim", "2023-06-30"),
    (2023, "annual", "2023-12-31"),
    (2024, "interim", "2024-06-30"),
    (2024, "annual", "2024-12-31"),
    (2025, "interim", "2025-06-30"),
    (2025, "annual", "2025-12-31"),
]

REPORT_CACHE_DIR = RAW_DIR / "cathay_report_cache"
REPORT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

FLEET_COLUMNS = [
    "date",
    "report_date",
    "report_type",
    "scope",
    "fleet_total_aircraft",
    "source_pdf_url",
]

_TOKEN_RE = re.compile(r"(?:\d[\d,]*(?:\.\d+)?(?:\([a-z]\))?|[–—-])")


def _report_url(year: int, report_type: str) -> str:
    filename = f"{year}_cx_{'annual_report' if report_type == 'annual' else 'interim_report'}_en.pdf"
    return f"{CATHAY_REPORT_BASE_URL}{filename}"


def _get_report_bytes(session: requests.Session, url: str) -> bytes | None:
    cache_name = re.sub(r"[^A-Za-z0-9._-]", "_", url.rsplit("/", 1)[-1])
    cache_path = REPORT_CACHE_DIR / cache_name
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path.read_bytes()
    try:
        response = session.get(url, headers=DEFAULT_HEADERS, timeout=45)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.info("Cathay fleet report unavailable at %s: %s", url, exc)
        return None
    if not response.content.startswith(b"%PDF"):
        logger.warning("Cathay fleet report at %s was not a PDF", url)
        return None
    cache_path.write_bytes(response.content)
    return response.content


def _row_total(line: str, *, total_index: int | None = None) -> float | None:
    """Return the fourth fleet-total column from one Fleet Profile row.

    Rows use four columns (owned, leased-with-transfer, leased-without-
    transfer, total). A dash is a published zero and must not shift the
    total column left, hence dashes are tokenised explicitly.
    """
    tokens = _TOKEN_RE.findall(line)
    if not tokens:
        return None
    # The first decimal token is the published average-age column. The fleet
    # total is immediately before it in both the older three-column layout
    # (Owned / Leased / Total) and the newer four-column layout (Owned /
    # Leased-with-transfer / Leased-without-transfer / Total).
    if total_index is not None and len(tokens) > total_index:
        token = tokens[total_index]
    else:
        decimal_index = next((index for index, token in enumerate(tokens) if "." in token), None)
        if decimal_index is not None and decimal_index > 0:
            token = tokens[decimal_index - 1]
        elif len(tokens) >= 4:
            token = tokens[3]
        else:
            token = tokens[-1]
    if token in {"-", "–", "—"}:
        return 0.0
    try:
        return float(re.sub(r"[^\d.]", "", token))
    except ValueError:
        return None


def _find_row_total(
    lines: list[str],
    anchor: str,
    *,
    max_lookahead: int = 80,
    total_index: int | None = None,
) -> float | None:
    anchor_lower = anchor.lower()
    for index, line in enumerate(lines):
        normalized_anchor_line = " ".join(line.split()).lower()
        if anchor_lower == "company":
            is_header = (
                normalized_anchor_line.startswith("company ")
                or normalized_anchor_line == "total of the"
                or normalized_anchor_line.startswith("the company")
            )
        else:
            is_header = normalized_anchor_line.startswith(anchor_lower) and ":" in normalized_anchor_line
        if not is_header:
            continue
        for candidate in lines[index : min(len(lines), index + max_lookahead)]:
            normalized = " ".join(candidate.split())
            lower = normalized.lower()
            if anchor_lower == "company" and lower.startswith("company "):
                total = _row_total(normalized, total_index=total_index)
                if total is not None:
                    return total
            if lower.startswith("total"):
                total = _row_total(normalized, total_index=total_index)
                if total is not None:
                    return total
        return None
    return None


def _find_grand_total(lines: list[str]) -> float | None:
    for line in lines:
        normalized = " ".join(line.split())
        if normalized.lower().startswith("grand total"):
            return _row_total(normalized)
    return None


def _parse_fleet_profile(content: bytes, report_date: str, report_type: str, source_url: str) -> pd.DataFrame:
    """Parse one official Fleet Profile page into four scope rows."""
    fleet_text = None
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if "FLEET PROFILE" in text.upper():
                fleet_text = text
                break
    if not fleet_text:
        logger.warning("Cathay %s report has no Fleet Profile page: %s", report_type, source_url)
        return pd.DataFrame(columns=FLEET_COLUMNS)

    lines = fleet_text.splitlines()
    company = _find_row_total(lines, "company")
    if company is None:
        # Pre-2021 reports label the first scope "Cathay Pacific and Cathay
        # Dragon" rather than using a separate "Company" row label.
        company = _find_row_total(lines, "cathay pacific and cathay dragon")
    if company is None:
        company = _find_row_total(lines, "aircraft operated by cathay pacific")
    if company is None:
        company = _find_row_total(lines, "cathay pacific")
    hk_express = _find_row_total(lines, "hk express")
    if hk_express is None:
        # Before the 2020 corporate naming/layout change, the same passenger
        # fleet was disclosed under Cathay Dragon/Dragonair.
        hk_express = _find_row_total(lines, "aircraft operated by dragonair", total_index=2)
    if hk_express is None:
        hk_express = _find_row_total(lines, "aircraft operated by cathay dragon", total_index=2)
    air_hong_kong = _find_row_total(lines, "air hong kong")
    if air_hong_kong is None:
        air_hong_kong = _find_row_total(lines, "aircraft operated by air hong kong")
    grand_total = _find_grand_total(lines)
    values = {
        "Company": company,
        "HK Express": hk_express,
        "Air Hong Kong": air_hong_kong,
        "Grand total": grand_total,
    }
    if grand_total is None:
        logger.warning("Cathay %s Fleet Profile has no grand total: %s", report_type, source_url)
        return pd.DataFrame(columns=FLEET_COLUMNS)

    rows = []
    for scope, total in values.items():
        if total is None:
            continue
        rows.append(
            {
                "date": pd.Timestamp(report_date),
                "report_date": report_date,
                "report_type": report_type,
                "scope": scope,
                "fleet_total_aircraft": total,
                "source_pdf_url": source_url,
            }
        )
    return pd.DataFrame(rows, columns=FLEET_COLUMNS)


def fetch_cathay_fleet_history() -> pd.DataFrame:
    """Fetch available official Cathay Fleet Profile observations."""
    session = requests.Session()
    frames: list[pd.DataFrame] = []
    for year, report_type, report_date in FLEET_REPORTS:
        url = _report_url(year, report_type)
        content = _get_report_bytes(session, url)
        if content is None:
            continue
        parsed = _parse_fleet_profile(content, report_date, report_type, url)
        if not parsed.empty:
            frames.append(parsed)

    if not frames:
        return pd.DataFrame(columns=FLEET_COLUMNS)
    result = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates(subset=["date", "scope"])
        .sort_values(["date", "scope"])
        .reset_index(drop=True)
    )
    raw_path = save_raw_snapshot(
        "cathay_fleet_profile",
        result.to_dict(orient="records"),
        file_ext="json",
        source_url=CATHAY_REPORT_BASE_URL,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = CATHAY_REPORT_BASE_URL
    return result
