from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_forecast_risk_framework import (
    build_airline_forecast_assumptions,
    build_airline_risk_invalidation_matrix,
)


def test_forecast_assumptions_preserve_observed_anchors_and_scenarios() -> None:
    assumptions = build_airline_forecast_assumptions()
    assert not assumptions.empty
    assert set(assumptions["scenario"]) == {"bear", "base", "bull"}
    spring = assumptions[
        (assumptions["entity"] == "Spring Airlines")
        & (assumptions["driver"] == "rpk_growth_pct")
    ]
    assert len(spring) == 3
    assert spring["observed_anchor_value"].map(lambda value: value == pytest.approx(18.009928, abs=1e-6)).all()
    assert spring.loc[spring.scenario.eq("bear"), "assumption_value"].iloc[0] < spring.loc[spring.scenario.eq("base"), "assumption_value"].iloc[0]
    assert spring.loc[spring.scenario.eq("bull"), "assumption_value"].iloc[0] > spring.loc[spring.scenario.eq("base"), "assumption_value"].iloc[0]
    assert spring["assumption_status"].eq("analyst_stress_around_observed_anchor").all()


def test_forecast_assumptions_keep_9air_pending_where_no_operator_anchor() -> None:
    assumptions = build_airline_forecast_assumptions()
    nine = assumptions[
        (assumptions["entity"] == "9 Air")
        & (assumptions["driver"] == "rpk_growth_pct")
    ]
    assert len(nine) == 3
    assert nine["assumption_value"].isna().all()
    assert nine["assumption_status"].eq("pending_operator_level_forecast").all()


def test_risk_matrix_has_triggers_and_scope_risks() -> None:
    risks = build_airline_risk_invalidation_matrix()
    assert len(risks) >= 10
    assert risks["invalidation_trigger"].notna().all()
    assert risks["earnings_impact_channel"].notna().all()
    assert "warning_recovery" in set(risks.loc[risks.entity.eq("Juneyao Airlines"), "risk_category"])
    assert "disclosure" in set(risks.loc[risks.entity.eq("9 Air"), "risk_category"])
    assert risks["is_modelled_analysis"].eq(True).all()


def test_assumptions_use_injected_trend_input() -> None:
    trend = pd.DataFrame([
        {
            "scope_type": "company", "company": "Spring Airlines", "region": "Total",
            "metric": "rpk", "current_period": "2026H1", "yoy_change_pct": 1.0,
            "snapshot_date": "2026-08-07", "source_quality": "test",
        },
        {
            "scope_type": "company", "company": "Spring Airlines", "region": "Total",
            "metric": "ask", "current_period": "2026H1", "yoy_change_pct": 2.0,
            "snapshot_date": "2026-08-07", "source_quality": "test",
        },
        {
            "scope_type": "company", "company": "Spring Airlines", "region": "Total",
            "metric": "passenger_load_factor_pct", "current_period": "2026H1", "yoy_change_pct": 0.5,
            "snapshot_date": "2026-08-07", "source_quality": "test",
        },
    ])
    assumptions = build_airline_forecast_assumptions(trend=trend)
    spring = assumptions[
        (assumptions.entity == "Spring Airlines") & (assumptions.driver == "rpk_growth_pct")
    ]
    assert spring["observed_anchor_value"].eq(1.0).all()


def test_unit_economic_assumptions_are_explicit_and_9air_pending() -> None:
    assumptions = build_airline_forecast_assumptions()
    for driver in ("rask_growth_pct_vs_fy2025", "cask_growth_pct_vs_fy2025"):
        spring = assumptions[(assumptions.entity == "Spring Airlines") & (assumptions.driver == driver)]
        assert len(spring) == 3
        assert spring["observed_anchor_value"].notna().all()
        assert spring["assumption_status"].eq("analyst_stress_around_fy2025_unit_economics").all()
        nine = assumptions[(assumptions.entity == "9 Air") & (assumptions.driver == driver)]
        assert len(nine) == 3
        assert nine["assumption_value"].isna().all()
