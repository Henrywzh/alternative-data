# HK Local Consumer Historical Data Design

**Approved scope:** preserve all history that an authoritative source exposes;
keep the published dashboard's default views compact.

## Objective

Replace misleading one-period presentation where a historical source is
available, without conflating source history with locally accumulated snapshots.

## Data contracts

| Family | Durable data layer | Dashboard default |
|---|---|---|
| HKO severe weather | Event-level warnings and derived daily/monthly disruption hours for all source history | daily event-hours over the latest 36 months; event log; monthly summary retained |
| Consumer Council oil prices | Full available daily net-price history by company and fuel type | latest 12 months; latest 7-day movement |
| Consumer Council discounts | Historical weekly discount rows only after source parsing is verified | latest comparison/table, with a separately labelled availability caveat |
| AFCD wholesale prices | Append-only local daily observations; no fabricated upstream history | latest 90 days once accumulated; no WoW before seven complete daily observations |
| Consumer Council complaints | Every source period/category row | all available periods; latest-period ranking remains secondary |
| Immigration control points | Daily control-point/direction/passenger-type observations for all CSV history | compact recent trend/selected checkpoint view plus latest detail table |
| Consumer watchlist valuation | All daily observations returned by the source, stored append-only | latest 30 trading days and 1-week movement |
| Retail categories | Full monthly category history | latest-month YoY comparison; MoM in detail table |
| Restaurant categories | Full quarterly category history | latest-quarter YoY comparison; QoQ in detail table |

## Metric and presentation rules

- Oil history from the Consumer Council trend endpoint is labelled as net price
  after walk-in discounts and excluding fuel duty. It is not silently combined
  with the homepage's duty-inclusive price.
- HKO warning intervals that cross midnight are split across days before daily
  and monthly aggregation.
- Retail YoY is the primary category comparison because monthly seasonality is
  material; MoM remains a secondary table field.
- Restaurant data is quarterly: use YoY and QoQ, never MoM.
- The 2026 Consumer Council complaint period lacks a stated month range in the
  source response. It is not treated as comparable with the 2024/2025 full-year
  periods for a percentage YoY calculation.
- AFCD category averages are a simple category mean, not a fixed-basket price
  index; composition caveats remain visible.

## Verification

For each source: rebuild the local-consumer artifact, check date range and row
counts in the generated JSON, run focused tests, build/package the dashboard,
and inspect English and Chinese pages in a real browser.
