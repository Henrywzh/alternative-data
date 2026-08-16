"""Company identity, registry lineage and provider-specific evidence view."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from html import escape
import json
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import streamlit as st

from ..filters import apply_event_filters
from ..market_data import QUOTE_SNAPSHOT_COLUMNS, classify_quote_freshness, format_quote_age
from ..models import ControlTowerSnapshot, EventFilters
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
    events: pd.DataFrame
    official_documents: pd.DataFrame
    consensus: pd.DataFrame
    consensus_revisions: pd.DataFrame
    consensus_status: str
    source_health: pd.DataFrame
    watch_questions: pd.DataFrame
    invalidation_evidence: pd.DataFrame
    caveats: tuple[str, ...]


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
        "prior_snapshot_at", "prior_provider_asof",
        "quote_timestamp",
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
    # Task 5 may already have enriched the event relation columns. They are an
    # explicit fallback only when the split link frames have no row for this
    # event; inactive raw links must not be revived by enrichment.
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
    active_listings = all_entity_listings.loc[all_entity_listings.apply(lambda row: _active(row, as_of), axis=1)].copy() if not all_entity_listings.empty else all_entity_listings.copy()
    listing_ids = set(active_listings["listing_id"].astype("string")) if not active_listings.empty else set()
    if listing_id is not None:
        requested_listing = _text(listing_id)
        if requested_listing not in set(all_entity_listings.get("listing_id", pd.Series(dtype="string"))):
            raise ValueError(f"listing_id {listing_id!r} does not belong to entity {requested_entity!r}")
        selected_listing_id = requested_listing
        selection_mode = "explicit"
    else:
        verified = active_listings.loc[
            active_listings["mapping_status"].astype("string").str.lower().eq("verified")
            & active_listings["primary_listing"].fillna(False).astype(bool)
            & active_listings["listing_status"].astype("string").str.lower().eq("active")
        ] if not active_listings.empty else active_listings
        if verified.empty:
            selected_listing_id = None
            selection_mode = "none"
        else:
            selected_listing_id = sorted(verified["listing_id"].astype("string"))[0]
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

    quote_source = snapshot.quote_snapshots
    quote_listing_ids = {selected_listing_id} if selected_listing_id else listing_ids
    if quote_source.empty or not quote_listing_ids:
        quote_snapshots = _empty(COMPANY_QUOTE_COLUMNS)
    else:
        quote_snapshots = quote_source.loc[
            quote_source["listing_id"].astype("string").isin(quote_listing_ids)
        ].copy()
        if filters is not None and filters.scope and "company" not in filters.scope:
            quote_snapshots = quote_snapshots.iloc[0:0].copy()
        if quote_snapshots.empty:
            quote_snapshots = _empty(COMPANY_QUOTE_COLUMNS)
        else:
            quote_snapshots["freshness"] = quote_snapshots.apply(
                lambda row: classify_quote_freshness(
                    row.get("quote_timestamp"),
                    snapshot.now_utc,
                    row.get("latency_class"),
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
    quote_status = "available" if not quote_snapshots.empty else "unavailable"

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

    if filters is not None and filters.scope and "company" not in filters.scope:
        official_documents = _empty(COMPANY_DOCUMENT_COLUMNS)
        consensus = _empty(COMPANY_CONSENSUS_COLUMNS)
        revisions = _empty(COMPANY_REVISION_COLUMNS)

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
        "fnguide|futu|yfinance|akshare|provider:|dart|krx|official|ir|research",
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
    bad_source_statuses = {"failed", "conflicted", "review_required", "entitlement_error", "unavailable", "degraded", "stale", "clock_skew"}
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


def render_company_page(
    snapshot: ControlTowerSnapshot,
    *,
    viewer_timezone: str,
    filters: EventFilters | None = None,
) -> CompanyView:
    """Render company identity and metadata, never document/article bodies."""

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
    entity_listings = snapshot.listings.loc[snapshot.listings["entity_id"].astype("string").eq(selected_entity)] if not snapshot.listings.empty else snapshot.listings
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
    st.markdown("#### Listings")
    st.dataframe(_friendly_listing_frame(view.listings), width="stretch", hide_index=True)
    st.markdown("#### Basket and layer memberships")
    st.dataframe(view.memberships, width="stretch", hide_index=True)
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
    st.markdown("#### Events and evidence lineage")
    if view.events.empty:
        st.info("No explicitly linked events are available for this company.")
    else:
        for _, row in view.events.iterrows():
            source_link = "source link available" if _text(row.get("source_url")).startswith(("http://", "https://")) else "source link unavailable"
            st.markdown(
                f"**{escape(_text(row.get('title')))}** · {escape(_text(row.get('relation_role')))} · "
                f"{escape(_text(row.get('certainty_class')).replace('_', ' '))} · {_format_time(row.get('starts_at'), viewer_timezone)} · "
                f"{escape(source_link)}"
            )
        with st.expander("Event lineage details", expanded=False):
            st.dataframe(view.events, width="stretch", hide_index=True)
    st.markdown("#### Provider-specific consensus")
    if view.consensus.empty:
        st.warning(f"Consensus unavailable · {view.consensus_status} · provider rows are not blended.")
    else:
        st.dataframe(_friendly_consensus_frame(view.consensus, viewer_timezone), width="stretch", hide_index=True)
    st.markdown("#### Consensus revisions")
    if view.consensus_revisions.empty:
        st.info("Consensus revision history unavailable; no 0/0 breadth is shown.")
    else:
        st.dataframe(_friendly_revision_frame(view.consensus_revisions, viewer_timezone), width="stretch", hide_index=True)
    st.markdown("#### Official filings and news metadata")
    if view.official_documents.empty:
        st.warning("Official documents unavailable — no local metadata export; no document body displayed.")
    else:
        st.dataframe(_friendly_document_frame(view.official_documents, viewer_timezone), width="stretch", hide_index=True)
    st.markdown("#### Watch questions")
    if view.watch_questions.empty:
        st.info("No watch questions are registered.")
    else:
        st.dataframe(_friendly_question_frame(view.watch_questions), width="stretch", hide_index=True)
    st.markdown("#### Invalidation evidence")
    if view.invalidation_evidence.empty:
        st.info("Invalidation evidence unavailable; support questions are not relabelled as falsification evidence.")
    else:
        st.dataframe(_friendly_invalidation_frame(view.invalidation_evidence, viewer_timezone), width="stretch", hide_index=True)
    with st.expander("Source and PIT caveats", expanded=False):
        for caveat in view.caveats:
            st.markdown(f"- {escape(_friendly_caveat(caveat))}")
        if not view.source_health.empty:
            st.dataframe(view.source_health, width="stretch", hide_index=True)
        else:
            st.info("No company-relevant source-health rows are available.")
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
]
