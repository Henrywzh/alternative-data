# Research Control Tower Phase 1–2 Design

**Date:** 2026-09-10
**Status:** Design ready for user review
**Scope:** Research Control Tower only

## 1. Purpose and boundary

Research Control Tower is the research surface for fundamental and tactical investment-thesis work across US, Hong Kong, China, Taiwan, Korea, and Europe. Its job is to connect:

```text
company / industry / index / macro identity
        → news, filings, financials, consensus, nowcasts, calendar
        → price, technicals, options, positioning, microstructure
        → alternative-data signals and thesis checkpoints
        → investment thesis (fundamental / tactical)
```

This is not the Quantamental Lab. PIT signal research, backtests, portfolio construction, and systematic execution remain outside this application.

The current branch contains the cockpit redesign and a working company flow, but the app can still present scope ambiguity, missing universal data, and inconsistent evidence states. Phase 1 fixes semantics and correctness. Phase 2 makes the universal data layer reusable so Tencent is not a one-off implementation and Alibaba becomes the first generalisation proof.

No production implementation starts until this specification is approved.

## 2. Goals

1. Make every page explicit about its data scope and filter scope.
2. Make catalyst status and time windows unambiguous, including active, future, expired, and terminal events.
3. Prevent rows newer than the selected snapshot from appearing in historical or frozen views.
4. Treat unavailable, partial, stale, empty, and not-applicable data as distinct, honest states.
5. Define reusable, source-backed contracts for universal company data: identity, listings, prices, filings, news, earnings, consensus, valuation, corporate actions, and Southbound ownership.
6. Keep company-specific and alternative-data logic behind profiles/adapters rather than in shared rendering code.
7. Preserve provenance so a user can tell official issuer/exchange data from yfinance, akshare, financial-data, vendor news, or internal alternative data.
8. Prove the design with Tencent and Alibaba using their Hong Kong primary listings.

## 3. Non-goals for Phase 1–2

- Adding the remaining Stage 1.5 universe or expanding the AI/sector baskets.
- Building intraday or tick-level real-time trading infrastructure.
- Implementing scheduled Codex agents, on-demand refresh, or provider credential management.
- PIT backtesting, portfolio optimization, order generation, or systematic execution.
- Forcing every custom alternative signal into a universal schema before its meaning is understood.
- Replacing the Alternative-data dashboard or copying its entire data universe into this app.

## 4. Design principles

### 4.1 Identity before display

All company data resolves through the registry:

- `entity_id` identifies the economic entity.
- `listing_id` identifies a tradable listing.
- `primary_listing` and `listing_role` determine the display listing.
- `basket_id` and membership dates determine universe membership.

For China Internet companies, the Hong Kong equity is the primary listing when it exists. US ADR/OTC instruments remain alternate listings and must never silently replace the HK primary listing.

Display code receives resolved rows and metadata; it does not infer identity from names, ticker strings, or provider-specific symbols.

### 4.2 Snapshot time and observation time are different

Every source-backed row carries the relevant source publication/observation date, retrieval timestamp, and the bundle `as_of` boundary. A frozen bundle may display only information available by that boundary. A live overlay may show newer information only when it is clearly labelled as an overlay and cannot mutate the frozen bundle or historical cards.

### 4.3 Provenance is part of the value

Every metric, chart, and event identifies its source class and timestamp. The UI must distinguish at least:

- `official_external`: issuer, exchange, regulator, or official public institution.
- `vendor_external`: yfinance, akshare, financial-data, Finnhub, Marketaux, or another vendor.
- `internal_alternative`: locally collected OpenRouter, Southbound, or other custom alternative data.
- `derived_internal`: a calculation from one or more cited source rows.

Provider rows are not blended into official actuals. A vendor estimate may be shown as context, never as if it were an issuer-reported result.

### 4.4 Unavailable is a valid result

Missing data must not be represented by zero, stale numbers, or empty cards that look complete. The contract carries a status, reason, source, and last-known timestamp where available.

## 5. Phase 1 — semantic and correctness layer

### 5.1 Scope and filter contract

Create one explicit page context with these independent fields:

```text
global_filter_context: baskets, regions, active/archive mode, snapshot_as_of
page_scope: today | unified_timeline | source_health | ai_bottlenecks | company
selected_entity_id: optional
selected_listing_id: optional
```

Rules:

1. Today, Unified Timeline, and Source Health use the global filter context.
2. Company uses the selected entity/listing and may show only data linked to that company.
3. AI Bottlenecks uses an explicit page-local Global AI scope unless the page is changed to offer a deliberate universe selector. Its heading and scope badge must state this. The top Stage 1 filter must not imply that Global AI data is Stage 1-filtered when it is not.
4. A page may narrow a global scope only through a visible control or a documented page rule; it may not silently inherit a different scope.
5. A direct URL with an archived or unknown entity must show an explicit unavailable/archived state rather than silently falling back to the previous company.
6. Selectors are built from the active registry snapshot. Archived entities remain queryable by explicit ID for audit, but are not in the default active selector.

Relation resolution is registry-first. A direct `entity_id` relation wins; a valid listing-to-entity relation is the fallback; denormalised basket or theme columns are supplementary. A row is not dropped merely because a copied basket field is absent.

### 5.2 Catalyst lifecycle

Normalize source date/time values into a canonical timezone and interval. Date-only observations represent a full source day, not a point at midnight. Store `start_at`, optional `end_at`, original source values, and normalization metadata.

The canonical display state is:

| State | Rule |
| --- | --- |
| Future | `now < start_at` |
| Active | `start_at <= now` and (`end_at` is absent or `now <= end_at`) |
| Expired | `end_at` exists and `now > end_at` |
| Completed | source explicitly marks the event completed |
| Cancelled | source explicitly marks it cancelled |
| Unavailable | dates are missing or invalid and no safe state can be inferred |

“Upcoming catalysts” includes Future and Active events only. Expired, Completed, and Cancelled events are kept for lineage but excluded from forward-looking cards. The UI labels Future and Active separately and renders `start → end` when an end exists. Each catalyst shows source, importance, confidence/data-quality state, and the last update.

When a source supersedes an event, the latest valid observation is displayed while the prior row remains linked as lineage. Invalid date ranges fail closed and surface a data-quality warning.

### 5.3 Snapshot and future-leakage rules

All frozen-bundle readers apply the same `snapshot_as_of` predicate before page-specific filtering. This applies to:

- prices and quote snapshots;
- filings, news metadata, and corporate actions;
- earnings actuals and calendar events;
- consensus snapshots and revisions;
- valuation rows;
- thesis evidence and catalyst observations;
- macro and alternative-data observations.

Rows with a source timestamp after the boundary are excluded, even if their period label is earlier. Live overlays are isolated, marked with retrieval time and “not part of the published generation,” and cannot backfill frozen artifacts implicitly.

### 5.4 Coverage and alert semantics

Use one common coverage model:

```text
available | partial | stale | no_records | not_applicable | unavailable
```

Each status includes `record_count`, `latest_observation_at`, `source_id`, `source_url` where applicable, and a human-readable `reason`. “No records” means the source was queried successfully and returned none; “unavailable” means the source/artifact could not be read or validated; “not applicable” means the metric is not meaningful for that entity. Global source alerts remain distinguishable from selected-company alerts.

The UI must show the same status vocabulary in cards, charts, source health, and company sections. Numeric placeholders are prohibited.

### 5.5 Phase 1 acceptance tests

Add pure tests for:

- page scope not being confused with the global Stage 1 filter;
- Global AI page scope being explicit;
- active/archived selector behavior and direct archived URLs;
- registry relation fallback;
- date-only, interval, expired, completed, cancelled, invalid, and superseded catalysts;
- future rows being excluded at the bundle boundary;
- overlay rows remaining separate from frozen data;
- all six coverage states and their reasons;
- selected company not persisting after a valid company switch;
- no silent fallback from an invalid/archived company to the prior company.

Run the existing Research Control Tower test suite, compile/lint checks, and a browser smoke test covering navigation, company switching, theme switching, and all primary pages. The smoke test must have no browser console errors or uncaught Streamlit exceptions.

## 6. Phase 2 — reusable universal data layer

### 6.1 Canonical marts

The application-facing repository exposes the following logical marts. Physical filenames may vary by generation, but the logical contract must remain stable.

| Domain | Logical marts | Minimum identity |
| --- | --- | --- |
| Registry | entities, listings, baskets, memberships | entity/listing/basket IDs and active dates |
| Market | quote snapshots, price bars, corporate actions, valuation snapshots | listing ID, observation time, source |
| Fundamentals | earnings calendar, earnings actuals | entity/listing, period, metric, basis |
| Expectations | consensus snapshots, consensus revisions | entity/listing, metric, forecast period, snapshot time |
| Documents | official filings, generic news/filing metadata | entity/listing or explicit global scope, publication time |
| Evidence | events, thesis claims, watch questions, evidence, claim links | entity or global scope, event/evidence IDs |
| Alternative | provider economics and custom signal marts | explicit entity/listing or theme scope, observation time |
| Operations | source health and collection runs | source ID, run ID, retrieved time, status |

Every row that can be company-specific must carry `entity_id` or `listing_id`; genuinely global rows must declare `scope_type=global` instead of using a fake company ID.

### 6.2 Minimum row metadata

Universal source-backed rows carry, when applicable:

```text
source_id / provider
source_url
source_published_at
observation_at or period_end
retrieved_at_utc
verified_at_utc
bundle_as_of
currency / unit / reporting_basis
parser_version / content_hash
coverage_status / coverage_reason
supersedes_id or lineage_id
```

Financial metrics additionally identify the metric definition, period type, actual/estimate flag, and accounting basis. Valuation rows additionally identify quote time, share-count basis, trailing/forward period, and the consensus source used. A PE or forward PE value is unavailable unless its denominator and contemporaneous quote are basis-compatible.

### 6.3 Ingestion and source precedence

Use a unified ingestion boundary for structured common sources:

1. Resolve registry identity and primary listing.
2. Collect source data through an adapter.
3. Normalize symbols, dates, units, currencies, and metric names.
4. Validate identity, grain, duplicates, timestamps, and hash/manifest membership.
5. Write a canonical mart plus collection-run/source-health record.
6. Render through the repository contract without provider-specific branching in page code.

Source precedence is domain-specific but explicit:

- official issuer/exchange/regulator data is the source for reported actuals and official documents;
- yfinance, akshare, and financial-data provide labelled vendor market/fundamental context where coverage is useful;
- Finnhub and Marketaux provide labelled news metadata overlays;
- custom OpenRouter/Hunyuan and Southbound collectors remain internal alternative-data sources with their own freshness and methodology;
- derived metrics cite the input rows and calculation version.

If two providers disagree, show separate labelled rows or a reconciliation state. Do not silently select one as official.

### 6.4 Repository and view-model interface

Shared components should depend on generic functions shaped around:

```text
snapshot + entity_id/listing_id + metric/domain → rows + coverage + provenance
```

Company profiles may declare aliases, segment mappings, custom alternative-data panels, and supported metrics. They may not contain hardcoded current values, manually typed source dates, or rendering-only company branches. A profile can state that a metric is not applicable; it cannot manufacture a value.

The generic Company view must be able to render, with the same code path:

- selected primary listing and current quote/price history;
- reported financial history and margins with period/basis labels;
- earnings calendar and actual-vs-consensus context;
- valuation multiples and return yields when inputs are complete;
- official filings and vendor news metadata;
- corporate actions and HKEX Southbound ownership history where available;
- thesis/evidence lineage and coverage state;
- optional custom alternative-data panels.

Charts use one reusable visual contract aligned with the Alternative-data dashboard: explicit source/as-of labels, complete date formatting including year, incomplete-day markers, consistent light/dark theme tokens, units in titles/axes, and an accompanying data table or hover details. The chart renderer must not infer a missing period as zero.

### 6.5 Universal failure contract

Repository reads return a typed result rather than raising a raw file/provider error into the UI:

```text
rows
coverage
provenance
warnings
error_code (only when unavailable)
```

Schema/hash failures remain startup-blocking for required artifacts. Optional domain failures degrade only that domain and explain the reason. A malformed vendor response must not erase valid official data or make the whole company page appear to have no fundamentals.

### 6.6 Tencent → Alibaba generalisation proof

The order is:

1. Implement the universal contract against the existing Tencent data and profile.
2. Verify Tencent’s Hong Kong primary listing, financials, consensus, valuation, filings, market data, Southbound series, and custom alternative-data panel.
3. Add Alibaba using `9988.HK` as primary listing and its registry/provider aliases.
4. Run the same view-model and chart builders for Alibaba without copying Tencent rendering logic.
5. Keep Alibaba-specific segment names, source quirks, and missing-data explanations in its profile/adapter only.
6. Add a fixture for a company with no optional data to prove graceful degradation.

Acceptance requires that switching Tencent ↔ Alibaba changes entity-scoped rows, titles, listing/currency/source labels, and coverage independently; no stale Tencent rows remain in Alibaba; no US ADR is selected as primary; and the shared code path contains no company-specific numeric KPI literals.

### 6.7 Phase 2 tests and data gates

Add contract tests for:

- schema and required identity fields for every logical mart;
- HK primary-listing resolution and alternate-listing labelling;
- metric units, currencies, periods, and accounting bases;
- duplicate and future-row rejection;
- official/vendor/internal provenance labels;
- valuation denominator/quote compatibility;
- source failure isolation and coverage states;
- Tencent/Alibaba parity through shared view-model builders;
- no-data/private/archived fixtures;
- chart date labels, incomplete-day handling, and table/chart value parity.

Before publishing a new generation, run the collector, validate manifests and hashes, run the full application test suite, execute the real-bundle smoke test, and inspect the key Tencent and Alibaba pages in a local browser.

## 7. Delivery gates and later scope

| Gate | Deliverable | Exit condition |
| --- | --- | --- |
| A | This design spec | User approves scope and contracts |
| B | Phase 1 semantic layer | Pure tests and page-scope/catalyst/as-of checks pass |
| C | Phase 1 UI review | Local browser review confirms clear states and no runtime errors |
| D | Phase 2 repository contracts | Universal marts, adapters, view-models, and failure states pass contract tests |
| E | Tencent/Alibaba data run | Fresh generation loads; manifest/hash and provenance audit pass |
| F | Release | Full CI, browser smoke, and user acceptance pass; then commit/push the implementation |

Work after Gate E is intentionally deferred: broader company universe, Stage 1.5, richer options/positioning/microstructure, automated refresh, scheduled agent workflows, and portfolio/quantamental integration.

## 8. Main risks and mitigations

| Risk | Mitigation |
| --- | --- |
| A global AI page looks filtered by Stage 1 | Page-local scope badge and separate filter contract |
| Future or expired catalysts look actionable | Canonical lifecycle states and interval rendering |
| Vendor values look like official results | Source-class labels on every card/chart and separate overlays |
| Mixed currency/accounting bases corrupt margins or PE | Require unit/basis metadata and fail closed |
| Profile-specific code spreads into shared pages | Adapter/profile boundary and static hardcoded-value checks |
| A missing optional artifact blanks the company page | Typed per-domain coverage and failure isolation |
| Frozen views leak newly collected rows | One snapshot predicate before every page filter |
| Alibaba exposes hidden Tencent assumptions | Shared fixture parity and a no-company-branch review gate |
| Chart design becomes inconsistent again | Reusable Alternative-data visual contract and browser review |

## 9. Approval checklist

Before implementation, confirm:

- Phase 1 precedes Phase 2.
- Global/page-local filter semantics are acceptable.
- Catalyst lifecycle and snapshot rules are acceptable.
- The listed universal marts are sufficient for the first reusable layer.
- Official, vendor, internal, and derived provenance must remain visibly separate.
- Tencent and Alibaba are the only generalisation proof companies in this scope.
- Scheduled automation and broader universe work stay outside this delivery.
