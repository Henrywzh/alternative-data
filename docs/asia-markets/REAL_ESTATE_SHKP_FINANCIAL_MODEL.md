# SHKP financial-model input contract

**Status:** first-stage input layer plus a research-only scenario/event-study
baseline; not a validated earnings forecast, investable strategy or investment
advice.

## Objective

The SHKP (`0016.HK`) model should explain three linked engines:

```text
residential / commercial development sales
  + recurring property rental and hotel income
  + other businesses
  -> reported earnings, cash flow and NAV
```

Project activity is a leading indicator. It is not automatically attributable
to SHKP and it is not the same thing as accounting revenue. The existing
phase-specific ownership gate remains the only route from a project phase to
company-attributable sales.

## Current first-stage inputs

`python -m src.hk_real_estate.cli run-shkp-financial-model` reads the sibling
DuckDB at `/Users/henrywzh/Desktop/Quant/financial-data/data/databases/
hk_financials.duckdb` in read-only mode and materializes only ticker-scoped
model inputs under `data/normalized/hk_real_estate/`.

| Input | Current rows | Role |
|---|---:|---|
| `shkp_financial_model_disclosed_facts` | 86 | Official SHKP five-year segment/consolidated summary, contracted-sales backlog and disclosed pipeline capacity |
| `shkp_financial_model_derived_metrics` | 29 | Segment operating margins, rental profit mix and investment-property year-over-year changes derived only from compatible official facts |
| `shkp_financial_model_recurring_portfolio_facts` | 46 | First normalized recurring-income tranche from FY2024/25 annual and FY2025/26 interim reports: rental revenue/profit, HK/Mainland office/retail splits, hotel revenue/EBITDA/profit, occupancy and selected recurring-capacity GFA |
| `shkp_financial_model_asset_pipeline_capacity` | 8 | Named future office/mall gross or retained GFA and stated opening/completion windows from the FY2024/25 annual report; capacity-only, not rent/NOI/valuation |
| `shkp_financial_model_financial_data_actuals` | 952 | Source-selected `0016.HK` income statement, balance sheet, cash-flow and indicator observations |
| `shkp_financial_model_capital_inputs` | 105 | Debt, cash, capex, investment-property, interest and tax rows selected for NAV/free-cash-flow modelling |
| `shkp_financial_model_capital_input_quality` | 105 | Non-destructive unit/quality view; preserves raw HKD values and adds normalized HKD-million values, while retaining the low-quality/no-announcement-date caveat |
| `shkp_financial_model_financial_reconciliation` | 6 | 2022–2024 group-revenue and investment-property checks; all six reconcile after converting sibling absolute HKD to the official HKD-million scale |
| `shkp_financial_model_consensus` | 55 | Dated consensus statistics with fiscal year, snapshot date and contributor count |
| `shkp_financial_model_broker_forecasts` | 33 | Broker-level EPS/net-profit/dividend/target-price rows with forecast dates from 2026-02-13 to 2026-07-21; useful for a current scenario range, not a complete historical revision tape |
| `shkp_financial_model_consensus_revisions` | 7 | Provider revision diagnostics from the single available 2026-07-26 snapshot; not multiple historical consensus vintages |
| `shkp_financial_model_dividends` | 55 | Dividend ex-date/payment-date observations |
| `shkp_financial_model_project_bridge` | 2,643 | SHKP-wide 56-phase project-month activity joined to the ownership gate; latest run is entirely leading-indicator-only because no phase has a reviewed bounded ownership interval |
| `shkp_financial_model_market_snapshot` | 1 | Latest 0016.HK market-cap/price/EV snapshot for valuation context; not a historical price series |
| `shkp_financial_model_price_history` | 4,086 | Yahoo/yfinance daily 0016.HK OHLCV bars from 2010-01-04 to 2026-08-05, with raw close, vendor adjusted close, dividends, split markers and a sample-normalized total-return index |
| `shkp_financial_model_vintage_coverage` | 6 | Layer-by-layer coverage contract for financial facts, consensus statistics, broker forecasts, consensus diagnostics, official disclosures and the SHKP document catalogue |
| `shkp_financial_model_filing_vintages` | 333 | Row-level document availability contract: exact HKEX timestamps, issuer date-only candidates and undated discovery rows; only exact HKEX rows are timestamp-safe PIT anchors |
| `shkp_financial_model_coverage` | 1 | Run-level validation and provenance summary |
| `shkp_forecast_scenarios` | 51 | Current broker min/median/max and consensus low/mean/high scenario rows for FY2026–FY2028; source layers remain separate and research-only |
| `shkp_release_event_study` | 8 | Descriptive release-event price reactions using exact curated HKEX timestamps and +1/+5/+20 trading-day vendor price returns; not causal or investable |
| `shkp_forecast_backtest_coverage` | 1 | Research-run coverage contract linking the baseline to the upstream model-input run and PIT caveats |

The first build is deliberately top-down. It does not copy the financial-data
database or infer SHKP segment numbers from generic yfinance total revenue. The
price history is a separate Yahoo/yfinance contract because the sibling
financial-data database does not own daily prices; use `run-shkp-price-history`
to refresh it, or `--include-price-history` to attach a fresh fetch to a model
run.

The price contract preserves raw OHLCV and Yahoo's adjusted close rather than
overwriting one with the other. `total_return_index` is normalized to 100 at
the first row of the requested sample, so it is a relative performance series,
not a permanent index level. A fetch-date row with no completed close is
excluded, while older missing closes fail validation. Yahoo bars can be
revised after the trading date, so `fetched_at` is audit metadata and not a
claim of full point-in-time price-vintage history.

`build_shkp_project_model_bridge()` is the bottom-up handoff. It joins SRPE
project-month activity to the SHKP registry, but ignores any legacy
`sales_value_attributable_hkd` field unless the registry has an approved
phase-specific interval. Blocked rows are retained as
`leading_indicator_only` with a null attributable amount.

The recurring portfolio layer is intentionally period-level rather than an
asset master. It includes six-month FY2025/26 rental and hotel facts plus
portfolio/named-asset occupancy observations, but it does not annualize the
interim values. It preserves HKD and RMB observations separately, and keeps
occupancy scope (portfolio, IFC, ICC or hotels) in `asset_class`/`caveat`.
Hotel rows include revenue, EBITDA and operating profit where disclosed; ADR,
RevPAR, room count and hotel-by-hotel occupancy remain missing.

## Accounting semantics

Keep these measures separate:

| Measure | Meaning | Safe use |
|---|---|---|
| `contracted_sales` | Customer contracts signed / attributable sales disclosed by SHKP | Forward sales and cash-collection proxy |
| `sales_backlog_yet_to_be_recognized` | Contracted sales not yet recognized in revenue | Recognition bridge by expected handover/period |
| `property_sales_revenue` | Accounting revenue recognized in the period | Historical P&L actual |
| `segment_revenue_including_jv_associates` | Segment view including the Group's share of JVs/associates | Segment trend and margin analysis; do not add to consolidated revenue |
| `property_rental_revenue` | Recurring property-rental segment revenue | Recurring-income model |
| `investment_properties` | Balance-sheet/NAV asset value | NAV and fair-value sensitivity |

The core bridge is:

```text
reported property-sales revenue
  <- contracted-sales backlog
  <- handover / completion curve
  <- project economics and attributable share
```

The arrows are model relationships, not automatic transformations. Any
assumption about recognition lag, gross margin or phase ownership must remain
an explicit model input with source and confidence.

## Research-only forecast/backtest baseline

`python -m src.hk_real_estate.cli run-shkp-forecast-backtest` creates a current
scenario layer and a release-event study. The scenario layer is a transparent
range from the current broker/consensus snapshot; it is not a historical
forecast vintage. The event study uses eight exact HKEX release timestamps and
the next trading session after an after-close release, so it is safe from
same-day post-release leakage. It is a descriptive event study rather than a
causal estimate or an investable strategy.

The full methodology and latest observed values are documented in
`docs/asia-markets/REAL_ESTATE_SHKP_FORECAST_BACKTEST.md`.

## Next model tranches

0. **Completed-property asset table (implemented):** the FY2024/25 annual-
   report `Major Completed Properties in Hong Kong` table (printed pp. 52–53)
   now produces 39 aligned property-group rows in
   `shkp_completed_properties` and is carried into the financial-model input
   snapshot. The parser retains raw labels, lease expiry, Group's Interest and
   attributable GFA by residential/retail/office/hotel/industrial use. This is
   an exposure bridge from the SHKP commercial/hospitality identity catalogue,
   not rent/NOI or a legal ownership interval; it remains separate from the
   under-development completion schedule.
1. **Historical actuals:** reconcile official SHKP annual/interim segment
   tables to the sibling financial-data observations; retain both segment
   (including JVs/associates) and consolidated views.
2. **Backlog bridge:** structure every company-disclosed Hong Kong/Mainland
   contracted-sales and expected-recognition statement with observation date,
   target recognition period and attributable scope.
3. **Project economics:** add units, GFA, ASP, cost, launch, handover and
   project-month activity for priority SHKP phases. Keep unresolved ownership
   as `non_attributable_activity`.
4. **Recurring portfolio:** add asset-level office/mall/hotel GFA, occupancy,
   passing rent, rent reversion, tenant sales/footfall, hotel ADR/RevPAR and
   investment-property fair values.
5. **Capital and NAV:** add debt maturities, fixed/floating mix, interest
   expense, hedging, land payments, capex, dividends, cash and JV/associate
   balances.
6. **Valuation/consensus:** add point-in-time broker EPS/revenue/NAV forecasts,
   revisions, target prices and a sum-of-the-parts sensitivity layer.

The first PIT tranche is now implemented at the document level. It does not
pretend to reconstruct the missing historical consensus tape or sibling
financial-fact announcement dates; it makes those gaps explicit for every
document and prevents an undated catalogue row from silently entering a
backtest.

## Current known gaps

- The sibling financial-data database has no daily price history and its HKEX
  metadata run has no `0016.HK` rows in the current snapshot; company filings
  therefore remain sourced from SHKP's official investor-relations catalogue.
- The current sibling `0016.HK` financial-fact extract has 952 rows with
  fiscal-period labels but zero populated original announcement dates; its
  `available_at` values are fetch timestamps in July 2026 and the rows are
  therefore historical context, not point-in-time backtest facts.
- Consensus statistics contain 55 non-null rows but only one snapshot date
  (2026-07-26) and no `estimate_period_end`; the 33 broker rows have dated
  forecast dates but were fetched in one batch. The seven consensus-revision
  rows are diagnostics inside that same snapshot. These layers can anchor
  current scenarios, but not a historical consensus-revision backtest.
- The SHKP official document catalogue contains 333 report/announcement links.
  A curated HKEX release contract now dates the four long-form FY22/23–FY24/25
  annual reports and FY25/26 interim report, plus their four results releases,
  with exact Hong Kong release timestamps. Those matched rows expose
  `reporting_period_end`, `hkex_release_at`, `release_source_url` and explicit
  `release_evidence_type`; the remaining rows still have no release date and
  remain discovery-only. PDF created/modified times are not used as PIT dates.
- The current 86 disclosed facts do not yet include asset-level rent, hotel
  KPIs, construction cost, land-premium or project gross-margin assumptions.
- The completed-property table is now normalized for FY2024/25 (39 aligned
  rows), but earlier annual-report vintages still need a separate layout audit
  before they can be promoted into a historical asset panel. The current
  commercial/hospitality catalogue remains broader than this one report table,
  and rows without a completed-property match stay identity-only.
- The recurring portfolio tranche now covers 46 exact/approximate period facts,
  but it is not a lease-level model: passing rent, rent reversion by asset,
  tenant sales/footfall history, WALE, ADR, RevPAR, room counts and asset-level
  fair values remain open inputs.
- Sibling capital inputs are absolute HKD values (`unit=currency`) whereas the
  curated official summary uses HKD millions. The model now retains both raw
  and normalized views and records six exact overlap checks; this is a unit
  reconciliation, not a substitute for official announcement-date evidence.
- The 13-phase ownership audit has zero approved bounded intervals. Project
  transaction activity must remain separate from company-attributable sales.
- Consensus is a current snapshot/revision surface, not a complete historical
  sell-side-vintage database.
- `shkp_financial_model_filing_vintages` contains 333 rows from the official
  SHKP catalogue. Eight curated report/results rows have exact HKEX release
  timestamps; issuer-date-only rows are date-level candidates only, and the
  remaining rows are discovery-only. This is an availability contract, not a
  substitute for extracting each document's financial facts at its release
  vintage.

The named commercial-asset capacity tranche is also intentionally separate
from recurring income. It gives the forecast a transparent completion runway
for IGC, Scramble Hill, Cullinan Sky Mall, Artist Square and the Mong Kok
commercial complex, but it does not annualize area into rent or infer a legal
ownership interval from the one disclosed 72.4% project stake.
- The price history now supports return calculations, but it is a vendor
  historical replay rather than an exchange-native, point-in-time database.
  A serious backtest still needs a frozen-as-of policy, delisting/corporate-
  action review and a dated consensus/filing vintage layer.

## Filing-time semantics

Results announcements and long-form reports are separate public vintages. For
example, FY2024/25 results were released on 4 September 2025 while the annual
report was released on 8 October 2025. Facts that only appear in the long-form
report must not be backdated to the earlier results announcement. The document
catalogue keeps both the issuer-page `published_date` (when available) and the
curated HKEX `hkex_release_at`; only the latter is used as a point-in-time
availability anchor for matched report rows.
