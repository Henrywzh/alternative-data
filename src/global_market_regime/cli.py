"""CLI for the global market-regime radar."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .alerts import (
    advance_alert_state,
    build_email_html,
    evaluate_alert,
    load_alert_state,
    save_alert_state,
    send_report,
)
from .config import ALERT_STATE_PATH
from .pipeline import run_pipeline
from .presentation import build_regime_summary, build_threshold_monitor
from .storage import utc_now


def _emit_degraded(reason: str) -> None:
    print(f"::warning title=Regime digest skipped::{reason}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write(f"### 全球市场状态邮件已跳过\n\n{reason}\n")
        except OSError:
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="global-market-regime", description="Global market-regime radar")
    parser.add_argument("--no-write", action="store_true", help="Run without persisting snapshots")
    parser.add_argument(
        "--alert-mode",
        choices=("preview", "defensive"),
        default=None,
        help="Preview component changes or send only breadth-qualified defensive alerts",
    )
    parser.add_argument("--send-report", action="store_true", help="Backward-compatible alias for --alert-mode defensive")
    parser.add_argument(
        "--force-report",
        action="store_true",
        help="Send even when no state change is detected; bypasses the freshness gate and records the decision as manual",
    )
    parser.add_argument("--recipient", default=None, help="Override recipient")
    parser.add_argument("--alert-state-path", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.alert_mode == "preview" and args.force_report:
        parser.error("--force-report cannot be combined with --alert-mode preview")

    results = run_pipeline(write=not args.no_write)
    snapshot = results.get("latest_conditions")
    summary = {
        "run_id": results.get("run_id"),
        "overall_state": results.get("overall_state"),
        "fred_errors": results.get("fred_errors"),
        "mpt_error": results.get("mpt_error"),
        "fred_rows": int(len(results.get("fred_observations"))) if results.get("fred_observations") is not None else 0,
        "mpt_rows": int(len(results.get("atlanta_mpt"))) if results.get("atlanta_mpt") is not None else 0,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))

    alert_mode = args.alert_mode or ("defensive" if args.send_report else None)
    if alert_mode is None and not args.force_report:
        return 0

    freshness_ok = bool(results.get("freshness_ok"))
    if not freshness_ok and not args.force_report:
        reason = "freshness gate blocked email; dashboard snapshots were still written"
        print(reason, file=sys.stderr)
        _emit_degraded(reason)
        return 0

    state_path = Path(args.alert_state_path) if args.alert_state_path else ALERT_STATE_PATH
    state = load_alert_state(state_path)
    decision = evaluate_alert(snapshot, state=state, mode=alert_mode or "defensive")
    if args.force_report:
        decision["should_send"] = True
        decision["kind"] = "manual"
    if alert_mode == "preview" and not args.force_report:
        updated = advance_alert_state(
            snapshot,
            events=decision["events"],
            state=state,
            sent=False,
            decision=decision,
            mode="preview",
            run_id=results.get("run_id"),
        )
        save_alert_state(updated, state_path)
        print(
            "Alert preview recorded: "
            f"{len(decision['events'])} component change(s); "
            f"defensive eligible={decision['defensive_alert_eligible']}."
        )
        return 0
    if not decision["should_send"]:
        save_alert_state(
            advance_alert_state(
                snapshot,
                events=decision["events"],
                state=state,
                sent=False,
                decision=decision,
                mode=alert_mode or "defensive",
                run_id=results.get("run_id"),
            ),
            state_path,
        )
        print("No breadth-qualified regime change; email skipped.")
        return 0

    subject = f"全球市场状态预警 · {results.get('overall_state')} · {utc_now()[:10]}"
    monitor = build_threshold_monitor(snapshot, results.get("condition_states"))
    regime_summary = build_regime_summary(monitor)
    body = build_email_html(
        snapshot,
        decision["events"],
        overall_state=str(results.get("overall_state") or "Normal"),
        breadth_zh=str(regime_summary.get("breadth_zh") or "—"),
    )
    try:
        send_report(subject=subject, body_html=body, recipient_override=args.recipient)
        save_alert_state(
            advance_alert_state(
                snapshot,
                events=decision["events"],
                state=state,
                sent=True,
                decision=decision,
                mode=alert_mode or "defensive",
                run_id=results.get("run_id"),
            ),
            state_path,
        )
        print(f"Sent regime alert ({decision['kind']}).")
    except Exception as exc:
        print(f"Gmail failed after data persistence: {exc}", file=sys.stderr)
        _emit_degraded(str(exc))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
