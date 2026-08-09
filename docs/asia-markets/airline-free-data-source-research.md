# Airline v3: Free Online Data-Source Research

Status: research note, 2026-08-09. This note supports the personal airline
long/short project. It is a source map and ingestion roadmap, not a pair
recommendation. The source list is deliberately separate from the model so
that a free source is not promoted to a model input merely because it is easy
to scrape.

## Bottom line

The highest-value free additions are:

1. **CAAC monthly industry statistics and seasonal schedule/licence releases**
   for sector demand, capacity, utilization, route openings and regional mix.
2. **Issuer primary disclosures** from CNINFO, HKEXnews and airline investor
   relations pages for financial statements, monthly traffic, fleet, fuel
   hedging, surcharge policy, guidance and earnings dates.
3. **GACC customs and State Post Bureau data** for air-cargo demand proxies.
4. **MOT / National Railway Administration / China Railway / 12306 data** for
   HSR capacity, passenger substitution and holiday transport regimes.
5. **Airport-operator traffic and weather data** for hub-specific demand and
   disruption risk.

The most important unresolved gap is still realized passenger yield/RASK. The
CAAC statistical system defines and collects average passenger and cargo
prices, but the public monthly releases do not provide a stable, company-level,
route-level realized-yield history. Public OTA prices can be useful as dated
forward fare observations, but they are not the same as realized revenue yield
and should not be silently substituted for it.

The first live P0 addition from this note is now implemented: the MOFCOM Data
Center's public [monthly goods-trade statistics page](https://data.mofcom.gov.cn/hwmy/imexmonth.shtml)
and its JSON query are captured into
`data/normalized/hk_transport/airline_cargo_demand_proxies.csv`, with raw
responses under `data/raw/hk_transport/mofcom_totalmonth_trade_*.json`. The
current response returns 2026-01 to 2026-06 total/export/import values and YoY
rates in USD 100 million. Because the endpoint does not expose its original
release timestamp, the normalized rows are explicitly
`retrieved_vintage_only_latest_snapshot`; they are suitable for a broad cargo
cycle overlay, not a historical PIT release series.

The second P0 addition is the official CAAC monthly sector table. The
normalized layer `airline_caac_sector_monthly.csv` now covers 2020-01 through
2026-06 with 5,928 rows at observation-month × monthly/YTD × scope × metric
grain. It preserves official release dates from 2020-03-20 through
2026-07-21, and covers passenger volume/turnover, cargo/mail volume/turnover,
utilization, load factors and airport throughput. The reports are fast-report
aggregates whose final values are subject to the annual statistical report, so
they are sector context and calibration inputs rather than company-specific
realized yields.

The State Post Bureau addition is now live as
`airline_postal_demand_proxies.csv`. It captures official national postal and
express revenue/parcel-volume observations for 2025 H1, 2026 Jan-Apr and 2026
H1 (cumulative plus latest-month rows where published), preserving article
release dates. The 2026 H1 article reports express revenue growth of 7.3% and
express parcel-volume growth of 5.0%; the layer is deliberately a broad
e-commerce/logistics context signal, not an airline-cargo forecast. v3 applies
release-date filtering: a model dated 2026-06-30 uses the 2026 Jan-Apr article
released 2026-05-20 and excludes the 2026 H1 article released 2026-07-17.
The first cross-vintage read is cautionary rather than bullish: express parcel
volume growth slowed from 19.3% in 2025 H1 to 5.0% in 2026 H1, express revenue
growth from 10.1% to 7.3%, and inter-city volume growth from 20.6% to 6.1%;
international/HK-Macau-Taiwan volume growth slowed from 22.5% to 6.6%, while
intra-city volume moved from +6.2% to -8.4%. This is useful as a demand/mix
warning flag, but not evidence that any particular airline's cargo revenue
will move one-for-one.

The MOT/MCT holiday demand layer is now implemented as
`airline_travel_demand_events.csv`. It contains 13 rows across the 2026
Spring Festival transport window, 2026 Spring Festival/May/Dragon Boat
tourism articles and a 2025 May comparison. It stores event duration and
per-day values, uses official article release dates for PIT filtering, and
does not fill the gaps between holidays. The Spring Festival tourism article
reports 5.96亿 domestic trips over nine days versus a prior eight-day holiday;
the layer derives a duration-adjusted daily growth rate and labels the method
separately from source-reported YoY. This is a sector demand regime control,
not a company-level revenue forecast.

The issuer airport monthly production layer is now implemented as
`airline_airport_traffic.csv` with six months (2026-01 through 2026-06).
Shanghai International Airport, Shenzhen
Airport and Guangzhou Baiyun Airport publish free monthly production
bulletins on CNINFO; the parser handles both the Shanghai dual-airport layout
and the Shenzhen/Guangzhou month-plus-cumulative layout, normalizing 人次/吨
units to 万人次/万吨. Beijing Capital International Airport (00694.HK) is
added through its investor-relations monthly operating-data fast reports
(`BCIA_TRAFFIC_URLS` in `src/hk_transport/config.py`), which carry an
explicit release date on the first line and the same movements/passengers/
cargo scope rows (domestic / HK-Macao-Taiwan / international). Release dates
come from the official announcement date, so model cutoffs exclude later
bulletins. Airport throughput is hub context only and is not converted into
company revenue.

`airline_cargo_airport_bridge.csv` is the cargo validation layer built on top
of the airport series. It compares H1-2026 hub cargo throughput with issuer
cargo tonnage and reported revenue, producing tonnage gap, coverage and
revenue-per-tonne diagnostics. The hub mapping is directional and the layer
is calibration context only.

`airline_cargo_yield_bridge.csv` builds the forward cargo-revenue bridge from
reported yield anchors and issuer tonnage. It exposes implied H1-2026 cargo
revenue growth for all six companies (H1-2025 official anchors for four,
FY2025 annualized anchors for Spring and Juneyao), giving the v3 cargo leg a
dated, tonnage-based alternative to the external trade proxy.

`airline_forward_assumptions.csv` adds the forward tax and FX layer. Effective
tax rates are derived from FY2025 reported anchors (with curated page-level
anchors for Spring, Juneyao and Eastern), extreme reversal cases are flagged
for absolute carry, and the latest ECB USD/CNY reference is carried forward
with an explicit not-a-forecast status.

`airline_h1_2026_validation_playbook.csv` is the H1-2026 report validation
playbook. It consolidates every pre-report model forecast with the official
filing dates and a validation status, so the interim results can be reconciled
against the model claim-by-claim. It also exposes the v3-versus-consensus
profit gap that the residual-bridge methodology must explain.

`airline_cargo_bridge_backtest.csv` backtests the cargo-yield bridge with a
genuine holdout: the FY2025 revenue-per-tonne anchor predicts 1H2025 cargo
revenue within 4-6% for Southern, Air China and Hainan. It also compares the
H1-2026 airport cargo signal with company tonnage on the same calendar basis.

The fuel pass-through layer is now implemented as
`airline_fuel_surcharge_recovery.csv`. It compares each dated surcharge change
with the EIA Gulf Coast kerosene-type jet-fuel benchmark window around the
effective date. The first observations are already informative: the mainland
2026-07-05 change cut surcharges 33-38% while the fuel benchmark rose about
18%, and Cathay's 2026-08-01 change raised surcharges 20-41% on a 2.1% fuel
move. The layer remains context only and is not realized accounting recovery.

The CAAC seasonal route-licence layer is also live as
`airline_caac_route_licence_events.csv`. The 2026 summer/autumn primary PDF
parses to 53 events: 36 new domestic route licences, 13 re-issued domestic
cargo-licence rows and 4 cancellations. For covered names it records 4 Spring
routes / 56 stated initial-frequency units, 2 Juneyao / 28, 2 9 Air / 28, 2
Southern / 28, 1 Eastern / 14 and 4 Air China / 56. These are planned-supply
events as of the 2026-03-23 release, not operated flights or realized ASK; v3
carries the counts as context only.

### Route-fare access audit

The route-fare experiment was deliberately kept separate from the model. The
[CAAC passenger-ticket guidance](https://app.caac.gov.cn/INDEX/HLFW/HKLXCS/)
confirms that domestic fares are market-regulated, are displayed by airlines
and sales channels, and can move with booking time and yield management. That
supports the economic relevance of dated quotes but does not create a public
historical realized-yield feed.

| Candidate | What was observable | Local access result | PIT/model decision |
|---|---|---|---|
| [Ctrip Chinese booking page](https://flights.ctrip.com/booking/SHA-CAN-day-1.html) | Search-indexed page exposed departure date, airline, flight, cabin and `¥...起` quote | Direct requests and Playwright received HTTP 432/`whaleguard block`; Scrapling stealth fetch could not initialize a usable browser header set | Research-only forward quote; not ingested automatically |
| [Trip.com route page](https://www.trip.com/flights/airport-sha-can/) | Search-indexed page exposed current/near-term route prices and airline/date examples | Direct request returned a challenge-validation page; accessible snippets describe rolling search/booking-derived prices rather than a raw inventory feed | Discovery/context only; not a clean PIT quote series |
| [Spring official booking page](https://flights.ch.com/SHA-CAN.html?FDate=2026-08-11&MType=0&SType=0) | Search-indexed result exposed official route fare and published-fare context | Direct request timed out in this environment; no stable response archive was obtained | Official-source candidate, but no automated ingestion until access is reproducible |

Conclusion: a low-frequency manual quote panel may still be useful for a
Spring-vs-mainline pricing check, but the current project will not label these
pages as a historical RASK feed. Any future quote row must retain query time,
departure date, route, airline, flight number, cabin, displayed base/tax/total
price, source URL and access status; comparisons should use the same route and
booking window across airlines.

## Evaluation standard

Every candidate source should be scored on five dimensions before it enters a
model:

| Dimension | Required question |
|---|---|
| Authority | Is it an issuer, regulator, exchange, government statistics agency or a secondary aggregator? |
| Access | Is it genuinely free and programmatically retrievable, or merely visible in a free web page? |
| Timing | Can we retain publication/release/effective time and avoid look-ahead? |
| Granularity | Does it measure the KPI we need, at company, airport, route or sector level? |
| Reproducibility | Can the same request be rerun later, with raw documents or response snapshots retained? |

The model input contract should retain `period_end`, `announced_at`,
`effective_from`, `source_release_date`, `retrieved_at`, `source_url`,
`source_quality`, `currency`, `unit` and `scope`. Missing disclosure remains
blank; an imputed value must be stored in an isolated research layer with an
imputation reason.

## Priority source map

| Priority | Free source | Useful fields | Model use | Main caveat |
|---|---|---|---|---|
| P0 | CAAC monthly KPI releases | passenger volume/turnover, cargo volume/turnover, passenger LF, aircraft utilization, airport throughput, domestic/HK-Macau-Taiwan/international split | Sector demand, market growth, calibration of company traffic and utilization | Industry total, not company yield or company profit; release is revised/verified later |
| P0 | CAAC seasonal schedules and route-licence tables | planned weekly flights, new routes, route start dates, initial frequency, carrier and city pair | Implemented dated forward-capacity event layer and v3 route context | Planned supply is not necessarily operated supply; preserve announcement date and season |
| P0 | CNINFO, HKEXnews and issuer IR | annual/interim reports, results announcements, preliminary earnings warnings, guidance, fuel/hedge notes, fleet and route disclosures | Revenue/cost/net-income bridge, PIT actuals, guidance and earnings catalyst | PDF parsing is issuer-specific; consolidated scope can hide subsidiaries such as 9 Air |
| P0 | Airline monthly operating releases | ASK, RPK, passenger count, LF, ATK/RTK, cargo, fleet additions/retirements and route events | Company-level volume and capacity nowcast | Usually preliminary and often omits realized fare, ancillary revenue, fuel expense and profit |
| P0 | GACC China Customs Statistics | exports/imports by country, customs district, HS code, quantity/value, trade mode and selected commodities | Cargo-demand and belly-cargo regime proxies; regional export intensity | Merchandise trade is not air cargo; release can be revised and should be vintage-stamped |
| P0 | MOFCOM Data Center monthly goods-trade API | monthly total trade, exports, imports, trade balance and YoY rates | Implemented broad cargo/trade-cycle overlay in airline model v3 | Latest snapshot has no original announcement timestamp; historical rows may be revised; not airline cargo revenue |
| P0 | MOT / National Railway Administration / China Railway | rail passenger trips, railway turnover, holiday flows, HSR network and investment | HSR substitution and broad travel-demand controls | National rail trips are not directly comparable with airline RPK; route-level join is required |
| P0 | Official fuel surcharge notices + EIA jet fuel/Brent/WTI | surcharge effective dates, distance bands, benchmark fuel prices | Pass-through timing and fuel shock sensitivity | Surcharge is not realized accounting recovery; EIA is a benchmark, not China purchase cost |
| P1 | Airport operators | monthly/holiday passenger, cargo, movements, international/regional traffic, new runway/terminal capacity | Hub demand, cargo mix, airport capacity and company exposure by base | Coverage is fragmented by airport; airport traffic includes many airlines |
| P1 | State Post Bureau | express parcel volume/revenue, international/HK-Macau-Taiwan parcels and regional mix | Implemented postal/express context layer for cargo triangulation | Parcel growth is not automatically air-freight growth |
| P1 | MCT and NBS | domestic trips/spend, tourism holidays, income, transport/telecom consumption, retail and PMI | Leisure/business demand regime and scenario controls | Aggregated macro data; avoid claiming direct revenue causality |
| P1 | HKO, CMA and Open-Meteo | warnings, rainfall, wind, typhoon, visibility and historical/forecast weather | Airport disruption, cancellation, delay and utilization-risk flags | Weather is a risk/execution variable, not a deterministic earnings forecast |
| P1 | 12306 plus dated train snapshots | rail timetable, train frequency, journey time, fare and seat availability | Route-level HSR overlap and substitution score | 12306 has no general public bulk API; retain dated snapshots and respect access limits |
| P2 | OpenSky / public flight trackers | observed flights, aircraft type, tail and actual movement | Research-only actual-flight/fleet cross-check | Coverage, history and terms are restrictive; not a core production source |
| P2 | OTA fare snapshots and Baidu Index | advertised fare/discount, booking availability, search interest | Forward pricing and attention indicators | Dynamic, itinerary-specific, login/anti-bot/terms risk; not realized yield or clean PIT consensus |
| P2 | Free consensus aggregators and open broker PDFs | EPS/revenue/target-price/rating snapshots | Market-expectations map and dispersion | Sparse coverage, asynchronous dates and no complete historical revision tape |
| P2 | HK SFC / SSE / SZSE short and margin disclosures | reportable short positions, margin balances, eligibility and turnover | Positioning/context and trade feasibility flags | Not locatable borrow, borrow cost or a directional alpha signal |
| P2 | HKEX RSS/News Alert and GDELT | dated announcements, media/event clusters and policy/news mentions | Event calendar and catalyst monitoring | Secondary news is noisy; official announcement must control factual claims |

## Verified free sources and links

### Sector demand and supply

- [CAAC monthly KPI index](https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/TJSJ_1/) and the [June 2026 release page](https://www.caac.gov.cn/PHONE/XXGK_17/XXGK/TJSJ/202607/t20260721_231347.html)
  provide passenger/cargo volume and turnover, load factor, aircraft use and
  domestic/international breakdowns.
- [CAAC 2026 summer-season schedule announcement](https://www.caac.gov.cn/English/News/202603/t20260331_230393.html)
  provides planned weekly flights, new domestic routes and international
  schedule growth.
- [CAAC route-licence table](https://www.caac.gov.cn/XXGK/XXGK/TZTG/202603/P020260323513975216641.pdf)
  gives carrier, city pair, planned start date and initial frequency, making it
  suitable for a dated capacity and route-event queue.
- [CAAC 2025 industry bulletin](https://www.caac.gov.cn/PHONE/XWZX/MHYW/202604/t20260417_230603.html)
  gives the annual fleet, route, airport, passenger and cargo baseline.
- [MOT 2026 Spring Festival transport summary](https://www.mot.gov.cn/zhuanti/2026chunyun/gongzuobushu/202603/t20260316_4201910.html)
  gives a dated holiday-regime control: 94.0bn cross-regional trips, 538m
  railway trips and 94.39m civil-aviation passengers over the 40-day period.
  It is useful for demand and HSR context, but raw year-on-year comparisons
  must normalize for holiday length and should not be treated as airline
  company revenue.
- [Airbus monthly Orders and Deliveries](https://www.airbus.com/en/products-services/commercial-aircraft/orders-and-deliveries)
  provides a free, reproducible aircraft-supply-chain series. The June 2026
  page reports 89 deliveries in the month and 351 year-to-date. It is a
  global OEM proxy rather than a carrier-specific delivery schedule; use it
  as a supply-chain/lead-time control alongside issuer fleet disclosures.
- [Boeing Q2 2026 commercial deliveries](https://investors.boeing.com/investors/news/press-release-details/2026/Boeing-Announces-Second-Quarter-Deliveries/default.aspx)
  reports 171 commercial deliveries in Q2 and 314 year-to-date, while noting
  that delivery information is not final until quarterly results. This is
  useful as a quarterly supply constraint indicator, not as a direct China
  airline ASK forecast.

### Cargo and macro demand

- [GACC monthly bulletin](https://english.customs.gov.cn/statics/report/monthly.html)
  exposes monthly trade tables by country, HS category, customs district and
  selected commodities. GACC explicitly warns that later verification can
  change earlier releases.
- [MOT 2025 transport statistics bulletin](https://xxgk.mot.gov.cn/jigou/zhghs/202606/t20260618_4207752.html)
  contains railway, aviation, port and postal transport baselines.
- [State Post Bureau / government parcel data](https://english.www.gov.cn/archive/statistics/202607/18/content_WS6a5ad899c6d00ca5f9a0c4ae.html)
  provides 2026 H1 parcel volume and revenue, useful as a time-sensitive
  e-commerce/cargo proxy.
- [NBS 2025 national statistical communiqué](https://www.stats.gov.cn/english/PressRelease/202602/t20260228_1962661.html)
  provides domestic tourism, income, transport and macro activity context.
- [MCT 2026 Spring Festival tourism data](https://mct.gov.cn/whzx/whyw/202602/t20260224_964790.htm)
  and [May holiday data](https://www.mct.gov.cn/whzx/whyw/202605/t20260506_965708.htm)
  provide dated holiday travel and spending observations.
- [MCT 2026 Dragon Boat holiday data](https://www.mct.gov.cn/wlbphone/wlbydd/xxfb/jiaodianxinwen/202606/t20260622_966305.html)
  adds a later H1 demand observation: domestic travel was up 4.4% and
  spending up 4.0% year-on-year over the three-day holiday. These low-
  frequency holiday points are best used as a demand-regime/event panel, not
  interpolated into monthly airline RPK.

### Primary company information

- [HKEXnews listed-company search](https://www.hkexnews.hk/homelcicontentsearch.html)
  covers announcements, annual/interim reports and prospectuses since 1999;
  [HKEX's investor FAQ](https://www.hkex.com.hk/Global/Exchange/FAQ/Getting-Started?sc_lang=en)
  confirms that annual and interim reports are publicly posted.
- [CNINFO](https://www.cninfo.com.cn/?lang=zh) is the statutory disclosure
  platform for Shanghai and Shenzhen listed-company announcements, periodic
  reports and prospectuses.
- Issuer IR pages are often better for recurring monthly KPI archives. For
  example, [China Eastern's operating-data page](https://global.ceair.com/global/static/AboutChinaEasternAirlines/intoEasternAirlines/InvestorRelations/operationalSummary/)
  currently exposes monthly operating data through 2026, while [Spring
  Airlines' IR page](https://www.ch.com/invester/) exposes its historical
  operating-data archive.

### Cost and disruption

- [CAAC/NDRC fuel-surcharge mechanism](https://www.caac.gov.cn/XXGK/XXGK/ZFGW/201601/t20160122_27649.html)
  documents the linkage between domestic aviation fuel and passenger
  surcharges. Individual issuer notices should be captured as effective-date
  events.
- [China Weather open service](https://www.weather.com.cn/wzfw/smart/) is a
  free/open weather service for non-commercial use; [HKO Open Data](https://www.weather.gov.hk/en/abouthko/opendata_intro.htm)
  provides documented warnings and weather APIs for Hong Kong and the Greater
  Bay Area context.
- [Open-Meteo](https://open-meteo.com/) provides no-key historical and forecast
  weather data and an archived forecast API. It is useful for a reproducible
  weather-risk control, with attribution and usage limits retained in source
  metadata.
- The CAAC's [2026 public-data catalogue](https://app.caac.gov.cn/XXGK/XXGK/ZCFBJD/202601/t20260116_229769.html)
  confirms that detailed flight plans, actual flights, slots, aircraft and
  pricing data exist. It also makes clear that this free sharing regime is for
  airlines, airports, ATC and regulators for operational or supervisory use;
  it is not an unrestricted public feed for this project.

### HSR and positioning

- [China Railway / government H1 2026 rail statistics](https://english.www.gov.cn/archive/statistics/202607/13/content_WS6a548ddac6d00ca5f9a0c276.html)
  provide current national passenger-trip and cross-border rail context.
- [12306](https://www.12306.cn/en/left-ticket.html) is the official train
  booking/timetable channel. We can use small, dated route snapshots for
  candidate city pairs rather than treating it as a bulk historical database.
- [SFC aggregated reportable short positions](https://hksfc.org/en/Regulatory-functions/Market/Short-position-reporting/Aggregated-reportable-short-positions-of-specified-shares)
  provides free reportable-short-position files. HKEX's daily short-selling
  history is visible as a product but is subscription-based, so it should not
  be labelled a free bulk source.

## What each missing KPI can realistically get

| KPI gap | Best free construction | Confidence |
|---|---|---|
| Sector passenger demand | CAAC passenger volume/turnover + MCT/NBS/MOT holiday controls + airport traffic | High for sector; medium for company read-through |
| Company ASK/RPK/LF | Issuer monthly operating releases, with CAAC as sector cross-check | High, subject to preliminary-release revisions |
| Forward capacity | CAAC seasonal schedule/licences + issuer fleet/order/route events | Medium-high for planned capacity; lower for actual execution |
| Passenger yield/RASK | Issuer disclosed yield/RASK where available + dated OTA fare snapshots as a separate forward-price layer | Low-medium; no clean free realized-yield history found |
| Cargo demand | CAAC cargo/CTK + GACC exports by region/commodity + airport cargo + State Post Bureau | Medium-high as a triangulated proxy; low as direct airline cargo yield |
| Fuel cost/pass-through | EIA benchmark + official surcharge effective dates + issuer fuel-cost/hedge disclosures | Medium-high for scenarios; not exact accounting forecast |
| Fleet/utilization | Issuer monthly fleet events + CAAC utilization + seasonal schedule; OpenSky only as cross-check | Medium-high |
| HSR substitution | CAAC route table + 12306 dated frequency/time/fare snapshots + route ASK weighting | Medium for route diagnostics; not a company revenue observation |
| Net income/EPS | Primary annual/interim reports, preliminary earnings warnings and issuer guidance | High after report publication; low before formal disclosure unless explicitly modelled |
| Consensus/revisions | Dated broker PDFs, A-share/HK public estimate snapshots and rating events | Medium for current map; low for historical revision backtest |
| News/events | HKEX/CNINFO/issuer/CAAC RSS or alerts first, GDELT/Google News only as discovery | High for official events; low-medium for media sentiment |

## Recommended ingestion order

### P0: implement first

1. Normalize CAAC monthly KPI and seasonal schedule/licence releases into
   append-only raw plus normalized tables.
2. Add GACC monthly trade tables, preserving the original release date and a
   later verification flag; use the implemented MOFCOM layer as a practical
   free fallback while the GACC endpoint remains access-blocked in this
   environment.
3. Expand issuer filing/operating-release ingestion to attach exact
   `announced_at` and document URLs to all traffic, fleet, fuel and earnings
   rows.
4. Normalize official fuel-surcharge notices into effective-date intervals and
   join them to company route mix only as pass-through scenarios.

### P1: add to v3 before final pair selection

1. Build airport-hub monthly/holiday traffic for Beijing, Shanghai, Guangzhou,
   Shenzhen, Chengdu and Hong Kong.
2. State Post Bureau parcels are implemented in `airline_postal_demand_proxies.csv`; next add NBS/MCT/MOT demand controls, with explicit holiday-length normalization.
3. Extend the existing HSR query queue with dated 12306 train frequency,
   centre-to-centre time and fare observations for the highest-ASK overlapping
   routes.
4. Add Open-Meteo/HKO weather observations and archived forecast vintages for
   the main bases and route endpoints.
5. Extend primary report extraction into a forward net-income bridge: the
   historical operating-profit/finance/tax/NCI waterfall is now available in
   `airline_official_report_drivers.csv` where disclosed; the remaining work is
   to set defensible forward assumptions for finance cost, FX, associates, NCI,
   recurring profit and diluted EPS.

### P2: use only as supplementary evidence

- OTA fare/availability snapshots, Baidu Index, public flight trackers, OpenSky
  and free consensus aggregators can help identify a lead, but each must remain
  separately labelled as secondary, dynamic or non-PIT.
- Do not use a current consensus page as a historical consensus vintage. Take a
  dated snapshot, retain the raw page/PDF and compare only observations with
  compatible publication dates.

## Proposed v3 source-layer contract

New source-specific data should not be appended directly into the existing
company KPI table. Use source layers first, then a controlled model join:

- `airline_caac_sector_monthly_raw` / `airline_caac_sector_monthly` (implemented)
- `airline_travel_demand_events_raw` / `airline_travel_demand_events` (implemented)
- `airline_caac_schedule_events_raw` / `airline_caac_schedule_events`
- `airline_customs_cargo_proxy_raw` / `airline_customs_cargo_proxy`
- `airline_airport_traffic_raw` / `airline_airport_traffic`
- `airline_weather_risk_raw` / `airline_weather_risk`
- `airline_rail_route_observations` (extend the existing HSR layer)
- `airline_primary_filing_facts` (extend the existing official-report layer)

Each source layer should have a small coverage/audit companion with row count,
date range, latest release, missingness, duplicate check, unit/currency check,
PIT status and source-quality flags. Only after that audit should v3 consume a
field.

## Current v3 model coverage

`data/normalized/hk_transport/airline_earnings_model_v3.csv` extends the
existing company unit-economics bridge with a release-date-safe cargo-demand
triangulation: CAAC cargo/mail growth, MOFCOM trade growth and State Post
Bureau express-volume growth. The
machine-readable contract is
`data/normalized/hk_transport/airline_earnings_model_v3_kpi_coverage.csv`.
At this stage ASK, RPK, load factor, passenger revenue, aggregate non-fuel
CASK and benchmark fuel price are modelled; passenger yield/RASK, fuel hedge
and pass-through, fleet/utilization, cargo revenue and net income are partial
or proxy layers. Cargo tonnage/yield and ancillary/other revenue remain
incomplete; ancillary/other revenue is a labelled residual proxy rather than a
separate attach-rate model. The official-report layer now carries a disclosed
FY2025 waterfall where the PDF can be reconciled, and v3 prefers reported
`营业利润` as the historical operating anchor. Forward finance cost, FX, tax,
associates and NCI are still not separately forecast, so the net-income/EPS
output remains a residual proxy using an implied basic share count. This is
the intended state of the model, not a parser failure.

The output also exposes a parallel `forward_waterfall_proxy` diagnostic. It is
currently available for Air China and China Southern because their FY2025
formal lower waterfall reconciles; finance cost is scaled with forecast
revenue and other disclosed lines are carried at FY2025 absolute values. It
does not replace the primary residual EPS output until debt, FX, recurring
versus non-recurring items, tax and dilution assumptions are independently
supported.

The latest v3 output also carries the individual cargo components and fixed
40% CAAC / 40% MOFCOM / 20% State Post Bureau blend (renormalized when a
component is unavailable), postal/express context, HSR route-coverage context
and fuel hedge/surcharge/pass-through status. The blend is a research
demand-regime input, not an airline cargo-revenue forecast; the HSR layer is
not a company revenue forecast, and the fuel layer does not assume realized
surcharge recovery or zero hedge cost when the issuer discloses no numeric
anchor.
The latest v3 output also carries release-date-safe MOT/MCT holiday context,
including domestic tourism YoY, rail/civil-aviation per-day passenger controls
and total Spring Festival transport growth. These fields remain context-only
and are not mechanically multiplied into company RPK.

The label `modelled` here means that a reproducible bridge exists; it does not
mean that the KPI has been independently validated as a company-specific
forecast. In particular, the current v3 net-income/EPS rows remain proxies and
should not be used as the final earnings leg for a pair. The FY2025
official-report layer still does not expose a uniform, table-level
reconciliation for finance cost, tax, FX, associates and NCI across all six
groups. The current residual bridge deliberately combines those lines; a
The FY2025 waterfall is now an audit context, but a forward granular waterfall
should be added only after each line has a defensible assumption and reconciles
to reported profit and attributable profit.

## Explicit non-findings

The following were not found as a clean, free, public, historical feed in this
research pass:

- company-level realized China airline fare/yield by route and cabin;
- complete historical broker consensus/revision vintages for Juneyao, Spring
  and the mainland airline universe;
- unrestricted flight-by-flight historical schedules with reliable seat
  counts;
- locatable share borrow, borrow fee and utilization for each potential short.

These are research gaps, not permissions to fill values with a current
aggregator snapshot or interpolation. For the thesis, the correct response is
to make the uncertainty explicit and use a range/sensitivity or a route-level
dated proxy.
