"""FAA commercial space KPI page parser."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, FAA_COMMERCIAL_SPACE_NUMBERS_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = ["metric", "value", "observed_date", "source_url", "fetched_at"]

METRICS = (
    "Licensed Launches",
    "Licensed Reentries",
    "Spaceport Operator Licenses",
    "Permitted (Experimental) Launches",
    "Active Safety Approvals",
    "Active Launch Licenses",
)


def fetch_faa_commercial_space_kpis() -> pd.DataFrame:
    """Fetch the official FAA commercial-space headline metrics.

    The linked Tableau workbook is interactive and not a stable CSV endpoint;
    this parser intentionally uses the official HTML KPI page instead.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        response = requests.get(
            FAA_COMMERCIAL_SPACE_NUMBERS_URL,
            headers=DEFAULT_HEADERS,
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
        html = response.text
        save_raw_snapshot("faa_commercial_space_numbers", {"html": html}, source_url=response.url)
        rows = []
        for metric in METRICS:
            match = re.search(
                rf'<div class="field--name-field-value[^>]*>\s*(?:<a[^>]*>)?\s*([\d,]+)\s*(?:</a>)?\s*</div>\s*'
                rf'<div class="field--name-field-label[^>]*>\s*{re.escape(metric)}\s*</div>',
                html,
                flags=re.IGNORECASE | re.DOTALL,
            )
            if match:
                rows.append({
                    "metric": metric,
                    "value": int(match.group(1).replace(",", "")),
                    "observed_date": fetched_at[:10],
                    "source_url": response.url,
                    "fetched_at": fetched_at,
                })
        return pd.DataFrame(rows, columns=SCHEMA_COLUMNS)
    except Exception as exc:
        logger.warning("Failed to fetch FAA commercial-space KPIs: %s", exc)
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
