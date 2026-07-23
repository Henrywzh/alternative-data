import io
import logging
import pandas as pd
import requests
from datetime import datetime, timezone
from typing import Optional

from ..config import AFCD_DAILY_WHOLESALE_URL, DEFAULT_HEADERS
from ..storage import save_raw_snapshot

logger = logging.getLogger(__name__)

# AFCD's export repeats every column twice (English label, then a mojibake
# Chinese-label duplicate of the same values) -- verified by inspecting a
# live fetch. Only the ASCII-named columns are used; the paired Chinese
# columns are redundant, not additional data.
_CATTY_TO_KG = 0.6047989

def parse_afcd_csv(csv_content: str) -> pd.DataFrame:
    """Parse AFCD daily wholesale prices CSV into normalized structure."""
    empty_cols = ["date", "category", "commodity_name", "price_hkd_per_kg", "unit", "remarks"]
    if not csv_content or not csv_content.strip():
        return pd.DataFrame(columns=empty_cols)

    df_raw = pd.read_csv(io.StringIO(csv_content))
    ascii_cols = [c for c in df_raw.columns if c.isascii()]
    df_raw = df_raw[ascii_cols]

    required = {"FRESH FOOD CATEGORY", "FOOD TYPE", "PRICE (THIS MORNING)", "UNIT"}
    if not required.issubset(set(df_raw.columns)):
        return pd.DataFrame(columns=empty_cols)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Rows where the category equals its own header text are embedded
    # section-boundary artifacts in AFCD's export, not real observations.
    df_raw = df_raw[df_raw["FRESH FOOD CATEGORY"] != "FRESH FOOD CATEGORY"]

    price_per_catty = pd.to_numeric(df_raw["PRICE (THIS MORNING)"], errors="coerce")
    df_raw = df_raw.assign(_price_per_catty=price_per_catty).dropna(subset=["_price_per_catty"])

    df_norm = pd.DataFrame({
        "date": today_str,
        "category": df_raw["FRESH FOOD CATEGORY"].str.strip(),
        "commodity_name": df_raw["FOOD TYPE"].str.strip(),
        "price_hkd_per_kg": (df_raw["_price_per_catty"] / _CATTY_TO_KG).round(2),
        "unit": "HKD/kg",
        "remarks": "AFCD daily wholesale average; converted from HKD/catty.",
    })

    if df_norm.empty:
        return pd.DataFrame(columns=empty_cols)
    return df_norm.reset_index(drop=True)


def fetch_afcd_food_prices(custom_url: Optional[str] = None) -> pd.DataFrame:
    """Fetch and parse AFCD wholesale fresh food prices."""
    url = custom_url or AFCD_DAILY_WHOLESALE_URL
    raw_path = None
    try:
        resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=15)
        if resp.status_code == 200:
            csv_text = resp.text
            raw_path = save_raw_snapshot("afcd_food_prices", csv_text, file_ext="csv", source_url=url)
            df = parse_afcd_csv(csv_text)
            df.attrs["raw_snapshot"] = str(raw_path)
            df.attrs["source_url"] = url
            return df
    except Exception as exc:
        logger.warning(f"Network fetch failed for AFCD prices ({exc}).")

    logger.error("AFCD wholesale food prices unavailable; returning empty dataset (no fabricated data).")
    df_empty = pd.DataFrame(columns=["date", "category", "commodity_name", "price_hkd_per_kg", "unit", "remarks"])
    df_empty.attrs["raw_snapshot"] = str(raw_path) if raw_path else None
    df_empty.attrs["source_url"] = url
    return df_empty
