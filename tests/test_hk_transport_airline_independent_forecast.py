from __future__ import annotations

from src.hk_transport.sources.airline_independent_forecast import build_airline_independent_forecast_view


def test_pre_event_view_is_explicit_and_not_copied_from_consensus() -> None:
    frame = build_airline_independent_forecast_view()
    assert len(frame) == 6
    base = frame.loc[frame.scenario.eq("base")].set_index("company")
    assert base.loc["Spring Airlines", "view_direction"] == "long_candidate"
    assert base.loc["Juneyao Airlines", "view_direction"] == "short_candidate"
    assert base.loc["Spring Airlines", "profit_gap_vs_consensus_pct"] > 0
    assert base.loc["Juneyao Airlines", "profit_gap_vs_consensus_pct"] < 0
    assert base["forecast_status"].eq("analyst_pre_event_base_view").all()
    assert base["forecast_method"].str.contains("explicit_growth").all()
    assert base["ask_growth_assumption_pct"].notna().all()
    assert base["independent_fuel_cost_native_mn"].notna().all()
    assert base["independent_nonfuel_cost_native_mn"].notna().all()
    assert base["sector_apac_rpk_forecast_pct"].eq(7.3).all()
    assert base["sector_cn_h1_rpk_growth_pct"].notna().all()
