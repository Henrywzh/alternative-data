#!/usr/bin/env bash
# Commit refreshed datasets and push, retrying against a moving branch.
#
# Usage: commit_dataset_paths.sh "<commit message>" <path>...
#
# Every data workflow needs the same four things, and each one that rewrote
# them by hand got a different subset wrong:
#
#   * A path must be staged when it EXISTS **or** is still TRACKED. A dataset
#     that migrates to date partitions deletes its single file, and an
#     existence-only test skips that deletion -- it then stays unstaged, the
#     commit succeeds without it, and the following `git pull --rebase` aborts
#     with "cannot pull with rebase: You have unstaged changes".
#   * `git add` fails hard on a pathspec matching nothing, so a path that is
#     neither present nor tracked must be dropped before staging, not after.
#   * The check for "anything to do" must be `git status --porcelain`, not
#     `git diff`: a new observation date is a new *untracked* partition file,
#     and git diff does not report untracked paths, so a diff-based guard
#     silently skips committing a fresh day.
#   * Concurrent data workflows land on the branch between the commit and the
#     push, so the push retries behind a fresh rebase.
set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "usage: $0 <commit-message> <path>..." >&2
  exit 2
fi

MESSAGE="$1"
shift
BRANCH="${DEFAULT_BRANCH:-main}"

PATHS=""
for candidate in "$@"; do
  if [ -e "$candidate" ] || git ls-files --error-unmatch "$candidate" >/dev/null 2>&1; then
    PATHS="$PATHS $candidate"
  fi
done

# shellcheck disable=SC2086
if [ -z "$PATHS" ] || [ -z "$(git status --porcelain -- $PATHS)" ]; then
  echo "No dataset changes to commit"
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

# shellcheck disable=SC2086
git add -A -- $PATHS
git commit -m "$MESSAGE"

for attempt in 1 2 3; do
  if git pull --rebase origin "$BRANCH" && git push origin "HEAD:$BRANCH"; then
    exit 0
  fi
  echo "Push failed on attempt ${attempt}; retrying after a fresh rebase" >&2
  sleep $((attempt * 5))
done

echo "Failed to push after 3 attempts" >&2
exit 1
