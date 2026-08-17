"""Tests for scripts/run_backtest_engine.py's stage sequencing.

Only the control flow is under test here (which subprocess commands get
invoked, and in what order) -- the actual stage scripts are never run.
``subprocess.run`` is monkeypatched so no real build work happens.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.run_backtest_engine as engine


def _fake_run(recorded: list[list[str]], *, fail_script: str | None):
    def _inner(command, cwd=None):  # noqa: ANN001 - matches subprocess.run's signature loosely
        recorded.append(command)
        script_name = Path(command[1]).name
        returncode = 1 if fail_script is not None and script_name == fail_script else 0
        return SimpleNamespace(returncode=returncode)

    return _inner


def test_prune_stage_does_not_run_when_a_prior_stage_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[list[str]] = []
    monkeypatch.setattr(
        engine.subprocess,
        "run",
        _fake_run(recorded, fail_script="build_asia_backtest_registry.py"),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["run_backtest_engine.py", "--skip-mtr"],
    )

    rc = engine.main()

    assert rc == 1
    invoked_scripts = [Path(command[1]).name for command in recorded]
    assert "build_asia_backtest_registry.py" in invoked_scripts
    # The long-form stage comes after the registry stage and must not run.
    assert "build_asia_backtest_long_form.py" not in invoked_scripts
    # The whole point of this test: pruning must never run after a failure.
    assert "prune_backtest_runs.py" not in invoked_scripts


def test_prune_stage_runs_after_all_stages_succeed(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[list[str]] = []
    monkeypatch.setattr(engine.subprocess, "run", _fake_run(recorded, fail_script=None))
    monkeypatch.setattr("sys.argv", ["run_backtest_engine.py", "--skip-mtr", "--keep-runs", "5"])

    rc = engine.main()

    assert rc == 0
    invoked_scripts = [Path(command[1]).name for command in recorded]
    assert invoked_scripts[-1] == "prune_backtest_runs.py"
    prune_command = recorded[-1]
    assert "--keep" in prune_command
    assert prune_command[prune_command.index("--keep") + 1] == "5"
    assert "--apply" in prune_command


def test_skip_prune_flag_prevents_prune_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[list[str]] = []
    monkeypatch.setattr(engine.subprocess, "run", _fake_run(recorded, fail_script=None))
    monkeypatch.setattr("sys.argv", ["run_backtest_engine.py", "--skip-mtr", "--skip-prune"])

    rc = engine.main()

    assert rc == 0
    invoked_scripts = [Path(command[1]).name for command in recorded]
    assert "prune_backtest_runs.py" not in invoked_scripts


def test_prune_failure_does_not_fail_the_overall_run(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: list[list[str]] = []
    monkeypatch.setattr(
        engine.subprocess,
        "run",
        _fake_run(recorded, fail_script="prune_backtest_runs.py"),
    )
    monkeypatch.setattr("sys.argv", ["run_backtest_engine.py", "--skip-mtr"])

    rc = engine.main()

    # A prune failure is cleanup-stage noise, not a build failure: the
    # engine's own artifacts already built successfully.
    assert rc == 0
    invoked_scripts = [Path(command[1]).name for command in recorded]
    assert "prune_backtest_runs.py" in invoked_scripts


def test_default_keep_runs_is_three() -> None:
    parser_defaults = engine.main.__globals__["DEFAULT_KEEP_RUNS"]
    assert parser_defaults == 3
