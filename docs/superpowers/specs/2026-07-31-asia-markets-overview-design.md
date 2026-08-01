# Asia Markets Streamlit Overview Design

Date: 2026-07-31  
Status: Approved direction; implementation pending written-spec review  
Scope: `apps/asia-markets-streamlit` Overview page

## Context

The current private Asia Markets Streamlit Overview is only an entry page: four
KPI cards, two large sector cards and a scope note. It does not help the user
answer what is changing across the connected Hong Kong sectors.

The existing `dashboard/sections/overview.py` in the alternative-data app is a
useful design reference. Its structure is:

1. a compact KPI strip;
2. a small number of chart-led theme sections;
3. a latest-signals table; and
4. source dates and lineage below the main reading.

The public Cloudflare Asia Markets home page is a second reference: it is a
scalable sector index with health/status, latest dates and clear links into
detail pages. It is not a chart-heavy overview and should not be copied as a
second sector dashboard.

The private Overview therefore needs to combine the two patterns without
becoming a miniature copy of every sector page.

## Goals

- Make Overview useful before any navigation or filter interaction.
- Give each connected sector a compact, source-backed pulse.
- Keep the amount of content bounded as more sectors and markets are added.
- Reuse the alternative-data dashboard's visual hierarchy, spacing, palette and
  chart treatment without copying its AI-specific metrics.
- Preserve each metric's own observation date and cadence.
- Keep detailed chart exploration on the sector pages.

## Non-goals

- No new ingestion or external fetches during page navigation.
- No company explorer, financial-data integration or cross-market comparison in
  this change.
- No full sector chart collections, long tables or dataset browser on Overview.
- No trend chart built from a snapshot-only dataset.
- No forced common index across labour, population, transport or future sectors
  when their units or definitions are incompatible.

## User-facing layout

### 1. Header and overall status

The page keeps a short Asia Markets title and a one-sentence description. A
compact status row shows only overall context:

- number of connected sectors;
- number of source-backed measures or healthy source rows;
- latest available release date;
- a mixed-date/source-snapshot caveat where applicable.

The page must not present one package-wide date as if every metric were observed
on that date.

### 2. Sector pulse

This is the scalable core of Overview. Each active sector contributes one
compact row or card containing:

- sector name and market/country label;
- status and latest observation date;
- at most three curated headline metrics;
- one small trend sparkline only when a dated time series exists, with a
  selectable text label, latest value, plotted-observation count, cadence and
  plotted date range;
- a clear action to open the sector page.

The current V1 pulse entries will be labour market/talent policy and population
/ migration. For example, the labour entry may show unemployment rate,
vacancies and median monthly earnings; the population entry may show population,
daily resident net flow and mainland visitor net retention. The exact values are
read from the existing artifacts and retain their individual as-of dates.

The current large "Connected V1 sectors" cards and the "Current scope" card will
not remain as the primary Overview content. Sector navigation remains available
in the sidebar and through the compact pulse action.

### 3. Featured trends

Overview has a hard budget of at most two chart panels. The panels are explicit
featured slots, not one chart per sector. The slots are intentionally blank for
the current V1: raw low-frequency charts or a single un-derived series are not
good enough for the Overview's purpose. They will be enabled only after the
required higher-frequency data has been ingested and the derived signals have
been validated.

Each featured chart may expose the existing history-window/view controls when
they add value. Overview should not introduce a large dataset selector or a
second copy of the sector-page series controls. A chart title, source/cadence
note and observation coverage remain visible.

When a new sector is added, it enters Sector pulse by default. It does not add a
chart automatically. A sector can be promoted into a featured slot only through
an explicit configuration choice; promotion replaces a slot rather than
increasing the page's chart count.

### 4. Source-health summary

Overview ends with a compact source-health summary: healthy/partial/problem
counts, the newest/oldest relevant observation context, and a link/action to
the full Source Health page. The full per-source table remains on Source Health.

## Scaling contract for future sectors

Every proposed new sector or Overview-facing feature must state one of:

```text
Overview impact:
- None
- Add one compact sector pulse
- Replace one featured trend
```

The implementation should make this contract data-driven. A sector's Overview
metadata may define:

- `headline_metrics`: maximum three metric/card references;
- `sparkline`: optional dated series reference;
- `featured_chart`: optional chart reference for one of the two slots;
- a short caveat or cadence label.

The renderer must enforce the caps rather than relying on each future agent to
remember them. Planned or unavailable sectors must not create empty Overview
cards or fake charts. When multiple markets are eventually supported, pulse
entries can be grouped by market/country, while the fixed featured slots remain
curated.

## Data and interpretation rules

- Read the existing generated artifacts only; Overview must not fetch remotely
  or create a second source pipeline.
- Preserve source grain and use the shared history-window setting for temporal
  charts.
- Show an observation date or period next to every headline metric where the
  artifact provides one.
- Calculate changes only within the same series and cadence. Do not compare
  daily passenger flow with half-year population movement as one growth rate.
- Use snapshot data as a labelled latest reading only. Do not create a sparkline
  or MoM/YoY claim from one or two snapshots.
- Keep source names, caveats and mixed cadence visible without crowding the
  first viewport.

## Visual direction

Use the established alternative-data visual language as the reference:

- light neutral canvas and sidebar;
- blue active navigation and primary accent;
- compact white cards with restrained borders/shadows;
- strong page/section hierarchy;
- the existing Asia Markets chart palette;
- selectable chart titles and clean hover labels;
- equal-height paired chart cards where two featured panels are side by side.

This is a structural and visual reference, not a request to copy the old
dashboard's AI labels, metrics or page content.

## Implementation boundaries

The first implementation should be limited to:

- `apps/asia-markets-streamlit/app.py` and small adjacent Streamlit-only
  helpers/configuration;
- no changes to source fetchers or artifact builders;
- no changes to Cloudflare production packaging;
- no activation of future sectors.

If an artifact lacks a reliable metric needed by the pulse, the implementation
must use the strongest available metric or leave that slot out; it must not
invent a value or silently substitute a snapshot for a trend.

## Validation and acceptance criteria

The implementation is acceptable when:

1. Overview contains no large placeholder/scope card and gives a useful market
   reading before navigation.
2. Both current sectors appear in the compact pulse with real values, dates and
   links.
3. Zero or no more than two featured chart panels render, regardless of the
   number of configured sectors; the current V1 renders zero.
4. When featured charts are later enabled, they must render from validated
   higher-frequency/derived signals, show the configured history window and
   retain source/cadence context.
5. Source-health summary links to the existing Source Health page and does not
   duplicate the full table.
6. Labour, Population & Migration, Data Explorer and Source Health still pass
   Streamlit AppTest without app exceptions.
7. Browser QA confirms the first viewport, intentional blank Featured Trends
   state, sidebar navigation, desktop layout and a narrow/mobile layout without
   framework overlays or
   relevant console errors.
