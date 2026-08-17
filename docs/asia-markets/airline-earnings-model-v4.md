# Airline Earnings Model v4: Decomposition Revenue Architecture

Status: 2026-08-11.  v4 replaces the flat-yield family as the primary
revenue forecasting engine.  It is the direct response to the 2023 error
autopsy: flat-ASK/flat-RPK assume yield is unchanged from the prior year,
which fails structurally in regime years (2020 COVID, 2022 lockdowns,
2023 reopening) where the prior-year yield is distorted - in OPPOSITE
directions for LCCs vs the big three.

## Architecture

    Revenue_t = ASK_t x LF_f x Yield_f

- LF (load factor = RPK/ASK) and yield-per-RPK each mean-revert to their
  company normal level with an anomaly-dependent shrinkage lambda
- Lambda is an explicit function of how far the prior-year LF sits from
  the company's own historical normal (LF is the cause, yield the result:
  regime detection uses LF, never yield)
- Normal levels are computed walk-forward (strictly earlier rows only) -
  no look-ahead
- ASK/RPK joint regression is NOT a candidate: ASK and RPK growth
  correlate ~1.00 (LF moves little), so coefficients are unidentified
  (66% of walk-forward fits had a negative coefficient)

## Stacked ablations (each stage adds exactly one component)

| Stage | Revenue MAE | Regime-year MAE | Normal-year MAE | Rank IC |
|---|---|---|---|---|
| base_decomposition (= flat-ASK) | 9.12% | 11.82% | 3.71% | 0.863 |
| + dynamic_shrinkage | 7.92% | 10.36% | 3.05% | 0.810 |
| + residual_yield (bounded, period-safe) | 7.69% | 9.88% | 3.33% | 0.802 |
| + recovery_overlay (Spring-only, period-safe) | **7.47%** | **9.55%** | 3.33% | 0.802 |

Direction accuracy (acceleration sign) improves from 98.6% to 100.0%.

### What each component contributes

1. **base_decomposition**: algebraically identical to flat-ASK (verified
   to 1e-14); the decomposition baseline.
2. **dynamic_shrinkage**: the big win - MAE -1.2pp, regime-year MAE
   -1.5pp.  `lambda_min=0.5` is retained as a fixed design parameter from an
   earlier exploratory sweep; no persisted sweep artifact is available, so
   it is not presented as independent OOS tuning evidence.
3. **residual_yield**: bounded modifier, |delta| <= 3%; small further MAE
   gain (-0.15pp) at a small rank-IC cost (-0.012).  Kept because the cap
   guarantees it cannot re-dominate the yield level.
4. **recovery_overlay**: Spring-only pre-declared +10% yield premium when
   RPK-ASK gap >= 15pp and LF lift >= 10pp.  Explicitly labelled
   (`recovery_overlay_active`); it improves the regime aggregate, but the
   sample is too small to prove that one reopening rule generalises.

## Honest limitations

- 2023 big-three errors improve to ~3-6% but Juneyao 2021/2022 (COVID
  persistence) still carries +10-18% errors - mean reversion to a normal
  computed from a pre-COVID history cannot know a multi-year regime will
  persist.
- Rank IC drops from base 0.863 to final 0.802: shrinkage trades a little
  cross-sectional ranking power for a lot of absolute accuracy.  For
  pair-spread construction this is the right trade (level accuracy is what
  the earnings event pays), but the spread model should consume the
  pre-shrinkage residual as a diagnostic.
- Historical calibration is not a full executable PIT backtest for the
  financial targets before 1H2025 (period-end rows without announcement
  vintages); KPI inputs are PIT-safe.

## Files

- Module: `src/hk_transport/sources/airline_earnings_model_v4.py`
- Backtest rows: `data/normalized/hk_transport/airline_earnings_model_v4.csv`
- Ablation: `data/normalized/hk_transport/airline_earnings_model_v4_ablation.csv`
- Rank IC: `data/normalized/hk_transport/airline_earnings_model_v4_rank_ic.csv`
- Tests: `tests/test_hk_transport_airline_earnings_model_v4.py` (8 tests)
- CLI: `run-airline-earnings-model-v4`
