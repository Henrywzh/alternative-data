"""Load and validate the source-backed Research Control Tower event ledger.

The event ledger is append-only at the observation level.  ``event_key`` is
the logical event identity, while the immutable observation key is
``(event_key, first_observed_at, observation_version)``.  A changed
observation is represented by a new row whose ``supersedes_event_id`` points
to the earlier observation; earlier rows are never replaced.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable
from zoneinfo import ZoneInfo

import pandas as pd

from .contracts import RegistryBundle, ValidationIssue


EVENT_FILES = {
    "events": "events.csv",
    "event_links": "event_links.csv",
    "event_watch_questions": "event_watch_questions.csv",
}

EVENT_REQUIRED_COLUMNS = {
    "events": {
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
    },
    "event_links": {
        "event_id",
        "target_type",
        "target_id",
        "link_role",
        "automated",
        "active_from",
        "active_to",
        "link_note",
        "registry_version",
    },
    "event_watch_questions": {
        "event_id",
        "question_id",
        "question",
        "question_type",
        "priority",
        "registry_version",
    },
}

EVENT_OBSERVATION_KEY = (
    "event_key",
    "first_observed_at",
    "observation_version",
)
EVENT_SCOPES = frozenset({"company", "basket", "macro", "policy", "index"})
EVENT_CERTAINTY_CLASSES = frozenset(
    {"hard", "provisional", "thesis_checkpoint", "observed"}
)
EVENT_EVIDENCE_CLASSES = frozenset(
    {"official_external", "source_observation", "internal_research"}
)
INTERNAL_RESEARCH_PREFIX = (
    "docs/superpowers/specs/2026-08-13-research-control-tower-design.md#"
)
EVENT_DATE_PRECISIONS = frozenset(
    {"minute", "day", "week", "month", "quarter", "half", "year"}
)
THESIS_DATE_PRECISIONS = frozenset({"week", "month", "quarter", "half", "year"})
EXACT_DATE_PRECISIONS = frozenset({"minute", "day"})
EVENT_STATUSES = frozenset(
    {
        "scheduled",
        "confirmed",
        "observed",
        "active",
        "watch",
        "completed",
        "cancelled",
        "unavailable",
    }
)
LINK_TARGET_TYPES = frozenset({"entity", "listing", "basket", "index"})
LINK_ROLES = frozenset({"primary", "affected", "automated", "watch_only", "context"})
SUPPORTED_ID = re.compile(r"^[A-Z0-9]+(?:_[A-Z0-9]+)*$")

TIMESTAMP_COLUMNS = (
    "starts_at",
    "ends_at",
    "source_published_at",
    "first_observed_at",
    "last_verified_at",
)
DATE_COLUMNS = ("active_from", "active_to", "review_by")
BOOLEAN_COLUMNS = ("automated",)
NUMERIC_COLUMNS = ("observation_version", "confidence")


@dataclass(frozen=True)
class EventBundle:
    """Frozen wrapper for the three normalized event-ledger frames."""

    events: pd.DataFrame
    event_links: pd.DataFrame
    event_watch_questions: pd.DataFrame


def _blank(value: object) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    try:
        missing = pd.isna(value)
        if not hasattr(missing, "__len__") and bool(missing):
            return True
    except (TypeError, ValueError):
        pass
    return not str(value).strip()


def _as_timestamp(value: object) -> pd.Timestamp | None:
    if _blank(value):
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    return parsed


def _is_timezone_aware(value: object) -> bool:
    parsed = _as_timestamp(value)
    if parsed is None:
        return False
    try:
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except (AttributeError, ValueError):
        return False


def _parse_timestamp_value(value: object) -> object:
    if _blank(value):
        return pd.NaT
    parsed = _as_timestamp(value)
    if parsed is None:
        return value
    if _is_timezone_aware(parsed):
        return parsed.tz_convert("UTC")
    # Preserve a naive timestamp so validation can explain the missing offset
    # instead of silently inventing UTC at load time.
    return parsed


def _parse_date_value(value: object) -> object:
    if _blank(value):
        return pd.NaT
    parsed = pd.to_datetime(value, format="%Y-%m-%d", errors="coerce")
    if pd.isna(parsed):
        return value
    return pd.Timestamp(parsed)


def _parse_boolean_value(value: object) -> object:
    if _blank(value):
        return pd.NA
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return value


def _read_event_csv(path: Path, name: str) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {name} registry: {path}")

    frame = pd.read_csv(
        path,
        dtype="string",
        keep_default_na=False,
        skipinitialspace=False,
    )
    missing = sorted(EVENT_REQUIRED_COLUMNS[name] - set(frame.columns))
    if missing:
        raise ValueError(
            f"{name} registry is missing required columns: {', '.join(missing)}"
        )

    for column in frame.select_dtypes(include=["string"]).columns:
        frame[column] = frame[column].str.strip()

    for column in TIMESTAMP_COLUMNS:
        if column in frame.columns:
            parsed_values = frame[column].map(_parse_timestamp_value)
            nonblank = [value for value in parsed_values if not _blank(value)]
            if any(not _is_timezone_aware(value) for value in nonblank):
                # Keep naive timestamps as naive values so validation can
                # reject them; ``utc=True`` here would silently invent UTC.
                frame[column] = pd.Series(
                    list(parsed_values), index=frame.index, dtype="object"
                )
            else:
                frame[column] = pd.to_datetime(parsed_values, utc=True)
    for column in DATE_COLUMNS:
        if column in frame.columns:
            parsed_values = frame[column].map(_parse_date_value)
            invalid = [
                (row_index, value)
                for row_index, value in parsed_values.items()
                if not _blank(value) and not isinstance(value, pd.Timestamp)
            ]
            if invalid:
                row_index, value = invalid[0]
                raise ValueError(
                    f"{name} row {row_index} has invalid {column}: {value!r}"
                )
            frame[column] = pd.to_datetime(parsed_values)
    for column in BOOLEAN_COLUMNS:
        if column in frame.columns:
            frame[column] = frame[column].map(_parse_boolean_value).astype("boolean")
    for column in NUMERIC_COLUMNS:
        if column in frame.columns:
            raw = frame[column].astype("string").str.strip()
            parsed = pd.to_numeric(raw.where(raw.ne("")), errors="coerce")
            frame[column] = parsed.astype("Int64" if column == "observation_version" else "Float64")
    return frame


def load_event_bundle(config_root: Path) -> EventBundle:
    """Load the three event-ledger CSVs with stable pandas dtypes."""

    root = Path(config_root)
    frames = {
        name: _read_event_csv(root / filename, name)
        for name, filename in EVENT_FILES.items()
    }
    return EventBundle(**frames)


def _issue(
    code: str,
    message: str,
    registry: str,
    row_index: int | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity="error",
        code=code,
        message=message,
        registry=registry,
        row_index=row_index,
    )


def _required_value_issues(
    frame: pd.DataFrame,
    registry: str,
    columns: Iterable[str],
) -> Iterable[ValidationIssue]:
    for column in sorted(columns):
        if column not in frame.columns:
            continue
        for row_index, value in frame[column].items():
            if _blank(value):
                yield _issue(
                    f"missing_{column}",
                    f"{registry} row {row_index} is missing required {column}",
                    registry,
                    int(row_index),
                )


def _duplicate_issues(
    frame: pd.DataFrame,
    registry: str,
    columns: list[str],
    code: str,
) -> Iterable[ValidationIssue]:
    if not set(columns) <= set(frame.columns):
        return
    duplicates = frame[frame.duplicated(columns, keep=False)]
    for _, row in duplicates.drop_duplicates(columns).iterrows():
        key = "/".join(str(row[column]) for column in columns)
        yield _issue(
            code,
            f"{registry} repeats natural key {key!r}",
            registry,
        )


def _timestamp_issues(
    events: pd.DataFrame,
) -> Iterable[ValidationIssue]:
    for column in TIMESTAMP_COLUMNS:
        if column not in events.columns:
            continue
        for row_index, value in events[column].items():
            if _blank(value):
                continue
            parsed = _as_timestamp(value)
            if parsed is None:
                yield _issue(
                    "invalid_event_timestamp",
                    f"events row {row_index} has invalid {column}={value!r}",
                    "events",
                    int(row_index),
                )
            elif not _is_timezone_aware(parsed):
                yield _issue(
                    "source_timestamp_not_timezone_aware",
                    f"events row {row_index} has naive {column}; source timestamps need a timezone",
                    "events",
                    int(row_index),
                )


def _date_issues(
    frame: pd.DataFrame,
    registry: str,
) -> Iterable[ValidationIssue]:
    for column in DATE_COLUMNS:
        if column not in frame.columns:
            continue
        for row_index, value in frame[column].items():
            if _blank(value):
                continue
            parsed = pd.to_datetime(value, format="%Y-%m-%d", errors="coerce")
            if pd.isna(parsed):
                yield _issue(
                    f"invalid_{column}_date",
                    f"{registry} row {row_index} has invalid {column}={value!r}",
                    registry,
                    int(row_index),
                )


def _as_date(value: object) -> pd.Timestamp | None:
    if _blank(value):
        return None
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    timestamp = pd.Timestamp(parsed)
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_localize(None)
    return timestamp.normalize()


def _valid_iana_timezone(value: object) -> bool:
    if _blank(value):
        return False
    try:
        ZoneInfo(str(value))
    except Exception:
        return False
    return True


def _evidence_issues(
    events: pd.DataFrame,
) -> Iterable[ValidationIssue]:
    for row_index, row in events.iterrows():
        evidence_class = str(row["evidence_class"])
        evidence_ref = str(row["evidence_ref"]).strip()
        if evidence_class not in EVENT_EVIDENCE_CLASSES:
            yield _issue(
                "invalid_evidence_class",
                f"events row {row_index} has invalid evidence_class={evidence_class!r}",
                "events",
                int(row_index),
            )
        if not evidence_ref:
            yield _issue(
                "missing_evidence_ref",
                f"events row {row_index} needs evidence_ref",
                "events",
                int(row_index),
            )
            continue
        if evidence_class == "internal_research":
            if (
                not evidence_ref.startswith(INTERNAL_RESEARCH_PREFIX)
                or not evidence_ref.removeprefix(INTERNAL_RESEARCH_PREFIX)
                or not re.fullmatch(
                    r"[a-z0-9]+(?:[.-][a-z0-9]+)*(?:-[a-z0-9]+)*",
                    evidence_ref.removeprefix(INTERNAL_RESEARCH_PREFIX),
                )
            ):
                yield _issue(
                    "invalid_internal_research_evidence_ref",
                    f"events row {row_index} needs the approved design-spec path and stable section",
                    "events",
                    int(row_index),
                )
            if not _blank(row["source_url"]):
                yield _issue(
                    "internal_research_must_not_use_source_url",
                    f"events row {row_index} must keep internal research out of source_url",
                    "events",
                    int(row_index),
                )
        if evidence_class == "official_external" and not evidence_ref.startswith(
            ("http://", "https://")
        ):
            yield _issue(
                "invalid_official_evidence_ref",
                f"events row {row_index} needs an external official evidence_ref",
                "events",
                int(row_index),
            )
        if evidence_class == "source_observation":
            local_ref = Path(evidence_ref)
            is_repo_relative = (
                not local_ref.is_absolute()
                and ".." not in local_ref.parts
                and bool(local_ref.parts)
                and local_ref.parts[0] in {"config", "data"}
            )
            if not (
                is_repo_relative
                or evidence_ref.startswith(("http://", "https://", "source:"))
            ):
                yield _issue(
                    "invalid_source_observation_evidence_ref",
                    f"events row {row_index} needs a source URI or repository-relative config/data path",
                    "events",
                    int(row_index),
                )


def _event_shape_issues(events: pd.DataFrame) -> Iterable[ValidationIssue]:
    for row_index, row in events.iterrows():
        scope = str(row["scope"])
        if scope not in EVENT_SCOPES:
            yield _issue(
                "invalid_event_scope",
                f"events row {row_index} has invalid scope={scope!r}",
                "events",
                int(row_index),
            )

        certainty = str(row["certainty_class"])
        if certainty not in EVENT_CERTAINTY_CLASSES:
            yield _issue(
                "invalid_certainty_class",
                f"events row {row_index} has invalid certainty_class={certainty!r}",
                "events",
                int(row_index),
            )

        precision = str(row["date_precision"])
        if precision not in EVENT_DATE_PRECISIONS:
            yield _issue(
                "invalid_date_precision",
                f"events row {row_index} has invalid date_precision={precision!r}",
                "events",
                int(row_index),
            )

        status = str(row["status"])
        if status not in EVENT_STATUSES:
            yield _issue(
                "invalid_event_status",
                f"events row {row_index} has invalid status={status!r}",
                "events",
                int(row_index),
            )

        source_timezone = row["source_timezone"]
        if not _valid_iana_timezone(source_timezone):
            yield _issue(
                "invalid_source_timezone",
                f"events row {row_index} has invalid source_timezone={source_timezone!r}",
                "events",
                int(row_index),
            )

        event_id = str(row["event_id"])
        event_key = str(row["event_key"])
        for field, value in (("event_id", event_id), ("event_key", event_key)):
            if _blank(value) or not SUPPORTED_ID.fullmatch(value):
                yield _issue(
                    f"invalid_{field}",
                    f"events row {row_index} has invalid {field}={value!r}",
                    "events",
                    int(row_index),
                )

        version = row["observation_version"]
        if _blank(version) or pd.isna(pd.to_numeric(version, errors="coerce")):
            yield _issue(
                "invalid_observation_version",
                f"events row {row_index} has invalid observation_version={version!r}",
                "events",
                int(row_index),
            )
        elif float(version) < 1 or float(version) % 1:
            yield _issue(
                "invalid_observation_version",
                f"events row {row_index} needs a positive integer observation_version",
                "events",
                int(row_index),
            )

        confidence = row["confidence"]
        if not _blank(confidence):
            parsed_confidence = pd.to_numeric(confidence, errors="coerce")
            if pd.isna(parsed_confidence) or not 0 <= float(parsed_confidence) <= 1:
                yield _issue(
                    "invalid_confidence",
                    f"events row {row_index} has confidence outside [0, 1]",
                    "events",
                    int(row_index),
                )

        starts_at = _as_timestamp(row["starts_at"])
        ends_at = _as_timestamp(row["ends_at"])
        if starts_at is None and status != "unavailable":
            yield _issue(
                "missing_starts_at",
                f"events row {row_index} is missing starts_at",
                "events",
                int(row_index),
            )
        if _blank(row["first_observed_at"]) and status != "unavailable":
            yield _issue(
                "missing_first_observed_at",
                f"events row {row_index} is missing first_observed_at",
                "events",
                int(row_index),
            )
        if starts_at is not None and ends_at is not None and starts_at > ends_at:
            yield _issue(
                "event_window_inverted",
                f"events row {row_index} must satisfy starts_at <= ends_at",
                "events",
                int(row_index),
            )

        if certainty in {"hard", "provisional"}:
            if _blank(row["source_url"]):
                yield _issue(
                    "hard_event_missing_source"
                    if certainty == "hard"
                    else "provisional_event_missing_source",
                    f"{certainty} event row {row_index} needs source_url",
                    "events",
                    int(row_index),
                )
            if _blank(row["first_observed_at"]):
                yield _issue(
                    "hard_event_missing_observation"
                    if certainty == "hard"
                    else "provisional_event_missing_observation",
                    f"{certainty} event row {row_index} needs first_observed_at",
                    "events",
                    int(row_index),
                )

        if certainty == "hard":
            if precision not in EXACT_DATE_PRECISIONS:
                yield _issue(
                    "hard_event_requires_exact_date",
                    f"hard event row {row_index} must use minute or day precision",
                    "events",
                    int(row_index),
                )
            if starts_at is not None and ends_at is not None and starts_at != ends_at:
                yield _issue(
                    "hard_event_requires_exact_date",
                    f"hard event row {row_index} cannot have a date range",
                    "events",
                    int(row_index),
                )

        if certainty == "thesis_checkpoint":
            if starts_at is None or ends_at is None:
                yield _issue(
                    "thesis_checkpoint_missing_window",
                    f"thesis checkpoint row {row_index} needs starts_at and ends_at",
                    "events",
                    int(row_index),
                )
            if precision not in THESIS_DATE_PRECISIONS:
                yield _issue(
                    "thesis_checkpoint_requires_range_precision",
                    f"thesis checkpoint row {row_index} needs non-exact date precision",
                    "events",
                    int(row_index),
                )
            if _blank(row["confidence"]):
                yield _issue(
                    "thesis_checkpoint_missing_confidence",
                    f"thesis checkpoint row {row_index} needs confidence",
                    "events",
                    int(row_index),
                )
            if _blank(row["review_by"]):
                yield _issue(
                    "thesis_checkpoint_missing_review_by",
                    f"thesis checkpoint row {row_index} needs review_by",
                    "events",
                    int(row_index),
                )
            if row["evidence_class"] != "internal_research":
                yield _issue(
                    "thesis_checkpoint_requires_internal_research_evidence",
                    f"thesis checkpoint row {row_index} needs internal_research evidence",
                    "events",
                    int(row_index),
                )

        actual_value = row["actual_value"]
        actual_unit = row["actual_unit"]
        if not _blank(actual_value):
            if _blank(actual_unit):
                yield _issue(
                    "actual_value_missing_unit",
                    f"events row {row_index} has actual_value without actual_unit",
                    "events",
                    int(row_index),
                )
            if ";" in str(actual_value):
                yield _issue(
                    "non_scalar_actual_value",
                    f"events row {row_index} must not store multiple observations in actual_value",
                    "events",
                    int(row_index),
                )
        if _blank(row["surprise_value"]) and not _blank(row["surprise_unit"]):
            yield _issue(
                "surprise_unit_without_value",
                f"events row {row_index} has surprise_unit without surprise_value",
                "events",
                int(row_index),
            )

        if row["event_type"] == "coverage_gap" and status != "unavailable":
            yield _issue(
                "coverage_gap_must_be_unavailable",
                f"coverage gap row {row_index} must have status=unavailable",
                "events",
                int(row_index),
            )


def _supersession_issues(events: pd.DataFrame) -> Iterable[ValidationIssue]:
    by_id = events.drop_duplicates("event_id", keep="first").set_index(
        "event_id", drop=False
    )
    for event_key, history in events.groupby("event_key", sort=True):
        versions = pd.to_numeric(
            history["observation_version"], errors="coerce"
        ).dropna()
        if versions.empty:
            continue
        integer_versions = sorted(
            int(version)
            for version in versions
            if float(version).is_integer() and int(version) > 0
        )
        if integer_versions != list(range(1, len(history) + 1)):
            yield _issue(
                "noncontiguous_observation_versions",
                f"event_key={event_key!r} must have contiguous versions starting at 1",
                "events",
            )

        children = history.loc[
            history["supersedes_event_id"].map(lambda value: not _blank(value)),
            "supersedes_event_id",
        ]
        for superseded_id, count in children.value_counts().sort_index().items():
            if count > 1:
                yield _issue(
                    "branched_supersession_chain",
                    f"event_key={event_key!r} has {count} observations superseding {superseded_id!r}",
                    "events",
                )

    for row_index, row in events.iterrows():
        supersedes = row["supersedes_event_id"]
        current_version = pd.to_numeric(row["observation_version"], errors="coerce")
        if _blank(supersedes):
            if not pd.isna(current_version) and int(current_version) > 1:
                yield _issue(
                    "missing_previous_observation",
                    f"events row {row_index} version >1 must supersede its immediate predecessor",
                    "events",
                    int(row_index),
                )
            continue
        supersedes_id = str(supersedes)
        if supersedes_id not in by_id.index:
            yield _issue(
                "supersedes_event_not_found",
                f"events row {row_index} supersedes unknown event_id={supersedes_id!r}",
                "events",
                int(row_index),
            )
            continue
        prior = by_id.loc[supersedes_id]
        current_observed = _as_timestamp(row["first_observed_at"])
        prior_observed = _as_timestamp(prior["first_observed_at"])
        if row["event_key"] != prior["event_key"]:
            yield _issue(
                "supersedes_event_key_mismatch",
                f"events row {row_index} supersedes an observation with a different event_key",
                "events",
                int(row_index),
            )
        prior_version = pd.to_numeric(prior["observation_version"], errors="coerce")
        if (
            current_observed is None
            or prior_observed is None
            or not _is_timezone_aware(current_observed)
            or not _is_timezone_aware(prior_observed)
            or current_observed <= prior_observed
            or pd.isna(current_version)
            or pd.isna(prior_version)
            or int(current_version) != int(prior_version) + 1
        ):
            yield _issue(
                "invalid_supersession_direction",
                f"events row {row_index} must supersede an earlier observation version",
                "events",
                int(row_index),
            )


def _registry_interval(
    registries: RegistryBundle,
    target_type: str,
    target_id: object,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    frame_by_type = {
        "entity": (registries.entities, "entity_id"),
        "listing": (registries.listings, "listing_id"),
        "basket": (registries.baskets, "basket_id"),
        "index": (registries.indices, "index_id"),
    }
    frame, id_column = frame_by_type[target_type]
    target = frame[frame[id_column] == target_id]
    if target.empty:
        return None, None
    row = target.iloc[0]
    return _as_date(row.get("active_from")), _as_date(row.get("active_to"))


def _date_interval_contains(
    parent_start: pd.Timestamp | None,
    parent_end: pd.Timestamp | None,
    child_start: pd.Timestamp | None,
    child_end: pd.Timestamp | None,
) -> bool:
    if parent_start is not None and (
        child_start is None or child_start < parent_start
    ):
        return False
    if parent_end is not None and (
        child_end is None or child_end > parent_end
    ):
        return False
    return True


def _link_issues(
    event_bundle: EventBundle,
    registries: RegistryBundle,
) -> Iterable[ValidationIssue]:
    events = event_bundle.events
    links = event_bundle.event_links
    event_ids = set(events["event_id"].dropna())
    events_by_id = events.drop_duplicates("event_id", keep="first").set_index(
        "event_id", drop=False
    )
    target_ids = {
        "entity": set(registries.entities.get("entity_id", pd.Series(dtype="string"))),
        "listing": set(registries.listings.get("listing_id", pd.Series(dtype="string"))),
        "basket": set(registries.baskets.get("basket_id", pd.Series(dtype="string"))),
        "index": set(registries.indices.get("index_id", pd.Series(dtype="string"))),
    }
    for row_index, row in links.iterrows():
        event_id = row["event_id"]
        target_type = str(row["target_type"])
        target_id = row["target_id"]
        if event_id not in event_ids:
            yield _issue(
                "orphan_event_link_event_id",
                f"event_links row {row_index} references unknown event_id={event_id!r}",
                "event_links",
                int(row_index),
            )
        if target_type not in LINK_TARGET_TYPES:
            yield _issue(
                "orphan_event_link_target_type",
                f"event_links row {row_index} has unknown target_type={target_type!r}",
                "event_links",
                int(row_index),
            )
            continue
        if target_id not in target_ids[target_type]:
            yield _issue(
                "orphan_event_link_target",
                f"event_links row {row_index} references unknown {target_type}={target_id!r}",
                "event_links",
                int(row_index),
            )
            continue

        active_from = _as_date(row["active_from"])
        active_to = _as_date(row["active_to"])
        if (
            active_from is not None
            and active_to is not None
            and active_to <= active_from
        ):
            yield _issue(
                "event_link_active_to_not_after_active_from",
                f"event_links row {row_index} must satisfy active_to > active_from",
                "event_links",
                int(row_index),
            )

        registry_start, registry_end = _registry_interval(
            registries, target_type, target_id
        )
        if event_id in events_by_id.index and active_from is not None:
            event = events_by_id.loc[event_id]
            event_start = _as_timestamp(event["starts_at"])
            event_end = _as_timestamp(event["ends_at"]) or event_start
            event_start_date = (
                event_start.tz_convert(str(event["source_timezone"])).tz_localize(None).normalize()
                if event_start is not None
                and _is_timezone_aware(event_start)
                and _valid_iana_timezone(event["source_timezone"])
                else None
            )
            event_end_date = (
                event_end.tz_convert(str(event["source_timezone"])).tz_localize(None).normalize()
                if event_end is not None
                and _is_timezone_aware(event_end)
                and _valid_iana_timezone(event["source_timezone"])
                else event_start_date
            )
            link_last_date = active_to - pd.Timedelta(days=1) if active_to is not None else None
            event_predates_registry = (
                event_end_date is not None
                and registry_start is not None
                and event_end_date < registry_start
            )
            overlaps_event = event_predates_registry or (
                event_start_date is not None
                and (link_last_date is None or link_last_date >= event_start_date)
                and (event_end_date is None or active_from <= event_end_date)
            )
            if not overlaps_event:
                yield _issue(
                    "event_link_outside_event_window",
                    f"event_links row {row_index} does not overlap the event observation window",
                    "event_links",
                    int(row_index),
                )

        if not _date_interval_contains(
            registry_start, registry_end, active_from, active_to
        ):
            yield _issue(
                "event_link_outside_target_interval",
                f"event_links row {row_index} is outside the target registry interval",
                "event_links",
                int(row_index),
            )

        role = str(row["link_role"])
        if role not in LINK_ROLES:
            yield _issue(
                "invalid_event_link_role",
                f"event_links row {row_index} has invalid link_role={role!r}",
                "event_links",
                int(row_index),
            )

        automated_value = row["automated"]
        if not _blank(automated_value) and not isinstance(automated_value, bool):
            yield _issue(
                "invalid_event_link_automated",
                f"event_links row {row_index} has invalid automated={automated_value!r}",
                "event_links",
                int(row_index),
            )
        automated = bool(automated_value) if not _blank(automated_value) else False
        automated = automated or role == "automated"
        if automated and target_type == "listing":
            listing = registries.listings[
                registries.listings["listing_id"] == target_id
            ]
            eligible = bool(listing.iloc[0]["collection_eligible"]) if not listing.empty else False
            if not eligible:
                yield _issue(
                    "ineligible_automated_listing_link",
                    f"event_links row {row_index} selects a non-eligible listing for automation",
                    "event_links",
                    int(row_index),
                )


def _watch_question_issues(
    event_bundle: EventBundle,
) -> Iterable[ValidationIssue]:
    events = event_bundle.events
    questions = event_bundle.event_watch_questions
    event_ids = set(events["event_id"].dropna())
    for row_index, row in questions.iterrows():
        if row["event_id"] not in event_ids:
            yield _issue(
                "orphan_event_watch_question",
                f"event_watch_questions row {row_index} references unknown event_id={row['event_id']!r}",
                "event_watch_questions",
                int(row_index),
            )
        if _blank(row["question"]):
            yield _issue(
                "empty_event_watch_question",
                f"event_watch_questions row {row_index} has an empty question",
                "event_watch_questions",
                int(row_index),
            )

    thesis_ids = set(
        events.loc[
            events["certainty_class"] == "thesis_checkpoint", "event_id"
        ].dropna()
    )
    questions_by_event = {
        event_id: group["question"].map(lambda value: not _blank(value)).any()
        for event_id, group in questions.groupby("event_id")
    }
    for event_id in sorted(thesis_ids):
        if not questions_by_event.get(event_id, False):
            row_index = int(events.index[events["event_id"] == event_id][0])
            yield _issue(
                "thesis_checkpoint_missing_watch_question",
                f"thesis checkpoint {event_id!r} needs at least one watch question",
                "event_watch_questions",
                row_index,
            )


def validate_event_bundle(
    events: EventBundle,
    registries: RegistryBundle,
    now_utc: pd.Timestamp,
) -> list[ValidationIssue]:
    """Return deterministic validation issues without mutating any input frame."""

    issues: list[ValidationIssue] = []
    now = _as_timestamp(now_utc)
    if now is None or not _is_timezone_aware(now):
        issues.append(
            _issue(
                "now_not_timezone_aware",
                "now_utc must be timezone-aware",
                "events",
            )
        )

    issues.extend(
        _required_value_issues(
            events.events,
            "events",
            {
                "event_id",
                "event_key",
                "observation_version",
                "scope",
                "event_type",
                "title",
                "description",
                "status",
                "certainty_class",
                "date_precision",
                "source_timezone",
                "evidence_class",
                "evidence_ref",
                "registry_version",
            },
        )
    )
    issues.extend(
        _required_value_issues(
            events.event_links,
            "event_links",
            {
                "event_id",
                "target_type",
                "target_id",
                "link_role",
                "automated",
                "active_from",
                "registry_version",
            },
        )
    )
    issues.extend(
        _required_value_issues(
            events.event_watch_questions,
            "event_watch_questions",
            {"event_id", "question_id", "question", "registry_version"},
        )
    )
    issues.extend(_duplicate_issues(events.events, "events", ["event_id"], "duplicate_event_id"))
    issues.extend(
        _duplicate_issues(
            events.events,
            "events",
            list(EVENT_OBSERVATION_KEY),
            "duplicate_event_observation_key",
        )
    )
    issues.extend(
        _duplicate_issues(
            events.event_links,
            "event_links",
            ["event_id", "target_type", "target_id", "link_role"],
            "duplicate_event_link",
        )
    )
    issues.extend(
        _duplicate_issues(
            events.event_watch_questions,
            "event_watch_questions",
            ["event_id", "question_id"],
            "duplicate_event_watch_question",
        )
    )
    issues.extend(_timestamp_issues(events.events))
    issues.extend(_date_issues(events.event_links, "event_links"))
    issues.extend(_date_issues(events.events, "events"))
    issues.extend(_evidence_issues(events.events))
    issues.extend(_event_shape_issues(events.events))
    issues.extend(_supersession_issues(events.events))
    issues.extend(_link_issues(events, registries))
    issues.extend(_watch_question_issues(events))
    return issues


def is_catalyst_eligible(events: pd.DataFrame) -> pd.Series:
    """Return the V1 timeline-selection gate for actionable catalysts.

    Coverage gaps and explicitly unavailable/cancelled rows remain auditable
    ledger observations but are excluded from next-catalyst selection.
    """

    event_type = events.get(
        "event_type", pd.Series("", index=events.index, dtype="string")
    ).astype("string")
    status = events.get(
        "status", pd.Series("", index=events.index, dtype="string")
    ).astype("string")
    return (
        event_type.str.strip().ne("coverage_gap")
        & ~status.str.strip().isin({"unavailable", "cancelled"})
    ).rename("catalyst_eligible")


def compute_t_minus(
    events: pd.DataFrame,
    now_utc: pd.Timestamp,
    viewer_timezone: str = "UTC",
) -> pd.Series:
    """Return calendar-day T-minus values in a caller-selected timezone.

    ``starts_at`` is the canonical event timestamp and is converted to the
    viewer timezone only for display semantics.  A range uses its start.  The
    operation subtracts local calendar dates, so an event can move from
    tomorrow to today when the viewer changes timezone even though its UTC
    instant is unchanged.
    """

    now = _as_timestamp(now_utc)
    if now is None or not _is_timezone_aware(now):
        raise ValueError("now_utc must be timezone-aware")
    try:
        timezone = ZoneInfo(viewer_timezone)
    except Exception as exc:  # pragma: no cover - zoneinfo supplies the detail
        raise ValueError(f"unknown viewer timezone: {viewer_timezone!r}") from exc

    if "starts_at" not in events.columns:
        raise ValueError("events must contain starts_at")

    now_local_date = now.tz_convert(timezone).date()
    values: list[int | pd._libs.missing.NAType] = []
    for value in events["starts_at"]:
        start = _as_timestamp(value)
        if start is None:
            values.append(pd.NA)
            continue
        if not _is_timezone_aware(start):
            raise ValueError("event starts_at values must be timezone-aware")
        values.append((start.tz_convert(timezone).date() - now_local_date).days)
    return pd.Series(values, index=events.index, name="t_minus", dtype="Int64")
