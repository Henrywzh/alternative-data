"""Fundamentals extractor for Prosperity REIT (0808.HK).

Scrapes Prosperity REIT's own investor-relations "Financial Highlights"
page. The page is a Vue.js app, but the data is passed as a JSON-encoded
`:data="[...]"` prop on `<financial-table>` custom elements, present
directly in the raw (unrendered) HTML response -- verified via direct
`curl` (no headless browser/JS execution needed). See
.claude/skills/data-source-deep-dive/references/
reit-prosperityreit-00808-findings.md for the verification trail.

Strictly dynamic: returns an empty DataFrame (with the expected schema)
if the page is unreachable or the expected `<financial-table>` blocks
can't be found/parsed -- no hardcoded/fallback figures.
"""

from __future__ import annotations

import html
import json
import logging
import re
from typing import Optional

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

PROSPERITY_REIT_HIGHLIGHTS_URL = "https://www.prosperityreit.com/en/investor-relations/financial_highlights"

_COLUMNS = [
    "date", "period", "ticker", "reit_name", "nav_per_unit_hkd", "dpu_hkd",
    "occupancy_pct", "rental_reversion_pct", "source_agency",
]

_DATA_ATTR_RE = re.compile(r'<financial-table[^>]*:data="([^"]+)"')


def _empty_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLUMNS)


def _parse_number(value: str) -> Optional[float]:
    if value is None:
        return None
    cleaned = value.replace("%", "").replace(",", "").strip()
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


def fetch_prosperityreit_fundamentals() -> pd.DataFrame:
    """Fetch NAV/unit, DPU, occupancy, and rental reversion for Prosperity REIT (0808.HK)."""
    headers = {**DEFAULT_HEADERS, "Referer": "https://www.prosperityreit.com/en/investor-relations/"}

    try:
        response = requests.get(PROSPERITY_REIT_HIGHLIGHTS_URL, headers=headers, timeout=20)
        if response.status_code != 200:
            logger.warning("Prosperity REIT financial_highlights returned HTTP %s", response.status_code)
            return _empty_df()

        raw_path = save_raw_snapshot(
            "prosperityreit_fundamentals", response.text, file_ext="html",
            source_url=PROSPERITY_REIT_HIGHLIGHTS_URL,
        )

        matches = _DATA_ATTR_RE.findall(response.text)
        if not matches:
            logger.warning("Prosperity REIT financial_highlights: no <financial-table> data attrs found")
            return _empty_df()

        years: list[str] = []
        dpu: dict[str, float] = {}
        nav: dict[str, float] = {}
        occ: dict[str, float] = {}
        reversion: dict[str, float] = {}

        for raw_attr in matches:
            try:
                table = json.loads(html.unescape(raw_attr))
            except json.JSONDecodeError:
                continue
            header_row = None
            for row in table:
                cells = [c for c in row if c]
                if len(cells) >= 4 and all(re.fullmatch(r"20\d{2}", c) for c in cells[-4:] if re.fullmatch(r"\d{4}", c or "")):
                    pass
                if row and re.search(r"20\d{2}", "".join(row)):
                    year_cells = [c for c in row if re.fullmatch(r"20\d{2}", c)]
                    if len(year_cells) >= 4:
                        header_row = row
                        years = year_cells
                        break
            if header_row is None:
                continue

            for row in table:
                if not row or not row[0]:
                    continue
                label = row[0].strip().lower()
                values = [v for v in row[1:] if v != ""][: len(years)]
                if len(values) < len(years):
                    continue
                if "distribution per unit" in label:
                    dpu = {y: _parse_number(v) for y, v in zip(years, values)}
                elif "net asset value per unit" in label:
                    nav = {y: _parse_number(v) for y, v in zip(years, values)}
                elif label.startswith("occupan"):
                    occ = {y: _parse_number(v) for y, v in zip(years, values)}
                elif "rental reversion" in label:
                    reversion = {y: _parse_number(v) for y, v in zip(years, values)}

        if not years or not dpu:
            logger.warning("Prosperity REIT financial_highlights: expected rows not found in parsed tables")
            return _empty_df()

        records = []
        for year in years:
            records.append({
                "date": f"{year}-12-31",
                "period": f"FY{year}",
                "ticker": "0808.HK",
                "reit_name": "Prosperity REIT",
                "nav_per_unit_hkd": nav.get(year),
                "dpu_hkd": dpu.get(year),
                "occupancy_pct": occ.get(year),
                "rental_reversion_pct": reversion.get(year),
                "source_agency": "Prosperity REIT Investor Relations",
            })

        df = pd.DataFrame(records)
        if df.empty:
            return _empty_df()
        df.attrs.update(raw_snapshot=str(raw_path), source_url=PROSPERITY_REIT_HIGHLIGHTS_URL)
        return df
    except Exception as exc:
        logger.warning("Prosperity REIT financial_highlights unreachable or unparseable: %s", exc)
        return _empty_df()
