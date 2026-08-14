"""Data coverage matrix models and builder for Control Tower."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from .models import ControlTowerSnapshot

CoverageStatusCode = Literal["available", "unavailable", "partial"]


@dataclass(frozen=True, slots=True)
class CoverageRow:
    category: str
    status: str
    status_code: CoverageStatusCode
    details: str
    record_count: int = 0
    linked_count: int | None = None


@dataclass(frozen=True, slots=True)
class DataCoverageSummary:
    rows: tuple[CoverageRow, ...]


def _is_missing_scalar(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return isinstance(missing, bool) and missing


def _relation_values(value: object) -> tuple[str, ...]:
    """Normalise relation cells from parquet/list and JSON-string encodings."""

    if _is_missing_scalar(value):
        return ()
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        if text.startswith(("[", "{")):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                return _relation_values(parsed)
        return (text,)
    if hasattr(value, "tolist"):
        return _relation_values(value.tolist())
    if isinstance(value, dict):
        return ()
    if isinstance(value, (list, tuple, set, frozenset)):
        values: set[str] = set()
        for item in value:
            values.update(_relation_values(item))
        return tuple(sorted(values))
    text = str(value).strip()
    return (text,) if text else ()


def _is_non_empty_relation(value: object) -> bool:
    return bool(_relation_values(value))


def _linked_row_count(frame: pd.DataFrame, columns: tuple[str, ...]) -> int:
    if frame.empty:
        return 0
    return sum(
        any(_is_non_empty_relation(row.get(column)) for column in columns)
        for _, row in frame.iterrows()
    )


def _linked_event_count(snapshot: ControlTowerSnapshot) -> int:
    if snapshot.events.empty or "event_id" not in snapshot.events.columns:
        return 0
    linked_event_ids: set[str] = set()
    for frame in (snapshot.event_entity_links, snapshot.event_basket_links):
        if not frame.empty and "event_id" in frame.columns:
            linked_event_ids.update(frame["event_id"].dropna().astype(str))
    for _, row in snapshot.events.iterrows():
        if any(
            _is_non_empty_relation(row.get(column))
            for column in (
                "related_entity_ids",
                "related_listing_ids",
                "related_basket_ids",
            )
        ):
            linked_event_ids.add(str(row.get("event_id")))
    return int(snapshot.events["event_id"].astype(str).isin(linked_event_ids).sum())


def build_data_coverage_summary(snapshot: ControlTowerSnapshot) -> DataCoverageSummary:
    """Build a deterministic matrix of available records and explicit gaps.

    Counts describe record presence only. Linkage counts are emitted only when
    the snapshot contains an actual relation field or link registry; they are
    not a data-quality or investment-signal score.
    """

    quote_snapshots = snapshot.quote_snapshots
    quote_count = len(quote_snapshots) if not quote_snapshots.empty else 0
    if quote_count:
        linked_quotes = _linked_row_count(quote_snapshots, ("listing_id",))
        quote_status: CoverageStatusCode = (
            "available" if linked_quotes == quote_count else "partial"
        )
        rows: list[CoverageRow] = [
            CoverageRow(
                category="Price / Market Quotes",
                status="Available" if quote_status == "available" else "Partial linkage",
                status_code=quote_status,
                details=(
                    f"{quote_count} latest quote snapshot{'s' if quote_count != 1 else ''} present; "
                    f"{linked_quotes} carry listing identifiers. Intraday bars are not yet in the V1 mart."
                ),
                record_count=quote_count,
                linked_count=linked_quotes,
            )
        ]
    else:
        rows = [
            CoverageRow(
                category="Price / Market Bars",
                status="Unavailable",
                status_code="unavailable",
                details="No price or market-bars artifact is part of the current V1 data contract.",
            )
        ]
    rows.extend([
        CoverageRow(
            category="Earnings Actuals",
            status="Unavailable",
            status_code="unavailable",
            details="No earnings-actuals mart is part of the current V1 data contract; event-level actual fields are separate.",
        ),
    ])

    snapshots = snapshot.consensus_snapshots
    revisions = snapshot.consensus_revisions
    snapshot_count = len(snapshots) if not snapshots.empty else 0
    revision_count = len(revisions) if not revisions.empty else 0
    consensus_count = snapshot_count + revision_count
    if consensus_count:
        linked_count = _linked_row_count(snapshots, ("entity_id", "listing_id"))
        linked_count += _linked_row_count(revisions, ("entity_id", "listing_id"))
        status_code: CoverageStatusCode = (
            "available" if linked_count == consensus_count else "partial"
        )
        rows.append(
            CoverageRow(
                category="Consensus Data",
                status="Available" if status_code == "available" else "Partial linkage",
                status_code=status_code,
                details=(
                    f"{snapshot_count} consensus snapshot{'s' if snapshot_count != 1 else ''} and "
                    f"{revision_count} revision record{'s' if revision_count != 1 else ''} present; "
                    f"{linked_count} of {consensus_count} rows carry entity/listing identifiers. "
                    "Source quality and entitlement are not assessed here."
                ),
                record_count=consensus_count,
                linked_count=linked_count,
            )
        )
    else:
        rows.append(
            CoverageRow(
                category="Consensus Data",
                status="Unavailable",
                status_code="unavailable",
                details="No consensus snapshots or revisions on record.",
            )
        )

    filings = snapshot.news_filings
    filing_count = len(filings) if not filings.empty else 0
    if filing_count:
        linked_count = _linked_row_count(
            filings,
            ("related_entity_ids", "related_listing_ids", "related_basket_ids"),
        )
        status_code = "available" if linked_count else "partial"
        rows.append(
            CoverageRow(
                category="News & Filings",
                status="Available" if linked_count else "Linkage unavailable",
                status_code=status_code,
                details=(
                    f"{filing_count} news/filing item{'s' if filing_count != 1 else ''} found; "
                    f"{linked_count} carry entity, listing, or basket relations. "
                    "Evidence without a relation is not assigned to a company."
                ),
                record_count=filing_count,
                linked_count=linked_count,
            )
        )
    else:
        rows.append(
            CoverageRow(
                category="News & Filings",
                status="Unavailable",
                status_code="unavailable",
                details="No news or filing records available in the current snapshot.",
            )
        )

    event_count = len(snapshot.events) if not snapshot.events.empty else 0
    macro_count = (
        len(snapshot.macro_observations)
        if not snapshot.macro_observations.empty
        else 0
    )
    evidence_count = event_count + macro_count
    if evidence_count:
        linked_events = _linked_event_count(snapshot)
        rows.append(
            CoverageRow(
                category="Alternative Evidence / Events",
                status="Available",
                status_code="available",
                details=(
                    f"{event_count} event record{'s' if event_count != 1 else ''} and "
                    f"{macro_count} macro observation{'s' if macro_count != 1 else ''} present; "
                    f"event link registry covers {linked_events} event record{'s' if linked_events != 1 else ''}. "
                    "This is evidence coverage, not a trading signal."
                ),
                record_count=evidence_count,
                linked_count=linked_events,
            )
        )
    else:
        rows.append(
            CoverageRow(
                category="Alternative Evidence / Events",
                status="Unavailable",
                status_code="unavailable",
                details="No evidence or event records on record.",
            )
        )

    return DataCoverageSummary(rows=tuple(rows))


__all__ = [
    "CoverageRow",
    "CoverageStatusCode",
    "DataCoverageSummary",
    "build_data_coverage_summary",
]
