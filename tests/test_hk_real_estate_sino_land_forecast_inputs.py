import pandas as pd
import pytest

from src.hk_real_estate import sino_land_forecast_inputs as forecast_inputs_module
from src.hk_real_estate.sino_land_financial_model import build_sino_land_financial_facts
from src.hk_real_estate.sino_land_forecast_inputs import (
    SINO_FORECAST_INPUT_COLUMNS,
    build_sino_land_forecast_input_quality,
    build_sino_land_forecast_input_selection,
    build_sino_land_forecast_inputs,
    build_sino_land_hk_scope_controls,
    build_sino_land_h1_annualisation_baseline,
    build_sino_land_hk_scope_proxy_scenario,
    build_sino_land_residential_bridge_inputs,
    build_sino_land_supplemental_inputs,
)


def _bridge_fixture() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "bridge_id": "bridge-1",
                "recognized_period_low": "2025-01-01",
                "recognized_period_base": "2025-07-01",
                "recognized_period_high": "2026-01-01",
                "attributable_contract_value_low_hkd": 100_000_000,
                "attributable_contract_value_base_hkd": 150_000_000,
                "attributable_contract_value_high_hkd": 200_000_000,
            },
            {
                "bridge_id": "bridge-2",
                "recognized_period_low": "2025-02-01",
                "recognized_period_base": "2025-08-01",
                "recognized_period_high": "2026-02-01",
                "attributable_contract_value_low_hkd": 50_000_000,
                "attributable_contract_value_base_hkd": 60_000_000,
                "attributable_contract_value_high_hkd": 75_000_000,
            },
        ]
    )


def test_official_panel_quarantines_global_segments():
    facts = build_sino_land_financial_facts()
    panel = build_sino_land_forecast_inputs(
        official_facts=facts,
        financial_data_actuals=pd.DataFrame(),
        consensus=pd.DataFrame(),
        bridge_schedule=pd.DataFrame(),
        load_financial_data=False,
    )["forecast_inputs"]

    assert list(panel.columns) == SINO_FORECAST_INPUT_COLUMNS
    assert not panel["input_id"].duplicated().any()
    assert panel["model_eligibility"].eq("scenario_only_until_hk_scope_bridge").any()
    assert (
        panel.loc[panel["metric"].eq("hong_kong_consolidated_external_revenue")][
            "model_eligibility"
        ]
        .eq("eligible_as_hk_scope_control")
        .all()
    )
    inputs = build_sino_land_forecast_inputs(
        official_facts=facts,
        financial_data_actuals=pd.DataFrame(),
        consensus=pd.DataFrame(),
        bridge_schedule=pd.DataFrame(),
        load_financial_data=False,
    )["selection"]
    assert len(inputs) == len(panel)
    assert inputs["include_hk_core_control"].sum() == 6
    assert inputs["include_pit_backtest"].sum() > 0
    combined = panel.loc[
        panel["metric"].eq("external_revenue_by_geography")
        & panel["geography_scope"].eq("mainland_china_and_hong_kong")
    ].iloc[0]
    assert combined["component"] == "geography_context"
    assert combined["model_eligibility"] == "reported_group_context_only"


def test_hk_scope_controls_are_h1_only_and_share_is_derived():
    facts = build_sino_land_financial_facts()
    controls = build_sino_land_hk_scope_controls(facts)

    assert controls["component"].eq("hk_scope_controls").all()
    share = controls.loc[
        controls["metric"].eq("hong_kong_external_revenue_share_of_consolidated")
        & controls["period_end"].eq("2025-12-31")
    ].iloc[0]
    assert round(float(share["value"]), 6) == round(4488 / 5185 * 100, 6)
    assert share["coverage_status"] == "h1_derived_hk_share_only"
    assert "not an annual" in share["caveat"]


def test_h1_baseline_is_latest_h1_only_and_research_benchmark():
    facts = build_sino_land_financial_facts()
    baseline = build_sino_land_h1_annualisation_baseline(facts)

    assert len(baseline) == 6
    revenue = baseline.loc[baseline["metric"].eq("consolidated_revenue")].iloc[0]
    assert revenue["target_period_end"] == "2026-06-30"
    assert revenue["h1_actual_value_hkd_m"] == 5185.0
    assert revenue["annualised_value_hkd_m"] == 10370.0
    assert revenue["model_use"] == "naive_h1_annualisation_benchmark"
    assert bool(revenue["research_only"]) is True
    assert (
        revenue["comparability_status"] == "benchmark_only_no_scope_matched_fy_growth"
    )


def test_hk_scope_proxy_is_range_only_and_not_a_reported_hk_segment():
    proxy = build_sino_land_hk_scope_proxy_scenario(build_sino_land_financial_facts())

    assert len(proxy) == 4
    fy2025 = proxy.loc[proxy["fiscal_year_end"].eq("2025-06-30")].iloc[0]
    assert fy2025["combined_geography_value_hkd_m"] == 7147.0
    assert fy2025["observed_h1_share_low_pct"] < fy2025["observed_h1_share_high_pct"]
    assert fy2025["hk_proxy_low_hkd_m"] < fy2025["hk_proxy_base_hkd_m"]
    assert fy2025["hk_proxy_base_hkd_m"] < fy2025["hk_proxy_high_hkd_m"]
    assert bool(fy2025["research_only"]) is True
    assert fy2025["model_use"] == "research_only_hk_scope_proxy_scenario"
    assert "not a reported Hong Kong segment" in fy2025["caveat"]


def test_residential_bridge_is_scenario_only_and_fiscal_aggregated():
    bridge = build_sino_land_residential_bridge_inputs(_bridge_fixture())

    base_2026 = bridge.loc[
        bridge["metric"].eq("attributable_contract_value_base")
        & bridge["period_end"].eq("2026-06-30")
    ].iloc[0]
    assert base_2026["value"] == 210.0
    assert bool(base_2026["research_only"]) is True
    assert base_2026["model_eligibility"] == "research_only_scenario"
    assert "not recognized revenue" in base_2026["caveat"]


def test_supplemental_rows_keep_pit_guard_and_source_index():
    supplemental = build_sino_land_supplemental_inputs(
        pd.DataFrame(
            [
                {
                    "metric": "revenue",
                    "value": 123.0,
                    "period_end": "2025-06-30",
                    "period_type": "annual",
                    "source": "vendor_a",
                    "announcement_date": None,
                }
            ]
        ),
        source_dataset="sino_land_financial_model_consensus",
        component="consensus_snapshot",
    )

    assert len(supplemental) == 1
    assert supplemental.iloc[0]["model_eligibility"] == "not_pit_clean"
    assert (
        supplemental.iloc[0]["availability_quality"]
        == "not_pit_clean_missing_announcement_date"
    )
    assert "0" in supplemental.iloc[0]["source_fact_ids"]


def test_explicit_persisted_snapshot_fallback_is_marked_non_pit_clean(monkeypatch):
    facts = build_sino_land_financial_facts()

    def _raise_db_error(_db_path):
        raise OSError("sibling DuckDB unavailable in test")

    def _latest_snapshot(dataset):
        if dataset == forecast_inputs_module.ACTUALS_DATASET:
            return pd.DataFrame(
                [
                    {
                        "metric": "revenue",
                        "value": 100.0,
                        "ticker": "0083.HK",
                        "period_end": "2025-06-30",
                        "period_type": "interim",
                        "source": "persisted_actuals",
                    },
                    {
                        "metric": "revenue",
                        "value": 999.0,
                        "ticker": "0016.HK",
                        "period_end": "2025-06-30",
                        "period_type": "interim",
                        "source": "persisted_actuals",
                    },
                ]
            )
        if dataset == forecast_inputs_module.CONSENSUS_DATASET:
            return pd.DataFrame(
                [
                    {
                        "metric": "revenue",
                        "value": 110.0,
                        "ticker": "0083.HK",
                        "period_end": "2025-06-30",
                        "period_type": "interim",
                        "source": "persisted_consensus",
                    },
                    {
                        "metric": "revenue",
                        "value": 999.0,
                        "ticker": "0016.HK",
                        "period_end": "2025-06-30",
                        "period_type": "interim",
                        "source": "persisted_consensus",
                    },
                ]
            )
        return pd.DataFrame()

    monkeypatch.setattr(
        forecast_inputs_module,
        "load_sino_land_financial_data_actuals",
        _raise_db_error,
    )
    monkeypatch.setattr(
        forecast_inputs_module,
        "load_sino_land_consensus",
        _raise_db_error,
    )
    monkeypatch.setattr(
        forecast_inputs_module,
        "load_latest_normalized",
        _latest_snapshot,
    )

    with pytest.raises(OSError, match="sibling DuckDB unavailable"):
        build_sino_land_forecast_inputs(
            official_facts=facts,
            bridge_schedule=pd.DataFrame(),
            load_financial_data=True,
        )

    result = build_sino_land_forecast_inputs(
        official_facts=facts,
        bridge_schedule=pd.DataFrame(),
        load_financial_data=True,
        use_persisted_financial_fallback=True,
    )

    assert result["financial_data_load_status"] == "persisted_snapshot_fallback_used"
    assert set(result["financial_data_fallback_notes"]) == {
        forecast_inputs_module.ACTUALS_DATASET,
        forecast_inputs_module.CONSENSUS_DATASET,
    }
    supplemental = result["forecast_inputs"].loc[
        result["forecast_inputs"]["source_dataset"].isin(
            {
                forecast_inputs_module.ACTUALS_DATASET,
                forecast_inputs_module.CONSENSUS_DATASET,
            }
        )
    ]
    assert len(supplemental) == 2
    assert supplemental["model_eligibility"].eq("not_pit_clean").all()
    assert (
        supplemental["availability_quality"]
        .eq("persisted_snapshot_fallback_not_pit_clean")
        .all()
    )
    assert supplemental["caveat"].str.contains("sibling DB could not be read").all()
    selection = result["selection"]
    assert (
        selection.loc[
            selection["input_id"].isin(supplemental["input_id"]), "include_pit_backtest"
        ]
        .eq(False)
        .all()
    )


def test_quality_flags_missing_annual_hk_scope_without_blocking_context():
    facts = build_sino_land_financial_facts()
    panel = build_sino_land_forecast_inputs(
        official_facts=facts,
        financial_data_actuals=pd.DataFrame(),
        consensus=pd.DataFrame(),
        bridge_schedule=_bridge_fixture(),
        load_financial_data=False,
    )["forecast_inputs"]
    quality = build_sino_land_forecast_input_quality(panel)

    annual_gap = quality.loc[quality["check_name"].eq("annual_hk_scope_gap")].iloc[0]
    assert annual_gap["status"] == "warn"
    combined = quality.loc[
        quality["check_name"].eq("annual_combined_geography_coverage")
    ].iloc[0]
    assert combined["status"] == "pass"
    research = quality.loc[quality["check_name"].eq("research_bridge_quarantine")].iloc[
        0
    ]
    assert research["status"] == "pass"


def test_selection_quarantines_research_and_non_pit_rows():
    panel = pd.DataFrame(
        [
            {
                "input_id": "official-hk",
                "ticker": "0083.HK",
                "model_eligibility": "eligible_as_hk_scope_control",
                "research_only": False,
                "source_dataset": "sino_land_financial_model_official_facts",
                "availability_quality": "hkex_release_time_verified",
            },
            {
                "input_id": "bridge",
                "ticker": "0083.HK",
                "model_eligibility": "research_only_scenario",
                "research_only": True,
                "source_dataset": "sino_land_hk_residential_recognition_schedule",
                "availability_quality": "latest_normalized_snapshot",
            },
            {
                "input_id": "snapshot",
                "ticker": "0083.HK",
                "model_eligibility": "not_pit_clean",
                "research_only": False,
                "source_dataset": "sino_land_financial_model_consensus",
                "availability_quality": "not_pit_clean_missing_announcement_date",
            },
        ]
    )
    selection = build_sino_land_forecast_input_selection(panel)

    hk = selection.loc[selection["input_id"].eq("official-hk")].iloc[0]
    bridge = selection.loc[selection["input_id"].eq("bridge")].iloc[0]
    snapshot = selection.loc[selection["input_id"].eq("snapshot")].iloc[0]
    assert bool(hk["include_hk_core_control"]) is True
    assert bool(hk["include_pit_backtest"]) is True
    assert bridge["selection_bucket"] == "research_only_scenario"
    assert bool(bridge["include_pit_backtest"]) is False
    assert snapshot["selection_bucket"] == "current_snapshot_only"
    assert bool(snapshot["include_pit_backtest"]) is False
