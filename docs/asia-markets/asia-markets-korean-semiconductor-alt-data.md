# Korean semiconductor alternative data

This note records the currently usable, non-Korean-identity-dependent pieces of
the SK Hynix and Samsung Electronics monitoring stack.

## Active sources

| Source | Package / dataset | Cadence | Access constraint | Intended signal |
|---|---|---:|---|---|
| U.S. Census Bureau International Trade API | `us_census_trade_data` / `us_census_memory_imports_monthly` | Monthly | Requires a Census API key; does not require a Korean phone number | U.S. imports of HS 854232 from selected partners: general/consumption value plus air/container/vessel value and shipping weight |
| U.S. Census Bureau Port-HS API | `us_census_trade_data` / `us_census_memory_imports_port_monthly` | Monthly | Same Census API key | Port-level U.S. import value and shipping-weight concentration by partner and HS |
| Taiwan MOPS | `taiwan_semiconductor_revenue_data` / `tw_monthly_revenue` | Monthly | Existing public MOPS adapter | Revenue momentum for memory supply-chain & AI server ODMs: Powertech (6239), Phison (8299), Nanya (2408), Winbond (2344), Foxconn (2317), Quanta (2382), Wistron (3231), Wiwynn (6669) |

The MOPS pipeline covers all 11 tracked companies by default. The four memory
watchlist companies and four major AI server ODMs are registered in the same source adapter with CLI presets:

```bash
taiwan-semiconductor-revenue-data \
  --companies memory update-latest

taiwan-semiconductor-revenue-data \
  --companies ai_server_odms update-latest
```

The Census API currently requires a key. Configure `CENSUS_DATA_API_KEY`,
`CENSUS_API_KEY` or `US_CENSUS_API_KEY` in the environment or the repository
`.config` file, then run:

```bash
us-census-trade-data update-latest
us-census-trade-data backfill --start-month 2010-01
```

The implementation never persists the key in raw snapshot URLs. It stores the
API response under `data/raw/us_census_trade/` and the normalized Parquet file
under `data/normalized/us_census_trade/`.

The national collector supports the comparison set Korea `5800`, Taiwan
`5830`, Japan `5880` and China `5700`:

```bash
us-census-trade-data \
  --partner-country-codes 5800,5830,5880,5700 \
  backfill --start-month 2010-01
```

The port-level collector uses a separate grain and file so port rows do not
duplicate national totals:

```bash
us-census-trade-data \
  --partner-country-codes 5800,5830,5880,5700 \
  port-backfill --start-month 2010-01
```

For the current HS 854232 response, Census returns quantity values as `0` with
unit `-` for the full available history. The parser normalizes that sentinel to
missing rather than treating it as a real measured zero. The current usable
signal is therefore import value plus the transport-specific shipping weights.
The Port-HS data reconciled exactly to the national general-import value for
all 792 country-month groups in the current backfill; port history is still
kept as a separate dataset because its grain is different. Census updates now
fail when a requested month/partner pair returns no usable rows.

MOPS JSON responses expose the retrieval timestamp, not the original historical
filing date. The normalized `filing_date` is therefore blank for JSON
snapshots; use `scraped_at` as retrieval metadata and do not treat it as a
point-in-time publication date. `mom_pct` is derived from adjacent monthly
revenue when MOPS does not publish it, and is marked with
`mom_pct_is_derived`.

As of 2026-08-25, the MOPS normalized dataset has been refreshed through
2026-07 for all 11 tracked companies. Census national and Port-HS datasets
remain through 2026-06: a 2026-07 retry returned an empty response for Korea
(`5800`), so the pipeline retained the previous normalized data and kept the
empty raw response plus manifest for audit.

A 2026-09-02 retry of Census 2026-07 still returned no rows for all four
partner countries; Census monthly trade typically lands roughly six weeks
after month end, so 2026-07 is expected in early September and the fetch
should be retried then.

The official-vs-backup `comparison_gap_pct` column was repaired on
2026-09-02. It had compared Korea's thousands-USD figures directly against
Comtrade dollars (and HKD/JPY thousands against dollars with no FX step),
reporting 99,900% / 12,700% / 674% gaps for rows that agree. Gaps are now
computed in USD after unit normalization; Korea's 50 comparable months show a
maximum gap of 0.00001%, and cross-currency Hong Kong/Japan rows carry no gap
until a monthly FX join is added.

## Deferred sources

KCS and KOSIS remain optional adapters from the earlier prototype, but they are
not required by the active pipeline because registration depends on Korean
identity verification. KRX positioning data is also not part of the current
no-registration path because the Data Marketplace endpoint is session-gated.
