# Research Control Tower Focus Universe and Theme Plan

**Date:** 2026-08-15
**Status:** Stage 1 focus/archive and explicit theme implemented; Stage 1.5
focus and an archived-universe selector remain pending.
**Repository:** `alternative-data`
**Parent scope:** Research Control Tower + investment-thesis workflow

## Objective

Reduce the Research Control Tower's active research surface from the current
60+ ticker universe to a deliberately small, reviewable focus universe, while
preserving archived entities and historical registry lineage. At the same time,
replace the current mixed light/dark presentation with one explicit app theme:
light by default, with an in-app dark-mode choice.

This slice is about research focus and usability. It does not add PIT signal
research, portfolio construction, systematic backtesting or automated trading;
those remain in `quantamental-lab`.

## Target universe

### Stage 1 — China Internet / Big Tech

Create the operational focus basket:

```text
RESEARCH_STAGE_1_CHINA_INTERNET
```

Members:

| Entity | Expected market identity | Research role |
|---|---|---|
| Alibaba | 9988.HK / BABA | Core listed company |
| Tencent | 0700.HK | Core listed company |
| ByteDance | Private; no listing | Competitor analysis / watch-only |
| Baidu | 9888.HK / BIDU | Core listed company |
| Kuaishou | 1024.HK | Core listed company |
| Bilibili | 9626.HK; ADR only if independently verified | Core listed company |

ByteDance must be represented as a real research entity without an invented
ticker. Its page may contain competitor, product, AI, advertising and industry
evidence, but it must not enter price, consensus or technical-data collection.

### Stage 1.5 — Hong Kong alternative-data ready

Create the operational focus basket:

```text
RESEARCH_STAGE_1_5_HK_ALT_DATA
```

Members:

| Entity | Expected HKEX identity | Existing research advantage |
|---|---|---|
| Cathay Pacific | 0293.HK | Airline/traffic and operating alternative data |
| MTR Corporation | 0066.HK | Existing Hong Kong transport data |
| Sun Hung Kai Properties | 0016.HK | Existing Hong Kong real-estate data |
| Midland Holdings | 1200.HK | Existing Hong Kong property/transaction data |

The Stage 1.5 slice should initially wire identity and source-availability
metadata. It must reuse the existing alternative-data pipelines rather than
create duplicate collectors.

## Archive contract

“Archive” means remove an entity from the default research universe, not delete
it from the registry or erase historical evidence.

### Registry semantics

- Keep the existing `active_from` / `active_to` interval history.
- Add `entity_type` to the entity contract with at least `public` and `private`.
- Set the five new entities to `public` except ByteDance, which is `private`.
- Use `active_status=archived` for current entities outside the ten-member focus
  set, with an archive effective date of `2026-08-15`.
- Set archived listings to `listing_status=archived` and close their current
  interval at the same effective date.
- Close current memberships for archived entities at the archive date, while
  retaining the rows for historical replay and audit.
- Do not change `collection_eligible` to mean research focus. Eligibility still
  describes whether a mapped listing can be collected; focus filtering happens
  in the Control Tower universe selection and collection entry points.
- Preserve the existing AI Bottlenecks, value, growth and Hong Kong baskets as
  legacy/recoverable research universes. They are not deleted merely because
  they are not the current focus.

### Default visibility

- Default dashboard focus: Stage 1.
- A single focus control switches between Stage 1, Stage 1.5 and both stages.
- Archived/legacy universes are hidden by default.
- A deliberate `Show archived` choice exposes archived entities and legacy
  baskets without making them part of the default daily review.
- Unknown or private entities must never be converted into fake listings to
  satisfy a UI selector.

## UI/theme design

### Root cause to remove

The current app has a light Streamlit canvas but a custom `prefers-color-scheme`
override that can turn the flight deck and custom cards dark when the browser or
OS is dark. `.streamlit/config.toml` also contains unsupported nested theme
sections. These two independent theme systems create the black/white seam seen
in the hosted screenshot.

### Explicit theme model

- Keep the Streamlit base theme light.
- Remove unsupported `[theme.light]` and `[theme.dark]` blocks from
  `.streamlit/config.toml`.
- Remove the OS-level `@media (prefers-color-scheme: dark)` override from the
  custom CSS.
- Add `ct_theme` to session state with `light` as the default.
- Add a visible sidebar theme choice: `Light` / `Dark`.
- Inject one token palette per rerun and scope all custom surfaces to that
  palette. No component may hard-code a dark background in the light palette.
- The light palette must cover the page canvas, flight deck slots, panels,
  event rows, alerts, borders, badges and muted text.
- The dark palette must provide its own contrast-safe text and status colors;
  it must not be derived from the user's OS setting.

### Focus-first information hierarchy

Move the active universe choice out of the collapsed general filter area and
make it a top-level control visible on every page:

```text
Focus universe
[Stage 1 · China Internet] [Stage 1.5 · HK Alt Data] [Both] [Archived]
```

The flight deck should report the selected focus label and covered entity count,
not default to “All baskets” when the app is intentionally scoped to ten names.
The Company selector should show display name, listing and private/listed state
without exposing internal entity IDs as the primary label.

## Implementation tasks

### Task 1 — Extend and validate the focused registry

- [ ] Add `entity_type` to the entity CSV contract, artifact schema and registry
  validation.
- [ ] Permit an active `private` entity without a listing, while retaining the
  existing requirement that public active entities resolve to a primary listing.
- [ ] Add the two focus baskets and the five missing entities, plus verified
  listings where applicable, required by the target universe.
- [ ] Verify Bilibili, Cathay, SHKP and Midland identifiers against the existing
  financial-data crosswalk before marking them collection-eligible.
- [ ] Archive every existing entity outside the ten-member focus set using the
  archive contract; retain all rows and historical dates.
- [ ] Close archived memberships without deleting their lineage.
- [ ] Keep ByteDance watch-only and non-collectible.

Likely files:

```text
config/research_control_tower/entities.csv
config/research_control_tower/listings.csv
config/research_control_tower/baskets.csv
config/research_control_tower/basket_memberships.csv
src/research_control_tower/contracts.py
src/research_control_tower/registries.py
src/research_control_tower/build.py
src/research_control_tower/quote_collector.py
scripts/research_control_tower_quote_collector.py
```

### Task 2 — Make focus and archive state visible in the read model

- [ ] Preserve the new entity/listing fields in Parquet output and repository
  loading.
- [ ] Add a typed focus selection model rather than passing ad-hoc ticker lists
  between pages.
- [ ] Filter default Company/Today/Timeline/AI views to the selected focus.
- [ ] Add an explicit archived view; do not silently mix archived rows into
  active counts or catalyst breadth.
- [ ] Make private entities render a clear “private / no listing” state.

Likely files:

```text
apps/research-control-tower/control_tower/config.py
apps/research-control-tower/control_tower/models.py
apps/research-control-tower/control_tower/repository.py
apps/research-control-tower/control_tower/filters.py
apps/research-control-tower/control_tower/pages/company.py
apps/research-control-tower/control_tower/components/flight_deck.py
apps/research-control-tower/app.py
```

### Task 3 — Replace the mixed theme with explicit light/dark tokens

- [ ] Clean `.streamlit/config.toml` to one valid light base theme.
- [ ] Remove OS/browser media-query theme overrides.
- [ ] Add session-state theme control with light default.
- [ ] Refactor CSS tokens so flight deck, panels, alerts and native page canvas
  do not form separate visual islands.
- [ ] Check both themes at desktop and mobile widths.

Likely files:

```text
.streamlit/config.toml
apps/research-control-tower/app.py
apps/research-control-tower/control_tower/components/__init__.py
```

### Task 4 — Add regression tests and rendered QA

- [ ] Registry tests cover the two focus baskets, all ten target entities,
  private ByteDance, archived rows and valid interval closure.
- [ ] Repository/build tests cover the new `entity_type` and archive fields.
- [ ] AppTest confirms Stage 1 is the default focus, Stage 1.5 shows exactly
  four companies, archived rows are hidden by default and recoverable through
  the archive choice.
- [ ] AppTest confirms light is the default and switching to dark does not
  raise an exception or expose raw IDs.
- [ ] Browser QA confirms no dark custom card appears on the light canvas and
  no light card appears on the dark canvas.
- [ ] Run the existing focused Control Tower suite and the privacy/no-network
  tests.

### Task 5 — Rebuild the publication and review the hosted result

- [ ] Build a fresh manifest after the archive/focus changes.
- [ ] Confirm the default bundle is explicitly scoped to Stage 1 and reports
  unavailable data instead of fabricating consensus/price coverage.
- [ ] Run the privacy and source-health checks on the new bundle.
- [ ] Review the Streamlit Cloud deployment after `main` rebuilds.

## Acceptance criteria

The plan is complete when:

1. The default app surfaces six Stage 1 entities, not the full 60+ universe.
2. Stage 1.5 surfaces exactly Cathay, MTR, SHKP and Midland.
3. ByteDance is visible for competitor research without a fake ticker or
   market-data row.
4. All other current entities remain recoverable as archived records.
5. Archived entities do not inflate active universe counts, catalysts or source
   coverage.
6. Light mode is the default and has one consistent light surface palette.
7. Dark mode is an explicit user choice and has one consistent dark surface
   palette.
8. Existing events, source-health caveats and unavailable consensus/price
   states remain evidence-first and are not silently upgraded.
9. The app remains read-only during navigation and does not add a collector or
   a quantamental-lab runtime dependency.

## Explicit non-goals

- No deletion of legacy entities, listings or historical evidence.
- No automatic ranking of the ten names into buy/sell recommendations.
- No PIT signal backtesting, portfolio construction, execution or systematic
  trading logic.
- No new paid data-provider integration in this slice.
- No broad expansion of the universe until the ten-name workflow is usable.

## Review gate

This document is the implementation plan only. Before code changes begin,
review the archive semantics, the private ByteDance model and the exact ten-name
focus scope. Any change to those decisions should be made here first rather
than encoded as an untracked UI shortcut.
