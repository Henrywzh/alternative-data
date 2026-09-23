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
_SENSITIVE_HEADER_PATTERN = re.compile(
    r"(?i)(?P<prefix>\b(?P<key>authorization|proxy-authorization|cookie|set-cookie)\s*[:=]\s*)"
    r"(?P<value>(?![\"'\\])[^\r\n]*)"
)
_ASSIGNMENT_PATTERN = re.compile(
    r"""(?ix)
    (?P<prefix>
      \\?["']?
      (?P<key>[a-z0-9][a-z0-9_.-]*)
      \\?["']?\s*[:=]\s*
    )
    (?:(?P<quote>\\?["'])
       (?:\\.|(?!(?P=quote)).)*
       (?P=quote)
      |(?P<unquoted>[^\s,;{}]+)
    )
    """
)


def redact_text(value: str) -> str:
    """Redact common credential shapes without reading the repository `.config`."""

    redacted = value
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    redacted = _SENSITIVE_HEADER_PATTERN.sub(_redact_sensitive_header, redacted)
    redacted = _ASSIGNMENT_PATTERN.sub(_redact_secret_assignment, redacted)
    return redacted


def _redact_sensitive_header(match: re.Match[str]) -> str:
    key = match.group("key").lower()
    value = match.group("value").strip()
    if key == "authorization" and re.fullmatch(
        r"(?i)Bearer\s+\[REDACTED\]", value
    ):
        return match.group(0)
    if value == "[REDACTED]":
        return match.group(0)
    return f"{match.group('prefix')}[REDACTED]"


def _redact_secret_assignment(match: re.Match[str]) -> str:
    key = match.group("key")
    if not _is_secret_key(key):
        return match.group(0)
    # The bearer-token pattern has already removed the credential after this
    # prefix. Keep the harmless scheme word instead of redacting it separately.
    unquoted_value = match.group("unquoted") or ""
    if key.lower() == "authorization" and unquoted_value.lower() == "bearer":
        return match.group(0)
    quote = match.group("quote")
    value = f"{quote}[REDACTED]{quote}" if quote else "[REDACTED]"
    return f"{match.group('prefix')}{value}"


def _is_secret_key(value: str) -> bool:
    separated = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", separated)
    words = re.findall(r"[a-z0-9]+", separated.lower())
    if any(
        word in {
            "auth",
            "authorization",
            "cookie",
            "credential",
            "credentials",
            "password",
            "passwd",
            "secret",
            "token",
        }
        for word in words
    ):
        return True
    compact = "".join(words)
    return compact.endswith(("apikey", "accesskey", "privatekey"))


def redact_value(value: Any) -> Any:
    """Recursively redact string values in structured evidence."""

    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if isinstance(key, str)
                and _is_secret_key(key)
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
