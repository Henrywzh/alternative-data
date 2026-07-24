"""Fundamentals extractor for Champion REIT (2778.HK).

Scrapes Champion REIT's own investor-relations pages, which are fully
server-side-rendered (Nuxt.js, `data-server-rendered="true"`) plain HTML
tables -- verified via direct `curl` (no headless browser/JS execution
needed). See .claude/skills/data-source-deep-dive/references/
reit-championreit-02778-findings.md for the verification trail.

Two pages are combined:
  - /investor-relations/financial-summary: annual NAV/unit, DPU,
    occupancy (Three Garden Road, Langham Place office/mall), passing
    rent -- 2021-2025 in one table.
  - /investor-relations/distribution-history: semi-annual DPU with
    exact declaration/payment dates (used to cross-check the annual
    total, not stored as separate rows here).

Strictly dynamic: returns an empty DataFrame (with the expected schema)
if either page is unreachable or the table structure can't be parsed --
no hardcoded/fallback figures.
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

CHAMPION_REIT_FINANCIAL_SUMMARY_URL = "https://www.championreit.com/investor-relations/financial-summary"

_COLUMNS = [
    "date", "period", "ticker", "reit_name", "nav_per_unit_hkd", "dpu_hkd",
    "three_garden_road_occupancy_pct", "langham_place_office_occupancy_pct",
    "langham_place_mall_occupancy_pct", "occupancy_pct",
    "rental_reversion_pct", "source_agency",
]


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLUMNS)


def _parse_pct(value: str) -> Optional[float]:
    if value is None:
        return None
    cleaned = value.replace("%", "").replace(",", "").strip()
    if not cleaned or cleaned in {"-", "N/A"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_money(value: str) -> Optional[float]:
    if value is None:
        return None
    cleaned = value.replace("$", "").replace(",", "").strip()
    if not cleaned or cleaned in {"-", "N/A"}:
        return None
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    try:
        val = float(cleaned)
        return -val if negative else val
    except ValueError:
        return None


def _table_rows(table) -> list[list[str]]:
    return [[c.get_text(strip=True) for c in tr.find_all(["td", "th"])] for tr in table.find_all("tr")]


def fetch_championreit_fundamentals() -> pd.DataFrame:
    """Fetch NAV/unit, DPU, and per-asset occupancy for Champion REIT (2778.HK)."""
    headers = {**DEFAULT_HEADERS, "Referer": "https://www.championreit.com/investor-relations/"}

    try:
        response = requests.get(CHAMPION_REIT_FINANCIAL_SUMMARY_URL, headers=headers, timeout=20)
        if response.status_code != 200:
            logger.warning("Champion REIT financial-summary returned HTTP %s", response.status_code)
            return _empty_df()

        raw_path = save_raw_snapshot(
            "championreit_fundamentals", response.text, file_ext="html",
            source_url=CHAMPION_REIT_FINANCIAL_SUMMARY_URL,
        )

        soup = BeautifulSoup(response.text, "lxml")
        tables = soup.find_all("table")
        if not tables:
            logger.warning("Champion REIT financial-summary: no <table> found")
            return _empty_df()

        years: list[str] = []
        dpu: dict[str, float] = {}
        nav: dict[str, float] = {}
        tgr_occ: dict[str, float] = {}
        lp_office_occ: dict[str, float] = {}
        lp_mall_occ: dict[str, float] = {}

        for table in tables:
            rows = _table_rows(table)
            if not rows:
                continue
            header = rows[0]
            if not years and len(header) > 1 and all(re.fullmatch(r"20\d{2}", h) for h in header[1:] if h):
                years = [h for h in header[1:] if h]

            for row in rows[1:]:
                if not row:
                    continue
                label = row[0]
                values = row[1:]
                if not years or len(values) < len(years):
                    continue
                if label == "Distribution per Unit":
                    dpu = {y: _parse_money(v) for y, v in zip(years, values)}
                elif label == "Net Asset Value per Unit":
                    nav = {y: _parse_money(v) for y, v in zip(years, values)}
                elif label == "Three Garden Road Office Occupancy":
                    tgr_occ = {y: _parse_pct(v) for y, v in zip(years, values)}
                elif label == "Langham Place Office Occupancy":
                    lp_office_occ = {y: _parse_pct(v) for y, v in zip(years, values)}
                elif label == "Langham Place Mall Occupancy":
                    lp_mall_occ = {y: _parse_pct(v) for y, v in zip(years, values)}

        if not years or not dpu:
            logger.warning("Champion REIT financial-summary: expected rows not found in parsed table")
            return _empty_df()

        records = []
        for year in years:
            records.append({
                "date": f"{year}-12-31",
                "period": f"FY{year}",
                "ticker": "2778.HK",
                "reit_name": "Champion REIT",
                "nav_per_unit_hkd": nav.get(year),
                "dpu_hkd": dpu.get(year),
                "three_garden_road_occupancy_pct": tgr_occ.get(year),
                "langham_place_office_occupancy_pct": lp_office_occ.get(year),
                "langham_place_mall_occupancy_pct": lp_mall_occ.get(year),
                "occupancy_pct": tgr_occ.get(year),
                "rental_reversion_pct": None,  # Not published as a single figure on this page.
                "source_agency": "Champion REIT Investor Relations",
            })

        df = pd.DataFrame(records)
        if df.empty:
            return _empty_df()
        df.attrs.update(raw_snapshot=str(raw_path), source_url=CHAMPION_REIT_FINANCIAL_SUMMARY_URL)
        return df
    except Exception as exc:
        logger.warning("Champion REIT financial-summary unreachable or unparseable: %s", exc)
        return _empty_df()
