from __future__ import annotations

from io import BytesIO
import json
import os
from pathlib import Path
from typing import Any, Iterable
from urllib.request import Request, urlopen
from zipfile import ZipFile


GITHUB_API = "https://api.github.com"


def select_previous_artifact(
    artifacts: Iterable[dict[str, Any]],
    *,
    artifact_prefix: str,
    current_run_id: str,
) -> dict[str, Any] | None:
    candidates = [
        artifact
        for artifact in artifacts
        if str(artifact.get("name", "")).startswith(artifact_prefix)
        and not bool(artifact.get("expired"))
        and str((artifact.get("workflow_run") or {}).get("id", ""))
        != current_run_id
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda artifact: str(artifact.get("created_at", "")))


def extract_run_report(archive: bytes) -> dict[str, Any]:
    with ZipFile(BytesIO(archive)) as bundle:
        matches = [
            name
            for name in bundle.namelist()
            if Path(name).name == "run-report.json"
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Expected one run-report.json in baseline artifact, found {len(matches)}"
            )
        payload = json.loads(bundle.read(matches[0]).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Baseline run report must be a JSON object")
    return payload


def fetch_previous_report(
    *,
    repository: str,
    token: str,
    current_run_id: str,
    artifact_prefix: str,
) -> dict[str, Any] | None:
    listing = _request_json(
        f"{GITHUB_API}/repos/{repository}/actions/artifacts?per_page=100",
        token=token,
    )
    artifact = select_previous_artifact(
        listing.get("artifacts", []),
        artifact_prefix=artifact_prefix,
        current_run_id=current_run_id,
    )
    if artifact is None:
        return None
    archive = _request_bytes(
        f"{GITHUB_API}/repos/{repository}/actions/artifacts/{artifact['id']}/zip",
        token=token,
    )
    return extract_run_report(archive)


def write_previous_report(
    *,
    artifact_prefix: str,
    output_path: Path,
) -> bool:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    current_run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not repository or not token or not current_run_id:
        raise RuntimeError(
            "GITHUB_REPOSITORY, GITHUB_TOKEN, and GITHUB_RUN_ID are required"
        )
    payload = fetch_previous_report(
        repository=repository,
        token=token,
        current_run_id=current_run_id,
        artifact_prefix=artifact_prefix,
    )
    if payload is None:
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return True


def _request_json(url: str, *, token: str) -> dict[str, Any]:
    payload = json.loads(_request_bytes(url, token=token).decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GitHub API response must be a JSON object")
    return payload


def _request_bytes(url: str, *, token: str) -> bytes:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "alternative-data-ops-control",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=30) as response:
        return response.read()
