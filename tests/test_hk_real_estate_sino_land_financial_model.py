import pandas as pd

from src.hk_real_estate.sino_land_financial_model import (
    SINO_LAND_TICKER,
    SINO_OFFICIAL_FACT_COLUMNS,
    build_sino_land_financial_facts,
    build_sino_land_financial_model_inputs,
    build_sino_land_financial_quality,
    build_sino_land_project_reconciliation,
    run_sino_land_financial_model,
)


def test_official_facts_keep_scope_and_provenance_separate():
    facts = build_sino_land_financial_facts()

    assert list(facts.columns) == SINO_OFFICIAL_FACT_COLUMNS
    assert facts["ticker"].eq(SINO_LAND_TICKER).all()
    assert not facts["fact_id"].duplicated().any()
    assert facts[["source_url", "source_page", "available_at"]].notna().all().all()

    fy2025_sales = facts.loc[
        facts["period_end"].eq("2025-06-30")
        & facts["metric"].eq("reported_property_sales_activity_revenue")
    ].iloc[0]
    assert fy2025_sales["value"] == 10813.0
    assert fy2025_sales["geography_scope"] == "group_all_geographies"
    assert "not Hong Kong-only" in fy2025_sales["caveat"]

    h1_hk = facts.loc[
        facts["period_end"].eq("2025-12-31")
        & facts["metric"].eq("consolidated_external_revenue_by_geography")
        & facts["geography_scope"].eq("hong_kong")
    ].iloc[0]
    assert h1_hk["value"] == 4488.0

    fy2025_combined = facts.loc[
        facts["period_end"].eq("2025-06-30")
        & facts["metric"].eq("external_revenue_by_geography")
        & facts["geography_scope"].eq("mainland_china_and_hong_kong")
    ].iloc[0]
    assert fy2025_combined["value"] == 7147.0
    assert "not a Hong Kong-only" in fy2025_combined["caveat"]


def test_project_reconciliation_is_diagnostic_and_never_accounting_revenue():
    facts = build_sino_land_financial_facts()
    schedule = pd.DataFrame(
        [
            {
                "recognized_period_low": "2025-04-01",
                "recognized_period_base": "2025-06-01",
                "recognized_period_high": "2025-08-01",
                "attributable_contract_value_low_hkd": 100_000_000,
                "attributable_contract_value_base_hkd": 120_000_000,
                "attributable_contract_value_high_hkd": 150_000_000,
            }
        ]
    )
    reconciliation = build_sino_land_project_reconciliation(schedule, facts)

    row = reconciliation.loc[
        reconciliation["fiscal_year_end"].eq("2025-06-30")
        & reconciliation["reported_metric"].eq(
            "reported_property_sales_activity_revenue"
        )
    ].iloc[0]
    assert row["bridge_schedule_rows"] == 1
    assert row["bridge_value_base_hkd_m"] == 120.0
    assert bool(row["research_only"]) is True
    assert row["model_use"] == "research_only_diagnostic_not_accounting_reconciliation"


def test_quality_flags_global_scope_and_source_conflicts():
    facts = build_sino_land_financial_facts()
    actuals = pd.DataFrame(
        [
            {
                "metric": "revenue",
                "period_end": "2025-06-30",
                "period_type": "annual",
                "source": "akshare",
                "value": 100.0,
                "announcement_date": None,
            },
            {
                "metric": "revenue",
                "period_end": "2025-06-30",
                "period_type": "annual",
                "source": "yfinance",
                "value": 110.0,
                "announcement_date": None,
            },
        ]
    )
    quality = build_sino_land_financial_quality(facts, actuals, pd.DataFrame())

    scope = quality.loc[quality["check_name"].eq("hk_scope_guard")].iloc[0]
    assert scope["status"] == "warn"
    conflicts = quality.loc[quality["check_name"].eq("source_overlap_conflicts")].iloc[
        0
    ]
    assert conflicts["observed_value"] == 1
    assert conflicts["status"] == "warn"


def test_build_inputs_can_run_without_financial_data():
    inputs = build_sino_land_financial_model_inputs(
        load_financial_data=False,
        bridge_schedule=pd.DataFrame(),
    )

    assert inputs["official_facts"].shape[0] > 100
    assert inputs["financial_data_actuals"].empty
    assert inputs["consensus"].empty
    assert not inputs["project_reconciliation"].empty
    assert not inputs["quality"].empty


def test_run_financial_model_can_refresh_official_facts_without_sibling_db():
    result = run_sino_land_financial_model(
        persist=False,
        load_financial_data=False,
        bridge_schedule=pd.DataFrame(),
    )

    assert result["official_fact_rows"] == 176
    assert result["actual_rows"] == 0
    assert result["consensus_rows"] == 0
