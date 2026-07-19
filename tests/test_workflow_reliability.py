from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def _tracked_workflows() -> list[Path]:
    return sorted(path for path in WORKFLOWS.glob("*.yml") if " 2" not in path.name)


def test_all_workflows_are_valid_yaml() -> None:
    for workflow_path in _tracked_workflows():
        with workflow_path.open(encoding="utf-8") as stream:
            assert yaml.load(stream, Loader=yaml.BaseLoader)


def test_all_scheduled_jobs_have_explicit_timeouts() -> None:
    for workflow_path in _tracked_workflows():
        workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
        if "schedule" not in workflow.get("on", {}):
            continue
        for job_name, job in workflow.get("jobs", {}).items():
            assert "timeout-minutes" in job, f"{workflow_path.name}:{job_name} has no timeout"


def test_artifact_uploads_use_the_current_node_runtime() -> None:
    for workflow_path in _tracked_workflows():
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "actions/upload-artifact@v4" not in workflow, workflow_path.name


def test_model_activity_workflow_stages_archive_only_when_it_exists() -> None:
    workflow = (WORKFLOWS / "openrouter-model-activity-daily.yml").read_text(encoding="utf-8")

    assert "if [ -d data/normalized/openrouter_archive ]; then" in workflow
    assert "git add data/normalized/openrouter_archive" in workflow


def test_fred_workflow_accepts_the_existing_semiconductor_fred_secret() -> None:
    workflow = (WORKFLOWS / "fred-macro-daily.yml").read_text(encoding="utf-8")

    assert "secrets.FRED_API_KEY || secrets.SEMICONDUCTOR_FRED_API_KEY" in workflow


_DERIVED_BUILD_COMMAND = "openrouter-derived-data --base-dir . build"
_DERIVED_TEST_COMMAND = "python -m pytest -q tests/test_openrouter_derived_data.py"
_DERIVED_RUN_STEP_NAMES = [
    "Install dependencies",
    "Build compact derived marts from committed inputs",
    "Run derived-mart quality tests",
    "Commit compact derived marts",
]
_EXTERNAL_DATA_TOKENS = (
    "curl",
    "wget",
    "http://",
    "https://",
    "requests",
    "urllib",
    "openrouter_data.cli",
    "openrouter_official_data.cli",
    "openrouter-data",
    "openrouter-official-data",
)


def _openrouter_derived_workflow() -> dict[str, object]:
    path = WORKFLOWS / "openrouter-derived-daily.yml"
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _derived_build_job(workflow: dict[str, object]) -> dict[str, object]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    build_jobs = [
        job
        for job in jobs.values()
        if isinstance(job, dict)
        and any(
            isinstance(step, dict) and step.get("run") == _DERIVED_BUILD_COMMAND
            for step in job.get("steps", [])
        )
    ]
    assert len(build_jobs) == 1
    return build_jobs[0]


def _all_run_steps(workflow: dict[str, object]) -> list[dict[str, object]]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    return [
        step
        for job in jobs.values()
        if isinstance(job, dict)
        for step in job.get("steps", [])
        if isinstance(step, dict) and "run" in step
    ]


def _assert_openrouter_derived_workflow_contract(workflow: dict[str, object]) -> None:
    assert workflow["on"]["schedule"] == [{"cron": "30 9 * * *"}]
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["concurrency"]["group"]
    assert workflow["concurrency"]["cancel-in-progress"] == "false"

    build_job = _derived_build_job(workflow)
    assert build_job.get("timeout-minutes") == "20"
    steps = build_job.get("steps", [])
    assert isinstance(steps, list)
    run_steps = [step for step in steps if isinstance(step, dict) and "run" in step]

    for step in _all_run_steps(workflow):
        run = step["run"]
        assert isinstance(run, str)
        assert not any(
            token in run.lower() for token in _EXTERNAL_DATA_TOKENS
        ), f"external data or network command found in {step.get('name')!r}"

    assert [step.get("name") for step in run_steps] == _DERIVED_RUN_STEP_NAMES
    assert run_steps[1]["run"] == _DERIVED_BUILD_COMMAND
    assert run_steps[2]["run"] == _DERIVED_TEST_COMMAND

    commit_run = run_steps[3]["run"]
    assert isinstance(commit_run, str)
    git_add_lines = [
        line.strip()
        for line in commit_run.replace("\\\n", " ").splitlines()
        if line.strip().startswith("git add ")
    ]
    assert len(git_add_lines) == 1
    assert git_add_lines[0].split() == [
        "git",
        "add",
        "data/normalized/marts/openrouter_usage_economics_daily.parquet",
        "data/normalized/marts/openrouter_workload_intensity_models.parquet",
    ]


def test_openrouter_derived_workflow_is_bounded_and_no_network() -> None:
    workflow_path = WORKFLOWS / "openrouter-derived-daily.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = _openrouter_derived_workflow()

    assert "secrets." not in workflow_text
    _assert_openrouter_derived_workflow_contract(workflow)


def test_openrouter_derived_workflow_rejects_an_external_data_step() -> None:
    workflow = deepcopy(_openrouter_derived_workflow())
    workflow["jobs"]["unexpected"] = {
        "steps": [{"name": "Fetch external data", "run": "curl https://example.com"}]
    }

    with pytest.raises(AssertionError, match="external data or network command"):
        _assert_openrouter_derived_workflow_contract(workflow)


def test_openrouter_derived_workflow_rejects_a_missing_timeout() -> None:
    workflow = deepcopy(_openrouter_derived_workflow())
    build_job = _derived_build_job(workflow)
    build_job.pop("timeout-minutes")

    with pytest.raises(AssertionError):
        _assert_openrouter_derived_workflow_contract(workflow)


def test_openrouter_derived_workflow_rejects_a_timeout_moved_to_another_job() -> None:
    workflow = deepcopy(_openrouter_derived_workflow())
    build_job = _derived_build_job(workflow)
    build_job.pop("timeout-minutes")
    workflow["jobs"]["unrelated"] = {"timeout-minutes": 20, "steps": []}

    with pytest.raises(AssertionError):
        _assert_openrouter_derived_workflow_contract(workflow)
