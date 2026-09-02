import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "apps/asia-markets-dashboard/scripts/build_hk_real_estate_artifact.py"
)
SPEC = importlib.util.spec_from_file_location("hk_real_estate_dashboard_export", SCRIPT_PATH)
dashboard_export = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = dashboard_export
SPEC.loader.exec_module(dashboard_export)


NOW = datetime(2026, 7, 22, 12, tzinfo=timezone.utc)


def _frame(dates, column, base, step, *, provisional=False):
    result = pd.DataFrame(
        {
            "date": [date.strftime("%Y-%m-%d") for date in dates],
            column: [base + index * step for index in range(len(dates))],
        }
    )
    if provisional:
        result["is_provisional"] = False
        result.loc[result.index[-1], "is_provisional"] = True
    return result


def _frames():
    weekly_ccl = pd.date_range(end="2026-07-19", periods=1_100, freq="W-SUN")
    weekly_mhpi = pd.date_range(end="2026-07-20", periods=450, freq="W-MON")
    weekly_confidence = pd.date_range(end="2026-07-20", periods=350, freq="W-MON")
    monthly = pd.date_range(end="2026-06-01", periods=360, freq="MS")
    return {
        "ccl": _frame(weekly_ccl, "ccl_index", 70, 0.05),
        "mhpi": _frame(weekly_mhpi, "mhpi_overall", 100, 0.04),
        "confidence": _frame(weekly_confidence, "confidence_index", 45, 0.02),
        "rvd_price": _frame(monthly, "overall", 120, 0.3, provisional=True),
        "rvd_rent": _frame(monthly, "overall", 90, 0.2, provisional=True),
    }


def _hkma_frame(n=6):
    dates = pd.date_range(end="2026-06-01", periods=n, freq="MS")
    return pd.DataFrame(
        {
            "observation_date": [d.strftime("%Y-%m-%d") for d in dates],
            "new_applications_count": [10_000 + i * 50 for i in range(n)],
            "approved_loans_amount_mhkd": [30_000 + i * 100 for i in range(n)],
            "approved_primary_presales_amount_mhkd": [8_000 + i * 20 for i in range(n)],
            "approved_secondary_amount_mhkd": [15_000 + i * 30 for i in range(n)],
            "approved_refinancing_amount_mhkd": [5_000 + i * 10 for i in range(n)],
            "drawn_down_amount_mhkd": [25_000 + i * 80 for i in range(n)],
            "average_ltv_ratio_pct": [55.0 + i * 0.1 for i in range(n)],
            "hibor_pricing_pct_share": [70.0 + i for i in range(n)],
            "blr_pricing_pct_share": [10.0 - i * 0.1 for i in range(n)],
            "fixed_pricing_pct_share": [20.0 - i * 0.9 for i in range(n)],
            "delinquency_ratio_pct": [0.03 + i * 0.001 for i in range(n)],
            "rescheduled_loan_ratio_pct": [0.0 for _ in range(n)],
        }
    )


def _cnsd_frame(n=8):
    dates = pd.date_range(end="2026-03-31", periods=n, freq="QE")
    return pd.DataFrame(
        {
            "period": [f"{d.year}-Q{(d.month - 1) // 3 + 1}" for d in dates],
            "value": [50_000 + i * 500 for i in range(n)],
            "unit": ["HK$ million"] * n,
        }
    )


def test_build_artifact_is_source_backed_and_deterministic():
    # build_artifact() falls through to a live network fetch for any of these
    # six raw_* params left as None (raw_land_disposals, raw_epi_eri,
    # raw_new_projects, raw_bd_supply, raw_landreg, raw_bd_monthly_stats) --
    # pin them to fixed empty inputs so this test measures the *code's*
    # determinism given fixed data, not a live site's. Without this, two
    # consecutive live fetches within the same test can legitimately return
    # different data and produce two different snapshot_id hashes with no
    # actual code regression involved.
    live_fetch_params = dict(
        raw_land_disposals=pd.DataFrame(),
        raw_epi_eri=pd.DataFrame(),
        raw_new_projects=pd.DataFrame(),
        raw_bd_supply=pd.DataFrame(),
        raw_landreg=(pd.DataFrame(), pd.DataFrame()),
        raw_bd_monthly_stats=pd.DataFrame(),
    )
    first, first_status = dashboard_export.build_artifact(
        _frames(), raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), now=NOW, **live_fetch_params
    )
    second, second_status = dashboard_export.build_artifact(
        _frames(), raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), now=NOW, **live_fetch_params
    )

    assert first_status["snapshot_id"] == second_status["snapshot_id"]
    assert first_status["data_as_of"] == "2026-07-20"
    assert first["snapshot"]["status"] == "ready"
    assert first["snapshot"]["datasets"]["kpi_ccl"][0]["latest"] > 0
    assert first["snapshot"]["datasets"]["kpi_rvd_price"][0]["is_provisional"] is True
    assert len(first["snapshot"]["datasets"]["source_health"]) == 6
    hkma_health = next(
        row for row in first["snapshot"]["datasets"]["source_health"]
        if row["source"] == dashboard_export.PUBLIC_SOURCES["hkma_mortgage"]["label"]
    )
    assert hkma_health["status"] == "Healthy"
    assert hkma_health["records"] == 6
    # 6dd3693 wired up the two sources that used to carry "Planned" (28Hse,
    # Land Registry) into live data; SRPE is the one remaining non-live
    # source, and its status has always been "Catalog only", not "Planned".
    assert any(row["status"] == "Catalog only" for row in first["snapshot"]["datasets"]["source_coverage"])


def test_rebased_series_start_at_100():
    artifact, _ = dashboard_export.build_artifact(_frames(), raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), now=NOW)
    rows = artifact["snapshot"]["datasets"]["rebased_five_year"]
    first_by_series = {}
    for row in rows:
        first_by_series.setdefault(row["series"], row["value"])
    assert set(first_by_series) == {"CCL", "MHPI", "RVD Price", "RVD Rent"}
    assert all(value == pytest.approx(100.0) for value in first_by_series.values())


def test_stage1_new_series_are_wired_into_separated_regime_and_commercial_views():
    dates = ["2026-01-01", "2026-02-01", "2026-03-01"]
    new_series = {
        "centaline_cci": pd.DataFrame({"date": dates, "series_id": ["overall"] * 3, "metric": ["price_index"] * 3, "index_value": [100, 101, 102]}),
        "centaline_cri": pd.DataFrame({"date": dates, "series_id": ["overall"] * 3, "metric": ["rental_index"] * 3, "index_value": [90, 91, 92]}),
        "centaline_cri_yield": pd.DataFrame({"date": dates, "series_id": ["overall"] * 3, "metric": ["rental_yield"] * 3, "index_value": [3.0, 3.1, 3.2]}),
        "centaline_csi": pd.DataFrame({"date": dates, "series_id": ["residential_price"] * 3, "metric": ["sentiment"] * 3, "index_value": [55, 56, 57]}),
        "rvd_office": pd.DataFrame({"date": dates, "segment": ["overall"] * 3, "metric": ["rental_index"] * 3, "value": [110, 111, 112], "is_provisional": [False] * 3}),
        "rvd_retail": pd.DataFrame({"date": dates, "segment": ["overall"] * 3, "metric": ["rental_index"] * 3, "value": [105, 106, 107], "is_provisional": [False] * 3}),
    }
    artifact, _ = dashboard_export.build_artifact(
        _frames(), raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), raw_new_series=new_series, now=NOW
    )
    datasets = artifact["snapshot"]["datasets"]
    assert len(datasets["cci_history"]) == 3
    assert len(datasets["cri_history"]) == 3
    assert len(datasets["rvd_office_history"]) == 3
    assert {row["date"] for row in datasets["cci_history"]} == {"2026-01", "2026-02", "2026-03"}
    assert all(len(row["date"]) == 7 for row in datasets["rvd_office_history"])
    assert len(datasets["residential_price_rebased"]) > 0
    assert len(datasets["residential_rent_rebased"]) > 0
    assert all(len(row["date"]) == 7 for row in datasets["residential_price_rebased"])
    block_ids = [block["id"] for block in artifact["manifest"]["blocks"]]
    assert block_ids.index("market_regime_intro") < block_ids.index("activity_financing_section") < block_ids.index("supply_commercial_section")
    assert "rebased_chart" not in block_ids


def test_srpe_project_sales_views_are_wired_and_attributable():
    srpe = pd.DataFrame(
        [
            {
                "development_id": "10045",
                "development_name": "NOVO LAND",
                "phase_name": "NOVO LAND",
                "period": "2026-06-01",
                "sales_units_gross": 10,
                "sales_value_gross_hkd": 100_000_000,
                "cancelled_units": 0,
                "cumulative_gross_units": 10,
                "cumulative_cancelled_units": 0,
                "cumulative_event_net_units": 10,
                "cumulative_unique_active_units": 10,
                "cumulative_net_units": 10,
                "total_residential_properties": 100,
                "cumulative_net_sell_through_pct": 10.0,
                "median_transaction_price_hkd": 10_000_000,
                "weighted_avg_transaction_price_hkd": 10_000_000,
                "days_since_first_pasp": 0,
                "project_id": "novo-land-phase-3b",
                "stock_code": "0016",
                "ownership_pct": 100.0,
                "srpe_development_id": "38009",
                "sales_value_attributable_hkd": 100_000_000,
                "ownership_attribution_ready": True,
                "ownership_effective_from": "2024-01-01",
                "ownership_effective_to": "2026-12-31",
                "ownership_interval_evidence_type": "approved_phase_attribution_decision",
                "ownership_attribution_decision_id": "decision:novo-3b",
                "ownership_interval_promotion_status": "approved_phase_attribution",
            },
            {
                "development_id": "7405",
                "development_name": "GRAND VICTORIA",
                "phase_name": "GRAND VICTORIA I",
                "period": "2026-06-01",
                "sales_units_gross": 4,
                "sales_value_gross_hkd": 20_000_000,
                "cancelled_units": 0,
                "cumulative_gross_units": 4,
                "cumulative_cancelled_units": 0,
                "cumulative_event_net_units": 4,
                "cumulative_unique_active_units": 4,
                "cumulative_net_units": 4,
                "total_residential_properties": 100,
                "cumulative_net_sell_through_pct": 4.0,
                "median_transaction_price_hkd": 5_000_000,
                "weighted_avg_transaction_price_hkd": 5_000_000,
                "days_since_first_pasp": 0,
                "project_id": "grand-victoria-phase-1",
                "stock_code": "0083",
                "ownership_pct": 22.5,
                "srpe_development_id": "61337",
                "sales_value_attributable_hkd": 4_500_000,
                "ownership_attribution_ready": True,
                "ownership_effective_from": "2024-01-01",
                "ownership_effective_to": "2026-12-31",
                "ownership_interval_evidence_type": "approved_phase_attribution_decision",
                "ownership_attribution_decision_id": "decision:grand-victoria",
                "ownership_interval_promotion_status": "approved_phase_attribution",
            },
        ]
    )
    artifact, _ = dashboard_export.build_artifact(
        _frames(),
        raw_hkma=_hkma_frame(),
        raw_cnsd=_cnsd_frame(),
        raw_epi_eri=pd.DataFrame(),
        raw_new_projects=pd.DataFrame(),
        raw_landreg=(pd.DataFrame(), pd.DataFrame()),
        raw_bd_monthly_stats=pd.DataFrame(),
        raw_bd_supply=pd.DataFrame(),
        raw_bd_supply_history=pd.DataFrame(),
        raw_unified_tx=pd.DataFrame(),
        raw_srpe_signals=srpe,
        now=NOW,
    )
    datasets = artifact["snapshot"]["datasets"]
    assert datasets["kpi_srpe_attributable_sales"][0]["latest"] == pytest.approx(104.5)
    assert datasets["kpi_srpe_projects"][0]["latest"] == 2
    assert {row["developer"] for row in datasets["srpe_developer_monthly_sales"]} == {
        "Sun Hung Kai Properties",
        "Sino Land",
    }
    assert next(chart for chart in artifact["manifest"]["charts"] if chart["id"] == "srpe_project_sell_through_chart")
    assert next(table for table in artifact["manifest"]["tables"] if table["id"] == "srpe_latest_project_snapshot_table")


def test_csi_weekly_history_keeps_distinct_week_dates_while_monthly_indices_stay_monthly():
    monthly_dates = ["2026-01-01", "2026-02-01"]
    weekly_dates = ["2026-01-05", "2026-01-12", "2026-01-19"]
    new_series = {
        "centaline_cci": pd.DataFrame({"date": monthly_dates, "series_id": ["overall"] * 2, "metric": ["price_index"] * 2, "index_value": [100, 101]}),
        "centaline_cri": pd.DataFrame({"date": monthly_dates, "series_id": ["overall"] * 2, "metric": ["rental_index"] * 2, "index_value": [90, 91]}),
        "centaline_cri_yield": pd.DataFrame({"date": monthly_dates, "series_id": ["overall"] * 2, "metric": ["rental_yield"] * 2, "index_value": [3.0, 3.1]}),
        "centaline_csi": pd.DataFrame({"date": weekly_dates, "series_id": ["residential_price"] * 3, "metric": ["sentiment"] * 3, "index_value": [55, 56, 57]}),
    }

    artifact, _ = dashboard_export.build_artifact(
        _frames(),
        raw_hkma=_hkma_frame(),
        raw_cnsd=_cnsd_frame(),
        raw_epi_eri=pd.DataFrame(),
        raw_new_projects=pd.DataFrame(),
        raw_landreg=(pd.DataFrame(), pd.DataFrame()),
        raw_bd_monthly_stats=pd.DataFrame(),
        raw_bd_supply=pd.DataFrame(),
        raw_bd_supply_history=pd.DataFrame(),
        raw_unified_tx=pd.DataFrame(),
        raw_new_series=new_series,
        now=NOW,
    )

    datasets = artifact["snapshot"]["datasets"]
    assert {row["date"] for row in datasets["csi_history"]} == set(weekly_dates)
    assert len({(row["date"], row["series"]) for row in datasets["csi_history"]}) == 3
    assert {row["date"] for row in datasets["cci_history"]} == {"2026-01", "2026-02"}
    chart = next(chart for chart in artifact["manifest"]["charts"] if chart["id"] == "csi_trend")
    assert chart["encodings"]["x"] == {"field": "date", "type": "temporal", "label": "Week"}


def test_new_real_estate_feeds_are_not_repeated_in_source_coverage():
    new_series = {
        "centaline_cci": pd.DataFrame({"date": ["2026-01-01"], "series_id": ["overall"], "metric": ["price_index"], "index_value": [100]}),
        "centaline_cri": pd.DataFrame({"date": ["2026-01-01"], "series_id": ["overall"], "metric": ["rental_index"], "index_value": [90]}),
        "centaline_cri_yield": pd.DataFrame({"date": ["2026-01-01"], "series_id": ["overall"], "metric": ["rental_yield"], "index_value": [3.0]}),
        "centaline_csi": pd.DataFrame({"date": ["2026-01-05"], "series_id": ["residential_price"], "metric": ["sentiment"], "index_value": [55]}),
        "rvd_office": pd.DataFrame({"date": ["2026-01-01"], "segment": ["overall"], "metric": ["rental_index"], "value": [110]}),
        "rvd_retail": pd.DataFrame({"date": ["2026-01-01"], "segment": ["overall"], "metric": ["rental_index"], "value": [105]}),
    }
    artifact, _ = dashboard_export.build_artifact(
        _frames(),
        raw_hkma=_hkma_frame(),
        raw_cnsd=_cnsd_frame(),
        raw_epi_eri=pd.DataFrame(),
        raw_new_projects=pd.DataFrame(),
        raw_landreg=(pd.DataFrame(), pd.DataFrame()),
        raw_bd_monthly_stats=pd.DataFrame(),
        raw_bd_supply=pd.DataFrame(),
        raw_bd_supply_history=pd.DataFrame(),
        raw_unified_tx=pd.DataFrame(),
        raw_new_series=new_series,
        now=NOW,
    )
    coverage = artifact["snapshot"]["datasets"]["source_coverage"]
    names = [row["source"] for row in coverage]
    for source_id in ("centaline_cci", "centaline_cri", "centaline_csi", "rvd_office", "rvd_retail"):
        assert names.count(dashboard_export.PUBLIC_SOURCES[source_id]["label"]) == 1
    csi = next(row for row in coverage if row["source"] == dashboard_export.PUBLIC_SOURCES["centaline_csi"]["label"])
    assert csi["latest_observation"] == "2026-01-05"
    assert csi["records"] == 1


def test_shkp_financial_bridge_keeps_hk_scope_and_pit_caveats():
    finance = {
        "shkp_financial_disclosed": pd.DataFrame([
            {
                "fact_group": "segment_financials",
                "metric": "property_sales_revenue_including_jv_associates",
                "value": 34_556,
                "unit": "HKD_m",
                "currency": "HKD",
                "period_end": "2025-06-30",
                "period_type": "annual",
                "attribution_scope": "company_reported_group_or_segment",
                "source_label": "SHKP annual report",
                "source_url": "https://www.shkp.com/report.pdf",
                "available_at": "2025-09-04",
                "evidence_status": "observed",
                "caveat": "Includes JV/associate shares.",
            },
            {
                "fact_group": "contracted_sales_backlog",
                "metric": "mainland_contract_sales_yet_to_be_recognized",
                "value": 8_100,
                "unit": "RMB_m",
                "currency": "RMB",
                "period_end": "2025-06-30",
                "period_type": "point_in_time_backlog",
                "source_label": "SHKP annual report",
                "source_url": "https://www.shkp.com/report.pdf",
                "available_at": "2025-09-04",
                "evidence_status": "observed",
                "caveat": "Mainland control row.",
            },
        ]),
        "shkp_financial_recurring": pd.DataFrame([
            {
                "geography": "hong_kong",
                "asset_class": "property_investment",
                "metric": "gross_rental_income",
                "value": 17_531,
                "unit": "HKD_m",
                "currency": "HKD",
                "period_end": "2025-06-30",
                "period_type": "annual",
                "scope": "portfolio",
                "source_label": "SHKP annual report",
                "source_url": "https://www.shkp.com/report.pdf",
                "availability_date": "2025-09-04",
                "evidence_status": "observed",
                "caveat": "Not asset-level rent roll.",
            },
            {
                "geography": "mainland",
                "asset_class": "property_investment",
                "metric": "gross_rental_income",
                "value": 6_173,
                "unit": "HKD_m",
                "currency": "HKD",
                "period_end": "2025-06-30",
                "period_type": "annual",
                "scope": "portfolio",
                "source_label": "SHKP annual report",
                "source_url": "https://www.shkp.com/report.pdf",
                "availability_date": "2025-09-04",
                "evidence_status": "observed",
                "caveat": "Mainland control row.",
            },
        ]),
        "shkp_financial_actuals": pd.DataFrame([
            {
                "statement_type": "income_statement",
                "metric": "revenue",
                "value": 79_721_000_000,
                "unit": "currency",
                "currency": "HKD",
                "period_end": "2025-06-30",
                "period_type": "annual",
                "source": "yfinance",
                "available_at": "2026-07-28",
                "point_in_time_quality": "low",
                "caveat": "No original announcement date.",
            },
            {
                "statement_type": "financial_indicators",
                "metric": "roe_yearly",
                "value": 3.2,
                "unit": "reported",
                "currency": "HKD",
                "period_end": "2025-06-30",
                "period_type": "annual",
                "source": "akshare",
                "available_at": "2026-07-28",
                "point_in_time_quality": "low",
            },
        ]),
        "shkp_financial_reconciliation": pd.DataFrame([
            {
                "metric": "group_revenue",
                "period_end": "2025-06-30",
                "official_value_hkd_m": 79_721,
                "financial_data_value_hkd_m": 79_721,
                "difference_pct": 0.0,
                "financial_data_source": "yfinance",
                "status": "reconciled_after_unit_normalization",
                "caveat": "Arithmetic check only.",
            },
        ]),
        "shkp_financial_consensus": pd.DataFrame([
            {
                "metric": "eps",
                "statistic": "mean",
                "value": 8.3,
                "unit": "currency_per_share",
                "currency": "HKD",
                "estimate_period_end": pd.NaT,
                "fiscal_year": 2027,
                "snapshot_date": "2026-07-26",
                "source": "akshare",
                "caveat": "Single current snapshot.",
            },
        ]),
        "shkp_financial_vintage": pd.DataFrame([
            {
                "layer": "financial_data_actuals",
                "row_count": 952,
                "period_end": "2025-12-31",
                "snapshot_end": "2026-07-28",
                "source": "financial-data",
                "status": "not_pit_safe_missing_announcement_dates",
                "point_in_time_quality": "low_missing_announcement_date",
                "model_use": "historical_context_only",
                "caveat": "Fetch-time availability only.",
            },
        ]),
        "shkp_financial_coverage": pd.DataFrame([
            {
                "disclosed_rows": 86,
                "recurring_portfolio_rows": 46,
                "financial_data_actual_rows": 952,
                "consensus_rows": 55,
                "filing_vintage_rows": 333,
                "project_bridge_rows": 3_265,
                "validation_status": "valid",
                "validation_warnings": "Actuals lack original announcement dates.",
                "last_verified_at": "2026-08-08T20:53:46Z",
            },
        ]),
    }
    artifact, _ = dashboard_export.build_artifact(
        _frames(),
        raw_hkma=_hkma_frame(),
        raw_cnsd=_cnsd_frame(),
        raw_land_disposals=pd.DataFrame(),
        raw_epi_eri=pd.DataFrame(),
        raw_new_projects=pd.DataFrame(),
        raw_landreg=(pd.DataFrame(), pd.DataFrame()),
        raw_bd_monthly_stats=pd.DataFrame(),
        raw_bd_supply=pd.DataFrame(),
        raw_bd_supply_history=pd.DataFrame(),
        raw_new_series=finance,
        now=NOW,
    )
    rows = artifact["snapshot"]["datasets"]["shkp_hk_financial_bridge"]
    assert rows
    assert not any(row.get("geography") == "mainland" for row in rows)
    assert {row["row_type"] for row in rows} == {
        "official_disclosed_fact",
        "hk_recurring_portfolio_fact",
        "financial_data_actual",
        "reconciliation",
        "consensus_snapshot",
        "vintage_diagnostic",
        "coverage_diagnostic",
    }
    actual = next(row for row in rows if row["row_type"] == "financial_data_actual")
    assert actual["value"] == pytest.approx(79_721.0)
    assert actual["unit"] == "HKD_m"
    assert actual["model_use"] == "historical_context_only"
    table = next(table for table in artifact["manifest"]["tables"] if table["id"] == "shkp_hk_financial_bridge_table")
    assert table["dataset"] == "shkp_hk_financial_bridge"
    bridge_source = next(row for row in artifact["snapshot"]["datasets"]["source_health"] if row["source"] == "SHKP — Hong Kong business financial bridge")
    assert bridge_source["status"] == "Healthy"
    assert "/Users/" not in json.dumps(artifact)


def test_artifact_contains_no_machine_local_paths_or_secrets():
    artifact, _ = dashboard_export.build_artifact(_frames(), raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), now=NOW)
    serialized = json.dumps(artifact)
    assert "/Users/" not in serialized
    assert "api_key" not in serialized.lower()
    assert ".config" not in serialized
    assert all(source.get("query", {}).get("url", "").startswith("https://") for source in artifact["sources"] if source.get("query", {}).get("url"))


def test_stale_or_duplicate_core_series_fails_closed():
    frames = _frames()
    frames["ccl"].loc[frames["ccl"].index[-1], "date"] = frames["ccl"].iloc[-2]["date"]
    with pytest.raises(ValueError, match="duplicate observation dates"):
        dashboard_export.build_artifact(frames, raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), now=NOW)


def test_rvd_price_and_rent_must_align():
    frames = _frames()
    frames["rvd_rent"].loc[frames["rvd_rent"].index[-1], "date"] = "2026-07-01"
    with pytest.raises(ValueError, match="RVD price and rent observation dates do not align"):
        dashboard_export.build_artifact(frames, raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), now=NOW)


def test_hkma_rate_mix_surfaces_other_pricing_bucket():
    hkma = _hkma_frame()
    hkma["other_pricing_pct_share"] = [0.5 + i * 0.01 for i in range(len(hkma))]
    artifact, _ = dashboard_export.build_artifact(_frames(), raw_hkma=hkma, raw_cnsd=_cnsd_frame(), now=NOW)
    rows = artifact["snapshot"]["datasets"]["hkma_mortgage_rate_mix"]
    assert {row["series"] for row in rows} == {
        "HIBOR",
        "BLR (Prime)",
        "Fixed",
        "Other",
    }


def test_core_histories_fallback_to_last_committed_artifact(monkeypatch):
    monkeypatch.setattr(dashboard_export, "load_latest_normalized", lambda _dataset: pd.DataFrame())
    monkeypatch.setattr(dashboard_export, "_safe_fetch", lambda *_args, **_kwargs: pd.DataFrame())

    hkma = dashboard_export._load_hkma_with_fallback()
    committed_activity = dashboard_export._load_dataset_from_committed_artifact("hkma_mortgage_activity")
    assert not committed_activity.empty
    assert len(hkma) == len(committed_activity)
    assert hkma["observation_date"].max() == pd.to_datetime(committed_activity["date"]).max().strftime("%Y-%m-01")
    assert hkma.attrs["dashboard_fallback_reason"] == "last committed artifact"

    bd_history = dashboard_export._load_bd_supply_history_from_committed_artifact()
    assert not bd_history.empty
    assert bd_history["observation_month"].max() == "2026-05-01"
    assert bd_history.attrs["dashboard_fallback_reason"] == "last committed artifact"


def test_build_marks_hkma_artifact_fallback_as_stale(monkeypatch):
    monkeypatch.setattr(dashboard_export, "load_latest_normalized", lambda _dataset: pd.DataFrame())
    monkeypatch.setattr(dashboard_export, "_safe_fetch", lambda *_args, **_kwargs: pd.DataFrame())
    artifact, status = dashboard_export.build_artifact(
        _frames(),
        raw_cnsd=_cnsd_frame(),
        raw_epi_eri=pd.DataFrame(),
        raw_new_projects=pd.DataFrame(),
        raw_landreg=(pd.DataFrame(), pd.DataFrame()),
        raw_bd_monthly_stats=pd.DataFrame(),
        raw_bd_supply=pd.DataFrame(),
        raw_bd_supply_history=pd.DataFrame(),
        raw_land_disposals=pd.DataFrame(),
        now=NOW,
    )
    hkma_health = next(
        row for row in artifact["snapshot"]["datasets"]["source_health"]
        if row["source"] == dashboard_export.PUBLIC_SOURCES["hkma_mortgage"]["label"]
    )
    assert hkma_health["status"] == "Stale"
    assert status["overall_status"] == "Degraded"
    committed_activity = dashboard_export._load_dataset_from_committed_artifact("hkma_mortgage_activity")
    assert len(artifact["snapshot"]["datasets"]["hkma_mortgage_activity"]) == len(committed_activity)


def test_published_real_estate_artifacts_keep_core_history_contracts():
    artifact_dir = Path(__file__).resolve().parents[1] / "apps/asia-markets-dashboard/.generated"
    required = {
        "hkma_mortgage_rate_mix_chart": "hkma_mortgage_rate_mix",
        "hkma_ltv_chart": "hkma_ltv_history",
        "hkma_credit_quality_chart": "hkma_credit_quality_history",
        "hkma_applications_chart": "hkma_applications_history",
        "hkma_loan_amount_chart": "hkma_loan_amount_history",
        "hkma_mortgage_activity_table": "hkma_mortgage_activity",
        "bd_supply_history_units_chart": "bd_supply_pipeline_history_units",
        "bd_supply_history_counts_chart": "bd_supply_pipeline_history_counts",
    }
    for path in (artifact_dir / "hk-real-estate-artifact.json", artifact_dir / "hk-real-estate-artifact-zh.json"):
        artifact = json.loads(path.read_text(encoding="utf-8"))
        manifest_items = {
            item["id"]: item
            for section in ("charts", "tables")
            for item in artifact["manifest"][section]
        }
        datasets = artifact["snapshot"]["datasets"]
        for item_id, dataset_id in required.items():
            assert item_id in manifest_items, f"{path.name} missing {item_id}"
            assert datasets.get(dataset_id), f"{path.name} has no rows for {dataset_id}"


def test_landreg_asp_chart_uses_historical_series_when_available():
    facts = pd.DataFrame(
        {
            "date": ["2026-06-01"],
            "table_id": ["t1"],
            "statistic_name": [
                "Total Number of Urban & New Territories deeds received for registration (ASP Building Units)"
            ],
            "units": [9434],
            "comparison_type": ["level"],
        }
    )
    asp = pd.DataFrame(
        {
            "date": ["2026-06-01"],
            "all_building_units_asp": [1234],
            "residential_units_asp": [1111],
        }
    )
    artifact, _ = dashboard_export.build_artifact(
        _frames(), raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), raw_landreg=(facts, asp), now=NOW
    )
    rows = artifact["snapshot"]["datasets"]["landreg_asp_history"]
    # The archive-backed ASP series is the only source with a long history;
    # current t1 facts are retained as a fallback but must not replace it.
    # (There used to be a separate landreg_volume_history dataset/chart
    # sourced from this same all_building_units_asp column under a
    # different label -- a pure duplicate of this series, now removed.)
    assert {"date": "2026-06", "series": "All Building Units ASP", "value": 1234.0} in rows
    assert {"date": "2026-06", "series": "Residential Units ASP", "value": 1111.0} in rows


def test_transaction_pulse_flags_single_agency_coverage():
    tx = pd.DataFrame(
        {
            "transaction_date": ["2026-07-20"],
            "estate_name": ["Example Estate"],
            "saleable_area_sqft": [500],
            "price_hkd": [5_000_000],
            "unit_price_hkd_sqft": [10_000],
            "primary_source_agency": ["28Hse"],
            "matched_agency_count": [1],
            "source_agencies": ["28Hse"],
        }
    )
    artifact, _ = dashboard_export.build_artifact(
        _frames(), raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), raw_unified_tx=tx, now=NOW
    )
    coverage = next(
        row for row in artifact["snapshot"]["datasets"]["source_coverage"] if row["source"] == "Agency transactions"
    )
    assert coverage["status"] == "Partial"
    assert "single agency" in coverage["notes"]
    table = next(table for table in artifact["manifest"]["tables"] if table["id"] == "agency_transactions_pulse_table")
    assert "only 28Hse" in table["subtitle"]


def test_bd_demolition_consents_are_not_rendered_as_zero_unit_supply():
    supply = pd.DataFrame(
        [
            {
                "permit_stage": "Demolition Consents",
                "region": "Hong Kong Island",
                "property_category": "Unknown",
                "total_projects_count": 2,
                "total_domestic_units": None,
                "total_usable_floor_area_sqm": None,
            },
            {
                "permit_stage": "Plans Approved",
                "region": "Hong Kong Island",
                "property_category": "Domestic",
                "total_projects_count": 1,
                "total_domestic_units": 100,
                "total_usable_floor_area_sqm": 1_000,
            },
        ]
    )
    artifact, _ = dashboard_export.build_artifact(
        _frames(),
        raw_hkma=_hkma_frame(),
        raw_cnsd=_cnsd_frame(),
        raw_bd_monthly_stats=pd.DataFrame(),
        raw_bd_supply=supply,
        now=NOW,
    )
    pipeline_rows = artifact["snapshot"]["datasets"]["bd_supply_pipeline"]
    assert pipeline_rows == [{"permit_stage": "Plans Approved", "region": "Hong Kong Island", "value": 100.0}]
    detail_rows = artifact["snapshot"]["datasets"]["bd_supply_detail"]
    demolition = next(row for row in detail_rows if row["permit_stage"] == "Demolition Consents")
    assert demolition["total_projects_count"] == 2
    assert demolition["total_domestic_units"] is None


def test_bd_history_is_a_dated_aggregate_trend_separate_from_current_snapshot():
    history = pd.DataFrame(
        [
            {
                "observation_month": "2024-12-01",
                "permit_stage": "Demolition Consents",
                "total_projects_count": 2,
                "total_domestic_units": None,
                "total_domestic_ufa_sqm": None,
                "revision_status": "as_published",
                "parser_confidence": "HIGH",
            },
            {
                "observation_month": "2024-12-01",
                "permit_stage": "Consent to Commence",
                "total_projects_count": 13,
                "total_domestic_units": 1_495,
                "total_domestic_ufa_sqm": 30_056.5,
                "revision_status": "as_published",
                "parser_confidence": "HIGH",
            },
            {
                "observation_month": "2024-12-01",
                "permit_stage": "Plans Approved",
                "total_projects_count": 14,
                "total_domestic_units": None,
                "total_domestic_ufa_sqm": None,
                "revision_status": "as_published",
                "parser_confidence": "LOW",
            },
            {
                "observation_month": "2010-01-01",
                "permit_stage": "Consent to Commence",
                "total_projects_count": 99,
                "total_domestic_units": 9_999,
                "total_domestic_ufa_sqm": 99_999,
                "revision_status": "as_published",
                "parser_confidence": "HIGH",
            },
        ]
    )
    artifact, _ = dashboard_export.build_artifact(
        _frames(),
        raw_hkma=_hkma_frame(),
        raw_cnsd=_cnsd_frame(),
        raw_bd_supply_history=history,
        now=NOW,
    )

    rows = (
        artifact["snapshot"]["datasets"]["bd_supply_pipeline_history_units"]
        + artifact["snapshot"]["datasets"]["bd_supply_pipeline_history_counts"]
    )
    assert {tuple(row.items()) for row in rows} == {
        (("date", "2024-12"), ("permit_stage", "Consent to Commence"), ("series", "Md54 Consent"), ("metric", "Domestic units"), ("value", 1495.0)),
        (("date", "2024-12"), ("permit_stage", "Consent to Commence"), ("series", "Md54 Consent"), ("metric", "Project / consent count"), ("value", 13.0)),
        (("date", "2024-12"), ("permit_stage", "Demolition Consents"), ("series", "Md52 Demolition"), ("metric", "Project / consent count"), ("value", 2.0)),
    }
    assert "bd_supply_pipeline_history" not in artifact["snapshot"]["datasets"]
    assert all(row["date"] >= "2014-12" for row in rows)
    assert not any(row["value"] == 9_999 for row in rows)
    unit_chart = next(chart for chart in artifact["manifest"]["charts"] if chart["id"] == "bd_supply_history_units_chart")
    count_chart = next(chart for chart in artifact["manifest"]["charts"] if chart["id"] == "bd_supply_history_counts_chart")
    assert unit_chart["dataset"] == "bd_supply_pipeline_history_units"
    assert count_chart["dataset"] == "bd_supply_pipeline_history_counts"
    assert unit_chart["sourceId"] == count_chart["sourceId"] == "bd_supply_history"


def test_shkp_leading_indicators_and_28hse_reconciliation_are_monitoring_only():
    leading = pd.DataFrame([
        {
            "phase_id": "1", "project_id": "shkp-srpe-1", "development_group_id": "srpe-development-1",
            "srpe_development_id": "1", "development_id": "1", "development_name": "TEST DEVELOPMENT",
            "phase_name": "PHASE 1", "period": "2026-01-01", "sales_units_gross": 10,
            "sales_value_gross_hkd": 100_000_000, "active_units_eom": 9, "published_inventory_units": 100,
            "sell_through_pct_eom": 9.0, "month_status": "observed_transactions", "candidate_status": "matched",
            "ownership_review_status": "blocked_interval_missing", "ownership_attribution_ready": False,
        },
        {
            "phase_id": "1", "project_id": "shkp-srpe-1", "development_group_id": "srpe-development-1",
            "srpe_development_id": "1", "development_id": "1", "development_name": "TEST DEVELOPMENT",
            "phase_name": "PHASE 1", "period": "2026-02-01", "sales_units_gross": 0,
            "sales_value_gross_hkd": 0, "active_units_eom": 9, "published_inventory_units": 100,
            "sell_through_pct_eom": 9.0, "month_status": "observed_zero_transactions", "candidate_status": "matched",
            "ownership_review_status": "blocked_interval_missing", "ownership_attribution_ready": False,
        },
    ])
    reconciliation = pd.DataFrame([{
        "row_side": "hse28_project", "hse28_project_name": "UNMATCHED", "srpe_development_id": None,
        "srpe_phase_name": None, "hse28_status": "開售中", "hse28_total_units": 100,
        "hse28_remaining_units": 90, "hse28_sold_units": 10, "srpe_active_units_eom": None,
        "srpe_published_inventory_units": None, "match_status": "not_matched_current_28hse_listing",
        "coverage_note": "not comparable",
    }])
    artifact, _ = dashboard_export.build_artifact(
        _frames(), raw_hkma=_hkma_frame(), raw_cnsd=_cnsd_frame(), raw_epi_eri=pd.DataFrame(),
        raw_new_projects=pd.DataFrame(), raw_landreg=(pd.DataFrame(), pd.DataFrame()),
        raw_bd_monthly_stats=pd.DataFrame(), raw_bd_supply=pd.DataFrame(), raw_bd_supply_history=pd.DataFrame(),
        raw_unified_tx=pd.DataFrame(), raw_shkp_leading_signals=leading,
        raw_28hse_reconciliation=reconciliation, raw_shkp_transaction_health=pd.DataFrame([{"srpe_development_id": "8225", "development_name": "TWENTY PEAK ROAD BY V", "situation": "situation_1_parsed", "current_event_rows": 4, "note": "recovered"}]), now=NOW,
    )
    datasets = artifact["snapshot"]["datasets"]
    assert len(datasets["shkp_leading_signal_history"]) == 2
    assert datasets["shkp_leading_phase_latest"][0]["model_use"] == "leading_indicator_only"
    assert datasets["shkp_28hse_reconciliation"][0]["match_status"] == "not_matched_current_28hse_listing"
    chart_ids = {chart["id"] for chart in artifact["manifest"]["charts"]}
    table_ids = {table["id"] for table in artifact["manifest"]["tables"]}
    block_ids = {block["id"] for block in artifact["manifest"]["blocks"]}
    assert {"shkp_leading_contract_sales_chart", "shkp_leading_active_units_chart", "shkp_leading_coverage_chart"} <= chart_ids
    assert {"shkp_leading_phase_latest_table", "shkp_28hse_reconciliation_table", "shkp_srpe_transaction_health_table"} <= table_ids
    assert {
        "shkp_leading_contract_sales_block",
        "shkp_leading_active_units_block",
        "shkp_leading_coverage_block",
        "shkp_leading_phase_latest_block",
        "shkp_28hse_reconciliation_block",
    } <= block_ids
