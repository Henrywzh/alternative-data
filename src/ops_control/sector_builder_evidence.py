from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from .redaction import redact_text


MAX_EXCERPT_CHARS = 4_000
MAX_FAILURES = 32
_BUILDER_LINE = re.compile(r"^\[(?P<builder>[^\]]+)\](?:\s(?P<text>.*))?$")
_FAILURE_LINE = re.compile(
    r"^\[run-artifact-builders\]\s+(?P<script>.+?)\s+"
    r"(?:(?:exited with code (?P<exit_code>-?\d+|null))|"
    r"(?:timed out after (?P<timeout_ms>\d+)ms))\s*$"
)


def build_sector_builder_evidence(
    *,
    log_path: Path,
    roster_path: Path,
    producer_outcome: str,
) -> dict[str, Any]:
    """Create bounded, redacted evidence for the Asia Markets sector builders.

    The combined runner log remains in the ephemeral runner temp directory. This
    function persists only failure metadata and a bounded excerpt for the failed
    builder(s), applying the shared ops-control secret redaction before output.
    """

    outcome = _normalise_outcome(producer_outcome)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "producer": "sector-builders",
        "producer_outcome": outcome,
        "capture_status": "complete",
        "reason": None,
        "failures": [],
    }
    if outcome == "success":
        return payload
    if outcome not in {"failure", "cancelled"}:
        payload.update(capture_status="unavailable", reason="producer_outcome_unavailable")
        return payload
    if not log_path.is_file():
        payload.update(capture_status="incomplete", reason="builder_log_missing")
        return payload

    try:
        roster = json.loads(roster_path.read_text(encoding="utf-8"))
        if not isinstance(roster, dict):
            raise ValueError("invalid sector roster")
        live_sectors = roster.get("live")
        if not isinstance(live_sectors, list):
            raise ValueError("invalid live sector roster")
        id_by_script = {
            _normalise_script(str(item["builder"])): str(item["id"])
            for item in live_sectors
            if isinstance(item, dict) and item.get("builder") and item.get("id")
        }
    except (OSError, json.JSONDecodeError, TypeError, ValueError, KeyError):
        payload.update(capture_status="unavailable", reason="sector_roster_unavailable")
        return payload

    excerpts: dict[str, str] = {}
    excerpt_truncated: dict[str, bool] = {}
    failures_by_script: dict[str, dict[str, Any]] = {}
    known_builder_ids = set(id_by_script.values())
    try:
        with log_path.open(encoding="utf-8", errors="replace") as log_file:
            for raw_line in log_file:
                line = raw_line.rstrip("\r\n")
                failure_match = _FAILURE_LINE.match(line)
                if failure_match:
                    script = _normalise_script(failure_match.group("script"))
                    timed_out = failure_match.group("timeout_ms") is not None
                    exit_code = failure_match.group("exit_code")
                    failures_by_script[script] = {
                        "builder_id": id_by_script.get(script),
                        "script": _safe_script(script),
                        "exit_code": (
                            int(exit_code) if exit_code and exit_code != "null" else None
                        ),
                        "timed_out": timed_out,
                        "termination": (
                            "signal_or_unknown_exit"
                            if exit_code == "null"
                            else None
                        ),
                        "timeout_ms": (
                            int(failure_match.group("timeout_ms")) if timed_out else None
                        ),
                    }
                    continue

                builder_match = _BUILDER_LINE.match(line)
                if not builder_match:
                    continue
                builder_id = builder_match.group("builder")
                if builder_id not in known_builder_ids:
                    continue
                raw_text = builder_match.group("text") or ""
                safe_line = redact_text(raw_text)
                excerpt_line = f"[{builder_id}] {safe_line}".rstrip()
                previous = excerpts.get(builder_id, "")
                combined = f"{previous}\n{excerpt_line}" if previous else excerpt_line
                if len(excerpt_line) > MAX_EXCERPT_CHARS or len(combined) > MAX_EXCERPT_CHARS:
                    combined = combined[-MAX_EXCERPT_CHARS:]
                    excerpt_truncated[builder_id] = True
                excerpts[builder_id] = combined
    except OSError:
        payload.update(capture_status="incomplete", reason="builder_log_unreadable")
        return payload

    if not failures_by_script:
        payload.update(capture_status="incomplete", reason="failure_summary_missing")
        return payload

    failures: list[dict[str, Any]] = []
    for script, failure in sorted(failures_by_script.items())[:MAX_FAILURES]:
        builder_id = failure["builder_id"]
        failure["log_excerpt"] = excerpts.get(builder_id, "") if builder_id else ""
        failure["excerpt_truncated"] = excerpt_truncated.get(builder_id, False)
        failures.append(failure)
    payload["failures"] = failures
    if len(failures_by_script) > MAX_FAILURES:
        payload.update(capture_status="incomplete", reason="failure_count_limit")
    elif any(item["builder_id"] is None for item in failures):
        payload.update(capture_status="incomplete", reason="builder_script_unmapped")
    elif any(not item["log_excerpt"] for item in failures):
        payload.update(capture_status="incomplete", reason="builder_output_missing")
    return payload


def _normalise_outcome(value: str) -> str:
    outcome = str(value or "").strip().lower()
    return outcome if outcome in {"success", "failure", "cancelled"} else "unknown"


def _normalise_script(value: str) -> str:
    normalised = PurePosixPath(value.replace("\\", "/")).as_posix()
    while normalised.startswith("./"):
        normalised = normalised[2:]
    return normalised


def _safe_script(value: str) -> str:
    safe = redact_text(value)
    return safe[-240:]
