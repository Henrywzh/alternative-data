# Airline Earnings Sensitivity Surface

Status: 2026-08-10.  Tests the robustness of the forward H1-2026 view to
simultaneous shocks in the three key unobservables: passenger yield (RASK),
jet fuel and USD/CNY FX.

## Construction

For each carrier, base H1-2026 net income (walk-forward integrated model)
is shocked across a 3x3x3 grid:

```
NetIncome(yield, fuel, fx)
  = base + yield x passenger revenue
         - fuel x (fuel-cost share x operating cost)
         +/- fx x (structural USD-cost share x revenue)
```

Shocks: yield -3/0/+3%, fuel -5/0/+5%, FX -3/0/+3%.  Fuel-cost share from
the unit-economics layer; FX exposure is a structural estimate by carrier
type (Big-3 international carriers ~45%, LCC ~30%).  Mechanical surface,
excludes hedging, pass-through, surcharge recovery and demand response.
Machine-readable output: `airline_earnings_sensitivity.csv` (162 rows,
6 carriers x 27 cells).

## Spring H1-2026 EPS surface (FX = 0)

| | Fuel -5% | Fuel 0% | Fuel +5% |
|---|---:|---:|---:|
| Yield -3% | 1.41 | 1.20 | 0.99 |
| Yield 0% | 2.05 | **1.84** | 1.63 |
| Yield +3% | 2.70 | 2.49 | 2.28 |

Worst case (yield -3 / fuel +5 / FX +3): EPS **0.88** - positive but
marginal.  Best case: 2.81.

## Juneyao H1-2026 EPS surface (FX = 0)

| | Fuel -5% | Fuel 0% | Fuel +5% |
|---|---:|---:|---:|
| Yield -3% | 0.03 | **-0.05** | -0.14 |
| Yield 0% | 0.33 | 0.24 | 0.16 |
| Yield +3% | 0.63 | 0.54 | 0.45 |

Juneyao turns NEGATIVE at yield -3% even with flat fuel.

## Thesis robustness answer

The Spring - Juneyao EPS spread is **positive in all 27 combinations**
(min 1.07, max 2.13, median 1.60).  Even the worst joint shock (yield -3 /
fuel +5 / FX +3) leaves a 1.07 EPS spread in Spring's favour.  This is a
robust variant: the pair does not depend on fuel or yield staying benign -
Spring's unit-cost advantage (CASK 0.300 vs 0.345) protects the spread
across the shock surface, while Juneyao's higher cost base converts yield
softness directly into losses.

## Limitations

* vs_consensus_status uses a 1.0 RMB EPS threshold as a simple marker, not
  Street consensus; the true beat/miss threshold differs by carrier.
* Fuel impact ignores hedging and surcharge pass-through (both can mute the
  fuel leg); FX ignores natural hedges and local-currency revenue.
* Yield impact assumes RASK scales linearly with passenger revenue and
  ignores volume response to pricing.
