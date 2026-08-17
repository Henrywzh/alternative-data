"""Tests for the MTR chronological practical-OOS track."""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.build_mtr_walk_forward_oos import build_walk_forward


def test_walk_forward_is_chronological_and_auditable() -> None:
    walk, monthly, summary = build_walk_forward()

    assert len(walk) == 16
    assert len(monthly) == 90
    assert summary["strict_pit_status"] == "not_eligible_until_patronage_release_registry_exists"
    assert summary["input_bundle"]["model_code"]["path"] == "scripts/build_mtr_walk_forward_oos.py"
    assert len(summary["input_bundle"]["model_code"]["sha256"]) == 64
    assert walk["input_bundle_id"].nunique() == 1
    assert walk["forecast_origin"].notna().all()
    assert walk["information_cutoff"].notna().all()
    assert walk["actual_available_at"].notna().all()
    assert walk["pit_grade"].eq("B_practical_pit").where(walk["has_prediction"], True).all()

    valid = walk[walk["has_prediction"]].copy()
    assert (valid["anchor_year"] < valid["target_year"]).all()
    assert (
        pd.to_datetime(valid["anchor_release_date"])
        <= pd.to_datetime(valid["information_cutoff"])
    ).all()
    assert valid["forecast_origin"].equals(valid["information_cutoff"])


def test_walk_forward_excludes_first_period_without_prior_anchor() -> None:
    walk, _, _ = build_walk_forward()
    first_fy = walk[(walk["period_type"] == "FY") & (walk["target_year"] == 2019)].iloc[0]
    first_h1 = walk[(walk["period_type"] == "H1") & (walk["target_year"] == 2017)].iloc[0]
    assert not bool(first_fy["has_prediction"])
    assert not bool(first_h1["has_prediction"])
    assert first_fy["evaluation_status"] == "insufficient_prior_actual_coverage"
    assert first_h1["evaluation_status"] == "insufficient_prior_actual_coverage"


def test_walk_forward_metrics_are_not_legacy_replay_metrics() -> None:
    _, _, summary = build_walk_forward()
    assert summary["metrics"]["FY"]["mape_pct"] == pytest.approx(9.3214592473)
    assert summary["metrics"]["H1"]["mape_pct"] == pytest.approx(8.1001304422)
    assert summary["metrics"]["FY"]["mape_pct"] > 4.78
    assert summary["metrics"]["H1"]["mape_pct"] > 5.99
