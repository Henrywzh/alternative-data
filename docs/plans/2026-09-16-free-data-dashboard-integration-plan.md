# Free Financial Data Integration Plan

## Status

- **Status**: Planning only; no pipeline or dashboard code changes in this plan.
- **Implementation target**: this repository, `/Users/henrywzh/Quant/alternative-data`.
- **Baseline**: `origin/main`.
- **Priority**: Asia Markets first, then Research Control Tower.
- **Deferred**: Alternative Data AI dashboard.

## Revision note (2026-09-16)

The first draft of this plan was written against
`/Users/henrywzh/Desktop/Quant/alternative-data` on branch
`feat/free-institutional-data-lanes`. Three premises in it were wrong, and the
corrections change the design rather than just the wording. They are recorded
here because each one is the reason a rule below reads the way it does.

**1. The target path and the branch.** `CLAUDE.md` records that this repository
deliberately lives outside `~/Desktop/`: iCloud "Desktop & Documents" sync
produced duplicate `<name> 2` files inside `.git/objects`, blocked `git gc`, and
risks rewriting files mid-write. The Desktop checkout has already started
accumulating those duplicates. It is also a stale second clone of the same
remote — 166 commits behind `origin/main` and 0 ahead, with all five of its lane
commits (`b4e4878b` … `fa9ede41`) already ancestors of `origin/main`. Every
`src/*_data` package it introduces is on main. Work here, against `origin/main`.

**2. Phase 0 is mostly already done.** `docs/free-institutional-data-backfill-audit.md`
(2026-09-11) is the source-ownership and coverage audit this plan asked for. It
carries per-lane row counts, per-column fill rates, the six post-backfill
defects, and the storage-layout rationale. Phase 0 below is reduced to the parts
that document does not settle: the *ownership decisions* between overlapping
lanes, and the field-level mapping into the Control Tower contracts.

**3. Scheduled refresh already exists.** The draft did not mention it. Three
workflows drive these lanes, and `config/ops/pipelines.yaml` already carries a
per-output `max_age_days` freshness contract for each:

| Workflow | Cron (UTC) | Lanes | `max_age_days` |
|---|---|---|---|
| `free-institutional-daily.yml` | `10 5 * * *` | hkex, eia, hkma | 7 / 5 / 7 |
| `free-institutional-weekly.yml` | `40 5 * * 1` | factset | 21 |
| `free-institutional-monthly.yml` | `10 6 6 * *` | sp_pmi, bis, msci | 75 / existence-only / — |
| *(none)* | — | cme_voi | HTTP 403; dispatch-only by design |

One claim from the review that produced this revision was itself wrong and is
withdrawn: the `eia_grid_hourly` day-partition layout (2,814 files) is not
small-file sprawl. It is a deliberate fix — as one table it was an 11.5 MB parquet
rewritten whole on every refresh, roughly 4 GB of git history a year. Day
partitions add about 5 KB per day. Leave it alone.

## Objective

Integrate the already researched free institutional and alternative data into
the investment-research stack without creating duplicate collectors, duplicate
normalized tables, or runtime network calls from Streamlit.

The two dashboards should consume the same canonical normalized data while
using different semantic views:

```text
official/public source
    -> existing source package and runner
    -> immutable raw snapshot
    -> data/normalized/<source>/ canonical parquet
    -> Asia Markets artifacts
    -> Research Control Tower immutable generation
```

The existing normalized data and source packages remain the source of truth.
Dashboard adapters may reshape data, calculate compact derived metrics, and
attach provenance, but must not fetch or parse external sources.

## Coverage reality

Nothing below may be designed against row counts. A lane can report thousands of
rows while the fields it was built for are empty, and three of these lanes do.
These figures are measured on `origin/main`, not on the backfill snapshot.

| Lane | Rows | What is actually usable |
|---|---:|---|
| `bis_observations` | 1,241 | 7 series, 1957-Q4 → 2025-Q4. Complete. |
| `hkma_observations` | 63,379 | 14 series, 2002-01-02 → 2026-09-15. Mixed tier: 49,383 `official_api`, 13,990 `aggregator`, 6 `official_document`. |
| `eia_grid_hourly` | 2,549,227 | 5 balancing authorities × 8 fuels, 2019 →. Complete. |
| `msci_rebalance_events` | 71,602 | Dates, `index_name` (120 indices), `country`, `security_name`. **`sedol`, `isin`, `ric`, `ticker` are 0% populated.** 8,888 HK/CN rows. |
| `hkex_market_flow_daily` | 1,816 | Short inventory (`security_count`, `turnover_shares`, `shares_available`) 99.2% from 2019-01-02. Stock Connect aggregate flow **151 rows, 2026-02-16 → 2026-09-15**. Six columns are 0% — see below. |
| `factset_sp500_earnings_regime` | 821 | **596 rows (73%) carry a `report_date` and a `source_url` and no numeric value at all.** |
| `sp_pmi_subindices` | 56 | **One period, `2026-08`.** Headline only; every sub-index is null. |
| `cme_voi` | 0 | HTTP 403. Unavailable. |

### Permanently empty HKEX columns

These exist in the schema and have never held a value, after the daily workflow
has been running:

```text
northbound_buy_turnover_rmb_mln        northbound_sell_turnover_rmb_mln
northbound_net_inflow_rmb_mln          total_market_turnover_hkd_mln
southbound_turnover_share_pct          short_selling_turnover_hkd_mln
short_selling_ratio_pct
```

`short_selling_turnover_rmb_mln` is non-null on 1,799 rows but non-zero on
**one**. The backfill audit already concludes that short *value* is not a usable
turnover measure and that counts and shares are the safer fields. The `rmb`
suffix on an HKEX short-selling turnover series is separately worth checking
before anything renders it.

### The FactSet lane has regressed since the audit

The audit recorded 218 rows on 2026-09-11. `origin/main` now holds 821. The
extra rows are empty, and two fields went *backwards*:

| Field | Audit (218 rows) | Now (821 rows) |
|---|---:|---:|
| `blended_earnings_growth_yoy` | 131 | 132 |
| `eps_beat_rate` | 6 | 101 |
| `revenue_surprise_pct` | 0 | 100 |
| `forward_12m_pe` | **179** | **177** |
| `forward_12m_pe_10y_avg` | **103** | **95** |
| rows with every numeric field null | — | **596** |

The freshness validator cannot see this: `observation_freshness` checks
`report_date`, and all 596 empty rows carry a valid one. The weekly workflow
reports success while publishing nothing. Fixing this is a prerequisite for
routing FactSet anywhere, and it motivates the fill-floor validator in the gates
section.

## Product structure

The current page set on `origin/main` is twelve pages in four groups
(`workspace` 1, `markets` 3, `hong_kong` 6, `data` 2). This plan adds one page
and changes no others. Labour Market, Population & Migration, and Commercial
Aerospace stay exactly as they are; the draft's nine-item structure omitted
them, which would read as deletion to whoever implements it.

```text
Asia Markets
├── workspace   Overview
├── markets     ETF Monitor
├── markets     Heat Maps
├── markets     Market Regime
├── markets     Hong Kong Flows & Liquidity          <- new
├── hong_kong   Labour Market
├── hong_kong   Population & Migration
├── hong_kong   Hong Kong Real Estate
├── hong_kong   Transport & Aviation
├── hong_kong   Commercial Aerospace
├── hong_kong   Stablecoin & Crypto
├── data        Data Explorer
└── data        Source Health
```

The new page is named `Hong Kong Flows & Liquidity`, not "Hong Kong Markets".
The `hong_kong` group already exists and holds six pages; a page whose name
matches its sibling group is ambiguous in the sidebar and in `url_path`. The
page belongs in `markets` beside ETF Monitor and Market Regime, which is what it
is: cross-border flow, funding, and index-event context.

It owns:

- Stock Connect southbound/northbound flow (Eastmoney-owned — see ownership table)
- HKEX short inventory — counts and shares, not value
- HKMA HIBOR, Aggregate Balance, and Hong Kong liquidity indicators
- MSCI index events for HK/CN, as unlinked index events
- Hong Kong-specific data quality and source-health warnings

ETF Monitor may show a small summary or link to this view, but the detailed flow
and short-selling tables have one canonical presentation location.

### `southbound_market_flow` is a migration, not a new feature

`southbound_market_flow` is already a published artifact dataset (2,715 rows)
built at `build_market_monitor_artifact.py:734` and rendered by
`market_page.py:435` inside ETF Monitor. The underlying parquet is gitignored,
so the published artifact is the durable copy of that history. Moving it to a
different artifact file is a contract change and must be staged:

1. Emit the dataset into both `market-monitor-artifact.json` and
   `hong-kong-flows-artifact.json` for one release, under the same key.
2. Move the renderer to the new page, reading the new artifact.
3. Drop it from the market-monitor artifact only after a release in which
   nothing reads it there.

## Source ownership

The draft pre-committed the conclusion of its own audit: *"HKEX should become
the official authority after row-level comparison."* The measurement says the
opposite, and acting on it would trade twelve years of daily flow for seven
months:

```text
Eastmoney  southbound_market_flow    13,565 rows   2014-11-17 -> 2026-09-15
HKEX       southbound_net_inflow        151 rows   2026-02-16 -> 2026-09-15
HKEX       northbound_net_inflow          0 rows
```

HKEX publishes only recent daily statistics through this endpoint; there is no
backfill, and the lane is forward-accumulating from February 2026. Ownership is
therefore decided **per field, not per source**, and the rule is longest honest
coverage:

| Field | Owner | Why | Other lane |
|---|---|---|---|
| Southbound buy/sell/net flow | `eastmoney_hsgt` | 2014 →, 13,565 rows | HKEX labelled `corroborating`, shown only where both exist |
| Northbound net flow | `eastmoney_hsgt` | HKEX column is 0% | HKEX `unavailable` |
| Short inventory: count, shares, shares available | `hkex_market_flow_data` | 99.2% from 2019; official | none |
| Short-selling value / ratio | **neither** | HKEX columns 0% or all-zero | declared `unavailable` |
| Market turnover, southbound turnover share | **neither** | HKEX columns 0% | declared `unavailable` |
| HIBOR, Aggregate Balance, TWI, CU | `hkma_macro_data` | `source_tier` already ranks official over aggregator | HKMA mortgage lane shares infrastructure, not a second fetcher |
| Credit-to-GDP gap | `bis_macro_data` | only source | — |
| Grid generation | `eia_energy_data` | distinct from the EIA benchmark-price lane | shared acquisition/source-health helpers only |
| Index review events | `msci_index_review_data` | only source | — |
| SEC filings | existing canonical EDGAR normalized data | Control Tower receives an adapter | no second SEC collector |

**Invariant.** No source may replace another where the replacement's earliest
observation is later than the incumbent's. This is the same guard added to
`build_market_monitor_artifact.py` after a truncated cache silently erased
17,106 rows of published ETF history, and it applies to source promotion for the
same reason.

Remaining Phase 0 reconciliations, unchanged from the draft: FRED normalized
data versus direct FRED logic inside market-regime builders; EIA grid versus EIA
benchmark price; CFTC, OFR, FRED VIX, and the existing transport/energy lanes.

`financial-data` remains a separate canonical system. Do not attach its DuckDB
at runtime or copy its collectors into this repository.

## Source value and routing

Two rows changed from the draft, because a source with one observation is not a
regime input and a source that is 73% empty is not an earnings input.

| Source | Frequency / coverage | Asia Markets | Control Tower |
|---|---|---|---|
| BIS credit gap | Quarterly; 1957 → | Market Regime | `macro_observations` |
| HKMA HIBOR/liquidity | Daily; official + marked aggregator rows | HK Flows & Liquidity / Real Estate / Regime | `macro_observations`, `source_health` |
| HKEX short inventory | Daily; 2019 → | HK Flows & Liquidity | Source health initially |
| Eastmoney Stock Connect flow | Daily; 2014 → | HK Flows & Liquidity | `macro_observations` |
| S&P PMI | **One period; no backfill available** | **Overview card only**, until ≥12 periods | `events` (release), not `macro_observations` |
| FactSet Earnings Insight | Weekly; **73% empty rows** | **Blocked** until the fill regression is fixed | Blocked |
| MSCI reviews | Monthly/quarterly; no identifiers | HK Flows & Liquidity / ETF Monitor, **unlinked index events** | Index events and timeline |
| EIA grid | Hourly; aggregate to daily | Compact daily energy context | Source Health only in RCT v1 |
| CFTC COT | Weekly; existing collector | Market Regime | Reuse existing normalized lane |
| FRED / OFR / VIX | Existing lanes | Market Regime | Reuse existing normalized lanes |
| CME VOI | 0 rows; HTTP 403 | Unavailable status only | Unavailable status only; **must be registered as a lane to appear at all** |

### Promotion rule

A source earns a page when it passes a stated minimum; until then it renders as
a single card carrying its coverage state. This turns "coverage status visible
for every new source" from a description into a gate.

| Source | Promotion trigger |
|---|---|
| S&P PMI | ≥12 monthly periods stored (earliest ≈ 2027-08 at one period per month) |
| FactSet | ≥60% non-null on `blended_earnings_growth_yoy` and `forward_12m_pe` over the last 24 report dates |
| HKEX Stock Connect flow | ≥250 trading days, or never — Eastmoney owns the field |
| MSCI security links | any non-zero `sedol`/`isin`/`ric` population |

## Phase 1 — Asia Markets

### 1A. Artifact layer

Extend the existing builder *modules*; do not extend the two largest artifact
*files*.

```text
global-market-regime-artifact.json     8.9 MB   (x2 with -zh)
market-monitor-artifact.json           6.6 MB   (x2 with -zh)
total .generated JSON                 47.2 MB   WARN_ARTIFACT_TOTAL_MB = 80
projected Streamlit RAM      132.5 + 10x = 604 MB   of STREAMLIT_LIMIT_MB = 1024
.generated commits, last 14 days            44   (~3/day)
```

Both artifacts are rewritten whole roughly three times a day, so git history
cost is size × rewrite frequency, and the repository already carries a
`fix/repo-daily-bloat` branch for exactly this. The HK and macro lanes go into a
third, smaller artifact:

```text
apps/asia-markets-dashboard/scripts/build_hong_kong_flows_artifact.py
    -> hong-kong-flows-artifact.json  (+ -zh)
```

Datasets, following the existing snake_case convention
(`fred_observations`, `cot_history`, `southbound_market_flow`):

```text
hkma_liquidity_daily          hkex_short_inventory_daily
southbound_market_flow        msci_index_events
bis_credit_cycle_quarterly    pmi_headline_latest
eia_power_mix_daily
```

`source_health` and `freshness` already exist as per-artifact dataset keys.
Extend them; do not invent a parallel mechanism.

Rules:

- **Publish only the columns a renderer reads.** This is already the practice —
  `build_market_monitor_artifact.py:730` publishes four fields of
  `southbound_market_flow` and says so in a comment. Make it a stated rule; it
  is the single most effective control on artifact size.
- Window before publishing. `msci_rebalance_events` is 71,602 rows; published
  unwindowed it roughly doubles an artifact. Filter to HK/CN (8,888 rows) and
  the last N review cycles.
- Aggregate EIA hourly rows to daily fuel/region summaries before publication;
  never send 2.5 M rows to Streamlit.
- Preserve nulls and distinguish observed zero from missing data. A column that
  is 0% populated is not published as an empty column — it is declared
  `unavailable` in source health and given no UI.
- Keep PMI `is_flash` separate from final observations.
- Keep MSCI `announcement_date` and `effective_date` separate.
- Do not infer missing FactSet fields or MSCI identifiers.
- Carry source id, source tier, release date, retrieval time, coverage reason,
  source URL, and PIT/vintage information in artifact metadata or rows.

### 1B. Page wiring

After the artifact contract is stable, add thin rendering changes:

- `Hong Kong Flows & Liquidity`: Eastmoney flow, HKEX short inventory, HKMA
  liquidity, MSCI HK/CN index events.
- `Market Regime`: FRED, OFR, CFTC, VIX, BIS, HKMA liquidity.
- `ETF Monitor`: MSCI context; flow detail links to the new page.
- `Overview`: latest cross-market pulse summaries, including the PMI card.
- `Data Explorer` and `Source Health`: expose the new datasets and their quality
  state without hardcoded source-specific loaders.

No new chart types are part of this planning pass. First stabilize artifact
semantics and provenance.

### 1C. Asia acceptance gates

Each of these is checkable, and each exists because something in this repository
has already failed the way it describes.

1. Offline Streamlit rendering with no runtime source calls.
2. English/Chinese page parity (`check_streamlit_parity.py` stays green).
3. **No published dataset has a column that is 0% non-null.** Such a column is
   declared `unavailable` in source health instead.
4. **No source promotion moves a series' earliest observation later.**
5. Artifact total stays under `WARN_ARTIFACT_TOTAL_MB`, asserted in the same run
   as `check_repo_size_budget.py`.
6. `is_flash`/final and `announcement_date`/`effective_date` survive a
   round-trip through the artifact — asserted on a **fixture**, not on tracked
   repo data. A test that reads the repository's own data asserts "the repo
   currently has data" as much as the behaviour, and breaks precisely when the
   guarded failure occurs.
7. A new ops validator, alongside the four in `src/ops_control/registry.py:223`
   (`file`, `dataset_contract`, `asia_markets_freshness`,
   `observation_freshness`): a **fill floor** per named column. `max_age_days`
   on `report_date` passed every day while 596 of 821 FactSet rows were empty;
   freshness validators check the date column, not the payload.

## Phase 2 — Research Control Tower

The Control Tower continues to publish immutable generations through
`.generated/CURRENT`. New data is added by adapters from normalized parquet to
the existing contracts; the app itself remains read-only.

### Fix the freshness SLA first

The draft asked that "Control Tower freshness must support a per-source override
before the schema default." The reader already exists; the writer does not.

```text
coverage.py:242,413,1031,1038        reads source.stale_after_days
pages/source_health.py:49,310,429    reads and renders it
tests/..._coverage_states.py         fixtures set it

build.py SOURCE_HEALTH_COLUMNS       has "cadence" -- no "stale_after_days"
all 14 emitted generations           column absent (21 columns)
```

So `coverage.py:1031` fires for every source today — `"{label} has no matched
freshness SLA"` → `partial`. The failure is not that BIS is mislabelled stale;
it is that no source has an SLA at all and everything is downgraded.

The values already exist and must not be duplicated into a second table:
`config/ops/pipelines.yaml` carries per-output `max_age_days` (hkex 7, eia 5,
hkma 7, factset 21, sp_pmi 75, bis existence-only). Add `stale_after_days` to
`SOURCE_HEALTH_COLUMNS` and populate it from the ops registry, with a test
asserting no emitted source row has a null SLA. This is a prerequisite for
Phase 2, not a detail of Phase 2C.

### Map fields, do not restate principles

The RCT contracts are richer than the draft's prose implied.
`macro_observations` already carries `pit_class`, `source_license_class`,
`is_provisional`, `realtime_start`/`realtime_end`, `first_observed_at`,
`source_published_at`, and `registry_version`; `source_health` carries
`entitlement_status`, `entitlement_evidence`, `entitlement_ref`, `input_sha256`,
and `schema_version`.

Phase 0's remaining deliverable is therefore a **per-source field-mapping
table**: source column → contract column → `pit_class` value →
`source_license_class` value → `entitlement_status` value. A prose rule cannot be
asserted by a test; a mapping table can.

Licensing is a field, not a sentence. MSCI review PDFs, FactSet Insight
articles, and the S&P Global PMI pages are all copyrighted publications being
read programmatically, and all three need an assigned `source_license_class` and
`entitlement_status` before anything derived from them is published.

### Data routing

- **`macro_observations`**: BIS, HKMA, CFTC, Eastmoney Stock Connect flow, and
  reused FRED/OFR/VIX data. PMI and FactSet are excluded until they pass their
  promotion triggers.
- **`events`**: PMI releases, MSCI announcement/effective events, important
  HKMA/HKEX releases, and official filing events.
- **`official_filings`**: reuse canonical SEC EDGAR and HKEX normalized data.
- **`source_health`**: register all lanes, including partial, unavailable, and
  out-of-scope states. `cme_voi` must be registered or it will not appear even
  as unavailable.
- **`evidence_items`**: metadata and short licensed summaries only; do not copy
  vendor article bodies.
- **Consensus marts**: do not map FactSet aggregate articles to security-level
  consensus snapshots or revisions.

### MSCI entity links

The draft's rule — links only on exact SEDOL/ISIN/RIC matches — is correct
policy and, against this data, produces **zero links**: those four identifier
columns are 0% populated across all 71,602 rows, because MSCI's public lists
carry names rather than tickers. The Company page would therefore show no MSCI
events at all.

The unlinked index-event view is the primary deliverable, not the exception:
events are scoped by `index_name` and `country`. Name-only matching and guessed
tickers remain prohibited. Security-level linkage requires parsing identifiers
out of the MSCI PDFs, which is a separate prerequisite task and is deferred
below.

### Control Tower pages

- `Today`: latest releases, observations, events, and source alerts.
- `Unified Timeline`: publication, observation, and effective-date sequence.
- `Company`: exact-linked filings only. **No MSCI events until identifiers exist.**
- `AI Bottlenecks`: later, selectively use relevant energy and filing evidence;
  do not force all macro data into this theme.
- `Source Health`: freshness, PIT, license, coverage, and entitlement state.

## Cross-phase quality rules

- One collector owner per source, decided per field where lanes overlap.
- One canonical normalized table per dataset.
- Shared calculations live in reusable source/semantic helpers when both
  dashboards need them. Note that `sp_pmi_subindices` currently violates this —
  `orders_to_inventory_ratio` and `price_pass_through_spread` are derived
  columns computed in the normalized table. Both are 0% populated, so the
  cleanest fix is to drop them from the normalized schema rather than backfill.
- Consumer adapters perform only reshaping, aggregation, and contract mapping.
- No silent fallback, interpolation, or zero-filling.
- Preserve observation, release, retrieval, and effective timestamps.
- Keep `current_vintage` separate from true historical-vintage data.
- Keep licensing and attribution metadata with every published artifact.
- Row count is never the health metric. Fill rate and earliest observation are.

## Implementation order

```text
Phase 0   ownership decisions + field-mapping table   (coverage audit already done)
Phase 0b  fix the FactSet fill regression; add the fill-floor validator
Phase 1A  hong-kong-flows artifact contract and source health
Phase 1B  Hong Kong Flows & Liquidity page; dual-key southbound migration
Phase 1C  Market Regime, ETF Monitor, and Overview
Phase 1D  Explorer and Source Health
Phase 2-0 emit source_health.stale_after_days from the ops registry
Phase 2A  Control Tower macro observations
Phase 2B  Control Tower events and filings
Phase 2C  immutable generation validation
Phase 2D  Control Tower page consumption
```

Each phase requires focused tests, a staging build, schema/hash/row-count
validation, provenance review, and only then publication of a new artifact or
generation.

## Explicitly deferred

- Alternative Data AI dashboard integration.
- CME VOI signal integration until access is restored.
- FTSE review collector.
- Full EIA hourly data in Control Tower.
- Security-level earnings consensus derived from FactSet public articles.
- MSCI identifier extraction from the public PDFs, and therefore all MSCI
  security-level entity linkage.
- Fuzzy MSCI security identity matching — permanently prohibited, not deferred.

## References

- `docs/free-institutional-data-backfill-audit.md` — per-lane coverage, column
  fill rates, post-backfill defects, storage rationale.
- `config/ops/pipelines.yaml` — per-output freshness contracts.
- `docs/asia-markets/OPERATING_MANUAL.md`, `PROJECT_STATUS.md`, `DATA_CATALOG.md`
  — keep current when this plan changes dashboard architecture or coverage.
