"""Tests for the unified pre-event reconciliation snapshot."""

from __future__ import annotations

import pandas as pd

from hk_transport.sources.airline_pre_event_unified_snapshot import (
    OUTPUT_PATH,
    build_airline_pre_event_unified_snapshot,
)


def test_unified_snapshot_covers_six_carriers_and_keeps_layers_explicit() -> None:
    frame = build_airline_pre_event_unified_snapshot()

    assert len(frame) == 6
    assert frame.company.nunique() == 6
    assert frame.lock_status.eq("locked_composite_read_only").all()
    assert frame.forecast_type.eq("pre_event_reconciliation").all()
    assert frame.v3_model_version.eq("v3_base_financial_bridge").all()
    assert frame.v4_model_version.notna().all()
    assert frame.decision_model_version.eq("walk_forward_integrated_mc_v1").all()
    assert frame.source_vintage_status.eq("source_vintages_aligned").all()


def test_unified_snapshot_preserves_spring_v4_and_consensus_fields() -> None:
    frame = build_airline_pre_event_unified_snapshot()
    spring = frame.loc[frame.company.eq("Spring Airlines")].iloc[0]

    assert spring.v4_h1_revenue_native_mn > 0
    assert spring.v4_h1_eps_rmb > 0
    assert spring.v4_consensus_eps_fy2026_rmb > 0
    assert spring.v4_surprise_x2_pct > 0
    assert spring.v4_surprise_season_adjusted_pct > spring.v4_surprise_x2_pct
    assert spring.consensus_freshness == "fresh"
    assert bool(spring.one_off_flagged) is True


def test_unified_snapshot_is_written() -> None:
    frame = build_airline_pre_event_unified_snapshot()
    on_disk = pd.read_csv(OUTPUT_PATH)
    assert len(on_disk) == len(frame)
    assert set(on_disk.columns) == set(frame.columns)
