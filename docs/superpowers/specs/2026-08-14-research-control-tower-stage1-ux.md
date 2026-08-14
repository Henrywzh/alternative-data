# Research Control Tower Stage 1 UX Scope

**Date:** 2026-08-14
**Status:** Approved for implementation
**Parent design:** `2026-08-13-research-control-tower-design.md`

## Product boundary

Stage 1 is a trustworthy research workbench, not a market-data terminal. The
default experience must make the current evidence state, upcoming catalysts
and data gaps easy to scan. It must not show placeholder prices, earnings,
consensus or technical values when those read marts are unavailable.

The existing five-page contract remains stable:

- **Today:** the prioritized delta and current data state.
- **Unified Timeline:** the one chronological catalyst ledger.
- **AI Bottlenecks:** the basket/layer workbench for the first cross-market
  research basket.
- **Company:** a filtered company drill-down with readable listing,
  consensus, filing and event summaries.
- **Source Health:** lineage and freshness exceptions.

## Stage 1 interaction rules

1. Superseded event versions are hidden from every catalyst presentation;
   lineage remains available in detail views.
2. A bundle whose newest source observation predates the previous build is
   labelled **Data bundle is stale**. The app shows a recent-record fallback,
   never a misleading “no changes” message.
3. Source Health separates status from freshness:
   `available`, `healthy`, `freshness unclassified`, `stale`,
   `unavailable/degraded`, and explicit errors/gaps are distinct buckets.
4. Navigation and filters persist in the same Streamlit interaction. The
   sidebar starts collapsed so a narrow viewport can see the research canvas.
5. The default workbench tables show ticker/company/region/tier/layer,
   evidence status, last evidence and consensus status. Stable ids, hashes,
   PIT fields and raw paths belong in expandable lineage details.
6. “Next catalyst” appears once in the flight deck. The timeline remains
   chronological and does not repeat the same priority card.
7. Today exposes a compact data-coverage matrix. It distinguishes record
   presence from entity/listing linkage and labels evidence coverage as
   evidence, not as an alpha or trading signal.

## Data-contract follow-up

The next data stage adds optional, listing-keyed marts with source and
point-in-time metadata:

- daily price/bars and minimal returns;
- earnings actuals by fiscal period and release time;
- refreshed provider-specific consensus snapshots/revisions;
- a compact alternative-data signal snapshot.

RSI14, MA20/MA50 and a volume proxy are derived during the deterministic build
from the price mart. Full options/order-book/CTA/hedge-fund microstructure is
out of scope for this Stage 1 UI pass.

## Acceptance checks

- A superseded catalyst cannot be selected as the next catalyst.
- A stale bundle is explicit and has a recent-event fallback.
- Source headline counts reconcile without counting cadence-unclassified rows
  as errors.
- Company filters affect the company selector and event/content scope.
- The default AI workbench contains no internal hash/path columns in its main
  tables and does not imply that missing market data exists.
- The Today coverage matrix does not count empty JSON relation arrays as linked
  evidence, and unavailable price/earnings marts are shown as unavailable.
- Desktop and narrow viewport smoke checks show no sidebar obstruction or
  repeated next-catalyst panel.
