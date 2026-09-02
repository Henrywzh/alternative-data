# Asia Markets Operating Manual

This is the canonical operating manual for the Asia Markets research and
dashboard project. Read it before changing files under `apps/asia-markets-dashboard/`
or the related `src/hk_*` pipelines.

## 1. Project purpose

Asia Markets is a source-backed Hong Kong-first market-monitoring project. It
combines research notes, normalized data pipelines, published artifacts, a
public static/interactive dashboard hosted on Cloudflare Pages and a private
Streamlit research terminal. The Index & ETF Allocation Monitor is currently
a Streamlit-native research-terminal feature; it is deliberately outside the
Cloudflare public sector roster.

The dashboard is not an investment-advice product. Do not add rankings,
forecasts or recommendations unless the user explicitly asks for a separate
research analysis.

The current production dashboard is:

- English: <https://asia-markets-dashboard.pages.dev/>
- Chinese: <https://asia-markets-dashboard.pages.dev/zh/>
- Data status: <https://asia-markets-dashboard.pages.dev/data-status/>
- Chinese data status: <https://asia-markets-dashboard.pages.dev/zh/data-status/>

The Cloudflare dashboard is the public monitoring surface and remains the
primary published surface unless the user explicitly says otherwise. The
Streamlit app is a separate private research surface for richer interactive
views; it reads the existing generated artifacts and does not replace the
Cloudflare pipeline.

## 2. Read first

At the beginning of a task:

1. Read this manual.
2. Read `PROJECT_STATUS.md` and `DATA_CATALOG.md`.
3. Read `MARKET_MONITOR_STREAMLIT.md` before changing the Index & ETF
   Allocation Monitor, its pipeline, artifact or Streamlit page.
4. Read `STREAMLIT_PARITY_PROTOCOL.md` before changing Cloudflare artifacts,
   dashboard builders, source contracts or sector wiring. The non-blocking
   GitHub Action automatically reminds agents when a structural Cloudflare
   change needs a Streamlit decision; routine value-only refreshes stay quiet.
5. Inspect `apps/asia-markets-dashboard/sectors.json` before changing the
   sector roster.
6. Run `git status --short` and preserve existing user work. Do not reset,
   discard or overwrite unrelated changes.

The repository root `AGENTS.md` and `CLAUDE.md` point here for Codex,
Antigravity and Claude-style agents. This manual is the source of truth;
those files are only entry points and safety notes.

## 2A. Sibling financial-data repository

The canonical financial-data repository is the sibling directory:

```text
/Users/henrywzh/Desktop/Quant/financial-data
```

It owns the point-in-time financial database, currently the 174-security HKEX
universe. Read `REPO_BRIDGE.md` here and
`/Users/henrywzh/Desktop/Quant/financial-data/docs/ASIA_MARKETS_BRIDGE.md`
before changing financial-data joins, ticker universes or dashboard financial
coverage. The current database can be attached directly in SQL; do not create
an untracked duplicate copy.

The planned Asia finance universe includes Futu (`FUTU`), Tiger Brokers
(`TIGR`), CITIC Securities (`6030.HK`), China Merchants Securities
(`6099.HK`), CICC (`3908.HK`), GF Securities (`1776.HK`), CSC Financial
(`6066.HK`), Guotai Haitong (`2611.HK`) and East Money (`300059.SZ`). These
are planning entries, not yet dashboard data. Keep online brokers,
traditional brokers, HKEX infrastructure and wealth/data platforms as separate
categories.

## 3. Dashboard architecture

The production flow is:

```text
source/API/scraper
  -> src/<sector>/ pipeline or existing processed data
  -> apps/asia-markets-dashboard/scripts/build_hk_*_artifact.py
  -> apps/asia-markets-dashboard/.generated/*-artifact.json
  -> scripts/build-static-hub.mjs
  -> scripts/package-dashboard.mjs
  -> apps/asia-markets-dashboard/dist/
  -> Cloudflare Pages
```

The private Streamlit flow is intentionally thinner:

```text
existing .generated/<sector>-artifact.json
  -> apps/asia-markets-streamlit/app.py
  -> Plotly charts, KPI cards, tables and source-health views
```

The current Streamlit app includes the overview, market monitor, labour,
population, transport, real-estate, aerospace, crypto, Data Explorer and
Source Health pages. It must not fetch from external sources during page
navigation or create a second copy of the source pipelines. The Index & ETF
Allocation Monitor is read from `market-monitor-artifact*.json` and is not
added to `sectors.json` or `package-dashboard.mjs` in V1. Company explorer and
broader portfolio workflows remain future scope.

The market-monitor-specific flow is:

```text
src/market_monitor sources
  -> data/normalized/market_monitor + data/derived/market_monitor
  -> apps/asia-markets-dashboard/.generated/market-monitor-artifact*.json
  -> apps/asia-markets-streamlit/app.py
```

This shared artifact is a read contract only. It does not make the monitor a
Cloudflare page or authorize adding it to the public sector roster.

The market monitor has two timing contracts. The daily close workflow persists
completed-session history and builds the artifact. The separate
`.github/workflows/market-monitor-intraday.yml` workflow fetches only the
midday ETF spot snapshot. Both workflows evaluate the same event-driven Gmail
policy: a baseline is sent once, confirmed signal changes trigger an alert, and
Friday sends a weekly no-change heartbeat when the week has been quiet. The
intraday workflow may commit only the tiny
`data/derived/market_monitor/alert_state.json` delivery cursor (including a
bounded event-key dedupe list and retry queue); it must not write quote
snapshots into Git or use a last-close reconstruction as a current quote. A
failed event or weekly heartbeat remains pending for the next healthy run.
Freshness status and observation dates are part of the artifact
contract; a rebuild timestamp is not an observation timestamp. The daily CLI
uses `--require-fresh` for the email and `--allow-stale-artifact` for the
artifact step: unavailable/stale/invalid regional or source data, coverage
regressions and failed fetches block the email but still permit a technical
artifact with an explicit warning. The intraday fetch is intentionally
non-persistent for market data; an empty provider response is `Unavailable`,
while retrieval-only Eastmoney rows are `Unverified` and stay out of
current-cost, alert and peer-ranking decisions.

Important files:

- `apps/asia-markets-dashboard/sectors.json`: single source of truth for live
  and planned sectors.
- `apps/asia-markets-dashboard/scripts/sectors.mjs`: derives artifact, route
  and status paths from the roster.
- `apps/asia-markets-dashboard/scripts/run-artifact-builders.mjs`: runs the
  Python artifact builders.
- `apps/asia-markets-dashboard/scripts/build-static-hub.mjs`: builds the hub
  and data-status pages.
- `apps/asia-markets-dashboard/scripts/package-dashboard.mjs`: packages the
  English and Chinese sector artifacts into portable HTML.
- `apps/asia-markets-dashboard/.generated/`: generated artifacts; inspect them
  for values, row counts, freshness and chart wiring.
- `apps/asia-markets-dashboard/dist/`: generated deploy output; do not hand-edit
  source logic there.

## 4. Current live sectors

The live roster is defined in `sectors.json` and currently includes:

- Hong Kong real estate
- Hong Kong local consumer
- Hong Kong utilities and infrastructure
- Hong Kong transport and aviation
- Hong Kong telecom
- Hong Kong labour market and talent policy
- Hong Kong REITs
- Hong Kong commercial aerospace
- Hong Kong stablecoin and crypto
- Hong Kong population and migration

Planned sectors are intentionally non-clickable research placeholders. Do not
turn a planned theme into a live dashboard merely because a document exists.
Require a real, validated dataset and a working artifact builder.

The Streamlit-only market monitor is a separate product surface and is not a
Cloudflare sector entry.

## 5. Data rules

Every dashboard measure must have:

- a named source and source URL where available;
- an explicit observation date or period when the source provides one;
- a documented cadence: daily, weekly, monthly, quarterly, irregular or
  snapshot;
- a clear unit and definition;
- a caveat when the data is partial, estimated, capped, provisional or only
  available at build time.

Do not infer a trend from a snapshot. A current-month cross-section is not a
monthly time series and cannot support MoM or YoY without historical snapshots.

### Refresh safety and empty snapshots

An upstream fetch returning zero rows is not automatically a valid new
snapshot. The artifact runner compares each refresh with the previous
published artifact and restores the previous artifact/status for any dataset
that was non-empty and becomes empty or disappears; other sectors continue to
refresh. Core real-estate histories such as HKMA mortgage and Buildings Department
pipeline data also use the latest normalized cache, then a committed-artifact
fallback when the clean CI runner has no cache. Fallback data must be marked
`Stale`/`Degraded` rather than presented as a fresh observation. A successful
GitHub Action is therefore not sufficient evidence of fresh data: inspect the
artifact row counts, manifest IDs and source-health status.

Do not silently aggregate data to a month if doing so collapses distinct daily
or weekly observations. Preserve the source grain, then format the axis
separately.

The current source-coverage table is generated at build time. `Live at build
time` / `构建时实时` means the fetch returned usable rows during the build; it
does not mean the published page has a live connection. If a source has an
observation date, prefer exposing that date and a calculated age instead.

## 6. Known data distinctions

### Buildings Department

Do not merge these concepts:

- `Md52`–`Md56`: project-level lifecycle files for demolition consents, Plans
  Approved, Consent to Commence, commencement notices and Occupation Permits.
  Current dashboard aggregation is a latest-snapshot supply pipeline. `Md52`
  records do not publish domestic units or usable floor area, so they must be
  treated as project/consent counts rather than zero-unit projects.
- `bd_monthly_stats`: `Md11`–`Md17` section-1 summary tables. The current parser
  retains historical rows but stores numeric cells as an unlabelled array, so
  the column meaning is not safe for arbitrary MoM/YoY analysis.

The source fetch also archives the current `Md21`–`Md25`, `Md31`, `Md41` and
`Md51`–`Md56` XLS files as raw snapshots. Archival coverage is not equivalent
to a normalized data contract; only `Md11`–`Md17` summaries and `Md52`–`Md56`
project-lifecycle records are currently structured for analysis.

`bd_supply_pipeline_history` is the separate historical contract. It uses one
official December Monthly Digest PDF per archived year (plus the latest direct
PDF for current years) and parses the more stable Section 1 aggregate tables:
Table 1.2 for Md52 demolition consents; 1.4 for Md53 approvals; 1.2/1.5 for
Md54 consent-to-commence counts, units and area; 1.6 for Md55 notification
units and area; and 1.3/1.7 for Md56 permit counts, units and area. It covers
2005-01 through 2026-05 at a stage-month aggregate grain. It does not identify
the same project across stages, infer a regional split, or invent Md52 units
or floor area. Run it explicitly with `run_bd_history_backfill`; routine
pipelines and dashboard builds read the latest normalized result and do not
download the archive.

### Transactions

The agency transaction pulse is intentionally capped for display. A display
cap is not the same as source-history availability. Always distinguish:

- total rows fetched;
- rows retained in the artifact;
- rows displayed in the table/chart.

### Transport parking signals

Keep the two TD parking feeds separate. The 548-car-park vacancy feed is a
current vacancy snapshot with vacancy-type exclusions; it has no historical
capacity denominator. The metered/on-street occupancy feed joins the official
parking-space inventory to live occupied/vacant sensor status and is a
different, sensor-covered sample. It becomes a trend only through repeated
dated collector runs; never present either feed as all-Hong-Kong parking
occupancy.

### Store footprints

Store-footprint data is a snapshot unless enough dated observations exist for a
trend. Most brands currently have only one or two snapshots. Do not label it a
trend prematurely.

### Planned or documentation-only themes

Stablecoin/crypto and commercial aerospace may have live monitoring artifacts,
but documentation-only claims must not be presented as validated live measures.
Consumer Council price-watch, stablecoin/crypto gaps or aerospace gaps remain
planned when the source is unavailable or the dataset is not real.

## 7. Chart and UI rules

- Use a real interactive chart/runtime when the portable renderer supports it;
  do not replace a time series with a screenshot or an unexplained static image.
- Every temporal chart must show month and year in visible ticks. Monthly
  labels should look like `Jan 2024`; daily/weekly charts must retain distinct
  observations while still exposing the year.
- A chart title should be ordinary selectable text and have a visible `Copy
  title` / `复制标题` control when the portable runtime is used.
- Keep source attribution accessible but do not make users go through a chart
  menu just to identify a title or table.
- English and Chinese pages must both be updated. Chinese translation should
  cover dashboard titles, descriptions, table headings, statuses, caveats and
  controlled category labels; proper names and technical acronyms may remain
  untranslated where that improves accuracy.
- Do not hide a caveat that changes how a chart should be interpreted.

## 8. Standard development workflow

For a data or dashboard change:

1. Inspect the source, builder, artifact and status output involved.
2. Make the smallest source-owned change with `apply_patch`.
3. Run focused tests first.
4. Rebuild artifacts with the repository Python runtime when needed:

   ```bash
   cd apps/asia-markets-dashboard
   PYTHON_BIN=/Users/henrywzh/.pyenv/shims/python3 npm run refresh
   ```

5. Build the hub and package the sector pages:

   ```bash
   node scripts/build-static-hub.mjs
   node scripts/package-dashboard.mjs
   ```

6. Spot-check real values and chart/table counts in `.generated/*.json` and
   `dist/`.
7. Run the relevant tests. For dashboard wiring, start with:

   ```bash
   cd /Users/henrywzh/Quant/alternative-data
   pytest -q tests/test_asia_dashboard_artifacts.py tests/test_asia_markets_wiring.py
   ```

8. Use a real browser to check at least one English page, one Chinese page,
   representative long and short charts, mobile layout, visible dates,
   copy-title controls and console errors.
9. Only deploy when the user requests publishing or the task clearly includes
   deployment.

The one-command build is:

```bash
cd apps/asia-markets-dashboard
PYTHON_BIN=/Users/henrywzh/.pyenv/shims/python3 npm run build
```

It may perform network fetches and update generated data. Do not run it merely
to inspect a source file when a focused artifact or test is enough.

For the private Streamlit V1 local app:

```bash
cd /Users/henrywzh/Quant/alternative-data
streamlit run apps/asia-markets-streamlit/app.py
```

This command is for local development or an explicitly requested Streamlit
deployment; it is not part of the Cloudflare build.

## 9. Deployment rules

Before a Cloudflare Pages deploy, verify authentication:

```bash
npx wrangler whoami
```

The production command is:

```bash
npx wrangler pages deploy dist \
  --project-name=asia-markets-dashboard \
  --branch=production \
  --commit-dirty=true
```

After deployment, verify the canonical Pages URL, not only the unique
deployment URL. Check representative English and Chinese routes, chart labels,
copy controls, source tables and browser console logs.

Do not commit or push unless explicitly requested. Never delete `.config`.

## 10. Updating this manual

Update this manual when any of the following changes:

- a sector becomes live or planned;
- a builder, artifact path or deployment command changes;
- a source changes grain, cadence, freshness semantics or coverage;
- a known limitation is fixed or discovered;
- the chart renderer or browser verification rules change.

Update `DATA_CATALOG.md` for source and dataset facts. Update
`PROJECT_STATUS.md` for current work and open decisions. Avoid duplicating
volatile status details throughout the manual.
