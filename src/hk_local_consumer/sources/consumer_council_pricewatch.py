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
        logger.warning(f"Failed to fetch Consumer Council Price Watch CSV: {exc}. Returning empty frame.")
        source_label = DATA_SOURCE_FALLBACK
        df = pd.DataFrame(columns=[c for c in PRICEWATCH_COLUMNS if c != "data_source"])

    df["data_source"] = source_label
    result = df.reindex(columns=PRICEWATCH_COLUMNS).reset_index(drop=True)

    # Save raw snapshot
    try:
        save_raw_snapshot("consumer_council_pricewatch", result.to_dict(orient="records")[:500])
    except Exception as exc:
        logger.warning(f"Failed to save raw pricewatch snapshot: {exc}")

    result.attrs["data_source"] = source_label
    return result


def load_historical_pricewatch_summary() -> pd.DataFrame:
    """
    Loads normalized historical daily price watch dataset from Parquet partitions.
    Returns aggregated monthly category average prices across major HK supermarkets (2020-2026).
    """
    from pathlib import Path
    base_dir = Path(__file__).resolve().parents[3]
    norm_dir = base_dir / "data" / "normalized" / "hk_local_consumer" / "consumer_council_price_watch_daily"

    if not norm_dir.exists():
        return pd.DataFrame(columns=["date", "category_1", "supermarket_code", "avg_price", "item_count"])

    files = sorted(norm_dir.glob("**/pricewatch_*.parquet"))
    if not files:
        return pd.DataFrame(columns=["date", "category_1", "supermarket_code", "avg_price", "item_count"])

    frames = []
    for f in files:
        try:
            df = pd.read_parquet(f, columns=["date", "category_1", "supermarket_code", "price"])
            if not df.empty:
                df["price"] = pd.to_numeric(df["price"], errors="coerce")
                df = df.dropna(subset=["price"])
                # Aggregate to monthly level by category and supermarket to keep payload lean
                df["year_month"] = df["date"].astype(str).str[:7]
                grp = (
                    df.groupby(["year_month", "category_1", "supermarket_code"])
                    .agg(avg_price=("price", "mean"), item_count=("price", "count"))
                    .reset_index()
                )
                frames.append(grp)
        except Exception as exc:
            logger.warning(f"Failed loading parquet {f}: {exc}")

    if not frames:
        return pd.DataFrame(columns=["year_month", "category_1", "supermarket_code", "avg_price", "item_count"])

    summary = pd.concat(frames, ignore_index=True)
    summary["avg_price"] = summary["avg_price"].round(2)
    return summary

