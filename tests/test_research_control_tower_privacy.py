"""Task 8 privacy and local-only navigation checks for Control Tower V1.

The privacy scanner is deliberately bound to the same production artifact
resolver as the app. It scans only the exact resolved generation, never raw
captures, repository ``.config`` files, sibling databases, or unbounded data
directories. Findings contain locations and one-way digests, never matched
secret values.
"""

from __future__ import annotations

import builtins
import csv
from dataclasses import dataclass
from html.parser import HTMLParser
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sys
from typing import Callable, Iterable
import urllib.parse
import urllib.request

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "apps" / "research-control-tower"
APP_PATH = APP_ROOT / "app.py"
FINANCIAL_DATA_ROOT = REPO_ROOT.parent / "financial-data"

ALLOWED_SUFFIXES = {".parquet", ".json", ".jsonl", ".csv", ".txt", ".md"}
MAX_ENCODED_JSON_BYTES = 64 * 1024
MAX_ENCODED_JSON_DEPTH = 4
HEADER_LINE_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9_-]{0,127})\s*:\s*(.*)$"
)

APP_SOURCE_HEALTH_COLUMNS = (
    "source_id",
    "input_path",
    "source_kind",
    "status",
    "required",
    "row_count",
    "first_observation_at",
    "latest_observation_at",
    "source_latest_at",
    "retrieved_at_utc",
    "cadence",
    "source_url",
    "pit_class",
    "source_license_class",
    "entitlement_status",
    "entitlement_evidence",
    "entitlement_ref",
    "input_sha256",
    "schema_version",
    "missing_geographies",
    "detail",
)

TASK3_HEALTH_COLUMNS = (
    "provider",
    "status",
    "reason",
    "row_count",
    "mapped_row_count",
    "latest_snapshot_at",
    "as_of",
    "network_calls",
    "source_license_class",
    "entitlement_status",
    "entitlement_evidence",
    "entitlement_ref",
)


def _normalise_name(value: object) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value))
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


# Exact normalized names only. Ordinary analytics fields containing "token"
# or "hash" are intentionally absent.
RISKY_FIELD_NAMES = {
    "api_key",
    "api_secret",
    "api_token",
    "secret",
    "secret_key",
    "client_secret",
    "password",
    "access_token",
    "refresh_token",
    "authorization",
    "proxy_authorization",
    "cookie",
    "set_cookie",
    "session_cookie",
    "bearer_token",
    "private_key",
    "signing_key",
    "token",
    "oauth_token",
    "github_token",
    "x_api_key",
    "x_auth_token",
    "aws_access_key_id",
    "aws_secret_access_key",
    "aws_session_token",
    "x_amz_credential",
    "x_amz_security_token",
    "x_amz_signature",
    "x_goog_signature",
    "google_access_id",
    "headers",
    "request_headers",
    "response_headers",
}

FORBIDDEN_BODY_FIELDS = {
    "body_text",
    "article_body",
    "full_text",
    "content",
    "raw_payload",
    "payload",
    "html",
    "filing_content",
    "news_content",
    "transcript",
    "transcript_text",
    "document_body",
    "raw_response",
    "response_json",
    "raw_html",
    "response_body",
    "request_body",
}

FORBIDDEN_HEADER_FIELDS = {
    "headers",
    "request_headers",
    "response_headers",
}

HASH_FIELDS = {
    "raw_hash",
    "content_hash_if_permitted",
    "input_sha256",
    "sha256",
}

URL_QUERY_RISK_NAMES = RISKY_FIELD_NAMES | {
    "signature",
    "sig",
    "signed",
    "signed_token",
    "security_token",
    "x_amz_algorithm",
    "x_amz_credential",
    "x_amz_security_token",
    "x_amz_signature",
    "x_goog_algorithm",
    "x_goog_credential",
    "x_goog_signature",
}

URL_FIELD_NAMES = {
    "url",
    "uri",
    "href",
    "link",
    "source_url",
    "mapping_source_url",
    "filing_url",
    "request_url",
    "response_url",
}

PLACEHOLDER_VALUES = {
    "",
    "null",
    "none",
    "nan",
    "n/a",
    "na",
    "redacted",
    "<redacted>",
    "[redacted]",
    "***",
    "unavailable",
    "unavailable_optional",
    "entitlement_required",
    "not_available",
    "not collected",
    "not_collected",
    "missing",
    "not configured",
    "not_configured",
    "placeholder_api_key",
    "placeholder_api_token",
}

SUMMARY_PERMITTED_LICENSES = {
    "official_public",
    "public",
    "public_metadata",
    "internal_research",
    "permitted_derived_summary",
}

KNOWN_CREDENTIAL_PATTERNS = (
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
)


@dataclass(frozen=True)
class PrivacyFinding:
    artifact: str
    format: str
    location: str
    rule_id: str
    digest: str


@dataclass(frozen=True)
class NavigationCase:
    name: str
    page: str
    publication_root: Path
    session_state: dict[str, object]
    expected_text: str


class NetworkViolation(AssertionError):
    """Raised when guarded AppTest navigation attempts outbound I/O."""


class ProtectedWriteViolation(AssertionError):
    """Raised when guarded AppTest navigation attempts a protected write."""


class _TagDetector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found_tag = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del tag, attrs
        self.found_tag = True

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        del tag, attrs
        self.found_tag = True

    def handle_endtag(self, tag: str) -> None:
        del tag
        self.found_tag = True


@pytest.fixture(autouse=True)
def _control_tower_import_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(APP_ROOT))


def _digest(value: object) -> str:
    return hashlib.sha256(
        str(value).encode("utf-8", errors="replace")
    ).hexdigest()[:12]


def _placeholder(value: object) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in PLACEHOLDER_VALUES


def _known_credential(value: object) -> bool:
    if not isinstance(value, (str, bytes)):
        return False
    text = (
        value.decode("utf-8", errors="ignore")
        if isinstance(value, bytes)
        else value
    )
    return any(pattern.search(text) for pattern in KNOWN_CREDENTIAL_PATTERNS)


def _hash_shaped(value: object) -> bool:
    if _placeholder(value):
        return True
    text = str(value).strip()
    return bool(re.fullmatch(r"(?:sha256:)?[0-9a-fA-F]{32,128}", text))


def _contains_html(value: str) -> bool:
    if "<" not in value or ">" not in value:
        return False
    detector = _TagDetector()
    try:
        detector.feed(value)
        detector.close()
    except Exception:
        return bool(
            re.search(r"<\s*/?\s*[A-Za-z][A-Za-z0-9:-]*(?:\s|/?>)", value)
        )
    return detector.found_tag


def _looks_body_like(value: object) -> bool:
    if not isinstance(value, str):
        return False
    if _contains_html(value):
        return True
    stripped = value.strip()
    if len(stripped) >= 500 and re.search(r"\n\s*\n", stripped):
        return True
    words = re.findall(r"\b[\w'-]+\b", stripped)
    # A one-line article/filing payload must not pass merely because it has no
    # paragraph breaks. This threshold stays above normal titles/metadata.
    return len(stripped) >= 1_200 and len(words) >= 120


def _url_parts(value: str) -> urllib.parse.SplitResult | None:
    text = value.strip()
    if not text or len(text) > MAX_ENCODED_JSON_BYTES:
        return None
    if not (
        re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", text)
        or text.startswith("//")
    ):
        return None
    try:
        parsed = urllib.parse.urlsplit(text)
    except ValueError:
        return None
    return parsed if parsed.scheme or parsed.netloc else None


def _url_has_secret(value: str) -> bool:
    parsed = _url_parts(value)
    if parsed is None:
        return False
    if parsed.username is not None or parsed.password is not None:
        return True
    for component in (parsed.query, parsed.fragment):
        for name, query_value in urllib.parse.parse_qsl(
            component,
            keep_blank_values=True,
        ):
            if (
                _normalise_name(name) in URL_QUERY_RISK_NAMES
                and not _placeholder(query_value)
            ):
                return True
    return False


def _finding(
    findings: list[PrivacyFinding],
    *,
    artifact: Path,
    format_name: str,
    location: str,
    rule_id: str,
    matched: object,
) -> None:
    findings.append(
        PrivacyFinding(
            artifact=artifact.as_posix(),
            format=format_name,
            location=location,
            rule_id=rule_id,
            digest=_digest(matched),
        )
    )


def _deduplicate(findings: Iterable[PrivacyFinding]) -> list[PrivacyFinding]:
    unique = {
        (
            finding.artifact,
            finding.format,
            finding.location,
            finding.rule_id,
            finding.digest,
        ): finding
        for finding in findings
    }
    return [unique[key] for key in sorted(unique)]


def _inspect_key(
    key: object,
    value: object,
    *,
    artifact: Path,
    format_name: str,
    location: str,
    findings: list[PrivacyFinding],
) -> str:
    field = _normalise_name(key)
    if field in RISKY_FIELD_NAMES:
        _finding(
            findings,
            artifact=artifact,
            format_name=format_name,
            location=location,
            rule_id=(
                "forbidden_header_field"
                if field in FORBIDDEN_HEADER_FIELDS
                else "credential_field_name"
            ),
            matched=key,
        )
    if field in FORBIDDEN_BODY_FIELDS:
        _finding(
            findings,
            artifact=artifact,
            format_name=format_name,
            location=location,
            rule_id="forbidden_body_field",
            matched=key,
        )
    if field in HASH_FIELDS and not _hash_shaped(value):
        _finding(
            findings,
            artifact=artifact,
            format_name=format_name,
            location=location,
            rule_id="hash_field_not_hash_shaped",
            matched=value,
        )
    return field


def _decode_json_scalar(value: str, encoded_depth: int) -> object | None:
    if encoded_depth >= MAX_ENCODED_JSON_DEPTH:
        return None
    encoded = value.encode("utf-8", errors="replace")
    if len(encoded) > MAX_ENCODED_JSON_BYTES:
        return None
    stripped = value.strip()
    if not (
        (stripped.startswith("{") and stripped.endswith("}"))
        or (stripped.startswith("[") and stripped.endswith("]"))
    ):
        return None
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, (dict, list)) else None


def _inspect_scalar(
    value: object,
    *,
    field: str | None,
    artifact: Path,
    format_name: str,
    location: str,
    findings: list[PrivacyFinding],
    encoded_depth: int,
) -> None:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    if not isinstance(value, str):
        return
    if _known_credential(value):
        _finding(
            findings,
            artifact=artifact,
            format_name=format_name,
            location=location,
            rule_id="credential_shaped_value",
            matched=value,
        )
    if _url_has_secret(value):
        _finding(
            findings,
            artifact=artifact,
            format_name=format_name,
            location=location,
            rule_id="secret_url",
            matched=value,
        )
    elif field in URL_FIELD_NAMES and _url_parts(value) is not None:
        # URL fields are parsed regardless of their exact spelling; a clean
        # URL produces no finding.
        pass
    if field in RISKY_FIELD_NAMES and not _placeholder(value):
        _finding(
            findings,
            artifact=artifact,
            format_name=format_name,
            location=location,
            rule_id="credential_value",
            matched=value,
        )
    if _looks_body_like(value):
        _finding(
            findings,
            artifact=artifact,
            format_name=format_name,
            location=location,
            rule_id="body_like_text",
            matched=value,
        )
    decoded = _decode_json_scalar(value, encoded_depth)
    if decoded is not None:
        _walk_value(
            decoded,
            field=field,
            artifact=artifact,
            format_name=format_name,
            location=f"{location}<decoded-json>",
            findings=findings,
            encoded_depth=encoded_depth + 1,
        )


def _walk_value(
    value: object,
    *,
    field: str | None,
    artifact: Path,
    format_name: str,
    location: str,
    findings: list[PrivacyFinding],
    encoded_depth: int = 0,
) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_location = f"{location}.{key}" if location else str(key)
            child_field = _inspect_key(
                key,
                child,
                artifact=artifact,
                format_name=format_name,
                location=child_location,
                findings=findings,
            )
            _walk_value(
                child,
                field=child_field,
                artifact=artifact,
                format_name=format_name,
                location=child_location,
                findings=findings,
                encoded_depth=encoded_depth,
            )
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _walk_value(
                child,
                field=field,
                artifact=artifact,
                format_name=format_name,
                location=f"{location}[{index}]",
                findings=findings,
                encoded_depth=encoded_depth,
            )
        return
    _inspect_scalar(
        value,
        field=field,
        artifact=artifact,
        format_name=format_name,
        location=location,
        findings=findings,
        encoded_depth=encoded_depth,
    )


def _walk_arrow_field(
    field,
    *,
    artifact: Path,
    location: str,
    findings: list[PrivacyFinding],
) -> None:
    import pyarrow as pa

    _inspect_key(
        field.name,
        None,
        artifact=artifact,
        format_name="parquet",
        location=location,
        findings=findings,
    )
    dtype = field.type
    if pa.types.is_struct(dtype) or pa.types.is_union(dtype):
        for index, child in enumerate(dtype):
            _walk_arrow_field(
                child,
                artifact=artifact,
                location=f"{location}.{child.name or index}",
                findings=findings,
            )
    elif (
        pa.types.is_list(dtype)
        or pa.types.is_large_list(dtype)
        or pa.types.is_fixed_size_list(dtype)
    ):
        child = dtype.value_field
        _walk_arrow_field(
            child,
            artifact=artifact,
            location=f"{location}[]:{child.name}",
            findings=findings,
        )
    elif pa.types.is_map(dtype):
        for label, child in (
            ("<map-key>", dtype.key_field),
            ("<map-item>", dtype.item_field),
        ):
            _walk_arrow_field(
                child,
                artifact=artifact,
                location=f"{location}.{label}:{child.name}",
                findings=findings,
            )
    elif pa.types.is_dictionary(dtype):
        value_type = dtype.value_type
        if (
            pa.types.is_struct(value_type)
            or pa.types.is_list(value_type)
            or pa.types.is_large_list(value_type)
            or pa.types.is_map(value_type)
        ):
            synthetic = pa.field(f"{field.name}<dictionary-value>", value_type)
            _walk_arrow_field(
                synthetic,
                artifact=artifact,
                location=f"{location}<dictionary-value>",
                findings=findings,
            )


def _schema_is_allowlisted(name: str, columns: list[str]) -> bool:
    from control_tower.config import (
        ARTIFACT_COLUMNS,
        LEGACY_EARNINGS_ACTUALS_COLUMNS,
    )

    expected = list(ARTIFACT_COLUMNS[name])
    if name == "earnings_actuals.parquet":
        return tuple(columns) in {
            tuple(expected),
            LEGACY_EARNINGS_ACTUALS_COLUMNS,
        }
    if name == "events.parquet":
        without_optional = [column for column in columns if column != "importance"]
        return (
            without_optional == expected
            and columns.count("importance") <= 1
        )
    return columns == expected


def _scan_json(
    path: Path,
    findings: list[PrivacyFinding],
    *,
    json_lines: bool = False,
) -> None:
    format_name = "jsonl" if json_lines else "json"
    if json_lines:
        for line_number, line in enumerate(
            path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines(),
            1,
        ):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                _inspect_scalar(
                    line,
                    field=None,
                    artifact=path,
                    format_name=format_name,
                    location=f"line {line_number}",
                    findings=findings,
                    encoded_depth=0,
                )
                _finding(
                    findings,
                    artifact=path,
                    format_name=format_name,
                    location=f"line {line_number}",
                    rule_id="invalid_json",
                    matched=line,
                )
                continue
            _walk_value(
                value,
                field=None,
                artifact=path,
                format_name=format_name,
                location=f"line {line_number}",
                findings=findings,
            )
        return
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _finding(
            findings,
            artifact=path,
            format_name=format_name,
            location="file",
            rule_id="invalid_json",
            matched=path.name,
        )
        return
    _walk_value(
        value,
        field=None,
        artifact=path,
        format_name=format_name,
        location="$",
        findings=findings,
    )


def _scan_csv(path: Path, findings: list[PrivacyFinding]) -> None:
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle)
        for index, header in enumerate(reader.fieldnames or [], 1):
            _inspect_key(
                header,
                None,
                artifact=path,
                format_name="csv",
                location=f"header {index}",
                findings=findings,
            )
        for row_number, row in enumerate(reader, 2):
            _walk_value(
                row,
                field=None,
                artifact=path,
                format_name="csv",
                location=f"row {row_number}",
                findings=findings,
            )


def _scan_text(path: Path, findings: list[PrivacyFinding]) -> None:
    text = path.read_text(encoding="utf-8", errors="replace")
    format_name = path.suffix.lstrip(".") or "text"
    _inspect_scalar(
        text,
        field=None,
        artifact=path,
        format_name=format_name,
        location="file",
        findings=findings,
        encoded_depth=0,
    )
    for line_number, line in enumerate(text.splitlines(), 1):
        location = f"line {line_number}"
        encoded_line = line.encode("utf-8", errors="replace")
        if len(encoded_line) <= MAX_ENCODED_JSON_BYTES:
            decoded = _decode_json_scalar(line, 0)
            if decoded is not None:
                _walk_value(
                    decoded,
                    field=None,
                    artifact=path,
                    format_name=format_name,
                    location=f"{location}<json-record>",
                    findings=findings,
                    encoded_depth=1,
                )
            else:
                header = HEADER_LINE_RE.fullmatch(line)
                if header is not None:
                    key, value = header.groups()
                    # Do not reinterpret a bare URL as a ``scheme: value``
                    # header record.
                    if not (
                        _normalise_name(key)
                        in {"http", "https", "ftp", "s3"}
                        and value.lstrip().startswith("//")
                    ):
                        field = _inspect_key(
                            key,
                            value,
                            artifact=path,
                            format_name=format_name,
                            location=f"{location}.{key}",
                            findings=findings,
                        )
                        _walk_value(
                            value,
                            field=field,
                            artifact=path,
                            format_name=format_name,
                            location=f"{location}.{key}",
                            findings=findings,
                            encoded_depth=0,
                        )
        for url in re.findall(
            r"[A-Za-z][A-Za-z0-9+.-]*://[^\s\"'<>]+",
            line,
        ):
            if _url_has_secret(url):
                _finding(
                    findings,
                    artifact=path,
                    format_name=format_name,
                    location=location,
                    rule_id="secret_url",
                    matched=url,
                )


def _scan_parquet(
    path: Path,
    findings: list[PrivacyFinding],
    *,
    expected_artifact_name: str | None = None,
) -> None:
    import pyarrow.parquet as pq

    try:
        parquet_file = pq.ParquetFile(path)
        schema = parquet_file.schema_arrow
        if (
            expected_artifact_name is not None
            and not _schema_is_allowlisted(
                expected_artifact_name,
                list(schema.names),
            )
        ):
            _finding(
                findings,
                artifact=path,
                format_name="parquet",
                location="schema",
                rule_id="output_schema_not_allowlisted",
                matched="|".join(schema.names),
            )
        for index, field in enumerate(schema, 1):
            _walk_arrow_field(
                field,
                artifact=path,
                location=f"schema column {index}:{field.name}",
                findings=findings,
            )
        row_offset = 0
        for batch in parquet_file.iter_batches(batch_size=256):
            for row_index, row in enumerate(
                batch.to_pylist(),
                row_offset + 1,
            ):
                _walk_value(
                    row,
                    field=None,
                    artifact=path,
                    format_name="parquet",
                    location=f"row {row_index}",
                    findings=findings,
                )
            row_offset += batch.num_rows
    except Exception as exc:
        _finding(
            findings,
            artifact=path,
            format_name="parquet",
            location="file",
            rule_id="unreadable_parquet",
            matched=f"{type(exc).__name__}:{path.name}",
        )


def _scan_path(
    path: Path,
    findings: list[PrivacyFinding],
    *,
    expected_artifact_name: str | None = None,
) -> None:
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        _finding(
            findings,
            artifact=path,
            format_name="bundle",
            location=path.name,
            rule_id="unsupported_bundle_format",
            matched=path.name,
        )
    elif suffix == ".parquet":
        _scan_parquet(
            path,
            findings,
            expected_artifact_name=expected_artifact_name,
        )
    elif suffix == ".jsonl":
        _scan_json(path, findings, json_lines=True)
    elif suffix == ".json":
        _scan_json(path, findings)
    elif suffix == ".csv":
        _scan_csv(path, findings)
    else:
        _scan_text(path, findings)


def _validate_summary_evidence(
    active_root: Path,
    findings: list[PrivacyFinding],
) -> None:
    import pyarrow.parquet as pq

    news_path = active_root / "news_filings.parquet"
    health_path = active_root / "source_health.parquet"
    try:
        news_rows = pq.read_table(
            news_path,
            columns=[
                "source_id",
                "source_license_class",
                "derived_summary_if_permitted",
            ],
        ).to_pylist()
        health_rows = pq.read_table(
            health_path,
            columns=[
                "source_id",
                "status",
                "source_license_class",
            ],
        ).to_pylist()
    except Exception as exc:
        _finding(
            findings,
            artifact=news_path,
            format_name="parquet",
            location="derived-summary-evidence",
            rule_id="summary_evidence_unreadable",
            matched=type(exc).__name__,
        )
        return

    health_by_source: dict[str, list[dict[str, object]]] = {}
    for row in health_rows:
        source_id = str(row.get("source_id") or "").strip()
        health_by_source.setdefault(source_id, []).append(row)

    for row_number, row in enumerate(news_rows, 1):
        summary = row.get("derived_summary_if_permitted")
        if _placeholder(summary):
            continue
        source_id = str(row.get("source_id") or "").strip()
        row_license = _normalise_name(
            row.get("source_license_class") or ""
        )
        matching_health = health_by_source.get(source_id, [])
        permitted_health = [
            health
            for health in matching_health
            if _normalise_name(health.get("status") or "") == "available"
            and _normalise_name(
                health.get("source_license_class") or ""
            )
            in SUMMARY_PERMITTED_LICENSES
        ]
        if (
            row_license not in SUMMARY_PERMITTED_LICENSES
            or not permitted_health
        ):
            _finding(
                findings,
                artifact=news_path,
                format_name="parquet",
                location=(
                    f"row {row_number}."
                    "derived_summary_if_permitted"
                ),
                rule_id="summary_without_permitted_source_evidence",
                matched=f"{source_id}:{row_license}",
            )


def scan_generated_bundle(root: Path) -> list[PrivacyFinding]:
    """Scan the exact artifact set selected by the production app resolver."""

    from control_tower.config import (
        DATA_ARTIFACT_NAMES,
        LEGACY_GENERATION_DATA_ARTIFACT_NAMES,
        resolve_artifact_root,
    )

    resolution = resolve_artifact_root(Path(root))
    active = resolution.artifact_root
    actual_files = {entry.name for entry in active.iterdir()}
    actual_data_files = actual_files - {resolution.manifest_name}
    if actual_data_files == set(LEGACY_GENERATION_DATA_ARTIFACT_NAMES):
        accepted_data_artifact_names = LEGACY_GENERATION_DATA_ARTIFACT_NAMES
    else:
        accepted_data_artifact_names = DATA_ARTIFACT_NAMES
    expected_files = set(accepted_data_artifact_names) | {
        resolution.manifest_name
    }
    findings: list[PrivacyFinding] = []

    for name in sorted(actual_files - expected_files):
        _finding(
            findings,
            artifact=active / name,
            format_name="bundle",
            location=name,
            rule_id="unexpected_bundle_file",
            matched=name,
        )
    for name in sorted(expected_files - actual_files):
        _finding(
            findings,
            artifact=active / name,
            format_name="bundle",
            location=name,
            rule_id="missing_bundle_file",
            matched=name,
        )

    manifest_path = resolution.manifest_path
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        manifest = None
        _finding(
            findings,
            artifact=manifest_path,
            format_name="json",
            location="file",
            rule_id="invalid_manifest",
            matched=manifest_path.name,
        )

    if isinstance(manifest, dict):
        manifest_artifacts = manifest.get("artifacts")
        allowed_manifest_records = set(accepted_data_artifact_names) | {
            resolution.manifest_name
        }
        if (
            not isinstance(manifest_artifacts, dict)
            or set(manifest_artifacts) != allowed_manifest_records
        ):
            _finding(
                findings,
                artifact=manifest_path,
                format_name="json",
                location="$.artifacts",
                rule_id="manifest_artifact_allowlist_mismatch",
                matched=sorted(
                    manifest_artifacts
                    if isinstance(manifest_artifacts, dict)
                    else []
                ),
            )
        if resolution.current_target is not None:
            expected_generation_id = Path(
                resolution.current_target
            ).name
            if manifest.get("generation_id") != expected_generation_id:
                _finding(
                    findings,
                    artifact=manifest_path,
                    format_name="json",
                    location="$.generation_id",
                    rule_id="manifest_generation_mismatch",
                    matched=manifest.get("generation_id"),
                )
            if (
                manifest.get("current_pointer")
                != resolution.current_target
            ):
                _finding(
                    findings,
                    artifact=manifest_path,
                    format_name="json",
                    location="$.current_pointer",
                    rule_id="manifest_pointer_mismatch",
                    matched=manifest.get("current_pointer"),
                )

    for path in sorted(active.iterdir()):
        if not path.is_file():
            continue
        expected_name = (
            path.name
            if path.name in accepted_data_artifact_names
            else None
        )
        _scan_path(
            path,
            findings,
            expected_artifact_name=expected_name,
        )

    _validate_summary_evidence(active, findings)
    return _deduplicate(findings)


privacy_scan = scan_generated_bundle


def _load_streamlit_helpers():
    helper_path = Path(__file__).with_name(
        "test_research_control_tower_streamlit.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_ct_streamlit_fixture_helpers",
        helper_path,
    )
    assert spec is not None and spec.loader is not None
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    return helpers


def _load_build_helpers():
    helper_path = Path(__file__).with_name(
        "test_research_control_tower_build.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_ct_build_fixture_helpers",
        helper_path,
    )
    assert spec is not None and spec.loader is not None
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    return helpers


def _publish_fixture(
    publication_root: Path,
    generation_id: str,
    writer: Callable[[Path], None],
    *,
    mutate_manifest: Callable[[dict[str, object]], None] | None = None,
) -> Path:
    helpers = _load_streamlit_helpers()
    generation = (
        publication_root / "generations" / generation_id
    )
    generation.parent.mkdir(parents=True)
    writer(generation)

    def mutate(manifest: dict[str, object]) -> None:
        if mutate_manifest is not None:
            mutate_manifest(manifest)
        manifest["generation_id"] = generation_id
        manifest["current_pointer"] = (
            f"generations/{generation_id}"
        )

    helpers._rewrite_manifest(generation, mutate)
    (publication_root / "CURRENT").write_text(
        f"generations/{generation_id}\n",
        encoding="utf-8",
    )
    return publication_root


def _app_text(app) -> str:
    pieces: list[str] = []
    for attr in (
        "title",
        "header",
        "subheader",
        "caption",
        "markdown",
        "info",
        "warning",
        "error",
        "text",
    ):
        for item in getattr(app, attr, []):
            value = getattr(item, "value", "")
            if isinstance(value, str):
                pieces.append(value)
    for html in app.get("html"):
        pieces.append(str(html.proto.body))
    return "\n".join(pieces)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint_roots(
    roots: Iterable[Path],
    *,
    hash_cache: dict[tuple[str, int, int, int], str],
    metadata_only: Iterable[Path] = (),
) -> dict[str, tuple[int, int, str]]:
    metadata_only_resolved = {
        path.resolve(strict=False) for path in metadata_only
    }
    result: dict[str, tuple[int, int, str]] = {}
    for root in roots:
        if not root.exists() and not root.is_symlink():
            result[str(root.resolve(strict=False))] = (-1, -1, "")
            continue
        candidates = [root] if root.is_file() else sorted(root.rglob("*"))
        for path in candidates:
            if (
                "__pycache__" in path.parts
                or path.suffix in {".pyc", ".pyo"}
            ):
                continue
            if path.is_symlink():
                stat = path.lstat()
                result[str(path.resolve(strict=False))] = (
                    stat.st_size,
                    stat.st_mtime_ns,
                    f"symlink:{os.readlink(path)}",
                )
                continue
            if not path.is_file():
                continue
            resolved = path.resolve(strict=False)
            stat = path.stat()
            if resolved in metadata_only_resolved:
                digest = "<metadata-only>"
            else:
                cache_key = (
                    str(resolved),
                    stat.st_size,
                    stat.st_mtime_ns,
                    stat.st_ino,
                )
                digest = hash_cache.get(cache_key, "")
                if not digest:
                    digest = _file_sha256(path)
                    hash_cache[cache_key] = digest
            result[str(resolved)] = (
                stat.st_size,
                stat.st_mtime_ns,
                digest,
            )
    return result


def _is_under(path: object, roots: tuple[Path, ...]) -> bool:
    if isinstance(path, int):
        return False
    try:
        candidate = Path(path).resolve(strict=False)
    except (TypeError, ValueError, OSError):
        return False
    return any(
        candidate == root or root in candidate.parents
        for root in roots
    )


@dataclass
class _AuditGuard:
    phase: str = "unassigned"
    network_calls: list[tuple[str, str]] | None = None
    write_calls: list[tuple[str, str, str]] | None = None

    def __post_init__(self) -> None:
        if self.network_calls is None:
            self.network_calls = []
        if self.write_calls is None:
            self.write_calls = []


def _install_network_guard(
    monkeypatch: pytest.MonkeyPatch,
    audit: _AuditGuard,
) -> None:
    def blocked(name: str):
        def fail(*args: object, **kwargs: object) -> None:
            del args, kwargs
            assert audit.network_calls is not None
            audit.network_calls.append((audit.phase, name))
            raise NetworkViolation(f"{audit.phase}:{name}")

        return fail

    monkeypatch.setattr(
        socket,
        "create_connection",
        blocked("socket.create_connection"),
    )
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        blocked("socket.getaddrinfo"),
    )
    monkeypatch.setattr(
        socket,
        "gethostbyname",
        blocked("socket.gethostbyname"),
    )
    monkeypatch.setattr(
        socket,
        "gethostbyaddr",
        blocked("socket.gethostbyaddr"),
    )
    monkeypatch.setattr(
        socket,
        "getnameinfo",
        blocked("socket.getnameinfo"),
    )
    monkeypatch.setattr(
        socket.socket,
        "connect",
        blocked("socket.socket.connect"),
    )
    monkeypatch.setattr(
        socket.socket,
        "connect_ex",
        blocked("socket.socket.connect_ex"),
    )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        blocked("urllib.request.urlopen"),
    )
    monkeypatch.setattr(
        urllib.request.OpenerDirector,
        "open",
        blocked("urllib.request.OpenerDirector.open"),
    )
    try:
        import requests
    except ImportError:
        requests = None
    if requests is not None:
        monkeypatch.setattr(
            requests.sessions.Session,
            "request",
            blocked("requests.Session.request"),
        )
        monkeypatch.setattr(
            requests.api,
            "request",
            blocked("requests.api.request"),
        )
        monkeypatch.setattr(
            requests.api,
            "get",
            blocked("requests.api.get"),
        )
        monkeypatch.setattr(
            requests.api,
            "post",
            blocked("requests.api.post"),
        )
    try:
        import httpx
    except ImportError:
        httpx = None
    if httpx is not None:
        monkeypatch.setattr(
            httpx.Client,
            "request",
            blocked("httpx.Client.request"),
        )
        monkeypatch.setattr(
            httpx.AsyncClient,
            "request",
            blocked("httpx.AsyncClient.request"),
        )


def _install_write_guard(
    monkeypatch: pytest.MonkeyPatch,
    audit: _AuditGuard,
    protected_roots: tuple[Path, ...],
) -> None:
    resolved_roots = tuple(
        root.resolve(strict=False) for root in protected_roots
    )

    def reject(operation: str, path: object) -> None:
        if not _is_under(path, resolved_roots):
            return
        assert audit.write_calls is not None
        try:
            label = Path(path).name
        except (TypeError, ValueError):
            label = "<non-path>"
        audit.write_calls.append((audit.phase, operation, label))
        raise ProtectedWriteViolation(
            f"{audit.phase}:{operation}:{label}"
        )

    original_builtin_open = builtins.open
    original_io_open = io.open
    original_path_open = Path.open
    original_os_open = os.open

    def guarded_builtin_open(
        file: object,
        mode: str = "r",
        *args: object,
        **kwargs: object,
    ):
        if any(flag in mode for flag in "wax+"):
            reject("builtins.open", file)
        return original_builtin_open(file, mode, *args, **kwargs)

    def guarded_io_open(
        file: object,
        mode: str = "r",
        *args: object,
        **kwargs: object,
    ):
        if any(flag in mode for flag in "wax+"):
            reject("io.open", file)
        return original_io_open(file, mode, *args, **kwargs)

    def guarded_path_open(
        self: Path,
        mode: str = "r",
        *args: object,
        **kwargs: object,
    ):
        if any(flag in mode for flag in "wax+"):
            reject("Path.open", self)
        return original_path_open(self, mode, *args, **kwargs)

    write_flags = (
        os.O_WRONLY
        | os.O_RDWR
        | os.O_CREAT
        | os.O_TRUNC
        | os.O_APPEND
    )

    def guarded_os_open(
        path: object,
        flags: int,
        *args: object,
        **kwargs: object,
    ):
        if flags & write_flags:
            reject("os.open", path)
        return original_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_builtin_open)
    monkeypatch.setattr(io, "open", guarded_io_open)
    monkeypatch.setattr(Path, "open", guarded_path_open)
    monkeypatch.setattr(os, "open", guarded_os_open)

    for name in (
        "write_text",
        "write_bytes",
        "touch",
        "unlink",
        "mkdir",
        "rmdir",
    ):
        original = getattr(Path, name)

        def guarded_path_method(
            self: Path,
            *args: object,
            _name=name,
            _original=original,
            **kwargs: object,
        ):
            reject(f"Path.{_name}", self)
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(Path, name, guarded_path_method)

    for name in ("rename", "replace"):
        original = getattr(Path, name)

        def guarded_path_move(
            self: Path,
            target: object,
            *args: object,
            _name=name,
            _original=original,
            **kwargs: object,
        ):
            reject(f"Path.{_name}", self)
            reject(f"Path.{_name}", target)
            return _original(self, target, *args, **kwargs)

        monkeypatch.setattr(Path, name, guarded_path_move)

    for name in (
        "replace",
        "rename",
        "remove",
        "unlink",
        "mkdir",
        "rmdir",
        "makedirs",
        "removedirs",
    ):
        if not hasattr(os, name):
            continue
        original = getattr(os, name)

        def guarded_os_method(
            *args: object,
            _name=name,
            _original=original,
            **kwargs: object,
        ):
            paths = (
                args[:2]
                if _name in {"replace", "rename"}
                else args[:1]
            )
            for path in paths:
                reject(f"os.{_name}", path)
            return _original(*args, **kwargs)

        monkeypatch.setattr(os, name, guarded_os_method)

    for name, destination_indexes in {
        "copyfile": (1,),
        "copy": (1,),
        "copy2": (1,),
        "copymode": (1,),
        "copystat": (1,),
        "copytree": (1,),
        "move": (0, 1),
        "rmtree": (0,),
    }.items():
        original = getattr(shutil, name)

        def guarded_shutil_method(
            *args: object,
            _name=name,
            _indexes=destination_indexes,
            _original=original,
            **kwargs: object,
        ):
            for index in _indexes:
                if index < len(args):
                    reject(f"shutil.{_name}", args[index])
            return _original(*args, **kwargs)

        monkeypatch.setattr(shutil, name, guarded_shutil_method)


def _build_navigation_cases(tmp_path: Path) -> list[NavigationCase]:
    helpers = _load_streamlit_helpers()

    def synthetic_writer(root: Path) -> None:
        helpers._write_synthetic_populated_task7_bundle(root)

    def initial_writer(root: Path) -> None:
        helpers._write_bundle(root, previous_build_at=None)

    def degraded_mutation(manifest: dict[str, object]) -> None:
        artifacts = manifest["artifacts"]
        assert isinstance(artifacts, dict)
        news = artifacts["news_filings.parquet"]
        assert isinstance(news, dict)
        news["status"] = "unavailable"
        manifest["status"] = "degraded"
        manifest["degraded_inputs"] = ["news_filings"]

    cases: list[NavigationCase] = []

    def add(
        name: str,
        page: str,
        state: dict[str, object],
        expected_text: str,
        *,
        writer: Callable[[Path], None] = synthetic_writer,
        mutate_manifest: Callable[[dict[str, object]], None] | None = None,
    ) -> None:
        publication = _publish_fixture(
            tmp_path / name,
            f"{name}-gen",
            writer,
            mutate_manifest=mutate_manifest,
        )
        cases.append(
            NavigationCase(
                name=name,
                page=page,
                publication_root=publication,
                session_state={"ct_page": page, **state},
                expected_text=expected_text,
            )
        )

    add(
        "today-initial",
        "Today",
        {},
        "Initial snapshot",
        writer=initial_writer,
    )
    add("today-delta", "Today", {}, "What changed")
    for horizon in ("7d", "30d", "90d", "long_range"):
        add(
            f"timeline-{horizon}",
            "Unified Timeline",
            {"ct_horizon": horizon},
            "Unified timeline",
        )
    add(
        "timeline-filtered",
        "Unified Timeline",
        {
            "ct_horizon": "all",
            "ct_basket_ids": ("AI_BOTTLENECKS_GLOBAL",),
            "ct_countries": ("KR",),
            "ct_membership_tiers": ("core",),
            "ct_certainty_classes": ("thesis_checkpoint",),
        },
        "Unified timeline",
    )
    add(
        "ai-hbm-filtered",
        "AI Bottlenecks",
        {
            "ct_ai_layer": "hbm_memory",
            "ct_ai_tiers": ("core",),
            "ct_ai_countries": ("KR",),
        },
        "AI Bottlenecks",
    )
    add(
        "company-sk-hynix-primary",
        "Company",
        {
            "ct_company_entity": "SK_HYNIX",
            "ct_company_listing": "000660_KR",
        },
        "SK Hynix",
    )
    add(
        "company-sk-hynix-secondary",
        "Company",
        {
            "ct_company_entity": "SK_HYNIX",
            "ct_company_listing": "000660_US",
        },
        "SK Hynix",
    )
    add(
        "source-health",
        "Source Health",
        {},
        "Source Health",
    )
    add(
        "today-degraded",
        "Today",
        {},
        "Degraded data coverage",
        mutate_manifest=degraded_mutation,
    )
    return cases


def test_generated_bundle_uses_production_current_contract(
    tmp_path: Path,
) -> None:
    helpers = _load_streamlit_helpers()
    publication = _publish_fixture(
        tmp_path / "publication",
        "gen-001",
        helpers._write_bundle,
    )
    assert scan_generated_bundle(publication) == []

    unsafe = tmp_path / "unsafe-publication"
    unsafe.mkdir()
    target = unsafe / "not-generations"
    helpers._write_bundle(target)
    (unsafe / "CURRENT").write_text(
        "not-generations\n",
        encoding="utf-8",
    )
    from control_tower.config import ArtifactResolutionError

    with pytest.raises(
        ArtifactResolutionError,
        match="safe relative path",
    ):
        scan_generated_bundle(unsafe)


def test_legacy_earnings_schema_allowlist_is_exact() -> None:
    from control_tower.config import LEGACY_EARNINGS_ACTUALS_COLUMNS

    legacy = list(LEGACY_EARNINGS_ACTUALS_COLUMNS)
    assert _schema_is_allowlisted("earnings_actuals.parquet", legacy)
    assert not _schema_is_allowlisted(
        "earnings_actuals.parquet", legacy[:-1]
    )
    assert not _schema_is_allowlisted(
        "earnings_actuals.parquet", [*legacy, "unexpected_lineage"]
    )


def test_partial_artifact_generation_is_rejected(
    tmp_path: Path,
) -> None:
    helpers = _load_streamlit_helpers()
    publication = _publish_fixture(
        tmp_path / "publication",
        "gen-001",
        helpers._write_bundle,
    )
    (publication / "generations" / "gen-001" / "price_bars.parquet").unlink()

    from control_tower.config import ArtifactResolutionError

    with pytest.raises(ArtifactResolutionError, match="exact current or legacy contract"):
        scan_generated_bundle(publication)


def test_privacy_fixtures_use_final_health_entitlement_contract(
    tmp_path: Path,
) -> None:
    import pyarrow.parquet as pq

    from control_tower.config import ARTIFACT_COLUMNS
    from src.research_control_tower.build import (
        TASK3_HEALTH_ARROW_SCHEMA as producer_task3_schema,
        TASK3_HEALTH_COLUMNS as producer_task3_columns,
    )

    helpers = _load_streamlit_helpers()
    assert (
        tuple(ARTIFACT_COLUMNS["source_health.parquet"])
        == APP_SOURCE_HEALTH_COLUMNS
    )
    assert (
        tuple(helpers._columns()["source_health.parquet"])
        == APP_SOURCE_HEALTH_COLUMNS
    )
    assert (
        tuple(helpers._schema("source_health.parquet").names)
        == APP_SOURCE_HEALTH_COLUMNS
    )
    assert tuple(producer_task3_columns) == TASK3_HEALTH_COLUMNS
    assert tuple(producer_task3_schema.names) == TASK3_HEALTH_COLUMNS

    task3_path = tmp_path / "task3-source-health.parquet"
    pq.write_table(
        producer_task3_schema.empty_table(),
        task3_path,
    )
    findings: list[PrivacyFinding] = []
    _scan_path(task3_path, findings)
    assert _deduplicate(findings) == []


def test_populated_task3_to_task4_publication_is_scanner_clean(
    tmp_path: Path,
) -> None:
    import pandas as pd

    from src.research_control_tower.build import (
        BuildConfig,
        build_control_tower_marts,
        current_generation,
    )

    helpers = _load_build_helpers()
    input_root = helpers._copy_control_tower_inputs(
        tmp_path / "input" / "config"
    )
    consensus_root = helpers._write_task3_exports(
        tmp_path / "input" / "consensus"
    )
    config = BuildConfig(
        registry_root=input_root,
        event_root=input_root,
        output_dir=tmp_path / "publication",
        as_of_utc=pd.Timestamp("2026-08-13T12:00:00Z"),
        build_id="task8-populated-privacy-fixture",
        consensus_export_dir=consensus_root,
    )

    build_control_tower_marts(config)
    consensus = pd.read_parquet(
        current_generation(config.output_dir)
        / "consensus_snapshots.parquet"
    )

    assert not consensus.empty
    assert consensus["raw_hash"].str.fullmatch(r"[0-9a-f]{64}").all()
    assert scan_generated_bundle(config.output_dir) == []


def test_generated_bundle_reconciles_manifest_generation_and_pointer(
    tmp_path: Path,
) -> None:
    helpers = _load_streamlit_helpers()
    publication = _publish_fixture(
        tmp_path / "publication",
        "gen-001",
        helpers._write_bundle,
    )
    generation = publication / "generations" / "gen-001"
    helpers._rewrite_manifest(
        generation,
        lambda manifest: manifest.update(
            {
                "generation_id": "wrong-generation",
                "current_pointer": "generations/wrong-generation",
            }
        ),
    )
    rule_ids = {
        finding.rule_id
        for finding in scan_generated_bundle(publication)
    }
    assert {
        "manifest_generation_mismatch",
        "manifest_pointer_mismatch",
    } <= rule_ids


def test_legitimate_analytics_names_are_not_credentials(
    tmp_path: Path,
) -> None:
    safe = tmp_path / "safe.json"
    safe.write_text(
        json.dumps(
            {
                "token_count": 12,
                "prompt_tokens": 8,
                "completion_tokens": 4,
                "reasoning_tokens": 2,
                "total_tokens": 14,
                "token_share": 0.5,
                "raw_hash": "a" * 64,
                "content_hash_if_permitted": "b" * 64,
                "input_sha256": "c" * 64,
                "sha256": "d" * 64,
                "snapshot_id": "snapshot-1",
                "source_run_id": "run-1",
                "source_url": "s3://bucket/object?versionId=clean",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    findings: list[PrivacyFinding] = []
    _scan_path(safe, findings)
    assert _deduplicate(findings) == []


def test_json_and_jsonl_adversaries_cover_encoded_headers_and_signed_urls(
    tmp_path: Path,
) -> None:
    encoded = tmp_path / "encoded.json"
    encoded.write_text(
        json.dumps(
            {
                "metadata": json.dumps(
                    {
                        "request_headers": json.dumps(
                            {
                                "Authorization": (
                                    "Bearer fake-live-value"
                                ),
                                "api-token": "fake-api-token",
                            }
                        )
                    }
                )
            }
        )
        + "\n",
        encoding="utf-8",
    )
    signed = tmp_path / "signed.jsonl"
    signed.write_text(
        json.dumps(
            {
                "source_url": (
                    "s3://bucket/object?"
                    "X-Amz-Signature=fake-signature"
                )
            }
        )
        + "\n"
        + json.dumps(
            {
                "source_url": (
                    "https://example.test/path"
                    "#api-token=fake-fragment-token"
                )
            }
        )
        + "\n",
        encoding="utf-8",
    )

    findings: list[PrivacyFinding] = []
    _scan_path(encoded, findings)
    _scan_path(signed, findings)
    rule_ids = {finding.rule_id for finding in findings}
    assert "forbidden_header_field" in rule_ids
    assert "credential_field_name" in rule_ids
    assert "credential_value" in rule_ids
    assert "secret_url" in rule_ids


def test_csv_and_text_adversaries_cover_headers_html_and_one_line_body(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "rows.csv"
    csv_path.write_text(
        "snapshot_id,headers,source_url\n"
        "S1,\"{"
        "\"\"Cookie\"\":\"\"session=fake\"\""
        "}\",https://example.test/source\n",
        encoding="utf-8",
    )
    html_path = tmp_path / "body.txt"
    html_path.write_text(
        "<div><p>Full article body in an unexpected text artifact.</p></div>",
        encoding="utf-8",
    )
    long_path = tmp_path / "long.md"
    long_path.write_text(
        " ".join(
            ["This is article-like prose retained as a single line."]
            * 180
        ),
        encoding="utf-8",
    )

    findings: list[PrivacyFinding] = []
    for path in (csv_path, html_path, long_path):
        _scan_path(path, findings)
    rule_ids = {finding.rule_id for finding in findings}
    assert "forbidden_header_field" in rule_ids
    assert "credential_field_name" in rule_ids
    assert "credential_value" in rule_ids
    assert "body_like_text" in rule_ids


def test_plaintext_parses_headers_and_newline_json_without_secret_leakage(
    tmp_path: Path,
) -> None:
    header_secret = "fake-plaintext-bearer"
    signed_secret = "fake-plaintext-signature"
    nested_secret = "fake-plaintext-cookie"
    headers_path = tmp_path / "headers.txt"
    headers_path.write_text(
        "Title: harmless metadata\n"
        f"Authorization: Bearer {header_secret}\n"
        "Source-URL: https://example.test/object?"
        f"X-Amz-Signature={signed_secret}\n",
        encoding="utf-8",
    )
    records_path = tmp_path / "records.md"
    records_path.write_text(
        json.dumps(
            {
                "request_headers": json.dumps(
                    {"Cookie": nested_secret}
                )
            }
        )
        + "\n"
        + json.dumps(
            {
                "source_url": (
                    "https://example.test/object"
                    "#api-token=fake-plaintext-token"
                )
            }
        )
        + "\n",
        encoding="utf-8",
    )

    findings: list[PrivacyFinding] = []
    _scan_path(headers_path, findings)
    _scan_path(records_path, findings)
    rule_ids = {finding.rule_id for finding in findings}
    assert {
        "credential_field_name",
        "credential_value",
        "forbidden_header_field",
        "secret_url",
    } <= rule_ids
    rendered_findings = repr(findings)
    for secret in (
        header_secret,
        signed_secret,
        nested_secret,
        "fake-plaintext-token",
    ):
        assert secret not in rendered_findings


def test_parquet_adversaries_cover_recursive_schema_and_nested_values(
    tmp_path: Path,
) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    nested_type = pa.struct(
        [
            pa.field(
                "safe_struct",
                pa.struct(
                    [
                        pa.field("Authorization", pa.string()),
                        pa.field(
                            "safe_list",
                            pa.list_(
                                pa.struct(
                                    [
                                        pa.field(
                                            "api-token",
                                            pa.string(),
                                        )
                                    ]
                                )
                            ),
                        ),
                        pa.field(
                            "safe_map",
                            pa.map_(
                                pa.string(),
                                pa.struct(
                                    [
                                        pa.field(
                                            "x-amz-signature",
                                            pa.string(),
                                        )
                                    ]
                                ),
                            ),
                        ),
                    ]
                ),
            )
        ]
    )
    nested_schema_path = tmp_path / "nested-schema.parquet"
    pq.write_table(
        pa.Table.from_arrays(
            [pa.array([None], type=nested_type)],
            names=["metadata"],
        ),
        nested_schema_path,
    )

    nested_value_path = tmp_path / "nested-values.parquet"
    pq.write_table(
        pa.table(
            {
                "metadata": [
                    {
                        "safe": [
                            json.dumps(
                                {
                                    "request_headers": {
                                        "Cookie": "fake-cookie"
                                    }
                                }
                            )
                        ]
                    }
                ]
            }
        ),
        nested_value_path,
    )

    findings: list[PrivacyFinding] = []
    _scan_path(nested_schema_path, findings)
    _scan_path(nested_value_path, findings)
    rule_ids = {finding.rule_id for finding in findings}
    assert "credential_field_name" in rule_ids
    assert "forbidden_header_field" in rule_ids
    assert "credential_value" in rule_ids


def test_output_schema_allowlist_rejects_extra_parquet_columns(
    tmp_path: Path,
) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "news_filings.parquet"
    pq.write_table(
        pa.table(
            {
                "document_id": ["D1"],
                "raw_payload": [None],
            }
        ),
        path,
    )
    findings: list[PrivacyFinding] = []
    _scan_parquet(
        path,
        findings,
        expected_artifact_name="news_filings.parquet",
    )
    rule_ids = {finding.rule_id for finding in findings}
    assert "output_schema_not_allowlisted" in rule_ids
    assert "forbidden_body_field" in rule_ids


def test_derived_summary_requires_explicit_permitted_source_evidence(
    tmp_path: Path,
) -> None:
    import pyarrow.parquet as pq

    helpers = _load_streamlit_helpers()
    root = tmp_path / "evidence"
    root.mkdir()
    pq.write_table(
        helpers._schema("news_filings.parquet").empty_table().from_pylist(
            helpers._frame(
                "news_filings.parquet",
                [
                    {
                        "document_id": "allowed",
                        "source_id": "source:allowed",
                        "source_license_class": "official_public",
                        "derived_summary_if_permitted": (
                            "Permitted metadata-derived summary."
                        ),
                    },
                    {
                        "document_id": "missing",
                        "source_id": "source:missing",
                        "source_license_class": "discovery",
                        "derived_summary_if_permitted": (
                            "Unpermitted derived summary."
                        ),
                    },
                ],
            ).to_dict("records")
        ),
        root / "news_filings.parquet",
    )
    pq.write_table(
        helpers._schema("source_health.parquet").empty_table().from_pylist(
            helpers._frame(
                "source_health.parquet",
                [
                    {
                        "source_id": "source:allowed",
                        "status": "available",
                        "source_license_class": "official_public",
                        "entitlement_status": "permitted_public_metadata",
                        "entitlement_evidence": (
                            "Synthetic fixture permits metadata summary."
                        ),
                        "entitlement_ref": (
                            "fixture-policy:public-metadata-v1"
                        ),
                    }
                ],
            ).to_dict("records")
        ),
        root / "source_health.parquet",
    )
    findings: list[PrivacyFinding] = []
    _validate_summary_evidence(root, findings)
    summary_findings = [
        finding
        for finding in findings
        if finding.rule_id
        == "summary_without_permitted_source_evidence"
    ]
    assert len(summary_findings) == 1
    assert summary_findings[0].location.startswith("row 2.")


def test_all_required_app_states_are_isolated_network_and_write_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    streamlit = pytest.importorskip("streamlit")
    from streamlit.testing.v1 import AppTest

    old_dont_write_bytecode = sys.dont_write_bytecode
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    cases = _build_navigation_cases(tmp_path / "matrix")

    static_protected = (
        REPO_ROOT / "config",
        REPO_ROOT / "src",
        REPO_ROOT / "tests",
        REPO_ROOT / "docs",
        APP_ROOT,
        REPO_ROOT / ".config",
        FINANCIAL_DATA_ROOT / "src",
        FINANCIAL_DATA_ROOT / "tests",
        FINANCIAL_DATA_ROOT / "data",
        FINANCIAL_DATA_ROOT / ".config",
    )
    all_publications = tuple(
        case.publication_root for case in cases
    )
    protected_roots = static_protected + all_publications
    metadata_only = (
        REPO_ROOT / ".config",
        FINANCIAL_DATA_ROOT / ".config",
    )
    hash_cache: dict[tuple[str, int, int, int], str] = {}

    audit = _AuditGuard()
    _install_network_guard(monkeypatch, audit)
    _install_write_guard(monkeypatch, audit, protected_roots)

    for case in cases:
        audit.phase = case.name
        roots_for_case = static_protected + (
            case.publication_root,
        )
        before = _fingerprint_roots(
            roots_for_case,
            hash_cache=hash_cache,
            metadata_only=metadata_only,
        )
        monkeypatch.setenv(
            "CONTROL_TOWER_ARTIFACT_ROOT",
            str(case.publication_root),
        )
        streamlit.cache_data.clear()
        app = AppTest.from_file(
            str(APP_PATH),
            default_timeout=30,
        )
        for key, value in case.session_state.items():
            app.session_state[key] = value
        app = app.run()
        assert not app.exception, case.name
        if case.name == "company-sk-hynix-secondary":
            listing = next(
                item
                for item in app.selectbox
                if item.label == "Listing"
            )
            app = listing.select("000660_US").run()
            assert not app.exception, case.name
        assert app.session_state["ct_page"] == case.page
        assert case.expected_text in _app_text(app), case.name
        for key, value in case.session_state.items():
            assert app.session_state[key] == value, (
                case.name,
                key,
            )
        after = _fingerprint_roots(
            roots_for_case,
            hash_cache=hash_cache,
            metadata_only=metadata_only,
        )
        assert after == before, case.name
        assert not [
            call
            for call in audit.network_calls or []
            if call[0] == case.name
        ]
        assert not [
            call
            for call in audit.write_calls or []
            if call[0] == case.name
        ]

    assert sys.dont_write_bytecode is True
    monkeypatch.setattr(
        sys,
        "dont_write_bytecode",
        old_dont_write_bytecode,
    )
