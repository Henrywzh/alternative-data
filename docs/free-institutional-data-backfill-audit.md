# Free institutional-data backfill audit

Date: 2026-09-11  
Checkout: `/Users/henrywzh/Desktop/Quant/alternative-data`

This is the Phase 1–4 extraction result for the eight newly scoped sources. The
pipeline only writes the new source namespaces under `data/raw/` and
`data/normalized/`; existing FRED/OFR, VIX, CFTC, Eastmoney southbound, HKMA
mortgage, airline short-selling, and EIA benchmark-price pipelines were not
touched.

The common path is:

```text
official/public endpoint -> immutable raw snapshot -> source parser
-> normalized parquet/csv -> source manifest with hashes, coverage, and errors
```

The runner is `scripts/backfill_free_institutional_data.py`.

## Scheduled refresh

These lanes were backfilled once and then sat still: until 2026-09-12 no
workflow referenced any of them, so every dataset here was last written by the
backfill or by a bug fix, never by a refresh. Three workflows now drive them,
grouped by how often the sources actually publish.

| Workflow | Cron (UTC) | Sources | Registry pipeline |
| --- | --- | --- | --- |
| `free-institutional-daily.yml` | `10 5 * * *` | hkex, eia, hkma | `free-institutional-daily` |
| `free-institutional-weekly.yml` | `40 5 * * 1` | factset | `free-institutional-weekly` |
| `free-institutional-monthly.yml` | `10 6 6 * *` | sp_pmi, bis, msci | `free-institutional-monthly` |

Scheduled runs pass `--resume`. Only two lanes walk a date range, and their
backfill defaults are wrong for a schedule: `--hkex-start 2019-01-01` is ~1,750
trading days of fetches per run, and `--eia-start 2019-01-01T00` re-merges
2,800 partitions. `--resume` starts each just *behind* the newest stored
observation -- behind, not after, because EIA revises recent hours and a missed
publication would otherwise leave a permanent hole. The remaining lanes re-read
whatever the source currently publishes and upsert it, so they are already
incremental. An explicit `--eia-start` / `--hkex-start` overrides `--resume`,
and `full_backfill: true` on a manual dispatch refetches from 2019.

`cme` is deliberately unscheduled: cmegroup.com answers HTTP 403 to the runner,
so a scheduled job would fail every day and train everyone to ignore the alert.
It stays available through `workflow_dispatch` and starts working the moment
access changes.

Each lane is registered in `config/ops/pipelines.yaml` with a `max_age_days`
contract, so a source that quietly stops answering is reported `STALE` rather
than leaving a complete, structurally valid, frozen dataset that passes an
existence check forever. `bis_observations` is the exception and is checked for
existence only -- its `period` is a quarter label parsed to the quarter's first
day, and BIS publishes about two quarters in arrears, so any threshold loose
enough to be quiet would let the lane die for a year unnoticed.

## Source results

| Source | Grain / observed coverage | Normalized result | Status and investment use |
|---|---|---:|---|
| BIS credit-to-GDP gap | Quarterly, 7 series, 1957-Q4 to 2025-Q4 | 1,241 rows | **OK**. Slow leverage/cycle and crisis-risk regime input. |
| HKMA HIBOR / liquidity | Daily, 8 HIBOR tenors, 2017-03-20 to 2026-09-11 | 18,640 rows | **Partial**. Official API timed out; history is explicitly marked as Jin10 public-aggregator fallback, with HKAB current fixing page retained separately. Useful for HK funding sensitivity, but not yet an official-only series. |
| EIA EBA grid generation | Hourly, 5 balancing authorities × 8 fuel categories, 2019-01-01 to 2026-09-10T06 | 2,545,579 rows | **OK after ERCO repair**. Captures electricity demand/supply mix and energy-regime signals. EIA’s official respondent code for ERCOT is `ERCO`; 471,656 rows were added from the preserved full bulk ZIP. Null source values are retained rather than imputed. |
| CME volume / open interest | Intended daily bulletin sections for equity, rates, metals, and energy | 0 rows | **Blocked**. Public Daily Bulletin requests returned HTTP 403; official historical detail is routed through CME DataMine/entitlement, so no synthetic VOI data was created. |
| FactSet public Earnings Insight | Irregular/weekly public S&P 500 aggregate articles and infographics, report dates 2014-10-10 to 2026-09-03 | 218 rows | **Partial at archive boundary**. 888 candidate article URLs were processed through 83 pages; page 84 is a confirmed 404 boundary. Public earnings growth, EPS surprise, revenue, and forward P/E fields are normalized. Legacy parser outliers were repaired; forward P/E and its 10-year average now have no values ≥30. |
| S&P Global PMI public pages | Monthly homepage headline cards, currently 2026-08, 53 cards / regions and sectors | 53 rows | **Partial**. 170 release links were discovered, but release detail responses are AWS WAF challenge pages. Headline cards are usable for current cross-country diffusion signals; historical sub-indices are not claimed. |
| MSCI public index review lists | Review event rows, 419 review cycles, effective dates 2006-02-28 to 2026-08-31 | 71,602 rows | **OK with known legacy caveat**. 697 public PDFs yielded 72,261 raw events, deduped at the event grain. MSCI lists generally provide names rather than tickers, so identifiers remain blank rather than guessed; 13 provisional 2007 rows lack an effective date. |
| HKEX Stock Connect / short-selling JS | Daily rows 2019-01-02 to 2026-09-11; Stock Connect aggregate flow available for 2026-02-16 onward; short inventory/shares for 2019 onward | 1,814 rows | **Partial**. Historical short detail is present; the dated daily aggregate endpoint returned data for 149 days only, and short-selling value is zero-dominant while security counts/shares are populated. A 2026-07-03 daily response was non-data and is recorded as an error. |

## Quality checks performed

- Verified candidate composite keys and duplicate rates at each source grain.
- Verified raw manifest paths and SHA-256 hashes: 5,253 entries checked, with 0 missing files and 0 hash mismatches.
- Checked date/period ranges, source row counts, distinct series/respondents, enum values, nulls, and numeric ranges.
- Checked FactSet parser-specific leakage: related-article footer quarters, `S&P 500` being misread as P/E, and EPS percentage averages being misread as P/E averages.
- Checked EIA respondent coverage after the `ERCOT` → `ERCO` source-code correction.
- Preserved source nulls and blocked/partial responses; no imputation or guessed MSCI tickers were introduced.

## Remaining analytical risks

1. HKMA history is not official-only until the HKMA API timeout is resolved or an official bulk series is found.
2. CME VOI remains unavailable in this environment; the portfolio-positioning stream should treat it as a pending connector, not a zero signal.
3. PMI history and sub-indices are incomplete because release detail is WAF-blocked.
4. HKEX historical Stock Connect aggregate flow is incomplete before 2026-02-16 through this endpoint. Short value should not be used as a reliable turnover measure until independently reconciled; counts and shares are the safer current fields.
5. FactSet fields are public article snapshots, not vendor security-level consensus history. Publication date, observation period, and retrieval time must remain separate in any nowcast or backtest.

## Research routing

- **Macro regime:** BIS credit gap + HKMA HIBOR + EIA generation mix + PMI headline.
- **Asia markets:** MSCI rebalance events + HKEX Stock Connect/short inventory.
- **Equity nowcast:** FactSet public earnings-season snapshots.
- **Portfolio liquidity/positioning:** CME VOI when access is restored; do not substitute zeros.

## Run receipts

- Initial eight-source run: `data/raw/free_institutional_backfill/20260911T080315Z-87299763/manifest.json`
- EIA official full bulk: `data/raw/eia_energy/20260911T112038Z-75b4ff8b/manifest.json`
- EIA `ERCO` correction: `data/raw/eia_energy/20260911T121910Z-eia-erco-repair/manifest.json`
- Latest FactSet raw archive: `data/raw/factset_earnings/20260911T120436Z-58a90ab8/manifest.json`
- FactSet parser repairs: `data/raw/factset_earnings/20260911T121654Z-factset-pe-repair/manifest.json` and `data/raw/factset_earnings/20260911T122242Z-factset-pe-average-cleanup/manifest.json`

Official source pages used for the receipts: [BIS bulk downloads](https://data.bis.org/bulkdownload), [EIA bulk downloads](https://www.eia.gov/opendata/bulk-downloads.php), [HKMA interbank API documentation](https://apidocs.hkma.gov.hk/gb_chi/documentation/market-data-and-statistics/daily-monetary-statistics/daily-figures-interbank-liquidity/), [HKEX historical daily statistics](https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Statistics/Historical-Daily?sc_lang=en), [HKEX short-selling statistics](https://www.hkex.com.hk/Mutual-Market/Stock-Connect/Statistics/Short-Selling?sc_lang=en), [MSCI index review public lists](https://www.msci.com/eqb/gimi/stdindex/index_review.html), [CME Daily Bulletin](https://www.cmegroup.com/market-data/daily-bulletin.html), [CME DataMine](https://www.cmegroup.com/datamine/datamine-api.html), [FactSet Earnings Insight](https://insight.factset.com/topic/earnings), and [S&P Global PMI releases](https://pmi.spglobal.com/Public/Release/PressReleases?language=en).

## Column fill rates

Row counts above describe how many rows exist, not how many carry a value.
A lane can report thousands of rows while the fields it was built for are
empty, so the fill rate is the number to read before using a lane.

### S&P Global PMI

| Field | Non-null | Non-zero | Rows |
|---|---:|---:|---:|
| `headline_pmi` | 53 | 53 | 53 |
| `new_orders_index` | 0 | 0 | 53 |
| `output_index` | 0 | 0 | 53 |
| `finished_goods_inventory_index` | 0 | 0 | 53 |
| `input_prices_index` | 0 | 0 | 53 |
| `output_prices_index` | 0 | 0 | 53 |
| `employment_index` | 0 | 0 | 53 |
| `orders_to_inventory_ratio` | 0 | 0 | 53 |
| `price_pass_through_spread` | 0 | 0 | 53 |
| `release_date` | 53 | 0 | 53 |

### HKEX flow / short

| Field | Non-null | Non-zero | Rows |
|---|---:|---:|---:|
| `southbound_buy_turnover_hkd_mln` | 149 | 134 | 1814 |
| `southbound_sell_turnover_hkd_mln` | 149 | 134 | 1814 |
| `southbound_net_inflow_hkd_mln` | 149 | 134 | 1814 |
| `northbound_buy_turnover_rmb_mln` | 0 | 0 | 1814 |
| `northbound_sell_turnover_rmb_mln` | 0 | 0 | 1814 |
| `northbound_net_inflow_rmb_mln` | 0 | 0 | 1814 |
| `total_market_turnover_hkd_mln` | 0 | 0 | 1814 |
| `southbound_turnover_share_pct` | 0 | 0 | 1814 |
| `short_selling_turnover_hkd_mln` | 0 | 0 | 1814 |
| `short_selling_ratio_pct` | 0 | 0 | 1814 |
| `northbound_total_turnover_rmb_mln` | 149 | 134 | 1814 |
| `short_selling_turnover_rmb_mln` | 1799 | 1 | 1814 |
| `short_selling_security_count` | 1799 | 1799 | 1814 |
| `short_selling_turnover_shares` | 1799 | 1311 | 1814 |

### FactSet Earnings Insight

| Field | Non-null | Non-zero | Rows |
|---|---:|---:|---:|
| `blended_earnings_growth_yoy` | 131 | 131 | 218 |
| `blended_revenue_growth_yoy` | 124 | 124 | 218 |
| `eps_beat_rate` | 6 | 6 | 218 |
| `eps_surprise_pct` | 1 | 1 | 218 |
| `revenue_beat_rate` | 0 | 0 | 218 |
| `revenue_surprise_pct` | 0 | 0 | 218 |
| `forward_12m_pe` | 179 | 179 | 218 |
| `forward_12m_pe_10y_avg` | 103 | 103 | 218 |
| `revision_breadth_score` | 0 | 0 | 218 |
| `sector_growth_json` | 0 | 0 | 218 |

## Defects found and fixed after the backfill

An independent review of the shipped code found six defects that produced
plausible output rather than an error. None were caught by the per-source
tests, which used fixtures too minimal for the defects to appear. All are now
covered by `tests/test_free_institutional_source_regressions.py`.

| Defect | Effect on data | Status |
|---|---|---|
| `classify_positioning_flow` returned `NEUTRAL` when price data was absent | Every CME row would read NEUTRAL, indistinguishable from a real flat reading. The bulletin section carries no settlement prices, so no other value was reachable. | Fixed: returns `UNKNOWN` when an input is missing. CME collected 0 rows, so no stored data was affected. |
| PMI region matched candidates in list order over the whole page | A Eurozone release mentioning "U.S." in passing stored `region=US`. | Fixed: matched against the headline, earliest position wins, vendor branding stripped. Not triggered in stored data -- the release parser was WAF-blocked, so all 53 rows came from the homepage cards. |
| PMI sector derived from full page text | Any page containing "composite" stored `sector=COMPOSITE`. | Fixed: derived from the headline. |
| PMI sub-index labels overlapped (`output` inside `output prices`) | `output_index` took the Output Prices figure; both derived signals were unusable. | Fixed: bounded label window and explicit exclusions. |
| HKEX deduped on `trade_date` with `keep="last"` | The short-selling upsert replaced the flow row for the same day, nulling southbound turnover. The runner merged both before writing, so stored data is unaffected; any partial re-run would have hit it. | Fixed: same-day rows now merge field by field. |
| HKMA deduped on `(series_id, date)` with `keep="last"` | The Jin10 mirror and the official API share a series id, so whichever ran last won. | Fixed: rows carry `source_tier`, and an official reading outranks an aggregator one regardless of arrival order. Existing rows were backfilled: 18,632 `aggregator`, 8 `official_document`. |

Two further changes came out of the same review:

- The five pipelines with no in-package collector returned
  `{"observations_written": 0, "errors": {}}`, which reads as a clean run that
  collected nothing. They now raise and name the runner to use instead.
- `EiaEnergyPipeline.run` called the non-paginating fetch with `length=168`.
  That caps rows, not hours: across 5 respondents and 8 fuel types it was about
  five hours of data, and it could not page past the API's 5,000-row cap. It now
  uses the paginator over an explicit date range, and reports a missing
  `EIA_API_KEY` as a configuration error rather than failing with an opaque 403.

## Storage layout

Normalized panels are now committable: each lane has a `.gitignore` allowlist,
and raw manifests are tracked while payloads stay ignored. Before this the
backfill wrote 363 MB that git silently ignored.

`eia_grid_hourly` is stored as one parquet per observation day. As a single
table it was an 11.5 MB parquet rewritten in full on every refresh, and parquet
is compressed binary git cannot delta -- roughly 4 GB of history a year. The
2,545,579 rows now occupy 2,810 day partitions (20 MB), and a new day adds
about 5 KB. CSV twins were dropped from all eight lanes: `*.csv` is gitignored
repo-wide, so they were never published, and EIA's was 151 MB against a 12 MB
parquet.
