# Mainland Airline Pair Thesis Review

Status: provisional, direction-neutral review as of 2026-08-08. This is a
working thesis handoff, not an approved trade list.

## Method and decision gate

The company bridge uses FY2025/1H2025 primary issuer drivers and 2026 H1
company traffic run-rates for ASK/RPK assumptions. Current consensus is kept
as the expectations comparator rather than being copied into the independent
forecast. The provisional price target diagnostic holds each market leg's
current consensus-revenue P/S multiple constant and applies the model revenue
gap to the current price. Pair payoffs use the directional mechanical beta from
the pair-risk layer.

As an independent asset-value cross-check, the P/B diagnostic uses dated
one-year public P/B observations and the latest available primary-issuer
equity basis. It is not a replacement for historical P/S/P/E and its equity
basis is still FY2025 or 1H2025 pending 1H2026 reports.

A candidate is not trade-ready if its base payoff turns negative under a 10%
compression of the long leg's multiple, if market-leg consensus scope is mixed
without reconciliation, or if factor/drawdown risk is not acceptable. The
constant-P/S calculation is therefore a diagnostic and not a fair-value target.

## Current pair review

| Pair | Provisional direction | Base beta-hedged payoff | Payoff after 10% long-leg compression | P/B median equal-notional payoff | Base beta-hedged range | Main issue | Catalyst |
|---|---|---:|---:|---:|---:|---|---|
| China Southern–Spring | Long Spring / short Southern | +2.75% | -7.25% | -11.60% | -19.81% to +29.64% | Spring P/S 1.83x versus Southern HK 0.28x; P/B cross-check disagrees; mixed HK/A scope; direction-aware drawdown -26.9% | Southern/Spring 1H2026 reports scheduled 2026-08-29 |
| China Eastern–Spring | Long Spring / short Eastern | -0.16% | -10.16% | +5.52% | -11.34% to +26.72% | No base payoff before valuation stress; P/B is the only supportive valuation cross-check; direction-aware drawdown -30.0% | Eastern 2026-08-31; Spring 2026-08-29 |
| Hainan–Spring | Long Spring / short Hainan | +6.64% | -3.36% | -43.25% | -34.63% to +33.53% | Hainan uses a weaker fallback forecast; P/B cross-check strongly disagrees; drawdown -20.7% | Hainan 2026-08-25; Spring 2026-08-29 |
| Air China–Spring | Long Spring / short Air China | +4.36% | -5.64% | +6.75% | -12.74% to +31.25% | Air China negative-profit base uses consensus-margin fallback; P/B is supportive but mixed HK/A scope remains; direction-aware drawdown -21.9% | Air China 2026-08-31; Spring 2026-08-29 |
| Spring–Juneyao | Long Spring / short Juneyao | +3.72% | -6.28% | -6.75% | -23.43% to +30.61% | Same A-share market leg, but Juneyao includes unresolved 9 Air economics; P/B cross-check disagrees; drawdown -14.2% | Spring 2026-08-29; Juneyao 2026-08-31 |

## Pair-level thesis statements

### China Southern–Spring — current core research candidate

Variant perception: the model's Spring revenue gap to consensus is about
`-6.1%`, versus about `-20.8%` for Southern. This supports a provisional view
that Spring's demand/pricing resilience could be better than the network-carrier
leg. The market, however, pays a large P/S premium for Spring, so the thesis is
execution resilience versus valuation premium, not a simple cheap-versus-expensive
trade.

The direction is not approved. It fails the 10% long-leg valuation-compression
gate and uses a Hong Kong Southern leg against a China-A-share company forecast.
The first validation is route-level yield/booking data and the 2026-08-29
interim-result revision.

### China Eastern–Spring — backup, currently rejected by the base payoff

Variant perception is directionally similar: Spring's model revenue gap is less
negative than Eastern's. But the base beta-hedged payoff is already slightly
negative before valuation stress. The pair also carries material factor and
drawdown risk. Keep it as a monitor only; it needs a clear Eastern-specific
negative revision or Spring-specific positive revision before promotion.

### Hainan–Spring — backup, valuation-sensitive

The model shows a large relative revenue gap in Spring's favour, but Hainan's
forecast relies on a mechanical H1 run-rate fallback. The apparent payoff is
therefore highly assumption-sensitive. The 10% premium-compression test fails,
so the pair needs independent Hainan capacity/yield evidence and its
2026-08-25 interim result before any direction is considered.

### Air China–Spring — backup, unstable profit base

Spring's model revenue gap is less negative than Air China's, but Air China's
FY2025 negative profit means the bridge uses a consensus-margin fallback. This
makes the earnings comparison weak and the H-share/A-share market-leg mapping
asynchronous. The pair is a monitor, not a trade, until Air China's actual
profit bridge and consensus revisions are available.

### Spring–Juneyao — monitor and cleanest market-leg comparison

Both legs are China A shares, so market-leg scope is cleaner. The model still
favours Spring: revenue gap is about `-6.1%` versus Juneyao about `-15.5%`.
However, Juneyao's consolidated numbers include 9 Air, whose standalone
revenue, cost, yield and margin are unavailable. The pair also fails the 10%
long-leg compression gate. It remains the cleanest pair for a focused operating
deep dive, but not an approved trade.

## Required evidence before direction approval

The direction-concordance gate initially left Eastern–Spring and Air China–Spring
as provisional candidates. The subsequent point-in-time revision gate finds no
full long-up/short-down confirmation as of 2026-08-07: Spring is `no_signal`,
Eastern is `up`, Air China is `down`, Southern is `up`, Juneyao is `down`, and
Hainan has no leg signal. Therefore all five pairs are currently monitors with
no approved direction; the two P/B-concordant pairs remain revision-unconfirmed.

Target/payoff ranges are reported in `airline_pair_target_range.csv`. They use
the min/max of the earnings/P-S and P/B diagnostics, so they should be read as
valuation-method uncertainty bands rather than confidence intervals.

The executable pre-event rule set is in
`airline_pair_event_trade_triggers.csv`. It requires a realized surprise gap,
with separate profit and revenue thresholds, fresh revision confirmation and a
non-negative lower valuation bound after the reports; until then every pair
remains `wait_for_event_trigger_no_pre_event_trade`.

For directionally conflicted pairs, the two falsifiable branches are preserved
in `airline_pair_branch_thesis.csv`: fundamental resilience versus valuation
mean reversion. This prevents the current P/B conflict from being hidden inside
one mechanically chosen direction.

1. Route-level fare, booking-window and fare-class observations for Spring and
   each proposed short leg.
2. Formal 1H2026 ASK/RPK/LF/yield/CASK actuals and the first post-result
   consensus revision.
3. Historical or peer-adjusted valuation multiples rather than constant-P/S.
4. Residual return after beta, size, momentum and volatility controls.
5. Fuel surcharge recovery, hedge/pass-through and HSR substitution evidence.
6. A portfolio risk budget, stop rule, hedge ratio and borrow/recall check.

## Source artifacts

- `data/normalized/hk_transport/airline_forward_earnings_bridge.csv`
- `data/normalized/hk_transport/airline_pair_thesis_working_set.csv`
- `data/normalized/hk_transport/airline_pair_trade_thesis_scenarios.csv`
- `data/normalized/hk_transport/airline_pair_valuation_factor_review.csv`
- `data/normalized/hk_transport/airline_valuation_peer_comparability.csv`
- `data/normalized/hk_transport/airline_pb_history.csv`
- `data/normalized/hk_transport/airline_historical_pb_valuation.csv`
- `data/normalized/hk_transport/airline_pair_pb_trade_diagnostic.csv`
- `data/normalized/hk_transport/airline_pair_risk_budget_sizing.csv`
- `data/normalized/hk_transport/airline_pair_direction_decision.csv`
- `data/normalized/hk_transport/airline_pair_revision_confirmation.csv`
- `data/normalized/hk_transport/airline_pair_target_range.csv`
- `data/normalized/hk_transport/airline_pair_event_trade_triggers.csv`
- `data/normalized/hk_transport/airline_pair_branch_thesis.csv`
- `data/normalized/hk_transport/airline_forward_invalidation_rules.csv`
- `data/normalized/hk_transport/airline_pair_risk_metrics.csv`
- `data/normalized/hk_transport/airline_pair_factor_diagnostics.csv`

Every derived row retains source paths and retrieval timestamps; no direction
above should be read independently of those fields.
