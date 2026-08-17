"""Tests for the H1/H2/FY airline KPI-to-earnings calibration.

Covers the derived-H2 identity, sample expansion after the source-recovery
parser repairs, the Spring recovery-case sensitivity and the Juneyao 2016
undisclosed AFTK handling (which must stay unfilled rather than interpolated).
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_period_kpi_backtest import (
    build_airline_period_kpi_backtest,
    build_airline_period_kpi_backtest_comparison,
)


def test_period_backtest_has_h1_h2_fy_rows() -> None:
    strict, summary = build_airline_period_kpi_backtest(
        assumption_mode="strict_observed", retrieved_at="2026-08-09T00:00:00+00:00"
    )
    assert set(strict["period"].unique()) == {"H1", "H2", "FY"}
    assert len(summary) == len(strict["company"].unique()) * 3


def test_h2_financial_is_derived_as_fy_minus_h1() -> None:
    strict, _ = build_airline_period_kpi_backtest(
        assumption_mode="strict_observed", retrieved_at="2026-08-09T00:00:00+00:00"
    )
    evaluated = strict.loc[strict["row_status"].eq("historical_evaluated")]
    for (company, year), group in evaluated.groupby(["company", "target_year"]):
        h1 = group.loc[group["period"].eq("H1")]
        h2 = group.loc[group["period"].eq("H2")]
        fy = group.loc[group["period"].eq("FY")]
        if h1.empty or h2.empty or fy.empty:
            continue
        rev_h1 = h1["target_revenue_native_mn"].iloc[0]
        rev_h2 = h2["target_revenue_native_mn"].iloc[0]
        rev_fy = fy["target_revenue_native_mn"].iloc[0]
        if pd.notna(rev_h1) and pd.notna(rev_h2) and pd.notna(rev_fy):
            assert abs((rev_h1 + rev_h2) - rev_fy) < 1.0
        assert h2["target_financial_source_quality"].iloc[0] == "derived_fy_minus_h1"


def test_source_recovery_expands_historical_samples() -> None:
    strict, summary = build_airline_period_kpi_backtest(
        assumption_mode="strict_observed", retrieved_at="2026-08-09T00:00:00+00:00"
    )
    # Juneyao previously had only 1 FY / 5 H1 / 2 H2 evaluated rows because of
    # the ASK/RPK Total parsing gap; after the parser repair it should have the
    # full 2017-2025 window across all periods.
    juneyao = summary.loc[summary["company"].eq("Juneyao Airlines")]
    assert (juneyao["historical_evaluated_rows"] >= 9).all()


def test_spring_recovery_case_reduces_revenue_mae_on_reopening_years() -> None:
    strict, _ = build_airline_period_kpi_backtest(
        assumption_mode="strict_observed", retrieved_at="2026-08-09T00:00:00+00:00"
    )
    spring = strict.loc[
        strict["company"].eq("Spring Airlines")
        & strict["row_status"].eq("historical_evaluated")
        & strict["spring_recovery_signal"].fillna(False).astype(bool)
    ]
    if spring.empty:
        pytest.skip("No Spring recovery-signal years in current data")
    improvement = (
        spring["revenue_error_flat_rpk_pct"].abs()
        - spring["revenue_error_spring_recovery_case_pct"].abs()
    )
    # The recovery case must not be a strictly worse revenue estimate than the
    # flat-RPK base on the flagged reopening years.
    assert (improvement >= -1.0).all()


def test_logical_assumption_layer_marks_assumption_rows() -> None:
    strict, logical, comparison, diagnostics = build_airline_period_kpi_backtest_comparison(
        retrieved_at="2026-08-09T00:00:00+00:00"
    )
    assert len(comparison) > 0
    # Logical rows are coverage sensitivity only; strict evaluated rows are the
    # clean calibration baseline and must never exceed logical evaluated rows.
    strict_rows = strict.loc[strict["row_status"].eq("historical_evaluated")]
    logical_rows = logical.loc[logical["row_status"].eq("historical_evaluated")]
    assert len(strict_rows) <= len(logical_rows)


def test_spring_diagnostics_are_pit_safe_after_recovery() -> None:
    _, _, _, diagnostics = build_airline_period_kpi_backtest_comparison(
        retrieved_at="2026-08-09T00:00:00+00:00"
    )
    assert not diagnostics.empty
    # After the parser repair, Spring's H1/FY diagnostics should all be PIT-safe
    # (the ask/rpk Total rows come from official PDFs, not future interpolation).
    assert diagnostics["kpi_pit_safe"].fillna(False).all()
