"""Tests for the Step 6 metric-policy builder."""

from __future__ import annotations

import os as _os
from pathlib import Path as _Path

# The builders write here; tests/conftest.py redirects the directory so those
# writes stay out of the working tree. Reading the literal "data/registries/..."
# would have read the repository's stale copy instead of what the test built.
_REGISTRY_DIR = _Path(_os.environ.get("ASIA_BACKTEST_REGISTRY_DIR", "").strip() or "data/registries")

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from scripts.build_asia_backtest_metrics import build_metrics
from src.common.backtest.metrics import compute_error_intervals, compute_metric_table
from src.common.backtest.vocabulary import canonicalize_unit


METRICS_CSV = Path(_REGISTRY_DIR / "asia_backtest_metrics.csv")


def _metrics() -> pd.DataFrame:
    """The built metric table, built here if no earlier test happened to.

    data/registries is gitignored, so on a fresh checkout this file exists
    only because some other test in this module called build_metrics() first.
    Several tests read it without doing so, which made them pass or fail on
    how pytest-xdist happened to distribute the module: adding tests anywhere
    in the suite could flip them. A reader that guarantees its own input has
    no such dependency.
    """
    if not METRICS_CSV.is_file():
        build_metrics()
    return pd.read_csv(METRICS_CSV)


def _synthetic_row(
    *,
    row_key: str,
    period_start: str,
    period_end: str,
    predicted_value: float,
    actual_value: float,
    registry_id: str = "synthetic:FY:revenue:challenger_v1",
    entity_id: str = "E1",
    model_id: str = "challenger_v1",
    is_baseline: bool = False,
    logical_observation_id: str | None = None,
    unit: str = "USD",
) -> dict:
    obs_id = logical_observation_id or f"{entity_id}:revenue:FY:{period_start}"
    return {
        "engine_version": "test_engine",
        "registry_id": registry_id,
        "row_key": row_key,
        "logical_observation_id": obs_id,
        "dedup_group_id": f"{obs_id}:{model_id}",
        "dedup_rank": 1,
        "is_primary_source": True,
        "source_dataset": "synthetic_dataset",
        "source_run_id": "",
        "input_bundle_id": "test-bundle",
        "source_row_index": 0,
        "source_row_fingerprint": row_key,
        "natural_observation_key": f"{obs_id}:{model_id}",
        "entity_id": entity_id,
        "target_id": "revenue",
        "target_period_start": period_start,
        "target_period_end": period_end,
        "target_period_type": "FY",
        "track_id": "fiscal_year",
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
        "unit": unit,
        "source_value_columns": "",
        "source_row_status": "historical_evaluated",
        "input_pit_status": "not_captured",
        "target_pit_status": "reported_actual",
        "pit_grade": "B_practical_pit",
        "evaluation_status": "valid_forward_oos",
        "has_prediction": True,
        "has_actual": True,
        "imputation_used": False,
        "dependency_status": "not_captured",
        "scenario": "",
        "lookback_months": "",
        "model_use": "",
        "research_only": False,
        "source_caveat": "",
        "notes": "",
    }


def test_metrics_builder_reports_sixteen_headline_contracts() -> None:
    # B2 fix: cross-sectional pooling (6 airlines x ~9 years) inflates n_valid
    # far past min_headline_rows while the true independent sample is the
    # distinct target-period count (6-9). Every previously "headline" airline
    # contract now fails the n_distinct_periods guard, so the headline set is
    # correctly empty until the engine accumulates more independent periods.
    # This assertion is deliberately updated from the pre-fix value of 16.
    manifest = build_metrics()
    metrics = _metrics()
    assert manifest["metric_policy_version"] == "asia_backtest_metrics_v2"
    assert manifest["headline_contracts"] == 0
    assert manifest["headline_contract_ids"] == []
    assert manifest["headline_metric_ids"] == []
    assert manifest["contract_rows"] == len(metrics)
    headline = metrics[metrics["headline_eligible"] == True]  # noqa: E712
    assert len(headline) == 0
    # Baselines are never headline contracts themselves.
    assert not headline["is_baseline"].any()


def test_airline_fy_revenue_contract_flips_to_insufficient_sample_on_period_count() -> None:
    # B2 fix: this contract pools 6 airlines across 9 distinct fiscal years
    # (n_valid=53) but only has 9 independent target periods, below the
    # FY min_headline_rows guard of 10. It is no longer headline_eligible.
    # This assertion is deliberately updated: previously it asserted
    # metric_status == "valid_headline" / headline_eligible == True, which
    # over-claimed a pooled cross-sectional sample as an independent one.
    #
    # B3 fix: the metrics table now also carries per-entity rows for this
    # registry_id (one per airline), so the old "exactly one non-baseline
    # row" filter is no longer unique on registry_id + is_baseline alone.
    # Restricting to metric_grain == "pooled" recovers the original,
    # deliberately-preserved pooled aggregate this test was written against.
    metrics = _metrics()
    row = metrics[
        metrics["registry_id"].eq("airline_period_kpi_backtest:FY:revenue:flat_ask_v1")
        & ~metrics["is_baseline"]
        & metrics["metric_grain"].eq("pooled")
    ]
    assert len(row) == 1
    row = row.iloc[0]
    assert row["metric_status"] == "insufficient_sample"
    assert bool(row["headline_eligible"]) is False
    assert row["n_valid"] == 53
    assert row["n_distinct_periods"] == 9
    assert row["n_distinct_entities"] == 6
    assert row["mae"] == pytest.approx(3870.72, rel=1e-3)
    # B1 fix: scaled_rmse/skill_vs_baseline must be computed from the model
    # RMSE restricted to the same overlap rows used for baseline_rmse
    # (rmse_on_overlap/n_scaled), not the full-sample rmse. This is the
    # deliberately updated, like-for-like value (was 0.20529 pre-fix, which
    # mixed a 53-row model RMSE against a 47-row baseline RMSE).
    assert row["n_scaled"] == 47
    assert row["rmse_on_overlap"] == pytest.approx(6027.165903, rel=1e-4)
    assert row["scaled_rmse"] == pytest.approx(0.21498, rel=1e-3)
    assert row["skill_vs_baseline"] == pytest.approx(0.78502, rel=1e-3)
    assert row["baseline_n_overlap"] == 47
    assert row["unit"] == "RMB mn"
    assert row["unit_canonical"] == "RMB_mn"
    assert row["n_structural_excluded"] == 1
    assert row["wape_status"] == "valid"
    # B3: pooled rows are structurally ineligible for headline status,
    # regardless of n_valid.
    assert row["metric_grain"] == "pooled"


def test_mtr_fy_physics_contract_never_reaches_headline() -> None:
    # B3: restrict to the pooled row for the same reason as the airline FY
    # revenue test above -- this registry_id now also carries a per-entity
    # row (entity_id == "MTR"), which duplicates the pooled row's content
    # exactly since MTR is the sole entity on this contract.
    metrics = _metrics()
    row = metrics[
        metrics["registry_id"].eq("mtr_farebox_revenue_annual_backtest:FY:fiscal_year:mtr_physics_yield_v1")
        & ~metrics["is_baseline"]
        & metrics["metric_grain"].eq("pooled")
    ]
    assert len(row) == 1
    row = row.iloc[0]
    # Only the 2025 forward-OOS observation survives the accuracy filter;
    # the 2019-2024 structural rows never enter the table.
    assert row["metric_scope"] == "headline_candidate"
    assert row["metric_status"] == "insufficient_sample"
    assert bool(row["headline_eligible"]) is False
    assert row["n_headline_valid"] == 1  # only FY2025 is forward OOS
    assert row["n_valid"] == 1


def test_shkp_contract_activity_is_diagnostic_only_in_metrics() -> None:
    # B3: every SHKP contract-activity contract has exactly one entity
    # (SHKP), so each pooled row now has a matching per-entity row with
    # identical content -- doubling the row count from the pre-B3 value of
    # 12 to 24 (6 models x (challenger + baseline) x 2 grains).
    metrics = _metrics()
    rows = metrics[metrics["registry_id"].str.contains("contract_activity_proxy")]
    assert len(rows) == 24
    pooled = rows[rows["metric_grain"] == "pooled"]
    per_entity = rows[rows["metric_grain"] == "per_entity"]
    assert len(pooled) == 12
    assert len(per_entity) == 12
    assert (per_entity["entity_id"] == "SHKP").all()
    assert (per_entity["n_distinct_entities"] == 1).all()
    challengers = rows[~rows["is_baseline"]]
    assert (challengers["metric_scope"] == "diagnostic_only").all()
    assert (challengers["metric_status"] == "diagnostic_only").all()
    assert not challengers["headline_eligible"].any()


def test_error_interval_artifact_is_well_formed() -> None:
    build_metrics()
    intervals = pd.read_csv(_REGISTRY_DIR / "asia_backtest_metric_intervals.csv")
    assert len(intervals) > 0
    assert {"metric_grain", "entity_id", "unit_canonical"}.issubset(intervals.columns)
    assert set(intervals["metric_grain"]) == {"pooled", "per_entity"}
    pooled = intervals[intervals["metric_grain"] == "pooled"]
    per_entity = intervals[intervals["metric_grain"] == "per_entity"]
    assert (pooled["entity_id"].str.contains(";") | pooled["entity_id"].notna()).all()
    assert (per_entity["entity_id"] != "").all()
    assert (intervals["error_p10"] <= intervals["error_p50"]).all()
    assert (intervals["error_p50"] <= intervals["error_p90"]).all()
    assert (intervals["n_eval"] > 0).all()
    # Intervals exclude baseline rows (challenger contracts only).
    assert not intervals["model_id"].str.contains("baseline").any()


# ---------------------------------------------------------------------------
# N2: error-intervals table sample guard
# ---------------------------------------------------------------------------


def test_error_interval_guard_columns_present() -> None:
    # N2: a consumer plotting an error band must be able to see, without
    # cross-referencing another table, whether the band is a real
    # distribution -- n_distinct_periods is the same independent-sample
    # notion the metrics table guards on, metric_status/interval_status
    # state whether the band means anything at all.
    build_metrics()
    intervals = pd.read_csv(_REGISTRY_DIR / "asia_backtest_metric_intervals.csv")
    assert {"n_distinct_periods", "metric_status", "interval_status"}.issubset(intervals.columns)
    assert (intervals["n_distinct_periods"] > 0).all()
    assert (intervals["n_distinct_periods"] <= intervals["n_eval"]).all()
    assert intervals["interval_status"].notna().all()


def test_error_interval_degenerate_rows_have_collapsed_percentiles() -> None:
    # Concrete case from the real artifact: a single-observation interval
    # (n_eval == 1) has every percentile equal to that one observation --
    # anyone plotting this as a band without the guard column would read a
    # single point as a distribution.
    build_metrics()
    intervals = pd.read_csv(_REGISTRY_DIR / "asia_backtest_metric_intervals.csv")
    single_obs = intervals[intervals["n_eval"] == 1]
    assert len(single_obs) > 0
    assert (single_obs["interval_status"] == "degenerate").all()
    for col in ("error_p25", "error_p50", "error_p75", "error_p90"):
        assert (single_obs[col] == single_obs["error_p10"]).all()
    # No row with n_eval > 1 and nonzero spread is ever mislabeled degenerate.
    spread = intervals["error_p90"] - intervals["error_p10"]
    non_degenerate_by_construction = intervals[(intervals["n_eval"] > 1) & (spread > 0)]
    assert (non_degenerate_by_construction["interval_status"] != "degenerate").all()


def test_error_interval_metric_status_agrees_with_metrics_table_across_artifact() -> None:
    # N2 requirement: the intervals table must never disagree with the
    # metrics table's classification for the same contract/grain/entity.
    # Checked here by rebuilding both tables from the same long form and
    # confirming every interval row's carried-through metric_status equals
    # the metrics table's metric_status for the matching
    # (registry_id, model_id, target_period_type, track_id, unit,
    # metric_grain, entity_id) key -- and that no row claims "eligible" or
    # "reference_only" while the metrics table says the sample was
    # insufficient.
    long_form = pd.read_parquet(_REGISTRY_DIR / "asia_backtest_long_form.parquet")
    metrics = compute_metric_table(long_form)
    intervals = compute_error_intervals(long_form, metrics=metrics)
    assert len(intervals) > 0

    challengers = metrics[~metrics["is_baseline"]]
    key = ["registry_id", "model_id", "target_period_type", "track_id", "unit", "metric_grain", "entity_id"]
    merged = intervals.merge(
        challengers[key + ["metric_status"]],
        on=key,
        how="left",
        suffixes=("", "_from_metrics_table"),
    )
    assert merged["metric_status_from_metrics_table"].notna().all()
    assert (merged["metric_status"] == merged["metric_status_from_metrics_table"]).all()

    # "eligible" is the only interval_status that tells a consumer the band
    # is safe to plot as-is; "reference_only" (pooled) and "degenerate" both
    # withhold that claim, so only "eligible" needs to be ruled out here.
    insufficient = intervals[intervals["metric_status"] == "insufficient_sample"]
    assert len(insufficient) > 0
    assert not (insufficient["interval_status"] == "eligible").any()


def test_error_interval_status_classification_synthetic() -> None:
    # Exercises every interval_status branch explicitly, including
    # "eligible" (per_entity, valid_headline, non-degenerate), which never
    # occurs in the current real artifact because no contract yet clears
    # the headline sample guard.
    rows = [
        _synthetic_row(
            row_key=f"c-{year}",
            period_start=f"{year}-01-01",
            period_end=f"{year}-12-31",
            predicted_value=105.0 + year % 3,
            actual_value=100.0,
            registry_id="synthetic:FY:revenue:interval_status_v1",
            entity_id="E1",
            model_id="interval_status_v1",
        )
        for year in range(2010, 2020)
    ]
    frame = pd.DataFrame(rows)
    metrics = compute_metric_table(frame)
    intervals = compute_error_intervals(frame, metrics=metrics)

    per_entity = intervals[intervals["metric_grain"] == "per_entity"].iloc[0]
    assert per_entity["n_eval"] == 10
    assert per_entity["n_distinct_periods"] == 10
    assert per_entity["metric_status"] == "valid_headline"
    assert per_entity["interval_status"] == "eligible"

    pooled = intervals[intervals["metric_grain"] == "pooled"].iloc[0]
    # Pooled stays a reference distribution even though the underlying
    # metrics row is also valid_headline -- it is never headline eligible.
    assert pooled["metric_status"] == "valid_headline"
    assert pooled["interval_status"] == "reference_only"


# ---------------------------------------------------------------------------
# N5: dead/redundant code removal
# ---------------------------------------------------------------------------


def test_baseline_coverage_status_isolated_per_entity_via_logical_observation_id() -> None:
    # N5(b): baseline_coverage_status must key on the entity-scoped
    # logical_observation_id, not just (registry_id, track_id). Two entities
    # sharing a registry_id/period_type/track_id but only one holding a
    # matching baseline row must not leak baseline coverage across entities.
    # This pins the format assumption
    # (<entity_id>:<target_id>:<period_type>:<period_start>) the N5(b)
    # simplification relies on -- a future change to that format that drops
    # or reorders the entity prefix should fail this test.
    rows = [
        _synthetic_row(
            row_key="r-c1",
            period_start="2015-01-01",
            period_end="2015-12-31",
            predicted_value=105.0,
            actual_value=100.0,
            registry_id="synthetic:FY:revenue:isolation_v1",
            entity_id="R",
            model_id="isolation_v1",
            logical_observation_id="R:revenue:FY:2015-01-01",
        ),
        _synthetic_row(
            row_key="r-b1",
            period_start="2015-01-01",
            period_end="2015-12-31",
            predicted_value=95.0,
            actual_value=100.0,
            registry_id="synthetic:FY:revenue:isolation_v1",
            entity_id="R",
            model_id="baseline_same_period_last_year",
            is_baseline=True,
            logical_observation_id="R:revenue:FY:2015-01-01",
        ),
        _synthetic_row(
            row_key="s-c1",
            period_start="2015-01-01",
            period_end="2015-12-31",
            predicted_value=205.0,
            actual_value=200.0,
            registry_id="synthetic:FY:revenue:isolation_v1",
            entity_id="S",
            model_id="isolation_v1",
            logical_observation_id="S:revenue:FY:2015-01-01",
        ),
    ]
    frame = pd.DataFrame(rows)
    result = compute_metric_table(frame)
    per_entity = result[~result["is_baseline"] & (result["metric_grain"] == "per_entity")]

    entity_r = per_entity[per_entity["entity_id"] == "R"].iloc[0]
    assert entity_r["n_scaled"] == 1
    assert entity_r["baseline_coverage_status"] != "not_available"

    entity_s = per_entity[per_entity["entity_id"] == "S"].iloc[0]
    assert entity_s["n_scaled"] == 0
    assert entity_s["baseline_coverage_status"] == "not_available"
    assert entity_s["baseline_coverage_ratio"] == pytest.approx(0.0)


def test_compute_metric_table_scaled_rmse_uses_overlap_rows_only() -> None:
    # B1: two of four challenger observations have no matching baseline
    # observation (no prior year to form a same-period-last-year baseline).
    # scaled_rmse/skill_vs_baseline must be built from a model RMSE computed
    # on exactly the two overlapping rows, not the full four-row sample.
    rows = [
        _synthetic_row(row_key="c1", period_start="2015-01-01", period_end="2015-12-31", predicted_value=110.0, actual_value=100.0),
        _synthetic_row(row_key="c2", period_start="2016-01-01", period_end="2016-12-31", predicted_value=195.0, actual_value=200.0),
        _synthetic_row(row_key="c3", period_start="2017-01-01", period_end="2017-12-31", predicted_value=50.0, actual_value=40.0),
        _synthetic_row(row_key="c4", period_start="2018-01-01", period_end="2018-12-31", predicted_value=310.0, actual_value=300.0),
        _synthetic_row(
            row_key="b1",
            period_start="2015-01-01",
            period_end="2015-12-31",
            predicted_value=80.0,
            actual_value=100.0,
            model_id="baseline_same_period_last_year",
            is_baseline=True,
            logical_observation_id="E1:revenue:FY:2015-01-01",
        ),
        _synthetic_row(
            row_key="b2",
            period_start="2016-01-01",
            period_end="2016-12-31",
            predicted_value=150.0,
            actual_value=200.0,
            model_id="baseline_same_period_last_year",
            is_baseline=True,
            logical_observation_id="E1:revenue:FY:2016-01-01",
        ),
    ]
    frame = pd.DataFrame(rows)
    result = compute_metric_table(frame)
    challenger = result[~result["is_baseline"]].iloc[0]
    assert challenger["n_valid"] == 4
    assert challenger["baseline_n_overlap"] == 2
    assert challenger["n_scaled"] == 2
    # Full-sample RMSE stays honest and unchanged (all four rows).
    assert challenger["rmse"] == pytest.approx(math.sqrt(81.25))
    # Model RMSE restricted to the overlap rows only (c1, c2).
    assert challenger["rmse_on_overlap"] == pytest.approx(math.sqrt(62.5))
    assert challenger["baseline_rmse"] == pytest.approx(math.sqrt(1450.0))
    assert challenger["scaled_rmse"] == pytest.approx(0.207614, rel=1e-5)
    assert challenger["skill_vs_baseline"] == pytest.approx(0.792386, rel=1e-5)


def test_compute_metric_table_blocks_headline_when_baseline_coverage_is_low() -> None:
    rows = []
    for year in range(2010, 2020):
        start = f"{year}-01-01"
        end = f"{year}-12-31"
        logical_id = f"E1:revenue:FY:{start}"
        rows.append(
            _synthetic_row(
                row_key=f"c-{year}",
                period_start=start,
                period_end=end,
                predicted_value=105.0,
                actual_value=100.0,
                logical_observation_id=logical_id,
            )
        )
        if year < 2017:
            rows.append(
                _synthetic_row(
                    row_key=f"b-{year}",
                    period_start=start,
                    period_end=end,
                    predicted_value=98.0,
                    actual_value=100.0,
                    model_id="baseline_same_period_last_year",
                    is_baseline=True,
                    logical_observation_id=logical_id,
                )
            )

    result = compute_metric_table(pd.DataFrame(rows))
    challenger = result[(~result["is_baseline"]) & (result["metric_grain"] == "per_entity")].iloc[0]
    assert challenger["n_valid"] == 10
    assert challenger["baseline_n_overlap"] == 7
    assert challenger["baseline_coverage_ratio"] == pytest.approx(0.7)
    assert challenger["baseline_coverage_status"] == "insufficient_coverage"
    assert challenger["metric_status"] == "insufficient_baseline_coverage"
    assert bool(challenger["headline_eligible"]) is False


def test_compute_metric_table_headline_guard_requires_distinct_periods() -> None:
    # B2: 12 rows from pooling 4 entities across only 3 distinct fiscal
    # years clears n_valid >= 10 but must NOT clear the headline guard,
    # because the effective independent sample is 3 periods, not 12 rows.
    pooled_rows = [
        _synthetic_row(
            row_key=f"pooled-{entity}-{year}",
            period_start=f"{year}-01-01",
            period_end=f"{year}-12-31",
            predicted_value=105.0,
            actual_value=100.0,
            registry_id="synthetic:FY:revenue:pooled_v1",
            entity_id=entity,
            model_id="pooled_v1",
        )
        for entity in ("A", "B", "C", "D")
        for year in (2020, 2021, 2022)
    ]
    # Contrast: a single entity observed across 10 distinct fiscal years
    # has a genuinely independent sample and should clear the guard.
    sufficient_rows = [
        _synthetic_row(
            row_key=f"suff-{year}",
            period_start=f"{year}-01-01",
            period_end=f"{year}-12-31",
            predicted_value=105.0,
            actual_value=100.0,
            registry_id="synthetic:FY:revenue:sufficient_v1",
            entity_id="E1",
            model_id="sufficient_v1",
        )
        for year in range(2010, 2020)
    ]
    frame = pd.DataFrame(pooled_rows + sufficient_rows)
    result = compute_metric_table(frame)
    pooled = result[
        (result["registry_id"] == "synthetic:FY:revenue:pooled_v1") & (result["metric_grain"] == "pooled")
    ].iloc[0]
    assert pooled["n_valid"] == 12
    assert pooled["n_distinct_periods"] == 3
    assert pooled["n_distinct_entities"] == 4
    assert pooled["metric_status"] == "insufficient_sample"
    assert bool(pooled["headline_eligible"]) is False

    # B3: the "sufficient" fixture is single-entity, so its pooled row is
    # identical in content to its per_entity row -- but headline_eligible is
    # hard-forced off at pooled grain regardless of status, so only the
    # per_entity row may report True.
    sufficient_pooled = result[
        (result["registry_id"] == "synthetic:FY:revenue:sufficient_v1") & (result["metric_grain"] == "pooled")
    ].iloc[0]
    assert sufficient_pooled["n_valid"] == 10
    assert sufficient_pooled["n_distinct_periods"] == 10
    assert sufficient_pooled["metric_status"] == "valid_headline"
    assert bool(sufficient_pooled["headline_eligible"]) is False

    sufficient = result[
        (result["registry_id"] == "synthetic:FY:revenue:sufficient_v1") & (result["metric_grain"] == "per_entity")
    ].iloc[0]
    assert sufficient["n_valid"] == 10
    assert sufficient["n_distinct_periods"] == 10
    assert sufficient["metric_status"] == "valid_headline"
    assert bool(sufficient["headline_eligible"]) is True


def test_compute_metric_table_directional_guard_requires_distinct_periods() -> None:
    # B2: 16 directional observations (4 entities x 4 periods) clears
    # n_directional >= 12 (FY guard) but only spans 4 distinct periods, so
    # the directional guard must still report insufficient_sample.
    period_specs = [
        ("2020-01-01", "2020-12-31", 90.0, 100.0, 110.0),
        ("2021-01-01", "2021-12-31", 210.0, 200.0, 190.0),
        ("2022-01-01", "2022-12-31", 290.0, 300.0, 280.0),
        ("2023-01-01", "2023-12-31", 390.0, 380.0, 400.0),
    ]
    rows = []
    for entity in ("A", "B", "C", "D"):
        for start, end, baseline_value, actual_value, predicted_value in period_specs:
            obs_id = f"{entity}:revenue:FY:{start}"
            rows.append(
                _synthetic_row(
                    row_key=f"c-{entity}-{start}",
                    period_start=start,
                    period_end=end,
                    predicted_value=predicted_value,
                    actual_value=actual_value,
                    registry_id="synthetic:FY:revenue:directional_pooled_v1",
                    entity_id=entity,
                    model_id="directional_pooled_v1",
                    logical_observation_id=obs_id,
                )
            )
            rows.append(
                _synthetic_row(
                    row_key=f"b-{entity}-{start}",
                    period_start=start,
                    period_end=end,
                    predicted_value=baseline_value,
                    actual_value=actual_value,
                    registry_id="synthetic:FY:revenue:directional_pooled_v1",
                    entity_id=entity,
                    model_id="baseline_same_period_last_year",
                    is_baseline=True,
                    logical_observation_id=obs_id,
                )
            )
    frame = pd.DataFrame(rows)
    result = compute_metric_table(frame)
    challenger = result[~result["is_baseline"]].iloc[0]
    assert challenger["n_directional"] == 16
    assert challenger["n_distinct_periods"] == 4
    assert challenger["directional_hit_rate"] == pytest.approx(0.5)
    assert challenger["directional_degeneracy"] == "none"
    assert challenger["directional_hit_rate_status"] == "insufficient_sample"


def test_compute_metric_table_flags_degenerate_directional_hit_rates() -> None:
    # B4: a perfect (or perfectly-inverted, or single-direction-actual)
    # directional hit rate must be flagged as degenerate rather than read
    # as skill; a genuinely mixed result must not be flagged.
    def _direction_group(registry_id: str, model_id: str, specs: list[tuple[str, str, float, float, float]]) -> list[dict]:
        group_rows = []
        for start, end, baseline_value, actual_value, predicted_value in specs:
            obs_id = f"E1:revenue:FY:{start}"
            group_rows.append(
                _synthetic_row(
                    row_key=f"{model_id}-c-{start}",
                    period_start=start,
                    period_end=end,
                    predicted_value=predicted_value,
                    actual_value=actual_value,
                    registry_id=registry_id,
                    entity_id="E1",
                    model_id=model_id,
                    logical_observation_id=obs_id,
                )
            )
            group_rows.append(
                _synthetic_row(
                    row_key=f"{model_id}-b-{start}",
                    period_start=start,
                    period_end=end,
                    predicted_value=baseline_value,
                    actual_value=actual_value,
                    registry_id=registry_id,
                    entity_id="E1",
                    model_id="baseline_same_period_last_year",
                    is_baseline=True,
                    logical_observation_id=obs_id,
                )
            )
        return group_rows

    all_correct_specs = [
        ("2015-01-01", "2015-12-31", 90.0, 100.0, 110.0),
        ("2016-01-01", "2016-12-31", 210.0, 200.0, 190.0),
        ("2017-01-01", "2017-12-31", 290.0, 300.0, 310.0),
    ]
    all_incorrect_specs = [
        ("2015-01-01", "2015-12-31", 90.0, 100.0, 80.0),
        ("2016-01-01", "2016-12-31", 210.0, 200.0, 220.0),
        ("2017-01-01", "2017-12-31", 290.0, 300.0, 280.0),
    ]
    single_direction_actual_specs = [
        ("2015-01-01", "2015-12-31", 90.0, 100.0, 110.0),
        ("2016-01-01", "2016-12-31", 190.0, 200.0, 180.0),
        ("2017-01-01", "2017-12-31", 290.0, 300.0, 310.0),
    ]
    informative_specs = [
        ("2015-01-01", "2015-12-31", 90.0, 100.0, 110.0),
        ("2016-01-01", "2016-12-31", 210.0, 200.0, 190.0),
        ("2017-01-01", "2017-12-31", 290.0, 300.0, 280.0),
    ]
    rows = (
        _direction_group("synthetic:FY:revenue:all_correct_v1", "all_correct_v1", all_correct_specs)
        + _direction_group("synthetic:FY:revenue:all_incorrect_v1", "all_incorrect_v1", all_incorrect_specs)
        + _direction_group("synthetic:FY:revenue:single_dir_v1", "single_dir_v1", single_direction_actual_specs)
        + _direction_group("synthetic:FY:revenue:informative_v1", "informative_v1", informative_specs)
    )
    frame = pd.DataFrame(rows)
    result = compute_metric_table(frame)
    challengers = result[~result["is_baseline"]]

    all_correct = challengers[challengers["registry_id"] == "synthetic:FY:revenue:all_correct_v1"].iloc[0]
    assert all_correct["directional_hit_rate"] == pytest.approx(1.0)
    assert all_correct["directional_degeneracy"] == "all_correct"
    assert all_correct["directional_hit_rate_status"] == "degenerate"

    all_incorrect = challengers[challengers["registry_id"] == "synthetic:FY:revenue:all_incorrect_v1"].iloc[0]
    assert all_incorrect["directional_hit_rate"] == pytest.approx(0.0)
    assert all_incorrect["directional_degeneracy"] == "all_incorrect"
    assert all_incorrect["directional_hit_rate_status"] == "degenerate"

    single_dir = challengers[challengers["registry_id"] == "synthetic:FY:revenue:single_dir_v1"].iloc[0]
    assert single_dir["directional_hit_rate"] == pytest.approx(2 / 3)
    assert single_dir["directional_degeneracy"] == "single_direction_actual"
    assert single_dir["directional_hit_rate_status"] == "degenerate"

    informative = challengers[challengers["registry_id"] == "synthetic:FY:revenue:informative_v1"].iloc[0]
    assert informative["directional_hit_rate"] == pytest.approx(2 / 3)
    assert informative["directional_degeneracy"] == "none"
    # Not flagged degenerate: mixed hits and mixed actual directions, same
    # shape as the real operating_cost/attributable_profit contracts which
    # must never be flagged despite an imperfect hit rate.
    assert informative["directional_hit_rate_status"] != "degenerate"


def test_metrics_manifest_records_status_counts() -> None:
    # B2 fix: no contract currently has enough distinct target periods to
    # clear the headline guard, so "valid_headline" no longer appears in the
    # status counts. This assertion is deliberately updated from asserting
    # counts["valid_headline"] >= 16.
    # B3 fix: per-entity rows roughly double the diagnostic_only count (12
    # pooled SHKP contract-activity rows -> 24 once their per-entity mirror
    # rows, one per single-entity contract, are added).
    build_metrics()
    manifest = json.load(open(_REGISTRY_DIR / "asia_backtest_metrics_manifest.json"))
    counts = manifest["metric_status_counts"]
    assert "valid_headline" not in counts
    assert counts["insufficient_sample"] >= 16
    assert counts["diagnostic_only"] == 24
    assert manifest["headline_contracts"] == 0
    assert manifest["interval_rows"] > 0
    assert len(manifest["input_bundle_ids"]) == 1


# ---------------------------------------------------------------------------
# B3: per-entity grain
# ---------------------------------------------------------------------------


def test_per_entity_rmse_differs_from_pooled_and_matches_hand_computed_value() -> None:
    # Entity A has small, tight errors; entity B has large errors on a much
    # bigger scale. Pooling them (the pre-B3 behaviour) lets B's scale
    # dominate the aggregate RMSE and hides A's genuinely different accuracy.
    rows = [
        _synthetic_row(row_key="a1", period_start="2020-01-01", period_end="2020-12-31", predicted_value=110.0, actual_value=100.0, entity_id="A"),
        _synthetic_row(row_key="a2", period_start="2021-01-01", period_end="2021-12-31", predicted_value=190.0, actual_value=200.0, entity_id="A"),
        _synthetic_row(row_key="a3", period_start="2022-01-01", period_end="2022-12-31", predicted_value=310.0, actual_value=300.0, entity_id="A"),
        _synthetic_row(row_key="b1", period_start="2020-01-01", period_end="2020-12-31", predicted_value=1300.0, actual_value=1000.0, entity_id="B"),
        _synthetic_row(row_key="b2", period_start="2021-01-01", period_end="2021-12-31", predicted_value=1700.0, actual_value=2000.0, entity_id="B"),
        _synthetic_row(row_key="b3", period_start="2022-01-01", period_end="2022-12-31", predicted_value=3600.0, actual_value=3000.0, entity_id="B"),
    ]
    frame = pd.DataFrame(rows)
    result = compute_metric_table(frame)
    challengers = result[~result["is_baseline"]]

    pooled = challengers[challengers["metric_grain"] == "pooled"].iloc[0]
    assert pooled["n_valid"] == 6
    assert pooled["n_distinct_entities"] == 2
    assert pooled["rmse"] == pytest.approx(math.sqrt(90050.0))

    entity_a = challengers[(challengers["metric_grain"] == "per_entity") & (challengers["entity_id"] == "A")].iloc[0]
    entity_b = challengers[(challengers["metric_grain"] == "per_entity") & (challengers["entity_id"] == "B")].iloc[0]
    assert entity_a["n_distinct_entities"] == 1
    assert entity_b["n_distinct_entities"] == 1
    assert entity_a["rmse"] == pytest.approx(10.0)
    assert entity_b["rmse"] == pytest.approx(math.sqrt(180000.0))
    # Neither entity's RMSE equals the pooled figure -- the pooled number
    # was masking both a much better (A) and a much worse (B) result.
    assert entity_a["rmse"] != pytest.approx(pooled["rmse"])
    assert entity_b["rmse"] != pytest.approx(pooled["rmse"])


def test_per_entity_scaled_rmse_uses_only_that_entitys_overlap_rows() -> None:
    # Entity P has a same-period-last-year baseline for both of its
    # observations; entity Q has a baseline for only one of its two, which
    # is below MIN_SCALER_OVERLAP (2) and so must resolve to NaN rather than
    # borrowing P's overlap rows. This is the 106/211 partial-baseline-
    # coverage case called out in the B3 spec, made explicit and minimal.
    rows = [
        _synthetic_row(row_key="p-c1", period_start="2015-01-01", period_end="2015-12-31", predicted_value=205.0, actual_value=200.0, entity_id="P", logical_observation_id="P:revenue:FY:2015-01-01"),
        _synthetic_row(row_key="p-c2", period_start="2016-01-01", period_end="2016-12-31", predicted_value=310.0, actual_value=300.0, entity_id="P", logical_observation_id="P:revenue:FY:2016-01-01"),
        _synthetic_row(row_key="p-b1", period_start="2015-01-01", period_end="2015-12-31", predicted_value=190.0, actual_value=200.0, entity_id="P", model_id="baseline_same_period_last_year", is_baseline=True, logical_observation_id="P:revenue:FY:2015-01-01"),
        _synthetic_row(row_key="p-b2", period_start="2016-01-01", period_end="2016-12-31", predicted_value=280.0, actual_value=300.0, entity_id="P", model_id="baseline_same_period_last_year", is_baseline=True, logical_observation_id="P:revenue:FY:2016-01-01"),
        _synthetic_row(row_key="q-c1", period_start="2015-01-01", period_end="2015-12-31", predicted_value=55.0, actual_value=50.0, entity_id="Q", logical_observation_id="Q:revenue:FY:2015-01-01"),
        _synthetic_row(row_key="q-c2", period_start="2016-01-01", period_end="2016-12-31", predicted_value=65.0, actual_value=60.0, entity_id="Q", logical_observation_id="Q:revenue:FY:2016-01-01"),
        _synthetic_row(row_key="q-b1", period_start="2015-01-01", period_end="2015-12-31", predicted_value=40.0, actual_value=50.0, entity_id="Q", model_id="baseline_same_period_last_year", is_baseline=True, logical_observation_id="Q:revenue:FY:2015-01-01"),
    ]
    frame = pd.DataFrame(rows)
    result = compute_metric_table(frame)
    challengers = result[~result["is_baseline"] & (result["metric_grain"] == "per_entity")]

    entity_p = challengers[challengers["entity_id"] == "P"].iloc[0]
    assert entity_p["n_scaled"] == 2
    assert entity_p["baseline_n_overlap"] == 2
    assert entity_p["rmse_on_overlap"] == pytest.approx(math.sqrt((5.0**2 + 10.0**2) / 2))
    assert entity_p["baseline_rmse"] == pytest.approx(math.sqrt((10.0**2 + 20.0**2) / 2))
    assert entity_p["scaled_rmse"] == pytest.approx(entity_p["rmse_on_overlap"] / entity_p["baseline_rmse"])
    assert not pd.isna(entity_p["scaled_rmse"])

    entity_q = challengers[challengers["entity_id"] == "Q"].iloc[0]
    # Only one baseline observation exists for Q (2016 has no prior-year
    # baseline row at all), so n_scaled == 1 < MIN_SCALER_OVERLAP and
    # scaled_rmse/baseline_rmse must be null -- and, crucially, must not
    # have picked up P's overlap rows to reach 2.
    assert entity_q["n_scaled"] == 1
    assert entity_q["baseline_n_overlap"] == 1
    assert pd.isna(entity_q["baseline_rmse"])
    assert pd.isna(entity_q["scaled_rmse"])

    # The pooled row combines both entities' overlap rows (2 + 1 = 3); it is
    # shown here only to prove per-entity did NOT just slice this number.
    pooled = result[~result["is_baseline"] & (result["metric_grain"] == "pooled")].iloc[0]
    assert pooled["n_scaled"] == 3


def test_pooled_rows_never_headline_eligible_even_with_large_sample() -> None:
    # Three entities, each observed across 10 distinct fiscal years with
    # clean headline-grade rows: at pooled grain this clears every guard
    # (n_valid=30, n_distinct_periods=10, all headline-grade) that would
    # otherwise mark it valid_headline. headline_eligible must still be
    # hard-forced to False for the pooled row -- only the per-entity rows
    # may be headline eligible.
    rows = [
        _synthetic_row(
            row_key=f"{entity}-{year}",
            period_start=f"{year}-01-01",
            period_end=f"{year}-12-31",
            predicted_value=105.0,
            actual_value=100.0,
            registry_id="synthetic:FY:revenue:large_pooled_v1",
            entity_id=entity,
            model_id="large_pooled_v1",
        )
        for entity in ("X", "Y", "Z")
        for year in range(2010, 2020)
    ]
    frame = pd.DataFrame(rows)
    result = compute_metric_table(frame)
    challengers = result[~result["is_baseline"]]

    pooled = challengers[challengers["metric_grain"] == "pooled"].iloc[0]
    assert pooled["n_valid"] == 30
    assert pooled["n_distinct_periods"] == 10
    assert pooled["metric_status"] == "valid_headline"
    assert bool(pooled["headline_eligible"]) is False

    per_entity = challengers[challengers["metric_grain"] == "per_entity"]
    assert len(per_entity) == 3
    assert (per_entity["n_distinct_entities"] == 1).all()
    assert (per_entity["metric_status"] == "valid_headline").all()
    assert per_entity["headline_eligible"].all()


def test_n_distinct_entities_is_one_on_every_per_entity_row() -> None:
    metrics = _metrics()
    per_entity = metrics[metrics["metric_grain"] == "per_entity"]
    assert len(per_entity) > 0
    assert (per_entity["n_distinct_entities"] == 1).all()


def test_unit_canonicalization_maps_all_four_spellings() -> None:
    assert canonicalize_unit("HK$m") == "HKD_mn"
    assert canonicalize_unit("HKD m") == "HKD_mn"
    assert canonicalize_unit("HKD") == "HKD"
    assert canonicalize_unit("RMB mn") == "RMB_mn"
    # HK$m and HKD m are the same unit spelled two ways; HKD is genuinely
    # 1e6 different (raw dollars, not millions) and must not collapse into
    # the same canonical bucket as the other two.
    assert canonicalize_unit("HK$m") == canonicalize_unit("HKD m")
    assert canonicalize_unit("HKD") != canonicalize_unit("HK$m")


def test_metric_table_populates_unit_canonical_per_row() -> None:
    rows = [
        _synthetic_row(row_key="u1", period_start="2020-01-01", period_end="2020-12-31", predicted_value=10.0, actual_value=9.0, unit="HK$m"),
        _synthetic_row(row_key="u2", period_start="2020-01-01", period_end="2020-12-31", predicted_value=10.0, actual_value=9.0, entity_id="E2", registry_id="synthetic:FY:revenue:other_unit_v1", model_id="other_unit_v1", unit="HKD"),
    ]
    frame = pd.DataFrame(rows)
    result = compute_metric_table(frame)
    assert (result.loc[result["unit"] == "HK$m", "unit_canonical"] == "HKD_mn").all()
    assert (result.loc[result["unit"] == "HKD", "unit_canonical"] == "HKD").all()
