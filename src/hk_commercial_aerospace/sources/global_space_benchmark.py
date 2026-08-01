"""Global space activity benchmark from UNOOSA data via Our World in Data."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, OWID_OBJECTS_LAUNCHED_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = ["entity", "code", "year", "year_label", "objects_launched", "fetched_at"]


def fetch_global_objects_launched() -> pd.DataFrame:
    """Fetch annual objects launched, retaining World/China/US benchmark rows."""
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        response = requests.get(
            OWID_OBJECTS_LAUNCHED_URL,
            headers={**DEFAULT_HEADERS, "User-Agent": "Our World in Data data fetch/1.0"},
            timeout=DEFAULT_TIMEOUT * 2,
        )
        response.raise_for_status()
        save_raw_snapshot("owid_global_objects_launched", {"csv": response.text}, source_url=OWID_OBJECTS_LAUNCHED_URL)
        frame = pd.read_csv(pd.io.common.StringIO(response.text))
        value_column = [column for column in frame.columns if column not in {"Entity", "Code", "Year"}]
        if len(value_column) != 1:
            raise ValueError(f"Unexpected OWID columns: {list(frame.columns)}")
        frame = frame.rename(columns={"Entity": "entity", "Code": "code", "Year": "year", value_column[0]: "objects_launched"})
        frame = frame[frame["entity"].isin(["World", "China", "United States"])].copy()
        frame["year"] = pd.to_numeric(frame["year"], errors="coerce").astype("Int64")
        frame["year_label"] = frame["year"].astype(str)
        frame["objects_launched"] = pd.to_numeric(frame["objects_launched"], errors="coerce")
        frame["fetched_at"] = fetched_at
        result = (
            frame[SCHEMA_COLUMNS]
            .dropna(subset=["year", "objects_launched"])
            .sort_values(["year", "entity"], kind="stable")
            .reset_index(drop=True)
        )
        # Keep `year` numeric for the data contract and use a separate textual
        # field for chart labels. This avoids the portable reader formatting a
        # nominal year such as 1957 as 1.96K without contaminating the year
        # value with an invisible character.
        return result
    except Exception as exc:
        logger.warning("Failed to fetch global space benchmark: %s", exc)
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
