from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_company_financial_forecast import (
    build_airline_company_financial_forecast_bridge,
)


def test_company_financial_bridge_has_two_modelled_groups_and_pending_9air() -> None:
    frame = build_airline_company_financial_forecast_bridge()
    assert len(frame) == 9
    assert set(frame["company"]) == {"Spring Airlines", "Juneyao Airlines", "9 Air"}
    assert frame.groupby("company").size().eq(3).all()
    assert set(frame["scenario"]) == {"bear", "base", "bull"}
    assert frame.loc[frame.company.eq("9 Air"), "forecast_status"].eq("pending_standalone_financial_disclosure").all()
    assert frame.loc[frame.company.eq("Spring Airlines"), "forecast_status"].eq("mechanical_driver_bridge_not_issuer_forecast").all()


def test_company_financial_bridge_reconciles_driver_math_and_units() -> None:
    frame = build_airline_company_financial_forecast_bridge()
    spring = frame[(frame.company == "Spring Airlines") & (frame.scenario == "base")].iloc[0]
    assert spring["forecast_ask_mn_seat_km"] == pytest.approx(
        spring["fy2025_ask_mn_seat_km"] * (1 + spring["ask_growth_assumption_pct"] / 100), rel=1e-9
    )
    assert spring["forecast_rpk_mn_passenger_km"] == pytest.approx(
        spring["fy2025_rpk_mn_passenger_km"] * (1 + spring["rpk_growth_assumption_pct"] / 100), rel=1e-9
    )
    assert spring["forecast_revenue_native_mn"] == pytest.approx(
        spring["forecast_ask_mn_seat_km"] * spring["forecast_rask_proxy_rmb_per_ask"], rel=1e-9
    )
    assert spring["forecast_operating_cost_native_mn"] == pytest.approx(
        spring["forecast_ask_mn_seat_km"] * spring["forecast_cask_rmb_per_ask"], rel=1e-9
    )
    assert spring["forecast_revenue_usd_mn"] > 0
    assert spring["actual_fx_native_per_usd"] == pytest.approx(7.0, abs=0.02)
    assert spring["forecast_status"] == "mechanical_driver_bridge_not_issuer_forecast"


def test_company_financial_bridge_keeps_juneyao_scope_and_consensus_gap() -> None:
    frame = build_airline_company_financial_forecast_bridge()
    juneyao = frame[(frame.company == "Juneyao Airlines") & (frame.scenario == "base")].iloc[0]
    assert "consolidated" in juneyao["entity_scope"]
    assert "9 Air" in juneyao["model_scope_note"]
    assert pd.notna(juneyao["consensus_profit_freshness"])
    assert pd.notna(juneyao["earnings_gap_to_consensus_pct"])


def test_company_financial_bridge_as_of_is_source_date_not_retrieval_date() -> None:
    frame = build_airline_company_financial_forecast_bridge(
        retrieved_at="2099-01-01T00:00:00+00:00"
    )
    assert frame["as_of_date"].eq("2026-08-07").all()
    assert frame["retrieved_at"].eq("2099-01-01T00:00:00+00:00").all()
