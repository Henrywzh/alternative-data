"""Data coverage state semantics and Stage 1 matrix for Control Tower.

Coverage is derived deterministically from the artifact bundle only:
artifact presence, row count, linkage, freshness/source-health and entity
applicability. The app never queries a provider at render time, and an
unconnected or failed provider is never converted into successful coverage.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal, Mapping

import pandas as pd

from .models import ControlTowerSnapshot

CoverageStatusCode = Literal[
    "available",
    "partial",
    "stale",
    "not_applicable",
    "no_records",
    "unavailable",
]

COVERAGE_STATUS_ORDER: tuple[CoverageStatusCode, ...] = (
    "available",
    "partial",
    "stale",
    "no_records",
    "not_applicable",
    "unavailable",
)

COVERAGE_STATUS_LABELS: Mapping[CoverageStatusCode, str] = {
    "available": "Available",
    "partial": "Partial",
    "stale": "Stale",
    "not_applicable": "Not applicable",
    "no_records": "No records",
    "unavailable": "Unavailable",
}

COVERAGE_STATUS_DESCRIPTIONS: Mapping[CoverageStatusCode, str] = {
    "available": "Valid rows passed schema, identity and freshness checks.",
    "partial": "The source covers only some listings, periods or geographies.",
    "stale": "Rows exist but are outside the source-specific freshness window.",
    "not_applicable": "The data concept does not apply to this entity.",
    "no_records": "The source was queried successfully but returned no matching rows.",
    "unavailable": "The artifact or provider is not connected, or the request failed.",
}

STAGE1_BASKET_ID = "RESEARCH_STAGE_1_CHINA_INTERNET"

COVERAGE_CATEGORIES: tuple[str, ...] = (
    "price_quotes",
    "consensus",
    "earnings_actuals",
    "filings_news",
    "events",
)

COVERAGE_CATEGORY_LABELS: Mapping[str, str] = {
    "price_quotes": "Price / market quotes",
    "consensus": "Analyst consensus",
    "earnings_actuals": "Earnings actuals",
    "filings_news": "Official filings & news",
    "events": "Events / evidence",
}

# Categories that do not apply to private entities: a private company has no
# public-market quote, analyst consensus or public earnings-actuals concept.
_PRIVATE_NOT_APPLICABLE_CATEGORIES = frozenset(
    {"price_quotes", "consensus", "earnings_actuals"}
)

_CATEGORY_SOURCE_KINDS: Mapping[str, frozenset[str]] = {
    "price_quotes": frozenset({"market"}),
    "consensus": frozenset({"consensus"}),
    "filings_news": frozenset({"filing", "news"}),
    "events": frozenset({"events", "registry"}),
    "macro": frozenset({"macro"}),
}

_CATEGORY_SOURCE_IDS: Mapping[str, frozenset[str]] = {
    "price_quotes": frozenset({"quote_snapshots"}),
    "consensus": frozenset(
        {"consensus_export", "consensus_snapshots", "consensus_revisions"}
    ),
    "filings_news": frozenset(
        {"filings_sec_edgar", "news_official_ai_rss"}
    ),
    "events": frozenset(
        {
            "events:events",
            "events:event_links",
            "events:event_watch_questions",
            "registry:entities",
            "registry:listings",
        }
    ),
    "macro": frozenset(
        {
            "fred_observations",
            "fred_series_meta",
            "ecb_fx_rates",
            "ofr_mnemonics",
            "ofr_timeseries",
            "tw_monthly_revenue",
        }
    ),
}

# Fallback freshness windows used when the source-health row does not supply
# a cadence or stale_after_days value. Mirrors the source-health cadence map.
_CATEGORY_DEFAULT_STALE_DAYS: Mapping[str, int | None] = {
    "price_quotes": 3,
    "consensus": 14,
    "filings_news": 14,
    "events": None,
    "earnings_actuals": None,
    "macro": 45,
}

_QUOTE_TS_COLUMNS = ("quote_timestamp", "retrieved_at_utc")
_CONSENSUS_TS_COLUMNS = ("provider_asof", "snapshot_at", "retrieved_at_utc")
_FILINGS_TS_COLUMNS = ("published_at", "first_observed_at")
_MACRO_TS_COLUMNS = ("release_at", "source_published_at", "retrieved_at_utc")

# Source-health display states that mean the provider is effectively absent:
# failure, entitlement, schema or integrity issues are never "no records".
_UNAVAILABLE_SOURCE_STATES = frozenset(
    {
        "unavailable",
        "failed",
        "error",
        "schema_error",
        "degraded",
        "entitlement_error",
        "review_required",
        "conflicted",
    }
)
_CONNECTED_SOURCE_STATES = frozenset(
    {
        "healthy",
        "unclassified",
        "clock_skew",
        "stale",
        "no_records",
        "not_applicable",
    }
)


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


@dataclass(frozen=True, slots=True)
class CoverageCell:
    """One entity-by-category coverage state with human-readable detail."""

    category: str
    status_code: CoverageStatusCode
    details: str
    record_count: int = 0


@dataclass(frozen=True, slots=True)
class Stage1ListingCoverage:
    """Quote-coverage state for one active registry listing."""

    listing_id: str
    entity_id: str
    canonical_ticker: str
    status_code: CoverageStatusCode
    details: str


@dataclass(frozen=True, slots=True)
class Stage1EntityCoverage:
    """Coverage cells for one Stage 1 entity across the fixed categories."""

    entity_id: str
    display_name: str
    entity_type: str
    listing_count: int
    listing_ids: tuple[str, ...]
    cells: tuple[CoverageCell, ...]


@dataclass(frozen=True, slots=True)
class Stage1CoverageMatrix:
    """Honest per-entity/per-listing coverage for the Stage 1 universe.

    A private entity (ByteDance) is represented as an entity row without a
    fabricated listing; the active-listing rows come from the registry only.
    """

    categories: tuple[str, ...]
    entity_rows: tuple[Stage1EntityCoverage, ...]
    listing_rows: tuple[Stage1ListingCoverage, ...]
    global_macro: CoverageCell
    now_utc: pd.Timestamp

    def entity_cell(self, entity_id: str, category: str) -> CoverageCell:
        if category not in self.categories:
            raise ValueError(f"unknown coverage category: {category!r}")
        for row in self.entity_rows:
            if row.entity_id == entity_id:
                return row.cells[self.categories.index(category)]
        raise KeyError(f"entity not in Stage 1 matrix: {entity_id!r}")

    def status_of(self, entity_id: str, category: str) -> CoverageStatusCode:
        return self.entity_cell(entity_id, category).status_code


def _text(value: object) -> str:
    if value is None or value is pd.NA or value is pd.NaT:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _coerce_int(value: object) -> int | None:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_utc_timestamp(value: object) -> pd.Timestamp | None:
    """Parse a timezone-aware timestamp; naive/missing values return None."""

    if value is None or value is pd.NaT:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed) or parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.tz_convert("UTC")


def _newest_timestamp(rows: pd.DataFrame, columns: tuple[str, ...]) -> pd.Timestamp | None:
    newest: pd.Timestamp | None = None
    for column in columns:
        if column not in rows.columns:
            continue
        for value in rows[column]:
            parsed = _as_utc_timestamp(value)
            if parsed is not None and (newest is None or parsed > newest):
                newest = parsed
    return newest


def _is_stale(
    newest: pd.Timestamp | None,
    threshold_days: int | None,
    now_utc: pd.Timestamp,
) -> bool:
    if newest is None or threshold_days is None:
        return False
    reference = _as_utc_timestamp(now_utc)
    if reference is None:
        return False
    return (reference - newest).total_seconds() > threshold_days * 86400.0


def _resolve_threshold(
    thresholds: Mapping[str, int | None],
    source_ids: tuple[str, ...],
    default: int | None,
) -> int | None:
    """First non-null stale threshold for the governing sources, else default."""

    for source_id in source_ids:
        value = thresholds.get(source_id)
        if value is not None:
            return value
    return default


def _source_health_states(
    snapshot: ControlTowerSnapshot,
) -> tuple[dict[str, str], dict[str, int | None]]:
    """Classify source-health rows into display states and stale thresholds.

    The classification lives in the source-health page module; it is imported
    lazily so coverage stays importable without the page package.
    """

    from .pages.source_health import classify_source_health

    classified = classify_source_health(
        snapshot.source_health, now_utc=snapshot.now_utc
    )
    states: dict[str, str] = {}
    thresholds: dict[str, int | None] = {}
    if classified.empty:
        return states, thresholds
    for _, row in classified.iterrows():
        source_id = _text(row.get("source_id"))
        if not source_id:
            continue
        states[source_id] = _text(row.get("display_status")).lower()
        thresholds[source_id] = _coerce_int(row.get("stale_after_days"))
    return states, thresholds


def _matches_category_source(
    source_id: str,
    source_kind: str,
    category: str,
) -> bool:
    """Match a source-health row to a coverage category.

    Matches canonical ids, repository synthetic ids ("artifact:<stem>") and
    prefixed provider ids such as "provider:yfinance", plus source kinds.
    """

    canonical = _CATEGORY_SOURCE_IDS.get(category, frozenset())
    for candidate in canonical:
        if source_id == candidate or source_id == f"artifact:{candidate}":
            return True
        if source_id.startswith(f"{candidate}:") or source_id.startswith(
            f"provider:{candidate}:"
        ):
            return True
    return source_kind in _CATEGORY_SOURCE_KINDS.get(category, frozenset())


def _category_source_status(
    states: Mapping[str, str],
    kinds: Mapping[str, str],
    category: str,
) -> str | None:
    """Aggregate governing source states for one category.

    Any failing/entitlement state wins (provider failure is preserved and is
    never converted into "no records"); otherwise a connected source with no
    rows yields no_records; a healthy source yields healthy.
    """

    matched = [
        state
        for source_id, state in states.items()
        if _matches_category_source(
            source_id, kinds.get(source_id, ""), category
        )
    ]
    if not matched:
        return None
    if any(state in _UNAVAILABLE_SOURCE_STATES for state in matched):
        return "unavailable"
    if any(state == "no_records" for state in matched):
        return "no_records"
    if any(state in _CONNECTED_SOURCE_STATES for state in matched):
        return "healthy"
    return None


def _active_listing_map(
    snapshot: ControlTowerSnapshot,
) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    """Return (entity_id -> active listing ids, listing_id -> entity_id)."""

    listings = snapshot.listings
    by_entity: dict[str, list[str]] = {}
    owner: dict[str, str] = {}
    if listings.empty:
        return {key: tuple() for key in by_entity}, owner
    for _, row in listings.iterrows():
        if _text(row.get("listing_status")).lower() != "active":
            continue
        listing_id = _text(row.get("listing_id"))
        entity_id = _text(row.get("entity_id"))
        if not listing_id or not entity_id:
            continue
        by_entity.setdefault(entity_id, []).append(listing_id)
        owner[listing_id] = entity_id
    return {key: tuple(sorted(value)) for key, value in by_entity.items()}, owner


def _stage1_entity_ids(snapshot: ControlTowerSnapshot) -> set[str]:
    """Stage 1 entities = active basket members, falling back to active entities."""

    memberships = snapshot.basket_memberships
    if not memberships.empty and {"entity_id", "basket_id"} <= set(
        memberships.columns
    ):
        stage1 = {
            _text(value)
            for value in memberships.loc[
                memberships["basket_id"].astype("string").eq(STAGE1_BASKET_ID),
                "entity_id",
            ]
            if _text(value)
        }
        if stage1:
            return stage1
    entities = snapshot.entities
    if entities.empty:
        return set()
    return {
        _text(row.get("entity_id"))
        for _, row in entities.iterrows()
        if _text(row.get("entity_id"))
        and _text(row.get("active_status")).lower() == "active"
    }


def _entity_rows(snapshot: ControlTowerSnapshot) -> tuple[dict[str, object], ...]:
    ids = _stage1_entity_ids(snapshot)
    rows = [
        row.to_dict()
        for _, row in snapshot.entities.iterrows()
        if _text(row.get("entity_id")) in ids
    ]
    return tuple(rows)


def _quote_rows_for_listing(
    snapshot: ControlTowerSnapshot,
    listing_id: str,
) -> pd.DataFrame:
    quotes = snapshot.quote_snapshots
    if quotes.empty or "listing_id" not in quotes.columns:
        return quotes.iloc[0:0]
    return quotes.loc[
        quotes["listing_id"].astype("string").eq(listing_id)
    ].copy()


def _quote_rows_for_entity(
    snapshot: ControlTowerSnapshot,
    listing_ids: tuple[str, ...],
) -> pd.DataFrame:
    quotes = snapshot.quote_snapshots
    if quotes.empty or "listing_id" not in quotes.columns:
        return quotes.iloc[0:0]
    return quotes.loc[
        quotes["listing_id"].astype("string").isin(listing_ids)
    ].copy()


def _consensus_rows_for_entity(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
    listing_ids: tuple[str, ...],
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for name in ("consensus_snapshots", "consensus_revisions"):
        frame = getattr(snapshot, name)
        if frame.empty:
            continue
        if "entity_id" in frame.columns:
            by_entity = frame["entity_id"].astype("string").eq(entity_id)
            if "listing_id" in frame.columns:
                by_listing = frame["listing_id"].astype("string").isin(listing_ids)
                parts.append(frame.loc[by_entity | by_listing])
            else:
                parts.append(frame.loc[by_entity])
    if not parts:
        return snapshot.consensus_snapshots.iloc[0:0]
    return pd.concat(parts, ignore_index=True).drop_duplicates()


def _filings_rows_for_entity(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
    listing_ids: tuple[str, ...],
) -> pd.DataFrame:
    filings = snapshot.news_filings
    if filings.empty:
        return filings.iloc[0:0]
    matched: list[bool] = []
    for _, row in filings.iterrows():
        related_entities = _relation_values(row.get("related_entity_ids"))
        related_listings = _relation_values(row.get("related_listing_ids"))
        matched.append(
            entity_id in related_entities
            or bool(set(related_listings) & set(listing_ids))
        )
    return filings.loc[matched].copy()


def _event_rows_for_entity(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
) -> pd.DataFrame:
    events = snapshot.events
    if events.empty:
        return events.iloc[0:0]
    matched = [
        entity_id in _relation_values(row.get("related_entity_ids"))
        for _, row in events.iterrows()
    ]
    return events.loc[matched].copy()


def _covered_listing_count(
    rows: pd.DataFrame,
    listing_ids: tuple[str, ...],
    column: str = "listing_id",
) -> int:
    if rows.empty or column not in rows.columns:
        return 0
    return len(
        set(rows[column].astype("string")) & set(listing_ids)
    )


def _missing_geographies(snapshot: ControlTowerSnapshot, category: str) -> bool:
    """True when a governing source records uncovered geographies."""

    health = snapshot.source_health
    if health.empty or "missing_geographies" not in health.columns:
        return False
    kinds = {
        _text(row.get("source_id")): _text(row.get("source_kind"))
        for _, row in health.iterrows()
    }
    for _, row in health.iterrows():
        source_id = _text(row.get("source_id"))
        if not _matches_category_source(
            source_id, kinds.get(source_id, ""), category
        ):
            continue
        if _text(row.get("missing_geographies")):
            return True
    return False


def _listing_cell(
    snapshot: ControlTowerSnapshot,
    listing_id: str,
    entity_id: str,
    canonical_ticker: str,
    *,
    source_state: str | None,
    threshold_days: int | None,
    now_utc: pd.Timestamp,
) -> Stage1ListingCoverage:
    rows = _quote_rows_for_listing(snapshot, listing_id)
    if not rows.empty:
        newest = _newest_timestamp(rows, _QUOTE_TS_COLUMNS)
        if _is_stale(newest, threshold_days, now_utc):
            status: CoverageStatusCode = "stale"
            details = (
                f"Quote rows exist but the newest observation "
                f"({newest.strftime('%d %b %Y %H:%M UTC') if newest is not None else 'unknown'}) "
                f"is outside the freshness window."
            )
        else:
            status = "available"
            details = f"{len(rows)} quote snapshot(s) present for this listing."
    elif source_state in {"no_records", "healthy"}:
        status = "no_records"
        details = "No quote rows for this listing; the source health record reports a successful run."
    elif source_state == "unavailable":
        status = "unavailable"
        details = "No quote rows for this listing; the quote source is disconnected or failed."
    else:
        status = "unavailable"
        details = "No quote rows for this listing and no connected quote source on record."
    return Stage1ListingCoverage(
        listing_id=listing_id,
        entity_id=entity_id,
        canonical_ticker=canonical_ticker,
        status_code=status,
        details=details,
    )


def _price_quotes_cell(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
    listing_ids: tuple[str, ...],
    *,
    entity_type: str,
    source_state: str | None,
    threshold_days: int | None,
    now_utc: pd.Timestamp,
) -> CoverageCell:
    if entity_type == "private":
        return CoverageCell(
            "price_quotes",
            "not_applicable",
            "Private entity; public-market quotes do not apply.",
        )
    if not listing_ids:
        return CoverageCell(
            "price_quotes",
            "not_applicable",
            "Entity has no active listing; the quote concept does not apply.",
        )
    rows = _quote_rows_for_entity(snapshot, listing_ids)
    if not rows.empty:
        newest = _newest_timestamp(rows, _QUOTE_TS_COLUMNS)
        if _is_stale(newest, threshold_days, now_utc):
            return CoverageCell(
                "price_quotes",
                "stale",
                f"Quote rows exist but the newest observation is outside the "
                f"{threshold_days}-day freshness window.",
                record_count=len(rows),
            )
        covered = _covered_listing_count(rows, listing_ids)
        if covered < len(listing_ids):
            return CoverageCell(
                "price_quotes",
                "partial",
                f"Quotes cover {covered} of {len(listing_ids)} active listings.",
                record_count=len(rows),
            )
        return CoverageCell(
            "price_quotes",
            "available",
            f"{len(rows)} quote snapshot(s) present for all {len(listing_ids)} "
            f"active listing(s); rows carry listing identifiers.",
            record_count=len(rows),
        )
    if source_state in {"no_records", "healthy"}:
        return CoverageCell(
            "price_quotes",
            "no_records",
            "No quote rows for this entity; the source health record reports a successful run.",
        )
    return CoverageCell(
        "price_quotes",
        "unavailable",
        "No quote rows for this entity; the quote source is disconnected, "
        "failed or not configured.",
    )


def _consensus_cell(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
    listing_ids: tuple[str, ...],
    *,
    entity_type: str,
    source_state: str | None,
    threshold_days: int | None,
    now_utc: pd.Timestamp,
) -> CoverageCell:
    if entity_type == "private":
        return CoverageCell(
            "consensus",
            "not_applicable",
            "Private entity; analyst consensus does not apply without public disclosures.",
        )
    rows = _consensus_rows_for_entity(snapshot, entity_id, listing_ids)
    if not rows.empty:
        newest = _newest_timestamp(rows, _CONSENSUS_TS_COLUMNS)
        if _is_stale(newest, threshold_days, now_utc):
            return CoverageCell(
                "consensus",
                "stale",
                f"Consensus rows exist but the newest observation is outside the "
                f"{threshold_days}-day freshness window.",
                record_count=len(rows),
            )
        covered = _covered_listing_count(rows, listing_ids)
        if listing_ids and covered < len(listing_ids):
            return CoverageCell(
                "consensus",
                "partial",
                f"Consensus rows cover {covered} of {len(listing_ids)} active listings.",
                record_count=len(rows),
            )
        return CoverageCell(
            "consensus",
            "available",
            f"{len(rows)} consensus snapshot/revision row(s) linked to this entity.",
            record_count=len(rows),
        )
    if source_state in {"no_records", "healthy"}:
        return CoverageCell(
            "consensus",
            "no_records",
            "No consensus rows for this entity; the source health record reports a successful run.",
        )
    return CoverageCell(
        "consensus",
        "unavailable",
        "No consensus rows for this entity; the consensus source is "
        "disconnected, entitlement-unverified or failed.",
    )


def _earnings_actuals_cell(entity_type: str) -> CoverageCell:
    if entity_type == "private":
        return CoverageCell(
            "earnings_actuals",
            "not_applicable",
            "Private entity; no public earnings-actuals concept.",
        )
    return CoverageCell(
        "earnings_actuals",
        "unavailable",
        "No earnings-actuals artifact is part of the V1 data contract.",
    )


def _filings_news_cell(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
    listing_ids: tuple[str, ...],
    *,
    entity_type: str,
    source_state: str | None,
    threshold_days: int | None,
    now_utc: pd.Timestamp,
) -> CoverageCell:
    rows = _filings_rows_for_entity(snapshot, entity_id, listing_ids)
    if not rows.empty:
        newest = _newest_timestamp(rows, _FILINGS_TS_COLUMNS)
        if _is_stale(newest, threshold_days, now_utc):
            return CoverageCell(
                "filings_news",
                "stale",
                f"Filing/news rows exist but the newest item is outside the "
                f"{threshold_days}-day freshness window.",
                record_count=len(rows),
            )
        if _missing_geographies(snapshot, "filings_news"):
            return CoverageCell(
                "filings_news",
                "partial",
                f"{len(rows)} filing/news item(s) linked to this entity; the "
                f"governing source records uncovered geographies.",
                record_count=len(rows),
            )
        return CoverageCell(
            "filings_news",
            "available",
            f"{len(rows)} filing/news item(s) linked to this entity.",
            record_count=len(rows),
        )
    if source_state in {"no_records", "healthy"}:
        return CoverageCell(
            "filings_news",
            "no_records",
            "No filing/news rows for this entity; the source health record reports a successful run.",
        )
    return CoverageCell(
        "filings_news",
        "unavailable",
        "No filing/news rows for this entity; the filings/news source is "
        "disconnected, failed or not configured.",
    )


def _events_cell(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
) -> CoverageCell:
    rows = _event_rows_for_entity(snapshot, entity_id)
    if not rows.empty:
        return CoverageCell(
            "events",
            "available",
            f"{len(rows)} event record(s) linked to this entity in the local registry.",
            record_count=len(rows),
        )
    return CoverageCell(
        "events",
        "no_records",
        "No event records linked to this entity; the local registry was read successfully.",
    )


def _macro_cell(
    snapshot: ControlTowerSnapshot,
    *,
    source_state: str | None,
    threshold_days: int | None,
    now_utc: pd.Timestamp,
) -> CoverageCell:
    rows = snapshot.macro_observations
    count = len(rows) if not rows.empty else 0
    if count:
        newest = _newest_timestamp(rows, _MACRO_TS_COLUMNS)
        if _is_stale(newest, threshold_days, now_utc):
            return CoverageCell(
                "macro",
                "stale",
                f"{count} macro observation(s) on record but the newest release "
                f"is outside the {threshold_days}-day freshness window.",
                record_count=count,
            )
        return CoverageCell(
            "macro",
            "available",
            f"{count} macro observation(s) on record; governing provider "
            f"{'state' if source_state == 'unavailable' else 'connectivity'} "
            f"is shown in Source Health.",
            record_count=count,
        )
    if source_state in {"no_records", "healthy"}:
        return CoverageCell(
            "macro",
            "no_records",
            "No macro observations on record; the source health record reports a successful run.",
        )
    return CoverageCell(
        "macro",
        "unavailable",
        "No macro observations on record; no macro source is connected or configured.",
    )


def build_stage1_coverage_matrix(
    snapshot: ControlTowerSnapshot,
) -> Stage1CoverageMatrix:
    """Derive the honest Stage 1 coverage matrix from the artifact bundle.

    Deterministic per bundle: statuses come only from artifact presence, row
    counts, linkage, source-health/freshness and entity applicability.
    """

    now_utc = snapshot.now_utc
    states, thresholds = _source_health_states(snapshot)
    kinds = {
        _text(row.get("source_id")): _text(row.get("source_kind"))
        for _, row in snapshot.source_health.iterrows()
        if _text(row.get("source_id"))
    }
    listing_by_entity, listing_owner = _active_listing_map(snapshot)

    entity_rows: list[Stage1EntityCoverage] = []
    for raw in _entity_rows(snapshot):
        entity_id = _text(raw.get("entity_id"))
        if not entity_id:
            continue
        entity_type = _text(raw.get("entity_type")).lower() or "public"
        listing_ids = listing_by_entity.get(entity_id, ())
        source_state = {
            category: _category_source_status(states, kinds, category)
            for category in COVERAGE_CATEGORIES
        }
        quote_threshold = _resolve_threshold(
            thresholds,
            ("quote_snapshots",),
            _CATEGORY_DEFAULT_STALE_DAYS["price_quotes"],
        )
        consensus_threshold = _resolve_threshold(
            thresholds,
            ("consensus_export",),
            _CATEGORY_DEFAULT_STALE_DAYS["consensus"],
        )
        filings_threshold = _resolve_threshold(
            thresholds,
            ("filings_sec_edgar", "news_official_ai_rss"),
            _CATEGORY_DEFAULT_STALE_DAYS["filings_news"],
        )
        cells: list[CoverageCell] = [
            _price_quotes_cell(
                snapshot,
                entity_id,
                listing_ids,
                entity_type=entity_type,
                source_state=source_state["price_quotes"],
                threshold_days=quote_threshold,
                now_utc=now_utc,
            ),
            _consensus_cell(
                snapshot,
                entity_id,
                listing_ids,
                entity_type=entity_type,
                source_state=source_state["consensus"],
                threshold_days=consensus_threshold,
                now_utc=now_utc,
            ),
            _earnings_actuals_cell(entity_type),
            _filings_news_cell(
                snapshot,
                entity_id,
                listing_ids,
                entity_type=entity_type,
                source_state=source_state["filings_news"],
                threshold_days=filings_threshold,
                now_utc=now_utc,
            ),
            _events_cell(snapshot, entity_id),
        ]
        entity_rows.append(
            Stage1EntityCoverage(
                entity_id=entity_id,
                display_name=_text(raw.get("display_name")) or entity_id,
                entity_type=entity_type,
                listing_count=len(listing_ids),
                listing_ids=listing_ids,
                cells=tuple(cells),
            )
        )

    quote_source_state = _category_source_status(states, kinds, "price_quotes")
    quote_threshold = _resolve_threshold(
        thresholds,
        ("quote_snapshots",),
        _CATEGORY_DEFAULT_STALE_DAYS["price_quotes"],
    )
    listing_rows: list[Stage1ListingCoverage] = []
    if not snapshot.listings.empty:
        for _, row in snapshot.listings.iterrows():
            listing_id = _text(row.get("listing_id"))
            if not listing_id or _text(row.get("listing_status")).lower() != "active":
                continue
            listing_rows.append(
                _listing_cell(
                    snapshot,
                    listing_id,
                    _text(row.get("entity_id")),
                    _text(row.get("canonical_ticker")) or listing_id,
                    source_state=quote_source_state,
                    threshold_days=quote_threshold,
                    now_utc=now_utc,
                )
            )

    macro_source_state = _category_source_status(states, kinds, "macro")
    macro_cell = _macro_cell(
        snapshot,
        source_state=macro_source_state,
        threshold_days=_resolve_threshold(
            thresholds,
            ("fred_observations", "ecb_fx_rates"),
            _CATEGORY_DEFAULT_STALE_DAYS["macro"],
        ),
        now_utc=now_utc,
    )

    return Stage1CoverageMatrix(
        categories=COVERAGE_CATEGORIES,
        entity_rows=tuple(entity_rows),
        listing_rows=tuple(listing_rows),
        global_macro=macro_cell,
        now_utc=now_utc,
    )


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


def _registry_id_sets(
    snapshot: ControlTowerSnapshot,
) -> tuple[set[str], set[str], set[str]]:
    """Known entity/listing/basket identifiers for identity/linkage QA."""

    def ids(frame: pd.DataFrame, column: str) -> set[str]:
        if frame is None or frame.empty or column not in frame.columns:
            return set()
        return {
            _text(value)
            for value in frame[column].dropna()
            if _text(value)
        }

    return (
        ids(snapshot.entities, "entity_id"),
        ids(snapshot.listings, "listing_id"),
        ids(snapshot.baskets, "basket_id"),
    )


def _linked_row_count(
    snapshot: ControlTowerSnapshot,
    frame: pd.DataFrame,
    columns: tuple[str, ...],
) -> int:
    """Count rows whose relation identifiers resolve in the registry.

    A non-empty relation cell is not enough: the identifier must resolve to a
    known entity, listing or basket, otherwise the row is unlinked evidence.
    """

    if frame.empty:
        return 0
    entity_ids, listing_ids, basket_ids = _registry_id_sets(snapshot)
    return sum(
        any(
            set(_relation_values(row.get(column))) & entity_ids
            for column in columns
            if column.endswith("entity_ids") or column == "entity_id"
        )
        or any(
            set(_relation_values(row.get(column))) & listing_ids
            for column in columns
            if column.endswith("listing_ids") or column == "listing_id"
        )
        or any(
            set(_relation_values(row.get(column))) & basket_ids
            for column in columns
            if column.endswith("basket_ids") or column == "basket_id"
        )
        or any(
            set(_relation_values(row.get(column)))
            & (entity_ids | listing_ids | basket_ids)
            for column in columns
            if not (
                column.endswith(("entity_ids", "listing_ids", "basket_ids"))
                or column in {"entity_id", "listing_id", "basket_id"}
            )
        )
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
    not a data-quality or investment-signal score. Statuses follow the six
    state vocabulary; a healthy source with zero rows is "no records", while a
    disconnected or failed source stays "unavailable".
    """

    states, thresholds = _source_health_states(snapshot)
    kinds = {
        _text(row.get("source_id")): _text(row.get("source_kind"))
        for _, row in snapshot.source_health.iterrows()
        if _text(row.get("source_id"))
    }
    quote_source_state = _category_source_status(states, kinds, "price_quotes")
    consensus_source_state = _category_source_status(states, kinds, "consensus")
    filings_source_state = _category_source_status(states, kinds, "filings_news")

    quote_snapshots = snapshot.quote_snapshots
    quote_count = len(quote_snapshots) if not quote_snapshots.empty else 0
    if quote_count:
        linked_quotes = _linked_row_count(
            snapshot, quote_snapshots, ("listing_id",)
        )
        newest = _newest_timestamp(
            quote_snapshots, _QUOTE_TS_COLUMNS
        )
        quote_threshold = _resolve_threshold(
            thresholds,
            ("quote_snapshots",),
            _CATEGORY_DEFAULT_STALE_DAYS["price_quotes"],
        )
        if _is_stale(newest, quote_threshold, snapshot.now_utc):
            quote_status: CoverageStatusCode = "stale"
            quote_status_text = "Stale"
            quote_details = (
                f"{quote_count} latest quote snapshot{'s' if quote_count != 1 else ''} "
                f"present but outside the {quote_threshold}-day freshness window."
            )
        else:
            quote_status = "available" if linked_quotes == quote_count else "partial"
            quote_status_text = (
                "Available" if quote_status == "available" else "Partial linkage"
            )
            quote_details = (
                f"{quote_count} latest quote snapshot{'s' if quote_count != 1 else ''} present; "
                f"{linked_quotes} carry listing identifiers that resolve in the registry. "
                "Intraday bars are not yet in the V1 mart."
            )
        rows: list[CoverageRow] = [
            CoverageRow(
                category="Price / Market Quotes",
                status=quote_status_text,
                status_code=quote_status,
                details=quote_details,
                record_count=quote_count,
                linked_count=linked_quotes,
            )
        ]
    elif quote_source_state in {"no_records", "healthy"}:
        rows = [
            CoverageRow(
                category="Price / Market Bars",
                status="No records",
                status_code="no_records",
                details=(
                    "The quote source health record reports a successful run "
                    "with no matching quote rows."
                ),
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
        linked_count = _linked_row_count(
            snapshot, snapshots, ("entity_id", "listing_id")
        )
        linked_count += _linked_row_count(
            snapshot, revisions, ("entity_id", "listing_id")
        )
        newest = _newest_timestamp(
            pd.concat(
                [snapshots, revisions], ignore_index=True
            )
            if not snapshots.empty and not revisions.empty
            else (snapshots if not snapshots.empty else revisions),
            _CONSENSUS_TS_COLUMNS,
        )
        consensus_threshold = _resolve_threshold(
            thresholds,
            ("consensus_export",),
            _CATEGORY_DEFAULT_STALE_DAYS["consensus"],
        )
        if _is_stale(newest, consensus_threshold, snapshot.now_utc):
            status_code: CoverageStatusCode = "stale"
            status_text = "Stale"
        else:
            status_code = (
                "available" if linked_count == consensus_count else "partial"
            )
            status_text = (
                "Available" if status_code == "available" else "Partial linkage"
            )
        details = (
            f"{snapshot_count} consensus snapshot{'s' if snapshot_count != 1 else ''} and "
            f"{revision_count} revision record{'s' if revision_count != 1 else ''} present; "
            f"{linked_count} of {consensus_count} rows carry entity/listing identifiers "
            "that resolve in the registry. "
            "Source quality and entitlement are not assessed here."
        )
        if status_code == "stale":
            details = (
                f"{snapshot_count} consensus snapshot{'s' if snapshot_count != 1 else ''} and "
                f"{revision_count} revision record{'s' if revision_count != 1 else ''} present "
                f"but outside the {consensus_threshold}-day freshness window; "
                f"{linked_count} of {consensus_count} rows carry entity/listing identifiers "
                "that resolve in the registry."
            )
        rows.append(
            CoverageRow(
                category="Consensus Data",
                status=status_text,
                status_code=status_code,
                details=details,
                record_count=consensus_count,
                linked_count=linked_count,
            )
        )
    elif consensus_source_state in {"no_records", "healthy"}:
        rows.append(
            CoverageRow(
                category="Consensus Data",
                status="No records",
                status_code="no_records",
                details=(
                    "The consensus source health record reports a successful "
                    "run with no matching snapshots or revisions."
                ),
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
            snapshot,
            filings,
            ("related_entity_ids", "related_listing_ids", "related_basket_ids"),
        )
        newest = _newest_timestamp(filings, _FILINGS_TS_COLUMNS)
        filings_threshold = _resolve_threshold(
            thresholds,
            ("filings_sec_edgar", "news_official_ai_rss"),
            _CATEGORY_DEFAULT_STALE_DAYS["filings_news"],
        )
        if _is_stale(newest, filings_threshold, snapshot.now_utc):
            status_code = "stale"
            status_text = "Stale"
        else:
            status_code = "available" if linked_count else "partial"
            status_text = (
                "Available" if linked_count else "Linkage unavailable"
            )
        if status_code == "stale":
            details = (
                f"{filing_count} news/filing item{'s' if filing_count != 1 else ''} found "
                f"but outside the {filings_threshold}-day freshness window; "
                f"{linked_count} carry entity, listing, or basket identifiers "
                "that resolve in the registry."
            )
        else:
            details = (
                f"{filing_count} news/filing item{'s' if filing_count != 1 else ''} found; "
                f"{linked_count} carry entity, listing, or basket identifiers "
                "that resolve in the registry. "
                "Evidence without a relation is not assigned to a company."
            )
        rows.append(
            CoverageRow(
                category="News & Filings",
                status=status_text,
                status_code=status_code,
                details=details,
                record_count=filing_count,
                linked_count=linked_count,
            )
        )
    elif filings_source_state in {"no_records", "healthy"}:
        rows.append(
            CoverageRow(
                category="News & Filings",
                status="No records",
                status_code="no_records",
                details=(
                    "The filings/news source health record reports a successful "
                    "run with no matching items."
                ),
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
    elif (
        _category_source_status(states, kinds, "events") is not None
        or _category_source_status(states, kinds, "macro") is not None
    ):
        rows.append(
            CoverageRow(
                category="Alternative Evidence / Events",
                status="No records",
                status_code="no_records",
                details=(
                    "The local event registry was read successfully but no "
                    "event or macro rows are on record for the current universe."
                ),
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
    "COVERAGE_CATEGORIES",
    "COVERAGE_CATEGORY_LABELS",
    "COVERAGE_STATUS_DESCRIPTIONS",
    "COVERAGE_STATUS_LABELS",
    "COVERAGE_STATUS_ORDER",
    "CoverageRow",
    "CoverageCell",
    "CoverageStatusCode",
    "DataCoverageSummary",
    "STAGE1_BASKET_ID",
    "Stage1CoverageMatrix",
    "Stage1EntityCoverage",
    "Stage1ListingCoverage",
    "build_data_coverage_summary",
    "build_stage1_coverage_matrix",
]
