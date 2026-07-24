"""Fundamentals extractor for Fortune REIT (0778.HK).

Scrapes Fortune REIT's own investor-relations "highlights" page
(`https://www.fortunereit.com/en/ir/highlights.php`), a plain
server-rendered WordPress HTML page containing a 5-year (2021-2025)
table of NAV/unit, DPU, and occupancy -- verified via direct `curl`
(no JS execution needed). See .claude/skills/data-source-deep-dive/
references/reit-fortunereit-00778-findings.md for the verification
trail.

Fortune REIT does not publish a single numeric "rental reversion %"
figure (disclosure is qualitative/directional only per the deep-dive
findings) -- that field is intentionally left null rather than
fabricated.

Strictly dynamic: returns an empty DataFrame (with the expected schema)
if the page is unreachable or the expected tables can't be found -- no
hardcoded/fallback figures.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

FORTUNE_REIT_HIGHLIGHTS_URL = "https://www.fortunereit.com/en/ir/highlights.php"

_COLUMNS = [
    "date", "period", "ticker", "reit_name", "nav_per_unit_hkd", "dpu_hkd",
    "occupancy_pct", "rental_reversion_pct", "source_agency",
]


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLUMNS)


def _parse_number(value: str) -> Optional[float]:
    if value is None:
        return None
    cleaned = value.replace("%", "").replace(",", "").strip()
    if not cleaned or cleaned in {"-", "N/A"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _table_rows(table) -> list[list[str]]:
    return [[c.get_text(strip=True) for c in tr.find_all(["td", "th"])] for tr in table.find_all("tr")]


def fetch_fortunereit_fundamentals() -> pd.DataFrame:
    """Fetch NAV/unit, DPU, and occupancy for Fortune REIT (0778.HK), 5-year annual series."""
    headers = {**DEFAULT_HEADERS, "Referer": "https://www.fortunereit.com/en/ir/"}

    try:
        response = requests.get(FORTUNE_REIT_HIGHLIGHTS_URL, headers=headers, timeout=20)
        if response.status_code != 200:
            logger.warning("Fortune REIT highlights.php returned HTTP %s", response.status_code)
            return _empty_df()

        raw_path = save_raw_snapshot(
            "fortunereit_fundamentals", response.text, file_ext="html",
            source_url=FORTUNE_REIT_HIGHLIGHTS_URL,
        )

        soup = BeautifulSoup(response.text, "lxml")
        tables = soup.find_all("table")
        if not tables:
            logger.warning("Fortune REIT highlights.php: no <table> found")
            return _empty_df()

        years: list[str] = []
        dpu: dict[str, float] = {}
        nav: dict[str, float] = {}
        occ: dict[str, float] = {}

        for table in tables:
            rows = _table_rows(table)
            if not rows:
                continue
            header = rows[0]
            # Only the 5-year tables have a year-only header row (2025, 2024, 2023, 2022, 2021).
            year_header = [h for h in header[1:] if re.fullmatch(r"20\d{2}", h)]
            if len(year_header) < 4:
                continue
            years = year_header

            for row in rows[1:]:
                if not row:
                    continue
                label = row[0]
                values = row[1:1 + len(years)]
                if len(values) < len(years):
                    continue
                if label.startswith("DPU"):
                    dpu = {y: _parse_number(v) for y, v in zip(years, values)}
                elif label.startswith("NAV per Unit"):
                    nav = {y: _parse_number(v) for y, v in zip(years, values)}
                elif label == "Occupancy":
                    occ = {y: _parse_number(v) for y, v in zip(years, values)}

        if not years or not dpu:
            logger.warning("Fortune REIT highlights.php: expected 5-year rows not found")
            return _empty_df()

        records = []
        for year in years:
            records.append({
                "date": f"{year}-12-31",
                "period": f"FY{year}",
                "ticker": "0778.HK",
                "reit_name": "Fortune REIT",
                "nav_per_unit_hkd": nav.get(year),
                "dpu_hkd": (dpu[year] / 100.0) if dpu.get(year) is not None else None,  # HK cents -> HK$
                "occupancy_pct": occ.get(year),
                "rental_reversion_pct": None,  # Not disclosed as a single numeric figure by this REIT.
                "source_agency": "Fortune REIT Investor Relations",
            })

        df = pd.DataFrame(records)
        if df.empty:
            return _empty_df()
        df.attrs.update(raw_snapshot=str(raw_path), source_url=FORTUNE_REIT_HIGHLIGHTS_URL)
        return df
    except Exception as exc:
        logger.warning("Fortune REIT highlights.php unreachable or unparseable: %s", exc)
        return _empty_df()
