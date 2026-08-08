from __future__ import annotations

import pandas as pd
import pytest

from src.hk_transport.sources.airline_forward_earnings_bridge import (
    MAINLAND_COMPANIES,
    build_airline_forward_earnings_bridge,
    build_airline_forward_invalidation_rules,
    build_airline_pair_scorecard,
)


def test_forward_bridge_covers_six_companies_and_three_scenarios() -> None:
    frame = build_airline_forward_earnings_bridge()
    assert len(frame) == 18
    assert set(frame.company) == {company for company, _ in MAINLAND_COMPANIES}
    assert set(frame.scenario) == {"bear", "base", "bull"}
    assert frame["forecast_status"].eq("research_model_not_issuer_guidance").all()
    assert frame["source_paths"].notna().all()
    spring = frame[(frame.company == "Spring Airlines") & frame.scenario.eq("base")].iloc[0]
    assert spring["forecast_revenue_usd_mn"] == pytest.approx(3450.095979, abs=1e-3)
    assert spring["consensus_fy2026_revenue_usd_mn"] > 0
    juneyao = frame[(frame.company == "Juneyao Airlines") & frame.scenario.eq("base")].iloc[0]
    assert juneyao["nine_air_scope_status"] == "group_consolidated_including_9air_component_mix_only"
    assert juneyao["nine_air_passenger_share_pct"] == pytest.approx(26.904, abs=0.02)
    assert bool(juneyao["nine_air_scope_adjustment_applied"]) is False
    assert juneyao["nine_air_scope_adjustment_type"] == "passenger_fleet_mix_context_only_no_financial_allocation"
    assert "not allocated" in juneyao["nine_air_scope_note"]


def test_forward_bridge_keeps_fuel_overlay_separate_and_flags_unstable_profit() -> None:
    frame = build_airline_forward_earnings_bridge()
    assert frame["fuel_overlay_included_in_core_earnings"].eq(False).all()
    air_china = frame[(frame.company == "Air China") & frame.scenario.eq("base")].iloc[0]
    eastern = frame[(frame.company == "China Eastern Airlines") & frame.scenario.eq("base")].iloc[0]
    assert air_china["profit_proxy_method"] == "consensus_margin_fallback_negative_FY2025_profit"
    assert eastern["profit_proxy_method"] == "consensus_margin_fallback_negative_FY2025_profit"
    assert pd.isna(frame[frame.scenario.eq("base")]["fuel_overlay_pre_tax_usd_mn"]).sum() == 0
    assert frame[frame.scenario.eq("bear")]["fuel_overlay_pre_tax_usd_mn"].notna().all()


def test_pair_scorecard_has_twenty_one_pairs_and_one_core_three_backups() -> None:
    bridge = build_airline_forward_earnings_bridge()
    frame = build_airline_pair_scorecard(bridge=bridge)
    assert len(frame) == 21
    assert frame.pair_id.is_unique
    assert frame.selection_bucket.eq("core_candidate").sum() == 1
    assert frame.selection_bucket.eq("backup_candidate").sum() == 3
    assert frame.selection_score.between(0, 100).all()
    assert frame[["hsr_coverage_status_a", "hsr_coverage_status_b", "nine_air_scope_status_a", "nine_air_scope_status_b"]].notna().all().all()


def test_invalidation_rules_cover_all_six_companies_and_four_risk_channels() -> None:
    bridge = build_airline_forward_earnings_bridge()
    frame = build_airline_forward_invalidation_rules(bridge=bridge)
    assert len(frame) == 24
    assert set(frame.company) == {company for company, _ in MAINLAND_COMPANIES}
    assert set(frame.risk_category) == {"demand_capacity", "pricing", "fuel_cost", "profit_scope"}
    assert frame.invalidation_trigger.notna().all()
    juneyao = frame[frame.company.eq("Juneyao Airlines") & frame.risk_category.eq("profit_scope")].iloc[0]
    assert "9 Air passenger share" in juneyao.current_evidence
