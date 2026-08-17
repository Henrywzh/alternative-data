"""Chart-ready view builders for the unified Asia Markets KPI backtest engine.

This module performs **no metric computation**. Every number it emits is
read verbatim off one of the three additive artifacts:

- ``asia_backtest_long_form`` (row-level predictions/actuals/quality flags)
- ``asia_backtest_metrics`` (the Step 6 metric policy: RMSE/MAE/bias,
  ``skill_vs_baseline``, ``metric_status``, sample-size guards, ...)
- ``asia_backtest_metric_intervals`` (PIT-filtered absolute-error
  percentiles and ``interval_status``)

The one place this module touches arithmetic is a row-wise algebraic
transform of two columns that are already part of the long-form contract
(``predicted_value - actual_value``, the same residual convention
``metrics.py`` uses for ``bias``/``rmse``/``mae``) -- never an aggregate,
never a second definition of an existing metric. If you find yourself
writing ``.mean()``, ``.std()``, or anything that looks like a model
evaluation, that computation belongs in ``metrics.py``, not here.

Do not import matplotlib or any plotting library from this module. Every
function here returns a plain ``pandas.DataFrame``; only
``scripts/build_asia_backtest_charts.py`` renders pixels.

Three hard rules, enforced here:

1. **One chart, one track.** Every view that produces a time axis calls
   ``tracks.assert_single_track`` on its output before returning it.
2. **Nowcast lives on the same axis as backtest.** ``forecast_only`` rows
   (null ``actual_value``) are never dropped by the row-selection helpers
   below; they survive into the chart frame with ``is_forecast=True`` so a
   renderer can draw them as the hollow/dashed forward point of the same
   series.
3. **Weak samples must be visible on the chart itself.** ``metric_status``,
   ``interval_status``, and ``n_distinct_periods`` are attached to every
   view that shows a per-series or per-contract aggregate, so a consumer
   cannot plot a headline-looking chart out of an ``insufficient_sample`` or
   ``degenerate`` contract without the flag riding along.
"""

from __future__ import annotations

from typing import Final, Iterable

import pandas as pd

from .tracks import assert_single_track

# ---------------------------------------------------------------------------
# Shared vocabulary for the chart-data contract
# ---------------------------------------------------------------------------

SERIES_ACTUAL: Final[str] = "actual"
SERIES_MODEL: Final[str] = "model"
SERIES_BASELINE: Final[str] = "baseline"

DEFAULT_METRIC_GRAIN: Final[str] = "per_entity"

# entity_id/target_id/track_id are the required scoping filters for each
# view that needs them; scripts/build_asia_backtest_charts.py uses this to
# drive its --all enumeration without hard-coding each view's signature.
VIEW_REQUIRED_FILTERS: Final[dict[str, tuple[str, ...]]] = {
    "sequential_actual_vs_pred": ("entity_id", "target_id", "track_id"),
    "error_over_time": ("entity_id", "target_id", "track_id"),
    "model_leaderboard": ("target_id", "track_id"),
    "coverage_grade_strip": ("entity_id", "target_id", "track_id"),
}

_METRIC_CONTEXT_COLUMNS: Final[tuple[str, ...]] = (
    "metric_status",
    "headline_eligible",
    "n_valid",
    "n_distinct_periods",
    "baseline_coverage_status",
    "skill_vs_baseline",
    "scaled_rmse",
    "bias",
    "rmse",
    "mae",
)

_INTERVAL_CONTEXT_COLUMNS: Final[tuple[str, ...]] = (
    "interval_status",
    "n_eval",
    "error_p10",
    "error_p50",
    "error_p90",
)

SEQUENTIAL_COLUMNS: Final[tuple[str, ...]] = (
    "entity_id",
    "target_id",
    "track_id",
    "target_period_type",
    "target_period_start",
    "target_period_end",
    "period_label",
    "series_id",
    "series_type",
    "registry_id",
    "is_baseline",
    "value",
    "is_forecast",
    "has_actual",
    "pit_grade",
    "evaluation_status",
) + _METRIC_CONTEXT_COLUMNS + _INTERVAL_CONTEXT_COLUMNS

ERROR_OVER_TIME_COLUMNS: Final[tuple[str, ...]] = (
    "entity_id",
    "target_id",
    "track_id",
    "target_period_type",
    "target_period_start",
    "target_period_end",
    "period_label",
    "series_id",
    "series_type",
    "registry_id",
    "is_baseline",
    "predicted_value",
    "actual_value",
    "signed_error",
    "pit_grade",
    "evaluation_status",
) + _METRIC_CONTEXT_COLUMNS + _INTERVAL_CONTEXT_COLUMNS

LEADERBOARD_COLUMNS: Final[tuple[str, ...]] = (
    "registry_id",
    "entity_id",
    "target_id",
    "target_period_type",
    "track_id",
    "model_id",
    "metric_grain",
    "is_reference_only",
    "unit_canonical",
    "skill_vs_baseline",
    "scaled_rmse",
    "rmse",
    "mae",
    "bias",
    "metric_status",
    "headline_eligible",
    "n_valid",
    "n_distinct_periods",
    "baseline_coverage_status",
    "directional_hit_rate",
    "directional_hit_rate_status",
    "interval_status",
)

COVERAGE_COLUMNS: Final[tuple[str, ...]] = (
    "entity_id",
    "target_id",
    "track_id",
    "target_period_type",
    "target_period_start",
    "target_period_end",
    "period_label",
    "pit_grade",
    "evaluation_status",
    "n_rows",
    "n_distinct_models",
)

AVAILABLE_AXES_COLUMNS: Final[tuple[str, ...]] = (
    "entity_id",
    "target_id",
    "track_id",
    "target_period_type",
    "n_rows",
    "n_forecast_only",
    "n_distinct_models",
)


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _period_label(period_type: object, period_start: object) -> str:
    """Return the short axis label for one target period.

    Half-year rows: ``H1'24`` / ``H2'24``. Fiscal-year rows: ``FY24``.
    Monthly rows: ``2018-01``. Anything else falls back to the ISO date so a
    future period type still renders instead of raising.
    """
    ts = pd.Timestamp(period_start)
    period_type = str(period_type)
    yy = ts.strftime("%y")
    if period_type == "FY":
        return f"FY{yy}"
    if period_type in ("H1", "H2"):
        return f"{period_type}'{yy}"
    if period_type == "month":
        return ts.strftime("%Y-%m")
    return ts.strftime("%Y-%m-%d")


def _select_contract_rows(
    long_form: pd.DataFrame,
    *,
    entity_id: str,
    target_id: str,
    track_id: str,
    include_baseline: bool,
    model_ids: Iterable[str] | None,
) -> pd.DataFrame:
    """Return primary-source long-form rows for one entity/target/track.

    Rows with neither a prediction nor an actual (true ``no_source_coverage``
    placeholders) are dropped -- there is nothing to plot for them. Every
    ``forecast_only`` row is kept regardless of whether it carries a
    prediction, so the "MTR Ridge 2026 has no applied prediction outside its
    structural-replay window" case documented in
    ``docs/asia-markets/unified-kpi-backtest-v1.md`` still surfaces as an
    explicit forward point rather than silently vanishing.
    """
    frame = long_form[
        (long_form["entity_id"] == entity_id)
        & (long_form["target_id"] == target_id)
        & (long_form["track_id"] == track_id)
        & (long_form["is_primary_source"] == True)  # noqa: E712
    ].copy()
    if not include_baseline:
        frame = frame[frame["is_baseline"] == False]  # noqa: E712
    if model_ids is not None:
        wanted = set(model_ids)
        frame = frame[frame["model_id"].isin(wanted) | frame["is_baseline"]]
    keep = (
        frame["has_prediction"].astype(bool)
        | frame["has_actual"].astype(bool)
        | frame["evaluation_status"].eq("forecast_only")
    )
    return frame[keep]


def _attach_metric_context(
    frame: pd.DataFrame,
    metrics: pd.DataFrame,
    intervals: pd.DataFrame | None,
    *,
    grain: str = DEFAULT_METRIC_GRAIN,
) -> pd.DataFrame:
    """Join per-series ``metrics``/``intervals`` context onto a chart frame.

    ``frame`` must carry ``registry_id``, ``entity_id``, and ``is_baseline``
    columns (rows with a null ``registry_id`` -- the synthetic "actual"
    series -- never match and are left with the "not_applicable" fallback).
    The metrics table stores one row per (registry_id, entity_id, is_baseline,
    metric_grain) -- a model contract and its same-period-last-year baseline
    share ``registry_id`` but differ in ``model_id``/``is_baseline``, so all
    three keys are required for a unique join; dropping ``is_baseline`` here
    would silently blend a model's accuracy context onto its own baseline.
    """
    result = frame.copy()
    join_keys = ["registry_id", "entity_id", "is_baseline"]
    if metrics is not None and not metrics.empty:
        metric_slice = (
            metrics[metrics["metric_grain"] == grain][[*join_keys, *_METRIC_CONTEXT_COLUMNS]]
            .drop_duplicates(subset=join_keys)
        )
        result = result.merge(metric_slice, on=join_keys, how="left", validate="many_to_one")
    else:
        for col in _METRIC_CONTEXT_COLUMNS:
            result[col] = pd.NA
    result["metric_status"] = result["metric_status"].fillna("not_applicable")
    result["headline_eligible"] = result["headline_eligible"].astype("boolean").fillna(False).astype(bool)

    if intervals is not None and not intervals.empty:
        interval_slice = (
            intervals[intervals["metric_grain"] == grain][
                ["registry_id", "entity_id", *_INTERVAL_CONTEXT_COLUMNS]
            ].drop_duplicates(subset=["registry_id", "entity_id"])
        )
        result = result.merge(interval_slice, on=["registry_id", "entity_id"], how="left", validate="many_to_one")
    else:
        for col in _INTERVAL_CONTEXT_COLUMNS:
            result[col] = pd.NA
    result["interval_status"] = result["interval_status"].fillna("not_applicable")
    return result


# ---------------------------------------------------------------------------
# The four default views
# ---------------------------------------------------------------------------


def sequential_actual_vs_pred(
    long_form: pd.DataFrame,
    metrics: pd.DataFrame,
    intervals: pd.DataFrame | None = None,
    *,
    entity_id: str,
    target_id: str,
    track_id: str,
    model_ids: Iterable[str] | None = None,
    include_baseline: bool = False,
) -> pd.DataFrame:
    """Actual vs. each model's prediction over the non-overlapping period sequence.

    One row per (period, series); ``series_id`` is a ``model_id`` or the
    literal string ``"actual"``. The x-axis sequence for
    ``half_year_non_overlapping`` is chronological (H1'24, H2'24, H1'25, ...)
    because sorting is done on ``target_period_start``, never interleaved
    with another track (``assert_single_track`` enforces this on the input
    before any row is emitted).

    Nowcast/forecast rows (``evaluation_status == "forecast_only"``) are
    never dropped: they appear with ``is_forecast=True`` and, if the source
    row genuinely has no prediction (e.g. the MTR Ridge residual outside its
    structural-replay window), ``value`` is null but the row itself still
    ties into the axis so a renderer can mark the gap explicitly instead of
    silently truncating the series.
    """
    frame = _select_contract_rows(
        long_form,
        entity_id=entity_id,
        target_id=target_id,
        track_id=track_id,
        include_baseline=include_baseline,
        model_ids=model_ids,
    )
    if frame.empty:
        return pd.DataFrame(columns=SEQUENTIAL_COLUMNS)
    assert_single_track(frame, context=f"sequential_actual_vs_pred({entity_id}, {target_id}, {track_id})")

    records: list[dict[str, object]] = []
    for row in frame.itertuples(index=False):
        records.append(
            {
                "entity_id": entity_id,
                "target_id": target_id,
                "track_id": track_id,
                "target_period_type": row.target_period_type,
                "target_period_start": row.target_period_start,
                "target_period_end": row.target_period_end,
                "period_label": _period_label(row.target_period_type, row.target_period_start),
                "series_id": row.model_id,
                "series_type": SERIES_BASELINE if row.is_baseline else SERIES_MODEL,
                "registry_id": row.registry_id,
                "is_baseline": bool(row.is_baseline),
                "value": row.predicted_value,
                "is_forecast": row.evaluation_status == "forecast_only",
                "has_actual": bool(row.has_actual),
                "pit_grade": row.pit_grade,
                "evaluation_status": row.evaluation_status,
            }
        )

    actual_rows = frame[frame["has_actual"] == True].drop_duplicates(subset=["target_period_start"])  # noqa: E712
    for row in actual_rows.itertuples(index=False):
        records.append(
            {
                "entity_id": entity_id,
                "target_id": target_id,
                "track_id": track_id,
                "target_period_type": row.target_period_type,
                "target_period_start": row.target_period_start,
                "target_period_end": row.target_period_end,
                "period_label": _period_label(row.target_period_type, row.target_period_start),
                "series_id": SERIES_ACTUAL,
                "series_type": SERIES_ACTUAL,
                "registry_id": pd.NA,
                "is_baseline": False,
                "value": row.actual_value,
                "is_forecast": False,
                "has_actual": True,
                "pit_grade": row.pit_grade,
                "evaluation_status": row.evaluation_status,
            }
        )

    result = pd.DataFrame.from_records(records)
    result = _attach_metric_context(result, metrics, intervals, grain=DEFAULT_METRIC_GRAIN)
    result = result.reindex(columns=SEQUENTIAL_COLUMNS)
    return result.sort_values(
        ["target_period_start", "series_type", "series_id"], kind="stable"
    ).reset_index(drop=True)


def error_over_time(
    long_form: pd.DataFrame,
    metrics: pd.DataFrame,
    intervals: pd.DataFrame | None = None,
    *,
    entity_id: str,
    target_id: str,
    track_id: str,
    model_ids: Iterable[str] | None = None,
    include_baseline: bool = False,
) -> pd.DataFrame:
    """Signed error (``predicted_value - actual_value``) per evaluated period.

    Signed, not absolute, so a systematic over- or under-forecast (bias) is
    visible on the chart rather than only in the ``bias`` column pulled from
    ``asia_backtest_metrics``. Only rows with both a prediction and a
    realized actual are included -- there is no error to plot for a
    ``forecast_only`` row, which is why ``sequential_actual_vs_pred`` is the
    view responsible for surfacing those, not this one.
    """
    frame = _select_contract_rows(
        long_form,
        entity_id=entity_id,
        target_id=target_id,
        track_id=track_id,
        include_baseline=include_baseline,
        model_ids=model_ids,
    )
    frame = frame[frame["has_prediction"].astype(bool) & frame["has_actual"].astype(bool)].copy()
    if frame.empty:
        return pd.DataFrame(columns=ERROR_OVER_TIME_COLUMNS)
    assert_single_track(frame, context=f"error_over_time({entity_id}, {target_id}, {track_id})")

    # Same residual convention as metrics.py's bias/rmse/mae (predicted minus
    # actual); this is a per-row algebraic transform of two long-form
    # columns already in the contract, not a new metric definition.
    frame["signed_error"] = frame["predicted_value"] - frame["actual_value"]
    frame["period_label"] = [
        _period_label(pt, ps) for pt, ps in zip(frame["target_period_type"], frame["target_period_start"])
    ]
    frame["series_id"] = frame["model_id"]
    frame["series_type"] = frame["is_baseline"].map({True: SERIES_BASELINE, False: SERIES_MODEL})

    result = frame[
        [
            "entity_id",
            "target_id",
            "track_id",
            "target_period_type",
            "target_period_start",
            "target_period_end",
            "period_label",
            "series_id",
            "series_type",
            "registry_id",
            "is_baseline",
            "predicted_value",
            "actual_value",
            "signed_error",
            "pit_grade",
            "evaluation_status",
        ]
    ].copy()
    result = _attach_metric_context(result, metrics, intervals, grain=DEFAULT_METRIC_GRAIN)
    result = result.reindex(columns=ERROR_OVER_TIME_COLUMNS)
    return result.sort_values(
        ["target_period_start", "series_type", "series_id"], kind="stable"
    ).reset_index(drop=True)


def model_leaderboard(
    metrics: pd.DataFrame,
    intervals: pd.DataFrame | None = None,
    *,
    target_id: str,
    track_id: str,
    entity_id: str | None = None,
    grain: str = DEFAULT_METRIC_GRAIN,
) -> pd.DataFrame:
    """``skill_vs_baseline`` per model for one target, straight off ``asia_backtest_metrics``.

    ``track_id`` is required, not optional: a target such as Airlines
    ``revenue`` has both an ``H1`` contract (``half_year_non_overlapping``)
    and an ``FY`` contract (``fiscal_year``), and pooling both into one
    leaderboard would double-count the same underlying information (H2 = FY
    - H1). ``assert_single_track`` raises rather than silently picking one.

    ``grain="per_entity"`` is the default and only grain that may be
    headline-eligible; ``grain="pooled"`` is accepted as an explicit
    reference view and is always flagged via ``is_reference_only=True``
    (``compute_metric_table`` already hard-forces ``headline_eligible=False``
    for pooled rows, so this column is redundant with that guarantee, not a
    substitute for it).

    Negative ``skill_vs_baseline`` (a model doing worse than the naive
    same-period-last-year baseline) is returned unmodified -- this function
    never clips, floors, or takes an absolute value of the sign.

    ``intervals`` (``asia_backtest_metric_intervals``) is optional; when
    supplied, its ``interval_status`` is joined in so a degenerate
    single-observation distribution (``n_eval == 1``) is visible on the
    leaderboard itself, not only in a caveat a reader might miss.
    """
    if grain not in ("per_entity", "pooled"):
        raise ValueError(f"grain must be 'per_entity' or 'pooled', got {grain!r}")
    if metrics.empty:
        return pd.DataFrame(columns=LEADERBOARD_COLUMNS)
    frame = metrics[
        (metrics["target_id"] == target_id)
        & (metrics["track_id"] == track_id)
        & (metrics["metric_grain"] == grain)
        & (metrics["is_baseline"] == False)  # noqa: E712
    ].copy()
    if entity_id is not None:
        frame = frame[frame["entity_id"] == entity_id]
    if frame.empty:
        return pd.DataFrame(columns=LEADERBOARD_COLUMNS)
    assert_single_track(frame, context=f"model_leaderboard({target_id}, {track_id})")
    frame["is_reference_only"] = grain == "pooled"
    if intervals is not None and not intervals.empty:
        interval_slice = (
            intervals[intervals["metric_grain"] == grain][["registry_id", "entity_id", "interval_status"]]
            .drop_duplicates(subset=["registry_id", "entity_id"])
        )
        frame = frame.merge(interval_slice, on=["registry_id", "entity_id"], how="left", validate="many_to_one")
    else:
        frame["interval_status"] = pd.NA
    frame["interval_status"] = frame["interval_status"].fillna("not_applicable")
    result = frame[
        [
            "registry_id",
            "entity_id",
            "target_id",
            "target_period_type",
            "track_id",
            "model_id",
            "metric_grain",
            "is_reference_only",
            "unit_canonical",
            "skill_vs_baseline",
            "scaled_rmse",
            "rmse",
            "mae",
            "bias",
            "metric_status",
            "headline_eligible",
            "n_valid",
            "n_distinct_periods",
            "baseline_coverage_status",
            "directional_hit_rate",
            "directional_hit_rate_status",
            "interval_status",
        ]
    ].copy()
    return result.sort_values(["model_id", "entity_id"], kind="stable").reset_index(drop=True)


def coverage_grade_strip(
    long_form: pd.DataFrame,
    *,
    entity_id: str,
    target_id: str,
    track_id: str,
    include_baseline: bool = False,
) -> pd.DataFrame:
    """``pit_grade`` x ``evaluation_status`` row composition per period.

    Pure counting over already-present columns -- no value arithmetic at
    all -- so a renderer can show, period by period, how much of the
    coverage behind a chart is strict/practical PIT vs. structural replay
    vs. diagnostic-only vs. missing, independent of whether any model's
    accuracy number is currently headline-eligible.
    """
    frame = long_form[
        (long_form["entity_id"] == entity_id)
        & (long_form["target_id"] == target_id)
        & (long_form["track_id"] == track_id)
        & (long_form["is_primary_source"] == True)  # noqa: E712
    ].copy()
    if not include_baseline:
        frame = frame[frame["is_baseline"] == False]  # noqa: E712
    if frame.empty:
        return pd.DataFrame(columns=COVERAGE_COLUMNS)
    assert_single_track(frame, context=f"coverage_grade_strip({entity_id}, {target_id}, {track_id})")
    frame["period_label"] = [
        _period_label(pt, ps) for pt, ps in zip(frame["target_period_type"], frame["target_period_start"])
    ]
    group_columns = [
        "target_period_start",
        "target_period_end",
        "target_period_type",
        "period_label",
        "pit_grade",
        "evaluation_status",
    ]
    counts = (
        frame.groupby(group_columns, dropna=False)
        .agg(n_rows=("row_key", "count"), n_distinct_models=("model_id", "nunique"))
        .reset_index()
    )
    counts["entity_id"] = entity_id
    counts["target_id"] = target_id
    counts["track_id"] = track_id
    counts = counts.reindex(columns=COVERAGE_COLUMNS)
    return counts.sort_values(
        ["target_period_start", "pit_grade", "evaluation_status"], kind="stable"
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Discovery helper for the renderer's --all mode
# ---------------------------------------------------------------------------


def available_chart_axes(long_form: pd.DataFrame) -> pd.DataFrame:
    """Return every (entity_id, target_id, track_id, target_period_type) combination.

    Used by ``scripts/build_asia_backtest_charts.py`` to enumerate what can
    actually be rendered from the current long form -- so "no data for this
    selection" can be reported explicitly rather than discovered by writing
    an empty chart.
    """
    frame = long_form[long_form["is_primary_source"] == True].copy()  # noqa: E712
    if frame.empty:
        return pd.DataFrame(columns=AVAILABLE_AXES_COLUMNS)
    grouped = frame.groupby(["entity_id", "target_id", "track_id", "target_period_type"], dropna=False)
    result = grouped.agg(
        n_rows=("row_key", "count"),
        n_forecast_only=("evaluation_status", lambda s: int((s == "forecast_only").sum())),
        n_distinct_models=("model_id", "nunique"),
    ).reset_index()
    return result.sort_values(["entity_id", "target_id", "track_id"], kind="stable").reset_index(drop=True)
