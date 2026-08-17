#!/usr/bin/env python3
"""Build an auditable chronological MTR revenue walk-forward track.

This is deliberately separate from ``mtr_farebox_revenue_backtest.py``'s
legacy FY2024-anchor replay.  The legacy 4.78%/4.06% figures remain useful as
structural diagnostics, but they are not chronological OOS metrics.

The model here uses only completed *prior* financial periods to estimate a
blended transport-operations yield, then applies that yield to the target
period's observed passenger volume.  The target-period volume is treated as
available at the period end, so this is a period-end revenue nowcast rather
than a beginning-of-period earnings forecast.

The MTR patronage endpoint provides a current full-history table but not a
historical release/vintage date for each monthly observation.  Therefore rows
are explicitly graded ``B_practical_pit`` and carry the caveat
``patronage_vintage_not_captured``.  The chronological training rule itself is
strict: no target-period or future financial actual is used to estimate yield.

Outputs:
  * data/processed/transport/mtr_farebox_walk_forward_oos.csv
  * data/processed/transport/mtr_farebox_monthly_nowcast.csv
  * data/processed/transport/mtr_farebox_walk_forward_summary.json
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw" / "hk_transport"
ACTUALS_PATH = ROOT / "data" / "normalized" / "hk_transport" / "mtr_transport_ops_actuals.csv"
OUT_DIR = ROOT / "data" / "processed" / "transport"
WALK_FORWARD_PATH = OUT_DIR / "mtr_farebox_walk_forward_oos.csv"
MONTHLY_NOWCAST_PATH = OUT_DIR / "mtr_farebox_monthly_nowcast.csv"
SUMMARY_PATH = OUT_DIR / "mtr_farebox_walk_forward_summary.json"
MODEL_SOURCE_PATH = Path(__file__).resolve()

MODEL_ID = "mtr_prior_yield_fam_walk_forward_v1"
MODEL_VERSION = "mtr_walk_forward_oos_v1"

FAM_PCT = {
    2010: 2.05, 2011: 2.20, 2012: 5.40, 2013: 2.70, 2014: 3.60,
    2015: 4.30, 2016: 2.65, 2017: 0.00, 2018: 3.14, 2019: 3.30,
    2020: 0.00, 2021: -1.85, 2022: 0.00, 2023: 2.30, 2024: 3.09,
    2025: 0.00, 2026: 0.00,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _latest_patronage_snapshot() -> tuple[Path, pd.DataFrame, str]:
    snapshots = sorted(RAW_DIR.glob("mtr_patronage_*.json"))
    if not snapshots:
        raise FileNotFoundError(f"no MTR patronage snapshots under {RAW_DIR}")
    path = snapshots[-1]
    raw = json.loads(path.read_text(encoding="utf-8"))
    frame = pd.DataFrame(raw.get("data", []))
    required = {
        "month", "date", "domestic_service_thousands", "airport_express_thousands",
        "cross_boundary_thousands", "light_rail_bus_thousands", "hsr_thousands",
    }
    missing = sorted(required - set(frame.columns))
    if missing or frame.empty:
        raise ValueError(f"invalid MTR patronage snapshot {path}: missing={missing}")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    frame["year"] = frame["date"].dt.year.astype(int)
    frame["month_num"] = frame["date"].dt.month.astype(int)
    volume_columns = [
        "domestic_service_thousands", "airport_express_thousands",
        "cross_boundary_thousands", "light_rail_bus_thousands", "hsr_thousands",
    ]
    for column in volume_columns:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    frame["total_volume_mn"] = frame[volume_columns].sum(axis=1) / 1000.0
    frame = frame.sort_values("date").drop_duplicates("month").reset_index(drop=True)
    snapshot_meta = {
        "path": str(path.relative_to(ROOT)),
        "sha256": _sha256(path),
        "fetched_at": raw.get("fetched_at", "not_captured"),
        "source_url": raw.get("source_url", "https://www.mtr.com.hk/en/corporate/investor/patronage.php"),
        "rows": int(len(frame)),
    }
    return path, frame, json.dumps(snapshot_meta, sort_keys=True)


def _load_actuals() -> pd.DataFrame:
    actuals = pd.read_csv(ACTUALS_PATH)
    required = {"period_type", "year", "actual_value_hkdm", "release_source_url", "actual_available_at"}
    missing = sorted(required - set(actuals.columns))
    if missing:
        raise ValueError(f"MTR actuals missing columns: {missing}")
    actuals["year"] = actuals["year"].astype(int)
    actuals["actual_available_at"] = pd.to_datetime(actuals["actual_available_at"], errors="raise")
    actuals["actual_value_hkdm"] = pd.to_numeric(actuals["actual_value_hkdm"], errors="raise")
    if actuals.duplicated(["period_type", "year"]).any():
        raise ValueError("duplicate MTR actual period")
    return actuals


def _period_volume(patronage: pd.DataFrame, period_type: str, year: int) -> float:
    rows = patronage[patronage["year"].eq(year)]
    if period_type == "H1":
        rows = rows[rows["month_num"].le(6)]
    elif period_type != "FY":
        raise ValueError(f"unsupported period type: {period_type}")
    if rows.empty:
        raise ValueError(f"no patronage for {period_type} {year}")
    return float(rows["total_volume_mn"].sum())


def _fam_factor(prior_year: int, target_year: int) -> float:
    """Apply known FAM adjustments after the prior period through target year."""
    factor = 1.0
    if target_year > prior_year:
        for year in range(prior_year + 1, target_year + 1):
            factor *= 1.0 + FAM_PCT.get(year, 0.0) / 100.0
    return factor


def _period_end(period_type: str, year: int) -> pd.Timestamp:
    return pd.Timestamp(f"{year}-06-30" if period_type == "H1" else f"{year}-12-31")


def _input_bundle(snapshot_path: Path, snapshot_meta: str) -> tuple[str, dict[str, object]]:
    payload = {
        "schema": "mtr_walk_forward_input_bundle_v1",
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "model_code": {
            "path": str(MODEL_SOURCE_PATH.relative_to(ROOT)),
            "sha256": _sha256(MODEL_SOURCE_PATH),
        },
        "actuals": {
            "path": str(ACTUALS_PATH.relative_to(ROOT)),
            "sha256": _sha256(ACTUALS_PATH),
        },
        "patronage": json.loads(snapshot_meta),
        "model_policy": {
            "training": "prior_completed_same_period_actual_only",
            "target_volume": "observed_target_period_volume_at_period_end",
            "fam": "known_FAM_factor_between_prior_and_target_year",
            "pit_grade": "B_practical_pit",
            "patronage_vintage": "not_captured",
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return f"{MODEL_VERSION}-{hashlib.sha256(encoded).hexdigest()[:16]}", payload


def _candidate_training_rows(actuals: pd.DataFrame, period_type: str, target_year: int, cutoff: pd.Timestamp) -> pd.DataFrame:
    rows = actuals[
        actuals["period_type"].eq(period_type)
        & actuals["year"].lt(target_year)
        & actuals["actual_available_at"].le(cutoff)
    ].copy()
    return rows.sort_values(["year", "actual_available_at"])


def build_walk_forward() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    snapshot_path, patronage, snapshot_meta = _latest_patronage_snapshot()
    actuals = _load_actuals()
    input_bundle_id, input_bundle = _input_bundle(snapshot_path, snapshot_meta)
    rows: list[dict[str, object]] = []

    for period_type in ("FY", "H1"):
        available = actuals[actuals["period_type"].eq(period_type)].sort_values("year")
        for _, target in available.iterrows():
            target_year = int(target["year"])
            cutoff = _period_end(period_type, target_year)
            # A revenue nowcast for a completed period cannot use the
            # issuer's report released months later to estimate the anchor.
            # Keep the cutoff both chronological and release-date safe.
            training = _candidate_training_rows(actuals, period_type, target_year, cutoff)
            target_volume = _period_volume(patronage, period_type, target_year)
            has_training = not training.empty
            if has_training:
                anchor = training.iloc[-1]
                anchor_year = int(anchor["year"])
                anchor_volume = _period_volume(patronage, period_type, anchor_year)
                anchor_yield = float(anchor["actual_value_hkdm"]) / anchor_volume
                fam_factor = _fam_factor(anchor_year, target_year)
                predicted = target_volume * anchor_yield * fam_factor
                anchor_release = pd.Timestamp(anchor["actual_available_at"])
                status = "valid_practical_oos"
                pit_grade = "B_practical_pit"
                caveat = "chronological_training_no_future_financial_actual; patronage_vintage_not_captured"
            else:
                anchor_year = None
                anchor_volume = np.nan
                anchor_yield = np.nan
                fam_factor = np.nan
                predicted = np.nan
                anchor_release = pd.NaT
                status = "insufficient_prior_actual_coverage"
                pit_grade = "D_diagnostic_only"
                caveat = "no_prior_same_period_actual_available_by_cutoff"
            actual = float(target["actual_value_hkdm"])
            error = predicted - actual if pd.notna(predicted) else np.nan
            error_pct = error / actual * 100.0 if pd.notna(error) else np.nan
            rows.append({
                "model_version": MODEL_VERSION,
                "model_id": MODEL_ID,
                "entity_id": "MTR",
                "target_id": "transport_operations_revenue",
                "period_type": period_type,
                "target_year": target_year,
                "target_period_start": f"{target_year}-01-01",
                "target_period_end": cutoff.strftime("%Y-%m-%d"),
                "forecast_origin": cutoff.strftime("%Y-%m-%d"),
                "information_cutoff": cutoff.strftime("%Y-%m-%d"),
                "forecast_origin_policy": "period_end_nowcast",
                "information_cutoff_policy": "period_end_conservative_proxy",
                "target_volume_mn": target_volume,
                "anchor_year": anchor_year,
                "anchor_release_date": anchor_release.strftime("%Y-%m-%d") if pd.notna(anchor_release) else "",
                "anchor_volume_mn": anchor_volume,
                "anchor_yield_hkd_per_passenger": anchor_yield,
                "fam_factor": fam_factor,
                "predicted_value_hkdm": predicted,
                "actual_value_hkdm": actual,
                "error_hkdm": error,
                "error_pct": error_pct,
                "absolute_error_pct": abs(error_pct) if pd.notna(error_pct) else np.nan,
                "actual_available_at": pd.Timestamp(target["actual_available_at"]).strftime("%Y-%m-%d"),
                "actual_source_url": target["release_source_url"],
                "evaluation_status": status,
                "pit_grade": pit_grade,
                "model_applied": bool(has_training),
                "has_prediction": bool(has_training),
                "has_actual": True,
                "chronological_training_periods": int(len(training)),
                "input_bundle_id": input_bundle_id,
                "source_snapshot": str(snapshot_path.relative_to(ROOT)),
                "source_snapshot_sha256": _sha256(snapshot_path),
                "source_caveat": caveat,
            })

    walk = pd.DataFrame(rows).sort_values(["period_type", "target_year"]).reset_index(drop=True)

    # Monthly nowcast is a transparent forecast-only companion.  It does not
    # claim monthly financial accuracy because MTR does not publish monthly
    # transport-operations revenue actuals.
    latest_month = patronage["date"].max()
    fy_anchors = actuals[actuals["period_type"].eq("FY")].sort_values("year")
    h1_anchors = actuals[actuals["period_type"].eq("H1")].sort_values("year")
    monthly_rows: list[dict[str, object]] = []
    for _, row in patronage.iterrows():
        target_year = int(row["year"])
        target_month = int(row["month_num"])
        period_type = "H1" if target_month <= 6 else "FY"
        anchors = h1_anchors if period_type == "H1" else fy_anchors
        anchors = anchors[anchors["year"].lt(target_year)]
        if anchors.empty:
            continue
        anchor = anchors.iloc[-1]
        anchor_year = int(anchor["year"])
        anchor_volume = _period_volume(patronage, period_type, anchor_year)
        anchor_yield = float(anchor["actual_value_hkdm"]) / anchor_volume
        fam_factor = _fam_factor(anchor_year, target_year)
        predicted = float(row["total_volume_mn"]) * anchor_yield * fam_factor
        month_end = row["date"] + pd.offsets.MonthEnd(0)
        monthly_rows.append({
            "model_version": MODEL_VERSION,
            "model_id": MODEL_ID,
            "entity_id": "MTR",
            "target_id": "transport_operations_revenue_monthly_nowcast",
            "month": row["date"].strftime("%Y-%m"),
            "forecast_origin": month_end.strftime("%Y-%m-%d"),
            "information_cutoff": month_end.strftime("%Y-%m-%d"),
            "target_volume_mn": float(row["total_volume_mn"]),
            "predicted_value_hkdm": predicted,
            "anchor_period_type": period_type,
            "anchor_year": anchor_year,
            "anchor_release_date": pd.Timestamp(anchor["actual_available_at"]).strftime("%Y-%m-%d"),
            "fam_factor": fam_factor,
            "evaluation_status": "forecast_only_no_monthly_official_actual",
            "pit_grade": "B_practical_pit",
            "has_actual": False,
            "monthly_actual_available": False,
            "source_caveat": "MTR_does_not_publish_monthly_transport_operations_revenue; patronage_vintage_not_captured",
            "input_bundle_id": input_bundle_id,
            "source_snapshot": str(snapshot_path.relative_to(ROOT)),
            "latest_snapshot_month": latest_month.strftime("%Y-%m"),
        })
    monthly = pd.DataFrame(monthly_rows)

    summary: dict[str, object] = {
        "model_version": MODEL_VERSION,
        "model_id": MODEL_ID,
        "input_bundle_id": input_bundle_id,
        "pit_grade": "B_practical_pit",
        "strict_pit_status": "not_eligible_until_patronage_release_registry_exists",
        "chronological_training_rule": "same-period prior actuals only; actual_available_at <= target period end",
        "forecast_origin_rule": "target period end; period-end revenue nowcast, not beginning-of-period forecast",
        "patronage_vintage_status": "not_captured",
        "fy_valid_rows": int(((walk["period_type"] == "FY") & walk["has_prediction"]).sum()),
        "h1_valid_rows": int(((walk["period_type"] == "H1") & walk["has_prediction"]).sum()),
        "monthly_rows": int(len(monthly)),
        "metrics": {},
        "input_bundle": input_bundle,
    }
    for period_type in ("FY", "H1"):
        valid = walk[(walk["period_type"] == period_type) & walk["has_prediction"]]
        summary["metrics"][period_type] = {
            "n": int(len(valid)),
            "wape_pct": float(valid["error_hkdm"].abs().sum() / valid["actual_value_hkdm"].abs().sum() * 100.0) if not valid.empty else None,
            "mape_pct": float(valid["absolute_error_pct"].mean()) if not valid.empty else None,
            "bias_hkdm": float(valid["error_hkdm"].mean()) if not valid.empty else None,
        }
    return walk, monthly, summary


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    walk, monthly, summary = build_walk_forward()
    walk.to_csv(WALK_FORWARD_PATH, index=False)
    monthly.to_csv(MONTHLY_NOWCAST_PATH, index=False)
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[mtr-walk-forward] wrote {WALK_FORWARD_PATH} ({len(walk)} rows)")
    print(f"[mtr-walk-forward] wrote {MONTHLY_NOWCAST_PATH} ({len(monthly)} rows)")
    for period_type, values in summary["metrics"].items():
        print(f"[mtr-walk-forward] {period_type}: n={values['n']} WAPE={values['wape_pct']:.2f}% MAPE={values['mape_pct']:.2f}%")
    print(f"[mtr-walk-forward] input_bundle_id={summary['input_bundle_id']}")
    print("[mtr-walk-forward] PIT grade B_practical_pit; strict A requires historical patronage release vintages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
