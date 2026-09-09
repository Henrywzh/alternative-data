# Global Market Regime V2 Design

## Objective

Turn the existing Streamlit-only Global Market Regime page from a
collection of source charts into a decision-first defensive radar.
Within ten seconds, the reader should understand:

1. the current aggregate state;
2. which fresh indicators caused it;
3. how far each indicator is from its next threshold;
4. whether a breach has persisted long enough to confirm;
5. what changed recently and what would trigger the next alert.

V2 does not add a black-box risk score, trading recommendation, paid
data source or Cloudflare surface.

## Product hierarchy

### 1. Today's assessment

The first screen starts with one aggregate-state banner, not five equal
source cards. It shows:

- aggregate state;
- active driver count;
- oldest-to-newest observation-date range across fresh headline drivers;
- freshness/alert eligibility;
- one generated explanation naming every non-normal fresh driver.

Stale and unavailable indicators remain visible below, but never
contribute to the aggregate state or explanation.

### 2. Threshold monitor

The five current headline conditions remain:

- Brent crude;
- US 10-year Treasury yield;
- Polymarket next-FOMC hike probability;
- Atlanta Fed probability that the selected three-month average SOFR
  window finishes above the current target range;
- shared-date high-yield OAS and VIX stress.

Each card shows the current value, state, observation date, threshold,
distance to threshold and persistence progress. Cards use responsive
one/two/three-column layouts and must not truncate titles or state
labels.

The Atlanta and Polymarket cards retain explicit wording that they are
different concepts and neither is CME FedWatch.

### 3. Evidence panels

- **Oil and duration:** raw levels with threshold lines and state
  transition markers.
- **Policy:** separate Atlanta SOFR-distribution and Polymarket
  next-meeting panels. The Polymarket panel shows the meeting date and
  prior-observation and seven-calendar-day probability changes. The
  latter compares the latest value with the last observation on or
  before `latest date - 7 days`.
- **Credit and volatility:** the primary view plots the two 20-day
  z-scores and the +1 threshold used by the rule. Raw HY OAS and VIX
  levels are a secondary view.
- **Positioning:** latest CFTC table plus a historical-percentile view
  for the selected contract.
- **Cross asset:** selectable rebased-to-100 performance and
  5D/20D/60D return table. Raw index levels are not overlaid across
  incomparable scales.

### 4. Recent changes and alerts

Derive a compact transition log from condition-state history. It shows
the latest ten changes with indicator, date, prior state, new state,
value and source observation date.

The page also shows:

- whether the current snapshot is alert-eligible;
- the last successful alert timestamp from the persisted alert state;
- the next threshold or persistence condition required for each
  indicator.

It does not claim an email was delivered unless `last_sent_at` exists
in the persisted alert state.

## Data and ownership

Signal definitions remain in `src/global_market_regime/`; Streamlit
does not duplicate threshold or state logic.

The normalized and derived run keeps the existing shared `run_id`.
The artifact builder exposes additional presentation datasets:

- `regime_summary`;
- `threshold_monitor`;
- `condition_state_history`;
- `state_transition_history`;
- `credit_vix_signal_history`;
- `cross_asset_returns`;
- `alert_status`.

Threshold metadata is declared once in the domain package and reused by
the pipeline, artifact builder and tests. It includes units,
confirmation requirements and human-readable rule labels. For the
credit/VIX rule, distance is based on the minimum of the two z-scores,
and confirmation still requires both z-scores plus both positive
five-day changes.

Interactive reindexing is performed from artifact-contained price
history in a pure, tested helper because its baseline depends on the
reader's selected window. No network request runs during navigation.

## Aggregate-state semantics

The aggregate remains transparent: it is the highest-severity state
among fresh, available headline conditions. V2 does not average the
conditions into a score.

The summary explanation lists all indicators tied at the highest
severity and separately counts other non-normal drivers. A stale
Escalating row cannot make the current aggregate Escalating.

## Error and degraded states

- Mixed run IDs make the artifact partial/degraded.
- A missing threshold definition makes that card unavailable rather
  than silently showing a zero distance.
- Insufficient history suppresses one-day/one-week changes and
  transition rows rather than filling them with zero.
- An unavailable alert-state file shows “No delivery history
  available”; it does not affect market-data health.
- If cross-asset data is absent, the rest of the regime page remains
  usable.

## Visual rules

Use the existing Asia Markets palette and card language. State color is
reserved for state meaning:

- neutral/blue: Normal;
- amber: Watch;
- red: Confirmed/Escalating;
- green: Improving;
- grey: stale/unavailable.

Chart color continues to identify data series, not state. Every chart
shows its date range, units and source meaning. The overview stays
compact; detailed evidence remains on the Market Regime page.

## Testing and acceptance

Required automated coverage:

- stale states cannot affect aggregate state or explanations;
- every threshold card calculates distance and units correctly;
- oil's four-of-five rule and ordinary two-observation confirmation
  display the correct progress;
- Polymarket one-day/one-week changes use actual outcome-token history;
- credit/VIX primary chart uses z-scores on shared dates;
- cross-asset reindexing starts at exactly 100 for every selected
  series;
- state transitions exclude unchanged rows;
- missing alert history is non-fatal;
- mixed-run artifact remains degraded;
- English and Chinese AppTest runs render with no exceptions and no
  truncated metric-card text at the supported desktop layout.

Acceptance also requires `py_compile`, all global-market-regime tests,
the Asia Markets Streamlit contracts, wiring tests and a real browser
check at the current local host.

## Deferred work

V3 may add real yields, curve spreads, IG credit, dollar, gold,
liquidity balances and broader market breadth. Those inputs require
their own source and signal review and are not part of this V2.

## V2.1 — Breadth, replay and alert calibration

The aggregate headline remains the highest-severity fresh state, but it is
qualified by risk breadth across three transparent domains:

- inflation/supply: Brent;
- rates/policy: US 10-year yield, Atlanta Fed SOFR probability and
  Polymarket next-meeting hike odds;
- financial stress: the same-date HY OAS/VIX stress rule.

Breadth is `none`, `narrow`, `broadening` or `broad stress` according to the
number of active domains. A formal defensive alert requires at least two
domains at Confirmed or worse, except that the financial-stress domain may
qualify alone. The scheduled workflow remains preview-only until historical
validation has been reviewed.

The Streamlit validation section exposes signal episodes, descriptive
5/20/60-session post-transition returns and threshold sensitivity. It never
turns those summaries into a black-box score or causal claim, and sample size
must remain visible.
