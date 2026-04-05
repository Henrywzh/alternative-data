from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any


NEXT_F_PATTERN = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)</script>', re.DOTALL)


def iter_next_f_decoded_strings(html: str) -> Iterable[str]:
    for encoded in NEXT_F_PATTERN.findall(html):
        try:
            yield json.loads(f'"{encoded}"')
        except json.JSONDecodeError:
            continue


def iter_next_f_objects(html: str) -> Iterable[Any]:
    for decoded in iter_next_f_decoded_strings(html):
        if ":" not in decoded:
            continue
        _, payload = decoded.split(":", 1)
        payload = payload.strip()
        if not payload.startswith("["):
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


def walk_json(obj: Any) -> Iterable[Any]:
    yield obj
    if isinstance(obj, dict):
        for value in obj.values():
            yield from walk_json(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from walk_json(item)


def iso_date(value: str) -> date:
    return date.fromisoformat(value)


def infer_completed_week_dates(
    x_values: list[str],
    scraped_at: datetime,
    *,
    week_anchor: str,
) -> set[str]:
    current_date = scraped_at.date()
    completed: set[str] = set()
    for raw in x_values:
        bucket_date = iso_date(raw)
        if week_anchor == "start":
            if bucket_date + timedelta(days=7) <= current_date:
                completed.add(raw)
        elif week_anchor == "end":
            if bucket_date < current_date:
                completed.add(raw)
        else:
            raise ValueError(f"Unsupported week anchor: {week_anchor}")
    return completed


def slug_author(entity_id: str) -> str | None:
    if "/" not in entity_id:
        return None
    return entity_id.split("/", 1)[0]


def humanize_identifier(identifier: str) -> str:
    return identifier.replace("_", " ").replace("-", " ")
