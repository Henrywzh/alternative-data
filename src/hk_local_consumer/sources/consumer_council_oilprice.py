import io
import json
import logging
import re
from datetime import datetime, timezone
import pandas as pd
import requests

from hk_local_consumer.config import (
    DATA_SOURCE_FALLBACK,
    DATA_SOURCE_LIVE,
    DataSourceLabel,
    NORMALIZED_DIR,
    RAW_DIR,
)

logger = logging.getLogger(__name__)

CONSUMER_COUNCIL_OILPRICE_URL = "https://oil-price.consumer.org.hk/en"
CONSUMER_COUNCIL_OILPRICE_TREND_URL = "https://oil-price.consumer.org.hk/en/chart/download-csv"
OILPRICE_HISTORY_START = "2009-01-01"
_OIL_COMPANIES = [":company:11:", ":company:12:", ":company:14:", ":company:9765:", ":company:13:"]

OILPRICE_COLUMNS = [
    "date",
    "company",
    "fuel_type",
    "discounted_price_hkd",
    "walkin_discount_hkd",
    "data_source",
]

OILPRICE_HISTORY_COLUMNS = [
    "date",
    "company",
    "fuel_type",
    "net_price_ex_duty_hkd",
    "data_source",
]
OILPRICE_HISTORY_CACHE_PATH = NORMALIZED_DIR / "consumer_council_oilprice_history.csv"


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
        logger.warning(f"Failed to fetch Consumer Council Oil Price data: {exc}. Returning empty frame (no fabricated data).")
        source_label = DATA_SOURCE_FALLBACK
        df = pd.DataFrame(columns=[c for c in OILPRICE_COLUMNS if c != "data_source"])

    df["data_source"] = source_label
    result = df.reindex(columns=OILPRICE_COLUMNS).reset_index(drop=True)

    try:
        save_raw_snapshot("consumer_council_oilprice", result.to_dict(orient="records"))
    except Exception as exc:
        logger.warning(f"Failed to save raw oilprice snapshot: {exc}")

    result.attrs["data_source"] = source_label
    return result


def fetch_consumer_council_oilprice_history(
    start_date: str = OILPRICE_HISTORY_START, end_date: str | None = None
) -> pd.DataFrame:
    """Fetch the complete available daily net-price trend from Oil Price Watch.

    The trend CSV is the authoritative historical series.  Its values are
    explicitly *after walk-in discounts and excluding fuel duty*, which differs
    from the homepage calculator's duty-inclusive current-price comparison.
    """
    today_str = end_date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    records: list[pd.DataFrame] = []
    for fuel_type in ("regular-unleaded-gasoline", "premium-unleaded-gasoline"):
        params: list[tuple[str, str]] = [
            ("shortcut", "custom"),
            ("from", start_date),
            ("to", today_str),
            ("auto_fuel_type", fuel_type),
        ]
        params.extend(("company[]", company) for company in _OIL_COMPANIES)
        try:
            response = requests.get(
                CONSUMER_COUNCIL_OILPRICE_TREND_URL,
                params=params,
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
                timeout=60,
            )
            response.raise_for_status()
            raw = pd.read_csv(io.StringIO(response.content.decode("utf-8-sig")))
        except Exception as exc:
            logger.warning("Failed to fetch Consumer Council oil-price trend for %s: %s", fuel_type, exc)
            continue
        if raw.empty or "Date" not in raw.columns:
            continue
        long = raw.melt(id_vars="Date", var_name="company", value_name="net_price_ex_duty_hkd")
        long["date"] = pd.to_datetime(long["Date"], errors="coerce")
        long["net_price_ex_duty_hkd"] = pd.to_numeric(long["net_price_ex_duty_hkd"], errors="coerce")
        long["fuel_type"] = fuel_type
        long["data_source"] = DATA_SOURCE_LIVE
        records.append(long[["date", "company", "fuel_type", "net_price_ex_duty_hkd", "data_source"]])

    if not records:
        return pd.DataFrame(columns=OILPRICE_HISTORY_COLUMNS)
    result = pd.concat(records, ignore_index=True).dropna(subset=["date", "net_price_ex_duty_hkd"])
    result["date"] = result["date"].dt.strftime("%Y-%m-%d")
    result = result.drop_duplicates(["date", "company", "fuel_type"], keep="last")
    result = result.sort_values(["fuel_type", "company", "date"]).reset_index(drop=True)
    try:
        save_raw_snapshot("consumer_council_oilprice_history", result.to_dict(orient="records"))
    except Exception as exc:
        logger.warning("Failed to save oil-price history snapshot: %s", exc)
    result.attrs["data_source"] = DATA_SOURCE_LIVE
    result.attrs["definition"] = "Net price after walk-in discounts, excluding fuel duty."
    return result.reindex(columns=OILPRICE_HISTORY_COLUMNS)


def load_consumer_council_oilprice_history() -> pd.DataFrame:
    """Read the durable backfill cache without making a network request."""
    if not OILPRICE_HISTORY_CACHE_PATH.exists():
        return pd.DataFrame(columns=OILPRICE_HISTORY_COLUMNS)
    result = pd.read_csv(OILPRICE_HISTORY_CACHE_PATH)
    return result.reindex(columns=OILPRICE_HISTORY_COLUMNS)


def merge_consumer_council_oilprice_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Upsert fetched history into the durable cache and return all rows."""
    existing = load_consumer_council_oilprice_history()
    combined = pd.concat([existing, frame], ignore_index=True)
    combined = combined.dropna(subset=["date", "company", "fuel_type", "net_price_ex_duty_hkd"])
    combined = combined.drop_duplicates(["date", "company", "fuel_type"], keep="last")
    combined = combined.sort_values(["fuel_type", "company", "date"]).reset_index(drop=True)
    combined.to_csv(OILPRICE_HISTORY_CACHE_PATH, index=False)
    return combined
