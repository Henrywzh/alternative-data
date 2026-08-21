"""Company identity, registry lineage, fundamental and thesis cockpit view."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from html import escape
import json
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import streamlit as st

from ..filters import apply_event_filters
from ..formatting import format_t_minus
from ..market_data import QUOTE_SNAPSHOT_COLUMNS, classify_quote_freshness, format_quote_age
from ..models import ControlTowerSnapshot, EventFilters
from ..components.filings_earnings import (
    render_official_filings,
    render_earnings_calendar,
    render_earnings_actuals,
    render_filings_earnings_sections,
)
from .source_health import classify_source_health


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
    return (
        _text(row.get("listing_status")).lower() == "active"
        and _text(row.get("mapping_status")).lower() == "verified"
        and _text(row.get("collection_eligible")).lower() in {"true", "1", "yes"}
        and _active(row, as_of)
    )


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
    roles: set[str] = set()
    has_raw_link = not entity_links.empty or not basket_links.empty
    for _, link in entity_links.iterrows():
        if not _link_active(link, event, snapshot.as_of_utc):
            continue
        target_type = _text(link.get("target_type")).lower()
        target_id = _text(link.get("target_id"))
        if target_type == "entity" and target_id == entity_id:
            roles.add("entity")
        elif target_type == "listing" and target_id in listing_ids:
            roles.add("listing")
    if roles:
        return "entity" if "entity" in roles else "listing"
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
    if has_raw_link:
        return None
    if entity_id in set(_ids(event.get("related_entity_ids"))):
        return "entity"
    if listing_ids.intersection(set(_ids(event.get("related_listing_ids")))):
        return "listing"
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
        verified = active_listings.loc[
            active_listings["mapping_status"].astype("string").str.lower().eq("verified")
            & active_listings["primary_listing"].map(
                lambda value: _text(value).lower() in {"true", "1", "yes"}
            )
            & active_listings["listing_status"].astype("string").str.lower().eq("active")
        ] if not active_listings.empty else active_listings
        if verified.empty:
            selected_listing_id = None
            selection_mode = "none"
        else:
            role_rank = {"primary": 0, "dual_primary": 1, "secondary": 2, "depositary_receipt": 3}
            exchange_rank = {"HKEX": 0, "NASDAQ": 1, "NYSE": 2, "LSE": 3}
            ranked = verified.copy()
            ranked["__role_rank"] = ranked["listing_role"].map(role_rank).fillna(99)
            ranked["__exchange_rank"] = ranked["exchange"].astype("string").str.upper().map(exchange_rank).fillna(99)
            ranked = ranked.sort_values(
                ["__role_rank", "__exchange_rank", "listing_id"],
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
    bar_listing_ids = {selected_listing_id} if selected_listing_id else listing_ids
    if bars_source is None or bars_source.empty or not bar_listing_ids:
        price_bars = pd.DataFrame(columns=["bar_date", "close", "adj_close", "volume", "listing_id", "currency", "source_id"])
    else:
        price_bars = bars_source.loc[
            bars_source["listing_id"].astype("string").isin(bar_listing_ids)
        ].copy()
        if not price_bars.empty:
            price_bars = price_bars.sort_values("bar_date")

    quote_source = snapshot.quote_snapshots
    quote_listing_ids = {selected_listing_id} if selected_listing_id else listing_ids
    if quote_source.empty or not quote_listing_ids:
        quote_snapshots = _empty(COMPANY_QUOTE_COLUMNS)
    else:
        quote_snapshots = quote_source.loc[
            quote_source["listing_id"].astype("string").isin(quote_listing_ids)
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

    consensus = snapshot.consensus_snapshots.loc[snapshot.consensus_snapshots["entity_id"].astype("string").eq(requested_entity)].copy() if not snapshot.consensus_snapshots.empty else snapshot.consensus_snapshots.copy()
    if listing_id is not None and not consensus.empty:
        consensus = consensus.loc[consensus["listing_id"].astype("string").eq(_text(listing_id))]
    consensus = consensus.loc[:, [column for column in COMPANY_CONSENSUS_COLUMNS if column in consensus.columns]].copy() if not consensus.empty else _empty(COMPANY_CONSENSUS_COLUMNS)
    for column in COMPANY_CONSENSUS_COLUMNS:
        if column not in consensus.columns:
            consensus[column] = pd.NA
    consensus = consensus.loc[:, COMPANY_CONSENSUS_COLUMNS]

    revisions = snapshot.consensus_revisions.loc[snapshot.consensus_revisions["entity_id"].astype("string").eq(requested_entity)].copy() if not snapshot.consensus_revisions.empty else snapshot.consensus_revisions.copy()
    if listing_id is not None and not revisions.empty:
        revisions = revisions.loc[revisions["listing_id"].astype("string").eq(_text(listing_id))]
    revisions = revisions.loc[:, [column for column in COMPANY_REVISION_COLUMNS if column in revisions.columns]].copy() if not revisions.empty else _empty(COMPANY_REVISION_COLUMNS)
    for column in COMPANY_REVISION_COLUMNS:
        if column not in revisions.columns:
            revisions[column] = pd.NA
    revisions = revisions.loc[:, COMPANY_REVISION_COLUMNS]

    # T1: Corporate actions (Statutory share repurchases / dividends)
    corp_actions_source = getattr(snapshot, "corporate_actions", pd.DataFrame())
    if corp_actions_source is not None and not corp_actions_source.empty:
        action_listing_ids = {selected_listing_id} if selected_listing_id else listing_ids
        if "listing_id" in corp_actions_source.columns and action_listing_ids:
            corp_actions = corp_actions_source.loc[
                corp_actions_source["listing_id"].astype("string").isin(action_listing_ids)
            ].copy()
        elif "entity_id" in corp_actions_source.columns:
            corp_actions = corp_actions_source.loc[
                corp_actions_source["entity_id"].astype("string").eq(requested_entity)
            ].copy()
        else:
            corp_actions = corp_actions_source.copy()
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
        val_listing_ids = {selected_listing_id} if selected_listing_id else listing_ids
        if "listing_id" in valuation_source.columns and val_listing_ids:
            val_snapshots = valuation_source.loc[
                valuation_source["listing_id"].astype("string").isin(val_listing_ids)
            ].copy()
        elif "entity_id" in valuation_source.columns:
            val_snapshots = valuation_source.loc[
                valuation_source["entity_id"].astype("string").eq(requested_entity)
            ].copy()
        else:
            val_snapshots = valuation_source.copy()
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
        if "entity_id" in internal_est_source.columns:
            internal_est = internal_est_source.loc[
                internal_est_source["entity_id"].astype("string").eq(requested_entity)
            ].copy()
        else:
            internal_est = internal_est_source.copy()
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
        quote_snapshots=quote_snapshots,
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
    except Exception:
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


def _company_earnings_actuals(
    snapshot: ControlTowerSnapshot,
    view: CompanyView,
) -> pd.DataFrame:
    """Return earnings rows scoped to the selected entity and listing."""

    source = getattr(snapshot, "earnings_actuals", pd.DataFrame())
    if source is None or source.empty or "entity_id" not in source.columns:
        return pd.DataFrame()
    frame = source.loc[source["entity_id"].astype("string").eq(view.entity_id)].copy()
    if view.selected_listing_id and "listing_id" in frame.columns:
        listing = frame["listing_id"]
        frame = frame.loc[
            listing.isna()
            | listing.astype("string").eq("")
            | listing.astype("string").eq(view.selected_listing_id)
        ]
    return frame


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

    upcoming = view.events.copy()
    if not upcoming.empty and "starts_at" in upcoming.columns:
        starts_at = pd.to_datetime(upcoming["starts_at"], errors="coerce", utc=True)
        upcoming = upcoming.loc[starts_at.ge(snapshot.now_utc)].copy()
        if not upcoming.empty:
            upcoming = upcoming.assign(_summary_starts_at=starts_at.loc[upcoming.index])
            upcoming = upcoming.sort_values("_summary_starts_at", na_position="last")
    if upcoming.empty:
        lines.append("Upcoming catalyst unavailable · no future linked event rows.")
    else:
        event = upcoming.iloc[0]
        lines.append(
            f"Upcoming catalyst · {_text(event.get('title')) or 'title unavailable'} · "
            f"{_summary_date(event.get('starts_at')) or 'date unavailable'} · "
            f"{_text(event.get('certainty_class')).replace('_', ' ') or 'certainty unavailable'} · "
            f"{_text(event.get('date_precision')) or 'precision unavailable'} · "
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


def _render_answer_first_summary(
    view: CompanyView,
    snapshot: ControlTowerSnapshot,
) -> None:
    listing_label = ""
    if view.selected_listing_id and not view.listings.empty:
        selected = view.listings.loc[
            view.listings["listing_id"].astype("string").eq(view.selected_listing_id)
        ]
        if not selected.empty:
            listing_label = _text(selected.iloc[0].get("canonical_ticker"))
    heading = " · ".join(
        value
        for value in ("Executive summary & recent changes", view.display_name, listing_label)
        if value
    )
    st.markdown(f"#### {escape(heading)}")
    for line in _answer_first_summary_lines(view, snapshot):
        st.markdown(f"- {escape(line)}")
    st.caption(
        "All displayed facts come from the selected local snapshot rows; unavailable marts stay unavailable."
    )


def _render_price_history(view: CompanyView, snapshot: ControlTowerSnapshot) -> None:
    """Daily close for the selected listing, with its provenance stated."""

    st.markdown("#### Price history")
    if view.entity_type == "private":
        st.info(
            f"Not applicable · {_text(view.display_name)} is a private company with no public listing; "
            "no price history is collected."
        )
        return
    bars = view.price_bars
    if bars is None or bars.empty:
        st.warning(
            "Price history unavailable · no price-bar rows for the selected listing; "
            "the app remains no-network/read-only and did not query a provider."
        )
        return

    frame = bars.copy()
    frame["bar_date"] = pd.to_datetime(frame["bar_date"], errors="coerce")
    frame = frame.loc[frame["bar_date"].notna()]
    adjusted = frame["adj_close"].notna().any() if "adj_close" in frame.columns else False
    series_column = "adj_close" if adjusted else "close"
    basis = "adjusted close" if adjusted else "unadjusted close"
    frame = frame.loc[frame[series_column].notna()]
    if frame.empty:
        st.warning("Price history unavailable · rows carry no usable close price.")
        return

    currency = _text(frame.iloc[-1].get("currency")) or ""
    chart = frame.set_index("bar_date")[[series_column]].rename(columns={series_column: f"{currency} {basis}".strip()})
    st.line_chart(chart, height=260)

    first = frame["bar_date"].min().date()
    last = frame["bar_date"].max().date()
    sources = ", ".join(sorted({_text(v) for v in frame["source_id"] if _text(v)}))
    span_days = (last - first).days
    st.caption(
        f"{len(frame):,} daily bars · {first} to {last} ({span_days} calendar days) · {basis} · "
        f"source: {sources or 'unattributed'} · read from the published artifact, no provider was queried"
    )


def _render_overview_tab(
    view: CompanyView,
    snapshot: ControlTowerSnapshot,
    viewer_timezone: str,
) -> None:
    """Tab 1: Overview - Answer-first summary, quote, price history, listings, memberships, flight deck."""

    # 1. Answer-first summary from the selected snapshot rows
    _render_answer_first_summary(view, snapshot)

    # 2. Latest market quote
    st.markdown("#### Latest market quote")
    if view.entity_type == "private":
        st.info(
            f"Not applicable · {_text(view.display_name)} is a private company with no public market listing; "
            "price, quote, and market data collection are excluded."
        )
    elif view.quote_snapshots.empty:
        st.warning(
            "Latest quote unavailable · no quote snapshot artifact or selected-listing row; "
            "the app remains no-network/read-only and did not query a provider."
        )
    else:
        for _, qrow in view.quote_snapshots.iterrows():
            last_price = qrow.get("last_price")
            currency = _text(qrow.get("currency")) or ""
            price_str = f"{currency} {last_price:,.2f}".strip() if pd.notna(last_price) else "Unavailable"

            day_change = qrow.get("day_change_pct")
            if pd.notna(day_change) and isinstance(day_change, (int, float)):
                change_str = f"{day_change:+.2f}%"
            else:
                change_str = "Day change unavailable"

            qtime = qrow.get("quote_timestamp")
            age_str = format_quote_age(qtime, snapshot.now_utc)
            freshness = _text(qrow.get("freshness")) or "delayed"
            latency = _text(qrow.get("latency_class")) or "delayed"
            source_id = _text(qrow.get("source_id")) or "market:yfinance"
            source_url = _text(qrow.get("source_url"))

            source_label = f"{source_id} ({latency})"
            if source_url.startswith(("http://", "https://")):
                source_link_html = f'<a class="ct-inline-link" href="{escape(source_url)}" target="_blank" rel="noopener">{escape(source_label)}</a>'
            else:
                source_link_html = escape(source_label)

            summary_html = (
                f'<div class="ct-change" style="margin-bottom: 0.75rem;">'
                f'<div class="ct-change-title"><strong>{escape(price_str)}</strong> · {escape(change_str)}</div>'
                f'<div class="ct-change-detail">Quote age: {escape(age_str)} · Freshness: {escape(freshness)}</div>'
                f'<div class="ct-source-line">Source: {source_link_html} · Delayed market data (no real-time claim)</div>'
                f'</div>'
            )
            st.markdown(summary_html, unsafe_allow_html=True)

        st.dataframe(
            _friendly_quote_frame(view.quote_snapshots, viewer_timezone),
            width="stretch",
            hide_index=True,
        )

    # 3. Price history
    _render_price_history(view, snapshot)

    # 4. Listings
    st.markdown("#### Listings")
    st.dataframe(_friendly_listing_frame(view.listings), width="stretch", hide_index=True)

    # 5. Basket and layer memberships
    st.markdown("#### Basket and layer memberships")
    st.dataframe(view.memberships, width="stretch", hide_index=True)

    # 6. Flight deck summary
    st.markdown("#### Flight deck & catalyst overview")
    upcoming_events_count = len(view.events)
    thesis_claims_count = len(view.thesis_claims)
    watch_q_count = len(view.thesis_watch_questions) if not view.thesis_watch_questions.empty else len(view.watch_questions)
    corporate_action_count = len(view.corporate_actions)

    cols = st.columns(4)
    cols[0].metric("Linked Events", str(upcoming_events_count))
    cols[1].metric("Thesis Claims", str(thesis_claims_count))
    cols[2].metric("Watch Questions", str(watch_q_count))
    cols[3].metric("Corporate Actions", str(corporate_action_count))


def _render_fundamentals_tab(
    view: CompanyView,
    snapshot: ControlTowerSnapshot,
    viewer_timezone: str,
) -> None:
    """Tab 2: Fundamentals - Segments, GAAP vs Non-IFRS dual track, FCF bridge, Buybacks, Valuation."""

    # 1. Segment disclosures & core financial actuals
    st.markdown("#### Segment disclosures & core operations")
    frame = _company_earnings_actuals(snapshot, view)
    if frame.empty:
        st.info(
            "No earnings-actuals rows for this entity/listing in the current snapshot; "
            "values are only shown from official issuer disclosure metadata."
        )
    else:
        metrics = frame.get("metric", pd.Series("", index=frame.index, dtype="string")).astype("string")
        has_segments = metrics.str.startswith("revenue_") & ~metrics.eq("revenue_total")
        if has_segments.any():
            st.caption("Official segment revenue rows extracted from issuer disclosures.")

        sorted_actuals = frame.sort_values(["period_end", "metric", "version"], ascending=False)
        actuals_display_columns = (
            "period_label", "metric", "reported_value", "normalized_value", "currency",
            "unit", "accounting_basis", "filing_at", "version", "is_restatement",
            "revision_reason", "source_url",
        )
        keep_cols = [c for c in actuals_display_columns if c in sorted_actuals.columns]
        friendly_actuals = sorted_actuals.loc[:, keep_cols].rename(
            columns={
                "period_label": "Period",
                "metric": "Metric",
                "reported_value": "Reported",
                "normalized_value": "Normalized",
                "currency": "Currency",
                "unit": "Unit",
                "accounting_basis": "Basis",
                "filing_at": "Filing date",
                "version": "Version",
                "is_restatement": "Restatement",
                "revision_reason": "Revision reason",
                "source_url": "Source link",
            }
        )
        st.dataframe(friendly_actuals, width="stretch", hide_index=True)
        latest = sorted_actuals["period_end"].dropna()
        if not latest.empty:
            latest_label = _text(sorted_actuals.loc[sorted_actuals["period_end"].eq(latest.max()), "period_label"].iloc[0])
            st.caption(f"Latest reported period in snapshot: {escape(latest_label) if latest_label else latest.max().strftime('%Y-%m-%d')} · reported values preserved per filing; restatements are versioned, not overwritten.")

    # 2. Official Earnings Calendar
    render_earnings_calendar(snapshot, entity_id=view.entity_id, listing_id=view.selected_listing_id)

    # 3. Profitability & Free Cash Flow trajectory
    st.markdown("#### Profitability & Free Cash Flow trajectory")
    trajectory = _latest_actual_rows(frame)
    if not trajectory.empty:
        metric_names = trajectory.get(
            "metric", pd.Series("", index=trajectory.index, dtype="string")
        ).astype("string").str.lower()
        trajectory = trajectory.loc[
            metric_names.str.contains(
                r"free_cash_flow|cash_flow|prepayment|capital_expenditure|capex|operating_margin|operating_profit",
                regex=True,
                na=False,
            )
        ]
    if trajectory.empty:
        st.info(
            "Profitability and Free Cash Flow metrics unavailable · no matching "
            "earnings-actuals rows for the latest reported period."
        )
    else:
        display_columns = [
            column
            for column in (
                "period_label", "metric", "reported_value", "normalized_value",
                "currency", "unit", "accounting_basis", "filing_at", "source_id",
                "source_url", "pit_class",
            )
            if column in trajectory.columns
        ]
        st.dataframe(
            trajectory.loc[:, display_columns].rename(
                columns={
                    "period_label": "Period",
                    "metric": "Metric",
                    "reported_value": "Reported",
                    "normalized_value": "Normalized",
                    "currency": "Currency",
                    "unit": "Unit",
                    "accounting_basis": "Basis",
                    "filing_at": "Filing date",
                    "source_id": "Source",
                    "source_url": "Source link",
                    "pit_class": "PIT class",
                }
            ),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "Reported and normalized values remain distinct and retain their row-level provenance."
        )

    # 4. Statutory capital returns and corporate actions
    st.markdown("#### Statutory capital returns & corporate actions")
    if view.corporate_actions.empty:
        st.info("No statutory corporate-action rows for the selected listing in the current snapshot.")
    else:
        total_spent = view.corporate_actions["total_amount_paid"].dropna().sum() if "total_amount_paid" in view.corporate_actions.columns else 0.0
        total_shares = view.corporate_actions["shares_affected"].dropna().sum() if "shares_affected" in view.corporate_actions.columns else 0
        ccy = _text(view.corporate_actions.iloc[0].get("currency"))

        mcols = st.columns(3)
        mcols[0].metric(
            "Total Consideration",
            f"{ccy} {total_spent:,.2f}".strip() if total_spent and ccy else "Unavailable",
        )
        mcols[1].metric("Shares Repurchased", f"{int(total_shares):,}" if total_shares else "Unavailable")
        mcols[2].metric("Corporate Action Rows", f"{len(view.corporate_actions):,}")

        st.dataframe(
            _friendly_corporate_actions_frame(view.corporate_actions, viewer_timezone),
            width="stretch",
            hide_index=True,
        )

    # 5. Valuation Multiples & Yields Context
    st.markdown("#### Valuation multiples & return yields")
    if view.valuation_snapshots.empty:
        st.warning(
            "Valuation multiples unavailable · requires contemporaneous quote, share count, and basis-verified forward consensus."
        )
    else:
        st.dataframe(_friendly_valuation_frame(view.valuation_snapshots), width="stretch", hide_index=True)
        st.caption(
            "percentile_history_status: unavailable · Historical denominator vintages are absent; "
            "reconstructing synthetic historical percentiles from current-vintage statements is strictly forbidden by policy."
        )


def _render_thesis_catalysts_tab(
    view: CompanyView,
    snapshot: ControlTowerSnapshot,
    viewer_timezone: str,
) -> None:
    """Tab 3: Thesis & Catalysts - Human-authored thesis claims, catalyst roadmap, and falsification questions."""

    # 1. Active Investment Thesis Claims
    st.markdown("#### Thesis claims (Human-authored)")
    if view.thesis_claims.empty:
        st.info("No human-authored thesis claims registered for this entity.")
    else:
        for _, row in view.thesis_claims.iterrows():
            title = _text(row.get("thesis_title")) or _text(row.get("claim_id"))
            status = _text(row.get("status")).upper() or "STATUS UNAVAILABLE"
            claim_text = _text(row.get("claim_text"))
            rule = _text(row.get("invalidation_rule"))
            reviewed_by = _text(row.get("reviewed_by")) or "Not recorded"
            reviewed_at = _format_time(row.get("last_reviewed_at_utc"), viewer_timezone) if _text(row.get("last_reviewed_at_utc")) else "Not recorded"

            status_badge_style = "var(--ct-warning)" if status == "DRAFT" else "var(--ct-accent)"
            card_html = (
                f'<div class="ct-panel" style="margin-bottom: 0.85rem;">'
                f'<div class="ct-panel-heading">'
                f'<h3 style="font-size: 0.98rem; font-weight: 750;">{escape(title)}</h3>'
                f'<span class="ct-badge" style="color: {status_badge_style}; border-color: {status_badge_style};">[{escape(status)}]</span>'
                f'</div>'
                f'<div class="ct-subtle" style="margin-bottom: 0.45rem;">Human-authored thesis · status: <strong>{escape(status.lower())}</strong> (never automatically promoted to active or mutated by AI)</div>'
                f'<div style="font-size: 0.88rem; line-height: 1.45; color: var(--ct-ink); margin-bottom: 0.55rem;">{escape(claim_text)}</div>'
                f'<div class="ct-alert-strip" style="margin: 0.4rem 0;"><strong>Invalidation Rule:</strong> {escape(rule)}</div>'
                f'<div class="ct-source-line">Reviewed by: {escape(reviewed_by)} · Last reviewed: {escape(reviewed_at)}</div>'
                f'</div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)

    # 2. Upcoming Catalysts & Event Roadmap
    st.markdown("#### Upcoming catalysts & event roadmap")
    if view.events.empty:
        st.info("No explicitly linked events are available for this company.")
    else:
        for _, row in view.events.iterrows():
            source_link = "source link available" if _text(row.get("source_url")).startswith(("http://", "https://")) else "source link unavailable"
            certainty = _text(row.get("certainty_class")).replace("_", " ")
            precision = _text(row.get("date_precision")) or "day"
            starts_at_str = _format_time(row.get("starts_at"), viewer_timezone)
            t_minus = format_t_minus(row.get("starts_at"), viewer_timezone, snapshot.now_utc)

            st.markdown(
                f"**{escape(_text(row.get('title')))}** · {escape(_text(row.get('relation_role')))} · "
                f"*{escape(certainty)}* · `{escape(precision)}` · {starts_at_str} ({t_minus}) · "
                f"{escape(source_link)}"
            )
        with st.expander("Event lineage details", expanded=False):
            st.dataframe(view.events, width="stretch", hide_index=True)

    # 3. Operational Watch Questions & Falsification Checklist
    st.markdown("#### Operational watch questions & falsification criteria")
    if not view.thesis_watch_questions.empty:
        st.dataframe(_friendly_thesis_questions_frame(view.thesis_watch_questions), width="stretch", hide_index=True)
    elif not view.watch_questions.empty:
        st.dataframe(_friendly_question_frame(view.watch_questions), width="stretch", hide_index=True)
    else:
        st.info("No watch questions are registered.")


def _render_evidence_tab(
    view: CompanyView,
    snapshot: ControlTowerSnapshot,
    viewer_timezone: str,
) -> None:
    """Tab 4: Evidence - Lineage feed, filings, consensus revisions, internal estimates, claim-evidence matrix."""

    # 1. Official Filings & Regulatory Announcements Metadata
    render_official_filings(snapshot, entity_id=view.entity_id, listing_id=view.selected_listing_id, viewer_timezone=viewer_timezone)

    # 2. News and Filing Metadata
    st.markdown("#### News and filing metadata")
    if view.official_documents.empty:
        st.warning("Official documents unavailable — no local metadata export; no document body displayed.")
    else:
        st.dataframe(_friendly_document_frame(view.official_documents, viewer_timezone), width="stretch", hide_index=True)

    # 3. Provider-Specific Consensus Snapshots
    st.markdown("#### Provider-specific consensus")
    if view.consensus.empty:
        st.warning(f"Consensus unavailable · {view.consensus_status} · provider rows are not blended.")
    else:
        st.dataframe(_friendly_consensus_frame(view.consensus, viewer_timezone), width="stretch", hide_index=True)

    # 4. Consensus Revisions & Trajectory
    st.markdown("#### Consensus revisions")
    if view.consensus_revisions.empty:
        st.info("Consensus revision history unavailable; no 0/0 breadth is shown.")
    else:
        st.dataframe(_friendly_revision_frame(view.consensus_revisions, viewer_timezone), width="stretch", hide_index=True)

    # 5. Internal Estimates & Management Guidance
    st.markdown("#### Internal estimates & management guidance")
    if view.internal_estimates.empty:
        st.info("No internal estimates or management guidance registered for this entity.")
    else:
        st.dataframe(_friendly_internal_estimates_frame(view.internal_estimates, viewer_timezone), width="stretch", hide_index=True)

    # 6. Claim-Evidence Matrix & Invalidation Conflict Hints
    st.markdown("#### Claim-evidence matrix & conflict detection")
    if not view.claim_evidence_links.empty:
        st.dataframe(
            _friendly_claim_evidence_links_frame(view.claim_evidence_links, view.evidence_items, viewer_timezone),
            width="stretch",
            hide_index=True,
        )
    elif not view.invalidation_evidence.empty:
        st.dataframe(_friendly_invalidation_frame(view.invalidation_evidence, viewer_timezone), width="stretch", hide_index=True)
    else:
        st.info("Invalidation evidence unavailable; support questions are not relabelled as falsification evidence.")

    # 7. Source Health & PIT Caveats
    with st.expander("Source and PIT caveats", expanded=False):
        for caveat in view.caveats:
            st.markdown(f"- {escape(_friendly_caveat(caveat))}")
        if not view.source_health.empty:
            st.dataframe(view.source_health, width="stretch", hide_index=True)
        else:
            st.info("No company-relevant source-health rows are available.")


def render_company_page(
    snapshot: ControlTowerSnapshot,
    *,
    viewer_timezone: str,
    filters: EventFilters | None = None,
) -> CompanyView:
    """Render a four-tab company fundamental and thesis cockpit, never document bodies."""

    entity_ids = _filtered_entity_ids(snapshot, filters)
    entity_options = sorted(entity_ids)
    if not entity_options:
        st.info("No company matches the active basket, country or membership filters.")
        raise ValueError("company registry is empty")
    if st.session_state.get("ct_company_entity") not in entity_options:
        st.session_state["ct_company_entity"] = entity_options[0]
    selected_entity = st.selectbox(
        "Company",
        entity_options,
        key="ct_company_entity",
        format_func=lambda value: _text(snapshot.entities.loc[snapshot.entities["entity_id"].astype("string").eq(value), "display_name"].iloc[0]) if not snapshot.entities.loc[snapshot.entities["entity_id"].astype("string").eq(value)].empty else value,
    )
    as_of_point = snapshot.as_of_utc
    entity_row = snapshot.entities.loc[
        snapshot.entities["entity_id"].astype("string").eq(selected_entity)
    ].iloc[0] if not snapshot.entities.empty and snapshot.entities["entity_id"].astype("string").eq(selected_entity).any() else None
    if entity_row is not None and _market_entity_eligible(entity_row, as_of_point) and not snapshot.listings.empty:
        entity_listings = snapshot.listings.loc[
            snapshot.listings["entity_id"].astype("string").eq(selected_entity)
            & snapshot.listings.apply(lambda row: _market_listing_eligible(row, as_of_point), axis=1)
        ]
    else:
        entity_listings = snapshot.listings.iloc[0:0].copy()
    listing_options = [None] + sorted(entity_listings["listing_id"].astype("string")) if not entity_listings.empty else [None]
    if st.session_state.get("ct_company_listing") not in listing_options:
        st.session_state["ct_company_listing"] = None
    selected_listing = st.selectbox(
        "Listing",
        listing_options,
        key="ct_company_listing",
        format_func=lambda value: _format_listing_option(snapshot, value),
    )
    view = build_company_view(snapshot, entity_id=selected_entity, listing_id=selected_listing, filters=filters)
    st.markdown(f"### {escape(view.display_name)}")
    entity_type_label = "private / no listing" if view.entity_type == "private" else "public"
    st.caption(f"{escape(view.legal_name)} · {escape(view.country)} · {escape(view.sector or 'sector unavailable')} · {escape(view.industry or 'industry unavailable')} · {escape(entity_type_label)} · {escape(view.active_status or 'status unavailable')}")
    if view.selected_listing_id:
        selection_mode = {
            "primary_default": "primary listing default",
            "explicit": "selected listing",
        }.get(view.selection_mode, _text(view.selection_mode).replace("_", " ") or "selected listing")
        st.caption(
            f"Selected listing · {_format_listing_option(snapshot, view.selected_listing_id)} · {selection_mode}"
        )
    else:
        st.warning("No verified primary listing is available; listing-specific data is unavailable.")

    tab_overview, tab_fundamentals, tab_thesis, tab_evidence = st.tabs(
        ["Overview", "Fundamentals", "Thesis & Catalysts", "Evidence"]
    )

    with tab_overview:
        _render_overview_tab(view, snapshot, viewer_timezone)

    with tab_fundamentals:
        _render_fundamentals_tab(view, snapshot, viewer_timezone)

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
