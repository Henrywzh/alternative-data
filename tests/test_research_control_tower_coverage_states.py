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
        },
        {
            "source_id": "consensus_export",
            "source_kind": "consensus",
            "status": "unavailable",
            "row_count": 0,
            "entitlement_status": "terms_unverified",
        },
        {
            "source_id": "filings_sec_edgar",
            "source_kind": "filing",
            "status": "unavailable",
            "row_count": 0,
            "missing_geographies": "CN,HK",
        },
        {
            "source_id": "news_official_ai_rss",
            "source_kind": "news",
            "status": "unavailable",
            "row_count": 0,
        },
        {
            "source_id": "events:events",
            "source_kind": "events",
            "status": "available",
            "row_count": 0,
        },
        {
            "source_id": "registry:entities",
            "source_kind": "registry",
            "status": "available",
            "row_count": 6,
        },
        {
            "source_id": "fred_observations",
            "source_kind": "macro",
            "status": "unavailable",
            "row_count": 0,
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
) -> dict[str, object]:
    return {
        "quote_id": quote_id,
        "listing_id": listing_id,
        "quote_timestamp": timestamp,
        "retrieved_at_utc": timestamp,
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
    assert "freshness window" in cell.details

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
            },
            news_official_ai_rss={
                "status": "available",
                "row_count": 0,
                "source_latest_at": FRESH,
                "cadence": "event_driven",
            },
        )

    def filing(document_id: str, entity: str) -> dict[str, object]:
        return {
            "document_id": document_id,
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
            },
            news_official_ai_rss={
                "status": "available",
                "row_count": 0,
                "source_latest_at": FRESH,
                "cadence": "event_driven",
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
    linked = _matrix(_snapshot(events=events))
    assert linked.status_of("ALIBABA", "events") == "available"
    assert linked.status_of("BYTEDANCE", "events") == "available"
    assert linked.status_of("TENCENT", "events") == "no_records"


def test_macro_cell_transitions() -> None:
    assert _matrix(_snapshot()).global_macro.status_code == "unavailable"

    connected = _health(
        fred_observations={
            "status": "available",
            "row_count": 1,
            "source_latest_at": FRESH,
            "cadence": "monthly",
        }
    )
    empty = _snapshot(health=connected)
    assert _matrix(empty).global_macro.status_code == "no_records"

    macro = pd.DataFrame(
        [
            {
                "observation_id": "M1",
                "release_at": FRESH,
                "source_published_at": FRESH,
            }
        ]
    )
    populated = _snapshot(macro_observations=macro, health=connected)
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
