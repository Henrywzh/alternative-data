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

_CATEGORY_SOURCE_KINDS: Mapping[str, frozenset[str]] = {
    "price_quotes": frozenset({"market", "quote", "market_data"}),
    "consensus": frozenset({"consensus", "consensus_provider"}),
    "earnings_actuals": frozenset({"earnings"}),
    "filings_news": frozenset(
        {"filing", "news", "official_document_metadata", "official_filing"}
    ),
    "events": frozenset({"events", "registry"}),
    "macro": frozenset({"macro"}),
}

_CATEGORY_SOURCE_IDS: Mapping[str, frozenset[str]] = {
    "price_quotes": frozenset({"quote_snapshots"}),
    "consensus": frozenset(
        {"consensus_export", "consensus_snapshots", "consensus_revisions"}
    ),
    "earnings_actuals": frozenset({"earnings_actuals"}),
    "filings_news": frozenset(
        {"filings_sec_edgar", "news_official_ai_rss", "official_filings"}
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

# Note: the source_state_v1 sidecar *files'* own load-state rows
# ("official_filings_state" / "earnings_actuals_state" -- collector
# execution metadata about reading the sidecar file, not an observation
# stream) are deliberately kept out of category matching, but not by an id
# list here. build.py gives that specific row a distinct source_kind
# ("official_filing_collector_state" / "earnings_collector_state", see
# OFFICIAL_FILINGS_STATE_SOURCE_KIND/EARNINGS_ACTUALS_STATE_SOURCE_KIND)
# that never appears in _CATEGORY_SOURCE_KINDS, so it naturally never
# matches any category through the kind-based fallback in
# _matches_category_source below -- no consumer-side id list to keep in
# sync as new sidecar-producing collectors are added. The real per-provider
# rows the builder unpacks out of the same sidecar file (e.g.
# "earnings:sec_companyfacts", "filings:hkexnews") keep their real kind
# ("earnings" / "official_filing") and continue to govern freshness/
# no-records as before.

_QUOTE_TS_COLUMNS = ("quote_timestamp",)
_CONSENSUS_TS_COLUMNS = (
    "provider_asof",
    "snapshot_at",
    "current_snapshot_at",
)
_FILINGS_TS_COLUMNS = ("published_at",)
_EARNINGS_ACTUALS_TS_COLUMNS = ("filing_at", "published_at")
_MACRO_TS_COLUMNS = ("release_at", "source_published_at")

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
_UNCERTAIN_SOURCE_STATES = frozenset(
    {"unclassified", "clock_skew"}
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


@dataclass(frozen=True, slots=True)
class _SourceState:
    source_id: str
    source_kind: str
    raw_status: str
    display_status: str
    stale_after_days: int | None
    row_count: int | None
    execution_completed: bool

    @property
    def label(self) -> str:
        return (
            self.source_id.replace("_", " ").replace(":", " · ")
            or "unknown source"
        )

    @property
    def state_label(self) -> str:
        state = self.raw_status
        if state in {"", "available", "success", "ok", "no_records"}:
            state = self.display_status
        state = state or "unclassified"
        return state.replace("_", " ")


@dataclass(frozen=True, slots=True)
class _CategorySources:
    category: str
    sources: tuple[_SourceState, ...]

    @property
    def adverse(self) -> tuple[_SourceState, ...]:
        return tuple(
            source
            for source in self.sources
            if source.display_status in _UNAVAILABLE_SOURCE_STATES
        )

    @property
    def uncertain(self) -> tuple[_SourceState, ...]:
        return tuple(
            source
            for source in self.sources
            if source.display_status in _UNCERTAIN_SOURCE_STATES
        )

    @property
    def no_records(self) -> tuple[_SourceState, ...]:
        return tuple(
            source
            for source in self.sources
            if source.display_status == "no_records"
        )

    @property
    def stale(self) -> tuple[_SourceState, ...]:
        return tuple(
            source
            for source in self.sources
            if source.display_status == "stale"
        )

    @property
    def incomplete_empty(self) -> tuple[_SourceState, ...]:
        return tuple(
            source
            for source in self.sources
            if source.row_count == 0
            and not source.execution_completed
            and source.display_status in {"healthy", "unclassified"}
        )

    def resolve(self, source_id: str) -> _SourceState | None:
        text = source_id.strip()
        if text:
            for source in self.sources:
                if source.source_id == text:
                    return source
                if source.source_id == f"provider:{text}":
                    return source
                if source.source_id.removeprefix("provider:") == text:
                    return source
            # Per-provider governing sources are namespaced ("filings:hkexnews",
            # "earnings:sec_companyfacts") and the producing collector
            # (official_filings.py / earnings_actuals.py) writes the identical
            # namespaced value onto the mart row's own source_id, so an exact
            # match (or the "provider:" handling above) is expected to
            # succeed. There is deliberately no namespace-suffix fallback
            # here: a bare provider id that reaches this point means the mart
            # row was produced by a pre-namespace-migration collector (or the
            # producer and its source_health record disagree), and that is
            # exactly the "cannot be matched to one governing source" case
            # the caller should surface as ``partial``, not something this
            # reader should guess at.
            return None
        populated = tuple(
            source
            for source in self.sources
            if source.row_count is not None and source.row_count > 0
        )
        if len(populated) == 1:
            return populated[0]
        if len(self.sources) == 1:
            return self.sources[0]
        return None


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


def _source_health_states(
    snapshot: ControlTowerSnapshot,
) -> tuple[_SourceState, ...]:
    """Return every classified source state without category aggregation."""

    from .pages.source_health import classify_source_health

    classified = classify_source_health(
        snapshot.source_health, now_utc=snapshot.now_utc
    )
    states: list[_SourceState] = []
    for _, row in classified.iterrows():
        source_id = _text(row.get("source_id"))
        if not source_id:
            continue
        states.append(
            _SourceState(
                source_id=source_id,
                source_kind=_text(row.get("source_kind")).lower(),
                raw_status=_text(row.get("status")).lower(),
                display_status=_text(row.get("display_status")).lower(),
                stale_after_days=_coerce_int(row.get("stale_after_days")),
                row_count=_coerce_int(row.get("row_count")),
                execution_completed=(
                    bool(row.get("query_attempted"))
                    and _text(row.get("execution_status")).lower() == "completed"
                    and _as_utc_timestamp(row.get("completed_at")) is not None
                    and _as_utc_timestamp(row.get("completed_at"))
                    <= snapshot.now_utc
                ),
            )
        )
    return tuple(states)


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


def _category_sources(
    states: tuple[_SourceState, ...],
    category: str,
) -> _CategorySources:
    return _CategorySources(
        category=category,
        sources=tuple(
            source
            for source in states
            if _matches_category_source(
                source.source_id,
                source.source_kind,
                category,
            )
        ),
    )


def _source_state_details(sources: tuple[_SourceState, ...]) -> str:
    return "; ".join(
        f"{source.label} is {source.state_label}"
        for source in sources
    )


def _empty_status(
    sources: _CategorySources,
) -> tuple[CoverageStatusCode, str]:
    """Coverage state when no matching artifact rows exist."""

    if not sources.sources:
        return (
            "unavailable",
            "No governing source-health records are available.",
        )
    if sources.adverse:
        return "unavailable", _source_state_details(sources.adverse)
    if sources.stale:
        return "stale", _source_state_details(sources.stale)
    # A ``not_applicable`` source has no opinion about this category -- it is
    # an explicit, hardcoded terminal state for a concept deliberately out of
    # scope (a private entity, an intentionally-unconfigured feed), never an
    # inferred default -- so it cannot satisfy *or* block "every source
    # agrees the data is genuinely absent". Requiring it to also report
    # available/no_records would conflate "does this source apply" with "did
    # this source's query complete", which would make ``no_records``
    # permanently unreachable for any category that has a not_applicable
    # placeholder at all, even when every source that actually applies
    # completed cleanly with nothing to report. This mirrors the existing
    # precedent of keeping ``not_applicable`` out of ``_UNAVAILABLE_SOURCE_STATES``
    # (see test_not_applicable_issuer_ir_source_no_longer_marks_category_adverse):
    # a source declining to have an opinion is not disagreement.
    applicable_sources = tuple(
        source
        for source in sources.sources
        if source.display_status != "not_applicable"
    )
    if applicable_sources and all(
        source.execution_completed
        and source.raw_status in {"available", "success", "ok", "no_records"}
        and source.display_status != "clock_skew"
        for source in applicable_sources
    ):
        return (
            "no_records",
            "All applicable governing sources record an explicitly "
            "completed execution with no matching rows"
            + (
                " (not_applicable sources excluded from this agreement: "
                + _source_state_details(
                    tuple(
                        source
                        for source in sources.sources
                        if source.display_status == "not_applicable"
                    )
                )
                + ")"
                if len(applicable_sources) != len(sources.sources)
                else "."
            ),
        )
    if sources.uncertain:
        return "partial", _source_state_details(sources.uncertain)
    if all(
        source.display_status == "not_applicable"
        for source in sources.sources
    ):
        return (
            "not_applicable",
            _source_state_details(sources.sources),
        )
    return (
        "partial",
        "No matching rows and source execution completion is not fully evidenced.",
    )


def _as_date(value: object) -> pd.Timestamp | None:
    if value is None or value is pd.NaT:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.tz_localize(None)
    return parsed.normalize()


def _active_at_snapshot(
    row: Mapping[str, object],
    snapshot: ControlTowerSnapshot,
) -> bool:
    """Half-open ``active_from <= as_of < active_to`` interval check."""

    as_of = snapshot.now_utc.tz_localize(None).normalize()
    active_from = _as_date(row.get("active_from"))
    active_to = _as_date(row.get("active_to"))
    return (
        (active_from is None or active_from <= as_of)
        and (active_to is None or as_of < active_to)
    )


def _active_entity_rows(
    snapshot: ControlTowerSnapshot,
) -> dict[str, dict[str, object]]:
    rows: dict[str, dict[str, object]] = {}
    for _, row in snapshot.entities.iterrows():
        payload = row.to_dict()
        entity_id = _text(payload.get("entity_id"))
        if (
            entity_id
            and _text(payload.get("active_status")).lower() == "active"
            and _active_at_snapshot(payload, snapshot)
        ):
            rows[entity_id] = payload
    return rows


def _stage1_entity_ids(snapshot: ControlTowerSnapshot) -> set[str]:
    """Active Stage 1 members at the snapshot reference time."""

    active_entities = _active_entity_rows(snapshot)
    memberships = snapshot.basket_memberships
    stage1_baskets = (
        snapshot.baskets.loc[
            snapshot.baskets["basket_id"]
            .astype("string")
            .eq(STAGE1_BASKET_ID)
        ]
        if not snapshot.baskets.empty
        and "basket_id" in snapshot.baskets.columns
        else snapshot.baskets.iloc[0:0]
    )
    if not stage1_baskets.empty:
        if not any(
            _active_at_snapshot(row.to_dict(), snapshot)
            for _, row in stage1_baskets.iterrows()
        ):
            return set()
        if memberships.empty or not {"entity_id", "basket_id"} <= set(
            memberships.columns
        ):
            return set()
        stage1_rows = memberships.loc[
            memberships["basket_id"].astype("string").eq(STAGE1_BASKET_ID)
        ]
        return {
            _text(row.get("entity_id"))
            for _, row in stage1_rows.iterrows()
            if _text(row.get("entity_id")) in active_entities
            and _active_at_snapshot(row.to_dict(), snapshot)
        }
    # Compatibility fallback for old focused bundles without the Stage 1
    # basket. A present-but-inactive basket never falls back to all entities.
    return set(active_entities)


def _active_listing_map(
    snapshot: ControlTowerSnapshot,
    stage1_entity_ids: set[str],
) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    """Return Stage 1 listing ownership at the snapshot reference time."""

    candidates: dict[str, set[str]] = {}
    for _, row in snapshot.listings.iterrows():
        payload = row.to_dict()
        if (
            _text(payload.get("listing_status")).lower() != "active"
            or not _active_at_snapshot(payload, snapshot)
        ):
            continue
        listing_id = _text(payload.get("listing_id"))
        entity_id = _text(payload.get("entity_id"))
        if not listing_id or entity_id not in stage1_entity_ids:
            continue
        candidates.setdefault(listing_id, set()).add(entity_id)

    # Duplicate owners are ambiguous and therefore excluded rather than
    # assigned arbitrarily.
    owner = {
        listing_id: next(iter(owners))
        for listing_id, owners in candidates.items()
        if len(owners) == 1
    }
    by_entity: dict[str, list[str]] = {}
    for listing_id, entity_id in owner.items():
        by_entity.setdefault(entity_id, []).append(listing_id)
    return (
        {
            entity_id: tuple(sorted(listing_ids))
            for entity_id, listing_ids in by_entity.items()
        },
        owner,
    )


def _entity_rows(snapshot: ControlTowerSnapshot) -> tuple[dict[str, object], ...]:
    stage1_ids = _stage1_entity_ids(snapshot)
    active_entities = _active_entity_rows(snapshot)
    return tuple(
        active_entities[entity_id]
        for entity_id in sorted(stage1_ids)
        if entity_id in active_entities
    )


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
    listing_owner: Mapping[str, str],
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for name in ("consensus_snapshots", "consensus_revisions"):
        frame = getattr(snapshot, name)
        if frame.empty:
            continue
        matched: list[bool] = []
        for _, row in frame.iterrows():
            row_entity = _text(row.get("entity_id"))
            row_listing = _text(row.get("listing_id"))
            if row_listing:
                owner = listing_owner.get(row_listing)
                matched.append(
                    owner == entity_id
                    and (not row_entity or row_entity == owner)
                )
            else:
                matched.append(row_entity == entity_id)
        parts.append(frame.loc[matched])
    if not parts:
        return snapshot.consensus_snapshots.iloc[0:0]
    return pd.concat(parts, ignore_index=True).drop_duplicates()


def _active_members_by_basket(
    snapshot: ControlTowerSnapshot,
    stage1_entity_ids: set[str],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for _, row in snapshot.basket_memberships.iterrows():
        payload = row.to_dict()
        entity_id = _text(payload.get("entity_id"))
        basket_id = _text(payload.get("basket_id"))
        if (
            entity_id in stage1_entity_ids
            and basket_id
            and _active_at_snapshot(payload, snapshot)
        ):
            result.setdefault(basket_id, set()).add(entity_id)
    return result


def _resolve_relation_entities(
    row: Mapping[str, object],
    *,
    stage1_entity_ids: set[str],
    listing_owner: Mapping[str, str],
    members_by_basket: Mapping[str, set[str]],
) -> set[str]:
    related = {
        entity_id
        for entity_id in _relation_values(row.get("related_entity_ids"))
        if entity_id in stage1_entity_ids
    }
    for listing_id in _relation_values(row.get("related_listing_ids")):
        owner = listing_owner.get(listing_id)
        if owner is not None:
            related.add(owner)
    for basket_id in _relation_values(row.get("related_basket_ids")):
        related.update(members_by_basket.get(basket_id, set()))
    return related


def _news_filing_rows_for_entity(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
    *,
    stage1_entity_ids: set[str],
    listing_owner: Mapping[str, str],
    members_by_basket: Mapping[str, set[str]],
) -> pd.DataFrame:
    filings = snapshot.news_filings
    if filings.empty:
        return filings.iloc[0:0]
    matched = [
        entity_id
        in _resolve_relation_entities(
            row,
            stage1_entity_ids=stage1_entity_ids,
            listing_owner=listing_owner,
            members_by_basket=members_by_basket,
        )
        for _, row in filings.iterrows()
    ]
    return filings.loc[matched].copy()


def _official_filing_rows_for_entity(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
    *,
    listing_owner: Mapping[str, str],
) -> pd.DataFrame:
    """Match official-filings rows via their direct entity_id/listing_id columns.

    Unlike news_filings, official_filings carries direct identity columns
    rather than relation lists, so this mirrors ``_consensus_rows_for_entity``
    rather than ``_resolve_relation_entities``.
    """

    filings = snapshot.official_filings
    if filings.empty:
        return filings.iloc[0:0]
    matched: list[bool] = []
    for _, row in filings.iterrows():
        row_entity = _text(row.get("entity_id"))
        row_listing = _text(row.get("listing_id"))
        if row_listing:
            owner = listing_owner.get(row_listing)
            matched.append(
                owner == entity_id
                and (not row_entity or row_entity == owner)
            )
        else:
            matched.append(row_entity == entity_id)
    return filings.loc[matched].copy()


def _filings_rows_for_entity(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
    *,
    stage1_entity_ids: set[str],
    listing_owner: Mapping[str, str],
    members_by_basket: Mapping[str, set[str]],
) -> pd.DataFrame:
    """Union of news_filings (relation-linked) and official_filings (direct)."""

    news_rows = _news_filing_rows_for_entity(
        snapshot,
        entity_id,
        stage1_entity_ids=stage1_entity_ids,
        listing_owner=listing_owner,
        members_by_basket=members_by_basket,
    )
    official_rows = _official_filing_rows_for_entity(
        snapshot,
        entity_id,
        listing_owner=listing_owner,
    )
    frames = [frame for frame in (news_rows, official_rows) if not frame.empty]
    if not frames:
        return snapshot.news_filings.iloc[0:0]
    if len(frames) == 1:
        return frames[0]
    return pd.concat(frames, ignore_index=True, sort=False)


def _earnings_actuals_rows_for_entity(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
    *,
    listing_owner: Mapping[str, str],
) -> pd.DataFrame:
    """Match earnings-actuals rows via their direct entity_id/listing_id columns."""

    actuals = snapshot.earnings_actuals
    if actuals.empty:
        return actuals.iloc[0:0]
    matched: list[bool] = []
    for _, row in actuals.iterrows():
        row_entity = _text(row.get("entity_id"))
        row_listing = _text(row.get("listing_id"))
        if row_listing:
            owner = listing_owner.get(row_listing)
            matched.append(
                owner == entity_id
                and (not row_entity or row_entity == owner)
            )
        else:
            matched.append(row_entity == entity_id)
    return actuals.loc[matched].copy()


def _event_relation_map(
    snapshot: ControlTowerSnapshot,
    *,
    stage1_entity_ids: set[str],
    listing_owner: Mapping[str, str],
    members_by_basket: Mapping[str, set[str]],
) -> dict[str, set[str]]:
    related: dict[str, set[str]] = {}
    registries_are_authoritative = (
        not snapshot.event_entity_links.empty
        or not snapshot.event_basket_links.empty
    )
    for _, row in snapshot.events.iterrows():
        event_id = _text(row.get("event_id"))
        if event_id:
            related[event_id] = (
                set()
                if registries_are_authoritative
                else _resolve_relation_entities(
                    row,
                    stage1_entity_ids=stage1_entity_ids,
                    listing_owner=listing_owner,
                    members_by_basket=members_by_basket,
                )
            )

    for frame in (
        snapshot.event_entity_links,
        snapshot.event_basket_links,
    ):
        for _, row in frame.iterrows():
            payload = row.to_dict()
            if not _active_at_snapshot(payload, snapshot):
                continue
            event_id = _text(payload.get("event_id"))
            target_type = _text(payload.get("target_type")).lower()
            target_id = _text(payload.get("target_id"))
            if not event_id or event_id not in related:
                continue
            if target_type == "entity" and target_id in stage1_entity_ids:
                related[event_id].add(target_id)
            elif target_type == "listing":
                owner = listing_owner.get(target_id)
                if owner is not None:
                    related[event_id].add(owner)
            elif target_type == "basket":
                related[event_id].update(
                    members_by_basket.get(target_id, set())
                )
    return related


def _event_rows_for_entity(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
    *,
    relation_map: Mapping[str, set[str]],
) -> pd.DataFrame:
    events = snapshot.events
    if events.empty:
        return events.iloc[0:0]
    matched = [
        entity_id in relation_map.get(_text(row.get("event_id")), set())
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


def _row_source_id(
    row: Mapping[str, object],
    columns: tuple[str, ...],
) -> str:
    for column in columns:
        value = _text(row.get(column))
        if value:
            return value
    return ""


def _row_source_timestamp(
    row: Mapping[str, object],
    columns: tuple[str, ...],
) -> pd.Timestamp | None:
    for column in columns:
        parsed = _as_utc_timestamp(row.get(column))
        if parsed is not None:
            return parsed
    return None


def _assess_time_sensitive_rows(
    rows: pd.DataFrame,
    *,
    sources: _CategorySources,
    timestamp_columns: tuple[str, ...],
    source_id_columns: tuple[str, ...],
    now_utc: pd.Timestamp,
) -> tuple[CoverageStatusCode, str]:
    """Apply source-state precedence and matched-source freshness SLA."""

    if sources.adverse:
        return (
            "partial",
            "Rows exist, but provider coverage is impaired: "
            + _source_state_details(sources.adverse),
        )
    if sources.uncertain:
        return (
            "partial",
            "Rows exist, but provider state is not classified: "
            + _source_state_details(sources.uncertain),
        )
    if sources.incomplete_empty:
        return (
            "partial",
            "Rows exist, but another source has zero rows without explicit "
            "execution-completion evidence: "
            + _source_state_details(sources.incomplete_empty),
        )
    if not sources.sources:
        return (
            "partial",
            "Rows exist, but no governing source-health/SLA record is available.",
        )
    if any(
        source.display_status == "not_applicable"
        for source in sources.sources
    ):
        conflicting = tuple(
            source
            for source in sources.sources
            if source.display_status == "not_applicable"
        )
        return (
            "partial",
            "Rows conflict with provider state: "
            + _source_state_details(conflicting),
        )

    stale_rows = 0
    for _, row in rows.iterrows():
        source_id = _row_source_id(row, source_id_columns)
        source = sources.resolve(source_id)
        if source is None:
            return (
                "partial",
                f"Row source {source_id or 'unavailable'} cannot be matched "
                "to one governing source-health record.",
            )
        if source.display_status == "no_records":
            return (
                "partial",
                "Rows conflict with a governing source that completed with "
                "no records: "
                + source.label,
            )
        if source.display_status == "not_applicable":
            return (
                "partial",
                "Rows conflict with a governing source marked not applicable: "
                + source.label,
            )
        timestamp = _row_source_timestamp(row, timestamp_columns)
        if timestamp is None:
            return (
                "partial",
                "At least one row lacks a valid source-native timestamp; "
                "retrieval time is not a freshness substitute.",
            )
        if timestamp > now_utc:
            return (
                "partial",
                f"{source.label} has a future source-native timestamp.",
            )
        if source.stale_after_days is None:
            return (
                "partial",
                f"{source.label} has no matched freshness SLA.",
            )
        if (
            source.display_status == "stale"
            or _is_stale(timestamp, source.stale_after_days, now_utc)
        ):
            stale_rows += 1

    if stale_rows == len(rows):
        return (
            "stale",
            "All matching rows are outside their matched source freshness SLA.",
        )
    if stale_rows:
        return (
            "partial",
            f"{stale_rows} of {len(rows)} matching rows are stale.",
        )
    if sources.stale:
        return (
            "partial",
            "Rows are fresh, but another governing source is stale: "
            + _source_state_details(sources.stale),
        )
    return "available", "Source state and source-native freshness checks passed."


def _listing_cell(
    snapshot: ControlTowerSnapshot,
    listing_id: str,
    entity_id: str,
    canonical_ticker: str,
    *,
    sources: _CategorySources,
    now_utc: pd.Timestamp,
) -> Stage1ListingCoverage:
    rows = _quote_rows_for_listing(snapshot, listing_id)
    if not rows.empty:
        status, source_detail = _assess_time_sensitive_rows(
            rows,
            sources=sources,
            timestamp_columns=_QUOTE_TS_COLUMNS,
            source_id_columns=("source_id",),
            now_utc=now_utc,
        )
        details = (
            f"{len(rows)} quote snapshot(s) present for this listing. "
            f"{source_detail}"
        )
    else:
        status, source_detail = _empty_status(sources)
        details = f"No quote rows for this listing. {source_detail}"
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
    sources: _CategorySources,
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
        source_status, source_detail = _assess_time_sensitive_rows(
            rows,
            sources=sources,
            timestamp_columns=_QUOTE_TS_COLUMNS,
            source_id_columns=("source_id",),
            now_utc=now_utc,
        )
        if source_status != "available":
            return CoverageCell(
                "price_quotes",
                source_status,
                source_detail,
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
            f"active listing(s); rows carry listing identifiers. {source_detail}",
            record_count=len(rows),
        )
    empty_status, empty_detail = _empty_status(sources)
    return CoverageCell(
        "price_quotes",
        empty_status,
        f"No quote rows for this entity. {empty_detail}",
    )


def _consensus_cell(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
    listing_ids: tuple[str, ...],
    *,
    entity_type: str,
    listing_owner: Mapping[str, str],
    sources: _CategorySources,
    now_utc: pd.Timestamp,
) -> CoverageCell:
    if entity_type == "private":
        return CoverageCell(
            "consensus",
            "not_applicable",
            "Private entity; analyst consensus does not apply without public disclosures.",
        )
    rows = _consensus_rows_for_entity(
        snapshot,
        entity_id,
        listing_owner,
    )
    if not rows.empty:
        source_status, source_detail = _assess_time_sensitive_rows(
            rows,
            sources=sources,
            timestamp_columns=_CONSENSUS_TS_COLUMNS,
            source_id_columns=("source_id", "provider"),
            now_utc=now_utc,
        )
        if source_status != "available":
            return CoverageCell(
                "consensus",
                source_status,
                source_detail,
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
            f"{len(rows)} consensus snapshot/revision row(s) linked to this "
            f"entity. {source_detail}",
            record_count=len(rows),
        )
    empty_status, empty_detail = _empty_status(sources)
    return CoverageCell(
        "consensus",
        empty_status,
        f"No consensus rows for this entity. {empty_detail}",
    )


def _earnings_actuals_cell(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
    listing_ids: tuple[str, ...],
    *,
    entity_type: str,
    listing_owner: Mapping[str, str],
    sources: _CategorySources,
    now_utc: pd.Timestamp,
) -> CoverageCell:
    if entity_type == "private":
        return CoverageCell(
            "earnings_actuals",
            "not_applicable",
            "Private entity; no public earnings-actuals concept.",
        )
    rows = _earnings_actuals_rows_for_entity(
        snapshot,
        entity_id,
        listing_owner=listing_owner,
    )
    if not rows.empty:
        source_status, source_detail = _assess_time_sensitive_rows(
            rows,
            sources=sources,
            timestamp_columns=_EARNINGS_ACTUALS_TS_COLUMNS,
            source_id_columns=("source_id",),
            now_utc=now_utc,
        )
        if source_status != "available":
            return CoverageCell(
                "earnings_actuals",
                source_status,
                source_detail,
                record_count=len(rows),
            )
        covered = _covered_listing_count(rows, listing_ids)
        if listing_ids and covered < len(listing_ids):
            return CoverageCell(
                "earnings_actuals",
                "partial",
                f"Earnings-actuals rows cover {covered} of {len(listing_ids)} "
                "active listings.",
                record_count=len(rows),
            )
        return CoverageCell(
            "earnings_actuals",
            "available",
            f"{len(rows)} earnings-actuals row(s) linked to this entity. "
            f"{source_detail}",
            record_count=len(rows),
        )
    empty_status, empty_detail = _empty_status(sources)
    return CoverageCell(
        "earnings_actuals",
        empty_status,
        f"No earnings-actuals rows for this entity. {empty_detail}",
    )


def _filings_news_cell(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
    *,
    stage1_entity_ids: set[str],
    listing_owner: Mapping[str, str],
    members_by_basket: Mapping[str, set[str]],
    sources: _CategorySources,
    now_utc: pd.Timestamp,
) -> CoverageCell:
    rows = _filings_rows_for_entity(
        snapshot,
        entity_id,
        stage1_entity_ids=stage1_entity_ids,
        listing_owner=listing_owner,
        members_by_basket=members_by_basket,
    )
    if not rows.empty:
        source_status, source_detail = _assess_time_sensitive_rows(
            rows,
            sources=sources,
            timestamp_columns=_FILINGS_TS_COLUMNS,
            source_id_columns=("source_id",),
            now_utc=now_utc,
        )
        if source_status != "available":
            return CoverageCell(
                "filings_news",
                source_status,
                source_detail,
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
            f"{len(rows)} filing/news item(s) linked to this entity. "
            f"{source_detail}",
            record_count=len(rows),
        )
    empty_status, empty_detail = _empty_status(sources)
    return CoverageCell(
        "filings_news",
        empty_status,
        f"No filing/news rows for this entity. {empty_detail}",
    )


def _event_component_status(
    row_count: int,
    *,
    sources: _CategorySources,
) -> tuple[CoverageStatusCode, str]:
    """Assess event rows independently from macro observations."""

    if row_count == 0:
        return _empty_status(sources)
    if sources.adverse:
        return (
            "partial",
            "Event rows exist, but source coverage is impaired: "
            + _source_state_details(sources.adverse),
        )
    if sources.no_records:
        return (
            "partial",
            "Event rows conflict with a governing source that completed "
            "with no records: "
            + _source_state_details(sources.no_records),
        )
    not_applicable = tuple(
        source
        for source in sources.sources
        if source.display_status == "not_applicable"
    )
    if not_applicable:
        return (
            "partial",
            "Event rows conflict with a governing source marked not "
            "applicable: "
            + _source_state_details(not_applicable),
        )
    if sources.stale:
        return (
            "partial",
            "Event rows exist, but a governing source is stale: "
            + _source_state_details(sources.stale),
        )
    event_uncertain = tuple(
        source
        for source in sources.uncertain
        if not (
            source.execution_completed
            and source.raw_status in {"available", "success", "ok"}
        )
    )
    if event_uncertain or not sources.sources:
        detail = (
            _source_state_details(event_uncertain)
            if event_uncertain
            else "no governing source-health records"
        )
        return "partial", f"Event rows exist, but {detail}."
    return "available", "Event source state checks passed."


def _events_cell(
    snapshot: ControlTowerSnapshot,
    entity_id: str,
    *,
    relation_map: Mapping[str, set[str]],
    sources: _CategorySources,
) -> CoverageCell:
    rows = _event_rows_for_entity(
        snapshot,
        entity_id,
        relation_map=relation_map,
    )
    status, detail = _event_component_status(len(rows), sources=sources)
    if rows.empty:
        return CoverageCell(
            "events",
            status,
            f"No event records linked to this entity. {detail}",
        )
    return CoverageCell(
        "events",
        status,
        f"{len(rows)} event record(s) linked to this entity in the local "
        f"registry. {detail}",
        record_count=len(rows),
    )


def _macro_cell(
    snapshot: ControlTowerSnapshot,
    *,
    sources: _CategorySources,
    now_utc: pd.Timestamp,
) -> CoverageCell:
    rows = snapshot.macro_observations
    count = len(rows) if not rows.empty else 0
    if count:
        source_status, source_detail = _assess_time_sensitive_rows(
            rows,
            sources=sources,
            timestamp_columns=_MACRO_TS_COLUMNS,
            source_id_columns=("source_id",),
            now_utc=now_utc,
        )
        return CoverageCell(
            "macro",
            source_status,
            f"{count} macro observation(s) on record. {source_detail}",
            record_count=count,
        )
    empty_status, empty_detail = _empty_status(sources)
    return CoverageCell(
        "macro",
        empty_status,
        f"No macro observations on record. {empty_detail}",
    )


def build_stage1_coverage_matrix(
    snapshot: ControlTowerSnapshot,
) -> Stage1CoverageMatrix:
    """Derive the honest Stage 1 coverage matrix from the artifact bundle.

    Deterministic per bundle: statuses come only from artifact presence, row
    counts, linkage, source-health/freshness and entity applicability.
    """

    now_utc = snapshot.now_utc
    states = _source_health_states(snapshot)
    sources = {
        category: _category_sources(states, category)
        for category in (*COVERAGE_CATEGORIES, "macro")
    }
    stage1_entity_ids = _stage1_entity_ids(snapshot)
    listing_by_entity, listing_owner = _active_listing_map(
        snapshot,
        stage1_entity_ids,
    )
    members_by_basket = _active_members_by_basket(
        snapshot,
        stage1_entity_ids,
    )
    event_relations = _event_relation_map(
        snapshot,
        stage1_entity_ids=stage1_entity_ids,
        listing_owner=listing_owner,
        members_by_basket=members_by_basket,
    )

    entity_rows: list[Stage1EntityCoverage] = []
    for raw in _entity_rows(snapshot):
        entity_id = _text(raw.get("entity_id"))
        if not entity_id:
            continue
        entity_type = _text(raw.get("entity_type")).lower() or "public"
        listing_ids = listing_by_entity.get(entity_id, ())
        cells: list[CoverageCell] = [
            _price_quotes_cell(
                snapshot,
                entity_id,
                listing_ids,
                entity_type=entity_type,
                sources=sources["price_quotes"],
                now_utc=now_utc,
            ),
            _consensus_cell(
                snapshot,
                entity_id,
                listing_ids,
                entity_type=entity_type,
                listing_owner=listing_owner,
                sources=sources["consensus"],
                now_utc=now_utc,
            ),
            _earnings_actuals_cell(
                snapshot,
                entity_id,
                listing_ids,
                entity_type=entity_type,
                listing_owner=listing_owner,
                sources=sources["earnings_actuals"],
                now_utc=now_utc,
            ),
            _filings_news_cell(
                snapshot,
                entity_id,
                stage1_entity_ids=stage1_entity_ids,
                listing_owner=listing_owner,
                members_by_basket=members_by_basket,
                sources=sources["filings_news"],
                now_utc=now_utc,
            ),
            _events_cell(
                snapshot,
                entity_id,
                relation_map=event_relations,
                sources=sources["events"],
            ),
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

    listing_rows: list[Stage1ListingCoverage] = []
    if not snapshot.listings.empty:
        for listing_id, entity_id in sorted(listing_owner.items()):
            matches = snapshot.listings.loc[
                snapshot.listings["listing_id"].astype("string").eq(listing_id)
            ]
            active_matches = [
                candidate
                for _, candidate in matches.iterrows()
                if _text(candidate.get("entity_id")) == entity_id
                and _text(candidate.get("listing_status")).lower() == "active"
                and _active_at_snapshot(candidate.to_dict(), snapshot)
            ]
            if not active_matches:
                continue
            row = active_matches[0]
            listing_rows.append(
                _listing_cell(
                    snapshot,
                    listing_id,
                    entity_id,
                    _text(row.get("canonical_ticker")) or listing_id,
                    sources=sources["price_quotes"],
                    now_utc=now_utc,
                )
            )

    macro_cell = _macro_cell(
        snapshot,
        sources=sources["macro"],
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


def _unambiguous_listing_owners(
    listings: pd.DataFrame,
) -> dict[str, str]:
    owner_candidates: dict[str, set[str]] = {}
    for _, listing in listings.iterrows():
        listing_id = _text(listing.get("listing_id"))
        entity_id = _text(listing.get("entity_id"))
        if listing_id and entity_id:
            owner_candidates.setdefault(listing_id, set()).add(entity_id)
    return {
        listing_id: next(iter(owners))
        for listing_id, owners in owner_candidates.items()
        if len(owners) == 1
    }


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
        set(_unambiguous_listing_owners(snapshot.listings)),
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
    if {"entity_id", "listing_id"} <= set(columns):
        listing_owner = _unambiguous_listing_owners(snapshot.listings)
        return sum(
            (
                bool(_text(row.get("listing_id")))
                and listing_owner.get(_text(row.get("listing_id"))) is not None
                and (
                    not _text(row.get("entity_id"))
                    or _text(row.get("entity_id"))
                    == listing_owner[_text(row.get("listing_id"))]
                )
            )
            or (
                not _text(row.get("listing_id"))
                and _text(row.get("entity_id")) in entity_ids
            )
            for _, row in frame.iterrows()
        )
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
    stage1_entity_ids = _stage1_entity_ids(snapshot)
    _, listing_owner = _active_listing_map(snapshot, stage1_entity_ids)
    members_by_basket = _active_members_by_basket(
        snapshot,
        stage1_entity_ids,
    )
    relation_map = _event_relation_map(
        snapshot,
        stage1_entity_ids=stage1_entity_ids,
        listing_owner=listing_owner,
        members_by_basket=members_by_basket,
    )
    return sum(
        bool(relation_map.get(_text(row.get("event_id")), set()))
        for _, row in snapshot.events.iterrows()
    )


def build_data_coverage_summary(snapshot: ControlTowerSnapshot) -> DataCoverageSummary:
    """Build a deterministic matrix of available records and explicit gaps.

    Counts describe record presence only. Linkage counts are emitted only when
    the snapshot contains an actual relation field or link registry; they are
    not a data-quality or investment-signal score. Statuses follow the six
    state vocabulary; a healthy source with zero rows is "no records", while a
    disconnected or failed source stays "unavailable".
    """

    states = _source_health_states(snapshot)
    source_groups = {
        category: _category_sources(states, category)
        for category in ("price_quotes", "consensus", "filings_news", "events", "macro")
    }

    quote_snapshots = snapshot.quote_snapshots
    quote_count = len(quote_snapshots) if not quote_snapshots.empty else 0
    if quote_count:
        linked_quotes = _linked_row_count(
            snapshot, quote_snapshots, ("listing_id",)
        )
        quote_status, source_detail = _assess_time_sensitive_rows(
            quote_snapshots,
            sources=source_groups["price_quotes"],
            timestamp_columns=_QUOTE_TS_COLUMNS,
            source_id_columns=("source_id",),
            now_utc=snapshot.now_utc,
        )
        if quote_status == "available" and linked_quotes != quote_count:
            quote_status = "partial"
        quote_status_text = COVERAGE_STATUS_LABELS[quote_status]
        quote_details = (
            f"{quote_count} latest quote snapshot{'s' if quote_count != 1 else ''} "
            f"present; {linked_quotes} carry listing identifiers that resolve "
            f"in the registry. {source_detail} Intraday bars are not yet in "
            "the V1 mart."
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
    else:
        quote_status, quote_detail = _empty_status(
            source_groups["price_quotes"]
        )
        rows = [
            CoverageRow(
                category="Price / Market Bars",
                status=COVERAGE_STATUS_LABELS[quote_status],
                status_code=quote_status,
                details=f"No price or market-bars artifact rows. {quote_detail}",
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
        consensus_rows = (
            pd.concat([snapshots, revisions], ignore_index=True)
            if not snapshots.empty and not revisions.empty
            else (snapshots if not snapshots.empty else revisions)
        )
        status_code, source_detail = _assess_time_sensitive_rows(
            consensus_rows,
            sources=source_groups["consensus"],
            timestamp_columns=_CONSENSUS_TS_COLUMNS,
            source_id_columns=("source_id", "provider"),
            now_utc=snapshot.now_utc,
        )
        if status_code == "available" and linked_count != consensus_count:
            status_code = "partial"
        status_text = COVERAGE_STATUS_LABELS[status_code]
        details = (
            f"{snapshot_count} consensus snapshot{'s' if snapshot_count != 1 else ''} and "
            f"{revision_count} revision record{'s' if revision_count != 1 else ''} present; "
            f"{linked_count} of {consensus_count} rows carry entity/listing identifiers "
            f"that resolve in the registry. {source_detail}"
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
    else:
        status_code, source_detail = _empty_status(
            source_groups["consensus"]
        )
        rows.append(
            CoverageRow(
                category="Consensus Data",
                status=COVERAGE_STATUS_LABELS[status_code],
                status_code=status_code,
                details=f"No consensus snapshots or revisions. {source_detail}",
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
        status_code, source_detail = _assess_time_sensitive_rows(
            filings,
            sources=source_groups["filings_news"],
            timestamp_columns=_FILINGS_TS_COLUMNS,
            source_id_columns=("source_id",),
            now_utc=snapshot.now_utc,
        )
        missing_geographies = _missing_geographies(
            snapshot,
            "filings_news",
        )
        if status_code == "available" and (
            not linked_count or missing_geographies
        ):
            status_code = "partial"
        status_text = COVERAGE_STATUS_LABELS[status_code]
        details = (
            f"{filing_count} news/filing item{'s' if filing_count != 1 else ''} "
            f"found; {linked_count} carry entity, listing, or basket identifiers "
            f"that resolve in the registry. {source_detail} Evidence without "
            "a relation is not assigned to a company."
            + (
                " The governing source records uncovered geographies."
                if missing_geographies
                else ""
            )
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
    else:
        status_code, source_detail = _empty_status(
            source_groups["filings_news"]
        )
        rows.append(
            CoverageRow(
                category="News & Filings",
                status=COVERAGE_STATUS_LABELS[status_code],
                status_code=status_code,
                details=f"No news or filing records. {source_detail}",
            )
        )

    event_count = len(snapshot.events) if not snapshot.events.empty else 0
    macro_count = (
        len(snapshot.macro_observations)
        if not snapshot.macro_observations.empty
        else 0
    )
    evidence_count = event_count + macro_count
    event_status, event_detail = _event_component_status(
        event_count,
        sources=source_groups["events"],
    )
    macro_cell = _macro_cell(
        snapshot,
        sources=source_groups["macro"],
        now_utc=snapshot.now_utc,
    )
    if evidence_count:
        linked_events = _linked_event_count(snapshot)
        evidence_status: CoverageStatusCode = (
            "available"
            if event_status == "available"
            and macro_cell.status_code == "available"
            else "partial"
        )
        rows.append(
            CoverageRow(
                category="Alternative Evidence / Events",
                status=COVERAGE_STATUS_LABELS[evidence_status],
                status_code=evidence_status,
                details=(
                    f"{event_count} event record{'s' if event_count != 1 else ''} and "
                    f"{macro_count} macro observation{'s' if macro_count != 1 else ''} present; "
                    f"event link registry covers {linked_events} event record{'s' if linked_events != 1 else ''}. "
                    f"Events: {event_detail} Macro: {macro_cell.details} "
                    + "This is evidence coverage, not a trading signal."
                ),
                record_count=evidence_count,
                linked_count=linked_events,
            )
        )
    else:
        macro_status = macro_cell.status_code
        if event_status == macro_status == "no_records":
            status_code = "no_records"
        elif event_status == macro_status == "unavailable":
            status_code = "unavailable"
        elif event_status == macro_status == "stale":
            status_code = "stale"
        else:
            status_code = "partial"
        rows.append(
            CoverageRow(
                category="Alternative Evidence / Events",
                status=COVERAGE_STATUS_LABELS[status_code],
                status_code=status_code,
                details=(
                    f"No evidence or event records. Events: {event_detail} "
                    f"Macro: {macro_cell.details}"
                ),
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
