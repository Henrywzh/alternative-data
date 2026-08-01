"""USAspending commercial-space contract discovery feed."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

from ..config import DEFAULT_HEADERS, DEFAULT_TIMEOUT, USASPENDING_SPENDING_BY_AWARD_URL
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

SCHEMA_COLUMNS = [
    "award_id",
    "recipient_name",
    "award_amount",
    "awarding_agency",
    "description",
    "start_date",
    "end_date",
    "keyword",
    "fetched_at",
]

DEFAULT_KEYWORDS = [
    "commercial space",
    "commercial satellite",
    "launch services",
]

SPACE_SIGNAL_TERMS = (
    "launch",
    "satellite",
    "spacecraft",
    "spaceport",
    "orbit",
    "rocket",
    "space flight",
    "spaceflight",
    "space technology",
    "space internet",
    "cislunar",
)

IRRELEVANT_TERMS = (
    "manufactured housing",
    "commercial space rental",
)


def fetch_commercial_space_contracts(
    *,
    keywords: list[str] | None = None,
    lookback_days: int = 365 * 3,
    limit_per_keyword: int = 50,
) -> pd.DataFrame:
    """Fetch recent federal awards whose descriptions mention space commerce."""
    fetched_at = datetime.now(timezone.utc)
    start_date = (fetched_at - timedelta(days=lookback_days)).date().isoformat()
    end_date = fetched_at.date().isoformat()
    rows = []
    for keyword in keywords or DEFAULT_KEYWORDS:
        payload = {
            "filters": {
                "keywords": [keyword],
                "time_period": [{"start_date": start_date, "end_date": end_date}],
                "award_type_codes": ["A", "B", "C", "D"],
            },
            "fields": [
                "Award ID",
                "Recipient Name",
                "Award Amount",
                "Awarding Agency",
                "Description",
                "Start Date",
                "End Date",
            ],
            "limit": min(limit_per_keyword, 100),
            "page": 1,
            "subawards": False,
        }
        try:
            response = requests.post(
                USASPENDING_SPENDING_BY_AWARD_URL,
                json=payload,
                headers={**DEFAULT_HEADERS, "Content-Type": "application/json"},
                timeout=DEFAULT_TIMEOUT * 2,
            )
            response.raise_for_status()
            data = response.json()
            save_raw_snapshot(
                f"usaspending_commercial_space_{keyword.replace(' ', '_')}",
                data,
                source_url=USASPENDING_SPENDING_BY_AWARD_URL,
            )
            for item in data.get("results", []):
                description = str(item.get("Description") or "")
                description_lower = description.lower()
                if any(term in description_lower for term in IRRELEVANT_TERMS):
                    continue
                if not any(term in description_lower for term in SPACE_SIGNAL_TERMS):
                    continue
                rows.append({
                    "award_id": item.get("Award ID"),
                    "recipient_name": item.get("Recipient Name"),
                    "award_amount": item.get("Award Amount"),
                    "awarding_agency": item.get("Awarding Agency"),
                    "description": item.get("Description"),
                    "start_date": item.get("Start Date"),
                    "end_date": item.get("End Date"),
                    "keyword": keyword,
                    "fetched_at": fetched_at.isoformat(),
                })
        except Exception as exc:
            logger.warning("USAspending query failed for %s: %s", keyword, exc)
    if not rows:
        return pd.DataFrame(columns=SCHEMA_COLUMNS)
    frame = pd.DataFrame(rows, columns=SCHEMA_COLUMNS)
    return frame.drop_duplicates(["award_id", "keyword"]).reset_index(drop=True)
