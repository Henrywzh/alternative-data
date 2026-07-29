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
| Hong Kong real estate | `build_hk_real_estate_artifact.py` | CCL, MHPI, confidence, RVD price/rent, HKMA mortgage, Land Registry, agency transactions, 28Hse EPI/ERI, Buildings Department | BD Md52–Md56 lifecycle data is currently a snapshot; Md52 is count-only; transaction display is capped. |
| Hong Kong local consumer | `build_hk_local_consumer_artifact.py` | weather, immigration, gold, retail, restaurant receipts, valuations, complaints, price/food data, store footprints where available | Some endpoints are shallow, stale or unavailable; footprints are not yet trends. |
| Hong Kong utilities | `build_hk_utilities_artifact.py` | CLP, Towngas, temperature/weather | Company disclosures have different cadences and may be quarterly or semiannual. |
| Hong Kong transport | `build_hk_transport_artifact.py` | MTR patronage, Cathay/HKIA traffic, China listed airlines | Monthly series must keep month and year visible. |
| Hong Kong telecom | `build_hk_telecom_artifact.py` | HKT, SmarTone, Hutchison Telecom, numbering-plan snapshots | Operator disclosures are usually semiannual; numbering-plan data is irregular. |
| Hong Kong REITs | `build_hk_reit_artifact.py` | NAV, DPU, occupancy, rent reversion, hotel KPIs, spot prices | Fundamental disclosures have irregular cadence; spot history may be partial. |
| Commercial aerospace | `build_hk_commercial_aerospace_artifact.py` | IPO status, launches, satellite counts, patents | Several measures are estimates or availability-limited; do not overstate coverage. |
| Stablecoin and crypto | `build_hk_stablecoin_crypto_artifact.py` | HKMA/SFC registers, ETF AUM, stablecoin supply, DEX volume, sentiment, BTC | Some series are current snapshots or public APIs with changing availability. |

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
| Raw Mdxx archive | Md11–Md17, Md21–Md25, Md31, Md41, Md51–Md56 | Current official XLS raw snapshots | Raw archival coverage only unless separately normalized. |

Do not calculate MoM/YoY for the last two datasets until historical Md52–Md56
files are collected and normalized at the same grain.

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
