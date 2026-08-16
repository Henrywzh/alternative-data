"""Tests for scripts/research_control_tower_pipeline.py.

Covers the toml -> descriptor expansion and, at minimum as required by the
task, the --strict missing-required-input failure path -- both for a row
whose file is missing/empty (per-row `required = true`) and for a kind
whose entire [[input]] block has been deleted from build_inputs.toml
(manifest-level `required_kinds`), which is the exact shape of the
b23-live-20260816T0420Z regression: --quote-input was never passed at all.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_pipeline_module():
    script_path = REPO_ROOT / "scripts" / "research_control_tower_pipeline.py"
    spec = importlib.util.spec_from_file_location("_rct_pipeline_under_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses' internal type-checking looks the module up via
    # sys.modules[cls.__module__], so it must be registered before exec.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


pipeline = _load_pipeline_module()


def _write_parquet(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)


def _write_toml(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# load_build_inputs / expand_to_cli_args
# ---------------------------------------------------------------------------


def test_load_build_inputs_parses_descriptors_and_required_kinds(tmp_path):
    quote_path = tmp_path / "data" / "quote_snapshots.parquet"
    _write_parquet(quote_path, [{"a": 1}])
    toml_path = tmp_path / "build_inputs.toml"
    _write_toml(
        toml_path,
        f"""
        schema_version = 1
        required_kinds = ["quote"]

        [[input]]
        kind = "quote"
        source_id = "quote_snapshots"
        path = "data/quote_snapshots.parquet"
        format = "parquet"
        schema_id = "quote_snapshots_v1"
        required = true
        description = "test quote input"
        """,
    )

    manifest = pipeline.load_build_inputs(toml_path, repo_root=tmp_path)

    assert manifest.required_kinds == ("quote",)
    assert len(manifest.descriptors) == 1
    descriptor = manifest.descriptors[0]
    assert descriptor.kind == "quote"
    assert descriptor.source_id == "quote_snapshots"
    assert descriptor.path == quote_path
    assert descriptor.format == "parquet"
    assert descriptor.schema_id == "quote_snapshots_v1"
    assert descriptor.required is True


def test_load_build_inputs_missing_file_raises_pipeline_error(tmp_path):
    with pytest.raises(pipeline.PipelineError, match="not found"):
        pipeline.load_build_inputs(tmp_path / "does_not_exist.toml")


def test_load_build_inputs_rejects_unknown_kind(tmp_path):
    toml_path = tmp_path / "build_inputs.toml"
    _write_toml(
        toml_path,
        """
        schema_version = 1
        [[input]]
        kind = "bogus"
        source_id = "x"
        path = "x.parquet"
        format = "parquet"
        schema_id = "x_v1"
        """,
    )
    with pytest.raises(pipeline.PipelineError, match="unknown kind"):
        pipeline.load_build_inputs(toml_path, repo_root=tmp_path)


def test_load_build_inputs_rejects_duplicate_source_id(tmp_path):
    toml_path = tmp_path / "build_inputs.toml"
    _write_toml(
        toml_path,
        """
        schema_version = 1
        [[input]]
        kind = "quote"
        source_id = "dup"
        path = "a.parquet"
        format = "parquet"
        schema_id = "quote_snapshots_v1"

        [[input]]
        kind = "earnings"
        source_id = "dup"
        path = "b.parquet"
        format = "parquet"
        schema_id = "earnings_actuals_v1"
        """,
    )
    with pytest.raises(pipeline.PipelineError, match="duplicate source_id"):
        pipeline.load_build_inputs(toml_path, repo_root=tmp_path)


def test_expand_to_cli_args_maps_kind_to_flag_and_formats_value(tmp_path):
    toml_path = tmp_path / "build_inputs.toml"
    _write_toml(
        toml_path,
        """
        schema_version = 1
        [[input]]
        kind = "official_filing"
        source_id = "official_filings"
        path = "official_filings_v1.parquet"
        format = "parquet"
        schema_id = "official_filings_v1"
        required = true

        [[input]]
        kind = "earnings"
        source_id = "earnings_actuals"
        path = "earnings_actuals_v1.parquet"
        format = "parquet"
        schema_id = "earnings_actuals_v1"
        required = true
        """,
    )
    manifest = pipeline.load_build_inputs(toml_path, repo_root=tmp_path)
    argv = pipeline.expand_to_cli_args(manifest.descriptors)

    assert argv == [
        "--official-filing-input",
        f"official_filings|{tmp_path / 'official_filings_v1.parquet'}|parquet|official_filings_v1",
        "--earnings-input",
        f"earnings_actuals|{tmp_path / 'earnings_actuals_v1.parquet'}|parquet|earnings_actuals_v1",
    ]


# ---------------------------------------------------------------------------
# verify_required_inputs (the --strict pre-flight gate)
# ---------------------------------------------------------------------------


def _manifest_with(descriptors, required_kinds=()):
    return pipeline.BuildInputsManifest(descriptors=list(descriptors), required_kinds=tuple(required_kinds))


def test_verify_required_inputs_passes_when_everything_present_and_non_empty(tmp_path):
    quote_path = tmp_path / "quote_snapshots.parquet"
    _write_parquet(quote_path, [{"a": 1}])
    descriptor = pipeline.InputDescriptor(
        kind="quote",
        source_id="quote_snapshots",
        path=quote_path,
        format="parquet",
        schema_id="quote_snapshots_v1",
        required=True,
    )
    manifest = _manifest_with([descriptor], required_kinds=["quote"])

    assert pipeline.verify_required_inputs(manifest) == []


def test_verify_required_inputs_fails_when_required_row_file_missing(tmp_path):
    descriptor = pipeline.InputDescriptor(
        kind="quote",
        source_id="quote_snapshots",
        path=tmp_path / "does_not_exist.parquet",
        format="parquet",
        schema_id="quote_snapshots_v1",
        required=True,
    )
    manifest = _manifest_with([descriptor])

    failures = pipeline.verify_required_inputs(manifest)

    assert len(failures) == 1
    assert "quote_snapshots" in failures[0]
    assert "does not exist" in failures[0]


def test_verify_required_inputs_fails_when_required_row_file_is_zero_row_parquet(tmp_path):
    path = tmp_path / "empty.parquet"
    _write_parquet(path, [])
    descriptor = pipeline.InputDescriptor(
        kind="quote",
        source_id="quote_snapshots",
        path=path,
        format="parquet",
        schema_id="quote_snapshots_v1",
        required=True,
    )
    manifest = _manifest_with([descriptor])

    failures = pipeline.verify_required_inputs(manifest)

    assert len(failures) == 1
    assert "0 rows" in failures[0]


def test_verify_required_inputs_fails_when_required_row_file_is_zero_bytes(tmp_path):
    path = tmp_path / "empty_bytes.parquet"
    path.write_bytes(b"")
    descriptor = pipeline.InputDescriptor(
        kind="quote",
        source_id="quote_snapshots",
        path=path,
        format="parquet",
        schema_id="quote_snapshots_v1",
        required=True,
    )
    manifest = _manifest_with([descriptor])

    failures = pipeline.verify_required_inputs(manifest)

    assert len(failures) == 1
    assert "0 bytes" in failures[0]


def test_verify_required_inputs_fails_when_required_kind_has_no_rows_at_all(tmp_path):
    # This is the b23-live-20260816T0420Z regression shape: the quote layer
    # is entirely absent from the manifest, not merely present-but-broken.
    other_path = tmp_path / "earnings_actuals_v1.parquet"
    _write_parquet(other_path, [{"a": 1}])
    other_descriptor = pipeline.InputDescriptor(
        kind="earnings",
        source_id="earnings_actuals",
        path=other_path,
        format="parquet",
        schema_id="earnings_actuals_v1",
        required=True,
    )
    manifest = _manifest_with([other_descriptor], required_kinds=["quote", "earnings"])

    failures = pipeline.verify_required_inputs(manifest)

    assert len(failures) == 1
    assert "quote" in failures[0]
    assert "no declared input" in failures[0]


def test_verify_required_inputs_optional_row_missing_is_not_a_failure(tmp_path):
    descriptor = pipeline.InputDescriptor(
        kind="macro",
        source_id="macro_collector_observations",
        path=tmp_path / "does_not_exist.parquet",
        format="parquet",
        schema_id="macro_collector_v1",
        required=False,
    )
    manifest = _manifest_with([descriptor], required_kinds=["quote"])
    # No quote descriptor at all, and required_kinds includes "quote" -> still fails,
    # but the optional macro row itself must not be the (sole/duplicate) cause.
    failures = pipeline.verify_required_inputs(manifest)
    assert len(failures) == 1
    assert "quote" in failures[0]
    assert "macro" not in failures[0]


# ---------------------------------------------------------------------------
# default_build_id
# ---------------------------------------------------------------------------


def test_default_build_id_matches_expected_format():
    from datetime import datetime, timezone

    as_of = datetime(2026, 8, 17, 4, 0, 0, tzinfo=timezone.utc)
    assert pipeline.default_build_id(as_of) == "rtc-20260817T0400Z"


# ---------------------------------------------------------------------------
# main(): the --strict end-to-end failure path
# ---------------------------------------------------------------------------


def test_main_strict_fails_before_invoking_build_when_required_kind_missing(tmp_path, monkeypatch):
    earnings_path = tmp_path / "earnings_actuals_v1.parquet"
    _write_parquet(earnings_path, [{"a": 1}])
    toml_path = tmp_path / "build_inputs.toml"
    _write_toml(
        toml_path,
        f"""
        schema_version = 1
        required_kinds = ["quote", "earnings"]

        [[input]]
        kind = "earnings"
        source_id = "earnings_actuals"
        path = "earnings_actuals_v1.parquet"
        format = "parquet"
        schema_id = "earnings_actuals_v1"
        required = true
        """,
    )

    build_was_invoked = False

    def _fail_if_called(argv):  # pragma: no cover - should never run
        nonlocal build_was_invoked
        build_was_invoked = True
        raise AssertionError("build must not be invoked when --strict pre-flight fails")

    monkeypatch.setattr(pipeline, "cli_main", _fail_if_called)

    output_dir = tmp_path / "out"
    exit_code = pipeline.main(
        [
            "--skip-collect",
            "--strict",
            "--build-inputs-toml", str(toml_path),
            "--registry-root", str(tmp_path),
            "--event-root", str(tmp_path),
            "--output-dir", str(output_dir),
        ]
    )

    assert exit_code == 1
    assert build_was_invoked is False
    assert not output_dir.exists()


def test_main_non_strict_still_invokes_build_when_required_kind_missing(tmp_path, monkeypatch):
    """Without --strict, the pipeline does not run the pre-flight gate at all
    (matches today's cli.py behaviour of trusting whatever was configured);
    --strict is what changes that."""

    toml_path = tmp_path / "build_inputs.toml"
    _write_toml(
        toml_path,
        """
        schema_version = 1
        required_kinds = ["quote"]
        """,
    )

    captured_argv = {}

    def _record(argv):
        captured_argv["argv"] = argv
        return 0

    monkeypatch.setattr(pipeline, "cli_main", _record)

    exit_code = pipeline.main(
        [
            "--skip-collect",
            "--build-inputs-toml", str(toml_path),
            "--registry-root", str(tmp_path),
            "--event-root", str(tmp_path),
            "--output-dir", str(tmp_path / "out"),
        ]
    )

    assert exit_code == 0
    assert "argv" in captured_argv
    assert "--quote-input" not in captured_argv["argv"]


def test_main_strict_succeeds_with_repo_committed_inputs(tmp_path):
    """Integration check against the real, committed build_inputs.toml and
    data/normalized/research_control_tower/ inputs: --skip-collect --strict
    should produce a bundle without touching the network."""

    output_dir = tmp_path / "out"
    exit_code = pipeline.main(
        [
            "--skip-collect",
            "--strict",
            "--output-dir", str(output_dir),
        ]
    )

    assert exit_code == 0
    assert (output_dir / "CURRENT").is_file()
    current = (output_dir / "CURRENT").read_text().strip()
    generation_dir = output_dir / current
    assert (generation_dir / "build_manifest.json").is_file()
    assert (generation_dir / "quote_snapshots.parquet").is_file()
    assert (generation_dir / "official_filings.parquet").is_file()
    assert (generation_dir / "earnings_actuals.parquet").is_file()
