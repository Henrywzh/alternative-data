# Airline Long/Short Underwriting Card

Status: 2026-08-10.  This is the capstone of the equity-underwriting upgrade:
it integrates the seven research layers into one execution-oriented view on
the Spring Airlines long / Juneyao Airlines short pair.  Research construct
only - not an approved live order.

## v3 NCI / operating-contribution fix (2026-08-10)

China Southern's v3 model previously reported a 588% model-vs-consensus
gap (model 720 USD mn vs consensus 105 USD mn).  Root cause was not the
NCI proration itself (Southern's FY2025 minority-interest share is a
genuine 68.1%: NCI 1,828m on net income 2,685m, reconciled to zero error)
but the forward operating-contribution leg: v3 used
`forecast revenue - forecast operating cost` (gross margin), while
Southern's FY2025 gross margin of 18,476m collapses to only 3,967m of
reported operating profit once period expenses (surtaxes, selling, G&A,
R&D) are deducted.  The ~14.5bn expense wedge inflated the forward
waterfall and, after the 68% NCI proration, still left an implausible
attributable profit.

Fix: when an issuer discloses a positive FY2025 reported operating profit,
the forward operating contribution is now anchored to that reported
operating profit scaled with forecast revenue
(`forward_operating_contribution_method = reported_operating_profit_revenue_scaled`).
Loss-year carriers (Eastern, Air China) keep the gross-margin proxy so the
existing regime-flip consensus guard still triggers.  After the fix:

| Carrier | Before (model vs consensus) | After |
|---|---|---|
| China Southern | +588% (gross-margin wedge) | -51% (conservative, comparable) |
| Hainan Airlines | +110% | -12% |

The change propagates to the H1-2026 validation playbook and the
post-earnings tracker; all other carriers are unchanged.

## The thesis in one paragraph

The market overestimates the earnings conversion from Juneyao's
international capacity recovery (its price implies FY26 EPS 0.83, +93% vs
Street consensus and +70% vs our model; Street's own revenue implies a RASK
11.8% above ours) while underestimating the durability of Spring's unit-cost
advantage (CASK 0.300 vs 0.345; non-fuel CASK 0.199 vs 0.235; fuel shares
nearly equal at ~33%, so the advantage is operational, not fuel).  The H1-2026
reports (2026-08-29/31) are the catalyst that tests this.

## Evidence stack (layer by layer)

| Layer | Spring vs Juneyao | File |
|---|---|---|
| Unit economics | CASK 0.300 vs 0.345 (+14.7%), unit profit +0.039 vs +0.030 | `airline_unit_economics.csv` |
| Yield pressure | validation limited (2025 only +0.66); direction modifier | `airline_yield_pressure_index.csv` |
| Capacity pipeline | ASK +14.7% vs +0.9%; 4 routes/56wk vs 2/28; fleet net add +4 vs +1 | `airline_capacity_pipeline.csv` |
| Consensus reverse | Street implies RASK +3.2% (Spring) vs +11.8% (Juneyao) | `airline_consensus_reverse.csv` |
| 3D sensitivity | Pair spread positive in 27/27 combos (min 1.07, med 1.60) | `airline_earnings_sensitivity.csv` |
| Valuation | Spring implied EPS +42% vs consensus; Juneyao +93% | `airline_valuation_snapshot.csv` |
| Trade construction | beta hedge 0.63, 0.5% NAV -> 3.5% gross, surprise >=15.6pp | `airline_trade_construction.csv` |

## Execution parameters

* Direction: long Spring (601021.SH) / short Juneyao (603885.SH)
* Beta hedge: short 0.63 units of Juneyao per unit of Spring (mechanical
  beta); residual factor exposures are labelled (size gap +0.62 log,
  momentum gap +2.8pp 3m, volatility gap -6.1pp - Spring is smaller and
  less volatile, so the pair carries a positive size tilt and negative
  volatility tilt)
* Sizing: 0.5% NAV loss budget over the direction-aware drawdown (~14.2%)
  -> ~3.5% gross notional; 0.25%/1.00% variants available
* Catalyst: 2026-08-29 (Juneyao) / 2026-08-31 (Spring) interim reports
* Entry trigger: realized long-minus-short profit surprise >= 15.6pp AND
  revenue surprise >= 3.2pp vs the pre-event forecast, plus a fresh
  revision signal, plus non-negative post-result valuation lower bound

## Why this is robust (not fragile)

The 3D sensitivity surface answers the fragility question directly: even at
the worst joint shock (yield -3%, fuel +5%, FX +3%), Spring keeps positive
EPS (0.88) while Juneyao turns negative at yield -3%.  The pair spread is
positive in all 27 combinations (min 1.07, median 1.60).  The trade does not
depend on fuel or yield staying benign.

## Invalidation

* Either report misses the surprise threshold (profit gap < 15.6pp or
  revenue gap < 3.2pp)
* Post-result consensus revisions stay no_signal or mixed (no long-up /
  short-down confirmation)
* P/B or P/S valuation direction remains conflicted after the prints
* Direction-aware drawdown breaches the approved loss budget

## Remaining gates before execution

* Borrow availability/cost for the Juneyao short is not established (free
  data does not provide locatable borrow)
* P/B valuation conflict (median-P/B diagnostic disagreed with the
  mechanical long-Spring direction) must be reconciled
* Final sizing and beta-hedge ratio re-estimated after the reports

## How the three projects unify

This card is the same framework as MTR (passenger + property pipeline ->
revenue/EPS) and SHKP (project launch -> sales -> recognition -> EPS):

    capacity -> traffic -> yield -> RASK-CASK -> EPS -> consensus -> valuation -> trade

Only the transmission differs: airlines use operating KPI -> unit economics,
MTR uses farebox + property pipeline, SHKP uses project launch -> handover.
The underwriting layer (what is priced, which assumption is wrong, how much
it changes earnings, what invalidates the trade) is now present in all three.
