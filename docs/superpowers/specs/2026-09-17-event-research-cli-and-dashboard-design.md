# Event Research CLI and Dashboard Design

Date: 2026-09-17

Status: Design approved; implementation pending

## Objective

Turn the standalone Asia Markets Events & Consensus page into a shared
event-research surface for both humans and repository-local coding agents.

The product must support three connected workflows:

1. a short-horizon macro catalyst briefing;
2. event-level research and nowcast inspection;
3. post-release review and event-study learning.

Streamlit and coding agents must consume the same read model. The design must
not create a second acquisition pipeline, duplicate the point-in-time ledgers,
or require a local server.

## Existing foundation

The existing `event_consensus` package remains the data owner. It already
provides:

- remote-source adapters and an executor-neutral refresh pipeline;
- append-only event, quote, and official-component Parquet ledgers;
- a bounded `events_consensus_latest.json` artifact;
- stable event IDs, checkpoint stages, source lineage, and semantic hashes;
- consensus history, current quotes, component contracts, scenario templates,
  and source-health records;
- an `event-consensus` command that performs refreshes.

The new work adds a read/query layer over these artifacts. It does not move
source collection into Streamlit and does not make page navigation trigger
network access.

## Scope

### In scope

- a pure, read-only Python query core inside `src/event_consensus/`;
- JSON-producing query commands under the existing `event-consensus` CLI;
- repository documentation that makes the CLI discoverable to Codex, Claude,
  and other local coding agents;
- three human workflows on the standalone Events & Consensus Streamlit page;
- consistent priority, availability, source, freshness, and PIT semantics
  across the CLI and Streamlit;
- deterministic tests using fixture artifacts and ledgers.

### Out of scope

- MCP, HTTP, REST, or hosted API services;
- access by agents that cannot mount the repository;
- automated trade execution or unconditional buy/sell recommendations;
- fabricated consensus dispersion, historical sensitivity, or event impact;
- a second event database or a duplicate dashboard-specific pipeline;
- automatic refreshes caused by read-only CLI queries or page navigation.

## Architecture

```text
Remote sources
      |
      v
Existing event_consensus refresh pipeline
      |
      +--> append-only PIT Parquet ledgers
      |
      +--> bounded latest JSON artifact
                    |
                    v
             EventQueryService
              |      |      |
              |      |      +--> Python callers / notebooks
              |      +---------> repo-local CLI JSON
              +----------------> Streamlit page
```

`EventQueryService` is the only place that implements read-side filtering,
ranking, availability annotations, and event dossier assembly. Streamlit must
not reimplement those rules. The CLI must not import Streamlit.

The query core accepts explicit artifact and ledger paths so tests and sibling
repos can use fixtures without relying on global process state. Production
defaults continue to come from `event_consensus.config`.

## Read models

The query core exposes seven read models.

### Capabilities

Describes the contract before an agent asks for data:

- schema and query-contract versions;
- supported commands and filters;
- available countries, event families, and observed date range;
- available analysis components;
- artifact generation time, semantic content hash, and source-health summary.

Capabilities are derived from the loaded artifact and supported query code.
They are not a manually maintained list that can drift from reality.

### Brief

Supports the opening A workflow: a one- to two-minute view of what matters
next.

Default behavior:

- horizon: 48 hours;
- countries: all countries present in the artifact;
- include high and medium display priorities;
- sort first by provider-high override, then descriptive score, then scheduled
  time;
- include the top events plus an explicit count of hidden lower-priority
  events.

Each result explains why it was selected and includes time to release,
consensus availability, verification status, source confidence, and applicable
scenario or asset lenses. Provider importance `1` always produces high display
priority, regardless of date proximity or the composite score.

### Event list

Returns the bounded event timeline with filters for:

- start and end timestamps;
- country;
- event family;
- display priority;
- checkpoint stage;
- verification status;
- released versus upcoming state.

This model powers the grouped 7-14 day Streamlit timeline and gives agents a
deterministic way to discover an `event_id`.

### Research dossier

Supports the B workflow for one `event_id`. It combines:

- normalized event identity and schedule;
- forecast, previous, revised previous, and actual observations;
- consensus revision history;
- explainable score components;
- official component contracts and available observations;
- current cross-asset quote context;
- scenario templates and invalidation conditions;
- source URLs, retrieval timestamps, and verification state.

Current cross-asset quotes must be labelled as market context, not as proof of
event-specific pricing. Event-specific beta or sensitivity remains unavailable
until a valid historical event-study dataset exists.

### History

Returns the point-in-time observations for one event in chronological order.
The response preserves snapshot IDs, observation signatures, trigger types,
checkpoint stages, and retrieval timestamps. It never rewrites historical
observations into the latest value.

### Postmortem

Supports the C workflow after release. It contains:

- the locked pre-release consensus;
- official or third-party actual and its verification state;
- revised previous value where available;
- raw and standardized surprise only when the required history exists;
- captured post-release quote checkpoints where available;
- explicit unavailable reasons for unsupported event-study horizons.

V1 may return a partial postmortem. It must not infer absent market reactions.
Later event-study outputs can extend this model without changing the CLI
command.

### Health

Returns artifact freshness, source status, record counts, coverage caveats, and
fallback use. This allows an agent to decide whether a brief or dossier is
trustworthy before using it.

## CLI contract

The existing command remains the single entry point:

```bash
event-consensus query capabilities
event-consensus query brief --horizon-hours 48
event-consensus query list --country US --priority high
event-consensus query research --event-id <event_id>
event-consensus query history --event-id <event_id>
event-consensus query postmortem --event-id <event_id>
event-consensus query health
```

Query commands:

- are offline and read-only;
- emit one JSON document to stdout;
- send warnings and diagnostics to stderr;
- use exit code `0` for a valid response, including a valid empty result;
- use a non-zero exit code for invalid arguments, unreadable contracts, or
  missing requested event IDs;
- accept explicit artifact and ledger path overrides for tests and advanced
  local use.

Refresh remains explicit:

```bash
event-consensus refresh [existing refresh options]
```

Existing root-level refresh invocations remain accepted during migration so
scheduled workflows do not break. Their behavior and output summary remain
unchanged.

## JSON response envelope

Every query emits the same top-level envelope:

```json
{
  "query_contract_version": "1.0",
  "query": "brief",
  "generated_at_utc": "...",
  "data_as_of_utc": "...",
  "artifact_schema_version": "1.0",
  "content_hash": "...",
  "status": "ready",
  "source_health_summary": {},
  "filters": {},
  "data": {},
  "warnings": []
}
```

`generated_at_utc` is when the query response was assembled.
`data_as_of_utc` is the latest relevant observation time, not the query time.
The content hash comes from the underlying artifact.

Missing values remain JSON `null`. Decision-relevant missing fields receive a
companion availability record with one of:

- `not_released`;
- `not_provided`;
- `source_unavailable`;
- `unsupported`;
- `insufficient_history`;
- `not_applicable`.

The query layer may explain missing data but must not mutate the stored
artifact to do so.

## Streamlit product design

The Events & Consensus page remains a standalone sibling of ETF Monitor and
Market Regime. It opens in Briefing and offers three internal research modes:

### Briefing

- a "What matters in the next 48 hours" summary;
- the highest-priority events with countdowns and selection reasons;
- grouped daily timeline for the wider 7-14 day window;
- visible consensus, verification, and source-confidence badges;
- operational health moved below decision-relevant information.

### Event Research

- plain-language description of what the event measures;
- consensus versus prior and revision history;
- visible score decomposition instead of an unexplained total;
- official components, scenarios, market context, and evidence lineage;
- unavailable states that explain why a field is absent.

### Post-release Review

- released events ordered by recency and importance;
- pre-release consensus versus actual and revised prior;
- verification and observation timing;
- available post-release checkpoints;
- sample size and sufficiency warnings before any historical conclusion.

The page calls `EventQueryService` directly. UI formatting, bilingual labels,
layout, and chart construction remain in the Streamlit package.

## Priority and evidence semantics

Priority and trust are separate dimensions.

- Provider importance `1` is always high display priority.
- Other events use the existing descriptive risk/catalyst score thresholds.
- Score decomposition remains visible and explainable.
- Source quality, freshness, verification, and missingness do not silently
  lower or raise provider importance.
- A high-priority event can still have weak evidence; the UI and CLI must show
  both facts.

Scenario templates are conditional research aids. They must retain their
invalidation conditions and must not be presented as predictions.

## Agent discoverability

The implementation adds a concise section to the repository agent guidance and
Asia Markets operating manual. It tells local agents:

- which command to run first (`event-consensus query capabilities`);
- that query commands are read-only;
- how to obtain an event ID;
- how to inspect source health and PIT history;
- not to scrape Streamlit or bypass the query core with ad hoc scoring;
- that refresh is an explicit mutation.

The CLI's `--help` output is part of the public local contract and receives
contract tests.

## Failure behavior

- Missing latest artifact: fail with a clear non-zero exit and path.
- Invalid artifact schema: fail closed; do not return partially interpreted
  decision data.
- Empty valid result: return status `ready`, an empty `data` collection, and
  exit `0`.
- Missing optional ledger: return the current artifact-backed response plus a
  structured warning.
- Missing requested event ID: return a non-zero exit with nearby discovery
  guidance, not an arbitrary event.
- Stale or degraded sources: return data with explicit health warnings when the
  existing artifact is still valid.
- Streamlit query failure: show the last valid page state when available and a
  visible diagnostic; do not trigger a refresh automatically.

## Testing

### Query-core tests

- filtering, ranking, and provider importance override;
- deterministic ordering;
- PIT history preservation;
- dossier joins across artifact sections;
- missing-value reason classification;
- partial postmortem behavior;
- source-health and freshness propagation;
- no network calls during every query method.

### CLI contract tests

- JSON-only stdout;
- diagnostics confined to stderr;
- exit codes for valid empty, missing event, missing artifact, and invalid
  schema cases;
- path overrides;
- backward-compatible legacy refresh invocation;
- complete and accurate `--help` text.

### Streamlit tests

- all three modes consume the query core;
- Briefing is the default;
- provider importance `1` remains visibly high;
- no raw `nan`, `None`, or `NaT` reaches the UI;
- operational health does not replace the last valid decision view;
- navigation and page load remain read-only.

### Integration validation

- run queries against the current local artifact;
- compare CLI brief results with the Streamlit Briefing ordering;
- confirm one event's research, history, and postmortem share the same
  `event_id`, content hash, and PIT observations;
- run the existing focused event-consensus and Asia Markets test suites.

## Delivery sequence

1. Introduce the pure query core and response envelope.
2. Add the read-only CLI commands while preserving refresh compatibility.
3. Document agent discovery and validate live local query output.
4. Refactor the standalone Streamlit page to consume the query core.
5. Add Briefing, Event Research, and Post-release Review modes.
6. Add historical reaction fields only when a separate PIT-safe event-study
   dataset passes its own data-quality gate.

The first five steps are one implementation program because they establish one
shared contract. Step six is intentionally deferred data research, not a UI
placeholder disguised as evidence.

## Success criteria

- A local coding agent can discover and retrieve the next 48-hour brief with
  one documented command.
- The same event has consistent priority, values, provenance, and PIT history
  in CLI and Streamlit.
- Every query is read-only and makes zero remote calls.
- Existing scheduled refresh behavior remains operational.
- The page supports briefing, research, and review without returning event
  content to the ETF Monitor.
- Missing or insufficient evidence is explicit rather than imputed.
- No duplicate event pipeline or agent-only data store is introduced.
