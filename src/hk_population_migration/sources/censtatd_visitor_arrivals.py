"""C&SD Table 650-80001: Visitor arrivals by nationality/region, monthly since 2004.

Direct companion/cross-check to the existing ImmD daily cross-border
passenger CSV (``immd_daily_traffic.py``) -- this table gives the full
monthly geographic breakdown (Mainland/Taiwan/Macao/Europe/Americas/etc.)
that ImmD's control-point data doesn't.

Uses the documented ``api/get.php`` JSON endpoint (not the MDT_ static-CSV
pattern) because this endpoint already returns a human-readable
``REGIONDesc`` label per row -- no separate classification-code lookup
needed. This also sidesteps a real footgun in the MDT_ CSV file for this
specific table: one of the real region codes is the literal string "NA"
(North Asia), which `pandas.read_csv` silently parses as a missing value
by default -- confirmed by comparing the CSV and JSON API responses
directly while building this module.
"""

from __future__ import annotations

import logging

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

VISITOR_ARRIVALS_TABLE_ID = "650-80001"
VISITOR_ARRIVALS_API_URL = f"https://www.censtatd.gov.hk/api/get.php?id={VISITOR_ARRIVALS_TABLE_ID}&lang=en&full_series=1"

BY_REGION_COLUMNS = ["date", "region", "visitors"]
MAINLAND_VS_ROW_COLUMNS = ["date", "series", "visitors"]


def fetch_visitor_arrivals_by_region() -> pd.DataFrame:
    """Monthly visitor arrivals by region (excludes the source's own Total row)."""
    try:
        response = requests.get(VISITOR_ARRIVALS_API_URL, headers=DEFAULT_HEADERS, timeout=20)
        response.raise_for_status()
        save_raw_snapshot("censtatd_visitor_arrivals", response.content, file_ext="json", source_url=VISITOR_ARRIVALS_API_URL)
        rows = response.json().get("dataSet", [])
    except Exception as exc:
        # Honest empty frame on network failure, matching the other C&SD
        # fetchers in this repo -- never a fabricated/stale substitute.
        logger.warning(f"Network fetch failed for C&SD visitor arrivals ({exc}).")
        df = pd.DataFrame(columns=BY_REGION_COLUMNS)
        df.attrs.update(source_url=VISITOR_ARRIVALS_API_URL)
        return df

    records = []
    for row in rows:
        if row.get("freq") != "M" or not row.get("REGION"):
            continue
        figure = row.get("figure")
        if not isinstance(figure, (int, float)):
            continue
        period = str(row["period"])
        records.append(
            {
                "date": f"{period[:4]}-{period[4:6]}",
                "region": str(row.get("REGIONDesc", row["REGION"])).strip(),
                "visitors": float(figure),
            }
        )

    df = pd.DataFrame(records, columns=BY_REGION_COLUMNS)
    if not df.empty:
        df = df.sort_values(["region", "date"]).reset_index(drop=True)
    df.attrs.update(source_url=VISITOR_ARRIVALS_API_URL)
    return df


def mainland_vs_rest_of_world(by_region: pd.DataFrame) -> pd.DataFrame:
    """Collapse the full region breakdown into a 2-series view (Mainland vs. Rest of World).

    Mainland China dominates the raw region breakdown so heavily that a
    faithful all-region chart would either need many legend entries (over
    this project's mobile-viewport chart series cap) or bury every other
    region at an unreadable scale next to it -- this two-series split is
    the informative summary, with the full per-region table still
    available in ``by_region`` for anyone wanting the detail.
    """
    if by_region.empty:
        return pd.DataFrame(columns=MAINLAND_VS_ROW_COLUMNS)
    mainland = by_region[by_region["region"] == "Chinese Mainland"].copy()
    mainland["series"] = "Mainland China"
    rest = by_region[by_region["region"] != "Chinese Mainland"].groupby("date", as_index=False)["visitors"].sum()
    rest["series"] = "Rest of World"
    combined = pd.concat([mainland[MAINLAND_VS_ROW_COLUMNS], rest[MAINLAND_VS_ROW_COLUMNS]], ignore_index=True)
    return combined.sort_values(["series", "date"]).reset_index(drop=True)
