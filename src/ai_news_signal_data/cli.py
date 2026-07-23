from __future__ import annotations

import argparse
from pathlib import Path

from ai_news_signal_data.pipeline import AiNewsSignalPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI news guard+engine triage and daily brief email")
    parser.add_argument("--base-dir", default=".", help="Repository root")
    parser.add_argument("--run-date", default=None, help="YYYY-MM-DD, defaults to today (UTC)")
    parser.add_argument(
        "--send-email",
        action="store_true",
        help="Actually send the Gmail digest (default: dry-run, prints the brief only)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Cap the number of candidates sent to the guard (sampled across sources) for a fast preview run",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    base_dir = Path(args.base_dir).resolve()
    pipeline = AiNewsSignalPipeline(base_dir)
    result = pipeline.run(run_date=args.run_date, send=args.send_email, limit=args.limit)

    print(
        f"candidates={result.candidates} guard_tagged={result.guard_tagged} "
        f"high_importance={result.high_importance} trending_flagged={result.trending_flagged}"
    )
    print()
    print(result.brief.get("overall_summary", ""))
    for item in result.brief.get("items", []):
        print(f"- {item.get('headline')}: {item.get('analysis')}")

    if not args.send_email:
        print("\n(dry-run: pass --send-email to actually send the Gmail digest)")


if __name__ == "__main__":
    main()
