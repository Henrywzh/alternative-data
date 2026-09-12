"""The commit helper every data workflow uses, exercised against real git.

Two production CI failures came from hand-written versions of this logic, and
both were invisible to the test suite because nothing here ever ran a commit
step. These tests drive the real script against real repositories with a real
upstream, so the failure modes are reproduced rather than described.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ci" / "commit_dataset_paths.sh"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture()
def repo_with_upstream(tmp_path: Path) -> tuple[Path, Path]:
    upstream = tmp_path / "upstream.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(upstream)], check=True, capture_output=True)

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(upstream), str(clone)], check=True, capture_output=True)
    _git(clone, "config", "user.email", "test@example.com")
    _git(clone, "config", "user.name", "Test")

    dataset = clone / "data" / "normalized" / "lane"
    dataset.mkdir(parents=True)
    (dataset / "thing.parquet").write_bytes(b"v1")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "seed")
    _git(clone, "push", "origin", "main")
    return clone, upstream


def _run(repo: Path, *paths: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "chore: refresh", *paths],
        cwd=repo,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(repo), "DEFAULT_BRANCH": "main"},
    )


def test_a_migration_to_partitions_stages_the_deletion(repo_with_upstream) -> None:
    # The exact production failure: the storage layer replaced the single file
    # with a directory of partitions. The tracked file is now gone, and if its
    # deletion is not staged the later `git pull --rebase` aborts.
    repo, _ = repo_with_upstream
    lane = repo / "data" / "normalized" / "lane"
    (lane / "thing.parquet").unlink()
    partitions = lane / "thing"
    partitions.mkdir()
    (partitions / "2026-09-12.parquet").write_bytes(b"day")

    result = _run(repo, "data/normalized/lane/thing", "data/normalized/lane/thing.parquet")

    assert result.returncode == 0, result.stderr
    assert _git(repo, "status", "--porcelain") == ""
    assert "thing.parquet" in _git(repo, "show", "--name-status", "--format=", "HEAD")


def test_a_brand_new_partition_is_committed(repo_with_upstream) -> None:
    # A new observation date is an *untracked* file. A `git diff` based guard
    # reports nothing to do and silently skips publishing the day.
    repo, _ = repo_with_upstream
    partitions = repo / "data" / "normalized" / "lane" / "thing"
    partitions.mkdir()
    (partitions / "2026-09-12.parquet").write_bytes(b"day")

    result = _run(repo, "data/normalized/lane/thing", "data/normalized/lane/thing.parquet")

    assert result.returncode == 0, result.stderr
    assert "2026-09-12.parquet" in _git(repo, "show", "--name-only", "--format=", "HEAD")


def test_a_path_that_never_existed_does_not_fail_the_run(repo_with_upstream) -> None:
    # `git add` exits non-zero on a pathspec matching nothing, so an absent
    # lane must be dropped before staging.
    repo, _ = repo_with_upstream
    (repo / "data" / "normalized" / "lane" / "thing.parquet").write_bytes(b"v2")

    result = _run(
        repo,
        "data/normalized/lane/thing.parquet",
        "data/normalized/absent_lane",
        "data/normalized/absent_lane.parquet",
    )

    assert result.returncode == 0, result.stderr
    assert _git(repo, "status", "--porcelain") == ""


def test_no_changes_is_success_and_commits_nothing(repo_with_upstream) -> None:
    repo, _ = repo_with_upstream
    before = _git(repo, "rev-parse", "HEAD")

    result = _run(repo, "data/normalized/lane/thing.parquet")

    assert result.returncode == 0, result.stderr
    assert "No dataset changes to commit" in result.stdout
    assert _git(repo, "rev-parse", "HEAD") == before


def test_the_commit_reaches_the_upstream(repo_with_upstream) -> None:
    repo, upstream = repo_with_upstream
    (repo / "data" / "normalized" / "lane" / "thing.parquet").write_bytes(b"v2")

    result = _run(repo, "data/normalized/lane/thing.parquet")

    assert result.returncode == 0, result.stderr
    assert _git(upstream, "log", "-1", "--format=%s", "main") == "chore: refresh"


def test_a_push_race_is_resolved_by_rebasing(repo_with_upstream) -> None:
    # Several data workflows land on the branch at once; the loser must rebase
    # and retry rather than fail the refresh.
    repo, upstream = repo_with_upstream
    other = repo.parent / "other"
    subprocess.run(["git", "clone", str(upstream), str(other)], check=True, capture_output=True)
    _git(other, "config", "user.email", "other@example.com")
    _git(other, "config", "user.name", "Other")
    (other / "unrelated.txt").write_text("landed first")
    _git(other, "add", "-A")
    _git(other, "commit", "-m", "other lane")
    _git(other, "push", "origin", "main")

    (repo / "data" / "normalized" / "lane" / "thing.parquet").write_bytes(b"v2")
    result = _run(repo, "data/normalized/lane/thing.parquet")

    assert result.returncode == 0, result.stderr
    subjects = _git(upstream, "log", "--format=%s", "main").splitlines()
    assert subjects[:2] == ["chore: refresh", "other lane"]
