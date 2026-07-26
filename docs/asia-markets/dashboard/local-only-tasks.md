# Asia Markets Dashboard — tasks that require a local run

GitHub Actions cannot do everything this dashboard needs. This is the list of
what only works from a local machine (this Mac, or any residential-IP /
plugin-equipped environment), why, and how often to do it.

## 1. Midland Realty scrape (MHPI + Confidence Index)

- **Why local-only**: `www.midland.com.hk/zh-hk/market-insight` WAF-blocks
  GitHub Actions' datacenter IP range (confirmed 403, reproducible). The
  exact same fetch succeeds from a residential IP with no code change.
- **What CI does instead**: skips the fetch (`HK_RE_SKIP_MIDLAND=1` set in
  `.github/workflows/asia-markets-dashboard-refresh-daily.yml`) and falls
  back to the last real snapshot on disk, so one blocked source doesn't
  stall the rest of the HK Real Estate refresh.
- **How to refresh it**: run locally, with the env var unset:
  ```bash
  python3 -c "from src.hk_real_estate.pipeline import run_group_a_pipeline; run_group_a_pipeline()"
  python3 apps/asia-markets-dashboard/scripts/build_hk_real_estate_artifact.py \
    --output apps/asia-markets-dashboard/.generated/hk-real-estate-artifact.json \
    --status-output apps/asia-markets-dashboard/src/data/dashboard-status.json
  ```
- **Cadence**: MHPI/Confidence Index publish weekly — running this every
  few days is enough to stay current. Not urgent daily.

## 2. Portable HTML packaging (`npm run build`'s last step)

- **Why local-only**: `scripts/package-dashboard.mjs` calls an external tool
  (`deliver_portable_artifact.mjs`) that lives under a local Claude Code/Codex
  plugin cache (`~/.codex/plugins/cache/openai-curated-remote/data-analytics/*/skills/build-report/scripts/`)
  — a proprietary plugin bundle, not a published npm package. No public
  registry entry exists to fetch this exact version on a generic GitHub
  Actions runner, and vendoring OpenAI's bundled plugin code into this repo
  isn't appropriate.
- **What CI does instead**: only runs `npm run refresh` (the live-data half)
  — `.generated/*.json` and `src/data/dashboard-status*.json` stay fresh
  daily. It does NOT run `build-static-hub.mjs` or `package-dashboard.mjs`,
  so the rendered `.generated/*.html` portable dashboards (and their `-zh`
  variants) go stale until the next local rebuild.
- **How to refresh it**: from `apps/asia-markets-dashboard/`:
  ```bash
  npm run build
  ```
  (needs the plugin cache present, i.e. run from a machine where Claude
  Code/Codex has already resolved that plugin — confirmed present on this
  Mac).
- **Cadence**: whenever you want the downloadable HTML exports and the
  `/data-status/` coverage tables to reflect the latest data — not required
  for the underlying JSON data to stay correct, just for the polished
  portable artifacts and hub page.

## 3. Production deploy (Cloudflare Pages)

- **Why local-only**: Cloudflare Pages' configured **Production** branch is
  literally named `production`, not `main`. Pushing to `main` only ever
  creates a **Preview** deployment — there is no CLI/API path from this
  session to reconfigure that branch mapping in Cloudflare's dashboard.
- **What CI does instead**: nothing — no workflow deploys to Cloudflare at
  all currently.
- **How to deploy**: from `apps/asia-markets-dashboard/`, after `npm run build`:
  ```bash
  npx wrangler pages deploy dist --project-name=asia-markets-dashboard --branch=production --commit-dirty=true
  ```
  (`--branch=main` or omitting `--branch` silently creates another Preview,
  not Production — verified this session, easy mistake to repeat.)
- **Cadence**: whenever you want the public site to reflect what's on
  `main` — not automatic.

## Not local-only (for contrast)

- Underlying data refresh for every other sector (Local Consumer, Utilities,
  Transport, Telecom, REITs) — all run fine in GitHub Actions today, no
  known IP-blocking issues.
- Unit/integration tests (`pytest`) — run in the `CI` workflow on every push.
