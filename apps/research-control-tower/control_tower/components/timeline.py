"""Pure timeline view models and event-row rendering."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any, Mapping
import pandas as pd
import streamlit as st

from ..filters import apply_event_filters
from ..formatting import format_t_minus
from ..models import ControlTowerSnapshot, EventFilters
from .source_badges import (
    SourceBadgeView,
    certainty_label,
    source_badges_for_event,
    source_badges_html,
)


@dataclass(frozen=True, slots=True)
class CatalystView:
    event_id: str
    title: str
    description: str
    scope: str
    event_type: str
    status: str
    certainty_class: str
    confidence: float | None
    importance: str | None
    date_precision: str
    starts_at: pd.Timestamp
    ends_at: pd.Timestamp | None
    display_window: str
    t_minus: str
    source_badges: tuple[SourceBadgeView, ...]
    ticker_chips: tuple["TickerChip", ...]
    related_entity_ids: tuple[str, ...]
    related_listing_ids: tuple[str, ...]
    related_basket_ids: tuple[str, ...]
    watch_questions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TimelineMonthGroup:
    month_key: str
    month_label: str
    events: tuple[CatalystView, ...]


@dataclass(frozen=True, slots=True)
class TickerChip:
    """Display label resolved from a verified active registry listing."""

    label: str
    title: str


_CERTAINTY_ORDER = {"hard": 0, "provisional": 1, "thesis_checkpoint": 2, "observed": 3}
_IMPORTANCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def _text(value: object) -> str:
    if value is None or value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip()


def _tuple_values(value: object) -> tuple[str, ...]:
    if value is None or value is pd.NA:
        return ()
    if isinstance(value, (tuple, list, set, frozenset)):
        return tuple(sorted({str(item).strip() for item in value if str(item).strip()}))
    text = _text(value)
    return (text,) if text else ()


def _utc(value: object) -> pd.Timestamp | None:
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed) or parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.tz_convert("UTC")


def _format_period(value: pd.Timestamp, precision: str, timezone: str) -> str:
    local = value.tz_convert(timezone)
    precision = precision.lower()
    if precision == "minute":
        return local.strftime("%d %b %Y %H:%M %Z")
    if precision == "day":
        return local.strftime("%d %b %Y")
    if precision == "week":
        return f"week of {local.strftime('%d %b %Y')}"
    if precision == "month":
        return local.strftime("%b %Y")
    if precision == "quarter":
        return f"Q{((local.month - 1) // 3) + 1} {local.year}"
    if precision == "half":
        return f"H{1 if local.month <= 6 else 2} {local.year}"
    if precision == "year":
        return str(local.year)
    return local.strftime("%d %b %Y")


def format_event_window(
    starts_at: object,
    ends_at: object,
    date_precision: object,
    viewer_timezone: str,
) -> str:
    """Format a source-backed event range without inventing exact dates."""

    start = _utc(starts_at)
    end = _utc(ends_at)
    if start is None:
        return "Date unavailable"
    precision = _text(date_precision) or "day"
    start_label = _format_period(start, precision, viewer_timezone)
    if end is None or end == start:
        return start_label
    end_label = _format_period(end, precision, viewer_timezone)
    return f"{start_label} → {end_label}"


def _importance(value: object) -> str | None:
    text = _text(value).lower()
    return text if text in _IMPORTANCE_ORDER else None


def _watch_questions(snapshot: ControlTowerSnapshot | None, event_id: str) -> tuple[str, ...]:
    if snapshot is None or snapshot.event_watch_questions.empty:
        return ()
    frame = snapshot.event_watch_questions
    rows = frame.loc[frame["event_id"].astype("string").eq(event_id)].copy()
    if rows.empty:
        return ()
    if "priority" in rows.columns:
        rows["__priority"] = pd.to_numeric(rows["priority"], errors="coerce").fillna(999999)
    else:
        rows["__priority"] = 999999
    rows["__qid"] = rows.get("question_id", pd.Series("", index=rows.index)).astype("string")
    rows = rows.sort_values(["__priority", "__qid"], kind="mergesort")
    values: list[str] = []
    for _, row in rows.iterrows():
        question = _text(row.get("question"))
        if not question:
            continue
        question_type = _text(row.get("question_type")).lower()
        prefix = f"{question_type.title()}: " if question_type in {"support", "falsification"} else ""
        values.append(prefix + question)
    return tuple(values)


def resolve_ticker_chips(snapshot: ControlTowerSnapshot | None, event: Mapping[str, Any]) -> tuple[TickerChip, ...]:
    if snapshot is None:
        return ()
    listings = snapshot.listings
    entities = snapshot.entities
    event_start = _utc(event.get("starts_at"))
    if event_start is None:
        event_start = _utc(getattr(snapshot, "as_of_utc", None))
    event_date = event_start.tz_localize(None).normalize() if event_start is not None else None
    candidates: list[tuple[int, str, str, str]] = []
    resolved_entities: set[str] = set()
    listing_ids = set(_tuple_values(event.get("related_listing_ids")))
    entity_ids = set(_tuple_values(event.get("related_entity_ids")))
    basket_ids = set(_tuple_values(event.get("related_basket_ids")))
    memberships = getattr(snapshot, "basket_memberships", pd.DataFrame()) if snapshot is not None else pd.DataFrame()
    if not memberships.empty and basket_ids and "basket_id" in memberships.columns:
        active_memberships = memberships.loc[memberships["basket_id"].astype("string").isin(basket_ids)].copy()
        if event_date is not None:
            if "active_from" in active_memberships.columns:
                starts = pd.to_datetime(active_memberships["active_from"], errors="coerce")
                active_memberships = active_memberships.loc[starts.isna() | starts.le(event_date)]
            if "active_to" in active_memberships.columns:
                ends = pd.to_datetime(active_memberships["active_to"], errors="coerce")
                active_memberships = active_memberships.loc[ends.isna() | ends.gt(event_date)]
        entity_ids.update(_text(value) for value in active_memberships.get("entity_id", pd.Series(dtype="string")).tolist() if _text(value))

    def tiers_for(entity_id: str) -> tuple[str, ...]:
        if memberships.empty or "entity_id" not in memberships.columns:
            return ()
        rows = memberships.loc[memberships["entity_id"].astype("string").eq(entity_id)].copy()
        if basket_ids and "basket_id" in rows.columns:
            rows = rows.loc[rows["basket_id"].astype("string").isin(basket_ids)]
        if event_date is not None:
            if "active_from" in rows.columns:
                starts = pd.to_datetime(rows["active_from"], errors="coerce")
                rows = rows.loc[starts.isna() | starts.le(event_date)]
            if "active_to" in rows.columns:
                ends = pd.to_datetime(rows["active_to"], errors="coerce")
                rows = rows.loc[ends.isna() | ends.gt(event_date)]
        return tuple(sorted({_text(value).lower() for value in rows.get("membership_tier", pd.Series(dtype="string")).tolist() if _text(value)}))

    if not listings.empty:
        for _, row in listings.iterrows():
            listing_id = _text(row.get("listing_id"))
            entity_id = _text(row.get("entity_id"))
            if listing_id not in listing_ids and entity_id not in entity_ids:
                continue
            active_from = pd.Timestamp(row["active_from"]) if _text(row.get("active_from")) else None
            active_to = pd.Timestamp(row["active_to"]) if _text(row.get("active_to")) else None
            if event_date is not None:
                if active_from is not None and event_date < active_from.normalize():
                    continue
                if active_to is not None and event_date >= active_to.normalize():
                    continue
            if _text(row.get("mapping_status")).lower() != "verified":
                continue
            if _text(row.get("listing_status")).lower() not in {"", "active"}:
                continue
            eligible = row.get("collection_eligible")
            if eligible is not None and not pd.isna(eligible) and not bool(eligible):
                continue
            role = _text(row.get("listing_role")).lower()
            primary = bool(row.get("primary_listing")) if not pd.isna(row.get("primary_listing")) else False
            rank = 0 if primary or role in {"primary", "dual_primary"} else 1
            ticker = _text(row.get("canonical_ticker")) or _text(row.get("native_ticker"))
            exchange = _text(row.get("exchange"))
            tiers = tiers_for(entity_id)
            tier_label = ", ".join(tiers) if tiers else "tier unclassified"
            label = " · ".join(value for value in (ticker, exchange, tier_label) if value)
            title = f"Registry-resolved listing · {exchange or 'exchange unavailable'} · {tier_label}"
            if label:
                candidates.append((rank, label, title, entity_id))
                resolved_entities.add(entity_id)
    if entity_ids and not entities.empty:
        for _, row in entities.iterrows():
            entity_id = _text(row.get("entity_id"))
            if entity_id in entity_ids and entity_id not in resolved_entities:
                display = _text(row.get("display_name")) or entity_id
                candidates.append((2, f"{display} · listing unresolved", f"{display} · registry listing unresolved", entity_id))
    deduped: list[TickerChip] = []
    for _, label, title, _ in sorted(candidates, key=lambda item: (item[0], item[1])):
        if not any(chip.label == label for chip in deduped):
            deduped.append(TickerChip(label=label, title=title))
    return tuple(deduped)


def catalyst_view_for_event(
    snapshot: ControlTowerSnapshot | None,
    event: Mapping[str, Any],
    *,
    now_utc: pd.Timestamp,
    viewer_timezone: str,
) -> CatalystView | None:
    start = _utc(event.get("starts_at"))
    if start is None:
        return None
    end = _utc(event.get("ends_at"))
    event_id = _text(event.get("event_id"))
    return CatalystView(
        event_id=event_id,
        title=_text(event.get("title")) or event_id,
        description=_text(event.get("description")),
        scope=_text(event.get("scope")),
        event_type=_text(event.get("event_type")),
        status=_text(event.get("status")),
        certainty_class=_text(event.get("certainty_class")).lower(),
        confidence=float(event["confidence"]) if event.get("confidence") is not None and not pd.isna(event.get("confidence")) else None,
        importance=_importance(event.get("importance")),
        date_precision=_text(event.get("date_precision")) or "day",
        starts_at=start,
        ends_at=end,
        display_window=format_event_window(start, end, event.get("date_precision"), viewer_timezone),
        t_minus=format_t_minus(start, viewer_timezone, now_utc),
        source_badges=source_badges_for_event(snapshot, event) if snapshot is not None else (),
        ticker_chips=resolve_ticker_chips(snapshot, event),
        related_entity_ids=_tuple_values(event.get("related_entity_ids")),
        related_listing_ids=_tuple_values(event.get("related_listing_ids")),
        related_basket_ids=_tuple_values(event.get("related_basket_ids")),
        watch_questions=_watch_questions(snapshot, event_id),
    )


def select_next_catalyst(events: pd.DataFrame, now_utc: pd.Timestamp) -> pd.Series | None:
    """Choose the next active/future event using only explicit ranks."""

    now = _utc(now_utc)
    if now is None:
        raise ValueError("now_utc must be timezone-aware")
    if events.empty:
        return None
    filtered = apply_event_filters(
        events,
        EventFilters(horizon="all", now_utc=now, catalyst_eligible=True),
    )
    candidates: list[tuple[tuple[Any, ...], int, pd.Series]] = []
    for position, (_, row) in enumerate(filtered.iterrows()):
        start = _utc(row.get("starts_at"))
        if start is None:
            continue
        end = _utc(row.get("ends_at")) or start
        if end < now:
            continue
        active = start < now <= end
        importance = _IMPORTANCE_ORDER.get(_text(row.get("importance")).lower(), 3)
        certainty = _CERTAINTY_ORDER.get(_text(row.get("certainty_class")).lower(), 9)
        key = (importance, certainty, 0 if active else 1, start, _text(row.get("event_id")), position)
        candidates.append((key, position, row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][2]


def group_timeline_events(
    events: pd.DataFrame,
    *,
    now_utc: pd.Timestamp,
    viewer_timezone: str,
) -> tuple[TimelineMonthGroup, ...]:
    """Group one already-selected event frame by local start month."""

    now = _utc(now_utc)
    if now is None:
        raise ValueError("now_utc must be timezone-aware")
    if not events.empty:
        filtered = apply_event_filters(events, EventFilters(horizon="all", now_utc=now))
    else:
        filtered = events.copy()
    groups: dict[str, list[CatalystView]] = {}
    for _, row in filtered.iterrows():
        view = catalyst_view_for_event(None, row, now_utc=now, viewer_timezone=viewer_timezone)
        if view is None:
            continue
        local = view.starts_at.tz_convert(viewer_timezone)
        key = local.strftime("%Y-%m")
        groups.setdefault(key, []).append(view)
    return tuple(
        TimelineMonthGroup(
            month_key=key,
            month_label=pd.Timestamp(f"{key}-01").strftime("%B %Y"),
            events=tuple(values),
        )
        for key, values in sorted(groups.items())
    )


def _chips_html(labels: tuple[TickerChip, ...]) -> str:
    if not labels:
        return ""
    visible = labels[:5]
    extra = len(labels) - len(visible)
    result = ''.join(f'<span class="ct-chip" title="{escape(chip.title, quote=True)}">{escape(chip.label)}</span>' for chip in visible)
    if extra:
        result += f'<span class="ct-chip">+{extra} more</span>'
    return f'<div class="ct-chips">{result}</div>'


def catalyst_html(view: CatalystView, *, viewer_timezone: str) -> str:
    certainty = view.certainty_class or "unclassified"
    badge_class = certainty if certainty in {"hard", "provisional", "thesis_checkpoint", "observed"} else ""
    confidence = "—" if view.confidence is None else f"{view.confidence:.2f}"
    meta = (
        f'<span class="ct-badge ct-badge--{badge_class}">{escape(certainty_label(certainty))}</span>'
        f'<span class="ct-badge">Status · {escape(view.status or "unclassified")}</span>'
        f'<span class="ct-badge">Confidence · {escape(confidence)}</span>'
        f'<span class="ct-badge">Importance · {escape(view.importance or "unclassified")}</span>'
    )
    source = source_badges_html(view.source_badges, viewer_timezone=viewer_timezone)
    chips = _chips_html(view.ticker_chips)
    questions = ""
    if view.watch_questions:
        items = "".join(f"<li>{escape(question)}</li>" for question in view.watch_questions)
        questions = f'<details class="ct-watch"><summary>Watch questions ({len(view.watch_questions)})</summary><ul>{items}</ul></details>'
    description = f'<div class="ct-event-description">{escape(view.description)}</div>' if view.description else ""
    return (
        f'<div class="ct-event-row ct-event-row--{escape(badge_class)}">'
        f'<div><div class="ct-event-date">{escape(view.display_window)}</div><div class="ct-t-minus">{escape(view.t_minus)}</div></div>'
        f'<div><div class="ct-event-title">{escape(view.title)}</div>{description}{chips}{questions}</div>'
        f'<div class="ct-event-meta"><div class="ct-badges">{meta}</div>{source}</div>'
        f'</div>'
    )


def render_catalyst(view: CatalystView, *, viewer_timezone: str) -> None:
    st.markdown(catalyst_html(view, viewer_timezone=viewer_timezone), unsafe_allow_html=True)


__all__ = [
    "CatalystView",
    "TimelineMonthGroup",
    "TickerChip",
    "catalyst_html",
    "catalyst_view_for_event",
    "format_event_window",
    "group_timeline_events",
    "render_catalyst",
    "resolve_ticker_chips",
    "select_next_catalyst",
]
