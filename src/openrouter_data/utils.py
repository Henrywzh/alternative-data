from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any


NEXT_F_PATTERN = re.compile(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)</script>', re.DOTALL)
NEXT_F_CHUNK_PATTERN = re.compile(r"(?m)(?:^|\n)([0-9A-Za-z]+):")


def iter_next_f_decoded_strings(html: str) -> Iterable[str]:
    for encoded in NEXT_F_PATTERN.findall(html):
        try:
            yield json.loads(f'"{encoded}"')
        except json.JSONDecodeError:
            continue


def iter_next_f_chunks(html: str) -> Iterable[tuple[str, Any]]:
    decoder = json.JSONDecoder()
    for decoded in iter_next_f_decoded_strings(html):
        # Next.js currently emits several newline-delimited flight chunks in
        # one script. Older responses contained a single ``label:payload``
        # chunk, so iterate over lines while retaining compatibility with
        # either shape.
        cursor = 0
        while cursor < len(decoded):
            match = NEXT_F_CHUNK_PATTERN.search(decoded, cursor)
            if match is None:
                break
            payload_start = match.end()
            while payload_start < len(decoded) and decoded[payload_start].isspace():
                payload_start += 1
            try:
                payload, payload_end = decoder.raw_decode(decoded, payload_start)
            except json.JSONDecodeError:
                # Module/import instructions (for example ``1:I[...]``) are
                # not JSON data. Continue scanning for the next chunk label.
                cursor = payload_start
                continue
            if isinstance(payload, (list, dict)):
                yield match.group(1), payload
            cursor = payload_end


def iter_next_f_objects(html: str) -> Iterable[Any]:
    for _, payload in iter_next_f_chunks(html):
        yield payload


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
