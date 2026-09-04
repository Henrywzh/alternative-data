from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import math
from typing import Any, Iterable

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from openrouter_data.exceptions import ExtractionError
from openrouter_data.models import DatasetRecord, RunContext, Snapshot
from openrouter_data.serving_provider import flag_latest_likely_incomplete_day, route_metadata
from openrouter_data.sources.base import SourceExtractor
from openrouter_data.utils import iter_next_f_decoded_strings, iter_next_f_objects, walk_json


CLOUD_INFRA_ACTIVITY_DATASET_ID = "cloud_infra_daily_activity"


class ServingProviderActivitySource(SourceExtractor):
    """Extract daily model-token charts from OpenRouter serving-provider pages.

    The public provider catalog is the discovery source.  Each provider page
    exposes a rolling chart under ``/provider/{slug}``; unlike the model-owner
    pages used by :class:`ProviderActivitySource`, these pages identify where
    the request was served.  A rolling chart is additive across runs: the
    storage layer upserts its natural key and retains older observations.
    """

    name = "openrouter_serving_provider_activity"
    PROVIDERS_API_URL = "https://openrouter.ai/api/v1/providers"
    BASE_URL = "https://openrouter.ai"

    def __init__(self, timeout: int = 30, max_workers: int = 4) -> None:
        self.timeout = timeout
        self.max_workers = max(1, max_workers)
        self.session = requests.Session()
        retries = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.75,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(
            max_retries=retries,
            pool_connections=self.max_workers,
            pool_maxsize=self.max_workers,
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
        )
        self.provider_metadata: dict[str, dict[str, Any]] = {}
        self.last_failures: list[dict[str, str]] = []
        self.last_parse_omissions: list[dict[str, str]] = []

    def fetch_provider_catalog(self) -> list[dict[str, Any]]:
        response = self.session.get(self.PROVIDERS_API_URL, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        values = payload.get("data", []) if isinstance(payload, dict) else []
        if not isinstance(values, list):
            raise ExtractionError("OpenRouter provider catalog returned a non-list data payload")

        providers: list[dict[str, Any]] = []
        for value in values:
            if not isinstance(value, dict):
                continue
            slug = str(value.get("slug") or value.get("id") or "").strip().casefold()
            if not slug:
                continue
            provider = {
                "slug": slug,
                "name": str(value.get("name") or value.get("display_name") or slug).strip(),
                "headquarters": value.get("headquarters"),
                "datacenters": value.get("datacenters"),
            }
            providers.append(provider)
        # A duplicate slug would otherwise create duplicate natural-key rows
        # and race to pick a metadata value. Keep first catalog order.
        deduped: dict[str, dict[str, Any]] = {}
        for provider in providers:
            deduped.setdefault(provider["slug"], provider)
        return list(deduped.values())

    def _fetch_provider_snapshot(self, provider: dict[str, Any]) -> Snapshot | None:
        slug = str(provider["slug"])
        url = f"{self.BASE_URL}/provider/{slug}"
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return Snapshot(name=f"serving_provider_{slug}", source_url=url, body=response.text)
        except Exception as exc:
            self.last_failures.append({"slug": slug, "error": str(exc)})
            return None

    def fetch_snapshots(
        self,
        providers: Iterable[dict[str, Any]] | None = None,
    ) -> list[Snapshot]:
        """Fetch provider pages concurrently while keeping a deterministic order."""

        self.last_failures = []
        self.last_parse_omissions = []
        catalog = list(providers) if providers is not None else self.fetch_provider_catalog()
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for provider in catalog:
            if isinstance(provider, str):
                provider = {"slug": provider, "name": provider}
            slug = str(provider.get("slug") or "").strip().casefold()
            if not slug or slug in seen:
                continue
            seen.add(slug)
            item = dict(provider)
            item["slug"] = slug
            normalized.append(item)
            self.provider_metadata[slug] = item

        snapshots_by_slug: dict[str, Snapshot] = {}
        with ThreadPoolExecutor(max_workers=min(self.max_workers, max(1, len(normalized)))) as executor:
            futures = {executor.submit(self._fetch_provider_snapshot, provider): provider["slug"] for provider in normalized}
            for future in as_completed(futures):
                snapshot = future.result()
                if snapshot is not None:
                    snapshots_by_slug[futures[future]] = snapshot
        return [snapshots_by_slug[provider["slug"]] for provider in normalized if provider["slug"] in snapshots_by_slug]

    @staticmethod
    def _find_activity_chart(html: str, provider_slug: str) -> dict[str, Any] | None:
        """Find a serving-provider stacked chart in a Next.js RSC payload."""

        for obj in iter_next_f_objects(html):
            for node in walk_json(obj):
                if not isinstance(node, dict):
                    continue
                data = node.get("data")
                if not isinstance(data, list):
                    # Current provider pages expose the same point structure
                    # under chartData. Keep data support for historical raw
                    # snapshots and tolerate either upstream field name.
                    data = node.get("chartData")
                if ServingProviderActivitySource._is_activity_chart_data(data):
                    return {"data": data}

        # Large provider pages often place model descriptions in Next.js
        # length-prefixed text chunks immediately before the provider payload.
        # Those chunks are not standalone JSON, so the general RSC iterator
        # intentionally skips them and may not see the following chart node.
        # The chartData value itself is JSON; decode that bounded field rather
        # than using a broad regex over the full HTML.
        decoder = json.JSONDecoder()
        marker = '"chartData":'
        for decoded in iter_next_f_decoded_strings(html):
            cursor = 0
            while True:
                marker_index = decoded.find(marker, cursor)
                if marker_index < 0:
                    break
                payload_start = marker_index + len(marker)
                try:
                    data, payload_end = decoder.raw_decode(decoded, payload_start)
                except json.JSONDecodeError:
                    cursor = payload_start
                    continue
                if ServingProviderActivitySource._is_activity_chart_data(data):
                    return {"data": data}
                cursor = payload_end
        return None

    @staticmethod
    def _is_activity_chart_data(data: Any) -> bool:
        if not isinstance(data, list) or len(data) < 2:
            return False
        first = data[0]
        if not isinstance(first, dict) or "x" not in first or "ys" not in first:
            return False
        ys = first.get("ys")
        if not isinstance(ys, dict) or not ys:
            return False
        # Serving pages can contain models from many owner prefixes.
        # Requiring slash-bearing keys avoids selecting unrelated numeric or
        # ranking payloads, while retaining the synthetic `Others` bucket.
        return any(key == "Others" or "/" in str(key) for key in ys)

    def extract(self, snapshots: list[Snapshot], context: RunContext) -> dict[str, list[DatasetRecord]]:
        records: list[DatasetRecord] = []
        for snapshot in snapshots:
            slug = snapshot.name.removeprefix("serving_provider_").casefold()
            metadata = self.provider_metadata.get(slug, {})
            provider_name = str(metadata.get("name") or slug)
            chart = self._find_activity_chart(snapshot.body, slug)
            if chart is None:
                self.last_parse_omissions.append(
                    {
                        "slug": slug,
                        "status": (
                            "provider page returned successfully but no "
                            "serving-provider activity chart was parsed"
                        ),
                    }
                )
                continue
            for point in chart.get("data", []):
                if not isinstance(point, dict):
                    continue
                usage_date = str(point.get("x") or "").split(" ")[0].strip()
                if not usage_date or pd.isna(pd.to_datetime(usage_date, errors="coerce")):
                    continue
                ys = point.get("ys") or {}
                if not isinstance(ys, dict):
                    continue
                for model_permaslug, raw_tokens in ys.items():
                    model = str(model_permaslug or "").strip()
                    if not model:
                        continue
                    total_tokens = pd.to_numeric(pd.Series([raw_tokens]), errors="coerce").iloc[0]
                    if pd.isna(total_tokens) or float(total_tokens) < 0:
                        continue
                    metadata_fields = route_metadata(model, slug)
                    datacenters = metadata.get("datacenters")
                    if isinstance(datacenters, list):
                        datacenters = ",".join(str(value) for value in datacenters)
                    records.append(
                        DatasetRecord(
                            dataset_id=CLOUD_INFRA_ACTIVITY_DATASET_ID,
                            source_url=snapshot.source_url,
                            source_run_id=context.run_id,
                            scraped_at=context.scraped_at_iso,
                            usage_date=usage_date,
                            model_permaslug=model,
                            category_slug=slug,
                            entity_id=slug,
                            entity_name=provider_name,
                            provider_slug=slug,
                            provider_name=provider_name,
                            serving_provider=slug,
                            serving_provider_name=provider_name,
                            serving_provider_type=metadata_fields["serving_provider_type"],
                            model_origin_company=metadata_fields["model_origin_company"],
                            is_first_party_route=metadata_fields["is_first_party_route"],
                            total_tokens=float(total_tokens),
                            headquarters=metadata.get("headquarters"),
                            datacenters=datacenters,
                        )
                    )

        if not records:
            return {CLOUD_INFRA_ACTIVITY_DATASET_ID: []}
        frame = pd.DataFrame([record.to_dict() for record in records])
        frame = flag_latest_likely_incomplete_day(
            frame,
            scraped_at=context.scraped_at,
            group_columns=["serving_provider"],
        )
        # Duplicates can occur if a chart payload is repeated in the RSC tree;
        # retain the last parsed observation for the natural key.
        frame = frame.drop_duplicates(
            subset=["usage_date", "serving_provider", "model_permaslug"], keep="last"
        )
        output = [DatasetRecord(**row) for row in frame.to_dict(orient="records")]
        return {CLOUD_INFRA_ACTIVITY_DATASET_ID: output}

    @staticmethod
    def validate_records(
        records: list[DatasetRecord],
        *,
        scraped_at: datetime,
        expected_provider_count: int | None = None,
        parse_omissions: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        if not records:
            raise ExtractionError("Serving-provider activity extraction failed health checks: no records extracted")
        frame = pd.DataFrame([record.to_dict() for record in records])
        required = {"usage_date", "serving_provider", "model_permaslug", "total_tokens"}
        missing = sorted(required - set(frame.columns))
        if missing:
            raise ExtractionError("Serving-provider activity extraction missing columns: " + ", ".join(missing))
        frame["usage_date_dt"] = pd.to_datetime(frame["usage_date"], errors="coerce")
        frame["total_tokens_numeric"] = pd.to_numeric(frame["total_tokens"], errors="coerce")
        errors: list[str] = []
        if frame["usage_date_dt"].isna().any():
            errors.append("malformed usage dates")
        if frame["total_tokens_numeric"].isna().any() or frame["total_tokens_numeric"].lt(0).any():
            errors.append("invalid or negative token totals")
        if frame["serving_provider"].isna().any() or frame["serving_provider"].astype(str).eq("").any():
            errors.append("missing serving-provider keys")
        duplicate_count = int(
            frame.duplicated(subset=["usage_date", "serving_provider", "model_permaslug"]).sum()
        )
        if duplicate_count:
            errors.append(f"{duplicate_count} duplicate natural keys")
        if errors:
            raise ExtractionError("Serving-provider activity extraction failed health checks: " + "; ".join(errors))

        latest_date = frame["usage_date_dt"].max().date()
        scrape_date = scraped_at.astimezone(timezone.utc).date()
        latest_likely_incomplete = latest_date >= scrape_date
        provider_count = int(frame["serving_provider"].nunique())
        if expected_provider_count is not None:
            minimum_provider_count = max(1, math.ceil(expected_provider_count * 0.80))
            if provider_count < minimum_provider_count:
                raise ExtractionError(
                    "Serving-provider activity extraction covered only "
                    f"{provider_count}/{expected_provider_count} catalog providers; "
                    f"minimum is {minimum_provider_count}"
                )
        return {
            "row_count": int(len(frame)),
            "provider_count": provider_count,
            "expected_provider_count": expected_provider_count,
            "date_count": int(frame["usage_date_dt"].dt.date.nunique()),
            "latest_date": latest_date.isoformat(),
            "latest_likely_incomplete": latest_likely_incomplete,
            "provider_coverage_ratio": (
                provider_count / expected_provider_count
                if expected_provider_count
                else 1.0
            ),
            "parse_omission_count": len(parse_omissions or []),
            "parse_omission_slugs": [
                str(item.get("slug") or "")
                for item in (parse_omissions or [])
                if item.get("slug")
            ],
        }
