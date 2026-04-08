---
description: Clean up git worktreeConfig settings to prevent Antigravity workspace issues
---

This workflow removes `worktreeConfig = true` from the `.git/config` files of your primary repositories.

1.  Navigate to the `alternative-data` repository and clean its config:
// turbo
```bash
git -C /Users/henrywzh/Desktop/quant/alternative-data config --unset-all extensions.worktreeConfig || true
```

2.  Navigate to the `equity-research` repository and clean its config:
// turbo
```bash
git -C /Users/henrywzh/Desktop/quant/equity-research config --unset-all extensions.worktreeConfig || true
```

3.  Verify the settings are gone (optional):
```bash
git -C /Users/henrywzh/Desktop/quant/alternative-data config --get extensions.worktreeConfig && echo "ERROR: Still exists in alternative-data" || echo "alternative-data: Clean"
git -C /Users/henrywzh/Desktop/quant/equity-research config --get extensions.worktreeConfig && echo "ERROR: Still exists in equity-research" || echo "equity-research: Clean"
```
