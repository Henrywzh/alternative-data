"""Quality gates for immutable HK labour-market source vintages."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from .source_registry import CenstatdTableSpec

REQUIRED_COLUMNS = {
    "source_table_id", "period", "period_end", "frequency_code", "metric_code",
    "metric_label", "dimension_key", "source_dimensions_json", "value", "status_flag",
    "retrieved_at", "data_source",
}
# `sv` identifies a family of statistics, not necessarily one observation,
# and each table can introduce different classification dimensions.  The
# source-derived dimension signature retains the complete original grain.
NATURAL_KEY = [
    "source_table_id", "period", "frequency_code", "metric_code", "metric_label",
    "dimension_key",
]
POLICY_NATURAL_KEY = [
    "source_table_id", "period", "frequency_code", "metric_code", "metric_label",
    "dimension_key",
]
POLICY_REQUIRED_COLUMNS = {
    "source_table_id", "period", "period_end", "frequency_code", "metric_code",
    "metric_label", "dimension_key", "value", "retrieved_at", "data_source",
}


def validate_frame(frame: pd.DataFrame, spec: CenstatdTableSpec) -> list[str]:
    """Return human-readable quality errors; suppressed / N.A. values remain valid rows."""
    if frame.empty:
        return ["dataset yielded zero normalized records"]
    missing = sorted(REQUIRED_COLUMNS.difference(frame.columns))
    if missing:
        return [f"missing required columns: {', '.join(missing)}"]
    if frame["source_table_id"].nunique() != 1 or frame["source_table_id"].iloc[0] != spec.table_id:
        return [f"source table identity does not match {spec.table_id}"]
    if frame["period"].isna().any() or frame["period_end"].isna().any():
        return ["contains invalid or unsupported source periods"]
    if frame.duplicated(subset=NATURAL_KEY).any():
        return ["contains duplicate source observations for its natural key"]
    available = frame["value"].notna()
    if not available.any():
        return ["contains no numeric observations"]
    latest = pd.to_datetime(frame.loc[available, "period_end"], errors="coerce").max()
    if pd.isna(latest):
        return ["cannot determine latest numeric observation"]
    now = pd.Timestamp(datetime.now(timezone.utc).date())
    if latest > now + pd.Timedelta(days=7):
        return [f"latest observation is implausibly in the future: {latest.date()}"]
    if latest < now - pd.Timedelta(days=spec.expected_latest_age_days):
        return [f"latest observation is stale: {latest.date()}"]
    return []


def validate_policy_frame(frame: pd.DataFrame, expected_source_table_id: str | None = None) -> list[str]:
    """Validate annual labour-supply policy counts in their source grain."""
    if frame.empty:
        return ["dataset yielded zero normalized records"]
    missing = sorted(POLICY_REQUIRED_COLUMNS.difference(frame.columns))
    if missing:
        return [f"missing required policy columns: {', '.join(missing)}"]
    if frame["source_table_id"].nunique() != 1:
        return ["policy frame contains more than one source table identity"]
    if expected_source_table_id and frame["source_table_id"].iloc[0] != expected_source_table_id:
        return [f"policy source table identity does not match {expected_source_table_id}"]
    if frame["period"].isna().any() or frame["period_end"].isna().any():
        return ["policy frame contains invalid source periods"]
    if frame.duplicated(subset=POLICY_NATURAL_KEY).any():
        return ["contains duplicate policy observations for its natural key"]
    values = pd.to_numeric(frame["value"], errors="coerce")
    if values.isna().any():
        return ["policy frame contains non-numeric counts"]
    if (values < 0).any():
        return ["policy frame contains negative counts"]
    latest = pd.to_datetime(frame["period_end"], errors="coerce").max()
    if pd.isna(latest):
        return ["cannot determine latest policy observation"]
    now = pd.Timestamp(datetime.now(timezone.utc).date())
    if latest > now + pd.Timedelta(days=7):
        return [f"latest policy observation is implausibly in the future: {latest.date()}"]
    return []
