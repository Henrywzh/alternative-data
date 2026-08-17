# Hong Kong / China Airlines Sector Map

Status: P0 personal long/short research layer, point-in-time snapshot
2026-08-07. This note fills the sector and business-model layer around the
existing airline financial, operating, consensus and risk artifacts. It does
not select a pair or assign a long/short direction.

## What was missing

The existing pack was already strong on company KPIs, filings, estimates,
fuel, FX and pair diagnostics. The missing bridge was:

```text
macro travel demand
    -> route-level demand and competition
    -> ASK / RPK / load factor / yield
    -> passenger and cargo revenue
    -> fuel + non-fuel cost
    -> earnings and consensus revision
    -> event risk and pair construction
```

This is why a company can report positive traffic growth while earnings still
miss: capacity may grow faster than demand, fares may be discounted, fuel may
rise, or the company may have a different hub, international or aircraft mix.

## Sector dashboard: the five layers

| Layer | Core question | Current local data | Next data to add |
|---|---|---|---|
| Demand | Is travel demand accelerating, broadening or weakening? | Monthly passengers/RPK, CAAC traffic, holiday and summer-rush statistics, IATA outlook | Tourism receipts, hotel/OTA bookings, airport throughput and route-level booking proxies |
| Supply | Is capacity disciplined or being pushed into the market? | ASK, fleet/route events, CAAC seasonal schedule, aircraft and new-route disclosures | Fleet deliveries/groundings, airport slots, route-level frequency and seat capacity |
| Pricing | Does demand convert into yield and revenue? | Passenger yield/RASK where disclosed, load factor, fuel surcharge schedules, consensus revenue | Ticket-fare/discount time series, route-level fare and advance-booking data |
| Cost | Which input drives the next estimate revision? | EIA jet fuel/Brent/WTI, FX, fuel sensitivity, reported cost lines and hedging | Labor, lease/maintenance, airport charges, aircraft delivery delays and utilization |
| Events/risk | What can move the stock inside the investment horizon? | Results calendar, warnings, monthly operating releases, holiday calendar, news and rating events | Formal seasonal schedule changes, aircraft orders/deliveries, policy and disruption calendar |

## Earnings driver tree

At the company level the first-order bridge is:

```text
Revenue = capacity (ASK) x load factor x yield
         + cargo volume x cargo yield

Operating cost = fuel cost + labor + aircraft ownership/lease
                + maintenance + airport/handling + distribution/other

Earnings = revenue - operating cost - finance/tax/other items
```

Fuel should not be treated as a one-way oil beta. The useful test is:

```text
net fuel exposure = fuel cost shock - surcharge recovery
                    - demand elasticity from higher ticket prices
                    + hedge effect + mix/utilization effect
```

That is the mechanism to compare Spring and Juneyao rather than simply asking
whether oil is bullish or bearish for airlines.

## Current sector read-through

The industry backdrop is not simply “travel demand is good.” IATA's dated
2026 Asia-Pacific outlook had passenger RPK growth of 7.3% versus ASK growth of
7.1%, but the CAAC summer schedule planned total passenger/cargo flights roughly
flat year on year while adding 434 domestic routes and increasing planned
international passenger flights. The investment question is therefore whether
each company converts demand into yield and margin, not whether passengers rise
in absolute terms.

The early-2026 demand evidence is constructive but mixed. CAAC reported 94.39m
civil-aviation passengers during the Spring Festival travel rush, up 4.6% year
on year, with an 87.8% average load factor. China Railway reported more than
2.3bn rail passenger trips in H1 2026, up 5%, with daily passenger trains up
5.8%. Air and rail can therefore grow at the same time; HSR should be treated
as a route-level fare and share constraint, not as an automatic negative for
the whole airline sector.

The attached research notes also flag a useful distinction to verify in the
primary reports: Spring's 2025 report appears to frame its 2026 fleet plan as
net additions of 12 A320-family aircraft, while Juneyao Group guidance is much
slower at group level. This could create a real question—growth versus
overcapacity—but it must be reconciled to actual deliveries, retirements,
wet-leases and the exact reporting scope before entering the earnings model.

## High-speed rail framework

Do not reduce HSR to a generic “competitor” label. For every meaningful airline
route, add:

1. city-pair and airport-pair;
2. rail alternative and centre-to-centre travel time;
3. airline frequency and seat capacity;
4. rail frequency and capacity;
5. relative fare and booking lead time;
6. whether the route is trunk business travel, leisure travel or a connecting
   leg.

The first risk flag should be `high_hsr_overlap`, not “HSR is a substitute” in
the abstract. A roughly four-hour centre-to-centre rail route is the first
screen for meaningful substitution; exposure can persist beyond that for some
city pairs, but the threshold is not universal. A long-haul international or
connecting route is much less exposed. The next useful join is a route-level
HSR overlap table, not more top-down passenger forecasts.

Suggested metric:

```text
HSR exposure_i = sum(route ASK_i,r x substitution score_r)
%ASK exposed_i = HSR exposure_i / total ASK_i
```

Keep the score transparent and route-level. A route with high rail frequency,
short centre-to-centre travel time and overlapping origin/destination airports
should score higher than a nominally similar route with poor station access.

## Spring versus Juneyao

These two names are informative precisely because they are not the same model.

| Dimension | Spring Airlines | Juneyao Airlines |
|---|---|---|
| Positioning | Structural low-cost carrier | Mid-to-high-end high-value-service carrier |
| Network | Shanghai-based domestic, Greater China and international short-haul network | Shanghai/Nanjing hubs, domestic plus Asia/Europe/Oceania and long-haul exposure |
| Fleet/model | Standardized A320-family, high utilization/load-factor model | A320 plus B787-9 dual-fleet model; more network and long-haul complexity |
| Demand | Price-sensitive leisure and stimulated demand | Premium leisure/business, hub connectivity and international recovery |
| Cost sensitivity | Fuel, utilization, airport/handling and ancillary economics | Fuel, FX, widebody utilization, long-haul cost and airport/maintenance complexity |
| HSR | High overlap on short-haul routes, but low fares can stimulate demand | Also exposed on short-haul routes; international and long-haul mix lowers group-wide overlap |
| Scope | FY2025 report is the listed company operating scope | FY2025 report explicitly includes 9 Air in operating data and consolidates the group financials; Juneyao Air and 9 Air fleet split is disclosed |
| Pair implication | Lower-cost structural model | More premium/network and long-haul mix; do not mix Juneyao Air with 9 Air, the group's separate LCC |

The clean thesis comparison is therefore not “two Chinese private airlines.” It
is “Spring's structural LCC economics versus Juneyao Group's mixed higher-value
network carrier plus separate LCC subsidiary.” The FY2025 scope question is now
resolved at group level; the model must still control for route mix,
international share, fleet type, hub and HSR overlap before interpreting margin
differences as management skill or mispricing.

## Company fundamental profiles: the business behind the KPI

The operating data answers **what moved**. This section answers **why the same
sector shock can affect each company differently**. The descriptions below are
anchored to the normalized company-fundamentals and FY2025 driver tables; the
thesis implications are analytical hypotheses that still need to be tested
against yield, cost, route and consensus revisions.

| Company | What the business actually is | Demand engine | Supply / cost character | Structural edge | Main earnings vulnerability | H1 2026 read-through |
|---|---|---|---|---|---|---|
| Air China | State-linked flag/network carrier centred on Beijing and Chengdu, with domestic trunk routes, international connectivity and belly cargo | Domestic business and hub traffic, international restoration, transfer flows and premium/long-haul mix | Large mixed narrowbody/widebody fleet; fuel, FX, labour, aircraft ownership/lease and maintenance are material | Flag-carrier network, slots/hubs and international connectivity | Widebody and international recovery can be sensitive to fuel, FX, geopolitics and weak business travel; network capacity can dilute yield | ASK was broadly controlled while RPK grew faster, producing a strong LF improvement; this is a positive utilization signal, but it is not yet proof of yield or profit conversion |
| China Southern | Largest-scale mainland network carrier in this set, anchored by Guangzhou and Beijing Daxing, with domestic, regional and international passenger/cargo operations | South China economic activity, domestic trunk/regional travel, international restoration and hub connectivity | 972-aircraft group scale, multiple branches/subsidiaries and a broad aircraft mix; absolute fuel and fixed operating cost are large | Scale, dense domestic network, hub breadth and operating infrastructure | Scale can become overcapacity if ASK is pushed ahead of RPK; fuel and fleet-renewal costs matter, and broad network exposure makes route-level weakness harder to hide | H1 ASK grew faster than RPK and passenger LF fell; June/Q2 deterioration makes the key question whether this is temporary timing or early capacity/yield pressure |
| China Eastern | Shanghai-centred network carrier using Hongqiao/Pudong hubs, with East China domestic routes and regional/international connectivity | Shanghai/East China business and leisure, international recovery, hub transfers and cargo/belly capacity | Large narrowbody/widebody network; Shanghai airport/hub costs, fuel, FX, labour and fleet utilization are important | Valuable Shanghai hub and international/regional connectivity | High HSR overlap on selected short-haul city pairs; hub congestion/cost, fare pressure and weak cargo monetization can offset traffic growth | Passenger demand outpaced capacity on H1 totals and LF improved, while cargo capacity expanded sharply; verify whether cargo growth is monetized before treating it as an earnings positive |
| Spring Airlines | Pure LCC, Shanghai-based, standardized A320-family operation focused on low fares and high utilization | Price-sensitive leisure, stimulated demand, short-haul international/Greater China and tourism | Homogeneous fleet, high utilization and high LF; fuel, airport/handling, distribution and ancillary revenue are the key operating levers | Lower structural cost and the ability to create incremental demand through price; simple fleet lowers complexity | Short-haul HSR substitution and fare competition; fast fleet/ASK growth can turn the cost advantage into yield dilution | H1 RPK grew faster than ASK and LF stayed very high, supporting the LCC demand thesis; June LF softened slightly, so the next test is yield and ancillary revenue rather than passenger growth alone |
| Juneyao Air + 9 Air | Listed group combines a higher-value network airline with a separately operated LCC subsidiary; Juneyao Air uses A320 plus B787-9, while 9 Air uses B737 | Juneyao Air: premium leisure/business, Shanghai/Nanjing hubs and international/long-haul recovery; 9 Air: price-sensitive domestic and short-haul demand | Two different fleets and cost structures; fuel, FX, widebody utilization, long-haul complexity and subsidiary scope are material | Mainline service/network positioning plus an LCC option inside the group | Consolidated results can hide opposite trends between Juneyao Air and 9 Air; widebody and international volatility, and any 9 Air capacity/yield weakness, can contaminate the group read-through | H1 group demand grew faster than capacity and LF improved, but this is a mixed-scope result; do not infer Juneyao Air premium pricing from group totals without separating 9 Air |
| Hainan Airlines | Consolidated multi-carrier group with Hainan/Beijing roots and a mixed domestic/international network; reported scope is less homogeneous than a single airline | Tourism, domestic connectivity, international routes and group-network restructuring | Multi-carrier fleet/network and consolidated costs; fuel, FX, labour, lease/maintenance and subsidiary scope all matter | Network breadth and potentially useful international/regional connectivity | Group consolidation, restructuring and heterogeneous fleet make unit economics less transparent; route/fleet changes can overwhelm a top-down demand read | H1 capacity contracted while RPK was roughly flat and LF improved, but June demand and LF weakened; this points to discipline or supply removal, not automatically stronger underlying demand |
| Cathay Pacific | Hong Kong hub group with premium international passenger, cargo, HK Express and associate exposure; not a like-for-like mainland domestic carrier | Hong Kong transfer traffic, premium long-haul and regional travel, China international connectivity and cargo cycle | Widebody-heavy international network plus low-cost subsidiary and associates; fuel, FX, labour, airport/route charges and aircraft utilization matter | Hong Kong hub, premium brand, long-haul network and cargo capability | International demand, Middle East/airspace/geopolitical disruption, fuel/FX and cargo-cycle swings; one-off associate gains can obscure recurring profit | H1 traffic and LF were strong, but the reported profit included an Air China dilution gain; recurring profit is the cleaner control for testing whether volume converts into earnings |

### How to use the profiles in the thesis

The profiles imply that the main cross-sectional questions are not simply
“which company has the highest passenger growth?” They are:

1. **Network carriers:** can Air China, Southern and Eastern convert hub and
   international recovery into yield, or are they adding seats faster than
   monetizable demand?
2. **LCC:** is Spring's high LF and standardized fleet a structural cost/moat,
   or is the market capitalizing a temporary low-fare demand window while yield
   compresses?
3. **Mixed-scope group:** is Juneyao's apparent resilience coming from
   Juneyao Air, 9 Air, or simply the consolidation boundary?
4. **Group restructuring:** is Hainan's lower capacity a deliberate supply
   discipline signal, or a symptom of weaker network/fleet availability?
5. **Control case:** does Cathay show that strong ASK/RPK/LF can coexist with
   weak yield or a profit result dominated by a non-recurring item?

For each company explorer page, expose these fields next to the time series:
`business_model`, `hub_region`, `international_share`, `fleet_mix`,
`scope_boundary`, `hsr_overlap`, `fuel_cost_share`, `yield`, `ASK`, `RPK`,
`LF`, and the latest **consensus revision / company guidance / invalidation
event**. This is the minimum context required to turn the dashboard from a
data catalogue into a thesis-testing tool.

## Exposure questions to test, not assumptions to hard-code

| Driver | Working question for Spring | Working question for Juneyao | Evidence needed |
|---|---|---|---|
| Domestic leisure | Does low fare stimulate enough demand to offset fare pressure? | How much premium demand survives a weak consumer cycle? | fare, booking, load factor and yield by route/market |
| International | Is Northeast/Southeast Asia the main incremental growth pocket? | Does Europe/Australia and long-haul recovery add more yield than risk? | international ASK/RPK, route profitability and visa/route policy |
| HSR | What percentage of ASK overlaps vulnerable city pairs? | Does long-haul mix materially lower HSR sensitivity? | route-level HSR score and ASK weighting |
| Fuel | Does the LCC cost base and utilization absorb fuel better? | Does widebody and long-haul mix magnify fuel shock? | fuel per ASK, aircraft mix, hedging and surcharge recovery |
| Fleet growth | Is faster fleet growth productive or overcapacity? | Is slower group growth a discipline signal or a constraint? | deliveries, retirements, utilization, ASK versus RPK and yield |
| FX | What is the real USD cost and lease exposure? | Does widebody, international revenue or foreign-currency debt change beta? | filing currency notes, debt/lease, international revenue and FX sensitivity |

The question marks are deliberate. They are research questions, not missing
columns to fill with unsupported guesses.

## Event calendar for the current horizon

The structured calendar is in
`data/normalized/hk_transport/airline_sector_event_calendar.csv`. The most
important near-term events as of 2026-08-07 are:

- July mainland operating bulletins are still a data-release watch item; no
  July bulletin was found in the scoped CNINFO window for the six names.
- 1H2026 results are scheduled for Hainan on 25 August, Spring and Southern on
  29 August, and Air China, Eastern and Juneyao on 31 August. These are
  scheduled dates, not actual disclosures until confirmed.
- The 25-27 September Mid-Autumn holiday and 1-7 October National Day holiday
  are demand and pricing tests. Track bookings, capacity, load factor, fare and
  rail traffic together.
- Fuel, FX and surcharge schedules are continuous events. A healthy traffic
  print does not remove fuel or translation risk.

Conditional events should also be monitored even without a fixed calendar date:

- jet fuel above a defined level for a defined number of weeks;
- USD/CNY moving through a defined threshold;
- rolling three-month industry passenger growth turning negative;
- Spring ASK growth exceeding RPK growth by a predefined gap;
- load factor holding while passenger yield declines materially;
- a new HSR route or speed upgrade overlapping a major airline city pair;
- visa, geopolitical or route-restriction changes affecting Northeast Asia,
  Southeast Asia, Europe or Australia.

## What to add next

Priority order for the dashboard/company explorer:

1. Add a company profile tab from
   `airline_company_fundamentals.csv`.
2. Add a sector overview tab with demand, capacity, yield, fuel, FX and HSR
   overlap indicators; show actual, forecast and planned values separately.
3. Add an event calendar with `days_to_event`, affected companies, earnings
   channel and invalidation risk.
4. Use `airline_scope_reconciliation.csv` to separate Juneyao Air from 9 Air
   wherever possible before using the Spring–Juneyao CASK comparison.
5. Enrich `airline_hsr_route_candidates.csv` with dated 12306 rail time,
   frequency, fare and station-access fields through leg-level `airline_hsr_route_query_queue.csv`
   and station-scoped `airline_hsr_route_observations.csv`. Station telecodes are verified,
   Ctrip SSR provides verified train observations, OSRM driving access latency is response-derived
   or marked pending without hardcoding benchmarks, and missing direct train search results return NaN
   (`pending_no_direct_rail_observation`) to preserve potential connecting rail capacity. Diagnostic HSR scores
   are explicitly flagged as modelled diagnostics. External aviation data sources are systematically classified
   in `airline_aviation_source_registry.csv`. Route capacity proxies are built in `airline_route_capacity_weights.csv`
   with explicit operator scope (`operating_entity`, `parent_group`), attributing 9 Air (九元航空) subsidiary routes to 9 Air
   using 9 Air's 188.0 operational seat proxy (live official [9air.com Fleet Page](https://www.9air.com/cmsProvider/info/1011/1431.htm), dated 2026-05-26) alongside the 189.0 seat upper-bound scenario (Juneyao FY2025 Annual Report [1225151299.PDF Page 15](https://static.cninfo.com.cn/finalpage/2026-04-23/1225151299.PDF), dated 2026-04-23) under status `frequency_disclosed_proxy_conflicted_seats`.
6. Non-directional pair thesis readiness is established in `airline_pair_thesis_readiness.csv`, joining financial actuals, consensus, fuel/FX, HSR capacity, and risk diagnostics while explicitly separating Juneyao Mainline from 9 Air.
6. Add booking/fare/OTA or airport throughput data only if the source is dated,
   repeatable and sufficiently granular; do not fill gaps with generic tourism
   headlines.
