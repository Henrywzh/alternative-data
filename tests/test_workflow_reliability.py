from __future__ import annotations

from pathlib import Path


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def test_model_activity_workflow_stages_archive_only_when_it_exists() -> None:
    workflow = (WORKFLOWS / "openrouter-model-activity-daily.yml").read_text(encoding="utf-8")

    assert "if [ -d data/normalized/openrouter_archive ]; then" in workflow
    assert "git add data/normalized/openrouter_archive" in workflow


def test_fred_workflow_accepts_the_existing_semiconductor_fred_secret() -> None:
    workflow = (WORKFLOWS / "fred-macro-daily.yml").read_text(encoding="utf-8")

    assert "secrets.FRED_API_KEY || secrets.SEMICONDUCTOR_FRED_API_KEY" in workflow
