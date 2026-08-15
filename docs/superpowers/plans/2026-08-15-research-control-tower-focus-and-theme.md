# Research Control Tower Focus Universe and Theme Plan

**Date:** 2026-08-15
**Last updated:** 2026-08-16
**Status:** Stage 1 focus/archive and explicit theme implemented; Stage 1.5
focus and an archived-universe selector remain pending. The next locked scope
is data-coverage Batches 0–4; Stage 1.5 and any wider universe expansion are
blocked until that gate is complete.
**Repository:** `alternative-data`
**Parent scope:** Research Control Tower + investment-thesis workflow

## Objective

Reduce the Research Control Tower's active research surface from the current
60+ ticker universe to a deliberately small, reviewable focus universe, while
preserving archived entities and historical registry lineage. At the same time,
replace the current mixed light/dark presentation with one explicit app theme:
light by default, with an in-app dark-mode choice.

This slice is about research focus and usability. It does not add PIT signal
research, portfolio construction, systematic backtesting or automated trading;
those remain in `quantamental-lab`.

## Data-coverage sequencing gate

The current Stage 1 universe is intentionally small: five public companies
with seven active listings, plus private ByteDance for competitor research.
The next work is to make this six-entity workflow useful before adding Stage
1.5 or restoring more stocks. Do not expand the operational universe until
Batches 0–4 below have passed their acceptance checks.

This is a Control Tower/investment-thesis data layer. It is not a commitment to
build a systematic trading or PIT backtest data stack in this repository.

### Coverage state semantics

The UI and artifacts must distinguish these states rather than collapsing them
into one `unavailable` label:

| State | Meaning | Example |
|---|---|---|
| `available` | Valid rows passed schema, identity and freshness checks | A recent quote for an active HK listing |
| `partial` | The source covers only some listings, periods or geographies | SEC filings for a subset of entities |
| `stale` | Rows exist but are outside the source-specific freshness window | Last quote is older than the quote SLA |
| `not_applicable` | The data concept does not apply to this entity | ByteDance public-market quote or analyst consensus |
| `no_records` | The source was queried successfully but returned no matching rows | No filing in the requested window |
| `unavailable` | The artifact/provider is not connected or the request failed | No consensus export has been configured |

### Locked implementation batches

| Batch | Scope | Shared/primary sources | First deliverable |
|---|---|---|---|
| 0 | Coverage semantics, source health and identity/linkage QA | Existing registry, manifest and source-health contracts | Honest per-entity/per-source status matrix |
| 1 | Latest quote snapshots, then daily market bars | Existing yfinance collector first; Massive/Polygon or Twelve Data only after entitlement probe | Price, change, timestamp and freshness on Company/Today |
| 2 | Official filings and earnings calendar metadata | SEC, HKEX, issuer IR and native exchange/company calendars | Filing/event rows linked to entity and listing |
| 3 | Earnings actuals and financial history | Derive from the Batch 2 official filing layer; SEC XBRL where available | Revenue, EPS, profit and reporting-period history |
| 4 | Macro calendar and macro observations | FRED/ALFRED, BLS, BEA, Fed, ECB, NBS China and other native official calendars | Upcoming macro events plus actual/release/vintage metadata |
| 5 | News metadata | Official sources first; Finnhub/Marketaux/Alpha Vantage/FMP as secondary discovery candidates | Source-quality-labelled company/industry updates |
| 6 | Consensus snapshots | Provider adapters such as Finnhub/FMP/Alpha Vantage only after free-entitlement probes | Current estimates with provider/as-of/source fields |
| 7 | Consensus revisions | Scheduled immutable snapshots of Batch 6 providers | Revision history; never reconstructed from current estimates |
| 8 | Alternative-data signals and thesis checkpoints | Existing internal datasets and source-specific pipelines | Investment-thesis evidence, not automatic trade signals |

### Batch 0 — coverage and linkage foundation

- [ ] Add explicit `available`, `partial`, `stale`, `not_applicable`,
  `no_records` and `unavailable` display semantics to source health and the
  Company/Data coverage components.
- [ ] Produce a coverage matrix for the six Stage 1 entities and seven active
  listings. A private entity must not create a fake listing row just to make a
  table complete.
- [ ] Validate that every quote, filing, earnings, consensus and macro row has
  the correct source-native time, `retrieved_at_utc`, identity relation and
  source/license/PIT label where applicable.
- [ ] Keep provider errors and missing entitlements visible; do not convert an
  empty response into successful coverage.

### Batch 1 — market snapshot first

The first user-visible data batch should fill the existing `quote_snapshots`
contract before introducing a larger market-bars mart.

- [ ] Run the existing free/delayed yfinance collector for active public Stage
  1 listings and publish a manifest-bound quote snapshot artifact.
- [ ] Label yfinance output as delayed and preserve quote time, retrieval time,
  market status, provider symbol and source URL. Do not call it real-time.
- [ ] Show latest price, day change, quote age/freshness and source status on
  the Company and Today pages.
- [ ] Add daily OHLCV/history only after the snapshot path is stable. Keep
  adjusted/unadjusted, exchange timezone and corporate-action treatment
  explicit.
- [ ] Probe Massive/Polygon and Twelve Data only as optional alternatives for
  US coverage; their free plans, exchange entitlements, rate limits and display
  terms must be recorded before adoption.
- [ ] Render ByteDance's market-data state as `not_applicable`, not as a failed
  quote request.

### Batch 2 — official filings and earnings calendar

Filings are the authoritative company-event layer and should precede both
earnings actuals and broad news ingestion.

- [ ] Build metadata-only adapters for SEC, HKEX and issuer IR/exchange sources
  relevant to the Stage 1 public listings.
- [ ] Capture headline/document type, issuer/listing, publication and accepted
  times when available, reporting period, source URL, source quality, content
  hash if permitted and retrieval time. Do not store document bodies in the
  portable Control Tower bundle.
- [ ] Derive next/previous earnings event metadata from official calendars or
  filings, with an explicit `date_precision` and source-native timezone.
- [ ] Add official company/competitor update metadata for ByteDance only where
  the source is public and legally reusable; do not treat it as a listed issuer.
- [ ] Make `Official filings and news metadata` distinguish no records from an
  unconnected provider.

### Batch 3 — earnings actuals

This batch reuses the official filing layer rather than treating an aggregator
as the accounting source of truth.

- [ ] Add an `earnings_actuals` artifact or an explicitly versioned extension
  to the financial mart with revenue, EPS, operating income, net income,
  period, currency, accounting basis, filing/publication time and source link.
- [ ] Preserve reported values separately from normalized values and flag
  restatements/revisions rather than overwriting the original observation.
- [ ] Start with the five public Stage 1 companies; ByteDance is `partial` or
  `not_applicable` unless a public company disclosure supplies the value.
- [ ] Show earnings history and latest reporting period on the Company page,
  including the source and coverage caveat.

### Batch 4 — macro calendar and observations

Macro is a shared Control Tower layer and can be implemented independently of
the company universe, but it must retain release-time and vintage semantics.

- [ ] Add release-calendar rows for US CPI/PPI/payrolls/unemployment/GDP,
  Fed decisions, China/HK releases and relevant ECB events.
- [ ] Prefer FRED/ALFRED, BLS, BEA, Federal Reserve, ECB, NBS China and other
  native official sources. Use third-party calendars only as discovery or
  cross-checks.
- [ ] Store release time, reference period, actual/previous/consensus/nowcast
  fields only when each field has a clearly identified source, plus vintage,
  retrieval and provisional/revised labels.
- [ ] Populate the macro timeline and source-health panel without implying
  that a current value was known historically.

### Free-source evaluation rules for Batches 0–4 and later

The working reference is `/tmp/free-data-control-tower-deep-research.md`,
especially its third-party API audit and free-data source hierarchy. It is a
research input, not a deployment dependency. Candidate services must be
probed and recorded before they become a source of truth:

| Source/candidate | Planned role | Default decision |
|---|---|---|
| SEC / HKEX / issuer IR | Filings, official events, earnings actuals | Primary source |
| FRED/ALFRED, BLS, BEA, Fed, ECB, NBS China | Macro observations and release calendars | Primary source |
| yfinance | Delayed quote/snapshot and discovery | Free fallback; not canonical PIT or real-time |
| Finnhub | US news and near-term earnings-calendar/estimate probe | Secondary; verify free entitlement and geography |
| Alpha Vantage / FMP | Low-frequency news/earnings/estimate probe | Secondary; respect daily limits and licensing |
| Massive/Polygon / Twelve Data | US quote/market-data alternatives | Entitlement probe before use |
| AkShare | Regional discovery/snapshot fallback | Source-specific QA; not uniform PIT contract |
| Futu/OpenAPI / IBKR | Account-entitled quote/depth/market data | Optional personal-account adapter, not free baseline |

For every candidate, record endpoint, fields, geography, cadence, historical
depth, rate limit, entitlement, source/license class, PIT status, source-native
timestamp and failure mode. “Free API key exists” is not enough to qualify a
source for the dashboard or redistribution.

### Stage 1 completion gate before Stage 1.5

- [ ] Batches 0–4 are complete for the Stage 1 public listings or explicitly
  labelled `partial`/`not_applicable` per entity.
- [ ] Price, official filings, earnings actuals and macro calendar no longer
  appear as a global false `unavailable` state when valid data exists.
- [ ] Company pages show price, filings/calendar and earnings history with
  source, timestamp and freshness/caveat fields.
- [ ] Hosted and local bundles pass schema, privacy, no-network and startup
  checks after each batch.
- [ ] Only after this gate: activate Stage 1.5 Cathay/MTR/SHKP/Midland, then
  consider additional stock universes.

## Target universe

### Stage 1 — China Internet / Big Tech

Create the operational focus basket:

```text
RESEARCH_STAGE_1_CHINA_INTERNET
```

Members:

| Entity | Expected market identity | Research role |
|---|---|---|
| Alibaba | 9988.HK / BABA | Core listed company |
| Tencent | 0700.HK | Core listed company |
| ByteDance | Private; no listing | Competitor analysis / watch-only |
| Baidu | 9888.HK / BIDU | Core listed company |
| Kuaishou | 1024.HK | Core listed company |
| Bilibili | 9626.HK; ADR only if independently verified | Core listed company |

ByteDance must be represented as a real research entity without an invented
ticker. Its page may contain competitor, product, AI, advertising and industry
evidence, but it must not enter price, consensus or technical-data collection.

### Stage 1.5 — Hong Kong alternative-data ready

Create the operational focus basket:

```text
RESEARCH_STAGE_1_5_HK_ALT_DATA
```

Members:

| Entity | Expected HKEX identity | Existing research advantage |
|---|---|---|
| Cathay Pacific | 0293.HK | Airline/traffic and operating alternative data |
| MTR Corporation | 0066.HK | Existing Hong Kong transport data |
| Sun Hung Kai Properties | 0016.HK | Existing Hong Kong real-estate data |
| Midland Holdings | 1200.HK | Existing Hong Kong property/transaction data |

The Stage 1.5 slice should initially wire identity and source-availability
metadata. It must reuse the existing alternative-data pipelines rather than
create duplicate collectors.

## Archive contract

“Archive” means remove an entity from the default research universe, not delete
it from the registry or erase historical evidence.

### Registry semantics

- Keep the existing `active_from` / `active_to` interval history.
- Add `entity_type` to the entity contract with at least `public` and `private`.
- Set the five new entities to `public` except ByteDance, which is `private`.
- Use `active_status=archived` for current entities outside the ten-member focus
  set, with an archive effective date of `2026-08-15`.
- Set archived listings to `listing_status=archived`; preserve their interval
  rows so historical and future thesis/event references remain auditable.
- Preserve membership and event-link rows and their interval semantics. Archive
  status plus focus selection controls visibility; do not invalidate lineage by
  date-ending rows merely to hide them from the default view.
- Do not change `collection_eligible` to mean research focus. Eligibility still
  describes whether a mapped listing can be collected; focus filtering happens
  in the Control Tower universe selection and collection entry points.
- Preserve the existing AI Bottlenecks, value, growth and Hong Kong baskets as
  legacy/recoverable research universes. They are not deleted merely because
  they are not the current focus.

### Default visibility

- Default dashboard focus: Stage 1.
- A single focus control switches between Stage 1, Stage 1.5 and both stages.
- Archived/legacy universes are hidden by default.
- A deliberate `Show archived` choice exposes archived entities and legacy
  baskets without making them part of the default daily review.
- Unknown or private entities must never be converted into fake listings to
  satisfy a UI selector.

## UI/theme design

### Root cause to remove

The current app has a light Streamlit canvas but a custom `prefers-color-scheme`
override that can turn the flight deck and custom cards dark when the browser or
OS is dark. `.streamlit/config.toml` also contains unsupported nested theme
sections. These two independent theme systems create the black/white seam seen
in the hosted screenshot.

### Explicit theme model

- Keep the Streamlit base theme light.
- Remove unsupported `[theme.light]` and `[theme.dark]` blocks from
  `.streamlit/config.toml`.
- Remove the OS-level `@media (prefers-color-scheme: dark)` override from the
  custom CSS.
- Add `ct_theme` to session state with `light` as the default.
- Add a visible sidebar theme choice: `Light` / `Dark`.
- Inject one token palette per rerun and scope all custom surfaces to that
  palette. No component may hard-code a dark background in the light palette.
- The light palette must cover the page canvas, flight deck slots, panels,
  event rows, alerts, borders, badges and muted text.
- The dark palette must provide its own contrast-safe text and status colors;
  it must not be derived from the user's OS setting.

### Focus-first information hierarchy

Move the active universe choice out of the collapsed general filter area and
make it a top-level control visible on every page:

```text
Focus universe
[Stage 1 · China Internet] [Stage 1.5 · HK Alt Data] [Both] [Archived]
```

The flight deck should report the selected focus label and covered entity count,
not default to “All baskets” when the app is intentionally scoped to ten names.
The Company selector should show display name, listing and private/listed state
without exposing internal entity IDs as the primary label.

## Implementation tasks

### Task 1 — Extend and validate the focused registry

- [ ] Add `entity_type` to the entity CSV contract, artifact schema and registry
  validation.
- [ ] Permit an active `private` entity without a listing, while retaining the
  existing requirement that public active entities resolve to a primary listing.
- [ ] Add the two focus baskets and the five missing entities, plus verified
  listings where applicable, required by the target universe.
- [ ] Verify Bilibili, Cathay, SHKP and Midland identifiers against the existing
  financial-data crosswalk before marking them collection-eligible.
- [ ] Archive every existing entity outside the ten-member focus set using the
  archive contract; retain all rows and historical dates.
- [ ] Preserve archived membership/event-link lineage while keeping it out of
  the default Stage 1 view.
- [ ] Keep ByteDance watch-only and non-collectible.

Likely files:

```text
config/research_control_tower/entities.csv
config/research_control_tower/listings.csv
config/research_control_tower/baskets.csv
config/research_control_tower/basket_memberships.csv
src/research_control_tower/contracts.py
src/research_control_tower/registries.py
src/research_control_tower/build.py
src/research_control_tower/quote_collector.py
scripts/research_control_tower_quote_collector.py
```

### Task 2 — Make focus and archive state visible in the read model

- [ ] Preserve the new entity/listing fields in Parquet output and repository
  loading.
- [ ] Add a typed focus selection model rather than passing ad-hoc ticker lists
  between pages.
- [ ] Filter default Company/Today/Timeline/AI views to the selected focus.
- [ ] Add an explicit archived view; do not silently mix archived rows into
  active counts or catalyst breadth.
- [ ] Make private entities render a clear “private / no listing” state.

Likely files:

```text
apps/research-control-tower/control_tower/config.py
apps/research-control-tower/control_tower/models.py
apps/research-control-tower/control_tower/repository.py
apps/research-control-tower/control_tower/filters.py
apps/research-control-tower/control_tower/pages/company.py
apps/research-control-tower/control_tower/components/flight_deck.py
apps/research-control-tower/app.py
```

### Task 3 — Replace the mixed theme with explicit light/dark tokens

- [ ] Clean `.streamlit/config.toml` to one valid light base theme.
- [ ] Remove OS/browser media-query theme overrides.
- [ ] Add session-state theme control with light default.
- [ ] Refactor CSS tokens so flight deck, panels, alerts and native page canvas
  do not form separate visual islands.
- [ ] Check both themes at desktop and mobile widths.

Likely files:

```text
.streamlit/config.toml
apps/research-control-tower/app.py
apps/research-control-tower/control_tower/components/__init__.py
```

### Task 4 — Add regression tests and rendered QA

- [ ] Registry tests cover the two focus baskets, all ten target entities,
  private ByteDance, archived rows and preserved interval/linkage lineage.
- [ ] Repository/build tests cover the new `entity_type` and archive fields.
- [ ] AppTest confirms Stage 1 is the default focus, Stage 1.5 shows exactly
  four companies, archived rows are hidden by default and recoverable through
  the archive choice.
- [ ] AppTest confirms light is the default and switching to dark does not
  raise an exception or expose raw IDs.
- [ ] Browser QA confirms no dark custom card appears on the light canvas and
  no light card appears on the dark canvas.
- [ ] Run the existing focused Control Tower suite and the privacy/no-network
  tests.

### Task 5 — Rebuild the publication and review the hosted result

- [ ] Build a fresh manifest after the archive/focus changes.
- [ ] Confirm the default bundle is explicitly scoped to Stage 1 and reports
  unavailable data instead of fabricating consensus/price coverage.
- [ ] Run the privacy and source-health checks on the new bundle.
- [ ] Review the Streamlit Cloud deployment after `main` rebuilds.

## Acceptance criteria

The plan is complete when:

1. The default app surfaces six Stage 1 entities, not the full 60+ universe.
2. Stage 1.5 surfaces exactly Cathay, MTR, SHKP and Midland.
3. ByteDance is visible for competitor research without a fake ticker or
   market-data row.
4. All other current entities remain recoverable as archived records.
5. Archived entities do not inflate active universe counts, catalysts or source
   coverage.
6. Light mode is the default and has one consistent light surface palette.
7. Dark mode is an explicit user choice and has one consistent dark surface
   palette.
8. Existing events, source-health caveats and unavailable consensus/price
   states remain evidence-first and are not silently upgraded.
9. The app remains read-only during navigation and does not add a collector or
   a quantamental-lab runtime dependency.

## Explicit non-goals

- No deletion of legacy entities, listings or historical evidence.
- No automatic ranking of the ten names into buy/sell recommendations.
- No PIT signal backtesting, portfolio construction, execution or systematic
  trading logic.
- No new paid data-provider integration in this slice.
- No broad expansion of the universe until the ten-name workflow is usable.

## Review gate

This document is the implementation plan only. Before code changes begin,
review the archive semantics, the private ByteDance model and the exact ten-name
focus scope. Any change to those decisions should be made here first rather
than encoded as an untracked UI shortcut.
