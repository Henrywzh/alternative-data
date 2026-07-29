import io
import json
import logging
import os
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_pricewatch")

BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw" / "hk_local_consumer" / "consumer_council_pricewatch_daily"
NORMALIZED_DIR = BASE_DIR / "data" / "normalized" / "hk_local_consumer" / "consumer_council_price_watch_daily"

RAW_DIR.mkdir(parents=True, exist_ok=True)
NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)

TARGET_CSV_URL = "https://online-price-watch.consumer.org.hk/opw/opendata/pricewatch_en.csv"
ENCODED_TARGET = urllib.parse.quote(TARGET_CSV_URL, safe="")
GET_FILE_BASE_URL = "https://api.data.gov.hk/v1/historical-archive/get-file"

STANDARDIZED_COLUMNS = [
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
]

SUPERMARKETS_2020 = [
    ("Price (Wellcome)", "Offers (Wellcome)", "WELLCOME"),
    ("Price (PARKnSHOP)", "Offers (PARKnSHOP)", "PARKNSHOP"),
    ("Price (Market Place by Jasons)", "Offers (Market Place by Jasons)", "MARKET PLACE"),
    ("Price (Watsons)", "Offers (Watsons)", "WATSONS"),
    ("Price (AEON)", "Offers (AEON)", "AEON"),
    ("Price (DCH Food Mart)", "Offers (DCH Food Mart)", "DCH FOOD MART"),
]


def get_daily_timestamps() -> dict[str, str]:
    """Fetch all available historical timestamps and pick 1 timestamp per date YYYY-MM-DD."""
    today_ymd = datetime.now(timezone.utc).strftime("%Y%m%d")
    list_versions_url = (
        f"https://api.data.gov.hk/v1/historical-archive/list-file-versions?url={ENCODED_TARGET}&start=20200501&end={today_ymd}"
    )
    logger.info("Fetching historical file version list from data.gov.hk...")
    resp = requests.get(list_versions_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    resp.raise_for_status()
    payload = resp.json()
    timestamps = payload.get("timestamps", [])
    logger.info(f"Total historical versions reported: {len(timestamps)}")

    daily_map = {}
    for ts in timestamps:
        date_str = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        # Store latest timestamp for each day
        daily_map[date_str] = ts
    logger.info(f"Deduplicated to {len(daily_map)} unique daily dates (from {min(daily_map.keys())} to {max(daily_map.keys())}).")
    return daily_map


def download_single_date(date_str: str, timestamp: str) -> tuple[str, bool, str]:
    """Download single daily CSV file if not already existing locally."""
    raw_path = RAW_DIR / f"pricewatch_{date_str}.csv"
    if raw_path.exists() and raw_path.stat().st_size > 100:
        return date_str, True, "cached"

    file_url = f"{GET_FILE_BASE_URL}?url={ENCODED_TARGET}&time={timestamp}"
    try:
        r = requests.get(file_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        if r.status_code == 200 and len(r.content) > 100:
            with open(raw_path, "wb") as f:
                f.write(r.content)
            return date_str, True, "downloaded"
        else:
            return date_str, False, f"HTTP {r.status_code}"
    except Exception as exc:
        return date_str, False, str(exc)


def parse_raw_csv(raw_path: Path, date_str: str) -> pd.DataFrame:
    """Parse wide (2020) or long (2021-2026) CSV into standard 10-column DataFrame."""
    df = pd.read_csv(raw_path)

    # Check if 2020 wide-table format
    if "Price (Wellcome)" in df.columns or "Price (PARKnSHOP)" in df.columns:
        frames = []
        for p_col, o_col, s_code in SUPERMARKETS_2020:
            if p_col in df.columns:
                sub = pd.DataFrame(
                    {
                        "date": date_str,
                        "category_1": df.get("Category 1"),
                        "category_2": df.get("Category 2"),
                        "category_3": df.get("Category 3"),
                        "product_code": df.get("Product Code"),
                        "brand": df.get("Brand"),
                        "product_name": df.get("Product Name"),
                        "supermarket_code": s_code,
                        "price": pd.to_numeric(df[p_col], errors="coerce"),
                        "offers": df[o_col] if o_col in df.columns else None,
                    }
                )
                sub = sub.dropna(subset=["price"])
                frames.append(sub)
        df_norm = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=STANDARDIZED_COLUMNS)

    else:
        # 2021-2026 Standard Long Format
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
        df_norm = df.rename(columns=rename_map)

        df_norm["date"] = date_str
        df_norm["price"] = pd.to_numeric(df_norm["price"], errors="coerce")
        df_norm = df_norm.dropna(subset=["price"])

    # Reindex to standard columns
    for col in STANDARDIZED_COLUMNS:
        if col not in df_norm.columns:
            df_norm[col] = None

    return df_norm[STANDARDIZED_COLUMNS]


def main():
    logger.info("=== Starting HK Consumer Council Price Watch Full Historical Backfill (2020.05 - Present) ===")

    daily_map = get_daily_timestamps()
    total_days = len(daily_map)

    # 1. Download raw CSVs concurrently
    logger.info(f"Downloading {total_days} daily CSV files with 16 parallel threads...")
    success_count = 0
    cached_count = 0
    failed_count = 0

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(download_single_date, date_str, ts): date_str for date_str, ts in daily_map.items()}
        for idx, future in enumerate(as_completed(futures), 1):
            date_str, success, status = future.result()
            if success:
                if status == "cached":
                    cached_count += 1
                else:
                    success_count += 1
            else:
                failed_count += 1
                logger.warning(f"Failed [{date_str}]: {status}")

            if idx % 200 == 0 or idx == total_days:
                logger.info(
                    f"Progress: {idx}/{total_days} dates processed (Downloaded: {success_count}, Cached: {cached_count}, Failed: {failed_count})"
                )

    # 2. Process and Normalize into Monthly Parquet Files
    logger.info("Normalizing and partitioning into monthly Parquet files...")
    all_dates = sorted(daily_map.keys())

    # Group dates by YYYY-MM
    months = {}
    for d in all_dates:
        ym = d[:7]
        months.setdefault(ym, []).append(d)

    total_records = 0
    for ym, date_list in sorted(months.items()):
        month_frames = []
        for d in date_list:
            raw_path = RAW_DIR / f"pricewatch_{d}.csv"
            if raw_path.exists() and raw_path.stat().st_size > 100:
                try:
                    df_day = parse_raw_csv(raw_path, d)
                    if not df_day.empty:
                        month_frames.append(df_day)
                except Exception as exc:
                    logger.warning(f"Failed parsing {raw_path}: {exc}")

        if month_frames:
            df_month = pd.concat(month_frames, ignore_index=True)
            month_parquet_dir = NORMALIZED_DIR / ym
            month_parquet_dir.mkdir(parents=True, exist_ok=True)
            parquet_path = month_parquet_dir / f"pricewatch_{ym}.parquet"
            df_month.to_parquet(parquet_path, index=False)
            total_records += len(df_month)
            logger.info(f"Saved {ym}: {len(df_month):,} records -> {parquet_path.name}")

    logger.info(f"=== Backfill Complete! Total normalized records across {len(months)} months: {total_records:,} ===")


if __name__ == "__main__":
    main()
