"""FEHD (Food and Environmental Hygiene Department) licensed restaurant directory.

Real endpoint: ``https://www.fehd.gov.hk/english/licensing/license/text/LP_Restaurants_EN.XML``
-- verified 200 OK, ~4.8MB, 17,144 real restaurant licence records
(General/Light Refreshment/Marine restaurant licences), regenerated daily
(``GENERATION_DATE`` matches the fetch date). District and licence-type
labels are looked up from the same XML's own ``<DIST_CODE>``/``<TYPE_CODE>``
tables rather than hardcoded, since FEHD's own code list is the ground
truth and (as with any government code table) could in principle change.

This is a **current-state snapshot only** -- there is no issue-date or
status-history field in the source, so "how many restaurants opened or
closed" cannot be read directly. Each pipeline run persists an immutable,
run_id-scoped snapshot (see ``pipeline.py``'s ``fehd_licensed_premises_daily``
entry); ``compute_density_by_district`` derives the current-state census
(usable immediately), and ``diff_against_previous_snapshot`` derives a
net-change signal by comparing today's LICNO set against the most recent
prior stored snapshot -- which is necessarily empty/unavailable on the
first run and thin for the first several days, the same honest
accumulate-over-time pattern already used by this sector's AFCD wholesale
price trend (no historical archive exists upstream for either dataset).
"""

from __future__ import annotations

import logging
from datetime import date
from xml.etree import ElementTree as ET

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

FEHD_RESTAURANTS_XML_URL = "https://www.fehd.gov.hk/english/licensing/license/text/LP_Restaurants_EN.XML"

SNAPSHOT_COLUMNS = [
    "generation_date",
    "licno",
    "type_code",
    "type_name",
    "district_code",
    "district_name",
    "shop_name",
    "address",
    "info_codes",
    "exp_date",
]

DENSITY_COLUMNS = ["generation_date", "district_name", "type_name", "count"]

DIFF_COLUMNS = ["generation_date", "prior_generation_date", "opened", "closed", "net_change"]


def fetch_fehd_licensed_premises() -> pd.DataFrame:
    response = requests.get(FEHD_RESTAURANTS_XML_URL, headers=DEFAULT_HEADERS, timeout=30)
    response.raise_for_status()
    raw_path = save_raw_snapshot(
        "fehd_licensed_premises",
        response.content,
        file_ext="xml",
        source_url=FEHD_RESTAURANTS_XML_URL,
    )

    root = ET.fromstring(response.content)
    generation_date = (root.findtext("GENERATION_DATE") or "").strip() or date.today().isoformat()

    type_labels = {code.get("ID"): code.text for code in root.find("TYPE_CODE") or []}
    district_labels = {code.get("ID"): code.text for code in root.find("DIST_CODE") or []}

    records = []
    lps = root.find("LPS")
    for lp in lps or []:
        type_code = lp.findtext("TYPE")
        district_code = lp.findtext("DIST")
        licno = lp.findtext("LICNO")
        if not licno:
            continue
        records.append(
            {
                "generation_date": generation_date,
                "licno": licno,
                "type_code": type_code,
                "type_name": type_labels.get(type_code, type_code),
                "district_code": district_code,
                "district_name": district_labels.get(district_code, district_code),
                "shop_name": lp.findtext("SS"),
                "address": lp.findtext("ADR"),
                "info_codes": lp.findtext("INFO"),
                "exp_date": lp.findtext("EXPDATE"),
            }
        )

    df = pd.DataFrame(records, columns=SNAPSHOT_COLUMNS)
    df.attrs.update(raw_snapshot=str(raw_path), source_url=FEHD_RESTAURANTS_XML_URL)
    return df


def compute_density_by_district(snapshot: pd.DataFrame) -> pd.DataFrame:
    """Current-state census: licensed premises count by district and type.

    Usable immediately from a single snapshot -- unlike the opening/closing
    diff below, this needs no history.
    """
    if snapshot.empty:
        return pd.DataFrame(columns=DENSITY_COLUMNS)
    grouped = (
        snapshot.groupby(["generation_date", "district_name", "type_name"], as_index=False)
        .size()
        .rename(columns={"size": "count"})
    )
    return grouped[DENSITY_COLUMNS].sort_values(["district_name", "type_name"]).reset_index(drop=True)


def diff_against_previous_snapshot(current: pd.DataFrame, previous: pd.DataFrame | None) -> pd.DataFrame:
    """Net opened/closed licences vs. the most recent prior stored snapshot.

    Returns an empty frame (not a fabricated zero row) when there is no
    prior snapshot to compare against yet -- an honest "not enough history"
    result, not a placeholder value.
    """
    if current.empty or previous is None or previous.empty:
        return pd.DataFrame(columns=DIFF_COLUMNS)

    current_licnos = set(current["licno"])
    previous_licnos = set(previous["licno"])
    opened = len(current_licnos - previous_licnos)
    closed = len(previous_licnos - current_licnos)

    return pd.DataFrame(
        [
            {
                "generation_date": current["generation_date"].iloc[0],
                "prior_generation_date": previous["generation_date"].iloc[0],
                "opened": opened,
                "closed": closed,
                "net_change": opened - closed,
            }
        ],
        columns=DIFF_COLUMNS,
    )
