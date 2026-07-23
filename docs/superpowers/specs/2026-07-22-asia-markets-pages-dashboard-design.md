# Asia Markets Pages Dashboard Design

## Objective

Publish a source-backed Asia Markets dashboard on Cloudflare Pages, beginning with Hong Kong real estate, and generate a Gmail-friendly self-contained HTML attachment from the exact same dashboard artifact.

## Visual thesis

An editorial market-monitoring desk: quiet paper-like surfaces, dense ink typography, restrained vermilion accents, and charts that privilege provenance and freshness over decoration.

## Content plan

1. The hub opens on sector availability, freshness, and the next useful action.
2. The Hong Kong real-estate dashboard opens on current price and rent measures, then historical movement, then source coverage and caveats.
3. The data-status page exposes release time, source health, and artifact identity.
4. The hub provides a dated offline HTML download suitable for attaching to email.

## Interaction thesis

- Short entrance transitions establish hierarchy without delaying the working surface.
- Sector rows reveal their action and coverage details on hover/focus.
- The dashboard reader provides chart inspection, source details, table sorting, and responsive layouts in both hosted and local-file environments.

## Architecture

The project lives at `apps/asia-markets-dashboard` and produces a static `dist` directory for Cloudflare Pages.

- Astro owns the multi-sector hub and the data-status page.
- A Python exporter fetches and validates first-party HK real-estate measures, then writes one canonical dashboard artifact JSON.
- The Data Analytics portable-artifact builder packages that artifact as a self-contained HTML dashboard.
- The same HTML bytes are copied to the Pages sector route and to a dated attachment filename. This guarantees hosted/offline rendering parity.
- No Pages Functions, database, authentication, or runtime data fetches are used in the first release.

## Initial data scope

The release includes only sources that can be validated at build time:

- Centaline CCL weekly index.
- Midland MHPI weekly index.
- Midland confidence index as a supporting sentiment series.
- Rating and Valuation Department residential price and rental indices.

Agency transactions, 28Hse EPI/ERI, SRPE project content, Land Registry facts, and Buildings Department facts appear as explicit planned or catalog-only coverage rows until their content pipelines are validated. No placeholder measures are generated.

## Data contract

The canonical artifact contains:

- a generated timestamp and deterministic snapshot identifier;
- bounded reviewed time-series datasets;
- one-row KPI datasets with latest, prior-period, and year-over-year comparisons;
- source-health and coverage datasets;
- canonical public source URLs, metric definitions, freshness, and caveats;
- no credentials, raw response bodies, local paths, or address-level records.

The build fails when a core series is empty, duplicated, stale beyond its source-specific SLA, contains invalid dates or values, or cannot be reconciled with its KPI row.

## Pages and attachment parity

The Pages route `/sectors/hk-real-estate/` and the downloadable file `hk-real-estate-dashboard-YYYY-MM-DD.html` are byte-identical. The attachment:

- embeds all data, CSS, JavaScript, charts, and icons;
- performs no network requests to render;
- works when opened from `file://` in a modern desktop browser;
- remains readable through a semantic fallback when JavaScript is unavailable;
- displays its data timestamp and snapshot identity prominently.

Gmail preview is not an execution environment. Recipients download the attachment and open it in Chrome, Safari, or Edge.

## Public-site boundary

The Pages site is intentionally unauthenticated. The release includes `robots.txt` and `X-Robots-Tag: noindex` but treats those as discovery controls, not access control. Only publishable aggregate data and public-source metadata are included.

## Error behavior

- Artifact generation is atomic: candidate files are validated before replacing the current output.
- A failed refresh does not produce a new release.
- The previous Pages deployment remains available through Cloudflare rollback history.
- Source failures are visible in build output and are never converted into zero values.

## Verification

Before deployment:

- Python exporter tests validate dates, changes, rebasing, provenance, and sensitive-field rejection.
- The portable artifact delivery verifier checks payload equality, desktop and narrow layouts, browser errors, external requests, and source interaction.
- The hosted route and attachment file hashes must match.
- Astro must build without warnings or broken links.
- A local Pages server is checked in a real browser at desktop and mobile widths.
- The attachment is opened from `file://` with network disabled and must render the expected KPIs and charts.
