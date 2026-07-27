# Phase 5 Plan: Ship the Aerospace + Crypto Dashboards

**Status check (verified 2026-07-27):** the backend pipelines for both
sectors are built, tested, and correct — `src/hk_commercial_aerospace/`
and `src/hk_stablecoin_crypto/`, committed in `fe185cc` and hardened in
`b8d3dc2`/`b999b51` after a review pass found and fixed 3 real
data-correctness bugs (SSE status field, HKMA licence-number column, SFC
header artifacts). **But no dashboard exists yet.** Confirmed:
- `apps/asia-markets-dashboard/sectors.json` still lists both under
  `"planned"`, not `"live"`.
- Neither artifact builder has ever produced a file in `.generated/` —
  they've only been run once each, straight to `/tmp`, during testing.
- **The artifact schema doesn't match what the rendering pipeline expects.**
  I ran `build_hk_commercial_aerospace_artifact.py` just now: it produces
  `{generated_at, sector, ipo_race, launch_cadence, satellite_counts,
  patent_counts, watchlist, policy_milestones, known_gaps, sources}` — a
  bespoke shape. Every live sector's artifact (checked `hk-reit`'s) instead
  produces `{surface, manifest, snapshot, sources, source_health,
  package_info}`, where `manifest.cards`/`manifest.charts`/`manifest.tables`
  declare *which dataset field maps to which UI element*, and
  `snapshot.datasets` holds the actual rows. `build-static-hub.mjs` and
  `package-dashboard.mjs` are generic renderers that only know how to walk
  the second shape. **This is the single biggest remaining task** — not
  "wire it in," but "restructure the artifact output to match the
  convention every other sector uses."

## What "done" looks like
Read `build_hk_reit_artifact.py` end to end (it's the smallest of the 6
live sectors) before touching anything else here. Match its shape:
`manifest.cards` for KPI tiles, `manifest.charts`/`manifest.tables` each
pointing at a `snapshot.datasets[<name>]` array of row dicts, plus
`sources`/`source_health`/`package_info` blocks. The aerospace/crypto
builders already compute the right underlying data (IPO status, launch
cadence, satellite counts, HKMA/SFC registers, DefiLlama, COIN/CRCL,
Polymarket) — this task is about re-shaping that data into the convention,
not re-fetching anything.

## Step-by-step

1. **Restructure both artifact builders' output** to the manifest+snapshot
   shape. Suggested chart/table mapping (adjust as you see fit — this is a
   starting point, not a spec):
   - Aerospace: an "IPO race" table (company, audit status, financing
     amount, update date) from `ipo_race`; a launch-cadence chart (launches
     per month per agency) from `launch_cadence`; a satellite-count chart
     (Qianfan/Jilin-1 over time) from `satellite_counts`; a patent-count
     card/table from `patent_counts`; the existing HK-listed watchlist as a
     comparison table; policy milestones as a simple timeline/table.
   - Crypto: an HKMA/SFC licensing-status table; a stablecoin
     market-share chart from DefiLlama; a Coinbase Premium + Fear & Greed
     KPI card; a company-tier table (the Tier 1-4 structure from the
     research doc, preserved — don't flatten it); an HKEX crypto-ETF AUM
     chart once the last fundId is resolved (see below).

2. **Add ZH dictionaries.** Every live sector has one in
   `package-dashboard.mjs` (`HK_REIT_ZH`, `HK_TELECOM_ZH`, etc. — grep for
   `_ZH = {` to see the full set and follow the exact pattern: chart
   titles, table headers, card labels, source names, and any `dataLabels`
   needed for categorical fields like status/region). Skipping this means
   the `/zh/` pages ship with English text, which is exactly the bug class
   that got fixed across the other 6 sectors earlier this session — don't
   reintroduce it for the two newest ones.

3. **Regenerate and manually spot-check.** Run both builders for real
   (`python3 scripts/build_hk_commercial_aerospace_artifact.py --output
   .generated/hk-commercial-aerospace-artifact.json --status-output
   src/data/dashboard-status-hk-commercial-aerospace.json`, same pattern
   for crypto) and actually open the JSON — confirm real numbers, not
   nulls, same standard as everywhere else in this repo. Note: Google
   Patents returned HTTP 503 for every query when I tested this today —
   almost certainly because this exact endpoint has been hit repeatedly all
   day across other work in this session, not a code problem. The pipeline
   already degrades gracefully (`ok: true` even when patent fetches fail),
   so don't chase this specific 503 — just don't mistake "patents came back
   empty this one run" for a real bug if everything else populated fine.

4. **Add both sectors to `sectors.json`**, moving them from `planned` to
   `live` (see the existing 6 entries for the exact fields needed:
   `code`, `id`, `package`, `nameEn`/`nameZh`, `builder`, `statusFile`).
   Remove their `planned` entries.

5. **Run the full local build pipeline and watch specifically for the
   mobile-viewport overflow check** — `node scripts/run-artifact-builders.mjs`
   → `node scripts/build-static-hub.mjs` → `node scripts/package-dashboard.mjs`.
   This just bit me today on an *existing* sector (adding one extra chart
   legend entry overflowed the 390px mobile check and blocked packaging for
   every sector, not just the one that caused it). Two new sectors with
   never-before-rendered chart/table content have real risk here —
   particularly long Chinese company names (蓝箭航天空间科技股份有限公司-style
   full legal names), IPO status labels, and ticker-heavy legends. If
   packaging fails with `horizontal_overflow`, don't fight the renderer
   (it's an external plugin, not something in this repo to patch) — trim
   which series get charted, shorten labels, or move dense content into a
   table instead of a chart legend, the same fix applied today.

6. **Verify locally in a browser** before deploying — open the generated
   `dist/sectors/hk-commercial-aerospace/` and `dist/sectors/hk-stablecoin-crypto/`
   pages (and their `/zh/` counterparts) and actually look at them.

7. **Deploy**: `npx wrangler pages deploy dist --project-name=asia-markets-dashboard --branch=production --commit-dirty=true`.

8. **Only after the above is confirmed working**, write the scheduled
   GitHub Actions workflows. Follow `hk-transport-monthly.yml` as the
   template (it's the most recently added one, for a similarly
   catalyst/theme-driven sector) — pick a cadence matching how often the
   underlying sources actually change (SSE/HKMA/SFC registers and
   Celestrak/DefiLlama don't need daily polling; weekly or monthly is
   probably right for both sectors, mirroring the aerospace doc's own
   framing that this is a slow-moving theme, not a high-frequency one).
   Respect Launch Library's 15-req/hour limit in however the workflow
   batches its calls.

## Known open items — don't block on these, note and move on
- **Harvest Ether Spot ETF (3179.HK)'s HKEX fundId is still unknown.** 5 of
  6 crypto ETFs are confirmed; ship with 5 and add the 6th once found (a
  5-minute lookup on `ifp.hkex.com.hk`, not a real blocker).
- **Guowang/国网's Celestrak identifier is still unresolved** (aerospace).
  Ship satellite-count tracking for Qianfan and Jilin-1 only; Guowang can
  be added later once the designator-to-launch cross-reference is done.
- Both allowlist entries in `tests/test_asia_markets_wiring.py`
  (`UNROSTERED_BUILDERS`/`UNPUBLISHED_PACKAGES`) expire **2026-09-28** —
  once these sectors are promoted to `sectors.json`, remove the
  now-unnecessary allowlist entries rather than letting them sit stale.

## Guardrails (same as the earlier implementation brief)
- Shared working tree, other work may be in flight — scope commits
  precisely, never `git add -A`.
- Verify against live data at each step, the same standard used
  throughout this repo — don't trust a green test suite alone as proof of
  correctness (the earlier review of this exact codebase found 3 real
  silent-data bugs that all had passing tests).
