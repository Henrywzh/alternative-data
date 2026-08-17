"""Pivot views over the long-form contract.

The long form is the additive source of truth; this module derives consumer
shapes from it instead of duplicating wide tables.  Nothing in this module
rewrites a wide table or a dashboard consumer.
"""

from __future__ import annotations

from typing import Iterable, Literal

import pandas as pd

from .metrics import compute_metric_table
from .tracks import assert_single_track
from .vocabulary import EVALUABLE_STATUSES, canonicalize_unit, is_headline_grade

SummaryGrain = Literal["per_entity", "pooled"]


def contract_table(
    long_form: pd.DataFrame,
    registry_id: str,
    *,
    include_baseline: bool = False,
) -> pd.DataFrame:
    """Return evaluated rows for one contract as an entity x period table.

    Columns: entity_id, target_period_start, target_period_end,
    model_id, is_baseline, predicted_value, actual_value, abs_error,
    abs_pct_error, evaluation_status, pit_grade, unit.

    Only primary rows with both a prediction and an actual are returned, so
    the table is directly usable for accuracy comparisons.
    """
    frame = long_form[
        (long_form["registry_id"] == registry_id)
        & (long_form["is_primary_source"] == True)  # noqa: E712
        & (long_form["evaluation_status"].isin(EVALUABLE_STATUSES))
        & (long_form["pit_grade"].map(is_headline_grade))
        & (long_form["predicted_value"].notna())
        & (long_form["actual_value"].notna())
    ].copy()
    if not include_baseline:
        frame = frame[frame["is_baseline"] == False]  # noqa: E712
    if not frame.empty:
        # This table is the input to contract_summary's per-contract
        # mape_pct/wape_pct aggregate, which would silently collapse rows
        # across track_id (see tracks.py's H1+H2 vs FY double-counting risk)
        # if a registry_id ever spanned more than one track.
        assert_single_track(frame, context=f"contract_table for {registry_id}")
    frame["abs_error"] = (frame["predicted_value"] - frame["actual_value"]).abs()
    actual_abs = frame["actual_value"].abs()
    frame["abs_pct_error"] = frame["abs_error"].div(actual_abs).where(actual_abs > 0) * 100.0
    columns = [
        "entity_id",
        "target_period_start",
        "target_period_end",
        "target_period_type",
        "model_id",
        "is_baseline",
        "predicted_value",
        "actual_value",
        "abs_error",
        "abs_pct_error",
        "evaluation_status",
        "pit_grade",
        "unit",
    ]
    return frame[columns].reset_index(drop=True)


def contract_summary(
    long_form: pd.DataFrame,
    registry_ids: Iterable[str],
    *,
    metric_grain: SummaryGrain = "per_entity",
    metrics: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Return MAPE/WAPE summaries at an explicit entity grain.

    Per-entity is the default consumer grain. ``metric_grain="pooled"`` is
    retained as an explicit reference/compatibility view; callers should not
    treat that aggregate as a headline accuracy result.

    ``compute_metric_table`` deliberately does not compute MAPE/WAPE (a
    percentage metric blows up whenever the actual is near zero, which is
    exactly why profit-style targets are scored on native MAE + sign
    accuracy instead). This function is the one place in the package that
    still needs a percentage summary, so it computes ``mape_pct``/
    ``wape_pct`` locally but sources ``metric_status``, ``headline_eligible``
    and ``n_distinct_periods`` from ``compute_metric_table`` for the same
    registry_id/entity/grain, so every row this function emits carries the
    same sample guard as every other metric in this package. A caller cannot
    read ``mape_pct`` off this table without also seeing whether the sample
    behind it is headline-eligible.

    ``compute_metric_table`` does several ``.iterrows()`` passes over the
    full long form, so recomputing it once per call is expensive for a
    caller that renders one contract at a time (e.g. a chart-per-registry_id
    visualization layer). Pass an already-computed ``metrics`` frame (from
    ``compute_metric_table(long_form)``) to reuse it instead -- matching
    ``compute_error_intervals``'s optional ``metrics`` parameter and
    fallback semantics. The guard lookup below still requires exactly one
    matching row per registry_id/entity/grain regardless of whether
    ``metrics`` was supplied or computed here, so a stale or partial
    ``metrics`` table cannot silently bypass the guard -- it just raises.
    """
    if metric_grain not in {"per_entity", "pooled"}:
        raise ValueError("metric_grain must be 'per_entity' or 'pooled'")
    metrics_table = compute_metric_table(long_form) if metrics is None else metrics
    records = []
    for registry_id in registry_ids:
        table = contract_table(long_form, registry_id)
        if table.empty:
            continue
        if metric_grain == "pooled":
            groups = [("pooled", ";".join(sorted(table["entity_id"].astype(str).unique())), table)]
        else:
            groups = [
                ("per_entity", str(entity_id), entity_table)
                for entity_id, entity_table in table.groupby("entity_id", sort=True)
            ]
        contract_metrics = metrics_table[
            (metrics_table["registry_id"] == registry_id)
            & (metrics_table["metric_grain"] == metric_grain)
            & (~metrics_table["is_baseline"])
        ]
        for grain, entity_scope, group in groups:
            model_ids = sorted(set(group["model_id"].astype(str)))
            units = sorted(set(group["unit"].astype(str)))
            if len(model_ids) != 1:
                raise ValueError(
                    f"contract_summary group for {registry_id!r}/{entity_scope!r} spans "
                    f"multiple model_ids, cannot pick one silently: {model_ids}"
                )
            if len(units) != 1:
                raise ValueError(
                    f"contract_summary group for {registry_id!r}/{entity_scope!r} spans "
                    f"multiple units, cannot pick one silently: {units}"
                )
            guard_rows = contract_metrics[contract_metrics["entity_id"] == entity_scope]
            if len(guard_rows) != 1:
                raise ValueError(
                    "Expected exactly one compute_metric_table guard row for "
                    f"{registry_id!r}/{entity_scope!r}/{grain!r}, found {len(guard_rows)}. "
                    "contract_summary refuses to emit an accuracy number it cannot attach "
                    "a metric_status/headline_eligible guard to."
                )
            guard_row = guard_rows.iloc[0]
            actual_abs_sum = float(group["actual_value"].abs().sum())
            # N4: abs_pct_error is NaN wherever the actual is zero (see
            # contract_table), so mape_pct's mean() silently drops those rows.
            # n_mape_eval records the sample the mean was actually taken over,
            # distinct from n_eval (the wape_pct/full-group row count), so the
            # two can never be confused the way rmse/baseline_rmse once were.
            n_mape_eval = int(group["abs_pct_error"].notna().sum())
            records.append(
                {
                    "registry_id": registry_id,
                    "entity_id": entity_scope,
                    "metric_grain": grain,
                    "model_id": model_ids[0],
                    "n_eval": int(len(group)),
                    "n_mape_eval": n_mape_eval,
                    "mape_pct": float(group["abs_pct_error"].mean()),
                    "wape_pct": (
                        float(group["abs_error"].sum() / actual_abs_sum * 100.0)
                        if actual_abs_sum > 0
                        else float("nan")
                    ),
                    "unit": units[0],
                    "unit_canonical": canonicalize_unit(units[0]),
                    "metric_status": str(guard_row["metric_status"]),
                    "headline_eligible": bool(guard_row["headline_eligible"]),
                    "n_distinct_periods": int(guard_row["n_distinct_periods"]),
                }
            )
    return pd.DataFrame.from_records(records)
