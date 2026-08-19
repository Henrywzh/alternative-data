"""Tests for the additive long-form emitter (Step 3)."""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.build_asia_backtest_registry import build_registry
from scripts.build_asia_backtest_long_form import (
    _prior_period_start,
    _value_for,
    build_long_form,
)
from src.common.backtest.pivot import contract_summary, contract_table


@pytest.fixture(autouse=True)
def _fresh_registry() -> None:
    """Keep emitter tests independent from stale generated registry files."""
    build_registry()


def _build(recon: dict) -> pd.DataFrame:
    frame = pd.read_csv("data/registries/asia_backtest_long_form.csv")
    return frame


def test_emitter_passes_hard_gate_and_produces_baselines() -> None:
    recon = build_long_form(write_outputs=True, write_run_store=False)
    assert recon["hard_gate_passed"] is True
    assert recon["dedup_violations"] == []
    assert recon["airline_overlap_reconciliation"]["pairs"] == 216
    assert recon["airline_overlap_reconciliation"]["exact_model_pairs"] == 162
    assert recon["airline_overlap_reconciliation"]["non_comparable_model_pairs"] == 54
    assert recon["airline_overlap_reconciliation"]["passed"] is True
    assert recon["dedup_value_checks"] > 0
    assert recon["primary_rows"] > 2000
    assert recon["baseline_rows"] > 100
    assert recon["baseline_rows"] == 2357
    assert recon["input_bundle_id"].startswith("asia_backtest_input_bundle-")
    # B3 fix: compute_metric_table now emits a per-entity row alongside each
    # pooled row (metric_grain), so the row count is no longer 1:1 with the
    # number of (registry_id, model_id, is_baseline) groups. The independent
    # MTR chronological FY/H1 track adds four pooled/per-entity contracts.
    assert recon["metrics_rows"] == 263
    frame = _build(recon)
    assert frame["row_key"].is_unique
    assert frame["input_bundle_id"].nunique() == 1
    assert frame["source_row_fingerprint"].notna().all()
    assert frame["natural_observation_key"].notna().all()
    assert frame["natural_observation_key"].is_unique
    mtr_reported = frame[
        frame["source_dataset"].eq("mtr_farebox_revenue_h1_backtest")
        & frame["has_actual"]
        & ~frame["is_baseline"]
    ]
    assert mtr_reported["actual_available_at"].ne("not_captured").all()
    assert mtr_reported["actual_source_url"].str.startswith("https://").all()


@pytest.mark.network
def test_csv_and_parquet_preserve_optional_provenance_values() -> None:
    build_long_form(write_outputs=True, write_run_store=False)
    csv = pd.read_csv("data/registries/asia_backtest_long_form.csv")
    parquet = pd.read_parquet("data/registries/asia_backtest_long_form.parquet")
    assert len(csv) == len(parquet)
    assert list(csv.columns) == list(parquet.columns)
    for column in ("source_run_id", "information_cutoff", "source_observation_date", "actual_available_at", "research_only", "notes"):
        assert csv[column].isna().sum() == 0
        assert parquet[column].isna().sum() == 0
        assert csv[column].astype(str).equals(parquet[column].astype(str))
    assert not (csv["has_prediction"] & csv["predicted_value"].isna()).any()
    assert not (csv["has_actual"] & csv["actual_value"].isna()).any()
    assert "not_captured" in set(csv["research_only"])
    assert "true" in set(csv["research_only"])


def test_main_hard_gate_includes_airline_overlap(monkeypatch) -> None:
    import scripts.build_asia_backtest_long_form as module

    original = module.build_long_form

    def failing(**kwargs):
        result = original(**kwargs)
        result["hard_gate_passed"] = False
        return result

    monkeypatch.setattr(module, "build_long_form", failing)
    monkeypatch.setattr(module.sys, "argv", ["build_asia_backtest_long_form.py", "--no-run-store"])
    assert module.main() == 1


def test_failed_reconciliation_does_not_publish_top_level_outputs_or_latest_pointer(monkeypatch, tmp_path) -> None:
    import json
    import scripts.build_asia_backtest_long_form as module

    output_root = tmp_path / "registry"
    output_root.mkdir()
    output_files = {
        "long_csv": output_root / "asia_backtest_long_form.csv",
        "long_parquet": output_root / "asia_backtest_long_form.parquet",
        "metrics_csv": output_root / "asia_backtest_metrics.csv",
        "metrics_parquet": output_root / "asia_backtest_metrics.parquet",
        "intervals_csv": output_root / "asia_backtest_metric_intervals.csv",
        "intervals_parquet": output_root / "asia_backtest_metric_intervals.parquet",
        "metrics_manifest": output_root / "asia_backtest_metrics_manifest.json",
        "input_bundle": output_root / "asia_backtest_input_bundle.json",
        "reconciliation": output_root / "asia_backtest_reconciliation.json",
    }
    sentinel = b"sentinel-before-failed-run\n"
    for path in output_files.values():
        path.write_bytes(sentinel)
    pointer = output_root / "asia_backtest_latest.json"
    pointer.write_text(json.dumps({"run_id": "prior-ready-run"}) + "\n", encoding="utf-8")

    monkeypatch.setattr(module, "REGISTRY_DIR", output_root)
    for name, path in (
        ("LONG_FORM_CSV", output_files["long_csv"]),
        ("LONG_FORM_PARQUET", output_files["long_parquet"]),
        ("METRICS_CSV", output_files["metrics_csv"]),
        ("METRICS_PARQUET", output_files["metrics_parquet"]),
        ("INTERVALS_CSV", output_files["intervals_csv"]),
        ("INTERVALS_PARQUET", output_files["intervals_parquet"]),
        ("METRICS_MANIFEST_JSON", output_files["metrics_manifest"]),
        ("INPUT_BUNDLE_JSON", output_files["input_bundle"]),
        ("RECONCILIATION_JSON", output_files["reconciliation"]),
    ):
        monkeypatch.setattr(module, name, path)

    monkeypatch.setattr(
        module,
        "_reconcile_dedup_groups",
        lambda frame: ([{"dedup_group_id": "forced-failure", "column": "actual_value"}], 1),
    )
    recon = module.build_long_form(write_outputs=True, write_run_store=True)

    assert recon["hard_gate_passed"] is False
    assert all(path.read_bytes() == sentinel for path in output_files.values())
    assert json.loads(pointer.read_text(encoding="utf-8"))["run_id"] == "prior-ready-run"
    failed_manifests = list((output_root / "runs").glob("*/manifest.json"))
    assert len(failed_manifests) == 1
    assert json.loads(failed_manifests[0].read_text(encoding="utf-8"))["status"] == "reconciliation_failed"


def test_mtr_2026_is_h1_forecast_with_ridge_gated() -> None:
    recon = build_long_form(write_outputs=True, write_run_store=False)
    frame = _build(recon)
    annual_2026 = frame[
        (frame["source_dataset"] == "mtr_farebox_revenue_annual_backtest")
        & (frame["source_row_index"] == 26)
    ]
    physics = annual_2026[annual_2026["model_id"] == "mtr_physics_yield_v1"]
    ridge = annual_2026[annual_2026["model_id"] == "mtr_ridge_residual_v1"]
    # The annual-table copy of the 2026 H1 forecast is a duplicate alias.
    assert bool(physics["is_primary_source"].iloc[0]) is False
    assert physics["predicted_value"].iloc[0] == pytest.approx(11976.685623)
    # Ridge has no adjustment outside 2019-2023: no prediction emitted.
    assert pd.isna(ridge["predicted_value"].iloc[0])
    assert bool(ridge["has_prediction"].iloc[0]) is False
    assert annual_2026["target_period_type"].isin(["H1"]).all()


def test_airline_h1_value_mapping_is_exact() -> None:
    recon = build_long_form(write_outputs=True, write_run_store=False)
    frame = _build(recon)
    row = frame[
        (frame["source_dataset"] == "airline_h1_kpi_backtest")
        & (frame["entity_id"] == "Air China")
        & (frame["target_period_start"] == "2019-01-01")
        & (frame["model_id"] == "flat_ask_v1")
        & (frame["target_id"] == "revenue")
    ]
    assert len(row) == 1
    assert row["predicted_value"].iloc[0] == pytest.approx(67749.011759)
    assert row["actual_value"].iloc[0] == pytest.approx(65313.087)
    assert row["unit"].iloc[0] == "RMB mn"


def test_mtr_fy2025_baseline_uses_prior_year_actual() -> None:
    recon = build_long_form(write_outputs=True, write_run_store=False)
    frame = _build(recon)
    baseline = frame[
        (frame["model_id"] == "baseline_same_period_last_year")
        & (frame["entity_id"] == "MTR")
        & (frame["target_period_type"] == "FY")
        & (frame["target_period_start"] == "2025-01-01")
    ]
    assert len(baseline) == 2
    # 2024 actual = 23013.0 HK$m.
    assert baseline["predicted_value"].eq(23013.0).all()
    # The observation's actual is the official reported figure (23595.0),
    # not the physics model estimate.
    assert baseline["actual_value"].eq(23595.0).all()


def test_mtr_2026_all_sources_are_h1_ytd_forecast_only() -> None:
    build_long_form(write_outputs=True, write_run_store=False)
    frame = _build({})
    rows = frame[
        frame["source_dataset"].str.startswith("mtr_")
        & frame["target_period_start"].eq("2026-01-01")
        & ~frame["is_baseline"]
    ]
    monthly = rows[rows["source_dataset"].eq("mtr_farebox_monthly_nowcast")]
    period_rows = rows[~rows["source_dataset"].eq("mtr_farebox_monthly_nowcast")]
    assert period_rows["target_period_type"].eq("H1").all()
    assert monthly["target_period_type"].eq("month").all()
    assert monthly["evaluation_status"].eq("forecast_only").all()
    assert monthly["has_actual"].eq(False).all()
    annual = rows[rows["source_dataset"].eq("mtr_farebox_revenue_annual_backtest")]
    h1 = rows[rows["source_dataset"].eq("mtr_farebox_revenue_h1_backtest")]
    assert annual["track_id"].eq("ytd_current").all()
    assert annual["target_period_end"].eq("2026-06-30").all()
    assert h1["track_id"].eq("half_year_non_overlapping").all()
    assert rows["evaluation_status"].eq("forecast_only").all()


def test_airline_h1_2025_baseline_uses_prior_h1_actual() -> None:
    recon = build_long_form(write_outputs=True, write_run_store=False)
    frame = _build(recon)
    baseline = frame[
        (frame["model_id"] == "baseline_same_period_last_year")
        & (frame["entity_id"] == "Air China")
        & (frame["target_period_type"] == "H1")
        & (frame["target_period_start"] == "2025-01-01")
        & (frame["target_id"] == "revenue")
    ]
    # One baseline row is emitted per declared source/model contract. This
    # keeps each challenger contract complete while sharing the same prior
    # actual value.
    assert len(baseline) == 7
    # Air China H1 2024 actual = 79520.332; H1 2025 actual = 80757.434.
    assert baseline["predicted_value"].nunique() == 1
    assert baseline["predicted_value"].iloc[0] == pytest.approx(79520.332)
    assert baseline["actual_value"].iloc[0] == pytest.approx(80757.434)


def test_unknown_contract_raises() -> None:
    row = pd.Series(
        {
            "source_dataset": "unknown_dataset",
            "target_id": "revenue",
            "model_id": "mystery",
            "source_row_index": 0,
        }
    )
    with pytest.raises(ValueError, match="no value mapping"):
        _value_for(row, pd.DataFrame({"x": [1.0]}))


def test_prior_period_start_rules() -> None:
    assert _prior_period_start("FY", "2025-01-01") == "2024-01-01"
    assert _prior_period_start("H1", "2025-01-01") == "2024-01-01"
    assert _prior_period_start("H2", "2025-07-01") == "2024-07-01"
    assert _prior_period_start("month", "2025-07-01") == "2024-07-01"
    assert _prior_period_start("quarter", "2025-01-01") is None


def test_contract_table_reproduces_source_values_for_airline_fy_revenue() -> None:
    build_long_form(write_outputs=True, write_run_store=False)
    frame = pd.read_csv("data/registries/asia_backtest_long_form.csv")
    registry_id = "airline_period_kpi_backtest:FY:revenue:flat_ask_v1"
    table = contract_table(frame, registry_id)
    # 54 rows in the period table for FY, minus the insufficient-coverage row.
    assert len(table) == 53
    assert (table["is_baseline"] == False).all()  # noqa: E712
    row = table[table["entity_id"] == "Air China"].sort_values("target_period_start").iloc[2]
    # Air China FY2019: matches the wide period table values.
    assert row["predicted_value"] == pytest.approx(143532.400088)
    assert row["actual_value"] == pytest.approx(136180.690)
    summary = contract_summary(frame, [registry_id], metric_grain="pooled")
    assert summary["n_eval"].iloc[0] == 53
    assert summary["metric_grain"].iloc[0] == "pooled"
    # Pooled MAPE (all rows).  The legacy summary uses per-company weighting
    # (7.13%), which the reconciliation report records separately.
    assert summary["mape_pct"].iloc[0] == pytest.approx(6.8466, abs=0.01)
