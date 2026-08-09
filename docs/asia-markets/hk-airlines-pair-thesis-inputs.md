# Airline Pair Thesis Inputs

Status: working pre-event thesis-input memo, 2026-08-08. This note is for a
personal long/short research project. It records the evidence stack and an
explicit working view before the reports; it is not a completed trade
recommendation.

## Evidence stack

The main historical panel is
`data/normalized/hk_transport/airline_historical_earnings_bridge.csv`. It
contains six mainland groups from 2016-03-31 to 2026-03-31 and aligns:

- financial revenue, operating cost, attributable profit, operating cash flow,
  margins, ROE and leverage;
- issuer-released monthly ASK, RPK, passenger, cargo and weighted load-factor
  data;
- period-average EIA jet fuel/Brent and ECB USD/CNY/USD/HKD benchmarks; and
- current FY2026 HK-broker and A-share detailed consensus as separate fields.

The pair-level output is
`data/normalized/hk_transport/airline_pair_historical_bridge.csv`. The current
pair-screening matrix remains the source for current readiness, valuation
revenue multiples, dated revision evidence, risk diagnostics and fuel-shock
proxies.

The base-case anchors have now been checked in
`airline_primary_financial_reconciliation.csv`. For the core and backup names,
FY2025/1H2025 revenue, attributable profit, operating cash flow and EPS mostly
match the official report layer where both values are populated. Operating-cost
values do not match consistently, so provider operating cost is not yet used as
the final CASK/earnings bridge input.

Important boundary: provider financial history has period-end but no issuer
announcement date, and current consensus is a 2026 snapshot rather than a
historical forecast vintage. Formal issuer filings control the final thesis.

## Core candidate: Spring Airlines vs Juneyao Airlines

### Verified relative evidence

| Metric | Spring | Juneyao | Relative read |
|---|---:|---:|---|
| FY2019 net margin | 12.42% | 6.04% | Spring +6.38pp |
| FY2024 net margin | 11.36% | 4.14% | Spring +7.22pp |
| FY2025 net margin | 10.80% | 4.62% | Spring +6.18pp |
| FY2019–FY2025 revenue CAGR | 6.28% | 4.94% | Spring +1.34pp |
| Q1 2026 passenger load factor | 92.66% | 86.63% | Spring +6.03pp |
| Q1 2026 demand-capacity gap | +2.64pp | +1.98pp | Spring +0.66pp |
| A-share detailed FY2026 profit expectation | USD312.7m | USD137.4m | Spring +USD175.3m |
| Market-cap / consensus-revenue proxy | 1.83x | 0.98x | Spring +0.85x |

The evidence supports a genuine quality/profitability divergence, but it does
not yet prove that Spring is cheap or Juneyao is expensive. The market already
assigns Spring a substantial revenue-multiple premium.

### Variant perception to test

The working question is:

> Is Spring's profitability premium structural enough to justify its valuation
> premium, or has the market already overpaid for the low-cost/high-load-factor
> story?

This creates two possible thesis directions without selecting one in advance:

- **Quality continuation:** Spring's higher load factor, faster revenue growth
  and more stable margin persist through 1H2026 and the premium is justified or
  still underappreciated in forward profit estimates.
- **Premium compression:** Spring's advantage narrows, while the 1.83x revenue
  proxy leaves more downside than Juneyao's 0.98x base if demand, yield or fuel
  assumptions disappoint.

### Current pre-event working view

We now take a provisional stance before the 1H2026 reports: **long Spring /
short Juneyao**. This is an independent bottom-up company forecast, not a copy
of the consensus stress bridge. The model goes from ASK/RPK and revenue-per-
ASK mix to fuel/non-fuel cost per ASK, operating profit and net profit:

| Company | FY2026 revenue growth | Net margin | Implied profit (USD mn) | Profit gap vs consensus |
|---|---:|---:|---:|---:|
| Spring Airlines | +17.0% | 9.6% | 344.3 | +9.2% |
| Juneyao Airlines | +4.0% | 3.2% | 107.2 | -22.0% |

The sector context is positive but not a free demand beta: APAC demand is
forecast at RPK +7.3% versus ASK +7.1%, while the six-company mainland H1
panel shows RPK +4.8% versus ASK +2.6% and fuel benchmarks were roughly 50%
higher year on year. The thesis is that Spring's low-cost/high-load-factor margin advantage is more
structural than the market's revenue-only comparison implies, while Juneyao's
group recovery is too optimistic because 9 Air economics remain unresolved.
This is falsified by a material Spring yield/margin miss, a sustained negative
Spring RPK-minus-ASK gap, or Juneyao margin recovery toward consensus. The
formal result is the validation event; we do not wait for it to form the view.

The residual check is supportive but modest: Spring–Juneyao's five-factor
beta-hedged residual alpha is approximately +2.8% annualised over 576
observations, with roughly -21.7% residual maximum drawdown. It reduces the
case for calling the pair only an airline-beta trade, but it does not prove
future alpha.

The resulting pre-event candidate card is
`airline_pre_event_trade_candidate.csv`: it carries a valuation range of about
-6.8% to +26.7%, uses a 0.25% NAV loss-budget diagnostic, and remains
conditional because the P/B cross-check is negative and borrow/recall is not
verified. This is the research expression to test before the reports, not a
claim that execution mechanics have already been cleared.

### Catalysts

- Spring 1H2026 formal report is scheduled for 2026-08-29.
- Juneyao 1H2026 formal report is scheduled for 2026-08-31.
- Monthly operating data through 2026-06 is available; July data was not found
  at the 2026-08-07 cutoff.

### Invalidation / monitoring conditions

- Spring's H1 passenger yield, RASK or net margin falls materially toward
  Juneyao's level.
- Spring's RPK-minus-ASK gap turns negative for multiple releases while
  Juneyao remains positive.
- The valuation premium widens without a corresponding upward revision in
  FY2026/FY2027 earnings.
- Juneyao's reported unit economics improve enough to close the historical
  margin gap.
- The historical Juneyao load-factor anomalies are not reconciled in primary
  reports; anomalous periods must not drive the final thesis.

## Backup candidate: China Southern vs China Eastern

### Verified relative evidence

- FY2025 net margin: Southern 1.47% versus Eastern -1.39%, a +2.87pp Southern
  advantage.
- Q1 2026 demand-capacity gap: Southern -0.34pp versus Eastern +3.48pp, giving
  Eastern a +3.82pp operational advantage in the latest comparable quarter.
- Q1 2026 passenger load factor: Southern 85.13% versus Eastern 86.75%.
- A-share detailed FY2026 profit expectation: Southern USD104.8m versus Eastern
  USD64.3m.
- The current HK-broker snapshot is more negative for both names, but its
  Southern-minus-Eastern gap is still positive at approximately USD163.6m;
  this is a cross-source expectation dispersion signal, not a clean consensus.
- One-year return correlation is high at approximately 0.92, so the pair has
  useful common-factor overlap but may still contain concentrated China-airline
  and policy exposure.

### Variant perception to test

The working question is:

> Has Eastern's recent capacity-demand improvement arrived before its earnings
> recovery, while Southern's better FY2025 profit base is already reflected in
> expectations?

This is a less clean candidate than Spring–Juneyao because both profit bases
remain unstable and the historical and latest operating signals disagree.

### Catalysts and invalidation

- Southern 1H2026 formal report is scheduled for 2026-08-29; Eastern is
  scheduled for 2026-08-31.
- The thesis fails if Eastern's Q1 demand-capacity advantage disappears in H1
  reported RPK/yield, or if Southern's margin recovery accelerates without a
  corresponding consensus revision.
- The pair should remain a backup until formal H1 revenue, yield, fuel cost and
  cash-flow data are reconciled.

## Scenario stress-test layer

`airline_pair_scenario_inputs.csv` contains three mechanical cases for every
pair. For each mainland leg, the current A-share detailed FY2026 snapshot is
used as the base; bear/base/bull cases apply consensus revenue -5%/0%/+5% and
implied net margin -2pp/0pp/+2pp. The scenarios are deliberately symmetric
stress tests, not independent forecasts. The separate
`airline_independent_forecast_view.csv` carries the actual pre-event stance;
after 1H2026 reports, compare actual revenue, yield, cost and guidance against
that stance and revise the assumptions.

## Cathay cross-market backup

Cathay remains useful because its 1H2026 official report is already available
and its international/cargo exposure is different. However, the current
six-company historical bridge does not cover Cathay's full 2016-to-latest
history. Cathay combinations are therefore labelled
`cross_market_backup` and `historical_bridge_incomplete`; use the Cathay
annual/interim primary-driver layers, current risk metrics and current
expectations separately until a comparable Cathay history is built.

## Trade-construction checklist before choosing direction

For either candidate, the final pitch must still quantify:

1. revenue bridge: capacity × traffic/load factor × yield/mix;
2. cost bridge: fuel, non-fuel unit cost, FX and fuel surcharge pass-through;
3. earnings bridge: reported baseline → H1/H2 estimate → FY2026 consensus;
4. valuation bridge: current price versus implied margin/growth assumptions;
5. catalyst timing and expected information surprise;
6. market beta, country, industry, size, growth, momentum, volatility and
   liquidity exposures; and
7. invalidation, drawdown contribution and position sizing.

The existing beta/correlation fields are mechanical diagnostics, not a formal
Barra neutralization. Borrow data remains unavailable and should be checked at
execution time, but it is not being used as a research-universe gate.

## Next research actions

1. Reconcile Spring/Juneyao and Southern/Eastern FY2025 and 1H2025 bridge rows
   against official issuer pages for the metrics used in the final model.
2. Refresh the two pairs immediately after the scheduled 1H2026 reports and
   compare actual revenue, yield, fuel cost, cash flow and guidance against the
   current consensus snapshot.
3. Add a scenario table for each pair: bear/base/bull demand, market share,
   yield/mix, gross margin and fuel-price assumptions.
4. Only after those checks decide whether the core expression is an outright
   position, a pair, or a basket, and write the formal long/short pitch.
