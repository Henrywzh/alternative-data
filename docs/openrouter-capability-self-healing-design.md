# Self-Healing Capability Resolution for OpenRouter Derived Data

**Design proposal — permanent fix for the recurring SOTA Realized Price outage**

Author: GLM-5.3 architecture pass (2026-08-20)
Status: Proposed
Scope: `src/openrouter_derived_data/`, `config/`, `.github/workflows/`, `tests/test_openrouter_derived_data.py`

---

## 1. Executive summary

Every frontier release (Kimi K3, Grok 4.6, GLM-5.2, ...) blanks the
`sota_volume_weighted_atp` metric for days because five independently reasonable
design decisions chain into an all-or-nothing outage:

1. `config/openrouter_capability_map.json` is a hand-maintained UUID → route map.
2. `rank_capability_families` ranks **all** AA families, then drops unmapped ones —
   leaving holes in ranks 1..10.
3. `_tier_cohort` demands the exact frozenset `{1,2,3,4,5}`.
4. `_realized_sota_row` multiplies that requirement into `guarded` → `value = NA`.
5. `_prepare_sota_daily` skips incomplete days entirely, starving the 7-day window.

The fix has four pillars:

| Pillar | Change | Effect |
|---|---|---|
| Auto-matching | Deterministic slug resolver (curated override > persistent registry > exact-normalized slug > stripped-slug fallback) | New frontier models resolve on day 1 without human action |
| Rank continuity | Rank only route-eligible families; keep the global rank as an audit column | Ranks 1..5 are always contiguous; cohort can never be "holey" |
| Resilient guardrails | `guarded := priced_count >= 3` + explicit `coverage_status` (`complete`/`degraded`/`insufficient`) | A missing 5th family degrades the metric, never blanks it |
| CI guard | `openrouter-derived-data guard` + daily workflow step that opens a `capability-map-drift` issue | Unmapped top-10 models alert within one scheduled run, before users notice |

All matching logic in this proposal was prototyped against the live repo data on
2026-08-19 (AA snapshot 2026-08-18 + current OpenRouter catalog): the resolver
resolves **both currently-unmapped top-10 models** (Grok 4.6, Qwen3.8 2.4T A95B)
at the exact-normalized tier, and route expansion via `canonical_slug` covers the
dated permaslugs that actually carry usage for all six live SOTA families
(§8).

---

## 2. Incident anatomy (live evidence, 2026-08-19)

Reproduced from the committed inputs with current `main` code:

```
rankings for usage_date 2026-08-19 (backfill mode):
  rank 1  anthropic/claude-opus-5        Claude Opus 5 (Max)      63.1
  rank 2  anthropic/claude-fable-5       Claude Fable 5 (Max)     62.1
  rank 3  (dropped)                      Grok 4.6 (high)          60.9   <- unmapped UUID c8adc5cf-…
  rank 4  openai/gpt-5.6-sol             GPT-5.6 Sol (max)        60.9
  rank 5  moonshotai/kimi-k3             Kimi K3 (max)            59.7

Ranks present: [1, 2, 4, 5, 6, 8, 10, 11, 13, …]   <- holes at 3, 7, 9
```

`_tier_cohort("sota")` computes `complete = {1,2,4,5} == {1,2,3,4,5} → False`,
so `guarded = False` and the published value is `NA` for every day until a human
edits the JSON. The frontier_contender cohort (`{6..10}`) fails the same way via
the holes at 7 and 9.

Two structural amplifiers make the outage worse than a single bad day:

- `_prepare_sota_daily` **skips data collection** for incomplete days, so the
  7-day rolling window loses a day of numerator/denominator for every day the
  map is stale — the metric stays `NA` even after ranks 1..5 are complete again,
  until the window refills.
- The current design intentionally encodes the gaps
  (`test_unmapped_benchmark_leaders_leave_explicit_top_five_and_top_ten_rank_gaps`),
  i.e. "an unmapped leader must be visible as a hole." The observability goal is
  right; coupling it to the *pricing cohort integer set* is what breaks.

---
## 3. Design goals and non-goals

**Goals**

1. **Zero-maintenance onboarding**: a new frontier model from any *known creator*
   enters the SOTA/contender cohorts on its first scored AA snapshot, with no
   human edit.
2. **Never blank**: the metric publishes a value whenever >= 3 of 5 cohort
   families are priced; coverage is annotated, not hidden.
3. **Point-in-time correctness**: no lookahead — auto-matches become effective no
   earlier than the AA release date and the route's catalog appearance, and are
   frozen into an append-only registry so history is stable and auditable.
4. **Determinism & auditability**: identical inputs -> identical map; every
   resolution records its layer, confidence, and chosen routes in a committed
   report artifact.
5. **Curated override supremacy**: humans can always pin, extend, or veto an
   automatic resolution via the existing JSON.
6. **Alert before users notice**: CI fails loudly with an actionable message the
   first scheduled run after drift appears.

**Non-goals**

- Ranking models that AA has not scored (no score, no rank — unchanged).
- Auto-matching brand-new *creators* (unknown `creator_slug` -> guard alert; a
  one-line alias addition resolves it — see §5.3).
- Changing the guarded as-of pricing philosophy (strict snapshots, no backcast,
  historical route fill) — only the *cohort completeness* gate is redesigned.
- Replacing the curated JSON; it remains the source of truth for overrides.

---
## 4. Target architecture

```
                     ┌────────────────────────────────────────────────┐
                     │  Layer 0 — curated override (existing JSON)    │
                     │  aa_model_id -> family_id + routes, dated      │
                     └───────────────┬────────────────────────────────┘
                                     │ misses
                     ┌───────────────▼────────────────────────────────┐
                     │  Layer 1 — persistent registry (new JSONL)      │
                     │  frozen auto-resolutions, append-only,         │
                     │  provenance-tagged, committed by CI            │
                     └───────────────┬────────────────────────────────┘
                                     │ misses
                     ┌───────────────▼────────────────────────────────┐
                     │  Layer 2 — deterministic slug resolver (new)    │
                     │  2a exact-normalized  (creator alias + slug)    │
                     │  2b stripped-normalized (effort/variant tiers)  │
                     │  route expansion via canonical_slug closure    │
                     └───────────────┬────────────────────────────────┘
                                     │ misses
                     ┌───────────────▼────────────────────────────────┐
                     │  Layer 3 — fuzzy fallback (guarded)             │
                     │  same-creator only, score >= 0.92, margin >= 5  │
                     │  -> always reported, never silent               │
                     └───────────────┬────────────────────────────────┘
                                     │ misses
                     ┌───────────────▼────────────────────────────────┐
                     │  unmapped: retained in rankings output with     │
                     │  global rank + model_match_status='unmapped';   │
                     │  CI guard opens capability-map-drift issue      │
                     └────────────────────────────────────────────────┘
```

Resolution result per AA model: the first layer that produces a hit wins.
Layers 2–3 write their result into the registry (Layer 1) on first observation,
so a resolution computed once on release day is reused verbatim forever — this
is what makes the system *stable* under catalog churn (aliases appearing/retiring
later cannot rewrite history).

### 4.1 Why a registry *and* a resolver

Pure runtime resolution would re-derive the map from the current catalog every
run. That is unstable: OpenRouter routinely adds undated aliases (`x-ai/grok-4.6`)
days after the dated route (`x-ai/grok-4.6-20260810`) appears, retires preview
slugs, and re-points canonical slugs. Freezing first-observation resolutions
into an append-only registry gives:

- reproducible point-in-time history (a rerun over old usage dates sees the same
  routes the run back then saw, modulo explicit registry appends);
- an audit trail (who/what matched, at which layer, with what confidence);
- immunity to later catalog mutations for already-known families.

The curated JSON stays the *override* channel: same schema as today, and any
entry there silently beats registry/resolver output for the same
`aa_model_id`.

---
## 5. Component design

### 5.1 Slug normalization (Layer 2 core)

Both sides normalize to a canonical key so that `grok-4-6`, `grok-4.6`,
`grok-4.6-20260810`, and `grok-4.6:free` collapse to `grok-4-6`:

```python
# src/openrouter_derived_data/resolver.py (new module)
import re

DATE_SUFFIX = re.compile(r"[-_:]?\d{8}$")
EFFORT_TIERS = {"high", "xhigh", "medium", "low", "max", "min"}
ROUTE_VARIANTS = {"free", "batch", "preview", "beta", "alpha", "latest",
                  "stable", "exp", "experimental", "fast"}

def normalize_slug(slug: str, *, strip_tiers: bool = False) -> str:
    """Canonical key: lowercase, unify separators, drop date suffix and
    route qualifiers; optionally drop trailing reasoning-effort tiers."""
    text = DATE_SUFFIX.sub("", slug.lower().strip())
    parts = [p for p in text.replace(".", "-").replace("_", "-").split("-") if p]
    parts = [p for p in parts if p not in ROUTE_VARIANTS]
    if strip_tiers:
        while parts and parts[-1] in EFFORT_TIERS:
            parts.pop()
    return "-".join(parts)

def route_slug(model_id: str) -> str:
    """'moonshotai/kimi-k3-20260715:free' -> 'kimi-k3-20260715'."""
    return model_id.split(":", 1)[0].split("/", 1)[-1]
```

Matching is two-tier and conservative:

1. **Tier A (exact-normalized)**: `normalize_slug(aa.model_slug)` equals
   `normalize_slug(or.route_slug)` within a creator-alias-matched prefix. No
   effort stripping. This resolved 33/39 curated UUIDs and *both* live unmapped
   models in validation.
2. **Tier B (stripped-normalized)**: retry with `strip_tiers=True` on both sides
   (collapses `claude-opus-5-xhigh` -> `claude-opus-5`). If the stripped key maps
   to **more than one distinct dated base family** within the prefix
   (e.g. `o3-mini` vs `o3-mini-high` both existing), the match is **ambiguous** ->
   unresolved + guard alert, never a silent guess.

The effort-tier/variant stripping is applied *symmetrically to both sides*, which
avoids one-sided over-stripping (AA `qwen3-8-max` keeps `max` because the OR side
`qwen3.8-max` keeps it too).

### 5.2 Route expansion via `canonical_slug` closure

Usage flows on **dated permaslugs** (`moonshotai/kimi-k3-20260715`,
`x-ai/grok-4.6-20260810`) while the current catalog exposes **undated aliases**
(`moonshotai/kimi-k3`). The catalog's `canonical_slug` column is the bridge:
the alias's canonical slug *is* the dated slug. Expansion is a transitive
closure (validated in §8):

```python
def expand_routes(seeds: set[str], canonical_of: dict[str, str],
                  ids_of_canonical: dict[str, set[str]]) -> frozenset[str]:
    """Closure over model_id <-> canonical_slug links.
    seed {moonshotai/kimi-k3} -> {kimi-k3, kimi-k3-20260715}."""
    routes, frontier = set(seeds), list(seeds)
    while frontier:
        nxt = []
        for route in frontier:
            targets = set()
            canonical = canonical_of.get(route)
            if canonical:
                targets.add(canonical)
            targets |= ids_of_canonical.get(route, set())
            for target in targets:
                if target not in routes:
                    routes.add(target)
                    nxt.append(target)
        frontier = nxt
    return frozenset(routes)
```

Route effective dates: each route's `effective_from = max(aa_release_date,
catalog created_at of that route)` — a route cannot carry usage before it exists,
and a family cannot enter the cohort before AA says it is released. This
preserves the existing `compatible_activity_ids` point-in-time contract.

### 5.3 Creator alias table

AA `creator_slug` and OpenRouter prefixes disagree for exactly the frontier
labs (`xai`->`x-ai`, `kimi`->`moonshotai`, `alibaba`->`qwen`, `zai`->`z-ai`, …).
This table changes only when a **new lab** starts publishing frontier models —
rare, and precisely the case the CI guard catches on day 1 with an actionable
message ("add alias for creator `foo`"). Seeded from today's data:

```python
CREATOR_ALIASES: dict[str, str] = {
    "xai": "x-ai", "kimi": "moonshotai", "alibaba": "qwen", "zai": "z-ai",
    "zhipu": "z-ai", "openai": "openai", "anthropic": "anthropic",
    "google": "google", "deepseek": "deepseek", "meta": "meta-llama",
    "mistral": "mistralai", "nvidia": "nvidia", "xiaomi": "xiaomi",
    "bytedance": "bytedance", "tencent": "tencent", "baidu": "baidu",
    "minimax": "minimax", "ai21": "ai21", "cohere": "cohere",
    "amazon": "amazon", "microsoft": "microsoft", "perplexity": "perplexity",
    "stepfun": "stepfun-ai",
}
```

An unknown creator falls back to trying the AA slug itself as prefix (some
creators match verbatim) and otherwise lands in the unmapped path with a guard
alert — never a wrong match.

### 5.4 Family grouping (effort variants)

AA publishes multiple UUIDs per family for reasoning-effort variants
(`claude-opus-5`, `claude-opus-5-high`, `claude-opus-5-xhigh`, …). Because Tier B
strips effort tiers symmetrically, all variants normalize to the same key and
therefore to the same `family_id = f"{prefix}/{normalized_base}"`. The existing
per-family dedup in `rank_capability_families` (sort by intelligence desc, keep
first) already selects the highest-scoring variant as representative — that
behavior is preserved unchanged.

The curated map occasionally assigns *multiple* AA UUIDs to one family (e.g. the
four Opus-5 UUIDs); the resolver reproduces this organically via normalization,
and the curated entries continue to win where present.

### 5.5 Rank continuity refactor (`identity.py`)

Replace rank-then-drop with **filter-then-rank**, while keeping the global rank
for auditability. The output schema gains one column; `family_rank` semantics
change from "rank among all AA families" to "rank among route-eligible
families" (methodology version bump, §7).

```python
# identity.py — inside rank_capability_families, per usage_date:

    eligible["_mapped"] = eligible["model_id"].isin(effective_entries) | \
        eligible["model_id"].isin(auto_resolved_ids)          # L1/L2/L3 hits

    # 1) Global rank over ALL families (audit signal; holes allowed here)
    eligible = eligible.sort_values(
        ["intelligence_index", "release_date", "family_id"],
        ascending=[False, False, True],
    ).reset_index(drop=True)
    eligible["global_family_rank"] = range(1, len(eligible) + 1)

    # 2) Cohort rank over route-eligible families ONLY — always contiguous
    ranked_eligible = eligible.loc[eligible["_mapped"]].copy()
    ranked_eligible["family_rank"] = range(1, len(ranked_eligible) + 1)
    ranked_eligible["capability_tier"] = ranked_eligible["family_rank"].map(_tier)

    # 3) Unmapped leaders stay in the output for observability, with an
    #    explicit status and a NULL cohort rank (they cannot be priced).
    unmapped = eligible.loc[~eligible["_mapped"]].copy()
    unmapped["family_rank"] = pd.NA
    unmapped["capability_tier"] = "unmapped"
    eligible = pd.concat([ranked_eligible, unmapped], ignore_index=True)
```

`RANKING_COLUMNS` gains `global_family_rank`; `model_match_status` takes values
`exact_curated_match` | `registry_auto_match` | `auto_slug_match` |
`auto_slug_match_stripped` | `auto_fuzzy_match` | `unmapped`.

Economic semantics: the SOTA cohort becomes "the top-5 capability families that
are actually routed and priceable on OpenRouter," which is the only definition a
*realized price* metric can support. An unmapped leader no longer corrupts the
cohort integer set; it surfaces as `capability_tier='unmapped'` + guard alert.
When its resolution lands (auto or curated), it re-enters at its earned position
and the cohort shifts by one — a normal, labeled composition change recorded via
`methodology_version` and the per-day `benchmark_snapshot_date`.

### 5.6 Resilient guardrails (`metrics.py`)

**Cohort selection.** `_tier_cohort` stops asserting the exact frozenset. It
returns the (now always contiguous) top-5 rows plus a completeness flag used
only for *annotation*:

```python
def _tier_cohort(rankings, tier):
    required = frozenset(range(1, 6) if tier == "sota" else range(6, 11))
    cohort = rankings.loc[rankings["capability_tier"].eq(tier)].copy()
    cohort = cohort.sort_values([...]).drop_duplicates(["family_rank", "family_id"])
    complete = (
        frozenset(cohort["family_rank"].dropna().astype(int)) == required
        and cohort["family_id"].nunique() == 5
    )
    return cohort, complete          # complete is now advisory only
```

**Coverage status state machine** (new output column, §7):

```python
def _coverage_status(expected: int, priced: int, identity_complete: bool) -> str:
    if priced >= expected and identity_complete:
        return "complete"        # 5/5 priced, cohort identity stable
    if priced >= 3:
        return "degraded"        # publishes, flagged (3-4 priced, or identity shifted)
    return "insufficient"        # value stays NA — with an explicit reason
```

**`_realized_sota_row`** — the guard drops `complete_current_cohort` as a hard
gate and annotates instead:

```python
    guarded = observed_count >= 3 and priced_count >= 3
    status = _coverage_status(5, int(priced_count), complete_current_cohort)
    row.update({
        "value": numerator / denominator * 1_000_000
            if guarded and pd.notna(denominator) and denominator > 0
            else pd.NA,
        "coverage_status": status,                       # new column
        "pricing_join_status": _sota_join_status(        # enriched reason
            status, complete_current_cohort, historical_fill_used),
        ...
    })
```

with `_sota_join_status` emitting e.g. `strict_asof_pricing|degraded_4_of_5`,
`degraded_missing_rank_3`, `insufficient_below_three_priced_families` so a
downstream reader can explain any NA without opening the pipeline.

The same relaxation applies to `_list_price_row` (`sota_median_list_price`,
`frontier_contenders_median_list_price`), whose median-over-families is already
well-defined for n=3..5 (median of 4 uses interpolation of the middle two —
acceptable and labeled `degraded`; can be pinned to `statistics.median` if the
strict middle-element definition is preferred).

**`_prepare_sota_daily`** — never skip a day. Collect whatever mapped routes
exist and record coverage honestly:

```python
    for activity_date, activity_day in economics.groupby("usage_date"):
        daily_rankings, complete_cohort = _tier_cohort(
            rankings.loc[rankings["usage_date"].eq(activity_date)], "sota")
        # REMOVED: if not complete_cohort: continue
        daily_routes = _routes_for_rankings(daily_rankings, capability_map,
                                            activity_date)
        ...
        coverage_rows.append({
            ...,
            "mapped_family_count": int(daily_rankings["family_id"].nunique()),
            "cohort_complete": bool(complete_cohort),
        })
```

This kills the window-starvation amplifier: when rank 3's resolution lands, the
metric recovers on the next run using the full 7 days of already-collected
numerator/denominator, instead of waiting a week.

### 5.7 Resolution report artifact

Each build writes `data/normalized/marts/openrouter_capability_resolution_report.parquet`
(committed by the daily workflow alongside the marts):

| column | example |
|---|---|
| `as_of_date` | 2026-08-18 |
| `aa_model_id` | c8adc5cf-fd5a-407b-af51-dc3bede3e49c |
| `model_slug` / `creator_slug` | grok-4-6 / xai |
| `resolution_layer` | curated / registry / slug_exact / slug_stripped / fuzzy / unmapped |
| `family_id` | x-ai/grok-4.6 |
| `routes` | [x-ai/grok-4.6, x-ai/grok-4.6-20260810] |
| `confidence` | 1.0 / 0.97 / NA |
| `global_rank` | 5 |
| `first_observed_date` | 2026-08-18 |
| `resolver_version` | resolver-v1 |

This is the audit trail, the guard's input, and the review surface for
human-in-the-loop promotion of fuzzy matches into the curated JSON.

---
## 6. CI guard — alert before users notice

### 6.1 Command

New subcommand wired into the existing entry point:

```
openrouter-derived-data --base-dir . guard [--top-n 10] [--fail-on degraded]
```

Checks (fast: reads the two committed input parquets + registry, no network):

1. **DRIFT (hard fail)**: any AA model in the top-N by `intelligence_index`
   (released, eligible) whose resolution layer is `unmapped` — message lists
   model name, slugs, creator, and the *suggested* alias/slug fix.
2. **AMBIGUOUS (hard fail)**: a Tier-B key collapsing >= 2 distinct dated base
   families within a prefix (collision detector from §5.1).
3. **FUZZY (soft/flag)**: any Layer-3 resolution in the top-N — should be
   promoted to curated within a few days; fails when `--fail-on fuzzy`.
4. **COVERAGE (hard fail)**: in the latest published mart, latest-day
   `sota_volume_weighted_atp` row has `coverage_status != 'complete'` for >= 3
   consecutive days (catches silent degradation the drift check missed).
5. **REGISTRY CONFLICT (hard fail)**: registry contains two different
   `family_id` assignments for one `aa_model_id` (data-integrity tripwire).

Exit code 0 = quiet; nonzero = actionable stderr + machine-readable
JSON summary (`--json` for the workflow annotation).

### 6.2 Workflow wiring (`.github/workflows/openrouter-derived-daily.yml`)

```yaml
      - name: Build compact derived marts from committed inputs
        run: openrouter-derived-data --base-dir . build

      - name: Commit compact derived marts + capability registry
        run: |
          git add data/normalized/marts/openrouter_usage_economics_daily.parquet \
                  data/normalized/marts/openrouter_workload_intensity_models.parquet \
                  data/normalized/marts/openrouter_capability_resolution_report.parquet \
                  config/openrouter_capability_registry.jsonl
          ...

      - name: Capability drift guard
        id: guard
        run: openrouter-derived-data --base-dir . guard --top-n 10 --json > guard.json
        continue-on-error: true      # degraded data still publishes; drift alerts

      - name: Open or update capability-map-drift issue
        if: steps.guard.outcome == 'failure'
        run: |
          gh issue view "capability-map-drift" >/dev/null 2>&1 || \
            gh issue create --title "capability-map-drift" \
              --label "capability-map-drift,data-quality" --body ""
          gh issue comment "capability-map-drift" --body-file guard.json
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

Deliberate choice: the guard runs **after** the commit step and uses
`continue-on-error` — a degraded-but-valid mart must still publish (that is the
whole point of §5.6); drift is an alerting concern, not a publication blocker.
Additionally `ci.yml` runs `guard` on every PR touching
`src/openrouter_derived_data/**` or `config/openrouter_capability*` against the
committed fixtures, so regressions surface at review time.

---
## 7. Schema, versioning, and migration

1. **`_DAILY_COLUMNS`** += `coverage_status` (string; one of
   `complete`/`degraded`/`insufficient`). Additive Parquet schema change;
   column-selecting consumers are unaffected.
2. **`RANKING_COLUMNS`** += `global_family_rank` (int). The rankings frame is an
   internal interchange (not a published mart), so the change is contained to
   `identity.py` -> `metrics.py` -> tests.
3. **`methodology_version`** bumps to `openrouter-derived-v3-auto-capability` in
   both the capability map JSON and `METHODOLOGY_VERSION`, so every published row
   carries the semantics change.
4. **Config additions**: `config/openrouter_capability_registry.jsonl` (append-only)
   and the resolution report parquet; both committed by the daily workflow.
5. **Test migration**: the semantics of
   `test_unmapped_benchmark_leaders_leave_explicit_top_five_and_top_ten_rank_gaps`
   invert — the new expectations are contiguous cohort ranks, an `unmapped` row
   retained at its global rank, and a *published* `degraded` value. The complete
   list of touched tests is in §9.
6. **Downstream consumers** of `openrouter_usage_economics_daily.parquet`
   (dashboards) should render `coverage_status` as a badge; until they adopt it,
   `degraded` rows are indistinguishable from today's rows except the new column
   — safe default.

---
## 8. Validation evidence (live data, 2026-08-19)

Prototyped against `artificial_analysis_models_daily.parquet` (snapshot 2026-08-18)
and `raw_openrouter_models.parquet` (current catalog):

**Resolver coverage of curated UUIDs** (would have produced identical families
without any human edit):

| Metric | Result |
|---|---|
| Curated UUIDs present in latest AA snapshot | 39 |
| Auto-resolved via exact-normalized tier | 33 |
| Resolvable only via stripped tier (effort variants) | remainder, e.g. `claude-opus-5-xhigh` |
| Unresolved (legacy `-thinking`/`-adaptive`/`-reasoning` AA slugs, retired routes) | 6 — all covered by curated JSON, which remains in force |

**The two live incident models:**

| AA model (unmapped today) | slug | resolution | routes found |
|---|---|---|---|
| Grok 4.6 (high) | `grok-4-6` / `xai` | exact tier | `x-ai/grok-4.6` -> expand -> `x-ai/grok-4.6-20260810` (the permaslug carrying 4.5e11 tokens since 8/10) |
| Qwen3.8 2.4T A95B | `qwen3-8-2-4t-a95b` / `alibaba` | exact tier | `qwen/qwen3.8-2.4t-a95b` |

**Canonical-slug expansion covers every active SOTA family route** (seed alias
-> dated permaslug with real usage):

```
kimi-k3       moonshotai/kimi-k3        -> moonshotai/kimi-k3-20260715      covered
grok-4.6      x-ai/grok-4.6             -> x-ai/grok-4.6-20260810           covered
claude-opus-5 anthropic/claude-opus-5    -> anthropic/claude-opus-5-20260723 covered
qwen3.8-max   qwen/qwen3.8-max           -> qwen/qwen3.8-max-20260803        covered
glm-5.2       z-ai/glm-5.2              -> z-ai/glm-5.2-20260616 (:free)    covered
gpt-5.6-sol   openai/gpt-5.6-sol        -> openai/gpt-5.6-sol-20260709      covered
```

**Collision safety**: scanning all catalog prefixes, 29 normalized keys collapse
>= 2 distinct dated base families (e.g. `o3-mini` vs `o3-mini-high`); all are
old-generation, non-frontier keys, and every one is caught by the ambiguity
detector (§5.1 Tier B) rather than mis-matched. Zero collisions exist inside
any creator-alias-filtered frontier top-10.

**End-to-end effect on today's incident**: with this design, 2026-08-19's cohort
is Opus 5, Fable 5, **Grok 4.6 (auto-matched)**, GPT-5.6 Sol, Kimi K3 — ranks
`{1,2,3,4,5}`, `coverage_status=complete` once priced, and even if Grok 4.6 had
resolved with zero usage yet, the metric would publish `degraded 4_of_5` instead
of `NA`.

---
## 9. Test plan

New tests (`tests/test_openrouter_derived_data.py` + new
`tests/test_openrouter_capability_resolver.py`):

1. `test_resolver_exact_tier_matches_frontier_releases` — Grok-4.6-shaped
   fixture (unmapped UUID entering at rank 3) resolves and the cohort publishes.
2. `test_resolver_rejects_ambiguous_stripped_keys` — two same-prefix families
   differing only by an effort tier stay unresolved; guard alerts.
3. `test_resolver_unknown_creator_is_unmapped_not_wrong` — unknown creator slug
   never produces a cross-creator match.
4. `test_registry_freezes_first_observation` — a resolution made on day D is
   reused verbatim on day D+30 even if the catalog mutates (alias retired).
5. `test_curated_override_beats_registry_and_resolver` — precedence order.
6. `test_ranks_are_contiguous_over_eligible_families` — replaces the gap test;
   asserts `family_rank == [1..5]`, unmapped row retained with
   `global_family_rank=3` and `capability_tier='unmapped'`.
7. `test_sota_metric_publishes_degraded_at_four_of_five` — one unpriced family
   -> value present, `coverage_status='degraded'`, join status explains.
8. `test_sota_metric_still_na_below_three_priced` — `insufficient` with reason.
9. `test_prepare_sota_daily_collects_partial_days` — window starvation removed;
   recovery on next run after a late map addition uses full 7-day window.
10. `test_guard_fails_on_unmapped_top_ten_and_emits_json`.
11. `test_pipeline_commits_resolution_report_and_registry_rows`.

Adjusted existing tests: the two "explicit rank gaps" tests (rank semantics),
`test_sota_price_metrics_require_the_complete_rank_one_to_five_cohort` and
`test_frontier_contender_price_requires_complete_ranks_six_to_ten` (NA now only
below 3 priced), and any fixture helpers building rankings frames
(`_price_rankings`, `_ranked_families` gain `global_family_rank`).

Golden replay: commit a sliced fixture of the actual 2026-08 inputs (AA top 15 +
relevant catalog rows) and assert the published mart matches the
post-fix expectations exactly — the regression test for "the next Grok 4.6".

---
## 10. Rollout plan

**Phase 1 — safety net (ship first, independently valuable).** Rank continuity
(§5.5) + guardrails (§5.6) + window fix. No resolver yet: the map is still
curated, but a missing model degrades instead of blanking. Low risk, pure
`identity.py`/`metrics.py` + tests.

**Phase 2 — resolver + registry.** `resolver.py`, registry merge in
`load_capability_map`, resolution report artifact, resolver tests with live-data
fixtures. Curated JSON untouched; resolver only fills holes the JSON leaves.

**Phase 3 — CI guard + issue automation** (§6) and the fuzzy tier (off by
default, `--enable-fuzzy` flag) after a week of Tier-A/B soak data in the
resolution reports.

**Phase 4 — curation burn-down.** As registry entries prove stable, optionally
prune the curated JSON to true overrides only (fast/pro variants, cross-family
pins). The JSON's methodology_version stays the human-controlled version knob.

Rollback at every phase = revert the commit; the registry is additive and the
curated JSON never stops working.

---
## 11. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Slug normalization mis-matches a same-creator model | Low (0 collisions in frontier top-10 today) | Symmetric stripping, ambiguity detector, curated override, golden replay test |
| Registry row conflicts with later curated edit | Medium (intended) | Precedence: curated > registry; loader raises on conflicting *registry* duplicates only; guard check #5 |
| `degraded` values mask persistent under-coverage | Medium | Consecutive-`degraded` guard check (#4) + issue label; dashboard badge |
| Median-of-4 definition dispute (list price) | Low | Pin `statistics.median` or keep pandas interpolation; document in methodology version |
| New creator with unknown alias | Certain eventually | Guard alert names the creator and suggests the alias line to add; one-line fix |
| Auto-family composition shifts historical continuity | Medium | Registry freeze + `methodology_version` bump + `benchmark_snapshot_date` per row already encode when composition changed |
| Resolver nondeterminism | Low | Pure functions, sorted candidates, no RNG; SequenceMatcher is deterministic |

---
## 12. Open questions (for the Gemini counterpart / review)

1. Should `coverage_status` thresholds be configurable per metric (SOTA 3-of-5
   vs contenders 3-of-5) or centralized in one guard policy object?
2. Is publishing a `degraded` value for the **list-price** medians acceptable,
   or should only the *realized* (volume-weighted) metrics degrade gracefully
   while medians stay strict?
3. Registry format: single JSONL vs per-month rotation? (JSONL recommended;
   expected volume ~10-40 rows/month.)
4. Should the fuzzy tier ever be enabled by default, or remain an operator
   escape hatch behind a flag?
5. Does the sibling `alternative-data-arr` repo consume the capability map
   directly and need the same loader changes ported?

