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
from src.hk_real_estate.sources.commercial_controls import (
    fetch_cnsd_retail_sales_control,
    fetch_rvd_commercial_forecast_completions,
    fetch_rvd_commercial_stock_vacancy_district,
    fetch_rvd_office_stock_vacancy_district,
    fetch_rvd_office_vacancy_annual,
    fetch_tourism_hotel_adr_category,
    fetch_tourism_hotel_occupancy_category,
    fetch_tourism_hotel_rooms_category,
)
from src.hk_real_estate.sources.hkma import HKMA_PUBLIC_RMS_URL, fetch_hkma_residential_mortgage_survey
from src.common.cnsd_mdt import fetch_cnsd_table
from src.hk_real_estate.storage import load_latest_normalized, save_normalized_dataset
from src.hk_real_estate.sources.epi import fetch_28hse_epi_eri
from src.hk_real_estate.sources.hse28 import fetch_28hse_new_projects, fetch_28hse_transaction_pilot
from src.hk_real_estate.sources.shkp import fetch_shkp_corporate_documents, fetch_shkp_property_catalog
from src.hk_real_estate.sources.midland_transactions import fetch_midland_transaction_pilot
from src.hk_real_estate.sources.centaline_transactions import fetch_centaline_transaction_pilot
from src.hk_real_estate.sources.landreg import fetch_landreg_monthly_statistics
from src.hk_real_estate.sources.buildings_dept import fetch_buildings_dept_monthly_stats
from src.hk_real_estate.sources.bd_projects import fetch_bd_supply_leading_indicators
from src.hk_real_estate.sources.land_disposals import fetch_land_disposals
from src.hk_real_estate.dedup.transaction_dedup import deduplicate_agency_transactions
from src.hk_real_estate.shkp_commercial import (
    build_shkp_commercial_asset_master,
    build_shkp_quarterly_events,
)
from src.hk_real_estate.shkp_financial_model import run_shkp_financial_model
from src.hk_real_estate.shkp_sales_handover_bridge import (
    ANNUAL_DATASET as SHKP_SALES_HANDOVER_ANNUAL_DATASET,
    PHASE_DATASET as SHKP_SALES_HANDOVER_PHASE_DATASET,
    run_shkp_sales_handover_revenue_bridge,
)
from src.hk_real_estate.sources.shkp_quarterly import fetch_shkp_quarterly_numeric_facts


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

# The SRPE pilot is phase-level, while stock-code attribution is company-level.
# Keep these labels explicit so the dashboard does not infer an issuer from a
# project name or accidentally merge a JV project into the wrong listed owner.
SRPE_DEVELOPER_LABELS = {
    "0012": "Henderson Land",
    "0016": "Sun Hung Kai Properties",
    "0017": "New World Development",
    "0066": "MTR Corporation",
    "0083": "Sino Land",
}
SRPE_PROJECT_LABELS = {
    "grand-victoria-phase-1": "Grand Victoria — Phase 1",
    "novo-land-phase-2a": "NOVO LAND — Phase 2A",
    "novo-land-phase-3b": "NOVO LAND — Phase 3B",
    "park-yoho-napoli": "PARK YOHO NAPOLI",
    "the-henley-ii": "The Henley II",
    "pavilia-farm-iii": "PAVILIA FARM III",
    "the-southside-blue-coast": "Blue Coast",
}
SRPE_PROJECT_SHORT_LABELS = {
    "grand-victoria-phase-1": "Grand Victoria",
    "novo-land-phase-2a": "NOVO 2A",
    "novo-land-phase-3b": "NOVO 3B",
    "park-yoho-napoli": "PARK YOHO",
    "the-henley-ii": "Henley II",
    "pavilia-farm-iii": "PAVILIA III",
    "the-southside-blue-coast": "Blue Coast",
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
    "rvd_commercial_controls": {
        "id": "rvd_commercial_controls",
        "label": "Rating and Valuation Department — Commercial stock / vacancy / completions",
        "href": "https://www.rvd.gov.hk/tc/publications/property_market_statistics.html",
        "query": {
            "engine": "official CSV",
            "url": "https://www.rvd.gov.hk/datagovhk/Com_Stock_Completions_and_Vacancy_by_District_Eng.csv",
            "language": "CSV",
            "description": "Annual office and private-commercial stock, completions, vacancy and forecast-completion controls; these are market snapshots, not SHKP assets.",
        },
    },
    "cnsd_retail_sales_control": {
        "id": "cnsd_retail_sales_control",
        "label": "C&SD — Monthly Retail Sales Control",
        "href": "https://data.gov.hk/en-data/dataset/hk-censtatd-tablechart-b1080003",
        "query": {
            "engine": "official C&SD MDT CSV",
            "url": "https://www.censtatd.gov.hk/data/MDT_75_620-67002_VAL_IDX_RS_Raw_1dp_idx_n.csv",
            "language": "CSV",
            "description": "Monthly retail sales value and volume indices by outlet category; economy-wide demand control, not tenant sales at an SHKP mall.",
        },
    },
    "tourism_hotel_controls": {
        "id": "tourism_hotel_controls",
        "label": "Culture, Sports and Tourism Bureau — Hotel occupancy / room-rate controls",
        "href": "https://data.gov.hk/en-data/dataset/hk-cstb-cstb_tc-tc-hotel-room-occupancy-rate-by-category",
        "query": {
            "engine": "official tourism CSV",
            "url": "https://www.tourism.gov.hk/datagovhk/hotelroomoccupancy/hotel_room_occupancy_rate_monthly_by_cat_en.csv",
            "language": "CSV",
            "description": "Rolling five-year monthly hotel occupancy, achieved room-rate and room-supply controls by category; not SHKP hotel KPIs.",
        },
    },
    "shkp_quarterly": {
        "id": "shkp_quarterly",
        "label": "SHKP Quarterly — issuer project and commercial events",
        "href": "https://www.shkp.com/en-US/investor-relations/shkp-quarterly",
        "query": {
            "engine": "official issuer PDF catalogue",
            "url": "https://www.shkp.com/en-US/investor-relations/shkp-quarterly",
            "language": "HTML/PDF",
            "description": "Quarterly article headlines since 2021; event classification is research-only and does not infer sales value, ownership or asset-level occupancy.",
        },
    },
    "shkp_commercial_assets": {
        "id": "shkp_commercial_assets",
        "label": "SHKP — Hong Kong commercial asset observation master",
        "href": "https://www.shkp.com/en-US/our-business/hong-kong-properties",
        "query": {
            "engine": "pandas source-layer union",
            "url": "https://www.shkp.com/en-US/our-business/hong-kong-properties",
            "language": "Python",
            "description": "Current issuer directory, annual-report completed-property exposure and HK Completion Schedule commercial rows kept as separate observations.",
        },
    },
    "shkp_financial_bridge": {
        "id": "shkp_financial_bridge",
        "label": "SHKP — Hong Kong business financial bridge",
        "href": "https://www.shkp.com/en-US/investor-relations/financial-results-reports",
        "query": {
            "engine": "official issuer disclosures + read-only financial-data DuckDB join",
            "url": "https://www.shkp.com/en-US/investor-relations/financial-results-reports",
            "language": "PDF/Parquet/DuckDB",
            "description": "Selected SHKP group/segment facts, Hong Kong recurring portfolio facts, source-selected 0016.HK actuals, current consensus and filing-vintage diagnostics. Group/segment facts include JV/associate shares where stated and are not a project-level HK revenue split.",
        },
    },
    "shkp_sales_handover_bridge": {
        "id": "shkp_sales_handover_bridge",
        "label": "SHKP — Sales / handover / revenue timing bridge",
        "href": "https://www.srpe.gov.hk/opip/all_development",
        "query": {
            "engine": "normalized SRPE + SHKP annual-report/completion-schedule/BD crosswalk",
            "url": "https://www.srpe.gov.hk/opip/all_development",
            "language": "Parquet/Python",
            "description": "Gross phase-month SRPE activity is aligned to issuer handover evidence, planned completion windows and the current BD occupation-permit crosswalk; company revenue remains an annual non-allocated anchor.",
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
    "srpe_sales": {
        "id": "srpe_sales",
        "label": "Sales of First-hand Residential Properties Electronic Platform (SRPE)",
        "href": "https://www.srpe.gov.hk/opip/",
        "query": {
            "engine": "official SRPE JSON manifest + PDF registers / price lists",
            "url": "https://www.srpe.gov.hk/opip/",
            "language": "JSON + PDF",
            "description": "Phase-level first-hand residential transaction registers and price lists parsed from official SRPE documents; attributable sales use the explicit project ownership registry.",
            "metric_definitions": [
                "Monthly attributable contract sales are gross transaction price multiplied by the listed-company ownership percentage in the phase registry.",
                "Sell-through uses unique active units from the transaction-register history divided by the phase's published total residential properties.",
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
        "source": "SRPE expansion",
        "dataset": "Full developer / project coverage",
        "type": "Catalog",
        "status": "Catalog only",
        "latest_observation": "—",
        "records": 0,
        "freshness": "Content parser pending",
        "notes": "The dashboard currently covers six explicit pilot phases; broader developer and phase coverage still requires registry expansion and backfill.",
    },
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_safe(value: Any) -> Any:
    """Convert pandas/numpy missing values to JSON nulls before persistence.

    Optional control sources are intentionally allowed to retain sparse fields
    (for example an asset row without a GFA or an issuer event without a
    project alias).  ``DataFrame.iterrows()`` can expose those missing cells as
    ``numpy.nan`` rather than ``None``; Python's strict ``allow_nan=False``
    serializer correctly rejects them.  Normalize recursively at the artifact
    boundary so one sparse upstream field cannot abort an otherwise valid
    build, while keeping missingness explicit as JSON ``null``.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    # numpy scalar values (np.int64/np.float64/np.bool_) expose ``item``;
    # converting them here keeps the helper dependency-free.
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except (TypeError, ValueError):
            pass
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return None
    except (TypeError, ValueError):
        pass
    return value


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_json_safe(payload), handle, ensure_ascii=False, indent=2, allow_nan=False)
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
    record_type: str = "Measure",
    status_override: str | None = None,
    stale_after_days: int | None = None,
) -> dict[str, Any] | None:
    """Build a source-health row for an optional normalized tranche."""
    if frame.empty:
        return None
    date_column = next((column for column in ("date", "event_date", "as_of_date", "quarter_end") if column in frame.columns), None)
    if date_column is None:
        return None
    dates = pd.to_datetime(frame[date_column], errors="coerce").dropna()
    if dates.empty:
        return None
    # Normalized parquet files may preserve timezone-aware timestamps while
    # the builder's ``now`` is a naive UTC datetime (or vice versa).  Strip
    # timezone metadata before subtracting so an optional source cannot make
    # the whole artifact build fail merely because its lineage parser kept a
    # ``Z`` suffix.  The observation date shown to users remains unchanged.
    latest = pd.Timestamp(dates.max())
    if latest.tzinfo is not None:
        latest = latest.tz_localize(None)
    now_ts = pd.Timestamp(now)
    if now_ts.tzinfo is not None:
        now_ts = now_ts.tz_localize(None)
    age = (now_ts.normalize() - latest.normalize()).days
    if age < 0:
        freshness = f"forecast +{abs(age)}d"
    else:
        freshness = f"{age}d old"
    status = status_override or ("Stale" if stale_after_days is not None and age > stale_after_days else "Healthy")
    return {
        "source": PUBLIC_SOURCES[source_id]["label"],
        "dataset": dataset,
        "type": record_type,
        "status": status,
        "latest_observation": latest.strftime("%Y-%m-%d"),
        "records": int(len(frame)),
        "freshness": freshness,
        "notes": note,
    }


_SHKP_BRIDGE_COLUMNS = [
    "row_type",
    "period",
    "target_period",
    "period_type",
    "layer",
    "geography",
    "asset_class",
    "metric",
    "statistic",
    "value",
    "comparison_value",
    "difference_pct",
    "unit",
    "currency",
    "scope",
    "source",
    "source_url",
    "availability_date",
    "snapshot_date",
    "status",
    "point_in_time_quality",
    "model_use",
    "caveat",
]


def _clean_bridge_value(value: Any) -> Any:
    """Convert pandas/numpy scalars to JSON-safe values for the artifact."""
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return value


def _shkp_financial_bridge_rows(
    *,
    disclosed: pd.DataFrame,
    recurring: pd.DataFrame,
    actuals: pd.DataFrame,
    reconciliation: pd.DataFrame,
    consensus: pd.DataFrame,
    vintage_coverage: pd.DataFrame,
    coverage: pd.DataFrame,
    timing_phase: pd.DataFrame | None = None,
    timing_annual: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """Project the financial-model inputs into one compact monitoring table.

    The normalized financial-model datasets remain the canonical research
    contract.  This projection deliberately keeps official segment facts,
    HK recurring facts, sibling-database actuals, consensus and PIT diagnostics
    in separate ``row_type`` values so a renderer cannot accidentally sum them
    together.  Mainland rows are excluded from this HK-only dashboard view.
    """
    rows: list[dict[str, Any]] = []

    def append(**values: Any) -> None:
        row = {column: None for column in _SHKP_BRIDGE_COLUMNS}
        row.update({key: _clean_bridge_value(value) for key, value in values.items()})
        rows.append(row)

    official_metrics = {
        "group_revenue",
        "property_sales_revenue_including_jv_associates",
        "property_rental_revenue_including_jv_associates",
        "property_sales_operating_profit_including_jv_associates",
        "property_rental_operating_profit_including_jv_associates",
        "hk_contract_sales_yet_to_be_recognized",
        "hk_contract_sales_expected_recognition",
        "investment_properties",
        "associates_and_joint_ventures",
    }
    if not disclosed.empty and {"metric", "value"}.issubset(disclosed.columns):
        for raw in disclosed.to_dict("records"):
            metric = str(raw.get("metric") or "")
            if metric not in official_metrics or _clean_bridge_value(raw.get("value")) is None:
                continue
            geography = "hong_kong" if metric.startswith("hk_") else "group"
            append(
                row_type="official_disclosed_fact",
                period=raw.get("period_end"),
                target_period=raw.get("target_period_end"),
                period_type=raw.get("period_type"),
                layer=raw.get("fact_group"),
                geography=geography,
                asset_class="residential_development" if "contract_sales" in metric else "property_business",
                metric=metric,
                value=raw.get("value"),
                unit=raw.get("unit"),
                currency=raw.get("currency"),
                scope=raw.get("attribution_scope"),
                source=raw.get("source_label"),
                source_url=raw.get("source_url"),
                availability_date=raw.get("available_at"),
                status=raw.get("evidence_status"),
                model_use="historical_context_and_forecast_anchor",
                caveat=raw.get("caveat"),
            )

    # Recurring portfolio facts are already normalized into HKD/RMB and
    # geography/asset-class fields.  Keep only group and Hong Kong rows here;
    # the Mainland rows remain available in normalized storage for a later,
    # separately scoped branch.
    if not recurring.empty and {"geography", "metric", "value"}.issubset(recurring.columns):
        for raw in recurring.to_dict("records"):
            geography = str(raw.get("geography") or "").strip().lower()
            if geography not in {"group", "hong_kong"} or _clean_bridge_value(raw.get("value")) is None:
                continue
            append(
                row_type="hk_recurring_portfolio_fact",
                period=raw.get("period_end"),
                period_type=raw.get("period_type"),
                layer="recurring_portfolio",
                geography=geography,
                asset_class=raw.get("asset_class"),
                metric=raw.get("metric"),
                value=raw.get("value"),
                unit=raw.get("unit"),
                currency=raw.get("currency"),
                scope=raw.get("scope"),
                source=raw.get("source_label"),
                source_url=raw.get("source_url"),
                availability_date=raw.get("availability_date"),
                status=raw.get("evidence_status"),
                model_use="historical_context_and_capacity_anchor",
                caveat=raw.get("caveat"),
            )

    # Keep a small, interpretable subset of the sibling financial database.
    # Values with unit=currency are normalized to HKD millions; no financial
    # indicator ratios are mixed into this level series.
    actual_metric_map = {
        "revenue",
        "net_income_attributable",
        "operating_income",
        "total_assets",
        "total_debt",
        "net_debt",
        "stockholders_equity",
        "operating_cash_flow",
        "purchase_of_investment_properties",
    }
    if not actuals.empty and {"statement_type", "metric", "value"}.issubset(actuals.columns):
        for raw in actuals.to_dict("records"):
            if str(raw.get("statement_type") or "") not in {"income_statement", "balance_sheet", "cash_flow"}:
                continue
            if str(raw.get("metric") or "") not in actual_metric_map:
                continue
            value = _clean_bridge_value(raw.get("value"))
            if value is None:
                continue
            unit = raw.get("unit")
            currency = raw.get("currency")
            if unit == "currency" and currency == "HKD":
                value = float(value) / 1_000_000.0
                unit = "HKD_m"
            append(
                row_type="financial_data_actual",
                period=raw.get("period_end"),
                period_type=raw.get("period_type"),
                layer=raw.get("statement_type"),
                geography="group",
                asset_class="company",
                metric=raw.get("metric"),
                value=value,
                unit=unit,
                currency=currency,
                source=raw.get("source"),
                availability_date=raw.get("available_at"),
                status="selected_actual",
                point_in_time_quality=raw.get("point_in_time_quality"),
                model_use="historical_context_only",
                caveat=raw.get("caveat") or "Sibling financial-data observation; current snapshot lacks original announcement date for full PIT replay.",
            )

    if not consensus.empty and {"metric", "statistic", "value"}.issubset(consensus.columns):
        for raw in consensus.to_dict("records"):
            if _clean_bridge_value(raw.get("value")) is None:
                continue
            fiscal_year = _clean_bridge_value(raw.get("fiscal_year"))
            period = raw.get("estimate_period_end")
            if _clean_bridge_value(period) is None and fiscal_year is not None:
                period = f"FY{int(fiscal_year)}"
            append(
                row_type="consensus_snapshot",
                period=period,
                period_type="current_snapshot",
                layer="consensus",
                geography="group",
                asset_class="company",
                metric=raw.get("metric"),
                statistic=raw.get("statistic"),
                value=raw.get("value"),
                unit=raw.get("unit"),
                currency=raw.get("currency"),
                source=raw.get("source"),
                snapshot_date=raw.get("snapshot_date"),
                status="current_snapshot_only",
                model_use="current_scenario_input_only",
                caveat=raw.get("caveat") or "Consensus is a dated market-expectation snapshot, not issuer guidance or an audited actual.",
            )

    if not reconciliation.empty:
        for raw in reconciliation.to_dict("records"):
            append(
                row_type="reconciliation",
                period=raw.get("period_end"),
                period_type="annual",
                layer="official_vs_financial_data",
                geography="group",
                asset_class="company",
                metric=raw.get("metric"),
                value=raw.get("official_value_hkd_m"),
                comparison_value=raw.get("financial_data_value_hkd_m"),
                difference_pct=raw.get("difference_pct"),
                unit="HKD_m",
                currency="HKD",
                source=raw.get("financial_data_source"),
                status=raw.get("status"),
                model_use="unit_reconciliation_only",
                caveat=raw.get("caveat"),
            )

    if not vintage_coverage.empty:
        for raw in vintage_coverage.to_dict("records"):
            append(
                row_type="vintage_diagnostic",
                period=raw.get("period_end") or raw.get("snapshot_end"),
                period_type="coverage_summary",
                layer=raw.get("layer"),
                geography="group",
                asset_class="company",
                metric="row_count",
                value=raw.get("row_count"),
                unit="rows",
                source=raw.get("source"),
                status=raw.get("status"),
                point_in_time_quality=raw.get("point_in_time_quality"),
                model_use=raw.get("model_use"),
                caveat=raw.get("caveat"),
            )

    if not coverage.empty:
        count_fields = [
            "disclosed_rows",
            "recurring_portfolio_rows",
            "financial_data_actual_rows",
            "consensus_rows",
            "filing_vintage_rows",
            "project_bridge_rows",
        ]
        raw = coverage.iloc[0].to_dict()
        for field in count_fields:
            if field not in raw or _clean_bridge_value(raw.get(field)) is None:
                continue
            append(
                row_type="coverage_diagnostic",
                period=raw.get("last_verified_at"),
                period_type="coverage_summary",
                layer="financial_model_coverage",
                geography="group",
                asset_class="company",
                metric=field,
                value=raw.get(field),
                unit="rows",
                status=raw.get("validation_status"),
                model_use="coverage_only",
                caveat=raw.get("validation_warnings"),
            )

    for timing_row in _shkp_sales_handover_bridge_rows(timing_phase, timing_annual):
        append(**timing_row)

    rows.sort(key=lambda row: (str(row.get("period") or "9999"), str(row.get("row_type") or ""), str(row.get("metric") or "")))
    return rows[:320]


def _shkp_sales_handover_bridge_rows(
    phase_bridge: pd.DataFrame,
    annual_bridge: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Project compact timing rows into the existing financial bridge table.

    The portable renderer has a 50-dataset contract.  The normalized timing
    bridge therefore stays in Parquet while this projection reuses the
    already-visible financial bridge dataset.  Two rows per current candidate
    phase (gross activity and latest active units) plus one annual diagnostic
    row per scope keeps the projection below the existing 320-row budget.
    """
    if phase_bridge is None or phase_bridge.empty:
        return []
    rows: list[dict[str, Any]] = []

    def first_url(value: Any) -> str | None:
        try:
            parsed = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError):
            parsed = []
        if isinstance(parsed, list):
            urls = [str(item) for item in parsed if str(item).startswith(("http://", "https://"))]
            return urls[0] if urls else None
        return value if isinstance(value, str) and value.startswith(("http://", "https://")) else None

    current = phase_bridge.loc[
        phase_bridge.get("signal_scope", pd.Series(dtype="string")).eq("current_candidate_signal")
    ].copy()
    if current.empty:
        current = phase_bridge.sort_values("sales_period_end", na_position="last").drop_duplicates(
            "srpe_development_id", keep="last"
        )
    current = current.sort_values(["sales_period_end", "srpe_development_id"], na_position="last")
    for raw in current.to_dict("records"):
        phase_label = raw.get("phase_name") or raw.get("development_name") or raw.get("srpe_development_id")
        period = raw.get("last_nonzero_sales_period") or raw.get("sales_period_end") or raw.get("completion_schedule_as_of")
        source_url = first_url(raw.get("source_urls_json"))
        common = {
            "row_type": "sales_handover_phase_summary",
            "period": period,
            "period_type": "phase_summary",
            "layer": "sales_handover_timing",
            "geography": "hong_kong",
            "asset_class": "residential_development",
            "statistic": raw.get("bridge_status"),
            "scope": phase_label,
            "source": PUBLIC_SOURCES["shkp_sales_handover_bridge"]["label"],
            "source_url": source_url,
            "availability_date": raw.get("completion_schedule_as_of") or raw.get("handover_report_period_end"),
            "status": raw.get("bridge_status"),
            "point_in_time_quality": "research_snapshot_not_pit_safe",
            "model_use": raw.get("model_use"),
            "caveat": raw.get("caveat"),
        }
        sales_value = pd.to_numeric(pd.Series([raw.get("sales_value_gross_hkd")]), errors="coerce").iloc[0]
        if pd.notna(sales_value):
            rows.append(
                {
                    **common,
                    "metric": "sales_value_gross_hkd",
                    "value": float(sales_value),
                    "unit": "HKD",
                    "currency": "HKD",
                }
            )
        active_units = pd.to_numeric(pd.Series([raw.get("active_units_latest")]), errors="coerce").iloc[0]
        if pd.notna(active_units):
            rows.append(
                {
                    **common,
                    "metric": "active_units_latest",
                    "value": float(active_units),
                    "unit": "units",
                    "currency": None,
                    "caveat": (
                        f"Latest non-null active-unit snapshot; sales activity is gross and handover state is "
                        f"{raw.get('handover_disclosure_status')}. " + str(raw.get("caveat") or "")
                    ),
                }
            )

    if annual_bridge is not None and not annual_bridge.empty:
        for raw in annual_bridge.to_dict("records"):
            ratio = pd.to_numeric(pd.Series([raw.get("gross_sales_to_property_revenue_ratio_pct")]), errors="coerce").iloc[0]
            sales_m = pd.to_numeric(pd.Series([raw.get("sales_value_gross_hkd")]), errors="coerce").iloc[0] / 1_000_000.0
            if pd.notna(ratio):
                metric = "gross_sales_to_property_revenue_ratio_pct"
                value = float(ratio)
                unit = "%"
                currency = None
            elif pd.notna(sales_m):
                metric = "gross_contract_activity_hkd_m"
                value = float(sales_m)
                unit = "HKD_m"
                currency = "HKD"
            else:
                continue
            rows.append(
                {
                    "row_type": "sales_handover_annual_diagnostic",
                    "period": raw.get("fiscal_label") or raw.get("fiscal_year_end"),
                    "period_type": "fiscal_year",
                    "layer": "sales_handover_timing",
                    "geography": "hong_kong",
                    "asset_class": "residential_development",
                    "metric": metric,
                    "statistic": raw.get("signal_scope"),
                    "value": value,
                    "unit": unit,
                    "currency": currency,
                    "source": PUBLIC_SOURCES["shkp_sales_handover_bridge"]["label"],
                    "source_url": first_url(raw.get("source_urls_json")),
                    "availability_date": raw.get("fiscal_year_end"),
                    "status": raw.get("bridge_status"),
                    "point_in_time_quality": "research_snapshot_not_pit_safe",
                    "model_use": raw.get("model_use"),
                    "caveat": raw.get("caveat"),
                }
            )
    return rows


def _srpe_signal_views(frame: pd.DataFrame) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
]:
    """Build compact dashboard views from the normalized SRPE signal table.

    The normalized table remains the source of truth.  This function only
    creates chart/table projections and deliberately excludes document paths,
    hashes and other lineage-heavy fields from the portable artifact.
    """
    required = {
        "period",
        "project_id",
        "stock_code",
        "sales_units_gross",
        "sales_value_attributable_hkd",
        "cumulative_unique_active_units",
        "total_residential_properties",
        "cumulative_net_sell_through_pct",
        "weighted_avg_transaction_price_hkd",
    }
    if frame.empty or not required.issubset(frame.columns):
        return [], [], [], None, None, None, None
    # Legacy SRPE pilot snapshots may carry a numeric ownership percentage
    # without the reviewed phase-specific interval.  Never expose those rows
    # as attributable company sales; the raw transaction/sell-through layers
    # remain available for review in normalized storage.
    if "ownership_attribution_ready" not in frame.columns:
        return [], [], [], None, None, None, None
    visible = frame.loc[frame["ownership_attribution_ready"].fillna(False).astype(bool)].copy()
    if visible.empty:
        return [], [], [], None, None, None, None

    visible["period_date"] = pd.to_datetime(visible["period"], errors="coerce")
    visible = visible[visible["period_date"].notna()].copy()
    if visible.empty:
        return [], [], [], None, None, None, None
    visible["period"] = visible["period_date"].dt.strftime("%Y-%m")
    visible["developer"] = visible["stock_code"].astype(str).str.zfill(4).map(SRPE_DEVELOPER_LABELS).fillna(
        "Stock code " + visible["stock_code"].astype(str)
    )
    visible["project_name"] = visible["project_id"].map(SRPE_PROJECT_LABELS).fillna(
        visible.get("phase_name", visible.get("development_name", visible["project_id"]))
    )
    visible["project_short_name"] = visible["project_id"].map(SRPE_PROJECT_SHORT_LABELS).fillna(visible["project_name"])

    developer_monthly = (
        visible.groupby(["period", "developer"], as_index=False)
        .agg(
            sales_value_attributable_hkd=("sales_value_attributable_hkd", "sum"),
            sales_units_gross=("sales_units_gross", "sum"),
        )
        .sort_values(["period", "developer"])
    )
    # Keep the portable chart legends within the mobile renderer's tested
    # three-series limit. The latest-project table still retains every phase;
    # this chart focuses on the three developers with the largest cumulative
    # attributable sales in the pilot window.
    top_developers = (
        visible.groupby("developer", as_index=False)["sales_value_attributable_hkd"]
        .sum()
        .sort_values("sales_value_attributable_hkd", ascending=False)
        .head(3)["developer"]
        .tolist()
    )
    developer_rows = [
        {
            "date": row["period"],
            "developer": row["developer"],
            "value": round(float(row["sales_value_attributable_hkd"]) / 1_000_000, 4),
            "sales_units_gross": int(row["sales_units_gross"]),
        }
        for _, row in developer_monthly.iterrows()
        if row["developer"] in top_developers
    ]

    top_project_ids = (
        visible.groupby("project_id", as_index=False)["sales_value_attributable_hkd"]
        .sum()
        .sort_values("sales_value_attributable_hkd", ascending=False)
        .head(3)["project_id"]
        .tolist()
    )
    sell_through_rows = [
        {
            "date": row["period"],
            "project_name": row["project_name"],
            "project_short_name": row["project_short_name"],
            "developer": row["developer"],
            "value": round(float(row["cumulative_net_sell_through_pct"]), 4),
        }
        for _, row in visible.sort_values(["project_name", "period_date"]).iterrows()
        if row["project_id"] in top_project_ids and pd.notna(row.get("cumulative_net_sell_through_pct"))
    ]

    # Latest available row per phase is more useful for monitoring than a
    # 196-row raw dump.  Keep the period explicit because pilot phases have
    # different document histories and therefore different latest months.
    latest_rows = visible.sort_values("period_date").groupby("project_id", as_index=False).tail(1)
    latest_rows = latest_rows.sort_values(["developer", "project_name"])
    latest_project_rows = [
        {
            "developer": row["developer"],
            "project_name": row["project_name"],
            "latest_period": row["period"],
            "sales_units_gross": int(row["sales_units_gross"]),
            "cumulative_unique_active_units": int(row["cumulative_unique_active_units"]),
            "total_residential_properties": float(row["total_residential_properties"]),
            "sell_through_pct": round(float(row["cumulative_net_sell_through_pct"]), 4),
            "weighted_avg_transaction_price_hkd": round(float(row["weighted_avg_transaction_price_hkd"]), 2)
            if pd.notna(row.get("weighted_avg_transaction_price_hkd"))
            else None,
            "ownership_pct": float(row["ownership_pct"]) if pd.notna(row.get("ownership_pct")) else None,
        }
        for _, row in latest_rows.iterrows()
    ]

    aggregate = (
        visible.groupby("period_date", as_index=False)
        .agg(
            sales_value_attributable_hkd=("sales_value_attributable_hkd", "sum"),
            sales_units_gross=("sales_units_gross", "sum"),
        )
        .sort_values("period_date")
    )
    latest = aggregate.iloc[-1]
    prior = aggregate.iloc[-2] if len(aggregate) > 1 else latest
    year_cutoff = latest["period_date"] - pd.DateOffset(years=1)
    yearly_candidates = aggregate[aggregate["period_date"] <= year_cutoff]
    yearly = yearly_candidates.iloc[-1] if not yearly_candidates.empty else aggregate.iloc[0]
    sales_kpi = {
        "latest": round(float(latest["sales_value_attributable_hkd"]) / 1_000_000, 4),
        "period_change": round(float(latest["sales_value_attributable_hkd"]) / float(prior["sales_value_attributable_hkd"]) - 1, 6)
        if float(prior["sales_value_attributable_hkd"])
        else None,
        "year_change": round(float(latest["sales_value_attributable_hkd"]) / float(yearly["sales_value_attributable_hkd"]) - 1, 6)
        if float(yearly["sales_value_attributable_hkd"])
        else None,
        "observation_date": latest["period_date"].strftime("%Y-%m"),
    }
    units_kpi = {
        "latest": int(latest["sales_units_gross"]),
        "period_change": round(float(latest["sales_units_gross"]) / float(prior["sales_units_gross"]) - 1, 6)
        if float(prior["sales_units_gross"])
        else None,
        "year_change": round(float(latest["sales_units_gross"]) / float(yearly["sales_units_gross"]) - 1, 6)
        if float(yearly["sales_units_gross"])
        else None,
        "observation_date": latest["period_date"].strftime("%Y-%m"),
    }
    inventory = pd.to_numeric(latest_rows["total_residential_properties"], errors="coerce").sum()
    active = pd.to_numeric(latest_rows["cumulative_unique_active_units"], errors="coerce").sum()
    sell_through_kpi = {
        "latest": round(float(active / inventory * 100), 4) if inventory else None,
        "projects": int(len(latest_rows)),
        "observation_date": latest["period_date"].strftime("%Y-%m"),
    }
    projects_kpi = {
        "latest": int(visible["project_id"].nunique()),
        "observation_date": latest["period_date"].strftime("%Y-%m"),
    }
    return developer_rows, sell_through_rows, latest_project_rows, sales_kpi, units_kpi, sell_through_kpi, projects_kpi


def _shkp_leading_signal_views(
    frame: pd.DataFrame,
    timing_bridge: pd.DataFrame | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project-level SHKP monitoring views that remain non-attributable."""
    required = {
        "period",
        "srpe_development_id",
        "sales_units_gross",
        "sales_value_gross_hkd",
        "active_units_eom",
        "month_status",
    }
    if frame is None or frame.empty or not required.issubset(frame.columns):
        return [], []
    signal = frame.copy()
    signal["period_date"] = pd.to_datetime(signal["period"], errors="coerce")
    signal = signal[signal["period_date"].notna()].copy()
    if signal.empty:
        return [], []
    for column in ("sales_units_gross", "sales_value_gross_hkd", "active_units_eom", "published_inventory_units", "sell_through_pct_eom"):
        if column not in signal.columns:
            signal[column] = pd.NA
        signal[column] = pd.to_numeric(signal[column], errors="coerce")
    signal["srpe_development_id"] = signal["srpe_development_id"].astype(str)
    history = (
        signal.groupby("period_date", as_index=False)
        .agg(
            raw_contract_sales_hkd=("sales_value_gross_hkd", lambda values: values.sum(min_count=1)),
            gross_pasp_units=("sales_units_gross", lambda values: values.sum(min_count=1)),
            active_units_eom=("active_units_eom", lambda values: values.sum(min_count=1)),
            phase_count=("srpe_development_id", "nunique"),
            covered_phase_count=("month_status", lambda values: int(values.ne("not_covered").sum())),
            not_covered_phase_count=("month_status", lambda values: int(values.eq("not_covered").sum())),
            observed_transaction_phase_count=("month_status", lambda values: int(values.eq("observed_transactions").sum())),
            observed_zero_phase_count=("month_status", lambda values: int(values.eq("observed_zero_transactions").sum())),
        )
        .sort_values("period_date")
    )
    history["coverage_ratio_pct"] = history["covered_phase_count"] / history["phase_count"] * 100

    def clean_number(value: Any, *, integer: bool = False) -> Any:
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        return int(value) if integer else float(value)

    history_rows = [
        {
            "date": row["period_date"].strftime("%Y-%m-%d"),
            "raw_contract_sales_hkd_m": round(clean_number(row["raw_contract_sales_hkd"]) / 1_000_000, 4) if clean_number(row["raw_contract_sales_hkd"]) is not None else None,
            "gross_pasp_units": clean_number(row["gross_pasp_units"], integer=True),
            "active_units_eom": clean_number(row["active_units_eom"], integer=True),
            "phase_count": int(row["phase_count"]),
            "covered_phase_count": int(row["covered_phase_count"]),
            "not_covered_phase_count": int(row["not_covered_phase_count"]),
            "coverage_ratio_pct": round(float(row["coverage_ratio_pct"]), 4),
            "observed_transaction_phase_count": int(row["observed_transaction_phase_count"]),
            "observed_zero_phase_count": int(row["observed_zero_phase_count"]),
            "ownership_policy": "leading_indicator_only",
        }
        for _, row in history.iterrows()
    ]
    latest = signal.sort_values("period_date").groupby("srpe_development_id", as_index=False).tail(1)
    latest = latest.sort_values(["candidate_status", "srpe_development_id"], na_position="last")
    timing = timing_bridge.copy() if timing_bridge is not None else pd.DataFrame()
    timing_map = {}
    if not timing.empty and {"srpe_development_id", "signal_scope"}.issubset(timing.columns):
        timing = timing.loc[timing["signal_scope"].eq("current_candidate_signal")].copy()
        timing["srpe_development_id"] = timing["srpe_development_id"].astype(str)
        timing_map = timing.set_index("srpe_development_id").to_dict("index")
    latest_rows: list[dict[str, Any]] = []
    for _, row in latest.iterrows():
        def clean(value: Any) -> Any:
            try:
                return None if pd.isna(value) else value
            except (TypeError, ValueError):
                return value
        phase_timing = timing_map.get(str(row.get("srpe_development_id")), {})
        latest_rows.append(
            {
                "project_id": clean(row.get("project_id")),
                "srpe_development_id": clean(row.get("srpe_development_id")),
                "development_name": clean(row.get("development_name")),
                "phase_name": clean(row.get("phase_name")),
                "candidate_status": clean(row.get("candidate_status")),
                "latest_period": row["period_date"].strftime("%Y-%m"),
                "sales_units_gross": clean_number(row.get("sales_units_gross"), integer=True),
                "raw_contract_sales_hkd": round(clean_number(row.get("sales_value_gross_hkd")), 2) if clean_number(row.get("sales_value_gross_hkd")) is not None else None,
                "active_units_eom": (
                    clean_number(row.get("active_units_eom"), integer=True)
                    if clean_number(row.get("active_units_eom"), integer=True) is not None
                    else clean_number(phase_timing.get("active_units_latest"), integer=True)
                ),
                "published_inventory_units": clean(row.get("published_inventory_units")),
                "sell_through_pct_eom": clean(row.get("sell_through_pct_eom")),
                "month_status": clean(row.get("month_status")),
                "coverage_end": clean(row.get("coverage_end")),
                "ownership_review_status": clean(row.get("ownership_review_status")) or "blocked_interval_missing",
                "handover_disclosure_status": clean(phase_timing.get("handover_disclosure_status")),
                "completion_window": clean(phase_timing.get("completion_window")),
                "bd_occupation_status": clean(phase_timing.get("bd_occupation_status")),
                "timing_bridge_status": clean(phase_timing.get("bridge_status")),
                "model_use": "leading_indicator_only",
            }
        )
    return history_rows, latest_rows


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
    raw_srpe_signals: pd.DataFrame | None = None,
    raw_shkp_leading_signals: pd.DataFrame | None = None,
    raw_28hse_reconciliation: pd.DataFrame | None = None,
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
    df_rvd_office_vacancy = new_series.get("rvd_office_vacancy", pd.DataFrame())
    df_rvd_office_stock = new_series.get("rvd_office_stock", pd.DataFrame())
    df_rvd_commercial_stock = new_series.get("rvd_commercial_stock", pd.DataFrame())
    df_rvd_commercial_forecast = new_series.get("rvd_commercial_forecast", pd.DataFrame())
    df_cnsd_retail_control = new_series.get("cnsd_retail_control", pd.DataFrame())
    df_tourism_occupancy = new_series.get("tourism_occupancy", pd.DataFrame())
    df_tourism_adr = new_series.get("tourism_adr", pd.DataFrame())
    df_tourism_rooms = new_series.get("tourism_rooms", pd.DataFrame())
    df_shkp_quarterly = new_series.get("shkp_quarterly_events", pd.DataFrame())
    df_shkp_quarterly_facts = new_series.get("shkp_quarterly_facts", pd.DataFrame())
    df_shkp_commercial_assets = new_series.get("shkp_commercial_assets", pd.DataFrame())
    df_shkp_financial_disclosed = new_series.get("shkp_financial_disclosed", pd.DataFrame())
    df_shkp_financial_recurring = new_series.get("shkp_financial_recurring", pd.DataFrame())
    df_shkp_financial_actuals = new_series.get("shkp_financial_actuals", pd.DataFrame())
    df_shkp_financial_reconciliation = new_series.get("shkp_financial_reconciliation", pd.DataFrame())
    df_shkp_financial_consensus = new_series.get("shkp_financial_consensus", pd.DataFrame())
    df_shkp_financial_vintage = new_series.get("shkp_financial_vintage", pd.DataFrame())
    df_shkp_financial_coverage = new_series.get("shkp_financial_coverage", pd.DataFrame())
    df_shkp_sales_handover_phase = new_series.get("shkp_sales_handover_phase", pd.DataFrame())
    df_shkp_sales_handover_annual = new_series.get("shkp_sales_handover_annual", pd.DataFrame())
    df_srpe_signals = raw_srpe_signals if raw_srpe_signals is not None else pd.DataFrame()
    df_shkp_leading_signals = raw_shkp_leading_signals if raw_shkp_leading_signals is not None else pd.DataFrame()
    df_28hse_reconciliation = raw_28hse_reconciliation if raw_28hse_reconciliation is not None else pd.DataFrame()

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

    def _control_rows(
        frame: pd.DataFrame,
        *,
        metric: str | None = None,
        category_column: str = "category",
        series_column: str = "segment",
        category_values: set[str] | None = None,
        max_rows: int = 2_000,
    ) -> list[dict[str, Any]]:
        if frame is None or frame.empty or not {"date", "value"}.issubset(frame.columns):
            return []
        selected = frame.copy()
        if metric is not None and "metric" in selected.columns:
            selected = selected.loc[selected["metric"].eq(metric)]
        if category_values is not None and category_column in selected.columns:
            selected = selected.loc[selected[category_column].astype(str).isin(category_values)]
        rows: list[dict[str, Any]] = []
        for _, row in selected.iterrows():
            date = pd.to_datetime(row.get("date"), errors="coerce")
            value = pd.to_numeric(row.get("value"), errors="coerce")
            if pd.isna(date) or pd.isna(value):
                continue
            series_value = row.get(series_column)
            if pd.isna(series_value) or str(series_value).strip() == "":
                series_value = row.get(category_column, row.get("metric", "value"))
            rows.append({
                "date": date.strftime("%Y-%m"),
                "series": str(series_value),
                "value": round(float(value), 4),
                "metric": str(row.get("metric", metric or "value")),
                "unit": row.get("unit"),
                "is_provisional": bool(row.get("is_provisional", False)),
            })
        rows.sort(key=lambda item: (item["series"], item["date"], item["metric"]))
        return rows[-max_rows:] if len(rows) > max_rows else rows

    cnsd_retail_rows = _control_rows(
        df_cnsd_retail_control,
        category_column="category",
        series_column="metric",
        category_values={"All retail outlet"},
        max_rows=1_500,
    )
    tourism_occupancy_rows = _control_rows(df_tourism_occupancy, series_column="category", max_rows=500)
    tourism_adr_rows = _control_rows(df_tourism_adr, series_column="category", max_rows=500)
    tourism_rooms_rows = _control_rows(df_tourism_rooms, series_column="category", max_rows=500)
    rvd_office_vacancy_rows = _control_rows(df_rvd_office_vacancy, metric="vacancy_pct", series_column="segment", max_rows=500)
    rvd_office_stock_rows = _control_rows(
        df_rvd_office_stock,
        metric="vacancy_pct",
        category_column="district",
        series_column="district",
        category_values={"HONG KONG", "KOWLOON", "NEW TERRITORIES"},
        max_rows=500,
    )
    rvd_commercial_vacancy_rows = _control_rows(
        df_rvd_commercial_stock,
        metric="vacancy_pct",
        category_column="district",
        series_column="district",
        category_values={"HONG KONG", "KOWLOON", "NEW TERRITORIES"},
        max_rows=500,
    )
    rvd_commercial_forecast_rows = _control_rows(
        df_rvd_commercial_forecast,
        metric="forecast_completions",
        category_column="district",
        series_column="district",
        category_values={"HONG KONG", "KOWLOON", "NEW TERRITORIES"},
        max_rows=500,
    )
    shkp_quarterly_event_rows = []
    if not df_shkp_quarterly.empty:
        selected_events = df_shkp_quarterly.loc[
            df_shkp_quarterly.get("property_relevance", pd.Series(dtype="string")).eq("property")
        ].copy()
        for _, row in selected_events.head(120).iterrows():
            shkp_quarterly_event_rows.append({
                "date": str(row.get("event_date") or row.get("quarter_end") or "")[:10],
                "quarter": row.get("quarter_label"),
                "event_type": row.get("event_type"),
                "asset_class": row.get("asset_class"),
                "geography": row.get("geography"),
                "project": row.get("project_label") or "—",
                "title": row.get("title"),
                "source_url": row.get("document_url"),
                "date_semantics": row.get("event_date_semantics"),
            })
        shkp_quarterly_event_rows.sort(key=lambda item: item["date"], reverse=True)
    shkp_quarterly_fact_rows = []
    if not df_shkp_quarterly_facts.empty:
        fact_slice = df_shkp_quarterly_facts.sort_values(
            ["event_date", "fact_type", "fact_id"], ascending=[False, True, True], na_position="last"
        ).head(160)
        for _, row in fact_slice.iterrows():
            shkp_quarterly_fact_rows.append(
                {
                    "date": str(row.get("event_date") or row.get("quarter_end") or "")[:10],
                    "quarter": row.get("quarter_label"),
                    "project": row.get("project_label") or "—",
                    "asset_class": row.get("asset_class"),
                    "fact_type": row.get("fact_type"),
                    "value": float(row["value"]) if pd.notna(row.get("value")) else None,
                    "unit": row.get("unit"),
                    "confidence": row.get("confidence"),
                    "fact_text": row.get("fact_text"),
                    "source_url": row.get("source_url"),
                    "page": int(row["page_number"]) if pd.notna(row.get("page_number")) else None,
                }
            )
    shkp_commercial_asset_rows = []
    if not df_shkp_commercial_assets.empty:
        for _, row in df_shkp_commercial_assets.head(180).iterrows():
            shkp_commercial_asset_rows.append({
                "asset_id": row.get("asset_id"),
                "asset_name": row.get("canonical_name") or row.get("name_raw"),
                "asset_class": row.get("asset_class"),
                "asset_subtype": row.get("asset_subtype"),
                "status": row.get("status"),
                "source_layer": row.get("source_layer"),
                "district": row.get("district"),
                "group_interest_pct": row.get("group_interest_pct"),
                "as_of_date": row.get("as_of_date"),
                "completion_window": row.get("completion_window"),
                "total_gfa_sqft": row.get("total_gfa_sqft"),
                "source_url": row.get("source_url"),
                "coverage_status": row.get("coverage_status"),
            })
    shkp_financial_bridge_rows = _shkp_financial_bridge_rows(
        disclosed=df_shkp_financial_disclosed,
        recurring=df_shkp_financial_recurring,
        actuals=df_shkp_financial_actuals,
        reconciliation=df_shkp_financial_reconciliation,
        consensus=df_shkp_financial_consensus,
        vintage_coverage=df_shkp_financial_vintage,
        coverage=df_shkp_financial_coverage,
        timing_phase=df_shkp_sales_handover_phase,
        timing_annual=df_shkp_sales_handover_annual,
    )
    carried_forward_datasets: dict[str, int] = {}
    shkp_financial_bridge_rows = _carry_forward_if_runner_unavailable(
        shkp_financial_bridge_rows, "shkp_hk_financial_bridge", carried_forward_datasets
    )
    (
        srpe_developer_monthly_rows,
        srpe_sell_through_rows,
        srpe_latest_project_rows,
        srpe_sales_kpi,
        srpe_units_kpi,
        srpe_sell_through_kpi,
        srpe_projects_kpi,
    ) = _srpe_signal_views(df_srpe_signals)
    shkp_leading_history_rows, shkp_leading_latest_rows = _shkp_leading_signal_views(
        df_shkp_leading_signals,
        timing_bridge=df_shkp_sales_handover_phase,
    )
    shkp_leading_phase_count = len({
        str(row.get("srpe_development_id"))
        for row in shkp_leading_latest_rows
        if row.get("srpe_development_id") not in (None, "", "nan")
    })
    srpe_signal_history_rows: list[dict[str, Any]] = []
    if not df_srpe_signals.empty:
        history_columns = [
            "development_id",
            "development_name",
            "phase_name",
            "period",
            "sales_units_gross",
            "sales_value_gross_hkd",
            "cancelled_units",
            "cumulative_gross_units",
            "cumulative_cancelled_units",
            "cumulative_event_net_units",
            "cumulative_unique_active_units",
            "cumulative_net_units",
            "total_residential_properties",
            "cumulative_net_sell_through_pct",
            "median_transaction_price_hkd",
            "weighted_avg_transaction_price_hkd",
            "days_since_first_pasp",
            "project_id",
            "stock_code",
            "ownership_pct",
            "srpe_development_id",
            "sales_value_attributable_hkd",
        ]
        present = [column for column in history_columns if column in df_srpe_signals.columns]
        for row in df_srpe_signals[present].to_dict("records"):
            clean = {}
            for key, value in row.items():
                if pd.isna(value):
                    clean[key] = None
                elif key in {"sales_units_gross", "cancelled_units", "cumulative_gross_units", "cumulative_cancelled_units", "cumulative_event_net_units", "cumulative_unique_active_units", "days_since_first_pasp"}:
                    clean[key] = int(value)
                elif key in {"sales_value_gross_hkd", "sales_value_attributable_hkd", "total_residential_properties", "cumulative_net_sell_through_pct", "median_transaction_price_hkd", "weighted_avg_transaction_price_hkd", "ownership_pct"}:
                    clean[key] = float(value)
                else:
                    clean[key] = value
            srpe_signal_history_rows.append(clean)

    # HKMA is a core monthly history, not an optional snapshot.  Prefer the
    # durable normalized cache, then fetch, then reconstruct the last
    # committed artifact if the upstream request returns no usable rows.  A
    # transient API outage must never make the mortgage charts disappear.
    df_hkma = raw_hkma if raw_hkma is not None else _load_hkma_with_fallback()
    df_hkma = _canonicalize_hkma_frame(df_hkma)
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

    if not df_hkma.empty and "observation_date" in df_hkma.columns:
        hkma_dates = pd.to_datetime(df_hkma["observation_date"], errors="coerce").dropna()
        if not hkma_dates.empty:
            hkma_latest = hkma_dates.max()
            now_date = pd.Timestamp(now.replace(tzinfo=None)).normalize()
            hkma_age = max(0, int((now_date - hkma_latest.normalize()).days))
            fallback_reason = df_hkma.attrs.get("dashboard_fallback_reason")
            health.append(
                {
                    "source": PUBLIC_SOURCES["hkma_mortgage"]["label"],
                    "dataset": "HKMA residential mortgage survey",
                    "type": "Measure",
                    "status": "Stale" if fallback_reason else "Healthy",
                    "latest_observation": hkma_latest.strftime("%Y-%m-%d"),
                    "records": int(len(df_hkma)),
                    "freshness": "Previous artifact snapshot" if fallback_reason else f"{hkma_age}d old",
                    "notes": (
                        f"Live fetch returned no usable rows; reused {fallback_reason}."
                        if fallback_reason
                        else "Official monthly residential mortgage survey; the source may revise the latest month."
                    ),
                }
            )

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

    df_land_disposals = (
        raw_land_disposals
        if raw_land_disposals is not None
        else _safe_fetch("Land disposals (C&SD E704)", fetch_land_disposals)
    )
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
    for health_row in (
        _new_source_health(df_shkp_quarterly, source_id="shkp_quarterly", dataset="SHKP Quarterly property events", now=now, note="Issuer headline events; property relevance and project aliases are heuristic.") if not df_shkp_quarterly.empty else None,
        _new_source_health(df_shkp_quarterly_facts, source_id="shkp_quarterly", dataset="SHKP Quarterly numeric facts", now=now, note="Bounded PDF text extraction of explicit units/areas/rates/milestones; not revenue or ownership.") if not df_shkp_quarterly_facts.empty else None,
        _new_source_health(df_shkp_commercial_assets, source_id="shkp_commercial_assets", dataset="SHKP Hong Kong commercial asset master", now=now, note="Current/annual-report/pipeline asset observations; no asset-level rent or NOI is inferred.") if not df_shkp_commercial_assets.empty else None,
        _new_source_health(df_cnsd_retail_control, source_id="cnsd_retail_sales_control", dataset="C&SD retail sales control", now=now, note="Economy-wide retail value/volume indices; not SHKP tenant sales.") if not df_cnsd_retail_control.empty else None,
        _new_source_health(df_tourism_occupancy, source_id="tourism_hotel_controls", dataset="Tourism hotel occupancy", now=now, note="Rolling five-year hotel-category occupancy; not SHKP hotel occupancy.") if not df_tourism_occupancy.empty else None,
        _new_source_health(df_tourism_adr, source_id="tourism_hotel_controls", dataset="Tourism hotel achieved room rate", now=now, note="Rolling five-year industry average room rate; not SHKP ADR.") if not df_tourism_adr.empty else None,
        _new_source_health(df_tourism_rooms, source_id="tourism_hotel_controls", dataset="Tourism hotel room supply", now=now, note="The public file currently ends at 2024-06; retained as a stale catalog/control input until the publisher updates it.", record_type="Catalog", status_override="Stale") if not df_tourism_rooms.empty else None,
        _new_source_health(df_rvd_office_vacancy, source_id="rvd_commercial_controls", dataset="RVD office vacancy annual", now=now, note="Historical year-end grade-level office vacancy; market control only.") if not df_rvd_office_vacancy.empty else None,
        _new_source_health(df_rvd_commercial_stock, source_id="rvd_commercial_controls", dataset="RVD commercial stock/vacancy district", now=now, note="Latest annual district snapshot; source does not provide a monthly history here.") if not df_rvd_commercial_stock.empty else None,
        _new_source_health(df_rvd_commercial_forecast, source_id="rvd_commercial_controls", dataset="RVD commercial forecast completions", now=now, note="Latest annual district forecast snapshot; future-dated by design and not SHKP pipeline.", record_type="Catalog", status_override="Catalog") if not df_rvd_commercial_forecast.empty else None,
    ):
        if health_row:
            health.append(health_row)
    if shkp_financial_bridge_rows:
        bridge_periods = pd.to_datetime(
            [row.get("period") for row in shkp_financial_bridge_rows], errors="coerce"
        ).dropna()
        latest_bridge = bridge_periods.max().strftime("%Y-%m-%d") if not bridge_periods.empty else "—"
        validation_status = (
            str(df_shkp_financial_coverage.iloc[0].get("validation_status"))
            if not df_shkp_financial_coverage.empty
            else "available"
        )
        health.append(
            {
                "source": PUBLIC_SOURCES["shkp_financial_bridge"]["label"],
                "dataset": "SHKP HK business financial bridge",
                "type": "Measure",
                # Carried-forward rows are real, but they are not this build's
                # rows, and a health table that calls them Healthy is worse than
                # no health table.
                "status": (
                    "Stale"
                    if "shkp_hk_financial_bridge" in carried_forward_datasets
                    else "Healthy" if validation_status in {"valid", "available"} else "Degraded"
                ),
                "latest_observation": latest_bridge,
                "records": len(shkp_financial_bridge_rows),
                "freshness": (
                    "Previous artifact snapshot"
                    if "shkp_hk_financial_bridge" in carried_forward_datasets
                    else "Research snapshot"
                ),
                "notes": (
                    (
                        f"{RUNNER_UNAVAILABLE_DATASETS['shkp_hk_financial_bridge'][1]} was unavailable "
                        "in this build, so the last published rows were retained. "
                    )
                    if "shkp_hk_financial_bridge" in carried_forward_datasets
                    else ""
                ) + (
                    "Official group/segment facts, HK recurring portfolio facts, selected 0016.HK actuals, "
                    "consensus and PIT diagnostics; no project-level HK revenue split is inferred."
                ),
            }
        )
    if not df_shkp_sales_handover_phase.empty:
        timing_dates = pd.to_datetime(
            df_shkp_sales_handover_phase.get("sales_period_end", pd.Series(dtype="string")),
            errors="coerce",
        ).dropna()
        health.append(
            {
                "source": PUBLIC_SOURCES["shkp_sales_handover_bridge"]["label"],
                "dataset": "SHKP sales / handover / revenue timing bridge",
                "type": "Measure",
                "status": "Research",
                "latest_observation": timing_dates.max().strftime("%Y-%m-%d") if not timing_dates.empty else "—",
                "records": int(len(df_shkp_sales_handover_phase)),
                "freshness": "Normalized snapshot",
                "notes": "Gross SRPE activity aligned to handover evidence and planned windows; no phase-level revenue allocation.",
            }
        )
    if srpe_developer_monthly_rows:
        srpe_latest_date = max(row["date"] for row in srpe_developer_monthly_rows)
        health.append(
            {
                "source": PUBLIC_SOURCES["srpe_sales"]["label"],
                "dataset": "SRPE phase-level first-hand sales signals",
                "type": "Measure",
                "status": "Healthy",
                "latest_observation": srpe_latest_date,
                "records": int(len(df_srpe_signals)),
                "freshness": "Published snapshot",
                "notes": "Six explicitly registered phases; attributable sales use the ownership registry and sell-through uses unique active units.",
            }
        )
    if shkp_leading_history_rows:
        health.append(
            {
                "source": PUBLIC_SOURCES["srpe_sales"]["label"],
                "dataset": "SHKP-wide SRPE project leading indicators",
                "type": "Measure",
                "status": "Healthy",
                "latest_observation": shkp_leading_history_rows[-1]["date"],
                "records": int(len(df_shkp_leading_signals)),
                "freshness": "Published snapshot",
                "notes": f"{shkp_leading_phase_count} candidate phases; raw contract activity only. Ownership intervals remain blocked.",
            }
        )

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
                    "project_url": r.get("project_url"),
                    "location_district": r.get("location_district"),
                    "status": r.get("status"),
                    "estimated_total_units": float(r["estimated_total_units"]) if pd.notna(r.get("estimated_total_units")) else None,
                    "remaining_units": float(r["remaining_units"]) if pd.notna(r.get("remaining_units")) else None,
                    "on_sale_units": float(r["on_sale_units"]) if pd.notna(r.get("on_sale_units")) else None,
                    "sold_units": float(r["sold_units"]) if pd.notna(r.get("sold_units")) else None,
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
    midland_estate_rows = _carry_forward_if_runner_unavailable(
        midland_estate_rows, "midland_top_estates", carried_forward_datasets
    )

    additional_coverage = []
    for label, dataset_label, rows_or_frame, source_label in (
        ("28Hse", "EPI / ERI", epi_eri_rows, "28Hse EPI / ERI Historical Index"),
        ("Agency transactions", "Centaline / Midland / 28Hse transactions", transaction_pulse_rows, "Deduplicated agency transaction feeds"),
        ("Land Registry", "Monthly facts + ASP series", landreg_asp_rows, "Land Registry Monthly Statistics (JSON)"),
        ("Buildings Department", "Monthly digest + project lifecycle", bd_monthly_stats_rows + bd_supply_table_rows, "Buildings Department Monthly Digest / Project Lifecycle"),
        ("Buildings Department history", "Md52-Md56 stage aggregates", bd_supply_history_rows, "Buildings Department Monthly Digest PDF archive (Section 1 aggregate tables)"),
        ("SRPE pilot", "Phase-level first-hand sales signals", srpe_developer_monthly_rows, "Sales of First-hand Residential Properties Electronic Platform (SRPE)"),
    ):
        record_count = len(rows_or_frame)
        fallback_reason = (
            df_bd_supply_history.attrs.get("dashboard_fallback_reason")
            if label == "Buildings Department history"
            else None
        )
        if not record_count:
            coverage_status = "No data this run"
            coverage_notes = f"{source_label}; live fetch returned no usable rows this run."
        elif fallback_reason:
            coverage_status = "Stale"
            coverage_notes = f"{source_label}; live cache/fetch was unavailable, so the {fallback_reason} was retained."
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
                "latest_observation": max((row["date"] for row in rows_or_frame), default="—") if label == "SRPE pilot" else "—",
                "records": record_count,
                "freshness": (
                    "Published snapshot"
                    if label == "SRPE pilot" and record_count
                    else ("Previous artifact snapshot" if fallback_reason else ("Live at build time" if record_count else "Fetch returned no rows"))
                ),
                "notes": coverage_notes,
            }
        )

    for dataset_key, row_count in carried_forward_datasets.items():
        # The SHKP bridge already owns a source_health row, marked Stale above.
        # The coverage table is a source inventory, not a list of every surface
        # using a source, so do not alias it here.
        if dataset_key == "shkp_hk_financial_bridge":
            continue
        label, upstream = RUNNER_UNAVAILABLE_DATASETS[dataset_key]
        additional_coverage.append(
            {
                "source": label,
                "dataset": dataset_key,
                "type": "Measure",
                "status": "Stale",
                "latest_observation": "—",
                "records": row_count,
                "freshness": "Previous artifact snapshot",
                "notes": (
                    f"{upstream} was unavailable in this build, so the last "
                    "published rows were retained. The figures are real but "
                    "not refreshed this run."
                ),
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
        "kpi_srpe_attributable_sales": [srpe_sales_kpi] if srpe_sales_kpi else [],
        "kpi_srpe_sales_units": [srpe_units_kpi] if srpe_units_kpi else [],
        "kpi_srpe_sell_through": [srpe_sell_through_kpi] if srpe_sell_through_kpi else [],
        "kpi_srpe_projects": [srpe_projects_kpi] if srpe_projects_kpi else [],
        "ccl_history": _series_records(frames["ccl"], "ccl_index"),
        "mhpi_history": _series_records(frames["mhpi"], "mhpi_overall"),
        "confidence_history": _series_records(frames["confidence"], "confidence_index"),
        "cci_history": cci_rows,
        "cri_history": cri_rows,
        "cri_yield_history": cri_yield_rows,
        "csi_history": csi_rows,
        "rvd_office_history": rvd_office_rows,
        "rvd_retail_history": rvd_retail_rows,
        "rvd_office_vacancy_history": rvd_office_vacancy_rows,
        "rvd_office_stock_vacancy_history": rvd_office_stock_rows,
        "rvd_commercial_vacancy_history": rvd_commercial_vacancy_rows,
        "rvd_commercial_forecast_history": rvd_commercial_forecast_rows,
        "cnsd_retail_sales_history": cnsd_retail_rows,
        "tourism_hotel_occupancy_history": tourism_occupancy_rows,
        "tourism_hotel_adr_history": tourism_adr_rows,
        "tourism_hotel_rooms_history": tourism_rooms_rows,
        "shkp_quarterly_property_events": shkp_quarterly_event_rows,
        "shkp_quarterly_numeric_facts": shkp_quarterly_fact_rows,
        "shkp_hk_commercial_asset_master": shkp_commercial_asset_rows,
        "shkp_hk_financial_bridge": shkp_financial_bridge_rows,
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
        "srpe_developer_monthly_sales": srpe_developer_monthly_rows,
        "srpe_project_sell_through": srpe_sell_through_rows,
        "srpe_latest_project_snapshot": srpe_latest_project_rows,
        "srpe_project_signal_history": srpe_signal_history_rows,
        "shkp_leading_signal_history": shkp_leading_history_rows,
        "shkp_leading_phase_latest": shkp_leading_latest_rows,
        "shkp_28hse_reconciliation": [
            {
                key: (None if pd.isna(value) else value)
                for key, value in row.items()
            }
            for row in df_28hse_reconciliation.to_dict("records")
        ] if not df_28hse_reconciliation.empty else [],
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

    if srpe_sales_kpi:
        cards.append(
            {
                "id": "srpe_attributable_sales_card",
                "description": "Latest monthly contract sales attributable to the listed-company ownership share in the tracked phases; HK$ million.",
                "dataset": "kpi_srpe_attributable_sales",
                "sourceId": "srpe_sales",
                "metrics": [
                    {"label": "Attributable Sales (HK$m)", "field": "latest", "format": "number"},
                    {"label": "MoM", "field": "period_change", "format": "percent", "signed": True},
                    {"label": "YoY", "field": "year_change", "format": "percent", "signed": True},
                ],
            }
        )
    if srpe_units_kpi:
        cards.append(
            {
                "id": "srpe_sales_units_card",
                "description": "Gross units recorded in the latest SRPE transaction-register month across the tracked phases.",
                "dataset": "kpi_srpe_sales_units",
                "sourceId": "srpe_sales",
                "metrics": [
                    {"label": "Units Sold (gross)", "field": "latest", "format": "number"},
                    {"label": "MoM", "field": "period_change", "format": "percent", "signed": True},
                    {"label": "YoY", "field": "year_change", "format": "percent", "signed": True},
                ],
            }
        )
    if srpe_sell_through_kpi:
        cards.append(
            {
                "id": "srpe_sell_through_card",
                "description": "Weighted sell-through across the latest available snapshot for each tracked phase; active units divided by published phase inventory.",
                "dataset": "kpi_srpe_sell_through",
                "sourceId": "srpe_sales",
                "metrics": [
                    {"label": "Sell-through (%)", "field": "latest", "format": "number"},
                    {"label": "Phases", "field": "projects", "format": "number"},
                ],
            }
        )
    if srpe_projects_kpi:
        cards.append(
            {
                "id": "srpe_projects_card",
                "description": "Explicit SRPE phase-level projects currently linked to listed-company ownership in the pilot registry.",
                "dataset": "kpi_srpe_projects",
                "sourceId": "srpe_sales",
                "metrics": [{"label": "Tracked Phases", "field": "latest", "format": "number"}],
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

    if srpe_developer_monthly_rows:
        charts.append(
            {
                "id": "srpe_developer_sales_chart",
                "title": "SRPE — Top Developers by Attributable First-hand Contract Sales",
                "subtitle": "Monthly contract sales attributable to the listed-company ownership share; chart shows the three largest developers by cumulative pilot-window sales, in HK$ million.",
                "type": "line",
                "intent": "trend",
                "dataset": "srpe_developer_monthly_sales",
                "sourceId": "srpe_sales",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "Attributable sales (HK$m)"},
                    "color": {"field": "developer", "type": "nominal", "label": "Developer"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 500,
            }
        )
    if srpe_sell_through_rows:
        charts.append(
            {
                "id": "srpe_project_sell_through_chart",
                "title": "SRPE — Top Project Phases by Sell-through",
                "subtitle": "Monthly cumulative sell-through based on unique active units; chart shows the three largest phases by cumulative attributable sales, while the table retains all registered phases.",
                "type": "line",
                "intent": "trend",
                "dataset": "srpe_project_sell_through",
                "sourceId": "srpe_sales",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "Sell-through (%)"},
                    "color": {"field": "project_short_name", "type": "nominal", "label": "Project phase"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 500,
            }
        )

    if shkp_leading_history_rows:
        charts.append(
            {
                "id": "shkp_leading_contract_sales_chart",
                "title": "SHKP Project Activity — Raw Contract Sales",
                "subtitle": f"{shkp_leading_phase_count} candidate phases; gross SRPE contract activity in HK$ million, not SHKP-attributable revenue.",
                "type": "line",
                "intent": "trend",
                "dataset": "shkp_leading_signal_history",
                "sourceId": "srpe_sales",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "raw_contract_sales_hkd_m", "type": "quantitative", "label": "Raw contract activity (HK$m)"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )
        charts.append(
            {
                "id": "shkp_leading_active_units_chart",
                "title": "SHKP Project Activity — Month-end Active Units",
                "subtitle": "Sum of active units for phases whose SRPE register is covered in that month; the coverage chart below shows how many phases are actually covered.",
                "type": "line",
                "intent": "trend",
                "dataset": "shkp_leading_signal_history",
                "sourceId": "srpe_sales",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "active_units_eom", "type": "quantitative", "label": "Covered-phase active units"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )
        charts.append(
            {
                "id": "shkp_leading_coverage_chart",
                "title": "SHKP Project Activity — SRPE Register Coverage",
                "subtitle": "Covered phase count versus the candidate phase universe; months after a phase's last observed register are marked not covered, not zero sales.",
                "type": "line",
                "intent": "trend",
                "dataset": "shkp_leading_signal_history",
                "sourceId": "srpe_sales",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "covered_phase_count", "type": "quantitative", "label": "Covered phases"},
                },
                "valueFormat": "number",
                "layout": "full",
            }
        )

    if cnsd_retail_rows:
        charts.append(
            {
                "id": "cnsd_retail_sales_control_chart",
                "title": "Commercial Control — C&SD retail sales",
                "subtitle": "Monthly all-retail value and volume indices; economy-wide demand control, not SHKP tenant sales.",
                "type": "line",
                "intent": "comparison",
                "dataset": "cnsd_retail_sales_history",
                "sourceId": "cnsd_retail_sales_control",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "Index"},
                    "color": {"field": "series", "type": "nominal", "label": "Measure"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 1_500,
            }
        )
    if tourism_occupancy_rows:
        charts.append(
            {
                "id": "tourism_hotel_occupancy_control_chart",
                "title": "Commercial Control — Hong Kong hotel occupancy",
                "subtitle": "Monthly occupancy by hotel category; industry control, not SHKP hotel occupancy.",
                "type": "line",
                "intent": "comparison",
                "dataset": "tourism_hotel_occupancy_history",
                "sourceId": "tourism_hotel_controls",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "Occupancy (%)"},
                    "color": {"field": "series", "type": "nominal", "label": "Hotel category"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 500,
            }
        )
    if tourism_adr_rows:
        charts.append(
            {
                "id": "tourism_hotel_adr_control_chart",
                "title": "Commercial Control — Hong Kong hotel achieved room rate",
                "subtitle": "Monthly industry average achieved room rate by hotel category; not SHKP asset ADR.",
                "type": "line",
                "intent": "comparison",
                "dataset": "tourism_hotel_adr_history",
                "sourceId": "tourism_hotel_controls",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Month"},
                    "y": {"field": "value", "type": "quantitative", "label": "HKD / room"},
                    "color": {"field": "series", "type": "nominal", "label": "Hotel category"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 500,
            }
        )
    if rvd_office_vacancy_rows:
        charts.append(
            {
                "id": "rvd_office_vacancy_control_chart",
                "title": "Commercial Control — RVD office vacancy",
                "subtitle": "Historical year-end vacancy by office grade; annual observations, not SHKP occupancy.",
                "type": "line",
                "intent": "comparison",
                "dataset": "rvd_office_vacancy_history",
                "sourceId": "rvd_commercial_controls",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Year"},
                    "y": {"field": "value", "type": "quantitative", "label": "Vacancy (%)"},
                    "color": {"field": "series", "type": "nominal", "label": "Grade"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 500,
            }
        )
    if rvd_commercial_vacancy_rows:
        charts.append(
            {
                "id": "rvd_commercial_vacancy_control_chart",
                "title": "Commercial Control — RVD private-commercial vacancy",
                "subtitle": "Latest annual district vacancy snapshot; market control, not SHKP mall occupancy.",
                "type": "line",
                "intent": "comparison",
                "dataset": "rvd_commercial_vacancy_history",
                "sourceId": "rvd_commercial_controls",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Year"},
                    "y": {"field": "value", "type": "quantitative", "label": "Vacancy (%)"},
                    "color": {"field": "series", "type": "nominal", "label": "Region"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 500,
            }
        )
    if rvd_commercial_forecast_rows:
        charts.append(
            {
                "id": "rvd_commercial_forecast_control_chart",
                "title": "Commercial Control — RVD forecast completions",
                "subtitle": "Annual private-commercial forecast completions by broad region; not SHKP pipeline capacity.",
                "type": "line",
                "intent": "trend",
                "dataset": "rvd_commercial_forecast_history",
                "sourceId": "rvd_commercial_controls",
                "encodings": {
                    "x": {"field": "date", "type": "temporal", "label": "Year"},
                    "y": {"field": "value", "type": "quantitative", "label": "Forecast completions (sqft)"},
                    "color": {"field": "series", "type": "nominal", "label": "Region"},
                },
                "valueFormat": "number",
                "layout": "full",
                "maxRows": 500,
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

    if shkp_quarterly_event_rows:
        tables.append(
            {
                "id": "shkp_quarterly_property_events_table",
                "title": "SHKP Quarterly — Hong Kong property events",
                "subtitle": "Issuer headline events classified from quarterly PDFs; event dates may use a quarter-end proxy when no publication date is exposed.",
                "dataset": "shkp_quarterly_property_events",
                "sourceId": "shkp_quarterly",
                "defaultSort": {"field": "date", "direction": "desc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "date", "label": "Date", "type": "date"},
                    {"field": "quarter", "label": "Quarter", "type": "text"},
                    {"field": "event_type", "label": "Event type", "type": "text"},
                    {"field": "asset_class", "label": "Asset class", "type": "text"},
                    {"field": "geography", "label": "Geography", "type": "text"},
                    {"field": "project", "label": "Project", "type": "text"},
                    {"field": "title", "label": "Issuer headline", "type": "text"},
                    {"field": "date_semantics", "label": "Date semantics", "type": "text"},
                ],
            }
        )
    if shkp_quarterly_fact_rows:
        tables.append(
            {
                "id": "shkp_quarterly_numeric_facts_table",
                "title": "SHKP Quarterly — extracted Hong Kong numeric facts",
                "subtitle": "Bounded PDF-text facts with page and source sentence; research context only, not revenue or ownership.",
                "dataset": "shkp_quarterly_numeric_facts",
                "sourceId": "shkp_quarterly",
                "defaultSort": {"field": "date", "direction": "desc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "date", "label": "Date", "type": "date"},
                    {"field": "quarter", "label": "Quarter", "type": "text"},
                    {"field": "project", "label": "Project", "type": "text"},
                    {"field": "asset_class", "label": "Asset class", "type": "text"},
                    {"field": "fact_type", "label": "Fact type", "type": "text"},
                    {"field": "value", "label": "Value", "format": "number"},
                    {"field": "unit", "label": "Unit", "type": "text"},
                    {"field": "confidence", "label": "Confidence", "type": "text"},
                    {"field": "page", "label": "Page", "format": "number"},
                    {"field": "fact_text", "label": "Evidence", "type": "text"},
                ],
            }
        )
    if shkp_commercial_asset_rows:
        tables.append(
            {
                "id": "shkp_hk_commercial_asset_master_table",
                "title": "SHKP — Hong Kong commercial asset master",
                "subtitle": "Current directory, completed-property and pipeline observations; repeated assets remain separated by source layer.",
                "dataset": "shkp_hk_commercial_asset_master",
                "sourceId": "shkp_commercial_assets",
                "defaultSort": {"field": "asset_name", "direction": "asc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "asset_name", "label": "Asset", "type": "text"},
                    {"field": "asset_class", "label": "Class", "type": "text"},
                    {"field": "asset_subtype", "label": "Subtype", "type": "text"},
                    {"field": "status", "label": "Status", "type": "text"},
                    {"field": "source_layer", "label": "Source layer", "type": "text"},
                    {"field": "district", "label": "District", "type": "text"},
                    {"field": "group_interest_pct", "label": "Group interest (%)", "format": "number"},
                    {"field": "as_of_date", "label": "As of", "type": "date"},
                    {"field": "completion_window", "label": "Completion window", "type": "text"},
                    {"field": "total_gfa_sqft", "label": "Total GFA (sqft)", "format": "number"},
                    {"field": "coverage_status", "label": "Coverage", "type": "text"},
                ],
            }
        )
    if shkp_financial_bridge_rows:
        tables.append(
            {
                "id": "shkp_hk_financial_bridge_table",
                "title": "SHKP — Hong Kong business financial bridge",
                "subtitle": "Official group/segment facts, HK recurring portfolio observations, selected 0016.HK actuals, consensus and PIT diagnostics. Row types must not be summed together.",
                "dataset": "shkp_hk_financial_bridge",
                "sourceId": "shkp_financial_bridge",
                "defaultSort": {"field": "period", "direction": "desc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "row_type", "label": "Row type", "type": "text"},
                    {"field": "period", "label": "Period", "type": "text"},
                    {"field": "target_period", "label": "Target recognition period", "type": "text"},
                    {"field": "period_type", "label": "Period type", "type": "text"},
                    {"field": "layer", "label": "Layer", "type": "text"},
                    {"field": "geography", "label": "Geography", "type": "text"},
                    {"field": "asset_class", "label": "Asset class", "type": "text"},
                    {"field": "metric", "label": "Metric", "type": "text"},
                    {"field": "statistic", "label": "Statistic", "type": "text"},
                    {"field": "value", "label": "Value", "format": "number"},
                    {"field": "comparison_value", "label": "Comparison value", "format": "number"},
                    {"field": "difference_pct", "label": "Difference (%)", "format": "number"},
                    {"field": "unit", "label": "Unit", "type": "text"},
                    {"field": "currency", "label": "Currency", "type": "text"},
                    {"field": "status", "label": "Status", "type": "text"},
                    {"field": "point_in_time_quality", "label": "PIT quality", "type": "text"},
                    {"field": "model_use", "label": "Model use", "type": "text"},
                    {"field": "source", "label": "Source", "type": "text"},
                    {"field": "caveat", "label": "Caveat", "type": "text"},
                ],
            }
        )

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
        if any(row.get("remaining_units") is not None for row in new_project_rows):
            _new_project_columns.append({"field": "remaining_units", "label": "Remaining", "format": "number"})
        if any(row.get("on_sale_units") is not None for row in new_project_rows):
            _new_project_columns.append({"field": "on_sale_units", "label": "On Sale", "format": "number"})
        if any(row.get("sold_units") is not None for row in new_project_rows):
            _new_project_columns.append({"field": "sold_units", "label": "Sold", "format": "number"})
        if any(row.get("status") for row in new_project_rows):
            _new_project_columns.append({"field": "status", "label": "Status", "type": "text"})
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

    if shkp_leading_latest_rows:
        tables.append(
            {
                "id": "shkp_leading_phase_latest_table",
                "title": "SHKP Project Activity — Latest Phase Snapshot",
                "subtitle": "Leading indicators only. Handover fields are separate annual-report / planned-window / BD snapshot evidence; no row is treated as SHKP-attributable sales or phase-level revenue.",
                "dataset": "shkp_leading_phase_latest",
                "sourceId": "srpe_sales",
                "defaultSort": {"field": "latest_period", "direction": "desc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "srpe_development_id", "label": "SRPE Phase", "type": "text"},
                    {"field": "development_name", "label": "Development", "type": "text"},
                    {"field": "phase_name", "label": "Phase", "type": "text"},
                    {"field": "candidate_status", "label": "Candidate Status", "type": "text"},
                    {"field": "latest_period", "label": "Latest", "type": "date"},
                    {"field": "sales_units_gross", "label": "Gross PASP Units", "format": "number"},
                    {"field": "raw_contract_sales_hkd", "label": "Raw Sales (HK$)", "format": "number"},
                    {"field": "active_units_eom", "label": "Active Units EOM", "format": "number"},
                    {"field": "published_inventory_units", "label": "Published Inventory", "format": "number"},
                    {"field": "sell_through_pct_eom", "label": "Sell-through %", "format": "percent"},
                    {"field": "month_status", "label": "Month Status", "type": "text"},
                    {"field": "coverage_end", "label": "Register Coverage End", "type": "date"},
                    {"field": "ownership_review_status", "label": "Ownership Review", "type": "text"},
                    {"field": "handover_disclosure_status", "label": "Handover Evidence", "type": "text"},
                    {"field": "completion_window", "label": "Completion Window", "type": "text"},
                    {"field": "bd_occupation_status", "label": "BD OP Snapshot", "type": "text"},
                ],
            }
        )

    if not df_28hse_reconciliation.empty:
        tables.append(
            {
                "id": "shkp_28hse_reconciliation_table",
                "title": "28Hse ↔ SRPE Reconciliation Coverage",
                "subtitle": "Exact-unique alias matches only; non-matches are coverage gaps, not zero inventory.",
                "dataset": "shkp_28hse_reconciliation",
                "sourceId": "hse28_new_projects",
                "defaultSort": {"field": "match_status", "direction": "asc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "row_side", "label": "Side", "type": "text"},
                    {"field": "hse28_project_name", "label": "28Hse Project", "type": "text"},
                    {"field": "srpe_development_id", "label": "SRPE Phase", "type": "text"},
                    {"field": "srpe_phase_name", "label": "SRPE Phase Name", "type": "text"},
                    {"field": "hse28_status", "label": "28Hse Status", "type": "text"},
                    {"field": "hse28_total_units", "label": "28Hse Total", "format": "number"},
                    {"field": "hse28_remaining_units", "label": "28Hse Remaining", "format": "number"},
                    {"field": "hse28_sold_units", "label": "28Hse Sold", "format": "number"},
                    {"field": "srpe_active_units_eom", "label": "SRPE Active EOM", "format": "number"},
                    {"field": "srpe_published_inventory_units", "label": "SRPE Inventory", "format": "number"},
                    {"field": "match_status", "label": "Match Status", "type": "text"},
                    {"field": "coverage_note", "label": "Coverage Note", "type": "text"},
                ],
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

    if srpe_latest_project_rows:
        tables.append(
            {
                "id": "srpe_latest_project_snapshot_table",
                "title": "SRPE — Latest Project Sales Snapshot",
                "subtitle": "Latest available observation for each explicitly registered phase; ownership-adjusted sales are shown in the KPI and developer chart above.",
                "dataset": "srpe_latest_project_snapshot",
                "sourceId": "srpe_sales",
                "defaultSort": {"field": "sell_through_pct", "direction": "desc"},
                "density": "dense",
                "layout": "full",
                "columns": [
                    {"field": "developer", "label": "Developer", "type": "text"},
                    {"field": "project_name", "label": "Project phase", "type": "text"},
                    {"field": "latest_period", "label": "Latest month", "type": "date"},
                    {"field": "sales_units_gross", "label": "Gross units (month)", "format": "number"},
                    {"field": "cumulative_unique_active_units", "label": "Active sold units", "format": "number"},
                    {"field": "total_residential_properties", "label": "Published inventory", "format": "number"},
                    {"field": "sell_through_pct", "label": "Sell-through (%)", "format": "number"},
                    {"field": "weighted_avg_transaction_price_hkd", "label": "Weighted avg price (HK$)", "format": "number"},
                    {"field": "ownership_pct", "label": "Ownership (%)", "format": "number"},
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
    if rvd_office_vacancy_rows:
        blocks.append({"id": "rvd_office_vacancy_control_block", "type": "chart", "chartId": "rvd_office_vacancy_control_chart"})
    if rvd_commercial_vacancy_rows:
        blocks.append({"id": "rvd_commercial_vacancy_control_block", "type": "chart", "chartId": "rvd_commercial_vacancy_control_chart"})
    if rvd_commercial_forecast_rows:
        blocks.append({"id": "rvd_commercial_forecast_control_block", "type": "chart", "chartId": "rvd_commercial_forecast_control_chart"})
    if cnsd_retail_rows:
        blocks.append({"id": "cnsd_retail_control_block", "type": "chart", "chartId": "cnsd_retail_sales_control_chart"})
    if tourism_occupancy_rows:
        blocks.append({"id": "tourism_occupancy_control_block", "type": "chart", "chartId": "tourism_hotel_occupancy_control_chart"})
    if tourism_adr_rows:
        blocks.append({"id": "tourism_adr_control_block", "type": "chart", "chartId": "tourism_hotel_adr_control_chart"})
    if shkp_quarterly_event_rows:
        blocks.append({"id": "shkp_quarterly_events_block", "type": "table", "tableId": "shkp_quarterly_property_events_table"})
    if shkp_commercial_asset_rows:
        blocks.append({"id": "shkp_commercial_asset_master_block", "type": "table", "tableId": "shkp_hk_commercial_asset_master_table"})

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
    # The 28Hse catalogue remains in the snapshot as a source-backed lookup
    # table, but is not rendered on the monitoring page: it is a wide,
    # non-time-series catalogue and causes the portable mobile layout to grow
    # horizontally. The charts above and the SRPE project snapshot are the
    # actionable views for this surface.
    if midland_estate_rows:
        blocks.append({"id": "midland_top_estates_block", "type": "table", "tableId": "midland_top_estates_table", "layout": "half"})
    # Keep the raw Buildings Department digest rows in the snapshot for audit,
    # but do not render this wide scratch table in the portable page. The
    # project-lifecycle and archive-backed history charts above are the useful
    # monitoring views; the raw table's long comma-separated values create a
    # horizontal overflow on the 390px mobile layout.

    if srpe_developer_monthly_rows:
        blocks.append(
            {
                "id": "srpe_developer_signals_section",
                "type": "markdown",
                "body": "## Residential developer sales signals\n\nSRPE phase-level transaction registers are linked to listed developers through the explicit ownership registry. These are contract-sales signals, not booked revenue or cash receipts.",
            }
        )
        blocks.append({"id": "srpe_developer_sales_chart_block", "type": "chart", "chartId": "srpe_developer_sales_chart"})
        blocks.append({"id": "srpe_project_sell_through_chart_block", "type": "chart", "chartId": "srpe_project_sell_through_chart"})
    if srpe_latest_project_rows:
        blocks.append({"id": "srpe_latest_project_snapshot_block", "type": "table", "tableId": "srpe_latest_project_snapshot_table"})

    # These SHKP-wide charts/tables are declared conditionally above, so they
    # must also be added to manifest.blocks. The portable renderer renders
    # blocks (not every chart/table declaration) and would otherwise omit the
    # new leading-indicator views while still showing their source-health row.
    if shkp_leading_history_rows:
        blocks.append(
            {
                "id": "shkp_leading_indicators_section",
                "type": "markdown",
                "body": f"## SHKP project activity monitoring\n\nThese {shkp_leading_phase_count} candidate phases are raw SRPE contract-activity leading indicators only. They are not SHKP-attributable sales or booked revenue until a dated ownership interval is approved.",
            }
        )
        blocks.append({"id": "shkp_leading_contract_sales_block", "type": "chart", "chartId": "shkp_leading_contract_sales_chart"})
        blocks.append({"id": "shkp_leading_active_units_block", "type": "chart", "chartId": "shkp_leading_active_units_chart"})
        blocks.append({"id": "shkp_leading_coverage_block", "type": "chart", "chartId": "shkp_leading_coverage_chart"})
    if shkp_leading_latest_rows:
        blocks.append({"id": "shkp_leading_phase_latest_block", "type": "table", "tableId": "shkp_leading_phase_latest_table"})
    if not df_28hse_reconciliation.empty:
        blocks.append({"id": "shkp_28hse_reconciliation_block", "type": "table", "tableId": "shkp_28hse_reconciliation_table"})
    if shkp_quarterly_fact_rows:
        blocks.append({"id": "shkp_quarterly_numeric_facts_block", "type": "table", "tableId": "shkp_quarterly_numeric_facts_table"})
    if shkp_financial_bridge_rows:
        blocks.append(
            {
                "id": "shkp_hk_financial_bridge_section",
                "type": "markdown",
                "body": "## SHKP Hong Kong business financial bridge\n\nThis is a monitoring/evidence table, not a synthetic HK-only revenue series. Group and segment disclosures may include the Group's share of joint ventures and associates; sibling financial-data actuals currently lack complete original announcement dates; consensus is a current snapshot only.",
            }
        )
        blocks.append({"id": "shkp_hk_financial_bridge_block", "type": "table", "tableId": "shkp_hk_financial_bridge_table"})

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
            "description": "A source-backed snapshot of residential price, rent, market confidence, supply, financing, and first-hand developer sales signals.",
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
        "overall_status": "Degraded" if any(row.get("status") == "Stale" for row in coverage) else "Healthy",
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


def _load_dataset_from_committed_artifact(dataset_key: str) -> pd.DataFrame:
    """Load an optional dataset from the last committed English artifact."""
    try:
        data = json.loads(_COMMITTED_ARTIFACT_PATH.read_text(encoding="utf-8"))
        rows = data["snapshot"]["datasets"][dataset_key]
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return pd.DataFrame()
    return pd.DataFrame(rows) if isinstance(rows, list) else pd.DataFrame()


# Datasets whose only upstream cannot exist on a GitHub runner. The SHKP
# financial bridge reads the sibling financial-data DuckDB, which CI never
# checks out; Midland is deliberately skipped there (HK_RE_SKIP_MIDLAND) and
# WAF-blocked besides. Neither absence is a data problem to fix here -- but
# rebuilding without them drops the dataset key outright, and the refresh
# guard correctly reads a vanished dataset as a regression and rejects the
# whole artifact. That is why CI last published this dashboard on 2026-08-12
# while every other sector in the same job kept refreshing daily, and why a
# Buildings Department history repaired upstream still could not reach the
# published chart. Serve the last published rows for these two and mark them
# stale, the way HKMA, SRPE and the BD history already do.
RUNNER_UNAVAILABLE_DATASETS = {
    "shkp_hk_financial_bridge": (
        "SHKP financial bridge",
        "sibling financial-data DuckDB (not checked out in CI)",
    ),
    "midland_top_estates": (
        "Midland top estates",
        "Midland market-insight scrape (skipped in CI, WAF-blocked)",
    ),
}


def _load_rows_from_committed_artifact(dataset_key: str) -> list[dict[str, Any]]:
    """Read a dataset out of the last committed artifact as raw JSON rows.

    Deliberately not the DataFrame reader above: these rows go straight back
    into the artifact, and a round-trip through pandas turns absent values into
    NaN, which json.dumps writes as the literal ``NaN`` that no JSON parser
    accepts.
    """
    try:
        data = json.loads(_COMMITTED_ARTIFACT_PATH.read_text(encoding="utf-8"))
        rows = data["snapshot"]["datasets"][dataset_key]
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _carry_forward_if_runner_unavailable(
    rows: list[dict[str, Any]],
    dataset_key: str,
    carried: dict[str, int],
) -> list[dict[str, Any]]:
    """Keep a structurally-absent dataset alive from the last published build."""
    if rows:
        return rows
    previous = _load_rows_from_committed_artifact(dataset_key)
    if not previous:
        return rows
    carried[dataset_key] = len(previous)
    print(
        f"  [hk_real_estate] {dataset_key} unavailable this build; "
        f"serving {len(previous)} rows from the last committed artifact.",
        file=sys.stderr,
    )
    return previous


def _mark_artifact_fallback(frame: pd.DataFrame, reason: str) -> pd.DataFrame:
    """Attach non-serialized provenance for a stale artifact fallback."""
    result = frame.copy()
    result.attrs["dashboard_fallback_reason"] = reason
    return result


def _canonicalize_hkma_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Accept both historical HKMA cache column spellings."""
    if frame.empty:
        return frame
    result = frame.copy()
    for canonical, legacy in {
        "hibor_pricing_pct_share": "hibor_pricing_pct",
        "blr_pricing_pct_share": "blr_pricing_pct",
        "fixed_pricing_pct_share": "fixed_pricing_pct",
    }.items():
        if canonical not in result.columns and legacy in result.columns:
            result[canonical] = result[legacy]
    return result


def _load_hkma_from_committed_artifact() -> pd.DataFrame:
    """Reconstruct the raw HKMA frame from the last valid dashboard artifact.

    The normalized HKMA cache is intentionally disposable in CI.  The
    committed artifact is therefore the second-level fallback when the clean
    runner has no Parquet cache and the official API returns an empty response.
    The conversion keeps the source's monthly grain and does not invent any
    values; it only joins the already-published wide activity rows to the
    already-published long-format rate/LTV/credit views.
    """
    activity = _load_dataset_from_committed_artifact("hkma_mortgage_activity")
    if activity.empty:
        return pd.DataFrame()

    frame = activity.rename(columns={"date": "observation_date"}).copy()
    frame["observation_date"] = pd.to_datetime(frame["observation_date"], errors="coerce").dt.strftime("%Y-%m-01")
    frame = frame.dropna(subset=["observation_date"])

    def merge_series(dataset_key: str, series_map: dict[str, str]) -> None:
        nonlocal frame
        rows = _load_dataset_from_committed_artifact(dataset_key)
        if rows.empty or not {"date", "series", "value"}.issubset(rows.columns):
            return
        rows = rows.copy()
        rows["observation_date"] = pd.to_datetime(rows["date"], errors="coerce").dt.strftime("%Y-%m-01")
        rows["field"] = rows["series"].map(series_map)
        rows = rows.dropna(subset=["observation_date", "field"])
        if rows.empty:
            return
        pivot = rows.pivot_table(index="observation_date", columns="field", values="value", aggfunc="last").reset_index()
        frame = frame.merge(pivot, on="observation_date", how="left")

    merge_series(
        "hkma_mortgage_rate_mix",
        {
            "HIBOR": "hibor_pricing_pct_share",
            "BLR (Prime)": "blr_pricing_pct_share",
            "Fixed": "fixed_pricing_pct_share",
            "Other": "other_pricing_pct_share",
        },
    )
    merge_series("hkma_ltv_history", {"Average LTV (%)": "average_ltv_ratio_pct"})
    merge_series(
        "hkma_credit_quality_history",
        {
            "Delinquency Ratio (%)": "delinquency_ratio_pct",
            "Rescheduled Loan Ratio (%)": "rescheduled_loan_ratio_pct",
        },
    )
    frame["source_agency"] = "Hong Kong Monetary Authority (HKMA)"
    frame["period_start"] = frame["observation_date"]
    frame["period_end"] = frame["observation_date"]
    frame["publication_date"] = None
    frame["is_provisional"] = False
    return _mark_artifact_fallback(frame, "last committed artifact")


HKMA_PUBLICATION_LAG_DAYS = 25
HKMA_PUBLICATION_MARGIN_DAYS = 5

def _naive_timestamp(value: pd.Timestamp) -> pd.Timestamp:
    return (value.tz_localize(None) if value.tzinfo else value).normalize()


def _monthly_cache_is_current(
    latest_observation: pd.Timestamp,
    *,
    publication_lag_days: int,
    margin_days: int,
    now: pd.Timestamp | None = None,
) -> bool:
    """Whether a monthly cache can still be holding the newest published month.

    ``observation_date`` on these series is the FIRST day of the observed
    month, and the source publishes a month roughly ``publication_lag_days``
    after that month has ended.  Measuring plain calendar age against a flat
    day threshold therefore never works here: a cache holding the newest
    published month is already ~55 days "old" on the very day it is published,
    so any threshold small enough to catch a genuinely stale vintage also
    rejects a perfectly current one (a 45-day gate rejects every HKMA cache
    that has ever existed).  Compare against when the NEXT month is due
    instead, and start refetching ``margin_days`` early so an early
    publication is still picked up.
    """
    reference = pd.Timestamp.now().normalize() if now is None else _naive_timestamp(now)
    next_period_start = _naive_timestamp(latest_observation).replace(day=1) + pd.DateOffset(months=1)
    # The next period ends the day before the period after it starts, so its
    # publication is due one further month on, plus the source's own lag.
    next_publication_due = (
        next_period_start
        + pd.DateOffset(months=1)
        + pd.Timedelta(days=publication_lag_days)
    )
    return reference < next_publication_due - pd.Timedelta(days=margin_days)


def _hkma_fetch_regresses_history(fetched: pd.DataFrame, cached: pd.DataFrame) -> bool:
    """Whether a live fetch would shorten the history the cache already holds.

    The old code preferred the cache unconditionally, so a truncated upstream
    response could not overwrite good history.  Now that a fresh fetch wins by
    default, that protection has to be restated explicitly: a response with
    fewer rows or an older newest month is an upstream fault (pagination
    change, partial outage), not a correction.
    """
    if cached.empty or fetched.empty:
        return False
    if len(fetched) < len(cached):
        return True
    fetched_latest = _extract_latest_date(fetched)
    cached_latest = _extract_latest_date(cached)
    if fetched_latest is None or cached_latest is None:
        return False
    return _naive_timestamp(fetched_latest) < _naive_timestamp(cached_latest)


def _hkma_cache_needs_rewrite(fetched: pd.DataFrame, cached: pd.DataFrame) -> bool:
    """Whether the fetch actually advanced the cache.

    ``save_normalized_dataset`` writes an immutable run directory per call, so
    rewriting an unchanged vintage on every build just accumulates identical
    snapshots that ``load_latest_normalized`` then has to scan.
    """
    if cached.empty:
        return True
    if len(fetched) != len(cached):
        return True
    fetched_latest = _extract_latest_date(fetched)
    cached_latest = _extract_latest_date(cached)
    if fetched_latest is None or cached_latest is None:
        return True
    return _naive_timestamp(fetched_latest) != _naive_timestamp(cached_latest)


def _load_hkma_with_fallback() -> pd.DataFrame:
    """Load HKMA history without allowing an empty fetch to erase history."""
    normalized = load_latest_normalized("hkma_residential_mortgage_survey")
    # A non-empty cache is only authoritative while it can still be holding
    # the newest published month.  Serving any non-empty vintage unconditionally
    # is exactly how a 2026-07-23 May-only cache regressed production from June
    # back to May (audit 2026-08-21).
    if not normalized.empty:
        latest_date = _extract_latest_date(normalized)
        if latest_date is not None and _monthly_cache_is_current(
            latest_date,
            publication_lag_days=HKMA_PUBLICATION_LAG_DAYS,
            margin_days=HKMA_PUBLICATION_MARGIN_DAYS,
        ):
            return _canonicalize_hkma_frame(normalized)

    fetched = _safe_fetch("HKMA residential mortgage survey", fetch_hkma_residential_mortgage_survey)
    if not fetched.empty:
        fetched = _canonicalize_hkma_frame(fetched)
        cached = _canonicalize_hkma_frame(normalized) if not normalized.empty else normalized
        if _hkma_fetch_regresses_history(fetched, cached):
            print(
                "  [hk_real_estate] HKMA fetch returned a shorter history than the local cache "
                f"({len(fetched)} vs {len(cached)} rows); keeping the cached vintage.",
                file=sys.stderr,
            )
            return cached
        if _hkma_cache_needs_rewrite(fetched, cached):
            # Persist the refreshed history so the next build (local or CI)
            # starts from this vintage instead of re-serving the stale one.
            try:
                save_normalized_dataset(
                    "hkma_residential_mortgage_survey",
                    fetched,
                    source_url=HKMA_PUBLIC_RMS_URL,
                    lineage_metadata={"written_by": "build_hk_real_estate_artifact._load_hkma_with_fallback"},
                )
            except Exception as error:  # cache refresh is best-effort, never fatal
                print(f"  [hk_real_estate] HKMA normalized cache refresh failed (non-fatal): {error}", file=sys.stderr)
        return fetched
    # Live fetch failed; a stale cache is still better than nothing.
    if not normalized.empty:
        return _canonicalize_hkma_frame(normalized)
    fallback = _load_hkma_from_committed_artifact()
    if not fallback.empty:
        print(
            "  [hk_real_estate] HKMA fetch returned no rows; using the last committed mortgage artifact.",
            file=sys.stderr,
        )
    return fallback


def _load_bd_supply_history_from_committed_artifact() -> pd.DataFrame:
    """Reconstruct BD history input from the last published chart datasets."""
    unit_rows = _load_dataset_from_committed_artifact("bd_supply_pipeline_history_units")
    count_rows = _load_dataset_from_committed_artifact("bd_supply_pipeline_history_counts")
    if unit_rows.empty and count_rows.empty:
        return pd.DataFrame()

    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for rows, value_column in (
        (unit_rows, "total_domestic_units"),
        (count_rows, "total_projects_count"),
    ):
        if rows.empty or not {"date", "permit_stage", "value"}.issubset(rows.columns):
            continue
        for row in rows.to_dict("records"):
            date = str(row.get("date") or "")[:7]
            stage = row.get("permit_stage")
            if not date or not stage or row.get("value") is None:
                continue
            key = (date, str(stage))
            target = merged.setdefault(
                key,
                {
                    "date": f"{date}-01",
                    "observation_month": f"{date}-01",
                    "permit_stage": stage,
                    "revision_status": "as_published",
                    "parser_confidence": "HIGH",
                    "source_agency": "Hong Kong Buildings Department",
                },
            )
            target[value_column] = float(row["value"])

    if not merged:
        return pd.DataFrame()
    return _mark_artifact_fallback(pd.DataFrame(sorted(merged.values(), key=lambda row: (row["date"], row["permit_stage"]))), "last committed artifact")


FRESHNESS_MAX_DAYS = 45


def _extract_latest_date(frame: pd.DataFrame) -> pd.Timestamp | None:
    if frame.empty:
        return None
    date_cols = [
        col for col in ("date", "observation_date", "observation_month", "period", "as_of_date", "event_date", "quarter_end")
        if col in frame.columns
    ]
    if not date_cols:
        date_cols = [col for col in frame.columns if any(kw in str(col).lower() for kw in ("date", "period", "month"))]

    max_dates = []
    for col in date_cols:
        parsed = pd.to_datetime(frame[col], errors="coerce").dropna()
        if not parsed.empty:
            max_dates.append(parsed.max())
    if not max_dates:
        return None
    latest = max(max_dates)
    if pd.isna(latest):
        return None
    return pd.Timestamp(latest)


def _load_normalized_or_fetch(dataset_name: str, label: str, fetch_fn) -> pd.DataFrame:
    """Prefer durable normalized output, with a bounded live-fetch fallback and freshness check."""
    normalized = load_latest_normalized(dataset_name)
    if not normalized.empty:
        latest_date = _extract_latest_date(normalized)
        if latest_date is not None:
            latest_naive = latest_date.tz_localize(None) if latest_date.tzinfo else latest_date
            now = pd.Timestamp.now().normalize()
            if (now - latest_naive.normalize()).days <= FRESHNESS_MAX_DAYS:
                normalized.attrs["is_cached"] = True
                return normalized

    fetched = _safe_fetch(label, fetch_fn)
    if not fetched.empty:
        fetched.attrs["is_cached"] = False
        return fetched
    if not normalized.empty:
        normalized.attrs["is_cached"] = True
        return normalized
    return pd.DataFrame()


def _load_shkp_financial_model_frames() -> dict[str, pd.DataFrame]:
    """Load the ticker-scoped SHKP financial bridge without copying DuckDB.

    A local refresh may have already materialised the model inputs.  If the
    essential layers are absent, run the model's read-only sibling-DB join once
    (without fetching price history) and reload the normalized snapshots.  A
    clean CI checkout without the sibling repository simply returns empty
    frames; the dashboard then reports the bridge as unavailable rather than
    fabricating financial rows.
    """
    dataset_map = {
        "disclosed": "shkp_financial_model_disclosed_facts",
        "recurring": "shkp_financial_model_recurring_portfolio_facts",
        "actuals": "shkp_financial_model_financial_data_actuals",
        "reconciliation": "shkp_financial_model_financial_reconciliation",
        "consensus": "shkp_financial_model_consensus",
        "vintage_coverage": "shkp_financial_model_vintage_coverage",
        "coverage": "shkp_financial_model_coverage",
    }

    def load() -> dict[str, pd.DataFrame]:
        return {key: load_latest_normalized(dataset_name) for key, dataset_name in dataset_map.items()}

    frames = load()
    if any(frames[key].empty for key in ("disclosed", "recurring", "actuals")):
        try:
            run_shkp_financial_model(include_price_history=False)
            frames = load()
        except Exception as exc:  # noqa: BLE001 - optional sibling dependency
            print(f"  [hk_real_estate] SHKP financial bridge unavailable, continuing without it: {exc}", file=sys.stderr)
    return frames


def _load_shkp_sales_handover_bridge_frames() -> dict[str, pd.DataFrame]:
    """Load the latest timing bridge, materialising it once when absent."""
    dataset_map = {
        "phase": SHKP_SALES_HANDOVER_PHASE_DATASET,
        "annual": SHKP_SALES_HANDOVER_ANNUAL_DATASET,
        "coverage": "shkp_sales_handover_revenue_coverage",
    }

    def load() -> dict[str, pd.DataFrame]:
        return {key: load_latest_normalized(dataset_name) for key, dataset_name in dataset_map.items()}

    frames = load()
    if frames["phase"].empty:
        try:
            run_shkp_sales_handover_revenue_bridge()
            frames = load()
        except Exception as exc:  # noqa: BLE001 - optional timing layer
            print(
                f"  [hk_real_estate] SHKP sales/handover bridge unavailable, continuing without it: {exc}",
                file=sys.stderr,
            )
    return frames


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
    rvd_office_vacancy = _load_normalized_or_fetch("rvd_office_vacancy_annual", "RVD office vacancy", fetch_rvd_office_vacancy_annual)
    rvd_office_stock = _load_normalized_or_fetch("rvd_office_stock_vacancy_district_annual", "RVD office stock/vacancy", fetch_rvd_office_stock_vacancy_district)
    rvd_commercial_stock = _load_normalized_or_fetch("rvd_commercial_stock_vacancy_district_annual", "RVD commercial stock/vacancy", fetch_rvd_commercial_stock_vacancy_district)
    rvd_commercial_forecast = _load_normalized_or_fetch("rvd_commercial_forecast_completions_annual", "RVD commercial forecast completions", fetch_rvd_commercial_forecast_completions)
    cnsd_retail_control = _load_normalized_or_fetch("cnsd_retail_sales_control_monthly", "C&SD retail sales control", fetch_cnsd_retail_sales_control)
    tourism_occupancy = _load_normalized_or_fetch("tourism_hotel_occupancy_category_monthly", "Tourism hotel occupancy", fetch_tourism_hotel_occupancy_category)
    tourism_adr = _load_normalized_or_fetch("tourism_hotel_adr_category_monthly", "Tourism hotel achieved room rate", fetch_tourism_hotel_adr_category)
    tourism_rooms = _load_normalized_or_fetch("tourism_hotel_rooms_category_monthly", "Tourism hotel room supply", fetch_tourism_hotel_rooms_category)
    shkp_catalog = load_latest_normalized("shkp_property_catalog")
    if shkp_catalog.empty:
        shkp_catalog = _safe_fetch("SHKP commercial asset directory", lambda: fetch_shkp_property_catalog(timeout=60, max_pages=None))
    shkp_corporate = load_latest_normalized("shkp_corporate_documents")
    if shkp_corporate.empty:
        shkp_corporate = _safe_fetch("SHKP Quarterly catalogue", lambda: fetch_shkp_corporate_documents(timeout=60))
    shkp_quarterly = build_shkp_quarterly_events(shkp_corporate, property_catalog=shkp_catalog)
    shkp_quarterly_facts = _load_normalized_or_fetch(
        "shkp_quarterly_numeric_facts",
        "SHKP Quarterly numeric facts",
        lambda: fetch_shkp_quarterly_numeric_facts(
            corporate_documents=shkp_corporate,
            quarterly_events=shkp_quarterly,
            max_documents=24,
        ),
    )
    shkp_commercial_assets = build_shkp_commercial_asset_master(
        property_catalog=shkp_catalog,
        completed_properties=load_latest_normalized("shkp_completed_properties"),
        completion_schedule=load_latest_normalized("shkp_completion_schedule_projects"),
    )
    shkp_financial_frames = _load_shkp_financial_model_frames()
    shkp_sales_handover_frames = _load_shkp_sales_handover_bridge_frames()
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
    srpe_signals = load_latest_normalized("srpe_pilot_developer_monthly_signals")
    if srpe_signals.empty:
        # The daily dashboard workflow intentionally does not re-download the
        # bounded SRPE PDF pilot. Preserve the last validated signal dataset
        # through the committed artifact until the separate SRPE ingestion job
        # writes a newer normalized snapshot.
        srpe_signals = _load_dataset_from_committed_artifact("srpe_project_signal_history")
    shkp_leading_signals = load_latest_normalized("shkp_srpe_project_month_signals")
    shkp_reconciliation = load_latest_normalized("shkp_28hse_reconciliation")
    bd_supply_history = load_latest_normalized("bd_supply_pipeline_history")
    if bd_supply_history.empty:
        bd_supply_history = _load_bd_supply_history_from_committed_artifact()
        if not bd_supply_history.empty:
            print(
                "  [hk_real_estate] BD history cache unavailable; using the last committed supply-history artifact.",
                file=sys.stderr,
            )
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
        "rvd_office_vacancy": rvd_office_vacancy,
        "rvd_office_stock": rvd_office_stock,
        "rvd_commercial_stock": rvd_commercial_stock,
        "rvd_commercial_forecast": rvd_commercial_forecast,
        "cnsd_retail_control": cnsd_retail_control,
        "tourism_occupancy": tourism_occupancy,
        "tourism_adr": tourism_adr,
        "tourism_rooms": tourism_rooms,
        "shkp_quarterly_events": shkp_quarterly,
        "shkp_quarterly_facts": shkp_quarterly_facts,
        "shkp_commercial_assets": shkp_commercial_assets,
        "shkp_financial_disclosed": shkp_financial_frames["disclosed"],
        "shkp_financial_recurring": shkp_financial_frames["recurring"],
        "shkp_financial_actuals": shkp_financial_frames["actuals"],
        "shkp_financial_reconciliation": shkp_financial_frames["reconciliation"],
        "shkp_financial_consensus": shkp_financial_frames["consensus"],
        "shkp_financial_vintage": shkp_financial_frames["vintage_coverage"],
        "shkp_financial_coverage": shkp_financial_frames["coverage"],
        "shkp_sales_handover_phase": shkp_sales_handover_frames["phase"],
        "shkp_sales_handover_annual": shkp_sales_handover_frames["annual"],
        "midland_estates": estates,
        "unified_tx": unified_tx,
        "srpe_signals": srpe_signals,
        "shkp_leading_signals": shkp_leading_signals,
        "shkp_reconciliation": shkp_reconciliation,
        "bd_supply_history": bd_supply_history,
    }


def _prune_unreferenced_portable_datasets(artifact: dict[str, Any]) -> None:
    """Keep the portable artifact within the renderer's dataset contract.

    ``build_artifact`` intentionally returns a rich research snapshot for unit
    tests and local inspection.  The portable renderer has a hard limit of 50
    dataset keys, so the on-disk dashboard should carry the datasets actually
    referenced by cards/charts/tables plus the source-health surfaces.  The
    omitted raw views remain available in normalized Parquet and can be added
    to a future research surface without silently changing dashboard rows.
    """
    snapshot = artifact.get("snapshot")
    manifest = artifact.get("manifest")
    if not isinstance(snapshot, dict) or not isinstance(manifest, dict):
        return
    datasets = snapshot.get("datasets")
    if not isinstance(datasets, dict):
        return
    referenced = {"source_health", "source_coverage"}
    for section in ("cards", "charts", "tables"):
        items = manifest.get(section, [])
        if isinstance(items, list):
            referenced.update(
                str(item["dataset"])
                for item in items
                if isinstance(item, dict) and item.get("dataset")
            )
    snapshot["datasets"] = {
        key: value for key, value in datasets.items() if key in referenced
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Canonical artifact JSON output path")
    parser.add_argument("--status-output", type=Path, required=True, help="Compact Astro status JSON output path")
    args = parser.parse_args()

    live_frames = fetch_live_frames()
    unified_tx = live_frames.pop("unified_tx", pd.DataFrame())
    bd_supply_history = live_frames.pop("bd_supply_history", pd.DataFrame())
    srpe_signals = live_frames.pop("srpe_signals", pd.DataFrame())
    shkp_leading_signals = live_frames.pop("shkp_leading_signals", pd.DataFrame())
    shkp_reconciliation = live_frames.pop("shkp_reconciliation", pd.DataFrame())
    new_series = {
        key: live_frames.pop(key, pd.DataFrame())
        for key in (
            "centaline_cci",
            "centaline_cri",
            "centaline_cri_yield",
            "centaline_csi",
            "rvd_office",
            "rvd_retail",
            "rvd_office_vacancy",
            "rvd_office_stock",
            "rvd_commercial_stock",
            "rvd_commercial_forecast",
            "cnsd_retail_control",
            "tourism_occupancy",
            "tourism_adr",
            "tourism_rooms",
            "shkp_quarterly_events",
            "shkp_quarterly_facts",
            "shkp_commercial_assets",
            "shkp_financial_disclosed",
            "shkp_financial_recurring",
            "shkp_financial_actuals",
            "shkp_financial_reconciliation",
            "shkp_financial_consensus",
            "shkp_financial_vintage",
            "shkp_financial_coverage",
            "shkp_sales_handover_phase",
            "shkp_sales_handover_annual",
        )
    }
    artifact, status = build_artifact(
        live_frames,
        raw_unified_tx=unified_tx,
        raw_bd_supply_history=bd_supply_history,
        raw_new_series=new_series,
        raw_srpe_signals=srpe_signals,
        raw_shkp_leading_signals=shkp_leading_signals,
        raw_28hse_reconciliation=shkp_reconciliation,
    )
    _prune_unreferenced_portable_datasets(artifact)
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
