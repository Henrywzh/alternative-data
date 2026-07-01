from __future__ import annotations

import pandas as pd

from signal_layer.quality import canonicalize_latest, evaluate_metric_quality


def test_canonicalize_latest_prefers_enriched_latest_rows() -> None:
    frame = pd.DataFrame(
        [
            {
                "provider": "anthropic",
                "package_name": "@anthropic-ai/sdk",
                "download_date": "2026-01-01",
                "package_category": pd.NA,
                "source_run_id": "20260414T000000Z-old",
                "downloads": 100,
            },
            {
                "provider": "anthropic",
                "package_name": "@anthropic-ai/sdk",
                "download_date": "2026-01-01",
                "package_category": "core_sdk",
                "source_run_id": "20260630T000000Z-new",
                "downloads": 100,
            },
        ]
    )

    result = canonicalize_latest(
        frame,
        grain=["provider", "package_name", "download_date"],
        prefer_non_null=["package_category"],
        run_id_column="source_run_id",
    )

    assert len(result) == 1
    assert result.iloc[0]["package_category"] == "core_sdk"


def test_evaluate_metric_quality_flags_insufficient_history() -> None:
    issues = evaluate_metric_quality(
        baseline_observation_count=12,
        min_baseline_observations=30,
        latest_date=pd.Timestamp("2026-06-30"),
        run_date=pd.Timestamp("2026-07-01"),
        max_freshness_lag_days=7,
        invalid_value_count=0,
        duplicate_count=0,
        coverage_ratio=None,
        min_coverage_ratio=None,
        partial_period=False,
        source_validated=True,
    )

    assert issues.quality_state == "insufficient_history"
    assert "baseline_observation_count=12 below min_baseline_observations=30" in issues.quality_issues


def test_evaluate_metric_quality_prioritizes_duplicate_grain() -> None:
    issues = evaluate_metric_quality(
        baseline_observation_count=40,
        min_baseline_observations=30,
        latest_date=pd.Timestamp("2026-06-30"),
        run_date=pd.Timestamp("2026-07-01"),
        max_freshness_lag_days=7,
        invalid_value_count=0,
        duplicate_count=2,
        coverage_ratio=None,
        min_coverage_ratio=None,
        partial_period=False,
        source_validated=True,
    )

    assert issues.quality_state == "duplicate_grain"
    assert "duplicate_count=2" in issues.quality_issues


def test_evaluate_metric_quality_flags_low_coverage() -> None:
    issues = evaluate_metric_quality(
        baseline_observation_count=40,
        min_baseline_observations=30,
        latest_date=pd.Timestamp("2026-06-30"),
        run_date=pd.Timestamp("2026-07-01"),
        max_freshness_lag_days=7,
        invalid_value_count=0,
        duplicate_count=0,
        coverage_ratio=0.62,
        min_coverage_ratio=0.8,
        partial_period=False,
        source_validated=True,
    )

    assert issues.quality_state == "low_coverage"
    assert "coverage_ratio=0.620 below min_coverage_ratio=0.800" in issues.quality_issues
