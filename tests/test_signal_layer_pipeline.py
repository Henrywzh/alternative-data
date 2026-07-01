from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd

from signal_layer.pipeline import SignalLayerPipeline
from signal_layer.storage import SignalLayerStorage


def test_storage_writes_csv_and_parquet(tmp_path: Path) -> None:
    storage = SignalLayerStorage(tmp_path)
    frame = pd.DataFrame(
        [
            {
                "metric_id": "sample_metric",
                "source": "provider_adoption",
                "as_of_date": "2026-06-30",
                "entity_key": "openai|openai",
                "entity_name": "openai",
                "latest_value": 1.0,
                "comparison_value": 0.5,
                "raw_change": 0.5,
                "pct_change": 100.0,
                "yoy_change": pd.NA,
                "rolling_change": 100.0,
                "z_score": 1.0,
                "robust_z_score": 1.0,
                "percentile": 90.0,
                "rank": pd.NA,
                "rank_change": pd.NA,
                "baseline_value": 0.5,
                "baseline_method": "robust_z",
                "baseline_window": "90D",
                "baseline_observation_count": 30,
                "empirical_percentile": 90.0,
                "tail_probability": 0.1,
                "effect_size": 1.0,
                "signed_stat": 1.0,
                "metric_direction": "positive",
                "signal_state": "watch",
                "confidence": "medium",
                "source_updated_at": "2026-06-30T00:00:00Z",
                "quality_state": "valid",
                "quality_issues": "",
                "caveats": "",
            }
        ]
    )

    output = storage.write_dataset("metric_signals", frame)

    assert output.name == "metric_signals.csv"
    assert output.exists()
    assert output.with_suffix(".parquet").exists()


def test_pipeline_validate_registry_returns_counts(tmp_path: Path) -> None:
    _write_reference_registries(tmp_path)

    counts = SignalLayerPipeline(tmp_path).validate_registry()

    assert counts == {"metrics": 1, "asset_mappings": 1}


def test_cli_validate_registry(tmp_path: Path) -> None:
    _write_reference_registries(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "signal_layer.cli",
            "--base-dir",
            str(tmp_path),
            "validate-registry",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "metrics: 1" in result.stdout
    assert "asset_mappings: 1" in result.stdout


def _write_reference_registries(base_dir: Path) -> None:
    reference_dir = base_dir / "data" / "reference" / "signal_layer"
    reference_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "metric_id": "sample_metric",
                "source": "provider_adoption",
                "dataset_id": "pypi_downloads_daily",
                "date_column": "download_date",
                "value_column": "downloads",
                "entity_columns": "provider|package_name",
                "cadence": "daily",
                "transform": "rolling_growth",
                "baseline_method": "robust_z",
                "baseline_window": "90D",
                "seasonality_mode": "none",
                "higher_is_better": True,
                "default_metric_direction": "positive",
                "min_baseline_observations": 30,
                "max_freshness_lag_days": 7,
                "min_coverage_ratio": "",
                "description": "Sample metric.",
                "caveats": "",
            }
        ]
    ).to_csv(reference_dir / "signal_metric_registry.csv", index=False)
    pd.DataFrame(
        [
            {
                "metric_id": "sample_metric",
                "ticker": "MSFT",
                "company_name": "Microsoft",
                "asset_type": "equity",
                "theme": "developer_ecosystem",
                "exposure_type": "ecosystem_adoption",
                "expected_direction": "positive",
                "exposure_weight": 1.0,
                "lag_days": 0,
                "confidence": "medium",
                "notes": "Sample mapping.",
            }
        ]
    ).to_csv(reference_dir / "signal_asset_mapping.csv", index=False)
