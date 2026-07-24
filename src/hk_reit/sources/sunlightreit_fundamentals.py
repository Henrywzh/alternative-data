"""Fundamentals extractor for Sunlight REIT (0435.HK).

Combines two of Sunlight REIT's own sources (both verified live, see
.claude/skills/data-source-deep-dive/references/
reit-sunlightreit-00435-findings.md):

  - `https://www.sunlightreit.com/investor-relations/financial-highlights/`:
    a plain WordPress-rendered HTML table giving NAV/unit, DPU, and
    gearing across several periods (annual/18-month-stub/semi-annual --
    Sunlight REIT changed its fiscal year-end from June to December).
  - The quarterly "Operational Statistics" announcement PDF, whose URL
    is NOT fixed/predictable -- it is discovered each run by crawling
    the announcements listing page
    (`https://www.sunlightreit.com/investor-relations/corporate-communications/announcements/`)
    and picking the newest link whose text/href contains "Operational
    Statistics". This PDF is the source for portfolio occupancy rate and
    rental reversion (quarterly cadence, higher frequency than the
    semi-annual results announcements).

Strictly dynamic: returns an empty DataFrame (with the expected schema)
if both sources fail -- no hardcoded/fallback figures. If only the
highlights table succeeds, occupancy/reversion are left null rather
than fabricated; the announcements-page PDF discovery step is repeated
on every call (never a cached/hardcoded PDF URL), since the URL changes
every quarter.
"""

from __future__ import annotations

import logging
import re
from io import BytesIO
from typing import Optional
from urllib.parse import urljoin

import pandas as pd
import pdfplumber
import requests
from bs4 import BeautifulSoup

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SUNLIGHT_REIT_HIGHLIGHTS_URL = "https://www.sunlightreit.com/investor-relations/financial-highlights/"
SUNLIGHT_REIT_ANNOUNCEMENTS_URL = "https://www.sunlightreit.com/investor-relations/corporate-communications/announcements/"

_COLUMNS = [
    "date", "period", "ticker", "reit_name", "nav_per_unit_hkd", "dpu_hkd",
    "occupancy_pct", "rental_reversion_pct", "source_agency",
]


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLUMNS)


def _parse_number(value: str) -> Optional[float]:
    if value is None:
        return None
    cleaned = value.replace("\xa0", " ").replace(",", "").strip()
    if not cleaned or cleaned in {"-", "N/A"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


_PERIOD_TO_DATE = {
    "31 December 2025": "2025-12-31",
    "31 December 2024": "2024-12-31",  # 18 months ended (FY-end transition stub period)
    "2023": "2023-06-30",
    "2022": "2022-06-30",
    "2021": "2021-06-30",
}


def _fetch_highlights(headers: dict) -> dict:
    resp = requests.get(SUNLIGHT_REIT_HIGHLIGHTS_URL, headers=headers, timeout=20)
    if resp.status_code != 200:
        logger.warning("Sunlight REIT financial-highlights returned HTTP %s", resp.status_code)
        return {}
    save_raw_snapshot(
        "sunlightreit_fundamentals_highlights", resp.text, file_ext="html",
        source_url=SUNLIGHT_REIT_HIGHLIGHTS_URL,
    )
    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table")
    if table is None:
        return {}

    rows = [[c.get_text(strip=True) for c in tr.find_all(["td", "th"])] for tr in table.find_all("tr")]
    if len(rows) < 2:
        return {}

    period_row = rows[1]
    periods = [p for p in period_row if p]
    dpu_row = next((r for r in rows if r and r[0].startswith("DPU")), None)
    nav_row = next((r for r in rows if r and r[0].startswith("Net asset value per unit")), None)

    dpu = {p: _parse_number(v) for p, v in zip(periods, (dpu_row[1:] if dpu_row else []))}
    nav = {p: _parse_number(v) for p, v in zip(periods, (nav_row[1:] if nav_row else []))}
    return {"periods": periods, "dpu": dpu, "nav": nav}


def _discover_latest_operational_statistics_pdf(headers: dict) -> Optional[str]:
    resp = requests.get(SUNLIGHT_REIT_ANNOUNCEMENTS_URL, headers=headers, timeout=20)
    if resp.status_code != 200:
        logger.warning("Sunlight REIT announcements page returned HTTP %s", resp.status_code)
        return None
    soup = BeautifulSoup(resp.text, "lxml")
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        if "operational_statistics" in href.lower() or "operational statistics" in text.lower():
            candidates.append(urljoin(SUNLIGHT_REIT_ANNOUNCEMENTS_URL, href))
    if not candidates:
        return None
    # Filenames embed the as-of date; lexicographic sort of the upload path (YYYY/MM) is a
    # reasonable proxy for recency, but the safest signal is just "first one listed" since the
    # page lists announcements newest-first.
    return candidates[0]


def _extract_operational_stats(pdf_bytes: bytes) -> dict:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)

    result: dict = {}
    m = re.search(r"FOR THE QUARTER ENDED\s+(\d{1,2}\s+\w+\s+\d{4})", text, re.IGNORECASE)
    if m:
        result["as_of_text"] = m.group(1)

    m = re.search(
        r"portfolio occupancy rate of Sunlight REIT was\s+([\d.]+)%",
        text, re.IGNORECASE,
    )
    if m:
        result["occupancy_pct"] = float(m.group(1))

    m = re.search(
        r"rental reversion for the quarter under review came in at\s+(negative|positive)?\s*([\d.]+)%",
        text, re.IGNORECASE,
    )
    if m:
        sign = -1.0 if (m.group(1) or "").lower() == "negative" else 1.0
        result["rental_reversion_pct"] = sign * float(m.group(2))

    return result


def fetch_sunlightreit_fundamentals() -> pd.DataFrame:
    """Fetch NAV/unit, DPU (from financial-highlights) and occupancy/reversion
    (from the latest discovered Operational Statistics PDF) for Sunlight REIT (0435.HK)."""
    headers = {**DEFAULT_HEADERS, "Referer": "https://www.sunlightreit.com/investor-relations/"}

    highlights: dict = {}
    try:
        highlights = _fetch_highlights(headers)
    except Exception as exc:
        logger.warning("Sunlight REIT financial-highlights fetch/parse failed: %s", exc)

    ops_stats: dict = {}
    ops_pdf_url = None
    try:
        ops_pdf_url = _discover_latest_operational_statistics_pdf(headers)
        if ops_pdf_url:
            pdf_resp = requests.get(ops_pdf_url, headers=headers, timeout=30)
            if pdf_resp.status_code == 200:
                save_raw_snapshot(
                    "sunlightreit_fundamentals_ops_pdf", pdf_resp.content, file_ext="pdf",
                    source_url=ops_pdf_url,
                )
                ops_stats = _extract_operational_stats(pdf_resp.content)
            else:
                logger.warning("Sunlight REIT Operational Statistics PDF returned HTTP %s", pdf_resp.status_code)
        else:
            logger.warning("Sunlight REIT: could not discover latest Operational Statistics PDF on announcements page")
    except Exception as exc:
        logger.warning("Sunlight REIT Operational Statistics PDF fetch/parse failed: %s", exc)

    periods = highlights.get("periods") or []
    if not periods:
        return _empty_df()

    records = []
    for i, period in enumerate(periods):
        date_val = _PERIOD_TO_DATE.get(period)
        if not date_val:
            continue
        is_latest = i == 0
        records.append({
            "date": date_val,
            "period": period,
            "ticker": "0435.HK",
            "reit_name": "Sunlight REIT",
            "nav_per_unit_hkd": highlights.get("nav", {}).get(period),
            "dpu_hkd": (highlights.get("dpu", {}).get(period) / 100.0)
            if highlights.get("dpu", {}).get(period) is not None else None,  # HK cents -> HK$
            "occupancy_pct": ops_stats.get("occupancy_pct") if is_latest else None,
            "rental_reversion_pct": ops_stats.get("rental_reversion_pct") if is_latest else None,
            "source_agency": "Sunlight REIT Investor Relations",
        })

    df = pd.DataFrame(records)
    if df.empty:
        return _empty_df()
    df.attrs.update(raw_snapshot=ops_pdf_url or "", source_url=SUNLIGHT_REIT_HIGHLIGHTS_URL)
    return df
