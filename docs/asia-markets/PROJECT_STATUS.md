# Asia Markets Project Status

This file is a short, human-maintained handoff for the next agent. It is not a
replacement for the operating manual or generated source-status JSON.

## Current state

- Production surface: Cloudflare Pages, non-Streamlit dashboard.
- Private research surface: `apps/asia-markets-streamlit/app.py`; V1 currently
  connects only Hong Kong labour-market/talent-policy and population/migration
  artifacts.
- Canonical financial-data sibling: `/Users/henrywzh/Desktop/Quant/financial-data`;
  see `REPO_BRIDGE.md` for the shared contract.
- Live sector roster: 10 sectors; see `apps/asia-markets-dashboard/sectors.json`.
- English and Chinese hub/data-status pages are published.
- Sector artifacts are generated as portable HTML from `.generated/*.json`.
- `STREAMLIT_PARITY_PROTOCOL.md` is the shared Cloudflare-to-Streamlit
  decision guide. The non-blocking GitHub Action
  `.github/workflows/streamlit-parity-reminder.yml` compares structural
  artifact changes and reminds agents when a Streamlit review is needed;
  value-only refreshes are intentionally ignored.
- The dashboard has explicit month/year chart ticks and visible copy-title
  controls in the current packaging path.
- The project contains both historical time series and current snapshots. Do
  not treat every non-empty dataset as a trend.

## Recent completed work

- China listed airline monthly operating data is wired into transport: passenger
  traffic, ASK, RPK, load factor and regional split.
- Hong Kong transport now includes TD monthly private-car first-registration
  make/fuel history (with BYD/Tesla/other-EV time series), latest make/model
  detail, and two distinct parking signals: the TD real-time car-park vacancy
  snapshot plus metered/on-street sensor-space occupancy. Group 1 also adds TD
  private-car fleet stock and net first-registration history, MTTD Table 2.3
  passenger journeys, and C&SD E705 boundary movements. Parking histories are
  append-only; the metered occupancy chart is a genuine time series only after
  repeated collector runs, and the dashboard does not infer historical values
  from a current feed.
- Hong Kong utilities now includes DSD daily sewage flow/final-effluent
  laboratory observations and WSD temporary water-suspension event notices.
  The public artifact preserves a treatment-works flow chart, latest lab table
  and current event table; DSD lab fields remain sparse and WSD is explicitly
  modeled as a five-minute event snapshot rather than a consumption series.
- Cloudflare historical charts now use a date-based latest-ten-year display
  policy for the transport service breakdown, utilities gas/temperature views,
  local-consumer weather/immigration/gold/retail/restaurant/oil-price views,
  and stablecoin/crypto histories. The source cadence is retained; feeds with
  less than ten years show all available history and must say so in the chart
  context. Snapshot, ranking and recent-event views remain explicitly outside
  this trend-window rule.
- The refactor exposed genuine source limits: Consumer Council watchlist
  valuation history currently returns only a rolling ~365 days from its
  endpoint, while AFCD category prices remain a run-accumulated snapshot.
  Neither is presented as a fabricated ten-year series.
- Dashboard source-status pages were updated and Chinese labels/caveats were
  localized.
- Hong Kong labour-market and talent-policy data is now a live sector with
  official C&SD labour, earnings, vacancies, wage and policy-flow panels.
- Hong Kong population and migration data is now a live sector with ImmD daily
  traffic, C&SD population/net movement, MPFA departure claims, UGC non-local
  enrolment, Transport Department cross-border traffic and C&SD visitor
  arrivals by region. Stage 1 persists normalized run-scoped Parquet datasets
  and the builder reads those before any bootstrap fetch; per-source status rows
  retain each source's own observation date. The full visitor-arrivals history
  remains in normalized storage, while the portable artifact uses a latest-
  ten-year regional detail window to stay under its per-dataset row limit.
- Streamlit V1 is implemented as a private research terminal. It reads the
  existing labour-market and population/migration artifacts, provides an
  Overview, scrollable sector pages with Plotly charts and Level/MoM/YoY-style
  controls, a read-only Data Explorer and Source Health. It intentionally does
  not connect the other Hong Kong sectors, company explorer or cross-market
  pages yet.
- Store-footprint, Google Trends and other planned integrations remain separate
  until their source history and data flow are validated.
- Real-estate dashboard work includes agency transaction pulse, 28Hse EPI/ERI,
  Land Registry statistics, HKMA mortgage measures, Buildings Department data
  and REIT/property trend series.
- Centaline Tranche 1 ingestion is now implemented as a standalone
  `run-centaline-indices` command. The 2026-07-30 run successfully materialised
  CCI (389 monthly rows), CRI (354 monthly rows), CRI yield (353 monthly rows),
  CSI (1,116 weekly rows) and 33 current CCI/CRI/CSI snapshot rows, each with
  raw JSON lineage. Stage 1 now wires CCI/CRI/CRI yield/CSI into the real-estate
  dashboard's regime and residential rent views; CSI's historical payload
  currently exposes residential price/rent history only, with office/
  industrial/retail values available as snapshots.
- CSI ingestion preserves unique weekly source observations and the artifact
  retains day-precision weekly dates; the portable chart runtime supplies the
  visible year without collapsing observations to a month.
- Midland Tranche 2 ingestion is implemented as a standalone
  `run-midland-monthly` command. The 2026-07-30 run materialised 355 monthly
  `mrIndex` rows with price, transaction-count and first-hand fields, plus
  3,185 long-form `economicIndicators` rows and a persisted
  `midland_field_dictionary`. Monthly, macro and dictionary rows share the
  frozen HTML lineage; Midland macro units remain Midland-derived until the
  planned HKMA/C&SD reconciliation. The routine `run-all` path now includes
  this tranche, while `HK_RE_SKIP_MIDLAND` marks it skipped in blocked CI.
- RVD commercial Tranche 3 is implemented as a standalone
  `run-rvd-commercial` command. The 2026-07-30 run materialised 1,604 office
  rental rows across Grades A/B/C and Overall, plus 802 retail rows covering
  rental and price metrics, preserving official provisional flags and raw CSV
  lineage. Stage 1 now wires the office and retail rental histories into the
  commercial-property dashboard section; retail price and grade-level drilldown
  remain follow-up work.
- Midland Tranche 4 is implemented as a standalone
  `run-midland-snapshots` command. The 2026-07-30 run materialised 598 rows
  from all/region/district current and previous-window market statistics, plus
  32 rows from the current registration summary and 45 Midland
  `propertyEvent` research hints. Market rows preserve units, source fields
  and optional window dates; registration rows preserve as-of/update dates
  and explicit transaction/amount units. These are explicitly as-of snapshots
  or discovery hints, not historical trends or official policy events; at
  least 90 days of dated snapshots are required before any MoM/YoY chart is
  considered. This tranche is also included in routine `run-all` with the
  Midland CI skip guard.
- Tranche 5 policy/event research contracts are implemented through
  `run-policy-events`: four primary-source catalog entries and a validated
  audit of the curated developer/project registry. Both outputs now retain a
  local raw snapshot and explicit lineage type; Midland events remain
  `research_only` until matched to an HKMA, Government, Lands Department or
  HKEX primary source with publication/effective-time semantics.
- The residential-developer SRPE bounded runner is implemented through
  `run-srpe-pilot` with an explicit phase registry, PDF hash reuse, raw PDF and
  manifest lineage, document audit, unit-level transaction/price rows and
  project-month sales signals. The final 2026-08-01 core run produced 2,892
  transaction events, 1,585 price-list unit rows, 196 project-month signals
  and 18/18 successful document audits across six phases. Sell-through uses
  active unit-level dedup while raw contract-event counts remain available;
  this prevents PASP/ASP updates and re-sales from producing a false >100%
  sell-through. The output is now wired into the HK real-estate dashboard as
  four KPI cards, top-three developer/project monthly time series and a
  six-phase latest-project table. The dashboard intentionally keeps broader
  developer/project coverage as catalog-only until the registry and backfill
  boundary is expanded. The optional Crawl4AI browser tool is installed
  outside the project dependency graph for future dynamic issuer pages, not
  for the SRPE API/PDF path.

## Open decisions / known limitations

- The planned Asia finance universe is documented in the sibling repo but is
  not active collection data. Futu (`FUTU`), Tiger (`TIGR`), CITIC Securities
  (`6030.HK`), China Merchants Securities (`6099.HK`), CICC (`3908.HK`), GF
  (`1776.HK`), CSC (`6066.HK`), Guotai Haitong (`2611.HK`) and East Money
  (`300059.SZ`) require a market-aware financial-data expansion before being
  wired into the dashboard.
- Buildings Department Md52–Md56 current XLS charts/tables remain project
  snapshots. A separate archive-backed `bd_supply_pipeline_history` now covers
  2005-01 to 2026-05 as month/stage aggregates parsed from the official PDF
  summary tables. The dashboard chart deliberately displays only the latest
  ten-year lookback (currently 2016-05 to 2026-05) for readability; the
  archive-backed normalized rows remain available for research. `Md52`
  demolition consents supply counts only; the history is not project-level
  stage linkage. `bd_monthly_stats` remains a distinct Md11–Md17 scratch
  dataset with unlabelled numeric arrays.
- The current monthly-digest fetch archives 20 Mdxx XLS files. Most of those
  are raw-only archival coverage, not normalized analytical datasets.
- Buildings Department coverage is split between raw Mdxx archival files,
  historical Section-1 stage aggregates and current Md52–Md56 project
  lifecycle snapshots. The next BD expansion is project-level historical
  extraction/entity resolution, which requires separate validation.
- Source coverage for newer feeds currently uses `Live at build time` when a
  build fetched rows, but often leaves `latest_observation` as `—`. This should
  be improved to expose actual as-of dates and age where possible.
- Population/migration source dates are mixed by design (daily, half-yearly,
  quarterly, academic-year and monthly). The status page shows each source's
  own latest label; the package-wide `data_as_of` is the latest dated source
  observation, not a claim that every source has that recency.
- Weekly/daily chart labels preserve distinct points while showing a year;
  month-granularity series use month/year labels. The portable packaging layer
  patches the shared reader's day-only axis labels in both interactive and
  static delivery modes.
  do not solve this by aggregating the data to monthly grain.
- Most store-footprint companies have only one or two dated snapshots; present
  them as footprint snapshots rather than trends.
- Consumer Council Online Price Watch historical Parquet is gated by a local
  manifest: all advertised archive dates must have source-version provenance,
  a successful parse and a materialised partition before it is Healthy. The
  dashboard shows archive coverage plus a product-code-matched, chain-linked
  index for the six longest supermarket-code series. It does not adjust for
  promotions or pack-size changes, and source-code renames are deliberately
  not inferred as continuity. The archive remains local rather than Git-tracked.

## Agent handoff checklist

Before starting a new task:

1. Read `OPERATING_MANUAL.md` and `DATA_CATALOG.md`.
2. Check `git status --short` for existing work.
3. Identify the sector roster entry, builder, artifact and status file.
4. Decide whether the requested metric is a time series, snapshot, catalog
   record or research-only item.
5. Update this file if the task changes the project state or resolves one of
   the limitations above.
