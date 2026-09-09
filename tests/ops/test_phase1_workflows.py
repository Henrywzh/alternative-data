from __future__ import annotations

from pathlib import Path
import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name: str) -> dict:
    return yaml.load((WORKFLOWS / name).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def test_phase_one_control_plane_workflows_are_github_hosted() -> None:
    for name in ("ops-reconcile.yml", "ops-daily-digest.yml"):
        workflow = _load(name)
        for job in workflow["jobs"].values():
            assert job["runs-on"] == "ubuntu-latest"
            assert "self-hosted" not in str(job)


def test_reconcile_runs_every_six_hours() -> None:
    workflow = _load("ops-reconcile.yml")
    assert {"cron": "0 */6 * * *"} in workflow["on"]["schedule"] or any(
        item.get("cron") == "0 */6 * * *" for item in workflow["on"]["schedule"]
    )
    job = workflow["jobs"]["reconcile"]
    names = [step.get("name") for step in job["steps"]]
    assert "Reconcile registered pipelines" in names
    assert workflow["permissions"]["contents"] == "read"
    assert "self-hosted" not in str(workflow)


def test_daily_digest_runs_at_taipei_0900() -> None:
    workflow = _load("ops-daily-digest.yml")
    crons = [item.get("cron") for item in workflow["on"]["schedule"]]
    assert "0 1 * * *" in crons
    run_step = next(step for step in workflow["jobs"]["digest"]["steps"] if step.get("name") == "Build daily digest")
    assert "scripts/ops/daily_digest.py" in run_step["run"]
    assert "GMAIL_APP_PASSWORD" in str(run_step["env"])


def test_pilot_finalizers_receive_incident_store_credentials() -> None:
    for name in (
        "openrouter-provider-activity-daily.yml",
        "asia-markets-dashboard-refresh-daily.yml",
        "semiconductor-memory-monthly.yml",
    ):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "OPS_INCIDENT_REPO: ${{ secrets.OPS_INCIDENT_REPO }}" in text
        assert "OPS_INCIDENT_TOKEN: ${{ secrets.OPS_INCIDENT_TOKEN }}" in text
        assert "self-hosted" not in text
