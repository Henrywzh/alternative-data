import pandas as pd
import pytest

from src.hk_real_estate.shkp_indicative_sales_model import (
    build_shkp_active_future_project_coverage,
    build_shkp_indicative_sales_model_annual,
    build_shkp_indicative_sales_model_backtest,
    build_shkp_indicative_sales_model_coverage,
    build_shkp_indicative_sales_model_monthly,
    build_shkp_indicative_sales_model_phase_summary,
    build_shkp_indicative_sales_model_scenarios,
    build_shkp_indicative_sales_model_forecast,
    build_shkp_indicative_sales_model_quarterly_reconciliation,
    build_shkp_indicative_sales_model_universe_coverage,
    build_shkp_indicative_sales_model_validation,
)


def _signals() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "phase_id": "numeric",
                "development_id": "dev-1",
                "development_name": "Numeric Development",
                "phase_name": "Phase 1",
                "period": "2025-01-01",
                "month_status": "observed_transactions",
                "indicative_attribution_status": "indicative_numeric_snapshot",
                "sales_value_gross_hkd": 100.0,
                "sales_units_gross": 1.0,
                "indicative_sales_value_hkd": 50.0,
                "indicative_sales_units": 0.5,
                "indicative_ownership_pct": 50.0,
                "indicative_confidence": "medium",
                "active_units_eom": 10.0,
            },
            {
                "phase_id": "jv",
                "development_id": "dev-2",
                "development_name": "JV Development",
                "phase_name": "Phase 1",
                "period": "2025-01-01",
                "month_status": "observed_transactions",
                "indicative_attribution_status": "indicative_jv_unquantified",
                "sales_value_gross_hkd": 200.0,
                "sales_units_gross": 2.0,
                "indicative_sales_value_hkd": None,
                "indicative_sales_units": None,
                "indicative_confidence": "medium",
                "active_units_eom": 20.0,
            },
            {
                "phase_id": "unknown",
                "development_id": "dev-3",
                "development_name": "Unknown Development",
                "phase_name": "Phase 1",
                "period": "2025-01-01",
                "month_status": "observed_transactions",
                "indicative_attribution_status": "not_observed",
                "sales_value_gross_hkd": 300.0,
                "sales_units_gross": 3.0,
                "indicative_sales_value_hkd": None,
                "indicative_sales_units": None,
                "active_units_eom": 30.0,
            },
            {
                "phase_id": "numeric",
                "development_id": "dev-1",
                "development_name": "Numeric Development",
                "phase_name": "Phase 1",
                "period": "2026-01-01",
                "month_status": "observed_transactions",
                "indicative_attribution_status": "indicative_numeric_snapshot",
                "sales_value_gross_hkd": 200.0,
                "sales_units_gross": 2.0,
                "indicative_sales_value_hkd": 100.0,
                "indicative_sales_units": 1.0,
                "indicative_ownership_pct": 50.0,
                "indicative_confidence": "medium",
                "active_units_eom": 11.0,
            },
            {
                "phase_id": "jv",
                "development_id": "dev-2",
                "development_name": "JV Development",
                "phase_name": "Phase 1",
                "period": "2026-01-01",
                "month_status": "observed_transactions",
                "indicative_attribution_status": "indicative_jv_unquantified",
                "sales_value_gross_hkd": 400.0,
                "sales_units_gross": 4.0,
                "indicative_sales_value_hkd": None,
                "indicative_sales_units": None,
                "indicative_confidence": "medium",
                "active_units_eom": 21.0,
            },
            {
                "phase_id": "jv",
                "development_id": "dev-2",
                "development_name": "JV Development",
                "phase_name": "Phase 1",
                "period": "2026-02-01",
                "month_status": "not_covered",
                "indicative_attribution_status": "indicative_jv_unquantified",
                "sales_value_gross_hkd": None,
                "sales_units_gross": None,
                "indicative_sales_value_hkd": None,
                "indicative_sales_units": None,
                "active_units_eom": None,
            },
        ]
    )


def test_monthly_model_keeps_numeric_fixed_and_applies_only_jv_scenarios():
    monthly = build_shkp_indicative_sales_model_monthly(_signals())
    jan_2025 = monthly.loc[monthly["period"].eq("2025-01-01")].iloc[0]
    jan_2026 = monthly.loc[monthly["period"].eq("2026-01-01")].iloc[0]

    assert jan_2025["numeric_stake_sales_value_hkd"] == pytest.approx(50.0)
    assert jan_2025["jv_gross_sales_value_hkd"] == pytest.approx(200.0)
    assert jan_2025["unknown_gross_sales_value_hkd"] == pytest.approx(300.0)
    assert jan_2025["estimated_total_low_sales_value_hkd"] == pytest.approx(100.0)
    assert jan_2025["estimated_total_base_sales_value_hkd"] == pytest.approx(150.0)
    assert jan_2025["estimated_total_high_sales_value_hkd"] == pytest.approx(200.0)
    assert jan_2026["numeric_stake_sales_value_hkd"] == pytest.approx(100.0)
    assert jan_2026["estimated_total_base_sales_value_hkd"] == pytest.approx(300.0)
    assert jan_2026["estimated_total_base_sales_value_hkd_yoy_growth_pct"] == pytest.approx(100.0)
    assert jan_2026["numeric_stake_sales_value_hkd_yoy_growth_pct"] == pytest.approx(100.0)


def test_long_scenarios_have_three_rows_per_observed_month_and_custom_jv_shares():
    monthly = build_shkp_indicative_sales_model_monthly(
        _signals(), jv_scenario_shares={"low": 0.2, "base": 0.4, "high": 0.6}
    )
    scenarios = build_shkp_indicative_sales_model_scenarios(
        monthly, jv_scenario_shares={"low": 0.2, "base": 0.4, "high": 0.6}
    )
    assert len(scenarios) == len(monthly) * 3
    base_jan = scenarios[(scenarios["period"] == "2025-01-01") & scenarios["scenario"].eq("base")].iloc[0]
    assert base_jan["jv_assumed_share_pct"] == pytest.approx(40.0)
    assert base_jan["numeric_stake_sales_value_hkd"] == pytest.approx(50.0)
    assert base_jan["estimated_total_sales_value_hkd"] == pytest.approx(130.0)


def test_phase_summary_and_coverage_keep_unknown_and_not_covered_visible():
    signals = _signals()
    phase = build_shkp_indicative_sales_model_phase_summary(signals)
    numeric = phase.loc[phase["phase_id"].eq("numeric")].iloc[0]
    jv = phase.loc[phase["phase_id"].eq("jv")].iloc[0]
    assert numeric["numeric_stake_sales_value_hkd"] == pytest.approx(150.0)
    assert jv["jv_gross_sales_value_hkd"] == pytest.approx(600.0)
    assert jv["months_covered"] == 2

    coverage = build_shkp_indicative_sales_model_coverage(signals).iloc[0]
    assert coverage["input_rows"] == 6
    assert coverage["not_covered_rows"] == 1
    assert coverage["numeric_stake_phases"] == 1
    assert coverage["jv_phases"] == 1
    assert coverage["unknown_gross_value_hkd"] == pytest.approx(300.0)
    assert bool(coverage["strict_ownership_promotion"]) is False


def test_annual_model_flags_partial_year_comparisons():
    monthly = build_shkp_indicative_sales_model_monthly(_signals())
    annual = build_shkp_indicative_sales_model_annual(monthly)
    current = annual.loc[annual["year"].eq(2026)].iloc[0]
    assert current["months_present"] == 2
    assert bool(current["is_partial_year"]) is True
    assert current["growth_comparison_status"] == "partial_year_or_missing_comparison"


def _complete_monthly_model() -> pd.DataFrame:
    rows = []
    for year_end in range(2022, 2027):
        annual_value = float((year_end - 2021) * 1_000_000_000)
        for period in pd.date_range(f"{year_end - 1}-07-01", f"{year_end}-06-01", freq="MS"):
            rows.append(
                {
                    "period": period.strftime("%Y-%m-%d"),
                    "numeric_stake_sales_value_hkd": annual_value / 12,
                    "jv_gross_sales_value_hkd": 0.0,
                    "unknown_gross_sales_value_hkd": 0.0,
                    "estimated_total_low_sales_value_hkd": annual_value * 0.9 / 12,
                    "estimated_total_base_sales_value_hkd": annual_value / 12,
                    "estimated_total_high_sales_value_hkd": annual_value * 1.1 / 12,
                    "numeric_stake_sales_units": 1.0,
                    "jv_gross_sales_units": 0.0,
                    "unknown_gross_sales_units": 0.0,
                    "estimated_total_low_sales_units": 1.0,
                    "estimated_total_base_sales_units": 1.0,
                    "estimated_total_high_sales_units": 1.0,
                }
            )
    return pd.DataFrame(rows)


def test_validation_is_directional_and_uses_the_right_fiscal_window():
    monthly = _complete_monthly_model()
    disclosed = pd.DataFrame(
        [
            {
                "metric": "property_sales_revenue_including_jv_associates",
                "value": 5000.0,
                "period_end": "2026-06-30",
                "source_url": "https://example.test/revenue",
            },
            {
                "metric": "hk_contract_sales_expected_recognition",
                "value": 4000.0,
                "target_period_end": "2026-06-30",
                "source_url": "https://example.test/backlog",
            },
            {
                "metric": "contracted_sales_hk_period",
                "value": 1500.0,
                "period_start": "2025-07-01",
                "period_end": "2025-12-31",
                "source_url": "https://example.test/interim",
            },
        ]
    )
    result = build_shkp_indicative_sales_model_validation(monthly, disclosed)
    fy26 = result.loc[result["fiscal_year_end"].eq(2026)].iloc[0]
    assert fy26["model_base_contract_activity_hkd"] == pytest.approx(5_000_000_000.0)
    assert fy26["model_base_vs_property_revenue_ratio_pct"] == pytest.approx(100.0)
    assert fy26["model_base_vs_expected_recognition_ratio_pct"] == pytest.approx(125.0)
    assert fy26["model_same_period_months"] == 6
    assert fy26["comparison_status"] == "directional_proxy_not_accuracy"


def test_forecast_keeps_ownership_and_growth_scenarios_separate():
    monthly = _complete_monthly_model()
    forecast = build_shkp_indicative_sales_model_forecast(monthly)
    assert len(forecast) == 9
    assert set(forecast["ownership_scenario"]) == {"low", "base", "high"}
    assert set(forecast["growth_scenario"]) == {"low", "base", "high"}
    base = forecast[(forecast["ownership_scenario"] == "base") & forecast["growth_scenario"].eq("base")].iloc[0]
    assert base["forecast_fiscal_year_end"] == 2027
    assert base["forecast_total_sales_hkd"] > base["latest_complete_numeric_stake_sales_hkd"]


def test_forecast_rejects_full_month_year_with_shrinking_phase_coverage():
    monthly = _complete_monthly_model()
    monthly["period"] = pd.to_datetime(monthly["period"])
    monthly["covered_phase_count"] = 100
    monthly["not_covered_phase_count"] = 0
    fy = monthly["period"].dt.year + monthly["period"].dt.month.ge(7).astype(int)
    # FY2026 has all 12 calendar rows but only half of the known phase grid.
    monthly.loc[fy.eq(2026), "covered_phase_count"] = 50
    monthly.loc[fy.eq(2026), "not_covered_phase_count"] = 50
    forecast = build_shkp_indicative_sales_model_forecast(monthly, min_coverage_ratio=0.75)
    assert forecast["latest_complete_fiscal_year_end"].eq(2025).all()
    assert forecast["forecast_fiscal_year_end"].eq(2026).all()
    assert forecast["min_monthly_coverage_ratio"].eq(1.0).all()


def test_backtest_uses_only_prior_contiguous_months_and_exposes_gap_status():
    monthly = _complete_monthly_model().copy()
    monthly["covered_phase_count"] = 10
    monthly["not_covered_phase_count"] = 2
    monthly["unknown_phase_count"] = 1
    monthly = monthly.drop(index=[5]).reset_index(drop=True)
    result = build_shkp_indicative_sales_model_backtest(monthly, lookback_months=3)
    assert set(result["scenario"]) == {"low", "base", "high"}
    assert set(result["forecast_method"]) == {"trailing_mean", "same_month_last_year"}
    assert result["research_only"].eq(True).all()
    # The missing sixth row breaks contiguity for the immediate target, so it
    # must not be scored using a fabricated zero-filled history.
    target = result.loc[result["target_period"].eq("2022-01-01")]
    assert target["backtest_status"].eq("insufficient_contiguous_history").all()
    valid = result.loc[result["backtest_status"].eq("valid_one_step_holdout")]
    assert not valid.empty
    assert valid["model_grid_coverage_ratio"].eq(10 / 12).all()


def test_quarterly_reconciliation_uses_reported_intervals_without_fake_quarters():
    monthly = build_shkp_indicative_sales_model_monthly(_signals())
    facts = pd.DataFrame([
        {
            "fact_id": "reported-1",
            "fact_type": "contracted_sales_attributable_hkd_m",
            "value": 0.00000015,
            "unit": "HKD_m",
            "reporting_period_start": "2025-01-01",
            "reporting_period_end": "2025-01-31",
            "reporting_period_type": "interim",
            "sales_scope": "hong_kong",
            "source_url": "https://example.test/results.pdf",
        }
    ])
    result = build_shkp_indicative_sales_model_quarterly_reconciliation(monthly, facts)
    assert len(result) == 1
    row = result.iloc[0]
    assert row["reported_contract_sales_hkd"] == pytest.approx(0.15)
    assert row["model_base_same_reported_period_hkd"] == pytest.approx(150.0)
    assert row["model_calendar_quarters"] == 1
    assert row["comparison_status"] == "matched_reported_interval"


def test_quarterly_reconciliation_keeps_model_only_quarters_visible():
    monthly = build_shkp_indicative_sales_model_monthly(_signals())
    result = build_shkp_indicative_sales_model_quarterly_reconciliation(monthly, pd.DataFrame())
    assert len(result) == 2
    assert set(result["comparison_status"]) == {"reported_contract_sales_not_available"}
    assert result["reported_contract_sales_hkd"].isna().all()


def test_universe_coverage_keeps_identity_unknown_separate_from_model_signal():
    roster = pd.DataFrame([
        {
            "srpe_development_id": "numeric",
            "candidate_status": "likely_shkp",
            "transaction_route_status": "transaction_register_available",
        },
        {
            "srpe_development_id": "unknown",
            "candidate_status": "identity_unknown_owner_evidence_missing",
            "transaction_route_status": "manifest_not_observed",
        },
        {
            "srpe_development_id": "route-only",
            "candidate_status": "possible_shkp_high_recall",
            "transaction_route_status": "transaction_register_available",
        },
    ])
    signals = _signals()[["phase_id", "period", "sales_value_gross_hkd", "sales_units_gross", "indicative_attribution_status"]]
    events = pd.DataFrame([{"srpe_development_id": "numeric", "transaction_id": "t1"}])
    result = build_shkp_indicative_sales_model_universe_coverage(roster, signals, events)
    by_phase = result.set_index("phase_id")
    assert by_phase.loc["numeric", "model_universe_status"] == "signal_included_likely_shkp"
    assert by_phase.loc["numeric", "has_transaction_events"]
    assert by_phase.loc["unknown", "model_universe_status"] == "signal_included_identity_unknown_excluded_from_attribution"
    assert by_phase.loc["route-only", "model_universe_status"] == "transaction_route_available_signal_missing"
    assert set(result["sales_attribution_status"]) == {"not_promoted"}


def test_active_future_coverage_does_not_turn_identity_gaps_into_zero():
    result = build_shkp_active_future_project_coverage(
        property_catalog=pd.DataFrame([
            {"asset_type": "residential_for_sale", "marketing_name": "A"},
            {"asset_type": "office", "marketing_name": "Office"},
        ]),
        crosswalk=pd.DataFrame([
            {"marketing_name": "A", "srpe_development_id": "1", "match_status": "matched"},
            {"marketing_name": "A", "srpe_development_id": "2", "match_status": "ambiguous"},
        ]),
        phase_candidates=pd.DataFrame([{"srpe_development_id": "1"}, {"srpe_development_id": "2"}]),
        current_manifest=pd.DataFrame([
            {"srpe_development_id": "1", "document_category": "register_of_transactions"},
        ]),
        pipeline_disclosures=pd.DataFrame([
            {"project_label": "Future A", "status": "planned_launch_10m"},
            {"project_label": "Future B", "status": "under_development"},
        ]),
        pipeline_resolution=pd.DataFrame([
            {"linked_srpe_development_id": "1", "resolution_status": "identity_phase_linked_review_required"},
            {"linked_srpe_development_id": None, "resolution_status": "identity_lot_resolved_srpe_pending"},
        ]),
        future_identity_evidence=pd.DataFrame([
            {"project_label": "Future A", "srpe_development_id": "1"},
            {"project_label": "Future B", "srpe_development_id": None},
        ]),
        indicative_signals=pd.DataFrame([
            {"srpe_development_id": "1", "ownership_attribution_ready": False},
        ]),
    )
    current = result.loc[result["coverage_scope"].eq("current_shkp_website_residential_for_sale")].iloc[0]
    future = result.loc[result["coverage_scope"].eq("shkp_disclosed_future_pipeline")].iloc[0]
    assert current["source_rows"] == 1
    assert current["unique_srpe_phase_candidates"] == 2
    assert current["current_transaction_register_phase_rows"] == 1
    assert current["strict_ready_phase_rows"] == 0
    assert future["planned_launch_rows"] == 1
    assert future["linked_srpe_phase_rows"] == 1
    assert future["identity_pending_no_srpe_rows"] == 1
    assert future["identity_evidence_rows"] == 2
    assert future["identity_evidence_no_srpe_rows"] == 1


def test_historical_reconciliation_panel_two_anchor_scopes():
    """Multi-year panel merges revenue + contracted-sales anchors with quality columns."""
    from src.hk_real_estate.shkp_indicative_sales_model import build_shkp_indicative_sales_model_historical_reconciliation
    months = pd.date_range("2020-07-01", "2026-08-01", freq="MS")
    monthly = pd.DataFrame(
        {
            "period": months,
            "estimated_total_low_sales_value_hkd": 1e9,
            "estimated_total_base_sales_value_hkd": 2e9,
            "estimated_total_high_sales_value_hkd": 3e9,
            "estimated_total_base_sales_units": 100.0,
            "covered_phase_count": 50,
            "not_covered_phase_count": 5,
        }
    )
    facts = pd.DataFrame(
        [
            {
                "metric": "property_sales_revenue_including_jv_associates",
                "value": 10000.0,
                "period_start": "2023-07-01",
                "period_end": "2024-06-30",
                "period_type": "annual",
                "available_at": "2024-09-05",
                "source_url": "https://example.com/ar",
                "source_label": "five-year summary",
                "caveat": "recognized revenue lag",
            }
        ]
    )
    quarters = pd.DataFrame(
        [
            {
                "fact_type": "contracted_sales_attributable_hkd_m",
                "value": 2000.0,
                "reporting_period_start": "2023-07-01",
                "reporting_period_end": "2023-12-31",
                "reporting_period_type": "interim_title_inferred",
                "sales_scope": "hong_kong",
                "available_at": "2024-02-26",
                "source_url": "https://example.com/q",
                "source_label": "quarterly article",
                "caveat": "contract flow",
            }
        ]
    )
    signals = pd.DataFrame({"phase_id": [str(i) for i in range(230)], "period": ["2024-01-01"] * 230})
    panel = build_shkp_indicative_sales_model_historical_reconciliation(
        monthly,
        disclosed_facts=facts,
        quarterly_facts=quarters,
        signals=signals,
    )
    assert len(panel) == 2
    scopes = set(panel["anchor_scope"])
    assert scopes == {
        "property_sales_revenue_all_regions_legacy_summary",
        "contracted_sales_attributable_hong_kong",
    }
    rev = panel[panel["anchor_scope"] == "property_sales_revenue_all_regions_legacy_summary"].iloc[0]
    con = panel[panel["anchor_scope"] == "contracted_sales_attributable_hong_kong"].iloc[0]
    assert rev["reported_sales_value_hkd"] == 10_000_000_000.0
    assert con["reported_sales_value_hkd"] == 2_000_000_000.0
    assert rev["model_months_present"] == 12
    assert con["model_months_present"] == 6
    assert rev["model_covered_phase_count"] == 230
    assert rev["model_total_phase_count"] == 230
    assert rev["model_grid_coverage_ratio"] == 1.0
    assert con["comparison_status"] == "matched_reported_interval"


def test_backtest_universe_coverage_column():
    """universe_coverage_ratio must expose early-year universe gaps vs the grid-only ratio."""
    from src.hk_real_estate.shkp_indicative_sales_model import build_shkp_indicative_sales_model_backtest
    months = pd.date_range("2013-01-01", "2013-12-01", freq="MS")
    monthly = pd.DataFrame(
        {
            "period": months,
            "estimated_total_low_sales_value_hkd": [1e9] * 12,
            "estimated_total_base_sales_value_hkd": [2e9] * 12,
            "estimated_total_high_sales_value_hkd": [3e9] * 12,
            "covered_phase_count": [5] * 12,
            "not_covered_phase_count": [1] * 12,
            "unknown_phase_count": [2] * 12,
        }
    )
    bt = build_shkp_indicative_sales_model_backtest(monthly, universe_phase_count=230)
    base = bt[bt["scenario"] == "base"]
    assert base["model_grid_coverage_ratio"].iloc[0] == 5 / 6  # grid-internal
    assert base["universe_coverage_ratio"].iloc[0] == 5 / 230  # full universe


def test_jv_stake_override_promotes_cullinan_west():
    """Cullinan West phases must be numeric 100% via the curated JV stake override."""
    from src.hk_real_estate.sources.shkp import SHKP_CURATED_JV_STAKE_OVERRIDES
    # Values are PERCENT (100.0 = 100%), consistent with the roster column.
    assert SHKP_CURATED_JV_STAKE_OVERRIDES == {"3945": 100.0, "4945": 100.0, "5886": 100.0}
