# HK Data Source Expansion — Vehicle Market, Real Estate Supply, Macro/Price

> For agentic workers: use the executing-plans skill to implement this plan task-by-task.

**Goal:** Turn today's verified-but-unbuilt HK data sources (CSDI/data.gov.hk + C&SD deep dives, `.claude/skills/data-source-deep-dive/references/verified-hk-sources.md`) into real pipeline additions, grouped by target sector so each group can be picked up and shipped independently.

**Context:** Every source below was independently fetched and verified this session (real endpoint, real schema, real freshness) — not assumed from a third-party summary. See the ledger file above for full endpoint/schema/freshness detail per source; this plan focuses on *what to build*, not re-verification.

**Tech Stack:** Python (`src/hk_*` packages, `requests`/`pandas`), existing artifact-builder pattern (`apps/asia-markets-dashboard/scripts/build_hk_*_artifact.py`), existing wiring test (`tests/test_asia_markets_wiring.py`).

## Global constraints

- Follow the existing per-sector pattern exactly: new fetcher lives in `src/hk_<package>/sources/<name>.py`, config constants (URLs) in `src/hk_<package>/config.py`, wired into that sector's `build_hk_<sector>_artifact.py` (new dataset + card/chart + `manifest.sources[]` entry with a `query.sql`-shaped pseudo-SQL string, per `mcp/server.cjs`'s `validateActualSqlSource` requirement).
- Do not touch `sectors.json`, `package-dashboard.mjs`'s `ZH_DICTIONARIES`, or the wiring-test allowlists for Groups 1–2 — both target sectors (`hk_transport`, `hk_real_estate`) already exist and are already rostered; this is additive dataset/chart work inside an existing sector, not a new sector.
- Cap any new chart at ≤3 series (the recurring mobile-viewport `horizontal_overflow` bug this session, root-caused earlier in `build_hk_real_estate_artifact.py`).
- Regenerate the affected sector's `.generated/*-artifact.json` and re-run `tests/test_asia_markets_wiring.py` after each group.

---

## Group 1 — Vehicle Market & Mobility Signals (extends `hk_transport`) — DONE 2026-07-31

The richest, most novel cluster — mostly monthly-or-better, one genuinely real-time. Natural home is `hk_transport` (currently only `mtr_patronage.py`, `cathay_traffic.py`), repositioned to also cover the private-vehicle/EV market and real-time mobility proxies.

### Task 1.1: TD real-time car park vacancy (flagship "signal" candidate)
- **Create:** `src/hk_transport/sources/td_carpark_vacancy.py`
- **Endpoints:** `https://resource.data.one.gov.hk/td/carpark/basic_info_all.json` (park metadata: name, district, type) + `.../vacancy_all.json` (live vacancy by vehicle type: `P`/`M`/`P_D`/`L`/`H`/`B`/`C`/`T`/`O`). 548 car parks, ~4–5 min update interval (empirically confirmed).
- **Transform:** aggregate to a district-level (or all-HK) **occupancy rate** time series (`1 - vacancy/capacity`, private-car type only for the headline metric) — this is the actual "signal," not the raw per-park snapshot. Store per-poll snapshots to build history; a single live pull has no time series of its own.
- **Output dataset:** `td_carpark_occupancy` (district, timestamp, occupancy_rate, sample_size).

### Task 1.2: TD First Registered Vehicles — brand/model EV tracker
- **Create:** `src/hk_transport/sources/td_first_registered_vehicles.py`
- **Endpoint:** `https://www.td.gov.hk/datagovhk_td/first-reg-vehicle/resources/en/particulars_of_first_registered_vehicle_<mon>_<yyyy>_eng.csv` (monthly, ~1-month lag, row-level with `Fuel Type`, `Vehicle Make`, `Vehicle Model`).
- **Transform:** monthly private-car first-registration counts grouped by `Fuel Type` and, for Electric, by `Vehicle Make` (BYD/Tesla/etc.).
- **Output dataset:** `td_ev_registrations_monthly` (month, fuel_type, make, count).

### Task 1.3: TD fleet stock by fuel type
- **Create:** `src/hk_transport/sources/td_vehicle_fleet_stock.py`
- **Endpoint:** `https://www.td.gov.hk/filemanager/en/content_4883/table41a.xls` (Table 4.1(a), monthly, `Total Registration`/`Total Licensed` by vehicle class and, for private cars, fuel type).
- **Output dataset:** `td_fleet_stock_monthly` (month, vehicle_class, fuel_type, total_registered, total_licensed) — enables "EV share of the whole road fleet," distinct from Task 1.2's new-registration flow.

### Task 1.4: TD net first registration of private cars
- **Create:** `src/hk_transport/sources/td_net_registration.py`
- **Endpoint:** `https://www.td.gov.hk/filemanager/en/content_4884/table41c.xls` (Table 4.1(c), monthly, gross first registration minus cumulative deregistration).
- **Output dataset:** `td_net_car_registration_monthly` (month, gross, deregistered, net).

### Task 1.5: C&SD Table E705 — cross-boundary vehicle/vessel/aircraft/train movements
- **Create:** `src/hk_transport/sources/censtatd_boundary_movements.py`
- **Endpoint:** product `D7000005` ("Table E705"), via the `report_index.json`/product-file mechanism documented in the ledger's subject-crawl section.
- **Output dataset:** `censtatd_boundary_movements_monthly`.

### Task 1.6: MTTD Table 2.3 passenger journeys (previously verified, never built)
- **Create:** `src/hk_transport/sources/mttd_passenger_journeys.py`
- **Endpoint:** `https://www.td.gov.hk/datagovhk_tis/mttd-csv/en/table23_eng.csv` (monthly, MTRC + franchised buses).

### Task 1.7: Wire into `build_hk_transport_artifact.py`
- Add up to 3 new charts (car park occupancy trend, EV registration share, fleet EV-share) and cards (latest occupancy rate, latest EV registration share, latest net registration).
- Add `manifest.sources[]` entries (5 new sources) with pseudo-SQL `query.sql` strings matching the existing pattern.
- Regenerate `.generated/hk-transport-artifact.json` + `-zh.json`, add ZH strings to `HK_TRANSPORT_ZH` in `package-dashboard.mjs`.

### Task 1.8: Verify
- `pytest tests/test_asia_markets_wiring.py -k hk_transport`
- Isolate-test packaging (chart series count, mobile viewport) before a full `npm run build`.

### Group 1 implementation note — 2026-07-31

Implemented in the shared `hk_transport` pipeline and artifact. The TD
vacancy feed itself does not publish a capacity denominator, so it remains the
separate `td_parking_vacancy` current snapshot. The derived
`td_carpark_occupancy` signal instead uses TD's official metered-space
inventory plus the matching occupied/vacant status CSV; this gives a real
observed-space denominator without claiming coverage of every car park.
Table 4.1(a), Table 4.1(c), Table 2.3 and C&SD E705 are persisted as reusable
Parquet histories, with fleet EV share, net registrations, MTTD journeys and
E705 movement views wired into the artifact. The occupancy chart is shown only
after at least two dated polls.

Verification completed: 28 focused transport tests, 37 wiring tests, 11
artifact tests, and isolated English/Chinese portable delivery (1440px and
390px viewports) all passed. A full multi-sector package remains separately
blocked by the pre-existing `hk-local-consumer` mobile horizontal-overflow
failure; the `hk-transport` package itself passes.

---

## Group 2 — Real Estate Supply-Side Signals (extends `hk_real_estate`) — DONE 2026-07-31

### Task 2.1: Government land disposals — DONE
- **Created:** `src/hk_real_estate/sources/land_disposals.py` — fetches C&SD product `D7000004` ("Table E704", quarterly since 2021 Q1), parses the 4-level merged-header XLSX (method × district × use category × metric) into a long-format frame.
- Wired into `build_hk_real_estate_artifact.py`: new `PUBLIC_SOURCES["censtatd_land_disposals"]` entry, `censtatd_land_disposals_chart` (2 series: Public Auction/Tender vs. Private Treaty Grant, quarterly total area sq.m.), new block. ZH strings added to `HK_REAL_ESTATE_ZH` in `package-dashboard.mjs` (chart, source label, and `dataLabels.censtatd_land_disposals_area.series` translations).
- Verified: `tests/test_asia_markets_wiring.py` (37 passed) + `tests/test_hk_real_estate_dashboard.py`/`test_hk_real_estate_pipeline.py` (60 passed) + a direct builder run producing a valid `.generated/hk-real-estate-artifact.json` with real, current (through 2026 Q1) data.
- **Note:** an earlier verification pass's cited example value ("2021 Q4 Residential/NT: 47,967 sq.m.") was wrong — that figure is actually Urban/Commercial. Corrected in the ledger; the shipped parser was built from an independently re-derived and directly-checked column mapping, not from that citation.
- **Deferred, not blocking:** `-zh.json` artifact regeneration and full `npm run build` packaging verification (mobile-viewport chart-series check) were intentionally not run this pass — `package-dashboard.mjs` iterates every live sector with no single-sector filter, and another session was concurrently modifying `hk_transport`/`hk_labour_market`/`hk_utilities`; running the full multi-sector pipeline risked colliding with that in-progress work. Safe to run whenever no other session is mid-build.

### Task 2.2: Gross value of construction works — ALREADY BUILT, discovered during this task
Turned out to already be fully wired (`PUBLIC_SOURCES["cnsd_construction"]`, `cnsd_construction_value_chart`, `cnsd_construction_value` dataset) in `build_hk_real_estate_artifact.py` before this session touched it — this plan's original assumption that it was unbuilt was wrong. No work needed; verify this in a codebase before re-planning it elsewhere.

---

## Group 3 — Macro Economy, plus dispersal of theme-fitting pieces (DECIDED)

Architecture decision made: this dashboard organizes by **theme, not by macro-vs-micro** — `hk_labour_market` is already proof that a macro topic (unemployment/wages) can be a narrow, standalone sector when its scope is tight. Applying that same test to each Group 3 source: three have a natural existing home and should disperse there; two (GDP, external trade) are genuinely homeless and get one new, narrowly-scoped sector.

### Task 3.1: CPI → `hk_local_consumer` — DONE 2026-07-31
- **Created:** `src/hk_local_consumer/sources/censtatd_cpi.py` — `510-60001` (headline, monthly since Oct 1974, 549 rows) + `510-60003` (COICOP category sub-indices, monthly only since 2005 — thirty years shorter, as expected).
- Wired: `cpi_card` (Composite CPI + MoM/YoY), `cpi_trend` chart (headline), `cpi_by_category_chart` (3 series: Food, Housing/Water/Electricity/Gas, Transport — the other 10 COICOP categories are fetched and available in the dataset but not charted, to stay under the mobile-viewport series cap). ZH strings added. Verified: builder runs clean, 37/37 wiring tests, 17/17 existing local-consumer pipeline tests.

### Task 3.2: Visitor arrivals by nationality → `hk_population_migration` — DONE 2026-07-31
- **Created:** `src/hk_population_migration/sources/censtatd_visitor_arrivals.py` — table `650-80001` via the `api/get.php` JSON endpoint (not the MDT_ CSV pattern: the CSV silently mis-parses the real region code `"NA"` for North Asia as a pandas missing value, confirmed while building this; the JSON API already includes a human-readable `REGIONDesc` field and sidesteps the issue entirely). Monthly since 2004, 11 regions.
- Wired: `kpi_visitor_arrivals` card, `visitor_arrivals_chart` (Mainland China vs. Rest of World, 2 series — the full 11-region breakdown would need too many legend entries, so this collapses it to the informative summary while keeping the full per-region data in `visitor_arrivals_by_region` for anyone wanting detail). ZH strings added.

### Task 3.3: Port container throughput → `hk_transport` — SKIPPED, deferred to the other session
- Not attempted this pass: the other session was actively building out all of Group 1 in `hk_transport` concurrently (new source files for car park vacancy, EV registration, fleet stock, net registration, boundary movements, passenger journeys all appeared mid-session). Touching `build_hk_transport_artifact.py` or `src/hk_transport/` right now risked colliding with in-progress work. Table `410-55294` (monthly since 1997) is still real, verified, and unbuilt — pick this up whenever `hk_transport` isn't mid-edit elsewhere.

### Task 3.4: FEHD licensed premises → `hk_local_consumer` — DONE 2026-07-31 (current-state census; diff signal is real but starts empty)
- **Created:** `src/hk_local_consumer/sources/fehd_licensed_premises.py` — `LP_Restaurants_EN.XML`, 17,144 real restaurant licences, daily-regenerated. Added `fehd_licensed_premises_daily` to `pipeline.py`'s `run_stage_1_pipeline` (as a `"catalog"`-kind `QUALITY_SPECS` entry) so a new immutable snapshot gets persisted every scheduled run, going forward.
- Shipped two real, distinct pieces: (1) `compute_density_by_district` — a current-state census (licensed restaurants by district, all 19 FEHD districts, works immediately from a single snapshot) — wired as `fehd_card` + `fehd_district_chart`. (2) `diff_against_previous_snapshot` — nets opened/closed licence numbers against the most recently *stored* prior snapshot; wired as the `fehd_opened_closed` dataset but **deliberately has no chart/table block yet** since it's correctly empty until a second pipeline run exists to diff against (same honest thin-start pattern as this sector's existing AFCD wholesale-price trend). Add the display block once a few days of scheduled runs have accumulated.

### Task 3.5: New sector — `hk_macro_economy` (GDP + external trade only)
Scoped as tight as `hk_labour_market` — aggregate output and trade, nothing else. Do not let this become a catch-all for future unhomed datasets; if something new doesn't fit an existing sector *or* this one, that's a sign it needs its own sector, not a slot here.

- **Create package:** `src/hk_macro_economy/` (`config.py`, `sources/gdp.py`, `sources/gdp_by_sector.py`, `sources/external_trade.py`), mirroring the shape of `src/hk_labour_market/`.
- **`sources/gdp.py`:** `310-31001` (headline real/nominal GDP, deflator, per-capita — quarterly since 1973, annual since 1961) + `310-31002` (components: PCE, Govt Consumption, GDFCF, Exports/Imports — quarterly since 1973).
- **`sources/gdp_by_sector.py`:** `310-34501` (quarterly since 2000, preferred over the annual `310-34101` for freshness) — value-added by economic activity; keep only Financial Services, Real Estate, Retail/Wholesale, Accommodation/F&B, Transportation for the dashboard (others are supplementary if kept in the raw dataset, but chart series stay capped at 3).
- **`sources/external_trade.py`:** `410-50011` (monthly since 1972, imports/exports/re-exports by partner — Mainland/US/Japan/Taiwan + 4 ASEAN members).
- **Create builder:** `apps/asia-markets-dashboard/scripts/build_hk_macro_economy_artifact.py`, following the `build_hk_stablecoin_crypto_artifact.py` shape (smallest existing example) for the manifest/snapshot/sources/package_info contract.
  - **Cards:** latest Real GDP YoY%, latest nominal GDP level, latest trade balance (exports − imports), latest GDFCF YoY%.
  - **Charts** (≤3 series each): GDP growth (Real GDP YoY% + QoQ seasonally-adjusted%); GDP by sector (Financial Services / Real Estate / Retail-Wholesale value-added); Trade (Imports / Exports / Re-exports).
- **Register in `sectors.json`:** next unused code (currently `10` and `11` are taken by population-migration and labour-market — use `12`), `id: "hk-macro-economy"`, `package: "hk_macro_economy"`.
- **Add `HK_MACRO_ECONOMY_ZH` to `package-dashboard.mjs`'s `ZH_DICTIONARIES`.**
- **Clear the `tests/test_asia_markets_wiring.py` allowlists** for this package/builder once wired (should need no allowlist entries at all if done in one pass, same as the population-migration and labour-market onboarding).

---

## Suggested build order

1. Group 2 (smallest, lowest-risk, extends a sector already well understood).
2. Group 3, Tasks 3.1–3.3 (small dispersal tasks into sectors that already exist — same shape as Group 2, low risk).
3. Group 1 (DONE — the car-park vacancy/occupancy signal is the closest thing found today to the "clean derived signal" discussed earlier this session).
4. Group 3, Task 3.4 (FEHD — needs new diffing infra, more effort than a stateless fetch).
5. Group 3, Task 3.5 (new `hk_macro_economy` sector — full onboarding, do last since it's the biggest single task).
