import pandas as pd
import pytest

from src.hk_transport.sources import airline_earnings_model_v3 as v3


def _v2_bridge() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "company": "Test Airlines",
                "parent_group": "Test Airlines",
                "ticker": "000000.SH",
                "scenario": "base",
                "forecast_horizon": "FY2026_pre_interim",
                "as_of_date": "2026-06-30",
                "fy2025_nonpassenger_revenue_native_mn": 100.0,
                "forecast_nonpassenger_revenue_native_mn": 100.0,
                "nonpassenger_revenue_growth_assumption_pct": 0.0,
                "forecast_passenger_revenue_native_mn": 900.0,
                "forecast_operating_cost_native_mn": 800.0,
                "actual_fx_native_per_usd": 7.0,
                "net_to_operating_profit_conversion": 0.8,
                "consensus_fy2026_revenue_usd_mn": 150.0,
                "consensus_fy2026_profit_usd_mn": 100.0,
            }
        ]
    )


def _cargo(snapshot_date: str = "2026-06-30") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observation_month": month,
                "export_yoy_pct": export,
                "import_yoy_pct": imports,
                "total_trade_yoy_pct": total,
                "source_snapshot_date": snapshot_date,
            }
            for month, export, imports, total in (
                ("2026-04", 20.0, 10.0, 16.0),
                ("2026-05", 30.0, 20.0, 26.0),
                ("2026-06", 40.0, 30.0, 36.0),
            )
        ]
    )


def _official_drivers() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"company": "Test Airlines", "statement_period": "FY2025", "metric": metric, "value_native": value}
            for metric, value in (
                ("total_revenue", 1000.0),
                ("operating_cost", 800.0),
                ("profit_total", 150.0),
                ("attributable_net_income", 100.0),
                ("basic_eps", 2.0),
            )
        ]
    )


def _official_drivers_with_revenue_split() -> pd.DataFrame:
    return pd.concat(
        [
            _official_drivers(),
            pd.DataFrame(
                [
                    {
                        "company": "Test Airlines",
                        "statement_period": "FY2025",
                        "metric": "passenger_revenue",
                        "value_native": 850.0,
                    },
                    {
                        "company": "Test Airlines",
                        "statement_period": "FY2025",
                        "metric": "cargo_revenue",
                        "value_native": 50.0,
                    },
                ]
            ),
        ],
        ignore_index=True,
    )


def _postal() -> pd.DataFrame:
    rows = []
    for period, month, period_end, release, express_volume, express_revenue in (
        ("2026-01_to_04", "2026-04", "2026-04-30", "2026-05-20", 5.1, 6.6),
        ("2026-H1", "2026-06", "2026-06-30", "2026-07-17", 5.0, 7.3),
    ):
        rows.extend(
            [
                {
                    "observation_period": period,
                    "period_type": "cumulative",
                    "observation_month": month,
                    "period_end": period_end,
                    "metric": "express_delivery_volume",
                    "yoy_pct": express_volume,
                    "source_release_date": release,
                    "source_quality": "spb_primary_official_html",
                },
                {
                    "observation_period": period,
                    "period_type": "cumulative",
                    "observation_month": month,
                    "period_end": period_end,
                    "metric": "express_business_revenue",
                    "yoy_pct": express_revenue,
                    "source_release_date": release,
                    "source_quality": "spb_primary_official_html",
                },
            ]
        )
    return pd.DataFrame(rows)


def _travel_demand_events() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": "mct_2026_may_tourism",
                "event_family": "holiday_tourism",
                "event_name": "2026 May Day domestic tourism",
                "event_duration_days": 5,
                "metric": "domestic_travelers",
                "value_per_day": 65.0,
                "yoy_pct": 3.6,
                "daily_yoy_pct": None,
                "source_release_date": "2026-05-07",
                "source_quality": "government_primary_official_html",
            },
            {
                "event_id": "mct_2026_dragon_boat_tourism",
                "event_family": "holiday_tourism",
                "event_name": "2026 Dragon Boat domestic tourism",
                "event_duration_days": 3,
                "metric": "domestic_travelers",
                "value_per_day": 41.333333,
                "yoy_pct": 4.4,
                "daily_yoy_pct": None,
                "source_release_date": "2026-06-22",
                "source_quality": "government_primary_official_html",
            },
        ]
    )


def _airport_traffic() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "observation_month": "2026-05",
                "airport": "SHA-PVG",
                "metric": "passenger_throughput",
                "scope": "total",
                "value": 650.0,
                "yoy_pct": 2.0,
                "source_release_date": "2026-06-15",
                "source_quality": "issuer_primary_official_pdf",
            },
            {
                "observation_month": "2026-06",
                "airport": "SHA-PVG",
                "metric": "passenger_throughput",
                "scope": "total",
                "value": 686.35,
                "yoy_pct": -0.55,
                "source_release_date": "2026-07-15",
                "source_quality": "issuer_primary_official_pdf",
            },
            {
                "observation_month": "2026-06",
                "airport": "SHA-PVG",
                "metric": "aircraft_movements",
                "scope": "total",
                "value": 44_342.0,
                "yoy_pct": -1.19,
                "source_release_date": "2026-07-15",
                "source_quality": "issuer_primary_official_pdf",
            },
        ]
    )


def test_v3_uses_external_trade_signal_for_nonpassenger_overlay(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(v3, "OUTPUT_PATH", tmp_path / "airline_earnings_model_v3.csv")
    result = v3.build_airline_earnings_model_v3(
        v2_bridge=_v2_bridge(),
        cargo=_cargo(),
        caac=pd.DataFrame(),
        postal=pd.DataFrame(),
        retrieved_at="2026-07-02T00:00:00+00:00",
    )

    row = result.iloc[0]
    # Average export=30, import=20; 0.6*30 + 0.4*20 = 26.
    assert row["cargo_proxy_yoy_pct"] == pytest.approx(26.0)
    assert row["v3_nonpassenger_revenue_growth_pct"] == pytest.approx(26.0)
    assert row["v3_nonpassenger_revenue_native_mn"] == pytest.approx(126.0)
    assert row["v3_revenue_native_mn"] == pytest.approx(1026.0)
    assert row["v3_operating_profit_native_mn"] == pytest.approx(226.0)
    assert row["v3_net_profit_proxy_usd_mn"] == pytest.approx(226.0 / 7.0 * 0.8)
    assert row["v3_eps_status"] == "not_modelled_missing_point_in_time_share_count_bridge"


def test_v3_kpi_coverage_explicitly_marks_missing_eps_and_partial_drivers(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(v3, "COVERAGE_OUTPUT_PATH", tmp_path / "airline_v3_coverage.csv")
    result = v3.build_airline_earnings_model_v3_kpi_coverage(
        retrieved_at="2026-07-02T00:00:00+00:00"
    )

    eps = result.loc[result["kpi"].eq("EPS")].iloc[0]
    fuel_hedge = result.loc[result["kpi"].eq("Fuel hedge")].iloc[0]
    assert eps["coverage_status"] == "proxy"
    assert fuel_hedge["coverage_status"] == "partial"
    assert result["kpi"].nunique() >= 15


def test_v3_prefers_reported_below_operating_residual_bridge(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(v3, "OUTPUT_PATH", tmp_path / "airline_earnings_model_v3.csv")
    result = v3.build_airline_earnings_model_v3(
        v2_bridge=_v2_bridge(),
        cargo=_cargo(),
        caac=pd.DataFrame(),
        postal=pd.DataFrame(),
        official_drivers=_official_drivers(),
        retrieved_at="2026-07-02T00:00:00+00:00",
    )

    row = result.iloc[0]
    # Historical operating contribution = 1,000 - 800 = 200.
    # Attributable below-operating residual = 100 - 200 = -100.
    assert row["profit_bridge_status"] == "available_fy2025_reported_below_operating_residual"
    assert row["v3_attributable_net_income_bridge_native_mn"] == pytest.approx(126.0)
    assert row["v3_net_profit_proxy_native_mn"] == pytest.approx(126.0)
    assert row["v3_basic_eps_bridge_rmb_per_share"] == pytest.approx(2.52)
    assert row["net_income_status"] == "proxy_operating_profit_plus_fy2025_reported_below_operating_residual"


def test_v3_uses_reported_operating_profit_and_carries_waterfall_context(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(v3, "OUTPUT_PATH", tmp_path / "airline_earnings_model_v3.csv")
    official = pd.concat(
        [
            _official_drivers(),
            pd.DataFrame(
                [
                    {"company": "Test Airlines", "statement_period": "FY2025", "metric": metric, "value_native": value}
                    for metric, value in (
                        ("operating_profit", 180.0),
                        ("finance_cost", 20.0),
                        ("income_tax_expense", 15.0),
                        ("net_income_total", 140.0),
                    )
                ]
            ),
        ],
        ignore_index=True,
    )
    result = v3.build_airline_earnings_model_v3(
        v2_bridge=_v2_bridge(),
        cargo=_cargo(),
        caac=pd.DataFrame(),
        postal=pd.DataFrame(),
        official_drivers=official,
        retrieved_at="2026-07-02T00:00:00+00:00",
    )

    row = result.iloc[0]
    # The reported operating-profit anchor replaces the old 1,000-800
    # contribution for the historical below-operating residual.
    assert row["fy2025_reported_operating_profit_native_mn"] == pytest.approx(180.0)
    assert row["operating_contribution_method"] == "fy2025_reported_consolidated_income_statement_operating_profit"
    assert row["fy2025_waterfall_status"] == "available_reported_fy2025_waterfall"
    assert row["fy2025_finance_cost_native_mn"] == pytest.approx(20.0)
    assert row["fy2025_income_tax_expense_native_mn"] == pytest.approx(15.0)
    assert row["fy2025_net_income_total_native_mn"] == pytest.approx(140.0)
    assert row["forward_waterfall_status"] == "not_available_missing_reconciled_historical_waterfall"
    # Attributable profit 100 - reported operating profit 180 = -80 residual.
    assert row["v3_attributable_net_income_bridge_native_mn"] == pytest.approx(146.0)


def test_v3_labels_v2_aggregate_operating_profit_proxy_when_formal_row_is_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(v3, "OUTPUT_PATH", tmp_path / "airline_earnings_model_v3.csv")
    bridge = _v2_bridge().copy()
    bridge["actual_operating_profit_usd_mn"] = 25.0
    bridge["actual_fx_native_per_usd"] = 7.0
    result = v3.build_airline_earnings_model_v3(
        v2_bridge=bridge,
        cargo=_cargo(),
        caac=pd.DataFrame(),
        postal=pd.DataFrame(),
        official_drivers=_official_drivers(),
        retrieved_at="2026-07-02T00:00:00+00:00",
    )

    row = result.iloc[0]
    assert row["operating_contribution_method"] == "fy2025_v2_aggregate_operating_profit_proxy"
    assert row["fy2025_operating_profit_proxy_native_mn"] == pytest.approx(175.0)
    # FY2025 attributable profit 100 - proxy operating profit 175 = -75.
    assert row["v3_attributable_net_income_bridge_native_mn"] == pytest.approx(151.0)


def test_forward_waterfall_proxy_requires_reconciled_history_and_is_explicitly_labelled() -> None:
    context = {
        "fy2025_waterfall_reconciliation_status": "reconciles_core_profit_waterfall",
        **{
            f"fy2025_{metric}_native_mn": value
            for metric, value in (
                ("finance_cost", 20.0),
                ("other_income", 5.0),
                ("investment_income", 3.0),
                ("fair_value_change_income", 1.0),
                ("credit_impairment_loss", -1.0),
                ("asset_impairment_loss", -2.0),
                ("asset_disposal_income", 1.0),
                ("non_operating_income", 4.0),
                ("non_operating_expense", 2.0),
                ("income_tax_expense", 10.0),
                ("minority_interest", 3.0),
            )
        },
    }
    anchor = {
        "fy2025_total_revenue_native_mn": 1000.0,
        "implied_basic_shares_mn": 50.0,
    }
    result = v3._forward_waterfall_proxy(
        context,
        anchor,
        forecast_operating_contribution_native_mn=220.0,
        forecast_revenue_native_mn=1100.0,
    )

    # Finance cost scales 20% with revenue; all other disclosed rows carry.
    assert result["forward_waterfall_status"] == "available_forward_waterfall_proxy"
    assert result["forward_finance_cost_native_mn"] == pytest.approx(22.0)
    assert result["forward_profit_total_waterfall_proxy_native_mn"] == pytest.approx(207.0)
    assert result["forward_net_income_total_waterfall_proxy_native_mn"] == pytest.approx(197.0)
    assert result["forward_attributable_net_income_waterfall_proxy_native_mn"] == pytest.approx(194.0)
    assert result["forward_basic_eps_waterfall_proxy_rmb_per_share"] == pytest.approx(3.88)

    context["fy2025_waterfall_reconciliation_status"] = "partial_reconciliation_missing_rows"
    blocked = v3._forward_waterfall_proxy(
        context,
        anchor,
        forecast_operating_contribution_native_mn=220.0,
        forecast_revenue_native_mn=1100.0,
    )
    assert blocked["forward_waterfall_status"] == "not_available_missing_reconciled_historical_waterfall"

    context["fy2025_waterfall_reconciliation_status"] = "reconciles_core_profit_waterfall"
    rate_result = v3._forward_waterfall_proxy(
        context,
        anchor,
        {"fy2025_effective_tax_rate_pct": 25.0},
        forecast_operating_contribution_native_mn=220.0,
        forecast_revenue_native_mn=1100.0,
    )
    assert rate_result["forward_income_tax_expense_native_mn"] == pytest.approx(51.75)
    assert rate_result["forward_income_tax_method"] == "fy2025_effective_tax_rate_on_forecast_profit"
    assert rate_result["forward_attributable_net_income_waterfall_proxy_native_mn"] == pytest.approx(152.25)

    nci_context = dict(context)
    nci_context["fy2025_net_income_total_native_mn"] = 200.0
    nci_context["fy2025_minority_interest_native_mn"] = 50.0
    nci_result = v3._forward_waterfall_proxy(
        nci_context,
        anchor,
        forecast_operating_contribution_native_mn=220.0,
        forecast_revenue_native_mn=1100.0,
    )
    assert nci_result["forward_minority_interest_share_pct"] == pytest.approx(25.0)
    assert nci_result["forward_nci_share_based_status"] == "available_share_based_nci"
    assert nci_result["forward_attributable_share_based_native_mn"] == pytest.approx(147.75)


def test_v3_postal_context_respects_release_date_cutoff(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(v3, "OUTPUT_PATH", tmp_path / "airline_earnings_model_v3.csv")
    result = v3.build_airline_earnings_model_v3(
        v2_bridge=_v2_bridge(),
        cargo=_cargo(),
        caac=pd.DataFrame(),
        postal=_postal(),
        retrieved_at="2026-07-02T00:00:00+00:00",
    )

    row = result.iloc[0]
    # The 2026 H1 article was released after the 2026-06-30 model cutoff;
    # the older Jan-Apr article is the latest admissible vintage.
    assert row["postal_context_status"] == "available_release_date_safe_cumulative_context"
    assert row["postal_observation_period"] == "2026-01_to_04"
    assert row["postal_source_release_date"] == "2026-05-20"
    assert row["postal_express_volume_yoy_pct"] == pytest.approx(5.1)
    assert row["postal_express_revenue_yoy_pct"] == pytest.approx(6.6)


def test_v3_travel_demand_context_respects_release_date_cutoff(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(v3, "OUTPUT_PATH", tmp_path / "airline_earnings_model_v3.csv")
    result = v3.build_airline_earnings_model_v3(
        v2_bridge=_v2_bridge(),
        cargo=_cargo(),
        caac=pd.DataFrame(),
        postal=pd.DataFrame(),
        travel_demand_events=_travel_demand_events(),
        retrieved_at="2026-07-02T00:00:00+00:00",
    )

    row = result.iloc[0]
    assert row["travel_demand_context_status"] == "available_release_date_safe_event_context"
    assert row["travel_demand_latest_event_id"] == "mct_2026_dragon_boat_tourism"
    assert row["travel_demand_domestic_tourism_yoy_pct"] == pytest.approx(4.4)
    assert row["travel_demand_latest_duration_days"] == pytest.approx(3.0)


def test_v3_airport_traffic_context_respects_release_date_cutoff(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(v3, "OUTPUT_PATH", tmp_path / "airline_earnings_model_v3.csv")
    result = v3.build_airline_earnings_model_v3(
        v2_bridge=_v2_bridge(),
        cargo=_cargo(),
        caac=pd.DataFrame(),
        postal=pd.DataFrame(),
        travel_demand_events=pd.DataFrame(),
        airport_traffic=_airport_traffic(),
        retrieved_at="2026-07-02T00:00:00+00:00",
    )

    row = result.iloc[0]
    assert row["airport_traffic_context_status"] == "available_release_date_safe_hub_context"
    # The June bulletin was released 2026-07-15, after the 2026-07-02 model
    # cutoff; the May bulletin released 2026-06-15 is the latest admissible row.
    assert row["airport_traffic_observation_month"] == "2026-05"
    assert row["airport_traffic_passenger_throughput_10k_persons"] == pytest.approx(650.0)
    assert row["airport_traffic_passenger_yoy_pct"] == pytest.approx(2.0)
    assert row["airport_traffic_aircraft_movements"] is None
    assert row["airport_traffic_airport"] == "SHA-PVG"

    late = pd.concat(
        [
            _airport_traffic(),
            pd.DataFrame(
                [
                    {
                        "observation_month": "2026-07",
                        "airport": "SHA-PVG",
                        "metric": "passenger_throughput",
                        "scope": "total",
                        "value": 700.0,
                        "yoy_pct": 1.0,
                        "source_release_date": "2026-08-15",
                        "source_quality": "issuer_primary_official_pdf",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    result2 = v3.build_airline_earnings_model_v3(
        v2_bridge=_v2_bridge(),
        cargo=_cargo(),
        caac=pd.DataFrame(),
        postal=pd.DataFrame(),
        travel_demand_events=pd.DataFrame(),
        airport_traffic=late,
        retrieved_at="2026-07-02T00:00:00+00:00",
    )
    # The July observation was released after the cutoff and must not leak in.
    assert result2.iloc[0]["airport_traffic_observation_month"] == "2026-05"


def test_v3_carries_fuel_surcharge_recovery_context(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(v3, "OUTPUT_PATH", tmp_path / "airline_earnings_model_v3.csv")
    recovery = pd.DataFrame(
        [
            {
                "carrier_scope": "Mainland China passenger airlines",
                "effective_from": "2026-07-05",
                "surcharge_change_pct": -33.33,
                "fuel_change_pct": 18.35,
                "surcharge_to_fuel_change_ratio": -1.82,
            },
            {
                "carrier_scope": "Cathay Pacific",
                "effective_from": "2026-08-01",
                "surcharge_change_pct": 20.0,
                "fuel_change_pct": 2.1,
                "surcharge_to_fuel_change_ratio": 9.52,
            },
        ]
    )
    result = v3.build_airline_earnings_model_v3(
        v2_bridge=_v2_bridge(),
        cargo=_cargo(),
        caac=pd.DataFrame(),
        postal=pd.DataFrame(),
        travel_demand_events=pd.DataFrame(),
        airport_traffic=pd.DataFrame(),
        fuel_recovery=recovery,
        retrieved_at="2026-07-02T00:00:00+00:00",
    )

    row = result.iloc[0]
    assert row["fuel_surcharge_recovery_status"] == "available_dated_surcharge_to_fuel_recovery_proxy"
    assert row["mainland_surcharge_change_pct"] == pytest.approx(-33.33)
    assert row["mainland_surcharge_to_fuel_change_ratio"] == pytest.approx(-1.82)
    assert row["cathay_surcharge_change_pct"] == pytest.approx(20.0)


def test_v3_carries_cargo_airport_bridge_calibration(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(v3, "OUTPUT_PATH", tmp_path / "airline_earnings_model_v3.csv")
    bridge = pd.DataFrame(
        [
            {
                "company": "Test Airlines",
                "hub_airports": "SHA-PVG,SHA-SHA",
                "airport_cargo_tonnes": 820_000.0,
                "airport_cargo_yoy_pct": 6.0,
                "company_cargo_tonnes": 22_000.0,
                "company_cargo_tonnes_yoy_pct": 15.79,
                "cargo_tonnage_bridge_gap_pp": -9.79,
                "airport_cargo_as_pct_of_company_cargo": 3_727.27,
                "reported_cargo_revenue_per_tonne_native": 7.2,
                "bridge_status": "available_airport_and_company_tonnage",
            }
        ]
    )
    result = v3.build_airline_earnings_model_v3(
        v2_bridge=_v2_bridge(),
        cargo=_cargo(),
        caac=pd.DataFrame(),
        postal=pd.DataFrame(),
        travel_demand_events=pd.DataFrame(),
        airport_traffic=pd.DataFrame(),
        cargo_airport_bridge=bridge,
        retrieved_at="2026-07-02T00:00:00+00:00",
    )

    row = result.iloc[0]
    assert row["cargo_airport_bridge_status"] == "available_airport_and_company_tonnage"
    assert row["cargo_airport_tonnes"] == pytest.approx(820_000.0)
    assert row["cargo_airport_yoy_pct"] == pytest.approx(6.0)
    assert row["cargo_company_tonnes"] == pytest.approx(22_000.0)
    assert row["cargo_tonnage_bridge_gap_pp"] == pytest.approx(-9.79)
    assert row["cargo_revenue_per_tonne_native"] == pytest.approx(7.2)


def test_v3_carries_cargo_yield_bridge_context(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(v3, "OUTPUT_PATH", tmp_path / "airline_earnings_model_v3.csv")
    bridge = pd.DataFrame(
        [
            {
                "company": "Test Airlines",
                "bridge_status": "available_bridge",
                "revenue_anchor_period": "1H2025",
                "h1_2025_cargo_revenue_native_mn": 100.0,
                "h1_2025_cargo_tonnes": 20_000.0,
                "revenue_per_tonne_native": 5_000.0,
                "h1_2026_cargo_tonnes": 24_000.0,
                "h1_2026_cargo_tonnes_yoy_pct": 20.0,
                "h1_2026_cargo_revenue_bridge_native_mn": 120.0,
                "bridge_revenue_growth_pct": 20.0,
                "h1_2025_cargo_revenue_proxy_native_mn": 100.0,
            }
        ]
    )
    result = v3.build_airline_earnings_model_v3(
        v2_bridge=_v2_bridge(),
        cargo=_cargo(),
        caac=pd.DataFrame(),
        postal=pd.DataFrame(),
        travel_demand_events=pd.DataFrame(),
        airport_traffic=pd.DataFrame(),
        cargo_yield_bridge=bridge,
        retrieved_at="2026-07-02T00:00:00+00:00",
    )

    row = result.iloc[0]
    assert row["cargo_yield_bridge_status"] == "available_bridge"
    assert row["cargo_yield_bridge_revenue_per_tonne_native"] == pytest.approx(5_000.0)
    assert row["cargo_yield_bridge_h1_2026_tonnes"] == pytest.approx(24_000.0)
    assert row["cargo_yield_bridge_h1_2026_revenue_native_mn"] == pytest.approx(120.0)
    assert row["cargo_yield_bridge_revenue_growth_pct"] == pytest.approx(20.0)


def test_v3_regime_flip_guard_switches_to_consensus_margin_for_loss_year_carriers(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(v3, "OUTPUT_PATH", tmp_path / "airline_earnings_model_v3.csv")
    official = pd.concat(
        [
            _official_drivers(),
            pd.DataFrame(
                [
                    {
                        "company": "Test Airlines",
                        "statement_period": "FY2025",
                        "metric": "operating_profit",
                        "value_native": -50.0,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    result = v3.build_airline_earnings_model_v3(
        v2_bridge=_v2_bridge(),
        cargo=_cargo(),
        caac=pd.DataFrame(),
        postal=pd.DataFrame(),
        official_drivers=official,
        retrieved_at="2026-07-02T00:00:00+00:00",
    )

    row = result.iloc[0]
    assert bool(row["regime_flip_flag"]) is True
    assert row["net_income_leg"] == "consensus_margin_guard_regime_flip"
    # Consensus margin 100/150 = 66.7% applied to forecast revenue 1,026m.
    assert row["v3_net_profit_consensus_guarded_native_mn"] == pytest.approx(684.0)
    # The raw residual bridge remains available as a diagnostic.
    assert row["v3_attributable_net_income_bridge_native_mn"] is not None


def test_v3_blends_cargo_sources_and_blocks_late_mofcom_snapshot() -> None:
    late_trade = _cargo(snapshot_date="2026-07-01")
    late = v3._latest_trade_signal(late_trade, as_of_date="2026-06-30")
    assert late["cargo_proxy_status"] == "no_observation_before_cutoff"

    blend = v3._blended_cargo_demand_signal(
        late,
        {
            "caac_sector_cargo_yoy_pct": 2.4,
        },
        {
            "postal_express_volume_yoy_pct": 5.1,
        },
    )
    assert blend["cargo_demand_blend_status"] == "available_partial_cargo_demand_blend"
    assert blend["cargo_proxy_blended_yoy_pct"] == pytest.approx(3.3)


def test_v3_route_licence_context_is_release_date_safe() -> None:
    route_events = pd.DataFrame(
        [
            {
                "airline_normalized_name": "Spring Airlines",
                "table_type": "new_domestic_route",
                "initial_frequency_per_week": 14.0,
                "source_release_date": "2026-03-23",
                "schedule_season": "2026_summer_autumn",
            },
            {
                "airline_normalized_name": "Spring Airlines",
                "table_type": "cancelled_route_licence",
                "initial_frequency_per_week": None,
                "source_release_date": "2026-08-15",
                "schedule_season": "2026_summer_autumn",
            },
        ]
    )
    result = v3._company_caac_route_licence_context(
        route_events,
        "Spring Airlines",
        as_of_date="2026-06-30",
    )
    assert result["caac_route_licence_context_status"] == "available_planned_supply_context_only"
    assert result["caac_route_licence_new_route_count"] == 1
    assert result["caac_route_licence_new_route_initial_frequency_per_week"] == pytest.approx(14.0)
    assert result["caac_route_licence_cancellation_count"] == 0


def test_v3_splits_reported_cargo_and_other_revenue(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(v3, "OUTPUT_PATH", tmp_path / "airline_earnings_model_v3.csv")
    result = v3.build_airline_earnings_model_v3(
        v2_bridge=_v2_bridge(),
        cargo=_cargo(),
        caac=pd.DataFrame(),
        postal=pd.DataFrame(),
        official_drivers=_official_drivers_with_revenue_split(),
        retrieved_at="2026-07-02T00:00:00+00:00",
    )

    row = result.iloc[0]
    assert row["revenue_split_status"] == "available_cargo_other_split"
    assert row["fy2025_cargo_revenue_native_mn"] == pytest.approx(50.0)
    assert row["fy2025_other_revenue_native_mn"] == pytest.approx(100.0)
    assert row["v3_cargo_revenue_growth_pct"] == pytest.approx(26.0)
    assert row["v3_cargo_revenue_native_mn"] == pytest.approx(63.0)
    assert row["v3_other_revenue_growth_pct"] == pytest.approx(900.0 / 850.0 * 100.0 - 100.0)
    assert row["v3_other_revenue_native_mn"] == pytest.approx(100.0 * (900.0 / 850.0))
    assert row["v3_nonpassenger_revenue_split_status"] == "available_cargo_proxy_plus_other_passenger_growth"


def test_select_net_income_leg_share_based_override_for_high_nci_carrier() -> None:
    # Southern-style: raw residual bridge carries a breakeven-year absolute
    # NCI/tax adjustment into a large forward profit year (15,133 vs 3,193).
    proxy_n, proxy_usd, guarded_n, guarded_usd, leg, override = v3._select_net_income_leg(
        residual_bridge_native=15_000.0,
        legacy_native=None,
        share_based_native=3_000.0,
        nci_share_status="available_share_based_nci",
        regime_flip=False,
        consensus_margin=0.5,
        forward_revenue_native=20_000.0,
        fx=6.75,
    )
    assert override is True
    assert leg == "share_based_nci_forward"
    assert guarded_n == pytest.approx(3_000.0)
    assert proxy_n == pytest.approx(3_000.0)
    assert proxy_usd == pytest.approx(3_000.0 / 6.75)


def test_select_net_income_leg_keeps_residual_when_share_based_does_not_diverge() -> None:
    proxy_n, proxy_usd, guarded_n, guarded_usd, leg, override = v3._select_net_income_leg(
        residual_bridge_native=1_100.0,
        legacy_native=None,
        share_based_native=1_000.0,
        nci_share_status="available_share_based_nci",
        regime_flip=False,
        consensus_margin=5.0,
        forward_revenue_native=20_000.0,
        fx=7.0,
    )
    assert override is False
    assert leg == "residual_bridge"
    assert guarded_n == pytest.approx(1_100.0)


def test_select_net_income_leg_regime_flip_guard_uses_consensus_margin() -> None:
    proxy_n, proxy_usd, guarded_n, guarded_usd, leg, override = v3._select_net_income_leg(
        residual_bridge_native=2_000.0,
        legacy_native=None,
        share_based_native=None,
        nci_share_status="not_interpretable_negative_or_zero_nci",
        regime_flip=True,
        consensus_margin=10.0,
        forward_revenue_native=20_000.0,
        fx=7.0,
    )
    assert override is False
    assert leg == "consensus_margin_guard_regime_flip"
    assert guarded_n == pytest.approx(2_000.0)


def test_select_net_income_leg_legacy_fallback() -> None:
    proxy_n, proxy_usd, guarded_n, guarded_usd, leg, override = v3._select_net_income_leg(
        residual_bridge_native=None,
        legacy_native=80.0,
        share_based_native=None,
        nci_share_status="not_available",
        regime_flip=False,
        consensus_margin=None,
        forward_revenue_native=1_000.0,
        fx=7.0,
    )
    assert override is False
    assert leg == "legacy_conversion"
    assert guarded_n == pytest.approx(80.0)
