"""Fundamentals extractor for Link REIT (0823.HK).

Combines two of Link REIT's own investor-relations sources (both
verified live/`curl`-able, see .claude/skills/data-source-deep-dive/
references/reit-linkreit-00823-findings.md):

  - The "Five Year Performance Summary" PDF, linked from
    `https://www.linkreit.com/en/investor-relations/financial-highlights/`
    -- a real, text-extractable (not scanned) PDF giving NAV/unit,
    occupancy, and reversion rate for the HK portfolio, 5 fiscal years.
    The PDF URL is discovered by reading the `<a href>` on the
    financial-highlights page rather than guessing the filename, since
    the fiscal-year tag in the filename changes every year.
  - The distribution-history HTML table at
    `https://www.linkreit.com/en/investor-relations/distribution/`,
    a plain server-rendered table giving semi-annual DPU with exact
    dates back to the 2006 IPO.

Strictly dynamic: returns an empty DataFrame (with the expected schema)
if either source is unreachable or unparseable -- no hardcoded/fallback
figures. If only one of the two sources succeeds, the dataset is built
from whichever succeeded (fields from the other are left null).
"""

from __future__ import annotations

import logging
import re
from typing import Optional
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup
from io import BytesIO

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

LINK_REIT_HIGHLIGHTS_URL = "https://www.linkreit.com/en/investor-relations/financial-highlights/"
LINK_REIT_DISTRIBUTION_URL = "https://www.linkreit.com/en/investor-relations/distribution/"

_COLUMNS = [
    "date", "period", "ticker", "reit_name", "nav_per_unit_hkd", "dpu_hkd",
    "occupancy_pct", "rental_reversion_pct", "source_agency",
]


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLUMNS)


def _parse_number(value: str) -> Optional[float]:
    if value is None:
        return None
    cleaned = value.replace(",", "").strip()
    if not cleaned or cleaned in {"-", "N/A", "–"}:
        return None
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    try:
        val = float(cleaned)
        return -val if negative else val
    except ValueError:
        return None


def _discover_five_year_pdf_url(headers: dict) -> Optional[str]:
    resp = requests.get(LINK_REIT_HIGHLIGHTS_URL, headers=headers, timeout=20)
    if resp.status_code != 200:
        logger.warning("Link REIT financial-highlights page returned HTTP %s", resp.status_code)
        return None
    soup = BeautifulSoup(resp.text, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "five-year-performance-summary" in href.lower() and ".pdf" in href.lower():
            return urljoin(LINK_REIT_HIGHLIGHTS_URL, href)
    return None


def _extract_five_year_metrics(pdf_bytes: bytes) -> dict:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        full_text = "\n".join((p.extract_text() or "") for p in pdf.pages)

    years: list[str] = []
    # Pull the first line containing repeated "31 March YYYY" (the shared column header).
    for line in full_text.split("\n"):
        found = re.findall(r"31 March (\d{4})", line)
        if len(found) >= 4:
            years = found
            break

    nav_per_unit: dict[str, float] = {}
    for line in full_text.split("\n"):
        if "Net assets per unit attributable to Unitholders" in line:
            nums = re.findall(r"[\d,]+\.\d+", line)
            if years and len(nums) >= len(years):
                nav_per_unit = {y: _parse_number(n) for y, n in zip(years, nums)}
            break

    # Isolate the Hong Kong Portfolio segment for occupancy/reversion (HK-specific figures).
    hk_segment = ""
    parts = re.split(
        r"\n(?=Hong Kong Portfolio|Chinese Mainland Portfolio|Australia Portfolio|United Kingdom Portfolio|Singapore Portfolio)",
        full_text,
    )
    for part in parts:
        if part.startswith("Hong Kong Portfolio"):
            hk_segment = part
            break

    reversion_retail: dict[str, float] = {}
    occupancy_office: dict[str, float] = {}
    occupancy_retail: dict[str, float] = {}
    for line in hk_segment.split("\n"):
        if line.startswith("Reversion rate") and years:
            tail = line.split("%", 1)[-1].strip()
            tokens = tail.split()
            if len(tokens) >= len(years):
                reversion_retail = {y: _parse_number(t) for y, t in zip(years, tokens[: len(years)])}
        elif line.strip().startswith("– Office %") and years and not occupancy_office:
            tail = line.split("%", 1)[-1].strip()
            tokens = tail.split()
            if len(tokens) >= len(years):
                occupancy_office = {y: _parse_number(t) for y, t in zip(years, tokens[: len(years)])}
        elif line.strip().startswith("– Retail %") and years and not occupancy_retail:
            tail = line.split("%", 1)[-1].strip()
            tokens = tail.split()
            if len(tokens) >= len(years):
                occupancy_retail = {y: _parse_number(t) for y, t in zip(years, tokens[: len(years)])}

    return {
        "years": years,
        "nav_per_unit": nav_per_unit,
        "reversion_retail": reversion_retail,
        "occupancy_office": occupancy_office,
        "occupancy_retail": occupancy_retail,
    }


def _fetch_distribution_dpu(headers: dict) -> dict[str, float]:
    resp = requests.get(LINK_REIT_DISTRIBUTION_URL, headers=headers, timeout=20)
    if resp.status_code != 200:
        logger.warning("Link REIT distribution page returned HTTP %s", resp.status_code)
        return {}
    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table")
    if table is None:
        return {}
    dpu_by_year: dict[str, float] = {}
    for tr in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["td", "th"])]
        if cells and re.fullmatch(r"\d{4}", cells[0]) and len(cells) >= 2:
            total = _parse_number(cells[1])
            if total is not None:
                dpu_by_year[cells[0]] = total
    return dpu_by_year


def fetch_linkreit_fundamentals() -> pd.DataFrame:
    """Fetch NAV/unit, DPU, HK-portfolio occupancy, and rental reversion for Link REIT (0823.HK)."""
    headers = {**DEFAULT_HEADERS, "Referer": "https://www.linkreit.com/en/investor-relations/"}

    metrics: dict = {}
    dpu_by_year: dict[str, float] = {}
    raw_source_url = None
    raw_snapshot = None

    try:
        pdf_url = _discover_five_year_pdf_url(headers)
        if pdf_url:
            pdf_resp = requests.get(pdf_url, headers=headers, timeout=30)
            if pdf_resp.status_code == 200:
                raw_snapshot = save_raw_snapshot(
                    "linkreit_fundamentals_pdf", pdf_resp.content, file_ext="pdf", source_url=pdf_url
                )
                metrics = _extract_five_year_metrics(pdf_resp.content)
                raw_source_url = pdf_url
            else:
                logger.warning("Link REIT five-year PDF returned HTTP %s", pdf_resp.status_code)
        else:
            logger.warning("Link REIT: could not discover five-year performance summary PDF link")
    except Exception as exc:
        logger.warning("Link REIT five-year PDF fetch/parse failed: %s", exc)

    try:
        dpu_by_year = _fetch_distribution_dpu(headers)
    except Exception as exc:
        logger.warning("Link REIT distribution page fetch/parse failed: %s", exc)

    years = metrics.get("years") or list(dpu_by_year.keys())
    if not years:
        return _empty_df()

    records = []
    for year in years:
        records.append({
            "date": f"{year}-03-31",
            "period": f"FY{year}",
            "ticker": "0823.HK",
            "reit_name": "Link REIT",
            "nav_per_unit_hkd": metrics.get("nav_per_unit", {}).get(year),
            "dpu_hkd": dpu_by_year.get(year),
            "occupancy_pct": metrics.get("occupancy_retail", {}).get(year),
            "rental_reversion_pct": metrics.get("reversion_retail", {}).get(year),
            "source_agency": "Link REIT Investor Relations",
        })

    df = pd.DataFrame(records)
    if df.empty or df[["nav_per_unit_hkd", "dpu_hkd", "occupancy_pct", "rental_reversion_pct"]].isna().all(axis=None):
        return _empty_df()
    df.attrs.update(
        raw_snapshot=str(raw_snapshot) if raw_snapshot else "",
        source_url=raw_source_url or LINK_REIT_DISTRIBUTION_URL,
    )
    return df
