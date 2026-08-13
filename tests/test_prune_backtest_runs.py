"""Tests for scripts/prune_backtest_runs.py.

Uses synthetic run directories under tmp_path so nothing here touches the
real data/registries/runs/ tree.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import prune_backtest_runs as prune  # noqa: E402


def _make_run(
    runs_root: Path,
    run_id: str,
    *,
    created_at: str | None,
    extra_files: dict[str, str] | None = None,
) -> Path:
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if created_at is not None:
        manifest = {
            "engine_version": run_id.rsplit("-", 1)[0],
            "run_id": run_id,
            "created_at": created_at,
            "status": "ready",
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "asia_backtest_long_form.parquet").write_bytes(b"fake-parquet-bytes")
    for name, content in (extra_files or {}).items():
        (run_dir / name).write_text(content, encoding="utf-8")
    return run_dir


def _make_latest_pointer(registries_root: Path, run_id: str) -> Path:
    pointer = registries_root / "asia_backtest_latest.json"
    payload = {
        "run_id": run_id,
        "manifest": f"runs/{run_id}/manifest.json",
        "engine_version": run_id.rsplit("-", 1)[0],
    }
    pointer.write_text(json.dumps(payload), encoding="utf-8")
    return pointer


@pytest.fixture
def registries_root(tmp_path: Path) -> Path:
    root = tmp_path / "data" / "registries"
    (root / "runs").mkdir(parents=True)
    return root


def test_dry_run_default_deletes_nothing(registries_root: Path) -> None:
    runs_root = registries_root / "runs"
    _make_run(runs_root, "engine_v1-aaa", created_at="2026-08-01T00:00:00+00:00")
    _make_run(runs_root, "engine_v1-bbb", created_at="2026-08-02T00:00:00+00:00")
    latest = _make_latest_pointer(registries_root, "engine_v1-bbb")

    rc = prune.main(
        [
            "--runs-root",
            str(runs_root),
            "--latest-pointer",
            str(latest),
            "--keep",
            "1",
        ]
    )

    assert rc == 0
    assert (runs_root / "engine_v1-aaa").exists()
    assert (runs_root / "engine_v1-bbb").exists()


def test_apply_without_flag_is_still_a_dry_run_by_default() -> None:
    parser = prune.build_parser()
    args = parser.parse_args([])
    assert args.apply is False


def test_latest_json_run_never_deleted_even_when_old(registries_root: Path) -> None:
    runs_root = registries_root / "runs"
    # 'old-latest' is the oldest run chronologically but is pinned by latest.json.
    _make_run(runs_root, "engine_v1-old-latest", created_at="2026-01-01T00:00:00+00:00")
    _make_run(runs_root, "engine_v1-mid", created_at="2026-06-01T00:00:00+00:00")
    _make_run(runs_root, "engine_v1-newest", created_at="2026-08-01T00:00:00+00:00")
    latest = _make_latest_pointer(registries_root, "engine_v1-old-latest")

    rc = prune.main(
        [
            "--runs-root",
            str(runs_root),
            "--latest-pointer",
            str(latest),
            "--keep",
            "1",
            "--apply",
        ]
    )

    assert rc == 0
    # protected despite being the oldest and outside the keep=1 window
    assert (runs_root / "engine_v1-old-latest").exists()
    # newest is retained because keep=1 selects it
    assert (runs_root / "engine_v1-newest").exists()
    # mid is neither the newest nor the protected latest run -> pruned
    assert not (runs_root / "engine_v1-mid").exists()


def test_keep_n_retains_right_set(registries_root: Path) -> None:
    runs_root = registries_root / "runs"
    _make_run(runs_root, "engine_v1-r1", created_at="2026-08-01T00:00:00+00:00")
    _make_run(runs_root, "engine_v1-r2", created_at="2026-08-02T00:00:00+00:00")
    _make_run(runs_root, "engine_v1-r3", created_at="2026-08-03T00:00:00+00:00")
    _make_run(runs_root, "engine_v1-r4", created_at="2026-08-04T00:00:00+00:00")
    latest = _make_latest_pointer(registries_root, "engine_v1-r4")

    rc = prune.main(
        [
            "--runs-root",
            str(runs_root),
            "--latest-pointer",
            str(latest),
            "--keep",
            "2",
            "--apply",
        ]
    )

    assert rc == 0
    assert not (runs_root / "engine_v1-r1").exists()
    assert not (runs_root / "engine_v1-r2").exists()
    assert (runs_root / "engine_v1-r3").exists()
    assert (runs_root / "engine_v1-r4").exists()


def test_missing_latest_pointer_aborts_without_deleting(registries_root: Path) -> None:
    runs_root = registries_root / "runs"
    _make_run(runs_root, "engine_v1-aaa", created_at="2026-08-01T00:00:00+00:00")
    missing_pointer = registries_root / "asia_backtest_latest.json"  # never created

    rc = prune.main(
        [
            "--runs-root",
            str(runs_root),
            "--latest-pointer",
            str(missing_pointer),
            "--keep",
            "0",
            "--apply",
        ]
    )

    assert rc == 1
    assert (runs_root / "engine_v1-aaa").exists()


def test_corrupt_latest_pointer_aborts_without_deleting(registries_root: Path) -> None:
    runs_root = registries_root / "runs"
    _make_run(runs_root, "engine_v1-aaa", created_at="2026-08-01T00:00:00+00:00")
    pointer = registries_root / "asia_backtest_latest.json"
    pointer.write_text("{not valid json", encoding="utf-8")

    rc = prune.main(
        [
            "--runs-root",
            str(runs_root),
            "--latest-pointer",
            str(pointer),
            "--keep",
            "0",
            "--apply",
        ]
    )

    assert rc == 1
    assert (runs_root / "engine_v1-aaa").exists()


def test_latest_pointer_missing_run_id_field_aborts(registries_root: Path) -> None:
    runs_root = registries_root / "runs"
    _make_run(runs_root, "engine_v1-aaa", created_at="2026-08-01T00:00:00+00:00")
    pointer = registries_root / "asia_backtest_latest.json"
    pointer.write_text(json.dumps({"manifest": "runs/x/manifest.json"}), encoding="utf-8")

    rc = prune.main(
        [
            "--runs-root",
            str(runs_root),
            "--latest-pointer",
            str(pointer),
            "--keep",
            "0",
            "--apply",
        ]
    )

    assert rc == 1
    assert (runs_root / "engine_v1-aaa").exists()


def test_path_outside_runs_root_is_refused(tmp_path: Path) -> None:
    outside_dir = tmp_path / "some" / "other" / "directory"
    outside_dir.mkdir(parents=True)
    _make_run(outside_dir, "engine_v1-aaa", created_at="2026-08-01T00:00:00+00:00")
    # a well-formed latest pointer sitting next to the bogus root
    latest = outside_dir.parent / "asia_backtest_latest.json"
    latest.write_text(json.dumps({"run_id": "engine_v1-aaa"}), encoding="utf-8")

    rc = prune.main(
        [
            "--runs-root",
            str(outside_dir),
            "--latest-pointer",
            str(latest),
            "--keep",
            "0",
            "--apply",
        ]
    )

    assert rc == 1
    assert (outside_dir / "engine_v1-aaa").exists()


def test_undated_run_is_protected_rather_than_guessed(registries_root: Path) -> None:
    runs_root = registries_root / "runs"
    _make_run(runs_root, "engine_v1-nomani", created_at=None)
    _make_run(runs_root, "engine_v1-newest", created_at="2026-08-01T00:00:00+00:00")
    latest = _make_latest_pointer(registries_root, "engine_v1-newest")

    rc = prune.main(
        [
            "--runs-root",
            str(runs_root),
            "--latest-pointer",
            str(latest),
            "--keep",
            "1",
            "--apply",
        ]
    )

    assert rc == 0
    # can't determine recency -> not deleted
    assert (runs_root / "engine_v1-nomani").exists()
    assert (runs_root / "engine_v1-newest").exists()
