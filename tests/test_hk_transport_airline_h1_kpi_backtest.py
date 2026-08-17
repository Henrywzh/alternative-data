from __future__ import annotations

import pytest

from src.hk_transport.sources.airline_h1_kpi_backtest import build_airline_h1_kpi_backtest


def test_h1_backtest_has_historical_rows_and_current_nowcast() -> None:
    observations, summary = build_airline_h1_kpi_backtest(retrieved_at="2026-08-09T00:00:00+00:00")
    assert len(summary) == 6
    assert observations["row_status"].eq("current_1h2026_nowcast").sum() == 6
    assert observations["row_status"].eq("historical_evaluated").sum() > 30


def test_current_kpi_inputs_are_available_before_the_august_cutoff() -> None:
    observations, _ = build_airline_h1_kpi_backtest(retrieved_at="2026-08-09T00:00:00+00:00")
    current = observations.loc[observations["row_status"].eq("current_1h2026_nowcast")]
    assert current["kpi_pre_report_cutoff_pass"].all()
    assert current["target_actual_pit_status"].eq("pending_formal_interim_report").all()
    assert current["target_h1_revenue_native_mn"].isna().all()


def test_spring_current_ask_revenue_bridge_is_reproducible() -> None:
    observations, _ = build_airline_h1_kpi_backtest(retrieved_at="2026-08-09T00:00:00+00:00")
    spring = observations.loc[
        observations["company"].eq("Spring Airlines")
        & observations["row_status"].eq("current_1h2026_nowcast")
    ].iloc[0]
    expected = spring["prior_h1_revenue_native_mn"] * (1.0 + spring["ask_growth_pct"] / 100.0)
    assert spring["flat_ask_revenue_pred_native_mn"] == pytest.approx(expected, rel=1e-10)
    assert spring["analyst_h1_revenue_pred_native_mn"] > spring["flat_ask_revenue_pred_native_mn"]


def test_2025_target_uses_primary_report_override_when_available() -> None:
    observations, _ = build_airline_h1_kpi_backtest(retrieved_at="2026-08-09T00:00:00+00:00")
    spring = observations.loc[
        observations["company"].eq("Spring Airlines")
        & observations["target_year"].eq(2025)
        & observations["row_status"].eq("historical_evaluated")
    ].iloc[0]
    assert spring["target_actual_source_quality"] == "primary_issuer"
    assert spring["target_actual_pit_status"] == "issuer_announcement_date_available"

