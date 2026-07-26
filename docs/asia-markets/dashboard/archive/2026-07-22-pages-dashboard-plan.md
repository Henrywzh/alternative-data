# Asia Markets Pages Dashboard Implementation Plan

1. Add a source-backed HK real-estate artifact exporter with source-specific validation and deterministic snapshot metadata.
2. Add unit tests for KPI calculations, rebasing, artifact provenance, planned-source labeling, and sensitive-data rejection.
3. Add the Astro source site with a sector hub, data-status page, no-index headers, and publishable snapshot metadata; use a stable static pre-render release path when local Astro native bindings are unavailable.
4. Package the canonical artifact with the shared portable dashboard renderer and structural verifier.
5. Copy the same portable HTML to the hosted sector route and the dated Gmail attachment path; verify byte equality.
6. Add build scripts that keep generated candidates isolated until every data and browser check passes.
7. Run the complete Python, static release, portable-structure, local browser, and offline-file verification suite.
8. Verify Cloudflare authentication and deploy the validated `dist` directory as a Pages project.
