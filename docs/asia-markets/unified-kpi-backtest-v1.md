# Asia Markets unified KPI backtest — Step 1 contract

Status: Steps 1–6 implemented on 2026-08-12. Step 1 is the metadata-only
contract below; Steps 2–6 (shared package, long-form emitter, MTR actuals
migration, SHKP target split, metric policy) are documented in the sections
after it.

This document defines the first migration step for the MTR, Airlines, and SHKP
forecast/backtest outputs. It is deliberately additive: it does not change a
model calculation, replace an existing wide CSV, or feed either dashboard.

## What Step 1 delivers

The generator is `scripts/build_asia_backtest_registry.py`. It reads the
existing outputs and writes four files under `data/registries/`:

- `asia_backtest_target_registry.csv`: one row per target/period track/model
  contract, with sample-size candidates, PIT quality, default model/baseline,
  and source dependencies. Its `candidate_headline_eligible` flag is
  pre-metric-policy metadata, not the final accuracy decision.
- `asia_backtest_row_status.csv`: one metadata row per source row/model
  combination. This is the value-free skeleton that the later long-form
  emitter can populate with `predicted` and `actual` values.
- `asia_backtest_document_registry.csv`: canonical versus numbered-copy
  classification for `docs/asia-markets/*.md`.
- `asia_backtest_registry_manifest.json`: version, scope, counts, and known
  limitations.

The row-status skeleton already carries the long-form keys and metadata needed
later: entity, target, target period, track, model, PIT grade, evaluation
status, forecast origin, information cutoff, actual availability, and
dependency status. `row_key` is the source-dataset/row/model identity;
`logical_observation_id` identifies the economic target-period observation;
`registry_id` is the target contract key and intentionally repeats across its
observations. SHKP scenario and lookback dimensions are preserved, and this
logical observation key makes cross-source duplicates (such as the MTR 2026
H1 row present in both current source tables) explicit for the later emitter.
For SHKP, scenario and lookback are also encoded into `model_id` (for example,
`trailing_mean_lb3_base`) so a later groupby cannot silently average scenarios.
Prediction and actual values are intentionally absent.
When a source does not preserve a provenance field, the value is explicitly
`not_captured`; it is never inferred from the run retrieval timestamp.

## Quality vocabulary

The PIT vocabulary is taken from the existing Airlines outputs and applied at
row level:

- `A_strict_pit`: issuer announcement date is available and no future KPI
  imputation is used.
- `B_practical_pit`: period-end-only actual timing, derived financial rows, or
  an explicitly pending practical PIT case.
- `C_structural_replay`: the source is a structural/calibration replay rather
  than a strict historical forecast.
- `D_diagnostic_only`: a proxy or diagnostic series that must not become a
  headline accuracy result.

The target-level guard is stricter than a row-level label. A target is not
headline eligible when its valid evaluation rows are structural-only, when it
is diagnostic-only, or when the valid sample is below the period threshold.
Mixed A/B targets can remain eligible when the C rows are explicitly
insufficient or unavailable rather than valid scored observations.

MTR has an explicit look-ahead rule: its FY2024 segment-yield anchor means
2017–2024 actual rows are `C_structural_replay` (historical checks/calibration),
while FY/H1 2025 is the first `B_practical_pit` practical forward observation.
It is not A-grade strict PIT because the patronage source has no historical
release-vintage registry. The independent prior-period-yield track is
`mtr_farebox_walk_forward_oos`, also B-practical until those patronage vintages
exist. The current 2026 forecast is also B, but remains `forecast_only` until an actual is
available. The Ridge residual variant is marked `model_applied=false` and
`has_prediction=false` outside its 2019–2023 structural-replay window when its adjustment
is zero; a copied physics value is not counted as a Ridge prediction.

## Track rules

Tracks are kept separate so the later evaluator cannot double count the same
information:

- `fiscal_year`: FY observations only.
- `half_year_non_overlapping`: H1 and H2 observations for the sequential
  half-year view.
- `ytd_current`: a current incomplete-period forecast. MTR 2026 is typed as
  H1/YTD, not FY, and is excluded from FY accuracy until the actual arrives.
- `monthly_sparse`: SHKP indicative contract activity, retained for coverage
  diagnostics only.

H1/H2/FY are never aggregated into one accuracy score. H2 may be derived from
FY minus H1 in an existing source; its eventual actual availability must use
the FY announcement date when the shared evaluator is built.

The 2026 MTR rows are typed as H1 rather than FY. The annual source uses
`H1/ytd_current`; the dedicated H1 source remains on the
`H1/half_year_non_overlapping` track — the annual-table copy is the duplicate
alias and the H1 source is the preferred one. The registry does not delete
duplicate source rows: `dedup_group_id`,
`dedup_rank`, and `is_primary_source` identify the preferred source.  Airlines
period-KPI rows take priority over the overlapping H1-only rows.  Target-level
headline status is calculated from primary rows; all-source row counts remain
available alongside primary-row counts.  A contract with no primary observation
is marked `duplicate_source_alias` rather than being allowed to inflate sample
size.

## Current source coverage

The registry currently covers:

- MTR annual and H1 farebox/transport-operations backtests;
- Airlines H1 KPI, H1/H2/FY period KPI, earnings model v4, and cost engine v2;
- SHKP indicative sales proxy, skeleton profit replay, and commercial rental
  backtests.

Known classifications include:

- MTR H1 2000–2016 and FY 2000–2018: `no_source_coverage`, not “pending”;
- MTR 2024: calibration; legacy MTR 2025: practical forward validation; the
  chronological `mtr_farebox_walk_forward_oos` track provides the cleaner FY/H1
  prior-period-yield comparison; MTR 2026: current H1/YTD forecast;
- SHKP contract activity: `diagnostic_only`, because it is an indicative
  gross SRPE proxy with sparse coverage and zero-actual months;
- SHKP skeleton/commercial outputs: structural or insufficient-sample
  diagnostics, not headline accuracy;
- Airlines v4: structural replay until historical and live predictor paths
  share one implementation.

The Airlines `analyst_h1_nowcast_v1` source column is mostly empty (only a
small number of rows contain a prediction), so its target is intentionally
`insufficient_sample`; it is not treated as a complete challenger model.
The MTR annual Ridge 2026 row is `insufficient_input_coverage`, not
`current_forecast`, because its residual adjustment is zero outside the
2019–2023 structural-replay window and the copied physics value is not a Ridge prediction.

The target registry distinguishes current forecasts from rows with no source
coverage (`n_forecast_only` versus `n_no_source_coverage`). For SHKP it also
surfaces `model_use`, `research_only`, and whether the input run set was
captured. For MTR and Airlines, input run sets are currently marked
`not_applicable`; this is different from SHKP's `not_captured` dependency gap.

The Step 1 registry declares the policy; the additive Step 3/6 artifacts now
materialize and calculate it. Financial targets use
`scaled_RMSE` as the primary cross-target metric, with `same_period_last_year_rmse`
as the declared scaler and `RMSE|directional_hit_rate` as secondary metrics.
The source tables do not contain those baseline predictions; the additive
long-form/metrics artifacts materialize them, so the target registry reports
`baseline_status=materialized_in_additive_long_form`. Existing source metric
names are retained in `legacy_primary_metric` for reconciliation. The headline
sample guard is 24 observations for monthly targets and 10 for half-year/FY
targets; directional hit rate has a stricter 36/12-observation guard and is not
treated as available merely because RMSE has enough rows.

## Explicitly deferred

Step 1 does not:

- calculate or rename model outputs;
- introduce a shared predictor;
- choose a universal metric or produce `scaled_RMSE`;
- alter SHKP run IDs, storage, or input-run selection;
- replace wide tables;
- change artifact builders, Streamlit, or Cloudflare dashboards;
- merge event studies or trade construction into forecast accuracy.

Those items are now implemented in the Steps 2–6 section below. The important
migration constraint remains additive: keep the wide tables and build a
long-form emitter plus reconciliation view before any consumer switches to the
new contract.

## Regeneration and verification

From the repository root:

```bash
python scripts/build_asia_backtest_registry.py
python -m py_compile scripts/build_asia_backtest_registry.py
pytest -q tests/test_asia_backtest_registry.py
```

The generator is metadata-only. The manifest records this with
`model_calculation_changed=false`, `dashboard_changed=false`, and
`wide_tables_replaced=false`.

## Steps 2–6: shared package, long form, MTR migration, SHKP split, metrics

Implemented on 2026-08-12, additively on top of Step 1.  No wide table, model
calculation, or dashboard consumer changed.

### Step 2 — shared package (`src/common/backtest/`)

- `vocabulary.py`: the Airlines-derived PIT/evaluation vocabulary plus track
  IDs, period types, minimum-row guards, baseline identifiers, and the
  scaler guards (`MIN_SCALER_OVERLAP=2`, `MIN_BASELINE_RMSE=1e-12`).
- `storage.py`: deterministic, content-addressed run storage
  (`BacktestRunSpec.run_id`, `RunArtifactStore`) with file/dataframe
  fingerprints and a stable `asia_backtest_latest.json` pointer.  It does not
  change `src.hk_real_estate.storage` or any ingestion writer.
- `schema.py`: `LONG_FORM_COLUMNS` (47 contract columns) and `METRIC_COLUMNS`
  plus `validate_long_form` (unique row keys, period bounds, vocabulary and
  value/flag consistency checks). `n_structural_excluded` is a metric-table
  field, not a long-form column.
- `metrics.py`: the Step 6 metric policy and shared error-interval emitter (see
  below).

### Step 3 — additive long-form emitter

`scripts/build_asia_backtest_long_form.py` reads the Step 1 registry plus the
existing source tables and emits `data/registries/asia_backtest_long_form.csv`
(5,188 rows: 2,682 primary + 163 source aliases + 2,343 same-period-last-year
baseline rows), a
run-scoped copy under `data/registries/runs/`, and
`data/registries/asia_backtest_reconciliation.json`.

- Value mapping: one explicit `(source_dataset, target_id, model_id) ->
  (prediction column, actual column, unit)` table (MTR HK$m, Airlines RMB mn,
  SHKP HKD/HKD m).
- Model-family column groups models that share inputs (v4 variants,
  cost-engine variants) so they are never counted as independent evidence.
- Baseline rows are flagged `is_baseline=True` with
  `model_id=baseline_same_period_last_year`; the baseline prediction is the
  prior-period actual of the same period type (H1→prior H1, FY→prior FY,
  month→same month last year; H2→prior-year H2).
  Baselines are emitted per declared source/model contract so each contract
  has its own overlap series. The annual MTR Ridge structural alias is the
  explicit exception: it does not emit an unevaluable duplicate baseline.
- Hard gate: every dedup group (same economic observation, same model,
  different source tables) is value-checked; 319 checks pass, zero
  violations.  This gate caught a real contract bug: the H1 table's profit
  prediction (`flat_ask_profit_pred_native_mn`) is operating profit times a
  net-to-operating conversion while the period table's
  (`flat_ask_profit_residual_pred_native_mn`) adds a modelled below-the-line
  residual.  They are different models, so the H1 one is now registered as
  `flat_ask_profit_v1` and the period one stays `flat_ask_residual_v1`.
- Legacy reconciliation: the long form reproduces the legacy summary MAPE
  values within 0.04pp (documented diffs in the reconciliation JSON).

### Step 4 — MTR actuals migration

The official actuals moved out of `scripts/mtr_farebox_revenue_backtest.py`
into `data/normalized/hk_transport/mtr_transport_ops_actuals.csv` (FY
2019–2025 and H1 2017–2025 rows, each with the period document URL, the
official results-announcement URL, `actual_available_at`, and definition).
`_load_transport_ops_actuals()` is the single loader; that provenance is
carried into the annual/H1 source outputs, then the registry and long-form
artifact. `actual_available_at` is the official results-announcement date,
not the local retrieval date or period end. The script still writes the
historical `mtr_h1_transport_operations_actuals.csv` compatibility output,
now with the same release provenance columns.
Rebuilds are byte-identical to the committed processed tables.  The engine
pipeline is `scripts/run_backtest_engine.py` (MTR → registry → long form →
metrics); every stage must exit zero. The default engine run is snapshot-based
and does not fetch the network; pass `--mtr-live` only for an explicit fresh
patronage/ImmD capture. The immutable input bundle records the raw snapshots
used by that MTR rebuild as well as the processed source tables.

### Step 5 — SHKP three-target split

The registry already carries three independent SHKP targets
(`contract_activity_proxy`, `underlying_profit`, `hk_rental_revenue`).
Contract activity stays `D_diagnostic_only` (six model contracts, zero
headline eligibility); skeleton and commercial are `C_structural_replay`.
Tests enforce that no SHKP contract can become headline eligible.

### Step 6 — metric policy and interval scoring

The long-form stage computes and stores
`data/registries/asia_backtest_metrics.csv` (pooled reference rows plus
per-entity rows; only per-entity rows may be final headline contracts),
`asia_backtest_metric_intervals.csv` and its Parquet twin (explicit pooled and
per-entity absolute-error percentiles p10/p25/p50/p75/p90), and a metrics
manifest. The long-form stage also stores all of these metric artifacts inside
the immutable run directory. The standalone
`scripts/build_asia_backtest_metrics.py` remains available for an explicit
compatibility rebuild; the main engine does not run it a second time, so the
long-form stage is the single metrics publisher.

- Final headline eligibility requires per-entity grain, evaluable status +
  A/B grade + minimum independent periods (24 monthly, 10 H1/H2/FY), and at
  least 80% baseline overlap when a same-period-last-year comparison is
  available. Baselines and pooled rows are never headline contracts.
- Directional hit rate is direction-vs-same-period-baseline, with a stricter
  guard (36 monthly, 12 H1/H2/FY) and an explicit status column.
- `scaled_RMSE` and `skill_vs_baseline` are guarded: at least 2 overlapping
  baseline observations, baseline RMSE above `MIN_BASELINE_RMSE`, otherwise
  null (never a misleading extreme).
- Metrics emit both a pooled reference row and one per-entity row for each
  contract. The pooled row is retained for reconciliation only; per-entity is
  the main grain.

### Regeneration and verification

```bash
python scripts/run_backtest_engine.py
python -m py_compile scripts/build_asia_backtest_long_form.py scripts/build_asia_backtest_metrics.py
pytest -q tests/test_asia_backtest_common.py tests/test_asia_backtest_registry.py \
  tests/test_asia_backtest_long_form.py tests/test_asia_backtest_metrics.py \
  tests/test_mtr_farebox_h1_backtest.py
```

Current outputs are regenerated by the commands above. The target registry is
metadata-only and reports candidate eligibility; the value-bearing metrics
artifact is the authority for final headline eligibility. The metrics output
emits explicit pooled reference and per-entity rows, while interval output
uses the same two grains. The manifest records row counts, grain counts and
baseline-coverage status counts; its `headline_metric_ids` distinguish entity,
model and grain so these numbers cannot silently be confused with the older
pooled-only output.
Registry rebuilds are deterministic; long-form dedup value checks (319) pass;
the Airlines overlap reconciliation covers all 216 expected pairs (162
exact-model pairs and 54 intentionally non-comparable profit-model pairs); and
MTR processed outputs are regenerated from the canonical actuals file without
changing model logic. Regression tests cover both the MTR current-forecast to
reported-actual state transition and the publication guard: a failed
reconciliation may create a failed immutable run record, but it cannot replace
the top-level compatibility artifacts or the latest pointer.

### Run directory retention

Every engine invocation writes an immutable directory under
`data/registries/runs/<engine_version>-<hash>/`, and none of it is git
history by default — the whole tree is untracked, matched by
`data/registries/runs/*` in `.gitignore` with narrow re-includes for
`*.parquet` and `*.json`. `.csv` files inside run directories are ignored,
the same policy already applied to `data/normalized/`: the parquet twin is
the artifact of record, and the CSV is a regenerable convenience file that
just bloats history if committed. Every run written by
`RunArtifactStore.write_dataframe` currently also gets a
`write_parquet` twin, so this is a no-op for read access, not a data loss.

Left alone, this directory accumulates without bound — one snapshot per
invocation, each holding a full parquet/JSON artifact set. `scripts/
prune_backtest_runs.py` retires the old ones:

```bash
# see what would be removed, changes nothing (dry run is the default)
python3 scripts/prune_backtest_runs.py --keep 1

# actually delete
python3 scripts/prune_backtest_runs.py --keep 1 --apply
```

`--keep N` retains the N most recent runs by the `created_at` timestamp in
each run's `manifest.json`. The run currently referenced by
`data/registries/asia_backtest_latest.json` is never deleted, regardless of
`--keep` or age — it is looked up by `run_id` and excluded from the deletion
set unconditionally. A run whose `manifest.json` is missing or unreadable is
also never deleted (its recency can't be determined, so it's treated as
protected rather than guessed at). The script refuses to run against any
path that doesn't resolve to `data/registries/runs`, and aborts without
deleting anything if the latest-run pointer is missing or fails to parse.
It never touches the top-level published artifacts directly under
`data/registries/` (`asia_backtest_metrics.csv`/`.parquet`,
`asia_backtest_long_form.csv`/`.parquet`, etc.) — those are the current
compatibility outputs, not run snapshots, and stay force-included in
`.gitignore` as before.
