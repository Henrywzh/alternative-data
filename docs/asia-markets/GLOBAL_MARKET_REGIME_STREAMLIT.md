# Global Market Regime — Streamlit contract

## Purpose

This page is a defensive market-conditions radar inside the private Asia
Markets Streamlit terminal. It answers whether oil, long rates, policy
expectations, credit and volatility are moving into a persistent stress
state. It is not a trading recommendation, allocation model or copy of
CME FedWatch.

## Data flow

```text
FRED + Atlanta Fed + Polymarket + CFTC
                  |
          normalized Parquet
                  |
      threshold/state derivations
                  |
       one run-scoped artifact
                  |
       Asia Markets Streamlit
```

The existing market-monitor index history supplies cross-asset context.
The regime pipeline does not create a second price database.

## Decision-first presentation

The Streamlit page reads one run-scoped artifact and presents it in this
order:

1. current aggregate state followed by a four-reading daily brief;
2. the persisted alert decision, new transition count, confirmed-domain
   breadth, evaluation timestamp and preview/defensive mode;
3. three domain cards for inflation/supply, rates/policy and financial stress;
4. one threshold card per condition, including distance, confirmation
   progress, freshness and the declared rule;
5. threshold history with state-transition markers;
6. separate Atlanta Fed and Polymarket policy-expectation panels;
7. same-date credit/VIX z-score evidence, with raw levels behind an
   expander;
8. CFTC latest positioning plus contract-level historical percentile;
9. cross-asset prices rebased to 100 plus exact 1/5/20-session returns;
10. historical signal episodes, post-event reactions and threshold
   sensitivity;
11. recent true state transitions and source health.

The artifact owns the calculations. Streamlit only filters, localizes and
renders these presentation datasets:

- `regime_summary`
- `domain_summary`
- `threshold_monitor`
- `condition_state_history`
- `state_transition_history`
- `credit_vix_signal_history`
- `cot_history`
- `cross_asset_returns`
- `signal_episodes`
- `threshold_sensitivity`
- `event_forward_returns`
- `event_forward_summary`
- `alert_status`

## Source semantics

- FRED supplies Brent, US Treasury yields, VIX, high-yield OAS, WTI and
  the broad advanced-economy dollar index. The committed history is the
  latest revised FRED vintage available at fetch time, not an ALFRED
  point-in-time vintage panel.
- Atlanta Fed Market Probability Tracker supplies option-implied
  distributions for a three-month average SOFR window. It is not a
  next-meeting probability.
- Polymarket supplies prices for the next open Fed Decision event. Each
  hike, hold and cut outcome uses its own CLOB token history; current
  snapshot prices are never backfilled into earlier dates. V1 retains only
  the currently selected open event and does not yet form a continuous
  archive across past meetings.
- CFTC Commitments of Traders is weekly. Financial futures use
  leveraged-money positioning; commodity futures use managed-money
  positioning.

## State and freshness rules

The state sequence is `Normal`, `Watch`, `Confirmed`, `Escalating` and
`Improving`. Persistence is measured in valid observations rather than
calendar days. A stale or unavailable condition remains visible on the
page but is excluded from the aggregate state and cannot create an
alert transition.

Every artifact dataset must resolve to the same full-run ID. A mixed-run
artifact is marked partial/degraded. The workflow runs at 22:30 UTC on
weekdays, after the US cash close in both daylight-saving and standard
time.

The shared cross-asset price context has its own coverage and freshness row;
it cannot inherit a healthy status from the macro sources. Persisted Parquet
snapshots are checked against their lineage SHA-256 before use, and alert state
plus generated JSON files use atomic replacement. Source errors are bounded
and credentials are redacted before they reach logs, lineage-facing status or
artifacts. `Recent` is a distinct freshness label for observations still
inside the declared cadence allowance but older than the immediately prior
session.

## Alerts

The scheduled V2.1 workflow is deliberately in `preview` mode. It records
fresh component transitions and the resulting breadth decision in
`data/derived/global_market_regime/alert_state.json`, but sends no automatic
email. The artifact publishes that persisted decision to Streamlit as one of
four explicit states: `quiet`, `component_preview`, `defensive_eligible` or
`unavailable`. Streamlit localizes and renders the decision but never
recomputes alert policy. Missing or run-mismatched evaluation state fails
closed as `unavailable`; the state must carry the same `last_run_id` as the
artifact datasets and a valid evaluation timestamp. Preview mode is also
incompatible with the manual force-send flag, so it cannot enter the email
path.

A future `defensive` mode may send only when a fresh transition occurs and
either (a) at least two domains are Confirmed or worse, or (b) the financial
stress domain alone is Confirmed or worse. A single oil or rates/policy
transition remains informational. Notification failure is isolated from
ingestion and artifact refresh.

## Historical validation

Validation is descriptive rather than causal or point-in-time. In particular,
FRED replay uses today's latest revised history, so it must not be interpreted
as evidence of what a live observer knew on each historical date. Non-Normal observations are
collapsed into auditable episodes, with source gaps longer than seven calendar
days starting a new episode. Only the first Confirmed-or-worse entry in each
episode is aligned to each market's first trading session strictly after the
event date, then measured over 5, 20 and 60 sessions. Every result keeps its
event count visible. Threshold
sensitivity reports raw observation hits and distinct hit episodes under
alternative levels; it does not silently redefine the live rule.

## Verification

```bash
PYTHONPATH=src python -m pytest tests/global_market_regime -q
python -m py_compile \
  src/global_market_regime/*.py \
  apps/asia-markets-dashboard/scripts/build_global_market_regime_artifact.py \
  apps/asia-markets-streamlit/app.py
```
