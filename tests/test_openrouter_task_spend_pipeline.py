from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from openrouter_data.models import RunContext, Snapshot
from openrouter_data.pipeline import TaskSpendPipeline
from openrouter_data.sources.task_spend import TaskSpendSource


def _payload(*, window_days: int = 30) -> dict:
    return {
        "data": {
            "spend": {
                "windowDays": window_days,
                "macroCategories": [
                    {"key": "agent", "label": "Agent", "spendShare": 0.6},
                    {"key": "code", "label": "Code", "spendShare": 0.4},
                ],
                "tasks": [
                    {
                        "tag": "agent:workflow_execution",
                        "macroCategory": "agent",
                        "spendShareOfTotal": 0.25,
                        "models": [
                            {"model": "anthropic/claude-4.7-opus-20260416", "share": 0.7, "deltaPp": 70.0},
                            {"model": "openai/gpt-5.5-20260423", "share": 0.3, "deltaPp": 30.0},
                        ],
                    }
                ],
            },
            "tokens": {
                "windowDays": window_days,
                "macroCategories": [
                    {"key": "agent", "label": "Agent", "spendShare": 0.5},
                ],
                "tasks": [
                    {
                        "tag": "agent:workflow_execution",
                        "macroCategory": "agent",
                        "spendShareOfTotal": 0.2,
                        "models": [
                            {"model": "google/gemini-3-flash-preview-20251217", "share": 0.55, "deltaPp": 55.0},
                        ],
                    }
                ],
            },
        }
    }


def _snapshot(*, window_days: int = 30) -> Snapshot:
    return Snapshot(
        name=f"rankings_task_spend_{window_days}d",
        source_url=f"https://openrouter.ai/api/frontend/v1/rankings/task-spend?window={window_days}d",
        body=json.dumps(_payload(window_days=window_days)),
    )


def test_task_spend_source_extracts_spend_and_token_rows() -> None:
    source = TaskSpendSource()
    context = RunContext(run_id="task-spend-test", scraped_at=pd.Timestamp("2026-06-30T12:00:00Z").to_pydatetime())

    extracted = source.extract([_snapshot()], context)

    records = extracted["openrouter_task_spend"]
    assert len(records) == 3

    first = records[0]
    assert first.snapshot_date == "2026-06-30"
    assert first.period == "spend"
    assert first.window_days == 30
    assert first.category_slug == "agent:workflow_execution"
    assert first.macro_category == "agent"
    assert first.task_share_of_total == 0.25
    assert first.model_permaslug == "anthropic/claude-4.7-opus-20260416"
    assert first.model_share == 0.7
    assert first.delta_pp == 70.0
    assert first.rank == 1

    token_row = records[-1]
    assert token_row.period == "tokens"
    assert token_row.model_permaslug == "google/gemini-3-flash-preview-20251217"


def test_task_spend_source_keeps_rolling_windows_separate() -> None:
    source = TaskSpendSource()
    context = RunContext(run_id="task-spend-test", scraped_at=pd.Timestamp("2026-06-30T12:00:00Z").to_pydatetime())

    extracted = source.extract([_snapshot(window_days=7), _snapshot(window_days=30)], context)

    records = extracted["openrouter_task_spend"]
    assert len(records) == 6
    assert sorted({record.window_days for record in records}) == [7, 30]


def test_task_spend_pipeline_upserts_daily_snapshots(tmp_path: Path, monkeypatch) -> None:
    pipeline = TaskSpendPipeline(tmp_path)
    monkeypatch.setattr(pipeline.source, "fetch_snapshots", lambda: [_snapshot()])
    monkeypatch.setattr(
        pipeline,
        "_create_context",
        lambda run_id=None: RunContext(
            run_id=run_id or "task-spend-run",
            scraped_at=pd.Timestamp("2026-06-30T12:00:00Z").to_pydatetime(),
        ),
    )

    first = pipeline.run_daily_update()
    second = pipeline.run_daily_update()

    path = tmp_path / "data" / "normalized" / "openrouter" / "openrouter_task_spend.parquet"
    written = pd.read_parquet(path)
    assert first.datasets_written["openrouter_task_spend"] == 3
    assert second.datasets_written["openrouter_task_spend"] == 3
    assert len(written) == 3
    assert written[["snapshot_date", "period", "window_days", "category_slug", "model_permaslug"]].duplicated().sum() == 0
