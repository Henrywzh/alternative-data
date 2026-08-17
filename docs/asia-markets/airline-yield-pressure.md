# Synthetic Yield-Pressure Index

Status: 2026-08-11.  Route-level realized yield is not available from free
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

Components are 3-month trailing moving averages (t-2..t), z-scored using
expanding history available at each month, and combined with economic-prior
weights (not fitted).  Inputs:
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
| 2017 | +0.60 | 2 |
| 2018 | -0.26 | 2 |
| 2019 | +0.37 | 3 |
| 2020 | -0.60 | 2 |
| 2021 | -0.77 | 6 |
| 2022 | +0.49 | 1 |
| 2023 | -0.26 | 1 |
| 2024 | -0.89 | 0 |
| 2025 | +0.54 | 4 |

All-year mean Spearman: **-0.09**; direction-consistent rate: **39%**.

NOTE (2026-08-11 PIT audit): the monthly index uses point-in-time
z-scoring and trailing smoothing.  The residual-yield consumer now also
aggregates scores by target period: H1 uses Jan-Jun, H2 uses Jul-Dec and FY
uses Jan-Dec.  The earlier consumer used one full-year score for H1/H2/FY,
which leaked the second half into H1; its downstream v4 result is no longer
the official figure.  The validation numbers above are the honest monthly
index results; the earlier reported "+0.66 in 2025 / all-year -0.14"
reflected the original look-ahead version and should not be quoted.

**Conclusion: the simple demand-capacity index does NOT explain historical
yield variation.**  It is mixed/negative in most years.  The negative
historical result is reported rather than hidden.

Interpretation:

* COVID years (2020-2022) broke the demand-capacity-to-pricing channel
  (policy-driven capacity, price floors, quarantine demand).
* 2024's strong negative suggests the post-recovery supply discipline
  regime changed the relationship (capacity control offsetting demand
  softness).
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
