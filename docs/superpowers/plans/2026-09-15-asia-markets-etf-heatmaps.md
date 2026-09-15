# Asia Markets ETF Heat Maps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Streamlit-only Heat Maps page with source-backed ETF return treemaps, validated China-listed ETF flow views, ETF price/moving-average detail, and an optional local US ETF post-close flow sampler.

**Architecture:** Extend `market_monitor` with a curated cross-asset ETF universe and pure derivation functions, then publish additive datasets through the existing market-monitor artifact. Render those datasets in a focused `am.heatmaps` page; the existing ETF Monitor and Market Regime pages keep their current responsibilities. US fund flow starts as an explicitly labelled market-cap proxy and remains unavailable until two valid local observations exist.

**Tech Stack:** Python 3.11+, pandas, yfinance, Plotly, Streamlit, Parquet/JSON artifacts, pytest.

**Spec:** `docs/superpowers/specs/2026-09-15-asia-markets-etf-heatmaps-design.md`

## Global Constraints

- The product surface is Asia Markets Streamlit only; do not add Cloudflare sector or portable-page wiring.
- Missing returns and flows remain null and never become zero.
- China monetary flow uses only exchange-published share changes and same-day published NAV.
- US estimated flow is labelled `market_cap_proxy`, begins after deployment, and requires two valid observations.
- Streamlit performs no external fetch during page navigation.
- Every derived row retains source, observation date, retrieval timestamp and run lineage.
- Existing stablecoin working-tree changes are unrelated and must not be staged, modified or discarded.

---

### Task 1: Curated heat-map universe and return snapshot

**Files:**
- Create: `src/market_monitor/heatmaps.py`
- Modify: `src/market_monitor/us_etf/universe.py`
- Test: `tests/market_monitor/test_heatmaps.py`

**Interfaces:**
- Consumes: daily rows with `date`, `ticker`, `close`; universe rows with `ticker`, `name_en`, `name_zh`, `category`, `currency`.
- Produces: `market_monitor.us_etf.universe.HEATMAP_ETFS`; `build_return_snapshot(prices: pd.DataFrame, universe: Sequence[Mapping[str, Any]], *, as_of: str | None = None) -> pd.DataFrame`.

- [ ] **Step 1: Write failing universe and return tests**

```python
def test_heatmap_universe_covers_five_asset_groups():
    assert {row["category"] for row in HEATMAP_ETFS} == {
        "broad_equity", "sector", "international", "commodity", "fixed_income"
    }

def test_return_snapshot_uses_trading_session_and_calendar_ytd():
    prices = pd.DataFrame([
        {"date": "2025-12-31", "ticker": "SPY", "close": 100.0},
        {"date": "2026-01-02", "ticker": "SPY", "close": 110.0},
        {"date": "2026-01-05", "ticker": "SPY", "close": 121.0},
    ])
    result = build_return_snapshot(prices, [_spy()], as_of="2026-01-05").iloc[0]
    assert result["return_1d_pct"] == pytest.approx(10.0)
    assert result["return_ytd_pct"] == pytest.approx(10.0)
    assert pd.isna(result["return_1m_pct"])
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `PYTHONPATH=src pytest tests/market_monitor/test_heatmaps.py -q`

Expected: collection fails because `market_monitor.heatmaps` and `HEATMAP_ETFS` do not exist.

- [ ] **Step 3: Add the curated universe**

Add `HEATMAP_ETFS` to `src/market_monitor/us_etf/universe.py` with unique
tickers and bilingual names:

```python
HEATMAP_ETFS = [
    {"ticker": "SPY", "name_en": "SPDR S&P 500 ETF", "name_zh": "标普500 ETF", "category": "broad_equity", "currency": "USD"},
    {"ticker": "QQQ", "name_en": "Invesco QQQ", "name_zh": "纳斯达克100 ETF", "category": "broad_equity", "currency": "USD"},
    {"ticker": "XLK", "name_en": "Technology Select Sector SPDR", "name_zh": "美国科技行业ETF", "category": "sector", "currency": "USD"},
    {"ticker": "EFA", "name_en": "iShares MSCI EAFE ETF", "name_zh": "发达市场（除美加）ETF", "category": "international", "currency": "USD"},
    {"ticker": "GLD", "name_en": "SPDR Gold Shares", "name_zh": "黄金ETF", "category": "commodity", "currency": "USD"},
    {"ticker": "AGG", "name_en": "iShares Core U.S. Aggregate Bond ETF", "name_zh": "美国综合债券ETF", "category": "fixed_income", "currency": "USD"},
]
```

Complete the reference-inspired set with the existing 11 sector SPDRs plus
IVV, DIA, RSP, MDY, IWM, EEM, SLV, USO, SHY, HYG, LQD and IEF. Reuse existing
sector metadata rather than duplicating sector names and fees.

- [ ] **Step 4: Implement pure return derivation**

Implement exact session returns for 1D/1W/1M/3M/1Y using 1/5/20/63/252
observations and YTD from the last close before the current calendar year:

```python
RETURN_WINDOWS = {"1d": 1, "1w": 5, "1m": 20, "3m": 63, "1y": 252}

def _session_return(closes: pd.Series, sessions: int) -> float | None:
    return None if len(closes) <= sessions else (closes.iloc[-1] / closes.iloc[-sessions - 1] - 1.0) * 100.0
```

Deduplicate by ticker/date, reject non-positive closes, preserve nulls for
short histories and emit `as_of`, latest price and all six return fields.

- [ ] **Step 5: Run focused tests**

Run: `PYTHONPATH=src pytest tests/market_monitor/test_heatmaps.py -q`

Expected: all Task 1 tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/market_monitor/heatmaps.py src/market_monitor/us_etf/universe.py tests/market_monitor/test_heatmaps.py
git commit -m "feat(market-monitor): derive ETF heat-map returns"
```

---

### Task 2: Validated flow-window snapshot

**Files:**
- Modify: `src/market_monitor/heatmaps.py`
- Test: `tests/market_monitor/test_heatmaps.py`

**Interfaces:**
- Consumes: existing `etf_fund_activity_daily` rows.
- Produces: `build_flow_snapshot(activity: pd.DataFrame, metadata: pd.DataFrame, *, as_of: str | None = None) -> pd.DataFrame`.

- [ ] **Step 1: Write failing flow tests**

```python
def test_flow_snapshot_sums_only_validated_rows():
    rows = pd.DataFrame([
        _activity("2026-09-12", 100.0, "validated"),
        _activity("2026-09-13", 999.0, "shares_only"),
        _activity("2026-09-14", -40.0, "validated"),
    ])
    row = build_flow_snapshot(rows, _metadata()).iloc[0]
    assert row["flow_1w"] == pytest.approx(60.0)
    assert row["valid_observations"] == 2

def test_flow_snapshot_does_not_turn_unavailable_into_zero():
    row = build_flow_snapshot(
        pd.DataFrame([_activity("2026-09-14", None, "shares_only")]),
        _metadata(),
    ).iloc[0]
    assert pd.isna(row["flow_1d"])
    assert row["coverage_status"] == "shares_only"
```

- [ ] **Step 2: Run the focused tests and confirm failure**

Run: `PYTHONPATH=src pytest tests/market_monitor/test_heatmaps.py -q`

Expected: flow tests fail because `build_flow_snapshot` does not exist.

- [ ] **Step 3: Implement flow aggregation**

Use the latest valid observation as `as_of`; calculate:

```python
FLOW_CALENDAR_DAYS = {"1d": 1, "1w": 7, "1m": 30, "3m": 90}
```

Sum `estimated_flow_cny` only where `flow_status == "validated"`. YTD begins
on January 1. Emit `flow_1d`, `flow_1w`, `flow_1m`, `flow_3m`, `flow_ytd`,
`first_valid_flow_date`, `latest_valid_flow_date`, `valid_observations`,
`size_value`, `size_basis="nav_estimate"` and a truthful coverage status.

- [ ] **Step 4: Run focused tests**

Run: `PYTHONPATH=src pytest tests/market_monitor/test_heatmaps.py -q`

Expected: all Task 1–2 tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/market_monitor/heatmaps.py tests/market_monitor/test_heatmaps.py
git commit -m "feat(market-monitor): aggregate validated ETF fund flows"
```

---

### Task 3: Artifact datasets and run/freshness contract

**Files:**
- Modify: `apps/asia-markets-dashboard/scripts/build_market_monitor_artifact.py`
- Modify: `src/market_monitor/pipeline.py`
- Test: `tests/market_monitor/test_market_monitor_core.py`
- Test: `tests/market_monitor/test_heatmaps.py`

**Interfaces:**
- Consumes: `build_return_snapshot`, `build_flow_snapshot`, full-run ETF prices and activity.
- Produces `build_heatmap_health(expected: int, observed: int, latest_date: str | None) -> dict[str, Any]` and artifact datasets `etf_heatmap_returns`, `etf_heatmap_flows`, and `heatmap_etf_price_daily`.

- [ ] **Step 1: Write failing artifact-contract tests**

```python
def test_market_artifact_includes_heatmap_datasets():
    artifact, _labels = builder.build_artifact()
    datasets = artifact["snapshot"]["datasets"]
    assert {"etf_heatmap_returns", "etf_heatmap_flows", "heatmap_etf_price_daily"} <= datasets.keys()

def test_optional_flow_run_cannot_make_core_artifact_healthy():
    status = build_heatmap_health(expected=3, observed=1, latest_date="2026-09-14")
    assert status["status"] == "Degraded"
    assert status["coverage"] == "1/3"
```

- [ ] **Step 2: Run focused tests and confirm failure**

Run: `PYTHONPATH=src pytest tests/market_monitor/test_market_monitor_core.py tests/market_monitor/test_heatmaps.py -q`

Expected: assertions fail because the new artifact datasets are absent.

- [ ] **Step 3: Fetch and persist the heat-map ETF price universe**

Use `fetch_us_etf_history(period="2y", tickers=[...])` in the market-monitor
pipeline. Persist the full response under normalized dataset
`heatmap_etf_price_daily` with the pipeline's existing `run_id`. Treat it as
optional: source failure records degraded health but never replaces a
non-empty retained history with an empty snapshot.

- [ ] **Step 4: Build additive artifact datasets**

Load one full coherent run for price/activity data. Derive and publish the
return and flow snapshots. Include bilingual category labels and source
health with expected/observed counts, latest source observation and
retrieval time. Do not add a Cloudflare block or route.

- [ ] **Step 5: Rebuild both artifacts and run tests**

Run:

```bash
PYTHONPATH=src pytest tests/market_monitor/test_market_monitor_core.py tests/market_monitor/test_heatmaps.py -q
python apps/asia-markets-dashboard/scripts/build_market_monitor_artifact.py --output apps/asia-markets-dashboard/.generated/market-monitor-artifact.json
python apps/asia-markets-dashboard/scripts/build_market_monitor_artifact.py --output apps/asia-markets-dashboard/.generated/market-monitor-artifact-zh.json
```

Expected: tests pass and both artifacts contain all three new dataset IDs.

- [ ] **Step 6: Commit Task 3**

```bash
git add src/market_monitor/pipeline.py apps/asia-markets-dashboard/scripts/build_market_monitor_artifact.py tests/market_monitor/test_market_monitor_core.py tests/market_monitor/test_heatmaps.py apps/asia-markets-dashboard/.generated/market-monitor-artifact.json apps/asia-markets-dashboard/.generated/market-monitor-artifact-zh.json
git commit -m "feat(market-monitor): publish ETF heat-map datasets"
```

---

### Task 4: Streamlit Heat Maps page

**Files:**
- Create: `apps/asia-markets-streamlit/am/heatmaps.py`
- Modify: `apps/asia-markets-streamlit/am/page_registry.py`
- Modify: `apps/asia-markets-streamlit/am/sidebar.py`
- Test: `tests/test_asia_markets_streamlit_pages.py`
- Create: `tests/test_asia_markets_streamlit_heatmaps.py`

**Interfaces:**
- Consumes artifact datasets from Task 3.
- Produces `render_heatmaps(artifact: dict[str, Any], labels: dict[str, Any], language: str, window: str) -> None`.

- [ ] **Step 1: Write failing page and rendering tests**

```python
def test_heatmaps_is_a_lazy_market_page():
    definition = DEFINITION_BY_KEY["heatmaps"]
    assert definition.group == "markets"
    assert definition.url_path == "heat-maps"
    assert definition.renderer == "am.heatmaps:render_heatmaps"

def test_heatmaps_complete_artifact_renders_three_tabs():
    app = AppTest.from_function(lambda: render_heatmaps(_artifact(), {}, "zh", "1 year"))
    app.run(timeout=20)
    assert not app.exception
    assert len(app.get("plotly_chart")) >= 4
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `PYTHONPATH=src pytest tests/test_asia_markets_streamlit_pages.py tests/test_asia_markets_streamlit_heatmaps.py -q`

Expected: the new page definition and renderer are absent.

- [ ] **Step 3: Register the lazy page**

Add:

```python
PageDefinition(
    "heatmaps", "markets", "Heat Maps", "热力图", "heat-maps", "🟩",
    sector_key="market", renderer="am.heatmaps:render_heatmaps",
)
```

Place it beside ETF Monitor and Market Regime. The sidebar must reference it
exactly once.

- [ ] **Step 4: Implement market-performance and flow treemaps**

Create Plotly treemaps with category parent nodes. Controls select the return
or flow window and category population. Size uses `size_value` only when its
basis is disclosed; otherwise a constant equal-area field. Color uses a
zero-centered red/neutral/green scale. Custom data drives bilingual tooltips
and preserves nulls.

- [ ] **Step 5: Implement ETF detail**

Add category/ticker/window selectors. Build one two-row Plotly figure using
`make_subplots(shared_xaxes=True)`:

```python
fig.add_trace(go.Scatter(name="Close", ...), row=1, col=1)
fig.add_trace(go.Scatter(name="SMA20", ...), row=1, col=1)
fig.add_trace(go.Scatter(name="SMA50", ...), row=1, col=1)
fig.add_trace(go.Scatter(name="SMA200", ...), row=1, col=1)
fig.add_trace(go.Bar(name="Estimated flow", ...), row=2, col=1)
```

When flow is absent, render the price panel and an explanatory coverage
message instead of an empty second chart.

- [ ] **Step 6: Run Streamlit tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_asia_markets_streamlit_pages.py tests/test_asia_markets_streamlit_heatmaps.py tests/test_asia_markets_streamlit_contracts.py -q
python -m py_compile apps/asia-markets-streamlit/app.py apps/asia-markets-streamlit/am/heatmaps.py
```

Expected: all tests and compilation pass.

- [ ] **Step 7: Commit Task 4**

```bash
git add apps/asia-markets-streamlit/am/heatmaps.py apps/asia-markets-streamlit/am/page_registry.py apps/asia-markets-streamlit/am/sidebar.py tests/test_asia_markets_streamlit_pages.py tests/test_asia_markets_streamlit_heatmaps.py
git commit -m "feat(asia-streamlit): add ETF heat maps page"
```

---

### Task 5: Optional local US ETF post-close sampler

**Files:**
- Create: `src/market_monitor/sources/us_etf_snapshot.py`
- Create: `src/market_monitor/us_flow.py`
- Modify: `src/market_monitor/cli.py`
- Modify: `src/market_monitor/pipeline.py`
- Test: `tests/market_monitor/test_us_flow.py`

**Interfaces:**
- Consumes: `HEATMAP_ETFS`, a co-timed quote frame and the last normalized proxy observation.
- Produces: `fetch_us_etf_size_snapshot(tickers: Sequence[str]) -> pd.DataFrame`; `build_us_proxy_flow(current: pd.DataFrame, previous: pd.DataFrame | None) -> pd.DataFrame`; CLI flag `--sample-us-etf-flow`.

- [ ] **Step 1: Write failing sampler tests**

```python
def test_us_proxy_flow_requires_two_observations():
    row = build_us_proxy_flow(_snapshot("2026-09-15", 100.0, 1_000.0), None).iloc[0]
    assert row["shares_basis"] == "market_cap_proxy"
    assert row["flow_status"] == "insufficient_history"
    assert pd.isna(row["estimated_flow"])

def test_us_proxy_flow_uses_same_moment_market_cap_and_price():
    previous = _snapshot("2026-09-14", 100.0, 1_000.0)
    current = _snapshot("2026-09-15", 110.0, 1_210.0)
    row = build_us_proxy_flow(current, previous).iloc[0]
    assert row["shares_outstanding"] == pytest.approx(11.0)
    assert row["shares_change"] == pytest.approx(1.0)
    assert row["estimated_flow"] == pytest.approx(110.0)
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `PYTHONPATH=src pytest tests/market_monitor/test_us_flow.py -q`

Expected: modules and functions are absent.

- [ ] **Step 3: Implement a fail-closed quote sampler**

Fetch `last_price` and `market_cap` for each explicit ticker through
`yfinance.Ticker(ticker).fast_info`. Record one row only when both values are
finite and positive and the session date is available. Stamp
`source="Yahoo Finance fast_info"`, `retrieved_at_utc`, and the provider
observation date. A partial response records requested and missing tickers in
frame attributes.

- [ ] **Step 4: Implement proxy-flow derivation**

Calculate shares as `market_cap / price`; compare only consecutive rows for
the same ticker with increasing observation dates. Emit
`shares_basis="market_cap_proxy"`, `size_basis="market_cap_proxy"` and
`flow_status` of `validated_proxy`, `insufficient_history` or `unavailable`.
Reject repeated dates, stale dates, non-positive values and missing prior
observations.

- [ ] **Step 5: Add an explicit local CLI path**

Add `--sample-us-etf-flow` to run the sampler, merge it additively with
retained normalized history and rebuild the market artifact. This path is
optional and non-blocking for the ordinary daily market-monitor run. It does
not send email.

- [ ] **Step 6: Run sampler tests**

Run: `PYTHONPATH=src pytest tests/market_monitor/test_us_flow.py tests/market_monitor/test_heatmaps.py -q`

Expected: all tests pass without network access.

- [ ] **Step 7: Create the local post-close schedule**

Create a Codex local cron automation named `Asia Markets US ETF close sampler`
for 06:30 Asia/Taipei every Monday through Friday. The saved task must:

1. run in an isolated worktree for this project;
2. execute only `PYTHONPATH=src python -m market_monitor.cli --sample-us-etf-flow`;
3. rebuild the English and Chinese market-monitor artifacts;
4. run the focused heat-map and US-flow tests;
5. stage only the US flow normalized/derived snapshots and two artifacts;
6. commit and push only when a new valid session observation exists;
7. report a failure or a material coverage change, and stay quiet when there
   is no new market session.

- [ ] **Step 8: Commit Task 5**

```bash
git add src/market_monitor/sources/us_etf_snapshot.py src/market_monitor/us_flow.py src/market_monitor/cli.py src/market_monitor/pipeline.py tests/market_monitor/test_us_flow.py
git commit -m "feat(market-monitor): sample US ETF flow proxies"
```

---

### Task 6: Documentation and end-to-end verification

**Files:**
- Modify: `docs/asia-markets/MARKET_MONITOR_STREAMLIT.md`
- Modify: `docs/asia-markets/PROJECT_STATUS.md`
- Modify: `docs/asia-markets/DATA_CATALOG.md`
- Modify: `apps/asia-markets-dashboard/.generated/market-monitor-artifact.json`
- Modify: `apps/asia-markets-dashboard/.generated/market-monitor-artifact-zh.json`

**Interfaces:**
- Consumes all Task 1–5 outputs.
- Produces the documented, tested V1 feature and a local preview.

- [ ] **Step 1: Update canonical documentation**

Document the Heat Maps page, five category groups, return windows, China
validated-flow method, US proxy-flow method, start-date limitation, local-only
sampling cadence and Streamlit-only boundary.

- [ ] **Step 2: Run the complete relevant test suite**

Run:

```bash
PYTHONPATH=src pytest tests/market_monitor -q
PYTHONPATH=src pytest tests/test_asia_markets_streamlit_pages.py tests/test_asia_markets_streamlit_heatmaps.py tests/test_asia_markets_streamlit_contracts.py tests/test_asia_markets_wiring.py tests/test_dashboard_history_policy.py -q
python -m py_compile apps/asia-markets-streamlit/app.py apps/asia-markets-streamlit/am/*.py apps/asia-markets-dashboard/scripts/build_market_monitor_artifact.py
git diff --check
```

Expected: all tests, compilation and whitespace checks pass.

- [ ] **Step 3: Rebuild and inspect artifacts**

Build both languages and assert:

```python
for path in (en_path, zh_path):
    artifact = json.loads(path.read_text())
    datasets = artifact["snapshot"]["datasets"]
    assert len(datasets["etf_heatmap_returns"]) > 0
    assert "etf_heatmap_flows" in datasets
    assert "heatmap_etf_price_daily" in datasets
```

- [ ] **Step 4: Run a real browser check**

Start Streamlit on an available port, open `/heat-maps`, and verify:

- desktop and 390px views have no page-level overflow;
- all three subtabs render;
- period and category controls update the intended charts;
- tooltips disclose size/flow basis;
- ETF detail price and flow timelines align;
- English and Chinese labels do not leak across language modes;
- browser console contains no errors or warnings.

- [ ] **Step 5: Commit Task 6**

```bash
git add docs/asia-markets/MARKET_MONITOR_STREAMLIT.md docs/asia-markets/PROJECT_STATUS.md docs/asia-markets/DATA_CATALOG.md apps/asia-markets-dashboard/.generated/market-monitor-artifact.json apps/asia-markets-dashboard/.generated/market-monitor-artifact-zh.json
git commit -m "docs(asia-markets): document ETF heat maps workflow"
```

- [ ] **Step 6: Review branch scope**

Run:

```bash
git status --short
git diff --stat 62d30d2e..HEAD
git log --oneline --decorate 62d30d2e..HEAD
```

Expected: only the design, plan and ETF heat-map implementation are committed;
the unrelated stablecoin files remain outside these commits.
