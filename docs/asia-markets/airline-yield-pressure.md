# Synthetic Yield-Pressure Index

Status: 2026-08-10.  Route-level realized yield is not available from free
public sources, so this layer infers yield pressure indirectly from
operating data.  It is a direction modifier, not a realised-yield forecast.

## Construction

Per company, per month (2016-01 to 2026-06):

```
YP = 0.5 x z(RPK growth - ASK growth)      demand-capacity gap
   + 0.25 x z(load-factor change)          cabin tightness
   + 0.15 x z(international-mix change)    mix effect on RASK
   - 0.10 x z(industry passenger growth)   competitive capacity
```

Components are 3-month centred moving averages, z-scored over the company's
own history, and combined with economic-prior weights (not fitted).  Inputs:
`china_airlines_monthly.parquet` (company ASK/RPK by region, 2016-2026-06)
and the CAAC sector monthly passenger volume.  Machine-readable outputs:
`airline_yield_pressure_index.csv` and
`airline_yield_pressure_validation.csv`.

## Honest validation result

The annualised index is compared with walk-forward
`revenue_per_rpk_growth_actual_pct` (the closest free realised-yield proxy)
cross-sectionally across the six carriers each year:

| Year | Spearman rank corr | Direction-consistent / 6 |
|---|---:|---:|
| 2017 | -0.66 | 2 |
| 2018 | -0.26 | 1 |
| 2019 | +0.14 | 3 |
| 2020 | -0.26 | 2 |
| 2021 | -0.60 | 3 |
| 2022 | +0.60 | 0 |
| 2023 | +0.03 | 1 |
| 2024 | -0.89 | 0 |
| 2025 | +0.66 | 4 |

All-year mean Spearman: **-0.14**; direction-consistent rate: **30%**.

**Conclusion: the simple demand-capacity index does NOT explain historical
yield variation.**  It is positive only in 2025 (+0.66) and mixed/negative
elsewhere.  The negative historical result is reported rather than hidden.

Interpretation:

* COVID years (2020-2022) broke the demand-capacity-to-pricing channel
  (policy-driven capacity, price floors, quarantine demand).
* 2024's strong negative (-0.89) suggests the post-recovery supply
  discipline regime changed the relationship (capacity control offsetting
  demand softness).
* The 2025 positive correlation is encouraging but single-year and small-
  sample (n=6); it is not evidence of a stable predictive relationship.

## How it is used

The index is carried as a **recent direction modifier** with status
`validation_limited_positive_2025_only_weak_history`.  It can support a
qualitative read on 1H2026 pricing (e.g. which carrier's RPK-ASK gap is
firming most) but it is NOT used as a quantitative yield forecast, and it
does not override the company-disclosed yield anchors in the earnings model.
The unmodelled yield drivers (FX, fuel surcharge pass-through, regulatory
fare bands, competitive route entry) are explicit limitations.
