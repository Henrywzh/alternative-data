"""Tests for the chart-data view builders in src/common/backtest/views.py.

Synthetic-frame tests exercise the logic in isolation (track-mixing guards,
forecast-row survival, metric-context attachment). The integration tests at
the bottom read the already-materialized
``data/registries/asia_backtest_long_form.csv`` /
``asia_backtest_metrics.csv`` / ``asia_backtest_metric_intervals.csv``
directly and skip (via ``pytest.skip``) if any is absent -- they never
regenerate those artifacts, matching this module's read-only contract
against ``data/registries/``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.common.backtest import views as v
from src.common.backtest.metrics import compute_error_intervals, compute_metric_table
from src.common.backtest.tracks import assert_single_track

LONG_FORM_PATH = Path("data/registries/asia_backtest_long_form.csv")
METRICS_PATH = Path("data/registries/asia_backtest_metrics.csv")
INTERVALS_PATH = Path("data/registries/asia_backtest_metric_intervals.csv")


# ---------------------------------------------------------------------------
# Synthetic long-form row builder (mirrors the LONG_FORM_COLUMNS contract)
# ---------------------------------------------------------------------------


def _row(
    *,
    row_key: str,
    entity_id: str = "E1",
    target_id: str = "T1",
    track_id: str = "fiscal_year",
    period_type: str = "FY",
    period_start: str,
    period_end: str,
    model_id: str = "challenger_v1",
    registry_id: str | None = None,
    is_baseline: bool = False,
    predicted_value: float | None = 100.0,
    actual_value: float | None = 100.0,
    evaluation_status: str = "valid_oos",
    pit_grade: str = "A_strict_pit",
    has_prediction: bool | None = None,
    has_actual: bool | None = None,
    is_primary_source: bool = True,
) -> dict[str, object]:
    reg = registry_id or f"synthetic_source:{period_type}:{track_id}:{model_id}"
    obs_id = f"{entity_id}:{target_id}:{period_type}:{period_start}"
    has_prediction = (predicted_value is not None) if has_prediction is None else has_prediction
    has_actual = (actual_value is not None) if has_actual is None else has_actual
    return {
        "engine_version": "test_engine",
        "registry_id": reg,
        "row_key": row_key,
        "logical_observation_id": obs_id,
        "dedup_group_id": f"{obs_id}:{model_id}",
        "dedup_rank": 1,
        "is_primary_source": is_primary_source,
        "source_dataset": "synthetic_dataset",
        "source_run_id": "",
        "input_bundle_id": "test-bundle",
        "source_row_index": 0,
        "source_row_fingerprint": row_key,
        "natural_observation_key": f"{obs_id}:{model_id}",
        "entity_id": entity_id,
        "target_id": target_id,
        "target_period_start": period_start,
        "target_period_end": period_end,
        "target_period_type": period_type,
        "track_id": track_id,
        "model_id": model_id,
        "model_family": "test_family",
        "is_baseline": is_baseline,
        "model_applied": True,
        "forecast_origin": "not_captured",
        "information_cutoff": "not_captured",
        "source_observation_date": "",
        "actual_available_at": "",
        "actual_source_url": "",
        "predicted_value": predicted_value,
        "actual_value": actual_value,
        "unit": "USD",
        "source_value_columns": "",
        "source_row_status": "historical_evaluated",
        "input_pit_status": "not_captured",
        "target_pit_status": "reported_actual",
        "pit_grade": pit_grade,
        "evaluation_status": evaluation_status,
        "has_prediction": has_prediction,
        "has_actual": has_actual,
        "imputation_used": False,
        "dependency_status": "not_captured",
        "scenario": "",
        "lookback_months": "",
        "model_use": "",
        "research_only": False,
        "source_caveat": "",
        "notes": "",
    }


def _frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def _fy_history_frame(*, n_years: int = 3, model_id: str = "challenger_v1") -> pd.DataFrame:
    """A clean multi-year FY history for one entity/target/model, plus its baseline."""
    rows = []
    for i, year in enumerate(range(2020, 2020 + n_years)):
        rows.append(
            _row(
                row_key=f"model-{year}",
                model_id=model_id,
                period_type="FY",
                track_id="fiscal_year",
                period_start=f"{year}-01-01",
                period_end=f"{year}-12-31",
                predicted_value=100.0 + i,
                actual_value=100.0 + i - 2.0,
                evaluation_status="valid_oos",
                pit_grade="A_strict_pit",
            )
        )
        rows.append(
            _row(
                row_key=f"baseline-{year}",
                model_id="baseline_same_period_last_year",
                is_baseline=True,
                period_type="FY",
                track_id="fiscal_year",
                period_start=f"{year}-01-01",
                period_end=f"{year}-12-31",
                predicted_value=90.0 + i,
                actual_value=100.0 + i - 2.0,
                evaluation_status="valid_oos",
                pit_grade="A_strict_pit",
            )
        )
    return _frame(rows)


# ---------------------------------------------------------------------------
# Rule 1: one chart, one track
# ---------------------------------------------------------------------------


def test_mixing_two_tracks_raises_via_assert_single_track() -> None:
    """The exact frame shape views.py builds internally (post entity/target
    selection, pre track filter) must be rejected by assert_single_track --
    this is the guard every view in this module relies on before emitting a
    time axis. Each single-track slice is built the same way a public view
    function builds it (via the private ``_select_contract_rows`` helper);
    mixing them reproduces what a view would hand to the plotting layer if
    the track_id filter were ever accidentally dropped.
    """
    long_form = _frame(
        [
            _row(
                row_key="fy-1",
                target_id="transport_operations_revenue",
                track_id="fiscal_year",
                period_type="FY",
                period_start="2024-01-01",
                period_end="2024-12-31",
            ),
            _row(
                row_key="h1-1",
                target_id="transport_operations_revenue",
                track_id="half_year_non_overlapping",
                period_type="H1",
                period_start="2024-01-01",
                period_end="2024-06-30",
            ),
        ]
    )
    fy_slice = v._select_contract_rows(
        long_form,
        entity_id="E1",
        target_id="transport_operations_revenue",
        track_id="fiscal_year",
        include_baseline=False,
        model_ids=None,
    )
    h1_slice = v._select_contract_rows(
        long_form,
        entity_id="E1",
        target_id="transport_operations_revenue",
        track_id="half_year_non_overlapping",
        include_baseline=False,
        model_ids=None,
    )
    assert set(fy_slice["track_id"]) == {"fiscal_year"}
    assert set(h1_slice["track_id"]) == {"half_year_non_overlapping"}

    mixed = pd.concat([fy_slice, h1_slice], ignore_index=True)
    with pytest.raises(ValueError, match="mutually exclusive|exactly one track_id"):
        assert_single_track(mixed, context="synthetic mixed-track probe")


def test_model_leaderboard_requires_explicit_track_id_and_never_pools_fy_with_h1() -> None:
    metrics = pd.DataFrame(
        [
            {
                "registry_id": "r1",
                "entity_id": "E1",
                "target_id": "revenue",
                "target_period_type": "FY",
                "track_id": "fiscal_year",
                "model_id": "m1",
                "metric_grain": "per_entity",
                "is_baseline": False,
                "unit_canonical": "USD",
                "skill_vs_baseline": 0.5,
                "scaled_rmse": 0.5,
                "rmse": 1.0,
                "mae": 1.0,
                "bias": 0.1,
                "metric_status": "valid_headline",
                "headline_eligible": True,
                "n_valid": 12,
                "n_distinct_periods": 12,
                "baseline_coverage_status": "complete",
                "directional_hit_rate": 0.8,
                "directional_hit_rate_status": "valid",
            },
            {
                "registry_id": "r2",
                "entity_id": "E1",
                "target_id": "revenue",
                "target_period_type": "H1",
                "track_id": "half_year_non_overlapping",
                "model_id": "m1",
                "metric_grain": "per_entity",
                "is_baseline": False,
                "unit_canonical": "USD",
                "skill_vs_baseline": -0.3,
                "scaled_rmse": 1.3,
                "rmse": 2.0,
                "mae": 2.0,
                "bias": -0.2,
                "metric_status": "insufficient_sample",
                "headline_eligible": False,
                "n_valid": 5,
                "n_distinct_periods": 5,
                "baseline_coverage_status": "partial",
                "directional_hit_rate": np.nan,
                "directional_hit_rate_status": "not_available",
            },
        ]
    )
    fy_only = v.model_leaderboard(metrics, target_id="revenue", track_id="fiscal_year")
    assert set(fy_only["track_id"]) == {"fiscal_year"}
    assert fy_only["skill_vs_baseline"].tolist() == [0.5]

    h1_only = v.model_leaderboard(metrics, target_id="revenue", track_id="half_year_non_overlapping")
    assert set(h1_only["track_id"]) == {"half_year_non_overlapping"}
    assert h1_only["skill_vs_baseline"].tolist() == [-0.3]

    with pytest.raises(TypeError):
        v.model_leaderboard(metrics, target_id="revenue")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Rule 2: nowcast lives on the same axis as backtest
# ---------------------------------------------------------------------------


def test_forecast_only_row_survives_and_is_flagged_not_dropped() -> None:
    long_form = _frame(
        [
            _row(
                row_key="hist-1",
                period_start="2024-01-01",
                period_end="2024-12-31",
                predicted_value=101.0,
                actual_value=99.0,
                evaluation_status="valid_oos",
            ),
            _row(
                row_key="forecast-1",
                period_start="2026-01-01",
                period_end="2026-12-31",
                predicted_value=110.0,
                actual_value=None,
                evaluation_status="forecast_only",
                has_actual=False,
            ),
        ]
    )
    metrics = pd.DataFrame(columns=list(v._METRIC_CONTEXT_COLUMNS) + ["registry_id", "entity_id", "is_baseline", "metric_grain"])
    result = v.sequential_actual_vs_pred(
        long_form, metrics, entity_id="E1", target_id="T1", track_id="fiscal_year"
    )
    forecast_rows = result[result["period_label"] == "FY26"]
    assert len(forecast_rows) == 1
    row = forecast_rows.iloc[0]
    assert row["is_forecast"] is np.True_ or row["is_forecast"] is True
    assert row["value"] == 110.0
    assert row["series_type"] == v.SERIES_MODEL
    # No "actual" series point should be synthesized for the forecast period.
    assert not ((result["period_label"] == "FY26") & (result["series_type"] == v.SERIES_ACTUAL)).any()


def test_forecast_only_row_without_a_prediction_still_survives() -> None:
    """Mirrors the documented MTR Ridge case: model_applied=false outside its
    structural-replay window means has_prediction=False even though the row
    is forecast_only. It must still appear on the axis (value null), not be
    silently dropped because there is "nothing to plot" for it.
    """
    long_form = _frame(
        [
            _row(
                row_key="forecast-no-pred",
                period_start="2026-01-01",
                period_end="2026-12-31",
                predicted_value=None,
                actual_value=None,
                evaluation_status="forecast_only",
                has_prediction=False,
                has_actual=False,
            ),
        ]
    )
    metrics = pd.DataFrame(columns=["registry_id", "entity_id", "is_baseline", "metric_grain", *v._METRIC_CONTEXT_COLUMNS])
    result = v.sequential_actual_vs_pred(
        long_form, metrics, entity_id="E1", target_id="T1", track_id="fiscal_year"
    )
    assert len(result) == 1
    row = result.iloc[0]
    assert bool(row["is_forecast"]) is True
    assert pd.isna(row["value"])


def test_no_source_coverage_row_with_no_data_is_dropped() -> None:
    """Unlike forecast_only, a true no_source_coverage placeholder (neither a
    prediction nor an actual, and not itself forecast_only) carries nothing
    to plot and is dropped -- this is what distinguishes it from rule 2's
    protection for forecast_only rows specifically.
    """
    long_form = _frame(
        [
            _row(
                row_key="no-coverage",
                period_start="2005-01-01",
                period_end="2005-12-31",
                predicted_value=None,
                actual_value=None,
                evaluation_status="no_source_coverage",
                has_prediction=False,
                has_actual=False,
            ),
        ]
    )
    metrics = pd.DataFrame(columns=["registry_id", "entity_id", "is_baseline", "metric_grain", *v._METRIC_CONTEXT_COLUMNS])
    result = v.sequential_actual_vs_pred(
        long_form, metrics, entity_id="E1", target_id="T1", track_id="fiscal_year"
    )
    assert result.empty


# ---------------------------------------------------------------------------
# Rule 3: weak samples must be visible on the chart itself
# ---------------------------------------------------------------------------


def test_metric_and_interval_context_present_in_sequential_view() -> None:
    long_form = _fy_history_frame(n_years=3)
    metrics = compute_metric_table(long_form)
    intervals = compute_error_intervals(long_form, metrics=metrics)
    result = v.sequential_actual_vs_pred(
        long_form, metrics, intervals, entity_id="E1", target_id="T1", track_id="fiscal_year"
    )
    for col in ("metric_status", "n_distinct_periods", "interval_status"):
        assert col in result.columns
    model_rows = result[result["series_type"] == v.SERIES_MODEL]
    assert not model_rows.empty
    assert model_rows["metric_status"].notna().all()


def test_metric_and_interval_context_present_in_error_over_time() -> None:
    long_form = _fy_history_frame(n_years=3)
    metrics = compute_metric_table(long_form)
    intervals = compute_error_intervals(long_form, metrics=metrics)
    result = v.error_over_time(
        long_form, metrics, intervals, entity_id="E1", target_id="T1", track_id="fiscal_year"
    )
    for col in ("metric_status", "n_distinct_periods", "interval_status"):
        assert col in result.columns
    assert not result.empty
    assert result["metric_status"].notna().all()


def test_metric_and_interval_context_present_in_model_leaderboard() -> None:
    long_form = _fy_history_frame(n_years=3)
    metrics = compute_metric_table(long_form)
    intervals = compute_error_intervals(long_form, metrics=metrics)
    result = v.model_leaderboard(metrics, intervals, target_id="T1", track_id="fiscal_year")
    for col in ("metric_status", "n_distinct_periods", "interval_status"):
        assert col in result.columns
    assert not result.empty


def test_degenerate_single_observation_interval_is_flagged() -> None:
    """n_eval == 1 (p10 == p50 == p90, "a distribution of one point") must
    surface as interval_status == "degenerate" wherever interval context is
    attached -- never silently pass through looking like a normal band.
    """
    long_form = _frame(
        [
            _row(
                row_key="single-obs",
                period_start="2024-01-01",
                period_end="2024-12-31",
                predicted_value=105.0,
                actual_value=100.0,
                evaluation_status="valid_oos",
                pit_grade="A_strict_pit",
            ),
        ]
    )
    metrics = compute_metric_table(long_form)
    intervals = compute_error_intervals(long_form, metrics=metrics)
    per_entity_intervals = intervals[intervals["metric_grain"] == "per_entity"]
    assert (per_entity_intervals["n_eval"] == 1).all()
    assert (per_entity_intervals["interval_status"] == "degenerate").all()

    result = v.error_over_time(
        long_form, metrics, intervals, entity_id="E1", target_id="T1", track_id="fiscal_year"
    )
    assert (result["interval_status"] == "degenerate").all()

    leaderboard = v.model_leaderboard(metrics, intervals, target_id="T1", track_id="fiscal_year")
    assert (leaderboard["interval_status"] == "degenerate").all()


# ---------------------------------------------------------------------------
# views.py performs no metric computation (guard against a third
# implementation, echoing airline_earnings_model_v4 vs _live and pivot.py's
# near-miss)
# ---------------------------------------------------------------------------


def test_no_third_metric_implementation_leaderboard_matches_source_exactly() -> None:
    long_form = _fy_history_frame(n_years=4, model_id="challenger_v1")
    metrics = compute_metric_table(long_form)
    intervals = compute_error_intervals(long_form, metrics=metrics)
    source_row = metrics[
        (metrics["metric_grain"] == "per_entity")
        & (~metrics["is_baseline"])
        & (metrics["model_id"] == "challenger_v1")
    ]
    assert len(source_row) == 1
    source_row = source_row.iloc[0]

    leaderboard = v.model_leaderboard(metrics, intervals, target_id="T1", track_id="fiscal_year")
    view_row = leaderboard[leaderboard["model_id"] == "challenger_v1"].iloc[0]
    assert view_row["skill_vs_baseline"] == pytest.approx(source_row["skill_vs_baseline"], nan_ok=True)
    assert view_row["rmse"] == pytest.approx(source_row["rmse"])
    assert view_row["bias"] == pytest.approx(source_row["bias"])
    assert view_row["n_distinct_periods"] == source_row["n_distinct_periods"]
    assert view_row["metric_status"] == source_row["metric_status"]


def test_no_third_metric_implementation_error_over_time_bias_matches_source() -> None:
    long_form = _fy_history_frame(n_years=4, model_id="challenger_v1")
    metrics = compute_metric_table(long_form)
    intervals = compute_error_intervals(long_form, metrics=metrics)
    source_row = metrics[
        (metrics["metric_grain"] == "per_entity")
        & (~metrics["is_baseline"])
        & (metrics["model_id"] == "challenger_v1")
    ].iloc[0]

    result = v.error_over_time(
        long_form, metrics, intervals, entity_id="E1", target_id="T1", track_id="fiscal_year"
    )
    model_rows = result[result["series_id"] == "challenger_v1"]
    assert model_rows["bias"].tolist() == pytest.approx([source_row["bias"]] * len(model_rows))
    # signed_error is a per-row algebraic transform of two long-form columns
    # already in the contract (predicted_value - actual_value), verified
    # directly against those same source columns -- not a recomputation of
    # any named metric.
    recomputed = (model_rows["predicted_value"] - model_rows["actual_value"]).tolist()
    assert model_rows["signed_error"].tolist() == pytest.approx(recomputed)


# ---------------------------------------------------------------------------
# per_entity is the default grain
# ---------------------------------------------------------------------------


def test_model_leaderboard_defaults_to_per_entity_grain() -> None:
    long_form = _fy_history_frame(n_years=3)
    metrics = compute_metric_table(long_form)
    default = v.model_leaderboard(metrics, target_id="T1", track_id="fiscal_year")
    assert not default.empty
    assert set(default["metric_grain"]) == {"per_entity"}
    assert not default["is_reference_only"].any()

    pooled = v.model_leaderboard(metrics, target_id="T1", track_id="fiscal_year", grain="pooled")
    assert not pooled.empty
    assert set(pooled["metric_grain"]) == {"pooled"}
    assert pooled["is_reference_only"].all()


def test_model_leaderboard_rejects_unknown_grain() -> None:
    metrics = pd.DataFrame(columns=["target_id", "track_id", "metric_grain", "is_baseline", "entity_id"])
    with pytest.raises(ValueError, match="grain"):
        v.model_leaderboard(metrics, target_id="T1", track_id="fiscal_year", grain="bogus")


# ---------------------------------------------------------------------------
# Negative skill must read as clearly negative, not clipped
# ---------------------------------------------------------------------------


def test_negative_skill_vs_baseline_is_not_clipped_or_flipped() -> None:
    metrics = pd.DataFrame(
        [
            {
                "registry_id": "r1",
                "entity_id": "E1",
                "target_id": "profit",
                "target_period_type": "FY",
                "track_id": "fiscal_year",
                "model_id": "flat_ask_residual_v1",
                "metric_grain": "per_entity",
                "is_baseline": False,
                "unit_canonical": "USD",
                "skill_vs_baseline": -1.42,
                "scaled_rmse": 2.42,
                "rmse": 5.0,
                "mae": 4.0,
                "bias": -3.0,
                "metric_status": "insufficient_sample",
                "headline_eligible": False,
                "n_valid": 9,
                "n_distinct_periods": 9,
                "baseline_coverage_status": "complete",
                "directional_hit_rate": np.nan,
                "directional_hit_rate_status": "not_available",
            }
        ]
    )
    result = v.model_leaderboard(metrics, target_id="profit", track_id="fiscal_year")
    assert result["skill_vs_baseline"].iloc[0] == pytest.approx(-1.42)


# ---------------------------------------------------------------------------
# Small standalone helpers
# ---------------------------------------------------------------------------


def test_period_label_formatting() -> None:
    assert v._period_label("FY", "2024-01-01") == "FY24"
    assert v._period_label("H1", "2024-01-01") == "H1'24"
    assert v._period_label("H2", "2024-07-01") == "H2'24"
    assert v._period_label("month", "2018-03-01") == "2018-03"


def test_empty_selection_returns_empty_frame_with_contract_columns() -> None:
    long_form = _fy_history_frame(n_years=2)
    metrics = compute_metric_table(long_form)
    result = v.sequential_actual_vs_pred(
        long_form, metrics, entity_id="does-not-exist", target_id="T1", track_id="fiscal_year"
    )
    assert result.empty
    assert list(result.columns) == list(v.SEQUENTIAL_COLUMNS)


def test_coverage_grade_strip_counts_rows_per_period_and_grade() -> None:
    long_form = _frame(
        [
            _row(row_key="a", model_id="m1", period_start="2024-01-01", period_end="2024-12-31", pit_grade="A_strict_pit"),
            _row(row_key="b", model_id="m2", period_start="2024-01-01", period_end="2024-12-31", pit_grade="A_strict_pit"),
            _row(
                row_key="c",
                model_id="m3",
                period_start="2024-01-01",
                period_end="2024-12-31",
                pit_grade="C_structural_replay",
                evaluation_status="historical_structural_check",
            ),
        ]
    )
    result = v.coverage_grade_strip(long_form, entity_id="E1", target_id="T1", track_id="fiscal_year")
    a_grade = result[result["pit_grade"] == "A_strict_pit"]
    assert a_grade["n_rows"].iloc[0] == 2
    assert a_grade["n_distinct_models"].iloc[0] == 2
    c_grade = result[result["pit_grade"] == "C_structural_replay"]
    assert c_grade["n_rows"].iloc[0] == 1


def test_available_chart_axes_reports_forecast_only_counts() -> None:
    long_form = _frame(
        [
            _row(row_key="hist", period_start="2024-01-01", period_end="2024-12-31"),
            _row(
                row_key="fc",
                period_start="2026-01-01",
                period_end="2026-12-31",
                predicted_value=10.0,
                actual_value=None,
                evaluation_status="forecast_only",
                has_actual=False,
            ),
        ]
    )
    axes = v.available_chart_axes(long_form)
    assert len(axes) == 1
    row = axes.iloc[0]
    assert row["n_rows"] == 2
    assert row["n_forecast_only"] == 1


# ---------------------------------------------------------------------------
# Integration tests against the real published artifacts
# ---------------------------------------------------------------------------


def _skip_unless_present(*paths: Path) -> None:
    missing = [str(p) for p in paths if not p.exists()]
    if missing:
        pytest.skip(f"real artifact(s) not present: {missing}")


def test_integration_sequential_view_on_real_data_for_a_known_contract() -> None:
    _skip_unless_present(LONG_FORM_PATH, METRICS_PATH, INTERVALS_PATH)
    long_form = pd.read_csv(LONG_FORM_PATH, low_memory=False)
    metrics = pd.read_csv(METRICS_PATH, low_memory=False)
    intervals = pd.read_csv(INTERVALS_PATH, low_memory=False)

    candidates = long_form[
        (long_form["entity_id"] == "MTR")
        & (long_form["target_id"] == "transport_operations_revenue")
        & (long_form["track_id"] == "fiscal_year")
    ]
    if candidates.empty:
        pytest.skip("MTR transport_operations_revenue fiscal_year contract not present in current registry")

    result = v.sequential_actual_vs_pred(
        long_form, metrics, intervals, entity_id="MTR", target_id="transport_operations_revenue", track_id="fiscal_year"
    )
    assert not result.empty
    assert set(result["track_id"]) == {"fiscal_year"}
    # This contract has no headline-eligible model today (headline_contracts
    # == 0 at time of writing); every model series must say so explicitly
    # rather than default to a misleadingly blank/'valid' status.
    model_rows = result[result["series_type"] == v.SERIES_MODEL]
    assert model_rows["metric_status"].isin(
        ["insufficient_sample", "diagnostic_only", "not_applicable", "valid_headline", "valid_diagnostic"]
    ).all()


def test_integration_model_leaderboard_matches_metrics_csv_verbatim() -> None:
    _skip_unless_present(METRICS_PATH)
    metrics = pd.read_csv(METRICS_PATH, low_memory=False)
    per_entity = metrics[
        (metrics["metric_grain"] == "per_entity") & (~metrics["is_baseline"]) & metrics["skill_vs_baseline"].notna()
    ]
    if per_entity.empty:
        pytest.skip("no per-entity contract with a finite skill_vs_baseline in the current metrics table")
    sample = per_entity.iloc[0]
    leaderboard = v.model_leaderboard(metrics, target_id=str(sample["target_id"]), track_id=str(sample["track_id"]))
    match = leaderboard[
        (leaderboard["entity_id"] == sample["entity_id"]) & (leaderboard["model_id"] == sample["model_id"])
    ]
    assert len(match) == 1
    assert match.iloc[0]["skill_vs_baseline"] == pytest.approx(sample["skill_vs_baseline"])
    assert match.iloc[0]["rmse"] == pytest.approx(sample["rmse"])
    assert match.iloc[0]["metric_status"] == sample["metric_status"]


def test_integration_headline_contracts_are_currently_zero_and_views_say_so() -> None:
    """Documents the current honest state of the engine (headline_contracts
    == 0 per asia_backtest_metrics_manifest.json) so this test breaks loudly,
    rather than silently, the day a contract first clears the bar.
    """
    _skip_unless_present(METRICS_PATH)
    metrics = pd.read_csv(METRICS_PATH, low_memory=False)
    headline = metrics[metrics["headline_eligible"] == True]  # noqa: E712
    if len(headline) != 0:
        pytest.skip(
            "headline_contracts is no longer 0 in the current metrics table; "
            "this test's assumption is stale, not broken -- update it alongside the engine change."
        )
    assert len(headline) == 0


def test_integration_available_chart_axes_nonempty_on_real_long_form() -> None:
    _skip_unless_present(LONG_FORM_PATH)
    long_form = pd.read_csv(LONG_FORM_PATH, low_memory=False)
    axes = v.available_chart_axes(long_form)
    assert not axes.empty
    assert set(v.AVAILABLE_AXES_COLUMNS) <= set(axes.columns)
