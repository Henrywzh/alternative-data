from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC
from typing import Any

import requests

from openrouter_data.exceptions import ExtractionError, ValidationError
from openrouter_data.models import DatasetRecord, RunContext, Snapshot
from openrouter_data.sources.base import SourceExtractor
from openrouter_data.utils import iter_next_f_decoded_strings, iter_next_f_objects, walk_json


@dataclass(frozen=True)
class MonitoredApp:
    slug: str
    origin_url: str
    source_url: str
    app_name: str
    fallback_source_urls: tuple[str, ...] = ()


MONITORED_APPS = (
    MonitoredApp(
        slug="openclaw",
        origin_url="https://openclaw.ai/",
        source_url="https://openrouter.ai/apps/openclaw",
        app_name="OpenClaw",
        fallback_source_urls=("https://openrouter.ai/apps?url=https%3A%2F%2Fopenclaw.ai%2F",),
    ),
    MonitoredApp(
        slug="hermes-agent",
        origin_url="https://hermes-agent.nousresearch.com/",
        source_url="https://openrouter.ai/apps/hermes-agent",
        app_name="Hermes Agent",
        fallback_source_urls=("https://openrouter.ai/apps?url=https%3A%2F%2Fhermes-agent.nousresearch.com%2F",),
    ),
)


class AppsSource(SourceExtractor):
    name = "openrouter_apps"

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "openrouter-alternative-data/0.2 (+https://github.com/Henrywzh/alternative-data)",
            }
        )

    def fetch_snapshots(self) -> list[Snapshot]:
        snapshots = [self._fetch("apps_directory", "https://openrouter.ai/apps")]
        for app in MONITORED_APPS:
            snapshots.append(self._fetch_app_snapshot(app))
        return snapshots

    def _fetch(self, name: str, url: str) -> Snapshot:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return Snapshot(name=name, source_url=url, body=response.text)

    def _fetch_app_snapshot(self, app: MonitoredApp) -> Snapshot:
        candidate_urls = (app.source_url, *app.fallback_source_urls)
        last_snapshot: Snapshot | None = None
        for url in candidate_urls:
            snapshot = self._fetch(f"app_{app.slug}", url)
            last_snapshot = snapshot
            if self._looks_like_app_detail_page(snapshot.body, app):
                return snapshot
        if last_snapshot is None:
            raise ExtractionError(f"Could not fetch snapshot for app {app.slug}")
        return last_snapshot

    @staticmethod
    def _looks_like_app_detail_page(html: str, app: MonitoredApp) -> bool:
        required_signals = (
            app.app_name,
            "forecast-1d",
            "appModelAnalytics",
        )
        return all(signal in html for signal in required_signals)

    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[DatasetRecord]]:
        snapshot_by_name = {snapshot.name: snapshot for snapshot in snapshots}
        directory_snapshot = snapshot_by_name["apps_directory"]
        ranking_map = self._extract_ranking_map(directory_snapshot.body)
        trending_apps = self._extract_trending_payload(directory_snapshot.body)

        extracted: dict[str, list[DatasetRecord]] = {
            "apps_global_ranking_snapshots": self._global_ranking_records(
                ranking_map=ranking_map,
                snapshot=directory_snapshot,
                context=context,
            ),
            "apps_trending_snapshots": self._trending_records(
                trending_apps=trending_apps,
                snapshot=directory_snapshot,
                context=context,
            ),
        }

        metadata_records: list[DatasetRecord] = []
        usage_records: list[DatasetRecord] = []
        top_model_records: list[DatasetRecord] = []
        for app in MONITORED_APPS:
            app_snapshot = snapshot_by_name[f"app_{app.slug}"]
            app_metadata = self._extract_app_metadata(app_snapshot.body, app)
            metadata_records.extend(self._app_metadata_records(app_metadata, app_snapshot, context))
            usage_records.extend(self._usage_records(app_metadata, app_snapshot, context))
            top_model_records.extend(self._top_model_records(app_metadata, app_snapshot, context))

        extracted["app_metadata_snapshots"] = metadata_records
        extracted["app_usage_daily"] = usage_records
        extracted["app_top_models_daily_snapshot"] = top_model_records
        return extracted

    def _extract_trending_payload(self, html: str) -> list[dict[str, Any]]:
        for payload in iter_next_f_objects(html):
            for node in walk_json(payload):
                if isinstance(node, dict) and "growthPercent" in node and "appAnalytics" in node:
                    return [item for item in walk_json(payload) if isinstance(item, dict) and "growthPercent" in item and "appAnalytics" in item]
        raise ExtractionError("Could not find trending payload in /apps")

    def _extract_ranking_map(self, html: str) -> dict[str, list[dict[str, Any]]]:
        chunks = self._parse_flight_chunks(html)
        for parsed in chunks.values():
            for node in walk_json(parsed):
                if isinstance(node, dict) and "rankingMap" in node:
                    ranking_map = self._resolve_ranking_map(node["rankingMap"], chunks)
                    if self._is_ranking_map(ranking_map):
                        return ranking_map
                if self._is_ranking_map(node):
                    return node
        return self._extract_ranking_map_with_playwright()

    @staticmethod
    def _is_ranking_map(node: Any) -> bool:
        return (
            isinstance(node, dict)
            and {"day", "week", "month"}.issubset(node.keys())
            and all(isinstance(node[key], list) for key in ("day", "week", "month"))
        )

    def _parse_flight_chunks(self, html: str) -> dict[str, Any]:
        chunks: dict[str, Any] = {}
        for decoded in iter_next_f_decoded_strings(html):
            if ":" not in decoded:
                continue
            label, payload = decoded.split(":", 1)
            payload = payload.strip()
            if not payload.startswith("[") and not payload.startswith("{"):
                continue
            try:
                chunks[label] = json.loads(payload)
            except json.JSONDecodeError:
                continue
        return chunks

    def _resolve_ranking_map(self, ranking_map: dict[str, Any], chunks: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        resolved: dict[str, list[dict[str, Any]]] = {}
        for period in ("day", "week", "month"):
            value = ranking_map.get(period)
            value = self._resolve_flight_reference(value, chunks) if isinstance(value, str) else value
            resolved[period] = value
        return resolved

    def _resolve_flight_reference(self, reference: str, chunks: dict[str, Any]) -> Any:
        if not reference.startswith("$"):
            return reference

        path_parts = reference[1:].split(":")
        label, path = path_parts[0], path_parts[1:]
        node = chunks.get(label)
        if node is None:
            raise ExtractionError(f"Could not resolve flight reference {reference}")

        for part in path:
            if part == "props":
                if isinstance(node, list) and len(node) > 3:
                    node = node[3]
                elif isinstance(node, dict) and "props" in node:
                    node = node["props"]
                else:
                    raise ExtractionError(f"Invalid props reference {reference}")
                continue
            if part == "children":
                if isinstance(node, dict):
                    node = node.get("children")
                else:
                    raise ExtractionError(f"Invalid children reference {reference}")
                continue
            if part.isdigit():
                node = node[int(part)]
                continue
            if isinstance(node, dict):
                node = node.get(part)
            else:
                raise ExtractionError(f"Invalid flight reference segment {part} in {reference}")
        return node

    def _extract_ranking_map_with_playwright(self) -> dict[str, list[dict[str, Any]]]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ExtractionError("Global ranking map not found in HTML and Playwright is unavailable") from exc

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1800})
            try:
                page.goto("https://openrouter.ai/apps", wait_until="domcontentloaded", timeout=self.timeout * 1000)
                next_f_strings = page.evaluate(
                    """
                    () => (Array.isArray(self.__next_f) ? self.__next_f : [])
                      .filter((entry) => Array.isArray(entry) && entry.length > 1 && typeof entry[1] === "string")
                      .map((entry) => entry[1])
                    """
                )
            finally:
                browser.close()

        chunks: dict[str, Any] = {}
        for decoded in next_f_strings:
            if '"rankingMap"' not in decoded or ":" not in decoded:
                continue
            label, payload = decoded.split(":", 1)
            try:
                chunks[label] = json.loads(payload)
            except json.JSONDecodeError:
                continue
        for parsed in chunks.values():
            for node in walk_json(parsed):
                if isinstance(node, dict) and "rankingMap" in node:
                    ranking_map = self._resolve_ranking_map(node["rankingMap"], chunks)
                    if self._is_ranking_map(ranking_map):
                        return ranking_map
                if self._is_ranking_map(node):
                    return node
        raise ExtractionError("Could not find global ranking payload in /apps")

    def _extract_app_metadata(self, html: str, app: MonitoredApp) -> dict[str, Any]:
        best_match: dict[str, Any] | None = None
        for payload in iter_next_f_objects(html):
            for node in walk_json(payload):
                if not isinstance(node, dict):
                    continue
                if "id" not in node:
                    continue
                origin_matches = node.get("origin_url") == app.origin_url
                title_matches = node.get("title") == app.app_name
                if not origin_matches and not title_matches:
                    continue
                if best_match is None or len(node) > len(best_match):
                    best_match = node
        if best_match is None:
            raise ExtractionError(f"Could not find app metadata for {app.origin_url}")
        return best_match

    def _extract_usage_chart(self, html: str, app_name: str) -> dict[str, Any]:
        for payload in iter_next_f_objects(html):
            for node in walk_json(payload):
                if not isinstance(node, dict):
                    continue
                if node.get("appName") != app_name or node.get("forecast") != "forecast-1d":
                    continue
                if self._is_usage_chart(node):
                    return node
        raise ExtractionError(f"Could not find usage chart payload for {app_name}")

    @staticmethod
    def _is_usage_chart(node: Any) -> bool:
        if not isinstance(node, dict):
            return False
        data = node.get("data")
        return isinstance(data, list) and bool(data) and isinstance(data[0], dict) and "x" in data[0] and "ys" in data[0]

    def _extract_top_models_payload(self, html: str, app_name: str) -> list[dict[str, Any]]:
        for payload in iter_next_f_objects(html):
            for node in walk_json(payload):
                if not isinstance(node, dict):
                    continue
                if node.get("appName") != app_name or "appModelAnalytics" not in node:
                    continue
                records = node["appModelAnalytics"]
                if isinstance(records, list) and records:
                    return records
        raise ExtractionError(f"Could not find top-model payload for {app_name}")

    def _app_metadata_records(
        self,
        app_metadata: dict[str, Any],
        snapshot: Snapshot,
        context: RunContext,
    ) -> list[DatasetRecord]:
        scrape_date = context.scraped_at.astimezone(UTC).date().isoformat()
        return [
            DatasetRecord(
                dataset_id="app_metadata_snapshots",
                source_url=snapshot.source_url,
                source_run_id=context.run_id,
                scraped_at=context.scraped_at_iso,
                app_id=str(app_metadata["id"]),
                app_name=app_metadata.get("title"),
                origin_url=app_metadata.get("origin_url"),
                main_url=app_metadata.get("main_url"),
                description=app_metadata.get("description"),
                categories=self._serialize_categories(app_metadata.get("categories")),
                group_by_origin=app_metadata.get("group_by_origin"),
                is_private=app_metadata.get("is_private"),
                is_hidden=app_metadata.get("is_hidden"),
                created_at=app_metadata.get("created_at"),
                scrape_date=scrape_date,
            )
        ]

    def _usage_records(
        self,
        app_metadata: dict[str, Any],
        snapshot: Snapshot,
        context: RunContext,
    ) -> list[DatasetRecord]:
        app_id = str(app_metadata["id"])
        app_name = app_metadata.get("title")
        chart = self._extract_usage_chart(snapshot.body, app_name)
        records: list[DatasetRecord] = []
        for point in chart["data"]:
            usage_date = point["x"].split(" ", 1)[0]
            daily_records = [
                DatasetRecord(
                    dataset_id="app_usage_daily",
                    source_url=snapshot.source_url,
                    source_run_id=context.run_id,
                    scraped_at=context.scraped_at_iso,
                    app_id=app_id,
                    app_name=app_name,
                    origin_url=app_metadata.get("origin_url"),
                    categories=self._serialize_categories(app_metadata.get("categories")),
                    usage_date=usage_date,
                    model_permaslug=model_permaslug,
                    total_tokens=float(total_tokens),
                    rank=0,
                )
                for model_permaslug, total_tokens in point["ys"].items()
            ]
            daily_records.sort(key=lambda record: (record.total_tokens or 0), reverse=True)
            for rank, record in enumerate(daily_records, start=1):
                records.append(DatasetRecord(**{**record.to_dict(), "rank": rank}))
        if not records:
            raise ValidationError(f"App usage dataset produced no records for {app_name}")
        return records

    def _top_model_records(
        self,
        app_metadata: dict[str, Any],
        snapshot: Snapshot,
        context: RunContext,
    ) -> list[DatasetRecord]:
        app_id = str(app_metadata["id"])
        app_name = app_metadata.get("title")
        payload = self._extract_top_models_payload(snapshot.body, app_name)
        ordered = sorted(payload, key=lambda item: float(item["total_tokens"]), reverse=True)
        records = [
            DatasetRecord(
                dataset_id="app_top_models_daily_snapshot",
                source_url=snapshot.source_url,
                source_run_id=context.run_id,
                scraped_at=context.scraped_at_iso,
                app_id=app_id,
                app_name=app_name,
                origin_url=app_metadata.get("origin_url"),
                categories=self._serialize_categories(app_metadata.get("categories")),
                snapshot_date=item["date"],
                model_permaslug=item["model_permaslug"],
                total_tokens=float(item["total_tokens"]),
                rank=rank,
            )
            for rank, item in enumerate(ordered, start=1)
        ]
        if not records:
            raise ValidationError(f"Top-model dataset produced no records for {app_name}")
        return records

    def _global_ranking_records(
        self,
        *,
        ranking_map: dict[str, list[dict[str, Any]]],
        snapshot: Snapshot,
        context: RunContext,
    ) -> list[DatasetRecord]:
        snapshot_date = context.scraped_at.astimezone(UTC).date().isoformat()
        records: list[DatasetRecord] = []
        for period, rows in ranking_map.items():
            for row in rows:
                app = row.get("app") or {}
                records.append(
                    DatasetRecord(
                        dataset_id="apps_global_ranking_snapshots",
                        source_url=snapshot.source_url,
                        source_run_id=context.run_id,
                        scraped_at=context.scraped_at_iso,
                        app_id=str(row["app_id"]),
                        app_name=app.get("title"),
                        origin_url=app.get("origin_url"),
                        main_url=app.get("main_url"),
                        description=app.get("description"),
                        categories=self._serialize_categories(app.get("categories")),
                        snapshot_date=snapshot_date,
                        observed_at=context.scraped_at_iso,
                        period=period,
                        tokens=float(row["total_tokens"]),
                        rank=int(row["rank"]),
                    )
                )
        if not records:
            raise ValidationError("Global ranking dataset produced no records")
        return records

    def _trending_records(
        self,
        *,
        trending_apps: list[dict[str, Any]],
        snapshot: Snapshot,
        context: RunContext,
    ) -> list[DatasetRecord]:
        snapshot_date = context.scraped_at.astimezone(UTC).date().isoformat()
        ordered = sorted(
            trending_apps,
            key=lambda item: (
                float(item.get("growthPercent", 0)),
                float((item.get("appAnalytics") or {}).get("total_tokens", 0)),
            ),
            reverse=True,
        )
        records = []
        for rank, item in enumerate(ordered, start=1):
            app_analytics = item["appAnalytics"]
            app = app_analytics.get("app") or {}
            records.append(
                DatasetRecord(
                    dataset_id="apps_trending_snapshots",
                    source_url=snapshot.source_url,
                    source_run_id=context.run_id,
                    scraped_at=context.scraped_at_iso,
                    app_id=str(app_analytics["app_id"]),
                    app_name=app.get("title"),
                    origin_url=app.get("origin_url"),
                    main_url=app.get("main_url"),
                    description=app.get("description"),
                    categories=self._serialize_categories(app.get("categories")),
                    snapshot_date=snapshot_date,
                    observed_at=context.scraped_at_iso,
                    tokens=float(app_analytics.get("total_tokens", 0)),
                    growth_percent=float(item.get("growthPercent", 0)),
                    rank=rank,
                )
            )
        if not records:
            raise ValidationError("Trending dataset produced no records")
        return records

    @staticmethod
    def _serialize_categories(categories: Any) -> str | None:
        if not categories:
            return None
        if isinstance(categories, list):
            return "|".join(str(category) for category in categories)
        return str(categories)
