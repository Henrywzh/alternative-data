# Provider Incident Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register verified Moonshot AI and MiniMax Statuspage feeds in the provider incident tracker without changing parser or reliability behavior.

**Architecture:** Add two `SourceSpec` entries to the existing source registry. The existing Statuspage JSON extractor, pipeline source-health guard, storage natural keys, and dashboard provider discovery remain unchanged; only the feed-count copy and regression tests need updates.

**Tech Stack:** Python, requests, pandas, pytest, Atlassian Statuspage JSON, Streamlit.

## Global Constraints

- Keep Z.ai out of the source registry until its official status endpoint is reachable and verified.
- Do not alter the majority-source failure guard or historical upsert semantics.
- Preserve unrelated working-tree files and `.config`.
- Use only low-volume official status endpoints.

---

### Task 1: Add verified source specifications and tests

**Files:**
- Modify: `src/provider_incident_data/source.py`
- Modify: `dashboard/sections/provider_incidents.py`
- Test: `tests/test_provider_incident_data.py`

**Interfaces:**
- `SOURCE_SPECS` gains `moonshot` and `minimax` entries using parser `statuspage`.
- The dashboard subtitle reports ten official feeds.

- [ ] **Step 1: Write the failing registry test**

  Add a test that indexes `SOURCE_SPECS` by `provider_id` and asserts the two IDs, URLs, display names, and `statuspage` parser.

- [ ] **Step 2: Run the focused test to verify it fails**

  Run: `PYTHONPATH=src python -m pytest -q tests/test_provider_incident_data.py -k source_spec`

  Expected: FAIL because neither provider is registered yet.

- [ ] **Step 3: Add the two minimal `SourceSpec` entries**

  Add:

  ```python
  SourceSpec("moonshot", "Moonshot AI (Kimi)", "statuspage_json", "https://status.moonshot.cn/api/v2/incidents.json", "statuspage"),
  SourceSpec("minimax", "MiniMax", "statuspage_json", "https://status.minimax.io/api/v2/incidents.json", "statuspage"),
  ```

  Update the dashboard subtitle from eight to ten feeds.

- [ ] **Step 4: Run the focused test to verify it passes**

  Run: `PYTHONPATH=src python -m pytest -q tests/test_provider_incident_data.py -k source_spec`

- [ ] **Step 5: Add fixture extraction assertions**

  Reuse the existing Statuspage fixture shape with provider-specific snapshots and assert extraction returns one incident and its update for both IDs.

- [ ] **Step 6: Run the complete incident and smoke tests**

  Run: `PYTHONPATH=src python -m pytest -q tests/test_provider_incident_data.py tests/test_dashboard_smoke.py --disable-warnings`

- [ ] **Step 7: Run a live read-only verification**

  Fetch both registered URLs with `ProviderIncidentSource`, call `extract_snapshot`, and print HTTP status plus incident/update counts. Do not write normalized data from the local verification.

- [ ] **Step 8: Review the diff and commit**

  Run `git diff --check` and stage only the source, dashboard, test, spec, and plan files. Commit with:

  ```bash
  git commit -m "feat: track Moonshot and MiniMax incidents"
  ```
