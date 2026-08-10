"""Residual yield model: predict the deviation from the flat-yield baseline.

The flat-ASK framework (Revenue = ASK x prior-year RASK) is the strongest
free-data revenue benchmark (H1 MAE ~5.8%).  Instead of learning absolute
revenue, this module predicts only the residual:

    Residual_t = ActualRevenue_t - FlatYieldRevenue_t

with two guards motivated by the weak historical validation of yield
pressure:

* sign/bucket prediction: the yield-pressure index is reduced to a 3-class
  signal (+1 improving / 0 flat / -1 deteriorating) rather than a level;
* shrinkage: the yield adjustment is capped at a fraction (lambda < 1) of
  the historical residual std, so a weak proxy cannot dominate the strong
  flat-yield prior.

Outputs per company/period: flat-yield baseline, residual-adjusted revenue,
the signed adjustment and its shrink factor, and the 3-class yield-pressure
bucket.  The model is deliberately simple: it recognises that historical
yield is the prior and the model learns only the deviation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..config import NORMALIZED_DIR

logger = logging.getLogger(__name__)


OUTPUT_PATH = NORMALIZED_DIR / "airline_residual_yield_model.csv"
DATASET_ID = "airline_residual_yield_model"

WALK_FORWARD_PATH = NORMALIZED_DIR / "airline_walk_forward_model_v2.csv"
YIELD_PRESSURE_PATH = NORMALIZED_DIR / "airline_yield_pressure_index.csv"

OUTPUT_COLUMNS = [
    "dataset_id",
    "company",
    "period",
    "target_year",
    "row_status",
    "ask_mn",
    "prior_rask_native",
    "flat_yield_revenue_native_mn",
    "actual_revenue_native_mn",
    "residual_pct",
    "residual_std_pct",
    "yield_pressure_bucket",
    "yield_pressure_score",
    "shrink_lambda",
    "yield_adjustment_pct",
    "adjusted_revenue_native_mn",
    "adjusted_revenue_mae_pct",
    "flat_yield_revenue_mae_pct",
    "adjusted_improves_mae",
    "source_note",
    "retrieved_at",
]

# Shrinkage: the yield adjustment is capped at lambda x historical residual
# std.  0.5 means at most half of the historical residual variability is
# attributed to the (weakly validated) yield-pressure signal.
LAMBDA = 0.5

# Bucket thresholds: the yield-pressure score is a z-score-like quantity;
# +/-0.25 separates improving / flat / deteriorating while still being
# permissive enough to fire on real demand-capacity divergence.
BUCKET_UP = 0.25
BUCKET_DOWN = -0.25


def _num(value: Any) -> float | None:
    if value is None:
        return None
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _yield_bucket(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score > BUCKET_UP:
        return "improving"
    if score < BUCKET_DOWN:
        return "deteriorating"
    return "flat"


def build_airline_residual_yield_model() -> pd.DataFrame:
    """Build the residual-yield model with sign buckets and shrinkage."""
    retrieved = datetime.now(timezone.utc).isoformat()
    walk = pd.read_csv(WALK_FORWARD_PATH)
    pressure = pd.read_csv(YIELD_PRESSURE_PATH)

    flat = walk[
        walk["model_name"].eq("flat_ask")
        & walk["row_status"].eq("historical_evaluated")
    ].copy()
    current = walk[
        walk["model_name"].eq("flat_ask")
        & walk["row_status"].eq("current_forecast")
    ].copy()

    # Historical residual per company: actual / flat-yield - 1
    flat["residual_pct"] = (
        flat["target_revenue_native_mn"] / flat["predicted_revenue_native_mn"] - 1.0
    ) * 100.0

    # Per-company, per-year yield-pressure score (mean of that year's months).
    # Historical evaluation rows use the score from the SAME target year
    # (PIT: the score uses only data up to that year); current forecasts use
    # the most recent 12-month mean.
    pressure["year"] = pressure["month"].str[:4].astype(int)
    year_score = (
        pressure.groupby(["company", "year"])["yield_pressure_score"]
        .mean()
        .to_dict()
    )
    pressure_sorted = pressure.sort_values(["company", "month"])
    recent = pressure_sorted.groupby("company").tail(12)
    recent_score = recent.groupby("company")["yield_pressure_score"].mean().to_dict()

    rows: list[dict[str, Any]] = []
    for _, row in pd.concat([flat, current]).iterrows():
        company = row["company"]
        period = row["period"]
        target_year = row["target_year"]
        row_status = row["row_status"]
        ask = _num(row.get("target_ask_mn")) if row_status == "current_forecast" else _num(row.get("target_ask_mn"))
        if ask is None:
            ask = _num(row.get("target_ask_mn"))
        prior_revenue = _num(row.get("prior_revenue_native_mn"))
        prior_ask = _num(row.get("prior_ask_mn"))
        prior_rask = prior_revenue / prior_ask if prior_revenue is not None and prior_ask not in (None, 0) else None
        flat_yield_rev = (
            ask * prior_rask
            if ask is not None and prior_rask is not None
            else _num(row.get("predicted_revenue_native_mn"))
        )
        actual_rev = _num(row.get("target_revenue_native_mn"))

        company_residual = flat[flat["company"].eq(company)]["residual_pct"]
        residual_std = float(company_residual.std(ddof=0)) if len(company_residual) >= 2 else None
        score = (
            year_score.get((company, int(target_year)))
            if row_status == "historical_evaluated"
            else recent_score.get(company)
        )
        bucket = _yield_bucket(score)
        # Sign of the bucket drives the direction; shrinkage caps magnitude.
        sign = {"improving": 1.0, "deteriorating": -1.0}.get(bucket, 0.0)
        adjustment = (
            LAMBDA * residual_std * sign
            if residual_std is not None and sign != 0.0
            else 0.0
        )
        adjusted_rev = (
            flat_yield_rev * (1.0 + adjustment / 100.0)
            if flat_yield_rev is not None
            else None
        )

        flat_mae = (
            abs(flat_yield_rev / actual_rev - 1.0) * 100.0
            if flat_yield_rev is not None and actual_rev not in (None, 0)
            else None
        )
        adj_mae = (
            abs(adjusted_rev / actual_rev - 1.0) * 100.0
            if adjusted_rev is not None and actual_rev not in (None, 0)
            else None
        )
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "company": company,
                "period": period,
                "target_year": target_year,
                "row_status": row_status,
                "ask_mn": ask,
                "prior_rask_native": prior_rask,
                "flat_yield_revenue_native_mn": flat_yield_rev,
                "actual_revenue_native_mn": actual_rev,
                "residual_pct": row.get("residual_pct") if row_status == "historical_evaluated" else None,
                "residual_std_pct": residual_std,
                "yield_pressure_bucket": bucket,
                "yield_pressure_score": score,
                "shrink_lambda": LAMBDA,
                "yield_adjustment_pct": adjustment,
                "adjusted_revenue_native_mn": adjusted_rev,
                "adjusted_revenue_mae_pct": adj_mae,
                "flat_yield_revenue_mae_pct": flat_mae,
                "adjusted_improves_mae": (
                    bool(adj_mae < flat_mae)
                    if adj_mae is not None and flat_mae is not None
                    else None
                ),
                "source_note": (
                    "Residual yield model: flat-yield baseline (ASK x prior "
                    "RASK) plus a shrunk signed adjustment from the 3-class "
                    "yield-pressure bucket (lambda 0.5 x historical residual "
                    "std).  The adjustment is capped so the weakly-validated "
                    "yield signal cannot dominate the strong flat-yield prior."
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
    "build_airline_residual_yield_model",
    "source_path",
]
