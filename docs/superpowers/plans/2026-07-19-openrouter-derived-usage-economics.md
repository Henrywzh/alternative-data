# OpenRouter Derived Usage and Economics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add defensible workload-intensity and SOTA-pricing measures to OpenRouter Usage & Economics without changing raw-source granularity or adding external requests.

**Architecture:** A focused `openrouter_derived_data` package will join existing normalized OpenRouter activity, pricing economics, catalog history, and Artificial Analysis snapshots into two compact long-format Parquet marts. A no-network daily workflow will refresh those marts after source workflows, while Streamlit will load only the compact outputs and preserve the existing weekly Tokens and Requests views.

**Tech Stack:** Python 3.11, pandas, PyArrow/Parquet, pytest, Streamlit, Plotly, GitHub Actions YAML.

## Global Constraints

- Add no new external scraping, API routes, or credentials.
- Do not modify or reduce existing raw and normalized source datasets.
- SOTA is ranks 1–5 across distinct model families; Frontier Contenders is ranks 6–10.
- A model family can occupy only one rank, represented by its highest-scoring eligible configuration.
- Capability membership requires an exact canonical ID or curated alias; fuzzy matching cannot assign a tier.
- New capability-price series use benchmark snapshots, release dates, and OpenRouter prices available on or before each usage date.
- Preserve the existing realized-market earliest-price backcast and label it `backcast_earliest_pricing`; never apply it to SOTA or Frontier Contender series.
- Emit SOTA list and realized measures only with at least 3/5 valid families.
- Keep `fast`, `preview`, free, reasoning, and non-reasoning routes priced separately.
- Workload Intensity must divide tokens and requests from the same `openrouter_model_activity` rows.
- Daily rolling ratios are ratios of rolling sums, not averages of daily ratios.
- Exclude the incomplete current UTC day and never replace guarded or missing metrics with zero.
- Persist compact long-format Parquet only; do not add duplicate CSV marts.
- Follow the existing dashboard chart, typography, KPI-card, date-formatting, and source-caption conventions.

---

## File Map

- Create `src/openrouter_derived_data/__init__.py`: public package exports.
- Create `src/openrouter_derived_data/identity.py`: curated-map loading, point-in-time family ranking, and exact route membership.
- Create `src/openrouter_derived_data/metrics.py`: workload-intensity and price-index computations.
- Create `src/openrouter_derived_data/pipeline.py`: input loading, quality validation, and atomic Parquet writes.
- Create `src/openrouter_derived_data/cli.py`: `build` command used locally and by Actions.
- Create `config/openrouter_capability_map.json`: versioned Artificial Analysis family IDs and exact OpenRouter route mappings.
- Create `tests/test_openrouter_derived_data.py`: unit and integration coverage for the derived package.
- Create `.github/workflows/openrouter-derived-daily.yml`: no-network daily mart refresh.
- Modify `pyproject.toml`: expose `openrouter-derived-data` CLI.
- Modify `dashboard/data.py`: register and project the two compact marts.
- Modify `dashboard/app.py`: load the derived domain only for OpenRouter Intelligence.
- Modify `dashboard/sections/openrouter.py`: add Workload Intensity and capability-aware Average Price views.
- Modify `tests/test_dashboard_data.py`: registry, state, coverage, and fallback tests.
- Modify `tests/test_workflow_reliability.py`: enforce the derived workflow's timeout and no-network contract.
- Generate `data/normalized/marts/openrouter_usage_economics_daily.parquet` and `data/normalized/marts/openrouter_workload_intensity_models.parquet` only after all package tests pass.

---

### Task 1: Curated Capability Families and Point-in-Time Ranking

**Files:**
- Create: `config/openrouter_capability_map.json`
- Create: `src/openrouter_derived_data/__init__.py`
- Create: `src/openrouter_derived_data/identity.py`
- Test: `tests/test_openrouter_derived_data.py`

**Interfaces:**
- Produces: `CapabilityMap`, `load_capability_map(base_dir: Path) -> CapabilityMap`
- Produces: `rank_capability_families(models: pd.DataFrame, usage_dates: pd.Series, capability_map: CapabilityMap) -> pd.DataFrame`
- Produces: `compatible_activity_ids(capability_map: CapabilityMap, aa_model_id: str) -> frozenset[str]`
- Ranking output columns: `usage_date`, `benchmark_snapshot_date`, `family_id`, `family_rank`, `capability_tier`, `representative_aa_model_id`, `representative_model_name`, `intelligence_index`, `release_date`, `model_match_status`, `methodology_version`

- [ ] **Step 1: Write failing curated-map and family-collapse tests**

Add fixtures with two GPT-5.6 Sol configurations sharing one family, plus Kimi K3, Claude Fable 5, GLM-5.2, and five other families. Assert one GPT family slot, deterministic rank order, release-date exclusion, snapshot-as-of selection, and no automatic tier for an unmapped row:

```python
def test_rank_capability_families_collapses_configurations_and_uses_asof_snapshot(tmp_path: Path) -> None:
    capability_map = _write_capability_map(tmp_path)
    models = _artificial_analysis_rows()
    ranked = rank_capability_families(
        models,
        pd.Series(["2026-07-10", "2026-07-18"]),
        load_capability_map(tmp_path),
    )

    july_18 = ranked[ranked["usage_date"] == "2026-07-18"]
    assert len(july_18[july_18["family_id"] == "openai/gpt-5.6-sol"]) == 1
    assert july_18.iloc[:5]["capability_tier"].eq("sota").all()
    assert july_18.iloc[5:10]["capability_tier"].eq("frontier_contender").all()
    assert "future/model" not in set(ranked[ranked["usage_date"] == "2026-07-10"]["family_id"])
    assert "unmapped/model" not in set(july_18["family_id"])
```

- [ ] **Step 2: Run the focused test and verify the missing module failure**

Run: `python -m pytest -q tests/test_openrouter_derived_data.py::test_rank_capability_families_collapses_configurations_and_uses_asof_snapshot`

Expected: FAIL during import because `openrouter_derived_data.identity` does not exist.

- [ ] **Step 3: Add the versioned capability-map schema**

Create JSON with this exact structure and populate every Artificial Analysis configuration that appears in the top ten of any stored snapshot. `openrouter_model_ids` contains only inspected, exact, capability-compatible routes; leave it empty when no defensible route exists:

```json
{
  "methodology_version": "openrouter-derived-v1",
  "models": [
    {
      "aa_model_id": "cd55210d-358e-4df1-ba9c-9acb5f186cc9",
      "family_id": "anthropic/claude-fable-5",
      "openrouter_model_ids": ["anthropic/claude-fable-5"]
    },
    {
      "aa_model_id": "d93edfe8-bf35-49ad-b56e-b18116142a1c",
      "family_id": "openai/gpt-5.6-sol",
      "openrouter_model_ids": ["openai/gpt-5.6-sol", "openai/gpt-5.6-sol-pro"]
    },
    {
      "aa_model_id": "d998db47-9b67-4727-a2bb-2e1261020ac0",
      "family_id": "openai/gpt-5.6-sol",
      "openrouter_model_ids": ["openai/gpt-5.6-sol", "openai/gpt-5.6-sol-pro"]
    },
    {
      "aa_model_id": "f7d2fc3e-1f7b-405f-818c-07952a4af78f",
      "family_id": "moonshotai/kimi-k3",
      "openrouter_model_ids": ["moonshotai/kimi-k3"]
    },
    {
      "aa_model_id": "f7a4ea75-e548-4069-80d4-9be8bc7c009b",
      "family_id": "z-ai/glm-5.2",
      "openrouter_model_ids": ["z-ai/glm-5.2"]
    }
  ]
}
```

Use this audit command before finalizing the file:

```bash
python - <<'PY'
import json
import pandas as pd
from pathlib import Path
models = pd.read_parquet('data/normalized/artificial_analysis/artificial_analysis_models_daily.parquet')
models['as_of_date'] = pd.to_datetime(models['as_of_date'])
candidates = models.sort_values(['as_of_date', 'intelligence_index'], ascending=[True, False]).groupby('as_of_date').head(10)
mapped = {row['aa_model_id'] for row in json.loads(Path('config/openrouter_capability_map.json').read_text())['models']}
missing = candidates.loc[~candidates['model_id'].isin(mapped), ['as_of_date', 'model_id', 'model_name']]
assert missing.empty, missing.to_string(index=False)
print(f'curated top-ten configurations: {len(mapped)}')
PY
```

Expected: exit 0 and a non-zero curated count.

- [ ] **Step 4: Implement strict map loading and family ranking**

Implement immutable records and deterministic family selection. Normalize dates to UTC-naive days, filter `as_of_date <= usage_date` and `release_date <= usage_date`, choose the latest snapshot, merge only on exact `model_id`, collapse by `family_id`, and rank with stable tie-breaks:

```python
@dataclass(frozen=True)
class CapabilityEntry:
    aa_model_id: str
    family_id: str
    openrouter_model_ids: frozenset[str]


@dataclass(frozen=True)
class CapabilityMap:
    methodology_version: str
    entries: tuple[CapabilityEntry, ...]

    @property
    def by_aa_model_id(self) -> dict[str, CapabilityEntry]:
        return {entry.aa_model_id: entry for entry in self.entries}


def _tier(rank: int) -> str:
    if rank <= 5:
        return "sota"
    if rank <= 10:
        return "frontier_contender"
    return "broader_scored_market"
```

For each date, select representatives with:

```python
eligible = eligible.sort_values(
    ["family_id", "intelligence_index", "release_date", "model_id"],
    ascending=[True, False, False, True],
).drop_duplicates("family_id", keep="first")
eligible = eligible.sort_values(
    ["intelligence_index", "release_date", "family_id"],
    ascending=[False, False, True],
).reset_index(drop=True)
eligible["family_rank"] = range(1, len(eligible) + 1)
eligible["capability_tier"] = eligible["family_rank"].map(_tier)
```

- [ ] **Step 5: Run identity tests and commit**

Run: `python -m pytest -q tests/test_openrouter_derived_data.py -k 'capability or family or rank'`

Expected: all selected tests PASS.

Commit:

```bash
git add config/openrouter_capability_map.json src/openrouter_derived_data/__init__.py src/openrouter_derived_data/identity.py tests/test_openrouter_derived_data.py
git commit -m "Add point-in-time OpenRouter capability families"
```

---

### Task 2: Workload Intensity Metrics

**Files:**
- Create: `src/openrouter_derived_data/metrics.py`
- Modify: `src/openrouter_derived_data/__init__.py`
- Modify: `tests/test_openrouter_derived_data.py`

**Interfaces:**
- Produces: `compute_workload_intensity_daily(activity: pd.DataFrame, *, today: date | None = None) -> pd.DataFrame`
- Produces: `compute_workload_intensity_models(activity: pd.DataFrame, *, today: date | None = None, window_days: int = 30) -> pd.DataFrame`
- Daily output uses the `openrouter_usage_economics_daily` schema and metric IDs `total_tokens_per_request`, `prompt_tokens_per_request`, and `completion_tokens_per_request` for rolling windows 1 and 7.
- Model output uses the exact schema from the approved specification.

- [ ] **Step 1: Write failing ratio-of-sums, current-day, and share tests**

Use two models where the arithmetic mean of ratios differs from the ratio of sums:

```python
def test_workload_intensity_uses_matching_rows_and_rolling_ratio_of_sums() -> None:
    activity = pd.DataFrame([
        {"usage_date": "2026-07-16", "model_permaslug": "a/model", "entity_id": "a", "total_tokens": 1000, "prompt_tokens": 800, "completion_tokens": 200, "request_count": 10},
        {"usage_date": "2026-07-16", "model_permaslug": "b/model", "entity_id": "b", "total_tokens": 9000, "prompt_tokens": 6000, "completion_tokens": 3000, "request_count": 90},
        {"usage_date": "2026-07-17", "model_permaslug": "a/model", "entity_id": "a", "total_tokens": 4000, "prompt_tokens": 3000, "completion_tokens": 1000, "request_count": 20},
        {"usage_date": "2026-07-18", "model_permaslug": "a/model", "entity_id": "a", "total_tokens": 999999, "prompt_tokens": 1, "completion_tokens": 1, "request_count": 1},
    ])
    result = compute_workload_intensity_daily(activity, today=date(2026, 7, 18))
    total_1d = result[(result.metric_id == "total_tokens_per_request") & (result.rolling_window_days == 1)]
    assert total_1d.set_index("usage_date").loc["2026-07-16", "value"] == pytest.approx(100.0)
    total_7d = result[(result.metric_id == "total_tokens_per_request") & (result.rolling_window_days == 7)]
    assert total_7d.iloc[-1]["value"] == pytest.approx(14000 / 120)
    assert "2026-07-18" not in set(result["usage_date"])
```

Also assert the 30-day model table uses one eligible row set, token/request shares each sum to 1, `intensity_ratio == token_share / request_share`, and zero-request rows are excluded and counted.

- [ ] **Step 2: Run tests and verify missing function failures**

Run: `python -m pytest -q tests/test_openrouter_derived_data.py -k workload`

Expected: FAIL because the workload functions are not implemented.

- [ ] **Step 3: Implement normalized activity preparation and daily metrics**

Create a private `_prepare_activity()` that coerces dates/numerics, excludes dates on or after `today`, excludes non-positive/missing requests from ratios, and carries `excluded_zero_request_rows`. Group daily numerators and denominators, then compute rolling metrics as:

The seven-day result must be a ratio of rolling sums, never an arithmetic mean of the daily ratios.

```python
daily = eligible.groupby("usage_date", as_index=False).agg(
    total_tokens=("total_tokens", "sum"),
    prompt_tokens=("prompt_tokens", "sum"),
    completion_tokens=("completion_tokens", "sum"),
    request_count=("request_count", "sum"),
    observed_model_count=("model_permaslug", "nunique"),
)
for window in (1, 7):
    rolling_requests = daily["request_count"].rolling(window, min_periods=1).sum()
    for metric_id, source_column in TOKEN_METRICS.items():
        rolling_tokens = daily[source_column].rolling(window, min_periods=1).sum()
        values = rolling_tokens / rolling_requests.replace(0, pd.NA)
```

Emit `dataset_id`, `source_url`, `source_run_id`, `scraped_at`, numerator, denominator, coverage counts, and `methodology_version="openrouter-derived-v1"` on every long-format row.

- [ ] **Step 4: Implement the latest-30-complete-day model table**

Set `window_end_date` to the latest eligible date and `window_start_date` to `window_end_date - 29 days`. Aggregate by canonical `model_permaslug` and company `entity_id`; compute shares from the same grouped frame and leave intensity missing when request share is zero.

- [ ] **Step 5: Run workload tests and commit**

Run: `python -m pytest -q tests/test_openrouter_derived_data.py -k workload`

Expected: all selected tests PASS.

Commit:

```bash
git add src/openrouter_derived_data/__init__.py src/openrouter_derived_data/metrics.py tests/test_openrouter_derived_data.py
git commit -m "Add OpenRouter workload intensity metrics"
```

---

### Task 3: Capability-Aware Price Indices and Coverage Guards

**Files:**
- Modify: `src/openrouter_derived_data/metrics.py`
- Modify: `src/openrouter_derived_data/__init__.py`
- Modify: `tests/test_openrouter_derived_data.py`

**Interfaces:**
- Consumes: ranking output from `rank_capability_families()` and exact routes from `CapabilityMap`.
- Produces: `compute_price_metrics(economics: pd.DataFrame, pricing: pd.DataFrame, rankings: pd.DataFrame, capability_map: CapabilityMap) -> pd.DataFrame`
- Output metric IDs: `realized_market_average`, `sota_median_list_price`, `realized_sota_price`, `frontier_contenders_median_list_price`, `premium_priced_realized`, `mid_priced_realized`, `low_priced_realized`, `fixed_workload_basket`.

- [ ] **Step 1: Write failing SOTA list-price and realized-price tests**

Create five SOTA families with distinct prices, two configurations in one family, one future price, one free route, and one `fast` route with a higher price. Assert:

```python
def test_sota_prices_use_distinct_families_strict_asof_and_minimum_coverage() -> None:
    result = compute_price_metrics(_economics(), _pricing_history(), _rankings(), _capability_map())
    list_price = _metric(result, "2026-07-17", "sota_median_list_price")
    assert list_price.value == pytest.approx(3.0)
    assert list_price.priced_family_count == 5
    realized = _metric(result, "2026-07-17", "realized_sota_price")
    assert realized.value == pytest.approx(realized.numerator / realized.denominator * 1_000_000)
    assert realized.observed_family_count >= 3
    assert realized.excluded_free_tokens > 0
```

Add separate tests asserting: two priced families produce a missing SOTA list value; two observed families produce a missing realized value; future prices do not match; `fast` keeps its own price; lower-capability siblings are excluded; the legacy market line retains `backcast_earliest_pricing` while SOTA lines do not.

- [ ] **Step 2: Run price tests and verify failures**

Run: `python -m pytest -q tests/test_openrouter_derived_data.py -k price`

Expected: FAIL because `compute_price_metrics` is missing.

- [ ] **Step 3: Implement strict exact-route as-of list pricing**

Prepare catalog pricing with exact `model_id`, normalized `snapshot_ts`, prompt price, completion price, and free-route status. For each ranked usage date and representative AA model, expand only the curated exact route IDs, then select the last snapshot with `snapshot_ts <= usage_date`.

Calculate fixed-blend dollars per million as:

```python
priced["blended_price_per_million"] = (
    priced["pricing_prompt"] * 0.977 + priced["pricing_completion"] * 0.023
) * 1_000_000
```

Group first by family so multiple compatible routes cannot duplicate a family; use the median family price. Emit SOTA only with `priced_family_count >= 3`, and use the same rule for Frontier Contenders.

- [ ] **Step 4: Implement realized market, realized SOTA, and renamed price cohorts**

For each day, use paid, priced economics rows. Preserve existing market provenance from `pricing_join_status`, including `backcast_earliest_pricing`. For SOTA, join only exact compatible routes for that date's representative configurations and reject any pricing snapshot after the usage date.

Compute every realized metric from summed revenue and tokens:

```python
value = estimated_revenue.sum() / total_tokens.sum() * 1_000_000
```

Classify price-only cohorts with the existing fixed blend:

```python
cohort = pd.Series("mid_priced", index=rows.index)
cohort.loc[rows["blended_price"] >= 2.0e-6] = "premium_priced"
cohort.loc[rows["blended_price"] < 0.5e-6] = "low_priced"
```

Calculate seven-day realized lines from rolling revenue divided by rolling tokens. Apply the 3/5 observed-and-priced family guard after forming each seven-day window. Count free, unpriced, and included paid tokens separately.

- [ ] **Step 5: Preserve the fixed workload basket and validate output keys**

Build the fixed basket from the realized cohort lines with weights 50% premium-priced, 40% mid-priced, and 10% low-priced. Do not forward-fill a missing cohort across unsupported dates; emit a missing basket value with coverage fields instead.

- [ ] **Step 6: Run price and identity tests and commit**

Run: `python -m pytest -q tests/test_openrouter_derived_data.py -k 'price or capability or family'`

Expected: all selected tests PASS.

Commit:

```bash
git add src/openrouter_derived_data/__init__.py src/openrouter_derived_data/metrics.py tests/test_openrouter_derived_data.py
git commit -m "Add guarded SOTA price indices"
```

---

### Task 4: Derived Pipeline, Atomic Storage, and CLI

**Files:**
- Create: `src/openrouter_derived_data/pipeline.py`
- Create: `src/openrouter_derived_data/cli.py`
- Modify: `src/openrouter_derived_data/__init__.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_openrouter_derived_data.py`

**Interfaces:**
- Produces: `OpenRouterDerivedPipeline(base_dir: Path)`
- Produces: `OpenRouterDerivedPipeline.build(*, today: date | None = None) -> dict[str, int]`
- CLI: `python -m openrouter_derived_data.cli --base-dir . build [--today YYYY-MM-DD]`
- Writes only `data/normalized/marts/openrouter_usage_economics_daily.parquet` and `data/normalized/marts/openrouter_workload_intensity_models.parquet`.

- [ ] **Step 1: Write a failing end-to-end pipeline test**

Seed a temporary repository with the four required input Parquets and the curated JSON. Assert both outputs exist, schemas are exact, row counts are non-zero, and a failed build leaves pre-existing bytes unchanged:

```python
def test_pipeline_builds_both_marts_and_preserves_last_valid_files_on_failure(tmp_path: Path) -> None:
    _seed_pipeline_inputs(tmp_path)
    result = OpenRouterDerivedPipeline(tmp_path).build(today=date(2026, 7, 19))
    assert result["openrouter_usage_economics_daily"] > 0
    assert result["openrouter_workload_intensity_models"] > 0
    economics_path = tmp_path / "data/normalized/marts/openrouter_usage_economics_daily.parquet"
    previous = economics_path.read_bytes()
    (tmp_path / "data/normalized/openrouter/openrouter_model_activity.parquet").unlink()
    with pytest.raises(FileNotFoundError):
        OpenRouterDerivedPipeline(tmp_path).build(today=date(2026, 7, 19))
    assert economics_path.read_bytes() == previous
```

- [ ] **Step 2: Run the pipeline test and verify failure**

Run: `python -m pytest -q tests/test_openrouter_derived_data.py -k pipeline`

Expected: FAIL because `OpenRouterDerivedPipeline` does not exist.

- [ ] **Step 3: Implement explicit input loading and quality validation**

Load:

```python
activity = pd.read_parquet(base_dir / "data/normalized/openrouter/openrouter_model_activity.parquet")
economics = pd.read_parquet(base_dir / "data/normalized/marts/daily_provider_economics.parquet")
pricing = pd.read_parquet(base_dir / "data/normalized/compute_availability/raw_openrouter_models.parquet")
models = pd.read_parquet(base_dir / "data/normalized/artificial_analysis/artificial_analysis_models_daily.parquet")
```

Raise before writing when an input is missing, required columns are missing, no complete-day activity exists, no Artificial Analysis snapshot exists, natural keys duplicate, or all output values are missing. Allow guarded SOTA gaps when Workload Intensity and market-price outputs remain valid.

- [ ] **Step 4: Implement atomic Parquet-only writes**

Write both completed frames to temporary files in the destination directory, read them back to verify schema and row count, then replace final paths only after both temporary files validate:

```python
temporary = destination.with_suffix(".parquet.tmp")
frame.to_parquet(temporary, index=False)
verified = pd.read_parquet(temporary)
if list(verified.columns) != list(frame.columns) or len(verified) != len(frame):
    raise ValueError(f"Failed to verify {destination.name}")
temporary.replace(destination)
```

Ensure exception cleanup removes temporary files but never existing final files.

- [ ] **Step 5: Add CLI and project entry point**

Add to `pyproject.toml`:

```toml
openrouter-derived-data = "openrouter_derived_data.cli:main"
```

The CLI parses `--today` as an optional ISO date, runs `build`, and prints one deterministic `<dataset_id>: <rows> rows` line per output.

- [ ] **Step 6: Run package tests and commit**

Run: `python -m pytest -q tests/test_openrouter_derived_data.py`

Expected: all tests PASS.

Commit:

```bash
git add pyproject.toml src/openrouter_derived_data tests/test_openrouter_derived_data.py
git commit -m "Add OpenRouter derived metrics pipeline"
```

---

### Task 5: Reliable No-Network Daily Workflow and Seeded Marts

**Files:**
- Create: `.github/workflows/openrouter-derived-daily.yml`
- Modify: `tests/test_workflow_reliability.py`
- Generate: `data/normalized/marts/openrouter_usage_economics_daily.parquet`
- Generate: `data/normalized/marts/openrouter_workload_intensity_models.parquet`

**Interfaces:**
- Consumes: `openrouter-derived-data --base-dir . build`
- Produces: committed compact marts and a manually dispatchable scheduled action.

- [ ] **Step 1: Write failing workflow-contract tests**

Add assertions that the workflow has schedule and dispatch triggers, a 20-minute timeout, no secret references, no collection CLI, and only stages the two derived files:

```python
def test_openrouter_derived_workflow_is_bounded_and_no_network() -> None:
    workflow = (WORKFLOWS / "openrouter-derived-daily.yml").read_text(encoding="utf-8")
    assert "timeout-minutes: 20" in workflow
    assert "workflow_dispatch:" in workflow
    assert "openrouter-derived-data --base-dir . build" in workflow
    assert "secrets." not in workflow
    assert "openrouter_data.cli" not in workflow
    assert "openrouter_official_data.cli" not in workflow
```

- [ ] **Step 2: Run workflow tests and verify the missing-file failure**

Run: `python -m pytest -q tests/test_workflow_reliability.py`

Expected: FAIL because `.github/workflows/openrouter-derived-daily.yml` does not exist.

- [ ] **Step 3: Create the scheduled workflow**

Use a daily `09:30 UTC` schedule, `workflow_dispatch`, contents-write permission, `concurrency` with `cancel-in-progress: false`, `actions/checkout@v7` with `fetch-depth: 0`, `actions/setup-python@v6`, `python -m pip install -e .[dev]`, the derived CLI, focused tests, and a retrying pull-rebase/push loop matching the OpenRouter Official workflow.

The commit step must run:

```bash
git add data/normalized/marts/openrouter_usage_economics_daily.parquet \
        data/normalized/marts/openrouter_workload_intensity_models.parquet
if git diff --staged --quiet; then
  echo "No OpenRouter derived metric changes to commit"
  exit 0
fi
git commit -m "chore: update OpenRouter derived metrics [$(date -u +%Y-%m-%d)]"
```

- [ ] **Step 4: Run workflow validation and generate real local marts**

Run:

```bash
python -m pytest -q tests/test_workflow_reliability.py tests/test_openrouter_derived_data.py
python -m openrouter_derived_data.cli --base-dir . build
python - <<'PY'
import pandas as pd
paths = [
    'data/normalized/marts/openrouter_usage_economics_daily.parquet',
    'data/normalized/marts/openrouter_workload_intensity_models.parquet',
]
for path in paths:
    frame = pd.read_parquet(path)
    assert not frame.empty, path
    print(path, len(frame), frame.memory_usage(deep=True).sum())
PY
```

Expected: all tests PASS; both files have non-zero rows and report compact in-memory byte counts.

- [ ] **Step 5: Commit workflow and generated marts**

```bash
git add .github/workflows/openrouter-derived-daily.yml tests/test_workflow_reliability.py data/normalized/marts/openrouter_usage_economics_daily.parquet data/normalized/marts/openrouter_workload_intensity_models.parquet
git commit -m "Automate compact OpenRouter derived metrics"
```

---

### Task 6: Dashboard Registry and Projected Loading

**Files:**
- Modify: `dashboard/data.py`
- Modify: `dashboard/app.py`
- Modify: `tests/test_dashboard_data.py`

**Interfaces:**
- Produces dataset IDs `openrouter_usage_economics_daily` and `openrouter_workload_intensity_models` in domain `openrouter_derived`.
- Maps `openrouter_derived` to `data/normalized/marts`.
- Adds `openrouter_derived` only to the `OpenRouter Intelligence` section domain tuple.

- [ ] **Step 1: Write failing registry and projection tests**

Assert both datasets have compact projections, load from `marts`, and are requested only for OpenRouter Intelligence:

```python
def test_openrouter_derived_registry_uses_compact_mart_projection(tmp_path: Path) -> None:
    assert dataset_source_for_domain("openrouter_derived") == "marts"
    assert DOMAIN_ORDER["openrouter_derived"] == [
        "openrouter_usage_economics_daily",
        "openrouter_workload_intensity_models",
    ]
    assert len(OPENROUTER_LOAD_COLUMNS["openrouter_usage_economics_daily"]) < 30
    assert len(OPENROUTER_LOAD_COLUMNS["openrouter_workload_intensity_models"]) < 25
```

Also assert `SECTION_DOMAIN_MAP["OpenRouter Intelligence"]` contains `openrouter_derived`, while Models and Workloads do not.

- [ ] **Step 2: Run registry tests and verify failures**

Run: `python -m pytest -q tests/test_dashboard_data.py -k openrouter_derived_registry`

Expected: FAIL because the registry entries do not exist.

- [ ] **Step 3: Register exact schemas and the `marts` source mapping**

Add both `DATASET_REGISTRY` entries with natural keys:

```python
"openrouter_usage_economics_daily": ["usage_date", "metric_id", "cohort_id", "rolling_window_days"],
"openrouter_workload_intensity_models": ["window_end_date", "model_id"],
```

Add their exact columns to `OPENROUTER_LOAD_COLUMNS`, add the domain list to `DOMAIN_ORDER`, and return `"marts"` for `dataset_source_for_domain("openrouter_derived")`.

- [ ] **Step 4: Add the focused section domain and verify projected loads**

Append `"openrouter_derived"` to the OpenRouter Intelligence tuple in `SECTION_DOMAIN_MAP`. Seed temporary Parquets with one row each and assert `load_domain_datasets("openrouter_derived")` returns only projected columns with zero missing required columns.

- [ ] **Step 5: Run dashboard data tests and commit**

Run: `python -m pytest -q tests/test_dashboard_data.py -k 'openrouter_derived or domain_map or projected'`

Expected: all selected tests PASS.

Commit:

```bash
git add dashboard/data.py dashboard/app.py tests/test_dashboard_data.py
git commit -m "Load compact OpenRouter derived marts"
```

---

### Task 7: OpenRouter Usage & Economics UI

**Files:**
- Modify: `dashboard/sections/openrouter.py`
- Modify: `tests/test_dashboard_data.py`

**Interfaces:**
- Replaces `_compute_daily_average_price_pivots()` with mart-backed helpers.
- Produces: `_derived_metric_pivot(frame: pd.DataFrame, metric_ids: list[str], *, rolling_window_days: int) -> pd.DataFrame`
- Produces: `_workload_intensity_section_state(datasets: dict[str, DatasetLoadResult], component: str) -> dict[str, object]`
- Produces: `_average_price_section_state(datasets: dict[str, DatasetLoadResult], diagnostic_metric_ids: list[str] | None = None) -> dict[str, object]`
- Extends `_weekly_usage_section_state()` to delegate `Workload Intensity` and `Average Price` to those helpers.

- [ ] **Step 1: Write failing state tests for Workload Intensity and Average Price**

Seed `DatasetLoadResult` objects for both marts and assert:

```python
def test_usage_economics_state_exposes_workload_and_guarded_sota_lines() -> None:
    workload = _weekly_usage_section_state(_derived_datasets(), {}, "Workload Intensity")
    assert workload["metric"] == "Workload Intensity"
    assert workload["pivot"].columns.tolist() == ["Total tokens/request"]
    assert workload["latest_values"]["observed_model_count"] == 4
    price = _weekly_usage_section_state(_derived_datasets(), {}, "Average Price")
    assert price["pivot"].columns.tolist() == [
        "Realized Market Average",
        "SOTA Median List Price",
        "Realized SOTA Price",
    ]
    assert price["coverage_label"] == "Observed 4/5 SOTA families · priced 5/5"
```

Add tests for missing SOTA values rendering as gaps, component selection using prompt/completion IDs, diagnostics remaining opt-in, and missing marts returning a scoped empty message without affecting Tokens or Requests.

- [ ] **Step 2: Run state tests and verify failures**

Run: `python -m pytest -q tests/test_dashboard_data.py -k 'usage_economics_state or workload_intensity_state'`

Expected: FAIL because the new metric state is not implemented.

- [ ] **Step 3: Implement mart-backed state helpers**

Map metric IDs to these exact labels:

```python
PRICE_LABELS = {
    "realized_market_average": "Realized Market Average",
    "sota_median_list_price": "SOTA Median List Price",
    "realized_sota_price": "Realized SOTA Price",
    "frontier_contenders_median_list_price": "Frontier Contenders Median List Price",
    "premium_priced_realized": "Premium-priced Realized Price",
    "mid_priced_realized": "Mid-priced Realized Price",
    "low_priced_realized": "Low-priced Realized Price",
    "fixed_workload_basket": "Fixed Workload Basket",
}
WORKLOAD_LABELS = {
    "total_tokens_per_request": "Total tokens/request",
    "prompt_tokens_per_request": "Prompt tokens/request",
    "completion_tokens_per_request": "Completion tokens/request",
}
```

Use seven-day rows by default, pivot `usage_date` by label, preserve missing values, and derive coverage from the latest row contributing to the displayed SOTA series.

- [ ] **Step 4: Update the section title, selector, KPIs, and charts**

Rename the title to `OpenRouter Usage & Economics` and use selector order `Tokens`, `Requests`, `Workload Intensity`, `Average Price`.

For Workload Intensity:

- Add a Total/Prompt/Completion segmented control and Raw Daily/7-Day control.
- Render four existing-style KPI cards for total, prompt, completion, and seven-day change.
- Render one default line with `/request` hover suffix.
- Render the latest 30-day model table with model/company, shares, tokens/request, and intensity ratio.
- Caption it as tracked-model workload intensity and request-demand proxy, not efficiency.

For Average Price:

- Default to the three agreed lines.
- Add a collapsed `Price diagnostics` expander containing a multiselect for contender, three price cohorts, and fixed basket.
- Show `Observed N/5 SOTA families · priced N/5` above the chart.
- Rename all old Frontier/Value labels and explanatory copy to Premium-priced/Low-priced.
- Explain that only the existing market average may contain labelled earliest-price backcasts.

- [ ] **Step 5: Remove the direct full-mart dashboard join**

Delete `_compute_daily_average_price_pivots()` and its direct `pd.read_parquet(daily_provider_economics.parquet)` path. Confirm the OpenRouter section reads only `DatasetLoadResult.frame` for the two derived datasets.

- [ ] **Step 6: Run dashboard tests and commit**

Run: `python -m pytest -q tests/test_dashboard_data.py tests/test_openrouter_explorer.py`

Expected: all tests PASS.

Commit:

```bash
git add dashboard/sections/openrouter.py tests/test_dashboard_data.py
git commit -m "Add OpenRouter workload and SOTA price views"
```

---

### Task 8: Full Verification, Streamlit QA, and Branch Review

**Files:**
- Modify only files required by failures found in this task.

**Interfaces:**
- Verifies all prior tasks; produces no new feature surface.

- [ ] **Step 1: Run the complete automated suite**

Run:

```bash
python -m compileall -q src dashboard
python -m pytest -q
```

Expected: compile exit 0 and the full pytest suite PASS with zero failures.

- [ ] **Step 2: Verify schemas, natural keys, coverage, and memory size on real data**

Run:

```bash
python - <<'PY'
import pandas as pd
from pathlib import Path
for name, keys in {
    'openrouter_usage_economics_daily': ['usage_date', 'metric_id', 'cohort_id', 'rolling_window_days'],
    'openrouter_workload_intensity_models': ['window_end_date', 'model_id'],
}.items():
    path = Path('data/normalized/marts') / f'{name}.parquet'
    frame = pd.read_parquet(path)
    assert not frame.empty
    assert not frame.duplicated(keys).any()
    assert frame.memory_usage(deep=True).sum() < 10_000_000, (name, frame.memory_usage(deep=True).sum())
    print(name, len(frame), frame.memory_usage(deep=True).sum())
PY
```

Expected: both marts are non-empty, naturally unique, and each uses less than 10 MB in memory.

- [ ] **Step 3: Run Streamlit and inspect the feature in a real browser**

Run:

```bash
DATA_SOURCE=local streamlit run dashboard/app.py --server.headless true --server.port 8501
```

Use the Playwright skill to verify:

- OpenRouter Intelligence loads without an exception.
- The section title is `OpenRouter Usage & Economics`.
- All four metric controls work.
- Workload component and raw/rolling controls update the chart and KPIs.
- The model table is readable at desktop width.
- Average Price defaults to exactly three lines.
- Price diagnostics are collapsed initially and add only selected lines.
- Coverage and legacy-backcast notes are visible and use the dashboard's existing style.
- Switching sections does not preserve stale highlighted controls or add model query parameters.

- [ ] **Step 4: Verify workflow YAML and git scope**

Run:

```bash
python -m pytest -q tests/test_workflow_reliability.py
git diff --check
git status --short --branch
git diff --stat main...HEAD
```

Expected: workflow tests PASS, no whitespace errors, only feature-related tracked files differ from `main`, and unrelated untracked ` 2` files remain unstaged.

- [ ] **Step 5: Commit any verification-only corrections**

If Step 1–4 required tracked corrections, stage only their explicit paths and commit:

```bash
git commit -m "Harden OpenRouter derived metric presentation"
```

If no tracked corrections were required, do not create an empty commit.

- [ ] **Step 6: Request code review before merge or push**

Invoke `superpowers:requesting-code-review`, address only evidence-backed findings, rerun Steps 1–4, then present the branch status and test evidence to the user. Do not merge to `main` without explicit user approval.
