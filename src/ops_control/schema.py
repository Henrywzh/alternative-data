from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError


class RunReportSchemaError(ValueError):
    """Raised when the run-report schema or a report is invalid."""


_FORMAT_CHECKER = FormatChecker()


@_FORMAT_CHECKER.checks("date-time", raises=ValueError)
def _is_rfc3339_datetime(value: object) -> bool:
    if not isinstance(value, str):
        return True
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.tzinfo is not None


def validate_run_report(payload: dict[str, Any], schema_path: Path) -> None:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema, format_checker=_FORMAT_CHECKER).validate(payload)
    except (OSError, json.JSONDecodeError, SchemaError) as exc:
        raise RunReportSchemaError(f"run-report schema: {exc}") from exc
    except ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "<root>"
        raise RunReportSchemaError(f"{location}: {exc.message}") from exc
