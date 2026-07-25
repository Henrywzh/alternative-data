#!/usr/bin/env python3
"""Build the source-backed HK real-estate dashboard artifact.

The module keeps data acquisition separate from artifact construction so the
metric contract can be tested without network access.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.hk_real_estate.pipeline import SKIP_MIDLAND_ENV_VAR
from src.hk_real_estate.sources.centaline import fetch_centaline_ccl
from src.hk_real_estate.sources.midland import run_midland_ingestion
from src.hk_real_estate.sources.rvd import run_rvd_ingestion
from src.hk_real_estate.sources.hkma import fetch_hkma_residential_mortgage_survey
from src.common.cnsd_mdt import fetch_cnsd_table
from src.hk_real_estate.storage import load_latest_normalized


@dataclass(frozen=True)
class SeriesRule:
    label: str
    value_column: str
    frequency: str
    min_rows: int
    max_age_days: int
    source_id: str


SERIES_RULES = {
    "ccl": SeriesRule("Centaline CCL", "ccl_index", "Weekly", 1_000, 30, "centaline_ccl"),
    "mhpi": SeriesRule("Midland MHPI", "mhpi_overall", "Weekly", 400, 30, "midland_mhpi"),
    "confidence": SeriesRule(
        "Midland Confidence Index", "confidence_index", "Weekly", 300, 30, "midland_confidence"
    ),
    "rvd_price": SeriesRule("RVD Residential Price Index", "overall", "Monthly", 350, 120, "rvd_price"),
    "rvd_rent": SeriesRule("RVD Residential Rental Index", "overall", "Monthly", 350, 120, "rvd_rent"),
}


PUBLIC_SOURCES = {
    "hkma_mortgage": {
        "id": "hkma_mortgage",
        "label": "HKMA Residential Mortgage Survey",
        "href": "https://www.hkma.gov.hk/",
        "query": {
            "engine": "official HKMA API / open data",
            "url": "https://api.hkma.gov.hk/public/market-data-and-statistics/monthly-statistical-bulletin/banking/residential-mortgage-survey",
            "language": "JSON",
            "description": "Monthly mortgage loan approvals, LTV ratio, interest rate plan mix (HIBOR vs BLR), and delinquency rates.",
        },
    },
    "cnsd_construction": {
        "id": "cnsd_construction",
        "label": "C&SD Gross Value of Construction Works (Table 615-66001)",
        "href": "https://www.censtatd.gov.hk/",
        "query": {
            "engine": "official C&SD JSON API",
            "url": "https://www.censtatd.gov.hk/api/get.php?id=615-66001&lang=en&full_series=1",
            "language": "JSON",
            "description": "Quarterly gross value of construction works performed by main contractors.",
        },
    },
    "centaline_ccl": {
        "id": "centaline_ccl",
        "label": "Centaline City Leading Index (CCL)",
        "href": "https://hk.centanet.com/CCI/index",
        "query": {
            "engine": "first-party HTTP JSON",
            "url": "https://hk.centanet.com/CCI/api/Index/CCL",
            "language": "HTTP",
            "description": "Loads the explicit ccl.chartData date and index arrays from Centaline's application endpoint.",
            "metric_definitions": [
                "CCL latest is the most recent published weekly Centaline City Leading Index observation.",
                "Weekly and yearly movements are latest divided by the prior observation or latest observation on/before one year earlier, minus one.",
            ],
        },
    },
    "midland_mhpi": {
        "id": "midland_mhpi",
        "label": "Midland Realty Market Insight — MHPI",
        "href": "https://www.midland.com.hk/zh-hk/market-insight",
        "query": {
            "engine": "first-party page payload",
            "url": "https://www.midland.com.hk/zh-hk/market-insight",
            "language": "HTML/JSON",
            "description": "Loads the mrIndexWeekly series from the page's first-party Next.js payload.",
            "metric_definitions": [
                "MHPI latest is the most recent published overall weekly Midland Hong Kong Property Price Index observation.",
                "Weekly and yearly movements are latest divided by the prior observation or latest observation on/before one year earlier, minus one.",
            ],
        },
    },
    "midland_confidence": {
        "id": "midland_confidence",
        "label": "Midland Realty Market Insight — Confidence Index",
        "href": "https://www.midland.com.hk/zh-hk/market-insight",
        "query": {
            "engine": "first-party page payload",
            "url": "https://www.midland.com.hk/zh-hk/market-insight",
            "language": "HTML/JSON",
            "description": "Loads the confidenceIndex series from the page's first-party Next.js payload.",
            "metric_definitions": [
                "The confidence series is a supporting market-sentiment measure published by Midland Realty.",
            ],
        },
    },
    "rvd_price": {
        "id": "rvd_price",
        "label": "Rating and Valuation Department — Private Domestic Price Index",
        "href": "https://www.rvd.gov.hk/en/property_market_statistics/index.html",
        "query": {
            "engine": "official CSV",
            "url": "https://www.rvd.gov.hk/datagovhk/1.4M.csv",
            "language": "CSV",
            "description": "Loads the All Classes private domestic monthly price index and its remarks column.",
            "metric_definitions": [
                "RVD price latest is the All Classes monthly private domestic price index.",
                "Monthly and yearly movements are latest divided by the prior month or observation twelve months earlier, minus one.",
            ],
        },
    },
    "rvd_rent": {
        "id": "rvd_rent",
        "label": "Rating and Valuation Department — Private Domestic Rental Index",
        "href": "https://www.rvd.gov.hk/en/property_market_statistics/index.html",
        "query": {
            "engine": "official CSV",
            "url": "https://www.rvd.gov.hk/datagovhk/1.3M.csv",
            "language": "CSV",
            "description": "Loads the All Classes private domestic monthly rental index and its remarks column.",
            "metric_definitions": [
                "RVD rent latest is the All Classes monthly private domestic rental index.",
                "Monthly and yearly movements are latest divided by the prior month or observation twelve months earlier, minus one.",
            ],
        },
    },
    "cross_source": {
        "id": "cross_source",
        "label": "Cross-source normalized comparison",
        "query": {
            "engine": "pandas",
            "language": "Python",
            "description": "Resamples reviewed CCL, MHPI, RVD price, and RVD rent observations to month-end and rebases each series to 100 at its first non-null observation in the five-year window.",
            "metric_definitions": [
                "Rebased value equals observed index divided by the first available index in the displayed five-year window, multiplied by 100.",
            ],
            "tables_used": [
                "Centaline CCL first-party JSON",
                "Midland mrIndexWeekly page payload",
                "RVD 1.4M.csv",
                "RVD 1.3M.csv",
            ],
        },
    },
    "source_registry": {
        "id": "source_registry",
        "label": "HK real-estate dashboard source registry",
        "query": {
            "engine": "dashboard exporter",
            "language": "Python",
            "description": "Build-time validation results and declared coverage state for each dashboard source.",
            "tables_used": ["Validated core measure frames", "Declared future-source registry"],
        },
    },
}


PLANNED_COVERAGE = [
    {
        "source": "28Hse",
        "dataset": "EPI / ERI",
        "type": "Measure",
        "status": "Planned",
        "latest_observation": "—",
        "records": 0,
        "freshness": "Not ingested",
        "notes": "High-value index source; endpoint and history contract still require validation.",
    },
    {
        "source": "Agency transactions",
        "dataset": "Centaline / Midland / 28Hse transactions",
        "type": "Measure",
        "status": "Planned",
        "latest_observation": "—",
        "records": 0,
        "freshness": "Not ingested",
        "notes": "Target is a deduplicated near-real-time transaction activity measure.",
    },
    {
        "source": "SRPE",
        "dataset": "First-hand residential project documents",
        "type": "Catalog",
        "status": "Catalog only",
        "latest_observation": "—",
        "records": 0,
        "freshness": "Content parser pending",
        "notes": "Current discovery code does not yet extract sales, units, price lists, or absorption facts.",
    },
    {
        "source": "Land Registry",
        "dataset": "Registered sale and purchase facts",
        "type": "Catalog",
        "status": "Catalog only",
        "latest_observation": "—",
        "records": 0,
        "freshness": "Content parser pending",
        "notes": "Current code discovers releases; fact extraction and point-in-time semantics remain pending.",
    },
    {
        "source": "Buildings Department",
        "dataset": "Approvals, starts and occupation permits",
        "type": "Catalog",
        "status": "Catalog only",
        "latest_observation": "—",
        "records": 0,
        "freshness": "Content parser pending",
        "notes": "Monthly digest discovery exists; structured project facts are not yet extracted.",
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


def _normalized_frame(frame: pd.DataFrame, rule: SeriesRule, now: datetime) -> pd.DataFrame:
    missing = {"date", rule.value_column}.difference(frame.columns)
    if missing:
        raise ValueError(f"{rule.label}: missing columns {sorted(missing)}")
    result = frame.copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result[rule.value_column] = pd.to_numeric(result[rule.value_column], errors="coerce")
    if result[["date", rule.value_column]].isna().any().any():
        raise ValueError(f"{rule.label}: invalid date or value")
    if len(result) < rule.min_rows:
        raise ValueError(f"{rule.label}: expected at least {rule.min_rows} rows, received {len(result)}")
    if result["date"].duplicated().any():
        raise ValueError(f"{rule.label}: duplicate observation dates")
    if not result[rule.value_column].map(math.isfinite).all() or (result[rule.value_column] <= 0).any():
        raise ValueError(f"{rule.label}: values must be finite and positive")
    result = result.sort_values("date").reset_index(drop=True)
    latest = result["date"].iloc[-1].to_pydatetime().replace(tzinfo=timezone.utc)
    age_days = (now - latest).days
    if age_days < -7:
        raise ValueError(f"{rule.label}: latest observation is in the future")
    if age_days > rule.max_age_days:
        raise ValueError(f"{rule.label}: latest observation is stale by {age_days} days")
    return result


def _comparison_row(frame: pd.DataFrame, value_column: str, periods_per_year: int) -> dict[str, Any]:
    latest = frame.iloc[-1]
    prior = frame.iloc[-2]
    yearly = frame.iloc[-(periods_per_year + 1)] if len(frame) > periods_per_year else frame.iloc[0]
    value = float(latest[value_column])
    prior_value = float(prior[value_column])
    yearly_value = float(yearly[value_column])
    return {
        "latest": round(value, 3),
        "period_change": round(value / prior_value - 1, 6),
        "year_change": round(value / yearly_value - 1, 6),
        "observation_date": latest["date"].strftime("%Y-%m-%d"),
        "is_provisional": bool(latest.get("is_provisional", False)),
    }


def _records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    selected = frame.loc[:, columns].copy()
    for column in selected.columns:
        if pd.api.types.is_datetime64_any_dtype(selected[column]):
            selected[column] = selected[column].dt.strftime("%Y-%m-%d")
    return json.loads(selected.to_json(orient="records", date_format="iso"))


def _series_records(frame: pd.DataFrame, value_column: str) -> list[dict[str, Any]]:
    renamed = frame[["date", value_column]].rename(columns={value_column: "value"})
    return _records(renamed, ["date", "value"])


def _rebased_records(frames: dict[str, pd.DataFrame], now: datetime) -> list[dict[str, Any]]:
    start = pd.Timestamp(now.replace(tzinfo=None)) - pd.DateOffset(years=5)
    labels = {
        "ccl": "CCL",
        "mhpi": "MHPI",
        "rvd_price": "RVD Price",
        "rvd_rent": "RVD Rent",
    }
    rows: list[dict[str, Any]] = []
    for key, label in labels.items():
        rule = SERIES_RULES[key]
        series = frames[key].set_index("date")[rule.value_column].sort_index()
        series = series.loc[series.index >= start]
        monthly = series.resample("ME").last().dropna()
        if monthly.empty:
            raise ValueError(f"{rule.label}: no observations in five-year comparison window")
        rebased = monthly / float(monthly.iloc[0]) * 100
        rows.extend(
            {
                "date": index.strftime("%Y-%m-%d"),
                "series": label,
                "value": round(float(value), 4),
            }
            for index, value in rebased.items()
        )
    return sorted(rows, key=lambda row: (row["date"], row["series"]))


def _source_health(frames: dict[str, pd.DataFrame], now: datetime) -> list[dict[str, Any]]:
    rows = []
    for key in ("ccl", "mhpi", "confidence", "rvd_price", "rvd_rent"):
        rule = SERIES_RULES[key]
        frame = frames[key]
        latest = frame["date"].iloc[-1]
        age = (pd.Timestamp(now.replace(tzinfo=None)).normalize() - latest.normalize()).days
        provisional = bool(frame.iloc[-1].get("is_provisional", False))
        rows.append(
            {
                "source": PUBLIC_SOURCES[rule.source_id]["label"],
                "dataset": rule.label,
                "type": "Measure",
                "status": "Healthy",
                "latest_observation": latest.strftime("%Y-%m-%d"),
                "records": int(len(frame)),
                "freshness": f"{age}d old",
                "notes": "Latest observation is provisional." if provisional else "Latest observation is published without a provisional flag.",
            }
        )
    return rows


def _stamp_sources(generated_at: str) -> list[dict[str, Any]]:
    result = []
    for source in PUBLIC_SOURCES.values():
        copy = json.loads(json.dumps(source))
        copy.setdefault("query", {})["executed_at"] = generated_at
        result.append(copy)
    return result


def build_artifact(raw_frames: dict[str, pd.DataFrame], *, now: datetime | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    now = now or _utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    frames = {
        key: _normalized_frame(raw_frames[key], rule, now)
        for key, rule in SERIES_RULES.items()
    }

    kpis = {
        "ccl": _comparison_row(frames["ccl"], "ccl_index", 52),
        "mhpi": _comparison_row(frames["mhpi"], "mhpi_overall", 52),
        "rvd_price": _comparison_row(frames["rvd_price"], "overall", 12),
        "rvd_rent": _comparison_row(frames["rvd_rent"], "overall", 12),
    }
    if not frames["rvd_price"]["date"].equals(frames["rvd_rent"]["date"]):
        raise ValueError("RVD price and rent observation dates do not align")
    generated_at = now.isoformat().replace("+00:00", "Z")
    health = _source_health(frames, now)
    df_hkma = fetch_hkma_residential_mortgage_survey()
    df_cnsd = fetch_cnsd_table("615-66001")

    hkma_rows = []
    if not df_hkma.empty and "observation_date" in df_hkma.columns:
        for _, r in df_hkma.iterrows():
            obs_d = str(r["observation_date"])[:10]
            hibor_pct = r.get("interest_rate_hibor_pct")
            blr_pct = r.get("interest_rate_blr_pct")
            if pd.notna(hibor_pct):
                hkma_rows.append({"date": obs_d, "series": "HIBOR-based (%)", "value": float(hibor_pct)})
            if pd.notna(blr_pct):
                hkma_rows.append({"date": obs_d, "series": "Best Lending Rate (%)", "value": float(blr_pct)})

    cnsd_const_rows = []
    if not df_cnsd.empty and "period" in df_cnsd.columns and "value" in df_cnsd.columns:
        for _, r in df_cnsd.iterrows():
            if pd.notna(r.get("value")) and pd.notna(r.get("period")):
                cnsd_const_rows.append({
                    "date": str(r["period"]),
                    "value": float(r["value"]),
                    "unit": str(r.get("unit", "HK$ million")),
                })

    coverage = health + PLANNED_COVERAGE

    datasets = {
        "kpi_ccl": [kpis["ccl"]],
        "kpi_mhpi": [kpis["mhpi"]],
        "kpi_rvd_price": [kpis["rvd_price"]],
        "kpi_rvd_rent": [kpis["rvd_rent"]],
        "ccl_history": _series_records(frames["ccl"], "ccl_index"),
        "mhpi_history": _series_records(frames["mhpi"], "mhpi_overall"),
        "confidence_history": _series_records(frames["confidence"], "confidence_index"),
        "rvd_history": [
            {
                "date": price["date"].strftime("%Y-%m-%d"),
                "price": round(float(price["overall"]), 4),
                "rent": round(float(rent["overall"]), 4),
                "price_provisional": bool(price.get("is_provisional", False)),
                "rent_provisional": bool(rent.get("is_provisional", False)),
            }
            for (_, price), (_, rent) in zip(frames["rvd_price"].iterrows(), frames["rvd_rent"].iterrows())
        ],
        "rebased_five_year": _rebased_records(frames, now),
        "hkma_mortgage_rate_mix": hkma_rows,
        "cnsd_construction_value": cnsd_const_rows,
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
    # The portable artifact contract accepts a durable SQL-file provenance pointer
    # for widgets whose upstream is HTTP/CSV/Python rather than a warehouse query.
    # The richer first-party acquisition metadata remains in top-level `sources`.
    manifest_sources = [
        {
            **{key: source[key] for key in ("id", "label", "href") if key in source},
            "path": f"sources/{source['id']}.sql",
        }
        for source in sources
    ]

    cards = []
    for card_id, label, dataset, source_id, cadence in (
        ("ccl_card", "CCL", "kpi_ccl", "centaline_ccl", "WoW"),
        ("mhpi_card", "MHPI", "kpi_mhpi", "midland_mhpi", "WoW"),
        ("rvd_price_card", "RVD Price", "kpi_rvd_price", "rvd_price", "MoM"),
        ("rvd_rent_card", "RVD Rent", "kpi_rvd_rent", "rvd_rent", "MoM"),
    ):
        cards.append(
            {
                "id": card_id,
                "description": f"Latest published index; {cadence} and year-on-year movements.",
                "dataset": dataset,
                "sourceId": source_id,
                "metrics": [
                    {"label": label, "field": "latest", "format": "number"},
                    {"label": cadence, "field": "period_change", "format": "percent", "signed": True},
                    {"label": "YoY", "field": "year_change", "format": "percent", "signed": True},
                ],
            }
        )

    charts = [
        {
            "id": "ccl_trend",
            "title": "Centaline CCL",
            "subtitle": "Weekly publisher level; the latest point may precede the build date.",
            "type": "line",
            "intent": "trend",
            "dataset": "ccl_history",
            "sourceId": "centaline_ccl",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Week"},
                "y": {"field": "value", "type": "quantitative", "label": "Index"},
            },
            "valueFormat": "number",
            "layout": "half",
            "maxRows": 2_000,
        },
        {
            "id": "mhpi_trend",
            "title": "Midland MHPI",
            "subtitle": "Weekly overall index from Midland Market Insight.",
            "type": "line",
            "intent": "trend",
            "dataset": "mhpi_history",
            "sourceId": "midland_mhpi",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Week"},
                "y": {"field": "value", "type": "quantitative", "label": "Index"},
            },
            "valueFormat": "number",
            "layout": "half",
            "maxRows": 1_000,
        },
        {
            "id": "rvd_trend",
            "title": "Official residential price and rental indices",
            "subtitle": "RVD All Classes monthly indices; provisional flags are retained in the reviewed rows.",
            "type": "line",
            "intent": "comparison",
            "dataset": "rvd_history",
            "sourceId": "cross_source",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Month"},
                "y": {"field": "price", "type": "quantitative", "label": "Price index"},
                "tooltip": [{"field": "rent", "label": "Rent index", "format": "number"}],
            },
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 600,
            "comparisonContext": {"grain": "month", "unit": "publisher index level"},
        },
        {
            "id": "rvd_rent_trend",
            "title": "RVD rental index (companion view)",
            "subtitle": "Same monthly observations as the price chart, with rent plotted as the primary series.",
            "type": "line",
            "intent": "trend",
            "dataset": "rvd_history",
            "sourceId": "rvd_rent",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Month"},
                "y": {"field": "rent", "type": "quantitative", "label": "Rent index"},
                "tooltip": [{"field": "price", "label": "Price index", "format": "number"}],
            },
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 600,
        },
        {
            "id": "rebased_trend",
            "title": "Five-year cross-source movement",
            "subtitle": "Each series is rebased to 100 at its first available month in the window; levels are not directly comparable outside this view.",
            "type": "line",
            "intent": "comparison",
            "dataset": "rebased_five_year",
            "sourceId": "cross_source",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Month"},
                "y": {"field": "value", "type": "quantitative", "label": "Rebased index"},
                "color": {"field": "series", "type": "nominal", "label": "Series"},
            },
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 400,
            "comparisonContext": {"grain": "month", "normalization": "First available month = 100"},
        },
        {
            "id": "confidence_trend",
            "title": "Midland confidence index",
            "subtitle": "Supporting sentiment context; not a residential price measure.",
            "type": "area",
            "intent": "trend",
            "dataset": "confidence_history",
            "sourceId": "midland_confidence",
            "encodings": {
                "x": {"field": "date", "type": "temporal", "label": "Week"},
                "y": {"field": "value", "type": "quantitative", "label": "Confidence index"},
            },
            "valueFormat": "number",
            "layout": "full",
            "maxRows": 1_000,
        },
    ]

    if hkma_rows:
        charts.append(
            {
                "id": "hkma_mortgage_rate_mix_chart",
                "title": "HKMA Residential Mortgage Interest Rate Plan Mix (%)",
                "subtitle": "Percentage share of new mortgage approvals priced on HIBOR vs Best Lending Rate (Prime).",
                "type": "line",
                "intent": "trend",
                "dataset": "hkma_mortgage_rate_mix",
                "sourceId": "hkma_mortgage",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "% Share"},
                    "color": {"field": "series", "type": "nominal", "label": "Rate Plan"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    if cnsd_const_rows:
        charts.append(
            {
                "id": "cnsd_construction_value_chart",
                "title": "C&SD Gross Value of Construction Works (HK$ million)",
                "subtitle": "Quarterly value of construction works performed by main contractors (supply-side pipeline).",
                "type": "line",
                "intent": "trend",
                "dataset": "cnsd_construction_value",
                "sourceId": "cnsd_construction",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Quarter"},
                    "y": {"field": "value", "type": "quantitative", "label": "HK$ million"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    tables = [
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
            "subtitle": "Catalog discovery is not treated as a market measure.",
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

    blocks = [
        {
            "id": "snapshot_context",
            "type": "markdown",
            "body": (
                f"**Data snapshot:** `{snapshot_id}` · generated {generated_at}.  "
                "This is a published snapshot, not a live connection. RVD observations marked provisional may be revised."
            ),
        },
        {"id": "market_pulse", "type": "metric-strip", "cardIds": [card["id"] for card in cards]},
        {"id": "ccl_chart", "type": "chart", "chartId": "ccl_trend", "layout": "half"},
        {"id": "mhpi_chart", "type": "chart", "chartId": "mhpi_trend", "layout": "half"},
    ]
    if hkma_rows:
        blocks.append({"id": "hkma_mortgage_chart_block", "type": "chart", "chartId": "hkma_mortgage_rate_mix_chart"})
    if cnsd_const_rows:
        blocks.append({"id": "cnsd_construction_chart_block", "type": "chart", "chartId": "cnsd_construction_value_chart"})

    blocks.extend([
        {"id": "rvd_price_chart", "type": "chart", "chartId": "rvd_trend", "layout": "half"},
        {"id": "rvd_rent_chart", "type": "chart", "chartId": "rvd_rent_trend", "layout": "half"},
        {"id": "rebased_chart", "type": "chart", "chartId": "rebased_trend"},
        {"id": "confidence_chart", "type": "chart", "chartId": "confidence_trend"},
        {"id": "source_health_table", "type": "table", "tableId": "source_health_table"},
        {"id": "coverage_table", "type": "table", "tableId": "coverage_table"},
    ])

    artifact = {
        "surface": "dashboard",
        "manifest": {
            "version": 1,
            "surface": "dashboard",
            "title": "Hong Kong Real Estate Monitor",
            "description": "A source-backed snapshot of residential price, rent, and market confidence measures.",
            "generatedAt": generated_at,
            "cards": cards,
            "charts": charts,
            "tables": tables,
            "sources": manifest_sources,
            "blocks": blocks,
        },
        "snapshot": {
            "version": 1,
            "generatedAt": generated_at,
            "status": "ready",
            "datasets": datasets,
        },
        "sources": sources,
        "package_info": {
            "originUrl": "https://asia-markets-dashboard.pages.dev/sectors/hk-real-estate/",
            "snapshotId": snapshot_id,
            "dataAsOf": max(row["observation_date"] for row in kpis.values()),
        },
    }
    status = {
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "data_as_of": artifact["package_info"]["dataAsOf"],
        "overall_status": "Healthy",
        "live_sources": len(health),
        "planned_sources": len(PLANNED_COVERAGE),
        "provisional_series": sum(int(row["is_provisional"]) for row in kpis.values()),
        "sources": coverage,
        "attachment_filename": f"hk-real-estate-dashboard-{now.date().isoformat()}.html",
    }
    return artifact, status


def fetch_live_frames() -> dict[str, pd.DataFrame]:
    if os.environ.get(SKIP_MIDLAND_ENV_VAR):
        # Midland's WAF blocks GitHub Actions' datacenter IP range (confirmed
        # 403, reproducible from a residential IP, no known bypass). Fall
        # back to the last real snapshot rather than attempting a fetch
        # that's known to fail here and blocking the whole sector refresh.
        mhpi = load_latest_normalized("midland_mhpi_weekly")
        confidence = load_latest_normalized("midland_confidence_weekly")
    else:
        mhpi, confidence, _estates = run_midland_ingestion()
    rvd_price, rvd_rent = run_rvd_ingestion()
    return {
        "ccl": fetch_centaline_ccl(),
        "mhpi": mhpi,
        "confidence": confidence,
        "rvd_price": rvd_price,
        "rvd_rent": rvd_rent,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Canonical artifact JSON output path")
    parser.add_argument("--status-output", type=Path, required=True, help="Compact Astro status JSON output path")
    args = parser.parse_args()

    artifact, status = build_artifact(fetch_live_frames())
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
