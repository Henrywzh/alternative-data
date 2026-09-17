"""Command-line entrypoint shared by local buttons and cloud executors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import DEFAULT_COUNTRIES, LATEST_ARTIFACT_PATH
from .pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="event-consensus",
        description="Refresh the PIT macro event and consensus artifact.",
    )
    parser.add_argument(
        "--trigger",
        choices=("scheduled", "event_window", "manual", "cloud_backup"),
        default="scheduled",
    )
    parser.add_argument("--from-date")
    parser.add_argument("--to-date")
    parser.add_argument("--countries", nargs="+", default=list(DEFAULT_COUNTRIES))
    parser.add_argument("--no-quotes", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument(
        "--artifact-path",
        type=Path,
        default=LATEST_ARTIFACT_PATH,
    )
    args = parser.parse_args(argv)

    result = run_pipeline(
        trigger_type=args.trigger,
        from_date=args.from_date,
        to_date=args.to_date,
        countries=args.countries,
        include_quotes=not args.no_quotes,
        write=not args.no_write,
        artifact_path=args.artifact_path,
    )
    artifact = result["artifact"]
    print(
        json.dumps(
            {
                "status": artifact.get("status"),
                "generated_at_utc": artifact.get("generated_at_utc"),
                "events": len(artifact.get("events", [])),
                "quotes": len(artifact.get("quotes", [])),
                "content_hash": artifact.get("content_hash"),
                "artifact_path": result["artifact_path"],
                "used_previous_artifact": result.get("used_previous_artifact", False),
                "source_health": artifact.get("source_health", []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    # A degraded run that retained a prior artifact is operationally useful:
    # the source-health rows carry the failure, while CI still archives the
    # last valid timeline. Fail only when this is a first run with no events
    # and no prior artifact to retain.
    return 0 if artifact.get("events") or result.get("used_previous_artifact") else 2


if __name__ == "__main__":
    raise SystemExit(main())
