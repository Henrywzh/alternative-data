# Research Control Tower V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent, private-first Streamlit Research Control Tower that presents versioned cross-market baskets, a unified source-backed catalyst and macro timeline, provider-specific consensus revisions, company drill-downs and source health.

**Architecture:** Canonical collectors and financial observations remain in `alternative-data` and `financial-data`. Focused build/export modules materialize compact Control Tower marts into `alternative-data/apps/research-control-tower/.generated/`; a modular Streamlit app reads only those marts and never performs source collection or canonical writes during navigation.

**Tech Stack:** Python 3.11, pandas, PyArrow/Parquet, Pydantic-compatible dataclasses or typed records, DuckDB read access where already supported, Streamlit 1.45+, Plotly 5.18+, pytest, Streamlit AppTest.

## Global Constraints

- Preserve all unrelated work in the dirty `alternative-data` and `financial-data` repositories; use explicit paths and never reset, clean or discard existing changes.
- The existing `apps/asia-markets-streamlit/app.py` is out of write scope.
- The new app performs no external requests, collection or canonical writes during page navigation.
- `financial-data` owns financial statements, actuals, consensus observations, fiscal semantics and security/listing identifiers.
- `alternative-data` owns macro/policy data, cross-market baskets, catalyst research, read marts and the Control Tower application.
- Company-level research attaches to stable `entity_id`; listing-level prices and estimates attach to `listing_id`.
- Basket membership is versioned with `active_from` and `active_to`.
- Event certainty classes are `hard`, `provisional`, `thesis_checkpoint` and `observed`.
- Uncertain milestones use ranges and `date_precision`; they must never use a quarter-end or year-end date as a fake exact event.
- Confirmed hard events require a source URL and observation/verification timestamp.
- Consensus sources remain separate. Cross-source blending is prohibited unless fiscal period, currency, unit, consolidation basis and EPS basis align.
- Every consensus observation carries one of: `true_pit`, `snapshot_from_live_source`, `dated_public_broker_report`, `reconstructed_sparse`, `current_vintage`, `not_pit`.
- `AI_BOTTLENECKS_GLOBAL`, CSI 500 (`000905`) and STOXX Europe 600 are required.
- SK Hynix is a Tier-1 AI-bottlenecks anchor and must have a complete V1 company page.
- Raw licensed Futu, IBKR, FMP, news or consensus payloads must not enter public/portable artifacts unless display rights are explicitly verified.
- Missing credentials or entitlements produce explicit `unavailable` coverage rows; no worker may bypass access controls, scrape restricted pages or fabricate coverage.
- V1 primary pages are Today, Unified Timeline, AI Bottlenecks, Company and Source Health.
- The interaction hierarchy may reference AI Bottlenecks' flight deck, themes, catalysts, stack, T-minus and watch-question grammar, but may not copy its assets, text or proprietary research.
- V1 is local/private. Hosting and scheduled LLM briefs are readiness outputs, not deployment requirements.
- Every implementation task follows test-first development and ends with a task-scoped review before dependent work begins.

---

## File and interface map

### `alternative-data`

```text
config/research_control_tower/
  entities.csv
  listings.csv
  baskets.csv
  basket_memberships.csv
  indices.csv
  events.csv
  event_links.csv
  event_watch_questions.csv

src/research_control_tower/
  __init__.py
  contracts.py
  registries.py
  events.py
  macro.py
  build.py
  cli.py

apps/research-control-tower/
  app.py
  requirements.txt
  .generated/
  control_tower/
    __init__.py
    config.py
    models.py
    repository.py
    filters.py
    formatting.py
    components/
      __init__.py
      flight_deck.py
      timeline.py
      source_badges.py
    pages/
      __init__.py
      today.py
      unified_timeline.py
      ai_bottlenecks.py
      company.py
      source_health.py

tests/
  test_research_control_tower_registries.py
  test_research_control_tower_events.py
  test_research_control_tower_build.py
  test_research_control_tower_repository.py
  test_research_control_tower_streamlit.py
  test_research_control_tower_privacy.py
```

### `financial-data`

```text
src/hk_financials/
  control_tower_export.py

scripts/
  build_control_tower_consensus_export.py

tests/
  test_control_tower_consensus_export.py
```

### Stable cross-repository artifact interfaces

`financial-data` produces:

```text
control_tower_consensus_snapshots.parquet
control_tower_consensus_revisions.parquet
control_tower_consensus_source_health.parquet
```

`alternative-data` consumes those inputs and produces:

```text
entities.parquet
listings.parquet
baskets.parquet
basket_memberships.parquet
indices.parquet
events.parquet
event_entity_links.parquet
event_basket_links.parquet
event_watch_questions.parquet
macro_observations.parquet
consensus_snapshots.parquet
consensus_revisions.parquet
news_filings.parquet
source_health.parquet
build_manifest.json
```

All output files use stable schemas defined in `src/research_control_tower/contracts.py`.

---

### Task 1: Versioned entity, listing, basket and index registries

**Repository:** `alternative-data`

**Files:**
- Create: `config/research_control_tower/entities.csv`
- Create: `config/research_control_tower/listings.csv`
- Create: `config/research_control_tower/baskets.csv`
- Create: `config/research_control_tower/basket_memberships.csv`
- Create: `config/research_control_tower/indices.csv`
- Create: `src/research_control_tower/__init__.py`
- Create: `src/research_control_tower/contracts.py`
- Create: `src/research_control_tower/registries.py`
- Create: `tests/test_research_control_tower_registries.py`

**Interfaces:**
- Produces: `load_registry_bundle(config_root: Path) -> RegistryBundle`
- Produces: `validate_registry_bundle(bundle: RegistryBundle) -> list[ValidationIssue]`
- Produces typed frames: `entities`, `listings`, `baskets`, `basket_memberships`, `indices`
- Required basket: `AI_BOTTLENECKS_GLOBAL`
- Required indices: `CSI500` with official code `000905`, and `STOXX_EUROPE_600`

- [x] **Step 1: Write failing tests for keys, versioning and required coverage**

```python
def test_required_control_tower_registries_load(registry_root):
    bundle = load_registry_bundle(registry_root)
    assert "AI_BOTTLENECKS_GLOBAL" in set(bundle.baskets["basket_id"])
    assert {"CSI500", "STOXX_EUROPE_600"} <= set(bundle.indices["index_id"])
    assert bundle.indices.set_index("index_id").loc["CSI500", "official_code"] == "000905"


def test_memberships_reference_active_entity_and_basket(registry_root):
    bundle = load_registry_bundle(registry_root)
    issues = validate_registry_bundle(bundle)
    assert not [issue for issue in issues if issue.severity == "error"]


def test_one_entity_can_have_multiple_listings(registry_root):
    bundle = load_registry_bundle(registry_root)
    tsmc = bundle.listings[bundle.listings["entity_id"] == "TSMC"]
    assert {"2330_TW", "TSM_US"} <= set(tsmc["listing_id"])
```

- [x] **Step 2: Run the focused test and verify it fails**

Run:

```bash
pytest -q tests/test_research_control_tower_registries.py
```

Expected: import/file-not-found failures for the new registry package.

- [x] **Step 3: Implement contracts, CSV loaders and deterministic validation**

Validation must reject:

```text
duplicate entity_id/listing_id/basket_id/index_id
orphan listing entity_id
orphan membership entity_id or basket_id
active_to before active_from
membership_tier outside core/read_through/watch_only
AI core membership without primary_layer
index without region, display_name or official_code/provider_symbol
```

- [x] **Step 4: Populate a bounded V1 registry**

Include all primary baskets from the design. Populate the AI basket with
validated listings for the named anchor companies across US, Taiwan, Korea,
Hong Kong/mainland China and Europe. Mark unresolved China listings
`watch_only`; do not invent ticker mappings.

- [x] **Step 5: Run tests**

Run:

```bash
pytest -q tests/test_research_control_tower_registries.py
```

Expected: PASS.

- [x] **Step 6: Run static checks and review the generated coverage**

Run:

```bash
python -m py_compile src/research_control_tower/contracts.py src/research_control_tower/registries.py
python - <<'PY'
from pathlib import Path
from src.research_control_tower.registries import load_registry_bundle
b = load_registry_bundle(Path("config/research_control_tower"))
print({name: len(getattr(b, name)) for name in ("entities", "listings", "baskets", "basket_memberships", "indices")})
PY
```

Expected: no compile error and non-zero counts for every registry.

---

### Task 2: Unified company, macro, policy, index and thesis event ledger

**Repository:** `alternative-data`

**Depends on:** Task 1 contracts and registry IDs.

**Files:**
- Create: `config/research_control_tower/events.csv`
- Create: `config/research_control_tower/event_links.csv`
- Create: `config/research_control_tower/event_watch_questions.csv`
- Create: `src/research_control_tower/events.py`
- Create: `src/research_control_tower/macro.py`
- Create: `tests/test_research_control_tower_events.py`

**Interfaces:**
- Consumes: `RegistryBundle`
- Produces: `load_event_bundle(config_root: Path) -> EventBundle`
- Produces: `validate_event_bundle(events: EventBundle, registries: RegistryBundle, now_utc: Timestamp) -> list[ValidationIssue]`
- Produces: `compute_t_minus(events: DataFrame, now_utc: Timestamp) -> Series`
- Produces: `materialize_macro_calendar(source_frames: Mapping[str, DataFrame]) -> DataFrame`

- [x] **Step 1: Write failing semantic tests**

```python
def test_hard_event_requires_source_and_exact_observation(event_bundle, registry_bundle):
    issues = validate_event_bundle(event_bundle, registry_bundle, pd.Timestamp("2026-08-13T00:00:00Z"))
    assert not [i for i in issues if i.code == "hard_event_missing_source"]


def test_thesis_checkpoint_preserves_window(event_bundle):
    row = event_bundle.events.set_index("event_id").loc["AI_HBM4_QUALIFICATION_WINDOW"]
    assert row["certainty_class"] == "thesis_checkpoint"
    assert row["date_precision"] in {"month", "quarter", "half", "year"}
    assert pd.notna(row["starts_at"]) and pd.notna(row["ends_at"])


def test_event_links_resolve_to_registry(event_bundle, registry_bundle):
    issues = validate_event_bundle(event_bundle, registry_bundle, pd.Timestamp("2026-08-13T00:00:00Z"))
    assert not [i for i in issues if i.code.startswith("orphan_event_link")]
```

- [x] **Step 2: Run focused tests and verify failure**

Run:

```bash
pytest -q tests/test_research_control_tower_events.py
```

Expected: missing module and fixture/contract failures.

- [x] **Step 3: Implement event loading, versioning and validation**

Required validation includes:

```text
scope in company/basket/macro/policy/index
certainty_class in hard/provisional/thesis_checkpoint/observed
hard event source_url and first_observed_at present
thesis starts_at <= ends_at and non-exact date_precision
supersedes_event_id points to an earlier event observation
event links resolve to entity/listing/basket/index IDs
watch questions are non-empty for thesis checkpoints
source timestamps parse with timezone
```

- [x] **Step 4: Add bounded representative V1 events**

Include:

- one confirmed company earnings event per represented geography where a
  source-backed date is already available;
- representative US, China/HK, Korea/Taiwan and Europe macro events;
- CSI 500 and STOXX Europe 600 review placeholders only when source-backed;
- AI thesis windows for HBM4, advanced packaging, CPO and power/grid with
  ranges, confidence and watch questions;
- an SK Hynix HBM qualification checkpoint linked to
  `AI_BOTTLENECKS_GLOBAL`.

If a current date cannot be verified from an existing source artifact, omit
the event rather than guessing.

- [x] **Step 5: Implement deterministic T-minus**

`compute_t_minus` returns whole calendar days in the viewer-selected timezone
for display and retains the canonical UTC timestamps. Past events return
negative values; date ranges use their start.

- [x] **Step 6: Run focused tests**

Run:

```bash
pytest -q tests/test_research_control_tower_events.py
```

Expected: PASS.

---

### Task 3: Provider-specific consensus export from `financial-data`

**Repository:** `financial-data`

**Independent of:** Task 2; it may be implemented in parallel with Tasks 1–2
only when its worker has exclusive write scope in `financial-data`.

**Files:**
- Create: `src/hk_financials/control_tower_export.py`
- Create: `scripts/build_control_tower_consensus_export.py`
- Create: `tests/test_control_tower_consensus_export.py`

**Interfaces:**
- Produces: `build_control_tower_consensus_exports(connection, entity_map: DataFrame, as_of: Timestamp) -> ConsensusExportBundle`
- Produces frames: `snapshots`, `revisions`, `source_health`
- Writes the three stable Parquet artifacts defined in the interface map.

- [x] **Step 1: Write failing tests using a temporary DuckDB fixture**

```python
def test_export_keeps_providers_separate(consensus_db, entity_map):
    bundle = build_control_tower_consensus_exports(
        consensus_db, entity_map, pd.Timestamp("2026-08-13T00:00:00Z")
    )
    rows = bundle.snapshots.query("listing_id == '0700_HK' and metric == 'eps'")
    assert set(rows["provider"]) == {"akshare", "yfinance"}
    assert len(rows) == 2


def test_export_does_not_compare_misaligned_periods(consensus_db, entity_map):
    bundle = build_control_tower_consensus_exports(
        consensus_db, entity_map, pd.Timestamp("2026-08-13T00:00:00Z")
    )
    assert bundle.revisions.query("alignment_status != 'aligned'")["revision_value"].isna().all()


def test_missing_optional_provider_is_explicit(consensus_db, entity_map):
    bundle = build_control_tower_consensus_exports(
        consensus_db, entity_map, pd.Timestamp("2026-08-13T00:00:00Z")
    )
    assert "futu" in set(bundle.source_health["provider"])
    assert set(bundle.source_health["status"]) <= {"available", "degraded", "unavailable"}
```

- [x] **Step 2: Run and verify failure**

Run:

```bash
pytest -q tests/test_control_tower_consensus_export.py
```

Expected: missing export module.

- [x] **Step 3: Implement schema detection against the existing canonical DuckDB**

Read the existing consensus tables without altering them. Normalize:

```text
provider, entity_id, listing_id, metric, fiscal_period, value, statistic,
low_value, high_value, analyst_count, currency, unit, accounting_basis,
provider_asof, retrieved_at_utc, source_url, raw_hash, pit_class
```

If an upstream field does not exist, emit null plus a coverage reason; do not
infer accounting basis or analyst count.

- [x] **Step 4: Implement revision calculations**

Calculate same-provider, aligned-fiscal-period changes over available 1-day,
7-day and 30-day snapshot windows. Include:

```text
lookback_days
prior_snapshot_at
revision_value
revision_pct
analyst_count_change
dispersion
alignment_status
```

Do not create cross-provider revisions.

- [x] **Step 5: Add optional-provider coverage records**

Futu, FnGuide, Alpha Vantage and FMP are V1 optional providers. Unless
validated data already exist locally under an approved collector, export
`status=unavailable` with a non-secret reason. This task performs no network
calls and no new scraping.

- [x] **Step 6: Run focused tests and a read-only real-database smoke test**

Run:

```bash
pytest -q tests/test_control_tower_consensus_export.py
python scripts/build_control_tower_consensus_export.py --help
```

Expected: PASS and CLI usage. A real build may write only to an explicit
temporary or requested output directory; it must not mutate canonical tables.

---

### Task 4: Build compact Control Tower marts and manifest

**Repository:** `alternative-data`

**Depends on:** Tasks 1–3.

**Files:**
- Create: `src/research_control_tower/build.py`
- Create: `src/research_control_tower/cli.py`
- Create: `tests/test_research_control_tower_build.py`
- Modify: `pyproject.toml` only if a new CLI entry point is needed

**Interfaces:**
- Consumes registry bundle, event bundle, existing macro/news/filing artifacts
  and optional consensus export directory.
- Produces: `build_control_tower_marts(config: BuildConfig) -> BuildManifest`
- Writes only to the requested `.generated` or temporary output directory.

- [x] **Step 1: Write failing build tests**

```python
def test_build_writes_stable_artifact_set(tmp_path, minimal_inputs):
    manifest = build_control_tower_marts(minimal_inputs.with_output(tmp_path))
    expected = {
        "entities.parquet", "listings.parquet", "baskets.parquet",
        "basket_memberships.parquet", "indices.parquet", "events.parquet",
        "event_entity_links.parquet", "event_basket_links.parquet",
        "event_watch_questions.parquet", "macro_observations.parquet",
        "consensus_snapshots.parquet", "consensus_revisions.parquet",
        "news_filings.parquet", "source_health.parquet", "build_manifest.json",
    }
    assert expected <= {p.name for p in tmp_path.iterdir()}
    assert manifest.status in {"success", "degraded"}


def test_build_has_no_external_network_calls(tmp_path, minimal_inputs, monkeypatch):
    monkeypatch.setattr("socket.create_connection", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    build_control_tower_marts(minimal_inputs.with_output(tmp_path))
```

- [x] **Step 2: Run and verify failure**

Run:

```bash
pytest -q tests/test_research_control_tower_build.py
```

Expected: missing build module.

- [x] **Step 3: Implement deterministic build and degradation rules**

The build:

- reads only explicit local paths;
- validates schemas before writing;
- writes via a temporary directory and atomically replaces each artifact;
- computes SHA-256 and row counts;
- carries source freshness into `source_health`;
- succeeds as `degraded` when optional consensus/news inputs are absent;
- fails when registries or event contracts are invalid.

- [x] **Step 4: Integrate existing macro, filing and news artifacts through adapters**

Use existing normalized/source-backed datasets only. Emit a normalized
`news_filings` row with metadata and URL; do not copy full commercial article
bodies. Missing geographies appear in source health rather than fabricated
records.

- [x] **Step 5: Run build tests and CLI smoke**

Run:

```bash
pytest -q tests/test_research_control_tower_build.py
python -m src.research_control_tower.cli --help
```

Expected: PASS and documented `build` command.

---

### Task 5: Read-only repository, filtering and formatting layer

**Repository:** `alternative-data`

**Depends on:** Task 4 artifact schemas.

**Files:**
- Create: `apps/research-control-tower/control_tower/__init__.py`
- Create: `apps/research-control-tower/control_tower/config.py`
- Create: `apps/research-control-tower/control_tower/models.py`
- Create: `apps/research-control-tower/control_tower/repository.py`
- Create: `apps/research-control-tower/control_tower/filters.py`
- Create: `apps/research-control-tower/control_tower/formatting.py`
- Create: `tests/test_research_control_tower_repository.py`

**Interfaces:**
- Produces: `ControlTowerRepository(artifact_root: Path)`
- Produces: `repository.load_snapshot() -> ControlTowerSnapshot`
- Produces: `apply_event_filters(events: DataFrame, filters: EventFilters) -> DataFrame`
- Produces: `format_t_minus(starts_at, viewer_tz, now_utc) -> str`

- [ ] **Step 1: Write failing repository tests**

```python
def test_repository_is_read_only(generated_root, monkeypatch):
    repo = ControlTowerRepository(generated_root)
    snapshot = repo.load_snapshot()
    assert len(snapshot.entities) > 0
    assert not hasattr(repo, "save")


def test_optional_artifact_missing_enters_degraded_mode(generated_root):
    (generated_root / "consensus_revisions.parquet").unlink()
    snapshot = ControlTowerRepository(generated_root).load_snapshot()
    assert snapshot.status == "degraded"
    assert "consensus_revisions" in snapshot.missing_optional


def test_t_minus_respects_viewer_timezone():
    assert format_t_minus(
        "2026-08-15T00:30:00+09:00", "Europe/London",
        pd.Timestamp("2026-08-13T00:00:00Z"),
    ).startswith("T-")
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
pytest -q tests/test_research_control_tower_repository.py
```

Expected: missing package.

- [x] **Step 3: Implement cached, schema-validated local reads**

Required artifacts must raise a concise startup error when absent. Optional
artifacts return empty typed frames and degraded status. No repository method
may write, fetch or mutate canonical data.

- [x] **Step 4: Implement stable global filters**

Filters cover:

```text
horizon
basket_id
country
scope
certainty_class
membership_tier
importance
```

Filtering must be deterministic and retain original row order after a stable
sort by `starts_at`, `importance`, `event_id`.

- [x] **Step 5: Run tests**

Run:

```bash
pytest -q tests/test_research_control_tower_repository.py
```

Expected: PASS.

---

### Task 6: Streamlit shell, flight deck, Today and Unified Timeline

**Repository:** `alternative-data`

**Depends on:** Task 5.

**Files:**
- Create: `apps/research-control-tower/app.py`
- Create: `apps/research-control-tower/requirements.txt`
- Create: `apps/research-control-tower/control_tower/components/__init__.py`
- Create: `apps/research-control-tower/control_tower/components/flight_deck.py`
- Create: `apps/research-control-tower/control_tower/components/timeline.py`
- Create: `apps/research-control-tower/control_tower/components/source_badges.py`
- Create: `apps/research-control-tower/control_tower/pages/__init__.py`
- Create: `apps/research-control-tower/control_tower/pages/today.py`
- Create: `apps/research-control-tower/control_tower/pages/unified_timeline.py`
- Create: `tests/test_research_control_tower_streamlit.py`

**Interfaces:**
- Consumes: `ControlTowerSnapshot`
- Produces: app pages `Today` and `Unified Timeline`
- Produces pure helpers: `select_today_changes`, `select_next_catalyst`,
  `group_timeline_events`

- [ ] **Step 1: Write failing helper and AppTest tests**

```python
def test_today_is_change_driven(snapshot):
    result = select_today_changes(snapshot, since=snapshot.previous_build_at)
    assert all(result["changed_at"] > snapshot.previous_build_at)


def test_next_catalyst_prefers_confirmed_high_importance(snapshot):
    row = select_next_catalyst(snapshot.events, snapshot.now_utc)
    assert row["certainty_class"] == "hard"


def test_streamlit_shell_renders_core_navigation(app_path):
    app = AppTest.from_file(str(app_path)).run(timeout=30)
    assert not app.exception
    assert {"Today", "Unified Timeline", "AI Bottlenecks", "Company", "Source Health"} <= set(app.session_state["page_labels"])
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
pytest -q tests/test_research_control_tower_streamlit.py -k "today or next_catalyst or shell"
```

Expected: missing app/page modules.

- [x] **Step 3: Implement a compact independent shell**

Use a coherent research-terminal aesthetic inspired by, but not copied from,
AI Bottlenecks:

- stable left navigation;
- compact top flight deck;
- restrained dark/light-compatible theme;
- dense information with readable spacing;
- no external images required;
- no giant card grid;
- source/confidence badges visible without opening raw data.

- [x] **Step 4: Implement Today**

Show:

- selected universe and horizon;
- evidence/revision breadth;
- next high-priority catalyst;
- changed dates/status/confidence;
- material consensus/guidance changes;
- new official filings;
- source conflicts and stale critical sources.

If there is no previous build, label the page `initial snapshot` and show
upcoming items without claiming they changed.

- [x] **Step 5: Implement Unified Timeline**

Show:

- prioritized next catalyst beside the timeline;
- month-grouped chronological events;
- 7/30/90-day and long-range horizons;
- visibly distinct hard/provisional/thesis/observed styles;
- `T-minus`, source timezone, source link, watch questions and ticker chips;
- macro/company/policy/index filters.

- [x] **Step 6: Run focused tests and compile**

Run:

```bash
python -m py_compile apps/research-control-tower/app.py \
  apps/research-control-tower/control_tower/components/*.py \
  apps/research-control-tower/control_tower/pages/today.py \
  apps/research-control-tower/control_tower/pages/unified_timeline.py
pytest -q tests/test_research_control_tower_streamlit.py -k "today or next_catalyst or shell or timeline"
```

Expected: PASS.

---

### Task 7: AI Bottlenecks, Company and Source Health pages

**Repository:** `alternative-data`

**Depends on:** Task 6.

**Files:**
- Create: `apps/research-control-tower/control_tower/pages/ai_bottlenecks.py`
- Create: `apps/research-control-tower/control_tower/pages/company.py`
- Create: `apps/research-control-tower/control_tower/pages/source_health.py`
- Modify: `apps/research-control-tower/app.py`
- Modify: `tests/test_research_control_tower_streamlit.py`

**Interfaces:**
- Produces pure helpers: `build_theme_summary`, `build_company_view`,
  `classify_source_health`
- Completes all five V1 pages.

- [ ] **Step 1: Write failing page-helper tests**

```python
def test_ai_theme_summary_keeps_membership_tiers(snapshot):
    summary = build_theme_summary(snapshot, "HBM_MEMORY")
    assert {"core", "read_through"} <= set(summary.members["membership_tier"])


def test_sk_hynix_company_view_is_complete(snapshot):
    view = build_company_view(snapshot, entity_id="SK_HYNIX")
    assert len(view.events) > 0
    assert len(view.official_documents) > 0
    assert set(view.consensus["provider"]) >= {"yfinance"} or view.consensus_status == "unavailable"


def test_stale_available_source_is_not_healthy(source_health):
    result = classify_source_health(source_health, now_utc=pd.Timestamp("2026-08-13T00:00:00Z"))
    assert not result.query("age_days > stale_after_days")["display_status"].eq("healthy").any()
```

- [ ] **Step 2: Run and verify failure**

Run:

```bash
pytest -q tests/test_research_control_tower_streamlit.py -k "theme or sk_hynix or source"
```

Expected: missing page/helper modules.

- [x] **Step 3: Implement AI Bottlenecks**

Provide:

- theme/bottleneck cluster cards;
- core/read-through/watch-only filters;
- regional filters;
- latest evidence and revision breadth;
- upcoming catalysts by layer;
- read-through relationships;
- source coverage and unavailable-data markers.

Price performance may be contextual but cannot replace evidence change as the
primary ranking.

- [x] **Step 4: Implement Company**

Provide:

- company and listing identity;
- basket/layer memberships;
- upcoming and historical events;
- provider-specific consensus and revisions;
- official filings/news metadata;
- watch questions and invalidation evidence;
- source/PIT caveats.

SK Hynix is the acceptance fixture. If FnGuide/Futu are unavailable, show the
explicit source-health reason alongside available yfinance/official data.

- [x] **Step 5: Implement Source Health**

Show:

- collector/provider status;
- last successful collection;
- latest source observation;
- row/document count;
- age and staleness threshold;
- schema or entitlement failure;
- unresolved entity mappings;
- source conflicts;
- license/display classification.

- [x] **Step 6: Run focused and full Streamlit tests**

Run:

```bash
pytest -q tests/test_research_control_tower_streamlit.py
```

Expected: PASS.

---

### Task 8: Privacy audit, integration verification, browser QA and documentation

**Repository:** `alternative-data`

**Depends on:** Tasks 1–7.

**Files:**
- Create: `tests/test_research_control_tower_privacy.py`
- Create: `apps/research-control-tower/README.md`
- Modify: `docs/asia-markets/PROJECT_STATUS.md`
- Modify: `docs/asia-markets/DATA_CATALOG.md`
- Modify: `docs/asia-markets/REPO_BRIDGE.md` only if the export contract changes the existing bridge

**Interfaces:**
- Produces final V1 validation evidence and documented local run/build steps.

- [x] **Step 1: Write privacy and no-network tests**

```python
def test_generated_artifacts_contain_no_secret_keys(generated_root):
    forbidden = {"api_key", "secret", "token", "authorization", "cookie"}
    for path in generated_root.iterdir():
        if path.suffix in {".json", ".csv", ".txt"}:
            text = path.read_text(errors="ignore").lower()
            assert not any(term in text for term in forbidden)


def test_streamlit_navigation_makes_no_network_calls(app_path, monkeypatch):
    monkeypatch.setattr("socket.create_connection", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network")))
    app = AppTest.from_file(str(app_path)).run(timeout=30)
    assert not app.exception
```

- [x] **Step 2: Run the complete focused V1 suite**

Run:

```bash
pytest -q \
  tests/test_research_control_tower_registries.py \
  tests/test_research_control_tower_events.py \
  tests/test_research_control_tower_build.py \
  tests/test_research_control_tower_repository.py \
  tests/test_research_control_tower_streamlit.py \
  tests/test_research_control_tower_privacy.py
```

Expected: PASS.

- [x] **Step 3: Run the financial-data export suite**

Run from `/Users/henrywzh/Desktop/Quant/financial-data`:

```bash
pytest -q tests/test_control_tower_consensus_export.py
```

Expected: PASS.

- [x] **Step 4: Build portable artifacts and start the app locally**

Run:

```bash
python -m src.research_control_tower.cli build \
  --output apps/research-control-tower/.generated
streamlit run apps/research-control-tower/app.py \
  --server.headless true \
  --server.port 8511
```

Expected: successful or explicitly degraded build, and app available at
`http://127.0.0.1:8511`.

- [x] **Step 5: Browser-check all V1 flows**

Verify at desktop and narrow widths:

- Today initial/delta state;
- 7/30/90-day and long-range timeline;
- certainty distinctions and T-minus;
- AI theme and regional filters;
- SK Hynix company drill-down;
- degraded optional consensus source;
- source health and source links;
- no console errors or accidental secret/licensed payload exposure.

- [x] **Step 6: Document local operation and boundaries**

README must include:

```text
purpose and relationship to Asia Markets
artifact build command
local Streamlit command
required versus optional inputs
degraded-mode semantics
no-navigation-fetch rule
licensing/privacy boundary
hosting-readiness checklist
```

- [x] **Step 7: Run final static and diff checks**

Run:

```bash
git diff --check
python -m py_compile apps/research-control-tower/app.py
```

Expected: no errors.

---

## Review and completion gates

After every task:

1. The implementer records changed paths and exact test output.
2. A fresh Luna max-effort reviewer checks spec compliance and code quality.
3. Critical or important findings return to a Luna implementer for a bounded
   fix and scoped re-review.
4. Dependent tasks do not start until the review gate is clean.

After Task 8:

1. A fresh Luna max-effort reviewer examines the complete V1 diff.
2. One Luna fix wave addresses all accepted findings.
3. A final scoped re-review and verification run must be clean.
4. The main agent marks the goal complete only after all acceptance criteria
   in the design spec are evidenced.
