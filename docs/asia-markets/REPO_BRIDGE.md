# Asia Markets ↔ Financial Data Repository Bridge

This project and the sibling `financial-data` repository are one research
workflow split across two repositories:

| Repository | Absolute path | Primary role |
|---|---|---|
| `alternative-data` | `/Users/henrywzh/Desktop/Quant/alternative-data` | Alternative-data pipelines, research notes and the non-Streamlit Cloudflare dashboard |
| `financial-data` | `/Users/henrywzh/Desktop/Quant/financial-data` | Point-in-time financial statements, consensus, daily free market valuations, HKEX metadata and DuckDB/Parquet storage |

Agents working in either repository must treat the other repository as an
existing sibling dependency and check its documentation before changing a
shared data contract.

## Current connection

`financial-data` currently owns the 174-security Hong Kong financial universe
and produces:

```text
/Users/henrywzh/Desktop/Quant/financial-data/data/databases/hk_financials.duckdb
```

The Asia Markets project can attach that database for research joins. Do not
copy it into `alternative-data` unless a task explicitly requires a published
artifact or a reproducible snapshot:

```sql
ATTACH '../financial-data/data/databases/hk_financials.duckdb' AS financials;
```

The current financial-data collectors are HKEX/HK-ticker oriented. The
cross-market list below is therefore a planning registry, not an instruction
to run the existing 174-security collection against unsupported ticker formats.

The exception is the daily market-valuation collector: it has a separate
183-listing registry for the 174 HKEX names plus the curated airline A/H
listings. It preserves native listing tickers and writes
`market_valuations_history` in the sibling DuckDB; it does not widen the
financial-statement or HKEX-announcement collectors.

The sibling also owns the HSCI PIT universe v1 collector. Its official-source
outputs live under `financial-data/data/processed/hk_pit_universe/` and are
safe to join only through the canonical event/interval contract. The collector
uses Hang Seng's free notices catalogue and live HSCI snapshot, preserves
official effective dates separately from activation dates, filters total-index
events to `Index Code = HSCI`, and keeps ad-hoc constituent PDFs in a manual
review queue until they are deterministically parsed. The live API's advertised
post-2008 `.xlsx` history link is currently HTTP 404, while the official legacy
`.xls` fallback provides a parsed 2001–2008 seed/event layer with no
announcement timestamp. The 2008–2021 Research bridge remains provisional;
do not use it as the source of truth. The sibling's separate provisional
`historical_review_events_active` layer now covers 1,158
direct/archived-official review actions from 2008-09-08 to 2021-09-06. Its
active source registry has 81 records (43 direct, 37 Wayback and one unresolved
strict-PIT HSCI-detail window at 2011-03-07); the raw source ledger has 91 rows.
The raw event ledger retains 1,213 observations and 64 correction records (ten
parser supersessions plus 54 `retire_event_unverified_pit` retirements for the
post-effective 2010-09-06 and 2011-09-05 review batches). The raw candidate
ledger has 272 observations, with 169 in the active candidate view and 221
candidate corrections (including fuzzy/phantom-row retirements such as the
`0181.HK` ordinal misread);
these include 63 rows from the post-effective 2011
Chinese detail, 50 rows diverted by the automatic `pit_availability_verified`
check, and 74 older official ad-hoc/prose/table/review rows. The strict replay
audit reports 90 state gaps (21 duplicate active adds and 69 inactive deletes);
its separate candidate-inclusive diagnostic replay uses 166 de-duplicated
candidate events and reports 4 (1 duplicate active add and 3 inactive deletes).
No combined interval mask is promoted. It is a
research/reconciliation input, not a canonical dashboard universe.
The sibling's market-cap PIT layer now also covers the full HSCI review
universe (`run-market-cap-pit --include-hsci`): 971 HK tickers with daily
market cap from 2023-01-03 (akshare Baidu daily + two-day proxy + yfinance
derived fallback); 62 historical names have no free-source data and are
flagged in coverage.
Daily OHLCV bars are consolidated in the same sibling DuckDB
(`market_data_bars`, 1,196,733 rows / 938 tickers / 2016-01-04+), fed by the
legacy research archives (imported as `yfinance_archive`) plus live
`run-market-data-bars --include-hsci` captures.  New research work should read
the sibling DuckDB instead of the legacy parquet archives.
The four gaps are explained in the sibling's
`historical_review_replay_explanations_v1.json` (three trace to the
Research-only 2008-10-08/10-20 batches, which remain without a recoverable
official source and are anchored for automatic re-probing; one is an official
redundancy for 1619).

## Research Control Tower consensus export

The accepted cross-repository consensus handoff is an explicit, build-time
export. The owner/producer is the sibling `financial-data` repository:

- `src/hk_financials/control_tower_export.py` — read-only exporter and the
  authoritative column/Arrow-schema constants;
- `scripts/build_control_tower_consensus_export.py` — explicit-path CLI that
  opens the canonical DuckDB read-only and writes the export directory.

The producer writes exactly these three files:

```text
control_tower_consensus_snapshots.parquet
control_tower_consensus_revisions.parquet
control_tower_consensus_source_health.parquet
```

The accepted physical schemas are exact and ordered: **29 snapshot columns,
35 revision columns and 12 source-health columns**. The producer constants and
the financial-data exporter tests are authoritative. The field families are:

- snapshots: snapshot/provider identity; `entity_id`, `listing_id`,
  `financial_data_security_id` and `canonical_ticker` crosswalk; metric,
  fiscal-period, estimate, value, statistic, dispersion and accounting/unit
  fields; then snapshot/PIT/provenance fields including `snapshot_at`,
  `provider_asof`, `retrieved_at_utc`, `source_url`, `raw_hash`, `pit_class`,
  `source_run_id`, `calculation_origin` and `coverage_reason`;
- revisions: revision/provider identity and `prior_provider`; the same
  security/listing crosswalk; current/prior aligned fiscal-period values and
  analyst/dispersion fields; lookback/cutoff/prior-snapshot fields; revision
  measures (`revision_value`, `revision_pct`, `analyst_count_change`) and the
  same PIT/provenance fields plus `alignment_status`;
- source health: provider/status/reason, row and mapping counts, latest
  snapshot and `as_of`, network-call count, and the license/entitlement
  evidence fields `source_license_class`, `entitlement_status`,
  `entitlement_evidence` and `entitlement_ref`.

The input crosswalk is explicit, not inferred from ticker text. It requires
`entity_id`, `listing_id`, `financial_data_security_id`, `canonical_ticker`,
`mapping_status`, `mapping_verified_at`, `mapping_source_url` and
`collection_eligible`; the exporter rejects ambiguous case-insensitive
duplicates for listing/security/ticker identifiers and admits only verified,
collection-eligible mappings. Native listing tickers and the stable security
ID remain distinct.

The `alternative-data` builder receives the export through the explicit
`BuildConfig.consensus_export_dir` path at build time, validates all three
files and publishes compact Control Tower marts. The Streamlit reader reads
only the selected published marts. There is no runtime sibling DuckDB attach,
import or collection call. Provider namespaces remain separate: revisions are
same-provider only, and misaligned fiscal periods do not produce a revision.

PIT and provenance are carried separately for observed/snapshot, retrieved,
provider-as-of and build-as-of semantics (`snapshot_at`/
`current_snapshot_at`, `retrieved_at_utc`, `provider_asof`, `cutoff_at`,
`pit_class`, `source_run_id` and health `as_of`). The builder/reader also retain
input SHA-256 fingerprints for cache/lineage and expose PIT, license and
entitlement display states in Source Health. Supported data providers
(`akshare`, `yfinance`) use `source_license_class=local_private_research` and
`entitlement_status=terms_unverified`. Optional coverage providers (`futu`,
`fnguide`, `alpha_vantage`, `fmp`) use
`source_license_class=entitlement_required` and
`entitlement_status=entitlement_required`; with no approved collector or
entitlement evidence, they remain `status=unavailable` with typed-empty
output. The contract asserts no redistribution rights.

Unknown populated providers fail closed under the Task 3 allowlist. Stale or
invalid optional exports become typed-empty consensus marts and degraded
source-health rows rather than fabricated or current-looking values; required
registry/event contracts and required inputs remain build-fatal. This bridge
section records the handoff only; it does not authorize hosting or public
redistribution.

## Planned Asia finance universe

| Company | Ticker | Listing market | Category | Status |
|---|---|---|---|---|
| Futu Holdings / 富途控股 | `FUTU` | NASDAQ | online broker / wealth platform | planned cross-market addition |
| UP Fintech / Tiger Brokers / 老虎证券 | `TIGR` | NASDAQ | online broker | planned cross-market addition |
| CITIC Securities / 中信证券 | `6030.HK` | HKEX | traditional broker / investment bank | planned HK addition |
| China Merchants Securities / 招商证券 | `6099.HK` | HKEX | traditional broker / investment bank | planned HK addition |
| China International Capital / 中金公司 | `3908.HK` | HKEX | investment bank / broker | planned HK addition |
| GF Securities / 广发证券 | `1776.HK` | HKEX | traditional broker | planned HK addition |
| CSC Financial / 中信建投证券 | `6066.HK` | HKEX | traditional broker | planned HK addition |
| Guotai Haitong Securities / 国泰海通证券 | `2611.HK` | HKEX | traditional broker / investment bank | planned HK addition |
| East Money / 东方财富 | `300059.SZ` | SZSE | online wealth platform / financial data | planned cross-market addition |
| HKEX / 香港交易所 | `0388.HK` | HKEX | exchange / market infrastructure | already in `financial-data` HK universe |

These names should be analysed in separate categories. Futu and Tiger are
closer operating peers; the traditional Chinese brokers are a broader capital
markets peer group; HKEX is market infrastructure; East Money is a wealth/data
platform rather than a direct broker peer.

## Rules for future changes

1. Keep `financial-data/universes/hk-v1.md` as the active HK-only V1 unless a
   deliberate universe expansion is approved.
2. Use a separate `financial-data/universes/asia-finance-v1.md` registry for
   the cross-market list until the schema and collectors support `HKEX`,
   `NASDAQ` and `SZSE` explicitly.
3. New cross-market financial collectors must add an explicit listing
   market/exchange field, make the HKEX collector conditional on
   `exchange == HKEX`, and preserve the original ticker format for
   yfinance/other market-compatible sources. The current valuation collector
   already follows this rule for its separate registry.
4. When financial data is added to the Asia Markets dashboard, record the
   source, observation period, currency and point-in-time availability in
   `DATA_CATALOG.md` and the financial-data run metadata.
5. Do not present a planned ticker as collected data until a real source run,
   validation result and database/artifact coverage check exist.

## Read next

- [Asia Markets operating manual](OPERATING_MANUAL.md)
- [Asia Markets project status](PROJECT_STATUS.md)
- [Asia Markets data catalog](DATA_CATALOG.md)
- Sibling [financial-data bridge](../../../financial-data/docs/ASIA_MARKETS_BRIDGE.md)
