"""One registry-backed rule for listing-scoped collection and display."""

from __future__ import annotations

from typing import Any

import pandas as pd


def _blank(value: Any) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    try:
        missing = pd.isna(value)
        if not hasattr(missing, "__len__") and bool(missing):
            return True
    except (TypeError, ValueError):
        pass
    return not str(value).strip()


def _text(value: Any) -> str:
    return "" if _blank(value) else str(value).strip()


def _as_of_date(as_of: object) -> pd.Timestamp:
    timestamp = pd.Timestamp(as_of)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    return timestamp.tz_convert("UTC").tz_localize(None).normalize()


def _date_value(value: Any) -> pd.Timestamp | None:
    if _blank(value):
        return None
    parsed = pd.to_datetime(value, format="%Y-%m-%d", errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def _boolean_value(value: Any) -> bool | None:
    if _blank(value):
        return None
    if isinstance(value, bool):
        return value
    normalized = _text(value).casefold()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def listing_eligibility_reason(row: Any, as_of: object) -> str | None:
    """Return the first explicit reason a listing cannot be collected/displayed.

    The rule is intentionally strict for listing rows: mapping must be
    verified, collection must be enabled, status must be active, and the
    half-open active interval must contain ``as_of``.  Entity-only rows do not
    pass through this function; callers that support entity scope preserve a
    blank ``listing_id`` separately.
    """

    listing_id = _text(row.get("listing_id"))
    if not listing_id:
        return "blank listing_id is entity-only, not a listing-scoped row"
    if "mapping_status" not in row or _text(row.get("mapping_status")).casefold() != "verified":
        return f"mapping_status={_text(row.get('mapping_status')) or '<blank>'}; requires verified"
    eligible = _boolean_value(row.get("collection_eligible"))
    if eligible is not True:
        return f"collection_eligible={_text(row.get('collection_eligible')) or '<blank>'}; requires true"
    if "listing_status" not in row or _text(row.get("listing_status")).casefold() != "active":
        return f"listing_status={_text(row.get('listing_status')) or '<blank>'}; requires active"

    as_of_date = _as_of_date(as_of)
    active_from = _date_value(row.get("active_from"))
    if not _blank(row.get("active_from")) and active_from is None:
        return f"active_from={_text(row.get('active_from'))!r} is invalid"
    active_to = _date_value(row.get("active_to"))
    if not _blank(row.get("active_to")) and active_to is None:
        return f"active_to={_text(row.get('active_to'))!r} is invalid"
    if active_from is not None and active_from > as_of_date:
        return f"active_from={active_from.date()} is after as_of={as_of_date.date()}"
    if active_to is not None and as_of_date >= active_to:
        return f"active_to={active_to.date()} is not after as_of={as_of_date.date()}"
    return None


def filter_eligible_listings(
    listings: pd.DataFrame,
    as_of: object,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Filter listing registry rows and return explicit rejection diagnostics."""

    if listings is None or listings.empty:
        return listings.copy() if listings is not None else pd.DataFrame(), []
    kept_indices: list[Any] = []
    rejected: list[dict[str, object]] = []
    for index, row in listings.iterrows():
        reason = listing_eligibility_reason(row, as_of)
        if reason is None:
            kept_indices.append(index)
        else:
            rejected.append(
                {
                    "row_index": index,
                    "listing_id": _text(row.get("listing_id")),
                    "entity_id": _text(row.get("entity_id")),
                    "reason": reason,
                }
            )
    return listings.loc[kept_indices].copy(), rejected


def eligible_listing_ids(listings: pd.DataFrame, as_of: object) -> set[str]:
    """Return registry listing IDs eligible for listing-scoped work."""

    filtered, _rejected = filter_eligible_listings(listings, as_of)
    if filtered.empty or "listing_id" not in filtered.columns:
        return set()
    return {
        _text(value)
        for value in filtered["listing_id"]
        if _text(value)
    }


def filter_listing_scoped_rows(
    frame: pd.DataFrame,
    listings: pd.DataFrame,
    as_of: object,
    *,
    preserve_entity_only: bool = True,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    """Reject ineligible listing rows while retaining valid entity-only rows."""

    if frame is None or frame.empty:
        return frame.copy() if frame is not None else pd.DataFrame(), []
    eligible, listing_rejections = filter_eligible_listings(listings, as_of)
    eligible_by_id = {
        _text(row.get("listing_id")): _text(row.get("entity_id"))
        for _, row in eligible.iterrows()
    }
    reasons_by_id = {
        _text(item.get("listing_id")): _text(item.get("reason"))
        for item in listing_rejections
        if _text(item.get("listing_id"))
    }
    kept_indices: list[Any] = []
    rejected: list[dict[str, object]] = []
    for index, row in frame.iterrows():
        listing_id = _text(row.get("listing_id"))
        entity_id = _text(row.get("entity_id"))
        if not listing_id:
            if preserve_entity_only:
                kept_indices.append(index)
            else:
                rejected.append(
                    {
                        "row_index": index,
                        "listing_id": "",
                        "entity_id": entity_id,
                        "reason": "entity-only row is not valid for this listing-scoped mart",
                    }
                )
            continue
        if listing_id not in eligible_by_id:
            rejected.append(
                {
                    "row_index": index,
                    "listing_id": listing_id,
                    "entity_id": entity_id,
                    "reason": reasons_by_id.get(listing_id, "listing_id is not present in the registry"),
                }
            )
            continue
        registered_entity = eligible_by_id[listing_id]
        if entity_id and registered_entity and entity_id != registered_entity:
            rejected.append(
                {
                    "row_index": index,
                    "listing_id": listing_id,
                    "entity_id": entity_id,
                    "reason": f"listing belongs to entity_id={registered_entity}, not {entity_id}",
                }
            )
            continue
        kept_indices.append(index)
    return frame.loc[kept_indices].copy(), rejected


__all__ = [
    "eligible_listing_ids",
    "filter_eligible_listings",
    "filter_listing_scoped_rows",
    "listing_eligibility_reason",
]
