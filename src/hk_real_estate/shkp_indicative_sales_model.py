"""Research-only SHKP contract-activity sales/growth model.

This module sits downstream of ``shkp_indicative_project_month_signals`` and
is intentionally separate from the strict SHKP financial model.  It is a
rough project-activity bridge, not recognised revenue and not a legal
ownership attribution.

Numeric-stake phases use the indicative point-in-time/grouped percentage
already present in the signal contract.  SHKP-linked JV phases without a
numeric percentage remain a separate gross bucket and are shown under three
explicit sensitivity assumptions.  Rows that are not covered or lack SHKP
identity evidence are retained in coverage diagnostics and excluded from the
estimated SHKP total.
"""

from __future__ import annotations

import uuid
import json
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .shkp_financial_model import build_shkp_disclosed_financial_facts
from .shkp_signals import ALL_HISTORY_INDICATIVE_SIGNAL_DATASET
from .storage import load_latest_normalized, save_normalized_dataset


INDICATIVE_SIGNAL_DATASET = "shkp_indicative_project_month_signals"
MONTHLY_DATASET = "shkp_indicative_sales_model_monthly"
SCENARIO_DATASET = "shkp_indicative_sales_model_scenarios"
ANNUAL_DATASET = "shkp_indicative_sales_model_annual"
VALIDATION_DATASET = "shkp_indicative_sales_model_validation"
FORECAST_DATASET = "shkp_indicative_sales_model_forecast"
BACKTEST_DATASET = "shkp_indicative_sales_model_backtest"
QUARTERLY_RECONCILIATION_DATASET = "shkp_indicative_sales_model_quarterly_reconciliation"
HISTORICAL_RECONCILIATION_DATASET = "shkp_indicative_sales_model_historical_reconciliation"
UNIVERSE_COVERAGE_DATASET = "shkp_indicative_sales_model_universe_coverage"
PROJECT_COVERAGE_DATASET = "shkp_indicative_sales_model_project_coverage"
PHASE_DATASET = "shkp_indicative_sales_model_phase_summary"
COVERAGE_DATASET = "shkp_indicative_sales_model_coverage"

# These are research defaults, not statements about any individual legal
# ownership interest.  Keeping them in one public constant makes the model
# assumptions easy to override and audit.
DEFAULT_JV_SCENARIO_SHARES: dict[str, float] = {
    "low": 0.25,
    "base": 0.50,
    "high": 0.75,
}

_REQUIRED_COLUMNS = {
    "phase_id",
    "period",
    "month_status",
    "indicative_attribution_status",
    "sales_value_gross_hkd",
    "sales_units_gross",
    "indicative_sales_value_hkd",
    "indicative_sales_units",
}
_SCENARIOS = ("low", "base", "high")
_NUMERIC_STATUS = "indicative_numeric_snapshot"
_JV_STATUS = "indicative_jv_unquantified"
_NOT_COVERED = "not_covered"
DEFAULT_FORECAST_GROWTH_WINDOW = 4
DEFAULT_BACKTEST_LOOKBACK_MONTHS = 3


def _sum_or_zero(values: pd.Series) -> float:
    numeric = pd.to_numeric(values, errors="coerce")
    return float(numeric.sum()) if numeric.notna().any() else 0.0


def _first_non_null(values: pd.Series) -> Any:
    non_null = values.dropna()
    if non_null.empty:
        return None
    return non_null.iloc[0]


def _mode_or_first(values: pd.Series, default: str = "") -> str:
    clean = values.dropna().astype(str).str.strip()
    clean = clean[clean.ne("")]
    if clean.empty:
        return default
    modes = clean.mode()
    return str(modes.iloc[0] if not modes.empty else clean.iloc[0])


def _normalise_signals(signals: pd.DataFrame) -> pd.DataFrame:
    if signals is None or signals.empty:
        return pd.DataFrame()
    missing = sorted(_REQUIRED_COLUMNS - set(signals.columns))
    if missing:
        raise ValueError(
            "indicative project-month signals missing required columns: "
            + ", ".join(missing)
        )
    frame = signals.copy()
    frame["phase_id"] = frame["phase_id"].fillna("").astype(str).str.strip()
    frame = frame[frame["phase_id"].ne("")].copy()
    frame["period"] = pd.to_datetime(frame["period"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    frame = frame[frame["period"].notna()].copy()
    for column in (
        "sales_value_gross_hkd",
        "sales_units_gross",
        "indicative_sales_value_hkd",
        "indicative_sales_units",
        "indicative_ownership_pct",
        "indicative_ownership_pct_low",
        "indicative_ownership_pct_high",
        "active_units_eom",
    ):
        if column not in frame.columns:
            frame[column] = pd.NA
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    for column in ("month_status", "indicative_attribution_status"):
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    return frame


def _validate_scenario_shares(shares: Mapping[str, float] | None) -> dict[str, float]:
    resolved = dict(DEFAULT_JV_SCENARIO_SHARES if shares is None else shares)
    if set(resolved) != set(_SCENARIOS):
        raise ValueError("jv_scenario_shares must contain exactly low, base and high")
    for scenario, value in resolved.items():
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"JV share for {scenario} is not numeric") from exc
        if not 0.0 <= numeric <= 1.0:
            raise ValueError(f"JV share for {scenario} must be between 0 and 1")
        resolved[scenario] = numeric
    if not resolved["low"] <= resolved["base"] <= resolved["high"]:
        raise ValueError("JV shares must satisfy low <= base <= high")
    return resolved


def _growth_pct(current: pd.Series, prior: pd.Series) -> pd.Series:
    current_values = pd.to_numeric(current, errors="coerce")
    prior_values = pd.to_numeric(prior, errors="coerce")
    result = pd.Series(np.nan, index=current.index, dtype="float64")
    valid = current_values.notna() & prior_values.notna() & prior_values.ne(0)
    result.loc[valid] = (current_values.loc[valid] / prior_values.loc[valid] - 1.0) * 100.0
    return result


def _add_calendar_yoy(frame: pd.DataFrame, metric_columns: list[str]) -> pd.DataFrame:
    """Add calendar-year YoY fields without relying on row position."""
    result = frame.copy()
    prior = result[["period", *metric_columns]].copy()
    prior["period"] = prior["period"] + pd.DateOffset(years=1)
    prior = prior.rename(columns={column: f"__prior_{column}" for column in metric_columns})
    result = result.merge(prior, on="period", how="left", validate="one_to_one")
    for column in metric_columns:
        result[f"{column}_yoy_growth_pct"] = _growth_pct(
            result[column], result[f"__prior_{column}"]
        )
        result = result.drop(columns=[f"__prior_{column}"])
    return result


def _add_rolling_columns(frame: pd.DataFrame, metric_columns: list[str]) -> pd.DataFrame:
    result = frame.sort_values("period").copy()
    # The signal contract normally has one row per calendar month.  A
    # gap-aware check avoids silently treating a two-month gap as a three-row
    # rolling window.
    period_ord = result["period"].dt.year * 12 + result["period"].dt.month
    contiguous_3 = period_ord.diff().eq(1).rolling(2, min_periods=2).sum().eq(2)
    contiguous_3 = contiguous_3.reindex(result.index, fill_value=False)
    contiguous_12 = period_ord.diff().eq(1).rolling(11, min_periods=11).sum().eq(11)
    contiguous_12 = contiguous_12.reindex(result.index, fill_value=False)
    for column in metric_columns:
        result[f"{column}_rolling_3m_hkd"] = result[column].rolling(3, min_periods=3).sum().where(contiguous_3)
        result[f"{column}_rolling_12m_hkd"] = result[column].rolling(12, min_periods=12).sum().where(contiguous_12)
    return result


def build_shkp_indicative_sales_model_monthly(
    indicative_signals: pd.DataFrame,
    *,
    jv_scenario_shares: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    """Aggregate phase-month contract activity into numeric/JV scenarios.

    The numeric bucket is fixed across scenarios.  Only the unquantified JV
    gross bucket varies with ``jv_scenario_shares``.  Unknown identity and
    uncovered tail rows are exposed as diagnostics, never folded into the
    estimated SHKP total.
    """
    frame = _normalise_signals(indicative_signals)
    if frame.empty:
        return pd.DataFrame()
    shares = _validate_scenario_shares(jv_scenario_shares)
    covered = frame["month_status"].ne(_NOT_COVERED)
    frame["_is_numeric"] = frame["indicative_attribution_status"].eq(_NUMERIC_STATUS)
    frame["_is_jv"] = frame["indicative_attribution_status"].eq(_JV_STATUS)
    frame["_is_unknown"] = ~frame["_is_numeric"] & ~frame["_is_jv"]
    frame["_is_covered"] = covered

    rows: list[dict[str, Any]] = []
    for period, group in frame.groupby("period", sort=True):
        covered_group = group[group["_is_covered"]].copy()
        numeric = covered_group[covered_group["_is_numeric"]]
        jv = covered_group[covered_group["_is_jv"]]
        unknown = covered_group[covered_group["_is_unknown"]]
        numeric_gross_value = _sum_or_zero(numeric["sales_value_gross_hkd"])
        numeric_gross_units = _sum_or_zero(numeric["sales_units_gross"])
        numeric_value = _sum_or_zero(numeric["indicative_sales_value_hkd"])
        numeric_units = _sum_or_zero(numeric["indicative_sales_units"])
        jv_gross_value = _sum_or_zero(jv["sales_value_gross_hkd"])
        jv_gross_units = _sum_or_zero(jv["sales_units_gross"])
        unknown_value = _sum_or_zero(unknown["sales_value_gross_hkd"])
        unknown_units = _sum_or_zero(unknown["sales_units_gross"])
        row: dict[str, Any] = {
            "period": period.strftime("%Y-%m-%d"),
            "numeric_gross_sales_value_hkd": numeric_gross_value,
            "numeric_gross_sales_units": numeric_gross_units,
            "numeric_stake_sales_value_hkd": numeric_value,
            "numeric_stake_sales_units": numeric_units,
            "jv_gross_sales_value_hkd": jv_gross_value,
            "jv_gross_sales_units": jv_gross_units,
            "unknown_gross_sales_value_hkd": unknown_value,
            "unknown_gross_sales_units": unknown_units,
            "numeric_phase_count": int(numeric["phase_id"].nunique()),
            "jv_phase_count": int(jv["phase_id"].nunique()),
            "unknown_phase_count": int(unknown["phase_id"].nunique()),
            "covered_phase_count": int(covered_group["phase_id"].nunique()),
            "not_covered_phase_count": int(group.loc[~group["_is_covered"], "phase_id"].nunique()),
            "covered_phase_month_rows": int(len(covered_group)),
            "not_covered_phase_month_rows": int((~group["_is_covered"]).sum()),
        }
        for scenario, share in shares.items():
            scenario_jv_value = jv_gross_value * share
            scenario_jv_units = jv_gross_units * share
            row[f"jv_{scenario}_share_pct"] = share * 100.0
            row[f"jv_{scenario}_sales_value_hkd"] = scenario_jv_value
            row[f"jv_{scenario}_sales_units"] = scenario_jv_units
            row[f"estimated_total_{scenario}_sales_value_hkd"] = numeric_value + scenario_jv_value
            row[f"estimated_total_{scenario}_sales_units"] = numeric_units + scenario_jv_units
        rows.append(row)

    monthly = pd.DataFrame(rows)
    monthly["period"] = pd.to_datetime(monthly["period"])
    metric_columns = [
        "numeric_gross_sales_value_hkd",
        "numeric_stake_sales_value_hkd",
        "jv_gross_sales_value_hkd",
        "estimated_total_low_sales_value_hkd",
        "estimated_total_base_sales_value_hkd",
        "estimated_total_high_sales_value_hkd",
        "numeric_gross_sales_units",
        "numeric_stake_sales_units",
        "jv_gross_sales_units",
        "estimated_total_low_sales_units",
        "estimated_total_base_sales_units",
        "estimated_total_high_sales_units",
    ]
    monthly = _add_calendar_yoy(monthly, metric_columns)
    monthly = _add_rolling_columns(
        monthly,
        [
            "numeric_stake_sales_value_hkd",
            "estimated_total_low_sales_value_hkd",
            "estimated_total_base_sales_value_hkd",
            "estimated_total_high_sales_value_hkd",
        ],
    )
    monthly["period"] = monthly["period"].dt.strftime("%Y-%m-%d")
    monthly["model_use"] = "indicative_contract_activity_proxy"
    monthly["research_only"] = True
    monthly["caveat"] = (
        "Gross SRPE contract activity, not recognised revenue; numeric stake is an indicative snapshot; "
        "JV totals vary only by the explicit assumed share; unknown/uncovered rows are excluded."
    )
    return monthly.sort_values("period").reset_index(drop=True)


def build_shkp_indicative_sales_model_scenarios(
    monthly: pd.DataFrame,
    *,
    jv_scenario_shares: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    """Return a long scenario table suitable for charts and comparisons."""
    if monthly is None or monthly.empty:
        return pd.DataFrame()
    shares = _validate_scenario_shares(jv_scenario_shares)
    rows: list[dict[str, Any]] = []
    for _, row in monthly.iterrows():
        for scenario, share in shares.items():
            rows.append(
                {
                    "period": row["period"],
                    "scenario": scenario,
                    "numeric_gross_sales_value_hkd": float(row["numeric_gross_sales_value_hkd"]),
                    "numeric_gross_sales_units": float(row["numeric_gross_sales_units"]),
                    "numeric_stake_sales_value_hkd": float(row["numeric_stake_sales_value_hkd"]),
                    "numeric_stake_sales_units": float(row["numeric_stake_sales_units"]),
                    "jv_gross_sales_value_hkd": float(row["jv_gross_sales_value_hkd"]),
                    "jv_gross_sales_units": float(row["jv_gross_sales_units"]),
                    "jv_assumed_share_pct": share * 100.0,
                    "jv_estimated_sales_value_hkd": float(row[f"jv_{scenario}_sales_value_hkd"]),
                    "jv_estimated_sales_units": float(row[f"jv_{scenario}_sales_units"]),
                    "estimated_total_sales_value_hkd": float(row[f"estimated_total_{scenario}_sales_value_hkd"]),
                    "estimated_total_sales_units": float(row[f"estimated_total_{scenario}_sales_units"]),
                    "unknown_gross_sales_value_hkd": float(row["unknown_gross_sales_value_hkd"]),
                    "unknown_gross_sales_units": float(row["unknown_gross_sales_units"]),
                    "model_use": "indicative_contract_activity_proxy",
                    "research_only": True,
                    "caveat": "JV share is a mechanical sensitivity, not a sourced ownership percentage.",
                }
            )
    return pd.DataFrame(rows)


def build_shkp_indicative_sales_model_annual(monthly: pd.DataFrame) -> pd.DataFrame:
    """Aggregate monthly scenarios to calendar years with partial-year flags."""
    if monthly is None or monthly.empty:
        return pd.DataFrame()
    frame = monthly.copy()
    frame["period"] = pd.to_datetime(frame["period"], errors="coerce")
    frame = frame[frame["period"].notna()].copy()
    if frame.empty:
        return pd.DataFrame()
    frame["year"] = frame["period"].dt.year.astype(int)
    value_columns = [
        "numeric_gross_sales_value_hkd",
        "numeric_stake_sales_value_hkd",
        "jv_gross_sales_value_hkd",
        "unknown_gross_sales_value_hkd",
        "estimated_total_low_sales_value_hkd",
        "estimated_total_base_sales_value_hkd",
        "estimated_total_high_sales_value_hkd",
        "numeric_gross_sales_units",
        "numeric_stake_sales_units",
        "jv_gross_sales_units",
        "unknown_gross_sales_units",
        "estimated_total_low_sales_units",
        "estimated_total_base_sales_units",
        "estimated_total_high_sales_units",
    ]
    grouped = frame.groupby("year", as_index=False).agg(
        **{column: (column, "sum") for column in value_columns},
        months_present=("period", "nunique"),
        first_period=("period", "min"),
        last_period=("period", "max"),
    )
    grouped["months_present"] = grouped["months_present"].astype(int)
    grouped["is_partial_year"] = grouped["months_present"].lt(12)
    prior = grouped[["year", "months_present", *value_columns]].copy()
    prior["year"] = prior["year"] + 1
    prior = prior.rename(columns={
        "months_present": "prior_year_months_present",
        **{column: f"__prior_{column}" for column in value_columns},
    })
    grouped = grouped.merge(prior, on="year", how="left", validate="one_to_one")
    for column in value_columns:
        grouped[f"{column}_yoy_growth_pct"] = _growth_pct(
            grouped[column], grouped[f"__prior_{column}"]
        )
        grouped = grouped.drop(columns=[f"__prior_{column}"])
    grouped["growth_comparison_status"] = np.where(
        grouped["prior_year_months_present"].eq(12) & grouped["months_present"].eq(12),
        "full_year_vs_full_year",
        "partial_year_or_missing_comparison",
    )
    grouped["first_period"] = grouped["first_period"].dt.strftime("%Y-%m-%d")
    grouped["last_period"] = grouped["last_period"].dt.strftime("%Y-%m-%d")
    grouped["model_use"] = "indicative_contract_activity_proxy"
    grouped["research_only"] = True
    grouped["caveat"] = (
        "Calendar-year sum of monthly gross contract-activity proxies. Partial years are flagged and their YoY "
        "growth is not directly comparable to a full year."
    )
    return grouped.sort_values("year").reset_index(drop=True)


_FISCAL_VALUE_COLUMNS = [
    "numeric_stake_sales_value_hkd",
    "jv_gross_sales_value_hkd",
    "unknown_gross_sales_value_hkd",
    "estimated_total_low_sales_value_hkd",
    "estimated_total_base_sales_value_hkd",
    "estimated_total_high_sales_value_hkd",
    "numeric_stake_sales_units",
    "jv_gross_sales_units",
    "unknown_gross_sales_units",
    "estimated_total_low_sales_units",
    "estimated_total_base_sales_units",
    "estimated_total_high_sales_units",
]


def _build_fiscal_annual(monthly: pd.DataFrame) -> pd.DataFrame:
    """Aggregate model months into SHKP's July-to-June fiscal years."""
    if monthly is None or monthly.empty:
        return pd.DataFrame()
    missing = sorted(set(["period", *_FISCAL_VALUE_COLUMNS]) - set(monthly.columns))
    if missing:
        raise ValueError("monthly model is missing fiscal aggregation columns: " + ", ".join(missing))
    frame = monthly.copy()
    frame["period"] = pd.to_datetime(frame["period"], errors="coerce")
    frame = frame[frame["period"].notna()].copy()
    if frame.empty:
        return pd.DataFrame()
    frame["fiscal_year_end"] = frame["period"].dt.year + frame["period"].dt.month.ge(7).astype(int)
    aggregation: dict[str, tuple[str, str | Any]] = {
        column: (column, "sum") for column in _FISCAL_VALUE_COLUMNS
    }
    aggregation.update(
        {
            "months_present": ("period", "nunique"),
            "first_period": ("period", "min"),
            "last_period": ("period", "max"),
        }
    )
    has_coverage = {"covered_phase_count", "not_covered_phase_count"}.issubset(frame.columns)
    if has_coverage:
        covered = pd.to_numeric(frame["covered_phase_count"], errors="coerce")
        not_covered = pd.to_numeric(frame["not_covered_phase_count"], errors="coerce")
        denominator = covered + not_covered
        frame["__monthly_coverage_ratio"] = (covered / denominator).where(denominator.gt(0))
        aggregation.update(
            {
                "min_monthly_coverage_ratio": ("__monthly_coverage_ratio", "min"),
                "min_covered_phase_count": ("covered_phase_count", "min"),
                "max_not_covered_phase_count": ("not_covered_phase_count", "max"),
            }
        )
    grouped = frame.groupby("fiscal_year_end", as_index=False).agg(**aggregation)
    grouped["months_present"] = grouped["months_present"].astype(int)
    grouped["is_partial_year"] = grouped["months_present"].lt(12)
    if not has_coverage:
        grouped["min_monthly_coverage_ratio"] = pd.NA
        grouped["min_covered_phase_count"] = pd.NA
        grouped["max_not_covered_phase_count"] = pd.NA
    grouped["coverage_quality_status"] = np.where(
        grouped["min_monthly_coverage_ratio"].isna(),
        "coverage_diagnostics_not_provided",
        "coverage_diagnostics_available",
    )
    return grouped.sort_values("fiscal_year_end").reset_index(drop=True)


def _ratio_pct(numerator: Any, denominator: Any) -> float | None:
    numerator_value = pd.to_numeric(pd.Series([numerator]), errors="coerce").iloc[0]
    denominator_value = pd.to_numeric(pd.Series([denominator]), errors="coerce").iloc[0]
    if pd.isna(numerator_value) or pd.isna(denominator_value) or denominator_value == 0:
        return None
    return float(numerator_value / denominator_value * 100.0)


def _fiscal_end_for_period(value: Any) -> int | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return int(parsed.year + (1 if parsed.month >= 7 else 0))


def build_shkp_indicative_sales_model_validation(
    monthly: pd.DataFrame,
    disclosed_facts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Compare the activity proxy with disclosed SHKP benchmarks.

    The comparison deliberately reports ratios and scope labels instead of an
    ``accuracy`` score.  Project contract activity is not the same event as
    property-sales revenue, and the disclosed backlog/contracted-sales facts
    have different timing and coverage definitions.
    """
    fiscal = _build_fiscal_annual(monthly)
    if fiscal.empty:
        return pd.DataFrame()
    facts = disclosed_facts.copy() if disclosed_facts is not None else build_shkp_disclosed_financial_facts()
    if facts.empty:
        facts = pd.DataFrame()
    rows: list[dict[str, Any]] = []

    revenue_by_year: dict[int, dict[str, Any]] = {}
    expected_by_year: dict[int, dict[str, Any]] = {}
    interim_by_year: dict[int, dict[str, Any]] = {}
    if not facts.empty and {"metric", "value", "period_end"}.issubset(facts.columns):
        revenue = facts[facts["metric"].eq("property_sales_revenue_including_jv_associates")].copy()
        for record in revenue.to_dict("records"):
            year = _fiscal_end_for_period(record.get("period_end"))
            if year is not None:
                revenue_by_year[year] = record
        expected = facts[facts["metric"].eq("hk_contract_sales_expected_recognition")].copy()
        for record in expected.to_dict("records"):
            year = _fiscal_end_for_period(record.get("target_period_end"))
            if year is not None:
                expected_by_year[year] = record
        interim = facts[facts["metric"].eq("contracted_sales_hk_period")].copy()
        for record in interim.to_dict("records"):
            year = _fiscal_end_for_period(record.get("period_start") or record.get("period_end"))
            if year is not None:
                interim_by_year[year] = record

    monthly_frame = monthly.copy()
    monthly_frame["period"] = pd.to_datetime(monthly_frame["period"], errors="coerce")
    for record in fiscal.to_dict("records"):
        fiscal_year = int(record["fiscal_year_end"])
        revenue = revenue_by_year.get(fiscal_year, {})
        expected = expected_by_year.get(fiscal_year, {})
        interim = interim_by_year.get(fiscal_year, {})
        revenue_value = pd.to_numeric(pd.Series([revenue.get("value")]), errors="coerce").iloc[0] * 1_000_000 if revenue else np.nan
        expected_value = pd.to_numeric(pd.Series([expected.get("value")]), errors="coerce").iloc[0] * 1_000_000 if expected else np.nan
        interim_value = pd.to_numeric(pd.Series([interim.get("value")]), errors="coerce").iloc[0] * 1_000_000 if interim else np.nan
        model_interim_value = np.nan
        model_interim_months = 0
        if interim:
            start = pd.to_datetime(interim.get("period_start"), errors="coerce")
            end = pd.to_datetime(interim.get("period_end"), errors="coerce")
            if pd.notna(start) and pd.notna(end):
                window = monthly_frame[monthly_frame["period"].between(start, end)]
                model_interim_value = window["estimated_total_base_sales_value_hkd"].sum(min_count=1)
                model_interim_months = int(len(window))
        rows.append(
            {
                "fiscal_year_end": fiscal_year,
                "fiscal_label": f"FY{fiscal_year - 1}/{str(fiscal_year)[-2:]}",
                "model_months_present": int(record["months_present"]),
                "model_partial_year": bool(record["is_partial_year"]),
                "model_low_contract_activity_hkd": float(record["estimated_total_low_sales_value_hkd"]),
                "model_base_contract_activity_hkd": float(record["estimated_total_base_sales_value_hkd"]),
                "model_high_contract_activity_hkd": float(record["estimated_total_high_sales_value_hkd"]),
                "disclosed_property_sales_revenue_hkd": revenue_value,
                "model_base_vs_property_revenue_ratio_pct": _ratio_pct(record["estimated_total_base_sales_value_hkd"], revenue_value),
                "model_base_minus_property_revenue_hkd": (
                    float(record["estimated_total_base_sales_value_hkd"] - revenue_value)
                    if pd.notna(revenue_value)
                    else np.nan
                ),
                "disclosed_hk_expected_recognition_hkd": expected_value,
                "model_base_vs_expected_recognition_ratio_pct": _ratio_pct(record["estimated_total_base_sales_value_hkd"], expected_value),
                "disclosed_hk_contracted_sales_period_hkd": interim_value,
                "model_same_period_base_contract_activity_hkd": model_interim_value,
                "model_same_period_months": model_interim_months,
                "model_same_period_vs_disclosed_ratio_pct": _ratio_pct(model_interim_value, interim_value),
                "revenue_source_url": revenue.get("source_url"),
                "expected_recognition_source_url": expected.get("source_url"),
                "interim_contract_source_url": interim.get("source_url"),
                "comparison_status": (
                    "directional_proxy_not_accuracy"
                    if revenue or expected or interim
                    else "no_disclosed_benchmark"
                ),
                "caveat": (
                    "Project contract activity and recognized property-sales revenue differ in timing, geography, "
                    "JV scope and phase coverage; ratios are diagnostics, not accuracy scores."
                ),
                "research_only": True,
            }
        )
    return pd.DataFrame(rows)


def build_shkp_indicative_sales_model_quarterly_reconciliation(
    monthly: pd.DataFrame,
    quarterly_facts: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Reconcile model activity to issuer-reported attributable sales periods.

    SHKP does not publish a complete calendar-quarter contracted-sales series.
    The official Quarterly results articles do publish annual and six-month
    attributable totals. This output therefore keeps the model at monthly
    grain, sums it only over each issuer-reported interval, and explicitly
    labels the comparison period. Missing issuer anchors remain visible rather
    than being backfilled or split into artificial quarters.
    """
    if monthly is None or monthly.empty:
        return pd.DataFrame()
    frame = monthly.copy()
    frame["period"] = pd.to_datetime(frame["period"], errors="coerce")
    frame = frame[frame["period"].notna()].copy()
    if frame.empty:
        return pd.DataFrame()
    frame["quarter_start"] = frame["period"].dt.to_period("Q").dt.start_time
    frame["quarter_end"] = frame["period"].dt.to_period("Q").dt.end_time.dt.normalize()
    quarter_model = frame.groupby(["quarter_start", "quarter_end"], as_index=False).agg(
        model_months_present=("period", "nunique"),
        model_base_sales_value_hkd=("estimated_total_base_sales_value_hkd", "sum"),
        model_low_sales_value_hkd=("estimated_total_low_sales_value_hkd", "sum"),
        model_high_sales_value_hkd=("estimated_total_high_sales_value_hkd", "sum"),
        model_base_sales_units=("estimated_total_base_sales_units", "sum"),
    )

    facts = quarterly_facts.copy() if quarterly_facts is not None else pd.DataFrame()
    if facts.empty or "fact_type" not in facts.columns:
        quarter_model["reported_period_start"] = pd.NaT
        quarter_model["reported_period_end"] = pd.NaT
        quarter_model["reported_period_type"] = None
        quarter_model["reported_sales_scope"] = None
        quarter_model["reported_contract_sales_hkd"] = np.nan
        quarter_model["model_base_same_reported_period_hkd"] = np.nan
        quarter_model["model_vs_reported_ratio_pct"] = np.nan
        quarter_model["comparison_status"] = "reported_contract_sales_not_available"
        quarter_model["reported_source_count"] = 0
        quarter_model["excluded_non_hk_anchor_count"] = 0
        quarter_model["reported_source_urls_json"] = "[]"
        quarter_model["model_use"] = "quarterly_reconciliation_diagnostic"
        quarter_model["research_only"] = True
        quarter_model["caveat"] = (
            "No issuer-reported attributable contracted-sales anchor was available for this calendar quarter; "
            "the row is model-only and is not treated as a zero reported value."
        )
        return quarter_model

    facts = facts.loc[facts["fact_type"].eq("contracted_sales_attributable_hkd_m")].copy()
    non_hk_anchor_count = 0
    if "sales_scope" not in facts.columns:
        facts["sales_scope"] = "legacy_unspecified"
    non_hk_anchor_count = int(facts["sales_scope"].ne("hong_kong").sum())
    facts = facts.loc[facts["sales_scope"].eq("hong_kong")].copy()
    facts["reported_period_start"] = pd.to_datetime(facts.get("reporting_period_start"), errors="coerce")
    facts["reported_period_end"] = pd.to_datetime(facts.get("reporting_period_end"), errors="coerce")
    facts["value_hkd"] = pd.to_numeric(facts.get("value"), errors="coerce")
    facts = facts.dropna(subset=["reported_period_start", "reported_period_end", "value_hkd"])
    # Duplicate bilingual/page rows should not multiply an issuer anchor.
    dedupe_columns = ["reported_period_start", "reported_period_end", "value_hkd"]
    if "fact_id" in facts.columns:
        facts = facts.drop_duplicates(subset=dedupe_columns + ["fact_id"])
    facts = facts.drop_duplicates(subset=dedupe_columns).copy()
    if facts.empty:
        result = build_shkp_indicative_sales_model_quarterly_reconciliation(monthly, None)
        result["excluded_non_hk_anchor_count"] = non_hk_anchor_count
        result["reported_sales_scope"] = None
        result["caveat"] = result["caveat"].astype(str) + (
            " Explicitly scoped-out group-total or otherwise unspecified issuer anchors are not used for the HK model."
        )
        return result

    rows: list[dict[str, Any]] = []
    for (period_start, period_end), group in facts.groupby(
        ["reported_period_start", "reported_period_end"], sort=True
    ):
        interval = frame[frame["period"].between(period_start, period_end)]
        reported_hkd = float(group["value_hkd"].sum() * 1_000_000.0)
        model_base = float(interval["estimated_total_base_sales_value_hkd"].sum()) if not interval.empty else np.nan
        model_low = float(interval["estimated_total_low_sales_value_hkd"].sum()) if not interval.empty else np.nan
        model_high = float(interval["estimated_total_high_sales_value_hkd"].sum()) if not interval.empty else np.nan
        model_units = float(interval["estimated_total_base_sales_units"].sum()) if not interval.empty else np.nan
        ratio = (model_base / reported_hkd * 100.0) if pd.notna(model_base) and reported_hkd else np.nan
        urls = []
        if "source_url" in group.columns:
            urls = sorted({str(value) for value in group["source_url"].dropna() if str(value).strip()})
        period_types = group.get("reporting_period_type", pd.Series(dtype=object)).dropna().astype(str).unique().tolist()
        rows.append({
            "reported_period_start": period_start,
            "reported_period_end": period_end,
            "reported_period_type": period_types[0] if period_types else "unknown",
            "reported_sales_scope": "hong_kong",
            "model_calendar_quarters": int(interval["quarter_end"].nunique()) if not interval.empty else 0,
            "model_months_present": int(interval["period"].nunique()) if not interval.empty else 0,
            "model_low_sales_value_hkd": model_low,
            "model_base_same_reported_period_hkd": model_base,
            "model_high_sales_value_hkd": model_high,
            "model_base_sales_units": model_units,
            "reported_contract_sales_hkd": reported_hkd,
            "model_vs_reported_ratio_pct": ratio,
            "reported_source_count": int(len(group)),
            "excluded_non_hk_anchor_count": non_hk_anchor_count,
            "reported_source_urls_json": json.dumps(urls, ensure_ascii=False),
            "comparison_status": "matched_reported_interval" if not interval.empty else "reported_interval_outside_model",
            "model_use": "quarterly_reconciliation_diagnostic",
            "research_only": True,
            "caveat": (
                "Issuer anchor is annual/interim attributable contracted sales, not a true calendar-quarter series. "
                "Model activity is gross SRPE contract proxy; ratio is a scope/timing diagnostic, not accuracy."
            ),
        })
    return pd.DataFrame(rows).sort_values("reported_period_end").reset_index(drop=True)


def build_shkp_indicative_sales_model_historical_reconciliation(
    monthly: pd.DataFrame,
    *,
    disclosed_facts: pd.DataFrame | None = None,
    quarterly_facts: pd.DataFrame | None = None,
    signals: pd.DataFrame | None = None,
    hk_segment_history: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build a multi-year reconciliation panel across both anchor scopes.

    SHKP discloses two families of Hong Kong property-sales anchors:

    * ``property_sales_revenue_including_jv_associates`` (segment revenue,
      annual, FY2020/21 onward in the current five-year summary) - a
      recognized-revenue benchmark with a recognition lag versus contract
      activity;
    * ``contracted_sales_attributable_hkd_m`` (issuer Quarterly results
      articles, annual/interim intervals, HK scope) - a contract-flow
      benchmark that is much closer to the SRPE activity proxy.

    The panel is deliberately airlines-backtest shaped: one row per anchor
    interval, model low/base/high totals alongside the reported value, the
    ratio, coverage diagnostics (months present, covered phase count, grid
    coverage), source/availability metadata, and an explicit scope label so
    the two anchor families are never silently mixed.
    """
    if monthly is None or monthly.empty:
        return pd.DataFrame()
    frame = monthly.copy()
    frame["period"] = pd.to_datetime(frame["period"], errors="coerce")
    frame = frame[frame["period"].notna()].copy()
    if frame.empty:
        return pd.DataFrame()
    if signals is not None and not signals.empty and "phase_id" in signals.columns:
        total_phases = int(signals["phase_id"].nunique())
    else:
        total_phases = 0

    facts = disclosed_facts.copy() if disclosed_facts is not None else pd.DataFrame()
    quarters = quarterly_facts.copy() if quarterly_facts is not None else pd.DataFrame()
    rows: list[dict[str, Any]] = []

    revenue_rows: list[dict[str, Any]] = []
    hk_segment = (
        hk_segment_history.copy()
        if hk_segment_history is not None and not hk_segment_history.empty
        else pd.DataFrame()
    )
    if not hk_segment.empty and {"period_start", "period_end", "revenue_hkd"}.issubset(hk_segment.columns):
        for record in hk_segment.to_dict("records"):
            value_hkd = pd.to_numeric(pd.Series([record.get("revenue_hkd")]), errors="coerce").iloc[0]
            start = pd.to_datetime(record.get("period_start"), errors="coerce")
            end = pd.to_datetime(record.get("period_end"), errors="coerce")
            if pd.isna(value_hkd) or pd.isna(start) or pd.isna(end):
                continue
            revenue_rows.append(
                {
                    "anchor_scope": "property_sales_revenue_hong_kong_combined",
                    "reported_period_start": start,
                    "reported_period_end": end,
                    "reported_period_type": "annual",
                    "reported_value_hkd": float(value_hkd),
                    "available_at": str(record.get("fiscal_year_end") or "") + "-09-30",
                    "source_url": "https://www.shkp.com/en-US/investor-relations/financial-reports",
                    "source_label": "annual report segment information note",
                    "caveat": str(record.get("caveat") or ""),
                }
            )
    elif not facts.empty and {"metric", "value", "period_start", "period_end"}.issubset(facts.columns):
        # Legacy fallback: the five-year summary property-sales line is
        # all-region (HK + Mainland + Singapore); keep it visible but clearly
        # labelled so it is never silently mixed with the HK-only anchor.
        revenue = facts.loc[facts["metric"].eq("property_sales_revenue_including_jv_associates")].copy()
        for record in revenue.to_dict("records"):
            value_hkd = pd.to_numeric(pd.Series([record.get("value")]), errors="coerce").iloc[0]
            start = pd.to_datetime(record.get("period_start"), errors="coerce")
            end = pd.to_datetime(record.get("period_end"), errors="coerce")
            if pd.isna(value_hkd) or pd.isna(start) or pd.isna(end):
                continue
            revenue_rows.append(
                {
                    "anchor_scope": "property_sales_revenue_all_regions_legacy_summary",
                    "reported_period_start": start,
                    "reported_period_end": end,
                    "reported_period_type": str(record.get("period_type") or "annual"),
                    "reported_value_hkd": float(value_hkd) * 1_000_000.0,
                    "available_at": record.get("available_at"),
                    "source_url": record.get("source_url"),
                    "source_label": record.get("source_label"),
                    "caveat": str(record.get("caveat") or ""),
                }
            )

    contract_rows: list[dict[str, Any]] = []
    if not quarters.empty and {"fact_type", "value", "reporting_period_start", "reporting_period_end", "sales_scope"}.issubset(quarters.columns):
        contract = quarters.loc[quarters["fact_type"].eq("contracted_sales_attributable_hkd_m")].copy()
        contract = contract.loc[contract["sales_scope"].eq("hong_kong")].copy()
        for record in contract.to_dict("records"):
            value_hkd = pd.to_numeric(pd.Series([record.get("value")]), errors="coerce").iloc[0]
            start = pd.to_datetime(record.get("reporting_period_start"), errors="coerce")
            end = pd.to_datetime(record.get("reporting_period_end"), errors="coerce")
            if pd.isna(value_hkd) or pd.isna(start) or pd.isna(end):
                continue
            contract_rows.append(
                {
                    "anchor_scope": "contracted_sales_attributable_hong_kong",
                    "reported_period_start": start,
                    "reported_period_end": end,
                    "reported_period_type": str(record.get("reporting_period_type") or "unknown"),
                    "reported_value_hkd": float(value_hkd) * 1_000_000.0,
                    "available_at": record.get("available_at"),
                    "source_url": record.get("source_url"),
                    "source_label": record.get("source_label"),
                    "caveat": str(record.get("caveat") or ""),
                }
            )

    anchors = [*revenue_rows, *contract_rows]
    anchors.sort(key=lambda row: (row["reported_period_start"], row["anchor_scope"]))
    for anchor in anchors:
        start = anchor["reported_period_start"]
        end = anchor["reported_period_end"]
        interval = frame[frame["period"].between(start, end)]
        months_present = int(interval["period"].nunique())
        if signals is not None and not signals.empty and "phase_id" in signals.columns:
            signal_window = signals.copy()
            signal_window["period"] = pd.to_datetime(signal_window["period"], errors="coerce")
            signal_window = signal_window[signal_window["period"].between(start, end)]
            covered_phases = int(signal_window["phase_id"].nunique())
            grid_coverage_ratio = float(covered_phases) / float(total_phases) if total_phases else float("nan")
        else:
            covered_phases = int(interval["covered_phase_count"].sum()) if "covered_phase_count" in interval.columns else 0
            grid_coverage_ratio = float("nan")
        model_low = float(interval["estimated_total_low_sales_value_hkd"].sum()) if not interval.empty else 0.0
        model_base = float(interval["estimated_total_base_sales_value_hkd"].sum()) if not interval.empty else 0.0
        model_high = float(interval["estimated_total_high_sales_value_hkd"].sum()) if not interval.empty else 0.0
        model_units = float(interval["estimated_total_base_sales_units"].sum()) if not interval.empty else 0.0
        reported = float(anchor["reported_value_hkd"])
        is_revenue_scope = anchor["anchor_scope"] == "property_sales_revenue_hong_kong_combined"
        comparison_validity = (
            "same_timing_contract_scope"
            if anchor["anchor_scope"] == "contracted_sales_attributable_hong_kong"
            else "recognition_lag_not_applicable" if is_revenue_scope else "diagnostic_only"
        )
        caveat_text = str(anchor["caveat"] or "")
        if is_revenue_scope:
            caveat_text = (
                caveat_text
                + " Model activity is contract-flow (PASP signing date) while the issuer anchor is "
                "recognized revenue (handover date); HK presales typically confirm 2-3 years after signing, "
                "so an over-100% ratio is expected in years with large recent launches and is NOT a "
                "double-counting error. Use the contracted-sales scope for same-timing validation."
            )
        rows.append(
            {
                "reported_period_start": start,
                "reported_period_end": end,
                "reported_period_type": anchor["reported_period_type"],
                "anchor_scope": anchor["anchor_scope"],
                "model_low_sales_value_hkd": model_low,
                "model_base_sales_value_hkd": model_base,
                "model_high_sales_value_hkd": model_high,
                "model_base_sales_units": model_units,
                "reported_sales_value_hkd": reported,
                "model_base_vs_reported_ratio_pct": _ratio_pct(model_base, reported),
                "model_months_present": months_present,
                "model_expected_months": int((end - start).days / 30.44) + 1,
                "model_covered_phase_count": covered_phases,
                "model_total_phase_count": total_phases,
                "model_grid_coverage_ratio": grid_coverage_ratio,
                "comparison_validity": comparison_validity,
                "available_at": anchor["available_at"],
                "source_url": anchor["source_url"],
                "source_label": anchor["source_label"],
                "comparison_status": "matched_reported_interval" if months_present else "reported_interval_outside_model",
                "model_use": "historical_reconciliation_diagnostic",
                "research_only": True,
                "caveat": caveat_text or (
                    "Issuer anchor is annual/interim segment revenue or attributable contracted sales; "
                    "model activity is a gross SRPE contract proxy. Ratio is a scope/timing diagnostic, not accuracy."
                ),
            }
        )
    return pd.DataFrame(rows).sort_values(["reported_period_start", "anchor_scope"]).reset_index(drop=True)


def build_shkp_indicative_sales_model_forecast(
    monthly: pd.DataFrame,
    *,
    disclosed_facts: pd.DataFrame | None = None,
    growth_window: int = DEFAULT_FORECAST_GROWTH_WINDOW,
    jv_scenario_shares: Mapping[str, float] | None = None,
    min_coverage_ratio: float = 0.75,
) -> pd.DataFrame:
    """Build a mechanical next-fiscal-year run-rate/growth sensitivity.

    The forecast starts from the latest *complete* July-to-June model year,
    avoiding the known publication lag in the newest monthly registers.  Low,
    base and high growth assumptions are the 25th/50th/75th percentiles of the
    latest full-year base-model growth observations.  Ownership and growth are
    kept as separate dimensions, producing nine transparent combinations.
    """
    if not 0.0 <= float(min_coverage_ratio) <= 1.0:
        raise ValueError("min_coverage_ratio must be between 0 and 1")
    fiscal = _build_fiscal_annual(monthly)
    complete = fiscal[
        fiscal["months_present"].eq(12)
        & (
            fiscal["min_monthly_coverage_ratio"].isna()
            | fiscal["min_monthly_coverage_ratio"].ge(float(min_coverage_ratio))
        )
    ].copy()
    if complete.empty:
        return pd.DataFrame()
    if growth_window < 2:
        raise ValueError("growth_window must be at least 2")
    complete["base_growth_pct"] = complete["estimated_total_base_sales_value_hkd"].pct_change() * 100.0
    growth_observations = complete["base_growth_pct"].dropna().tail(growth_window)
    if growth_observations.empty:
        return pd.DataFrame()
    growth_assumptions = {
        "low": float(growth_observations.quantile(0.25)),
        "base": float(growth_observations.quantile(0.50)),
        "high": float(growth_observations.quantile(0.75)),
    }
    growth_years = complete.loc[complete["base_growth_pct"].notna(), "fiscal_year_end"].tail(growth_window)
    latest = complete.sort_values("fiscal_year_end").iloc[-1]
    latest_fiscal_end = int(latest["fiscal_year_end"])
    target_fiscal_end = latest_fiscal_end + 1
    shares = _validate_scenario_shares(jv_scenario_shares)
    pipeline_facts = disclosed_facts.copy() if disclosed_facts is not None else build_shkp_disclosed_financial_facts()

    def _pipeline_value(metric: str) -> float | None:
        if pipeline_facts.empty or "metric" not in pipeline_facts.columns:
            return None
        values = pd.to_numeric(
            pipeline_facts.loc[pipeline_facts["metric"].eq(metric), "value"],
            errors="coerce",
        ).dropna()
        return float(values.iloc[-1]) if not values.empty else None

    rows: list[dict[str, Any]] = []
    for ownership_scenario, share in shares.items():
        current_numeric = float(latest["numeric_stake_sales_value_hkd"])
        current_jv_gross = float(latest["jv_gross_sales_value_hkd"])
        for growth_scenario, growth_pct in growth_assumptions.items():
            multiplier = 1.0 + growth_pct / 100.0
            numeric_forecast = current_numeric * multiplier
            jv_gross_forecast = current_jv_gross * multiplier
            jv_estimated_forecast = jv_gross_forecast * share
            rows.append(
                {
                    "forecast_fiscal_year_end": target_fiscal_end,
                    "forecast_fiscal_label": f"FY{target_fiscal_end - 1}/{str(target_fiscal_end)[-2:]}",
                    "latest_complete_fiscal_year_end": latest_fiscal_end,
                    "ownership_scenario": ownership_scenario,
                    "jv_assumed_share_pct": share * 100.0,
                    "growth_scenario": growth_scenario,
                    "growth_assumption_pct": growth_pct,
                    "growth_observation_count": int(len(growth_observations)),
                    "growth_observation_start_fiscal_year_end": int(growth_years.iloc[0]),
                    "min_monthly_coverage_ratio": (
                        float(latest["min_monthly_coverage_ratio"])
                        if pd.notna(latest.get("min_monthly_coverage_ratio"))
                        else None
                    ),
                    "min_covered_phase_count": (
                        int(latest["min_covered_phase_count"])
                        if pd.notna(latest.get("min_covered_phase_count"))
                        else None
                    ),
                    "max_not_covered_phase_count": (
                        int(latest["max_not_covered_phase_count"])
                        if pd.notna(latest.get("max_not_covered_phase_count"))
                        else None
                    ),
                    "coverage_threshold_used": float(min_coverage_ratio),
                    "coverage_quality_status": str(latest.get("coverage_quality_status") or "unknown"),
                    "latest_complete_numeric_stake_sales_hkd": current_numeric,
                    "latest_complete_jv_gross_sales_hkd": current_jv_gross,
                    "forecast_numeric_stake_sales_hkd": numeric_forecast,
                    "forecast_jv_gross_sales_hkd": jv_gross_forecast,
                    "forecast_jv_estimated_sales_hkd": jv_estimated_forecast,
                    "forecast_total_sales_hkd": numeric_forecast + jv_estimated_forecast,
                    "disclosed_planned_launch_project_count": _pipeline_value("planned_launch_project_count"),
                    "disclosed_under_development_project_count": _pipeline_value("northern_metropolis_projects_under_development"),
                    "disclosed_northern_metropolis_planned_units": _pipeline_value("northern_metropolis_planned_units"),
                    "disclosed_kwu_tung_planned_units": _pipeline_value("kwu_tung_project_planned_units"),
                    "forecast_method": "latest_complete_fiscal_run_rate_times_recent_full_year_growth_quantile",
                    "model_use": "rough_research_forecast_only",
                    "research_only": True,
                    "caveat": (
                        "Mechanical sensitivity, not management guidance or consensus. It excludes unlinked future "
                        "projects from the numeric formula; disclosed pipeline counts are context only. Latest SRPE "
                        "registers can lag current sales, and contract activity is not recognized revenue. Fiscal "
                        f"years with observed coverage below {float(min_coverage_ratio) * 100:.0f}% are excluded "
                        "from the growth calibration; missing coverage is not treated as zero sales."
                    ),
                }
            )
    return pd.DataFrame(rows)


def build_shkp_indicative_sales_model_backtest(
    monthly: pd.DataFrame,
    *,
    lookback_months: int = DEFAULT_BACKTEST_LOOKBACK_MONTHS,
    universe_phase_count: int | None = None,
) -> pd.DataFrame:
    """Run a conservative one-step monthly holdout on the activity proxy.

    The backtest is deliberately descriptive rather than an investable forecast
    test.  A target month is scored only when its preceding ``lookback_months``
    rows are calendar-contiguous; missing months are not filled with zero. Two
    transparent baselines are emitted for each low/base/high JV scenario:
    trailing-mean and same-month-last-year.  Coverage fields travel with every
    row so an apparent error change cannot be mistaken for a pure model change.
    ``universe_phase_count`` (when supplied) adds a second coverage column that
    divides covered phases by the FULL known SHKP universe, exposing how much
    of the universe the model grid actually covers in early years.
    """
    if monthly is None or monthly.empty:
        return pd.DataFrame()
    if lookback_months < 1:
        raise ValueError("lookback_months must be at least 1")
    required = {"period"}
    required.update({f"estimated_total_{scenario}_sales_value_hkd" for scenario in _SCENARIOS})
    missing = sorted(required - set(monthly.columns))
    if missing:
        raise ValueError("monthly model is missing backtest columns: " + ", ".join(missing))
    frame = monthly.copy()
    for column in ("covered_phase_count", "not_covered_phase_count", "unknown_phase_count"):
        if column not in frame.columns:
            frame[column] = 0
    frame["period"] = pd.to_datetime(frame["period"], errors="coerce").dt.to_period("M").dt.to_timestamp()
    frame = frame[frame["period"].notna()].sort_values("period").reset_index(drop=True)
    if frame.empty:
        return pd.DataFrame()
    if frame["period"].duplicated().any():
        raise ValueError("monthly model must have one row per period for backtest")
    period_to_index = {period: index for index, period in enumerate(frame["period"])}
    rows: list[dict[str, Any]] = []

    def _contiguous(periods: pd.Series) -> bool:
        if len(periods) <= 1:
            return True
        ordinals = periods.dt.year * 12 + periods.dt.month
        return bool(ordinals.diff().dropna().eq(1).all())

    for target_index, target in frame.iterrows():
        target_period = target["period"]
        history = frame.iloc[max(0, target_index - lookback_months):target_index]
        enough_history = len(history) == lookback_months
        target_follows_history = (
            enough_history
            and not history.empty
            and target_period == history["period"].iloc[-1] + pd.offsets.MonthBegin(1)
        )
        contiguous_history = enough_history and target_follows_history and _contiguous(history["period"])
        prior_period = target_period - pd.DateOffset(years=1)
        prior_index = period_to_index.get(prior_period)
        same_year_available = prior_index is not None
        same_year_contiguous = False
        if same_year_available:
            span = frame.iloc[min(prior_index, target_index):max(prior_index, target_index) + 1]
            same_year_contiguous = _contiguous(span["period"])
        coverage_denominator = pd.to_numeric(
            pd.Series([target.get("covered_phase_count", 0), target.get("not_covered_phase_count", 0)]),
            errors="coerce",
        ).sum()
        coverage_ratio = (
            float(pd.to_numeric(pd.Series([target.get("covered_phase_count")]), errors="coerce").iloc[0] / coverage_denominator)
            if pd.notna(coverage_denominator) and coverage_denominator > 0
            else None
        )
        universe_coverage_ratio = (
            float(pd.to_numeric(pd.Series([target.get("covered_phase_count")]), errors="coerce").iloc[0] / universe_phase_count)
            if universe_phase_count and pd.notna(target.get("covered_phase_count"))
            else None
        )
        for scenario in _SCENARIOS:
            metric_column = f"estimated_total_{scenario}_sales_value_hkd"
            actual = pd.to_numeric(pd.Series([target.get(metric_column)]), errors="coerce").iloc[0]
            forecasts = {
                "trailing_mean": (
                    pd.to_numeric(history[metric_column], errors="coerce").mean()
                    if contiguous_history
                    else np.nan
                ),
                "same_month_last_year": (
                    pd.to_numeric(pd.Series([frame.iloc[prior_index].get(metric_column)]), errors="coerce").iloc[0]
                    if same_year_available and same_year_contiguous
                    else np.nan
                ),
            }
            for method, forecast_value in forecasts.items():
                valid = pd.notna(actual) and pd.notna(forecast_value)
                error = float(forecast_value - actual) if valid else np.nan
                abs_error = abs(error) if valid else np.nan
                abs_pct_error = (
                    float(abs_error / abs(actual) * 100.0)
                    if valid and actual != 0
                    else np.nan
                )
                previous_actual = (
                    pd.to_numeric(pd.Series([frame.iloc[target_index - 1].get(metric_column)]), errors="coerce").iloc[0]
                    if target_index > 0
                    else np.nan
                )
                direction_hit = (
                    bool(np.sign(float(forecast_value - previous_actual)) == np.sign(float(actual - previous_actual)))
                    if valid and pd.notna(previous_actual) and actual != previous_actual and forecast_value != previous_actual
                    else None
                )
                rows.append(
                    {
                        "target_period": target_period.strftime("%Y-%m-%d"),
                        "scenario": scenario,
                        "forecast_method": method,
                        "lookback_months": int(lookback_months),
                        "training_period_start": history["period"].min().strftime("%Y-%m-%d") if not history.empty else None,
                        "training_period_end": history["period"].max().strftime("%Y-%m-%d") if not history.empty else None,
                        "history_rows": int(len(history)),
                        "history_contiguous": bool(contiguous_history),
                        "same_month_last_year_available": bool(same_year_available and same_year_contiguous),
                        "forecast_value_hkd": float(forecast_value) if pd.notna(forecast_value) else np.nan,
                        "actual_value_hkd": float(actual) if pd.notna(actual) else np.nan,
                        "error_hkd": error,
                        "absolute_error_hkd": abs_error,
                        "absolute_percentage_error": abs_pct_error,
                        "direction_hit": direction_hit,
                        "backtest_status": "valid_one_step_holdout" if valid else "insufficient_contiguous_history",
                        "covered_phase_count": int(pd.to_numeric(pd.Series([target.get("covered_phase_count")]), errors="coerce").fillna(0).iloc[0]),
                        "not_covered_phase_count": int(pd.to_numeric(pd.Series([target.get("not_covered_phase_count")]), errors="coerce").fillna(0).iloc[0]),
                        "unknown_phase_count": int(pd.to_numeric(pd.Series([target.get("unknown_phase_count")]), errors="coerce").fillna(0).iloc[0]),
                        "model_grid_coverage_ratio": coverage_ratio,
                        "universe_coverage_ratio": universe_coverage_ratio,
                        "model_use": "rough_one_step_holdout_backtest",
                        "research_only": True,
                        "caveat": (
                            "Descriptive holdout on observed indicative contract activity only. Missing months are not zero-filled; "
                            "coverage ratio is a model-grid diagnostic and does not impute omitted SHKP phases."
                        ),
                    }
                )
    return pd.DataFrame(rows)


def build_shkp_active_future_project_coverage(
    *,
    property_catalog: pd.DataFrame,
    crosswalk: pd.DataFrame,
    phase_candidates: pd.DataFrame,
    current_manifest: pd.DataFrame,
    pipeline_disclosures: pd.DataFrame,
    pipeline_resolution: pd.DataFrame,
    future_identity_evidence: pd.DataFrame,
    indicative_signals: pd.DataFrame,
) -> pd.DataFrame:
    """Audit current-listing and future-pipeline coverage separately.

    A current website listing can have a complete SRPE document/register
    route while still being an ambiguous ownership/phase match.  Future
    disclosure labels often have a lot number but no SRPE phase yet.  This
    summary preserves those distinctions rather than reporting one misleading
    project-coverage percentage.
    """
    catalog = property_catalog.copy() if property_catalog is not None else pd.DataFrame()
    current = catalog[catalog.get("asset_type", pd.Series(dtype=str)).eq("residential_for_sale")].copy()
    xwalk = crosswalk.copy() if crosswalk is not None else pd.DataFrame()
    candidates = phase_candidates.copy() if phase_candidates is not None else pd.DataFrame()
    manifest = current_manifest.copy() if current_manifest is not None else pd.DataFrame()
    signals = indicative_signals.copy() if indicative_signals is not None else pd.DataFrame()
    planned = pipeline_disclosures.copy() if pipeline_disclosures is not None else pd.DataFrame()
    resolution = pipeline_resolution.copy() if pipeline_resolution is not None else pd.DataFrame()
    future_identity = future_identity_evidence.copy() if future_identity_evidence is not None else pd.DataFrame()

    xwalk_phase_ids = set(xwalk.get("srpe_development_id", pd.Series(dtype=str)).dropna().astype(str))
    manifest_phase_ids = set(manifest.get("srpe_development_id", pd.Series(dtype=str)).dropna().astype(str))
    signal_phase_ids = set(signals.get("srpe_development_id", pd.Series(dtype=str)).dropna().astype(str))
    candidate_phase_ids = set(candidates.get("srpe_development_id", pd.Series(dtype=str)).dropna().astype(str))
    current_rows = {
        "coverage_scope": "current_shkp_website_residential_for_sale",
        "source_rows": int(len(current)),
        "unique_project_or_listing_rows": int(current.get("marketing_name", pd.Series(dtype=str)).nunique()),
        "unique_srpe_phase_candidates": int(len(xwalk_phase_ids)),
        "exact_match_rows": int(xwalk.get("match_status", pd.Series(dtype=str)).eq("matched").sum()),
        "review_match_rows": int(xwalk.get("match_status", pd.Series(dtype=str)).eq("matched_needs_review").sum()),
        "ambiguous_match_rows": int(xwalk.get("match_status", pd.Series(dtype=str)).eq("ambiguous").sum()),
        "exact_match_listing_rows": int(
            xwalk.loc[xwalk.get("match_status", pd.Series(dtype=str)).eq("matched"), "marketing_name"].nunique()
        ) if "marketing_name" in xwalk.columns else 0,
        "review_match_listing_rows": int(
            xwalk.loc[xwalk.get("match_status", pd.Series(dtype=str)).eq("matched_needs_review"), "marketing_name"].nunique()
        ) if "marketing_name" in xwalk.columns else 0,
        "ambiguous_match_listing_rows": int(
            xwalk.loc[xwalk.get("match_status", pd.Series(dtype=str)).eq("ambiguous"), "marketing_name"].nunique()
        ) if "marketing_name" in xwalk.columns else 0,
        "candidate_phase_rows": int(len(candidate_phase_ids)),
        "current_manifest_phase_rows": int(len(manifest_phase_ids & xwalk_phase_ids)),
        "current_transaction_register_phase_rows": int(
                len(
                    set(
                        manifest.loc[
                            manifest.get("document_category", pd.Series(dtype=str)).eq("register_of_transactions"),
                            "srpe_development_id",
                        ].dropna().astype(str)
                    )
                    & xwalk_phase_ids
                )
        ) if "srpe_development_id" in manifest.columns else 0,
        "signal_phase_rows": int(len(signal_phase_ids & xwalk_phase_ids)),
        "strict_ready_phase_rows": int(
            signals.loc[
                signals.get("ownership_attribution_ready", pd.Series(False, index=signals.index)).fillna(False),
                "srpe_development_id",
            ].dropna().astype(str).nunique()
        ) if "srpe_development_id" in signals.columns else 0,
        "coverage_status": "broad_document_coverage_identity_partial",
        "caveat": (
            "The current SHKP residential-for-sale website is a live listing snapshot, not a complete historical "
            "developer universe. SRPE manifests/registers are broad for the routed candidates, but 17 exact, "
            "14 review candidate rows and 40 ambiguous candidate rows (spanning 12 listing names) remain separate "
            "identity states."
        ),
    }
    planned_mask = planned.get("status", pd.Series(dtype=str)).eq("planned_launch_10m")
    under_dev_mask = planned.get("status", pd.Series(dtype=str)).eq("under_development")
    linked_ids = set(resolution.get("linked_srpe_development_id", pd.Series(dtype=str)).dropna().astype(str))
    future_rows = {
        "coverage_scope": "shkp_disclosed_future_pipeline",
        "source_rows": int(len(planned)),
        "unique_project_or_listing_rows": int(planned.get("project_label", pd.Series(dtype=str)).nunique()),
        "planned_launch_rows": int(planned_mask.sum()),
        "under_development_rows": int(under_dev_mask.sum()),
        "resolution_rows": int(len(resolution)),
        "identity_evidence_rows": int(len(future_identity)),
        "identity_evidence_unique_labels": int(
            future_identity.get("project_label", pd.Series(dtype=str)).nunique()
        ),
        "identity_evidence_srpe_linked_rows": int(
            future_identity.get("srpe_development_id", pd.Series(dtype=str)).notna().sum()
        ),
        "identity_evidence_no_srpe_rows": int(
            future_identity.get("srpe_development_id", pd.Series(dtype=str)).isna().sum()
        ),
        "linked_srpe_phase_rows": int(len(linked_ids)),
        "srpe_manifest_phase_rows": int(len(linked_ids & manifest_phase_ids)),
        "signal_phase_rows": int(len(linked_ids & signal_phase_ids)),
        "identity_pending_no_srpe_rows": int(
            resolution.get("resolution_status", pd.Series(dtype=str)).eq("identity_lot_resolved_srpe_pending").sum()
        ),
        "multiple_candidate_rows": int(
            resolution.get("resolution_status", pd.Series(dtype=str)).eq("unresolved_multiple_srpe_candidates").sum()
        ),
        "non_srpe_asset_rows": int(
            resolution.get("resolution_status", pd.Series(dtype=str)).eq("resolved_non_srpe_commercial_bot").sum()
        ),
        "coverage_status": "partial_identity_no_complete_future_transaction_coverage",
        "caveat": (
            "The six planned-launch labels and two under-development labels are disclosure-level anchors. "
            "Most future rows still require an SRPE phase/website/vendor route; the commercial BOT row is not a "
            "residential SRPE phase. No future label is counted as a sale until its phase and documents exist."
        ),
    }
    for row in (current_rows, future_rows):
        row["research_only"] = True
        row["strict_ownership_promotion"] = False
    return pd.DataFrame([current_rows, future_rows])


def build_shkp_indicative_sales_model_universe_coverage(
    high_recall_roster: pd.DataFrame,
    indicative_signals: pd.DataFrame,
    transaction_events: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Join the full SHKP/SRPE routing universe to model signal coverage.

    This is a phase-level coverage audit, not an ownership decision. It makes
    clear which likely/possible/unknown candidates have transaction events,
    which only have a document route, and which are not yet in the model.
    """
    roster = high_recall_roster.copy() if high_recall_roster is not None else pd.DataFrame()
    signals = indicative_signals.copy() if indicative_signals is not None else pd.DataFrame()
    if roster.empty or "srpe_development_id" not in roster.columns:
        return pd.DataFrame()
    roster["srpe_development_id"] = roster["srpe_development_id"].astype(str).str.strip()
    roster = roster[roster["srpe_development_id"].ne("")].drop_duplicates("srpe_development_id", keep="first").copy()
    if not signals.empty and "phase_id" in signals.columns:
        signal_frame = signals.copy()
        signal_frame["phase_id"] = signal_frame["phase_id"].astype(str).str.strip()
        signal_frame["period"] = pd.to_datetime(signal_frame.get("period"), errors="coerce")
        signal_summary = signal_frame.groupby("phase_id", as_index=False).agg(
            signal_rows=("phase_id", "size"),
            signal_first_period=("period", "min"),
            signal_last_period=("period", "max"),
            signal_gross_sales_value_hkd=("sales_value_gross_hkd", "sum"),
            signal_gross_sales_units=("sales_units_gross", "sum"),
            signal_attribution_status=("indicative_attribution_status", _mode_or_first),
        )
    else:
        signal_summary = pd.DataFrame(columns=["phase_id", "signal_rows"])
    event_summary = pd.DataFrame(columns=["phase_id", "transaction_event_rows"])
    if transaction_events is not None and not transaction_events.empty:
        events = transaction_events.copy()
        event_column = "srpe_development_id" if "srpe_development_id" in events.columns else "development_id"
        if event_column in events.columns:
            events["phase_id"] = events[event_column].astype(str).str.strip()
            event_summary = events.groupby("phase_id", as_index=False).size().rename(columns={"size": "transaction_event_rows"})
    result = roster.rename(columns={"srpe_development_id": "phase_id"}).merge(signal_summary, on="phase_id", how="left").merge(event_summary, on="phase_id", how="left")
    for column in ("signal_rows", "transaction_event_rows"):
        result[column] = pd.to_numeric(result.get(column), errors="coerce").fillna(0).astype(int)
    result["has_model_signal"] = result["signal_rows"].gt(0)
    result["has_transaction_events"] = result["transaction_event_rows"].gt(0)
    result["model_universe_status"] = np.select(
        [
            result["has_model_signal"] & result["candidate_status"].eq("likely_shkp"),
            result["has_model_signal"] & result["candidate_status"].eq("possible_shkp_high_recall"),
            result["has_model_signal"],
            result.get("transaction_route_status", pd.Series(index=result.index, dtype=object)).eq("transaction_register_available"),
        ],
        [
            "signal_included_likely_shkp",
            "signal_included_possible_shkp",
            "signal_included_identity_unknown_excluded_from_attribution",
            "transaction_route_available_signal_missing",
        ],
        default="roster_only_no_signal_or_route",
    )
    result["strict_ownership_promotion_status"] = "blocked_phase_specific_interval"
    result["sales_attribution_status"] = "not_promoted"
    result["model_use"] = "shkp_residential_universe_coverage_audit"
    result["research_only"] = True
    result["caveat"] = (
        "Full high-recall SHKP/SRPE phase routing universe joined to current all-history signals. "
        "candidate status and transaction route are discovery evidence, not legal ownership or SHKP sales attribution."
    )
    return result.sort_values(["model_universe_status", "phase_id"]).reset_index(drop=True)


def _phase_summary_base(frame: pd.DataFrame, shares: Mapping[str, float]) -> pd.DataFrame:
    covered = frame[frame["month_status"].ne(_NOT_COVERED)].copy()
    covered["_is_numeric"] = covered["indicative_attribution_status"].eq(_NUMERIC_STATUS)
    covered["_is_jv"] = covered["indicative_attribution_status"].eq(_JV_STATUS)
    covered["_is_unknown"] = ~covered["_is_numeric"] & ~covered["_is_jv"]
    rows: list[dict[str, Any]] = []
    for phase_id, group in covered.groupby("phase_id", sort=True):
        group = group.sort_values("period")
        numeric = group[group["_is_numeric"]]
        jv = group[group["_is_jv"]]
        unknown = group[group["_is_unknown"]]
        numeric_gross_value = _sum_or_zero(numeric["sales_value_gross_hkd"])
        numeric_gross_units = _sum_or_zero(numeric["sales_units_gross"])
        numeric_value = _sum_or_zero(numeric["indicative_sales_value_hkd"])
        numeric_units = _sum_or_zero(numeric["indicative_sales_units"])
        jv_value = _sum_or_zero(jv["sales_value_gross_hkd"])
        jv_units = _sum_or_zero(jv["sales_units_gross"])
        latest = group.iloc[-1]
        row: dict[str, Any] = {
            "phase_id": str(phase_id),
            "development_id": _first_non_null(group.get("development_id", pd.Series(dtype=object))),
            "development_name": _first_non_null(group.get("development_name", pd.Series(dtype=object))),
            "phase_name": _first_non_null(group.get("phase_name", pd.Series(dtype=object))),
            "first_period": group["period"].min().strftime("%Y-%m-%d"),
            "last_period": group["period"].max().strftime("%Y-%m-%d"),
            "months_covered": int(len(group)),
            "months_with_transactions": int(group["month_status"].eq("observed_transactions").sum()),
            "primary_attribution_status": _mode_or_first(group["indicative_attribution_status"], "not_observed"),
            "indicative_ownership_pct": _first_non_null(group.get("indicative_ownership_pct", pd.Series(dtype=float))),
            "indicative_ownership_pct_low": _first_non_null(group.get("indicative_ownership_pct_low", pd.Series(dtype=float))),
            "indicative_ownership_pct_high": _first_non_null(group.get("indicative_ownership_pct_high", pd.Series(dtype=float))),
            "indicative_numeric_consistency_status": _mode_or_first(
                group.get("indicative_numeric_consistency_status", pd.Series(dtype=object)),
                "not_observed",
            ),
            "indicative_confidence": _mode_or_first(group.get("indicative_confidence", pd.Series(dtype=object)), "none"),
            "numeric_gross_sales_value_hkd": numeric_gross_value,
            "numeric_gross_sales_units": numeric_gross_units,
            "numeric_stake_sales_value_hkd": numeric_value,
            "numeric_stake_sales_units": numeric_units,
            "jv_gross_sales_value_hkd": jv_value,
            "jv_gross_sales_units": jv_units,
            "unknown_gross_sales_value_hkd": _sum_or_zero(unknown["sales_value_gross_hkd"]),
            "unknown_gross_sales_units": _sum_or_zero(unknown["sales_units_gross"]),
            "latest_active_units_eom": pd.to_numeric(pd.Series([latest.get("active_units_eom")]), errors="coerce").iloc[0],
        }
        for scenario, share in shares.items():
            row[f"jv_{scenario}_share_pct"] = share * 100.0
            row[f"estimated_total_{scenario}_sales_value_hkd"] = numeric_value + jv_value * share
            row[f"estimated_total_{scenario}_sales_units"] = numeric_units + jv_units * share
        rows.append(row)
    return pd.DataFrame(rows)


def build_shkp_indicative_sales_model_phase_summary(
    indicative_signals: pd.DataFrame,
    *,
    jv_scenario_shares: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    frame = _normalise_signals(indicative_signals)
    if frame.empty:
        return pd.DataFrame()
    return _phase_summary_base(frame, _validate_scenario_shares(jv_scenario_shares))


def build_shkp_indicative_sales_model_coverage(
    indicative_signals: pd.DataFrame,
    *,
    jv_scenario_shares: Mapping[str, float] | None = None,
) -> pd.DataFrame:
    """Return one auditable coverage/assumption row for the model run."""
    frame = _normalise_signals(indicative_signals)
    shares = _validate_scenario_shares(jv_scenario_shares)
    if frame.empty:
        return pd.DataFrame([{
            "status": "empty_input",
            "input_rows": 0,
            "input_phases": 0,
            "jv_low_share_pct": shares["low"] * 100.0,
            "jv_base_share_pct": shares["base"] * 100.0,
            "jv_high_share_pct": shares["high"] * 100.0,
            "model_use": "indicative_contract_activity_proxy",
            "research_only": True,
        }])
    covered = frame[frame["month_status"].ne(_NOT_COVERED)]
    numeric = covered[covered["indicative_attribution_status"].eq(_NUMERIC_STATUS)]
    jv = covered[covered["indicative_attribution_status"].eq(_JV_STATUS)]
    unknown = covered[~covered["indicative_attribution_status"].isin({_NUMERIC_STATUS, _JV_STATUS})]
    return pd.DataFrame([{
        "status": "valid_research_only",
        "input_rows": int(len(frame)),
        "input_phases": int(frame["phase_id"].nunique()),
        "covered_rows": int(len(covered)),
        "not_covered_rows": int(len(frame) - len(covered)),
        "numeric_stake_rows": int(len(numeric)),
        "numeric_stake_phases": int(numeric["phase_id"].nunique()),
        "jv_rows": int(len(jv)),
        "jv_phases": int(jv["phase_id"].nunique()),
        "unknown_rows": int(len(unknown)),
        "unknown_phases": int(unknown["phase_id"].nunique()),
        "numeric_gross_value_hkd": _sum_or_zero(numeric["sales_value_gross_hkd"]),
        "numeric_stake_gross_value_hkd": _sum_or_zero(numeric["indicative_sales_value_hkd"]),
        "jv_gross_value_hkd": _sum_or_zero(jv["sales_value_gross_hkd"]),
        "unknown_gross_value_hkd": _sum_or_zero(unknown["sales_value_gross_hkd"]),
        "jv_low_share_pct": shares["low"] * 100.0,
        "jv_base_share_pct": shares["base"] * 100.0,
        "jv_high_share_pct": shares["high"] * 100.0,
        "date_min": frame["period"].min().strftime("%Y-%m-%d"),
        "date_max": frame["period"].max().strftime("%Y-%m-%d"),
        "model_use": "indicative_contract_activity_proxy",
        "research_only": True,
        "strict_ownership_promotion": False,
        "caveat": (
            "Gross SRPE contract activity can include contract updates/resales and is not recognised revenue. "
            "Numeric stakes are indicative snapshots; JV shares are mechanical sensitivities; not-covered tails "
            "and unknown identity rows are not imputed."
        ),
    }])


def run_shkp_indicative_sales_model(
    *,
    jv_scenario_shares: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Build and persist the indicative monthly, scenario, phase and audit outputs."""
    shares = _validate_scenario_shares(jv_scenario_shares)
    signal_source_dataset = ALL_HISTORY_INDICATIVE_SIGNAL_DATASET
    signals = load_latest_normalized(signal_source_dataset)
    if signals.empty:
        signal_source_dataset = INDICATIVE_SIGNAL_DATASET
        signals = load_latest_normalized(signal_source_dataset)
    if signals.empty:
        raise RuntimeError(
            "indicative project-month signals are missing; run run-shkp-indicative-signals first"
        )
    monthly = build_shkp_indicative_sales_model_monthly(
        signals,
        jv_scenario_shares=shares,
    )
    scenarios = build_shkp_indicative_sales_model_scenarios(
        monthly,
        jv_scenario_shares=shares,
    )
    annual = build_shkp_indicative_sales_model_annual(monthly)
    backtest = build_shkp_indicative_sales_model_backtest(
        monthly,
        universe_phase_count=int(signals["phase_id"].nunique()) if "phase_id" in signals.columns else None,
    )
    disclosed_facts = build_shkp_disclosed_financial_facts()
    validation = build_shkp_indicative_sales_model_validation(monthly, disclosed_facts)
    quarterly_reconciliation = build_shkp_indicative_sales_model_quarterly_reconciliation(
        monthly,
        load_latest_normalized("shkp_quarterly_numeric_facts"),
    )
    historical_reconciliation = build_shkp_indicative_sales_model_historical_reconciliation(
        monthly,
        disclosed_facts=disclosed_facts,
        quarterly_facts=load_latest_normalized("shkp_quarterly_numeric_facts"),
        signals=signals,
        hk_segment_history=load_latest_normalized("shkp_financial_model_hk_property_sales_segment_history"),
    )
    forecast = build_shkp_indicative_sales_model_forecast(
        monthly,
        disclosed_facts=disclosed_facts,
        jv_scenario_shares=shares,
    )
    project_coverage = build_shkp_active_future_project_coverage(
        property_catalog=load_latest_normalized("shkp_property_catalog"),
        crosswalk=load_latest_normalized("shkp_srpe_crosswalk"),
        phase_candidates=load_latest_normalized("shkp_srpe_phase_candidates"),
        current_manifest=load_latest_normalized("shkp_current_srpe_document_manifest_backfill"),
        pipeline_disclosures=load_latest_normalized("shkp_pipeline_disclosures"),
        pipeline_resolution=load_latest_normalized("shkp_future_project_resolution_plan"),
        future_identity_evidence=load_latest_normalized("shkp_future_project_identity_evidence"),
        indicative_signals=signals,
    )
    phase_summary = build_shkp_indicative_sales_model_phase_summary(
        signals,
        jv_scenario_shares=shares,
    )
    coverage = build_shkp_indicative_sales_model_coverage(
        signals,
        jv_scenario_shares=shares,
    )
    universe_coverage = build_shkp_indicative_sales_model_universe_coverage(
        load_latest_normalized("shkp_high_recall_phase_candidates"),
        signals,
        load_latest_normalized("shkp_srpe_project_transaction_events_dedup"),
    )
    run_id = f"shkp-indicative-sales-model-{uuid.uuid4()}"
    lineage = {
        "lineage_type": "shkp_indicative_sales_growth_model",
        "source_datasets": [signal_source_dataset],
        "jv_scenario_shares": shares,
        "indicative_only": True,
        "strict_ownership_promotion": False,
        "model_semantics": "monthly gross SRPE contract-activity proxy with numeric stake and JV sensitivity split",
    }
    normalized = {
        MONTHLY_DATASET: save_normalized_dataset(MONTHLY_DATASET, monthly, run_id=run_id, lineage_metadata=lineage),
        SCENARIO_DATASET: save_normalized_dataset(SCENARIO_DATASET, scenarios, run_id=run_id, lineage_metadata=lineage),
        ANNUAL_DATASET: save_normalized_dataset(ANNUAL_DATASET, annual, run_id=run_id, lineage_metadata=lineage),
        BACKTEST_DATASET: save_normalized_dataset(BACKTEST_DATASET, backtest, run_id=run_id, lineage_metadata=lineage),
        VALIDATION_DATASET: save_normalized_dataset(VALIDATION_DATASET, validation, run_id=run_id, lineage_metadata=lineage),
        QUARTERLY_RECONCILIATION_DATASET: save_normalized_dataset(
            QUARTERLY_RECONCILIATION_DATASET,
            quarterly_reconciliation,
            run_id=run_id,
            lineage_metadata=lineage,
        ),
        HISTORICAL_RECONCILIATION_DATASET: save_normalized_dataset(
            HISTORICAL_RECONCILIATION_DATASET,
            historical_reconciliation,
            run_id=run_id,
            lineage_metadata=lineage,
        ),
        UNIVERSE_COVERAGE_DATASET: save_normalized_dataset(
            UNIVERSE_COVERAGE_DATASET,
            universe_coverage,
            run_id=run_id,
            lineage_metadata=lineage,
        ),
        FORECAST_DATASET: save_normalized_dataset(FORECAST_DATASET, forecast, run_id=run_id, lineage_metadata=lineage),
        PROJECT_COVERAGE_DATASET: save_normalized_dataset(PROJECT_COVERAGE_DATASET, project_coverage, run_id=run_id, lineage_metadata=lineage),
        PHASE_DATASET: save_normalized_dataset(PHASE_DATASET, phase_summary, run_id=run_id, lineage_metadata=lineage),
        COVERAGE_DATASET: save_normalized_dataset(COVERAGE_DATASET, coverage, run_id=run_id, lineage_metadata=lineage),
    }
    return {
        "run_id": run_id,
        "monthly_rows": int(len(monthly)),
        "scenario_rows": int(len(scenarios)),
        "annual_rows": int(len(annual)),
        "backtest_rows": int(len(backtest)),
        "validation_rows": int(len(validation)),
        "quarterly_reconciliation_rows": int(len(quarterly_reconciliation)),
        "historical_reconciliation_rows": int(len(historical_reconciliation)),
        "universe_coverage_rows": int(len(universe_coverage)),
        "forecast_rows": int(len(forecast)),
        "project_coverage_rows": int(len(project_coverage)),
        "phase_rows": int(len(phase_summary)),
        "input_rows": int(len(signals)),
        "input_phases": int(signals["phase_id"].nunique()),
        "jv_scenario_shares": shares,
        "normalized": normalized,
        "strict_ownership_promotion": False,
    }
