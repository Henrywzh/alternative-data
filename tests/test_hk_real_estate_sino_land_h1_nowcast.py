import pandas as pd

from src.hk_real_estate.sino_land_financial_model import (
    build_sino_land_financial_facts,
)
from src.hk_real_estate.sino_land_h1_nowcast import (
    BACKTEST_DATASET,
    GROUP_METRICS,
    SEGMENT_COMPONENTS,
    SEGMENT_METRICS,
    RESIDENTIAL_H2_DATASET,
    build_sino_land_h1_residential_h2_scenario,
    build_sino_land_h1_backtest,
    build_sino_land_h1_nowcast,
    run_sino_land_h1_nowcast,
)


def test_h1_nowcast_keeps_group_baseline_separate_from_segment_scenarios():
    result = build_sino_land_h1_nowcast(build_sino_land_financial_facts())

    nowcast = result["nowcast"]
    segment = result["segment_scenarios"]
    quality = result["quality"]

    assert len(nowcast) == len(GROUP_METRICS)
    revenue = nowcast.loc[nowcast["metric"].eq("consolidated_revenue")].iloc[0]
    assert revenue["target_fiscal_year_end"] == "2026-06-30"
    assert revenue["h1_actual_hkd_m"] == 5185.0
    assert revenue["h2_forecast_hkd_m"] == 5185.0
    assert revenue["fy_forecast_hkd_m"] == 10370.0
    assert revenue["model_name"] == "naive_2x_h1"
    assert bool(revenue["research_only"]) is True

    assert len(segment) == len(SEGMENT_COMPONENTS) * len(SEGMENT_METRICS) * 3
    assert set(segment["scenario"]) == {"low", "base", "high"}
    property_sales = segment.loc[
        segment["component"].eq("property_sales")
        & segment["metric"].eq("segment_revenue")
        & segment["scenario"].eq("base")
    ].iloc[0]
    assert property_sales["anchor_fiscal_year_end"] == "2025-06-30"
    assert property_sales["anchor_h1_hkd_m"] == 2544.0
    assert property_sales["anchor_fy_hkd_m"] == 10920.0
    assert property_sales["fy_forecast_hkd_m"] > property_sales["h1_actual_hkd_m"]
    assert "Do not sum these rows" in property_sales["caveat"]

    scope_guard = quality.loc[
        quality["check_name"].eq("segment_scope_mismatch_guard")
    ].iloc[0]
    assert scope_guard["status"] == "pass"
    assert quality["status"].ne("fail").all()


def test_h1_nowcast_no_persist_returns_metadata_only():
    result = run_sino_land_h1_nowcast(persist=False)

    assert result["ticker"] == "0083.HK"
    assert result["nowcast_rows"] == 6
    assert result["segment_scenario_rows"] == 36
    assert result["model_fit_performed"] is False
    assert result["research_only"] is True
    assert result["normalized"] == {}


def test_h1_backtest_matches_h1_to_next_fy_without_mixing_segment_scope():
    facts = build_sino_land_financial_facts()
    h1_history = facts.loc[facts["period_end"].eq("2024-12-31")].copy()

    result = build_sino_land_h1_backtest(h1_history, facts)
    backtest = result["backtest"]
    quality = result["quality"]

    group = backtest.loc[backtest["backtest_scope"].eq("consolidated_group")]
    segments = backtest.loc[backtest["backtest_scope"].eq("operating_segment")]
    assert len(group) == 3
    assert len(segments) == len(SEGMENT_COMPONENTS) * len(SEGMENT_METRICS)
    assert backtest["backtest_id"].is_unique
    revenue = group.loc[group["metric"].eq("consolidated_revenue")].iloc[0]
    assert revenue["fiscal_year_end"] == "2025-06-30"
    assert revenue["h1_actual_hkd_m"] == 3854.0
    assert revenue["actual_fy_hkd_m"] == 8183.0
    assert revenue["forecast_fy_hkd_m"] == 7708.0
    assert revenue["model_name"] == "naive_2x_h1"
    assert quality.loc[
        quality["check_name"].eq("backtest_scope_guard"), "status"
    ].iloc[0] == "pass"
    assert BACKTEST_DATASET == "sino_land_h1_backtest"


def test_h1_backtest_adds_prior_share_benchmark_only_after_prior_pairs_exist():
    facts = build_sino_land_financial_facts()
    template = facts.loc[
        facts["period_end"].eq("2024-12-31")
        & facts["metric"].isin(
            [
                "consolidated_revenue",
                "underlying_profit_attributable",
                "profit_attributable",
            ]
        )
    ].copy()
    # Create three historical H1 pairs using the same schema; the annual
    # targets are real official FY2023-FY2025 facts from the fixture.
    history_rows = []
    for period_end, multiplier in (
        ("2022-12-31", 0.8),
        ("2023-12-31", 0.9),
        ("2024-12-31", 1.0),
    ):
        period_rows = template.copy()
        period_rows["period_end"] = period_end
        period_rows["fact_id"] = period_rows["fact_id"].astype(str) + ":" + period_end
        period_rows["value"] = period_rows["value"] * multiplier
        history_rows.append(period_rows)
    h1_history = pd.concat(history_rows, ignore_index=True)

    result = build_sino_land_h1_backtest(h1_history, facts)
    backtest = result["backtest"]
    prior = backtest.loc[
        backtest["model_name"].eq("prior_h1_share_median")
    ]

    assert len(prior) == 2 * 3  # FY2024 and FY2025, three group metrics each
    assert prior["source_fact_ids"].str.len().gt(0).all()
    assert prior["backtest_id"].is_unique
    coverage = result["quality"].loc[
        result["quality"]["check_name"].eq("prior_h1_share_backtest_coverage")
    ].iloc[0]
    assert coverage["observed_value"] == 6
    assert coverage["status"] == "warn"  # fixture has only two eligible target years


def test_residential_h2_scenario_excludes_post_h1_sale_cohorts():
    schedule = pd.DataFrame(
        [
            {
                "srpe_development_id": "100",
                "project_label": "Example Phase",
                "sale_period": "2025-11-01",
                "contract_units_gross": 10,
                "contract_sales_value_gross_hkd": 1_000_000_000,
                "recognized_period_low": "2026-01-01",
                "recognized_period_base": "2026-02-01",
                "recognized_period_high": "2026-03-01",
                "attributable_contract_value_low_hkd": 500_000_000,
                "attributable_contract_value_base_hkd": 750_000_000,
                "attributable_contract_value_high_hkd": 1_000_000_000,
            },
            {
                "srpe_development_id": "100",
                "project_label": "Example Phase",
                "sale_period": "2026-01-01",  # must be excluded at H1 cutoff
                "contract_units_gross": 20,
                "contract_sales_value_gross_hkd": 2_000_000_000,
                "recognized_period_low": "2026-02-01",
                "recognized_period_base": "2026-03-01",
                "recognized_period_high": "2026-04-01",
                "attributable_contract_value_low_hkd": 1_000_000_000,
                "attributable_contract_value_base_hkd": 1_500_000_000,
                "attributable_contract_value_high_hkd": 2_000_000_000,
            },
        ]
    )

    result = build_sino_land_h1_residential_h2_scenario(
        schedule,
        latest_h1_period_end="2025-12-31",
        target_fiscal_year_end="2026-06-30",
    )
    scenario = result["scenario"]
    portfolio = scenario.loc[scenario["scope_level"].eq("portfolio")]

    assert set(portfolio["scenario"]) == {"low", "base", "high"}
    base = portfolio.loc[portfolio["scenario"].eq("base")].iloc[0]
    assert base["cohort_rows"] == 1
    assert base["cohort_units_gross"] == 10
    assert base["contract_value_gross_hkd_m"] == 1000.0
    assert base["attributable_contract_value_hkd_m"] == 750.0
    assert base["pit_quality"] == "h1_cutoff_filtered_research_only"
    assert result["quality"]["status"].ne("fail").all()
    assert RESIDENTIAL_H2_DATASET == "sino_land_h1_residential_h2_scenario"
