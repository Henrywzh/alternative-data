#!/usr/bin/env python3
"""Backfill Consumer Council Online Price Watch with an auditable coverage manifest.

The data.gov.hk archive publishes versions only for days on which it captured
the CSV; those archive dates, rather than every calendar day, are the coverage
contract.  A run exits non-zero when any advertised archive date cannot be
downloaded or parsed, and writes ``backfill_manifest.json`` for the dashboard
to verify before it calls the archive Healthy.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import sys
import tempfile
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("backfill_pricewatch")

BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw" / "hk_local_consumer" / "consumer_council_pricewatch_daily"
NORMALIZED_DIR = BASE_DIR / "data" / "normalized" / "hk_local_consumer" / "consumer_council_price_watch_daily"
MANIFEST_PATH = NORMALIZED_DIR / "backfill_manifest.json"

TARGET_CSV_URL = "https://online-price-watch.consumer.org.hk/opw/opendata/pricewatch_en.csv"
ENCODED_TARGET = urllib.parse.quote(TARGET_CSV_URL, safe="")
GET_FILE_BASE_URL = "https://api.data.gov.hk/v1/historical-archive/get-file"
LIST_FILE_VERSIONS_URL = "https://api.data.gov.hk/v1/historical-archive/list-file-versions"

STANDARDIZED_COLUMNS = [
    "date", "category_1", "category_2", "category_3", "product_code",
    "brand", "product_name", "supermarket_code", "price", "offers",
]
PRICEWATCH_ARROW_SCHEMA = pa.schema(
    [
        pa.field("date", pa.string()),
        pa.field("category_1", pa.string()),
        pa.field("category_2", pa.string()),
        pa.field("category_3", pa.string()),
        pa.field("product_code", pa.string()),
        pa.field("brand", pa.string()),
        pa.field("product_name", pa.string()),
        pa.field("supermarket_code", pa.string()),
        pa.field("price", pa.float64()),
        pa.field("offers", pa.string()),
    ]
)
SUPERMARKETS_2020 = [
    ("Price (Wellcome)", "Offers (Wellcome)", "WELLCOME"),
    ("Price (PARKnSHOP)", "Offers (PARKnSHOP)", "PARKNSHOP"),
    ("Price (Market Place by Jasons)", "Offers (Market Place by Jasons)", "MARKET PLACE"),
    ("Price (Watsons)", "Offers (Watsons)", "WATSONS"),
    ("Price (AEON)", "Offers (AEON)", "AEON"),
    ("Price (DCH Food Mart)", "Offers (DCH Food Mart)", "DCH FOOD MART"),
]


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def _versions_url(today_ymd: str) -> str:
    return f"{LIST_FILE_VERSIONS_URL}?url={ENCODED_TARGET}&start=20200501&end={today_ymd}"


def get_daily_timestamps(*, now: datetime | None = None) -> dict[str, str]:
    """Fetch archive versions and deterministically select the latest per date."""
    now = now or datetime.now(timezone.utc)
    today_ymd = now.strftime("%Y%m%d")
    response = requests.get(_versions_url(today_ymd), headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    response.raise_for_status()
    timestamps = response.json().get("timestamps", [])
    daily_map: dict[str, str] = {}
    for timestamp in timestamps:
        timestamp = str(timestamp)
        if len(timestamp) < 8 or not timestamp[:8].isdigit():
            logger.warning("Ignoring malformed archive timestamp: %r", timestamp)
            continue
        date_str = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}"
        daily_map[date_str] = max(timestamp, daily_map.get(date_str, timestamp))
    if not daily_map:
        raise RuntimeError("data.gov.hk returned no usable Price Watch archive versions")
    logger.info("Archive reports %s unique dates (%s to %s).", len(daily_map), min(daily_map), max(daily_map))
    return dict(sorted(daily_map.items()))


def download_single_date(
    date_str: str, timestamp: str, *, raw_dir: Path = RAW_DIR, max_attempts: int = 3
) -> tuple[str, bool, str]:
    """Download one date atomically, retrying transient transport/server errors."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"pricewatch_{date_str}.csv"
    if raw_path.exists() and raw_path.stat().st_size > 100:
        return date_str, True, "cached"

    file_url = f"{GET_FILE_BASE_URL}?url={ENCODED_TARGET}&time={timestamp}"
    last_error = "no response"
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(file_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            if response.status_code == 200 and len(response.content) > 100:
                temporary = raw_path.with_suffix(".csv.part")
                temporary.write_bytes(response.content)
                os.replace(temporary, raw_path)
                return date_str, True, "downloaded"
            last_error = f"HTTP {response.status_code} ({len(response.content)} bytes)"
            if response.status_code < 500:
                break
        except requests.RequestException as exc:
            last_error = str(exc)
        if attempt < max_attempts:
            time.sleep(0.5 * attempt)
    return date_str, False, last_error


def parse_raw_csv(raw_path: Path, date_str: str) -> pd.DataFrame:
    """Normalize one wide (2020) or long (2021+) archive CSV with a schema contract."""
    df = pd.read_csv(raw_path)
    if "Price (Wellcome)" in df.columns or "Price (PARKnSHOP)" in df.columns:
        frames = []
        required = {"Product Code", "Product Name"}
        missing = sorted(required - set(df.columns))
        if missing:
            raise ValueError(f"wide Price Watch CSV missing required columns: {', '.join(missing)}")
        for price_column, offer_column, supermarket_code in SUPERMARKETS_2020:
            if price_column not in df.columns:
                continue
            subset = pd.DataFrame(
                {
                    "date": date_str,
                    "category_1": df.get("Category 1"),
                    "category_2": df.get("Category 2"),
                    "category_3": df.get("Category 3"),
                    "product_code": df.get("Product Code"),
                    "brand": df.get("Brand"),
                    "product_name": df.get("Product Name"),
                    "supermarket_code": supermarket_code,
                    "price": pd.to_numeric(df[price_column], errors="coerce"),
                    "offers": df[offer_column] if offer_column in df.columns else None,
                }
            )
            frames.append(subset)
        normalized = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=STANDARDIZED_COLUMNS)
    else:
        rename_map = {
            "Category 1": "category_1", "Category 2": "category_2", "Category 3": "category_3",
            "Product Code": "product_code", "Brand": "brand", "Product Name": "product_name",
            "Supermarket Code": "supermarket_code", "Price": "price", "Offers": "offers",
        }
        required = {"Product Code", "Product Name", "Supermarket Code", "Price"}
        missing = sorted(required - set(df.columns))
        if missing:
            raise ValueError(f"long Price Watch CSV missing required columns: {', '.join(missing)}")
        normalized = df.rename(columns=rename_map)
        normalized["date"] = date_str
        normalized["price"] = pd.to_numeric(normalized["price"], errors="coerce")

    for column in STANDARDIZED_COLUMNS:
        if column not in normalized.columns:
            normalized[column] = None
    normalized = normalized.loc[:, STANDARDIZED_COLUMNS].copy()
    normalized["price"] = pd.to_numeric(normalized["price"], errors="coerce")
    normalized = normalized.dropna(subset=["product_code", "product_name", "supermarket_code", "price"])
    normalized = normalized[normalized["price"] > 0]
    if normalized.empty:
        raise ValueError("Price Watch CSV yielded no positive-priced product/store rows")
    for column in STANDARDIZED_COLUMNS:
        if column != "price":
            normalized[column] = normalized[column].astype("string")
    normalized["price"] = normalized["price"].astype(float)
    return normalized.reset_index(drop=True)


def _build_manifest(
    daily_map: dict[str, str],
    download_status: dict[str, str],
    parsed_dates: set[str],
    parse_failures: dict[str, str],
    partitions: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_dates = sorted(daily_map)
    downloaded_dates = sorted(download_status)
    complete = (
        set(expected_dates) == set(downloaded_dates) == parsed_dates
        and not parse_failures
        and all(status in {"cached", "downloaded"} for status in download_status.values())
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete" if complete else "incomplete",
        "source": {
            "dataset_url": TARGET_CSV_URL,
            "versions_endpoint": LIST_FILE_VERSIONS_URL,
            "archive_start": "2020-05-01",
        },
        "expected_dates": expected_dates,
        "source_versions": daily_map,
        "download_status": download_status,
        "parse_failures": parse_failures,
        "parsed_dates": sorted(parsed_dates),
        "partitions": partitions,
    }


def run_backfill(*, workers: int = 16) -> dict[str, Any]:
    """Download, parse and materialise every advertised archive date or fail loudly."""
    daily_map = get_daily_timestamps()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)

    download_status: dict[str, str] = {}
    download_failures: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(download_single_date, date_str, timestamp): date_str
            for date_str, timestamp in daily_map.items()
        }
        for future in as_completed(futures):
            date_str, succeeded, status = future.result()
            if succeeded:
                download_status[date_str] = status
            else:
                download_failures[date_str] = status

    parsed_dates: set[str] = set()
    parse_failures: dict[str, str] = dict(download_failures)
    partitions: list[dict[str, Any]] = []
    months: dict[str, list[str]] = {}
    for date_str in daily_map:
        months.setdefault(date_str[:7], []).append(date_str)

    for year_month, date_list in sorted(months.items()):
        parsed_for_month: list[str] = []
        records_for_month = 0
        partition_dir = NORMALIZED_DIR / year_month
        partition_dir.mkdir(parents=True, exist_ok=True)
        partition_path = partition_dir / f"pricewatch_{year_month}.parquet"
        temporary_path = partition_path.with_suffix(".parquet.part")
        writer: pq.ParquetWriter | None = None
        for date_str in date_list:
            if date_str not in download_status:
                continue
            try:
                frame = parse_raw_csv(RAW_DIR / f"pricewatch_{date_str}.csv", date_str)
            except Exception as exc:
                parse_failures[date_str] = str(exc)
                continue
            table = pa.Table.from_pandas(frame, schema=PRICEWATCH_ARROW_SCHEMA, preserve_index=False)
            if writer is None:
                writer = pq.ParquetWriter(temporary_path, PRICEWATCH_ARROW_SCHEMA)
            writer.write_table(table)
            parsed_dates.add(date_str)
            parsed_for_month.append(date_str)
            records_for_month += len(frame)
        if writer is None:
            continue
        writer.close()
        os.replace(temporary_path, partition_path)
        partitions.append(
            {
                "year_month": year_month,
                "path": str(partition_path.relative_to(NORMALIZED_DIR)),
                "sha256": _sha256_path(partition_path),
                "records": records_for_month,
                "expected_dates": sorted(date_list),
                "parsed_dates": parsed_for_month,
            }
        )

    manifest = _build_manifest(daily_map, download_status, parsed_dates, parse_failures, partitions)
    _atomic_json(MANIFEST_PATH, manifest)
    if manifest["status"] != "complete":
        missing_downloads = sorted(set(daily_map) - set(download_status))
        missing_parses = sorted(set(daily_map) - parsed_dates)
        raise RuntimeError(
            f"Price Watch backfill incomplete; manifest={MANIFEST_PATH}; "
            f"downloads missing={len(missing_downloads)}, parses missing={len(missing_parses)}"
        )
    logger.info("Price Watch backfill complete: %s dates, %s partitions.", len(parsed_dates), len(partitions))
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=16, help="Concurrent archive downloads (default: 16)")
    args = parser.parse_args()
    try:
        manifest = run_backfill(workers=args.workers)
    except Exception as exc:
        logger.error("%s", exc)
        return 1
    print(json.dumps({"ok": True, "manifest": str(MANIFEST_PATH), "dates": len(manifest["expected_dates"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
