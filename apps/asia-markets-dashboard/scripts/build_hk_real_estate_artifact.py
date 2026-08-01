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
from src.hk_real_estate.sources.centaline import fetch_centaline_ccl, fetch_centaline_index_bundle
from src.hk_real_estate.sources.midland import run_midland_ingestion
from src.hk_real_estate.sources.rvd import (
    fetch_rvd_office_rental_index,
    fetch_rvd_retail_rental_index,
    run_rvd_ingestion,
)
from src.hk_real_estate.sources.hkma import fetch_hkma_residential_mortgage_survey
from src.common.cnsd_mdt import fetch_cnsd_table
from src.hk_real_estate.storage import load_latest_normalized
from src.hk_real_estate.sources.epi import fetch_28hse_epi_eri
from src.hk_real_estate.sources.hse28 import fetch_28hse_new_projects, fetch_28hse_transaction_pilot
from src.hk_real_estate.sources.midland_transactions import fetch_midland_transaction_pilot
from src.hk_real_estate.sources.centaline_transactions import fetch_centaline_transaction_pilot
from src.hk_real_estate.sources.landreg import fetch_landreg_monthly_statistics
from src.hk_real_estate.sources.buildings_dept import fetch_buildings_dept_monthly_stats
from src.hk_real_estate.sources.bd_projects import fetch_bd_supply_leading_indicators
from src.hk_real_estate.sources.land_disposals import fetch_land_disposals
from src.hk_real_estate.dedup.transaction_dedup import deduplicate_agency_transactions


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

BD_HISTORY_SERIES_LABELS = {
    "Demolition Consents": "Md52 Demolition",
    "Plans Approved": "Md53 Plans",
    "Consent to Commence": "Md54 Consent",
    "Notice of Commencement Received": "Md55 Start",
    "Occupation Permits (OP) Issued": "Md56 Occupation",
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
    "censtatd_land_disposals": {
        "id": "censtatd_land_disposals",
        "label": "C&SD Table E704 — Disposals of Government Land",
        "href": "https://www.censtatd.gov.hk/en/data/stat_report/subject/100/report_index.json",
        "query": {
            "engine": "official C&SD publication archive",
            "url": "https://www.censtatd.gov.hk/en/data/stat_report/product/D7000004/att/D7000004.xlsx",
            "language": "XLSX",
            "description": "Quarterly area (sq. m.) and realised premium (HK$ million) of government land disposed via public auction/tender vs. private treaty grant, sourced from Lands Department.",
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
    "centaline_cci": {
        "id": "centaline_cci",
        "label": "Centaline CCI — Residential Price Index",
        "href": "https://hk.centanet.com/CCI/index",
        "query": {
            "engine": "first-party HTTP JSON",
            "url": "https://hk.centanet.com/CCI/api/Index/CCI",
            "language": "JSON",
            "description": "Monthly CCI history from the normalized Centaline index contract.",
        },
    },
    "centaline_cri": {
        "id": "centaline_cri",
        "label": "Centaline CRI — Residential Rental Index",
        "href": "https://hk.centanet.com/CCI/index",
        "query": {
            "engine": "first-party HTTP JSON",
            "url": "https://hk.centanet.com/CCI/api/Index/CRI",
            "language": "JSON",
            "description": "Monthly residential rental index and rental-yield history from the normalized Centaline contract.",
        },
    },
    "centaline_csi": {
        "id": "centaline_csi",
        "label": "Centaline CSI — Market Sentiment",
        "href": "https://hk.centanet.com/CCI/index",
        "query": {
            "engine": "first-party HTTP JSON",
            "url": "https://hk.centanet.com/CCI/api/Index/CSI",
            "language": "JSON",
            "description": "Weekly Centaline sentiment observations; not a transaction or price index.",
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
    "rvd_office": {
        "id": "rvd_office",
        "label": "Rating and Valuation Department — Office Rental Index",
        "href": "https://www.rvd.gov.hk/en/property_market_statistics/index.html",
        "query": {
            "engine": "official CSV",
            "url": "https://www.rvd.gov.hk/datagovhk/2.3M.csv",
            "language": "CSV",
            "description": "Monthly private office rental indices by grade, including official provisional flags.",
        },
    },
    "rvd_retail": {
        "id": "rvd_retail",
        "label": "Rating and Valuation Department — Retail Rental / Price Index",
        "href": "https://www.rvd.gov.hk/en/property_market_statistics/index.html",
        "query": {
            "engine": "official CSV",
            "url": "https://www.rvd.gov.hk/datagovhk/3.2M.csv",
            "language": "CSV",
            "description": "Monthly private retail rental and price indices with official provisional flags.",
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
    "hse28_epi_eri": {
        "id": "hse28_epi_eri",
        "label": "28Hse EPI / ERI Historical Index",
        "href": "https://www.28hse.com/epi/historical_data",
        "query": {
            "engine": "first-party form endpoint",
            "url": "https://www.28hse.com/epi/historical_data/doaction",
            "language": "HTML (embedded in a JSON envelope)",
            "description": "Weekly all-HK Estate Price Index (EPI) and Estate Rental Index (ERI) history, 2016-present.",
        },
    },
    "hse28_new_projects": {
        "id": "hse28_new_projects",
        "label": "28Hse New Properties Listing",
        "href": "https://www.28hse.com/new-properties",
        "query": {
            "engine": "first-party HTML",
            "url": "https://www.28hse.com/new-properties",
            "language": "HTML",
            "description": "Catalogue of newly launched residential projects with district and estimated unit count.",
        },
    },
    "agency_transactions": {
        "id": "agency_transactions",
        "label": "Deduplicated agency transaction feeds (28Hse / Midland / Centaline)",
        "query": {
            "engine": "pandas cross-source dedup",
            "language": "Python",
            "description": "Merges per-transaction records from 28Hse estate detail pages, Midland's building transaction API, and Centaline's transaction search API, then deduplicates on estate/floor/unit/date/price.",
            "tables_used": [
                "28Hse estate detail pages",
                "Midland data.midland.com.hk/info/v1/transactions/buildings",
                "Centaline hk.centanet.com/findproperty/api/Transaction/Search",
            ],
        },
    },
    "landreg_monthly": {
        "id": "landreg_monthly",
        "label": "Land Registry Monthly Statistics (JSON)",
        "href": "https://www.landreg.gov.hk/en/monthly/monthly.htm",
        "query": {
            "engine": "official first-party JSON",
            "url": "https://www.landreg.gov.hk/json/monthly_stat/monthly/t1.json",
            "language": "JSON",
            "description": "Monthly deeds-received-for-registration counts (Agreements for Sale & Purchase, Assignments, Mortgages) and the Agreements-for-Sale-and-Purchase (ASP) series.",
        },
    },
    "bd_monthly_digest": {
        "id": "bd_monthly_digest",
        "label": "Buildings Department Monthly Digest (Section 1 tables)",
        "href": "https://www.bd.gov.hk/en/whats-new/monthly-digests/index.html",
        "query": {
            "engine": "official XLS tables",
            "url": "https://www.bd.gov.hk/doc/en/whats-new/monthly-digests/Md11.xls",
            "language": "XLS",
            "description": "Scratch extraction of Buildings Department's monthly digest section-1 statistical tables (Md11-Md17).",
        },
    },
    "bd_supply": {
        "id": "bd_supply",
        "label": "Buildings Department Project Lifecycle (Demolition to Occupation)",
        "href": "https://www.bd.gov.hk/en/whats-new/monthly-digests/index.html",
        "query": {
            "engine": "official XLS tables",
            "url": "https://www.bd.gov.hk/en/whats-new/monthly-digests/index.html",
            "language": "XLS",
            "description": "Project-level Md52-Md56 files: demolition consents, plans approved, consent to commence, commencement notices, and occupation permits. Aggregated as a current-month snapshot by stage, region, and property category; Md52 publishes project counts but not units or floor area.",
            "tables_used": ["Md52.xls", "Md53.xls", "Md54.xls", "Md55.xls", "Md56.xls"],
        },
    },
    "bd_supply_history": {
        "id": "bd_supply_history",
        "label": "Buildings Department Historical Supply Pipeline",
        "href": "https://www.bd.gov.hk/en/whats-new/monthly-digests/index.html",
        "query": {
            "engine": "official monthly-digest PDF archive",
            "url": "https://www.bd.gov.hk/en/whats-new/monthly-digests/index.html",
            "language": "PDF",
            "description": "Historical monthly stage aggregates derived from Section 1 tables in the official BD Monthly Digest PDF archive. This is not project-level lifecycle linkage.",
            "tables_used": ["Table 1.2", "Table 1.3", "Table 1.4", "Table 1.5", "Table 1.6", "Table 1.7"],
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
        "source": "SRPE",
        "dataset": "First-hand residential project documents",
        "type": "Catalog",
        "status": "Catalog only",
        "latest_observation": "—",
        "records": 0,
        "freshness": "Content parser pending",
        "notes": "Current discovery code does not yet extract sales, units, price lists, or absorption facts.",
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


def _series_history(df: pd.DataFrame, series_label: str, value_column: str) -> list[dict[str, Any]]:
    """Long-format {date, series, value} rows for a multi-series line chart."""
    if df.empty or value_column not in df.columns:
        return []
    rows = []
    for _, row in df.iterrows():
        value = row.get(value_column)
        date = row.get("observation_date")
        if pd.isna(value) or pd.isna(date):
            continue
        date_str = str(date)[:10]
        rows.append(
            {
                "date": date_str,
                "series": series_label,
                "value": round(float(value), 4),
            }
        )
    return rows


def _series_records(frame: pd.DataFrame, value_column: str) -> list[dict[str, Any]]:
    renamed = frame[["date", value_column]].rename(columns={value_column: "value"})
    return _records(renamed, ["date", "value"])


def _index_history_rows(
    frame: pd.DataFrame,
    *,
    metric: str | None = None,
    series_label: str | None = None,
    series_column: str = "series_id",
    date_format: str = "%Y-%m",
) -> list[dict[str, Any]]:
    """Convert a normalized index family to bounded chart rows at source grain."""
    if frame.empty or not {"date", "index_value"}.issubset(frame.columns):
        return []
    selected = frame.copy()
    if metric is not None and "metric" in selected.columns:
        selected = selected[selected["metric"].eq(metric)]
    rows = []
    for _, row in selected.iterrows():
        value = pd.to_numeric(row.get("index_value"), errors="coerce")
        date = pd.to_datetime(row.get("date"), errors="coerce")
        if pd.isna(value) or pd.isna(date):
            continue
        label = series_label or str(row.get(series_column, "overall"))
        rows.append({"date": date.strftime(date_format), "series": label, "value": float(value)})
    return sorted(rows, key=lambda row: (row["series"], row["date"]))


def _commercial_history_rows(
    frame: pd.DataFrame,
    *,
    metric: str | None = None,
    label_prefix: str = "",
) -> list[dict[str, Any]]:
    """Convert RVD commercial long-form rows to chart rows."""
    if frame.empty or not {"date", "value", "segment", "metric"}.issubset(frame.columns):
        return []
    selected = frame.copy()
    if metric is not None:
        selected = selected[selected["metric"].eq(metric)]
    rows = []
    for _, row in selected.iterrows():
        value = pd.to_numeric(row.get("value"), errors="coerce")
        date = pd.to_datetime(row.get("date"), errors="coerce")
        if pd.isna(value) or pd.isna(date):
            continue
        segment = str(row.get("segment", "overall")).replace("_", " ").title()
        rows.append({
            # RVD commercial observations are monthly, not daily. Month
            # precision keeps the year visible without changing the cadence.
            "date": date.strftime("%Y-%m"),
            "series": f"{label_prefix}{segment}".strip(),
            "value": float(value),
            "is_provisional": bool(row.get("is_provisional", False)),
        })
    return sorted(rows, key=lambda row: (row["series"], row["date"]))


def _rebase_chart_rows(rows: list[dict[str, Any]], now: datetime, *, years: int = 5) -> list[dict[str, Any]]:
    """Rebase compatible index rows to 100 without mixing asset classes."""
    if not rows:
        return []
    frame = pd.DataFrame(rows)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    frame = frame.dropna(subset=["date", "value"])
    start = pd.Timestamp(now.replace(tzinfo=None)) - pd.DateOffset(years=years)
    output = []
    for series, group in frame.groupby("series"):
        monthly = group.set_index("date")["value"].sort_index()
        monthly = monthly.loc[monthly.index >= start].resample("ME").last().dropna()
        if monthly.empty or float(monthly.iloc[0]) == 0:
            continue
        for date, value in (monthly / float(monthly.iloc[0]) * 100).items():
            # This view is explicitly monthly; month-granularity labels render
            # as `Aug 2021` in the shared portable chart reader.
            output.append({"date": date.strftime("%Y-%m"), "series": series, "value": round(float(value), 4)})
    return sorted(output, key=lambda row: (row["date"], row["series"]))


def _safe_fetch(label: str, fetch_fn, *args, **kwargs) -> pd.DataFrame:
    """Call a live fetch function, returning an empty frame (not a crash) on failure.

    Unlike CCL/RVD/HKMA/CNSD (stable official APIs with strict validation via
    SERIES_RULES), these newer sources are first-party HTML/XLS scrapers that
    can legitimately break on a site change. A transient failure here should
    drop that one chart/table, not take down the whole real-estate artifact.
    """
    try:
        return fetch_fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001
        print(f"  [hk_real_estate] {label} fetch failed, continuing without it: {exc}", file=sys.stderr)
        return pd.DataFrame()


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
                "date": index.strftime("%Y-%m"),
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


def _new_source_health(
    frame: pd.DataFrame,
    *,
    source_id: str,
    dataset: str,
    now: datetime,
    note: str,
) -> dict[str, Any] | None:
    """Build a source-health row for an optional normalized tranche."""
    if frame.empty or "date" not in frame.columns:
        return None
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    if dates.empty:
        return None
    latest = dates.max()
    age = (pd.Timestamp(now.replace(tzinfo=None)).normalize() - latest.normalize()).days
    return {
        "source": PUBLIC_SOURCES[source_id]["label"],
        "dataset": dataset,
        "type": "Measure",
        "status": "Healthy",
        "latest_observation": latest.strftime("%Y-%m-%d"),
        "records": int(len(frame)),
        "freshness": f"{age}d old",
        "notes": note,
    }


def _stamp_sources(generated_at: str) -> list[dict[str, Any]]:
    result = []
    for source in PUBLIC_SOURCES.values():
        copy = json.loads(json.dumps(source))
        copy.setdefault("query", {})["executed_at"] = generated_at
        result.append(copy)
    return result


def build_artifact(
    raw_frames: dict[str, pd.DataFrame],
    raw_hkma: pd.DataFrame | None = None,
    raw_cnsd: pd.DataFrame | None = None,
    raw_epi_eri: pd.DataFrame | None = None,
    raw_new_projects: pd.DataFrame | None = None,
    raw_landreg: tuple[pd.DataFrame, pd.DataFrame] | None = None,
    raw_bd_monthly_stats: pd.DataFrame | None = None,
    raw_bd_supply: pd.DataFrame | None = None,
    raw_bd_supply_history: pd.DataFrame | None = None,
    raw_unified_tx: pd.DataFrame | None = None,
    raw_new_series: dict[str, pd.DataFrame] | None = None,
    raw_land_disposals: pd.DataFrame | None = None,
    *,
    now: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
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
    new_series = raw_new_series or {}
    df_cci = new_series.get("centaline_cci", pd.DataFrame())
    df_cri = new_series.get("centaline_cri", pd.DataFrame())
    df_cri_yield = new_series.get("centaline_cri_yield", pd.DataFrame())
    df_csi = new_series.get("centaline_csi", pd.DataFrame())
    df_rvd_office = new_series.get("rvd_office", pd.DataFrame())
    df_rvd_retail = new_series.get("rvd_retail", pd.DataFrame())

    # New normalized tranches are deliberately kept optional.  A clean
    # checkout can still build the legacy artifact while a local or scheduled
    # run that has materialised the tranche exposes the richer chart family.
    cci_rows = _index_history_rows(df_cci, metric="price_index", series_label="Overall")
    cri_rows = _index_history_rows(df_cri, metric="rental_index", series_label="Overall")
    cri_yield_rows = _index_history_rows(df_cri_yield, metric="rental_yield", series_label="Rental yield")
    # CSI is genuinely weekly. Keep the source date so several observations in
    # one month remain separate chart points; the packaging runtime supplies
    # the year in visible day/weekly labels.
    csi_rows = _index_history_rows(df_csi, metric="sentiment", date_format="%Y-%m-%d")
    rvd_office_rows = _commercial_history_rows(df_rvd_office, metric="rental_index")
    rvd_retail_rows = _commercial_history_rows(df_rvd_retail)

    df_hkma = raw_hkma if raw_hkma is not None else fetch_hkma_residential_mortgage_survey()
    df_cnsd = raw_cnsd if raw_cnsd is not None else fetch_cnsd_table("615-66001")

    hkma_rows = []
    hkma_ltv_rows: list[dict[str, Any]] = []
    hkma_credit_quality_rows: list[dict[str, Any]] = []
    hkma_activity_rows: list[dict[str, Any]] = []
    if not df_hkma.empty and "observation_date" in df_hkma.columns:
        for _, r in df_hkma.iterrows():
            # HKMA's mortgage survey is genuinely one observation per
            # calendar month -- using "YYYY-MM" (vs. "YYYY-MM-DD") is safe
            # here and gets the interactive chart renderer to always show
            # the year on its x-axis (it only omits year for day-precision
            # date strings, a behavior baked into the external chart
            # library, not something this repo can configure otherwise).
            obs_d = str(r["observation_date"])[:7]
            hibor_pct = r.get("hibor_pricing_pct_share")
            blr_pct = r.get("blr_pricing_pct_share")
            fixed_pct = r.get("fixed_pricing_pct_share")
            if pd.notna(hibor_pct):
                hkma_rows.append({"date": obs_d, "series": "HIBOR", "value": float(hibor_pct)})
            if pd.notna(blr_pct):
                hkma_rows.append({"date": obs_d, "series": "BLR (Prime)", "value": float(blr_pct)})
            if pd.notna(fixed_pct):
                hkma_rows.append({"date": obs_d, "series": "Fixed", "value": float(fixed_pct)})
            other_pct = r.get("other_pricing_pct_share")
            if pd.notna(other_pct):
                hkma_rows.append({"date": obs_d, "series": "Other", "value": float(other_pct)})
            # LTV single series
            ltv = r.get("average_ltv_ratio_pct")
            if pd.notna(ltv):
                hkma_ltv_rows.append({"date": obs_d, "series": "Average LTV (%)", "value": float(ltv)})
            # Credit quality: delinquency + rescheduled
            dq = r.get("delinquency_ratio_pct")
            if pd.notna(dq):
                hkma_credit_quality_rows.append({"date": obs_d, "series": "Delinquency Ratio (%)", "value": float(dq)})
            rs = r.get("rescheduled_loan_ratio_pct")
            if pd.notna(rs):
                hkma_credit_quality_rows.append({"date": obs_d, "series": "Rescheduled Loan Ratio (%)", "value": float(rs)})
            # Activity table row (latest period)
            hkma_activity_rows.append({
                "date": obs_d,
                "new_applications_count": float(r["new_applications_count"]) if pd.notna(r.get("new_applications_count")) else None,
                "approved_loans_amount_mhkd": float(r["approved_loans_amount_mhkd"]) if pd.notna(r.get("approved_loans_amount_mhkd")) else None,
                "approved_primary_presales_amount_mhkd": float(r["approved_primary_presales_amount_mhkd"]) if pd.notna(r.get("approved_primary_presales_amount_mhkd")) else None,
                "approved_secondary_amount_mhkd": float(r["approved_secondary_amount_mhkd"]) if pd.notna(r.get("approved_secondary_amount_mhkd")) else None,
                "approved_refinancing_amount_mhkd": float(r["approved_refinancing_amount_mhkd"]) if pd.notna(r.get("approved_refinancing_amount_mhkd")) else None,
                "drawn_down_amount_mhkd": float(r["drawn_down_amount_mhkd"]) if pd.notna(r.get("drawn_down_amount_mhkd")) else None,
            })
        hkma_credit_quality_rows.sort(key=lambda r: (r["series"], r["date"]))
        hkma_ltv_rows.sort(key=lambda r: r["date"])

    # Long-format {date, series, value} views of hkma_activity_rows for the
    # two charts below -- the table itself stays wide-format (one row per
    # month, one column per metric).
    hkma_applications_rows: list[dict[str, Any]] = [
        {"date": r["date"], "series": "New Applications", "value": r["new_applications_count"]}
        for r in hkma_activity_rows
        if r.get("new_applications_count") is not None
    ]
    # Capped at 3 series -- confirmed by direct testing that a 4th legend
    # entry on this chart pushes the portable artifact's interactive-shell
    # relayout past the verifier's mobile-viewport budget (this is a legend
    # entry *count* threshold, not a label-length one -- shortening all 5
    # labels to single words was tested and still failed at 390px). Primary
    # and Refinancing stay visible in the full activity table above instead.
    _HKMA_LOAN_AMOUNT_SERIES = {
        "approved_loans_amount_mhkd": "Approved Loans (Total)",
        "approved_secondary_amount_mhkd": "Secondary",
        "drawn_down_amount_mhkd": "Drawn Down",
    }
    hkma_loan_amount_rows: list[dict[str, Any]] = [
        {"date": r["date"], "series": series_label, "value": r[field]}
        for r in hkma_activity_rows
        for field, series_label in _HKMA_LOAN_AMOUNT_SERIES.items()
        if r.get(field) is not None
    ]
    hkma_loan_amount_rows.sort(key=lambda r: (r["series"], r["date"]))

    cnsd_const_rows = []
    if not df_cnsd.empty and "period" in df_cnsd.columns and "value" in df_cnsd.columns:
        # C&SD's table mixes multiple series in one flat frame: freq="Y" rows
        # use a bare 4-digit year period ("2000", the annual total) alongside
        # freq="Q" rows with a 6-digit YYYYMM period ("200003", quarter-end
        # month); and within freq="Q" there are two more axes -- variable
        # (GVCW_NOM nominal vs GVCW_REAL real/deflated) and unit (HK$ million
        # level vs "Year-on-year % change") -- four series total sharing the
        # same period values. Previously all of this was dumped into "date"
        # unfiltered and unparsed: the annual total sat at the same tick as
        # Q1 (a sawtooth/"duplicated time" artifact), 4 different-scale
        # values (a level in HK$m and a %-change figure) landed on the same
        # quarter, and since neither "2000" nor "200003" parses as a real
        # date, the axis fell back to formatting them as plain numbers ("2K",
        # "200K", ...). Filter to the single nominal-value-in-HK$-million
        # series the chart's title actually promises, and parse each YYYYMM
        # period into its real quarter-end date.
        quarterly = df_cnsd[
            (df_cnsd.get("freq") == "Q")
            & (df_cnsd.get("variable") == "GVCW_NOM")
            & (df_cnsd.get("unit") == "HK$ million")
        ] if {"freq", "variable", "unit"}.issubset(df_cnsd.columns) else df_cnsd.iloc[0:0]
        for _, r in quarterly.iterrows():
            period = str(r.get("period", ""))
            value = r.get("value")
            if pd.isna(value) or len(period) != 6 or not period.isdigit():
                continue
            year, month = int(period[:4]), int(period[4:6])
            quarter_end = pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)
            cnsd_const_rows.append({
                # One observation per calendar month -- "YYYY-MM" (see
                # obs_d above for why) rather than the month-end day.
                "date": quarter_end.strftime("%Y-%m"),
                "value": float(value),
                "unit": str(r.get("unit", "HK$ million")),
            })
        cnsd_const_rows.sort(key=lambda row: row["date"])

    df_land_disposals = raw_land_disposals if raw_land_disposals is not None else fetch_land_disposals()
    land_disposal_rows: list[dict[str, Any]] = []
    if not df_land_disposals.empty:
        # The raw table splits every method by district (Urban/New
        # Territories) and use category (Residential/Commercial/...); the
        # dashboard signal is total land supply released per method, so sum
        # the "total" use-category row across both districts rather than
        # exposing the full disaggregation. Two series (method), capped well
        # under the mobile-viewport chart series limit.
        _LAND_METHOD_LABELS = {
            "public_auction_tender": "Public Auction/Tender",
            "private_treaty_grant": "Private Treaty Grant",
        }
        totals = df_land_disposals[
            (df_land_disposals["use_category"] == "total") & (df_land_disposals["metric"] == "area_sqm")
        ]
        grouped = totals.groupby(["quarter", "method"], as_index=False)["value"].sum()
        for _, r in grouped.iterrows():
            land_disposal_rows.append(
                {
                    "date": str(r["quarter"])[:7],
                    "series": _LAND_METHOD_LABELS.get(r["method"], r["method"]),
                    "value": float(r["value"]),
                }
            )
        land_disposal_rows.sort(key=lambda row: (row["series"], row["date"]))

    # 28Hse EPI/ERI weekly index history -> two-series line chart.
    df_epi_eri = raw_epi_eri if raw_epi_eri is not None else _safe_fetch("28Hse EPI/ERI", fetch_28hse_epi_eri)
    epi_eri_rows: list[dict[str, Any]] = []
    if not df_epi_eri.empty and {"date", "index_type", "index_value"}.issubset(df_epi_eri.columns):
        for _, r in df_epi_eri.iterrows():
            if pd.notna(r.get("index_value")) and pd.notna(r.get("date")):
                epi_eri_rows.append(
                    {"date": str(r["date"])[:10], "series": str(r["index_type"]), "value": float(r["index_value"])}
                )
        epi_eri_rows.sort(key=lambda r: (r["series"], r["date"]))

    # Keep price and rent normalization separate.  Combining a rent index with
    # price indices in one rebased chart is numerically possible but visually
    # ambiguous, so the dashboard exposes two explicit comparison families.
    price_rebase_input = [
        {"date": row["date"], "series": "CCL", "value": row["value"]}
        for row in _series_records(frames["ccl"], "ccl_index")
    ]
    price_rebase_input.extend(
        {"date": row["date"], "series": "MHPI", "value": row["value"]}
        for row in _series_records(frames["mhpi"], "mhpi_overall")
    )
    price_rebase_input.extend({"date": row["date"], "series": "CCI", "value": row["value"]} for row in cci_rows)
    rent_rebase_input = []
    rent_rebase_input.extend(
        {"date": row["date"], "series": "CRI", "value": row["value"]}
        for row in cri_rows
    )
    for _, row in frames["rvd_rent"].iterrows():
        rent_rebase_input.append({
            "date": pd.to_datetime(row["date"]).strftime("%Y-%m-%d"),
            "series": "RVD Rent",
            "value": float(row["overall"]),
        })
    for row in epi_eri_rows:
        upper_series = row["series"].upper()
        if "EPI" in upper_series or "PRICE" in upper_series:
            price_rebase_input.append({"date": row["date"], "series": "EPI", "value": row["value"]})
        elif "ERI" in upper_series or "RENT" in upper_series:
            rent_rebase_input.append({"date": row["date"], "series": "ERI", "value": row["value"]})
    residential_price_rebased = _rebase_chart_rows(price_rebase_input, now)
    residential_rent_rebased = _rebase_chart_rows(rent_rebase_input, now)
    for health_row in (
        _new_source_health(df_cci, source_id="centaline_cci", dataset="Centaline CCI monthly", now=now, note="Normalized residential price index; CCI is not a sentiment measure."),
        _new_source_health(df_cri, source_id="centaline_cri", dataset="Centaline CRI monthly", now=now, note="Normalized residential rental index; rental-yield history is a companion dataset."),
        _new_source_health(df_csi, source_id="centaline_csi", dataset="Centaline CSI weekly", now=now, note="Normalized sentiment history; not a transaction or price series."),
        _new_source_health(df_rvd_office, source_id="rvd_office", dataset="RVD office rental monthly", now=now, note="Official grade-level rental index; provisional flags are retained."),
        _new_source_health(df_rvd_retail, source_id="rvd_retail", dataset="RVD retail monthly", now=now, note="Official retail rental/price indices; provisional flags are retained."),
    ):
        if health_row:
            health.append(health_row)

    # 28Hse new-project catalogue -> small supporting table.
    df_new_projects = (
        raw_new_projects if raw_new_projects is not None else _safe_fetch("28Hse new projects", fetch_28hse_new_projects)
    )
    new_project_rows: list[dict[str, Any]] = []
    if not df_new_projects.empty and "project_name" in df_new_projects.columns:
        for _, r in df_new_projects.iterrows():
            new_project_rows.append(
                {
                    "project_name": r.get("project_name"),
                    "location_district": r.get("location_district"),
                    "estimated_total_units": float(r["estimated_total_units"]) if pd.notna(r.get("estimated_total_units")) else None,
                    "estimated_move_in_year": int(r["estimated_move_in_year"]) if pd.notna(r.get("estimated_move_in_year")) else None,
                }
            )

    # Land Registry monthly facts + ASP series -> volume trend + ASP trend.
    if raw_landreg is not None:
        df_landreg_facts, df_landreg_asp = raw_landreg
    else:
        try:
            df_landreg_facts, df_landreg_asp = fetch_landreg_monthly_statistics()
        except Exception as exc:  # noqa: BLE001
            print(f"  [hk_real_estate] Land Registry fetch failed, continuing without it: {exc}", file=sys.stderr)
            df_landreg_facts, df_landreg_asp = pd.DataFrame(), pd.DataFrame()

    # A single chart carries both the "All Building Units ASP" and
    # "Residential Units ASP" series -- there used to be a second,
    # standalone "volume" chart sourced from the same all_building_units_asp
    # column under a different label, which was a pure duplicate of the
    # first series here and has been removed.
    landreg_asp_rows: list[dict[str, Any]] = []
    if not df_landreg_asp.empty and {"date", "all_building_units_asp"}.issubset(df_landreg_asp.columns):
        for _, r in df_landreg_asp.iterrows():
            date_s = str(r["date"])[:7]
            if pd.notna(r.get("all_building_units_asp")):
                landreg_asp_rows.append({"date": date_s, "series": "All Building Units ASP", "value": float(r["all_building_units_asp"])})
            if pd.notna(r.get("residential_units_asp")):
                landreg_asp_rows.append({"date": date_s, "series": "Residential Units ASP", "value": float(r["residential_units_asp"])})
    elif not df_landreg_facts.empty and {"date", "table_id", "statistic_name", "units"}.issubset(df_landreg_facts.columns):
        # Fallback for older snapshots that predate the archive-backed ASP
        # endpoints: the t1 facts table only carries the combined
        # "All Building Units" series, not a residential-only breakdown.
        _LANDREG_VOLUME_STATISTIC = "Total Number of Urban & New Territories deeds received for registration (ASP Building Units)"
        volume_slice = df_landreg_facts[
            (df_landreg_facts["statistic_name"] == _LANDREG_VOLUME_STATISTIC)
            & (df_landreg_facts["table_id"] == "t1")
            & (df_landreg_facts.get("comparison_type", "level") == "level")
        ]
        for _, r in volume_slice.iterrows():
            if pd.notna(r.get("units")):
                landreg_asp_rows.append({"date": str(r["date"])[:7], "series": "All Building Units ASP", "value": float(r["units"])})
    landreg_asp_rows.sort(key=lambda r: (r["series"], r["date"]))

    # Buildings Department: raw monthly digest scratch table (dense table --
    # numeric_values are still an unlabelled per-row array since per-column
    # names aren't parsed out yet, but the underlying table structure itself
    # IS stable: tables 1.1-1.7 have had an identical annual-summary-row +
    # Jan-Dec-breakdown layout back to 2021, confirmed against the live
    # files. See buildings_dept.py's _period_from_row/period_type for the
    # annual-vs-monthly row distinction.) + project-lifecycle supply
    # indicators (a genuine supply-pipeline snapshot, clean enough for a
    # comparison chart).
    df_bd_monthly_stats = (
        raw_bd_monthly_stats
        if raw_bd_monthly_stats is not None
        else _safe_fetch("Buildings Dept monthly stats", fetch_buildings_dept_monthly_stats)
    )
    bd_monthly_stats_rows: list[dict[str, Any]] = []
    if not df_bd_monthly_stats.empty and {"date", "table_id", "row_label", "numeric_values"}.issubset(df_bd_monthly_stats.columns):
        for _, r in df_bd_monthly_stats.iterrows():
            try:
                values = json.loads(r["numeric_values"]) if r.get("numeric_values") else []
            except (TypeError, json.JSONDecodeError):
                values = []
            bd_monthly_stats_rows.append(
                {
                    "date": str(r["date"])[:10],
                    "table_id": r.get("table_id"),
                    "row_label": r.get("row_label"),
                    "values": ", ".join(f"{v:,.0f}" for v in values) if values else None,
                }
            )

    df_bd_supply = (
        raw_bd_supply if raw_bd_supply is not None else _safe_fetch("BD supply leading indicators", fetch_bd_supply_leading_indicators)
    )
    bd_supply_rows: list[dict[str, Any]] = []
    bd_supply_table_rows: list[dict[str, Any]] = []
    if not df_bd_supply.empty and {"permit_stage", "region", "property_category", "total_domestic_units"}.issubset(df_bd_supply.columns):
        # Restrict this units chart to Domestic records. Stages/records that
        # do not publish unit counts (notably Md52 demolition consents) carry
        # null rather than zero and are therefore not shown as false zero bars.
        domestic_only = df_bd_supply[df_bd_supply["property_category"] == "Domestic"]
        for _, r in domestic_only.iterrows():
            if pd.notna(r.get("total_domestic_units")):
                bd_supply_rows.append(
                    {
                        "permit_stage": r.get("permit_stage"),
                        "region": r.get("region"),
                        "value": float(r["total_domestic_units"]),
                    }
                )
        for _, r in df_bd_supply.iterrows():
            bd_supply_table_rows.append(
                {
                    "permit_stage": r.get("permit_stage"),
                    "region": r.get("region"),
                    "property_category": r.get("property_category"),
                    "total_projects_count": int(r["total_projects_count"]) if pd.notna(r.get("total_projects_count")) else None,
                    "total_domestic_units": float(r["total_domestic_units"]) if pd.notna(r.get("total_domestic_units")) else None,
                    "total_usable_floor_area_sqm": float(r["total_usable_floor_area_sqm"]) if pd.notna(r.get("total_usable_floor_area_sqm")) else None,
                }
            )

    # Usable floor area by permit stage and property category -- unlike unit
    # count, non-domestic rows carry a genuine non-zero floor area, so this
    # (unlike bd_supply_pipeline_chart above) charts Domestic and
    # Non-domestic side by side rather than filtering Non-domestic out.
    bd_supply_floor_area_rows: list[dict[str, Any]] = []
    if not df_bd_supply.empty and {"permit_stage", "property_category", "total_usable_floor_area_sqm"}.issubset(df_bd_supply.columns):
        for _, r in df_bd_supply.iterrows():
            if pd.notna(r.get("total_usable_floor_area_sqm")):
                bd_supply_floor_area_rows.append(
                    {
                        "permit_stage": r.get("permit_stage"),
                        "property_category": r.get("property_category"),
                        "value": float(r["total_usable_floor_area_sqm"]),
                    }
                )

    # Archive-backed monthly stage aggregates.  These are deliberately a
    # separate time series from the current XLS project snapshot above: they
    # preserve the official Section-1 aggregate grain and make no claim that
    # a project was linked across Md52--Md56 stages.
    df_bd_supply_history = raw_bd_supply_history if raw_bd_supply_history is not None else pd.DataFrame()
    bd_supply_history_rows: list[dict[str, Any]] = []
    if not df_bd_supply_history.empty and {"observation_month", "permit_stage"}.issubset(df_bd_supply_history.columns):
        visible_history = df_bd_supply_history.copy()
        if "parser_confidence" in visible_history.columns:
            visible_history = visible_history[visible_history["parser_confidence"] == "HIGH"]
        if "revision_status" in visible_history.columns:
            visible_history = visible_history[visible_history["revision_status"] == "as_published"]
        # Keep the archive-backed source complete for research, but keep the
        # dashboard chart readable with a ten-year lookback. Anchor the cutoff
        # to the latest published month so stale upstream data does not make
        # the visible window shorter than intended.
        history_months = pd.to_datetime(visible_history["observation_month"], errors="coerce").dropna()
        if not history_months.empty:
            latest_history_month = history_months.max()
            cutoff_history_month = latest_history_month - pd.DateOffset(years=10)
            parsed_history_months = pd.to_datetime(visible_history["observation_month"], errors="coerce")
            visible_history = visible_history[parsed_history_months >= cutoff_history_month]
        for _, r in visible_history.iterrows():
            date = str(r["observation_month"])[:7]
            for column, metric in (
                ("total_domestic_units", "Domestic units"),
                ("total_projects_count", "Project / consent count"),
                ("total_domestic_ufa_sqm", "Domestic usable floor area (sqm)"),
            ):
                if column in visible_history.columns and pd.notna(r.get(column)):
                    bd_supply_history_rows.append(
                        {
                            "date": date,
                            "permit_stage": r.get("permit_stage"),
                            "series": BD_HISTORY_SERIES_LABELS.get(r.get("permit_stage"), r.get("permit_stage")),
                            "metric": metric,
                            "value": float(r[column]),
                        }
                    )
    bd_supply_history_rows.sort(key=lambda row: (row["metric"], row["permit_stage"], row["date"]))
    bd_supply_history_unit_rows = [row for row in bd_supply_history_rows if row["metric"] == "Domestic units"]
    # Capped at 3 series, not the 4 official count-bearing stages: the
    # portable-chart plugin's mobile-viewport verification fails on this
    # exact chart with 4 line series (empirically bisected, matching the
    # same 3-pass/4-fail threshold found for hkma_loan_amount_chart) and
    # passes again once it is 3. Occupation-permit counts are the stage
    # already covered (in units) by bd_supply_history_units_chart, so they
    # are the one dropped here rather than demolition/plans/consent, which
    # have no other chart representation.
    bd_supply_history_count_rows = [
        row
        for row in bd_supply_history_rows
        if row["metric"] == "Project / consent count" and row["permit_stage"] != "Occupation Permits (OP) Issued"
    ]

    # Deduplicated cross-agency transaction pulse (28Hse + Midland + Centaline).
    # Keep the artifact builder pure: live acquisition belongs in
    # fetch_live_frames(), and callers must pass the resulting frame explicitly.
    # This keeps snapshot fingerprints deterministic when an upstream source is
    # blocked or returns a transiently different fallback response.
    df_unified_tx = raw_unified_tx if raw_unified_tx is not None else pd.DataFrame()

    _TRANSACTION_PULSE_MAX_ROWS = 300
    transaction_pulse_rows: list[dict[str, Any]] = []
    if not df_unified_tx.empty and "transaction_date" in df_unified_tx.columns:
        # "Pulse" means recent activity, not a full history dump -- the combined
        # feed can run into the thousands once all three agencies are merged,
        # so cap to the most recent window rather than shipping it unbounded.
        pulse_slice = df_unified_tx.sort_values("transaction_date", ascending=False).head(_TRANSACTION_PULSE_MAX_ROWS)
        for _, r in pulse_slice.iterrows():
            transaction_pulse_rows.append(
                {
                    "transaction_date": str(r.get("transaction_date"))[:10] if pd.notna(r.get("transaction_date")) else None,
                    "estate_name": r.get("estate_name"),
                    "saleable_area_sqft": float(r["saleable_area_sqft"]) if pd.notna(r.get("saleable_area_sqft")) else None,
                    "price_hkd": float(r["price_hkd"]) if pd.notna(r.get("price_hkd")) else None,
                    "unit_price_hkd_sqft": float(r["unit_price_hkd_sqft"]) if pd.notna(r.get("unit_price_hkd_sqft")) else None,
                    "primary_source_agency": r.get("primary_source_agency"),
                    "matched_agency_count": int(r["matched_agency_count"]) if pd.notna(r.get("matched_agency_count")) else None,
                }
            )

    observed_agencies: set[str] = set()
    if not df_unified_tx.empty:
        for _, row in df_unified_tx.iterrows():
            raw_agencies = row.get("source_agencies")
            if pd.notna(raw_agencies):
                observed_agencies.update(
                    agency.strip() for agency in str(raw_agencies).split("|") if agency.strip()
                )
            elif pd.notna(row.get("primary_source_agency")):
                observed_agencies.add(str(row["primary_source_agency"]).strip())
    if len(observed_agencies) > 1:
        agency_pulse_subtitle = (
            "Deduplicated recent transactions across "
            + ", ".join(sorted(observed_agencies))
            + "."
        )
    elif len(observed_agencies) == 1:
        agency_pulse_subtitle = (
            "Recent transactions from only "
            + next(iter(observed_agencies))
            + "; no cross-agency overlap observed in this run."
        )
    else:
        agency_pulse_subtitle = "No agency transaction source returned usable rows in this run."

    # Midland top-estates by transaction volume -- a byproduct of the same
    # run_midland_ingestion() call already made for MHPI/confidence above, so
    # it's passed through raw_frames rather than fetched again separately.
    df_midland_estates = raw_frames.get("midland_estates", pd.DataFrame())
    midland_estate_rows: list[dict[str, Any]] = []
    if isinstance(df_midland_estates, pd.DataFrame) and not df_midland_estates.empty and "estate_name" in df_midland_estates.columns:
        sorted_estates = df_midland_estates.sort_values("transaction_count", ascending=False, na_position="last")
        for _, r in sorted_estates.iterrows():
            midland_estate_rows.append(
                {
                    "estate_name": r.get("estate_name"),
                    "region_name": r.get("region_name"),
                    "district_name": r.get("district_name"),
                    "transaction_count": float(r["transaction_count"]) if pd.notna(r.get("transaction_count")) else None,
                }
            )

    additional_coverage = []
    for label, dataset_label, rows_or_frame, source_label in (
        ("28Hse", "EPI / ERI", epi_eri_rows, "28Hse EPI / ERI Historical Index"),
        ("Agency transactions", "Centaline / Midland / 28Hse transactions", transaction_pulse_rows, "Deduplicated agency transaction feeds"),
        ("Land Registry", "Monthly facts + ASP series", landreg_asp_rows, "Land Registry Monthly Statistics (JSON)"),
        ("Buildings Department", "Monthly digest + project lifecycle", bd_monthly_stats_rows + bd_supply_table_rows, "Buildings Department Monthly Digest / Project Lifecycle"),
        ("Buildings Department history", "Md52-Md56 stage aggregates", bd_supply_history_rows, "Buildings Department Monthly Digest PDF archive (Section 1 aggregate tables)"),
    ):
        record_count = len(rows_or_frame)
        if not record_count:
            coverage_status = "No data this run"
            coverage_notes = f"{source_label}; live fetch returned no usable rows this run."
        elif label == "Agency transactions" and len(observed_agencies) < 2:
            coverage_status = "Partial"
            coverage_notes = (
                f"{source_label}; only {next(iter(observed_agencies), 'one agency')} (single agency) was observed, "
                "so cross-agency deduplication was not exercised in this run."
            )
        else:
            coverage_status = "Healthy"
            coverage_notes = f"{source_label}; see the chart/table above."
        additional_coverage.append(
            {
                "source": label,
                "dataset": dataset_label,
                "type": "Measure",
                "status": coverage_status,
                "latest_observation": "—",
                "records": record_count,
                "freshness": "Live at build time" if record_count else "Fetch returned no rows",
                "notes": coverage_notes,
            }
        )

    # New normalized Centaline/RVD feeds already contribute one complete row
    # each through `health` above (including observation date and row count).
    # Do not add aliases here: the coverage table is a source inventory, not a
    # list of every chart using that source.
    coverage = health + additional_coverage + PLANNED_COVERAGE

    datasets = {
        "kpi_ccl": [kpis["ccl"]],
        "kpi_mhpi": [kpis["mhpi"]],
        "kpi_rvd_price": [kpis["rvd_price"]],
        "kpi_rvd_rent": [kpis["rvd_rent"]],
        "ccl_history": _series_records(frames["ccl"], "ccl_index"),
        "mhpi_history": _series_records(frames["mhpi"], "mhpi_overall"),
        "confidence_history": _series_records(frames["confidence"], "confidence_index"),
        "cci_history": cci_rows,
        "cri_history": cri_rows,
        "cri_yield_history": cri_yield_rows,
        "csi_history": csi_rows,
        "rvd_office_history": rvd_office_rows,
        "rvd_retail_history": rvd_retail_rows,
        "rvd_history": [
            {
                # One observation per calendar month (see obs_d above).
                "date": price["date"].strftime("%Y-%m"),
                "price": round(float(price["overall"]), 4),
                "rent": round(float(rent["overall"]), 4),
                "price_provisional": bool(price.get("is_provisional", False)),
                "rent_provisional": bool(rent.get("is_provisional", False)),
            }
            for (_, price), (_, rent) in zip(frames["rvd_price"].iterrows(), frames["rvd_rent"].iterrows())
        ],
        "rebased_five_year": _rebased_records(frames, now),
        "residential_price_rebased": residential_price_rebased,
        "residential_rent_rebased": residential_rent_rebased,
        "hkma_mortgage_rate_mix": hkma_rows,
        "hkma_ltv_history": hkma_ltv_rows,
        "hkma_credit_quality_history": hkma_credit_quality_rows,
        "hkma_mortgage_activity": hkma_activity_rows,
        "hkma_applications_history": hkma_applications_rows,
        "hkma_loan_amount_history": hkma_loan_amount_rows,
        "cnsd_construction_value": cnsd_const_rows,
        "censtatd_land_disposals_area": land_disposal_rows,
        "epi_eri_history": epi_eri_rows,
        "hse28_new_projects": new_project_rows,
        "landreg_asp_history": landreg_asp_rows,
        "bd_monthly_stats": bd_monthly_stats_rows,
        "bd_supply_pipeline": bd_supply_rows,
        "bd_supply_detail": bd_supply_table_rows,
        "bd_supply_floor_area": bd_supply_floor_area_rows,
        "bd_supply_pipeline_history_units": bd_supply_history_unit_rows,
        "bd_supply_pipeline_history_counts": bd_supply_history_count_rows,
        "agency_transactions_pulse": transaction_pulse_rows,
        "midland_top_estates": midland_estate_rows,
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

    # Stage 1 chart family: keep price and rent as separate rebased views,
    # then expose source-owned raw histories below them for inspection.
    if residential_price_rebased:
        charts.append(
            {
                "id": "residential_price_rebased_chart",
                "title": "Residential Price Regime — Five-year comparison",
                "subtitle": "CCL, MHPI, CCI and EPI are each rebased to 100 at the first available month; use the raw source charts for publisher levels.",
                "type": "line",
                "intent": "comparison",
                "dataset": "residential_price_rebased",
                "sourceId": "cross_source",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "Rebased price index"},
                    "color": {"field": "series", "type": "nominal", "label": "Series"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 500,
                "comparisonContext": {"grain": "month", "normalization": "First available month = 100", "assetClass": "residential price"},
            }
        )
    if residential_rent_rebased:
        charts.append(
            {
                "id": "residential_rent_rebased_chart",
                "title": "Residential Rent Regime — Five-year comparison",
                "subtitle": "CRI, RVD rent and ERI are rebased separately from prices; raw levels and rental yield remain available below.",
                "type": "line",
                "intent": "comparison",
                "dataset": "residential_rent_rebased",
                "sourceId": "cross_source",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "Rebased rent index"},
                    "color": {"field": "series", "type": "nominal", "label": "Series"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 500,
                "comparisonContext": {"grain": "month", "normalization": "First available month = 100", "assetClass": "residential rent"},
            }
        )
    if cci_rows:
        charts.append(
            {
                "id": "cci_trend",
                "title": "Centaline CCI — Residential price index",
                "subtitle": "Monthly overall CCI history; CCI is a price index, not a sentiment measure.",
                "type": "line",
                "intent": "trend",
                "dataset": "cci_history",
                "sourceId": "centaline_cci",
                "encodings": {"x": {"field": "date", "type": "temporal", "label": "Month"}, "y": {"field": "value", "type": "quantitative", "label": "Index"}},
                "valueFormat": "number",
                "layout": "half",
                "maxRows": 500,
            }
        )
    if cri_rows:
        charts.append(
            {
                "id": "cri_trend",
                "title": "Centaline CRI — Residential rental index",
                "subtitle": "Monthly overall CRI history from the normalized Centaline contract.",
                "type": "line",
                "intent": "trend",
                "dataset": "cri_history",
                "sourceId": "centaline_cri",
                "encodings": {"x": {"field": "date", "type": "temporal", "label": "Month"}, "y": {"field": "value", "type": "quantitative", "label": "Rental index"}},
                "valueFormat": "number",
                "layout": "half",
                "maxRows": 500,
            }
        )
    if cri_yield_rows:
        charts.append(
            {
                "id": "cri_yield_trend",
                "title": "Centaline CRI rental yield",
                "subtitle": "Monthly rental-yield companion series; this is not a rent level.",
                "type": "line",
                "intent": "trend",
                "dataset": "cri_yield_history",
                "sourceId": "centaline_cri",
                "encodings": {"x": {"field": "date", "type": "temporal", "label": "Month"}, "y": {"field": "value", "type": "quantitative", "label": "Yield (%)"}},
                "valueFormat": "number",
                "layout": "half",
                "maxRows": 500,
            }
        )
    if csi_rows:
        charts.append(
            {
                "id": "csi_trend",
                "title": "Centaline CSI — Market sentiment",
                "subtitle": "Weekly sentiment history; the historical payload currently exposes residential price/rent sentiment fields.",
                "type": "line",
                "intent": "trend",
                "dataset": "csi_history",
                "sourceId": "centaline_csi",
                "encodings": {"x": {"field": "date", "type": "temporal", "label": "Week"}, "y": {"field": "value", "type": "quantitative", "label": "Sentiment index"}, "color": {"field": "series", "type": "nominal", "label": "Measure"}},
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 1_500,
            }
        )
    if rvd_office_rows:
        charts.append(
            {
                "id": "rvd_office_trend",
                "title": "Commercial Property — RVD office rental",
                "subtitle": "Monthly private office rental indices by grade; provisional observations remain flagged in the dataset.",
                "type": "line",
                "intent": "comparison",
                "dataset": "rvd_office_history",
                "sourceId": "rvd_office",
                "encodings": {"x": {"field": "date", "type": "temporal", "label": "Month"}, "y": {"field": "value", "type": "quantitative", "label": "Rental index"}, "color": {"field": "series", "type": "nominal", "label": "Grade"}},
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 2_000,
            }
        )
    if rvd_retail_rows:
        charts.append(
            {
                "id": "rvd_retail_trend",
                "title": "Commercial Property — RVD retail rental / price",
                "subtitle": "Monthly private retail rental and price indices; provisional observations remain flagged in the dataset.",
                "type": "line",
                "intent": "comparison",
                "dataset": "rvd_retail_history",
                "sourceId": "rvd_retail",
                "encodings": {"x": {"field": "date", "type": "temporal", "label": "Month"}, "y": {"field": "value", "type": "quantitative", "label": "Index"}, "color": {"field": "series", "type": "nominal", "label": "Measure / segment"}},
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 1_000,
            }
        )

    if hkma_rows:
        charts.append(
            {
                "id": "hkma_mortgage_rate_mix_chart",
                "title": "HKMA Mortgage Rate Plan Mix (%)",
                "subtitle": "Percentage share of new mortgage approvals by HIBOR, Best Lending Rate, fixed-rate, and other pricing plans.",
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

    if land_disposal_rows:
        charts.append(
            {
                "id": "censtatd_land_disposals_chart",
                "title": "Government Land Disposed by Method (sq. m.)",
                "subtitle": "Quarterly land area released via public auction/tender vs. private treaty grant (supply-side pipeline).",
                "type": "line",
                "intent": "trend",
                "dataset": "censtatd_land_disposals_area",
                "sourceId": "censtatd_land_disposals",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Quarter"},
                    "y": {"field": "value", "type": "quantitative", "label": "Area (sq. m.)"},
                    "color": {"field": "series", "type": "nominal", "label": "Method"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    if hkma_ltv_rows:
        charts.append(
            {
                "id": "hkma_ltv_chart",
                "title": "HKMA Average LTV Ratio (%)",
                "subtitle": "Average loan-to-value ratio for new mortgage approvals.",
                "type": "line",
                "intent": "trend",
                "dataset": "hkma_ltv_history",
                "sourceId": "hkma_mortgage",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "LTV (%)"},
                },
                "valueFormat": "number",
                "layout": "half",
            }
        )

    if hkma_credit_quality_rows:
        charts.append(
            {
                "id": "hkma_credit_quality_chart",
                "title": "HKMA Mortgage Credit Quality (%)",
                "subtitle": "Delinquency and rescheduled loan ratios -- a genuine credit-cycle risk indicator.",
                "type": "line",
                "intent": "comparison",
                "dataset": "hkma_credit_quality_history",
                "sourceId": "hkma_mortgage",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "%"},
                    "color": {"field": "series", "type": "nominal", "label": "Metric"},
                },
                "valueFormat": "number",
                "layout": "half",
            }
        )

    if hkma_applications_rows:
        charts.append(
            {
                "id": "hkma_applications_chart",
                "title": "HKMA New Mortgage Applications",
                "subtitle": "Monthly count of new residential mortgage loan applications.",
                "type": "line",
                "intent": "trend",
                "dataset": "hkma_applications_history",
                "sourceId": "hkma_mortgage",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "Applications"},
                },
                "valueFormat": "number",
                "layout": "half",
            }
        )

    if hkma_loan_amount_rows:
        charts.append(
            {
                "id": "hkma_loan_amount_chart",
                "title": "HKMA Mortgage Loan Amounts (HK$m)",
                "subtitle": "Total approved loans, the secondary-market share, and drawn-down amount, monthly. Primary/presales and refinancing breakdowns are in the table below.",
                "type": "line",
                "intent": "comparison",
                "dataset": "hkma_loan_amount_history",
                "sourceId": "hkma_mortgage",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "HK$m"},
                    "color": {"field": "series", "type": "nominal", "label": "Category"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    if epi_eri_rows:
        charts.append(
            {
                "id": "epi_eri_chart",
                "title": "28Hse Estate Price & Rental Index (EPI / ERI)",
                "subtitle": "Weekly all-HK estate price and rental indices, 2016-present.",
                "type": "line",
                "intent": "comparison",
                "dataset": "epi_eri_history",
                "sourceId": "hse28_epi_eri",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Week"},
                    "y": {"field": "value", "type": "quantitative", "label": "Index"},
                    "color": {"field": "series", "type": "nominal", "label": "Index"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    if landreg_asp_rows:
        charts.append(
            {
                "id": "landreg_asp_chart",
                "title": "Land Registry — Agreements for Sale & Purchase (ASP)",
                "subtitle": "Monthly ASP counts, all building units vs residential units only.",
                "type": "line",
                "intent": "comparison",
                "dataset": "landreg_asp_history",
                "sourceId": "landreg_monthly",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "ASP count"},
                    "color": {"field": "series", "type": "nominal", "label": "Series"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    if bd_supply_rows:
        charts.append(
            {
                "id": "bd_supply_pipeline_chart",
                "title": "Buildings Department — Housing Supply Pipeline (current month)",
                "subtitle": "Domestic units by permit stage and region -- a leading indicator for future housing supply.",
                "type": "bar",
                "intent": "comparison",
                "dataset": "bd_supply_pipeline",
                "sourceId": "bd_supply",
                "encodings": {
                    "x": {"field": "permit_stage", "type": "nominal", "label": "Permit stage"},
                    "y": {"field": "value", "type": "quantitative", "label": "Domestic units"},
                    "color": {"field": "region", "type": "nominal", "label": "Region"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    if bd_supply_floor_area_rows:
        charts.append(
            {
                "id": "bd_supply_floor_area_chart",
                "title": "Buildings Department — Usable Floor Area by Permit Stage (current month)",
                "subtitle": "Domestic vs Non-domestic usable floor area, all regions combined.",
                "type": "bar",
                "intent": "comparison",
                "dataset": "bd_supply_floor_area",
                "sourceId": "bd_supply",
                "encodings": {
                    "x": {"field": "permit_stage", "type": "nominal", "label": "Permit stage"},
                    "y": {"field": "value", "type": "quantitative", "label": "Usable floor area (sqm)"},
                    "color": {"field": "property_category", "type": "nominal", "label": "Property category"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    if bd_supply_history_unit_rows:
        charts.append(
            {
                "id": "bd_supply_history_units_chart",
                "title": "Buildings Department — Historical Housing Supply Pipeline",
                "subtitle": "Monthly domestic units at consent-to-commence, commencement notice and occupation-permit stages, from the official PDF archive.",
                "type": "line",
                "intent": "trend",
                "dataset": "bd_supply_pipeline_history_units",
                "sourceId": "bd_supply_history",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "Domestic units"},
                    "color": {"field": "series", "type": "nominal", "label": "Permit stage"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    if bd_supply_history_count_rows:
        charts.append(
            {
                "id": "bd_supply_history_counts_chart",
                "title": "Buildings Department — Historical Permit / Consent Counts",
                "subtitle": "Monthly demolition, plans-approved and consent-to-commence counts; Md55 has no corresponding count field and occupation-permit counts are covered by the units chart above.",
                "type": "line",
                "intent": "trend",
                "dataset": "bd_supply_pipeline_history_counts",
                "sourceId": "bd_supply_history",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "Project / consent count"},
                    "color": {"field": "series", "type": "nominal", "label": "Permit stage"},
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

    if hkma_activity_rows:
        latest_activity = hkma_activity_rows[-1] if hkma_activity_rows else {}
        tables.append(
            {
                "id": "hkma_mortgage_activity_table",
                "title": "HKMA Mortgage Market Activity",
                "subtitle": f"Monthly new applications, approved loans, and drawn-down amount ({latest_activity.get('date', '—')} shown latest).",
                "dataset": "hkma_mortgage_activity",
                "sourceId": "hkma_mortgage",
                "defaultSort": {"field": "date", "direction": "desc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "date", "label": "Month", "type": "date"},
                    {"field": "new_applications_count", "label": "New Applications", "format": "number"},
                    {"field": "approved_loans_amount_mhkd", "label": "Approved Loans (HK$m)", "format": "number"},
                    {"field": "approved_primary_presales_amount_mhkd", "label": "Primary/Presales (HK$m)", "format": "number"},
                    {"field": "approved_secondary_amount_mhkd", "label": "Secondary (HK$m)", "format": "number"},
                    {"field": "approved_refinancing_amount_mhkd", "label": "Refinancing (HK$m)", "format": "number"},
                    {"field": "drawn_down_amount_mhkd", "label": "Drawn Down (HK$m)", "format": "number"},
                ],
            }
        )

    if transaction_pulse_rows:
        tables.append(
            {
                "id": "agency_transactions_pulse_table",
                "title": "Agency Transaction Pulse",
                "subtitle": agency_pulse_subtitle,
                "dataset": "agency_transactions_pulse",
                "sourceId": "agency_transactions",
                "defaultSort": {"field": "transaction_date", "direction": "desc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "transaction_date", "label": "Date", "type": "date"},
                    {"field": "estate_name", "label": "Estate", "type": "text"},
                    {"field": "saleable_area_sqft", "label": "Area (sq ft)", "format": "number"},
                    {"field": "price_hkd", "label": "Price (HK$)", "format": "number"},
                    {"field": "unit_price_hkd_sqft", "label": "HK$ / sq ft", "format": "number"},
                    {"field": "primary_source_agency", "label": "Primary Agency", "type": "text"},
                    {"field": "matched_agency_count", "label": "Agencies Matched", "format": "number"},
                ],
            }
        )

    if new_project_rows:
        # Only show a column if at least one row has a real value for it --
        # move-in year in particular isn't shown for every 28Hse listing.
        _new_project_columns = [{"field": "project_name", "label": "Project", "type": "text"}]
        if any(row.get("location_district") for row in new_project_rows):
            _new_project_columns.append({"field": "location_district", "label": "District", "type": "text"})
        if any(row.get("estimated_total_units") is not None for row in new_project_rows):
            _new_project_columns.append({"field": "estimated_total_units", "label": "Est. Units", "format": "number"})
        if any(row.get("estimated_move_in_year") is not None for row in new_project_rows):
            _new_project_columns.append({"field": "estimated_move_in_year", "label": "Est. Move-in Year", "format": "number"})
        tables.append(
            {
                "id": "hse28_new_projects_table",
                "title": "Newly Launched Residential Projects",
                "subtitle": "28Hse new-properties catalogue.",
                "dataset": "hse28_new_projects",
                "sourceId": "hse28_new_projects",
                "density": "dense",
                "layout": "half",
                "columns": _new_project_columns,
            }
        )

    if midland_estate_rows:
        tables.append(
            {
                "id": "midland_top_estates_table",
                "title": "Top Estates by Transaction Volume (Midland)",
                "subtitle": "Estates with the most recent transaction activity per Midland Realty.",
                "dataset": "midland_top_estates",
                "sourceId": "midland_mhpi",
                "defaultSort": {"field": "transaction_count", "direction": "desc"},
                "density": "dense",
                "layout": "half",
                "columns": [
                    {"field": "estate_name", "label": "Estate", "type": "text"},
                    {"field": "region_name", "label": "Region", "type": "text"},
                    {"field": "district_name", "label": "District", "type": "text"},
                    {"field": "transaction_count", "label": "Transactions", "format": "number"},
                ],
            }
        )

    if bd_supply_table_rows:
        tables.append(
            {
                "id": "bd_supply_detail_table",
                "title": "Housing Supply Pipeline — Detail",
                "subtitle": "Current-month project counts and floor area by permit stage, region, and property category.",
                "dataset": "bd_supply_detail",
                "sourceId": "bd_supply",
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "permit_stage", "label": "Permit Stage", "type": "text"},
                    {"field": "region", "label": "Region", "type": "text"},
                    {"field": "property_category", "label": "Category", "type": "text"},
                    {"field": "total_projects_count", "label": "Projects", "format": "number"},
                    {"field": "total_domestic_units", "label": "Domestic Units", "format": "number"},
                    {"field": "total_usable_floor_area_sqm", "label": "Usable Floor Area (sqm)", "format": "number"},
                ],
            }
        )

    if bd_monthly_stats_rows:
        tables.append(
            {
                "id": "bd_monthly_stats_table",
                "title": "Buildings Department Monthly Digest (raw statistics)",
                "subtitle": "Scratch extraction of the digest's section-1 tables; row labels and figures are kept verbatim.",
                "dataset": "bd_monthly_stats",
                "sourceId": "bd_monthly_digest",
                "defaultSort": {"field": "date", "direction": "desc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "date", "label": "Month", "type": "date"},
                    {"field": "table_id", "label": "Table", "type": "text"},
                    {"field": "row_label", "label": "Row", "type": "text"},
                    {"field": "values", "label": "Values", "type": "text"},
                ],
            }
        )

    blocks = [
        {
            "id": "snapshot_context",
            "type": "markdown",
            "body": (
                f"**Data snapshot:** `{snapshot_id}` · generated {generated_at}.  "
                "This is a published snapshot, not a live connection. RVD observations marked provisional may be revised."
            ),
        },
        {
            "id": "market_regime_intro",
            "type": "markdown",
            "body": "## Market Regime Overview\n\nTime-series first: compare residential prices, rents, activity, credit, supply and commercial property without treating a snapshot as a trend.",
        },
        {"id": "market_pulse", "type": "metric-strip", "cardIds": [card["id"] for card in cards]},
    ]
    if residential_price_rebased:
        blocks.append({"id": "residential_price_regime_block", "type": "chart", "chartId": "residential_price_rebased_chart"})
    if residential_rent_rebased:
        blocks.append({"id": "residential_rent_regime_block", "type": "chart", "chartId": "residential_rent_rebased_chart"})
    blocks.append({"id": "residential_sources_section", "type": "markdown", "body": "## Residential source histories\n\nRaw publisher levels and sentiment remain separate from the rebased regime views above."})
    blocks.extend([
        {"id": "ccl_chart", "type": "chart", "chartId": "ccl_trend", "layout": "half"},
        {"id": "mhpi_chart", "type": "chart", "chartId": "mhpi_trend", "layout": "half"},
    ])
    if cci_rows:
        blocks.append({"id": "cci_chart_block", "type": "chart", "chartId": "cci_trend", "layout": "half"})
    if cri_rows:
        blocks.append({"id": "cri_chart_block", "type": "chart", "chartId": "cri_trend", "layout": "half"})
    if cri_yield_rows:
        blocks.append({"id": "cri_yield_chart_block", "type": "chart", "chartId": "cri_yield_trend", "layout": "half"})
    if csi_rows:
        blocks.append({"id": "csi_chart_block", "type": "chart", "chartId": "csi_trend", "layout": "half"})
    blocks.extend([
        {"id": "rvd_price_chart", "type": "chart", "chartId": "rvd_trend", "layout": "half"},
        {"id": "rvd_rent_chart", "type": "chart", "chartId": "rvd_rent_trend", "layout": "half"},
        {"id": "confidence_chart", "type": "chart", "chartId": "confidence_trend"},
    ])
    blocks.append({"id": "activity_financing_section", "type": "markdown", "body": "## Activity & financing\n\nTransactions, mortgage applications, loan amounts and credit quality are shown as separate compatible time series."})
    if hkma_rows:
        blocks.append({"id": "hkma_mortgage_chart_block", "type": "chart", "chartId": "hkma_mortgage_rate_mix_chart"})
    if cnsd_const_rows:
        blocks.append({"id": "cnsd_construction_chart_block", "type": "chart", "chartId": "cnsd_construction_value_chart"})
    if land_disposal_rows:
        blocks.append({"id": "censtatd_land_disposals_chart_block", "type": "chart", "chartId": "censtatd_land_disposals_chart"})

    if hkma_ltv_rows:
        blocks.append({"id": "hkma_ltv_chart_block", "type": "chart", "chartId": "hkma_ltv_chart", "layout": "half"})
    if hkma_credit_quality_rows:
        blocks.append({"id": "hkma_credit_quality_chart_block", "type": "chart", "chartId": "hkma_credit_quality_chart", "layout": "half"})
    if hkma_applications_rows:
        blocks.append({"id": "hkma_applications_chart_block", "type": "chart", "chartId": "hkma_applications_chart", "layout": "half"})
    if hkma_loan_amount_rows:
        blocks.append({"id": "hkma_loan_amount_chart_block", "type": "chart", "chartId": "hkma_loan_amount_chart"})
    if hkma_activity_rows:
        blocks.append({"id": "hkma_mortgage_activity_table_block", "type": "table", "tableId": "hkma_mortgage_activity_table"})

    blocks.append({"id": "supply_commercial_section", "type": "markdown", "body": "## Supply & commercial property\n\nSupply history and official office/retail rent series are separate from residential price and rent levels."})
    if rvd_office_rows:
        blocks.append({"id": "rvd_office_chart_block", "type": "chart", "chartId": "rvd_office_trend"})
    if rvd_retail_rows:
        blocks.append({"id": "rvd_retail_chart_block", "type": "chart", "chartId": "rvd_retail_trend"})

    if epi_eri_rows:
        blocks.append({"id": "epi_eri_chart_block", "type": "chart", "chartId": "epi_eri_chart"})
    if transaction_pulse_rows:
        blocks.append({"id": "agency_transactions_pulse_block", "type": "table", "tableId": "agency_transactions_pulse_table"})
    if landreg_asp_rows:
        blocks.append({"id": "landreg_asp_chart_block", "type": "chart", "chartId": "landreg_asp_chart", "layout": "full"})
    if bd_supply_rows:
        blocks.append({"id": "bd_supply_pipeline_chart_block", "type": "chart", "chartId": "bd_supply_pipeline_chart"})
    if bd_supply_floor_area_rows:
        blocks.append({"id": "bd_supply_floor_area_chart_block", "type": "chart", "chartId": "bd_supply_floor_area_chart"})
    if bd_supply_history_unit_rows:
        blocks.append({"id": "bd_supply_history_units_chart_block", "type": "chart", "chartId": "bd_supply_history_units_chart"})
    if bd_supply_history_count_rows:
        blocks.append({"id": "bd_supply_history_counts_chart_block", "type": "chart", "chartId": "bd_supply_history_counts_chart"})
    if bd_supply_table_rows:
        blocks.append({"id": "bd_supply_detail_block", "type": "table", "tableId": "bd_supply_detail_table"})
    if new_project_rows:
        blocks.append({"id": "hse28_new_projects_block", "type": "table", "tableId": "hse28_new_projects_table", "layout": "half"})
    if midland_estate_rows:
        blocks.append({"id": "midland_top_estates_block", "type": "table", "tableId": "midland_top_estates_table", "layout": "half"})
    if bd_monthly_stats_rows:
        blocks.append({"id": "bd_monthly_stats_block", "type": "table", "tableId": "bd_monthly_stats_table"})

    blocks.extend([
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


_COMMITTED_ARTIFACT_PATH = Path(__file__).resolve().parent.parent / ".generated" / "hk-real-estate-artifact.json"


def _load_midland_fallback_from_committed_artifact(dataset_key: str, value_column: str) -> pd.DataFrame:
    """Reconstruct a raw Midland frame from yesterday's committed artifact.

    load_latest_normalized() reads data/normalized/hk_real_estate/, which is
    entirely gitignored -- on a fresh CI checkout that directory never has
    anything in it, so the fallback silently produced an empty, columnless
    DataFrame that crashed _normalized_frame's schema check downstream
    (confirmed via a real CI failure: "Midland MHPI: missing columns
    ['date', 'mhpi_overall']"), taking the whole sector refresh down with it
    even though CCL/RVD had nothing to do with Midland.

    .generated/hk-real-estate-artifact.json, by contrast, IS committed to
    git every successful run, so it always has real historical rows on a
    fresh checkout. Re-derive a compatible raw frame from its own
    mhpi_history/confidence_history datasets (which are {date, value} pairs)
    as a real second-level fallback, rather than a fabricated one.
    """
    try:
        data = json.loads(_COMMITTED_ARTIFACT_PATH.read_text(encoding="utf-8"))
        rows = data["snapshot"]["datasets"][dataset_key]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame({"date": [r["date"] for r in rows], value_column: [r["value"] for r in rows]})


def _load_normalized_or_fetch(dataset_name: str, label: str, fetch_fn) -> pd.DataFrame:
    """Prefer durable normalized output, with a bounded live-fetch fallback."""
    normalized = load_latest_normalized(dataset_name)
    if not normalized.empty:
        return normalized
    return _safe_fetch(label, fetch_fn)


def _fetch_centaline_history(index_code: str) -> pd.DataFrame:
    try:
        return fetch_centaline_index_bundle(index_code)[0]
    except Exception as exc:  # noqa: BLE001
        print(f"  [hk_real_estate] Centaline {index_code} fetch failed, continuing without it: {exc}", file=sys.stderr)
        return pd.DataFrame()


def fetch_live_frames() -> dict[str, pd.DataFrame]:
    if os.environ.get(SKIP_MIDLAND_ENV_VAR):
        # Midland's WAF blocks GitHub Actions' datacenter IP range (confirmed
        # 403, reproducible from a residential IP, no known bypass). Fall
        # back to the last real snapshot rather than attempting a fetch
        # that's known to fail here and blocking the whole sector refresh.
        mhpi = load_latest_normalized("midland_mhpi_weekly")
        if mhpi.empty:
            mhpi = _load_midland_fallback_from_committed_artifact("mhpi_history", "mhpi_overall")
        confidence = load_latest_normalized("midland_confidence_weekly")
        if confidence.empty:
            confidence = _load_midland_fallback_from_committed_artifact("confidence_history", "confidence_index")
        # No live Midland fetch happens on this path, so there's no fresh
        # top-estates snapshot to offer -- an honest empty frame, not a guess.
        estates = pd.DataFrame()
    else:
        mhpi, confidence, estates = run_midland_ingestion()
    rvd_price, rvd_rent = run_rvd_ingestion()
    cci = _load_normalized_or_fetch("centaline_cci_monthly", "Centaline CCI", lambda: _fetch_centaline_history("CCI"))
    cri = _load_normalized_or_fetch("centaline_cri_monthly", "Centaline CRI", lambda: _fetch_centaline_history("CRI"))
    cri_yield = _load_normalized_or_fetch("centaline_cri_yield_monthly", "Centaline CRI yield", lambda: _fetch_centaline_history("CRI"))
    csi = _load_normalized_or_fetch("centaline_csi_weekly", "Centaline CSI", lambda: _fetch_centaline_history("CSI"))
    rvd_office = _load_normalized_or_fetch("rvd_office_rental_index_monthly", "RVD office rental", fetch_rvd_office_rental_index)
    rvd_retail = _load_normalized_or_fetch("rvd_retail_index_monthly", "RVD retail rental", fetch_rvd_retail_rental_index)
    agency_frames = []
    for label, fetch_fn in (
        ("28Hse transactions", fetch_28hse_transaction_pilot),
        ("Midland transactions", fetch_midland_transaction_pilot),
        ("Centaline transactions", fetch_centaline_transaction_pilot),
    ):
        frame = _safe_fetch(label, fetch_fn)
        if not frame.empty:
            agency_frames.append(frame)
    unified_tx = deduplicate_agency_transactions(agency_frames) if agency_frames else pd.DataFrame()
    return {
        "ccl": fetch_centaline_ccl(),
        "mhpi": mhpi,
        "confidence": confidence,
        "rvd_price": rvd_price,
        "rvd_rent": rvd_rent,
        "centaline_cci": cci,
        "centaline_cri": cri,
        "centaline_cri_yield": cri_yield,
        "centaline_csi": csi,
        "rvd_office": rvd_office,
        "rvd_retail": rvd_retail,
        "midland_estates": estates,
        "unified_tx": unified_tx,
        "bd_supply_history": load_latest_normalized("bd_supply_pipeline_history"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Canonical artifact JSON output path")
    parser.add_argument("--status-output", type=Path, required=True, help="Compact Astro status JSON output path")
    args = parser.parse_args()

    live_frames = fetch_live_frames()
    unified_tx = live_frames.pop("unified_tx", pd.DataFrame())
    bd_supply_history = live_frames.pop("bd_supply_history", pd.DataFrame())
    new_series = {
        key: live_frames.pop(key, pd.DataFrame())
        for key in ("centaline_cci", "centaline_cri", "centaline_cri_yield", "centaline_csi", "rvd_office", "rvd_retail")
    }
    artifact, status = build_artifact(
        live_frames,
        raw_unified_tx=unified_tx,
        raw_bd_supply_history=bd_supply_history,
        raw_new_series=new_series,
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
