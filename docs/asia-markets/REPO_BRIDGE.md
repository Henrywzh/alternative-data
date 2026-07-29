# Asia Markets ↔ Financial Data Repository Bridge

This project and the sibling `financial-data` repository are one research
workflow split across two repositories:

| Repository | Absolute path | Primary role |
|---|---|---|
| `alternative-data` | `/Users/henrywzh/Desktop/Quant/alternative-data` | Alternative-data pipelines, research notes and the non-Streamlit Cloudflare dashboard |
| `financial-data` | `/Users/henrywzh/Desktop/Quant/financial-data` | Point-in-time financial statements, consensus, HKEX metadata and DuckDB/Parquet storage |

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
3. A future implementation must add an explicit listing market/exchange field,
   make the HKEX collector conditional on `exchange == HKEX`, and preserve the
   original ticker format for yfinance/other market-compatible sources.
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
