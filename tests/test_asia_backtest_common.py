"""Tests for the shared backtest contract (src/common/backtest/)."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from src.common.backtest import (
    BacktestRunSpec,
    EVALUABLE_STATUSES,
    EvaluationStatus,
    PIT_GRADES,
    PitGrade,
    RunArtifactStore,
    TRACK_IDS,
    dataframe_fingerprint,
    file_fingerprint,
    compute_metric_table,
)
from src.common.backtest.metrics import METRIC_POLICY_VERSION
from src.common.backtest.schema import LONG_FORM_COLUMNS, empty_long_form, validate_long_form
from src.common.backtest.pivot import contract_summary, contract_table
from src.common.backtest.storage import canonical_json
from src.common.backtest.vocabulary import (
    BASELINE_MODEL_ID,
    MIN_DIRECTIONAL_HIT_RATE_ROWS,
    MIN_HEADLINE_ROWS,
    is_evaluable_status,
    is_headline_grade,
)


def _long_form_row(
    *,
    row_key: str,
    registry_id: str = "mtr:FY:transport_operations_revenue:mtr_physics_yield_v1",
    entity_id: str = "MTR",
    target_id: str = "transport_operations_revenue",
    period_start: str = "2025-01-01",
    period_end: str = "2025-12-31",
    period_type: str = "FY",
    track_id: str = "fiscal_year",
    model_id: str = "mtr_physics_yield_v1",
    is_baseline: bool = False,
    evaluation_status: str = "valid_forward_oos",
    pit_grade: str = "B_practical_pit",
    predicted_value: float | None = None,
    actual_value: float | None = None,
    has_prediction: bool | None = None,
    has_actual: bool | None = None,
    unit: str = "HK$m",
    is_primary_source: bool = True,
) -> dict:
    if has_prediction is None:
        has_prediction = predicted_value is not None
    if has_actual is None:
        has_actual = actual_value is not None
    row = {
        "engine_version": "asia_backtest_engine_v1",
        "registry_id": registry_id,
        "row_key": row_key,
        "logical_observation_id": f"{entity_id}:{target_id}:{period_type}:{period_start}",
        "dedup_group_id": f"{entity_id}:{target_id}:{period_type}:{period_start}:{model_id}",
        "dedup_rank": 1,
        "is_primary_source": is_primary_source,
        "source_dataset": "mtr_farebox_revenue_annual_backtest",
        "source_run_id": "",
        "input_bundle_id": "test-bundle",
        "source_row_index": 0,
        "source_row_fingerprint": "test-source-row",
        "natural_observation_key": f"{entity_id}:{target_id}:{period_type}:{period_start}:{model_id}",
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
        "unit": unit,
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
    return row


def test_vocabulary_contains_the_contract_statuses() -> None:
    assert "valid_forward_oos" in EVALUABLE_STATUSES
    assert "valid_practical_oos" in EVALUABLE_STATUSES
    assert "diagnostic_only" not in EVALUABLE_STATUSES
    assert "no_source_coverage" not in EVALUABLE_STATUSES
    assert "A_strict_pit" in PIT_GRADES
    assert "D_diagnostic_only" in PIT_GRADES
    assert set(TRACK_IDS) == {"fiscal_year", "half_year_non_overlapping", "ytd_current", "monthly_sparse"}
    assert MIN_HEADLINE_ROWS["month"] == 24
    assert MIN_DIRECTIONAL_HIT_RATE_ROWS["FY"] == 12
    assert is_evaluable_status("valid_oos")
    assert not is_evaluable_status("structural_calibration")
    assert is_headline_grade("A_strict_pit")
    assert not is_headline_grade("C_structural_replay")
    assert BASELINE_MODEL_ID == "baseline_same_period_last_year"
    assert METRIC_POLICY_VERSION == "asia_backtest_metrics_v2"


def test_status_literals_are_consistent() -> None:
    for name in ("valid_oos", "valid_practical_oos", "valid_forward_oos", "forecast_only"):
        assert name in EvaluationStatus.__args__
    for name in ("A_strict_pit", "B_practical_pit", "C_structural_replay", "D_diagnostic_only"):
        assert name in PitGrade.__args__


def test_run_id_is_deterministic_and_content_addressed() -> None:
    spec_a = BacktestRunSpec(
        engine_version="asia_backtest_engine_v1",
        config={"mode": "emitter"},
        input_fingerprints={"registry": "abc123"},
        parent_run_ids=("run-1",),
    )
    spec_b = BacktestRunSpec(
        engine_version="asia_backtest_engine_v1",
        config={"mode": "emitter"},
        input_fingerprints={"registry": "abc123"},
        parent_run_ids=("run-1",),
    )
    spec_c = BacktestRunSpec(
        engine_version="asia_backtest_engine_v1",
        config={"mode": "emitter"},
        input_fingerprints={"registry": "abc124"},
        parent_run_ids=("run-1",),
    )
    assert spec_a.run_id == spec_b.run_id
    assert spec_a.run_id != spec_c.run_id
    assert spec_a.run_id.startswith("asia_backtest_engine_v1-")


def test_fingerprints_are_stable_and_sensitive(tmp_path) -> None:
    frame = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
    assert dataframe_fingerprint(frame) == dataframe_fingerprint(frame.copy())
    changed = frame.copy()
    changed.loc[0, "a"] = 99
    assert dataframe_fingerprint(frame) != dataframe_fingerprint(changed)
    shuffled = frame.iloc[::-1].reset_index(drop=True)
    assert dataframe_fingerprint(frame) == dataframe_fingerprint(shuffled)

    path = tmp_path / "input.csv"
    path.write_text("a,b\n1,x\n2,y\n", encoding="utf-8")
    digest = file_fingerprint(path)
    path.write_text("a,b\n1,x\n3,y\n", encoding="utf-8")
    assert file_fingerprint(path) != digest
    assert len(digest) == 64


def test_run_artifact_store_writes_manifest_and_pointer(tmp_path) -> None:
    spec = BacktestRunSpec(
        engine_version="asia_backtest_engine_v1",
        config={"mode": "test"},
        input_fingerprints={"input": "deadbeef"},
    )
    store = RunArtifactStore(tmp_path / "runs", spec)
    frame = pd.DataFrame({"x": [1.0, 2.0]})
    data_path = store.write_dataframe("long_form", frame)
    parquet_path = store.write_parquet("long_form", frame)
    assert data_path.exists()
    assert parquet_path.exists()
    written = pd.read_csv(data_path)
    assert written["x"].tolist() == [1.0, 2.0]

    manifest_path = store.write_manifest(
        artifacts={"long_form": data_path, "long_form_parquet": parquet_path},
        counts={"rows": 2},
        caveats=["test caveat"],
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["run_id"] == spec.run_id
    assert manifest["model_calculation_changed"] is False
    assert manifest["wide_tables_replaced"] is False
    assert manifest["input_fingerprints"] == {"input": "deadbeef"}
    assert manifest["artifacts"]["long_form"]["sha256"]
    assert manifest["runtime"]["pyarrow"] != "unavailable"

    pointer = store.write_latest_pointer(manifest_path)
    assert pointer.exists()
    pointer_payload = json.loads(pointer.read_text(encoding="utf-8"))
    assert pointer_payload["run_id"] == spec.run_id

    # A deterministic rerun is a no-op; a changed artifact cannot silently
    # overwrite an immutable run directory.
    assert store.write_dataframe("long_form", frame) == data_path
    with pytest.raises(FileExistsError, match="immutable run artifact"):
        store.write_dataframe("long_form", pd.DataFrame({"x": [999.0]}))


def test_run_artifact_store_rejects_non_ready_latest_pointer(tmp_path) -> None:
    spec = BacktestRunSpec(
        engine_version="asia_backtest_engine_v1",
        config={"mode": "failed"},
        input_fingerprints={"input": "deadbeef"},
    )
    store = RunArtifactStore(tmp_path / "runs", spec)
    data_path = store.write_dataframe("long_form", pd.DataFrame({"x": [1.0]}))
    manifest_path = store.write_manifest(
        artifacts={"long_form": data_path},
        counts={"rows": 1},
        caveats=["failed"],
        status="reconciliation_failed",
    )
    with pytest.raises(ValueError, match="non-ready run"):
        store.write_latest_pointer(manifest_path)


def test_run_artifact_store_json_is_immutable(tmp_path) -> None:
    spec = BacktestRunSpec(
        engine_version="asia_backtest_engine_v1",
        config={"mode": "json"},
        input_fingerprints={"input": "deadbeef"},
    )
    store = RunArtifactStore(tmp_path / "runs", spec)
    path = store.write_json("metadata", {"value": 1})
    assert store.write_json("metadata", {"value": 1}) == path
    with pytest.raises(FileExistsError, match="immutable run artifact"):
        store.write_json("metadata", {"value": 2})


def test_canonical_json_is_deterministic() -> None:
    payload = {"b": [3, 1], "a": {"nested": True}}
    assert canonical_json(payload) == canonical_json({"a": {"nested": True}, "b": [3, 1]})


def test_schema_validation_rejects_missing_columns_and_bad_periods() -> None:
    frame = empty_long_form()
    assert list(frame.columns) == list(LONG_FORM_COLUMNS)
    with pytest.raises(ValueError, match="missing columns"):
        validate_long_form(frame.drop(columns=["unit"]))

    valid = pd.DataFrame([_long_form_row(row_key="r1")])
    validate_long_form(valid)

    duplicate = pd.concat([valid, valid], ignore_index=True)
    with pytest.raises(ValueError, match="row_key must be unique"):
        validate_long_form(duplicate)

    bad_period = valid.copy()
    bad_period["target_period_type"] = "quarter"
    with pytest.raises(ValueError, match="Unsupported target period types"):
        validate_long_form(bad_period)

    bad_bounds = valid.copy()
    bad_bounds["target_period_end"] = "2024-12-31"
    with pytest.raises(ValueError, match="invalid target period bounds"):
        validate_long_form(bad_bounds)


def _metric_frame() -> pd.DataFrame:
    rows = [
        # Challenger: two forward-OOS observations, both beating the baseline.
        _long_form_row(row_key="c1", predicted_value=101.0, actual_value=100.0),
        _long_form_row(
            row_key="c2",
            period_start="2024-01-01",
            period_end="2024-12-31",
            predicted_value=190.0,
            actual_value=200.0,
        ),
        # Duplicate row: must be excluded from metrics.
        _long_form_row(row_key="dup", predicted_value=999.0, actual_value=100.0, is_primary_source=False),
        # Structural row: evaluable-status filter must exclude it.
        _long_form_row(
            row_key="struct",
            predicted_value=500.0,
            actual_value=100.0,
            evaluation_status="structural_calibration",
            pit_grade="C_structural_replay",
        ),
        # Baseline rows for the same observations.
        _long_form_row(
            row_key="b1",
            model_id="baseline_same_period_last_year",
            is_baseline=True,
            predicted_value=95.0,
            actual_value=100.0,
        ),
        _long_form_row(
            row_key="b2",
            model_id="baseline_same_period_last_year",
            is_baseline=True,
            period_start="2024-01-01",
            period_end="2024-12-31",
            predicted_value=210.0,
            actual_value=200.0,
        ),
    ]
    # Fix the second observation's logical id after the fact.
    frame = pd.DataFrame(rows)
    frame.loc[frame["row_key"] == "c2", "logical_observation_id"] = "MTR:transport_operations_revenue:FY:2024-01-01"
    frame.loc[frame["row_key"] == "b2", "logical_observation_id"] = "MTR:transport_operations_revenue:FY:2024-01-01"
    frame.loc[frame["row_key"] == "dup", "logical_observation_id"] = "MTR:transport_operations_revenue:FY:2025-01-01"
    frame.loc[frame["row_key"] == "struct", "logical_observation_id"] = "MTR:transport_operations_revenue:FY:2025-01-01"
    return frame


def test_compute_metric_table_uses_only_primary_evaluable_rows() -> None:
    # B3: every group now emits a pooled row plus one per-entity row; this
    # fixture is single-entity, so pooled and per_entity are identical in
    # content (2 groups x 2 grains = 4 rows), and grain is filtered to
    # "pooled" to keep this test's intent (the same aggregate as before B3).
    frame = _metric_frame()
    result = compute_metric_table(frame)
    assert len(result) == 4  # (challenger + baseline) x (pooled + per_entity)
    pooled_result = result[result["metric_grain"] == "pooled"]
    assert len(pooled_result) == 2
    challenger = pooled_result[~pooled_result["is_baseline"]].iloc[0]
    baseline = pooled_result[pooled_result["is_baseline"]].iloc[0]
    # Structural rows never enter the accuracy table at all.
    assert challenger["n_valid"] == 2
    assert challenger["n_headline_valid"] == 2
    assert challenger["metric_scope"] == "headline_candidate"
    assert challenger["mae"] == pytest.approx(5.5)
    assert challenger["metric_status"] == "insufficient_sample"  # n=2 < 10 FY
    assert bool(challenger["headline_eligible"]) is False
    assert challenger["baseline_n_overlap"] == 2
    assert challenger["scaled_rmse"] > 0
    assert challenger["skill_vs_baseline"] > 0
    assert baseline["model_id"] == "baseline_same_period_last_year"


def test_compute_metric_table_directional_hit_rate_is_vs_baseline() -> None:
    rows = []
    # Three observations: model predicts direction correctly twice.
    for index, (actual, predicted, baseline_value) in enumerate(
        [(100.0, 110.0, 90.0), (200.0, 190.0, 210.0), (300.0, 280.0, 290.0)]
    ):
        start = f"20{15 + index}-01-01"
        rows.append(
            _long_form_row(
                row_key=f"c{index}",
                period_start=start,
                period_end=f"20{15 + index}-12-31",
                predicted_value=predicted,
                actual_value=actual,
            )
        )
        rows.append(
            _long_form_row(
                row_key=f"b{index}",
                model_id="baseline_same_period_last_year",
                is_baseline=True,
                period_start=start,
                period_end=f"20{15 + index}-12-31",
                predicted_value=baseline_value,
                actual_value=actual,
            )
        )
    frame = pd.DataFrame(rows)
    frame["logical_observation_id"] = [
        f"MTR:transport_operations_revenue:FY:{start}" for start in frame["target_period_start"]
    ]
    result = compute_metric_table(frame)
    challenger = result[~result["is_baseline"]].iloc[0]
    # vs baseline directions: (110>90 & 100>90)=hit; (190<210 & 200<210)=hit; (280<290 & 300>290)=miss.
    assert challenger["directional_hit_rate"] == pytest.approx(2 / 3)
    assert challenger["n_directional"] == 3


def test_compute_metric_table_headline_only_when_sample_sufficient() -> None:
    rows = []
    baseline_values = [90.0 + index for index in range(10)]
    actuals = [100.0 + index for index in range(10)]
    predictions = [value + 5.0 for value in actuals]
    for index in range(10):
        start = f"20{15 + index}-01-01"
        rows.append(
            _long_form_row(
                row_key=f"c{index}",
                period_start=start,
                period_end=f"20{15 + index}-12-31",
                predicted_value=predictions[index],
                actual_value=actuals[index],
            )
        )
        rows.append(
            _long_form_row(
                row_key=f"b{index}",
                model_id="baseline_same_period_last_year",
                is_baseline=True,
                period_start=start,
                period_end=f"20{15 + index}-12-31",
                predicted_value=baseline_values[index],
                actual_value=actuals[index],
            )
        )
    frame = pd.DataFrame(rows)
    frame["logical_observation_id"] = [
        f"MTR:transport_operations_revenue:FY:{start}" for start in frame["target_period_start"]
    ]
    result = compute_metric_table(frame)
    # B3: this fixture is single-entity, so pooled and per_entity share the
    # same status/mae -- but only per_entity may report headline_eligible.
    pooled_challenger = result[(result["metric_grain"] == "pooled") & ~result["is_baseline"]].iloc[0]
    assert pooled_challenger["n_valid"] == 10
    assert pooled_challenger["metric_status"] == "valid_headline"
    assert bool(pooled_challenger["headline_eligible"]) is False
    assert pooled_challenger["mae"] == pytest.approx(5.0)

    challenger = result[(result["metric_grain"] == "per_entity") & ~result["is_baseline"]].iloc[0]
    assert challenger["n_valid"] == 10
    assert challenger["metric_status"] == "valid_headline"
    assert bool(challenger["headline_eligible"]) is True
    assert challenger["mae"] == pytest.approx(5.0)
    assert challenger["baseline_coverage_ratio"] == pytest.approx(1.0)
    assert challenger["baseline_coverage_status"] == "complete"


def test_compute_metric_table_reports_diagnostic_scope() -> None:
    row = _long_form_row(
        row_key="d1",
        registry_id="shkp:month:contract_activity_proxy:trailing_mean_lb3_base",
        entity_id="SHKP",
        target_id="contract_activity_proxy",
        period_type="month",
        period_start="2025-01-01",
        period_end="2025-01-31",
        track_id="monthly_sparse",
        evaluation_status="diagnostic_only",
        pit_grade="D_diagnostic_only",
        predicted_value=100.0,
        actual_value=90.0,
        unit="HKD",
    )
    result = compute_metric_table(pd.DataFrame([row]))
    # B3: single-entity input still yields both a pooled and a per_entity
    # row (they are identical in content here since there is one entity).
    assert len(result) == 2
    assert (result["metric_scope"] == "diagnostic_only").all()
    assert (result["metric_status"] == "diagnostic_only").all()
    assert not result["headline_eligible"].any()
    assert set(result["metric_grain"]) == {"pooled", "per_entity"}


def test_contract_table_returns_primary_evaluated_rows_only() -> None:
    rows = [
        _long_form_row(
            row_key=f"c{i}",
            period_start=f"20{15 + i}-01-01",
            period_end=f"20{15 + i}-12-31",
            predicted_value=100.0 + i,
            actual_value=95.0 + i,
        )
        for i in range(3)
    ]
    rows.append(_long_form_row(row_key="dup", predicted_value=1.0, actual_value=1.0, is_primary_source=False))
    frame = pd.DataFrame(rows)
    table = contract_table(frame, "mtr:FY:transport_operations_revenue:mtr_physics_yield_v1")
    assert len(table) == 3
    assert (table["is_baseline"] == False).all()  # noqa: E712
    assert table["abs_error"].tolist() == [5.0, 5.0, 5.0]
    assert table["abs_pct_error"].iloc[0] == pytest.approx(5.0 / 95.0 * 100.0)


def test_contract_table_excludes_structural_replay_and_guards_zero_actual() -> None:
    rows = [
        _long_form_row(row_key="valid", predicted_value=10.0, actual_value=0.0),
        _long_form_row(
            row_key="structural",
            predicted_value=10.0,
            actual_value=10.0,
            pit_grade="C_structural_replay",
            evaluation_status="structural_calibration",
        ),
    ]
    table = contract_table(pd.DataFrame(rows), "mtr:FY:transport_operations_revenue:mtr_physics_yield_v1")
    assert list(table["row_key"]) if "row_key" in table else len(table) == 1
    assert len(table) == 1
    assert pd.isna(table["abs_pct_error"].iloc[0])


def test_contract_summary_matches_legacy_mape() -> None:
    rows = [
        _long_form_row(
            row_key=f"c{i}",
            period_start=f"20{15 + i}-01-01",
            period_end=f"20{15 + i}-12-31",
            predicted_value=100.0 + i,
            actual_value=95.0 + i,
        )
        for i in range(3)
    ]
    frame = pd.DataFrame(rows)
    summary = contract_summary(frame, ["mtr:FY:transport_operations_revenue:mtr_physics_yield_v1"])
    assert len(summary) == 1
    assert summary["n_eval"].iloc[0] == 3
    assert summary["mape_pct"].iloc[0] == pytest.approx(
        (5 / 95 + 5 / 96 + 5 / 97) / 3 * 100.0
    )
    assert summary["metric_grain"].iloc[0] == "per_entity"
    assert summary["entity_id"].iloc[0] == "MTR"
    assert summary["unit_canonical"].iloc[0] == "HKD_mn"


def test_contract_summary_defaults_to_per_entity_and_keeps_pooled_reference() -> None:
    rows = [
        _long_form_row(
            row_key=f"entity-{entity}",
            entity_id=entity,
            predicted_value=105.0,
            actual_value=100.0,
        )
        for entity in ("A", "B")
    ]
    frame = pd.DataFrame(rows)
    registry_id = "mtr:FY:transport_operations_revenue:mtr_physics_yield_v1"

    per_entity = contract_summary(frame, [registry_id])
    assert set(per_entity["metric_grain"]) == {"per_entity"}
    assert set(per_entity["entity_id"]) == {"A", "B"}
    assert set(per_entity["n_eval"]) == {1}

    pooled = contract_summary(frame, [registry_id], metric_grain="pooled")
    assert len(pooled) == 1
    assert pooled["metric_grain"].iloc[0] == "pooled"
    assert pooled["entity_id"].iloc[0] == "A;B"
    assert pooled["n_eval"].iloc[0] == 2


def test_contract_summary_reuses_precomputed_metrics_table(monkeypatch: pytest.MonkeyPatch) -> None:
    """A passed-in ``metrics`` table must be reused, not recomputed.

    Mirrors compute_error_intervals's optional-``metrics``/fallback contract.
    Wraps pivot.compute_metric_table to count invocations: passing a
    precomputed table must trigger zero calls, while omitting it must fall
    back to exactly one call -- and either way the emitted rows must be
    identical, so a caller cannot get a different (or unguarded) answer by
    passing metrics ahead of time.
    """
    rows = [
        _long_form_row(
            row_key=f"c{i}",
            period_start=f"20{15 + i}-01-01",
            period_end=f"20{15 + i}-12-31",
            predicted_value=100.0 + i,
            actual_value=95.0 + i,
        )
        for i in range(3)
    ]
    frame = pd.DataFrame(rows)
    registry_id = "mtr:FY:transport_operations_revenue:mtr_physics_yield_v1"

    import src.common.backtest.pivot as pivot_module

    precomputed = compute_metric_table(frame)

    call_count = {"n": 0}
    original_compute_metric_table = pivot_module.compute_metric_table

    def _counting_compute_metric_table(long_form_arg):
        call_count["n"] += 1
        return original_compute_metric_table(long_form_arg)

    monkeypatch.setattr(pivot_module, "compute_metric_table", _counting_compute_metric_table)

    with_precomputed = contract_summary(frame, [registry_id], metrics=precomputed)
    assert call_count["n"] == 0, "passing metrics= must not trigger a recompute"

    without_precomputed = contract_summary(frame, [registry_id])
    assert call_count["n"] == 1, "omitting metrics= must fall back to computing it exactly once"

    pd.testing.assert_frame_equal(
        with_precomputed.reset_index(drop=True),
        without_precomputed.reset_index(drop=True),
    )


def test_contract_summary_raises_on_stale_precomputed_metrics() -> None:
    """A precomputed ``metrics`` table missing the guard row must still raise.

    Passing metrics= must not let a caller silently bypass the
    one-guard-row-or-raise contract that contract_summary already enforces
    when it computes the table itself.
    """
    rows = [
        _long_form_row(
            row_key=f"c{i}",
            period_start=f"20{15 + i}-01-01",
            period_end=f"20{15 + i}-12-31",
            predicted_value=100.0 + i,
            actual_value=95.0 + i,
        )
        for i in range(3)
    ]
    frame = pd.DataFrame(rows)
    registry_id = "mtr:FY:transport_operations_revenue:mtr_physics_yield_v1"
    stale_metrics = compute_metric_table(frame).iloc[0:0]  # emptied out, i.e. stale/partial

    with pytest.raises(ValueError, match="guard row"):
        contract_summary(frame, [registry_id], metrics=stale_metrics)
