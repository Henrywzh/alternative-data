import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKER_PATH = (
    REPO_ROOT
    / "apps"
    / "asia-markets-dashboard"
    / "scripts"
    / "check_streamlit_parity.py"
)
CHECKER_SPEC = importlib.util.spec_from_file_location("streamlit_parity_checker", CHECKER_PATH)
assert CHECKER_SPEC and CHECKER_SPEC.loader
checker = importlib.util.module_from_spec(CHECKER_SPEC)
CHECKER_SPEC.loader.exec_module(checker)


def _artifact(*, value: int = 1, add_chart: bool = False) -> dict:
    charts = [{"id": "trend", "dataset": "monthly", "type": "line"}]
    if add_chart:
        charts.append({"id": "new", "dataset": "daily", "type": "bar"})
    return {
        "manifest": {
            "cards": [{"id": "latest", "dataset": "monthly"}],
            "charts": charts,
            "tables": [{"id": "rows", "dataset": "monthly"}],
        },
        "snapshot": {"datasets": {"monthly": [{"date": "2026-06", "value": value}]}},
        "sources": [{"id": "official", "url": "https://example.test/source"}],
    }


def _contracts(before: dict | None, after: dict | None) -> tuple[dict, dict]:
    path = "apps/asia-markets-dashboard/.generated/hk-example-artifact.json"
    return (
        {path: checker.artifact_contract(before)},
        {path: checker.artifact_contract(after)},
    )


def test_value_only_artifact_refresh_is_quiet() -> None:
    before, after = _contracts(_artifact(value=1), _artifact(value=2))

    assessment = checker.assess_changes(list(before), before, after)

    assert assessment["needs_review"] is False
    assert assessment["structural_artifacts"] == []
    assert "value-only refreshes" in checker.report_markdown(assessment)


def test_artifact_contract_change_requires_review() -> None:
    before, after = _contracts(_artifact(), _artifact(add_chart=True))

    assessment = checker.assess_changes(list(before), before, after)

    assert assessment["needs_review"] is True
    assert assessment["affected"] == ["hk-example"]
    assert assessment["structural_artifacts"] == list(before)
    report = checker.report_markdown(assessment)
    assert "Streamlit parity review required" in report
    assert "Cloudflare artifact contract changed" in report


def test_pipeline_and_ui_changes_require_review() -> None:
    paths = [
        "apps/asia-markets-dashboard/scripts/build_hk_example_artifact.py",
        "apps/asia-markets-dashboard/src/pages/sector.astro",
        "src/hk_example/pipeline.py",
        "apps/asia-markets-dashboard/sectors.json",
    ]

    assessment = checker.assess_changes(paths, {}, {})

    assert assessment["needs_review"] is True
    assert assessment["reasons"] == [
        "Cloudflare builder or packaging code changed",
        "Cloudflare dashboard UI code changed",
        "shared Hong Kong/Asia source pipeline changed",
        "sector roster changed",
    ]


def test_protocol_only_change_does_not_create_a_parity_decision() -> None:
    assessment = checker.assess_changes([checker.PROTOCOL_PATH], {}, {})

    assert assessment["needs_review"] is False


# --- push events with no diffable base ------------------------------------
#
# On a push, the base is `github.event.before`. A force-push orphans that
# commit, and the runner's fresh clone never receives unreachable objects, so
# `git diff` against it dies with "fatal: bad object" and the whole parity job
# fails. That is what took down the check on codex/ops-control-plane-phase1.
#
# These drive real repositories, because the bug only exists in git's object
# reachability -- and note the clone below must be --no-local: cloning from a
# path hardlinks the entire object store, unreachable commits included, which
# makes the broken case silently pass.

import subprocess


def _git(repo, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _force_pushed_clone(tmp_path):
    """A clone whose `event.before` SHA is unreachable, as after a force-push."""
    upstream = tmp_path / "up.git"
    subprocess.run(["git", "init", "-q", "-b", "main", "--bare", str(upstream)], check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(upstream), str(work)], check=True)
    _git(work, "config", "user.email", "t@e.com")
    _git(work, "config", "user.name", "T")

    target = work / "apps" / "asia-markets-dashboard"
    target.mkdir(parents=True)
    (target / "app.py").write_text("v1\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "base")
    _git(work, "push", "-q", "origin", "main")

    (target / "app.py").write_text("v2\n")
    _git(work, "commit", "-qam", "work")
    _git(work, "push", "-q", "origin", "main")
    orphaned = _git(work, "rev-parse", "HEAD")

    _git(work, "commit", "-q", "--amend", "-m", "work amended")
    _git(work, "push", "-qf", "origin", "main")
    head = _git(work, "rev-parse", "HEAD")

    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", "--no-local", str(upstream), str(fresh)], check=True)
    return fresh, orphaned, head


def test_a_force_pushed_base_does_not_crash_the_parity_check(tmp_path, monkeypatch) -> None:
    fresh, orphaned, head = _force_pushed_clone(tmp_path)
    assert subprocess.run(
        ["git", "cat-file", "-e", orphaned], cwd=fresh, capture_output=True
    ).returncode != 0, "the base must really be unreachable or this proves nothing"

    monkeypatch.setattr(checker, "REPO_ROOT", fresh)

    paths = checker.changed_paths(orphaned, head)

    assert paths == ["apps/asia-markets-dashboard/app.py"]


def test_a_reachable_base_still_diffs_the_full_range(tmp_path, monkeypatch) -> None:
    # The fallback must not swallow the normal case.
    fresh, _, head = _force_pushed_clone(tmp_path)
    monkeypatch.setattr(checker, "REPO_ROOT", fresh)
    base = _git(fresh, "rev-parse", "HEAD~1")

    assert checker.changed_paths(base, head) == ["apps/asia-markets-dashboard/app.py"]


def test_a_created_branch_still_reports_the_head_commit(tmp_path, monkeypatch) -> None:
    fresh, _, head = _force_pushed_clone(tmp_path)
    monkeypatch.setattr(checker, "REPO_ROOT", fresh)

    assert checker.changed_paths("0" * 40, head) == ["apps/asia-markets-dashboard/app.py"]
