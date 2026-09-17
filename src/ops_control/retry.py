from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .github_api import request_json
from .incidents import Incident, mark_retry_attempted


class RetryError(RuntimeError):
    pass


def retry_workflow_run(
    *,
    repository: str,
    token: str,
    run_id: str,
) -> dict[str, Any]:
    if not run_id or run_id.startswith("local-") or run_id.startswith("missed-"):
        raise RetryError(f"Cannot retry non-GitHub run_id {run_id!r}")
    return request_json(
        f"https://api.github.com/repos/{repository}/actions/runs/{run_id}/rerun-failed-jobs",
        token=token,
        method="POST",
        payload={},
    ) or {}


def maybe_retry_incident(
    *,
    incident: Incident,
    repository: str,
    token: str | None,
    now: datetime | None = None,
) -> tuple[Incident, bool]:
    if not incident.retry_eligible or incident.retry_attempted:
        return incident, False
    if not token:
        return incident, False
    run_id = next((item for item in reversed(incident.run_ids) if item.isdigit()), None)
    if run_id is None:
        return incident, False
    retry_workflow_run(repository=repository, token=token, run_id=run_id)
    updated = mark_retry_attempted(incident, now=now or datetime.now(timezone.utc))
    return updated, True
