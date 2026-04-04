from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from openrouter_data.exceptions import ExtractionError, ValidationError
from openrouter_data.models import DatasetRecord, RunContext, Snapshot
from openrouter_data.sources.base import SourceExtractor
from openrouter_data.utils import (
    humanize_identifier,
    infer_completed_week_dates,
    iter_next_f_objects,
    slug_author,
    walk_json,
)


@dataclass(frozen=True)
class DatasetSpec:
    dataset_id: str
    source_url: str
    metric_name: str
    metric_unit: str
    week_anchor: str
    category_slug: str | None = None


TOP_MODELS_SPEC = DatasetSpec(
    dataset_id="top_models",
    source_url="https://openrouter.ai/rankings",
    metric_name="tokens",
    metric_unit="tokens",
    week_anchor="start",
)

MARKET_SHARE_SPEC = DatasetSpec(
    dataset_id="market_share",
    source_url="https://openrouter.ai/rankings",
    metric_name="token_share_pct",
    metric_unit="share",
    week_anchor="end",
)

CATEGORIES_PROGRAMMING_SPEC = DatasetSpec(
    dataset_id="categories_programming",
    source_url="https://openrouter.ai/rankings/programming",
    metric_name="tokens",
    metric_unit="tokens",
    week_anchor="start",
    category_slug="programming",
)


class RankingsSource(SourceExtractor):
    name = "openrouter_rankings"

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "openrouter-alternative-data/0.1 (+https://github.com/Henrywzh/alternative-data)",
            }
        )

    def fetch_snapshots(self) -> list[Snapshot]:
        return [
            self._fetch("rankings", TOP_MODELS_SPEC.source_url),
            self._fetch("rankings_programming", CATEGORIES_PROGRAMMING_SPEC.source_url),
        ]

    def _fetch(self, name: str, url: str) -> Snapshot:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return Snapshot(name=name, source_url=url, body=response.text)

    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[DatasetRecord]]:
        snapshot_by_name = {snapshot.name: snapshot for snapshot in snapshots}
        rankings_html = snapshot_by_name["rankings"].body
        programming_html = snapshot_by_name["rankings_programming"].body

        top_models_chart = self._find_chart(
            rankings_html,
            predicate=lambda chart: chart.get("forecast") == "forecast-1w",
            label="top_models",
        )
        market_share_chart = self._find_chart(
            rankings_html,
            predicate=self._looks_like_market_share_chart,
            label="market_share",
        )
        categories_programming_chart = self._find_chart(
            programming_html,
            predicate=lambda chart: chart.get("testId") == "model-rankings-categories-chart",
            label="categories_programming",
        )

        return {
            TOP_MODELS_SPEC.dataset_id: self._records_from_chart(top_models_chart, TOP_MODELS_SPEC, context),
            MARKET_SHARE_SPEC.dataset_id: self._records_from_chart(market_share_chart, MARKET_SHARE_SPEC, context),
            CATEGORIES_PROGRAMMING_SPEC.dataset_id: self._records_from_chart(
                categories_programming_chart,
                CATEGORIES_PROGRAMMING_SPEC,
                context,
            ),
        }

    def _find_chart(self, html: str, *, predicate: Any, label: str) -> dict[str, Any]:
        for payload in iter_next_f_objects(html):
            for node in walk_json(payload):
                if self._is_chart_candidate(node) and predicate(node):
                    return node
        raise ExtractionError(f"Could not find chart payload for {label}")

    @staticmethod
    def _is_chart_candidate(node: Any) -> bool:
        if not isinstance(node, dict):
            return False
        data = node.get("data")
        if not isinstance(data, list) or not data:
            return False
        first = data[0]
        return isinstance(first, dict) and "x" in first and "ys" in first

    @staticmethod
    def _looks_like_market_share_chart(chart: dict[str, Any]) -> bool:
        data = chart.get("data", [])
        if not data:
            return False
        ys = data[0].get("ys", {})
        if not isinstance(ys, dict):
            return False
        keys = list(ys.keys())
        if not keys:
            return False
        return all("/" not in key for key in keys)

    def _records_from_chart(
        self,
        chart: dict[str, Any],
        spec: DatasetSpec,
        context: RunContext,
    ) -> list[DatasetRecord]:
        raw_points = chart["data"]
        completed_weeks = infer_completed_week_dates(
            [point["x"] for point in raw_points],
            context.scraped_at,
            week_anchor=spec.week_anchor,
        )
        if not completed_weeks:
            raise ValidationError(f"No completed weeks available for dataset {spec.dataset_id}")

        records: list[DatasetRecord] = []
        for point in raw_points:
            if point["x"] not in completed_weeks:
                continue
            week_records = []
            for entity_id, metric_value in point["ys"].items():
                parent_entity_id = None
                parent_entity_name = None
                entity_name = entity_id
                if spec.dataset_id != MARKET_SHARE_SPEC.dataset_id:
                    parent_entity_id = slug_author(entity_id)
                    parent_entity_name = parent_entity_id
                else:
                    entity_name = humanize_identifier(entity_id)
                week_records.append(
                    DatasetRecord(
                        dataset_id=spec.dataset_id,
                        week_label=point["x"],
                        week_start_date=point["x"],
                        entity_id=entity_id,
                        entity_name=entity_name,
                        parent_entity_id=parent_entity_id,
                        parent_entity_name=parent_entity_name,
                        metric_name=spec.metric_name,
                        metric_unit=spec.metric_unit,
                        metric_value=float(metric_value),
                        rank=0,
                        source_url=spec.source_url,
                        source_run_id=context.run_id,
                        scraped_at=context.scraped_at_iso,
                        category_slug=spec.category_slug,
                    )
                )

            week_records.sort(key=lambda item: item.metric_value, reverse=True)
            for rank, record in enumerate(week_records, start=1):
                records.append(
                    DatasetRecord(
                        **{
                            **record.to_dict(),
                            "rank": rank,
                        }
                    )
                )

        if not records:
            raise ValidationError(f"Dataset {spec.dataset_id} produced no normalized records")
        return records
