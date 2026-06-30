from __future__ import annotations

import json
from typing import Any

import requests

from openrouter_data.exceptions import ExtractionError
from openrouter_data.models import DatasetRecord, RunContext, Snapshot
from openrouter_data.sources.base import SourceExtractor


TASK_SPEND_DATASET_ID = "openrouter_task_spend"


class TaskSpendSource(SourceExtractor):
    """Fetch OpenRouter's task-level spend/token ranking frontend payload."""

    name = "openrouter_task_spend"
    URL = "https://openrouter.ai/api/frontend/v1/rankings/task-spend"
    DEFAULT_WINDOWS = (7, 30, 90)

    def __init__(self, timeout: int = 30, windows: tuple[int, ...] = DEFAULT_WINDOWS) -> None:
        self.timeout = timeout
        self.windows = windows

    def fetch_snapshots(self) -> list[Snapshot]:
        snapshots: list[Snapshot] = []
        for window_days in self.windows:
            source_url = f"{self.URL}?window={window_days}d"
            response = requests.get(
                source_url,
                timeout=self.timeout,
                headers={
                    "User-Agent": "openrouter-alternative-data/0.2 (+https://github.com/Henrywzh/alternative-data)"
                },
            )
            response.raise_for_status()
            snapshots.append(
                Snapshot(name=f"rankings_task_spend_{window_days}d", source_url=source_url, body=response.text)
            )
        return snapshots

    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[DatasetRecord]]:
        task_snapshots = [item for item in snapshots if item.name.startswith("rankings_task_spend")]
        if not task_snapshots:
            raise ExtractionError("Missing rankings_task_spend snapshot")

        records: list[DatasetRecord] = []
        for snapshot in task_snapshots:
            records.extend(self._extract_snapshot(snapshot, context))

        if not records:
            raise ExtractionError("OpenRouter task-spend payload did not contain spend or token task rows")
        return {TASK_SPEND_DATASET_ID: records}

    def _extract_snapshot(self, snapshot: Snapshot, context: RunContext) -> list[DatasetRecord]:
        try:
            payload = json.loads(snapshot.body)
        except json.JSONDecodeError as exc:
            raise ExtractionError("OpenRouter task-spend payload is not valid JSON") from exc

        data = payload.get("data")
        if not isinstance(data, dict):
            raise ExtractionError("OpenRouter task-spend payload is missing data")

        snapshot_date = context.scraped_at.date().isoformat()
        records: list[DatasetRecord] = []
        for period in ("spend", "tokens"):
            view = data.get(period)
            if not isinstance(view, dict):
                continue
            records.extend(self._extract_view(period=period, view=view, snapshot=snapshot, context=context, snapshot_date=snapshot_date))

        return records

    def _extract_view(
        self,
        *,
        period: str,
        view: dict[str, Any],
        snapshot: Snapshot,
        context: RunContext,
        snapshot_date: str,
    ) -> list[DatasetRecord]:
        window_days = _safe_int(view.get("windowDays"))
        tasks = view.get("tasks")
        if not isinstance(tasks, list):
            return []

        records: list[DatasetRecord] = []
        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_tag = _clean_str(task.get("tag"))
            macro_category = _clean_str(task.get("macroCategory"))
            task_share = _safe_float(task.get("spendShareOfTotal"))
            models = task.get("models")
            if not task_tag or not isinstance(models, list):
                continue

            for rank, model in enumerate(models, start=1):
                if not isinstance(model, dict):
                    continue
                model_id = _clean_str(model.get("model"))
                if not model_id:
                    continue
                records.append(
                    DatasetRecord(
                        dataset_id=TASK_SPEND_DATASET_ID,
                        source_url=snapshot.source_url,
                        source_run_id=context.run_id,
                        scraped_at=context.scraped_at_iso,
                        snapshot_date=snapshot_date,
                        observed_at=context.scraped_at_iso,
                        period=period,
                        window_days=window_days,
                        category_slug=task_tag,
                        macro_category=macro_category,
                        task_share_of_total=task_share,
                        model_permaslug=model_id,
                        model_share=_safe_float(model.get("share")),
                        delta_pp=_safe_float(model.get("deltaPp")),
                        rank=rank,
                        metric_name=f"{period}_share_within_task",
                        metric_unit="share",
                        metric_value=_safe_float(model.get("share")),
                    )
                )
        return records


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
