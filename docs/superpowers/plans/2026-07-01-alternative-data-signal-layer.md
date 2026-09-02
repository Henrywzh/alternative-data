# Alternative Data Signal Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v1 signal layer that turns selected normalized alternative-data tables into quality-gated metric signals, then maps valid evidence to stock and theme signals.

**Architecture:** Add a new `signal_layer` package with typed records, reference registries, canonicalization and eligibility gates, statistical baseline helpers, source-specific builders, aggregation, storage, and CLI entrypoints. Metric signals are the source of truth; asset and theme signals are derived outputs that include quality caveats and do not treat combined statistics as formal independent p-values.

**Tech Stack:** Python 3.11, pandas, pyarrow/parquet, argparse, dataclasses, pytest.

---

## File Structure

Create:
- `src/signal_layer/__init__.py`: package marker.
- `src/signal_layer/models.py`: dataclasses, enums, constants, column lists.
- `src/signal_layer/registry.py`: load and validate metric and asset mapping CSV files.
- `src/signal_layer/quality.py`: canonicalization and metric eligibility gates.
- `src/signal_layer/transforms.py`: transform calculations and statistical baseline helpers.
- `src/signal_layer/builders/__init__.py`: builder package marker.
- `src/signal_layer/builders/provider_adoption.py`: first source builder for PyPI/npm/GitHub/Hugging Face/provider momentum.
- `src/signal_layer/builders/semiconductor.py`: first source builder for Taiwan revenue, official semiconductor series, and FRED memory PPI.
- `src/signal_layer/builders/openrouter.py`: conservative OpenRouter provider-token growth builder from `daily_provider_economics`.
- `src/signal_layer/builders/minerals.py`: conservative mineral price momentum builder from live tungsten/molybdenum price tables.
- `src/signal_layer/aggregation.py`: asset and theme aggregation.
- `src/signal_layer/storage.py`: read/write CSV and parquet outputs.
- `src/signal_layer/pipeline.py`: orchestration across registry, builders, aggregation, storage.
- `src/signal_layer/cli.py`: `signal-layer` command.
- `tests/test_signal_layer_registry.py`: registry validation tests.
- `tests/test_signal_layer_quality.py`: canonicalization and eligibility tests.
- `tests/test_signal_layer_transforms.py`: transform/statistical tests.
- `tests/test_signal_layer_aggregation.py`: asset/theme aggregation tests.
- `tests/test_signal_layer_pipeline.py`: end-to-end fixture pipeline tests.
- `data/reference/signal_layer/signal_metric_registry.csv`: initial metric definitions.
- `data/reference/signal_layer/signal_asset_mapping.csv`: initial metric-to-asset mappings.

Modify:
- `pyproject.toml`: add `signal-layer = "signal_layer.cli:main"`.

Read but do not modify unless implementation reveals a narrow need:
- `docs/superpowers/specs/2026-07-01-alternative-data-signal-layer-design.md`
- `src/provider_adoption_data/storage.py`
- `src/semiconductor_memory_data/storage.py`
- `src/minerals_signal_data/storage.py`
- existing tests under `tests/` for local style.

---

### Task 1: Models And Registry Validation

**Files:**
- Create: `src/signal_layer/__init__.py`
- Create: `src/signal_layer/models.py`
- Create: `src/signal_layer/registry.py`
- Create: `tests/test_signal_layer_registry.py`
- Create: `data/reference/signal_layer/signal_metric_registry.csv`
- Create: `data/reference/signal_layer/signal_asset_mapping.csv`

- [ ] **Step 1: Write failing registry tests**

Create `tests/test_signal_layer_registry.py`:

```python
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
                "max_freshness_lag_days": 120,
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
pytest tests/test_signal_layer_registry.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'signal_layer'`.

- [ ] **Step 3: Add model constants and registry implementation**

Create `src/signal_layer/__init__.py`:

```python
"""Signal layer package for alternative-data research outputs."""
```

Create `src/signal_layer/models.py`:

```python
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


METRIC_REGISTRY_COLUMNS = [
    "metric_id",
    "source",
    "dataset_id",
    "date_column",
    "value_column",
    "entity_columns",
    "cadence",
    "transform",
    "baseline_method",
    "baseline_window",
    "seasonality_mode",
    "higher_is_better",
    "default_metric_direction",
    "min_baseline_observations",
    "max_freshness_lag_days",
    "min_coverage_ratio",
    "description",
    "caveats",
]

ASSET_MAPPING_COLUMNS = [
    "metric_id",
    "ticker",
    "company_name",
    "asset_type",
    "theme",
    "exposure_type",
    "expected_direction",
    "exposure_weight",
    "lag_days",
    "confidence",
    "notes",
]

METRIC_SIGNAL_COLUMNS = [
    "metric_id",
    "source",
    "as_of_date",
    "entity_key",
    "entity_name",
    "latest_value",
    "comparison_value",
    "raw_change",
    "pct_change",
    "yoy_change",
    "rolling_change",
    "z_score",
    "robust_z_score",
    "percentile",
    "rank",
    "rank_change",
    "baseline_value",
    "baseline_method",
    "baseline_window",
    "baseline_observation_count",
    "empirical_percentile",
    "tail_probability",
    "effect_size",
    "signed_stat",
    "metric_direction",
    "signal_state",
    "confidence",
    "source_updated_at",
    "quality_state",
    "quality_issues",
    "caveats",
]

ASSET_SIGNAL_COLUMNS = [
    "ticker",
    "company_name",
    "asset_type",
    "as_of_date",
    "theme",
    "combined_signed_stat",
    "combined_tail_probability",
    "median_signed_stat",
    "positive_evidence_count",
    "negative_evidence_count",
    "bullish_metric_count",
    "bearish_metric_count",
    "neutral_metric_count",
    "top_metric_id",
    "top_metric_description",
    "driver_count",
    "valid_driver_count",
    "non_valid_driver_count",
    "quality_issues",
    "signal_state",
    "confidence",
    "summary",
]

THEME_SIGNAL_COLUMNS = [
    "theme",
    "as_of_date",
    "combined_signed_stat",
    "combined_tail_probability",
    "median_signed_stat",
    "positive_evidence_count",
    "negative_evidence_count",
    "active_metric_count",
    "active_asset_count",
    "top_metric_id",
    "top_ticker",
    "signal_state",
    "confidence",
    "summary",
]

ALLOWED_DIRECTIONS = {"positive", "negative", "ambiguous"}
ALLOWED_EXPECTED_DIRECTIONS = {"positive", "negative"}
ALLOWED_SIGNAL_STATES = {"bullish", "bearish", "neutral", "watch"}
ALLOWED_QUALITY_STATES = {
    "valid",
    "insufficient_history",
    "stale",
    "duplicate_grain",
    "low_coverage",
    "invalid_values",
    "partial_period",
    "unvalidated_source",
}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}


@dataclass(frozen=True)
class PipelineResult:
    run_id: str
    datasets_written: dict[str, int]
    output_dir: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

Create `src/signal_layer/registry.py`:

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd

from signal_layer.models import (
    ALLOWED_CONFIDENCE,
    ALLOWED_DIRECTIONS,
    ALLOWED_EXPECTED_DIRECTIONS,
    ASSET_MAPPING_COLUMNS,
    METRIC_REGISTRY_COLUMNS,
)


class RegistryValidationError(ValueError):
    """Raised when signal-layer reference registries are invalid."""


def reference_dir(base_dir: str | Path) -> Path:
    return Path(base_dir) / "data" / "reference" / "signal_layer"


def load_registries(base_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    root = reference_dir(base_dir)
    metrics_path = root / "signal_metric_registry.csv"
    mappings_path = root / "signal_asset_mapping.csv"
    metrics = pd.read_csv(metrics_path)
    mappings = pd.read_csv(mappings_path)
    validate_registries(metrics, mappings)
    return _coerce_metrics(metrics), _coerce_mappings(mappings)


def validate_registries(metrics: pd.DataFrame, mappings: pd.DataFrame) -> None:
    _require_columns(metrics, METRIC_REGISTRY_COLUMNS, "signal_metric_registry")
    _require_columns(mappings, ASSET_MAPPING_COLUMNS, "signal_asset_mapping")

    duplicated_metrics = metrics.loc[metrics["metric_id"].duplicated(), "metric_id"].dropna().unique().tolist()
    if duplicated_metrics:
        raise RegistryValidationError(f"duplicate metric_id values: {duplicated_metrics}")

    unknown_metrics = sorted(set(mappings["metric_id"].dropna()) - set(metrics["metric_id"].dropna()))
    if unknown_metrics:
        raise RegistryValidationError(f"mapping references unknown metric_id values: {unknown_metrics}")

    bad_directions = sorted(set(metrics["default_metric_direction"].dropna().str.lower()) - ALLOWED_DIRECTIONS)
    if bad_directions:
        raise RegistryValidationError(f"invalid default_metric_direction values: {bad_directions}")

    bad_expected = sorted(set(mappings["expected_direction"].dropna().str.lower()) - ALLOWED_EXPECTED_DIRECTIONS)
    if bad_expected:
        raise RegistryValidationError(f"invalid expected_direction values: {bad_expected}")

    bad_confidence = sorted(set(mappings["confidence"].dropna().str.lower()) - ALLOWED_CONFIDENCE)
    if bad_confidence:
        raise RegistryValidationError(f"invalid confidence values: {bad_confidence}")

    weights = pd.to_numeric(mappings["exposure_weight"], errors="coerce")
    if weights.isna().any() or (weights <= 0).any():
        raise RegistryValidationError("exposure_weight must be positive numeric values")


def _require_columns(frame: pd.DataFrame, required: list[str], name: str) -> None:
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RegistryValidationError(f"{name} missing required columns: {missing}")


def _coerce_metrics(metrics: pd.DataFrame) -> pd.DataFrame:
    frame = metrics.copy()
    frame["higher_is_better"] = frame["higher_is_better"].map(
        lambda value: str(value).strip().lower() in {"true", "1", "yes"}
    )
    frame["min_baseline_observations"] = pd.to_numeric(frame["min_baseline_observations"], errors="coerce").astype("Int64")
    frame["max_freshness_lag_days"] = pd.to_numeric(frame["max_freshness_lag_days"], errors="coerce").astype("Int64")
    frame["min_coverage_ratio"] = pd.to_numeric(frame["min_coverage_ratio"], errors="coerce")
    return frame


def _coerce_mappings(mappings: pd.DataFrame) -> pd.DataFrame:
    frame = mappings.copy()
    frame["exposure_weight"] = pd.to_numeric(frame["exposure_weight"], errors="coerce")
    frame["lag_days"] = pd.to_numeric(frame["lag_days"], errors="coerce").fillna(0).astype(int)
    return frame
```

- [ ] **Step 4: Add initial reference CSVs**

Create `data/reference/signal_layer/signal_metric_registry.csv`:

```csv
metric_id,source,dataset_id,date_column,value_column,entity_columns,cadence,transform,baseline_method,baseline_window,seasonality_mode,higher_is_better,default_metric_direction,min_baseline_observations,max_freshness_lag_days,min_coverage_ratio,description,caveats
pypi_openai_downloads_28d_growth,provider_adoption,pypi_downloads_daily,download_date,downloads,provider|package_name|with_mirrors,daily,rolling_growth,robust_z,90D,none,true,positive,30,7,,OpenAI PyPI download 28-day growth,Package downloads include non-production usage.
npm_anthropic_downloads_28d_growth,provider_adoption,npm_downloads_daily,download_date,downloads,provider|package_name,daily,rolling_growth,robust_z,90D,none,true,positive,30,7,,Anthropic npm package download 28-day growth,npm rows require canonicalization because older uncategorized rows can overlap with categorized rows.
openrouter_anthropic_tokens_28d_growth,openrouter,daily_provider_economics,usage_date,total_tokens,provider_slug,daily,rolling_growth,robust_z,90D,none,true,positive,30,10,,Anthropic OpenRouter total-token 28-day growth,OpenRouter token history is uneven by provider/model; this provider-level metric avoids task-spend snapshots until more history exists.
tw_tsmc_revenue_yoy,semiconductor,tw_monthly_revenue,revenue_month,monthly_revenue_ntd,company_code,monthly,yoy_growth,robust_z,36M,same_month,true,positive,36,45,,TSMC monthly revenue YoY growth,Monthly revenue can be revised and should be interpreted with release lag.
fred_memory_ppi_yoy,semiconductor,fred_semiconductor_ppi,date,value,series_id,monthly,yoy_growth,robust_z,36M,same_month,true,positive,36,75,,FRED semiconductor PPI YoY growth,FRED PPI is a pricing proxy and not a direct revenue metric.
tungsten_apt_13w_momentum,minerals,tungsten_price_daily,date,apt,commodity,daily,rolling_growth,robust_z,52W,none,true,positive,60,10,,China tungsten APT 13-week momentum,Producer-positive signal; downstream consumer mappings should use negative expected direction.
```

Create `data/reference/signal_layer/signal_asset_mapping.csv`:

```csv
metric_id,ticker,company_name,asset_type,theme,exposure_type,expected_direction,exposure_weight,lag_days,confidence,notes
pypi_openai_downloads_28d_growth,MSFT,Microsoft,equity,developer_ecosystem,ecosystem_adoption,positive,1.0,0,medium,Microsoft has economic exposure to OpenAI adoption.
npm_anthropic_downloads_28d_growth,AMZN,Amazon,equity,developer_ecosystem,ecosystem_adoption,positive,0.7,0,low,Anthropic adoption can be an indirect AWS demand signal.
openrouter_anthropic_tokens_28d_growth,AMZN,Amazon,equity,ai_model_adoption,ecosystem_adoption,positive,0.7,0,low,Anthropic usage on OpenRouter can be an indirect AI adoption and infrastructure demand read-through.
tw_tsmc_revenue_yoy,TSM,Taiwan Semiconductor Manufacturing,equity,foundry_cycle,direct_revenue_proxy,positive,1.0,0,high,Monthly revenue is a direct company operating proxy.
fred_memory_ppi_yoy,MU,Micron Technology,equity,memory_cycle,macro_cycle_proxy,positive,0.8,30,medium,Memory PPI improvement can proxy memory pricing cycle strength.
tungsten_apt_13w_momentum,600549.SH,Xiamen Tungsten,equity,critical_minerals,direct_revenue_proxy,positive,1.0,0,medium,Tungsten price momentum can be positive for tungsten producers.
```

- [ ] **Step 5: Run tests and verify they pass**

Run:

```bash
pytest tests/test_signal_layer_registry.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/signal_layer/__init__.py src/signal_layer/models.py src/signal_layer/registry.py tests/test_signal_layer_registry.py data/reference/signal_layer/signal_metric_registry.csv data/reference/signal_layer/signal_asset_mapping.csv
git commit -m "feat: add signal layer registries"
```

---

### Task 2: Quality Gates And Canonicalization

**Files:**
- Create: `src/signal_layer/quality.py`
- Create: `tests/test_signal_layer_quality.py`
- Modify: `src/signal_layer/models.py`

- [ ] **Step 1: Write failing quality tests**

Create `tests/test_signal_layer_quality.py`:

```python
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
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
pytest tests/test_signal_layer_quality.py -v
```

Expected: FAIL with `ModuleNotFoundError` or `ImportError` for `signal_layer.quality`.

- [ ] **Step 3: Implement quality helpers**

Create `src/signal_layer/quality.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


@dataclass(frozen=True)
class QualityResult:
    quality_state: str
    quality_issues: str


def canonicalize_latest(
    frame: pd.DataFrame,
    *,
    grain: list[str],
    prefer_non_null: Iterable[str] = (),
    run_id_column: str = "source_run_id",
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    working = frame.copy()
    working["_row_order"] = range(len(working))
    for column in prefer_non_null:
        working[f"_has_{column}"] = working[column].notna().astype(int) if column in working.columns else 0
    if run_id_column in working.columns:
        working["_run_order"] = working[run_id_column].astype("string").fillna("")
    else:
        working["_run_order"] = ""

    sort_columns = [f"_has_{column}" for column in prefer_non_null] + ["_run_order", "_row_order"]
    working = working.sort_values(sort_columns)
    result = working.drop_duplicates(subset=grain, keep="last")
    helper_columns = [column for column in result.columns if column.startswith("_has_")] + ["_run_order", "_row_order"]
    return result.drop(columns=helper_columns).reset_index(drop=True)


def duplicate_count(frame: pd.DataFrame, grain: list[str]) -> int:
    if frame.empty:
        return 0
    return int(frame.duplicated(grain).sum())


def evaluate_metric_quality(
    *,
    baseline_observation_count: int,
    min_baseline_observations: int,
    latest_date: pd.Timestamp | None,
    run_date: pd.Timestamp,
    max_freshness_lag_days: int | None,
    invalid_value_count: int,
    duplicate_count: int,
    coverage_ratio: float | None,
    min_coverage_ratio: float | None,
    partial_period: bool,
    source_validated: bool,
) -> QualityResult:
    issues: list[str] = []

    if duplicate_count > 0:
        issues.append(f"duplicate_count={duplicate_count}")
        return QualityResult("duplicate_grain", "; ".join(issues))

    if invalid_value_count > 0:
        issues.append(f"invalid_value_count={invalid_value_count}")
        return QualityResult("invalid_values", "; ".join(issues))

    if not source_validated:
        issues.append("source_validated=false")
        return QualityResult("unvalidated_source", "; ".join(issues))

    if partial_period:
        issues.append("partial_period=true")
        return QualityResult("partial_period", "; ".join(issues))

    if latest_date is not None and max_freshness_lag_days is not None:
        lag_days = int((run_date.normalize() - latest_date.normalize()).days)
        if lag_days > max_freshness_lag_days:
            issues.append(f"freshness_lag_days={lag_days} above max_freshness_lag_days={max_freshness_lag_days}")
            return QualityResult("stale", "; ".join(issues))

    if baseline_observation_count < min_baseline_observations:
        issues.append(
            f"baseline_observation_count={baseline_observation_count} "
            f"below min_baseline_observations={min_baseline_observations}"
        )
        return QualityResult("insufficient_history", "; ".join(issues))

    if coverage_ratio is not None and min_coverage_ratio is not None and coverage_ratio < min_coverage_ratio:
        issues.append(f"coverage_ratio={coverage_ratio:.3f} below min_coverage_ratio={min_coverage_ratio:.3f}")
        return QualityResult("low_coverage", "; ".join(issues))

    return QualityResult("valid", "")
```

- [ ] **Step 4: Run quality tests and registry tests**

Run:

```bash
pytest tests/test_signal_layer_quality.py tests/test_signal_layer_registry.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/signal_layer/quality.py tests/test_signal_layer_quality.py
git commit -m "feat: add signal quality gates"
```

---

### Task 3: Statistical Transform Helpers

**Files:**
- Create: `src/signal_layer/transforms.py`
- Create: `tests/test_signal_layer_transforms.py`

- [ ] **Step 1: Write failing transform tests**

Create `tests/test_signal_layer_transforms.py`:

```python
from __future__ import annotations

import math

import pandas as pd

from signal_layer.transforms import (
    calculate_rolling_growth,
    calculate_yoy_growth,
    empirical_tail_probability,
    robust_z_score,
    summarize_latest_signal,
)


def test_calculate_yoy_growth_uses_same_month_prior_year() -> None:
    series = pd.Series(
        [100.0, 120.0, 150.0],
        index=pd.to_datetime(["2025-05-01", "2026-04-01", "2026-05-01"]),
    )

    result = calculate_yoy_growth(series)

    assert math.isclose(result.loc[pd.Timestamp("2026-05-01")], 50.0)


def test_calculate_rolling_growth_compares_latest_to_prior_window_average() -> None:
    series = pd.Series(
        [100.0, 100.0, 100.0, 120.0, 120.0, 120.0],
        index=pd.date_range("2026-01-01", periods=6, freq="D"),
    )

    result = calculate_rolling_growth(series, window=3)

    assert math.isclose(result.iloc[-1], 20.0)


def test_robust_z_score_uses_median_and_mad() -> None:
    baseline = pd.Series([10.0, 11.0, 12.0, 13.0, 100.0])

    result = robust_z_score(15.0, baseline)

    assert result > 0
    assert result < 3


def test_empirical_tail_probability_is_two_sided() -> None:
    baseline = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])

    assert empirical_tail_probability(5.0, baseline) == 0.4


def test_summarize_latest_signal_returns_watch_for_invalid_quality() -> None:
    result = summarize_latest_signal(
        latest_value=150.0,
        transformed_value=50.0,
        baseline_values=pd.Series([1.0, 2.0, 3.0]),
        baseline_method="robust_z",
        baseline_window="90D",
        metric_direction="positive",
        quality_state="insufficient_history",
    )

    assert result["signal_state"] == "watch"
    assert result["signed_stat"] > 0
    assert result["baseline_observation_count"] == 3
```

- [ ] **Step 2: Run transform tests and verify they fail**

Run:

```bash
pytest tests/test_signal_layer_transforms.py -v
```

Expected: FAIL with `ImportError` for `signal_layer.transforms`.

- [ ] **Step 3: Implement transform helpers**

Create `src/signal_layer/transforms.py`:

```python
from __future__ import annotations

import math

import pandas as pd


def calculate_yoy_growth(series: pd.Series) -> pd.Series:
    ordered = _numeric_time_series(series)
    prior = ordered.shift(12)
    return ((ordered / prior) - 1.0) * 100.0


def calculate_rolling_growth(series: pd.Series, *, window: int) -> pd.Series:
    ordered = _numeric_time_series(series)
    prior_average = ordered.shift(window).rolling(window=window, min_periods=window).mean()
    return ((ordered / prior_average) - 1.0) * 100.0


def robust_z_score(value: float, baseline: pd.Series) -> float:
    clean = pd.to_numeric(baseline, errors="coerce").dropna()
    if clean.empty or pd.isna(value):
        return float("nan")
    median = float(clean.median())
    mad = float((clean - median).abs().median())
    if mad == 0:
        std = float(clean.std(ddof=0))
        return float("nan") if std == 0 else (float(value) - median) / std
    return 0.6745 * (float(value) - median) / mad


def standard_z_score(value: float, baseline: pd.Series) -> float:
    clean = pd.to_numeric(baseline, errors="coerce").dropna()
    if clean.empty or pd.isna(value):
        return float("nan")
    std = float(clean.std(ddof=0))
    if std == 0:
        return float("nan")
    return (float(value) - float(clean.mean())) / std


def empirical_percentile(value: float, baseline: pd.Series) -> float:
    clean = pd.to_numeric(baseline, errors="coerce").dropna()
    if clean.empty or pd.isna(value):
        return float("nan")
    return float((clean <= float(value)).mean() * 100.0)


def empirical_tail_probability(value: float, baseline: pd.Series) -> float:
    percentile = empirical_percentile(value, baseline)
    if pd.isna(percentile):
        return float("nan")
    left_tail = percentile / 100.0
    right_tail = 1.0 - ((percentile / 100.0) - (1.0 / len(pd.to_numeric(baseline, errors="coerce").dropna())))
    return float(min(1.0, 2.0 * min(left_tail, right_tail)))


def summarize_latest_signal(
    *,
    latest_value: float,
    transformed_value: float,
    baseline_values: pd.Series,
    baseline_method: str,
    baseline_window: str,
    metric_direction: str,
    quality_state: str,
) -> dict[str, object]:
    clean = pd.to_numeric(baseline_values, errors="coerce").dropna()
    baseline_value = float(clean.median()) if not clean.empty else float("nan")
    robust = robust_z_score(transformed_value, clean)
    standard = standard_z_score(transformed_value, clean)
    stat = robust if baseline_method == "robust_z" else standard
    signed_stat = -stat if metric_direction == "negative" else stat
    tail = empirical_tail_probability(transformed_value, clean)
    percentile = empirical_percentile(transformed_value, clean)

    if quality_state != "valid":
        signal_state = "watch" if not pd.isna(signed_stat) and abs(float(signed_stat)) >= 1.0 else "neutral"
    elif not pd.isna(tail) and tail <= 0.05 and signed_stat > 0:
        signal_state = "bullish"
    elif not pd.isna(tail) and tail <= 0.05 and signed_stat < 0:
        signal_state = "bearish"
    elif not pd.isna(tail) and tail <= 0.10:
        signal_state = "watch"
    else:
        signal_state = "neutral"

    return {
        "latest_value": latest_value,
        "comparison_value": baseline_value,
        "baseline_value": baseline_value,
        "baseline_method": baseline_method,
        "baseline_window": baseline_window,
        "baseline_observation_count": int(len(clean)),
        "empirical_percentile": percentile,
        "tail_probability": tail,
        "effect_size": stat,
        "z_score": standard,
        "robust_z_score": robust,
        "percentile": percentile,
        "signed_stat": signed_stat,
        "signal_state": signal_state,
    }


def _numeric_time_series(series: pd.Series) -> pd.Series:
    ordered = pd.to_numeric(series, errors="coerce").copy()
    ordered.index = pd.to_datetime(ordered.index)
    return ordered.sort_index()
```

- [ ] **Step 4: Run transform tests**

Run:

```bash
pytest tests/test_signal_layer_transforms.py -v
```

Expected: PASS.

- [ ] **Step 5: Run all signal-layer unit tests so far**

Run:

```bash
pytest tests/test_signal_layer_registry.py tests/test_signal_layer_quality.py tests/test_signal_layer_transforms.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/signal_layer/transforms.py tests/test_signal_layer_transforms.py
git commit -m "feat: add signal statistical transforms"
```

---

### Task 4: Storage And CLI Skeleton

**Files:**
- Create: `src/signal_layer/storage.py`
- Create: `src/signal_layer/pipeline.py`
- Create: `src/signal_layer/cli.py`
- Create: `tests/test_signal_layer_pipeline.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing storage and CLI tests**

Create `tests/test_signal_layer_pipeline.py`:

```python
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
    reference_dir = tmp_path / "data" / "reference" / "signal_layer"
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

    counts = SignalLayerPipeline(tmp_path).validate_registry()

    assert counts == {"metrics": 1, "asset_mappings": 1}


def test_cli_validate_registry(tmp_path: Path) -> None:
    reference_dir = tmp_path / "data" / "reference" / "signal_layer"
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

    result = subprocess.run(
        [sys.executable, "-m", "signal_layer.cli", "--base-dir", str(tmp_path), "validate-registry"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "metrics: 1" in result.stdout
    assert "asset_mappings: 1" in result.stdout
```

- [ ] **Step 2: Run pipeline tests and verify they fail**

Run:

```bash
pytest tests/test_signal_layer_pipeline.py -v
```

Expected: FAIL with import errors for `signal_layer.storage`, `signal_layer.pipeline`, or `signal_layer.cli`.

- [ ] **Step 3: Implement storage, pipeline skeleton, and CLI**

Create `src/signal_layer/storage.py`:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


class SignalLayerStorage:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.processed_root = self.base_dir / "data" / "processed" / "signals"
        self.processed_root.mkdir(parents=True, exist_ok=True)

    def write_dataset(self, dataset_name: str, frame: pd.DataFrame) -> Path:
        self.processed_root.mkdir(parents=True, exist_ok=True)
        csv_path = self.processed_root / f"{dataset_name}.csv"
        parquet_path = self.processed_root / f"{dataset_name}.parquet"
        frame.to_csv(csv_path, index=False)
        frame.to_parquet(parquet_path, index=False)
        return csv_path

    def write_run_manifest(self, manifest: dict[str, Any]) -> Path:
        path = self.processed_root / "latest_signal_run.json"
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        return path
```

Create `src/signal_layer/pipeline.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from signal_layer.models import PipelineResult
from signal_layer.registry import load_registries
from signal_layer.storage import SignalLayerStorage


class SignalLayerPipeline:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.storage = SignalLayerStorage(self.base_dir)

    def validate_registry(self) -> dict[str, int]:
        metrics, mappings = load_registries(self.base_dir)
        return {"metrics": int(len(metrics)), "asset_mappings": int(len(mappings))}

    def build(self, *, sources: list[str] | None = None) -> PipelineResult:
        load_registries(self.base_dir)
        selected_sources = sources or []
        empty = pd.DataFrame()
        self.storage.write_dataset("metric_signals", empty)
        self.storage.write_dataset("asset_signals", empty)
        self.storage.write_dataset("theme_signals", empty)
        manifest = {
            "run_id": _run_id(),
            "sources": selected_sources,
            "datasets_written": {"metric_signals": 0, "asset_signals": 0, "theme_signals": 0},
        }
        self.storage.write_run_manifest(manifest)
        return PipelineResult(
            run_id=manifest["run_id"],
            datasets_written=manifest["datasets_written"],
            output_dir=str(self.storage.processed_root),
        )


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
```

Create `src/signal_layer/cli.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from signal_layer.pipeline import SignalLayerPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Alternative-data signal layer pipeline")
    parser.add_argument("--base-dir", default=".", help="Repository root")
    parser.add_argument("--sources", help="Comma-separated sources to build")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-registry", help="Validate signal registry files")
    subparsers.add_parser("build", help="Build metric, asset, and theme signals")
    return parser


def _source_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> None:
    args = build_parser().parse_args()
    pipeline = SignalLayerPipeline(Path(args.base_dir).resolve())

    if args.command == "validate-registry":
        counts = pipeline.validate_registry()
        for key, value in counts.items():
            print(f"{key}: {value}")
        return

    if args.command == "build":
        result = pipeline.build(sources=_source_list(args.sources))
        print(f"run_id={result.run_id}")
        for dataset, rows in result.datasets_written.items():
            print(f"{dataset}: {rows} rows written")
        print(f"output_dir={result.output_dir}")
        return

    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
```

Modify `pyproject.toml` under `[project.scripts]`:

```toml
signal-layer = "signal_layer.cli:main"
```

- [ ] **Step 4: Run pipeline tests**

Run:

```bash
pytest tests/test_signal_layer_pipeline.py -v
```

Expected: PASS.

- [ ] **Step 5: Run all signal-layer tests**

Run:

```bash
pytest tests/test_signal_layer_registry.py tests/test_signal_layer_quality.py tests/test_signal_layer_transforms.py tests/test_signal_layer_pipeline.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/signal_layer/storage.py src/signal_layer/pipeline.py src/signal_layer/cli.py tests/test_signal_layer_pipeline.py pyproject.toml
git commit -m "feat: add signal layer pipeline shell"
```

---

### Task 5: Provider Adoption Builder

**Files:**
- Create: `src/signal_layer/builders/__init__.py`
- Create: `src/signal_layer/builders/provider_adoption.py`
- Modify: `src/signal_layer/pipeline.py`
- Modify: `tests/test_signal_layer_pipeline.py`

- [ ] **Step 1: Add failing provider-adoption builder test**

Append to `tests/test_signal_layer_pipeline.py`:

```python
def test_pipeline_build_provider_adoption_signals(tmp_path: Path) -> None:
    reference_dir = tmp_path / "data" / "reference" / "signal_layer"
    normalized_dir = tmp_path / "data" / "normalized" / "provider_adoption"
    reference_dir.mkdir(parents=True)
    normalized_dir.mkdir(parents=True)

    pd.DataFrame(
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
                "max_freshness_lag_days": 120,
                "min_coverage_ratio": "",
                "description": "OpenAI PyPI download 28-day growth.",
                "caveats": "Package downloads include non-production usage.",
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
                "notes": "Microsoft has economic exposure to OpenAI adoption.",
            }
        ]
    ).to_csv(reference_dir / "signal_asset_mapping.csv", index=False)

    rows = []
    for index, day in enumerate(pd.date_range("2026-03-01", periods=60, freq="D")):
        rows.append(
            {
                "dataset_id": "pypi_downloads_daily",
                "source_url": "https://pypistats.org/api/packages/openai/overall",
                "source_run_id": "fixture",
                "scraped_at": "2026-05-01T00:00:00Z",
                "provider": "openai",
                "provider_display_name": "OpenAI",
                "package_name": "openai",
                "package_type": "sdk",
                "package_category": "core_sdk",
                "with_mirrors": False,
                "download_date": day.strftime("%Y-%m-%d"),
                "downloads": 1000 + index * 10,
            }
        )
    pd.DataFrame(rows).to_parquet(normalized_dir / "pypi_downloads_daily.parquet", index=False)

    result = SignalLayerPipeline(tmp_path).build(sources=["provider_adoption"])
    metric_signals = pd.read_parquet(tmp_path / "data" / "processed" / "signals" / "metric_signals.parquet")

    assert result.datasets_written["metric_signals"] == 1
    assert metric_signals["metric_id"].tolist() == ["pypi_openai_downloads_28d_growth"]
    assert metric_signals["quality_state"].tolist() == ["valid"]
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
pytest tests/test_signal_layer_pipeline.py::test_pipeline_build_provider_adoption_signals -v
```

Expected: FAIL because the pipeline writes empty outputs.

- [ ] **Step 3: Implement provider adoption builder**

Create `src/signal_layer/builders/__init__.py`:

```python
"""Source-specific signal builders."""
```

Create `src/signal_layer/builders/provider_adoption.py`:

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd

from signal_layer.models import METRIC_SIGNAL_COLUMNS
from signal_layer.quality import canonicalize_latest, duplicate_count, evaluate_metric_quality
from signal_layer.transforms import calculate_rolling_growth, summarize_latest_signal


def build_provider_adoption_signals(base_dir: Path, metric_registry: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    metrics = metric_registry.loc[metric_registry["source"] == "provider_adoption"].copy()
    for metric in metrics.to_dict("records"):
        dataset_path = base_dir / "data" / "normalized" / "provider_adoption" / f"{metric['dataset_id']}.parquet"
        if not dataset_path.exists():
            continue
        source = pd.read_parquet(dataset_path)
        records.extend(_build_metric_records(source, metric))
    return pd.DataFrame(records, columns=METRIC_SIGNAL_COLUMNS)


def _build_metric_records(source: pd.DataFrame, metric: dict[str, object]) -> list[dict[str, object]]:
    date_column = str(metric["date_column"])
    value_column = str(metric["value_column"])
    entity_columns = str(metric["entity_columns"]).split("|")
    grain = entity_columns + [date_column]
    duplicate_before = duplicate_count(source, grain)
    canonical = canonicalize_latest(
        source,
        grain=grain,
        prefer_non_null=["package_category"],
        run_id_column="source_run_id",
    )
    records: list[dict[str, object]] = []
    for entity_values, group in canonical.groupby(entity_columns, dropna=False):
        group = group.copy()
        group[date_column] = pd.to_datetime(group[date_column], errors="coerce")
        group[value_column] = pd.to_numeric(group[value_column], errors="coerce")
        group = group.dropna(subset=[date_column, value_column]).sort_values(date_column)
        if group.empty:
            continue
        series = pd.Series(group[value_column].to_numpy(), index=group[date_column])
        transformed = calculate_rolling_growth(series, window=28)
        latest_date = transformed.dropna().index.max() if transformed.notna().any() else group[date_column].max()
        latest_transformed = float(transformed.loc[latest_date]) if latest_date in transformed.index and pd.notna(transformed.loc[latest_date]) else float("nan")
        baseline = transformed.loc[transformed.index < latest_date].dropna().tail(90)
        run_date = pd.Timestamp.utcnow().tz_localize(None)
        quality = evaluate_metric_quality(
            baseline_observation_count=int(len(baseline)),
            min_baseline_observations=int(metric["min_baseline_observations"]),
            latest_date=pd.Timestamp(latest_date).tz_localize(None),
            run_date=run_date,
            max_freshness_lag_days=int(metric["max_freshness_lag_days"]),
            invalid_value_count=int((group[value_column] < 0).sum()),
            duplicate_count=duplicate_before,
            coverage_ratio=None,
            min_coverage_ratio=None,
            partial_period=False,
            source_validated=True,
        )
        summary = summarize_latest_signal(
            latest_value=float(series.loc[latest_date]) if latest_date in series.index else float(group[value_column].iloc[-1]),
            transformed_value=latest_transformed,
            baseline_values=baseline,
            baseline_method=str(metric["baseline_method"]),
            baseline_window=str(metric["baseline_window"]),
            metric_direction=str(metric["default_metric_direction"]),
            quality_state=quality.quality_state,
        )
        entity_tuple = entity_values if isinstance(entity_values, tuple) else (entity_values,)
        entity_key = "|".join("" if pd.isna(value) else str(value) for value in entity_tuple)
        records.append(
            {
                "metric_id": metric["metric_id"],
                "source": metric["source"],
                "as_of_date": pd.Timestamp(latest_date).date().isoformat(),
                "entity_key": entity_key,
                "entity_name": entity_key,
                "raw_change": pd.NA,
                "pct_change": pd.NA,
                "yoy_change": pd.NA,
                "rolling_change": latest_transformed,
                "rank": pd.NA,
                "rank_change": pd.NA,
                "metric_direction": metric["default_metric_direction"],
                "confidence": "medium",
                "source_updated_at": str(group.get("scraped_at", pd.Series([""])).iloc[-1]),
                "quality_state": quality.quality_state,
                "quality_issues": quality.quality_issues,
                "caveats": metric.get("caveats", ""),
                **summary,
            }
        )
    return records
```

- [ ] **Step 4: Wire provider builder into pipeline**

Modify `src/signal_layer/pipeline.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from signal_layer.aggregation import build_asset_signals, build_theme_signals
from signal_layer.builders.provider_adoption import build_provider_adoption_signals
from signal_layer.models import PipelineResult
from signal_layer.registry import load_registries
from signal_layer.storage import SignalLayerStorage


class SignalLayerPipeline:
    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.storage = SignalLayerStorage(self.base_dir)

    def validate_registry(self) -> dict[str, int]:
        metrics, mappings = load_registries(self.base_dir)
        return {"metrics": int(len(metrics)), "asset_mappings": int(len(mappings))}

    def build(self, *, sources: list[str] | None = None) -> PipelineResult:
        metric_registry, asset_mapping = load_registries(self.base_dir)
        selected_sources = sources or ["provider_adoption"]
        metric_frames = []
        if "provider_adoption" in selected_sources:
            metric_frames.append(build_provider_adoption_signals(self.base_dir, metric_registry))
        metric_signals = pd.concat(metric_frames, ignore_index=True) if metric_frames else pd.DataFrame()
        asset_signals = build_asset_signals(metric_signals, asset_mapping, metric_registry)
        theme_signals = build_theme_signals(asset_signals)
        self.storage.write_dataset("metric_signals", metric_signals)
        self.storage.write_dataset("asset_signals", asset_signals)
        self.storage.write_dataset("theme_signals", theme_signals)
        manifest = {
            "run_id": _run_id(),
            "sources": selected_sources,
            "datasets_written": {
                "metric_signals": int(len(metric_signals)),
                "asset_signals": int(len(asset_signals)),
                "theme_signals": int(len(theme_signals)),
            },
        }
        self.storage.write_run_manifest(manifest)
        return PipelineResult(
            run_id=manifest["run_id"],
            datasets_written=manifest["datasets_written"],
            output_dir=str(self.storage.processed_root),
        )


def _run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
```

This imports `signal_layer.aggregation`, which is implemented in Task 6. To keep Task 5 independently green, add a temporary minimal `src/signal_layer/aggregation.py`:

```python
from __future__ import annotations

import pandas as pd


def build_asset_signals(metric_signals: pd.DataFrame, asset_mapping: pd.DataFrame, metric_registry: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame()


def build_theme_signals(asset_signals: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame()
```

- [ ] **Step 5: Run provider-adoption test**

Run:

```bash
pytest tests/test_signal_layer_pipeline.py::test_pipeline_build_provider_adoption_signals -v
```

Expected: PASS.

- [ ] **Step 6: Run all signal-layer tests**

Run:

```bash
pytest tests/test_signal_layer_registry.py tests/test_signal_layer_quality.py tests/test_signal_layer_transforms.py tests/test_signal_layer_pipeline.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/signal_layer/builders/__init__.py src/signal_layer/builders/provider_adoption.py src/signal_layer/aggregation.py src/signal_layer/pipeline.py tests/test_signal_layer_pipeline.py
git commit -m "feat: build provider adoption metric signals"
```

---

### Task 6: Asset And Theme Aggregation

**Files:**
- Modify: `src/signal_layer/aggregation.py`
- Create: `tests/test_signal_layer_aggregation.py`

- [ ] **Step 1: Write failing aggregation tests**

Create `tests/test_signal_layer_aggregation.py`:

```python
from __future__ import annotations

import pandas as pd

from signal_layer.aggregation import build_asset_signals, build_theme_signals


def test_build_asset_signals_uses_only_valid_rows_for_combined_stat() -> None:
    metric_signals = pd.DataFrame(
        [
            {
                "metric_id": "metric_a",
                "as_of_date": "2026-06-30",
                "signed_stat": 2.0,
                "signal_state": "bullish",
                "quality_state": "valid",
                "quality_issues": "",
            },
            {
                "metric_id": "metric_b",
                "as_of_date": "2026-06-30",
                "signed_stat": -5.0,
                "signal_state": "watch",
                "quality_state": "insufficient_history",
                "quality_issues": "baseline too short",
            },
        ]
    )
    asset_mapping = pd.DataFrame(
        [
            {
                "metric_id": "metric_a",
                "ticker": "MSFT",
                "company_name": "Microsoft",
                "asset_type": "equity",
                "theme": "developer_ecosystem",
                "expected_direction": "positive",
                "exposure_weight": 1.0,
                "confidence": "medium",
            },
            {
                "metric_id": "metric_b",
                "ticker": "MSFT",
                "company_name": "Microsoft",
                "asset_type": "equity",
                "theme": "developer_ecosystem",
                "expected_direction": "positive",
                "exposure_weight": 1.0,
                "confidence": "low",
            },
        ]
    )
    metric_registry = pd.DataFrame(
        [
            {"metric_id": "metric_a", "description": "Valid metric."},
            {"metric_id": "metric_b", "description": "Invalid metric."},
        ]
    )

    result = build_asset_signals(metric_signals, asset_mapping, metric_registry)

    assert len(result) == 1
    assert result.iloc[0]["combined_signed_stat"] == 2.0
    assert result.iloc[0]["valid_driver_count"] == 1
    assert result.iloc[0]["non_valid_driver_count"] == 1
    assert "baseline too short" in result.iloc[0]["quality_issues"]


def test_build_theme_signals_summarizes_assets() -> None:
    asset_signals = pd.DataFrame(
        [
            {
                "ticker": "MSFT",
                "theme": "developer_ecosystem",
                "as_of_date": "2026-06-30",
                "combined_signed_stat": 2.0,
                "combined_tail_probability": 0.05,
                "signal_state": "bullish",
            },
            {
                "ticker": "AMZN",
                "theme": "developer_ecosystem",
                "as_of_date": "2026-06-30",
                "combined_signed_stat": 1.0,
                "combined_tail_probability": 0.2,
                "signal_state": "watch",
            },
        ]
    )

    result = build_theme_signals(asset_signals)

    assert result.iloc[0]["theme"] == "developer_ecosystem"
    assert result.iloc[0]["active_asset_count"] == 2
    assert result.iloc[0]["top_ticker"] == "MSFT"
```

- [ ] **Step 2: Run aggregation tests and verify they fail**

Run:

```bash
pytest tests/test_signal_layer_aggregation.py -v
```

Expected: FAIL because `src/signal_layer/aggregation.py` currently returns empty frames.

- [ ] **Step 3: Implement aggregation**

Replace `src/signal_layer/aggregation.py`:

```python
from __future__ import annotations

import math

import pandas as pd

from signal_layer.models import ASSET_SIGNAL_COLUMNS, THEME_SIGNAL_COLUMNS


def build_asset_signals(metric_signals: pd.DataFrame, asset_mapping: pd.DataFrame, metric_registry: pd.DataFrame) -> pd.DataFrame:
    if metric_signals.empty or asset_mapping.empty:
        return pd.DataFrame(columns=ASSET_SIGNAL_COLUMNS)
    joined = metric_signals.merge(asset_mapping, on="metric_id", how="inner")
    descriptions = metric_registry[["metric_id", "description"]].drop_duplicates("metric_id")
    joined = joined.merge(descriptions, on="metric_id", how="left")
    direction = joined["expected_direction"].map({"positive": 1.0, "negative": -1.0}).fillna(1.0)
    joined["mapped_signed_stat"] = pd.to_numeric(joined["signed_stat"], errors="coerce") * direction
    rows: list[dict[str, object]] = []
    for keys, group in joined.groupby(["ticker", "company_name", "asset_type", "theme", "as_of_date"], dropna=False):
        ticker, company_name, asset_type, theme, as_of_date = keys
        valid = group.loc[group["quality_state"] == "valid"].copy()
        combined = _combined_signed_stat(valid)
        tail = _descriptive_tail(combined)
        median = float(valid["mapped_signed_stat"].median()) if "mapped_signed_stat" in valid and not valid.empty else float("nan")
        if valid.empty:
            top = group.iloc[group["signed_stat"].abs().fillna(-1).argmax()]
        else:
            top = valid.iloc[valid["mapped_signed_stat"].abs().fillna(-1).argmax()]
        quality_issues = "; ".join(issue for issue in group.get("quality_issues", pd.Series(dtype=str)).dropna().astype(str) if issue)
        rows.append(
            {
                "ticker": ticker,
                "company_name": company_name,
                "asset_type": asset_type,
                "as_of_date": as_of_date,
                "theme": theme,
                "combined_signed_stat": combined,
                "combined_tail_probability": tail,
                "median_signed_stat": median,
                "positive_evidence_count": int((valid.get("mapped_signed_stat", pd.Series(dtype=float)) > 0).sum()),
                "negative_evidence_count": int((valid.get("mapped_signed_stat", pd.Series(dtype=float)) < 0).sum()),
                "bullish_metric_count": int((valid.get("signal_state", pd.Series(dtype=str)) == "bullish").sum()),
                "bearish_metric_count": int((valid.get("signal_state", pd.Series(dtype=str)) == "bearish").sum()),
                "neutral_metric_count": int((valid.get("signal_state", pd.Series(dtype=str)) == "neutral").sum()),
                "top_metric_id": top["metric_id"],
                "top_metric_description": top.get("description", ""),
                "driver_count": int(len(group)),
                "valid_driver_count": int(len(valid)),
                "non_valid_driver_count": int(len(group) - len(valid)),
                "quality_issues": quality_issues,
                "signal_state": _state_from_stat(combined),
                "confidence": _lowest_confidence(group["confidence"].dropna().astype(str).tolist()),
                "summary": f"{ticker} has {len(valid)} valid signal drivers in {theme}.",
            }
        )
    return pd.DataFrame(rows, columns=ASSET_SIGNAL_COLUMNS)


def build_theme_signals(asset_signals: pd.DataFrame) -> pd.DataFrame:
    if asset_signals.empty:
        return pd.DataFrame(columns=THEME_SIGNAL_COLUMNS)
    rows: list[dict[str, object]] = []
    for keys, group in asset_signals.groupby(["theme", "as_of_date"], dropna=False):
        theme, as_of_date = keys
        top = group.iloc[group["combined_signed_stat"].abs().fillna(-1).argmax()]
        combined = _combined_from_asset_group(group)
        rows.append(
            {
                "theme": theme,
                "as_of_date": as_of_date,
                "combined_signed_stat": combined,
                "combined_tail_probability": _descriptive_tail(combined),
                "median_signed_stat": float(group["combined_signed_stat"].median()),
                "positive_evidence_count": int(group["positive_evidence_count"].sum()),
                "negative_evidence_count": int(group["negative_evidence_count"].sum()),
                "active_metric_count": int(group["valid_driver_count"].sum()),
                "active_asset_count": int(group["ticker"].nunique()),
                "top_metric_id": top["top_metric_id"],
                "top_ticker": top["ticker"],
                "signal_state": _state_from_stat(combined),
                "confidence": _lowest_confidence(group["confidence"].dropna().astype(str).tolist()),
                "summary": f"{theme} has {group['ticker'].nunique()} active mapped assets.",
            }
        )
    return pd.DataFrame(rows, columns=THEME_SIGNAL_COLUMNS)


def _combined_signed_stat(valid: pd.DataFrame) -> float:
    if valid.empty:
        return float("nan")
    weights = pd.to_numeric(valid["exposure_weight"], errors="coerce").fillna(1.0).clip(lower=0.000001)
    numerator = (valid["mapped_signed_stat"] * weights.pow(0.5)).sum()
    denominator = math.sqrt(float(weights.sum()))
    return float(numerator / denominator) if denominator else float("nan")


def _combined_from_asset_group(group: pd.DataFrame) -> float:
    stats = pd.to_numeric(group["combined_signed_stat"], errors="coerce").dropna()
    if stats.empty:
        return float("nan")
    return float(stats.sum() / math.sqrt(len(stats)))


def _descriptive_tail(stat: float) -> float:
    if pd.isna(stat):
        return float("nan")
    return float(math.erfc(abs(float(stat)) / math.sqrt(2.0)))


def _state_from_stat(stat: float) -> str:
    if pd.isna(stat):
        return "watch"
    tail = _descriptive_tail(stat)
    if tail <= 0.05 and stat > 0:
        return "bullish"
    if tail <= 0.05 and stat < 0:
        return "bearish"
    if tail <= 0.10:
        return "watch"
    return "neutral"


def _lowest_confidence(values: list[str]) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    if not values:
        return "low"
    return min(values, key=lambda value: order.get(value, 0))
```

- [ ] **Step 4: Run aggregation tests**

Run:

```bash
pytest tests/test_signal_layer_aggregation.py -v
```

Expected: PASS.

- [ ] **Step 5: Run all signal-layer tests**

Run:

```bash
pytest tests/test_signal_layer_registry.py tests/test_signal_layer_quality.py tests/test_signal_layer_transforms.py tests/test_signal_layer_aggregation.py tests/test_signal_layer_pipeline.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/signal_layer/aggregation.py tests/test_signal_layer_aggregation.py
git commit -m "feat: aggregate signal evidence to assets"
```

---

### Task 7: Semiconductor Builder

**Files:**
- Create: `src/signal_layer/builders/semiconductor.py`
- Modify: `src/signal_layer/pipeline.py`
- Modify: `tests/test_signal_layer_pipeline.py`

- [ ] **Step 1: Add failing semiconductor fixture test**

Append to `tests/test_signal_layer_pipeline.py`:

```python
def test_pipeline_build_semiconductor_signals(tmp_path: Path) -> None:
    reference_dir = tmp_path / "data" / "reference" / "signal_layer"
    normalized_dir = tmp_path / "data" / "normalized" / "taiwan_semiconductor_revenue"
    reference_dir.mkdir(parents=True)
    normalized_dir.mkdir(parents=True)
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
    rows = []
    for index, month in enumerate(pd.date_range("2023-01-01", periods=40, freq="MS")):
        rows.append(
            {
                "dataset_id": "tw_monthly_revenue",
                "company_code": "2330",
                "company_name": "台積電",
                "filing_date": "2026-05-10",
                "revenue_month": month.strftime("%Y-%m-%d"),
                "monthly_revenue_ntd": 100_000_000 + index * 1_000_000,
                "scraped_at": "2026-05-10T00:00:00Z",
            }
        )
    pd.DataFrame(rows).to_parquet(normalized_dir / "tw_monthly_revenue.parquet", index=False)

    result = SignalLayerPipeline(tmp_path).build(sources=["semiconductor"])
    metric_signals = pd.read_parquet(tmp_path / "data" / "processed" / "signals" / "metric_signals.parquet")

    assert result.datasets_written["metric_signals"] == 1
    assert metric_signals.iloc[0]["metric_id"] == "tw_tsmc_revenue_yoy"
    assert metric_signals.iloc[0]["quality_state"] == "valid"
```

- [ ] **Step 2: Run the semiconductor test and verify it fails**

Run:

```bash
pytest tests/test_signal_layer_pipeline.py::test_pipeline_build_semiconductor_signals -v
```

Expected: FAIL because there is no semiconductor builder.

- [ ] **Step 3: Implement semiconductor builder**

Create `src/signal_layer/builders/semiconductor.py`:

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd

from signal_layer.models import METRIC_SIGNAL_COLUMNS
from signal_layer.quality import canonicalize_latest, duplicate_count, evaluate_metric_quality
from signal_layer.transforms import calculate_yoy_growth, summarize_latest_signal


DATASET_DIRS = {
    "tw_monthly_revenue": ("taiwan_semiconductor_revenue", "tw_monthly_revenue.parquet"),
    "fred_semiconductor_ppi": ("semiconductor_memory", "fred_semiconductor_ppi.parquet"),
    "semiconductor_official_monthly": ("semiconductor_proxies", "semiconductor_official_monthly.parquet"),
}


def build_semiconductor_signals(base_dir: Path, metric_registry: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    metrics = metric_registry.loc[metric_registry["source"] == "semiconductor"].copy()
    for metric in metrics.to_dict("records"):
        dataset_id = str(metric["dataset_id"])
        if dataset_id not in DATASET_DIRS:
            continue
        dataset_dir, filename = DATASET_DIRS[dataset_id]
        dataset_path = base_dir / "data" / "normalized" / dataset_dir / filename
        if not dataset_path.exists():
            continue
        source = pd.read_parquet(dataset_path)
        records.extend(_build_monthly_metric_records(source, metric))
    return pd.DataFrame(records, columns=METRIC_SIGNAL_COLUMNS)


def _build_monthly_metric_records(source: pd.DataFrame, metric: dict[str, object]) -> list[dict[str, object]]:
    date_column = str(metric["date_column"])
    value_column = str(metric["value_column"])
    entity_columns = str(metric["entity_columns"]).split("|")
    grain = entity_columns + [date_column]
    duplicate_before = duplicate_count(source, grain)
    canonical = canonicalize_latest(source, grain=grain, prefer_non_null=[], run_id_column="source_run_id")
    records: list[dict[str, object]] = []
    for entity_values, group in canonical.groupby(entity_columns, dropna=False):
        group = group.copy()
        group[date_column] = pd.to_datetime(group[date_column], errors="coerce")
        group[value_column] = pd.to_numeric(group[value_column], errors="coerce")
        group = group.dropna(subset=[date_column, value_column]).sort_values(date_column)
        if group.empty:
            continue
        series = pd.Series(group[value_column].to_numpy(), index=group[date_column])
        transformed = calculate_yoy_growth(series)
        latest_date = transformed.dropna().index.max() if transformed.notna().any() else group[date_column].max()
        latest_transformed = float(transformed.loc[latest_date]) if latest_date in transformed.index and pd.notna(transformed.loc[latest_date]) else float("nan")
        baseline = transformed.loc[transformed.index < latest_date].dropna().tail(36)
        quality = evaluate_metric_quality(
            baseline_observation_count=int(len(baseline)),
            min_baseline_observations=int(metric["min_baseline_observations"]),
            latest_date=pd.Timestamp(latest_date).tz_localize(None),
            run_date=pd.Timestamp.utcnow().tz_localize(None),
            max_freshness_lag_days=int(metric["max_freshness_lag_days"]),
            invalid_value_count=int((group[value_column] < 0).sum()),
            duplicate_count=duplicate_before,
            coverage_ratio=None,
            min_coverage_ratio=None,
            partial_period=False,
            source_validated=True,
        )
        summary = summarize_latest_signal(
            latest_value=float(series.loc[latest_date]) if latest_date in series.index else float(group[value_column].iloc[-1]),
            transformed_value=latest_transformed,
            baseline_values=baseline,
            baseline_method=str(metric["baseline_method"]),
            baseline_window=str(metric["baseline_window"]),
            metric_direction=str(metric["default_metric_direction"]),
            quality_state=quality.quality_state,
        )
        entity_tuple = entity_values if isinstance(entity_values, tuple) else (entity_values,)
        entity_key = "|".join("" if pd.isna(value) else str(value) for value in entity_tuple)
        records.append(
            {
                "metric_id": metric["metric_id"],
                "source": metric["source"],
                "as_of_date": pd.Timestamp(latest_date).date().isoformat(),
                "entity_key": entity_key,
                "entity_name": entity_key,
                "raw_change": pd.NA,
                "pct_change": pd.NA,
                "yoy_change": latest_transformed,
                "rolling_change": pd.NA,
                "rank": pd.NA,
                "rank_change": pd.NA,
                "metric_direction": metric["default_metric_direction"],
                "confidence": "medium",
                "source_updated_at": str(group.get("scraped_at", pd.Series([""])).iloc[-1]),
                "quality_state": quality.quality_state,
                "quality_issues": quality.quality_issues,
                "caveats": metric.get("caveats", ""),
                **summary,
            }
        )
    return records
```

- [ ] **Step 4: Wire semiconductor builder into pipeline**

Modify `src/signal_layer/pipeline.py` imports:

```python
from signal_layer.builders.semiconductor import build_semiconductor_signals
```

Modify the `build()` method source selection:

```python
selected_sources = sources or ["provider_adoption", "semiconductor"]
metric_frames = []
if "provider_adoption" in selected_sources:
    metric_frames.append(build_provider_adoption_signals(self.base_dir, metric_registry))
if "semiconductor" in selected_sources:
    metric_frames.append(build_semiconductor_signals(self.base_dir, metric_registry))
```

- [ ] **Step 5: Run semiconductor test**

Run:

```bash
pytest tests/test_signal_layer_pipeline.py::test_pipeline_build_semiconductor_signals -v
```

Expected: PASS.

- [ ] **Step 6: Run all signal-layer tests**

Run:

```bash
pytest tests/test_signal_layer_registry.py tests/test_signal_layer_quality.py tests/test_signal_layer_transforms.py tests/test_signal_layer_aggregation.py tests/test_signal_layer_pipeline.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/signal_layer/builders/semiconductor.py src/signal_layer/pipeline.py tests/test_signal_layer_pipeline.py
git commit -m "feat: build semiconductor metric signals"
```

---

### Task 8: OpenRouter Builder

**Files:**
- Create: `src/signal_layer/builders/openrouter.py`
- Modify: `src/signal_layer/pipeline.py`
- Modify: `tests/test_signal_layer_pipeline.py`

- [ ] **Step 1: Add failing OpenRouter fixture test**

Append to `tests/test_signal_layer_pipeline.py`:

```python
def test_pipeline_build_openrouter_signals(tmp_path: Path) -> None:
    reference_dir = tmp_path / "data" / "reference" / "signal_layer"
    normalized_dir = tmp_path / "data" / "normalized" / "marts"
    reference_dir.mkdir(parents=True)
    normalized_dir.mkdir(parents=True)
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

    rows = []
    for index, day in enumerate(pd.date_range("2026-03-01", periods=70, freq="D")):
        rows.append(
            {
                "usage_date": day.strftime("%Y-%m-%d"),
                "provider_slug": "anthropic",
                "provider_name": "Anthropic",
                "model_permaslug": "all_models",
                "total_tokens": 1_000_000 + index * 10_000,
                "has_pricing": False,
            }
        )
    pd.DataFrame(rows).to_parquet(normalized_dir / "daily_provider_economics.parquet", index=False)

    result = SignalLayerPipeline(tmp_path).build(sources=["openrouter"])
    metric_signals = pd.read_parquet(tmp_path / "data" / "processed" / "signals" / "metric_signals.parquet")

    assert result.datasets_written["metric_signals"] == 1
    assert metric_signals.iloc[0]["metric_id"] == "openrouter_anthropic_tokens_28d_growth"
    assert metric_signals.iloc[0]["quality_state"] == "valid"
```

- [ ] **Step 2: Run the OpenRouter test and verify it fails**

Run:

```bash
pytest tests/test_signal_layer_pipeline.py::test_pipeline_build_openrouter_signals -v
```

Expected: FAIL because there is no OpenRouter builder.

- [ ] **Step 3: Implement OpenRouter builder**

Create `src/signal_layer/builders/openrouter.py`:

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd

from signal_layer.models import METRIC_SIGNAL_COLUMNS
from signal_layer.quality import canonicalize_latest, duplicate_count, evaluate_metric_quality
from signal_layer.transforms import calculate_rolling_growth, summarize_latest_signal


def build_openrouter_signals(base_dir: Path, metric_registry: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    metrics = metric_registry.loc[metric_registry["source"] == "openrouter"].copy()
    for metric in metrics.to_dict("records"):
        dataset_path = base_dir / "data" / "normalized" / "marts" / f"{metric['dataset_id']}.parquet"
        if not dataset_path.exists():
            continue
        source = pd.read_parquet(dataset_path)
        records.extend(_build_provider_token_records(source, metric))
    return pd.DataFrame(records, columns=METRIC_SIGNAL_COLUMNS)


def _build_provider_token_records(source: pd.DataFrame, metric: dict[str, object]) -> list[dict[str, object]]:
    date_column = str(metric["date_column"])
    value_column = str(metric["value_column"])
    entity_columns = str(metric["entity_columns"]).split("|")
    raw = source.copy()
    raw[date_column] = pd.to_datetime(raw[date_column], errors="coerce")
    raw[value_column] = pd.to_numeric(raw[value_column], errors="coerce")
    aggregated = (
        raw.dropna(subset=[date_column, value_column])
        .groupby(entity_columns + [date_column], dropna=False, as_index=False)
        .agg({value_column: "sum"})
    )
    grain = entity_columns + [date_column]
    duplicate_before = duplicate_count(aggregated, grain)
    canonical = canonicalize_latest(aggregated, grain=grain, prefer_non_null=[], run_id_column="source_run_id")
    records: list[dict[str, object]] = []
    for entity_values, group in canonical.groupby(entity_columns, dropna=False):
        group = group.sort_values(date_column)
        series = pd.Series(group[value_column].to_numpy(), index=group[date_column])
        transformed = calculate_rolling_growth(series, window=28)
        latest_date = transformed.dropna().index.max() if transformed.notna().any() else group[date_column].max()
        latest_transformed = float(transformed.loc[latest_date]) if latest_date in transformed.index and pd.notna(transformed.loc[latest_date]) else float("nan")
        baseline = transformed.loc[transformed.index < latest_date].dropna().tail(90)
        quality = evaluate_metric_quality(
            baseline_observation_count=int(len(baseline)),
            min_baseline_observations=int(metric["min_baseline_observations"]),
            latest_date=pd.Timestamp(latest_date).tz_localize(None),
            run_date=pd.Timestamp.utcnow().tz_localize(None),
            max_freshness_lag_days=int(metric["max_freshness_lag_days"]),
            invalid_value_count=int((group[value_column] < 0).sum()),
            duplicate_count=duplicate_before,
            coverage_ratio=None,
            min_coverage_ratio=None,
            partial_period=False,
            source_validated=True,
        )
        summary = summarize_latest_signal(
            latest_value=float(series.loc[latest_date]) if latest_date in series.index else float(group[value_column].iloc[-1]),
            transformed_value=latest_transformed,
            baseline_values=baseline,
            baseline_method=str(metric["baseline_method"]),
            baseline_window=str(metric["baseline_window"]),
            metric_direction=str(metric["default_metric_direction"]),
            quality_state=quality.quality_state,
        )
        entity_tuple = entity_values if isinstance(entity_values, tuple) else (entity_values,)
        entity_key = "|".join("" if pd.isna(value) else str(value) for value in entity_tuple)
        records.append(
            {
                "metric_id": metric["metric_id"],
                "source": metric["source"],
                "as_of_date": pd.Timestamp(latest_date).date().isoformat(),
                "entity_key": entity_key,
                "entity_name": entity_key,
                "raw_change": pd.NA,
                "pct_change": pd.NA,
                "yoy_change": pd.NA,
                "rolling_change": latest_transformed,
                "rank": pd.NA,
                "rank_change": pd.NA,
                "metric_direction": metric["default_metric_direction"],
                "confidence": "low",
                "source_updated_at": "",
                "quality_state": quality.quality_state,
                "quality_issues": quality.quality_issues,
                "caveats": metric.get("caveats", ""),
                **summary,
            }
        )
    return records
```

- [ ] **Step 4: Wire OpenRouter builder into pipeline**

Modify `src/signal_layer/pipeline.py` imports:

```python
from signal_layer.builders.openrouter import build_openrouter_signals
```

Modify the `build()` method source selection:

```python
selected_sources = sources or ["provider_adoption", "semiconductor", "openrouter"]
metric_frames = []
if "provider_adoption" in selected_sources:
    metric_frames.append(build_provider_adoption_signals(self.base_dir, metric_registry))
if "semiconductor" in selected_sources:
    metric_frames.append(build_semiconductor_signals(self.base_dir, metric_registry))
if "openrouter" in selected_sources:
    metric_frames.append(build_openrouter_signals(self.base_dir, metric_registry))
```

- [ ] **Step 5: Run OpenRouter test**

Run:

```bash
pytest tests/test_signal_layer_pipeline.py::test_pipeline_build_openrouter_signals -v
```

Expected: PASS.

- [ ] **Step 6: Run all signal-layer tests**

Run:

```bash
pytest tests/test_signal_layer_registry.py tests/test_signal_layer_quality.py tests/test_signal_layer_transforms.py tests/test_signal_layer_aggregation.py tests/test_signal_layer_pipeline.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/signal_layer/builders/openrouter.py src/signal_layer/pipeline.py tests/test_signal_layer_pipeline.py
git commit -m "feat: build openrouter metric signals"
```

---

### Task 9: Minerals Builder

**Files:**
- Create: `src/signal_layer/builders/minerals.py`
- Modify: `src/signal_layer/pipeline.py`
- Modify: `tests/test_signal_layer_pipeline.py`

- [ ] **Step 1: Add failing minerals fixture test**

Append to `tests/test_signal_layer_pipeline.py`:

```python
def test_pipeline_build_minerals_signals(tmp_path: Path) -> None:
    reference_dir = tmp_path / "data" / "reference" / "signal_layer"
    processed_dir = tmp_path / "data" / "processed" / "minerals_signal_data" / "tungsten_price_daily" / "latest"
    reference_dir.mkdir(parents=True)
    processed_dir.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "metric_id": "tungsten_apt_13w_momentum",
                "source": "minerals",
                "dataset_id": "tungsten_price_daily",
                "date_column": "date",
                "value_column": "apt",
                "entity_columns": "commodity",
                "cadence": "daily",
                "transform": "rolling_growth",
                "baseline_method": "robust_z",
                "baseline_window": "52W",
                "seasonality_mode": "none",
                "higher_is_better": True,
                "default_metric_direction": "positive",
                "min_baseline_observations": 60,
                "max_freshness_lag_days": 120,
                "min_coverage_ratio": "",
                "description": "China tungsten APT 13-week momentum.",
                "caveats": "Producer-positive signal.",
            }
        ]
    ).to_csv(reference_dir / "signal_metric_registry.csv", index=False)
    pd.DataFrame(
        [
            {
                "metric_id": "tungsten_apt_13w_momentum",
                "ticker": "600549.SH",
                "company_name": "Xiamen Tungsten",
                "asset_type": "equity",
                "theme": "critical_minerals",
                "exposure_type": "direct_revenue_proxy",
                "expected_direction": "positive",
                "exposure_weight": 1.0,
                "lag_days": 0,
                "confidence": "medium",
                "notes": "Tungsten price momentum can be positive for tungsten producers.",
            }
        ]
    ).to_csv(reference_dir / "signal_asset_mapping.csv", index=False)
    rows = []
    for index, day in enumerate(pd.date_range("2026-01-01", periods=130, freq="D")):
        rows.append({"date": day.strftime("%Y-%m-%d"), "apt": 200_000 + index * 500, "title": "fixture", "url": "fixture://apt"})
    pd.DataFrame(rows).to_parquet(processed_dir / "tungsten_price_daily.parquet", index=False)

    result = SignalLayerPipeline(tmp_path).build(sources=["minerals"])
    metric_signals = pd.read_parquet(tmp_path / "data" / "processed" / "signals" / "metric_signals.parquet")

    assert result.datasets_written["metric_signals"] == 1
    assert metric_signals.iloc[0]["metric_id"] == "tungsten_apt_13w_momentum"
    assert metric_signals.iloc[0]["quality_state"] == "valid"
```

- [ ] **Step 2: Run the minerals test and verify it fails**

Run:

```bash
pytest tests/test_signal_layer_pipeline.py::test_pipeline_build_minerals_signals -v
```

Expected: FAIL because there is no minerals builder.

- [ ] **Step 3: Implement minerals builder**

Create `src/signal_layer/builders/minerals.py`:

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd

from signal_layer.models import METRIC_SIGNAL_COLUMNS
from signal_layer.quality import canonicalize_latest, duplicate_count, evaluate_metric_quality
from signal_layer.transforms import calculate_rolling_growth, summarize_latest_signal


def build_minerals_signals(base_dir: Path, metric_registry: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    metrics = metric_registry.loc[metric_registry["source"] == "minerals"].copy()
    for metric in metrics.to_dict("records"):
        dataset_id = str(metric["dataset_id"])
        dataset_path = (
            base_dir
            / "data"
            / "processed"
            / "minerals_signal_data"
            / dataset_id
            / "latest"
            / f"{dataset_id}.parquet"
        )
        if not dataset_path.exists():
            continue
        source = pd.read_parquet(dataset_path)
        records.extend(_build_price_records(source, metric))
    return pd.DataFrame(records, columns=METRIC_SIGNAL_COLUMNS)


def _build_price_records(source: pd.DataFrame, metric: dict[str, object]) -> list[dict[str, object]]:
    date_column = str(metric["date_column"])
    value_column = str(metric["value_column"])
    working = source.copy()
    working["commodity"] = value_column
    entity_columns = str(metric["entity_columns"]).split("|")
    grain = entity_columns + [date_column]
    duplicate_before = duplicate_count(working, grain)
    canonical = canonicalize_latest(working, grain=grain, prefer_non_null=[value_column], run_id_column="url")
    records: list[dict[str, object]] = []
    for entity_values, group in canonical.groupby(entity_columns, dropna=False):
        group = group.copy()
        group[date_column] = pd.to_datetime(group[date_column], errors="coerce")
        group[value_column] = pd.to_numeric(group[value_column], errors="coerce")
        group = group.dropna(subset=[date_column, value_column]).sort_values(date_column)
        if group.empty:
            continue
        series = pd.Series(group[value_column].to_numpy(), index=group[date_column])
        transformed = calculate_rolling_growth(series, window=65)
        latest_date = transformed.dropna().index.max() if transformed.notna().any() else group[date_column].max()
        latest_transformed = float(transformed.loc[latest_date]) if latest_date in transformed.index and pd.notna(transformed.loc[latest_date]) else float("nan")
        baseline = transformed.loc[transformed.index < latest_date].dropna().tail(252)
        quality = evaluate_metric_quality(
            baseline_observation_count=int(len(baseline)),
            min_baseline_observations=int(metric["min_baseline_observations"]),
            latest_date=pd.Timestamp(latest_date).tz_localize(None),
            run_date=pd.Timestamp.utcnow().tz_localize(None),
            max_freshness_lag_days=int(metric["max_freshness_lag_days"]),
            invalid_value_count=int((group[value_column] <= 0).sum()),
            duplicate_count=duplicate_before,
            coverage_ratio=None,
            min_coverage_ratio=None,
            partial_period=False,
            source_validated=True,
        )
        summary = summarize_latest_signal(
            latest_value=float(series.loc[latest_date]) if latest_date in series.index else float(group[value_column].iloc[-1]),
            transformed_value=latest_transformed,
            baseline_values=baseline,
            baseline_method=str(metric["baseline_method"]),
            baseline_window=str(metric["baseline_window"]),
            metric_direction=str(metric["default_metric_direction"]),
            quality_state=quality.quality_state,
        )
        entity_tuple = entity_values if isinstance(entity_values, tuple) else (entity_values,)
        entity_key = "|".join("" if pd.isna(value) else str(value) for value in entity_tuple)
        records.append(
            {
                "metric_id": metric["metric_id"],
                "source": metric["source"],
                "as_of_date": pd.Timestamp(latest_date).date().isoformat(),
                "entity_key": entity_key,
                "entity_name": entity_key,
                "raw_change": pd.NA,
                "pct_change": pd.NA,
                "yoy_change": pd.NA,
                "rolling_change": latest_transformed,
                "rank": pd.NA,
                "rank_change": pd.NA,
                "metric_direction": metric["default_metric_direction"],
                "confidence": "medium",
                "source_updated_at": "",
                "quality_state": quality.quality_state,
                "quality_issues": quality.quality_issues,
                "caveats": metric.get("caveats", ""),
                **summary,
            }
        )
    return records
```

- [ ] **Step 4: Wire minerals builder into pipeline**

Modify `src/signal_layer/pipeline.py` imports:

```python
from signal_layer.builders.minerals import build_minerals_signals
```

Modify the `build()` method source selection:

```python
selected_sources = sources or ["provider_adoption", "semiconductor", "openrouter", "minerals"]
metric_frames = []
if "provider_adoption" in selected_sources:
    metric_frames.append(build_provider_adoption_signals(self.base_dir, metric_registry))
if "semiconductor" in selected_sources:
    metric_frames.append(build_semiconductor_signals(self.base_dir, metric_registry))
if "openrouter" in selected_sources:
    metric_frames.append(build_openrouter_signals(self.base_dir, metric_registry))
if "minerals" in selected_sources:
    metric_frames.append(build_minerals_signals(self.base_dir, metric_registry))
```

- [ ] **Step 5: Run minerals test**

Run:

```bash
pytest tests/test_signal_layer_pipeline.py::test_pipeline_build_minerals_signals -v
```

Expected: PASS.

- [ ] **Step 6: Run all signal-layer tests**

Run:

```bash
pytest tests/test_signal_layer_registry.py tests/test_signal_layer_quality.py tests/test_signal_layer_transforms.py tests/test_signal_layer_aggregation.py tests/test_signal_layer_pipeline.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/signal_layer/builders/minerals.py src/signal_layer/pipeline.py tests/test_signal_layer_pipeline.py
git commit -m "feat: build mineral price signals"
```

---

### Task 10: Local End-To-End Run And Spec Review

**Files:**
- Modify only if failures reveal a concrete issue in files created by Tasks 1-7.

- [ ] **Step 1: Validate registries on the real repo**

Run:

```bash
python -m signal_layer.cli --base-dir . validate-registry
```

Expected:

```text
metrics: 6
asset_mappings: 6
```

- [ ] **Step 2: Build the v1 signals from real local normalized data**

Run:

```bash
python -m signal_layer.cli --base-dir . --sources provider_adoption,semiconductor,openrouter,minerals build
```

Expected:

```text
run_id=<timestamp>
metric_signals: <nonzero> rows written
asset_signals: <nonzero> rows written
theme_signals: <nonzero> rows written
output_dir=/Users/henrywzh/Quant/alternative-data/data/processed/signals
```

- [ ] **Step 3: Inspect output quality states**

Run:

```bash
python - <<'PY'
import pandas as pd
metric = pd.read_parquet("data/processed/signals/metric_signals.parquet")
asset = pd.read_parquet("data/processed/signals/asset_signals.parquet")
theme = pd.read_parquet("data/processed/signals/theme_signals.parquet")
print(metric["quality_state"].value_counts(dropna=False).to_string())
print(asset[["ticker", "theme", "combined_signed_stat", "signal_state", "valid_driver_count", "non_valid_driver_count"]].head(20).to_string(index=False))
print(theme[["theme", "combined_signed_stat", "signal_state", "active_metric_count", "active_asset_count"]].to_string(index=False))
PY
```

Expected:
- At least one `valid` or explicitly explained non-valid metric row.
- Asset and theme outputs include valid and non-valid driver counts.
- No source with duplicate grain contributes silently as valid.

- [ ] **Step 4: Run all signal-layer tests**

Run:

```bash
pytest tests/test_signal_layer_registry.py tests/test_signal_layer_quality.py tests/test_signal_layer_transforms.py tests/test_signal_layer_aggregation.py tests/test_signal_layer_pipeline.py -v
```

Expected: PASS.

- [ ] **Step 5: Run focused adjacent tests**

Run:

```bash
pytest tests/test_provider_adoption_pipeline.py tests/test_semiconductor_memory_pipeline.py tests/test_taiwan_semiconductor_revenue_pipeline.py -q
```

Expected: PASS. If unrelated pre-existing local changes affect these tests, record the failing test names and confirm whether failures touch signal-layer code before changing anything.

- [ ] **Step 6: Compare implementation against spec**

Run:

```bash
python - <<'PY'
from pathlib import Path
spec = Path("docs/superpowers/specs/2026-07-01-alternative-data-signal-layer-design.md").read_text()
required = [
    "quality_state",
    "Metric Eligibility Gates",
    "OpenRouter",
    "Provider Adoption",
    "Semiconductor",
    "Minerals",
    "Statistical Signal Measurement",
]
for item in required:
    print(f"{item}: {'present' if item in spec else 'missing'}")
PY
```

Expected: all lines end with `present`.

- [ ] **Step 7: Commit final verification adjustments if needed**

If code changed during verification:

```bash
git add src/signal_layer tests/test_signal_layer_*.py data/reference/signal_layer pyproject.toml
git commit -m "test: verify signal layer outputs"
```

If no code changed, do not create an empty commit.

---

## Plan Self-Review

Spec coverage:
- Metric registry: Task 1.
- Asset mapping registry: Task 1.
- Quality states and metric eligibility gates: Task 2.
- Statistical transforms and surprise fields: Task 3.
- Storage and CLI: Task 4.
- Provider adoption v1 builder: Task 5.
- Asset/theme aggregation: Task 6.
- Semiconductor v1 builder: Task 7.
- OpenRouter v1 builder: Task 8.
- Minerals v1 builder: Task 9.
- Real-data inspection and caveat review: Task 10.

Known scope decisions:
- OpenRouter v1 starts with provider-level token growth from `daily_provider_economics`; task-spend and revenue signals stay out until there is enough comparable history and pricing coverage.
- Minerals v1 starts with live tungsten APT price momentum; USGS extracted metrics stay out until parser contamination is fixed and validated.
- Artificial Analysis and Google Trends remain later-phase builders as specified.
- Combined tail probability remains descriptive because source metrics can be correlated.

Placeholder scan:
- The plan contains no placeholder steps. Each code-changing task includes concrete tests, code, commands, and expected outcomes.

Type consistency:
- Registry column names use `exposure_weight`, not the older `weight`.
- Metric signal fields include `quality_state` and `quality_issues`.
- Aggregation uses `combined_signed_stat`, `combined_tail_probability`, and driver quality counts.
