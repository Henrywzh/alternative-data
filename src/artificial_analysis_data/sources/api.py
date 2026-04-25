from __future__ import annotations

import json
from typing import Any

import requests

from artificial_analysis_data.models import (
    ArtificialAnalysisModelPoint,
    Snapshot,
    coerce_date_string,
    quarter_label_for_date,
)


class ArtificialAnalysisApiSource:
    def __init__(self, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.source_url = "https://artificialanalysis.ai/api/v2/data/llms/models"

    def fetch_snapshot(self, api_key: str) -> Snapshot:
        response = self.session.get(
            self.source_url,
            headers={"x-api-key": api_key},
            timeout=30,
        )
        response.raise_for_status()
        return Snapshot(name="llms_models", source_url=self.source_url, body=response.text)

    def extract(
        self,
        snapshot: Snapshot,
        *,
        run_id: str,
        scraped_at: str,
        as_of_date: str,
    ) -> list[ArtificialAnalysisModelPoint]:
        payload = json.loads(snapshot.body)
        items = payload.get("data", payload if isinstance(payload, list) else [])
        points: list[ArtificialAnalysisModelPoint] = []
        for item in items:
            creator = item.get("model_creator") or item.get("creator") or {}
            evaluations = item.get("evaluations") or {}
            pricing = item.get("pricing") or {}
            training = item.get("training_information") or {}
            raw_release_date = item.get("release_date")
            normalized_release_date = coerce_date_string(raw_release_date)
            open_source_categorization = item.get("open_source_categorization")
            inferred_is_open = item.get("is_open_weights")
            if inferred_is_open is None and isinstance(open_source_categorization, str):
                inferred_is_open = "open" in open_source_categorization.lower()

            points.append(
                ArtificialAnalysisModelPoint(
                    as_of_date=as_of_date,
                    model_id=str(item.get("id")),
                    model_slug=item.get("slug"),
                    model_name=item.get("name") or item.get("model_name") or str(item.get("id")),
                    creator_id=creator.get("id"),
                    creator_name=creator.get("name"),
                    creator_slug=creator.get("slug"),
                    creator_country=creator.get("country"),
                    release_date=normalized_release_date,
                    release_quarter=quarter_label_for_date(raw_release_date),
                    intelligence_index=_to_float(
                        item.get("intelligence_index"),
                        evaluations.get("artificial_analysis_intelligence_index"),
                    ),
                    coding_index=_to_float(item.get("coding_index"), evaluations.get("artificial_analysis_coding_index")),
                    math_index=_to_float(item.get("math_index"), evaluations.get("artificial_analysis_math_index")),
                    gpqa=_to_float(item.get("gpqa"), evaluations.get("gpqa")),
                    scicode=_to_float(item.get("scicode"), evaluations.get("scicode")),
                    price_1m_blended_3_to_1=_to_float(
                        item.get("price_1m_blended_3_to_1"),
                        pricing.get("price_1m_blended_3_to_1"),
                    ),
                    price_1m_input_tokens=_to_float(
                        item.get("price_1m_input_tokens"),
                        pricing.get("price_1m_input_tokens"),
                    ),
                    price_1m_output_tokens=_to_float(
                        item.get("price_1m_output_tokens"),
                        pricing.get("price_1m_output_tokens"),
                    ),
                    median_output_tokens_per_second=_to_float(item.get("median_output_tokens_per_second")),
                    median_time_to_first_token_seconds=_to_float(item.get("median_time_to_first_token_seconds")),
                    context_window_tokens=_to_int(item.get("context_window_tokens"), item.get("context_window")),
                    total_parameters_billions=_to_float(
                        item.get("total_parameters_billions"),
                        item.get("parameters_billions"),
                        item.get("parameters"),
                    ),
                    active_parameters_billions=_to_float(
                        item.get("active_parameters_billions"),
                        item.get("inference_parameters_active_billions"),
                    ),
                    training_tokens_trillions=_to_float(
                        item.get("training_tokens_trillions"),
                        training.get("training_tokens_trillions"),
                    ),
                    open_source_categorization=open_source_categorization,
                    license_name=item.get("license_name"),
                    is_open_weights=None if inferred_is_open is None else bool(inferred_is_open),
                    source_url=snapshot.source_url,
                    source_run_id=run_id,
                    scraped_at=scraped_at,
                )
            )
        return points


def _to_float(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        return float(value)
    return None


def _to_int(*values: Any) -> int | None:
    for value in values:
        if value is None or value == "":
            continue
        return int(value)
    return None
