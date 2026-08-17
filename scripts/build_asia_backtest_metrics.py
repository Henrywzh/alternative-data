#!/usr/bin/env python3
"""Compute the Step 6 metric-policy table for the unified backtest engine.

Reads the additive long form and writes:

* ``data/registries/asia_backtest_metrics.csv`` — per-contract metrics under
  the shared metric policy (row-count guards, headline eligibility,
  directional hit rate vs the same-period baseline, scaled RMSE with
  degenerate-denominator guards).
* ``data/registries/asia_backtest_metric_intervals.csv`` — error-interval
  percentiles per explicit pooled/per-entity grain (p10/p25/p50/p75/p90 of
  absolute errors).
* ``data/registries/asia_backtest_metrics_manifest.json`` — policy version,
  counts, and the headline contract list.

Additive: no wide table and no dashboard consumer changes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

# Make the repository-root ``src`` package importable when this script is
# invoked directly, as documented, rather than only via ``python -m``.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.common.backtest import build_metrics_manifest, compute_error_intervals, compute_metric_table

REGISTRY_DIR = ROOT / "data" / "registries"
LONG_FORM_CSV = REGISTRY_DIR / "asia_backtest_long_form.csv"
LONG_FORM_PARQUET = REGISTRY_DIR / "asia_backtest_long_form.parquet"
METRICS_CSV = REGISTRY_DIR / "asia_backtest_metrics.csv"
METRICS_PARQUET = REGISTRY_DIR / "asia_backtest_metrics.parquet"
INTERVALS_CSV = REGISTRY_DIR / "asia_backtest_metric_intervals.csv"
INTERVALS_PARQUET = REGISTRY_DIR / "asia_backtest_metric_intervals.parquet"
MANIFEST_JSON = REGISTRY_DIR / "asia_backtest_metrics_manifest.json"


def build_metrics() -> dict[str, object]:
    if not LONG_FORM_PARQUET.exists() and not LONG_FORM_CSV.exists():
        raise FileNotFoundError(
            f"missing long form; run the engine first: {LONG_FORM_PARQUET} (or {LONG_FORM_CSV})"
        )
    long_form = pd.read_parquet(LONG_FORM_PARQUET) if LONG_FORM_PARQUET.exists() else pd.read_csv(LONG_FORM_CSV)
    metrics = compute_metric_table(long_form)
    metrics.to_csv(METRICS_CSV, index=False)
    metrics.to_parquet(METRICS_PARQUET, index=False)
    intervals = compute_error_intervals(long_form, metrics=metrics)
    intervals.to_csv(INTERVALS_CSV, index=False)
    intervals.to_parquet(INTERVALS_PARQUET, index=False)
    manifest = build_metrics_manifest(long_form, metrics, intervals)
    MANIFEST_JSON.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    manifest = build_metrics()
    print(
        f"[metrics] ok: {manifest['contract_rows']} contract rows, "
        f"{manifest['headline_contracts']} headline contracts, "
        f"{manifest['interval_rows']} interval rows "
        f"({manifest['metric_policy_version']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
