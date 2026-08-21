"""Deterministic, no-network tests for the four-tab Company-page cockpit."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any, Mapping

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "apps" / "research-control-tower"
APP_PATH = APP_ROOT / "app.py"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from control_tower.models import ControlTowerSnapshot, EventFilters
from control_tower.pages.company import (
    COMPANY_CLAIM_EVIDENCE_LINK_COLUMNS,
    COMPANY_CORPORATE_ACTION_COLUMNS,
    COMPANY_EVIDENCE_ITEM_COLUMNS,
    COMPANY_INTERNAL_ESTIMATES_COLUMNS,
    COMPANY_LISTING_COLUMNS,
    COMPANY_MEMBERSHIP_COLUMNS,
    COMPANY_QUESTION_COLUMNS,
    COMPANY_QUOTE_COLUMNS,
    COMPANY_REVISION_COLUMNS,
    COMPANY_THESIS_CLAIM_COLUMNS,
    COMPANY_THESIS_QUESTION_COLUMNS,
    COMPANY_VALUATION_COLUMNS,
    CompanyView,
    _answer_first_summary_lines,
    build_company_view,
    render_company_page,
)
from control_tower.config import ARTIFACT_COLUMNS, SCHEMA_VERSION
from control_tower.components import get_control_tower_css


_DATE_COLUMNS = {
    "active_from", "active_to", "mapping_verified_at", "review_by", "observation_date",
    "estimate_period_end", "scheduled_date", "reporting_period_start",
    "reporting_period_end", "period_start", "period_end", "event_date", "bar_date", "valuation_date",
}
_TIMESTAMP_COLUMNS = {
    "starts_at", "ends_at", "source_published_at", "first_observed_at", "last_verified_at", "release_at",
    "retrieved_at_utc", "snapshot_at", "provider_asof", "current_snapshot_at",
    "cutoff_at", "prior_snapshot_at", "prior_provider_asof", "published_at", "first_observation_at",
    "latest_observation_at", "source_latest_at", "quote_timestamp", "accepted_at", "filing_at",
    "valuation_at", "fx_snapshot_at_utc", "recorded_at_utc", "observed_at_utc", "reviewed_at_utc", "last_reviewed_at_utc",
}
_BOOLEAN_COLUMNS = {
    "collection_eligible", "primary_listing", "automated", "is_provisional",
    "required", "is_restatement", "conflict_hint",
}
_INTEGER_COLUMNS = {
    "observation_version", "fiscal_year", "analyst_count", "provider_contributor_count", "lookback_days",
    "current_analyst_count", "prior_analyst_count", "analyst_count_change", "row_count", "version", "shares_affected",
}
_FLOAT_COLUMNS = {
    "confidence", "value", "low_value", "high_value", "current_value", "current_dispersion", "prior_value",
    "revision_value", "revision_pct", "dispersion", "last_price", "bid", "ask",
    "day_change_pct", "volume", "reported_value", "normalized_value",
    "open", "high", "low", "close", "adj_close", "price_min", "price_max", "price_avg", "total_amount_paid",
    "ratio_value", "numerator_value", "denominator_value", "fx_rate_applied", "value_low", "value_mid", "value_high",
}


def _typed(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for column in _DATE_COLUMNS & set(frame.columns):
        frame[column] = pd.to_datetime(frame[column], errors="coerce").dt.date
    for column in _TIMESTAMP_COLUMNS & set(frame.columns):
        frame[column] = pd.to_datetime(frame[column], errors="coerce", utc=True)
    for column in _BOOLEAN_COLUMNS & set(frame.columns):
        frame[column] = frame[column].astype("boolean")
    for column in _INTEGER_COLUMNS & set(frame.columns):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    for column in _FLOAT_COLUMNS & set(frame.columns):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Float64")
    for column in frame.columns:
        if column not in _DATE_COLUMNS | _TIMESTAMP_COLUMNS | _BOOLEAN_COLUMNS | _INTEGER_COLUMNS | _FLOAT_COLUMNS:
            frame[column] = frame[column].astype("string")
    return frame


def _schema_for_columns(columns: list[str]) -> pa.Schema:
    fields: list[pa.Field] = []
    for column in columns:
        if column in _DATE_COLUMNS:
            dtype = pa.date32()
        elif column in _TIMESTAMP_COLUMNS:
            dtype = pa.timestamp("us", tz="UTC")
        elif column in _BOOLEAN_COLUMNS:
            dtype = pa.bool_()
        elif column in _INTEGER_COLUMNS:
            dtype = pa.int64()
        elif column in _FLOAT_COLUMNS:
            dtype = pa.float64()
        else:
            dtype = pa.string()
        fields.append(pa.field(column, dtype, nullable=True))
    return pa.schema(fields)


def _app_text(app) -> str:
    """Extract all text rendered in the AppTest run."""
    parts: list[str] = []
    for markdown in app.markdown:
        parts.append(str(markdown.value))
    for caption in app.caption:
        parts.append(str(caption.value))
    for info in app.info:
        parts.append(str(info.value))
    for warning in app.warning:
        parts.append(str(warning.value))
    for metric in app.metric:
        parts.append(f"{metric.label}: {metric.value}")
    for tab in app.tabs:
        parts.append(str(tab.label))
    return "\n".join(parts)


@dataclass(frozen=True)
class ExtendedSnapshot:
    entities: pd.DataFrame
    listings: pd.DataFrame
    baskets: pd.DataFrame
    basket_memberships: pd.DataFrame
    indices: pd.DataFrame
    events: pd.DataFrame
    event_entity_links: pd.DataFrame
    event_basket_links: pd.DataFrame
    event_watch_questions: pd.DataFrame
    macro_observations: pd.DataFrame
    consensus_snapshots: pd.DataFrame
    consensus_revisions: pd.DataFrame
    quote_snapshots: pd.DataFrame
    price_bars: pd.DataFrame
    news_filings: pd.DataFrame
    official_filings: pd.DataFrame
    earnings_calendar: pd.DataFrame
    earnings_actuals: pd.DataFrame
    source_health: pd.DataFrame
    manifest: Mapping[str, Any]
    status: str
    missing_optional: tuple[str, ...]
    degraded_reasons: Mapping[str, str]
    build_id: str
    built_at_utc: pd.Timestamp
    as_of_utc: pd.Timestamp
    previous_build_at: pd.Timestamp | None
    corporate_actions: pd.DataFrame = field(default_factory=pd.DataFrame)
    valuation_snapshots: pd.DataFrame = field(default_factory=pd.DataFrame)
    internal_estimates: pd.DataFrame = field(default_factory=pd.DataFrame)
    thesis_claims: pd.DataFrame = field(default_factory=pd.DataFrame)
    thesis_watch_questions: pd.DataFrame = field(default_factory=pd.DataFrame)
    evidence_items: pd.DataFrame = field(default_factory=pd.DataFrame)
    claim_evidence_links: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def now_utc(self) -> pd.Timestamp:
        return self.as_of_utc


def _make_tencent_snapshot() -> ExtendedSnapshot:
    """Create a deterministic in-memory snapshot with Tencent T0-T3 records."""
    now_utc = pd.Timestamp("2026-08-21T12:00:00Z")

    entities = pd.DataFrame([
        {
            "entity_id": "TENCENT",
            "legal_name": "Tencent Holdings Limited",
            "display_name": "Tencent Holdings",
            "country": "CN",
            "sector": "Communication Services",
            "industry": "Interactive Media & Services",
            "active_status": "active",
            "active_from": "2004-06-16",
            "active_to": None,
            "registry_version": "v1",
            "source_or_research_note": "Tencent primary entity",
            "entity_type": "public",
        },
        {
            "entity_id": "BYTEDANCE",
            "legal_name": "ByteDance Ltd.",
            "display_name": "ByteDance",
            "country": "CN",
            "sector": "Communication Services",
            "industry": "Interactive Media & Services",
            "active_status": "active",
            "active_from": "2012-03-01",
            "active_to": None,
            "registry_version": "v1",
            "source_or_research_note": "Private peer",
            "entity_type": "private",
        },
    ])

    listings = pd.DataFrame([
        {
            "listing_id": "0700_HK",
            "entity_id": "TENCENT",
            "exchange": "HKEX",
            "native_ticker": "0700",
            "canonical_ticker": "0700.HK",
            "financial_data_security_id": "sec-0700",
            "financial_data_issuer_group_id": "grp-tencent",
            "mapping_status": "verified",
            "mapping_verified_at": "2026-08-21",
            "mapping_source_url": "https://www.hkex.com.hk",
            "collection_eligible": True,
            "listing_role": "primary",
            "vendor_tickers": "yfinance:0700.HK;akshare:00700",
            "currency": "HKD",
            "primary_listing": True,
            "active_from": "2004-06-16",
            "active_to": None,
            "listing_status": "active",
            "registry_version": "v1",
            "source_url": "https://www.hkex.com.hk",
            "source_or_research_note": "Primary HKD listing",
        },
        {
            "listing_id": "TCEHY_US",
            "entity_id": "TENCENT",
            "exchange": "OTC",
            "native_ticker": "TCEHY",
            "canonical_ticker": "TCEHY.US",
            "financial_data_security_id": "",
            "financial_data_issuer_group_id": "grp-tencent",
            "mapping_status": "unresolved",
            "mapping_verified_at": "",
            "mapping_source_url": "",
            "collection_eligible": False,
            "listing_role": "depositary_receipt",
            "vendor_tickers": "yfinance:TCEHY",
            "currency": "USD",
            "primary_listing": False,
            "active_from": "2008-01-01",
            "active_to": None,
            "listing_status": "active",
            "registry_version": "v1",
            "source_url": "https://www.otcmarkets.com",
            "source_or_research_note": "US OTC ADR",
        },
    ])

    baskets = pd.DataFrame([
        {"basket_id": "RESEARCH_STAGE_1_CHINA_INTERNET", "display_name": "China Internet Stage 1", "purpose": "Focus research", "active_from": "2026-01-01", "active_to": None, "registry_version": "v1"},
    ])

    basket_memberships = pd.DataFrame([
        {"entity_id": "TENCENT", "basket_id": "RESEARCH_STAGE_1_CHINA_INTERNET", "membership_tier": "core", "primary_layer": "platforms", "secondary_layers": "gaming;advertising;cloud", "active_from": "2026-01-01", "active_to": None, "membership_reason": "Core China Internet holding", "registry_version": "v1"},
        {"entity_id": "BYTEDANCE", "basket_id": "RESEARCH_STAGE_1_CHINA_INTERNET", "membership_tier": "watch_only", "primary_layer": "platforms", "secondary_layers": "short_video", "active_from": "2026-01-01", "active_to": None, "membership_reason": "Private competitor benchmark", "registry_version": "v1"},
    ])

    indices = pd.DataFrame([
        {"index_id": "HSI", "region": "HK", "display_name": "Hang Seng Index", "official_code": "HSI", "official_code_namespace": "HKEX", "official_code_provider": "HSI", "provider_symbol": "^HSI", "provider_symbol_namespace": "yahoo", "provider_symbol_provider": "yfinance", "provider": "yfinance", "currency": "HKD", "active_from": "1969-11-24", "active_to": None, "registry_version": "v1", "source_url": "", "source_or_research_note": ""}
    ])

    events = pd.DataFrame([
        {
            "event_id": "EV_TENCENT_2Q2026_RESULTS",
            "event_key": "EV_TENCENT_2Q2026_RESULTS",
            "observation_version": 1,
            "scope": "company",
            "event_type": "earnings_release",
            "title": "Tencent 2Q2026 Financial Results",
            "description": "Tencent reports 2Q2026 quarterly results on HKEXnews.",
            "status": "observed",
            "certainty_class": "observed",
            "importance": "high",
            "confidence": 1.0,
            "date_precision": "day",
            "starts_at": pd.Timestamp("2026-08-12T08:31:00Z"),
            "ends_at": None,
            "source_timezone": "Asia/Hong_Kong",
            "source_id": "filings:hkexnews",
            "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0812/2026081200296.pdf",
            "source_published_at": pd.Timestamp("2026-08-12T08:31:00Z"),
            "first_observed_at": pd.Timestamp("2026-08-12T08:35:00Z"),
            "last_verified_at": pd.Timestamp("2026-08-18T12:00:00Z"),
            "review_by": None,
            "supersedes_event_id": None,
            "evidence_class": "official_external",
            "evidence_ref": "hkexnews:12280990",
            "related_entity_ids": ("TENCENT",),
            "related_listing_ids": ("0700_HK",),
            "related_basket_ids": ("RESEARCH_STAGE_1_CHINA_INTERNET",),
            "registry_version": "v1",
        },
        {
            "event_id": "EV_TENCENT_3Q2026_WINDOW",
            "event_key": "EV_TENCENT_3Q2026_WINDOW",
            "observation_version": 1,
            "scope": "company",
            "event_type": "earnings_release",
            "title": "Tencent 3Q2026 Results Window",
            "description": "Estimated 3Q2026 financial reporting window.",
            "status": "scheduled",
            "certainty_class": "thesis_checkpoint",
            "importance": "high",
            "confidence": 0.85,
            "date_precision": "month",
            "starts_at": pd.Timestamp("2026-11-12T00:00:00Z"),
            "ends_at": None,
            "source_timezone": "Asia/Hong_Kong",
            "source_id": "research:internal",
            "source_url": "",
            "source_published_at": None,
            "first_observed_at": pd.Timestamp("2026-08-18T12:00:00Z"),
            "last_verified_at": pd.Timestamp("2026-08-18T12:00:00Z"),
            "review_by": None,
            "supersedes_event_id": None,
            "evidence_class": "internal_research",
            "evidence_ref": "internal:checkpoint",
            "related_entity_ids": ("TENCENT",),
            "related_listing_ids": ("0700_HK",),
            "related_basket_ids": ("RESEARCH_STAGE_1_CHINA_INTERNET",),
            "registry_version": "v1",
        },
    ])

    event_entity_links = pd.DataFrame([
        {"event_id": "EV_TENCENT_2Q2026_RESULTS", "target_type": "entity", "target_id": "TENCENT", "link_role": "primary", "automated": True, "active_from": "2026-01-01", "active_to": None, "link_note": "", "registry_version": "v1"},
        {"event_id": "EV_TENCENT_2Q2026_RESULTS", "target_type": "listing", "target_id": "0700_HK", "link_role": "primary", "automated": True, "active_from": "2026-01-01", "active_to": None, "link_note": "", "registry_version": "v1"},
        {"event_id": "EV_TENCENT_3Q2026_WINDOW", "target_type": "entity", "target_id": "TENCENT", "link_role": "primary", "automated": True, "active_from": "2026-01-01", "active_to": None, "link_note": "", "registry_version": "v1"},
    ])

    event_basket_links = pd.DataFrame([
        {"event_id": "EV_TENCENT_2Q2026_RESULTS", "target_type": "basket", "target_id": "RESEARCH_STAGE_1_CHINA_INTERNET", "link_role": "primary", "automated": True, "active_from": "2026-01-01", "active_to": None, "link_note": "", "registry_version": "v1"},
        {"event_id": "EV_TENCENT_3Q2026_WINDOW", "target_type": "basket", "target_id": "RESEARCH_STAGE_1_CHINA_INTERNET", "link_role": "primary", "automated": True, "active_from": "2026-01-01", "active_to": None, "link_note": "", "registry_version": "v1"},
    ])

    event_watch_questions = pd.DataFrame([
        {"event_id": "EV_TENCENT_2Q2026_RESULTS", "question_id": "Q_FCF", "question": "Does AI CapEx prepayment reverse in 2H2026?", "question_type": "falsification", "priority": "1", "registry_version": "v1"},
    ])

    quote_snapshots = pd.DataFrame([
        {
            "quote_id": "quote-0700-20260821",
            "listing_id": "0700_HK",
            "canonical_ticker": "0700.HK",
            "provider_symbol": "0700.HK",
            "quote_timestamp": pd.Timestamp("2026-08-21T08:00:00Z"),
            "retrieved_at_utc": pd.Timestamp("2026-08-21T08:05:00Z"),
            "last_price": 441.20,
            "bid": 441.00,
            "ask": 441.40,
            "day_change_pct": 1.45,
            "volume": 14_500_000.0,
            "currency": "HKD",
            "market_status": "closed",
            "latency_class": "delayed",
            "source_id": "market:yfinance",
            "source_url": "https://finance.yahoo.com/quote/0700.HK",
            "pit_class": "snapshot_from_delayed_source",
            "source_license_class": "personal_use_terms_unverified",
            "registry_version": "v1",
        }
    ])

    price_bars = pd.DataFrame([
        {
            "bar_id": "bar-0700-20260820",
            "listing_id": "0700_HK",
            "entity_id": "TENCENT",
            "canonical_ticker": "0700.HK",
            "provider_symbol": "0700.HK",
            "interval": "1d",
            "bar_date": pd.Timestamp("2026-08-20").date(),
            "open": 435.0,
            "high": 443.0,
            "low": 434.6,
            "close": 441.2,
            "adj_close": 441.2,
            "volume": 14_500_000.0,
            "currency": "HKD",
            "source_id": "market:yfinance",
            "source_url": "https://finance.yahoo.com/quote/0700.HK",
            "retrieved_at_utc": pd.Timestamp("2026-08-21T08:05:00Z"),
            "pit_class": "snapshot_from_delayed_source",
            "source_license_class": "personal_use_terms_unverified",
            "registry_version": "v1",
        }
    ])

    earnings_actuals = pd.DataFrame([
        {
            "actual_id": "act-tencent-2026q2-rev",
            "version": 1,
            "supersedes_actual_id": None,
            "entity_id": "TENCENT",
            "listing_id": "0700_HK",
            "canonical_ticker": "0700.HK",
            "metric": "revenue_total",
            "period_label": "2026Q2",
            "period_start": pd.Timestamp("2026-04-01").date(),
            "period_end": pd.Timestamp("2026-06-30").date(),
            "reported_value": 204785.0,
            "normalized_value": 204785.0,
            "normalization_note": "in RMB millions",
            "currency": "CNY",
            "unit": "million",
            "accounting_basis": "IFRS",
            "filing_at": pd.Timestamp("2026-08-12T08:31:00Z"),
            "published_at": pd.Timestamp("2026-08-12T08:31:00Z"),
            "retrieved_at_utc": pd.Timestamp("2026-08-18T15:27:59Z"),
            "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0812/2026081200296.pdf",
            "accession_no": "2026081200296",
            "form": "interim_results",
            "xbrl_frame": None,
            "revision_reason": "",
            "is_restatement": False,
            "source_id": "filings:hkexnews",
            "source_quality": "official_statutory",
            "pit_class": "snapshot_from_live_source",
            "source_license_class": "official_public_metadata",
            "source_note": "",
            "registry_version": "v1",
        },
        {
            "actual_id": "act-tencent-2026q2-op-nonifrs",
            "version": 1,
            "supersedes_actual_id": None,
            "entity_id": "TENCENT",
            "listing_id": "0700_HK",
            "canonical_ticker": "0700.HK",
            "metric": "operating_profit",
            "period_label": "2026Q2",
            "period_start": pd.Timestamp("2026-04-01").date(),
            "period_end": pd.Timestamp("2026-06-30").date(),
            "reported_value": 75636.0,
            "normalized_value": 75636.0,
            "normalization_note": "Non-IFRS Operating Profit in RMB millions",
            "currency": "CNY",
            "unit": "million",
            "accounting_basis": "Non-IFRS",
            "filing_at": pd.Timestamp("2026-08-12T08:31:00Z"),
            "published_at": pd.Timestamp("2026-08-12T08:31:00Z"),
            "retrieved_at_utc": pd.Timestamp("2026-08-18T15:27:59Z"),
            "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0812/2026081200296.pdf",
            "accession_no": "2026081200296",
            "form": "interim_results",
            "xbrl_frame": None,
            "revision_reason": "",
            "is_restatement": False,
            "source_id": "filings:hkexnews",
            "source_quality": "official_statutory",
            "pit_class": "snapshot_from_live_source",
            "source_license_class": "official_public_metadata",
            "source_note": "",
            "registry_version": "v1",
        },
    ])
    actual_template = earnings_actuals.iloc[0].to_dict()
    for actual_id, metric, value, basis, note in (
        (
            "act-tencent-2026q2-fcf",
            "free_cash_flow",
            -13_800.0,
            "reported",
            "Reported Free Cash Flow in CNY millions",
        ),
        (
            "act-tencent-2026q2-compute-prepayments",
            "compute_hardware_prepayments",
            51_400.0,
            "reported",
            "Compute hardware prepayments in CNY millions",
        ),
        (
            "act-tencent-2026q2-fcf-ex-prepayments",
            "free_cash_flow_ex_prepayments",
            37_600.0,
            "management_adjusted",
            "Free Cash Flow excluding compute hardware prepayments in CNY millions",
        ),
    ):
        row = actual_template.copy()
        row.update(
            {
                "actual_id": actual_id,
                "metric": metric,
                "reported_value": value,
                "normalized_value": value,
                "normalization_note": note,
                "accounting_basis": basis,
            }
        )
        earnings_actuals.loc[len(earnings_actuals)] = row

    corporate_actions = pd.DataFrame([
        {
            "action_id": "act-0700-buyback-20260818",
            "listing_id": "0700_HK",
            "action_type": "buyback_execution",
            "filing_date": pd.Timestamp("2026-08-18").date(),
            "execution_date": pd.Timestamp("2026-08-18").date(),
            "shares_affected": 681_000,
            "price_min": 437.80,
            "price_max": 445.00,
            "price_avg": 441.19,
            "total_amount_paid": 300_451_683.90,
            "currency": "HKD",
            "cancellation_status": "designated_treasury",
            "coverage_reason": "",
            "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0818/2026081801120.pdf",
            "retrieved_at_utc": pd.Timestamp("2026-08-18T15:27:59Z"),
            "pit_class": "snapshot_from_live_source",
        }
    ])

    valuation_snapshots = pd.DataFrame([
        {
            "valuation_id": "val-0700-fpe-2026",
            "listing_id": "0700_HK",
            "valuation_date": pd.Timestamp("2026-08-21").date(),
            "valuation_at": pd.Timestamp("2026-08-21T08:00:00Z"),
            "metric_name": "forward_pe",
            "metric_basis": "NON_IFRS_MANAGEMENT",
            "ratio_value": 16.2,
            "numerator_value": 441.20,
            "numerator_currency": "HKD",
            "numerator_ref": "quote-0700-20260821",
            "denominator_value": 25.10,
            "denominator_currency": "CNY",
            "denominator_ref": "consensus-0700-eps-2026",
            "fx_rate_applied": 1.085,
            "fx_source": "ECB",
            "fx_snapshot_at_utc": pd.Timestamp("2026-08-21T00:00:00Z"),
            "source_id": "valuation:derived",
            "source_url": "https://finance.yahoo.com/quote/0700.HK",
            "retrieved_at_utc": pd.Timestamp("2026-08-21T08:05:00Z"),
            "pit_class": "snapshot_from_delayed_source",
            "coverage_reason": "",
            "percentile_history_status": "unavailable",
        }
    ])

    internal_estimates = pd.DataFrame([
        {
            "estimate_id": "est-internal-tencent-2026-rev",
            "version": "1",
            "supersedes_estimate_id": None,
            "entity_id": "TENCENT",
            "listing_id": "0700_HK",
            "observation_type": "internal_estimate",
            "author": "Analyst_HK",
            "metric": "revenue_total",
            "accounting_basis": "IFRS",
            "metric_basis": "GAAP_REPORTED",
            "fiscal_period": "FY2026",
            "fiscal_year": 2026,
            "value_low": 790000.0,
            "value_high": 820000.0,
            "value_mid": 805000.0,
            "currency": "CNY",
            "unit": "million",
            "effective_asof": "2026-08-15",
            "recorded_at_utc": pd.Timestamp("2026-08-15T10:00:00Z"),
            "rationale_notes": "Sustained AIM+ advertising growth offsetting gaming seasonality.",
            "source_ref": "internal_note_20260815",
            "source_url": "",
            "pit_class": "not_pit",
            "reviewed_at_utc": None,
            "reviewed_by": None,
        }
    ])

    thesis_claims = pd.DataFrame([
        {
            "claim_id": "TENCENT_THESIS_BULL_AI_ADS",
            "entity_id": "TENCENT",
            "thesis_title": "Bull Case: AI Ad Efficiencies (AIM+) & Agentic Workflows",
            "claim_text": "AI advertising algorithm upgrades (AIM+) and agentic workflow integration sustain mid-teens profit growth.",
            "invalidation_rule": "Gross Margin falls below 55.0% for 2 consecutive quarters; OR Marketing Services YoY revenue growth slows below 12.0%.",
            "status": "draft",
            "last_reviewed_at_utc": None,
            "reviewed_by": None,
            "registry_version": "v1",
        },
        {
            "claim_id": "TENCENT_THESIS_BASE_COMPOUNDER",
            "entity_id": "TENCENT",
            "thesis_title": "Base Case: Core Gaming & Advertising Compounder with P/E Floor",
            "claim_text": "Evergreen gaming franchise and high-margin ad network compound operating earnings at 8-11% YoY.",
            "invalidation_rule": "Non-IFRS operating profit growth turns flat or negative (<0% YoY).",
            "status": "draft",
            "last_reviewed_at_utc": None,
            "reviewed_by": None,
            "registry_version": "v1",
        },
    ])

    thesis_watch_questions = pd.DataFrame([
        {
            "question_id": "TENCENT_TWQ_AIM_GROWTH",
            "claim_id": "TENCENT_THESIS_BULL_AI_ADS",
            "entity_id": "TENCENT",
            "question": "Does Marketing Services / Online Advertising maintain YoY revenue growth >= 15% with expanding gross margins?",
            "question_type": "support",
            "priority": "1",
            "registry_version": "v1",
        },
        {
            "question_id": "TENCENT_TWQ_NON_IFRS_OP_FLOOR",
            "claim_id": "TENCENT_THESIS_BASE_COMPOUNDER",
            "entity_id": "TENCENT",
            "question": "Does Non-IFRS operating profit maintain positive YoY growth (>= 8%) despite new AI product drag?",
            "question_type": "falsification",
            "priority": "1",
            "registry_version": "v1",
        },
    ])

    evidence_items = pd.DataFrame([
        {
            "evidence_id": "EVID_TENCENT_2Q2026_RESULTS_FILING",
            "entity_id": "TENCENT",
            "source_id": "hkexnews",
            "evidence_ref": "hkexnews:12280990",
            "source_type": "filing",
            "source_url": "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0812/2026081200296.pdf",
            "evidence_class": "official_external",
            "pit_class": "snapshot_from_live_source",
            "source_license_class": "official_public_metadata",
            "published_at": pd.Timestamp("2026-08-12T08:31:00Z"),
            "summary_text": "Tencent 2Q2026 Results: Total revenue RMB204.785B (+11% YoY), Non-IFRS operating profit RMB75.636B (+9% YoY).",
            "observed_at_utc": pd.Timestamp("2026-08-18T15:27:59Z"),
            "content_hash": "",
            "registry_version": "v1",
        }
    ])

    claim_evidence_links = pd.DataFrame([
        {
            "link_id": "LINK_TENCENT_BASE_2Q26_OP",
            "claim_id": "TENCENT_THESIS_BASE_COMPOUNDER",
            "evidence_id": "EVID_TENCENT_2Q2026_RESULTS_FILING",
            "conflict_hint": False,
            "review_state": "pending_review",
            "analyst_note": "Non-IFRS operating profit grew 9% YoY (+19% ex-AI), supporting compounder base case above 0% floor.",
            "registry_version": "v1",
        }
    ])

    source_health = pd.DataFrame([
        {
            "source_id": "filings:hkexnews",
            "input_path": "official_filings.parquet",
            "source_kind": "official_filing",
            "status": "available",
            "required": True,
            "row_count": 10,
            "first_observation_at": pd.Timestamp("2021-05-20T08:30:00Z"),
            "latest_observation_at": pd.Timestamp("2026-08-18T15:27:59Z"),
            "source_latest_at": pd.Timestamp("2026-08-18T15:27:59Z"),
            "retrieved_at_utc": pd.Timestamp("2026-08-18T15:27:59Z"),
            "cadence": "daily",
            "source_url": "https://www.hkexnews.hk",
            "pit_class": "snapshot_from_live_source",
            "source_license_class": "official_public_metadata",
            "entitlement_status": "verified",
            "entitlement_evidence": "",
            "entitlement_ref": "",
            "input_sha256": "fakehash",
            "schema_version": "control_tower_marts_v1",
            "missing_geographies": "",
            "detail": "HKEX disclosures active",
        }
    ])

    return ExtendedSnapshot(
        entities=entities,
        listings=listings,
        baskets=baskets,
        basket_memberships=basket_memberships,
        indices=indices,
        events=events,
        event_entity_links=event_entity_links,
        event_basket_links=event_basket_links,
        event_watch_questions=event_watch_questions,
        macro_observations=pd.DataFrame(),
        consensus_snapshots=pd.DataFrame(),
        consensus_revisions=pd.DataFrame(),
        quote_snapshots=quote_snapshots,
        price_bars=price_bars,
        news_filings=pd.DataFrame(),
        official_filings=pd.DataFrame(),
        earnings_calendar=pd.DataFrame(),
        earnings_actuals=earnings_actuals,
        source_health=source_health,
        manifest={"build_id": "test-build-tencent", "built_at_utc": "2026-08-21T12:00:00Z"},
        status="success",
        missing_optional=(),
        degraded_reasons={},
        build_id="test-build-tencent",
        built_at_utc=now_utc,
        as_of_utc=now_utc,
        previous_build_at=pd.Timestamp("2026-08-21T10:00:00Z"),
        corporate_actions=corporate_actions,
        valuation_snapshots=valuation_snapshots,
        internal_estimates=internal_estimates,
        thesis_claims=thesis_claims,
        thesis_watch_questions=thesis_watch_questions,
        evidence_items=evidence_items,
        claim_evidence_links=claim_evidence_links,
    )


def _write_manifest(root: Path, manifest: dict[str, object]) -> None:
    path = root / "build_manifest.json"
    for _ in range(8):
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        size = path.stat().st_size
        if manifest["artifacts"]["build_manifest.json"]["byte_size"] == size:
            return
        manifest["artifacts"]["build_manifest.json"]["byte_size"] = size
    raise AssertionError("manifest size did not converge")


def _write_test_bundle(root: Path, snapshot: ExtendedSnapshot) -> None:
    root.mkdir(parents=True, exist_ok=True)
    schema_map = {
        "entities.parquet": snapshot.entities,
        "listings.parquet": snapshot.listings,
        "baskets.parquet": snapshot.baskets,
        "basket_memberships.parquet": snapshot.basket_memberships,
        "indices.parquet": snapshot.indices,
        "events.parquet": snapshot.events.drop(columns=["related_entity_ids", "related_listing_ids", "related_basket_ids", "related_index_ids", "related_countries", "membership_tiers"], errors="ignore"),
        "event_entity_links.parquet": snapshot.event_entity_links,
        "event_basket_links.parquet": snapshot.event_basket_links,
        "event_watch_questions.parquet": snapshot.event_watch_questions,
        "macro_observations.parquet": snapshot.macro_observations,
        "consensus_snapshots.parquet": snapshot.consensus_snapshots,
        "consensus_revisions.parquet": snapshot.consensus_revisions,
        "quote_snapshots.parquet": snapshot.quote_snapshots,
        "price_bars.parquet": snapshot.price_bars,
        "news_filings.parquet": snapshot.news_filings,
        "official_filings.parquet": snapshot.official_filings,
        "earnings_calendar.parquet": snapshot.earnings_calendar,
        "earnings_actuals.parquet": snapshot.earnings_actuals,
        "source_health.parquet": snapshot.source_health,
    }
    for name, frame in schema_map.items():
        cols = ARTIFACT_COLUMNS[name]
        padded = frame.copy()
        for col in cols:
            if col not in padded.columns:
                padded[col] = pd.NA
        padded = padded.loc[:, [col for col in cols if col in padded.columns]]
        typed_df = _typed(padded)
        schema = _schema_for_columns(list(typed_df.columns))
        table = pa.Table.from_pandas(typed_df, schema=schema, preserve_index=False, safe=False)
        pq.write_table(table, root / name)

    artifacts: dict[str, dict[str, object]] = {}
    for name in (*schema_map.keys(), "build_manifest.json"):
        p = root / name
        is_m = name == "build_manifest.json"
        artifacts[name] = {
            "name": name,
            "relative_path": name,
            "sha256": None if is_m else hashlib.sha256(p.read_bytes()).hexdigest(),
            "row_count": 1 if is_m else len(schema_map[name]),
            "byte_size": 0 if is_m else p.stat().st_size,
            "schema_version": "control_tower_marts_v1",
            "source_ids": [],
            "status": "available",
        }
    manifest = {
        "schema_version": "control_tower_marts_v1",
        "build_id": "test-build-tencent-001",
        "status": "success",
        "built_at_utc": "2026-08-21T12:00:00Z",
        "as_of_utc": "2026-08-21T12:00:00Z",
        "previous_build_at": "2026-08-21T10:00:00Z",
        "network_policy": "forbidden",
        "input_fingerprints": {},
        "artifacts": artifacts,
        "degraded_inputs": [],
        "validation_errors": [],
        "source_health_summary": {"available": 1, "unavailable": 0},
    }
    _write_manifest(root, manifest)


def test_company_view_loads_tencent_t0_t3_additive_marts() -> None:
    """Verify build_company_view correctly binds all 7 additive marts."""
    snapshot = _make_tencent_snapshot()
    view = build_company_view(snapshot, entity_id="TENCENT")

    assert view.entity_id == "TENCENT"
    assert view.display_name == "Tencent Holdings"
    assert view.selected_listing_id == "0700_HK"
    assert view.selection_mode == "primary_default"

    # 1. Corporate actions (Buybacks)
    assert not view.corporate_actions.empty
    assert len(view.corporate_actions) == 1
    assert tuple(view.corporate_actions.columns) == COMPANY_CORPORATE_ACTION_COLUMNS
    action = view.corporate_actions.iloc[0]
    assert action["action_type"] == "buyback_execution"
    assert action["shares_affected"] == 681_000
    assert action["total_amount_paid"] == 300_451_683.90

    # 2. Valuation snapshots
    assert not view.valuation_snapshots.empty
    assert len(view.valuation_snapshots) == 1
    assert tuple(view.valuation_snapshots.columns) == COMPANY_VALUATION_COLUMNS
    val = view.valuation_snapshots.iloc[0]
    assert val["metric_name"] == "forward_pe"
    assert val["ratio_value"] == 16.2
    assert val["percentile_history_status"] == "unavailable"

    # 3. Internal estimates
    assert not view.internal_estimates.empty
    assert len(view.internal_estimates) == 1
    assert tuple(view.internal_estimates.columns) == COMPANY_INTERNAL_ESTIMATES_COLUMNS
    est = view.internal_estimates.iloc[0]
    assert est["observation_type"] == "internal_estimate"
    assert est["pit_class"] == "not_pit"

    # 4. Thesis claims
    assert not view.thesis_claims.empty
    assert len(view.thesis_claims) == 2
    assert tuple(view.thesis_claims.columns) == COMPANY_THESIS_CLAIM_COLUMNS
    assert set(view.thesis_claims["status"]) == {"draft"}

    # 5. Thesis watch questions
    assert not view.thesis_watch_questions.empty
    assert len(view.thesis_watch_questions) == 2
    assert tuple(view.thesis_watch_questions.columns) == COMPANY_THESIS_QUESTION_COLUMNS
    assert set(view.thesis_watch_questions["question_type"]) == {"support", "falsification"}

    # 6. Evidence items
    assert not view.evidence_items.empty
    assert len(view.evidence_items) == 1
    assert tuple(view.evidence_items.columns) == COMPANY_EVIDENCE_ITEM_COLUMNS

    # 7. Claim evidence links
    assert not view.claim_evidence_links.empty
    assert len(view.claim_evidence_links) == 1
    assert tuple(view.claim_evidence_links.columns) == COMPANY_CLAIM_EVIDENCE_LINK_COLUMNS
    link = view.claim_evidence_links.iloc[0]
    assert bool(link["conflict_hint"]) is False
    assert link["review_state"] == "pending_review"


def test_company_view_uses_one_listing_scope_and_keeps_entity_only_estimates_separate() -> None:
    snapshot = _make_tencent_snapshot()
    consensus = pd.DataFrame([
        {"entity_id": "TENCENT", "listing_id": "TCEHY_US", "provider": "yfinance"},
    ])
    revisions = pd.DataFrame([
        {"entity_id": "TENCENT", "listing_id": "TCEHY_US", "provider": "yfinance"},
    ])
    quotes = snapshot.quote_snapshots.copy()
    quote_row = quotes.iloc[0].copy()
    quote_row["listing_id"] = "TCEHY_US"
    quote_row["canonical_ticker"] = "TCEHY.US"
    quote_row["provider_symbol"] = "TCEHY"
    quotes = pd.concat([quotes, pd.DataFrame([quote_row])], ignore_index=True)
    bars = snapshot.price_bars.copy()
    bar_row = bars.iloc[0].copy()
    bar_row["listing_id"] = "TCEHY_US"
    bar_row["canonical_ticker"] = "TCEHY.US"
    bars = pd.concat([bars, pd.DataFrame([bar_row])], ignore_index=True)
    actions = snapshot.corporate_actions.copy()
    action_row = actions.iloc[0].copy()
    action_row["listing_id"] = "TCEHY_US"
    actions = pd.concat([actions, pd.DataFrame([action_row])], ignore_index=True)
    valuations = snapshot.valuation_snapshots.copy()
    valuation_row = valuations.iloc[0].copy()
    valuation_row["listing_id"] = "TCEHY_US"
    valuations = pd.concat([valuations, pd.DataFrame([valuation_row])], ignore_index=True)
    estimates = snapshot.internal_estimates.copy()
    estimate_row = estimates.iloc[0].copy()
    estimate_row["listing_id"] = "TCEHY_US"
    entity_only = estimate_row.copy()
    entity_only["estimate_id"] = "est-entity-only"
    entity_only["listing_id"] = ""
    estimates = pd.concat([estimates, pd.DataFrame([estimate_row, entity_only])], ignore_index=True)

    view = build_company_view(
        replace(
            snapshot,
            consensus_snapshots=consensus,
            consensus_revisions=revisions,
            quote_snapshots=quotes,
            price_bars=bars,
            corporate_actions=actions,
            valuation_snapshots=valuations,
            internal_estimates=estimates,
        ),
        entity_id="TENCENT",
    )

    assert view.scope_listing_id == view.selected_listing_id == "0700_HK"
    assert set(view.listings["listing_id"]) == {"0700_HK"}
    for frame in (
        view.consensus,
        view.consensus_revisions,
        view.quote_snapshots,
        view.price_bars,
        view.corporate_actions,
        view.valuation_snapshots,
    ):
        if "listing_id" in frame.columns:
            assert set(frame["listing_id"].dropna().astype(str)) <= {"0700_HK", ""}
    assert set(view.internal_estimates["listing_id"].fillna("").astype(str)) <= {"0700_HK", ""}
    assert "est-entity-only" in set(view.internal_estimates["estimate_id"])


def test_answer_first_summary_derives_selected_snapshot_facts() -> None:
    snapshot = _make_tencent_snapshot()
    view = build_company_view(snapshot, entity_id="TENCENT")

    summary = "\n".join(_answer_first_summary_lines(view, snapshot))

    assert "Latest fundamentals · 2026Q2" in summary
    assert "Revenue Total: CNY 204,785 million (IFRS)" in summary
    assert "Free Cash Flow: CNY -13,800 million (reported)" in summary
    assert "681,000 shares" in summary
    assert "HKD 300,451,683.9" in summary
    assert "Forward Pe: 16.2 (NON_IFRS_MANAGEMENT)" in summary
    assert "Tencent 3Q2026 Results Window" in summary
    assert "Thesis registry · 2 claim rows · draft: 2" in summary
    assert "Evidence lineage · 1 evidence rows" in summary
    assert "filings:hkexnews" in summary


def test_answer_first_summary_has_no_company_fact_fallbacks_when_marts_are_empty() -> None:
    snapshot = _make_tencent_snapshot()
    empty_snapshot = replace(
        snapshot,
        events=snapshot.events.iloc[0:0].copy(),
        event_entity_links=snapshot.event_entity_links.iloc[0:0].copy(),
        event_basket_links=snapshot.event_basket_links.iloc[0:0].copy(),
        earnings_actuals=snapshot.earnings_actuals.iloc[0:0].copy(),
        consensus_snapshots=snapshot.consensus_snapshots.iloc[0:0].copy(),
        corporate_actions=snapshot.corporate_actions.iloc[0:0].copy(),
        valuation_snapshots=snapshot.valuation_snapshots.iloc[0:0].copy(),
        thesis_claims=snapshot.thesis_claims.iloc[0:0].copy(),
        thesis_watch_questions=snapshot.thesis_watch_questions.iloc[0:0].copy(),
        evidence_items=snapshot.evidence_items.iloc[0:0].copy(),
        claim_evidence_links=snapshot.claim_evidence_links.iloc[0:0].copy(),
    )
    view = build_company_view(empty_snapshot, entity_id="TENCENT")

    summary = "\n".join(_answer_first_summary_lines(view, empty_snapshot))

    assert "Latest fundamentals unavailable" in summary
    assert "Recent corporate action unavailable" in summary
    assert "Expectation context unavailable" in summary
    assert "Valuation context unavailable" in summary
    assert "Upcoming catalyst unavailable" in summary
    assert "Thesis registry unavailable" in summary
    assert "Evidence lineage unavailable" in summary
    for forbidden in (
        "2Q2026",
        "204,785",
        "75,636",
        "13,800",
        "37,600",
        "51,400",
        "681,000",
        "300,451,683",
        "AI Ad Efficiencies",
        "Core Gaming & Advertising Compounder",
    ):
        assert forbidden not in summary


def test_company_view_supports_old_snapshots_safely() -> None:
    """Verify backward compatibility when optional T0-T3 fields are absent."""
    base = _make_tencent_snapshot()
    legacy_snapshot = ControlTowerSnapshot(
        entities=base.entities,
        listings=base.listings,
        baskets=base.baskets,
        basket_memberships=base.basket_memberships,
        indices=base.indices,
        events=base.events,
        event_entity_links=base.event_entity_links,
        event_basket_links=base.event_basket_links,
        event_watch_questions=base.event_watch_questions,
        macro_observations=base.macro_observations,
        consensus_snapshots=base.consensus_snapshots,
        consensus_revisions=base.consensus_revisions,
        quote_snapshots=base.quote_snapshots,
        price_bars=base.price_bars,
        news_filings=base.news_filings,
        official_filings=base.official_filings,
        earnings_calendar=base.earnings_calendar,
        earnings_actuals=base.earnings_actuals,
        source_health=base.source_health,
        manifest=base.manifest,
        status=base.status,
        missing_optional=base.missing_optional,
        degraded_reasons=base.degraded_reasons,
        build_id=base.build_id,
        built_at_utc=base.built_at_utc,
        as_of_utc=base.as_of_utc,
        previous_build_at=base.previous_build_at,
    )

    view = build_company_view(legacy_snapshot, entity_id="TENCENT")
    assert view.corporate_actions.empty
    assert view.valuation_snapshots.empty
    assert view.internal_estimates.empty
    assert view.thesis_claims.empty
    assert view.thesis_watch_questions.empty
    assert view.evidence_items.empty
    assert view.claim_evidence_links.empty
    assert tuple(view.corporate_actions.columns) == COMPANY_CORPORATE_ACTION_COLUMNS
    assert tuple(view.valuation_snapshots.columns) == COMPANY_VALUATION_COLUMNS
    assert tuple(view.internal_estimates.columns) == COMPANY_INTERNAL_ESTIMATES_COLUMNS
    assert tuple(view.thesis_claims.columns) == COMPANY_THESIS_CLAIM_COLUMNS
    assert tuple(view.thesis_watch_questions.columns) == COMPANY_THESIS_QUESTION_COLUMNS
    assert tuple(view.evidence_items.columns) == COMPANY_EVIDENCE_ITEM_COLUMNS
    assert tuple(view.claim_evidence_links.columns) == COMPANY_CLAIM_EVIDENCE_LINK_COLUMNS


def test_company_page_renders_four_tabs_cleanly_via_apptest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AppTest rendering verification of the four tabs and row-derived summary."""
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    root = tmp_path / "tencent-ui-apptest"
    snapshot = _make_tencent_snapshot()
    _write_test_bundle(root, snapshot)

    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(root))
    st.cache_data.clear()

    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception

    app.session_state["ct_page"] = "Company"
    app.session_state["ct_company_entity"] = "TENCENT"
    app = app.run()
    assert not app.exception

    text = _app_text(app)
    # 1. Company header and primary listing selector
    assert "Tencent Holdings" in text
    assert "Selected listing · 0700.HK · HKEX · HKD · primary listing default" in text

    # 2. Four tabs present
    assert "Overview" in text
    assert "Fundamentals" in text
    assert "Thesis & Catalysts" in text
    assert "Evidence" in text

    # 3. Answer-first executive summary from bundle rows
    assert "Executive summary &amp; recent changes · Tencent Holdings · 0700.HK" in text
    assert "Latest fundamentals · 2026Q2" in text
    assert "Revenue Total: CNY 204,785 million (IFRS)" in text
    assert "Free Cash Flow: CNY -13,800 million (reported)" in text
    assert "Recent corporate action unavailable" in text

    # 4. Market quote display
    assert "HKD 441.20" in text
    assert "+1.45%" in text
    assert "Freshness: delayed" in text

    # 5. Price history
    assert "Price history" in text

    # 6. Fundamentals section
    assert "Segment disclosures & core operations" in text
    assert "Profitability & Free Cash Flow trajectory" in text
    assert "Reported and normalized values remain distinct" in text

    # 7. Thesis & Catalysts section
    assert "Thesis claims (Human-authored)" in text
    assert "Active & upcoming catalysts" in text
    assert "Operational watch questions & falsification criteria" in text

    # 8. Evidence section
    assert "Official filings and announcements metadata" in text
    assert "Provider-specific consensus" in text
    assert "Consensus revisions" in text


def test_private_entity_bytedance_handles_quotes_and_price_history_not_applicable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify private companies render honest not-applicable states without crashing."""
    from streamlit.testing.v1 import AppTest
    import streamlit as st

    root = tmp_path / "bytedance-ui-apptest"
    snapshot = _make_tencent_snapshot()
    _write_test_bundle(root, snapshot)

    monkeypatch.setenv("CONTROL_TOWER_ARTIFACT_ROOT", str(root))
    st.cache_data.clear()

    app = AppTest.from_file(str(APP_PATH), default_timeout=30).run()
    assert not app.exception

    app.session_state["ct_page"] = "Company"
    app.session_state["ct_company_entity"] = "BYTEDANCE"
    app = app.run()
    assert not app.exception

    text = _app_text(app)
    assert "ByteDance" in text
    assert "private / no listing" in text
    assert "Not applicable · ByteDance is a private company with no public market listing" in text


def test_company_view_preserves_strict_no_network_isolation() -> None:
    """Verify building and rendering the company view performs zero socket connections."""
    import socket

    def guarded_socket(*args, **kwargs):
        raise RuntimeError("Network socket call attempted during UI rendering!")

    snapshot = _make_tencent_snapshot()
    orig_socket = socket.socket
    try:
        socket.socket = guarded_socket
        view = build_company_view(snapshot, entity_id="TENCENT")
        assert view.entity_id == "TENCENT"
    finally:
        socket.socket = orig_socket

    assert view.quote_status == "available"


def test_dark_theme_css_tokens_and_components() -> None:
    css = get_control_tower_css("Dark")
    assert '.stTabs [data-baseweb="tab-list"]' in css
    assert '--gdg-bg-cell: #161b22' in css
    assert '[data-baseweb="select"] > div' in css


def test_company_catalyst_date_precision_and_active_status_rendering() -> None:
    snapshot = _make_tencent_snapshot()
    view = build_company_view(snapshot, entity_id="TENCENT")
    summary = "\n".join(_answer_first_summary_lines(view, snapshot))
    assert "Tencent 3Q2026 Results Window" in summary
    assert "Nov 2026" in summary
    assert "Upcoming catalyst" in summary
