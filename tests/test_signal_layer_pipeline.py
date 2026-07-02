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


def test_pipeline_build_semiconductor_signals(tmp_path: Path) -> None:
    _write_semiconductor_fixture(tmp_path)

    result = SignalLayerPipeline(tmp_path).build(sources=["semiconductor"])
    metric_signals = _read_metric_signals(tmp_path, result)

    assert sorted(metric_signals["metric_id"].tolist()) == [
        "fred_memory_ppi_yoy",
        "tw_tsmc_revenue_yoy",
    ]

    tsmc_signal = metric_signals.loc[metric_signals["metric_id"] == "tw_tsmc_revenue_yoy"].iloc[0]
    assert tsmc_signal["as_of_date"] == "2026-03-01"
    assert tsmc_signal["entity_key"] == "2330"
    assert tsmc_signal["entity_name"] == "TSMC"
    assert tsmc_signal["yoy_change"] == 200.0
    assert tsmc_signal["quality_state"] == "valid"

    memory_signal = metric_signals.loc[metric_signals["metric_id"] == "fred_memory_ppi_yoy"].iloc[0]
    assert memory_signal["as_of_date"] == "2026-03-01"
    assert memory_signal["entity_key"] == "WPU117909"
    assert memory_signal["entity_name"] == "Memory chip PPI"
    assert memory_signal["yoy_change"] == 50.0
    assert memory_signal["quality_state"] == "valid"


def test_pipeline_build_defaults_to_implemented_registry_sources(tmp_path: Path) -> None:
    _write_provider_adoption_fixture(tmp_path)

    result = SignalLayerPipeline(tmp_path).build()
    metric_signals = _read_metric_signals(tmp_path, result)

    assert len(metric_signals) == 1
    assert metric_signals.loc[0, "metric_id"] == "pypi_openai_downloads_28d_growth"


def test_pipeline_build_semiconductor_signals(tmp_path: Path) -> None:
    _write_semiconductor_fixture(tmp_path)

    result = SignalLayerPipeline(tmp_path).build(sources=["semiconductor"])
    metric_signals = _read_metric_signals(tmp_path, result)

    assert result.datasets_written["metric_signals"] == 1
    assert len(metric_signals) == 1
    assert metric_signals.loc[0, "metric_id"] == "tw_tsmc_revenue_yoy"
    assert metric_signals.loc[0, "entity_key"] == "2330"
    assert metric_signals.loc[0, "entity_name"] == "TSMC"
    assert metric_signals.loc[0, "quality_state"] == "valid"
    assert metric_signals.loc[0, "yoy_change"] > 0


def test_pipeline_build_openrouter_signals(tmp_path: Path) -> None:
    _write_openrouter_fixture(tmp_path)

    result = SignalLayerPipeline(tmp_path).build(sources=["openrouter"])
    metric_signals = _read_metric_signals(tmp_path, result)

    assert result.datasets_written["metric_signals"] == 1
    assert len(metric_signals) == 1
    assert metric_signals.loc[0, "metric_id"] == "openrouter_anthropic_tokens_28d_growth"
    assert metric_signals.loc[0, "entity_key"] == "anthropic"
    assert metric_signals.loc[0, "entity_name"] == "Anthropic"
    assert metric_signals.loc[0, "quality_state"] == "valid"
    assert metric_signals.loc[0, "rolling_change"] > 0


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


def _write_semiconductor_fixture(base_dir: Path) -> None:
    reference_dir = base_dir / "data" / "reference" / "signal_layer"
    reference_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "metric_id": "tw_tsmc_revenue_yoy",
                "source": "semiconductor",
                "dataset_id": "tw_monthly_revenue",
                "date_column": "revenue_month",
                "value_column": "monthly_revenue_ntd",
                "entity_columns": "company_code",
                "cadence": "monthly",
                "transform": "yoy_growth",
                "baseline_method": "robust_z",
                "baseline_window": "36M",
                "seasonality_mode": "yoy",
                "higher_is_better": True,
                "default_metric_direction": "positive",
                "min_baseline_observations": 1,
                "max_freshness_lag_days": 365,
                "min_coverage_ratio": "",
                "description": "TSMC monthly revenue YoY.",
                "caveats": "Monthly revenue can be revised and should be interpreted with release lag.",
            },
            {
                "metric_id": "fred_memory_ppi_yoy",
                "source": "semiconductor",
                "dataset_id": "fred_semiconductor_ppi",
                "date_column": "date",
                "value_column": "value",
                "entity_columns": "series_id",
                "cadence": "monthly",
                "transform": "yoy_growth",
                "baseline_method": "robust_z",
                "baseline_window": "36M",
                "seasonality_mode": "yoy",
                "higher_is_better": True,
                "default_metric_direction": "positive",
                "min_baseline_observations": 1,
                "max_freshness_lag_days": 365,
                "min_coverage_ratio": "",
                "description": "Memory chip producer price index YoY.",
                "caveats": "FRED PPI is a pricing proxy and not a direct revenue metric.",
            },
        ]
    ).to_csv(reference_dir / "signal_metric_registry.csv", index=False)
    pd.DataFrame(
        [
            {
                "metric_id": "tw_tsmc_revenue_yoy",
                "ticker": "TSM",
                "company_name": "Taiwan Semiconductor Manufacturing Company",
                "asset_type": "equity",
                "theme": "semiconductor_supply_chain",
                "exposure_type": "direct",
                "expected_direction": "positive",
                "exposure_weight": 1.0,
                "lag_days": 0,
                "confidence": "high",
                "notes": "TSMC direct exposure.",
            },
            {
                "metric_id": "fred_memory_ppi_yoy",
                "ticker": "MU",
                "company_name": "Micron Technology",
                "asset_type": "equity",
                "theme": "semiconductor_memory",
                "exposure_type": "pricing_proxy",
                "expected_direction": "positive",
                "exposure_weight": 1.0,
                "lag_days": 0,
                "confidence": "medium",
                "notes": "Memory pricing proxy.",
            },
        ]
    ).to_csv(reference_dir / "signal_asset_mapping.csv", index=False)

    taiwan_dir = base_dir / "data" / "normalized" / "taiwan_semiconductor_revenue"
    taiwan_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "dataset_id": "tw_monthly_revenue",
                "company_code": "2330",
                "company_name": "TSMC",
                "market": "TWSE",
                "industry": "Semiconductor",
                "filing_date": "2025-01-10",
                "revenue_month": "2025-01",
                "monthly_revenue_ntd": 100.0,
                "mom_pct": 0.0,
                "yoy_pct": 0.0,
                "ytd_revenue_ntd": 100.0,
                "ytd_yoy_pct": 0.0,
                "source_url": "https://mops.twse.com.tw",
                "source_run_id": "run-001",
                "scraped_at": "2026-03-31T00:00:00Z",
            },
            {
                "dataset_id": "tw_monthly_revenue",
                "company_code": "2330",
                "company_name": "TSMC",
                "market": "TWSE",
                "industry": "Semiconductor",
                "filing_date": "2025-02-10",
                "revenue_month": "2025-02",
                "monthly_revenue_ntd": 100.0,
                "mom_pct": 0.0,
                "yoy_pct": 0.0,
                "ytd_revenue_ntd": 200.0,
                "ytd_yoy_pct": 0.0,
                "source_url": "https://mops.twse.com.tw",
                "source_run_id": "run-001",
                "scraped_at": "2026-03-31T00:00:00Z",
            },
            {
                "dataset_id": "tw_monthly_revenue",
                "company_code": "2330",
                "company_name": "TSMC",
                "market": "TWSE",
                "industry": "Semiconductor",
                "filing_date": "2025-03-10",
                "revenue_month": "2025-03",
                "monthly_revenue_ntd": 100.0,
                "mom_pct": 0.0,
                "yoy_pct": 0.0,
                "ytd_revenue_ntd": 300.0,
                "ytd_yoy_pct": 0.0,
                "source_url": "https://mops.twse.com.tw",
                "source_run_id": "run-001",
                "scraped_at": "2026-03-31T00:00:00Z",
            },
            {
                "dataset_id": "tw_monthly_revenue",
                "company_code": "2330",
                "company_name": "TSMC",
                "market": "TWSE",
                "industry": "Semiconductor",
                "filing_date": "2026-01-10",
                "revenue_month": "2026-01",
                "monthly_revenue_ntd": 200.0,
                "mom_pct": 0.0,
                "yoy_pct": 100.0,
                "ytd_revenue_ntd": 200.0,
                "ytd_yoy_pct": 100.0,
                "source_url": "https://mops.twse.com.tw",
                "source_run_id": "run-002",
                "scraped_at": "2026-03-31T00:00:00Z",
            },
            {
                "dataset_id": "tw_monthly_revenue",
                "company_code": "2330",
                "company_name": "TSMC",
                "market": "TWSE",
                "industry": "Semiconductor",
                "filing_date": "2026-02-10",
                "revenue_month": "2026-02",
                "monthly_revenue_ntd": 250.0,
                "mom_pct": 25.0,
                "yoy_pct": 150.0,
                "ytd_revenue_ntd": 450.0,
                "ytd_yoy_pct": 125.0,
                "source_url": "https://mops.twse.com.tw",
                "source_run_id": "run-002",
                "scraped_at": "2026-03-31T00:00:00Z",
            },
            {
                "dataset_id": "tw_monthly_revenue",
                "company_code": "2330",
                "company_name": "TSMC",
                "market": "TWSE",
                "industry": "Semiconductor",
                "filing_date": "2026-03-10",
                "revenue_month": "2026-03",
                "monthly_revenue_ntd": 300.0,
                "mom_pct": 20.0,
                "yoy_pct": 200.0,
                "ytd_revenue_ntd": 750.0,
                "ytd_yoy_pct": 150.0,
                "source_url": "https://mops.twse.com.tw",
                "source_run_id": "run-002",
                "scraped_at": "2026-03-31T00:00:00Z",
            },
        ]
    ).to_parquet(taiwan_dir / "tw_monthly_revenue.parquet", index=False)

    memory_dir = base_dir / "data" / "normalized" / "semiconductor_memory"
    memory_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "date": "2025-01-01",
                "series_id": "WPU117909",
                "series_name": "Memory chip PPI",
                "value": 100.0,
                "source_url": "https://fred.stlouisfed.org/series/WPU117909",
                "source_run_id": "run-101",
                "scraped_at": "2026-03-31T00:00:00Z",
            },
            {
                "date": "2025-02-01",
                "series_id": "WPU117909",
                "series_name": "Memory chip PPI",
                "value": 100.0,
                "source_url": "https://fred.stlouisfed.org/series/WPU117909",
                "source_run_id": "run-101",
                "scraped_at": "2026-03-31T00:00:00Z",
            },
            {
                "date": "2025-03-01",
                "series_id": "WPU117909",
                "series_name": "Memory chip PPI",
                "value": 100.0,
                "source_url": "https://fred.stlouisfed.org/series/WPU117909",
                "source_run_id": "run-101",
                "scraped_at": "2026-03-31T00:00:00Z",
            },
            {
                "date": "2026-01-01",
                "series_id": "WPU117909",
                "series_name": "Memory chip PPI",
                "value": 120.0,
                "source_url": "https://fred.stlouisfed.org/series/WPU117909",
                "source_run_id": "run-102",
                "scraped_at": "2026-03-31T00:00:00Z",
            },
            {
                "date": "2026-02-01",
                "series_id": "WPU117909",
                "series_name": "Memory chip PPI",
                "value": 130.0,
                "source_url": "https://fred.stlouisfed.org/series/WPU117909",
                "source_run_id": "run-102",
                "scraped_at": "2026-03-31T00:00:00Z",
            },
            {
                "date": "2026-03-01",
                "series_id": "WPU117909",
                "series_name": "Memory chip PPI",
                "value": 150.0,
                "source_url": "https://fred.stlouisfed.org/series/WPU117909",
                "source_run_id": "run-102",
                "scraped_at": "2026-03-31T00:00:00Z",
            },
        ]
    ).to_parquet(memory_dir / "fred_semiconductor_ppi.parquet", index=False)


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


def _write_semiconductor_fixture(base_dir: Path) -> None:
    reference_dir = base_dir / "data" / "reference" / "signal_layer"
    reference_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "metric_id": "tw_tsmc_revenue_yoy",
                "source": "semiconductor",
                "dataset_id": "tw_monthly_revenue",
                "date_column": "revenue_month",
                "value_column": "monthly_revenue_ntd",
                "entity_columns": "company_code",
                "cadence": "monthly",
                "transform": "yoy_growth",
                "baseline_method": "robust_z",
                "baseline_window": "36M",
                "seasonality_mode": "same_month",
                "higher_is_better": True,
                "default_metric_direction": "positive",
                "min_baseline_observations": 24,
                "max_freshness_lag_days": 120,
                "min_coverage_ratio": "",
                "description": "TSMC monthly revenue YoY growth.",
                "caveats": "Monthly revenue can be revised.",
            }
        ]
    ).to_csv(reference_dir / "signal_metric_registry.csv", index=False)
    pd.DataFrame(
        [
            {
                "metric_id": "tw_tsmc_revenue_yoy",
                "ticker": "TSM",
                "company_name": "Taiwan Semiconductor Manufacturing",
                "asset_type": "equity",
                "theme": "foundry_cycle",
                "exposure_type": "direct_revenue_proxy",
                "expected_direction": "positive",
                "exposure_weight": 1.0,
                "lag_days": 0,
                "confidence": "high",
                "notes": "Monthly revenue is a direct company operating proxy.",
            }
        ]
    ).to_csv(reference_dir / "signal_asset_mapping.csv", index=False)

    normalized_dir = base_dir / "data" / "normalized" / "taiwan_semiconductor_revenue"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for month in pd.date_range("2023-01-01", periods=40, freq="MS"):
        month_number = month.month
        base_value = 100_000_000 + month_number * 1_000_000
        if month.year == 2024:
            value = base_value * 1.08
        elif month.year == 2025:
            value = base_value * 1.18
        elif month.year == 2026:
            value = base_value * 1.35
        else:
            value = base_value
        rows.append(
            {
                "dataset_id": "tw_monthly_revenue",
                "company_code": "2330",
                "company_name": "TSMC",
                "filing_date": "2026-05-10",
                "revenue_month": month.strftime("%Y-%m"),
                "monthly_revenue_ntd": float(value),
                "source_url": "https://mops.twse.com.tw/mops/api/t05st10_ifrs",
                "source_run_id": "run-001",
                "scraped_at": "2026-05-10T00:00:00Z",
            }
        )
    pd.DataFrame(rows).to_parquet(normalized_dir / "tw_monthly_revenue.parquet", index=False)


def _write_openrouter_fixture(base_dir: Path) -> None:
    reference_dir = base_dir / "data" / "reference" / "signal_layer"
    reference_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "metric_id": "openrouter_anthropic_tokens_28d_growth",
                "source": "openrouter",
                "dataset_id": "daily_provider_economics",
                "date_column": "usage_date",
                "value_column": "total_tokens",
                "entity_columns": "provider_slug",
                "cadence": "daily",
                "transform": "rolling_growth",
                "baseline_method": "robust_z",
                "baseline_window": "90D",
                "seasonality_mode": "none",
                "higher_is_better": True,
                "default_metric_direction": "positive",
                "min_baseline_observations": 30,
                "max_freshness_lag_days": 120,
                "min_coverage_ratio": "",
                "description": "Anthropic OpenRouter total-token 28-day growth.",
                "caveats": "Provider-level token metric avoids task-spend snapshots.",
            }
        ]
    ).to_csv(reference_dir / "signal_metric_registry.csv", index=False)
    pd.DataFrame(
        [
            {
                "metric_id": "openrouter_anthropic_tokens_28d_growth",
                "ticker": "AMZN",
                "company_name": "Amazon",
                "asset_type": "equity",
                "theme": "ai_model_adoption",
                "exposure_type": "ecosystem_adoption",
                "expected_direction": "positive",
                "exposure_weight": 0.7,
                "lag_days": 0,
                "confidence": "low",
                "notes": "Anthropic usage can be an indirect AI demand read-through.",
            }
        ]
    ).to_csv(reference_dir / "signal_asset_mapping.csv", index=False)

    normalized_dir = base_dir / "data" / "normalized" / "marts"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, day in enumerate(pd.date_range("2026-03-01", periods=140, freq="D")):
        rows.append(
            {
                "usage_date": day.strftime("%Y-%m-%d"),
                "provider_slug": "anthropic",
                "provider_name": "Anthropic",
                "model_permaslug": "anthropic/claude-all",
                "total_tokens": float(1_000_000 + index * 20_000),
            }
        )
        rows.append(
            {
                "usage_date": day.strftime("%Y-%m-%d"),
                "provider_slug": "anthropic",
                "provider_name": "Anthropic",
                "model_permaslug": "anthropic/claude-secondary",
                "total_tokens": float(500_000 + index * 10_000),
            }
        )
    pd.DataFrame(rows).to_parquet(normalized_dir / "daily_provider_economics.parquet", index=False)
