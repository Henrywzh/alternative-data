#!/usr/bin/env python3
"""Build the source-backed HK Local Consumer dashboard artifact.

Mirrors build_hk_real_estate_artifact.py's shape: acquisition and artifact
construction are kept separate so the metric contract can be tested without
network access. Only datasets confirmed to return real (non-fabricated)
data are treated as live measures here -- see PLANNED_COVERAGE for the
sources whose endpoints are currently broken/guessed and therefore excluded
from the live dashboard rather than shown with placeholder values.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.hk_local_consumer.sources.afcd_food import fetch_afcd_food_prices
from src.hk_local_consumer.sources.sge_gold import fetch_sge_gold_benchmark
from src.hk_local_consumer.sources.hk_valuation import fetch_hk_consumer_valuations
from src.hk_local_consumer.sources.cnsd_retail import fetch_cnsd_retail_sales
from src.hk_local_consumer.sources.censtatd_restaurant import fetch_censtatd_restaurant_survey
from src.hk_local_consumer.sources.immigration_flow import fetch_immigration_flow
from src.hk_local_consumer.sources.weather_demand_drivers import fetch_weather_demand_drivers
from src.hk_local_consumer.sources.consumer_council_oilprice import (
    fetch_consumer_council_oilprice,
    load_consumer_council_oilprice_history,
)
from src.hk_local_consumer.sources.consumer_council_complaints import fetch_consumer_council_complaints
from src.hk_local_consumer.sources.consumer_council_pricewatch import (
    load_historical_pricewatch_matched_index,
    load_historical_pricewatch_summary,
)
from src.hk_local_consumer.config import NORMALIZED_DIR


# AFCD's wholesale-prices CSV was verified (live fetch + a scan of the
# afcd.gov.hk price page) to expose only that morning's readings -- no
# archive, no date-parameterized endpoint. There is therefore no real
# "AFCD category prices over time" series available from the upstream
# source itself. Rather than fabricate one, each pipeline run appends the
# real same-day category averages it just computed to this small
# append-only local file, so the "over time" chart genuinely accumulates
# one real row per (date, category) each time the pipeline runs -- see
# _update_afcd_category_history(). It is intentionally whitelisted in
# .gitignore (unlike the rest of data/normalized/hk_local_consumer, which
# is disposable per-run scratch output) so the history survives across CI
# runs instead of resetting on every fresh checkout.
AFCD_CATEGORY_HISTORY_PATH = NORMALIZED_DIR / "afcd_category_history.csv"


def _load_latest_normalized(dataset: str) -> pd.DataFrame:
    """Load the latest successfully materialised source run; never fetch here."""
    candidates = sorted((NORMALIZED_DIR / dataset).glob(f"*/{dataset}.parquet"), key=lambda path: path.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(f"No local normalized cache exists for {dataset}; run HK Local Consumer ingestion first.")
    return pd.read_parquet(candidates[-1])


PUBLIC_SOURCES = {
    "consumer_council_oilprice": {
        "id": "consumer_council_oilprice",
        "label": "Consumer Council Auto Fuel Calculator",
        "href": "https://oil-price.consumer.org.hk/en",
        "query": {
            "engine": "first-party HTML / inline JS",
            "url": "https://oil-price.consumer.org.hk/en",
            "language": "JSON",
            "description": "Daily auto-fuel pump prices, walk-in discounts, and net prices across Caltex, PetroChina, Shell, Sinopec, and Esso.",
        },
    },
    "consumer_council_complaints": {
        "id": "consumer_council_complaints",
        "label": "Consumer Council Complaints API",
        "href": "https://www.consumer.org.hk/",
        "query": {
            "engine": "official JSON API",
            "url": "https://www.consumer.org.hk/node/32290/export-complaints/json?lang=en",
            "language": "JSON",
            "description": "Annual consumer complaints by category across Hong Kong consumer sectors.",
        },
    },
    "consumer_council_pricewatch": {
        "id": "consumer_council_pricewatch",
        "label": "Consumer Council Online Price Watch",
        "href": "https://online-price-watch.consumer.org.hk/opw/",
        "query": {
            "engine": "official Open Data CSV & local historical archive",
            "url": "https://online-price-watch.consumer.org.hk/opw/opendata/pricewatch_en.csv",
            "language": "CSV / Parquet",
            "description": (
                "Supermarket item prices and promotion offers. The dashboard currently "
                "reports only validated local archive coverage; it does not present an "
                "assortment-sensitive arithmetic mean as a price index."
            ),
        },
    },
    "afcd_wholesale": {
        "id": "afcd_wholesale",
        "label": "AFCD Fresh Food Wholesale Prices",
        "href": "https://www.afcd.gov.hk/english/agriculture/agr_fresh/agr_fresh_pri/agr_fresh_pri.html",
        "query": {
            "engine": "official CSV",
            "url": "https://www.afcd.gov.hk/english/agriculture/agr_fresh/files/Wholesale_Prices.csv",
            "language": "CSV",
            "description": "Loads that morning's average wholesale price per commodity across Hong Kong's fresh-food wholesale markets; prices are converted from the published HKD/catty unit to HKD/kg.",
            "metric_definitions": [
                "Each commodity's price is the mean of same-day readings across the wholesale markets/sources AFCD reports for it.",
            ],
        },
    },
    "sge_gold": {
        "id": "sge_gold",
        "label": "Shanghai Gold Exchange AM/PM Benchmark",
        "href": "https://www.sge.com.cn/",
        "query": {
            "engine": "akshare",
            "url": "akshare.spot_golden_benchmark_sge",
            "language": "Python",
            "description": "Daily AM and PM gold benchmark fixings published by the Shanghai Gold Exchange, in RMB per gram.",
            "metric_definitions": [
                "Latest is the most recent published PM benchmark fixing.",
                "Day and year movements are latest divided by the prior trading day or the observation on/before one year earlier, minus one.",
            ],
        },
    },
    "hk_valuation": {
        "id": "hk_valuation",
        "label": "Baidu Gushitong HK Equity Valuation",
        "href": "https://gushitong.baidu.com/",
        "query": {
            "engine": "akshare",
            "url": "akshare.stock_hk_valuation_baidu",
            "language": "Python",
            "description": "Daily trailing PE, PB, and market cap for the 11-name HK local-consumer watchlist, fetched per ticker per indicator.",
            "metric_definitions": [
                "PE (TTM), PB, and market cap (HKD bn) are each ticker's latest published daily value.",
                "No dividend-yield indicator exists on this endpoint; yield is not reported here.",
            ],
        },
    },
    "cnsd_retail": {
        "id": "cnsd_retail",
        "label": "C&SD Retail Sales Value/Volume Index",
        "href": "https://www.censtatd.gov.hk/en/web_table.html?id=620-67002",
        "query": {
            "engine": "official CSV",
            "url": "https://www.censtatd.gov.hk/data/MDT_75_620-67002_VAL_IDX_RS_Raw_1dp_idx_n.csv",
            "language": "CSV",
            "description": "Monthly retail sales value and volume index by type of retail outlet (tables 620-67002 / 620-67003).",
            "metric_definitions": [
                "All retail outlet is the classification group's own published total across all outlet types.",
                "Month and year movements are latest divided by the prior month or the observation twelve months earlier, minus one.",
            ],
        },
    },
    "censtatd_restaurant": {
        "id": "censtatd_restaurant",
        "label": "CenStatD Quarterly Restaurant Receipts & Purchases Survey",
        "href": "https://www.censtatd.gov.hk/en/web_table.html?id=625-68003",
        "query": {
            "engine": "official CSV",
            "url": "https://www.censtatd.gov.hk/data/MDT_90_625-68003_VAL_RR_Raw_M_hkd_d.csv",
            "language": "CSV",
            "description": "Quarterly restaurant receipts and value/volume indices by restaurant type (table 625-68003); sector-wide purchases from table 625-68001.",
            "metric_definitions": [
                "Purchases are only published sector-wide, not broken out by restaurant type.",
                "Quarter and year movements are latest divided by the prior quarter or the observation four quarters earlier, minus one.",
            ],
        },
    },
    "immigration_flow": {
        "id": "immigration_flow",
        "label": "HK Immigration Department Daily Passenger Traffic",
        "href": "https://www.immd.gov.hk/opendata/eng/transport/immigration_clearance/statistics_on_daily_passenger_traffic.csv",
        "query": {
            "engine": "official CSV",
            "url": "https://www.immd.gov.hk/opendata/eng/transport/immigration_clearance/statistics_on_daily_passenger_traffic.csv",
            "language": "CSV",
            "description": "Daily passenger clearance counts across 17 control points for HK Residents, Mainland Visitors, and Other Visitors.",
            "metric_definitions": [
                "Northbound (北上) flow is daily HK resident departures through the 9 land control points only (Lo Wu, Lok Ma Chau, Lok Ma Chau Spur Line, Shenzhen Bay, Heung Yuen Wai, Man Kam To, Sha Tau Kok, HZMB, Express Rail Link West Kowloon) -- this excludes the Airport and other cruise/ferry terminals so it isolates cross-border day-trippers from residents flying abroad.",
                "Southbound (南下) flow is daily Mainland visitor arrivals across all 17 control points, since Mainland visitors legitimately arrive by air, rail, and sea, not just by land.",
                "7-day moving averages (7d MA) smooth out day-of-week seasonality (weekend shopping spikes).",
            ],
        },
    },
    "weather_demand_drivers": {
        "id": "weather_demand_drivers",
        "label": "HKO Severe Weather Warnings & FRED Exchange Rate",
        "href": "https://www.hko.gov.hk/en/wxinfo/climat/warndb/warndb3.shtml",
        "query": {
            "engine": "official DAT & FRED CSV",
            "url": "https://www.hko.gov.hk/dps/wxinfo/climat/warndb/rstorm.dat",
            "language": "DAT",
            "description": "Monthly severe weather disruption hours (Typhoon Signal 8+ and Red/Black Rainstorm warnings) alongside monthly HKD/RMB cross exchange rate.",
            "metric_definitions": [
                "Typhoon Signal 8+ hours measures total duration under Signal 8, 9, or 10.",
                "Red/Black Rainstorm hours measures total duration under Red or Black rainstorm warnings.",
                "RMB per 100 HKD is derived from FRED daily DEXCHUS and DEXHKUS rates.",
            ],
        },
    },
    "hk_store_footprint": {
        "id": "hk_store_footprint",
        "label": "HK Retail/F&B Store-Count Scrapers",
        "href": "https://github.com/",
        "query": {
            "engine": "11 first-party scrapers (scripts/scrape_*_stores.py)",
            "language": "Python",
            "description": (
                "Store/branch counts scraped directly from each company's own store-locator "
                "page or API (Demandware, WCF REST, Next.js SSR, official mobile-app backends, "
                "etc.) -- see scripts/STORE_SCRAPE_REPORT.md in the repo root for per-company "
                "source detail and known coverage gaps."
            ),
            "metric_definitions": [
                "Total stores is each company's own latest snapshot count (not a cross-company-comparable unit -- a POP MART Roboshop and a Chow Tai Fook boutique are both counted as one location).",
                "This is a footprint snapshot, not a trend: most companies only have 1-2 dated snapshots so far, so month-over-month change is not yet meaningful.",
            ],
        },
    },
    "source_registry": {
        "id": "source_registry",
        "label": "HK Local Consumer dashboard source registry",
        "query": {
            "engine": "dashboard exporter",
            "language": "Python",
            "description": "Build-time validation results and declared coverage state for each dashboard source.",
            "tables_used": ["Validated live measure frames", "Declared future-source registry"],
        },
    },
}

# The portable dashboard renderer lays out a chart's color legend as a
# single-row flex box that does not actually reflow onto multiple lines at
# mobile width (a limitation of the vendored report runtime, not something
# this repo's code controls) -- so a multi-series legend must fit on one
# ~340px-wide line at the 390px mobile viewport the portable-artifact
# verifier checks, or the whole page overflows horizontally and the build
# fails. HK REIT's charts already work around this by coloring by short
# ticker codes rather than full REIT names (see build_hk_reit_artifact.py);
# AFCD's five wholesale-price categories have no natural short code, so
# this map supplies one just for the chart legend -- the full category
# name is still used everywhere else (bar chart x-axis, tables).
AFCD_CATEGORY_SHORT_LABELS = {
    "Eggs": "Eggs",
    "Freshwater fish": "FW fish",
    "Livestock / Poultry": "Meat/Poultry",
    "Marine fish": "Marine",
    "Vegetables": "Veg",
}


def _afcd_category_short_label(category: str) -> str:
    return AFCD_CATEGORY_SHORT_LABELS.get(category, category[:10])


# The classification variable's top-level breakdown (ccg "1" in CenStatD's
# table_620-67002_lang.json); the finer ~14-row "1.1" breakdown is fetched
# but not charted, to keep the comparison view readable.
TOP_LEVEL_RETAIL_CATEGORIES = [
    "Food, drinks & tobacco (excl. supermarkets)",
    "Supermarkets",
    "Fuels",
    "Clothing, footwear & allied products",
    "Consumer durable goods",
    "Department stores",
    "Jewellery, watches & valuable gifts",
    "Other consumer goods",
]

PLANNED_COVERAGE = []


def _records_json_safe(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a DataFrame to JSON-safe records (NaN/NaT -> null, dates -> ISO strings)."""
    if frame.empty:
        return []
    selected = frame.copy()
    for column in selected.columns:
        if pd.api.types.is_datetime64_any_dtype(selected[column]):
            selected[column] = selected[column].dt.strftime("%Y-%m-%d")
    return json.loads(selected.to_json(orient="records", date_format="iso"))


def _pricewatch_archive_coverage(summary: pd.DataFrame | None) -> list[dict[str, Any]]:
    """Return one honest archive-availability row, or no row when it is unusable.

    ``avg_price`` is deliberately not exposed here: a simple average of listed
    products moves when the retailer assortment changes, so it is not a
    comparable consumer-price index. A later matched-item methodology may use
    the archive to build a separately documented series.
    """
    required = {"year_month", "category_1", "supermarket_code", "avg_price", "item_count"}
    validation = summary.attrs.get("archive_validation", {}) if summary is not None else {}
    if not validation.get("complete"):
        return []
    if summary is None or summary.empty or not required.issubset(summary.columns):
        return []

    result = summary.loc[:, sorted(required)].copy()
    result["year_month"] = result["year_month"].astype(str)
    result["avg_price"] = pd.to_numeric(result["avg_price"], errors="coerce")
    result["item_count"] = pd.to_numeric(result["item_count"], errors="coerce")
    result = result[
        result["year_month"].str.fullmatch(r"\d{4}-\d{2}", na=False)
        & result["category_1"].notna()
        & result["supermarket_code"].notna()
        & result["avg_price"].notna()
        & result["item_count"].gt(0)
    ]
    if result.empty:
        return []

    return [
        {
            "first_observation": result["year_month"].min(),
            "latest_observation": result["year_month"].max(),
            "months": int(result["year_month"].nunique()),
            "category_supermarket_aggregates": int(len(result)),
            "categories": int(result["category_1"].nunique()),
            "supermarkets": int(result["supermarket_code"].nunique()),
            "notes": (
                "Local archive coverage only. A simple monthly mean of listed products is not "
                "a price index because product assortment, pack size, and offers can change."
            ),
        }
    ]


def _pricewatch_matched_index_rows(index: pd.DataFrame | None) -> list[dict[str, Any]]:
    required = {"year_month", "supermarket_code", "matched_item_index", "matched_products", "match_rate"}
    validation = index.attrs.get("archive_validation", {}) if index is not None else {}
    if index is None or index.empty or not validation.get("complete") or not required.issubset(index.columns):
        return []
    result = index.loc[:, sorted(required)].copy()
    result["matched_item_index"] = pd.to_numeric(result["matched_item_index"], errors="coerce")
    result["matched_products"] = pd.to_numeric(result["matched_products"], errors="coerce")
    result["match_rate"] = pd.to_numeric(result["match_rate"], errors="coerce")
    result = result.dropna(subset=["year_month", "supermarket_code", "matched_item_index", "matched_products"])
    # Several short-lived/renamed source codes exist in the archive. Showing
    # every one would turn a monitoring chart into an unreadable legend and
    # imply continuity that the raw code does not establish. Retain the four
    # longest source-code series with at least one year of linked
    # observations -- six, even with short codes, measured wider than the
    # mobile (390px) viewport in the portable-chart delivery pipeline.
    coverage = result.groupby("supermarket_code")["year_month"].nunique()
    eligible = coverage[coverage >= 12].sort_values(ascending=False).head(4).index
    result = result[result["supermarket_code"].isin(eligible)]
    return _records(result.sort_values(["year_month", "supermarket_code"]), list(sorted(required)))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _validate_gold(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError("SGE gold benchmark: no data returned")
    result = df.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["gold_benchmark_pm_rmb_gram"] = pd.to_numeric(result["gold_benchmark_pm_rmb_gram"], errors="coerce")
    result = result.dropna(subset=["date", "gold_benchmark_pm_rmb_gram"])
    if len(result) < 100:
        raise ValueError(f"SGE gold benchmark: expected at least 100 rows, received {len(result)}")
    if result["date"].duplicated().any():
        raise ValueError("SGE gold benchmark: duplicate observation dates")
    if (result["gold_benchmark_pm_rmb_gram"] <= 0).any():
        raise ValueError("SGE gold benchmark: non-positive price observed")
    result = result.sort_values("date").reset_index(drop=True)
    age_days = (now.replace(tzinfo=None) - result["date"].iloc[-1]).days
    if age_days > 20:
        raise ValueError(f"SGE gold benchmark: latest observation is stale by {age_days} days")
    return result


def _validate_afcd(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError("AFCD wholesale prices: no data returned")
    result = df.copy()
    result["price_hkd_per_kg"] = pd.to_numeric(result["price_hkd_per_kg"], errors="coerce")
    result = result.dropna(subset=["price_hkd_per_kg"])
    if len(result) < 100:
        raise ValueError(f"AFCD wholesale prices: expected at least 100 raw readings, received {len(result)}")
    aggregated = (
        result.groupby(["category", "commodity_name"], as_index=False)
        .agg(avg_price_hkd_per_kg=("price_hkd_per_kg", "mean"), num_readings=("price_hkd_per_kg", "size"))
    )
    if len(aggregated) < 15 or aggregated["category"].nunique() < 3:
        raise ValueError(
            f"AFCD wholesale prices: expected at least 15 commodities across 3+ categories, "
            f"received {len(aggregated)} commodities across {aggregated['category'].nunique()} categories"
        )
    aggregated["avg_price_hkd_per_kg"] = aggregated["avg_price_hkd_per_kg"].round(2)
    return aggregated.sort_values(["category", "avg_price_hkd_per_kg"], ascending=[True, False]).reset_index(drop=True)


def _validate_valuation(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError("HK consumer valuations: no data returned")
    result = df.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    for col in ("pe_ttm", "pb_ratio", "market_cap_hkd_b"):
        result[col] = pd.to_numeric(result[col], errors="coerce")
    result = result.dropna(subset=["date"])
    latest = result.sort_values("date").groupby("ticker", as_index=False).tail(1)
    usable = latest.dropna(subset=["pe_ttm", "pb_ratio", "market_cap_hkd_b"], how="all")
    if len(usable) < 5:
        raise ValueError(f"HK consumer valuations: expected at least 5 tickers with usable data, received {len(usable)}")
    age_days = (now.replace(tzinfo=None) - latest["date"].max()).days
    if age_days > 20:
        raise ValueError(f"HK consumer valuations: latest observation is stale by {age_days} days")
    return result.sort_values(["ticker", "date"]).reset_index(drop=True)


def _latest_growth(frame: pd.DataFrame, key: str, value: str, periods: int, change_name: str) -> pd.DataFrame:
    """Return each series' latest row with a same-grain percent change."""
    result = frame.sort_values([key, "date"]).copy()
    result[change_name] = result.groupby(key)[value].pct_change(periods=periods)
    return result.groupby(key, as_index=False).tail(1).reset_index(drop=True)


def _validate_retail_sales(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError("C&SD retail sales: no data returned")
    result = df.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["sales_value_index"] = pd.to_numeric(result["sales_value_index"], errors="coerce")
    result = result.dropna(subset=["date", "category", "sales_value_index"])
    if len(result) < 100 or result["category"].nunique() < 5:
        raise ValueError(f"C&SD retail sales: expected at least 100 rows across 5+ categories, received {len(result)}")
    if "All retail outlet" not in set(result["category"]):
        raise ValueError("C&SD retail sales: missing the All retail outlet total series")
    age_days = (now.replace(tzinfo=None) - result["date"].max()).days
    if age_days > 120:
        raise ValueError(f"C&SD retail sales: latest observation is stale by {age_days} days")
    return result.sort_values(["category", "date"]).reset_index(drop=True)


def _validate_restaurant_survey(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError("CenStatD restaurant survey: no data returned")
    result = df.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["total_receipts_hkd_m"] = pd.to_numeric(result["total_receipts_hkd_m"], errors="coerce")
    result = result.dropna(subset=["date", "sub_sector", "total_receipts_hkd_m"])
    if len(result) < 20 or result["sub_sector"].nunique() < 4:
        raise ValueError(f"CenStatD restaurant survey: expected at least 20 rows across 4+ sub-sectors, received {len(result)}")
    if "All restaurants" not in set(result["sub_sector"]):
        raise ValueError("CenStatD restaurant survey: missing the All restaurants total series")
    age_days = (now.replace(tzinfo=None) - result["date"].max()).days
    if age_days > 200:
        raise ValueError(f"CenStatD restaurant survey: latest observation is stale by {age_days} days")
    return result.sort_values(["sub_sector", "date"]).reset_index(drop=True)


def _validate_immigration(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError("Immigration daily traffic: no data returned")
    result = df.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    for col in (
        "hk_resident_departures",
        "mainland_visitor_arrivals",
        "hk_resident_departures_7d_ma",
        "mainland_visitor_arrivals_7d_ma",
        "land_hk_resident_departures_7d_ma",
    ):
        result[col] = pd.to_numeric(result[col], errors="coerce")
    result = result.dropna(subset=["date", "hk_resident_departures", "mainland_visitor_arrivals"])
    if len(result) < 100:
        raise ValueError(f"Immigration daily traffic: expected at least 100 days of data, received {len(result)}")
    age_days = (now.replace(tzinfo=None) - result["date"].max()).days
    if age_days > 20:
        raise ValueError(f"Immigration daily traffic: latest observation is stale by {age_days} days")
    return result.sort_values("date").reset_index(drop=True)


# The 11 store-count scrapers live in the repo root's scripts/ directory,
# outside this app's own data flow -- their output is data/processed/*_stores/
# store_counts.parquet in the repo root, not anything under this app's own
# data/ directories. Each is real, already-hardened data (see
# scripts/STORE_SCRAPE_REPORT.md); this just reads it directly rather than
# needing a separate sync/copy step, since REPO_ROOT is already on sys.path.
STORE_FOOTPRINT_COMPANIES: list[dict[str, str]] = [
    {"company": "Chow Tai Fook", "stock_code": "01929.HK", "sector": "Jewellery", "dir": "ctf_stores"},
    {"company": "Luk Fook", "stock_code": "00590.HK", "sector": "Jewellery", "dir": "lukfook_stores"},
    {"company": "Chow Sang Sang", "stock_code": "00116.HK", "sector": "Jewellery", "dir": "chowsangsang_stores"},
    {"company": "Lao Pu Gold", "stock_code": "06181.HK", "sector": "Jewellery", "dir": "laopugold_stores"},
    {"company": "Giordano", "stock_code": "00709.HK", "sector": "Apparel", "dir": "giordano_stores"},
    {"company": "Bossini", "stock_code": "00592.HK", "sector": "Apparel", "dir": "bossini_stores"},
    {"company": "Tai Hing Group", "stock_code": "06811.HK", "sector": "F&B", "dir": "taihing_stores"},
    {"company": "Fairwood", "stock_code": "00052.HK", "sector": "F&B", "dir": "fairwood_stores"},
    {"company": "Café de Coral", "stock_code": "00341.HK", "sector": "F&B", "dir": "cafedecoral_stores"},
    {"company": "Sa Sa", "stock_code": "00178.HK", "sector": "Cosmetics", "dir": "sasa_stores"},
    {"company": "POP MART", "stock_code": "09992.HK", "sector": "Trendy Toys", "dir": "popmart_stores"},
]


def fetch_store_footprint_snapshot() -> pd.DataFrame:
    """Read each company's latest store-count snapshot from the repo-root scrapers.

    Two schema shapes exist across the 11 scrapers (see STORE_SCRAPE_REPORT.md):
    - 10 of them: a (date, <group_key>, store_count) rollup with a "TOTAL"
      row -- but the group-key column name is NOT consistently "region":
      Fairwood uses "category", Sa Sa uses "district", Café de Coral uses
      "area" (each scraper's own append_snapshot(key_column=...) choice).
      Detected dynamically here rather than hardcoding "region", which
      previously misdetected those three as the POP MART shape below and
      silently undercounted them (e.g. Fairwood read as 5 stores, not 151).
    - POP MART: a rich per-store record (one row per store/Roboshop, no
      rollup, no "store_count"/"TOTAL" at all) -- its total is len() of the
      latest date's rows instead.
    """
    rows: list[dict[str, Any]] = []
    for entry in STORE_FOOTPRINT_COMPANIES:
        path = REPO_ROOT / "data" / "processed" / entry["dir"] / "store_counts.parquet"
        if not path.exists():
            continue
        try:
            df = pd.read_parquet(path)
        except Exception:  # noqa: BLE001 -- a corrupt/partial local file should not break the build
            continue
        if df.empty or "date" not in df.columns:
            continue
        latest_date = df["date"].max()
        latest = df[df["date"] == latest_date]

        group_key = next(
            (
                col
                for col in latest.columns
                if col not in ("date", "store_count") and (latest[col] == "TOTAL").any()
            ),
            None,
        ) if "store_count" in latest.columns else None

        if group_key is not None:
            total_row = latest[latest[group_key] == "TOTAL"]
            if total_row.empty:
                continue
            total_stores = float(total_row["store_count"].iloc[0])
            regions_tracked = int((latest[group_key] != "TOTAL").sum())
        else:
            # POP MART's rich per-store schema: one row = one store/Roboshop.
            total_stores = float(len(latest))
            market_col = "market" if "market" in latest.columns else ("country" if "country" in latest.columns else None)
            regions_tracked = int(latest[market_col].nunique()) if market_col else 0

        rows.append(
            {
                "company": entry["company"],
                "stock_code": entry["stock_code"],
                "sector": entry["sector"],
                "total_stores": total_stores,
                "snapshot_date": str(latest_date)[:10],
                "regions_tracked": regions_tracked,
            }
        )
    return pd.DataFrame(rows)


def _validate_weather(df: pd.DataFrame, now: datetime) -> pd.DataFrame:
    if df is None or df.empty:
        raise ValueError("Weather and demand drivers: no data returned")
    result = df.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    for col in ("signal_8_plus_hours", "red_black_rain_hours", "total_disruption_hours", "rmb_per_100_hkd"):
        result[col] = pd.to_numeric(result[col], errors="coerce")
    result = result.dropna(subset=["date", "total_disruption_hours"])
    if len(result) < 20:
        raise ValueError(f"Weather and demand drivers: expected at least 20 months of data, received {len(result)}")
    return result.sort_values("date").reset_index(drop=True)


def _comparison_row(frame: pd.DataFrame, value_column: str, now: datetime) -> dict[str, Any]:
    latest = frame.iloc[-1]
    prior = frame.iloc[-2]
    target = pd.Timestamp(now.replace(tzinfo=None)) - pd.DateOffset(years=1)
    past = frame[frame["date"] <= target]
    yearly = past.iloc[-1] if not past.empty else frame.iloc[0]
    value = float(latest[value_column])
    prior_value = float(prior[value_column])
    yearly_value = float(yearly[value_column])
    period_change = round(value / prior_value - 1, 6) if prior_value else None
    year_change = round(value / yearly_value - 1, 6) if yearly_value else None
    return {
        "latest": round(value, 2),
        "period_change": period_change,
        "year_change": year_change,
        "observation_date": latest["date"].strftime("%Y-%m-%d"),
    }


def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    selected = frame.loc[:, columns].copy()
    for column in selected.columns:
        if pd.api.types.is_datetime64_any_dtype(selected[column]):
            selected[column] = selected[column].dt.strftime("%Y-%m-%d")
    return json.loads(selected.to_json(orient="records", date_format="iso"))


def _daily_weather_hours(events: list[dict[str, Any]], start_date: pd.Timestamp) -> pd.DataFrame:
    """Split warning intervals at midnight before aggregating daily hours."""
    rows: list[dict[str, Any]] = []
    for event in events:
        start = pd.to_datetime(event.get("start"), errors="coerce")
        end = pd.to_datetime(event.get("end"), errors="coerce")
        if pd.isna(start) or pd.isna(end) or end <= start:
            continue
        current = max(start, start_date)
        while current < end:
            next_midnight = current.normalize() + pd.Timedelta(days=1)
            segment_end = min(end, next_midnight)
            rows.append({
                "date": current.normalize(),
                "warning_type": "Red/Black rain" if "Rainstorm" in str(event.get("signal_name")) else "Typhoon Signal 8+",
                "hours": round((segment_end - current).total_seconds() / 3600.0, 2),
            })
            current = segment_end
    if not rows:
        return pd.DataFrame(columns=["date", "warning_type", "hours"])
    return pd.DataFrame(rows).groupby(["date", "warning_type"], as_index=False)["hours"].sum()


def _stamp_sources(generated_at: str) -> list[dict[str, Any]]:
    result = []
    for source in PUBLIC_SOURCES.values():
        copy = json.loads(json.dumps(source))
        copy.setdefault("query", {})["executed_at"] = generated_at
        result.append(copy)
    return result


def _update_afcd_category_history(
    category_summary: pd.DataFrame, now: datetime, history_path: Path = AFCD_CATEGORY_HISTORY_PATH
) -> pd.DataFrame:
    """Append today's real AFCD category averages to the running local
    history file and return the full accumulated history.

    This is a genuine build-forward accumulation, not a backfill: AFCD
    itself only ever publishes today's readings (see
    AFCD_CATEGORY_HISTORY_PATH's comment above), so the only honest way to
    build an "over time" series is to keep every day's real snapshot that
    this pipeline actually captures. The history therefore starts as thin
    as a single day and grows by one row per category each time the
    pipeline runs (daily, per the GitHub Actions schedule). Re-running on
    the same UTC date replaces that date's rows instead of duplicating
    them, so the file stays idempotent under repeated manual runs.
    """
    today = now.date().isoformat()
    today_rows = category_summary.loc[:, ["category", "avg_price_hkd_per_kg", "commodities"]].copy()
    today_rows.insert(0, "date", today)

    if history_path.exists():
        existing = pd.read_csv(history_path, dtype={"date": str})
    else:
        existing = pd.DataFrame(columns=["date", "category", "avg_price_hkd_per_kg", "commodities"])

    existing = existing[existing["date"] != today]
    combined = today_rows if existing.empty else pd.concat([existing, today_rows], ignore_index=True)
    combined["date"] = combined["date"].astype(str)
    combined["avg_price_hkd_per_kg"] = pd.to_numeric(combined["avg_price_hkd_per_kg"], errors="coerce")
    combined["commodities"] = pd.to_numeric(combined["commodities"], errors="coerce").astype("Int64")
    combined = combined.sort_values(["date", "category"]).reset_index(drop=True)

    history_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(history_path, index=False)
    return combined


def build_artifact(
    raw_gold: pd.DataFrame,
    raw_afcd: pd.DataFrame,
    raw_valuation: pd.DataFrame,
    raw_retail: pd.DataFrame,
    raw_restaurant: pd.DataFrame,
    raw_immigration: pd.DataFrame | None = None,
    raw_weather: pd.DataFrame | None = None,
    raw_store_footprint: pd.DataFrame | None = None,
    raw_pricewatch_summary: pd.DataFrame | None = None,
    raw_pricewatch_index: pd.DataFrame | None = None,
    *,
    now: datetime | None = None,
    afcd_history_path: Path = AFCD_CATEGORY_HISTORY_PATH,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    if raw_immigration is None:
        raw_immigration = fetch_immigration_flow()
    if raw_weather is None:
        raw_weather = fetch_weather_demand_drivers()
    if raw_store_footprint is None:
        raw_store_footprint = fetch_store_footprint_snapshot()

    gold = _validate_gold(raw_gold, now)
    afcd = _validate_afcd(raw_afcd)
    valuation = _validate_valuation(raw_valuation, now)
    retail = _validate_retail_sales(raw_retail, now)
    restaurant = _validate_restaurant_survey(raw_restaurant, now)
    immigration = _validate_immigration(raw_immigration, now)
    weather = _validate_weather(raw_weather, now)
    pricewatch_archive = _pricewatch_archive_coverage(raw_pricewatch_summary)
    pricewatch_index_rows = _pricewatch_matched_index_rows(raw_pricewatch_index)
    pricewatch_validation = (
        raw_pricewatch_summary.attrs.get("archive_validation", {})
        if raw_pricewatch_summary is not None
        else {"reason": "historical archive was not loaded"}
    )

    generated_at = now.isoformat().replace("+00:00", "Z")
    gold_kpi = _comparison_row(gold, "gold_benchmark_pm_rmb_gram", now)

    valuation_latest = valuation.sort_values("date").groupby("ticker", as_index=False).tail(1)
    pe_values = valuation_latest["pe_ttm"].dropna()
    median_pe_latest = float(pe_values.median()) if not pe_values.empty else None

    retail_total = retail[retail["category"] == "All retail outlet"].sort_values("date").reset_index(drop=True)
    # "YYYY-MM" companion column: retail_history is a >20-year monthly
    # series, and the portable-chart plugin's date-axis formatter always
    # includes the year for month-granularity values but omits it by
    # default for day-granularity ones (see mtr/transport builder for the
    # same pattern). Encoding the chart's x axis against `month` instead of
    # `date` keeps every tick year-unambiguous.
    retail_total["month"] = retail_total["date"].dt.strftime("%Y-%m")
    retail_kpi = _comparison_row(retail_total, "sales_value_index", now)
    retail_latest_by_category = retail.sort_values("date").groupby("category", as_index=False).tail(1)
    retail_category_snapshot = retail_latest_by_category[
        retail_latest_by_category["category"].isin(TOP_LEVEL_RETAIL_CATEGORIES + ["All retail outlet"])
    ].sort_values("sales_value_index", ascending=False).reset_index(drop=True)
    retail_yoy = _latest_growth(
        retail[retail["category"].isin(TOP_LEVEL_RETAIL_CATEGORIES)], "category", "sales_value_index", 12, "yoy_change"
    )
    retail_mom = _latest_growth(
        retail[retail["category"].isin(TOP_LEVEL_RETAIL_CATEGORIES)], "category", "sales_value_index", 1, "mom_change"
    )
    retail_growth = retail_yoy.merge(retail_mom[["category", "mom_change"]], on="category", how="left")
    retail_category_snapshot = retail_category_snapshot.merge(
        retail_growth[["category", "yoy_change", "mom_change"]], on="category", how="left"
    )
    retail_chart_rows = retail_growth.sort_values("yoy_change").reset_index(drop=True)

    restaurant_total = restaurant[restaurant["sub_sector"] == "All restaurants"].sort_values("date").reset_index(drop=True)
    # Same month-granularity treatment as retail_total above -- restaurant
    # receipts are quarterly over >20 years, so each quarter-end date lands
    # on a distinct "YYYY-MM" with no collisions.
    restaurant_total["month"] = restaurant_total["date"].dt.strftime("%Y-%m")
    restaurant_kpi = _comparison_row(restaurant_total, "total_receipts_hkd_m", now)
    restaurant_latest_by_type = restaurant.sort_values("date").groupby("sub_sector", as_index=False).tail(1)
    restaurant_snapshot = restaurant_latest_by_type.sort_values("total_receipts_hkd_m", ascending=False).reset_index(drop=True)
    restaurant_yoy = _latest_growth(
        restaurant[restaurant["sub_sector"] != "All restaurants"], "sub_sector", "total_receipts_hkd_m", 4, "yoy_change"
    )
    restaurant_qoq = _latest_growth(
        restaurant[restaurant["sub_sector"] != "All restaurants"], "sub_sector", "total_receipts_hkd_m", 1, "qoq_change"
    )
    restaurant_growth = restaurant_yoy.merge(restaurant_qoq[["sub_sector", "qoq_change"]], on="sub_sector", how="left")
    restaurant_snapshot = restaurant_snapshot.merge(
        restaurant_growth[["sub_sector", "yoy_change", "qoq_change"]], on="sub_sector", how="left"
    )
    restaurant_chart_rows = restaurant_growth.sort_values("yoy_change").reset_index(drop=True)

    # Cross-border immigration KPIs and trend charts
    northbound_kpi = _comparison_row(immigration, "land_hk_resident_departures_7d_ma", now)
    southbound_kpi = _comparison_row(immigration, "mainland_visitor_arrivals_7d_ma", now)

    # HK Immigration's daily CSV goes back to 2021-01-01 (~5.5 years), but
    # the portable-chart plugin's x-axis auto-tick placement always forces a
    # label on the very last point regardless of the chosen tick interval;
    # with the full ~67-month history that forced last tick collides with
    # the previous auto-picked tick and overlaps text at the chart's right
    # edge (confirmed empirically -- trimming one partial month just shifted
    # which two ticks collided, not whether they did). A bounded window
    # avoids that edge case and was the previously verified-passing state.
    imm_chart_window = immigration.tail(1000).copy()
    imm_north = imm_chart_window[["date", "land_hk_resident_departures_7d_ma"]].rename(columns={"land_hk_resident_departures_7d_ma": "value"})
    imm_north["flow_type"] = "Northbound"
    imm_south = imm_chart_window[["date", "mainland_visitor_arrivals_7d_ma"]].rename(columns={"mainland_visitor_arrivals_7d_ma": "value"})
    imm_south["flow_type"] = "Southbound"
    imm_daily = pd.concat([imm_north, imm_south], ignore_index=True)
    # Resampled to a monthly mean (of the already-smoothed 7d moving
    # average) for the chart specifically: this ~2.7-year window is
    # genuinely daily-granularity data, and the portable-chart plugin's
    # date-axis formatter has no schema-level way to force the year onto
    # day-granularity tick labels (it's a hardcoded default in the
    # renderer's formatDateAxisLabel, not something artifact JSON can
    # override) -- every tick would otherwise show only "Mon DD" and, with
    # ~2.7 years of daily points, the same day-of-month recurs across
    # multiple different years with no way to tell them apart. Rolling up
    # to a "YYYY-MM" `month` column keeps every point on a distinct,
    # always-year-labeled tick at the cost of daily resolution, which this
    # already-smoothed series does not need for a dashboard trend line.
    imm_daily["month"] = imm_daily["date"].dt.strftime("%Y-%m")
    # Drop the current, still-incomplete calendar month: a partial month's
    # mean sits right next to the prior full month with far less than a
    # month's worth of days behind it, which both understates the point
    # and -- pixel-adjacent to the previous tick at the axis's right edge --
    # is what was overlapping the portable chart's last two x-axis labels
    # into each other and tripping the delivery pipeline's desktop-width
    # overflow check.
    current_month = now.strftime("%Y-%m")
    imm_daily = imm_daily[imm_daily["month"] < current_month]
    immigration_trend_rows = (
        imm_daily.groupby(["month", "flow_type"], as_index=False)["value"]
        .mean()
        .sort_values(["month", "flow_type"])
        .reset_index(drop=True)
    )
    immigration_trend_rows["value"] = immigration_trend_rows["value"].round(1)
    # Built from the same fetch already performed above (raw_immigration),
    # not re-read from the local normalized cache: that cache only exists
    # after `hk-local-consumer run-dashboard-history` has been run locally
    # and is gitignored (data/normalized/hk_local_consumer/*), so a fresh CI
    # checkout has no such directory and would otherwise crash this build.
    checkpoint_history = raw_immigration.attrs.get("checkpoint_history", pd.DataFrame())
    checkpoint_trend = pd.DataFrame(columns=["date", "series", "value"])
    if isinstance(checkpoint_history, pd.DataFrame) and not checkpoint_history.empty:
        checkpoint_history = checkpoint_history.rename(columns={
            "Date": "date", "Control Point": "control_point", "Arrival / Departure": "direction",
            "Hong Kong Residents": "hk_residents", "Mainland Visitors": "mainland_visitors",
            "Other Visitors": "other_visitors", "Total": "total",
        })
        checkpoint_history["date"] = pd.to_datetime(checkpoint_history["date"], errors="coerce")
        checkpoint_history["value"] = pd.to_numeric(checkpoint_history["total"], errors="coerce")
        checkpoint_history = checkpoint_history.dropna(subset=["date", "value"])
        checkpoint_history["series"] = checkpoint_history["control_point"].astype(str) + " — " + checkpoint_history["direction"].astype(str)
        latest_window = checkpoint_history[checkpoint_history["date"] >= checkpoint_history["date"].max() - pd.Timedelta(days=6)]
        top_series = latest_window.groupby("series")["value"].mean().nlargest(5).index
        checkpoint_trend = checkpoint_history[checkpoint_history["series"].isin(top_series)].copy()
        checkpoint_trend["value"] = checkpoint_trend.sort_values("date").groupby("series")["value"].transform(lambda values: values.rolling(7, min_periods=1).mean()).round(1)
        checkpoint_trend = checkpoint_trend[checkpoint_trend["date"] >= checkpoint_trend["date"].max() - pd.Timedelta(days=89)]

    # Severe weather & FX demand driver KPIs and charts
    weather_kpi = _comparison_row(weather, "total_disruption_hours", now)
    fx_kpi = _comparison_row(weather, "rmb_per_100_hkd", now)
    weather_chart_rows = weather.tail(36).copy()
    # Same reasoning as checkpoint_history above: use the events already
    # attached to raw_weather's fetch rather than the gitignored, locally-only
    # normalized cache, so this chart also works on a fresh CI checkout.
    weather_daily = _daily_weather_hours(
        raw_weather.attrs.get("events", []),
        pd.Timestamp(now.replace(tzinfo=None)).normalize() - pd.DateOffset(months=36),
    )
    if not weather_daily.empty:
        weather_daily["month"] = weather_daily["date"].dt.strftime("%Y-%m")
    else:
        weather_daily = pd.DataFrame(columns=["date", "month", "warning_type", "hours"])

    category_summary = (
        afcd.groupby("category", as_index=False)
        .agg(avg_price_hkd_per_kg=("avg_price_hkd_per_kg", "mean"), commodities=("commodity_name", "size"))
    )
    category_summary["avg_price_hkd_per_kg"] = category_summary["avg_price_hkd_per_kg"].round(2)
    category_summary = category_summary.sort_values("avg_price_hkd_per_kg", ascending=False).reset_index(drop=True)

    afcd_category_history = _update_afcd_category_history(category_summary, now, afcd_history_path)

    valuation_chart_rows = valuation_latest.dropna(subset=["pe_ttm"])
    valuation_chart_rows = valuation_chart_rows[valuation_chart_rows["pe_ttm"] > 0]

    health = [
        {
            "source": PUBLIC_SOURCES["weather_demand_drivers"]["label"],
            "dataset": "HKO Severe Weather & FRED FX",
            "type": "Measure",
            "status": "Healthy",
            "latest_observation": weather["date"].max().strftime("%Y-%m-%d"),
            "records": int(len(weather)),
            "freshness": f"{(now.replace(tzinfo=None) - weather['date'].max()).days}d old",
            "notes": "Monthly hours under Typhoon Signal 8+ & Red/Black Rainstorm warnings alongside HKD/RMB FX.",
        },
        {
            "source": PUBLIC_SOURCES["immigration_flow"]["label"],
            "dataset": "Immigration Passenger Clearance",
            "type": "Measure",
            "status": "Healthy",
            "latest_observation": immigration["date"].max().strftime("%Y-%m-%d"),
            "records": int(len(immigration)),
            "freshness": f"{(now.replace(tzinfo=None) - immigration['date'].max()).days}d old",
            "notes": "Daily clearance across 17 control points for HK residents & Mainland visitors.",
        },
        {
            "source": PUBLIC_SOURCES["sge_gold"]["label"],
            "dataset": "SGE Gold Benchmark",
            "type": "Measure",
            "status": "Healthy",
            "latest_observation": gold["date"].iloc[-1].strftime("%Y-%m-%d"),
            "records": int(len(gold)),
            "freshness": f"{(now.replace(tzinfo=None) - gold['date'].iloc[-1]).days}d old",
            "notes": "Daily AM/PM benchmark fixing.",
        },
        {
            "source": PUBLIC_SOURCES["afcd_wholesale"]["label"],
            "dataset": "AFCD Wholesale Food Prices",
            "type": "Measure",
            "status": "Healthy",
            "latest_observation": now.date().isoformat(),
            "records": int(len(afcd)),
            "freshness": "Same-day snapshot",
            "notes": f"{len(afcd)} commodities across {afcd['category'].nunique()} categories; averaged across same-day market readings.",
        },
        {
            "source": PUBLIC_SOURCES["hk_valuation"]["label"],
            "dataset": "HK Consumer Ticker Valuations",
            "type": "Measure",
            "status": "Healthy",
            "latest_observation": valuation["date"].max().strftime("%Y-%m-%d"),
            "records": int(len(valuation)),
            "freshness": f"{(now.replace(tzinfo=None) - valuation['date'].max()).days}d old",
            "notes": "PE (TTM), PB, and market cap only; no dividend-yield indicator is available from this endpoint.",
        },
        {
            "source": PUBLIC_SOURCES["cnsd_retail"]["label"],
            "dataset": "Retail Sales Value/Volume Index",
            "type": "Measure",
            "status": "Healthy",
            "latest_observation": retail["date"].max().strftime("%Y-%m-%d"),
            "records": int(len(retail)),
            "freshness": f"{(now.replace(tzinfo=None) - retail['date'].max()).days}d old",
            "notes": f"{retail['category'].nunique()} outlet-type categories, monthly since {retail['date'].min().strftime('%Y')}.",
        },
        {
            "source": PUBLIC_SOURCES["censtatd_restaurant"]["label"],
            "dataset": "Restaurant Receipts & Purchases Survey",
            "type": "Measure",
            "status": "Healthy",
            "latest_observation": restaurant["date"].max().strftime("%Y-%m-%d"),
            "records": int(len(restaurant)),
            "freshness": f"{(now.replace(tzinfo=None) - restaurant['date'].max()).days}d old",
            "notes": "Sector-wide purchases only; per-type purchases are not published.",
        },
    ]
    store_footprint = raw_store_footprint if raw_store_footprint is not None else pd.DataFrame()
    if not store_footprint.empty:
        store_footprint = store_footprint.sort_values("total_stores", ascending=False).reset_index(drop=True)
        health.append(
            {
                "source": PUBLIC_SOURCES["hk_store_footprint"]["label"],
                "dataset": "HK Retail/F&B Store Counts",
                "type": "Snapshot",
                "status": "Healthy",
                "latest_observation": store_footprint["snapshot_date"].max(),
                "records": int(len(store_footprint)),
                "freshness": "Footprint snapshot (most brands: 1-2 dated snapshots so far, not yet a trend)",
                "notes": f"{int(store_footprint['total_stores'].sum()):,} total tracked locations across {len(store_footprint)} companies.",
            }
        )
    if pricewatch_archive:
        archive = pricewatch_archive[0]
        health.append(
            {
                "source": PUBLIC_SOURCES["consumer_council_pricewatch"]["label"],
                "dataset": "Online Price Watch historical archive",
                "type": "Catalog",
                "status": "Healthy",
                "latest_observation": archive["latest_observation"],
                "records": archive["category_supermarket_aggregates"],
                "freshness": f"Archive through {archive['latest_observation']}",
                "notes": (
                    f"{archive['months']} months across {archive['categories']} categories and "
                    f"{archive['supermarkets']} supermarket codes. Coverage only; no price index is rendered."
                ),
            }
        )
    # Split, not merged: "active" is every source already backing a live
    # card/chart/table above; "planned" is next-target sources whose
    # endpoint is broken/unverified and therefore excluded from the live
    # dashboard rather than shown with placeholder values.
    coverage_active = health
    coverage_planned = list(PLANNED_COVERAGE)
    if not pricewatch_archive:
        coverage_planned.append(
            {
                "source": PUBLIC_SOURCES["consumer_council_pricewatch"]["label"],
                "dataset": "Online Price Watch historical archive",
                "type": "Catalog",
                "status": "Unavailable locally",
                "freshness": "—",
                "notes": f"Not marked Healthy: {pricewatch_validation.get('reason', 'archive validation did not pass')}.",
            }
        )

    # KPI comparisons use the full validated history; the chart itself is
    # windowed to the portable artifact's 2,000-row-per-dataset cap, then
    # resampled to a monthly mean. This ~7-year window is genuinely
    # daily-granularity data, and the portable-chart plugin's date-axis
    # formatter has no schema-level way to force the year onto
    # day-granularity tick labels (it always includes the year for
    # month-granularity values but omits it by default for day-granularity
    # ones, hardcoded in the renderer's formatDateAxisLabel) -- every tick
    # would otherwise show only "Mon DD" and the same day-of-month recurs
    # across many different years with no way to tell them apart. Rolling
    # up to a "YYYY-MM" `month` column keeps every point on a distinct,
    # always-year-labeled tick.
    gold_chart_daily = gold.tail(1_800).rename(columns={"gold_benchmark_pm_rmb_gram": "value"})[["date", "value"]].copy()
    gold_chart_daily["month"] = gold_chart_daily["date"].dt.strftime("%Y-%m")
    gold_chart_window = (
        gold_chart_daily.groupby("month", as_index=False)["value"]
        .mean()
        .sort_values("month")
        .reset_index(drop=True)
    )
    gold_chart_window["value"] = gold_chart_window["value"].round(2)

    recent_weather_events = weather.attrs.get("recent_events", [])

    datasets = {
        "kpi_weather": [weather_kpi],
        "kpi_fx": [fx_kpi],
        "severe_weather_history": _records(
            weather_chart_rows, ["date", "month", "signal_8_plus_hours", "red_black_rain_hours", "total_disruption_hours"]
        ),
        "severe_weather_daily": _records(weather_daily, ["date", "month", "warning_type", "hours"]),
        "severe_weather_log": recent_weather_events,
        "kpi_northbound": [northbound_kpi],
        "kpi_southbound": [southbound_kpi],
        "immigration_trend_history": _records(immigration_trend_rows, ["month", "value", "flow_type"]),
        "immigration_checkpoint_history": _records(checkpoint_trend, ["date", "series", "value"]),
        "kpi_gold": [gold_kpi],
        "kpi_median_pe": [{"latest": round(median_pe_latest, 2)}] if median_pe_latest is not None else [],
        "gold_history": _records(gold_chart_window, ["month", "value"]),
        "afcd_category_summary": _records(category_summary, ["category", "avg_price_hkd_per_kg", "commodities"]),
        "afcd_category_trend_history": _records(
            afcd_category_history.tail(450).assign(
                category_short=lambda frame: frame["category"].map(_afcd_category_short_label)
            ),
            ["date", "category", "category_short", "avg_price_hkd_per_kg", "commodities"],
        ),
        "afcd_commodity_table": _records(
            afcd, ["category", "commodity_name", "avg_price_hkd_per_kg", "num_readings"]
        ),
        "valuation_table": _records(
            valuation_latest, ["ticker", "company_name", "pe_ttm", "pb_ratio", "market_cap_hkd_b", "date"]
        ),
        "valuation_pe_chart": _records(valuation_chart_rows, ["company_name", "pe_ttm"]),
        "valuation_history": _records(
            valuation[
                (valuation["date"] >= valuation["date"].max() - pd.Timedelta(days=30))
                # Top 3 by latest market cap, not all 11 watchlist names: a
                # legend of full company names past 3 entries measured wider
                # than the mobile (390px) viewport in the portable-chart
                # delivery pipeline (confirmed via direct DOM inspection of
                # the rendered legend at both 1440px and 390px). The full
                # watchlist is still in valuation_table below.
                & valuation["company_name"].isin(
                    valuation_latest.nlargest(3, "market_cap_hkd_b")["company_name"]
                )
            ],
            ["date", "ticker", "company_name", "pe_ttm", "pb_ratio", "market_cap_hkd_b"],
        ),
        "kpi_retail": [retail_kpi],
        "retail_history": _records(
            retail_total.tail(120).rename(columns={"sales_value_index": "value"}), ["date", "month", "value"]
        ),
        "retail_category_snapshot": _records(
            retail_category_snapshot, ["category", "sales_value_index", "sales_volume_index", "yoy_change", "mom_change", "date"]
        ),
        "retail_category_chart": _records(retail_chart_rows, ["category", "yoy_change"]),
        "kpi_restaurant": [restaurant_kpi],
        "restaurant_history": _records(
            restaurant_total.tail(80).rename(columns={"total_receipts_hkd_m": "value"}), ["date", "month", "value"]
        ),
        "restaurant_snapshot": _records(
            restaurant_snapshot,
            ["sub_sector", "total_receipts_hkd_m", "total_purchases_hkd_m", "receipts_value_index", "yoy_change", "qoq_change", "date"],
        ),
        "restaurant_chart": _records(restaurant_chart_rows, ["sub_sector", "yoy_change"]),
        "kpi_store_footprint": (
            [
                {
                    "latest": int(store_footprint["total_stores"].sum()),
                    "observation_date": store_footprint["snapshot_date"].max(),
                }
            ]
            if not store_footprint.empty
            else []
        ),
        "store_footprint_snapshot": _records(
            store_footprint, ["company", "stock_code", "sector", "total_stores", "regions_tracked", "snapshot_date"]
        ),
        "store_footprint_chart": _records(store_footprint, ["company", "total_stores"]),
        "consumer_council_pricewatch_archive": pricewatch_archive,
        "consumer_council_pricewatch_matched_index": pricewatch_index_rows,
        "source_health": health,
        "source_coverage_active": coverage_active,
        "source_coverage_planned": coverage_planned,
    }
    fingerprint_payload = {
        "datasets": datasets,
        "source_urls": [source.get("href") for source in PUBLIC_SOURCES.values() if source.get("href")],
    }
    snapshot_id = hashlib.sha256(
        json.dumps(fingerprint_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:16]

    sources = _stamp_sources(generated_at)
    manifest_sources = [
        {
            **{key: source[key] for key in ("id", "label", "href") if key in source},
            "path": f"sources/{source['id']}.sql",
        }
        for source in sources
    ]

    cards = [
        {
            "id": "northbound_card",
            "description": "Daily HK resident departures via land control points only (7-day MA); day-on-day and year-on-year movements.",
            "dataset": "kpi_northbound",
            "sourceId": "immigration_flow",
            "metrics": [
                {"label": "Northbound 7d MA (land)", "field": "latest", "format": "number"},
                {"label": "DoD", "field": "period_change", "format": "percent", "signed": True},
                {"label": "YoY", "field": "year_change", "format": "percent", "signed": True},
            ],
        },
        {
            "id": "southbound_card",
            "description": "Daily Mainland visitor arrivals (7-day MA); day-on-day and year-on-year movements.",
            "dataset": "kpi_southbound",
            "sourceId": "immigration_flow",
            "metrics": [
                {"label": "Southbound 7d MA", "field": "latest", "format": "number"},
                {"label": "DoD", "field": "period_change", "format": "percent", "signed": True},
                {"label": "YoY", "field": "year_change", "format": "percent", "signed": True},
            ],
        },
        {
            "id": "weather_card",
            "description": "Monthly severe weather disruption hours (Signal 8+ Typhoons & Red/Black Rainstorm Warnings).",
            "dataset": "kpi_weather",
            "sourceId": "weather_demand_drivers",
            "metrics": [
                {"label": "Severe weather (hrs/mo)", "field": "latest", "format": "number"},
                {"label": "YoY", "field": "year_change", "format": "percent", "signed": True},
            ],
        },
        {
            "id": "fx_card",
            "description": "Monthly average RMB per 100 HKD cross rate derived from FRED daily quotes.",
            "dataset": "kpi_fx",
            "sourceId": "weather_demand_drivers",
            "metrics": [
                {"label": "RMB / 100 HKD", "field": "latest", "format": "number"},
                {"label": "MoM", "field": "period_change", "format": "percent", "signed": True},
                {"label": "YoY", "field": "year_change", "format": "percent", "signed": True},
            ],
        },
        {
            "id": "gold_card",
            "description": "Latest published SGE PM benchmark fixing; day and year-on-year movements.",
            "dataset": "kpi_gold",
            "sourceId": "sge_gold",
            "metrics": [
                {"label": "Gold PM (RMB/g)", "field": "latest", "format": "number"},
                {"label": "DoD", "field": "period_change", "format": "percent", "signed": True},
                {"label": "YoY", "field": "year_change", "format": "percent", "signed": True},
            ],
        },
    ]
    if median_pe_latest is not None:
        cards.append(
            {
                "id": "median_pe_card",
                "description": "Median trailing PE across the 11-name HK local-consumer watchlist.",
                "dataset": "kpi_median_pe",
                "sourceId": "hk_valuation",
                "metrics": [{"label": "Median PE (TTM)", "field": "latest", "format": "number"}],
            }
        )
    cards.append(
        {
            "id": "retail_card",
            "description": "All retail outlet value index; month and year-on-year movements.",
            "dataset": "kpi_retail",
            "sourceId": "cnsd_retail",
            "metrics": [
                {"label": "Retail sales index", "field": "latest", "format": "number"},
                {"label": "MoM", "field": "period_change", "format": "percent", "signed": True},
                {"label": "YoY", "field": "year_change", "format": "percent", "signed": True},
            ],
        }
    )
    cards.append(
        {
            "id": "restaurant_card",
            "description": "All-restaurants quarterly receipts; quarter and year-on-year movements.",
            "dataset": "kpi_restaurant",
            "sourceId": "censtatd_restaurant",
            "metrics": [
                {"label": "Receipts (HKD m)", "field": "latest", "format": "number"},
                {"label": "QoQ", "field": "period_change", "format": "percent", "signed": True},
                {"label": "YoY", "field": "year_change", "format": "percent", "signed": True},
            ],
        }
    )
    if not store_footprint.empty:
        cards.append(
            {
                "id": "store_footprint_card",
                "description": f"Total tracked store/branch count across {len(store_footprint)} HK-listed retail, jewellery, F&B, and consumer names.",
                "dataset": "kpi_store_footprint",
                "sourceId": "hk_store_footprint",
                "metrics": [{"label": "Total tracked locations", "field": "latest", "format": "number"}],
            }
        )

    charts = [
        {
            "id": "severe_weather_trend",
            "title": "Monthly severe weather disruption hours",
            "subtitle": "Total duration (hours per month) under Typhoon Signal 8+ and Red/Black Rainstorm warnings in Hong Kong.",
            "type": "bar",
            "intent": "trend",
            "dataset": "severe_weather_history",
            "sourceId": "weather_demand_drivers",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "total_disruption_hours", "type": "quantitative", "label": "Disruption Hours"},
            },
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 60,
        },
        *(
            [
                {
                    "id": "severe_weather_daily_trend",
                    "title": "Daily severe-weather disruption hours",
                    "subtitle": "Latest 36 months; warning intervals are split across midnight before daily aggregation.",
                    "type": "bar",
                    "intent": "trend",
                    "dataset": "severe_weather_daily",
                    "sourceId": "weather_demand_drivers",
                    "encodings": {
                        "x": {"field": "month", "type": "temporal", "label": "Month"},
                        "y": {"field": "hours", "type": "quantitative", "label": "Hours"},
                        "color": {"field": "warning_type", "type": "nominal", "label": "Warning type"},
                    },
                    "valueFormat": "number",
                    "layout": "full",
                    "maxRows": 720,
                }
            ]
            if not weather_daily.empty
            else []
        ),
        {
            "id": "immigration_trend",
            "title": "Cross-border passenger traffic (7-day MA, monthly average)",
            "subtitle": "Monthly average of daily 7-day MA: Northbound (HK resident land departures) vs Southbound (Mainland visitor arrivals).",
            "type": "line",
            "intent": "trend",
            "dataset": "immigration_trend_history",
            "sourceId": "immigration_flow",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "value", "type": "quantitative", "label": "Passengers / day (7d MA)"},
                "color": {"field": "flow_type", "type": "nominal", "label": "Flow direction"},
            },
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 180,
        },
        *(
            [
                {
                    "id": "immigration_checkpoint_trend",
                    "title": "Busiest immigration checkpoints — daily traffic",
                    "subtitle": "Top five checkpoint series by latest 7-day average; latest 90 days.",
                    "type": "line",
                    "intent": "trend",
                    "dataset": "immigration_checkpoint_history",
                    "sourceId": "immigration_flow",
                    "encodings": {
                        "x": {"field": "date", "type": "temporal", "label": "Date"},
                        "y": {"field": "value", "type": "quantitative", "label": "Passengers (7d MA)"},
                        "color": {"field": "series", "type": "nominal", "label": "Checkpoint / direction"},
                    },
                    "valueFormat": "number",
                    "layout": "full",
                    "maxRows": 500,
                }
            ]
            if not checkpoint_trend.empty
            else []
        ),
        {
            "id": "afcd_category_chart",
            "title": "AFCD wholesale prices by category",
            "subtitle": "Today's average wholesale price per kg, averaged across commodities in each category.",
            "type": "bar",
            "intent": "comparison",
            "dataset": "afcd_category_summary",
            "sourceId": "afcd_wholesale",
            "encodings": {
                "x": {"field": "category", "type": "nominal", "label": "Category"},
                "y": {"field": "avg_price_hkd_per_kg", "type": "quantitative", "label": "HKD / kg"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "afcd_category_trend",
            "title": "AFCD wholesale prices by category, over time",
            "subtitle": "Daily snapshots accumulated per pipeline run (AFCD only publishes today's readings). Legend: FW fish = Freshwater fish, Meat/Poultry = Livestock/Poultry, Marine = Marine fish, Veg = Vegetables.",
            "type": "line",
            "intent": "trend",
            "dataset": "afcd_category_trend_history",
            "sourceId": "afcd_wholesale",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "avg_price_hkd_per_kg", "type": "quantitative", "label": "HKD / kg"},
                "color": {"field": "category_short", "type": "nominal", "label": "Category"},
            },
            "valueFormat": "number",
            "layout": "half",
            "maxRows": 2000,
        },
        {
            "id": "gold_trend",
            "title": "Shanghai Gold Exchange PM benchmark (margin-cost reference)",
            "subtitle": (
                "Monthly average of the daily PM fixing in RMB per gram, last ~7 years; a secondary reference for "
                "HK gold-jewellery input costs, shown alongside AFCD wholesale food costs for margin context -- see "
                "the cross-border passenger traffic chart above for the featured consumer-demand signal."
            ),
            "type": "line",
            "intent": "trend",
            "dataset": "gold_history",
            "sourceId": "sge_gold",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "value", "type": "quantitative", "label": "RMB / gram"},
            },
            "valueFormat": "number",
            "layout": "half",
            "maxRows": 180,
        },
        {
            "id": "valuation_pe_chart",
            "title": "Watchlist trailing PE comparison",
            "subtitle": "Latest positive trailing PE per company; loss-making names are excluded from this view.",
            "type": "horizontalBar",
            "intent": "comparison",
            "dataset": "valuation_pe_chart",
            "sourceId": "hk_valuation",
            "encodings": {
                "x": {"field": "company_name", "type": "nominal", "label": "Company"},
                "y": {"field": "pe_ttm", "type": "quantitative", "label": "PE (TTM)"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
        {
            "id": "valuation_market_cap_trend",
            "title": "Consumer watchlist market-cap trend",
            "subtitle": "Latest 30 calendar days of source-provided daily observations; market capitalisation in HKD billions.",
            "type": "line",
            "intent": "trend",
            "dataset": "valuation_history",
            "sourceId": "hk_valuation",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "market_cap_hkd_b", "type": "quantitative", "label": "Market cap (HKD bn)"},
                "color": {"field": "company_name", "type": "nominal", "label": "Company"},
            },
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 400,
        },
        {
            "id": "retail_trend",
            "title": "Retail sales value index (all outlets)",
            "subtitle": "Monthly C&SD value index, full published history.",
            "type": "line",
            "intent": "trend",
            "dataset": "retail_history",
            "sourceId": "cnsd_retail",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Month"},
                "y": {"field": "value", "type": "quantitative", "label": "Value index"},
            },
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 120,
        },
        {
            "id": "retail_category_chart",
            "title": "Retail sales value index by category — YoY",
            "subtitle": "Latest published month; year-on-year change by mutually exclusive top-level outlet category.",
            "type": "horizontalBar",
            "intent": "comparison",
            "dataset": "retail_category_chart",
            "sourceId": "cnsd_retail",
            "encodings": {
                "x": {"field": "category", "type": "nominal", "label": "Category"},
                "y": {"field": "yoy_change", "type": "quantitative", "label": "YoY change"},
            },
            "valueFormat": "percent",
            "layout": "half",
        },
        {
            "id": "restaurant_trend",
            "title": "Restaurant receipts (all restaurants)",
            "subtitle": "Quarterly sector-wide receipts, HKD millions, full published history.",
            "type": "line",
            "intent": "trend",
            "dataset": "restaurant_history",
            "sourceId": "censtatd_restaurant",
            "encodings": {
                "x": {"field": "month", "type": "temporal", "label": "Quarter"},
                "y": {"field": "value", "type": "quantitative", "label": "HKD million"},
            },
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 80,
        },
        {
            "id": "restaurant_chart",
            "title": "Restaurant receipts by type — YoY",
            "subtitle": "Latest published quarter; year-on-year change in nominal receipts by restaurant type.",
            "type": "horizontalBar",
            "intent": "comparison",
            "dataset": "restaurant_chart",
            "sourceId": "censtatd_restaurant",
            "encodings": {
                "x": {"field": "sub_sector", "type": "nominal", "label": "Restaurant type"},
                "y": {"field": "yoy_change", "type": "quantitative", "label": "YoY change"},
            },
            "valueFormat": "percent",
            "layout": "half",
        },
    ]
    if not store_footprint.empty:
        charts.append(
            {
                "id": "store_footprint_chart",
                "title": "Tracked store/branch count by company",
                "subtitle": "Latest footprint snapshot per company (not a directly comparable unit -- see notes).",
                "type": "horizontalBar",
                "intent": "comparison",
                "dataset": "store_footprint_chart",
                "sourceId": "hk_store_footprint",
                "encodings": {
                    "x": {"field": "company", "type": "nominal", "label": "Company"},
                    "y": {"field": "total_stores", "type": "quantitative", "label": "Total stores"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    tables = [
        {
            "id": "severe_weather_log_table",
            "title": "Recent severe weather warning events log",
            "subtitle": "Start time, end time, and duration for recent Red/Black Rainstorm and Typhoon Signal 8+ warnings.",
            "dataset": "severe_weather_log",
            "sourceId": "weather_demand_drivers",
            "defaultSort": {"field": "start", "direction": "desc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "signal_name", "label": "Warning Signal", "type": "text"},
                {"field": "start", "label": "Start Time (HKT)", "type": "text"},
                {"field": "end", "label": "End Time (HKT)", "type": "text"},
                {"field": "duration_hours", "label": "Duration (Hours)", "format": "number"},
            ],
        },
        {
            "id": "afcd_commodity_table",
            "title": "AFCD wholesale price snapshot",
            "subtitle": "Same-day average price per commodity, HKD/kg (converted from the published HKD/catty rate).",
            "dataset": "afcd_commodity_table",
            "sourceId": "afcd_wholesale",
            "defaultSort": {"field": "avg_price_hkd_per_kg", "direction": "desc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "category", "label": "Category", "type": "text"},
                {"field": "commodity_name", "label": "Commodity", "type": "text"},
                {"field": "avg_price_hkd_per_kg", "label": "HKD/kg", "format": "number"},
                {"field": "num_readings", "label": "Readings", "format": "number"},
            ],
        },
        {
            "id": "valuation_table",
            "title": "Consumer watchlist valuation snapshot",
            "subtitle": "Latest trailing PE, PB, and market cap per company.",
            "dataset": "valuation_table",
            "sourceId": "hk_valuation",
            "defaultSort": {"field": "market_cap_hkd_b", "direction": "desc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "company_name", "label": "Company", "type": "text"},
                {"field": "ticker", "label": "Ticker", "type": "text"},
                {"field": "pe_ttm", "label": "PE (TTM)", "format": "number"},
                {"field": "pb_ratio", "label": "PB", "format": "number"},
                {"field": "market_cap_hkd_b", "label": "Market cap (HKD bn)", "format": "number"},
                {"field": "date", "label": "As of", "type": "date"},
            ],
        },
        {
            "id": "retail_category_table",
            "title": "Retail sales snapshot by category",
            "subtitle": "Latest published month; YoY is the primary comparison and MoM is shown as secondary context.",
            "dataset": "retail_category_snapshot",
            "sourceId": "cnsd_retail",
            "defaultSort": {"field": "sales_value_index", "direction": "desc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "category", "label": "Category", "type": "text"},
                {"field": "sales_value_index", "label": "Value index", "format": "number"},
                {"field": "sales_volume_index", "label": "Volume index", "format": "number"},
                {"field": "yoy_change", "label": "YoY", "format": "percent", "signed": True},
                {"field": "mom_change", "label": "MoM", "format": "percent", "signed": True},
                {"field": "date", "label": "As of", "type": "date"},
            ],
        },
        {
            "id": "restaurant_snapshot_table",
            "title": "Restaurant receipts snapshot by type",
            "subtitle": "Latest published quarter; YoY is primary and QoQ is secondary. Purchases are sector-wide only.",
            "dataset": "restaurant_snapshot",
            "sourceId": "censtatd_restaurant",
            "defaultSort": {"field": "total_receipts_hkd_m", "direction": "desc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "sub_sector", "label": "Restaurant type", "type": "text"},
                {"field": "total_receipts_hkd_m", "label": "Receipts (HKD m)", "format": "number"},
                {"field": "total_purchases_hkd_m", "label": "Purchases (HKD m)", "format": "number"},
                {"field": "receipts_value_index", "label": "Receipts value index", "format": "number"},
                {"field": "yoy_change", "label": "YoY", "format": "percent", "signed": True},
                {"field": "qoq_change", "label": "QoQ", "format": "percent", "signed": True},
                {"field": "date", "label": "As of", "type": "date"},
            ],
        },
        {
            "id": "source_health_table",
            "title": "Live source health",
            "subtitle": "Build-time checks for the measures rendered above.",
            "dataset": "source_health",
            "sourceId": "source_registry",
            "defaultSort": {"field": "latest_observation", "direction": "desc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "dataset", "label": "Dataset", "type": "text"},
                {"field": "status", "label": "Status", "type": "text"},
                {"field": "latest_observation", "label": "Latest", "type": "date"},
                {"field": "records", "label": "Rows", "format": "number"},
                {"field": "freshness", "label": "Freshness", "type": "text"},
                {"field": "notes", "label": "Notes", "type": "text"},
            ],
        },
        {
            "id": "active_signals_table",
            "title": "Active data signals",
            "subtitle": "Sources with a live, validated feed powering the cards, charts, and tables above.",
            "dataset": "source_coverage_active",
            "sourceId": "source_registry",
            "defaultSort": {"field": "source", "direction": "asc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "source", "label": "Source", "type": "text"},
                {"field": "dataset", "label": "Dataset", "type": "text"},
                {"field": "type", "label": "Type", "type": "text"},
                {"field": "status", "label": "Status", "type": "text"},
                {"field": "freshness", "label": "Freshness", "type": "text"},
                {"field": "notes", "label": "Scope / caveat", "type": "text"},
            ],
        },
        {
            "id": "coverage_table",
            "title": "Coverage and next ingestion targets",
            "subtitle": "Sources with a broken or unverified endpoint are tracked here rather than shown with placeholder values.",
            "dataset": "source_coverage_planned",
            "sourceId": "source_registry",
            "defaultSort": {"field": "status", "direction": "asc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "source", "label": "Source", "type": "text"},
                {"field": "dataset", "label": "Dataset", "type": "text"},
                {"field": "type", "label": "Type", "type": "text"},
                {"field": "status", "label": "Status", "type": "text"},
                {"field": "freshness", "label": "Freshness", "type": "text"},
                {"field": "notes", "label": "Scope / caveat", "type": "text"},
            ],
        },
    ]

    if pricewatch_archive:
        tables.append(
            {
                "id": "consumer_council_pricewatch_archive_table",
                "title": "Online Price Watch historical archive coverage",
                "subtitle": "Availability check only; no average-price trend is presented as an index.",
                "dataset": "consumer_council_pricewatch_archive",
                "sourceId": "consumer_council_pricewatch",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "first_observation", "label": "First month", "type": "text"},
                    {"field": "latest_observation", "label": "Latest month", "type": "text"},
                    {"field": "months", "label": "Months", "format": "number"},
                    {"field": "category_supermarket_aggregates", "label": "Monthly category-store aggregates", "format": "number"},
                    {"field": "categories", "label": "Categories", "format": "number"},
                    {"field": "supermarkets", "label": "Supermarket codes", "format": "number"},
                    {"field": "notes", "label": "Methodology caveat", "type": "text"},
                ],
            }
        )
    if pricewatch_index_rows:
        charts.append(
            {
                "id": "consumer_council_pricewatch_matched_index_chart",
                "title": "Online Price Watch matched-item supermarket price index",
                "subtitle": (
                    "The six longest source-code series (at least 12 linked months). Each supermarket starts at 100 in its "
                    "first available month; each link uses the equal-weight geometric mean of product-code price relatives "
                    "matched to the prior month. Promotions and pack-size changes are not adjusted."
                ),
                "type": "line",
                "intent": "trend",
                "dataset": "consumer_council_pricewatch_matched_index",
                "sourceId": "consumer_council_pricewatch",
                "encodings": {
                    "x": {"field": "year_month", "type": "temporal", "label": "Month"},
                    "y": {"field": "matched_item_index", "type": "quantitative", "label": "Index (first month = 100)"},
                    "color": {"field": "supermarket_code", "type": "nominal", "label": "Supermarket"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 1200,
            }
        )

    df_oil = _load_latest_normalized("consumer_council_oilprice_daily")
    df_oil_history = load_consumer_council_oilprice_history()
    df_complaints = _load_latest_normalized("consumer_council_complaints_by_sector")

    oil_rows = _records_json_safe(df_oil) if not df_oil.empty else []
    oil_history_rows: dict[str, list[dict[str, Any]]] = {}
    oil_wow_rows: list[dict[str, Any]] = []
    if not df_oil_history.empty:
        df_oil_history["date"] = pd.to_datetime(df_oil_history["date"], errors="coerce")
        for fuel_type, history in df_oil_history.groupby("fuel_type"):
            compact = history[history["date"] >= history["date"].max() - pd.Timedelta(days=365)].copy()
            compact["month"] = compact["date"].dt.strftime("%Y-%m")
            oil_history_rows[fuel_type] = _records(compact, ["date", "month", "company", "net_price_ex_duty_hkd"])
        ordered = df_oil_history.sort_values(["fuel_type", "company", "date"]).copy()
        ordered["prior_7d"] = ordered.groupby(["fuel_type", "company"])["net_price_ex_duty_hkd"].shift(7)
        latest = ordered.groupby(["fuel_type", "company"], as_index=False).tail(1).copy()
        latest["wow_change"] = latest["net_price_ex_duty_hkd"] / latest["prior_7d"] - 1
        oil_wow_rows = _records(latest, ["date", "company", "fuel_type", "net_price_ex_duty_hkd", "wow_change"])
    complaint_rows = _records_json_safe(df_complaints) if not df_complaints.empty else []

    if oil_rows:
        tables.append(
            {
                "id": "consumer_council_oilprice_table",
                "title": "Consumer Council Auto Fuel Pump Prices & Discounts",
                "subtitle": "Daily pump prices, walk-in discounts, and net prices per liter across Hong Kong oil majors.",
                "dataset": "consumer_council_oilprice",
                "sourceId": "consumer_council_oilprice",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "company", "label": "Oil Major", "type": "text"},
                    {"field": "fuel_type", "label": "Fuel Type", "type": "text"},
                    {"field": "walkin_discount_hkd", "label": "Walk-in Discount (HK$/L)", "format": "number"},
                    {"field": "discounted_price_hkd", "label": "Net Price (HK$/L)", "format": "number"},
                ],
            }
        )
        charts.append(
            {
                "id": "consumer_council_oilprice_chart",
                "title": "Auto Fuel Walk-in Discount Comparison (HK$/L)",
                "subtitle": "Walk-in discounts per liter across Caltex, PetroChina, Shell, Sinopec, and Esso.",
                "type": "bar",
                "dataset": "consumer_council_oilprice",
                "sourceId": "consumer_council_oilprice",
                "encodings": {
                    "x": {"field": "company", "type": "nominal", "label": "Oil Major"},
                    "y": {"field": "walkin_discount_hkd", "type": "quantitative", "label": "Discount (HK$/L)"},
                },
                "valueFormat": "number",
                "layout": "half",
            }
        )

    if oil_history_rows.get("regular-unleaded-gasoline"):
        charts.append(
            {
                "id": "consumer_council_oilprice_history_chart",
                "title": "Standard petrol net price trend",
                "subtitle": "Latest 12 months; daily net price after walk-in discount, excluding fuel duty.",
                "type": "line",
                "intent": "trend",
                "dataset": "consumer_council_oilprice_history_regular",
                "sourceId": "consumer_council_oilprice",
                "encodings": {
                    "x": {"field": "month", "type": "temporal", "label": "Month"},
                    "y": {"field": "net_price_ex_duty_hkd", "type": "quantitative", "label": "HKD / L (ex-duty)"},
                    "color": {"field": "company", "type": "nominal", "label": "Oil Major"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 1830,
            }
        )
        tables.append(
            {
                "id": "consumer_council_oilprice_wow_table",
                "title": "Auto fuel net price — latest 7-day movement",
                "subtitle": "Daily net price after walk-in discount, excluding fuel duty; compared with seven calendar days earlier.",
                "dataset": "consumer_council_oilprice_wow",
                "sourceId": "consumer_council_oilprice",
                "defaultSort": {"field": "wow_change", "direction": "desc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "company", "label": "Oil Major", "type": "text"},
                    {"field": "fuel_type", "label": "Fuel Type", "type": "text"},
                    {"field": "net_price_ex_duty_hkd", "label": "Net price (HK$/L, ex-duty)", "format": "number"},
                    {"field": "wow_change", "label": "7-day change", "format": "percent", "signed": True},
                    {"field": "date", "label": "As of", "type": "date"},
                ],
            }
        )
        charts.append(
            {
                "id": "consumer_council_oilprice_net_chart",
                "title": "Auto Fuel Net Price Comparison (HK$/L)",
                "subtitle": "Same-day net price-per-liter across Caltex, PetroChina, Shell, Sinopec, and Esso.",
                "type": "bar",
                "dataset": "consumer_council_oilprice",
                "sourceId": "consumer_council_oilprice",
                "encodings": {
                    "x": {"field": "company", "type": "nominal", "label": "Oil Major"},
                    "y": {"field": "discounted_price_hkd", "type": "quantitative", "label": "Net Price (HK$/L)"},
                },
                "valueFormat": "number",
                "layout": "half",
            }
        )

    # Build complaints table and chart data
    complaint_table_rows: list[dict[str, Any]] = []
    complaint_chart_rows: list[dict[str, Any]] = []
    complaint_history_chart_rows: list[dict[str, Any]] = []
    if complaint_rows:
        latest_periods = sorted(set(r["period"] for r in complaint_rows), reverse=True)
        latest_period = latest_periods[0] if latest_periods else ""
        period_rows = [r for r in complaint_rows if r["period"] == latest_period]
        period_rows.sort(key=lambda r: r["amount"], reverse=True)
        complaint_table_rows = period_rows
        # Top 10 categories for chart
        top10 = period_rows[:10]
        top10.reverse()  # horizontalBar renders bottom-to-top, so reverse for largest at top
        for r in top10:
            complaint_chart_rows.append({
                "category": r["category"],
                "amount": r["amount"],
            })
        # Only the top 2 (not top10) get a line in the history trend: with
        # long category names (e.g. "Food & Entertainment Services"), even 3
        # entries measured wider than the mobile (390px) viewport and
        # tripped the portable-chart delivery pipeline's horizontal-overflow
        # check (confirmed via direct DOM inspection at both 1440px and
        # 390px -- the legend's own bounding box, not any chart data, was
        # the overflowing element). The full top-10 breakdown is still
        # available in the snapshot bar chart and the history table below.
        latest_top_categories = {row["category"] for row in top10[-2:]}
        complaint_history_chart_rows = [
            {"period": row["period"], "category": row["category"], "amount": row["amount"]}
            for row in complaint_rows
            if row["category"] in latest_top_categories
        ]
        # Add table
        tables.append({
            "id": "consumer_council_complaints_table",
            "title": "Consumer Council Complaints by Category (Latest Period)",
            "subtitle": f"All complaint categories during {latest_period}, sorted by number of complaints.",
            "dataset": "consumer_council_complaints_table",
            "sourceId": "consumer_council_complaints",
            "defaultSort": {"field": "amount", "direction": "desc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "period", "label": "Period", "type": "text"},
                {"field": "category", "label": "Category", "type": "text"},
                {"field": "amount", "label": "Complaints", "format": "number"},
            ],
        })
        # Add chart
        charts.append({
            "id": "consumer_council_complaints_chart",
            "title": "Consumer Council Top Complaint Categories",
            "subtitle": f"Top 10 categories during {latest_period}, by number of complaints.",
            "type": "horizontalBar",
            "intent": "comparison",
            "dataset": "consumer_council_complaints_chart",
            "sourceId": "consumer_council_complaints",
            "encodings": {
                "x": {"field": "category", "type": "nominal", "label": "Category"},
                "y": {"field": "amount", "type": "quantitative", "label": "Complaints"},
            },
            "valueFormat": "number",
            "layout": "half",
        })
        charts.append({
            "id": "consumer_council_complaints_history_chart",
            "title": "Consumer Council complaint categories — available history",
            "subtitle": "Latest-period top 10 categories across every published source period. 2026 has no source month range, so no YoY percentage is inferred.",
            "type": "line",
            "intent": "trend",
            "dataset": "consumer_council_complaints_history_chart",
            "sourceId": "consumer_council_complaints",
            "encodings": {
                "x": {"field": "period", "type": "nominal", "label": "Published period"},
                "y": {"field": "amount", "type": "quantitative", "label": "Complaints"},
                "color": {"field": "category", "type": "nominal", "label": "Category"},
            },
            "valueFormat": "number",
            "layout": "full",
        })
        tables.append({
            "id": "consumer_council_complaints_history_table",
            "title": "Consumer Council complaints by category — all available periods",
            "subtitle": "Every category and period supplied by the official API; 2026 is not assumed to be a full-year total.",
            "dataset": "consumer_council_complaints",
            "sourceId": "consumer_council_complaints",
            "defaultSort": {"field": "amount", "direction": "desc"},
            "density": "dense",
            "layout": "full",
            "maxRows": 160,
            "columns": [
                {"field": "period", "label": "Published period", "type": "text"},
                {"field": "category", "label": "Category", "type": "text"},
                {"field": "amount", "label": "Complaints", "format": "number"},
            ],
        })

    # Build checkpoint breakdown table from immigration attrs
    checkpoint_rows: list[dict[str, Any]] = []
    try:
        raw_snapshot = immigration.attrs.get("latest_checkpoint_snapshot", [])
        if raw_snapshot:
            for entry in raw_snapshot:
                checkpoint_rows.append({
                    "control_point": entry.get("Control Point", ""),
                    "direction": entry.get("Arrival / Departure", ""),
                    "hk_residents": int(entry.get("Hong Kong Residents", 0)),
                    "mainland_visitors": int(entry.get("Mainland Visitors", 0)),
                    "other_visitors": int(entry.get("Other Visitors", 0)),
                    "total": int(entry.get("Total", 0)),
                })
            checkpoint_rows.sort(key=lambda r: (r["control_point"], r["direction"]))
            tables.append({
                "id": "immigration_checkpoint_table",
                "title": "Immigration Checkpoint Breakdown",
                "subtitle": f"Latest date: {immigration.attrs.get('latest_date', '—')}. Passenger clearance by control point and direction.",
                "dataset": "immigration_checkpoint_snapshot",
                "sourceId": "immigration_flow",
                "defaultSort": {"field": "control_point", "direction": "asc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "control_point", "label": "Control Point", "type": "text"},
                    {"field": "direction", "label": "Direction", "type": "text"},
                    {"field": "hk_residents", "label": "HK Residents", "format": "number"},
                    {"field": "mainland_visitors", "label": "Mainland Visitors", "format": "number"},
                    {"field": "other_visitors", "label": "Other Visitors", "format": "number"},
                    {"field": "total", "label": "Total", "format": "number"},
                ],
            })
    except Exception:
        pass

    if not store_footprint.empty:
        tables.append(
            {
                "id": "store_footprint_table",
                "title": "HK Retail/F&B Store-Count Snapshot",
                "subtitle": "Latest tracked store/branch count per company -- a footprint snapshot, not yet a trend (most companies have 1-2 dated snapshots so far).",
                "dataset": "store_footprint_snapshot",
                "sourceId": "hk_store_footprint",
                "defaultSort": {"field": "total_stores", "direction": "desc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "company", "label": "Company", "type": "text"},
                    {"field": "stock_code", "label": "Stock Code", "type": "text"},
                    {"field": "sector", "label": "Sector", "type": "text"},
                    {"field": "total_stores", "label": "Total Stores", "format": "number"},
                    {"field": "regions_tracked", "label": "Regions/Markets Tracked", "format": "number"},
                    {"field": "snapshot_date", "label": "Snapshot Date", "type": "date"},
                ],
            }
        )

    datasets["consumer_council_oilprice"] = oil_rows
    datasets["consumer_council_oilprice_history_regular"] = oil_history_rows.get("regular-unleaded-gasoline", [])
    datasets["consumer_council_oilprice_history_premium"] = oil_history_rows.get("premium-unleaded-gasoline", [])
    datasets["consumer_council_oilprice_wow"] = oil_wow_rows
    datasets["consumer_council_complaints"] = complaint_rows
    datasets["consumer_council_complaints_table"] = complaint_table_rows
    datasets["consumer_council_complaints_chart"] = complaint_chart_rows
    datasets["consumer_council_complaints_history_chart"] = complaint_history_chart_rows
    datasets["immigration_checkpoint_snapshot"] = checkpoint_rows

    artifact = {
        "surface": "dashboard",
        "manifest": {
            "version": 1,
            "surface": "dashboard",
            "title": "Hong Kong Local Consumer Monitor",
            "description": "A source-backed snapshot of cross-border passenger traffic, fresh-food wholesale prices, gold input costs, auto fuel pricing, and watchlist valuations for HK local-consumer names.",
            "generatedAt": generated_at,
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": manifest_sources,
            "blocks": [
                {
                    "id": "snapshot_context",
                    "type": "markdown",
                    "body": (
                        f"**Data snapshot:** `{snapshot_id}` · generated {generated_at}.  "
                        "This is a published snapshot, not a live connection. Includes official Consumer Council auto fuel calculator pricing."
                    ),
                },
                {"id": "market_pulse_1", "type": "metric-strip", "cardIds": ["northbound_card", "southbound_card", "weather_card"]},
                {"id": "market_pulse_2", "type": "metric-strip", "cardIds": (
                    ["fx_card", "gold_card"]
                    + (["median_pe_card"] if median_pe_latest is not None else [])
                )},
                {"id": "market_pulse_3", "type": "metric-strip", "cardIds": (
                    ["retail_card", "restaurant_card"]
                    + (["store_footprint_card"] if not store_footprint.empty else [])
                )},
                {"id": "immigration_chart", "type": "chart", "chartId": "immigration_trend"},
                *(
                    [
                        {
                            "id": "immigration_checkpoint_trend_chart",
                            "type": "chart",
                            "chartId": "immigration_checkpoint_trend",
                        }
                    ]
                    if not checkpoint_trend.empty
                    else []
                ),
                {"id": "weather_chart", "type": "chart", "chartId": "severe_weather_trend"},
                *(
                    [
                        {
                            "id": "weather_daily_chart",
                            "type": "chart",
                            "chartId": "severe_weather_daily_trend",
                        }
                    ]
                    if not weather_daily.empty
                    else []
                ),
                {"id": "weather_log_table", "type": "table", "tableId": "severe_weather_log_table"},
                {"id": "afcd_trend_chart", "type": "chart", "chartId": "afcd_category_chart", "layout": "half"},
                {"id": "afcd_category_trend_block", "type": "chart", "chartId": "afcd_category_trend", "layout": "half"},
                {"id": "gold_chart", "type": "chart", "chartId": "gold_trend", "layout": "half"},
                {"id": "valuation_chart", "type": "chart", "chartId": "valuation_pe_chart", "layout": "half"},
                {"id": "valuation_market_cap_chart", "type": "chart", "chartId": "valuation_market_cap_trend"},
                {"id": "oilprice_chart_block", "type": "chart", "chartId": "consumer_council_oilprice_chart", "layout": "half"},
                {"id": "oilprice_net_chart_block", "type": "chart", "chartId": "consumer_council_oilprice_net_chart", "layout": "half"},
                {"id": "oilprice_history_chart_block", "type": "chart", "chartId": "consumer_council_oilprice_history_chart"},
                {"id": "oilprice_table_block", "type": "table", "tableId": "consumer_council_oilprice_table"},
                {"id": "oilprice_wow_table_block", "type": "table", "tableId": "consumer_council_oilprice_wow_table"},
                {"id": "complaints_chart_block", "type": "chart", "chartId": "consumer_council_complaints_chart", "layout": "half"},
                {"id": "complaints_history_chart_block", "type": "chart", "chartId": "consumer_council_complaints_history_chart"},
                {"id": "complaints_table_block", "type": "table", "tableId": "consumer_council_complaints_table"},
                {"id": "complaints_history_table_block", "type": "table", "tableId": "consumer_council_complaints_history_table"},
                *(
                    [
                        {
                            "id": "immigration_checkpoint_table_block",
                            "type": "table",
                            "tableId": "immigration_checkpoint_table",
                        }
                    ]
                    if checkpoint_rows
                    else []
                ),
                {"id": "afcd_table", "type": "table", "tableId": "afcd_commodity_table"},
                {"id": "valuation_table_block", "type": "table", "tableId": "valuation_table"},
                {"id": "retail_trend_chart", "type": "chart", "chartId": "retail_trend"},
                {"id": "retail_category_chart_block", "type": "chart", "chartId": "retail_category_chart", "layout": "half"},
                {"id": "restaurant_chart_block", "type": "chart", "chartId": "restaurant_chart", "layout": "half"},
                {"id": "retail_category_table_block", "type": "table", "tableId": "retail_category_table"},
                {"id": "restaurant_trend_chart", "type": "chart", "chartId": "restaurant_trend"},
                {"id": "restaurant_snapshot_table_block", "type": "table", "tableId": "restaurant_snapshot_table"},
                {"id": "store_footprint_chart_block", "type": "chart", "chartId": "store_footprint_chart"},
                {"id": "store_footprint_table_block", "type": "table", "tableId": "store_footprint_table"},
                *(
                    [
                        {
                            "id": "consumer_council_pricewatch_matched_index_block",
                            "type": "chart",
                            "chartId": "consumer_council_pricewatch_matched_index_chart",
                        }
                    ]
                    if pricewatch_index_rows
                    else []
                ),
                *(
                    [
                        {
                            "id": "consumer_council_pricewatch_archive_block",
                            "type": "table",
                            "tableId": "consumer_council_pricewatch_archive_table",
                        }
                    ]
                    if pricewatch_archive
                    else []
                ),
                {"id": "source_health", "type": "table", "tableId": "source_health_table"},
                {"id": "active_signals", "type": "table", "tableId": "active_signals_table"},
                {"id": "coverage", "type": "table", "tableId": "coverage_table"},
                {
                    "id": "methodology",
                    "type": "markdown",
                    "body": (
                        "## Reading the dashboard\n\n"
                        "Cross-border passenger traffic (northbound/southbound) is the featured consumer-demand signal. "
                        "Gold is a secondary proxy for jewellery-sector input costs, not a stock-price forecast, and is shown "
                        "alongside AFCD wholesale food costs for margin context rather than as a standalone headline chart. "
                        "Wholesale food prices are a single-day snapshot, averaged across the markets AFCD samples that day; "
                        "the AFCD category trend chart accumulates one real observation per pipeline run (no historical "
                        "backfill exists for this feed), so it starts thin and grows over time. "
                        "Retail sales and restaurant receipts are official monthly/quarterly government indices, not real-time. "
                        "Online Price Watch uses a product-code matched, chain-linked supermarket indicator rather than "
                        "an assortment-sensitive average listed price; promotions and pack-size changes are not adjusted. "
                        "Active data signals lists sources already backing a live measure above; the coverage table tracks "
                        "sources whose endpoints are still broken or unverified. "
                        "No stock ranking, forecast, or investment recommendation is produced."
                    ),
                },
            ],
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": datasets,
        },
        "sources": sources,
        "package_info": {
            "originUrl": "https://asia-markets-dashboard.pages.dev/sectors/hk-local-consumer/",
            "snapshotId": snapshot_id,
            "dataAsOf": gold_kpi["observation_date"],
        },
    }
    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": artifact["package_info"]["dataAsOf"],
        "overall_status": "Healthy",
        "live_sources": len(health),
        "planned_sources": len(coverage_planned),
        "sources": coverage_active + coverage_planned,
        "attachment_filename": f"hk-local-consumer-dashboard-{now.date().isoformat()}.html",
    }
    return artifact, status


def fetch_live_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        _load_latest_normalized("sge_gold_benchmark_daily"),
        _load_latest_normalized("afcd_wholesale_food_prices_daily"),
        _load_latest_normalized("hk_consumer_ticker_valuations_daily"),
        _load_latest_normalized("cnsd_retail_sales_monthly"),
        _load_latest_normalized("censtatd_fast_food_survey_quarterly"),
        _load_latest_normalized("immigration_passenger_traffic_daily"),
        _load_latest_normalized("weather_demand_drivers_monthly"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Canonical artifact JSON output path")
    parser.add_argument("--status-output", type=Path, required=True, help="Compact Astro status JSON output path")
    args = parser.parse_args()

    gold, afcd, valuation, retail, restaurant, immigration, weather = fetch_live_frames()
    pricewatch_summary = load_historical_pricewatch_summary()
    pricewatch_index = load_historical_pricewatch_matched_index()
    artifact, status = build_artifact(
        gold,
        afcd,
        valuation,
        retail,
        restaurant,
        immigration,
        weather,
        raw_pricewatch_summary=pricewatch_summary,
        raw_pricewatch_index=pricewatch_index,
    )
    _atomic_json(args.output, artifact)
    _atomic_json(args.status_output, status)
    print(
        json.dumps(
            {
                "ok": True,
                "artifact": str(args.output),
                "status": str(args.status_output),
                "snapshot_id": status["snapshot_id"],
                "data_as_of": status["data_as_of"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
