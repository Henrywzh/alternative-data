import json
import logging
from datetime import datetime, timezone
import pandas as pd
import requests

from src.hk_local_consumer.config import (
    DATA_SOURCE_FALLBACK,
    DATA_SOURCE_LIVE,
    DataSourceLabel,
    RAW_DIR,
)

logger = logging.getLogger(__name__)

CONSUMER_COUNCIL_COMPLAINTS_URL = "https://www.consumer.org.hk/node/32290/export-complaints/json?lang=en"

COMPLAINTS_COLUMNS = [
    "period",
    "category",
    "amount",
    "data_source",
]


def save_raw_snapshot(name: str, payload: list[dict]) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = RAW_DIR / f"{name}_{timestamp}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return str(path)


def fetch_consumer_council_complaints() -> pd.DataFrame:
    """
    Fetches official Consumer Council complaint statistics by sector/category.
    Returns normalized DataFrame with sector complaint counts.
    """
    source_label: DataSourceLabel = DATA_SOURCE_LIVE
    records = []

    try:
        resp = requests.get(
            CONSUMER_COUNCIL_COMPLAINTS_URL,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        complaints_list = data.get("complaints", [])
        for block in complaints_list:
            yr = str(block.get("complaints_year", ""))
            mo = str(block.get("complaints_month", ""))
            period_str = f"{yr} {mo}".strip()
            cats = block.get("categories", [])
            for item in cats:
                cat_name = str(item.get("category", "")).strip()
                amt_str = str(item.get("amount", "0")).replace(",", "").strip()
                try:
                    amt = int(amt_str)
                except ValueError:
                    amt = 0
                records.append({
                    "period": period_str,
                    "category": cat_name,
                    "amount": amt,
                })

        df = pd.DataFrame(records)
        if df.empty:
            raise ValueError("No complaint categories extracted")

    except Exception as exc:
        logger.warning(f"Failed to fetch Consumer Council Complaints data: {exc}. Returning empty frame (no fabricated data).")
        source_label = DATA_SOURCE_FALLBACK
        df = pd.DataFrame(columns=[c for c in COMPLAINTS_COLUMNS if c != "data_source"])

    df["data_source"] = source_label
    result = df.reindex(columns=COMPLAINTS_COLUMNS).reset_index(drop=True)

    try:
        save_raw_snapshot("consumer_council_complaints", result.to_dict(orient="records"))
    except Exception as exc:
        logger.warning(f"Failed to save raw complaints snapshot: {exc}")

    result.attrs["data_source"] = source_label
    return result
