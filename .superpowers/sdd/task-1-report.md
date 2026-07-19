# Task 1 Report: Curated Capability Families and Point-in-Time Ranking

## Status

Completed and committed as `aadbdff Add point-in-time OpenRouter capability families`.

## RED evidence

Command:

```bash
python -m pytest -q tests/test_openrouter_derived_data.py::test_rank_capability_families_collapses_configurations_and_uses_asof_snapshot
```

Output before implementation:

```text
ImportError while importing test module 'tests/test_openrouter_derived_data.py'
ModuleNotFoundError: No module named 'openrouter_derived_data'
1 error in 0.44s
```

This is the expected missing-package/module failure for the required focused ranking test.

## GREEN evidence

Focused capability tests:

```bash
python -m pytest -q tests/test_openrouter_derived_data.py -k 'capability or family or rank'
```

Output:

```text
3 passed in 0.41s
```

Full new test file:

```bash
python -m pytest -q tests/test_openrouter_derived_data.py
```

Output:

```text
3 passed in 0.41s
```

Stored-snapshot map audit:

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

Output:

```text
curated top-ten configurations: 11
```

`git diff --check --no-index` was also run against each of the four new task files before committing; it reported no whitespace errors.

## Files changed

- `config/openrouter_capability_map.json`
- `src/openrouter_derived_data/__init__.py`
- `src/openrouter_derived_data/identity.py`
- `tests/test_openrouter_derived_data.py`

## Implementation notes

- The curated JSON contains every configuration in the stored Artificial Analysis top ten plus the required GLM-5.2 configuration, using exact inspected OpenRouter route IDs.
- Map loading validates the exact schema, non-empty version and identity strings, duplicate AA IDs, and duplicate/invalid route IDs, then returns immutable records.
- Ranking normalizes all dates to UTC-naive days; uses only exact map matches; filters snapshots and releases as of each usage day; collapses configurations to one deterministic family representative; and assigns the prescribed tiers.
- The ranking rows carry all required output columns and a `model_match_status` of `exact_curated_match`.

## Self-review

- Confirmed family collapse uses the mandated representative and final rank tie-break order.
- Confirmed an unmapped benchmark row cannot appear or receive a capability tier because the join is exact and inner.
- Confirmed the test fixture covers duplicate Sol configurations, future release exclusion, future snapshot exclusion, tier boundaries, and exact route lookup.
- Confirmed only the four listed task files were staged and committed. Pre-existing untracked files, including names containing ` 2` and `.playwright-cli`, were not staged or modified.

## Concerns

- `model_match_status` is required as an output column but the brief does not prescribe its literal value. This task uses `exact_curated_match` to make the exact curated join explicit; downstream consumers should treat it as a provenance label rather than infer fuzzy matching behavior.
- Pytest emitted an existing `RequestsDependencyWarning` about the local `requests`/`urllib3` package combination; all task tests nevertheless passed.

## P1 snapshot-selection fix

Review identified that `rank_capability_families()` applied the release-date condition before selecting the benchmark snapshot. That meant a latest snapshot containing only future-release mapped models was discarded, allowing the function to rewind to an older snapshot with released models.

### Regression RED evidence

Added `test_rank_capability_families_does_not_rewind_when_latest_snapshot_is_future_only`, with a released Claude Fable row in the 2026-07-09 snapshot and only a future-release mapped row in the 2026-07-17 snapshot. For usage date 2026-07-18, the required result is an empty ranking gap.

Command before the fix:

```bash
python -m pytest -q tests/test_openrouter_derived_data.py::test_rank_capability_families_does_not_rewind_when_latest_snapshot_is_future_only
```

Output:

```text
F                                                                        [100%]
AssertionError: assert False
... [1 rows x 11 columns].empty
1 failed in 0.68s
```

### Fix and GREEN evidence

The function now selects the latest `as_of_date <= usage_date` from the complete Artificial Analysis snapshot set, then applies the release-date condition and exact curated-model merge inside that one selected snapshot. If no row remains, it emits no ranking for the usage date.

Command:

```bash
python -m pytest -q tests/test_openrouter_derived_data.py
```

Output:

```text
4 passed in 0.64s
```

`git diff --check -- src/openrouter_derived_data/identity.py tests/test_openrouter_derived_data.py` completed without whitespace errors.
