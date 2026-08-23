#!/usr/bin/env python3
"""Build the additive long-form backtest table (Step 3 of the unified engine).

The long form is value-bearing but additive: it does not replace any wide
table, does not touch a model calculation, and does not feed either
dashboard.  It reads the Step 1 registry (row metadata) plus the existing
source tables, and emits one row per source row/model contract with
``predicted_value`` / ``actual_value`` filled in, followed by
same-period-last-year baseline rows.

Outputs (under ``data/registries/``):

* ``asia_backtest_long_form.csv`` — the stable long-form contract.
* ``asia_backtest_reconciliation.json`` — value-level assertions on dedup
  groups and an informational legacy-metric comparison.
* ``runs/<run-id>/`` + ``asia_backtest_latest.json`` — content-addressed
  run copy with input fingerprints and manifest.

Hard gate: any value mismatch inside a dedup group (same economic
observation, same model, different source tables) fails the run.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.backtest.schema import validate_long_form
from src.common.backtest.metrics import build_metrics_manifest, compute_error_intervals, compute_metric_table
from src.common.backtest.tracks import check_period_type_consistency
from src.common.backtest.storage import (
    BacktestRunSpec,
    RunArtifactStore,
    canonical_json,
    dataframe_fingerprint,
    file_fingerprint,
    runtime_metadata,
    sha256_bytes,
)
from src.common.backtest.vocabulary import BASELINE_MODEL_ID, METRIC_POLICY_VERSION

def _registry_dir() -> Path:
    """The backtest registry directory, overridable for tests.

    build_registry() and build_long_form() write their outputs here as part of
    building, so a test that only wants the returned frame still rewrote the
    tracked files -- and their manifests carry a build timestamp, so every run
    showed a diff. tests/conftest.py points ASIA_BACKTEST_REGISTRY_DIR at a
    session-scoped copy, keeping reads intact while writes land outside the
    repository.
    """
    override = os.environ.get("ASIA_BACKTEST_REGISTRY_DIR", "").strip()
    return Path(override) if override else ROOT / "data" / "registries"


REGISTRY_DIR = _registry_dir()


def _repo_relative(path: Path) -> str:
    """Label a path for the manifest, tolerating one outside the repository.

    REGISTRY_DIR is redirectable (see _registry_dir), so relative_to(ROOT)
    could raise on an input that lives under the redirect. The manifest wants
    a stable label, not a real location, so fall back to the file name.
    """
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.name

ROW_STATUS_CSV = REGISTRY_DIR / "asia_backtest_row_status.csv"
TARGET_CSV = REGISTRY_DIR / "asia_backtest_target_registry.csv"
LONG_FORM_CSV = REGISTRY_DIR / "asia_backtest_long_form.csv"
LONG_FORM_PARQUET = REGISTRY_DIR / "asia_backtest_long_form.parquet"
METRICS_CSV = REGISTRY_DIR / "asia_backtest_metrics.csv"
METRICS_PARQUET = REGISTRY_DIR / "asia_backtest_metrics.parquet"
INTERVALS_CSV = REGISTRY_DIR / "asia_backtest_metric_intervals.csv"
INTERVALS_PARQUET = REGISTRY_DIR / "asia_backtest_metric_intervals.parquet"
METRICS_MANIFEST_JSON = REGISTRY_DIR / "asia_backtest_metrics_manifest.json"
RECONCILIATION_JSON = REGISTRY_DIR / "asia_backtest_reconciliation.json"
INPUT_BUNDLE_JSON = REGISTRY_DIR / "asia_backtest_input_bundle.json"

ENGINE_VERSION = "asia_backtest_engine_v1_11"

# Keep absent optional provenance values explicit and identical in CSV and
# Parquet.  Empty strings are read back as NaN by pandas' CSV parser, while
# Parquet preserves them, which otherwise makes the two published formats
# disagree on the same run.
STRING_COLUMNS = (
    "engine_version",
    "registry_id",
    "row_key",
    "logical_observation_id",
    "dedup_group_id",
    "source_dataset",
    "source_run_id",
    "input_bundle_id",
    "source_row_fingerprint",
    "natural_observation_key",
    "entity_id",
    "target_id",
    "target_period_start",
    "target_period_end",
    "target_period_type",
    "track_id",
    "model_id",
    "model_family",
    "forecast_origin",
    "information_cutoff",
    "source_observation_date",
    "actual_available_at",
    "actual_source_url",
    "unit",
    "source_value_columns",
    "source_row_status",
    "input_pit_status",
    "target_pit_status",
    "pit_grade",
    "evaluation_status",
    "dependency_status",
    "scenario",
    "lookback_months",
    "model_use",
    "source_caveat",
    "notes",
)


def _model_family(source_dataset: str, model_id: str, source_row: pd.Series) -> str:
    """Family grouping for models that share inputs (e.g. v4 variants)."""
    if source_dataset == "airline_earnings_model_v4":
        return "v4_revenue_decomposition"
    if source_dataset == "airline_cost_engine_v2":
        return "cost_engine_v2"
    if source_dataset == "airline_h1_kpi_backtest" or source_dataset == "airline_period_kpi_backtest":
        if model_id in {"flat_ask_v1", "flat_rpk_v1", "spring_recovery_v1"}:
            return "flat_unit_economics"
        if model_id == "analyst_h1_nowcast_v1":
            return "analyst_nowcast"
        return "below_the_line_residual"
    if source_dataset == "mtr_farebox_walk_forward_oos":
        return "mtr_farebox_chronological_walk_forward"
    if source_dataset == "mtr_farebox_monthly_nowcast":
        return "mtr_farebox_chronological_monthly_nowcast"
    if source_dataset == "mtr_farebox_revenue_annual_backtest" or source_dataset == "mtr_farebox_revenue_h1_backtest":
        return "mtr_farebox_physics" if model_id == "mtr_physics_yield_v1" else "mtr_farebox_ridge"
    if source_dataset == "shkp_indicative_sales_model_backtest":
        return str(source_row.get("forecast_method") or "not_captured")
    if source_dataset == "shkp_skeleton_historical_backtest":
        return "shkp_skeleton"
    if source_dataset == "shkp_commercial_backtest":
        return str(source_row.get("method") or "not_captured")
    return "not_captured"


def _source_observation_date(source: pd.DataFrame, index: int) -> str:
    """Observation/announcement date retained by the source, if any."""
    if index < 0 or index >= len(source):
        return ""
    row = source.iloc[index]
    for column in (
        "kpi_latest_announcement_date",
        "kpi_information_cutoff",
        "information_cutoff",
        "data_cutoff",
        "target_financial_announcement_date",
        "actual_available_at",
    ):
        if column in source.columns:
            value = row.get(column)
            if pd.notna(value) and str(value).strip() not in {"", "nan", "None"}:
                return str(value)
    return ""


def _flag(value: Any) -> bool:
    """Parse a registry boolean without treating ``not_captured`` as true."""
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}


def _research_only_value(value: Any) -> str:
    """Preserve the registry's tri-state research-only provenance field."""
    if value is None or pd.isna(value):
        return "not_captured"
    if isinstance(value, bool):
        return "true" if value else "false"
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "t"}:
        return "true"
    if normalized in {"0", "false", "no", "n", "f"}:
        return "false"
    return "not_captured"


# (source_dataset, target_id, model_id) -> (prediction column, actual column, unit)
VALUE_MAP: dict[tuple[str, str, str], tuple[str, str, str]] = {
    ("mtr_farebox_revenue_annual_backtest", "transport_operations_revenue", "mtr_physics_yield_v1"): (
        "farebox_revenue_hkdm",
        "transport_ops_revenue_hkdm",
        "HK$m",
    ),
    ("mtr_farebox_revenue_annual_backtest", "transport_operations_revenue", "mtr_ridge_residual_v1"): (
        "ridge_adjusted_revenue_hkdm",
        "transport_ops_revenue_hkdm",
        "HK$m",
    ),
    ("mtr_farebox_revenue_h1_backtest", "transport_operations_revenue", "mtr_physics_yield_v1"): (
        "h1_model_revenue_hkdm",
        "h1_actual_transport_ops_revenue_hkdm",
        "HK$m",
    ),
    ("mtr_farebox_walk_forward_oos", "transport_operations_revenue", "mtr_prior_yield_fam_walk_forward_v1"): (
        "predicted_value_hkdm",
        "actual_value_hkdm",
        "HK$m",
    ),
    ("mtr_farebox_monthly_nowcast", "transport_operations_revenue_monthly_nowcast", "mtr_prior_yield_fam_walk_forward_v1"): (
        "predicted_value_hkdm",
        "actual_value_hkdm",
        "HK$m",
    ),
    ("airline_h1_kpi_backtest", "revenue", "flat_ask_v1"): (
        "flat_ask_revenue_pred_native_mn",
        "target_h1_revenue_native_mn",
        "RMB mn",
    ),
    ("airline_h1_kpi_backtest", "revenue", "flat_rpk_v1"): (
        "flat_rpk_revenue_pred_native_mn",
        "target_h1_revenue_native_mn",
        "RMB mn",
    ),
    ("airline_h1_kpi_backtest", "revenue", "analyst_h1_nowcast_v1"): (
        "analyst_h1_revenue_pred_native_mn",
        "target_h1_revenue_native_mn",
        "RMB mn",
    ),
    ("airline_h1_kpi_backtest", "operating_cost", "flat_ask_v1"): (
        "flat_ask_cost_pred_native_mn",
        "target_h1_operating_cost_native_mn",
        "RMB mn",
    ),
    ("airline_h1_kpi_backtest", "attributable_profit", "flat_ask_profit_v1"): (
        "flat_ask_profit_pred_native_mn",
        "target_h1_attributable_profit_native_mn",
        "RMB mn",
    ),
    ("airline_period_kpi_backtest", "revenue", "flat_ask_v1"): (
        "flat_ask_revenue_pred_native_mn",
        "target_revenue_native_mn",
        "RMB mn",
    ),
    ("airline_period_kpi_backtest", "revenue", "flat_rpk_v1"): (
        "flat_rpk_revenue_pred_native_mn",
        "target_revenue_native_mn",
        "RMB mn",
    ),
    ("airline_period_kpi_backtest", "revenue", "spring_recovery_v1"): (
        "spring_recovery_case_revenue_pred_native_mn",
        "target_revenue_native_mn",
        "RMB mn",
    ),
    ("airline_period_kpi_backtest", "operating_cost", "flat_ask_v1"): (
        "flat_ask_cost_pred_native_mn",
        "target_operating_cost_native_mn",
        "RMB mn",
    ),
    ("airline_period_kpi_backtest", "attributable_profit", "flat_ask_residual_v1"): (
        "flat_ask_profit_residual_pred_native_mn",
        "target_attributable_profit_native_mn",
        "RMB mn",
    ),
    ("airline_earnings_model_v4", "revenue", "v4_base_decomposition_v1"): (
        "revenue_base_decomposition_native_mn",
        "target_revenue_native_mn",
        "RMB mn",
    ),
    ("airline_earnings_model_v4", "revenue", "v4_dynamic_shrinkage_v1"): (
        "revenue_dynamic_shrinkage_native_mn",
        "target_revenue_native_mn",
        "RMB mn",
    ),
    ("airline_earnings_model_v4", "revenue", "v4_residual_yield_v1"): (
        "revenue_residual_yield_native_mn",
        "target_revenue_native_mn",
        "RMB mn",
    ),
    ("airline_earnings_model_v4", "revenue", "v4_recovery_overlay_v1"): (
        "revenue_recovery_overlay_native_mn",
        "target_revenue_native_mn",
        "RMB mn",
    ),
    ("airline_cost_engine_v2", "operating_cost", "flat_ask_cost_v1"): (
        "cost_flat_ask_native_mn",
        "operating_cost_actual_native_mn",
        "RMB mn",
    ),
    ("airline_cost_engine_v2", "operating_cost", "fuel_mechanical_cost_v1"): (
        "cost_fuel_mechanical_native_mn",
        "operating_cost_actual_native_mn",
        "RMB mn",
    ),
    ("airline_cost_engine_v2", "operating_cost", "nonfuel_driver_cost_v1"): (
        "cost_nonfuel_drivers_native_mn",
        "operating_cost_actual_native_mn",
        "RMB mn",
    ),
    ("airline_cost_engine_v2", "operating_cost", "company_shrink_cask_v2"): (
        "cost_company_shrink_native_mn",
        "operating_cost_actual_native_mn",
        "RMB mn",
    ),
    ("airline_cost_engine_v2", "operating_cost", "full_cask_v2"): (
        "cost_full_cask_native_mn",
        "operating_cost_actual_native_mn",
        "RMB mn",
    ),
}


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"missing input: {path}")
    return pd.read_csv(path)


def _load_sources(row_status: pd.DataFrame) -> dict[str, pd.DataFrame]:
    norm = ROOT / "data" / "normalized" / "hk_transport"
    processed = ROOT / "data" / "processed" / "transport"
    sources: dict[str, pd.DataFrame] = {
        "mtr_farebox_revenue_annual_backtest": _read_csv(processed / "mtr_farebox_revenue_annual_backtest.csv"),
        "mtr_farebox_revenue_h1_backtest": _read_csv(processed / "mtr_farebox_revenue_h1_backtest.csv"),
        "mtr_farebox_walk_forward_oos": _read_csv(processed / "mtr_farebox_walk_forward_oos.csv"),
        "mtr_farebox_monthly_nowcast": _read_csv(processed / "mtr_farebox_monthly_nowcast.csv"),
        "airline_h1_kpi_backtest": _read_csv(norm / "airline_h1_kpi_backtest.csv"),
        "airline_period_kpi_backtest": _read_csv(norm / "airline_period_kpi_backtest.csv"),
        "airline_earnings_model_v4": _read_csv(norm / "airline_earnings_model_v4.csv"),
        "airline_cost_engine_v2": _read_csv(norm / "airline_cost_engine_v2.csv"),
    }
    canonical_actuals = _read_csv(norm / "mtr_transport_ops_actuals.csv")
    required_actuals = {"period_type", "year", "actual_value_hkdm"}
    missing_actuals = sorted(required_actuals - set(canonical_actuals.columns))
    if missing_actuals:
        raise ValueError(f"MTR canonical actuals are missing value columns: {missing_actuals}")
    for dataset, period_type, actual_column in (
        ("mtr_farebox_revenue_annual_backtest", "FY", "transport_ops_revenue_hkdm"),
        ("mtr_farebox_revenue_h1_backtest", "H1", "h1_actual_transport_ops_revenue_hkdm"),
    ):
        source = sources[dataset].copy()
        source_year = source["year"].astype(int)
        observed = pd.to_numeric(source[actual_column], errors="coerce")
        if period_type == "FY":
            partial_ytd = source["period_status"].eq("partial_ytd") if "period_status" in source.columns else pd.Series(False, index=source.index)
            partial_ytd = partial_ytd | (
                source_year.eq(int(source_year.max()))
                & observed.isna()
                & pd.to_numeric(source.get("farebox_revenue_hkdm"), errors="coerce").notna()
            )
            canonical_periods = pd.Series(
                ["H1" if is_partial else "FY" for is_partial in partial_ytd],
                index=source.index,
            )
        else:
            canonical_periods = pd.Series(period_type, index=source.index)
        for index, year in source_year.items():
            if canonical_periods.loc[index] == "H1":
                h1_exists = canonical_actuals["period_type"].eq("H1") & canonical_actuals["year"].astype(int).eq(int(year))
                fy_exists = canonical_actuals["period_type"].eq("FY") & canonical_actuals["year"].astype(int).eq(int(year))
                if not h1_exists.any() and fy_exists.any():
                    raise ValueError(
                        f"MTR partial H1/YTD source is stale relative to a FY canonical actual: {dataset} {year}"
                    )
        expected_values: list[float | None] = []
        for index, year in source_year.items():
            matches = canonical_actuals.loc[
                canonical_actuals["period_type"].eq(canonical_periods.loc[index])
                & canonical_actuals["year"].astype(int).eq(int(year)),
                "actual_value_hkdm",
            ]
            expected_values.append(float(matches.iloc[0]) if not matches.empty else None)
        expected = pd.Series(expected_values, index=source.index, dtype="float64")
        mismatch = observed.notna() & expected.notna() & ((observed - expected).abs() > 1e-6)
        stale = observed.notna() & expected.isna()
        if mismatch.any() or stale.any():
            raise ValueError(f"{dataset} actual values diverge from canonical MTR actuals")
        source.loc[expected.notna(), actual_column] = expected[expected.notna()]
        sources[dataset] = source
    real_estate_root = ROOT / "data" / "normalized" / "hk_real_estate"
    for dataset in (
        "shkp_indicative_sales_model_backtest",
        "shkp_skeleton_historical_backtest",
        "shkp_commercial_backtest",
    ):
        run_ids = sorted(
            str(value)
            for value in row_status.loc[
                row_status["source_dataset"].eq(dataset), "source_run_id"
            ].dropna().unique()
            if str(value).strip() and str(value) != "nan"
        )
        if len(run_ids) != 1:
            raise ValueError(f"{dataset} must resolve to exactly one source run, got {run_ids}")
        candidates = sorted((real_estate_root / dataset / run_ids[0]).glob("*.parquet"))
        if len(candidates) != 1:
            raise ValueError(f"{dataset} source run must contain exactly one parquet")
        sources[dataset] = pd.read_parquet(candidates[0])
    return sources


def _select_valid_mtr_patronage_snapshot(candidates: list[Path]) -> Path:
    """Return the newest patronage snapshot that the MTR loader can use."""
    required = {"month", "domestic_service_thousands", "total_mtr_patronage_thousands"}
    last_error: Exception | None = None
    for path in reversed(candidates):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            frame = pd.DataFrame(payload["data"])
            if frame.empty or not required.issubset(frame.columns):
                raise ValueError("snapshot is empty or missing required patronage columns")
            pd.to_datetime(frame["month"], errors="raise")
            return path
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            last_error = exc
    raise ValueError(f"no valid local MTR patronage snapshot found: {last_error}")


def _select_valid_immd_snapshot(candidates: list[Path]) -> Path | None:
    """Return the newest ImmD snapshot with a usable date column."""
    required = {
        "Date",
        "Arrival / Departure",
        "Control Point",
        "Hong Kong Residents",
        "Mainland Visitors",
        "Other Visitors",
        "Total",
    }
    last_error: Exception | None = None
    for path in reversed(candidates):
        try:
            frame = pd.read_csv(path, encoding="utf-8-sig")
            if frame.empty or not required.issubset(frame.columns):
                raise ValueError("snapshot is empty or missing required ImmD columns")
            dates = pd.to_datetime(frame["Date"], format="%d-%m-%Y", errors="coerce")
            if dates.notna().sum() == 0:
                raise ValueError("snapshot contains no valid dates")
            return path
        except (OSError, ValueError, TypeError, pd.errors.ParserError) as exc:
            last_error = exc
    return None


def _input_bundle(row_status: pd.DataFrame) -> tuple[str, dict[str, Any], list[Path]]:
    """Resolve every source used by the emitter into one reproducible bundle."""
    norm = ROOT / "data" / "normalized" / "hk_transport"
    processed = ROOT / "data" / "processed" / "transport"
    paths: dict[str, Path] = {
        "registry_row_status": ROW_STATUS_CSV,
        "registry_target": TARGET_CSV,
        "mtr_annual": processed / "mtr_farebox_revenue_annual_backtest.csv",
        "mtr_h1": processed / "mtr_farebox_revenue_h1_backtest.csv",
        "mtr_walk_forward": processed / "mtr_farebox_walk_forward_oos.csv",
        "mtr_monthly_nowcast": processed / "mtr_farebox_monthly_nowcast.csv",
        "mtr_walk_forward_model_code": ROOT / "scripts" / "build_mtr_walk_forward_oos.py",
        "mtr_canonical_actuals": norm / "mtr_transport_ops_actuals.csv",
        "airline_h1": norm / "airline_h1_kpi_backtest.csv",
        "airline_period": norm / "airline_period_kpi_backtest.csv",
        "airline_v4": norm / "airline_earnings_model_v4.csv",
        "airline_cost": norm / "airline_cost_engine_v2.csv",
    }
    mtr_raw = sorted((ROOT / "data" / "raw" / "hk_transport").glob("mtr_patronage_*.json"))
    if not mtr_raw:
        raise FileNotFoundError("input bundle has no MTR patronage snapshot")
    paths["mtr_patronage_snapshot"] = _select_valid_mtr_patronage_snapshot(mtr_raw)
    immd_raw = sorted((ROOT / "data" / "raw" / "hk_population_migration").glob("immd_daily_traffic_*.csv"))
    if immd_raw:
        immd_snapshot = _select_valid_immd_snapshot(immd_raw)
        if immd_snapshot is not None:
            paths["immd_daily_traffic_snapshot"] = immd_snapshot
    real_estate_root = ROOT / "data" / "normalized" / "hk_real_estate"
    for dataset in (
        "shkp_indicative_sales_model_backtest",
        "shkp_skeleton_historical_backtest",
        "shkp_commercial_backtest",
    ):
        run_ids = sorted(
            str(value)
            for value in row_status.loc[
                row_status["source_dataset"].eq(dataset), "source_run_id"
            ].dropna().unique()
            if str(value).strip() and str(value) != "nan"
        )
        if len(run_ids) != 1:
            raise ValueError(f"{dataset} must resolve to exactly one source run, got {run_ids}")
        run_dir = real_estate_root / dataset / run_ids[0]
        parquet_candidates = sorted(run_dir.glob("*.parquet"))
        if len(parquet_candidates) != 1:
            raise ValueError(f"{dataset} source run must contain exactly one parquet: {run_dir}")
        paths[f"{dataset}:data"] = parquet_candidates[0]
        lineage = run_dir / "lineage.json"
        if not lineage.exists():
            raise ValueError(f"{dataset} source run is missing lineage.json: {run_dir}")
        paths[f"{dataset}:lineage"] = lineage

    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"input bundle has missing paths: {missing}")
    entries: dict[str, Any] = {}
    for label, path in sorted(paths.items()):
        entry: dict[str, Any] = {
            "path": _repo_relative(path),
            "sha256": file_fingerprint(path),
            "bytes": path.stat().st_size,
        }
        if path.suffix == ".parquet":
            table = pd.read_parquet(path)
        elif path.suffix == ".csv":
            table = pd.read_csv(path)
        else:
            table = None
        if table is not None:
            entry["rows"] = int(table.shape[0])
            entry["canonical_table_fingerprint"] = dataframe_fingerprint(table)
        entries[label] = entry
    bundle_payload = {"schema": "asia_backtest_input_bundle_v1", "inputs": entries}
    bundle_id = f"asia_backtest_input_bundle-{sha256_bytes(canonical_json(bundle_payload).encode('utf-8'))[:16]}"
    bundle_payload["bundle_id"] = bundle_id
    return bundle_id, bundle_payload, [path for path in paths.values()]


def _publish_compatibility_outputs(artifacts: dict[Path, Path]) -> None:
    """Atomically publish compatibility copies after a ready run is built."""
    for source, target in artifacts.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
            temp_path = Path(handle.name)
        try:
            shutil.copyfile(source, temp_path)
            os.replace(temp_path, target)
        finally:
            temp_path.unlink(missing_ok=True)


def _row_fingerprint(record: dict[str, Any]) -> str:
    payload = {
        "source_dataset": record["source_dataset"],
        "entity_id": record["entity_id"],
        "target_id": record["target_id"],
        "target_period_start": record["target_period_start"],
        "target_period_type": record["target_period_type"],
        "track_id": record["track_id"],
        "model_id": record["model_id"],
        "scenario": record["scenario"],
        "lookback_months": record["lookback_months"],
        "source_value_columns": record["source_value_columns"],
        "predicted_value": record.get("predicted_value"),
        "actual_value": record.get("actual_value"),
        "has_prediction": record.get("has_prediction"),
        "has_actual": record.get("has_actual"),
        "actual_available_at": record.get("actual_available_at"),
        "actual_source_url": record.get("actual_source_url"),
    }
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def _natural_observation_key(record: dict[str, Any]) -> str:
    """Identify one source-contract observation, including its contract key.

    This key is intentionally unique per registry row.  ``logical_observation_id``
    remains the cross-source economic observation key used for reconciliation.
    """
    return "|".join(
        str(record[field])
        for field in (
            "registry_id",
            "source_dataset",
            "source_row_index",
            "dedup_rank",
            "entity_id",
            "target_id",
            "target_period_type",
            "track_id",
            "target_period_start",
            "model_id",
            "scenario",
            "lookback_months",
        )
    )


def _assert_mtr_contract(frame: pd.DataFrame) -> None:
    """Repeat the MTR period remap/gating rules at the value-emission layer."""
    mtr = frame[frame["source_dataset"].str.startswith("mtr_")]
    if mtr.empty:
        return
    mtr_ytd = mtr[mtr["track_id"].eq("ytd_current")]
    if not mtr_ytd.empty:
        if not mtr_ytd["target_period_type"].eq("H1").all():
            raise ValueError("MTR ytd_current rows must be H1, never FY")
        contradictory = mtr_ytd["has_actual"] & mtr_ytd["evaluation_status"].eq("forecast_only")
        if contradictory.any():
            raise ValueError("MTR ytd_current rows with an actual cannot remain forecast_only")
        # The annual-table copy is a YTD-current alias; the dedicated H1 source
        # remains on the half-year non-overlapping track.
        if not mtr_ytd["source_dataset"].eq("mtr_farebox_revenue_annual_backtest").all():
            raise ValueError("MTR ytd_current rows must come from the annual YTD source")
    ridge = mtr[mtr["model_id"].eq("mtr_ridge_residual_v1")]
    if not ridge.empty:
        invalid_ridge = ridge[ridge["target_period_start"].str[:4].astype(int).gt(2023) & ridge["predicted_value"].notna()]
        if not invalid_ridge.empty:
            raise ValueError("MTR ridge predictions are only allowed through 2023")


def _value_for(row_status_row: pd.Series, source: pd.DataFrame) -> tuple[float | None, float | None, str, str]:
    """Return (predicted, actual, unit, source_value_columns) for a registry row."""
    source_dataset = str(row_status_row["source_dataset"])
    target_id = str(row_status_row["target_id"])
    model_id = str(row_status_row["model_id"])
    key = (source_dataset, target_id, model_id)
    spec = VALUE_MAP.get(key)
    if spec is None:
        # SHKP model IDs are constructed from the frame itself.
        if source_dataset == "shkp_indicative_sales_model_backtest":
            spec = ("forecast_value_hkd", "actual_value_hkd", "HKD")
        elif source_dataset == "shkp_skeleton_historical_backtest":
            spec = ("model_underlying_profit_hkd_m", "actual_underlying_profit_hkd_m", "HKD m")
        elif source_dataset == "shkp_commercial_backtest":
            spec = ("forecast_rental_revenue_hkd_m", "actual_rental_revenue_hkd_m", "HKD m")
        else:
            raise ValueError(f"no value mapping for {key}")
    pred_col, actual_col, unit = spec
    index = int(row_status_row["source_row_index"])
    if index < 0 or index >= len(source):
        raise ValueError(f"source row index out of range for {row_status_row['row_key']}: {index}")
    source_row = source.iloc[index]
    predicted = source_row.get(pred_col)
    actual = source_row.get(actual_col)
    predicted_value = float(predicted) if pd.notna(predicted) else None
    actual_value = float(actual) if pd.notna(actual) else None
    return predicted_value, actual_value, unit, f"{pred_col},{actual_col}"


def _prior_period_start(period_type: str, period_start: str) -> str | None:
    try:
        start = pd.Timestamp(period_start)
    except (ValueError, TypeError):
        return None
    if period_type == "month":
        return str((start - pd.DateOffset(months=12)).date())
    if period_type in {"H1", "H2", "FY"}:
        return str((start - pd.DateOffset(years=1)).date())
    return None


def _build_baseline_rows(
    frame: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Same-period-last-year baselines, isolated by declared contract.

    Actuals may exist on a duplicate source alias even when that alias is not
    the primary source for scoring. Build the lookup from the complete frame,
    but keep the contract registry in the key so each baseline uses its own
    source contract's actual series.
    """
    actuals: dict[tuple[str, str, str, str, str, str], float] = {}
    canonical_actuals: dict[tuple[str, str, str, str, str], float] = {}
    source_priority = {
        "mtr_farebox_revenue_h1_backtest": 10,
        "airline_period_kpi_backtest": 10,
        "mtr_farebox_revenue_annual_backtest": 20,
        "airline_h1_kpi_backtest": 20,
    }
    canonical_candidates: dict[tuple[str, str, str, str, str], list[tuple[int, str, float]]] = {}
    for _, row in frame.iterrows():
        if row["has_actual"] and pd.notna(row["actual_value"]):
            source_dataset = str(row["source_dataset"])
            key = (
                str(row["registry_id"]),
                str(row["entity_id"]),
                str(row["target_id"]),
                str(row["target_period_type"]),
                str(row["track_id"]),
                str(row["target_period_start"]),
            )
            actuals[key] = float(row["actual_value"])
            economic_key = key[1:]
            canonical_candidates.setdefault(economic_key, []).append(
                (source_priority.get(source_dataset, 30), source_dataset, float(row["actual_value"]))
            )
    for key, candidates in canonical_candidates.items():
        canonical_actuals[key] = sorted(candidates, key=lambda item: (item[0], item[1]))[0][2]

    baseline_rows: list[dict[str, Any]] = []
    emitted_observations: set[tuple[str, str]] = set()
    primary = frame[frame["is_primary_source"]].copy()
    for _, row in primary.iterrows():
        if not (bool(row["is_primary_source"]) and bool(row["has_prediction"])):
            continue
        # The annual MTR Ridge rows are structural calibration aliases of the
        # physics track.  They have no headline accuracy output, so emitting
        # another identical baseline for them would create a false second
        # observation without adding a scored contract.
        if (
            str(row["source_dataset"]) == "mtr_farebox_revenue_annual_backtest"
            and str(row["model_id"]) == "mtr_ridge_residual_v1"
        ):
            continue
        prior_start = _prior_period_start(str(row["target_period_type"]), str(row["target_period_start"]))
        if prior_start is None:
            continue
        prior_key = (
            str(row["registry_id"]),
            str(row["entity_id"]),
            str(row["target_id"]),
            str(row["target_period_type"]),
            str(row["track_id"]),
            prior_start,
        )
        prior_actual = actuals.get(prior_key)
        if prior_actual is None:
            source_key = (
                str(row["entity_id"]),
                str(row["target_id"]),
                str(row["target_period_type"]),
                str(row["track_id"]),
                prior_start,
            )
            # A contract can start later than its actual series (e.g. v4).
            # Fall back to the deterministic canonical actual for the same
            # economic observation, never to row-order-dependent last write.
            prior_actual = canonical_actuals.get(source_key)
        if prior_actual is None:
            continue
        # Baselines are required per declared registry/model contract so each
        # challenger has a complete baseline series.  The MTR Ridge alias is
        # the one explicit exception above because it is not an evaluable
        # contract outside its structural calibration window.
        observation_key = (
            str(row["registry_id"]),
            str(row["logical_observation_id"]),
        )
        if observation_key in emitted_observations:
            continue
        emitted_observations.add(observation_key)
        baseline_row = dict(row)
        baseline_row["row_key"] = f"baseline:{row['registry_id']}:{row['logical_observation_id']}"
        baseline_row["model_id"] = BASELINE_MODEL_ID
        baseline_row["model_family"] = "same_period_last_year"
        baseline_row["is_baseline"] = True
        baseline_row["model_applied"] = True
        baseline_row["has_prediction"] = True
        baseline_row["has_actual"] = bool(row["has_actual"]) and pd.notna(row["actual_value"])
        baseline_row["predicted_value"] = prior_actual
        baseline_row["forecast_origin"] = "prior_actual"
        baseline_row["information_cutoff"] = ""
        baseline_row["source_observation_date"] = ""
        baseline_row["source_dataset"] = f"{row['source_dataset']}:baseline"
        baseline_row["input_bundle_id"] = row.get("input_bundle_id", "asia_backtest_input_bundle_v1")
        baseline_row["source_row_index"] = np.nan
        baseline_row["source_run_id"] = ""
        baseline_row["dedup_rank"] = 1
        baseline_row["is_primary_source"] = True
        baseline_row["dedup_group_id"] = f"{row['registry_id']}:{row['logical_observation_id']}:{BASELINE_MODEL_ID}"
        baseline_row["source_value_columns"] = "prior_actual,current_actual"
        baseline_row["source_caveat"] = ""
        baseline_row["source_row_fingerprint"] = _row_fingerprint(baseline_row)
        baseline_row["natural_observation_key"] = _natural_observation_key(baseline_row)
        baseline_rows.append(baseline_row)
    return baseline_rows


def _reconcile_dedup_groups(long_form: pd.DataFrame) -> list[dict[str, Any]]:
    """Assert value equality across duplicate source representations."""
    violations: list[dict[str, Any]] = []
    checks = 0
    for group_id, group in long_form.groupby("dedup_group_id", dropna=False):
        valued = group[
            group["predicted_value"].notna() | group["actual_value"].notna()
        ]
        if len(valued) < 2:
            continue
        sources = sorted(valued["source_dataset"].unique())
        for column in ("predicted_value", "actual_value"):
            values = valued.dropna(subset=[column])
            if len(values) < 2:
                continue
            checks += 1
            first_value = float(values[column].iloc[0])
            max_abs_diff = float(np.max(np.abs(values[column].astype(float) - first_value)))
            if max_abs_diff > 1e-6:
                violations.append(
                    {
                        "dedup_group_id": str(group_id),
                        "column": column,
                        "sources": sources,
                        "max_abs_diff": max_abs_diff,
                        "values": [
                            {"source": str(row["source_dataset"]), "value": float(row[column])}
                            for _, row in values.iterrows()
                        ],
                    }
                )
    return violations, checks


def _airline_overlap_reconciliation(long_form: pd.DataFrame) -> dict[str, Any]:
    """Reconcile every H1/period overlap, keeping different profit models apart."""
    left = long_form[
        long_form["source_dataset"].eq("airline_h1_kpi_backtest")
        & long_form["is_baseline"].eq(False)
    ].set_index("row_key")
    right = long_form[
        long_form["source_dataset"].eq("airline_period_kpi_backtest")
        & long_form["is_baseline"].eq(False)
    ]
    comparable = right[right["target_period_type"].eq("H1")].copy()
    model_counterpart = {
        "flat_ask_v1": "flat_ask_v1",
        "flat_rpk_v1": "flat_rpk_v1",
        "flat_ask_profit_v1": "flat_ask_residual_v1",
        "analyst_h1_nowcast_v1": None,
    }
    left["comparison_model_id"] = left["model_id"].map(model_counterpart)
    comparable["comparison_model_id"] = comparable["model_id"]
    left = left[left["comparison_model_id"].notna()]
    pairs = left.merge(
        comparable,
        on=["entity_id", "target_id", "target_period_start", "target_period_type", "comparison_model_id", "unit"],
        suffixes=("_h1", "_period"),
    )
    mismatches: list[dict[str, Any]] = []
    non_comparable = 0
    exact_model_pairs = 0
    for _, row in pairs.iterrows():
        if row["model_id_h1"] == row["model_id_period"]:
            exact_model_pairs += 1
            fields = ("predicted_value", "actual_value")
        else:
            # H1 profit and period profit are intentionally different model
            # specifications; actuals are the only comparable value.
            non_comparable += 1
            fields = ("actual_value",)
        for field in fields:
            left_value = row[f"{field}_h1"]
            right_value = row[f"{field}_period"]
            if pd.notna(left_value) and pd.notna(right_value) and abs(float(left_value) - float(right_value)) > 1e-6:
                mismatches.append(
                    {
                        "entity_id": row["entity_id"],
                        "target_id": row["target_id"],
                        "period_start": row["target_period_start"],
                        "model_id": row["model_id"],
                        "field": field,
                        "h1": float(left_value),
                        "period_value": float(right_value),
                    }
                )
    # The expected overlap is derived from the current two source tables. A
    # source can legitimately add a new current forecast before the other
    # table catches up; that is reported separately rather than failing the
    # historical value reconciliation.
    expected_pairs = int(len(pairs))
    complete_pairs = pairs[
        pairs[["actual_value_h1", "actual_value_period"]].notna().all(axis=1)
    ]
    comparable_observations = int(len(complete_pairs))
    # Expected model-family counts describe all source overlaps, including
    # current rows whose actual is not yet available. Keep that separate from
    # complete-pair counts so a new current forecast is not misreported as a
    # model-family mismatch.
    expected_exact_model_pairs = int(
        pairs["model_id_h1"].eq(pairs["model_id_period"]).sum()
    )
    expected_non_comparable_pairs = int(len(pairs) - expected_exact_model_pairs)
    return {
        "pairs": int(len(pairs)),
        "expected_pairs": expected_pairs,
        "complete_pairs": comparable_observations,
        "incomplete_current_pairs": expected_pairs - comparable_observations,
        "expected_exact_model_pairs": expected_exact_model_pairs,
        "expected_non_comparable_model_pairs": expected_non_comparable_pairs,
        "exact_model_pairs": exact_model_pairs,
        "non_comparable_model_pairs": non_comparable,
        "mismatches": mismatches,
        "passed": len(mismatches) == 0,
    }


def _legacy_metric_compare(long_form: pd.DataFrame) -> list[dict[str, Any]]:
    """Informational MAPE comparison against the legacy summary tables."""
    diffs: list[dict[str, Any]] = []
    norm = ROOT / "data" / "normalized" / "hk_transport"
    evaluated = long_form[
        (long_form["is_primary_source"])
        & (long_form["is_baseline"] == False)  # noqa: E712
        & (long_form["evaluation_status"].isin(("valid_oos", "valid_practical_oos", "valid_forward_oos")))
        & (long_form["pit_grade"].isin(("A_strict_pit", "B_practical_pit")))
        & (long_form["predicted_value"].notna())
        & (long_form["actual_value"].notna())
        & (long_form["actual_value"] != 0)
    ].copy()
    evaluated["abs_pct_error"] = (
        (evaluated["predicted_value"] - evaluated["actual_value"]).abs() / evaluated["actual_value"].abs() * 100.0
    )

    checks: list[tuple[str, str, str, str, str]] = [
        (
            "airline_h1_kpi_backtest",
            "revenue",
            "flat_ask_v1",
            "revenue_flat_ask_mae_pct",
            "airline_h1_kpi_backtest_summary.csv",
        ),
        (
            "airline_h1_kpi_backtest",
            "operating_cost",
            "flat_ask_v1",
            "operating_cost_flat_ask_mae_pct",
            "airline_h1_kpi_backtest_summary.csv",
        ),
        (
            "airline_period_kpi_backtest",
            "revenue",
            "flat_ask_v1",
            "revenue_flat_ask_mae_pct",
            "airline_period_kpi_backtest_summary.csv",
        ),
        (
            "airline_period_kpi_backtest",
            "revenue",
            "flat_rpk_v1",
            "revenue_flat_rpk_mae_pct",
            "airline_period_kpi_backtest_summary.csv",
        ),
        (
            "airline_period_kpi_backtest",
            "operating_cost",
            "flat_ask_v1",
            "operating_cost_flat_ask_mae_pct",
            "airline_period_kpi_backtest_summary.csv",
        ),
    ]
    for source_dataset, target_id, model_id, legacy_column, summary_name in checks:
        summary_path = norm / summary_name
        if not summary_path.exists():
            continue
        summary = _read_csv(summary_path)
        if legacy_column not in summary.columns:
            continue
        rows = evaluated[
            (evaluated["source_dataset"] == source_dataset)
            & (evaluated["target_id"] == target_id)
            & (evaluated["model_id"] == model_id)
        ]
        if rows.empty:
            if source_dataset == "airline_h1_kpi_backtest":
                # Period-priority dedup intentionally keeps the overlapping
                # H1 source rows as non-primary aliases. Reconcile the legacy
                # H1 summary against those source rows anyway, but do not
                # promote them into the headline metric population.
                source_rows = long_form[
                    (long_form["source_dataset"] == source_dataset)
                    & (long_form["is_baseline"] == False)  # noqa: E712
                    & (long_form["target_id"] == target_id)
                    & (long_form["model_id"] == model_id)
                    & (long_form["predicted_value"].notna())
                    & (long_form["actual_value"].notna())
                    & (long_form["actual_value"] != 0)
                ].copy()
                if not source_rows.empty:
                    source_rows["abs_pct_error"] = (
                        (source_rows["predicted_value"] - source_rows["actual_value"]).abs()
                        / source_rows["actual_value"].abs()
                        * 100.0
                    )
                    computed = float(source_rows.groupby("entity_id")["abs_pct_error"].mean().mean())
                    legacy = float(summary[legacy_column].mean())
                    diffs.append(
                        {
                            "source_dataset": source_dataset,
                            "target_id": target_id,
                            "model_id": model_id,
                            "legacy_source": summary_name,
                            "legacy_column": legacy_column,
                            "legacy_mean_mae_pct": legacy,
                            "computed_mean_mae_pct": computed,
                            "abs_diff_pp": abs(computed - legacy),
                            "note": (
                                "Source-only reconciliation: H1 rows are non-primary aliases under "
                                "period-priority dedup and therefore are not headline metric rows."
                            ),
                        }
                    )
                    continue
            diffs.append(
                {
                    "source_dataset": source_dataset,
                    "target_id": target_id,
                    "model_id": model_id,
                    "legacy_source": summary_name,
                    "legacy_column": legacy_column,
                    "legacy_mean_mae_pct": None,
                    "computed_mean_mae_pct": None,
                    "abs_diff_pp": None,
                    "note": (
                        "Skipped: no primary evaluated long-form rows for this source "
                        "(rows are non-primary duplicates under period-priority dedup)."
                    ),
                }
            )
            continue
        computed = float(rows.groupby("entity_id")["abs_pct_error"].mean().mean())
        legacy = float(summary[legacy_column].mean())
        diffs.append(
            {
                "source_dataset": source_dataset,
                "target_id": target_id,
                "model_id": model_id,
                "legacy_source": summary_name,
                "legacy_column": legacy_column,
                "legacy_mean_mae_pct": legacy,
                "computed_mean_mae_pct": computed,
                "abs_diff_pp": abs(computed - legacy),
                "note": (
                    "Informational: legacy summaries may use a narrower evaluated window "
                    "or a different per-company weighting."
                ),
            }
        )
    return diffs


def build_long_form(
    *,
    write_outputs: bool = True,
    write_run_store: bool = True,
) -> dict[str, Any]:
    row_status = _read_csv(ROW_STATUS_CSV)
    input_bundle_id, input_bundle_payload, input_paths = _input_bundle(row_status)
    sources = _load_sources(row_status)

    records: list[dict[str, Any]] = []
    for _, row in row_status.iterrows():
        source = sources.get(str(row["source_dataset"]))
        if source is None:
            raise ValueError(f"missing source frame for {row['source_dataset']}")
        predicted, actual, unit, value_columns = _value_for(row, source)
        source_caveat = ""
        index = int(row["source_row_index"])
        if 0 <= index < len(source) and "caveat" in source.columns:
            caveat = source.iloc[index].get("caveat")
            source_caveat = str(caveat) if pd.notna(caveat) else ""
        source_row = source.iloc[index] if 0 <= index < len(source) else pd.Series(dtype="object")
        model_family = _model_family(str(row["source_dataset"]), str(row["model_id"]), source_row)
        observation_date = _source_observation_date(source, index)
        record = {
            "engine_version": ENGINE_VERSION,
            "registry_id": row["registry_id"],
            "row_key": row["row_key"],
            "logical_observation_id": row["logical_observation_id"],
            "dedup_group_id": row["dedup_group_id"],
            "dedup_rank": int(row["dedup_rank"]) if pd.notna(row["dedup_rank"]) else 1,
            "is_primary_source": _flag(row["is_primary_source"]),
            "source_dataset": row["source_dataset"],
            "source_run_id": row["source_run_id"] if pd.notna(row["source_run_id"]) else "",
            "input_bundle_id": input_bundle_id,
            "source_row_index": index,
            "source_row_fingerprint": "",
            "natural_observation_key": "",
            "entity_id": row["entity_id"],
            "target_id": row["target_id"],
            "target_period_start": row["target_period_start"],
            "target_period_end": row["target_period_end"],
            "target_period_type": row["target_period_type"],
            "track_id": row["track_id"],
            "model_id": row["model_id"],
            "model_family": model_family,
            "is_baseline": False,
            "model_applied": _flag(row["model_applied"]),
            "forecast_origin": row["forecast_origin"] if pd.notna(row["forecast_origin"]) else "",
            "information_cutoff": row["information_cutoff"] if pd.notna(row["information_cutoff"]) else "",
            "source_observation_date": observation_date,
            "actual_available_at": row["actual_available_at"] if pd.notna(row["actual_available_at"]) else "",
            "actual_source_url": row.get("actual_source_url", "") if pd.notna(row.get("actual_source_url", "")) else "",
            "predicted_value": predicted,
            "actual_value": actual,
            "unit": unit,
            "source_value_columns": value_columns,
            "source_row_status": row["source_row_status"] if pd.notna(row["source_row_status"]) else "",
            "input_pit_status": row["input_pit_status"] if pd.notna(row["input_pit_status"]) else "",
            "target_pit_status": row["target_pit_status"] if pd.notna(row["target_pit_status"]) else "",
            "pit_grade": row["pit_grade"],
            "evaluation_status": row["evaluation_status"],
            "has_prediction": _flag(row["has_prediction"]),
            "has_actual": _flag(row["has_actual"]),
            "imputation_used": _flag(row["imputation_used"]),
            "dependency_status": row["dependency_status"] if pd.notna(row["dependency_status"]) else "",
            "scenario": row["scenario"] if pd.notna(row["scenario"]) else "",
            "lookback_months": row["lookback_months"] if pd.notna(row["lookback_months"]) else "",
            "model_use": row["model_use"] if pd.notna(row["model_use"]) else "",
            "research_only": _research_only_value(row["research_only"]),
            "source_caveat": source_caveat,
            "notes": row["notes"] if pd.notna(row["notes"]) else "",
        }
        record["source_row_fingerprint"] = _row_fingerprint(record)
        record["natural_observation_key"] = _natural_observation_key(record)
        records.append(record)

    frame = pd.DataFrame.from_records(records)
    frame["predicted_value"] = pd.to_numeric(frame["predicted_value"], errors="coerce")
    frame["actual_value"] = pd.to_numeric(frame["actual_value"], errors="coerce")

    primary = frame[frame["is_primary_source"]].copy()
    baseline_rows = _build_baseline_rows(frame)
    if baseline_rows:
        frame = pd.concat([frame, pd.DataFrame.from_records(baseline_rows)], ignore_index=True)

    for column in STRING_COLUMNS:
        if column in frame.columns:
            frame[column] = (
                frame[column]
                .astype("string")
                .replace(r"^\s*$", pd.NA, regex=True)
                .fillna("not_captured")
            )

    # model_applied must gate predictions (e.g. MTR ridge zero-adjust rows).
    frame.loc[~frame["model_applied"], ["predicted_value", "has_prediction"]] = [np.nan, False]
    _assert_mtr_contract(frame)
    frame["input_bundle_id"] = input_bundle_id
    frame["source_row_fingerprint"] = frame.apply(
        lambda row: _row_fingerprint(row.to_dict()), axis=1
    )
    frame["natural_observation_key"] = frame.apply(
        lambda row: _natural_observation_key(row.to_dict()), axis=1
    )
    if frame["input_bundle_id"].nunique() != 1:
        raise ValueError("long-form rows must carry one input bundle ID")

    validate_long_form(frame)
    check_period_type_consistency(frame)
    violations, checks = _reconcile_dedup_groups(frame)
    legacy_diffs = _legacy_metric_compare(frame)
    airline_overlap = _airline_overlap_reconciliation(frame)
    metrics = compute_metric_table(frame)
    intervals = compute_error_intervals(frame, metrics=metrics)
    metrics_manifest = build_metrics_manifest(frame, metrics, intervals)
    metrics["input_bundle_id"] = input_bundle_id
    structural_counts = (
        frame[frame["pit_grade"].eq("C_structural_replay")]
        .groupby(["registry_id"], dropna=False)
        .size()
        .to_dict()
    )

    reconciliation = {
        "engine_version": ENGINE_VERSION,
        "contract_version": "asia_backtest_reconciliation_v1",
        "rows": int(len(frame)),
        "primary_rows": int(len(primary)),
        "baseline_rows": int(len(baseline_rows)),
        "dedup_value_checks": checks,
        "dedup_violations": violations,
        "airline_overlap_reconciliation": airline_overlap,
        "legacy_metric_diffs": legacy_diffs,
        "hard_gate_passed": not violations and bool(airline_overlap["passed"]),
        "input_bundle_id": input_bundle_id,
        "input_bundle": input_bundle_payload,
        "metrics_rows": int(len(metrics)),
        "structural_rows_excluded_from_accuracy": int(frame["pit_grade"].eq("C_structural_replay").sum()),
        "structural_counts_by_registry": {str(k): int(v) for k, v in structural_counts.items()},
    }

    if write_run_store:
        fingerprints = {
            _repo_relative(path): file_fingerprint(path)
            for path in input_paths
            if path.exists()
        }
        spec = BacktestRunSpec(
            engine_version=ENGINE_VERSION,
            config={
                "mode": "long_form_emitter",
                "schema": "asia_backtest_long_form_v1_9",
                "metric_policy": METRIC_POLICY_VERSION,
                "input_bundle_id": input_bundle_id,
                "reconciliation_status": "ready" if reconciliation["hard_gate_passed"] else "reconciliation_failed",
                "runtime": runtime_metadata(),
            },
            input_fingerprints=fingerprints,
            parent_run_ids=tuple(sorted(row_status["source_run_id"].dropna().astype(str).unique())),
        )
        store = RunArtifactStore(REGISTRY_DIR / "runs", spec)
        data_path = store.write_dataframe("asia_backtest_long_form", frame)
        data_parquet_path = store.write_parquet("asia_backtest_long_form", frame)
        metrics_path = store.write_dataframe("asia_backtest_metrics", metrics)
        metrics_parquet_path = store.write_parquet("asia_backtest_metrics", metrics)
        intervals_path = store.write_dataframe("asia_backtest_metric_intervals", intervals)
        intervals_parquet_path = store.write_parquet("asia_backtest_metric_intervals", intervals)
        metrics_manifest_path = store.write_json("asia_backtest_metrics_manifest", metrics_manifest)
        recon_path = store.write_json("reconciliation", reconciliation)
        bundle_path = store.write_json("input_bundle", input_bundle_payload)
        manifest_path = store.write_manifest(
            artifacts={
                "long_form_csv": data_path,
                "long_form_parquet": data_parquet_path,
                "metrics_csv": metrics_path,
                "metrics_parquet": metrics_parquet_path,
                "metric_intervals_csv": intervals_path,
                "metric_intervals_parquet": intervals_parquet_path,
                "metrics_manifest": metrics_manifest_path,
                "reconciliation": recon_path,
                "input_bundle": bundle_path,
            },
            counts={
                "rows": int(len(frame)),
                "primary_rows": int(len(primary)),
                "baseline_rows": int(len(baseline_rows)),
                "dedup_value_checks": checks,
                "dedup_violations": len(violations),
                "metrics_rows": int(len(metrics)),
                "interval_rows": int(len(intervals)),
            },
            caveats=[
                "Additive long-form emission; wide tables and dashboards are unchanged.",
                "Baseline rows use prior-period actuals and are flagged is_baseline=True.",
            ],
            status="ready" if reconciliation["hard_gate_passed"] else "reconciliation_failed",
        )

    # Publish compatibility files only after the immutable run artifacts and
    # ready manifest have been written. A failed run must never overwrite the
    # current top-level consumer files.
    if write_outputs and reconciliation["hard_gate_passed"]:
        with tempfile.TemporaryDirectory(dir=REGISTRY_DIR) as temp_dir:
            temp_root = Path(temp_dir)
            temp_long_csv = temp_root / LONG_FORM_CSV.name
            temp_long_parquet = temp_root / LONG_FORM_PARQUET.name
            temp_metrics_csv = temp_root / METRICS_CSV.name
            temp_metrics_parquet = temp_root / METRICS_PARQUET.name
            temp_intervals_csv = temp_root / INTERVALS_CSV.name
            temp_intervals_parquet = temp_root / INTERVALS_PARQUET.name
            temp_metrics_manifest = temp_root / METRICS_MANIFEST_JSON.name
            temp_input_bundle = temp_root / INPUT_BUNDLE_JSON.name
            temp_reconciliation = temp_root / RECONCILIATION_JSON.name
            frame.to_csv(temp_long_csv, index=False)
            frame.to_parquet(temp_long_parquet, index=False)
            metrics.to_csv(temp_metrics_csv, index=False)
            metrics.to_parquet(temp_metrics_parquet, index=False)
            intervals.to_csv(temp_intervals_csv, index=False)
            intervals.to_parquet(temp_intervals_parquet, index=False)
            temp_metrics_manifest.write_text(
                json.dumps(metrics_manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp_input_bundle.write_text(
                json.dumps(input_bundle_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp_reconciliation.write_text(
                json.dumps(reconciliation, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            _publish_compatibility_outputs(
                {
                    temp_long_csv: LONG_FORM_CSV,
                    temp_long_parquet: LONG_FORM_PARQUET,
                    temp_metrics_csv: METRICS_CSV,
                    temp_metrics_parquet: METRICS_PARQUET,
                    temp_intervals_csv: INTERVALS_CSV,
                    temp_intervals_parquet: INTERVALS_PARQUET,
                    temp_metrics_manifest: METRICS_MANIFEST_JSON,
                    temp_input_bundle: INPUT_BUNDLE_JSON,
                    temp_reconciliation: RECONCILIATION_JSON,
                }
            )
            if write_run_store:
                store.write_latest_pointer(manifest_path)

    return reconciliation


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the additive long-form backtest table")
    parser.add_argument("--no-run-store", action="store_true", help="skip the run-scoped store copy")
    args = parser.parse_args()
    reconciliation = build_long_form(write_run_store=not args.no_run_store)
    if not reconciliation["hard_gate_passed"]:
        print("[long-form] FAIL: reconciliation hard gate failed")
        print(f"  dedup violations: {len(reconciliation['dedup_violations'])}")
        print(f"  airline overlap: {reconciliation['airline_overlap_reconciliation']}")
        for violation in reconciliation["dedup_violations"][:10]:
            print(f"  {violation['dedup_group_id']} {violation['column']} diff={violation['max_abs_diff']:.6g}")
        return 1
    print(
        f"[long-form] ok: {reconciliation['rows']} rows "
        f"({reconciliation['primary_rows']} primary, {reconciliation['baseline_rows']} baseline), "
        f"{reconciliation['dedup_value_checks']} dedup value checks passed"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
