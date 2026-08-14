"""Today / What Changed page and pure delta selection helpers."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

import pandas as pd
import streamlit as st

from ..components.flight_deck import FlightDeckViewModel, build_flight_deck, render_flight_deck
from ..components.timeline import catalyst_view_for_event, render_catalyst, select_next_catalyst
from ..filters import apply_event_filters
from ..models import ControlTowerSnapshot, EventFilters


TODAY_CHANGE_COLUMNS = (
    "change_id", "changed_at", "change_kind", "title", "description", "scope",
    "status", "certainty_class", "confidence", "importance", "event_id", "provider",
    "entity_id", "listing_id", "document_type", "source_id", "source_url",
    "source_timezone", "source_published_at", "retrieved_at_utc", "last_verified_at", "pit_class", "alignment_status", "lookback_days", "currency", "unit", "analyst_count", "related_entity_ids",
    "related_listing_ids", "related_basket_ids", "watch_question_ids",
)


@dataclass(frozen=True, slots=True)
class TodayViewModel:
    flight_deck: FlightDeckViewModel
    changes: pd.DataFrame
    next_catalyst: Any | None
    consensus_revisions: pd.DataFrame
    official_filings: pd.DataFrame
    guidance_changes: pd.DataFrame
    source_alerts: pd.DataFrame
    initial_snapshot: bool


def _empty_changes() -> pd.DataFrame:
    data: dict[str, pd.Series] = {}
    for column in TODAY_CHANGE_COLUMNS:
        if column in {"changed_at", "last_verified_at"}:
            data[column] = pd.Series(dtype="datetime64[ns, UTC]")
        elif column == "confidence":
            data[column] = pd.Series(dtype="Float64")
        else:
            data[column] = pd.Series(dtype="string")
    return pd.DataFrame(data)


def _text(value: object) -> str:
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _utc(value: object) -> pd.Timestamp | None:
    if value is None or value is pd.NaT:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed) or parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.tz_convert("UTC")


def _within(value: object, *, since: pd.Timestamp, as_of: pd.Timestamp) -> bool:
    timestamp = _utc(value)
    return timestamp is not None and timestamp > since and timestamp <= as_of


def _row_value(row: pd.Series, column: str, default: object = "") -> object:
    return row[column] if column in row.index else default


def _event_change_description(row: pd.Series, previous: pd.Series | None) -> str:
    if previous is None:
        return _text(_row_value(row, "description"))
    changed: list[str] = []
    for field, label in (
        ("starts_at", "date"), ("ends_at", "date"), ("status", "status"),
        ("confidence", "confidence"), ("source_id", "source"),
        ("description", "description"),
    ):
        old = _text(_row_value(previous, field))
        new = _text(_row_value(row, field))
        if old != new:
            changed.append(label)
    suffix = f"Changed: {', '.join(dict.fromkeys(changed))}." if changed else "Revision observed."
    description = _text(_row_value(row, "description"))
    return f"{suffix} {description}".strip()


def _normalise_change(
    *,
    change_id: str,
    changed_at: pd.Timestamp,
    change_kind: str,
    title: object = "",
    description: object = "",
    scope: object = "",
    status: object = "",
    certainty_class: object = "",
    confidence: object = pd.NA,
    importance: object = pd.NA,
    event_id: object = "",
    provider: object = "",
    entity_id: object = "",
    listing_id: object = "",
    document_type: object = "",
    source_id: object = "",
    source_url: object = "",
    source_timezone: object = "",
    source_published_at: object = pd.NaT,
    retrieved_at_utc: object = pd.NaT,
    last_verified_at: object = pd.NaT,
    pit_class: object = "",
    alignment_status: object = "",
    lookback_days: object = pd.NA,
    currency: object = "",
    unit: object = "",
    analyst_count: object = pd.NA,
    related_entity_ids: object = "",
    related_listing_ids: object = "",
    related_basket_ids: object = "",
    watch_question_ids: object = "",
) -> dict[str, object]:
    return {
        "change_id": change_id, "changed_at": changed_at, "change_kind": change_kind,
        "title": _text(title), "description": _text(description), "scope": _text(scope),
        "status": _text(status), "certainty_class": _text(certainty_class),
        "confidence": confidence, "importance": importance, "event_id": _text(event_id),
        "provider": _text(provider), "entity_id": _text(entity_id), "listing_id": _text(listing_id),
        "document_type": _text(document_type), "source_id": _text(source_id),
        "source_url": _text(source_url), "source_timezone": _text(source_timezone),
        "source_published_at": source_published_at, "retrieved_at_utc": retrieved_at_utc,
        "last_verified_at": last_verified_at, "pit_class": _text(pit_class),
        "alignment_status": _text(alignment_status), "lookback_days": lookback_days,
        "currency": _text(currency), "unit": _text(unit), "analyst_count": analyst_count,
        "related_entity_ids": related_entity_ids, "related_listing_ids": related_listing_ids,
        "related_basket_ids": related_basket_ids, "watch_question_ids": watch_question_ids,
    }


def _typed_changes(rows: list[dict[str, object]]) -> pd.DataFrame:
    if not rows:
        return _empty_changes()
    frame = pd.DataFrame(rows)
    for column in TODAY_CHANGE_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame = frame.loc[:, list(TODAY_CHANGE_COLUMNS)]
    frame["changed_at"] = pd.to_datetime(frame["changed_at"], utc=True, errors="coerce")
    for column in ("source_published_at", "retrieved_at_utc", "last_verified_at"):
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
    frame["confidence"] = pd.to_numeric(frame["confidence"], errors="coerce").astype("Float64")
    frame["lookback_days"] = pd.to_numeric(frame["lookback_days"], errors="coerce").astype("Int64")
    frame["analyst_count"] = pd.to_numeric(frame["analyst_count"], errors="coerce").astype("Int64")
    return frame.sort_values(["changed_at", "change_id"], kind="mergesort").reset_index(drop=True)


def enrich_consensus_revisions(
    revisions: pd.DataFrame,
    snapshots: pd.DataFrame,
) -> pd.DataFrame:
    """Add snapshot-owned display fields without changing the 35-column mart.

    ``snapshot_id`` is joined together with ``provider`` so one provider can
    never supply display metadata for another provider's revision.
    """

    result = revisions.copy()
    for column, dtype in (
        ("currency", "string"),
        ("unit", "string"),
        ("provider_contributor_count", "Int64"),
    ):
        if column not in result.columns:
            result[column] = pd.Series(pd.NA, index=result.index, dtype=dtype)
    if "current_analyst_count" not in result.columns:
        result["current_analyst_count"] = pd.Series(
            pd.NA, index=result.index, dtype="Int64"
        )
    if result.empty or snapshots.empty:
        return result

    join_keys = ["snapshot_id", "provider"]
    if not all(column in result.columns for column in join_keys):
        return result
    if not all(column in snapshots.columns for column in join_keys):
        return result

    enrichment_columns = [
        column
        for column in (
            "currency",
            "unit",
            "analyst_count",
            "provider_contributor_count",
        )
        if column in snapshots.columns
    ]
    lookup = snapshots.loc[:, join_keys + enrichment_columns].copy()
    # Ambiguous provider/snapshot identities are not safe to enrich.
    lookup = lookup.loc[~lookup.duplicated(join_keys, keep=False)].copy()
    lookup = lookup.rename(
        columns={
            "currency": "_snapshot_currency",
            "unit": "_snapshot_unit",
            "analyst_count": "_snapshot_analyst_count",
            "provider_contributor_count": "_snapshot_provider_contributor_count",
        }
    )
    enriched = result.merge(
        lookup,
        on=join_keys,
        how="left",
        sort=False,
        validate="many_to_one",
    )
    for target, source, dtype in (
        ("currency", "_snapshot_currency", "string"),
        ("unit", "_snapshot_unit", "string"),
        (
            "provider_contributor_count",
            "_snapshot_provider_contributor_count",
            "Int64",
        ),
    ):
        if source in enriched.columns:
            enriched[target] = enriched[target].combine_first(enriched[source])
            enriched[target] = enriched[target].astype(dtype)
            enriched = enriched.drop(columns=[source])
    if "_snapshot_analyst_count" in enriched.columns:
        current = pd.to_numeric(
            enriched["current_analyst_count"], errors="coerce"
        ).astype("Int64")
        snapshot_count = pd.to_numeric(
            enriched["_snapshot_analyst_count"], errors="coerce"
        ).astype("Int64")
        enriched["current_analyst_count"] = current.combine_first(snapshot_count)
        enriched = enriched.drop(columns=["_snapshot_analyst_count"])
    return enriched


def select_today_changes(
    snapshot: ControlTowerSnapshot,
    *,
    since: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Return a common, typed delta frame bounded by the snapshot vintage."""

    previous = _utc(since if since is not None else snapshot.previous_build_at)
    as_of = _utc(snapshot.as_of_utc)
    if previous is None or as_of is None:
        return _empty_changes()
    rows: list[dict[str, object]] = []
    events = snapshot.events
    by_event = events.set_index("event_id", drop=False) if not events.empty and "event_id" in events.columns else pd.DataFrame()
    superseded_in_window: set[str] = set()
    if not events.empty:
        for _, event in events.iterrows():
            changed_at = _utc(event.get("first_observed_at"))
            supersedes = _text(event.get("supersedes_event_id"))
            if supersedes and changed_at is not None and _within(changed_at, since=previous, as_of=as_of):
                superseded_in_window.add(supersedes)
        for _, event in events.iterrows():
            changed_at = _utc(event.get("first_observed_at"))
            if changed_at is None or not _within(changed_at, since=previous, as_of=as_of):
                continue
            if _text(event.get("event_id")) in superseded_in_window:
                continue
            supersedes = _text(event.get("supersedes_event_id"))
            prior = by_event.loc[supersedes] if supersedes and supersedes in by_event.index else None
            kind = "event_revision" if prior is not None else "new_event"
            rows.append(_normalise_change(
                change_id=f"event:{_text(event.get('event_id'))}", changed_at=changed_at,
                change_kind=kind, title=event.get("title"),
                description=_event_change_description(event, prior), scope=event.get("scope"),
                status=event.get("status"), certainty_class=event.get("certainty_class"),
                confidence=event.get("confidence"), importance=event.get("importance"),
                event_id=event.get("event_id"), source_id=event.get("source_id"),
                source_url=event.get("source_url"), source_timezone=event.get("source_timezone"),
                source_published_at=event.get("source_published_at"),
                last_verified_at=event.get("last_verified_at"),
                related_entity_ids=event.get("related_entity_ids"),
                related_listing_ids=event.get("related_listing_ids"),
                related_basket_ids=event.get("related_basket_ids"),
            ))

    revisions = enrich_consensus_revisions(
        snapshot.consensus_revisions,
        snapshot.consensus_snapshots,
    )
    if not revisions.empty:
        for _, row in revisions.iterrows():
            changed_at = _utc(row.get("current_snapshot_at")) or _utc(row.get("retrieved_at_utc"))
            if changed_at is None or not _within(changed_at, since=previous, as_of=as_of):
                continue
            rows.append(_normalise_change(
                change_id=f"revision:{_text(row.get('revision_id')) or _text(row.get('snapshot_id'))}",
                changed_at=changed_at, change_kind="consensus_revision",
                title=f"{_text(row.get('provider'))} · {_text(row.get('canonical_ticker')) or _text(row.get('entity_id'))}",
                description=f"{_text(row.get('metric'))} {_text(row.get('fiscal_period'))}: {_text(row.get('prior_value')) or '—'} → {_text(row.get('current_value')) or '—'} {_text(row.get('unit'))}".strip(),
                provider=row.get("provider"), entity_id=row.get("entity_id"), listing_id=row.get("listing_id"),
                source_url=row.get("source_url"), pit_class=row.get("pit_class"),
                alignment_status=row.get("alignment_status"), lookback_days=row.get("lookback_days"),
                currency=row.get("currency"), unit=row.get("unit"), analyst_count=row.get("current_analyst_count"),
                retrieved_at_utc=row.get("retrieved_at_utc"),
            ))

    filings = snapshot.news_filings
    if not filings.empty:
        for _, row in filings.iterrows():
            changed_at = _utc(row.get("first_observed_at"))
            if changed_at is None or not _within(changed_at, since=previous, as_of=as_of):
                continue
            document_type = _text(row.get("document_type"))
            event_class = _text(row.get("event_class")).lower()
            kind = "guidance_change" if "guidance" in document_type.lower() or "guidance" in event_class else "official_filing"
            rows.append(_normalise_change(
                change_id=f"filing:{_text(row.get('document_id'))}", changed_at=changed_at,
                change_kind=kind, title=row.get("headline"), description=row.get("publisher"),
                document_type=document_type, source_id=row.get("source_id"), source_url=row.get("source_url"),
                source_published_at=row.get("published_at"), last_verified_at=row.get("first_observed_at"),
                pit_class=row.get("pit_class"), related_entity_ids=row.get("related_entity_ids"),
                related_listing_ids=row.get("related_listing_ids"), related_basket_ids=row.get("related_basket_ids"),
            ))

    health = snapshot.source_health
    if not health.empty:
        bad_statuses = {"stale", "failed", "conflicted", "unavailable", "review_required"}
        for _, row in health.iterrows():
            if _text(row.get("status")).lower() not in bad_statuses:
                continue
            changed_at = _utc(row.get("retrieved_at_utc")) or _utc(row.get("latest_observation_at"))
            if changed_at is None or not _within(changed_at, since=previous, as_of=as_of):
                continue
            rows.append(_normalise_change(
                change_id=f"health:{_text(row.get('source_id'))}", changed_at=changed_at,
                change_kind="source_conflict" if _text(row.get("status")).lower() in {"conflicted", "review_required"} else "source_stale",
                title=f"Global source health · {_text(row.get('source_id'))}", description=row.get("detail"),
                status=row.get("status"), source_id=row.get("source_id"), source_url=row.get("source_url"),
                retrieved_at_utc=row.get("retrieved_at_utc"), pit_class=row.get("pit_class"),
            ))
    return _typed_changes(rows)


def _filter_change_rows(
    changes: pd.DataFrame,
    selected_entities: set[str],
    selected_listings: set[str],
    selected_baskets: set[str],
    *,
    restricted: bool,
    allowed_event_ids: set[str],
    include_company_content: bool,
) -> pd.DataFrame:
    if changes.empty:
        return changes
    event_ids = changes.get("event_id", pd.Series("", index=changes.index)).astype("string")
    event_mask = event_ids.eq("") | event_ids.isin(allowed_event_ids)
    if not include_company_content:
        company_kinds = {
            "consensus_revision",
            "official_filing",
            "guidance_change",
        }
        change_kinds = changes.get(
            "change_kind", pd.Series("", index=changes.index, dtype="string")
        ).astype("string")
        event_mask &= ~change_kinds.isin(company_kinds)
    if not restricted:
        return changes.loc[event_mask].reset_index(drop=True)
    def any_relation(column: str, selected: set[str]) -> pd.Series:
        if not selected:
            return pd.Series(False, index=changes.index)
        values = changes.get(column, pd.Series("", index=changes.index, dtype="string"))
        return values.map(lambda value: bool(set(_tuple_values(value)) & selected))
    relation_keep = (
        any_relation("related_entity_ids", selected_entities)
        | any_relation("related_listing_ids", selected_listings)
        | any_relation("related_basket_ids", selected_baskets)
        | changes.get("entity_id", pd.Series("", index=changes.index)).astype("string").isin(selected_entities)
        | changes.get("listing_id", pd.Series("", index=changes.index)).astype("string").isin(selected_listings)
    )
    return changes.loc[event_mask & relation_keep].reset_index(drop=True)


def _windowed_frame(frame: pd.DataFrame, timestamp_columns: tuple[str, ...], snapshot: ControlTowerSnapshot) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    start = snapshot.previous_build_at
    if start is None:
        return frame.iloc[0:0].copy()
    as_of = snapshot.as_of_utc
    mask = pd.Series(False, index=frame.index)
    for column in timestamp_columns:
        if column in frame.columns:
            values = pd.to_datetime(frame[column], utc=True, errors="coerce")
            mask |= values.gt(start) & values.le(as_of)
    return frame.loc[mask].copy().reset_index(drop=True)


def _source_alerts(snapshot: ControlTowerSnapshot) -> pd.DataFrame:
    if snapshot.source_health.empty:
        return snapshot.source_health.iloc[0:0].copy()
    bad = {"stale", "failed", "conflicted", "unavailable", "review_required"}
    return snapshot.source_health.loc[snapshot.source_health["status"].astype("string").str.lower().isin(bad)].copy().reset_index(drop=True)


def _tuple_values(value: object) -> tuple[str, ...]:
    if value is None or value is pd.NA:
        return ()
    if isinstance(value, (tuple, list, set, frozenset)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = _text(value)
    return (text,) if text else ()


def _selected_universe(snapshot: ControlTowerSnapshot, filters: EventFilters) -> tuple[set[str], set[str], set[str]]:
    selected_baskets = set(filters.basket_id)
    memberships = snapshot.basket_memberships
    entities = set(snapshot.entities.get("entity_id", pd.Series(dtype="string")).astype("string"))
    if selected_baskets:
        if memberships.empty:
            entities = set()
        else:
            membership_rows = memberships.loc[memberships["basket_id"].astype("string").isin(selected_baskets)].copy()
            if filters.membership_tier:
                membership_rows = membership_rows.loc[membership_rows["membership_tier"].astype("string").str.lower().isin(filters.membership_tier)]
            entities &= set(membership_rows["entity_id"].astype("string"))
    if filters.country:
        entities &= set(snapshot.entities.loc[snapshot.entities["country"].astype("string").str.upper().isin(filters.country), "entity_id"].astype("string"))
    elif filters.membership_tier and not selected_baskets:
        if memberships.empty:
            entities = set()
        else:
            entities &= set(memberships.loc[memberships["membership_tier"].astype("string").str.lower().isin(filters.membership_tier), "entity_id"].astype("string"))
    listings = set(snapshot.listings.loc[snapshot.listings["entity_id"].astype("string").isin(entities), "listing_id"].astype("string")) if not snapshot.listings.empty else set()
    return entities, listings, selected_baskets


def _filter_frame_universe(
    frame: pd.DataFrame,
    entities: set[str],
    listings: set[str],
    baskets: set[str],
    *,
    restricted: bool,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    if not restricted:
        return frame.copy().reset_index(drop=True)
    masks: list[pd.Series] = []
    if "entity_id" in frame.columns:
        masks.append(frame["entity_id"].astype("string").isin(entities))
    if "listing_id" in frame.columns:
        masks.append(frame["listing_id"].astype("string").isin(listings))
    for column, selected in (("related_entity_ids", entities), ("related_listing_ids", listings), ("related_basket_ids", baskets)):
        if column in frame.columns:
            masks.append(frame[column].map(lambda value: bool(set(_tuple_values(value)) & selected)))
    if not masks:
        return frame.iloc[0:0].copy()
    mask = masks[0]
    for item in masks[1:]:
        mask |= item
    return frame.loc[mask].copy().reset_index(drop=True)


def build_today_view(
    snapshot: ControlTowerSnapshot,
    *,
    filters: EventFilters,
    viewer_timezone: str,
) -> TodayViewModel:
    filtered_events = apply_event_filters(snapshot.events, filters)
    selected_entities, selected_listings, selected_baskets = _selected_universe(snapshot, filters)
    restricted = bool(filters.basket_id or filters.country or filters.membership_tier)
    include_company_content = not filters.scope or "company" in filters.scope
    allowed_event_ids = set(filtered_events.get("event_id", pd.Series(dtype="string")).astype("string"))
    changes = _filter_change_rows(
        select_today_changes(snapshot),
        selected_entities,
        selected_listings,
        selected_baskets,
        restricted=restricted,
        allowed_event_ids=allowed_event_ids,
        include_company_content=include_company_content,
    )
    enriched_revisions = enrich_consensus_revisions(
        snapshot.consensus_revisions,
        snapshot.consensus_snapshots,
    )
    revisions = _filter_frame_universe(_windowed_frame(enriched_revisions, ("current_snapshot_at", "retrieved_at_utc"), snapshot), selected_entities, selected_listings, selected_baskets, restricted=restricted)
    filings = _filter_frame_universe(_windowed_frame(snapshot.news_filings, ("first_observed_at",), snapshot), selected_entities, selected_listings, selected_baskets, restricted=restricted)
    if not include_company_content:
        revisions = revisions.iloc[0:0].copy()
        filings = filings.iloc[0:0].copy()
    guidance = filings.loc[
        filings.get("document_type", pd.Series("", index=filings.index)).astype("string").str.contains("guidance", case=False, na=False)
        | filings.get("event_class", pd.Series("", index=filings.index)).astype("string").str.contains("guidance", case=False, na=False)
    ].copy() if not filings.empty else filings.copy()
    deck = build_flight_deck(snapshot, filters=filters, viewer_timezone=viewer_timezone)
    next_row = select_next_catalyst(filtered_events, snapshot.now_utc)
    next_view = catalyst_view_for_event(snapshot, next_row, now_utc=snapshot.now_utc, viewer_timezone=viewer_timezone) if next_row is not None else None
    return TodayViewModel(
        flight_deck=deck, changes=changes, next_catalyst=next_view,
        consensus_revisions=revisions, official_filings=filings.loc[~filings.index.isin(guidance.index)].copy() if not filings.empty else filings,
        guidance_changes=guidance, source_alerts=_source_alerts(snapshot),
        initial_snapshot=snapshot.previous_build_at is None,
    )


def _display_time(value: object, timezone: str) -> str:
    timestamp = _utc(value)
    if timestamp is None:
        return "—"
    try:
        return timestamp.tz_convert(timezone).strftime("%d %b %H:%M %Z")
    except Exception:
        return timestamp.strftime("%d %b %H:%M UTC")


def _table_cell_text(column: str, value: object, timezone: str) -> str:
    if column in {"changed_at", "source_published_at", "retrieved_at_utc", "last_verified_at", "first_observed_at", "current_snapshot_at"}:
        return _display_time(value, timezone)
    if column == "source_url":
        url = _text(value)
        return url if url.startswith(("http://", "https://")) else "Source link unavailable"
    text = _text(value)
    if text:
        return text
    if column in {
        "currency",
        "unit",
        "current_analyst_count",
        "provider_contributor_count",
    }:
        return "Unavailable"
    return "—"


def _render_table(frame: pd.DataFrame, columns: tuple[str, ...], *, timezone: str) -> None:
    if frame.empty:
        return
    rows: list[str] = []
    for _, row in frame.head(25).iterrows():
        cells: list[str] = []
        for column in columns:
            text = _table_cell_text(column, row.get(column), timezone)
            cells.append(f"<td>{escape(text)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    heads = "".join(f"<th>{escape(column.replace('_', ' ').title())}</th>" for column in columns)
    body = "".join(rows)
    st.markdown(f'<table><thead><tr>{heads}</tr></thead><tbody>{body}</tbody></table>', unsafe_allow_html=True)


def _change_ticker_label(snapshot: ControlTowerSnapshot, row: pd.Series) -> str:
    from ..components.timeline import resolve_ticker_chips

    chips = resolve_ticker_chips(snapshot, row.to_dict())
    if chips:
        return chips[0].label
    return "ticker unavailable · registry unresolved"


def _render_changes(snapshot: ControlTowerSnapshot, changes: pd.DataFrame, *, timezone: str) -> None:
    if changes.empty:
        st.markdown('<div class="ct-empty">No changes in the selected snapshot window.</div>', unsafe_allow_html=True)
        return
    blocks: list[str] = []
    for _, row in changes.iterrows():
        title = _text(row.get("title")) or _text(row.get("change_id"))
        kind = _text(row.get("change_kind")).replace("_", " ").title()
        detail = _text(row.get("description"))
        changed = _display_time(row.get("changed_at"), timezone)
        source = _text(row.get("source_id")) or "source unavailable"
        source_link = _text(row.get("source_url"))
        source_text = f'<a class="ct-inline-link" href="{escape(source_link, quote=True)}" target="_blank" rel="noopener">{escape(source)}</a>' if source_link.startswith(("http://", "https://")) else f"{escape(source)} · source link unavailable"
        ticker = _change_ticker_label(snapshot, row)
        pit = _text(row.get("pit_class")) or "PIT unavailable"
        blocks.append(f'<div class="ct-change"><div class="ct-change-title">{escape(title)}</div><div class="ct-change-detail">{escape(kind)} · {escape(changed)} · {escape(detail)}</div><div class="ct-source-line">{escape(ticker)} · {source_text} · PIT · {escape(pit)}</div></div>')
    st.markdown('<div class="ct-change-list">' + "".join(blocks) + "</div>", unsafe_allow_html=True)


def render_today_page(
    snapshot: ControlTowerSnapshot,
    *,
    filters: EventFilters,
    viewer_timezone: str,
) -> TodayViewModel:
    model = build_today_view(snapshot, filters=filters, viewer_timezone=viewer_timezone)
    render_flight_deck(model.flight_deck)
    if model.initial_snapshot:
        st.info("Initial snapshot · upcoming items are shown for review; none are labelled as changed.")
    else:
        st.caption(f"Changes since {snapshot.previous_build_at.tz_convert(viewer_timezone).strftime('%d %b %Y %H:%M %Z')}")

    left, right = st.columns([1.9, .9])
    with left:
        with st.container(border=True):
            st.markdown('<div class="ct-panel-heading"><h3>What changed</h3><span class="ct-count">prioritized delta</span></div>', unsafe_allow_html=True)
            _render_changes(snapshot, model.changes, timezone=viewer_timezone)
        if not model.consensus_revisions.empty:
            st.markdown("### Consensus revisions")
            with st.container(border=True):
                _render_table(model.consensus_revisions, ("provider", "listing_id", "metric", "fiscal_period", "lookback_days", "prior_value", "current_value", "currency", "unit", "current_analyst_count", "provider_contributor_count", "pit_class", "alignment_status", "source_url"), timezone=viewer_timezone)
        if not model.official_filings.empty:
            st.markdown("### Official filings")
            with st.container(border=True):
                _render_table(model.official_filings, ("headline", "publisher", "first_observed_at", "source_id", "source_url"), timezone=viewer_timezone)
        if not model.guidance_changes.empty:
            st.markdown("### Guidance changes")
            with st.container(border=True):
                _render_table(model.guidance_changes, ("headline", "publisher", "first_observed_at", "source_id", "source_url"), timezone=viewer_timezone)
    with right:
        with st.container(border=True):
            st.markdown('<h3>Upcoming from initial snapshot</h3>' if model.initial_snapshot else '<h3>Next catalyst</h3>', unsafe_allow_html=True)
            if model.next_catalyst is None:
                st.markdown('<div class="ct-empty">No eligible catalyst in the selected horizon.</div>', unsafe_allow_html=True)
            else:
                render_catalyst(model.next_catalyst, viewer_timezone=viewer_timezone)

    if not model.source_alerts.empty:
        alerts = "; ".join(f"{_text(row.get('source_id'))}: {_text(row.get('status'))}" for _, row in model.source_alerts.head(8).iterrows())
        st.markdown(f'<div class="ct-alert-strip"><strong>Global source alerts</strong> · These alerts are not universe-filtered. · {escape(alerts)}</div>', unsafe_allow_html=True)
    return model


__all__ = [
    "TODAY_CHANGE_COLUMNS",
    "TodayViewModel",
    "build_today_view",
    "render_today_page",
    "select_next_catalyst",
    "select_today_changes",
]
