"""Deterministic normalization helpers for macro event source frames."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd


MACRO_EVENT_COLUMNS = [
    "event_id",
    "event_key",
    "observation_version",
    "scope",
    "event_type",
    "title",
    "description",
    "status",
    "certainty_class",
    "confidence",
    "date_precision",
    "starts_at",
    "ends_at",
    "source_timezone",
    "source_id",
    "source_url",
    "source_published_at",
    "first_observed_at",
    "last_verified_at",
    "review_by",
    "supersedes_event_id",
    "evidence_class",
    "evidence_ref",
    "reference_period",
    "previous_value",
    "previous_vintage",
    "market_consensus",
    "consensus_source",
    "own_nowcast",
    "actual_value",
    "actual_unit",
    "revised_value",
    "surprise_value",
    "surprise_unit",
    "scenario_notes",
    "expected_metrics",
    "thesis_implications",
    "registry_version",
]


def _blank(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    try:
        missing = pd.isna(value)
        if isinstance(missing, bool) and missing:
            return True
    except (TypeError, ValueError):
        pass
    return not str(value).strip()


def _first(row: pd.Series, names: tuple[str, ...], default: Any = "") -> Any:
    for name in names:
        if name in row.index and not _blank(row[name]):
            return row[name]
    return default


def _safe_identifier(value: object) -> str:
    text = str(value).strip().upper()
    text = "".join(character if character.isalnum() else "_" for character in text)
    text = "_".join(token for token in text.split("_") if token)
    return text or "SOURCE"


def _source_timezone(row: pd.Series) -> str:
    timezone = str(
        _first(row, ("source_timezone", "timezone", "tz"), default="UTC")
    ).strip()
    try:
        ZoneInfo(timezone)
    except Exception as exc:
        raise ValueError(f"unknown source timezone: {timezone!r}") from exc
    return timezone


def _timestamp(value: object, timezone: str) -> pd.Timestamp | pd.NaT:
    if _blank(value):
        return pd.NaT
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        raise ValueError(f"invalid macro timestamp: {value!r}")
    parsed = pd.Timestamp(parsed)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.tz_localize(timezone)
    return parsed.tz_convert("UTC")


def _release_timestamp(
    row: pd.Series, timezone: str
) -> tuple[pd.Timestamp | pd.NaT, str]:
    raw_date = _first(
        row,
        (
            "release_datetime",
            "event_datetime",
            "starts_at",
            "release_date",
            "event_date",
            "date",
            "observation_date",
        ),
    )
    raw_time = _first(row, ("release_time", "event_time", "time"), default="")
    if _blank(raw_date):
        precision = _first(row, ("date_precision", "precision"), default="day")
        return pd.NaT, str(precision).strip()

    date_text = str(raw_date).strip()
    if not _blank(raw_time) and len(date_text) <= 10:
        date_text = f"{date_text} {str(raw_time).strip()}"
    parsed = _timestamp(date_text, timezone)
    if pd.isna(parsed):
        raise ValueError(f"invalid macro release date: {raw_date!r}")

    precision = _first(row, ("date_precision", "precision"), default="")
    if not _blank(precision):
        return parsed, str(precision).strip()
    return parsed, ("minute" if not _blank(raw_time) else "day")


def _metadata_timestamp(
    row: pd.Series,
    names: tuple[str, ...],
    timezone: str,
) -> pd.Timestamp | pd.NaT:
    raw = _first(
        row,
        names,
        default="",
    )
    return _timestamp(raw, timezone)


def _value(row: pd.Series, names: tuple[str, ...]) -> Any:
    return _first(row, names, default="")


def materialize_macro_calendar(
    source_frames: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Normalize macro source frames into the unified event shape.

    This is a pure function: it does not read files, access the network, or
    mutate any input frame.  Each mapping key becomes the deterministic
    ``event_type``/``source_id`` namespace.  Dates are interpreted in the
    row's source timezone and emitted as UTC-aware timestamps; calendar dates
    without a time use midnight in that source timezone.
    """

    rows: list[dict[str, Any]] = []
    for source_name in sorted(source_frames):
        frame = source_frames[source_name]
        if not isinstance(frame, pd.DataFrame):
            raise TypeError(f"macro source {source_name!r} is not a DataFrame")
        for row_number, (_, source_row) in enumerate(frame.copy(deep=True).iterrows()):
            timezone = _source_timezone(source_row)
            starts_at, precision = _release_timestamp(source_row, timezone)
            observed_at = _metadata_timestamp(
                source_row,
                (
                    "first_observed_at",
                    "retrieved_at",
                    "fetched_at",
                    "scraped_at",
                ),
                timezone,
            )
            source_namespace = _safe_identifier(source_name)
            timing_token = (
                starts_at.strftime("%Y%m%dT%H%M%SZ")
                if not pd.isna(starts_at)
                else "TIMING_UNAVAILABLE"
            )
            event_key = f"MACRO_{source_namespace}_{timing_token}_{row_number:04d}"
            title = str(
                _first(
                    source_row,
                    ("title", "event_title", "name", "indicator_name", "series_title"),
                    default=source_name,
                )
            ).strip()
            description = str(
                _first(source_row, ("description", "notes", "source_note"), default=title)
            ).strip()
            source_url = str(_first(source_row, ("source_url", "url"), default="")).strip()
            timing_available = not pd.isna(starts_at) and not pd.isna(observed_at)
            status = (
                str(_first(source_row, ("status", "calendar_status"), default="observed"))
                if timing_available
                else "unavailable"
            )
            certainty = str(
                _first(source_row, ("certainty_class", "certainty"), default="observed")
            )
            source_published = _metadata_timestamp(
                source_row,
                ("source_published_at", "published_at", "release_published_at"),
                timezone,
            )
            source_id = str(
                _first(source_row, ("source_id",), default=source_name)
            ).strip()
            rows.append(
                {
                    "event_id": event_key,
                    "event_key": event_key,
                    "observation_version": 1,
                    "scope": "macro",
                    "event_type": source_name,
                    "title": title,
                    "description": description,
                    "status": status,
                    "certainty_class": certainty,
                    "confidence": _value(source_row, ("confidence",)),
                    "date_precision": precision,
                    "starts_at": starts_at,
                    "ends_at": _timestamp(
                        _first(source_row, ("ends_at", "end_datetime"), default=""),
                        timezone,
                    ),
                    "source_timezone": timezone,
                    "source_id": source_id,
                    "source_url": source_url,
                    "source_published_at": source_published,
                    "first_observed_at": observed_at,
                    "last_verified_at": observed_at,
                    "review_by": _first(source_row, ("review_by",), default=""),
                    "supersedes_event_id": "",
                    "evidence_class": "source_observation",
                    "evidence_ref": source_url or f"source:{source_id}",
                    "reference_period": _value(source_row, ("reference_period", "period")),
                    "previous_value": _value(source_row, ("previous_value", "previous")),
                    "previous_vintage": _value(source_row, ("previous_vintage",)),
                    "market_consensus": _value(source_row, ("market_consensus", "consensus")),
                    "consensus_source": _value(source_row, ("consensus_source",)),
                    "own_nowcast": _value(source_row, ("own_nowcast", "nowcast")),
                    "actual_value": _value(source_row, ("actual_value", "actual", "value", "observation_value")),
                    "actual_unit": _value(
                        source_row, ("actual_unit", "unit", "observation_unit")
                    ),
                    "revised_value": _value(source_row, ("revised_value", "revised")),
                    "surprise_value": _value(source_row, ("surprise_value", "surprise")),
                    "surprise_unit": _value(source_row, ("surprise_unit",)),
                    "scenario_notes": _value(source_row, ("scenario_notes",)),
                    "expected_metrics": _value(source_row, ("expected_metrics",)),
                    "thesis_implications": _value(source_row, ("thesis_implications",)),
                    "registry_version": "v1",
                }
            )

    if not rows:
        return pd.DataFrame(columns=MACRO_EVENT_COLUMNS)
    return pd.DataFrame(rows, columns=MACRO_EVENT_COLUMNS)
