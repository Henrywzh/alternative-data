from __future__ import annotations

import json

from event_consensus_fixtures import fake_pipeline_result
from event_consensus.cli import main


def test_query_brief_writes_one_json_document_to_stdout(artifact_path, capsys):
    assert main(["query", "brief", "--artifact-path", str(artifact_path)]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    payload = json.loads(captured.out)
    assert payload["query"] == "brief"
    assert payload["query_contract_version"] == "1.0"


def test_query_missing_event_returns_nonzero_and_diagnostic_on_stderr(
    artifact_path,
    capsys,
):
    assert (
        main(
            [
                "query",
                "research",
                "--event-id",
                "missing",
                "--artifact-path",
                str(artifact_path),
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "missing" in captured.err


def test_query_does_not_call_refresh_pipeline(monkeypatch, artifact_path):
    def fail_refresh(**_kwargs):
        raise AssertionError("network refresh")

    monkeypatch.setattr("event_consensus.cli.run_pipeline", fail_refresh)

    assert main(["query", "health", "--artifact-path", str(artifact_path)]) == 0


def test_legacy_refresh_arguments_still_parse(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("event_consensus.cli.run_pipeline", fake_pipeline_result)

    assert main(["--no-write", "--artifact-path", str(tmp_path / "latest.json")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
