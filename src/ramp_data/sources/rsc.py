"""Robust decoding of Ramp's Next.js React Server Component (RSC) payload.

Ramp embeds page data in ``self.__next_f.push([1,"<chunk>"])`` calls. Each
``<chunk>`` is an independently JSON-string-encoded fragment of the RSC stream;
concatenating the decoded chunks reconstructs the full payload.

The original scraper decoded chunks with a hand-rolled chain of ``str.replace``
calls, which got the escape ordering wrong and never handled ``\\uXXXX`` — so
category names leaked literal ``\\u0026`` into the data. It also carved JSON
objects out with a brace counter that ignored string contents, so any brace
inside a description broke the balance.

Both problems disappear if we let ``json`` do the work:

* decode each chunk with ``json.loads`` (handles every escape correctly), and
* pull objects out with ``JSONDecoder.raw_decode`` (string/escape aware).
"""
from __future__ import annotations

import json
import re
from typing import Any

_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,\s*(".*?")\]\)', re.DOTALL)

_DECODER = json.JSONDecoder()

# React serializes a missing value as the string "$undefined" -- the payload has
# no JSON `undefined`, so the framing token travels as ordinary text. Left
# alone it lands in the data as a value: `is_publishable` on every one of the
# 37 ramp_ai_pepm_spend rows read as the literal "$undefined", which is
# *truthy*, so a filter on that column silently kept rows Ramp never marked
# publishable. Numeric fields hid it better -- coercion turned it into NaN --
# but only by accident of the column's type.
_UNDEFINED = "$undefined"


def _denull(value: Any) -> Any:
    """Recursively turn React's ``"$undefined"`` sentinel into ``None``."""
    if isinstance(value, str):
        return None if value == _UNDEFINED else value
    if isinstance(value, list):
        return [_denull(item) for item in value]
    if isinstance(value, dict):
        return {key: _denull(item) for key, item in value.items()}
    return value


def decode_payload(html: str) -> str:
    """Reconstruct the RSC payload string from a page's HTML.

    Each pushed chunk is a valid JSON string literal, so ``json.loads`` decodes
    it losslessly (unicode escapes, ``\\/``, control chars and all).
    """
    chunks: list[str] = []
    for match in _PUSH_RE.finditer(html):
        try:
            chunks.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            # A malformed chunk is skipped rather than aborting the whole page;
            # the caller's data-quality gate catches wholesale extraction loss.
            continue
    return "".join(chunks)


def objects_containing(payload: str, marker: str, required_keys: set[str]) -> list[dict[str, Any]]:
    """Every JSON object that contains ``marker`` and all of ``required_keys``.

    The RSC payload is not one valid JSON document — it is a tree studded with
    ``$``-prefixed references and framing tokens, so a left-to-right object scan
    either chokes on an enclosing structure or skips past the leaf objects nested
    inside it. Instead we anchor on a distinctive ``marker`` substring (e.g.
    ``"cleanDomain":``) and expand outward: from each marker occurrence we walk
    back over candidate ``{`` positions and ``raw_decode`` each, taking the
    *tightest* enclosing object that is valid JSON and actually spans the marker.

    Because parsing is delegated to ``json``, this is immune to the original
    scraper's two failure modes: braces inside string values no longer unbalance
    the extraction, and the marker key need not be the object's first field.
    """
    results: list[dict[str, Any]] = []
    seen_starts: set[int] = set()
    for match in re.finditer(re.escape(marker), payload):
        marker_pos = match.start()
        search_end = marker_pos + 1
        while True:
            brace = payload.rfind("{", 0, search_end)
            if brace == -1:
                break
            if brace in seen_starts:
                # Already resolved (or rejected) this object start for an earlier marker.
                break
            try:
                obj, end = _DECODER.raw_decode(payload, brace)
            except json.JSONDecodeError:
                search_end = brace
                continue
            # Must be a dict whose span actually contains the marker; a nested
            # object that closes before the marker is too tight — keep expanding.
            if isinstance(obj, dict) and end > marker_pos:
                seen_starts.add(brace)
                if required_keys.issubset(obj.keys()):
                    results.append(_denull(obj))
                break
            search_end = brace
    return results


def extract_array_after_key(payload: str, key: str) -> list[Any]:
    """Decode the JSON array that follows ``"<key>":`` in the payload.

    Returns ``[]`` if the key is absent or the value is not an array. Uses
    ``raw_decode`` so nested arrays/objects and bracketed string contents are
    handled correctly.
    """
    needle = f'"{key}":'
    idx = payload.find(needle)
    if idx == -1:
        return []
    bracket = payload.find("[", idx + len(needle))
    if bracket == -1:
        return []
    try:
        value, _ = _DECODER.raw_decode(payload, bracket)
    except json.JSONDecodeError:
        return []
    return _denull(value) if isinstance(value, list) else []
