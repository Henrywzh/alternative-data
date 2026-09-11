"""Shared Phase 1 semantics for scope, catalyst lifecycle and snapshots.

This module is deliberately pure: it does not read files, call providers, or
touch Streamlit state.  Page and repository readers use these functions so a
date, snapshot boundary, or page-local scope cannot acquire different
meanings depending on which surface renders it.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
import re
from typing import Any, Literal, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from .models import ControlTowerSnapshot, EventFilters, PageFilterContext


GLOBAL_AI_BASKET_ID = "AI_BOTTLENECKS_GLOBAL"

CatalystLifecycle = Literal[
    "future",
    "active",
    "expired",
    "completed",
    "cancelled",
    "unavailable",
]


@dataclass(frozen=True, slots=True)
class CatalystInterval:
    """Canonical UTC interval plus the boundary semantics used to classify it."""

    start_utc: pd.Timestamp | None
    end_utc: pd.Timestamp | None
    end_inclusive: bool
    date_only: bool
    valid: bool
    reason: str = ""


def _missing(value: object) -> bool:
    if value is None or value is pd.NaT or value is pd.NA:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(result) if isinstance(result, bool) else False


def source_timezone(value: object) -> ZoneInfo:
    """Resolve an event's declared timezone, failing safely to UTC."""

    if isinstance(value, ZoneInfo):
        return value
    text = "" if _missing(value) else str(value).strip()
    if not text:
        return ZoneInfo("UTC")
    try:
        return ZoneInfo(text)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return ZoneInfo("UTC")


def parse_timestamp_utc(
    value: object,
    *,
    source_tz: object | None = None,
) -> pd.Timestamp | None:
    """Parse an instant into UTC.

    Naive/date-only values are accepted only when a source timezone is
    supplied.  This keeps knowledge timestamps strict while allowing event
    dates to be interpreted as source-local calendar values.
    """

    if _missing(value):
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        if source_tz is None:
            return None
        try:
            parsed = parsed.tz_localize(source_timezone(source_tz))
        except (TypeError, ValueError, OverflowError):
            return None
    try:
        return parsed.tz_convert("UTC")
    except (TypeError, ValueError, OverflowError):
        return None


def _is_date_only(value: object) -> bool:
    if isinstance(value, date) and not isinstance(value, datetime):
        return True
    if _missing(value):
        return False
    text = str(value).strip()
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", text))


def _next_local_midnight(start_utc: pd.Timestamp, tz: ZoneInfo) -> pd.Timestamp:
    local_date = start_utc.tz_convert(tz).date()
    next_date = local_date + timedelta(days=1)
    return pd.Timestamp(next_date).tz_localize(tz).tz_convert("UTC")


def resolve_catalyst_interval(
    starts_at: object,
    ends_at: object,
    date_precision: object = None,
    source_tz: object | None = None,
) -> CatalystInterval:
    """Normalize an event into a source-aware UTC interval.

    ``date``/``day`` rows with no end represent the complete source-local
    calendar day.  Other rows with no end are genuinely open-ended.  Explicit
    timestamp endpoints are inclusive, matching the Phase 1 contract; the
    inferred next-local-midnight boundary is half-open so the following day is
    not accidentally treated as active.
    """

    tz = source_timezone(source_tz)
    precision = "" if _missing(date_precision) else str(date_precision).strip().lower()
    start = parse_timestamp_utc(starts_at, source_tz=tz)
    if start is None:
        return CatalystInterval(None, None, True, False, False, "missing or invalid start")

    end = parse_timestamp_utc(ends_at, source_tz=tz)
    date_precision = precision in {"date", "day"}
    date_only = date_precision or _is_date_only(starts_at) or _is_date_only(ends_at)
    end_inclusive = True

    if end is None and (date_precision or _is_date_only(starts_at)):
        end = _next_local_midnight(start, tz)
        end_inclusive = False
        date_only = True
    elif end is not None and _is_date_only(ends_at):
        # A source-local end date includes that whole calendar day.
        # Advance the local calendar date before converting back to UTC.  A
        # fixed 24-hour delta is wrong across DST transitions (the next local
        # midnight may be 23 or 25 elapsed hours away).
        end = _next_local_midnight(end, tz)
        end_inclusive = False
        date_only = True

    if end is not None and end < start:
        return CatalystInterval(
            start,
            end,
            end_inclusive,
            date_only,
            False,
            "end precedes start",
        )
    return CatalystInterval(start, end, end_inclusive, date_only, True)


def classify_catalyst(
    starts_at: object,
    ends_at: object,
    now_utc: object,
    *,
    date_precision: object = None,
    source_tz: object | None = None,
    status: object = None,
    event_type: object = None,
) -> CatalystLifecycle:
    """Return one canonical lifecycle state for a catalyst row."""

    status_text = "" if _missing(status) else str(status).strip().lower()
    event_type_text = "" if _missing(event_type) else str(event_type).strip().lower()
    if status_text == "completed":
        return "completed"
    if status_text == "cancelled":
        return "cancelled"
    if status_text == "unavailable" or event_type_text == "coverage_gap":
        return "unavailable"

    interval = resolve_catalyst_interval(
        starts_at,
        ends_at,
        date_precision=date_precision,
        source_tz=source_tz,
    )
    now = parse_timestamp_utc(now_utc)
    if not interval.valid or interval.start_utc is None or now is None:
        return "unavailable"
    if now < interval.start_utc:
        return "future"
    if interval.end_utc is None:
        return "active"
    if interval.end_inclusive:
        return "active" if now <= interval.end_utc else "expired"
    return "active" if now < interval.end_utc else "expired"


def catalyst_state_for_row(row: Mapping[str, Any], now_utc: object) -> CatalystLifecycle:
    return classify_catalyst(
        row.get("starts_at"),
        row.get("ends_at"),
        now_utc,
        date_precision=row.get("date_precision"),
        source_tz=row.get("source_timezone"),
        status=row.get("status"),
        event_type=row.get("event_type"),
    )


def page_filter_context(
    page_scope: str,
    global_filters: EventFilters,
    *,
    selected_entity_id: str | None = None,
    selected_listing_id: str | None = None,
) -> PageFilterContext:
    """Resolve global filters and deliberate page-local scope in one place.

    The AI Bottlenecks page is a global theme surface.  Its own basket and
    region controls must not inherit the app's current Stage 1 company filter
    silently, while time/quality filters remain useful and consistent.
    """

    label = str(page_scope).strip()
    key = label.casefold().replace("_", " ")
    if key in {"ai bottlenecks", "ai bottlenecks page", "global ai"}:
        effective = replace(
            global_filters,
            basket_id=(GLOBAL_AI_BASKET_ID,),
            country=(),
            scope=(),
            membership_tier=(),
        )
        return PageFilterContext(
            page_scope=label or "AI Bottlenecks",
            scope_kind="global_ai",
            scope_label="Global AI Bottlenecks",
            global_filters=global_filters,
            effective_filters=effective,
            overridden_dimensions=("basket_id", "country", "scope", "membership_tier"),
            selected_entity_id=selected_entity_id,
            selected_listing_id=selected_listing_id,
        )
    if key == "company":
        return PageFilterContext(
            page_scope=label or "Company",
            scope_kind="company",
            scope_label="Selected company/listing",
            global_filters=global_filters,
            effective_filters=global_filters,
            selected_entity_id=selected_entity_id,
            selected_listing_id=selected_listing_id,
        )
    return PageFilterContext(
        page_scope=label,
        scope_kind="global",
        scope_label=label or "Global universe",
        global_filters=global_filters,
        effective_filters=global_filters,
        selected_entity_id=selected_entity_id,
        selected_listing_id=selected_listing_id,
    )


# Knowledge/observation clocks used for frozen-vintage filtering.  Economic
# dates such as an announced future execution date are deliberately absent:
# they describe when something happens, not when the row became knowable.
SNAPSHOT_ARTIFACT_TIME_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "events.parquet": ("source_published_at", "first_observed_at", "last_verified_at"),
    "macro_observations.parquet": (
        "release_at", "first_observed_at", "source_published_at", "retrieved_at_utc",
    ),
    "consensus_snapshots.parquet": (
        "snapshot_at", "provider_asof", "retrieved_at_utc",
    ),
    "consensus_revisions.parquet": (
        "current_snapshot_at", "provider_asof", "prior_snapshot_at",
        "prior_provider_asof", "retrieved_at_utc",
    ),
    "quote_snapshots.parquet": ("quote_timestamp", "retrieved_at_utc"),
    "price_bars.parquet": ("bar_date", "retrieved_at_utc"),
    "news_filings.parquet": ("published_at", "first_observed_at"),
    "official_filings.parquet": (
        "published_at", "accepted_at", "retrieved_at_utc",
    ),
    "earnings_calendar.parquet": ("published_at", "retrieved_at_utc"),
    "earnings_actuals.parquet": (
        "filing_at", "published_at", "retrieved_at_utc",
    ),
    "corporate_actions.parquet": (
        "filing_date", "published_at", "retrieved_at_utc",
    ),
    "valuation_snapshots.parquet": (
        "valuation_at", "numerator_at_utc", "numerator_retrieved_at_utc",
        "denominator_at_utc", "denominator_provider_asof_utc",
        "denominator_retrieved_at_utc", "fx_snapshot_at_utc", "fx_retrieved_at_utc",
        "retrieved_at_utc",
    ),
    "internal_estimates.parquet": (
        "effective_asof", "recorded_at_utc", "reviewed_at_utc",
    ),
    "thesis_claims.parquet": ("last_reviewed_at_utc",),
    "evidence_items.parquet": ("published_at", "observed_at_utc"),
    "source_health.parquet": (
        "first_observation_at", "latest_observation_at", "source_latest_at",
        "retrieved_at_utc", "completed_at",
    ),
}


def filter_frame_to_as_of(
    frame: pd.DataFrame | None,
    as_of_utc: object,
    *,
    timestamp_columns: tuple[str, ...] = (),
    keep_undated: bool = True,
) -> pd.DataFrame:
    """Exclude rows with any known timestamp after a frozen boundary.

    A row with several clocks is usable only if every populated clock is at or
    before the boundary.  Rows with no populated clock are retained so a
    missing optional timestamp does not become an invented coverage failure;
    malformed non-empty timestamps are retained and remain visible for QA.
    """

    if frame is None:
        return pd.DataFrame()
    reference = parse_timestamp_utc(as_of_utc)
    if reference is None:
        raise ValueError("as_of_utc must be timezone-aware")
    result = frame.copy(deep=True)
    if result.empty:
        return result
    columns = tuple(column for column in timestamp_columns if column in result.columns)
    if not columns:
        return result

    future = pd.Series(False, index=result.index, dtype="boolean")
    observed = pd.Series(False, index=result.index, dtype="boolean")
    for column in columns:
        parsed = pd.to_datetime(result[column], utc=True, errors="coerce")
        present = parsed.notna()
        observed |= present
        future |= parsed.gt(reference).fillna(False)
    mask = ~future
    if not keep_undated:
        mask &= observed
    return result.loc[mask.fillna(False)].copy().reset_index(drop=True)


def filter_artifact_frames_to_as_of(
    frames: Mapping[str, pd.DataFrame],
    as_of_utc: object,
) -> dict[str, pd.DataFrame]:
    """Apply the common snapshot predicate to loaded artifact frames."""

    result = dict(frames)
    for artifact, columns in SNAPSHOT_ARTIFACT_TIME_COLUMNS.items():
        if artifact in result:
            result[artifact] = filter_frame_to_as_of(
                result[artifact],
                as_of_utc,
                timestamp_columns=columns,
            )
    return result


def _filter_id_relation(
    frame: pd.DataFrame,
    column: str,
    allowed: set[str],
) -> pd.DataFrame:
    if frame.empty or column not in frame.columns:
        return frame.copy(deep=True)
    values = frame[column].astype("string")
    return frame.loc[values.isin(allowed)].copy().reset_index(drop=True)


def filter_loaded_frames_to_as_of(
    frames: Mapping[str, pd.DataFrame],
    as_of_utc: object,
) -> dict[str, pd.DataFrame]:
    """Filter source frames and remove dependent rows orphaned by the cut.

    Link tables have no observation clock of their own.  When a future event,
    claim, or evidence item is removed, its links and watch questions must be
    removed with it before repository referential-integrity checks run.
    """

    result = filter_artifact_frames_to_as_of(frames, as_of_utc)
    events = result.get("events.parquet", pd.DataFrame())
    event_ids = set(events.get("event_id", pd.Series(dtype="string")).astype("string"))
    for artifact in (
        "event_entity_links.parquet",
        "event_basket_links.parquet",
        "event_watch_questions.parquet",
    ):
        if artifact in result:
            result[artifact] = _filter_id_relation(result[artifact], "event_id", event_ids)

    claims = result.get("thesis_claims.parquet", pd.DataFrame())
    claim_ids = set(claims.get("claim_id", pd.Series(dtype="string")).astype("string"))
    if "thesis_watch_questions.parquet" in result:
        result["thesis_watch_questions.parquet"] = _filter_id_relation(
            result["thesis_watch_questions.parquet"], "claim_id", claim_ids
        )
    if "claim_evidence_links.parquet" in result:
        links = result["claim_evidence_links.parquet"]
        links = _filter_id_relation(links, "claim_id", claim_ids)
        evidence = result.get("evidence_items.parquet", pd.DataFrame())
        evidence_ids = set(evidence.get("evidence_id", pd.Series(dtype="string")).astype("string"))
        result["claim_evidence_links.parquet"] = _filter_id_relation(
            links, "evidence_id", evidence_ids
        )
    return result


def filter_snapshot_to_as_of(snapshot: ControlTowerSnapshot) -> ControlTowerSnapshot:
    """Return a copy whose data marts cannot leak rows after ``as_of_utc``."""

    frames = {
        f"{attribute}.parquet": getattr(snapshot, attribute)
        for attribute in (
            "events", "event_entity_links", "event_basket_links",
            "event_watch_questions", "macro_observations", "consensus_snapshots",
            "consensus_revisions", "quote_snapshots", "price_bars", "news_filings",
            "official_filings", "earnings_calendar", "earnings_actuals",
            "corporate_actions", "valuation_snapshots", "internal_estimates",
            "thesis_claims", "thesis_watch_questions", "evidence_items",
            "claim_evidence_links", "source_health",
        )
        if hasattr(snapshot, attribute)
    }
    filtered = filter_loaded_frames_to_as_of(frames, snapshot.as_of_utc)
    updates = {
        artifact.removesuffix(".parquet"): frame
        for artifact, frame in filtered.items()
        if hasattr(snapshot, artifact.removesuffix(".parquet"))
    }
    return replace(snapshot, **updates)


__all__ = [
    "CatalystInterval",
    "CatalystLifecycle",
    "GLOBAL_AI_BASKET_ID",
    "SNAPSHOT_ARTIFACT_TIME_COLUMNS",
    "catalyst_state_for_row",
    "classify_catalyst",
    "filter_artifact_frames_to_as_of",
    "filter_frame_to_as_of",
    "filter_loaded_frames_to_as_of",
    "filter_snapshot_to_as_of",
    "page_filter_context",
    "parse_timestamp_utc",
    "resolve_catalyst_interval",
    "source_timezone",
]
