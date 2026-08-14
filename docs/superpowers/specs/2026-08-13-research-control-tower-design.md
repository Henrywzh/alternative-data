# Research Control Tower Streamlit Design

**Date:** 2026-08-13  
**Status:** Approved direction; Stage 1 UX scope approved 2026-08-14
**Primary repository:** `alternative-data`  
**Related repository:** `financial-data`

## 1. Decision

Build a new, private-first Streamlit application called **Research Control
Tower**. It will reuse the existing collectors, normalized datasets and
financial database, but it will not be added to the existing Asia Markets
Streamlit application.

The product boundary is:

- **Asia Markets:** Hong Kong-first sector and alternative-data deep dives.
- **Research Control Tower:** cross-market baskets, company and macro
  catalysts, consensus revisions, filings/news changes and research workflow.

The two applications share canonical entities and data contracts. They do not
duplicate collectors or embed one another's source pipelines.

The first release is local/private and read-only. Free web hosting is a later
deployment gate after data licensing, privacy and usefulness are validated.

## 2. Objectives

The Control Tower should answer five questions quickly:

1. What changed since the previous review?
2. What confirmed events occur in the next 7, 30 and 90 days?
3. Which longer-range thesis milestones need evidence or review?
4. Which baskets and companies are affected by each event?
5. Which data are stale, conflicting, missing or weakly sourced?

It is not intended to:

- reproduce a market-data terminal;
- display every headline;
- run collectors while a user navigates the app;
- invent precise dates for uncertain industry milestones;
- blend incompatible consensus estimates;
- become a public redistribution surface for licensed content;
- replace the detailed Asia Markets sector dashboards.

## 3. Research universe

### 3.1 Primary baskets

The initial basket registry contains:

| Basket ID | Purpose |
|---|---|
| `US_VALUE` | US banks, insurance, energy, industrials, utilities and defensive value |
| `US_GROWTH` | US mega-cap platforms, software, semiconductors and long-duration growth |
| `HK_VALUE` | Hong Kong developers, banks, insurers, utilities, transport and local leaders |
| `HK_INTERNET` | Hong Kong-listed internet and platform companies |
| `HK_AI_THEMATIC` | Hong Kong-listed AI, semiconductor, robotics and related thematic names |
| `AI_BOTTLENECKS_GLOBAL` | Cross-market AI infrastructure bottlenecks and demand chain |

Every membership has:

```text
entity_id
basket_id
membership_tier       # core | read_through | watch_only
primary_layer
secondary_layers[]
active_from
active_to
membership_reason
source_or_research_note
```

Membership is versioned. Historical analysis must not apply today's membership
to an earlier date without explicitly labelling it as a current-universe
replay.

### 3.2 Global AI Bottlenecks basket

`AI_BOTTLENECKS_GLOBAL` is organized by supply-chain constraint rather than
country.

| Layer | Initial anchor entities |
|---|---|
| Accelerators and custom silicon | NVIDIA, AMD, Broadcom, Marvell, Cambricon |
| HBM and memory | SK Hynix, Micron, Samsung Electronics, Nanya, Winbond |
| Foundry | TSMC, Samsung Electronics, SMIC, Hua Hong Semiconductor, UMC, GlobalFoundries |
| Advanced packaging and test | ASE Technology, Amkor, BESI, Hanmi Semiconductor, JCET |
| Semiconductor equipment and materials | ASML, Applied Materials, Lam Research, KLA, ASM International, NAURA |
| Substrates and PCBs | Unimicron, Nan Ya PCB, Ibiden, Ajinomoto |
| Optical and networking | Arista Networks, Lumentum, Coherent, Accton, ZTE |
| Server ODM and systems | Quanta, Wistron, Wiwynn, Dell, HPE |
| Rack power and cooling | Vertiv, Eaton, Monolithic Power Systems, Delta Electronics, Schneider Electric |
| Grid and energy | GE Vernova, Constellation Energy, Vistra, Siemens Energy |
| Hyperscaler demand | Microsoft, Amazon, Alphabet, Meta, Oracle, Tencent, Alibaba |

Initial tiering rules:

- **Core:** direct bottleneck owner or major demand anchor; receives daily
  consensus snapshots and complete catalyst monitoring.
- **Read-through:** supplier, customer or competitor whose disclosure can
  validate a core thesis; receives event and guidance monitoring.
- **Watch-only:** distant supplier, unresolved listing, possible IPO or weak
  data coverage; excluded from automated consensus aggregation.

SK Hynix is a core anchor. TSMC, NVIDIA, Micron, Samsung Electronics and ASML
are cross-layer anchors. Mainland and Hong Kong ticker mappings must be
validated before a company becomes active in automated collection; unresolved
entities remain watch-only.

### 3.3 Index registry

The benchmark registry initially contains:

| Region | Index |
|---|---|
| US | S&P 500, Nasdaq 100, Russell 2000 |
| Hong Kong | Hang Seng Index, Hang Seng TECH Index |
| Mainland China | CSI 300, CSI 500 (`000905`) |
| Taiwan | TAIEX |
| South Korea | KOSPI |
| Japan | Nikkei 225, TOPIX |
| Europe | STOXX Europe 600 |

STOXX Europe 600 is the primary European research benchmark because it covers
broader European value, growth and AI-supply-chain exposure than Euro STOXX
50. Euro STOXX 50 may later be added as a liquid trading proxy, but is not
required in V1.

Index-level estimate signals are bottom-up aggregates of covered constituents.
Every result displays coverage by count and index weight. The system does not
present incomplete constituent estimates as full-index consensus.

## 4. Shared data architecture

### 4.1 Repository ownership

`financial-data` remains canonical for:

- financial statements and actuals;
- consensus observations and snapshots;
- fiscal-period and accounting-basis normalization;
- security and listing identifiers;
- market valuations owned by that repository.

`alternative-data` remains canonical for:

- macro and policy datasets;
- filings/news/event metadata outside the financial database;
- alternative and supply-chain indicators;
- basket definitions and catalyst research;
- dashboard artifacts and the Control Tower application.

The hosted or portable application must not depend on attaching a sibling
DuckDB at runtime. A build step exports compact, privacy-reviewed marts from
each canonical repository. Local development may read the sibling DuckDB
through the existing bridge.

### 4.2 Data flow

```text
Official APIs / RSS / permitted pages / company IR
                         |
             deterministic collectors
                         |
       immutable raw capture + content hash
                         |
       source-specific normalized observations
                         |
        entity resolution and timing semantics
                         |
   event ledger / consensus snapshots / news metadata
                         |
        compact Control Tower read marts
                         |
              read-only Streamlit app
```

The Streamlit process performs no source collection during page navigation.
Refreshing a page cannot modify canonical research data.

### 4.3 Entity model

One company can have multiple listings. Events and research claims attach to a
stable `entity_id`; market data and consensus attach to a `listing_id`.

Required entity fields:

```text
entity_id
legal_name
display_name
country
sector
industry
active_status
```

Required listing fields:

```text
listing_id
entity_id
exchange
native_ticker
vendor_tickers
currency
primary_listing
active_from
active_to
```

This prevents TSMC ADR, TSMC Taiwan and company-level TSMC guidance from being
treated as three unrelated entities.

## 5. Unified event ledger

### 5.1 Event scopes

Company and macro timelines use one event contract:

```text
scope = company | basket | macro | policy | index
```

### 5.2 Event classes

Events are separated into:

1. **Hard event:** officially scheduled or legally effective.
2. **Provisional event:** reported date that may still change.
3. **Thesis checkpoint:** an uncertain research window.
4. **Observed event:** a release, disclosure or development that already
   occurred.

Examples of hard events:

- earnings releases;
- investor days;
- shareholder meetings;
- macro releases;
- central-bank decisions;
- regulatory deadlines;
- index review announcements and effective dates;
- dividend and lock-up dates.

Examples of thesis checkpoints:

- HBM4 qualification;
- HBM4E volume ramp;
- CPO production ramp;
- ABF undersupply inflection;
- hybrid-bonding adoption;
- new-fab customer qualification;
- AI-server power bottlenecks.

### 5.3 Event fields

```text
event_id
scope
event_type
title
description
status
confidence
date_precision          # minute | day | week | month | quarter | half | year
starts_at
ends_at
source_timezone
source_id
source_url
source_published_at
first_observed_at
last_verified_at
review_by
supersedes_event_id
related_entities[]
related_listings[]
related_baskets[]
watch_questions[]
expected_metrics[]
thesis_implications[]
```

An uncertain window must have `starts_at`, `ends_at` and `date_precision`.
Using the final day of a quarter as a fake exact event date is prohibited.

Changes do not overwrite history. Date, status and confidence revisions create
versioned observations linked through `supersedes_event_id`.

### 5.4 Watch questions

The most important research field is `watch_questions[]`. It states what
evidence would support or reject the thesis.

Example:

```text
event: SK Hynix HBM4 qualification window
watch_questions:
  - Has customer qualification moved from sampling to production approval?
  - Is HBM capacity sold through for the next planning period?
  - Are yield and packaging constraints improving?
  - Does capex indicate supply growth ahead of demand?
  - Has expected HBM mix or ASP changed?
```

## 6. Macro timeline

### 6.1 Initial coverage

The macro timeline includes:

- US CPI, PCE, payrolls, unemployment, GDP and major surveys;
- FOMC decisions, projections, minutes and relevant Treasury events;
- China GDP, CPI/PPI, industrial production, trade, property and policy
  releases;
- Hong Kong GDP, CPI, unemployment, trade and HKMA events;
- Korean CPI, Bank of Korea decisions, exports and semiconductor exports;
- Taiwan central-bank decisions, exports, export orders, production and
  company monthly revenue windows;
- Euro-area inflation, GDP, labour and ECB events;
- UK inflation, labour, GDP and Bank of England events;
- export-control and industrial-policy deadlines;
- official index reviews and effective dates.

### 6.2 Macro event extension

Macro events extend the unified event contract with:

```text
reference_period
previous_value
previous_vintage
market_consensus
consensus_source
own_nowcast
actual_value
revised_value
surprise_value
surprise_unit
affected_baskets[]
scenario_notes[]
```

Market consensus, own nowcast and actual are separate fields. Later revisions
never replace the originally observed release.

Every source timestamp is retained in source-local time and UTC. The UI may
also display London time, but London time is not stored as the canonical
release timestamp.

## 7. Consensus and revision layer

### 7.1 Source policy

V1 uses provider-specific observations rather than a blended consensus:

- Futu for current target prices, rating distribution, analyst counts and
  near-term earnings-calendar estimates where entitled;
- yfinance as a current aggregate and short-window revision source;
- AkShare/Eastmoney for China/Hong Kong discovery and dated broker reports;
- FnGuide pages and dated Korean broker reports for SK Hynix and Korea;
- official filings and company IR for actuals and guidance;
- Alpha Vantage or FMP only in a bounded validation experiment.

IBKR is treated primarily as a news/calendar supplement. Wall Street Horizon
is optional and paid, not a free consensus dependency.

### 7.2 PIT classifications

Every observation is labelled:

```text
true_pit
snapshot_from_live_source
dated_public_broker_report
reconstructed_sparse
current_vintage
not_pit
```

Wayback-recovered values are `reconstructed_sparse`, never `true_pit`, unless
the archived source independently proves the original availability timestamp.

### 7.3 Snapshot fields

```text
snapshot_id
provider
entity_id
listing_id
metric
fiscal_period
value
statistic
low_value
high_value
analyst_count
currency
unit
accounting_basis
provider_asof
retrieved_at_utc
source_url
raw_hash
pit_class
```

Cross-source comparison is permitted only when fiscal period, currency, unit,
consolidation basis and EPS basis align.

### 7.4 Derived signals

Initial derived measures are:

- 1-day, 7-day and 30-day estimate revision;
- positive/negative revision breadth;
- estimate dispersion;
- analyst-count change;
- target-price revision;
- rating-distribution change;
- management-guidance change;
- event proximity.

No composite score or trading recommendation is included in V1.

## 8. News, filings and transcripts

### 8.1 Source hierarchy

1. **Official facts:** SEC, OpenDART, company IR, permitted exchange or
   regulator sources, official macro and index calendars.
2. **Professional enrichment:** entitled IBKR providers, Finnhub, Marketaux or
   another validated API.
3. **Discovery:** GDELT, Google News RSS and search/RSS adapters.

Discovery sources cannot confirm financial or regulatory facts.

### 8.2 Stored data

For licensed or copyrighted news, the default stored/displayed fields are:

```text
document_id
headline
publisher
published_at
first_observed_at
source_url
language
related_entities[]
related_baskets[]
event_class
importance
content_hash_if_permitted
derived_summary_if_permitted
```

The application does not publicly reproduce full article bodies or licensed
consensus tables. Raw Futu, IBKR and commercial API payloads are not committed
to a public Git repository.

### 8.3 Transcript extraction

Priority order:

1. company IR prepared remarks or transcript;
2. filing exhibit;
3. entitled platform or transcript provider.

Derived transcript observations include guidance changes, new metrics,
capacity comments, customer comments, risk-language changes and thesis
checkpoints. The source transcript remains evidence; LLM output is explicitly
derived.

## 9. Streamlit application

### 9.1 Reference product principles

The interaction and information hierarchy may draw from the current
AI Bottlenecks application, especially:

- a compact **flight deck** showing the research universe, current horizon,
  breadth/leadership context and next catalyst;
- a stable left navigation that moves from names to themes, catalysts,
  supply-chain stack and research;
- theme chips and market filters above a dense but searchable watchlist;
- bottleneck-cluster cards that summarize a theme before exposing its members;
- a catalyst view with one prioritized event beside a chronological list;
- visible countdowns such as `T-2d`;
- event descriptions framed as what evidence to watch;
- compact ticker chips that reveal cross-company read-through.

The Control Tower does not copy the reference product's visual assets, text or
proprietary research. It adapts the useful interaction grammar to the user's
own source-backed data.

The design also deliberately differs from the reference:

- the flight deck prioritizes changes in evidence, consensus, guidance and
  event status rather than only price leadership;
- macro and policy events are first-class timeline objects;
- confirmed, provisional and thesis-window events are visibly different;
- long-range milestones retain date ranges and precision instead of being
  rendered as arbitrary exact dates;
- source timestamps, PIT class, confidence and revision history are available
  from every research item;
- value/growth and regional baskets coexist with the AI supply-chain view.

### 9.2 Location and structure

Proposed entry point:

```text
apps/research-control-tower/app.py
```

Unlike the existing 4,000-line Asia Markets app, the new application must use
small modules with separate responsibilities:

```text
apps/research-control-tower/
  app.py
  control_tower/
    config.py
    models.py
    repository.py
    filters.py
    formatting.py
    pages/
    components/
  .generated/
  requirements.txt
```

The repository layer hides whether data came from local DuckDB/Parquet or a
portable artifact bundle. Pages do not contain source-specific loading logic.

### 9.3 V1 pages

V1 has five primary pages.

#### Today / What Changed

- compact flight deck with selected universe, review horizon, current evidence
  breadth and next high-priority catalyst;
- next confirmed events;
- new or changed catalyst dates;
- material consensus revisions;
- new official filings and guidance;
- unresolved high-importance source conflicts;
- stale-source warnings.

This page is a prioritized delta, not a general news feed.

#### Unified Timeline

- 7-day, 30-day, 90-day and long-range views;
- company, macro, policy, index and thesis filters;
- confirmed/provisional/thesis visual distinction;
- basket and geography filters;
- prioritized next-catalyst panel beside the chronological event list;
- month grouping, local date/time and visible `T-minus` countdown;
- event detail with sources, watch questions and revision history.

#### AI Bottlenecks

- supply-chain layer navigation modeled as bottleneck-cluster/theme cards;
- core/read-through/watch-only filtering;
- upcoming catalysts by layer;
- cross-company read-through map;
- latest guidance and consensus changes;
- source and coverage status.

#### Company

- company thesis summary;
- upcoming and historical catalysts;
- consensus provider comparison;
- revisions and analyst coverage;
- filings/news metadata;
- affected and related baskets;
- watch questions and invalidation evidence.

#### Source Health

- last successful collection;
- latest source observation;
- rows or documents captured;
- staleness status;
- schema/collector failures;
- entitlement or licensing flags;
- unresolved entity matches and source conflicts.

News and consensus do not receive standalone V1 pages. They appear where they
affect today's decisions or a specific company. Standalone explorers are
considered only after observed use demonstrates a need.

### 9.4 Interaction rules

Global filters persist within a session:

```text
date horizon
basket
country
event class
confidence/status
membership tier
importance
```

Every displayed event exposes:

- event type and certainty;
- a calculated `T-minus` value for future events;
- original/source timezone;
- source and last verification time;
- affected baskets/entities;
- watch questions;
- whether any data are reconstructed or non-PIT.

The app defaults to concise summaries. Raw provenance and revision history are
available through drill-downs.

## 10. Daily workflow

The intended research cycle is:

### Before an event

- **T-30:** verify date/source and define watch questions.
- **T-14:** gather consensus, company guidance and read-through evidence.
- **T-3:** freeze a pre-event consensus and thesis snapshot.

### After an event

- **T+0:** ingest actuals, filings, prepared remarks and initial reaction.
- **T+1:** classify surprise, guidance change and thesis impact.
- **T+5/T+20:** review persistence and whether the market incorporated the
  information.

### Scheduled LLM role

An LLM may:

- cluster duplicates;
- compare old and new source observations;
- draft summaries;
- propose thesis checkpoints;
- identify source conflicts;
- produce a daily research brief.

An LLM may not:

- create a confirmed event without a qualifying source;
- silently merge conflicting consensus values;
- overwrite raw records;
- promote discovery headlines to verified facts;
- make the dashboard the sole record of an event.

## 11. Failure handling

- Optional source failure degrades the affected module without preventing app
  startup.
- A failed collector preserves the previous good snapshot and displays its
  age; it does not relabel it as current.
- Source conflicts become `review_required`.
- Unresolved ticker/entity mappings are excluded from aggregation.
- An event with no valid source is excluded from the confirmed calendar.
- A stale macro calendar cannot silently generate future recurring dates.
- Schema changes fail the artifact build before deployment rather than
  producing partially shifted columns.

## 12. Security and licensing

- The repository-root `.config` file is never copied, deleted or deployed.
- API keys are used only by collectors or deployment secrets, never embedded
  in generated artifacts.
- Licensed payloads remain in approved private storage.
- Public or portable artifacts contain only fields permitted for display.
- Source terms are recorded at the connector level.
- Private Streamlit hosting is not assumed to grant redistribution rights.
- Deployment is blocked until a field-level exposure audit passes.

## 13. Hosting decision

V1 runs locally as a private Streamlit app. A separate Streamlit Community
Cloud deployment may be tested after:

1. the application is useful in repeated local research sessions;
2. portable artifact generation is stable;
3. all displayed fields pass licensing/privacy review;
4. secrets and sibling-repository dependencies are removed from runtime;
5. resource usage fits the free service.

Cloudflare is not part of the V1 implementation. It remains a later option for
a public or durable read-only surface after the interaction and data model
stabilize.

## 14. Validation

### Data-contract tests

- entity/listing uniqueness and validity;
- basket membership temporal consistency;
- event date precision and timezone validity;
- confirmed-event source requirement;
- thesis-window start/end consistency;
- consensus fiscal-period and currency alignment;
- PIT classification presence;
- append-only revision lineage;
- index aggregate coverage calculation.

### Application tests

- application starts with all required marts;
- application starts in degraded mode when optional marts are missing;
- each page renders through Streamlit AppTest;
- filters produce deterministic row sets;
- confirmed and thesis events are visibly distinct;
- stale and conflicting data warnings are visible;
- company and basket drill-down links resolve correctly;
- no page-navigation action writes canonical data or calls external sources.

### Manual browser verification

- desktop and narrow-window layouts;
- timeline readability across short and long horizons;
- source links and timestamps;
- interaction latency on the full V1 basket;
- no accidental exposure of keys or licensed payloads;
- useful bilingual handling of company names and source-language text.

## 15. V1 acceptance criteria

V1 is complete when:

1. The new app is independent of the existing Asia Markets Streamlit entry
   point.
2. `AI_BOTTLENECKS_GLOBAL`, CSI 500 and STOXX Europe 600 are represented in
   versioned registries.
3. Company, macro, policy, index and thesis events render through one source-
   backed event contract.
4. Confirmed dates and uncertain thesis windows cannot be confused visually or
   semantically.
5. At least one representative company from US, Hong Kong/mainland China,
   Taiwan, Korea and Europe can be resolved through the entity/listing model.
6. SK Hynix has a complete company view with event, official filing and
   provider-specific consensus sections.
7. Today shows only changes since a recorded previous snapshot.
8. Consensus observations remain provider-specific and expose PIT class,
   fiscal period, currency and analyst count where available.
9. Source Health makes stale, failed, conflicted and unavailable data obvious.
10. The application performs no collection or canonical writes during
    navigation.

## 16. Implementation sequencing

The implementation plan should be divided into these bounded stages:

1. Registries and entity/listing resolution.
2. Unified event ledger and macro-event extension.
3. Consensus snapshot export and revision calculations.
4. Compact read marts and repository interface.
5. Streamlit shell, Today and Unified Timeline.
6. AI Bottlenecks and Company pages.
7. Source Health, degraded-mode behavior and complete QA.
8. Optional scheduled brief and hosting-readiness audit.

Each stage must use existing collectors where available and preserve unrelated
work in both repositories.
