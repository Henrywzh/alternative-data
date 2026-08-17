from __future__ import annotations

import pytest

from src.hk_transport.sources.airline_forecast_reconciliation import (
    build_airline_forecast_reconciliation,
)


def test_reconciliation_has_two_core_pair_rows() -> None:
    frame = build_airline_forecast_reconciliation()
    assert len(frame) == 2
    assert set(frame["company"]) == {"Spring Airlines", "Juneyao Airlines"}
    assert frame["scenario"].eq("base").all()


def test_reconciliation_recomputes_cost_and_profit_deltas() -> None:
    frame = build_airline_forecast_reconciliation()
    for _, row in frame.iterrows():
        assert row["revenue_delta_bridge_minus_independent_usd_mn"] == pytest.approx(
            row["bridge_revenue_usd_mn"] - row["independent_revenue_usd_mn"], rel=1e-9
        )
        assert row["operating_cost_delta_bridge_minus_independent_usd_mn"] == pytest.approx(
            row["bridge_operating_cost_usd_mn"] - row["independent_operating_cost_usd_mn"], rel=1e-9
        )
        assert row["profit_delta_bridge_minus_independent_usd_mn"] == pytest.approx(
            row["bridge_earnings_proxy_usd_mn"] - row["independent_profit_usd_mn"], rel=1e-9
        )


def test_reconciliation_identifies_cost_assumption_difference() -> None:
    frame = build_airline_forecast_reconciliation()
    assert frame["primary_difference_driver"].eq("cost_assumption_difference").all()
    juneyao = frame[frame["company"].eq("Juneyao Airlines")].iloc[0]
    assert "9 Air" in juneyao["scope_note"]


def test_reconciliation_does_not_create_direction() -> None:
    frame = build_airline_forecast_reconciliation()
    assert "direction" not in frame.columns
    assert "long" not in " ".join(frame["interpretation"].astype(str)).lower()
