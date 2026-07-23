"""OFCA Numbering Plan -- mobile number block allocations by operator.

This is a coarse, all-five-operator structural proxy, NOT a subscriber-count
or market-share series. It sums the size of 8-digit "Mobile Service" number
blocks (NUM_START-NUM_END ranges) allocated/assigned to each operator in
OFCA's public numbering-plan register.

**Explicit caveat, load-bearing for how this is presented downstream**:
number blocks are issued in anticipation of growth/porting capacity, not
1:1 with active SIMs -- there is no visibility into what fraction of an
allocated block is actually in use. Blocks are only reassigned when an
operator applies for more, which is an irregular, event-driven cadence, not
a smooth time series. A single fetch of this file is a capacity/footprint
snapshot, not a trend -- it must be presented as a supporting/context table,
never charted as if it were a subscriber KPI trend line.

Endpoint: https://www.ofca.gov.hk/filemanager/ofca/common/datagovhk/tel_no_en_tc.csv
(discovered via the CKAN package_show API for OFCA dataset id
hk-ofca-ofca-ofca-dataset-17; verified 200 OK, plain CSV, ~1,343 rows).
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

NUMBERING_PLAN_CSV_URL = "https://www.ofca.gov.hk/filemanager/ofca/common/datagovhk/tel_no_en_tc.csv"

SCHEMA_COLUMNS = [
    "allocatee",
    "num_blocks",
    "total_numbers_allocated",
]

# The raw allocatee field is bilingual (English name + Chinese name). We
# extract just the English portion and fold known operator name variants
# into the 5 licensed-operator groupings (4 MNOs + an MVNO/other bucket),
# matching the ledger's verified real-world subscriber-share ordering
# (HKT > CMHK > Hutchison/3 > SmarTone).
_OPERATOR_MATCH = {
    "Hong Kong Telecommunications (HKT) Limited": "HKT",
    "China Mobile Hong Kong Company Limited": "China Mobile Hong Kong (CMHK)",
    "Hutchison Telephone Company Limited": "Hutchison Telephone (3 HK)",
    "SmarTone Mobile Communications Limited": "SmarTone",
}


def _classify_allocatee(raw: str) -> str | None:
    if not isinstance(raw, str):
        return None
    if raw.startswith("**"):
        return None  # spare / reserved / open-for-application blocks, not an operator
    for prefix, label in _OPERATOR_MATCH.items():
        if raw.startswith(prefix):
            return label
    # Any other named allocatee is a genuine MVNO/other licensee.
    english_part = raw.split(" ")[0] if raw else raw
    return "Other MVNO / licensee"


def _block_size(row: pd.Series) -> int:
    """Number of 8-digit numbers covered by a NUM_START-NUM_END range."""
    start, end = str(row["NUM_START"]), str(row["NUM_END"])
    try:
        return int(end.rstrip("-")) - int(start.rstrip("-")) + 1
    except ValueError:
        return 0


def fetch_numbering_plan() -> pd.DataFrame:
    """Fetch OFCA's numbering plan CSV and summarize Mobile Service number
    block allocations per operator. This is a single-snapshot structural
    proxy (see module docstring caveat), not a time series."""
    resp = requests.get(NUMBERING_PLAN_CSV_URL, headers=DEFAULT_HEADERS, timeout=30)
    resp.raise_for_status()

    raw = pd.read_csv(io.BytesIO(resp.content), encoding="utf-8-sig")
    mobile = raw[raw["NUM_CATEGORY"].str.contains("Mobile Service", na=False)].copy()

    mobile["operator"] = mobile["NUM_ALLOCATEE_OR_ASSIGNEE"].apply(_classify_allocatee)
    mobile = mobile.dropna(subset=["operator"])
    mobile["block_size"] = mobile.apply(_block_size, axis=1)

    summary = (
        mobile.groupby("operator")
        .agg(num_blocks=("block_size", "size"), total_numbers_allocated=("block_size", "sum"))
        .reset_index()
        .rename(columns={"operator": "allocatee"})
        .sort_values("total_numbers_allocated", ascending=False)
        .reset_index(drop=True)
    )

    raw_path = save_raw_snapshot(
        "numbering_plan",
        summary.to_dict(orient="records"),
        file_ext="json",
        source_url=NUMBERING_PLAN_CSV_URL,
    )
    summary.attrs["raw_snapshot"] = str(raw_path)
    summary.attrs["source_url"] = NUMBERING_PLAN_CSV_URL
    summary.attrs["caveat"] = (
        "Number blocks are issued mobile-number capacity, not active subscriber "
        "counts. Updates are irregular/event-driven -- this is a single "
        "structural snapshot, not a time series."
    )
    return summary[SCHEMA_COLUMNS]
