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
