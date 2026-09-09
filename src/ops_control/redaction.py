from __future__ import annotations

import re
from typing import Any


_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/=-]+"),
        r"\1[REDACTED]",
    ),
    (
        re.compile(
            r"(?i)\b([a-z0-9]*(?:[_-][a-z0-9]+)*[_-])?"
            r"(api[_-]?key|access[_-]?token|token|secret|password)"
            r"(\s*[=:]\s*)"
            r"[^\s,;]+"
        ),
        r"\1\2\3[REDACTED]",
    ),
    (
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
        "[REDACTED]",
    ),
    (
        re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
        "[REDACTED]",
    ),
)
_SECRET_KEY_PATTERN = re.compile(
    r"(?i)^(?:[a-z0-9]+[_-])*"
    r"(?:api[_-]?key|access[_-]?token|token|secret|password|authorization)$"
)


def redact_text(value: str) -> str:
    """Redact common credential shapes without reading the repository `.config`."""

    redacted = value
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def redact_value(value: Any) -> Any:
    """Recursively redact string values in structured evidence."""

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if isinstance(key, str)
                and _SECRET_KEY_PATTERN.fullmatch(key)
                and item is not None
                else redact_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value
