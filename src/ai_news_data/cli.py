from __future__ import annotations

import argparse
from pathlib import Path

from ai_news_data.pipeline import AiNewsPipeline, PipelineResult


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI/LLM release news alternative-data ingestion pipeline")
    parser.add_argument("--base-dir", default=".", help="Repository root for data writes")
    parser.add_argument(
        "--sources",
        default="all",
        help="Comma-separated: huggingface,hackernews,reddit,blogs (default: all)",
    )
    return parser


def _print_result(name: str, result: PipelineResult) -> None:
    print(f"== {name} == run_id={result.run_id}")
    for dataset_id, rows in result.datasets_written.items():
        print(f"  {dataset_id}: {rows} rows")


def main() -> None:
    args = build_parser().parse_args()
    base_dir = Path(args.base_dir).resolve()
    pipeline = AiNewsPipeline(base_dir)

    names = list(pipeline.sources.keys()) if args.sources == "all" else [s.strip() for s in args.sources.split(",")]

    # One source failing (e.g. Reddit rate-limiting) must not stop the rest
    # from running and writing their updates.
    failures: dict[str, str] = {}
    for name in names:
        try:
            _print_result(name, pipeline.run_source(name))
        except Exception as exc:
            failures[name] = str(exc)
            print(f"== {name} == FAILED: {exc}")

    if failures:
        raise SystemExit(f"{len(failures)}/{len(names)} source(s) failed: {list(failures)}")


if __name__ == "__main__":
    main()
