from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from .github_api import paginate, request_json
from .incidents import Incident, merge_incident, redact_incident, validate_incident
from .redaction import redact_text


class IncidentStore:
    """Persist incidents as GitHub issues in a private ops repository."""

    def __init__(
        self,
        *,
        repository: str,
        token: str,
        schema_path: Path,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not repository or "/" not in repository:
            raise ValueError("Incident store requires owner/name repository")
        self.repository = repository
        self.token = token
        self.schema_path = schema_path
        self._now = now or (lambda: datetime.now(timezone.utc))

    def upsert(self, incident: Incident) -> Incident:
        sanitized = redact_incident(incident)
        existing = self.find_by_fingerprint(sanitized.fingerprint)
        merged = sanitized if existing is None else merge_incident(existing, sanitized)
        validate_incident(merged.to_dict(), self.schema_path)
        body = _issue_body(merged)
        title = merged.title[:240]
        labels = _labels(merged)
        if existing is None or existing.issue_url is None:
            created = request_json(
                f"https://api.github.com/repos/{self.repository}/issues",
                token=self.token,
                method="POST",
                payload={"title": title, "body": body, "labels": labels},
            )
            merged = Incident.from_dict({**merged.to_dict(), "issue_url": str(created["html_url"])})
        else:
            number = existing.issue_url.rstrip("/").split("/")[-1]
            request_json(
                f"https://api.github.com/repos/{self.repository}/issues/{number}",
                token=self.token,
                method="PATCH",
                payload={
                    "title": title,
                    "body": body,
                    "state": "closed" if merged.status in {"RECOVERED", "CLOSED"} else "open",
                    "labels": labels,
                },
            )
            merged = Incident.from_dict({**merged.to_dict(), "issue_url": existing.issue_url})
        return merged

    def find_by_fingerprint(self, fingerprint: str) -> Incident | None:
        query = (
            f'repo:{self.repository} label:ops-incident '
            f'"fingerprint: {fingerprint}" in:body'
        )
        items = paginate(
            "https://api.github.com/search/issues",
            token=self.token,
            params={"q": query},
        )
        for item in items:
            parsed = parse_issue(item)
            if parsed is not None and parsed.fingerprint == fingerprint:
                return parsed
        return None

    def find_open_for_job(self, pipeline_id: str, job_id: str) -> list[Incident]:
        return [
            item
            for item in self.list_open()
            if item.pipeline_id == pipeline_id and item.job_id == job_id
        ]

    def list_open(self) -> list[Incident]:
        items = paginate(
            f"https://api.github.com/repos/{self.repository}/issues",
            token=self.token,
            params={"state": "open", "labels": "ops-incident"},
        )
        return [parsed for item in items if (parsed := parse_issue(item)) is not None]

    def list_recent(self, *, state: str = "all") -> list[Incident]:
        items = paginate(
            f"https://api.github.com/repos/{self.repository}/issues",
            token=self.token,
            params={"state": state, "labels": "ops-incident"},
        )
        return [parsed for item in items if (parsed := parse_issue(item)) is not None]


def parse_issue(item: dict[str, Any]) -> Incident | None:
    body = str(item.get("body") or "")
    marker = "```json\nops-incident\n"
    if marker not in body:
        return None
    encoded = body.split(marker, 1)[1]
    encoded = encoded.split("```", 1)[0]
    payload = json.loads(encoded)
    if not payload.get("issue_url"):
        payload["issue_url"] = item.get("html_url")
    return Incident.from_dict(payload)


def _issue_body(incident: Incident) -> str:
    payload = json.dumps(incident.to_dict(), indent=2, ensure_ascii=False, sort_keys=True)
    observed = "\n".join(f"- {item}" for item in incident.observed) or "- none"
    inferred = "\n".join(f"- {item}" for item in incident.inferred) or "- none"
    unknown = "\n".join(f"- {item}" for item in incident.unknown) or "- none"
    summary = redact_text(incident.summary)
    return (
        f"<!-- ops-incident:{incident.fingerprint} -->\n"
        f"fingerprint: {incident.fingerprint}\n\n"
        f"{summary}\n\n"
        f"**Observed**\n{observed}\n\n"
        f"**Inferred**\n{inferred}\n\n"
        f"**Unknown**\n{unknown}\n\n"
        f"```json\nops-incident\n{payload}\n```\n"
    )


def _labels(incident: Incident) -> list[str]:
    labels = [
        "ops-incident",
        f"pipeline:{incident.pipeline_id}",
        f"status:{incident.status.lower()}",
    ]
    if incident.retry_eligible:
        labels.append("retry-eligible")
    if incident.needs_human:
        labels.append("needs-human")
    if incident.needs_local:
        labels.append("needs-local")
    return labels
