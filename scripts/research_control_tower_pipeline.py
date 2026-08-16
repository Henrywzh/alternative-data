#!/usr/bin/env python3
"""Single entry point that makes a Research Control Tower bundle reproducible
from the repository.

Background
----------
``src/research_control_tower/cli.py`` takes every optional input as a
repeated ``--<kind>-input "source_id|path|format|schema_id"`` flag with no
discovery and no declared set -- whatever the operator typed by hand is what
got built. That is how bundle ``b23-live-20260816T0420Z`` shipped without
``--quote-input``: ``quote_snapshots.parquet`` came out with 0 rows and every
Stage 1 listing rendered ``unavailable`` in production, while the build still
reported ``degraded`` and published anyway.

This script closes that gap:

1. (optionally, with ``--collect``) runs the four external collectors,
   writing their standardized local inputs to a controlled in-repo
   directory instead of an ephemeral ``/tmp`` path;
2. reads ``config/research_control_tower/build_inputs.toml`` -- the
   versioned declaration of which data layers this build should contain --
   and expands it into the full set of ``--<kind>-input`` descriptors;
3. in ``--strict`` mode, verifies every ``required = true`` input exists and
   is non-empty *before* invoking the builder, failing with a clear message
   naming the missing layer instead of silently publishing a degraded
   bundle;
4. invokes the existing builder (``research_control_tower.cli.main``), which
   still runs with ``network_policy: forbidden`` -- collection and building
   stay architecturally separate.

Usage
-----
    # Use already-committed inputs, no network calls, publish if healthy:
    python scripts/research_control_tower_pipeline.py --skip-collect

    # Fail fast if a required data layer is missing/empty:
    python scripts/research_control_tower_pipeline.py --skip-collect --strict

    # Refresh every collector over the network, then build:
    python scripts/research_control_tower_pipeline.py --collect --strict
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

# Make direct ``python scripts/...`` execution resolve the repository package
# without requiring an editable install (mirrors the four collector scripts).
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - repo requires-python is >=3.11
    import tomli as tomllib  # type: ignore[no-redef]

from src.research_control_tower.build import BuildError
from src.research_control_tower.cli import main as cli_main

DEFAULT_BUILD_INPUTS_TOML = REPO_ROOT / "config" / "research_control_tower" / "build_inputs.toml"
DEFAULT_REGISTRY_ROOT = REPO_ROOT / "config" / "research_control_tower"
DEFAULT_EVENT_ROOT = REPO_ROOT / "config" / "research_control_tower"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "apps" / "research-control-tower" / ".generated"
DEFAULT_COLLECT_OUTPUT_DIR = REPO_ROOT / "data" / "normalized" / "research_control_tower"

DEFAULT_LISTINGS = DEFAULT_REGISTRY_ROOT / "listings.csv"
DEFAULT_ENTITIES = DEFAULT_REGISTRY_ROOT / "entities.csv"
DEFAULT_BASKETS = DEFAULT_REGISTRY_ROOT / "baskets.csv"
DEFAULT_BASKET_MEMBERSHIPS = DEFAULT_REGISTRY_ROOT / "basket_memberships.csv"
DEFAULT_SOURCE_IDENTITY = DEFAULT_REGISTRY_ROOT / "official_source_identity.csv"

# Maps a build_inputs.toml [[input]] "kind" to the matching cli.py flag.
KIND_TO_FLAG = {
    "quote": "--quote-input",
    "official_filing": "--official-filing-input",
    "earnings": "--earnings-input",
    "macro": "--macro-input",
    "news": "--news-input",
    "filing": "--filing-input",
}


class PipelineError(RuntimeError):
    """Raised for pipeline-level failures (bad manifest, missing required input)."""


@dataclass(frozen=True)
class InputDescriptor:
    """One row of ``build_inputs.toml``, resolved to an absolute path."""

    kind: str
    source_id: str
    path: Path
    format: str
    schema_id: str
    required: bool
    description: str = ""

    def as_cli_value(self) -> str:
        """Render as the ``SOURCE_ID|PATH|FORMAT|SCHEMA_ID`` string cli.py expects."""

        return f"{self.source_id}|{self.path}|{self.format}|{self.schema_id}"


@dataclass(frozen=True)
class BuildInputsManifest:
    """The parsed contents of ``build_inputs.toml``."""

    descriptors: list[InputDescriptor]
    required_kinds: tuple[str, ...]


def load_build_inputs(toml_path: Path, *, repo_root: Path = REPO_ROOT) -> BuildInputsManifest:
    """Parse ``build_inputs.toml`` into a :class:`BuildInputsManifest`.

    Paths in the file are repo-relative; they are resolved against
    ``repo_root`` here so the returned descriptors are usable regardless of
    the caller's current working directory.
    """

    if not toml_path.is_file():
        raise PipelineError(f"build inputs manifest not found: {toml_path}")
    with toml_path.open("rb") as handle:
        try:
            document = tomllib.load(handle)
        except tomllib.TOMLDecodeError as exc:
            raise PipelineError(f"{toml_path} is not valid TOML: {exc}") from exc

    required_kinds = tuple(str(kind) for kind in document.get("required_kinds", []))
    unknown_kinds = set(required_kinds) - set(KIND_TO_FLAG)
    if unknown_kinds:
        raise PipelineError(
            f"{toml_path}: required_kinds has unknown kind(s): {sorted(unknown_kinds)}"
        )

    rows = document.get("input", [])
    if not isinstance(rows, list):
        raise PipelineError(f"{toml_path}: [[input]] must be an array of tables")

    descriptors: list[InputDescriptor] = []
    seen_source_ids: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise PipelineError(f"{toml_path}: input row #{index} is not a table")
        missing_keys = {"kind", "source_id", "path", "format", "schema_id"} - row.keys()
        if missing_keys:
            raise PipelineError(
                f"{toml_path}: input row #{index} is missing required key(s): "
                + ", ".join(sorted(missing_keys))
            )
        kind = str(row["kind"])
        if kind not in KIND_TO_FLAG:
            raise PipelineError(
                f"{toml_path}: input row #{index} has unknown kind {kind!r}; "
                f"must be one of {sorted(KIND_TO_FLAG)}"
            )
        source_id = str(row["source_id"])
        if source_id in seen_source_ids:
            raise PipelineError(f"{toml_path}: duplicate source_id {source_id!r}")
        seen_source_ids.add(source_id)
        raw_path = Path(str(row["path"]))
        resolved_path = raw_path if raw_path.is_absolute() else (repo_root / raw_path)
        descriptors.append(
            InputDescriptor(
                kind=kind,
                source_id=source_id,
                path=resolved_path,
                format=str(row["format"]),
                schema_id=str(row["schema_id"]),
                required=bool(row.get("required", False)),
                description=str(row.get("description", "")),
            )
        )
    return BuildInputsManifest(descriptors=descriptors, required_kinds=required_kinds)


def _is_non_empty(descriptor: InputDescriptor) -> tuple[bool, str]:
    """Return ``(ok, reason)``. ``ok`` is False if the file is missing or empty."""

    path = descriptor.path
    if not path.exists():
        return False, "file does not exist"
    if not path.is_file():
        return False, "path is not a regular file"
    if path.stat().st_size == 0:
        return False, "file is empty (0 bytes)"

    try:
        if descriptor.format == "parquet":
            import pandas as pd

            frame = pd.read_parquet(path)
            if len(frame) == 0:
                return False, "parquet file has 0 rows"
        elif descriptor.format == "csv":
            import pandas as pd

            frame = pd.read_csv(path)
            if len(frame) == 0:
                return False, "csv file has 0 data rows"
        elif descriptor.format == "json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload in ({}, [], None):
                return False, "json file has no content"
        elif descriptor.format == "jsonl":
            lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            if not lines:
                return False, "jsonl file has 0 records"
    except Exception as exc:  # noqa: BLE001 - surfaced as a clear pipeline failure
        return False, f"could not be read as {descriptor.format}: {exc}"
    return True, ""


def verify_required_inputs(manifest: BuildInputsManifest) -> list[str]:
    """Check the manifest for missing required layers; return failure messages.

    Two independent checks, because they guard against two different ways a
    layer can go missing:

    1. Per-row ``required = true``: the row is still declared in
       build_inputs.toml, but its file is missing, empty, or unreadable
       (e.g. a collector sidecar that never got written).
    2. Manifest-level ``required_kinds``: the *entire* ``[[input]]`` block
       for a required kind has been deleted from build_inputs.toml (e.g.
       dropping every ``kind = "quote"`` row), so there is nothing left to
       even check row-by-row. This is exactly the shape of the
       b23-live-20260816T0420Z regression: ``--quote-input`` was never
       passed at all, not passed-but-broken.
    """

    failures: list[str] = []
    for descriptor in manifest.descriptors:
        if not descriptor.required:
            continue
        ok, reason = _is_non_empty(descriptor)
        if not ok:
            failures.append(
                f"required input missing for layer '{descriptor.source_id}' "
                f"(kind={descriptor.kind}, schema={descriptor.schema_id}): "
                f"{reason} -- expected at {descriptor.path}"
            )

    descriptors_by_kind: dict[str, list[InputDescriptor]] = {}
    for descriptor in manifest.descriptors:
        descriptors_by_kind.setdefault(descriptor.kind, []).append(descriptor)
    for kind in manifest.required_kinds:
        kind_descriptors = descriptors_by_kind.get(kind, [])
        if not kind_descriptors:
            failures.append(
                f"required data layer kind '{kind}' has no declared input in "
                "build_inputs.toml at all (its [[input]] block was removed, or "
                "never added) -- this is the b23-live-20260816T0420Z regression shape: "
                "a data layer silently missing from the build"
            )
        elif not any(_is_non_empty(descriptor)[0] for descriptor in kind_descriptors):
            failures.append(
                f"required data layer kind '{kind}' has {len(kind_descriptors)} declared "
                "input(s) but none of them are present and non-empty"
            )
    return failures


def expand_to_cli_args(descriptors: list[InputDescriptor]) -> list[str]:
    """Expand descriptors into the ``--<kind>-input VALUE`` argv fragments cli.py expects."""

    argv: list[str] = []
    for descriptor in descriptors:
        argv.extend([KIND_TO_FLAG[descriptor.kind], descriptor.as_cli_value()])
    return argv


def default_build_id(as_of_utc: datetime) -> str:
    """Derive a build id from ``as_of_utc`` so repeated builds do not collide.

    Example: 2026-08-17T04:00:00Z -> "rtc-20260817T0400Z".
    """

    return f"rtc-{as_of_utc.strftime('%Y%m%dT%H%M')}Z"


def _run_collector(description: str, argv: list[str]) -> None:
    print(f"[collect] {description}: {' '.join(str(a) for a in argv)}")
    result = subprocess.run([sys.executable, *[str(a) for a in argv]], cwd=REPO_ROOT)
    if result.returncode != 0:
        raise PipelineError(f"{description} exited with status {result.returncode}")


def run_collectors(args: argparse.Namespace, *, collect_output_dir: Path) -> None:
    """Run the four external collectors, writing outputs under ``collect_output_dir``.

    Collectors perform network I/O; the build step that follows runs with
    ``network_policy: forbidden`` and never touches the network itself. This
    function is the only place in the pipeline that may reach out to the
    network.
    """

    collect_output_dir.mkdir(parents=True, exist_ok=True)
    as_of_args = ["--as-of-utc", args.as_of_utc] if args.as_of_utc else []

    _run_collector(
        "quote_collector",
        [
            REPO_ROOT / "scripts" / "research_control_tower_quote_collector.py",
            "--listings", args.listings,
            "--entities", args.entities,
            "--baskets", args.baskets,
            "--basket-memberships", args.basket_memberships,
            "--output", collect_output_dir / "quote_snapshots.parquet",
            *as_of_args,
        ],
    )
    _run_collector(
        "official_filings",
        [
            REPO_ROOT / "scripts" / "research_control_tower_official_filings.py",
            "--identity", args.source_identity,
            "--output-dir", collect_output_dir,
            *as_of_args,
        ],
    )
    _run_collector(
        "earnings_actuals",
        [
            REPO_ROOT / "scripts" / "research_control_tower_earnings_actuals.py",
            "--identity", args.source_identity,
            "--output-dir", collect_output_dir,
            *as_of_args,
        ],
    )
    macro_argv = [
        REPO_ROOT / "scripts" / "research_control_tower_macro_collector.py",
        "--output-dir", collect_output_dir,
        "--output-events", collect_output_dir / "macro_events.parquet",
        "--output-observations", collect_output_dir / "macro_observations.parquet",
        "--output-health", collect_output_dir / "macro_source_health.json",
        *as_of_args,
    ]
    if args.macro_indicators:
        macro_argv.extend(["--indicators", *args.macro_indicators])
    _run_collector("macro_collector", macro_argv)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="research-control-tower-pipeline",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    collect_group = parser.add_mutually_exclusive_group()
    collect_group.add_argument(
        "--collect",
        dest="collect",
        action="store_true",
        help="run the four external collectors before building (network I/O)",
    )
    collect_group.add_argument(
        "--skip-collect",
        dest="collect",
        action="store_false",
        help="do not run collectors; build from whatever is already at --collect-output-dir "
        "(default)",
    )
    parser.set_defaults(collect=False)

    parser.add_argument(
        "--strict",
        action="store_true",
        default=False,
        help="before invoking the build, fail if any input declared required=true in "
        "build_inputs.toml is missing or empty (this is the pipeline's own pre-flight "
        "gate; see --allow-degraded-optional for the builder's own completeness gate)",
    )
    parser.add_argument(
        "--allow-degraded-optional",
        dest="allow_degraded_optional",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="forwarded to the builder as --allow-degraded-optional/--strict (default: "
        "true). Setting --no-allow-degraded-optional requires every optional input the "
        "builder knows about -- not just the ones required=true in build_inputs.toml -- "
        "to be configured and healthy; see BuildConfig.allow_degraded_optional.",
    )

    parser.add_argument(
        "--build-inputs-toml", type=Path, default=DEFAULT_BUILD_INPUTS_TOML,
        help=f"path to the declarative input manifest (default: {DEFAULT_BUILD_INPUTS_TOML})",
    )
    parser.add_argument("--registry-root", type=Path, default=DEFAULT_REGISTRY_ROOT)
    parser.add_argument("--event-root", type=Path, default=DEFAULT_EVENT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--consensus-export-dir", type=Path, default=None)
    parser.add_argument(
        "--as-of-utc", default=None,
        help="ISO-8601 UTC timestamp for the build and (if --collect) the collectors; "
        "defaults to the current UTC time",
    )
    parser.add_argument(
        "--build-id", default=None,
        help="defaults to rtc-<as-of-utc as YYYYMMDDTHHMMZ>, e.g. rtc-20260817T0400Z, so "
        "repeated builds do not collide on generation id",
    )

    parser.add_argument(
        "--collect-output-dir", type=Path, default=DEFAULT_COLLECT_OUTPUT_DIR,
        help="where collectors write their standardized local inputs, and where "
        "build_inputs.toml's committed paths normally point (default: "
        f"{DEFAULT_COLLECT_OUTPUT_DIR})",
    )
    parser.add_argument("--listings", type=Path, default=DEFAULT_LISTINGS)
    parser.add_argument("--entities", type=Path, default=DEFAULT_ENTITIES)
    parser.add_argument("--baskets", type=Path, default=DEFAULT_BASKETS)
    parser.add_argument("--basket-memberships", type=Path, default=DEFAULT_BASKET_MEMBERSHIPS)
    parser.add_argument("--source-identity", type=Path, default=DEFAULT_SOURCE_IDENTITY)
    parser.add_argument(
        "--macro-indicators", nargs="*", default=None,
        help="optional subset of macro indicators to collect (default: all)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    as_of_dt = (
        datetime.fromisoformat(args.as_of_utc.replace("Z", "+00:00"))
        if args.as_of_utc
        else datetime.now(timezone.utc)
    )
    as_of_dt = as_of_dt.astimezone(timezone.utc)
    as_of_str = args.as_of_utc or as_of_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    build_id = args.build_id or default_build_id(as_of_dt)

    if args.collect:
        args.as_of_utc = as_of_str
        try:
            run_collectors(args, collect_output_dir=args.collect_output_dir)
        except PipelineError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    try:
        manifest = load_build_inputs(args.build_inputs_toml)
    except PipelineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.strict:
        failures = verify_required_inputs(manifest)
        if failures:
            print(
                f"error: --strict pre-flight check failed ({len(failures)} problem(s)); "
                "refusing to invoke the build:",
                file=sys.stderr,
            )
            for failure in failures:
                print(f"  - {failure}", file=sys.stderr)
            return 1
        print(
            f"[strict] {len(manifest.descriptors)} declared input(s) and "
            f"{len(manifest.required_kinds)} required kind(s) checked; all required layers present."
        )

    build_argv: list[str] = [
        "build",
        "--registry-root", str(args.registry_root),
        "--event-root", str(args.event_root),
        "--output-dir", str(args.output_dir),
        "--as-of-utc", as_of_str,
        "--build-id", build_id,
    ]
    if args.consensus_export_dir is not None:
        build_argv += ["--consensus-export-dir", str(args.consensus_export_dir)]
    build_argv += expand_to_cli_args(manifest.descriptors)
    if not args.allow_degraded_optional:
        build_argv += ["--strict"]

    print(f"[build] research-control-tower {' '.join(build_argv)}")
    try:
        return cli_main(build_argv)
    except BuildError as exc:
        print(f"error: build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
