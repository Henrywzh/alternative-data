"""Dated fuel-surcharge recovery proxy from official schedules and EIA fuel.

The surcharge schedule alone is policy context.  This module compares each
dated surcharge change with the concurrent change in the EIA Gulf Coast
kerosene-type jet-fuel benchmark around the effective date, producing a
transparent pass-through ratio per observation.

The result is a research proxy: the mainland China surcharge is a regulated
per-passenger amount rather than realized fuel-cost recovery, and the EIA
benchmark is not the issuer's purchase price.  It is carried into v3 as
context only and never changes operating profit mechanically.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import NORMALIZED_DIR


SURCHARGE_PATH = NORMALIZED_DIR / "airline_fuel_surcharges.parquet"
ENERGY_PATH = NORMALIZED_DIR / "airline_energy_prices.parquet"
OUTPUT_PATH = NORMALIZED_DIR / "airline_fuel_surcharge_recovery.csv"
DATASET_ID = "airline_fuel_surcharge_recovery"

JET_FUEL_SERIES = "EER_EPJK_PF4_RGC_DPG"
FUEL_LOOKBACK_DAYS = 30
FUEL_LOOKAHEAD_DAYS = 30
MIN_FUEL_CHANGE_PCT = 0.5

OUTPUT_COLUMNS = [
    "dataset_id",
    "carrier_scope",
    "charge_type",
    "route_band",
    "currency",
    "previous_value",
    "current_value",
    "effective_from",
    "surcharge_change_pct",
    "fuel_avg_before_usd_per_gallon",
    "fuel_avg_after_usd_per_gallon",
    "fuel_change_pct",
    "surcharge_to_fuel_change_ratio",
    "recovery_proxy_status",
    "source_note",
    "retrieved_at",
]


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def build_airline_fuel_surcharge_recovery(
    *,
    surcharges: pd.DataFrame | None = None,
    energy: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build the dated surcharge-versus-fuel recovery proxy table."""
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    surcharges = surcharges if surcharges is not None else (
        pd.read_parquet(SURCHARGE_PATH) if SURCHARGE_PATH.exists() else pd.DataFrame()
    )
    energy = energy if energy is not None else (
        pd.read_parquet(ENERGY_PATH) if ENERGY_PATH.exists() else pd.DataFrame()
    )
    rows: list[dict[str, Any]] = []
    if surcharges.empty or energy.empty:
        result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
        result.to_csv(OUTPUT_PATH, index=False)
        return result

    jet = energy.loc[
        energy["series_id"].eq(JET_FUEL_SERIES)
        & energy["frequency"].eq("daily")
    ].copy()
    jet["observation_date_parsed"] = pd.to_datetime(
        jet["observation_date"], errors="coerce"
    )
    jet["fuel_value"] = pd.to_numeric(jet["value"], errors="coerce")
    jet = jet.dropna(subset=["observation_date_parsed", "fuel_value"])

    for _, row in surcharges.iterrows():
        previous = _num(row.get("previous_value"))
        current = _num(row.get("current_value"))
        effective = pd.to_datetime(row.get("effective_from"), errors="coerce")
        if previous is None or current is None or pd.isna(effective):
            continue
        if previous == 0:
            continue
        before = jet.loc[
            jet["observation_date_parsed"].ge(effective - pd.Timedelta(days=FUEL_LOOKBACK_DAYS))
            & jet["observation_date_parsed"].lt(effective)
        ]["fuel_value"]
        after = jet.loc[
            jet["observation_date_parsed"].gt(effective)
            & jet["observation_date_parsed"].le(effective + pd.Timedelta(days=FUEL_LOOKAHEAD_DAYS))
        ]["fuel_value"]
        if before.empty or after.empty:
            status = "missing_fuel_benchmark_window"
            fuel_before = fuel_after = fuel_change = ratio = None
        else:
            fuel_before = float(before.mean())
            fuel_after = float(after.mean())
            fuel_change = 100.0 * fuel_after / fuel_before - 100.0 if fuel_before else None
            surcharge_change = 100.0 * current / previous - 100.0
            ratio = (
                surcharge_change / fuel_change
                if fuel_change is not None and abs(fuel_change) >= MIN_FUEL_CHANGE_PCT
                else None
            )
            status = (
                "available_pass_through_proxy"
                if ratio is not None
                else "fuel_change_too_small_for_ratio"
            )
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "carrier_scope": row.get("carrier_scope"),
                "charge_type": row.get("charge_type"),
                "route_band": row.get("route_band"),
                "currency": row.get("currency"),
                "previous_value": previous,
                "current_value": current,
                "effective_from": effective.strftime("%Y-%m-%d"),
                "surcharge_change_pct": (
                    100.0 * current / previous - 100.0 if previous else None
                ),
                "fuel_avg_before_usd_per_gallon": fuel_before,
                "fuel_avg_after_usd_per_gallon": fuel_after,
                "fuel_change_pct": fuel_change,
                "surcharge_to_fuel_change_ratio": ratio,
                "recovery_proxy_status": status,
                "source_note": (
                    "Dated surcharge change compared with the EIA Gulf Coast jet-fuel benchmark "
                    "window around the effective date. Regulated per-passenger surcharge is not "
                    "realized fuel-cost recovery and the benchmark is not the issuer purchase price."
                ),
                "retrieved_at": retrieved,
            }
        )
    result = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def source_path() -> Path:
    return OUTPUT_PATH


__all__ = [
    "OUTPUT_PATH",
    "build_airline_fuel_surcharge_recovery",
    "source_path",
]
