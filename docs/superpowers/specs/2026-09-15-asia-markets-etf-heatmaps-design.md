# Asia Markets ETF Heat Maps and Flow Views

**Date:** 2026-09-15
**Status:** Approved design
**Product surface:** Asia Markets Streamlit research terminal

## 1. Purpose

Add a source-backed Heat Maps page to the Asia Markets Streamlit terminal,
inspired by the information hierarchy in Shepherd Capital Markets without
copying unsupported data or treating estimates as official fund flows.

The page should answer three distinct questions:

1. Which markets, exposures and ETF groups are leading or lagging?
2. Where do validated ETF share changes imply creations or redemptions?
3. For one ETF, how do price, moving averages and estimated fund activity
   evolve on the same timeline?

The existing ETF Monitor remains the place for exposure selection and wrapper
comparison. The existing Market Regime page remains the place for Equity,
Fixed Income and Macro conditions. Its commodity-return table and inflation
release matrix already cover the useful parts of the reference Macro screen
and must not be duplicated.

## 2. Product and publishing boundary

This feature is Streamlit-only:

```text
market_monitor sources and samplers
  -> immutable normalized observations
  -> derived heat-map and flow views
  -> market-monitor artifact
  -> Asia Markets Streamlit
```

It does not add a Cloudflare sector, portable HTML page or public-dashboard
navigation entry. The artifact contract should remain frontend-agnostic so a
future custom research terminal can reuse the data without reproducing the
pipeline.

## 3. Navigation and page structure

Add `Heat Maps / 热力图` to the existing Markets sidebar group. The page has
three subtabs:

### 3.1 Market Performance / 市场表现

A treemap compares current performance across broad equity, sectors,
international markets, commodities and fixed income.

- Rectangle size uses a verified fund-size field when available.
- A clearly named size proxy may be used when its basis is present in the
  artifact.
- If neither is available, use equal area rather than inventing size.
- Color can switch between 1D, 1W, 1M, 3M, YTD and 1Y total return.
- Tooltip includes ticker, bilingual name, category, latest price, size basis,
  selected-period return and all available return windows.
- Missing returns remain missing and use a neutral treatment; they are never
  rendered as zero.

The default view should show the broad cross-market layer. Category controls
allow focused inspection without hiding the all-market comparison.

### 3.2 ETF Fund Flow / ETF资金流

A second treemap displays only observations whose flow methodology is valid.

- Rectangle size uses NAV-backed estimated assets where available.
- Color uses estimated net creation/redemption over 1D, 1W, 1M, 3M or YTD.
- Grouping follows broad equity, sector, international, commodity and fixed
  income.
- Tooltip discloses the share basis, valuation basis, calculation, observation
  dates, coverage count and selected-window flow.
- A fund with no valid flow is marked unavailable, not zero-flow.

China-listed wrappers use the existing official SSE/SZSE share-count layer.
Estimated CNY flow remains:

```text
change in exchange-published shares × same-day published NAV
```

Only rows already classified as validated may enter monetary flow aggregates.
Shares-only and insufficient-history rows remain visible as coverage states
but do not contribute an estimated amount.

US ETF flows are not backfilled from price or volume. They begin only after a
local post-close sampler records co-timed price and fund-size observations.
The resulting share count is a proxy:

```text
estimated shares = sampled market capitalization / same-moment price
estimated flow = change in estimated shares × sampled price
```

This lane is labelled `market_cap_proxy`, not official flow. It is shown only
after at least two valid observations for a fund. Every view states the first
sample date and usable observation count.

### 3.3 ETF Detail / ETF明细

This tab provides a ticker selector, category filter and observation window.
It renders two vertically aligned charts with a shared date range:

1. adjusted close with SMA20, SMA50 and SMA200;
2. daily estimated fund flow, with positive and negative bars.

The detail panel also shows the latest price, selected-window return, latest
validated/proxy flow, coverage start and data basis. The price chart remains
available when flow is absent; the flow panel explains why it is unavailable
or still accumulating.

## 4. Data contracts

### 4.1 Daily flow observations

Create or extend a normalized daily observation contract with these fields:

- `observation_date`
- `fund_id`
- `ticker`
- `fund_name`
- `exposure_id`
- `category`
- `venue`
- `currency`
- `shares_outstanding`
- `shares_basis`: `exchange_published` or `market_cap_proxy`
- `price`
- `nav`
- `size_value`
- `size_basis`
- `shares_change`
- `estimated_flow`
- `flow_status`
- `source`
- `retrieved_at`
- `run_id`

Existing China ETF activity can be adapted additively. Do not rename or remove
the current artifact fields until the existing ETF Monitor has migrated.

### 4.2 Derived heat-map snapshot

Build a derived dataset at fund/date grain containing:

- return values for 1D, 1W, 1M, 3M, YTD and 1Y;
- flow aggregates for the same supported windows;
- size and size basis;
- first and latest valid flow dates;
- valid-flow observation count;
- freshness and quality status;
- source/run lineage.

Calendar windows must use the latest valid trading observation on or before
the comparison date. Returns are compounded price returns, not sums of daily
returns. Flow windows sum only valid daily estimated-flow rows.

### 4.3 Run consistency

The page must consume one coherent artifact run. A newer flow sample must not
be silently combined with an older price dataset and presented as a fresh
complete run. Optional US flow coverage may be unavailable without blocking
price and return views, but the artifact must preserve that degraded status.

## 5. US post-close sampler

The US sampler is local and scheduled once after the US cash-market close. It:

1. loads the explicit ETF universe;
2. fetches same-session price and fund-size observations as close together as
   practical;
3. rejects non-positive values, missing timestamps and stale sessions;
4. writes an immutable observation with source and retrieval timestamps;
5. derives estimated shares only when both inputs pass validation;
6. calculates flow only when a valid prior observation exists.

Provider failure is non-destructive. It does not overwrite the last valid
history, fabricate a zero, or block the rest of the market-monitor artifact.
No email alert is enabled from this new proxy history in V1.

## 6. Presentation rules

- Use the existing Asia Markets light theme and bilingual vocabulary rather
  than reproducing the reference dashboard's black-and-orange styling.
- Green and red encode positive and negative returns or flows; neutral and
  missing are visually distinct.
- Every treemap title states both size and color encodings.
- Estimated values always include `Estimated / 估算` in titles or tooltips.
- Tooltips show human-readable dates, currency and units.
- AUM proxy, market-cap proxy and verified NAV assets are never all labelled
  simply `AUM`.
- Controls update every view within their tab; default selections show all
  useful categories.

## 7. Failure and empty-state behavior

- Partial provider responses disclose missing funds and coverage ratios.
- A fund with one share observation reports `needs next observation`.
- Missing same-day NAV remains shares-only for the China lane.
- Missing co-timed price or size remains unavailable for the US proxy lane.
- Stale data cannot receive fresh positive/negative status colors.
- Empty data yields an explanatory message and source-health detail, not an
  empty Plotly frame or a zero-valued treemap.

## 8. Testing and acceptance

### Data tests

- exact return-window calculations, including YTD;
- valid and invalid flow-window aggregation;
- missing values stay null;
- equal-area fallback when no size is available;
- source and run consistency;
- no US flow from a single observation;
- no China monetary flow without same-day published NAV;
- partial provider and stale-session handling.

### Streamlit tests

- bilingual page and control labels;
- all three subtabs render from a complete artifact;
- price detail renders when flow is unavailable;
- treemap controls change color windows without changing size semantics;
- category filters preserve the correct population;
- empty/degraded states do not raise exceptions.

### Rendered verification

- desktop and 390px mobile widths have no page-level overflow;
- treemap labels and tooltips remain readable;
- positive, negative, neutral and missing states are distinguishable;
- ETF detail charts align on the same date range;
- browser console has no errors or warnings.

## 9. Delivery stages

### V1

- add the Heat Maps page and navigation;
- build the source-backed return treemap;
- build the validated China-listed ETF flow treemap;
- add ETF price/SMA and flow detail views;
- add the optional US post-close observation contract and local sampler;
- show US price/technical detail immediately and flow only as history
  accumulates.

### Later

- alert rules after a sufficient proxy history exists;
- verified US fund-assets or official share-history source;
- historical flow z-scores and persistence signals;
- custom non-Streamlit frontend using the same artifact contract.

These later items must not delay V1 or be simulated with unsupported data.
