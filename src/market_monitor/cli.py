"""CLI for the market_monitor daily pipeline."""

from __future__ import annotations

import argparse
import json
import sys

import pandas as pd

from .alerts import build_email_html, generate_sparkline_chart, send_report
from .freshness import BLOCKING_FRESHNESS_STATUSES, market_date
from .pipeline import run_intraday_snapshot, run_pipeline


# One entry per chart embedded in the digest. The email renders an ETF card
# for each of these, so a card without its chart reads as a missing chart
# rather than a deliberate omission -- keep the two lists in step.
EMAIL_CHART_SERIES: tuple[tuple[str, str, str], ...] = (
    ("csi300", "CSI 300 (沪深300) — 60D Trend & 20D MA", "#7c3aed"),
    ("csi500", "CSI 500 (中证500) — 60D Trend & 20D MA", "#2563eb"),
    ("sp500", "S&P 500 (标普500) — 60D Trend & 20D MA", "#0284c7"),
)


def _freshness_blockers(freshness: dict[str, object], *, mode: str) -> list[str]:
    """Return blocking freshness/coverage issues before an email is sent."""
    records: list[tuple[str, dict[str, object]]] = []
    if mode == "intraday":
        records.append(("ETF spot", freshness.get("quote", {}) or {}))
    else:
        records.extend(
            [
                ("daily close", freshness.get("daily_close", {}) or {}),
                ("ETF spot", freshness.get("quote", {}) or {}),
            ]
        )
        for group, record in sorted((freshness.get("daily_close_by_region", {}) or {}).items()):
            records.append((f"region {group}", record or {}))
        for group, record in sorted((freshness.get("daily_close_by_source", {}) or {}).items()):
            records.append((f"source {group}", record or {}))

    blockers = [
        f"{scope}: {record.get('status')}"
        for scope, record in records
        if str(record.get("status")) in BLOCKING_FRESHNESS_STATUSES
    ]
    regressions = freshness.get("coverage_regressions") or []
    if regressions:
        blockers.append("coverage regression: " + "; ".join(str(item) for item in regressions[:6]))
    return blockers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="market-monitor", description="Index & ETF Allocation Monitor pipeline")
    parser.add_argument("--limit-exposures", nargs="*", default=None, help="Restrict to these exposure ids (for testing)")
    parser.add_argument("--etf-only", nargs="*", default=None, help="Restrict ETF fetches to these tickers")
    parser.add_argument("--start-date", default=None, help="YYYYMMDD start for history")
    parser.add_argument("--no-write", action="store_true", help="Run without persisting snapshots")
    parser.add_argument("--allow-partial-write", action="store_true", help="Allow persisting partial/test runs to disk")
    parser.add_argument("--send-report", action="store_true", help="Send the daily Gmail digest after running")
    parser.add_argument("--recipient", default=None, help="Override recipient email address")
    parser.add_argument(
        "--mode",
        choices=("close", "intraday"),
        default="close",
        help="close persists daily completed-session data; intraday fetches a non-persistent live quote snapshot",
    )
    parser.add_argument(
        "--require-fresh",
        action="store_true",
        help="Fail before sending when selected data has unavailable, stale, invalid or regressed coverage",
    )
    parser.add_argument(
        "--allow-stale-artifact",
        action="store_true",
        help="For close mode, skip the email but let the dashboard artifact build from the degraded run",
    )
    args = parser.parse_args(argv)

    is_partial = bool(args.limit_exposures or args.etf_only)
    should_write = args.mode == "close" and (not args.no_write) and (not is_partial or args.allow_partial_write)

    if args.allow_stale_artifact and args.mode != "close":
        parser.error("--allow-stale-artifact is only valid with --mode close")

    if args.mode == "intraday":
        # Intraday mode never writes the daily store and does not accept
        # historical-scope arguments that would imply a completed bar.
        if is_partial or args.start_date:
            parser.error("--mode intraday cannot be combined with --limit-exposures, --etf-only, or --start-date")
        results = run_intraday_snapshot()
    else:
        results = run_pipeline(
            limit_exposures=tuple(args.limit_exposures) if args.limit_exposures else None,
            etf_only=tuple(args.etf_only) if args.etf_only else None,
            start_date=args.start_date,
            write=should_write,
        )
    summary = {k: (int(v) if isinstance(v, int) else (len(v) if hasattr(v, "__len__") and not isinstance(v, str) else v)) for k, v in results.items() if k != "_run"}
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    freshness_blocked = False
    if args.require_fresh:
        freshness = results.get("freshness") or {}
        blockers = _freshness_blockers(freshness, mode=args.mode)
        fetch_errors = [
            error
            for error in (freshness.get("fetch_errors") or [])
            if error.get("severity") != "event"
        ]
        if fetch_errors:
            blockers.append(f"{len(fetch_errors)} fetch error(s)")
        if blockers:
            print(
                "Required freshness gate blocked report: " + ", ".join(blockers),
                file=sys.stderr,
            )
            if args.allow_stale_artifact:
                freshness_blocked = True
                print(
                    "Continuing close-mode persistence so the dashboard can show the degraded run; email skipped.",
                    file=sys.stderr,
                )
            else:
                return 2
    if args.send_report and not freshness_blocked:
        # Use the current in-memory run, not load_latest_derived(), to
        # guarantee the email always matches the pipeline result that was
        # just computed (never silently mixes old/new snapshots from disk).
        technicals = results.get("exposure_technicals", pd.DataFrame())
        regime = results.get("relative_regime", pd.DataFrame())
        wrappers = results.get("wrapper_metrics", pd.DataFrame())
        try:
            prices = results.get("index_price_daily", pd.DataFrame())
            images = {}
            if not prices.empty:
                for exposure_id, title, color in EMAIL_CHART_SERIES:
                    image = generate_sparkline_chart(
                        prices, exposure_id, title, color=color, days=60
                    )
                    if image:
                        images[f"chart_{exposure_id}"] = image
            report_date = market_date()
            body = build_email_html(
                report_date=report_date,
                technicals=technicals,
                regime=regime,
                wrappers=wrappers,
                charts=images.keys(),
                mode=args.mode,
                freshness=results.get("freshness"),
            )
            send_report(
                subject=(
                    f"Index & ETF Intraday Snapshot — {report_date}"
                    if args.mode == "intraday"
                    else f"Index & ETF Allocation Monitor — {report_date}"
                ),
                body_html=body,
                recipient_override=args.recipient,
                images=images,
            )
            print("daily Gmail digest sent")
        except Exception as exc:
            # Email is best-effort; pipeline/dashboard must never fail because
            # SMTP or Gmail credentials are unavailable.
            print(f"Warning: Gmail digest not sent ({exc})", file=sys.stderr)
    elif args.send_report and freshness_blocked:
        print("Report skipped because required freshness was not satisfied.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
