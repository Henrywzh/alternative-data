from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_juneyao_9air_scope import (
    build_airline_juneyao_9air_scope_reconciliation,
)


def test_scope_reconciliation_reconciles_fy2025_passengers_and_fleet() -> None:
    frame = build_airline_juneyao_9air_scope_reconciliation()
    passengers = frame[(frame.statement_period == "FY2025") & frame.canonical_metric.eq("passengers")].iloc[0]
    fleet = frame[(frame.statement_period == "FY2025") & frame.canonical_metric.eq("fleet_total")].iloc[0]
    assert passengers["group_value_native"] == pytest.approx(27.1945, abs=1e-6)
    assert passengers["nine_air_value_native"] == pytest.approx(7.3163, abs=1e-6)
    assert passengers["mainline_value_native"] == pytest.approx(19.8782, abs=1e-6)
    assert passengers["residual_native"] == pytest.approx(0.0, abs=1e-8)
    assert passengers["nine_air_share_pct"] == pytest.approx(26.904, abs=0.02)
    assert fleet["group_value_native"] == pytest.approx(129.0)
    assert fleet["mainline_value_native"] == pytest.approx(103.0)
    assert fleet["nine_air_value_native"] == pytest.approx(26.0)
    assert fleet["residual_native"] == pytest.approx(0.0)
    assert fleet["reconciliation_status"] == "fleet_reconciles_exactly"


def test_scope_reconciliation_does_not_allocate_group_financials_or_capacity() -> None:
    frame = build_airline_juneyao_9air_scope_reconciliation()
    for metric in ("total_revenue", "operating_cost", "fuel_cost", "attributable_net_income", "ask", "rpk"):
        row = frame[(frame.statement_period == "FY2025") & frame.canonical_metric.eq(metric)].iloc[0]
        assert pd.isna(row["mainline_value_native"])
        assert pd.isna(row["nine_air_value_native"])
        assert row["reconciliation_status"] == "group_only_standalone_component_missing"
        assert row["model_use"] == "use_group_only_do_not_allocate_to_mainline_or_9air"


def test_scope_reconciliation_preserves_interim_group_only_status_and_pit() -> None:
    frame = build_airline_juneyao_9air_scope_reconciliation(
        retrieved_at="2099-01-01T00:00:00+00:00"
    )
    interim = frame[frame.statement_period.eq("1H2025")]
    assert not interim.empty
    assert interim["nine_air_value_native"].isna().all()
    assert interim["snapshot_as_of_date"].eq("2026-08-07").all()
    assert interim["retrieved_at"].eq("2099-01-01T00:00:00+00:00").all()
