import io
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import requests

from hk_local_consumer.config import (
    CONSUMER_COUNCIL_PRICE_WATCH_URL,
    DATA_SOURCE_FALLBACK,
    DATA_SOURCE_LIVE,
    DataSourceLabel,
    RAW_DIR,
)

logger = logging.getLogger(__name__)

PRICEWATCH_ARCHIVE_MANIFEST = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "normalized"
    / "hk_local_consumer"
    / "consumer_council_price_watch_daily"
    / "backfill_manifest.json"
)

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
    base_dir = Path(__file__).resolve().parents[3]
    norm_dir = base_dir / "data" / "normalized" / "hk_local_consumer" / "consumer_council_price_watch_daily"

    if not norm_dir.exists():
        return pd.DataFrame(columns=["year_month", "category_1", "supermarket_code", "avg_price", "item_count"])

    files = sorted(norm_dir.glob("**/pricewatch_*.parquet"))
    if not files:
        return pd.DataFrame(columns=["year_month", "category_1", "supermarket_code", "avg_price", "item_count"])

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
    summary.attrs["archive_validation"] = _load_pricewatch_archive_validation(norm_dir, files)
    return summary


def load_historical_pricewatch_matched_index(min_matched_products: int = 20) -> pd.DataFrame:
    """Build a monthly, chain-linked matched-item index for each supermarket.

    Every monthly link uses only product codes that appear with a positive
    price in both adjacent months for the same supermarket. The link is the
    equal-weight geometric mean of those price relatives. This avoids the
    invalid shortcut of comparing the arithmetic mean of a changing product
    assortment. It still does not adjust for pack-size changes or classify
    promotions, so it is a monitoring indicator rather than an official CPI.
    """
    base_dir = Path(__file__).resolve().parents[3]
    norm_dir = base_dir / "data" / "normalized" / "hk_local_consumer" / "consumer_council_price_watch_daily"
    files = sorted(norm_dir.glob("**/pricewatch_*.parquet")) if norm_dir.exists() else []
    validation = _load_pricewatch_archive_validation(norm_dir, files)
    empty = pd.DataFrame(
        columns=["year_month", "supermarket_code", "matched_item_index", "matched_products", "current_products", "match_rate"]
    )
    empty.attrs["archive_validation"] = validation
    if not validation.get("complete"):
        return empty

    frames = []
    for path in files:
        try:
            frame = pd.read_parquet(path, columns=["date", "product_code", "supermarket_code", "price"])
        except Exception as exc:
            logger.warning("Failed loading Price Watch index input %s: %s", path, exc)
            return empty
        frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
        frame = frame.dropna(subset=["product_code", "supermarket_code", "price"])
        frame = frame[frame["price"] > 0]
        if not frame.empty:
            frame["year_month"] = frame["date"].astype(str).str[:7]
            frames.append(frame)
    if not frames:
        return empty

    monthly = (
        pd.concat(frames, ignore_index=True)
        .groupby(["year_month", "supermarket_code", "product_code"], as_index=False)["price"]
        .mean()
    )
    rows = []
    for supermarket_code, series in monthly.groupby("supermarket_code"):
        months = sorted(series["year_month"].unique())
        prior_prices = None
        index_value = None
        for year_month in months:
            current = series.loc[series["year_month"] == year_month, ["product_code", "price"]].set_index("product_code")["price"]
            if prior_prices is None:
                index_value = 100.0
                rows.append(
                    {
                        "year_month": year_month,
                        "supermarket_code": supermarket_code,
                        "matched_item_index": index_value,
                        "matched_products": int(len(current)),
                        "current_products": int(len(current)),
                        "match_rate": 1.0,
                    }
                )
            else:
                matched = prior_prices.to_frame("prior").join(current.rename("current"), how="inner")
                matched = matched[(matched["prior"] > 0) & (matched["current"] > 0)]
                if len(matched) >= min_matched_products and index_value is not None:
                    link = float((matched["current"] / matched["prior"]).map(math.log).mean())
                    index_value *= math.exp(link)
                    rows.append(
                        {
                            "year_month": year_month,
                            "supermarket_code": supermarket_code,
                            "matched_item_index": round(index_value, 2),
                            "matched_products": int(len(matched)),
                            "current_products": int(len(current)),
                            "match_rate": round(len(matched) / len(current), 4) if len(current) else None,
                        }
                    )
                elif len(matched) < min_matched_products:
                    # Do not resume a chain after an unlinked month: that
                    # would silently skip a price movement.
                    index_value = None
            prior_prices = current
    result = pd.DataFrame(rows, columns=empty.columns)
    result.attrs["archive_validation"] = validation
    return result


def _load_pricewatch_archive_validation(norm_dir: Path, files: list[Path]) -> dict:
    """Validate the local backfill manifest before exposing archive coverage.

    The dashboard does not require every Parquet hash to be recomputed on
    every build, but it requires a complete manifest whose declared archive
    dates, parsed dates and named partitions agree with the materialised
    files.  Anything less is deliberately reported as unavailable rather than
    as a Healthy historical archive.
    """
    manifest_path = norm_dir / "backfill_manifest.json"
    result = {"complete": False, "reason": "backfill manifest is missing"}
    if not manifest_path.exists():
        return result
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"complete": False, "reason": f"backfill manifest is unreadable: {exc}"}

    expected_dates = set(manifest.get("expected_dates", []))
    parsed_dates = set(manifest.get("parsed_dates", []))
    source_versions = manifest.get("source_versions", {})
    declared_paths = {entry.get("path") for entry in manifest.get("partitions", [])}
    actual_paths = {str(path.relative_to(norm_dir)) for path in files}
    if manifest.get("schema_version") != 1:
        return {"complete": False, "reason": "unsupported backfill manifest schema"}
    if manifest.get("status") != "complete":
        return {"complete": False, "reason": "backfill manifest is not complete"}
    if not expected_dates or expected_dates != parsed_dates:
        return {"complete": False, "reason": "expected and parsed archive dates differ"}
    if set(source_versions) != expected_dates:
        return {"complete": False, "reason": "archive version provenance is incomplete"}
    if declared_paths != actual_paths:
        return {"complete": False, "reason": "declared and materialised partitions differ"}
    return {
        "complete": True,
        "expected_dates": len(expected_dates),
        "manifest_path": str(manifest_path),
        "generated_at": manifest.get("generated_at"),
    }
