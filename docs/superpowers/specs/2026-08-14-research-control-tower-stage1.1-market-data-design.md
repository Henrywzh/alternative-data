# Research Control Tower Stage 1.1A Market Data Design

**Date:** 2026-08-14
**Status:** Approved for implementation by user
**Parent design:** `2026-08-14-research-control-tower-stage1-ux.md`

## Goal

Make the Company page useful for price-aware research without pretending that
the dashboard is a tick terminal. Stage 1.1A adds two optional, listing-keyed
read marts:

- `market_bars.parquet` for historical daily bars and charting;
- `quote_snapshots.parquet` for the latest quote refreshed by an external
  collector or scheduled job.

The Streamlit app remains read-only. It does not call a market-data provider,
open a broker session, or write canonical data during navigation.

## Data boundary and identifiers

Both marts attach to the stable Control Tower `listing_id`. The producer may
carry a provider symbol and security identifier in provenance fields, but the
app must resolve display labels through the local listing registry. Rows that
cannot be mapped to a known listing are excluded from the published mart and
reported in source health; ticker text alone is not an identity key.

### Historical bars

The normalized contract contains:

```text
bar_id, listing_id, canonical_ticker, interval, timestamp_utc,
open, high, low, close, adj_close, volume,
source_id, source_url, retrieved_at_utc, pit_class,
source_license_class, registry_version
```

The first supported interval is `1d`. The app may display the latest close
and a compact recent-price chart. RSI, moving averages, signals and
microstructure remain later stages.

### Latest quote snapshots

The normalized contract contains:

```text
quote_id, listing_id, canonical_ticker, provider_symbol,
quote_timestamp, retrieved_at_utc, last_price, bid, ask,
day_change_pct, volume, currency, market_status, latency_class,
source_id, source_url, pit_class, source_license_class,
registry_version
```

`quote_timestamp` is the provider's market timestamp; `retrieved_at_utc` is
when the collector observed it. The UI must show the freshness class, never
label a row `REAL-TIME` merely because it is the newest row in the file.

For the Streamlit refresh mode, a quote is considered `live/best-effort` only
when its declared latency class permits it and the quote timestamp is within
the configured short freshness window. Otherwise it is labelled `delayed`,
`stale` or `unavailable`. This is a display contract, not a guarantee of
exchange entitlement.

## Bundle compatibility and UI

The two marts are optional. Existing Stage 1 bundles without them remain
loadable and continue to show explicit unavailable coverage. New builds write
typed empty artifacts when an optional input is absent and record the reason in
Source Health/manifest metadata.

The Data Coverage matrix adds separate rows for historical price bars and
latest quote snapshots. The Company page shows:

- latest quote when a fresh snapshot exists, with timestamp and freshness
  label;
- latest historical close and a compact recent daily-price view when bars
  exist;
- clear unavailable/stale states with no placeholder numeric values.

No auto-refresh loop is implemented inside the app in this slice. A later
scheduled workflow may refresh `quote_snapshots.parquet`; the app's existing
manual rerun/refresh mechanism can then display the new snapshot.

## Quality and safety rules

- No network calls from Streamlit navigation.
- No raw broker/API credentials or commercial payloads in portable artifacts.
- Reject future quote timestamps relative to the build `as_of_utc`.
- Preserve provider and retrieval timestamps; do not overwrite source time with
  retrieval time.
- Deduplicate by listing, interval and market timestamp using an explicit
  source-priority rule.
- Do not use live snapshots as historical backtest observations unless a later
  stage persists and validates the required point-in-time history.

## Acceptance checks

- A legacy Stage 1 bundle loads without error and reports both price rows as
  unavailable.
- A fixture with mapped bars and a fresh quote shows values with the correct
  listing label and freshness class.
- An unmapped provider symbol is not displayed as a company price.
- A delayed/stale quote is visibly labelled and never presented as live.
- AppTest and local rendered QA show no raw security IDs, source paths or
  placeholder prices.
