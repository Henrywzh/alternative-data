# Codex Repo Notes

## Git Compatibility

`extensions.worktreeConfig` is allowed in this repository's `.git/config`.

Historical note:
- Antigravity previously failed to resolve workspace metadata when that Git extension was present.
- That failure broke workspace/chat state lookup and caused replies to stop.

If Antigravity stops responding again, one thing to check is whether `extensions.worktreeConfig = true` is contributing to the issue.

## Local Configuration

DO NOT delete the `.config` file in the repository root.

Reason:
- This file contains critical API keys for FRED, Groq, Gmail, etc., that are required for local execution.
- It is ignored by Git and must be preserved manually or restored from backups if lost.

## Asia Markets

When working anywhere in the Asia Markets project, read the canonical operating
manual before taking action:

- `docs/asia-markets/OPERATING_MANUAL.md`
- `docs/asia-markets/PROJECT_STATUS.md`
- `docs/asia-markets/DATA_CATALOG.md`

These documents are the shared context for Codex, Antigravity, and other agents.
If architecture, data coverage, deployment rules, or known limitations change,
update the relevant document in the same task.

The canonical financial-data repository is the sibling repo at
`/Users/henrywzh/Desktop/Quant/financial-data`. See
`docs/asia-markets/REPO_BRIDGE.md` for the high-level relationship.

## Repository Location

This repository lives at `/Users/henrywzh/Quant/alternative-data`, deliberately
**outside** `~/Desktop/`. Do not move it back.

Reason: macOS iCloud "Desktop & Documents" sync is enabled, so anything under
`~/Desktop/Quant/` is continuously synced. That produced duplicate `<name> 2`
files inside `.git/objects`, blocked `git gc` (a stale `gc.log` stopped
automatic cleanup for weeks), and risked real corruption — iCloud can rewrite
or evict files mid-write while git is building objects. A 31 GB `.git`-bearing
repo also burns iCloud quota for no benefit; code is backed up by its git
remote, not by file-level cloud sync.

Note: `mv` cannot move a large synced tree out of the iCloud domain — it blocks
indefinitely in the file provider with zero CPU. Use `ditto` to copy, verify,
then delete the source.

The sibling repos below are still under `~/Desktop/Quant/` and those paths
remain correct.

## Wider Workspace

Other repos under `~/Desktop/Quant/` are part of the same user's broader
quant work:

- `/Users/henrywzh/Desktop/Quant/quantamental-lab` — mid-frequency
  quantamental factor research. **Actually connected as of 2026-08-08**: its
  regime-risk v2 overlay (`scripts/prepare_regime_inputs_v2.py`) hard-codes a
  path into this repo and reads this repo's normalized OFR/FRED macro data as
  a fallback and positioning source. It has also started a research-only
  "HKEX Corporate Event Impact Baseline v1" chain that pulls its input event
  panel from this repo's and `financial-data`'s HKEX announcement inventory —
  this is the previously-planned HK equity expansion, now underway rather
  than future. It uses a pre-registered-quality-rule selection methodology
  (family chosen before looking at return output) and is explicitly
  research-only in v1: no portfolio construction or trading signal yet.
  The matching half of this work lives here as uncommitted paths under
  `scripts/run_hkex_event_study_yfinance.py`, `data/raw/market_data/yfinance/`
  and `outputs/hkex_event_study_candidates/` — check `git status` for current
  state before assuming it's been committed.
- `/Users/henrywzh/Desktop/Quant/portfolio-research` — the main
  systematic-strategy repo `quantamental-lab` was extracted from. No direct
  connection to this repo found as of 2026-08-08.
- `/Users/henrywzh/Desktop/Quant/equity-research` — referenced by
  `quantamental-lab` for `daily-macro` release-calendar/nowcast code (fetched
  independently via FRED release timing, not shared runtime code). Not yet
  surveyed from this repo's side.

Re-check this section periodically — it has already gone stale once (written
2026-08-07 as "no connection," corrected 2026-08-08 after real coupling
appeared within 24 hours).
