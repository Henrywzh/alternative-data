from __future__ import annotations

import argparse
from pathlib import Path

from signal_layer.pipeline import SignalLayerPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Alternative-data signal layer pipeline")
    parser.add_argument("--base-dir", default=".", help="Repository root")
    parser.add_argument("--sources", help="Comma-separated sources to build")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-registry", help="Validate signal registry files")
    subparsers.add_parser("build", help="Build metric, asset, and theme signals")
    return parser


def _source_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> None:
    args = build_parser().parse_args()
    pipeline = SignalLayerPipeline(Path(args.base_dir).resolve())

    if args.command == "validate-registry":
        counts = pipeline.validate_registry()
        for key, value in counts.items():
            print(f"{key}: {value}")
        return

    if args.command == "build":
        result = pipeline.build(sources=_source_list(args.sources))
        print(f"run_id={result.run_id}")
        for dataset, rows in result.datasets_written.items():
            print(f"{dataset}: {rows} rows written")
        print(f"output_dir={result.output_dir}")
        return

    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
