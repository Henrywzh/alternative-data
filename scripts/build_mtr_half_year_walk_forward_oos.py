#!/usr/bin/env python3
"""Build a sequential H1/H2 MTR transport-revenue practical-OOS track.

This companion track is designed for a continuous half-year chart.  It keeps
the target grain non-overlapping and applies the same chronological rule to
both halves:

* H1 forecast: use the latest earlier H1 official actual;
* H2 forecast: use the latest earlier H2 actual, where H2 actual is derived
  only after the official FY result as ``FY - H1``;
* 2026 H1 is a current forecast and is not scored.

It deliberately does not use the legacy FY2024-anchor replay, and it does
not derive an H2 forecast by subtracting an H1 forecast from an FY forecast.
The latter would be a different model and would not be a same-half OOS test.

The result remains ``B_practical_pit`` because the current MTR patronage
download does not retain historical release vintages.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# When this file is executed directly (``python scripts/...py``), Python puts
# ``scripts/`` rather than the repository root on sys.path.  Add the root so
# the companion FY/H1 engine can be imported consistently from both the CLI
# and test runners.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_mtr_walk_forward_oos import (
    FAM_PCT,
    _fam_factor,
    _latest_patronage_snapshot,
    _load_actuals,
    _sha256,
)

OUT_DIR = ROOT / "data" / "processed" / "transport"
OUTPUT_PATH = OUT_DIR / "mtr_farebox_half_year_walk_forward_oos.csv"
SUMMARY_PATH = OUT_DIR / "mtr_farebox_half_year_walk_forward_summary.json"
MODEL_SOURCE_PATH = Path(__file__).resolve()

MODEL_ID = "mtr_prior_same_half_yield_walk_forward_v1"
MODEL_VERSION = "mtr_half_year_walk_forward_oos_v1"


def _half_label(month: int) -> str:
    return "H1" if int(month) <= 6 else "H2"


def _half_end(year: int, half: str) -> pd.Timestamp:
    return pd.Timestamp(f"{year}-06-30" if half == "H1" else f"{year}-12-31")


def _half_volume(patronage: pd.DataFrame, year: int, half: str) -> float:
    rows = patronage[patronage["year"].eq(int(year))]
    rows = rows[rows["month_num"].le(6)] if half == "H1" else rows[rows["month_num"].ge(7)]
    if rows.empty:
        raise ValueError(f"no MTR patronage for {year} {half}")
    return float(rows["total_volume_mn"].sum())


def _prepare_patronage(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    frame["year"] = frame["date"].dt.year.astype(int)
    frame["month_num"] = frame["date"].dt.month.astype(int)
    volume_columns = [
        "domestic_service_thousands",
        "airport_express_thousands",
        "cross_boundary_thousands",
        "light_rail_bus_thousands",
        "hsr_thousands",
    ]
    for column in volume_columns:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    frame["total_volume_mn"] = frame[volume_columns].sum(axis=1) / 1000.0
    frame["half"] = frame["month_num"].map(_half_label)
    return frame.sort_values("date").drop_duplicates("month").reset_index(drop=True)


def _half_actuals(actuals: pd.DataFrame) -> dict[tuple[int, str], dict[str, object]]:
    """Create official H1 and explicitly derived H2 actual labels.

    H2 is a financial-period label, but MTR normally discloses it only
    indirectly.  Its availability date is therefore the FY result release
    date, not 30 December of the target year.
    """
    actuals = actuals.copy()
    actuals["year"] = actuals["year"].astype(int)
    actuals["actual_value_hkdm"] = pd.to_numeric(actuals["actual_value_hkdm"], errors="raise")
    by_key = {(int(row.year), str(row.period_type)): row for row in actuals.itertuples()}
    result: dict[tuple[int, str], dict[str, object]] = {}

    for (year, period_type), row in by_key.items():
        if period_type != "H1":
            continue
        result[(year, "H1")] = {
            "actual_value_hkdm": float(row.actual_value_hkdm),
            "actual_available_at": pd.Timestamp(row.actual_available_at),
            "source_url": row.source_url,
            "release_source_url": row.release_source_url,
            "actual_status": "official_h1",
            "actual_definition": "Official Hong Kong Transport Operations / Total Revenue; six months ended 30 June; HK$m",
        }

    for year, fy in sorted((key[0], row) for key, row in by_key.items() if key[1] == "FY"):
        h1 = result.get((year, "H1"))
        if h1 is None:
            continue
        result[(year, "H2")] = {
            "actual_value_hkdm": float(fy.actual_value_hkdm) - float(h1["actual_value_hkdm"]),
            "actual_available_at": pd.Timestamp(fy.actual_available_at),
            "source_url": fy.source_url,
            "release_source_url": fy.release_source_url,
            "actual_status": "derived_fy_minus_h1",
            "actual_definition": "Derived H2 Hong Kong Transport Operations / Total Revenue = official FY actual minus official H1 actual; HK$m",
        }
    return result


def _input_bundle(snapshot_path: Path, snapshot_meta: str) -> tuple[str, dict[str, object]]:
    payload = {
        "schema": "mtr_half_year_walk_forward_input_bundle_v1",
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "model_code": {
            "path": str(MODEL_SOURCE_PATH.relative_to(ROOT)),
            "sha256": _sha256(MODEL_SOURCE_PATH),
        },
        "actuals": {
            "path": "data/normalized/hk_transport/mtr_transport_ops_actuals.csv",
            "sha256": _sha256(ROOT / "data/normalized/hk_transport/mtr_transport_ops_actuals.csv"),
        },
        "patronage": json.loads(snapshot_meta),
        "model_policy": {
            "training": "latest_prior_same_half_actual_only",
            "h2_actual": "official_fy_minus_official_h1;_available_at_fy_release",
            "target_volume": "observed_target_half_volume_at_period_end",
            "fam": "known_FAM_factor_between_anchor_and_target_year",
            "pit_grade": "B_practical_pit",
            "patronage_vintage": "not_captured",
        },
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return f"{MODEL_VERSION}-{hashlib.sha256(encoded).hexdigest()[:16]}", payload


def build_half_year_walk_forward() -> tuple[pd.DataFrame, dict[str, object]]:
    snapshot_path, raw_patronage, snapshot_meta = _latest_patronage_snapshot()
    patronage = _prepare_patronage(raw_patronage)
    actuals = _load_actuals()
    half_actuals = _half_actuals(actuals)
    input_bundle_id, input_bundle = _input_bundle(snapshot_path, snapshot_meta)

    periods = (
        patronage[["year", "half"]]
        .drop_duplicates()
        .sort_values(["year", "half"], key=lambda series: series.map({"H1": 1, "H2": 2}) if series.name == "half" else series)
    )
    rows: list[dict[str, object]] = []

    for period in periods.itertuples(index=False):
        year = int(period.year)
        half = str(period.half)
        cutoff = _half_end(year, half)
        target_volume = _half_volume(patronage, year, half)
        target_actual = half_actuals.get((year, half))
        training = [
            (anchor_year, anchor_data)
            for (anchor_year, anchor_half), anchor_data in half_actuals.items()
            if anchor_half == half
            and anchor_year < year
            and pd.Timestamp(anchor_data["actual_available_at"]) <= cutoff
        ]
        training.sort(key=lambda item: (item[0], item[1]["actual_available_at"]))

        has_training = bool(training)
        if has_training:
            anchor_year, anchor = training[-1]
            anchor_volume = _half_volume(patronage, anchor_year, half)
            anchor_actual = float(anchor["actual_value_hkdm"])
            anchor_yield = anchor_actual / anchor_volume
            fam_factor = _fam_factor(anchor_year, year)
            predicted = target_volume * anchor_yield * fam_factor
            anchor_release = pd.Timestamp(anchor["actual_available_at"])
            anchor_actual_status = str(anchor["actual_status"])
            evaluation_status = "current_forecast" if target_actual is None else "valid_practical_oos"
            pit_grade = "B_practical_pit"
            caveat = (
                "chronological_training_no_future_financial_actual; "
                "h2_actual_is_official_fy_minus_h1; patronage_vintage_not_captured"
            )
        else:
            anchor_year = None
            anchor_volume = np.nan
            anchor_actual = np.nan
            anchor_yield = np.nan
            fam_factor = np.nan
            predicted = np.nan
            anchor_release = pd.NaT
            anchor_actual_status = ""
            evaluation_status = "insufficient_prior_same_half_actual"
            pit_grade = "D_diagnostic_only"
            caveat = (
                "no_prior_same_half_actual_available; "
                "h2_actual_is_official_fy_minus_h1; patronage_vintage_not_captured"
            )

        actual_value = float(target_actual["actual_value_hkdm"]) if target_actual else np.nan
        error = predicted - actual_value if pd.notna(predicted) and pd.notna(actual_value) else np.nan
        error_pct = error / actual_value * 100.0 if pd.notna(error) and actual_value else np.nan

        rows.append(
            {
                "model_version": MODEL_VERSION,
                "model_id": MODEL_ID,
                "entity_id": "MTR",
                "target_id": "transport_operations_revenue_half_year",
                "period_type": half,
                "target_year": year,
                "period_label": f"{year} {half}",
                "target_period_start": f"{year}-01-01" if half == "H1" else f"{year}-07-01",
                "target_period_end": cutoff.strftime("%Y-%m-%d"),
                "forecast_origin": cutoff.strftime("%Y-%m-%d"),
                "information_cutoff": cutoff.strftime("%Y-%m-%d"),
                "target_volume_mn": target_volume,
                "anchor_year": anchor_year,
                "anchor_period_type": half,
                "anchor_release_date": anchor_release.strftime("%Y-%m-%d") if pd.notna(anchor_release) else "",
                "anchor_actual_status": anchor_actual_status,
                "anchor_volume_mn": anchor_volume,
                "anchor_actual_value_hkdm": anchor_actual,
                "anchor_yield_hkd_per_passenger": anchor_yield,
                "fam_factor": fam_factor,
                "predicted_value_hkdm": predicted,
                "actual_value_hkdm": actual_value,
                "error_hkdm": error,
                "error_pct": error_pct,
                "absolute_error_pct": abs(error_pct) if pd.notna(error_pct) else np.nan,
                "actual_status": str(target_actual["actual_status"]) if target_actual else "not_available",
                "actual_available_at": target_actual["actual_available_at"].strftime("%Y-%m-%d") if target_actual else "",
                "actual_source_url": target_actual["release_source_url"] if target_actual else "",
                "actual_definition": target_actual["actual_definition"] if target_actual else "",
                "evaluation_status": evaluation_status,
                "pit_grade": pit_grade,
                "model_applied": has_training,
                "has_prediction": has_training,
                "has_actual": target_actual is not None,
                "chronological_training_periods": len(training),
                "input_bundle_id": input_bundle_id,
                "source_snapshot": str(snapshot_path.relative_to(ROOT)),
                "source_snapshot_sha256": _sha256(snapshot_path),
                "source_caveat": caveat,
            }
        )

    frame = pd.DataFrame(rows)
    frame["_half_order"] = frame["period_type"].map({"H1": 1, "H2": 2})
    frame = frame.sort_values(["target_year", "_half_order"]).drop(columns="_half_order").reset_index(drop=True)

    summary: dict[str, object] = {
        "model_version": MODEL_VERSION,
        "model_id": MODEL_ID,
        "input_bundle_id": input_bundle_id,
        "pit_grade": "B_practical_pit",
        "strict_pit_status": "not_eligible_until_patronage_release_registry_exists",
        "training_rule": "latest_prior same-half actual only; actual_available_at <= target period end",
        "h2_actual_rule": "official FY actual minus official H1 actual; available at FY release date",
        "forecast_origin_rule": "target half-year end; period-end revenue nowcast, not beginning-of-period forecast",
        "patronage_vintage_status": "not_captured",
        "rows": int(len(frame)),
        "metrics": {},
        "input_bundle": input_bundle,
    }
    for half in ("H1", "H2"):
        valid = frame[
            frame["period_type"].eq(half)
            & frame["has_prediction"]
            & frame["has_actual"]
            & frame["evaluation_status"].eq("valid_practical_oos")
        ]
        summary["metrics"][half] = {
            "n": int(len(valid)),
            "mape_pct": float(valid["absolute_error_pct"].mean()) if not valid.empty else None,
            "wape_pct": float(valid["error_hkdm"].abs().sum() / valid["actual_value_hkdm"].abs().sum() * 100.0) if not valid.empty else None,
            "bias_hkdm": float(valid["error_hkdm"].mean()) if not valid.empty else None,
        }
    summary["current_forecasts"] = frame[frame["evaluation_status"].eq("current_forecast")][
        ["period_label", "predicted_value_hkdm"]
    ].to_dict(orient="records")
    return frame, summary


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frame, summary = build_half_year_walk_forward()
    frame.to_csv(OUTPUT_PATH, index=False)
    SUMMARY_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[mtr-half-year-oos] wrote {OUTPUT_PATH} ({len(frame)} rows)")
    for half, metrics in summary["metrics"].items():
        print(f"[mtr-half-year-oos] {half}: n={metrics['n']} WAPE={metrics['wape_pct']:.2f}% MAPE={metrics['mape_pct']:.2f}%")
    print(f"[mtr-half-year-oos] input_bundle_id={summary['input_bundle_id']}")
    print("[mtr-half-year-oos] PIT grade B_practical_pit; strict A requires historical patronage release vintages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
