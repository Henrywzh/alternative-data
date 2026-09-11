"""Focused contract tests for the Phase 1 semantic layer."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pandas as pd

APP_ROOT = Path(__file__).resolve().parents[1] / "apps" / "research-control-tower"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from control_tower.components.timeline import catalyst_view_for_event, select_next_catalyst
from control_tower.company_profiles import get_company_profile
from control_tower.filters import apply_event_filters
from control_tower.models import ControlTowerSnapshot, EventFilters
from control_tower.pages.company import _load_southbound_holdings, _openrouter_daily_frame
from control_tower.semantics import (
    catalyst_state_for_row,
    classify_catalyst,
    filter_loaded_frames_to_as_of,
    filter_snapshot_to_as_of,
    page_filter_context,
    resolve_catalyst_interval,
)


def _empty_snapshot() -> ControlTowerSnapshot:
    as_of = pd.Timestamp("2026-08-10T12:00:00Z")
    empty = pd.DataFrame()
    return ControlTowerSnapshot(
        entities=empty.copy(),
        listings=empty.copy(),
        baskets=empty.copy(),
        basket_memberships=empty.copy(),
        indices=empty.copy(),
        events=empty.copy(),
        event_entity_links=empty.copy(),
        event_basket_links=empty.copy(),
        event_watch_questions=empty.copy(),
        macro_observations=empty.copy(),
        consensus_snapshots=empty.copy(),
        consensus_revisions=empty.copy(),
        quote_snapshots=empty.copy(),
        news_filings=empty.copy(),
        official_filings=empty.copy(),
        earnings_calendar=empty.copy(),
        earnings_actuals=empty.copy(),
        source_health=empty.copy(),
        manifest={},
        status="success",
        missing_optional=(),
        degraded_reasons={},
        build_id="phase1-test",
        built_at_utc=as_of + pd.Timedelta(hours=1),
        as_of_utc=as_of,
        previous_build_at=None,
    )


def test_catalyst_lifecycle_distinguishes_open_date_only_and_terminal_rows() -> None:
    now = pd.Timestamp("2026-08-15T12:00:00Z")

    assert classify_catalyst("2026-08-01T00:00:00Z", None, now) == "active"
    assert (
        classify_catalyst(
            "2026-08-15",
            None,
            now,
            date_precision="day",
            source_tz="Asia/Hong_Kong",
        )
        == "active"
    )
    assert (
        classify_catalyst(
            "2026-08-15",
            None,
            pd.Timestamp("2026-08-15T16:00:00Z"),
            date_precision="day",
            source_tz="Asia/Hong_Kong",
        )
        == "expired"
    )
    assert classify_catalyst("2026-08-20T00:00:00Z", "2026-08-21T00:00:00Z", now) == "future"
    assert classify_catalyst("2026-08-01T00:00:00Z", "2026-08-02T00:00:00Z", now) == "expired"
    assert classify_catalyst("2026-08-20T00:00:00Z", None, now, status="completed") == "completed"
    assert classify_catalyst("2026-08-20T00:00:00Z", None, now, status="cancelled") == "cancelled"
    assert classify_catalyst("2026-08-20T00:00:00Z", None, now, event_type="coverage_gap") == "unavailable"
    assert classify_catalyst("2026-08-21T00:00:00Z", "2026-08-20T00:00:00Z", now) == "unavailable"


def test_forward_event_filters_and_next_catalyst_never_promote_expired_rows() -> None:
    now = pd.Timestamp("2026-08-15T12:00:00Z")
    events = pd.DataFrame(
        [
            {
                "event_id": "completed",
                "event_type": "earnings",
                "status": "completed",
                "importance": "high",
                "starts_at": "2026-08-01T00:00:00Z",
                "ends_at": None,
            },
            {
                "event_id": "expired",
                "event_type": "earnings",
                "status": "scheduled",
                "importance": "high",
                "starts_at": "2026-08-01T00:00:00Z",
                "ends_at": "2026-08-02T00:00:00Z",
            },
            {
                "event_id": "open",
                "event_type": "thesis_checkpoint",
                "status": "active",
                "importance": "high",
                "starts_at": "2026-08-01T00:00:00Z",
                "ends_at": None,
            },
            {
                "event_id": "day",
                "event_type": "earnings",
                "status": "scheduled",
                "importance": "low",
                "date_precision": "day",
                "source_timezone": "UTC",
                "starts_at": "2026-08-15",
                "ends_at": None,
            },
            {
                "event_id": "future",
                "event_type": "earnings",
                "status": "scheduled",
                "importance": "high",
                "starts_at": "2026-08-20T00:00:00Z",
                "ends_at": "2026-08-21T00:00:00Z",
            },
        ]
    )

    filtered = apply_event_filters(events, EventFilters(now_utc=now))
    assert set(filtered["event_id"]) == {"open", "day", "future"}

    next_row = select_next_catalyst(events, now)
    assert next_row is not None
    assert next_row["event_id"] == "open"

    day_view = catalyst_view_for_event(
        None,
        events.loc[events["event_id"].eq("day")].iloc[0],
        now_utc=now,
        viewer_timezone="Asia/Taipei",
    )
    assert day_view is not None
    assert day_view.starts_at == pd.Timestamp("2026-08-15T00:00:00Z")


def test_snapshot_as_of_filters_all_source_marts_and_orphaned_dependencies() -> None:
    snapshot = _empty_snapshot()
    old_event = {
        "event_id": "old-event",
        "source_published_at": pd.Timestamp("2026-08-10T10:00:00Z"),
    }
    future_event = {
        "event_id": "future-event",
        "source_published_at": pd.Timestamp("2026-08-10T13:00:00Z"),
    }
    old_claim = {"claim_id": "old-claim", "last_reviewed_at_utc": "2026-08-10T10:00:00Z"}
    future_claim = {"claim_id": "future-claim", "last_reviewed_at_utc": "2026-08-10T13:00:00Z"}
    old_evidence = {
        "evidence_id": "old-evidence",
        "published_at": "2026-08-10T10:00:00Z",
        "observed_at_utc": "2026-08-10T10:00:00Z",
    }
    future_evidence = {
        "evidence_id": "future-evidence",
        "published_at": "2026-08-10T13:00:00Z",
        "observed_at_utc": "2026-08-10T13:00:00Z",
    }
    snapshot = replace(
        snapshot,
        events=pd.DataFrame([old_event, future_event]),
        event_entity_links=pd.DataFrame(
            [
                {"event_id": "old-event", "target_type": "entity", "target_id": "E1"},
                {"event_id": "future-event", "target_type": "entity", "target_id": "E1"},
            ]
        ),
        event_watch_questions=pd.DataFrame(
            [
                {"event_id": "old-event", "question": "old"},
                {"event_id": "future-event", "question": "future"},
            ]
        ),
        quote_snapshots=pd.DataFrame(
            [
                {"quote_id": "q-old", "quote_timestamp": "2026-08-10T12:00:00Z"},
                {"quote_id": "q-future", "quote_timestamp": "2026-08-10T12:00:01Z"},
            ]
        ),
        price_bars=pd.DataFrame(
            [
                {"bar_id": "b-old", "bar_date": "2026-08-10"},
                {"bar_id": "b-future", "bar_date": "2026-08-11"},
            ]
        ),
        consensus_snapshots=pd.DataFrame(
            [
                {"snapshot_id": "c-old", "snapshot_at": "2026-08-10T12:00:00Z"},
                {"snapshot_id": "c-future", "snapshot_at": "2026-08-10T12:00:01Z"},
            ]
        ),
        official_filings=pd.DataFrame(
            [
                {"document_id": "f-old", "published_at": "2026-08-10T12:00:00Z"},
                {"document_id": "f-future", "published_at": "2026-08-10T12:00:01Z"},
            ]
        ),
        valuation_snapshots=pd.DataFrame(
            [
                {"valuation_at": "2026-08-10T12:00:00Z", "ratio_value": 10.0},
                {"valuation_at": "2026-08-10T12:00:01Z", "ratio_value": 11.0},
            ]
        ),
        thesis_claims=pd.DataFrame([old_claim, future_claim]),
        thesis_watch_questions=pd.DataFrame(
            [
                {"claim_id": "old-claim", "question": "old"},
                {"claim_id": "future-claim", "question": "future"},
            ]
        ),
        evidence_items=pd.DataFrame([old_evidence, future_evidence]),
        claim_evidence_links=pd.DataFrame(
            [
                {"claim_id": "old-claim", "evidence_id": "old-evidence"},
                {"claim_id": "future-claim", "evidence_id": "future-evidence"},
            ]
        ),
    )

    filtered = filter_snapshot_to_as_of(snapshot)
    assert set(filtered.events["event_id"]) == {"old-event"}
    assert set(filtered.event_entity_links["event_id"]) == {"old-event"}
    assert set(filtered.event_watch_questions["event_id"]) == {"old-event"}
    assert set(filtered.quote_snapshots["quote_id"]) == {"q-old"}
    assert set(filtered.price_bars["bar_id"]) == {"b-old"}
    assert set(filtered.consensus_snapshots["snapshot_id"]) == {"c-old"}
    assert set(filtered.official_filings["document_id"]) == {"f-old"}
    assert len(filtered.valuation_snapshots) == 1
    assert set(filtered.thesis_claims["claim_id"]) == {"old-claim"}
    assert set(filtered.thesis_watch_questions["claim_id"]) == {"old-claim"}
    assert set(filtered.evidence_items["evidence_id"]) == {"old-evidence"}
    assert set(filtered.claim_evidence_links["evidence_id"]) == {"old-evidence"}

    loaded = filter_loaded_frames_to_as_of(
        {"events.parquet": snapshot.events, "event_entity_links.parquet": snapshot.event_entity_links},
        snapshot.as_of_utc,
    )
    assert set(loaded["event_entity_links.parquet"]["event_id"]) == {"old-event"}


def test_ai_page_context_overrides_only_its_global_universe_dimensions() -> None:
    filters = EventFilters(
        horizon="30d",
        basket_id=("RESEARCH_STAGE_1_CHINA_INTERNET",),
        country=("CN",),
        scope=("basket",),
        membership_tier=("core",),
        importance=("high",),
        now_utc="2026-08-10T12:00:00Z",
    )
    context = page_filter_context("AI Bottlenecks", filters)

    assert context.scope_kind == "global_ai"
    assert context.scope_label == "Global AI Bottlenecks"
    assert context.effective_filters.basket_id == ("AI_BOTTLENECKS_GLOBAL",)
    assert context.effective_filters.country == ()
    assert context.effective_filters.scope == ()
    assert context.effective_filters.membership_tier == ()
    assert context.effective_filters.horizon == "30d"
    assert context.effective_filters.importance == ("high",)
    assert context.effective_filters.now_utc == filters.now_utc


def test_catalyst_state_for_row_preserves_explicit_status_precedence() -> None:
    row = {
        "starts_at": "2026-08-01T00:00:00Z",
        "ends_at": None,
        "status": "completed",
        "date_precision": "day",
        "source_timezone": "Asia/Hong_Kong",
    }
    assert catalyst_state_for_row(row, pd.Timestamp("2026-08-15T12:00:00Z")) == "completed"


def test_date_only_end_uses_next_local_midnight_across_dst() -> None:
    interval = resolve_catalyst_interval(
        "2026-03-08",
        "2026-03-08",
        date_precision="day",
        source_tz="America/New_York",
    )

    assert interval.valid is True
    assert interval.end_inclusive is False
    assert interval.start_utc == pd.Timestamp("2026-03-08T05:00:00Z")
    assert interval.end_utc == pd.Timestamp("2026-03-09T04:00:00Z")


def test_explicit_audit_filters_retain_terminal_rows() -> None:
    now = pd.Timestamp("2026-08-15T12:00:00Z")
    events = pd.DataFrame(
        [
            {
                "event_id": "expired",
                "event_type": "earnings",
                "status": "scheduled",
                "starts_at": "2026-08-01T00:00:00Z",
                "ends_at": "2026-08-02T00:00:00Z",
            },
            {
                "event_id": "completed",
                "event_type": "earnings",
                "status": "completed",
                "starts_at": "2026-08-10T00:00:00Z",
                "ends_at": None,
            },
            {
                "event_id": "cancelled",
                "event_type": "earnings",
                "status": "cancelled",
                "starts_at": "2026-08-20T00:00:00Z",
                "ends_at": None,
            },
            {
                "event_id": "future",
                "event_type": "earnings",
                "status": "scheduled",
                "starts_at": "2026-08-20T00:00:00Z",
                "ends_at": None,
            },
        ]
    )

    audit = apply_event_filters(
        events,
        EventFilters(
            horizon="all",
            now_utc=now,
            catalyst_eligible=False,
        ),
    )

    assert set(audit["event_id"]) == {"expired", "completed", "cancelled"}


def test_alternative_data_observation_dates_obey_frozen_snapshot_boundary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Generation-external alternative marts must not expose future observation dates."""
    profile = get_company_profile("TENCENT")
    raw = pd.DataFrame(
        [
            {
                "usage_date": "2026-08-10",
                "model_permaslug": "tencent/hunyuan-a13b",
                "total_tokens": 100.0,
                "estimated_revenue": 1.0,
            },
            {
                "usage_date": "2026-08-11",
                "model_permaslug": "tencent/hunyuan-a13b",
                "total_tokens": 900.0,
                "estimated_revenue": 9.0,
            },
        ]
    )
    daily = _openrouter_daily_frame(
        raw,
        profile,
        as_of_utc="2026-08-10T12:00:00Z",
    )
    assert daily["usage_date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-08-10"]
    assert daily["total_tokens"].tolist() == [100.0]

    mart_dir = tmp_path / "data" / "normalized" / "marts"
    mart_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {"hold_date": "2026-08-10", "holding_shares": 100},
            {"hold_date": "2026-08-11", "holding_shares": 900},
        ]
    ).to_parquet(mart_dir / "0700_hk_southbound_holdings.parquet", index=False)
    monkeypatch.setattr(
        "control_tower.pages.company._control_tower_repo_root",
        lambda: tmp_path,
    )
    holdings = _load_southbound_holdings(
        {
            "listing_id": "0700_HK",
            "mart_filename": "tencent_southbound_holdings.parquet",
            "security_code": "00700",
            "canonical_ticker": "0700.HK",
        },
        as_of_utc="2026-08-10T12:00:00Z",
    )
    assert holdings["hold_date"].dt.strftime("%Y-%m-%d").tolist() == ["2026-08-10"]
    assert holdings["holding_shares"].tolist() == [100]
