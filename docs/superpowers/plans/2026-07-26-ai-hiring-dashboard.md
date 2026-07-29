# AI Hiring Dashboard Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework the Streamlit AI Hiring Demand tab into a data-honest, company-first hiring explorer while preserving the existing Indeed macro signal and all available role/seniority granularity.

**Architecture:** Keep ingestion and normalized schemas unchanged. Add a small, versioned display-only parent-segment mapping and pure analytics helpers that derive company intensity, the early-cohort trend, and the role-family × seniority matrix from the existing `hiring_demand_daily` and `hiring_jobs` datasets. The Streamlit section consumes those helpers and retains the existing job explorer and source-health coverage table.

**Tech Stack:** Python, pandas, pytest, Plotly, Streamlit, Parquet datasets already registered in `dashboard/data.py`.

## Global Constraints

- Preserve the existing Economy-Wide AI Hiring Signal sourced from Indeed Hiring Lab’s public GitHub CSV.
- Do not treat Greenhouse/Ashby company-board data as a replacement for the Indeed macro series.
- Do not invent company history: only the original 10 companies currently have nine daily observations; the other 60 are current-snapshot baselines.
- Keep the current production-backed seniority categories: `Early career`, `Individual contributor / unspecified`, `Senior / Lead`, and `Executive / Director`.
- Use active public job rows for the heatmap and label them as postings, not hires or headcount.
- Preserve raw `company_segment`; parent segments are display-only and must be explicitly mapped.
- Do not add a new scrape or normalized dataset for this UI work.
- Avoid material data copies: aggregate the existing 10k-row job table once per render and reuse the result.
- Preserve unrelated working-tree changes and `.config`.

---

### Task 1: Add an explicit parent-segment display mapping

**Files:**
- Create: `src/ai_hiring_data/segments.py`
- Test: `tests/test_ai_hiring_data.py`

**Interfaces:**
- `PARENT_SEGMENT_BY_COMPANY: dict[str, str]` covers every active company ID in `BOARD_SPECS`.
- `parent_segment_for_company(company_id: str) -> str` returns the mapped display group or `"Unmapped"`.

- [ ] **Step 1: Write the failing coverage test**

  Assert that every `company_id` in `BOARD_SPECS` appears in the mapping and that the returned group is non-empty.

- [ ] **Step 2: Run the focused test and confirm it fails**

  Run: `PYTHONPATH=src python -m pytest -q tests/test_ai_hiring_data.py -k parent_segment`

  Expected: FAIL because the mapping module does not exist.

- [ ] **Step 3: Add the minimal mapping**

  Add one explicit entry for every current company using exactly these display groups: `Foundation & model platforms`, `Data & cloud infrastructure`, `Developer & data tools`, `Consumer & services`, `Fintech & commerce`, or `Chips & compute`. Do not fuzzy-match names at render time. Keep the original `company_segment` untouched in every table.

- [ ] **Step 4: Run the focused test and confirm it passes**

  Run the same command; expect a green result with no unmapped active companies.

---

### Task 2: Add pure analytics helpers for the new views

**Files:**
- Create: `src/ai_hiring_data/analytics.py`
- Test: `tests/test_ai_hiring_data.py`

**Interfaces:**
- `build_company_intensity(demand: pd.DataFrame, parent_segment_by_company: Mapping[str, str]) -> pd.DataFrame` returns one latest `All roles` row per company with `active_requisitions`, `active_postings`, `ai_role_postings`, `ai_role_share_pct`, `company_segment`, and `parent_segment`.
- `build_early_cohort_trend(demand: pd.DataFrame, min_observations: int = 2) -> pd.DataFrame` returns `snapshot_date`, `active_requisitions`, `active_postings`, `ai_role_postings`, and `company_count` for companies meeting the observation threshold.
- `build_role_seniority_matrix(jobs: pd.DataFrame, mode: Literal["count", "share"] = "count") -> pd.DataFrame` returns rows for the eight role families and columns for the four production seniority categories.
- `build_seniority_totals(matrix: pd.DataFrame) -> pd.DataFrame` returns seniority labels and counts for the concentration panel.

- [ ] **Step 1: Write failing tests for company intensity**

  Use a small fixture with two companies and two dates. Assert that the helper selects the latest `All roles` snapshot, calculates `ai_role_share_pct = ai_role_postings / active_postings * 100`, and adds the display parent segment without dropping the raw segment.

- [ ] **Step 2: Write failing tests for cohort trend and heatmap**

  Assert that a company with one observation is excluded from the early-cohort trend, that a two-company date sums correctly, and that the heatmap preserves all four seniority columns even when a cell is zero. For `mode="share"`, assert each role-family row sums to 100% within rounding tolerance.

- [ ] **Step 3: Run the focused tests and confirm they fail**

  Run: `PYTHONPATH=src python -m pytest -q tests/test_ai_hiring_data.py -k 'company_intensity or cohort_trend or seniority_matrix'`

- [ ] **Step 4: Implement the helpers with explicit empty-data behavior**

  Normalize dates and numerics, filter to `role_family == "All roles"` for demand views, filter to `status == "active"` for job views, and return schema-correct empty frames when inputs are absent.

- [ ] **Step 5: Run the focused tests and confirm they pass**

  Re-run the focused command; expect all new helper tests to pass.

---

### Task 3: Preserve the Indeed macro section and update page hierarchy

**Files:**
- Modify: `dashboard/sections/ai_hiring.py`
- Test: `tests/test_dashboard_smoke.py`

**Interfaces:**
- Keep `_render_indeed` as the first analytical section after the KPI strip.
- Keep its country selector, `28-day average` / `Daily` control, and source wording unchanged in meaning.
- The page header must state that the macro signal and company-board tracker are different source families.

- [ ] **Step 1: Extend the dashboard smoke test with source separation assertions**

  Render the AI Hiring tab and assert that the visible output contains `Economy-Wide AI Hiring Signal`, `Indeed Hiring Lab`, and `official public ATS boards`.

- [ ] **Step 2: Run the smoke test before implementation**

  Run: `PYTHONPATH=src python -m pytest -q tests/test_dashboard_smoke.py::test_ai_hiring_section_renders_macro_company_and_job_views`

- [ ] **Step 3: Reorder the section layout**

  Keep the macro graph immediately below the KPI strip, then place the current company footprint, hiring intensity, early-cohort trend, role/seniority analysis, job explorer, and coverage definitions in that order.

- [ ] **Step 4: Re-run the smoke test**

  Confirm the section still renders without exceptions and that the macro chart remains present.

---

### Task 4: Build the current company footprint and hiring-intensity scatter

**Files:**
- Modify: `dashboard/sections/ai_hiring.py`
- Test: `tests/test_dashboard_smoke.py`

**Interfaces:**
- Add a metric control with `Active requisitions`, `Active public postings`, and `AI / ML-titled postings`.
- Add a parent-segment selector and pass the selection into the pure company-intensity frame.
- Render a sorted parent-segment bar chart plus a company ranking table.
- Render a scatter with x=`active_requisitions`, y=`ai_role_share_pct`, bubble size=`active_postings`, and color=`parent_segment`.

- [ ] **Step 1: Add a smoke-test assertion for the scatter**

  Assert that the rendered AI Hiring tab contains at least five Plotly charts after the macro, footprint, scatter, early-cohort trend, and heatmap views are added, and that no Streamlit exception is present.

- [ ] **Step 2: Implement the current cross-section views**

  Use the latest company snapshot only. Show all parent groups in the sorted bar chart; keep the company table searchable and retain raw `company_segment` alongside the derived parent group.

- [ ] **Step 3: Implement the scatter with honest labels**

  Use a visible subtitle: `Active requisitions vs AI-role share; bubble area is active public postings.` Add a caption that AI-role share is a deterministic title/team classification, not a claim that other roles do not use AI.

- [ ] **Step 4: Run the smoke test and inspect the chart objects**

  Run the focused smoke test and assert that the scatter has non-empty x/y arrays when the local hiring data is present.

---

### Task 5: Add the early-cohort trend strip with coverage guardrails

**Files:**
- Modify: `dashboard/sections/ai_hiring.py`
- Test: `tests/test_ai_hiring_data.py`
- Test: `tests/test_dashboard_smoke.py`

**Interfaces:**
- Render `10-company early cohort · N observations` using the helper’s `company_count` and date range.
- Keep a separate `28-day trend-ready cohort` state that displays an explicit unavailable message while no company has 28 days of coverage.
- Never draw a 70-company trend by carrying one-observation baselines backward.

- [ ] **Step 1: Add a regression test for the current coverage state**

  Use the local data and assert that the trend helper returns the original 10-company cohort, excludes the 60 one-observation companies, and reports nine observations.

- [ ] **Step 2: Implement the trend strip**

  Use active requisitions as the default metric, provide the same metric selector as the footprint view, and show a warning caption: `The newer companies contribute to today’s cross-section but do not support a trend yet.`

- [ ] **Step 3: Run the helper and smoke tests**

  Confirm that the chart has nine points locally and that the 28-day state is informational rather than a blank or zero-valued series.

---

### Task 6: Replace the role composition chart with the validated heatmap and concentration panel

**Files:**
- Modify: `dashboard/sections/ai_hiring.py`
- Test: `tests/test_ai_hiring_data.py`
- Test: `tests/test_dashboard_smoke.py`

**Interfaces:**
- Render `Active public postings by role family × seniority`.
- Columns must remain `Early career`, `Individual contributor / unspecified`, `Senior / Lead`, and `Executive / Director`.
- Provide `Raw count` and `% within role family` modes.
- Restore `Where the demand concentrates` as a side panel using actual totals: 55 early career, 3,593 IC/unspecified, 5,906 senior/lead, and 571 executive/director in the current snapshot.

- [ ] **Step 1: Add regression tests for actual local totals**

  Assert that the local active-job matrix totals 10,125 rows and that its seniority totals match the four values above.

- [ ] **Step 2: Implement the heatmap and side panel**

  Use a sequential blue scale, preserve zero cells, and keep the denominator visible. Do not relabel the four categories as the unsupported six-band mock taxonomy.

- [ ] **Step 3: Run the focused tests and smoke test**

  Confirm both heatmap modes render and the original job explorer remains available below the analysis section.

---

### Task 7: Keep the explorer, coverage table, and freshness definitions coherent

**Files:**
- Modify: `dashboard/sections/ai_hiring.py`
- Test: `tests/test_dashboard_smoke.py`

- [ ] **Step 1: Add visible coverage labels**

  Keep the current board-health table and add the latest snapshot date, observation count, and maturity label for each company where space allows.

- [ ] **Step 2: Preserve raw lookup fields**

  The explorer must retain company name, raw `company_segment`, active requisitions, public postings, AI-role postings/share, and history maturity. Parent grouping is an additional display field, not a replacement.

- [ ] **Step 3: Run the smoke test**

  Assert that three dataframes remain available: company explorer, source-health coverage, and the existing job explorer.

---

### Task 8: Validate data, responsive layout, and performance

**Files:**
- Modify: `tests/test_dashboard_smoke.py` only if assertions need updating.
- No new production data files.

- [ ] **Step 1: Run focused tests**

  ```bash
  PYTHONPATH=src python -m pytest -q tests/test_ai_hiring_data.py tests/test_dashboard_smoke.py --disable-warnings
  ```

- [ ] **Step 2: Run the dashboard data tests**

  ```bash
  PYTHONPATH=src python -m pytest -q tests/test_dashboard_data.py --disable-warnings
  ```

- [ ] **Step 3: Run local-data reconciliation checks**

  Verify that the company snapshot has 70 companies, active postings total 10,125, AI-role postings total 1,243, seniority totals reconcile to 10,125, and the trend has 10 companies with nine observations.

- [ ] **Step 4: Render-check the Streamlit tab at desktop and narrow widths**

  Confirm that the macro chart, scatter, heatmap, and concentration panel do not clip; controls remain usable; and the trend warning is visible without requiring a hover.

- [ ] **Step 5: Check the diff and commit only feature files**

  Run `git diff --check`, review the diff against this plan, and stage only the analytics helper, segment mapping, dashboard section, and relevant tests. Do not stage the user’s unrelated AI hiring expansion changes or mockup artifacts unless explicitly requested.
