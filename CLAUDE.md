# Claude Repo Notes

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

Before working on Asia Markets, read the shared project context:

- `docs/asia-markets/OPERATING_MANUAL.md`
- `docs/asia-markets/PROJECT_STATUS.md`
- `docs/asia-markets/DATA_CATALOG.md`

Keep these documents current when changing the dashboard architecture, data
coverage, deployment workflow, or known limitations.

The sibling canonical financial-data repository is
`/Users/henrywzh/Desktop/Quant/financial-data`. See
`docs/asia-markets/REPO_BRIDGE.md` for the high-level relationship.

## Wider Workspace

Two other repos under `~/Desktop/Quant/` are part of the same user's broader
quant work but are not currently wired to this repo or to `financial-data` —
no shared code or data as of 2026-08-07:

- `/Users/henrywzh/Desktop/Quant/quantamental-lab` — mid-frequency
  quantamental factor research. Currently implements a US-equities
  SEC-filing earnings-alpha strategy only, but is scoped more broadly; HK
  equity is a planned future expansion that should converge with
  `financial-data`'s existing HK universe rather than duplicate it.
- `/Users/henrywzh/Desktop/Quant/portfolio-research` — the main
  systematic-strategy repo `quantamental-lab` was extracted from.

Check both before assuming a code/data connection doesn't exist elsewhere in
the workspace, and update this note if either becomes actually connected.
