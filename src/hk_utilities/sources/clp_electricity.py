"""CLP Power Hong Kong Quarterly Electricity Sales by Customer Sector.

Fetches and parses CLP Holdings' genuine HKEX "Quarterly Statement" PDF
filings (Q1 standalone statements; other quarters use narrative-only or
cumulative disclosures and are intentionally not covered here to avoid
inventing figures for periods that were not fetched and parsed).

Real quarterly sales by sector (GWh) are extracted directly from the PDF
text of each filing:
- Residential
- Commercial
- Infrastructure and Public Services
- Manufacturing

No historical figures are hardcoded. If a filing cannot be fetched or
parsed, that period is simply absent from the result -- never
back-filled with guessed numbers.
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date

import pandas as pd
import pdfplumber
import requests

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "quarter",
    "date",
    "residential_gwh",
    "commercial_gwh",
    "infrastructure_public_gwh",
    "manufacturing_gwh",
    "total_local_gwh",
    "ai_data_centre_yoy_pct",
]

# CLP Holdings publishes its Q1 "Quarterly Statement" as an HKEX announcement
# hosted on its investor-relations domain (clpgroup.com), on a stable
# per-year URL pattern. This pattern has been verified back to 2023
# (2021/2022 return 404 -- a genuine gap in this URL scheme, not fetched).
_Q1_URL_TEMPLATE = (
    "https://www.clpgroup.com/content/dam/clp-group/channels/investor/document/"
    "3-3-financial-reports/{year}/e_1st%20Quarterly%20Statement"
    "%20(announcement%20version)_final.pdf.coredownload.pdf"
)

_EARLIEST_YEAR = 2023

_TITLE_RE = re.compile(r"Quarterly Statement (\d{4}) \(([A-Za-z–\-\s]+)\)")
_TOTAL_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*gigawatt\s*hours\s*\(GWh\)", re.IGNORECASE)
_SECTOR_RE = re.compile(
    r"(Residential|Commercial|Infrastructure and Public Services|Manufacturing)"
    r"\s+([\d,]+)\s+(\(?-?[\d.]+%\)?)\s+(\d+)%"
)
_DATA_CENTRE_RE = re.compile(r"data centre[s]?[^.]*?(-?\d+\.?\d*)%", re.IGNORECASE)

_SECTOR_COL_MAP = {
    "Residential": "residential_gwh",
    "Commercial": "commercial_gwh",
    "Infrastructure and Public Services": "infrastructure_public_gwh",
    "Manufacturing": "manufacturing_gwh",
}


def _parse_pct(raw: str) -> float:
    """Parse a percentage token, treating parenthesised values as negative."""
    negative = raw.strip().startswith("(")
    value = float(re.sub(r"[()%]", "", raw))
    return -value if negative else value


def _parse_statement(pdf_bytes: bytes) -> dict | None:
    """Parse a single CLP Quarterly Statement PDF's first page.

    Returns a dict of parsed fields, or None if the expected sector table
    was not found (rather than guessing/back-filling).
    """
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = pdf.pages[0].extract_text() or ""

    title_match = _TITLE_RE.search(text)
    if not title_match:
        return None

    year = int(title_match.group(1))
    period_label = title_match.group(2).strip()
    # Only accept standalone Q1 statements (January - March); other periods
    # (e.g. "January - September") are cumulative, not a single quarter's
    # sales, and are deliberately excluded to avoid mislabeling them.
    if "March" not in period_label or "January" not in period_label:
        logger.info("Skipping non-Q1 period '%s %s' (cumulative, not a discrete quarter)", year, period_label)
        return None

    sector_matches = _SECTOR_RE.findall(text)
    if len(sector_matches) < 4:
        logger.warning("Expected 4 sectors, found %d for %s", len(sector_matches), year)
        return None

    sectors: dict[str, float] = {}
    for name, value, _pct, _share in sector_matches:
        col = _SECTOR_COL_MAP.get(name)
        if col is None:
            continue
        sectors[col] = float(value.replace(",", ""))

    if len(sectors) < 4:
        return None

    total_match = _TOTAL_RE.search(text)
    total_gwh = float(total_match.group(1).replace(",", "")) if total_match else sum(sectors.values())

    dc_match = _DATA_CENTRE_RE.search(text)
    ai_dc_pct = float(dc_match.group(1)) if dc_match else None

    return {
        "quarter": f"{year} Q1",
        "date": date(year, 3, 31).isoformat(),
        "total_local_gwh": total_gwh,
        "ai_data_centre_yoy_pct": ai_dc_pct,
        **sectors,
    }


def fetch_clp_electricity() -> pd.DataFrame:
    """Fetch and normalize CLP Power HK Q1 quarterly electricity sales.

    Iterates known Q1 "Quarterly Statement" filings from _EARLIEST_YEAR
    through the current year. Years whose filing cannot be fetched (404,
    not yet published) or parsed (unexpected layout) are silently skipped
    -- never substituted with fabricated data.
    """
    current_year = date.today().year
    records: list[dict] = []
    raw_snapshots: dict[str, str] = {}

    for year in range(_EARLIEST_YEAR, current_year + 1):
        url = _Q1_URL_TEMPLATE.format(year=year)
        try:
            resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=20)
        except requests.RequestException as exc:
            logger.info("CLP Q1 statement fetch failed for %s: %s", year, exc)
            continue

        if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
            logger.info("CLP Q1 statement not available for %s (status=%s)", year, resp.status_code)
            continue

        parsed = _parse_statement(resp.content)
        if parsed is None:
            logger.warning("CLP Q1 statement for %s fetched but could not be parsed", year)
            continue

        records.append(parsed)
        raw_path = save_raw_snapshot(
            f"clp_electricity_q1_{year}",
            resp.content,
            file_ext="pdf",
            source_url=url,
        )
        raw_snapshots[str(year)] = str(raw_path)

    if not records:
        result = pd.DataFrame(columns=SCHEMA_COLUMNS)
        result.attrs["raw_snapshot"] = None
        result.attrs["source_url"] = _Q1_URL_TEMPLATE.format(year=current_year)
        return result

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    result = df[SCHEMA_COLUMNS].sort_values("date").reset_index(drop=True)
    result.attrs["raw_snapshot"] = raw_snapshots
    result.attrs["source_url"] = "https://www.clpgroup.com/en/investors/financial-reports.html"
    return result
