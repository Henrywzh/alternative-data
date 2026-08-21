"""Load and validate the Research Control Tower T3 human thesis and evidence seed layer.

Human owns thesis state; automation may only link evidence and flag conflict hints.
This module provides deterministic loader, validation, and querying routines for:
- thesis_claims
- thesis_watch_questions
- evidence_items
- claim_evidence_links
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

import pandas as pd

from .contracts import RegistryBundle, ValidationIssue
from .events import EventBundle, _read_event_csv, validate_event_bundle


THESIS_SEED_FILES = {
    "thesis_claims": "thesis_claims.csv",
    "thesis_watch_questions": "thesis_watch_questions.csv",
    "evidence_items": "evidence_items.csv",
    "claim_evidence_links": "claim_evidence_links.csv",
}

TENCENT_EVENT_SEED_FILES = {
    "events": "tencent_events.csv",
    "event_links": "tencent_event_links.csv",
    "event_watch_questions": "tencent_event_watch_questions.csv",
}

THESIS_REQUIRED_COLUMNS = {
    "thesis_claims": {
        "claim_id",
        "entity_id",
        "thesis_title",
        "claim_text",
        "invalidation_rule",
        "status",
        "last_reviewed_at_utc",
        "reviewed_by",
        "registry_version",
    },
    "thesis_watch_questions": {
        "question_id",
        "claim_id",
        "entity_id",
        "question",
        "question_type",
        "priority",
        "registry_version",
    },
    "evidence_items": {
        "evidence_id",
        "entity_id",
        "source_id",
        "source_type",
        "source_url",
        "evidence_class",
        "pit_class",
        "source_license_class",
        "published_at",
        "summary_text",
        "observed_at_utc",
        "registry_version",
    },
    "claim_evidence_links": {
        "link_id",
        "claim_id",
        "evidence_id",
        "conflict_hint",
        "review_state",
        "analyst_note",
        "registry_version",
    },
}

THESIS_STATUSES = frozenset({"draft", "active", "falsified", "confirmed", "archived"})
QUESTION_TYPES = frozenset({"support", "falsification", "tracking"})
QUESTION_PRIORITIES = frozenset({"1", "2", "3"})
EVIDENCE_SOURCE_TYPES = frozenset(
    {
        "filing",
        "consensus_revision",
        "corporate_action",
        "source_observation",
        "market_quote",
        "internal_research",
    }
)
EVIDENCE_CLASSES = frozenset(
    {
        "official_external",
        "source_observation",
        "internal_research",
    }
)
PIT_CLASSES = frozenset(
    {
        "point_in_time",
        "restated",
        "provisional",
    }
)
SOURCE_LICENSE_CLASSES = frozenset(
    {
        "public_regulatory_filing",
        "public_statutory_disclosure",
        "public_domain",
        "proprietary_internal",
        "commercial_licensed",
    }
)
LINK_REVIEW_STATES = frozenset({"pending_review", "acknowledged", "dismissed"})
SUPPORTED_ID = re.compile(r"^[A-Z0-9]+(?:_[A-Z0-9]+)*$")

TIMESTAMP_COLUMNS = {
    "thesis_claims": ("last_reviewed_at_utc",),
    "evidence_items": ("observed_at_utc", "published_at"),
}
BOOLEAN_COLUMNS = {
    "claim_evidence_links": ("conflict_hint",),
}


@dataclass(frozen=True)
class ThesisSeedBundle:
    """Frozen container for the four normalized thesis/evidence frames."""

    thesis_claims: pd.DataFrame
    thesis_watch_questions: pd.DataFrame
    evidence_items: pd.DataFrame
    claim_evidence_links: pd.DataFrame


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
    return parsed


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


def _read_thesis_csv(path: Path, name: str) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Missing {name} registry: {path}")

    frame = pd.read_csv(
        path,
        dtype="string",
        keep_default_na=False,
        skipinitialspace=False,
    )
    missing = sorted(THESIS_REQUIRED_COLUMNS[name] - set(frame.columns))
    if missing:
        raise ValueError(
            f"{name} registry is missing required columns: {', '.join(missing)}"
        )

    for column in frame.select_dtypes(include=["string"]).columns:
        frame[column] = frame[column].str.strip()

    ts_cols = TIMESTAMP_COLUMNS.get(name, ())
    for column in ts_cols:
        if column in frame.columns:
            parsed_values = frame[column].map(_parse_timestamp_value)
            nonblank = [val for val in parsed_values if not _blank(val)]
            if any(not _is_timezone_aware(val) for val in nonblank):
                frame[column] = pd.Series(
                    list(parsed_values), index=frame.index, dtype="object"
                )
            else:
                frame[column] = pd.to_datetime(parsed_values, utc=True)

    bool_cols = BOOLEAN_COLUMNS.get(name, ())
    for column in bool_cols:
        if column in frame.columns:
            frame[column] = frame[column].map(_parse_boolean_value).astype("boolean")

    return frame


def load_thesis_seed_bundle(config_root: Path) -> ThesisSeedBundle:
    """Load the four thesis seed CSVs with stable pandas dtypes."""
    root = Path(config_root)
    frames = {
        name: _read_thesis_csv(root / filename, name)
        for name, filename in THESIS_SEED_FILES.items()
    }
    return ThesisSeedBundle(
        thesis_claims=frames["thesis_claims"],
        thesis_watch_questions=frames["thesis_watch_questions"],
        evidence_items=frames["evidence_items"],
        claim_evidence_links=frames["claim_evidence_links"],
    )


def load_tencent_event_seed_bundle(config_root: Path) -> EventBundle:
    """Load the source-backed Tencent event seed CSVs as an EventBundle."""
    root = Path(config_root)
    frames = {
        name: _read_event_csv(root / filename, name)
        for name, filename in TENCENT_EVENT_SEED_FILES.items()
    }
    return EventBundle(
        events=frames["events"],
        event_links=frames["event_links"],
        event_watch_questions=frames["event_watch_questions"],
    )


def merge_event_bundles(base: EventBundle, addition: EventBundle) -> EventBundle:
    """Merge two event bundles deterministically and fail closed on duplicate natural keys."""
    # Check for duplicate event_id collisions between base and addition
    base_event_ids = set(base.events["event_id"].dropna())
    addition_event_ids = set(addition.events["event_id"].dropna())
    event_id_collision = base_event_ids & addition_event_ids
    if event_id_collision:
        raise ValueError(
            f"Cannot merge event bundles: duplicate event_id collision {sorted(event_id_collision)!r}"
        )

    # Check for duplicate event observation key collisions (event_key, first_observed_at, observation_version)
    def _obs_keys(df: pd.DataFrame) -> set[tuple]:
        if df.empty:
            return set()
        keys = set()
        for _, r in df.iterrows():
            keys.add((str(r.get("event_key", "")), str(r.get("first_observed_at", "")), str(r.get("observation_version", ""))))
        return keys

    obs_collision = _obs_keys(base.events) & _obs_keys(addition.events)
    if obs_collision:
        raise ValueError(
            f"Cannot merge event bundles: duplicate event observation key collision {sorted(obs_collision)!r}"
        )

    # Check for duplicate event_links natural key (event_id, target_type, target_id, link_role)
    def _link_keys(df: pd.DataFrame) -> set[tuple]:
        if df.empty:
            return set()
        keys = set()
        for _, r in df.iterrows():
            keys.add((str(r.get("event_id", "")), str(r.get("target_type", "")), str(r.get("target_id", "")), str(r.get("link_role", ""))))
        return keys

    link_collision = _link_keys(base.event_links) & _link_keys(addition.event_links)
    if link_collision:
        raise ValueError(
            f"Cannot merge event bundles: duplicate event link key collision {sorted(link_collision)!r}"
        )

    # Check for duplicate event_watch_questions natural key (event_id, question_id)
    def _question_keys(df: pd.DataFrame) -> set[tuple]:
        if df.empty:
            return set()
        keys = set()
        for _, r in df.iterrows():
            keys.add((str(r.get("event_id", "")), str(r.get("question_id", ""))))
        return keys

    question_collision = _question_keys(base.event_watch_questions) & _question_keys(addition.event_watch_questions)
    if question_collision:
        raise ValueError(
            f"Cannot merge event bundles: duplicate event watch question key collision {sorted(question_collision)!r}"
        )

    merged_events = pd.concat([base.events, addition.events], ignore_index=True)
    merged_links = pd.concat([base.event_links, addition.event_links], ignore_index=True)
    merged_questions = pd.concat(
        [base.event_watch_questions, addition.event_watch_questions], ignore_index=True
    )
    return EventBundle(
        events=merged_events,
        event_links=merged_links,
        event_watch_questions=merged_questions,
    )


def _issue(
    code: str,
    message: str,
    registry: str,
    row_index: int | None = None,
    severity: str = "error",
) -> ValidationIssue:
    return ValidationIssue(
        severity=severity,  # type: ignore[arg-type]
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


def _identifier_issues(
    frame: pd.DataFrame,
    registry: str,
    key: str,
) -> Iterable[ValidationIssue]:
    if key not in frame.columns:
        return
    for row_index, value in frame[key].items():
        if _blank(value) or not SUPPORTED_ID.fullmatch(str(value)):
            yield _issue(
                f"invalid_{key}",
                f"{registry} row {row_index} has invalid stable identifier {key}={value!r}",
                registry,
                int(row_index),
            )


def validate_thesis_seed_bundle(
    thesis: ThesisSeedBundle,
    registries: RegistryBundle,
    events: EventBundle,
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
                "thesis_claims",
            )
        )

    # 1. Required columns check
    # Non-optional columns:
    # thesis_claims: last_reviewed_at_utc and reviewed_by are optional when status is draft
    # claim_evidence_links: analyst_note is optional
    issues.extend(_required_value_issues(thesis.thesis_claims, "thesis_claims", {"claim_id", "entity_id", "thesis_title", "claim_text", "invalidation_rule", "status", "registry_version"}))
    issues.extend(_required_value_issues(thesis.thesis_watch_questions, "thesis_watch_questions", THESIS_REQUIRED_COLUMNS["thesis_watch_questions"]))
    issues.extend(_required_value_issues(thesis.evidence_items, "evidence_items", THESIS_REQUIRED_COLUMNS["evidence_items"]))
    issues.extend(_required_value_issues(thesis.claim_evidence_links, "claim_evidence_links", {"link_id", "claim_id", "evidence_id", "conflict_hint", "review_state", "registry_version"}))

    # 2. PK duplicate and identifier checks
    issues.extend(_duplicate_issues(thesis.thesis_claims, "thesis_claims", ["claim_id"], "duplicate_claim_id"))
    issues.extend(_identifier_issues(thesis.thesis_claims, "thesis_claims", "claim_id"))

    issues.extend(_duplicate_issues(thesis.thesis_watch_questions, "thesis_watch_questions", ["question_id"], "duplicate_question_id"))
    issues.extend(_identifier_issues(thesis.thesis_watch_questions, "thesis_watch_questions", "question_id"))

    issues.extend(_duplicate_issues(thesis.evidence_items, "evidence_items", ["evidence_id"], "duplicate_evidence_id"))
    issues.extend(_identifier_issues(thesis.evidence_items, "evidence_items", "evidence_id"))

    issues.extend(_duplicate_issues(thesis.claim_evidence_links, "claim_evidence_links", ["link_id"], "duplicate_link_id"))
    issues.extend(_duplicate_issues(thesis.claim_evidence_links, "claim_evidence_links", ["claim_id", "evidence_id"], "duplicate_claim_evidence_link"))
    issues.extend(_identifier_issues(thesis.claim_evidence_links, "claim_evidence_links", "link_id"))

    # 3. Foreign key integrity and semantic checks
    known_entities = set(registries.entities.get("entity_id", pd.Series(dtype="string")).dropna())
    known_claims = set(thesis.thesis_claims.get("claim_id", pd.Series(dtype="string")).dropna())
    known_evidence = set(thesis.evidence_items.get("evidence_id", pd.Series(dtype="string")).dropna())

    claims_by_id = thesis.thesis_claims.drop_duplicates("claim_id", keep="first").set_index("claim_id", drop=False)

    for row_index, row in thesis.thesis_claims.iterrows():
        entity_id = row.get("entity_id")
        if not _blank(entity_id) and entity_id not in known_entities:
            issues.append(
                _issue(
                    "orphan_claim_entity_id",
                    f"thesis_claims row {row_index} references unknown entity_id={entity_id!r}",
                    "thesis_claims",
                    int(row_index),
                )
            )
        status = str(row.get("status", "")).strip().lower()
        if status not in THESIS_STATUSES:
            issues.append(
                _issue(
                    "invalid_thesis_status",
                    f"thesis_claims row {row_index} has invalid status={status!r}",
                    "thesis_claims",
                    int(row_index),
                )
            )
        last_reviewed = _as_timestamp(row.get("last_reviewed_at_utc"))
        if last_reviewed is not None:
            if not _is_timezone_aware(last_reviewed):
                issues.append(
                    _issue(
                        "last_reviewed_at_utc_not_timezone_aware",
                        f"thesis_claims row {row_index} last_reviewed_at_utc must be timezone-aware",
                        "thesis_claims",
                        int(row_index),
                    )
                )
            elif now is not None and _is_timezone_aware(now) and last_reviewed > now:
                issues.append(
                    _issue(
                        "last_reviewed_at_in_future",
                        f"thesis_claims row {row_index} last_reviewed_at_utc is in the future",
                        "thesis_claims",
                        int(row_index),
                    )
                )

        # If status is not draft, reviewed_by and last_reviewed_at_utc are required
        if status in {"active", "falsified", "confirmed", "archived"}:
            if _blank(row.get("reviewed_by")):
                issues.append(
                    _issue(
                        "missing_reviewed_by",
                        f"thesis_claims row {row_index} with status={status!r} requires human reviewed_by",
                        "thesis_claims",
                        int(row_index),
                    )
                )
            if _blank(row.get("last_reviewed_at_utc")):
                issues.append(
                    _issue(
                        "missing_last_reviewed_at_utc",
                        f"thesis_claims row {row_index} with status={status!r} requires last_reviewed_at_utc",
                        "thesis_claims",
                        int(row_index),
                    )
                )

    for row_index, row in thesis.thesis_watch_questions.iterrows():
        claim_id = row.get("claim_id")
        entity_id = row.get("entity_id")
        if not _blank(claim_id) and claim_id not in known_claims:
            issues.append(
                _issue(
                    "orphan_watch_question_claim_id",
                    f"thesis_watch_questions row {row_index} references unknown claim_id={claim_id!r}",
                    "thesis_watch_questions",
                    int(row_index),
                )
            )
        if not _blank(entity_id) and entity_id not in known_entities:
            issues.append(
                _issue(
                    "orphan_watch_question_entity_id",
                    f"thesis_watch_questions row {row_index} references unknown entity_id={entity_id!r}",
                    "thesis_watch_questions",
                    int(row_index),
                )
            )
        if not _blank(claim_id) and claim_id in claims_by_id.index:
            parent_entity = claims_by_id.loc[claim_id].get("entity_id")
            if not _blank(entity_id) and entity_id != parent_entity:
                issues.append(
                    _issue(
                        "watch_question_entity_mismatch",
                        f"thesis_watch_questions row {row_index} entity_id={entity_id!r} does not match parent claim entity_id={parent_entity!r}",
                        "thesis_watch_questions",
                        int(row_index),
                    )
                )
        q_type = str(row.get("question_type", "")).strip().lower()
        if q_type not in QUESTION_TYPES:
            issues.append(
                _issue(
                    "invalid_question_type",
                    f"thesis_watch_questions row {row_index} has invalid question_type={q_type!r}",
                    "thesis_watch_questions",
                    int(row_index),
                )
            )
        priority = str(row.get("priority", "")).strip()
        if priority not in QUESTION_PRIORITIES:
            issues.append(
                _issue(
                    "invalid_question_priority",
                    f"thesis_watch_questions row {row_index} has invalid priority={priority!r}",
                    "thesis_watch_questions",
                    int(row_index),
                )
            )

    for row_index, row in thesis.evidence_items.iterrows():
        entity_id = row.get("entity_id")
        if not _blank(entity_id) and entity_id not in known_entities:
            issues.append(
                _issue(
                    "orphan_evidence_entity_id",
                    f"evidence_items row {row_index} references unknown entity_id={entity_id!r}",
                    "evidence_items",
                    int(row_index),
                )
            )
        source_type = str(row.get("source_type", "")).strip().lower()
        if source_type not in EVIDENCE_SOURCE_TYPES:
            issues.append(
                _issue(
                    "invalid_evidence_source_type",
                    f"evidence_items row {row_index} has invalid source_type={source_type!r}",
                    "evidence_items",
                    int(row_index),
                )
            )
        evidence_class = str(row.get("evidence_class", "")).strip().lower()
        if evidence_class not in EVIDENCE_CLASSES:
            issues.append(
                _issue(
                    "invalid_evidence_class",
                    f"evidence_items row {row_index} has invalid evidence_class={evidence_class!r}",
                    "evidence_items",
                    int(row_index),
                )
            )
        pit_class = str(row.get("pit_class", "")).strip().lower()
        if pit_class not in PIT_CLASSES:
            issues.append(
                _issue(
                    "invalid_pit_class",
                    f"evidence_items row {row_index} has invalid pit_class={pit_class!r}",
                    "evidence_items",
                    int(row_index),
                )
            )
        license_class = str(row.get("source_license_class", "")).strip().lower()
        if license_class not in SOURCE_LICENSE_CLASSES:
            issues.append(
                _issue(
                    "invalid_source_license_class",
                    f"evidence_items row {row_index} has invalid source_license_class={license_class!r}",
                    "evidence_items",
                    int(row_index),
                )
            )
        observed_at = _as_timestamp(row.get("observed_at_utc"))
        published_at = _as_timestamp(row.get("published_at"))
        if observed_at is not None:
            if not _is_timezone_aware(observed_at):
                issues.append(
                    _issue(
                        "observed_at_utc_not_timezone_aware",
                        f"evidence_items row {row_index} observed_at_utc must be timezone-aware",
                        "evidence_items",
                        int(row_index),
                    )
                )
            elif now is not None and _is_timezone_aware(now) and observed_at > now:
                issues.append(
                    _issue(
                        "observed_at_utc_in_future",
                        f"evidence_items row {row_index} observed_at_utc is in the future",
                        "evidence_items",
                        int(row_index),
                    )
                )
        if published_at is not None:
            if not _is_timezone_aware(published_at):
                issues.append(
                    _issue(
                        "published_at_not_timezone_aware",
                        f"evidence_items row {row_index} published_at must be timezone-aware",
                        "evidence_items",
                        int(row_index),
                    )
                )
            elif now is not None and _is_timezone_aware(now) and published_at > now:
                issues.append(
                    _issue(
                        "published_at_in_future",
                        f"evidence_items row {row_index} published_at is in the future",
                        "evidence_items",
                        int(row_index),
                    )
                )
        if (
            observed_at is not None
            and published_at is not None
            and _is_timezone_aware(observed_at)
            and _is_timezone_aware(published_at)
        ):
            if observed_at < published_at:
                issues.append(
                    _issue(
                        "observed_at_before_published_at",
                        f"evidence_items row {row_index} observed_at_utc ({observed_at}) is before published_at ({published_at})",
                        "evidence_items",
                        int(row_index),
                    )
                )

    for row_index, row in thesis.claim_evidence_links.iterrows():
        claim_id = row.get("claim_id")
        evidence_id = row.get("evidence_id")
        if not _blank(claim_id) and claim_id not in known_claims:
            issues.append(
                _issue(
                    "orphan_claim_evidence_link_claim_id",
                    f"claim_evidence_links row {row_index} references unknown claim_id={claim_id!r}",
                    "claim_evidence_links",
                    int(row_index),
                )
            )
        if not _blank(evidence_id) and evidence_id not in known_evidence:
            issues.append(
                _issue(
                    "orphan_claim_evidence_link_evidence_id",
                    f"claim_evidence_links row {row_index} references unknown evidence_id={evidence_id!r}",
                    "claim_evidence_links",
                    int(row_index),
                )
            )
        review_state = str(row.get("review_state", "")).strip().lower()
        if review_state not in LINK_REVIEW_STATES:
            issues.append(
                _issue(
                    "invalid_link_review_state",
                    f"claim_evidence_links row {row_index} has invalid review_state={review_state!r}",
                    "claim_evidence_links",
                    int(row_index),
                )
            )
        conflict_hint = row.get("conflict_hint")
        if not _blank(conflict_hint) and not isinstance(conflict_hint, bool):
            issues.append(
                _issue(
                    "invalid_conflict_hint_boolean",
                    f"claim_evidence_links row {row_index} has non-boolean conflict_hint={conflict_hint!r}",
                    "claim_evidence_links",
                    int(row_index),
                )
            )

    return issues


def get_entity_thesis_claims(thesis_bundle: ThesisSeedBundle, entity_id: str) -> pd.DataFrame:
    """Return all thesis claims registered for a given entity."""
    claims = thesis_bundle.thesis_claims
    if claims.empty or "entity_id" not in claims.columns:
        return claims.copy()
    return claims[claims["entity_id"] == entity_id].copy()


def get_claim_watch_questions(thesis_bundle: ThesisSeedBundle, claim_id: str) -> pd.DataFrame:
    """Return watch questions attached to a thesis claim."""
    questions = thesis_bundle.thesis_watch_questions
    if questions.empty or "claim_id" not in questions.columns:
        return questions.copy()
    return questions[questions["claim_id"] == claim_id].copy()


def get_claim_evidence(thesis_bundle: ThesisSeedBundle, claim_id: str) -> pd.DataFrame:
    """Return evidence items joined to a thesis claim with review state and notes."""
    links = thesis_bundle.claim_evidence_links
    items = thesis_bundle.evidence_items
    if links.empty or items.empty:
        return pd.DataFrame()
    claim_links = links[links["claim_id"] == claim_id]
    if claim_links.empty:
        return pd.DataFrame()
    joined = claim_links.merge(items, on="evidence_id", how="inner")
    return joined


def count_active_conflicts(thesis_bundle: ThesisSeedBundle, entity_id: str | None = None) -> int:
    """Count active pending conflict hints across claims (optionally filtered by entity)."""
    links = thesis_bundle.claim_evidence_links
    claims = thesis_bundle.thesis_claims
    if links.empty:
        return 0
    conflicts = links[
        links["conflict_hint"].fillna(False).astype(bool)
        & links["review_state"].astype("string").str.strip().eq("pending_review")
    ]
    if conflicts.empty:
        return 0
    if entity_id is not None and not claims.empty:
        entity_claims = set(claims.loc[claims["entity_id"] == entity_id, "claim_id"])
        conflicts = conflicts[conflicts["claim_id"].isin(entity_claims)]
    return len(conflicts)
