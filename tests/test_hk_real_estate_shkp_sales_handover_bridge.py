import pandas as pd

from src.hk_real_estate.shkp_sales_handover_bridge import (
    ANNUAL_COLUMNS,
    PHASE_COLUMNS,
    build_shkp_sales_handover_revenue_annual,
    build_shkp_sales_handover_revenue_bridge,
    build_shkp_sales_handover_revenue_coverage,
)


def _signals() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "srpe_development_id": "10045",
                "development_name": "NOVO LAND",
                "phase_name": "NOVO LAND",
                "signal_scope": "current_candidate_signal",
                "period": "2025-06-01",
                "sales_units_gross": 4,
                "sales_value_gross_hkd": 40_000_000,
                "active_units_eom": 8,
                "cumulative_unique_active_units": 8,
                "indicative_ownership_pct": 100,
                "indicative_attribution_status": "indicative_numeric_snapshot",
                "indicative_confidence": "medium",
            },
            {
                "srpe_development_id": "10045",
                "development_name": "NOVO LAND",
                "phase_name": "NOVO LAND",
                "signal_scope": "current_candidate_signal",
                "period": "2025-07-01",
                "sales_units_gross": 10,
                "sales_value_gross_hkd": 100_000_000,
                "active_units_eom": 10,
                "cumulative_unique_active_units": 10,
                "indicative_ownership_pct": 100,
                "indicative_attribution_status": "indicative_numeric_snapshot",
                "indicative_confidence": "medium",
            },
            {
                "srpe_development_id": "10045",
                "development_name": "NOVO LAND",
                "phase_name": "NOVO LAND",
                "signal_scope": "current_candidate_signal",
                "period": "2025-08-01",
                "sales_units_gross": 0,
                "sales_value_gross_hkd": 0,
                "active_units_eom": 10,
                "cumulative_unique_active_units": 10,
                "indicative_ownership_pct": 100,
                "indicative_attribution_status": "indicative_numeric_snapshot",
                "indicative_confidence": "medium",
            },
            # A trailing parser-gap row must not erase the last usable active
            # unit snapshot.
            {
                "srpe_development_id": "10045",
                "development_name": "NOVO LAND",
                "phase_name": "NOVO LAND",
                "signal_scope": "current_candidate_signal",
                "period": "2025-09-01",
                "sales_units_gross": pd.NA,
                "sales_value_gross_hkd": pd.NA,
                "active_units_eom": pd.NA,
                "cumulative_unique_active_units": pd.NA,
                "indicative_ownership_pct": 100,
                "indicative_attribution_status": "indicative_numeric_snapshot",
                "indicative_confidence": "medium",
            },
        ]
    )


def test_bridge_keeps_sales_handover_and_revenue_semantics_separate():
    phase = build_shkp_sales_handover_revenue_bridge(
        _signals(),
        completion_schedule=pd.DataFrame(
            [
                {
                    "srpe_development_id": "10045",
                    "schedule_date": "2025-02-28",
                    "completion_window": "FY2025/26",
                    "match_status": "ambiguous",
                    "ownership_status": "schedule_numeric_reported",
                    "group_interest_pct": 100,
                    "source_url": "https://example.com/completion.pdf",
                }
            ]
        ),
        annual_crosswalk=pd.DataFrame(
            [
                {
                    "srpe_development_id": "10045",
                    "report_period_end": "2025-06-30",
                    "project_state": "handover_completed",
                    "match_status": "ambiguous",
                    "annual_document_url": "https://example.com/annual.pdf",
                }
            ]
        ),
        bd_crosswalk=pd.DataFrame(
            [
                {
                    "srpe_development_id": "10045",
                    "bd_permit_stage": "Occupation Permits (OP) Issued",
                    "bd_permit_number": "NT1/2025/OP",
                    "bd_domestic_units_count": 12,
                    "bd_source_url": "https://example.com/bd",
                }
            ]
        ),
        disclosed_facts=pd.DataFrame(
            [
                {
                    "metric": "property_sales_revenue_including_jv_associates",
                    "period_end": "2025-06-30",
                    "value": 34_556,
                    "source_url": "https://example.com/financials",
                }
            ]
        ),
    )

    assert list(phase.columns) == PHASE_COLUMNS
    row = phase.iloc[0]
    assert row["active_units_latest"] == 10
    assert row["sales_months_missing_inside_window"] == 0
    assert row["last_nonzero_sales_period"] == "2025-07-01"
    assert row["handover_disclosure_status"] == "observed_annual_handover_completed"
    assert row["completion_window"] == "FY2025/26"
    assert row["bd_occupation_status"] == "current_bd_occupation_permit_snapshot"
    assert row["bd_occupation_permit_count"] == 1
    assert row["revenue_anchor_status"] == "company_annual_property_sales_only_not_phase_allocated"
    assert row["bridge_status"].startswith("sales_observed_handover_disclosure")
    assert row["model_use"] == "timing_bridge_only_research"

    annual = build_shkp_sales_handover_revenue_annual(
        _signals(), phase, pd.DataFrame(
            [
                {
                    "metric": "property_sales_revenue_including_jv_associates",
                    "period_end": "2025-06-30",
                    "value": 34_556,
                    "source_url": "https://example.com/financials",
                }
            ]
        )
    )
    assert list(annual.columns) == ANNUAL_COLUMNS
    annual_row = annual.loc[annual["fiscal_year_end"].eq(2026)].iloc[0]
    assert annual_row["sales_value_gross_hkd"] == 100_000_000
    revenue_row = annual.loc[annual["fiscal_year_end"].eq(2025)].iloc[0]
    assert revenue_row["disclosed_property_sales_revenue_hkd_m"] == 34_556
    assert revenue_row["gross_sales_to_property_revenue_ratio_pct"] > 0
    assert revenue_row["revenue_anchor_status"] == "company_annual_anchor_not_phase_allocated"

    coverage = build_shkp_sales_handover_revenue_coverage(phase, annual)
    assert coverage["phase_revenue_allocated_count"].eq(0).all()
    assert coverage["data_quality_status"].eq("usable_for_timing_monitoring_not_revenue_model").all()


def test_empty_bridge_is_schema_stable():
    phase = build_shkp_sales_handover_revenue_bridge(pd.DataFrame())
    annual = build_shkp_sales_handover_revenue_annual(pd.DataFrame(), phase)
    coverage = build_shkp_sales_handover_revenue_coverage(phase, annual)
    assert list(phase.columns) == PHASE_COLUMNS
    assert list(annual.columns) == ANNUAL_COLUMNS
    assert coverage.empty
