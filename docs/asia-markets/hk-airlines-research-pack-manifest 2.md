# Hong Kong / Mainland Airlines Research-Pack Manifest

Status: P0 personal long/short research pack, point-in-time snapshot
2026-08-07. This manifest is the single navigation index for the airline
evidence layers; it is not a trade recommendation and does not rank long or
short directions.

## Universe

Cathay Pacific (`0293.HK`), Air China (`0753.HK` / `601111.SH`), China
Southern (`01055.HK` / `600029.SH`), China Eastern (`0670.HK` / `600115.SH`),
Spring Airlines (`601021.SH`), Juneyao Airlines (`603885.SH`) and Hainan
Airlines Holdings (`600221.SH`). China Eastern's canonical H-share key is
`0670.HK`; `00670.HK` is treated as a legacy alias only.

## Requirement-to-artifact map

| Research question | Primary artifact | Current evidence | Binding caveat |
|---|---|---|---|
| Jet fuel / crude / FX regime | `airline_energy_prices.parquet`, `airline_fx_rates.parquet` | EIA daily/weekly jet fuel, Brent, WTI and ECB USD/CNY/USD/HKD; latest observations are retained separately from retrieval time | Benchmarks/reference FX are not company purchase prices, hedge accounting or live prices at every cutoff |
| Fuel pass-through | `airline_fuel_surcharges.parquet`, chain and pair matrix surcharge fields | Cathay and mainland passenger surcharge schedules with effective dates | Route/policy context, not realized fuel-cost recovery |
| Passenger/cargo supply-demand | `china_airlines_monthly.parquet`, Cathay traffic artifact, `airline_operating_diagnostics.csv`, `airline_sector_external_outlook.csv` | Mainland monthly ASK/RPK/passengers/cargo through 2026-06; Q2/June equal-period diagnostics; IATA/CAAC sector forecasts and actuals | Monthly releases are preliminary/unaudited; July 2026 mainland bulletins were not found at the 2026-08-07 cutoff |
| Yield / RASK / CASK / fuel cost | `airline_earnings_driver_comparability.csv`, `airline_official_report_drivers.csv`, Cathay annual/interim driver snapshots | 560 canonical rows across 16 issuer-periods and 35 definitions, including reported and separately labelled derived proxies | Native units/currencies and issuer scope must remain attached; missing disclosures are not zeros |
| Hedging | `airline_hedging_disclosures.csv`, earnings-driver layer, chain/pair fields | Primary-report fair value, notional, policy and explicit no-futures statements where safely anchored | Fair value, notional, qualitative policy and no-futures statements are not interchangeable |
| Latest formal results | Cathay interim driver snapshot; mainland official report registry/drivers | Cathay 1H2026 official results (released 2026-08-05); mainland controlling reports are FY2025/1H2025 until 1H2026 filing | Six mainland 1H2026 filings remain scheduled/no-match at this snapshot; scheduled date is not actual disclosure |
| Historical financial trends | `airline_financial_history_trend.csv` | 3,175 rows from 2016 to latest available provider period across six mainland groups, covering revenue, cost, profit, cash flow, EPS, margins, ROE and debt/assets | AkShare/Sina provider history has period-end but no issuer announcement date; use for trend/model calibration, not strict PIT backtesting |
| Synchronized historical earnings bridge | `airline_historical_earnings_bridge.csv` | 246 company-period rows from 2016-03-31 to 2026-03-31, joining financials, monthly ASK/RPK/passengers/cargo/load factors, fuel/FX benchmarks and separate current consensus fields | Financial history is period-end-only; current consensus is a snapshot, not a historical vintage; fuel/FX are sector benchmarks |
| Guidance / warnings / catalysts | `airline_event_timeline.csv`, `airline_guidance_coverage.csv`, filing watch | Dated issuer guidance and H1 preliminary warning ranges with official source lineage where available | Warning is unaudited; absence of guidance is explicit and not a forecast of zero |
| Consensus / sell-side estimates | `airline_consensus_freshness.csv`, `airline_consensus_dispersion_all.csv`, `airline_revision_evidence.csv`, `airline_sell_side_revenue_forecasts.csv` and revisions | Current A/H/Eastmoney/Yahoo snapshots plus dated EPS/profit/rating and PDF revenue evidence; PDF revenue layer has 95 forecasts and latest report date 2026-05-05 | Free sources do not provide a complete broker-vintage tape; 10jqka revenue tooltip rows are page-snapshot-only because institution report dates are absent |
| News / event timeline | `airline_news_events.csv`, `airline_consensus_events.csv`, `airline_event_timeline.csv` | 79 public news-window records, 330 consensus/rating events and curated issuer events | Discovery window, not a complete archive, sentiment model or alpha signal |
| Risk / pair construction | `airline_market_risk_metrics.csv`, `airline_pair_risk_metrics.csv`, `airline_pair_factor_diagnostics.csv` | Free beta, volatility, drawdown, turnover and mechanical hedge diagnostics for 21 pairs | Not formal Barra neutralisation; borrow availability/cost/recall remain unavailable and are not a hard gate |
| Pair-level thesis inputs | `airline_pair_screening_matrix.csv` | 21 unordered pairs, 181 columns: readiness, expectations, demand/capacity, unit-cost/cargo drivers, fuel shocks, surcharge context and lineage | Descriptive deep-dive gate only; no direction or trade recommendation |
| Historical pair thesis inputs | `airline_pair_historical_bridge.csv` | 21 pair rows covering FY2019/FY2024/FY2025 and Q1 2025/Q1 2026 margin, revenue-growth, demand-capacity, fuel-regime, consensus and anomaly differentials | Core/backup/cross-market buckets are research priorities, not trade directions; Cathay rows have partial historical bridge coverage |
| Pair scenario stress tests | `airline_pair_scenario_inputs.csv` | 63 rows: bear/base/bull cases for 21 pairs using current FY2026 A-share detailed revenue/profit expectations | Mechanical consensus +/-5% revenue and +/-2pp margin stress tests; not independent forecasts or trade recommendations |
| Pre-H1 core-pair scenario bridge | `airline_pre_h1_scenario_bridge.csv` | Six Spring/Juneyao rows joining FY2025 actual USD financials, FY2026 consensus freshness/analyst count, Q2/June operating diagnostics, fuel overlay and 2026-08-29/31 report catalysts | Mechanical pre-event stress test only; fuel overlay excludes hedging/pass-through and 1H2026 actuals remain pending |
| Forecast assumptions and risk register | `airline_forecast_assumptions.csv`, `airline_risk_invalidation_matrix.csv` | Observed sector/company H1 anchors, explicit bear/base/bull assumptions, validation KPIs and sector/company invalidation triggers | Research-only framework; 9 Air operator-level forecast gaps, preliminary monthly data and all modelled assumptions remain explicitly labelled |
| Company financial forecast bridge | `airline_company_financial_forecast_bridge.csv` | FY2025 ASK/RPK and group RASK/CASK proxies bridged to FY2026 scenario revenue, cost, operating profit and earnings proxies versus current consensus for Spring/Juneyao; 9 Air pending row | Mechanical driver bridge, not issuer guidance or a long/short recommendation; Juneyao is consolidated and fuel overlay is a sensitivity, not a hedge/pass-through forecast |
| Six-company forward earnings bridge | `airline_forward_earnings_bridge.csv` | 18 bear/base/bull rows across six mainland groups, joining H1 traffic run-rates, ASK/RPK/LF, yield/RASK/CASK, revenue/profit proxies, consensus gaps, fuel overlay, HSR coverage and Juneyao/9 Air scope context | Research model rather than issuer guidance; fuel overlay is excluded from core earnings, and Air China/Eastern use an explicit consensus-margin fallback because FY2025 profit is negative |
| 21-pair forward scorecard | `airline_pair_scorecard.csv` | All 21 pairs ranked with a transparent 100-point direction-neutral score; current output has one core research candidate and three backups | Selection buckets are deep-dive priorities only; they do not assign long/short direction, factor neutrality or locatable borrow |
| Six-company invalidation rules | `airline_forward_invalidation_rules.csv` | 24 rules covering demand/capacity, pricing, fuel/cost and profit/scope for each mainland group, with leading indicators and formal triggers | Monitoring contract only; a rule is not marked as breached until the dated validation observation is captured |
| Interim claim validation queue | `airline_h1_claim_validation_queue.csv` | 16 pre-event claims covering H1 operating KPIs, RASK/CASK/profit, Juneyao warning reconciliation and 9 Air standalone disclosure | Formal actuals and pass/fail are intentionally blank before the scheduled issuer reports; missing standalone 9 Air P&L is not zero |
| Sector and company fundamentals | `airline_company_fundamentals.csv`, `airline_scope_reconciliation.csv`, `airline_hsr_route_candidates.csv`, `airline_hsr_route_query_queue.csv`, `airline_hsr_route_observations.csv`, `airline_sector_event_calendar.csv`, `hk-airlines-sector-map.md` | Business-model, hub, region, cargo, cost, HSR-candidate, leg-level queue, verified dated Ctrip route observations, scope and event-calendar layer for seven names | Juneyao FY2025 group scope is confirmed, but Spring versus Juneyao remains a model-mix comparison; only a small route sample has rail observations and access-time/ASK weighting remains pending |
| Juneyao / 9 Air scope bridge | `airline_juneyao_9air_scope_reconciliation.csv` | 28 FY2025/1H2025 group/component rows with passenger and fleet residual checks, component shares, group-only financial/capacity statuses and primary-report lineage | Only FY2025 passengers/fleet reconcile to standalone components; no unsupported allocation of ASK/RPK/revenue/cost/fuel/profit |
| Comparable yield / pricing panel | `airline_yield_pricing_matrix.csv` | 12 rows across six mainland groups and FY2025/1H2025, with reported/derived yield, passenger/cargo mix, ASK/RPK, LF, RASK/CASK and issuer source lineage | Company-period pricing is available, but route fare, booking-window, fare-class and ancillary time series remain a research gap; `reported_yield_only` is not a complete mix bridge |
| Fuel pass-through / hedge panel | `airline_fuel_pass_through_hedge_matrix.csv`, `airline_yield_fuel_research_queue.csv` | 12 rows separating fuel cost, mechanical fuel shock, mainland surcharge schedule, primary hedge anchors and explicit missingness; 48 field-level research tasks | Surcharge is schedule context rather than realized recovery; fair value, notional, policy and no-anchor scan results are not interchangeable |
| HSR coverage expansion | `airline_hsr_research_coverage.csv` | Six-company coverage summary of event-driven route candidates, query legs, verified observations and ASK-weighted legs | No candidate extraction is not zero HSR exposure; future travel dates in observations do not change the source/query PIT cutoff |
| Primary financial reconciliation | `airline_primary_financial_reconciliation.csv` | 60 official-versus-provider rows across six mainland groups, FY2025/1H2025 and five metrics | Revenue/profit/cash-flow/EPS mostly match where populated; operating-cost mismatches are retained for scope review and do not automatically control CASK |
| Core pair model / thesis draft | `airline_core_pair_model_inputs.csv`, `spring-juneyao-thesis-draft.md` | Compact two-leg model inputs and first working direction-neutral long/short draft for Spring–Juneyao | Working candidate only; final direction awaits 1H2026 primary results and post-result consensus revisions |

## Preferred long-form chain

Use `airline_research_chain.csv` as the thesis navigation layer. It currently
contains 688 rows across nine stages:

`supply → demand → revenue → cost → earnings → expectations → forecast → catalyst → risk`

Every populated row retains a source field and as-of date. The chain adds no
new issuer or broker estimate; it joins the expectation bridge, official driver
layer, mechanical forecast bridge, revision evidence, fuel scenarios, news,
event and risk layers. The pair matrix is the wide per-leg view; the chain is
the auditable source-linked view.

## Point-in-time rules

1. Keep observation/report/announcement date separate from `retrieved_at`.
2. Preserve native currency and unit next to every monetary or operational value.
3. Do not mix Cathay HKD aggregates with mainland RMB aggregates.
4. Do not annualise Cathay 1H2026 or treat mainland FY2025 as a 1H2026 actual.
5. Treat missing, scan-gap and query-scoped no-match fields as missingness, not zero.
6. Treat mechanical fuel shocks, implied H2 profit and RPK-minus-ASK gaps as diagnostics, not forecasts.
7. Treat exchange eligibility and public short activity as implementation context, not locatable borrow.

## Refresh order

For a new cutoff, refresh source layers first, then rebuild derived layers:

1. `run-energy-prices`, `run-fx-rates`, `run-fuel-surcharges`
2. operating releases/freshness/diagnostics and official filing watch
3. official reports, financial drivers, guidance and news
4. A/H consensus, public report evidence, sell-side revenue and revision layers
5. sector expectations, fuel sensitivity, expectation bridge, yield/fuel/HSR framework and research chain
6. market risk, pair risk, pair readiness, factor diagnostics and pair screening

The companion quality audit is
[`hk-airlines-data-quality-audit.md`](hk-airlines-data-quality-audit.md).
The current airline suite has 182 tests; formal mainland 1H2026 filing
reconciliation remains an external future-state update rather than a backfilled
value.
