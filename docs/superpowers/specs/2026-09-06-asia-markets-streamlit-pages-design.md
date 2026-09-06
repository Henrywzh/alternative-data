# Asia Markets Streamlit Pages and Lazy Loading Design

## Objective

Convert the Asia Markets Streamlit terminal from one session-state router that
loads every sector artifact on every rerun into a true multipage application.
The refactor must preserve the current custom full-width sidebar, bilingual
presentation and sector visuals while reducing unnecessary imports and JSON
parsing during ordinary navigation.

This is a Streamlit-only architecture change. It does not alter source
pipelines, artifact builders, Cloudflare publishing, signal definitions or
dashboard content.

## Current problem

The current `app.py` is short after the first module split, but it still:

- imports every sector renderer at startup;
- loads the English and localized artifact for every sector before dispatch;
- parses roughly 30 MB of artifact JSON even when the reader opens one sector;
- represents navigation as a session-state string rather than a Streamlit page;
- makes page-level test coverage depend on parsing the central dispatch.

The existing `am/*.py` modules are reusable renderers, not independently
loadable pages. The refactor should retain them and add a page/application
layer around them.

## Chosen architecture

Use `st.Page` and `st.navigation(..., position="hidden")`. Streamlit owns the
active page and URL, while the application continues to render its existing
custom sidebar. Standard Streamlit sidebar navigation stays hidden.

`app.py` becomes a bootstrap entry point responsible only for:

1. repository import paths;
2. `st.set_page_config`;
3. shared styling;
4. page registry construction;
5. custom sidebar rendering;
6. running the selected page.

Each `st.Page` uses a callable that imports its renderer inside the callable.
This avoids importing inactive sector modules during startup. Page callables
read language and history-window state established by the shared sidebar.

The current full-width navigation buttons remain. A button switches to the
corresponding registered `st.Page`, so the visual design does not regress to
Streamlit's small default page controls.

## Page registry

The registry contains stable keys and URL paths for:

- Overview;
- Index & ETF Monitor;
- Global Market Regime;
- Hong Kong Labour Market;
- Hong Kong Population & Migration;
- Hong Kong Real Estate;
- Hong Kong Transport & Aviation;
- Hong Kong Commercial Aerospace;
- Hong Kong Stablecoin & Crypto;
- Data Explorer;
- Source Health.

Page labels are bilingual in the custom sidebar. URL paths and internal keys
remain language-neutral so changing language does not reset the active page.

The registry is the single source of truth for page ordering, sidebar
grouping, callable ownership and test discovery.

## Module boundaries

The refactor introduces three small application-layer modules:

- `am/page_registry.py`: page metadata, URL paths and lazy page callables;
- `am/artifacts.py`: canonical and localized artifact loading policies;
- `am/sidebar.py`: language, history-window and full-width navigation UI.

Existing sector modules remain presentation renderers:

- `am/overview.py`;
- `am/market_page.py` plus market helpers;
- `am/regime.py` plus evidence helpers;
- `am/labour.py`;
- `am/population.py`;
- `am/realestate.py`;
- `am/transport.py`;
- `am/aerospace.py`;
- `am/crypto.py`;
- `am/explorer.py`.

Generic period and daily-signal helpers currently imported by Crypto from
Transport move to a shared helper module. Regime label constants currently
owned by Overview move to shared configuration. These moves remove
cross-sector ownership without changing calculations.

## Artifact loading policy

English artifacts remain the canonical data contract. Localized artifacts are
presentation-only.

Ordinary sector pages load exactly one sector:

```text
selected page
    -> canonical English artifact
    -> optional localized artifact
    -> sector renderer
```

If the canonical artifact is missing, malformed or has an invalid dataset
shape, that sector receives an unavailable artifact and a visible warning.

If only the localized artifact fails, the page retains current English data
and uses the English manifest as its label fallback. A presentation failure
must never turn valid data into an unavailable sector.

The three aggregate pages intentionally load more:

- Overview loads all connected sectors because it summarizes all of them.
- Data Explorer loads all connected sectors because its picker spans them.
- Source Health loads all connected sectors because it reports total coverage.

All loading continues to use file modification time as part of the Streamlit
cache key so a running app can see rebuilt artifacts without a server restart.

## Rendering and state

Language and default history window stay in `st.session_state` and apply
across page changes. Page-specific controls retain their existing stable keys.

The Market page continues to render only the selected geographic region. The
US remote-sector artifact is loaded only when the US region is active.

Changing page, language or history window must not trigger network access
other than the existing US-sector loader on the active US page. All other
sector pages remain local-artifact readers.

## Error handling

The loader validates:

- artifact root is an object;
- manifest and snapshot are objects;
- snapshot datasets is an object;
- every dataset value is an array of row objects.

Renderers continue to guard the required columns for optional datasets.
Malformed optional datasets hide or degrade their own panel; they do not crash
the rest of the page.

Warnings are scoped:

- sector page: only that sector's load warning;
- overview/data/health: aggregated warnings for affected sectors;
- localized failure: explicit label fallback warning without a data-loss
  message.

## Compatibility

The deployment entry point remains:

```text
apps/asia-markets-streamlit/app.py
```

Streamlit Cloud settings and requirements do not change. The supported
Streamlit range already includes `st.Page`, `st.navigation` and
`st.switch_page`.

Tests and internal callers should import helpers from their owning modules
rather than relying on `app.py` to re-export every private function. During
the migration, a small explicit compatibility surface may remain in
`app.py`, but broad wildcard-style re-export behavior is removed.

## Testing

Required automated checks:

- every registered page renders in English and Chinese;
- every Market inner region renders in English and Chinese;
- registry keys, URL paths and sidebar entries are unique;
- ordinary sector pages load only their own canonical/localized artifacts;
- Overview, Data Explorer and Source Health load all sectors;
- a malformed localized artifact retains canonical English data;
- a malformed canonical artifact degrades only its own sector;
- malformed optional dataset columns do not crash Crypto, Regime or Explorer;
- Python compilation and undefined/duplicate import checks pass.

AppTest page discovery reads the page registry instead of parsing an
`if/elif` dispatch tree. A loader spy verifies per-page artifact calls, making
lazy loading an enforced contract rather than an assumed performance benefit.

Acceptance also requires a real local-browser check of:

- custom full-width sidebar navigation;
- language persistence across page changes;
- direct URL navigation;
- Overview;
- US Market region;
- one Hong Kong sector;
- Data Explorer;
- Source Health.

## Delivery sequence

1. Extract artifact loading, sidebar and shared cross-sector helpers.
2. Add the page registry and lazy page callables.
3. Replace the session-state dispatch in `app.py` with hidden
   `st.navigation`.
4. Update tests to discover and exercise the registry.
5. Run the full Streamlit contract suite and browser smoke checks.
6. Remove compatibility re-exports proven unused by repository search.

The content and visuals of sector pages remain unchanged throughout this
sequence, allowing navigation and loading regressions to be isolated from
product changes.
