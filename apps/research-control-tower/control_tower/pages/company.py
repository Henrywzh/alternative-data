"""Company identity, registry lineage, fundamental and thesis cockpit view."""

from __future__ import annotations
from pathlib import Path

from dataclasses import dataclass, field
from datetime import timedelta
from html import escape
import re
import unicodedata
import json
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import pyarrow.parquet as pq
import streamlit as st

from ..charts import (
    ACCENT,
    MODEL_COLORS,
    apply_theme as apply_chart_theme,
    bar_chart as _plotly_bar_chart,
    dual_axis_bar_line,
    line_chart as _plotly_line_chart,
    stacked_share_chart,
)

from ..company_profiles import SegmentSpec, get_company_profile, segment_label

from src.research_control_tower.eligibility import listing_eligibility_reason
from src.research_control_tower.southbound_holdings import hkex_security_code, southbound_mart_path
from src.research_control_tower.live_refresh import (
    load_local_hkex_overlay,
    record_refresh,
    refresh_company_news,
    refresh_cooldown_remaining,
)
from src.research_control_tower.news_overlay import load_local_news_overlay
from src.research_control_tower.vendor_financials import (
    VendorLoadResult,
    default_local_mart_path,
    load_vendor_financials,
    vendor_source_caption,
)

from ..filters import apply_event_filters
from ..formatting import format_t_minus
from ..components import ct_dataframe
from ..components.timeline import format_event_window, is_active_catalyst, select_next_catalyst
from ..market_data import QUOTE_SNAPSHOT_COLUMNS, classify_quote_freshness, format_quote_age
from ..models import ControlTowerSnapshot, EventFilters
from ..components.filings_earnings import (
    render_official_filings,
    render_earnings_calendar,
    render_earnings_actuals,
    render_filings_earnings_sections,
)
from .source_health import classify_source_health

def _slugify(text: str) -> str:
    norm = unicodedata.normalize("NFKD", text)
    norm = re.sub(r"[^\w\s-]", "", norm).strip().lower()
    return re.sub(r"[-_\s]+", "-", norm)


def _render_section_heading(level: int, title: str, anchor: str | None = None) -> None:
    anchor_id = anchor or _slugify(title)
    st.html(f'<h{level} id="{escape(anchor_id)}">{escape(title)}</h{level}>')


COMPANY_LISTING_COLUMNS = (
    "listing_id", "entity_id", "exchange", "native_ticker", "canonical_ticker",
    "financial_data_security_id", "mapping_status", "mapping_verified_at", "mapping_source_url",
    "collection_eligible", "listing_role", "vendor_tickers", "currency", "primary_listing",
    "active_from", "active_to", "listing_status",
)
COMPANY_MEMBERSHIP_COLUMNS = (
    "basket_id", "basket_display_name", "membership_tier", "primary_layer", "secondary_layers",
    "active_from", "active_to", "membership_reason",
)
COMPANY_EVENT_COLUMNS = (
    "event_id", "event_key", "observation_version", "scope", "event_type", "title", "description",
    "status", "certainty_class", "confidence", "date_precision", "starts_at", "ends_at",
    "source_timezone", "source_id", "source_url", "source_published_at", "first_observed_at",
    "last_verified_at", "review_by", "supersedes_event_id", "evidence_class", "evidence_ref",
    "related_entity_ids", "related_listing_ids", "related_basket_ids", "watch_question_count",
    "relation_role",
)
COMPANY_DOCUMENT_COLUMNS = (
    "document_id", "document_type", "source_id", "headline", "publisher", "published_at",
    "first_observed_at", "source_url", "language", "related_entity_ids", "related_listing_ids",
    "related_basket_ids", "event_class", "importance", "source_quality", "pit_class",
    "source_license_class", "content_hash_if_permitted", "derived_summary_if_permitted",
)
COMPANY_CONSENSUS_COLUMNS = (
    "snapshot_id", "provider", "entity_id", "listing_id", "financial_data_security_id", "canonical_ticker",
    "metric", "fiscal_period", "fiscal_year", "estimate_period_end", "horizon", "snapshot_at", "value",
    "statistic", "low_value", "high_value", "analyst_count", "provider_contributor_count", "currency",
    "unit", "accounting_basis", "provider_asof", "retrieved_at_utc", "source_url", "raw_hash", "pit_class",
    "source_run_id", "calculation_origin", "coverage_reason",
)
COMPANY_REVISION_COLUMNS = (
    "revision_id", "snapshot_id", "provider", "prior_provider", "entity_id", "listing_id",
    "financial_data_security_id", "canonical_ticker", "metric", "fiscal_period", "fiscal_year",
    "estimate_period_end", "horizon", "statistic", "current_snapshot_at", "current_value",
    "current_analyst_count", "current_dispersion", "lookback_days", "cutoff_at", "prior_snapshot_id",
    "prior_snapshot_at", "prior_value", "prior_provider_asof", "provider_asof", "retrieved_at_utc",
    "source_url", "pit_class", "source_run_id", "prior_analyst_count", "revision_value", "revision_pct",
    "analyst_count_change", "dispersion", "alignment_status",
)
COMPANY_QUOTE_COLUMNS = (*QUOTE_SNAPSHOT_COLUMNS, "freshness")
COMPANY_QUESTION_COLUMNS = ("event_id", "question_id", "question", "question_type", "priority", "registry_version")
COMPANY_INVALIDATION_COLUMNS = (
    "evidence_id", "event_id", "entity_id", "question_id", "question_type", "source_id", "observed_at",
    "title", "detail", "source_url", "evidence_class", "pit_class", "source_license_class", "status",
)
COMPANY_CORPORATE_ACTION_COLUMNS = (
    "action_id", "listing_id", "action_type", "filing_date", "execution_date",
    "shares_affected", "price_min", "price_max", "price_avg", "total_amount_paid",
    "currency", "cancellation_status", "coverage_reason", "source_url",
    "retrieved_at_utc", "pit_class",
)
COMPANY_VALUATION_COLUMNS = (
    "valuation_id", "listing_id", "valuation_date", "valuation_at", "metric_name",
    "metric_basis", "ratio_value", "numerator_value", "numerator_currency",
    "numerator_ref", "denominator_value", "denominator_currency", "denominator_ref",
    "fx_rate_applied", "fx_source", "fx_snapshot_at_utc", "source_id", "source_url",
    "retrieved_at_utc", "pit_class", "coverage_reason", "percentile_history_status",
)
COMPANY_INTERNAL_ESTIMATES_COLUMNS = (
    "estimate_id", "version", "supersedes_estimate_id", "entity_id", "listing_id",
    "observation_type", "author", "metric", "accounting_basis", "metric_basis",
    "fiscal_period", "fiscal_year", "value_low", "value_high", "value_mid",
    "currency", "unit", "effective_asof", "recorded_at_utc", "rationale_notes",
    "source_ref", "source_url", "pit_class", "reviewed_at_utc", "reviewed_by",
)
COMPANY_THESIS_CLAIM_COLUMNS = (
    "claim_id", "entity_id", "thesis_title", "claim_text", "invalidation_rule",
    "status", "last_reviewed_at_utc", "reviewed_by", "registry_version",
)
COMPANY_THESIS_QUESTION_COLUMNS = (
    "question_id", "claim_id", "entity_id", "question", "question_type", "priority", "registry_version",
)
COMPANY_EVIDENCE_ITEM_COLUMNS = (
    "evidence_id", "entity_id", "source_id", "evidence_ref", "source_type", "source_url",
    "evidence_class", "pit_class", "source_license_class", "published_at", "summary_text",
    "observed_at_utc", "content_hash", "registry_version",
)
COMPANY_CLAIM_EVIDENCE_LINK_COLUMNS = (
    "link_id", "claim_id", "evidence_id", "conflict_hint", "review_state", "analyst_note", "registry_version",
)


@dataclass(frozen=True, slots=True)
class CompanyView:
    entity_id: str
    legal_name: str
    display_name: str
    country: str
    sector: str
    industry: str
    entity_type: str
    active_status: str
    selected_listing_id: str | None
    selection_mode: str
    listings: pd.DataFrame
    memberships: pd.DataFrame
    quote_snapshots: pd.DataFrame
    quote_status: str
    price_bars: pd.DataFrame
    events: pd.DataFrame
    official_documents: pd.DataFrame
    consensus: pd.DataFrame
    consensus_revisions: pd.DataFrame
    consensus_status: str
    source_health: pd.DataFrame
    watch_questions: pd.DataFrame
    invalidation_evidence: pd.DataFrame
    caveats: tuple[str, ...]
    corporate_actions: pd.DataFrame = field(default_factory=pd.DataFrame)
    valuation_snapshots: pd.DataFrame = field(default_factory=pd.DataFrame)
    internal_estimates: pd.DataFrame = field(default_factory=pd.DataFrame)
    thesis_claims: pd.DataFrame = field(default_factory=pd.DataFrame)
    thesis_watch_questions: pd.DataFrame = field(default_factory=pd.DataFrame)
    evidence_items: pd.DataFrame = field(default_factory=pd.DataFrame)
    claim_evidence_links: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def scope_listing_id(self) -> str | None:
        """The one listing scope applied to every listing-scoped mart."""

        return self.selected_listing_id


def _text(value: object) -> str:
    if value is None or value is pd.NA:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _timestamp(value: object) -> pd.Timestamp | None:
    if value is None or value is pd.NaT:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed) or parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.tz_convert("UTC")


def _date(value: object) -> pd.Timestamp | None:
    timestamp = _timestamp(value)
    if timestamp is not None:
        return timestamp.tz_localize(None).normalize()
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return None if pd.isna(parsed) else parsed.normalize()


def _source_timezone(event: Any) -> ZoneInfo:
    name = _text(event.get("source_timezone")) or "UTC"
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        return ZoneInfo("UTC")


def _interval_timestamp(
    value: object,
    *,
    source_timezone: ZoneInfo,
) -> pd.Timestamp | None:
    timestamp = _timestamp(value)
    if timestamp is not None:
        return timestamp
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.tz_localize(source_timezone)
    return parsed.tz_convert("UTC")


def _active(row: Any, as_of: pd.Timestamp) -> bool:
    point = as_of.tz_localize(None).normalize()
    start = _date(row.get("active_from"))
    end = _date(row.get("active_to"))
    return (start is None or point >= start) and (end is None or point < end)


def _market_entity_eligible(row: Any, as_of: pd.Timestamp) -> bool:
    entity_type = _text(row.get("entity_type")).lower() or "public"
    active_status = _text(row.get("active_status")).lower()
    return entity_type != "private" and active_status in {"", "active"} and _active(row, as_of)


def _market_listing_eligible(row: Any, as_of: pd.Timestamp) -> bool:
    return listing_eligibility_reason(row, as_of) is None


def _scope_listing_rows(
    frame: pd.DataFrame,
    *,
    entity_id: str,
    scope_listing_id: str | None,
    include_entity_only: bool = True,
) -> pd.DataFrame:
    """Apply one selected-listing scope without leaking another listing."""

    if frame is None or frame.empty:
        return frame.copy() if frame is not None else pd.DataFrame()
    scoped = frame.copy()
    if "entity_id" in scoped.columns:
        scoped = scoped.loc[scoped["entity_id"].astype("string").eq(entity_id)]
    if "listing_id" not in scoped.columns:
        return scoped.copy()
    listing = scoped["listing_id"].map(_text)
    entity_only = listing.eq("")
    if scope_listing_id:
        mask = listing.eq(scope_listing_id)
        if include_entity_only:
            mask |= entity_only
    else:
        mask = entity_only if include_entity_only else pd.Series(False, index=scoped.index)
    return scoped.loc[mask].copy()


def _vendor_symbols(row: Any) -> tuple[str, ...]:
    raw = row.get("vendor_tickers", "")
    if not _text(raw):
        return ()
    return tuple(
        symbol.strip()
        for token in str(raw).split(";")
        for name, separator, symbol in [token.partition(":")]
        if separator and symbol.strip()
    )


def _derived_provider_symbol(listing: Any, source_id: object) -> str:
    raw = _text(listing.get("vendor_tickers"))
    if not raw:
        return ""
    providers: dict[str, list[str]] = {}
    for token in raw.split(";"):
        name, separator, symbol = token.partition(":")
        if separator and symbol.strip():
            providers.setdefault(name.strip().casefold(), []).append(symbol.strip())
    provider_key = _text(source_id).rsplit(":", 1)[-1].casefold()
    candidates = providers.get(provider_key, [])
    if len(candidates) == 1:
        return candidates[0]
    all_symbols = [symbol for symbols in providers.values() for symbol in symbols]
    return all_symbols[0] if len(all_symbols) == 1 else ""


def _quote_matches_listing(quote: Any, listing: Any) -> bool:
    canonical = _text(quote.get("canonical_ticker"))
    registry_canonical = _text(listing.get("canonical_ticker"))
    if canonical and registry_canonical and canonical != registry_canonical:
        return False
    currency = _text(quote.get("currency")).upper()
    registry_currency = _text(listing.get("currency")).upper()
    if currency and registry_currency and currency != registry_currency:
        return False
    provider_symbol = _text(quote.get("provider_symbol"))
    registry_symbols = _vendor_symbols(listing)
    return not provider_symbol or not registry_symbols or provider_symbol in registry_symbols


def _derive_quote_registry_truth(frame: pd.DataFrame, listing_by_id: dict[str, dict[str, object]]) -> pd.DataFrame:
    output = frame.copy()
    for index, row in output.iterrows():
        listing = listing_by_id.get(_text(row.get("listing_id")), {})
        output.at[index, "canonical_ticker"] = _text(listing.get("canonical_ticker"))
        output.at[index, "currency"] = _text(listing.get("currency"))
        if not _text(row.get("provider_symbol")):
            output.at[index, "provider_symbol"] = _derived_provider_symbol(
                listing, row.get("source_id")
            )
    return output


def _safe_quote_descriptors(frame: pd.DataFrame) -> pd.DataFrame:
    """Enforce the delayed, personal-use quote contract at the view boundary."""

    output = frame.copy()
    if "latency_class" in output.columns:
        output["latency_class"] = "delayed"
    if "pit_class" in output.columns:
        output["pit_class"] = output["pit_class"].map(
            lambda value: "snapshot_from_delayed_source"
            if _text(value).lower() in {"", "live", "snapshot_from_live_source"}
            else _text(value)
        )
    if "source_license_class" in output.columns:
        output["source_license_class"] = output["source_license_class"].map(
            lambda value: "personal_use_terms_unverified"
            if _text(value).lower() in {"", "public", "public_metadata"}
            else _text(value)
        )
    return output


def _active_for_event(row: Any, event: Any, fallback: pd.Timestamp) -> bool:
    event_start = _timestamp(event.get("starts_at")) or fallback
    event_end = _timestamp(event.get("ends_at"))
    source_timezone = _source_timezone(event)
    link_start = _interval_timestamp(
        row.get("active_from"), source_timezone=source_timezone
    )
    link_end = _interval_timestamp(
        row.get("active_to"), source_timezone=source_timezone
    )
    if event_end is None and _text(event.get("date_precision")).lower() in {"date", "day"}:
        local_date = event_start.tz_convert(source_timezone).date()
        next_local_midnight = pd.Timestamp(local_date + timedelta(days=1)).tz_localize(
            source_timezone
        )
        event_end = next_local_midnight.tz_convert("UTC")
    elif event_end is None:
        return (
            (link_start is None or link_start <= event_start)
            and (link_end is None or event_start < link_end)
        )
    return (
        (link_end is None or event_start < link_end)
        and (event_end is None or link_start is None or link_start < event_end)
    )


def _ids(value: object) -> tuple[str, ...]:
    if value is None or value is pd.NA:
        return ()
    if isinstance(value, (tuple, list, set, frozenset)):
        return tuple(sorted({str(item).strip() for item in value if str(item).strip()}))
    text = _text(value)
    if not text:
        return ()
    if text.startswith("["):
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            decoded = None
        if isinstance(decoded, list):
            return tuple(sorted({str(item).strip() for item in decoded if str(item).strip()}))
    return tuple(sorted({item.strip() for item in text.split(";") if item.strip()}))


def _empty(columns: tuple[str, ...]) -> pd.DataFrame:
    timestamp_columns = {
        "mapping_verified_at", "active_from", "active_to", "published_at", "first_observed_at",
        "source_published_at", "last_verified_at", "review_by", "starts_at", "ends_at", "snapshot_at",
        "provider_asof", "retrieved_at_utc", "estimate_period_end", "current_snapshot_at", "cutoff_at",
        "prior_snapshot_at", "prior_provider_asof", "quote_timestamp",
        "valuation_at", "fx_snapshot_at_utc", "recorded_at_utc", "reviewed_at_utc", "observed_at_utc",
        "filing_date", "execution_date", "valuation_date", "last_reviewed_at_utc",
    }
    return pd.DataFrame(
        {
            column: pd.Series(
                [],
                dtype="datetime64[ns, UTC]" if column in timestamp_columns else "object",
            )
            for column in columns
        }
    )


def _link_active(link: Any, event: Any, fallback: pd.Timestamp) -> bool:
    return _active_for_event(link, event, fallback)


def _event_relation(snapshot: ControlTowerSnapshot, event: Any, entity_id: str, listing_ids: set[str]) -> str | None:
    event_id = _text(event.get("event_id"))
    entity_links = snapshot.event_entity_links.loc[snapshot.event_entity_links["event_id"].astype("string").eq(event_id)] if not snapshot.event_entity_links.empty else snapshot.event_entity_links
    basket_links = snapshot.event_basket_links.loc[snapshot.event_basket_links["event_id"].astype("string").eq(event_id)] if not snapshot.event_basket_links.empty else snapshot.event_basket_links

    # 1. Check for active explicit entity/listing links for this event
    has_active_explicit_links = False
    roles: set[str] = set()
    for _, link in entity_links.iterrows():
        if not _link_active(link, event, snapshot.as_of_utc):
            continue
        has_active_explicit_links = True
        target_type = _text(link.get("target_type")).lower()
        target_id = _text(link.get("target_id"))
        if target_type == "entity" and target_id == entity_id:
            roles.add("entity")
        elif target_type == "listing" and target_id in listing_ids:
            roles.add("listing")
    if has_active_explicit_links:
        # Fail-closed precedence: when any active explicit entity/listing links exist,
        # only those explicit targets define Company-page relation; basket links must not broaden to other companies.
        if roles:
            return "entity" if "entity" in roles else "listing"
        return None

    # 2. Check basket links for basket-only events (no active explicit entity/listing links)
    for _, link in basket_links.iterrows():
        if not _link_active(link, event, snapshot.as_of_utc):
            continue
        basket_id = _text(link.get("target_id"))
        if snapshot.basket_memberships.empty:
            continue
        active_membership = snapshot.basket_memberships.loc[
            snapshot.basket_memberships["basket_id"].astype("string").eq(basket_id)
            & snapshot.basket_memberships["entity_id"].astype("string").eq(entity_id)
        ]
        if any(_active_for_event(row, event, snapshot.as_of_utc) for _, row in active_membership.iterrows()):
            return "basket_membership"

    # 3. If raw links existed in the tables, do not fall back to denormalized fields
    has_raw_link = not entity_links.empty or not basket_links.empty
    if has_raw_link:
        return None

    # 4. Fallback to denormalized related_* only when no raw links exist in tables
    related_entities = set(_ids(event.get("related_entity_ids")))
    related_listings = set(_ids(event.get("related_listing_ids")))
    if related_entities or related_listings:
        if entity_id in related_entities:
            return "entity"
        if listing_ids.intersection(related_listings):
            return "listing"
        return None
    return None


def _document_matches(snapshot: ControlTowerSnapshot, row: Any, entity_id: str, listing_ids: set[str], basket_ids: set[str]) -> bool:
    return bool(
        entity_id in set(_ids(row.get("related_entity_ids")))
        or listing_ids.intersection(set(_ids(row.get("related_listing_ids"))))
        or basket_ids.intersection(set(_ids(row.get("related_basket_ids"))))
    )


def _source_relevance(frame: pd.DataFrame) -> set[str]:
    if frame.empty or "source_id" not in frame.columns:
        return set()
    return {value for value in frame["source_id"].map(_text) if value}


def _collapse_superseded_event_rows(events: pd.DataFrame) -> tuple[pd.DataFrame, tuple[str, ...]]:
    if events.empty:
        return events.copy(), ()
    event_ids = set(events["event_id"].astype("string"))
    superseded = tuple(
        sorted(
            {
                value
                for value in events.get("supersedes_event_id", pd.Series(dtype="string")).map(_text)
                if value and value in event_ids
            }
        )
    )
    visible = events.loc[~events["event_id"].astype("string").isin(superseded)].copy()
    return visible.reset_index(drop=True), superseded


def _provider_source_rows(
    snapshot: ControlTowerSnapshot,
    classified: pd.DataFrame,
    consensus: pd.DataFrame,
) -> pd.DataFrame:
    """Return explicit provider health rows without upgrading missing health."""

    providers = ("yfinance", "akshare", "fnguide", "futu")
    existing = classified.copy(deep=True)
    raw_rows: list[dict[str, object]] = []
    export_rows = existing.loc[
        existing["source_id"].astype("string").str.contains("consensus_export", case=False, na=False)
    ] if not existing.empty else existing
    for provider in providers:
        provider_mask = existing["source_id"].astype("string").str.contains(provider, case=False, na=False) if not existing.empty else pd.Series(dtype="boolean")
        if provider_mask.any():
            continue
        provider_rows = consensus.loc[
            consensus.get("provider", pd.Series("", index=consensus.index)).astype("string").str.casefold().eq(provider)
        ] if not consensus.empty else consensus
        if not provider_rows.empty:
            latest = provider_rows.get("snapshot_at", pd.Series(dtype="datetime64[ns, UTC]")).dropna()
            retrieved = provider_rows.get("retrieved_at_utc", pd.Series(dtype="datetime64[ns, UTC]")).dropna()
            raw_rows.append(
                {
                    "source_id": f"provider:{provider}",
                    "input_path": "consensus provider rows",
                    "source_kind": "consensus_provider",
                    "status": "degraded",
                    "required": False,
                    "row_count": len(provider_rows),
                    "latest_observation_at": latest.max() if not latest.empty else pd.NaT,
                    "source_latest_at": latest.max() if not latest.empty else pd.NaT,
                    "retrieved_at_utc": retrieved.max() if not retrieved.empty else pd.NaT,
                    "cadence": "irregular",
                    "source_url": _text(provider_rows.iloc[0].get("source_url")),
                    "pit_class": _text(provider_rows.iloc[0].get("pit_class")),
                    "source_license_class": "",
                    "schema_version": "",
                    "missing_geographies": "",
                    "detail": "provider rows present; provider-specific source-health row unavailable",
                }
            )
        elif not export_rows.empty:
            export = export_rows.iloc[0]
            raw_rows.append(
                {
                    "source_id": f"provider:{provider}",
                    "input_path": _text(export.get("input_path")) or "consensus export",
                    "source_kind": "consensus_provider",
                    "status": _text(export.get("status")) or "unavailable",
                    "required": False,
                    "row_count": 0,
                    "retrieved_at_utc": export.get("retrieved_at_utc", pd.NaT),
                    "cadence": _text(export.get("cadence")),
                    "source_url": _text(export.get("source_url")),
                    "pit_class": _text(export.get("pit_class")),
                    "source_license_class": _text(export.get("source_license_class")),
                    "schema_version": _text(export.get("schema_version")),
                    "missing_geographies": _text(export.get("missing_geographies")),
                    "detail": f"{provider} provider export unavailable; {_text(export.get('detail')) or 'no provider-specific export row'}",
                }
            )
        else:
            raw_rows.append(
                {
                    "source_id": f"provider:{provider}",
                    "input_path": "consensus provider export",
                    "source_kind": "consensus_provider",
                    "status": "unavailable",
                    "required": False,
                    "row_count": 0,
                    "cadence": "irregular",
                    "source_url": "",
                    "pit_class": "",
                    "source_license_class": "",
                    "schema_version": "",
                    "missing_geographies": "",
                    "detail": f"{provider} provider export unavailable; no local provider-specific source-health row",
                }
            )
    if not raw_rows:
        return existing
    additions = classify_source_health(pd.DataFrame(raw_rows), now_utc=snapshot.now_utc)
    return pd.concat([existing, additions], ignore_index=True).drop_duplicates(subset=["source_id"], keep="last")


def build_company_view(
    snapshot: ControlTowerSnapshot,
    *,
    entity_id: str,
    listing_id: str | None = None,
    filters: EventFilters | None = None,
) -> CompanyView:
    """Build one company view using only explicit registry and mart relations."""

    requested_entity = _text(entity_id)
    entity_rows = snapshot.entities.loc[snapshot.entities["entity_id"].astype("string").eq(requested_entity)] if not snapshot.entities.empty else snapshot.entities
    if entity_rows.empty:
        raise ValueError(f"unknown entity_id: {entity_id!r}")
    entity = entity_rows.iloc[0]
    as_of = snapshot.as_of_utc
    all_entity_listings = snapshot.listings.loc[snapshot.listings["entity_id"].astype("string").eq(requested_entity)] if not snapshot.listings.empty else snapshot.listings
    if _market_entity_eligible(entity, as_of) and not all_entity_listings.empty:
        active_listings = all_entity_listings.loc[
            all_entity_listings.apply(lambda row: _market_listing_eligible(row, as_of), axis=1)
        ].copy()
    else:
        active_listings = all_entity_listings.iloc[0:0].copy()
    listing_ids = set(active_listings["listing_id"].astype("string")) if not active_listings.empty else set()
    if listing_id is not None:
        requested_listing = _text(listing_id)
        if requested_listing not in listing_ids:
            raise ValueError(
                f"listing_id {listing_id!r} is not an active, verified public listing for entity {requested_entity!r}"
            )
        selected_listing_id = requested_listing
        selection_mode = "explicit"
    else:
        eligible = active_listings.loc[
            active_listings["mapping_status"].astype("string").str.lower().eq("verified")
            & active_listings["listing_status"].astype("string").str.lower().eq("active")
        ] if not active_listings.empty else active_listings
        if eligible.empty:
            selected_listing_id = None
            selection_mode = "none"
        else:
            exchanges = eligible["exchange"].astype("string").str.upper()
            roles = eligible.get("listing_role", pd.Series("", index=eligible.index, dtype="string")).astype("string").str.lower()
            has_hkex = bool(exchanges.eq("HKEX").any())
            has_us_listing = bool(
                roles.eq("depositary_receipt").any()
                or exchanges.isin(["NYSE", "NASDAQ", "OTC"]).any()
            )
            # China-internet ADR pairs: prefer the HK ordinary share.
            #
            # config/listings.csv has since been corrected -- Alibaba, Baidu
            # and JD all mark the HK line primary now -- so for anything
            # published from it this branch and the generic one agree. It
            # stays because the snapshot comes from a *published generation*,
            # and generations are frozen: an older bundle still carries the
            # ADR marked primary, and loading one must not silently flip the
            # page to the US line.
            #
            # Known limitation: an issuer genuinely primary in the US with an
            # HK secondary would be mis-preferred here. No such issuer is in
            # the registry; revisit this rule before adding one.
            if has_hkex and has_us_listing:
                pool = eligible.loc[exchanges.eq("HKEX")].copy()
            else:
                pool = eligible.loc[
                    eligible["primary_listing"].map(
                        lambda value: _text(value).lower() in {"true", "1", "yes"}
                    )
                ].copy()
                if pool.empty:
                    pool = eligible.copy()
            role_rank = {"primary": 0, "dual_primary": 1, "secondary": 2, "depositary_receipt": 3}
            ranked = pool.copy()
            ranked["__primary_rank"] = ranked["primary_listing"].map(
                lambda value: 0 if _text(value).lower() in {"true", "1", "yes"} else 1
            )
            ranked["__role_rank"] = ranked["listing_role"].map(role_rank).fillna(99)
            ranked = ranked.sort_values(
                ["__primary_rank", "__role_rank", "listing_id"],
                kind="mergesort",
            )
            selected_listing_id = _text(ranked.iloc[0]["listing_id"])
            selection_mode = "primary_default"

    listings = active_listings.loc[:, [column for column in COMPANY_LISTING_COLUMNS if column in active_listings.columns]].copy() if not active_listings.empty else _empty(COMPANY_LISTING_COLUMNS)
    for column in COMPANY_LISTING_COLUMNS:
        if column not in listings.columns:
            listings[column] = pd.NA
    listings = listings.loc[:, COMPANY_LISTING_COLUMNS]

    memberships = snapshot.basket_memberships.loc[
        snapshot.basket_memberships["entity_id"].astype("string").eq(requested_entity)
        & snapshot.basket_memberships.apply(lambda row: _active(row, as_of), axis=1)
    ].copy() if not snapshot.basket_memberships.empty else snapshot.basket_memberships.copy()
    basket_names = snapshot.baskets.set_index("basket_id")["display_name"].to_dict() if not snapshot.baskets.empty else {}
    if not memberships.empty:
        memberships["basket_display_name"] = memberships["basket_id"].map(lambda value: _text(basket_names.get(_text(value))))
        memberships = memberships.rename(columns={"basket_id": "basket_id"})
        memberships = memberships.loc[:, [column for column in ("basket_id", "basket_display_name", "membership_tier", "primary_layer", "secondary_layers", "active_from", "active_to", "membership_reason") if column in memberships.columns]]
    else:
        memberships = _empty(COMPANY_MEMBERSHIP_COLUMNS)
    for column in COMPANY_MEMBERSHIP_COLUMNS:
        if column not in memberships.columns:
            memberships[column] = pd.NA
    memberships = memberships.loc[:, COMPANY_MEMBERSHIP_COLUMNS]
    basket_ids = set(memberships["basket_id"].astype("string")) if not memberships.empty else set()

    # Price history is scoped to the same listing the quote is
    bars_source = getattr(snapshot, "price_bars", pd.DataFrame())
    if bars_source is None or bars_source.empty or not selected_listing_id:
        price_bars = pd.DataFrame(columns=["bar_date", "close", "adj_close", "volume", "listing_id", "currency", "source_id"])
    else:
        price_bars = _scope_listing_rows(
            bars_source,
            entity_id=requested_entity,
            scope_listing_id=selected_listing_id,
            include_entity_only=False,
        )
        if not price_bars.empty:
            price_bars = price_bars.sort_values("bar_date")

    quote_source = snapshot.quote_snapshots
    if quote_source.empty or not selected_listing_id:
        quote_snapshots = _empty(COMPANY_QUOTE_COLUMNS)
    else:
        quote_snapshots = quote_source.loc[
            quote_source["listing_id"].astype("string").eq(selected_listing_id)
        ].copy()
        if not quote_snapshots.empty:
            listing_by_id = active_listings.set_index("listing_id", drop=False).to_dict("index")
            quote_snapshots = quote_snapshots.loc[
                quote_snapshots.apply(
                    lambda row: _quote_matches_listing(
                        row,
                        listing_by_id.get(_text(row.get("listing_id")), {}),
                    ),
                    axis=1,
                )
            ].copy()
            if not quote_snapshots.empty:
                quote_snapshots = _derive_quote_registry_truth(
                    quote_snapshots, listing_by_id
                )
        if filters is not None and filters.scope and "company" not in filters.scope:
            quote_snapshots = quote_snapshots.iloc[0:0].copy()
        if quote_snapshots.empty:
            quote_snapshots = _empty(COMPANY_QUOTE_COLUMNS)
        else:
            quote_snapshots = _safe_quote_descriptors(quote_snapshots)
            quote_snapshots["freshness"] = quote_snapshots.apply(
                lambda row: classify_quote_freshness(
                    row.get("quote_timestamp"),
                    snapshot.now_utc,
                    "delayed",
                ),
                axis=1,
            )
            quote_snapshots = quote_snapshots.loc[
                :, [column for column in COMPANY_QUOTE_COLUMNS if column in quote_snapshots.columns]
            ].copy()
            for column in COMPANY_QUOTE_COLUMNS:
                if column not in quote_snapshots.columns:
                    quote_snapshots[column] = pd.NA
            quote_snapshots = quote_snapshots.loc[:, COMPANY_QUOTE_COLUMNS].sort_values(
                ["listing_id", "quote_timestamp"],
                ascending=[True, False],
                na_position="last",
                kind="mergesort",
            ).reset_index(drop=True)
    if _text(entity.get("entity_type")).lower() == "private":
        quote_status = "not_applicable"
    elif quote_snapshots.empty:
        quote_status = "unavailable"
    elif "freshness" in quote_snapshots.columns and quote_snapshots["freshness"].eq("stale").all():
        quote_status = "stale"
    elif "freshness" in quote_snapshots.columns and quote_snapshots["freshness"].isin({"stale", "unavailable"}).any():
        quote_status = "degraded"
    else:
        quote_status = "available"

    event_rows: list[dict[str, object]] = []
    question_counts = snapshot.event_watch_questions["event_id"].astype("string").value_counts().to_dict() if not snapshot.event_watch_questions.empty else {}
    event_frame = apply_event_filters(snapshot.events, filters) if filters is not None else snapshot.events
    for _, event in event_frame.iterrows():
        relation = _event_relation(snapshot, event, requested_entity, listing_ids)
        if relation is None:
            continue
        row = {column: event.get(column, pd.NA) for column in COMPANY_EVENT_COLUMNS}
        row["watch_question_count"] = int(question_counts.get(_text(event.get("event_id")), 0))
        row["relation_role"] = relation
        event_rows.append(row)
    events = pd.DataFrame(event_rows, columns=COMPANY_EVENT_COLUMNS) if event_rows else _empty(COMPANY_EVENT_COLUMNS)
    events, superseded_event_ids = _collapse_superseded_event_rows(events)

    documents = snapshot.news_filings.loc[
        snapshot.news_filings.apply(lambda row: _document_matches(snapshot, row, requested_entity, listing_ids, basket_ids), axis=1)
    ].copy() if not snapshot.news_filings.empty else snapshot.news_filings.copy()
    official_documents = documents.loc[:, [column for column in COMPANY_DOCUMENT_COLUMNS if column in documents.columns]].copy() if not documents.empty else _empty(COMPANY_DOCUMENT_COLUMNS)
    for column in COMPANY_DOCUMENT_COLUMNS:
        if column not in official_documents.columns:
            official_documents[column] = pd.NA
    official_documents = official_documents.loc[:, COMPANY_DOCUMENT_COLUMNS]

    consensus = _scope_listing_rows(
        snapshot.consensus_snapshots,
        entity_id=requested_entity,
        scope_listing_id=selected_listing_id,
        include_entity_only=True,
    )
    consensus = consensus.loc[:, [column for column in COMPANY_CONSENSUS_COLUMNS if column in consensus.columns]].copy() if not consensus.empty else _empty(COMPANY_CONSENSUS_COLUMNS)
    for column in COMPANY_CONSENSUS_COLUMNS:
        if column not in consensus.columns:
            consensus[column] = pd.NA
    consensus = consensus.loc[:, COMPANY_CONSENSUS_COLUMNS]

    revisions = _scope_listing_rows(
        snapshot.consensus_revisions,
        entity_id=requested_entity,
        scope_listing_id=selected_listing_id,
        include_entity_only=True,
    )
    revisions = revisions.loc[:, [column for column in COMPANY_REVISION_COLUMNS if column in revisions.columns]].copy() if not revisions.empty else _empty(COMPANY_REVISION_COLUMNS)
    for column in COMPANY_REVISION_COLUMNS:
        if column not in revisions.columns:
            revisions[column] = pd.NA
    revisions = revisions.loc[:, COMPANY_REVISION_COLUMNS]

    # T1: Corporate actions (Statutory share repurchases / dividends)
    corp_actions_source = getattr(snapshot, "corporate_actions", pd.DataFrame())
    if corp_actions_source is not None and not corp_actions_source.empty:
        corp_actions = _scope_listing_rows(
            corp_actions_source,
            entity_id=requested_entity,
            scope_listing_id=selected_listing_id,
            include_entity_only=True,
        )
        if not corp_actions.empty:
            for col in COMPANY_CORPORATE_ACTION_COLUMNS:
                if col not in corp_actions.columns:
                    corp_actions[col] = pd.NA
            corp_actions = corp_actions.loc[:, [col for col in COMPANY_CORPORATE_ACTION_COLUMNS if col in corp_actions.columns]]
            if "execution_date" in corp_actions.columns:
                corp_actions = corp_actions.sort_values("execution_date", ascending=False)
        else:
            corp_actions = _empty(COMPANY_CORPORATE_ACTION_COLUMNS)
    else:
        corp_actions = _empty(COMPANY_CORPORATE_ACTION_COLUMNS)

    # T2: Valuation snapshots (Forward P/E, EV/EBITDA, FCF yield, Cash return yield)
    valuation_source = getattr(snapshot, "valuation_snapshots", pd.DataFrame())
    if valuation_source is not None and not valuation_source.empty:
        val_snapshots = _scope_listing_rows(
            valuation_source,
            entity_id=requested_entity,
            scope_listing_id=selected_listing_id,
            include_entity_only=True,
        )
        if not val_snapshots.empty:
            for col in COMPANY_VALUATION_COLUMNS:
                if col not in val_snapshots.columns:
                    val_snapshots[col] = pd.NA
            val_snapshots = val_snapshots.loc[:, [col for col in COMPANY_VALUATION_COLUMNS if col in val_snapshots.columns]]
        else:
            val_snapshots = _empty(COMPANY_VALUATION_COLUMNS)
    else:
        val_snapshots = _empty(COMPANY_VALUATION_COLUMNS)

    # T2: Internal estimates & management guidance
    internal_est_source = getattr(snapshot, "internal_estimates", pd.DataFrame())
    if internal_est_source is not None and not internal_est_source.empty:
        internal_est = _scope_listing_rows(
            internal_est_source,
            entity_id=requested_entity,
            scope_listing_id=selected_listing_id,
            include_entity_only=True,
        )
        if not internal_est.empty:
            for col in COMPANY_INTERNAL_ESTIMATES_COLUMNS:
                if col not in internal_est.columns:
                    internal_est[col] = pd.NA
            internal_est = internal_est.loc[:, [col for col in COMPANY_INTERNAL_ESTIMATES_COLUMNS if col in internal_est.columns]]
        else:
            internal_est = _empty(COMPANY_INTERNAL_ESTIMATES_COLUMNS)
    else:
        internal_est = _empty(COMPANY_INTERNAL_ESTIMATES_COLUMNS)

    # T3: Thesis claims (Human-authored investment theses)
    thesis_claims_source = getattr(snapshot, "thesis_claims", pd.DataFrame())
    if thesis_claims_source is not None and not thesis_claims_source.empty:
        if "entity_id" in thesis_claims_source.columns:
            thesis_claims = thesis_claims_source.loc[
                thesis_claims_source["entity_id"].astype("string").eq(requested_entity)
            ].copy()
        else:
            thesis_claims = thesis_claims_source.copy()
        if not thesis_claims.empty:
            for col in COMPANY_THESIS_CLAIM_COLUMNS:
                if col not in thesis_claims.columns:
                    thesis_claims[col] = pd.NA
            thesis_claims = thesis_claims.loc[:, [col for col in COMPANY_THESIS_CLAIM_COLUMNS if col in thesis_claims.columns]]
        else:
            thesis_claims = _empty(COMPANY_THESIS_CLAIM_COLUMNS)
    else:
        thesis_claims = _empty(COMPANY_THESIS_CLAIM_COLUMNS)

    # T3: Thesis watch questions
    thesis_questions_source = getattr(snapshot, "thesis_watch_questions", pd.DataFrame())
    if thesis_questions_source is not None and not thesis_questions_source.empty:
        claim_ids = set(thesis_claims["claim_id"].astype("string")) if not thesis_claims.empty else set()
        mask = pd.Series(False, index=thesis_questions_source.index)
        if "entity_id" in thesis_questions_source.columns:
            mask |= thesis_questions_source["entity_id"].astype("string").eq(requested_entity)
        if "claim_id" in thesis_questions_source.columns and claim_ids:
            mask |= thesis_questions_source["claim_id"].astype("string").isin(claim_ids)
        thesis_questions = thesis_questions_source.loc[mask].copy()
        if not thesis_questions.empty:
            for col in COMPANY_THESIS_QUESTION_COLUMNS:
                if col not in thesis_questions.columns:
                    thesis_questions[col] = pd.NA
            thesis_questions = thesis_questions.loc[:, [col for col in COMPANY_THESIS_QUESTION_COLUMNS if col in thesis_questions.columns]]
        else:
            thesis_questions = _empty(COMPANY_THESIS_QUESTION_COLUMNS)
    else:
        thesis_questions = _empty(COMPANY_THESIS_QUESTION_COLUMNS)

    # T3: Evidence items
    evidence_items_source = getattr(snapshot, "evidence_items", pd.DataFrame())
    if evidence_items_source is not None and not evidence_items_source.empty:
        if "entity_id" in evidence_items_source.columns:
            evidence_items = evidence_items_source.loc[
                evidence_items_source["entity_id"].astype("string").eq(requested_entity)
            ].copy()
        else:
            evidence_items = evidence_items_source.copy()
        if not evidence_items.empty:
            for col in COMPANY_EVIDENCE_ITEM_COLUMNS:
                if col not in evidence_items.columns:
                    evidence_items[col] = pd.NA
            evidence_items = evidence_items.loc[:, [col for col in COMPANY_EVIDENCE_ITEM_COLUMNS if col in evidence_items.columns]]
        else:
            evidence_items = _empty(COMPANY_EVIDENCE_ITEM_COLUMNS)
    else:
        evidence_items = _empty(COMPANY_EVIDENCE_ITEM_COLUMNS)

    # T3: Claim evidence links
    claim_links_source = getattr(snapshot, "claim_evidence_links", pd.DataFrame())
    if claim_links_source is not None and not claim_links_source.empty and not thesis_claims.empty:
        claim_ids = set(thesis_claims["claim_id"].astype("string"))
        if "claim_id" in claim_links_source.columns:
            claim_links = claim_links_source.loc[
                claim_links_source["claim_id"].astype("string").isin(claim_ids)
            ].copy()
        else:
            claim_links = claim_links_source.copy()
        if not claim_links.empty:
            for col in COMPANY_CLAIM_EVIDENCE_LINK_COLUMNS:
                if col not in claim_links.columns:
                    claim_links[col] = pd.NA
            claim_links = claim_links.loc[:, [col for col in COMPANY_CLAIM_EVIDENCE_LINK_COLUMNS if col in claim_links.columns]]
        else:
            claim_links = _empty(COMPANY_CLAIM_EVIDENCE_LINK_COLUMNS)
    else:
        claim_links = _empty(COMPANY_CLAIM_EVIDENCE_LINK_COLUMNS)

    if filters is not None and filters.scope and "company" not in filters.scope:
        official_documents = _empty(COMPANY_DOCUMENT_COLUMNS)
        consensus = _empty(COMPANY_CONSENSUS_COLUMNS)
        revisions = _empty(COMPANY_REVISION_COLUMNS)
        corp_actions = _empty(COMPANY_CORPORATE_ACTION_COLUMNS)
        val_snapshots = _empty(COMPANY_VALUATION_COLUMNS)
        internal_est = _empty(COMPANY_INTERNAL_ESTIMATES_COLUMNS)
        thesis_claims = _empty(COMPANY_THESIS_CLAIM_COLUMNS)
        thesis_questions = _empty(COMPANY_THESIS_QUESTION_COLUMNS)
        evidence_items = _empty(COMPANY_EVIDENCE_ITEM_COLUMNS)
        claim_links = _empty(COMPANY_CLAIM_EVIDENCE_LINK_COLUMNS)

    event_ids_for_questions = {
        _text(row.get("event_id"))
        for row in event_rows
        if _text(row.get("event_id"))
    }
    watch_questions = snapshot.event_watch_questions.loc[
        snapshot.event_watch_questions["event_id"].astype("string").isin(event_ids_for_questions)
    ].copy() if not snapshot.event_watch_questions.empty and event_ids_for_questions else _empty(COMPANY_QUESTION_COLUMNS)
    for column in COMPANY_QUESTION_COLUMNS:
        if column not in watch_questions.columns:
            watch_questions[column] = pd.NA
    watch_questions = watch_questions.loc[:, COMPANY_QUESTION_COLUMNS]
    invalidation_evidence = _empty(COMPANY_INVALIDATION_COLUMNS)

    source_ids = _source_relevance(events) | _source_relevance(official_documents)
    source_ids |= _source_relevance(quote_snapshots)
    if not consensus.empty:
        source_ids |= {f"provider:{value}" for value in consensus["provider"].map(_text) if value}
    classified = classify_source_health(snapshot.source_health, now_utc=snapshot.now_utc)
    classified = _provider_source_rows(snapshot, classified, consensus)
    source_ids_lower = {value.casefold() for value in source_ids}
    stable_provider_sources = classified["source_id"].astype("string").str.contains(
        "fnguide|futu|yfinance|akshare|provider:|dart|krx|official|ir|research|hkex",
        case=False,
        regex=True,
        na=False,
    ) if not classified.empty else pd.Series(dtype="boolean")
    if source_ids or not classified.empty:
        source_health = classified.loc[
            classified["source_id"].astype("string").str.casefold().isin(source_ids_lower)
            | stable_provider_sources
        ].copy()
    else:
        source_health = classified.iloc[0:0].copy()
    if official_documents.empty:
        official_row = classify_source_health(
            pd.DataFrame(
                [
                    {
                        "source_id": "official_documents",
                        "input_path": "news_filings.parquet",
                        "source_kind": "official_document_metadata",
                        "status": "unavailable",
                        "required": False,
                        "row_count": 0,
                        "cadence": "irregular",
                        "pit_class": "",
                        "source_license_class": "official_public",
                        "detail": f"no local metadata row for entity={requested_entity}; document body unavailable",
                    }
                ]
            ),
            now_utc=snapshot.now_utc,
        )
        source_health = pd.concat([source_health, official_row], ignore_index=True)

    caveats: list[str] = []
    if selected_listing_id is None:
        caveats.append("no_verified_primary_listing")
    if official_documents.empty:
        caveats.append(
            f"Official documents unavailable — no local { _text(entity.get('display_name')) or requested_entity } metadata export; no document body displayed"
        )
    if consensus.empty:
        caveats.append("Consensus unavailable — no local provider rows for the selected listing; no provider was queried")
        caveats.extend(("FnGuide consensus unavailable — no local export", "Futu consensus unavailable — no local export"))
    if quote_snapshots.empty:
        caveats.append("Latest quote unavailable — no local quote snapshot was loaded; no provider was queried")
    if requested_entity.casefold() == "sk_hynix":
        caveats.extend(("FnGuide consensus unavailable — no local export", "Futu consensus unavailable — no local export"))
    if invalidation_evidence.empty:
        caveats.append("invalidation_evidence_unavailable")
    if superseded_event_ids:
        caveats.append("Superseded event lineage retained: " + ", ".join(superseded_event_ids))
    event_pit = events.get("pit_class", pd.Series("", index=events.index, dtype="string"))
    event_evidence = events.get("evidence_class", pd.Series("", index=events.index, dtype="string"))
    if not events.empty and (event_pit.map(_text).eq("").any() or event_evidence.map(_text).str.contains("internal_research", case=False, na=False).any()):
        caveats.extend(("Internal research evidence is not PIT", "Source link unavailable for internal research rows"))
    if not source_health.empty:
        caveats.extend(_text(value) for value in source_health["detail"] if _text(value))
        pit_values = set(source_health["pit_display"].map(_text))
        if "not_pit" in pit_values:
            caveats.append("not_pit source evidence remains visibly labelled")
        if "PIT unavailable" in pit_values:
            caveats.append("PIT unavailable; no PIT class is inferred")
    caveats = tuple(dict.fromkeys(caveats))
    bad_source_statuses = {
        "failed", "conflicted", "review_required", "entitlement_error",
        "unavailable", "degraded", "partial", "no_records", "stale", "clock_skew",
    }
    relevant_health_ids = set(source_ids)
    if not consensus.empty:
        relevant_health_ids |= {
            f"provider:{value}"
            for value in consensus["provider"].map(_text)
            if value
        }
    relevant_health = source_health.loc[
        source_health["source_id"].astype("string").isin(relevant_health_ids)
    ] if relevant_health_ids and not source_health.empty else source_health.iloc[0:0]
    source_degraded = not relevant_health.empty and bool(set(relevant_health["display_status"]) & bad_source_statuses)
    if consensus.empty:
        consensus_status = "unavailable"
    elif source_degraded:
        consensus_status = "degraded"
    else:
        consensus_status = "available"

    return CompanyView(
        entity_id=requested_entity,
        legal_name=_text(entity.get("legal_name")),
        display_name=_text(entity.get("display_name")) or _text(entity.get("legal_name")) or requested_entity,
        country=_text(entity.get("country")),
        sector=_text(entity.get("sector")),
        industry=_text(entity.get("industry")),
        entity_type=_text(entity.get("entity_type")) or "public",
        active_status=_text(entity.get("active_status")),
        selected_listing_id=selected_listing_id,
        selection_mode=selection_mode,
        listings=listings,
        memberships=memberships,
        quote_snapshots=_newer_local_quotes(quote_snapshots),
        price_bars=price_bars,
        quote_status=quote_status,
        events=events,
        official_documents=official_documents,
        consensus=consensus,
        consensus_revisions=revisions,
        consensus_status=consensus_status,
        source_health=source_health,
        watch_questions=watch_questions,
        invalidation_evidence=invalidation_evidence,
        caveats=caveats,
        corporate_actions=corp_actions,
        valuation_snapshots=val_snapshots,
        internal_estimates=internal_est,
        thesis_claims=thesis_claims,
        thesis_watch_questions=thesis_questions,
        evidence_items=evidence_items,
        claim_evidence_links=claim_links,
    )


def _format_time(value: object, timezone: str) -> str:
    timestamp = _timestamp(value)
    if timestamp is None:
        return "Unavailable"
    try:
        return timestamp.tz_convert(timezone).strftime("%d %b %H:%M %Z")
    except (KeyError, TypeError, ValueError):
        # Unknown zone name (pytz raises a KeyError subclass), or a naive
        # timestamp that cannot be converted. Anything else is a bug here.
        return timestamp.strftime("%d %b %H:%M UTC")


def _filtered_entity_ids(snapshot: ControlTowerSnapshot, filters: EventFilters | None) -> set[str]:
    """Resolve global basket/country/tier filters before rendering the selector."""

    if filters is None:
        return set(snapshot.entities.get("entity_id", pd.Series(dtype="string")).astype("string"))
    entity_ids = set(snapshot.entities.get("entity_id", pd.Series(dtype="string")).astype("string"))
    memberships = snapshot.basket_memberships
    if filters.basket_id or filters.membership_tier:
        if memberships.empty:
            return set()
        rows = memberships.copy()
        if filters.basket_id:
            rows = rows.loc[rows["basket_id"].astype("string").isin(filters.basket_id)]
        if filters.membership_tier:
            rows = rows.loc[rows["membership_tier"].astype("string").str.lower().isin(filters.membership_tier)]
        entity_ids &= set(rows["entity_id"].astype("string"))
    if filters.country and not snapshot.entities.empty:
        entity_ids &= set(
            snapshot.entities.loc[
                snapshot.entities["country"].astype("string").str.upper().isin(filters.country),
                "entity_id",
            ].astype("string")
        )
    return entity_ids


def _friendly_listing_frame(frame: pd.DataFrame) -> pd.DataFrame:
    columns = {
        "exchange": "Exchange",
        "native_ticker": "Ticker",
        "canonical_ticker": "Canonical ticker",
        "currency": "Currency",
        "primary_listing": "Primary",
        "listing_role": "Role",
        "mapping_status": "Mapping",
        "collection_eligible": "Collection eligible",
        "listing_status": "Status",
    }
    available = [column for column in columns if column in frame.columns]
    return frame.loc[:, available].rename(columns={column: columns[column] for column in available})


def _friendly_document_frame(frame: pd.DataFrame, viewer_timezone: str) -> pd.DataFrame:
    columns = {
        "headline": "Headline",
        "publisher": "Publisher",
        "document_type": "Type",
        "published_at": "Published",
        "importance": "Importance",
        "source_quality": "Source quality",
        "source_url": "Source link",
    }
    available = [column for column in columns if column in frame.columns]
    result = frame.loc[:, available].rename(columns={column: columns[column] for column in available}).copy()
    if "Published" in result.columns:
        result["Published"] = result["Published"].map(lambda value: _format_time(value, viewer_timezone))
    return result


def _friendly_consensus_frame(frame: pd.DataFrame, viewer_timezone: str) -> pd.DataFrame:
    columns = {
        "provider": "Provider",
        "canonical_ticker": "Ticker",
        "metric": "Metric",
        "fiscal_period": "Fiscal period",
        "value": "Estimate",
        "statistic": "Statistic",
        "analyst_count": "Analysts",
        "currency": "Currency",
        "unit": "Unit",
        "snapshot_at": "Snapshot",
        "pit_class": "PIT class",
        "source_url": "Source link",
    }
    available = [column for column in columns if column in frame.columns]
    result = frame.loc[:, available].rename(columns={column: columns[column] for column in available}).copy()
    for column in ("Snapshot",):
        if column in result.columns:
            result[column] = result[column].map(lambda value: _format_time(value, viewer_timezone))
    return result


def _friendly_revision_frame(frame: pd.DataFrame, viewer_timezone: str) -> pd.DataFrame:
    columns = {
        "provider": "Provider",
        "canonical_ticker": "Ticker",
        "metric": "Metric",
        "fiscal_period": "Fiscal period",
        "prior_value": "Prior",
        "current_value": "Current",
        "revision_value": "Revision",
        "revision_pct": "Revision %",
        "current_analyst_count": "Analysts",
        "current_snapshot_at": "Snapshot",
        "alignment_status": "Alignment",
        "pit_class": "PIT class",
        "source_url": "Source link",
    }
    available = [column for column in columns if column in frame.columns]
    result = frame.loc[:, available].rename(columns={column: columns[column] for column in available}).copy()
    if "Snapshot" in result.columns:
        result["Snapshot"] = result["Snapshot"].map(lambda value: _format_time(value, viewer_timezone))
    return result


def _friendly_quote_frame(frame: pd.DataFrame, viewer_timezone: str) -> pd.DataFrame:
    columns = {
        "canonical_ticker": "Ticker",
        "provider_symbol": "Provider symbol",
        "last_price": "Last",
        "bid": "Bid",
        "ask": "Ask",
        "day_change_pct": "Day change %",
        "volume": "Volume",
        "currency": "Currency",
        "quote_timestamp": "Quote time",
        "retrieved_at_utc": "Retrieved",
        "freshness": "Freshness",
        "market_status": "Market status",
        "source_id": "Source",
        "source_url": "Source link",
    }
    available = [column for column in columns if column in frame.columns]
    result = frame.loc[:, available].rename(
        columns={column: columns[column] for column in available}
    ).copy()
    for column in ("Quote time", "Retrieved"):
        if column in result.columns:
            result[column] = result[column].map(
                lambda value: _format_time(value, viewer_timezone)
            )
    return result


def _friendly_question_frame(frame: pd.DataFrame) -> pd.DataFrame:
    columns = {
        "question": "Question",
        "question_type": "Type",
        "priority": "Priority",
    }
    available = [column for column in columns if column in frame.columns]
    return frame.loc[:, available].rename(columns={column: columns[column] for column in available})


def _friendly_invalidation_frame(frame: pd.DataFrame, viewer_timezone: str) -> pd.DataFrame:
    columns = {
        "title": "Evidence",
        "detail": "Detail",
        "observed_at": "Observed",
        "status": "Status",
        "evidence_class": "Evidence class",
        "source_url": "Source link",
    }
    available = [column for column in columns if column in frame.columns]
    result = frame.loc[:, available].rename(columns={column: columns[column] for column in available}).copy()
    if "Observed" in result.columns:
        result["Observed"] = result["Observed"].map(lambda value: _format_time(value, viewer_timezone))
    return result


def _friendly_corporate_actions_frame(frame: pd.DataFrame, viewer_timezone: str) -> pd.DataFrame:
    columns = {
        "execution_date": "Execution date",
        "filing_date": "Filing date",
        "action_type": "Action type",
        "shares_affected": "Shares affected",
        "price_min": "Price min",
        "price_max": "Price max",
        "price_avg": "Price avg",
        "total_amount_paid": "Total consideration",
        "currency": "Currency",
        "pit_class": "PIT class",
        "source_url": "Source link",
    }
    available = [col for col in columns if col in frame.columns]
    return frame.loc[:, available].rename(columns={col: columns[col] for col in available}).copy()


def _friendly_valuation_frame(frame: pd.DataFrame) -> pd.DataFrame:
    columns = {
        "metric_name": "Metric",
        "metric_basis": "Basis",
        "ratio_value": "Multiple / Yield",
        "numerator_value": "Numerator",
        "numerator_currency": "Num ccy",
        "numerator_ref": "Numerator ref",
        "denominator_value": "Denominator",
        "denominator_currency": "Den ccy",
        "denominator_ref": "Denominator ref",
        "fx_rate_applied": "FX rate",
        "fx_source": "FX source",
        "pit_class": "PIT class",
        "percentile_history_status": "History percentile",
    }
    available = [col for col in columns if col in frame.columns]
    return frame.loc[:, available].rename(columns={col: columns[col] for col in available}).copy()


def _friendly_internal_estimates_frame(frame: pd.DataFrame, viewer_timezone: str) -> pd.DataFrame:
    columns = {
        "observation_type": "Observation type",
        "author": "Author",
        "metric": "Metric",
        "accounting_basis": "Accounting basis",
        "metric_basis": "Metric basis",
        "fiscal_period": "Fiscal period",
        "fiscal_year": "Fiscal year",
        "value_low": "Low",
        "value_mid": "Mid",
        "value_high": "High",
        "currency": "Currency",
        "unit": "Unit",
        "effective_asof": "Effective as-of",
        "rationale_notes": "Rationale / Notes",
        "source_ref": "Source ref",
        "pit_class": "PIT class",
    }
    available = [col for col in columns if col in frame.columns]
    return frame.loc[:, available].rename(columns={col: columns[col] for col in available}).copy()


def _friendly_thesis_questions_frame(frame: pd.DataFrame) -> pd.DataFrame:
    columns = {
        "question": "Question",
        "question_type": "Type",
        "priority": "Priority",
        "claim_id": "Claim ID",
    }
    available = [col for col in columns if col in frame.columns]
    return frame.loc[:, available].rename(columns={col: columns[col] for col in available})


def _friendly_claim_evidence_links_frame(
    links_frame: pd.DataFrame,
    evidence_frame: pd.DataFrame,
    viewer_timezone: str,
) -> pd.DataFrame:
    if links_frame.empty:
        return pd.DataFrame()
    if not evidence_frame.empty and "evidence_id" in links_frame.columns and "evidence_id" in evidence_frame.columns:
        merged = links_frame.merge(evidence_frame, on="evidence_id", how="left", suffixes=("", "_ev"))
    else:
        merged = links_frame.copy()
    columns = {
        "evidence_id": "Evidence ID",
        "claim_id": "Claim ID",
        "source_type": "Source type",
        "summary_text": "Summary",
        "conflict_hint": "Conflict hint",
        "review_state": "Review state",
        "analyst_note": "Analyst note",
        "published_at": "Published",
        "source_url": "Source link",
        "pit_class": "PIT class",
        "evidence_class": "Evidence class",
    }
    available = [col for col in columns if col in merged.columns]
    result = merged.loc[:, available].rename(columns={col: columns[col] for col in available}).copy()
    if "Published" in result.columns:
        result["Published"] = result["Published"].map(lambda v: _format_time(v, viewer_timezone))
    return result


def _friendly_caveat(value: object) -> str:
    text = _text(value)
    exact = {
        "no_verified_primary_listing": "No verified primary listing is registered for this entity.",
        "invalidation_evidence_unavailable": "No invalidation evidence is available in the current bundle.",
        "Internal research evidence is not PIT": "Internal research evidence is not point-in-time.",
        "Source link unavailable for internal research rows": "Some internal research rows do not have a source link.",
        "not_pit source evidence remains visibly labelled": "Some evidence is explicitly marked as non-point-in-time.",
        "PIT unavailable; no PIT class is inferred": "Point-in-time classification is unavailable for one or more sources.",
    }
    if text in exact:
        return exact[text]
    if text.startswith("Official documents unavailable"):
        return "Official filing metadata is unavailable for this entity in the current bundle."
    if text.startswith("Consensus unavailable"):
        return "Consensus data is unavailable for this listing; no provider estimates were blended."
    if text.startswith("Latest quote unavailable"):
        return "Latest quote data is unavailable; no provider was queried by the dashboard."
    if text.startswith("Superseded event lineage retained:"):
        return "Superseded event lineage is retained in the detail view for audit."
    return text.replace("_", " ").strip().capitalize()


def _format_listing_option(snapshot: ControlTowerSnapshot, listing_id: str | None) -> str:
    if listing_id is None:
        return "All active listings"
    row = snapshot.listings.loc[
        snapshot.listings["listing_id"].astype("string").eq(listing_id)
    ] if not snapshot.listings.empty else snapshot.listings
    if row.empty:
        return "Listing unavailable"
    listing = row.iloc[0]
    ticker = _text(listing.get("canonical_ticker")) or _text(listing.get("native_ticker"))
    exchange = _text(listing.get("exchange"))
    currency = _text(listing.get("currency"))
    return " · ".join(value for value in (ticker, exchange, currency) if value) or "Listing unavailable"



def _latest_reported_kpi(frame: pd.DataFrame, metrics: tuple[str, ...]) -> tuple[float | None, str]:
    """Pick a display KPI from official actuals without inventing a period."""

    if frame is None or frame.empty or 'metric' not in frame.columns:
        return None, 'unavailable'
    work = frame.copy()
    work['metric'] = work['metric'].astype('string')
    work = work.loc[work['metric'].isin(list(metrics))].copy()
    if work.empty:
        return None, 'unavailable'
    work['period_end'] = pd.to_datetime(work.get('period_end'), errors='coerce')
    work = work.dropna(subset=['period_end', 'reported_value'])
    if work.empty:
        return None, 'unavailable'
    work['period_label'] = work.get('period_label', pd.Series('', index=work.index)).astype('string')
    quarterly = work.loc[work['period_label'].str.match(r'^([1-4]Q|Q[1-4]|1H)', na=False)]
    if len(quarterly['period_label'].dropna().unique()) >= 4:
        latest = quarterly.sort_values('period_end').drop_duplicates(['period_label', 'metric'], keep='last')
        labels = latest['period_label'].drop_duplicates().tail(4)
        subset = latest.loc[latest['period_label'].isin(labels)]
        return float(subset['reported_value'].sum()), 'sum of latest disclosed quarters'
    annual = work.loc[work['period_label'].str.startswith('FY', na=False)]
    source = annual if not annual.empty else work
    row = source.sort_values('period_end').drop_duplicates(['period_label', 'metric'], keep='last').iloc[-1]
    label = str(row.get('period_label') or 'latest period')
    return float(row['reported_value']), f'{label} official'

def _company_earnings_actuals(
    snapshot: ControlTowerSnapshot,
    view: CompanyView,
) -> pd.DataFrame:
    """Return earnings rows for the selected issuer.

    Official actuals are issuer-level. A Hong Kong ordinary share should still
    see SEC companyfacts filed against the ADR listing of the same entity;
    filtering only on the selected listing hid Alibaba/Baidu annuals.
    """

    source = getattr(snapshot, "earnings_actuals", pd.DataFrame())
    if source is None or source.empty or "entity_id" not in source.columns:
        return pd.DataFrame()
    return source.loc[source["entity_id"].astype("string").eq(view.entity_id)].copy()


def _latest_actual_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Select the latest reported period without inventing a period fallback."""

    if frame.empty:
        return frame.copy()
    latest = frame.copy()
    if "period_end" in latest.columns:
        period_end = pd.to_datetime(latest["period_end"], errors="coerce")
        if period_end.notna().any():
            latest = latest.loc[period_end.eq(period_end.max())].copy()
    sort_columns = [
        column
        for column in ("filing_at", "version", "metric", "accounting_basis")
        if column in latest.columns
    ]
    if sort_columns:
        latest = latest.sort_values(sort_columns, ascending=False, na_position="last")
    dedupe_columns = [
        column for column in ("metric", "accounting_basis") if column in latest.columns
    ]
    if dedupe_columns:
        latest = latest.drop_duplicates(dedupe_columns, keep="first")
    return latest


def _format_number(value: object, *, decimals: int = 2) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if pd.isna(number):
        return ""
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.{decimals}f}".rstrip("0").rstrip(".")


def _format_actual_value(row: Any) -> str:
    value = row.get("reported_value")
    if not _text(value):
        value = row.get("normalized_value")
    number = _format_number(value)
    if not number:
        return "value unavailable"
    currency = _text(row.get("currency"))
    unit = _text(row.get("unit"))
    if unit.casefold() in {"percent", "percentage", "%"}:
        return f"{number}%"
    components = [currency, number]
    if unit and unit.casefold() != currency.casefold():
        components.append(unit)
    return " ".join(component for component in components if component)


def _summary_date(value: object) -> str:
    parsed = _date(value)
    return parsed.strftime("%Y-%m-%d") if parsed is not None else ""


def _summary_source(row: Any) -> str:
    source_id = _text(row.get("source_id")) or _text(row.get("provider"))
    source_url = _text(row.get("source_url"))
    if source_id and source_url:
        return f"{source_id} · {source_url}"
    if source_id:
        return source_id
    if source_url:
        return source_url
    return "provenance unavailable"


def _answer_first_summary_lines(
    view: CompanyView,
    snapshot: ControlTowerSnapshot,
) -> tuple[str, ...]:
    """Build compact answer-first facts exclusively from selected snapshot rows."""

    lines: list[str] = []

    actuals = _latest_actual_rows(_company_earnings_actuals(snapshot, view))
    if actuals.empty:
        lines.append("Latest fundamentals unavailable · no earnings-actuals rows for this entity/listing.")
    else:
        priorities = {
            "revenue_total": 0,
            "operating_profit": 1,
            "net_profit_attributable": 2,
            "free_cash_flow": 3,
            "capital_expenditure": 4,
        }
        ordered = actuals.assign(
            _summary_priority=actuals.get(
                "metric", pd.Series("", index=actuals.index, dtype="string")
            ).map(lambda value: priorities.get(_text(value), len(priorities)))
        ).sort_values(["_summary_priority", "metric"], na_position="last")
        facts: list[str] = []
        for _, row in ordered.head(4).iterrows():
            metric = _text(row.get("metric")).replace("_", " ").strip().title()
            basis = _text(row.get("accounting_basis"))
            fact = f"{metric or 'Metric unavailable'}: {_format_actual_value(row)}"
            if basis:
                fact += f" ({basis})"
            facts.append(fact)
        representative = ordered.iloc[0]
        period = _text(representative.get("period_label")) or _summary_date(
            representative.get("period_end")
        )
        filed = _summary_date(representative.get("filing_at"))
        context = " · ".join(
            value for value in (period, f"filed {filed}" if filed else "") if value
        )
        lines.append(
            f"Latest fundamentals · {context or 'period unavailable'} · "
            f"{'; '.join(facts)} · source: {_summary_source(representative)}"
        )

    if view.corporate_actions.empty:
        lines.append("Recent corporate action unavailable · no selected-listing rows.")
    else:
        actions = view.corporate_actions.copy()
        sort_column = next(
            (
                column
                for column in ("execution_date", "filing_date", "retrieved_at_utc")
                if column in actions.columns and actions[column].notna().any()
            ),
            None,
        )
        if sort_column:
            actions = actions.sort_values(sort_column, ascending=False, na_position="last")
        action = actions.iloc[0]
        action_type = _text(action.get("action_type")).replace("_", " ").strip().title()
        action_date = _summary_date(action.get("execution_date"))
        if not action_date:
            action_date = _summary_date(action.get("filing_date"))
        shares = _format_number(action.get("shares_affected"), decimals=0)
        amount = _format_number(action.get("total_amount_paid"))
        currency = _text(action.get("currency"))
        details = [
            action_type or "Action type unavailable",
            action_date or "date unavailable",
        ]
        if shares:
            details.append(f"{shares} shares")
        if amount:
            details.append(" ".join(value for value in (currency, amount) if value))
        lines.append(
            f"Recent corporate action · {' · '.join(details)} · "
            f"source: {_summary_source(action)}"
        )

    if view.consensus.empty:
        lines.append("Expectation context unavailable · no provider consensus rows.")
    else:
        consensus = view.consensus.copy()
        if "snapshot_at" in consensus.columns and consensus["snapshot_at"].notna().any():
            consensus = consensus.sort_values("snapshot_at", ascending=False, na_position="last")
        row = consensus.iloc[0]
        metric = _text(row.get("metric")).replace("_", " ").strip().title()
        value = _format_number(row.get("value"))
        currency = _text(row.get("currency"))
        unit = _text(row.get("unit"))
        estimate = " ".join(part for part in (currency, value, unit) if part)
        lines.append(
            f"Expectation context · {metric or 'metric unavailable'}: "
            f"{estimate or 'value unavailable'} · "
            f"{_text(row.get('horizon')) or 'horizon unavailable'} · "
            f"source: {_summary_source(row)}"
        )

    if view.valuation_snapshots.empty:
        lines.append("Valuation context unavailable · no selected-listing valuation rows.")
    else:
        valuations = view.valuation_snapshots.copy()
        sort_column = next(
            (
                column
                for column in ("valuation_at", "valuation_date", "retrieved_at_utc")
                if column in valuations.columns and valuations[column].notna().any()
            ),
            None,
        )
        if sort_column:
            valuations = valuations.sort_values(sort_column, ascending=False, na_position="last")
        latest_date = _summary_date(valuations.iloc[0].get("valuation_at"))
        if not latest_date:
            latest_date = _summary_date(valuations.iloc[0].get("valuation_date"))
        facts = []
        for _, row in valuations.head(3).iterrows():
            metric = _text(row.get("metric_name")).replace("_", " ").strip().title()
            ratio = _format_number(row.get("ratio_value"))
            basis = _text(row.get("metric_basis"))
            fact = f"{metric or 'Metric unavailable'}: {ratio or 'value unavailable'}"
            if basis:
                fact += f" ({basis})"
            facts.append(fact)
        lines.append(
            f"Valuation context · {latest_date or 'date unavailable'} · "
            f"{'; '.join(facts)} · source: {_summary_source(valuations.iloc[0])}"
        )

    event = select_next_catalyst(view.events, snapshot.now_utc)
    if event is None:
        lines.append("Upcoming catalyst unavailable · no future linked event rows.")
    else:
        start = pd.to_datetime(event.get("starts_at"), errors="coerce", utc=True)
        end = pd.to_datetime(event.get("ends_at"), errors="coerce", utc=True)
        if pd.isna(start):
            start = None
        if pd.isna(end):
            end = start
        precision = _text(event.get("date_precision")) or "day"
        window_label = format_event_window(start, end, precision, "UTC")
        is_active = is_active_catalyst(event.get("starts_at"), event.get("ends_at"), snapshot.now_utc)
        catalyst_prefix = "Active catalyst" if is_active else "Upcoming catalyst"
        lines.append(
            f"{catalyst_prefix} · {_text(event.get('title')) or 'title unavailable'} · "
            f"{window_label or 'date unavailable'} · "
            f"{_text(event.get('certainty_class')).replace('_', ' ') or 'certainty unavailable'} · "
            f"{precision or 'precision unavailable'} · "
            f"source: {_summary_source(event)}"
        )

    if view.thesis_claims.empty:
        lines.append("Thesis registry unavailable · no thesis-claim rows.")
    else:
        statuses = (
            view.thesis_claims.get(
                "status", pd.Series("", index=view.thesis_claims.index, dtype="string")
            )
            .map(lambda value: _text(value).lower() or "status unavailable")
            .value_counts()
        )
        status_text = ", ".join(
            f"{status}: {int(count)}" for status, count in sorted(statuses.items())
        )
        lines.append(
            f"Thesis registry · {len(view.thesis_claims)} claim rows · "
            f"{status_text or 'status unavailable'}."
        )

    if view.evidence_items.empty:
        lines.append("Evidence lineage unavailable · no evidence-item rows.")
    else:
        evidence = view.evidence_items.copy()
        if "published_at" in evidence.columns and evidence["published_at"].notna().any():
            evidence = evidence.sort_values("published_at", ascending=False, na_position="last")
        row = evidence.iloc[0]
        lines.append(
            f"Evidence lineage · {len(evidence)} evidence rows · "
            f"latest class: {_text(row.get('evidence_class')) or 'unavailable'} · "
            f"published: {_summary_date(row.get('published_at')) or 'unavailable'} · "
            f"source: {_summary_source(row)}"
        )

    return tuple(lines)


def _render_company_hero_card(
    view: CompanyView,
    snapshot: ControlTowerSnapshot,
    viewer_timezone: str,
) -> None:
    ticker = ''
    exchange = ''
    currency = ''
    if view.selected_listing_id and not view.listings.empty:
        selected = view.listings.loc[
            view.listings['listing_id'].astype('string').eq(view.selected_listing_id)
        ]
        if not selected.empty:
            ticker = _text(selected.iloc[0].get('canonical_ticker')) or _text(selected.iloc[0].get('native_ticker'))
            exchange = _text(selected.iloc[0].get('exchange'))
            currency = _text(selected.iloc[0].get('currency'))

    price_html = ''
    if not view.quote_snapshots.empty and view.entity_type != 'private':
        qrow = view.quote_snapshots.iloc[0]
        last_price = qrow.get('last_price')
        qccy = _text(qrow.get('currency')) or currency or 'HKD'
        price_val_str = f'{qccy} {last_price:,.2f}'.strip() if pd.notna(last_price) else ''
        day_change = qrow.get('day_change_pct')
        if pd.notna(day_change) and isinstance(day_change, (int, float)):
            change_class = 'ct-hero-change--up' if day_change >= 0 else 'ct-hero-change--down'
            change_str = f'{day_change:+.2f}%'
        else:
            change_class = ''
            change_str = ''
        qtime = qrow.get('quote_timestamp')
        age_str = format_quote_age(qtime, snapshot.now_utc)
        freshness = _text(qrow.get('freshness')) or 'delayed'
        if price_val_str:
            change_badge = f'<span class="ct-hero-change {change_class}">{escape(change_str)}</span>' if change_str else ''
            price_html = f'<div class="ct-hero-price-box"><div class="ct-hero-price">{escape(price_val_str)}</div>{change_badge}<div class="ct-subtle" style="font-size: 0.76rem; margin-left: 0.2rem;">{escape(freshness)} ({escape(age_str)})</div></div>'

    actuals = _company_earnings_actuals(snapshot, view)
    ltm_rev_str = 'Unavailable'
    ltm_profit_str = 'Unavailable'
    ltm_fcf_str = 'Unavailable'
    buyback_str = 'Unavailable'
    ltm_rev_sub = 'Official issuer actuals'
    ltm_profit_sub = 'Official issuer actuals'
    if not actuals.empty:
        rev_val, rev_note = _latest_reported_kpi(actuals, ('revenue_total', 'revenue'))
        if rev_val is not None:
            ltm_rev_str = f'¥{rev_val/1e9:,.1f}B' if abs(rev_val) >= 1e9 else f'¥{rev_val:,.0f}'
            ltm_rev_sub = rev_note
        profit_val, profit_note = _latest_reported_kpi(actuals, ('net_profit_attributable', 'net_income'))
        if profit_val is not None:
            ltm_profit_str = f'¥{profit_val/1e9:,.1f}B' if abs(profit_val) >= 1e9 else f'¥{profit_val:,.0f}'
            ltm_profit_sub = profit_note
        fcf_val, fcf_note = _latest_reported_kpi(actuals, ('free_cash_flow',))
        if fcf_val is not None:
            ltm_fcf_str = f'¥{fcf_val/1e9:,.1f}B' if abs(fcf_val) >= 1e9 else f'¥{fcf_val:,.0f}'

    if not view.corporate_actions.empty:
        tot_bb = view.corporate_actions['total_amount_paid'].dropna().sum()
        if tot_bb > 0:
            buyback_str = f'HK$ {tot_bb/1e9:,.1f}B YTD'

    ticker_badge = f'<span class="ct-hero-ticker">{escape(ticker)}</span>' if ticker else ''
    profile = get_company_profile(view.entity_id)
    listing_role = ''
    if view.selected_listing_id and not view.listings.empty:
        selected_role = view.listings.loc[
            view.listings['listing_id'].astype('string').eq(view.selected_listing_id)
        ]
        if not selected_role.empty:
            listing_role = _text(selected_role.iloc[0].get('listing_role')).replace('_', ' ')
    role_suffix = f' · {listing_role}' if listing_role else ''
    exchange_badge = f'<span class="ct-badge">{escape(exchange)}{escape(role_suffix)}</span>' if exchange else ''
    sector_badge = f'<span class="ct-badge">{escape(view.sector)}</span>' if view.sector else ''
    industry_badge = f'<span class="ct-badge">{escape(view.industry)}</span>' if view.industry else ''
    buyback_sub = 'Selected-listing statutory filings'
    hero_html = f'<div class="ct-hero-card"><div class="ct-hero-top"><div><div class="ct-hero-title">{escape(view.display_name)} {ticker_badge} {exchange_badge}</div><div class="ct-subtle" style="margin-top: 0.25rem;">{escape(view.legal_name)} · {escape(view.country)} {sector_badge} {industry_badge}</div></div>{price_html}</div><div class="ct-kpi-grid"><div class="ct-kpi-card"><div class="ct-kpi-label">Latest Revenue</div><div class="ct-kpi-value">{escape(ltm_rev_str)}</div><div class="ct-kpi-sub">{escape(ltm_rev_sub)}</div></div><div class="ct-kpi-card"><div class="ct-kpi-label">Latest Net Profit</div><div class="ct-kpi-value">{escape(ltm_profit_str)}</div><div class="ct-kpi-sub">{escape(ltm_profit_sub)}</div></div><div class="ct-kpi-card"><div class="ct-kpi-label">Free Cash Flow</div><div class="ct-kpi-value">{escape(ltm_fcf_str)}</div><div class="ct-kpi-sub">Latest Reported Period</div></div><div class="ct-kpi-card"><div class="ct-kpi-label">Capital Return / Buybacks</div><div class="ct-kpi-value">{escape(buyback_str)}</div><div class="ct-kpi-sub">{escape(buyback_sub)}</div></div></div></div>'
    st.markdown(hero_html, unsafe_allow_html=True)
    if actuals.empty:
        st.caption('Official LTM cards stay unavailable when issuer actuals are absent. A labelled yfinance/akshare overlay, if present, is on Fundamentals and is not written into these KPIs.')


def _render_styled_bullet_card(line: str) -> None:
    if line.startswith("Latest fundamentals ·"):
        icon = "📊"
        label = "Fundamentals"
        badge_style = "color: var(--ct-accent); border-color: var(--ct-accent);"
    elif line.startswith("Recent corporate action ·"):
        icon = "🏛️"
        label = "Capital Return"
        badge_style = "color: var(--ct-hard); border-color: var(--ct-hard);"
    elif line.startswith("Expectation context ·"):
        icon = "🎯"
        label = "Consensus"
        badge_style = "color: var(--ct-provisional); border-color: var(--ct-provisional);"
    elif line.startswith("Active catalyst ·"):
        icon = "⚡"
        label = "Catalyst"
        badge_style = "color: var(--ct-thesis); border-color: var(--ct-thesis);"
    elif line.startswith("Thesis registry ·"):
        icon = "💡"
        label = "Thesis"
        badge_style = "color: var(--ct-accent); border-color: var(--ct-accent);"
    elif line.startswith("Evidence lineage ·"):
        icon = "🔍"
        label = "Evidence Lineage"
        badge_style = "color: var(--ct-observed); border-color: var(--ct-observed);"
    else:
        icon = "ℹ️"
        label = "Fact"
        badge_style = "color: var(--ct-muted); border-color: var(--ct-border);"
    clean_line = line
    source_link_html = ""
    url_match = re.search(r'https?://[^\s]+', line)
    if url_match:
        url = url_match.group(0)
        clean_line = line.replace(url, "").strip(" ·").strip()
        source_link_html = f' · <a class="ct-inline-link" href="{escape(url)}" target="_blank" rel="noopener">Official Source ↗</a>'
    card_html = f'<div class="ct-change" style="padding: 0.6rem 0.85rem; background: var(--ct-surface); border-radius: 9px; margin-bottom: 0.5rem; border: 1px solid var(--ct-border);"><div style="display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 0.25rem;"><span class="ct-badge" style="{badge_style}; padding: 0.12rem 0.45rem; font-size: 0.72rem; font-weight: 750;">{icon} {escape(label)}</span></div><div style="font-size: 0.86rem; line-height: 1.45; color: var(--ct-ink);">{escape(clean_line)}{source_link_html}</div></div>'
    st.markdown(card_html, unsafe_allow_html=True)

def _render_answer_first_summary(
    view: CompanyView,
    snapshot: ControlTowerSnapshot,
) -> None:
    listing_label = ''
    if view.selected_listing_id and not view.listings.empty:
        selected = view.listings.loc[
            view.listings['listing_id'].astype('string').eq(view.selected_listing_id)
        ]
        if not selected.empty:
            listing_label = _text(selected.iloc[0].get('canonical_ticker'))
    heading = ' · '.join(
        value
        for value in ('Executive summary & recent changes', view.display_name, listing_label)
        if value
    )
    entity_slug = _slugify(view.entity_id)
    listing_slug = _slugify(view.selected_listing_id) if view.selected_listing_id else 'all'
    _render_section_heading(4, heading, f'exec-summary-{entity_slug}-{listing_slug}')
    summary_facts = _answer_first_summary_lines(view, snapshot)
    for line in summary_facts:
        _render_styled_bullet_card(line)
    st.caption('All displayed facts come from the selected local snapshot rows; unavailable marts stay unavailable.')


def _render_price_history(view: CompanyView, snapshot: ControlTowerSnapshot) -> None:
    _render_section_heading(4, 'Price history', f'price-history-{_slugify(view.entity_id)}')
    if view.entity_type == 'private':
        st.info(f'Not applicable · {_text(view.display_name)} is a private company with no public listing; no price history is collected.')
        return
    bars = view.price_bars
    if bars is None or bars.empty:
        st.warning('Price history unavailable · no price-bar rows for the selected listing; the app remains no-network/read-only and did not query a provider.')
        return
    frame = bars.copy()
    frame['bar_date'] = pd.to_datetime(frame['bar_date'], errors='coerce')
    frame = frame.loc[frame['bar_date'].notna()]
    adjusted = frame['adj_close'].notna().any() if 'adj_close' in frame.columns else False
    series_column = 'adj_close' if adjusted else 'close'
    basis = 'adjusted close' if adjusted else 'unadjusted close'
    frame = frame.loc[frame[series_column].notna()]
    if frame.empty:
        st.warning('Price history unavailable · rows carry no usable close price.')
        return
    currency = _text(frame.iloc[-1].get('currency')) or ''
    chart = frame.set_index('bar_date')[[series_column]].rename(columns={series_column: f'{currency} {basis}'.strip()})
    _render_plotly(_plotly_line_chart(chart, y_title=f'{currency} {basis}'.strip(), value_format=',.2f', height=280))
    first = frame['bar_date'].min().date()
    last = frame['bar_date'].max().date()
    sources = ', '.join(sorted({_text(v) for v in frame['source_id'] if _text(v)}))
    span_days = (last - first).days
    st.caption(f'{len(frame):,} daily bars · {first} to {last} ({span_days} calendar days) · {basis} · source: {sources or "unattributed"} · read from the published artifact, no provider was queried')


def _render_overview_tab(
    view: CompanyView,
    snapshot: ControlTowerSnapshot,
    viewer_timezone: str,
) -> None:
    _render_answer_first_summary(view, snapshot)
    _render_section_heading(4, 'Latest market quote', f'latest-quote-{_slugify(view.entity_id)}')
    if view.entity_type == 'private':
        st.info(f'Not applicable · {_text(view.display_name)} is a private company with no public market listing; price, quote, and market data collection are excluded.')
    elif view.quote_snapshots.empty:
        st.warning('Latest quote unavailable · no quote snapshot artifact or selected-listing row; the app remains no-network/read-only and did not query a provider.')
    else:
        for _, qrow in view.quote_snapshots.iterrows():
            last_price = qrow.get('last_price')
            currency = _text(qrow.get('currency')) or ''
            price_str = f'{currency} {last_price:,.2f}'.strip() if pd.notna(last_price) else 'Unavailable'
            day_change = qrow.get('day_change_pct')
            if pd.notna(day_change) and isinstance(day_change, (int, float)):
                change_str = f'{day_change:+.2f}%'
            else:
                change_str = 'Day change unavailable'
            qtime = qrow.get('quote_timestamp')
            age_str = format_quote_age(qtime, snapshot.now_utc)
            freshness = _text(qrow.get('freshness')) or 'delayed'
            latency = _text(qrow.get('latency_class')) or 'delayed'
            source_id = _text(qrow.get('source_id')) or 'market:yfinance'
            source_url = _text(qrow.get('source_url'))
            source_label = f'{source_id} ({latency})'
            if source_url.startswith(('http://', 'https://')):
                source_link_html = f'<a class="ct-inline-link" href="{escape(source_url)}" target="_blank" rel="noopener">{escape(source_label)}</a>'
            else:
                source_link_html = escape(source_label)
            summary_html = f'<div class="ct-change" style="margin-bottom: 0.75rem;"><div class="ct-change-title"><strong>{escape(price_str)}</strong> · {escape(change_str)}</div><div class="ct-change-detail">Quote age: {escape(age_str)} · Freshness: {escape(freshness)}</div><div class="ct-source-line">Source: {source_link_html} · Delayed market data (no real-time claim)</div></div>'
            st.markdown(summary_html, unsafe_allow_html=True)
        ct_dataframe(_friendly_quote_frame(view.quote_snapshots, viewer_timezone), width='stretch', hide_index=True)
    _render_price_history(view, snapshot)
    _render_section_heading(4, 'Listings', f'listings-{_slugify(view.entity_id)}')
    ct_dataframe(_friendly_listing_frame(view.listings), width='stretch', hide_index=True)
    _render_section_heading(4, 'Basket and layer memberships', f'memberships-{_slugify(view.entity_id)}')
    ct_dataframe(view.memberships, width='stretch', hide_index=True)
    _render_section_heading(4, 'Flight deck & catalyst overview', f'flight-deck-{_slugify(view.entity_id)}')
    cols = st.columns(4)
    cols[0].metric('Linked Events', str(len(view.events)))
    cols[1].metric('Thesis Claims', str(len(view.thesis_claims)))
    cols[2].metric('Watch Questions', str(len(view.thesis_watch_questions) if not view.thesis_watch_questions.empty else len(view.watch_questions)))
    cols[3].metric('Corporate Actions', str(len(view.corporate_actions)))


def _build_quarterly_financial_pivot(frame: pd.DataFrame, n_periods: int = 8, profile=None) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    df = frame.copy()
    df['period_end'] = pd.to_datetime(df['period_end'], errors='coerce')
    period_map = df[['period_label', 'period_end']].dropna().drop_duplicates().sort_values('period_end')
    if period_map.empty:
        return pd.DataFrame()
    all_periods = period_map['period_label'].tolist()
    recent_periods = period_map.tail(n_periods)['period_label'].tolist()
    tot_rev = {}
    non_ifrs_op = {}
    non_ifrs_np = {}
    for p in all_periods:
        sub_rev = df[(df['period_label'] == p) & (df['metric'] == 'revenue_total') & (df['accounting_basis'] == 'IFRS')]
        tot_rev[p] = float(sub_rev.iloc[0]['reported_value']) if not sub_rev.empty and pd.notna(sub_rev.iloc[0]['reported_value']) else None
        sub_op = df[(df['period_label'] == p) & (df['metric'] == 'operating_profit') & (df['accounting_basis'] == 'Non-IFRS management measure')]
        non_ifrs_op[p] = float(sub_op.iloc[0]['reported_value']) if not sub_op.empty and pd.notna(sub_op.iloc[0]['reported_value']) else None
        sub_np = df[(df['period_label'] == p) & (df['metric'] == 'net_profit_attributable') & (df['accounting_basis'] == 'Non-IFRS management measure')]
        non_ifrs_np[p] = float(sub_np.iloc[0]['reported_value']) if not sub_np.empty and pd.notna(sub_np.iloc[0]['reported_value']) else None
    profile = profile or get_company_profile(None)
    symbol = profile.reporting_currency_symbol or '¥'
    present_metrics = set(df.get('metric', pd.Series(dtype='string')).astype('string'))
    segment_rows = []
    seen_labels = set()
    preferred = list(profile.segment_metrics) if profile.segment_metrics else []
    if not preferred:
        extra = sorted(
            metric for metric in present_metrics
            if str(metric).startswith('revenue_') and str(metric) != 'revenue_total'
        )
        preferred = [SegmentSpec(metric, segment_label(metric, profile)) for metric in extra]
    for spec in preferred:
        if spec.metric not in present_metrics or spec.label in seen_labels:
            continue
        seen_labels.add(spec.label)
        segment_rows.append((spec.metric, spec.label))
    formatted_segments = []
    for idx, (metric, label) in enumerate(segment_rows):
        prefix = '  └─ ' if idx == len(segment_rows) - 1 else '  ├─ '
        formatted_segments.append((f'{prefix}{label}', metric, 'IFRS', 1e9, symbol + '{:.1f}B'))
    row_specs = [
        (f'Revenue: Total ({profile.reporting_currency} B)', 'revenue_total', 'IFRS', 1e9, symbol + '{:.1f}B'),
        *formatted_segments,
        ('YoY Revenue Growth (%)', '__yoy_rev__', '', 1.0, '{:+.1f}%'),
        ('QoQ Revenue Growth (%)', '__qoq_rev__', '', 1.0, '{:+.1f}%'),
        (f'Operating Profit (Non-IFRS, {profile.reporting_currency} B)', 'operating_profit', 'Non-IFRS management measure', 1e9, symbol + '{:.1f}B'),
        ('Non-IFRS Operating Margin (%)', '__non_ifrs_op_margin__', '', 1.0, '{:.1f}%'),
        (f'Operating Profit (IFRS, {profile.reporting_currency} B)', 'operating_profit', 'IFRS', 1e9, symbol + '{:.1f}B'),
        (f'Net Profit (Non-IFRS, {profile.reporting_currency} B)', 'net_profit_attributable', 'Non-IFRS management measure', 1e9, symbol + '{:.1f}B'),
        ('Non-IFRS Net Margin (%)', '__non_ifrs_net_margin__', '', 1.0, '{:.1f}%'),
        (f'Net Profit (IFRS, {profile.reporting_currency} B)', 'net_profit_attributable', 'IFRS', 1e9, symbol + '{:.1f}B'),
        (f'Diluted EPS (Non-IFRS, {profile.reporting_currency})', 'diluted_eps', 'Non-IFRS management measure', 1.0, symbol + '{:.2f}'),
        (f'Free Cash Flow ({profile.reporting_currency} B)', 'free_cash_flow', 'Non-IFRS management measure', 1e9, symbol + '{:.1f}B'),
        (f'CapEx ({profile.reporting_currency} B)', 'capex', 'IFRS', 1e9, symbol + '{:.1f}B'),
    ]
    result_rows = []
    for label, metric, basis, scale, fmt in row_specs:
        row_data = {'Metric': label}
        for period in recent_periods:
            p_idx = all_periods.index(period)
            if metric == '__yoy_rev__':
                if p_idx >= 4 and tot_rev.get(period) and tot_rev.get(all_periods[p_idx-4]):
                    cur = tot_rev[period]
                    prior = tot_rev[all_periods[p_idx-4]]
                    row_data[period] = fmt.format(((cur / prior) - 1.0) * 100.0)
                else:
                    row_data[period] = '-'
            elif metric == '__qoq_rev__':
                if p_idx >= 1 and tot_rev.get(period) and tot_rev.get(all_periods[p_idx-1]):
                    cur = tot_rev[period]
                    prior = tot_rev[all_periods[p_idx-1]]
                    row_data[period] = fmt.format(((cur / prior) - 1.0) * 100.0)
                else:
                    row_data[period] = '-'
            elif metric == '__non_ifrs_op_margin__':
                if tot_rev.get(period) and non_ifrs_op.get(period):
                    row_data[period] = fmt.format((non_ifrs_op[period] / tot_rev[period]) * 100.0)
                else:
                    row_data[period] = '-'
            elif metric == '__non_ifrs_net_margin__':
                if tot_rev.get(period) and non_ifrs_np.get(period):
                    row_data[period] = fmt.format((non_ifrs_np[period] / tot_rev[period]) * 100.0)
                else:
                    row_data[period] = '-'
            else:
                subset = df[(df['period_label'] == period) & (df['metric'] == metric)]
                if basis:
                    subset = subset[subset['accounting_basis'] == basis]
                if not subset.empty:
                    val = subset.iloc[0]['reported_value']
                    if pd.notna(val):
                        scaled = float(val) / scale
                        row_data[period] = fmt.format(scaled)
                    else:
                        row_data[period] = '-'
                else:
                    row_data[period] = '-'
        result_rows.append(row_data)
    return pd.DataFrame(result_rows)


# Intermediate column name shared between the revenue frame and its chart.
REVENUE_CHART_COLUMN = 'Total revenue'


def _control_tower_repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


# The alternative-data marts live outside the published generation, so they are
# not covered by the snapshot cache in app.py. They are read from a tab body,
# and st.tabs evaluates every tab body on every rerun -- so without a cache the
# OpenRouter economics mart is decoded again on each widget interaction, even
# when the user is on Overview. Project first (17 columns -> 5 cuts the frame
# from ~38 MB to ~14 MB), then cache on (path, size, mtime).
OPENROUTER_MART_COLUMNS: tuple[str, ...] = (
    'usage_date',
    'model_permaslug',
    'model_origin_company',
    'entity_id',
    'provider_slug',
    'total_tokens',
    'estimated_revenue',
    'include_in_default_kpis',
    'is_complete_day',
)

SOUTHBOUND_MART_COLUMNS: tuple[str, ...] = (
    'hold_date',
    'holding_shares',
    'holding_market_value',
    'holding_share_pct',
)


def _parquet_fingerprint(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns)


@st.cache_data(show_spinner=False, max_entries=8)
def _read_mart_projected(
    path_str: str,
    fingerprint: tuple[int, int],
    columns: tuple[str, ...],
) -> pd.DataFrame:
    """Read a local mart, keeping only ``columns`` that the file actually has.

    A column named here but absent from the file is dropped rather than raised
    on: the candidate marts have overlapping but not identical schemas, and the
    filters downstream already treat every one of these columns as optional.
    """
    del fingerprint  # cache key only
    path = Path(path_str)
    if columns:
        available = set(pq.ParquetFile(path).schema_arrow.names)
        wanted = [column for column in columns if column in available]
        if wanted:
            return pd.read_parquet(path, columns=wanted)
    return pd.read_parquet(path)


def _bar_chart_with_year_axis(
    frame: pd.DataFrame,
    *,
    x: str,
    y: str,
    y_title: str,
    y_format: str | None = None,
    height: int = 220,
    series_name: str | None = None,
):
    plot = frame[[x, y]].dropna().copy()
    plot = plot.set_index(x)[[y]]
    # bar_chart names each trace after its column, so the legend showed the
    # raw identifier ('daily_repurchase_hkd_m') next to a worded axis.
    plot.columns = [series_name or y_title]
    return _plotly_bar_chart(
        plot,
        title='',
        y_title=y_title,
        height=height,
        value_format=y_format or ',.1f',
        tickformat='%b %Y',
    )


def _segment_share_chart(frame: pd.DataFrame):
    plot = frame.copy()
    value_cols = [c for c in plot.columns if c != 'period']
    long_index = plot['period'].astype(str)
    values = plot.loc[:, value_cols].apply(pd.to_numeric, errors='coerce')
    totals = values.sum(axis=1).replace(0, pd.NA)
    share = values.div(totals, axis=0) * 100.0
    share.index = long_index
    return stacked_share_chart(share, title='', height=280)


def _quarterly_yoy(series: pd.Series) -> pd.Series:
    """YoY % on a quarter-labelled series, by calendar quarter.

    Labels look like ``2026Q2``. Reindexing onto a gapless quarterly range
    makes the four-period lag mean a year, and fill_method=None leaves a
    quarter with no year-ago counterpart empty instead of reaching further
    back for one.
    """
    if series is None or series.empty:
        return pd.Series(dtype="float64")
    try:
        quarters = pd.PeriodIndex(series.index.astype(str), freq="Q")
    except (TypeError, ValueError):
        return series.pct_change(4) * 100
    dense = series.set_axis(quarters).reindex(
        pd.period_range(quarters.min(), quarters.max(), freq="Q")
    )
    grown = dense.pct_change(4, fill_method=None) * 100
    return grown.reindex(quarters).set_axis(series.index)


def _quarterly_profitability_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Derive quarterly operating/net margins from issuer actuals.

    Gross margin is omitted because gross profit is not in the earnings-actuals mart.
    """
    empty = pd.DataFrame(columns=[
        'period', 'period_end', 'revenue_rmb_b', 'operating_profit_non_ifrs_rmb_b',
        'net_profit_non_ifrs_rmb_b', 'operating_margin_pct', 'net_margin_pct', 'ifrs_operating_margin_pct',
    ])
    if frame is None or frame.empty:
        return empty
    df = frame.copy()
    df['period_end'] = pd.to_datetime(df['period_end'], errors='coerce')
    df = df.dropna(subset=['period_end'])
    if df.empty:
        return empty

    def _series(metric: str, basis: str) -> pd.Series:
        subset = df.loc[
            df['metric'].astype('string').eq(metric) & df['accounting_basis'].astype('string').eq(basis),
            ['period_label', 'period_end', 'reported_value'],
        ].copy()
        if subset.empty:
            return pd.Series(dtype='float64')
        subset['reported_value'] = pd.to_numeric(subset['reported_value'], errors='coerce')
        subset = subset.sort_values('period_end').drop_duplicates('period_label', keep='last')
        return subset.set_index('period_label')['reported_value']

    periods = (
        df[['period_label', 'period_end']]
        .drop_duplicates()
        .sort_values('period_end')
        .rename(columns={'period_label': 'period'})
    )
    out = periods.set_index('period')
    out['revenue'] = _series('revenue_total', 'IFRS')
    out['op_non_ifrs'] = _series('operating_profit', 'Non-IFRS management measure')
    out['np_non_ifrs'] = _series('net_profit_attributable', 'Non-IFRS management measure')
    out['op_ifrs'] = _series('operating_profit', 'IFRS')
    out = out.reset_index()
    out['revenue_rmb_b'] = pd.to_numeric(out['revenue'], errors='coerce') / 1e9
    out['operating_profit_non_ifrs_rmb_b'] = pd.to_numeric(out['op_non_ifrs'], errors='coerce') / 1e9
    out['net_profit_non_ifrs_rmb_b'] = pd.to_numeric(out['np_non_ifrs'], errors='coerce') / 1e9
    revenue = pd.to_numeric(out['revenue'], errors='coerce')
    out['operating_margin_pct'] = (pd.to_numeric(out['op_non_ifrs'], errors='coerce') / revenue * 100.0).where(revenue > 0)
    out['net_margin_pct'] = (pd.to_numeric(out['np_non_ifrs'], errors='coerce') / revenue * 100.0).where(revenue > 0)
    out['ifrs_operating_margin_pct'] = (pd.to_numeric(out['op_ifrs'], errors='coerce') / revenue * 100.0).where(revenue > 0)
    keep = [
        'period', 'period_end', 'revenue_rmb_b', 'operating_profit_non_ifrs_rmb_b',
        'net_profit_non_ifrs_rmb_b', 'operating_margin_pct', 'net_margin_pct', 'ifrs_operating_margin_pct',
    ]
    return out.loc[:, keep].dropna(subset=['operating_profit_non_ifrs_rmb_b', 'operating_margin_pct'], how='all')


def _profit_margin_chart(frame: pd.DataFrame, currency: str = 'CNY'):
    # The financial matrix reads its currency from the company profile; these
    # axis titles said RMB regardless, so a non-CNY reporter would have had a
    # currency-aware table sitting above a chart contradicting it.
    plot = frame.copy().set_index('period')
    return dual_axis_bar_line(
        plot,
        bar_column='operating_profit_non_ifrs_rmb_b',
        line_columns=['operating_margin_pct', 'net_margin_pct'],
        bar_title=f'Non-IFRS operating profit ({currency} B)',
        line_title='Margin (%)',
        bar_name=f'Non-IFRS operating profit ({currency} B)',
        line_names={
            'operating_margin_pct': 'Non-IFRS operating margin',
            'net_margin_pct': 'Non-IFRS net margin',
        },
        bar_format=',.1f',
        line_format='.1f',
        line_suffix='%',
        height=320,
    )


def _spot_forward_pe_payload(view: CompanyView) -> dict[str, Any] | None:
    """Display-only FY1 P/E from delayed quote / same-currency consensus EPS.

    This is not written into valuation_snapshots; that mart stays fail-closed
    until share count and basis-verified inputs exist.
    """
    if view.quote_snapshots.empty or view.consensus.empty:
        return None
    quote = view.quote_snapshots.iloc[0]
    price = pd.to_numeric(pd.Series([quote.get('last_price')]), errors='coerce').iloc[0]
    price_ccy = _text(quote.get('currency'))
    if pd.isna(price) or float(price) <= 0 or not price_ccy:
        return None
    cons = view.consensus.copy()
    metrics = cons.get('metric', pd.Series('', index=cons.index, dtype='string')).astype('string').str.lower()
    horizons = cons.get('horizon', pd.Series('', index=cons.index, dtype='string')).astype('string').str.lower()
    periods = cons.get('fiscal_period', pd.Series('', index=cons.index, dtype='string')).astype('string').str.lower()
    annual = cons.loc[metrics.eq('eps') & (horizons.eq('0y') | periods.eq('annual'))].copy()
    if annual.empty:
        return None
    # FY1 is the `0y` horizon. `fiscal_period == 'annual'` on its own also
    # matches +1y/+2y rows, and one capture stamps every fiscal year with the
    # same snapshot_at, so ordering by snapshot_at alone returned whichever
    # year happened to be stored first -- FY2 for every real generation. Pin
    # 0y, and fall back to the earliest annual year only when no 0y row exists.
    fy1 = annual.loc[horizons.reindex(annual.index).eq('0y')]
    is_fy1 = not fy1.empty
    eps = fy1 if is_fy1 else annual
    if not is_fy1 and 'fiscal_year' in eps.columns:
        eps = eps.assign(__fiscal_year=pd.to_numeric(eps['fiscal_year'], errors='coerce'))
        eps = eps.sort_values('__fiscal_year', na_position='last', kind='mergesort')
    if 'snapshot_at' in eps.columns and eps['snapshot_at'].notna().any():
        # Stable, so the fiscal-year order above survives inside one capture.
        eps = eps.sort_values('snapshot_at', ascending=False, na_position='last', kind='mergesort')
    row = eps.iloc[0]
    eps_value = pd.to_numeric(pd.Series([row.get('value')]), errors='coerce').iloc[0]
    eps_ccy = _text(row.get('currency'))
    if pd.isna(eps_value) or not eps_ccy:
        return None
    if eps_ccy.casefold() != price_ccy.casefold():
        return None
    eps_num = float(eps_value)
    pe_value = float(price) / eps_num if eps_num > 0 else None
    return {
        'price': float(price),
        'eps': eps_num,
        'pe': pe_value,
        'price_ccy': price_ccy,
        'eps_ccy': eps_ccy,
        'horizon': _text(row.get('horizon')),
        'fiscal_year': row.get('fiscal_year'),
        'is_fy1': is_fy1,
        'provider': _text(row.get('provider')) or 'unattributed',
        'analyst_count': row.get('analyst_count'),
        'source_url': _text(row.get('source_url')),
    }


def _dual_axis_revenue_yoy_chart(frame: pd.DataFrame, currency: str = 'CNY'):
    plot = frame.rename(columns={
        REVENUE_CHART_COLUMN: 'revenue_rmb_b',
        'YoY Growth (%)': 'yoy_pct',
    })
    return dual_axis_bar_line(
        plot,
        bar_column='revenue_rmb_b',
        line_columns=['yoy_pct'],
        bar_title=f'Total Revenue ({currency} B)',
        line_title='YoY Growth (%)',
        bar_name=f'Total revenue ({currency} B)',
        line_names={'yoy_pct': 'YoY growth'},
        bar_format=',.1f',
        line_format='+.1f',
        line_suffix='%',
        height=320,
    )


def _openrouter_daily_frame(raw: pd.DataFrame, profile=None) -> pd.DataFrame:
    """Sum OpenRouter activity for one company profile into a daily series."""
    empty_cols = ['usage_date', 'total_tokens', 'estimated_revenue', 'model_count', 'is_complete']
    filt = None if profile is None else profile.openrouter
    if raw is None or raw.empty or filt is None:
        return pd.DataFrame(columns=empty_cols)
    frame = raw.copy()
    if 'model_permaslug' not in frame.columns:
        return pd.DataFrame(columns=empty_cols)
    slugs = frame['model_permaslug'].astype('string')
    origin = frame['model_origin_company'].astype('string') if 'model_origin_company' in frame.columns else pd.Series('', index=frame.index, dtype='string')
    entity = frame['entity_id'].astype('string').str.lower() if 'entity_id' in frame.columns else pd.Series('', index=frame.index, dtype='string')
    provider = frame['provider_slug'].astype('string').str.lower() if 'provider_slug' in frame.columns else pd.Series('', index=frame.index, dtype='string')
    mask = pd.Series(False, index=frame.index)
    for prefix in filt.slug_prefixes:
        mask = mask | slugs.str.startswith(prefix, na=False)
    if filt.origin_names:
        mask = mask | origin.isin(list(filt.origin_names))
    if filt.entity_ids:
        wanted = {value.lower() for value in filt.entity_ids}
        mask = mask | entity.isin(wanted) | provider.isin(wanted)
    frame = frame.loc[mask].copy()
    if frame.empty:
        return pd.DataFrame(columns=empty_cols)
    frame['usage_date'] = pd.to_datetime(frame['usage_date'], errors='coerce').dt.normalize()
    frame = frame.dropna(subset=['usage_date'])
    frame['total_tokens'] = pd.to_numeric(frame['total_tokens'], errors='coerce').fillna(0.0)
    if 'estimated_revenue' in frame.columns:
        frame['estimated_revenue'] = pd.to_numeric(frame['estimated_revenue'], errors='coerce').fillna(0.0)
    else:
        frame['estimated_revenue'] = 0.0
    if 'include_in_default_kpis' in frame.columns:
        frame['row_complete'] = frame['include_in_default_kpis'].astype('boolean').fillna(True)
    elif 'is_complete_day' in frame.columns:
        frame['row_complete'] = frame['is_complete_day'].astype('boolean').fillna(True)
    else:
        frame['row_complete'] = True
    daily = (
        frame.groupby('usage_date', as_index=False)
        .agg(
            total_tokens=('total_tokens', 'sum'),
            estimated_revenue=('estimated_revenue', 'sum'),
            model_count=('model_permaslug', 'nunique'),
            is_complete=('row_complete', 'all'),
        )
        .sort_values('usage_date')
        .reset_index(drop=True)
    )
    daily['is_complete'] = daily['is_complete'].astype(bool)
    if daily['is_complete'].all() and len(daily) >= 8:
        last = float(daily['total_tokens'].iloc[-1])
        last_day = daily['usage_date'].iloc[-1]
        same_weekday = daily.loc[daily['usage_date'].dt.weekday.eq(last_day.weekday()) & daily['usage_date'].lt(last_day), 'total_tokens']
        typical = float(same_weekday.tail(4).median()) if len(same_weekday) >= 3 else 0.0
        if typical > 0 and last < 0.5 * typical:
            daily.loc[daily.index[-1], 'is_complete'] = False
    return daily


def _openrouter_period_frame(daily: pd.DataFrame, granularity: str) -> pd.DataFrame:
    frame = daily.copy()
    if frame.empty:
        return frame
    frame['usage_date'] = pd.to_datetime(frame['usage_date'], errors='coerce')
    if granularity == 'Daily':
        out = frame.rename(columns={'usage_date': 'period'})
        out['is_partial'] = ~out['is_complete']
        return out
    if granularity == 'Weekly':
        frame['period'] = frame['usage_date'] - pd.to_timedelta(frame['usage_date'].dt.weekday, unit='D')
        expected_days = 7
    else:
        frame['period'] = frame['usage_date'].dt.to_period('M').dt.to_timestamp()
        expected_days = frame.groupby('period')['usage_date'].transform(lambda s: int(pd.Timestamp(s.min()).days_in_month))
    grouped = (
        frame.groupby('period', as_index=False)
        .agg(
            total_tokens=('total_tokens', 'sum'),
            estimated_revenue=('estimated_revenue', 'sum'),
            model_count=('model_count', 'max'),
            observed_days=('usage_date', 'nunique'),
            complete_days=('is_complete', 'sum'),
        )
        .sort_values('period')
        .reset_index(drop=True)
    )
    if granularity == 'Weekly':
        grouped['is_partial'] = grouped['complete_days'] < expected_days
    else:
        month_days = grouped['period'].dt.days_in_month
        grouped['is_partial'] = grouped['complete_days'] < month_days
    return grouped


def _southbound_spec_from_view(view: CompanyView, profile):
    """Prefer listing-derived HKEX southbound identity over hardcoded profiles."""
    listing = None
    if view.selected_listing_id and not view.listings.empty:
        rows = view.listings.loc[view.listings['listing_id'].astype('string').eq(view.selected_listing_id)]
        if not rows.empty:
            listing = rows.iloc[0]
    if listing is None and not view.listings.empty:
        hk = view.listings.loc[view.listings.get('exchange', pd.Series('', index=view.listings.index)).astype('string').str.upper().eq('HKEX')]
        if not hk.empty:
            listing = hk.iloc[0]
    if listing is not None:
        listing_id = _text(listing.get('listing_id'))
        canonical = _text(listing.get('canonical_ticker')) or _text(listing.get('native_ticker'))
        code = hkex_security_code(listing.get('native_ticker'), canonical)
        if listing_id and code:
            return {
                'mart_filename': f'{listing_id.lower()}_southbound_holdings.parquet',
                'security_code': code,
                'canonical_ticker': canonical or f"{code[1:]}.HK",
                'listing_id': listing_id,
            }
    spec = None if profile is None else profile.southbound
    if spec is None:
        return None
    return {
        'mart_filename': spec.mart_filename,
        'security_code': spec.security_code,
        'canonical_ticker': spec.canonical_ticker,
        'listing_id': spec.listing_id,
    }


def _local_quote_overlay_path() -> Path:
    return _control_tower_repo_root() / 'data' / 'normalized' / 'marts' / 'quote_snapshots_v1.parquet'


def _newer_local_quotes(snapshot_quotes: pd.DataFrame) -> pd.DataFrame:
    """Replace published quotes with a newer local mart, listing by listing.

    This does not rewrite the generation and never widens company scope to
    other tickers. Pytest keeps the snapshot fixture by skipping the overlay.
    """
    import os
    if os.environ.get('PYTEST_CURRENT_TEST') or os.environ.get('CONTROL_TOWER_DISABLE_LOCAL_QUOTE_OVERLAY'):
        return snapshot_quotes
    if snapshot_quotes is None or snapshot_quotes.empty or 'listing_id' not in snapshot_quotes.columns:
        return snapshot_quotes
    path = _local_quote_overlay_path()
    if not path.is_file():
        return snapshot_quotes
    try:
        local = pd.read_parquet(path)
    except (OSError, ValueError):
        return snapshot_quotes
    if local.empty or 'listing_id' not in local.columns or 'quote_timestamp' not in local.columns:
        return snapshot_quotes
    local = local.copy()
    local['quote_timestamp'] = pd.to_datetime(local['quote_timestamp'], errors='coerce', utc=True)
    published = snapshot_quotes.copy()
    published['quote_timestamp'] = pd.to_datetime(published['quote_timestamp'], errors='coerce', utc=True)
    wanted = set(published['listing_id'].astype('string'))
    local = local.loc[local['listing_id'].astype('string').isin(wanted)]
    if local.empty:
        return snapshot_quotes
    rows = []
    for listing_id, group in published.groupby(published['listing_id'].astype('string'), dropna=False):
        overlay = local.loc[local['listing_id'].astype('string').eq(str(listing_id))]
        if overlay.empty:
            rows.append(group)
            continue
        pub_ts = group['quote_timestamp'].max()
        loc_ts = overlay['quote_timestamp'].max()
        if pd.notna(loc_ts) and (pd.isna(pub_ts) or loc_ts > pub_ts):
            rows.append(overlay.loc[overlay['quote_timestamp'].eq(loc_ts)].head(1))
        else:
            rows.append(group)
    return pd.concat(rows, ignore_index=True)


def _load_southbound_holdings(spec) -> pd.DataFrame:
    if spec is None:
        return pd.DataFrame()
    if not isinstance(spec, dict):
        southbound = getattr(spec, 'southbound', None)
        if southbound is None:
            return pd.DataFrame()
        spec = {
            'mart_filename': southbound.mart_filename,
            'security_code': southbound.security_code,
            'canonical_ticker': southbound.canonical_ticker,
            'listing_id': southbound.listing_id,
        }
    repo_root = _control_tower_repo_root()
    listing_id = spec.get('listing_id')
    filename = spec.get('mart_filename')
    candidates = []
    if listing_id:
        candidates.append(southbound_mart_path(repo_root, listing_id))
    if filename:
        candidates.append(repo_root / 'data/normalized/marts' / filename)
    for path in candidates:
        if path.exists():
            frame = _read_mart_projected(str(path), _parquet_fingerprint(path), SOUTHBOUND_MART_COLUMNS)
            if frame.empty:
                continue
            frame = frame.copy()
            frame['hold_date'] = pd.to_datetime(frame['hold_date'], errors='coerce')
            frame = frame.dropna(subset=['hold_date']).sort_values('hold_date').reset_index(drop=True)
            for column in ('holding_shares', 'holding_market_value', 'holding_share_pct'):
                if column in frame.columns:
                    frame[column] = pd.to_numeric(frame[column], errors='coerce')
            return frame
    return pd.DataFrame()


def _load_openrouter_raw() -> tuple[pd.DataFrame, Path | None]:
    repo_root = _control_tower_repo_root()
    candidates = [
        repo_root / 'data/normalized/marts/daily_provider_economics.parquet',
        Path('data/normalized/marts/daily_provider_economics.parquet'),
        repo_root / 'data/normalized/marts/daily_cloud_infra_economics.parquet',
        Path('data/normalized/marts/daily_cloud_infra_economics.parquet'),
        repo_root / 'data/normalized/openrouter/cloud_infra_daily_activity.parquet',
        Path('data/normalized/openrouter/cloud_infra_daily_activity.parquet'),
    ]
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            return _read_mart_projected(str(path), _parquet_fingerprint(path), OPENROUTER_MART_COLUMNS), path
    return pd.DataFrame(), None


def _render_plotly(fig) -> None:
    # Single entry point for every chart on this page, so the theme is applied
    # once here rather than threaded through ten factory calls.
    apply_chart_theme(fig, st.session_state.get('ct_theme', 'Light') == 'Dark')
    st.plotly_chart(fig, width='stretch', theme=None, config={'displayModeBar': False})


def _render_openrouter_module(view: CompanyView, profile) -> None:
    filt = profile.openrouter
    if filt is None:
        return
    heading = f'🤖 {filt.title}' if filt.title else '🤖 OpenRouter AI Token & API Economics'
    _render_section_heading(4, heading, f'{_slugify(view.entity_id)}-openrouter')
    # Only the load is guarded. The blanket try that used to wrap this whole
    # function turned any bug in the chart code below into a one-line caption
    # reading "temporarily unavailable", which is how a broken chart hid as a
    # missing feed. Data being absent or malformed is the real failure this
    # handles; a TypeError in the plotting path should surface.
    try:
        raw, source_path = _load_openrouter_raw()
        daily = _openrouter_daily_frame(raw, profile)
    except (OSError, KeyError, ValueError) as exc:
        st.caption(f'OpenRouter signal temporarily unavailable: {exc}')
        return
    if daily.empty:
        if source_path is None:
            st.info('OpenRouter alternative data dataset not found in local normalized storage.')
        else:
            st.info(f'OpenRouter dataset loaded, but no {escape(_text(view.display_name))} rows were present.')
        return
    window_options = ['Weekly', 'Daily', 'Monthly']
    window_key = f'{_slugify(view.entity_id)}_openrouter_window'
    if hasattr(st, 'segmented_control'):
        granularity = st.segmented_control('Window', window_options, default='Weekly', key=window_key)
    else:
        granularity = st.radio('Window', window_options, horizontal=True, index=0, key=window_key)
    granularity = str(granularity or 'Weekly')
    period = _openrouter_period_frame(daily, granularity)
    complete = period.loc[~period['is_partial']].copy() if 'is_partial' in period.columns else period
    latest = complete.iloc[-1] if not complete.empty else period.iloc[-1]
    recent_cut = latest['period'] - pd.Timedelta(days=30) if granularity == 'Daily' else latest['period'] - pd.Timedelta(days=90)
    recent = complete[complete['period'] >= recent_cut] if not complete.empty else period
    avg_tokens = float(recent['total_tokens'].mean()) if not recent.empty else 0.0
    n_models = int(period['model_count'].max()) if not period.empty else 0
    start = period['period'].min().strftime('%Y-%m-%d')
    end = period['period'].max().strftime('%Y-%m-%d')
    source_name = source_path.name if source_path is not None else 'openrouter'
    partial_n = int(period['is_partial'].sum()) if 'is_partial' in period.columns else 0
    signal_name = filt.signal_name or 'tokens'
    st.markdown(
        (
            '<div class="ct-kpi-grid">'
            f'<div class="ct-kpi-card"><div class="ct-kpi-label">Latest complete {granularity.lower()} tokens</div><div class="ct-kpi-value">{float(latest["total_tokens"]) / 1e9:,.1f}B</div><div class="ct-kpi-sub">{pd.Timestamp(latest["period"]).strftime("%Y-%m-%d")} · all models summed</div></div>'
            f'<div class="ct-kpi-card"><div class="ct-kpi-label">Latest complete est. revenue</div><div class="ct-kpi-value">${float(latest["estimated_revenue"]):,.0f}</div><div class="ct-kpi-sub">OpenRouter priced routes</div></div>'
            f'<div class="ct-kpi-card"><div class="ct-kpi-label">Recent avg tokens</div><div class="ct-kpi-value">{avg_tokens / 1e9:,.1f}B</div><div class="ct-kpi-sub">Complete {granularity.lower()} periods only</div></div>'
            f'<div class="ct-kpi-card"><div class="ct-kpi-label">Tracked models</div><div class="ct-kpi-value">{n_models} Models</div><div class="ct-kpi-sub">Aggregated, not split by model</div></div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )
    token_plot = period.set_index('period')[['total_tokens']].rename(columns={'total_tokens': signal_name})
    revenue_plot = period.set_index('period')[['estimated_revenue']].rename(columns={'estimated_revenue': 'Estimated revenue'})
    partial_mask = period.set_index('period')['is_partial'] if 'is_partial' in period.columns else None
    if granularity == 'Daily':
        _render_plotly(_plotly_line_chart(token_plot / 1e9, colors=MODEL_COLORS, y_title='Tokens (billions)', value_format=',.1f', hover_suffix='B', height=340))
        _render_plotly(_plotly_line_chart(revenue_plot, colors=[ACCENT], y_title='Estimated revenue (USD)', value_format='$,.0f', height=300))
    else:
        _render_plotly(_plotly_bar_chart(token_plot / 1e9, y_title='Tokens (billions)', value_format=',.1f', hover_suffix='B', height=340, partial_mask=partial_mask))
        _render_plotly(_plotly_bar_chart(revenue_plot, colors=[ACCENT], y_title='Estimated revenue (USD)', value_format='$,.0f', height=300, partial_mask=partial_mask))
    note = f'{granularity} {signal_name} and estimated-revenue totals, all models summed · {start} to {end} · source: {source_name}.'
    if partial_n:
        note += f' Lighter bars are incomplete {granularity.lower()} periods shown as observed totals only; they are not nowcast.'
    st.caption(note + ' ' + (filt.caption or 'Estimated revenue is a priced-route reconstruction, not issuer billed revenue.'))


def _render_southbound_module(view: CompanyView, profile) -> None:
    spec = _southbound_spec_from_view(view, profile)
    if spec is None:
        return
    _render_section_heading(4, '🌊 HKEX Southbound Stock Connect (港股通南向资金) Liquidity Signal', f'{_slugify(view.entity_id)}-southbound-flow')
    holdings = _load_southbound_holdings(spec)
    ticker = spec['canonical_ticker']
    if holdings.empty:
        code = spec['security_code']
        extra = ''
        if code in {'09888', '9888'}:
            extra = ' Eastmoney returned an empty payload for Baidu 9888.HK (akshare result[pages] is null); this is an upstream gap, not a missing listing mapping.'
        st.warning(
            f"Southbound holding history is unavailable locally. Expected data/normalized/marts/{spec['mart_filename']} "
            f"from Eastmoney/akshare stock_hsgt_individual_em({code}).{extra}"
        )
        st.caption('This is a rolling ~2-year per-stock ownership series, not the 2014-onward market-wide southbound flow.')
        return
    latest = holdings.iloc[-1]
    prev_30 = holdings[holdings['hold_date'] <= latest['hold_date'] - pd.Timedelta(days=30)]
    shares = float(latest['holding_shares']) if pd.notna(latest.get('holding_shares')) else float('nan')
    mv = float(latest['holding_market_value']) if pd.notna(latest.get('holding_market_value')) else float('nan')
    pct = float(latest['holding_share_pct']) if pd.notna(latest.get('holding_share_pct')) else float('nan')
    mv_30 = float('nan')
    if not prev_30.empty and pd.notna(mv):
        prior_mv = pd.to_numeric(prev_30.iloc[-1].get('holding_market_value'), errors='coerce')
        if pd.notna(prior_mv):
            mv_30 = mv - float(prior_mv)
    asof = pd.Timestamp(latest['hold_date']).strftime('%Y-%m-%d')
    # NaN formats as the literal string 'nan', so an absent value rendered as
    # 'nanM shares' / 'HK$ nanB' / 'nan%'. Only the 30-day delta was guarded.
    shares_html = f'{shares/1e6:,.1f}M shares' if pd.notna(shares) else 'Unavailable'
    mv_html = f'HK$ {mv/1e9:,.1f}B' if pd.notna(mv) else 'Unavailable'
    pct_html = f'{pct:.2f}%' if pd.notna(pct) else 'Unavailable'
    mv_30_html = f'+HK$ {mv_30/1e9:,.1f}B' if pd.notna(mv_30) and mv_30 >= 0 else (f'-HK$ {abs(mv_30)/1e9:,.1f}B' if pd.notna(mv_30) else 'Unavailable')
    mv_30_color = '#16a34a' if pd.notna(mv_30) and mv_30 >= 0 else ('#dc2626' if pd.notna(mv_30) else 'inherit')
    st.markdown(
        (
            '<div class="ct-kpi-grid">'
            f'<div class="ct-kpi-card"><div class="ct-kpi-label">Southbound holding</div><div class="ct-kpi-value">{shares_html}</div><div class="ct-kpi-sub">{asof}</div></div>'
            f'<div class="ct-kpi-card"><div class="ct-kpi-label">Holding market value</div><div class="ct-kpi-value">{mv_html}</div><div class="ct-kpi-sub">Eastmoney / HSGT individual</div></div>'
            f'<div class="ct-kpi-card"><div class="ct-kpi-label">Share of issued shares</div><div class="ct-kpi-value">{pct_html}</div><div class="ct-kpi-sub">Provider labels this as A-share %, but the series is {escape(ticker)}</div></div>'
            f'<div class="ct-kpi-card"><div class="ct-kpi-label">~30D holding MV change</div><div class="ct-kpi-value" style="color:{mv_30_color};">{mv_30_html}</div><div class="ct-kpi-sub">Price plus share-count mix, not official net inflow</div></div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )
    share_plot = holdings.set_index('hold_date')[['holding_shares']].rename(columns={'holding_shares': 'Southbound shares'})
    mv_plot = holdings.set_index('hold_date')[['holding_market_value']].rename(columns={'holding_market_value': 'Holding market value'})
    pct_plot = holdings.set_index('hold_date')[['holding_share_pct']].rename(columns={'holding_share_pct': 'Holding share %'})
    _render_plotly(_plotly_line_chart(share_plot / 1e6, y_title='Shares (millions)', value_format=',.1f', hover_suffix='M', height=300))
    _render_plotly(_plotly_line_chart(mv_plot / 1e9, colors=['#00B5A4'], y_title='Holding market value (HK$ B)', value_format=',.1f', hover_suffix='B', height=280))
    _render_plotly(_plotly_line_chart(pct_plot, colors=['#8B5CF6'], y_title='Holding share %', value_format='.2f', hover_suffix='%', height=240))
    start = holdings['hold_date'].min().strftime('%Y-%m-%d')
    end = holdings['hold_date'].max().strftime('%Y-%m-%d')
    st.caption(f'{ticker} southbound ownership from Eastmoney/akshare stock_hsgt_individual_em · {start} to {end} · {len(holdings):,} daily rows. Rolling window only; this is not the 2014-onward market-wide southbound series.')


def _render_alternative_data_tab(view: CompanyView) -> None:
    profile = get_company_profile(view.entity_id)
    _render_section_heading(4, 'Alternative data signals', f'alternative-data-{_slugify(view.entity_id)}')
    southbound_spec = _southbound_spec_from_view(view, profile)
    has_modules = bool(profile.openrouter or southbound_spec)
    if not has_modules:
        st.info(
            f'No company-specific alternative-data modules are wired for {_text(view.display_name)} yet. '
            'Official filings, consensus, and thesis evidence remain on the other tabs.'
        )
        return
    if profile.alt_data_caption:
        st.caption(profile.alt_data_caption)
    _render_openrouter_module(view, profile)
    _render_southbound_module(view, profile)




@st.cache_data(show_spinner=False, max_entries=8)
def _load_vendor_financials_cached(
    entity_id: str,
    listing_id: str | None,
    listings_json: str,
    mart_path: str,
    fingerprint: tuple[int, int] | None,
) -> tuple[str, str, str, str]:
    """Cache the labelled vendor overlay; official actuals are never touched."""

    del fingerprint
    listings = pd.read_json(listings_json, dtype=False) if listings_json else pd.DataFrame()
    result = load_vendor_financials(
        entity_id=entity_id,
        listing_id=listing_id,
        listings=listings,
        local_mart_path=Path(mart_path) if mart_path else None,
        allow_sibling_fallback=not bool(mart_path and Path(mart_path).is_file()),
    )
    payload = result.frame.to_json(date_format='iso', default_handler=str) if result.frame is not None else ''
    return result.status, result.detail, result.source_kind, payload


def _vendor_financials_for_view(view: CompanyView) -> VendorLoadResult:
    """Read labelled yfinance/akshare rows without touching official actuals."""

    if view.entity_type == 'private' and view.listings.empty:
        return VendorLoadResult(pd.DataFrame(), 'unavailable', 'private entity has no listing for vendor financials', 'local_mart')
    mart = default_local_mart_path(_control_tower_repo_root())
    fingerprint = _parquet_fingerprint(mart) if mart.is_file() else None
    listings_json = view.listings.to_json(date_format='iso', default_handler=str) if view.listings is not None and not view.listings.empty else ''
    try:
        status, detail, source_kind, payload = _load_vendor_financials_cached(
            view.entity_id,
            view.selected_listing_id,
            listings_json,
            str(mart),
            fingerprint,
        )
    except (OSError, ValueError) as exc:
        return VendorLoadResult(pd.DataFrame(), 'error', f'vendor financials failed: {exc}', 'local_mart')
    frame = pd.read_json(payload, dtype=False) if payload else pd.DataFrame()
    return VendorLoadResult(frame, status, detail, source_kind)


def _vendor_series(frame: pd.DataFrame, provider: str, metric: str, period_type: str) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=['period_end', 'period_label', 'reported_value', 'currency', 'source_label'])
    scoped = frame.loc[
        frame['provider'].astype('string').eq(provider)
        & frame['metric'].astype('string').eq(metric)
        & frame['period_type'].astype('string').eq(period_type)
    ].copy()
    if scoped.empty:
        return scoped
    scoped['period_end'] = pd.to_datetime(scoped['period_end'], errors='coerce')
    scoped = scoped.dropna(subset=['period_end', 'reported_value']).sort_values('period_end')
    return scoped.drop_duplicates(subset=['period_end'], keep='last')


def _render_vendor_financials_overlay(view: CompanyView) -> VendorLoadResult:
    _render_section_heading(
        4,
        'Vendor financials overlay (not official)',
        f'vendor-financials-{_slugify(view.entity_id)}',
    )
    result = _vendor_financials_for_view(view)
    st.caption(vendor_source_caption(result))
    frame = result.frame
    if result.status == 'error':
        st.error(result.detail)
        return result
    if frame is None or frame.empty:
        st.info(result.detail or 'Vendor financials overlay unavailable for this listing.')
        return result
    st.warning(
        'These numbers come from yfinance and/or akshare inside the sibling financial-data store. '
        'They are not HKEX/SEC issuer actuals, not IFRS vs Non-IFRS, and not a PIT official series. '
        'AkShare interim rows are year-to-date. Currencies are source-reported and not FX-aligned.'
    )
    annual_rev = _vendor_series(frame, 'yfinance', 'revenue_total', 'annual')
    annual_op = _vendor_series(frame, 'yfinance', 'operating_profit', 'annual')
    annual_np = _vendor_series(frame, 'yfinance', 'net_profit_attributable', 'annual')
    if not annual_rev.empty:
        annual_rev = annual_rev.loc[pd.to_numeric(annual_rev['reported_value'], errors='coerce').fillna(0) != 0]
        plot = pd.DataFrame({'period_end': annual_rev['period_end']})
        plot = plot.merge(
            annual_rev[['period_end', 'reported_value']].rename(columns={'reported_value': 'Revenue'}),
            on='period_end',
            how='left',
        )
        if not annual_op.empty:
            plot = plot.merge(
                annual_op[['period_end', 'reported_value']].rename(columns={'reported_value': 'Operating profit'}),
                on='period_end',
                how='left',
            )
        if not annual_np.empty:
            plot = plot.merge(
                annual_np[['period_end', 'reported_value']].rename(columns={'reported_value': 'Net profit attributable'}),
                on='period_end',
                how='left',
            )
        currency = _text(annual_rev.iloc[-1].get('currency')) or 'CNY'
        values = plot.set_index('period_end').apply(pd.to_numeric, errors='coerce') / 1e9
        st.caption(f'yfinance annual statements via financial-data · values in {currency} billions · vendor reported, unverified · zeros dropped')
        _render_plotly(_plotly_bar_chart(values, y_title=f'{currency} billions', value_format=',.1f', height=300, tickformat='%Y'))
    display_columns = [
        column for column in (
            'provider', 'source_label', 'period_label', 'period_type', 'interim_is_ytd', 'metric',
            'source_metric_label', 'reported_value', 'currency', 'currency_semantics', 'unit', 'pit_class',
        ) if column in frame.columns
    ]
    friendly = frame.loc[:, display_columns].rename(columns={
        'provider': 'Provider',
        'source_label': 'Source',
        'period_label': 'Period',
        'period_type': 'Period type',
        'interim_is_ytd': 'Interim is YTD',
        'metric': 'Metric',
        'source_metric_label': 'Vendor line item',
        'reported_value': 'Reported',
        'currency': 'Currency',
        'currency_semantics': 'Currency semantics',
        'unit': 'Unit',
        'pit_class': 'PIT class',
    })
    with st.expander('Vendor row registry (yfinance / akshare via financial-data)', expanded=False):
        ct_dataframe(friendly, width='stretch', hide_index=True)
    return result

def _render_fundamentals_tab(
    view: CompanyView,
    snapshot: ControlTowerSnapshot,
    viewer_timezone: str,
) -> None:
    _render_section_heading(4, 'Segment disclosures & core operations', f'segment-disclosures-{_slugify(view.entity_id)}')
    frame = _company_earnings_actuals(snapshot, view)
    if frame.empty:
        st.info('No earnings-actuals rows for this entity/listing in the current snapshot; values are only shown from official issuer disclosure metadata.')
    else:
        profile = get_company_profile(view.entity_id)
        pivoted_model = _build_quarterly_financial_pivot(frame, n_periods=8, profile=profile)
        if not pivoted_model.empty:
            st.caption(f'Multi-period quarterly financial trajectory (LTM 8 quarters in {profile.reporting_currency} billions) · GAAP vs Non-IFRS dual track · YoY & QoQ growth metrics')
            ct_dataframe(pivoted_model, width='stretch', hide_index=True)
        act_dt = frame.copy()
        act_dt['period_end'] = pd.to_datetime(act_dt['period_end'], errors='coerce')
        act_dt = act_dt.dropna(subset=['period_end']).sort_values('period_end')
        act_dt['quarter_label'] = act_dt['period_end'].dt.year.astype(str) + 'Q' + act_dt['period_end'].dt.quarter.astype(str)
        piv_chart = act_dt[act_dt['accounting_basis'] == 'IFRS'].pivot_table(index='quarter_label', columns='metric', values='reported_value', aggfunc='first') / 1e9
        period_order = act_dt[['quarter_label', 'period_end']].drop_duplicates().sort_values('period_end')['quarter_label'].tolist()
        piv_chart = piv_chart.reindex(period_order)
        if 'revenue_total' in piv_chart.columns:
            piv_chart = piv_chart.dropna(subset=['revenue_total'])
        if len(piv_chart) >= 4:
            seg_chart_df = pd.DataFrame(index=piv_chart.index)
            seen_labels = set()
            preferred = list(profile.segment_metrics)
            if not preferred:
                extra = [c for c in piv_chart.columns if str(c).startswith('revenue_') and str(c) != 'revenue_total']
                preferred = [SegmentSpec(metric, segment_label(metric, profile)) for metric in extra]
            for spec in preferred:
                if spec.metric not in piv_chart.columns or spec.label in seen_labels:
                    continue
                seen_labels.add(spec.label)
                seg_chart_df[spec.label] = piv_chart[spec.metric]
            if not seg_chart_df.empty and seg_chart_df.notna().any().any():
                share_frame = seg_chart_df.copy()
                share_frame.index.name = 'period'
                share_frame = share_frame.reset_index()
                st.caption('Quarterly segment mix (% share of disclosed segments). Absolute reported currency is on the total-revenue chart below.')
                _render_plotly(_segment_share_chart(share_frame))
            rev_growth_df = pd.DataFrame(index=piv_chart.index)
            rev_growth_df[REVENUE_CHART_COLUMN] = piv_chart['revenue_total']
            # Four rows back is only a year back when every intervening
            # quarter is present, and the dropna above removes any quarter
            # without a reported total -- so a company that skipped one had
            # its next four quarters compared against the wrong period.
            rev_growth_df['YoY Growth (%)'] = _quarterly_yoy(piv_chart['revenue_total'])
            st.caption('Quarterly topline and YoY growth · left axis revenue, right axis YoY')
            _render_plotly(_dual_axis_revenue_yoy_chart(rev_growth_df, profile.reporting_currency))
            profit_frame = _quarterly_profitability_frame(frame)
            if not profit_frame.empty:
                st.caption('Quarterly Non-IFRS operating profit and margins. Gross margin is unavailable because gross profit is not in the current earnings-actuals mart.')
                _render_plotly(_profit_margin_chart(profit_frame, profile.reporting_currency))
        metrics = frame.get('metric', pd.Series('', index=frame.index, dtype='string')).astype('string')
        has_segments = metrics.str.startswith('revenue_') & ~metrics.eq('revenue_total')
        if has_segments.any():
            st.caption('Official segment revenue rows extracted from issuer disclosures.')
        sorted_actuals = frame.sort_values(['period_end', 'metric', 'version'], ascending=False)
        actuals_display_columns = ('period_label', 'metric', 'reported_value', 'normalized_value', 'currency', 'unit', 'accounting_basis', 'filing_at', 'version', 'is_restatement', 'revision_reason', 'source_url')
        keep_cols = [c for c in actuals_display_columns if c in sorted_actuals.columns]
        friendly_actuals = sorted_actuals.loc[:, keep_cols].rename(columns={'period_label': 'Period', 'metric': 'Metric', 'reported_value': 'Reported', 'normalized_value': 'Normalized', 'currency': 'Currency', 'unit': 'Unit', 'accounting_basis': 'Basis', 'filing_at': 'Filing date', 'version': 'Version', 'is_restatement': 'Restatement', 'revision_reason': 'Revision reason', 'source_url': 'Source link'})
        with st.expander('Detailed row-level filing actuals registry', expanded=False):
            ct_dataframe(friendly_actuals, width='stretch', hide_index=True)
        latest = sorted_actuals['period_end'].dropna()
        if not latest.empty:
            latest_label = _text(sorted_actuals.loc[sorted_actuals['period_end'].eq(latest.max()), 'period_label'].iloc[0])
            st.caption(f'Latest reported period in snapshot: {escape(latest_label) if latest_label else latest.max().strftime("%Y-%m-%d")} · reported values preserved per filing; restatements are versioned, not overwritten.')
    _render_vendor_financials_overlay(view)
    render_earnings_calendar(snapshot, entity_id=view.entity_id, listing_id=view.selected_listing_id)
    _render_section_heading(4, 'Profitability & Free Cash Flow trajectory', f'fcf-trajectory-{_slugify(view.entity_id)}')
    trajectory = _latest_actual_rows(frame)
    if not trajectory.empty:
        metric_names = trajectory.get('metric', pd.Series('', index=trajectory.index, dtype='string')).astype('string').str.lower()
        trajectory = trajectory.loc[metric_names.str.contains(r'free_cash_flow|cash_flow|prepayment|capital_expenditure|capex|operating_margin|operating_profit', regex=True, na=False)]
    if trajectory.empty:
        st.info('Profitability and Free Cash Flow metrics unavailable · no matching earnings-actuals rows for the latest reported period.')
    else:
        display_columns = [column for column in ('period_label', 'metric', 'reported_value', 'normalized_value', 'currency', 'unit', 'accounting_basis', 'filing_at', 'source_id', 'source_url', 'pit_class') if column in trajectory.columns]
        ct_dataframe(trajectory.loc[:, display_columns].rename(columns={'period_label': 'Period', 'metric': 'Metric', 'reported_value': 'Reported', 'normalized_value': 'Normalized', 'currency': 'Currency', 'unit': 'Unit', 'accounting_basis': 'Basis', 'filing_at': 'Filing date', 'source_id': 'Source', 'source_url': 'Source link', 'pit_class': 'PIT class'}), width='stretch', hide_index=True)
        st.caption('Reported and normalized values remain distinct and retain their row-level provenance.')
    _render_section_heading(4, 'Statutory capital returns & corporate actions', f'corporate-actions-{_slugify(view.entity_id)}')
    if view.corporate_actions.empty:
        st.info('No statutory corporate-action rows for the selected listing in the current snapshot.')
    else:
        total_spent = view.corporate_actions['total_amount_paid'].dropna().sum() if 'total_amount_paid' in view.corporate_actions.columns else 0.0
        total_shares = view.corporate_actions['shares_affected'].dropna().sum() if 'shares_affected' in view.corporate_actions.columns else 0
        ccy = _text(view.corporate_actions.iloc[0].get('currency')) or 'HKD'
        spent_html = f'{ccy} {total_spent/1e9:,.2f}B' if total_spent else 'Unavailable'
        shares_html = f'{int(total_shares):,}' if total_shares else 'Unavailable'
        bb_tracker_html = (
            '<div class="ct-buyback-tracker">'
            '<div class="ct-panel-heading"><h3 style="font-size: 0.95rem; font-weight: 750;">🛡️ Statutory capital returns</h3></div>'
            '<div class="ct-kpi-grid" style="margin-top: 0.5rem;">'
            f'<div class="ct-kpi-card"><div class="ct-kpi-label">Recorded amount</div><div class="ct-kpi-value">{spent_html}</div><div class="ct-kpi-sub">{len(view.corporate_actions)} selected-listing rows</div></div>'
            f'<div class="ct-kpi-card"><div class="ct-kpi-label">Shares affected</div><div class="ct-kpi-value">{shares_html}</div><div class="ct-kpi-sub">From local corporate-actions mart</div></div>'
            '</div></div>'
        )
        st.markdown(bb_tracker_html, unsafe_allow_html=True)
        ct_dataframe(_friendly_corporate_actions_frame(view.corporate_actions, viewer_timezone), width='stretch', hide_index=True)
    _render_section_heading(4, 'Valuation multiples & return yields', f'valuation-multiples-{_slugify(view.entity_id)}')
    spot = _spot_forward_pe_payload(view)
    if spot is not None:
        spot_pe_html = f'{spot["pe"]:.1f}x' if spot.get('pe') else 'NM'
        analysts = spot['analyst_count']
        analyst_label = f"{int(analysts)} analysts" if pd.notna(analysts) else 'analyst count unavailable'
        # Name the year the ratio actually used. The card used to say "FY1"
        # unconditionally, which hid a selection that could land on FY2.
        if pd.notna(spot['fiscal_year']):
            year_label = f"FY{int(spot['fiscal_year'])}"
        else:
            year_label = spot['horizon'] or 'fiscal year unavailable'
        eps_label = 'FY1 consensus EPS' if spot['is_fy1'] else f'Consensus EPS · {year_label}'
        st.markdown(
            (
                '<div class="ct-kpi-grid">'
                f'<div class="ct-kpi-card"><div class="ct-kpi-label">Last delayed price</div><div class="ct-kpi-value">{spot["price_ccy"]} {spot["price"]:,.2f}</div><div class="ct-kpi-sub">Quote snapshot</div></div>'
                f'<div class="ct-kpi-card"><div class="ct-kpi-label">{escape(eps_label)}</div><div class="ct-kpi-value">{spot["eps_ccy"]} {spot["eps"]:.2f}</div><div class="ct-kpi-sub">{escape(year_label)} · {escape(spot["provider"])} · {escape(analyst_label)}</div></div>'
                f'<div class="ct-kpi-card"><div class="ct-kpi-label">Spot forward P/E</div><div class="ct-kpi-value">{spot_pe_html}</div><div class="ct-kpi-sub">Price / {escape(year_label)} EPS · vendor display-only, not official valuation_snapshots</div></div>'
                '<div class="ct-kpi-card"><div class="ct-kpi-label">Trailing / historical P/E</div><div class="ct-kpi-value">Unavailable</div><div class="ct-kpi-sub">No share-count or historical EPS vintage in the valuation mart</div></div>'
                '</div>'
            ),
            unsafe_allow_html=True,
        )
        fy1_note = '' if spot['is_fy1'] else ' No 0y consensus row is available, so the earliest annual estimate is used instead.'
        st.caption(
            f'Spot forward P/E is a same-currency vendor display ratio from delayed yfinance quote and yfinance consensus EPS ({year_label}).'
            f'{fy1_note} Negative FY1 EPS is shown as NM. This is not a valuation_snapshots row, not share-count-based, and not a historical percentile.'
        )
    else:
        st.info('Vendor forward P/E unavailable · needs a delayed quote and a same-currency yfinance annual EPS consensus row.')
    if view.valuation_snapshots.empty:
        st.warning('Audited valuation mart unavailable · official forward_pe / EV/EBITDA / FCF yield still require contemporaneous quote, share count, and basis-verified consensus. The vendor overlay above is separate and labelled.')
    else:
        ct_dataframe(_friendly_valuation_frame(view.valuation_snapshots), width='stretch', hide_index=True)
        st.caption('percentile_history_status: unavailable · Historical denominator vintages are absent; reconstructing synthetic historical percentiles from current-vintage statements is strictly forbidden by policy.')



def _render_thesis_catalysts_tab(
    view: CompanyView,
    snapshot: ControlTowerSnapshot,
    viewer_timezone: str,
) -> None:
    _render_section_heading(4, 'Thesis claims (Human-authored)', f'thesis-claims-{_slugify(view.entity_id)}')
    if view.thesis_claims.empty:
        st.info('No human-authored thesis claims registered for this entity.')
    else:
        for _, row in view.thesis_claims.iterrows():
            title = _text(row.get('thesis_title')) or _text(row.get('claim_id'))
            status = _text(row.get('status')).upper() or 'STATUS UNAVAILABLE'
            claim_text = _text(row.get('claim_text'))
            rule = _text(row.get('invalidation_rule'))
            reviewed_by = _text(row.get('reviewed_by')) or 'Not recorded'
            reviewed_at = _format_time(row.get('last_reviewed_at_utc'), viewer_timezone) if _text(row.get('last_reviewed_at_utc')) else 'Not recorded'
            title_lower = title.lower()
            if 'bull' in title_lower:
                card_class = 'ct-thesis-card--bull'
                badge_color = '#16a34a'
            elif 'bear' in title_lower:
                card_class = 'ct-thesis-card--bear'
                badge_color = '#dc2626'
            else:
                card_class = 'ct-thesis-card--base'
                badge_color = 'var(--ct-accent)'
            card_html = f'<div class="ct-thesis-card {card_class}"><div class="ct-panel-heading"><h3 style="font-size: 1.02rem; font-weight: 800; color: var(--ct-ink); margin: 0;">{escape(title)}</h3><span class="ct-badge" style="color: {badge_color}; border-color: {badge_color}; font-weight: 750;">[{escape(status)}]</span></div><div class="ct-subtle" style="margin-bottom: 0.5rem;">Human-authored thesis · status: <strong>{escape(status.lower())}</strong> (never automatically promoted to active or mutated by AI)</div><div style="font-size: 0.9rem; line-height: 1.5; color: var(--ct-ink); margin-bottom: 0.65rem;">{escape(claim_text)}</div><div class="ct-alert-strip" style="margin: 0.5rem 0; font-size: 0.82rem;"><strong>🚨 Invalidation Rule:</strong> {escape(rule)}</div><div class="ct-source-line">Reviewed by: {escape(reviewed_by)} · Last reviewed: {escape(reviewed_at)}</div></div>'
            st.markdown(card_html, unsafe_allow_html=True)
    _render_section_heading(4, 'Active & upcoming catalysts', f'catalysts-{_slugify(view.entity_id)}')
    if view.events.empty:
        st.info('No explicitly linked events are available for this company.')
    else:
        for _, row in view.events.iterrows():
            source_link = 'source link available' if _text(row.get('source_url')).startswith(('http://', 'https://')) else 'source link unavailable'
            certainty = _text(row.get('certainty_class')).replace('_', ' ')
            precision = str(row.get('date_precision') or 'day').lower()
            start = pd.to_datetime(row.get('starts_at'), errors='coerce', utc=True)
            end = pd.to_datetime(row.get('ends_at'), errors='coerce', utc=True)
            if pd.isna(start):
                start = None
            if pd.isna(end):
                end = start
            window_str = format_event_window(row.get('starts_at'), row.get('ends_at'), precision, viewer_timezone)
            is_active = is_active_catalyst(row.get('starts_at'), row.get('ends_at'), snapshot.now_utc)
            is_upcoming = (start is not None and start > snapshot.now_utc)
            status_label = 'Active window' if is_active else ('Upcoming' if is_upcoming else 'Observed / Past')
            if precision in ('day', 'exact', 'hour', 'minute'):
                t_minus = format_t_minus(row.get('starts_at'), viewer_timezone, snapshot.now_utc)
                timing_str = f'{window_str} ({t_minus})'
            else:
                timing_str = f'{window_str} · {status_label}'
            st.markdown(f'**{escape(_text(row.get("title")))}** · {escape(_text(row.get("relation_role")))} · *{escape(certainty)}* · `{escape(precision)}` · {timing_str} · {escape(source_link)}')
        with st.expander('Event lineage details', expanded=False):
            ct_dataframe(view.events, width='stretch', hide_index=True)
    _render_section_heading(4, 'Operational watch questions & falsification criteria', f'watch-questions-{_slugify(view.entity_id)}')
    if not view.thesis_watch_questions.empty:
        ct_dataframe(_friendly_thesis_questions_frame(view.thesis_watch_questions), width='stretch', hide_index=True)
    elif not view.watch_questions.empty:
        ct_dataframe(_friendly_question_frame(view.watch_questions), width='stretch', hide_index=True)
    else:
        st.info('No watch questions are registered.')



def _consensus_revision_chart_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """One bar per lookback x horizon, in percent units.

    The mart stores revision_pct as a decimal (-0.024 = -2.4%). Duplicate
    labels such as "eps (annual)" must not collapse FY1 and FY2, or 7d/30d/60d/90d,
    onto two oversized bars.
    """
    empty = pd.DataFrame()
    if frame is None or frame.empty or 'revision_pct' not in frame.columns:
        return empty
    plot = frame.copy()
    plot['revision_pct'] = pd.to_numeric(plot['revision_pct'], errors='coerce') * 100.0
    plot = plot.dropna(subset=['revision_pct'])
    if plot.empty:
        return empty
    metrics = plot.get('metric', pd.Series('eps', index=plot.index, dtype='string')).astype('string').str.lower()
    plot = plot.loc[metrics.eq('eps')].copy()
    if plot.empty:
        return empty
    lookback = pd.to_numeric(plot.get('lookback_days', pd.Series(index=plot.index, dtype='float64')), errors='coerce')
    horizon = plot.get('horizon', pd.Series('', index=plot.index, dtype='string')).astype('string')
    fiscal_year = plot.get('fiscal_year', pd.Series(pd.NA, index=plot.index))
    period = plot.get('fiscal_period', pd.Series('', index=plot.index, dtype='string')).astype('string')
    labels = []
    for idx in plot.index:
        year = fiscal_year.loc[idx]
        year_bit = f"FY{int(year)}" if pd.notna(year) else str(period.loc[idx] or 'period')
        hz = str(horizon.loc[idx] or '').strip()
        labels.append(f"{year_bit} {hz}".strip())
    plot['series'] = labels
    plot['lookback'] = lookback.map(lambda value: f"{int(value)}d" if pd.notna(value) else 'lookback unavailable')
    # Prefer the latest snapshot when a lookback/horizon pair is duplicated.
    if 'current_snapshot_at' in plot.columns:
        plot = plot.sort_values('current_snapshot_at', ascending=False, na_position='last')
    plot = plot.drop_duplicates(['lookback', 'series'], keep='first')
    wide = (
        plot.pivot_table(index='lookback', columns='series', values='revision_pct', aggfunc='first')
        .reindex([label for label in ('7d', '30d', '60d', '90d') if label in set(plot['lookback'])])
    )
    return wide.dropna(how='all')



def _refresh_cooldown_remaining(entity_id: str) -> tuple[float, str]:
    # Read from disk, not session_state: a page reload or a second tab starts
    # a new Streamlit session, and the quota being protected belongs to the
    # API key, which every session shares.
    return refresh_cooldown_remaining(entity_id, repo_root=_control_tower_repo_root())


def _run_company_news_refresh(view: CompanyView) -> None:
    remaining, scope = _refresh_cooldown_remaining(view.entity_id)
    if remaining > 0:
        st.warning(
            f'Refresh cooldown ({scope}) · wait {int(remaining) + 1}s to protect '
            'Marketaux free-tier quota.'
        )
        return
    with st.spinner('Fetching HKEXnews plus vendor headlines for this company…'):
        result = refresh_company_news(
            view.entity_id,
            repo_root=_control_tower_repo_root(),
            listing_id=view.selected_listing_id,
        )
    record_refresh(
        view.entity_id,
        now_utc=result.fetched_at_utc,
        repo_root=_control_tower_repo_root(),
    )
    st.session_state['ct_news_refresh_result'] = result.to_dict()
    st.session_state['ct_news_refresh_entity'] = view.entity_id


def _render_refresh_status(view: CompanyView) -> None:
    payload = st.session_state.get('ct_news_refresh_result') or {}
    if payload.get('entity_id') != view.entity_id:
        return
    fetched = escape(_text(payload.get('fetched_at_utc')) or 'time unavailable')
    bits = []
    for item in payload.get('sources') or []:
        bits.append(
            f"{escape(_text(item.get('source_id')))} · {escape(_text(item.get('status')))} · "
            f"new {escape(_text(item.get('new_rows')))}"
        )
    st.caption(f'Last on-demand refresh · {fetched} · ' + ' · '.join(bits))
    for issue in payload.get('issues') or []:
        st.warning(escape(_text(issue)))


def _hkex_event_bucket(event_class: object, headline: object) -> str:
    label = _text(event_class).lower()
    title = _text(headline).upper()
    if label == 'earnings_results' or ('RESULTS' in title and 'ENDED' in title):
        return 'priority'
    if label == 'period_report' or title.strip() in {'INTERIM REPORT', 'ANNUAL REPORT'} or (
        ('INTERIM REPORT' in title or 'ANNUAL REPORT' in title) and 'ENDED' not in title
    ):
        return 'reports'
    if label in {'share_buyback', 'share_scheme'} or 'NEXT DAY DISCLOSURE' in title or 'SHARE AWARD' in title or 'SHARE OPTION' in title:
        return 'routine'
    return 'other'


def _hkex_card_tone(event_class: object, headline: object) -> str:
    label = _text(event_class).lower()
    title = _text(headline).upper()
    if label == 'earnings_results' or ('RESULTS' in title and 'ENDED' in title):
        return 'results'
    if label == 'period_report' or 'INTERIM REPORT' in title or 'ANNUAL REPORT' in title:
        return 'report'
    if label == 'share_buyback' or 'NEXT DAY DISCLOSURE' in title:
        return 'buyback'
    if label == 'share_scheme' or 'SHARE AWARD' in title or 'SHARE OPTION' in title:
        return 'scheme'
    return 'other'


def _hkex_card(row: pd.Series) -> str:
    published = row.get('published_at')
    published_txt = pd.Timestamp(published).strftime('%Y-%m-%d %H:%M UTC') if pd.notna(published) else 'date unavailable'
    headline = escape(_text(row.get('headline')) or 'headline unavailable')
    event_class = escape(_text(row.get('event_class')) or 'unclassified')
    url = _text(row.get('source_url'))
    link = f'<a class="ct-inline-link" href="{escape(url)}" target="_blank" rel="noopener">Open ↗</a>' if url else 'link unavailable'
    tone = _hkex_card_tone(row.get('event_class'), row.get('headline'))
    return (
        f'<div class="ct-thesis-card ct-news-card ct-news-card--{tone}">'
        f'<div class="ct-subtle">{escape(published_txt)} · hkexnews · {event_class}</div>'
        f'<div style="font-weight:700;margin:0.25rem 0;">{headline}</div>'
        f'<div class="ct-source-line">{link}</div>'
        '</div>'
    )


def _render_live_hkex_overlay(view: CompanyView) -> None:
    _render_section_heading(4, 'On-demand HKEXnews overlay (official metadata)', f'hkex-live-{_slugify(view.entity_id)}')
    st.caption('Official exchange announcements from a local live mart, not the published generation. Titles and PDF links only. Results stay on the first screen; daily buyback returns are grouped separately.')
    try:
        frame = load_local_hkex_overlay(
            entity_id=view.entity_id,
            listing_id=view.selected_listing_id,
            repo_root=_control_tower_repo_root(),
        )
    except (OSError, ValueError) as exc:
        st.error(f'HKEXnews overlay failed: {exc}')
        return
    if frame is None or frame.empty:
        st.info('No on-demand HKEXnews rows yet. Use Refresh news & filings on this company.')
        return
    work = frame.copy()
    work['_bucket'] = [
        _hkex_event_bucket(row.get('event_class'), row.get('headline'))
        for _, row in work.iterrows()
    ]
    sections = (
        ('priority', 'Results and material announcements'),
        ('reports', 'Interim / annual reports'),
        ('other', 'Other announcements'),
        ('routine', 'Routine capital-return filings'),
    )
    for bucket, title in sections:
        subset = work.loc[work['_bucket'].eq(bucket)]
        if subset.empty:
            continue
        st.caption(f'{title} · {len(subset)}')
        limit = 8 if bucket != 'routine' else 5
        st.markdown(''.join(_hkex_card(row) for _, row in subset.head(limit).iterrows()), unsafe_allow_html=True)
        if bucket == 'routine' and len(subset) > limit:
            with st.expander(f'{len(subset) - limit} older buyback / share-scheme filings'):
                st.markdown(''.join(_hkex_card(row) for _, row in subset.iloc[limit:].iterrows()), unsafe_allow_html=True)
    st.caption(f'{len(frame)} live HKEXnews rows for {escape(_text(view.display_name))}. The published official_filings table below is the frozen generation.')


def _render_local_news_overlay(view: CompanyView) -> None:
    remaining, scope = _refresh_cooldown_remaining(view.entity_id)
    cols = st.columns([1, 3])
    with cols[0]:
        clicked = st.button(
            'Refresh news & filings',
            key=f'ct_refresh_news_{_slugify(view.entity_id)}',
            type='primary',
            disabled=remaining > 0,
            help=(
                'Fetch latest HKEXnews plus Marketaux/Finnhub headlines for this company only. '
                '60s cooldown per company, 15s across companies.'
            ),
        )
    if clicked:
        _run_company_news_refresh(view)
        remaining, scope = _refresh_cooldown_remaining(view.entity_id)
    with cols[1]:
        if remaining > 0:
            st.caption(
                f'Cooldown {int(remaining) + 1}s ({scope}) · Marketaux free tier is 100 requests/day.'
            )
        else:
            st.caption('On-demand fetch for this company only. Does not rewrite the published generation. HKEX needs no key; Finnhub is US ADR only.')
    _render_refresh_status(view)
    _render_live_hkex_overlay(view)
    _render_section_heading(4, 'Vendor news overlay (not official filings)', f'vendor-news-{_slugify(view.entity_id)}')
    st.caption('Not official issuer disclosure. Marketaux and Finnhub metadata from local marts, resolved through the registry alias table. Article bodies are not stored. Finnhub free tier 403s HK symbols; Marketaux covers HK listings.')
    try:
        frame = load_local_news_overlay(
            entity_id=view.entity_id,
            listing_id=view.selected_listing_id,
            repo_root=_control_tower_repo_root(),
        )
    except (OSError, ValueError) as exc:
        st.error(f'Vendor news overlay failed: {exc}')
        return
    if frame is None or frame.empty:
        st.info('No locally collected vendor headlines currently resolve to this company.')
        return
    refresh_at = None
    payload = st.session_state.get('ct_news_refresh_result') or {}
    if payload.get('entity_id') == view.entity_id:
        refresh_at = pd.to_datetime(payload.get('fetched_at_utc'), errors='coerce', utc=True)
    cards = []
    for _, row in frame.head(12).iterrows():
        published = row.get('published_at')
        published_txt = pd.Timestamp(published).strftime('%Y-%m-%d %H:%M UTC') if pd.notna(published) else 'date unavailable'
        headline = escape(_text(row.get('headline')) or 'headline unavailable')
        source = escape(_text(row.get('source_id')) or 'source unavailable')
        publisher = escape(_text(row.get('publisher')) or 'publisher unavailable')
        url = _text(row.get('source_url'))
        link = f'<a class="ct-inline-link" href="{escape(url)}" target="_blank" rel="noopener">Open ↗</a>' if url else 'link unavailable'
        last_seen = pd.to_datetime(row.get('last_seen_at'), errors='coerce', utc=True)
        freshness = 'not in this refresh'
        if pd.notna(refresh_at) and pd.notna(last_seen) and last_seen >= refresh_at - pd.Timedelta(seconds=5):
            freshness = 'updated this refresh'
        elif pd.isna(refresh_at):
            freshness = 'cached overlay'
        tone = 'fresh' if freshness == 'updated this refresh' else 'stale'
        cards.append(
            f'<div class="ct-thesis-card ct-news-card ct-news-card--{tone}">'
            f'<div class="ct-subtle">{escape(published_txt)} · {source} · {publisher} · {escape(freshness)}</div>'
            f'<div style="font-weight:700;margin:0.25rem 0;">{headline}</div>'
            f'<div class="ct-source-line">{link}</div>'
            '</div>'
        )
    st.markdown(''.join(cards), unsafe_allow_html=True)
    st.caption(
        f'{len(frame)} resolved vendor headlines for {escape(_text(view.display_name))}. '
        'Finnhub rows on HK-only names are leftover title matches, not a HK feed. '
        'This is not the published news_filings.parquet table below.'
    )

def _render_evidence_tab(
    view: CompanyView,
    snapshot: ControlTowerSnapshot,
    viewer_timezone: str,
) -> None:
    _render_local_news_overlay(view)
    _render_section_heading(4, 'Provider-specific consensus', f'provider-consensus-{_slugify(view.entity_id)}')
    if view.consensus.empty:
        st.warning(f'Consensus unavailable · {view.consensus_status} · provider rows are not blended.')
    else:
        c_eps = view.consensus[view.consensus['metric'] == 'eps']
        c_rev = view.consensus[view.consensus['metric'] == 'revenue']
        if not c_eps.empty or not c_rev.empty:
            cols = st.columns(3)
            if not c_eps.empty:
                eps_val = c_eps.iloc[0]['value']
                eps_ccy = _text(c_eps.iloc[0].get('currency')) or 'HKD'
                eps_n = c_eps.iloc[0].get('analyst_count', '')
                cols[0].metric('Consensus EPS', f'{eps_ccy} {float(eps_val):.2f}' if pd.notna(eps_val) else 'Unavailable', f'{eps_n} analysts' if eps_n else '')
            if not c_rev.empty:
                rev_val = c_rev.iloc[0]['value']
                rev_ccy = _text(c_rev.iloc[0].get('currency')) or 'HKD'
                rev_n = c_rev.iloc[0].get('analyst_count', '')
                cols[1].metric('Consensus Revenue', f'{rev_ccy} {float(rev_val)/1e9:.1f}B' if pd.notna(rev_val) and float(rev_val) >= 1e9 else f'{rev_ccy} {float(rev_val):,.0f}', f'{rev_n} analysts' if rev_n else '')
            cols[2].metric('Provider Source', 'yfinance', 'Mean Consensus')
        ct_dataframe(_friendly_consensus_frame(view.consensus, viewer_timezone), width='stretch', hide_index=True)
    _render_section_heading(4, 'Consensus revisions', f'consensus-revisions-{_slugify(view.entity_id)}')
    if view.consensus_revisions.empty:
        st.info('Consensus revision history unavailable; no 0/0 breadth is shown.')
    else:
        rev_chart_data = _consensus_revision_chart_frame(view.consensus_revisions)
        if not rev_chart_data.empty:
            st.caption('Consensus EPS revision vs prior snapshot, grouped by lookback window. Values are percent change, not decimal points on a percent axis.')
            _render_plotly(
                _plotly_bar_chart(
                    rev_chart_data,
                    y_title='Revision (%)',
                    value_format='+.2f',
                    hover_suffix='%',
                    tickformat=None,
                    height=280,
                )
            )
        ct_dataframe(_friendly_revision_frame(view.consensus_revisions, viewer_timezone), width='stretch', hide_index=True)
    if not view.corporate_actions.empty:
        ca_df = view.corporate_actions.copy()
        ca_df['date'] = pd.to_datetime(ca_df['filing_date'], errors='coerce').dt.date
        ca_df = ca_df.dropna(subset=['date']).sort_values('date')
        if not ca_df.empty:
            plot = ca_df.copy()
            plot['usage_date'] = pd.to_datetime(plot['date'], errors='coerce')
            plot = plot.dropna(subset=['usage_date'])
            plot['daily_repurchase_hkd_m'] = pd.to_numeric(plot['total_amount_paid'], errors='coerce') / 1e6
            start = plot['usage_date'].min().strftime('%Y-%m-%d')
            end = plot['usage_date'].max().strftime('%Y-%m-%d')
            n_days = int(plot['usage_date'].nunique())
            st.caption(f'{n_days}-Day Statutory Repurchase Intensity (HK$ Millions per trading day · {start} to {end})')
            _render_plotly(
                _bar_chart_with_year_axis(
                    plot,
                    x='usage_date',
                    y='daily_repurchase_hkd_m',
                    y_title='Daily repurchase (HK$ millions)',
                    y_format=',.0f',
                )
            )
    render_official_filings(snapshot, entity_id=view.entity_id, listing_id=view.selected_listing_id, viewer_timezone=viewer_timezone)
    _render_section_heading(4, 'Published news/filing metadata (generation artifact)', f'news-filing-metadata-{_slugify(view.entity_id)}')
    if view.official_documents.empty:
        st.caption('This empty state is the published news_filings.parquet artifact, whose related_entity_ids are still blank. Vendor Marketaux/Finnhub headlines are in the overlay at the top of this tab, not this generation table.')
    else:
        ct_dataframe(_friendly_document_frame(view.official_documents, viewer_timezone), width='stretch', hide_index=True)
    _render_section_heading(4, 'Internal estimates & management guidance', f'internal-estimates-{_slugify(view.entity_id)}')
    if view.internal_estimates.empty:
        st.info('No internal estimates or management guidance registered for this entity.')
    else:
        listing_ids = view.internal_estimates.get('listing_id', pd.Series('', index=view.internal_estimates.index, dtype='string')).map(_text)
        listing_rows = view.internal_estimates.loc[listing_ids.ne('')]
        entity_rows = view.internal_estimates.loc[listing_ids.eq('')]
        if not listing_rows.empty:
            st.caption('Selected listing scope')
            ct_dataframe(_friendly_internal_estimates_frame(listing_rows, viewer_timezone), width='stretch', hide_index=True)
        if not entity_rows.empty:
            st.caption('Entity scope · listing-independent estimates; these rows are not assigned to any listing.')
            ct_dataframe(_friendly_internal_estimates_frame(entity_rows, viewer_timezone), width='stretch', hide_index=True)
    _render_section_heading(4, 'Claim-evidence matrix & conflict detection', f'claim-evidence-matrix-{_slugify(view.entity_id)}')
    if not view.claim_evidence_links.empty:
        ct_dataframe(_friendly_claim_evidence_links_frame(view.claim_evidence_links, view.evidence_items, viewer_timezone), width='stretch', hide_index=True)
    elif not view.invalidation_evidence.empty:
        ct_dataframe(_friendly_invalidation_frame(view.invalidation_evidence, viewer_timezone), width='stretch', hide_index=True)
    else:
        st.info('Invalidation evidence unavailable; support questions are not relabelled as falsification evidence.')
    with st.expander('Source and PIT caveats', expanded=False):
        for caveat in view.caveats:
            st.markdown(f'- {escape(_friendly_caveat(caveat))}')
        if not view.source_health.empty:
            ct_dataframe(view.source_health, width='stretch', hide_index=True)
        else:
            st.info('No company-relevant source-health rows are available.')


def render_company_page(
    snapshot: ControlTowerSnapshot,
    *,
    viewer_timezone: str,
    filters: EventFilters | None = None,
) -> CompanyView:
    entity_ids = _filtered_entity_ids(snapshot, filters)
    entity_options = sorted(entity_ids)
    if not entity_options:
        st.info('No company matches the active basket, country or membership filters.')
        raise ValueError('company registry is empty')
    query_entity = st.query_params.get('entity')
    session_entity = st.session_state.get('ct_company_entity')
    if session_entity not in entity_options:
        if query_entity in entity_options:
            st.session_state['ct_company_entity'] = query_entity
        else:
            st.session_state['ct_company_entity'] = 'TENCENT' if 'TENCENT' in entity_options else entity_options[0]
        st.session_state['ct_company_listing'] = None
    selected_entity = st.selectbox(
        'Company',
        entity_options,
        key='ct_company_entity',
        format_func=lambda value: _text(snapshot.entities.loc[snapshot.entities['entity_id'].astype('string').eq(value), 'display_name'].iloc[0]) if not snapshot.entities.loc[snapshot.entities['entity_id'].astype('string').eq(value)].empty else value,
    )
    if selected_entity != session_entity:
        st.session_state['ct_company_listing'] = None
    if st.query_params.get('entity') != selected_entity:
        st.query_params['entity'] = selected_entity
    as_of_point = snapshot.as_of_utc
    entity_row = snapshot.entities.loc[
        snapshot.entities['entity_id'].astype('string').eq(selected_entity)
    ].iloc[0] if not snapshot.entities.empty and snapshot.entities['entity_id'].astype('string').eq(selected_entity).any() else None
    if entity_row is not None and _market_entity_eligible(entity_row, as_of_point) and not snapshot.listings.empty:
        entity_listings = snapshot.listings.loc[
            snapshot.listings['entity_id'].astype('string').eq(selected_entity)
            & snapshot.listings.apply(lambda row: _market_listing_eligible(row, as_of_point), axis=1)
        ]
    else:
        entity_listings = snapshot.listings.iloc[0:0].copy()
    listing_options = [None] + sorted(entity_listings['listing_id'].astype('string')) if not entity_listings.empty else [None]
    if st.session_state.get('ct_company_listing') not in listing_options:
        st.session_state['ct_company_listing'] = None
    selected_listing = st.selectbox(
        'Listing',
        listing_options,
        key='ct_company_listing',
        format_func=lambda value: _format_listing_option(snapshot, value),
    )
    view = build_company_view(snapshot, entity_id=selected_entity, listing_id=selected_listing, filters=filters)
    _render_company_hero_card(view, snapshot, viewer_timezone)
    _render_section_heading(3, view.display_name, f'company-view-{_slugify(view.entity_id)}')
    entity_type_label = 'private / no listing' if view.entity_type == 'private' else 'public'
    st.caption(f'{escape(view.legal_name)} · {escape(view.country)} · {escape(view.sector or "sector unavailable")} · {escape(view.industry or "industry unavailable")} · {escape(entity_type_label)} · {escape(view.active_status or "status unavailable")}')
    if view.selected_listing_id:
        selection_mode = {'primary_default': 'primary listing default', 'explicit': 'selected listing'}.get(view.selection_mode, _text(view.selection_mode).replace('_', ' ') or 'selected listing')
        st.caption(f'Selected listing · {_format_listing_option(snapshot, view.selected_listing_id)} · {selection_mode}')
    else:
        st.warning('No verified primary listing is available; listing-specific data is unavailable.')
    tab_overview, tab_fundamentals, tab_alt, tab_thesis, tab_evidence = st.tabs(
        ['Overview', 'Fundamentals', 'Alternative Data', 'Thesis & Catalysts', 'Evidence']
    )
    with tab_overview:
        _render_overview_tab(view, snapshot, viewer_timezone)
    with tab_fundamentals:
        _render_fundamentals_tab(view, snapshot, viewer_timezone)
    with tab_alt:
        _render_alternative_data_tab(view)
    with tab_thesis:
        _render_thesis_catalysts_tab(view, snapshot, viewer_timezone)
    with tab_evidence:
        _render_evidence_tab(view, snapshot, viewer_timezone)
    return view


__all__ = [
    "CompanyView",
    "build_company_view",
    "render_company_page",
    "COMPANY_LISTING_COLUMNS",
    "COMPANY_MEMBERSHIP_COLUMNS",
    "COMPANY_EVENT_COLUMNS",
    "COMPANY_DOCUMENT_COLUMNS",
    "COMPANY_CONSENSUS_COLUMNS",
    "COMPANY_REVISION_COLUMNS",
    "COMPANY_QUOTE_COLUMNS",
    "COMPANY_QUESTION_COLUMNS",
    "COMPANY_INVALIDATION_COLUMNS",
    "COMPANY_CORPORATE_ACTION_COLUMNS",
    "COMPANY_VALUATION_COLUMNS",
    "COMPANY_INTERNAL_ESTIMATES_COLUMNS",
    "COMPANY_THESIS_CLAIM_COLUMNS",
    "COMPANY_THESIS_QUESTION_COLUMNS",
    "COMPANY_EVIDENCE_ITEM_COLUMNS",
    "COMPANY_CLAIM_EVIDENCE_LINK_COLUMNS",
]
