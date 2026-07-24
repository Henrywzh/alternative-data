import io
import logging
from datetime import datetime, timezone
import pandas as pd
import requests

from src.hk_local_consumer.config import (
    CONSUMER_COUNCIL_PRICE_WATCH_URL,
    DATA_SOURCE_FALLBACK,
    DATA_SOURCE_LIVE,
    DataSourceLabel,
    RAW_DIR,
)

logger = logging.getLogger(__name__)

PRICEWATCH_COLUMNS = [
    "date",
    "category_1",
    "category_2",
    "category_3",
    "product_code",
    "brand",
    "product_name",
    "supermarket_code",
    "price",
    "offers",
    "data_source",
]


def save_raw_snapshot(name: str, payload: list[dict]) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = RAW_DIR / f"{name}_{timestamp}.json"
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return str(path)


def fetch_consumer_council_pricewatch() -> pd.DataFrame:
    """
    Fetches the latest HK Consumer Council Online Price Watch open dataset (pricewatch_en.csv).
    Returns normalized DataFrame containing daily item prices across HK supermarkets.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_label: DataSourceLabel = DATA_SOURCE_LIVE

    try:
        resp = requests.get(
            CONSUMER_COUNCIL_PRICE_WATCH_URL,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            timeout=20,
        )
        resp.raise_for_status()
        df = pd.read_csv(io.BytesIO(resp.content))

        # Rename columns to standard snake_case
        rename_map = {
            "Category 1": "category_1",
            "Category 2": "category_2",
            "Category 3": "category_3",
            "Product Code": "product_code",
            "Brand": "brand",
            "Product Name": "product_name",
            "Supermarket Code": "supermarket_code",
            "Price": "price",
            "Offers": "offers",
        }
        df = df.rename(columns=rename_map)
        df["date"] = today_str
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
        df = df.dropna(subset=["price"])

    except Exception as exc:
        logger.warning(f"Failed to fetch Consumer Council Price Watch CSV: {exc}. Using fallback snapshot.")
        source_label = DATA_SOURCE_FALLBACK
        df = pd.DataFrame([
            {"category_1": "Bakery / Cereals / Spreads", "category_2": "Breads", "product_name": "White Bread 8 Slice", "price": 10.9},
            {"category_1": "Dairy / Eggs / Ice Cream", "category_2": "Milk", "product_name": "Fresh Milk 1L", "price": 28.5},
            {"category_1": "Personal Care", "category_2": "Shampoo", "product_name": "Moisturizing Shampoo 500ml", "price": 45.0},
        ])
        df["date"] = today_str
        df["category_3"] = ""
        df["product_code"] = ""
        df["brand"] = ""
        df["supermarket_code"] = ""
        df["offers"] = ""

    df["data_source"] = source_label
    result = df.reindex(columns=PRICEWATCH_COLUMNS).reset_index(drop=True)

    # Save raw snapshot
    try:
        save_raw_snapshot("consumer_council_pricewatch", result.to_dict(orient="records")[:500])
    except Exception as exc:
        logger.warning(f"Failed to save raw pricewatch snapshot: {exc}")

    result.attrs["data_source"] = source_label
    return result
