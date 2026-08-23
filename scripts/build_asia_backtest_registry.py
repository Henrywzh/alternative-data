#!/usr/bin/env python3
"""Build the Step 1 registry for the Asia Markets forecast backtests.

This is deliberately a metadata-only bridge.  It does not run a model, alter
an existing wide backtest table, or publish anything to either dashboard.  It
turns the current MTR, Airlines, and SHKP outputs into two small registry
tables:

* ``asia_backtest_target_registry.csv`` — one row per target/track/model
  contract with sample counts and pre-metric-policy candidate status. The
  final headline decision is emitted by the value-bearing metrics artifact.
* ``asia_backtest_row_status.csv`` — one metadata row per source row/model
  combination.  Prediction and actual values are intentionally omitted.

The registry is the input contract for the later additive long-form emitter.
It also makes known limitations explicit: MTR's 2026 H1 value is not a FY
value, SHKP contract activity is diagnostic-only, and SHKP input run sets are
not currently captured as one coherent dependency bundle.
"""

from __future__ import annotations

import argparse
import json
import re
import os
import sys
from calendar import monthrange
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.backtest.storage import dataframe_fingerprint
from src.common.backtest.vocabulary import (
    EVALUABLE_STATUSES,
    MIN_DIRECTIONAL_HIT_RATE_ROWS,
    MIN_HEADLINE_ROWS,
    is_headline_grade,
)

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
REGISTRY_VERSION = "asia_backtest_registry_v2"

TARGET_OUTPUT = "asia_backtest_target_registry.csv"
ROW_OUTPUT = "asia_backtest_row_status.csv"
DOC_OUTPUT = "asia_backtest_document_registry.csv"
MANIFEST_OUTPUT = "asia_backtest_registry_manifest.json"

def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def _latest_shkp_frame(dataset_name: str) -> tuple[pd.DataFrame, str, dict[str, Any]]:
    dataset_dir = ROOT / "data" / "normalized" / "hk_real_estate" / dataset_name
    candidates = list(dataset_dir.glob("*/*.parquet")) if dataset_dir.exists() else []
    if not candidates:
        return pd.DataFrame(), "", {}

    def sort_key(path: Path) -> tuple[str, float, str]:
        lineage_path = path.parent / "lineage.json"
        created_at = ""
        if lineage_path.exists():
            try:
                created_at = str(json.loads(lineage_path.read_text()).get("created_at") or "")
            except (OSError, ValueError, TypeError):
                pass
        return (created_at, path.stat().st_mtime, path.parent.name)

    path = max(candidates, key=sort_key)
    lineage_path = path.parent / "lineage.json"
    lineage: dict[str, Any] = {}
    if lineage_path.exists():
        try:
            lineage = json.loads(lineage_path.read_text())
        except (OSError, ValueError, TypeError):
            lineage = {}
    return pd.read_parquet(path), path.parent.name, lineage


def _date_bounds(
    period_type: str,
    value: Any,
    *,
    shkp_fiscal: bool = False,
    period_end_override: Any = None,
) -> tuple[str | None, str | None]:
    if value is None or pd.isna(value):
        return None, None
    if period_type == "FY":
        year = int(value)
        if shkp_fiscal:
            return f"{year - 1:04d}-07-01", f"{year:04d}-06-30"
        return f"{year:04d}-01-01", f"{year:04d}-12-31"
    if period_type == "H1" and period_end_override is not None:
        year = int(value)
        end = pd.to_datetime(period_end_override, errors="coerce")
        if pd.notna(end):
            return f"{year:04d}-01-01", end.strftime("%Y-%m-%d")
    if period_type == "H1":
        year = int(value)
        return f"{year:04d}-01-01", f"{year:04d}-06-30"
    if period_type == "H2":
        year = int(value)
        return f"{year:04d}-07-01", f"{year:04d}-12-31"
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None, None
    last_day = monthrange(int(parsed.year), int(parsed.month))[1]
    return parsed.strftime("%Y-%m-01"), f"{parsed.year:04d}-{parsed.month:02d}-{last_day:02d}"


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or pd.isna(value):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "t"}


def _notna(value: Any) -> bool:
    try:
        return bool(pd.notna(value))
    except (TypeError, ValueError):
        return False


def _metadata_value(value: Any) -> str:
    if not _notna(value):
        return "not_captured"
    text = str(value).strip()
    return text if text and text.lower() not in {"none", "nan"} else "not_captured"


def _metadata_bool(value: Any) -> str:
    if not _notna(value):
        return "not_captured"
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "t"}:
        return "true"
    if text in {"0", "false", "no", "n", "f"}:
        return "false"
    return "not_captured"


def _row_status(
    *,
    registry_id: str,
    source_dataset: str,
    source_run_id: str,
    source_row_index: int,
    entity_id: str,
    target_id: str,
    period_type: str,
    track_id: str,
    period_value: Any,
    source_row_status: str,
    input_pit_status: str,
    target_pit_status: str,
    pit_grade: str,
    evaluation_status: str,
    has_prediction: bool,
    has_actual: bool,
    actual_available_at: Any,
    actual_source_url: Any = None,
    imputation_used: bool,
    dependency_status: str,
    model_id: str,
    shkp_fiscal: bool = False,
    forecast_origin: Any = None,
    information_cutoff: Any = None,
    scenario: Any = None,
    lookback_months: Any = None,
    model_use: Any = None,
    research_only: Any = None,
    model_applied: Any = None,
    period_end_override: Any = None,
    notes: str = "",
) -> dict[str, Any]:
    start, end = _date_bounds(
        period_type,
        period_value,
        shkp_fiscal=shkp_fiscal,
        period_end_override=period_end_override,
    )
    return {
        "registry_id": registry_id,
        "source_dataset": source_dataset,
        "source_run_id": source_run_id,
        "source_row_index": int(source_row_index),
        "entity_id": entity_id,
        "target_id": target_id,
        "target_period_start": start,
        "target_period_end": end,
        "target_period_type": period_type,
        "track_id": track_id,
        "model_id": model_id,
        "source_row_status": source_row_status,
        "input_pit_status": input_pit_status,
        "target_pit_status": target_pit_status,
        "pit_grade": pit_grade,
        "evaluation_status": evaluation_status,
        "row_key": f"{source_dataset}:{int(source_row_index)}:{target_id}:{model_id}",
        "logical_observation_id": f"{entity_id}:{target_id}:{period_type}:{start or period_value}",
        "forecast_origin": _metadata_value(forecast_origin),
        "information_cutoff": _metadata_value(information_cutoff),
        "scenario": _metadata_value(scenario),
        "lookback_months": _metadata_value(lookback_months),
        "model_use": _metadata_value(model_use),
        "research_only": _metadata_bool(research_only),
        "model_applied": bool(has_prediction if model_applied is None else model_applied),
        "has_prediction": bool(has_prediction),
        "has_actual": bool(has_actual),
        "actual_available_at": None if not _notna(actual_available_at) else str(actual_available_at),
        "actual_source_url": None if not _notna(actual_source_url) else str(actual_source_url),
        "imputation_used": bool(imputation_used),
        "dependency_status": dependency_status,
        "notes": notes,
    }


def _mtr_status(
    row: pd.Series,
    *,
    period_type: str,
    current_forecast: bool = False,
) -> tuple[str, str, str, str, bool, bool, str]:
    year = int(row["year"])
    actual_column = "transport_ops_revenue_hkdm" if period_type == "FY" else "h1_actual_transport_ops_revenue_hkdm"
    has_actual = _notna(row.get(actual_column))

    if current_forecast and not has_actual:
        if period_type == "YTD":
            return (
                "current_forecast",
                "B_practical_pit",
                "forecast_only",
                "not_captured",
                False,
                True,
                "Current year-to-date model output; the partial-period actual is not yet available.",
            )
        return (
            "current_forecast",
            "B_practical_pit",
            "forecast_only",
            "not_captured",
            False,
            True,
            "Current H1 forecast awaiting the official interim actual.",
        )

    if period_type == "FY":
        if not has_actual:
            return "model_only", "D_diagnostic_only", "no_source_coverage", "not_captured", False, True, "No official annual actual is present for this year."
        role = "calibration_year" if year == 2024 else "practical_forward_validation" if year >= 2025 else "historical_structural_check"
        status = "valid_practical_oos" if role == "practical_forward_validation" else role
        grade = "B_practical_pit" if year >= 2025 else "C_structural_replay"
        return role, grade, status, "not_captured", False, True, "FY2024 segment-yield calibration is used for 2019-2024; those rows are structural checks, not strict PIT/OOS."

    role = str(row.get("backtest_role") or "")
    if year < 2017 and not has_actual:
        return "model_only", "D_diagnostic_only", "no_source_coverage", "not_captured", False, True, "No official H1 actual coverage in the current source contract."
    if period_type not in {"H1", "H2"}:
        raise ValueError(f"Unsupported MTR partial period type: {period_type}")
    if role in {"true_forward_oos", "true_forward_validation"}:
        # Backward-compatible normalization for previously generated wide
        # tables; this model is practical validation, not strict OOS.
        role = "practical_forward_validation"
    if has_actual and role == "current_forecast":
        role = "practical_forward_validation"
    status = "valid_practical_oos" if role == "practical_forward_validation" else role or "historical_evaluated"
    grade = "B_practical_pit" if year >= 2025 else "C_structural_replay"
    return role or "historical_evaluated", grade, status, "not_captured", False, True, "FY2024 segment-yield calibration is used for 2017-2024; those rows are structural checks, not strict PIT/OOS."


def _airline_pit_grade(row: pd.Series) -> str:
    target = _first_present(row, ("target_actual_pit_status", "target_financial_pit_status"))
    if "issuer_announcement_date_available" in target and not _bool(row.get("kpi_future_imputation_used")):
        return "A_strict_pit"
    if "period_end_only" in target or "derived_from_period_end" in target:
        return "B_practical_pit"
    if "pending" in target:
        return "B_practical_pit"
    return "C_structural_replay"


def _airline_eval_status(row: pd.Series, *, has_actual: bool, pit_grade: str) -> str:
    source_status = str(row.get("row_status") or "")
    if source_status.startswith("current_") or "nowcast" in source_status:
        return "forecast_only"
    if "insufficient" in source_status:
        return "insufficient_input_coverage"
    if not has_actual:
        return "forecast_only"
    return "valid_oos" if pit_grade == "A_strict_pit" else "valid_practical_oos"


def _first_present(row: pd.Series, columns: Iterable[str], default: str = "not_captured") -> str:
    for column in columns:
        value = row.get(column)
        if _notna(value) and str(value) not in {"", "None", "nan"}:
            return str(value)
    return default


def _airline_input_pit_status(row: pd.Series) -> str:
    value = _first_present(row, ("kpi_pit_safe", "kpi_pit_safe_for_h1_event"))
    if value in {"True", "true", "1"}:
        return "safe"
    if value in {"False", "false", "0"}:
        return "not_safe"
    return value


def _models_for_columns(columns: Iterable[str], specs: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    available: list[tuple[str, str]] = []
    column_set = set(columns)
    for model_id, column in specs:
        if column in column_set:
            available.append((model_id, column))
    return available


def _mtr_model_applied(row: pd.Series, model_id: str, prediction: bool) -> bool:
    if not prediction:
        return False
    if model_id != "mtr_ridge_residual_v1":
        return True
    adjustment = row.get("ridge_residual_adj_hkdm")
    return _notna(adjustment) and float(adjustment) != 0.0


def build_mtr_rows() -> list[dict[str, Any]]:
    annual_path = ROOT / "data" / "processed" / "transport" / "mtr_farebox_revenue_annual_backtest.csv"
    h1_path = ROOT / "data" / "processed" / "transport" / "mtr_farebox_revenue_h1_backtest.csv"
    canonical_actuals = _read_csv(
        ROOT / "data" / "normalized" / "hk_transport" / "mtr_transport_ops_actuals.csv"
    )
    if canonical_actuals.empty:
        raise ValueError("MTR canonical actuals are required to build MTR provenance")
    required_provenance = {
        "period_type",
        "year",
        "actual_value_hkdm",
        "actual_available_at",
        "release_source_url",
    }
    missing_provenance = sorted(required_provenance - set(canonical_actuals.columns))
    if missing_provenance:
        raise ValueError(f"MTR canonical actuals are missing provenance columns: {missing_provenance}")
    if canonical_actuals.duplicated(["period_type", "year"]).any():
        raise ValueError("MTR canonical actuals contain duplicate period_type/year rows")
    if (
        canonical_actuals["actual_available_at"].isna().any()
        or ~canonical_actuals["release_source_url"].astype(str).str.startswith("https://").all()
    ):
        raise ValueError("MTR canonical actuals contain invalid release provenance")
    provenance = canonical_actuals.set_index(
        ["period_type", canonical_actuals["year"].astype(int)]
    )
    rows: list[dict[str, Any]] = []
    for period_type, path, model_specs in [
        (
            "FY",
            annual_path,
            (("mtr_physics_yield_v1", "farebox_revenue_hkdm"), ("mtr_ridge_residual_v1", "ridge_adjusted_revenue_hkdm")),
        ),
        ("H1", h1_path, (("mtr_physics_yield_v1", "h1_model_revenue_hkdm"),)),
    ]:
        frame = _read_csv(path)
        if frame.empty:
            continue
        dataset = path.stem
        current_h1_years = set()
        if period_type == "H1" and "actual_status" in frame.columns:
            current_h1_years = set(
                frame.loc[
                    frame["actual_status"].eq("not_yet_reported") & frame["year"].ge(2017),
                    "year",
                ].astype(int)
            )
        for index, row in frame.iterrows():
            actual_column = "transport_ops_revenue_hkdm" if period_type == "FY" else "h1_actual_transport_ops_revenue_hkdm"
            prediction_probe = "farebox_revenue_hkdm" if period_type == "FY" else "h1_model_revenue_hkdm"
            source_actual = row.get(actual_column)
            partial_candidate = period_type == "FY" and (
                str(row.get("period_status") or "") == "partial_ytd"
                or (
                    int(row["year"]) == int(frame["year"].max())
                    and not _notna(source_actual)
                    and _notna(row.get(prediction_probe))
                )
            )
            canonical_period_type = "H1" if partial_candidate else period_type
            try:
                canonical_actual = canonical_actuals.loc[
                    canonical_actuals["period_type"].eq(canonical_period_type)
                    & canonical_actuals["year"].astype(int).eq(int(row["year"])),
                    "actual_value_hkdm",
                ].iloc[0]
            except IndexError:
                canonical_actual = None
            if partial_candidate and not _notna(canonical_actual):
                fy_actual_exists = canonical_actuals["period_type"].eq("FY") & canonical_actuals["year"].astype(int).eq(int(row["year"]))
                if fy_actual_exists.any():
                    raise ValueError(
                        f"MTR partial H1/YTD row has only a FY canonical actual; rebuild the H1 source before registry emission: {dataset} {row['year']}"
                    )
            if _notna(source_actual) and not _notna(canonical_actual):
                raise ValueError(
                    f"MTR processed output has an actual absent from canonical actuals: {dataset} {row['year']}"
                )
            if _notna(source_actual) and _notna(canonical_actual) and abs(float(source_actual) - float(canonical_actual)) > 1e-6:
                raise ValueError(
                    f"MTR actual diverges from canonical actuals: {dataset} {row['year']} "
                    f"processed={source_actual} canonical={canonical_actual}"
                )
            resolved_actual = canonical_actual if _notna(canonical_actual) else None
            row_for_status = row.copy()
            row_for_status[actual_column] = resolved_actual
            if canonical_period_type == "H1":
                row_for_status["h1_actual_transport_ops_revenue_hkdm"] = resolved_actual
            if partial_candidate:
                row_for_status["backtest_role"] = "practical_forward_validation" if _notna(resolved_actual) else "current_forecast"
            is_partial_ytd = partial_candidate
            current_forecast = is_partial_ytd or (
                period_type == "H1" and int(row["year"]) in current_h1_years and not _notna(resolved_actual)
            )
            # The annual source's partial current-year value is an H1/YTD
            # observation. Keep the shared period vocabulary at H1; the
            # ytd_current track carries the incomplete-period semantics.
            row_period_type = "H1" if is_partial_ytd else period_type
            row_track_id = (
                "ytd_current"
                if is_partial_ytd
                else ("fiscal_year" if period_type == "FY" else "half_year_non_overlapping")
            )
            has_actual = _notna(resolved_actual)
            if is_partial_ytd and _notna(source_actual):
                raise ValueError(f"MTR partial-period row unexpectedly has a full-period actual: {dataset} {row['year']}")
            actual_period_type = "H1" if is_partial_ytd else period_type
            try:
                canonical_provenance = provenance.loc[(actual_period_type, int(row["year"]))]
            except KeyError:
                canonical_provenance = pd.Series(dtype="object")
            actual_available = (
                row.get("actual_available_at")
                if _notna(row.get("actual_available_at"))
                else canonical_provenance.get("actual_available_at")
            )
            actual_source_url = (
                row.get("release_source_url")
                if _notna(row.get("release_source_url"))
                else canonical_provenance.get("release_source_url")
            )
            status, grade, evaluation, dependency, imputation, prediction, notes = _mtr_status(
                row_for_status,
                period_type="H1" if is_partial_ytd else row_period_type,
                current_forecast=current_forecast,
            )
            for model_id, prediction_column in _models_for_columns(frame.columns, model_specs):
                model_applied = _mtr_model_applied(row, model_id, _notna(row.get(prediction_column)) and prediction)
                registry_id = f"{dataset}:{row_period_type}:{row_track_id}:{model_id}"
                rows.append(
                    _row_status(
                        registry_id=registry_id,
                        source_dataset=dataset,
                        source_run_id="",
                        source_row_index=int(index),
                        entity_id="MTR",
                        target_id="transport_operations_revenue",
                        period_type=row_period_type,
                        track_id=row_track_id,
                        period_value=row["year"],
                        source_row_status=status,
                        input_pit_status="not_captured",
                        target_pit_status="reported_actual" if has_actual else "not_available",
                        pit_grade=grade,
                        evaluation_status=evaluation,
                        has_prediction=model_applied,
                        has_actual=has_actual,
                        actual_available_at=actual_available if has_actual else None,
                        actual_source_url=actual_source_url if has_actual else None,
                        imputation_used=imputation,
                        dependency_status=dependency,
                        model_id=model_id,
                        model_applied=model_applied,
                        period_end_override=row.get("coverage_end") if is_partial_ytd else None,
                        notes=notes,
                    )
                )
    return rows


def build_mtr_walk_forward_rows() -> list[dict[str, Any]]:
    """Register the independent chronological MTR practical-OOS track."""
    path = ROOT / "data" / "processed" / "transport" / "mtr_farebox_walk_forward_oos.csv"
    frame = _read_csv(path)
    if frame.empty:
        return []
    required = {
        "period_type", "target_year", "target_period_end", "forecast_origin",
        "information_cutoff", "predicted_value_hkdm", "actual_value_hkdm",
        "actual_available_at", "actual_source_url", "model_applied",
        "input_bundle_id", "source_caveat",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"MTR walk-forward output is missing columns: {missing}")
    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        period_type = str(row["period_type"])
        if period_type not in {"FY", "H1"}:
            raise ValueError(f"Unsupported MTR walk-forward period type: {period_type}")
        has_prediction = _notna(row.get("predicted_value_hkdm")) and _bool(row.get("model_applied"))
        has_actual = _notna(row.get("actual_value_hkdm"))
        evaluation = "valid_practical_oos" if has_prediction and has_actual else "insufficient_input_coverage"
        grade = "B_practical_pit" if has_prediction else "D_diagnostic_only"
        if has_actual and not _notna(row.get("actual_available_at")):
            raise ValueError(f"MTR walk-forward actual lacks availability date: row {index}")
        rows.append(
            _row_status(
                registry_id=(
                    "mtr_farebox_walk_forward_oos:"
                    f"{period_type}:{'fiscal_year' if period_type == 'FY' else 'half_year_non_overlapping'}:"
                    f"{row['model_id']}"
                ),
                source_dataset="mtr_farebox_walk_forward_oos",
                source_run_id="",
                source_row_index=int(index),
                entity_id="MTR",
                target_id="transport_operations_revenue",
                period_type=period_type,
                track_id="fiscal_year" if period_type == "FY" else "half_year_non_overlapping",
                period_value=int(row["target_year"]),
                source_row_status=str(row.get("evaluation_status") or evaluation),
                input_pit_status="not_captured",
                target_pit_status="reported_actual" if has_actual else "not_available",
                pit_grade=grade,
                evaluation_status=evaluation,
                has_prediction=has_prediction,
                has_actual=has_actual,
                actual_available_at=row.get("actual_available_at"),
                actual_source_url=row.get("actual_source_url"),
                imputation_used=False,
                dependency_status=str(row.get("input_bundle_id") or "not_captured"),
                model_id=str(row["model_id"]),
                forecast_origin=row.get("forecast_origin"),
                information_cutoff=row.get("information_cutoff"),
                model_use="chronological_walk_forward",
                research_only=True,
                period_end_override=row.get("target_period_end"),
                notes=str(row.get("source_caveat") or ""),
            )
        )
    return rows


def build_mtr_monthly_nowcast_rows() -> list[dict[str, Any]]:
    """Register monthly MTR estimates as forecast-only monitoring rows."""
    path = ROOT / "data" / "processed" / "transport" / "mtr_farebox_monthly_nowcast.csv"
    frame = _read_csv(path)
    if frame.empty:
        return []
    required = {
        "month", "forecast_origin", "information_cutoff", "predicted_value_hkdm",
        "input_bundle_id", "source_caveat",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"MTR monthly nowcast output is missing columns: {missing}")
    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        if not _notna(row.get("predicted_value_hkdm")):
            continue
        rows.append(
            _row_status(
                registry_id="mtr_farebox_monthly_nowcast:month:monthly_sparse:mtr_prior_yield_fam_walk_forward_v1",
                source_dataset="mtr_farebox_monthly_nowcast",
                source_run_id="",
                source_row_index=int(index),
                entity_id="MTR",
                target_id="transport_operations_revenue_monthly_nowcast",
                period_type="month",
                track_id="monthly_sparse",
                period_value=str(row["month"]),
                source_row_status="forecast_only",
                input_pit_status="not_captured",
                target_pit_status="not_available",
                pit_grade="B_practical_pit",
                evaluation_status="forecast_only",
                has_prediction=True,
                has_actual=False,
                actual_available_at=None,
                actual_source_url=None,
                imputation_used=False,
                dependency_status=str(row.get("input_bundle_id") or "not_captured"),
                model_id="mtr_prior_yield_fam_walk_forward_v1",
                forecast_origin=row.get("forecast_origin"),
                information_cutoff=row.get("information_cutoff"),
                model_use="monthly_nowcast_monitoring",
                research_only=True,
                notes=str(row.get("source_caveat") or ""),
            )
        )
    return rows


def _period_type_for_row(row: pd.Series, default: str) -> str:
    value = row.get("period")
    if _notna(value):
        normalized = str(value).strip().upper()
        if normalized in {"H1", "H2", "FY"}:
            return normalized
    normalized_default = str(default).strip().upper()
    if normalized_default not in {"H1", "H2", "FY"}:
        raise ValueError(f"Unsupported airline period type: {default!r}")
    return normalized_default


def _build_airline_rows(
    frame: pd.DataFrame,
    *,
    source_dataset: str,
    period_type: str,
    model_specs: list[tuple[str, str, str, str]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if frame.empty:
        return rows
    available_specs = [
        spec
        for spec in model_specs
        if spec[2] in frame.columns and frame[spec[2]].notna().any()
    ]
    for index, row in frame.iterrows():
        entity = str(row.get("company") or "airline")
        year = int(row["target_year"])
        row_period_type = _period_type_for_row(row, period_type)
        period_value = year
        status = str(row.get("row_status") or "historical_evaluated")
        grade = _airline_pit_grade(row)
        input_pit = _airline_input_pit_status(row)
        target_pit = _first_present(row, ("target_actual_pit_status", "target_financial_pit_status"))
        imputation = _bool(row.get("kpi_imputation_used")) or _bool(row.get("kpi_future_imputation_used"))
        actual_available = _first_present(
            row,
            ("target_financial_announcement_date", "financial_announcement_date"),
            default="",
        )
        actual_available = actual_available or None
        forecast_origin = _first_present(row, ("forecast_origin", "forecast_asof"))
        information_cutoff = _first_present(
            row,
            ("information_cutoff", "kpi_information_cutoff", "data_cutoff"),
        )
        for model_id, target_id, prediction_column, actual_column in available_specs:
            has_prediction = _notna(row.get(prediction_column))
            has_actual = _notna(row.get(actual_column))
            evaluation = _airline_eval_status(row, has_actual=has_actual, pit_grade=grade)
            registry_id = f"{source_dataset}:{row_period_type}:{target_id}:{model_id}"
            rows.append(
                _row_status(
                    registry_id=registry_id,
                    source_dataset=source_dataset,
                    source_run_id="",
                    source_row_index=int(index),
                    entity_id=entity,
                    target_id=target_id,
                    period_type=row_period_type,
                    track_id="fiscal_year" if row_period_type == "FY" else "half_year_non_overlapping",
                    period_value=period_value,
                    source_row_status=status,
                    input_pit_status=input_pit,
                    target_pit_status=target_pit,
                    pit_grade=grade,
                    evaluation_status=evaluation,
                    has_prediction=has_prediction,
                    has_actual=has_actual,
                    actual_available_at=actual_available,
                    imputation_used=imputation,
                    dependency_status="not_captured",
                    model_id=model_id,
                    forecast_origin=forecast_origin,
                    information_cutoff=information_cutoff,
                    notes=(
                        "Historical and live predictor implementations are separate code paths."
                        if source_dataset == "airline_earnings_model_v4"
                        else "Financial actual availability is retained only where the source row provides it."
                    ),
                )
            )
    return rows


def build_airline_rows() -> list[dict[str, Any]]:
    norm = ROOT / "data" / "normalized" / "hk_transport"
    h1 = _read_csv(norm / "airline_h1_kpi_backtest.csv")
    period = _read_csv(norm / "airline_period_kpi_backtest.csv")
    v4 = _read_csv(norm / "airline_earnings_model_v4.csv")
    cost = _read_csv(norm / "airline_cost_engine_v2.csv")
    rows: list[dict[str, Any]] = []
    rows.extend(
        _build_airline_rows(
            h1,
            source_dataset="airline_h1_kpi_backtest",
            period_type="H1",
            model_specs=[
                ("flat_ask_v1", "revenue", "flat_ask_revenue_pred_native_mn", "target_h1_revenue_native_mn"),
                ("flat_rpk_v1", "revenue", "flat_rpk_revenue_pred_native_mn", "target_h1_revenue_native_mn"),
                ("analyst_h1_nowcast_v1", "revenue", "analyst_h1_revenue_pred_native_mn", "target_h1_revenue_native_mn"),
                ("flat_ask_v1", "operating_cost", "flat_ask_cost_pred_native_mn", "target_h1_operating_cost_native_mn"),
                # The H1 profit prediction is operating profit times the
                # prior net-to-operating conversion; the period-table residual
                # model adds a modelled below-the-line residual instead.  They
                # are different model constructions and must not share a
                # model_id (they are not duplicate sources of the same model).
                ("flat_ask_profit_v1", "attributable_profit", "flat_ask_profit_pred_native_mn", "target_h1_attributable_profit_native_mn"),
            ],
        )
    )
    rows.extend(
        _build_airline_rows(
            period,
            source_dataset="airline_period_kpi_backtest",
            period_type="FY",
            model_specs=[
                ("flat_ask_v1", "revenue", "flat_ask_revenue_pred_native_mn", "target_revenue_native_mn"),
                ("flat_rpk_v1", "revenue", "flat_rpk_revenue_pred_native_mn", "target_revenue_native_mn"),
                ("spring_recovery_v1", "revenue", "spring_recovery_case_revenue_pred_native_mn", "target_revenue_native_mn"),
                ("flat_ask_v1", "operating_cost", "flat_ask_cost_pred_native_mn", "target_operating_cost_native_mn"),
                ("flat_ask_residual_v1", "attributable_profit", "flat_ask_profit_residual_pred_native_mn", "target_attributable_profit_native_mn"),
            ],
        )
    )
    rows.extend(
        _build_airline_rows(
            v4,
            source_dataset="airline_earnings_model_v4",
            period_type="FY",
            model_specs=[
                ("v4_base_decomposition_v1", "revenue", "revenue_base_decomposition_native_mn", "target_revenue_native_mn"),
                ("v4_dynamic_shrinkage_v1", "revenue", "revenue_dynamic_shrinkage_native_mn", "target_revenue_native_mn"),
                ("v4_residual_yield_v1", "revenue", "revenue_residual_yield_native_mn", "target_revenue_native_mn"),
                ("v4_recovery_overlay_v1", "revenue", "revenue_recovery_overlay_native_mn", "target_revenue_native_mn"),
            ],
        )
    )
    rows.extend(
        _build_airline_rows(
            cost,
            source_dataset="airline_cost_engine_v2",
            period_type="FY",
            model_specs=[
                ("flat_ask_cost_v1", "operating_cost", "cost_flat_ask_native_mn", "operating_cost_actual_native_mn"),
                ("fuel_mechanical_cost_v1", "operating_cost", "cost_fuel_mechanical_native_mn", "operating_cost_actual_native_mn"),
                ("nonfuel_driver_cost_v1", "operating_cost", "cost_nonfuel_drivers_native_mn", "operating_cost_actual_native_mn"),
                ("company_shrink_cask_v2", "operating_cost", "cost_company_shrink_native_mn", "operating_cost_actual_native_mn"),
                ("full_cask_v2", "operating_cost", "cost_full_cask_native_mn", "operating_cost_actual_native_mn"),
            ],
        )
    )
    return rows


def _shkp_dependency_status(lineage: dict[str, Any]) -> str:
    input_ids = lineage.get("input_dataset_run_ids")
    return "captured" if isinstance(input_ids, (list, tuple, dict)) and input_ids else "input_run_set_not_captured"


def _shkp_sales_model_id(row: pd.Series) -> str:
    method = _metadata_value(row.get("forecast_method"))
    scenario = _metadata_value(row.get("scenario"))
    lookback = row.get("lookback_months")
    if _notna(lookback):
        try:
            lookback_label = str(int(float(lookback)))
        except (TypeError, ValueError):
            lookback_label = str(lookback).strip()
    else:
        lookback_label = "not_captured"
    return f"{method}_lb{lookback_label}_{scenario}"


def build_shkp_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sales, sales_run_id, sales_lineage = _latest_shkp_frame("shkp_indicative_sales_model_backtest")
    if not sales.empty:
        for index, source_row in sales.iterrows():
            model_id = _shkp_sales_model_id(source_row)
            registry_id = f"shkp_indicative_sales_model_backtest:month:contract_activity_proxy:{model_id}"
            rows.append(
                _row_status(
                    registry_id=registry_id,
                    source_dataset="shkp_indicative_sales_model_backtest",
                    source_run_id=sales_run_id,
                    source_row_index=int(index),
                    entity_id="SHKP",
                    target_id="contract_activity_proxy",
                    period_type="month",
                    track_id="monthly_sparse",
                    period_value=source_row.get("target_period"),
                    source_row_status=str(source_row.get("backtest_status") or ""),
                    input_pit_status="not_captured",
                    target_pit_status="not_applicable_proxy",
                    pit_grade="D_diagnostic_only",
                    evaluation_status="diagnostic_only",
                    has_prediction=_notna(source_row.get("forecast_value_hkd")),
                    has_actual=_notna(source_row.get("actual_value_hkd")),
                    actual_available_at=None,
                    imputation_used=False,
                    dependency_status=_shkp_dependency_status(sales_lineage),
                    model_id=model_id,
                    scenario=source_row.get("scenario"),
                    lookback_months=source_row.get("lookback_months"),
                    model_use=source_row.get("model_use"),
                    research_only=source_row.get("research_only"),
                    notes="Gross SRPE contract activity proxy; not recognised revenue and not a headline accuracy target.",
                )
            )

    skeleton, skeleton_run_id, skeleton_lineage = _latest_shkp_frame("shkp_skeleton_historical_backtest")
    if not skeleton.empty:
        for index, source_row in skeleton.iterrows():
            model_id = f"shkp_skeleton_{_metadata_value(source_row.get('margin_mode'))}_v2"
            has_actual = _notna(source_row.get("actual_underlying_profit_hkd_m"))
            rows.append(
                _row_status(
                    registry_id=f"shkp_skeleton_historical_backtest:FY:underlying_profit:{model_id}",
                    source_dataset="shkp_skeleton_historical_backtest",
                    source_run_id=skeleton_run_id,
                    source_row_index=int(index),
                    entity_id="SHKP",
                    target_id="underlying_profit",
                    period_type="FY",
                    track_id="fiscal_year",
                    period_value=source_row.get("fiscal_year_end"),
                    source_row_status="historical_evaluated" if has_actual else "forecast_only",
                    input_pit_status="not_captured",
                    target_pit_status="period_end_only_no_announcement_date",
                    pit_grade="C_structural_replay",
                    evaluation_status="structural_calibration" if has_actual else "forecast_only",
                    has_prediction=_notna(source_row.get("model_underlying_profit_hkd_m")),
                    has_actual=has_actual,
                    actual_available_at=None,
                    imputation_used=False,
                    dependency_status=_shkp_dependency_status(skeleton_lineage),
                    model_id=model_id,
                    model_use=source_row.get("model_use"),
                    research_only=source_row.get("research_only"),
                    shkp_fiscal=True,
                    notes="Hindsight-calibrated margin replay; not strict PIT/OOS.",
                )
            )

    commercial, commercial_run_id, commercial_lineage = _latest_shkp_frame("shkp_commercial_backtest")
    if not commercial.empty:
        for index, source_row in commercial.iterrows():
            model_id = str(source_row.get("method") or "unknown")
            has_actual = _notna(source_row.get("actual_rental_revenue_hkd_m"))
            rows.append(
                _row_status(
                    registry_id=f"shkp_commercial_backtest:FY:hk_rental_revenue:{model_id}",
                    source_dataset="shkp_commercial_backtest",
                    source_run_id=commercial_run_id,
                    source_row_index=int(index),
                    entity_id="SHKP",
                    target_id="hk_rental_revenue",
                    period_type="FY",
                    track_id="fiscal_year",
                    period_value=source_row.get("fiscal_year_end"),
                    source_row_status="historical_evaluated" if has_actual else "forecast_only",
                    input_pit_status="not_captured",
                    target_pit_status="period_end_only_no_announcement_date",
                    pit_grade="C_structural_replay",
                    evaluation_status="structural_calibration" if has_actual else "forecast_only",
                    has_prediction=_notna(source_row.get("forecast_rental_revenue_hkd_m")),
                    has_actual=has_actual,
                    actual_available_at=None,
                    imputation_used=False,
                    dependency_status=_shkp_dependency_status(commercial_lineage),
                    model_id=model_id,
                    model_use=source_row.get("model_use"),
                    research_only=source_row.get("research_only"),
                    shkp_fiscal=True,
                    notes="Short annual walk-forward rental bridge; scenario-grade and not headline eligible.",
                )
            )
    return rows


SOURCE_PRIORITY = {
    "mtr_farebox_walk_forward_oos": 5,
    "airline_period_kpi_backtest": 10,
    "mtr_farebox_revenue_h1_backtest": 10,
    "airline_h1_kpi_backtest": 20,
    "mtr_farebox_revenue_annual_backtest": 20,
}


def _assign_dedup_flags(row_status: pd.DataFrame) -> pd.DataFrame:
    if row_status.empty:
        return row_status
    result = row_status.copy()
    result["dedup_group_id"] = result["logical_observation_id"] + ":" + result["model_id"]
    result["_source_priority"] = result["source_dataset"].map(SOURCE_PRIORITY).fillna(30)
    result["_original_order"] = range(len(result))
    result = result.sort_values(
        ["dedup_group_id", "_source_priority", "source_dataset", "source_row_index", "row_key"]
    )
    result["dedup_rank"] = result.groupby("dedup_group_id", sort=False).cumcount() + 1
    result["is_primary_source"] = result["dedup_rank"] == 1
    return result.sort_values("_original_order").drop(columns=["_source_priority", "_original_order"])


def _aggregate_status(
    values: pd.Series,
    grades: pd.Series,
    *,
    has_actual: int,
    n_valid: int,
    period_type: str,
    diagnostic: bool,
    n_headline_valid: int | None = None,
    n_predictions: int | None = None,
) -> tuple[str, bool]:
    if diagnostic:
        return "diagnostic_only", False
    if has_actual == 0:
        if n_predictions == 0:
            return "insufficient_input_coverage", False
        return "current_forecast", False
    statuses = set(values.dropna().astype(str))
    grade_values = set(grades.dropna().astype(str))
    if "C_structural_replay" in grade_values and not grade_values.intersection({"A_strict_pit", "B_practical_pit"}):
        return "structural_calibration", False
    min_rows = MIN_HEADLINE_ROWS.get(period_type, 10)
    if n_valid < min_rows:
        return "insufficient_sample", False
    if n_headline_valid is not None and n_headline_valid < min_rows:
        return "insufficient_sample", False
    eligible_statuses = statuses.intersection({"valid_oos", "valid_practical_oos", "valid_forward_oos"})
    if not eligible_statuses:
        if statuses <= {"historical_structural_check", "calibration_year"}:
            return "historical_structural_check", False
        return "not_headline_eligible", False
    eligible = bool(eligible_statuses) and bool(grade_values.intersection({"A_strict_pit", "B_practical_pit"}))
    return ("valid_oos" if eligible_statuses == {"valid_oos"} and grade_values == {"A_strict_pit"} else "valid_practical_oos", eligible)


def _metadata_policy(values: pd.Series) -> str:
    return "row_level_source_field" if _metadata_summary(values) != "not_captured" else "not_captured"


def _metadata_summary(values: pd.Series) -> str:
    captured = {
        str(value)
        for value in values.dropna()
        if str(value).strip() not in {"", "not_captured", "None", "nan"}
    }
    return "|".join(sorted(captured)) if captured else "not_captured"


def _input_run_set_status(source_dataset: str, statuses: set[str]) -> str:
    if "captured" in statuses:
        return "captured"
    return "not_captured" if source_dataset.startswith("shkp_") else "not_applicable"


# Registry build order: this script runs before the long-form/metrics stages
# (see run_backtest_engine.py), so the metrics table below can only ever be
# the *previous* run's measurement of a possibly-different set of predictions.
# It is read as diagnostic-grade prior evidence for which model to declare as
# default, never as a validation of the run currently being built.
DEFAULT_MODEL_SENTINEL = "no_model_beats_baseline"
METRICS_FILENAME = "asia_backtest_metrics.csv"
LATEST_RUN_FILENAME = "asia_backtest_latest.json"


SELECTION_EVIDENCE_COLUMNS = (
    "registry_id",
    "entity_id",
    "model_id",
    "metric_grain",
    "is_baseline",
    "skill_vs_baseline",
    "n_scaled",
    "metric_status",
)


def _selection_evidence_fingerprint(frame: pd.DataFrame) -> str:
    """Fingerprint only the measured values a default-model choice rests on.

    The registry is itself hashed into the long-form input bundle, so anything
    written into ``asia_backtest_target_registry.csv`` feeds the next run's
    ``input_bundle_id`` and ``run_id``.  Recording the previous run's ids here
    therefore made the pipeline chase its own tail: the registry changed every
    run, so the bundle hash changed, so the next run recorded different ids
    again and no fixed point was ever reached.

    The metric *values* behind a selection are stable across reruns even
    though the run identity is not, so fingerprinting them keeps the decision
    auditable (recompute it to prove which measurement was used) without
    feeding run-to-run churn back into the hash.  The volatile ids stay in the
    registry manifest, which is not part of the input bundle.
    """
    columns = [column for column in SELECTION_EVIDENCE_COLUMNS if column in frame.columns]
    if not columns:
        return "not_captured"
    evidence = frame.loc[:, columns].sort_values(columns).reset_index(drop=True)
    return f"selection_evidence-{dataframe_fingerprint(evidence)[:16]}"


def _load_previous_metrics(registry_dir: Path) -> dict[str, Any]:
    metrics_path = registry_dir / METRICS_FILENAME
    latest_path = registry_dir / LATEST_RUN_FILENAME
    bundle: dict[str, Any] = {
        "available": False,
        "frame": pd.DataFrame(),
        "source_path": _relative(metrics_path),
        "evidence_fingerprint": "not_captured",
        "input_bundle_id": "not_captured",
        "latest_run_id": "not_captured",
    }
    frame = _read_csv(metrics_path)
    if frame.empty:
        return bundle
    bundle["frame"] = frame
    bundle["available"] = True
    bundle["evidence_fingerprint"] = _selection_evidence_fingerprint(frame)
    bundle_ids = sorted(
        {str(value) for value in frame.get("input_bundle_id", pd.Series(dtype="object")).dropna() if str(value)}
    )
    bundle["input_bundle_id"] = "|".join(bundle_ids) if bundle_ids else "not_captured"
    if latest_path.exists():
        try:
            latest = json.loads(latest_path.read_text())
            bundle["latest_run_id"] = str(latest.get("run_id") or "not_captured")
        except (OSError, ValueError, TypeError):
            pass
    return bundle


def _metric_evidence_lookup(frame: pd.DataFrame, grain: str) -> dict[tuple[str, str], dict[str, Any]]:
    """Map (registry_id, entity_id) -> measured skill evidence for one metric grain.

    ``entity_id`` is the empty string for the pooled grain, matching how
    entity keys are built for per-entity lookups below.
    """
    if frame.empty or "metric_grain" not in frame.columns:
        return {}
    subset = frame[(frame["metric_grain"] == grain) & (frame["is_baseline"] == False)]  # noqa: E712
    lookup: dict[tuple[str, str], dict[str, Any]] = {}
    for _, row in subset.iterrows():
        entity_key = str(row["entity_id"]) if grain == "per_entity" else ""
        skill = row.get("skill_vs_baseline")
        n_scaled = row.get("n_scaled")
        lookup[(str(row["registry_id"]), entity_key)] = {
            "skill_vs_baseline": float(skill) if pd.notna(skill) else None,
            "n_scaled": int(n_scaled) if pd.notna(n_scaled) else None,
            "metric_status": str(row.get("metric_status") or "not_available"),
        }
    return lookup


def _entity_best_model(
    entity_id: str,
    candidates: list[str],
    registry_id_for_model: dict[str, str],
    entity_lookup: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    measured: list[tuple[str, dict[str, Any]]] = []
    for model_id in candidates:
        registry_id = registry_id_for_model.get(model_id)
        evidence = entity_lookup.get((registry_id, entity_id)) if registry_id else None
        if evidence is None or evidence["skill_vs_baseline"] is None:
            continue
        measured.append((model_id, evidence))
    if not measured:
        return {"entity_id": entity_id, "model_id": None, "status": "not_measured", "evidence": None}
    # Rank strictly on skill_vs_baseline. directional_hit_rate is never used
    # as a tie-breaker: it can be degenerate (e.g. capacity and revenue
    # moving together gives a spurious 100% hit rate on several carriers).
    # Ties -- including bit-identical predictions from an overlay model that
    # degenerates to its base model on entities it wasn't built for -- break
    # on the lower model_id string so the pick is stable across rebuilds.
    measured.sort(key=lambda item: (-item[1]["skill_vs_baseline"], item[0]))
    best_model, best_evidence = measured[0]
    if best_evidence["skill_vs_baseline"] <= 0:
        return {"entity_id": entity_id, "model_id": None, "status": "no_model_beats_baseline", "evidence": None}
    return {"entity_id": entity_id, "model_id": best_model, "status": "measured", "evidence": best_evidence}


def _contract_default_from_entities(picks: list[dict[str, Any]]) -> dict[str, Any]:
    votes: dict[str, int] = {}
    skill_sum: dict[str, float] = {}
    for pick in picks:
        if pick["status"] == "measured":
            votes[pick["model_id"]] = votes.get(pick["model_id"], 0) + 1
            skill_sum[pick["model_id"]] = skill_sum.get(pick["model_id"], 0.0) + pick["evidence"]["skill_vs_baseline"]
    total_measured = sum(1 for pick in picks if pick["status"] in {"measured", "no_model_beats_baseline"})
    if votes:
        ranked = sorted(votes, key=lambda model_id: (-votes[model_id], -skill_sum[model_id], model_id))
        winner = ranked[0]
        return {
            "status": "measured_per_entity_majority",
            "model_id": winner,
            "vote_count": votes[winner],
            "total_measured_entities": total_measured,
        }
    if any(pick["status"] == "no_model_beats_baseline" for pick in picks):
        return {
            "status": "measured_no_model_beats_baseline",
            "model_id": DEFAULT_MODEL_SENTINEL,
            "vote_count": 0,
            "total_measured_entities": total_measured,
        }
    return {"status": "assumed_heuristic_fallback", "model_id": None, "vote_count": 0, "total_measured_entities": 0}


def _build_contract_evidence(
    row_status: pd.DataFrame, metrics_bundle: dict[str, Any]
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    entity_lookup = _metric_evidence_lookup(metrics_bundle["frame"], "per_entity")
    pooled_lookup = _metric_evidence_lookup(metrics_bundle["frame"], "pooled")
    contract_columns = ["source_dataset", "target_id", "target_period_type", "track_id"]
    result: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for keys, group in row_status.groupby(contract_columns, dropna=False, sort=True):
        source_dataset, target_id, period_type, track_id = keys
        if target_id == "contract_activity_proxy":
            # Diagnostic-only contract: never acquires a skill-derived default.
            continue
        contract_key = (str(source_dataset), str(target_id), str(period_type), str(track_id))
        candidates = sorted({str(model_id) for model_id in group["model_id"].dropna().unique()})
        registry_id_for_model = {
            str(model_id): str(registry_id)
            for model_id, registry_id in group.drop_duplicates("model_id")
            .set_index("model_id")["registry_id"]
            .items()
        }
        entities = sorted({str(entity_id) for entity_id in group["entity_id"].dropna().unique()})
        picks = [_entity_best_model(entity_id, candidates, registry_id_for_model, entity_lookup) for entity_id in entities]
        contract_result = _contract_default_from_entities(picks)
        pooled_evidence = None
        winner = contract_result["model_id"]
        if winner not in (None, DEFAULT_MODEL_SENTINEL):
            pooled_evidence = pooled_lookup.get((registry_id_for_model[winner], ""))
        result[contract_key] = {**contract_result, "picks": picks, "pooled_evidence": pooled_evidence}
    return result


def _format_entity_picks(picks: list[dict[str, Any]]) -> str:
    if not picks:
        return "not_measured"
    parts: list[str] = []
    for pick in sorted(picks, key=lambda p: p["entity_id"]):
        if pick["status"] == "measured":
            skill = pick["evidence"]["skill_vs_baseline"]
            n_scaled = pick["evidence"]["n_scaled"]
            parts.append(f"{pick['entity_id']}={pick['model_id']}(skill={skill:.4f},n={n_scaled})")
        elif pick["status"] == "no_model_beats_baseline":
            parts.append(f"{pick['entity_id']}={DEFAULT_MODEL_SENTINEL}")
        else:
            parts.append(f"{pick['entity_id']}=not_measured")
    return "|".join(parts)


def _format_entity_disagreements(evidence: dict[str, Any], default_model: str) -> str:
    if evidence["status"] != "measured_per_entity_majority":
        return "not_applicable"
    disagreeing = sorted(
        pick["entity_id"] for pick in evidence["picks"] if pick["status"] == "measured" and pick["model_id"] != default_model
    )
    return "|".join(disagreeing) if disagreeing else "none"


def build_target_registry(
    row_status: pd.DataFrame, metrics_bundle: dict[str, Any] | None = None
) -> pd.DataFrame:
    if row_status.empty:
        return pd.DataFrame()
    if metrics_bundle is None:
        metrics_bundle = _load_previous_metrics(REGISTRY_DIR)
    contract_evidence = _build_contract_evidence(row_status, metrics_bundle)
    rows: list[dict[str, Any]] = []
    group_columns = ["registry_id", "source_dataset", "target_id", "target_period_type", "track_id", "model_id"]
    for keys, group in row_status.groupby(group_columns, dropna=False, sort=True):
        registry_id, source_dataset, target_id, period_type, track_id, model_id = keys
        primary_group = group[group["is_primary_source"]]
        n_total = len(group)
        has_actual = int(group["has_actual"].sum())
        evaluable_mask = (
            group["has_actual"]
            & group["has_prediction"]
            & group["evaluation_status"].isin(EVALUABLE_STATUSES)
            & group["pit_grade"].map(is_headline_grade)
        )
        n_valid = int(evaluable_mask.sum())
        n_primary = int(group["is_primary_source"].sum())
        n_duplicate = n_total - n_primary
        n_forecast = int((group["evaluation_status"] == "forecast_only").sum())
        n_no_source = int((group["evaluation_status"] == "no_source_coverage").sum())
        n_insufficient = int(group["evaluation_status"].astype(str).str.contains("insufficient", na=False).sum())
        n_imputed = int(group["imputation_used"].sum())
        primary_has_actual = int(primary_group["has_actual"].sum())
        primary_valid_mask = (
            primary_group["has_actual"]
            & primary_group["has_prediction"]
            & primary_group["evaluation_status"].isin(EVALUABLE_STATUSES)
            & primary_group["pit_grade"].map(is_headline_grade)
        )
        primary_n_valid = int(primary_valid_mask.sum())
        primary_n_forecast = int((primary_group["evaluation_status"] == "forecast_only").sum())
        primary_n_no_source = int((primary_group["evaluation_status"] == "no_source_coverage").sum())
        diagnostic = bool((primary_group["evaluation_status"] == "diagnostic_only").all()) if not primary_group.empty else False
        primary_headline_mask = primary_valid_mask & primary_group["evaluation_status"].isin(
            {"valid_oos", "valid_practical_oos", "valid_forward_oos"}
        ) & primary_group["pit_grade"].isin({"A_strict_pit", "B_practical_pit"})
        if primary_group.empty:
            status, headline_eligible = "duplicate_source_alias", False
        else:
            status, headline_eligible = _aggregate_status(
                primary_group["evaluation_status"],
                primary_group.loc[primary_valid_mask, "pit_grade"],
                has_actual=primary_has_actual,
                n_valid=primary_n_valid,
                n_headline_valid=int(primary_headline_mask.sum()),
                period_type=str(period_type),
                diagnostic=diagnostic,
                n_predictions=int(primary_group["has_prediction"].sum()),
            )
        if target_id == "contract_activity_proxy":
            default_model = "diagnostic_only"
            baseline = "same_month_last_year"
            primary_metric = "diagnostic_coverage"
        elif source_dataset.startswith("mtr_"):
            default_model = "mtr_physics_yield_v1"
            baseline = "same_period_last_year"
            primary_metric = "WAPE"
        elif target_id == "operating_cost":
            default_model = "company_shrink_cask_v2" if source_dataset == "airline_cost_engine_v2" else "flat_ask_v1"
            baseline = "same_period_last_year"
            primary_metric = "WAPE"
        elif target_id in {"attributable_profit", "underlying_profit"}:
            default_model = "flat_ask_residual_v1" if target_id == "attributable_profit" else "structural_replay"
            baseline = "same_period_last_year"
            primary_metric = "native_MAE"
        else:
            default_model = "distributed_lag_rvd_v1" if target_id == "hk_rental_revenue" else model_id
            baseline = "same_period_last_year"
            primary_metric = "MAE"
        legacy_primary_metric = primary_metric
        if target_id == "contract_activity_proxy":
            default_model = "not_applicable"
            secondary_metrics = "coverage_by_phase|zero_target_rate"
            scaler_id = "not_applicable"
            baseline_status = "not_applicable"
            directional_hit_rate_min_rows = None
        else:
            secondary_metrics = "RMSE|directional_hit_rate"
            scaler_id = "same_period_last_year_rmse"
            baseline_status = "materialized_in_additive_long_form"
            primary_metric = "scaled_RMSE"
            directional_hit_rate_min_rows = MIN_DIRECTIONAL_HIT_RATE_ROWS.get(str(period_type), 12)
        # default_model above is the pre-metrics heuristic chain; it is kept
        # as the fallback used only when no measured skill evidence exists
        # for this contract (see the ordering-problem note on
        # _load_previous_metrics). Where measured per-entity evidence is
        # available it overrides the heuristic below -- selection happens at
        # entity grain, never from the pooled cross-entity number, because a
        # pooled skill can point to the wrong model for the very entities
        # that a pooled average dilutes (an overlay model tuned for one
        # entity reads as worse than a generic model once averaged across
        # every other entity it doesn't apply to).
        if target_id == "contract_activity_proxy":
            selection_basis = "not_applicable"
            by_entity = "not_applicable"
            entity_disagreements = "not_applicable"
            entity_vote_count: int | None = None
            entity_total_count: int | None = None
            pooled_skill: float | None = None
            pooled_skill_n: int | None = None
            pooled_metric_status = "not_applicable"
            selection_confidence = "not_applicable"
        else:
            contract_key = (str(source_dataset), str(target_id), str(period_type), str(track_id))
            evidence = contract_evidence.get(contract_key)
            if evidence is None:
                selection_basis = "assumed_heuristic_fallback"
                by_entity = "not_measured"
                entity_disagreements = "not_applicable"
                entity_vote_count = None
                entity_total_count = None
            elif evidence["status"] == "measured_per_entity_majority":
                default_model = evidence["model_id"]
                selection_basis = "per_entity_majority_vote"
                by_entity = _format_entity_picks(evidence["picks"])
                entity_disagreements = _format_entity_disagreements(evidence, default_model)
                entity_vote_count = evidence["vote_count"]
                entity_total_count = evidence["total_measured_entities"]
            elif evidence["status"] == "measured_no_model_beats_baseline":
                default_model = DEFAULT_MODEL_SENTINEL
                selection_basis = "measured_no_model_beats_baseline"
                by_entity = _format_entity_picks(evidence["picks"])
                entity_disagreements = "not_applicable"
                entity_vote_count = evidence["vote_count"]
                entity_total_count = evidence["total_measured_entities"]
            else:
                selection_basis = "assumed_heuristic_fallback"
                by_entity = _format_entity_picks(evidence["picks"])
                entity_disagreements = "not_applicable"
                entity_vote_count = evidence["vote_count"]
                entity_total_count = evidence["total_measured_entities"]
            pooled_evidence = evidence["pooled_evidence"] if evidence else None
            pooled_skill = pooled_evidence["skill_vs_baseline"] if pooled_evidence else None
            pooled_skill_n = pooled_evidence["n_scaled"] if pooled_evidence else None
            pooled_metric_status = pooled_evidence["metric_status"] if pooled_evidence else "not_available"
            if selection_basis == "assumed_heuristic_fallback":
                selection_confidence = "not_measured"
            elif pooled_metric_status == "valid_headline":
                selection_confidence = "validated_headline"
            else:
                selection_confidence = "diagnostic_grade_not_validated"
        canonical_doc = _canonical_doc_for(source_dataset, target_id)
        source_run_ids = sorted({str(value) for value in group["source_run_id"].dropna() if str(value)})
        input_statuses = sorted({str(value) for value in group["dependency_status"].dropna()})
        predictor_binding = "historical_live_split" if source_dataset == "airline_earnings_model_v4" else "not_shared_or_not_captured"
        valid_mask = evaluable_mask
        valid_pit_grades = group.loc[valid_mask, "pit_grade"].dropna().astype(str)
        primary_valid_pit_grades = primary_group.loc[primary_valid_mask, "pit_grade"].dropna().astype(str)
        headline_mask = valid_mask & group["evaluation_status"].isin(
            {"valid_oos", "valid_practical_oos", "valid_forward_oos"}
        ) & group["pit_grade"].isin({"A_strict_pit", "B_practical_pit"})
        pit_grades = sorted(set(primary_valid_pit_grades)) or sorted(set(valid_pit_grades)) or sorted(set(group["pit_grade"].astype(str)))
        rows.append(
            {
                "registry_version": REGISTRY_VERSION,
                "registry_id": registry_id,
                "source_dataset": source_dataset,
                "entity_scope": ";".join(sorted({str(value) for value in group["entity_id"].dropna().unique()})),
                "sector_id": "hk-transport" if source_dataset.startswith(("mtr_", "airline_")) else "hk-real-estate",
                "target_id": target_id,
                "target_period_type": period_type,
                "track_id": track_id,
                "model_id": model_id,
                "default_model_id": default_model,
                "default_baseline_id": baseline,
                "default_model_selection_basis": selection_basis,
                "default_model_selection_confidence": selection_confidence,
                "default_model_entity_vote_count": entity_vote_count,
                "default_model_entity_total_count": entity_total_count,
                "default_model_id_by_entity": by_entity,
                "default_model_id_entity_disagreements": entity_disagreements,
                "default_model_pooled_skill_vs_baseline": pooled_skill,
                "default_model_pooled_skill_n": pooled_skill_n,
                "default_model_pooled_metric_status": pooled_metric_status,
                # Content fingerprint, not the source run id: this column is
                # hashed into the next stage's input bundle, so it must be
                # stable whenever the underlying measurements are unchanged.
                # The run/bundle ids live in the registry manifest instead.
                "default_model_selection_evidence_fingerprint": metrics_bundle["evidence_fingerprint"],
                "pit_grade": ";".join(pit_grades),
                "evaluation_status": status,
                # Step 1 is metadata-only. This is a candidate flag before
                # the value-bearing metric engine applies per-entity grain,
                # distinct-period and baseline-coverage gates.
                "candidate_headline_eligible": bool(headline_eligible and not diagnostic),
                "headline_eligibility_scope": "candidate_pre_metric_policy",
                "n_total_rows": n_total,
                "n_primary_source_rows": n_primary,
                "n_duplicate_rows": n_duplicate,
                "n_valid_eval_rows": n_valid,
                "n_primary_valid_eval_rows": primary_n_valid,
                "n_primary_headline_valid_rows": int(primary_headline_mask.sum()),
                "n_primary_forecast_only": primary_n_forecast,
                "n_primary_no_source_coverage": primary_n_no_source,
                "n_headline_valid_rows": int(headline_mask.sum()),
                "n_actual_available": has_actual,
                "n_forecast_only": n_forecast,
                "n_no_source_coverage": n_no_source,
                "n_insufficient_rows": n_insufficient,
                "n_imputed_rows": n_imputed,
                "source_run_ids": "|".join(source_run_ids),
                "input_run_set_status": _input_run_set_status(source_dataset, set(input_statuses)),
                "predictor_binding_status": predictor_binding,
                "forecast_origin_policy": _metadata_policy(group["forecast_origin"]),
                "information_cutoff_policy": _metadata_policy(group["information_cutoff"]),
                "model_use": _metadata_summary(group["model_use"]),
                "research_only": _metadata_summary(group["research_only"]),
                "primary_metric": primary_metric,
                "legacy_primary_metric": legacy_primary_metric,
                "secondary_metrics": secondary_metrics,
                "scaler_id": scaler_id,
                "baseline_status": baseline_status,
                "directional_hit_rate_min_rows": directional_hit_rate_min_rows,
                "canonical_spec_doc": canonical_doc,
                "notes": " | ".join(sorted({str(value) for value in group["notes"].dropna() if str(value)})),
            }
        )
    return pd.DataFrame(rows).sort_values("registry_id").reset_index(drop=True)


def _canonical_doc_for(source_dataset: str, target_id: str) -> str:
    mapping = {
        "mtr_farebox_revenue_annual_backtest": "docs/asia-markets/MTR_EARNINGS_ENGINE_SPEC.md",
        "mtr_farebox_revenue_h1_backtest": "docs/asia-markets/MTR_EARNINGS_ENGINE_SPEC.md",
        "mtr_farebox_walk_forward_oos": "docs/asia-markets/MTR_EARNINGS_ENGINE_SPEC.md",
        "mtr_farebox_monthly_nowcast": "docs/asia-markets/MTR_EARNINGS_ENGINE_SPEC.md",
        "airline_h1_kpi_backtest": "docs/asia-markets/airline-backtest-audit-and-improvements.md",
        "airline_period_kpi_backtest": "docs/asia-markets/airline-backtest-audit-and-improvements.md",
        "airline_earnings_model_v4": "docs/asia-markets/airline-earnings-model-v4.md",
        "airline_cost_engine_v2": "docs/asia-markets/airline-cost-engine-v2.md",
        "shkp_indicative_sales_model_backtest": "docs/asia-markets/REAL_ESTATE_SRPE_DATA_QUALITY_AUDIT.md",
        "shkp_skeleton_historical_backtest": "docs/asia-markets/SHKP_SKELETON_BACKTEST_V2_REPORT.md",
        "shkp_commercial_backtest": "docs/asia-markets/REAL_ESTATE_SHKP_FINANCIAL_MODEL.md",
    }
    return mapping.get(source_dataset, "docs/asia-markets/OPERATING_MANUAL.md")


def build_document_registry() -> pd.DataFrame:
    docs_dir = ROOT / "docs" / "asia-markets"
    paths = sorted(docs_dir.glob("*.md"))
    rows: list[dict[str, Any]] = []
    suffix_pattern = re.compile(r"^(.*) ([2-9][0-9]*)$")
    path_by_stem = {path.stem: path for path in paths}
    canonical_topics = {
        "MTR_EARNINGS_ENGINE_SPEC",
        "MTR_RESEARCH_STACK",
        "airline-backtest-audit-and-improvements",
        "airline-history-backtest-view",
        "airline-earnings-model-v4",
        "airline-cost-engine-v2",
        "REAL_ESTATE_SHKP_FORECAST_BACKTEST",
        "REAL_ESTATE_SRPE_DATA_QUALITY_AUDIT",
        "SHKP_SKELETON_BACKTEST_V2_REPORT",
        "REAL_ESTATE_SHKP_FINANCIAL_MODEL",
        "OPERATING_MANUAL",
        "unified-kpi-backtest-v1",
    }
    for path in paths:
        match = suffix_pattern.match(path.stem)
        if match and match.group(1) in path_by_stem:
            classification = "numbered_copy"
            canonical_path = path_by_stem[match.group(1)]
            reason = "Numbered duplicate; keep for history but use the unsuffixed file as canonical."
            topic_key = match.group(1).lower()
        else:
            classification = "canonical" if path.stem in canonical_topics else "unclassified"
            canonical_path = path
            reason = "Explicitly selected canonical backtest/reference document." if classification == "canonical" else "Requires later topic-level review."
            topic_key = path.stem.lower()
        rows.append(
            {
                "registry_version": REGISTRY_VERSION,
                "doc_id": path.stem,
                "path": _relative(path),
                "topic_key": topic_key,
                "classification": classification,
                "canonical_path": _relative(canonical_path),
                "reason": reason,
            }
        )
    return pd.DataFrame(rows).sort_values(["topic_key", "classification", "path"]).reset_index(drop=True)


def build_registry(output_dir: Path = REGISTRY_DIR) -> dict[str, pd.DataFrame]:
    row_frames = [
        pd.DataFrame(build_mtr_rows()),
        pd.DataFrame(build_mtr_walk_forward_rows()),
        pd.DataFrame(build_mtr_monthly_nowcast_rows()),
        pd.DataFrame(build_airline_rows()),
        pd.DataFrame(build_shkp_rows()),
    ]
    row_status = pd.concat([frame for frame in row_frames if not frame.empty], ignore_index=True)
    row_status = _assign_dedup_flags(row_status)
    # Read the *previous* run's measured skill as diagnostic-grade prior
    # evidence for default_model_id. This script runs before the long-form/
    # metrics stages (see run_backtest_engine.py) so it can never see the
    # metrics for the run currently being built -- only ever the prior one,
    # or nothing at all on a fresh clone.
    metrics_bundle = _load_previous_metrics(REGISTRY_DIR)
    target_registry = build_target_registry(row_status, metrics_bundle)
    documents = build_document_registry()
    output_dir.mkdir(parents=True, exist_ok=True)
    row_status.to_csv(output_dir / ROW_OUTPUT, index=False)
    target_registry.to_csv(output_dir / TARGET_OUTPUT, index=False)
    documents.to_csv(output_dir / DOC_OUTPUT, index=False)
    manifest = {
        "registry_version": REGISTRY_VERSION,
        "scope": "forecast_accuracy_metadata_only",
        "headline_eligibility_scope": "candidate_pre_metric_policy",
        "model_calculation_changed": False,
        "dashboard_changed": False,
        "wide_tables_replaced": False,
        "outputs": {
            "target_registry": TARGET_OUTPUT,
            "row_status": ROW_OUTPUT,
            "document_registry": DOC_OUTPUT,
        },
        "target_rows": int(len(target_registry)),
        "row_status_rows": int(len(row_status)),
        "document_rows": int(len(documents)),
        "default_model_selection": {
            "method": "per_entity_skill_vs_baseline_majority_vote",
            "note": (
                "Diagnostic-grade prior evidence only, not a validated ranking: "
                "every contract measured so far is metric_status=insufficient_sample "
                "(headline_contracts == 0). See default_model_selection_confidence "
                "and default_model_id_by_entity per row for the evidence behind "
                "each declared default."
            ),
            "metrics_available": bool(metrics_bundle["available"]),
            "metrics_source": metrics_bundle["source_path"],
            # The fingerprint is what the registry rows carry, because the
            # registry is hashed into the long-form input bundle and must not
            # churn between otherwise identical runs. The volatile source ids
            # are kept here: the manifest is not part of that bundle, so it can
            # hold them without breaking the pipeline's fixed point.
            "evidence_fingerprint": metrics_bundle["evidence_fingerprint"],
            "input_bundle_id": metrics_bundle["input_bundle_id"],
            "latest_run_id": metrics_bundle["latest_run_id"],
        },
        "known_gaps": [
            "SHKP input dataset run set is not captured as one dependency bundle.",
            "Airline historical v4 and live v4 use separate predictor implementations.",
            "MTR actual availability dates are sourced from official results announcements and propagated to the row contract; legacy MTR replay rows remain structural unless their model contract supplies chronological inputs.",
            "Same-period-last-year baseline predictions and scaled_RMSE are materialized in the additive long-form/metrics outputs; this Step 1 registry remains metadata-only.",
            "default_model_id is now derived per-entity from the previous run's measured skill_vs_baseline where available (see default_model_selection below); it falls back to the pre-metrics heuristic chain, labelled assumed_heuristic_fallback, wherever no measured evidence exists yet.",
        ],
    }
    (output_dir / MANIFEST_OUTPUT).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return {"target_registry": target_registry, "row_status": row_status, "documents": documents}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Asia Markets Step 1 backtest registry")
    parser.add_argument("--output-dir", type=Path, default=REGISTRY_DIR)
    args = parser.parse_args()
    result = build_registry(args.output_dir)
    print(f"wrote {len(result['target_registry'])} target registry rows")
    print(f"wrote {len(result['row_status'])} row status rows")
    print(f"wrote {len(result['documents'])} document registry rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
