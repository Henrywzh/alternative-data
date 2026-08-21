"""Valuation multiples, yields, and internal estimates data contracts and transforms.

Strict deterministic implementation for Research Control Tower Gate T2.
Captures forward multiples, EV/EBITDA, FCF yield, and shareholder return yields
with fully auditable numerator and denominator inputs, explicit vintages,
currency alignment logs, and strict fail-closed validation.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import pyarrow as pa


logger = logging.getLogger(__name__)

# Canonical metric names for valuation snapshots
SUPPORTED_VALUATION_METRICS = frozenset({
    "forward_pe",
    "ev_ebitda",
    "fcf_yield",
    "shareholder_cash_return_yield",
})

# Canonical metric basis enum
SUPPORTED_METRIC_BASES = frozenset({
    "GAAP_REPORTED",
    "NON_IFRS_MANAGEMENT",
    "PROVIDER_UNVERIFIED",
})

# Allowed observation types for internal estimates
SUPPORTED_OBSERVATION_TYPES = frozenset({
    "management_guidance",
    "internal_estimate",
})

# Allowed PIT classes for valuation snapshots
SUPPORTED_VALUATION_PIT_CLASSES = frozenset({
    "snapshot_from_live_source",
    "snapshot_from_delayed_source",
    "repository_captured",
    "true_pit",
    "dated_public_broker_report",
    "reconstructed_sparse",
    "current_vintage",
    "not_pit",
})

# Valuation Snapshots Parquet / DataFrame columns
VALUATION_SNAPSHOTS_COLUMNS = [
    "valuation_id",
    "listing_id",
    "valuation_date",
    "valuation_at",
    "metric_name",
    "metric_basis",
    "ratio_value",
    "numerator_value",
    "numerator_currency",
    "numerator_ref",
    "denominator_value",
    "denominator_currency",
    "denominator_ref",
    "fx_rate_applied",
    "fx_source",
    "fx_snapshot_at_utc",
    "source_id",
    "source_url",
    "retrieved_at_utc",
    "pit_class",
    "coverage_reason",
    "percentile_history_status",
]

VALUATION_SNAPSHOTS_SCHEMA_ID = "valuation_snapshots_v1"

# Internal Estimates Parquet / DataFrame columns
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


def compute_valuation_id(
    listing_id: str,
    valuation_at_iso: str,
    metric_name: str,
    metric_basis: str,
    numerator_ref: str,
    denominator_ref: str,
) -> str:
    """Deterministic hash primary key for valuation snapshots."""
    raw = f"{listing_id}|{valuation_at_iso}|{metric_name}|{metric_basis}|{numerator_ref}|{denominator_ref}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class ValuationInput:
    """Strongly typed input structure for computing a valuation multiple / yield."""

    listing_id: str
    valuation_at: datetime
    metric_name: str
    metric_basis: str
    numerator_value: float
    numerator_currency: str
    numerator_ref: str
    denominator_value: float
    denominator_currency: str
    denominator_ref: str
    fx_rate_applied: float | None = None
    fx_source: str | None = None
    fx_snapshot_at_utc: datetime | None = None
    source_id: str = "valuation_engine"
    source_url: str = ""
    retrieved_at_utc: datetime | None = None
    pit_class: str = "snapshot_from_delayed_source"
    coverage_reason: str | None = None
    percentile_history_status: str = "unavailable"


def build_valuation_snapshot_row(inp: ValuationInput) -> dict[str, Any]:
    """Validate inputs and construct an auditable valuation snapshot row."""
    if inp.metric_name not in SUPPORTED_VALUATION_METRICS:
        raise ValueError(
            f"Unsupported metric_name: {inp.metric_name!r}. Must be one of {sorted(SUPPORTED_VALUATION_METRICS)}"
        )
    if inp.metric_basis not in SUPPORTED_METRIC_BASES:
        raise ValueError(
            f"Unsupported metric_basis: {inp.metric_basis!r}. Must be one of {sorted(SUPPORTED_METRIC_BASES)}"
        )
    if inp.pit_class not in SUPPORTED_VALUATION_PIT_CLASSES:
        raise ValueError(
            f"Unsupported pit_class: {inp.pit_class!r}. Must be one of {sorted(SUPPORTED_VALUATION_PIT_CLASSES)}"
        )

    if not inp.listing_id or not inp.numerator_ref or not inp.denominator_ref:
        raise ValueError("listing_id, numerator_ref, and denominator_ref must not be empty")

    if inp.valuation_at.tzinfo is None:
        raise ValueError("valuation_at must be timezone-aware (UTC)")

    valuation_at_utc = inp.valuation_at.astimezone(timezone.utc)
    valuation_date = valuation_at_utc.strftime("%Y-%m-%d")
    valuation_at_iso = valuation_at_utc.isoformat()

    retrieved_at = inp.retrieved_at_utc or valuation_at_utc
    if retrieved_at.tzinfo is None:
        raise ValueError("retrieved_at_utc must be timezone-aware (UTC)")
    retrieved_at_utc = retrieved_at.astimezone(timezone.utc)

    # Check denominator validity
    if inp.denominator_value is None or inp.denominator_value == 0:
        raise ValueError("denominator_value cannot be None or 0")

    # Currency conversion check:
    # If currencies differ, FX rate must be provided and > 0, along with fx_source and fx_snapshot_at_utc
    num_curr = inp.numerator_currency.upper().strip()
    den_curr = inp.denominator_currency.upper().strip()

    if num_curr != den_curr:
        if inp.fx_rate_applied is None or inp.fx_rate_applied <= 0:
            raise ValueError(
                f"Currencies differ ({num_curr} vs {den_curr}) but fx_rate_applied is missing or <= 0"
            )
        if not inp.fx_source:
            raise ValueError(
                f"Currencies differ ({num_curr} vs {den_curr}) but fx_source is missing"
            )
        if inp.fx_snapshot_at_utc is None:
            raise ValueError(
                f"Currencies differ ({num_curr} vs {den_curr}) but fx_snapshot_at_utc is missing"
            )
        # Note on FX conversion:
        # If numerator is in HKD and denominator is in CNY (e.g. Price in HKD, EPS in CNY)
        # To compute P/E: we need both in same currency.
        # fx_rate_applied is the multiplier applied to convert denominator into numerator currency,
        # OR fx_rate_applied is explicitly recorded.
        # E.g. EPS_HKD = EPS_CNY * (HKD_per_CNY). Then P / EPS_HKD.
        # Here we compute ratio_value = numerator_value / (denominator_value * fx_rate_applied)
        # Or for yield: denominator_value * fx_rate_applied / numerator_value
        den_converted = inp.denominator_value * inp.fx_rate_applied
    else:
        den_converted = inp.denominator_value

    if inp.metric_name in {"forward_pe", "ev_ebitda"}:
        ratio_value = float(inp.numerator_value / den_converted)
    elif inp.metric_name in {"fcf_yield", "shareholder_cash_return_yield"}:
        ratio_value = float(den_converted / inp.numerator_value)
    else:
        raise ValueError(f"Unhandled metric calculation: {inp.metric_name}")

    fx_snapshot_utc = None
    if inp.fx_snapshot_at_utc is not None:
        if inp.fx_snapshot_at_utc.tzinfo is None:
            raise ValueError("fx_snapshot_at_utc must be timezone-aware (UTC)")
        fx_snapshot_utc = inp.fx_snapshot_at_utc.astimezone(timezone.utc)

    val_id = compute_valuation_id(
        listing_id=inp.listing_id,
        valuation_at_iso=valuation_at_iso,
        metric_name=inp.metric_name,
        metric_basis=inp.metric_basis,
        numerator_ref=inp.numerator_ref,
        denominator_ref=inp.denominator_ref,
    )

    return {
        "valuation_id": val_id,
        "listing_id": inp.listing_id,
        "valuation_date": valuation_date,
        "valuation_at": valuation_at_utc,
        "metric_name": inp.metric_name,
        "metric_basis": inp.metric_basis,
        "ratio_value": ratio_value,
        "numerator_value": float(inp.numerator_value),
        "numerator_currency": num_curr,
        "numerator_ref": inp.numerator_ref,
        "denominator_value": float(inp.denominator_value),
        "denominator_currency": den_curr,
        "denominator_ref": inp.denominator_ref,
        "fx_rate_applied": float(inp.fx_rate_applied) if inp.fx_rate_applied is not None else None,
        "fx_source": inp.fx_source,
        "fx_snapshot_at_utc": fx_snapshot_utc,
        "source_id": inp.source_id,
        "source_url": inp.source_url,
        "retrieved_at_utc": retrieved_at_utc,
        "pit_class": inp.pit_class,
        "coverage_reason": inp.coverage_reason,
        "percentile_history_status": inp.percentile_history_status,
    }


def validate_valuation_snapshots_df(df: pd.DataFrame) -> list[str]:
    """Deterministic validator for valuation_snapshots DataFrame."""
    issues: list[str] = []
    missing_cols = set(VALUATION_SNAPSHOTS_COLUMNS) - set(df.columns)
    if missing_cols:
        issues.append(f"Missing required columns: {sorted(missing_cols)}")
        return issues

    if df.empty:
        return issues

    # Primary key uniqueness
    if df["valuation_id"].duplicated().any():
        dupes = df.loc[df["valuation_id"].duplicated(), "valuation_id"].tolist()
        issues.append(f"Duplicate valuation_id values found: {dupes[:5]}")

    for idx, row in df.iterrows():
        # Metric validation
        if row["metric_name"] not in SUPPORTED_VALUATION_METRICS:
            issues.append(f"Row {idx}: invalid metric_name '{row['metric_name']}'")
        if row["metric_basis"] not in SUPPORTED_METRIC_BASES:
            issues.append(f"Row {idx}: invalid metric_basis '{row['metric_basis']}'")
        if row["pit_class"] not in SUPPORTED_VALUATION_PIT_CLASSES:
            issues.append(f"Row {idx}: invalid pit_class '{row['pit_class']}'")

        # Percentile status must be unavailable unless historical denominator vintages are validated
        if row["percentile_history_status"] != "unavailable":
            issues.append(
                f"Row {idx}: percentile_history_status must be 'unavailable' when historical vintages are unverified"
            )

        # Currency and FX audit
        num_curr = str(row["numerator_currency"]).upper().strip()
        den_curr = str(row["denominator_currency"]).upper().strip()
        if num_curr != den_curr:
            if pd.isna(row["fx_rate_applied"]) or row["fx_rate_applied"] <= 0:
                issues.append(
                    f"Row {idx}: fx_rate_applied must be positive when {num_curr} != {den_curr}"
                )
            if pd.isna(row["fx_source"]) or not str(row["fx_source"]).strip():
                issues.append(
                    f"Row {idx}: fx_source must be non-empty when {num_curr} != {den_curr}"
                )
            if pd.isna(row["fx_snapshot_at_utc"]):
                issues.append(
                    f"Row {idx}: fx_snapshot_at_utc must be non-null when {num_curr} != {den_curr}"
                )

        # Non-null essential refs
        if pd.isna(row["numerator_ref"]) or not str(row["numerator_ref"]).strip():
            issues.append(f"Row {idx}: numerator_ref must not be empty")
        if pd.isna(row["denominator_ref"]) or not str(row["denominator_ref"]).strip():
            issues.append(f"Row {idx}: denominator_ref must not be empty")

    return issues


def validate_internal_estimates_df(df: pd.DataFrame) -> list[str]:
    """Deterministic validator for internal_estimates DataFrame."""
    issues: list[str] = []
    missing_cols = set(INTERNAL_ESTIMATES_COLUMNS) - set(df.columns)
    if missing_cols:
        issues.append(f"Missing required columns: {sorted(missing_cols)}")
        return issues

    if df.empty:
        return issues

    if df["estimate_id"].duplicated().any():
        dupes = df.loc[df["estimate_id"].duplicated(), "estimate_id"].tolist()
        issues.append(f"Duplicate estimate_id values found: {dupes[:5]}")

    for idx, row in df.iterrows():
        if row["observation_type"] not in SUPPORTED_OBSERVATION_TYPES:
            issues.append(
                f"Row {idx}: invalid observation_type '{row['observation_type']}'. Must be one of {sorted(SUPPORTED_OBSERVATION_TYPES)}"
            )
        if row["metric_basis"] not in SUPPORTED_METRIC_BASES:
            issues.append(
                f"Row {idx}: invalid metric_basis '{row['metric_basis']}'. Must be one of {sorted(SUPPORTED_METRIC_BASES)}"
            )
        if pd.isna(row["entity_id"]) or not str(row["entity_id"]).strip():
            issues.append(f"Row {idx}: entity_id must not be empty")
        if pd.isna(row["metric"]) or not str(row["metric"]).strip():
            issues.append(f"Row {idx}: metric must not be empty")
        if pd.isna(row["author"]) or not str(row["author"]).strip():
            issues.append(f"Row {idx}: author must not be empty")
        if pd.isna(row["source_ref"]) or not str(row["source_ref"]).strip():
            issues.append(f"Row {idx}: source_ref must not be empty")

        # Values check: at least one of value_low, value_high, value_mid must be non-null
        v_low = row["value_low"]
        v_high = row["value_high"]
        v_mid = row["value_mid"]
        if pd.isna(v_low) and pd.isna(v_high) and pd.isna(v_mid):
            issues.append(
                f"Row {idx}: at least one of value_low, value_high, value_mid must be provided"
            )

    return issues


def load_internal_estimates_csv(csv_path: Path) -> pd.DataFrame:
    """Read internal_estimates.csv with deterministic typing."""
    if not csv_path.exists():
        return pd.DataFrame(columns=INTERNAL_ESTIMATES_COLUMNS)

    df = pd.read_csv(csv_path, dtype=str)
    # Ensure all columns present
    for col in INTERNAL_ESTIMATES_COLUMNS:
        if col not in df.columns:
            df[col] = pd.NA

    df = df[INTERNAL_ESTIMATES_COLUMNS]

    # Convert numeric columns
    for col in ["value_low", "value_high", "value_mid"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if "fiscal_year" in df.columns:
        df["fiscal_year"] = pd.to_numeric(df["fiscal_year"], errors="coerce").astype("Int64")

    # Convert timestamps
    for col in ["recorded_at_utc", "reviewed_at_utc"]:
        df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")

    return df

