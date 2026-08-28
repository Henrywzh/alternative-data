import json
import logging
from datetime import datetime, timezone
import pandas as pd
import requests

from hk_local_consumer.config import (
    DATA_SOURCE_FALLBACK,
    DATA_SOURCE_LIVE,
    DataSourceLabel,
    RAW_DIR,
)

logger = logging.getLogger(__name__)

CNSD_API_URL = "https://www.censtatd.gov.hk/api/get.php"

CNSD_COLUMNS = [
    "table_id",
    "period",
    "freq",
    "variable",
    "unit",
    "value",
    "data_source",
]


def fetch_cnsd_table(table_id: str, lang: str = "en") -> pd.DataFrame:
    """
    Fetches any of C&SD's 572 government statistical web tables directly via official JSON API.
    Returns normalized DataFrame containing historical time series data.
    """
    source_label: DataSourceLabel = DATA_SOURCE_LIVE
    records = []

    try:
        url = f"{CNSD_API_URL}?id={table_id}&lang={lang}&full_series=1"
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()

        dataset = data.get("dataSet", [])
        for row in dataset:
            records.append({
                "table_id": table_id,
                "period": str(row.get("period", "")),
                "freq": str(row.get("freq", "")),
                "variable": str(row.get("sv", "")),
                "unit": str(row.get("svDesc", "")),
                "value": pd.to_numeric(row.get("figure"), errors="coerce"),
            })

        df = pd.DataFrame(records)
        df = df.dropna(subset=["value"])
        if df.empty:
            raise ValueError(f"C&SD table {table_id} returned no valid records")

    except Exception as exc:
        logger.warning(f"Failed to fetch C&SD table {table_id}: {exc}. Returning empty frame.")
        source_label = DATA_SOURCE_FALLBACK
        df = pd.DataFrame(columns=[c for c in CNSD_COLUMNS if c != "data_source"])

    df["data_source"] = source_label
    result = df.reindex(columns=CNSD_COLUMNS).reset_index(drop=True)

    # Save raw snapshot
    try:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = RAW_DIR / f"cnsd_{table_id}_{timestamp}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records[:1000], f, indent=2, ensure_ascii=False)
    except Exception as exc:
        logger.warning(f"Failed to save raw C&SD snapshot for {table_id}: {exc}")

    result.attrs["data_source"] = source_label
    return result
