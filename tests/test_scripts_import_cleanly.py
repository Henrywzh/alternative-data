"""Every entry-point script must import the way it is actually invoked.

These run as `python scripts/foo.py` from the repo root, with no PYTHONPATH,
so each is responsible for its own sys.path. Three of them set up only the
repo root while resolving modules through `src.`, which broke the moment the
domain packages started importing their siblings by the top-level names
pyproject actually ships.

The check runs in a subprocess with a clean environment on purpose. An
in-process import under the test suite's own PYTHONPATH=src cannot see this
class of failure at all -- the sibling package resolves from the path pytest
already set up, and the guard passes while the script stays broken.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted(
    path
    for path in (REPO_ROOT / "scripts").glob("*.py")
    if not path.name.startswith("_")
)
OWN_PACKAGES = frozenset(
    entry.name for entry in (REPO_ROOT / "src").iterdir() if entry.is_dir()
)

_PROBE = """
import runpy, sys
sys.argv = [{path!r}]
try:
    runpy.run_path({path!r}, run_name="__probe__")
except SystemExit:
    pass
"""


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_script_imports(path: Path) -> None:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(path=str(path))],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode == 0:
        return

    stderr = result.stderr
    if "ModuleNotFoundError" in stderr:
        missing = stderr.rsplit("No module named ", 1)[-1].strip().strip("'\"").split(".")[0]
        if missing not in OWN_PACKAGES and missing != "src":
            pytest.skip(f"optional dependency not installed: {missing}")
    pytest.fail(f"{path.name} does not import as `python {path.relative_to(REPO_ROOT)}`:\n{stderr[-1500:]}")


def test_the_scripts_directory_was_actually_found() -> None:
    """A glob that silently matches nothing would make the sweep vacuous."""
    assert len(SCRIPTS) > 20
