# Buildings Department Md52–Md56 Historical Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first-party monthly aggregate history for BD Md52–Md56, retain raw PDF lineage, and show it as a dated dashboard trend.

**Architecture:** A new PDF archive source fetches annual BD ZIP files only when an opt-in backfill runner is invoked. It emits stage-level aggregate observations; current XLS project snapshots remain separate. The dashboard reads the latest normalized history and never downloads archives.

**Tech Stack:** Python 3, pandas, requests, zipfile, pdfplumber, pytest, Astro artifact JSON.

## Global Constraints

- Use only first-party Buildings Department Monthly Digest archives and preserve the PDF URL plus immutable raw snapshot.
- Md52 values are counts only; all unavailable units/areas must be null.
- Do not claim project linkage or create a regional split from historical PDF aggregates.
- Keep amendments as explicit observations and keep historical archive fetching out of normal pipeline/dashboard runs.
- Preserve `.config` and unrelated dirty-worktree changes.

---

## File structure

- Create: `src/hk_real_estate/sources/bd_history.py` — archive discovery, PDF extraction, aggregation, raw provenance.
- Modify: `src/hk_real_estate/config.py` — archive constants.
- Modify: `src/hk_real_estate/pipeline.py` — history quality contract and opt-in runner.
- Modify: `apps/asia-markets-dashboard/scripts/build_hk_real_estate_artifact.py` — dated history dataset.
- Modify: `apps/asia-markets-dashboard/scripts/package-dashboard.mjs` — bilingual chart copy.
- Modify: `tests/test_hk_real_estate_pipeline.py`, `tests/test_hk_real_estate_dashboard.py` — executable contracts.
- Modify: `docs/asia-markets/OPERATING_MANUAL.md`, `PROJECT_STATUS.md`, `DATA_CATALOG.md` — coverage and limits.

### Task 1: Discover deterministic annual archives

**Files:**
- Create: `src/hk_real_estate/sources/bd_history.py`
- Modify: `src/hk_real_estate/config.py`
- Test: `tests/test_hk_real_estate_pipeline.py`

**Interfaces:**
- Produces: `discover_bd_digest_archives(index_html: str) -> dict[int, str]`.
- Produces: `list_archive_pdf_members(zip_bytes: bytes, archive_year: int) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
def test_bd_history_discovers_first_party_annual_archives():
    html = '<a href="/doc/en/whats-new/monthly-digests/Md2024e.zip">2024</a>'
    assert discover_bd_digest_archives(html) == {
        2024: 'https://www.bd.gov.hk/doc/en/whats-new/monthly-digests/Md2024e.zip'
    }
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_hk_real_estate_pipeline.py -k bd_history_discovers -v`

Expected: FAIL because `bd_history` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
def discover_bd_digest_archives(index_html: str) -> dict[int, str]:
    years = re.findall(r"Md(20\\d{2})e\\.zip", index_html)
    return {int(year): f"{BD_MONTHLY_DIGEST_ARCHIVE_BASE}/Md{year}e.zip" for year in sorted(set(years))}
```

Use `zipfile.ZipFile(io.BytesIO(zip_bytes))`. Require the exact twelve names
`MdYYYYMMe.pdf`, ordered by month, and raise `ValueError` showing unexpected
or missing members.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_hk_real_estate_pipeline.py -k bd_history -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hk_real_estate/config.py src/hk_real_estate/sources/bd_history.py tests/test_hk_real_estate_pipeline.py
git commit -m "feat: discover Buildings Department history archives"
```

### Task 2: Parse stage aggregate rows safely

**Files:**
- Modify: `src/hk_real_estate/sources/bd_history.py`
- Test: `tests/test_hk_real_estate_pipeline.py`

**Interfaces:**
- Produces: `parse_bd_history_text(text: str, observation_month: str, source_url: str, archive_year: int) -> pd.DataFrame`.
- Produces: `parse_bd_history_digest(pdf_bytes: bytes, observation_month: str, source_url: str, archive_year: int) -> pd.DataFrame`.

- [ ] **Step 1: Write the failing tests**

```python
def test_bd_history_md52_keeps_unpublished_metrics_null():
    row = parse_bd_history_text(MD52_TEXT, "2024-12-01", SOURCE_URL, 2024).iloc[0]
    assert row["permit_stage"] == "Demolition Consents"
    assert row["total_projects_count"] == 3
    assert pd.isna(row["total_domestic_units"])
    assert pd.isna(row["total_domestic_gfa_sqm"])


def test_bd_history_amendment_is_separate_revision_row():
    rows = parse_bd_history_text(MD54_WITH_AMENDMENT, "2024-12-01", SOURCE_URL, 2024)
    assert set(rows["revision_status"]) == {"original", "amendment"}
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_hk_real_estate_pipeline.py -k 'bd_history_md52 or bd_history_amendment' -v`

Expected: FAIL because parser functions do not exist.

- [ ] **Step 3: Write minimal implementation**

```python
def extract_pdf_text(pdf_bytes: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        return "\\n".join(page.extract_text() or "" for page in pdf.pages)
```

Split text at `TABLE 5.2` through `TABLE 5.6` headings. Emit `HIGH` only if
the heading and a complete aggregate total parse. Populate every dataset
contract column, use null for unavailable measures, set
`parser_version="bd-history-v1"`, and add amendment blocks with
`revision_status="amendment"` rather than changing original totals.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_hk_real_estate_pipeline.py -k bd_history -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hk_real_estate/sources/bd_history.py tests/test_hk_real_estate_pipeline.py
git commit -m "feat: parse BD historical supply aggregates"
```

### Task 3: Add opt-in backfill runner

**Files:**
- Modify: `src/hk_real_estate/sources/bd_history.py`
- Modify: `src/hk_real_estate/pipeline.py`
- Test: `tests/test_hk_real_estate_pipeline.py`

**Interfaces:**
- Produces: `fetch_bd_supply_pipeline_history(start_year: int = 2005, end_year: int | None = None) -> pd.DataFrame`.
- Produces: `run_bd_history_backfill(run_id: str | None = None, *, start_year: int = 2005, end_year: int | None = None, _raise_on_failure: bool = True) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing integration test**

```python
def test_bd_history_backfill_preserves_raw_pdf_lineage():
    with patch("src.hk_real_estate.sources.bd_history.requests.get", side_effect=_archive_then_pdf_responses), \\
         patch("src.hk_real_estate.sources.bd_history.save_raw_snapshot", side_effect=["/raw/a.pdf", "/raw/b.pdf"]):
        result = fetch_bd_supply_pipeline_history(start_year=2024, end_year=2024)
    assert set(result["raw_snapshot"]) == {"/raw/a.pdf", "/raw/b.pdf"}
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_hk_real_estate_pipeline.py -k bd_history_backfill -v`

Expected: FAIL because the history fetcher does not exist.

- [ ] **Step 3: Write minimal implementation**

For every official PDF member, call
`save_raw_snapshot("bd_monthly_digest_history", pdf_bytes, file_ext="pdf", source_url=official_pdf_url)`.
Attach that returned path to rows. Register `bd_supply_pipeline_history` in
`QUALITY_SPECS`; its duplicate key is month, stage, category, revision status,
and source URL. Add only the dedicated runner, never to `run_all_pipelines`,
stage pipelines, or dashboard construction.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_hk_real_estate_pipeline.py -k bd_history -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/hk_real_estate/sources/bd_history.py src/hk_real_estate/pipeline.py tests/test_hk_real_estate_pipeline.py
git commit -m "feat: add opt-in BD history backfill"
```

### Task 4: Display history and document it

**Files:**
- Modify: `apps/asia-markets-dashboard/scripts/build_hk_real_estate_artifact.py`
- Modify: `apps/asia-markets-dashboard/scripts/package-dashboard.mjs`
- Modify: `docs/asia-markets/OPERATING_MANUAL.md`
- Modify: `docs/asia-markets/PROJECT_STATUS.md`
- Modify: `docs/asia-markets/DATA_CATALOG.md`
- Test: `tests/test_hk_real_estate_dashboard.py`

**Interfaces:**
- Consumes: `raw_bd_supply_history: pd.DataFrame | None` in `build_artifact`.
- Produces: `snapshot.datasets["bd_supply_pipeline_history"]` with `date`, `permit_stage`, `metric`, and `value`.

- [ ] **Step 1: Write the failing dashboard test**

```python
def test_dashboard_serializes_bd_history_as_dated_trend_not_snapshot():
    history = pd.DataFrame([{"observation_month": "2024-12-01", "permit_stage": "Plans Approved", "total_domestic_units": 120, "revision_status": "original", "parser_confidence": "HIGH"}])
    artifact, _ = build_artifact(BASE_FRAMES, raw_bd_supply_history=history)
    assert artifact["snapshot"]["datasets"]["bd_supply_pipeline_history"] == [{"date": "2024-12", "permit_stage": "Plans Approved", "metric": "Domestic units", "value": 120.0}]
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_hk_real_estate_dashboard.py -k bd_history -v`

Expected: FAIL because the history input and dataset do not exist.

- [ ] **Step 3: Write minimal implementation**

Load `load_latest_normalized("bd_supply_pipeline_history")` only in
`fetch_live_frames`. Serialize only `HIGH` original observations into the
main trend; leave amendments in source detail. Add Chinese/English history
labels, source coverage, and documentation of aggregate grain, archive/raw
lineage, opt-in command, null metrics and no-project-linkage limitation.

- [ ] **Step 4: Verify GREEN**

Run: `pytest -q tests/test_bd_projects.py tests/test_hk_real_estate_pipeline.py tests/test_hk_real_estate_dashboard.py tests/test_asia_markets_wiring.py && PYTHON_BIN=$(command -v python3) npm --prefix apps/asia-markets-dashboard run build`

Expected: PASS; artifact is valid with history and provides an explicit
unavailable-history state when no backfill run exists.

- [ ] **Step 5: Commit**

```bash
git add apps/asia-markets-dashboard/scripts/build_hk_real_estate_artifact.py apps/asia-markets-dashboard/scripts/package-dashboard.mjs docs/asia-markets tests/test_hk_real_estate_dashboard.py
git commit -m "feat: display Buildings Department historical supply trend"
```

## Self-review

- Archive discovery, source contract, null semantics, amendment handling, raw
  provenance and opt-in execution each have a dedicated testable task.
- The dashboard consumes a stable normalized history and cannot trigger
  archive downloads.
- All interfaces in later tasks are defined in earlier tasks; historical
  project linkage is explicitly excluded rather than deferred ambiguously.
