from __future__ import annotations

import json
from pathlib import Path

from ops_control.sector_builder_evidence import (
    MAX_EXCERPT_CHARS,
    build_sector_builder_evidence,
)


def _write_roster(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "live": [
                    {
                        "id": "hk-real-estate",
                        "builder": "scripts/build_hk_real_estate_artifact.py",
                    },
                    {
                        "id": "hk-transport",
                        "builder": "scripts/build_hk_transport_artifact.py",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_failure_evidence_is_per_builder_and_redacts_log_excerpt(tmp_path: Path) -> None:
    roster_path = _write_roster(tmp_path / "sectors.json")
    log_path = tmp_path / "builders.log"
    log_path.write_text(
        "\n".join(
            [
                "[hk-real-estate] building artifact",
                "[hk-transport] transport refresh completed",
                '[hk-real-estate] request payload {"api_key": "super-secret-value"}',
                "[hk-real-estate] Traceback (most recent call last):",
                "[run-artifact-builders] scripts/build_hk_real_estate_artifact.py exited with code 1",
            ]
        ),
        encoding="utf-8",
    )

    payload = build_sector_builder_evidence(
        log_path=log_path,
        roster_path=roster_path,
        producer_outcome="failure",
    )

    assert payload["capture_status"] == "complete"
    assert payload["producer_outcome"] == "failure"
    assert len(payload["failures"]) == 1
    failure = payload["failures"][0]
    assert failure["builder_id"] == "hk-real-estate"
    assert failure["script"] == "scripts/build_hk_real_estate_artifact.py"
    assert failure["exit_code"] == 1
    assert failure["timed_out"] is False
    assert "super-secret-value" not in failure["log_excerpt"]
    assert "[REDACTED]" in failure["log_excerpt"]
    assert "transport refresh completed" not in failure["log_excerpt"]


def test_timeout_metadata_is_retained(tmp_path: Path) -> None:
    roster_path = _write_roster(tmp_path / "sectors.json")
    log_path = tmp_path / "builders.log"
    log_path.write_text(
        "[run-artifact-builders] scripts/build_hk_transport_artifact.py timed out after 600000ms\n",
        encoding="utf-8",
    )

    payload = build_sector_builder_evidence(
        log_path=log_path,
        roster_path=roster_path,
        producer_outcome="failure",
    )

    failure = payload["failures"][0]
    assert failure["builder_id"] == "hk-transport"
    assert failure["exit_code"] is None
    assert failure["timed_out"] is True
    assert failure["timeout_ms"] == 600000


def test_signal_termination_summary_keeps_builder_identity(tmp_path: Path) -> None:
    roster_path = _write_roster(tmp_path / "sectors.json")
    log_path = tmp_path / "builders.log"
    log_path.write_text(
        "[run-artifact-builders] scripts/build_hk_transport_artifact.py exited with code null\n",
        encoding="utf-8",
    )

    payload = build_sector_builder_evidence(
        log_path=log_path,
        roster_path=roster_path,
        producer_outcome="failure",
    )

    failure = payload["failures"][0]
    assert failure["builder_id"] == "hk-transport"
    assert failure["exit_code"] is None
    assert failure["termination"] == "signal_or_unknown_exit"


def test_excerpt_is_bounded_to_the_latest_failure_context(tmp_path: Path) -> None:
    roster_path = _write_roster(tmp_path / "sectors.json")
    log_path = tmp_path / "builders.log"
    lines = [f"[hk-real-estate] diagnostic line {i}: {'x' * 100}" for i in range(100)]
    lines.append(
        "[run-artifact-builders] scripts/build_hk_real_estate_artifact.py exited with code 1"
    )
    log_path.write_text("\n".join(lines), encoding="utf-8")

    payload = build_sector_builder_evidence(
        log_path=log_path,
        roster_path=roster_path,
        producer_outcome="failure",
    )

    excerpt = payload["failures"][0]["log_excerpt"]
    assert len(excerpt) <= MAX_EXCERPT_CHARS
    assert payload["failures"][0]["excerpt_truncated"] is True
    assert "diagnostic line 99" in excerpt
    assert "diagnostic line 0" not in excerpt


def test_failure_without_a_matching_summary_is_marked_incomplete(tmp_path: Path) -> None:
    roster_path = _write_roster(tmp_path / "sectors.json")
    log_path = tmp_path / "builders.log"
    log_path.write_text("[hk-real-estate] failed but no summary was emitted\n", encoding="utf-8")

    payload = build_sector_builder_evidence(
        log_path=log_path,
        roster_path=roster_path,
        producer_outcome="failure",
    )

    assert payload["capture_status"] == "incomplete"
    assert payload["reason"] == "failure_summary_missing"
    assert payload["failures"] == []


def test_missing_log_is_explicitly_reported_without_blocking_payload_creation(tmp_path: Path) -> None:
    roster_path = _write_roster(tmp_path / "sectors.json")

    payload = build_sector_builder_evidence(
        log_path=tmp_path / "missing.log",
        roster_path=roster_path,
        producer_outcome="failure",
    )

    assert payload["capture_status"] == "incomplete"
    assert payload["reason"] == "builder_log_missing"
    assert payload["failures"] == []
