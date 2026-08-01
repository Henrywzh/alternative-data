# Asia Markets Data Catalog

This is the quick map from dashboard sector to builder, artifact and main data
families. The authoritative roster is `apps/asia-markets-dashboard/sectors.json`.

## Cross-repository financial data

The sibling `/Users/henrywzh/Desktop/Quant/financial-data` repository owns the
canonical point-in-time financial database. Its active V1 contains 174 HKEX
securities, including HKEX `0388.HK`. The proposed Asia finance extension is
tracked in [`financial-data/universes/asia-finance-v1.md`](../../../financial-data/universes/asia-finance-v1.md)
and is not yet collected by the dashboard.

Planned names: `FUTU`, `TIGR`, `6030.HK`, `6099.HK`, `3908.HK`, `1776.HK`,
`6066.HK`, `2611.HK` and `300059.SZ`. Treat them as separate categories:
online broker, traditional broker/investment bank, exchange infrastructure and
wealth/data platform. A planned registry entry must not be described as a live
dashboard dataset.

| Sector | Builder | Main data families | Important caveat |
|---|---|---|---|
| Hong Kong real estate | `build_hk_real_estate_artifact.py` | CCL, CCI, CRI/rental yield, CSI, MHPI weekly/monthly, Midland field dictionary/economic indicators/market snapshots/registration snapshots, policy-source catalogue and registry audit, property-event research hints, RVD residential and commercial price/rent, HKMA mortgage, Land Registry, agency transactions, 28Hse EPI/ERI, SRPE first-hand sales document catalogue, bounded PDF backfill and project-month signals, Buildings Department | Centaline Tranche 1 and RVD commercial Tranche 3 are normalized with explicit lineage and are wired into the Stage 1 regime/commercial views; Midland Tranches 2/4/5 remain ingestion/status-first and are not yet charted. SRPE bounded run `2a390f89-439d-4619-b30c-c9ab0b8cfa1e` produced 2,892 transaction events, 1,585 price-list unit rows, 196 project-month signal rows and 18 successful document audit rows across six registered phases. The dashboard now exposes four SRPE KPI cards, top-three developer/project time series and a six-phase latest-project table; the full developer/project expansion remains catalog-only. SRPE raw event counts must be distinguished from unit-level active sell-through because registers include PASP/ASP updates and re-sales. Public history depends on retained PDF versions and stale manifest rows must be logged. Centaline history covers only charted CSI residential price/rent fields, while office/industrial/retail values are snapshots. Midland macro fields remain Midland-derived pending reconciliation; units are persisted in `midland_field_dictionary`; property events remain research-only until primary-source matching. RVD commercial rows preserve grade/metric and provisional flags. Md52–Md56 remains a snapshot; the archive-backed normalized stage history covers 2005-01 to 2026-05, while the dashboard charts show only the latest ten-year lookback for readability; Md52 remains count-only; transaction display is capped. Multi-parent datasets expose `raw_snapshots`/`source_urls` lineage arrays. |
| Hong Kong local consumer | `build_hk_local_consumer_artifact.py` | weather, immigration, gold, retail, restaurant receipts, valuations, complaints, Price Watch archive coverage and matched-item index, price/food data, store footprints where available | Historical trend charts use a date-based latest-ten-year window, or all available history when shorter. Consumer Council valuation history is currently source-limited to about one rolling year; AFCD category prices are run-accumulated snapshots rather than a backfilled history. Price Watch uses a product-code-matched chain index by supermarket, not a simple average across changing product lists; it does not adjust for promotions or pack-size changes. Footprints are not yet trends. |
| Hong Kong utilities | `build_hk_utilities_artifact.py` | CLP, Towngas, temperature/weather, DSD daily sewage flow and effluent laboratory observations, WSD temporary water-suspension events | Towngas and HKO chart views use the latest ten years of available history by date; HKO source ingestion no longer discards pre-2021 observations. DSD preserves daily source grain but treatment-works coverage changes over time and laboratory columns are sparse. WSD is a five-minute current event snapshot, not a water-consumption time series; scheduled future notices remain in the event table. Company disclosures have different cadences and may be quarterly or semiannual. |
| Hong Kong transport | `build_hk_transport_artifact.py` | MTR patronage, Cathay/HKIA traffic, Cathay Cargo monthly tonnage/AFTK/RFTK/load factor/flight sectors, Cathay official Fleet Profile reports, six China-listed airline groups' passenger and cargo operating data, sparse airline fleet/route events, TD Table 2.1 public transport passenger journeys by operator/mode, MTTD Table 2.3 passenger journeys by mode, C&SD E705 cross-boundary movements, TD Table 4.1(a) private-car fleet by fuel type, TD Table 4.1(c) private-car net first registration, TD Table 4.1(e) monthly private-car first registration by make/fuel, latest private-car make/model detail, TD real-time car-park vacancy, TD metered/on-street parking-space occupancy | MTR service-type breakdown uses the latest ten years by date; total MTR/Cathay/airline histories retain their longer available coverage. Cathay monthly traffic PDFs recover passenger history from 2012-12 to 2026-06; cargo tonnage/AFTK/cargo load factor are broadly complete across the recovered archive, while RFTK and flight-sector labels vary by report era and are never silently backfilled. Cathay Fleet Profile totals cover 2015-06 to 2025-12 at annual/interim report cadence; the 2019 report path is unavailable and no monthly interpolation is performed. The six listed-airline histories currently run monthly to 2026-06, with Air China/China Southern/China Eastern/Spring/Juneyao from 2016-01 and Hainan from 2016-06. Passenger fields are ASK/RPK/passengers/load factor; cargo fields normalize cargo/mail tonnes and RFTK/AFTK across issuer units, including wrapped unit rows. Juneyao's carrier-level passenger-by-region drill-down preserves explicit source dashes as zero but leaves blank issuer cells missing; its four cross-page passenger-header gaps in 2023-04, 2023-07, 2024-04 and 2024-11 are repaired in the normalized parquet. The separate airline event layer contains disclosed fleet additions/retirements/totals and new-route phrases; explicit no-new-route disclosures are represented as zero, while months with no route disclosure remain absent and raw detail is retained. Early China Eastern fleet tables are reconciled from the fleet-total row rather than freighter subtotals. Latest tables preserve reporting scope: Hainan is an eight-operating-carrier group consolidation and Juneyao includes Jiuyuan Airlines. Monthly and weekly series must keep their source cadence and year visible. MTTD Table 2.3 is monthly and currently reaches 2013-01, with a normal 2–3 month publication lag. E705 is monthly and currently reaches 2026-05; latest cells may be provisional estimates. The current 4.1(a) and 4.1(c) workbooks provide monthly rows from 2025-01; they add registered-fleet EV share and net registration history, respectively. The TD make/fuel series remains the longer EV-registration flow history. The 548-car-park vacancy feed is a five-minute current snapshot and excludes vacancy types B/C and negative/no-data values. Metered occupancy is a separate sensor-backed signal over 20k listed spaces, not a denominator for all car parks; its history chart appears only after repeated collector runs. The three TD Table 2.1/4.1(a)/4.1(c) scrapers recompute TD's own published subtotals from their parts and refuse to write output that doesn't reconcile. EV fleet share is of the registered (not licensed) fleet; EV first-registration share is a monthly flow share. Some official Spring cargo load-factor observations exceed 100%; these are retained as source anomalies rather than clipped. |
| Hong Kong telecom | `build_hk_telecom_artifact.py` | HKT, SmarTone, Hutchison Telecom, numbering-plan snapshots | Operator disclosures are usually semiannual; numbering-plan data is irregular. |
| Hong Kong labour market | `build_hk_labour_market_artifact.py` | C&SD labour force, unemployment, vacancies, wage/payroll indices, median employment earnings by industry/occupation, talent-policy flows | Labour-force and earnings series use rolling-three-month observations; vacancies and wage/payroll data are quarterly; policy flows are annual. |
| Hong Kong REITs | `build_hk_reit_artifact.py` | NAV, DPU, occupancy, rent reversion, hotel KPIs, spot prices | Fundamental disclosures have irregular cadence; spot history may be partial. |
| Commercial aerospace | `build_hk_commercial_aerospace_artifact.py` | Official CASC/CALT Long March and Jielong event baseline, exact-provider Launch Library 2 events and monthly cadence, LL2 national/state enrichment, CelesTrak constellation snapshots/history, FAA commercial-space KPIs, USAspending contracts, SEC company filings, global objects-launched benchmark, patents | The verified first-party launch baseline currently covers 1970-04-24 to 2026-07-30 with 598 Long March `national_program` events and 11 Jielong `state_owned_commercial` events; `china_launch_monthly` is zero-filled and reconciles to canonical events, while the existing `launch_monthly`/`launch_monthly_total` views remain commercial-provider-only. LL2 national rows enrich official events but LL2-only candidates are excluded; cached enrichment is marked stale under the 15-request/hour free-tier limit. Kuaizhou/CASIC and other state families are explicit V1 coverage gaps. CelesTrak counts tracked objects rather than confirmed operational satellites and currently has only a short repeated-snapshot history; SZSE's classification includes aviation/rail/other transport equipment; FAA KPIs are current snapshots rather than a historical event series; SEC data is filing-event discovery only and does not infer order/financing amounts; global benchmark counts objects/payloads, not rocket launches; Google Patents is currently unavailable. |
| Stablecoin and crypto | `build_hk_stablecoin_crypto_artifact.py` | HKMA/SFC registers, ETF AUM, stablecoin supply, DEX volume, sentiment, BTC, SFC/HKMA regulatory news, HKEXnews watchlist company announcements, watchlist live stock quotes | Stablecoin supply, DEX, sentiment and BTC charts now request long-run available history (latest-ten-year default); source coverage begins in 2016–2018 for these public APIs, while ETF/register/watchlist views remain snapshots or shorter-lived histories. SFC/HKMA news is crypto-keyword-filtered over the trailing ~13 months, capped per-regulator (20 each) before merging so a higher-frequency source cannot crowd the other one out. HKEXnews company announcements cover the trailing 90 days for every watchlist ticker, resolved through the prefix-autocomplete endpoint with a hard STOCK_CODE cross-check (the raw title-search servlet silently returns a different company's filings for an unresolved ticker). Watchlist live quotes are a same-day snapshot via akshare/eastmoney and can be transiently unavailable if that upstream endpoint is flaky; the dashboard reports it as degraded rather than fabricating a price. |
| Hong Kong population and migration | `build_hk_population_migration_artifact.py` | ImmD daily passenger traffic, C&SD population/net movement, MPFA permanent-departure claims, UGC non-local enrolment, Transport Department cross-border traffic, C&SD visitor arrivals by region | Cadences are mixed: daily, half-yearly, quarterly, annual and monthly. Stage 1 persists normalized run-scoped Parquet; the builder prefers that local data and only bootstraps by fetch when absent. MPFA uses the latest locally cached official digest PDFs as a network fallback, never the stale JSON snapshots. Status retains each source's own latest observation; comparison charts use explicit tidy series rather than silently plotting only one retained field. C&SD visitor-arrivals normalized data retains the full source history, while the portable artifact's regional detail and comparison chart use the latest ten years to stay below the runtime's per-dataset row limit. |

### SHKP project-universe tranche

The `run-shkp-catalog` runner writes four separate, lineage-preserving
datasets under `data/normalized/hk_real_estate/`:

| Dataset | Grain | Current coverage | Interpretation / caveat |
|---|---|---|---|
| `shkp_property_catalog` | Current SHKP website listing row | 109 rows: 43 residential-for-sale, 2 residential-for-lease, 27 malls, 24 offices, 10 hotels and 3 serviced suites | Official SHKP marketing/asset directory snapshot. The industrial page is currently a static photo album rather than a structured project feed; absence from this table is not evidence of no industrial asset. |
| `srpe_development_index` | SRPE development/phase row | 522 rows: 360 active and 162 inactive at the 2026-08-01 fetch | Official SRPE all-development index. It is a first-hand residential development/phase universe, not all Hong Kong housing and not a developer-ownership table. |
| `shkp_srpe_crosswalk` | SHKP residential listing × candidate SRPE development/phase | 74 candidate rows from the 43 current SHKP residential listings | Exact official website-domain and exact normalized-English-name candidates are retained. Shared domains and multi-phase names are marked `ambiguous`/`matched_needs_review`; ownership fields (`listed_parent`, `ticker`, `ownership_pct`, effective dates and evidence URL/level) are explicit but `not_verified` until disclosure evidence is attached. |
| `shkp_corporate_documents` | Official SHKP investor/quarterly/announcement PDF link | 333 links in the latest fetch: 31 annual reports, 40 interim reports, 244 quarterly articles, 6 results presentations, 8 announcements and 4 other financial reports | Document discovery/catalogue only. Annual-report project-table extraction, publication-time semantics and project ownership evidence are follow-up stages; quarterly page availability should be checked on each refresh. |
| `shkp_pipeline_disclosures` | Curated project-label evidence row from an official SHKP disclosure | 8 rows from the 2025/26 interim-results announcement: 6 planned launches over the next 10 months and 2 under-development projects | The labels are search anchors with retained surrounding text, not legal project IDs. `found` means the phrase was observed in this disclosure; it does not establish ownership percentage, start/completion date or revenue. |

The SHKP website catalogue and SRPE index should therefore be used for project
discovery and coverage auditing. They must not be summed into attributable
company sales until a dated ownership/evidence registry is reconciled against
annual reports, HKEX announcements, LandsD/TPB records and project documents.

## Artifact conventions

For a sector ID `<sector>`:

- English artifact: `apps/asia-markets-dashboard/.generated/<sector>-artifact.json`
- Chinese artifact: `apps/asia-markets-dashboard/.generated/<sector>-artifact-zh.json`
- English route: `/sectors/<sector>/`
- Chinese route: `/zh/sectors/<sector>/`
- Status JSON: `apps/asia-markets-dashboard/src/data/<statusFile>`

An artifact normally contains:

- `manifest.cards`: latest KPI cards;
- `manifest.charts`: chart definitions and encodings;
- `manifest.tables`: visible/detail tables;
- `snapshot.datasets`: the actual rows used by charts and tables;
- `source_health` / `source_coverage`: build-time lineage and coverage checks;
- `package_info` and `manifest.generatedAt`: snapshot identity and build time.

## Buildings Department detail

| Name | Files | Grain | Current dashboard use |
|---|---|---|---|
| `bd_monthly_stats` | Md11–Md17 | Historical summary-table rows | Detail/scratch table; numeric arrays are not fully semantically labelled. |
| `bd_supply_pipeline` | Md52–Md56 | Current project lifecycle grouped by stage, region and category | Current-month domestic-unit snapshot; Md52 is excluded because it has no unit field. |
| `bd_supply_floor_area` | Md52–Md56 | Current project lifecycle grouped by stage and property category | Current-month usable-floor-area snapshot; Md52 is excluded because it has no area field. |
| `bd_supply_pipeline_history` | Monthly Digest PDF archive, Section 1 Tables 1.2–1.7 | Monthly stage aggregate, all Hong Kong | Archive rows cover 2005-01 to 2026-05; dashboard charts use the latest ten-year lookback. Counts, domestic units and area are only populated where the official summary publishes each metric; it is not project-level lifecycle linkage. |
| Raw Mdxx archive | Md11–Md17, Md21–Md25, Md31, Md41, Md51–Md56 | Current official XLS raw snapshots | Raw archival coverage only unless separately normalized. |

MoM/YoY for the historical stage aggregate is valid only within the same
stage/metric series. Do not compare projects/consents, units and floor area as
one measure, and do not infer project-level stage progression from it.

## Freshness semantics

- A dated time series should expose its latest observation date and age.
- `Live` means the source was successfully fetched and validated as part of
  the build, when the builder uses that status.
- `Live at build time` means the source returned rows during the build but the
  current coverage record does not yet expose a reliable source observation
  date. It is not a live browser connection.
- `Snapshot` means the data is intentionally a point-in-time view.
- `Catalog only`, `planned`, `unavailable` and `stale/unreachable` must remain
  visible; do not convert them into healthy measures merely to improve the hub
  summary.
