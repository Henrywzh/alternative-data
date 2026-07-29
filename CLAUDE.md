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
