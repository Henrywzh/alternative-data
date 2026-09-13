from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path

from ops_control.incidents import missed_schedule_incident
from ops_control.models import CheckResult, RunReport
from ops_control.registry import load_registry


ROOT = Path(__file__).resolve().parents[2]


def _healthy_report() -> RunReport:
    finished_at = "2026-09-13T10:12:14Z"
    return RunReport(
        pipeline_id="openrouter-provider-activity",
        job_id="scrape-provider-activity",
        workflow="OpenRouter Provider Activity Daily",
        run_id="healthy-1",
        run_attempt=1,
        commit_sha="abc",
        started_at=finished_at,
        finished_at=finished_at,
        execution="success",
        collection="complete",
        data_health="fresh",
        publication="published",
        evidence_quality="verified",
        derived_state="HEALTHY",
        checks=[CheckResult(check_id="ok", status="healthy", required=True, message="ok")],
        outputs=[],
        evidence=[],
        shadow=True,
    )


def test_reconcile_script_closes_open_issue_when_report_is_healthy(monkeypatch, capsys) -> None:
    """The CLI must persist recovery updates, not only current failures."""

    spec = importlib.util.spec_from_file_location(
        "ops_reconcile_script",
        ROOT / "scripts" / "ops" / "reconcile_all.py",
    )
    assert spec is not None and spec.loader is not None
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    registry = load_registry(ROOT / "config" / "ops" / "pipelines.yaml", repo_root=ROOT)
    existing = missed_schedule_incident(
        pipeline=registry.pipelines["openrouter-provider-activity"],
        job_id="scrape-provider-activity",
        now=datetime(2026, 9, 8, 12, 0, tzinfo=timezone.utc),
        last_finished_at=None,
    )
    report = _healthy_report()
    stores = []

    class FakeStore:
        def __init__(self, **_kwargs) -> None:
            self.upserts = []
            stores.append(self)

        def list_open(self):
            return [existing]

        def upsert(self, incident):
            self.upserts.append(incident)
            return incident

    monkeypatch.setenv("GITHUB_REPOSITORY", "Henrywzh/alternative-data")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_test")
    monkeypatch.setenv("OPS_INCIDENT_REPO", "Henrywzh/alternative-data-ops")
    monkeypatch.setenv("OPS_INCIDENT_TOKEN", "github_pat_test")
    monkeypatch.setattr("ops_control.github_api.paginate", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "ops_control.reconcile.collect_latest_reports",
        lambda **_kwargs: {(report.pipeline_id, report.job_id): report},
    )
    monkeypatch.setattr("ops_control.reconcile.reconcile_registry", lambda **_kwargs: [])
    monkeypatch.setattr("ops_control.store.IncidentStore", FakeStore)

    assert script.main(["--incident-repo", "Henrywzh/alternative-data-ops"]) == 0
    capsys.readouterr()

    assert len(stores) == 1
    assert len(stores[0].upserts) == 1
    assert stores[0].upserts[0].fingerprint == existing.fingerprint
    assert stores[0].upserts[0].status == "RECOVERED"
