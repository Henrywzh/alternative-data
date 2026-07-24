"""Fundamentals extractor for Regal REIT (1881.HK).

`regalreit.com`'s `/investor-relations/report` page is a Webflow shell
that renders almost no content via a plain `curl` -- the actual list of
Interim/Annual Report PDFs is loaded through an **embedded iframe**
pointing at the REIT's legacy static site
(`https://www.regalreit.com/annualrpt.html?if=yes`), not visible from
the top-level page's raw HTML. See .claude/skills/data-source-deep-dive/
references/reit-regalreit-01881-findings.md for the verification trail
-- a naive curl of the visible URL is a trap that looks like "no data"
but is actually just "wrong page".

The newest report is discovered dynamically each run:
  1. Fetch the iframe page directly and parse every `<a href>` matching
     the `E_1881_<YYYY> (Interim|Annual) Report...pdf` filename pattern
     -- never hardcode a specific year/filename, since new reports are
     added every ~6 months and filenames are not fully predictable
     (some have a date suffix, some don't).
  2. HEAD-request each of the most recent few candidates and compare
     `Last-Modified` response headers to determine which was actually
     published most recently -- report *year* in the filename alone is
     not a reliable ordering (e.g. "Annual Report 2025" was published
     ~April 2026, after "Interim Report 2025" published ~Sept 2025).
  3. Fetch and text-extract that single PDF with pdfplumber, and regex
     the NAV/Unit, DPU, and hotel KPI (occupancy/ADR/RevPAR) figures out
     of the narrative/table text -- both the Interim and Annual report
     layouts are handled since either could be "latest" depending on
     when the pipeline runs.

Strictly dynamic: returns an empty DataFrame (with the expected schema)
if the iframe page, PDF discovery, or PDF fetch/parse fails at any step
-- no hardcoded/fallback figures.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from io import BytesIO
from typing import Optional
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

REGAL_REIT_REPORTS_IFRAME_URL = "https://www.regalreit.com/annualrpt.html?if=yes"

_COLUMNS = [
    "date", "period", "ticker", "reit_name", "nav_per_unit_hkd", "dpu_hkd",
    "hotel_occupancy_pct", "average_daily_rate_hkd", "revpar_hkd", "source_agency",
]

_REPORT_HREF_RE = re.compile(
    r'href="([^"]*E_1881_(\d{4})[^"]*(Interim|Annual) Report[^"]*\.pdf)"', re.IGNORECASE
)


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLUMNS)


def _discover_report_candidates(headers: dict) -> list[tuple[int, str, str]]:
    """Return [(year, kind, absolute_url), ...] parsed from the reports iframe page."""
    resp = requests.get(REGAL_REIT_REPORTS_IFRAME_URL, headers=headers, timeout=20)
    if resp.status_code != 200:
        logger.warning("Regal REIT reports iframe page returned HTTP %s", resp.status_code)
        return []
    candidates = []
    for href, year, kind in _REPORT_HREF_RE.findall(resp.text):
        url = urljoin(REGAL_REIT_REPORTS_IFRAME_URL, href)
        candidates.append((int(year), kind, url))
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates


def _pick_latest_by_last_modified(candidates: list[tuple[int, str, str]], headers: dict, top_n: int = 4) -> Optional[tuple[int, str, str]]:
    """Among the top_n most recent-year candidates, pick the one with the newest Last-Modified."""
    best = None
    best_dt = None
    for year, kind, url in candidates[:top_n]:
        try:
            head = requests.head(url, headers=headers, timeout=15, allow_redirects=True)
            last_mod = head.headers.get("Last-Modified")
            if not last_mod:
                continue
            dt = parsedate_to_datetime(last_mod)
        except Exception:
            continue
        if best_dt is None or dt > best_dt:
            best_dt = dt
            best = (year, kind, url)
    return best or (candidates[0] if candidates else None)


def _parse_hkd(value: str) -> Optional[float]:
    cleaned = value.replace("HK$", "").replace(",", "").strip()
    if not cleaned or cleaned in {"-", "—", "N/A"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_nav_per_unit(text: str) -> Optional[float]:
    # Interim-report narrative style.
    m = re.search(
        r'net asset value \(.NAV.\) per Unit attributable to Unitholders of HK\$([\d.]+)',
        text, re.IGNORECASE,
    )
    if m:
        return float(m.group(1))
    # Annual-report balance-sheet table row style.
    m = re.search(
        r'Net asset value per Unit attributable to Unitholders\s+\d*\s*HK\$([\d.]+)\s+HK\$([\d.]+)',
        text,
    )
    if m:
        return float(m.group(1))
    return None


def _extract_dpu(text: str) -> Optional[float]:
    # Annual-report "Distributions per Unit:" block: Interim / Final / Total lines.
    m = re.search(
        r'Distributions per Unit:\s*\n\s*Interim[^\n]*?([—\-]|[\d.]+)\s+[—\-\d.]+\s*\n'
        r'\s*Final[^\n]*?([—\-]|[\d.]+)\s+[—\-\d.]+\s*\n\s*([—\-]|[\d.]+)\s+[—\-\d.]+',
        text,
    )
    if m:
        total = m.group(3)
        if total not in {"—", "-"}:
            try:
                return float(total)
            except ValueError:
                pass
    # Interim-report "Distribution per Unit (a) — —" row style.
    m = re.search(r'Distribution per Unit \([a-z]\)\s*([—\-]|[\d.]+)\s+([—\-]|[\d.]+)', text)
    if m:
        current = m.group(1)
        if current not in {"—", "-"}:
            try:
                return float(current)
            except ValueError:
                pass
        return None  # Genuinely nil distribution, not a parse failure.
    return None


def _extract_hotel_kpis(text: str) -> dict:
    """Extract the combined ('Initial Hotels') portfolio-level occupancy/ADR/RevPAR."""
    result: dict = {}
    m = re.search(r'Occupancy rate\s+([\d.]+)%\s+([\d.]+)%', text)
    if m:
        result["hotel_occupancy_pct"] = float(m.group(1))
    m = re.search(r'Average room rate\s+HK\$([\d,.]+)\s+HK\$([\d,.]+)', text)
    if m:
        result["average_daily_rate_hkd"] = _parse_hkd(m.group(1))
    m = re.search(r'RevPAR\s+HK\$([\d,.]+)\s+HK\$([\d,.]+)', text)
    if m:
        result["revpar_hkd"] = _parse_hkd(m.group(1))
    return result


def fetch_regalreit_fundamentals() -> pd.DataFrame:
    """Fetch NAV/unit, DPU, and hotel KPIs (occupancy/ADR/RevPAR) for Regal REIT (1881.HK)."""
    headers = {**DEFAULT_HEADERS, "Referer": "https://www.regalreit.com/investor-relations/"}

    try:
        candidates = _discover_report_candidates(headers)
        if not candidates:
            logger.warning("Regal REIT: no report PDF links discovered on reports iframe page")
            return _empty_df()

        chosen = _pick_latest_by_last_modified(candidates, headers)
        if chosen is None:
            return _empty_df()
        year, kind, pdf_url = chosen

        pdf_resp = requests.get(pdf_url, headers=headers, timeout=45)
        if pdf_resp.status_code != 200:
            logger.warning("Regal REIT report PDF returned HTTP %s (%s)", pdf_resp.status_code, pdf_url)
            return _empty_df()

        save_raw_snapshot("regalreit_fundamentals", pdf_resp.content, file_ext="pdf", source_url=pdf_url)

        with pdfplumber.open(BytesIO(pdf_resp.content)) as pdf:
            # NAV/DPU/hotel-KPI narrative typically appears within the first ~80 pages
            # (MD&A + financial statements); avoid extracting all 200+ pages of a full
            # annual report for performance.
            text = "\n".join((p.extract_text() or "") for p in pdf.pages[:100])

        nav = _extract_nav_per_unit(text)
        dpu = _extract_dpu(text)
        kpis = _extract_hotel_kpis(text)

        if nav is None and dpu is None and not kpis:
            logger.warning("Regal REIT report PDF (%s): no expected fields found via regex", pdf_url)
            return _empty_df()

        period_label = f"{kind} {year}"
        date_val = f"{year}-06-30" if kind == "Interim" else f"{year}-12-31"

        record = {
            "date": date_val,
            "period": period_label,
            "ticker": "1881.HK",
            "reit_name": "Regal REIT",
            "nav_per_unit_hkd": nav,
            "dpu_hkd": dpu,
            "hotel_occupancy_pct": kpis.get("hotel_occupancy_pct"),
            "average_daily_rate_hkd": kpis.get("average_daily_rate_hkd"),
            "revpar_hkd": kpis.get("revpar_hkd"),
            "source_agency": "Regal REIT Investor Relations",
        }
        df = pd.DataFrame([record])
        df.attrs.update(raw_snapshot=pdf_url, source_url=pdf_url)
        return df
    except Exception as exc:
        logger.warning("Regal REIT report discovery/fetch/parse failed: %s", exc)
        return _empty_df()
