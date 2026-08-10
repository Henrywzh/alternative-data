# Consensus Reverse Engineering

Status: 2026-08-10.  Instead of comparing our EPS with consensus as a single
number, this layer reverses the Street's FY2026 consensus net profit into the
operating assumptions it implies (margin, RASK, CASK) and compares those with
our own model.  The output is the assumption gap, not a forecast.

## Reverse path

```
consensus net profit
  -> / (1 - effective tax rate)       implied PBT
  -> + finance - non-operating net    implied operating profit
  -> implied operating margin on consensus revenue
  -> implied RASK = (consensus revenue - non-passenger) / our ASK
  -> implied CASK = (consensus revenue - implied op profit) / our ASK
```

Implied RASK/CASK use **our** FY2026 ASK, so the implied values are what
Street's revenue/profit implies under our capacity assumptions - the direct
assumption gap.  Tax rate prefers the interim (1H2025) anchor with a 0-60%
guard; below-operating anchors fall back from annual to interim where the
annual statement is a scanned image (Spring/Juneyao).

## FY2026 result (RMB per ASK)

| Company | Street implied RASK | Model RASK | RASK gap | Street net margin | Model margin gap |
|---|---:|---:|---:|---:|---:|
| Spring Airlines | 0.350 | 0.339 | +3.2% | 8.27% | -5.2pp |
| Juneyao Airlines | 0.419 | 0.375 | **+11.8%** | 3.66% | -8.8pp |
| China Southern | 0.440 | 0.405 | +8.4% | 0.35% | -9.6pp |
| China Eastern | 0.483 | 0.442 | +9.4% | 0.27% | -5.7pp |
| Air China | 0.473 | 0.421 | +12.3% | 0.14% | -5.0pp |
| Hainan Airlines | 0.453 | 0.375 | +20.8% | 2.65% | -5.2pp |

## What this says about the pair

**Juneyao is the largest pricing-assumption disagreement.**  Street's FY2026
revenue implies a RASK of 0.419 - 11.8% above our model - i.e. the market is
paying for strong pricing power from Juneyao's international capacity
recovery.  Our unit economics and yield-pressure layers do not support that
conversion (flat fleet, unproven delivery pace, hybrid cost structure).

**Spring is a margin disagreement, not a pricing one.**  Street's implied
RASK (+3.2% vs ours) is close; the gap is operating margin (-5.2pp), where
our unit-economics decomposition (CASK 0.300 vs 0.345) supports a better
outcome than Street's implied cost base.

The variant perception becomes: the market overestimates Juneyao's earnings
conversion from international recovery (implied RASK too high) while
underestimating the durability of Spring's unit-cost advantage (implied
margin too low).

## Limitations

* A-share consensus revenue/profit is a dated snapshot (2026-08-07), not a
  full broker vintage.
* Implied RASK/CASK inherit our ASK and non-passenger assumptions; they are
  conditional on the model, not independent Street unit metrics.
* Tax and below-operating anchors are FY2025/1H2025; Air China's operating
  margin reverse is blank where the annual finance anchor is missing.
