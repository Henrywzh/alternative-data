"""Tests for the repository size guardrail.

The load-bearing property is that the installed hook must never block a commit
for a reason unrelated to size. Hooks live in .git/, which is shared across
branches, while the checker lives in the working tree -- so on any branch
predating the checker the hook runs with the script absent.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check_repo_size_budget.py"


def _hook_body() -> str:
    namespace: dict[str, object] = {}
    source = SCRIPT.read_text(encoding="utf-8")
    start = source.index('HOOK_BODY = """')
    end = source.index('"""', start + len('HOOK_BODY = """'))
    return source[start + len('HOOK_BODY = """') : end]


def test_hook_allows_the_commit_when_the_checker_is_absent(tmp_path: Path) -> None:
    """A branch without the checker must still be committable.

    The first version of this hook exec'd the script unconditionally, so every
    commit on a branch predating it died with "can't open file".
    """
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    hook = tmp_path / "pre-commit.sh"
    hook.write_text(_hook_body(), encoding="utf-8")

    result = subprocess.run(["sh", str(hook)], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 0, f"hook blocked a commit with no checker present: {result.stderr}"


def test_hook_runs_the_checker_when_it_is_present(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    # A checker that fails loudly, to prove the hook actually invokes it.
    (repo / "scripts" / "check_repo_size_budget.py").write_text(
        "import sys\nsys.exit(42)\n", encoding="utf-8"
    )

    hook = tmp_path / "pre-commit.sh"
    hook.write_text(_hook_body(), encoding="utf-8")

    result = subprocess.run(["sh", str(hook)], cwd=repo, capture_output=True, text=True)
    assert result.returncode == 42, "hook did not invoke the checker that is present"


def test_staged_mode_passes_on_an_ordinary_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "notes.md").write_text("small\n", encoding="utf-8")
    subprocess.run(["git", "add", "notes.md"], cwd=repo, check=True)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--staged"], cwd=repo, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
