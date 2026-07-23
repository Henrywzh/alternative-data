# OpenRouter Derived Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish validated OpenRouter usage economics and workload-intensity marts through a deterministic CLI.

**Architecture:** `OpenRouterDerivedPipeline` will load and validate the four existing normalized inputs plus the curated capability map, compose the Task 1–3 metric functions, validate both final frames, and publish both Parquet files as a recoverable pair. The CLI will only parse command-line values, invoke the pipeline, and print sorted row counts.

**Tech Stack:** Python 3.11, pandas, pyarrow, pytest, argparse.

## Global Constraints

- Write only `data/normalized/marts/openrouter_usage_economics_daily.parquet` and `data/normalized/marts/openrouter_workload_intensity_models.parquet`.
- Validate every required input and both output frames before replacing either final mart.
- Use Parquet-only temporary and final files; retain prior valid final bytes on a failed build.
- Preserve `pricing_join_status` and all metric-provided provenance and coverage columns.
- Expose `python -m openrouter_derived_data.cli --base-dir . build [--today YYYY-MM-DD]` and `openrouter-derived-data`.

---

### Task 1: End-to-end pipeline and storage

**Files:**
- Create: `src/openrouter_derived_data/pipeline.py`
- Modify: `src/openrouter_derived_data/__init__.py`
- Test: `tests/test_openrouter_derived_data.py`

**Interfaces:**
- Produces: `OpenRouterDerivedPipeline(base_dir: Path)`.
- Produces: `OpenRouterDerivedPipeline.build(*, today: date | None = None) -> dict[str, int]`.

- [ ] **Step 1: Write failing integration tests**

```python
result = OpenRouterDerivedPipeline(tmp_path).build(today=date(2026, 7, 19))
assert result["openrouter_usage_economics_daily"] > 0
assert result["openrouter_workload_intensity_models"] > 0
```

Also seed the four input Parquets and curated JSON, assert both exact output schemas and preserved prior bytes after an input is removed, and cover required columns, duplicate natural keys, incomplete activity, absent Artificial Analysis snapshots, and an allowed guarded SOTA gap.

- [ ] **Step 2: Run the focused tests to verify RED**

Run: `python -m pytest -q tests/test_openrouter_derived_data.py -k pipeline`
Expected: FAIL because `OpenRouterDerivedPipeline` is unavailable.

- [ ] **Step 3: Implement loading, validation, derivation, and atomic publication**

```python
activity = pd.read_parquet(base_dir / "data/normalized/openrouter/openrouter_model_activity.parquet")
economics = pd.read_parquet(base_dir / "data/normalized/marts/daily_provider_economics.parquet")
pricing = pd.read_parquet(base_dir / "data/normalized/compute_availability/raw_openrouter_models.parquet")
models = pd.read_parquet(base_dir / "data/normalized/artificial_analysis/artificial_analysis_models_daily.parquet")
```

Validate input schemas, natural keys, complete activity, and eligible benchmark snapshots. Compose workload and price metrics, concatenate them without dropping columns, validate output schemas/keys/non-missing values, write both temporary Parquets, read both back, then replace both destinations with rollback cleanup on any exception.

- [ ] **Step 4: Run the focused tests to verify GREEN**

Run: `python -m pytest -q tests/test_openrouter_derived_data.py -k pipeline`
Expected: PASS.

### Task 2: CLI and packaging

**Files:**
- Create: `src/openrouter_derived_data/cli.py`
- Modify: `pyproject.toml`
- Test: `tests/test_openrouter_derived_data.py`

**Interfaces:**
- Produces: `main() -> None`.
- Adds: `openrouter-derived-data = "openrouter_derived_data.cli:main"`.

- [ ] **Step 1: Write a failing CLI test**

```python
monkeypatch.setattr(sys, "argv", ["openrouter-derived-data", "--base-dir", str(tmp_path), "build", "--today", "2026-07-19"])
main()
assert capsys.readouterr().out.splitlines() == [
    "openrouter_usage_economics_daily: 1 rows",
    "openrouter_workload_intensity_models: 1 rows",
]
```

- [ ] **Step 2: Run the CLI test to verify RED**

Run: `python -m pytest -q tests/test_openrouter_derived_data.py -k cli`
Expected: FAIL because the CLI module is unavailable.

- [ ] **Step 3: Implement and register the CLI**

```python
for dataset_id, rows in sorted(result.items()):
    print(f"{dataset_id}: {rows} rows")
```

Parse `--today` with `date.fromisoformat` and only accept the `build` subcommand.

- [ ] **Step 4: Run package verification and commit**

Run: `python -m pytest -q tests/test_openrouter_derived_data.py`
Expected: PASS.

```bash
git add pyproject.toml src/openrouter_derived_data tests/test_openrouter_derived_data.py
git commit -m "Add OpenRouter derived metrics pipeline"
```

## Self-Review

- Spec coverage: all required input files, failure modes, output schemas, Parquet-only atomic publishing, Python module CLI, package entry point, and deterministic output are covered by Tasks 1–2.
- Placeholder scan: no implementation placeholders remain; exact paths, APIs, commands, and expected outcomes are stated.
- Type consistency: all consumers use `OpenRouterDerivedPipeline.build(today: date | None) -> dict[str, int]` and `main() -> None`.
