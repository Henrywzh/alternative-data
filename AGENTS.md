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
