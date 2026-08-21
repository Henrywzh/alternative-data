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


def test_asia_markets_refresh_stages_all_durable_builder_outputs() -> None:
    workflow = (WORKFLOWS / "asia-markets-dashboard-refresh-daily.yml").read_text(encoding="utf-8")
    commit_section = workflow.split("git add \\\n", 1)[1].split("if git diff --staged --quiet; then", 1)[0]

    for path in (
        "apps/asia-markets-dashboard/.generated/",
        "apps/asia-markets-dashboard/src/data/",
        "data/normalized/hk_commercial_aerospace/",
        "data/normalized/hk_local_consumer/afcd_category_history.csv",
        "data/normalized/hk_local_consumer/consumer_council_oilprice_history.csv",
    ):
        assert path in commit_section


@pytest.mark.parametrize(
    "workflow_name",
    [
        "openrouter-apps-daily.yml",
        "openrouter-task-spend-daily.yml",
        "openrouter-rankings-weekly.yml",
    ],
)
def test_openrouter_write_workflows_are_serialized_and_retry_pushes(workflow_name: str) -> None:
    workflow = (WORKFLOWS / workflow_name).read_text(encoding="utf-8")
    parsed = yaml.load(workflow, Loader=yaml.BaseLoader)

    assert parsed["concurrency"]["cancel-in-progress"] == "false"
    assert "fetch-depth: 0" in workflow
    assert "for attempt in 1 2 3; do" in workflow
    assert "git pull --rebase" in workflow
    assert "git push" in workflow


def test_fred_workflow_accepts_the_existing_semiconductor_fred_secret() -> None:
    workflow = (WORKFLOWS / "fred-macro-daily.yml").read_text(encoding="utf-8")

    assert "secrets.FRED_API_KEY || secrets.SEMICONDUCTOR_FRED_API_KEY" in workflow


_DERIVED_BUILD_COMMAND = "openrouter-derived-data --base-dir . build"
_DERIVED_TEST_COMMAND = """python -m pytest -q \\
  tests/test_openrouter_derived_data.py \\
  tests/test_openrouter_capability_resolver.py"""
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
_INSTALL_DEPENDENCIES_RUN = """\
python -m pip install --upgrade pip
python -m pip install -e .[dev]"""
_SYNC_INPUTS_RUN = """\
for attempt in 1 2 3; do
  if git pull --rebase origin "${{ github.event.repository.default_branch }}"; then
    exit 0
  fi
  sleep $((attempt * 5))
done
exit 1"""
_COMMIT_DERIVED_MARTS_RUN = """\
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add data/normalized/marts/openrouter_usage_economics_daily.parquet \\
        data/normalized/marts/openrouter_workload_intensity_models.parquet
if git diff --staged --quiet; then
  echo "No OpenRouter derived metric changes to commit"
  exit 0
fi
git commit -m "chore: update OpenRouter derived metrics [$(date -u +%Y-%m-%d)]"

for attempt in 1 2 3; do
  if git push; then
    exit 0
  fi
  sleep $((attempt * 5))
done
exit 1"""
_DRIFT_GUARD_RUN = """\
openrouter-derived-data --base-dir . guard --top-n 10 --json > guard.json"""
_DRIFT_ISSUE_RUN = """\
gh issue list --state open --search "capability-map-drift in:title" \\
  --json number --jq '.[0].number' > issue.txt || true
if [ ! -s issue.txt ] || [ "$(cat issue.txt)" = "null" ]; then
  gh issue create --title "capability-map-drift" \\
    --label "data-quality" \\
    --body "The daily capability guard reported unresolved top-10 models. Details follow as comments."
fi
gh issue comment "$(gh issue list --state open --search 'capability-map-drift in:title' --json number --jq '.[0].number')" \\
  --body "$(printf 'Capability guard, %s\\n\\n```json\\n%s\\n```\\n' "$(date -u +%Y-%m-%d)" "$(cat guard.json)")"
"""


def _normalize_run_body(run: str) -> str:
    return "\n".join(line.rstrip() for line in run.strip().splitlines())


_APPROVED_DERIVED_STEPS = [
    {
        "name": "Check out repository",
        "uses": "actions/checkout@v7",
        "with": {
            "ref": "${{ github.event.repository.default_branch }}",
            "fetch-depth": "0",
        },
    },
    {
        "name": "Set up Python",
        "uses": "actions/setup-python@v6",
        "with": {"python-version": "3.11"},
    },
    {
        "name": "Install dependencies",
        "run": _normalize_run_body(_INSTALL_DEPENDENCIES_RUN),
    },
    {
        "name": "Synchronize committed inputs",
        "run": _normalize_run_body(_SYNC_INPUTS_RUN),
    },
    {
        "name": "Build compact derived marts from committed inputs",
        "run": _DERIVED_BUILD_COMMAND,
    },
    {
        "name": "Run derived-mart quality tests",
        "run": _normalize_run_body(_DERIVED_TEST_COMMAND),
    },
    {
        "name": "Commit compact derived marts",
        "run": _normalize_run_body(_COMMIT_DERIVED_MARTS_RUN),
    },
    {
        "continue-on-error": "true",
        "id": "guard",
        "name": "Capability drift guard",
        "run": _normalize_run_body(_DRIFT_GUARD_RUN),
    },
    {
        "env": {"GH_TOKEN": "${{ secrets.GITHUB_TOKEN }}"},
        "if": "steps.guard.outcome == 'failure'",
        "name": "Open or update capability-map-drift issue",
        "run": _normalize_run_body(_DRIFT_ISSUE_RUN),
    },
]


def _openrouter_derived_workflow() -> dict[str, object]:
    path = WORKFLOWS / "openrouter-derived-daily.yml"
    return yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def _derived_build_job(workflow: dict[str, object]) -> dict[str, object]:
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    assert list(jobs) == ["build"]
    build_job = jobs["build"]
    assert isinstance(build_job, dict)
    return build_job


def _derived_build_steps(workflow: dict[str, object]) -> list[dict[str, object]]:
    steps = _derived_build_job(workflow).get("steps")
    assert isinstance(steps, list)
    assert all(isinstance(step, dict) for step in steps)
    return steps


def _assert_openrouter_derived_workflow_contract(workflow: dict[str, object]) -> None:
    assert workflow["on"]["schedule"] == [{"cron": "30 9 * * *"}]
    assert "workflow_dispatch" in workflow["on"]
    assert workflow["concurrency"]["group"]
    assert workflow["concurrency"]["cancel-in-progress"] == "false"

    build_job = _derived_build_job(workflow)
    assert set(build_job) == {"runs-on", "timeout-minutes", "steps"}
    assert build_job["runs-on"] == "ubuntu-latest"
    assert build_job["timeout-minutes"] == "20"
    steps = _derived_build_steps(workflow)
    normalized_steps = [
        {
            **step,
            "run": _normalize_run_body(step["run"]),
        }
        if "run" in step
        else step
        for step in steps
    ]
    assert normalized_steps == _APPROVED_DERIVED_STEPS

    for step in steps:
        if "run" not in step:
            continue
        run = step["run"]
        assert isinstance(run, str)
        assert not any(
            token in run.lower() for token in _EXTERNAL_DATA_TOKENS
        ), f"external data or network command found in {step.get('name')!r}"


def test_openrouter_derived_workflow_is_bounded_and_no_custom_secrets() -> None:
    workflow_path = WORKFLOWS / "openrouter-derived-daily.yml"
    workflow_text = workflow_path.read_text(encoding="utf-8")
    workflow = _openrouter_derived_workflow()

    # The built-in GITHUB_TOKEN is allowed for repo-scoped issue notifications;
    # any other secret would imply an external credential (and network access).
    for line in workflow_text.splitlines():
        if "secrets." not in line:
            continue
        assert "${{ secrets.GITHUB_TOKEN }}" in line, f"unexpected secret usage: {line}"
    _assert_openrouter_derived_workflow_contract(workflow)


def test_openrouter_derived_workflow_rejects_an_external_data_step() -> None:
    workflow = deepcopy(_openrouter_derived_workflow())
    _derived_build_steps(workflow)[2]["run"] += "\ncurl https://example.com"

    with pytest.raises(AssertionError):
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


def test_openrouter_derived_workflow_rejects_an_extra_collector_job() -> None:
    workflow = deepcopy(_openrouter_derived_workflow())
    workflow["jobs"]["collector"] = {
        "steps": [{"name": "Collect data", "run": "python scripts/collect_openrouter.py"}]
    }

    with pytest.raises(AssertionError):
        _assert_openrouter_derived_workflow_contract(workflow)


def test_openrouter_derived_workflow_rejects_an_extra_action_only_step() -> None:
    workflow = deepcopy(_openrouter_derived_workflow())
    _derived_build_steps(workflow).append(
        {"name": "Cache dependencies", "uses": "actions/cache@v4"}
    )

    with pytest.raises(AssertionError):
        _assert_openrouter_derived_workflow_contract(workflow)


def test_openrouter_derived_workflow_rejects_an_appended_collector_command() -> None:
    workflow = deepcopy(_openrouter_derived_workflow())
    _derived_build_steps(workflow)[4]["run"] += "\npython -m another_collector"

    with pytest.raises(AssertionError):
        _assert_openrouter_derived_workflow_contract(workflow)


def test_openrouter_derived_workflow_builds_only_after_successful_sync() -> None:
    steps = _derived_build_steps(_openrouter_derived_workflow())
    names = [step["name"] for step in steps]

    assert names.index("Synchronize committed inputs") < names.index(
        "Build compact derived marts from committed inputs"
    )


def test_openrouter_derived_workflow_has_no_sync_after_build() -> None:
    steps = _derived_build_steps(_openrouter_derived_workflow())
    build_index = next(
        index
        for index, step in enumerate(steps)
        if step["name"] == "Build compact derived marts from committed inputs"
    )

    for step in steps[build_index + 1 :]:
        run = str(step.get("run", "")).lower()
        assert "git pull" not in run
        assert "git rebase" not in run
