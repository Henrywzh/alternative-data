"""Guard against nested pytest conftest files shadowing tests/conftest.py."""

from __future__ import annotations

from pathlib import Path

import conftest


ROOT = Path(__file__).resolve().parent.parent


def test_conftest_module_is_the_repo_root_helper() -> None:
    assert Path(conftest.__file__).resolve() == (ROOT / "tests" / "conftest.py").resolve()
    assert hasattr(conftest, "require_local_normalized")
    assert hasattr(conftest, "require_local_capture")


def test_event_fixtures_live_outside_nested_conftest() -> None:
    nested = ROOT / "tests" / "event_consensus" / "conftest.py"
    assert not nested.exists()
    from event_consensus_fixtures import NOW, fake_pipeline_result, write_artifact

    assert NOW.year == 2026
    assert fake_pipeline_result()["artifact"]["status"] == "ready"
    assert callable(write_artifact)
