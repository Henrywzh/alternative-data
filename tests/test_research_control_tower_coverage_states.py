"""Batch 0: coverage-state semantics and identity/linkage QA.

These tests exercise the six coverage states (available, partial, stale,
not_applicable, no_records, unavailable) on synthetic Stage 1 fixtures only.
No live network, provider or Streamlit runtime is used.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest


APP_ROOT = Path(__file__).resolve().parents[1] / "apps" / "research-control-tower"

AS_OF = pd.Timestamp("2026-08-13T12:00:00Z")
FRESH = "2026-08-13T11:00:00Z"
OLD = "2026-07-01T00:00:00Z"

STAGE1_ENTITY_IDS = frozenset(
    {"ALIBABA", "TENCENT", "BYTEDANCE", "BAIDU", "KUAISHOU", "BILIBILI"}
)
ACTIVE_LISTING_IDS = frozenset(
    {"0700_HK", "1024_HK", "9626_HK", "9888_HK", "9988_HK", "BABA_US", "BIDU_US"}
)


@pytest.fixture(autouse=True)
def _imports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(APP_ROOT))


def _entities() -> pd.DataFrame:
    rows = [
        {
            "entity_id": "ALIBABA",
            "display_name": "Alibaba",
            "entity_type": "public",
            "active_status": "active",
        },
        {
            "entity_id": "TENCENT",
            "display_name": "Tencent",
            "entity_type": "public",
            "active_status": "active",
        },
        {
            "entity_id": "BYTEDANCE",
            "display_name": "ByteDance",
            "entity_type": "private",
            "active_status": "active",
        },
        {
            "entity_id": "BAIDU",
            "display_name": "Baidu",
            "entity_type": "public",
            "active_status": "active",
        },
        {
            "entity_id": "KUAISHOU",
            "display_name": "Kuaishou",
            "entity_type": "public",
            "active_status": "active",
        },
        {
            "entity_id": "BILIBILI",
            "display_name": "Bilibili",
            "entity_type": "public",
            "active_status": "active",
        },
    ]
    return pd.DataFrame(rows)


def _listings() -> pd.DataFrame:
    rows = [
        {"listing_id": "0700_HK", "entity_id": "TENCENT", "canonical_ticker": "0700.HK", "listing_status": "active"},
        {"listing_id": "1024_HK", "entity_id": "KUAISHOU", "canonical_ticker": "1024.HK", "listing_status": "active"},
        {"listing_id": "9626_HK", "entity_id": "BILIBILI", "canonical_ticker": "9626.HK", "listing_status": "active"},
        {"listing_id": "9888_HK", "entity_id": "BAIDU", "canonical_ticker": "9888.HK", "listing_status": "active"},
        {"listing_id": "9988_HK", "entity_id": "ALIBABA", "canonical_ticker": "9988.HK", "listing_status": "active"},
        {"listing_id": "BABA_US", "entity_id": "ALIBABA", "canonical_ticker": "BABA.US", "listing_status": "active"},
        {"listing_id": "BIDU_US", "entity_id": "BAIDU", "canonical_ticker": "BIDU.US", "listing_status": "active"},
    ]
    return pd.DataFrame(rows)


def _baskets() -> pd.DataFrame:
    return pd.DataFrame(
        [{"basket_id": "RESEARCH_STAGE_1_CHINA_INTERNET", "display_name": "Stage 1"}]
    )


def _memberships() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"entity_id": entity_id, "basket_id": "RESEARCH_STAGE_1_CHINA_INTERNET"}
            for entity_id in STAGE1_ENTITY_IDS
        ]
    )


def _health(**overrides: dict[str, object]) -> pd.DataFrame:
    """Production-like source-health rows; per-source overrides by source_id."""

    rows = [
        {
            "source_id": "quote_snapshots",
            "source_kind": "market",
            "status": "unavailable",
            "row_count": 0,
            "query_attempted": False,
            "execution_status": None,
            "completed_at": None,
        },
        {
            "source_id": "consensus_export",
            "source_kind": "consensus",
            "status": "unavailable",
            "row_count": 0,
            "entitlement_status": "terms_unverified",
            "query_attempted": False,
            "execution_status": None,
            "completed_at": None,
        },
        {
            "source_id": "filings_sec_edgar",
            "source_kind": "filing",
            "status": "unavailable",
            "row_count": 0,
            "missing_geographies": "CN,HK",
            "query_attempted": False,
            "execution_status": None,
            "completed_at": None,
        },
        {
            "source_id": "news_official_ai_rss",
            "source_kind": "news",
            "status": "unavailable",
            "row_count": 0,
            "query_attempted": False,
            "execution_status": None,
            "completed_at": None,
        },
        {
            "source_id": "events:events",
            "source_kind": "events",
            "status": "available",
            "row_count": 0,
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        },
        {
            "source_id": "registry:entities",
            "source_kind": "registry",
            "status": "available",
            "row_count": 6,
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        },
        {
            "source_id": "fred_observations",
            "source_kind": "macro",
            "status": "unavailable",
            "row_count": 0,
            "query_attempted": False,
            "execution_status": None,
            "completed_at": None,
        },
        {
            "source_id": "official_filings",
            "source_kind": "official_filing",
            "status": "unavailable",
            "row_count": 0,
            "query_attempted": False,
            "execution_status": None,
            "completed_at": None,
        },
        {
            "source_id": "earnings_actuals",
            "source_kind": "earnings",
            "status": "unavailable",
            "row_count": 0,
            "query_attempted": False,
            "execution_status": None,
            "completed_at": None,
        },
    ]
    for source_id, values in overrides.items():
        for row in rows:
            if row["source_id"] == source_id:
                row.update(values)
    return pd.DataFrame(rows)


def _snapshot(
    *,
    quotes: pd.DataFrame | None = None,
    consensus_snapshots: pd.DataFrame | None = None,
    consensus_revisions: pd.DataFrame | None = None,
    news_filings: pd.DataFrame | None = None,
    official_filings: pd.DataFrame | None = None,
    earnings_actuals: pd.DataFrame | None = None,
    events: pd.DataFrame | None = None,
    macro_observations: pd.DataFrame | None = None,
    health: pd.DataFrame | None = None,
) -> "object":
    from control_tower.models import ControlTowerSnapshot

    def frame(columns: tuple[str, ...]) -> pd.DataFrame:
        return pd.DataFrame({column: pd.Series(dtype="object") for column in columns})

    snapshot = ControlTowerSnapshot(
        entities=_entities(),
        listings=_listings(),
        baskets=_baskets(),
        basket_memberships=_memberships(),
        indices=frame(("index_id",)),
        events=(
            events
            if events is not None
            else frame(("event_id", "related_entity_ids"))
        ),
        event_entity_links=frame(("event_id", "target_type", "target_id")),
        event_basket_links=frame(("event_id", "target_type", "target_id")),
        event_watch_questions=frame(("event_id", "question_id")),
        macro_observations=(
            macro_observations
            if macro_observations is not None
            else frame(("observation_id", "release_at", "source_published_at"))
        ),
        consensus_snapshots=(
            consensus_snapshots
            if consensus_snapshots is not None
            else frame(
                ("snapshot_id", "entity_id", "listing_id", "provider_asof", "snapshot_at")
            )
        ),
        consensus_revisions=(
            consensus_revisions
            if consensus_revisions is not None
            else frame(
                ("revision_id", "entity_id", "listing_id", "provider_asof", "current_snapshot_at")
            )
        ),
        quote_snapshots=(
            quotes
            if quotes is not None
            else frame(("quote_id", "listing_id", "quote_timestamp", "retrieved_at_utc"))
        ),
        news_filings=(
            news_filings
            if news_filings is not None
            else frame(
                (
                    "document_id",
                    "related_entity_ids",
                    "related_listing_ids",
                    "related_basket_ids",
                    "published_at",
                )
            )
        ),
        official_filings=(
            official_filings
            if official_filings is not None
            else frame(
                (
                    "document_id",
                    "entity_id",
                    "listing_id",
                    "source_id",
                    "published_at",
                    "accepted_at",
                )
            )
        ),
        earnings_calendar=frame(
            (
                "calendar_id",
                "entity_id",
                "listing_id",
                "event_date",
                "period_end",
            )
        ),
        earnings_actuals=(
            earnings_actuals
            if earnings_actuals is not None
            else frame(
                (
                    "actual_id",
                    "entity_id",
                    "listing_id",
                    "metric",
                    "source_id",
                    "filing_at",
                    "period_end",
                )
            )
        ),
        source_health=health if health is not None else _health(),
        manifest={"build_id": "coverage-states-fixture"},
        status="success",
        missing_optional=(),
        degraded_reasons={},
        build_id="coverage-states-fixture",
        built_at_utc=AS_OF,
        as_of_utc=AS_OF,
        previous_build_at=None,
    )
    return snapshot


def _quote(
    quote_id: str,
    listing_id: str,
    timestamp: str = FRESH,
    *,
    source_id: str = "quote_snapshots",
    retrieved_at_utc: str | None = None,
) -> dict[str, object]:
    return {
        "quote_id": quote_id,
        "listing_id": listing_id,
        "quote_timestamp": timestamp,
        "retrieved_at_utc": retrieved_at_utc or timestamp,
        "source_id": source_id,
    }


def _consensus(
    snapshot_id: str,
    entity_id: str,
    listing_id: str,
    provider_asof: str = FRESH,
) -> dict[str, object]:
    return {
        "snapshot_id": snapshot_id,
        "entity_id": entity_id,
        "listing_id": listing_id,
        "provider_asof": provider_asof,
        "snapshot_at": provider_asof,
    }


def _matrix(snapshot: "object"):
    from control_tower.coverage import build_stage1_coverage_matrix

    return build_stage1_coverage_matrix(snapshot)


def test_coverage_status_contract_declares_all_six_states() -> None:
    from typing import get_args

    from control_tower.coverage import (
        COVERAGE_STATUS_DESCRIPTIONS,
        COVERAGE_STATUS_LABELS,
        COVERAGE_STATUS_ORDER,
        CoverageStatusCode,
    )

    assert set(COVERAGE_STATUS_ORDER) == {
        "available",
        "partial",
        "stale",
        "not_applicable",
        "no_records",
        "unavailable",
    }
    assert set(COVERAGE_STATUS_LABELS) == set(COVERAGE_STATUS_ORDER)
    assert set(COVERAGE_STATUS_DESCRIPTIONS) == set(COVERAGE_STATUS_ORDER)
    assert all(isinstance(status, str) for status in COVERAGE_STATUS_ORDER)
    # The literal must accept exactly the six states.
    assert set(get_args(CoverageStatusCode)) == set(COVERAGE_STATUS_ORDER)


def test_stage1_matrix_counts_six_entities_and_seven_active_listings() -> None:
    matrix = _matrix(_snapshot())

    assert {row.entity_id for row in matrix.entity_rows} == STAGE1_ENTITY_IDS
    assert len(matrix.entity_rows) == 6
    assert {row.listing_id for row in matrix.listing_rows} == ACTIVE_LISTING_IDS
    assert len(matrix.listing_rows) == 7

    bytedance = next(
        row for row in matrix.entity_rows if row.entity_id == "BYTEDANCE"
    )
    assert bytedance.entity_type == "private"
    assert bytedance.listing_count == 0
    assert bytedance.listing_ids == ()
    # A private entity must never create a fake listing row.
    assert all(row.entity_id != "BYTEDANCE" for row in matrix.listing_rows)


def test_private_bytedance_quote_consensus_and_earnings_are_not_applicable() -> None:
    matrix = _matrix(_snapshot())

    assert matrix.status_of("BYTEDANCE", "price_quotes") == "not_applicable"
    assert matrix.status_of("BYTEDANCE", "consensus") == "not_applicable"
    assert matrix.status_of("BYTEDANCE", "earnings_actuals") == "not_applicable"
    # Public entities keep the honest unavailable state; they are not
    # exempted from the quote/consensus concept.
    assert matrix.status_of("ALIBABA", "price_quotes") == "unavailable"
    assert matrix.status_of("ALIBABA", "consensus") == "unavailable"
    assert matrix.status_of("ALIBABA", "earnings_actuals") == "unavailable"
    cell = matrix.entity_cell("BYTEDANCE", "price_quotes")
    assert "Private entity" in cell.details


def test_available_quote_status_from_fresh_linked_rows() -> None:
    quotes = pd.DataFrame(
        [
            _quote("Q1", "9988_HK"),
            _quote("Q2", "BABA_US"),
        ]
    )
    health = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 2,
            "source_latest_at": FRESH,
            "cadence": "daily",
        }
    )
    matrix = _matrix(_snapshot(quotes=quotes, health=health))

    cell = matrix.entity_cell("ALIBABA", "price_quotes")
    assert cell.status_code == "available"
    assert cell.record_count == 2
    assert "listing identifiers" in cell.details
    alibaba_listing = {row.listing_id for row in matrix.listing_rows if row.entity_id == "ALIBABA"}
    assert alibaba_listing == {"9988_HK", "BABA_US"}
    assert all(
        row.status_code == "available"
        for row in matrix.listing_rows
        if row.entity_id == "ALIBABA"
    )


def test_partial_quote_status_when_rows_cover_only_some_listings() -> None:
    quotes = pd.DataFrame([_quote("Q1", "9988_HK")])
    health = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 1,
            "source_latest_at": FRESH,
            "cadence": "daily",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        }
    )
    matrix = _matrix(_snapshot(quotes=quotes, health=health))

    cell = matrix.entity_cell("ALIBABA", "price_quotes")
    assert cell.status_code == "partial"
    assert "1 of 2" in cell.details
    # The listing without a quote row is a per-listing no_records state.
    baba = next(row for row in matrix.listing_rows if row.listing_id == "BABA_US")
    assert baba.status_code == "no_records"


def test_stale_quote_status_from_freshness_window() -> None:
    quotes = pd.DataFrame(
        [
            _quote("Q1", "9988_HK", timestamp=OLD),
            _quote("Q2", "BABA_US", timestamp=OLD),
        ]
    )
    health = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 2,
            "source_latest_at": OLD,
            "cadence": "daily",
            "stale_after_days": 3,
        }
    )
    snapshot = _snapshot(quotes=quotes, health=health)
    matrix = _matrix(snapshot)

    cell = matrix.entity_cell("ALIBABA", "price_quotes")
    assert cell.status_code == "stale"
    assert "freshness SLA" in cell.details

    from control_tower.coverage import build_data_coverage_summary

    summary = {
        row.category: row for row in build_data_coverage_summary(snapshot).rows
    }
    assert summary["Price / Market Quotes"].status_code == "stale"
    assert summary["Price / Market Quotes"].status == "Stale"


def test_no_records_when_source_connected_but_zero_matching_rows() -> None:
    health = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 0,
            "source_latest_at": FRESH,
            "cadence": "daily",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        }
    )
    snapshot = _snapshot(health=health)
    matrix = _matrix(snapshot)

    assert matrix.status_of("ALIBABA", "price_quotes") == "no_records"
    assert all(
        row.status_code == "no_records" for row in matrix.listing_rows
    )

    from control_tower.coverage import build_data_coverage_summary

    summary = {
        row.category: row for row in build_data_coverage_summary(snapshot).rows
    }
    assert summary["Price / Market Bars"].status_code == "no_records"
    assert summary["Price / Market Bars"].status == "No records"


def test_unavailable_when_source_disconnected_or_failed_never_no_records() -> None:
    snapshot = _snapshot()  # production-like: quote source unavailable
    matrix = _matrix(snapshot)

    assert matrix.status_of("ALIBABA", "price_quotes") == "unavailable"
    assert matrix.status_of("TENCENT", "consensus") == "unavailable"
    assert all(row.status_code == "unavailable" for row in matrix.listing_rows)

    from control_tower.coverage import build_data_coverage_summary

    summary = {
        row.category: row for row in build_data_coverage_summary(snapshot).rows
    }
    assert summary["Price / Market Bars"].status_code == "unavailable"
    assert summary["Consensus Data"].status_code == "unavailable"

    # A failed/error source stays unavailable even with zero rows.
    failed = _health(
        quote_snapshots={"status": "failed", "row_count": 0, "detail": "boom"}
    )
    assert _matrix(_snapshot(health=failed)).status_of(
        "ALIBABA", "price_quotes"
    ) == "unavailable"


def test_consensus_status_transitions() -> None:
    from control_tower.coverage import build_data_coverage_summary

    connected = _health(
        consensus_export={
            "status": "available",
            "row_count": 2,
            "source_latest_at": FRESH,
            "cadence": "weekly",
            "entitlement_status": "active",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        }
    )
    available = _snapshot(
        consensus_snapshots=pd.DataFrame(
            [
                _consensus("S1", "ALIBABA", "9988_HK"),
                _consensus("S2", "ALIBABA", "BABA_US"),
            ]
        ),
        health=connected,
    )
    matrix = _matrix(available)
    assert matrix.status_of("ALIBABA", "consensus") == "available"
    assert matrix.status_of("TENCENT", "consensus") == "no_records"
    summary = {
        row.category: row for row in build_data_coverage_summary(available).rows
    }
    assert summary["Consensus Data"].status_code == "available"

    partial = _snapshot(
        consensus_snapshots=pd.DataFrame([_consensus("S1", "ALIBABA", "9988_HK")]),
        health=connected,
    )
    assert _matrix(partial).status_of("ALIBABA", "consensus") == "partial"

    stale = _snapshot(
        consensus_snapshots=pd.DataFrame(
            [_consensus("S1", "ALIBABA", "9988_HK", provider_asof=OLD)]
        ),
        health=connected,
    )
    assert _matrix(stale).status_of("ALIBABA", "consensus") == "stale"

    empty_connected = _snapshot(
        health=_health(
            consensus_export={
                "status": "available",
                "row_count": 0,
                "source_latest_at": FRESH,
                "cadence": "weekly",
                "entitlement_status": "active",
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            }
        )
    )
    matrix = _matrix(empty_connected)
    assert matrix.status_of("ALIBABA", "consensus") == "no_records"
    summary = {
        row.category: row
        for row in build_data_coverage_summary(empty_connected).rows
    }
    assert summary["Consensus Data"].status_code == "no_records"


def test_filings_news_status_transitions() -> None:
    from control_tower.coverage import build_data_coverage_summary

    def connected_filings() -> pd.DataFrame:
        return _health(
            filings_sec_edgar={
                "status": "available",
                "row_count": 1,
                "source_latest_at": FRESH,
                "cadence": "event_driven",
                "missing_geographies": None,
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            },
            news_official_ai_rss={
                "status": "available",
                "row_count": 0,
                "source_latest_at": FRESH,
                "cadence": "event_driven",
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            },
            # This test exercises the news_filings path only; the
            # official_filings governing source is also part of the
            # filings_news category and must be an explicitly completed,
            # non-adverse run so it doesn't mask the news_filings signal.
            official_filings={
                "status": "available",
                "row_count": 0,
                "source_latest_at": FRESH,
                "cadence": "event_driven",
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            },
        )

    def filing(document_id: str, entity: str) -> dict[str, object]:
        return {
            "document_id": document_id,
            "source_id": "filings_sec_edgar",
            "related_entity_ids": entity,
            "related_listing_ids": None,
            "related_basket_ids": None,
            "published_at": FRESH,
        }

    connected = connected_filings()
    available = _snapshot(
        news_filings=pd.DataFrame([filing("D1", "ALIBABA")]), health=connected
    )
    matrix = _matrix(available)
    assert matrix.status_of("ALIBABA", "filings_news") == "available"
    assert matrix.status_of("TENCENT", "filings_news") == "no_records"

    # Unlinked items degrade the category summary to partial.
    unlinked = _snapshot(
        news_filings=pd.DataFrame(
            [
                {
                    "document_id": "D1",
                    "related_entity_ids": None,
                    "related_listing_ids": None,
                    "related_basket_ids": None,
                    "published_at": FRESH,
                }
            ]
        ),
        health=connected,
    )
    summary = {
        row.category: row for row in build_data_coverage_summary(unlinked).rows
    }
    assert summary["News & Filings"].status_code == "partial"

    # A governing source with uncovered geographies degrades to partial.
    partial_geo = _snapshot(
        news_filings=pd.DataFrame([filing("D1", "ALIBABA")]),
        health=_health(
            filings_sec_edgar={
                "status": "available",
                "row_count": 1,
                "source_latest_at": FRESH,
                "cadence": "event_driven",
                "missing_geographies": "CN,HK",
            },
            news_official_ai_rss={
                "status": "available",
                "row_count": 0,
                "source_latest_at": FRESH,
                "cadence": "event_driven",
            },
        ),
    )
    assert _matrix(partial_geo).status_of("ALIBABA", "filings_news") == "partial"

    # A successful filings run with zero rows is no_records, not unavailable.
    empty_connected = _snapshot(
        health=_health(
            filings_sec_edgar={
                "status": "available",
                "row_count": 0,
                "source_latest_at": FRESH,
                "cadence": "event_driven",
                "missing_geographies": None,
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            },
            news_official_ai_rss={
                "status": "available",
                "row_count": 0,
                "source_latest_at": FRESH,
                "cadence": "event_driven",
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            },
            official_filings={
                "status": "available",
                "row_count": 0,
                "source_latest_at": FRESH,
                "cadence": "event_driven",
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            },
        )
    )
    matrix = _matrix(empty_connected)
    assert matrix.status_of("ALIBABA", "filings_news") == "no_records"
    summary = {
        row.category: row
        for row in build_data_coverage_summary(empty_connected).rows
    }
    assert summary["News & Filings"].status_code == "no_records"


def test_earnings_actuals_available_from_populated_frame_and_healthy_source() -> None:
    """Regression for the P0: earnings_actuals cell must read snapshot.earnings_actuals.

    Before the fix, ``_earnings_actuals_cell`` took only ``entity_type`` and
    hardcoded ``unavailable`` for every public entity regardless of what was
    in the artifact bundle. This reproduces a populated, healthy case and
    asserts the cell is no longer falsely unavailable.
    """

    earnings_actuals = pd.DataFrame(
        [
            {
                "actual_id": "A1",
                "entity_id": "BILIBILI",
                "listing_id": "9626_HK",
                "metric": "eps_basic",
                "period_end": "2026-03-31",
                "filing_at": FRESH,
                "published_at": FRESH,
                "source_id": "earnings_actuals",
            }
        ]
    )
    health = _health(
        earnings_actuals={
            "status": "available",
            "row_count": 1,
            "source_latest_at": FRESH,
            "cadence": "quarterly",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        }
    )
    matrix = _matrix(
        _snapshot(earnings_actuals=earnings_actuals, health=health)
    )

    cell = matrix.entity_cell("BILIBILI", "earnings_actuals")
    assert cell.status_code != "unavailable"
    assert cell.status_code == "available"
    assert cell.record_count == 1
    # Private entities are unaffected by this fix.
    assert matrix.status_of("BYTEDANCE", "earnings_actuals") == "not_applicable"


def test_official_filings_available_from_populated_frame_and_healthy_source() -> None:
    """Regression for the P0: filings_news must also read snapshot.official_filings.

    Before the fix, ``_filings_rows_for_entity`` only read ``news_filings``
    (relation-linked, empty in production) and ignored ``official_filings``
    (519 rows, direct entity_id/listing_id columns). This also exercises exact
    source_id resolution against the namespaced governing source: the
    official_filings collector writes the mart row's source_id already
    namespaced ("filings:hkexnews"), identical to the source_health record
    for the same provider, so ``resolve()`` matches it exactly with no
    suffix-guessing fallback.
    """

    official_filings = pd.DataFrame(
        [
            {
                "document_id": "OF1",
                "entity_id": "TENCENT",
                "listing_id": "0700_HK",
                "source_id": "filings:hkexnews",
                "published_at": FRESH,
                "accepted_at": FRESH,
            }
        ]
    )
    base_health = _health(
        filings_sec_edgar={
            "status": "available",
            "row_count": 0,
            "source_latest_at": FRESH,
            "cadence": "event_driven",
            "missing_geographies": None,
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        },
        news_official_ai_rss={
            "status": "available",
            "row_count": 0,
            "source_latest_at": FRESH,
            "cadence": "event_driven",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        },
        official_filings={
            "status": "available",
            "row_count": 1,
            "source_latest_at": FRESH,
            "cadence": "event_driven",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        },
    )
    # The per-provider governing source is namespaced ("filings:hkexnews")
    # and is not part of the base fixture list, so it is appended directly.
    health = pd.concat(
        [
            base_health,
            pd.DataFrame(
                [
                    {
                        "source_id": "filings:hkexnews",
                        "source_kind": "official_filing",
                        "status": "available",
                        "row_count": 1,
                        "source_latest_at": FRESH,
                        "cadence": "event_driven",
                        "query_attempted": True,
                        "execution_status": "completed",
                        "completed_at": FRESH,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    matrix = _matrix(
        _snapshot(official_filings=official_filings, health=health)
    )

    cell = matrix.entity_cell("TENCENT", "filings_news")
    assert cell.status_code != "unavailable"
    assert cell.status_code == "available"
    assert cell.record_count == 1


def test_official_filings_bare_source_id_is_partial_not_a_suffix_guess() -> None:
    """T2: the namespace-suffix fallback in ``_CategorySources.resolve`` is gone.

    A mart row carrying the old bare provider id ("hkexnews") no longer
    resolves to the namespaced governing source ("filings:hkexnews") by
    matching the trailing suffix. This is deliberate: that fallback rotted
    (it silently returns None once a second source shares the same suffix)
    and is the wrong layer to encode producer identity. A row whose source_id
    does not exactly match its governing source_health record is an honest
    ``partial``, with a reason that points at the row's own source_id — never
    a fabricated ``available``.
    """

    official_filings = pd.DataFrame(
        [
            {
                "document_id": "OF1",
                "entity_id": "TENCENT",
                "listing_id": "0700_HK",
                "source_id": "hkexnews",
                "published_at": FRESH,
                "accepted_at": FRESH,
            }
        ]
    )
    base_health = _health(
        filings_sec_edgar={
            "status": "available",
            "row_count": 0,
            "source_latest_at": FRESH,
            "cadence": "event_driven",
            "missing_geographies": None,
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        },
        news_official_ai_rss={
            "status": "available",
            "row_count": 0,
            "source_latest_at": FRESH,
            "cadence": "event_driven",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        },
        official_filings={
            "status": "available",
            "row_count": 1,
            "source_latest_at": FRESH,
            "cadence": "event_driven",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        },
    )
    health = pd.concat(
        [
            base_health,
            pd.DataFrame(
                [
                    {
                        "source_id": "filings:hkexnews",
                        "source_kind": "official_filing",
                        "status": "available",
                        "row_count": 1,
                        "source_latest_at": FRESH,
                        "cadence": "event_driven",
                        "query_attempted": True,
                        "execution_status": "completed",
                        "completed_at": FRESH,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    matrix = _matrix(
        _snapshot(official_filings=official_filings, health=health)
    )

    cell = matrix.entity_cell("TENCENT", "filings_news")
    assert cell.status_code == "partial"
    assert "hkexnews" in cell.details
    assert "cannot be matched" in cell.details


def test_events_are_no_records_when_registry_read_but_nothing_linked() -> None:
    matrix = _matrix(_snapshot())
    assert all(
        matrix.status_of(entity_id, "events") == "no_records"
        for entity_id in STAGE1_ENTITY_IDS
    )

    events = pd.DataFrame(
        [
            {
                "event_id": "EV_1",
                "related_entity_ids": ("ALIBABA",),
            },
            {
                "event_id": "EV_2",
                "related_entity_ids": ("BYTEDANCE",),
            },
        ]
    )
    event_health = _health(
        **{
            "events:events": {
                "status": "available",
                "row_count": 2,
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            }
        }
    )
    linked = _matrix(_snapshot(events=events, health=event_health))
    assert linked.status_of("ALIBABA", "events") == "available"
    assert linked.status_of("BYTEDANCE", "events") == "available"
    assert linked.status_of("TENCENT", "events") == "no_records"


def test_macro_cell_transitions() -> None:
    assert _matrix(_snapshot()).global_macro.status_code == "unavailable"

    connected = _health(
        fred_observations={
            "status": "available",
            "row_count": 0,
            "source_latest_at": FRESH,
            "cadence": "monthly",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        }
    )
    empty = _snapshot(health=connected)
    assert _matrix(empty).global_macro.status_code == "no_records"

    macro = pd.DataFrame(
        [
            {
                "observation_id": "M1",
                "source_id": "fred_observations",
                "release_at": FRESH,
                "source_published_at": FRESH,
            }
        ]
    )
    populated_health = _health(
        fred_observations={
            "status": "available",
            "row_count": 1,
            "source_latest_at": FRESH,
            "cadence": "monthly",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        }
    )
    populated = _snapshot(macro_observations=macro, health=populated_health)
    assert _matrix(populated).global_macro.status_code == "available"


def test_source_health_classifier_distinguishes_no_records_from_unavailable() -> None:
    from control_tower.pages.source_health import (
        classify_source_health,
        source_health_counts,
    )

    frame = pd.DataFrame(
        [
            {
                "source_id": "connected-empty",
                "status": "available",
                "row_count": 0,
                "source_latest_at": FRESH,
                "cadence": "daily",
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            },
            {
                "source_id": "connected-populated",
                "status": "available",
                "row_count": 4,
                "source_latest_at": FRESH,
                "cadence": "daily",
            },
            {
                "source_id": "disconnected",
                "status": "unavailable",
                "row_count": 0,
            },
            {
                "source_id": "failed",
                "status": "failed",
                "row_count": 0,
            },
            {
                "source_id": "na",
                "status": "not_applicable",
                "row_count": 0,
            },
        ]
    )
    classified = classify_source_health(frame, now_utc=AS_OF)
    by_id = classified.set_index("source_id")
    assert by_id.loc["connected-empty", "display_status"] == "no_records"
    assert by_id.loc["connected-empty", "display_label"] == "No records"
    assert by_id.loc["connected-populated", "display_status"] == "healthy"
    assert by_id.loc["disconnected", "display_status"] == "unavailable"
    assert by_id.loc["failed", "display_status"] == "failed"
    assert by_id.loc["na", "display_status"] == "not_applicable"
    assert by_id.loc["na", "display_label"] == "Not applicable"

    counts = source_health_counts(classified)
    assert counts["no_records"] == 1
    assert counts["not_applicable"] == 1
    assert counts["available"] == 2
    assert counts["unavailable_degraded"] == 1
    assert counts["errors_gaps"] == 1


def test_identity_and_linkage_qa_rejects_unresolvable_quote_rows() -> None:
    """Quote rows whose listing_id does not resolve to the registry are not
    silently counted as entity coverage."""

    quotes = pd.DataFrame(
        [
            _quote("Q1", "9988_HK"),
            _quote("Q2", "FAKE_US"),  # not in the registry
        ]
    )
    health = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 2,
            "source_latest_at": FRESH,
            "cadence": "daily",
        }
    )
    snapshot = _snapshot(quotes=quotes, health=health)
    matrix = _matrix(snapshot)
    # Only the registry-resolvable row counts toward entity coverage.
    assert matrix.status_of("ALIBABA", "price_quotes") == "partial"
    # FAKE_US is not a registry listing, so it never appears in the matrix.
    assert all(row.listing_id != "FAKE_US" for row in matrix.listing_rows)

    from control_tower.coverage import build_data_coverage_summary

    summary = {
        row.category: row for row in build_data_coverage_summary(snapshot).rows
    }
    quote_row = summary["Price / Market Quotes"]
    assert quote_row.status_code == "partial"
    assert quote_row.linked_count == 1
    assert quote_row.record_count == 2


def test_matrix_derivation_is_deterministic_per_bundle() -> None:
    quotes = pd.DataFrame([_quote("Q1", "9988_HK")])
    health = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 1,
            "source_latest_at": FRESH,
            "cadence": "daily",
        }
    )
    first = _matrix(_snapshot(quotes=quotes, health=health))
    second = _matrix(_snapshot(quotes=quotes.copy(), health=health.copy()))
    assert [
        cell.status_code for row in first.entity_rows for cell in row.cells
    ] == [
        cell.status_code for row in second.entity_rows for cell in row.cells
    ]
    assert [row.details for row in first.listing_rows] == [
        row.details for row in second.listing_rows
    ]
    assert first.global_macro == second.global_macro


def test_ui_labels_are_human_readable_without_provider_query_language() -> None:
    from control_tower.components.coverage_matrix import (
        coverage_legend_html,
        stage1_matrix_to_dataframe,
    )

    matrix = _matrix(_snapshot())
    frame = stage1_matrix_to_dataframe(matrix)
    status_columns = [column for column in frame.columns if column.endswith("_status")]
    assert status_columns
    labels = set(frame[status_columns].to_numpy().ravel())
    assert labels <= {"Available", "Partial", "Stale", "No records", "Not applicable", "Unavailable"}
    assert labels == {"Not applicable", "No records", "Unavailable"}

    details_text = " ".join(
        str(value)
        for column in frame.columns
        if column.endswith("_details")
        for value in frame[column]
    ).lower()
    for forbidden in ("querying", "fetching", "live query", "calling provider"):
        assert forbidden not in details_text

    legend = coverage_legend_html()
    assert "Available" in legend and "Not applicable" in legend
    assert "No records" in legend and "Unavailable" in legend


def test_matrix_falls_back_to_active_entities_without_stage1_basket() -> None:
    from dataclasses import replace

    snapshot = _snapshot()
    fallback = replace(
        snapshot,
        baskets=pd.DataFrame(),
        basket_memberships=pd.DataFrame(),
    )
    matrix = _matrix(fallback)
    assert {row.entity_id for row in matrix.entity_rows} == STAGE1_ENTITY_IDS


def test_zero_rows_require_explicit_completed_execution_evidence() -> None:
    from control_tower.pages.source_health import classify_source_health

    unexecuted = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 0,
            "source_latest_at": FRESH,
            "cadence": "daily",
            "query_attempted": False,
            "execution_status": None,
            "completed_at": None,
        }
    )
    classified = classify_source_health(unexecuted, now_utc=AS_OF)
    quote = classified.loc[classified["source_id"].eq("quote_snapshots")].iloc[0]
    assert quote["display_status"] != "no_records"
    assert _matrix(_snapshot(health=unexecuted)).status_of(
        "ALIBABA", "price_quotes"
    ) != "no_records"

    incomplete = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 0,
            "source_latest_at": FRESH,
            "cadence": "daily",
            "query_attempted": True,
            "execution_status": "running",
            "completed_at": None,
        }
    )
    classified = classify_source_health(incomplete, now_utc=AS_OF)
    quote = classified.loc[classified["source_id"].eq("quote_snapshots")].iloc[0]
    assert quote["display_status"] != "no_records"


@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        ("stale", "stale"),
        ("not_applicable", "not_applicable"),
        ("failed", "failed"),
        ("entitlement_required", "entitlement_error"),
        ("mystery", "unclassified"),
    ],
)
def test_zero_rows_preserve_explicit_source_semantics(
    raw_status: str,
    expected: str,
) -> None:
    from control_tower.pages.source_health import classify_source_health

    health = _health(
        quote_snapshots={
            "status": raw_status,
            "row_count": 0,
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        }
    )
    classified = classify_source_health(health, now_utc=AS_OF)
    quote = classified.loc[classified["source_id"].eq("quote_snapshots")].iloc[0]
    assert quote["display_status"] == expected


def test_zero_rows_preserve_clock_skew_instead_of_no_records() -> None:
    from control_tower.pages.source_health import classify_source_health

    future = (AS_OF + pd.Timedelta(hours=1)).isoformat()
    health = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 0,
            "source_latest_at": future,
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
            "cadence": "daily",
        }
    )
    classified = classify_source_health(health, now_utc=AS_OF)
    quote = classified.loc[classified["source_id"].eq("quote_snapshots")].iloc[0]
    assert quote["display_status"] == "clock_skew"
    assert _matrix(_snapshot(health=health)).status_of(
        "ALIBABA", "price_quotes"
    ) == "partial"


def test_completed_zero_rows_preserve_derived_stale_status() -> None:
    from control_tower.pages.source_health import classify_source_health

    health = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 0,
            "source_latest_at": OLD,
            "retrieved_at_utc": FRESH,
            "stale_after_days": 3,
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
            "cadence": "daily",
        }
    )
    classified = classify_source_health(health, now_utc=AS_OF)
    quote = classified.loc[classified["source_id"].eq("quote_snapshots")].iloc[0]
    assert quote["display_status"] == "stale"


@pytest.mark.parametrize(
    ("raw_status", "expected"),
    [
        ("failed", "failed"),
        ("stale", "stale"),
        ("not_applicable", "not_applicable"),
    ],
)
def test_explicit_states_take_precedence_over_future_completion_metadata(
    raw_status: str,
    expected: str,
) -> None:
    from control_tower.pages.source_health import classify_source_health

    future = (AS_OF + pd.Timedelta(hours=1)).isoformat()
    health = _health(
        quote_snapshots={
            "status": raw_status,
            "row_count": 0,
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": future,
        }
    )
    classified = classify_source_health(health, now_utc=AS_OF)
    quote = classified.loc[classified["source_id"].eq("quote_snapshots")].iloc[0]
    assert quote["display_status"] == expected


def test_retrieval_time_cannot_mask_stale_source_observation() -> None:
    quotes = pd.DataFrame(
        [
            _quote(
                "Q1",
                "9988_HK",
                OLD,
                retrieved_at_utc=FRESH,
            ),
            _quote(
                "Q2",
                "BABA_US",
                OLD,
                retrieved_at_utc=FRESH,
            ),
        ]
    )
    health = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 2,
            "source_latest_at": OLD,
            "retrieved_at_utc": FRESH,
            "stale_after_days": 3,
            "cadence": "daily",
        }
    )
    matrix = _matrix(_snapshot(quotes=quotes, health=health))
    assert matrix.status_of("ALIBABA", "price_quotes") == "stale"


def test_time_sensitive_available_requires_source_timestamp_and_matched_sla() -> None:
    missing_source_time = pd.DataFrame(
        [
            _quote("Q1", "9988_HK"),
            _quote("Q2", "BABA_US"),
        ]
    )
    missing_source_time["quote_timestamp"] = None
    health = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 2,
            "source_latest_at": (AS_OF - pd.Timedelta(days=2)).isoformat(),
            "retrieved_at_utc": FRESH,
            "cadence": "daily",
            "stale_after_days": 1,
        }
    )
    assert _matrix(
        _snapshot(quotes=missing_source_time, health=health)
    ).status_of("ALIBABA", "price_quotes") == "partial"

    two_days_old = (AS_OF - pd.Timedelta(days=2)).isoformat()
    quotes = pd.DataFrame(
        [
            _quote("Q1", "9988_HK", two_days_old),
            _quote("Q2", "BABA_US", two_days_old),
        ]
    )
    assert _matrix(_snapshot(quotes=quotes, health=health)).status_of(
        "ALIBABA", "price_quotes"
    ) == "stale"


@pytest.mark.parametrize("bad_status", ["failed", "entitlement_required"])
def test_failed_or_entitlement_source_with_rows_is_partial(
    bad_status: str,
) -> None:
    quotes = pd.DataFrame(
        [
            _quote("Q1", "9988_HK"),
            _quote("Q2", "BABA_US"),
        ]
    )
    health = _health(
        quote_snapshots={
            "status": bad_status,
            "row_count": 2,
            "source_latest_at": FRESH,
            "cadence": "daily",
        }
    )
    cell = _matrix(_snapshot(quotes=quotes, health=health)).entity_cell(
        "ALIBABA", "price_quotes"
    )
    assert cell.status_code == "partial"
    assert bad_status.replace("_", " ") in cell.details.lower()


def test_denied_entitlement_with_rows_is_partial() -> None:
    quotes = pd.DataFrame(
        [
            _quote("Q1", "9988_HK"),
            _quote("Q2", "BABA_US"),
        ]
    )
    health = _health(
        quote_snapshots={
            "status": "available",
            "entitlement_status": "denied",
            "row_count": 2,
            "source_latest_at": FRESH,
            "cadence": "daily",
        }
    )
    cell = _matrix(_snapshot(quotes=quotes, health=health)).entity_cell(
        "ALIBABA", "price_quotes"
    )
    assert cell.status_code == "partial"
    assert "entitlement error" in cell.details.lower()


def test_mismatched_consensus_entity_and_listing_ownership_is_rejected() -> None:
    health = _health(
        consensus_export={
            "status": "available",
            "row_count": 1,
            "source_latest_at": FRESH,
            "cadence": "weekly",
            "entitlement_status": "active",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        }
    )
    mismatched = pd.DataFrame(
        [_consensus("S1", "ALIBABA", "0700_HK")]
    )
    matrix = _matrix(
        _snapshot(consensus_snapshots=mismatched, health=health)
    )
    assert matrix.status_of("ALIBABA", "consensus") == "no_records"
    assert matrix.status_of("TENCENT", "consensus") == "no_records"


def test_stage1_matrix_honours_entity_membership_and_listing_intervals() -> None:
    from dataclasses import replace

    snapshot = _snapshot()
    entities = snapshot.entities.copy()
    entities["active_from"] = pd.NaT
    entities["active_to"] = pd.NaT
    entities.loc[entities["entity_id"].eq("BILIBILI"), "active_to"] = "2026-08-13"

    memberships = snapshot.basket_memberships.copy()
    memberships["active_from"] = pd.NaT
    memberships["active_to"] = pd.NaT
    memberships.loc[
        memberships["entity_id"].eq("KUAISHOU"), "active_from"
    ] = "2026-08-14"

    listings = snapshot.listings.copy()
    listings["active_from"] = pd.NaT
    listings["active_to"] = pd.NaT
    listings.loc[listings["listing_id"].eq("BABA_US"), "active_to"] = "2026-08-13"
    listings = pd.concat(
        [
            listings,
            pd.DataFrame(
                [
                    {
                        "listing_id": "ARCHIVED_OTHER",
                        "entity_id": "OUTSIDE_STAGE1",
                        "canonical_ticker": "OUT.US",
                        "listing_status": "active",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    matrix = _matrix(
        replace(
            snapshot,
            entities=entities,
            basket_memberships=memberships,
            listings=listings,
        )
    )
    entity_ids = {row.entity_id for row in matrix.entity_rows}
    listing_ids = {row.listing_id for row in matrix.listing_rows}
    assert "BILIBILI" not in entity_ids
    assert "KUAISHOU" not in entity_ids
    assert "9626_HK" not in listing_ids
    assert "1024_HK" not in listing_ids
    assert "BABA_US" not in listing_ids
    assert "ARCHIVED_OTHER" not in listing_ids
    assert listing_ids <= ACTIVE_LISTING_IDS


def test_mixed_source_states_with_records_are_partial() -> None:
    quotes = pd.DataFrame(
        [
            _quote("Q1", "9988_HK", source_id="quote_snapshots"),
            _quote("Q2", "BABA_US", source_id="quote_snapshots"),
        ]
    )
    health = pd.concat(
        [
            _health(
                quote_snapshots={
                    "status": "available",
                    "row_count": 2,
                    "source_latest_at": FRESH,
                    "cadence": "daily",
                }
            ),
            pd.DataFrame(
                [
                    {
                        "source_id": "provider:backup_quotes",
                        "source_kind": "market",
                        "status": "unavailable",
                        "row_count": 0,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    cell = _matrix(_snapshot(quotes=quotes, health=health)).entity_cell(
        "ALIBABA", "price_quotes"
    )
    assert cell.status_code == "partial"
    assert "backup quotes" in cell.details.lower()


def test_macro_rows_do_not_green_unavailable_providers() -> None:
    macro = pd.DataFrame(
        [
            {
                "observation_id": "M1",
                "source_id": "fred_observations",
                "release_at": FRESH,
                "source_published_at": FRESH,
            }
        ]
    )
    cell = _matrix(_snapshot(macro_observations=macro)).global_macro
    assert cell.status_code == "partial"
    assert "unavailable" in cell.details.lower()


def test_event_link_registries_resolve_listing_basket_and_intervals() -> None:
    from dataclasses import replace

    snapshot = _snapshot(
        events=pd.DataFrame(
            [
                {"event_id": "EV_LISTING"},
                {"event_id": "EV_BASKET"},
                {
                    "event_id": "EV_EXPIRED",
                    # Mirrors repository enrichment from the registry. The
                    # expired authoritative link below must still win.
                    "related_entity_ids": ("TENCENT",),
                },
            ]
        ),
        health=_health(
            **{
                "events:events": {
                    "status": "available",
                    "row_count": 3,
                    "query_attempted": True,
                    "execution_status": "completed",
                    "completed_at": FRESH,
                }
            }
        ),
    )
    entity_links = pd.DataFrame(
        [
            {
                "event_id": "EV_LISTING",
                "target_type": "listing",
                "target_id": "BABA_US",
                "active_from": "2026-01-01",
                "active_to": None,
            },
            {
                "event_id": "EV_EXPIRED",
                "target_type": "entity",
                "target_id": "TENCENT",
                "active_from": "2026-01-01",
                "active_to": "2026-08-13",
            },
        ]
    )
    basket_links = pd.DataFrame(
        [
            {
                "event_id": "EV_BASKET",
                "target_type": "basket",
                "target_id": "RESEARCH_STAGE_1_CHINA_INTERNET",
                "active_from": "2026-01-01",
                "active_to": None,
            }
        ]
    )
    matrix = _matrix(
        replace(
            snapshot,
            event_entity_links=entity_links,
            event_basket_links=basket_links,
        )
    )
    assert matrix.entity_cell("ALIBABA", "events").record_count == 2
    assert matrix.entity_cell("BYTEDANCE", "events").record_count == 1
    assert matrix.entity_cell("TENCENT", "events").record_count == 1


def test_legacy_zero_row_source_health_requires_review_before_no_records() -> None:
    from control_tower.pages.source_health import classify_source_health

    health = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 0,
            "source_latest_at": FRESH,
            "cadence": "daily",
        }
    )
    classified = classify_source_health(health, now_utc=AS_OF)
    quote = classified.loc[classified["source_id"].eq("quote_snapshots")].iloc[0]

    assert quote["display_status"] == "review_required"
    assert _matrix(_snapshot(health=health)).status_of(
        "ALIBABA", "price_quotes"
    ) == "unavailable"


def test_denied_entitlement_outranks_completed_zero_row_no_records() -> None:
    from control_tower.pages.source_health import classify_source_health

    health = _health(
        quote_snapshots={
            "status": "no_records",
            "row_count": 0,
            "source_latest_at": FRESH,
            "cadence": "daily",
            "entitlement_status": "denied",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        }
    )
    classified = classify_source_health(health, now_utc=AS_OF)
    quote = classified.loc[classified["source_id"].eq("quote_snapshots")].iloc[0]

    assert quote["display_status"] == "entitlement_error"
    assert _matrix(_snapshot(health=health)).status_of(
        "ALIBABA", "price_quotes"
    ) == "unavailable"


def test_artifact_rows_conflict_with_completed_zero_row_source_health() -> None:
    from control_tower.coverage import build_data_coverage_summary

    quotes = pd.DataFrame(
        [
            _quote("Q1", "9988_HK"),
            _quote("Q2", "BABA_US"),
        ]
    )
    health = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 0,
            "source_latest_at": FRESH,
            "cadence": "daily",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        }
    )
    snapshot = _snapshot(quotes=quotes, health=health)
    matrix = _matrix(snapshot)

    assert matrix.status_of("ALIBABA", "price_quotes") == "partial"
    assert all(
        row.status_code == "partial"
        for row in matrix.listing_rows
        if row.entity_id == "ALIBABA"
    )
    summary = {
        row.category: row for row in build_data_coverage_summary(snapshot).rows
    }
    assert summary["Price / Market Quotes"].status_code == "partial"


def test_present_stage1_basket_with_no_active_memberships_has_empty_matrix() -> None:
    from dataclasses import replace

    snapshot = _snapshot()
    matrix = _matrix(
        replace(
            snapshot,
            basket_memberships=snapshot.basket_memberships.iloc[0:0].copy(),
        )
    )

    assert matrix.entity_rows == ()
    assert matrix.listing_rows == ()


def test_evidence_summary_assesses_unavailable_macro_when_events_have_rows() -> None:
    from control_tower.coverage import build_data_coverage_summary

    events = pd.DataFrame(
        [{"event_id": "EV_VALID", "related_entity_ids": ("ALIBABA",)}]
    )
    health = _health(
        **{
            "events:events": {
                "status": "available",
                "row_count": 1,
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            }
        }
    )
    summary = {
        row.category: row
        for row in build_data_coverage_summary(
            _snapshot(events=events, health=health)
        ).rows
    }
    evidence = summary["Alternative Evidence / Events"]

    assert evidence.status_code == "partial"
    assert "fred" in evidence.details.lower()


def test_summary_linked_event_count_uses_active_authoritative_links() -> None:
    from dataclasses import replace
    from control_tower.coverage import build_data_coverage_summary

    events = pd.DataFrame(
        [
            {"event_id": "EV_ACTIVE", "related_entity_ids": ("ALIBABA",)},
            {"event_id": "EV_EXPIRED", "related_entity_ids": ("TENCENT",)},
        ]
    )
    health = _health(
        **{
            "events:events": {
                "status": "available",
                "row_count": 2,
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            }
        }
    )
    snapshot = replace(
        _snapshot(events=events, health=health),
        event_entity_links=pd.DataFrame(
            [
                {
                    "event_id": "EV_ACTIVE",
                    "target_type": "entity",
                    "target_id": "ALIBABA",
                    "active_from": "2026-01-01",
                    "active_to": None,
                },
                {
                    "event_id": "EV_EXPIRED",
                    "target_type": "entity",
                    "target_id": "TENCENT",
                    "active_from": "2026-01-01",
                    "active_to": "2026-08-13",
                },
            ]
        ),
    )
    summary = {
        row.category: row for row in build_data_coverage_summary(snapshot).rows
    }

    assert summary["Alternative Evidence / Events"].linked_count == 1
    assert _matrix(snapshot).status_of("TENCENT", "events") == "no_records"


def test_empty_evidence_mixes_completed_events_and_unavailable_macro_as_partial() -> None:
    from control_tower.coverage import build_data_coverage_summary

    summary = {
        row.category: row
        for row in build_data_coverage_summary(_snapshot()).rows
    }
    evidence = summary["Alternative Evidence / Events"]

    assert evidence.record_count == 0
    assert evidence.status_code == "partial"
    assert "completed execution" in evidence.details.lower()
    assert "fred observations is unavailable" in evidence.details.lower()


def test_empty_stage1_matrix_renderer_keeps_schema_and_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    from control_tower.components import coverage_matrix as component

    snapshot = _snapshot()
    matrix = _matrix(
        replace(
            snapshot,
            basket_memberships=snapshot.basket_memberships.iloc[0:0].copy(),
        )
    )
    entity_frame = component.stage1_matrix_to_dataframe(matrix)
    listing_frame = component.stage1_listings_to_dataframe(matrix)

    assert list(entity_frame.columns) == [
        "entity_id",
        "display_name",
        "entity_type",
        "listing_count",
        "listing_ids",
        *[
            column
            for category in matrix.categories
            for column in (
                f"{category}_status",
                f"{category}_details",
            )
        ],
    ]
    assert list(listing_frame.columns) == [
        "listing_id",
        "entity_id",
        "canonical_ticker",
        "quote_status",
        "details",
    ]

    class _NoopContext:
        def __enter__(self) -> "_NoopContext":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

    monkeypatch.setattr(component.st, "dataframe", lambda *args, **kwargs: None)
    monkeypatch.setattr(component.st, "caption", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        component.st,
        "expander",
        lambda *args, **kwargs: _NoopContext(),
    )
    component.render_stage1_coverage_matrix(matrix)


def test_ambiguous_listing_is_unlinked_and_cannot_make_global_quotes_available() -> None:
    from dataclasses import replace

    from control_tower.coverage import build_data_coverage_summary

    snapshot = _snapshot()
    listings = pd.concat(
        [
            snapshot.listings,
            pd.DataFrame(
                [
                    {
                        "listing_id": "9988_HK",
                        "entity_id": "TENCENT",
                        "canonical_ticker": "9988.HK",
                        "listing_status": "active",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    health = _health(
        quote_snapshots={
            "status": "available",
            "row_count": 1,
            "source_latest_at": FRESH,
            "cadence": "daily",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        }
    )
    ambiguous = replace(
        _snapshot(
            quotes=pd.DataFrame([_quote("Q_AMBIG", "9988_HK")]),
            health=health,
        ),
        listings=listings,
    )
    quote = next(
        row
        for row in build_data_coverage_summary(ambiguous).rows
        if row.category == "Price / Market Quotes"
    )

    assert quote.linked_count == 0
    assert quote.status_code == "partial"
    assert all(row.listing_id != "9988_HK" for row in _matrix(ambiguous).listing_rows)


def test_expired_stage1_basket_has_no_members_and_never_falls_back() -> None:
    from dataclasses import replace

    snapshot = _snapshot()
    baskets = snapshot.baskets.copy()
    baskets["active_from"] = "2020-01-01"
    baskets["active_to"] = "2026-08-13"
    matrix = _matrix(replace(snapshot, baskets=baskets))

    assert matrix.entity_rows == ()
    assert matrix.listing_rows == ()


def test_filings_missing_geographies_are_partial_in_matrix_and_summary() -> None:
    from control_tower.coverage import build_data_coverage_summary

    filings = pd.DataFrame(
        [
            {
                "document_id": "F_MISSING_GEO",
                "source_id": "filings_sec_edgar",
                "related_entity_ids": ("ALIBABA",),
                "related_listing_ids": (),
                "related_basket_ids": (),
                "published_at": FRESH,
            }
        ]
    )
    health = _health(
        filings_sec_edgar={
            "status": "available",
            "row_count": 1,
            "source_latest_at": FRESH,
            "cadence": "event_driven",
            "missing_geographies": "CN,HK",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        },
        news_official_ai_rss={
            "status": "available",
            "row_count": 0,
            "source_latest_at": FRESH,
            "cadence": "event_driven",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        },
    )
    snapshot = _snapshot(news_filings=filings, health=health)
    matrix = _matrix(snapshot)
    summary = {
        row.category: row
        for row in build_data_coverage_summary(snapshot).rows
    }

    assert matrix.status_of("ALIBABA", "filings_news") == "partial"
    assert summary["News & Filings"].status_code == "partial"
    assert "uncovered geographies" in summary["News & Filings"].details.lower()


def test_not_applicable_issuer_ir_source_no_longer_marks_category_adverse() -> None:
    """Regression for the review_required issuer-IR defect.

    ``filings:issuer_ir`` / ``earnings:hkex_issuer_ir`` are deliberately
    out-of-scope (issuer-IR HTML scraping is a non-goal; SEC/HKEX metadata
    is the intended source). Before the fix, the collector reported them as
    ``no_records`` with a ``monthly`` cadence and zero rows, which
    ``classify_source_health`` aged into a permanent ``review_required`` --
    an adverse display status (``review_required`` is a member of
    ``_UNAVAILABLE_SOURCE_STATES``). ``_CategorySources.adverse`` treats
    that as "the provider is effectively absent" for the *whole* category
    (``_empty_status`` short-circuits on ``sources.adverse`` before looking
    at any specific entity's own rows), so every entity with zero rows in
    that category -- e.g. TENCENT/KUAISHOU/BILIBILI's real earnings_actuals
    gap -- read "unavailable" forever via that specific guard, even though
    the source genuinely was queried (a private-collector policy decision,
    not a failure).

    Now that the collector reports these sources as ``not_applicable``
    (not a member of ``_UNAVAILABLE_SOURCE_STATES``), that specific
    "adverse" cap no longer fires -- confirmed below by the category
    status changing from "unavailable" (old raw emission) to "partial"
    (new raw emission) for the identical fixture, with the detail text no
    longer mentioning ``review_required``.

    This test deliberately does NOT assert "available": a separate,
    pre-existing and intentionally-conservative guard in ``_empty_status``
    only reaches "not_applicable"/"no_records" when *every* governing
    source in the category agrees; with a healthy governing source
    (filings:hkexnews / earnings:sec_companyfacts) mixed in, the honest
    outcome is "partial" ("No matching rows and source execution
    completion is not fully evidenced"), which is untouched by this
    defect fix (the acceptance bar explicitly forbids weakening
    ``_assess_time_sensitive_rows``/``_empty_status``'s fail-closed logic).
    A truthful "partial" here is correct, not a shortfall.
    """

    def _health_for(issuer_ir_status: str, issuer_ir_cadence: str) -> pd.DataFrame:
        base_health = _health(
            filings_sec_edgar={
                "status": "available",
                "row_count": 0,
                "source_latest_at": FRESH,
                "cadence": "event_driven",
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            },
            news_official_ai_rss={
                "status": "available",
                "row_count": 0,
                "source_latest_at": FRESH,
                "cadence": "event_driven",
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            },
            official_filings={
                "status": "available",
                "row_count": 100,
                "source_latest_at": FRESH,
                "cadence": "event_driven",
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            },
            earnings_actuals={
                "status": "available",
                "row_count": 100,
                "source_latest_at": FRESH,
                "cadence": "quarterly",
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            },
        )
        extra_sources = pd.DataFrame(
            [
                {
                    "source_id": "filings:hkexnews",
                    "source_kind": "official_filing",
                    "status": "available",
                    "row_count": 100,
                    "source_latest_at": FRESH,
                    "cadence": "daily",
                    "query_attempted": True,
                    "execution_status": "completed",
                    "completed_at": FRESH,
                },
                {
                    "source_id": "filings:issuer_ir",
                    "source_kind": "official_filing",
                    "status": issuer_ir_status,
                    "row_count": 0,
                    "cadence": issuer_ir_cadence,
                },
                {
                    "source_id": "earnings:sec_companyfacts",
                    "source_kind": "earnings",
                    "status": "available",
                    "row_count": 100,
                    "source_latest_at": FRESH,
                    "cadence": "weekly",
                    "query_attempted": True,
                    "execution_status": "completed",
                    "completed_at": FRESH,
                },
                {
                    "source_id": "earnings:hkex_issuer_ir",
                    "source_kind": "earnings",
                    "status": issuer_ir_status,
                    "row_count": 0,
                    "cadence": issuer_ir_cadence,
                },
            ]
        )
        return pd.concat([base_health, extra_sources], ignore_index=True)

    # TENCENT has zero rows in both categories in this fixture (no
    # official_filings/earnings_actuals rows are supplied at all), mirroring
    # the real production shape for an HK-only issuer's earnings_actuals gap.
    fixed_matrix = _matrix(_snapshot(health=_health_for("not_applicable", "")))
    filings_cell = fixed_matrix.entity_cell("TENCENT", "filings_news")
    assert filings_cell.status_code == "partial"
    assert "review_required" not in filings_cell.details
    assert "review required" not in filings_cell.details.lower()
    earnings_cell = fixed_matrix.entity_cell("TENCENT", "earnings_actuals")
    assert earnings_cell.status_code == "partial"
    assert "review_required" not in earnings_cell.details
    assert "review required" not in earnings_cell.details.lower()

    # Same fixture, but with the OLD (pre-fix) raw emission -- no_records,
    # monthly cadence, zero rows, no execution-completion evidence -- to
    # prove the category really was capped "unavailable" before this
    # defect fix, not merely a status this test invented.
    stale_matrix = _matrix(_snapshot(health=_health_for("no_records", "monthly")))
    stale_filings_cell = stale_matrix.entity_cell("TENCENT", "filings_news")
    assert stale_filings_cell.status_code == "unavailable"
    assert "review required" in stale_filings_cell.details.lower()
    stale_earnings_cell = stale_matrix.entity_cell("TENCENT", "earnings_actuals")
    assert stale_earnings_cell.status_code == "unavailable"
    assert "review required" in stale_earnings_cell.details.lower()


def test_hk_only_issuer_earnings_actuals_never_reaches_available() -> None:
    """Trap regression: fixing the issuer-IR adverse-cap defect must not
    manufacture earnings data for HK-only issuers.

    TENCENT/KUAISHOU/BILIBILI have no SEC XBRL CIK and no issuer-IR
    snapshot is configured (a deliberate non-goal, see
    ``earnings_actuals.py``), so ``earnings_actuals`` genuinely has zero
    rows for them -- unlike ALIBABA/BAIDU, who do have SEC XBRL actuals.
    The honest state for "every configured source was queried and there is
    nothing for this entity" is ``no_records`` (or, if another governing
    source in the same category has a real, unrelated issue, an honest
    ``partial``) -- never ``available`` (rows were never queried into
    existence) and never silently masked as ``unavailable`` (the sources
    were, in fact, queried).
    """

    # No earnings_actuals rows at all for TENCENT/KUAISHOU/BILIBILI.
    earnings_actuals = pd.DataFrame(
        [
            {
                "actual_id": "A1",
                "entity_id": "ALIBABA",
                "listing_id": "BABA_US",
                "metric": "eps_basic",
                "period_end": "2026-03-31",
                "filing_at": FRESH,
                "source_id": "earnings:sec_companyfacts",
            }
        ]
    )
    base_health = _health(
        earnings_actuals={
            "status": "available",
            "row_count": 1,
            "source_latest_at": FRESH,
            "cadence": "quarterly",
            "query_attempted": True,
            "execution_status": "completed",
            "completed_at": FRESH,
        },
    )
    extra_sources = pd.DataFrame(
        [
            {
                "source_id": "earnings:sec_companyfacts",
                "source_kind": "earnings",
                "status": "available",
                "row_count": 1,
                "source_latest_at": FRESH,
                "cadence": "weekly",
                "query_attempted": True,
                "execution_status": "completed",
                "completed_at": FRESH,
            },
            {
                "source_id": "earnings:hkex_issuer_ir",
                "source_kind": "earnings",
                "status": "not_applicable",
                "row_count": 0,
                "cadence": "",
                "detail": (
                    "HKEX-only issuers without SEC XBRL actuals: BILIBILI, "
                    "KUAISHOU, TENCENT; no machine-readable issuer IR "
                    "actuals snapshot configured; no values fabricated"
                ),
            },
        ]
    )
    health = pd.concat([base_health, extra_sources], ignore_index=True)
    matrix = _matrix(
        _snapshot(earnings_actuals=earnings_actuals, health=health)
    )

    for entity_id in ("TENCENT", "KUAISHOU", "BILIBILI"):
        status = matrix.status_of(entity_id, "earnings_actuals")
        assert status != "available", (
            f"{entity_id} has zero earnings_actuals rows and must not read "
            f"'available'; got {status!r}"
        )
        assert status in {"no_records", "partial"}
    # ALIBABA genuinely has SEC XBRL rows. It does not reach "available"
    # either here -- the category-wide "any not_applicable governing
    # source" guard in _assess_time_sensitive_rows (see the companion test
    # above) conservatively marks every entity in the category "partial"
    # while earnings:hkex_issuer_ir remains part of the governing set, not
    # just the HK-only issuers. That guard is untouched by this fix; the
    # point of this assertion is that ALIBABA's real data is not
    # misclassified as "unavailable" or "no_records" -- it is honestly
    # "partial", never silently upgraded to "available".
    assert matrix.status_of("ALIBABA", "earnings_actuals") == "partial"
