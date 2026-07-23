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


PUBLIC_SOURCES = {
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

# Consumer Council's configured endpoint was later found to be
# guessed/incorrect (see src/hk_local_consumer/config.py comments) -- it
# returns empty, not fake data, and is surfaced here as Planned rather than
# fabricated.
# The classification variable's top-level breakdown (ccg "1" in CenStatD's
# table_620-67002_lang.json); the finer ~14-row "1.1" breakdown is fetched
# but not charted, to keep the comparison view readable.
TOP_LEVEL_RETAIL_CATEGORIES = [
    "Food, alcoholic drinks and tobacco (other than supermarkets)",
    "Supermarkets",
    "Fuels",
    "Clothing, footwear and allied products",
    "Consumer durable goods",
    "Department stores",
    "Jewellery, watches and clocks, and valuable gifts",
    "Other consumer goods",
]

PLANNED_COVERAGE = [
    {
        "source": "HK Consumer Council",
        "dataset": "Online Price Watch (personal care / cosmetics prices)",
        "type": "Measure",
        "status": "Planned",
        "latest_observation": "—",
        "records": 0,
        "freshness": "Endpoint returns no data",
        "notes": "Configured JSON/CSV endpoints do not resolve to real payloads; data.gov.hk listing needs re-verification before this can go live.",
    },
]


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
    return latest.sort_values("market_cap_hkd_b", ascending=False).reset_index(drop=True)


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


def _comparison_row(frame: pd.DataFrame, value_column: str, now: datetime) -> dict[str, Any]:
    latest = frame.iloc[-1]
    prior = frame.iloc[-2]
    target = pd.Timestamp(now.replace(tzinfo=None)) - pd.DateOffset(years=1)
    past = frame[frame["date"] <= target]
    yearly = past.iloc[-1] if not past.empty else frame.iloc[0]
    value = float(latest[value_column])
    prior_value = float(prior[value_column])
    yearly_value = float(yearly[value_column])
    return {
        "latest": round(value, 2),
        "period_change": round(value / prior_value - 1, 6),
        "year_change": round(value / yearly_value - 1, 6),
        "observation_date": latest["date"].strftime("%Y-%m-%d"),
    }


def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    selected = frame.loc[:, columns].copy()
    for column in selected.columns:
        if pd.api.types.is_datetime64_any_dtype(selected[column]):
            selected[column] = selected[column].dt.strftime("%Y-%m-%d")
    return json.loads(selected.to_json(orient="records", date_format="iso"))


def _stamp_sources(generated_at: str) -> list[dict[str, Any]]:
    result = []
    for source in PUBLIC_SOURCES.values():
        copy = json.loads(json.dumps(source))
        copy.setdefault("query", {})["executed_at"] = generated_at
        result.append(copy)
    return result


def build_artifact(
    raw_gold: pd.DataFrame,
    raw_afcd: pd.DataFrame,
    raw_valuation: pd.DataFrame,
    raw_retail: pd.DataFrame,
    raw_restaurant: pd.DataFrame,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    gold = _validate_gold(raw_gold, now)
    afcd = _validate_afcd(raw_afcd)
    valuation = _validate_valuation(raw_valuation, now)
    retail = _validate_retail_sales(raw_retail, now)
    restaurant = _validate_restaurant_survey(raw_restaurant, now)

    generated_at = now.isoformat().replace("+00:00", "Z")
    gold_kpi = _comparison_row(gold, "gold_benchmark_pm_rmb_gram", now)

    pe_values = valuation["pe_ttm"].dropna()
    median_pe_latest = float(pe_values.median()) if not pe_values.empty else None

    retail_total = retail[retail["category"] == "All retail outlet"].sort_values("date").reset_index(drop=True)
    retail_kpi = _comparison_row(retail_total, "sales_value_index", now)
    retail_latest_by_category = retail.sort_values("date").groupby("category", as_index=False).tail(1)
    retail_category_snapshot = retail_latest_by_category[
        retail_latest_by_category["category"].isin(TOP_LEVEL_RETAIL_CATEGORIES + ["All retail outlet"])
    ].sort_values("sales_value_index", ascending=False).reset_index(drop=True)
    retail_chart_rows = retail_category_snapshot[retail_category_snapshot["category"] != "All retail outlet"]

    restaurant_total = restaurant[restaurant["sub_sector"] == "All restaurants"].sort_values("date").reset_index(drop=True)
    restaurant_kpi = _comparison_row(restaurant_total, "total_receipts_hkd_m", now)
    restaurant_latest_by_type = restaurant.sort_values("date").groupby("sub_sector", as_index=False).tail(1)
    restaurant_snapshot = restaurant_latest_by_type.sort_values("total_receipts_hkd_m", ascending=False).reset_index(drop=True)
    restaurant_chart_rows = restaurant_snapshot[restaurant_snapshot["sub_sector"] != "All restaurants"]

    category_summary = (
        afcd.groupby("category", as_index=False)
        .agg(avg_price_hkd_per_kg=("avg_price_hkd_per_kg", "mean"), commodities=("commodity_name", "size"))
    )
    category_summary["avg_price_hkd_per_kg"] = category_summary["avg_price_hkd_per_kg"].round(2)
    category_summary = category_summary.sort_values("avg_price_hkd_per_kg", ascending=False).reset_index(drop=True)

    valuation_chart_rows = valuation.dropna(subset=["pe_ttm"])
    valuation_chart_rows = valuation_chart_rows[valuation_chart_rows["pe_ttm"] > 0]

    health = [
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
    coverage = health + PLANNED_COVERAGE

    # KPI comparisons use the full validated history; the chart itself is
    # windowed to the portable artifact's 2,000-row-per-dataset cap.
    gold_chart_window = gold.tail(1_800)

    datasets = {
        "kpi_gold": [gold_kpi],
        "kpi_median_pe": [{"latest": round(median_pe_latest, 2)}] if median_pe_latest is not None else [],
        "gold_history": _records(
            gold_chart_window.rename(columns={"gold_benchmark_pm_rmb_gram": "value"}), ["date", "value"]
        ),
        "afcd_category_summary": _records(category_summary, ["category", "avg_price_hkd_per_kg", "commodities"]),
        "afcd_commodity_table": _records(
            afcd, ["category", "commodity_name", "avg_price_hkd_per_kg", "num_readings"]
        ),
        "valuation_table": _records(
            valuation, ["ticker", "company_name", "pe_ttm", "pb_ratio", "market_cap_hkd_b", "date"]
        ),
        "valuation_pe_chart": _records(valuation_chart_rows, ["company_name", "pe_ttm"]),
        "kpi_retail": [retail_kpi],
        "retail_history": _records(
            retail_total.rename(columns={"sales_value_index": "value"}), ["date", "value"]
        ),
        "retail_category_snapshot": _records(
            retail_category_snapshot, ["category", "sales_value_index", "sales_volume_index", "date"]
        ),
        "retail_category_chart": _records(retail_chart_rows, ["category", "sales_value_index"]),
        "kpi_restaurant": [restaurant_kpi],
        "restaurant_history": _records(
            restaurant_total.rename(columns={"total_receipts_hkd_m": "value"}), ["date", "value"]
        ),
        "restaurant_snapshot": _records(
            restaurant_snapshot,
            ["sub_sector", "total_receipts_hkd_m", "total_purchases_hkd_m", "receipts_value_index", "date"],
        ),
        "restaurant_chart": _records(restaurant_chart_rows, ["sub_sector", "total_receipts_hkd_m"]),
        "source_health": health,
        "source_coverage": coverage,
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

    charts = [
        {
            "id": "gold_trend",
            "title": "Shanghai Gold Exchange PM benchmark",
            "subtitle": "Daily fixing in RMB per gram, last ~7 years; the primary reference for HK gold-jewellery input costs.",
            "type": "line",
            "intent": "trend",
            "dataset": "gold_history",
            "sourceId": "sge_gold",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Date"},
                "y": {"field": "value", "type": "quantitative", "label": "RMB / gram"},
            },
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 1_800,
        },
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
            "id": "retail_trend",
            "title": "Retail sales value index (all outlets)",
            "subtitle": "Monthly C&SD value index, full published history.",
            "type": "line",
            "intent": "trend",
            "dataset": "retail_history",
            "sourceId": "cnsd_retail",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Month"},
                "y": {"field": "value", "type": "quantitative", "label": "Value index"},
            },
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 400,
        },
        {
            "id": "retail_category_chart",
            "title": "Retail sales value index by category",
            "subtitle": "Latest published month, by type of retail outlet.",
            "type": "horizontalBar",
            "intent": "comparison",
            "dataset": "retail_category_chart",
            "sourceId": "cnsd_retail",
            "encodings": {
                "x": {"field": "category", "type": "nominal", "label": "Category"},
                "y": {"field": "sales_value_index", "type": "quantitative", "label": "Value index"},
            },
            "valueFormat": "number",
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
                "x": {"field": "date", "type": "temporal", "label": "Quarter"},
                "y": {"field": "value", "type": "quantitative", "label": "HKD million"},
            },
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 200,
        },
        {
            "id": "restaurant_chart",
            "title": "Restaurant receipts by type",
            "subtitle": "Latest published quarter, HKD millions.",
            "type": "horizontalBar",
            "intent": "comparison",
            "dataset": "restaurant_chart",
            "sourceId": "censtatd_restaurant",
            "encodings": {
                "x": {"field": "sub_sector", "type": "nominal", "label": "Restaurant type"},
                "y": {"field": "total_receipts_hkd_m", "type": "quantitative", "label": "HKD million"},
            },
            "valueFormat": "number",
            "layout": "half",
        },
    ]

    tables = [
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
            "subtitle": "Latest published month; value and volume index by type of retail outlet.",
            "dataset": "retail_category_snapshot",
            "sourceId": "cnsd_retail",
            "defaultSort": {"field": "sales_value_index", "direction": "desc"},
            "density": "dense",
            "layout": "full",
            "columns": [
                {"field": "category", "label": "Category", "type": "text"},
                {"field": "sales_value_index", "label": "Value index", "format": "number"},
                {"field": "sales_volume_index", "label": "Volume index", "format": "number"},
                {"field": "date", "label": "As of", "type": "date"},
            ],
        },
        {
            "id": "restaurant_snapshot_table",
            "title": "Restaurant receipts snapshot by type",
            "subtitle": "Latest published quarter; sector-wide purchases shown only for the All restaurants total.",
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
            "id": "coverage_table",
            "title": "Coverage and next ingestion targets",
            "subtitle": "Sources with a broken or unverified endpoint are tracked here rather than shown with placeholder values.",
            "dataset": "source_coverage",
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

    artifact = {
        "surface": "dashboard",
        "manifest": {
            "version": 1,
            "surface": "dashboard",
            "title": "Hong Kong Local Consumer Monitor",
            "description": "A source-backed snapshot of gold input costs, fresh-food wholesale prices, and watchlist valuations for HK local-consumer names.",
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
                        "This is a published snapshot, not a live connection. Consumer Council price-watch coverage "
                        "remains planned; it is not shown with placeholder values."
                    ),
                },
                {"id": "market_pulse", "type": "metric-strip", "cardIds": [card["id"] for card in cards]},
                {"id": "gold_chart", "type": "chart", "chartId": "gold_trend"},
                {"id": "afcd_chart", "type": "chart", "chartId": "afcd_category_chart", "layout": "half"},
                {"id": "valuation_chart", "type": "chart", "chartId": "valuation_pe_chart", "layout": "half"},
                {"id": "afcd_table", "type": "table", "tableId": "afcd_commodity_table"},
                {"id": "valuation_table_block", "type": "table", "tableId": "valuation_table"},
                {"id": "retail_trend_chart", "type": "chart", "chartId": "retail_trend"},
                {"id": "retail_category_chart_block", "type": "chart", "chartId": "retail_category_chart", "layout": "half"},
                {"id": "restaurant_chart_block", "type": "chart", "chartId": "restaurant_chart", "layout": "half"},
                {"id": "retail_category_table_block", "type": "table", "tableId": "retail_category_table"},
                {"id": "restaurant_trend_chart", "type": "chart", "chartId": "restaurant_trend"},
                {"id": "restaurant_snapshot_table_block", "type": "table", "tableId": "restaurant_snapshot_table"},
                {"id": "source_health", "type": "table", "tableId": "source_health_table"},
                {"id": "coverage", "type": "table", "tableId": "coverage_table"},
                {
                    "id": "methodology",
                    "type": "markdown",
                    "body": (
                        "## Reading the dashboard\n\n"
                        "Gold is a rough proxy for jewellery-sector input costs, not a stock-price forecast. "
                        "Wholesale food prices are a single-day snapshot, averaged across the markets AFCD samples that day. "
                        "Retail sales and restaurant receipts are official monthly/quarterly government indices, not real-time. "
                        "The coverage table distinguishes live measures from sources whose endpoints are still broken or unverified. "
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
        "planned_sources": len(PLANNED_COVERAGE),
        "sources": coverage,
        "attachment_filename": f"hk-local-consumer-dashboard-{now.date().isoformat()}.html",
    }
    return artifact, status


def fetch_live_frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        fetch_sge_gold_benchmark(),
        fetch_afcd_food_prices(),
        fetch_hk_consumer_valuations(),
        fetch_cnsd_retail_sales(),
        fetch_censtatd_restaurant_survey(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Canonical artifact JSON output path")
    parser.add_argument("--status-output", type=Path, required=True, help="Compact Astro status JSON output path")
    args = parser.parse_args()

    gold, afcd, valuation, retail, restaurant = fetch_live_frames()
    artifact, status = build_artifact(gold, afcd, valuation, retail, restaurant)
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
