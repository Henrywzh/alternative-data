import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "apps/asia-markets-dashboard/scripts/build_hk_population_migration_artifact.py"
)
SPEC = importlib.util.spec_from_file_location("hk_population_migration_dashboard_export", SCRIPT_PATH)
dashboard_export = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = dashboard_export
SPEC.loader.exec_module(dashboard_export)


NOW = datetime(2026, 7, 30, 12, tzinfo=timezone.utc)


def _inputs():
    return {
        "raw_immd": pd.DataFrame(
            {
                "date": ["2026-07-28", "2026-07-29"],
                "hk_resident_net_flow": [-100, 250],
                "mainland_visitor_net_retention": [300, 400],
                "hk_resident_departures_7d_ma": [1_000, 1_100],
                "mainland_visitor_arrivals_7d_ma": [2_000, 2_100],
            }
        ),
        "raw_pop": pd.DataFrame(
            {
                "period": ["2025-06", "2025-12"],
                "mid_year_population_thousands": [7_520, 7_540],
                "natural_growth_thousands": [-5, -3],
                "net_movement_thousands": [20, 25],
            }
        ),
        "raw_mpfa": pd.DataFrame({"quarter": ["2025-Q4", "2026-Q1"], "claims_count": [100, 110], "amount_mhkd": [300, 320]}),
        "raw_ugc": pd.DataFrame(
            {
                "academic_year": ["2024/25", "2025/26"],
                "mainland_students": [10_000, 11_000],
                "other_non_local_students": [2_000, 2_200],
                "total_non_local": [12_000, 13_200],
            }
        ),
        "raw_td": pd.DataFrame(
            {
                "month": ["2026-04", "2026-05"],
                "hzmb_vehicular_traffic": [10_000, 11_000],
                "hzmb_northbound_hk_vehicles": [1_000, 1_200],
                "express_rail_passengers": [100_000, 110_000],
            }
        ),
    }


def _build(**overrides):
    inputs = _inputs()
    inputs.update(overrides)
    return dashboard_export.build_artifact(now=NOW, **inputs)


def test_comparison_charts_use_long_series_datasets_for_every_promised_measure():
    artifact, _ = _build()
    charts = {chart["id"]: chart for chart in artifact["manifest"]["charts"]}
    datasets = artifact["snapshot"]["datasets"]

    expected = {
        "immd_net_flow_chart": {"HK Resident Net Flow", "Mainland Visitor Net Retention"},
        "csd_population_chart": {"Population", "Net Movement"},
        "ugc_students_chart": {"Mainland Students", "Other Non-local Students"},
        "td_cross_border_chart": {"Northbound HK Vehicles", "Express Rail Passengers"},
    }
    for chart_id, series in expected.items():
        chart = charts[chart_id]
        assert chart["encodings"]["y"]["field"] == "value"
        assert chart["encodings"]["color"]["field"] == "series"
        assert {row["series"] for row in datasets[chart["dataset"]]} == series

    assert charts["mpfa_claims_chart"]["encodings"]["y"]["field"] == "amount_mhkd"
    claims_chart = charts["mpfa_claims_count_chart"]
    assert claims_chart["encodings"]["y"]["field"] == "claims_count"


def test_status_uses_each_source_latest_observation_and_degrades_when_any_required_feed_is_empty():
    artifact, status = _build(raw_td=pd.DataFrame())

    latest = {row["dataset"]: row["latest_observation"] for row in status["sources"]}
    assert latest == {
        "immd": "2026-07-29",
        "csd": "2025-12",
        "mpfa": "2026-Q1",
        "ugc": "2025/26",
        "td": "—",
    }
    assert status["overall_status"] == "Degraded"
    assert artifact["manifest"]["dataAsOf"] == "2026-07-29"
    assert artifact["package_info"]["dataAsOf"] == "2026-07-29"


def test_builder_does_not_fetch_when_explicit_offline_inputs_are_supplied(monkeypatch):
    def fail_fetch():
        raise AssertionError("network fetch should not be called for supplied normalized inputs")

    monkeypatch.setattr(dashboard_export, "fetch_immd_daily_traffic", fail_fetch)
    monkeypatch.setattr(dashboard_export, "fetch_csd_population_estimates", fail_fetch)
    monkeypatch.setattr(dashboard_export, "fetch_mpfa_permanent_departure_claims", fail_fetch)
    monkeypatch.setattr(dashboard_export, "fetch_ugc_nonlocal_students", fail_fetch)
    monkeypatch.setattr(dashboard_export, "fetch_td_cross_border_traffic", fail_fetch)
    artifact, status = _build()
    assert artifact["snapshot"]["status"] == "ready"
    assert status["overall_status"] == "Healthy"


def test_builder_prefers_normalized_inputs_before_network_fetch(monkeypatch):
    normalized = _inputs()
    by_dataset = {
        "immd_daily_traffic": normalized["raw_immd"],
        "csd_population_estimates": normalized["raw_pop"],
        "mpfa_departure_claims": normalized["raw_mpfa"],
        "ugc_nonlocal_students": normalized["raw_ugc"],
        "td_cross_border_traffic": normalized["raw_td"],
    }
    monkeypatch.setattr(dashboard_export, "load_latest_normalized", lambda dataset: by_dataset.get(dataset, pd.DataFrame()))
    monkeypatch.setattr(dashboard_export, "fetch_immd_daily_traffic", lambda: (_ for _ in ()).throw(AssertionError("unexpected fetch")))
    monkeypatch.setattr(dashboard_export, "fetch_csd_population_estimates", lambda: (_ for _ in ()).throw(AssertionError("unexpected fetch")))
    monkeypatch.setattr(dashboard_export, "fetch_mpfa_permanent_departure_claims", lambda: (_ for _ in ()).throw(AssertionError("unexpected fetch")))
    monkeypatch.setattr(dashboard_export, "fetch_ugc_nonlocal_students", lambda: (_ for _ in ()).throw(AssertionError("unexpected fetch")))
    monkeypatch.setattr(dashboard_export, "fetch_td_cross_border_traffic", lambda: (_ for _ in ()).throw(AssertionError("unexpected fetch")))

    artifact, status = dashboard_export.build_artifact(now=NOW)
    assert artifact["manifest"]["dataAsOf"] == "2026-07-29"
    assert status["overall_status"] == "Healthy"
