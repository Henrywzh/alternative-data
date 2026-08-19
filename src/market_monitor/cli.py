"""CLI for the market_monitor daily pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date

import pandas as pd

from .alerts import build_email_html, send_report
from .pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="market-monitor", description="Index & ETF Allocation Monitor pipeline")
    parser.add_argument("--limit-exposures", nargs="*", default=None, help="Restrict to these exposure ids (for testing)")
    parser.add_argument("--etf-only", nargs="*", default=None, help="Restrict ETF fetches to these tickers")
    parser.add_argument("--start-date", default=None, help="YYYYMMDD start for history")
    parser.add_argument("--no-write", action="store_true", help="Run without persisting snapshots")
    parser.add_argument("--allow-partial-write", action="store_true", help="Allow persisting partial/test runs to disk")
    parser.add_argument("--send-report", action="store_true", help="Send the daily Gmail digest after running")
    args = parser.parse_args(argv)

    is_partial = bool(args.limit_exposures or args.etf_only)
    should_write = (not args.no_write) and (not is_partial or args.allow_partial_write)

    results = run_pipeline(
        limit_exposures=tuple(args.limit_exposures) if args.limit_exposures else None,
        etf_only=tuple(args.etf_only) if args.etf_only else None,
        start_date=args.start_date,
        write=should_write,
    )
    summary = {k: (int(v) if isinstance(v, int) else (len(v) if hasattr(v, "__len__") and not isinstance(v, str) else v)) for k, v in results.items() if k != "_run"}
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    if args.send_report:
        # Use the current in-memory run, not load_latest_derived(), to
        # guarantee the email always matches the pipeline result that was
        # just computed (never silently mixes old/new snapshots from disk).
        technicals = results.get("exposure_technicals", pd.DataFrame())
        regime = results.get("relative_regime", pd.DataFrame())
        wrappers = results.get("wrapper_metrics", pd.DataFrame())
        try:
            body = build_email_html(
                report_date=date.today().isoformat(),
                technicals=technicals,
                regime=regime,
                wrappers=wrappers,
            )
            send_report(subject=f"Index & ETF Allocation Monitor — {date.today().isoformat()}", body_html=body)
            print("daily Gmail digest sent")
        except Exception as exc:
            # Email is best-effort; pipeline/dashboard must never fail because
            # SMTP or Gmail credentials are unavailable.
            print(f"Warning: Gmail digest not sent ({exc})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
