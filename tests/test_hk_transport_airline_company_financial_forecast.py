from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_company_financial_forecast import (
    build_airline_company_financial_forecast_bridge,
)


def test_company_financial_bridge_covers_six_mainland_carriers_and_pending_9air() -> None:
    frame = build_airline_company_financial_forecast_bridge()
    assert len(frame) == 21
    expected_companies = {
        "Spring Airlines",
        "Juneyao Airlines",
        "China Southern Airlines",
        "China Eastern Airlines",
        "Air China",
        "Hainan Airlines Holdings",
        "9 Air",
    }
    assert set(frame["company"]) == expected_companies
    assert frame.groupby("company").size().eq(3).all()
    assert set(frame["scenario"]) == {"bear", "base", "bull"}
    assert frame.loc[frame.company.eq("9 Air"), "forecast_status"].eq("pending_standalone_financial_disclosure").all()

    for company in expected_companies - {"9 Air"}:
        assert frame.loc[frame.company.eq(company), "forecast_status"].eq("mechanical_driver_bridge_not_issuer_forecast").all()


def test_company_financial_bridge_reconciles_driver_math_and_units() -> None:
    frame = build_airline_company_financial_forecast_bridge()
    modelled_carriers = [
        "Spring Airlines",
        "Juneyao Airlines",
        "China Southern Airlines",
        "China Eastern Airlines",
        "Air China",
        "Hainan Airlines Holdings",
    ]
    for company in modelled_carriers:
        row = frame[(frame.company == company) & (frame.scenario == "base")].iloc[0]
        assert row["forecast_ask_mn_seat_km"] == pytest.approx(
            row["fy2025_ask_mn_seat_km"] * (1 + row["ask_growth_assumption_pct"] / 100), rel=1e-6
        )
        assert row["forecast_rpk_mn_passenger_km"] == pytest.approx(
            row["fy2025_rpk_mn_passenger_km"] * (1 + row["rpk_growth_assumption_pct"] / 100), rel=1e-6
        )
        assert row["forecast_revenue_native_mn"] == pytest.approx(
            row["forecast_passenger_revenue_native_mn"]
            + row["forecast_nonpassenger_revenue_native_mn"], rel=1e-6
        )
        assert row["forecast_total_revenue_per_ask_rmb_per_ask"] == pytest.approx(
            row["forecast_revenue_native_mn"] / row["forecast_ask_mn_seat_km"], rel=1e-6
        )
        assert row["forecast_operating_cost_native_mn"] == pytest.approx(
            row["forecast_ask_mn_seat_km"] * row["forecast_cask_rmb_per_ask"], rel=1e-6
        )
        assert row["forecast_revenue_usd_mn"] > 0
        assert row["actual_fx_native_per_usd"] == pytest.approx(7.0, abs=0.05)


def test_company_financial_bridge_handles_unprofitable_carriers_without_inversion() -> None:
    frame = build_airline_company_financial_forecast_bridge()
    for company in ["Air China", "China Eastern Airlines"]:
        base = frame[(frame.company == company) & (frame.scenario == "base")].iloc[0]
        assert base["profit_proxy_method"] in (
            "consensus_margin_fallback_unprofitable_FY2025",
            "actual_margin_carry_unprofitable_FY2025",
        )
        assert base["net_to_operating_profit_conversion"] >= 0
        assert not bool(base["fuel_overlay_applied_to_net_profit"])


def test_company_financial_bridge_prefers_a_share_consensus_for_mainland_names() -> None:
    frame = build_airline_company_financial_forecast_bridge()
    mainland = frame[frame.company != "9 Air"]
    assert mainland["selected_consensus_market"].eq("CN_A").all()


def test_company_financial_bridge_keeps_nonpassenger_revenue_visible() -> None:
    frame = build_airline_company_financial_forecast_bridge()
    for company in ["China Southern Airlines", "China Eastern Airlines", "Air China", "Hainan Airlines Holdings"]:
        base = frame[(frame.company == company) & (frame.scenario == "base")].iloc[0]
        assert base["fy2025_nonpassenger_revenue_native_mn"] > 0
        assert base["forecast_nonpassenger_revenue_native_mn"] > 0


def test_company_financial_bridge_exposes_market_implied_revenue_diagnostic() -> None:
    frame = build_airline_company_financial_forecast_bridge()
    modelled = frame[frame.company != "9 Air"]
    assert modelled["market_cap_usd_mn"].notna().all()
    assert modelled["historical_ps_median"].notna().all()
    assert modelled["market_implied_revenue_usd_mn_at_historical_ps_median"].notna().all()
    assert modelled["historical_ps_status"].isin(
        ["same_market_historical_ps_band", "same_company_cross_market_historical_ps_band"]
    ).all()


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
    assert frame["as_of_date"].str.len().eq(10).all()
    assert frame["retrieved_at"].eq("2099-01-01T00:00:00+00:00").all()
