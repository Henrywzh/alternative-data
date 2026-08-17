# 2023 Backtest Error Autopsy: Why Was 2023 So Bad?

Status: 2026-08-10.  Research note answering: why did the flat-yield
backtest error blow up in 2023 (-16% to -32% for the pair carriers)?

## TL;DR

The flat-ASK model assumes yield (rev/ASK) is unchanged from the prior
year.  2023 was a regime-transition year in which rev/ASK moved
dramatically - in OPPOSITE directions for LCCs vs the big three.  The
error is not a model bug; it is the flat-yield assumption failing exactly
where the market regime changed.  And critically: 2022 was the abnormal
year, not 2023.

## Mechanism (verified)

Flat-ASK predicts revenue = ASK x prior-year rev/ASK.  So the error is
mechanically equal to the actual rev/ASK change:

    error = 1/(1 + revASK_growth) - 1

Every 2023 large-error row matches this identity exactly (checked across
all carriers/years).  The model never has a chance: it holds yield flat,
2023 yield moved.

## The actual 2023 yield moves (FY, rev/ASK in RMB cents per ASK)

| Carrier | 2022 rev/ASK | 2023 rev/ASK | 2023 rev/ASK chg | 2023 model error | 2019 baseline |
|---|---|---|---|---|---|
| Spring Airlines | 27.57 | 37.79 | **+37.1%** | **-27.0%** | 33.87 |
| Juneyao Airlines | 35.39 | 42.09 | **+18.9%** | **-15.9%** | 41.06 |
| Air China | 54.99 | 48.24 | **-12.3%** | **+14.0%** | 47.44 |
| China Southern | 56.57 | 50.57 | **-10.6%** | **+11.9%** | 44.86 |
| China Eastern | 48.14 | 46.45 | **-3.5%** | +3.7% | 44.74 |
| Hainan Airlines | 46.17 | 46.71 | +1.2% | -1.2% | 41.52 |

Key observation: LCC yield exploded UP (+19% to +37%), the big three
yield fell (-4% to -12%).  One flat-yield model cannot be right for both.

## Why 2022 was abnormal (the real culprit)

2022 was the deepest COVID year: lockdowns, mass flight cancellations.
ASK was slashed so hard that the remaining seats priced at scarcity
premiums:

- Big three 2022 rev/ASK: 48-57 cents vs 2019 baseline 44-47 cents -
  yield was ABOVE normal because supply collapsed faster than demand.
- Spring 2022 rev/ASK: 27.6 cents vs 2019 33.9 cents - yield BELOW normal
  because LCC load factor collapsed to 74.7% (vs 90.8% in 2019).

So the prior year (2022) was distorted in opposite directions by carrier
type, and the model carried that distortion forward.

## Why 2023 moved the way it did

| Carrier | LF 2022 -> 2023 | Driver |
|---|---|---|
| Spring | 74.7 -> 89.4 (+14.7pp) | reopening demand surge; LCC price elasticity high; yield +37% |
| Juneyao | 67.3 -> 82.8 (+15.5pp) | same demand surge, hybrid model; yield +19% |
| Air China | 62.7 -> 73.2 (+10.5pp) | supply restored (ASK +204%), intl still weak, domestic oversupply -> yield -12% |
| China Southern | 66.3 -> 78.1 (+11.8pp) | same; yield -11% |
| China Eastern | 63.7 -> 74.4 (+10.7pp) | same; yield -4% |
| Hainan | 67.7 -> 81.4 (+13.7pp) | mostly domestic, least distorted 2022; yield ~flat |

- LCCs: 2022 was depressed (low LF, low yield), so 2023 reopening lifted
  both LF and price -> yield surged, model under-predicted revenue.
- Big three: 2022 was scarcity-inflated, 2023 supply restoration + slow
  international recovery + domestic oversupply -> yield normalized DOWN,
  model over-predicted revenue.
- Hainan: least distorted 2022 base, so 2023 error was tiny.

## What this means for the 2026 trade

1. The 2023 episode is the empirical basis for the
   `spring_recovery_case` rule: pre-declared +10% yield premium when the
   RPK-ASK gap and load-factor lift both clear thresholds.  It cut Spring
   H1-2023 error from -31.9% to -9.3%.
2. 2026 is NOT a 2023-style regime year: Spring ASK +15.4% / RPK +18.0% /
   LF +2.1pp is a normal-growth profile (2023 was ASK +50% / RPK +81% /
   LF +15pp).  The flat-yield baseline is appropriate; the residual-yield
   model hedges the tail.
3. The pair thesis (long Spring / short Juneyao) is consistent with the
   2023 read-through: in a demand-positive regime LCC yield elasticity
   exceeds hybrid/FSC yield elasticity.  The 2023-2025 yield paths confirm
   Spring's unit-yield advantage persists (+37% in 2023, then 36.3, 34.7 -
   still above the 2022 trough and re-approaching 2019's 33.9 from above).

## Files

- Row data: `data/normalized/hk_transport/airline_period_kpi_backtest.csv`
- Charts: `docs/asia-markets/charts/history_backtest_*.png`
- Method: `docs/asia-markets/airline-backtest-audit-and-improvements.md`
