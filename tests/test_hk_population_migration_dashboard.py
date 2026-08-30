import importlib.util
import json
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
        "raw_mpfa": pd.DataFrame(
            {
                "quarter": ["2025-Q4", "2026-Q1"],
                "claims_count": [100, 110],
                "amount_mhkd": [300.0, 320.0],
                "source_agency": ["MPFA", "MPFA"],
            }
        ),
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
        "raw_visitor_arrivals": pd.DataFrame(
            {
                "date": ["2026-04", "2026-04", "2026-05", "2026-05"],
                "region": ["Chinese Mainland", "Europe", "Chinese Mainland", "Europe"],
                "visitors": [2_500_000, 300_000, 2_600_000, 320_000],
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
        "visitor_arrivals": "2026-05",
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
    monkeypatch.setattr(dashboard_export, "fetch_visitor_arrivals_by_region", fail_fetch)
    artifact, status = _build()
    assert artifact["snapshot"]["status"] == "ready"
    assert status["overall_status"] == "Healthy"


_BY_DATASET_KEYS = {
    "immd_daily_traffic": "raw_immd",
    "csd_population_estimates": "raw_pop",
    "mpfa_departure_claims": "raw_mpfa",
    "ugc_nonlocal_students": "raw_ugc",
    "td_cross_border_traffic": "raw_td",
    "censtatd_visitor_arrivals": "raw_visitor_arrivals",
}

_FETCHER_BY_DATASET = {
    "immd_daily_traffic": "fetch_immd_daily_traffic",
    "csd_population_estimates": "fetch_csd_population_estimates",
    "ugc_nonlocal_students": "fetch_ugc_nonlocal_students",
    "td_cross_border_traffic": "fetch_td_cross_border_traffic",
    "censtatd_visitor_arrivals": "fetch_visitor_arrivals_by_region",
}


def _monkeypatch_live_fetch_success(monkeypatch):
    """Every fetcher serves its canonical test frame; committed store is empty."""
    normalized = _inputs()
    monkeypatch.setattr(dashboard_export, "load_latest_normalized", lambda dataset: pd.DataFrame())
    monkeypatch.setattr(dashboard_export, "fetch_mpfa_permanent_departure_claims", lambda: normalized["raw_mpfa"])
    monkeypatch.setattr(dashboard_export, "_persist_mpfa_cache", lambda frame: None)
    for dataset, fetcher_name in _FETCHER_BY_DATASET.items():
        frame = normalized[_BY_DATASET_KEYS[dataset]]
        monkeypatch.setattr(dashboard_export, fetcher_name, lambda frame=frame: frame.copy())


def test_builder_fetches_live_first_and_reports_healthy_when_all_sources_succeed(monkeypatch):
    dashboard_export._fetch_status.clear()
    _monkeypatch_live_fetch_success(monkeypatch)

    artifact, status = dashboard_export.build_artifact(now=NOW)

    assert artifact["manifest"]["dataAsOf"] == "2026-07-29"
    assert status["overall_status"] == "Healthy"
    assert all(entry["status"] == "Healthy" for entry in status["sources"])


def test_builder_falls_back_to_committed_snapshot_when_live_fetch_fails(monkeypatch):
    dashboard_export._fetch_status.clear()
    normalized = _inputs()
    by_dataset = {name: normalized[key].copy() for name, key in _BY_DATASET_KEYS.items()}
    monkeypatch.setattr(dashboard_export, "load_latest_normalized", lambda dataset: by_dataset.get(dataset, pd.DataFrame()))
    monkeypatch.setattr(dashboard_export, "_fallback_state", lambda dataset: False)

    def _network_down():
        raise RuntimeError("network down")

    monkeypatch.setattr(dashboard_export, "fetch_mpfa_permanent_departure_claims", _network_down)
    for fetcher_name in _FETCHER_BY_DATASET.values():
        monkeypatch.setattr(dashboard_export, fetcher_name, _network_down)

    artifact, status = dashboard_export.build_artifact(now=NOW)

    assert artifact["manifest"]["dataAsOf"] == "2026-07-29"
    assert status["overall_status"] == "Degraded"
    by_id = {entry["dataset"]: entry for entry in status["sources"]}
    assert all(entry["status"] == "Degraded" for entry in by_id.values())
    assert all(entry["freshness"] == "Dated snapshot" for entry in by_id.values())
    assert "committed snapshot" in by_id["immd"]["notes"]


def test_builder_flags_stale_fallback_when_committed_snapshot_exceeds_max_age(monkeypatch):
    dashboard_export._fetch_status.clear()
    normalized = _inputs()
    by_dataset = {name: normalized[key].copy() for name, key in _BY_DATASET_KEYS.items()}
    monkeypatch.setattr(dashboard_export, "load_latest_normalized", lambda dataset: by_dataset.get(dataset, pd.DataFrame()))
    monkeypatch.setattr(dashboard_export, "MAX_FALLBACK_AGE_DAYS", -1)
    monkeypatch.setattr(dashboard_export, "_fallback_state", lambda dataset: True)

    def _network_down():
        raise RuntimeError("network down")

    monkeypatch.setattr(dashboard_export, "fetch_mpfa_permanent_departure_claims", _network_down)
    for fetcher_name in _FETCHER_BY_DATASET.values():
        monkeypatch.setattr(dashboard_export, fetcher_name, _network_down)

    _, status = dashboard_export.build_artifact(now=NOW)

    by_id = {entry["dataset"]: entry for entry in status["sources"]}
    assert all(entry["freshness"] == "Stale" for entry in by_id.values())
    assert "older than -1 days" in by_id["immd"]["notes"]


def test_mpfa_merge_prefers_fetched_quarters_and_fills_gaps_from_cache(monkeypatch, tmp_path):
    dashboard_export._fetch_status.clear()
    monkeypatch.setattr("src.hk_population_migration.config.NORMALIZED_DIR", tmp_path)
    fetched = pd.DataFrame(
        {
            "quarter": ["2026-Q1", "2026-Q2"],
            "claims_count": [222, 300],
            "amount_mhkd": [999.0, 610.0],
            "source_agency": ["MPFA", "MPFA"],
        }
    )
    cache = pd.DataFrame(
        {
            "quarter": ["2025-Q4", "2026-Q1"],
            "claims_count": [100, 110],
            "amount_mhkd": [300.0, 320.0],
            "source_agency": ["MPFA", "MPFA"],
        }
    )
    monkeypatch.setattr(dashboard_export, "fetch_mpfa_permanent_departure_claims", lambda: fetched.copy())
    monkeypatch.setattr(dashboard_export, "load_latest_normalized", lambda dataset: cache.copy())

    merged = dashboard_export._load_mpfa()

    assert list(merged["quarter"]) == ["2025-Q4", "2026-Q1", "2026-Q2"]
    q1 = merged.loc[merged["quarter"] == "2026-Q1"].iloc[0]
    q4 = merged.loc[merged["quarter"] == "2025-Q4"].iloc[0]
    assert q1["claims_count"] == 222  # live fetch wins on overlap
    assert q4["claims_count"] == 100  # cache fills the gap
    assert dashboard_export._fetch_status["mpfa"] == "live"

    persisted = pd.read_parquet(
        tmp_path / "mpfa_departure_claims" / "20260801_mpfa_cached_v2" / "mpfa_departure_claims.parquet"
    )
    assert len(persisted) == 3


def test_mpfa_fetch_failure_serves_committed_cache_and_reports_fallback(monkeypatch):
    dashboard_export._fetch_status.clear()
    cache = pd.DataFrame(
        {
            "quarter": ["2025-Q4", "2026-Q1"],
            "claims_count": [100, 110],
            "amount_mhkd": [300.0, 320.0],
            "source_agency": ["MPFA", "MPFA"],
        }
    )

    def _network_down():
        raise RuntimeError("network down")

    monkeypatch.setattr(dashboard_export, "fetch_mpfa_permanent_departure_claims", _network_down)
    monkeypatch.setattr(dashboard_export, "load_latest_normalized", lambda dataset: cache.copy())
    monkeypatch.setattr(dashboard_export, "_fallback_state", lambda dataset: False)

    merged = dashboard_export._load_mpfa()

    assert list(merged["quarter"]) == ["2025-Q4", "2026-Q1"]
    assert dashboard_export._fetch_status["mpfa"] == "fallback"


def test_visitor_arrivals_detail_keeps_full_source_count_but_windows_artifact_rows():
    visitor = pd.DataFrame(
        {
            "date": ["2004-01", "2004-01", "2016-08", "2016-08", "2026-05", "2026-05"],
            "region": [
                "Chinese Mainland", "Europe",
                "Chinese Mainland", "Europe",
                "Chinese Mainland", "Europe",
            ],
            "visitors": [100, 50, 200, 75, 300, 125],
        }
    )

    artifact, status = _build(raw_visitor_arrivals=visitor)

    detail = artifact["snapshot"]["datasets"]["visitor_arrivals_by_region"]
    assert {row["date"] for row in detail} == {"2016-08", "2026-05"}
    assert len(detail) <= 2_000
    visitor_status = next(row for row in status["sources"] if row["dataset"] == "visitor_arrivals")
    assert visitor_status["records"] == len(visitor)


def test_published_artifact_retains_mpfa_departure_claims():
    """The production snapshot must not silently publish the MPFA series empty."""
    artifact_path = (
        Path(__file__).resolve().parents[1]
        / "apps/asia-markets-dashboard/.generated/hk-population-migration-artifact.json"
    )
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    rows = artifact["snapshot"]["datasets"]["mpfa_claims"]
    assert len(rows) >= 1
    assert rows[-1]["quarter"] == "2026-Q2"
    assert rows[-1]["claims_count"] == 5200
    assert rows[-1]["amount_mhkd"] == 1203.0
    source = next(row for row in artifact["source_health"] if row["id"] == "mpfa")
    assert source["status"] == "success"
    assert source["records"] == len(rows)
