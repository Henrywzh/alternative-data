from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

from ops_control.baseline import extract_run_report, select_previous_artifact


def test_select_previous_artifact_excludes_current_run_and_expired_entries() -> None:
    artifacts = [
        {
            "id": 3,
            "name": "ops-shadow-pilot-300-1",
            "created_at": "2026-09-08T03:00:00Z",
            "expired": False,
            "workflow_run": {"id": 300},
        },
        {
            "id": 2,
            "name": "ops-shadow-pilot-200-1",
            "created_at": "2026-09-08T02:00:00Z",
            "expired": False,
            "workflow_run": {"id": 200},
        },
        {
            "id": 1,
            "name": "ops-shadow-pilot-100-1",
            "created_at": "2026-09-08T01:00:00Z",
            "expired": True,
            "workflow_run": {"id": 100},
        },
    ]

    selected = select_previous_artifact(
        artifacts,
        artifact_prefix="ops-shadow-pilot-",
        current_run_id="300",
    )

    assert selected is not None
    assert selected["id"] == 2


def test_extract_run_report_reads_only_the_report_from_artifact_zip() -> None:
    archive = BytesIO()
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("run-report.json", json.dumps({"schema_version": 1}))
        bundle.writestr("evidence-manifest.json", "{}")

    payload = extract_run_report(archive.getvalue())

    assert payload == {"schema_version": 1}
