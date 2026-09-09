# Asia Markets Streamlit Pages Implementation Plan

## Goal

Replace the central session-state page dispatcher with hidden Streamlit
navigation and enforce per-page artifact loading without changing sector
content.

## Tasks

1. Add regression tests for page-registry uniqueness and page-specific
   artifact-loading scope.
2. Extract canonical/localized artifact loading into `am/artifacts.py`.
3. Extract the custom bilingual sidebar into `am/sidebar.py`.
4. Add lazy page callables and the single page registry in
   `am/page_registry.py`.
5. Reduce `app.py` to bootstrap, hidden navigation, sidebar and selected-page
   execution.
6. Move cross-sector helpers and labels out of sector-owned modules where the
   move is calculation-preserving.
7. Update AppTest coverage to use the page registry and exercise all pages,
   both languages and all Market regions.
8. Run compilation, focused tests, the full Streamlit contract suite and a
   local browser smoke check.
