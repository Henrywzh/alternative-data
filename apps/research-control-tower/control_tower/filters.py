"""Deterministic, non-mutating event filtering and ordering."""

from __future__ import annotations

from typing import Any

import pandas as pd

from .models import EventFilters


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


def _catalyst_mask(frame: pd.DataFrame) -> pd.Series:
    event_type = frame.get("event_type", pd.Series("", index=frame.index)).astype("string").str.strip().str.lower()
    status = frame.get("status", pd.Series("", index=frame.index)).astype("string").str.strip().str.lower()
    return event_type.ne("coverage_gap") & ~status.isin({"unavailable", "cancelled"})


def _horizon_mask(frame: pd.DataFrame, filters: EventFilters) -> pd.Series:
    starts = frame["starts_at"].map(_as_utc) if "starts_at" in frame.columns else pd.Series(pd.NaT, index=frame.index)
    ends = frame["ends_at"].map(_as_utc) if "ends_at" in frame.columns else pd.Series(pd.NaT, index=frame.index)
    ends = ends.where(ends.notna(), starts)
    usable = starts.notna()
    if filters.horizon == "all":
        return usable

    assert filters.now_utc is not None
    now = filters.now_utc
    if filters.horizon == "long_range":
        cutoff = now + pd.Timedelta(days=90)
        return usable & ends.gt(cutoff)

    cutoff = now + pd.Timedelta(days=_HORIZON_DAYS[filters.horizon])
    # Half-open horizon: [now, cutoff). An event ending exactly at the upper
    # bound remains visible only when its start is before that bound.
    return usable & starts.lt(cutoff) & ends.ge(now)


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
    but are never timeline-eligible. Long-range uses the explicit event end
    (or start for an exact event) beyond the 90-day cutoff; it does not invent
    a second row or truncate the original range.
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

    eligible = _catalyst_mask(frame)
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


__all__ = ["apply_event_filters"]
