"""Page-scoped artifact loading for the Asia Markets terminal."""

from __future__ import annotations

import json
from typing import Any, Iterable

from .config import SECTORS
from .core import (
    artifact_mtime_ns,
    load_artifact,
    tr,
    unavailable_artifact,
)


ARTIFACT_LOAD_ERRORS = (
    FileNotFoundError,
    json.JSONDecodeError,
    TypeError,
    ValueError,
)


def load_sector_artifact(
    sector_key: str,
    language: str,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Load one canonical artifact and its optional localized presentation."""
    if sector_key not in SECTORS:
        raise KeyError(f"Unknown Asia Markets sector: {sector_key}")

    config = SECTORS[sector_key]
    slug = config["slug"]
    errors: list[str] = []

    try:
        current = load_artifact(
            slug,
            "en",
            artifact_mtime_ns(slug, "en"),
        )
    except ARTIFACT_LOAD_ERRORS as error:
        reason = f"{type(error).__name__}: {error}"
        current = unavailable_artifact(slug, reason)
        errors.append(
            tr(
                language,
                f"{config['name_en']} artifact is unavailable.",
                f"{config['name_zh']}的数据快照不可用。",
            )
        )
        return current, current, errors

    if language == "en":
        return current, current, errors

    try:
        localized = load_artifact(
            slug,
            language,
            artifact_mtime_ns(slug, language),
        )
    except ARTIFACT_LOAD_ERRORS:
        localized = current
        errors.append(
            tr(
                language,
                f"{config['name_en']} localized labels are unavailable; using English labels.",
                f"{config['name_zh']}的中文展示快照不可用，已改用英文标签。",
            )
        )
    return current, localized, errors


def load_all_sector_artifacts(
    language: str,
    sector_keys: Iterable[str] | None = None,
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    list[str],
]:
    """Load all requested sectors for aggregate pages."""
    keys = tuple(sector_keys) if sector_keys is not None else tuple(SECTORS)
    artifacts: dict[str, dict[str, Any]] = {}
    labels: dict[str, dict[str, Any]] = {}
    errors: list[str] = []

    for sector_key in keys:
        artifact, localized, sector_errors = load_sector_artifact(
            sector_key,
            language,
        )
        artifacts[sector_key] = artifact
        labels[sector_key] = localized
        errors.extend(sector_errors)

    return artifacts, labels, errors
