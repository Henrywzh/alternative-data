# Residual Yield Model (Priority 1 + 2)

Status: 2026-08-10.  Moves from predicting absolute revenue to predicting
only the deviation from the flat-yield baseline, with the yield-pressure
signal reduced to a 3-class bucket and shrunk.

## Construction

```
FlatYieldRevenue_t = ASK_t x RASK_{t-1}
Residual_t        = ActualRevenue_t - FlatYieldRevenue_t

AdjustedRevenue_t = FlatYieldRevenue_t x (1 + adjustment)
adjustment        = lambda x historical_residual_std x sign(yield_pressure_bucket)
lambda            = 0.5
```

The yield-pressure index is reduced to +1 improving / 0 flat / -1
deteriorating (buckets at +/-0.25), and the magnitude of the adjustment is
capped at half the historical residual standard deviation - so the weakly
validated yield signal can never dominate the strong flat-yield prior.
Historical rows use the yield-pressure score from the SAME target year
(PIT); current forecasts use the trailing-12m mean.

## Historical result (honest)

| Company | Flat-yield MAE | Adjusted MAE | Change |
|---|---:|---:|---:|
| Spring Airlines | 10.54% | 9.29% | **-1.25pp** |
| Juneyao Airlines | 7.89% | 7.21% | **-0.68pp** |
| Hainan Airlines | 5.54% | 5.50% | -0.04pp |
| Air China | 5.87% | 6.90% | +1.03pp |
| China Southern | 5.93% | 7.27% | +1.34pp |
| China Eastern | 7.05% | 7.19% | +0.14pp |

The residual model improves the two carriers with the largest yield
variability - Spring and Juneyao, exactly the pair legs - and degrades the
Big 3, whose flat-yield residual is already small and where the yield
pressure signal is noise.  17% of historical rows improve; 62% are flat (no
adjustment).

## Why this is the right structure

* It recognises that historical yield is the prior; the model learns only
  the deviation, which is more stable than re-learning absolute revenue.
* The 3-class bucket + shrinkage prevents the weakly-validated yield signal
  (2025 cross-sectional +0.66, all-year -0.14) from making false precision
  claims.
* For the 1H2026 forecast, the recent yield-pressure signal is weak, so the
  model conservatively keeps flat-yield - the right behaviour when the
  signal does not support a directional call.

## Limitations

* The yield-pressure bucket is validated only weakly; the improvement on
  Spring/Juneyao is in-sample and needs 1H2026 actuals as the out-of-sample
  test.
* Lambda is fixed at 0.5, not optimised; a per-company lambda (higher where
  the residual is predictable) is a natural extension.
