"""Auditable valuation and internal-estimate contracts for Control Tower T2."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import pyarrow as pa

from .atomic_io import write_parquet_atomic as _write_parquet_atomic


SUPPORTED_VALUATION_METRICS = frozenset(
    {
        "forward_pe",
        "ev_ebitda",
        "fcf_yield",
        "shareholder_cash_return_yield",
    }
)
SUPPORTED_METRIC_BASES = frozenset(
    {"GAAP_REPORTED", "NON_IFRS_MANAGEMENT", "PROVIDER_UNVERIFIED"}
)
# ``PROVIDER_UNVERIFIED`` is retained above because the same canonical label
# is useful for uncertainty context in consensus/internal-estimate inputs.  It
# is deliberately not admissible in the valuation_snapshots contract.
SUPPORTED_VALUATION_METRIC_BASES = frozenset(
    {"GAAP_REPORTED", "NON_IFRS_MANAGEMENT"}
)
SUPPORTED_OBSERVATION_TYPES = frozenset(
    {"management_guidance", "internal_estimate"}
)
SUPPORTED_PIT_CLASSES = frozenset(
    {
        "snapshot_from_live_source",
        "snapshot_from_delayed_source",
        "repository_captured",
        "true_pit",
        "dated_public_broker_report",
        "reconstructed_sparse",
        "current_vintage",
        "not_pit",
    }
)
UTC_TIMESTAMP = pa.timestamp("us", tz="UTC")

VALUATION_SNAPSHOTS_COLUMNS = [
    "valuation_id",
    "listing_id",
    "valuation_date",
    "valuation_at",
    "metric_name",
    "accounting_basis",
    "metric_basis",
    "ratio_value",
    "numerator_value",
    "numerator_currency",
    "numerator_ref",
    "numerator_source_id",
    "numerator_source_url",
    "numerator_pit_class",
    "numerator_at_utc",
    "numerator_retrieved_at_utc",
    "denominator_value",
    "denominator_currency",
    "denominator_ref",
    "denominator_source_id",
    "denominator_source_url",
    "denominator_pit_class",
    "denominator_at_utc",
    "denominator_provider_asof_utc",
    "denominator_retrieved_at_utc",
    "fx_rate_applied",
    "fx_base_currency",
    "fx_quote_currency",
    "fx_source",
    "fx_source_url",
    "fx_snapshot_at_utc",
    "fx_retrieved_at_utc",
    "source_id",
    "source_url",
    "retrieved_at_utc",
    "pit_class",
    "coverage_reason",
    "percentile_history_status",
]
VALUATION_SNAPSHOTS_SCHEMA_ID = "valuation_snapshots_v2"
VALUATION_SNAPSHOTS_ARROW_SCHEMA = pa.schema(
    [
        ("valuation_id", pa.string()),
        ("listing_id", pa.string()),
        ("valuation_date", pa.date32()),
        ("valuation_at", UTC_TIMESTAMP),
        ("metric_name", pa.string()),
        ("accounting_basis", pa.string()),
        ("metric_basis", pa.string()),
        ("ratio_value", pa.float64()),
        ("numerator_value", pa.float64()),
        ("numerator_currency", pa.string()),
        ("numerator_ref", pa.string()),
        ("numerator_source_id", pa.string()),
        ("numerator_source_url", pa.string()),
        ("numerator_pit_class", pa.string()),
        ("numerator_at_utc", UTC_TIMESTAMP),
        ("numerator_retrieved_at_utc", UTC_TIMESTAMP),
        ("denominator_value", pa.float64()),
        ("denominator_currency", pa.string()),
        ("denominator_ref", pa.string()),
        ("denominator_source_id", pa.string()),
        ("denominator_source_url", pa.string()),
        ("denominator_pit_class", pa.string()),
        ("denominator_at_utc", UTC_TIMESTAMP),
        ("denominator_provider_asof_utc", UTC_TIMESTAMP),
        ("denominator_retrieved_at_utc", UTC_TIMESTAMP),
        ("fx_rate_applied", pa.float64()),
        ("fx_base_currency", pa.string()),
        ("fx_quote_currency", pa.string()),
        ("fx_source", pa.string()),
        ("fx_source_url", pa.string()),
        ("fx_snapshot_at_utc", UTC_TIMESTAMP),
        ("fx_retrieved_at_utc", UTC_TIMESTAMP),
        ("source_id", pa.string()),
        ("source_url", pa.string()),
        ("retrieved_at_utc", UTC_TIMESTAMP),
        ("pit_class", pa.string()),
        ("coverage_reason", pa.string()),
        ("percentile_history_status", pa.string()),
    ]
)

INTERNAL_ESTIMATES_COLUMNS = [
    "estimate_id",
    "version",
    "supersedes_estimate_id",
    "entity_id",
    "listing_id",
    "observation_type",
    "author",
    "metric",
    "accounting_basis",
    "metric_basis",
    "fiscal_period",
    "fiscal_year",
    "value_low",
    "value_high",
    "value_mid",
    "currency",
    "unit",
    "effective_asof",
    "recorded_at_utc",
    "rationale_notes",
    "source_ref",
    "source_url",
    "pit_class",
    "reviewed_at_utc",
    "reviewed_by",
]
INTERNAL_ESTIMATES_SCHEMA_ID = "internal_estimates_v1"
INTERNAL_ESTIMATES_ARROW_SCHEMA = pa.schema(
    [
        ("estimate_id", pa.string()),
        ("version", pa.int64()),
        ("supersedes_estimate_id", pa.string()),
        ("entity_id", pa.string()),
        ("listing_id", pa.string()),
        ("observation_type", pa.string()),
        ("author", pa.string()),
        ("metric", pa.string()),
        ("accounting_basis", pa.string()),
        ("metric_basis", pa.string()),
        ("fiscal_period", pa.string()),
        ("fiscal_year", pa.int64()),
        ("value_low", pa.float64()),
        ("value_high", pa.float64()),
        ("value_mid", pa.float64()),
        ("currency", pa.string()),
        ("unit", pa.string()),
        ("effective_asof", pa.date32()),
        ("recorded_at_utc", UTC_TIMESTAMP),
        ("rationale_notes", pa.string()),
        ("source_ref", pa.string()),
        ("source_url", pa.string()),
        ("pit_class", pa.string()),
        ("reviewed_at_utc", UTC_TIMESTAMP),
        ("reviewed_by", pa.string()),
    ]
)


def _utc(value: Any, field: str) -> datetime:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise ValueError(f"{field} must be a timezone-aware timestamp")
    return timestamp.tz_convert("UTC").to_pydatetime()


def _finite(value: Any, field: str, *, positive: bool = False) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    if positive and result <= 0:
        raise ValueError(f"{field} must be positive")
    return result


def _blank(value: Any) -> bool:
    if value is None or value is pd.NA or value is pd.NaT:
        return True
    try:
        missing = pd.isna(value)
        # ``pd.isna`` returns an array for array-like input; only a scalar
        # result is a meaningful "this value is missing" answer.
        if not hasattr(missing, "__len__") and bool(missing):
            return True
    except (TypeError, ValueError):
        pass
    return not str(value).strip()


def empty_frame(schema: pa.Schema) -> pd.DataFrame:
    """Return a typed empty pandas frame backed by the supplied Arrow schema."""

    return pa.Table.from_pylist([], schema=schema).to_pandas()


def canonicalize_metric_basis(accounting_basis: Any) -> str:
    """Map only explicit, verified source labels to a canonical metric basis."""

    normalized = " ".join(
        str(accounting_basis or "").strip().upper().replace("-", "_").split()
    )
    if normalized in {
        "GAAP_REPORTED",
        "IFRS AS REPORTED",
        "IFRS_REPORTED",
        "US_GAAP AS REPORTED",
    }:
        return "GAAP_REPORTED"
    if normalized in {
        "NON_IFRS_MANAGEMENT",
        "NON_IFRS MANAGEMENT",
        "TENCENT NON_IFRS MANAGEMENT",
    }:
        return "NON_IFRS_MANAGEMENT"
    return "PROVIDER_UNVERIFIED"


def compute_valuation_id(
    listing_id: str,
    valuation_at_iso: str,
    metric_name: str,
    metric_basis: str,
    numerator_ref: str,
    denominator_ref: str,
    *,
    lineage_payload: Mapping[str, Any] | None = None,
) -> str:
    natural_key = (
        listing_id,
        valuation_at_iso,
        metric_name,
        metric_basis,
        numerator_ref,
        denominator_ref,
    )
    raw = json.dumps(
        {
            "natural_key": natural_key,
            "lineage": _json_canonical(lineage_payload or {}),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _json_canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_canonical(item) for item in value]
    if isinstance(value, (datetime, pd.Timestamp)):
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp) or timestamp.tzinfo is None:
            raise ValueError("lineage timestamps must be timezone-aware")
        return timestamp.tz_convert("UTC").isoformat()
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value.isoformat()
    if value is None or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        return None
    if isinstance(value, float):
        return _finite(value, "lineage numeric value")
    return value


@dataclass(frozen=True)
class ValuationInput:
    listing_id: str
    valuation_at: datetime
    metric_name: str
    accounting_basis: str
    metric_basis: str
    numerator_value: float
    numerator_currency: str
    numerator_ref: str
    numerator_source_id: str
    numerator_source_url: str
    numerator_pit_class: str
    numerator_at_utc: datetime
    numerator_retrieved_at_utc: datetime
    denominator_value: float
    denominator_currency: str
    denominator_ref: str
    denominator_source_id: str
    denominator_source_url: str
    denominator_pit_class: str
    denominator_at_utc: datetime
    denominator_provider_asof_utc: datetime
    denominator_retrieved_at_utc: datetime
    fx_rate_applied: float | None = None
    fx_base_currency: str | None = None
    fx_quote_currency: str | None = None
    fx_source: str | None = None
    fx_source_url: str | None = None
    fx_snapshot_at_utc: datetime | None = None
    fx_retrieved_at_utc: datetime | None = None
    source_id: str = "research_control_tower_valuation_v2"
    source_url: str = ""
    retrieved_at_utc: datetime | None = None
    pit_class: str = "snapshot_from_delayed_source"
    coverage_reason: str | None = None
    percentile_history_status: str = "unavailable"


def build_valuation_snapshot_row(inp: ValuationInput) -> dict[str, Any]:
    """Build one ratio only when every causal and numeric input is auditable."""

    if inp.metric_name not in SUPPORTED_VALUATION_METRICS:
        raise ValueError(f"unsupported metric_name: {inp.metric_name!r}")
    if inp.metric_basis not in SUPPORTED_VALUATION_METRIC_BASES:
        raise ValueError(
            "valuation metric basis must be GAAP_REPORTED or "
            f"NON_IFRS_MANAGEMENT; got {inp.metric_basis!r}"
        )
    canonical_basis = canonicalize_metric_basis(inp.accounting_basis)
    if canonical_basis != inp.metric_basis:
        raise ValueError(
            "valuation metric basis does not match accounting_basis: "
            f"{inp.metric_basis!r} != {canonical_basis!r}"
        )
    if inp.pit_class not in SUPPORTED_PIT_CLASSES:
        raise ValueError(f"unsupported pit_class: {inp.pit_class!r}")
    if inp.numerator_pit_class not in SUPPORTED_PIT_CLASSES:
        raise ValueError(
            f"unsupported numerator_pit_class: {inp.numerator_pit_class!r}"
        )
    if inp.denominator_pit_class not in SUPPORTED_PIT_CLASSES:
        raise ValueError(
            f"unsupported denominator_pit_class: {inp.denominator_pit_class!r}"
        )
    if inp.percentile_history_status != "unavailable":
        raise ValueError(
            "percentile_history_status must remain unavailable without "
            "historical denominator vintages"
        )

    required_text = {
        "listing_id": inp.listing_id,
        "accounting_basis": inp.accounting_basis,
        "numerator_currency": inp.numerator_currency,
        "numerator_ref": inp.numerator_ref,
        "numerator_source_id": inp.numerator_source_id,
        "numerator_source_url": inp.numerator_source_url,
        "numerator_pit_class": inp.numerator_pit_class,
        "denominator_currency": inp.denominator_currency,
        "denominator_ref": inp.denominator_ref,
        "denominator_source_id": inp.denominator_source_id,
        "denominator_source_url": inp.denominator_source_url,
        "denominator_pit_class": inp.denominator_pit_class,
        "source_id": inp.source_id,
    }
    missing = [name for name, value in required_text.items() if not str(value or "").strip()]
    if missing:
        raise ValueError(f"required lineage fields are empty: {sorted(missing)}")

    valuation_at = _utc(inp.valuation_at, "valuation_at")
    numerator_at = _utc(inp.numerator_at_utc, "numerator_at_utc")
    numerator_retrieved = _utc(
        inp.numerator_retrieved_at_utc, "numerator_retrieved_at_utc"
    )
    denominator_at = _utc(inp.denominator_at_utc, "denominator_at_utc")
    denominator_provider_asof = _utc(
        inp.denominator_provider_asof_utc, "denominator_provider_asof_utc"
    )
    denominator_retrieved = _utc(
        inp.denominator_retrieved_at_utc, "denominator_retrieved_at_utc"
    )
    retrieved_at = _utc(
        valuation_at if _blank(inp.retrieved_at_utc) else inp.retrieved_at_utc,
        "retrieved_at_utc",
    )
    if numerator_at > valuation_at or numerator_retrieved > valuation_at:
        raise ValueError("numerator vintage must not exceed valuation_at")
    if numerator_at > numerator_retrieved:
        raise ValueError("numerator observation must not exceed source retrieval")
    if (
        denominator_at > valuation_at
        or denominator_provider_asof > valuation_at
        or denominator_retrieved > valuation_at
    ):
        raise ValueError("denominator vintage must not exceed valuation_at")
    if (
        denominator_at > denominator_retrieved
        or denominator_provider_asof > denominator_retrieved
    ):
        raise ValueError(
            "denominator observation/provider-as-of must not exceed source retrieval"
        )
    if valuation_at > retrieved_at:
        raise ValueError("valuation_at must not exceed retrieved_at_utc")

    numerator = _finite(inp.numerator_value, "numerator_value", positive=True)
    denominator = _finite(inp.denominator_value, "denominator_value", positive=True)
    numerator_currency = str(inp.numerator_currency).strip().upper()
    denominator_currency = str(inp.denominator_currency).strip().upper()

    fx_rate: float | None = None
    fx_snapshot: datetime | None = None
    fx_retrieved: datetime | None = None
    if numerator_currency != denominator_currency:
        fx_rate = _finite(inp.fx_rate_applied, "fx_rate_applied", positive=True)
        fx_base = str(inp.fx_base_currency or "").strip().upper()
        fx_quote = str(inp.fx_quote_currency or "").strip().upper()
        if fx_base != denominator_currency or fx_quote != numerator_currency:
            raise ValueError(
                "FX must be denominator-to-numerator: "
                f"expected {denominator_currency}/{numerator_currency}"
            )
        if not str(inp.fx_source or "").strip() or not str(
            inp.fx_source_url or ""
        ).strip():
            raise ValueError("fx_source and fx_source_url are required")
        fx_snapshot = _utc(inp.fx_snapshot_at_utc, "fx_snapshot_at_utc")
        fx_retrieved = _utc(inp.fx_retrieved_at_utc, "fx_retrieved_at_utc")
        if fx_snapshot > valuation_at or fx_retrieved > valuation_at:
            raise ValueError("FX vintage must not exceed valuation_at")
        if fx_snapshot > fx_retrieved:
            raise ValueError("FX observation must not exceed source retrieval")
    else:
        provided = (
            inp.fx_rate_applied,
            inp.fx_base_currency,
            inp.fx_quote_currency,
            inp.fx_source,
            inp.fx_source_url,
            inp.fx_snapshot_at_utc,
            inp.fx_retrieved_at_utc,
        )
        if any(not _blank(value) for value in provided):
            raise ValueError("same-currency valuation must not carry FX fields")

    converted_denominator = denominator * (fx_rate or 1.0)
    if inp.metric_name in {"forward_pe", "ev_ebitda"}:
        ratio_value = numerator / converted_denominator
    else:
        ratio_value = converted_denominator / numerator * 100.0
    ratio_value = _finite(ratio_value, "ratio_value", positive=True)

    canonical_row = {
        "listing_id": inp.listing_id,
        "valuation_date": valuation_at.date(),
        "valuation_at": valuation_at,
        "metric_name": inp.metric_name,
        "accounting_basis": inp.accounting_basis,
        "metric_basis": inp.metric_basis,
        "ratio_value": ratio_value,
        "numerator_value": numerator,
        "numerator_currency": numerator_currency,
        "numerator_ref": inp.numerator_ref,
        "numerator_source_id": inp.numerator_source_id,
        "numerator_source_url": inp.numerator_source_url,
        "numerator_pit_class": inp.numerator_pit_class,
        "numerator_at_utc": numerator_at,
        "numerator_retrieved_at_utc": numerator_retrieved,
        "denominator_value": denominator,
        "denominator_currency": denominator_currency,
        "denominator_ref": inp.denominator_ref,
        "denominator_source_id": inp.denominator_source_id,
        "denominator_source_url": inp.denominator_source_url,
        "denominator_pit_class": inp.denominator_pit_class,
        "denominator_at_utc": denominator_at,
        "denominator_provider_asof_utc": denominator_provider_asof,
        "denominator_retrieved_at_utc": denominator_retrieved,
        "fx_rate_applied": fx_rate,
        "fx_base_currency": denominator_currency if fx_rate is not None else None,
        "fx_quote_currency": numerator_currency if fx_rate is not None else None,
        "fx_source": str(inp.fx_source) if fx_rate is not None else None,
        "fx_source_url": str(inp.fx_source_url) if fx_rate is not None else None,
        "fx_snapshot_at_utc": fx_snapshot,
        "fx_retrieved_at_utc": fx_retrieved,
        "source_id": inp.source_id,
        "source_url": None if _blank(inp.source_url) else str(inp.source_url),
        "retrieved_at_utc": retrieved_at,
        "pit_class": inp.pit_class,
        "coverage_reason": (
            None if _blank(inp.coverage_reason) else str(inp.coverage_reason)
        ),
        "percentile_history_status": "unavailable",
    }
    valuation_id = compute_valuation_id(
        inp.listing_id,
        valuation_at.isoformat(),
        inp.metric_name,
        inp.metric_basis,
        inp.numerator_ref,
        inp.denominator_ref,
        lineage_payload=canonical_row,
    )
    return {
        "valuation_id": valuation_id,
        **canonical_row,
    }


def _canonical_field_equal(field: str, actual: Any, expected: Any) -> bool:
    arrow_type = VALUATION_SNAPSHOTS_ARROW_SCHEMA.field(field).type
    actual_null = actual is None or bool(pd.isna(actual))
    expected_null = expected is None or bool(pd.isna(expected))
    if actual_null or expected_null:
        return actual_null and expected_null
    if pa.types.is_timestamp(arrow_type):
        actual_ts = pd.Timestamp(actual)
        expected_ts = pd.Timestamp(expected)
        if actual_ts.tzinfo is None or expected_ts.tzinfo is None:
            return False
        return actual_ts.tz_convert("UTC") == expected_ts.tz_convert("UTC")
    if pa.types.is_date(arrow_type):
        return pd.Timestamp(actual).date() == pd.Timestamp(expected).date()
    if pa.types.is_floating(arrow_type):
        try:
            return math.isclose(
                float(actual),
                float(expected),
                rel_tol=1e-12,
                abs_tol=0.0,
            )
        except (TypeError, ValueError):
            return False
    return actual == expected


def validate_valuation_snapshots_df(frame: pd.DataFrame) -> list[str]:
    issues: list[str] = []
    if list(frame.columns) != VALUATION_SNAPSHOTS_COLUMNS:
        return ["valuation_snapshots has invalid exact schema"]
    if frame.empty:
        return issues
    if frame["valuation_id"].isna().any() or frame["valuation_id"].duplicated().any():
        issues.append("valuation_id must be non-null and unique")
    for index, row in frame.iterrows():
        try:
            kwargs = {
                field: row[field]
                for field in ValuationInput.__dataclass_fields__
                if field in row.index
            }
            rebuilt = build_valuation_snapshot_row(ValuationInput(**kwargs))
            mismatches = [
                field
                for field in VALUATION_SNAPSHOTS_COLUMNS
                if not _canonical_field_equal(field, row[field], rebuilt[field])
            ]
            if mismatches:
                raise ValueError(
                    "canonical rebuild mismatch: " + ", ".join(mismatches)
                )
        except (TypeError, ValueError) as exc:
            issues.append(f"row {index}: {exc}")
    return issues


def validate_internal_estimates_df(frame: pd.DataFrame) -> list[str]:
    issues: list[str] = []
    if list(frame.columns) != INTERNAL_ESTIMATES_COLUMNS:
        return ["internal_estimates has invalid exact schema"]
    if frame.empty:
        return issues
    if frame["estimate_id"].isna().any() or frame["estimate_id"].duplicated().any():
        issues.append("estimate_id must be non-null and unique")

    ids = set(frame["estimate_id"].astype(str))
    by_id = {str(row["estimate_id"]): row for _, row in frame.iterrows()}
    for index, row in frame.iterrows():
        prefix = f"row {index}: "
        for field in (
            "entity_id",
            "author",
            "metric",
            "accounting_basis",
            "currency",
            "unit",
            "source_ref",
        ):
            if _blank(row[field]):
                issues.append(prefix + f"{field} must not be empty")
        if row["observation_type"] not in SUPPORTED_OBSERVATION_TYPES:
            issues.append(prefix + "invalid observation_type")
        if row["metric_basis"] not in SUPPORTED_METRIC_BASES:
            issues.append(prefix + "invalid metric_basis")
        if row["pit_class"] not in SUPPORTED_PIT_CLASSES:
            issues.append(prefix + "invalid pit_class")
        if (
            row["observation_type"] == "internal_estimate"
            and row["pit_class"] != "not_pit"
        ):
            issues.append(prefix + "internal_estimate pit_class must be not_pit")
        if (
            row["observation_type"] == "management_guidance"
            and row["pit_class"] != "not_pit"
            and _blank(row["source_url"])
        ):
            issues.append(
                prefix + "public management_guidance requires source_url"
            )

        try:
            raw_version = row["version"]
            if isinstance(raw_version, bool):
                raise ValueError
            version_float = float(raw_version)
            if not math.isfinite(version_float) or not version_float.is_integer():
                raise ValueError
            version = int(version_float)
            if version < 1:
                raise ValueError
        except (TypeError, ValueError):
            issues.append(prefix + "version must be a positive integer")
            version = 0
        try:
            fiscal_year_float = float(row["fiscal_year"])
            if not math.isfinite(fiscal_year_float) or not fiscal_year_float.is_integer():
                raise ValueError
            fiscal_year = int(fiscal_year_float)
            if fiscal_year < 1900:
                raise ValueError
        except (TypeError, ValueError):
            issues.append(prefix + "fiscal_year must be a valid integer")
        supersedes = (
            None
            if _blank(row["supersedes_estimate_id"])
            else str(row["supersedes_estimate_id"])
        )
        if version == 1 and supersedes is not None:
            issues.append(prefix + "version 1 must not supersede another estimate")
        if version > 1 and supersedes is None:
            issues.append(prefix + "version > 1 must supersede a prior estimate")
        if supersedes is not None:
            if supersedes == str(row["estimate_id"]):
                issues.append(prefix + "estimate must not supersede itself")
            elif supersedes not in ids:
                issues.append(prefix + "supersedes_estimate_id does not exist")
            else:
                prior = by_id[supersedes]
                try:
                    prior_version = int(prior["version"])
                except (TypeError, ValueError):
                    prior_version = version
                if prior_version >= version:
                    issues.append(prefix + "superseded estimate version must be lower")
                lineage_fields = (
                    "entity_id",
                    "listing_id",
                    "observation_type",
                    "metric",
                    "fiscal_period",
                    "fiscal_year",
                )
                if any(row[field] != prior[field] for field in lineage_fields):
                    issues.append(prefix + "superseded estimate lineage does not match")

        numeric: dict[str, float | None] = {}
        for field in ("value_low", "value_mid", "value_high"):
            if pd.isna(row[field]):
                numeric[field] = None
                continue
            try:
                numeric[field] = _finite(row[field], field)
            except ValueError as exc:
                issues.append(prefix + str(exc))
                numeric[field] = None
        if all(value is None for value in numeric.values()):
            issues.append(prefix + "at least one estimate value is required")
        low, mid, high = (
            numeric["value_low"],
            numeric["value_mid"],
            numeric["value_high"],
        )
        if low is not None and mid is not None and low > mid:
            issues.append(prefix + "value_low must be <= value_mid")
        if mid is not None and high is not None and mid > high:
            issues.append(prefix + "value_mid must be <= value_high")
        if low is not None and high is not None and low > high:
            issues.append(prefix + "value_low must be <= value_high")

        try:
            effective = pd.Timestamp(row["effective_asof"])
            if pd.isna(effective):
                raise ValueError
            recorded = _utc(row["recorded_at_utc"], "recorded_at_utc")
            effective_utc = (
                effective.tz_localize("UTC")
                if effective.tzinfo is None
                else effective.tz_convert("UTC")
            )
            if effective_utc.to_pydatetime() > recorded:
                issues.append(prefix + "effective_asof must not exceed recorded_at_utc")
        except (TypeError, ValueError):
            issues.append(prefix + "effective_asof/recorded_at_utc is invalid")

        reviewed_at_blank = pd.isna(row["reviewed_at_utc"])
        reviewed_by_blank = _blank(row["reviewed_by"])
        if reviewed_at_blank != reviewed_by_blank:
            issues.append(
                prefix
                + "reviewed_at_utc and reviewed_by must both be set or both be null"
            )
        if not reviewed_at_blank:
            try:
                reviewed = _utc(row["reviewed_at_utc"], "reviewed_at_utc")
                recorded = _utc(row["recorded_at_utc"], "recorded_at_utc")
                if reviewed < recorded:
                    issues.append(
                        prefix + "reviewed_at_utc must not precede recorded_at_utc"
                    )
            except ValueError as exc:
                issues.append(prefix + str(exc))
    return issues


def load_internal_estimates_csv(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        return empty_frame(INTERNAL_ESTIMATES_ARROW_SCHEMA)
    frame = pd.read_csv(csv_path, dtype=str)
    if list(frame.columns) != INTERNAL_ESTIMATES_COLUMNS:
        raise ValueError("internal_estimates CSV has invalid exact schema")
    for column in ("version", "fiscal_year"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype("Int64")
    for column in ("value_low", "value_high", "value_mid"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["effective_asof"] = pd.to_datetime(
        frame["effective_asof"], errors="coerce"
    ).dt.date
    for column in ("recorded_at_utc", "reviewed_at_utc"):
        parsed: list[pd.Timestamp | pd.NaT] = []
        for value in frame[column]:
            if _blank(value):
                parsed.append(pd.NaT)
                continue
            # ``pd.Timestamp`` raises on unparseable text; coerce instead so a
            # malformed cell becomes a validation issue rather than an import
            # crash with no row number attached.
            timestamp = pd.to_datetime(value, errors="coerce")
            parsed.append(
                pd.NaT
                if pd.isna(timestamp) or timestamp.tzinfo is None
                else timestamp.tz_convert("UTC")
            )
        frame[column] = pd.to_datetime(parsed, utc=True, errors="coerce")
    return frame


def frame_from_rows(
    rows: Sequence[Mapping[str, Any]], schema: pa.Schema
) -> pd.DataFrame:
    return pa.Table.from_pylist(list(rows), schema=schema).to_pandas()


def write_parquet_atomic(
    frame: pd.DataFrame, schema: pa.Schema, output_path: Path
) -> Path:
    """Write an exact Arrow schema atomically, including typed empty outputs."""

    return _write_parquet_atomic(frame, output_path, schema=schema)


__all__ = [
    "INTERNAL_ESTIMATES_ARROW_SCHEMA",
    "INTERNAL_ESTIMATES_COLUMNS",
    "INTERNAL_ESTIMATES_SCHEMA_ID",
    "SUPPORTED_METRIC_BASES",
    "SUPPORTED_VALUATION_METRIC_BASES",
    "SUPPORTED_OBSERVATION_TYPES",
    "SUPPORTED_PIT_CLASSES",
    "SUPPORTED_VALUATION_METRICS",
    "VALUATION_SNAPSHOTS_ARROW_SCHEMA",
    "VALUATION_SNAPSHOTS_COLUMNS",
    "VALUATION_SNAPSHOTS_SCHEMA_ID",
    "ValuationInput",
    "build_valuation_snapshot_row",
    "canonicalize_metric_basis",
    "compute_valuation_id",
    "empty_frame",
    "frame_from_rows",
    "load_internal_estimates_csv",
    "validate_internal_estimates_df",
    "validate_valuation_snapshots_df",
    "write_parquet_atomic",
]
