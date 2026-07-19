# OpenRouter SOTA Backfill and Usage Chart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Backfill a clearly labeled SOTA volume-weighted ATP from the latest Artificial Analysis scores, restore all five original price-index lines, and simplify OpenRouter usage charts to total weekly/daily demand.

**Architecture:** Keep compact derived marts as the source of truth. Extend the existing OpenRouter derived identity/metrics pipeline with a backfilled benchmark mode and explicit original-index/SOTA metric IDs. Make the dashboard consume those rows with a single Tokens/Requests toggle, a Weekly/Daily window control, fixed Total workload intensity, and no price-diagnostics expander.

**Tech Stack:** Python 3.11, pandas, Parquet, Streamlit, Plotly, pytest, GitHub Actions.

## Global Constraints

- Backfilled scores are current-score historical proxies, not point-in-time Artificial Analysis measurements.
- Backfill only to each family’s release date; never show a family before release.
- Collapse variants for SOTA membership, but keep dated/preview/fast/pro/free OpenRouter routes separate for pricing.
- Route matching is exact and fail-closed; no fuzzy pricing joins.
- Volume-weighted ATP is `paid SOTA revenue / paid SOTA tokens`; insufficient traffic remains missing, never zero.
- Preserve the existing original five index definitions and names.
- Keep derived marts compact enough for the Streamlit memory budget.
- Do not stage or modify unrelated untracked `* 2*` files, `.playwright-cli`, output artifacts, or `.config`.

## Files and Responsibilities

- Modify `src/openrouter_derived_data/identity.py`: add explicit backfill mode and status labeling while preserving strict point-in-time mode.
- Modify `config/openrouter_capability_map.json`: add exact routes for the current SOTA/popular families and dated OpenRouter variants.
- Modify `src/openrouter_derived_data/metrics.py`: emit original five indices and `sota_volume_weighted_atp` from the canonical economics/pricing inputs.
- Modify `src/openrouter_derived_data/pipeline.py`: pass backfill mode, validate the new metric contract, and publish the compact mart.
- Modify `dashboard/sections/openrouter.py`: simplify controls, show all original lines plus the one labeled new SOTA line, and explain backfill/coverage.
- Modify `tests/test_openrouter_derived_data.py`: cover backfill ranking, release floors, exact routes, volume-weighted ATP, and guarded gaps.
- Modify `tests/test_dashboard_data.py`: cover chart controls, line labels, daily/weekly behavior, and removal of diagnostic/component controls.
- Modify `.github/workflows/openrouter-derived-daily.yml` only if the new mart contract requires an explicit output assertion.

### Task 1: Add failing identity/backfill tests

**Files:**
- Test: `tests/test_openrouter_derived_data.py`

- [ ] **Step 1: Add a test that the latest AA score snapshot can be backfilled to earlier post-release usage dates.**

```python
def test_rank_capability_families_backfills_latest_scores_after_release(tmp_path: Path) -> None:
    _write_capability_map(tmp_path)
    models = _artificial_analysis_rows_with_one_latest_snapshot()
    ranked = rank_capability_families(
        models,
        pd.Series(["2026-04-25", "2026-07-18"]),
        load_capability_map(tmp_path),
        backfill_latest_snapshot=True,
    )
    assert ranked["usage_date"].astype(str).unique().tolist() == ["2026-04-25", "2026-07-18"]
    assert ranked["model_match_status"].eq("backfilled_current_score_exact_match").all()
    assert ranked["benchmark_snapshot_date"].astype(str).eq("2026-07-18").all()
```

- [ ] **Step 2: Add a test that a family is absent before its release date.**

```python
def test_backfilled_capability_family_never_precedes_release_date(tmp_path: Path) -> None:
    _write_capability_map(tmp_path)
    ranked = rank_capability_families(
        _artificial_analysis_rows_with_one_latest_snapshot(),
        pd.Series(["2026-04-01"]),
        load_capability_map(tmp_path),
        backfill_latest_snapshot=True,
    )
    assert "2026-04-01" not in ranked["usage_date"].astype(str).tolist()
```

- [ ] **Step 3: Run the focused tests and confirm they fail because the backfill argument is not implemented.**

Run: `pytest -q tests/test_openrouter_derived_data.py -k 'backfill_latest_scores or never_precedes_release'`

Expected: FAIL with the current `rank_capability_families` signature/behavior.

### Task 2: Implement backfilled family ranking and exact route coverage

**Files:**
- Modify: `src/openrouter_derived_data/identity.py`
- Modify: `config/openrouter_capability_map.json`
- Test: `tests/test_openrouter_derived_data.py`

- [ ] **Step 1: Add `backfill_latest_snapshot: bool = False` to `rank_capability_families`.** In backfill mode, select the latest available benchmark snapshot for every usage date, filter candidates by `release_date <= usage_date`, rank the full family universe before filtering to curated identities, and set `model_match_status` to `backfilled_current_score_exact_match` for mapped rows.
- [ ] **Step 2: Preserve strict point-in-time behavior when the flag is false and retain the existing unmapped-rank gap behavior.**
- [ ] **Step 3: Add exact dated routes for the observed SOTA/popular families, including `anthropic/claude-5-fable-20260609`, `openai/gpt-5.5-20260423`, `openai/gpt-5.5-pro-20260423`, `openai/gpt-5.6-sol-20260709`, `openai/gpt-5.6-sol-pro-20260709`, `openai/gpt-5.6-terra-20260709`, `openai/gpt-5.6-terra-pro-20260709`, `moonshotai/kimi-k3-20260715`, `z-ai/glm-5.2-20260616`, and `x-ai/grok-4.5-20260708`, using their first observed activity/catalog date as route effective dates.
- [ ] **Step 4: Add tests that route variants remain separate for pricing while sharing one family rank, and that a future route cannot leak backward.**
- [ ] **Step 5: Run:** `pytest -q tests/test_openrouter_derived_data.py -k 'backfill or route or capability'` and confirm all focused identity tests pass.
- [ ] **Step 6: Commit:** `git add src/openrouter_derived_data/identity.py config/openrouter_capability_map.json tests/test_openrouter_derived_data.py && git commit -m "Add backfilled OpenRouter capability rankings"`.

### Task 3: Add original price indices and volume-weighted SOTA ATP

**Files:**
- Modify: `src/openrouter_derived_data/metrics.py`
- Modify: `src/openrouter_derived_data/pipeline.py`
- Test: `tests/test_openrouter_derived_data.py`

- [ ] **Step 1: Add failing metric tests for exact names and formulas.**

```python
def test_price_metrics_emit_original_indices_and_volume_weighted_sota_atp() -> None:
    result = compute_price_metrics(
        _economics(),
        _pricing_history(),
        _price_rankings(),
        _price_capability_map(),
        backfilled_rankings=True,
    )
    metrics = set(result["metric_id"])
    assert {
        "original_spend_weighted_tei",
        "original_cpi_workload_basket",
        "original_volume_weighted_tei",
        "original_frontier_tei",
        "original_value_tei",
        "sota_volume_weighted_atp",
    } <= metrics
    sota = result[result["metric_id"].eq("sota_volume_weighted_atp")].iloc[-1]
    assert sota["value"] == pytest.approx(sota["numerator"] / sota["denominator"] * 1_000_000)
```

- [ ] **Step 2: Run the new tests and confirm the metric IDs/formula fail before implementation.**
- [ ] **Step 3: Implement the five original index formulas from the pre-derived dashboard behavior using canonical economics rows; retain the existing market/cohort calculations for compatibility.**
- [ ] **Step 4: Implement `sota_volume_weighted_atp` as paid SOTA revenue divided by paid SOTA tokens, using backfilled rankings and exact effective routes. Require at least three observed and priced SOTA families; emit `pd.NA` otherwise.**
- [ ] **Step 5: Pass `backfill_latest_snapshot=True` from `OpenRouterDerivedPipeline.build`, update output validation to require a non-missing original volume-weighted index and permit guarded SOTA gaps, and keep the marts’ natural keys unique.**
- [ ] **Step 6: Run:** `pytest -q tests/test_openrouter_derived_data.py` and `python -m compileall -q src/openrouter_derived_data`.
- [ ] **Step 7: Commit:** `git add src/openrouter_derived_data/metrics.py src/openrouter_derived_data/pipeline.py tests/test_openrouter_derived_data.py && git commit -m "Add original price indices and SOTA ATP"`.

### Task 4: Simplify the dashboard usage and price views

**Files:**
- Modify: `dashboard/sections/openrouter.py`
- Test: `tests/test_dashboard_data.py`

- [ ] **Step 1: Add failing tests named `test_usage_window_defaults_to_weekly_and_supports_daily`, `test_workload_state_is_fixed_to_total_without_component_control`, `test_average_price_state_has_all_original_indices_and_backfilled_sota_label`, and `test_price_diagnostics_are_not_rendered`. Assert the window state is `Weekly`, the daily token pivot uses provider activity, the workload metric ID is `total_tokens_per_request`, and the six displayed labels are the five original names plus `SOTA Volume-Weighted ATP (backfilled AA score)`.**
- [ ] **Step 2: Run:** `pytest -q tests/test_dashboard_data.py -k 'usage_economics or average_price'` and confirm the current controls/labels fail the new contract.
- [ ] **Step 3: Add a `Window` control for Tokens/Requests with `Weekly` default and `Daily` option. Use the existing weekly total token/request pivots; use daily provider activity totals for Tokens and explicitly fall back to weekly Requests with a source note because provider daily request counts are unavailable.**
- [ ] **Step 4: Keep Workload Intensity as Total only; remove the Component selector and call `_workload_intensity_section_state(datasets, "Total")` directly.**
- [ ] **Step 5: Remove the Price diagnostics expander and render the five original index labels plus `SOTA Volume-Weighted ATP (backfilled AA score)` by default. Keep guarded missing values as gaps and show a concise coverage/backfill note.**
- [ ] **Step 6: Run:** `pytest -q tests/test_dashboard_data.py` and verify the test suite passes.
- [ ] **Step 7: Commit:** `git add dashboard/sections/openrouter.py tests/test_dashboard_data.py && git commit -m "Simplify OpenRouter usage and price charts"`.

### Task 5: Regenerate compact marts and validate the workflow contract

**Files:**
- Modify: `.github/workflows/openrouter-derived-daily.yml` only if output assertions need updating.
- Update: `data/normalized/marts/openrouter_usage_economics_daily.parquet`
- Update: `data/normalized/marts/openrouter_workload_intensity_models.parquet` only if regenerated bytes differ.

- [ ] **Step 1: Run the real pipeline:** `PYTHONPATH=src python -m openrouter_derived_data.cli --base-dir . build --today 2026-07-19`.
- [ ] **Step 2: Verify both marts are non-empty, naturally unique, under 10 MB in memory/on disk, and price rows end at 2026-07-18 with complete derived provenance.**
- [ ] **Step 3: Verify at least one `sota_volume_weighted_atp` value is non-null where route/activity coverage permits; otherwise preserve the explicit guarded-gap note and report the coverage count.**
- [ ] **Step 4: Run:** `pytest -q tests/test_workflow_reliability.py` and `git diff --check`.
- [ ] **Step 5: Commit:** `git add data/normalized/marts/openrouter_usage_economics_daily.parquet data/normalized/marts/openrouter_workload_intensity_models.parquet .github/workflows/openrouter-derived-daily.yml && git commit -m "Regenerate OpenRouter derived marts"`.

### Task 6: Full verification and local browser QA

- [ ] **Step 1: Run:** `PYTHONDONTWRITEBYTECODE=1 python -B -m pytest -q` and require zero failures.
- [ ] **Step 2: Run:** `PYTHONDONTWRITEBYTECODE=1 python -B -m compileall -q src dashboard tests`.
- [ ] **Step 3: Start Streamlit on port 8501 and verify the OpenRouter Usage & Economics section:** Tokens/Requests toggle, Weekly default, Daily option, fixed Total workload, all six price lines, visible backfill label, and no Price diagnostics/Component controls.
- [ ] **Step 4: Verify no console errors and stop the local server after QA.**
- [ ] **Step 5: Run `git status --short` and confirm only intended tracked changes are staged/committed; preserve unrelated untracked files.
