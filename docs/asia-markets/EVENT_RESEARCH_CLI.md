# Local Event Research CLI

The event research CLI is the machine-readable access point for the private
Events & Consensus data. It is intended for Codex, Claude, notebooks and other
coding agents that have this repository mounted locally.

It reads the same point-in-time artifact and append-only ledgers used by the
Streamlit page. It does not create a second event database and it does not
scrape the page.

## First discovery

Run this first:

```bash
PYTHONPATH=src python -m event_consensus.cli query capabilities
```

The response describes the query contract, available countries and event
families, scheduled date range, artifact sections, source-health summary and
content hash.

## Query commands

All query commands are offline, read-only and emit one JSON document to
stdout. Warnings and errors go to stderr. A query never calls a source adapter
and never appends to a PIT ledger.

```bash
# A: what matters next
PYTHONPATH=src python -m event_consensus.cli query brief --horizon-hours 48

# Discover a deterministic event list and event_id
PYTHONPATH=src python -m event_consensus.cli query list \
  --countries US --priority high

# B: inspect one event
PYTHONPATH=src python -m event_consensus.cli query research \
  --event-id tradingview:example

# Inspect point-in-time forecast/prior/actual snapshots
PYTHONPATH=src python -m event_consensus.cli query history \
  --event-id tradingview:example

# C: compare the release with its locked pre-release context
PYTHONPATH=src python -m event_consensus.cli query postmortem \
  --event-id tradingview:example

# Check whether the artifact is fresh and source coverage is degraded
PYTHONPATH=src python -m event_consensus.cli query health
```

The command accepts `--artifact-path`, `--event-ledger-path`,
`--quote-ledger-path` and `--component-ledger-path` for fixture or alternate
local snapshots. `--format json` is the only supported format in V1.

## Response contract

Every response has this envelope:

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

`generated_at_utc` is the time the local query ran. `data_as_of_utc` is the
latest relevant observation time. `content_hash` identifies the decision-
relevant artifact content.

The `brief` and `list` models decorate event rows with:

- `priority`: `high`, `medium`, `low` or `unknown`;
- `priority_reason`: `provider_importance_1`, `risk_score` or
  `score_unavailable`;
- `released`: whether the scheduled time has passed at query time;
- `availability`: field-level states for forecast, actual and market reaction.

Provider importance `1` always maps to `high`, even when the descriptive risk
score is below the high threshold. Priority and evidence quality are separate:
a high-priority event may still have an unverified or degraded source.

## Missing evidence

Missing values remain JSON `null`. Decision-relevant availability states are
explicit:

- `not_released`: the event has not published an actual;
- `not_provided`: the source did not provide the field;
- `source_unavailable`: an optional source or ledger could not be read;
- `unsupported`: the repository does not have the required coverage;
- `insufficient_history`: a historical reaction cannot be estimated safely;
- `not_applicable`: the field does not apply to the event.

An `insufficient_history` postmortem must not be converted into a reaction
chart, event beta or trade recommendation.

## PIT and source rules

Use `research` for the current event dossier and `history` when the question
depends on what was known at an earlier time. History preserves snapshot IDs,
observation signatures, trigger types, checkpoint stages and retrieval times;
do not collapse it into the latest value for a backtest.

The current quote collection is market context. It is not an event-specific
implied move unless a separate PIT-safe event-study artifact explicitly says
so. TradingView calendar values are third-party until an official adapter
confirms the actual. The CLI preserves source URLs and verification fields so
an agent can cite the evidence it used.

## Refresh boundary

Reading is separate from collection. Only an explicit refresh may contact
remote sources or append a manual observation:

```bash
PYTHONPATH=src python -m event_consensus.cli refresh --trigger manual
```

Legacy root-level refresh flags remain accepted for scheduled workflows:

```bash
PYTHONPATH=src python -m event_consensus.cli --trigger scheduled
```

An agent should check `health` before using a brief or dossier and should
include source-health warnings in its answer when the artifact is degraded.
