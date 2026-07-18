from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from openrouter_official_data.source import Snapshot, parse_json


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return None if number is None else int(number)


def _snapshot_date(value: Any, fallback: str) -> str:
    if value:
        return str(value).split("T", 1)[0]
    return fallback.split("T", 1)[0]


def extract_rankings(snapshot: Snapshot, *, run_id: str, scraped_at: str) -> list[dict[str, Any]]:
    payload = parse_json(snapshot)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    counts: dict[str, int] = defaultdict(int)
    rows: list[dict[str, Any]] = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        usage_date = str(item.get("date") or "").split("T", 1)[0]
        model = str(item.get("model_permaslug") or "").strip()
        total_tokens = _number(item.get("total_tokens"))
        if not usage_date or not model or total_tokens is None:
            continue
        counts[usage_date] += 1
        rows.append(
            {
                "usage_date": usage_date,
                "model_permaslug": model,
                "total_tokens": total_tokens,
                "rank": None if model.casefold() == "other" else counts[usage_date],
                "is_other": model.casefold() == "other",
                "period": str(snapshot.query.get("period", "day")),
                "modality": snapshot.query.get("modality"),
                "context_bucket": snapshot.query.get("context_bucket"),
                "category": snapshot.query.get("category"),
                "language_type": snapshot.query.get("language_type"),
                "is_sampled": bool(snapshot.query.get("category") or snapshot.query.get("language_type")),
                "as_of": meta.get("as_of"),
                "window_start_date": meta.get("start_date"),
                "window_end_date": meta.get("end_date"),
                "api_version": meta.get("version"),
                "source_url": snapshot.source_url,
                "source_run_id": run_id,
                "scraped_at": scraped_at,
            }
        )
    return rows


def extract_app_rankings(snapshot: Snapshot, *, run_id: str, scraped_at: str) -> list[dict[str, Any]]:
    payload = parse_json(snapshot)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    ranking_type = str(snapshot.query.get("sort", "popular"))
    snapshot_date = _snapshot_date(meta.get("as_of") or meta.get("end_date"), scraped_at)
    rows: list[dict[str, Any]] = []
    for item in payload.get("data", []):
        if not isinstance(item, dict):
            continue
        app_id = _integer(item.get("app_id"))
        rank = _integer(item.get("rank"))
        if app_id is None or rank is None:
            continue
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "ranking_type": ranking_type,
                "app_id": app_id,
                "app_name": item.get("app_name"),
                "rank": rank,
                "total_tokens": _number(item.get("total_tokens")),
                "total_requests": _number(item.get("total_requests")),
                "window_start_date": meta.get("start_date"),
                "window_end_date": meta.get("end_date"),
                "as_of": meta.get("as_of"),
                "api_version": meta.get("version"),
                "source_url": snapshot.source_url,
                "source_run_id": run_id,
                "scraped_at": scraped_at,
            }
        )
    return rows


def extract_task_classifications(
    snapshot: Snapshot, *, run_id: str, scraped_at: str
) -> dict[str, list[dict[str, Any]]]:
    payload = parse_json(snapshot)
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    snapshot_date = _snapshot_date(data.get("as_of"), scraped_at)
    window_days = _integer(data.get("window_days")) or 7
    base = {
        "snapshot_date": snapshot_date,
        "window_days": window_days,
        "as_of": data.get("as_of"),
        "is_sampled": True,
        "source_url": snapshot.source_url,
        "source_run_id": run_id,
        "scraped_at": scraped_at,
    }
    classifications: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []
    macros: list[dict[str, Any]] = []
    for item in data.get("classifications", []):
        if not isinstance(item, dict) or not item.get("tag"):
            continue
        classification = {
            **base,
            "tag": item.get("tag"),
            "display_name": item.get("display_name"),
            "macro_category": item.get("macro_category"),
            "usage_share": _number(item.get("usage_share")),
            "token_share": _number(item.get("token_share")),
            "category_usage_share": _number(item.get("category_usage_share")),
            "category_token_share": _number(item.get("category_token_share")),
        }
        classifications.append(classification)
        for rank, model in enumerate(item.get("models", []), start=1):
            if not isinstance(model, dict) or not model.get("id"):
                continue
            models.append(
                {
                    **base,
                    "tag": item.get("tag"),
                    "model_permaslug": model.get("id"),
                    "rank": rank,
                    "tag_usage_share": _number(model.get("tag_usage_share")),
                    "tag_token_share": _number(model.get("tag_token_share")),
                }
            )
    for item in data.get("macro_categories", []):
        if not isinstance(item, dict) or not item.get("key"):
            continue
        macros.append(
            {
                **base,
                "macro_category": item.get("key"),
                "display_name": item.get("label"),
                "usage_share": _number(item.get("usage_share")),
                "token_share": _number(item.get("token_share")),
            }
        )
    return {
        "official_task_classifications": classifications,
        "official_task_models": models,
        "official_task_macro_categories": macros,
    }


def extract_providers(snapshot: Snapshot, *, run_id: str, scraped_at: str) -> list[dict[str, Any]]:
    payload = parse_json(snapshot)
    snapshot_date = scraped_at.split("T", 1)[0]
    rows: list[dict[str, Any]] = []
    for item in payload.get("data", []):
        if not isinstance(item, dict) or not item.get("slug"):
            continue
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "provider_slug": item.get("slug"),
                "provider_name": item.get("name"),
                "headquarters": item.get("headquarters"),
                "datacenters_json": json.dumps(item.get("datacenters"), sort_keys=True),
                "status_page_url": item.get("status_page_url"),
                "privacy_policy_url": item.get("privacy_policy_url"),
                "terms_of_service_url": item.get("terms_of_service_url"),
                "source_url": snapshot.source_url,
                "source_run_id": run_id,
                "scraped_at": scraped_at,
            }
        )
    return rows


def extract_benchmarks(snapshot: Snapshot, *, run_id: str, scraped_at: str) -> list[dict[str, Any]]:
    payload = parse_json(snapshot)
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    snapshot_date = _snapshot_date(meta.get("as_of"), scraped_at)
    rows: list[dict[str, Any]] = []
    variants: dict[tuple[Any, ...], int] = defaultdict(int)
    for item in payload.get("data", []):
        if not isinstance(item, dict) or not item.get("model_permaslug"):
            continue
        pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
        tournament = item.get("tournament_stats") if isinstance(item.get("tournament_stats"), dict) else {}
        variant_key = (
            item.get("source"),
            item.get("model_permaslug"),
            item.get("display_name"),
            item.get("arena"),
            item.get("category"),
        )
        variants[variant_key] += 1
        rows.append(
            {
                "snapshot_date": snapshot_date,
                "benchmark_source": item.get("source"),
                "model_permaslug": item.get("model_permaslug"),
                "display_name": item.get("display_name"),
                # A few sources emit otherwise indistinguishable configurations.
                # The API exposes no configuration ID, so retain every row with
                # a stable-in-response occurrence index instead of dropping data.
                "variant_index": variants[variant_key],
                "arena": item.get("arena"),
                "category": item.get("category"),
                "intelligence_index": _number(item.get("intelligence_index")),
                "coding_index": _number(item.get("coding_index")),
                "agentic_index": _number(item.get("agentic_index")),
                "elo": _number(item.get("elo")),
                "win_rate": _number(item.get("win_rate")),
                "avg_generation_time_ms": _number(item.get("avg_generation_time_ms")),
                "first_place": _integer(tournament.get("first_place")),
                "second_place": _integer(tournament.get("second_place")),
                "third_place": _integer(tournament.get("third_place")),
                "fourth_place": _integer(tournament.get("fourth_place")),
                "tournament_total": _integer(tournament.get("total")),
                "pricing_prompt": _number(pricing.get("prompt")),
                "pricing_completion": _number(pricing.get("completion")),
                "as_of": meta.get("as_of"),
                "api_version": meta.get("version"),
                "citation": meta.get("citation"),
                "source_url": snapshot.source_url,
                "source_run_id": run_id,
                "scraped_at": scraped_at,
            }
        )
    return rows


def extract_snapshots(
    snapshots: list[Snapshot], *, run_id: str, scraped_at: str
) -> dict[str, list[dict[str, Any]]]:
    extracted: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in snapshots:
        if snapshot.name.startswith("rankings_daily"):
            extracted["official_model_rankings_daily"].extend(
                extract_rankings(snapshot, run_id=run_id, scraped_at=scraped_at)
            )
        elif snapshot.name.startswith("app_rankings_"):
            extracted["official_app_rankings"].extend(
                extract_app_rankings(snapshot, run_id=run_id, scraped_at=scraped_at)
            )
        elif snapshot.name == "task_classifications":
            for dataset_id, rows in extract_task_classifications(
                snapshot, run_id=run_id, scraped_at=scraped_at
            ).items():
                extracted[dataset_id].extend(rows)
        elif snapshot.name == "providers":
            extracted["official_providers"].extend(
                extract_providers(snapshot, run_id=run_id, scraped_at=scraped_at)
            )
        elif snapshot.name == "benchmarks":
            extracted["official_benchmarks"].extend(
                extract_benchmarks(snapshot, run_id=run_id, scraped_at=scraped_at)
            )
    return dict(extracted)
