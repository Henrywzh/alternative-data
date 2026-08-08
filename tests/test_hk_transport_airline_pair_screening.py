from __future__ import annotations

import pandas as pd


def test_pair_screening_matrix_covers_all_unordered_pairs_without_direction() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_screening_matrix.csv")
    assert len(frame) == 21
    assert frame.duplicated("pair_id").sum() == 0
    assert frame["data_comparability_status"].notna().all()
    assert frame["expectation_comparability_status"].notna().all()
    assert frame["screen_status"].notna().all()
    assert "long" not in " ".join(frame["screen_status"].astype(str)).lower()
    assert "short" not in " ".join(frame["screen_status"].astype(str)).lower()


def test_pair_screening_matrix_preserves_same_market_and_cross_market_groups() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_screening_matrix.csv")
    assert frame["same_market"].any()
    assert (~frame["same_market"]).any()
    assert frame["source_quality"].eq("derived_screening_matrix").all()
    assert frame["borrow_data_available_a"].eq(False).all()
    assert frame["borrow_data_available_b"].eq(False).all()
    assert frame[["debt_to_assets_a_pct", "debt_to_assets_b_pct"]].notna().any(axis=1).all()
    mainland_pairs = frame.loc[
        frame["debt_to_assets_a_pct"].notna() & frame["debt_to_assets_b_pct"].notna()
    ]
    assert not mainland_pairs.empty
    assert (
        mainland_pairs["debt_to_assets_gap_a_minus_b_pct"]
        - (mainland_pairs["debt_to_assets_a_pct"] - mainland_pairs["debt_to_assets_b_pct"])
    ).abs().lt(1e-6).all()
    primary_pairs = frame.loc[
        frame["primary_liabilities_to_assets_a_pct"].notna()
        & frame["primary_liabilities_to_assets_b_pct"].notna()
    ]
    assert not primary_pairs.empty
    assert primary_pairs[["primary_liabilities_to_assets_a_pct", "primary_liabilities_to_assets_b_pct"]].apply(
        lambda col: col.between(0, 100).all()
    ).all()
    assert (
        primary_pairs["primary_liabilities_to_assets_gap_a_minus_b_pct"]
        - (
            primary_pairs["primary_liabilities_to_assets_a_pct"]
            - primary_pairs["primary_liabilities_to_assets_b_pct"]
        )
    ).abs().lt(1e-6).all()
    assert frame[[
        "unified_estimate_revision_count_a", "unified_estimate_revision_count_b",
        "unified_up_revision_count_a", "unified_up_revision_count_b",
        "unified_down_revision_count_a", "unified_down_revision_count_b",
    ]].notna().all().all()
    assert (
        frame["unified_revision_balance_a"]
        == frame["unified_up_revision_count_a"] - frame["unified_down_revision_count_a"]
    ).all()
    assert frame[[
        "market_cap_to_consensus_revenue_a_usd", "market_cap_to_consensus_revenue_b_usd",
        "valuation_revenue_gap_a_minus_b", "consensus_net_margin_a_pct",
        "consensus_net_margin_b_pct", "consensus_net_margin_gap_a_minus_b_pct",
    ]].notna().all().all()
    assert (
        frame["valuation_revenue_gap_a_minus_b"]
        - frame["market_cap_to_consensus_revenue_a_usd"]
        + frame["market_cap_to_consensus_revenue_b_usd"]
    ).abs().lt(1e-9).all()


def test_pair_screening_matrix_exposes_per_leg_public_expectation_dispersion() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_screening_matrix.csv")
    public_cols = [
        "public_eps_count_a", "public_eps_count_b",
        "public_net_profit_count_a", "public_net_profit_count_b",
        "public_revenue_count_a", "public_revenue_count_b",
    ]
    assert frame[public_cols].notna().all().all()
    assert frame[public_cols].ge(0).all().all()
    mainland = frame.loc[
        frame["company_a"].ne("Cathay Pacific") & frame["company_b"].ne("Cathay Pacific")
    ]
    assert not mainland.empty
    assert mainland[[
        "public_eps_median_a_rmb_per_share", "public_eps_median_b_rmb_per_share",
        "public_net_profit_median_a_rmb_100m", "public_net_profit_median_b_rmb_100m",
        "public_revenue_median_a_rmb_100m", "public_revenue_median_b_rmb_100m",
    ]].notna().all().all()
    assert mainland[[
        "public_eps_range_width_pct_a", "public_eps_range_width_pct_b",
        "public_net_profit_range_width_pct_a", "public_net_profit_range_width_pct_b",
        "public_revenue_range_width_pct_a", "public_revenue_range_width_pct_b",
    ]].notna().all().all()
    assert mainland[["public_report_latest_date_a", "public_report_latest_date_b"]].notna().all().all()
    cathay = frame.loc[frame["company_a"].eq("Cathay Pacific") | frame["company_b"].eq("Cathay Pacific")]
    assert cathay[["public_eps_count_a", "public_eps_count_b"]].eq(0).any(axis=1).all()


def test_pair_screening_matrix_exposes_exchange_eligibility_without_borrow_claim() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_screening_matrix.csv")
    eligibility = frame[["short_eligibility_status_a", "short_eligibility_status_b"]]
    assert eligibility.notna().all().all()
    assert eligibility.astype(str).apply(lambda col: col.str.contains("eligible|observed").all()).all()
    assert frame[[
        "short_eligibility_effective_date_a", "short_eligibility_effective_date_b",
        "short_eligibility_source_quality_a", "short_eligibility_source_quality_b",
    ]].notna().all().all()


def test_pair_screening_matrix_exposes_hk_sfc_short_position_context() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_screening_matrix.csv")
    hk_legs = frame.loc[frame["market_a"].eq("HK")]
    assert not hk_legs.empty
    assert hk_legs[[
        "sfc_short_position_shares_a", "sfc_short_position_value_hkd_a",
        "sfc_short_position_reporting_date_a", "sfc_short_position_history_count_a",
    ]].notna().all().all()
    assert hk_legs["sfc_short_position_history_count_a"].ge(1).all()
    assert frame.loc[frame["market_b"].eq("CN_A"), "sfc_short_position_value_hkd_b"].isna().all()


def test_pair_screening_matrix_exposes_demand_gap_and_implied_h2_diagnostics() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_screening_matrix.csv")
    southern_eastern = frame.loc[
        frame["pair_id"].eq("01055.HK__0670.HK")
    ].iloc[0]
    assert southern_eastern["rpk_minus_ask_growth_gap_pp_a"] < 0
    assert southern_eastern["rpk_minus_ask_growth_gap_pp_b"] > 0
    assert southern_eastern["implied_h2_profit_mid_native_mn_a"] == 4430.0
    assert southern_eastern["implied_h2_profit_mid_native_mn_b"] == 2534.0
    assert southern_eastern["historical_2h2025_profit_native_mn_a"] == 261.0
    assert southern_eastern["historical_2h2025_profit_native_mn_b"] == -202.0
    assert southern_eastern["q2_rpk_minus_ask_gap_pp_a"] < 0
    assert southern_eastern["q2_rpk_minus_ask_gap_pp_b"] > 0
    assert southern_eastern["june_passenger_lf_yoy_pp_a"] < 0
    assert southern_eastern["june_passenger_lf_yoy_pp_b"] > 0


def test_pair_screening_matrix_exposes_latest_driver_lineage_per_leg() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_screening_matrix.csv")
    required = [
        "latest_driver_period_a", "latest_driver_period_b",
        "latest_driver_as_of_a", "latest_driver_as_of_b",
        "latest_driver_metric_count_a", "latest_driver_metric_count_b",
        "latest_cargo_yield_a", "latest_cargo_yield_b",
        "latest_cargo_yield_unit_a", "latest_cargo_yield_unit_b",
        "latest_fuel_cost_per_ask_a", "latest_fuel_cost_per_ask_b",
        "latest_fuel_cost_per_ask_unit_a", "latest_fuel_cost_per_ask_unit_b",
        "latest_operating_cash_flow_native_mn_a", "latest_operating_cash_flow_native_mn_b",
    ]
    assert frame[required[:6]].notna().all().all()
    assert frame[["latest_driver_metric_count_a", "latest_driver_metric_count_b"]].ge(1).all().all()
    assert frame["latest_fuel_cost_per_ask_unit_a"].notna().any()
    assert frame["latest_fuel_cost_per_ask_unit_b"].notna().any()
    assert frame[["latest_cargo_yield_unit_a", "latest_cargo_yield_unit_b"]].notna().any().any()


def test_pair_screening_matrix_exposes_fuel_shock_and_surcharge_context() -> None:
    frame = pd.read_csv("data/normalized/hk_transport/airline_pair_screening_matrix.csv")
    required = [
        "fuel_plus_5pct_profit_impact_usd_mn_a", "fuel_plus_5pct_profit_impact_usd_mn_b",
        "fuel_minus_5pct_profit_impact_usd_mn_a", "fuel_minus_5pct_profit_impact_usd_mn_b",
        "fuel_plus_5pct_scenario_method_a", "fuel_plus_5pct_scenario_method_b",
        "fuel_surcharge_context_a", "fuel_surcharge_context_b",
        "fuel_scenario_fx_observation_date_a", "fuel_scenario_fx_observation_date_b",
    ]
    assert frame[required].notna().all().all()
    assert frame[[
        "fuel_plus_5pct_profit_impact_usd_mn_a",
        "fuel_plus_5pct_profit_impact_usd_mn_b",
        "fuel_minus_5pct_profit_impact_usd_mn_a",
        "fuel_minus_5pct_profit_impact_usd_mn_b",
    ]].apply(lambda col: col.dtype.kind in "fi").all()
