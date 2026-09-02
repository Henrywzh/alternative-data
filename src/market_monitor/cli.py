"""CLI for the market_monitor daily pipeline."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

from .alerts import build_email_html, generate_sparkline_chart, send_report
from .alert_policy import (
    advance_alert_state,
    evaluate_alert,
    load_alert_state,
    save_alert_state,
    state_with_pending_events,
)
from .freshness import BLOCKING_FRESHNESS_STATUSES, market_date
from .pipeline import run_intraday_snapshot, run_pipeline
from .storage import prune_all_runs


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


def _emit_degraded_signal(blockers: list[str]) -> None:
    """Make a skipped digest visible to CI without failing the artifact build.

    Writes the ``degraded`` step output the workflow fails on, an annotation,
    and a job-summary line. Outside GitHub Actions the env vars are unset and
    only the annotation is printed, which is harmless in a terminal.
    """
    reason = ", ".join(blockers)
    print(f"::warning title=Digest skipped::{reason}")
    for env_var, payload in (
        ("GITHUB_OUTPUT", "degraded=true\n"),
        ("GITHUB_STEP_SUMMARY", f"### ⚠️ 邮件已跳过\n\n数据未通过 freshness gate：{reason}\n"),
    ):
        path = os.environ.get(env_var)
        if not path:
            continue
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(payload)
        except OSError as exc:  # never let a CI-reporting write break the run
            print(f"Warning: could not write {env_var} ({exc})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="market-monitor", description="Index & ETF Allocation Monitor pipeline")
    parser.add_argument("--limit-exposures", nargs="*", default=None, help="Restrict to these exposure ids (for testing)")
    parser.add_argument("--etf-only", nargs="*", default=None, help="Restrict ETF fetches to these tickers")
    parser.add_argument("--start-date", default=None, help="YYYYMMDD start for history")
    parser.add_argument("--no-write", action="store_true", help="Run without persisting snapshots")
    parser.add_argument("--allow-partial-write", action="store_true", help="Allow persisting partial/test runs to disk")
    parser.add_argument("--send-report", action="store_true", help="Evaluate the Gmail alert policy after running")
    parser.add_argument(
        "--force-report",
        action="store_true",
        help="Send a report even when no material alert or weekly heartbeat is due",
    )
    parser.add_argument(
        "--alert-state-path",
        default=None,
        help=argparse.SUPPRESS,
    )
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
        if should_write:
            removed_runs = prune_all_runs(keep=20)
            if removed_runs:
                print(f"Pruned {len(removed_runs)} stale market-monitor run directories")
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
                # A skipped digest used to leave no trace anywhere the operator
                # looks: exit 0, a green job, and simply no mail that morning.
                # The whole point of the gate is to make bad data loud, so
                # announce the degradation to CI even though the job continues.
                _emit_degraded_signal(blockers)
            else:
                return 2
    send_requested = args.send_report or args.force_report
    if send_requested and not freshness_blocked:
        # Use the current in-memory run, not load_latest_derived(), to
        # guarantee the email always matches the pipeline result that was
        # just computed (never silently mixes old/new snapshots from disk).
        technicals = results.get("exposure_technicals", pd.DataFrame())
        regime = results.get("relative_regime", pd.DataFrame())
        wrappers = results.get("wrapper_metrics", pd.DataFrame())
        state_path = Path(args.alert_state_path) if args.alert_state_path else None
        state = load_alert_state(state_path)
        report_date = market_date()
        decision = evaluate_alert(
            report_date=report_date,
            mode=args.mode,
            state=state,
            technicals=technicals,
            index_prices=results.get("index_price_daily", pd.DataFrame()),
            wrappers=wrappers,
            premium_history=results.get("premium_history", pd.DataFrame()),
            relative_pair_history=results.get("relative_pair_history", pd.DataFrame()),
            freshness=results.get("freshness"),
            force=args.force_report,
        )
        # Close runs persist the daily market snapshots; intraday runs persist
        # only this small delivery cursor. A --no-write run stays side-effect
        # free, which is important for partial/local tests and dry runs.
        persist_alert_state = not args.no_write and (
            args.mode == "intraday" or (should_write and not is_partial)
        )
        if not decision.should_send:
            if persist_alert_state:
                updated_state = advance_alert_state(
                    state,
                    mode=args.mode,
                    observation_date=decision.observation_date,
                    report_date=report_date,
                    kind=decision.kind,
                    sent=False,
                )
                # A second run on the same report date must not advance past a
                # newly confirmed event and then lose it permanently. Keep the
                # unsent event queued for the next healthy run.
                if decision.kind == "deduped" and decision.events:
                    updated_state = state_with_pending_events(updated_state, decision.events)
                save_alert_state(updated_state, state_path)
            print(f"Gmail alert skipped: {decision.reason_lines[0]}")
            return 0
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
            body = build_email_html(
                report_date=report_date,
                technicals=technicals,
                regime=regime,
                wrappers=wrappers,
                charts=images.keys(),
                mode=args.mode,
                freshness=results.get("freshness"),
                alert_reason=decision.reason_lines,
            )
            # Write a pending queue before SMTP. If Gmail times out after the
            # provider accepted the message, the next run may duplicate it;
            # that is preferable to losing a fee/risk event silently. A
            # successful send clears the queue and advances the mode cursor.
            if persist_alert_state and decision.events:
                save_alert_state(state_with_pending_events(state, decision.events), state_path)
            send_report(
                subject=f"{decision.subject_prefix} — {report_date}",
                body_html=body,
                recipient_override=args.recipient,
                images=images,
            )
            if persist_alert_state:
                save_alert_state(
                    advance_alert_state(
                        state,
                        mode=args.mode,
                        observation_date=decision.observation_date,
                        report_date=report_date,
                        kind=decision.kind,
                        sent=True,
                        sent_events=decision.events,
                    ),
                    state_path,
                )
            print(f"Gmail alert sent: {decision.kind}")
        except Exception as exc:
            # Email is best-effort; pipeline/dashboard must never fail because
            # SMTP or Gmail credentials are unavailable.
            print(f"Warning: Gmail alert not sent ({exc})", file=sys.stderr)
    elif send_requested and freshness_blocked:
        print("Report skipped because required freshness was not satisfied.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
