"""Portability checks for the scheduled Hong Kong retail store runner."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run-store-scrapers.sh"


def test_store_runner_uses_path_resolved_python_interpreter():
    content = RUNNER.read_text(encoding="utf-8")

    assert 'PYTHON_BIN="${PYTHON_BIN:-python3}"' in content
    assert '"$PYTHON_BIN" "scripts/$script"' in content
    assert "~/.pyenv/shims/python3" not in content
