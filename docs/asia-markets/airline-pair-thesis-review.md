# Mainland Airline Pair Thesis Review

Status: provisional pre-event review as of 2026-08-08. It contains an
independent working view for Spring–Juneyao, but it is not an approved trade
list.

## Method and decision gate

The company bridge uses FY2025/1H2025 primary issuer drivers and 2026 H1
company traffic run-rates for ASK/RPK assumptions. Current consensus is kept
as the expectations comparator rather than being copied into the independent
forecast. The provisional trade-scenario price target diagnostic holds each
market leg's current consensus-revenue P/S multiple constant and applies the
model revenue gap to the current price. A separate historical-valuation layer
now supplies dated PE/PB and constructed annual-revenue P/S bands; those bands
are the proper valuation comparison, while the constant-P/S output remains a
stress diagnostic. Pair payoffs use the directional mechanical beta from the
pair-risk layer.

The companion `airline_company_financial_forecast_bridge.csv` now provides the
broader six-company earnings bridge before pair selection. It separates
passenger revenue (`passenger RASK x ASK`) from cargo/other revenue, prefers the
A-share consensus leg for dual-listed mainland companies, and marks all
H1-cargo and unit-economics proxies. For FY2025 loss-making carriers it uses a
dated consensus-margin normalization fallback rather than a negative historical
net-profit/operating-profit conversion. This layer expands the forecast
coverage; it does not replace the more opinionated Spring–Juneyao independent
view below.

The new `airline_independent_forecast_view.csv` is the pre-event analyst
starting point rather than another consensus stress test. It records explicit
ASK/RPK, revenue-per-ASK mix/yield, fuel-price and non-fuel cost-per-ASK
assumptions before the scheduled reports, then derives operating profit and
net profit. The resulting company profit gap versus consensus is the variant
view. The sector context is positive demand but fuel/pricing sensitive: APAC
IATA's dated forecast is RPK +7.3% versus ASK +7.1%, while the six-company
China H1 panel shows RPK +4.8% versus ASK +2.6%. The 1H2026 report is a
pre-defined validation catalyst: actuals should update or falsify the view,
not create the first view after the fact.

The separate `airline_h1_kpi_backtest.csv` keeps the event test aligned to that
catalyst. It uses January--June ASK/RPK releases available before an August 1
cutoff and tests a flat-unit-economics H1 bridge on historical company-years.
The source-recovered/imputed layer gives Spring flat-ASK revenue MAE of 9.8%
and flat-RPK MAE of 7.5% across nine rows; the separate recovery-case
yield/mix sensitivity is 6.6%. Spring's cost MAE is 11.1%. The current 1H2026
flat-unit-economics nowcast remains approximately USD1,659m revenue / USD188m
attributable-profit proxy for Spring and USD1,562m / USD71m for Juneyao. The
analyst yield/non-fuel overlay lowers the profit estimates to approximately
USD170m and USD50m. These are pre-report nowcasts, not realized results; the
historical financial target panel before 1H2025 lacks a complete issuer
announcement-date tape, so the backtest is calibration evidence rather than a
strict PIT trading backtest.

The expanded `airline_period_kpi_backtest` separately evaluates H1, H2 and FY
(162 company-year-period rows). H2 financial actuals are derived as FY minus
H1 and are labelled accordingly. The strict layer has nine evaluated years for
each company-period except Hainan H1/FY, where the 2016 January--May operating
base is unavailable; the logical nearest-observed sensitivity restores that
case but excludes it from PIT-safe evidence. Spring's high MAE is concentrated
in the COVID/reopening regime, especially 1H2023 when RPK grew 81.3% versus ASK
49.6% and revenue per RPK rose 21.3%. This supports using RPK as the base
revenue bridge and treating recovery-yield uplift as a sensitivity, not as a
validated replacement.

## Walk-forward model v2 and current H1 2026 alternatives

The V1 calibration is now complemented by
`airline_walk_forward_model_v2.csv`. This is a separate, leakage-safe
research layer rather than a replacement for the V1 files. It trains pooled
coefficients only on target years strictly earlier than each forecast year and
compares five transparent combinations: flat-ASK, flat-RPK, yield/mix plus
flat-ASK cost, flat-RPK plus fuel/non-fuel cost, and the integrated case.
The output covers 160 evaluated historical company-period observations and
six current H1 2026 company forecasts across 30 model rows.

The current empirical conclusion is conservative. Spring's flat-RPK revenue
MAE is about 7.4% in H1, 10.8% in H2 and 7.9% in FY, while the pooled
walk-forward yield/mix case is about 12.3%, 13.3% and 11.2%, respectively.
Therefore the more complex yield regression is retained as a sensitivity and
not adopted as the base revenue bridge. The current research base case in the
V2 input layer is `walk_forward_fuel_nonfuel`: RPK-scaled revenue plus an
explicit fuel/non-fuel cost bridge. It is a working model convention, not an
approved trade view.

The V2 current forecast uses the 2026-08-09 cutoff and has no H1 2026
financial actuals. It forecasts an operating-profit proxy (revenue less
operating cost), not attributable net income. The companion
`airline_thesis_v2_input_coverage.csv` joins these alternatives to annual
consensus context, dated public revision evidence, issuer guidance/report
dates and 3-year PE/PB/P/S bands. Juneyao has only one revenue analyst and is
explicitly a thin-consensus leg; the annual-consensus-scaled H1 revenue field
is a rough anchor, not direct H1 broker consensus.

`airline_thesis_v2_pair_readiness.csv` is symmetric: it uses `leg_a` and
`leg_b`, never `long` and `short`, and keeps `direction_status` equal to
`not_selected_by_v2`. It is used to compare revenue-growth/margin spreads and
data blockers before the fundamental variant perception and valuation gates
are approved.

The source-recovery layer now restores 178 rows from cached official CNINFO
PDFs, including parser gaps that had previously been filled by interpolation.
It also verifies 22 Juneyao 2016-01--2016-11 AFTK/freight-load-factor gaps as
genuine non-disclosures rather than parser misses; the other 178 audit rows are
explicitly classified as parser-gap recoveries. The recovery script does not
overwrite the raw parser archive, although a raw refresh after the parser repair
can carry recovery-labelled rows. The subsequent research-imputed sensitivity layer increases
usable historical H1 rows from 43 to 53; only the remaining interpolated rows
use future monthly observations and are excluded from the 1H2026 event model.
Source-PDF recoveries retain issuer announcement dates. The current
Spring/Juneyao 1H2026 KPI inputs are complete and observed, so the raw and
source-recovered/imputed nowcasts are identical.

As an independent asset-value cross-check, the P/B diagnostic uses dated
one-year public P/B observations and the latest primary-issuer equity basis
announced on or before each observation date. Cathay now has FY2024, 1H2025,
FY2025 and 1H2026 official equity anchors; the mainland names still require
their 1H2026 refresh. P/B is not a replacement for historical P/S/P/E.

A candidate is not trade-ready if its base payoff turns negative under a 10%
compression of the long leg's multiple, if market-leg consensus scope is mixed
without reconciliation, or if factor/drawdown risk is not acceptable. The
constant-P/S calculation is therefore a diagnostic and not a fair-value target.

## Pre-event analyst view: Spring–Juneyao

The current working base case is **long Spring / short Juneyao** before the
reports, subject to the valuation and risk gates below. It is deliberately
more conservative on both companies' revenue than the current consensus, but
it assumes Spring retains more of its structural margin advantage.

| Company | Independent FY2026 revenue growth | Independent net margin | Independent profit (USD mn) | Profit gap vs consensus | Pre-event view |
|---|---:|---:|---:|---:|---|
| Spring Airlines | +17.0% | 9.6% | 344.3 | +9.2% | Long candidate |
| Juneyao Airlines | +4.0% | 3.2% | 107.2 | -22.0% | Short candidate |

This creates a 31.1 percentage-point relative profit-gap spread in the base
case. The core risks are Spring's 1.83x market-cap/consensus-revenue proxy,
the P/B conflict, and Juneyao's unresolved 9 Air economics. The five-factor
residual test is a useful diagnostic (about +2.8% annualised alpha, 576
observations, approximately -21.7% residual maximum drawdown), not proof of
future alpha.

As a transparent expression of the view, applying the independent revenue
gaps to the existing 3-year median annual-P/S diagnostic gives illustrative
targets of RMB62.41 for Spring and RMB12.73 for Juneyao, with a beta-hedged
pair payoff of about +26.7%. This is not a fair-value target: the P/S
denominator remains partly period-end/annual, and the P/B cross-check still
disagrees.

## Pre-event candidate decision

The current research expression is a **conditional pre-event candidate**, not
a post-result trade: long Spring / short Juneyao before the later scheduled
report. The independent-P/S expression is +26.7% beta-hedged, while the P/B
equal-notional cross-check is -6.8%, creating a bounded valuation diagnostic of
approximately **-6.8% to +26.7%**. We therefore use the conservative 0.25% NAV
loss budget: the existing direction-aware diagnostic implies about 2.86% NAV
gross notional and a -14.2% observed spread drawdown. Borrow/recall and live
liquidity remain execution checks, not hidden assumptions.

The bet is valid only while the variant remains intact: Spring's RPK-minus-ASK
and yield/margin advantage persists, Juneyao's warning/9 Air cost pressure is
not reversed, and the spread remains inside the risk budget. The two reports
on 2026-08-29 and 2026-08-31 are validation catalysts; we do not wait for
them to create the direction.

## Current pair review

| Pair | Provisional direction | Model-only beta-hedged payoff | Payoff after 10% long-leg compression | P/B median equal-notional payoff | Base beta-hedged range | Main issue | Catalyst |
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

The executable event rule set is in
`airline_pair_event_trade_triggers.csv`. It requires a realized surprise gap,
with separate profit and revenue thresholds, fresh revision confirmation and a
non-negative lower valuation bound after the reports. That is an execution
gate, not a reason to postpone the pre-event forecast: the independent view is
defined now, while the reports determine whether to keep, resize or reject it.

For directionally conflicted pairs, the two falsifiable branches are preserved
in `airline_pair_branch_thesis.csv`: fundamental resilience versus valuation
mean reversion. This prevents the current P/B conflict from being hidden inside
one mechanically chosen direction.

1. Route-level fare, booking-window and fare-class observations for Spring and
   each proposed short leg.
2. Formal 1H2026 ASK/RPK/LF/yield/CASK actuals and the first post-result
   consensus revision.
3. Historical or peer-adjusted valuation bands, reconciled to announcement
   dates and denominator definitions rather than relying on constant-P/S.
4. Residual return after beta, size, momentum and volatility controls.
5. Fuel surcharge recovery, hedge/pass-through and HSR substitution evidence.
6. A portfolio risk budget, stop rule, hedge ratio and borrow/recall check.

## Source artifacts

- `data/normalized/hk_transport/airline_forward_earnings_bridge.csv`
- `data/normalized/hk_transport/airline_pair_thesis_working_set.csv`
- `data/normalized/hk_transport/airline_pair_trade_thesis_scenarios.csv`
- `data/normalized/hk_transport/airline_operating_kpi_source_recovered.parquet`
- `data/normalized/hk_transport/airline_operating_kpi_source_recovery_audit.csv`
- `data/normalized/hk_transport/airline_operating_kpi_imputed.parquet`
- `data/normalized/hk_transport/airline_operating_kpi_imputation_audit.csv`
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
- `data/normalized/hk_transport/airline_independent_forecast_view.csv`
- `data/normalized/hk_transport/airline_company_financial_forecast_bridge.csv`
- `data/normalized/hk_transport/airline_h1_kpi_backtest.csv`
- `data/normalized/hk_transport/airline_h1_kpi_backtest_summary.csv`
- `data/normalized/hk_transport/airline_operating_kpi_imputed.parquet`
- `data/normalized/hk_transport/airline_operating_kpi_imputation_audit.csv`
- `data/normalized/hk_transport/airline_h1_kpi_backtest_imputed.csv`
- `data/normalized/hk_transport/airline_h1_kpi_backtest_raw_vs_imputed.csv`
- `data/normalized/hk_transport/airline_period_kpi_backtest.csv`
- `data/normalized/hk_transport/airline_period_kpi_backtest_summary.csv`
- `data/normalized/hk_transport/airline_period_kpi_backtest_logical_assumptions.csv`
- `data/normalized/hk_transport/airline_period_kpi_backtest_model_comparison.csv`
- `data/normalized/hk_transport/airline_walk_forward_model_v2.csv`
- `data/normalized/hk_transport/airline_walk_forward_model_v2_summary.csv`
- `data/normalized/hk_transport/airline_walk_forward_model_v2_current_forecast.csv`
- `data/normalized/hk_transport/airline_walk_forward_model_v2_model_comparison.csv`
- `data/normalized/hk_transport/airline_thesis_v2_input_coverage.csv`
- `data/normalized/hk_transport/airline_thesis_v2_pre_h1_forecast.csv`
- `data/normalized/hk_transport/airline_thesis_v2_pair_readiness.csv`
- `data/normalized/hk_transport/airline_spring_mae_diagnostics.csv`
- `data/normalized/hk_transport/airline_pair_factor_residual_test.csv`
- `data/normalized/hk_transport/airline_pre_event_trade_candidate.csv`

Every derived row retains source paths and retrieval timestamps; no direction
above should be read independently of those fields.
