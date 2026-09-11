"""Deterministic, non-mutating event filtering and ordering."""

from __future__ import annotations

import pandas as pd

from .models import EventFilters
from .semantics import catalyst_state_for_row, resolve_catalyst_interval


_IMPORTANCE_RANK = {"high": 0, "medium": 1, "low": 2}
_HORIZON_DAYS = {"7d": 7, "30d": 30, "90d": 90}


def _as_utc(value: object) -> pd.Timestamp | pd.NaT:
    if value is None or value is pd.NaT:
        return pd.NaT
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return pd.NaT
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return pd.NaT
    return parsed.tz_convert("UTC")


def _tuple_values(value: object) -> tuple[str, ...]:
    if value is None or value is pd.NA:
        return ()
    if isinstance(value, (tuple, list, set, frozenset)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


def _relation_mask(frame: pd.DataFrame, column: str, selected: tuple[str, ...]) -> pd.Series:
    if not selected:
        return pd.Series(True, index=frame.index)
    selected_set = set(selected)
    return frame[column].map(lambda value: bool(set(_tuple_values(value)) & selected_set))


def _scalar_mask(frame: pd.DataFrame, column: str, selected: tuple[str, ...]) -> pd.Series:
    if not selected:
        return pd.Series(True, index=frame.index)
    if column not in frame.columns:
        return pd.Series(False, index=frame.index)
    values = frame[column].astype("string").str.strip().str.lower()
    return values.isin(selected)


def _normalise_relation_column(frame: pd.DataFrame, column: str, *, upper: bool = False) -> None:
    if column not in frame.columns:
        frame[column] = [() for _ in range(len(frame))]
        return
    result: list[tuple[str, ...]] = []
    for value in frame[column]:
        values = {str(item).strip() for item in _tuple_values(value) if str(item).strip()}
        if upper:
            values = {item.upper() for item in values}
        result.append(tuple(sorted(values)))
    frame[column] = result


def _catalyst_mask(
    frame: pd.DataFrame,
    *,
    now_utc: object | None = None,
) -> pd.Series:
    event_type = frame.get("event_type", pd.Series("", index=frame.index)).astype("string").str.strip().str.lower()
    status = frame.get("status", pd.Series("", index=frame.index)).astype("string").str.strip().str.lower()
    mask = event_type.ne("coverage_gap") & ~status.isin({"unavailable", "cancelled"})
    if now_utc is not None:
        mask &= frame.apply(
            lambda row: catalyst_state_for_row(row.to_dict(), now_utc)
            in {"future", "active"},
            axis=1,
        )
    return mask


def superseded_event_ids(events: pd.DataFrame) -> set[str]:
    """Return event ids that another row in the same frame supersedes.

    Only ids that resolve to a row inside the frame are returned, so a
    dangling ``supersedes_event_id`` never hides a live event.
    """

    if events.empty or "supersedes_event_id" not in events.columns:
        return set()
    known = set(events["event_id"].astype("string"))
    superseded: set[str] = set()
    for value in events["supersedes_event_id"]:
        if value is None:
            continue
        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass
        text = str(value).strip()
        if text and text in known:
            superseded.add(text)
    return superseded


def _horizon_mask(frame: pd.DataFrame, filters: EventFilters) -> pd.Series:
    intervals = frame.apply(
        lambda row: resolve_catalyst_interval(
            row.get("starts_at"),
            row.get("ends_at"),
            date_precision=row.get("date_precision"),
            source_tz=row.get("source_timezone"),
        ),
        axis=1,
    )
    starts = intervals.map(lambda interval: interval.start_utc)
    ends = intervals.map(lambda interval: interval.end_utc)
    usable = intervals.map(lambda interval: interval.valid and interval.start_utc is not None)
    if filters.horizon == "all":
        return usable

    assert filters.now_utc is not None
    now = _as_utc(filters.now_utc)
    if now is pd.NaT:
        return pd.Series(False, index=frame.index)
    if filters.horizon == "long_range":
        cutoff = now + pd.Timedelta(days=90)
        # An open-ended event has no evidence that it extends beyond the
        # long-range boundary; keep it out of this specialised horizon.
        return usable & ends.notna() & ends.gt(cutoff)

    cutoff = now + pd.Timedelta(days=_HORIZON_DAYS[filters.horizon])
    # Half-open horizon: [now, cutoff). An event ending exactly at the upper
    # bound remains visible only when its start is before that bound.  Open
    # ended events remain visible; inferred date-only ends are already
    # represented as half-open intervals by the canonical resolver.
    return usable & starts.lt(cutoff) & (ends.isna() | ends.ge(now))


def _confidence_mask(frame: pd.DataFrame, filters: EventFilters) -> pd.Series:
    mask = pd.Series(True, index=frame.index)
    if filters.confidence:
        if "confidence" not in frame.columns:
            return pd.Series(False, index=frame.index)
        values = pd.to_numeric(frame["confidence"], errors="coerce")
        requested: set[float] = set()
        for value in filters.confidence:
            try:
                requested.add(float(value))
            except ValueError:
                raise ValueError(f"invalid confidence value: {value!r}") from None
        mask &= values.isin(requested)
    if filters.confidence_min is not None:
        if "confidence" not in frame.columns:
            return pd.Series(False, index=frame.index)
        mask &= pd.to_numeric(frame["confidence"], errors="coerce").ge(filters.confidence_min)
    return mask


def apply_event_filters(events: pd.DataFrame, filters: EventFilters) -> pd.DataFrame:
    """Apply global filters and return one stably ordered row per event.

    Coverage gaps/unavailable/cancelled rows remain in the repository snapshot
    but are never timeline-eligible. With a reference time, expired and
    completed rows are also retained only for explicit audit views. Long-range
    uses an explicit event end beyond the 90-day cutoff; it does not invent a
    second row or truncate the original range.
    """

    frame = events.copy(deep=True)
    for column, upper in (
        ("related_entity_ids", True),
        ("related_listing_ids", True),
        ("related_basket_ids", True),
        ("related_index_ids", True),
        ("related_countries", True),
        ("membership_tiers", False),
    ):
        _normalise_relation_column(frame, column, upper=upper)

    eligible = _catalyst_mask(frame, now_utc=filters.now_utc)
    # Superseded ledger rows are excluded from every catalyst presentation
    # (timeline, next catalyst, flight deck). The explicit False audit view
    # keeps the original eligible semantics for excluded rows.
    if filters.catalyst_eligible is not False:
        superseded = superseded_event_ids(frame)
        if superseded:
            eligible &= ~frame["event_id"].astype("string").isin(superseded)
    # The normal timeline is catalyst-eligible. Explicit False is an audit
    # view for excluded ledger rows, including coverage gaps.
    mask = eligible if filters.catalyst_eligible is not False else pd.Series(True, index=frame.index)
    mask &= _horizon_mask(frame, filters)
    mask &= _relation_mask(frame, "related_basket_ids", filters.basket_id)
    mask &= _relation_mask(frame, "related_countries", filters.country)
    mask &= _relation_mask(frame, "membership_tiers", filters.membership_tier)
    mask &= _scalar_mask(frame, "scope", filters.scope)
    mask &= _scalar_mask(frame, "certainty_class", filters.certainty_class)
    mask &= _scalar_mask(frame, "status", filters.status)
    mask &= _scalar_mask(frame, "importance", filters.importance)
    mask &= _confidence_mask(frame, filters)
    if filters.catalyst_eligible is not None:
        mask &= eligible.eq(filters.catalyst_eligible)

    result = frame.loc[mask].copy()
    if result.empty:
        return result.reset_index(drop=True)

    result["__starts_at_utc"] = result["starts_at"].map(_as_utc)
    importance = result.get("importance", pd.Series(pd.NA, index=result.index)).astype("string").str.strip().str.lower()
    result["__importance_rank"] = importance.map(_IMPORTANCE_RANK).fillna(3).astype(int)
    result["__input_position"] = result.index.to_series()
    result = result.sort_values(
        by=["__starts_at_utc", "__importance_rank", "event_id", "__input_position"],
        ascending=[True, True, True, True],
        kind="mergesort",
        na_position="last",
    )
    return result.drop(columns=["__starts_at_utc", "__importance_rank", "__input_position"]).reset_index(drop=True)


__all__ = ["apply_event_filters", "superseded_event_ids"]
