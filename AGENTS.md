# Codex Repo Notes

## Git Compatibility

Do not enable `extensions.worktreeConfig` in this repository's `.git/config`.

Reason:
- Antigravity failed to resolve workspace metadata when that Git extension was present.
- The failure broke workspace/chat state lookup and caused replies to stop.

If Antigravity stops responding again, first verify that `.git/config` does not contain `extensions.worktreeConfig = true`.

## Local Configuration

DO NOT delete the `.config` file in the repository root.

Reason:
- This file contains critical API keys for FRED, Groq, Gmail, etc., that are required for local execution.
- It is ignored by Git and must be preserved manually or restored from backups if lost.
