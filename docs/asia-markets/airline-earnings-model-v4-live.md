# v4 Live Pre-Event Forecast (1H2026) + Diagnostics

Status: 2026-08-10.  This is the v4 engine in its pre-event form for the
2026-08-25/29/31 report cycle: a frozen, attributable forecast per carrier,
a surprise ranking vs consensus, and two honest diagnostics.

## Live forecast layers (per carrier, H1-2026)

Revenue is built layer by layer so EPS_v4 - EPS_v3 can be attributed:

    revenue_base    = ASK_2026 x LF_2025 x Yield_2025          (flat-ASK)
    revenue_shrink  = ASK_2026 x LF_f x Yield_f_MR             (+ mean reversion)
    revenue_resid   = ASK_2026 x LF_f x Yield_f_final          (+ bounded yield modifier)
    revenue_overlay = ... x (1 + recovery premium)             (Spring-only rule, if triggered)

Each layer is pushed through the forward-NI bridge waterfall (op scaled
with v4 revenue vs bridge revenue, finance scaled with revenue, tax at the
H1-2025 effective rate, NCI carried) to give NI and EPS per layer.  The
shrinkage lambda, yield modifier delta and recovery flag are stored per
carrier, so the EPS_v4 - EPS_v3 gap is fully attributable.

## Surprise ranking vs consensus (the pair question)

Surprise_i = (EPS_v4_FY_annualised - EPS_cons) / |EPS_cons|,
EPS_v4_FY_annualised = EPS_v4_H1 x 2 (conservative lower bound; H2 is
seasonally stronger for mainland carriers - same convention as the
decision-eval layer).

| Rank | Company | v4 surprise | v3 surprise | Valid |
|---|---|---|---|---|
| 1 | Spring Airlines | +64.7% | +28.5% | yes |
| 2 | Juneyao Airlines | +18.5% | +21.1% | yes |
| - | Air China / Eastern / Southern / Hainan | n/a | n/a | **no** |

Validity rule: annualisation x2 is only meaningful when the carrier had a
POSITIVE H1-2025 attributable profit.  The big three lost money in H1-2025
(their losses are H1-seasonal, not full-year), so their x2 proxy would be
a fabricated surprise and is flagged invalid rather than reported.

**Pair read**: the Spring long / Juneyao short thesis HOLDS under v4, and
Spring's edge over consensus is now much larger (+64.7% vs +18.5%, a 46pp
gap, up from 7pp under v3).  The v4 engine is more bullish on Spring
primarily through the LF/yield mean-reversion layers: consensus is priced
on a weaker yield recovery than the v4 normal-level anchor implies.

## Frozen pre-event snapshot

- `data/normalized/hk_transport/snapshots/airline_v4_pre_event_20260810.csv`
- Written ONCE per forecast_asof; never overwritten or recomputed after the
  reports.  Carries `forecast_asof`, `data_cutoff` (2026-08-01),
  `model_version`, `forecast_type = pre_event`.
- Post-report corrections belong in the validation playbook and
  post-earnings tracker, never in this file.

## Spread residual diagnostic (Spring - Juneyao)

SpreadResidual_t = pre-shrink residual (base-layer error) of Spring minus
Juneyao, tested against the NEXT year's realised revenue-spread change
(both first-order growth-spread and second-order change).

Result (honest): **direction accuracy 0/5 (both definitions)**.  The
pre-shrink residual has NO predictive power for next-year spread changes -
it is dominated by regime-year errors (2020/2023) that do not mean-revert
on a one-year horizon.  Conclusion: keep it as a diagnostic / relative
signal only; it does NOT qualify to become a formal spread model (per the
pre-agreed bar: only upgrade if OOS clearly beats EPS_S - EPS_J).

## Error persistence diagnostic (the Juneyao 2021-22 question)

Per FY row: z_LF (deviation in std units), shrink lambda, forecast error
and prior-error sign.  Conditional same-sign probability
P(error_t same sign | error_{t-1} > 0):

| Company | P(same sign | prior > 0) |
|---|---|
| Spring | 3/4 = 75% |
| Air China / Southern / Juneyao | 2/3 = 67% |
| Eastern / Hainan | 1/2 = 50% |

Weak positive persistence (~50-75%, tiny samples).  The Juneyao 2021-22
errors are NOT a clean AR(1) story: 2021 over-forecast (+11%) was followed
by 2022 near-zero (-0.1%), then 2023 under-forecast (-13%).  The multi-year
regime persistence is real but shorter-lived than assumed; a residual AR(1)
correction (rho x residual_{t-1}) would have helped 2021 only and hurt
2022-23.  Recommendation: do NOT add a mechanical residual correction;
keep the v4 mean-reversion layers as the regime handling.

## Files

- Module: `src/hk_transport/sources/airline_earnings_model_v4_live.py`
- Live forecast: `data/normalized/hk_transport/airline_earnings_model_v4_live_forecast.csv`
- Surprise: `data/normalized/hk_transport/airline_earnings_model_v4_surprise.csv`
- Spread diagnostic: `data/normalized/hk_transport/airline_earnings_model_v4_spread_residual_diagnostic.csv`
- Persistence: `data/normalized/hk_transport/airline_earnings_model_v4_error_persistence.csv`
- Snapshot: `data/normalized/hk_transport/snapshots/airline_v4_pre_event_20260810.csv`
- Tests: `tests/test_hk_transport_airline_earnings_model_v4_live.py` (8 tests)
- CLI: `run-airline-earnings-model-v4-live`
