from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import requests

from openrouter_data.exceptions import ExtractionError, ValidationError
from openrouter_data.models import DatasetRecord, RunContext, Snapshot
from openrouter_data.sources.base import SourceExtractor
from openrouter_data.utils import (
    humanize_identifier,
    infer_completed_week_dates,
    iter_next_f_chunks,
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
    context_length_bucket: str | None = None
    modality: str | None = None


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

PROVIDER_WEEKLY_REQUESTS_SPEC = DatasetSpec(
    dataset_id="provider_weekly_requests",
    source_url="https://openrouter.ai/rankings",
    metric_name="requests",
    metric_unit="requests",
    week_anchor="end",
)

# categories_programming is retired.
#
# OpenRouter deleted /rankings/programming. The route answers 200 and renders
# a client-side "404: Not Found", so raise_for_status() saw nothing wrong and
# the chart was simply absent; the categories testId is gone from /rankings
# too, and model-rankings-chart returns byte identical responses for
# category, routeSegment and categorySlug, so no parameter brings it back.
# The current page has a Programming section, but it breaks down by language
# rather than ranking models within a category -- a different series, not a
# new address for this one.
#
# The 104 weeks already collected (2025-05-19 to 2026-08-03) stay on disk and
# stay readable: storage.py keeps this dataset's keys. Nothing writes it.

CONTEXT_LENGTH_BUCKETS = ("1K", "10K", "100K", "1M", "10M")
CONTEXT_LENGTH_LABELS = {
    "1K": "<1K",
    "10K": "1K-10K",
    "100K": "10K-100K",
    "1M": "100K-1M",
    "10M": "1M-10M",
}
CONTEXT_LENGTH_DATASET_ID = "context_length_requests"

MODALITIES = ("image", "embeddings", "rerank", "video", "speech", "transcription")
MODALITY_METRIC_UNITS = {
    "image": "tokens",
    "embeddings": "tokens",
    "rerank": "requests",
    "video": "seconds",
    "speech": "seconds",
    "transcription": "seconds",
}
MODALITY_RANKINGS_DATASET_ID = "modality_rankings"

MODEL_RANKINGS_CHART_URL = "https://openrouter.ai/api/frontend/v1/rankings/model-rankings-chart"
TEXT_MODALITY_CHART_URL = "https://openrouter.ai/api/frontend/v1/rankings/modality-chart?routeSegment=text"
MODALITY_CHART_URL = "https://openrouter.ai/api/frontend/v1/rankings/modality-chart"
CONTEXT_LENGTH_CHART_URL = "https://openrouter.ai/api/frontend/v1/rankings/context-length"


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
        snapshots = [
            self._fetch("rankings", TOP_MODELS_SPEC.source_url),
            self._fetch_optional("model_rankings_chart", MODEL_RANKINGS_CHART_URL),
            self._fetch_optional("text_modality_chart", TEXT_MODALITY_CHART_URL),
        ]
        for bucket in CONTEXT_LENGTH_BUCKETS:
            snapshots.append(
                self._fetch_optional(
                    f"context_length_{bucket}",
                    f"{CONTEXT_LENGTH_CHART_URL}?bucket={bucket}",
                )
            )
        for modality in MODALITIES:
            snapshots.append(
                self._fetch_optional(
                    f"modality_chart_{modality}",
                    f"{MODALITY_CHART_URL}?routeSegment={modality}",
                )
            )
        return snapshots

    def _fetch(self, name: str, url: str) -> Snapshot:
        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        return Snapshot(name=name, source_url=url, body=response.text)

    def _fetch_optional(self, name: str, url: str) -> Snapshot:
        try:
            return self._fetch(name, url)
        except requests.RequestException as exc:
            logging.warning("OpenRouter rankings API %s is unavailable: %s", name, exc)
            return Snapshot(name=name, source_url=url, body="")

    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[DatasetRecord]]:
        snapshot_by_name = {snapshot.name: snapshot for snapshot in snapshots}
        rankings_html = snapshot_by_name["rankings"].body

        charts = self._extract_chart_payloads_from_api(snapshot_by_name)
        static_charts = self._extract_chart_payloads(rankings_html)
        for label, chart in static_charts.items():
            charts.setdefault(label, chart)
        missing = self._missing_chart_labels(charts)
        if missing:
            logging.warning(
                "Static OpenRouter rankings extraction missed %s; attempting Playwright fallback",
                ", ".join(missing),
            )
            fallback_charts = self._extract_chart_payloads_with_playwright()
            charts.update({label: chart for label, chart in fallback_charts.items() if chart is not None})
            missing = self._missing_chart_labels(charts)
        if missing:
            raise ExtractionError(f"Could not find chart payloads for {', '.join(missing)}")

        return {
            TOP_MODELS_SPEC.dataset_id: self._records_from_chart(charts[TOP_MODELS_SPEC.dataset_id], TOP_MODELS_SPEC, context),
            MARKET_SHARE_SPEC.dataset_id: self._records_from_chart(charts[MARKET_SHARE_SPEC.dataset_id], MARKET_SHARE_SPEC, context),
            **self._extract_context_length_records(charts, context),
            **self._extract_modality_records(charts, context),
            **(
                {
                    PROVIDER_WEEKLY_REQUESTS_SPEC.dataset_id: self._records_from_chart(
                        charts[PROVIDER_WEEKLY_REQUESTS_SPEC.dataset_id],
                        PROVIDER_WEEKLY_REQUESTS_SPEC,
                        context,
                    )
                }
                if charts.get(PROVIDER_WEEKLY_REQUESTS_SPEC.dataset_id)
                else {}
            ),
        }

    def _extract_context_length_records(
        self,
        charts: dict[str, dict[str, Any] | None],
        context: RunContext,
    ) -> dict[str, list[DatasetRecord]]:
        """Normalize the official context-length endpoint without making it a hard dependency.

        The rankings page can still render its core sections if this newer endpoint
        is temporarily unavailable. Missing buckets are therefore skipped and will
        be filled by the next scheduled scrape.
        """
        records: list[DatasetRecord] = []
        for bucket in CONTEXT_LENGTH_BUCKETS:
            chart = charts.get(self._context_chart_key(bucket))
            if not chart:
                continue
            spec = DatasetSpec(
                dataset_id=CONTEXT_LENGTH_DATASET_ID,
                source_url=f"{CONTEXT_LENGTH_CHART_URL}?bucket={bucket}",
                metric_name="requests",
                metric_unit="requests",
                week_anchor="start",
                context_length_bucket=CONTEXT_LENGTH_LABELS[bucket],
            )
            records.extend(self._records_from_chart(chart, spec, context))
        return {CONTEXT_LENGTH_DATASET_ID: records} if records else {}

    def _extract_modality_records(
        self,
        charts: dict[str, dict[str, Any] | None],
        context: RunContext,
    ) -> dict[str, list[DatasetRecord]]:
        """Normalize the per-modality ranking endpoints (image, embeddings, rerank, video, speech, transcription).

        Each modality is fetched independently and is not a hard pipeline dependency:
        if OpenRouter retires or breaks one modality route, that modality is skipped
        for this run and the rest of the rankings pipeline still succeeds.
        """
        records: list[DatasetRecord] = []
        for modality in MODALITIES:
            chart = charts.get(self._modality_chart_key(modality))
            if not chart:
                continue
            spec = DatasetSpec(
                dataset_id=MODALITY_RANKINGS_DATASET_ID,
                source_url=f"{MODALITY_CHART_URL}?routeSegment={modality}",
                metric_name="volume",
                metric_unit=MODALITY_METRIC_UNITS[modality],
                week_anchor="start",
                modality=modality,
            )
            records.extend(self._records_from_chart(chart, spec, context))
        return {MODALITY_RANKINGS_DATASET_ID: records} if records else {}

    @staticmethod
    def _extract_chart_payloads_from_api(snapshot_by_name: dict[str, Snapshot]) -> dict[str, dict[str, Any]]:
        """Use OpenRouter's ranking APIs before falling back to page internals."""
        charts: dict[str, dict[str, Any]] = {}

        model_snapshot = snapshot_by_name.get("model_rankings_chart")
        if model_snapshot is not None:
            try:
                model_payload = json.loads(model_snapshot.body)
                model_data = model_payload.get("data", {}).get("data")
                if RankingsSource._is_chart_data(model_data):
                    charts[TOP_MODELS_SPEC.dataset_id] = {"data": model_data}
            except (AttributeError, json.JSONDecodeError):
                pass

        modality_snapshot = snapshot_by_name.get("text_modality_chart")
        if modality_snapshot is not None:
            try:
                modality_payload = json.loads(modality_snapshot.body)
                market_share_data = modality_payload.get("data", {}).get("marketShareData")
                if RankingsSource._is_chart_data(market_share_data):
                    # `marketShareData` is provider token volume.  It is not a
                    # request-count feed; never publish the same payload under
                    # the requests dataset.
                    charts[MARKET_SHARE_SPEC.dataset_id] = {"data": market_share_data}
            except (AttributeError, json.JSONDecodeError):
                pass

        for bucket in CONTEXT_LENGTH_BUCKETS:
            snapshot = snapshot_by_name.get(f"context_length_{bucket}")
            if snapshot is None or not snapshot.body:
                continue
            try:
                payload = json.loads(snapshot.body)
                data = payload.get("data")
                # This endpoint returns {"data": [{"x": ..., "ys": ...}]}.
                if RankingsSource._is_chart_data(data):
                    charts[RankingsSource._context_chart_key(bucket)] = {"data": data}
            except (AttributeError, json.JSONDecodeError):
                continue

        for modality in MODALITIES:
            snapshot = snapshot_by_name.get(f"modality_chart_{modality}")
            if snapshot is None or not snapshot.body:
                continue
            try:
                payload = json.loads(snapshot.body)
                data = payload.get("data", {}).get("data")
                if RankingsSource._is_chart_data(data):
                    charts[RankingsSource._modality_chart_key(modality)] = {"data": data}
            except (AttributeError, json.JSONDecodeError):
                continue

        return charts

    @staticmethod
    def _context_chart_key(bucket: str) -> str:
        return f"{CONTEXT_LENGTH_DATASET_ID}:{bucket}"

    @staticmethod
    def _modality_chart_key(modality: str) -> str:
        return f"{MODALITY_RANKINGS_DATASET_ID}:{modality}"

    def _extract_chart_payloads(self, rankings_html: str) -> dict[str, dict[str, Any] | None]:
        return {
            TOP_MODELS_SPEC.dataset_id: self._find_chart(
                rankings_html,
                predicate=lambda chart: chart.get("forecast") == "forecast-1w",
                label=TOP_MODELS_SPEC.dataset_id,
            ),
            MARKET_SHARE_SPEC.dataset_id: self._find_chart(
                rankings_html,
                predicate=self._looks_like_market_share_chart,
                label=MARKET_SHARE_SPEC.dataset_id,
            ),
        }

    @staticmethod
    def _missing_chart_labels(charts: dict[str, dict[str, Any] | None]) -> list[str]:
        return [label for label, chart in charts.items() if chart is None]

    def _find_first_chart(self, *html_bodies: str, predicate: Any, label: str) -> dict[str, Any] | None:
        for html in html_bodies:
            if not html:
                continue
            chart = self._find_chart(html, predicate=predicate, label=label)
            if chart is not None:
                return chart
        return None

    def _find_chart(self, html: str, *, predicate: Any, label: str) -> dict[str, Any]:
        for payload in iter_next_f_objects(html):
            for node in walk_json(payload):
                if self._is_chart_candidate(node) and predicate(node):
                    return node
        chunks = self._parse_flight_chunks(html)
        if chunks:
            for payload in chunks.values():
                materialized = self._materialize_flight_node(payload, chunks)
                for node in walk_json(materialized):
                    if self._is_chart_candidate(node) and predicate(node):
                        return node
        return None

    def _parse_flight_chunks(self, html: str) -> dict[str, Any]:
        return {label: payload for label, payload in iter_next_f_chunks(html)}

    def _materialize_flight_node(
        self,
        node: Any,
        chunks: dict[str, Any],
        seen: set[int] | None = None,
    ) -> Any:
        seen = seen or set()
        node_id = id(node)
        if node_id in seen:
            return node

        if isinstance(node, str):
            return self._resolve_flight_reference(node, chunks, seen)
        if isinstance(node, list):
            seen.add(node_id)
            return [self._materialize_flight_node(item, chunks, seen) for item in node]
        if isinstance(node, dict):
            seen.add(node_id)
            return {key: self._materialize_flight_node(value, chunks, seen) for key, value in node.items()}
        return node

    def _resolve_flight_reference(self, value: str, chunks: dict[str, Any], seen: set[int]) -> Any:
        if not value.startswith("$"):
            return value
        if value in {"$undefined", "$null", "$true", "$false"}:
            return {
                "$undefined": None,
                "$null": None,
                "$true": True,
                "$false": False,
            }[value]

        ref = value[1:]
        if ref.startswith("L"):
            ref = ref[1:]
        if not ref or ref not in chunks:
            return value
        return self._materialize_flight_node(chunks[ref], chunks, seen)

    def _extract_chart_payloads_with_playwright(self) -> dict[str, dict[str, Any] | None]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logging.warning("Playwright is unavailable for OpenRouter rankings fallback")
            return {}

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={"width": 1440, "height": 1800})
                    try:
                        page.goto(TOP_MODELS_SPEC.source_url, wait_until="networkidle", timeout=self.timeout * 1000)
                        charts = {
                            TOP_MODELS_SPEC.dataset_id: self._extract_runtime_chart_from_page(
                                page,
                                section_selector="#leaderboard",
                                label=TOP_MODELS_SPEC.dataset_id,
                            ),
                            MARKET_SHARE_SPEC.dataset_id: self._extract_runtime_chart_from_page(
                                page,
                                section_selector="#market-share",
                                label=MARKET_SHARE_SPEC.dataset_id,
                            ),
                        }
                    finally:
                        page.close()

                    if not self._missing_chart_labels(charts):
                        return charts

                    rankings_html = self._capture_runtime_next_f_html(browser, TOP_MODELS_SPEC.source_url)
                    html_charts = self._extract_chart_payloads(rankings_html)
                    charts.update({label: chart for label, chart in html_charts.items() if chart is not None})
                finally:
                    browser.close()
        except Exception as exc:  # pragma: no cover - exercised via mocked fallback path in tests
            logging.warning("Playwright fallback failed for OpenRouter rankings: %s", exc)
            return {}

        return charts

    def _extract_runtime_chart_from_page(self, page: Any, *, section_selector: str, label: str) -> dict[str, Any] | None:
        section = page.locator(section_selector).first
        if section.count() == 0:
            logging.warning("Could not find OpenRouter section %s for %s", section_selector, label)
            return None
        section.scroll_into_view_if_needed()
        return page.evaluate(
            """
            ({ sectionSelector, label }) => {
              const section = document.querySelector(sectionSelector);
              if (!section) return null;

              const visited = new WeakSet();
              const chartPredicate = (item) => {
                if (!item || typeof item !== "object") return false;
                if (!Array.isArray(item.data) || item.data.length === 0) return false;
                const first = item.data[0];
                if (!first || typeof first !== "object" || !("x" in first) || !("ys" in first)) return false;
                if (label === "top_models") return item.forecast === "forecast-1w";
                if (label === "market_share" || label === "provider_weekly_requests") return item.isPercentage === true || Object.keys(first.ys || {}).every((key) => !key.includes("/"));
                return true;
              };

              const stack = [section];
              while (stack.length) {
                const current = stack.pop();
                if (!current || typeof current !== "object") continue;

                if (current instanceof Element) {
                  for (const child of current.children) stack.push(child);
                  for (const key of Object.keys(current)) {
                    if (!key.startsWith("__reactProps$") && !key.startsWith("__reactFiber$")) continue;
                    stack.push(current[key]);
                  }
                  continue;
                }

                if (visited.has(current)) continue;
                visited.add(current);

                if (chartPredicate(current)) {
                  return {
                    data: current.data,
                    forecast: current.forecast ?? null,
                    testId: current.testId ?? null,
                    isPercentage: current.isPercentage ?? null,
                  };
                }

                if (Array.isArray(current)) {
                  for (const child of current) stack.push(child);
                } else {
                  for (const child of Object.values(current)) stack.push(child);
                }
              }
              return null;
            }
            """,
            {"sectionSelector": section_selector, "label": label},
        )

    def _capture_runtime_next_f_html(self, browser: Any, url: str) -> str:
        page = browser.new_page(viewport={"width": 1440, "height": 1800})
        page.add_init_script(
            """
            (() => {
              const captured = [];
              Object.defineProperty(window, "__capturedNextF", { value: captured, configurable: true });
              const install = (arr) => {
                const originalPush = arr.push.bind(arr);
                arr.push = function (...args) {
                  try { captured.push(...args); } catch (e) {}
                  return originalPush(...args);
                };
                return arr;
              };
              let internal = install([]);
              Object.defineProperty(window, "__next_f", {
                get() { return internal; },
                set(value) { internal = Array.isArray(value) ? install(value) : value; },
                configurable: true,
              });
            })();
            """
        )
        try:
            page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)
            html = page.content()
            runtime_strings = page.evaluate(
                """
                () => (Array.isArray(window.__capturedNextF) ? window.__capturedNextF : [])
                  .filter((entry) => Array.isArray(entry) && typeof entry[1] === "string")
                  .map((entry) => entry[1])
                """
            )
        finally:
            page.close()
        if not runtime_strings:
            return html
        return html + self._render_captured_next_f_html(runtime_strings)

    @staticmethod
    def _render_captured_next_f_html(runtime_strings: list[str]) -> str:
        return "".join(
            f"<script>self.__next_f.push([1,{json.dumps(decoded)}])</script>"
            for decoded in runtime_strings
        )


    @staticmethod
    def _is_chart_candidate(node: Any) -> bool:
        if not isinstance(node, dict):
            return False
        return RankingsSource._is_chart_data(node.get("data"))

    @staticmethod
    def _is_chart_data(data: Any) -> bool:
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
                        context_length_bucket=spec.context_length_bucket,
                        modality=spec.modality,
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
