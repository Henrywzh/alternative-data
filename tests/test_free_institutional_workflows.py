"""The scheduled refresh workflows for the free institutional lanes.

These lanes were backfilled once and then never refreshed -- every dataset was
last written by the backfill or a bug fix, never by a scheduled run. The point
of these tests is that the schedule actually exists, resumes rather than
refetching from 2019, and commits through the one helper whose logic has been
tested against real git.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
REFRESH_WORKFLOWS = {
    "free-institutional-daily.yml": {"hkex", "eia", "hkma"},
    "free-institutional-weekly.yml": {"factset"},
    "free-institutional-monthly.yml": {"sp_pmi", "bis", "msci"},
}


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _run_steps(workflow: dict) -> list[str]:
    return [
        step["run"]
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if "run" in step
    ]


@pytest.mark.parametrize("name", sorted(REFRESH_WORKFLOWS))
def test_the_lane_is_actually_scheduled(name: str) -> None:
    # The whole failure being fixed: seven lanes, zero schedules.
    workflow = _load(name)
    # PyYAML resolves a bare `on:` key to the boolean True.
    triggers = workflow.get("on") or workflow[True]
    assert triggers.get("schedule"), f"{name} has no cron"
    assert "workflow_dispatch" in triggers, f"{name} cannot be run by hand"


@pytest.mark.parametrize("name", sorted(REFRESH_WORKFLOWS))
def test_a_scheduled_run_resumes_instead_of_refetching_from_2019(name: str) -> None:
    # Without --resume a daily run re-fetches ~1,750 HKEX trading days and
    # re-merges 2,800 EIA partitions, which is why these were never scheduled.
    runs = "\n".join(_run_steps(_load(name)))
    assert "--resume" in runs, f"{name} would refetch the full history every run"


@pytest.mark.parametrize(("name", "sources"), sorted((k, v) for k, v in REFRESH_WORKFLOWS.items()))
def test_the_workflow_runs_the_sources_it_claims(name: str, sources: set[str]) -> None:
    runs = "\n".join(_run_steps(_load(name)))
    default = runs.split("${SOURCES:-", 1)[1].split("}", 1)[0]
    assert set(default.split()) == sources


@pytest.mark.parametrize("name", sorted(REFRESH_WORKFLOWS))
def test_the_commit_goes_through_the_shared_helper(name: str) -> None:
    # Two production CI failures came from hand-rolled commit steps. The logic
    # lives in one tested script now, and these workflows must not grow their
    # own copy.
    runs = "\n".join(_run_steps(_load(name)))
    assert "scripts/ci/commit_dataset_paths.sh" in runs
    assert "git add" not in runs, f"{name} hand-rolls staging instead of using the helper"
    assert "git push" not in runs, f"{name} hand-rolls pushing instead of using the helper"


@pytest.mark.parametrize("name", sorted(REFRESH_WORKFLOWS))
def test_cme_is_not_scheduled(name: str) -> None:
    # cmegroup.com answers 403 to the runner. A lane that fails every single
    # run trains everyone to ignore the alert, so it stays dispatch-only.
    runs = "\n".join(_run_steps(_load(name)))
    default = runs.split("${SOURCES:-", 1)[1].split("}", 1)[0]
    assert "cme" not in default.split()


@pytest.mark.parametrize("name", sorted(REFRESH_WORKFLOWS))
def test_the_refreshed_lanes_are_the_committed_lanes(name: str) -> None:
    # A lane fetched but not committed is a job that reports success and
    # publishes nothing -- the exact shape of the bug this replaces.
    lanes = {
        "hkex": "data/normalized/hkex_market_flow",
        "eia": "data/normalized/eia_energy",
        "hkma": "data/normalized/hkma_macro",
        "factset": "data/normalized/factset_earnings",
        "sp_pmi": "data/normalized/sp_pmi",
        "bis": "data/normalized/bis_macro",
        "msci": "data/normalized/msci_reviews",
    }
    runs = "\n".join(_run_steps(_load(name)))
    for source in REFRESH_WORKFLOWS[name]:
        assert lanes[source] in runs, f"{name} refreshes {source} but never commits it"


@pytest.mark.parametrize("name", sorted(REFRESH_WORKFLOWS))
def test_the_workflow_is_registered_for_staleness_monitoring(name: str) -> None:
    registry = yaml.safe_load((ROOT / "config" / "ops" / "pipelines.yaml").read_text())
    workflows = {pipeline["workflow"] for pipeline in registry["pipelines"].values()}
    assert name in workflows, f"{name} refreshes data nothing watches for going stale"
