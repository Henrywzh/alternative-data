# Codex Repo Notes

## Git Compatibility

Do not enable `extensions.worktreeConfig` in this repository's `.git/config`.

Reason:
- Antigravity failed to resolve workspace metadata when that Git extension was present.
- The failure broke workspace/chat state lookup and caused replies to stop.

If Antigravity stops responding again, first verify that `.git/config` does not contain `extensions.worktreeConfig = true`.
