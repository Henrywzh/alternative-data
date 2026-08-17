# Asia Markets Overview Implementation Plan

> For agentic workers: use the executing-plans skill to implement this plan task-by-task.

**Goal:** Replace the Streamlit Overview entry page with a bounded, source-backed cross-sector pulse that remains useful as more Asia Markets sectors are added.

**Architecture:** Keep rendering in the Streamlit app and read only the existing generated sector artifacts. Define a small per-sector Overview configuration for headline metrics and optional sparklines, render a compact pulse for every connected sector, and render at most two explicitly configured featured charts. Keep full detail and source tables on the existing sector and Source Health pages.

**Tech Stack:** Python, Streamlit, pandas, Plotly, existing Asia Markets JSON artifacts, Streamlit AppTest, in-app Browser.

## Global Constraints

- Overview must not fetch externally or create a second source pipeline.
- Each sector contributes at most three headline metrics and one optional sparkline.
- Overview renders no more than two featured chart panels.
- Snapshot-only data may appear as a labelled latest reading, never as a trend.
- Every displayed metric keeps its source observation date or period where available.
- Do not change Cloudflare packaging, artifact builders or source ingestion in this task.
- Preserve the existing alternative-data visual hierarchy and Asia Markets palette.

---

### Task 1: Add bounded Overview metadata and display helpers

**Files:**
- Modify: apps/asia-markets-streamlit/app.py near the existing artifact constants and Overview helpers.
- Test: tests/test_asia_markets_streamlit_overview.py.

**Interfaces:**
- Add OVERVIEW_PULSE_CONFIG, keyed by current sector key, with no more than three metric definitions and one optional sparkline definition per sector.
- Add pure helpers for latest metric extraction and dated series extraction so missing optional datasets return an empty result instead of raising.
- Keep metric_from_card, render_line_chart, render_source_coverage and artifact contracts unchanged.

- [ ] Define current V1 pulse configuration using existing artifact datasets:
  - Labour: unemployment rate, vacancies, median monthly earnings, plus unemployment-rate sparkline.
  - Population: population, latest HK resident net flow, latest mainland visitor net retention, plus population sparkline.
- [ ] Add latest_metric_reading(artifact, dataset_id, field, fmt) returning display label, formatted value and observation label.
- [ ] Add latest_series_reading(artifact, chart_id, series_name) returning formatted value and latest observation date.
- [ ] Use latest_row and add_date_column; missing data returns em dashes and never invents a date.
- [ ] Run python -m py_compile apps/asia-markets-streamlit/app.py.

### Task 2: Replace the entry-page Overview with the scalable pulse

**Files:**
- Modify: apps/asia-markets-streamlit/app.py in render_overview and adjacent rendering helpers.

**Interfaces:**
- Change render_overview to accept the global history-window value.
- Add render_overview_header, render_sector_pulse, render_featured_trends and render_overview_health_summary.
- Keep sidebar page keys and sector-page renderers unchanged.

- [ ] Replace hard-coded connected-sector text with counts derived from artifacts, the latest available release/data date, and a mixed-date caveat.
- [ ] Render one compact pulse card or row per connected sector with sector name, market context, status/date, at most three configured metrics, and an optional sparkline whose title, latest value, point count, cadence and date range are visible before the navigation button.
- [ ] Keep the Featured trends section intentionally blank for V1 by leaving the explicit featured chart list empty; enable up to two entries only after higher-frequency inputs and derived signals have been validated.
- [ ] Do not add a dataset selectbox or full series multiselect to Overview.
- [ ] Replace the large Current scope card with a compact source-health summary and a button to Source Health.
- [ ] Wire main dispatch as render_overview(artifacts, labels, language, window).

### Task 3: Add focused regression coverage

**Files:**
- Create: tests/test_asia_markets_streamlit_overview.py.
- Modify: apps/asia-markets-streamlit/app.py only for pure-helper corrections.

- [ ] Assert every configured sector has at most three metrics and the featured chart list has at most two entries.
- [ ] Load the two current artifact JSON files and assert helpers return non-empty values and dates for unemployment rate, population and both latest ImmD series.
- [ ] Run pytest -q tests/test_asia_markets_streamlit_overview.py.

### Task 4: Validate the complete Streamlit surface

**Files:**
- No source changes expected; use the existing local app at http://127.0.0.1:8501.

- [ ] Run Streamlit AppTest across Overview, Labour, Population, Data Explorer and Source Health with no app exceptions, and assert Overview renders zero featured charts while the reserved section remains visible.
- [ ] Browser-check Overview load, two sector pulse entries, intentional blank Featured trends state, sector navigation and Source Health navigation.
- [ ] Check desktop and narrow/mobile layouts for clipping, overflow, blank charts, framework overlays and relevant console errors.
- [ ] Leave the existing 8501 server running and the browser on the new Overview page.
