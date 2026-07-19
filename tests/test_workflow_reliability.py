from __future__ import annotations

from pathlib import Path

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
