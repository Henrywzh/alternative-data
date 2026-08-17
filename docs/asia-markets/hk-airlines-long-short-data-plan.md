# Hong Kong / China Airlines Long-Short Data Plan

Status: P0 research build, 2026-08-07. This is a personal long/short
research project. The purpose of this note is to complete a point-in-time
evidence pack before selecting a pair; it is not yet a trade recommendation.

The companion [free online data-source research note](airline-free-data-source-research.md)
records the additional official/open sources reviewed on 2026-08-09, their
point-in-time and access limitations, and the P0/P1 ingestion order for the v3
earnings model. It is intentionally separate from the normalized data tables.

## Research universe

The initial comparable set is Cathay Pacific (`0293.HK`), Air China
(`0753.HK`, `601111.SH`), China Southern (`01055.HK`, `600029.SH`), China
Eastern (`0670.HK`, `600115.SH`), Spring Airlines (`601021.SH`), Juneyao
Airlines (`603885.SH`) and Hainan Airlines Holdings (`600221.SH`). The first
screen should distinguish Cathay's Hong Kong hub/international exposure from
the mainland carriers' domestic, regional, international and state-policy
exposure. Airports, aircraft lessors and cargo-only names are adjacent
comparables, not automatically eligible pair legs.

## Data already available

- `data/processed/airline_traffic/china_airlines_monthly.parquet` contains
  monthly passenger, ASK, RPK, load-factor and cargo fields for six mainland
  listed airline groups, generally from 2016-01 through 2026-06. Each KPI row
  now retains the Cninfo announcement date/time, announcement ID, issuer PDF
  URL, source quality and retrieval timestamp. The separate operating-events
  file carries disclosed fleet/route events with the same PIT metadata, while
  `airline_operating_release_registry.csv` provides one release row per
  carrier/month. `airline_operating_freshness.csv` is the six-row companion
  check for whether the expected prior-month bulletin exists at the stated
  snapshot; on 2026-08-07 it found no 2026-07 bulletin for any of the six
  names, so no July KPI is imputed.
- `airline_operating_diagnostics.csv` adds a six-row Q2/June diagnostic from
  the same monthly issuer-release archive. It compares equal-period ASK, RPK,
  passenger and cargo growth, weighted load factors and the demand-capacity
  gap; it is especially useful for separating a post-March supply/demand
  deterioration from a benign H1 aggregate.
- The transport artifact contains Cathay passenger and cargo traffic history,
  report-period fleet signals and the same mainland airline operating layer.
  Monthly operating releases are preliminary/unaudited and issuer scope must
  remain visible.
- `data/normalized/hk_transport/airline_energy_prices.parquet` contains EIA
  daily and weekly WTI, Brent and Gulf Coast kerosene-type jet-fuel spot
  benchmarks. The current live pull covers daily data through 2026-08-03 and
  weekly data through 2026-07-31, with the 2026-08-05 EIA release retained.
- `data/normalized/hk_transport/airline_fuel_surcharges.parquet` contains the
  current official Cathay schedule effective 2026-08-01 and mainland-China
  domestic passenger surcharge policy effective 2026-07-05. These are
  pass-through indicators, not realized accounting fuel recovery.
- `data/normalized/hk_transport/airline_fx_rates.parquet` contains ECB daily
  USD/CNY and USD/HKD reference rates from 2000-01-13 through 2026-08-06. The
  ECB public endpoint does not expose a complete historical release-vintage
  field, so the file retains observation date and retrieval timestamp and is
  not a full point-in-time revision history.
- `data/normalized/hk_transport/airline_cargo_demand_proxies.csv` is the first
  newly implemented P0 free-online source from the v3 research pass. It
  captures MOFCOM monthly total trade, exports, imports, balance and YoY rates
  in USD 100 million, with the raw JSON response and retrieval-vintage fields.
  It is a broad external cargo-cycle proxy, not airline cargo revenue or a
  full release-vintage series because the endpoint does not expose its original
  publication timestamp.
- `data/normalized/hk_transport/airline_caac_sector_monthly.csv` is the second
  live P0 source: official CAAC monthly PDFs backfilled from 2020-01 through
  2026-06, expanded into monthly/YTD sector observations with release dates.
  It adds sector passenger/cargo volume and turnover, utilization, load-factor
  and airport-throughput context; it is a regulator fast-report layer, not a
  company-specific yield or profit forecast. The current layer has 5,928 rows;
  2019 remains an explicit source gap rather than an interpolated history.
- `data/normalized/hk_transport/airline_postal_demand_proxies.csv` is the
  official State Post Bureau postal/express context layer. It contains 33
  normalized rows across 2025 H1, 2026 Jan-Apr and 2026 H1, with article
  release dates and normalized RMB-million / million-parcel units. It is a
  broad logistics proxy only; the v3 join keeps it separate from airline
  cargo revenue and enforces the model-date release cutoff.
- `data/normalized/hk_transport/airline_caac_route_licence_events.csv` is the
  dated CAAC 2026 summer/autumn planned-supply layer. It contains 53 route/
  cargo-licence additions and cancellations, including carrier, route, start
  date and stated initial frequency. It is a forward-capacity event layer,
  not realized ASK; v3 only carries route counts and frequency context.
- `data/normalized/hk_transport/airline_earnings_model_v3.csv` adds a separate
  bear/base/bull cargo-demand triangulation to the existing unit-economics
  bridge. It grows reported cargo revenue from CAAC/MOFCOM/State Post Bureau
  context where the official split is available, while other revenue is kept
  as a separately labelled passenger-growth residual; it does not treat these
  proxies as airline cargo revenue.
  `airline_earnings_model_v3_kpi_coverage.csv` is the explicit coverage
  contract: it marks each KPI `modelled`, `partial`, `proxy`, `snapshot` or
  `not_modelled`, so missing EPS/ancillary/cargo-yield/net-income bridges are
  not hidden by a populated revenue row.
- `data/normalized/hk_transport/airline_travel_demand_events.csv` adds the
  release-date-safe MOT/MCT holiday demand context layer. It is useful for
  sector regime and HSR-versus-air controls, but its sparse event grain is not
  a substitute for company ASK/RPK or realized yield.
- `data/normalized/hk_transport/airline_airport_traffic.csv` adds issuer
  monthly airport production statistics for Shanghai Pudong/Hongqiao,
  Shenzhen, Guangzhou Baiyun and Beijing Capital (2026-01 through 2026-06).
  Beijing Capital is parsed from the issuer's investor-relations monthly fast
  reports with release-date safety. It is a hub-demand context layer for
  Spring/Juneyao/9 Air base coverage and is not company revenue.
- `data/normalized/hk_transport/airline_cargo_airport_bridge.csv` adds the
  airport-cargo calibration layer that compares hub cargo throughput with
  company cargo tonnage and reported revenue, supporting the v3 cargo bridge.
- `data/normalized/hk_transport/airline_cargo_yield_bridge.csv` adds the
  forward cargo-revenue bridge: reported revenue-per-tonne anchors applied to
  H1-2026 tonnage, usable as an H1 evidence layer and for the H1-2026 report
  validation playbook.
- `data/normalized/hk_transport/airline_forward_assumptions.csv` adds the
  forward tax-rate and FX assumption table that the waterfall proxy consumes,
  including curated FY2025 tax anchors and the ECB USD/CNY carry.
- `data/normalized/hk_transport/airline_h1_2026_validation_playbook.csv` adds
  the H1-2026 report reconciliation table: all pre-report forecasts plus
  filing dates, ready for actuals and error columns after publication.
- `data/normalized/hk_transport/airline_cargo_bridge_backtest.csv` adds the
  cargo-bridge backtest with a 1H2025 yield-anchor holdout and the airport
  signal direction check.
- `data/normalized/hk_transport/airline_fuel_surcharge_recovery.csv` adds a
  dated surcharge-versus-EIA-fuel recovery proxy, giving the fuel pass-through
  KPI a measurable context signal instead of schedule text only.
- `data/normalized/hk_transport/airline_event_timeline.csv` records Cathay's
  2026 H1 formal results and preceding guidance/June operating update, plus the
  2026 H1 preliminary loss ranges for Air China, China Eastern and China Southern. Native HKD/RMB
  values are preserved alongside announcement-date USD translations using the
  FX layer; Air China, China Southern, China Eastern and Juneyao warning rows
  now point to official issuer/CNINFO PDFs and are marked `primary_issuer`.
  Cathay's formal-result outlook is also structured as a dated guidance row:
  approximately 10% 2026 passenger-capacity growth, strong Q3 summer demand,
  continued elevated fuel-price impact and cautious cargo peak-season optimism.
  It also records a Reuters-reported HSBC-versus-market 2026 Big Three profit
  expectation gap as a sector-level secondary event rather than assigning it
  to an individual airline.
- The event timeline now also includes Juneyao's 2026-07-11 H1 preliminary
  profit range of RMB140–210m and adjusted profit of RMB59–88.5m. The issuer
  attributes the deterioration to sharply higher Q2 aviation-fuel prices; the
  values remain unaudited pending the interim report. No comparable H1
  preannouncement was found for Spring or Hainan in this pass, so H1 earnings
  warnings remain explicitly unfilled rather than assigned a zero event. Their
  separate annual-report/investor-Q&A fleet guidance is retained below.
- Spring Airlines' 2026 annual-report guidance is now captured separately:
  planned introduction of 12 A320-series aircraft during 2026. This is a
  fleet/capacity input, not a direct passenger-demand forecast.
- `airline_consensus_events.csv` unifies dated EPS/revenue revision events and
  Cninfo rating events, while `airline_consensus_revision_pulse.csv` aggregates
  the public revision subset by company, metric, fiscal year and event date.
  Both preserve the sparse-public-feed caveat; the pulse is not a complete
  broker consensus curve and does not forward-fill missing dates.
- `airline_revenue_consensus_coverage.csv` is the share-class revenue coverage
  gate. It separates direct Yahoo estimates from same-company fallback and
  missing coverage, and records the explicit 100x conversion needed for
  Hainan's RMB100m detailed-indicator revenue unit.
- `airline_guidance_coverage.csv` is the company-level guidance gate. It
  distinguishes direct issuer guidance, warning-only coverage and no company
  guidance before the scheduled 1H2026 report, while retaining the formal
  filing catalyst and source lineage.
- `airline_hedging_disclosures.csv` is the dedicated primary-report hedge
  layer. It separates Eastern FY2025's RMB3.75m fair-value change/ending fair
  value from its 500,000-barrel open position, records Southern's explicit
  FY2025/1H2025 no-fuel-futures statements and keeps Eastern 1H2025's
  qualitative policy statement separate from numeric evidence. Eight other
  mainland report-period rows are scan-result gaps, not zero hedging.
- `airline_pair_screening_matrix.csv` consolidates the 21 unordered pair
  combinations into a non-directional deep-dive gate, combining data
  comparability, expectation evidence, profit-base stability, catalyst stage
  and mechanical hedge/liquidity diagnostics. It also exposes each leg's
  dated revision counts, up/down balance and latest revision date without
  assigning trade direction, alongside per-leg revenue-multiple and consensus-
  margin dispersion for later mispricing analysis.
  The current matrix also carries latest comparable-period issuer-driver
  values for cargo yield/load factor, fuel cost per ASK, non-fuel ATK cost,
  operating cash flow, fuel intensity and fuel hedging, with per-leg
  native-unit/currency/as-of metadata; these fields are descriptive and do
  not assign pair direction. It also carries per-leg ±5% fuel-profit impact
  scenarios, scenario methods, surcharge context and FX observation dates.
  It also carries per-leg 10jqka public-report dispersion counts, native-RMB
  medians, range widths versus median and latest dated report evidence, while
  keeping EPS/share and RMB100m profit/revenue units explicit.
- `airline_short_eligibility.csv` separates HKEX designated short-selling
  eligibility and SSE margin-detail presence from actual borrow feasibility;
  the latter remains a direct broker/prime-broker gap.
- `airline_stock_connect_short_selling.csv` adds 846 dated HKEX Stock Connect
  observations for the six A-share airline names, covering 2026-01-05 to
  2026-08-07. It preserves the exchange's literal `Available` display,
  numeric remaining balance where shown, daily/ten-day short-selling
  percentages and turnover shares/value. This is a low-weight implementation
  context layer, not locatable borrow or a directional short signal.
- `airline_sector_external_outlook.csv` adds dated IATA/CAAC sector context:
  forecast vintages, Asia-Pacific passenger/cargo actuals, CAAC June/1H2026
  China passenger/cargo/RPK/CTK/load-factor statistics, seasonal schedules and
  airport/holiday traffic. Passenger traffic, RPK, airport throughput and
  planned flights are kept as distinct measures.
- `data/normalized/hk_transport/airline_financial_driver_snapshot.csv` is the
  first detailed official driver snapshot for Cathay and China Southern. It
  includes Cathay 1H2025 versus 1H2024 passenger/cargo revenue and traffic
  metrics plus fuel cost, hedge result, fuel intensity, yield and ATK-cost
  fields; Southern adds FY2025 versus FY2024 revenue, cost, fuel, cash flow,
  traffic, yield and fleet fields. Monetary rows include period-end USD
  translations while physical KPIs remain in their operational units.
- `data/normalized/hk_transport/airline_cathay_annual_driver_snapshot.csv`
  adds 31 primary-issuer FY2025 rows from Cathay's official annual report,
  including group revenue/cost/fuel/hedge, passenger and cargo KPIs, ATK/RTK,
  yields, unit cost and balance-sheet liquidity. It is kept separate from the
  earlier 1H2025 briefing layer and uses explicit report pages/URLs.
- `data/normalized/hk_transport/airline_cathay_interim_driver_snapshot.csv`
  adds 43 page-anchored primary-issuer rows from Cathay's official 2026 Interim
  Results released on 2026-08-05. It includes group and segment revenue,
  operating-cost lines, gross/net fuel and hedging, recurring underlying profit,
  reported profit, operating cash flow, ASK/RPK/LF, yield, RASK proxy, ATK cost,
  cargo KPIs, liquidity and borrowings. Native HKD rows retain period-end USD
  translations; physical KPIs remain in operational units.
- `data/normalized/hk_transport/airline_official_report_registry.csv` and
  `airline_official_report_drivers.csv` now form the primary-issuer layer for
  six mainland listed airline groups. The registry covers FY2025 and 1H2025
  annual/interim reports with Cninfo URLs, report announcement dates, local
  PDF snapshots and parse status. The driver layer keeps RMB-million rows plus
  period-end USD translations and page-level evidence for revenue, operating
  cost, fuel, labor, depreciation, airport/landing, maintenance, cash flow,
  ASK, passengers, load factor, yield, utilization, fleet and derived
  RASK/CASK/fuel-per-ASK fields where scope permits, plus 11 primary consolidated
  total-liabilities anchors, issuer-report-derived liabilities-to-assets ratios,
  6 interest-bearing-debt anchors and 7 cash-capex anchors. Hainan passenger-and-other
  revenue is explicitly scoped, and `rask_from_reported_yield_derived` is used
  only where passenger revenue is not separately disclosed. It also captures the
  Eastern 1H2025 consolidated-note anchors for RMB61,813m passenger-service
  revenue and RMB2,577m cargo-service revenue, so that period uses reported
  passenger revenue for its labelled yield/RASK proxies. It also captures the
  quantified Eastern fuel-hedge fair-value row and fuel-price sensitivity,
  plus Air China/Juneyao fuel-cost sensitivity disclosures. Juneyao FY2025
  attributable profit is now anchored to page 7 of its primary annual report;
  Hainan 1H2025 keeps both the issuer-reported fuel-cost share/sensitivity from
  report page 19 and a separately labelled implied fuel-cost amount; no direct
  RMB fuel-cost line is promoted from that disclosure. A blank remains a
  disclosure or safe-parser gap: Southern FY2025 daily utilization is not
  filled by an estimate.
- `data/normalized/hk_transport/airline_consensus_snapshot.csv` contains a
  2026-08-07 public broker snapshot for the four HK-listed names across
  FY2026–FY2028. It includes native and USD EPS/net-profit ranges, HKD and USD
  target prices, broker counts, forecast-date ranges and raw rating labels.
  Revenue consensus and historical revisions are explicitly marked unavailable.
- `data/normalized/hk_transport/airline_financial_actuals_akshare_snapshot.csv`
  provides a six-company A-share discovery history through 2026-03-31 for
  revenue, operating cost, attributable profit, non-GAAP profit, operating
  cash flow, EPS, margins, ROE and debt/assets. Native RMB and period-end
  USD/CNY translations are kept together; the latest pull was retrieved on
  2026-08-06. The source is AkShare/Sina and does not expose issuer
  announcement dates, so `announcement_date_available=false` and
  `source_quality=akshare_discovery` are intentional.
- `data/normalized/hk_transport/airline_financial_history_trend.csv` is the
  explicit 2016-to-latest historical trend view of that provider archive. It
  contains the full available 2016-to-latest rows across six mainland groups and keeps FY/H1/Q1/Q3
  period types, native/USD values and provider source URLs. It is useful for
  multi-year revenue, cost, profit, cash-flow, margin, ROE and leverage trends,
  but its `period_end_only_no_announcement_date` status means it must not be
  used as a strict announcement-date PIT backtest without primary-report
  reconciliation.
- `data/normalized/hk_transport/airline_historical_earnings_bridge.csv` is the
  synchronized 250-row company-period panel across 2016-03-31 to 2026-03-31.
  The six mainland groups retain the long provider/monthly panel; Cathay adds
  four explicit official-driver rows for 1H2024, 1H2025, FY2025 and 1H2026.
  Cathay's rows retain HKD/group-scope and unit metadata and are marked
  partial rather than treated as like-for-like mainland history. The bridge
  aligns financial revenue/cost/profit/cash flow with ASK/RPK, passengers/cargo,
  load factors, period-average fuel/Brent and USD/CNY/USD/HKD benchmarks.
  Current HK broker and A-share detailed FY2026 consensus are separate fields,
  with explicit snapshot dates and unit normalization; it is not a historical
  consensus-vintage tape. Source-derived load-factor anomalies are retained
  and flagged rather than clipped.
- `data/normalized/hk_transport/airline_pair_historical_bridge.csv` converts
  the company-period panel into 21 pair rows. It compares FY2019/FY2024/FY2025
  profitability, Q1 2025/Q1 2026 demand-capacity changes, current consensus
  dispersion, fuel-regime changes, risk/readiness fields and source anomalies.
  Spring–Juneyao is tagged `core_candidate`, Southern–Eastern is tagged
  `backup_candidate`, and Cathay combinations are `cross_market_backup` with
  an explicit partial-history status.
- `data/normalized/hk_transport/airline_pair_scenario_inputs.csv` provides
  63 transparent bear/base/bull rows for all 21 pairs. It applies the same
  explicit revenue and margin shocks to both legs around the current A-share
  detailed FY2026 snapshot; replace these assumptions after primary 1H2026
  results rather than treating them as forecasts.
- `data/normalized/hk_transport/airline_primary_financial_reconciliation.csv`
  compares provider history with covered official FY2025/1H2025 reports for
  revenue, operating cost, attributable profit, operating cash flow and EPS.
  It confirms the core/backup revenue and profit anchors while flagging a
  systematic operating-cost definition mismatch that must be resolved before
  using provider cost values in the final unit-cost model.
- `data/normalized/hk_transport/airline_core_pair_model_inputs.csv` is the
  compact two-row Spring/Juneyao model entry point, combining official FY2025/
  1H2025 drivers, Q1 2026 operating context, current market expectations,
  scenarios and reconciliation statuses. The working draft is
  `docs/asia-markets/spring-juneyao-thesis-draft.md`.
- `data/normalized/hk_transport/airline_consensus_ashare_snapshot.csv` adds
  public 10jqka forecast ranges for the same six A-share groups across
  FY2026–FY2028: EPS, net profit, low/average/high values, forecast count,
  industry average and institution-report date bounds. Net profit is stored
  in RMB 100 million and translated at the retrieval-date USD/CNY snapshot;
  this is a comparison convention, not a forward-FX forecast. Historical
  estimate revisions remain unavailable.
- `data/normalized/hk_transport/airline_consensus_ashare_detailed.csv` adds
  the separate 10jqka detailed-indicator average forecasts for FY2026–FY2028:
  revenue, revenue growth, profit before tax, detailed net profit, net-profit
  growth and ROE. It is explicitly an average-only discovery layer without
  metric-level low/high ranges, broker counts or complete estimate vintages;
  direct HK revenue estimates, where available, come from the separate vendor
  revenue layer rather than this A-share detailed layer.
- `data/normalized/hk_transport/airline_consensus_em_snapshot.csv` adds a
  separate current Eastmoney/AkShare layer with FY2025–FY2028 EPS, six-month
  research-report counts and rating buckets. It is useful for measuring
  expectations breadth and rating crowding, but it has no historical broker
  revision vintages; its snapshot date is therefore a hard analytical boundary.
- `data/normalized/hk_transport/airline_cninfo_rating_events.csv` adds 168 dated
  Cninfo rating events from selected and 2026 business-day queries, including prior
  rating, rating-change label, institution and target-price range. It is a
  useful point-in-time rating-event history, but the explicit queried-date
  scope means it cannot be treated as a complete daily rating or earnings
  revision series.
- `data/normalized/hk_transport/airline_revision_coverage.csv` summarizes the
  evidence boundary for each of the seven names, separating true broker
  revisions, public EPS/revenue revision proxies, dated rating events,
  current-only consensus and Yahoo share-class revision/rating coverage. Use
  this as a data-readiness gate before treating a company as a serious pair
  candidate; Yahoo fields remain vendor snapshots, not full broker vintages.
- `data/normalized/hk_transport/airline_pair_readiness.csv` turns that evidence
  into a non-directional thesis-preparation gate, separating core actuals,
  demand/fuel/expectations, revision evidence, catalyst timing, unstable
  profit bases and market-risk/borrow caveats. It is deliberately not a
  long/short ranking.
- `data/normalized/hk_transport/airline_research_data_completeness.csv` is the
  final pre-pair evidence audit. It records 15 company-level domains for all
  seven names plus shared energy/FX, surcharge and sector-outlook rows, with
  explicit coverage, PIT status, source quality and limitations. Use it to
  decide whether a pair is research-ready; it does not select direction.
- `data/normalized/hk_transport/airline_news_events.csv` adds a current public
  news window for all seven names, with publication timestamp, source URL,
  keyword event category and relevance scope. Use it for catalyst discovery and
  manual verification, not as an automatic sentiment or alpha signal.
- `data/normalized/hk_transport/airline_research_chain.csv` materializes the
  auditable supply/demand→revenue→cost→earnings→expectations→catalyst→risk
  chain for each name. It also carries dated estimate-revision counts and
  up/down direction evidence where the sparse public revision layer has coverage,
  plus latest event metric/value/unit/source details and ±5% fuel-shock USD
  impacts with method/FX lineage, plus latest public-news-window counts/title/
  source discovery fields. It is the preferred long-form input for a future
  dashboard or thesis template because every row retains its upstream source
  field and as-of date. The expectations stage now also includes the three
  A/H-paired names' HK-versus-A-share profit-consensus gap, sign disagreement,
  zero-crossing and warning-alignment diagnostics. For Air China, Southern,
  Eastern and Juneyao it also computes the mechanical FY2026-consensus-minus-
  H1-warning implied 2H profit in RMB million; this makes the recovery implied
  by the market explicit without presenting it as our forecast. It also carries
  the FY2025-minus-1H2025 historical 2H profit base and the implied-minus-
  historical gap for the same four names. It also carries each company's H1
  RPK-minus-ASK growth gap as a demand-versus-capacity diagnostic.
- `data/normalized/hk_transport/airline_consensus_dispersion_all.csv` extends
  the HK/A-share profit-consensus reconciliation to all seven names. It keeps
  market ranges separate and flags sign disagreement, zero-crossing ranges,
  single-market coverage and rating breadth before any pair is selected.
- `data/normalized/hk_transport/airline_market_risk_metrics.csv` adds free
  historical return, volatility, drawdown, benchmark beta/correlation and
  USD-turnover proxies for factor and liquidity checks. The companion
  `airline_short_side_proxies.csv` adds HKEX regulated short-turnover and SSE
  margin-short balance/volume observations at the latest market cutoff. These
  improve observable short-side context, while borrow availability, borrow
  cost, recall risk and broker-specific short-sale constraints remain explicit
  missing data.
- `data/normalized/hk_transport/airline_pair_risk_metrics.csv` provides the
  21 pair-level correlation and beta-hedge diagnostics needed before choosing
  a hedge leg. It includes spread volatility and observations, but does not
  claim factor neutrality, borrow feasibility or a preferred pair.
- `data/normalized/hk_transport/airline_pair_factor_diagnostics.csv` adds
  free-data proxies for benchmark beta, size, value/revenue, momentum,
  volatility, drawdown and mechanical beta hedge ratios across all 21 pairs.
  These are a pre-trade diagnostic layer only: they are not formal Barra
  exposures, factor neutralization, borrow feasibility or a directional signal.
- `data/normalized/hk_transport/airline_sell_side_reports_akshare_snapshot.csv`
  stores the public Eastmoney research-report discovery feed with report date,
  institution, rating, forecast EPS/PE and original PDF URL. It is a review
  queue for manual primary-source checking, not a complete sell-side archive.
- `data/normalized/hk_transport/airline_sell_side_forecast_revisions.csv`
  converts those dated reports into same-institution, same-fiscal-year EPS
  changes versus the prior available report. It is a useful revision-direction
  signal, but not a complete broker estimate-vintage tape because the public
  feed can omit reports, change coverage and mix report types.
- `data/normalized/hk_transport/airline_public_report_evidence.csv` adds a
  refreshable public 10jqka evidence layer for the six mainland groups. It
  preserves visible institution report dates and revision markers for EPS/net
  profit, while explicitly keeping institution-level revenue rows as
  `page_snapshot_only` because their row-level dates are not exposed.
- `data/normalized/hk_transport/airline_yahoo_analyst_snapshot.csv` adds a
  free vendor cross-check for revenue/EPS estimate ranges, 7/30-day EPS
  revision counts, recommendation trends and growth estimates across the
  available share classes. It is useful for current expectation direction and
  rating breadth, but its `yfinance_discovery` quality and
  `revision_history_available=False` mean it cannot replace dated broker-PDF
  revisions.
- `data/normalized/hk_transport/airline_filing_calendar.csv` is a dated
  discovery snapshot for 1H2026 report schedules. As of 2026-08-07, all six
  mainland names were scheduled rather than actually disclosed: Hainan
  2026-08-25; Southern and Spring 2026-08-29; Air China, Eastern and Juneyao
  2026-08-31. Scheduled dates remain separate from actual disclosure dates and
  must be confirmed against SSE/Cninfo filings. Cathay is tracked separately:
  its official 2026 interim results were released on 2026-08-05.
- `data/normalized/hk_transport/airline_official_filing_watch.csv` is the
  direct CNINFO evidence watch for the same six names. It keeps the scheduled
  date separate from a query-scoped official-report match and is append-only by
  company/snapshot date. The current snapshot has no 1H2026 full-report match;
  once disclosed, it will retain the announcement date, ID and PDF URL.
- `data/normalized/hk_transport/airline_market_snapshot.csv` and
  `airline_market_expectations_snapshot.csv` align current A/H-share prices,
  native market caps, USD market caps, FY2026 EPS/net-profit expectations,
  USD-normalized EPS/net-profit/revenue/target-price views, A-share detailed
  revenue/revenue-growth expectations, forward-PE proxies and HK target-price
  upside on the 2026-08-06 observation date. Quotes and market
  caps retain separate timestamps. Market-cap history is not implied; this is
  a current snapshot for valuation and trade construction. The bridge now uses
  Yahoo Finance revenue estimate avg/low/high/analyst-count data for nine
  share classes; Hainan falls back to the 10jqka average-only layer. These are
  vendor/discovery estimates, not complete broker-vintage histories.
- `data/normalized/hk_transport/airline_expectation_bridge.csv` is the derived
  10-share-class bridge from H1 operating trend to latest financial driver,
  revenue/profit expectations, valuation, catalyst, formal-report
  status/scheduled date and current weekly energy benchmark. It preserves the
  period label for each financial actual and carries the latest dated HK broker
  observation plus an explicit true-revision count. It also carries matched
  consensus as-of dates, age/freshness bands and revision-history availability
  for the revenue/profit, HK broker and public sell-side layers, including the
  actual matched source-layer name for fallback cases such as Hainan. It is a
  navigation layer rather than a new source of facts.
- The expectation bridge also carries exact-share-class Yahoo short-horizon EPS
  revision counts and current recommendation breadth where available. These
  fields help cross-check expectation direction, but retain the vendor's
  `yfinance_discovery` quality and do not become a dated broker-event signal.
- `data/normalized/hk_transport/airline_earnings_driver_comparability.csv`
  is the canonical KPI comparison matrix built from those official layers and
  Cathay's report-period driver files. It covers revenue/profit/cash flow,
  ASK/RPK/passengers/load factors, passenger/cargo yields, operating/fuel cost,
  CASK/RASK proxies, hedge/sensitivity, fleet and utilization. It keeps source
  metric/unit/page and marks every row as issuer-reported, derived or missing;
  `common_FY2025` and `common_1H2025` are cohort labels rather than a claim
  that every metric is disclosed by every issuer.
- `data/normalized/hk_transport/airline_sector_expectation_snapshot.csv`
  aggregates the six mainland A-share groups in RMB and retains separate
  company rows for the mainland groups and Cathay. It combines H1
  capacity/traffic/load-factor trends, FY2025 actuals and ASK/RPK/load-factor/
  yield/RASK/CASK unit economics, FY2026 consensus,
  fuel-cost share, warning counts, broker-evidence coverage, unified estimate-
  revision direction and formal-report catalysts, with explicit coverage counts
  for incomplete metrics. It also
  carries the latest weekly jet-fuel/Brent benchmark in USD, USD-normalized
  FY2026 revenue/profit consensus and a revenue-based market-cap multiple;
  profit-based valuation is marked unstable if any constituent consensus range
  crosses zero.
- `data/normalized/hk_transport/airline_sell_side_revenue_forecasts.csv` and
  `airline_sell_side_revenue_revisions.csv` contain dated revenue tables
  extracted from public Eastmoney-linked sell-side PDFs. The current run has
  95 forecast rows and 48 prior comparisons for five mainland groups; each row
  retains report date, institution, PDF URL and source page. The latest
  extracted mainland PDF observation is dated 2026-05-05, so the layer is
  useful for revision direction but remains sparse and is not a complete broker
  consensus tape.
- `data/normalized/hk_transport/airline_fuel_sensitivity_scenarios.csv` adds
  -20% to +20% fuel-price shocks for the seven underlying groups, using issuer
  5% sensitivity where available and clearly labelled mechanical proxies
  elsewhere. Current EIA jet-fuel observation, ECB FX quote/observation date,
  native-currency fuel-price views and USD-normalized cost/profit impacts,
  plus surcharge context, remain attached to each scenario. FX is a
  translation snapshot rather than a forward-FX assumption.
- `data/normalized/hk_transport/airline_sector_trend_snapshot.csv` summarizes
  2026H1 versus 2025H1 capacity, passenger traffic, cargo, load factors and
  six-company aggregate trends by carrier and region. It prefers issuer Total
  rows and otherwise sums regional rows to create an explicit synthetic Total.
  Every row carries a quality flag; large year-on-year moves remain review
  items rather than being smoothed away.
- `data/normalized/hk_transport/airline_cathay_sector_trend_snapshot.csv`
  applies the same 2026H1-versus-2025H1 schema to Cathay's issuer monthly
  traffic releases. Passenger counts and thousand traffic units are normalized
  into the mainland layer's units, and passenger/freight load factors are
  weighted from RPK/ASK and RFTK/AFTK. Cathay remains separate from the
  six-company mainland aggregate because issuer/group and Hong Kong-hub scope
  are not directly additive.
- `data/normalized/hk_transport/airline_hk_sell_side_forecasts.csv` contains
  82 dated broker observations for Cathay, Air China, China Eastern and China
  Southern, with FY2026–FY2028 net profit, EPS, target price and rating. The
  provider currently returns one latest row per broker/FY; the collector keeps
  an append-only history across refreshes. The paired
  `airline_hk_forecast_revisions.csv` compares prior rows when they become
  available; in the initial 2026-08-06 pull all 82 rows are initial
  observations, so there are currently zero genuine HK revisions.
- A 2026-08-07 refresh of the free HK/A-share providers added no new HK broker
  rows; the A-share discovery layer completed with 36 consensus rows, 108
  detailed-indicator rows across all six groups, 335 public report rows and
  179 EPS revision-proxy rows. Market quote/market-cap observations remain the
  separate 2026-08-06 snapshot and are not silently mixed into the 2026-08-07
  forecast retrieval cutoff. A-share consensus refreshes are append-only by
  ticker/snapshot date/fiscal year/metric, and the latest snapshot is required
  to retain all six companies before it is used downstream.
- `data/normalized/hk_transport/airline_consensus_freshness.csv` standardizes
  the as-of date, latest forecast date, age, freshness band, observation count
  and prior-comparison count across the A-share, HK broker, public sell-side PDF
  and vendor-revenue layers. It is the timing guard for comparing expectations;
  it does not turn sparse observations into a complete consensus tape.
- `data/normalized/hk_transport/airline_consensus_dispersion.csv` compares the
  FY2026 USD profit/revenue expectations of the three dual-listed mainland
  groups across HK and A shares. It keeps each side's forecast observation date,
  freshness band and source quality, and flags sign disagreements or
  asynchronous vintages. It also records whether each forecast was published
  before or after the issuer's H1 earnings warning, for reconciliation before
  any pair is selected. Available public sell-side EPS/revenue revision counts
  and latest revision dates are included as a revision proxy, while the full
  broker-vintage history remains incomplete.
- `data/raw/airline_pdfs/` provides the existing official monthly operating
  release archive. Preserve it as the evidence layer; normalized values must
  retain source document and publication metadata.

## First financial / consensus coverage probe

On 2026-08-06, a read-only run of the existing free Etnet/AkShare collectors
found the following initial coverage. This is an audit result, not yet a
canonical research dataset.

| HK ticker | Distinct brokers | Forecast rows | FY2026 EPS average / low / high | FY2026 target-price average / median (HKD) | Latest interim period returned |
|---|---:|---:|---:|---:|---|
| `0293.HK` Cathay | 8 | 24 | 1.710 / 1.240 / 2.300 | 15.59 / 16.30 | 2026-06-30 |
| `0753.HK` Air China | 7 | 20 | -0.121 / -0.390 / 0.290 | 5.84 / 5.40 | 2026-03-31 |
| `0670.HK` China Eastern | 7 | 18 | -0.119 / -0.320 / 0.140 | 3.59 / 3.50 | 2026-03-31 |
| `1055.HK` China Southern | 7 | 20 | -0.083 / -0.360 / 0.270 | 4.60 / 4.40 | 2026-03-31 |

The probe confirms that the market is already split on FY2026 mainland-airline
profitability: broker EPS ranges cross zero for all three mainland names. It
does not prove a trade because the estimate dates are asynchronous, target
 prices are in HKD while mainland forecast EPS/profit is in CNY, and the HK
 collector does not provide revenue consensus or a complete revision history.
 The A-share detailed-indicator layer now supplies average revenue forecasts,
 but remains discovery-quality and does not provide a complete vintage tape.
The AkShare financial-indicator values are explicitly `source_reported_unverified`
and lack issuer announcement dates in this run. Official company filings and
results presentations must therefore be the controlling source for actual
revenue, fuel expense, margin and guidance.

### Current coverage gate

| Name | Monthly operating KPIs | Detailed financial drivers | Current guidance / event | Consensus snapshot | Main remaining gap |
|---|---|---|---|---|---|
| Cathay | ready through 2026-06 | 1H2026 primary interim driver + FY2025 annual layer | 1H2026 formal results; 2026 capacity and fuel outlook | price/market cap/target-price bridge ready | complete consensus/revision history |
| Air China | ready through 2026-06 | FY2025/1H2025 primary report layer + A-share discovery history | 1H2026 preliminary loss range; report scheduled 2026-08-31 | HK + A-share + dated EPS revisions + A-share revenue average | HK revenue consensus and formal 1H2026 report |
| China Eastern | ready through 2026-06 | FY2025/1H2025 primary report layer + A-share discovery history | 1H2026 preliminary loss range; report scheduled 2026-08-31 | HK + A-share + dated EPS revisions + A-share revenue average | HK revenue consensus and formal 1H2026 report |
| China Southern | ready through 2026-06 | FY2025/1H2025 primary report layer + A-share discovery history | 1H2026 preliminary loss range; report scheduled 2026-08-29 | HK + A-share + dated EPS revisions + A-share revenue average | HK revenue consensus, formal report, daily utilization disclosure |
| Spring Airlines | ready through 2026-06 | FY2025/1H2025 primary report layer + A-share discovery history | 2026 fleet guidance; report scheduled 2026-08-29 | A-share + dated EPS revisions | 2026 H1 earnings warning and formal report |
| Juneyao Airlines | ready through 2026-06 | FY2025/1H2025 primary report layer + A-share discovery history | 1H2026 preliminary profit decline; report scheduled 2026-08-31 | A-share + dated EPS revisions + revenue average | formal 1H2026 report |
| Hainan Airlines Holdings | ready through 2026-06 | FY2025/1H2025 primary report layer + A-share discovery history | 3–5% annual net fleet-growth guidance; report scheduled 2026-08-25 | A-share + dated EPS revisions + revenue average | 2026 H1 earnings warning and formal report |

This gate is intentionally asymmetric: a company can remain in the monitor
universe with strong operating data while being excluded from pair selection
until the earnings and expectations layers are comparable.

## Evidence chain for each company

The model should be built as:

`market demand → company traffic / capacity → yield and mix → revenue → fuel,
labor, airport, maintenance and ownership costs → EBIT / cash flow → consensus
expectation → valuation → trade expression`.

### Revenue and demand

Priority fields are passengers, RPK, ASK, load factor, domestic/international
and regional mix, passenger yield, RASK, cargo/mail tonnes, RFTK/AFTK, cargo load
factor, cargo yield, ancillary revenue and the revenue split disclosed in
financial statements. Monthly traffic data tests volume and capacity; filings
are needed to map those operating KPIs into revenue and margin.

### Cost and cash flow

Priority fields are fuel volume, fuel expense, fuel expense per ASK, fuel as a
share of operating cost, hedge gains/losses and hedge coverage; then labor,
airport/air-navigation charges, aircraft ownership/lease cost, depreciation,
maintenance, FX and net interest. The EIA benchmark can test direction and
scenario sensitivity, but cannot replace company fuel expense because of
hedging, purchase contracts, route mix, product mix and currency.

### Supply, capacity and structural change

Track fleet size and type, deliveries/retirements, aircraft orders, utilization,
airport slots, route openings/cancellations, international traffic rights,
border/visa rules, airport capacity, ATC constraints, cargo capacity and
geopolitical airspace disruption. A capacity increase with weak load factor is
different from a structural market-share gain; do not collapse both into one
sector conclusion.

### Market expectations and catalysts

For every ticker, capture the price and market capitalization timestamp,
consensus revenue/EBITDA/EBIT/net profit/EPS, target price, recommendation,
estimate revision date, forecast horizon and the assumptions behind the
revision. Record earnings dates, monthly traffic-release dates, fuel-surcharge
changes, fleet/order announcements, policy changes and material news. A
sell-side number without an observation date is not point-in-time consensus.

## Source hierarchy

1. Issuer monthly traffic releases, annual/interim reports, results
   presentations and HKEX/SSE filings.
2. CAAC, airport operators, Hong Kong airport/transport authorities and
   official surcharge/policy notices.
3. EIA for free crude and jet-fuel benchmarks; Cathay's official surcharge
   page for issuer pass-through data.
4. Public consensus aggregators and broker pages for an initial expectation
   map, cross-checked against the original broker or company source whenever
   accessible. Treat target prices and ratings as snapshots, not fundamentals.
5. News and channel checks as event evidence only; retain publication time,
   issuer, claim, source URL and whether the information is confirmed.

## Point-in-time rules

Every observation should distinguish `period_end`, `announced_at`,
`source_release_date`, `effective_from`, `retrieved_at` and, for market data,
`as_of`. Never use a later filing or a revised macro series to explain an
earlier trade date without marking the look-ahead. Keep source vintages when a
provider revises a historical observation. Use blank for unavailable issuer
data; do not silently turn missing disclosure into zero.

## Remaining P0/P1 gaps

- Extend the primary filing layer for the six mainland groups, including
  revenue by passenger/cargo/other where disclosed, leases, depreciation, FX,
  debt, cash and capex. Primary total-liabilities/cash coverage is now strong
  but not complete: Spring FY2025 total liabilities and Cathay cash are still
  explicit gaps, while interest-bearing debt and cash capex have partial
  report-period coverage. Several mainland issuer layouts still require manual
  review for segment revenue and hedge coverage.
- Promote the A-share AkShare discovery rows only after reconciling them to
  issuer annual/interim reports and adding announcement timestamps. Use the
  discovery files now for coverage mapping and hypothesis generation, not as
  final backtest truth.
- Keep filling remaining disclosure gaps from results presentations, especially
  mainland 1H2025 direct fuel-cost/hedging fields and passenger/cargo/other
  revenue splits; reconcile units and HKD/RMB reporting currencies. Keep
  issuer-reported and derived unit economics separate.
- Capture monthly capacity, international recovery, airport/route and fleet
  events from official sources, then connect events to the operating series.
- Create a point-in-time consensus table with estimate revisions, ratings,
  target prices and forecast dates. The dated EPS revision layer is now a
  discovery proxy; HK revenue consensus and a complete institutional consensus
  history remain unavailable. A-share revenue averages are available but still
  require primary-source/vintage reconciliation.
- Add official report PDFs and results presentations behind each mainland event
  row, then reconcile their preliminary H1 ranges to audited interim statements
  and company guidance. The CNINFO official-filing watch now automates the
  discovery gate; after each report is published, the driver parser must be
  refreshed and the preliminary range reconciled. Cathay's 1H2026 preliminary
  range is already reconciled to the formal report; the current event timeline
  remains an evidence bridge, not a substitute for the mainland formal
  financial-statement layer.
- Build the sector dashboard view: demand/capacity trends, fuel and FX,
  earnings revision direction, valuation dispersion and event timeline. Only
  after this layer is stable should we rank possible long/short pairs.

## Pair-selection gate

A candidate pair must have: (1) a measurable variant view, (2) a KPI that can
falsify the view, (3) a valuation/expectation gap, (4) a dated catalyst, (5) a
credible hedge rationale, and (6) explicit factor, liquidity, borrow and
drawdown risks. A pair is not attractive merely because both companies have
similar business descriptions or because one has better recent traffic growth.
