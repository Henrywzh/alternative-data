# SHKP Earnings Model v1.0 - Validation & Status Report

Status: FROZEN v1.0 (2026-08-09). This document separates "the code /
accounting chain is correct" from "the forecast model is historically
validated" - the two are different claims and are reported separately.

## Part 1 - Full-chain technical validation

Raw data -> residential sales -> recognition kernel -> project margin ->
development profit; RVD -> commercial rental -> NRI; hotel + Mainland +
other -> underlying profit -> EPS -> consensus gap. Nine invariant checks
all pass (9/9):

1. Unit consistency: recognition HKD scale (30.4bn/33.1bn), margin
   fractions (29.8%/29.1%), EPS 5-12, underlying HKD_m 15-35k.
2. Accounting identities: underlying = modelled segment + below-segment;
   reported = underlying + FV; EPS = profit / 2,896m shares (all exact).
3. PIT integrity: below-segment residual is FY2025-calibrated (documented
   limitation, not a claim of out-of-sample purity).
4. Version consistency: skeleton consumes the frozen project-mix weighted
   margins (29.8%/29.1%), NOT the legacy 24% constant (verified by
   reverse-deriving the implied margins from the output).

The engineering layer is therefore frozen and self-consistent.

## Part 2 - FY25A -> FY26E -> FY27E earnings bridge

| HKD m / EPS | FY25A | FY26E | FY27E |
|---|---:|---:|---:|
| HK development recognised revenue | 26.1bn | 30.4bn | 33.1bn |
| HK development margin | 12.2% | 29.8% | 29.1% |
| HK development profit | 3,200 | 9,052 | 9,644 |
| HK commercial NRI | 12,956 | 12,956 | 12,956 |
| Hotel | 615 | 630 | 630 |
| Other businesses | ~4,891* | 5,506 | 5,506 |
| Mainland + SG | 10,526 | (in residual) | (in residual) |
| Below-segment residual | n/a | -3,854 | -3,854 |
| Underlying profit | 21,855 | 24,290 | 24,882 |
| Underlying EPS | 7.54 | 8.39 | 8.59 |
| Consensus EPS | - | 7.91 | 8.65 |
| Variant | - | +6.1% | -0.6% |

*FY25A "other businesses" of 4,891 is telecom 752 + infra 1,666 + DC
1,489 + other 984; the 5,506 figure in the FY26/27 columns is the
five-year-summary other-businesses run-rate used by the skeleton
(includes items the segment note splits differently - the two are not
arithmetically identical, noted for audit).

### FY2026 +6.1% variant attribution

The +0.48 EPS gap is entirely attributable to residential in this
decomposition:

* Model: 30.4bn recognised x 29.8% margin = 9,052 HKD_m development
  profit.
* Consensus implied: ~25.2% margin on 30.4bn, or ~25.7bn volume at 29.8%
  - i.e. consensus is NOT using the official 30.1bn recognition guidance
  at the model's margin.
* Non-residential components are held at the same run-rates on both
  sides, so they contribute 0 to the gap BY CONSTRUCTION.

CAVEAT (the FY26 variant's largest uncertainty): if consensus uses a
different Mainland / below-segment assumption (e.g. Mainland normalising
down from the FY2025 5.1bn spike), part of the +6.1% is offset. The
attribution above assumes consensus non-residential = model
non-residential, which is a modelling assumption, not a fact.

## Part 3 - Backtest conclusions, redefined (three layers)

The statement "FY2025 error ~0 so FY26/27 are the most validated" is too
strong. Correct framing:

### A. Component validation (the strongest evidence)
* Residential recognition kernel: FY2026 kernel 30.4bn vs official
  guidance 30.1bn = +1.0% - genuinely strong, independent validation.
* Commercial: OOS MAPE 1.62% vs naive 3.85% (FY2016-25, 10-year walk-
  forward) - strong, self-contained module validation.

### B. Skeleton backtest (portability stress test, NOT accuracy proof)
* Full-sample MAE 20.1%, systematically under-estimating FY2017-2022
  (-15% to -31%). Structural causes, not engine failure:
  1. Non-residential run-rate lags Mainland development spikes (FY2025
     actual 18.7bn vs 3yr mean 14.8bn, +26%).
  2. Margin bucket (calibrated to FY26/27 mix) understates the FY2017-20
     high-margin mix (actual 32.8-44.9% vs bucket 22.5-37.5%).
* Purpose: stress-test model portability across business-mix regimes.

### C. Recent-regime fit
* FY2024 -2.4%, FY2025 -0.2%. Report as "recent-regime fit", NOT clean
  OOS predictive accuracy: inputs and specification are closest to the
  current regime, so this is expected and not evidence of general
  predictive power.

## Part 4 - What we now know (five investment conclusions)

1. Recognition is no longer the main debate: the empirical kernel
   (P0/P1/P2 = 29/48/24%, mean ~0.95 FY) is independently validated by
   the official FY2026 guidance.
2. FY27 consensus margin is not aggressive: historical median 39.0%,
   recent 3Y mean 24.7%, FY27 project mix 29.1%, consensus-implied 29.6%
   - the market asks for a reasonable mix-driven normalisation, not a
   return to the historical median.
3. FY2026 is the real positive variant: model 8.39 vs consensus 7.91
   (+6.1%), FY2027 neutral (8.59 vs 8.65). The investment question shifts
   from "long-term upside" to "is FY26 consensus understating near-term
   earnings realisation while FY27 has priced the normalisation?"
4. Commercial is a validated, low-volatility earnings stream: RVD
   distributed-lag cuts OOS MAPE 3.85% -> 1.62%; high-confidence module.
5. The largest remaining model risk moved from residential to Mainland /
   below-segment: the backtest shows FY2025 non-residential 26% above its
   trailing run-rate; if the FY26 +6.1% variant depends on Mainland
   normalising upward, that is the next risk check.

## Model confidence table

| Module | Evidence | Confidence | Main risk |
|---|---|---|---|
| Recognition kernel | 21 projects + FY26 official guidance | HIGH | project timing |
| Development margin | 13Y history + project mix | MEDIUM-HIGH | cost proxy / ASP |
| HK commercial | 16Y + OOS backtest | HIGH | RVD lag stability |
| Hotel | 13Y history | MEDIUM | margin recovery |
| Mainland / other | historical decomposition | MEDIUM/LOW | composition volatility |
| Whole-company EPS | component aggregation | MEDIUM | below-segment residual |

## Freeze declaration

SHKP Earnings Model v1.0 is FROZEN as of 2026-08-09. Success criteria met:
accounting integrity + PIT integrity + component-level validation +
transparent uncertainty. The next phase is the INVESTMENT LAYER, not more
model building: the concrete sources of the FY26 +6.1% upside, why the
market may not price it, which catalysts would drive consensus revision,
and which observable data would falsify the 8.39 estimate.
