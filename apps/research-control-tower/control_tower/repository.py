"""Read-only, manifest-bound Control Tower artifact repository."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from .config import (
    ARTIFACT_COLUMNS,
    ARTIFACT_NAMES,
    ArtifactResolutionError,
    EVENT_OPTIONAL_COLUMNS,
    OPTIONAL_ARTIFACT_NAMES,
    REQUIRED_ARTIFACT_NAMES,
    SCHEMA_VERSION,
    SOURCE_HEALTH_EXECUTION_COLUMNS,
    _sha256,
    resolve_artifact_root,
)
from .models import ControlTowerSnapshot


class ControlTowerStartupError(RuntimeError):
    """Required local artifact or manifest failure at application startup."""


_EVENT_ENTITY_TARGET_TYPES = {"entity", "listing", "index"}
_ALL_TARGET_TYPES = _EVENT_ENTITY_TARGET_TYPES | {"basket"}
_MISSING = object()


def _empty_frame(name: str) -> pd.DataFrame:
    columns = (
        (*ARTIFACT_COLUMNS[name], *SOURCE_HEALTH_EXECUTION_COLUMNS)
        if name == "source_health.parquet"
        else ARTIFACT_COLUMNS[name]
    )
    numeric = {
        "observation_version", "fiscal_year", "analyst_count",
        "provider_contributor_count", "lookback_days", "current_analyst_count",
        "prior_analyst_count", "analyst_count_change", "row_count", "version",
    }
    floats = {
        "confidence", "value", "low_value", "high_value", "current_value",
        "current_dispersion", "prior_value", "revision_value", "revision_pct",
        "dispersion", "last_price", "bid", "ask", "day_change_pct", "volume",
        "reported_value", "normalized_value",
    }
    booleans = {
        "collection_eligible", "primary_listing", "automated", "is_provisional",
        "required", "is_restatement", "query_attempted",
    }
    dates = {
        "active_from", "active_to", "mapping_verified_at", "review_by",
        "observation_date", "estimate_period_end", "scheduled_date",
        "reporting_period_start", "reporting_period_end", "period_start",
        "period_end", "event_date",
    }
    timestamps = {
        "starts_at", "ends_at", "source_published_at", "first_observed_at",
        "last_verified_at", "release_at", "retrieved_at_utc", "snapshot_at",
        "provider_asof", "prior_provider_asof", "current_snapshot_at", "cutoff_at",
        "prior_snapshot_at", "published_at", "first_observed_at",
        "first_observation_at", "latest_observation_at", "source_latest_at",
        "quote_timestamp", "accepted_at", "filing_at", "completed_at",
    }
    data: dict[str, pd.Series] = {}
    for column in columns:
        if column in booleans:
            dtype = "boolean"
        elif column in numeric:
            dtype = "Int64"
        elif column in floats:
            dtype = "Float64"
        elif column in dates:
            dtype = "datetime64[ns]"
        elif column in timestamps:
            dtype = "datetime64[ns, UTC]"
        else:
            dtype = "string"
        data[column] = pd.Series(dtype=dtype)
    return pd.DataFrame(data)


def _manifest_error(detail: str) -> ControlTowerStartupError:
    return ControlTowerStartupError(f"Control Tower startup failed: build_manifest.json is invalid: {detail}")


def _artifact_error(name: str, detail: str) -> ControlTowerStartupError:
    return ControlTowerStartupError(
        f"Control Tower startup failed: required artifact '{name}' {detail}"
    )


def _timestamp(value: object, label: str, *, allow_none: bool = False) -> pd.Timestamp | None:
    if value is None or value is pd.NaT or (isinstance(value, float) and pd.isna(value)):
        if allow_none:
            return None
        raise _manifest_error(f"missing {label}")
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _manifest_error(f"invalid {label}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _manifest_error(f"{label} must be timezone-aware")
    return parsed.tz_convert("UTC")


def _is_compatible(field: pa.Field, expected: str) -> bool:
    data_type = field.type
    if expected in {"string", "list_or_string"}:
        return pa.types.is_string(data_type) or pa.types.is_large_string(data_type) or (
            expected == "list_or_string" and pa.types.is_list(data_type)
        )
    if expected == "boolean":
        return pa.types.is_boolean(data_type)
    if expected == "integer":
        return pa.types.is_integer(data_type)
    if expected == "float":
        return pa.types.is_floating(data_type) or pa.types.is_integer(data_type)
    if expected == "date":
        return pa.types.is_date(data_type)
    if expected == "timestamp":
        return pa.types.is_timestamp(data_type)
    return True


def _expected_types(name: str) -> dict[str, str]:
    result = {column: "string" for column in ARTIFACT_COLUMNS[name]}
    result.update({
        "observation_version": "integer", "confidence": "float",
        "starts_at": "timestamp", "ends_at": "timestamp",
        "source_published_at": "timestamp", "first_observed_at": "timestamp",
        "last_verified_at": "timestamp", "review_by": "date",
    })
    if name in {"entities.parquet", "listings.parquet", "baskets.parquet", "basket_memberships.parquet", "indices.parquet"}:
        result.update({"active_from": "date", "active_to": "date"})
    if name == "listings.parquet":
        result.update({"mapping_verified_at": "date", "collection_eligible": "boolean", "primary_listing": "boolean"})
    if name in {"event_entity_links.parquet", "event_basket_links.parquet"}:
        result.update({"automated": "boolean", "active_from": "date", "active_to": "date"})
    if name == "event_watch_questions.parquet":
        # Task 2 reads the registry as strings and Task 4's explicit Arrow
        # schema preserves that contract for priority.
        result.update({"priority": "string"})
    if name == "macro_observations.parquet":
        result.update({
            "observation_date": "date", "release_at": "timestamp",
            "first_observed_at": "timestamp", "source_published_at": "timestamp",
            "retrieved_at_utc": "timestamp", "is_provisional": "boolean",
        })
    if name == "consensus_snapshots.parquet":
        result.update({
            "fiscal_year": "integer", "estimate_period_end": "date",
            "snapshot_at": "timestamp", "value": "float", "low_value": "float",
            "high_value": "float", "analyst_count": "integer",
            "provider_contributor_count": "integer", "provider_asof": "timestamp",
            "retrieved_at_utc": "timestamp", "source_run_id": "string",
        })
    if name == "consensus_revisions.parquet":
        result.update({
            "fiscal_year": "integer", "estimate_period_end": "date",
            "current_snapshot_at": "timestamp", "current_value": "float",
            "current_analyst_count": "integer", "current_dispersion": "float",
            "lookback_days": "integer", "cutoff_at": "timestamp",
            "prior_snapshot_at": "timestamp", "prior_value": "float",
            "prior_provider_asof": "timestamp", "provider_asof": "timestamp",
            "retrieved_at_utc": "timestamp",
            "prior_analyst_count": "integer", "revision_value": "float",
            "revision_pct": "float", "analyst_count_change": "integer",
            "dispersion": "float",
        })
    if name == "news_filings.parquet":
        result.update({
            "published_at": "timestamp", "first_observed_at": "timestamp",
            "related_entity_ids": "list_or_string",
            "related_listing_ids": "list_or_string",
            "related_basket_ids": "list_or_string",
        })
    if name == "official_filings.parquet":
        result.update({
            "published_at": "timestamp", "accepted_at": "timestamp",
            "scheduled_date": "date", "retrieved_at_utc": "timestamp",
            "reporting_period_start": "date", "reporting_period_end": "date",
        })
    if name == "earnings_calendar.parquet":
        result.update({
            "period_start": "date", "period_end": "date", "event_date": "date",
            "published_at": "timestamp", "retrieved_at_utc": "timestamp",
        })
    if name == "earnings_actuals.parquet":
        result.update({
            "version": "integer", "period_start": "date", "period_end": "date",
            "reported_value": "float", "normalized_value": "float",
            "filing_at": "timestamp", "published_at": "timestamp",
            "retrieved_at_utc": "timestamp", "is_restatement": "boolean",
        })
    if name == "price_bars.parquet":
        result.update({
            "bar_date": "date",
            "retrieved_at_utc": "timestamp",
            "open": "float", "high": "float", "low": "float",
            "close": "float", "adj_close": "float", "volume": "float",
        })
    if name == "quote_snapshots.parquet":
        result.update({
            "quote_timestamp": "timestamp",
            "retrieved_at_utc": "timestamp",
            "last_price": "float",
            "bid": "float",
            "ask": "float",
            "day_change_pct": "float",
            "volume": "float",
        })
    if name == "source_health.parquet":
        result.update({
            "required": "boolean", "row_count": "integer",
            "first_observation_at": "timestamp", "latest_observation_at": "timestamp",
            "source_latest_at": "timestamp", "retrieved_at_utc": "timestamp",
            "query_attempted": "boolean", "execution_status": "string",
            "completed_at": "timestamp",
        })
    return result


def _validate_parquet_schema(name: str, table: pa.Table) -> None:
    expected = list(ARTIFACT_COLUMNS[name])
    actual = list(table.schema.names)
    if name == "events.parquet":
        without_optional = [column for column in actual if column != "importance"]
        if without_optional != expected or actual.count("importance") > 1:
            raise ValueError(f"expected columns {expected!r}, got {actual!r}")
        expected = actual
    elif name == "source_health.parquet" and tuple(actual) not in {
        tuple(expected),
        tuple([*expected, *SOURCE_HEALTH_EXECUTION_COLUMNS]),
    }:
        raise ValueError(
            f"expected columns {expected!r} with optional trailing execution "
            f"columns {list(SOURCE_HEALTH_EXECUTION_COLUMNS)!r}, got {actual!r}"
        )
    elif name == "macro_observations.parquet":
        without_vintage = [column for column in actual if column not in ("realtime_start", "realtime_end")]
        expected_base = [column for column in expected if column not in ("realtime_start", "realtime_end")]
        if without_vintage != expected_base:
            raise ValueError(f"expected columns {expected!r}, got {actual!r}")
    elif name != "source_health.parquet" and actual != expected:
        raise ValueError(f"expected columns {expected!r}, got {actual!r}")
    types = _expected_types(name)
    if "importance" in actual:
        types["importance"] = "string"
    if "realtime_start" in actual:
        types["realtime_start"] = "string"
    if "realtime_end" in actual:
        types["realtime_end"] = "string"
    for field in table.schema:
        if not _is_compatible(field, types[field.name]):
            raise ValueError(f"column {field.name!r} has incompatible dtype {field.type}")


def _read_frame(name: str, path: Path) -> pd.DataFrame:
    table = pq.read_table(path)
    _validate_parquet_schema(name, table)
    frame = table.to_pandas()
    expected = list(ARTIFACT_COLUMNS[name])
    if name == "events.parquet" and "importance" in frame.columns:
        expected = list(frame.columns)
    elif name == "source_health.parquet" and set(
        SOURCE_HEALTH_EXECUTION_COLUMNS
    ) <= set(frame.columns):
        expected = [*expected, *SOURCE_HEALTH_EXECUTION_COLUMNS]
    elif name == "macro_observations.parquet":
        expected = [column for column in expected if column in frame.columns]
    return frame.loc[:, expected].copy()


def _record(manifest: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise _manifest_error("missing artifacts")
    record = artifacts.get(name)
    if not isinstance(record, Mapping):
        raise _manifest_error(f"missing artifact record for {name}")
    required_fields = {
        "name", "relative_path", "sha256", "row_count", "byte_size",
        "schema_version", "source_ids", "status",
    }
    if not required_fields <= set(record):
        missing = ", ".join(sorted(required_fields - set(record)))
        raise _manifest_error(f"artifact '{name}' record missing {missing}")
    if record.get("name") != name or record.get("relative_path") != name:
        raise _manifest_error(f"artifact '{name}' has unsafe relative_path")
    relative = Path(str(record.get("relative_path")))
    if relative.is_absolute() or relative.parts != (name,):
        raise _manifest_error(f"artifact '{name}' has unsafe relative_path")
    if record.get("schema_version") != SCHEMA_VERSION and name not in OPTIONAL_ARTIFACT_NAMES:
        raise _manifest_error(f"artifact '{name}' has unsupported schema_version")
    if record.get("status") not in {"available", "degraded", "unavailable"}:
        raise _manifest_error(f"artifact '{name}' has invalid status")
    if not isinstance(record.get("source_ids"), list):
        raise _manifest_error(f"artifact '{name}' has invalid source_ids")
    for field in ("row_count", "byte_size"):
        value = record.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise _manifest_error(f"artifact '{name}' has invalid {field}")
    if name != "build_manifest.json" and record.get("status") == "available" and not record.get("sha256"):
        raise _manifest_error(f"artifact '{name}' is available without sha256")
    if name == "build_manifest.json" and record.get("sha256") not in (None, ""):
        raise _manifest_error("build_manifest.json must not be self-hashed")
    return record


def _validate_manifest(root: Path, manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise _manifest_error("top-level JSON value must be an object")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise _manifest_error("unsupported manifest schema")
    for key in (
        "build_id", "status", "built_at_utc", "as_of_utc", "network_policy",
        "input_fingerprints", "artifacts", "degraded_inputs", "validation_errors",
        "source_health_summary",
    ):
        if key not in manifest or manifest[key] in (None, ""):
            raise _manifest_error(f"missing {key}")
    if manifest.get("status") not in {"success", "degraded"}:
        raise _manifest_error("invalid status")
    if manifest.get("network_policy") != "forbidden":
        raise _manifest_error("network_policy must be 'forbidden'")
    if not isinstance(manifest.get("input_fingerprints"), dict):
        raise _manifest_error("input_fingerprints must be an object")
    if not isinstance(manifest.get("source_health_summary"), dict):
        raise _manifest_error("source_health_summary must be an object")
    if not isinstance(manifest.get("artifacts"), dict):
        raise _manifest_error("missing artifacts")
    artifact_names = set(manifest["artifacts"])
    missing_optional = set(ARTIFACT_NAMES) - artifact_names
    if (
        missing_optional
        and missing_optional <= set(OPTIONAL_ARTIFACT_NAMES)
        and all(not (root / name).exists() for name in missing_optional)
    ):
        normalized = deepcopy(manifest)
        normalized_artifacts = normalized["artifacts"]
        for name in sorted(missing_optional):
            normalized_artifacts[name] = {
                "name": name,
                "relative_path": name,
                "sha256": None,
                "row_count": 0,
                "byte_size": 0,
                "schema_version": SCHEMA_VERSION,
                "source_ids": [],
                "status": "unavailable",
            }
        degraded_inputs = list(normalized.get("degraded_inputs", []))
        degraded_inputs.extend(Path(name).stem for name in missing_optional)
        normalized["degraded_inputs"] = sorted(set(degraded_inputs))
        normalized["status"] = "degraded"
        manifest = normalized
        artifact_names = set(manifest["artifacts"])
    if artifact_names != set(ARTIFACT_NAMES):
        unexpected = sorted(set(manifest["artifacts"]) - set(ARTIFACT_NAMES))
        missing = sorted(set(ARTIFACT_NAMES) - set(manifest["artifacts"]))
        detail = f"unexpected artifact {unexpected[0]}" if unexpected else f"missing artifact record for {missing[0]}"
        raise _manifest_error(detail)
    for name in ARTIFACT_NAMES:
        _record(manifest, name)
    degraded_inputs = manifest.get("degraded_inputs", [])
    validation_errors = manifest.get("validation_errors", [])
    if not isinstance(degraded_inputs, list) or not isinstance(validation_errors, list):
        raise _manifest_error("degraded_inputs and validation_errors must be lists")
    # A required artifact must be usable, which is not the same as every
    # provider behind it being connected.  "degraded" means the artifact was
    # written and passed schema validation while some of its sources are
    # impaired -- stale, partial, or unconfigured -- and the per-source reasons
    # are already carried in source_health and validation_errors, which the
    # coverage matrix renders.  Demanding "available" here conflated the two:
    # wiring real FRED observations into macro_observations moved it from
    # "available" with four hand-entered rows to "degraded" with 19,761 real
    # ones, and the app refused to start on the richer artifact.  Only
    # "unavailable" -- no usable rows -- still fails closed.
    bad_required_records = [
        name
        for name in REQUIRED_ARTIFACT_NAMES
        if manifest["artifacts"][name].get("status") not in {"available", "degraded"}
    ]
    if bad_required_records:
        raise _manifest_error(
            f"required artifact '{bad_required_records[0]}' has unavailable status"
        )
    if manifest["status"] == "success" and (
        degraded_inputs or validation_errors or bad_required_records
    ):
        raise _manifest_error("inconsistent manifest status")
    built_at = _timestamp(manifest["built_at_utc"], "built_at_utc")
    as_of = _timestamp(manifest["as_of_utc"], "as_of_utc")
    if "previous_build_at" in manifest and manifest["previous_build_at"] not in (None, ""):
        previous = _timestamp(manifest["previous_build_at"], "previous_build_at")
        assert built_at is not None and as_of is not None and previous is not None
        if previous >= built_at or previous >= as_of:
            raise _manifest_error(
                "previous_build_at must be strictly earlier than "
                "built_at_utc and as_of_utc"
            )
    return deepcopy(manifest)


def _canonicalize_manifest_filename(manifest: Any, manifest_name: str) -> Any:
    """Normalize the direct ``manifest.json`` filename to the fixed contract."""

    if manifest_name != "manifest.json" or not isinstance(manifest, dict):
        return manifest
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict) or "manifest.json" not in artifacts:
        return manifest
    if "build_manifest.json" in artifacts:
        raise _manifest_error("manifest.json and build_manifest.json records are both present")
    normalized = deepcopy(manifest)
    record = normalized["artifacts"].pop("manifest.json")
    record["name"] = "build_manifest.json"
    record["relative_path"] = "build_manifest.json"
    normalized["artifacts"]["build_manifest.json"] = record
    return normalized


def _validate_record_integrity(name: str, path: Path, record: Mapping[str, Any], frame: pd.DataFrame) -> None:
    if record.get("byte_size") is not None and int(record["byte_size"]) != path.stat().st_size:
        raise ValueError("byte_size mismatch")
    if record.get("row_count") is not None and int(record["row_count"]) != len(frame):
        raise ValueError("row_count mismatch")
    if record.get("sha256"):
        if str(record["sha256"]) != _sha256(path):
            raise ValueError("hash mismatch")


def _link_targets(frame: pd.DataFrame, allowed: set[str], name: str) -> None:
    if frame.empty:
        return
    if not frame["target_type"].astype("string").isin(allowed).all():
        raise _artifact_error(name, "has invalid target_type")


def _as_date(value: object) -> pd.Timestamp | None:
    if value is None or value is pd.NaT:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.tz_localize(None)
    return parsed.normalize()


def _as_utc(value: object) -> pd.Timestamp | None:
    if value is None or value is pd.NaT:
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if pd.isna(parsed) or parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.tz_convert("UTC")


def _active_at(
    active_from: object,
    active_to: object,
    event_start: pd.Timestamp | None,
    event_end: pd.Timestamp | None = None,
) -> bool:
    if event_start is None:
        return True
    event_date = event_start.tz_localize(None).normalize()
    event_end_date = (
        event_end.tz_localize(None).normalize()
        if event_end is not None
        else event_date
    )
    start = _as_date(active_from)
    end = _as_date(active_to)
    return (end is None or event_date < end) and (start is None or event_end_date >= start)


def _enrich_events(
    events: pd.DataFrame,
    entity_links: pd.DataFrame,
    basket_links: pd.DataFrame,
    entities: pd.DataFrame,
    listings: pd.DataFrame,
    memberships: pd.DataFrame,
) -> pd.DataFrame:
    result = events.copy(deep=True)
    entity_by_id = entities.set_index("entity_id", drop=False).to_dict("index") if not entities.empty else {}
    listing_by_id = listings.set_index("listing_id", drop=False).to_dict("index") if not listings.empty else {}
    membership_rows = memberships.to_dict("records")
    baskets_by_event = {
        event_id: group.to_dict("records")
        for event_id, group in basket_links.groupby("event_id", sort=False)
    }
    entity_links_by_event = {
        event_id: group.to_dict("records")
        for event_id, group in entity_links.groupby("event_id", sort=False)
    }
    enriched: list[dict[str, Any]] = []
    for _, event in result.iterrows():
        event_id = event["event_id"]
        start = _as_utc(event.get("starts_at"))
        end = _as_utc(event.get("ends_at")) or start
        direct_entity_ids: set[str] = set()
        listing_ids: set[str] = set()
        index_ids: set[str] = set()
        basket_ids: set[str] = set()
        for link in entity_links_by_event.get(event_id, []):
            target_type = str(link["target_type"])
            target_id = str(link["target_id"])
            if target_type == "entity" and target_id in entity_by_id:
                direct_entity_ids.add(target_id)
            elif target_type == "listing" and target_id in listing_by_id:
                listing_ids.add(target_id)
                direct_entity_ids.add(str(listing_by_id[target_id]["entity_id"]))
            elif target_type == "index":
                index_ids.add(target_id)
        for link in baskets_by_event.get(event_id, []):
            basket_ids.add(str(link["target_id"]))

        basket_member_entity_ids: set[str] = set()
        for membership in membership_rows:
            if str(membership["basket_id"]) in basket_ids and _active_at(membership.get("active_from"), membership.get("active_to"), start, end):
                basket_member_entity_ids.add(str(membership["entity_id"]))

        derived_entity_ids = direct_entity_ids | basket_member_entity_ids

        countries: set[str] = set()
        tiers: set[str] = set()
        for membership in membership_rows:
            if str(membership["entity_id"]) in derived_entity_ids and _active_at(membership.get("active_from"), membership.get("active_to"), start, end):
                tier = str(membership.get("membership_tier") or "").strip()
                if tier:
                    tiers.add(tier.lower())
        for entity_id in derived_entity_ids:
            row = entity_by_id.get(entity_id)
            if row:
                country = str(row.get("country") or "").strip()
                if country:
                    countries.add(country.upper())

        row = event.to_dict()
        row.update({
            "related_entity_ids": tuple(sorted(direct_entity_ids)),
            "related_listing_ids": tuple(sorted(listing_ids)),
            "related_basket_ids": tuple(sorted(basket_ids)),
            "related_index_ids": tuple(sorted(index_ids)),
            "related_countries": tuple(sorted(countries)),
            "membership_tiers": tuple(sorted(tiers)),
        })
        if "importance" not in row:
            row["importance"] = pd.NA
        enriched.append(row)
    return pd.DataFrame(enriched, columns=[*result.columns, *[column for column in (
        "related_entity_ids", "related_listing_ids", "related_basket_ids",
        "related_index_ids", "related_countries", "membership_tiers", "importance",
    ) if column not in result.columns]])


def _health_reason_row(name: str, reason: str) -> dict[str, Any]:
    return {
        "source_id": f"artifact:{Path(name).stem}",
        "input_path": name,
        "source_kind": "artifact",
        "status": "unavailable" if reason in {"missing", "corrupt", "schema_mismatch"} else "degraded",
        "required": False,
        "row_count": 0,
        "query_attempted": False,
        "execution_status": "",
        "completed_at": pd.NaT,
        "first_observation_at": pd.NaT,
        "latest_observation_at": pd.NaT,
        "source_latest_at": pd.NaT,
        "retrieved_at_utc": pd.NaT,
        "cadence": "",
        "source_url": "",
        "pit_class": "",
        "source_license_class": "",
        "entitlement_status": "",
        "entitlement_evidence": "",
        "entitlement_ref": "",
        "input_sha256": "",
        "schema_version": SCHEMA_VERSION,
        "missing_geographies": "",
        "detail": f"artifact={name}; reason={reason}",
    }


class ControlTowerRepository:
    """Load one explicit local Control Tower artifact root.

    The class has no write, refresh, network, discovery, or fallback methods.
    """

    def __init__(self, artifact_root: Path) -> None:
        self.artifact_root = Path(artifact_root)

    def load_snapshot(self) -> ControlTowerSnapshot:
        try:
            resolution = resolve_artifact_root(self.artifact_root)
        except ArtifactResolutionError as exc:
            raise ControlTowerStartupError(
                f"Control Tower startup failed: artifact root is invalid: {exc}"
            ) from exc
        root = resolution.artifact_root
        manifest_path = resolution.manifest_path
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise _manifest_error("invalid JSON") from exc
        manifest = _canonicalize_manifest_filename(manifest, resolution.manifest_name)
        manifest = _validate_manifest(root, manifest)
        if resolution.current_target is not None:
            expected_generation_id = Path(resolution.current_target).name
            if manifest.get("generation_id") != expected_generation_id:
                raise _manifest_error(
                    "generation_id does not match CURRENT target"
                )
            if manifest.get("current_pointer") != resolution.current_target:
                raise _manifest_error(
                    "current_pointer does not match CURRENT target"
                )
        manifest_record = manifest["artifacts"]["build_manifest.json"]
        try:
            if int(manifest_record["byte_size"]) != manifest_path.stat().st_size:
                raise _manifest_error("build_manifest.json byte_size mismatch")
            if int(manifest_record["row_count"]) != 1:
                raise _manifest_error("build_manifest.json row count mismatch")
        except (OSError, TypeError, ValueError) as exc:
            if isinstance(exc, ControlTowerStartupError):
                raise
            raise _manifest_error("build_manifest.json has invalid byte_size") from exc

        loaded: dict[str, pd.DataFrame] = {}
        missing_optional: set[str] = set()
        degraded_reasons: dict[str, str] = {}
        synthetic_health: list[dict[str, Any]] = []

        for name in ARTIFACT_NAMES:
            if name == "build_manifest.json":
                continue
            required = name in REQUIRED_ARTIFACT_NAMES
            path = root / name
            record = manifest["artifacts"][name]
            if (
                not required
                and record.get("schema_version") != SCHEMA_VERSION
            ):
                stem = Path(name).stem
                missing_optional.add(stem)
                degraded_reasons[stem] = "schema_mismatch"
                loaded[name] = _empty_frame(name)
                synthetic_health.append(_health_reason_row(name, "schema_mismatch"))
                continue
            if not path.is_file():
                if required:
                    raise _artifact_error(name, "is missing")
                stem = Path(name).stem
                missing_optional.add(stem)
                reason = "missing" if record.get("status") in {"degraded", "unavailable"} else "manifest_mismatch"
                degraded_reasons[stem] = reason
                loaded[name] = _empty_frame(name)
                synthetic_health.append(_health_reason_row(name, reason))
                continue
            if not required and record.get("status") == "unavailable":
                stem = Path(name).stem
                missing_optional.add(stem)
                degraded_reasons[stem] = "unavailable"
                loaded[name] = _empty_frame(name)
                synthetic_health.append(_health_reason_row(name, "unavailable"))
                continue
            if not required and record.get("status") == "degraded":
                # A degraded optional artifact holds real rows that passed
                # schema validation; only some of its sources are impaired.
                # Emptying it here discarded them and relabelled the result
                # "unavailable", which is how 2,045 SEC filings were reported
                # as "News & Filings: Unavailable" merely because the AI RSS
                # feed beside them was unconfigured. The degradation is still
                # recorded, so the coverage matrix reports partial rather than
                # available -- it just no longer throws the evidence away.
                stem = Path(name).stem
                missing_optional.add(stem)
                degraded_reasons[stem] = "degraded"
                synthetic_health.append(_health_reason_row(name, "degraded"))
                # fall through to the normal integrity-checked load
            try:
                expected_hash = record.get("sha256")
                if expected_hash and str(expected_hash) != _sha256(path):
                    raise ValueError("hash mismatch")
                frame = _read_frame(name, path)
                _validate_record_integrity(name, path, {**record, "sha256": None}, frame)
            except Exception as exc:
                detail = str(exc)
                if "hash mismatch" in detail or "byte_size mismatch" in detail or "row_count mismatch" in detail:
                    reason = "manifest_mismatch"
                elif "expected columns" in detail or "incompatible dtype" in detail:
                    reason = "schema_mismatch"
                else:
                    reason = "corrupt"
                if required:
                    if reason == "manifest_mismatch" and "hash mismatch" in detail:
                        raise _artifact_error(name, "hash mismatch") from exc
                    if reason == "manifest_mismatch" and "row_count mismatch" in detail:
                        raise _artifact_error(name, "row count mismatch") from exc
                    if reason == "schema_mismatch":
                        raise _artifact_error(name, f"has invalid schema ({detail})") from exc
                    raise _artifact_error(name, "is corrupt") from exc
                stem = Path(name).stem
                missing_optional.add(stem)
                degraded_reasons[stem] = reason
                loaded[name] = _empty_frame(name)
                synthetic_health.append(_health_reason_row(name, reason))
                continue
            loaded[name] = frame

        events = loaded["events.parquet"]
        importance_present = "importance" in events.columns
        if importance_present:
            values = events["importance"].astype("string").str.strip().str.lower()
            invalid = values.notna() & values.ne("") & ~values.isin({"high", "medium", "low"})
            if invalid.any():
                raise _artifact_error("events.parquet", "has invalid importance values")
            events["importance"] = values.mask(values.eq(""), pd.NA)

        entity_links = loaded["event_entity_links.parquet"]
        basket_links = loaded["event_basket_links.parquet"]
        _link_targets(entity_links, _EVENT_ENTITY_TARGET_TYPES, "event_entity_links.parquet")
        _link_targets(basket_links, {"basket"}, "event_basket_links.parquet")
        known_events = set(events["event_id"].astype("string"))
        known_entities = set(loaded["entities.parquet"]["entity_id"].astype("string"))
        known_listings = set(loaded["listings.parquet"]["listing_id"].astype("string"))
        known_baskets = set(loaded["baskets.parquet"]["basket_id"].astype("string"))
        known_indices = set(loaded["indices.parquet"]["index_id"].astype("string"))
        target_sets = {"entity": known_entities, "listing": known_listings, "basket": known_baskets, "index": known_indices}
        for name, frame in (("event_entity_links.parquet", entity_links), ("event_basket_links.parquet", basket_links)):
            for row_index, row in frame.iterrows():
                if row["event_id"] not in known_events or row["target_id"] not in target_sets[str(row["target_type"])]:
                    raise _artifact_error(name, f"has an orphan link at row {row_index}")

        enriched = _enrich_events(
            events,
            entity_links,
            basket_links,
            loaded["entities.parquet"],
            loaded["listings.parquet"],
            loaded["basket_memberships.parquet"],
        )

        source_health = loaded["source_health.parquet"].copy(deep=True)
        if synthetic_health:
            source_health = pd.concat([source_health, pd.DataFrame(synthetic_health)], ignore_index=True)

        built_at = _timestamp(manifest["built_at_utc"], "built_at_utc")
        as_of = _timestamp(manifest["as_of_utc"], "as_of_utc")
        previous = _timestamp(manifest.get("previous_build_at"), "previous_build_at", allow_none=True)
        status = "degraded" if manifest["status"] == "degraded" or missing_optional else "success"
        return ControlTowerSnapshot(
            entities=loaded["entities.parquet"],
            listings=loaded["listings.parquet"],
            baskets=loaded["baskets.parquet"],
            basket_memberships=loaded["basket_memberships.parquet"],
            indices=loaded["indices.parquet"],
            events=enriched,
            event_entity_links=entity_links,
            event_basket_links=basket_links,
            event_watch_questions=loaded["event_watch_questions.parquet"],
            macro_observations=loaded["macro_observations.parquet"],
            consensus_snapshots=loaded["consensus_snapshots.parquet"],
            consensus_revisions=loaded["consensus_revisions.parquet"],
            quote_snapshots=loaded["quote_snapshots.parquet"],
            price_bars=loaded["price_bars.parquet"],
            news_filings=loaded["news_filings.parquet"],
            official_filings=loaded["official_filings.parquet"],
            earnings_calendar=loaded["earnings_calendar.parquet"],
            earnings_actuals=loaded["earnings_actuals.parquet"],
            source_health=source_health,
            manifest=manifest,
            status=status,
            missing_optional=tuple(sorted(missing_optional)),
            degraded_reasons=dict(sorted(degraded_reasons.items())),
            build_id=str(manifest["build_id"]),
            built_at_utc=built_at,
            as_of_utc=as_of,
            previous_build_at=previous,
        )


__all__ = ["ControlTowerRepository", "ControlTowerStartupError"]
