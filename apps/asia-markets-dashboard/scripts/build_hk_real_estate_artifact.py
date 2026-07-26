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
from src.hk_real_estate.sources.epi import fetch_28hse_epi_eri
from src.hk_real_estate.sources.hse28 import fetch_28hse_new_projects, fetch_28hse_transaction_pilot
from src.hk_real_estate.sources.midland_transactions import fetch_midland_transaction_pilot
from src.hk_real_estate.sources.centaline_transactions import fetch_centaline_transaction_pilot
from src.hk_real_estate.sources.landreg import fetch_landreg_monthly_statistics
from src.hk_real_estate.sources.buildings_dept import fetch_buildings_dept_monthly_stats
from src.hk_real_estate.sources.bd_projects import fetch_bd_supply_leading_indicators
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
        "label": "Buildings Department Project Lifecycle (Plans/Consent/OP)",
        "href": "https://www.bd.gov.hk/en/whats-new/monthly-digests/index.html",
        "query": {
            "engine": "official XLS tables",
            "url": "https://www.bd.gov.hk/doc/en/whats-new/monthly-digests/Md53.xls",
            "language": "XLS",
            "description": "Project-level Plans Approved / Consent to Commence Works / Occupation Permits Issued tables, aggregated into a current-month supply-pipeline snapshot by stage, region, and property category.",
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


def build_artifact(
    raw_frames: dict[str, pd.DataFrame],
    raw_hkma: pd.DataFrame | None = None,
    raw_cnsd: pd.DataFrame | None = None,
    raw_epi_eri: pd.DataFrame | None = None,
    raw_new_projects: pd.DataFrame | None = None,
    raw_landreg: tuple[pd.DataFrame, pd.DataFrame] | None = None,
    raw_bd_monthly_stats: pd.DataFrame | None = None,
    raw_bd_supply: pd.DataFrame | None = None,
    raw_unified_tx: pd.DataFrame | None = None,
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
    df_hkma = raw_hkma if raw_hkma is not None else fetch_hkma_residential_mortgage_survey()
    df_cnsd = raw_cnsd if raw_cnsd is not None else fetch_cnsd_table("615-66001")

    hkma_rows = []
    hkma_ltv_rows: list[dict[str, Any]] = []
    hkma_credit_quality_rows: list[dict[str, Any]] = []
    hkma_activity_rows: list[dict[str, Any]] = []
    if not df_hkma.empty and "observation_date" in df_hkma.columns:
        for _, r in df_hkma.iterrows():
            obs_d = str(r["observation_date"])[:10]
            hibor_pct = r.get("hibor_pricing_pct_share")
            blr_pct = r.get("blr_pricing_pct_share")
            fixed_pct = r.get("fixed_pricing_pct_share")
            if pd.notna(hibor_pct):
                hkma_rows.append({"date": obs_d, "series": "HIBOR-based (%)", "value": float(hibor_pct)})
            if pd.notna(blr_pct):
                hkma_rows.append({"date": obs_d, "series": "Best Lending Rate (%)", "value": float(blr_pct)})
            if pd.notna(fixed_pct):
                hkma_rows.append({"date": obs_d, "series": "Fixed-rate (%)", "value": float(fixed_pct)})
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

    cnsd_const_rows = []
    if not df_cnsd.empty and "period" in df_cnsd.columns and "value" in df_cnsd.columns:
        for _, r in df_cnsd.iterrows():
            if pd.notna(r.get("value")) and pd.notna(r.get("period")):
                cnsd_const_rows.append({
                    "date": str(r["period"]),
                    "value": float(r["value"]),
                    "unit": str(r.get("unit", "HK$ million")),
                })

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

    landreg_volume_rows: list[dict[str, Any]] = []
    _LANDREG_VOLUME_STATISTIC = "Total Number of Urban & New Territories deeds received for registration (ASP Building Units)"
    _LANDREG_VOLUME_TABLE_ID = "t1"
    if not df_landreg_facts.empty and {"date", "table_id", "statistic_name", "units"}.issubset(df_landreg_facts.columns):
        # This exact description string is not a unique key -- Land Registry's
        # own JSON (see landreg.py's docstring: "does not pretend to have a
        # stable semantic taxonomy") repeats it verbatim in table t2 attached
        # to unrelated Assignment-of-Building-Units figures. Scoping to t1
        # (confirmed to be where this total genuinely lives, one row/month)
        # avoids picking up those unrelated same-labelled values.
        volume_slice = df_landreg_facts[
            (df_landreg_facts["statistic_name"] == _LANDREG_VOLUME_STATISTIC)
            & (df_landreg_facts["table_id"] == _LANDREG_VOLUME_TABLE_ID)
        ]
        for _, r in volume_slice.iterrows():
            if pd.notna(r.get("units")):
                landreg_volume_rows.append({"date": str(r["date"])[:10], "value": float(r["units"])})
        landreg_volume_rows.sort(key=lambda r: r["date"])

    landreg_asp_rows: list[dict[str, Any]] = []
    if not df_landreg_asp.empty and "date" in df_landreg_asp.columns:
        for _, r in df_landreg_asp.iterrows():
            date_s = str(r["date"])[:10]
            if pd.notna(r.get("all_building_units_asp")):
                landreg_asp_rows.append({"date": date_s, "series": "All Building Units ASP", "value": float(r["all_building_units_asp"])})
            if pd.notna(r.get("residential_units_asp")):
                landreg_asp_rows.append({"date": date_s, "series": "Residential Units ASP", "value": float(r["residential_units_asp"])})
        landreg_asp_rows.sort(key=lambda r: (r["series"], r["date"]))

    # Buildings Department: raw monthly digest scratch table (dense table only --
    # numeric_values are an unlabelled per-row array, not a stable chartable
    # series) + project-lifecycle supply indicators (a genuine supply-pipeline
    # snapshot, clean enough for a comparison chart).
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
        # Non-domestic rows always carry total_domestic_units == 0 by
        # definition, which would otherwise draw a second, always-zero bar
        # alongside the real Domestic figure for the same permit_stage/region.
        # Restrict the chart to Domestic (the actual housing-supply signal);
        # Non-domestic stays visible in the detail table below.
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

    # Deduplicated cross-agency transaction pulse (28Hse + Midland + Centaline).
    if raw_unified_tx is not None:
        df_unified_tx = raw_unified_tx
    else:
        agency_frames = []
        for label, fetch_fn in (
            ("28Hse transactions", fetch_28hse_transaction_pilot),
            ("Midland transactions", fetch_midland_transaction_pilot),
            ("Centaline transactions", fetch_centaline_transaction_pilot),
        ):
            frame = _safe_fetch(label, fetch_fn)
            if not frame.empty:
                agency_frames.append(frame)
        df_unified_tx = deduplicate_agency_transactions(agency_frames) if agency_frames else pd.DataFrame()

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
        ("Land Registry", "Monthly facts + ASP series", landreg_volume_rows + landreg_asp_rows, "Land Registry Monthly Statistics (JSON)"),
        ("Buildings Department", "Monthly digest + project lifecycle", bd_monthly_stats_rows + bd_supply_table_rows, "Buildings Department Monthly Digest / Project Lifecycle"),
    ):
        record_count = len(rows_or_frame)
        additional_coverage.append(
            {
                "source": label,
                "dataset": dataset_label,
                "type": "Measure",
                "status": "Healthy" if record_count else "No data this run",
                "latest_observation": "—",
                "records": record_count,
                "freshness": "Live at build time" if record_count else "Fetch returned no rows",
                "notes": f"{source_label}; see the chart/table above." if record_count else f"{source_label}; live fetch returned no usable rows this run.",
            }
        )

    coverage = health + additional_coverage + PLANNED_COVERAGE

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
        "hkma_ltv_history": hkma_ltv_rows,
        "hkma_credit_quality_history": hkma_credit_quality_rows,
        "hkma_mortgage_activity": hkma_activity_rows,
        "cnsd_construction_value": cnsd_const_rows,
        "epi_eri_history": epi_eri_rows,
        "hse28_new_projects": new_project_rows,
        "landreg_volume_history": landreg_volume_rows,
        "landreg_asp_history": landreg_asp_rows,
        "bd_monthly_stats": bd_monthly_stats_rows,
        "bd_supply_pipeline": bd_supply_rows,
        "bd_supply_detail": bd_supply_table_rows,
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

    if landreg_volume_rows:
        charts.append(
            {
                "id": "landreg_volume_chart",
                "title": "Land Registry — Registered Agreements for Sale & Purchase",
                "subtitle": "Total monthly deeds received for registration, Urban & New Territories combined.",
                "type": "line",
                "intent": "trend",
                "dataset": "landreg_volume_history",
                "sourceId": "landreg_monthly",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "Deeds registered"},
                },
                "valueFormat": "number",
                "layout": "half",
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
                "layout": "half",
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
                "subtitle": "Deduplicated recent transactions across 28Hse, Midland, and Centaline listings.",
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
        # District / estimated-unit-count extraction from 28Hse's current markup
        # consistently returns null (site structure drifted from what the
        # source parser expects) -- only show columns with real values rather
        # than a table that looks broken with two permanently empty columns.
        _new_project_columns = [{"field": "project_name", "label": "Project", "type": "text"}]
        if any(row.get("location_district") for row in new_project_rows):
            _new_project_columns.append({"field": "location_district", "label": "District", "type": "text"})
        if any(row.get("estimated_total_units") is not None for row in new_project_rows):
            _new_project_columns.append({"field": "estimated_total_units", "label": "Est. Units", "format": "number"})
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
        {"id": "market_pulse", "type": "metric-strip", "cardIds": [card["id"] for card in cards]},
        {"id": "ccl_chart", "type": "chart", "chartId": "ccl_trend", "layout": "half"},
        {"id": "mhpi_chart", "type": "chart", "chartId": "mhpi_trend", "layout": "half"},
    ]
    if hkma_rows:
        blocks.append({"id": "hkma_mortgage_chart_block", "type": "chart", "chartId": "hkma_mortgage_rate_mix_chart"})
    if cnsd_const_rows:
        blocks.append({"id": "cnsd_construction_chart_block", "type": "chart", "chartId": "cnsd_construction_value_chart"})

    if hkma_ltv_rows:
        blocks.append({"id": "hkma_ltv_chart_block", "type": "chart", "chartId": "hkma_ltv_chart", "layout": "half"})
    if hkma_credit_quality_rows:
        blocks.append({"id": "hkma_credit_quality_chart_block", "type": "chart", "chartId": "hkma_credit_quality_chart", "layout": "half"})
    if hkma_activity_rows:
        blocks.append({"id": "hkma_mortgage_activity_table_block", "type": "table", "tableId": "hkma_mortgage_activity_table"})

    blocks.extend([
        {"id": "rvd_price_chart", "type": "chart", "chartId": "rvd_trend", "layout": "half"},
        {"id": "rvd_rent_chart", "type": "chart", "chartId": "rvd_rent_trend", "layout": "half"},
        {"id": "rebased_chart", "type": "chart", "chartId": "rebased_trend"},
        {"id": "confidence_chart", "type": "chart", "chartId": "confidence_trend"},
    ])

    if epi_eri_rows:
        blocks.append({"id": "epi_eri_chart_block", "type": "chart", "chartId": "epi_eri_chart"})
    if transaction_pulse_rows:
        blocks.append({"id": "agency_transactions_pulse_block", "type": "table", "tableId": "agency_transactions_pulse_table"})
    if landreg_volume_rows:
        blocks.append({"id": "landreg_volume_chart_block", "type": "chart", "chartId": "landreg_volume_chart", "layout": "half"})
    if landreg_asp_rows:
        blocks.append({"id": "landreg_asp_chart_block", "type": "chart", "chartId": "landreg_asp_chart", "layout": "half"})
    if bd_supply_rows:
        blocks.append({"id": "bd_supply_pipeline_chart_block", "type": "chart", "chartId": "bd_supply_pipeline_chart"})
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
    return {
        "ccl": fetch_centaline_ccl(),
        "mhpi": mhpi,
        "confidence": confidence,
        "rvd_price": rvd_price,
        "rvd_rent": rvd_rent,
        "midland_estates": estates,
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
