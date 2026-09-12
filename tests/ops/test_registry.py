from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from ops_control.registry import RegistryError, load_registry


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "config" / "ops" / "pipelines.yaml"


def _write_file_registry(tmp_path: Path, *, cadence: str, freshness: str = "") -> Path:
    workflow = tmp_path / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "pilot.yml").write_text("name: pilot\n", encoding="utf-8")
    registry = tmp_path / "pipelines.yaml"
    registry.write_text(
        f"""
version: 1
phase: 0
pipelines:
  pilot:
    workflow: pilot.yml
    cadence:
{cadence}
    criticality: medium
    jobs:
      job:
        outputs:
          - id: output
            path: data/output.json
            required: true
            validator: file
{freshness}
""",
        encoding="utf-8",
    )
    return registry


def test_registry_contains_exactly_the_watched_pipelines_and_real_jobs() -> None:
    """The registry is an explicit inventory, so every addition is deliberate.

    Kept exhaustive rather than relaxed to a subset: what this catches is a
    pipeline appearing or disappearing by accident, and a >= assertion would
    notice neither. The three free-institutional entries joined the original
    Phase 0 pilots when those lanes got their first scheduled refresh.
    """
    registry = load_registry(REGISTRY_PATH, repo_root=ROOT)

    assert set(registry.pipelines) == {
        "asia-markets-dashboard-refresh",
        "openrouter-provider-activity",
        "semiconductor-memory-monthly",
        "free-institutional-daily",
        "free-institutional-weekly",
        "free-institutional-monthly",
    }
    assert set(registry.pipelines["openrouter-provider-activity"].jobs) == {
        "scrape-provider-activity"
    }
    assert set(registry.pipelines["asia-markets-dashboard-refresh"].jobs) == {
        "refresh-dashboard-data"
    }
    assert set(registry.pipelines["semiconductor-memory-monthly"].jobs) == {
        "adata-update",
        "fred-update",
    }
    for pipeline_id in (
        "free-institutional-daily",
        "free-institutional-weekly",
        "free-institutional-monthly",
    ):
        assert set(registry.pipelines[pipeline_id].jobs) == {"refresh"}


def test_registry_rejects_paths_that_escape_the_repository(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "pilot.yml").write_text("name: pilot\n", encoding="utf-8")
    registry = tmp_path / "pipelines.yaml"
    registry.write_text(
        """
version: 1
phase: 0
pipelines:
  unsafe:
    workflow: pilot.yml
    cadence:
      kind: daily
      expected_interval_hours: 24
    criticality: medium
    jobs:
      job:
        outputs:
          - id: unsafe
            path: ../outside.parquet
            required: true
            validator: file
""",
        encoding="utf-8",
    )

    with pytest.raises(RegistryError, match="repository-relative"):
        load_registry(registry, repo_root=tmp_path)


def test_registry_rejects_duplicate_yaml_ids(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "pilot.yml").write_text("name: pilot\n", encoding="utf-8")
    registry = tmp_path / "pipelines.yaml"
    registry.write_text(
        """
version: 1
phase: 0
pipelines:
  pilot:
    workflow: pilot.yml
    cadence: {kind: daily, expected_interval_hours: 24}
    criticality: medium
    jobs:
      job:
        outputs:
          - {id: first, path: data/first.json, validator: file}
  pilot:
    workflow: pilot.yml
    cadence: {kind: daily, expected_interval_hours: 24}
    criticality: medium
    jobs:
      job:
        outputs:
          - {id: second, path: data/second.json, validator: file}
""",
        encoding="utf-8",
    )

    with pytest.raises(RegistryError, match="duplicate key"):
        load_registry(registry, repo_root=tmp_path)


def test_registry_rejects_impossible_daily_cadence(tmp_path: Path) -> None:
    registry = _write_file_registry(
        tmp_path,
        cadence="      kind: daily\n      expected_interval_hours: 0",
    )

    with pytest.raises(RegistryError, match="expected_interval_hours"):
        load_registry(registry, repo_root=tmp_path)


def test_registry_rejects_unknown_freshness_mode(tmp_path: Path) -> None:
    registry = _write_file_registry(
        tmp_path,
        cadence="      kind: daily\n      expected_interval_hours: 24",
        freshness=(
            "            freshness:\n"
            "              mode: eventually\n"
        ),
    )

    with pytest.raises(RegistryError, match="freshness mode"):
        load_registry(registry, repo_root=tmp_path)


def test_registry_loads_dashboard_contracts_outside_repo_working_directory(
    tmp_path: Path,
) -> None:
    """The workflow script adds src/, but dashboard.data lives at repo root."""

    program = (
        "from pathlib import Path; "
        "from ops_control.registry import load_registry; "
        f"root=Path({str(ROOT)!r}); "
        "registry=load_registry(root/'config/ops/pipelines.yaml', repo_root=root); "
        "assert 'openrouter-provider-activity' in registry.pipelines"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
