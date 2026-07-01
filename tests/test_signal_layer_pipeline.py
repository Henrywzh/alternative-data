from __future__ import annotations

import json
import os
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


def test_pipeline_build_writes_run_specific_outputs_and_updates_latest(
    tmp_path: Path,
) -> None:
    _write_reference_registries(tmp_path)

    result = SignalLayerPipeline(tmp_path).build(sources=["provider_adoption"])

    run_dir = tmp_path / "data" / "processed" / "signals" / result.run_id
    latest_dir = tmp_path / "data" / "processed" / "signals" / "latest"

    assert Path(result.output_dir) == run_dir
    assert run_dir.is_dir()
    assert latest_dir.is_dir()

    manifest = json.loads((run_dir / "latest_signal_run.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == result.run_id
    assert manifest["sources"] == ["provider_adoption"]
    assert manifest["datasets_written"] == result.datasets_written

    for directory in (run_dir, latest_dir):
        assert (directory / "metric_signals.csv").exists()
        assert (directory / "metric_signals.parquet").exists()
        assert (directory / "asset_signals.csv").exists()
        assert (directory / "asset_signals.parquet").exists()
        assert (directory / "theme_signals.csv").exists()
        assert (directory / "theme_signals.parquet").exists()
        assert (directory / "latest_signal_run.json").exists()


def test_pipeline_builds_use_distinct_run_ids_and_latest_tracks_newest(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _write_reference_registries(tmp_path)
    pipeline = SignalLayerPipeline(tmp_path)

    run_ids = iter(
        [
            "20260701T201042000000Z-firstaaa",
            "20260701T201042000000Z-firstaaa",
            "20260701T201042000001Z-secondbb",
        ]
    )
    monkeypatch.setattr("signal_layer.pipeline._run_id", lambda: next(run_ids))

    first = pipeline.build(sources=["provider_adoption"])
    second = pipeline.build(sources=["provider_adoption", "apps"])

    assert first.run_id != second.run_id
    assert first.output_dir != second.output_dir
    assert Path(first.output_dir).is_dir()
    assert Path(second.output_dir).is_dir()

    latest_manifest = json.loads(
        (
            tmp_path
            / "data"
            / "processed"
            / "signals"
            / "latest"
            / "latest_signal_run.json"
        ).read_text(encoding="utf-8")
    )
    assert latest_manifest["run_id"] == second.run_id
    assert latest_manifest["sources"] == ["provider_adoption", "apps"]
    assert latest_manifest["datasets_written"] == second.datasets_written


def test_pipeline_build_provider_adoption_signals(tmp_path: Path) -> None:
    _write_provider_adoption_fixture(tmp_path)

    result = SignalLayerPipeline(tmp_path).build(sources=["provider_adoption"])

    metric_signals = _read_metric_signals(tmp_path, result)

    assert len(metric_signals) == 1
    assert metric_signals.loc[0, "metric_id"] == "pypi_openai_downloads_28d_growth"
    assert metric_signals.loc[0, "quality_state"] == "valid"


def test_pipeline_build_provider_adoption_signals_ignores_mirror_variants(
    tmp_path: Path,
) -> None:
    _write_provider_adoption_fixture(
        tmp_path,
        rows_per_day=lambda index, day: [
            {
                "provider": "openai",
                "provider_display_name": "OpenAI",
                "package_name": "openai",
                "package_type": "sdk",
                "package_category": "core_sdk",
                "with_mirrors": False,
                "download_date": day,
                "downloads": 1000 + index * 10,
                "source_url": "https://pypistats.org/packages/openai",
                "scraped_at": "2026-04-29T00:00:00Z",
                "source_run_id": "run-001",
            },
            {
                "provider": "openai",
                "provider_display_name": "OpenAI",
                "package_name": "openai",
                "package_type": "sdk",
                "package_category": "core_sdk",
                "with_mirrors": True,
                "download_date": day,
                "downloads": 1500 + index * 10,
                "source_url": "https://pypistats.org/packages/openai",
                "scraped_at": "2026-04-29T00:00:00Z",
                "source_run_id": "run-001",
            },
        ],
    )

    result = SignalLayerPipeline(tmp_path).build(sources=["provider_adoption"])
    metric_signals = _read_metric_signals(tmp_path, result)

    assert len(metric_signals) == 1
    assert metric_signals.loc[0, "quality_state"] == "valid"


def test_pipeline_build_provider_adoption_signals_handles_null_entity_values_in_quality_checks(
    tmp_path: Path,
) -> None:
    _write_provider_adoption_fixture(
        tmp_path,
        rows_per_day=lambda index, day: _null_package_rows(index, day),
    )

    result = SignalLayerPipeline(tmp_path).build(sources=["provider_adoption"])
    metric_signals = _read_metric_signals(tmp_path, result)

    assert len(metric_signals) == 1
    assert metric_signals.loc[0, "quality_state"] == "duplicate_grain"
    assert "duplicate_count=1" in metric_signals.loc[0, "quality_issues"]


def test_pipeline_build_defaults_to_implemented_registry_sources(tmp_path: Path) -> None:
    _write_provider_adoption_fixture(tmp_path)

    result = SignalLayerPipeline(tmp_path).build()
    metric_signals = _read_metric_signals(tmp_path, result)

    assert len(metric_signals) == 1
    assert metric_signals.loc[0, "metric_id"] == "pypi_openai_downloads_28d_growth"


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
        env=_cli_env(),
        text=True,
    )

    assert "metrics: 1" in result.stdout
    assert "asset_mappings: 1" in result.stdout


def test_cli_build_accepts_natural_subcommand_argument_order(tmp_path: Path) -> None:
    _write_reference_registries(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "signal_layer.cli",
            "build",
            "--base-dir",
            str(tmp_path),
            "--sources",
            "provider_adoption",
        ],
        check=True,
        capture_output=True,
        env=_cli_env(),
        text=True,
    )

    assert "run_id=" in result.stdout
    run_id = next(
        line.removeprefix("run_id=")
        for line in result.stdout.splitlines()
        if line.startswith("run_id=")
    )
    assert f"output_dir={tmp_path / 'data' / 'processed' / 'signals' / run_id}" in result.stdout
    assert (
        tmp_path / "data" / "processed" / "signals" / "latest" / "latest_signal_run.json"
    ).exists()


def _cli_env() -> dict[str, str]:
    env = dict(os.environ)
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src_path if not existing else f"{src_path}{os.pathsep}{existing}"
    return env


def _read_metric_signals(base_dir: Path, result) -> pd.DataFrame:
    metric_signals_path = Path(result.output_dir) / "metric_signals.parquet"
    if not metric_signals_path.exists():
        metric_signals_path = (
            base_dir / "data" / "processed" / "signals" / "latest" / "metric_signals.parquet"
        )
    return pd.read_parquet(metric_signals_path)


def _write_provider_adoption_fixture(
    base_dir: Path,
    *,
    rows_per_day=None,
) -> None:
    reference_dir = base_dir / "data" / "reference" / "signal_layer"
    reference_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "metric_id": "pypi_openai_downloads_28d_growth",
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
                "min_baseline_observations": 1,
                "max_freshness_lag_days": 365,
                "min_coverage_ratio": "",
                "description": "OpenAI PyPI downloads 28-day growth.",
                "caveats": "",
            }
        ]
    ).to_csv(reference_dir / "signal_metric_registry.csv", index=False)
    pd.DataFrame(
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
                "notes": "OpenAI ecosystem proxy.",
            }
        ]
    ).to_csv(reference_dir / "signal_asset_mapping.csv", index=False)

    normalized_dir = base_dir / "data" / "normalized" / "provider_adoption"
    normalized_dir.mkdir(parents=True)
    if rows_per_day is None:
        rows = [
            {
                "provider": "openai",
                "provider_display_name": "OpenAI",
                "package_name": "openai",
                "package_type": "sdk",
                "package_category": "core_sdk",
                "with_mirrors": False,
                "download_date": (pd.Timestamp("2026-03-01") + pd.Timedelta(days=index)).date().isoformat(),
                "downloads": 1000 + index * 10,
                "source_url": "https://pypistats.org/packages/openai",
                "scraped_at": "2026-04-29T00:00:00Z",
                "source_run_id": "run-001",
            }
            for index in range(60)
        ]
    else:
        rows = []
        for index in range(60):
            day = (pd.Timestamp("2026-03-01") + pd.Timedelta(days=index)).date().isoformat()
            generated = rows_per_day(index, day)
            if isinstance(generated, list):
                rows.extend(generated)
            else:
                rows.append(generated)
    pd.DataFrame(rows).to_parquet(normalized_dir / "pypi_downloads_daily.parquet", index=False)


def _null_package_rows(index: int, day: str) -> list[dict[str, object]]:
    row = {
        "provider": "openai",
        "provider_display_name": "OpenAI",
        "package_name": None,
        "package_type": "sdk",
        "package_category": "core_sdk",
        "with_mirrors": False,
        "download_date": day,
        "downloads": 1000 + index * 10,
        "source_url": "https://pypistats.org/packages/openai",
        "scraped_at": "2026-04-29T00:00:00Z",
        "source_run_id": "run-001",
    }
    return [row, row.copy()] if index == 10 else [row]


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
