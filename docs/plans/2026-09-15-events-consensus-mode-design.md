# Asia Markets Events / Consensus Mode

Date: 2026-09-15

Status: Approved for implementation

## Objective

Add a private, macro-first event and market-consensus workflow inside the
existing Asia Markets Streamlit Market Monitor. The workflow is for identifying
risks and catalysts, inspecting what markets expected before a release, and
building conditional responses. It is not an automated trading system.

Research Control Tower is not the V1 host. The data engine is an independent
`event_consensus` package in `alternative-data`; Asia Markets is its first
consumer and Research Control Tower may consume the same artifacts later.

## Product surface

The Market Monitor receives a top-level internal mode selector:

- Markets: the existing regional index and ETF monitor, unchanged.
- Events / Consensus: the new event workflow.

The Events / Consensus mode opens with a 7-14 day timeline ranked by an
explainable risk/catalyst score. Selecting an event opens an event console with:

- consensus and revision history;
- event-specific component contract;
- cross-asset pricing;
- scenario/playbook templates;
- post-release actual and surprise fields;
- source health and timestamp lineage.

## Acquisition paths

All triggers use the same collectors and normalized schema:

1. Scheduled refresh for calendar maintenance and eventual cloud capture.
2. Event-window refresh for T-5d, T-1d, T-60m, release, T+2m, T+30m,
   end-of-day and next-day checkpoints.
3. Explicit Streamlit buttons for refresh-now and selected-event refresh.

Page navigation remains read-only. Only an explicit button may call a remote
source from Streamlit.

Free-source hierarchy:

- official publishers for final actuals and detailed components;
- third-party calendar/consensus sources for pre-release expectations;
- Futu OpenD as an optional local fast lane;
- Finnhub and other free quote sources as fallbacks;
- user-defined alternative-data sources as registered evidence, not
  automatically invented theses.

The first implementation uses TradingView's public economic-calendar response
as a clearly labelled third-party calendar/consensus source because the
configured Finnhub free plan permits quote access but returns HTTP 403 for the
economic-calendar endpoint. Finnhub remains the initial manual quote adapter.
No third-party actual is labelled official.

## Point-in-time contract

Every observation retains:

- stable provider and canonical event identifiers;
- scheduled release time in UTC and source timezone when known;
- provider-published time when exposed;
- first-observed and retrieved timestamps;
- trigger type and checkpoint stage;
- forecast, previous, revised previous and actual values as separately
  nullable fields;
- source, source URL, provider event ID and payload checksum;
- verification status.

Manual refreshes append observations and never overwrite locked pre-event
snapshots. Repeated identical scheduled observations within the same checkpoint
may be deduplicated, but a changed forecast, prior or actual creates a new
observation. Quote and official-component ledgers follow the same rule: an
updated value creates a new row; only a complete identical automatic payload
may be deduplicated.

## Storage and publication

Local immutable observation ledgers live under
`data/normalized/event_consensus/` and remain git-ignored. The latest compact
UI artifact lives under `data/cache/event_consensus/`. A scheduled GitHub
workflow uses cache plus per-run uploaded artifacts as a free cloud backup;
the pipeline itself is executor-neutral and may later publish the same compact
artifact to R2 or be called by a Cloudflare Worker.

The compact artifact contains bounded current events, bounded consensus
history, current market snapshots, component contracts, source health and a
semantic content hash. Raw credentials and full provider payloads are never
included.

## Event scoring

The timeline score is descriptive and decomposed into visible components:

- event importance;
- proximity/checkpoint;
- forecast availability;
- forecast revision;
- actual surprise once released;
- provisional watchlist relevance.

Consensus dispersion and historical asset sensitivity stay unavailable until
there is a real multi-contributor or historical event-study dataset. They are
not imputed.

## Failure behavior

- A failed refresh keeps the last valid local artifact and adds a degraded
  source-health result.
- An empty provider response never replaces a non-empty timeline.
- Missing consensus, component values or market quotes remain null and visibly
  unavailable.
- Unsupported Finnhub markets such as Korea/Hong Kong are not represented as
  covered.
- The interface states whether a number is third-party, official, provisional
  or unverified.

## Initial validation

- unit tests for source parsing, stable IDs, checkpoint assignment, scoring,
  append-only deduplication and fallback;
- Streamlit contract tests for the internal mode and explicit-only refresh;
- focused Asia Markets and market-monitor test suites;
- live manual refresh against the free calendar and Finnhub quote endpoints;
- bilingual Streamlit smoke test.
