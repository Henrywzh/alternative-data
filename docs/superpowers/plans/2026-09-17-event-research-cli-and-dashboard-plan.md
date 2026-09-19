# Event Research CLI and Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repo-local, read-only event research CLI and make the standalone Events & Consensus page serve briefing, event research, and post-release review from the same query core.

**Architecture:** Keep `event_consensus` as the only data owner. Add `EventQueryService` as a pure read model over the latest JSON artifact and append-only Parquet ledgers; expose it through `event-consensus query ...` and call it directly from Streamlit. Preserve the existing refresh pipeline and make refresh the only operation allowed to contact remote sources.

**Tech Stack:** Python 3.11, pandas, PyArrow/Parquet, argparse, pytest, Streamlit, existing Asia Markets page registry.

**Spec:** `docs/superpowers/specs/2026-09-17-event-research-cli-and-dashboard-design.md`

## Global Constraints

- Query commands are offline, read-only, and make zero remote calls.
- Query commands emit one JSON document to stdout; diagnostics go to stderr.
- Existing root-level refresh invocations and scheduled workflows remain compatible.
- Provider importance `1` always maps to high display priority.
- Missing evidence is explicit; no consensus dispersion, event beta, or market reaction is imputed.
- Streamlit and CLI consume the same query core; no dashboard-only event pipeline is allowed.
- The standalone Events & Consensus page remains separate from ETF Monitor.
- MCP, HTTP, REST, and hosted APIs are out of scope.

---

### Task 1: Close and commit the standalone Events & Consensus page migration

**Files:**
- Modify: `apps/asia-markets-streamlit/am/events_consensus.py`
- Modify: `apps/asia-markets-streamlit/am/market_page.py`
- Modify: `apps/asia-markets-streamlit/am/page_registry.py`
- Modify: `apps/asia-markets-streamlit/am/sidebar.py`
- Modify: `docs/asia-markets/DATA_CATALOG.md`
- Modify: `docs/asia-markets/MARKET_MONITOR_STREAMLIT.md`
- Modify: `docs/asia-markets/OPERATING_MANUAL.md`
- Modify: `docs/asia-markets/PROJECT_STATUS.md`
- Modify: `tests/event_consensus/test_streamlit_contract.py`
- Modify: `tests/test_asia_markets_streamlit_pages.py`

**Interfaces:**
- Produces: registered page key `events`, URL path `events-consensus`, and renderer `am.events_consensus:render_events_consensus`.
- Preserves: `market_page.py` renders ETF Monitor only; `events_consensus.py` keeps explicit manual refresh behavior.

- [ ] **Step 1: Verify the existing red/green baseline.**

  Run:

  ```bash
  PYTHONPATH=src:. python -m pytest \
    tests/event_consensus/test_streamlit_contract.py \
    tests/test_asia_markets_streamlit_pages.py -q
  ```

  Expected: all current migration tests pass; no event mode is present in the ETF page source.

- [ ] **Step 2: Check the migration diff and page contract.**

  Run:

  ```bash
  git diff --check
  rg -n 'events-consensus|render_events_consensus|market_monitor_mode' \
    apps/asia-markets-streamlit/am tests/event_consensus tests/test_asia_markets_streamlit_pages.py
  ```

  Expected: the standalone registry/sidebar references exist, `market_monitor_mode` is absent from `market_page.py`, and `git diff --check` is clean.

- [ ] **Step 3: Commit only the migration files.**

  Stage the ten paths listed above explicitly, review `git diff --cached --stat`, and commit:

  ```bash
  git add \
    apps/asia-markets-streamlit/am/events_consensus.py \
    apps/asia-markets-streamlit/am/market_page.py \
    apps/asia-markets-streamlit/am/page_registry.py \
    apps/asia-markets-streamlit/am/sidebar.py \
    docs/asia-markets/DATA_CATALOG.md \
    docs/asia-markets/MARKET_MONITOR_STREAMLIT.md \
    docs/asia-markets/OPERATING_MANUAL.md \
    docs/asia-markets/PROJECT_STATUS.md \
    tests/event_consensus/test_streamlit_contract.py \
    tests/test_asia_markets_streamlit_pages.py
  git diff --cached --check
  git commit -m "feat(events): make events consensus a standalone page"
  ```

  Expected: the commit contains only the standalone-page migration; the approved design and implementation plan remain separate commits.

---

### Task 2: Add the read-only query core with the common response envelope

**Files:**
- Create: `src/event_consensus/query.py`
- Create: `tests/event_consensus/conftest.py`
- Create: `tests/event_consensus/test_query.py`

**Interfaces:**
- Consumes: `event_consensus.storage.load_artifact`, `load_event_ledger`, `load_quote_ledger`, `load_component_ledger`, and the existing normalized event fields.
- Produces: `QueryError` and `EventQueryService` with the methods below. Every public method returns a JSON-serializable `dict` with the common envelope.

  ```python
  class EventQueryService:
      def __init__(
          self,
          *,
          artifact_path: Path = LATEST_ARTIFACT_PATH,
          event_ledger_path: Path = EVENT_LEDGER_PATH,
          quote_ledger_path: Path = QUOTE_LEDGER_PATH,
          component_ledger_path: Path = COMPONENT_LEDGER_PATH,
          now_utc: datetime | None = None,
      ) -> None: ...

      def capabilities(self) -> dict[str, Any]: ...
      def brief(self, *, horizon_hours: int = 48, countries: Iterable[str] | None = None, limit: int = 10) -> dict[str, Any]: ...
      def list_events(self, *, start_utc: str | None = None, end_utc: str | None = None, countries: Iterable[str] | None = None, priority: str | None = None, event_family: str | None = None, checkpoint: str | None = None, released: bool | None = None) -> dict[str, Any]: ...
      def research(self, event_id: str) -> dict[str, Any]: ...
      def history(self, event_id: str) -> dict[str, Any]: ...
      def postmortem(self, event_id: str) -> dict[str, Any]: ...
      def health(self) -> dict[str, Any]: ...
  ```

- [ ] **Step 1: Create shared fixtures and write failing tests for the envelope and capabilities.**

  Add `tests/event_consensus/conftest.py` with `NOW`, `write_artifact(tmp_path)`, `write_event_ledger(tmp_path)`, and `fake_pipeline_result()`. The artifact helper writes two events, one provider-importance `1` event with a low score, one normal event, consensus history, one quote, one component, and source health. Add `tests/event_consensus/test_query.py` with:

  ```python
  def test_capabilities_describe_loaded_artifact(tmp_path):
      service = EventQueryService(artifact_path=write_artifact(tmp_path))
      result = service.capabilities()
      assert result["query"] == "capabilities"
      assert result["artifact_schema_version"] == "1.0"
      assert result["data"]["countries"] == ["CN", "US"]
      assert "brief" in result["data"]["commands"]

  def test_missing_artifact_fails_closed(tmp_path):
      with pytest.raises(QueryError, match="latest artifact"):
          EventQueryService(artifact_path=tmp_path / "missing.json").health()
  ```

- [ ] **Step 2: Run the focused tests to verify the expected failure.**

  Run:

  ```bash
  PYTHONPATH=src:. python -m pytest tests/event_consensus/test_query.py -q
  ```

  Expected: collection fails because `event_consensus.query` and `EventQueryService` do not exist yet.

- [ ] **Step 3: Implement the minimal loader and envelope.**

  Implement `QueryError`, `_load_required_artifact`, `_envelope`, `_as_records`, and `EventQueryService.__init__`. The loader must call only local storage functions, reject a missing/non-dict artifact, preserve the artifact `content_hash`, and calculate `data_as_of_utc` from available `retrieved_at_utc` values. Do not import `event_consensus.pipeline`.

  Use this envelope shape:

  ```python
  {
      "query_contract_version": "1.0",
      "query": query_name,
      "generated_at_utc": query_time,
      "data_as_of_utc": data_as_of,
      "artifact_schema_version": artifact.get("schema_version"),
      "content_hash": artifact.get("content_hash"),
      "status": "ready",
      "source_health_summary": summary,
      "filters": filters,
      "data": data,
      "warnings": warnings,
  }
  ```

- [ ] **Step 4: Implement `capabilities()` and `health()` and run the tests.**

  Derive countries, event families, observed ranges, component families, and supported commands from the artifact. Summarize each source-health status and record count. A valid empty artifact returns `status="ready"` with empty collections; an unreadable artifact raises `QueryError`.

  Run:

  ```bash
  PYTHONPATH=src:. python -m pytest tests/event_consensus/test_query.py -q
  ```

  Expected: the envelope and capabilities tests pass.

---

### Task 3: Implement briefing, list, research, history, and postmortem read models

**Files:**
- Modify: `src/event_consensus/query.py`
- Modify: `tests/event_consensus/test_query.py`

**Interfaces:**
- Consumes: `EventQueryService` loader and envelope from Task 2.
- Produces: deterministic query results used by both CLI and Streamlit. The query layer never calls a source adapter or refresh function.

- [ ] **Step 1: Write failing tests for priority and timeline behavior.**

  Add tests with `now_utc=2026-09-17T00:00:00Z`:

  ```python
  def test_brief_keeps_provider_importance_one_high_even_with_low_score(tmp_path):
      service = EventQueryService(artifact_path=write_artifact(tmp_path), now_utc=NOW)
      rows = service.brief(horizon_hours=48)["data"]["events"]
      assert rows[0]["event_id"] == "tradingview:importance-one"
      assert rows[0]["priority"] == "high"
      assert rows[0]["priority_reason"] == "provider_importance_1"

  def test_list_events_filters_country_priority_and_release_state(tmp_path):
      service = EventQueryService(artifact_path=write_artifact(tmp_path), now_utc=NOW)
      rows = service.list_events(countries=["US"], priority="high", released=False)["data"]["events"]
      assert [row["country"] for row in rows] == ["US"]
      assert all(row["priority"] == "high" for row in rows)
  ```

- [ ] **Step 2: Run the tests to verify the expected failure.**

  Run:

  ```bash
  PYTHONPATH=src:. python -m pytest tests/event_consensus/test_query.py -q
  ```

  Expected: the new tests fail because the read models do not exist.

- [ ] **Step 3: Implement deterministic priority and event-list helpers.**

  Add private helpers for UTC parsing, priority band, priority reason, release state, availability reason, and stable sorting. Apply provider importance `1` before score thresholds. Return event records with normalized `priority`, `priority_reason`, `released`, `availability`, and original PIT/source fields. Keep provider importance and evidence quality as separate fields.

- [ ] **Step 4: Implement `brief()` and `list_events()` and run tests.**

  `brief()` defaults to the next 48 hours, includes high/medium records, returns `hidden_low_priority_count`, and sorts provider-high override first, then descending risk score, then scheduled timestamp. `list_events()` supports all filters in the spec and returns a deterministic event list.

  Run:

  ```bash
  PYTHONPATH=src:. python -m pytest tests/event_consensus/test_query.py -q
  ```

  Expected: briefing and list tests pass.

- [ ] **Step 5: Write failing tests for dossier, PIT history, and postmortem semantics.**

  Add tests:

  ```python
  def test_research_joins_consensus_components_quotes_and_scenarios(tmp_path):
      service = EventQueryService(
          artifact_path=write_artifact(tmp_path),
          event_ledger_path=write_event_ledger(tmp_path),
          now_utc=NOW,
      )
      data = service.research("tradingview:importance-one")["data"]
      assert data["event"]["event_id"] == "tradingview:importance-one"
      assert data["consensus_history"]
      assert data["quotes"]
      assert data["scenario_templates"]

  def test_history_preserves_snapshot_lineage_and_does_not_collapse_pit_rows(tmp_path):
      service = EventQueryService(
          artifact_path=write_artifact(tmp_path),
          event_ledger_path=write_event_ledger(tmp_path),
      )
      rows = service.history("tradingview:importance-one")["data"]["observations"]
      assert [row["snapshot_id"] for row in rows] == ["old", "new"]
      assert [row["trigger_type"] for row in rows] == ["scheduled", "manual"]

  def test_postmortem_explains_insufficient_history_without_inventing_reaction(tmp_path):
      service = EventQueryService(artifact_path=write_artifact(tmp_path))
      data = service.postmortem("tradingview:importance-one")["data"]
      assert data["market_reaction"]["status"] == "insufficient_history"
      assert data["market_reaction"]["observations"] == []
  ```

- [ ] **Step 6: Run the tests to verify the expected failure.**

  Run the focused query test file and confirm the new assertions fail for missing methods or incomplete joins, not due to fixture syntax.

- [ ] **Step 7: Implement dossier, history, and postmortem.**

  `research()` returns the event, consensus history, matching component contracts/official components, quotes, scenarios, and evidence lineage. `history()` reads the event ledger without collapsing changed observations. `postmortem()` includes actual, prior revision, verification state, and available post-release checkpoints; it returns a structured `insufficient_history` market-reaction object when no valid event-study observations exist.

- [ ] **Step 8: Run query-core tests and refactor only after green.**

  Run:

  ```bash
  PYTHONPATH=src:. python -m pytest tests/event_consensus/test_query.py -q
  ```

  Expected: all query-core tests pass with no network access. Only then extract duplicated normalization helpers or improve names while preserving the tested response shapes.

---

### Task 4: Add the query subcommands while preserving refresh compatibility

**Files:**
- Modify: `src/event_consensus/cli.py`
- Create: `tests/event_consensus/test_cli.py`

**Interfaces:**
- Consumes: `EventQueryService` and `QueryError` from Task 2/3.
- Produces: `event-consensus query capabilities|brief|list|research|history|postmortem|health`, one JSON document on stdout, non-zero exit codes for invalid or missing data.

- [ ] **Step 1: Write failing CLI contract tests.**

  Import `write_artifact` and `fake_pipeline_result` from `tests/event_consensus/conftest.py`. Use `main([...])`, `capsys`, and the temporary artifact. Cover:

  ```python
  def test_query_brief_writes_one_json_document_to_stdout(tmp_path, capsys):
      artifact = write_artifact(tmp_path)
      assert main(["query", "brief", "--artifact-path", str(artifact)]) == 0
      captured = capsys.readouterr()
      assert captured.err == ""
      payload = json.loads(captured.out)
      assert payload["query"] == "brief"

  def test_query_missing_event_returns_nonzero_and_diagnostic_on_stderr(tmp_path, capsys):
      artifact = write_artifact(tmp_path)
      assert main(["query", "research", "--event-id", "missing", "--artifact-path", str(artifact)]) == 2
      captured = capsys.readouterr()
      assert captured.out == ""
      assert "missing" in captured.err

  def test_query_does_not_call_refresh_pipeline(monkeypatch, tmp_path):
      monkeypatch.setattr("event_consensus.pipeline.run_pipeline", lambda **_: (_ for _ in ()).throw(AssertionError("network refresh")))
      assert main(["query", "health", "--artifact-path", str(write_artifact(tmp_path))]) == 0

  def test_legacy_refresh_arguments_still_parse(monkeypatch, tmp_path):
      monkeypatch.setattr("event_consensus.cli.run_pipeline", fake_pipeline_result)
      assert main(["--no-write", "--artifact-path", str(tmp_path / "latest.json")]) == 0
  ```

- [ ] **Step 2: Run the CLI tests to verify the expected failure.**

  Run:

  ```bash
  PYTHONPATH=src:. python -m pytest tests/event_consensus/test_cli.py -q
  ```

  Expected: query commands fail because the CLI dispatch and query parser do not exist.

- [ ] **Step 3: Implement query dispatch and JSON output.**

  Keep legacy root-level refresh flags working. Dispatch `query` to a read-only parser, dispatch explicit `refresh` to the existing refresh parser, and treat all other root-level arguments as the legacy refresh form. Add common local path flags and `--format json` with JSON as the only V1 format. Catch `QueryError`, print only the diagnostic to stderr, and return `2`.

- [ ] **Step 4: Run CLI tests and the existing refresh CLI tests.**

  Run:

  ```bash
  PYTHONPATH=src:. python -m pytest tests/event_consensus/test_cli.py tests/event_consensus/test_pipeline.py -q
  ```

  Expected: query contract tests and existing refresh pipeline tests pass; no query test invokes a source adapter.

- [ ] **Step 5: Validate the installed/local command.**

  Run:

  ```bash
  PYTHONPATH=src:. python -m event_consensus.cli query capabilities
  PYTHONPATH=src:. python -m event_consensus.cli query brief --horizon-hours 48
  ```

  Expected: each command emits one parseable JSON document and does not append to any ledger.

---

### Task 5: Document local agent discovery and query semantics

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/asia-markets/OPERATING_MANUAL.md`
- Modify: `docs/asia-markets/DATA_CATALOG.md`
- Create: `docs/asia-markets/EVENT_RESEARCH_CLI.md`

**Interfaces:**
- Consumes: the final CLI command names and response semantics from Task 4.
- Produces: durable instructions that a repo-local Codex/Claude agent can follow without scraping Streamlit or guessing artifact paths.

- [ ] **Step 1: Write the documentation contract.**

  The new page must state that the first discovery command is:

  ```bash
  event-consensus query capabilities
  ```

  It must show one example each for `brief`, `research`, `history`, `postmortem`, and `health`; explain that query commands are read-only; and identify `event-consensus refresh` as the only command that may contact remote sources.

- [ ] **Step 2: Add the command reference and repository pointers.**

  Add the concise entry point to `AGENTS.md` and the Asia Markets operating manual. Put the detailed examples, envelope fields, PIT cautions, missing-value statuses, and no-scraping rule in `EVENT_RESEARCH_CLI.md`.

- [ ] **Step 3: Validate documentation consistency.**

  Run:

  ```bash
  rg -n 'event-consensus query|event-consensus refresh|read-only|PIT|MCP' \
    AGENTS.md docs/asia-markets/EVENT_RESEARCH_CLI.md \
    docs/asia-markets/OPERATING_MANUAL.md docs/asia-markets/DATA_CATALOG.md
  git diff --check
  ```

  Expected: all documented command names match the CLI parser and no documentation claims remote agent access or MCP support.

---

### Task 6: Refactor Streamlit to use the query core and add the three workflows

**Files:**
- Modify: `apps/asia-markets-streamlit/am/events_consensus.py`
- Modify: `tests/event_consensus/test_streamlit_contract.py`
- Modify: `tests/test_asia_markets_streamlit_pages.py`

**Interfaces:**
- Consumes: `EventQueryService` from Task 2/3; existing `_run_manual_refresh()` remains the only mutating path.
- Produces: standalone page modes `Briefing`, `Event Research`, and `Post-release Review`, with Briefing selected by default.

- [ ] **Step 1: Write failing Streamlit contract tests.**

  Add source/behavior assertions that:

  ```python
  def test_events_page_exposes_all_three_research_modes():
      source = _events_source()
      assert "Briefing" in source
      assert "Event Research" in source
      assert "Post-release Review" in source

  def test_events_page_uses_query_service_for_read_models():
      source = _events_source()
      assert "EventQueryService" in source
      assert "service.brief(" in source
      assert "service.research(" in source
      assert "service.postmortem(" in source

  def test_navigation_still_does_not_call_refresh_pipeline():
      source = _events_source()
      assert "run_pipeline(trigger_type=\"manual\", write=True)" in source
      assert source.count("run_pipeline(trigger_type=\"manual\", write=True)") == 1
  ```

- [ ] **Step 2: Run the tests to verify the expected failure.**

  Run:

  ```bash
  PYTHONPATH=src:. python -m pytest \
    tests/event_consensus/test_streamlit_contract.py \
    tests/test_asia_markets_streamlit_pages.py -q
  ```

  Expected: the new mode/query assertions fail because the current page reads the artifact directly.

- [ ] **Step 3: Add a cached query-service loader and mode selector.**

  Add a page-local loader keyed by artifact/ledger mtimes so read-side data is cached but refresh clears the cache. Add a horizontal mode selector with the exact internal values `briefing`, `research`, and `postmortem`; display localized labels, defaulting to `briefing`. Keep timezone, country, provider-importance filtering, and explicit refresh controls.

- [ ] **Step 4: Implement Briefing using `service.brief()`.**

  Render a decision-first summary above the existing operational status:

  - count of high-priority events in the next 48 hours;
  - count with consensus and count awaiting consensus;
  - top selected events with countdown, selection reason, evidence state, and affected scenario family;
  - grouped 7-14 day timeline using `service.list_events()`.

  Keep colors tied to priority/status only. Preserve the provider-importance `1` override and render missing values as `—`.

- [ ] **Step 5: Implement Event Research using `service.research()`.**

  Keep the selected-event console and existing component/scenario/source renderers, but pass them dossier data from the query service. Display score factors separately from source quality, label cross-asset quotes as market context, and show explicit availability messages for absent actuals, components, or historical beta.

- [ ] **Step 6: Implement Post-release Review using `service.postmortem()`.**

  Select released events from `service.list_events(released=True)`, show consensus versus actual and revised prior, verification status, and available post-release checkpoints. If the response says `insufficient_history`, display that status and sample-size warning instead of a reaction chart or trade conclusion.

- [ ] **Step 7: Run focused page tests and compile checks.**

  Run:

  ```bash
  PYTHONPATH=src:. python -m pytest \
    tests/event_consensus \
    tests/test_asia_markets_streamlit_pages.py \
    tests/test_asia_markets_streamlit_contracts.py -q
  python -m py_compile \
    apps/asia-markets-streamlit/app.py \
    apps/asia-markets-streamlit/am/events_consensus.py \
    apps/asia-markets-streamlit/am/page_registry.py \
    apps/asia-markets-streamlit/am/sidebar.py
  ```

  Expected: focused tests pass, with only previously known non-blocking warnings if they remain in the heat-map code.

---

### Task 7: End-to-end local verification and implementation commits

**Files:**
- Modify: files from Tasks 2-6 only
- Test: `tests/event_consensus/`, `tests/test_asia_markets_streamlit_pages.py`, `tests/test_asia_markets_streamlit_contracts.py`

**Interfaces:**
- Consumes: final query core, CLI, docs, and Streamlit modes.
- Produces: verified local CLI and browser behavior with separate, reviewable commits. No push is performed unless explicitly requested.

- [ ] **Step 1: Run the complete relevant test suite.**

  Run:

  ```bash
  PYTHONPATH=src:. python -m pytest \
    tests/event_consensus \
    tests/test_asia_markets_streamlit_pages.py \
    tests/test_asia_markets_streamlit_contracts.py -q
  git diff --check
  ```

  Expected: zero test failures and no whitespace errors.

- [ ] **Step 2: Run the local CLI against the real artifact.**

  Run:

  ```bash
  PYTHONPATH=src:. python -m event_consensus.cli query capabilities
  PYTHONPATH=src:. python -m event_consensus.cli query brief --horizon-hours 48
  PYTHONPATH=src:. python -m event_consensus.cli query health
  ```

  Parse each stdout value as JSON and verify that the artifact content hash and source-health summary are present. Record the observed event count and warning state in the implementation handoff; do not alter the artifact during these commands.

- [ ] **Step 3: Smoke-test the browser.**

  Start or reuse the local server:

  ```bash
  PYTHONPATH=src:. streamlit run apps/asia-markets-streamlit/app.py \
    --server.headless true --server.address 127.0.0.1 --server.port 8501
  ```

  Verify `/events-consensus` shows the standalone page, Briefing is the default mode, the ETF page has no nested Events mode, and switching to Event Research and Post-release Review does not trigger a network refresh. Verify the page still shows `—` for missing units rather than `nan`.

- [ ] **Step 4: Review and commit implementation slices.**

  Review `git status --short`, `git diff --stat`, and `git diff --check`. Stage only implementation files and use focused commits:

  ```bash
  git commit -m "feat(events): add read-only event query core"
  git commit -m "feat(events): expose local query CLI"
  git commit -m "feat(events): add briefing and review workflows"
  ```

  If a slice is too small to stand alone, combine it with its direct consumer and keep the commit message specific. Do not stage unrelated user changes and do not push without a separate explicit request.
