"""Fixed local artifact and schema configuration for Control Tower V1.

This module contains only path-bound constants and read-only fingerprinting.
It deliberately does not discover runs, create directories, or import the
Streamlit runtime.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final


SCHEMA_VERSION: Final[str] = "control_tower_marts_v1"
NETWORK_POLICY: Final[str] = "forbidden"
_SAFE_GENERATION_ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")

ARTIFACT_NAMES: Final[tuple[str, ...]] = (
    "entities.parquet",
    "listings.parquet",
    "baskets.parquet",
    "basket_memberships.parquet",
    "indices.parquet",
    "events.parquet",
    "event_entity_links.parquet",
    "event_basket_links.parquet",
    "event_watch_questions.parquet",
    "macro_observations.parquet",
    "consensus_snapshots.parquet",
    "consensus_revisions.parquet",
    "quote_snapshots.parquet",
    "news_filings.parquet",
    "source_health.parquet",
    "build_manifest.json",
)

MANIFEST_FILENAMES: Final[tuple[str, ...]] = ("build_manifest.json", "manifest.json")
DATA_ARTIFACT_NAMES: Final[tuple[str, ...]] = tuple(
    name for name in ARTIFACT_NAMES if name != "build_manifest.json"
)
LEGACY_DATA_ARTIFACT_NAMES: Final[tuple[str, ...]] = tuple(
    name for name in DATA_ARTIFACT_NAMES if name != "quote_snapshots.parquet"
)

OPTIONAL_ARTIFACT_NAMES: Final[tuple[str, ...]] = (
    "consensus_snapshots.parquet",
    "consensus_revisions.parquet",
    "quote_snapshots.parquet",
    "news_filings.parquet",
)

REQUIRED_ARTIFACT_NAMES: Final[tuple[str, ...]] = tuple(
    name for name in ARTIFACT_NAMES if name not in OPTIONAL_ARTIFACT_NAMES
)


ARTIFACT_COLUMNS: Final[dict[str, tuple[str, ...]]] = {
    "entities.parquet": (
        "entity_id", "legal_name", "display_name", "country", "sector",
        "industry", "active_status", "active_from", "active_to",
        "registry_version", "source_or_research_note",
    ),
    "listings.parquet": (
        "listing_id", "entity_id", "exchange", "native_ticker",
        "canonical_ticker", "financial_data_security_id",
        "financial_data_issuer_group_id", "mapping_status",
        "mapping_verified_at", "mapping_source_url", "collection_eligible",
        "listing_role", "vendor_tickers", "currency", "primary_listing",
        "active_from", "active_to", "listing_status", "registry_version",
        "source_url", "source_or_research_note",
    ),
    "baskets.parquet": (
        "basket_id", "display_name", "purpose", "active_from", "active_to",
        "registry_version", "source_or_research_note",
    ),
    "basket_memberships.parquet": (
        "entity_id", "basket_id", "membership_tier", "primary_layer",
        "secondary_layers", "active_from", "active_to", "membership_reason",
        "source_or_research_note", "registry_version",
    ),
    "indices.parquet": (
        "index_id", "region", "display_name", "official_code",
        "official_code_namespace", "official_code_provider", "provider_symbol",
        "provider_symbol_namespace", "provider_symbol_provider", "provider",
        "currency", "active_from", "active_to", "registry_version",
        "source_url", "source_or_research_note",
    ),
    "events.parquet": (
        "event_id", "event_key", "observation_version", "scope", "event_type",
        "title", "description", "status", "certainty_class", "confidence",
        "date_precision", "starts_at", "ends_at", "source_timezone", "source_id",
        "source_url", "source_published_at", "first_observed_at",
        "last_verified_at", "review_by", "supersedes_event_id", "evidence_class",
        "evidence_ref", "reference_period", "previous_value", "previous_vintage",
        "market_consensus", "consensus_source", "own_nowcast", "actual_value",
        "actual_unit", "revised_value", "surprise_value", "surprise_unit",
        "scenario_notes", "expected_metrics", "thesis_implications",
        "registry_version",
    ),
    "event_entity_links.parquet": (
        "event_id", "target_type", "target_id", "link_role", "automated",
        "active_from", "active_to", "link_note", "registry_version",
    ),
    "event_basket_links.parquet": (
        "event_id", "target_type", "target_id", "link_role", "automated",
        "active_from", "active_to", "link_note", "registry_version",
    ),
    "event_watch_questions.parquet": (
        "event_id", "question_id", "question", "question_type", "priority",
        "registry_version",
    ),
    "macro_observations.parquet": (
        "observation_id", "event_id", "source_id", "series_id", "scope",
        "event_type", "metric_name", "reference_period", "observation_date",
        "release_at", "actual_value", "unit", "frequency", "first_observed_at",
        "source_published_at", "retrieved_at_utc", "source_url", "pit_class",
        "source_license_class", "is_provisional", "registry_version",
    ),
    "consensus_snapshots.parquet": (
        "snapshot_id", "provider", "entity_id", "listing_id",
        "financial_data_security_id", "canonical_ticker", "metric",
        "fiscal_period", "fiscal_year", "estimate_period_end", "horizon",
        "snapshot_at", "value", "statistic", "low_value", "high_value",
        "analyst_count", "provider_contributor_count", "currency", "unit",
        "accounting_basis", "provider_asof", "retrieved_at_utc", "source_url",
        "raw_hash", "pit_class", "source_run_id", "calculation_origin",
        "coverage_reason",
    ),
    "consensus_revisions.parquet": (
        "revision_id", "snapshot_id", "provider", "prior_provider", "entity_id",
        "listing_id", "financial_data_security_id", "canonical_ticker", "metric",
        "fiscal_period", "fiscal_year", "estimate_period_end", "horizon",
        "statistic", "current_snapshot_at", "current_value",
        "current_analyst_count", "current_dispersion", "lookback_days",
        "cutoff_at", "prior_snapshot_id", "prior_snapshot_at", "prior_value",
        "prior_provider_asof", "provider_asof", "retrieved_at_utc", "source_url",
        "pit_class", "source_run_id", "prior_analyst_count", "revision_value",
        "revision_pct", "analyst_count_change", "dispersion", "alignment_status",
    ),
    "quote_snapshots.parquet": (
        "quote_id", "listing_id", "canonical_ticker", "provider_symbol",
        "quote_timestamp", "retrieved_at_utc", "last_price", "bid", "ask",
        "day_change_pct", "volume", "currency", "market_status", "latency_class",
        "source_id", "source_url", "pit_class", "source_license_class",
        "registry_version",
    ),
    "news_filings.parquet": (
        "document_id", "document_type", "source_id", "headline", "publisher",
        "published_at", "first_observed_at", "source_url", "language",
        "related_entity_ids", "related_listing_ids", "related_basket_ids",
        "event_class", "importance", "source_quality", "pit_class",
        "source_license_class", "content_hash_if_permitted",
        "derived_summary_if_permitted",
    ),
    "source_health.parquet": (
        "source_id", "input_path", "source_kind", "status", "required",
        "row_count", "first_observation_at", "latest_observation_at",
        "source_latest_at", "retrieved_at_utc", "cadence", "source_url",
        "pit_class", "source_license_class", "entitlement_status",
        "entitlement_evidence", "entitlement_ref", "input_sha256", "schema_version",
        "missing_geographies", "detail",
    ),
}

EVENT_OPTIONAL_COLUMNS: Final[tuple[str, ...]] = ("importance",)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ArtifactResolutionError(ValueError):
    """The supplied root/pointer cannot resolve to one safe artifact set."""


@dataclass(frozen=True, slots=True)
class ArtifactResolution:
    """Resolved active directory and manifest identity for one local root."""

    artifact_root: Path
    manifest_path: Path
    manifest_name: str
    publication_root: Path | None = None
    current_path: Path | None = None
    current_bytes: bytes = b""
    current_target: str | None = None


def _safe_directory(path: Path, root: Path, label: str) -> Path:
    if path.is_symlink() or path.parent.is_symlink():
        raise ArtifactResolutionError(f"{label} must not use symlinked directories")
    try:
        resolved_root = root.resolve(strict=True)
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ArtifactResolutionError(f"{label} is missing or unreadable") from exc
    if not resolved.is_dir():
        raise ArtifactResolutionError(f"{label} is not a directory")
    if not resolved.is_relative_to(resolved_root):
        raise ArtifactResolutionError(f"{label} escapes publication root")
    return resolved


def _safe_file(path: Path, root: Path, label: str) -> Path:
    try:
        resolved_root = root.resolve(strict=True)
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ArtifactResolutionError(f"artifact '{label}' is missing or unreadable") from exc
    if not resolved.is_file():
        raise ArtifactResolutionError(f"artifact '{label}' is not a regular file")
    if not resolved.is_relative_to(resolved_root):
        raise ArtifactResolutionError(f"artifact '{label}' escapes publication root")
    return resolved


def _manifest_in_directory(directory: Path, publication_root: Path) -> tuple[str, Path]:
    present: list[tuple[str, Path]] = []
    for filename in MANIFEST_FILENAMES:
        candidate = directory / filename
        if candidate.exists() or candidate.is_symlink():
            present.append((filename, _safe_file(candidate, publication_root, filename)))
    if not present:
        raise ArtifactResolutionError(
            "artifact 'build_manifest.json' is missing (no build_manifest.json or manifest.json)"
        )
    if len(present) > 1:
        raise ArtifactResolutionError(f"{directory} has multiple manifest files")
    return present[0]


def _validate_generation_contents(directory: Path, manifest_name: str, publication_root: Path) -> None:
    expected = set(DATA_ARTIFACT_NAMES) | {manifest_name}
    legacy_expected = set(LEGACY_DATA_ARTIFACT_NAMES) | {manifest_name}
    actual = {entry.name for entry in directory.iterdir()}
    if actual != expected and actual != legacy_expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = f"missing {missing[0]}" if missing else f"unexpected {extra[0]}"
        raise ArtifactResolutionError(f"generation directory has {detail}")
    for entry in directory.iterdir():
        if entry.is_symlink():
            raise ArtifactResolutionError(f"generation entry '{entry.name}' must not be a symlink")
    for filename in sorted(actual - {manifest_name}):
        _safe_file(directory / filename, publication_root, filename)


def resolve_artifact_root(artifact_root: Path) -> ArtifactResolution:
    """Resolve either a direct artifact directory or a CURRENT publication.

    ``CURRENT`` is a regular UTF-8 file containing one relative directory
    path. Path traversal, absolute targets, missing targets, extra generation
    files, and symlink escapes are rejected before any Parquet is read.

    A legacy direct root may contain unrelated entries for compatibility.
    They are never selected: direct reads remain restricted to the fixed data
    artifact names and one recognized manifest filename.
    """

    supplied_root = Path(artifact_root)
    try:
        root = supplied_root.resolve(strict=True)
    except OSError as exc:
        raise ArtifactResolutionError("artifact root is missing or unreadable") from exc
    if not root.is_dir():
        raise ArtifactResolutionError("artifact root is not a directory")

    current_path = root / "CURRENT"
    if current_path.exists() or current_path.is_symlink():
        if current_path.is_symlink() or not current_path.is_file():
            raise ArtifactResolutionError("CURRENT must be a regular file")
        try:
            current_bytes = current_path.read_bytes()
            target_text = current_bytes.decode("utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise ArtifactResolutionError("CURRENT is not valid UTF-8") from exc
        if not target_text or "\x00" in target_text or "\n" in target_text or "\r" in target_text:
            raise ArtifactResolutionError("CURRENT must contain one relative target")
        raw_parts = target_text.split("/")
        if (
            "\\" in target_text
            or len(raw_parts) != 2
            or raw_parts[0] != "generations"
            or any(part in {"", ".", ".."} for part in raw_parts)
            or _SAFE_GENERATION_ID.fullmatch(raw_parts[1]) is None
        ):
            raise ArtifactResolutionError("CURRENT target must be a safe relative path")
        target = Path(target_text)
        if target.is_absolute() or ".." in target.parts or "." in target.parts:
            raise ArtifactResolutionError("CURRENT target must be a safe relative path")
        generation = _safe_directory(root / target, root, "CURRENT target")
        manifest_name, manifest_path = _manifest_in_directory(generation, root)
        _validate_generation_contents(generation, manifest_name, root)
        return ArtifactResolution(
            artifact_root=generation,
            manifest_path=manifest_path,
            manifest_name=manifest_name,
            publication_root=root,
            current_path=current_path,
            current_bytes=current_bytes,
            current_target=target_text,
        )

    manifest_name, manifest_path = _manifest_in_directory(root, root)
    for filename in DATA_ARTIFACT_NAMES:
        path = root / filename
        if path.exists() or path.is_symlink():
            _safe_file(path, root, filename)
    return ArtifactResolution(
        artifact_root=root,
        manifest_path=manifest_path,
        manifest_name=manifest_name,
    )


def artifact_fingerprint(
    artifact_root: Path,
) -> tuple[tuple[str, int, int, str], ...]:
    """Return a deterministic cache key for the fixed bundle paths.

    Missing paths are represented by ``(-1, -1, "")`` so callers can compute
    a key before handing the root to the uncached repository, which remains the
    authority for the concise startup error.
    """

    try:
        resolution = resolve_artifact_root(Path(artifact_root))
    except ArtifactResolutionError:
        # Preserve a useful invalidation key for an incomplete root; the
        # repository remains responsible for the fail-closed startup error.
        root = Path(artifact_root)
        values: list[tuple[str, int, int, str]] = []

        def append_path(key: str, path: Path) -> None:
            if not (path.exists() or path.is_symlink()):
                return
            try:
                stat = path.stat()
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(root.resolve(strict=True)):
                    values.append((key, -1, stat.st_mtime_ns, ""))
                    return
                if not path.is_file():
                    values.append((key, -1, stat.st_mtime_ns, ""))
                    return
                values.append((key, stat.st_size, stat.st_mtime_ns, _sha256(path)))
            except OSError:
                values.append((key, -1, -1, ""))

        def append_expected(directory: Path, prefix: str = "") -> None:
            for name in DATA_ARTIFACT_NAMES:
                append_path(f"{prefix}{name}", directory / name)
            build_manifest = directory / "build_manifest.json"
            short_manifest = directory / "manifest.json"
            if build_manifest.exists() or build_manifest.is_symlink():
                append_path(f"{prefix}build_manifest.json", build_manifest)
            elif short_manifest.exists() or short_manifest.is_symlink():
                append_path(f"{prefix}manifest.json", short_manifest)

        current = root / "CURRENT"
        if current.exists() or current.is_symlink():
            append_path("CURRENT", current)
            try:
                current_bytes = current.read_bytes()
                target_text = current_bytes.decode("utf-8").strip()
                values.append(
                    (
                        "CURRENT_TARGET",
                        len(target_text),
                        0,
                        hashlib.sha256(target_text.encode("utf-8")).hexdigest(),
                    )
                )
                parts = target_text.split("/")
                if (
                    len(parts) == 2
                    and parts[0] == "generations"
                    and _SAFE_GENERATION_ID.fullmatch(parts[1]) is not None
                ):
                    generation = root / target_text
                    append_expected(generation, f"{target_text}/")
            except (OSError, UnicodeDecodeError):
                pass
        append_expected(root)
        return tuple(values)

    values = []
    if resolution.current_path is not None:
        current_stat = resolution.current_path.stat()
        current_hash = hashlib.sha256(resolution.current_bytes).hexdigest()
        values.append(("CURRENT", current_stat.st_size, current_stat.st_mtime_ns, current_hash))
        target_hash = hashlib.sha256((resolution.current_target or "").encode("utf-8")).hexdigest()
        values.append(("CURRENT_TARGET", len(resolution.current_target or ""), 0, target_hash))

    manifest_name = resolution.manifest_name
    for name in ARTIFACT_NAMES:
        actual_name = manifest_name if name == "build_manifest.json" else name
        path = resolution.artifact_root / actual_name
        key = name if resolution.current_path is None else f"{resolution.current_target}/{name}"
        try:
            stat = path.stat()
        except OSError:
            values.append((key, -1, -1, ""))
            continue
        if not path.is_file():
            values.append((key, -1, -1, ""))
            continue
        values.append((key, stat.st_size, stat.st_mtime_ns, _sha256(path)))
    return tuple(values)


__all__ = [
    "ARTIFACT_COLUMNS",
    "ARTIFACT_NAMES",
    "ArtifactResolution",
    "ArtifactResolutionError",
    "DATA_ARTIFACT_NAMES",
    "LEGACY_DATA_ARTIFACT_NAMES",
    "EVENT_OPTIONAL_COLUMNS",
    "MANIFEST_FILENAMES",
    "NETWORK_POLICY",
    "OPTIONAL_ARTIFACT_NAMES",
    "REQUIRED_ARTIFACT_NAMES",
    "SCHEMA_VERSION",
    "artifact_fingerprint",
    "resolve_artifact_root",
]
