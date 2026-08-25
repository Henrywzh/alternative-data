"""AI Bottlenecks theme view: registry relationships plus evidence metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from html import escape
import json
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import streamlit as st

from ..components import ct_dataframe
from ..components.flight_deck import build_flight_deck, render_flight_deck
from ..models import ControlTowerSnapshot, EventFilters
from .source_health import classify_source_health


AI_BASKET_ID = "AI_BOTTLENECKS_GLOBAL"

LAYER_LABELS = {
    "accelerators_custom_silicon": "Accelerators & custom silicon",
    "hbm_memory": "HBM & memory",
    "foundry": "Foundry",
    "advanced_packaging_test": "Advanced packaging & test",
    "semiconductor_equipment_materials": "Semiconductor equipment & materials",
    "substrates_pcbs": "Substrates & PCBs",
    "optical_networking": "Optical & networking",
    "server_systems": "Server ODM & systems",
    "rack_power_cooling": "Rack power & cooling",
    "grid_energy": "Grid & energy",
    "hyperscaler_demand": "Hyperscaler demand",
}
_LAYER_ALIASES = {
    **{key: key for key in LAYER_LABELS},
    **{label.casefold(): key for key, label in LAYER_LABELS.items()},
    "hbm_memory": "hbm_memory",
    "hbm memory": "hbm_memory",
    "hbm & memory": "hbm_memory",
    "hbm_memory": "hbm_memory",
    "ai_bottlenecks_global": "__basket__",
}

THEME_MEMBER_COLUMNS = (
    "entity_id", "display_name", "country", "basket_id", "membership_tier",
    "primary_layer", "secondary_layers", "member_role", "listing_ids",
    "verified_listing_ids", "collection_eligible", "latest_evidence_at",
    "evidence_count", "evidence_status", "consensus_status",
)
THEME_EVIDENCE_COLUMNS = (
    "change_id", "changed_at", "change_kind", "event_id", "entity_id", "source_id",
    "title", "description", "certainty_class", "confidence", "evidence_class",
    "source_url", "pit_class", "source_license_class", "display_status", "detail",
)
THEME_CATALYST_COLUMNS = (
    "event_id", "event_key", "event_type", "title", "scope", "status", "certainty_class",
    "confidence", "date_precision", "starts_at", "ends_at", "source_timezone", "source_id",
    "source_url", "first_observed_at", "last_verified_at", "supersedes_event_id",
    "related_entity_ids", "related_listing_ids", "related_basket_ids", "watch_question_count",
    "latest_observation", "source_health_status", "source_link_status", "pit_class",
    "source_license_class", "display_status",
)
THEME_RELATIONSHIP_COLUMNS = (
    "relationship_id", "basket_id", "entity_id", "entity_display_name", "primary_layer",
    "secondary_layer", "membership_tier", "relationship_type", "relationship_basis",
    "source_or_research_note",
)
THEME_SOURCE_COLUMNS = (
    "source_id", "source_kind", "status", "display_status", "row_count",
    "latest_observation_at", "source_latest_at", "retrieved_at_utc", "age_days",
    "stale_after_days", "cadence", "source_url", "pit_class", "source_license_class",
    "missing_geographies", "detail",
)


@dataclass(frozen=True, slots=True)
class ThemeSummary:
    cluster_id: str
    basket_id: str
    display_name: str
    primary_layer: str
    member_count: int
    tier_counts: tuple[tuple[str, int], ...]
    members: pd.DataFrame
    evidence_changes: pd.DataFrame
    catalysts: pd.DataFrame
    relationships: pd.DataFrame
    source_coverage: pd.DataFrame
    unavailable_reasons: tuple[str, ...]


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
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
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


def _active_for_event(row: Any, event: Any, *, fallback: pd.Timestamp) -> bool:
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


def _tokens(value: object) -> tuple[str, ...]:
    if value is None or value is pd.NA:
        return ()
    if isinstance(value, (tuple, list, set, frozenset)):
        values = [str(item).strip() for item in value]
    else:
        text = _text(value)
        if not text:
            return ()
        values = []
        if text.startswith("["):
            try:
                loaded = json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                loaded = None
            if isinstance(loaded, list):
                values = [str(item).strip() for item in loaded]
        if not values:
            values = text.split(";")
    return tuple(sorted({item for item in values if item}))


def _tuple_ids(value: object) -> tuple[str, ...]:
    return _tokens(value)


def _empty(columns: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            column: pd.Series(
                [],
                dtype="datetime64[ns, UTC]" if column == "latest_evidence_at" else "object",
            )
            for column in columns
        }
    )


def _normalize_cluster(cluster_id: str) -> tuple[str, str, str]:
    raw = _text(cluster_id)
    key = raw.casefold()
    normalized = _LAYER_ALIASES.get(key)
    if normalized == "__basket__":
        return AI_BASKET_ID, AI_BASKET_ID, ""
    if normalized is None:
        raise ValueError(f"unknown AI Bottlenecks layer: {cluster_id!r}")
    return normalized, AI_BASKET_ID, normalized


def _event_link_targets(snapshot: ControlTowerSnapshot, event: Any) -> tuple[set[str], set[str], set[str]]:
    """Resolve only explicit links active over the event's declared interval."""

    event_id = _text(event.get("event_id"))
    entity_ids: set[str] = set()
    listing_ids: set[str] = set()
    basket_ids: set[str] = set()
    has_raw_link = False
    entity_links = snapshot.event_entity_links.loc[
        snapshot.event_entity_links["event_id"].astype("string").eq(event_id)
    ] if not snapshot.event_entity_links.empty else snapshot.event_entity_links
    for _, link in entity_links.iterrows():
        has_raw_link = True
        if not _active_for_event(link, event, fallback=snapshot.as_of_utc):
            continue
        target_type = _text(link.get("target_type")).lower()
        target_id = _text(link.get("target_id"))
        if target_type == "entity" and target_id:
            entity_ids.add(target_id)
        elif target_type == "listing" and target_id:
            listing_ids.add(target_id)
        if target_type == "listing":
            listing_rows = snapshot.listings.loc[
                snapshot.listings["listing_id"].astype("string").eq(target_id)
            ] if not snapshot.listings.empty else snapshot.listings
            entity_ids.update(_text(value) for value in listing_rows.get("entity_id", pd.Series(dtype="string")) if _text(value))

    basket_links = snapshot.event_basket_links.loc[
        snapshot.event_basket_links["event_id"].astype("string").eq(event_id)
    ] if not snapshot.event_basket_links.empty else snapshot.event_basket_links
    for _, link in basket_links.iterrows():
        has_raw_link = True
        if _active_for_event(link, event, fallback=snapshot.as_of_utc):
            target_id = _text(link.get("target_id"))
            if target_id:
                basket_ids.add(target_id)

    if not has_raw_link:
        # Task 5's enriched relation columns are an explicit fallback only
        # when no split link row exists for the event. They are never used to
        # override an inactive raw link.
        entity_ids.update(_tuple_ids(event.get("related_entity_ids")))
        listing_ids.update(_tuple_ids(event.get("related_listing_ids")))
        basket_ids.update(_tuple_ids(event.get("related_basket_ids")))
    return entity_ids, listing_ids, basket_ids


def _event_entities(snapshot: ControlTowerSnapshot, event: Any) -> set[str]:
    entity_ids, listing_ids, basket_ids = _event_link_targets(snapshot, event)
    if listing_ids and not snapshot.listings.empty:
        entity_ids |= set(snapshot.listings.loc[snapshot.listings["listing_id"].astype("string").isin(listing_ids), "entity_id"].astype("string"))
    if basket_ids and not snapshot.basket_memberships.empty:
        for _, membership in snapshot.basket_memberships.iterrows():
            if _text(membership.get("basket_id")) in basket_ids and _active_for_event(membership, event, fallback=snapshot.as_of_utc):
                entity_ids.add(_text(membership.get("entity_id")))
    return {entity_id for entity_id in entity_ids if entity_id}


def _explicit_event_entities(snapshot: ControlTowerSnapshot, event: Any) -> set[str]:
    """Return only entity/listing targets explicitly attached to an event."""

    entity_ids, _, _ = _event_link_targets(snapshot, event)
    return {entity_id for entity_id in entity_ids if entity_id}


def _relevant_events(
    snapshot: ControlTowerSnapshot,
    member_ids: set[str],
    basket_id: str,
    *,
    include_basket_links: bool = True,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, event in snapshot.events.iterrows():
        _, _, event_baskets = _event_link_targets(snapshot, event)
        related_entities = _event_entities(snapshot, event) if include_basket_links else _explicit_event_entities(snapshot, event)
        basket_match = include_basket_links and basket_id in event_baskets
        if not basket_match and not related_entities.intersection(member_ids):
            continue
        rows.append(event.to_dict())
    if not rows:
        return snapshot.events.iloc[0:0].copy()
    return pd.DataFrame(rows).drop_duplicates(subset=["event_id"], keep="last").reset_index(drop=True)


def _collapse_supersessions(events: pd.DataFrame) -> tuple[pd.DataFrame, set[str]]:
    """Keep the latest visible observation while retaining IDs for disclosure."""

    if events.empty:
        return events.copy(), set()
    ids = set(events["event_id"].astype("string"))
    superseded = {
        value for value in events.get("supersedes_event_id", pd.Series(dtype="string")).map(_text)
        if value and value in ids
    }
    visible = events.loc[~events["event_id"].astype("string").isin(superseded)].copy()
    return visible.reset_index(drop=True), superseded


def _latest_observation(row: Any) -> pd.Timestamp | pd.NaT:
    values = [_timestamp(row.get("last_verified_at")), _timestamp(row.get("first_observed_at"))]
    valid = [value for value in values if value is not None]
    return max(valid) if valid else pd.NaT


def _display_status(source_row: Any) -> str:
    return _text(source_row.get("display_status")) or _text(source_row.get("status")) or "unclassified"


def build_theme_summary(
    snapshot: ControlTowerSnapshot,
    cluster_id: str,
    *,
    membership_tiers: tuple[str, ...] = (),
    countries: tuple[str, ...] = (),
) -> ThemeSummary:
    """Build a theme view from versioned registry relations and snapshot marts."""

    normalized, basket_id, primary_layer = _normalize_cluster(cluster_id)
    as_of = snapshot.as_of_utc
    basket_rows = snapshot.baskets.loc[snapshot.baskets["basket_id"].astype("string").str.upper().eq(basket_id)] if not snapshot.baskets.empty else snapshot.baskets
    display_name = _text(basket_rows.iloc[0].get("display_name")) if not basket_rows.empty else "AI Bottlenecks"
    if not primary_layer:
        primary_layer = normalized
    memberships = snapshot.basket_memberships.copy(deep=True)
    if not memberships.empty:
        memberships = memberships.loc[
            memberships["basket_id"].astype("string").str.upper().eq(basket_id)
            & memberships.apply(lambda row: _active(row, as_of), axis=1)
        ].copy()
    entities = snapshot.entities.set_index("entity_id", drop=False).to_dict("index") if not snapshot.entities.empty else {}
    listings = snapshot.listings.copy(deep=True)
    if not listings.empty:
        listings = listings.loc[listings.apply(lambda row: _active(row, as_of), axis=1)].copy()

    selected_tiers = {str(value).strip().lower() for value in membership_tiers if str(value).strip()}
    selected_countries = {str(value).strip().upper() for value in countries if str(value).strip()}
    theme_filter_active = bool(selected_tiers or selected_countries)
    member_rows: list[dict[str, object]] = []
    relationship_rows: list[dict[str, object]] = []
    for _, membership in memberships.iterrows():
        entity_id = _text(membership.get("entity_id"))
        entity = entities.get(entity_id, {})
        tier = _text(membership.get("membership_tier")).lower()
        country = _text(entity.get("country")).upper()
        if selected_tiers and tier not in selected_tiers:
            continue
        if selected_countries and country not in selected_countries:
            continue
        secondary = _tokens(membership.get("secondary_layers"))
        direct = _text(membership.get("primary_layer")).casefold() == primary_layer.casefold()
        read_through = primary_layer.casefold() in {item.casefold() for item in secondary}
        if not direct and not read_through:
            continue
        role = "primary_member" if direct else "read_through_member"
        entity_listings = listings.loc[listings["entity_id"].astype("string").eq(entity_id)] if not listings.empty else listings
        listing_ids = tuple(sorted(_text(value) for value in entity_listings.get("listing_id", pd.Series(dtype="string")) if _text(value)))
        verified = tuple(sorted(_text(row.get("listing_id")) for _, row in entity_listings.iterrows() if _text(row.get("mapping_status")).lower() == "verified" and _text(row.get("listing_id"))))
        eligible = any(bool(row.get("collection_eligible")) for _, row in entity_listings.iterrows()) if not entity_listings.empty else False
        member_rows.append(
            {
                "entity_id": entity_id,
                "display_name": _text(entity.get("display_name")) or _text(entity.get("legal_name")) or entity_id,
                "country": country,
                "basket_id": basket_id,
                "membership_tier": tier,
                "primary_layer": _text(membership.get("primary_layer")),
                "secondary_layers": "; ".join(secondary),
                "member_role": role,
                "listing_ids": listing_ids,
                "verified_listing_ids": verified,
                "collection_eligible": eligible,
                "latest_evidence_at": pd.NaT,
                "evidence_count": 0,
                "evidence_status": "unavailable",
                "consensus_status": "unavailable" if tier == "watch_only" else "unavailable",
            }
        )
        for secondary_layer in secondary:
            relationship_rows.append(
                {
                    "relationship_id": f"{basket_id}:{entity_id}:{secondary_layer}",
                    "basket_id": basket_id,
                    "entity_id": entity_id,
                    "entity_display_name": _text(entity.get("display_name")) or entity_id,
                    "primary_layer": _text(membership.get("primary_layer")),
                    "secondary_layer": secondary_layer,
                    "membership_tier": tier,
                    "relationship_type": "member_to_secondary_layer",
                    "relationship_basis": "basket_memberships.secondary_layers",
                    "source_or_research_note": _text(membership.get("source_or_research_note")),
                }
            )

    members = pd.DataFrame(member_rows, columns=THEME_MEMBER_COLUMNS) if member_rows else _empty(THEME_MEMBER_COLUMNS)
    if "latest_evidence_at" in members.columns:
        members["latest_evidence_at"] = pd.to_datetime(members["latest_evidence_at"], utc=True, errors="coerce")
    member_ids = set(members["entity_id"].astype("string")) if not members.empty else set()
    aggregation_ids = set(members.loc[members["membership_tier"].ne("watch_only"), "entity_id"].astype("string")) if not members.empty else set()
    events = (
        _relevant_events(
            snapshot,
            aggregation_ids,
            basket_id,
            include_basket_links=not theme_filter_active,
        )
        if aggregation_ids
        else snapshot.events.iloc[0:0].copy()
    )
    visible_events, superseded_ids = _collapse_supersessions(events)

    classified = classify_source_health(snapshot.source_health, now_utc=snapshot.now_utc)

    def source_meta(source_id: object, evidence_class: object, raw_url: object = "") -> dict[str, str]:
        source_text = _text(source_id)
        evidence_text = _text(evidence_class).lower()
        source_row = classified.loc[classified["source_id"].astype("string").eq(source_text)] if source_text and not classified.empty else classified.iloc[0:0]
        if source_row.empty and source_text and not classified.empty:
            source_row = classified.loc[classified["source_id"].astype("string").str.casefold().str.endswith(source_text.casefold())]
        internal = "internal_research" in evidence_text or (not source_row.empty and source_row.iloc[0]["source_license_class"] in {"private", "internal_research"})
        if internal:
            return {
                "source_url": "",
                "source_health_status": _display_status(source_row.iloc[0]) if not source_row.empty else "unavailable",
                "source_link_status": "unavailable",
                "pit_class": "not_pit",
                "source_license_class": "internal_research",
                "display_status": "not_pit",
            }
        if source_row.empty:
            return {
                "source_url": "",
                "source_health_status": "unavailable",
                "source_link_status": "unavailable",
                "pit_class": "PIT unavailable",
                "source_license_class": "",
                "display_status": "unavailable",
            }
        row = source_row.iloc[0]
        source_url = _text(row.get("source_url"))
        if not source_url.startswith(("http://", "https://")) and _text(raw_url).startswith(("http://", "https://")):
            source_url = _text(raw_url)
        return {
            "source_url": source_url,
            "source_health_status": _display_status(row),
            "source_link_status": "available" if source_url else "unavailable",
            "pit_class": _text(row.get("pit_display")) or "PIT unavailable",
            "source_license_class": _text(row.get("source_license_class")),
            "display_status": _display_status(row),
        }

    catalyst_rows: list[dict[str, object]] = []
    evidence_rows: list[dict[str, object]] = []
    for _, event in events.iterrows():
        event_id = _text(event.get("event_id"))
        event_entities = (
            _explicit_event_entities(snapshot, event)
            if theme_filter_active
            else _event_entities(snapshot, event)
        ).intersection(aggregation_ids)
        latest = _latest_observation(event)
        source = source_meta(event.get("source_id"), event.get("evidence_class"), event.get("source_url"))
        if event_id in set(visible_events["event_id"].astype("string")) and _text(event.get("event_type")).lower() != "coverage_gap" and _text(event.get("status")).lower() not in {"unavailable", "cancelled"} and _timestamp(event.get("starts_at")) is not None:
            question_count = int(snapshot.event_watch_questions.loc[snapshot.event_watch_questions["event_id"].astype("string").eq(event_id)].shape[0]) if not snapshot.event_watch_questions.empty else 0
            catalyst_rows.append(
                {
                    **{column: event.get(column, pd.NA) for column in THEME_CATALYST_COLUMNS[:21]},
                    "source_url": source["source_url"],
                    "watch_question_count": question_count,
                    "latest_observation": latest,
                    "source_health_status": source["source_health_status"],
                    "source_link_status": source["source_link_status"],
                    "pit_class": source["pit_class"],
                    "source_license_class": source["source_license_class"],
                    "display_status": source["display_status"],
                }
            )
        for entity_id in sorted(event_entities):
            evidence_rows.append(
                {
                    "change_id": f"event:{event_id}:{entity_id or 'basket'}",
                    "changed_at": latest,
                    "change_kind": "evidence_change",
                    "event_id": event_id,
                    "entity_id": entity_id or pd.NA,
                    "source_id": event.get("source_id", pd.NA),
                    "title": event.get("title", pd.NA),
                    "description": event.get("description", pd.NA),
                    "certainty_class": event.get("certainty_class", pd.NA),
                    "confidence": event.get("confidence", pd.NA),
                    "evidence_class": event.get("evidence_class", pd.NA),
                    "source_url": source["source_url"],
                    "pit_class": source["pit_class"],
                    "source_license_class": source["source_license_class"],
                    "display_status": "superseded" if event_id in superseded_ids else source["display_status"],
                    "detail": (
                        "superseded lineage · supersedes " + _text(event.get("supersedes_event_id"))
                        if _text(event.get("supersedes_event_id"))
                        else "superseded by visible replacement" if event_id in superseded_ids else ""
                    ),
                }
            )

    revisions = snapshot.consensus_revisions.copy(deep=True)
    if not revisions.empty and aggregation_ids:
        revisions = revisions.loc[revisions["entity_id"].astype("string").isin(aggregation_ids)].copy()
    if not revisions.empty:
        for _, revision in revisions.iterrows():
            entity_id = _text(revision.get("entity_id"))
            if entity_id not in aggregation_ids:
                continue
            changed = _timestamp(revision.get("current_snapshot_at")) or _timestamp(revision.get("retrieved_at_utc"))
            source = source_meta(
                f"provider:{_text(revision.get('provider'))}",
                revision.get("pit_class"),
                revision.get("source_url"),
            )
            evidence_rows.append(
                {
                    "change_id": f"revision:{_text(revision.get('revision_id'))}",
                    "changed_at": changed,
                    "change_kind": "consensus_revision",
                    "event_id": pd.NA,
                    "entity_id": entity_id,
                    "source_id": f"provider:{_text(revision.get('provider'))}" if _text(revision.get("provider")) else pd.NA,
                    "title": f"{_text(revision.get('metric'))} consensus revision",
                    "description": f"{_text(revision.get('fiscal_period'))} · provider-specific revision",
                    "certainty_class": pd.NA,
                    "confidence": pd.NA,
                    "evidence_class": "consensus_snapshot",
                    "source_url": source["source_url"],
                    "pit_class": source["pit_class"],
                    "source_license_class": source["source_license_class"],
                    "display_status": source["display_status"],
                    "detail": _text(revision.get("alignment_status")),
                }
            )

    evidence = pd.DataFrame(evidence_rows, columns=THEME_EVIDENCE_COLUMNS) if evidence_rows else _empty(THEME_EVIDENCE_COLUMNS)
    if not members.empty and not evidence.empty:
        for index, member in members.iterrows():
            relevant = evidence.loc[evidence["entity_id"].astype("string").eq(_text(member.get("entity_id")))]
            if relevant.empty:
                continue
            latest = pd.to_datetime(relevant["changed_at"], utc=True, errors="coerce").max()
            members.at[index, "latest_evidence_at"] = latest
            members.at[index, "evidence_count"] = len(relevant)
            statuses = set(relevant["display_status"].astype("string"))
            members.at[index, "evidence_status"] = "available" if statuses & {"healthy", "available"} else sorted(statuses)[0] if statuses else "unavailable"
    if not members.empty and not revisions.empty:
        consensus_entities = set(revisions["entity_id"].astype("string"))
        members.loc[members["membership_tier"].ne("watch_only") & members["entity_id"].isin(consensus_entities), "consensus_status"] = "available"

    catalysts = pd.DataFrame(catalyst_rows, columns=THEME_CATALYST_COLUMNS) if catalyst_rows else _empty(THEME_CATALYST_COLUMNS)
    relationships = pd.DataFrame(relationship_rows, columns=THEME_RELATIONSHIP_COLUMNS) if relationship_rows else _empty(THEME_RELATIONSHIP_COLUMNS)
    relevant_sources = set(evidence["source_id"].dropna().astype("string")) if not evidence.empty else set()
    if relevant_sources:
        source_coverage = classified.loc[classified["source_id"].astype("string").isin(relevant_sources)].copy()
    else:
        source_coverage = classified.iloc[0:0].copy()
    missing_sources = relevant_sources - set(source_coverage.get("source_id", pd.Series(dtype="string")).astype("string"))
    if missing_sources:
        missing_rows = pd.DataFrame(
            [
                {
                    "source_id": source_id,
                    "source_kind": "",
                    "status": "unavailable",
                    "display_status": "unavailable",
                    "row_count": pd.NA,
                    "latest_observation_at": pd.NaT,
                    "source_latest_at": pd.NaT,
                    "retrieved_at_utc": pd.NaT,
                    "age_days": pd.NA,
                    "stale_after_days": pd.NA,
                    "cadence": "",
                    "source_url": "",
                    "pit_class": "PIT unavailable",
                    "source_license_class": "",
                    "missing_geographies": "",
                    "detail": "source-health row unavailable; source link unavailable",
                }
                for source_id in sorted(missing_sources)
            ],
            columns=THEME_SOURCE_COLUMNS,
        )
        source_coverage = pd.concat([source_coverage, missing_rows], ignore_index=True)
    source_coverage = source_coverage.loc[:, [column for column in THEME_SOURCE_COLUMNS if column in source_coverage.columns]] if not source_coverage.empty else _empty(THEME_SOURCE_COLUMNS)
    unavailable: list[str] = []
    if members.empty:
        unavailable.append("no_matching_members")
    else:
        if evidence.empty:
            unavailable.append("latest_evidence_unavailable")
        if revisions.empty:
            unavailable.append("consensus_revisions_unavailable")
    return ThemeSummary(
        cluster_id=normalized,
        basket_id=basket_id,
        display_name=display_name,
        primary_layer=primary_layer,
        member_count=len(members),
        tier_counts=tuple(sorted((str(key), int(value)) for key, value in members["membership_tier"].value_counts().items())) if not members.empty else (),
        members=members.loc[:, THEME_MEMBER_COLUMNS],
        evidence_changes=evidence.loc[:, THEME_EVIDENCE_COLUMNS],
        catalysts=catalysts.loc[:, THEME_CATALYST_COLUMNS],
        relationships=relationships.loc[:, THEME_RELATIONSHIP_COLUMNS],
        source_coverage=source_coverage.loc[:, THEME_SOURCE_COLUMNS],
        unavailable_reasons=tuple(unavailable),
    )


def _time_text(value: object, timezone: str) -> str:
    timestamp = _timestamp(value)
    if timestamp is None:
        return "Unavailable"
    try:
        return timestamp.tz_convert(timezone).strftime("%d %b %H:%M %Z")
    except Exception:
        return timestamp.strftime("%d %b %H:%M UTC")


def _theme_filter_summary(tiers: list[str], countries: list[str]) -> str:
    parts: list[str] = []
    if tiers:
        parts.append(f"tier={','.join(tiers)}")
    if countries:
        parts.append(f"region={','.join(countries)}")
    return " · ".join(parts) if parts else "All theme filters at default"


def _member_watchlist_frame(
    snapshot: ControlTowerSnapshot,
    members: pd.DataFrame,
    *,
    viewer_timezone: str,
) -> pd.DataFrame:
    """Build the compact investor-facing member matrix.

    The underlying theme contract intentionally keeps stable ids and listing
    arrays.  Those are useful for joins, but they are not the right default
    presentation for a research workbench.
    """

    if members.empty:
        return pd.DataFrame(
            columns=[
                "Ticker", "Company", "Region", "Tier", "Layer", "Role",
                "Evidence", "Last evidence", "Consensus",
            ]
        )
    listing_labels: dict[str, str] = {}
    for _, listing in snapshot.listings.iterrows():
        listing_id = _text(listing.get("listing_id"))
        if not listing_id:
            continue
        ticker = _text(listing.get("canonical_ticker")) or _text(listing.get("native_ticker"))
        exchange = _text(listing.get("exchange"))
        label = " · ".join(value for value in (ticker, exchange) if value)
        if label:
            listing_labels[listing_id] = label

    rows: list[dict[str, object]] = []
    for _, member in members.iterrows():
        listing_ids = _tokens(member.get("verified_listing_ids")) or _tokens(member.get("listing_ids"))
        ticker = ", ".join(listing_labels.get(listing_id, listing_id) for listing_id in listing_ids) or "unresolved"
        evidence_status = _text(member.get("evidence_status")).replace("_", " ") or "unavailable"
        rows.append(
            {
                "Ticker": ticker,
                "Company": _text(member.get("display_name")) or "unavailable",
                "Region": _text(member.get("country")) or "unavailable",
                "Tier": _text(member.get("membership_tier")).replace("_", "-") or "unclassified",
                "Layer": _text(member.get("primary_layer")).replace("_", " ") or "unclassified",
                "Role": _text(member.get("member_role")).replace("_", " ") or "unclassified",
                "Evidence": evidence_status,
                "Last evidence": _time_text(member.get("latest_evidence_at"), viewer_timezone),
                "Consensus": _text(member.get("consensus_status")).replace("_", " ") or "unavailable",
            }
        )
    return pd.DataFrame(rows)


def _source_coverage_frame(source_coverage: pd.DataFrame) -> pd.DataFrame:
    """Keep source-health details compact and free of internal ids/paths."""

    if source_coverage.empty:
        return pd.DataFrame(columns=["Source kind", "Status", "Latest observation", "Age", "Cadence"])
    columns = {
        "source_kind": "Source kind",
        "display_status": "Status",
        "latest_observation_at": "Latest observation",
        "age_days": "Age (days)",
        "cadence": "Cadence",
    }
    available = [column for column in columns if column in source_coverage.columns]
    return source_coverage.loc[:, available].rename(columns={column: columns[column] for column in available})


def _compact_catalyst_frame(catalysts: pd.DataFrame) -> pd.DataFrame:
    """Collapse duplicate representations of one source observation."""

    if catalysts.empty:
        return catalysts
    frame = catalysts.copy()
    if not {"starts_at", "source_id"}.issubset(frame.columns):
        return frame
    relation_columns = ("related_entity_ids", "related_basket_ids")

    def normalise(value: object) -> tuple[str, ...]:
        return tuple(sorted(_tokens(value)))

    keys = [
        (
            _text(row.get("starts_at")),
            _text(row.get("source_id")),
            *(normalise(row.get(column)) for column in relation_columns),
            (
                "tw_monthly_revenue"
                if _text(row.get("source_id")) == "tw_monthly_revenue"
                else _text(row.get("event_type"))
            ),
            (
                ""
                if _text(row.get("source_id")) == "tw_monthly_revenue"
                else _text(row.get("title"))
            ),
        )
        for _, row in frame.iterrows()
    ]
    return frame.loc[~pd.Series(keys, index=frame.index).duplicated(keep="first")].reset_index(drop=True)


def _compact_evidence_frame(evidence: pd.DataFrame) -> pd.DataFrame:
    """Show one basket-level evidence item instead of one row per member."""

    if evidence.empty:
        return evidence
    frame = evidence.copy()
    groups: list[tuple[object, ...]] = []
    for _, row in frame.iterrows():
        source_id = _text(row.get("source_id"))
        if source_id == "tw_monthly_revenue":
            groups.append((source_id, _text(row.get("changed_at"))))
        else:
            groups.append(
                (
                    _text(row.get("event_id")),
                    _text(row.get("change_kind")),
                    _text(row.get("title")),
                )
            )
    return frame.loc[~pd.Series(groups, index=frame.index).duplicated(keep="first")].reset_index(drop=True)


def render_ai_bottlenecks_page(
    snapshot: ControlTowerSnapshot,
    *,
    filters: EventFilters,
    viewer_timezone: str,
) -> ThemeSummary:
    """Render the evidence-first AI Bottlenecks surface."""

    render_flight_deck(build_flight_deck(snapshot, filters=filters, viewer_timezone=viewer_timezone))
    layer_options = list(LAYER_LABELS)
    selected_layer = st.selectbox(
        "Primary bottleneck layer",
        layer_options,
        key="ct_ai_layer",
        format_func=lambda value: LAYER_LABELS[value],
    )
    tier_options = ["core", "read_through", "watch_only"]
    tiers = st.multiselect("Theme membership tier", tier_options, key="ct_ai_tiers", format_func=lambda value: value.replace("_", "-"))
    country_options = sorted({_text(value).upper() for value in snapshot.entities.get("country", pd.Series(dtype="string")) if _text(value)})
    countries = st.multiselect("Theme region", country_options, key="ct_ai_countries")
    st.caption(f"Active theme filters · {_theme_filter_summary(tiers, countries)}")
    summary = build_theme_summary(snapshot, selected_layer, membership_tiers=tuple(tiers), countries=tuple(countries))
    st.markdown(f"### {escape(summary.display_name)} · {escape(LAYER_LABELS.get(summary.primary_layer, summary.primary_layer))}")
    st.caption(f"{summary.member_count} registry member(s) · tier counts {summary.tier_counts or 'unavailable'} · evidence change is the ranking primitive")
    if summary.unavailable_reasons:
        st.warning("Data unavailable or degraded · " + "; ".join(summary.unavailable_reasons))
    st.info("Market data and earnings actuals are not in this bundle yet; no placeholder values are shown.")

    left, right = st.columns([1.35, 1])
    with left:
        st.markdown("#### Basket workbench")
        if summary.members.empty:
            st.info("No registry members match these layer, tier and region filters.")
        else:
            ct_dataframe(
                _member_watchlist_frame(snapshot, summary.members, viewer_timezone=viewer_timezone),
                width="stretch",
                hide_index=True,
            )
    with right:
        st.markdown("#### Explicit read-through context")
        if summary.relationships.empty:
            st.info("No explicit secondary-layer relationship is registered.")
        else:
            relationship_view = summary.relationships.loc[:, [
                "entity_display_name", "primary_layer", "secondary_layer",
                "membership_tier", "relationship_type",
            ]].rename(columns={
                "entity_display_name": "Company",
                "primary_layer": "Primary layer",
                "secondary_layer": "Read-through layer",
                "membership_tier": "Tier",
                "relationship_type": "Relationship",
            })
            ct_dataframe(relationship_view, width="stretch", hide_index=True)
            st.caption("Shared-layer cohort only; no supplier, customer, competitor or causal edge is inferred.")

    st.markdown("#### Upcoming catalysts")
    visible_catalysts = _compact_catalyst_frame(summary.catalysts)
    visible_evidence = _compact_evidence_frame(summary.evidence_changes)
    if "display_status" in visible_evidence.columns:
        visible_evidence = visible_evidence.loc[
            visible_evidence["display_status"].astype("string").str.casefold().ne("superseded")
        ].reset_index(drop=True)
    if visible_catalysts.empty:
        st.info("No upcoming catalyst is available from the selected registry-linked evidence.")
    else:
        for _, row in visible_catalysts.iterrows():
            source_link = "Source link unavailable" if _text(row.get("source_link_status")) != "available" or not _text(row.get("source_url")) else "Source link available"
            st.markdown(
                f"**{escape(_text(row.get('title')))}** · {escape(_text(row.get('certainty_class')).replace('_', ' '))} · "
                f"{_time_text(row.get('starts_at'), viewer_timezone)} · {escape(source_link)} · "
                f"health {escape(_text(row.get('source_health_status')) or 'unavailable')}"
            )
    if not visible_evidence.empty:
        st.markdown("#### Recent evidence changes")
        for _, row in visible_evidence.head(10).iterrows():
            st.markdown(
                f"**{escape(_text(row.get('title')) or 'Evidence change')}** · "
                f"{escape(_text(row.get('change_kind')).replace('_', ' '))} · "
                f"{_time_text(row.get('changed_at'), viewer_timezone)} · "
                f"{escape(_text(row.get('display_status')) or 'unavailable')}"
            )
    else:
        st.info("Latest evidence change is unavailable for this selection.")

    with st.expander("Lineage details", expanded=False):
        pit_values = {
            _text(value)
            for value in summary.catalysts.get("pit_class", pd.Series(dtype="string"))
            if _text(value)
        }
        link_unavailable = (
            not summary.catalysts.empty
            and summary.catalysts.get("source_link_status", pd.Series(dtype="string")).astype("string").ne("available").any()
        )
        if pit_values or link_unavailable:
            lineage_labels = []
            if pit_values:
                lineage_labels.append("PIT " + ", ".join(sorted(pit_values)))
            if link_unavailable:
                lineage_labels.append("source link unavailable")
            st.caption("Lineage status · " + " · ".join(lineage_labels))
        if not summary.evidence_changes.empty:
            ct_dataframe(summary.evidence_changes, width="stretch", hide_index=True)
        if not summary.catalysts.empty:
            ct_dataframe(summary.catalysts, width="stretch", hide_index=True)
    with st.expander("Source coverage and caveats", expanded=False):
        if summary.source_coverage.empty:
            st.info("Source coverage unavailable for this registry selection.")
        else:
            ct_dataframe(_source_coverage_frame(summary.source_coverage), width="stretch", hide_index=True)
        st.caption("Registry relationships, evidence change and source coverage only.")
    return summary


render_ai_page = render_ai_bottlenecks_page


__all__ = [
    "AI_BASKET_ID",
    "LAYER_LABELS",
    "THEME_MEMBER_COLUMNS",
    "THEME_EVIDENCE_COLUMNS",
    "THEME_CATALYST_COLUMNS",
    "THEME_RELATIONSHIP_COLUMNS",
    "THEME_SOURCE_COLUMNS",
    "ThemeSummary",
    "build_theme_summary",
    "render_ai_bottlenecks_page",
    "render_ai_page",
]
