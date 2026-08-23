from __future__ import annotations

import os as _os
from pathlib import Path as _Path

# The builders write here; tests/conftest.py redirects the directory so those
# writes stay out of the working tree. Reading the literal "data/registries/..."
# would have read the repository's stale copy instead of what the test built.
_REGISTRY_DIR = _Path(_os.environ.get("ASIA_BACKTEST_REGISTRY_DIR", "").strip() or "data/registries")

import pandas as pd

from scripts.build_asia_backtest_registry import (
    DEFAULT_MODEL_SENTINEL,
    _aggregate_status,
    _assign_dedup_flags,
    _contract_default_from_entities,
    _date_bounds,
    _entity_best_model,
    _load_previous_metrics,
    _mtr_status,
    _period_type_for_row,
    _row_status,
    _selection_evidence_fingerprint,
    build_mtr_rows,
    build_target_registry,
)


def test_mtr_h1_actual_arrival_promotes_current_forecast_and_preserves_provenance(monkeypatch) -> None:
    import scripts.build_asia_backtest_registry as module

    annual = pd.DataFrame(
        [
            {
                "year": 2026,
                "farebox_revenue_hkdm": 12000.0,
                "transport_ops_revenue_hkdm": None,
                "period_status": "partial_ytd",
                "coverage_end": "2026-06-30",
                "ridge_adjusted_revenue_hkdm": None,
            }
        ]
    )
    h1 = pd.DataFrame(
        [
            {
                "year": 2026,
                "h1_model_revenue_hkdm": 12000.0,
                "h1_actual_transport_ops_revenue_hkdm": None,
                "actual_status": "not_yet_reported",
                "backtest_role": "current_forecast",
                "actual_available_at": "2026-08-14",
                "release_source_url": "https://www.mtr.com.hk/archive/corporate/en/press_release/PR-26-059-E.pdf",
                "source_url": "https://www.mtr.com.hk/archive/corporate/en/investor/interim2026/2026IR_Eng.pdf",
            }
        ]
    )
    canonical = pd.DataFrame(
        [
            {
                "period_type": "H1",
                "year": 2026,
                "actual_value_hkdm": 12100.0,
                "actual_available_at": "2026-08-14",
                "release_source_url": "https://www.mtr.com.hk/archive/corporate/en/press_release/PR-26-059-E.pdf",
            }
        ]
    )

    def fake_read(path):
        if path.stem.endswith("annual_backtest"):
            return annual.copy()
        if path.stem.endswith("h1_backtest"):
            return h1.copy()
        return canonical.copy()

    monkeypatch.setattr(module, "_read_csv", fake_read)
    rows = pd.DataFrame(module.build_mtr_rows())
    arrived = rows[
        rows["source_dataset"].eq("mtr_farebox_revenue_h1_backtest")
        & rows["source_row_index"].eq(0)
    ]

    assert len(arrived) == 1
    assert arrived["source_row_status"].iloc[0] == "practical_forward_validation"
    assert arrived["evaluation_status"].iloc[0] == "valid_practical_oos"
    assert arrived["actual_available_at"].iloc[0] == "2026-08-14"
    assert arrived["actual_source_url"].iloc[0].endswith("PR-26-059-E.pdf")


def test_mtr_annual_ytd_alias_also_promotes_when_canonical_h1_actual_arrives(monkeypatch) -> None:
    import scripts.build_asia_backtest_registry as module

    annual = pd.DataFrame(
        [{
            "year": 2026,
            "farebox_revenue_hkdm": 12000.0,
            "transport_ops_revenue_hkdm": None,
            "period_status": "partial_ytd",
            "ridge_adjusted_revenue_hkdm": None,
        }]
    )
    h1 = pd.DataFrame(
        [{
            "year": 2026,
            "h1_model_revenue_hkdm": 12000.0,
            "h1_actual_transport_ops_revenue_hkdm": None,
            "actual_status": "not_yet_reported",
            "backtest_role": "current_forecast",
        }]
    )
    canonical = pd.DataFrame(
        [{
            "period_type": "H1",
            "year": 2026,
            "actual_value_hkdm": 12100.0,
            "actual_available_at": "2026-08-14",
            "release_source_url": "https://www.mtr.com.hk/archive/corporate/en/press_release/PR-26-059-E.pdf",
        }]
    )

    def fake_read(path):
        if path.stem.endswith("annual_backtest"):
            return annual.copy()
        if path.stem.endswith("h1_backtest"):
            return h1.copy()
        return canonical.copy()

    monkeypatch.setattr(module, "_read_csv", fake_read)
    rows = pd.DataFrame(module.build_mtr_rows())
    alias = rows[
        rows["source_dataset"].eq("mtr_farebox_revenue_annual_backtest")
        & rows["source_row_index"].eq(0)
    ]
    assert len(alias) == 2
    assert alias["target_period_type"].eq("H1").all()
    assert alias["track_id"].eq("ytd_current").all()
    assert alias["evaluation_status"].eq("valid_practical_oos").all()
    assert alias["has_actual"].all()


def test_mtr_2026_annual_source_row_is_classified_as_h1_forecast() -> None:
    row = pd.Series(
        {
            "year": 2026,
            "farebox_revenue_hkdm": 11976.69,
            "transport_ops_revenue_hkdm": None,
        }
    )

    status, grade, evaluation, *_ = _mtr_status(
        row,
        period_type="H1",
        current_forecast=True,
    )

    assert status == "current_forecast"
    assert grade == "B_practical_pit"
    assert evaluation == "forecast_only"
    assert _date_bounds("H1", 2026) == ("2026-01-01", "2026-06-30")


def test_mtr_reported_h1_is_not_forecast_only() -> None:
    row = pd.Series(
        {
            "year": 2026,
            "h1_model_revenue_hkdm": 12000.0,
            "h1_actual_transport_ops_revenue_hkdm": 12100.0,
            "backtest_role": "current_forecast",
        }
    )
    status, grade, evaluation, *_ = _mtr_status(row, period_type="H1")
    assert status == "practical_forward_validation"
    assert grade == "B_practical_pit"
    assert evaluation == "valid_practical_oos"


def test_structural_grade_suppresses_headline_accuracy() -> None:
    status, headline = _aggregate_status(
        pd.Series(["structural_calibration"] * 10),
        pd.Series(["C_structural_replay"] * 10),
        has_actual=10,
        n_valid=10,
        period_type="FY",
        diagnostic=False,
    )

    assert status == "structural_calibration"
    assert headline is False


def test_practical_pit_rows_can_be_headline_eligible_when_sample_is_sufficient() -> None:
    status, headline = _aggregate_status(
        pd.Series(["valid_practical_oos"] * 10),
        pd.Series(["B_practical_pit"] * 10),
        has_actual=10,
        n_valid=10,
        period_type="FY",
        diagnostic=False,
    )

    assert status == "valid_practical_oos"
    assert headline is True


def test_target_registry_exposes_candidate_headline_scope() -> None:
    import scripts.build_asia_backtest_registry as module

    registry = module.build_registry()["target_registry"]
    assert "candidate_headline_eligible" in registry.columns
    assert "headline_eligibility_scope" in registry.columns
    assert "headline_eligible" not in registry.columns
    assert set(registry["headline_eligibility_scope"]) == {"candidate_pre_metric_policy"}


def test_forward_oos_is_eligible_but_structural_checks_are_not() -> None:
    status, headline = _aggregate_status(
        pd.Series(["historical_structural_check"] * 11),
        pd.Series(["B_practical_pit"] * 11),
        has_actual=11,
        n_valid=11,
        period_type="H1",
        diagnostic=False,
    )
    assert status == "historical_structural_check"
    assert headline is False

    status, headline = _aggregate_status(
        pd.Series(["historical_structural_check"] * 10 + ["valid_forward_oos"]),
        pd.Series(["B_practical_pit"] * 11),
        has_actual=11,
        n_valid=11,
        period_type="H1",
        diagnostic=False,
    )
    assert status == "valid_practical_oos"
    assert headline is True


def test_no_prediction_current_row_is_not_labelled_as_current_forecast() -> None:
    status, headline = _aggregate_status(
        pd.Series(["forecast_only"]),
        pd.Series(["B_practical_pit"]),
        has_actual=0,
        n_valid=0,
        period_type="H1",
        diagnostic=False,
        n_predictions=0,
    )
    assert status == "insufficient_input_coverage"
    assert headline is False


def test_diagnostic_target_never_enters_headline_accuracy() -> None:
    status, headline = _aggregate_status(
        pd.Series(["diagnostic_only"] * 100),
        pd.Series(["D_diagnostic_only"] * 100),
        has_actual=100,
        n_valid=100,
        period_type="month",
        diagnostic=True,
    )

    assert status == "diagnostic_only"
    assert headline is False


def test_airline_period_type_uses_row_value_without_placeholder_dates() -> None:
    assert _period_type_for_row(pd.Series({"period": "H2"}), "FY") == "H2"
    assert _period_type_for_row(pd.Series({"period": None}), "FY") == "FY"
    assert _date_bounds(_period_type_for_row(pd.Series({"period": "H2"}), "FY"), 2025) == (
        "2025-07-01",
        "2025-12-31",
    )


def test_mtr_2026_rows_are_all_ytd_and_never_fy() -> None:
    rows = pd.DataFrame(build_mtr_rows())
    current = rows[rows["source_row_status"] == "current_forecast"]

    assert len(current) == 3
    assert set(current["target_period_type"]) == {"H1"}
    assert (current["track_id"] == "ytd_current").sum() == 2
    assert (current["track_id"] == "half_year_non_overlapping").sum() == 1
    assert not ((rows["source_row_index"] == 26) & (rows["target_period_type"] == "FY")).any()


def test_mtr_fy2024_is_structural_and_ridge_zero_adjustment_is_not_a_prediction() -> None:
    status_row = pd.Series({"year": 2024, "transport_ops_revenue_hkdm": 23013.0})
    _, grade, *_ = _mtr_status(status_row, period_type="FY")
    assert grade == "C_structural_replay"

    rows = pd.DataFrame(build_mtr_rows())
    ridge = rows[
        (rows["model_id"] == "mtr_ridge_residual_v1")
        & (rows["source_dataset"] == "mtr_farebox_revenue_annual_backtest")
    ]
    holdout = ridge["source_row_index"].isin([19, 20, 21, 22, 23])
    assert ridge.loc[holdout, "has_prediction"].all()
    assert not ridge.loc[~holdout, "has_prediction"].any()


def test_dedup_flags_prefer_unified_period_source() -> None:
    frame = pd.DataFrame(
        [
            {
                "logical_observation_id": "Air China:revenue:H1:2025-01-01",
                "model_id": "flat_ask_v1",
                "source_dataset": "airline_h1_kpi_backtest",
                "source_row_index": 0,
                "row_key": "h1",
            },
            {
                "logical_observation_id": "Air China:revenue:H1:2025-01-01",
                "model_id": "flat_ask_v1",
                "source_dataset": "airline_period_kpi_backtest",
                "source_row_index": 0,
                "row_key": "period",
            },
        ]
    )
    result = _assign_dedup_flags(frame)
    assert bool(result.loc[result.row_key == "period", "is_primary_source"].iloc[0])
    assert int(result.loc[result.row_key == "h1", "dedup_rank"].iloc[0]) == 2


def test_shkp_three_targets_are_separate_and_contract_activity_is_diagnostic() -> None:
    """Step 5 contract: SHKP is split into three targets and the gross SRPE
    contract-activity proxy never enters headline accuracy."""
    import pandas as pd

    registry = pd.read_csv(_REGISTRY_DIR / "asia_backtest_target_registry.csv")
    shkp = registry[registry["entity_scope"].astype(str).eq("SHKP")]
    targets = sorted(shkp["target_id"].unique())
    assert targets == ["contract_activity_proxy", "hk_rental_revenue", "underlying_profit"]

    contract = shkp[shkp["target_id"] == "contract_activity_proxy"]
    assert len(contract) == 6  # 2 methods x 3 scenarios
    assert (contract["pit_grade"] == "D_diagnostic_only").all()
    assert (contract["evaluation_status"] == "diagnostic_only").all()
    assert not contract["candidate_headline_eligible"].any()
    assert (contract["primary_metric"] == "diagnostic_coverage").all()

    # No SHKP target of any kind is headline eligible (all C/D grade).
    assert not shkp["candidate_headline_eligible"].any()

    skeleton = shkp[shkp["target_id"] == "underlying_profit"]
    assert len(skeleton) == 1
    assert skeleton["pit_grade"].iloc[0] == "C_structural_replay"
    commercial = shkp[shkp["target_id"] == "hk_rental_revenue"]
    assert len(commercial) == 3
    assert (commercial["pit_grade"] == "C_structural_replay").all()


def test_shkp_sales_model_ids_preserve_method_lookback_scenario() -> None:
    import pandas as pd

    row_status = pd.read_csv(_REGISTRY_DIR / "asia_backtest_row_status.csv")
    sales = row_status[row_status["source_dataset"] == "shkp_indicative_sales_model_backtest"]
    assert len(sales) == 948
    assert sales["model_id"].str.contains(r"_lb\d+_(?:low|base|high)$").all()
    assert sales["scenario"].isin(["low", "base", "high"]).all()
    assert sales["scenario"].notna().all()
    assert sales["lookback_months"].notna().all()


def _synthetic_row(
    *,
    source_dataset: str,
    target_id: str,
    model_id: str,
    entity_id: str,
    row_index: int,
    period_type: str = "FY",
    track_id: str = "fiscal_year",
    pit_grade: str = "B_practical_pit",
) -> dict:
    """Build one valid row_status row for the default_model_id tests below.

    registry_id intentionally ignores entity_id / row_index, matching the
    real builders: the same model candidate shares one registry_id across
    every entity in a contract.
    """
    registry_id = f"{source_dataset}:{period_type}:{target_id}:{model_id}"
    return _row_status(
        registry_id=registry_id,
        source_dataset=source_dataset,
        source_run_id="",
        source_row_index=row_index,
        entity_id=entity_id,
        target_id=target_id,
        period_type=period_type,
        track_id=track_id,
        period_value=2024,
        source_row_status="historical_evaluated",
        input_pit_status="not_captured",
        target_pit_status="reported_actual",
        pit_grade=pit_grade,
        evaluation_status="valid_practical_oos",
        has_prediction=True,
        has_actual=True,
        actual_available_at="2024-01-01",
        imputation_used=False,
        dependency_status="not_captured",
        model_id=model_id,
    )


def _synthetic_metric(
    *,
    registry_id: str,
    grain: str,
    entity_id: str,
    skill_vs_baseline: float | None,
    n_scaled: int = 8,
    metric_status: str = "insufficient_sample",
) -> dict:
    return {
        "metric_grain": grain,
        "is_baseline": False,
        "registry_id": registry_id,
        "entity_id": entity_id,
        "skill_vs_baseline": skill_vs_baseline,
        "n_scaled": n_scaled,
        "metric_status": metric_status,
    }


def _metrics_bundle(rows: list[dict]) -> dict:
    return {
        "available": True,
        "frame": pd.DataFrame(rows),
        "source_path": "synthetic_metrics.csv",
        "evidence_fingerprint": "selection_evidence-synthetic",
        "input_bundle_id": "synthetic-bundle",
        "latest_run_id": "synthetic-run",
    }


def test_entity_best_model_never_picks_negative_skill() -> None:
    lookup = {("r:model_bad", "EntityA"): {"skill_vs_baseline": -0.4, "n_scaled": 8, "metric_status": "insufficient_sample"}}
    pick = _entity_best_model("EntityA", ["model_bad"], {"model_bad": "r:model_bad"}, lookup)
    assert pick["status"] == "no_model_beats_baseline"
    assert pick["model_id"] is None


def test_entity_best_model_ranks_on_skill_and_skips_unmeasured_candidates() -> None:
    lookup = {
        ("r:model_a", "EntityA"): {"skill_vs_baseline": 0.2, "n_scaled": 8, "metric_status": "insufficient_sample"},
        # model_b has no entry at all (never measured for this entity).
    }
    registry_ids = {"model_a": "r:model_a", "model_b": "r:model_b"}
    pick = _entity_best_model("EntityA", ["model_a", "model_b"], registry_ids, lookup)
    assert pick["status"] == "measured"
    assert pick["model_id"] == "model_a"


def test_entity_best_model_with_no_measured_candidates_is_not_measured() -> None:
    pick = _entity_best_model("EntityA", ["model_a"], {"model_a": "r:model_a"}, {})
    assert pick["status"] == "not_measured"
    assert pick["model_id"] is None


def test_entity_best_model_tie_breaks_deterministically_on_model_id() -> None:
    # Mirrors the real spring_recovery_v1/flat_rpk_v1 degeneracy: two models
    # produce bit-identical predictions for an entity, so their skill is
    # bit-identical too. The pick must not depend on dict/frame iteration
    # order, only on the model_id string.
    lookup = {
        ("r:zeta", "EntityA"): {"skill_vs_baseline": 0.6, "n_scaled": 8, "metric_status": "insufficient_sample"},
        ("r:alpha", "EntityA"): {"skill_vs_baseline": 0.6, "n_scaled": 8, "metric_status": "insufficient_sample"},
    }
    registry_ids = {"zeta": "r:zeta", "alpha": "r:alpha"}
    pick = _entity_best_model("EntityA", ["zeta", "alpha"], registry_ids, lookup)
    assert pick["model_id"] == "alpha"
    # Order of the candidates list must not change the outcome.
    pick_reversed = _entity_best_model("EntityA", ["alpha", "zeta"], registry_ids, lookup)
    assert pick_reversed["model_id"] == "alpha"


def test_contract_default_all_negative_yields_sentinel() -> None:
    picks = [
        {"entity_id": "EntityA", "model_id": None, "status": "no_model_beats_baseline", "evidence": None},
        {"entity_id": "EntityB", "model_id": None, "status": "no_model_beats_baseline", "evidence": None},
    ]
    result = _contract_default_from_entities(picks)
    assert result["status"] == "measured_no_model_beats_baseline"
    assert result["model_id"] == DEFAULT_MODEL_SENTINEL


def test_contract_default_majority_vote_flags_the_minority_entity() -> None:
    picks = [
        {"entity_id": "EntityA", "model_id": "model_x", "status": "measured", "evidence": {"skill_vs_baseline": 0.5, "n_scaled": 8, "metric_status": "insufficient_sample"}},
        {"entity_id": "EntityB", "model_id": "model_x", "status": "measured", "evidence": {"skill_vs_baseline": 0.6, "n_scaled": 8, "metric_status": "insufficient_sample"}},
        {"entity_id": "EntityC", "model_id": "model_y", "status": "measured", "evidence": {"skill_vs_baseline": 0.8, "n_scaled": 8, "metric_status": "insufficient_sample"}},
    ]
    result = _contract_default_from_entities(picks)
    assert result["status"] == "measured_per_entity_majority"
    assert result["model_id"] == "model_x"
    assert result["vote_count"] == 2
    assert result["total_measured_entities"] == 3


def test_contract_default_with_no_measurement_falls_back() -> None:
    picks = [{"entity_id": "EntityA", "model_id": None, "status": "not_measured", "evidence": None}]
    result = _contract_default_from_entities(picks)
    assert result["status"] == "assumed_heuristic_fallback"
    assert result["model_id"] is None


def test_load_previous_metrics_missing_file_is_reported_as_unavailable(tmp_path) -> None:
    bundle = _load_previous_metrics(tmp_path)
    assert bundle["available"] is False
    assert bundle["frame"].empty
    assert bundle["input_bundle_id"] == "not_captured"
    assert bundle["latest_run_id"] == "not_captured"


def test_load_previous_metrics_reads_input_bundle_id_and_run_id(tmp_path) -> None:
    metrics = pd.DataFrame(
        [_synthetic_metric(registry_id="r:m", grain="pooled", entity_id="", skill_vs_baseline=0.1)]
    )
    metrics["input_bundle_id"] = "bundle-123"
    metrics.to_csv(tmp_path / "asia_backtest_metrics.csv", index=False)
    (tmp_path / "asia_backtest_latest.json").write_text('{"run_id": "run-456"}')

    bundle = _load_previous_metrics(tmp_path)
    assert bundle["available"] is True
    assert bundle["input_bundle_id"] == "bundle-123"
    assert bundle["latest_run_id"] == "run-456"


def test_negative_skill_model_is_never_the_registry_default() -> None:
    row_status = _assign_dedup_flags(
        pd.DataFrame(
            [
                _synthetic_row(
                    source_dataset="synthetic_neg",
                    target_id="synthetic_target",
                    model_id="model_bad",
                    entity_id="EntityA",
                    row_index=0,
                )
            ]
        )
    )
    registry_id = "synthetic_neg:FY:synthetic_target:model_bad"
    bundle = _metrics_bundle(
        [
            _synthetic_metric(registry_id=registry_id, grain="per_entity", entity_id="EntityA", skill_vs_baseline=-0.5),
            _synthetic_metric(registry_id=registry_id, grain="pooled", entity_id="", skill_vs_baseline=-0.5),
        ]
    )
    registry = build_target_registry(row_status, bundle)
    row = registry.iloc[0]
    assert row["default_model_id"] == DEFAULT_MODEL_SENTINEL
    assert row["default_model_id"] != "model_bad"
    assert row["default_model_selection_basis"] == "measured_no_model_beats_baseline"


def test_all_candidates_negative_yields_sentinel_with_baseline_kept() -> None:
    rows = [
        _synthetic_row(
            source_dataset="synthetic_neg2",
            target_id="synthetic_target",
            model_id=model_id,
            entity_id="EntityA",
            row_index=index,
        )
        for index, model_id in enumerate(["model_a", "model_b"])
    ]
    row_status = _assign_dedup_flags(pd.DataFrame(rows))
    bundle = _metrics_bundle(
        [
            _synthetic_metric(
                registry_id=f"synthetic_neg2:FY:synthetic_target:{model_id}",
                grain="per_entity",
                entity_id="EntityA",
                skill_vs_baseline=skill,
            )
            for model_id, skill in [("model_a", -0.1), ("model_b", -0.9)]
        ]
    )
    registry = build_target_registry(row_status, bundle)
    assert (registry["default_model_id"] == DEFAULT_MODEL_SENTINEL).all()
    assert (registry["default_model_selection_basis"] == "measured_no_model_beats_baseline").all()
    # The naive baseline stays declared as the best available choice.
    assert (registry["default_baseline_id"] == "same_period_last_year").all()


def test_missing_metrics_file_falls_back_and_is_labelled_assumed(tmp_path) -> None:
    row_status = _assign_dedup_flags(
        pd.DataFrame(
            [
                _synthetic_row(
                    source_dataset="mtr_synthetic_dataset",
                    target_id="transport_operations_revenue",
                    model_id="mtr_physics_yield_v1",
                    entity_id="MTR",
                    row_index=0,
                )
            ]
        )
    )
    bundle = _load_previous_metrics(tmp_path)
    assert bundle["available"] is False

    registry = build_target_registry(row_status, bundle)
    row = registry.iloc[0]
    # Falls back to the pre-metrics heuristic chain (mtr_ prefix -> physics model).
    assert row["default_model_id"] == "mtr_physics_yield_v1"
    assert row["default_model_selection_basis"] == "assumed_heuristic_fallback"
    assert row["default_model_selection_confidence"] == "not_measured"
    assert row["default_model_id_by_entity"] == "MTR=not_measured"
    assert row["default_model_selection_evidence_fingerprint"] == "not_captured"


def test_diagnostic_only_contract_never_acquires_skill_derived_default() -> None:
    row_status = _assign_dedup_flags(
        pd.DataFrame(
            [
                _synthetic_row(
                    source_dataset="shkp_synthetic_sales",
                    target_id="contract_activity_proxy",
                    model_id="trailing_mean_lb3_base",
                    entity_id="SHKP",
                    row_index=0,
                    period_type="month",
                    track_id="monthly_sparse",
                    pit_grade="D_diagnostic_only",
                )
            ]
        )
    )
    registry_id = "shkp_synthetic_sales:month:contract_activity_proxy:trailing_mean_lb3_base"
    # Even with strong measured positive skill on file, contract_activity_proxy
    # must stay diagnostic-only per the pre-existing special case.
    bundle = _metrics_bundle(
        [
            _synthetic_metric(registry_id=registry_id, grain="per_entity", entity_id="SHKP", skill_vs_baseline=0.9),
            _synthetic_metric(registry_id=registry_id, grain="pooled", entity_id="", skill_vs_baseline=0.9),
        ]
    )
    registry = build_target_registry(row_status, bundle)
    row = registry.iloc[0]
    assert row["default_model_id"] == "not_applicable"
    assert row["default_model_selection_basis"] == "not_applicable"
    assert row["default_model_id_by_entity"] == "not_applicable"


def test_per_entity_majority_vote_selects_default_and_flags_disagreeing_entity() -> None:
    entities = ["EntityA", "EntityB", "EntityC"]
    models = ["model_x", "model_y"]
    rows = [
        _synthetic_row(
            source_dataset="synthetic_vote",
            target_id="revenue",
            model_id=model_id,
            entity_id=entity_id,
            row_index=index,
        )
        for index, (entity_id, model_id) in enumerate(
            [(entity_id, model_id) for entity_id in entities for model_id in models]
        )
    ]
    row_status = _assign_dedup_flags(pd.DataFrame(rows))
    # EntityA and EntityB both do best with model_x; EntityC does best with model_y.
    skills = {
        "EntityA": {"model_x": 0.7, "model_y": 0.3},
        "EntityB": {"model_x": 0.6, "model_y": 0.2},
        "EntityC": {"model_x": 0.1, "model_y": 0.9},
    }
    metric_rows = [
        _synthetic_metric(
            registry_id=f"synthetic_vote:FY:revenue:{model_id}",
            grain="per_entity",
            entity_id=entity_id,
            skill_vs_baseline=skill,
        )
        for entity_id, model_skills in skills.items()
        for model_id, skill in model_skills.items()
    ]
    bundle = _metrics_bundle(metric_rows)
    registry = build_target_registry(row_status, bundle)

    for _, row in registry.iterrows():
        assert row["default_model_id"] == "model_x"
        assert row["default_model_selection_basis"] == "per_entity_majority_vote"
        assert row["default_model_entity_vote_count"] == 2
        assert row["default_model_entity_total_count"] == 3
        assert row["default_model_id_entity_disagreements"] == "EntityC"
        assert "EntityC=model_y" in row["default_model_id_by_entity"]


def _metric_frame_with_ids(input_bundle_id: str, run_id_column_value: str) -> pd.DataFrame:
    """A metrics frame whose measured values are fixed but whose ids differ."""
    return pd.DataFrame(
        [
            {
                "registry_id": "synthetic:FY:revenue:model_x",
                "entity_id": "EntityA",
                "model_id": "model_x",
                "metric_grain": "per_entity",
                "is_baseline": False,
                "skill_vs_baseline": 0.42,
                "n_scaled": 8,
                "metric_status": "insufficient_sample",
                "input_bundle_id": input_bundle_id,
                "notes": run_id_column_value,
            }
        ]
    )


def test_selection_evidence_fingerprint_ignores_volatile_run_identity() -> None:
    """The registry is hashed into the long-form input bundle, so a value it
    records must not change when only the *identity* of the source run does.

    Recording the previous run's input_bundle_id/run_id made the pipeline
    never reach a fixed point: registry changes -> bundle hash changes -> new
    run id -> registry changes again. A single-rebuild determinism check
    cannot catch that, because the churn only appears across runs.
    """
    first = _selection_evidence_fingerprint(_metric_frame_with_ids("bundle-aaa", "run-aaa"))
    second = _selection_evidence_fingerprint(_metric_frame_with_ids("bundle-bbb", "run-bbb"))
    assert first == second
    assert first.startswith("selection_evidence-")


def test_selection_evidence_fingerprint_changes_when_measured_skill_changes() -> None:
    """The fingerprint must still detect a real change in the evidence."""
    base = _metric_frame_with_ids("bundle-aaa", "run-aaa")
    moved = base.copy()
    moved.loc[0, "skill_vs_baseline"] = 0.91
    assert _selection_evidence_fingerprint(base) != _selection_evidence_fingerprint(moved)


def test_registry_rows_carry_no_volatile_run_identity_columns() -> None:
    """Guards the fix at the schema level: no registry column may hold a run
    id or input bundle id, since every registry column feeds the next stage's
    content hash. Those ids belong in the manifest, which is not hashed."""
    row_status = _assign_dedup_flags(
        pd.DataFrame(
            [
                _synthetic_row(
                    source_dataset="synthetic",
                    target_id="revenue",
                    model_id="model_x",
                    entity_id="EntityA",
                    row_index=0,
                )
            ]
        )
    )
    registry = build_target_registry(row_status, _metrics_bundle([]))
    offenders = [
        column
        for column in registry.columns
        if column.endswith("_run_id") or column.endswith("_input_bundle_id")
    ]
    assert offenders == []
