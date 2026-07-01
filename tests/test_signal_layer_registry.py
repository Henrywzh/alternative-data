from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from signal_layer.registry import RegistryValidationError, load_registries, validate_registries


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def test_load_registries_accepts_valid_reference_files(tmp_path: Path) -> None:
    reference_dir = tmp_path / "data" / "reference" / "signal_layer"
    _write_csv(
        reference_dir / "signal_metric_registry.csv",
        [
            {
                "metric_id": "pypi_openai_downloads_28d_growth",
                "source": "provider_adoption",
                "dataset_id": "pypi_downloads_daily",
                "date_column": "download_date",
                "value_column": "downloads",
                "entity_columns": "provider|package_name|with_mirrors",
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
                "description": "OpenAI PyPI download 28-day growth.",
                "caveats": "Package downloads include non-production usage.",
            }
        ],
    )
    _write_csv(
        reference_dir / "signal_asset_mapping.csv",
        [
            {
                "metric_id": "pypi_openai_downloads_28d_growth",
                "ticker": "MSFT",
                "company_name": "Microsoft",
                "asset_type": "equity",
                "theme": "developer_ecosystem",
                "exposure_type": "ecosystem_adoption",
                "expected_direction": "positive",
                "exposure_weight": 1.0,
                "lag_days": 0,
                "confidence": "medium",
                "notes": "Microsoft has economic exposure to OpenAI adoption.",
            }
        ],
    )

    metric_registry, asset_mapping = load_registries(tmp_path)

    assert metric_registry["metric_id"].tolist() == ["pypi_openai_downloads_28d_growth"]
    assert asset_mapping["ticker"].tolist() == ["MSFT"]


def test_validate_registries_rejects_duplicate_metric_ids() -> None:
    metrics = pd.DataFrame(
        [
            {
                "metric_id": "duplicate",
                "source": "provider_adoption",
                "dataset_id": "pypi_downloads_daily",
                "date_column": "download_date",
                "value_column": "downloads",
                "entity_columns": "provider",
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
                "description": "First row.",
                "caveats": "",
            },
            {
                "metric_id": "duplicate",
                "source": "provider_adoption",
                "dataset_id": "npm_downloads_daily",
                "date_column": "download_date",
                "value_column": "downloads",
                "entity_columns": "provider",
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
                "description": "Second row.",
                "caveats": "",
            },
        ]
    )
    mappings = pd.DataFrame(
        [
            {
                "metric_id": "duplicate",
                "ticker": "MSFT",
                "company_name": "Microsoft",
                "asset_type": "equity",
                "theme": "developer_ecosystem",
                "exposure_type": "ecosystem_adoption",
                "expected_direction": "positive",
                "exposure_weight": 1.0,
                "lag_days": 0,
                "confidence": "medium",
                "notes": "Mapping note.",
            }
        ]
    )

    with pytest.raises(RegistryValidationError, match="duplicate metric_id"):
        validate_registries(metrics, mappings)


def test_validate_registries_rejects_mapping_to_unknown_metric() -> None:
    metrics = pd.DataFrame(
        [
            {
                "metric_id": "known_metric",
                "source": "provider_adoption",
                "dataset_id": "pypi_downloads_daily",
                "date_column": "download_date",
                "value_column": "downloads",
                "entity_columns": "provider",
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
                "description": "Known metric.",
                "caveats": "",
            }
        ]
    )
    mappings = pd.DataFrame(
        [
            {
                "metric_id": "missing_metric",
                "ticker": "MSFT",
                "company_name": "Microsoft",
                "asset_type": "equity",
                "theme": "developer_ecosystem",
                "exposure_type": "ecosystem_adoption",
                "expected_direction": "positive",
                "exposure_weight": 1.0,
                "lag_days": 0,
                "confidence": "medium",
                "notes": "Mapping note.",
            }
        ]
    )

    with pytest.raises(RegistryValidationError, match="unknown metric_id"):
        validate_registries(metrics, mappings)
