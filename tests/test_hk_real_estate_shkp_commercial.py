import pandas as pd

from src.hk_real_estate.shkp_commercial import (
    build_shkp_commercial_market_context,
    build_shkp_commercial_pipeline_capacity,
    build_shkp_commercial_recurring_coverage,
    build_shkp_commercial_recurring_facts,
    build_shkp_mainland_project_coverage_audit,
)


def test_commercial_facts_keep_period_grain_and_exclude_capacity_rows():
    source = pd.DataFrame([
        {
            "fact_id": "office-revenue",
            "ticker": "0016.HK",
            "report_id": "r1",
            "period_start": "2024-07-01",
            "period_end": "2025-06-30",
            "period_type": "annual",
            "geography": "hong_kong",
            "segment": "property_rental",
            "asset_class": "office",
            "metric": "revenue",
            "value": 100.0,
            "unit": "HKD_m",
            "currency": "HKD",
        },
        {
            "fact_id": "office-gfa",
            "ticker": "0016.HK",
            "report_id": "r1",
            "period_start": "2024-07-01",
            "period_end": "2025-06-30",
            "period_type": "annual",
            "geography": "hong_kong",
            "segment": "property_rental",
            "asset_class": "office",
            "metric": "completed_gfa",
            "value": 1.0,
            "unit": "million_sqft",
            "currency": None,
        },
    ])
    facts = build_shkp_commercial_recurring_facts(source)
    assert len(facts) == 1
    assert facts.iloc[0]["commercial_asset_class"] == "office"
    assert facts.iloc[0]["coverage_status"] == "group_period_facts_available_not_asset_level"


def test_commercial_pipeline_is_capacity_only():
    source = pd.DataFrame([
        {
            "asset_id": "a1",
            "asset_name": "Example Mall",
            "asset_class": "retail",
            "metric": "gross_gfa",
            "value": 100000,
            "unit": "sqft",
        },
        {
            "asset_id": "a2",
            "asset_name": "Example Residential",
            "asset_class": "residential",
            "metric": "gross_gfa",
            "value": 200000,
            "unit": "sqft",
        },
    ])
    pipeline = build_shkp_commercial_pipeline_capacity(source)
    assert len(pipeline) == 1
    assert pipeline.iloc[0]["commercial_asset_class"] == "retail"
    assert pipeline.iloc[0]["coverage_status"] == "pipeline_capacity_only"


def test_commercial_coverage_distinguishes_market_from_company_assets():
    facts = build_shkp_commercial_recurring_facts(pd.DataFrame([
        {
            "fact_id": "f1",
            "ticker": "0016.HK",
            "report_id": "r1",
            "period_start": "2024-07-01",
            "period_end": "2025-06-30",
            "period_type": "annual",
            "geography": "hong_kong",
            "segment": "property_rental",
            "asset_class": "retail",
            "metric": "revenue",
            "value": 100.0,
            "unit": "HKD_m",
            "currency": "HKD",
        },
    ]))
    coverage = build_shkp_commercial_recurring_coverage(
        property_catalog=pd.DataFrame([{"asset_type": "shopping_mall", "marketing_name": "Mall A"}]),
        recurring_facts=facts,
        completed_properties=pd.DataFrame(),
        pipeline_capacity=pd.DataFrame(),
        office_index=pd.DataFrame(),
        retail_index=pd.DataFrame([
            {"date": "2025-01-01", "metric": "rental_index", "value": 100.0},
        ]),
    )
    assert set(coverage["coverage_scope"]) == {
        "issuer_asset_catalog",
        "recurring_period_facts",
        "market_context_index",
    }
    assert coverage["coverage_id"].is_unique
    market = coverage.loc[coverage["coverage_scope"].eq("market_context_index")].iloc[0]
    assert market["coverage_status"] == "market_context_available_not_shkp_asset"


def test_mainland_audit_does_not_treat_hk_srpe_signals_as_mainland_sales():
    audit = build_shkp_mainland_project_coverage_audit(
        annual_report_projects=pd.DataFrame([
            {
                "geography": "Mainland",
                "project_label": "Mainland Phase 1",
                "report_period_end": "2025-06-30",
                "attributable_gfa_sqft": 100000,
            },
        ]),
        historical_annual_report_projects=pd.DataFrame(),
        recurring_facts=pd.DataFrame([
            {
                "geography": "mainland",
                "period_start": "2024-07-01",
                "period_end": "2025-06-30",
                "metric": "revenue",
                "value": 50,
            },
        ]),
        disclosed_facts=pd.DataFrame([
            {
                "metric": "mainland_contract_sales_yet_to_be_recognized",
                "period_end": "2025-06-30",
                "value": 100,
            },
        ]),
        project_month_signals=pd.DataFrame([
            {"phase_id": "hk-1", "period": "2025-01-01", "sales_value_gross_hkd": 100},
        ]),
        planning_crosswalk=pd.DataFrame(),
        landsd_consent_facts=pd.DataFrame(),
        landsd_monthly_observations=pd.DataFrame(),
        tpb_application_facts=pd.DataFrame(),
    )
    annual = audit.loc[audit["coverage_scope"].eq("current_annual_report_projects")].iloc[0]
    signals = audit.loc[audit["coverage_scope"].eq("mainland_project_month_transactions")].iloc[0]
    backlog = audit.loc[audit["coverage_scope"].eq("mainland_disclosed_backlog_and_land_bank")].iloc[0]
    assert annual["distinct_project_count"] == 1
    assert annual["project_level_sales_status"] == "not_available"
    assert signals["source_rows"] == 0
    assert signals["coverage_status"] == "not_covered"
    assert backlog["project_level_sales_status"] == "aggregate_backlog_only"


def test_market_context_preserves_office_and_retail_source_labels():
    market = build_shkp_commercial_market_context(
        pd.DataFrame([{"date": "2025-01-01", "value": 1}]),
        pd.DataFrame([{"date": "2025-01-01", "value": 2}]),
    )
    assert set(market["commercial_asset_class"]) == {"office", "retail"}
    assert set(market["coverage_status"]) == {"market_context_available_not_shkp_asset"}


def test_commercial_transmission_and_backtest():
    """Portfolio-level transmission + walk-forward backtest run end to end."""
    from src.hk_real_estate.shkp_commercial_model import (
        SHKP_HK_RENTAL_REVENUE_HKD_M,
        build_shkp_commercial_backtest,
        build_shkp_commercial_transmission,
    )
    import numpy as np
    # Build a minimal market-context frame: office + retail monthly index 2014-2026
    dates = pd.date_range("2014-01-01", "2026-05-01", freq="MS")
    rows = []
    for d in dates:
        rows.append({"date": d, "commercial_asset_class": "office", "segment": "overall", "metric": "rental_index", "value": 150 + d.year})
        rows.append({"date": d, "commercial_asset_class": "office", "segment": "grade_a", "metric": "rental_index", "value": 160 + d.year})
        rows.append({"date": d, "commercial_asset_class": "retail", "segment": "rents", "metric": "rental_index", "value": 130 + d.year})
    mc = pd.DataFrame(rows)
    trans = build_shkp_commercial_transmission(mc)
    assert not trans.empty
    assert set(trans["segment"]) == {"office", "office_grade_a", "retail"}
    assert set(trans["horizon"]) == {"contemporaneous", "distributed_lag_1y", "stability_drop_2021"}
    bt = build_shkp_commercial_backtest(mc)
    assert not bt.empty
    assert set(bt["method"]) == {"contemporaneous", "distributed_lag", "naive_flat"}
    assert len(SHKP_HK_RENTAL_REVENUE_HKD_M) == 16
