"""Command-line entrypoint shared by local buttons and cloud executors."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

from .config import DEFAULT_COUNTRIES, LATEST_ARTIFACT_PATH
from .pipeline import run_pipeline
from .query import EventQueryService, QueryError


def _refresh_main(argv: list[str]) -> int:
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


def _add_query_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--artifact-path", type=Path, default=LATEST_ARTIFACT_PATH)
    parser.add_argument("--event-ledger-path", type=Path)
    parser.add_argument("--quote-ledger-path", type=Path)
    parser.add_argument("--component-ledger-path", type=Path)
    parser.add_argument("--format", choices=("json",), default="json")


def _query_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="event-consensus query",
        description="Read local event and consensus research data without refreshing sources.",
    )
    commands = parser.add_subparsers(dest="query_name", required=True)

    capabilities = commands.add_parser("capabilities", help="Describe the local query contract and available data.")
    _add_query_paths(capabilities)

    brief = commands.add_parser("brief", help="Return the next short-horizon event brief.")
    _add_query_paths(brief)
    brief.add_argument("--horizon-hours", type=int, default=48)
    brief.add_argument("--countries", nargs="+")
    brief.add_argument("--limit", type=int, default=10)

    event_list = commands.add_parser("list", help="List events with deterministic filters.")
    _add_query_paths(event_list)
    event_list.add_argument("--start-utc")
    event_list.add_argument("--end-utc")
    event_list.add_argument("--countries", nargs="+")
    event_list.add_argument("--priority", choices=("high", "medium", "low", "unknown"))
    event_list.add_argument("--event-family")
    event_list.add_argument("--checkpoint")
    event_list.add_argument("--released", action=argparse.BooleanOptionalAction, default=None)

    for name, help_text in (
        ("research", "Return the event research dossier."),
        ("history", "Return point-in-time observations for an event."),
        ("postmortem", "Return the post-release review for an event."),
    ):
        command = commands.add_parser(name, help=help_text)
        _add_query_paths(command)
        command.add_argument("--event-id", required=True)

    health = commands.add_parser("health", help="Return artifact and source-health status.")
    _add_query_paths(health)
    return parser


def _query_service(args: argparse.Namespace) -> EventQueryService:
    path_kwargs: dict[str, Any] = {}
    for argument, parameter in (
        ("event_ledger_path", "event_ledger_path"),
        ("quote_ledger_path", "quote_ledger_path"),
        ("component_ledger_path", "component_ledger_path"),
    ):
        value = getattr(args, argument, None)
        if value is not None:
            path_kwargs[parameter] = value
    return EventQueryService(
        artifact_path=args.artifact_path,
        **path_kwargs,
    )


def _query_callable(args: argparse.Namespace) -> Callable[[], dict[str, Any]]:
    service = _query_service(args)
    if args.query_name == "capabilities":
        return service.capabilities
    if args.query_name == "brief":
        return lambda: service.brief(
            horizon_hours=args.horizon_hours,
            countries=args.countries,
            limit=args.limit,
        )
    if args.query_name == "list":
        return lambda: service.list_events(
            start_utc=args.start_utc,
            end_utc=args.end_utc,
            countries=args.countries,
            priority=args.priority,
            event_family=args.event_family,
            checkpoint=args.checkpoint,
            released=args.released,
        )
    if args.query_name == "research":
        return lambda: service.research(args.event_id)
    if args.query_name == "history":
        return lambda: service.history(args.event_id)
    if args.query_name == "postmortem":
        return lambda: service.postmortem(args.event_id)
    if args.query_name == "health":
        return service.health
    raise QueryError(f"unsupported query: {args.query_name}")


def _query_main(argv: list[str]) -> int:
    args = _query_parser().parse_args(argv)
    try:
        payload = _query_callable(args)()
    except QueryError as exc:
        print(f"event-consensus query failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv[:1] == ["query"]:
        return _query_main(raw_argv[1:])
    if raw_argv[:1] == ["refresh"]:
        raw_argv = raw_argv[1:]
    return _refresh_main(raw_argv)


if __name__ == "__main__":
    raise SystemExit(main())
