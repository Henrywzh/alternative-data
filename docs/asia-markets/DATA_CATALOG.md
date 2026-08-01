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
| Hong Kong real estate | `build_hk_real_estate_artifact.py` | CCL, CCI, CRI/rental yield, CSI, MHPI weekly/monthly, Midland field dictionary/economic indicators/market snapshots/registration snapshots, policy-source catalogue and registry audit, property-event research hints, RVD residential and commercial price/rent, HKMA mortgage, Land Registry, agency transactions, 28Hse EPI/ERI, Buildings Department | Centaline Tranche 1 and RVD commercial Tranche 3 are normalized with explicit lineage and are wired into the Stage 1 regime/commercial views; Midland Tranches 2/4/5 remain ingestion/status-first and are not yet charted. Routine `run-all` includes these tranches (with Midland skip support for WAF-blocked CI). Centaline history covers only charted CSI residential price/rent fields, while office/industrial/retail values are snapshots. Midland macro fields remain Midland-derived pending reconciliation; units are persisted in `midland_field_dictionary`; property events remain research-only until primary-source matching. RVD commercial rows preserve grade/metric and provisional flags. Md52–Md56 remains a snapshot; the archive-backed normalized stage history covers 2005-01 to 2026-05, while the dashboard charts show only the latest ten-year lookback for readability; Md52 remains count-only; transaction display is capped. Multi-parent datasets expose `raw_snapshots`/`source_urls` lineage arrays. |
| Hong Kong local consumer | `build_hk_local_consumer_artifact.py` | weather, immigration, gold, retail, restaurant receipts, valuations, complaints, Price Watch archive coverage and matched-item index, price/food data, store footprints where available | Historical trend charts use a date-based latest-ten-year window, or all available history when shorter. Consumer Council valuation history is currently source-limited to about one rolling year; AFCD category prices are run-accumulated snapshots rather than a backfilled history. Price Watch uses a product-code-matched chain index by supermarket, not a simple average across changing product lists; it does not adjust for promotions or pack-size changes. Footprints are not yet trends. |
| Hong Kong utilities | `build_hk_utilities_artifact.py` | CLP, Towngas, temperature/weather, DSD daily sewage flow and effluent laboratory observations, WSD temporary water-suspension events | Towngas and HKO chart views use the latest ten years of available history by date; HKO source ingestion no longer discards pre-2021 observations. DSD preserves daily source grain but treatment-works coverage changes over time and laboratory columns are sparse. WSD is a five-minute current event snapshot, not a water-consumption time series; scheduled future notices remain in the event table. Company disclosures have different cadences and may be quarterly or semiannual. |
| Hong Kong transport | `build_hk_transport_artifact.py` | MTR patronage, Cathay/HKIA traffic, China listed airlines, TD Table 2.1 public transport passenger journeys by operator/mode, MTTD Table 2.3 passenger journeys by mode, C&SD E705 cross-boundary movements, TD Table 4.1(a) private-car fleet by fuel type, TD Table 4.1(c) private-car net first registration, TD Table 4.1(e) monthly private-car first registration by make/fuel, latest private-car make/model detail, TD real-time car-park vacancy, TD metered/on-street parking-space occupancy | MTR service-type breakdown uses the latest ten years by date; total MTR/Cathay/airline histories retain their longer available coverage. Monthly and weekly series must keep their source cadence and year visible. MTTD Table 2.3 is monthly and currently reaches 2013-01, with a normal 2–3 month publication lag. E705 is monthly and currently reaches 2026-05; latest cells may be provisional estimates. The current 4.1(a) and 4.1(c) workbooks provide monthly rows from 2025-01; they add registered-fleet EV share and net registration history, respectively. The TD make/fuel series remains the longer EV-registration flow history. The 548-car-park vacancy feed is a five-minute current snapshot and excludes vacancy types B/C and negative/no-data values. Metered occupancy is a separate sensor-backed signal over 20k listed spaces, not a denominator for all car parks; its history chart appears only after repeated collector runs. The three TD Table 2.1/4.1(a)/4.1(c) scrapers recompute TD's own published subtotals from their parts and refuse to write output that doesn't reconcile. EV fleet share is of the registered (not licensed) fleet; EV first-registration share is a monthly flow share. |
| Hong Kong telecom | `build_hk_telecom_artifact.py` | HKT, SmarTone, Hutchison Telecom, numbering-plan snapshots | Operator disclosures are usually semiannual; numbering-plan data is irregular. |
| Hong Kong labour market | `build_hk_labour_market_artifact.py` | C&SD labour force, unemployment, vacancies, wage/payroll indices, median employment earnings by industry/occupation, talent-policy flows | Labour-force and earnings series use rolling-three-month observations; vacancies and wage/payroll data are quarterly; policy flows are annual. |
| Hong Kong REITs | `build_hk_reit_artifact.py` | NAV, DPU, occupancy, rent reversion, hotel KPIs, spot prices | Fundamental disclosures have irregular cadence; spot history may be partial. |
| Commercial aerospace | `build_hk_commercial_aerospace_artifact.py` | IPO status, launches, satellite counts, patents | Several measures are estimates or availability-limited; do not overstate coverage. |
| Stablecoin and crypto | `build_hk_stablecoin_crypto_artifact.py` | HKMA/SFC registers, ETF AUM, stablecoin supply, DEX volume, sentiment, BTC | Stablecoin supply, DEX, sentiment and BTC charts now request long-run available history (latest-ten-year default); source coverage begins in 2016–2018 for these public APIs, while ETF/register/watchlist views remain snapshots or shorter-lived histories. |
| Hong Kong population and migration | `build_hk_population_migration_artifact.py` | ImmD daily passenger traffic, C&SD population/net movement, MPFA permanent-departure claims, UGC non-local enrolment, Transport Department cross-border traffic, C&SD visitor arrivals by region | Cadences are mixed: daily, half-yearly, quarterly, annual and monthly. Stage 1 persists normalized run-scoped Parquet; the builder prefers that local data and only bootstraps by fetch when absent. Status retains each source's own latest observation; comparison charts use explicit tidy series rather than silently plotting only one retained field. C&SD visitor-arrivals normalized data retains the full source history, while the portable artifact's regional detail and comparison chart use the latest ten years to stay below the runtime's per-dataset row limit. |

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
