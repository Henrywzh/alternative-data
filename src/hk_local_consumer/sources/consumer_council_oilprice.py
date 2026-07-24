import json
import logging
import re
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

CONSUMER_COUNCIL_OILPRICE_URL = "https://oil-price.consumer.org.hk/en"

OILPRICE_COLUMNS = [
    "date",
    "company",
    "fuel_type",
    "discounted_price_hkd",
    "walkin_discount_hkd",
    "data_source",
]


def save_raw_snapshot(name: str, payload: list[dict]) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = RAW_DIR / f"{name}_{timestamp}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return str(path)


def fetch_consumer_council_oilprice() -> pd.DataFrame:
    """
    Fetches live auto-fuel pump prices and walk-in discounts across major HK oil majors
    (Caltex, PetroChina, Shell, Sinopec, Esso) from Consumer Council's Oil Price Calculator.
    """
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    source_label: DataSourceLabel = DATA_SOURCE_LIVE
    records = []

    try:
        resp = requests.get(
            CONSUMER_COUNCIL_OILPRICE_URL,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
            timeout=15,
        )
        resp.raise_for_status()

        match = re.search(r"var\s+barChartData\s*=\s*(\{.*?\}\});", resp.text, re.DOTALL)
        if not match:
            raise ValueError("Could not locate barChartData inline script in oil price HTML")

        data = json.loads(match.group(1))
        light_data = data.get("light", {})
        labels = light_data.get("labels", [])
        datasets = light_data.get("datasets", [])

        # Parse datasets into company records
        for dataset in datasets:
            lbl = dataset.get("label", "")
            fuel_stack = dataset.get("stack", "")
            data_pts = dataset.get("data", [])

            is_after_discount = "After walkin discount" in lbl
            is_discount_amount = "Walkin Reduce" in lbl

            for company_name, val in zip(labels, data_pts):
                try:
                    num_val = float(val)
                except (ValueError, TypeError):
                    continue

                key = (company_name, fuel_stack)
                existing = next((r for r in records if r["company"] == company_name and r["fuel_type"] == fuel_stack), None)
                if not existing:
                    existing = {
                        "date": today_str,
                        "company": company_name,
                        "fuel_type": fuel_stack,
                        "discounted_price_hkd": None,
                        "walkin_discount_hkd": None,
                    }
                    records.append(existing)

                if is_after_discount:
                    existing["discounted_price_hkd"] = num_val
                elif is_discount_amount:
                    existing["walkin_discount_hkd"] = num_val

        df = pd.DataFrame(records)
        if df.empty:
            raise ValueError("No records extracted from barChartData")

    except Exception as exc:
        logger.warning(f"Failed to fetch Consumer Council Oil Price data: {exc}. Using fallback snapshot.")
        source_label = DATA_SOURCE_FALLBACK
        df = pd.DataFrame([
            {"date": today_str, "company": "Caltex", "fuel_type": "Standard Petrol", "discounted_price_hkd": 22.14, "walkin_discount_hkd": 10.2},
            {"date": today_str, "company": "PetroChina", "fuel_type": "Standard Petrol", "discounted_price_hkd": 25.34, "walkin_discount_hkd": 7.0},
            {"date": today_str, "company": "Shell", "fuel_type": "Standard Petrol", "discounted_price_hkd": 25.67, "walkin_discount_hkd": 7.0},
            {"date": today_str, "company": "Sinopec", "fuel_type": "Standard Petrol", "discounted_price_hkd": 26.04, "walkin_discount_hkd": 6.2},
            {"date": today_str, "company": "Esso", "fuel_type": "Standard Petrol", "discounted_price_hkd": 31.07, "walkin_discount_hkd": 1.6},
        ])

    df["data_source"] = source_label
    result = df.reindex(columns=OILPRICE_COLUMNS).reset_index(drop=True)

    try:
        save_raw_snapshot("consumer_council_oilprice", result.to_dict(orient="records"))
    except Exception as exc:
        logger.warning(f"Failed to save raw oilprice snapshot: {exc}")

    result.attrs["data_source"] = source_label
    return result
