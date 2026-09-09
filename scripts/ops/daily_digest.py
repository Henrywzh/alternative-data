#!/usr/bin/env python3
"""Build and optionally email the daily operations digest."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
    parser.add_argument("--incident-repo", default=os.environ.get("OPS_INCIDENT_REPO", ""))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--send-email", action="store_true")
    parser.add_argument("--weekly", action="store_true")
    args = parser.parse_args(argv)

    from ops_control.registry import load_registry
    from ops_control.reporting import build_digest, send_digest_email
    from ops_control.store import IncidentStore

    token = os.environ.get("OPS_INCIDENT_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
    if not args.incident_repo or not token:
        raise SystemExit("OPS_INCIDENT_REPO and GITHUB_TOKEN are required")
    registry = load_registry(args.registry, repo_root=REPO_ROOT)
    store = IncidentStore(
        repository=args.incident_repo,
        token=token,
        schema_path=REPO_ROOT / "schemas" / "ops" / "incident.schema.json",
    )
    incidents = store.list_recent(state="all")
    now = datetime.now(timezone.utc)
    body = build_digest(registry=registry, incidents=incidents, now=now, weekly=args.weekly)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(body, encoding="utf-8")
    print(body)
    if args.send_email:
        recipients = [
            item.strip()
            for item in os.environ.get("GMAIL_RECIPIENTS", os.environ.get("GMAIL_RECIPIENT", "")).split(",")
            if item.strip()
        ]
        send_digest_email(
            body=body,
            sender=os.environ.get("GMAIL_SENDER", ""),
            password=os.environ.get("GMAIL_APP_PASSWORD", ""),
            recipients=recipients,
            now=now,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
