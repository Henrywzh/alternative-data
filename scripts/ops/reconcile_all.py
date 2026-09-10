#!/usr/bin/env python3
"""Reconcile registered pipelines and upsert incidents."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REPO_ROOT / "config" / "ops" / "pipelines.yaml")
    parser.add_argument("--schema", type=Path, default=REPO_ROOT / "schemas" / "ops" / "incident.schema.json")
    parser.add_argument("--producer-repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--incident-repo", default=os.environ.get("OPS_INCIDENT_REPO", ""))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    from ops_control.github_api import paginate, request_json
    from ops_control.reconcile import collect_latest_reports, reconcile_registry
    from ops_control.registry import load_registry
    from ops_control.retry import maybe_retry_incident
    from ops_control.store import IncidentStore

    producer_token = os.environ.get("GITHUB_TOKEN", "").strip()
    incident_token = os.environ.get("OPS_INCIDENT_TOKEN", "").strip()
    if not args.producer_repo or not producer_token:
        raise SystemExit("GITHUB_REPOSITORY and GITHUB_TOKEN are required")
    registry = load_registry(args.registry, repo_root=REPO_ROOT)
    artifacts = paginate(
        f"https://api.github.com/repos/{args.producer_repo}/actions/artifacts",
        token=producer_token,
        params={"per_page": 100},
    )

    def download_artifact(artifact: dict) -> bytes:
        from ops_control.github_api import request_json as _unused
        from urllib.request import Request, urlopen
        request = Request(
            f"https://api.github.com/repos/{args.producer_repo}/actions/artifacts/{artifact['id']}/zip",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {producer_token}",
                "User-Agent": "alternative-data-ops-control",
            },
        )
        with urlopen(request, timeout=30) as response:
            return response.read()

    reports = collect_latest_reports(registry=registry, artifacts=artifacts, download_artifact=download_artifact)
    now = datetime.now(timezone.utc)
    incidents = reconcile_registry(registry=registry, reports=reports, now=now)
    stored = []
    if args.incident_repo and incident_token:
        store = IncidentStore(repository=args.incident_repo, token=incident_token, schema_path=args.schema)
        for incident in incidents:
            current = store.upsert(incident)
            current, retried = maybe_retry_incident(
                incident=current,
                repository=args.producer_repo,
                token=producer_token,
                now=now,
            )
            if retried:
                current = store.upsert(current)
            stored.append(current.to_dict())
    else:
        stored = [item.to_dict() for item in incidents]
    payload = {"generated_at": now.isoformat().replace("+00:00", "Z"), "incident_count": len(stored), "incidents": stored}
    rendered = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
