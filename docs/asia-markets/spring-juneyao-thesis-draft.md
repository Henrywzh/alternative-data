# Spring Airlines / Juneyao Airlines — Working Long/Short Thesis

Status: first draft, 2026-08-07. This is a research candidate, not a final
trade recommendation. The working expression is **long Spring Airlines / short
Juneyao Airlines**, subject to the 1H2026 primary-report check.

## One-line idea

Spring has delivered a persistent profitability and utilization premium, while
the current market data shows that its revenue-multiple premium does not
translate into a higher consensus net-profit multiple. The trade is attractive
if Spring's operating advantage persists and Juneyao's lower-margin recovery is
already too fully reflected in its share price.

## Current evidence

| Metric | Spring | Juneyao | Implication |
|---|---:|---:|---|
| FY2025 revenue | USD3,065m | USD3,214m | Similar scale |
| FY2025 attributable profit | USD331.0m | USD148.5m | Spring +USD182.5m |
| FY2025 net margin | 10.80% | 4.62% | Spring +6.18pp |
| FY2025 passenger load factor | 91.53% | 85.63% | Spring +5.90pp |
| FY2025 CASK | RMB0.300 | RMB0.345 | Spring lower cost |
| FY2025 fuel cost / ASK | RMB0.1009 | RMB0.1135 | Spring lower fuel cost per ASK |
| 1H2025 net margin | 11.34% | 4.57% | Spring +6.77pp |
| 1H2025 passenger load factor | 90.52% | 85.17% | Spring +5.35pp |
| Q1 2026 provider net margin | 16.19% | 7.36% | Spring +8.83pp |
| Q1 2026 demand-capacity gap | +2.64pp | +1.98pp | Spring +0.66pp |
| FY2026 consensus net profit | USD312.7m | USD137.4m | Spring +USD175.3m |
| FY2026 implied consensus margin | 8.51% | 3.75% | Spring +4.76pp |
| Market cap / consensus revenue | 1.80x | 0.97x | Spring +0.83x premium |
| Market cap / consensus net profit | 21.2x | 25.9x | Spring is cheaper on profit |

Sources: `airline_core_pair_model_inputs.csv`, official driver layer,
`airline_pair_historical_bridge.csv` and the 2026-08-07 market-expectations
snapshot. USD values are translated at the stored snapshot/period FX. Current
consensus is asynchronous public discovery data, not a complete broker-vintage
tape.

## Variant perception

The market appears to recognize Spring's scale and revenue quality: it assigns
Spring a material revenue-multiple premium. The less obvious point is that the
premium is not expensive on the current consensus profit base because Juneyao's
lower implied margin makes its consensus-profit multiple higher.

The key question is therefore:

> Will Spring's margin and load-factor premium persist long enough for the
> relative profit gap to remain wider than the valuation gap implies?

This is a relative thesis, not a claim that Spring is absolutely cheap.

## Earnings bridge

Spring's FY2025 official report gives USD3,065m revenue, USD331m attributable
profit, USD946m operating cash flow, 33.6% fuel-cost share and RMB0.300 CASK.
Juneyao reports USD3,214m revenue and USD148.5m attributable profit, with
RMB0.345 CASK and RMB0.1135 fuel cost per ASK. The official Juneyao FY2025
operating-cash-flow field is not safely populated, so it is not imputed.

The provider-versus-primary reconciliation matches revenue, profit, cash flow
and EPS where both values are available. Operating-cost values mismatch for
both companies in FY2025 and 1H2025, so the cost comparison uses the official
driver layer rather than provider operating cost.

## Scenario sensitivity

The mechanical scenario artifact applies consensus revenue -5%/0%/+5% and
implied net margin -2pp/0pp/+2pp to both legs:

| Scenario | Spring profit | Juneyao profit | Gap |
|---|---:|---:|---:|
| Bear | USD225m | USD59m | USD166m |
| Base | USD313m | USD137m | USD175m |
| Bull | USD408m | USD223m | USD185m |

The relative gap persists under common shocks, but this is only a symmetric
stress test. It does not model a Spring-specific disruption, Juneyao-specific
recovery or different fuel/passenger sensitivities.

## Catalyst

- Spring 1H2026 formal report: scheduled 2026-08-29.
- Juneyao 1H2026 formal report: scheduled 2026-08-31.
- Monthly operating releases through 2026-06 are available; July data was not
  found at the 2026-08-07 cutoff.

The primary catalyst test is whether the reported H1 revenue, yield, CASK,
fuel cost and cash flow preserve the relative advantage shown in the monthly
data and current consensus.

## Invalidation conditions

The long-Spring/short-Juneyao direction should be reconsidered if:

- Spring's H1 net margin or CASK advantage compresses materially;
- Spring's RPK-minus-ASK advantage turns negative while Juneyao remains positive;
- Spring's consensus-profit advantage is revised away without a comparable
  Juneyao downgrade;
- Juneyao's reported yield and cost improvement closes most of the 6pp
  historical margin gap; or
- Spring's valuation premium widens faster than its earnings advantage.

## Risk and construction

The current one-year pair diagnostic shows approximately 0.76 correlation,
Spring-to-Juneyao beta of 0.63, hedged-spread volatility of 19.0% and maximum
drawdown of about -14.2%. These are mechanical diagnostics, not Barra
neutralization. The final trade must separately check market beta, China
airline/consumer factors, size, momentum, liquidity, currency and drawdown
contribution. Borrow availability and cost remain unavailable from the current
free data pack.

## Decision gate after 1H2026

Before converting this draft into a final pitch, update the model with:

1. official H1 revenue, passenger/cargo yield, CASK, fuel cost and cash flow;
2. the first post-result consensus revisions and target-price changes;
3. July/August operating data when released;
4. a company-specific rather than symmetric fuel/demand scenario; and
5. the final beta/factor-aware sizing and drawdown limit.
