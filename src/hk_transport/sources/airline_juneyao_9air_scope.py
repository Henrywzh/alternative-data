"""Point-in-time Juneyao Group versus 9 Air scope reconciliation.

The issuer reports consolidated financials and group operating tables, while
only selected 9 Air standalone passenger/fleet fields are disclosed. This
module makes the reconciliation explicit and refuses to allocate group ASK,
RPK, revenue, cost, fuel or profit using unsupported shares.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..config import NORMALIZED_DIR

OFFICIAL_PATH = NORMALIZED_DIR / "airline_official_report_drivers.csv"
SCOPE_PATH = NORMALIZED_DIR / "airline_scope_reconciliation.csv"
OUTPUT_PATH = NORMALIZED_DIR / "airline_juneyao_9air_scope_reconciliation.csv"

PERIODS = ("FY2025", "1H2025")

# The first candidate is preferred when the same period has both a reported
# issuer line and a derived proxy. The remaining candidates are fallback rows.
OFFICIAL_METRICS = {
    "total_revenue": ("total_revenue",),
    "operating_cost": ("operating_cost",),
    "fuel_cost": ("fuel_cost",),
    "attributable_net_income": ("attributable_net_income",),
    "ask": ("ask",),
    "rpk": ("rpk",),
    "passengers": ("passengers",),
    "passenger_load_factor_pct": ("passenger_load_factor_pct",),
    "passenger_yield": ("passenger_yield",),
    "rask_proxy": ("rask_derived", "rask_from_reported_yield_derived"),
    "cask": ("cask", "cask_derived"),
    "fuel_cost_per_ask": ("fuel_cost_per_ask_derived",),
    "fuel_cost_share_pct": ("fuel_cost_share_pct_derived",),
    "fleet_total": ("fleet_total",),
}


def _num(value: object) -> float | None:
    parsed = pd.to_numeric(value, errors="coerce")
    return None if pd.isna(parsed) else float(parsed)


def _source_date(value: object) -> str:
    text = str(value)[:10]
    return text if len(text) == 10 and text[4] == "-" and text[7] == "-" else "pending"


def _official_row(official: pd.DataFrame, period: str, candidates: tuple[str, ...]) -> pd.Series:
    rows = official[
        official["company"].eq("Juneyao Airlines")
        & official["statement_period"].eq(period)
        & official["metric"].isin(candidates)
        & official["value_native"].notna()
    ].copy()
    if rows.empty:
        return pd.Series(dtype=object)
    order = {metric: index for index, metric in enumerate(candidates)}
    rows["_order"] = rows["metric"].map(order).fillna(999)
    return rows.sort_values("_order").iloc[0]


def _scope_row(scope: pd.DataFrame, period: str, metric: str) -> pd.Series:
    rows = scope[
        scope["company"].eq("Juneyao Airlines")
        & scope["period"].eq(period)
        & scope["metric"].eq(metric)
        & scope["reported_value"].notna()
    ]
    return rows.iloc[0] if not rows.empty else pd.Series(dtype=object)


def _scope_value(row: pd.Series) -> float | None:
    value = _num(row.get("reported_value"))
    if value is None:
        return None
    unit = str(row.get("reported_unit", ""))
    if unit == "passengers":
        return value / 1_000_000.0
    return value


def _latest_snapshot_date(official: pd.DataFrame, scope: pd.DataFrame) -> str:
    dates: list[str] = []
    for frame, columns in ((official, ("announced_at", "period_end")), (scope, ("as_of_date",))):
        for column in columns:
            if column in frame.columns:
                dates.extend(_source_date(value) for value in frame[column].dropna())
    valid = [date for date in dates if date != "pending"]
    return max(valid) if valid else "pending"


def build_airline_juneyao_9air_scope_reconciliation(
    *,
    official: pd.DataFrame | None = None,
    scope: pd.DataFrame | None = None,
    retrieved_at: str | None = None,
) -> pd.DataFrame:
    """Build group/component reconciliation rows without unsupported allocation."""
    official = official if official is not None else pd.read_csv(OFFICIAL_PATH)
    scope = scope if scope is not None else pd.read_csv(SCOPE_PATH)
    retrieved = retrieved_at or datetime.now(timezone.utc).isoformat()
    snapshot_date = _latest_snapshot_date(official, scope)
    rows: list[dict[str, object]] = []

    for period in PERIODS:
        for canonical_metric, candidates in OFFICIAL_METRICS.items():
            group_row = _official_row(official, period, candidates)
            group_value = _num(group_row.get("value_native"))
            group_unit = str(group_row.get("native_unit", "")) if not group_row.empty else ""
            group_currency = str(group_row.get("native_currency", "")) if not group_row.empty else ""
            if group_value is None:
                continue

            nine_value: float | None = None
            mainline_value: float | None = None
            derivation = "group_reported_only"
            reconciliation_status = "group_only_standalone_component_missing"
            model_use = "use_group_only_do_not_allocate_to_mainline_or_9air"
            component_source = pd.Series(dtype=object)

            if period == "FY2025" and canonical_metric == "passengers":
                component_source = _scope_row(scope, period, "passengers_9air_standalone")
                nine_value = _scope_value(component_source)
                if nine_value is not None:
                    mainline_value = group_value - nine_value
                    derivation = "mainline_implied_as_group_minus_disclosed_9air"
                    reconciliation_status = "passenger_volume_reconciles_with_derived_mainline"
                    model_use = "use_for_passenger_mix_only_not_revenue_or_unit_cost_allocation"
            elif period == "FY2025" and canonical_metric == "fleet_total":
                mainline_source = _scope_row(scope, period, "fleet_juneyao_standalone")
                component_source = _scope_row(scope, period, "fleet_9air_standalone")
                mainline_value = _scope_value(mainline_source)
                nine_value = _scope_value(component_source)
                if mainline_value is not None and nine_value is not None:
                    derivation = "component_fleet_values_reported_and_summed"
                    reconciliation_status = "fleet_reconciles_exactly"
                    model_use = "use_for_fleet_mix_and_capacity_scope_only"

            residual = (
                group_value - mainline_value - nine_value
                if group_value is not None and mainline_value is not None and nine_value is not None
                else None
            )
            nine_share = 100.0 * nine_value / group_value if nine_value is not None and group_value else None
            mainline_share = 100.0 * mainline_value / group_value if mainline_value is not None and group_value else None
            group_info_date = _source_date(group_row.get("announced_at")) if not group_row.empty else "pending"
            group_source_url = str(group_row.get("source_url", "")) if not group_row.empty else ""
            group_source_page = _num(group_row.get("source_page")) if not group_row.empty else None
            component_source_url = str(component_source.get("source_url", group_source_url)) if not component_source.empty else group_source_url
            component_source_page = _num(component_source.get("source_page")) if not component_source.empty else group_source_page
            rows.append({
                "dataset_id": "airline_juneyao_9air_scope_reconciliation",
                "snapshot_as_of_date": snapshot_date,
                "parent_group": "Juneyao Airlines",
                "listed_ticker": "603885.SH",
                "statement_period": period,
                "period_end": str(group_row.get("period_end", "")),
                "canonical_metric": canonical_metric,
                "group_value_native": group_value,
                "mainline_value_native": mainline_value,
                "nine_air_value_native": nine_value,
                "residual_native": residual,
                "nine_air_share_pct": nine_share,
                "mainline_share_pct": mainline_share,
                "native_unit": group_unit,
                "native_currency": group_currency,
                "group_scope": "Juneyao consolidated group; includes 9 Air where issuer scope is consolidated",
                "mainline_scope": "Juneyao Air standalone only when separately disclosed; otherwise unavailable",
                "nine_air_scope": "9 Air standalone only when separately disclosed; unlisted subsidiary",
                "reconciliation_status": reconciliation_status,
                "derivation_method": derivation,
                "model_use": model_use,
                "group_information_date": group_info_date,
                "group_source_url": group_source_url,
                "group_source_page": group_source_page,
                "component_source_url": component_source_url,
                "component_source_page": component_source_page,
                "source_quality": "primary_issuer_with_explicit_scope_boundary" if nine_value is not None or mainline_value is not None else "primary_issuer_group_only",
                "source_note": (
                    "Group values are from the Juneyao primary report driver layer. "
                    "Only FY2025 9 Air passengers and fleet, plus Juneyao standalone fleet, are separately disclosed in the covered scope layer. "
                    "Missing standalone revenue, cost, fuel, profit, ASK and RPK are intentionally not allocated."
                ),
                "retrieved_at": retrieved,
            })

    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT_PATH, index=False)
    return result


def fetch_airline_juneyao_9air_scope_reconciliation() -> pd.DataFrame:
    return build_airline_juneyao_9air_scope_reconciliation()
