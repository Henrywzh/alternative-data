"""MTR Corporation Monthly Patronage Statistics.

Parses monthly passenger journeys ('000s) and daily averages from MTR Investor Relations:
- Domestic Service (heavy rail)
- Airport Express
- Cross-boundary (Lo Wu & Lok Ma Chau)
- Light Rail & Bus
- High Speed Rail (HSR)
"""

from __future__ import annotations

import logging
import re

import pandas as pd
import requests
from bs4 import BeautifulSoup

from ..config import DEFAULT_HEADERS, MTR_PATRONAGE_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "month",
    "date",
    "domestic_service_thousands",
    "domestic_service_daily_avg_thousands",
    "airport_express_thousands",
    "airport_express_daily_avg_thousands",
    "cross_boundary_thousands",
    "cross_boundary_daily_avg_thousands",
    "light_rail_bus_thousands",
    "light_rail_bus_daily_avg_thousands",
    "hsr_thousands",
    "hsr_daily_avg_thousands",
    "total_mtr_patronage_thousands",
]

MONTH_MAP = {
    "Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
    "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
    "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12",
}


def _clean_num(val: str) -> float:
    """Clean formatted number string into float."""
    if not val or val == "-" or val == "N/A":
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", val)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def fetch_mtr_patronage() -> pd.DataFrame:
    """Fetch and parse MTR monthly patronage statistics."""
    resp = requests.get(MTR_PATRONAGE_URL, headers=DEFAULT_HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")

    rows_data = []

    # Table 2 contains historical monthly rows
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cols = [c.get_text(strip=True) for c in row.find_all(["th", "td"])]
            if len(cols) >= 11 and any(m in cols[0] for m in MONTH_MAP.keys()):
                # Format: ['Jun 2026', '128,248', '4,563', '1,030', '34.3', '8,591', '286', '18,047', '602', '2,477', '82.6']
                month_str = cols[0].strip()
                parts = month_str.split()
                if len(parts) == 2 and parts[0] in MONTH_MAP:
                    m_code = MONTH_MAP[parts[0]]
                    year_str = parts[1]
                    month_key = f"{year_str}-{m_code}"
                    date_key = f"{month_key}-01"

                    dom_tot = _clean_num(cols[1])
                    dom_avg = _clean_num(cols[2])
                    aex_tot = _clean_num(cols[3])
                    aex_avg = _clean_num(cols[4])
                    xb_tot = _clean_num(cols[5])
                    xb_avg = _clean_num(cols[6])
                    lrb_tot = _clean_num(cols[7])
                    lrb_avg = _clean_num(cols[8])
                    hsr_tot = _clean_num(cols[9])
                    hsr_avg = _clean_num(cols[10])

                    tot_patronage = dom_tot + aex_tot + xb_tot + lrb_tot + hsr_tot

                    rows_data.append({
                        "month": month_key,
                        "date": date_key,
                        "domestic_service_thousands": dom_tot,
                        "domestic_service_daily_avg_thousands": dom_avg,
                        "airport_express_thousands": aex_tot,
                        "airport_express_daily_avg_thousands": aex_avg,
                        "cross_boundary_thousands": xb_tot,
                        "cross_boundary_daily_avg_thousands": xb_avg,
                        "light_rail_bus_thousands": lrb_tot,
                        "light_rail_bus_daily_avg_thousands": lrb_avg,
                        "hsr_thousands": hsr_tot,
                        "hsr_daily_avg_thousands": hsr_avg,
                        "total_mtr_patronage_thousands": tot_patronage,
                    })

    if not rows_data:
        logger.warning("No MTR patronage rows parsed from investor relations page.")
        return pd.DataFrame(columns=SCHEMA_COLUMNS)

    df = pd.DataFrame(rows_data)
    df["date"] = pd.to_datetime(df["date"])
    df = df.drop_duplicates(subset=["month"]).sort_values("date").reset_index(drop=True)

    result = df[SCHEMA_COLUMNS]

    raw_path = save_raw_snapshot(
        "mtr_patronage",
        result.to_dict(orient="records"),
        file_ext="json",
        source_url=MTR_PATRONAGE_URL,
    )
    result.attrs["raw_snapshot"] = str(raw_path)
    result.attrs["source_url"] = MTR_PATRONAGE_URL
    return result
